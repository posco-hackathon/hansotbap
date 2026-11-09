// 이력(F5): 제64조 이행 기록(제출·판정·공유·조정·TBM·현장 기록, 엑셀 내보내기) · 계획서 제출 이력 · 조정 기록(F4, 원청은 되돌리기) · 충돌 상태
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { GradeBadge, TypeBadge } from "@/components/ConflictBadge";
import { fmtDateTime, fmtRange } from "@/lib/format";
import { usePerson } from "@/lib/person";
import type { AdjustmentRecord, AdjustmentResult, ConflictRecord, HistoryEvent, HistoryEventKind, PlanRecord, Task } from "@/types";

interface Props {
  plans: PlanRecord[];
  tasks: Task[];
  contractor?: string; // 협력사로 보면 서버가 자기 것만 준다
  onAdjusted?: (result: AdjustmentResult) => void; // 원청이 조정을 되돌린 뒤 (있으면 [되돌리기]를 보여 준다)
}

const ADJ_STATUS: Record<AdjustmentRecord["status"], string> = { active: "적용 중", reverted: "되돌림", stale: "무효(재제출)" };
const CF_STATUS: Record<ConflictRecord["status"], string> = { open: "열림", adjusted: "조정 적용", resolved: "해소" };
// 서버 엑셀 내보내기(api/history.py)와 같은 이름
const KIND_LABEL: Record<HistoryEventKind, string> = {
  plan_submitted: "계획서 제출",
  conflict_judged: "충돌 판정",
  conflict_shared: "협력사 공유",
  adjustment_replaced: "조정 대체",
  adjustment_applied: "조정 적용",
  conflict_resolved: "충돌 해소",
  adjustment_reverted: "조정 되돌림",
  adjustment_stale: "조정 무효",
  tbm_checked: "TBM 전달 확인",
  field_record: "현장 기록",
};

export function HistoryView({ plans, tasks, contractor, onAdjusted }: Props) {
  const [adjustments, setAdjustments] = useState<AdjustmentRecord[]>([]);
  const [conflicts, setConflicts] = useState<ConflictRecord[]>([]);
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [showJudged, setShowJudged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [person, setPerson] = usePerson();
  const [reverting, setReverting] = useState<string | null>(null);
  const taskOf = (id: string) => tasks.find((t) => t.id === id);

  useEffect(() => {
    Promise.all([api.adjustments({ contractor }), api.conflicts({ contractor, includeResolved: true }), api.history(contractor)])
      .then(([a, c, h]) => {
        setAdjustments(a);
        setConflicts(c);
        setEvents(h);
        setError(null);
      })
      .catch((e) => setError((e as Error).message));
  }, [contractor]);

  // 충돌 판정 줄은 공정 전체라 수가 많다 → 기본은 숨기고 고르면 보인다 (엑셀에는 모두 들어간다)
  const shownEvents = [...events].filter((e) => showJudged || e.kind !== "conflict_judged").reverse();

  const revert = async (id: string) => {
    if (!person.trim()) {
      setError("되돌린 책임자 이름을 적어 주세요 (이행 기록에 남습니다)");
      return;
    }
    setReverting(id);
    setError(null);
    try {
      onAdjusted?.(await api.revertAdjustment(id, person.trim()));
    } catch (e) {
      setError((e as Error).message);
      setReverting(null);
    }
  };

  const counts = { open: 0, adjusted: 0, resolved: 0 } as Record<ConflictRecord["status"], number>;
  for (const c of conflicts) counts[c.status] += 1;
  const sortedPlans = [...plans].sort((a, b) => b.id - a.id);
  const sortedConflicts = [...conflicts].sort((a, b) => b.judged_at.localeCompare(a.judged_at));

  const csv = () => {
    const rows = [
      ["종류", "시각", "누가", "내용"],
      ...sortedPlans.map((p) => ["제출", p.submitted_at, p.submitted_by ?? p.contractor, `${p.contractor} ${p.file} v${p.version} 작업 ${p.task_count}건`]),
      ...adjustments.map((r) => ["조정", r.adjustment.decided_at, r.adjustment.decided_by, `${r.adjustment.task_id} ${fmtRange(r.adjustment.original_start, r.adjustment.original_end)} → ${fmtRange(r.adjustment.new_start, r.adjustment.new_end)} (${r.adjustment.conflict_id}, ${ADJ_STATUS[r.status]})`]),
      ...sortedConflicts.map((r) => ["충돌", r.judged_at, "규칙 판정", `${r.conflict.id} ${r.conflict.grade} ${CF_STATUS[r.status]}`]),
    ];
    const text = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    void navigator.clipboard?.writeText(text);
  };

  return (
    <div className="grid gap-4">
      {error && <p className="rounded bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      <div className="flex flex-wrap items-center gap-4 rounded-lg bg-white p-3 text-sm shadow-sm">
        <span>
          제출 <b>{plans.length}</b>건
        </span>
        <span>
          조정 <b>{adjustments.length}</b>건
        </span>
        <span>
          충돌 열림 <b>{counts.open}</b> · 조정 적용 <b>{counts.adjusted}</b> · 해소 <b>{counts.resolved}</b>
        </span>
        <a
          href={api.historyExportUrl(contractor)}
          className="ml-auto rounded bg-stone-800 px-2 py-1 text-xs font-medium text-white hover:bg-stone-700"
          title="제64조 이행 기록 엑셀 (합성 데이터 표시, 보는 사람의 권한 범위만)"
        >
          엑셀 내보내기
        </a>
        <button type="button" onClick={csv} className="rounded border border-stone-300 px-2 py-1 text-xs hover:bg-stone-50">
          CSV 복사
        </button>
      </div>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <h3 className="font-semibold">이행 기록 (산안법 제64조) — 제출·공유·조정·TBM·현장 기록, 최근순</h3>
          <label className="flex items-center gap-1 text-xs text-stone-600">
            <input type="checkbox" checked={showJudged} onChange={(e) => setShowJudged(e.target.checked)} />
            충돌 판정 줄도 보기
          </label>
        </div>
        {shownEvents.length === 0 ? (
          <p className="text-sm text-stone-500">아직 기록이 없습니다.</p>
        ) : (
          <div className="max-h-[50vh] overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-stone-50 text-stone-600">
                <tr>
                  <th className="p-2">시각</th>
                  <th className="p-2">구분</th>
                  <th className="p-2">관련 업체</th>
                  <th className="p-2">책임자</th>
                  <th className="p-2">내용</th>
                  <th className="p-2">규칙</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {shownEvents.map((e, i) => (
                  <tr key={`${e.target_id}-${e.kind}-${i}`}>
                    <td className="whitespace-nowrap p-2">{fmtDateTime(e.at)}</td>
                    <td className="whitespace-nowrap p-2">{e.label ?? KIND_LABEL[e.kind]}</td>
                    <td className="p-2">{e.contractors.join(", ") || "—"}</td>
                    <td className="p-2">{e.actor ?? "시스템"}</td>
                    <td className="p-2">{e.detail}</td>
                    <td className="p-2" title={e.legal_basis ?? undefined}>
                      {e.rule_id ?? (e.legal_basis ? "제64조" : "")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-2 font-semibold">계획서 제출 이력</h3>
        {sortedPlans.length === 0 ? (
          <p className="text-sm text-stone-500">아직 제출된 계획서가 없습니다.</p>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="bg-stone-50 text-stone-600">
              <tr>
                <th className="p-2">#</th>
                <th className="p-2">제출 시각</th>
                <th className="p-2">협력사</th>
                <th className="p-2">파일</th>
                <th className="p-2">버전</th>
                <th className="p-2">작업</th>
                <th className="p-2">제출자</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {sortedPlans.map((p) => (
                <tr key={p.id}>
                  <td className="p-2 font-mono">{p.id}</td>
                  <td className="p-2 whitespace-nowrap">{fmtDateTime(p.submitted_at)}</td>
                  <td className="p-2">{p.contractor}</td>
                  <td className="p-2">{p.file}</td>
                  <td className="p-2">v{p.version}</td>
                  <td className="p-2">{p.task_count}건</td>
                  <td className="p-2">{p.submitted_by ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h3 className="font-semibold">조정 기록 (F4) — 적용한 책임자가 남는다</h3>
          {onAdjusted && (
            <input
              value={person}
              onChange={(e) => setPerson(e.target.value)}
              placeholder="되돌린 책임자 (되돌릴 때 필수)"
              className="rounded border border-stone-300 px-2 py-1 text-xs"
            />
          )}
        </div>
        {adjustments.length === 0 ? (
          <p className="text-sm text-stone-500">적용한 조정이 없습니다.</p>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="bg-stone-50 text-stone-600">
              <tr>
                <th className="p-2">시각</th>
                <th className="p-2">작업</th>
                <th className="p-2">이동</th>
                <th className="p-2">푼 충돌</th>
                <th className="p-2">책임자</th>
                <th className="p-2">상태</th>
                {onAdjusted && <th className="p-2" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {adjustments.map((r) => {
                const a = r.adjustment;
                const t = taskOf(a.task_id);
                return (
                  <tr key={a.id}>
                    <td className="p-2 whitespace-nowrap">{fmtDateTime(a.decided_at)}</td>
                    <td className="p-2">
                      <b>{a.task_id}</b> {t ? `${t.contractor} · ${t.name}` : ""}
                    </td>
                    <td className="p-2 whitespace-nowrap">
                      {fmtRange(a.original_start, a.original_end)} → <b>{fmtRange(a.new_start, a.new_end)}</b>
                    </td>
                    <td className="p-2 font-mono">{a.conflict_id}</td>
                    <td className="p-2">{a.decided_by}</td>
                    <td className="p-2">{ADJ_STATUS[r.status]}</td>
                    {onAdjusted && (
                      <td className="p-2">
                        {r.status === "active" && (
                          <button
                            type="button"
                            onClick={() => revert(a.id)}
                            disabled={reverting !== null}
                            className="rounded border border-red-300 px-2 py-0.5 text-red-700 hover:bg-red-50 disabled:opacity-40"
                            title="협력사 원본 일정으로 돌아가고 바로 재판정합니다"
                          >
                            {reverting === a.id ? "재판정 중…" : "되돌리기"}
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-2 font-semibold">충돌 판정 기록 (해소된 것 포함)</h3>
        <ul className="max-h-[50vh] divide-y divide-stone-100 overflow-y-auto text-xs">
          {sortedConflicts.map((r) => (
            <li key={r.conflict.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <GradeBadge grade={r.conflict.grade} />
              <TypeBadge type={r.conflict.type} />
              <span className="font-mono">{r.conflict.id}</span>
              <span className="text-stone-600">{r.conflict.task_ids.map((id) => taskOf(id)?.name ?? id).join(" × ")}</span>
              <span className={`ml-auto rounded px-1.5 py-0.5 ${r.status === "resolved" ? "bg-stone-100 text-stone-600" : r.status === "adjusted" ? "bg-ok-soft text-ok" : "bg-red-50 text-red-700"}`}>
                {CF_STATUS[r.status]}
              </span>
              <span className="text-stone-400">{fmtDateTime(r.judged_at)}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
