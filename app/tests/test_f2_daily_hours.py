"""F2 같은 시간 판정은 '매일 같은 시각대'로 본다.

F1은 여러 날 작업의 매일 작업 시각을 시작·종료 일시의 시각 부분에 담는다(야간 19:00~07:00 은 종료가 다음 날 07:00).
이를 이어진 한 구간으로 읽으면 같은 날짜의 주간조와 야간조, 오전·오후 작업이 겹친다고 잘못 나온다.
순서 위반(R08)처럼 '끝나기 전에 시작'을 보는 규칙은 날짜 기준 그대로다."""

from datetime import date, datetime

from rules.data_loader import load_rules, load_zones
from rules.engine import detect_conflicts
from rules.overlap import daily_overlap, minutes_on
from schemas import Hazard, Task


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def task(tid: str, contractor: str, name: str, start: str, end: str, zone: str = "TUYERE", hazards=()) -> Task:
    return Task(id=tid, contractor=contractor, name=name, zone_id=zone, start=dt(start), end=dt(end), hazards=list(hazards))


# ── 시간 계산 ──────────────────────────────────────────────────────────
def test_day_and_night_shift_on_same_dates_do_not_overlap():
    day = (dt("2027-02-26T07:00"), dt("2027-03-04T19:00"))
    night = (dt("2027-02-26T19:00"), dt("2027-03-05T07:00"))  # F1: 야간은 종료가 다음 날 07:00
    assert daily_overlap(*day, *night) is None


def test_morning_and_afternoon_jobs_do_not_overlap():
    am = (dt("2027-02-26T07:00"), dt("2027-03-04T12:00"))
    pm = (dt("2027-02-26T13:00"), dt("2027-03-04T19:00"))
    assert daily_overlap(*am, *pm) is None


def test_same_hours_overlap_from_first_to_last_shared_moment():
    a = (dt("2027-02-26T08:00"), dt("2027-03-04T17:00"))  # 배관 08~17시
    b = (dt("2027-02-05T07:00"), dt("2027-03-02T19:00"))  # 축조 07~19시
    assert daily_overlap(*a, *b) == (dt("2027-02-26T08:00"), dt("2027-03-02T17:00"))


def test_night_shifts_overlap_each_other():
    a = (dt("2027-02-26T19:00"), dt("2027-02-28T07:00"))
    b = (dt("2027-02-27T22:00"), dt("2027-03-01T06:00"))
    assert daily_overlap(*a, *b) == (dt("2027-02-27T22:00"), dt("2027-02-28T06:00"))  # b 는 매일 06시에 끝난다


def test_round_the_clock_task_overlaps_day_work():
    allday = (dt("2027-02-26T00:00"), dt("2027-03-01T00:00"))  # 시작=끝 시각 → 하루 종일
    day = (dt("2027-02-27T07:00"), dt("2027-02-27T19:00"))
    assert daily_overlap(*allday, *day) == (dt("2027-02-27T07:00"), dt("2027-02-27T19:00"))


def test_minutes_on_splits_night_shift_across_midnight():
    start, end = dt("2027-02-26T19:00"), dt("2027-02-28T07:00")
    assert minutes_on(start, end, date(2027, 2, 27)) == [(19 * 60, 24 * 60), (0, 7 * 60)]


# ── 판정 ───────────────────────────────────────────────────────────────
def judge(*tasks: Task):
    return detect_conflicts(list(tasks), load_zones(), load_rules())


def test_hot_work_and_gas_opening_conflict_only_in_the_same_hours():
    """같은 풍구 레벨에서 화기 작업과 가스 배관 개방: 같은 시각대면 화기×가스 충돌, 주간·야간으로 갈리면 없음."""
    hot = task("H1", "가상-가", "송풍지관 용접", "2027-02-26T07:00", "2027-03-04T19:00", hazards=[Hazard.HOT_WORK])
    gas_day = task("G1", "가상-나", "가스 배관 플랜지 해체", "2027-02-26T07:00", "2027-03-04T19:00", hazards=[Hazard.GAS])
    gas_night = gas_day.model_copy(update={"start": dt("2027-02-26T19:00"), "end": dt("2027-03-05T07:00")})

    together = [c for c in judge(hot, gas_day) if {"H1", "G1"} <= set(c.task_ids)]
    assert together, "같은 시각대면 충돌이 있어야 한다"
    assert not [c for c in judge(hot, gas_night) if {"H1", "G1"} <= set(c.task_ids)]


def test_mixed_work_counts_only_contractors_working_at_the_same_time():
    """R30 혼재: 같은 구역·같은 기간에 세 업체가 있어도, 한 곳이 야간조면 같은 시각에 일하는 곳은 둘 → 혼재 아님."""
    a = task("A1", "가상-가", "내화물 운반", "2027-02-26T07:00", "2027-03-04T19:00", zone="STACK")
    b = task("B1", "가상-나", "케이블 포설", "2027-02-26T07:00", "2027-03-04T19:00", zone="STACK")
    c_day = task("C1", "가상-다", "계측기 설치", "2027-02-26T07:00", "2027-03-04T19:00", zone="STACK")
    c_night = c_day.model_copy(update={"start": dt("2027-02-26T19:00"), "end": dt("2027-03-05T07:00")})

    assert [x for x in judge(a, b, c_day) if x.rule_id == "R30"]
    assert not [x for x in judge(a, b, c_night) if x.rule_id == "R30"]
