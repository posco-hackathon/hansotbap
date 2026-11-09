"""F2 판정 결과 저장·조회: 새로고침해도 남는지, 권한으로 걸리는지, 재판정에서 해소로 바뀌는지."""

from conftest import s1_xlsx
from fastapi.testclient import TestClient

from db.database import session
from main import app

client = TestClient(app)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# S1 핵심 장면: 앞당긴 질소·가스 라인 연결(P34)이 노 내부 작업 두 건보다 먼저 시작한다
# P21 풍구 레벨 내화물(2/25 종료) / P22 노복~노흉 축조(3/2 종료) — 둘 다 P34의 선행 작업이다
# 판정은 일정 전체를 보므로 기본 일정의 다른 충돌(R16·R18 등)도 함께 저장된다. 여기서는 S1 순서 위반만 따라간다
S1_CONFLICTS = {"R08:P21>P34", "R08:P22>P34"}
P22_CONFLICT = "R08:P22>P34"


def s1_ids(records: list[dict]) -> set[str]:
    return {r["conflict"]["id"] for r in records} & S1_CONFLICTS


def ids(records: list[dict]) -> set[str]:
    return {r["conflict"]["id"] for r in records}


def one(records: list[dict], conflict_id: str) -> dict:
    return next(r for r in records if r["conflict"]["id"] == conflict_id)


def submit_s1() -> dict:
    """배관 협력사가 P34를 노 내부 작업 완료 전으로 앞당긴 계획서를 올리고 제출한다."""
    ext = client.post("/api/plans", files={"file": ("배관O_수정.xlsx", s1_xlsx(), XLSX)}).json()
    res = client.post(
        "/api/plans/submit",
        json={
            "contractor": "가상-배관O",
            "file": ext["file"],
            "tasks": [t["task"] for t in ext["tasks"]],
            "submitted_by": "배관O 현장소장",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_no_conflicts_before_any_submission():
    """판정은 제출 순간에만 돈다. 아무도 올리지 않았으면 저장된 충돌도 없다."""
    assert client.get("/api/conflicts").json() == []


def test_submit_persists_conflict_so_refresh_keeps_it():
    out = submit_s1()
    assert {c["id"] for c in out["conflicts"] if c["rule_id"] == "R08"} == S1_CONFLICTS

    # 제출 응답을 버리고 다시 조회해도(= 판정 후 화면 강제 새로고침) 남아 있다
    records = client.get("/api/conflicts").json()
    assert s1_ids(records) == S1_CONFLICTS
    rec = one(records, P22_CONFLICT)
    assert rec["status"] == "open" and rec["resolved_at"] is None
    assert rec["plan_id"] == out["plan"]["id"] and rec["judged_at"]
    assert rec["conflict"]["rule_id"] == "R08" and rec["conflict"]["legal_basis"]


def test_contractor_sees_only_conflicts_on_own_tasks():
    submit_s1()
    assert client.post(
        "/api/shares", json={"conflict_ids": list(ids(client.get("/api/conflicts").json())), "shared_by": "원청 담당자"}
    ).status_code == 200  # 협력사에게는 원청이 확인해 공유한 뒤에 보인다
    # 배관O(P34)와 축로I(P21·P22) 양쪽에 보인다 — 혼재작업 조정에 두 업체가 다 필요하다
    assert s1_ids(client.get("/api/conflicts", params={"contractor": "가상-배관O"}).json()) == S1_CONFLICTS
    assert s1_ids(client.get("/api/conflicts", params={"contractor": "가상-축로I"}).json()) == S1_CONFLICTS
    # 무관한 업체는 S1 충돌을 못 보고, 자기 작업이 걸린 충돌만 본다 (권한은 서버에서 거른다)
    others = client.get("/api/conflicts", params={"contractor": "가상-기계J"}).json()
    assert s1_ids(others) == set()
    own = {t["id"] for t in client.get("/api/tasks").json() if t["contractor"] == "가상-기계J"}
    assert all(own & set(r["conflict"]["task_ids"]) for r in others)


def test_rejudge_marks_vanished_conflicts_resolved():
    submit_s1()
    # 조정안 적용 = 수정 계획서 재제출. P34를 노 내부 작업 완료(2027-03-02) 뒤로 되돌린다
    p34 = next(t for t in client.get("/api/tasks").json() if t["id"] == "P34") | {
        "start": "2027-03-04T07:00:00",
        "end": "2027-03-12T19:00:00",
    }
    res = client.post(
        "/api/plans/submit", json={"contractor": "가상-배관O", "file": "배관O_조정판.xlsx", "tasks": [p34]}
    )
    assert not {c["id"] for c in res.json()["conflicts"]} & S1_CONFLICTS

    assert s1_ids(client.get("/api/conflicts").json()) == set()  # 기본 조회에서는 빠진다
    history = client.get("/api/conflicts", params={"include_resolved": "true"}).json()
    assert s1_ids(history) == S1_CONFLICTS  # 없어졌다는 사실은 F5 이행 기록으로 남는다
    assert all(r["status"] == "resolved" and r["resolved_at"] for r in history if r["conflict"]["id"] in S1_CONFLICTS)


def test_plan_id_keeps_the_submission_that_revealed_it():
    """plan_id 는 충돌을 처음 드러낸 제출이다. 원청 화면의 '최근 제출이 만든 것만' 필터가 이 값으로 거른다."""
    first = submit_s1()["plan"]["id"]
    again = submit_s1()["plan"]["id"]  # 같은 계획 재제출 → 같은 충돌이 그대로 남는다
    assert again != first
    assert one(client.get("/api/conflicts").json(), P22_CONFLICT)["plan_id"] == first

    # 해소됐다가 다시 나타나면 다시 드러낸 제출로 바뀐다
    p34 = next(t for t in client.get("/api/tasks").json() if t["id"] == "P34") | {
        "start": "2027-03-04T07:00:00",
        "end": "2027-03-12T19:00:00",
    }
    client.post("/api/plans/submit", json={"contractor": "가상-배관O", "file": "배관O_조정판.xlsx", "tasks": [p34]})
    assert P22_CONFLICT not in ids(client.get("/api/conflicts").json())
    back = submit_s1()["plan"]["id"]
    assert one(client.get("/api/conflicts").json(), P22_CONFLICT)["plan_id"] == back


def test_adjusted_status_survives_rejudge():
    """사람이 적용한 조정(adjusted)은 재판정이 open 으로 되돌리지 않는다."""
    submit_s1()
    with session() as conn:
        conn.execute("UPDATE conflicts SET status = 'adjusted' WHERE id = ?", (P22_CONFLICT,))
    submit_s1()  # 같은 계획을 다시 제출 → 같은 충돌이 다시 나온다
    records = client.get("/api/conflicts").json()
    assert one(records, P22_CONFLICT)["status"] == "adjusted"
    assert one(records, "R08:P21>P34")["status"] == "open"
