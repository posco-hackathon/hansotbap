"""F9 위험 시간대 예보: 저장된 판정 결과를 시간대별로 모아 근거와 함께 돌려준다. 점수는 규칙(rules/risk.py)이 낸다."""

from datetime import date

from fastapi import APIRouter, Query

from db.plans import current_schedule, list_conflicts
from llm.risk_text import polish_notices
from rules.data_loader import load_zones
from rules.risk import score_windows
from schemas import RiskWindow

router = APIRouter(tags=["risk"])

_POLISH_TOP = 5  # polish 때 LLM으로 다듬는 건수. 목록 전체를 부르면 느리고 비용이 든다 [팀 설정값]


def _polish_top(windows: list[RiskWindow]) -> list[RiskWindow]:
    """점수가 높은 건의 문장만 다듬고, 순서는 그대로 둔다. 호출은 한꺼번에 보낸다(순차 20초 → 4초대)."""
    top = sorted(range(len(windows)), key=lambda i: -windows[i].score)[:_POLISH_TOP]
    out = list(windows)
    for i, notice in zip(top, polish_notices([out[i].notice for i in top]), strict=True):
        out[i] = out[i].model_copy(update={"notice": notice})
    return out


@router.get("/risk-windows", response_model=list[RiskWindow])
def risk_windows(
    contractor: str | None = Query(default=None, description="협력사로 보면 자기 작업이 걸린 충돌만 집계한다 (서버에서 거른다)"),
    trade: str | None = Query(default=None, description="이 공정의 작업이 걸린 충돌만 집계"),
    zone_id: str | None = Query(default=None, description="이 구역의 시간대만"),
    on: date | None = Query(default=None, description="이 날짜의 시간대만 (없으면 공정 전체, 연속된 날은 합쳐서)"),
    polish: bool = Query(default=False, description="true 면 점수 상위 건의 공지 문장을 LLM으로 다듬는다 (실패하면 규칙 문장)"),
) -> list[RiskWindow]:
    """구역별 위험 시간대와 공지 문장. 권한을 먼저 거른 뒤 집계해 다른 업체만 걸린 충돌은 점수에도 들어가지 않는다."""
    tasks = current_schedule()
    conflicts = [r.conflict for r in list_conflicts(contractor)]
    if trade:
        in_trade = {t.id for t in tasks if t.trade == trade}
        conflicts = [c for c in conflicts if in_trade & set(c.task_ids)]

    windows = score_windows(conflicts, tasks, load_zones(), on)
    if zone_id:
        windows = [w for w in windows if w.zone_id == zone_id]
    return _polish_top(windows) if polish else windows
