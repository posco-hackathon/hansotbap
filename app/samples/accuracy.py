"""F1 추출 정확도 측정: samples/ 의 계획서를 추출기에 넣고 answers/ 의 정답셋과 칸별로 비교한다.

    cd app/backend && uv run python ../samples/accuracy.py            # 표 규칙 경로 (LLM 안 부름)
    cd app/backend && uv run python ../samples/accuracy.py --mode llm  # LLM 경로 (.env 의 ANTHROPIC_API_KEY 필요)
    cd app/backend && uv run python ../samples/accuracy.py --json ../samples/answers/_last_result.json
    cd app/backend && uv run python ../samples/accuracy.py --mode llm-raw            # LLM만: 표 구조 없이 글자만 통째로
    cd app/backend && uv run python ../samples/accuracy.py --samples ../samples/variants --repeat 3   # 변형 표본, 3회 반복

경로(--mode): rules = 파싱 + 표 규칙 · llm = 파싱 + LLM · auto = 규칙 먼저, 못 읽으면 LLM · llm-raw = LLM만(구조 없는 글자)
결과 보고서용 지표: 칸 정확도 · 작업 완전 일치율 · 누락/추가 작업 · 확인 필요 작업 · 건당 시간 · LLM 토큰 · 반복 일치율

칸: 업체 · 작업명 · 구역 · 시작일 · 종료일 · 주야간 · 투입 인원 · 작업 유형 · 선행 작업 · 기준 일정 ID (10칸).
정답셋의 값이 null 이면 그 칸은 세지 않는다 (예: '주야간' 연속 작업은 한쪽으로 정할 수 없다).
틀린 칸 목록은 프롬프트·규칙 수정용으로 그대로 전달한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from llm.extract import extract_plan  # noqa: E402
from parsers.docx import parse_docx  # noqa: E402
from parsers.hwpx import parse_hwpx  # noqa: E402
from parsers.normalize import name_similarity  # noqa: E402
from parsers.pdf import parse_pdf  # noqa: E402
from parsers.xlsx import parse_xlsx  # noqa: E402
from parsers.document import ParsedDocument  # noqa: E402

HERE = Path(__file__).resolve().parent
PARSERS = {".pdf": parse_pdf, ".xlsx": parse_xlsx, ".hwpx": parse_hwpx, ".docx": parse_docx}
FIELDS = ("contractor", "name", "zone_id", "start", "end", "shift", "headcount", "hazards", "predecessors", "wbs_id")
LABEL = {
    "contractor": "업체", "name": "작업명", "zone_id": "구역", "start": "시작일", "end": "종료일",
    "shift": "주야간", "headcount": "투입 인원", "hazards": "작업 유형", "predecessors": "선행 작업", "wbs_id": "기준 일정 ID",
}


def _squash(t: str | None) -> str:
    return re.sub(r"[\s·,./()\-~]", "", t or "")


def extracted_row(et) -> dict:
    t = et.task
    return {
        "contractor": t.contractor,
        "name": t.name,
        "zone_id": t.zone_id or None,
        "start": t.start.date().isoformat(),
        "end": t.end.date().isoformat(),
        "shift": t.shift.value if t.shift else None,
        "headcount": t.crew,
        "hazards": sorted(h.value for h in t.hazards),
        "predecessors": sorted(t.predecessors),
        "wbs_id": et.wbs_id,
    }


def same(field: str, truth, got) -> bool:
    if field in ("contractor", "name"):
        return _squash(truth) == _squash(got)
    if field in ("hazards", "predecessors"):
        return sorted(truth or []) == sorted(got or [])
    return truth == got


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


# ── LLM만(조건 ①): 파서가 나눈 표·위치표식을 버리고 글자만 이어 붙여 LLM에 넘긴다 ──
@dataclass
class RawDocument(ParsedDocument):
    def text(self) -> str:
        return "\n".join(re.sub(r"\s*\|\s*", " ", s.text) for s in self.segments)


def raw_document(doc: ParsedDocument) -> RawDocument:
    return RawDocument(filename=doc.filename, file_type=doc.file_type, segments=list(doc.segments), tables=[])


# ── LLM 토큰: provider 가 남기는 사용량 로그를 가로챈다 (Claude 만 기록) ──
class _UsageTap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.calls: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if str(record.msg).startswith("claude extract") and record.args and len(record.args) >= 6:
            _, _, i, cr, cw, o = record.args[:6]
            self.calls.append({"in": i or 0, "cache_read": cr or 0, "cache_write": cw or 0, "out": o or 0})


USAGE = _UsageTap()
logging.getLogger("llm.provider").addHandler(USAGE)
logging.getLogger("llm.provider").setLevel(logging.INFO)


def _sig(rows: list[dict]) -> str:
    return json.dumps(sorted(rows, key=lambda r: r["name"] or ""), ensure_ascii=False, sort_keys=True)


def _truth_cells(truth: dict) -> int:
    return sum(sum(1 for f in FIELDS if tt.get(f) is not None or f == "wbs_id") for tt in truth["tasks"])


def measure(mode: str, only: str | None = None, samples: Path | None = None, repeat: int = 1) -> dict:
    """repeat 회 돌려 정확도는 1회차, 시간은 평균, 반복 일치율은 모든 회차 결과가 같은 파일 비율로 낸다."""
    base = samples or HERE
    report = {"mode": mode, "samples": base.name, "repeat": repeat, "files": [], "cells": 0, "correct": 0,
              "tasks": 0, "tasks_exact": 0, "missed_tasks": 0, "extra_tasks": 0, "needs_review": 0,
              "seconds": [], "tokens": {"in": 0, "cache_read": 0, "cache_write": 0, "out": 0}, "llm_calls": 0,
              "consistent_files": 0, "failed": [], "wrong": [], "skipped": []}
    for ans_path in sorted((base / "answers").glob("*.json")):
        if ans_path.name.startswith("_"):
            continue
        truth = json.loads(ans_path.read_text(encoding="utf-8"))
        if only and only not in truth["file"]:
            continue
        # 표가 없어 LLM 으로만 읽히는 샘플(가상-제관F)은 rules 경로에서 빼고 센다 — "못 읽음"으로 정확도를 깎지 않게
        if mode == "rules" and truth.get("extraction") == "llm":
            report["skipped"].append(truth["file"])
            continue
        sample = base / truth["file"]
        runs, secs = [], []
        for _ in range(max(1, repeat)):
            t0 = time.perf_counter()
            n_calls = len(USAGE.calls)
            try:
                doc = PARSERS[sample.suffix](sample.read_bytes(), sample.name)
                if mode == "llm-raw":
                    doc = raw_document(doc)
                ex = extract_plan(doc, mode="llm" if mode == "llm-raw" else mode)
            except Exception as e:  # 규칙으로 못 읽는 양식(문장형 등)은 실패로 세고 계속
                ex = None
                if not any(f["file"] == truth["file"] for f in report["failed"]):
                    report["failed"].append({"file": truth["file"], "error": f"{type(e).__name__}: {e}"[:200]})
            secs.append(time.perf_counter() - t0)
            for c in USAGE.calls[n_calls:]:
                report["llm_calls"] += 1
                for k in report["tokens"]:
                    report["tokens"][k] += c[k]
            runs.append(ex)
        report["seconds"].append(statistics.mean(secs))
        ex = runs[0]
        if ex is None:
            n_cells = _truth_cells(truth)
            report["missed_tasks"] += len(truth["tasks"])
            report["tasks"] += len(truth["tasks"])
            report["cells"] += n_cells
            for tt in truth["tasks"]:
                report["wrong"].append({"file": truth["file"], "task": tt["name"], "field": "(파일 못 읽음)", "truth": tt["name"], "got": None})
            report["files"].append({"file": truth["file"], "method": "실패", "tasks_truth": len(truth["tasks"]), "tasks_got": 0,
                                    "cells": n_cells, "correct": 0, "warnings": [], "seconds": round(report["seconds"][-1], 3), "consistent": None})
            continue
        sigs = [_sig([extracted_row(t) for t in r.tasks]) if r else None for r in runs]
        consistent = all(x == sigs[0] for x in sigs)
        report["consistent_files"] += 1 if consistent else 0
        report["needs_review"] += sum(1 for t in ex.tasks if getattr(t, "needs_review", False))
        rows = [extracted_row(t) for t in ex.tasks]
        pairs = pair_tasks(truth["tasks"], rows)
        f_cells = f_ok = 0
        for tt, got in pairs:
            report["tasks"] += 1
            if got is None:
                report["missed_tasks"] += 1
                report["wrong"].append({"file": truth["file"], "task": tt["name"], "field": "(작업 누락)", "truth": tt["name"], "got": None})
                continue
            task_ok = True
            for field in FIELDS:
                if tt.get(field) is None and field != "wbs_id":
                    continue  # 정답이 없는 칸은 세지 않는다
                f_cells += 1
                if same(field, tt.get(field), got.get(field)):
                    f_ok += 1
                else:
                    task_ok = False
                    report["wrong"].append({"file": truth["file"], "task": tt["name"], "field": LABEL[field], "truth": tt.get(field), "got": got.get(field)})
            report["tasks_exact"] += 1 if task_ok else 0
        extra = len(rows) - sum(1 for _, g in pairs if g is not None)
        report["extra_tasks"] += extra
        report["files"].append({"file": truth["file"], "method": ex.method, "tasks_truth": len(truth["tasks"]), "tasks_got": len(rows), "cells": f_cells, "correct": f_ok, "warnings": ex.warnings,
                                "seconds": round(report["seconds"][-1], 3), "consistent": consistent})
        report["cells"] += f_cells
        report["correct"] += f_ok
    report["accuracy"] = round(100 * report["correct"] / report["cells"], 1) if report["cells"] else 0.0
    report["task_exact_rate"] = round(100 * report["tasks_exact"] / report["tasks"], 1) if report["tasks"] else 0.0
    report["sec_per_file"] = round(statistics.mean(report["seconds"]), 3) if report["seconds"] else 0.0
    report["sec_total"] = round(sum(report["seconds"]), 3)
    n = len([f for f in report["files"] if f["consistent"] is not None])
    report["consistency"] = round(100 * report["consistent_files"] / n, 1) if n and repeat > 1 else None
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="F1 추출 정확도 측정 (합성 계획서 5건)")
    ap.add_argument("--mode", choices=("auto", "rules", "llm", "llm-raw"), default="rules")
    ap.add_argument("--samples", help="표본 폴더 (그 안에 answers/). 기본은 samples/")
    ap.add_argument("--repeat", type=int, default=1, help="같은 파일을 몇 번 돌릴지 (시간 평균·반복 일치율)")
    ap.add_argument("--only", help="파일 이름 일부로 하나만")
    ap.add_argument("--json", help="결과를 JSON 으로 저장할 경로")
    args = ap.parse_args()
    r = measure(args.mode, args.only, Path(args.samples).resolve() if args.samples else None, args.repeat)
    print(f"추출 경로: {args.mode}   표본: {r['samples']}   반복: {r['repeat']}회")
    if r.get("skipped"):
        print(f"  (표가 없어 LLM 으로만 읽히는 {len(r['skipped'])}건 제외: {', '.join(r['skipped'])} — --mode llm 으로 재시)")
    print(f"{'파일':48} {'경로':12} {'작업(정답/추출)':>14} {'칸':>6} {'정답':>6} {'정확도':>7}")
    for f in r["files"]:
        acc = 100 * f["correct"] / f["cells"] if f["cells"] else 0
        print(f"{f['file']:48} {f['method']:12} {f['tasks_truth']:>6}/{f['tasks_got']:<7} {f['cells']:>6} {f['correct']:>6} {acc:>6.1f}%")
        for w in f["warnings"]:
            print(f"    ! {w}")
    print(f"\n합계: {r['correct']}/{r['cells']} 칸 = {r['accuracy']}%   작업 누락 {r['missed_tasks']}건, 정답셋에 없는 작업 {r['extra_tasks']}건")
    print(f"작업 완전 일치: {r['tasks_exact']}/{r['tasks']} = {r['task_exact_rate']}%   확인 필요 작업 {r['needs_review']}건   못 읽은 파일 {len(r['failed'])}건")
    print(f"시간: 건당 {r['sec_per_file']}초 · 합계 {r['sec_total']}초 (파싱 포함, uv 시작 제외)")
    if r["llm_calls"]:
        t = r["tokens"]
        print(f"LLM: 호출 {r['llm_calls']}회 · 입력 {t['in']} · 캐시 읽기 {t['cache_read']} · 캐시 쓰기 {t['cache_write']} · 출력 {t['out']} 토큰")
    if r["consistency"] is not None:
        print(f"반복 일치율: {r['consistency']}% (같은 파일 {r['repeat']}회 결과가 모두 같은 비율)")
    for f in r["failed"][:10]:
        print(f"  ✗ {f['file']}: {f['error']}")
    if r["wrong"]:
        print("\n틀린 칸:")
        for w in r["wrong"]:
            print(f"  - {w['file']} / {w['task']} / {w['field']}: 정답 {w['truth']!r} → 추출 {w['got']!r}")
    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n저장: {args.json}")


if __name__ == "__main__":
    main()
