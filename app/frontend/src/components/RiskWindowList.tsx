// F9 위험 시간대 공지: 판정 결과를 구역·시간대별로 모은 것. 점수·등급은 서버 규칙(가중치는 팀 설정값), 공지 문장은 규칙 문장 또는 LLM이 다듬은 문장
import { GradeBadge } from "@/components/ConflictBadge";
import { fmtDate, fmtRange } from "@/lib/format";
import type { RiskWindow, Zone } from "@/types";

interface Props {
  windows: RiskWindow[];
  zones: Zone[];
  emptyText: string;
}

/** 하루 안이면 그 시각, 여러 날이 합쳐진 건은 "그 기간 매일 그 시각" (서버 RiskWindow 설명대로) */
function span(w: RiskWindow): string {
  if (w.start.slice(0, 10) === w.end.slice(0, 10)) return fmtRange(w.start, w.end);
  return `${fmtDate(w.start)}~${fmtDate(w.end)} 매일 ${w.start.slice(11, 16)}~${w.end.slice(11, 16)}`;
}

export function RiskWindowList({ windows, zones, emptyText }: Props) {
  if (windows.length === 0) return <p className="text-sm text-stone-500">{emptyText}</p>;
  const zoneName = (id: string) => zones.find((z) => z.id === id)?.name ?? id;
  const sorted = [...windows].sort((a, b) => b.score - a.score || a.start.localeCompare(b.start));
  return (
    <ul className="grid gap-2 text-xs">
      {sorted.map((w, i) => (
        <li key={`${w.zone_id}-${w.start}-${i}`} className="rounded border border-stone-200 bg-white p-2">
          <div className="flex flex-wrap items-center gap-2">
            <GradeBadge grade={w.peak_grade} />
            <b>{zoneName(w.zone_id)}</b>
            <span className="text-stone-600">{span(w)}</span>
            <span className="text-stone-500">점수 {w.score}</span>
            <span className="ml-auto text-stone-500">{w.contractors.join(", ")}</span>
          </div>
          <p className="mt-1 text-[13px] text-stone-800">{w.notice}</p>
          <div className="mt-1 text-stone-500">
            규칙 {w.rule_ids.join(", ")} · {[...new Set(w.legal_basis)].join(" / ")}
          </div>
        </li>
      ))}
    </ul>
  );
}
