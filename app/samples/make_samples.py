"""합성 협력사 계획서 8건 생성 (PDF 3 · 엑셀 1 · HWPX 3 · Word 1). 협력사명은 모두 가상, 모든 파일에 "합성 데이터" 표시.

    cd app/backend && uv run python ../samples/make_samples.py

양식은 일부러 서로 다르게 만든다(머리글 낱말·열 순서·날짜 표기·업체명 위치). F1 파서가 "양식을 강제하지 않아도"
읽을 수 있음을 보이기 위해서다. 여덟 건은 표 규칙으로 읽히고, 가상-제관F 한 건은 표가 아예 없는 공문 형식이라
LLM 추출 경로로 간다 (둘 다 되는 것을 보이는 게 목적이다). 작업은 data/gy2bf_wbs.csv(기준 일정)에서 골랐고, 아래 네 쌍이 충돌 4유형을 하나씩 낸다.

  S1 순서 위반  가상-배관O  P34 질소·가스 라인 연결을 02-26으로 앞당김  ↔ 가상-축로I P22 노흉 축조(~03-02)   R08·R07
  S2 위아래     가상-기계J  P23 노정 장입설비 설치(TOP)                  ↔ 가상-축로I P20 노저 축조(HEARTH)    R16
  S4 화기×가스  가상-제관F  P10 하강관 절단을 11-15로 앞당김              ↔ 원청-정비 P05 가스 퍼지(~11-15)     R04
  같은 시간·구역 가상-비계N  노흉 내부 비계 해체 03-01~                  ↔ 가상-축로I P22 노흉 축조(~03-02)    R17·R16
                가상-비계N  철피 외부 비계 설치 12-28~                   ↔ 가상-양중C P17 링블록 인양(~01-03)  R18·R20

정답셋은 answers/<파일명>.json 에 같이 만든다 (추출 정확도 비교용, accuracy.py).
"""

from __future__ import annotations

import datetime as dt
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
ANSWERS = HERE / "answers"
SYNTH = "※ 본 문서는 해커톤 시연용 합성 데이터이며 협력사명·일정·인원은 모두 가상입니다."
# PyMuPDF 내장 CJK 글꼴. 시스템 TTF(AppleGothic 등)를 insert_text 로 넣으면 보기엔 좋지만 PyMuPDF 가 글자를 다시 읽을 때
# 순서·띄어쓰기가 깨져(표 칸 "2 20 02 26 …") F1 파서가 못 읽는다. 계획서 샘플은 "읽히는 것"이 먼저라 내장 글꼴을 쓴다.
FONT_KW = {"fontname": "korea"}


# ──────────────────────────────────────────────────────────────────────
# 1. 가상-축로I — 엑셀 (기준 일정 그대로, 시드와 같은 파일명)
# ──────────────────────────────────────────────────────────────────────
def make_chukro_xlsx() -> tuple[Path, dict]:
    wb = Workbook()
    ws = wb.active
    ws.title = "작업계획"
    ws["A1"] = "주간 작업계획서 — 광양 2고로 개수 노체 축조 (합성 데이터)"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "업체명: 가상-축로I"
    ws["A3"] = "공종: 축로(내화물)   현장 책임자: 홍길동(가상)   제출일: 2027-01-18"
    ws["A4"] = SYNTH
    header = ["업체", "작업명", "작업위치", "시작일", "종료일", "주야간", "투입인원", "위험작업", "선행조건", "비고"]
    ws.append([])
    ws.append(header)
    for c in range(1, len(header) + 1):
        cell = ws.cell(row=6, column=c)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
        cell.alignment = Alignment(horizontal="center")
    rows = [
        ["가상-축로I", "노저 카본블록·세라믹컵 축조(연와정초)", "노저(hearth) 내부", dt.datetime(2027, 1, 21), dt.datetime(2027, 2, 15), "주간", 18, "밀폐공간", "노저 해체·청소 완료, 철피 용접 완료 후", "산소농도 측정 1일 2회"],
        [None, "풍구 레벨 내화물·풍구·냉각기 신설", "풍구 레벨", dt.datetime(2027, 2, 10), dt.datetime(2027, 2, 25), "주간", 14, "밀폐공간, 중량물", "노저 축조 완료 후", "호이스트 인양"],
        [None, "노복~노흉 내화물 축조·캐스터블", "노흉(shaft) 내부", dt.datetime(2027, 2, 5), dt.datetime(2027, 3, 2), "주간", 22, "밀폐공간, 고소", "스테이브·냉각판 설치 완료 후", "달비계 사용"],
    ]
    for r in rows:
        ws.append(r)
    for row in ws.iter_rows(min_row=7, max_row=9, min_col=4, max_col=5):
        for cell in row:
            cell.number_format = "yyyy-mm-dd"
    widths = [12, 38, 18, 12, 12, 8, 9, 16, 32, 20]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws2 = wb.create_sheet("안전조치")
    for line in [
        "노 내부 밀폐공간 작업 안전조치 (합성)",
        "1. 작업 전 산소농도(18~23.5%)·가연성가스·CO 측정, 결과를 출입 기록부에 기재",
        "2. 감시인 1명 출입구 상주, 구조장비(삼각대·공기호흡기) 비치",
        "3. 환기팬 연속 가동, 불활성가스(질소) 유입 가능 배관은 맹판 설치 확인",
        "4. 달비계·안전대 체결 확인(고소), 자재 인양 시 하부 출입 통제",
    ]:
        ws2.append([line])
    ws2.column_dimensions["A"].width = 90

    path = HERE / "가상-축로I_노체축조_주간계획.xlsx"
    wb.save(path)
    answer = {
        "file": path.name,
        "contractor": "가상-축로I",
        "format": "xlsx",
        "tasks": [
            {"wbs_id": "P20", "name": "노저 카본블록·세라믹컵 축조(연와정초)", "zone_id": "HEARTH", "start": "2027-01-21", "end": "2027-02-15", "shift": "day", "headcount": 18, "hazards": ["confined"], "predecessors": ["P16", "P18"]},
            {"wbs_id": "P21", "name": "풍구 레벨 내화물·풍구·냉각기 신설", "zone_id": "TUYERE", "start": "2027-02-10", "end": "2027-02-25", "shift": "day", "headcount": 14, "hazards": ["confined", "heavy_lift"], "predecessors": ["P20"]},
            {"wbs_id": "P22", "name": "노복~노흉 내화물 축조·캐스터블", "zone_id": "STACK", "start": "2027-02-05", "end": "2027-03-02", "shift": "day", "headcount": 22, "hazards": ["confined", "height"], "predecessors": ["P19"]},
        ],
        "expected_conflicts": [
            {"scenario": "S2", "type": "vertical", "rule_ids": ["R16"], "with": "가상-기계J P23 (TOP, 2027-01-06~02-20)", "note": "기준 일정 그대로여도 노정 설치 아래 노저 축조가 겹친다 — 조정 대상 표시"},
        ],
        "note": "기준 일정 그대로. 시드(db/seed.py)가 넣는 파일과 같은 이름. 이 계획서 단독으로는 충돌 없음",
    }
    return path, answer


# ──────────────────────────────────────────────────────────────────────
# PDF 공통: 표 그리기 (PyMuPDF find_tables 가 선을 보고 표를 찾는다)
# ──────────────────────────────────────────────────────────────────────
def _pdf_table(page: pymupdf.Page, x0: float, y0: float, widths: list[float], rows: list[list[str]], row_h: float = 34, font: float = 8) -> float:
    y = y0
    for r_no, row in enumerate(rows):
        x = x0
        h = row_h if r_no else 20
        for w, val in zip(widths, row):
            rect = pymupdf.Rect(x, y, x + w, y + h)
            if r_no == 0:
                page.draw_rect(rect, color=(0, 0, 0), fill=(0.88, 0.92, 0.97), width=0.8)
            else:
                page.draw_rect(rect, color=(0, 0, 0), width=0.6)
            rc = page.insert_textbox(rect + (3, 3, -3, -2), val, **FONT_KW, fontsize=font, align=pymupdf.TEXT_ALIGN_LEFT)
            if rc < 0:
                raise SystemExit(f"표 칸이 좁아 글이 넘칩니다: {val!r} (행 높이 {h}, 폭 {w})")
            x += w
        y += h
    return y


def _pdf_lines(page: pymupdf.Page, x: float, y: float, lines: list[str], size: float = 9, gap: float = 14) -> float:
    for ln in lines:
        page.insert_text((x, y), ln, **FONT_KW, fontsize=size)
        y += gap
    return y


# ──────────────────────────────────────────────────────────────────────
# 2. 가상-기계J — PDF (세로, 결재란 + 표, 시드와 같은 파일명)
# ──────────────────────────────────────────────────────────────────────
def make_gigye_pdf() -> tuple[Path, dict]:
    doc = pymupdf.open()
    page = doc.new_page()  # A4 세로
    page.insert_text((50, 55), "작 업 계 획 서", **FONT_KW, fontsize=18)
    page.insert_text((50, 72), "광양 2고로 개수 — 노정 장입설비(벨리스 탑) 설치", **FONT_KW, fontsize=10)
    # 결재란
    for i, (k, v) in enumerate([("작성", "김가상"), ("검토", "이가상"), ("승인", "")]):
        x = 380 + i * 55
        page.draw_rect(pymupdf.Rect(x, 40, x + 55, 58), width=0.6, fill=(0.9, 0.9, 0.9))
        page.draw_rect(pymupdf.Rect(x, 58, x + 55, 85), width=0.6)
        page.insert_text((x + 18, 53), k, **FONT_KW, fontsize=8)
        page.insert_text((x + 14, 76), v, **FONT_KW, fontsize=8)
    y = _pdf_lines(page, 50, 100, [
        "협력사: 가상-기계J (장비 제작사)      공종: 기계      작성일: 2026-12-28",
        "현장 책임자: 박가상(가상)      비상연락: 000-0000-0000(가상)",
        SYNTH,
    ])
    y = _pdf_lines(page, 50, y + 6, ["1. 작업 개요"], size=10)
    y = _pdf_lines(page, 60, y, [
        "신 철피 링블록 설치 완료 후 노정 플랫폼에 벨리스 탑·호퍼를 대형 크레인으로 인양하여 설치한다.",
        "설치 후 장입 구동부 시운전을 2월 셋째 주에 실시한다.",
    ], size=8.5, gap=12)
    y = _pdf_lines(page, 50, y + 8, ["2. 작업 일정표"], size=10)
    header = ["작업명", "위치", "기간", "작업시간", "인원", "위험작업", "선행조건"]
    rows = [
        header,
        ["벨리스 탑 부품 야드 반입·검수", "조립장 야드", "2026.12.20 ~ 2027.01.05", "08:00~17:00", "6", "중량물", ""],
        ["노정 장입설비(벨리스 탑) 설치", "노정 플랫폼", "2027.01.06 ~ 2027.02.20", "08:00~17:00", "12", "크레인 인양, 고소작업, 용접", "링블록 반입·설치(대형 인양) 완료 후"],
        ["장입 구동부 시운전", "노정 플랫폼", "2027.02.18 ~ 2027.02.20", "13:00~17:00", "4", "끼임(시운전)", "설치 완료·LOTO 해제 후"],
    ]
    y = _pdf_table(page, 40, y + 4, [104, 52, 114, 56, 24, 80, 92], rows, row_h=40)
    y = _pdf_lines(page, 50, y + 16, ["3. 안전조치"], size=10)
    _pdf_lines(page, 60, y, [
        "- 인양 시 신호수 2명 배치, 인양 경로 하부 출입 통제(노정 직하 노 내부 작업 업체와 시간 협의)",
        "- 고소작업: 안전대 100% 체결, 노정 개구부 덮개·난간 확인",
        "- 용접 시 화재감시자 배치, 소화기 2대, 종료 후 30분 감시",
        "- 시운전 전 구동부 주변 인원 철수 확인, 시운전 중 접근 금지",
    ], size=8.5, gap=12)
    path = HERE / "가상-기계J_장입설비_설치계획서.pdf"
    doc.save(path, garbage=3, deflate=True)
    answer = {
        "file": path.name,
        "contractor": "가상-기계J",
        "format": "pdf",
        "tasks": [
            {"wbs_id": None, "name": "벨리스 탑 부품 야드 반입·검수", "zone_id": "YARD", "start": "2026-12-20", "end": "2027-01-05", "shift": "day", "headcount": 6, "hazards": ["heavy_lift"], "predecessors": []},
            {"wbs_id": "P23", "name": "노정 장입설비(벨리스 탑) 설치", "zone_id": "TOP", "start": "2027-01-06", "end": "2027-02-20", "shift": "day", "headcount": 12, "hazards": ["heavy_lift", "height", "hot_work"], "predecessors": ["P17"]},
            {"wbs_id": None, "name": "장입 구동부 시운전", "zone_id": "TOP", "start": "2027-02-18", "end": "2027-02-20", "shift": "day", "headcount": 4, "hazards": [], "predecessors": []},
        ],
        "expected_conflicts": [
            {"scenario": "S2", "type": "vertical", "rule_ids": ["R16", "R18"], "with": "가상-축로I P20 (HEARTH, 2027-01-21~02-15)", "note": "노정 고소·인양 바로 아래 노저 축조 — 방호선반·하부 출입금지 기재 없으면 금지"},
        ],
        "note": "기준 일정 그대로. 시드가 넣는 파일과 같은 이름",
    }
    return path, answer


# ──────────────────────────────────────────────────────────────────────
# 4. 가상-제관F — PDF (가로, 다른 머리글 낱말, 업체명은 머리에만) — S4 화기×가스
# ──────────────────────────────────────────────────────────────────────
def make_jegwan_pdf() -> tuple[Path, dict]:
    """일부러 '지저분한' 한 건: 표가 없는 공문 형식.

    협력사가 늘 깔끔한 표로 내지는 않는다. 이 건은 번호 문단에 줄글로 쓰고 날짜 표기도 제각각이라
    (11월 15일 / '27. 1. 11. / '26.11.22. / 2027-02-20 / 2026.12.31) 표 규칙(parsers/table_mapper.py)이
    집을 표가 아예 없다 → F1 이 LLM 추출 경로로 넘어간다. 나머지 8건은 표 규칙으로 읽힌다.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 세로
    y = _pdf_lines(page, 180, 70, ["공 사  작 업 계 획  통 보"], size=16)
    y = _pdf_lines(page, 50, y + 10, [
        "문서번호 JG-2026-11-07 (가상)          작성일 2026.11.10          개정 1차",
        "수신: 원청 공사관리팀          발신: 가상-제관F (제관·내화물)",
        "제목: 광양 2고로 개수 상승관·하강관 및 가스청정설비 보수 작업계획 통보의 건",
    ], size=9, gap=15)
    y = _pdf_lines(page, 50, y + 12, [
        "1. 귀 사의 무궁한 발전을 기원합니다.",
        "2. 당사는 광양 2고로 개수공사와 관련하여 아래와 같이 작업을 시행하고자 통보드립니다.",
    ], size=9.5, gap=16)
    y = _pdf_lines(page, 62, y + 10, [
        "가. 상승관·하강관 가스 배관 절단·보수",
        "    - 작업장소는 하강관 구간이며 11월 15일 착수하여 '27. 1. 11. 종료 예정입니다.",
        "    - 주간 작업이고 1일 10명이 투입되며, 화기작업(용단·용접)과 고소작업이 포함됩니다.",
        "    - 원청의 가스 계통 차단 및 블리더 방산이 끝난 뒤 착수합니다. 방산 완료 여부는",
        "      원청 확인을 요청드립니다.",
        "",
        "나. 제진기·가스청정설비 보수·교체",
        "    - 제진기 일원에서 '26.11.22. 부터 2027-02-20 까지 주야간 교대로 14명이 작업합니다.",
        "    - 화기작업, 밀폐공간 출입, 중량물 취급이 수반되며 야간에는 교체품 반입·인양 위주입니다.",
        "",
        "다. 보수 자재 가공",
        "    - 자재 야드에서 2026.11.12 ~ 2026.12.31 주간 5명이 그라인딩·절단 작업을 합니다.",
    ], size=9, gap=15)
    y = _pdf_lines(page, 50, y + 12, ["3. 하강관 절단·보수 작업절차는 다음과 같습니다."], size=9.5, gap=16)
    y = _pdf_lines(page, 62, y, [
        "작업허가서(화기·고소) 발급 → 가스 계통 차단·맹판 확인 → 작업 전 가스 측정",
        "(LEL 10% 미만, O2 18~23.5%, CO 30ppm 미만) 기록 → 화재감시자 배치·불티비산방지포 설치 →",
        "절단·보수 용접 → 비파괴검사 → 작업 종료 후 30분 화재감시 → 허가서 반납",
    ], size=9, gap=15)
    y = _pdf_lines(page, 50, y + 12, [
        "4. 기타 자세한 사항은 당사 안전관리자 최가상(가상), 작업 책임자 정가상(가상)에게",
        "   문의하여 주시기 바랍니다.  끝.",
    ], size=9.5, gap=16)
    _pdf_lines(page, 50, y + 24, [SYNTH], size=8)
    path = HERE / "가상-제관F_하강관_가스청정_보수계획.pdf"
    doc.save(path, garbage=3, deflate=True)
    answer = {
        "file": path.name,
        "contractor": "가상-제관F",
        "format": "pdf",
        "extraction": "llm",
        "tasks": [
            {"wbs_id": "P10", "name": "상승관·하강관 가스 배관 절단·보수", "zone_id": "DOWNCOMER", "start": "2026-11-15", "end": "2027-01-11", "shift": "day", "headcount": 10, "hazards": ["gas", "height", "hot_work"], "predecessors": ["P05"]},
            {"wbs_id": "P25", "name": "제진기·가스청정설비 보수·교체", "zone_id": "GCP", "start": "2026-11-22", "end": "2027-02-20", "shift": None, "headcount": 14, "hazards": ["confined", "gas", "heavy_lift", "hot_work"], "predecessors": ["P05"]},
            {"wbs_id": None, "name": "보수 자재 가공", "zone_id": "YARD", "start": "2026-11-12", "end": "2026-12-31", "shift": "day", "headcount": 5, "hazards": ["hot_work"], "predecessors": []},
        ],
        "expected_conflicts": [
            {"scenario": "S4", "type": "hot_gas", "rule_ids": ["R04"], "with": "원청-정비 P05 가스 계통 차단·블리더 방산·질소 퍼지 (DOWNCOMER, 2026-11-13~11-15)", "note": "하강관 절단을 기준(11-17)보다 이틀 앞당겨 퍼지 중 화기 — 금지"},
        ],
        "note": "표가 없는 공문 형식(줄글·날짜 표기 제각각) → 표 규칙으로 읽히지 않고 LLM 추출 경로로 간다. P10 시작일은 2026-11-15로 앞당겨 제출(기준 11-17)",
    }
    return path, answer


# ──────────────────────────────────────────────────────────────────────
# HWPX 공통: 최소 패키지 (파서는 Contents/section*.xml 만 읽는다)
# ──────────────────────────────────────────────────────────────────────
_NS = (
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"'
)
_PID = [100]


def _pid() -> int:
    _PID[0] += 1
    return _PID[0]


def _para(text: str, char_pr: int = 0, para_pr: int = 0, first: bool = False) -> str:
    sec_pr = ""
    if first:
        sec_pr = (
            '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" '
            'outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">'
            '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>'
            '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
            '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" '
            'hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
            '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
            '<hp:pagePr landscape="WIDELY" width="59528" height="84188" gutterType="LEFT_ONLY">'
            '<hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/></hp:pagePr>'
            "</hp:secPr>"
        )
    return (
        f'<hp:p id="{_pid()}" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{char_pr}">{sec_pr}<hp:t>{escape(text)}</hp:t></hp:run></hp:p>'
    )


def _cell(text: str, col: int, row: int, width: int, header: bool) -> str:
    return (
        f'<hp:tc name="" header="{int(header)}" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="3">'
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" '
        'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f"{_para(text, char_pr=1 if header else 0)}"
        "</hp:subList>"
        f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{width}" height="1800"/><hp:cellMargin left="510" right="510" top="141" bottom="141"/>'
        "</hp:tc>"
    )


def _table(rows: list[list[str]], widths: list[int]) -> str:
    total_w = sum(widths)
    trs = []
    for r, row in enumerate(rows):
        tcs = "".join(_cell(val, c, r, widths[c], header=(r == 0)) for c, val in enumerate(row))
        trs.append(f"<hp:tr>{tcs}</hp:tr>")
    tbl = (
        f'<hp:tbl id="{_pid()}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
        f'dropcapstyle="None" pageBreak="CELL" repeatHeader="1" rowCnt="{len(rows)}" colCnt="{len(widths)}" cellSpacing="0" '
        'borderFillIDRef="3" noAdjust="0">'
        f'<hp:sz width="{total_w}" widthRelTo="ABSOLUTE" height="{1800 * len(rows)}" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
        'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
        '<hp:outMargin left="283" right="283" top="283" bottom="283"/>'
        '<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
        + "".join(trs)
        + "</hp:tbl>"
    )
    return (
        f'<hp:p id="{_pid()}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="0">{tbl}</hp:run></hp:p>'
    )


_HEADER_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" version="1.4" secCnt="1">
<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
<hh:refList>
<hh:fontfaces itemCnt="7">
<hh:fontface lang="HANGUL" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/></hh:fontface>
<hh:fontface lang="LATIN" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/></hh:fontface>
<hh:fontface lang="HANJA" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/></hh:fontface>
<hh:fontface lang="JAPANESE" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/></hh:fontface>
<hh:fontface lang="OTHER" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/></hh:fontface>
<hh:fontface lang="SYMBOL" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/></hh:fontface>
<hh:fontface lang="USER" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF" isEmbedded="0"/></hh:fontface>
</hh:fontfaces>
<hh:borderFills itemCnt="3">
<hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/><hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/><hh:topBorder type="NONE" width="0.1 mm" color="#000000"/><hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/><hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/></hh:borderFill>
<hh:borderFill id="2" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/><hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/><hh:topBorder type="NONE" width="0.1 mm" color="#000000"/><hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/><hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/></hh:borderFill>
<hh:borderFill id="3" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/><hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/><hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/><hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/><hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/></hh:borderFill>
</hh:borderFills>
<hh:charProperties itemCnt="3">
<hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/><hh:shadow type="NONE" color="#B2B2B2" offsetX="10" offsetY="10"/></hh:charPr>
<hh:charPr id="1" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:bold/><hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/><hh:shadow type="NONE" color="#B2B2B2" offsetX="10" offsetY="10"/></hh:charPr>
<hh:charPr id="2" height="1600" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/><hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:bold/><hh:underline type="NONE" shape="SOLID" color="#000000"/><hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/><hh:shadow type="NONE" color="#B2B2B2" offsetX="10" offsetY="10"/></hh:charPr>
</hh:charProperties>
<hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties>
<hh:numberings itemCnt="1"><hh:numbering id="1" start="0"><hh:paraHead start="1" level="1" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="DIGIT" charPrIDRef="4294967295" checkable="0">^1.</hh:paraHead></hh:numbering></hh:numberings>
<hh:paraProperties itemCnt="1">
<hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"><hh:align horizontal="JUSTIFY" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/><hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/><hp:switch xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"><hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin><hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hp:case><hp:default><hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin><hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hp:default></hp:switch><hh:border borderFillIDRef="2" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/></hh:paraPr>
</hh:paraProperties>
<hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>
</hh:refList>
</hh:head>
"""

_CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">
<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></ocf:rootfiles>
</ocf:container>
"""

_MANIFEST_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">
<odf:file-entry odf:full-path="/" odf:media-type="application/hwp+zip"/>
<odf:file-entry odf:full-path="Contents/header.xml" odf:media-type="application/xml"/>
<odf:file-entry odf:full-path="Contents/section0.xml" odf:media-type="application/xml"/>
<odf:file-entry odf:full-path="settings.xml" odf:media-type="application/xml"/>
<odf:file-entry odf:full-path="version.xml" odf:media-type="application/xml"/>
</odf:manifest>
"""

_VERSION_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.4" application="Hancom Office Hangul" appVersion="12.0.0.0"/>
"""

_SETTINGS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">
<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>
</ha:HWPApplicationSetting>
"""


def _content_hpf(title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="" unique-identifier="" id="">
<opf:metadata><opf:title>{escape(title)}</opf:title><opf:language>ko</opf:language><opf:meta name="creator" content="text">가상 협력사(합성 데이터)</opf:meta></opf:metadata>
<opf:manifest>
<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
<opf:item id="settings" href="settings.xml" media-type="application/xml"/>
</opf:manifest>
<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine>
</opf:package>
"""


def write_hwpx(path: Path, title: str, body: str) -> None:
    sec = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<hs:sec {_NS}>{body}</hs:sec>'
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("version.xml", _VERSION_XML, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("META-INF/container.xml", _CONTAINER_XML, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("META-INF/manifest.xml", _MANIFEST_XML, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("Contents/content.hpf", _content_hpf(title), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("Contents/header.xml", _HEADER_XML, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("Contents/section0.xml", sec, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("settings.xml", _SETTINGS_XML, compress_type=zipfile.ZIP_DEFLATED)


# ──────────────────────────────────────────────────────────────────────
# 3. 가상-배관O — HWPX (S1 핵심 장면: P34 앞당김, 절차에 '작업 전 가스 측정' 없음)
# ──────────────────────────────────────────────────────────────────────
def make_baegwan_hwpx() -> tuple[Path, dict]:
    title = "가스·냉각수 라인 복구 작업계획서"
    body = _para(title, char_pr=2, first=True)
    body += _para("업체명: 가상-배관O      공종: 배관(가스·냉각수)      작성일: 2027-02-18      작성자: 윤가상(가상)")
    body += _para(SYNTH)
    body += _para("1. 작업 개요")
    body += _para(
        "노 내부 내화물 축조가 마무리 단계에 들어감에 따라 풍구 레벨 질소·가스·송풍 라인 복구 연결을 당초 3월 4일에서 "
        "2월 26일로 앞당겨 착수하고자 함. 냉각수 계통 압력시험은 기존 일정대로 진행."
    )
    body += _para("2. 작업 내역")
    rows = [
        ["작업명", "작업장소", "작업기간", "근무", "인원", "위험작업", "착수조건"],
        ["질소·가스·송풍 라인 복구 연결", "풍구 레벨 환상관·송풍지관", "2027.02.26 ~ 2027.03.04", "주간", "8", "화기(용접), 가스", "노흉 내화물 축조(P22) 완료 후"],
        ["냉각수 계통 압력시험·플러싱", "노복·조안 스테이브 배관", "2027.02.20 ~ 2027.03.07", "주간", "6", "", "스테이브 냉각수 배관 연결 완료 후"],
    ]
    body += _table(rows, [9000, 8000, 8600, 2800, 2600, 5500, 8000])
    body += _para("3. 작업 절차 (라인 복구 연결)")
    for step in [
        "① 작업허가서(화기) 접수 및 작업 구역 표시",
        "② 플랜지 면 청소, 가스켓 교체",
        "③ 볼트 체결 및 연결부 용접",
        "④ 질소 가압 기밀시험(누설 확인)",
        "⑤ 복구 완료 보고 및 허가서 반납",
    ]:
        body += _para(step)
    body += _para("4. 안전조치: 용접 시 소화기 비치, 안전모·보안경 착용, 작업 구역 외 출입 금지")
    path = HERE / "가상-배관O_가스라인_복구_작업계획서.hwpx"
    write_hwpx(path, title, body)
    answer = {
        "file": path.name,
        "contractor": "가상-배관O",
        "format": "hwpx",
        "tasks": [
            {"wbs_id": "P34", "name": "질소·가스·송풍 라인 복구 연결", "zone_id": "TUYERE", "start": "2027-02-26", "end": "2027-03-04", "shift": "day", "headcount": 8, "hazards": ["gas", "hot_work"], "predecessors": ["P20", "P21", "P22"]},
            {"wbs_id": "P33", "name": "냉각수 계통 압력시험·플러싱", "zone_id": "BELLY_BOSH", "start": "2027-02-20", "end": "2027-03-07", "shift": "day", "headcount": 6, "hazards": [], "predecessors": ["P19"]},
        ],
        "expected_conflicts": [
            {"scenario": "S1", "type": "sequence", "rule_ids": ["R08", "R07"], "with": "가상-축로I P22 노복~노흉 내화물 축조 (STACK, ~2027-03-02)", "note": "핵심 장면. 선행 조건에 'P22 완료 후'라고 써 놓고 02-26에 착수 → 순서 위반(금지). 조정안: P22 완료·인원 철수 확인 후(03-03~)로 이동"},
            {"scenario": "F8", "type": "sop_missing", "rule_ids": ["R04", "R27"], "with": "SOP-04 가스 배관 연결·기밀시험 표준", "note": "절차에 '작업 전 가스 측정(LEL·O2)'과 '맹판·LOTO 확인' 단계가 빠져 있다 → 결함"},
            {"scenario": "F8", "type": "sop_missing", "rule_ids": ["R04", "R27"], "with": "SOP-P34 질소·가스·송풍 라인 복구 연결 작업표준 (작업별)", "note": "작업별 표준서도 같은 핵심 단계(4 작업 전 가스 측정, 5 연결 대상 계통 내부 작업 완료·인원 철수 확인)가 빠져 결함. P33 압력시험은 핵심 단계가 적혀 있어 결함 없음"},
        ],
        "note": "시연 중 직접 올리는 파일(시드에 넣지 않는다). 기준 P34는 2027-03-04~03-12",
    }
    return path, answer


# ──────────────────────────────────────────────────────────────────────
# 5. 가상-비계N — HWPX (머리글 낱말이 다른 양식) — 같은 시간·구역
# ──────────────────────────────────────────────────────────────────────
def make_bigye_hwpx() -> tuple[Path, dict]:
    title = "비계 설치·해체 작업계획"
    body = _para(title, char_pr=2, first=True)
    body += _para("협력사: 가상-비계N (비계 전문)   현장소장: 강가상(가상)   제출: 2026-12-22")
    body += _para(SYNTH)
    body += _para("□ 작업 범위: 노체 철피 외부 비계 설치(용접·검사용), 노 내부 축조 비계 해체")
    rows = [
        ["구분", "작업내용", "구역", "시작일", "종료일", "시간대", "인원", "위험요인"],
        ["설치", "노체 철피 외부 비계 설치", "노체 철피 외부", "2026.12.28", "2027.01.05", "07:00~18:00", "12", "고소작업, 낙하물"],
        ["해체", "노흉 내부 작업 비계 해체", "노흉 내부", "2027.03.01", "2027.03.05", "07:00~18:00", "8", "고소작업, 밀폐공간, 낙하물"],
    ]
    body += _table(rows, [3000, 9500, 7000, 5000, 5000, 5500, 2500, 7000])
    body += _para("□ 안전조치")
    for s in [
        "- 비계 설치·해체 구간 하부 출입통제(관리감독자 배치), 낙하물 방지망 10m 이내마다 설치",
        "- 안전대 부착설비 선행 설치, 작업발판 폭 40cm 이상·안전난간 설치",
        "- 노 내부 해체 시 산소농도 측정 후 입장, 감시인 배치",
    ]:
        body += _para(s)
    path = HERE / "가상-비계N_비계_설치해체_작업계획.hwpx"
    write_hwpx(path, title, body)
    answer = {
        "file": path.name,
        "contractor": "가상-비계N",
        "format": "hwpx",
        "tasks": [
            {"wbs_id": "P30", "name": "노체 철피 외부 비계 설치", "zone_id": "SHELL", "start": "2026-12-28", "end": "2027-01-05", "shift": "day", "headcount": 12, "hazards": ["height"], "predecessors": ["P06"]},
            {"wbs_id": "P30", "name": "노흉 내부 작업 비계 해체", "zone_id": "STACK", "start": "2027-03-01", "end": "2027-03-05", "shift": "day", "headcount": 8, "hazards": ["confined", "height"], "predecessors": []},
        ],
        "expected_conflicts": [
            {"scenario": "same_zone", "type": "same_time_zone", "rule_ids": ["R17", "R16"], "with": "가상-축로I P22 노복~노흉 내화물 축조 (STACK, ~2027-03-02)", "note": "축조가 끝나기 전(03-01~03-02) 같은 노흉에서 비계 해체 — 금지"},
            {"scenario": "S3-변형", "type": "same_time_zone", "rule_ids": ["R18", "R20"], "with": "가상-양중C P17 신 철피 링블록 반입·설치(대형 인양) (SHELL, 2026-12-27~2027-01-03)", "note": "링블록 인양 중 같은 철피 외부에서 비계 설치(고소) — 인양 시간대 분리"},
        ],
        "note": "기준 P30(비계, 전 구역 D3~D125)을 구역·기간별 작업 2건으로 쪼개 제출. 두 건 모두 기준 일정상 P30에 해당한다",
    }
    return path, answer

# ──────────────────────────────────────────────────────────────────────
# 6. 가상-양중C — PDF (중장비 작업계획서: 결재란 + 일정표 + 장비·비용 표) — S3 대형 인양
#    3D·판정에 필요한 칸을 모두 둔 "완성도 높은" 계획서 예시: 구역 안 세부 위치, 작업시간, 인원, 투입 장비, 선행 조건(기준 ID)
# ──────────────────────────────────────────────────────────────────────
def make_yangjung_pdf() -> tuple[Path, dict]:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), "중 장 비 작 업 계 획 서", **FONT_KW, fontsize=18)
    page.insert_text((50, 96), "광양 2고로 개수 — 대형 크레인 조립 · 신 철피 링블록 반입 · 노내 호이스트 운영", **FONT_KW, fontsize=9.5)
    for i, (k, v) in enumerate([("작성", "장가상"), ("검토", "오가상"), ("승인", "")]):
        x = 380 + i * 55
        page.draw_rect(pymupdf.Rect(x, 40, x + 55, 58), width=0.6, fill=(0.9, 0.9, 0.9))
        page.draw_rect(pymupdf.Rect(x, 58, x + 55, 85), width=0.6)
        page.insert_text((x + 18, 53), k, **FONT_KW, fontsize=8)
        page.insert_text((x + 14, 76), v, **FONT_KW, fontsize=8)
    y = _pdf_lines(page, 50, 114, [
        "협력사: 가상-양중C (양중 전문)      공종: 양중      작성일: 2026-11-05",
        "문서번호: YJ-26-011(가상)      현장소장: 장가상(가상)      안전관리자: 오가상(가상)",
        "비상연락: 000-0000-0000(가상)",
        SYNTH,
    ])
    y = _pdf_lines(page, 50, y + 6, ["1. 작업 일정표"], size=10)
    header = ["작업명", "작업위치", "기간", "작업시간", "인원", "투입장비", "위험작업", "선행조건"]
    rows = [
        header,
        ["대형 크레인 기초 파일·크레인 조립", "크레인 기초 구역 (노체 남측)", "2026.09.28 ~ 2026.11.09", "07:00~18:00", "16", "크롤러 크레인 1,600t(조립), 보조 크레인 250t, 트레일러 6대", "중량물, 고소", "P01 가설 펜스·동선 구축 완료 후"],
        ["신 철피 링블록 반입·설치(대형 인양)", "노체 철피 외부 남측 (크레인 측 반원)", "2026.12.27 ~ 2027.01.03", "07:00~17:00", "20", "크롤러 크레인 1,600t, 보조 크레인 250t, 다축 트레일러 2대", "중량물, 고소", "P15 구 블록 반출, P02 크레인 조립, P03 링블록 선조립 완료 후"],
        ["공사용 호이스트·승강설비 운영", "노흉 승강로 (북측)", "2026.11.27 ~ 2027.03.02", "07:00~19:00", "4", "노내 호이스트 2기(2t), 체인블록 3t", "고소, 중량물", "P12 노내 장입물 배출 완료 후"],
    ]
    y = _pdf_table(page, 40, y + 4, [88, 74, 68, 42, 28, 92, 42, 84], rows, row_h=70, font=7.2)
    y = _pdf_lines(page, 50, y + 14, ["2. 투입 장비 (3D 배치·간섭 검토용)"], size=10)
    eq = [
        ["장비명", "규격", "대수", "배치 위치", "사용 기간", "용도"],
        ["크롤러 크레인", "1,600t (주 붐 84m)", "1", "크레인 기초 구역", "2026.11.09 ~ 2027.01.03", "링블록(최대 505t) 인양"],
        ["보조 크레인", "250t", "1", "크레인 기초 구역 동측", "2026.09.28 ~ 2027.01.03", "주 크레인 조립, 소물 인양"],
        ["다축 트레일러", "SPMT 2조", "2", "야드 → 크레인 패드", "2026.12.27 ~ 2027.01.03", "링블록 운반"],
        ["노내 호이스트", "2t × 2기", "2", "노흉 내부 승강로", "2026.11.27 ~ 2027.03.02", "축조 자재·인원 승강"],
    ]
    y = _pdf_table(page, 40, y + 4, [70, 90, 28, 100, 110, 120], eq, row_h=32, font=7.4)
    y = _pdf_lines(page, 50, y + 14, ["3. 예상 비용 (가상 금액, 단위 천원)"], size=10)
    cost = [
        ["항목", "금액", "산정 근거"],
        ["장비 임차 (크롤러 1,600t·보조 250t·SPMT)", "1,850,000", "임차 일수 × 단가 (가상)"],
        ["인건비 (운전원·신호수·리거 20명)", "620,000", "투입 인원 × 공수 (가상)"],
        ["크레인 기초 파일·매트", "480,000", "파일 32본 + 철판 매트 (가상)"],
        ["안전관리비", "95,000", "출입 통제 펜스·표지·무전기·풍속계 (가상)"],
    ]
    _pdf_table(page, 40, y + 4, [220, 80, 218], cost, row_h=28, font=7.4)

    page = doc.new_page()
    y = _pdf_lines(page, 50, 55, ["4. 작업 절차 및 안전조치"], size=10)
    y = _pdf_lines(page, 60, y, [
        "(1) 크레인 조립",
        "  ① 중장비 작업계획서 작성(크레인 제원·조립 순서·지반 지내력)  ② 파일 기초 지내력 시험 결과 확인",
        "  ③ 조립 구역 출입 통제 펜스·표지 설치  ④ 신호수 지정(조립용 보조 크레인 인양)",
        "  ⑤ 붐·카운터웨이트 인양 시 하부 출입 통제  ⑥ 붐 상부 핀 체결 시 안전대 체결",
        "  ⑦ 풍속 확인(10m/s 이상 조립 중지)  ⑧ 조립 완료 후 하중시험·검사 기록",
        "(2) 링블록 인양",
        "  ① 중장비 작업계획서(링블록 중량·크레인 정격·인양 경로도)  ② 줄걸이 용구 점검·블록 중량 확인(정격 하중 대비)",
        "  ③ 신호수 지정, 무전 신호 통일  ④ 인양 경로 하부 전면 출입 통제(주상·크레인 패드·야드)",
        "  ⑤ 작업반경 내 인원 철수 확인(비계·고소 작업 중지)  ⑥ 풍속 확인(10m/s 이상 인양 중지)",
        "  ⑦ 블록 안착 후 가볼트 체결 확인 전 줄걸이 해제 금지  ⑧ 인양 종료 후 구역 해제 통보",
        "(3) 호이스트 운영",
        "  ① 호이스트 설치 검사·정격 하중 표지  ② 운전원 지정·신호 방법 통일",
        "  ③ 승강로 하부 출입 통제(낙하물 방지)  ④ 탑승 인원·적재 하중 초과 금지 확인",
        "  ⑤ 노정 개구부 승강 출입구 난간·덮개 확인  ⑥ 일일 와이어·브레이크 점검 기록",
        "  ⑦ 노 내부 작업 업체 인양 시간 조정 기록  ⑧ 운영 종료·전원 차단 확인",
    ], size=7.8, gap=12)
    y = _pdf_lines(page, 50, y + 10, ["5. 보호구·비상 조치"], size=10)
    _pdf_lines(page, 60, y, [
        "- 보호구: 안전모·안전화·안전대(고소), 리거 절연장갑, 무전기(신호수 전원), 풍속계 2대",
        "- 인양 중 풍속 10m/s 초과·시야 불량 시 즉시 중지, 블록은 지상 또는 가볼트 체결 상태로 대기",
        "- 사고 발생 시 크레인 정지 → 작업반경 출입 통제 유지 → 원청 상황실·119 연락(연락처 가상)",
    ], size=7.8, gap=12)
    path = HERE / "가상-양중C_대형인양_중장비작업계획서.pdf"
    doc.save(path, garbage=3, deflate=True)
    answer = {
        "file": path.name,
        "contractor": "가상-양중C",
        "format": "pdf",
        "tasks": [
            {"wbs_id": "P02", "name": "대형 크레인 기초 파일·크레인 조립", "zone_id": "CRANE_PAD", "start": "2026-09-28", "end": "2026-11-09", "shift": "day", "headcount": 16, "equipment": ["크롤러 크레인 1,600t", "보조 크레인 250t", "트레일러 6대"], "hazards": ["heavy_lift", "height"], "predecessors": ["P01"]},
            {"wbs_id": "P17", "name": "신 철피 링블록 반입·설치(대형 인양)", "zone_id": "SHELL", "start": "2026-12-27", "end": "2027-01-03", "shift": "day", "headcount": 20, "equipment": ["크롤러 크레인 1,600t", "보조 크레인 250t", "다축 트레일러 2대"], "hazards": ["heavy_lift", "height"], "predecessors": ["P15", "P02", "P03"]},
            {"wbs_id": "P31", "name": "공사용 호이스트·승강설비 운영", "zone_id": "STACK", "start": "2026-11-27", "end": "2027-03-02", "shift": "day", "headcount": 4, "equipment": ["노내 호이스트 2기(2t)", "체인블록 3t"], "hazards": ["heavy_lift", "height"], "predecessors": ["P12"]},
        ],
        "expected_conflicts": [
            {"scenario": "S3", "type": "same_time_zone", "rule_ids": ["R18"], "with": "가상-주상K P24 출선장 개조 (CASTHOUSE, 2026-11-22~2027-03-07)", "note": "링블록 인양 경로 아래 출선장 작업 — 인양 시간대 분리·출입통제 (기준 일정 그대로여도 걸린다)"},
            {"scenario": "S3-변형", "type": "same_time_zone", "rule_ids": ["R18", "R20"], "with": "가상-비계N 노체 철피 외부 비계 설치 (SHELL, 2026-12-28~2027-01-05)", "note": "비계N 계획서가 올라와 있을 때만. 인양 중 같은 철피 외부 고소 작업"},
        ],
        "note": "기준 일정 그대로. 3D에 필요한 칸(세부 위치·시간·인원·장비)과 비용 표를 모두 갖춘 예시. 작업별 표준서 핵심 단계가 절차에 다 적혀 있어 결함 없음",
    }
    return path, answer


# ──────────────────────────────────────────────────────────────────────
# 7. 가상-기계E — Word(.docx) (업체 정보 표 + 작업 표 + 장비·비용 표) — S5 잔선 출선 중 노정 해체 하루 앞당김
# ──────────────────────────────────────────────────────────────────────
def make_gigyeE_docx() -> tuple[Path, dict]:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Pt

    d = Document()
    style = d.styles["Normal"]
    style.font.name = "맑은 고딕"
    style.font.size = Pt(9.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")

    def table(rows: list[list[str]], widths: list[float] | None = None):
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        t.style = "Table Grid"
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                cell = t.cell(r, c)
                cell.text = val
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.size = Pt(8.5)
                        if r == 0:
                            run.bold = True
        return t

    h = d.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = h.add_run("작 업 계 획 서 (기계 정비)")
    run.bold = True
    run.font.size = Pt(16)
    d.add_paragraph("광양 2고로 개수 — 노정 장입설비 해체 · 풍구 철거 · 스테이브 설치")
    d.add_paragraph(SYNTH)
    table([
        ["업체명", "가상-기계E (기계 정비)", "공종", "기계 정비 + 배관"],
        ["작성일", "2026-11-10", "문서번호", "GE-2026-11-03 (가상)"],
        ["현장소장", "한가상(가상)", "안전관리자", "구가상(가상)"],
        ["비상연락", "000-0000-0000 (가상)", "원청 담당", "원청 정비팀 (가상)"],
    ])
    d.add_paragraph("")
    d.add_paragraph("1. 작업 내역").runs[0].bold = True
    table([
        ["공종", "작업명", "작업 장소", "착수일", "완료일", "작업시간", "투입인원", "투입 장비", "위험요인", "선행조건"],
        ["기계 정비", "노정 장입설비(벨리스 탑·호퍼) 해체", "노정 플랫폼 동측 (호퍼 하부)", "2026-11-14", "2026-11-26", "07:00~18:00", "14", "250t 크레인, 산소절단기 4조, 체인블록 5t", "화기(용단), 고소, 중량물, 잔류가스", "에너지 격리(LOTO) 완료 후"],
        ["기계 정비", "풍구·냉각기·송풍지관 철거", "풍구 레벨 플랫폼 전 둘레", "2026-11-17", "2026-11-27", "07:00~18:00", "10", "체인블록 3t, 산소절단기 2조, 지게차 3t", "화기, 중량물", "에너지 격리(LOTO) 완료 후"],
        ["기계+배관", "스테이브·냉각판 설치와 냉각수 배관 연결", "노복·조안 내부 (스테이브 1~9단)", "2027-01-06", "2027-02-05", "07:00~18:00", "18", "노내 호이스트, 용접기 4대, 달비계 2조", "화기(용접), 밀폐공간, 고소, 중량물", "철피 용접·비파괴검사 완료 후"],
    ])
    d.add_paragraph("")
    d.add_paragraph("2. 투입 장비·인원 (3D 배치용)").runs[0].bold = True
    table([
        ["장비명", "규격", "대수", "배치 위치", "사용 기간"],
        ["이동식 크레인", "250t", "1", "노정 플랫폼 옆 크레인 패드", "2026-11-14 ~ 2026-11-26"],
        ["산소절단기", "LPG·O2 세트", "6", "노정 2조 → 풍구 레벨 2조, 예비 2조", "2026-11-14 ~ 2026-11-27"],
        ["체인블록", "3t·5t", "6", "노정 동측·풍구 레벨", "2026-11-14 ~ 2026-11-27"],
        ["노내 호이스트(양중C 운영)", "2t", "2", "노흉 내부 승강로", "2027-01-06 ~ 2027-02-05"],
        ["용접기", "인버터 400A", "4", "노복·조안 내부", "2027-01-06 ~ 2027-02-05"],
    ])
    d.add_paragraph("")
    d.add_paragraph("3. 예상 비용 (가상 금액, 단위 천원)").runs[0].bold = True
    table([
        ["항목", "금액", "비고"],
        ["인건비 (기계공·용접사·신호수 42명)", "1,120,000", "투입 인원 × 공수 (가상)"],
        ["장비 임차 (250t 크레인·호이스트·용접기)", "310,000", "임차 일수 × 단가 (가상)"],
        ["스테이브·냉각수 배관 자재", "2,450,000", "원청 지급 자재 제외 (가상)"],
        ["안전관리비", "68,000", "가스측정기·방화포·안전대 (가상)"],
    ])
    d.add_paragraph("")
    d.add_paragraph("4. 작업 절차 및 안전조치").runs[0].bold = True
    for line in [
        "(1) 노정 해체: 작업허가서 발급(화기·고소·중장비) → 노정 잔류가스 측정(CO 30ppm 미만, LEL 10% 미만) 후 진입 → 화재감시자 배치(절단 중 상주, 종료 후 30분 감시)",
        "    → 노정 개구부 덮개·난간 설치(추락 방지) → 해체 부재 인양 신호수 지정·줄걸이 점검 → 인양 경로 하부·노 내부 출입 통제 → 안전대 체결 확인 → 해체 완료·개구부 보호 상태 인계 기록",
        "(2) 풍구 철거: 작업허가서(화기·중장비) 발급 → 송풍·냉각수 LOTO 확인(P06 격리 목록 대조) → 냉각수 배관 잔압 제거·배수 확인 → 화재감시자 배치(볼트 절단·용단)",
        "    → 풍구·냉각기 인양 신호수 지정·줄걸이 점검 → 환상관 아래 주상 하부 출입 통제 → 철거품 반출 경로 확보·유도자 배치 → 철거 완료 개구부 막음 확인·허가서 반납",
        "(3) 스테이브 설치: 작업허가서(화기·밀폐·고소) 발급 → 작업 전 산소·가스 측정 후 진입(노 내부) → 감시인 배치·출입자 명부 기록 → 스테이브 인양 신호수 지정·호이스트 하부 출입 통제",
        "    → 화재감시자 배치(배관 용접) → 달비계·안전대 체결 확인 → 작업반경 내 인원 철수 확인 → 냉각수 배관 연결 후 가압 전 인원 철수 확인 → 설치 완료 검사(압력시험 P33 인계)",
        "(4) 보호구: 안전모·안전화·보안경, 용접 보안면·방열 장갑, 안전대(2중 걸이), 휴대용 CO 경보기(노정·노 내부)",
    ]:
        d.add_paragraph(line)
    path = HERE / "가상-기계E_노정해체_스테이브설치_작업계획서.docx"
    d.save(path)
    answer = {
        "file": path.name,
        "contractor": "가상-기계E",
        "format": "docx",
        "tasks": [
            {"wbs_id": "P09", "name": "노정 장입설비(벨리스 탑·호퍼) 해체", "zone_id": "TOP", "start": "2026-11-14", "end": "2026-11-26", "shift": "day", "headcount": 14, "equipment": ["250t 크레인", "산소절단기 4조", "체인블록 5t"], "hazards": ["gas", "heavy_lift", "height", "hot_work"], "predecessors": ["P06"]},
            {"wbs_id": "P11", "name": "풍구·냉각기·송풍지관 철거", "zone_id": "TUYERE", "start": "2026-11-17", "end": "2026-11-27", "shift": "day", "headcount": 10, "equipment": ["체인블록 3t", "산소절단기 2조", "지게차 3t"], "hazards": ["heavy_lift", "hot_work"], "predecessors": ["P06"]},
            {"wbs_id": "P19", "name": "스테이브·냉각판 설치와 냉각수 배관 연결", "zone_id": "BELLY_BOSH", "start": "2027-01-06", "end": "2027-02-05", "shift": "day", "headcount": 18, "equipment": ["노내 호이스트", "용접기 4대", "달비계 2조"], "hazards": ["confined", "heavy_lift", "height", "hot_work"], "predecessors": ["P18"]},
        ],
        "expected_conflicts": [
            {"scenario": "S5", "type": "same_time_zone", "rule_ids": ["R12"], "with": "가상-출선D P07 잔선구 출선(산소 랜싱) (HEARTH, 2026-11-13~11-14)", "note": "노정 해체를 기준(11-15)보다 하루 앞당겨 출선 통제 시간대(24h)에 착수 — 금지"},
        ],
        "note": "P09 착수일을 2026-11-14로 앞당겨 제출(기준 11-15). Word 양식 예시. 작업별 표준서 핵심 단계가 절차에 다 적혀 있어 결함 없음",
    }
    return path, answer


# ──────────────────────────────────────────────────────────────────────
# 8. 가상-축로L — HWPX (월간 계획, 표 + 절차 문단) — S6 열풍로 보수 연장 중 승온
# ──────────────────────────────────────────────────────────────────────
def make_chukroL_hwpx() -> tuple[Path, dict]:
    title = "열풍로·환상관 내화물 보수 월간 작업계획"
    body = _para(title, char_pr=2, first=True)
    body += _para("협력업체: 가상-축로L (축로)   현장대리인: 문가상(가상)   작성: 2026-11-12   개정: 2차(2027-02-20, 열풍로 보수 기간 연장)")
    body += _para(SYNTH)
    body += _para("1. 공정 개요: 열풍로 2·3호 돔·축열 연와·버너 보수와 열풍 본관·환상관 내화물 축조. 돔 연와 손상이 예상보다 커 열풍로 보수를 3월 6일까지 연장함.")
    rows = [
        ["구분", "공정명", "작업장소", "착수일", "완료일", "근무", "작업인원", "투입장비", "필요허가", "착수조건"],
        ["보수", "열풍로 돔·축열 연와·버너 보수", "열풍로 2·3호 돔 내부", "2026.11.17", "2027.03.06", "주간", "16", "돔 내부 달비계 2조, 연와 호이스트 1t, 용접기 2대, 환기팬", "화기, 밀폐공간, 고소", "에너지 격리(LOTO) 완료 후"],
        ["축조", "열풍 본관·환상관 내화물", "풍구 레벨 환상관 내부", "2026.12.22", "2027.02.15", "주간", "12", "환상관 이동 발판, 환기팬 2대, 벽돌 운반 대차", "밀폐공간, 고소", "송풍지관 철거 완료 후"],
    ]
    body += _table(rows, [2400, 7200, 6000, 4200, 4200, 2400, 2800, 8000, 5400, 6400])
    body += _para("2. 투입 장비·인원: 달비계 2조(돔 내부), 연와 호이스트 1t(열풍로 외벽 개구부), 용접기 2대(버너 보수), 환기팬 3대, 산소·CO 측정기 3대, 공기호흡기 2조. 인원은 축로공 20명·감시인 4명·반장 2명·안전관리자 1명·운전원 1명.")
    body += _para("3. 예상 비용(가상, 천원): 축열 연와·캐스터블 자재 1,320,000 / 인건비 980,000 / 장비 임차 140,000 / 안전관리비 52,000")
    body += _para("4. 작업 절차 (열풍로 보수)")
    for step in [
        "① 작업허가서(화기·밀폐·고소) 발급",
        "② 열풍로 가스(BFG·COG) 차단·맹판 확인 — 승온(P35) 허가와 상호 참조 번호 기재",
        "③ 작업 전 산소·CO 측정 후 진입, 연속 측정 (O2 18~23.5%, CO 30ppm 미만)",
        "④ 감시인 배치·출입자 명부 기록",
        "⑤ 돔 내부 달비계·안전대 체결 확인",
        "⑥ 버너 용접 화재감시자 배치, 종료 후 30분 감시",
        "⑦ 연와 반입 호이스트 하부 출입 통제",
        "⑧ 보수 완료·전원 퇴출 확인 서명 후 승온(P35) 허용",
    ]:
        body += _para(step)
    body += _para("5. 작업 절차 (환상관 내화물)")
    for step in [
        "① 밀폐공간 작업허가서 발급",
        "② 작업 전 산소농도·CO 측정 후 진입",
        "③ 환상관 내부 환기팬 가동·연속 측정",
        "④ 감시인 배치·출입자 명부 기록",
        "⑤ 환상관 내부 이동 발판·안전대 체결 확인",
        "⑥ 송풍 계통 LOTO 확인 (송풍지관 P11 철거 완료)",
        "⑦ 내화물 반입 개구부 하부 출입 통제",
        "⑧ 작업 종료 퇴출 확인 서명 (송풍 라인 복구 P34 인계)",
    ]:
        body += _para(step)
    body += _para("6. 보호구·비상: 안전모·안전화·안전대·방진마스크, 휴대용 산소 경보기. 가스 경보 시 전원 퇴출 후 원청 상황실 보고, 구조는 공기호흡기 착용자만.")
    path = HERE / "가상-축로L_열풍로_환상관_내화물_월간계획.hwpx"
    write_hwpx(path, title, body)
    answer = {
        "file": path.name,
        "contractor": "가상-축로L",
        "format": "hwpx",
        "tasks": [
            {"wbs_id": "P26", "name": "열풍로 돔·축열 연와·버너 보수", "zone_id": "STOVE", "start": "2026-11-17", "end": "2027-03-06", "shift": "day", "headcount": 16, "equipment": ["돔 내부 달비계 2조", "연와 호이스트 1t", "용접기 2대", "환기팬"], "hazards": ["confined", "height", "hot_work"], "predecessors": ["P06"]},
            {"wbs_id": "P27", "name": "열풍 본관·환상관 내화물", "zone_id": "TUYERE", "start": "2026-12-22", "end": "2027-02-15", "shift": "day", "headcount": 12, "equipment": ["환상관 이동 발판", "환기팬 2대", "벽돌 운반 대차"], "hazards": ["confined", "height"], "predecessors": ["P11"]},
        ],
        "expected_conflicts": [
            {"scenario": "S6", "type": "sequence", "rule_ids": ["R08", "R07"], "with": "원청-제선 P35 열풍로 승온·가스 계통 기밀시험·퍼지 (STOVE, 2027-03-04~03-20)", "note": "열풍로 보수를 03-06까지 연장해 제출 → 보수 완료 전 승온·가스 투입 — 금지. 조정안: 승온을 보수 완료·퇴출 확인 후로"},
        ],
        "note": "P26 완료일을 2027-03-06으로 연장해 제출(기준 02-25). HWPX 양식 예시. 작업별 표준서 핵심 단계가 절차에 다 적혀 있어 결함 없음",
    }
    return path, answer


def main() -> None:
    ANSWERS.mkdir(exist_ok=True)
    made = []
    for fn in (make_chukro_xlsx, make_gigye_pdf, make_baegwan_hwpx, make_jegwan_pdf, make_bigye_hwpx, make_yangjung_pdf, make_gigyeE_docx, make_chukroL_hwpx):
        path, answer = fn()
        (ANSWERS / (path.stem + ".json")).write_text(json.dumps(answer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        made.append(path)
        print(f"만듦: {path.relative_to(HERE.parent)}  ({path.stat().st_size:,} bytes)")
    print(f"정답셋 {len(made)}건: {ANSWERS.relative_to(HERE.parent)}/")


if __name__ == "__main__":
    main()
