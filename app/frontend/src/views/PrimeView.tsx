// 원청 대시보드(현재상황판): 상단 요약 + [현황판: 상황판(BoardView, 시안 #board 레이아웃) + 위험 시간대 공지 + 오늘 출입 제한] / [3D·충돌: scene3d]
// / [충돌 목록: 규칙·조문·원문·조정안·협력사 공유] / [표준서 매칭] / [TBM 확인] / [이력]
import { useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { ConflictFilter, useConflictFilter } from "@/components/ConflictFilter";
import { ConflictList } from "@/components/ConflictList";
import { GradeBadge } from "@/components/ConflictBadge";
import { RiskWindowList } from "@/components/RiskWindowList";
import { SopMatchPanel } from "@/components/SopMatchPanel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { defaultBoardDate } from "@/lib/siteDate";
import { usePerson } from "@/lib/person";
import { groupByZone, restrictionsOn, type ZoneRestriction } from "@/lib/restrictions";
import type { AdjustmentResult, ConflictRecord, Grade, OverlapCandidate, PlanRecord, RiskWindow, SopInfo, SopMatch, Task, Zone } from "@/types";
import { ApprovalPanel } from "@/views/ApprovalPanel";
import { HistoryView } from "@/views/HistoryView";
import { RestrictionPanel } from "@/views/RestrictionPanel";
import { Scene3DTab } from "@/views/Scene3DTab";
import { SopLibrary } from "@/views/SopLibrary";
import { TbmView } from "@/views/TbmView";
import { BoardView } from "@/views/BoardView";

export const DATE_KEY = "hansotbap.date";

interface Props {
  zones: Zone[];
  tasks: Task[];
  overlaps: OverlapCandidate[];
  conflicts: ConflictRecord[]; // 서버 판정 결과 (해소된 것 제외)
  sopMatches: SopMatch[];
  sops: SopInfo[]; // 원청 작업표준서 목록 (공통 4 + 작업별)
  plans: PlanRecord[]; // 제출 이력 (가장 최근 제출을 찾는 데 쓴다)
  restrictions: ZoneRestriction[]; // 금지 판정 → 구역별 출입 제한 (안내 패널·3D 공용)
  onAdjusted: (result: AdjustmentResult) => void;
  onReload: () => void; // 협력사 공유 뒤 다시 불러오기
  onDateChange?: (date: string) => void; // 지금 보는 날짜 (AI 챗봇이 '오늘' 기준으로 쓴다)
}

export function PrimeView({ zones, tasks, overlaps, conflicts, sopMatches, sops, plans, restrictions, onAdjusted, onReload, onDateChange }: Props) {
  // 기본 날짜는 오늘(공사 기간 밖이면 가장 가까운 공사일). 계획서를 낸 직후 한 번만 그 제출이 낸 충돌 날로 간다.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 처음 한 번만 정한다 (제출 표식을 소비하므로 다시 계산하면 안 된다)
  const defaultDate = useMemo(() => defaultBoardDate({ plans, conflicts, tasks }), []);
  // 판정 후 강제 새로고침을 해도 보던 날짜가 남게 한다 (새 제출이 오면 App 이 지워서 새 충돌 날짜로 간다)
  const [dateOverride, setDateOverride] = useState<string | null>(() => sessionStorage.getItem(DATE_KEY));
  const date = dateOverride ?? defaultDate;
  const setDate = setDateOverride;
  useEffect(() => sessionStorage.setItem(DATE_KEY, date), [date]);
  useEffect(() => onDateChange?.(date), [date, onDateChange]);
  const [tab, setTab] = useState("board");
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [sopView, setSopView] = useState<"matches" | "library">("matches");
  const blockedZones = useMemo(() => groupByZone(restrictionsOn(restrictions, date), zones).length, [restrictions, date, zones]);

  const open = useMemo(() => conflicts.map((r) => r.conflict), [conflicts]);
  const todays = useMemo(() => {
    const dayStart = new Date(`${date}T07:00:00`);
    const dayEnd = new Date(`${date}T19:00:00`);
    return tasks.filter((t) => new Date(t.start) < dayEnd && new Date(t.end) > dayStart);
  }, [tasks, date]);
  const contractors = new Set(todays.map((t) => t.contractor));

  // 충돌 목록: 가장 최근 제출이 만든 것만 기본으로 보여 준다 (기준 일정끼리의 충돌 100여 건에 묻히지 않게). 규칙별 묶음도 기본
  const latestPlan = useMemo(() => [...plans].sort((a, b) => b.id - a.id)[0] ?? null, [plans]);
  // F5 원청 승인: 승인 대기 계획서 수(탭 배지). 3D·현황의 "확정" 작업은 승인된 계획서(와 기준 일정)의 것만 — 승인 대기 작업은 3D에 넣지 않는다
  const pendingPlans = useMemo(() => plans.filter((p) => p.status === "pending"), [plans]);
  const approvedTasks = useMemo(() => tasks.filter((t) => t.plan_status !== "pending"), [tasks]);
  const filter = useConflictFilter(conflicts, tasks, date, latestPlan?.id ?? null);
  const [groupRules, setGroupRules] = useState(true);
  const allContractors = useMemo(() => [...new Set(tasks.map((t) => t.contractor))].sort(), [tasks]);

  // F9 그날의 위험 시간대: 판정·조정이 바뀌면(conflicts) 다시 부른다. polish 는 공지 문장만 LLM으로 다듬는다
  const [riskWindows, setRiskWindows] = useState<RiskWindow[]>([]);
  const [polishing, setPolishing] = useState(false);
  useEffect(() => {
    api.riskWindows({ on: date }).then(setRiskWindows).catch(() => setRiskWindows([]));
  }, [date, conflicts]);
  const polishNotices = async () => {
    setPolishing(true);
    try {
      setRiskWindows(await api.riskWindows({ on: date, polish: true }));
    } catch {
      // LLM 이 안 되면 규칙 문장 그대로 둔다
    } finally {
      setPolishing(false);
    }
  };

  // F5 보이는 충돌 중 공유 전인 것을 한꺼번에 협력사에 공유
  const [person, setPerson] = usePerson();
  const [sharing, setSharing] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);
  const unshared = filter.filtered.filter((r) => !r.shared_at && r.status !== "resolved");
  const shareAll = async () => {
    if (!person.trim()) {
      setShareError("확인한 책임자 이름을 적어 주세요 (이행 기록에 남습니다)");
      return;
    }
    setSharing(true);
    setShareError(null);
    try {
      await api.share({ conflict_ids: unshared.map((r) => r.conflict.id), shared_by: person.trim() });
      onReload();
    } catch (e) {
      setShareError((e as Error).message);
    } finally {
      setSharing(false);
    }
  };

  const counts = { 금지: 0, 조건부: 0, 결함: 0 } as Record<Grade, number>;
  for (const c of open) counts[c.grade] += 1;

  // 충돌 상세의 [3D로 보기]: 충돌이 걸린 날짜로 옮기고 3D 탭에서 그 작업을 고른다
  const show3D = (taskId: string, r: ConflictRecord) => {
    const day = r.conflict.window_start.slice(0, 10);
    if (day !== date) setDate(day);
    setSelectedTask(taskId);
    setTab("scene3d");
  };

  return (
    <div className="grid gap-4">
      <section className="flex flex-wrap items-center gap-4 rounded-lg bg-white p-3 text-sm shadow-sm">
        <label className="flex items-center gap-2">
          날짜
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="rounded border border-stone-300 px-2 py-1"
          />
        </label>
        <span>업체 {contractors.size}곳</span>
        <span>작업 {todays.length}건</span>
        <span className="text-stone-500">겹침 후보(전체 공정) {overlaps.length}쌍</span>
        <span className="ml-auto flex items-center gap-2">
          충돌 {open.length}건
          {(["금지", "조건부", "결함"] as Grade[]).map(
            (g) =>
              counts[g] > 0 && (
                <span key={g} className="flex items-center gap-1">
                  <GradeBadge grade={g} />
                  <span className="text-xs text-stone-600">{counts[g]}</span>
                </span>
              ),
          )}
        </span>
      </section>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="board">현황판</TabsTrigger>
          <TabsTrigger value="approval">
            승인 {pendingPlans.length > 0 && <span className="ml-1 rounded bg-amber-500 px-1.5 text-[10px] text-white">{pendingPlans.length}</span>}
          </TabsTrigger>
          <TabsTrigger value="scene3d">3D·충돌</TabsTrigger>
          <TabsTrigger value="conflicts">충돌 목록 {open.length > 0 && <span className="ml-1 rounded bg-red-600 px-1.5 text-[10px] text-white">{open.length}</span>}</TabsTrigger>
          <TabsTrigger value="restrictions">출입 제한 {blockedZones > 0 && <span className="ml-1 rounded bg-red-600 px-1.5 text-[10px] text-white">{blockedZones}</span>}</TabsTrigger>
          <TabsTrigger value="sops">표준서</TabsTrigger>
          <TabsTrigger value="tbm">TBM 확인</TabsTrigger>
          <TabsTrigger value="history">이력</TabsTrigger>
        </TabsList>

        <TabsContent value="board" className="grid gap-4">
          {/* 시안 상황판(#board) 레이아웃을 서버 데이터로: 숫자 띠 · 30분 칸 시간표 · 위험 시간대 띠 · 조치 카드 · 충돌 상세 */}
          <BoardView
            role={{ kind: "prime" }}
            date={date}
            setDate={setDate}
            zones={zones}
            tasks={tasks}
            conflicts={conflicts}
            plans={plans}
            onAdjusted={onAdjusted}
            onShared={onReload}
            onShow3D={show3D}
          />

          <section className="rounded-lg bg-white p-3 shadow-sm">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="font-semibold">위험 시간대 공지 (F9) — {date}</h3>
              <span className="text-xs text-stone-500">판정 결과를 구역·시간대별로 모은 것 (가중치는 팀 설정값). 간트의 옅은 띠가 이 시간대입니다</span>
              {riskWindows.length > 0 && (
                <button type="button" onClick={polishNotices} disabled={polishing} className="ml-auto rounded border border-stone-300 px-2 py-1 text-xs hover:bg-stone-50 disabled:opacity-40">
                  {polishing ? "다듬는 중…" : "공지 문장 다듬기 (LLM)"}
                </button>
              )}
            </div>
            <RiskWindowList windows={riskWindows} zones={zones} emptyText="이 날짜에는 위험 시간대가 없습니다." />
          </section>

          {/* 시간표 아래: 오늘 금지 판정으로 막힌 구역 (3D 안전띠·출입 금지 표지와 같은 자료). 작은 고로 3D는 scene3d 탭과 겹쳐서 뺐다 */}
          <section className="rounded-lg bg-white p-3 shadow-sm">
            <h3 className="mb-2 font-semibold">오늘 출입 제한 구역</h3>
            <RestrictionPanel
              restrictions={restrictions}
              tasks={tasks}
              zones={zones}
              date={date}
              onShow3D={(taskId) => {
                setSelectedTask(taskId);
                setTab("scene3d");
              }}
            />
          </section>
        </TabsContent>

        {/* scene3d(/scene3d/index.html, three.js)를 iframe으로 — 전체 작업과 서버 판정을 넘기면 위치별 목록·3D·조치 카드가 그려짐 */}
        <TabsContent
          value="scene3d"
          className="h-[calc(100vh-180px)] min-h-[560px] overflow-hidden rounded-lg border border-stone-200"
        >
          <Scene3DTab date={date} tasks={approvedTasks} conflicts={open} restrictions={restrictions} role={{ kind: "prime" }} selectTaskId={selectedTask} />
        </TabsContent>

        <TabsContent value="approval">
          <ApprovalPanel
            plans={plans}
            tasks={tasks}
            zones={zones}
            onDecided={onReload}
            onShow3D={(taskId, day) => {
              if (day !== date) setDate(day);
              setSelectedTask(taskId);
              setTab("scene3d");
            }}
            onShowConflict={() => setTab("conflicts")}
          />
        </TabsContent>

        <TabsContent value="restrictions">
          <RestrictionPanel
            restrictions={restrictions}
            tasks={tasks}
            zones={zones}
            date={date}
            onShow3D={(taskId) => {
              setSelectedTask(taskId);
              setTab("scene3d");
            }}
          />
        </TabsContent>

        <TabsContent value="conflicts" className="rounded-lg bg-white p-4 shadow-sm">
          <h3 className="mb-2 font-semibold">판정된 충돌 (규칙 ID · 법 조문 · 원문 근거 · 조정안)</h3>
          <ConflictFilter
            state={filter.state}
            onChange={filter.setState}
            contractors={allContractors}
            date={date}
            total={conflicts.length}
            shown={filter.filtered.length}
            latestOn={filter.latestOn}
            latestPlanLabel={latestPlan ? `#${latestPlan.id} ${latestPlan.contractor}` : null}
          />
          <label className="mb-2 flex items-center gap-1 text-xs text-stone-600">
            <input type="checkbox" checked={groupRules} onChange={(e) => setGroupRules(e.target.checked)} /> 규칙별로 묶어 보기
          </label>
          {unshared.length > 0 && (
            <div className="mb-2 flex flex-wrap items-center gap-2 rounded bg-brand-soft p-2 text-xs">
              <span>
                보이는 충돌 중 협력사 공유 전 <b>{unshared.length}</b>건
              </span>
              <input value={person} onChange={(e) => setPerson(e.target.value)} placeholder="확인한 책임자 (필수)" className="rounded border border-stone-300 bg-white px-2 py-1" />
              <button type="button" onClick={shareAll} disabled={sharing} className="rounded bg-brand px-2 py-1 font-medium text-white disabled:opacity-40">
                {sharing ? "공유 중…" : `${unshared.length}건 협력사에 공유`}
              </button>
              <span className="text-stone-500">각 협력사에는 자기 작업과 겹친 내용·인계 조건만 내려갑니다</span>
              {shareError && <span className="text-red-700">{shareError}</span>}
            </div>
          )}
          <ConflictList
            records={filter.filtered}
            tasks={tasks}
            role={{ kind: "prime" }}
            onShow3D={show3D}
            onAdjusted={onAdjusted}
            onShared={onReload}
            groupByRule={groupRules}
            emptyText={filter.latestOn ? "최근 제출이 새로 만든 충돌이 없습니다. 위 체크를 끄면 전체 충돌이 보입니다." : "아직 판정된 충돌이 없습니다. 협력사 화면에서 계획서를 올려 제출하면 그 순간 판정합니다."}
          />
        </TabsContent>

        <TabsContent value="sops" className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <div className="inline-flex rounded-lg bg-stone-200/70 p-[3px] text-xs">
              {(["matches", "library"] as const).map((v) => (
                <button key={v} type="button" onClick={() => setSopView(v)} className={`rounded-md px-3 py-1 font-medium ${sopView === v ? "bg-white shadow-sm" : "text-stone-600"}`}>
                  {v === "matches" ? `제출 계획서 매칭 ${sopMatches.length}` : `표준서 목록 ${sops.length}`}
                </button>
              ))}
            </div>
            <span className="text-xs text-stone-500">
              {sopView === "matches" ? "제출된 계획서의 작업마다 매칭된 표준서와 필수 단계 기재 여부 (F8). 주 표준서의 핵심 단계가 빠지면 결함" : "원청 작업표준서: 공통(유형별) 4종 + 작업별(P01~P37). 보라색 단계가 빠지면 결함"}
            </span>
          </div>
          {sopView === "matches" ? (
            <div className="rounded-lg bg-white p-4 shadow-sm">
              <SopMatchPanel matches={sopMatches} tasks={tasks} emptyText="제출된 계획서가 없습니다. 협력사가 계획서를 제출하면 작업별 표준서 매칭이 여기에 나옵니다." />
            </div>
          ) : (
            <SopLibrary sops={sops} tasks={tasks} />
          )}
        </TabsContent>

        <TabsContent value="tbm">
          <TbmView
            role={{ kind: "prime" }}
            contractors={allContractors.filter((c) => c.startsWith("가상-"))}
            defaultContractor={latestPlan?.contractor}
            defaultDate={date}
          />
        </TabsContent>

        <TabsContent value="history">
          <HistoryView plans={plans} tasks={tasks} onAdjusted={onAdjusted} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
