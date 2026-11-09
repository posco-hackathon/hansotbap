// F3 ① 메인: 시간표형 간트 (07~19시, 30분 칸, 구역 위→아래, 지금 선, 충돌 작업은 등급 색)
// 담당: 프론트. TODO: 위험 시간대 띠(F9), 아래 조치 카드
import { useEffect, useRef } from "react";
import { DataSet, Timeline } from "vis-timeline/standalone";
import "vis-timeline/styles/vis-timeline-graph2d.min.css";
import { worstGrade } from "@/lib/format";
import type { Conflict, Grade, Task, Zone } from "@/types";

interface Props {
  date: string; // YYYY-MM-DD
  zones: Zone[];
  tasks: Task[];
  conflicts?: Conflict[]; // 서버 판정. 작업이 걸린 충돌 중 가장 높은 등급으로 막대 색을 칠한다
  onSelectTask?: (taskId: string) => void;
}

const DAY_START = "07:00";
const DAY_END = "19:00";
const GRADE_CLASS: Record<Grade, string> = { 금지: "cf-prohibited", 조건부: "cf-conditional", 결함: "cf-defect" };
const WEEKDAY = "일월화수목금토";

/** 간트 위쪽 머리글: '2027-01-21 (목)'. vis-timeline 이 넘기는 값은 moment 라 valueOf() 로 Date 를 만든다 */
function koreanDayLabel(date: Date): string {
  const d = new Date(date.valueOf());
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} (${WEEKDAY[d.getDay()]})`;
}

export function TimetableGantt({ date, zones, tasks, conflicts = [], onSelectTask }: Props) {
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
    const items = new DataSet(
      tasks
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
        }),
    );

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
      // vis-timeline 번들은 moment 로케일을 여러 개 싣는데, 마지막에 실린 우크라이나어가 전역 로케일이 되어
      // 날짜 머리글이 "чт 21 січня"처럼 나온다. 로케일은 en 으로 되돌리고 머리글은 직접 한국어로 쓴다
      locale: "en",
      format: { minorLabels: { minute: "HH:mm" }, majorLabels: koreanDayLabel },
    });
    timeline.on("select", (props: { items: string[] }) => {
      if (props.items[0]) onSelectTask?.(props.items[0]);
    });
    return () => timeline.destroy();
  }, [date, zones, tasks, conflicts, onSelectTask]);

  return <div ref={ref} className="rounded-lg border border-stone-200 bg-white" />;
}
