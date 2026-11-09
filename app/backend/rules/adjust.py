"""F4 조정안 계산·적용·재판정·전후 비교. LLM을 쓰지 않는다. pytest로 검증한다.

흐름: 충돌 → propose_adjustments(후보 계산, 가상 적용 재판정) → make_adjustment(원청이 고르면 기록)
      → recheck(원본 + 조정 기록을 합쳐 다시 판정) → diff_conflicts(사라짐 / 새로 생김 / 등급 바뀜)

협력사가 낸 원본 계획서(tasks)는 바꾸지 않는다. 조정은 Adjustment 기록으로 따로 두고 판정할 때 얹는다.
이유 문장은 규칙 CSV의 '조정안' 문구로 만든 결정적 문장이다. 나중에 LLM이 다듬을 수 있지만 판정과 후보 계산에는 쓰지 않는다.
"""

from datetime import datetime, timedelta

from rules.data_loader import DEFAULT_DAY_START
from rules.engine import detect_conflicts
from schemas import (
    Adjustment,
    AdjustmentCandidate,
    AdjustmentKind,
    Conflict,
    ConflictDiff,
    ConflictGradeChange,
    ConflictType,
    Rule,
    Task,
    Zone,
)

# 새 충돌이 없는 이동일을 찾을 때 하루씩 늦춰 보는 최대 일수 [팀 설정값]
MAX_SHIFT_DAYS = 60


def propose_adjustments(
    conflict: Conflict, tasks: list[Task], zones: list[Zone], rules: list[Rule]
) -> list[AdjustmentCandidate]:
    """순서 위반(후행 작업 B가 선행 작업 A보다 먼저 시작)을 푸는 일정 이동 후보를 계산한다.

    B를 "B를 막고 있는 모든 선행 작업이 끝난 다음 날 07시"부터 기간을 유지한 채 옮긴다. 거기서부터 하루씩 늦춰
    가며 전체를 다시 판정해, 새 충돌이 없는 가장 이른 날을 고른다. 한계(MAX_SHIFT_DAYS) 안에 없으면 가장 이른
    후보를 new_conflict_ids와 함께 그대로 보여 준다(걸러 내지 않는다). 순서 위반이 아니면 후보가 없다.
    """
    if conflict.type != ConflictType.SEQUENCE:
        return []

    by_id = {t.id: t for t in tasks}
    b = by_id[conflict.task_ids[1]]
    before = detect_conflicts(tasks, zones, rules)
    before_ids = {c.id for c in before}

    # B를 막고 있는 선행 작업: 이 충돌의 선행 작업 + B가 걸린 다른 순서 위반의 선행 작업
    blocker_ids = {conflict.task_ids[0]} | {
        c.task_ids[0] for c in before if c.type == ConflictType.SEQUENCE and c.task_ids[1] == b.id
    }
    blockers = [by_id[i] for i in sorted(blocker_ids)]
    latest_end = max(a.end for a in blockers)
    first_start = datetime.combine(latest_end.date() + timedelta(days=1), DEFAULT_DAY_START)
    duration = b.end - b.start

    picked: tuple[datetime, datetime, list[str]] | None = None
    fallback: tuple[datetime, datetime, list[str]] | None = None
    for shift in range(MAX_SHIFT_DAYS + 1):
        new_start = first_start + timedelta(days=shift)
        new_end = new_start + duration
        moved = [t.model_copy(update={"start": new_start, "end": new_end}) if t.id == b.id else t for t in tasks]
        after_ids = {c.id for c in detect_conflicts(moved, zones, rules)}
        if conflict.id in after_ids:
            continue  # 이 이동으로 원래 충돌이 안 풀리면 후보가 아니다
        new_ids = sorted(after_ids - before_ids)
        if fallback is None:
            fallback = (new_start, new_end, new_ids)
        if not new_ids:
            picked = (new_start, new_end, new_ids)
            break
    chosen = picked or fallback
    if chosen is None:
        return []
    new_start, new_end, new_ids = chosen

    successors = sorted(t.id for t in tasks if b.id in t.predecessors and t.start < new_end)
    rule = next((r for r in rules if r.id == conflict.rule_id), None)
    reason = (
        f"{b.name}({b.id})을(를) {new_start:%Y-%m-%d}로 옮겨, 선행 작업 {', '.join(a.id for a in blockers)}이(가) "
        f"모두 끝난({latest_end:%Y-%m-%d}) 뒤에 시작하게 합니다."
    )
    if rule:
        reason += f" 규칙 {rule.id} 조정안: {rule.adjustment}."
    if successors:
        reason += (
            f" 옮기면 {', '.join(successors)}의 시작이 {b.id}의 새 종료({new_end:%Y-%m-%d})보다 앞서게 되어 "
            "일정 확인이 필요합니다."
        )
    if new_ids:
        reason += f" 새 충돌 {len(new_ids)}건이 생깁니다."

    return [
        AdjustmentCandidate(
            id=f"{conflict.id}:shift:{new_start:%Y%m%d}",
            kind=AdjustmentKind.RESCHEDULE,
            task_id=b.id,
            conflict_id=conflict.id,
            original_start=b.start,
            original_end=b.end,
            new_start=new_start,
            new_end=new_end,
            reason=reason,
            resolves=True,
            new_conflict_ids=new_ids,
            affected_successors=successors,
        )
    ]


def make_adjustment(candidate: AdjustmentCandidate, decided_by: str, decided_at: datetime) -> Adjustment:
    """원청 담당자가 고른 후보를 조정 기록으로 만든다 (누가·언제·무엇을 바꿨는지)."""
    return Adjustment(
        id=f"ADJ-{candidate.id}",
        kind=candidate.kind,
        task_id=candidate.task_id,
        conflict_id=candidate.conflict_id,
        original_start=candidate.original_start,
        original_end=candidate.original_end,
        new_start=candidate.new_start,
        new_end=candidate.new_end,
        reason=candidate.reason,
        decided_by=decided_by,
        decided_at=decided_at,
    )


def apply_adjustments(tasks: list[Task], adjustments: list[Adjustment]) -> list[Task]:
    """원본 위에 조정 기록을 얹은 복사본을 돌려준다. 입력 tasks는 바꾸지 않는다. 같은 작업의 기록이 여럿이면 뒤의 것이 이긴다."""
    latest = {adj.task_id: adj for adj in adjustments}
    out: list[Task] = []
    for t in tasks:
        adj = latest.get(t.id)
        update = {"start": adj.new_start, "end": adj.new_end} if adj else {}
        out.append(t.model_copy(update=update, deep=True))
    return out


def recheck(
    tasks: list[Task], adjustments: list[Adjustment], zones: list[Zone], rules: list[Rule]
) -> list[Conflict]:
    """원본 + 조정 기록을 합쳐 다시 판정한다."""
    return detect_conflicts(apply_adjustments(tasks, adjustments), zones, rules)


def diff_conflicts(before: list[Conflict], after: list[Conflict]) -> ConflictDiff:
    """조정 전후 충돌을 Conflict.id 기준으로 비교한다."""
    b = {c.id: c for c in before}
    a = {c.id: c for c in after}
    return ConflictDiff(
        resolved=[b[i] for i in b if i not in a],
        introduced=[a[i] for i in a if i not in b],
        grade_changed=[
            ConflictGradeChange(conflict_id=i, before=b[i].grade, after=a[i].grade)
            for i in b
            if i in a and b[i].grade != a[i].grade
        ],
    )
