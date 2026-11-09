"""F4 조정안·재판정 시험. 시연 핵심 장면 S1: P34 앞당김 → 순서 위반 → 조정안 적용 → 해소."""

import inspect
from datetime import datetime

from rules import adjust
from rules.adjust import apply_adjustments, diff_conflicts, make_adjustment, propose_adjustments, recheck
from rules.data_loader import load_rules, load_wbs_tasks, load_zones
from rules.engine import detect_conflicts
from schemas import AdjustmentKind, Conflict, ConflictType, Grade

D105 = datetime(2027, 2, 25, 7)  # S1: P34를 앞당긴 날 (P22 ~03-02 19시, P21 ~02-25 19시가 아직 안 끝남)
D111 = datetime(2027, 3, 3, 7)  # 모든 선행 작업이 끝난 다음 날 07시
P34_NEW_END = datetime(2027, 3, 18, 19)  # 기간(15일 12시간)을 유지한 새 종료
DECIDED_AT = datetime(2026, 11, 12, 9)


def _s1_tasks():
    return [t.model_copy(update={"start": D105}) if t.id == "P34" else t for t in load_wbs_tasks()]


def _conflict(cid: str, grade: Grade = Grade.PROHIBITED, type_: ConflictType = ConflictType.SEQUENCE) -> Conflict:
    return Conflict(
        id=cid, type=type_, grade=grade, task_ids=["A", "B"], rule_id="R08", legal_basis="x",
        window_start=D105, window_end=D111, reason="x",
    )


def test_s1_full_flow_conflict_disappears_after_applying_adjustment():
    tasks, zones, rules = _s1_tasks(), load_zones(), load_rules()
    before = detect_conflicts(tasks, zones, rules)
    assert [c.id for c in before] == ["R08:P21>P34", "R08:P22>P34"]

    candidates = propose_adjustments(before[1], tasks, zones, rules)
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.kind == AdjustmentKind.RESCHEDULE
    assert cand.task_id == "P34"
    assert cand.new_start == D111  # P22(03-02)가 끝난 다음 날 07시. P21도 함께 풀리는 가장 늦은 선행 기준
    assert cand.new_end == P34_NEW_END  # 기간 유지
    assert cand.original_start == D105
    assert cand.resolves is True
    assert cand.new_conflict_ids == []
    assert cand.affected_successors == ["P36"]  # P36 코크스 충전(03-12 시작)이 P34 새 종료(03-18)보다 앞섬
    assert "P22" in cand.reason and "완료" in cand.reason

    adj = make_adjustment(cand, decided_by="원청 담당자", decided_at=DECIDED_AT)
    after = recheck(tasks, [adj], zones, rules)
    assert after == []

    diff = diff_conflicts(before, after)
    assert [c.id for c in diff.resolved] == ["R08:P21>P34", "R08:P22>P34"]
    assert diff.introduced == [] and diff.grade_changed == []


def test_adjustment_record_keeps_who_when_and_original_values():
    tasks, zones, rules = _s1_tasks(), load_zones(), load_rules()
    conflict = detect_conflicts(tasks, zones, rules)[1]
    cand = propose_adjustments(conflict, tasks, zones, rules)[0]
    adj = make_adjustment(cand, decided_by="원청 담당자", decided_at=DECIDED_AT)
    assert (adj.decided_by, adj.decided_at) == ("원청 담당자", DECIDED_AT)
    assert (adj.original_start, adj.new_start) == (D105, D111)
    assert adj.conflict_id == conflict.id


def test_apply_adjustments_does_not_change_original_plan():
    tasks, zones, rules = _s1_tasks(), load_zones(), load_rules()
    conflict = detect_conflicts(tasks, zones, rules)[1]
    adj = make_adjustment(propose_adjustments(conflict, tasks, zones, rules)[0], "원청 담당자", DECIDED_AT)

    adjusted = apply_adjustments(tasks, [adj])

    by_id = {t.id: t for t in tasks}
    assert by_id["P34"].start == D105  # 협력사가 낸 원본은 그대로
    assert {t.id: t for t in adjusted}["P34"].start == D111
    assert adjusted[0] is not tasks[0]  # 복사본이다
    # 조정 기록을 빼면(되돌리기) 원래 충돌이 다시 나온다
    assert [c.id for c in recheck(tasks, [], load_zones(), load_rules())] == ["R08:P21>P34", "R08:P22>P34"]


def test_no_candidate_for_non_sequence_conflict():
    tasks, zones, rules = _s1_tasks(), load_zones(), load_rules()
    assert propose_adjustments(_conflict("X", type_=ConflictType.VERTICAL), tasks, zones, rules) == []


def test_picks_earliest_shift_without_new_conflicts(monkeypatch):
    # 첫 이동일(D111)이 새 충돌을 만들면 건너뛰고 새 충돌이 없는 가장 이른 날(D112)을 고른다
    real = adjust.detect_conflicts

    def fake(tasks, zones, rules):
        out = real(tasks, zones, rules)
        p34 = next(t for t in tasks if t.id == "P34")
        if p34.start == D111:
            out.append(_conflict("NEW:1"))
        return out

    monkeypatch.setattr(adjust, "detect_conflicts", fake)
    tasks, zones, rules = _s1_tasks(), load_zones(), load_rules()
    conflict = real(tasks, zones, rules)[1]
    cand = propose_adjustments(conflict, tasks, zones, rules)[0]
    assert cand.new_start == datetime(2027, 3, 4, 7)
    assert cand.new_conflict_ids == []


def test_shows_earliest_candidate_with_new_conflicts_when_none_is_clean(monkeypatch):
    real = adjust.detect_conflicts

    def fake(tasks, zones, rules):
        out = real(tasks, zones, rules)
        p34 = next(t for t in tasks if t.id == "P34")
        if p34.start >= D111:
            out.append(_conflict("NEW:1"))
        return out

    monkeypatch.setattr(adjust, "detect_conflicts", fake)
    tasks, zones, rules = _s1_tasks(), load_zones(), load_rules()
    conflict = real(tasks, zones, rules)[1]
    cand = propose_adjustments(conflict, tasks, zones, rules)[0]
    assert cand.new_start == D111  # 걸러 내지 않고 가장 이른 후보를 보여 준다
    assert cand.new_conflict_ids == ["NEW:1"]
    assert "새 충돌 1건" in cand.reason


def test_diff_reports_resolved_introduced_and_grade_changed():
    before = [_conflict("a"), _conflict("b", Grade.PROHIBITED)]
    after = [_conflict("b", Grade.CONDITIONAL), _conflict("c")]
    diff = diff_conflicts(before, after)
    assert [c.id for c in diff.resolved] == ["a"]
    assert [c.id for c in diff.introduced] == ["c"]
    assert [(g.conflict_id, g.before, g.after) for g in diff.grade_changed] == [("b", Grade.PROHIBITED, Grade.CONDITIONAL)]


def test_same_input_same_result_and_no_llm():
    tasks, zones, rules = _s1_tasks(), load_zones(), load_rules()
    conflict = detect_conflicts(tasks, zones, rules)[1]
    assert propose_adjustments(conflict, tasks, zones, rules) == propose_adjustments(conflict, tasks, zones, rules)
    source = inspect.getsource(adjust)
    assert "import llm" not in source and "from llm" not in source  # 판정·후보 계산은 규칙만
