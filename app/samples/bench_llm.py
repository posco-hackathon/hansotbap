"""F1 추출 비교 시험 도구: LLM 호출의 시간·토큰을 기록하고, 'LLM만' 조건의 입력과 채점 행을 만든다.

'LLM만' 조건은 규칙 보정을 거치지 않은 LLM 출력을 그대로 채점한다. LLM 호출은 llm/provider.py 인터페이스 뒤에서만 한다.
"""

from __future__ import annotations

import base64
import logging
import sys
import time
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))


# ── LLM 토큰: provider 가 남기는 사용량 로그를 가로챈다 (Claude 만 기록) ──
class _UsageTap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.calls: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if str(record.msg).startswith("claude extract") and record.args and len(record.args) >= 6:
            model, stop, i, cr, cw, o = record.args[:6]
            self.calls.append(
                {"model": model, "stop": stop, "in": i or 0, "cache_read": cr or 0, "cache_write": cw or 0, "out": o or 0}
            )


USAGE = _UsageTap()
logging.getLogger("llm.provider").addHandler(USAGE)
logging.getLogger("llm.provider").setLevel(logging.INFO)


def _is_transient(e: Exception) -> bool:
    """다시 보내면 나을 수 있는 장애인가. SDK 예외 타입만 볼 뿐 SDK 를 호출하지 않는다."""
    import anthropic

    if isinstance(e, (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError)):
        return True  # APITimeoutError 는 APIConnectionError 의 하위 타입이다
    return isinstance(e, anthropic.APIStatusError) and (e.status_code in (408, 409, 429) or e.status_code >= 500)


class MeasuredProvider:
    """LLMProvider 래퍼. extract 호출마다 시간·시도 수·토큰·실패 종류를 calls 에 남긴다.

    USAGE 가 프로세스 전역이므로 한 번에 한 호출씩 쓴다 (동시에 부르면 토큰이 섞인다).
    """

    def __init__(
        self,
        inner,
        timeout: float = 600.0,  # 호출 1회 제한(초) [팀 설정값]
        max_attempts: int = 3,  # 일시 장애 포함 최대 시도 수 [팀 설정값]
        sleep=time.sleep,
    ) -> None:
        self.inner = inner
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.calls: list[dict] = []
        self.plans: list = []

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def model(self) -> str:
        return self.inner.model  # 대체 모델이 답하면 provider 가 값을 바꾸므로 매번 읽는다

    def complete(self, system, user, max_tokens: int = 2048, timeout: float | None = None) -> str:
        return self.inner.complete(system, user, max_tokens=max_tokens, timeout=timeout)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed(texts)

    def extract(self, system, user, schema, max_tokens: int = 16000, timeout: float | None = None):
        # timeout 을 항상 넘겨 provider 의 SDK 자동 재시도를 끈다. 재시도는 아래에서 기록하며 한다
        limit = self.timeout if timeout is None else timeout
        started = time.perf_counter()
        attempts = 0
        while True:
            attempts += 1
            mark = len(USAGE.calls)
            t0 = time.perf_counter()
            try:
                plan = self.inner.extract(system, user, schema, max_tokens=max_tokens, timeout=limit)
            except Exception as e:
                seconds = time.perf_counter() - t0
                kind = "transient" if _is_transient(e) else "permanent"
                if kind == "transient" and attempts < self.max_attempts:
                    self.sleep(2**attempts)
                    continue
                self._record(seconds, started, attempts, mark, f"{type(e).__name__}: {e}"[:200], kind)
                raise
            self._record(time.perf_counter() - t0, started, attempts, mark)
            self.plans.append(plan)
            return plan

    def _record(
        self, seconds: float, started: float, attempts: int, mark: int, error: str | None = None, error_kind: str | None = None
    ) -> None:
        new = USAGE.calls[mark:]
        usage = new[-1] if new else None
        self.calls.append(
            {
                "seconds": seconds,
                "total_seconds": time.perf_counter() - started,
                "attempts": attempts,
                "ok": error_kind is None,
                "error": error,
                "error_kind": error_kind,
                "model": usage["model"] if usage else None,
                "stop": usage["stop"] if usage else None,
                "tokens": {k: usage[k] for k in ("in", "cache_read", "cache_write", "out")} if usage else None,
            }
        )


# ── 'LLM만' 조건의 입력: PDF 를 파서 없이 그대로 넘긴다 ──
def direct_content(pdf_bytes: bytes, anon_name: str) -> list[dict]:
    data = base64.b64encode(pdf_bytes).decode("ascii")
    text = (
        f"파일: {anon_name}\n제출 협력사: (미지정)\n\n"
        "위 PDF가 작업계획서 원본이다. 이 입력에는 위치표식이 없으니 evidence_locs 는 빈 목록으로 둔다."
    )
    return [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
        {"type": "text", "text": text},
    ]


# ── 'LLM만' 조건의 채점 행: LLM 출력을 규칙으로 고치지 않는다 ──
def _is_iso_date(value: str) -> bool:
    # parsers.normalize.iso_date 는 앞 10자만 잘라 읽어 '2027-02-05T08:00' 같은 값도 통과시키므로 쓰지 않는다.
    # date.fromisoformat 도 Python 3.11 부터 '20270205'·'2027-W06-5' 를 받으므로, 되돌린 글자가 입력과 같은지까지 본다.
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def plan_to_rows(plan) -> list[dict]:
    """LLMPlan → 채점 행. 키는 accuracy.py 의 extracted_row 와 같고, _format_errors 에 형식 오류 칸을 적는다."""
    rows: list[dict] = []
    for t in plan.tasks:
        name = t.name.strip()
        if not name:
            continue
        dates = {"start": t.start_date, "end": t.end_date}
        rows.append(
            {
                "contractor": t.contractor or plan.contractor,
                "name": name,
                "zone_id": t.zone_id or None,
                **dates,  # 맞는 형식이면 이미 YYYY-MM-DD, 틀리면 원래 문자열 그대로
                "shift": t.shift,
                "headcount": t.headcount,
                "hazards": sorted(set(t.hazards)),
                "predecessors": sorted(set(t.predecessor_wbs_ids) - {t.wbs_id}),
                "wbs_id": t.wbs_id,
                "_format_errors": [k for k, v in dates.items() if v is not None and not _is_iso_date(v)],
            }
        )
    return rows


# ── 비용: 백만 토큰당 달러 ──
CACHE_WRITE_RATE = 1.25  # 캐시 쓰기는 입력 단가의 1.25배
PRICES: dict[str, dict[str, float]] = {
    # Haiku 는 프롬프트 10만 토큰 이하 단가다. cache_read 는 공식 값을 확인하지 못해 입력의 0.1배로 둔다 [팀 설정값]
    "claude-haiku-5-5": {"in": 0.10, "cache_read": 0.01, "out": 0.50},
    "claude-sonnet-5-5": {"in": 2.0, "cache_read": 0.20, "out": 10.0},
    "claude-opus-5-5": {"in": 4.0, "cache_read": 0.20, "out": 20.0},
}


def cost_usd(tokens: dict, model: str, nominal: bool = False) -> float:
    """달러. nominal=True 면 캐시 없이 입력을 전부 입력 단가로 계산한 명목 비용. 모르는 모델이면 KeyError."""
    p = PRICES[model]
    if nominal:
        per_million = (tokens["in"] + tokens["cache_read"] + tokens["cache_write"]) * p["in"] + tokens["out"] * p["out"]
    else:
        per_million = (
            tokens["in"] * p["in"]
            + tokens["cache_read"] * p["cache_read"]
            + tokens["cache_write"] * p["in"] * CACHE_WRITE_RATE
            + tokens["out"] * p["out"]
        )
    return per_million / 1_000_000
