"""F4·F9 문장 다듬기: 숫자(날짜·시각·작업 ID·규칙 번호·건수)가 절대 바뀌지 않는지.

LLM 은 부르지 않는다 — 가짜 제공자를 끼워 "모델이 이렇게 답했을 때" 만 본다.
"""

import pytest

from llm import adjust_text
from llm.adjust_text import _protect, _restore, _tokens_preserved, polish_text

NOTICE = (
    "노상·노저(hearth) 2026-12-22 07:00~19:00 위험 시간대입니다. 금지 7건·조건부 6건 겹칩니다 "
    "(규칙 R03, R05, R16 외 1건)."
)
REASON = "질소·가스 라인 연결(P34)을 2027-03-03로 옮겨, 선행 작업 P22가 끝난(2027-03-02) 뒤에 시작하게 합니다."


class FakeProvider:
    """complete() 가 정해진 답을 돌려주는 가짜 제공자."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def complete(self, system: str, text: str) -> str:
        self.calls += 1
        return self.reply(text) if callable(self.reply) else self.reply


@pytest.fixture
def fake(monkeypatch):
    def use(reply):
        p = FakeProvider(reply)
        monkeypatch.setattr(adjust_text, "get_provider", lambda: p)
        return p

    return use


def test_protect_restore_roundtrip():
    masked, values = _protect(NOTICE)
    assert "2026-12-22" not in masked and "R03" not in masked and "7건" not in masked
    assert values == ["2026-12-22", "07:00", "19:00", "7", "6", "R03", "R05", "R16", "1"]
    assert _restore(masked, values) == NOTICE


def test_count_keeps_the_unit_outside_the_placeholder():
    """'7건' 은 숫자만 가린다 — 통째로 가리면 모델이 '건' 을 또 붙여 "7건건" 이 되고 조사도 틀린다."""
    masked, _ = _protect("금지 7건·조건부 6건 겹칩니다")
    assert masked == "금지 ⟦1⟧건·조건부 ⟦2⟧건 겹칩니다"


def test_duplicated_unit_cannot_happen(fake):
    fake(lambda masked: masked.replace("겹칩니다", "겹칩니다(확인)"))
    out = polish_text("sys", NOTICE)
    assert "건건" not in out and "7건" in out and "6건" in out


def test_restore_rejects_lost_placeholder():
    masked, values = _protect(NOTICE)
    assert _restore(masked.replace("⟦1⟧ ", ""), values) is None  # 모델이 날짜를 통째로 지운 경우


def test_restore_rejects_invented_placeholder():
    masked, values = _protect(NOTICE)
    assert _restore(masked + " ⟦99⟧", values) is None


def test_polished_sentence_keeps_every_number(fake):
    """모델이 문장을 다시 써도 자리표만 옮기면 숫자는 그대로다."""
    fake(lambda masked: masked.replace("위험 시간대입니다.", "위험 시간대이니 주의하십시오.").replace("노상·노저(hearth) ", "노상·노저(hearth)는 "))
    out = polish_text("sys", NOTICE)
    assert out != NOTICE
    assert _tokens_preserved(NOTICE, out)
    assert "2026-12-22" in out and "07:00~19:00" in out and "R16" in out and "7건" in out


def test_lost_placeholder_falls_back_to_original(fake):
    p = fake("노상·노저 구역이 위험합니다.")  # 자리표를 다 날린 답
    assert polish_text("sys", NOTICE) == NOTICE
    assert p.calls == 2  # 한 번 더 해 보고 포기한다


def test_retry_recovers(fake):
    """첫 호출이 자리표를 흘려도 두 번째가 성공하면 다듬은 문장을 쓴다 (LLM 출력이 매번 달라서)."""
    state = {"n": 0}

    def reply(masked: str) -> str:
        state["n"] += 1
        return "자리표를 잃은 답" if state["n"] == 1 else masked.replace("겹칩니다", "겹칩니다 — 주의")

    p = fake(reply)
    out = polish_text("sys", NOTICE)
    assert p.calls == 2
    assert "주의" in out and _tokens_preserved(NOTICE, out)


def test_provider_error_returns_original(fake):
    def boom(_):
        raise RuntimeError("sk-ant-… 가 섞일 수 있는 오류")

    fake(boom)
    assert polish_text("sys", NOTICE) == NOTICE


def test_empty_text_is_not_sent(fake):
    p = fake("무언가")
    assert polish_text("sys", "   ") == "   "
    assert p.calls == 0


def test_reason_sentence_keeps_task_ids_and_dates(fake):
    fake(lambda masked: masked.replace("합니다.", "합니다. 착수 전 완료·퇴출을 확인하십시오."))
    out = polish_text("sys", REASON)
    assert _tokens_preserved(REASON, out)
    assert "P34" in out and "P22" in out and "2027-03-03" in out and "2027-03-02" in out


def test_model_inventing_a_number_is_rejected(fake):
    """자리표 밖에서 새 숫자를 지어내면 원문을 쓴다 (근거가 아닌 숫자가 공지에 나가지 않게)."""
    p = fake(lambda masked: masked + " 규칙 R99 도 함께 봅니다.")
    assert polish_text("sys", NOTICE) == NOTICE
    assert p.calls == 2


def test_polish_notices_runs_in_parallel_and_keeps_order(fake):
    from llm import risk_text

    fake(lambda masked: masked.replace("겹칩니다", "겹칩니다(확인)"))
    notices = [NOTICE, NOTICE.replace("2026-12-22", "2026-12-23"), NOTICE.replace("2026-12-22", "2026-12-24")]
    out = risk_text.polish_notices(notices)
    assert len(out) == 3
    assert [n.count("확인") for n in out] == [1, 1, 1]
    for src, got in zip(notices, out, strict=True):
        assert _tokens_preserved(src, got)
