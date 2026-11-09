// 화면 기본 날짜는 "오늘"이다. 어느 화면에서도 날짜를 코드에 박지 않는다.
// 오늘이 공사 기간 밖이면(착공 전·화입 후) 가장 가까운 공사일로 당긴다 — 빈 화면으로 열리지 않게.
import { useEffect, useState } from "react";
import type { Conflict, ConflictRecord, PlanRecord, Task } from "@/types";
import { GRADE_RANK } from "@/lib/format";

/** 광양 2고로 개수 D0 = 종풍일 (백엔드 config.project_d0 와 같은 값) */
export const PROJECT_D0 = "2026-11-12";
/** 기준 일정의 첫 작업일. 가설·조립장 같은 사전 준비는 D0 보다 앞선다 (data/gy2bf_wbs.csv P01 시작일) */
export const SCHEDULE_START = "2026-06-15";
/** 화입 예정일 (data/gy2bf_wbs.csv 의 마지막 작업 종료일) */
export const PROJECT_END = "2027-03-23";

/** 오늘 (YYYY-MM-DD, 브라우저가 있는 시간대 기준 — UTC 로 밀려 하루 어긋나지 않게 직접 만든다) */
export function todayISO(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 일정이 있는 기간 안으로 당긴다 (첫 작업 전 → 첫 작업일, 화입 후 → 마지막 날) */
export function clampToProject(iso: string): string {
  if (iso < SCHEDULE_START) return SCHEDULE_START;
  if (iso > PROJECT_END) return PROJECT_END;
  return iso;
}

/** 화면이 처음 열릴 때 보여 줄 날짜 = 오늘(공사 기간 안으로 당김) */
export function defaultSiteDate(): string {
  return clampToProject(todayISO());
}

/** 종풍(D0) 으로부터 며칠째인지. D0 당일 = D1, D0 전이면 0 이하 */
export function dday(iso: string): number {
  const ms = new Date(`${iso.slice(0, 10)}T00:00:00`).getTime() - new Date(`${PROJECT_D0}T00:00:00`).getTime();
  return Math.round(ms / 86400000) + 1;
}

/** 두 날짜 사이 일수 */
export function daysBetween(from: string, to: string): number {
  const ms = new Date(`${to.slice(0, 10)}T00:00:00`).getTime() - new Date(`${from.slice(0, 10)}T00:00:00`).getTime();
  return Math.round(ms / 86400000);
}

/** 오늘이 일정 기간 밖이라 날짜를 당겼는지 (화면에 안내를 붙일 때) */
export function isOutsideProject(iso: string = todayISO()): "before" | "after" | null {
  if (iso < SCHEDULE_START) return "before";
  if (iso > PROJECT_END) return "after";
  return null;
}

// ── 제출 직후 한 번만: 그 제출이 낸 충돌 날짜로 보낸다 ────────────────────
// 기본은 어디까지나 오늘이고, 계획서를 낸 직후에만 그 충돌이 있는 날로 옮긴다.
// (예전에는 DB 에 제출 이력이 있기만 하면 늘 그 충돌 날짜로 열려서, 화면이 2027년으로 시작했다)
const JUMP_KEY = "hansotbap.jumpToLatestConflict";

/** 계획서 제출 직후 호출 — 다음 한 번의 기본 날짜를 "그 제출이 낸 충돌 날"로 만든다 */
export function markJumpToLatestConflict(): void {
  try {
    sessionStorage.setItem(JUMP_KEY, "1");
  } catch {
    /* 저장이 막혀 있으면 그냥 오늘로 연다 */
  }
}

/** 표식이 있으면 지우고 true (한 번만 쓴다) */
function takeJumpFlag(): boolean {
  try {
    if (sessionStorage.getItem(JUMP_KEY) !== "1") return false;
    sessionStorage.removeItem(JUMP_KEY);
    return true;
  } catch {
    return false;
  }
}

/** 충돌 목록에서 가장 높은 등급(같으면 먼저 시작)의 날 */
export function topConflictDate(conflicts: Conflict[]): string | null {
  const top = [...conflicts].sort((a, b) => GRADE_RANK[b.grade] - GRADE_RANK[a.grade] || a.window_start.localeCompare(b.window_start))[0];
  return top ? top.window_start.slice(0, 10) : null;
}

/**
 * 화면 기본 날짜. 평소에는 오늘이고, 계획서를 낸 직후 한 번만 그 제출이 낸 충돌 날로 간다.
 * 원청 화면·협력사 화면·3D 가 같은 규칙을 쓴다.
 */
export function defaultBoardDate(opts: { plans?: PlanRecord[]; conflicts?: ConflictRecord[]; tasks?: Task[] }): string {
  const { plans = [], conflicts = [], tasks = [] } = opts;
  if (!plans.length && !conflicts.length) return defaultSiteDate(); // 아직 서버 응답 전 — 표식은 그대로 둔다
  if (!takeJumpFlag()) return defaultSiteDate();
  const latest = [...plans].sort((a, b) => b.id - a.id)[0];
  const mine = new Set(tasks.filter((t) => latest && t.contractor === latest.contractor).map((t) => t.id));
  const pool = conflicts.map((r) => r.conflict).filter((c) => !latest || c.task_ids.some((id) => mine.has(id)));
  return topConflictDate(pool) ?? defaultSiteDate();
}

/**
 * 화면이 쓸 기본 날짜. 서버 응답이 오기 전에는 오늘을 보여 주고, 데이터가 들어오면 한 번만 다시 정한다.
 *
 * 제출 뒤에는 화면을 강제 새로고침하므로(기획서) 첫 렌더에는 작업·충돌이 비어 있다.
 * 그때 바로 정해 버리면 "방금 낸 계획서가 만든 충돌 날로 간다"가 동작하지 않는다.
 */
export function useDefaultBoardDate(opts: { plans?: PlanRecord[]; conflicts?: ConflictRecord[]; tasks?: Task[] }): string {
  const { plans = [], conflicts = [], tasks = [] } = opts;
  const [resolved, setResolved] = useState<string | null>(null);
  useEffect(() => {
    if (resolved !== null) return;
    if (!plans.length && !conflicts.length) return; // 아직 못 받았다
    setResolved(defaultBoardDate({ plans, conflicts, tasks }));
  }, [plans, conflicts, tasks, resolved]);
  return resolved ?? defaultSiteDate();
}
