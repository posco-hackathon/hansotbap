"""F2 충돌 판정 엔진 (담당: 백엔드·규칙). LLM을 쓰지 않는다. pytest로 검증한다.

입력: 작업 목록, 구역, 규칙(R01~R30)
출력: Conflict 목록 — 모든 판정에 rule_id, legal_basis(법 조문), sources(원문 문장)를 붙인다.

순서
1. 서로 다른 협력사 작업 쌍마다 공간 관계(rules/relations.py)와 시간 관계를 본다
2. 작업 성격(rules/activities.py)이 규칙 A/B 조건에 맞으면 충돌 → 같은 시간·구역 / 위아래 / 화기×가스
3. 선행 조건(predecessors)과 일정으로 순서 위반을 본다 (R08, 예: P34 질소 라인 연결이 P22 축조 완료 전)
   R13(출선 전 살수)·R23(통전 후 작업)도 순서 위반으로 본다
4. 같은 구역·같은 시간에 협력사 3곳 이상이면 혼재 경고(R30)
5. F8 표준서 필수 단계 누락을 '결함'으로 합친다 (sop_matches 를 넘기면)

규칙 CSV(data/conflict_rules.csv)는 판정 등급·근거·조정안 문구를 준다. 걸리는 조건은 사람이 쓴 문장이라
기계가 못 읽으므로, 규칙 ID마다 이 파일에 조건(PAIR_RULES)을 둔다.
R26~R29(단일 허가서 결함·허가 상호참조)는 허가서 정보가 있어야 하므로 판정하지 않는다.

전 구역(ALL) 작업은 실제 위치를 모른다. 그 작업이 규칙의 A(위험을 만드는 쪽)일 때만 어디서든 겹친다고 보고,
'조건부'로 낮춰 "실제 위치 확인"을 붙인다. B(영향받는 쪽)일 때는 판정하지 않는다 — 그렇지 않으면 전 구역 작업
하나가 모든 작업과 충돌로 잡혀 화면을 덮는다 [팀 설정값].
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import permutations
from typing import Literal

from rules import activities as act
from rules.data_loader import load_rules
from rules.overlap import ALL_ZONE, FURNACE_COLUMN, daily_overlap, minutes_on
from rules.relations import SYSTEMS, Rel, relate, zone_name
from schemas import Conflict, ConflictType, Grade, Hazard, Rule, SopMatch, SourceRef, Task, Zone

# R08 후행 작업(가스·냉각수·동력 라인 복구/연결·가스 투입)으로 보는 작업명 키워드.
# 작업 유형 태그에 '라인 연결'이 없어서 작업명으로 본다 [팀 설정값]
LINE_CONNECT_KEYWORDS = ("연결", "복구", "투입", "승온", "기밀", "퍼지")

# R08 선행 작업: 노 내부(수직 공동)와 설비 내부(열풍로·제진기·가스 배관) 밀폐공간 작업 [팀 설정값]
INSIDE_WORK_ZONES = FURNACE_COLUMN | {"STOVE", "GCP", "DOWNCOMER"}

# 모든 혼재작업 판정에 같이 붙는 원청 의무 조문
MIXED_WORK_LAW = "산업안전보건법 제64조 제1항 제7·8호(같은 장소 혼재작업 확인·조정)"

# R30 혼재 경고: 같은 구역·같은 시간 협력사 수 [팀 설정값, 규칙 CSV의 N=3]
MIXED_WORK_MIN_CONTRACTORS = 3

# R25 화기작업 종료 후 화재 감시 시간 (KOSHA A-G-14-2026 "최소 30분")
FIRE_WATCH = timedelta(minutes=30)


def grade_of(rule: Rule) -> Grade:
    """CSV '판정' 칸("금지 (순서 위반)", "조건부(…없으면 금지)" 등)을 등급 3종으로 바꾼다."""
    for prefix, grade in (("금지", Grade.PROHIBITED), ("조건부", Grade.CONDITIONAL), ("결함", Grade.DEFECT)):
        if rule.grade.startswith(prefix):
            return grade
    # R30 "경고(혼재)" 같은 값은 '참고' 등급을 정한 뒤에 처리한다
    raise ValueError(f"{rule.id}: 등급 3종으로 바꿀 수 없는 판정 값 {rule.grade!r}")


def legal_basis(rule: Rule) -> str:
    return f"{rule.basis} / {MIXED_WORK_LAW}" if rule.basis else MIXED_WORK_LAW


def _sources(*tasks: Task) -> list[SourceRef]:
    return [t.source for t in tasks if t.source]


# ── 공간 조건: 규칙 CSV '공간 관계' 칸 ─────────────────────────────────
Where = Callable[[Rel, Task, Task], bool]


def near(r: Rel, a: Task, b: Task) -> bool:
    """WITHIN 11m·작업반경·관리구역 → 같은 구역 또는 인접 구역 [팀 설정값]."""
    return r.same_zone or r.adjacent


def same_zone(r: Rel, a: Task, b: Task) -> bool:
    return r.same_zone


def adjacent_only(r: Rel, a: Task, b: Task) -> bool:
    """R06: 같은 설비가 아니라 인접 설비."""
    return r.adjacent


def a_above(r: Rel, a: Task, b: Task) -> bool:
    """VERTICAL: A가 위, B가 아래 (노 내부 수직 공동)."""
    return r.vertical and r.a_above


def above_or_same_zone(r: Rel, a: Task, b: Task) -> bool:
    """R03: A 아래 전부 (하부는 11m 초과 포함). 같은 구역(철피처럼 높은 면)도 아래가 있을 수 있다."""
    return r.same_zone or (r.vertical and r.a_above)


def around_or_below(r: Rel, a: Task, b: Task) -> bool:
    """VERTICAL / SAME_ZONE: 같은 구역·인접 구역이거나 A 아래."""
    return r.same_zone or r.adjacent or (r.vertical and r.a_above)


def same_system(r: Rel, a: Task, b: Task) -> bool:
    return r.same_zone or r.same_system


def near_or_gas_system(r: Rel, a: Task, b: Task) -> bool:
    """R04: 11m 이내 또는 가스 배관이 이어진 같은 가스 계통(노정·하강관·제진기)."""
    gas_zones = SYSTEMS["가스청정"]
    return near(r, a, b) or (a.zone_id in gas_zones and b.zone_id in gas_zones)


def blast_area(r: Rel, a: Task, b: Task) -> bool:
    """출선·발파 통제 범위: 같은 계통(노체) 전체와 인접 구역 [팀 설정값]."""
    return r.same_zone or r.adjacent or r.same_system


def top_area(r: Rel, a: Task, b: Task) -> bool:
    """R11: 방산 지점(노정·하강관)과 노정 작업."""
    return b.zone_id == "TOP" and (r.same_zone or r.adjacent)


# ── 규칙 표 ───────────────────────────────────────────────────────────
Timing = Literal["overlap", "b_before_a_done", "a_before_b_done", "b_after_a_within_watch"]


@dataclass(frozen=True)
class PairRule:
    id: str
    a: Callable[[Task], bool]
    b: Callable[[Task], bool]
    where: Where
    type: ConflictType | None = None  # None → 위아래 관계면 VERTICAL, 아니면 SAME_TIME_ZONE
    when: Timing = "overlap"


ST, VT, HG, SQ = ConflictType.SAME_TIME_ZONE, ConflictType.VERTICAL, ConflictType.HOT_GAS, ConflictType.SEQUENCE


def _upper_handling_not_scaffold(t: Task) -> bool:
    """R16 A. 비계 설치·해체는 R17이 따로 본다."""
    return act.upper_handling(t) and not act.scaffold(t)


# 같은 협력사 안의 작업끼리도 보는 규칙: 화재·폭발·질식처럼 한 번에 여럿이 다치는 조합 [팀 설정값]
SAME_CONTRACTOR_RULES = frozenset({"R01", "R02", "R04", "R05", "R06", "R07", "R13", "R23", "R25"})

PAIR_RULES: tuple[PairRule, ...] = (
    PairRule("R01", act.hot, act.flammable_use, near, HG),
    PairRule("R02", act.hot, act.combustible, near, HG),
    PairRule("R03", act.hot, act.anyone, above_or_same_zone, VT),
    PairRule("R04", act.hot, act.gas_opening, near_or_gas_system, HG),
    PairRule("R05", act.hot, act.confined, same_zone, HG),
    PairRule("R06", act.hot, act.confined, adjacent_only, HG),
    PairRule("R07", act.confined, act.gas_introduce, same_system, ST),
    PairRule("R09", act.inert_purge, act.opening_area, near, ST),
    PairRule("R10", act.gas_dismantle, act.anyone, same_zone, ST),
    PairRule("R11", act.bleeder, act.anyone, top_area, ST),
    PairRule("R12", act.salamander, act.anyone, blast_area, ST),
    PairRule("R13", act.salamander, act.quench, same_system, SQ, "b_before_a_done"),
    PairRule("R14", act.quench, act.anyone, around_or_below),
    PairRule("R15", act.blasting, act.anyone, blast_area, ST),
    PairRule("R16", _upper_handling_not_scaffold, act.anyone, a_above, VT),
    PairRule("R17", act.scaffold, act.anyone, around_or_below),
    PairRule("R18", act.crane_lift, act.anyone, around_or_below),
    PairRule("R19", act.crane_lift, act.crane_lift, near, ST),
    PairRule("R20", act.crane_lift, act.height, near, ST),
    PairRule("R21", act.vehicle, act.anyone, near, ST),
    PairRule("R22", act.trial_run, act.anyone, same_system, ST),
    PairRule("R23", act.energize, act.anyone, same_system, SQ, "a_before_b_done"),
    PairRule("R24", act.radiation, act.anyone, near, ST),
    PairRule("R25", act.hot, act.combustible, same_zone, HG, "b_after_a_within_watch"),
)


def _window(rule: PairRule, a: Task, b: Task) -> tuple[datetime, datetime] | None:
    if rule.when == "overlap":
        # 같은 시간: 날짜와 그날의 작업 시각대가 둘 다 겹칠 때만 (주간조·야간조, 오전·오후 작업은 겹치지 않는다)
        return daily_overlap(a.start, a.end, b.start, b.end)
    if rule.when == "b_before_a_done":  # B는 A 완료 뒤에 시작해야 한다
        return (b.start, max(b.start, min(a.end, b.end))) if b.start < a.end else None
    if rule.when == "a_before_b_done":  # A는 B가 모두 끝난 뒤에 해야 한다
        return (max(a.start, b.start), b.end) if a.start < b.end else None
    watch_end = a.end + FIRE_WATCH  # b_after_a_within_watch
    return (b.start, min(b.end, watch_end)) if a.end <= b.start < watch_end else None


def _fmt(w: tuple[datetime, datetime]) -> str:
    return f"{w[0]:%m/%d %H:%M}~{w[1]:%m/%d %H:%M}"


def _reason(rule: Rule, pr: PairRule, a: Task, b: Task, rel: Rel, w: tuple[datetime, datetime]) -> str:
    who_a = f"{a.contractor} '{a.name}'({a.id})"
    who_b = f"{b.contractor} '{b.name}'({b.id})"
    if pr.when == "b_before_a_done":
        head = f"{who_b}이(가) {who_a}이(가) 끝나는 {a.end:%m/%d %H:%M} 전({b.start:%m/%d %H:%M})에 시작합니다."
    elif pr.when == "a_before_b_done":
        head = f"{who_a}이(가) {who_b}이(가) 끝나는 {b.end:%m/%d %H:%M} 전({a.start:%m/%d %H:%M})에 시작합니다."
    elif pr.when == "b_after_a_within_watch":
        head = f"{who_a} 종료 후 화재 감시 30분 안({_fmt(w)})에 {who_b}이(가) 시작합니다."
    else:
        head = f"{who_a}과(와) {who_b}이(가) {_fmt(w)} {rel.label(a, b)}에서 겹칩니다."
    return f"{head} 규칙 {rule.id}: {rule.task_a} × {rule.task_b} → {rule.grade}."


def _all_zone_conflict(rule: Rule, pr: PairRule, a: Task, hits: list[tuple[Task, tuple[datetime, datetime]]]) -> Conflict:
    """전 구역 작업(A)과 겹칠 수 있는 작업들을 규칙마다 1건으로 묶는다. 위치를 정하면 개별 판정으로 바뀐다."""
    others = sorted({b.id: b for b, _ in hits}.values(), key=lambda t: t.id)
    start = min(w[0] for _, w in hits)
    end = max(w[1] for _, w in hits)
    listed = ", ".join(f"{b.name}({b.id})" for b in others[:6]) + (f" 외 {len(others) - 6}건" if len(others) > 6 else "")
    grade = grade_of(rule)
    return Conflict(
        id=f"{rule.id}:{a.id}>{ALL_ZONE}",
        type=pr.type or ST,
        grade=Grade.CONDITIONAL if grade == Grade.PROHIBITED else grade,
        task_ids=[a.id] + [b.id for b in others],
        rule_id=rule.id,
        legal_basis=legal_basis(rule),
        window_start=start,
        window_end=end,
        reason=(
            f"{a.contractor} '{a.name}'({a.id})은(는) 전 구역 작업이라 {_fmt((start, end))} 사이 작업 {len(others)}건과 "
            f"겹칠 수 있습니다: {listed}. 규칙 {rule.id}: {rule.task_a} × {rule.task_b} → {rule.grade}. "
            "실제 작업 위치(구역)를 계획서에 적으면 작업별로 다시 판정합니다."
        ),
        suggestion=f"{a.id}의 구역별 작업 위치·일정을 받아 다시 판정한다. {rule.adjustment}",
        sources=_sources(a, *others),
    )


def is_all_zone_conflict(conflict: Conflict) -> bool:
    return conflict.id.endswith(f">{ALL_ZONE}")


def scope_all_zone_conflict(conflict: Conflict, tasks: list[Task], viewer: str) -> Conflict:
    """협력사 화면용: 전 구역 묶음 충돌(…>ALL)을 '전 구역 작업 + 이 협력사의 작업'으로 좁혀 다시 만든다.

    묶음에는 전 구역 작업과 겹칠 수 있는 모든 업체의 작업이 들어 있다. 그대로 공유하면 협력사 한 곳이 전체 일정을
    받게 되므로, 협력사에게는 자기 작업과의 겹침만 준다(이유 문장·기간·근거도 그 범위로 다시 만든다).
    전 구역 작업을 낸 협력사에게는 묶음 전체가 자기 작업의 상대이므로 그대로 둔다.
    """
    if not is_all_zone_conflict(conflict):
        return conflict
    by_id = {t.id: t for t in tasks}
    a = by_id.get(conflict.task_ids[0])
    if a is None or a.contractor == viewer:
        return conflict
    mine = [by_id[t] for t in conflict.task_ids[1:] if t in by_id and by_id[t].contractor == viewer]
    rule = next((r for r in load_rules() if r.id == conflict.rule_id), None)
    pr = next((p for p in PAIR_RULES if p.id == conflict.rule_id), None)
    if not mine or rule is None or pr is None:  # 정상 판정 결과에서는 생기지 않는다. 생겨도 묶음 목록은 내보내지 않는다
        return conflict.model_copy(update={
            "task_ids": [a.id] + [t.id for t in mine],
            "reason": f"{a.contractor} '{a.name}'({a.id})은(는) 전 구역 작업이라 이 업체 작업과 겹칠 수 있습니다.",
            "sources": _sources(a, *mine),
        })
    # 판정 뒤 일정이 바뀌어 겹침이 사라졌으면 저장된 묶음 기간을 쓴다 (전체 묶음을 내보내지 않는다)
    fallback = (conflict.window_start, conflict.window_end)
    hits = [(m, _window(pr, a, m) or fallback) for m in mine]
    scoped = _all_zone_conflict(rule, pr, a, hits)
    return scoped.model_copy(update={"grade": conflict.grade, "type": conflict.type})


def detect_pair_rules(tasks: list[Task], rules: list[Rule]) -> list[Conflict]:
    """2·3단계: 작업 쌍에 R01~R25(R08 제외)를 적용한다. 기본은 서로 다른 협력사, 치명적 조합은 같은 협력사도."""
    by_id = {r.id: r for r in rules}
    active = [pr for pr in PAIR_RULES if pr.id in by_id]
    ordered = sorted(tasks, key=lambda t: t.id)
    seen: set[tuple[str, frozenset[str]]] = set()
    all_zone_hits: dict[tuple[str, str], list[tuple[Task, tuple[datetime, datetime]]]] = {}
    out: list[Conflict] = []
    for a, b in permutations(ordered, 2):
        same_contractor = a.contractor == b.contractor
        rel = relate(a, b)
        for pr in active:
            if same_contractor and pr.id not in SAME_CONTRACTOR_RULES:
                continue
            if not (pr.a(a) and pr.b(b)):
                continue
            via_all = False
            if not pr.where(rel, a, b):
                # 전 구역 작업은 A(위험을 만드는 쪽)일 때만, 위아래 방향을 따지지 않는 규칙에서만 겹친다고 본다
                if not (rel.all_zone and a.zone_id == ALL_ZONE and pr.where is not a_above):
                    continue
                via_all = True
            w = _window(pr, a, b)
            if w is None:
                continue
            if via_all:
                all_zone_hits.setdefault((pr.id, a.id), []).append((b, w))
                continue
            key = (pr.id, frozenset((a.id, b.id)))
            if key in seen:  # 두 작업이 서로 A·B 양쪽에 다 맞으면 한 번만
                continue
            seen.add(key)
            rule = by_id[pr.id]
            ctype = pr.type or (VT if rel.vertical and not rel.same_zone else ST)
            reason = _reason(rule, pr, a, b, rel, w)
            if same_contractor:
                reason += " 같은 협력사 안의 작업끼리도 함께 보는 조합입니다."
            out.append(
                Conflict(
                    id=f"{rule.id}:{a.id}>{b.id}",  # A>B. 전후 비교(F4)에서 같은 충돌을 알아보는 키
                    type=ctype,
                    grade=grade_of(rule),
                    task_ids=[a.id, b.id],
                    rule_id=rule.id,
                    legal_basis=legal_basis(rule),
                    window_start=w[0],
                    window_end=w[1],
                    reason=reason,
                    suggestion=rule.adjustment,
                    sources=_sources(a, b),
                )
            )
    pr_by_id = {pr.id: pr for pr in active}
    for (rule_id, a_id), hits in all_zone_hits.items():
        a = next(t for t in ordered if t.id == a_id)
        out.append(_all_zone_conflict(by_id[rule_id], pr_by_id[rule_id], a, hits))
    return out


def _simultaneous(members: list[Task], s: datetime, e: datetime) -> bool:
    """구간 s~e 의 가운데 날에 서로 다른 협력사 MIXED_WORK_MIN_CONTRACTORS 곳 이상이 같은 시각에 일하는가 (매일 시각대 기준)."""
    day = (s + (e - s) / 2).date()
    marks: list[tuple[int, int, str]] = []
    for t in members:
        for m0, m1 in minutes_on(t.start, t.end, day):
            marks += [(m0, 1, t.contractor), (m1, -1, t.contractor)]
    working: dict[str, int] = {}
    for _, step, who in sorted(marks, key=lambda m: (m[0], m[1])):  # 같은 분에는 끝(-1)을 먼저
        working[who] = working.get(who, 0) + step
        if sum(1 for n in working.values() if n > 0) >= MIXED_WORK_MIN_CONTRACTORS:
            return True
    return False


def detect_mixed_work(tasks: list[Task], rules: list[Rule]) -> list[Conflict]:
    """4단계 R30: 같은 구역·같은 시간에 서로 다른 협력사가 N곳 이상이면 혼재 경고.

    등급 3종에 '경고'가 없어 '조건부'(협의체 상정·조정 필요)로 낸다. 전 구역 작업은 세지 않는다.
    """
    rule = next((r for r in rules if r.id == "R30"), None)
    if rule is None:
        return []
    out: list[Conflict] = []
    zones = sorted({t.zone_id for t in tasks if t.zone_id and t.zone_id != ALL_ZONE})
    for zone in zones:
        in_zone = [t for t in tasks if t.zone_id == zone]
        cuts = sorted({x for t in in_zone for x in (t.start, t.end)})
        spans: list[tuple[datetime, datetime, tuple[str, ...]]] = []
        for s, e in zip(cuts, cuts[1:]):
            live = tuple(sorted(t.id for t in in_zone if t.start < e and s < t.end))
            if len({t.contractor for t in in_zone if t.id in live}) < MIXED_WORK_MIN_CONTRACTORS:
                continue
            # 기간이 겹쳐도 매일 시각대가 엇갈리면(주간조·야간조) 같이 일하지 않는다 → 같은 시각에 일하는 업체 수로 다시 센다
            if not _simultaneous([t for t in in_zone if t.id in live], s, e):
                continue
            if spans and spans[-1][2] == live and spans[-1][1] == s:
                spans[-1] = (spans[-1][0], e, live)
            else:
                spans.append((s, e, live))
        for s, e, live in spans:
            members = [t for t in in_zone if t.id in live]
            names = ", ".join(f"{t.contractor} {t.name}({t.id})" for t in members)
            out.append(
                Conflict(
                    id=f"{rule.id}:{zone}:{s:%Y%m%d%H%M}",
                    type=ST,
                    grade=Grade.CONDITIONAL,
                    task_ids=list(live),
                    rule_id=rule.id,
                    legal_basis=legal_basis(rule),
                    window_start=s,
                    window_end=e,
                    reason=(
                        f"{zone_name(zone)}에서 {_fmt((s, e))} 협력사 {len({t.contractor for t in members})}곳이 "
                        f"같이 작업합니다: {names}. 규칙 {rule.id}: {rule.grade}."
                    ),
                    suggestion=rule.adjustment,
                    sources=_sources(*members),
                )
            )
    return out


def defects_from_sop(tasks: list[Task], sop_matches: list[SopMatch]) -> list[Conflict]:
    """5단계: F8 작업표준서 필수 단계 누락 → '결함'."""
    by_id = {t.id: t for t in tasks}
    out: list[Conflict] = []
    for m in sop_matches:
        t = by_id.get(m.task_id)
        if t is None or not m.missing_steps:
            continue
        out.append(
            Conflict(
                id=f"SOP:{t.id}:{m.sop_id}",
                type=ConflictType.SOP_MISSING,
                grade=Grade.DEFECT,
                task_ids=[t.id],
                rule_id=f"SOP:{m.sop_id}",
                legal_basis="산업안전보건법 제65조(위험 작업 도급 시 안전·보건 정보 문서 제공) — 작업표준서 필수 단계",
                window_start=t.start,
                window_end=t.end,
                reason=f"{t.contractor} '{t.name}'({t.id}) 계획서에 작업표준서 '{m.title}'의 필수 단계가 없습니다: {', '.join(m.missing_steps)}.",
                suggestion="빠진 단계를 계획서 작업 절차에 넣어 다시 제출한다",
                # 계획서 위치 + 빠진 단계가 적힌 표준서 위치 (무엇이 빠졌는지 원본을 같이 본다)
                sources=_sources(t)
                + [
                    SourceRef(file=m.sop_id, locator=f"필수 단계 {s.no}", text=s.text)
                    for s in m.steps
                    if s.critical and not s.found
                ],
            )
        )
    return out


def detect_conflicts(
    tasks: list[Task],
    zones: list[Zone],
    rules: list[Rule],
    sop_matches: list[SopMatch] | None = None,
) -> list[Conflict]:
    """제출 판정과 조정안 재판정(F4)이 부르는 전체 판정. zones 는 호출 모양을 맞추려고 받는다 (구역 관계는 relations.py)."""
    found = (
        detect_pair_rules(tasks, rules)
        + detect_sequence_violations(tasks, rules)
        + detect_mixed_work(tasks, rules)
        + (defects_from_sop(tasks, sop_matches) if sop_matches else [])
    )
    unique: dict[str, Conflict] = {}
    for c in found:
        unique.setdefault(c.id, c)
    return sorted(unique.values(), key=lambda c: (c.window_start, c.id))


def _is_furnace_inside_work(t: Task) -> bool:
    """R08 A: 노 내부(수직 공동)·설비 내부(열풍로·제진기·가스 배관) 밀폐공간 작업."""
    return t.zone_id in INSIDE_WORK_ZONES and Hazard.CONFINED in t.hazards


def _is_line_connection(t: Task) -> bool:
    """R08 B: 가스 계통 라인 복구·연결·가스 투입 작업."""
    return Hazard.GAS in t.hazards and any(k in t.name for k in LINE_CONNECT_KEYWORDS)


def detect_sequence_violations(tasks: list[Task], rules: list[Rule] | None = None) -> list[Conflict]:
    """R08: 노 내부·설비 내부 작업(A)이 끝나기 전에 가스 라인 연결(B)이 시작하면 순서 위반.

    rules를 생략하면 data/conflict_rules.csv 의 규칙을 쓴다. 제출 판정(db/plans.py judge)이
    detect_sequence_violations(tasks) 로 부르기 때문이다.

    A는 B가 계획서에 적은 선행 작업(predecessors) 중에서만 본다. 데이터의 '선행 작업' 열은 느슨한 의존이라
    기본 일정에서도 선행보다 먼저 시작하는 쌍이 여럿(예: P01→P02) 있다. 규칙에 해당하는 쌍만 판정한다.
    끝과 시작이 같은 시각이면 위반이 아니고, A가 끝나는 날 B가 시작하면(07시 < 19시) 위반이다.
    """
    rules = load_rules() if rules is None else rules
    rule = next((r for r in rules if r.id == "R08"), None)
    if rule is None:
        return []
    by_id = {t.id: t for t in tasks}
    out: list[Conflict] = []
    for b in tasks:
        if not _is_line_connection(b):
            continue
        for a_id in b.predecessors:
            a = by_id.get(a_id)
            if a is None or not _is_furnace_inside_work(a) or b.start >= a.end:
                continue
            out.append(
                Conflict(
                    id=f"{rule.id}:{a.id}>{b.id}",  # 선행>후행. 전후 비교(F4)에서 같은 충돌을 알아보는 키
                    type=ConflictType.SEQUENCE,
                    grade=grade_of(rule),
                    task_ids=[a.id, b.id],
                    rule_id=rule.id,
                    legal_basis=legal_basis(rule),
                    window_start=b.start,
                    window_end=min(a.end, b.end),
                    reason=(
                        f"{b.name}({b.id})이(가) 선행 작업 {a.name}({a.id})이(가) 끝나는 {a.end:%Y-%m-%d} 전인 "
                        f"{b.start:%Y-%m-%d}에 시작합니다 (규칙 {rule.id}: 노 내부·설비 내부 작업이 끝나기 전 "
                        "가스·냉각수·동력 라인 연결 금지)."
                    ),
                    suggestion=rule.adjustment,
                    sources=_sources(a, b),
                )
            )
    return sorted(out, key=lambda c: (c.window_start, c.id))
