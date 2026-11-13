"""F1 정확도 측정 도구(samples/accuracy.py)의 채점이 틀어지지 않는지 본다. 실제 LLM은 부르지 않는다 (합성 데이터)."""

import json
import sys
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
sys.path.insert(0, str(SAMPLES))

from accuracy import FIELDS, aggregate, run_once, score_rows  # noqa: E402


class FailingProvider:
    name, model = "fake", "fake-1"

    def extract(self, system, user, schema, max_tokens=16000, timeout=None):
        raise RuntimeError("LLM 장애")


def uniform_plan() -> tuple[Path, dict]:
    """표 규칙으로 잘 읽히는 통일 양식 계획서와 그 정답."""
    base = SAMPLES / "uniform"
    truth = json.loads((base / "answers" / "가상-배관O_표준양식_작업계획.json").read_text(encoding="utf-8"))
    return base / truth["file"], truth


def test_llm_failure_counts_as_failure():
    """LLM 이 실패해 extract_plan 이 표 규칙 결과로 돌아가도, 그 점수를 LLM 경로의 점수로 세지 않는다."""
    sample, truth = uniform_plan()
    rec = run_once(sample, truth, "llm", provider_factory=FailingProvider)
    assert rec["status"] == "실패"
    assert rec["views"]["final"]["doc_correct"] == 0
    assert aggregate([rec], "final")["failed"] == 1


def test_contractor_cell_is_scored():
    """정답의 업체는 파일 최상위에만 있어도 작업마다 채점한다."""
    _, truth = uniform_plan()
    tasks = truth["tasks"]
    assert all("contractor" not in t for t in tasks)

    def contractor_stats(contractor: str) -> dict:
        rows = [{**{f: t.get(f) for f in FIELDS}, "contractor": contractor} for t in tasks]
        return score_rows(truth, rows)["field_stats"]["contractor"]

    n = len(tasks)
    assert contractor_stats(truth["contractor"]) == {"correct": n, "total": n}
    assert contractor_stats("가상-축로I") == {"correct": 0, "total": n}
