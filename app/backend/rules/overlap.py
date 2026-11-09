"""시간·공간 겹침 후보 찾기. 판정(금지·조건부·결함)은 하지 않는다 — 그건 engine.py 의 규칙이 한다.

작업의 시간: F1은 계획서의 기간과 작업 시간을 시작·종료 일시 두 값에 담는다. 여러 날 작업이면 '매일 같은 시각대'라는 뜻이다
(예: 2/26~3/4, 08:00~17:00 → 시작 2/26 08:00, 종료 3/4 17:00 / 야간 19:00~07:00 → 종료가 다음 날 07:00).
그래서 겹침은 두 구간을 이어진 하나로 보지 않고, 날짜와 그날의 작업 시각대가 둘 다 겹칠 때만 본다 (daily_overlap).
시작·종료 시각이 같으면(예: 00:00~00:00) 하루 종일 이어지는 작업으로 본다.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import combinations

from schemas import OverlapCandidate, Task, Zone

# 노 내부 수직 공동: 위아래 관계를 보는 구역 [팀 설정값, zones.csv 수직순서 기준]
FURNACE_COLUMN = {"TOP", "STACK", "BELLY_BOSH", "TUYERE", "HEARTH"}
ALL_ZONE = "ALL"


def time_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime):
    """두 구간이 겹치면 (시작, 끝)을, 아니면 None을 돌려준다. 끝이 맞닿기만 하면 겹침이 아니다."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return (start, end) if start < end else None


DAY_MIN = 24 * 60


@dataclass(frozen=True)
class Band:
    """같은 시각대가 여러 날 이어지는 묶음: d0~d1 날마다 그날 0시부터 m0분~m1분."""

    m0: int
    m1: int
    d0: date
    d1: date


def _minute(t: datetime) -> int:
    return t.hour * 60 + t.minute


def daily_bands(start: datetime, end: datetime) -> list[Band]:
    """작업 하나의 매일 시각대. 야간(끝 시각 < 시작 시각)은 그날 밤과 다음 날 새벽 두 묶음, 시작=끝 시각이면 하루 종일."""
    a0, a1 = _minute(start), _minute(end)
    s, e = start.date(), end.date()
    if a1 == a0:  # 하루 종일 이어지는 작업 — 첫날·마지막 날 일부는 daily_overlap 이 실제 시작·끝으로 자른다
        return [Band(0, DAY_MIN, s, e)]
    if a1 > a0:
        return [Band(a0, a1, s, e)]
    one = timedelta(days=1)
    return [Band(a0, DAY_MIN, s, e - one), Band(0, a1, s + one, e)]


def daily_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime):
    """두 작업이 실제로 같은 시각에 일하는 첫 순간~마지막 순간. 날짜는 겹쳐도 시각대가 안 겹치면(주간조·야간조) None."""
    span = time_overlap(a_start, a_end, b_start, b_end)
    if span is None:
        return None
    lo = hi = None
    for x in daily_bands(a_start, a_end):
        for y in daily_bands(b_start, b_end):
            m0, m1 = max(x.m0, y.m0), min(x.m1, y.m1)
            d0, d1 = max(x.d0, y.d0), min(x.d1, y.d1)
            if m0 >= m1 or d0 > d1:
                continue
            s = datetime.combine(d0, time()) + timedelta(minutes=m0)
            e = datetime.combine(d1, time()) + timedelta(minutes=m1)
            lo = s if lo is None or s < lo else lo
            hi = e if hi is None or e > hi else hi
    if lo is None:
        return None
    lo, hi = max(lo, span[0]), min(hi, span[1])
    return (lo, hi) if lo < hi else None


def minutes_on(start: datetime, end: datetime, day: date) -> list[tuple[int, int]]:
    """그 날짜(0시~24시) 안에서 작업이 일하는 분 구간들 (실제 시작·끝으로 자른다)."""
    day0 = datetime.combine(day, time())
    out = []
    for b in daily_bands(start, end):
        if not (b.d0 <= day <= b.d1):
            continue
        s = max(day0 + timedelta(minutes=b.m0), start)
        e = min(day0 + timedelta(minutes=b.m1), end)
        if s < e:
            out.append((int((s - day0).total_seconds() // 60), int((e - day0).total_seconds() // 60)))
    return out


def spatial_relation(a: Task, b: Task) -> str | None:
    if ALL_ZONE in (a.zone_id, b.zone_id):
        return "all_zone"
    if a.zone_id == b.zone_id:
        return "same_zone"
    if a.zone_id in FURNACE_COLUMN and b.zone_id in FURNACE_COLUMN:
        return "vertical"
    return None


def find_overlap_candidates(tasks: list[Task], zones: list[Zone] | None = None) -> list[OverlapCandidate]:
    out: list[OverlapCandidate] = []
    for a, b in combinations(tasks, 2):
        if a.contractor == b.contractor:
            continue
        relation = spatial_relation(a, b)
        if relation is None:
            continue
        window = daily_overlap(a.start, a.end, b.start, b.end)  # 매일 시각대까지 겹칠 때만
        if window is None:
            continue
        out.append(
            OverlapCandidate(
                task_a=a.id, task_b=b.id, relation=relation,
                window_start=window[0], window_end=window[1],
            )
        )
    return out
