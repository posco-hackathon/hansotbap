// F3 ① 메인: 시간표형 간트 (07~19시, 30분 칸, 구역 위→아래, 지금 선, 충돌 작업은 등급 색, F9 위험 시간대 띠)
// 담당: 프론트. TODO: 아래 조치 카드
import { useEffect, useRef } from "react";
import { DataSet, Timeline, type DataItem } from "vis-timeline/standalone";
import "vis-timeline/styles/vis-timeline-graph2d.min.css";
import { worstGrade } from "@/lib/format";
import type { Conflict, Grade, RiskWindow, Task, Zone } from "@/types";

interface Props {
  date: string; // YYYY-MM-DD
  zones: Zone[];
  tasks: Task[];
  conflicts?: Conflict[]; // 서버 판정. 작업이 걸린 충돌 중 가장 높은 등급으로 막대 색을 칠한다
  riskWindows?: RiskWindow[]; // F9 그날의 위험 시간대 (GET /api/risk-windows?on=) → 그 구역 줄에 배경 띠
  onSelectTask?: (taskId: string) => void;
}

const DAY_START = "07:00";
const DAY_END = "19:00";
const GRADE_CLASS: Record<Grade, string> = { 금지: "cf-prohibited", 조건부: "cf-conditional", 결함: "cf-defect" };
const RISK_CLASS: Record<Grade, string> = { 금지: "rw-prohibited", 조건부: "rw-conditional", 결함: "rw-defect" };

export function TimetableGantt({ date, zones, tasks, conflicts = [], riskWindows = [], onSelectTask }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const start = new Date(`${date}T${DAY_START}:00`);
    const end = new Date(`${date}T${DAY_END}:00`);

    const gradeOf = (taskId: string): Grade | undefined =>
      worstGrade(conflicts.filter((c) => c.task_ids.includes(taskId)).map((c) => c.grade));

    const groups = new DataSet(
      [...zones]
        .sort((a, b) => b.vertical_order - a.vertical_order)
        .map((z) => ({ id: z.id, content: z.name })),
    );
    const taskItems: DataItem[] = tasks
      .filter((t) => new Date(t.start) < end && new Date(t.end) > start)
      .map((t) => {
        const grade = gradeOf(t.id);
        return {
          id: t.id,
          group: t.zone_id,
          content: `${grade ? `<b>${grade}</b> ` : ""}${t.contractor} · ${t.name}`,
          start: t.start,
          end: t.end,
          title: `${t.id} ${t.name}${grade ? ` — 충돌 ${grade}` : ""}`,
          className: grade ? GRADE_CLASS[grade] : undefined,
        };
      });
    // 위험 시간대는 고를 수 없는 배경 띠로 (막대를 가리지 않게)
    const riskItems: DataItem[] = riskWindows
      .filter((w) => new Date(w.start) < end && new Date(w.end) > start)
      .map((w, i) => ({
        id: `rw-${i}`,
        group: w.zone_id,
        content: "",
        start: w.start,
        end: w.end,
        type: "background",
        className: RISK_CLASS[w.peak_grade],
        title: w.notice,
      }));
    const items = new DataSet([...taskItems, ...riskItems]);

    const timeline = new Timeline(ref.current, items, groups, {
      start,
      end,
      min: start,
      max: end,
      zoomable: false,
      moveable: false,
      stack: true,
      orientation: "top",
      showCurrentTime: true,
      timeAxis: { scale: "minute", step: 30 },
      format: { minorLabels: { minute: "HH:mm" } },
    });
    timeline.on("select", (props: { items: string[] }) => {
      if (props.items[0]) onSelectTask?.(props.items[0]);
    });
    return () => timeline.destroy();
  }, [date, zones, tasks, conflicts, riskWindows, onSelectTask]);

  return <div ref={ref} className="rounded-lg border border-stone-200 bg-white" />;
}
