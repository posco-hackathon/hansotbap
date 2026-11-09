/* 한솥밥 3D · 단독 실행(/scene3d/index.html)에서 백엔드(FastAPI, 같은 출처의 /api) 데이터를 읽는다.
   - React 앱과 같은 API 클라이언트(src/api/client.ts)와 데이터 계약(src/types.ts ↔ app/backend/schemas.py)을 쓴다.
   - iframe(embed) 안에서는 부모 화면이 postMessage로 넘기므로 쓰지 않는다.
   - ?source=sample 이면 서버를 부르지 않고 합성 시안 데이터(data.js)를 쓴다. 서버가 꺼져 있어도 data.js로 돌아간다.
   - 권한은 서버가 거른다: 협력사로 보면 ?contractor= 로 불러 자기 작업 + 원청이 공유한 충돌의 상대 작업만 받는다.
   - 판정은 서버 규칙(R01~R30)이 한 것을 그대로 쓴다. 여기서는 모양만 바꾼다 (adapter.js). */
import { api } from "@/api/client";
import { restrictionsFrom } from "@/lib/restrictions";
import { defaultBoardDate } from "@/lib/siteDate";
import type { Task } from "@/types";
import { companiesFrom, fromHansotbap, type Scene3DCompany, type Scene3DData } from "./adapter.js";

export const POLL_MS = 10000; // 원청·협력사가 다른 화면에서 제출·조정·공유하면 3D에 반영되는 주기 [팀 설정값]

export interface ViewResult {
  data: Scene3DData;
  sig: string; // 바뀐 게 있을 때만 다시 그리려고 비교하는 값
}

export type BootResult =
  | { companies: Scene3DCompany[]; contractor: string | null; data: Scene3DData; sig: string; date: string | null; error?: undefined }
  | { error: string; data?: undefined };

/* 기본 날짜: 오늘(공사 기간 밖이면 가장 가까운 공사일). 계획서를 낸 직후 한 번만 그 제출이 낸 충돌 날로 간다.
   React 화면(PrimeView·ContractorView)과 같은 규칙 — lib/siteDate.ts 하나를 같이 쓴다 */
async function pickDate(allTasks: Task[]): Promise<string | null> {
  const [plans, records] = await Promise.all([api.plans(), api.conflicts()]);
  return defaultBoardDate({ plans, conflicts: records, tasks: allTasks });
}

/* 보는 사람(협력사면 그 업체, 원청이면 null)의 권한으로 서버가 거른 작업·충돌 → scene3d 데이터.
   companies 는 처음에 받은 전체 업체 목록을 계속 쓴다 (역할을 바꿔도 업체 색이 바뀌지 않게) */
export async function loadView(contractor: string | null, companies?: Scene3DCompany[]): Promise<ViewResult> {
  const who = contractor ?? undefined;
  const [tasks, records] = await Promise.all([api.tasks(who), api.conflicts({ contractor: who })]);
  const conflicts = records.map((r) => r.conflict);
  // 금지 판정 → 구역별 출입 제한: React 화면과 같은 함수 (3D가 안전띠·출입 금지 표지를 세운다)
  const data = fromHansotbap({ tasks, conflicts, restrictions: restrictionsFrom(conflicts, tasks) });
  if (companies) data.companies = companies;
  const sig = JSON.stringify([
    tasks.map((t) => [t.id, t.start, t.end, t.zone_id]),
    records.map((r) => [r.conflict.id, r.status, r.shared_at]),
  ]);
  return { data, sig };
}

/* 처음 한 번: 전체 업체 목록(역할 선택·색), 보는 사람의 데이터, 날짜(?date= 가 없으면 서버 판정으로 고름).
   실패하면 { error } — 부르는 쪽이 합성 데이터로 계속한다 */
export async function bootFromApi(qs: URLSearchParams): Promise<BootResult> {
  try {
    const all = await api.tasks();
    const companies = companiesFrom(all);
    const roleId = qs.get("role");
    const contractor = roleId && roleId !== "PRIME" && companies.some((c) => c.id === roleId) ? roleId : null;
    const [view, date] = await Promise.all([loadView(contractor, companies), qs.get("date") ?? pickDate(all)]);
    return { companies, contractor, data: view.data, sig: view.sig, date };
  } catch (e) {
    console.warn("[scene3d] 서버 데이터를 불러오지 못해 합성 시안 데이터로 엽니다", e);
    return { error: String((e as Error)?.message ?? e) };
  }
}
