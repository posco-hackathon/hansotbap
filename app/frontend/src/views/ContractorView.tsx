// 협력사 화면: 계획서 올리기·제출(F1→F8→F2), 내 작업, 나와 겹친 충돌, 원청 공유·공지(F5·F9), 매칭된 표준서, 내 작업 3D, TBM 확인(F7)
// 권한: 작업·충돌·표준서 매칭·공유·위험 시간대는 서버가 contractor 로 거른 것만 받는다 (자기 작업 + 공유된 충돌의 상대 작업)
import { useEffect, useMemo, useState } from "react";
import { ConflictList } from "@/components/ConflictList";
import { PlanUpload } from "@/components/PlanUpload";
import { SopMatchPanel } from "@/components/SopMatchPanel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { HAZARD_LABEL, fmtRange } from "@/lib/format";
import { defaultBoardDate } from "@/lib/siteDate";
import { groupByZone, restrictionsForContractor, restrictionsOn, type ZoneRestriction } from "@/lib/restrictions";
import type { ConflictRecord, PlanRecord, PlanSubmitResult, SopInfo, SopMatch, Task, Zone } from "@/types";
import { PLAN_STATUS_LABEL, PlanStatusChip } from "@/views/ApprovalPanel";
import { HistoryView } from "@/views/HistoryView";
import { RestrictionPanel } from "@/views/RestrictionPanel";
import { Scene3DTab } from "@/views/Scene3DTab";
import { SharedView } from "@/views/SharedView";
import { SopLibrary } from "@/views/SopLibrary";
import { TbmView } from "@/views/TbmView";
import { BoardView } from "@/views/BoardView";

interface Props {
  contractor: string;
  zones: Zone[];
  tasks: Task[];
  conflicts: ConflictRecord[]; // 서버가 이 협력사 작업이 걸린 것만 준다
  sopMatches: SopMatch[];
  sops: SopInfo[]; // 원청 작업표준서 목록 — 내 작업에 적용되는 것을 먼저 보여 준다
  plans: PlanRecord[]; // 내 제출 이력 (서버가 걸러 준다)
  restrictions: ZoneRestriction[]; // 금지 판정 → 출입 제한 (내 작업이 걸린 것만 다시 거른다)
  onSubmitted: (result: PlanSubmitResult) => void;
  onDateChange?: (date: string) => void; // 지금 보는 날짜 (AI 챗봇이 '오늘' 기준으로 쓴다)
}

export function ContractorView({ contractor, zones, tasks, conflicts, sopMatches, sops, plans, restrictions, onSubmitted, onDateChange }: Props) {
  const mine = tasks.filter((t) => t.contractor === contractor);
  const myRestrictions = useMemo(() => restrictionsForContractor(restrictions, tasks, contractor), [restrictions, tasks, contractor]);
  // 기본 날짜는 오늘(공사 기간 밖이면 가장 가까운 공사일). 계획서를 낸 직후 한 번만 그 제출이 낸 충돌 날로 간다.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 처음 한 번만 정한다 (제출 표식을 소비하므로 다시 계산하면 안 된다)
  const defaultDate = useMemo(() => defaultBoardDate({ plans, conflicts, tasks }), []);
  const [dateOverride, setDateOverride] = useState<string | null>(null);
  const date = dateOverride ?? defaultDate;
  const setDate = setDateOverride;
  useEffect(() => onDateChange?.(date), [date, onDateChange]);
  const zoneName = (id: string) => zones.find((z) => z.id === id)?.name ?? id;
  const [tab, setTab] = useState("board");
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const blockedZones = useMemo(() => groupByZone(restrictionsOn(myRestrictions, date), zones).length, [myRestrictions, date, zones]);
  // 공유·조정이 바뀌면 "원청 공유·공지"를 다시 부른다 (App 이 다시 불러온 충돌 목록이 바뀐 것으로 안다)
  const conflictsKey = conflicts.map((r) => `${r.conflict.id}:${r.status}:${r.shared_at ?? ""}`).join("|");

  // 내 최근 제출 계획서의 승인 상태 — 승인 대기면 3D·현황에 아직 "확정"으로 들어가지 않는다
  const latestPlan = [...plans].sort((a, b) => b.id - a.id)[0] ?? null;

  return (
    <div className="grid gap-4">
      <PlanUpload contractor={contractor} zones={zones} onSubmitted={onSubmitted} />
      {latestPlan && (
        <div className={`flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm ${latestPlan.status === "rejected" ? "border-red-300 bg-red-50" : latestPlan.status === "approved" ? "border-green-300 bg-green-50" : "border-amber-300 bg-amber-50"}`}>
          <PlanStatusChip status={latestPlan.status} />
          <span>
            최근 제출 <b>{latestPlan.file}</b> v{latestPlan.version} — {PLAN_STATUS_LABEL[latestPlan.status]}
            {latestPlan.status === "pending" && ": 원청이 겹침·출입 금지 구역을 확인한 뒤 승인하면 3D·현황에 확정으로 들어갑니다"}
            {latestPlan.status === "approved" && `: ${latestPlan.decided_by ?? "원청"} 승인 (${latestPlan.decided_at ?? ""})`}
            {latestPlan.status === "rejected" && `: ${latestPlan.decided_by ?? "원청"} 반려 — 사유를 반영해 수정 계획서를 다시 올려 주세요`}
          </span>
          {latestPlan.decision_note && <span className="w-full text-xs text-stone-600">사유·메모: {latestPlan.decision_note}</span>}
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="board">상황판</TabsTrigger>
          <TabsTrigger value="mine">내 작업 {mine.length}</TabsTrigger>
          <TabsTrigger value="conflicts">
            나와 겹친 충돌 {conflicts.length > 0 && <span className="ml-1 rounded bg-red-600 px-1.5 text-[10px] text-white">{conflicts.length}</span>}
          </TabsTrigger>
          <TabsTrigger value="shared">원청 공유·공지</TabsTrigger>
          <TabsTrigger value="restrictions">
            작업 금지 구역 {blockedZones > 0 && <span className="ml-1 rounded bg-red-600 px-1.5 text-[10px] text-white">{blockedZones}</span>}
          </TabsTrigger>
          <TabsTrigger value="sops">표준서</TabsTrigger>
          <TabsTrigger value="scene3d">내 작업 3D</TabsTrigger>
          <TabsTrigger value="tbm">TBM 확인</TabsTrigger>
          <TabsTrigger value="history">내 이력</TabsTrigger>
        </TabsList>

        <TabsContent value="board">
          <BoardView
            role={{ kind: "contractor", contractor }}
            date={date}
            setDate={setDate}
            zones={zones}
            tasks={tasks}
            conflicts={conflicts}
            plans={plans}
            onShow3D={(taskId) => {
              setSelectedTask(taskId);
              setTab("scene3d");
            }}
          />
        </TabsContent>

        <TabsContent value="shared">
          <SharedView contractor={contractor} zones={zones} tasks={tasks} conflictsKey={conflictsKey} />
        </TabsContent>

        <TabsContent value="tbm">
          <TbmView role={{ kind: "contractor", contractor }} contractors={[contractor]} defaultDate={date} />
        </TabsContent>

        <TabsContent value="mine" className="rounded-lg bg-white p-4 text-sm shadow-sm">
          <h2 className="mb-2 font-semibold">{contractor} — 내 작업 {mine.length}건</h2>
          {mine.length === 0 ? (
            <p className="text-stone-500">계획서를 올려 제출하면 이 협력사의 작업이 여기에 나옵니다.</p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="bg-stone-50 text-stone-600">
                <tr>
                  <th className="p-2">ID</th>
                  <th className="p-2">작업</th>
                  <th className="p-2">구역</th>
                  <th className="p-2">기간</th>
                  <th className="p-2">투입 인원</th>
                  <th className="p-2">위험작업</th>
                  <th className="p-2">선행</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {mine.map((t) => (
                  <tr key={t.id}>
                    <td className="p-2 font-semibold">{t.id}</td>
                    <td className="p-2">{t.name}</td>
                    <td className="p-2">{zoneName(t.zone_id)}</td>
                    <td className="whitespace-nowrap p-2">{fmtRange(t.start, t.end)}</td>
                    <td className="p-2">{t.crew != null ? `${t.crew}명` : "—"}</td>
                    <td className="p-2">{t.hazards.map((h) => HAZARD_LABEL[h]).join(", ") || "—"}</td>
                    <td className="p-2">{t.predecessors.join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </TabsContent>

        <TabsContent value="conflicts" className="rounded-lg bg-white p-4 shadow-sm">
          <h3 className="mb-2 font-semibold">나와 겹친 충돌 — 내 작업이 걸린 것만 (서버에서 거름)</h3>
          <ConflictList records={conflicts} tasks={tasks} role={{ kind: "contractor", contractor }} emptyText="원청이 공유한 충돌이 없습니다. 원청 확인 전인 충돌은 여기에 나오지 않습니다." />
        </TabsContent>

        <TabsContent value="restrictions" className="grid gap-2">
          <label className="flex items-center gap-2 text-sm">
            날짜
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="rounded border border-stone-300 px-2 py-1" />
            <span className="text-xs text-stone-500">내 작업이 걸린 금지 판정만 — 그 기간에 그 구역에서는 작업하지 마세요. 3D에도 출입 금지 표지가 섭니다</span>
          </label>
          <RestrictionPanel
            restrictions={myRestrictions}
            tasks={tasks}
            zones={zones}
            date={date}
            contractor={contractor}
            onShow3D={(taskId) => {
              setSelectedTask(taskId);
              setTab("scene3d");
            }}
          />
        </TabsContent>

        <TabsContent value="sops" className="grid gap-3">
          <div className="rounded-lg bg-white p-4 shadow-sm">
            <h3 className="mb-2 font-semibold">제출 계획서의 표준서 매칭 (F8) — 빠진 핵심 단계를 보완해 재제출하면 결함이 해소됩니다</h3>
            <SopMatchPanel matches={sopMatches} tasks={tasks} emptyText="제출한 계획서가 없습니다. 아래 '내 작업 표준서'를 보고 절차를 적어 제출하세요." />
          </div>
          <h3 className="font-semibold">내 작업 표준서 — 계획서 절차에 보라색 핵심 단계가 들어가야 합니다</h3>
          <SopLibrary sops={sops} tasks={tasks} contractor={contractor} />
        </TabsContent>

        <TabsContent value="scene3d" className="grid gap-2">
          <label className="flex items-center gap-2 text-sm">
            날짜
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="rounded border border-stone-300 px-2 py-1" />
          </label>
          <div className="h-[calc(100vh-260px)] min-h-[520px] overflow-hidden rounded-lg border border-stone-200">
            <Scene3DTab
              date={date}
              tasks={tasks}
              conflicts={conflicts.map((r) => r.conflict)}
              restrictions={myRestrictions}
              role={{ kind: "contractor", contractor }}
              selectTaskId={selectedTask}
            />
          </div>
        </TabsContent>

        <TabsContent value="history">
          <HistoryView plans={plans} tasks={tasks} contractor={contractor} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
