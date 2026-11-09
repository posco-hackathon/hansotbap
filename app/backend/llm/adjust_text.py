"""규칙이 만든 문장을 LLM으로 읽기 쉽게 다듬는다 (F4 조정안 이유, F9 위험 시간대 공지).

판정·점수·후보 계산은 rules/ 가 하고 여기서는 **문장만** 고친다. 숫자가 바뀌면 근거가 깨지므로,
작업 ID·날짜·시각·규칙 번호·건수는 LLM 에게 보내기 전에 자리표(⟦1⟧)로 가린 뒤 그대로 되돌린다.
LLM 이 자리표를 잃거나 호출이 실패하면 원문을 그대로 돌려준다 (어떤 실패에서도 예외를 내지 않는다).
"""

import logging
import re

from llm.provider import get_provider

log = logging.getLogger(__name__)

_SYSTEM = (
    "너는 제철소 고로 개수공사의 작업 조정안 이유 문장을 다듬는 도우미다.\n"
    "입력은 규칙이 만든 이유 문장이다. 현장 담당자가 읽기 쉬운 한두 문장으로 다듬어 돌려준다.\n"
    "⟦1⟧ 같은 자리표는 날짜·시각·작업 번호·건수다. 글자 그대로 옮기고 지우거나 바꾸거나 새로 만들지 않는다.\n"
    "원문에 없는 사실·판단·권고를 덧붙이지 않는다.\n"
    "머리말·따옴표·목록·마크다운 없이 다듬은 문장만 출력한다."
)

# 결과를 검사할 때 세는 토큰. 영문·숫자 바로 앞뒤가 아닐 때만 토큰으로 본다
# ("P22가" 처럼 한글이 붙은 경우는 토큰으로 센다)
_TOKENS = {
    "날짜": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "시각": re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)"),
    "작업 ID": re.compile(r"(?<![A-Za-z0-9])P\d+(?!\d)"),
    "규칙 번호": re.compile(r"(?<![A-Za-z0-9])R\d+(?!\d)"),
    "건수": re.compile(r"(?<!\d)\d+건"),
}
# 보낼 때 가리는 범위. 건수는 숫자만 가리고 '건'은 남긴다 —
# '7건' 을 통째로 가리면 모델이 ⟦4⟧건 처럼 '건' 을 또 붙여 "7건건" 이 되고,
# 받침을 몰라 조사도 틀린다("4건와"). 숫자만 가리면 모델이 '건' 을 보고 조사를 맞춘다.
# 날짜를 먼저 찾아야 날짜 안의 숫자가 따로 잘리지 않는다.
_ANY_TOKEN = re.compile(
    "|".join(
        [
            _TOKENS["날짜"].pattern,
            _TOKENS["시각"].pattern,
            _TOKENS["작업 ID"].pattern,
            _TOKENS["규칙 번호"].pattern,
            r"(?<!\d)\d+(?=건)",
        ]
    )
)
_PLACEHOLDER = "⟦{}⟧"
_PLACEHOLDER_RE = re.compile(r"⟦(\d+)⟧")


def _tokens_preserved(original: str, polished: str) -> bool:
    """원문의 토큰이 결과에 모두 있고, 결과에 원문에 없는 토큰이 없을 때만 참."""
    return all(set(p.findall(original)) == set(p.findall(polished)) for p in _TOKENS.values())


def _protect(text: str) -> tuple[str, list[str]]:
    """숫자 토큰을 자리표로 가린다. 같은 토큰이 여러 번 나와도 자리마다 따로 센다."""
    values: list[str] = []

    def take(m: re.Match[str]) -> str:
        values.append(m.group(0))
        return _PLACEHOLDER.format(len(values))

    return _ANY_TOKEN.sub(take, text), values


def _restore(text: str, values: list[str]) -> str | None:
    """자리표를 원래 값으로. 하나라도 빠지거나 없는 번호가 나오면 None (원문으로 되돌린다)."""
    seen: set[int] = set()

    def put(m: re.Match[str]) -> str:
        i = int(m.group(1))
        if not 1 <= i <= len(values):
            seen.add(-1)
            return m.group(0)
        seen.add(i)
        return values[i - 1]

    out = _PLACEHOLDER_RE.sub(put, text)
    if seen != set(range(1, len(values) + 1)):
        return None
    return out


def _once(system: str, masked: str, values: list[str], original: str) -> str | None:
    """한 번 호출해 본다. 쓸 수 있는 결과면 문장, 아니면 None."""
    polished = get_provider().complete(system, masked).strip()
    if not polished:
        log.warning("문장 다듬기 결과가 비었다")
        return None
    restored = _restore(polished, values)
    if restored is None:
        log.warning("문장 다듬기 결과가 자리표(날짜·시각·번호)를 잃었다")
        return None
    if not _tokens_preserved(original, restored):  # 자리표 밖에서 숫자를 새로 지어낸 경우
        log.warning("문장 다듬기 결과가 원문에 없는 날짜·시각·번호를 넣었다")
        return None
    return restored


def polish_text(system: str, text: str, *, retries: int = 1) -> str:
    """규칙이 만든 문장을 다듬는다. 어떤 실패에서도 예외를 내지 않고 원문을 돌려준다.

    LLM 출력은 호출마다 조금씩 달라서 한 번은 자리표를 흘릴 수 있다 → 기본 1회까지 다시 해 본다.
    """
    if not text.strip():
        return text
    masked, values = _protect(text)
    for attempt in range(retries + 1):
        try:
            if (out := _once(system, masked, values, text)) is not None:
                return out
        except Exception as e:  # 키 없음·네트워크·제공자 오류 모두. 메시지에 키가 섞일 수 있어 종류만 남긴다
            log.warning("문장 다듬기 실패 (%s), %s", type(e).__name__, "다시 시도" if attempt < retries else "원문 사용")
    return text


def polish_reason(reason: str) -> str:
    """조정안 이유 문장을 다듬는다."""
    return polish_text(_SYSTEM, reason)
