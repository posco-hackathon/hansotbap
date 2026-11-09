// 이력(F5 바탕): 계획서 제출 이력 · 조정 기록(F4) · 충돌 상태(열림/조정/해소). 제64조 이행 기록의 바탕이 되는 표
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { GradeBadge, TypeBadge } from "@/components/ConflictBadge";
import { fmtDateTime, fmtRange } from "@/lib/format";
import type { AdjustmentRecord, ConflictRecord, PlanRecord, Task } from "@/types";

interface Props {
  plans: PlanRecord[];
  tasks: Task[];
  contractor?: string; // 협력사로 보면 서버가 자기 것만 준다
}

const ADJ_STATUS: Record<AdjustmentRecord["status"], string> = { active: "적용 중", reverted: "되돌림", stale: "무효(재제출)" };
const CF_STATUS: Record<ConflictRecord["status"], string> = { open: "열림", adjusted: "조정 적용", resolved: "해소" };

export function HistoryView({ plans, tasks, contractor }: Props) {
  const [adjustments, setAdjustments] = useState<AdjustmentRecord[]>([]);
  const [conflicts, setConflicts] = useState<ConflictRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null); // CSV 복사 결과 (3초 뒤 사라진다)
  const taskOf = (id: string) => tasks.find((t) => t.id === id);

  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(null), 3000);
    return () => window.clearTimeout(t);
  }, [copied]);

  useEffect(() => {
    Promise.all([api.adjustments({ contractor }), api.conflicts({ contractor, includeResolved: true })])
      .then(([a, c]) => {
        setAdjustments(a);
        setConflicts(c);
        setError(null);
      })
      .catch((e) => setError((e as Error).message));
  }, [contractor]);

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
    // 눌러도 아무 표시가 없으면 복사됐는지 알 수 없다. clipboard 는 http 원격 주소에서는 없을 수 있다
    if (!navigator.clipboard) {
      setCopied("이 주소에서는 클립보드를 쓸 수 없습니다 — 엑셀 내보내기를 쓰세요");
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => setCopied(`${rows.length - 1}줄 복사했습니다`),
      () => setCopied("복사하지 못했습니다 — 엑셀 내보내기를 쓰세요"),
    );
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
        <span className="ml-auto flex items-center gap-2">
          {copied && <span className="text-xs text-stone-500">{copied}</span>}
          <button type="button" onClick={csv} className="rounded border border-stone-300 px-2 py-1 text-xs hover:bg-stone-50">
            CSV 복사
          </button>
          {/* 서버가 같은 권한 범위로 만든 제64조 이행 기록 엑셀 (제출·판정·공유·조정·해소) */}
          <a href={api.historyExportUrl(contractor)} download className="rounded border border-stone-300 px-2 py-1 text-xs hover:bg-stone-50">
            엑셀 내보내기
          </a>
        </span>
      </div>

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
        <h3 className="mb-2 font-semibold">조정 기록 (F4) — 적용한 책임자가 남는다</h3>
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
