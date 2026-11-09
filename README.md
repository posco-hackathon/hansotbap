# 🍲 한솥밥

고로 개수 협력사 동시작업 간섭 감지·예보 — 팀 세이프루프(SafeLoop), POSCO K-뉴딜 아카데미 해커톤 2026

여러 협력사가 한 현장에 들어오는 대형 정비 공사에서, 제각각인 작업계획서를 AI로 구조화하고 규칙으로 계획 간 충돌을 미리 찾아 원청이 조정하고 협력사에 공유하게 하는 시스템이다. 기준 현장은 포스코 광양 2고로 개수(2026-11-12 ~ 2027-03-23, 132일). **화면과 데이터는 모두 합성 데이터이며 협력사명은 가상이다.**

기획서: [`docs/40_기획서_최종.md`](docs/40_기획서_최종.md)

## 구조

```
app/
  backend/            FastAPI (Python)
    api/              라우터 — 엔드포인트 목록은 아래 "API" 절
    parsers/          pdf, xlsx, hwpx, docx → 텍스트 (위치 표식 포함)
    llm/              LLMProvider: Claude | Unsloth Studio | LM Studio (F1 추출, F4·F9 문장, F7 전달 판정)
    chat/             F6 챗봇: 질문 해석 → 조회 함수(도구) → 근거 붙은 답
    rules/            F2 판정, F8 누락 판정, F9 점수 (pytest 대상)
    search/           F8 작업표준서 임베딩 인덱스
    stt/              F7 Whisper large-v3-turbo / large-v3
    db/               SQLite
    data/             gy2bf_wbs.csv, zones.csv, conflict_rules.csv, sop/(작업표준서)
    schemas.py        데이터 계약 (프론트 src/types.ts 와 같은 모양)
  frontend/           React + Vite + TypeScript (npm run dev 가 여는 화면, 서버 연결)
    src/views/        원청 화면, 협력사 화면, 상황판(BoardView), TBM 확인, 이력
    src/components/   충돌 목록·조정안·공유, 계획서 올리기, 위험 시간대
    src/api/          API 클라이언트 (client.ts)
    scene3d/          three.js 고로 3D·2D 도면 (/scene3d/index.html, Vite 가 함께 빌드)
    public/prototype/ 정적 시안 (서버 연결 없음, 합성 데이터만)
  samples/            합성 계획서(HWPX·엑셀·PDF·Word), 정답셋, TBM 녹음, 추출·판정 평가 스크립트
  tests/              pytest
docs/                 기획서, 기술 스택, 작업 분해 (docs/private/ 는 git 제외)
```

## 준비물

- Node.js 24 (`.nvmrc`, npm 11 포함). 24보다 낮으면 `npm run setup` 이 `EBADENGINE` 오류로 멈춘다 (`.npmrc` 의 `engine-strict`). nvm-windows: `nvm install 24 && nvm use 24`
- [uv](https://docs.astral.sh/uv/) (`pip install uv` 또는 `winget install astral-sh.uv`). Python은 `app/backend/.python-version` 에 3.12로 고정돼 있고, 없으면 uv가 자동으로 받는다
- Unsloth Studio(채팅·임베딩)는 팀의 로컬 LLM 전용 노트북에서 API로 받는다. 각자 PC에 설치하지 않는다. `.env` 의 `UNSLOTH_BASE_URL`(노트북 주소)과 `UNSLOTH_API_KEY` 는 팀 채널에서 받아 넣는다(공개 저장소라 적지 않는다)
- LM Studio(선택)는 각자 PC에서 로컬로 돌릴 때 쓴다. LM Studio > Developer 에서 서버를 켜고(기본 `http://localhost:1234/v1`) `.env` 에 `LLM_PROVIDER=lmstudio`, `LMSTUDIO_CHAT_MODEL`(`lms ls` 로 나오는 이름)을 넣는다. Claude로 추출하면서 F8 임베딩만 LM Studio에서 받으려면 `EMBEDDING_PROVIDER=lmstudio` 와 `LMSTUDIO_EMBEDDING_MODEL` 을 넣는다
- 모델은 `npm run models` 로 고른다. Claude·Unsloth Studio·LM Studio에서 모델 목록을 조회해(로컬은 로드 여부도 표시) 번호로 고르면 `.env` 의 `LLM_PROVIDER`·`EMBEDDING_PROVIDER`·`*_MODEL` 줄만 바꾼다. `npm run models -- --list` 는 조회만 한다
- Whisper(F7 음성인식)는 각자 PC에서 띄운다. 아래 "음성인식 준비"

## 음성인식 준비 (F7, 각자 PC)

```bash
npm run whisper           # 처음 한 번은 설치·모델 다운로드(약 550MB)까지 하고, 서버를 켠 뒤 연결을 확인한다
```

이 창을 켜 둔 채로 다른 터미널에서 `npm run dev` 를 한다. 하는 일:

1. `whisper-server` 가 없으면 설치한다. macOS는 `brew install whisper-cpp`, Windows·Linux는 [whisper.cpp 공식 릴리스](https://github.com/ggml-org/whisper.cpp/releases)를 `.tools/whisper/` 에 푼다(NVIDIA GPU가 있으면 CUDA판)
2. ffmpeg 가 없으면 설치를 시도한다(macOS brew, Windows winget). m4a·webm·mp3 변환용이고, 없으면 wav만 받는다
3. 모델이 없으면 `~/models/`(Windows: `C:\Users\<이름>\models`)에 받는다. `.env` 의 `WHISPER_MODEL`: `large-v3-turbo`(기본, 빠름) / `large-v3`(정확, 약 1GB)
4. `.env` 의 `WHISPER_BASE_URL` 포트(기본 `http://127.0.0.1:8090/v1`)로 서버를 켜고 1초 무음을 보내 확인한다. 백엔드 API가 8000을 쓰므로 8090에 둔다

NVIDIA GPU가 없으면 CPU판으로 돈다. 노트북 CPU(i5-10210U, 스레드를 늘려도 같음) 기준 녹음 길이의 약 2.5배가 걸린다(7초 → 51초, 90초 → 3분 39초). 백엔드는 `.env` 의 `WHISPER_TIMEOUT`(기본 1800초)까지 기다린다.

`npm run whisper -- --check` 는 설치·다운로드만 하고 서버는 켜지 않는다. Windows에서 CUDA판이 켜지지 않으면 `.tools` 폴더를 지우고 `npm run whisper -- --cpu` 로 CPU판을 받는다. PowerShell·cmd·Git Bash 모두 된다. winget 으로 ffmpeg 를 처음 깔았으면 터미널을 새로 열어야 잡힌다. `.env` 의 `WHISPER_API_KEY` 는 비워 둔다(키를 검사하는 원격 음성 서버를 쓸 때만).

TBM 녹음은 참석자 동의를 받은 뒤에만 올린다. 원본 녹음은 받아쓰기가 끝나면 지우고, 전사문은 전달 확인 기록과 함께 DB에 남는다. 시연 전에 샘플 공지를 넣으려면 `npm run seed` 뒤에 `cd app/backend && uv run python ../samples/seed_tbm_notices.py` 를 한 번 실행한다(`npm run seed`·`db:reset` 은 TBM 공지·전달 확인 기록도 비운다).

## 계획서 읽기 (F1) — 표 규칙과 AI, 두 경로

협력사 양식은 제각각이라 두 경로를 둔다. 올린 파일에 **표가 있고 머리글을 알아보면 규칙으로 바로 읽고(LLM 안 부름, 0.1초)**,
표가 없거나 읽다가 사람 확인이 필요한 칸이 생기면 **LLM 추출로 넘어간다**(`method` 가 `table_rules` → `llm` 으로 바뀐다).
어느 경로든 결과에 원문 위치(`locator`)와 인용 문장을 붙여 화면에서 근거로 보여 주고, 사람이 확인·수정한 뒤 제출한다.

- 샘플 9건 중 8건은 표 규칙으로 읽힌다. **`가상-제관F_하강관_가스청정_보수계획.pdf` 한 건은 일부러 표 없는 공문 형식**이라 LLM 경로로 간다 (약 20초)
- `POST /api/plans?mode=llm` 으로 어떤 파일이든 LLM 경로를 강제할 수 있다 (`mode`: `auto` 기본 · `llm` · `rules`)
- 두 해석이 다르면 경고로 남긴다. 표 날짜 칸은 규칙 값을 쓰고, 표가 없는 줄글이면 LLM 이 읽은 시작·종료 쌍을 쓴다
- 정확도 비교: `cd app/backend && uv run python ../samples/accuracy.py` (규칙) / `--mode llm` (AI)

## 챗봇 (F6)

질문 → 조회 함수 → 근거 붙은 답. LLM 은 질문 해석(조회 도구 고르기)과 답 문장만 쓰고, 조회와 권한(협력사는 자기 작업 + 원청이 공유한 겹침만)은 서버 코드가 한다. SQL 은 실행하지 않는다.

```bash
npm run chat:check -- --provider unsloth   # Qwen(Unsloth Studio)으로 기능별 점검 (임시 DB, 합성 데이터)
npm run chat:check                         # CHAT_PROVIDER → LLM_PROVIDER 로 점검 (Claude 로 바꾼 뒤)
```

- API: `POST /api/chat?contractor=가상-배관O` 본문 `{"question": "내 작업과 겹치는 작업은?", "today": "2027-02-19"}`, 연결 확인 `GET /api/chat/status`
- `.env` 의 `CHAT_PROVIDER`·`CHAT_MODEL`·`CHAT_EFFORT` 로 챗봇만 다른 제공자·모델·생각 깊이를 쓴다(비우면 `LLM_PROVIDER`·기본 모델). 모델 비교: `npm run chat:check -- --provider claude --model claude-haiku-5-5`
- 응답이 늦으면: 질문 해석 `CHAT_PLAN_TIMEOUT`(20초)·답 `CHAT_ANSWER_TIMEOUT`(30초)·전체 `CHAT_TOTAL_TIMEOUT`(45초)을 넘는 순간 LLM 을 기다리지 않고 규칙으로 해석·답한다. 응답의 `plan_by`·`answer_by`·`notice` 로 화면에 알린다. 화면(fetch)은 60초에서 끊는다
- LLM 답에 조회 결과 밖의 작업 번호·업체가 나오면 규칙 답으로 바꾼다 (협력사에게 다른 업체 정보가 새지 않게)

## 실행

```bash
cp .env.example .env      # Windows: copy .env.example .env  → ANTHROPIC_API_KEY 입력
npm run setup             # 커밋 훅 연결 + 루트·프론트 npm ci + 백엔드 uv sync --locked (lock 파일 그대로 설치)
npm run seed              # DB 초기화 + 시연용 제출 이력 2건 (합성 데이터)
npm run dev               # API http://localhost:8000 + 웹 http://localhost:5173
npm test                  # 백엔드 pytest
npm run build             # 프론트 타입 검사·빌드
```

## API

FastAPI, 주소 `http://localhost:8000/api` (웹은 Vite가 `/api`를 그대로 넘긴다). 실행 중이면 `http://localhost:8000/docs`에서 요청·응답 모양을 바로 볼 수 있다. 요청·응답 타입은 `app/backend/schemas.py` ↔ `app/frontend/src/types.ts`.

**공통 약속**
- **보는 사람:** 협력사로 볼 때는 `?contractor=가상-배관O`처럼 업체명을 붙이고, 원청은 비운다. 권한은 서버가 거른다 — 협력사는 자기 작업과 원청이 공유한 충돌의 상대 작업만 받고, 상대 업체의 원문 문장·투입 인원은 받지 않는다
- **원청 전용**(협력사로 부르면 403): 조정안 조회·적용·되돌리기, 협력사 공유, TBM 공지 추가
- **책임자 필수**(비면 422): 조정 적용·되돌리기(`decided_by`), 공유(`shared_by`), TBM 공지(`created_by`)·전달 확인(`checked_by`) — 제64조 이행 기록의 "누가"
- **판정 시점:** 계획서 제출 순간(`POST /plans/submit`). 적용·되돌리기 응답의 `refresh`가 `true`면 화면을 한 번 새로고침한다
- 충돌 ID에는 `:`와 `>`가 들어가므로 경로에 넣을 때 URL 인코딩한다

| 기능 | 메서드 · 경로 | 하는 일 |
|---|---|---|
| 기준 | `GET /health` | 서버·LLM 제공자 확인 |
| 기준 | `GET /zones` | 구역 14개와 수직 순서 (`data/zones.csv`) |
| 기준 | `GET /rules` | 충돌 규칙 R01~R30 (`data/conflict_rules.csv`) |
| 기준 | `GET /contractors` | '보는 사람'에서 고를 협력사 (작업 분해표 업체 + 계획서를 낸 업체) |
| F2·F3 | `GET /tasks?contractor=` | 현재 일정: 기준 일정(`USE_BASELINE=false`면 없음) + 제출 계획서 + 적용 중인 조정 |
| F2 | `GET /overlaps?contractor=` | 규칙 판정 전 겹침 후보 (같은 구역·위아래·전 구역) |
| F1 | `POST /plans?mode=auto\|llm\|rules&refresh=` | 계획서 파일(HWPX·엑셀·PDF·Word) → 구조화 결과, 원문 근거, 확인 필요 표시, F8 표준서 매칭 (같은 파일은 캐시) |
| F1·F2 | `POST /plans/submit` | 사람이 확인·수정한 작업 제출 → 그 순간 전체 일정 판정·저장. 계획서의 업체와 제출 협력사가 다르면 422. 응답은 제출 협력사에게 공유된 충돌만 |
| F5 | `GET /plans?contractor=` | 제출 이력 (버전·제출자) |
| F2 | `GET /conflicts?contractor=&include_resolved=` | 저장된 판정 (규칙 ID·법 조문·원문 근거, 상태, `plan_id` = 이 충돌을 처음 드러낸 제출). 협력사는 공유된 자기 충돌만 |
| F4 | `GET /conflicts/{id}/adjustments?polish=` | 조정안 후보 (일정 이동, 추천 안이 맨 앞). `polish=true`면 이유 문장만 LLM으로 다듬음 · 원청 |
| F4 | `POST /adjustments` | 조정안 적용 → 즉시 재판정, 사라진·새로 생긴 충돌 비교. 적용하면 그 충돌은 협력사에 공유됨 · 원청 |
| F4 | `DELETE /adjustments/{id}?decided_by=` | 조정 되돌리기 → 재판정 · 원청 |
| F4·F5 | `GET /adjustments?contractor=&task_id=` | 조정 기록 (적용 중·되돌림·재제출로 무효) |
| F9 | `GET /risk-windows?contractor=&on=&zone_id=&trade=&polish=` | 구역별 위험 시간대·점수(가중치는 팀 설정값)·근거·공지 문장. `on=YYYY-MM-DD`면 그날만 |
| F5 | `POST /shares` | 원청이 확인한 충돌을 협력사에 공유 · 원청 |
| F5 | `GET /shares?contractor=` | 공유된 충돌을 인접 작업·위험 요소·작업 인계 조건으로 추린 것 |
| F5 | `GET /history?contractor=` | 이행 기록(제64조): 제출·판정·공유·조정·TBM·현장 기록, 시각순 |
| F5 | `GET /history/export?contractor=` | 이행 기록 엑셀 (합성 데이터 표시, 같은 권한 범위) |
| F8 | `GET /sops` | 작업표준서 목록 (적용 유형·작업 예·필수 단계·핵심 단계) |
| F8 | `GET /sops/{id}` | 표준서 한 건 + 본문 |
| F8 | `GET /sop-matches?contractor=` | 현재 일정 작업별 표준서 매칭·필수 단계 기재 여부 (주 표준서의 핵심 단계가 빠지면 F2 결함) |
| F7 | `GET /tbm/checklist?contractor=&on=` | 그 업체·날짜에 TBM에서 전달할 항목 (공유된 조정·위험 시간대·원청 공지, 서버가 만듦). `contractor` 필수 |
| F7 | `POST /tbm/notices` | 전달 항목에 원청 공지 추가 · 원청 |
| F7 | `POST /tbm/transcribe` | 녹음(wav·m4a·mp3·webm·ogg, 참석자 동의 필수) → 전사문. 원본은 받아쓴 뒤 지움 |
| F7 | `POST /tbm/checks?contractor=` | 전사문이 전달 항목을 담았는지 판정·기록 (LLM 판단 + 규칙 확인). 협력사는 자기 업체만 |
| F7 | `GET /tbm/checks?contractor=` | TBM 전달 확인 기록 (최근순) |
| F6 | `POST /chat?contractor=` | 질문 → 조회 함수(도구) → 근거 붙은 답. 권한 범위 안에서만 답하고, LLM이 늦거나 실패하면 규칙으로 대신 답함 |
| F6 | `GET /chat/status` | 챗봇 LLM 연결 확인 (`CHAT_PROVIDER` 또는 `LLM_PROVIDER`) |

## DB (팀원이 같은 상태를 보는 방법)

DB는 SQLite 파일 하나(`app/backend/hansotbap.db`)이고 **각자 PC에 따로 생긴다.** 파일은 공유하지 않는다 — 바이너리라 merge가 안 되고 누가 최신인지 알 수 없게 된다. 대신 **시드 스크립트를 공유**해서 각자 같은 상태를 다시 만든다.

```bash
npm run seed       # 비우고 시연용 제출 이력을 넣는다 (여러 번 돌려도 결과가 같다)
npm run db:reset   # 비우기만 한다 (시연 직전 "아무도 올리지 않은" 상태)
```

- **문서에서 읽은 데이터만 쓰려면** `.env`에 `USE_BASELINE=false`를 넣고 백엔드를 다시 켠 뒤 `npm run db:reset`. 기준 일정(합성 작업 분해표 37건)이 화면·판정에서 빠지고, 올린 계획서로만 일정을 만든다. 예: S1 순서 위반을 보려면 축로I·배관O 계획서를 둘 다 올린다. `npm run seed`는 쓰지 않는다(합성 제출·현장 기록을 넣는다)

- 기준 일정(작업 37개)은 `data/gy2bf_wbs.csv` 에서 읽으므로 시드할 것이 없다. 시드는 **협력사 제출 이력**만 넣는다
- 시연 핵심 장면(S1)의 배관 계획서는 일부러 넣지 않는다 — 시연 중에 직접 올리는 파일이다
- **스키마를 바꾸면** 커밋 메시지에 `[db]` 를 붙이고 팀에 알린다. 받은 사람은 `npm run db:reset`. (해커톤 범위에서는 마이그레이션을 만들지 않고 비우고 다시 만든다)
- **저장소를 OneDrive·Google Drive·Dropbox 폴더 안에 clone 하지 않는다.** 동기화가 파일 잠금을 깨서 SQLite가 깨진다. `C:\Dev\` 같은 로컬 경로에 둔다
- 통합 테스트 때 백엔드 한 대를 같이 쓰려면: `uv run uvicorn main:app --host 0.0.0.0 --port 8000` + `config.py` 의 `cors_origins` 에 팀원 주소 추가. 개발 중에는 각자 로컬로 띄우는 게 안전하다 (그 PC가 꺼지면 전원이 멈추고, 동시에 올리면 서로 덮어쓴다)

`npm run setup` 은 lock 파일을 고치지 않는다. 라이브러리를 추가할 때만 `npm --prefix app/frontend install <패키지>` 또는 `cd app/backend && uv add <패키지>` 를 쓰고, 바뀐 lock 파일(`package-lock.json`·`uv.lock`)을 같은 커밋에 넣는다.

API 문서: http://localhost:8000/docs

shadcn/ui(radix, Nova 프리셋)는 초기화돼 있고 기본 컴포넌트 20개가 `app/frontend/src/components/ui/` 에 있다. 더 필요하면 `cd app/frontend && npx shadcn@latest add <이름>` 으로 추가하고 `package-lock.json` 을 같은 커밋에 넣는다. 툴팁을 쓰려면 앱을 `TooltipProvider` 로 감싼다.

## 협업 규칙 (기획서 9장)

- `main` 은 항상 시연 가능한 상태. 기능 번호로 브랜치: `feat/F1-extract`, `feat/F2-rules` …
- 커밋: `[F2] 위아래 충돌 규칙 추가` 처럼 기능 번호를 앞에
- PR은 작게 자주, 다른 개발자 1명 확인 후 merge (리뷰 30분 안에). 기능별 이슈를 PR에 연결
- 커밋·PR·이슈에 AI 도구 서명(Co-Authored-By 등)을 넣지 않는다. `npm run setup` 이 커밋 훅(`.githooks/commit-msg`)을 연결해 자동으로 지운다
- API 키는 `.env` 에만. `.env` 는 커밋하지 않는다
- 판정은 규칙(`rules/`), LLM은 추출·설명·문장만. 모든 판정에 규칙 ID·법 조문·원문 문장을 붙인다
