// F7 TBM 전달 확인: 그날 전달할 항목(서버가 공유된 조정·위험 시간대·원청 공지로 만든다) → 녹음 받아쓰기 또는 전사문 → 항목별 전달 여부
// 전달 여부는 LLM이 판단하고 서버 규칙이 다시 확인한다. 시스템은 작업을 승인·중지하지 않는다 — 빠진 항목을 보충 전달하라고 알릴 뿐이다
import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import { fmtDateTime } from "@/lib/format";
import { usePerson } from "@/lib/person";
import type { TbmCheckRecord, TbmChecklist, TbmItemKind, ViewerRole } from "@/types";

interface Props {
  role: ViewerRole;
  contractors: string[]; // 원청이 고를 수 있는 협력사
  defaultContractor?: string;
  defaultDate: string; // YYYY-MM-DD
}

const KIND_LABEL: Record<TbmItemKind, string> = { adjustment: "조정", risk_window: "위험 시간대", notice: "원청 공지" };
const KIND_CLASS: Record<TbmItemKind, string> = {
  adjustment: "bg-ok-soft text-ok",
  risk_window: "bg-orange-100 text-orange-800",
  notice: "bg-brand-soft text-brand",
};
const AUDIO_ACCEPT = ".wav,.m4a,.mp3,.webm,.ogg";

export function TbmView({ role, contractors, defaultContractor, defaultDate }: Props) {
  const isPrime = role.kind === "prime";
  const viewer = role.kind === "contractor" ? role.contractor : undefined;
  const [contractor, setContractor] = useState(viewer ?? defaultContractor ?? contractors[0] ?? "");
  const [date, setDate] = useState(defaultDate);
  const [checklist, setChecklist] = useState<TbmChecklist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [person, setPerson] = usePerson();

  const [noticeText, setNoticeText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcribeError, setTranscribeError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [result, setResult] = useState<TbmCheckRecord | null>(null);
  const [records, setRecords] = useState<TbmCheckRecord[]>([]);

  useEffect(() => {
    if (!contractor && contractors[0]) setContractor(defaultContractor ?? contractors[0]);
  }, [contractor, contractors, defaultContractor]);

  const loadChecklist = useCallback(async () => {
    if (!contractor) return;
    try {
      setChecklist(await api.tbmChecklist(contractor, date));
      setError(null);
    } catch (e) {
      setChecklist(null);
      setError((e as Error).message);
    }
  }, [contractor, date]);

  useEffect(() => {
    setResult(null);
    void loadChecklist();
  }, [loadChecklist]);

  useEffect(() => {
    api.tbmChecks(viewer).then(setRecords).catch(() => setRecords([]));
  }, [viewer, result]);

  const addNotice = async () => {
    if (!noticeText.trim() || !person.trim()) {
      setError("공지 문장과 추가한 책임자 이름을 적어 주세요");
      return;
    }
    try {
      await api.addTbmNotice({ contractor, date, text: noticeText.trim(), created_by: person.trim() });
      setNoticeText("");
      await loadChecklist();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const transcribe = async () => {
    if (!file) return;
    setTranscribing(true);
    setTranscribeError(null);
    try {
      const t = await api.transcribeTbm(file, consent);
      setTranscript(t.transcript);
    } catch (e) {
      setTranscribeError((e as Error).message);
    } finally {
      setTranscribing(false);
    }
  };

  const check = async () => {
    if (!person.trim()) {
      setCheckError("확인한 책임자 이름을 적어 주세요 (이행 기록에 남습니다)");
      return;
    }
    setChecking(true);
    setCheckError(null);
    try {
      // 503 이 와도 전사문은 지우지 않는다 → 다시 누르면 된다
      setResult(await api.checkTbm({ contractor, date, transcript: transcript.trim(), checked_by: person.trim() }, viewer));
    } catch (e) {
      setCheckError((e as Error).message);
    } finally {
      setChecking(false);
    }
  };

  const items = checklist?.items ?? [];
  const missing = new Set(result?.missing_ids ?? []);
  const shownRecords = records.filter((r) => r.contractor === contractor);

  return (
    <div className="grid gap-4 text-sm">
      <section className="flex flex-wrap items-center gap-3 rounded-lg bg-white p-3 shadow-sm">
        <b>TBM 전달 확인 (F7)</b>
        {isPrime ? (
          <label className="flex items-center gap-1">
            협력사
            <select value={contractor} onChange={(e) => setContractor(e.target.value)} className="rounded border border-stone-300 bg-white px-2 py-1">
              {contractors.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span>{contractor}</span>
        )}
        <label className="flex items-center gap-1">
          TBM 날짜
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="rounded border border-stone-300 px-2 py-1" />
        </label>
        <input value={person} onChange={(e) => setPerson(e.target.value)} placeholder="확인한 책임자 (필수)" className="rounded border border-stone-300 px-2 py-1" />
        <span className="text-xs text-stone-500">빠진 항목을 알려 보충 전달하게 할 뿐, 작업을 승인·중지하지 않습니다</span>
      </section>
      {error && <p className="rounded bg-red-50 p-2 text-red-700">{error}</p>}

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-2 font-semibold">
          전달할 항목 {items.length}건 <span className="text-xs font-normal text-stone-500">— 원청이 공유한 조정·위험 시간대와 원청 공지 (서버가 만든다)</span>
        </h3>
        {items.length === 0 ? (
          <p className="text-stone-500">이 업체·날짜에 전달할 항목이 없습니다. 원청이 충돌을 공유하거나 조정을 적용하면 생깁니다.</p>
        ) : (
          <ul className="grid gap-1.5">
            {items.map((it) => {
              const r = result?.results.find((x) => x.item.id === it.id);
              const miss = missing.has(it.id);
              return (
                <li key={it.id} className={`rounded border p-2 ${miss ? "border-red-300 bg-red-50" : r ? "border-ok bg-ok-soft" : "border-stone-200"}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    {r && <b className={miss ? "text-red-700" : "text-ok"}>{miss ? "✗ 빠짐" : "✓ 전달"}</b>}
                    <span className={`rounded px-1.5 py-0.5 text-xs ${KIND_CLASS[it.kind]}`}>{KIND_LABEL[it.kind]}</span>
                    <span>{it.text}</span>
                    {it.rule_ids.length > 0 && <span className="text-xs text-stone-500">{it.rule_ids.join(", ")}</span>}
                  </div>
                  {r?.quote && <p className="mt-1 text-xs text-stone-600">근거 문장: "{r.quote}"</p>}
                  {r?.note && <p className="mt-1 text-xs text-stone-500">참고: {r.note}</p>}
                </li>
              );
            })}
          </ul>
        )}
        {isPrime && (
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-stone-200 pt-3">
            <b>원청 공지 추가</b>
            <input
              value={noticeText}
              onChange={(e) => setNoticeText(e.target.value)}
              placeholder="예: 축조 완료·인원 철수 확인 후 질소 라인 연결"
              className="min-w-[280px] flex-1 rounded border border-stone-300 px-2 py-1"
            />
            <button type="button" onClick={addNotice} className="rounded bg-brand px-2 py-1 font-medium text-white">
              공지 추가
            </button>
          </div>
        )}
      </section>

      <section className="grid gap-3 rounded-lg bg-white p-4 shadow-sm">
        <h3 className="font-semibold">TBM 녹음 → 전사문</h3>
        <p className="rounded bg-amber-50 p-2 text-xs text-amber-900">
          참석자 동의를 받은 녹음만 올립니다. 원본 녹음은 받아쓴 뒤 바로 지우고, 전사문은 전달 확인 기록으로 남습니다.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input type="file" accept={AUDIO_ACCEPT} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
          <label className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            참석자 녹음 동의를 받았습니다
          </label>
          <button
            type="button"
            onClick={transcribe}
            disabled={!file || !consent || transcribing}
            className="rounded bg-stone-800 px-2 py-1 font-medium text-white disabled:opacity-40"
          >
            {transcribing ? "받아쓰는 중…" : "받아쓰기"}
          </button>
          {transcribing && <span className="text-xs text-stone-500">CPU판 음성 서버는 녹음 길이의 2~3배 걸립니다</span>}
        </div>
        {transcribeError && (
          <p className="rounded bg-red-50 p-2 text-xs text-red-700">
            {transcribeError} — 음성 서버가 꺼져 있으면 아래 칸에 전사문을 직접 붙여 넣어도 됩니다.
          </p>
        )}
        <textarea
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          rows={6}
          placeholder="받아쓴 전사문이 여기에 들어옵니다. 직접 붙여 넣어도 됩니다."
          className="w-full rounded border border-stone-300 p-2 text-xs"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={check}
            disabled={!transcript.trim() || items.length === 0 || checking}
            className="rounded bg-ok px-3 py-1 font-medium text-white disabled:opacity-40"
          >
            {checking ? "확인 중…" : "전달 확인"}
          </button>
          {result && (
            <span>
              전달 항목 {result.results.length}건 중 <b className="text-ok">{result.results.length - result.missing_ids.length}건 전달</b>
              {result.missing_ids.length > 0 && (
                <>
                  , <b className="text-red-700">{result.missing_ids.length}건 빠짐</b> — 보충 전달 후 다시 확인하세요
                </>
              )}
              <span className="ml-2 text-xs text-stone-500">
                ({result.provider} {result.model})
              </span>
            </span>
          )}
        </div>
        {checkError && <p className="rounded bg-red-50 p-2 text-xs text-red-700">{checkError} — 전사문은 그대로 있으니 다시 눌러 주세요.</p>}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-2 font-semibold">지난 확인 기록 — {contractor}</h3>
        {shownRecords.length === 0 ? (
          <p className="text-stone-500">아직 확인 기록이 없습니다.</p>
        ) : (
          <ul className="divide-y divide-stone-100 text-xs">
            {shownRecords.map((r) => (
              <li key={r.id} className="flex flex-wrap gap-3 py-1.5">
                <span className="text-stone-500">{fmtDateTime(r.checked_at)}</span>
                <span>TBM {r.date}</span>
                <span>{r.checked_by}</span>
                <span>
                  {r.results.length}건 중 {r.results.length - r.missing_ids.length}건 전달
                  {r.missing_ids.length > 0 && <b className="ml-1 text-red-700">{r.missing_ids.length}건 빠짐</b>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
