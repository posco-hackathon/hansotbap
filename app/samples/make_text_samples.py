"""F1 비교 시험 표본: uniform/ 의 표준양식 엑셀을 같은 내용의 텍스트 파일로 옮겨 text/ 에 만든다.

    cd app/backend && uv run python ../samples/make_text_samples.py

입력이 같으면 결과도 바이트까지 같다. 정답셋은 uniform/answers/ 를 복사하고 "file" 값만 새 파일 이름으로 바꾼다.
협력사명·일정·인원은 모두 합성 데이터다.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "uniform"
TARGET = HERE / "text"
CONTRACTOR_HEADER = "업체명"  # 머리글 행을 찾는 표지이자, 파일 머리에 한 번만 적는 칸


def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, date):  # datetime 도 date 의 하위 형이다. 시각은 버린다
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def read_plan(path: Path) -> tuple[str, list[list[tuple[str, str]]]]:
    """엑셀에서 (업체명, 작업별 [(머리글, 값), ...]) 을 읽는다. 머리글과 순서는 엑셀의 머리글 행을 따른다."""
    rows = list(load_workbook(path, data_only=True)["작업계획"].iter_rows(values_only=True))
    header_at = next(i for i, row in enumerate(rows) if CONTRACTOR_HEADER in row)
    header = rows[header_at]
    contractor_col = header.index(CONTRACTOR_HEADER)
    columns = [(i, str(name)) for i, name in enumerate(header) if name is not None and i != contractor_col]
    task_rows = [row for row in rows[header_at + 1 :] if any(value is not None for value in row)]
    contractors = {row[contractor_col] for row in task_rows}
    if len(contractors) != 1:
        raise ValueError(f"{path.name}: 파일 하나에 업체 한 곳이어야 한다: {sorted(map(str, contractors))}")
    tasks = [[(name, cell_text(row[i])) for i, name in columns] for row in task_rows]
    return str(contractors.pop()), tasks


def render_text(contractor: str, tasks: list[list[tuple[str, str]]]) -> str:
    blocks = [f"작업계획서 (합성 데이터)\n{CONTRACTOR_HEADER}: {contractor}"]
    for number, task in enumerate(tasks, start=1):
        blocks.append("\n".join([f"[작업 {number}]", *(f"{name}: {value}" for name, value in task)]))
    return "\n\n".join(blocks) + "\n"


def render_answer(stem: str, text_name: str) -> str:
    answer = json.loads((SOURCE / "answers" / f"{stem}.json").read_text(encoding="utf-8"))
    answer["file"] = text_name  # 키 순서는 그대로 남는다
    return json.dumps(answer, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    answers_dir = TARGET / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(SOURCE.glob("가상-*_표준양식_작업계획.xlsx"))
    task_count = 0
    for source in sources:
        contractor, tasks = read_plan(source)
        text_path = TARGET / f"{source.stem}.txt"
        # 운영체제와 무관하게 줄바꿈을 \n 으로 고정하려고 바이트로 쓴다
        text_path.write_bytes(render_text(contractor, tasks).encode("utf-8"))
        (answers_dir / f"{source.stem}.json").write_bytes(render_answer(source.stem, text_path.name).encode("utf-8"))
        task_count += len(tasks)
    print(f"텍스트 표본 {len(sources)}건, 작업 {task_count}개")


if __name__ == "__main__":
    main()
