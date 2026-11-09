// 실사용 화면(React, API 연결). 시연용 정적 시안은 /prototype/index.html 에 따로 있다.
// 역할(원청/협력사)을 고르면 서버가 걸러 준 데이터로 원청 화면·협력사 화면을 보여 준다
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api/client";
import { restrictionsFrom } from "@/lib/restrictions";
import type { AdjustmentResult, ConflictRecord, OverlapCandidate, PlanRecord, PlanSubmitResult, SopInfo, SopMatch, Task, ViewerRole, Zone } from "@/types";
import { ContractorView } from "@/views/ContractorView";
import { DATE_KEY, PrimeView } from "@/views/PrimeView";

const ROLE_KEY = "hansotbap.role"; // 판정 후 강제 새로고침을 해도 고른 역할이 남게
const NOTICE_KEY = "hansotbap.notice"; // 새로고침 뒤에 보여 줄 제출·조정 결과
const PROJECT_D0 = "2026-11-12"; // 광양 2고로 개수 D0 (백엔드 config.project_d0 와 같은 값)

function loadRole(): ViewerRole {
  try {
    const v = sessionStorage.getItem(ROLE_KEY);
    return v ? (JSON.parse(v) as ViewerRole) : { kind: "prime" };
  } catch {
    return { kind: "prime" };
  }
}

export default function App() {
  const [zones, setZones] = useState<Zone[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [overlaps, setOverlaps] = useState<OverlapCandidate[]>([]);
  const [conflicts, setConflicts] = useState<ConflictRecord[]>([]);
  const [sopMatches, setSopMatches] = useState<SopMatch[]>([]);
  const [sops, setSops] = useState<SopInfo[]>([]);
  const [plans, setPlans] = useState<PlanRecord[]>([]);
  const [allContractors, setAllContractors] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [role, setRole] = useState<ViewerRole>(loadRole);
  const [notice, setNotice] = useState<string | null>(() => sessionStorage.getItem(NOTICE_KEY));

  const contractor = role.kind === "contractor" ? role.contractor : undefined;

  // 역할에 맞게 서버에서 걸러 받는다 (협력사는 자기 작업 + 공유된 충돌의 상대 작업만). 프론트 필터로 대신하지 않는다
  const loadSeq = useRef(0);
  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    try {
      const [z, t, o, c, s, p, lib] = await Promise.all([
        api.zones(),
        api.tasks(contractor),
        api.overlaps(contractor),
        api.conflicts({ contractor }),
        api.sopMatches(contractor),
        api.plans(contractor),
        api.sops(),
      ]);
      if (seq !== loadSeq.current) return; // 역할을 빨리 바꾸면 앞 역할의 늦은 응답이 덮어쓰지 않게
      setZones(z);
      setTasks(t);
      setOverlaps(o);
      setConflicts(c);
      setSopMatches(s);
      setPlans(p);
      setSops(lib);
      setError(null);
    } catch (e) {
      if (seq === loadSeq.current) setError((e as Error).message);
    }
  }, [contractor]);

  useEffect(() => {
    void load();
  }, [load]);

  // 역할 선택 목록은 전체 일정에서 뽑는다 (협력사로 좁혀 받은 뒤에도 다른 업체로 바꿀 수 있게)
  useEffect(() => {
    api.tasks().then((t) => setAllContractors([...new Set(t.map((x) => x.contractor))].filter((c) => c.startsWith("가상-")).sort())).catch(() => {});
  }, []);

  useEffect(() => {
    if (notice) sessionStorage.removeItem(NOTICE_KEY);
  }, [notice]);

  const changeRole = (r: ViewerRole) => {
    sessionStorage.setItem(ROLE_KEY, JSON.stringify(r));
    setRole(r);
  };

  // 기획서: 판정 후 화면을 한 번 강제 새로고침한다. 결과 요약은 새로고침 뒤에 띄운다
  const finishWithRefresh = (text: string, refresh: boolean) => {
    if (refresh) {
      sessionStorage.setItem(NOTICE_KEY, text);
      window.location.reload();
    } else {
      setNotice(text);
      void load();
    }
  };

  const onSubmitted = (r: PlanSubmitResult) => {
    const intro = r.diff?.introduced ?? [];
    const gone = r.diff?.resolved ?? [];
    const parts = [
      `${r.plan.contractor} 계획서 v${r.plan.version} 제출 · 작업 ${r.plan.task_count}건 · 판정 ${r.recheck_ms != null ? `${Math.round(r.recheck_ms)}ms` : ""}`,
      `현재 충돌 ${r.conflicts.length}건`,
      intro.length ? `새로 생긴 충돌 ${intro.length}건: ${intro.map((c) => `${c.id} (${c.grade})`).join(", ")}` : "새로 생긴 충돌 없음",
      gone.length ? `해소된 충돌 ${gone.length}건: ${gone.map((c) => c.id).join(", ")}` : "",
    ].filter(Boolean);
    sessionStorage.removeItem(DATE_KEY); // 원청 화면이 이 제출이 낸 충돌 날짜로 가게
    finishWithRefresh(parts.join(" · "), r.refresh);
  };

  const onAdjusted = (r: AdjustmentResult) => {
    const a = r.record.adjustment;
    const text = `조정 적용: ${a.task_id} 일정 이동 (${a.decided_by}) · 사라진 충돌 ${r.diff.resolved.length}건 · 새로 생긴 충돌 ${r.diff.introduced.length}건 · 현재 충돌 ${r.conflicts.length}건`;
    // 적용 결과 카드를 잠깐 보여 준 뒤 새로고침 (기획서: 판정 후 강제 새로고침)
    window.setTimeout(() => finishWithRefresh(text, r.refresh), 1500);
  };

  const contractors = useMemo(() => {
    const fromTasks = [...new Set(tasks.map((t) => t.contractor))].filter((c) => c.startsWith("가상-"));
    return [...new Set([...allContractors, ...fromTasks])].sort();
  }, [tasks, allContractors]);
  const roleValue = role.kind === "prime" ? "prime" : role.contractor;

  // 금지 판정 → 구역별 출입 제한 (안내 패널과 3D가 같이 쓴다). 협력사는 서버가 걸러 준 충돌 기준이라 자기 것만 나온다
  const restrictions = useMemo(() => restrictionsFrom(conflicts.map((r) => r.conflict), tasks), [conflicts, tasks]);

  const dday = (iso: string) => Math.round((new Date(`${iso.slice(0, 10)}T00:00:00`).getTime() - new Date(`${PROJECT_D0}T00:00:00`).getTime()) / 86400000);

  return (
    <div className="min-h-screen text-ink">
      <header className="sticky top-0 z-20 border-b border-stone-200 bg-white">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2 xl:px-6">
          <div className="flex items-center gap-2.5">
            <svg viewBox="0 0 32 32" aria-hidden="true" className="h-8 w-8">
              <path d="M5 14h22v4c0 5-4.5 9-11 9S5 23 5 18z" fill="#192027" />
              <rect x="3" y="12" width="26" height="3" rx="1.5" fill="#192027" />
              <path d="M11 9c0-2 2-2 2-4M16 9c0-2 2-2 2-4M21 9c0-2 2-2 2-4" stroke="#7d8893" fill="none" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
            <div>
              <div className="text-[15px] font-bold leading-tight">한솥밥</div>
              <div className="text-[11.5px] text-stone-500">광양 2고로 개수 · 협력사 동시작업 간섭 감지</div>
            </div>
          </div>
          <div className="hidden items-center gap-3 text-xs text-stone-500 md:flex">
            <span>
              D0 {PROJECT_D0} · 화입 예정 2027-03-23 (D{dday("2027-03-23")})
            </span>
            <span>작업 {tasks.length}건 · 업체 {new Set(tasks.map((t) => t.contractor)).size}곳 · 표준서 {sops.length}건</span>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${error ? "bg-red-500" : "bg-ok"}`} title={error ? "API 연결 실패" : "API 연결됨"} />
            <span className="rounded bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">합성 데이터</span>
            <label className="flex items-center gap-1 text-xs text-stone-500">
              보는 사람
              <select
                value={roleValue}
                onChange={(e) => changeRole(e.target.value === "prime" ? { kind: "prime" } : { kind: "contractor", contractor: e.target.value })}
                className="rounded border border-stone-300 bg-white px-2 py-1 text-sm text-stone-900"
              >
                <option value="prime">원청 (전체)</option>
                {contractors.map((c) => (
                  <option key={c} value={c}>
                    협력사: {c}
                  </option>
                ))}
              </select>
            </label>
            <a href="/prototype/index.html" className="rounded border border-stone-300 px-2 py-1 text-xs text-stone-600 hover:bg-stone-50" title="합성 데이터로 흐름을 보여 주는 정적 시안">
              시연판 열기
            </a>
          </div>
        </div>
      </header>

      <main className="px-4 py-4 xl:px-6">
        {error && (
          <p className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700">
            API 연결 실패: {error} — 백엔드(8000)가 켜져 있는지, 8000 포트를 다른 프로그램이 쓰고 있지 않은지 확인하세요.
          </p>
        )}
        {notice && (
          <div className="mb-4 flex items-start gap-3 rounded border border-ok bg-ok-soft p-3 text-sm text-ok">
            <span className="flex-1">{notice}</span>
            <button type="button" onClick={() => setNotice(null)} className="text-xs text-ok underline">
              닫기
            </button>
          </div>
        )}

        {role.kind === "prime" ? (
          <PrimeView
            zones={zones}
            tasks={tasks}
            overlaps={overlaps}
            conflicts={conflicts}
            sopMatches={sopMatches}
            sops={sops}
            plans={plans}
            restrictions={restrictions}
            onAdjusted={onAdjusted}
            onShared={() => void load()}
          />
        ) : (
          <ContractorView
            key={role.contractor} // 다른 협력사로 바꾸면 앞 업체의 날짜·탭·올리던 계획서를 넘겨받지 않게 새로 그린다
            contractor={role.contractor}
            zones={zones}
            tasks={tasks}
            conflicts={conflicts}
            sopMatches={sopMatches}
            sops={sops}
            plans={plans}
            restrictions={restrictions}
            onSubmitted={onSubmitted}
          />
        )}
      </main>
    </div>
  );
}
