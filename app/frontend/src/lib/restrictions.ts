// 서버 판정(금지 충돌) → 구역별 "작업 금지·출입 제한". 3D(scene3d)의 안전띠·출입 금지 표지와
// 화면의 "출입 제한" 안내가 같은 자료를 쓴다. 판정은 서버 규칙이 한 것이고 여기서는 모양만 바꾼다.
// 한계: 계획서에 구역 안 위치(방위)가 없어서 구역 단위로만 막는다. 방위별 제한은 3D의 브라우저 규칙이 보탠다
import type { Conflict, Task, Zone } from "@/types";

export type Dir = "N" | "E" | "S" | "W";

/** scene3d `data.restrictions` 모양({zone_id,start,end,blocked,reason,source_ids}) + 안내에 쓰는 근거 */
export interface ZoneRestriction {
  zone_id: string;
  start: string; // ISO
  end: string;
  blocked: Dir[]; // 구역 단위라 항상 4방위 전부
  reason: string;
  source_ids: string[]; // 이 제한을 만든 작업들 (3D가 그 작업 자신은 위반으로 보지 않는다)
  conflict_id: string;
  rule_id: string;
  legal_basis: string;
  suggestion: string | null;
  task_ids: string[];
}

const ALL_DIRS: Dir[] = ["N", "E", "S", "W"];

/** 금지 판정(표준서 결함 제외)마다 걸린 작업의 구역을 그 기간 동안 출입 제한으로 본다 */
export function restrictionsFrom(conflicts: Conflict[], tasks: Task[]): ZoneRestriction[] {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const out: ZoneRestriction[] = [];
  for (const c of conflicts) {
    if (c.grade !== "금지" || c.type === "sop_missing") continue;
    const ts = c.task_ids.map((id) => byId.get(id)).filter((t): t is Task => !!t);
    if (ts.length === 0) continue;
    for (const zone_id of new Set(ts.map((t) => t.zone_id))) {
      out.push({
        zone_id,
        start: c.window_start,
        end: c.window_end,
        blocked: ALL_DIRS,
        reason: `${c.rule_id} 금지 · ${ts.map((t) => `${t.contractor} ${t.name}`).join(" × ")}`,
        source_ids: c.task_ids,
        conflict_id: c.id,
        rule_id: c.rule_id,
        legal_basis: c.legal_basis,
        suggestion: c.suggestion,
        task_ids: c.task_ids,
      });
    }
  }
  return out;
}

/** 그날(07:00~다음 날 07:00)에 걸린 것만 */
export function restrictionsOn(list: ZoneRestriction[], date: string): ZoneRestriction[] {
  const dayStart = new Date(`${date}T07:00:00`).getTime();
  const dayEnd = dayStart + 24 * 3600 * 1000;
  return list.filter((r) => new Date(r.start).getTime() < dayEnd && new Date(r.end).getTime() > dayStart);
}

/** 협력사가 보는 것: 내 작업이 걸린 제한만 (서버가 이미 거른 충돌에서 한 번 더 — 상대 작업만 걸린 제한은 빼고 보여 준다) */
export function restrictionsForContractor(list: ZoneRestriction[], tasks: Task[], contractor: string): ZoneRestriction[] {
  const mine = new Set(tasks.filter((t) => t.contractor === contractor).map((t) => t.id));
  return list.filter((r) => r.task_ids.some((id) => mine.has(id)));
}

/** 구역별 묶음 (위층부터) */
export function groupByZone(list: ZoneRestriction[], zones: Zone[]): { zone: Zone; items: ZoneRestriction[] }[] {
  const order = [...zones].sort((a, b) => b.vertical_order - a.vertical_order);
  return order
    .map((zone) => ({ zone, items: list.filter((r) => r.zone_id === zone.id) }))
    .filter((g) => g.items.length > 0);
}
