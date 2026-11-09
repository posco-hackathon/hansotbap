// 데이터 계약 — app/backend/schemas.py 와 같은 모양을 유지한다. 필드를 바꾸면 두 파일을 같이 고친다.

export type Hazard = "hot_work" | "confined" | "height" | "heavy_lift" | "gas";
export type Shift = "day" | "night";
export type ConflictType = "same_time_zone" | "vertical" | "hot_gas" | "sequence" | "sop_missing";
export type Grade = "금지" | "조건부" | "결함";

export interface Zone {
  id: string;
  name: string;
  vertical_order: number; // 클수록 위, -1 = 전 구역
  description: string;
}

export interface SourceRef {
  file: string;
  locator: string | null;
  text: string;
}

export interface Task {
  id: string;
  contractor: string;
  name: string;
  trade: string | null;
  zone_id: string;
  start: string; // ISO datetime
  end: string;
  shift: Shift | null;
  hazards: Hazard[];
  risk_codes: string[];
  predecessors: string[];
  source: SourceRef | null;
}

export interface Conflict {
  id: string;
  type: ConflictType;
  grade: Grade;
  task_ids: string[];
  rule_id: string;
  legal_basis: string;
  window_start: string;
  window_end: string;
  reason: string;
  suggestion: string | null;
  sources: SourceRef[];
}

// 저장된 충돌 하나 (GET /api/conflicts). 판정 결과는 제출 응답에만 두지 않고 DB에 남는다
export type ConflictStatus = "open" | "adjusted" | "resolved";

export interface ConflictRecord {
  conflict: Conflict;
  status: ConflictStatus;
  plan_id: number | null; // 이 충돌을 드러낸 제출
  judged_at: string;
  resolved_at: string | null; // 재판정에서 사라진 시각
  shared_at: string | null; // 원청이 확인해 협력사에 공유한 시각 (null 이면 공유 전)
}

/** GET /api/rules: 충돌 규칙 R01~R30 (data/conflict_rules.csv 한 줄) */
export interface Rule {
  id: string;
  task_a: string;
  task_b: string;
  spatial: string;
  temporal: string;
  grade: string;
  risk_code: string;
  basis: string; // 근거 조문
  adjustment: string; // 조정안 문구
}

// ── F4 조정안·재판정 ──────────────────────────────────────────────────

export type AdjustmentKind = "reschedule";
export type AdjustmentStatus = "active" | "reverted" | "stale";

/** F4 조정안 후보: 규칙이 계산한 일정 이동안 (GET /api/conflicts/{id}/adjustments, 추천 안이 맨 앞) */
export interface AdjustmentCandidate {
  id: string;
  kind: AdjustmentKind;
  task_id: string; // 옮길 작업
  conflict_id: string; // 이 조정안이 풀려는 충돌
  original_start: string; // ISO datetime
  original_end: string;
  new_start: string;
  new_end: string;
  reason: string;
  resolves: boolean; // 적용하면 conflict_id의 충돌이 사라지는가
  new_conflict_ids: string[]; // 적용하면 새로 생기는 충돌
  affected_successors: string[]; // 옮긴 뒤 시작이 이 작업의 새 종료보다 이른 후행 작업
  recommended: boolean; // 후보 중 새 충돌·영향 받는 후행 작업이 가장 적은 안
}

/** 적용한 조정 기록: 협력사 원본 계획서는 그대로 두고 이 기록을 얹어 판정한다 */
export interface Adjustment {
  id: string;
  kind: AdjustmentKind;
  task_id: string;
  conflict_id: string;
  original_start: string;
  original_end: string;
  new_start: string;
  new_end: string;
  reason: string;
  decided_by: string; // 적용한 책임자
  decided_at: string;
}

export interface ConflictGradeChange {
  conflict_id: string;
  before: Grade;
  after: Grade;
}

/** 조정 전후 비교 (Conflict.id 기준) */
export interface ConflictDiff {
  resolved: Conflict[]; // 사라진 충돌
  introduced: Conflict[]; // 새로 생긴 충돌
  grade_changed: ConflictGradeChange[];
}

export interface AdjustmentRecord {
  adjustment: Adjustment;
  status: AdjustmentStatus;
  closed_at: string | null; // 되돌렸거나 무효가 된 시각
}

/** POST /api/adjustments 본문 */
export interface AdjustmentApply {
  conflict_id: string;
  candidate_id: string;
  decided_by: string; // 적용한 책임자
}

export interface AdjustmentResult {
  record: AdjustmentRecord;
  conflicts: Conflict[]; // 재판정 결과
  diff: ConflictDiff;
  recheck_ms: number;
  refresh: boolean;
}

export interface OverlapCandidate {
  task_a: string;
  task_b: string;
  relation: "same_zone" | "vertical" | "all_zone";
  window_start: string;
  window_end: string;
}

// ── F5 공유·이행 기록 ─────────────────────────────────────────────────

/** POST /api/shares 본문: 원청이 확인해 협력사에 내려보낼 충돌 */
export interface ShareRequest {
  conflict_ids: string[];
  shared_by: string; // 확인한 책임자
}

/** 협력사에게 보여 주는 인접 작업. 일정·위치·위험 유형만 담고 상대 업체의 원문은 담지 않는다 */
export interface SharedTask {
  id: string;
  contractor: string;
  name: string;
  zone_id: string;
  start: string;
  end: string;
  hazards: Hazard[];
}

/** GET /api/shares: 협력사 공유 한 건 (인접 위치 작업, 위험 요소, 작업 인계 조건) */
export interface SharedItem {
  conflict_id: string;
  type: ConflictType;
  grade: Grade;
  status: ConflictStatus;
  rule_id: string;
  legal_basis: string;
  window_start: string;
  window_end: string;
  reason: string;
  handover: string | null; // 작업 인계 조건 (조정안 문구)
  my_task_ids: string[]; // 이 협력사의 작업 (원청으로 보면 빈 목록)
  adjacent_tasks: SharedTask[]; // 이 충돌에 걸린 다른 작업
  adjustment: Adjustment | null; // 이 충돌에 적용 중인 조정
  shared_by: string;
  shared_at: string;
}

/** 이행 기록의 구분. 순서는 같은 시각의 기록을 늘어놓는 순서다 */
export type HistoryEventKind =
  | "plan_submitted"
  | "conflict_judged"
  | "conflict_shared"
  | "adjustment_replaced"
  | "adjustment_applied"
  | "conflict_resolved"
  | "adjustment_reverted"
  | "adjustment_stale"
  | "tbm_checked" // TBM 전달 확인
  | "field_record"; // 현장 기록: 교대 인계·착수 승인·잔업 등 사람이 남긴 기록 (구분 이름은 label)

/** GET /api/history: 이행 기록 한 줄 (제64조) */
export interface HistoryEvent {
  at: string;
  kind: HistoryEventKind;
  label: string | null; // 현장 기록의 구분 이름 (교대 인계, 착수 승인 …). 다른 기록은 null
  target_id: string; // plan-<번호>, tbm-<번호>, rec-<번호>(현장 기록) 또는 충돌 ID
  actor: string | null; // 책임자 (시스템이 남긴 기록은 null)
  contractors: string[];
  detail: string;
  rule_id: string | null;
  legal_basis: string | null;
}

// ── F7 TBM 전달 확인 ──────────────────────────────────────────────────

export type TbmItemKind = "adjustment" | "risk_window" | "notice";

/** TBM에서 작업자에게 전달해야 할 항목 하나. 서버가 규칙으로 만든다 */
export interface TbmItem {
  id: string;
  kind: TbmItemKind;
  text: string;
  rule_ids: string[];
  legal_basis: string[];
  conflict_ids: string[];
}

/** GET /api/tbm/checklist */
export interface TbmChecklist {
  contractor: string;
  date: string; // YYYY-MM-DD
  items: TbmItem[];
}

/** POST /api/tbm/notices 본문: 원청이 업체·날짜를 정해 추가하는 공지 */
export interface TbmNoticeCreate {
  contractor: string;
  date: string; // YYYY-MM-DD
  text: string;
  created_by: string;
}

export interface TbmNotice {
  id: number;
  contractor: string;
  date: string; // YYYY-MM-DD
  text: string;
  created_by: string;
  created_at: string;
}

/** POST /api/tbm/transcribe 응답. 원본 녹음은 받아쓴 뒤 지운다 */
export interface TbmTranscript {
  transcript: string;
  model: string;
}

/** POST /api/tbm/checks 본문. 전달 항목은 보내지 않는다 (서버가 만든다) */
export interface TbmCheckRequest {
  contractor: string;
  date: string; // YYYY-MM-DD
  transcript: string;
  checked_by: string;
}

export interface TbmItemResult {
  item: TbmItem;
  mentioned: boolean;
  quote: string | null; // 전달을 뒷받침하는 전사문의 문장
  note: string | null; // LLM 답을 규칙이 뒤집은 까닭
}

/** 저장된 TBM 전달 확인 한 건 (F5 이행 기록에도 남는다) */
export interface TbmCheckRecord {
  id: number;
  contractor: string;
  date: string; // YYYY-MM-DD
  checked_by: string;
  checked_at: string;
  transcript: string;
  results: TbmItemResult[];
  missing_ids: string[]; // 전달이 확인되지 않은 항목
  provider: string;
  model: string;
}

// ── F9 위험 시간대 ────────────────────────────────────────────────────

/** GET /api/risk-windows. 여러 날이 합쳐진 건은 start 날짜~end 날짜 동안 매일 start 시각~end 시각을 뜻한다 */
export interface RiskWindow {
  zone_id: string;
  start: string;
  end: string;
  score: number; // 금지 3, 조건부 2, 결함 1의 합
  contractors: string[];
  conflict_ids: string[];
  weights_note: string;
  trades: string[]; // 관련 공정
  peak_grade: Grade; // 이 시간대에서 가장 높은 등급
  rule_ids: string[];
  legal_basis: string[];
  sources: SourceRef[];
  notice: string; // 공지 문장
}

/** F8 표준서 필수 단계 1개가 계획서에 적혀 있는지 (규칙 판정) */
export interface SopStepCheck {
  no: number;
  text: string;
  critical: boolean; // 핵심 단계 — 빠지면 결함
  found: boolean;
  evidence: SourceRef | null; // 이 단계를 찾은 계획서 원문 줄
}

export interface SopMatch {
  task_id: string;
  sop_id: string;
  title: string;
  score: number;
  reason: string;
  missing_steps: string[]; // 빠진 핵심 단계. 주 표준서(primary)일 때만 → F2 결함
  primary: boolean; // 결함 판정 대상인 주 표준서 (원청 적용 목록 + 작업명 일치)
  basis: string[]; // wbs_example | name | hazard | embedding
  steps: SopStepCheck[];
}

/** GET /api/sops: 원청 작업표준서 (합성) */
export interface SopInfo {
  id: string;
  title: string;
  file: string;
  hazards: string[];
  wbs_examples: string[];
  steps: string[];
  critical_steps: number[]; // 빠지면 결함인 단계 번호 (1부터)
  source: string;
  text: string | null; // 본문(마크다운). 목록 조회에서는 null
}

// 로그인 없이 역할 선택 (원청 / 협력사 A~E)
export type ViewerRole = { kind: "prime" } | { kind: "contractor"; contractor: string };

// ── F1 계획서 구조화 ──────────────────────────────────────────────────

/** 파서가 읽은 원문 한 줄 (원문 근거 하이라이트용) */
export interface SourceLine {
  locator: string;
  text: string;
}

/** 계획서에서 뽑은 작업 1건 + 근거·확인 필요 표시. 사람이 확인·수정한 뒤 task 만 제출한다 */
export interface ExtractedTask {
  task: Task;
  wbs_id: string | null; // 원청 기준 일정(작업 분해표)에서 대응하는 작업 ID
  raw: Record<string, string>; // 원문 그대로: contractor·name·location·period·time·shift·hazards·precondition
  sources: SourceRef[]; // 근거 줄 (파서 원문)
  confidence: number; // 0~1
  needs_review: boolean;
  warnings: string[];
}

/** POST /api/plans 응답 */
export interface PlanExtraction {
  draft_id: string;
  file: string;
  file_sha256: string;
  file_type: string; // pdf | xlsx | hwpx
  method: string; // table_rules | llm
  provider: string | null;
  model: string | null;
  contractor: string | null;
  tasks: ExtractedTask[];
  lines: SourceLine[];
  warnings: string[];
  cached: boolean;
  created_at: string;
  sop_matches: SopMatch[]; // F8 작업별 표준서 매칭·필수 단계 확인 (제출 전 확인 화면용)
}

/** POST /api/plans/submit 본문 */
export interface PlanSubmission {
  contractor: string;
  file: string;
  tasks: Task[];
  submitted_by?: string | null;
  draft_id?: string | null;
}

export interface PlanRecord {
  id: number;
  contractor: string;
  file: string;
  version: number; // 같은 협력사의 몇 번째 제출인지
  submitted_at: string;
  submitted_by: string | null;
  task_count: number;
}

export interface PlanSubmitResult {
  plan: PlanRecord;
  conflicts: Conflict[];
  refresh: boolean; // 판정 후 화면을 한 번 강제 새로고침
  diff: ConflictDiff | null; // 이 제출로 사라지거나 새로 생긴 충돌 (새 충돌 알림)
  recheck_ms: number | null;
}
