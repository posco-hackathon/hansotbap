"""F1 추출 정확도 측정: samples/ 의 계획서를 추출기에 넣고 answers/ 의 정답셋과 칸별로 비교한다.

    cd app/backend && uv run python ../samples/accuracy.py                                            # 표 규칙 경로 (LLM 안 부름)
    cd app/backend && uv run python ../samples/accuracy.py --samples ../samples/variants --repeat 3   # 변형 표본, 3회 반복
    cd app/backend && uv run python ../samples/accuracy.py --mode llm                                 # LLM 경로 (.env 의 ANTHROPIC_API_KEY 필요)
    cd app/backend && uv run python ../samples/accuracy.py --mode llm-file --samples ../samples/variants  # LLM만 (PDF 만)
    cd app/backend && uv run python ../samples/accuracy.py --json <저장 경로>

경로(--mode)
- rules    = 파서 + 표 규칙. 예외만 실패로 센다
- auto     = 표 규칙 먼저, 못 읽거나 확인 필요가 있으면 LLM. 표 규칙 결과는 정상이고, LLM 을 불렀다가 실패해 규칙으로 돌아가면 실패다
- llm      = 파서 + LLM + 규칙 보정
- llm-raw  = 파서 글자(표 구조·위치표식 제거) + LLM + 규칙 보정을 받는 참고용. LLM만이 아니다
- llm-file = LLM만: PDF 바이트를 파서 없이 LLM 에 넘기고 답을 규칙 보정 없이 채점한다.
             PDF 가 아니면 실행하지 않고 '입력 불가'로 남겨 분모에서 뺀다. LLM_PROVIDER=claude 일 때만 돈다
llm·llm-raw·llm-file 은 성공한 LLM 호출이 없거나 규칙 결과로 대체된 회차를 실패로 세어 정답 칸 0, 작업 전부 누락으로 집계한다.
LLM 을 부를 수 있는 경로는 원래 파일명 대신 '문서.확장자'를 넘겨 파일 이름이 정답 힌트가 되지 않게 한다.

채점 값(view): final = 규칙 보정까지 거친 결과(rules·auto·llm·llm-raw), raw = 규칙 보정 없는 LLM 원답(llm·llm-raw·llm-file, LLM 을 부른 auto)

칸
- 문서 칸(머리 지표): 업체 · 작업명 · 구역 · 시작일 · 종료일 · 주야간 · 투입 인원 · 작업 유형 (8칸). 작업 완전 일치도 이 칸 기준이다
- 연결 칸(따로 집계): 기준 일정 ID · 선행 작업 (2칸)
- 정답셋의 값이 null 이면 그 칸은 세지 않는다 (예: '주야간' 연속 작업은 한쪽으로 정할 수 없다). 기준 일정 ID 는 null 도 '연결 없음'이라는 정답으로 센다
- 짝을 찾지 못한 정답 작업의 칸도 분모에 남는다 (실패 회차와 같은 기준)
- 작업명 머리 정확도는 완화 일치(유사도 기준 + 설치/해체 뒤바뀜 아님)이고, 엄격 일치 값을 같이 낸다
- 규칙이 기본값으로 채운 주야간·투입 인원·기간은 문서에서 읽은 값이 아니므로 비워서 채점한다
회차마다 채점해 평균·최소·최대를 낸다. 틀린 칸 목록은 프롬프트·규칙 수정용으로 그대로 전달한다.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from bench_llm import PRICES, MeasuredProvider, cost_usd, direct_content, plan_to_rows  # noqa: E402
from config import settings  # noqa: E402
from llm.extract import LLMPlan, extract_plan, is_degraded, system_prompt  # noqa: E402
from llm.provider import get_provider  # noqa: E402
from parsers.document import ParsedDocument, Segment  # noqa: E402
from parsers.docx import parse_docx  # noqa: E402
from parsers.hwpx import parse_hwpx  # noqa: E402
from parsers.normalize import name_similarity, same_contractor  # noqa: E402
from parsers.pdf import parse_pdf  # noqa: E402
from parsers.xlsx import parse_xlsx  # noqa: E402

HERE = Path(__file__).resolve().parent


def parse_txt(data: bytes, filename: str = "plan.txt") -> ParsedDocument:
    """텍스트 제출 표본 → 줄마다 `L<파일의 줄 번호>` 표식. 빈 줄은 뺀다. 표가 없으므로 rules 경로로는 읽히지 않는다."""
    # ParsedDocument.file_type 의 Literal 에 txt 가 없지만 실행 때 검사하지 않고, PlanExtraction.file_type 은 str 이다
    doc = ParsedDocument(filename=filename, file_type="txt")  # type: ignore[arg-type]
    for no, line in enumerate(data.decode("utf-8").splitlines(), start=1):
        if line.strip():
            doc.segments.append(Segment(f"L{no}", line.strip()))
    return doc


PARSERS = {".pdf": parse_pdf, ".xlsx": parse_xlsx, ".hwpx": parse_hwpx, ".docx": parse_docx, ".txt": parse_txt}
MODES = ("auto", "rules", "llm", "llm-raw", "llm-file")
DOC_FIELDS = ("contractor", "name", "zone_id", "start", "end", "shift", "headcount", "hazards")
LINK_FIELDS = ("wbs_id", "predecessors")
FIELDS = DOC_FIELDS + LINK_FIELDS
LABEL = {
    "contractor": "업체", "name": "작업명", "zone_id": "구역", "start": "시작일", "end": "종료일",
    "shift": "주야간", "headcount": "투입 인원", "hazards": "작업 유형", "predecessors": "선행 작업", "wbs_id": "기준 일정 ID",
}
LOOSE_NAME_SIM = 0.5  # 작업명 완화 일치 기준 [팀 설정값]
TOKEN_KEYS = ("in", "cache_read", "cache_write", "out")

# 규칙이 기본값으로 채운 칸을 알아보는 경고 문구 (parsers/normalize.py build_interval, llm/extract.py finalize)
WARN_SHIFT_DEFAULT = "주간(07~19시) 기본값"
WARN_CREW_DEFAULT = "계획서에 투입 인원이 없어 기준 일정 값"
WARN_PERIOD_DEFAULT = "기간이 없어 임시값(D0)"


def _squash(t: str | None) -> str:
    return re.sub(r"[\s·,./()\-~]", "", t or "")


def extracted_row(et) -> dict:
    """ExtractedTask → 채점 행. 규칙의 기본값으로 채운 칸은 None 으로 비우고, 종료일은 문서에 적힌 날로 되돌린다."""
    t = et.task

    def warned(text: str) -> bool:
        return any(text in w for w in et.warnings)

    end = t.end.date()
    if t.end.time() <= t.start.time():  # build_interval 은 자정을 넘기면 end 에 하루를 더한다
        end -= timedelta(days=1)
    no_period = warned(WARN_PERIOD_DEFAULT)
    return {
        "contractor": t.contractor,
        "name": t.name,
        "zone_id": t.zone_id or None,
        "start": None if no_period else t.start.date().isoformat(),
        "end": None if no_period else end.isoformat(),
        "shift": None if warned(WARN_SHIFT_DEFAULT) else (t.shift.value if t.shift else None),
        "headcount": None if warned(WARN_CREW_DEFAULT) else t.crew,
        "hazards": sorted(h.value for h in t.hazards),
        "predecessors": sorted(t.predecessors),
        "wbs_id": et.wbs_id,
    }


def same(field: str, truth, got) -> bool:
    """칸 일치. 작업명은 여기서 엄격 일치만 본다 (완화 일치는 name_loose)."""
    if field == "contractor":
        return same_contractor(truth, got)
    if field == "name":
        return _squash(truth) == _squash(got)
    if field in ("hazards", "predecessors"):
        return sorted(truth or []) == sorted(got or [])
    return truth == got


def name_flipped(a: str, b: str) -> bool:
    """설치 ↔ 해체·철거가 뒤바뀌었는가. 한쪽 낱말이 양쪽 작업명에 다 있으면(예: '비계 설치·해체' ↔ '비계 해체') 뒤바뀜이 아니다."""
    a, b = _squash(a), _squash(b)

    def install(s: str) -> bool:
        return "설치" in s

    def remove(s: str) -> bool:
        return "해체" in s or "철거" in s

    def only(word, x: str, y: str) -> bool:
        return word(x) and not word(y)

    return (only(install, a, b) and only(remove, b, a)) or (only(install, b, a) and only(remove, a, b))


def name_loose(truth: str, got: str) -> bool:
    if same("name", truth, got):
        return True
    return name_similarity(truth, got) >= LOOSE_NAME_SIM and not name_flipped(truth, got)


def pair_tasks(truth_tasks: list[dict], got_rows: list[dict]) -> list[tuple[dict, dict | None]]:
    """정답 작업 ↔ 추출 작업을 작업명 유사도로 짝짓는다 (한 번 쓴 추출 작업은 다시 쓰지 않는다)."""
    free = list(range(len(got_rows)))
    out: list[tuple[dict, dict | None]] = []
    for tt in truth_tasks:
        best, best_sim = None, 0.0
        for i in free:
            sim = name_similarity(tt["name"], got_rows[i]["name"])
            if sim > best_sim:
                best, best_sim = i, sim
        if best is not None and best_sim >= 0.3:
            free.remove(best)
            out.append((tt, got_rows[best]))
        else:
            out.append((tt, None))
    return out


# ── llm-raw(참고용): 파서가 나눈 표·위치표식을 버리고 글자만 이어 붙여 LLM에 넘긴다. 답은 규칙 보정을 받는다 ──
@dataclass
class RawDocument(ParsedDocument):
    def text(self) -> str:
        return "\n".join(re.sub(r"\s*\|\s*", " ", s.text) for s in self.segments)


def raw_document(doc: ParsedDocument) -> RawDocument:
    return RawDocument(filename=doc.filename, file_type=doc.file_type, segments=list(doc.segments), tables=[])


# ── 채점 ──
def _sig(rows: list[dict]) -> str:
    """문서 칸만 본 결과 비교용 문자열. 행 순서와 무관하다."""
    canon = (json.dumps({f: r.get(f) for f in DOC_FIELDS}, ensure_ascii=False, sort_keys=True) for r in rows)
    return json.dumps(sorted(canon), ensure_ascii=False)


def score_rows(truth: dict, rows: list[dict], missing_label: str = "(작업 누락)") -> dict:
    """채점 행 → view 하나. 정답의 업체는 파일 최상위에만 있어 작업마다 넣어 비교한다."""
    file = truth["file"]
    view: dict = {
        "doc_cells": 0, "doc_correct": 0, "doc_correct_strict": 0, "link_cells": 0, "link_correct": 0,
        "tasks": 0, "tasks_exact": 0, "missed_tasks": 0, "extra_tasks": 0, "wrong": [], "signature": _sig(rows),
        "field_stats": {f: {"correct": 0, "total": 0} for f in FIELDS},
    }
    pairs = pair_tasks([{**tt, "contractor": truth["contractor"]} for tt in truth["tasks"]], rows)
    for tt, got in pairs:
        view["tasks"] += 1
        exact = got is not None
        if got is None:
            view["missed_tasks"] += 1
            view["wrong"].append({"file": file, "task": tt["name"], "field": missing_label, "truth": tt["name"], "got": None})
        for field in FIELDS:
            if tt.get(field) is None and field != "wbs_id":
                continue  # 정답이 없는 칸은 세지 않는다
            is_doc = field in DOC_FIELDS
            view["doc_cells" if is_doc else "link_cells"] += 1
            view["field_stats"][field]["total"] += 1
            if got is None:
                continue  # 짝이 없는 작업의 칸은 맞은 칸 없이 분모에만 남는다
            strict = same(field, tt.get(field), got.get(field))
            ok = name_loose(tt[field], got[field]) if field == "name" else strict
            if ok:
                view["field_stats"][field]["correct"] += 1
                view["doc_correct" if is_doc else "link_correct"] += 1
                if is_doc and strict:
                    view["doc_correct_strict"] += 1
            else:
                exact = exact and not is_doc
                view["wrong"].append({"file": file, "task": tt["name"], "field": LABEL[field], "truth": tt.get(field), "got": got.get(field)})
        view["tasks_exact"] += 1 if exact else 0
    view["extra_tasks"] = len(rows) - sum(1 for _, g in pairs if g is not None)
    return view


def _failed_view(truth: dict) -> dict:
    view = score_rows(truth, [], "(회차 실패)")
    view["signature"] = None
    return view


def _ai_failure(mode: str, ex, calls: list[dict]) -> str | None:
    """이 회차를 실패로 볼 사유. 정상이면 None. rules 는 예외만 실패이고, auto 는 표 규칙 결과가 정상이다."""
    if mode == "rules":
        return None
    if ex is not None and is_degraded(ex):
        return next(w for w in ex.warnings if w.startswith("LLM 추출 실패"))
    if mode == "auto":
        return None
    if ex is not None and ex.method != "llm":
        return f"LLM 결과가 아닙니다 (method={ex.method})"
    if not any(c["ok"] for c in calls):
        return "성공한 LLM 호출이 없습니다"
    return None


def _view_names(mode: str, llm_tried: bool) -> tuple[str, ...]:
    if mode == "rules" or (mode == "auto" and not llm_tried):
        return ("final",)
    return ("raw",) if mode == "llm-file" else ("final", "raw")


def llm_file_unavailable() -> str | None:
    if settings.llm_provider != "claude":
        return f"llm-file 은 PDF 를 직접 받는 Claude 로만 돕니다. 지금 LLM_PROVIDER={settings.llm_provider} 입니다. LLM_PROVIDER=claude 로 바꾼 뒤 다시 돌리세요."
    return None


def run_once(sample: Path, truth: dict, mode: str, provider_factory=None, timeout: float | None = None) -> dict:
    """계획서 1건을 1회 추출해 채점한다. 예외를 밖으로 던지지 않고 record 의 status("ok"/"실패"/"입력 불가")와 error 로 남긴다."""
    started = time.perf_counter()
    rec: dict = {
        "file": truth.get("file", sample.name), "mode": mode, "status": "ok", "error": None, "method": None, "views": {},
        "parse_seconds": 0.0, "llm_seconds": 0.0, "total_seconds": 0.0, "calls": [], "model": None, "stop": None, "attempts": 0,
        "tokens": dict.fromkeys(TOKEN_KEYS, 0), "cache_write": False, "cost_usd": None, "nominal_usd": None,
        "needs_review": 0, "format_errors": 0, "warnings": [],
    }
    if mode == "llm-file" and sample.suffix.lower() != ".pdf":
        rec["status"], rec["error"] = "입력 불가", f"llm-file 은 PDF 만 받습니다 ({sample.suffix})"
        return rec

    make_provider = provider_factory or get_provider
    limit = {} if timeout is None else {"timeout": timeout}
    measured: MeasuredProvider | None = None
    llm_tried = False

    def measured_factory() -> MeasuredProvider:
        nonlocal measured, llm_tried
        llm_tried = True  # provider 를 만들다 실패해도(키 없음) LLM 경로를 시도한 것이다
        measured = MeasuredProvider(make_provider(), **limit)
        return measured

    ended = failure = None
    try:
        if mode not in MODES:
            raise ValueError(f"모르는 경로입니다: {mode}")
        data = sample.read_bytes()
        rows: dict[str, list[dict]] = {}
        if mode == "llm-file":
            if provider_factory is None and (why := llm_file_unavailable()):
                raise RuntimeError(why)
            plan = measured_factory().extract(system_prompt(), direct_content(data, "문서.pdf"), LLMPlan)  # type: ignore[arg-type]
            ended = time.perf_counter()
            rec["method"] = "llm-file"
            rows["raw"] = plan_to_rows(plan)
            failure = _ai_failure(mode, None, measured.calls)
        else:
            t0 = time.perf_counter()
            doc = PARSERS[sample.suffix](data, sample.name if mode == "rules" else f"문서{sample.suffix}")
            if mode == "llm-raw":
                doc = raw_document(doc)
            rec["parse_seconds"] = time.perf_counter() - t0
            ex = extract_plan(doc, mode="llm" if mode == "llm-raw" else mode, provider_factory=measured_factory)
            ended = time.perf_counter()
            rec["method"], rec["warnings"] = ex.method, ex.warnings
            rec["needs_review"] = sum(1 for t in ex.tasks if t.needs_review)
            rows["final"] = [extracted_row(t) for t in ex.tasks]
            if measured is not None and measured.plans:
                rows["raw"] = plan_to_rows(measured.plans[-1])
            failure = _ai_failure(mode, ex, measured.calls if measured else [])
        if failure is None:
            rec["views"] = {name: score_rows(truth, r) for name, r in rows.items()}
            rec["format_errors"] = sum(len(row["_format_errors"]) for row in rows.get("raw", []))
    except Exception as e:  # 규칙으로 못 읽는 양식(문장형 등), 파일 오류, 키 없음은 실패로 세고 계속
        failure = f"{type(e).__name__}: {e}"[:200]
    if failure:
        rec["status"], rec["error"], rec["needs_review"] = "실패", failure, 0  # 규칙 결과로 돌아간 회차의 확인 필요 수를 남기지 않는다
        rec["views"] = {name: _failed_view(truth) for name in _view_names(mode, llm_tried)}

    calls = measured.calls if measured is not None else []
    used = [c for c in calls if c["tokens"]]
    rec["total_seconds"] = (ended or time.perf_counter()) - started
    rec["calls"] = calls
    rec["llm_seconds"] = sum(c["seconds"] for c in calls)
    rec["attempts"] = sum(c["attempts"] for c in calls)
    for c in used:
        for k in TOKEN_KEYS:
            rec["tokens"][k] += c["tokens"][k]
    rec["cache_write"] = any(c["tokens"]["cache_write"] > 0 for c in used)
    rec["model"] = used[-1]["model"] if used else getattr(measured, "model", None)
    rec["stop"] = used[-1]["stop"] if used else None
    if used and all(c["model"] in PRICES for c in used):
        rec["cost_usd"] = sum(cost_usd(c["tokens"], c["model"]) for c in used)
        rec["nominal_usd"] = sum(cost_usd(c["tokens"], c["model"], nominal=True) for c in used)
    return rec


def load_truths(base: Path, names: list[str] | None = None) -> list[tuple[Path, dict]]:
    """answers/*.json → (표본 경로, 정답) 목록. 밑줄로 시작하는 결과 파일은 뺀다. names 를 주면 표본 파일 이름이 그 안에 있는 것만."""
    out: list[tuple[Path, dict]] = []
    for ans_path in sorted((base / "answers").glob("*.json")):
        if ans_path.name.startswith("_"):
            continue
        truth = json.loads(ans_path.read_text(encoding="utf-8"))
        sample = base / truth["file"]
        if names is None or sample.name in names:
            out.append((sample, truth))
    return out


# ── 집계 ──
def _rate(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def _time_means(records: list[dict]) -> dict:
    means = {k: round(statistics.mean(r[f"{k}_seconds"] for r in records), 3) if records else None for k in ("total", "llm", "parse")}
    return {"runs": len(records), **means}


def _sum_and_mean(values: list[float]) -> tuple[float | None, float | None]:
    return (round(sum(values), 6), round(statistics.mean(values), 6)) if values else (None, None)


def aggregate(records: list[dict], view: str = "final") -> dict:
    """같은 조건의 record 를 합친다. 회차는 같은 파일 record 의 순서로 정한다.

    '입력 불가'는 분모에서 뺀다. 시간은 성공 회차 평균이고(실패 회차는 답이 없어 비교 대상이 아니다), 토큰·비용은 실패 회차까지 합친다.
    반복 일치율에서 모든 회차가 실패한 파일은 비교할 결과가 없어 뺀다. 일부 회차만 실패한 파일은 불일치다.
    """
    runnable = [r for r in records if r["status"] != "입력 불가"]
    scored = [r for r in runnable if view in r["views"]]
    views = [r["views"][view] for r in scored]
    ok = [r for r in scored if r["status"] == "ok"]
    by_file: dict[str, list[dict]] = {}
    for r in scored:
        by_file.setdefault(r["file"], []).append(r["views"][view])
    n_rounds = max((len(vs) for vs in by_file.values()), default=0)

    def total(key: str) -> int:
        return sum(v[key] for v in views)

    per_round = []
    for k in range(n_rounds):
        round_views = [vs[k] for vs in by_file.values() if k < len(vs)]
        per_round.append(_rate(sum(v["doc_correct"] for v in round_views), sum(v["doc_cells"] for v in round_views)))

    consistency, comparable, same_files = None, 0, 0
    if n_rounds >= 2:
        for vs in by_file.values():
            sigs = [v["signature"] for v in vs]
            if len(sigs) < 2 or all(s is None for s in sigs):
                continue
            comparable += 1
            same_files += 1 if len(set(sigs)) == 1 else 0
        consistency = _rate(same_files, comparable) if comparable else None

    fields = {}
    for f in FIELDS:
        c, t = sum(v["field_stats"][f]["correct"] for v in views), sum(v["field_stats"][f]["total"] for v in views)
        fields[f] = {"correct": c, "total": t, "accuracy": _rate(c, t)}

    tokens = {k: sum(r["tokens"][k] for r in scored) for k in TOKEN_KEYS}
    cost, cost_per_run = _sum_and_mean([r["cost_usd"] for r in scored if r["cost_usd"] is not None])
    nominal, nominal_per_run = _sum_and_mean([r["nominal_usd"] for r in scored if r["nominal_usd"] is not None])
    return {
        "view": view, "runs": len(scored), "rounds": n_rounds,
        "doc_cells": total("doc_cells"), "doc_correct": total("doc_correct"), "doc_correct_strict": total("doc_correct_strict"),
        "doc_accuracy": _rate(total("doc_correct"), total("doc_cells")),
        "doc_accuracy_strict": _rate(total("doc_correct_strict"), total("doc_cells")),
        "link_cells": total("link_cells"), "link_correct": total("link_correct"),
        "link_accuracy": _rate(total("link_correct"), total("link_cells")),
        "tasks": total("tasks"), "tasks_exact": total("tasks_exact"), "task_exact_rate": _rate(total("tasks_exact"), total("tasks")),
        "missed_tasks": total("missed_tasks"), "extra_tasks": total("extra_tasks"),
        "missed_per_round": round(total("missed_tasks") / n_rounds, 2) if n_rounds else 0.0,
        "extra_per_round": round(total("extra_tasks") / n_rounds, 2) if n_rounds else 0.0,
        "round_accuracy": {
            "mean": round(statistics.mean(per_round), 1) if per_round else 0.0,
            "min": min(per_round, default=0.0), "max": max(per_round, default=0.0), "per_round": per_round,
        },
        "seconds": _time_means(ok),
        "seconds_no_cache_write": _time_means([r for r in ok if not r["cache_write"]]),
        "llm_calls": sum(len(r["calls"]) for r in scored), "tokens": tokens,
        "cost_usd": cost, "cost_usd_per_run": cost_per_run, "nominal_usd": nominal, "nominal_usd_per_run": nominal_per_run,
        "failed": sum(1 for r in scored if r["status"] == "실패"),
        "failures": [{"file": r["file"], "error": r["error"]} for r in scored if r["status"] == "실패"],
        "input_unavailable": len(records) - len(runnable),
        "needs_review": sum(r["needs_review"] for r in scored), "format_errors": sum(r["format_errors"] for r in scored),
        "consistency": consistency, "consistent_files": same_files, "consistency_files": comparable,
        "field_accuracy": fields,
        "wrong": [w for v in views for w in v["wrong"]],
    }


def _file_row(truth: dict, records: list[dict], view: str) -> dict:
    a = aggregate(records, view)
    got = [v["tasks"] - v["missed_tasks"] + v["extra_tasks"] for v in (r["views"][view] for r in records if view in r["views"])]
    warnings = list(dict.fromkeys(w for r in records for w in r["warnings"]))
    return {
        "file": truth["file"],
        "method": "/".join(sorted({r["method"] if r["status"] == "ok" else r["status"] for r in records})),
        "tasks_truth": len(truth["tasks"]), "tasks_got": round(statistics.mean(got), 1) if got else 0,
        "doc_cells": a["doc_cells"], "doc_correct": a["doc_correct"], "doc_correct_strict": a["doc_correct_strict"],
        "link_cells": a["link_cells"], "link_correct": a["link_correct"], "failed": a["failed"], "warnings": warnings,
        "consistent": None if a["consistency"] is None else a["consistency"] == 100.0,
    }


def measure(mode: str, only: str | None = None, samples: Path | None = None, repeat: int = 1, view: str | None = None) -> dict:
    """파일·회차 순서대로 run_once 를 돌려 aggregate 한다. view 를 주지 않으면 llm-file 은 raw, 나머지는 final."""
    if mode == "llm-file" and (why := llm_file_unavailable()):
        raise SystemExit(why)
    base = samples or HERE
    view = view or ("raw" if mode == "llm-file" else "final")
    records: list[dict] = []
    files: list[dict] = []
    for sample, truth in load_truths(base):
        if only and only not in truth["file"]:
            continue
        runs = [run_once(sample, truth, mode) for _ in range(max(1, repeat))]
        records += runs
        files.append(_file_row(truth, runs, view))
    return {"mode": mode, "samples": base.name, "repeat": repeat, **aggregate(records, view), "files": files, "records": records}


def _print_summary(title: str, r: dict) -> None:
    print(f"\n{title}")
    print(f"  문서 칸: 완화 {r['doc_correct']}/{r['doc_cells']} = {r['doc_accuracy']}%   엄격 {r['doc_correct_strict']}/{r['doc_cells']} = {r['doc_accuracy_strict']}%")
    print(f"  연결 칸: {r['link_correct']}/{r['link_cells']} = {r['link_accuracy']}%")
    print(f"  작업 완전 일치(문서 칸): {r['tasks_exact']}/{r['tasks']} = {r['task_exact_rate']}%")
    print(f"  작업 누락 {r['missed_tasks']}건(회차 평균 {r['missed_per_round']}), 정답셋에 없는 작업 {r['extra_tasks']}건(회차 평균 {r['extra_per_round']})")
    print(f"  실패 {r['failed']}회   입력 불가 {r['input_unavailable']}회   확인 필요 작업 {r['needs_review']}건   형식 오류 칸 {r['format_errors']}개")
    ra = r["round_accuracy"]
    if r["rounds"] > 1:
        print(f"  회차별 문서 칸 정확도: 평균 {ra['mean']}% · 최소 {ra['min']}% · 최대 {ra['max']}% ({r['rounds']}회차)")
    if r["consistency"] is not None:
        print(f"  반복 일치율: {r['consistency']}% (비교한 파일 {r['consistency_files']}건 중 모든 회차 결과가 같은 파일 {r['consistent_files']}건, 모든 회차 실패 파일 제외)")


def main() -> None:
    try:  # Windows 콘솔 코드 페이지에 없는 글자가 있어도 집계를 잃지 않게 한다
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="F1 추출 정확도 측정 (합성 계획서)")
    ap.add_argument("--mode", choices=MODES, default="rules")
    ap.add_argument("--samples", help="표본 폴더 (그 안에 answers/). 기본은 samples/")
    ap.add_argument("--repeat", type=int, default=1, help="같은 파일을 몇 번 돌릴지 (회차마다 채점, 반복 일치율)")
    ap.add_argument("--only", help="파일 이름 일부로 하나만")
    ap.add_argument("--json", help="결과를 JSON 으로 저장할 경로")
    args = ap.parse_args()
    r = measure(args.mode, args.only, Path(args.samples).resolve() if args.samples else None, args.repeat)
    print(f"추출 경로: {args.mode}   표본: {r['samples']}   반복: {r['repeat']}회   채점 값: {r['view']}")
    print(f"{'파일':48} {'경로':12} {'작업(정답/추출)':>14} {'문서 칸(완화/엄격/전체, 회차 합)':>26} {'연결 칸':>10} {'실패':>4}")
    for f in r["files"]:
        doc = f"{f['doc_correct']}/{f['doc_correct_strict']}/{f['doc_cells']}"
        link = f"{f['link_correct']}/{f['link_cells']}"
        print(f"{f['file']:48} {f['method']:12} {f['tasks_truth']:>6}/{f['tasks_got']:<7g} {doc:>26} {link:>10} {f['failed']:>4}")
        for w in f["warnings"]:
            print(f"    ! {w}")
    _print_summary(f"합계 ({r['view']})", r)
    if r["view"] == "final" and any("raw" in rec["views"] for rec in r["records"]):
        _print_summary("참고: 규칙 보정 없는 LLM 원답 (raw)", aggregate(r["records"], "raw"))
    print("\n칸별: " + " · ".join(f"{LABEL[k]} {v['correct']}/{v['total']}" for k, v in r["field_accuracy"].items() if v["total"]))
    s, nc = r["seconds"], r["seconds_no_cache_write"]
    if s["runs"]:
        print(f"시간(성공 {s['runs']}회 평균, uv 시작 제외): 전체 {s['total']}초 · LLM {s['llm']}초 · 파싱 {s['parse']}초")
        if nc["runs"] != s["runs"] and nc["runs"]:
            print(f"시간(cache_write 호출 제외 {nc['runs']}회): 전체 {nc['total']}초 · LLM {nc['llm']}초 · 파싱 {nc['parse']}초")
    if r["llm_calls"]:
        t = r["tokens"]
        print(f"LLM: 호출 {r['llm_calls']}회 · 입력 {t['in']} · 캐시 읽기 {t['cache_read']} · 캐시 쓰기 {t['cache_write']} · 출력 {t['out']} 토큰")
    if r["cost_usd"] is not None:
        print(f"비용: 실비 ${r['cost_usd']} (건당 ${r['cost_usd_per_run']}) · 명목 ${r['nominal_usd']} (건당 ${r['nominal_usd_per_run']})")
    for (file, error), n in Counter((f["file"], f["error"]) for f in r["failures"]).items():
        print(f"  실패 {n}회: {file}: {error}")
    if r["wrong"]:
        print("\n틀린 칸:")
        lines = Counter(f"{w['file']} / {w['task']} / {w['field']}: 정답 {w['truth']!r} → 추출 {w['got']!r}" for w in r["wrong"])
        for line, n in lines.items():
            print(f"  - {line}" + (f" ({n}회)" if n > 1 else ""))
    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n저장: {args.json}")


if __name__ == "__main__":
    main()
