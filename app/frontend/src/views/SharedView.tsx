// 협력사 화면 "원청 공유·공지": 원청이 확인해 내려보낸 충돌(F5)과 내 작업이 걸린 위험 시간대 공지(F9)
// 서버가 이 협력사 범위로 거른다 — 인접 위치 작업, 위험 요소, 작업 인계 조건만 오고 상대 업체의 계획서 원문은 오지 않는다
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { GradeBadge, TypeBadge } from "@/components/ConflictBadge";
import { RiskWindowList } from "@/components/RiskWindowList";
import { HAZARD_LABEL, fmtDateTime, fmtRange } from "@/lib/format";
import type { RiskWindow, SharedItem, Task, Zone } from "@/types";

interface Props {
  contractor: string;
  zones: Zone[];
  tasks: Task[];
  conflictsKey: string; // 판정·공유가 바뀌면 다시 부르게 (App 이 다시 불러온 충돌 목록에서 만든다)
}

export function SharedView({ contractor, zones, tasks, conflictsKey }: Props) {
  const [items, setItems] = useState<SharedItem[]>([]);
  const [windows, setWindows] = useState<RiskWindow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const zoneName = (id: string) => zones.find((z) => z.id === id)?.name ?? id;
  const taskName = (id: string) => tasks.find((t) => t.id === id)?.name ?? id;

  useEffect(() => {
    Promise.all([api.shares(contractor), api.riskWindows({ contractor })])
      .then(([s, w]) => {
        setItems(s);
        setWindows(w);
        setError(null);
      })
      .catch((e) => setError((e as Error).message));
  }, [contractor, conflictsKey]);

  return (
    <div className="grid gap-4">
      {error && <p className="rounded bg-red-50 p-2 text-sm text-red-700">{error}</p>}

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-2 font-semibold">
          원청이 공유한 충돌 {items.length}건 <span className="text-xs font-normal text-stone-500">— 내 작업과 겹친 내용과 작업 인계 조건만</span>
        </h3>
        {items.length === 0 ? (
          <p className="text-sm text-stone-500">아직 원청이 공유한 충돌이 없습니다. 원청이 확인해 공유하거나 조정을 적용하면 여기에 나옵니다.</p>
        ) : (
          <ul className="grid gap-2 text-xs">
            {items.map((i) => (
              <li key={i.conflict_id} className="rounded border border-stone-200 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <GradeBadge grade={i.grade} />
                  <TypeBadge type={i.type} />
                  <b>{i.my_task_ids.map((id) => `${id} ${taskName(id)}`).join(", ")}</b>
                  <span className="text-stone-500">{fmtRange(i.window_start, i.window_end)}</span>
                  {i.status === "adjusted" && <span className="rounded bg-ok-soft px-1.5 py-0.5 text-ok">조정 적용됨</span>}
                  {i.status === "resolved" && <span className="rounded bg-stone-100 px-1.5 py-0.5 text-stone-600">해소</span>}
                  <span className="ml-auto text-stone-400">
                    {i.shared_by} · {fmtDateTime(i.shared_at)}
                  </span>
                </div>
                <div className="mt-2 grid gap-1 sm:grid-cols-[6rem_1fr]">
                  <span className="text-stone-500">이유</span>
                  <span>{i.reason}</span>
                  {i.handover && (
                    <>
                      <span className="text-stone-500">작업 인계 조건</span>
                      <b className="text-brand">{i.handover}</b>
                    </>
                  )}
                  {i.adjustment && (
                    <>
                      <span className="text-stone-500">적용된 조정</span>
                      <span>
                        {i.adjustment.task_id} {fmtRange(i.adjustment.original_start, i.adjustment.original_end)} →{" "}
                        <b>{fmtRange(i.adjustment.new_start, i.adjustment.new_end)}</b> ({i.adjustment.decided_by})
                      </span>
                    </>
                  )}
                  <span className="text-stone-500">인접 작업</span>
                  <span className="flex flex-wrap gap-1.5">
                    {i.adjacent_tasks.length === 0
                      ? "—"
                      : i.adjacent_tasks.map((t) => (
                          <span key={t.id} className="rounded bg-stone-50 px-2 py-0.5 ring-1 ring-stone-200">
                            <b>{t.id}</b> {t.contractor} · {t.name} · {zoneName(t.zone_id)} · {fmtRange(t.start, t.end)}
                            {t.hazards.length > 0 && ` · ${t.hazards.map((h) => HAZARD_LABEL[h]).join("·")}`}
                          </span>
                        ))}
                  </span>
                  <span className="text-stone-500">규칙 · 근거</span>
                  <span>
                    <b>{i.rule_id}</b> · {i.legal_basis}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-2 font-semibold">
          위험 시간대 공지 (F9) <span className="text-xs font-normal text-stone-500">— 공유된 내 충돌만 모은 것. TBM에서 작업자에게 전달하세요</span>
        </h3>
        <RiskWindowList windows={windows} zones={zones} emptyText="공유된 위험 시간대가 없습니다." />
      </section>
    </div>
  );
}
