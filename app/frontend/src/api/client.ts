import type {
  AdjustmentApply,
  AdjustmentCandidate,
  AdjustmentRecord,
  AdjustmentResult,
  ConflictRecord,
  HistoryEvent,
  OverlapCandidate,
  PlanExtraction,
  PlanRecord,
  PlanSubmission,
  PlanSubmitResult,
  RiskWindow,
  Rule,
  SharedItem,
  ShareRequest,
  SopInfo,
  SopMatch,
  Task,
  TbmCheckRecord,
  TbmCheckRequest,
  TbmChecklist,
  TbmNotice,
  TbmNoticeCreate,
  TbmTranscript,
  Zone,
} from "@/types";

/** 서버 오류 본문(detail)을 사람이 읽을 문장으로 */
async function errorMessage(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    const d = body.detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "problems" in d) {
      const p = d as { message?: string; problems?: string[] };
      return [p.message, ...(p.problems ?? [])].filter(Boolean).join("\n");
    }
    return text || `${res.status}`;
  } catch {
    return text || `${res.status}`;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json() as Promise<T>;
}

const get = <T>(path: string) => request<T>(path);
const json = <T>(path: string, method: string, body: unknown) =>
  request<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** 협력사로 보면 `contractor`를 붙인다 — 권한은 서버에서 거른다 (프론트 필터로 대신하지 않는다) */
function qs(params: Record<string, string | boolean | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === false || v === "") continue;
    q.set(k, v === true ? "true" : v);
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const api = {
  zones: () => get<Zone[]>("/zones"),
  rules: () => get<Rule[]>("/rules"),
  // 협력사로 보면 자기 작업 + 공유된 충돌의 상대 작업만 (상대 작업의 source 는 null). 원청은 비워 둔다
  tasks: (contractor?: string) => get<Task[]>(`/tasks${qs({ contractor })}`),
  overlaps: (contractor?: string) => get<OverlapCandidate[]>(`/overlaps${qs({ contractor })}`),

  // ── F2 판정 결과 ───────────────────────────────────────────────────
  conflicts: (opts: { contractor?: string; includeResolved?: boolean } = {}) =>
    get<ConflictRecord[]>(`/conflicts${qs({ contractor: opts.contractor, include_resolved: opts.includeResolved })}`),

  // ── F1 계획서 업로드 → 구조화 → 제출(이 순간 F2 판정) ──────────────
  uploadPlan: async (file: File, opts: { contractor?: string; refresh?: boolean } = {}) => {
    const body = new FormData();
    body.append("file", file);
    if (opts.contractor) body.append("contractor", opts.contractor);
    const res = await fetch(`/api/plans${qs({ refresh: opts.refresh })}`, { method: "POST", body });
    if (!res.ok) throw new Error(await errorMessage(res));
    return res.json() as Promise<PlanExtraction>;
  },
  submitPlan: (sub: PlanSubmission) => json<PlanSubmitResult>("/plans/submit", "POST", sub),
  plans: (contractor?: string) => get<PlanRecord[]>(`/plans${qs({ contractor })}`),

  // ── F8 작업표준서 ──────────────────────────────────────────────────
  sops: () => get<SopInfo[]>("/sops"),
  sop: (id: string) => get<SopInfo>(`/sops/${encodeURIComponent(id)}`),
  // 현재 일정(협력사별 최근 제출분)의 작업별 표준서 매칭. 협력사로 보면 자기 작업만
  sopMatches: (contractor?: string) => get<SopMatch[]>(`/sop-matches${qs({ contractor })}`),

  // ── F4 조정안 (원청 전용 — 협력사로 부르면 서버가 403) ─────────────
  // 충돌 ID에는 ':'와 '>'가 들어가므로 경로에 넣을 때 encodeURIComponent 를 쓴다
  adjustmentCandidates: (conflictId: string, polish = false) =>
    get<AdjustmentCandidate[]>(`/conflicts/${encodeURIComponent(conflictId)}/adjustments${qs({ polish })}`),
  applyAdjustment: (body: AdjustmentApply) => json<AdjustmentResult>("/adjustments", "POST", body),
  revertAdjustment: (adjustmentId: string, decidedBy: string) =>
    request<AdjustmentResult>(`/adjustments/${encodeURIComponent(adjustmentId)}${qs({ decided_by: decidedBy })}`, {
      method: "DELETE",
    }),
  adjustments: (opts: { contractor?: string; taskId?: string } = {}) =>
    get<AdjustmentRecord[]>(`/adjustments${qs({ contractor: opts.contractor, task_id: opts.taskId })}`),

  // ── F5 공유·이행 기록 ──────────────────────────────────────────────
  // 원청이 확인한 충돌을 협력사에 공유 (원청 전용 — 협력사로 부르면 서버가 403). 이미 공유한 건은 처음 기록 유지
  share: (body: ShareRequest) => json<ConflictRecord[]>("/shares", "POST", body),
  // 협력사로 보면 자기 작업이 걸린 공유만 (최근 공유순)
  shares: (contractor?: string) => get<SharedItem[]>(`/shares${qs({ contractor })}`),
  history: (contractor?: string) => get<HistoryEvent[]>(`/history${qs({ contractor })}`),
  // 이행 기록 엑셀은 파일 내려받기라 fetch 대신 <a href={api.historyExportUrl(...)}> 로 연다
  historyExportUrl: (contractor?: string) => `/api/history/export${qs({ contractor })}`,

  // ── F9 위험 시간대 ─────────────────────────────────────────────────
  // 하루를 그리는 화면(간트)은 on 에 그 날짜(YYYY-MM-DD)를 넣는다. polish 는 공지 화면에서만 (LLM이라 몇 초 걸림)
  riskWindows: (opts: { contractor?: string; trade?: string; zoneId?: string; on?: string; polish?: boolean } = {}) =>
    get<RiskWindow[]>(
      `/risk-windows${qs({ contractor: opts.contractor, trade: opts.trade, zone_id: opts.zoneId, on: opts.on, polish: opts.polish })}`,
    ),

  // ── F7 TBM 전달 확인 ───────────────────────────────────────────────
  // 그 업체·날짜에 전달할 항목. 서버가 공유된 조정·위험 시간대·원청 공지로 만든다 (contractor 는 항상 필수)
  tbmChecklist: (contractor: string, on: string) => get<TbmChecklist>(`/tbm/checklist${qs({ contractor, on })}`),
  // 원청 전용 — 협력사로 부르면 서버가 403. 같은 업체·날짜·문장은 처음 기록을 돌려준다
  addTbmNotice: (body: TbmNoticeCreate) => json<TbmNotice>("/tbm/notices", "POST", body),
  // 녹음 → 전사문. 원본은 서버가 받아쓴 뒤 지운다. CPU판 음성 서버는 녹음 길이의 2~3배 걸린다
  transcribeTbm: async (file: File, consent: boolean) => {
    const body = new FormData();
    body.append("file", file);
    body.append("consent", consent ? "true" : "false");
    const res = await fetch("/api/tbm/transcribe", { method: "POST", body });
    if (!res.ok) throw new Error(await errorMessage(res));
    return res.json() as Promise<TbmTranscript>;
  },
  // viewer: 보는 협력사(원청은 비움). 협력사는 자기 업체 TBM만 확인할 수 있다
  checkTbm: (body: TbmCheckRequest, viewer?: string) => json<TbmCheckRecord>(`/tbm/checks${qs({ contractor: viewer })}`, "POST", body),
  tbmChecks: (contractor?: string) => get<TbmCheckRecord[]>(`/tbm/checks${qs({ contractor })}`),
};
