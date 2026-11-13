"""F1 계획서 추출 비교 시험: 같은 표본을 조건별로 돌려 모델별로 기록하고 보고서용 표를 만든다. 표본은 모두 합성 데이터다.

    cd app/backend
    uv run python ../samples/compare_f1.py --model claude-haiku-5-5 --effort high --dry-run
    uv run python ../samples/compare_f1.py --model claude-haiku-5-5 --effort high --out <폴더> --budget-usd 1 --smoke
    uv run python ../samples/compare_f1.py --model claude-haiku-5-5 --effort high --out <폴더> --budget-usd 1
    uv run python ../samples/compare_f1.py --report <폴더> --markdown <파일>

config 가 import 시점에 값을 읽으므로, 인자를 파싱해 환경 변수를 넣은 뒤에 accuracy 를 불러온다 (.env 는 고치지 않는다).
한 프로세스 안에서는 순차로만 돌린다: 토큰 기록이 프로세스 전역이고, 동시 요청은 프롬프트 캐시를 읽지 못한다.
LLM 호출은 accuracy.run_once → llm/provider.py 뒤에서만 한다.

종료 코드: 0 정상 · 1 설정·입력 오류 · 2 예산 초과로 중단 · 3 응답 모델 불일치로 중단
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
FOLDERS = {"samples": HERE, "variants": HERE / "variants", "uniform": HERE / "uniform", "text": HERE / "text"}
SHUFFLE_SEED = 20261109  # 회차 안의 순서를 섞는 기준 시드 [팀 설정값]
EFFORTS = ("low", "medium", "high", "xhigh", "max")
EXIT_OK, EXIT_SETUP, EXIT_BUDGET, EXIT_MODEL = 0, 1, 2, 3

MACHINE_PDF = "가상-기계J_장입설비_설치계획서.pdf"
VESSEL_PDF = "가상-제관F_하강관_가스청정_보수계획.pdf"
SMOKE_TEXT = "가상-기계J_표준양식_작업계획.txt"
ORIG5 = (
    MACHINE_PDF,
    "가상-배관O_가스라인_복구_작업계획서.hwpx",
    "가상-비계N_비계_설치해체_작업계획.hwpx",
    VESSEL_PDF,
    "가상-축로I_노체축조_주간계획.xlsx",
)
VARIANT_PDFS = (
    "가상-기계J_v3_문장형_PDF.pdf",
    "가상-기계J_v4_PDF_작업기간_한글날짜.pdf",
    "가상-배관O_v2_PDF_머리업체_한글날짜.pdf",
    "가상-비계N_v1_PDF_기간한칸_한글날짜.pdf",
    "가상-제관F_v3_PDF_두자리연도_머리업체.pdf",
    "가상-제관F_v4_문장형_PDF.pdf",
    "가상-축로I_v1_PDF_첫행업체_점날짜.pdf",
)
PDF9 = (MACHINE_PDF, VESSEL_PDF, *VARIANT_PDFS)
# 13개 작업을 한 번씩 담는 PDF 부분집합
PDF5 = (
    MACHINE_PDF,
    VESSEL_PDF,
    "가상-축로I_v1_PDF_첫행업체_점날짜.pdf",
    "가상-배관O_v2_PDF_머리업체_한글날짜.pdf",
    "가상-비계N_v1_PDF_기간한칸_한글날짜.pdf",
)
SET_SIZE = {"PDF9": 9, "ALL25": 25, "UNIFORM5": 5, "TEXT5": 5}


@dataclass(frozen=True)
class Condition:
    id: str
    mode: str
    sample_set: str
    repeat: int


CONDITIONS = (
    Condition("llm_only", "llm-file", "PDF9", 3),
    Condition("parse_llm", "llm", "ALL25", 3),
    Condition("uniform_rules", "rules", "UNIFORM5", 3),
    Condition("uniform_llm", "llm", "UNIFORM5", 3),
    Condition("text_llm", "llm", "TEXT5", 3),
    Condition("parse_rules", "rules", "ALL25", 3),
    Condition("auto", "auto", "ALL25", 1),
)
CONDITION = {c.id: c for c in CONDITIONS}
# 스모크에 없는 조건은 양식이 가까운 조건의 토큰으로 비용을 어림한다
ESTIMATE_PROXY = {"llm_only": "llm_only", "parse_llm": "parse_llm", "uniform_llm": "text_llm", "text_llm": "text_llm", "auto": "parse_llm"}


class SetupError(Exception):
    """시작 전에 멈춰야 하는 설정·입력 오류."""


def say(text: str) -> None:
    print(text, flush=True)


# ── 설정 ──
def _import_accuracy():
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import accuracy

    return accuracy


def load_accuracy(model: str, effort: str):
    """환경 변수를 넣고 accuracy 를 불러온 뒤, 설정이 요청과 같은지 확인한다."""
    os.environ.update(CLAUDE_MODEL=model, LLM_EFFORT=effort, LLM_PROVIDER="claude", LLM_FALLBACKS="false")
    acc = _import_accuracy()
    # 실패 사유는 record 의 error 로 남긴다. 외부 오류 문구를 거르지 않은 채 콘솔에 내보내는 경고 로그는 끈다
    logging.getLogger("llm.extract").setLevel(logging.ERROR)
    s = acc.settings
    got = (s.claude_model, s.llm_effort, s.llm_provider, s.llm_fallbacks)
    want = (model, effort, "claude", False)
    if got != want:
        raise SetupError(f"설정이 요청과 다릅니다 (요청 {want}, 실제 {got}). 같은 프로세스에서 다른 설정으로 accuracy 를 이미 불렀는지 확인하세요")
    if model not in acc.PRICES:
        raise SetupError(f"단가표(PRICES)에 없는 모델입니다: {model} (있는 모델: {', '.join(acc.PRICES)})")
    return acc


# ── 표본·작업 ──
@dataclass(frozen=True)
class Job:
    condition: str
    mode: str
    sample: Path
    truth: dict
    round: int

    @property
    def key(self) -> tuple:
        return (self.condition, self.truth["file"], self.round)


def resolve_samples(acc) -> dict[str, list[tuple[Path, dict]]]:
    """표본 묶음 → (경로, 정답) 목록. 파일이나 정답셋이 하나라도 없으면 건너뛰지 않고 SetupError 로 멈춘다."""
    by_folder = {key: {s.name: (s, t) for s, t in acc.load_truths(path)} for key, path in FOLDERS.items()}
    problems: list[str] = []

    def named(folder: str, names: tuple[str, ...]) -> list[tuple[Path, dict]]:
        out = []
        for name in names:
            entry = by_folder[folder].get(name)
            if entry is None or not entry[0].is_file():
                problems.append(f"{folder} 폴더에 파일 또는 정답셋이 없습니다: {name}")
            else:
                out.append(entry)
        return out

    def whole(folder: str, count: int) -> list[tuple[Path, dict]]:
        names = sorted(by_folder[folder])
        on_disk = sorted(p.name for p in FOLDERS[folder].glob("*") if p.is_file() and p.suffix.lower() in acc.PARSERS)
        if names != on_disk or len(names) != count:
            problems.append(f"{folder} 폴더는 표본과 정답셋이 같은 {count}건이어야 합니다 (정답셋 {len(names)}건, 파일 {len(on_disk)}건)")
        return named(folder, tuple(names))

    variants = whole("variants", 20)
    groups = {
        "PDF9": named("samples", PDF9[:2]) + named("variants", VARIANT_PDFS),
        "ALL25": named("samples", ORIG5) + variants,
        "UNIFORM5": whole("uniform", 5),
        "TEXT5": whole("text", 5),
    }
    if problems:
        raise SetupError("표본 확인 실패\n  " + "\n  ".join(problems))
    return groups


def build_rounds(samples: dict[str, list[tuple[Path, dict]]]) -> list[list[Job]]:
    """회차별 작업 목록. 회차 안의 순서는 고정 시드로 섞어 모델끼리 같게 한다."""
    rounds: list[list[Job]] = []
    for rnd in range(max(c.repeat for c in CONDITIONS)):
        jobs = [Job(c.id, c.mode, s, t, rnd) for c in CONDITIONS if rnd < c.repeat for s, t in samples[c.sample_set]]
        random.Random(SHUFFLE_SEED + rnd).shuffle(jobs)
        rounds.append(jobs)
    return rounds


# ── 실행 ──
class _CaptureProvider:
    """provider 를 감싸 LLMPlan 을 sink 에 남긴다. run_once 의 record 에는 읽어 낸 값이 없어서 스모크에서 쓴다."""

    def __init__(self, inner, sink: list) -> None:
        self.inner = inner
        self.sink = sink

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def model(self) -> str:
        return self.inner.model

    def complete(self, system, user, max_tokens: int = 2048, timeout: float | None = None) -> str:
        return self.inner.complete(system, user, max_tokens=max_tokens, timeout=timeout)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed(texts)

    def extract(self, system, user, schema, max_tokens: int = 16000, timeout: float | None = None):
        plan = self.inner.extract(system, user, schema, max_tokens=max_tokens, timeout=timeout)
        self.sink.append(plan)
        return plan


@dataclass
class RunResult:
    exit_code: int = EXIT_OK
    reason: str | None = None
    completed: int = 0
    total: int = 0
    reruns: int = 0
    spent_usd: float = 0.0
    records: list[dict] = field(default_factory=list)  # 웜업·재실행을 포함해 실행한 순서대로


def _scrubbed(acc, rec: dict) -> dict:
    """외부 오류 문구에 API 키가 섞여도 출력·저장되지 않게 지운다."""
    key = acc.settings.anthropic_api_key
    if not key:
        return rec
    return json.loads(json.dumps(rec, ensure_ascii=False).replace(key, "***"))


def _wrong_model(rec: dict, requested: str) -> str | None:
    seen = [rec.get("model"), *(c.get("model") for c in rec.get("calls", []))]
    return next((m for m in seen if m and m != requested), None)


def _needs_rerun(rec: dict) -> bool:
    return rec["status"] == "실패" and bool(rec["calls"]) and rec["calls"][-1]["error_kind"] == "transient"


def _progress(rec: dict, spent: float) -> str:
    view = rec["views"].get("final") or rec["views"].get("raw")
    cells = f"{view['doc_correct']}/{view['doc_cells']}" if view else "-"
    tag = " 웜업" if rec["warmup"] else " 재실행" if rec["rerun"] else ""
    return f"[{rec['condition']}{tag}] {rec['file']} 회차 {rec['round']} · {rec['status']} · 문서 칸 {cells} · {rec['total_seconds']:.1f}초 · 누적 ${spent:.4f}"


def run_jobs(
    acc,
    jobs: list[Job],
    out_path: Path,
    model: str,
    effort: str,
    budget_usd: float,
    provider_factory: Callable | None = None,
    warmup: tuple[Path, dict] | None = None,
    rerun: bool = True,
    capture: bool = False,
) -> RunResult:
    """작업을 주어진 순서대로 하나씩 돌려 out_path 에 한 줄씩 덧붙인다. out_path 가 이미 있으면 SetupError."""
    try:
        handle = out_path.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        raise SetupError(f"결과 파일이 이미 있습니다 (덮어쓰지 않습니다): {out_path}") from None

    result = RunResult(total=len(jobs))
    latest: dict[tuple, dict] = {}

    def execute(job: Job, is_warmup: bool = False, is_rerun: bool = False) -> dict:
        sink: list = []
        factory = provider_factory
        if capture:
            inner = provider_factory or acc.get_provider
            factory = lambda: _CaptureProvider(inner(), sink)  # noqa: E731
        rec = acc.run_once(job.sample, job.truth, job.mode, provider_factory=factory)
        rec.update(condition=job.condition, round=job.round, requested_model=model, requested_effort=effort, warmup=is_warmup, rerun=is_rerun)
        if capture:
            rec["plan_tasks"] = [{"name": t.name, "start_date": t.start_date, "end_date": t.end_date} for plan in sink[-1:] for t in plan.tasks]
        rec = _scrubbed(acc, rec)
        handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
        handle.flush()
        result.records.append(rec)
        result.spent_usd += rec["cost_usd"] or 0.0
        say(_progress(rec, result.spent_usd))
        return rec

    def halt(code: int, reason: str) -> RunResult:
        result.exit_code, result.reason = code, reason
        say(f"{reason}: 완료 {result.completed}/{result.total}건 · 재실행 {result.reruns}건 · 누적 ${result.spent_usd:.4f}")
        return result

    def halt_model(rec: dict, wrong: str) -> RunResult:
        return halt(EXIT_MODEL, f"응답 모델 불일치로 중단 (요청 {model}, 응답 {wrong}, 조건 {rec['condition']}, 파일 {rec['file']}, 회차 {rec['round']})")

    def over_budget() -> bool:
        return result.spent_usd > budget_usd

    with handle:
        if warmup is not None:
            rec = execute(Job("warmup", "llm", warmup[0], warmup[1], -1), is_warmup=True)  # 캐시를 데우는 호출. 통계에서 빠지고 비용에는 든다
            if wrong := _wrong_model(rec, model):
                return halt_model(rec, wrong)

        for job in jobs:
            if over_budget():
                return halt(EXIT_BUDGET, "예산 초과로 중단")
            rec = execute(job)
            result.completed += 1
            latest[job.key] = rec
            if wrong := _wrong_model(rec, model):
                return halt_model(rec, wrong)

        if rerun:
            for job in [j for j in jobs if _needs_rerun(latest[j.key])]:
                if over_budget():
                    return halt(EXIT_BUDGET, "예산 초과로 중단")
                rec = execute(job, is_rerun=True)
                result.reruns += 1
                latest[job.key] = rec
                if wrong := _wrong_model(rec, model):
                    return halt_model(rec, wrong)
            say(f"일시 장애 재실행: {result.reruns}건")
    return result


# ── --dry-run ──
def print_dry_run(rounds: list[list[Job]], model: str, effort: str) -> None:
    say(f"모델 {model} · effort {effort} · LLM 을 부르지 않는 점검")
    say(f"{'조건':14} {'mode':9} {'표본':>4} {'반복':>4} {'작업':>4}  LLM 호출")
    jobs = [j for r in rounds for j in r]
    fixed, capped = 1, 0  # 웜업 1회
    for c in CONDITIONS:
        n = sum(1 for j in jobs if j.condition == c.id)
        if c.mode in ("llm", "llm-file"):
            calls, fixed = str(n), fixed + n
        elif c.mode == "auto":
            calls, capped = f"최대 {n} (표 규칙으로 끝나지 않는 파일만)", n
        else:
            calls = "0"
        say(f"{c.id:14} {c.mode:9} {SET_SIZE[c.sample_set]:>4} {c.repeat:>4} {n:>4}  {calls}")
    say(f"{'웜업':14} {'llm':9} {1:>4} {1:>4} {1:>4}  1 (통계 제외, 비용 포함)")
    say(f"예상 LLM 호출 합계: {fixed}회 (웜업 1 포함) + auto 최대 {capped}회 = 최대 {fixed + capped}회. 일시 장애 재실행은 제외")
    for rnd, round_jobs in enumerate(rounds):
        say(f"\n회차 {rnd}: 작업 {len(round_jobs)}건, 앞 15개")
        for i, j in enumerate(round_jobs[:15], start=1):
            say(f"  {i:>2}. {j.condition:14} {j.mode:9} {j.truth['file']}")


# ── --smoke ──
def _usd(value: float | None) -> str:
    return "-" if value is None else f"${value:.6f}"


def _cells(rec: dict, view: str) -> str:
    v = rec["views"].get(view)
    return f"{v['doc_correct']}/{v['doc_cells']}" if v else "-"


def _plan_text(tasks: list[dict], i: int) -> str:
    if i >= len(tasks):
        return "(행 없음)"
    t = tasks[i]
    return f"{t['name']} | {t['start_date']} ~ {t['end_date']}"


def print_smoke(acc, result: RunResult, model: str) -> None:
    jobs = [r for r in result.records if not r["warmup"]]
    say("\n── 작업별 결과 ──")
    for r in jobs:
        t = r["tokens"]
        say(f"{r['condition']} · {r['file']}")
        say(f"  status={r['status']} · error={r['error']} · method={r['method']} · 응답 모델={r['model']} · stop={r['stop']}")
        say(f"  호출 {r['llm_seconds']:.2f}초 · in={t['in']} cache_read={t['cache_read']} cache_write={t['cache_write']} out={t['out']} · cache_read {'있음' if t['cache_read'] else '없음'} · 실비 {_usd(r['cost_usd'])}")
        say(f"  문서 칸 맞음/전체: raw {_cells(r, 'raw')} · final {_cells(r, 'final')} · 형식 오류 {r['format_errors']}개")

    by_condition = {r["condition"]: r for r in jobs}
    only, parsed = by_condition.get("llm_only"), by_condition.get("parse_llm")
    if only and parsed:
        say("\n── 읽어 낸 작업명·날짜 (한글 깨짐 확인: llm_only 와 parse_llm raw 를 나란히) ──")
        for i in range(max(len(only["plan_tasks"]), len(parsed["plan_tasks"]), 1)):
            say(f"  {i + 1}. llm_only      : {_plan_text(only['plan_tasks'], i)}")
            say(f"     parse_llm raw : {_plan_text(parsed['plan_tasks'], i)}")
        for r in (only, parsed):
            say(f"  {r['condition']} raw 틀린 칸:")
            for w in r["views"].get("raw", {}).get("wrong", []) or [None]:
                say("    (없음)" if w is None else f"    {w['task']} / {w['field']}: 정답 {w['truth']!r} → 추출 {w['got']!r}")

    say("\n── 전수 비용 재추정 (추정값: 스모크 조건별 호출 1건의 토큰을 곱한 값이고, 파일 크기가 달라 실제와 다를 수 있다) ──")
    price = acc.PRICES[model]
    usage: dict[str, tuple[float, float, float]] = {}
    for r in jobs:
        used = [c["tokens"] for c in r["calls"] if c["tokens"]]
        if used:
            total_in = sum(u["in"] + u["cache_read"] + u["cache_write"] for u in used)
            usage[r["condition"]] = (total_in / len(used), sum(u["cache_read"] for u in used) / total_in if total_in else 0.0, sum(u["out"] for u in used) / len(used))
    total, unknown = 0.0, []
    for cid, proxy in ESTIMATE_PROXY.items():
        c = CONDITION[cid]
        calls = SET_SIZE[c.sample_set] * c.repeat
        label = f"호출 {'상한 ' if c.mode == 'auto' else ''}{calls}회"
        note = "" if proxy == cid else f" ({proxy} 스모크 값으로 대신)"
        if proxy not in usage:
            unknown.append(cid)
            say(f"  {cid}: {label} · 토큰 기록 없음, 추정 불가{note}")
            continue
        avg_in, ratio, avg_out = usage[proxy]
        per_call = (avg_in * (1 - ratio) * price["in"] + avg_in * ratio * price["cache_read"] + avg_out * price["out"]) / 1_000_000
        total += per_call * calls
        say(f"  {cid}: {label} × (입력 {avg_in:.0f} · cache_read 비율 {ratio * 100:.1f}% · 출력 {avg_out:.0f}) = ${per_call * calls:.4f}{note}")
    warm = sum(r["cost_usd"] or 0.0 for r in result.records if r["warmup"])
    suffix = f" · 추정 불가 조건: {', '.join(unknown)}" if unknown else ""
    say(f"  합계(추정): ${total + warm:.4f} (웜업 실비 ${warm:.4f} 포함, 일시 장애 재실행 제외){suffix}")


def _smoke_jobs(samples: dict[str, list[tuple[Path, dict]]]) -> list[Job]:
    entry = {s.name: (s, t) for group in samples.values() for s, t in group}
    picks = (("llm_only", MACHINE_PDF), ("parse_llm", MACHINE_PDF), ("text_llm", SMOKE_TEXT))
    return [Job(cid, CONDITION[cid].mode, *entry[name], 0) for cid, name in picks]


# ── --report ──
@dataclass(frozen=True)
class Row:
    label: str
    condition: str
    view: str
    only: frozenset[str] | None = None
    exclude: frozenset[str] = frozenset()


_PDF5, _PDF9, _ORIG5 = frozenset(PDF5), frozenset(PDF9), frozenset(ORIG5)
_LLM_FINAL = "② 파싱+LLM 최종 (parse_llm · final)"
_LLM_RAW = "② 파싱+LLM 원답 (parse_llm · raw)"
_RULES = "참고 파싱+규칙 (parse_rules · final)"
_AUTO = "참고 auto (final)"
TABLES = (
    ("table1", "표 1. 같은 내용 13개 작업 (PDF5 기준)", (
        Row("① LLM만 (llm_only · raw)", "llm_only", "raw", only=_PDF5),
        Row(_LLM_RAW, "parse_llm", "raw", only=_PDF5),
        Row(_LLM_FINAL, "parse_llm", "final", only=_PDF5),
        Row("③-a 통일 엑셀+규칙 (uniform_rules · final)", "uniform_rules", "final"),
        Row("③-b 통일 엑셀+LLM (uniform_llm · final)", "uniform_llm", "final"),
        Row("③-c 통일 텍스트+LLM (text_llm · final)", "text_llm", "final"),
        Row(_RULES, "parse_rules", "final", only=_PDF5),
    )),
    ("table2", "표 2. 같은 PDF 9건 쌍 비교", (
        Row("① LLM만 (llm_only · raw)", "llm_only", "raw"),
        Row(_LLM_RAW, "parse_llm", "raw", only=_PDF9),
        Row(_LLM_FINAL, "parse_llm", "final", only=_PDF9),
    )),
    ("table3", "표 3. 변형 20건", (
        Row(_LLM_FINAL, "parse_llm", "final", exclude=_ORIG5),
        Row(_LLM_RAW, "parse_llm", "raw", exclude=_ORIG5),
        Row(_RULES, "parse_rules", "final", exclude=_ORIG5),
        Row(_AUTO, "auto", "final", exclude=_ORIG5),
    )),
    ("table4", "표 4. 전체 25건", (
        Row(_LLM_FINAL, "parse_llm", "final"),
        Row(_LLM_RAW, "parse_llm", "raw"),
        Row(_RULES, "parse_rules", "final"),
        Row(_AUTO, "auto", "final"),
    )),
)
FIELD_ROWS = (
    Row("① LLM만 (llm_only · raw)", "llm_only", "raw"),
    Row(_LLM_RAW, "parse_llm", "raw"),
    Row(_LLM_FINAL, "parse_llm", "final"),
    Row("③-a 통일 엑셀+규칙 (uniform_rules · final)", "uniform_rules", "final"),
    Row("③-b 통일 엑셀+LLM (uniform_llm · final)", "uniform_llm", "final"),
    Row("③-c 통일 텍스트+LLM (text_llm · final)", "text_llm", "final"),
    Row(_RULES, "parse_rules", "final"),
    Row(_AUTO, "auto", "final"),
)
METRIC_HEAD = (
    "조건", "문서 칸(완화)", "엄격", "맞음/전체", "연결 칸", "작업 완전 일치", "회차 평균 누락/추가", "회차별 최소~최대", "반복 일치율",
    "건당 시간 전체(초)", "건당 LLM(초)", "건당 파싱(초)", "건당 실비", "건당 명목비", "실패",
)


def read_records(path: Path) -> list[dict]:
    """jsonl → 웜업을 뺀 record. 같은 (condition, file, round) 는 가장 나중 줄만 남긴다."""
    latest: dict[tuple, dict] = {}
    with path.open(encoding="utf-8") as f:
        for no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise SetupError(f"{path} {no}번째 줄을 읽지 못했습니다: {e}") from None
            if not rec.get("warmup"):
                latest[(rec["condition"], rec["file"], rec["round"])] = rec
    return list(latest.values())


def _select(records: list[dict], row: Row) -> list[dict]:
    chosen = [r for r in records if r["condition"] == row.condition and (row.only is None or r["file"] in row.only) and r["file"] not in row.exclude]
    return sorted(chosen, key=lambda r: (r["file"], r["round"]))


def _pct(correct: int, total: int) -> str:
    return f"{100 * correct / total:.1f}% ({correct}/{total})" if total else "-"


def _ratio(pair: tuple[int, int]) -> float:
    return pair[0] / pair[1] if pair[1] else 0.0


def _round_counts(records: list[dict], view: str) -> list[tuple[int, int]]:
    """회차별 (맞음, 전체). aggregate 의 회차별 정확도와 같은 기준(같은 파일 record 의 순서)이다."""
    by_file: dict[str, list[dict]] = {}
    for r in records:
        if r["status"] != "입력 불가" and view in r["views"]:
            by_file.setdefault(r["file"], []).append(r["views"][view])
    counts = []
    for k in range(max((len(vs) for vs in by_file.values()), default=0)):
        round_views = [vs[k] for vs in by_file.values() if k < len(vs)]
        counts.append((sum(v["doc_correct"] for v in round_views), sum(v["doc_cells"] for v in round_views)))
    return counts


def _seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _metric_cells(label: str, a: dict | None, counts: list[tuple[int, int]]) -> list[str]:
    if a is None:
        return [label, "기록 없음", *["-"] * (len(METRIC_HEAD) - 2)]
    low, high = min(counts, key=_ratio, default=(0, 0)), max(counts, key=_ratio, default=(0, 0))
    span = f"{_pct(*low)} ~ {_pct(*high)}" if counts else "-"
    same = f"{a['consistency']:.1f}% ({a['consistent_files']}/{a['consistency_files']})" if a["consistency"] is not None else "-"
    sec = a["seconds_no_cache_write"]
    return [
        label,
        _pct(a["doc_correct"], a["doc_cells"]),
        _pct(a["doc_correct_strict"], a["doc_cells"]),
        f"{a['doc_correct']}/{a['doc_cells']}",
        _pct(a["link_correct"], a["link_cells"]),
        _pct(a["tasks_exact"], a["tasks"]),
        f"{a['missed_per_round']} / {a['extra_per_round']}",
        span,
        same,
        _seconds(sec["total"]),
        _seconds(sec["llm"]),
        _seconds(sec["parse"]),
        _usd(a["cost_usd_per_run"]),
        _usd(a["nominal_usd_per_run"]),
        str(a["failed"]),
    ]


def _table_lines(head, rows) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *("| " + " | ".join(r) + " |" for r in rows), ""]


def _pair_files(acc, records: list[dict]) -> list[dict]:
    """표 2 파일별 비교: 문서 칸 정확도와 ① 대비 차이(퍼센트포인트)."""
    columns = (("llm_only_raw", "llm_only", "raw"), ("parse_llm_raw", "parse_llm", "raw"), ("parse_llm_final", "parse_llm", "final"))
    out = []
    for name in PDF9:
        row: dict = {"file": name}
        for key, condition, view in columns:
            chosen = _select(records, Row("", condition, view, only=frozenset({name})))
            a = acc.aggregate(chosen, view) if chosen else None
            row[key] = {"correct": a["doc_correct"], "total": a["doc_cells"]} if a else None
        base = row["llm_only_raw"]
        for key, target in (("diff_raw", row["parse_llm_raw"]), ("diff_final", row["parse_llm_final"])):
            row[key] = round(100 * (target["correct"] / target["total"] - base["correct"] / base["total"]), 1) if base and target and base["total"] and target["total"] else None
        out.append(row)
    return out


def _pair_cell(value: dict | None) -> str:
    return _pct(value["correct"], value["total"]) if value else "기록 없음"


def _diff_cell(value: float | None) -> str:
    return "-" if value is None else f"{value:+.1f}"


def build_report(acc, folder: Path) -> tuple[str, dict]:
    paths = sorted(folder.glob("records_*.jsonl"))
    if not paths:
        raise SetupError(f"records_*.jsonl 이 없습니다: {folder}")
    lines = ["# F1 계획서 추출 비교 시험 결과", ""]
    payload: dict = {"models": {}}
    for path in paths:
        model = path.stem.removeprefix("records_")
        records = read_records(path)
        effort = "·".join(sorted({str(r.get("requested_effort", "(기록 없음)")) for r in records})) or "(기록 없음)"
        criteria = [
            "합성 데이터(`가상-…`)로 잰 값이다. 실제 계획서의 정확도가 아니다.",
            f"모델 `{model}` · effort `{effort}` · 반복 " + ", ".join(f"{c.id} {c.repeat}회" for c in CONDITIONS),
            "표본은 같은 13개 작업을 양식만 바꿔 되풀이한 것이라 칸이 서로 독립이 아니다. 칸 수를 독립 관측 수로 읽지 않는다.",
            "`llm_only` 는 PDF 를 파서 없이 LLM 에 바로 넘기는 조건이라 PDF 만 가능하다. xlsx·hwpx 는 입력 불가다.",
            "건당 시간은 캐시 쓰기가 없는 성공 회차의 평균이고, 건당 비용은 비용이 기록된 회차의 평균이다.",
        ]
        for c in CONDITIONS:
            got, want = sum(1 for r in records if r["condition"] == c.id), SET_SIZE[c.sample_set] * c.repeat
            if got != want:
                criteria.append(f"**미완료:** `{c.id}` 는 {got}/{want}건만 기록되어 있다.")
        lines += [f"## 모델 `{model}`", "", *(f"- {c}" for c in criteria), ""]
        model_data: dict = {"effort": effort, "criteria": criteria, "tables": {}}

        for key, title, rows in TABLES:
            table_rows, raw_rows = [], []
            for row in rows:
                chosen = _select(records, row)
                a = acc.aggregate(chosen, row.view) if chosen else None
                counts = _round_counts(chosen, row.view)
                table_rows.append(_metric_cells(row.label, a, counts))
                raw_rows.append({"label": row.label, "condition": row.condition, "view": row.view, "round_counts": counts, "aggregate": a})
            lines += [f"### {title}", "", *_table_lines(METRIC_HEAD, table_rows)]
            model_data["tables"][key] = {"title": title, "rows": raw_rows}
            if key == "table2":
                pairs = _pair_files(acc, records)
                model_data["table2_files"] = pairs
                pair_rows = [[p["file"], _pair_cell(p["llm_only_raw"]), _pair_cell(p["parse_llm_raw"]), _pair_cell(p["parse_llm_final"]), _diff_cell(p["diff_raw"]), _diff_cell(p["diff_final"])] for p in pairs]
                lines += ["파일별 문서 칸 정확도 (완화, 회차 합산. 차이는 ① 대비 퍼센트포인트)", "", *_table_lines(("파일", "① raw", "② raw", "② final", "② raw − ①", "② final − ①"), pair_rows)]

        field_rows, raw_fields = [], []
        for row in FIELD_ROWS:
            chosen = _select(records, row)
            fields = acc.aggregate(chosen, row.view)["field_accuracy"] if chosen else None
            field_rows.append([row.label, *((_pct(fields[f]["correct"], fields[f]["total"]) if fields else "기록 없음") for f in acc.FIELDS)])
            raw_fields.append({"label": row.label, "condition": row.condition, "view": row.view, "field_accuracy": fields})
        lines += ["### 칸 표 (조건별 칸 정확도, 조건의 표본 전체)", "", *_table_lines(("조건", *(acc.LABEL[f] for f in acc.FIELDS)), field_rows)]
        model_data["field_table"] = raw_fields
        payload["models"][model] = model_data
    return "\n".join(lines), payload


def write_report(acc, folder: Path, markdown: Path) -> None:
    text, payload = build_report(acc, folder)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(text, encoding="utf-8")
    raw = markdown.with_suffix(".json")
    raw.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    say(f"저장: {markdown}\n저장: {raw}")


# ── 진입점 ──
class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # 종료 코드 2는 예산 초과 중단에만 쓴다
        self.print_usage(sys.stderr)
        self.exit(EXIT_SETUP, f"{self.prog}: 오류: {message}\n")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = _Parser(description="F1 계획서 추출 비교 시험 (합성 데이터)")
    ap.add_argument("--model", help="CLAUDE_MODEL 로 넣을 모델")
    ap.add_argument("--effort", choices=EFFORTS, help="LLM_EFFORT 로 넣을 값")
    ap.add_argument("--out", help="결과 jsonl 을 쓸 폴더")
    ap.add_argument("--budget-usd", type=float, help="누적 실비(달러)가 이 값을 넘으면 다음 작업을 시작하지 않는다")
    only = ap.add_mutually_exclusive_group()
    only.add_argument("--smoke", action="store_true", help="웜업 1회와 세 작업만 돌린다")
    only.add_argument("--dry-run", action="store_true", help="LLM 없이 호출 수와 순서만 출력한다")
    ap.add_argument("--report", help="records_*.jsonl 이 있는 폴더로 표를 만든다 (LLM 없음)")
    ap.add_argument("--markdown", help="--report 결과를 쓸 Markdown 파일. 같은 이름의 .json 도 쓴다")
    args = ap.parse_args(argv)
    if args.report:
        if not args.markdown:
            ap.error("--report 에는 --markdown 이 필요합니다")
        if args.model or args.effort or args.out or args.budget_usd is not None or args.smoke or args.dry_run:
            ap.error("--report 는 실행 인자와 함께 쓰지 않습니다")
        return args
    if args.markdown:
        ap.error("--markdown 은 --report 와 함께 씁니다")
    if not args.model or not args.effort:
        ap.error("--model 과 --effort 가 필요합니다")
    if not args.dry_run:
        if not args.out or args.budget_usd is None:
            ap.error("--out 과 --budget-usd 가 필요합니다")
        if args.budget_usd <= 0:
            ap.error("--budget-usd 는 0보다 커야 합니다")
    return args


def main(argv: list[str] | None = None, provider_factory: Callable | None = None) -> int:
    try:  # Windows 콘솔 코드 페이지에 없는 글자가 있어도 실행을 잃지 않게 한다
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    args = parse_args(argv)
    try:
        if args.report:
            write_report(_import_accuracy(), Path(args.report), Path(args.markdown))
            return EXIT_OK
        acc = load_accuracy(args.model, args.effort)
        samples = resolve_samples(acc)
        rounds = build_rounds(samples)
        if args.dry_run:
            print_dry_run(rounds, args.model, args.effort)
            return EXIT_OK
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        warmup = samples["TEXT5"][0]
        if args.smoke:
            result = run_jobs(
                acc, _smoke_jobs(samples), out / f"smoke_{args.model}.jsonl", args.model, args.effort, args.budget_usd,
                provider_factory=provider_factory, warmup=warmup, rerun=False, capture=True,
            )
            print_smoke(acc, result, args.model)
            return result.exit_code
        path = out / f"records_{args.model}.jsonl"
        result = run_jobs(
            acc, [j for r in rounds for j in r], path, args.model, args.effort, args.budget_usd,
            provider_factory=provider_factory, warmup=warmup,
        )
        if result.exit_code == EXIT_OK:
            say(f"완료: {result.completed}/{result.total}건 · 재실행 {result.reruns}건 · 누적 ${result.spent_usd:.4f} · 저장: {path}")
        return result.exit_code
    except SetupError as e:
        print(f"오류: {e}", file=sys.stderr, flush=True)
        return EXIT_SETUP


if __name__ == "__main__":
    sys.exit(main())
