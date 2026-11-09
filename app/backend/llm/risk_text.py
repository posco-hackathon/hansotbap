"""F9 위험 시간대 공지 문장 다듬기 (선택 기능). 점수와 시간대는 rules/risk.py 가 정하고 여기서는 문장만 고친다."""

from concurrent.futures import ThreadPoolExecutor

from llm.adjust_text import polish_text

# 동시에 보낼 최대 건수. 제공자 속도 제한에 걸리지 않을 만큼 [팀 설정값]
_MAX_PARALLEL = 5

_SYSTEM = (
    "너는 제철소 고로 개수공사의 위험 시간대 공지 문장을 다듬는 도우미다.\n"
    "입력은 규칙이 만든 공지 문장이다. 현장 작업자가 읽기 쉬운 한두 문장으로 다듬어 돌려준다.\n"
    "⟦1⟧ 같은 자리표는 날짜·시각·규칙 번호·건수다. 글자 그대로 옮기고 지우거나 바꾸거나 새로 만들지 않는다.\n"
    "구역·업체 이름도 바꾸거나 빼지 말고 문장만 다듬는다.\n"
    "원문에 없는 사실·판단·권고를 덧붙이지 않는다.\n"
    "머리말·따옴표·목록·마크다운 없이 다듬은 문장만 출력한다."
)


def polish_notice(notice: str) -> str:
    return polish_text(_SYSTEM, notice)


def polish_notices(notices: list[str]) -> list[str]:
    """여러 건을 한꺼번에. LLM 호출은 서로 기다릴 이유가 없어 동시에 보낸다 (5건 순차 20초 → 4초대).

    제공자 SDK 호출은 입출력 대기라 스레드로 겹쳐도 된다. 실패한 건은 polish_notice 가 원문을 돌려준다.
    """
    if len(notices) <= 1:
        return [polish_notice(n) for n in notices]
    with ThreadPoolExecutor(max_workers=min(len(notices), _MAX_PARALLEL)) as pool:
        return list(pool.map(polish_notice, notices))
