import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertIcon, CalendarIcon, CheckIcon, CloseIcon } from "../components/icons";

export interface EclassStatus {
  available: boolean;
  connected: boolean;
  connected_at?: number | null;
  last_ok_at?: number | null;
  last_error?: string | null;
}

const API = "/api/integrations/eclass";

export async function fetchEclassStatus(): Promise<EclassStatus | null> {
  try {
    const r = await fetch(API);
    return r.ok ? ((await r.json()) as EclassStatus) : null;
  } catch { return null; }
}

function when(ts?: number | null): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** eclass(Canvas) 캘린더 피드 연결 창. 주소는 채팅이 아니라 이 입력칸으로만 받는다 (대화 기록·LLM에 남지 않게). */
export function EclassDialog({ open, status, onClose, onChange }: {
  open: boolean;
  status: EclassStatus | null;
  onClose: () => void;
  onChange: (s: EclassStatus) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [url, setUrl] = useState("");
  const [state, setState] = useState<"idle" | "sending">("idle");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      setUrl(""); setError(null); setDone(null); setEditing(false);
      d.showModal();
    } else if (!open && d.open) d.close();
  }, [open]);

  const connected = Boolean(status?.connected);
  const showForm = !connected || editing;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!url.trim() || state === "sending") return;
    setState("sending"); setError(null); setDone(null);
    try {
      const r = await fetch(API, { method: "PUT", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify({ url: url.trim() }) });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || `연결하지 못했어요 (${r.status})`);
      setUrl(""); setEditing(false);
      setDone(`연결했어요. 일정 ${body.events}건을 확인했고, 그중 다가오는 것은 ${body.upcoming}건이에요.`);
      onChange(body as EclassStatus);
    } catch (err) {
      setError(err instanceof Error ? err.message : "연결하지 못했어요.");
    } finally { setState("idle"); }
  };

  const disconnect = async () => {
    setState("sending"); setError(null); setDone(null);
    try {
      const r = await fetch(API, { method: "DELETE" });
      if (!r.ok) throw new Error(`연결을 해제하지 못했어요 (${r.status})`);
      setDone("연결을 해제했어요. 저장된 주소도 지웠어요.");
      onChange({ available: true, connected: false });
    } catch (err) {
      setError(err instanceof Error ? err.message : "연결을 해제하지 못했어요.");
    } finally { setState("idle"); }
  };

  return (
    <dialog ref={ref} className="eclass-dialog" aria-labelledby="eclass-title" onClose={onClose}
            onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <div className="dlg-body">
        <div className="dlg-head">
          <h2 id="eclass-title"><CalendarIcon size={18} /> eclass 일정 연결</h2>
          <button className="icon-btn" type="button" aria-label="닫기" onClick={onClose}><CloseIcon /></button>
        </div>
        <p className="dlg-lead">
          연결하면 “이번 주 과제 뭐 있어?”처럼 물어볼 수 있어요. 단비는 eclass 캘린더의 과제 마감·일정만 읽고,
          제출 여부와 성적은 볼 수 없어요.
        </p>

        {connected && (
          <div className="dlg-status">
            <span className="dlg-badge"><CheckIcon /> 연결됨</span>
            <span className="dlg-muted">
              {status?.last_ok_at ? `마지막 확인 ${when(status.last_ok_at)}` : `연결 ${when(status?.connected_at)}`}
            </span>
            {status?.last_error && <p className="dlg-error" role="alert"><AlertIcon /> {status.last_error}</p>}
          </div>
        )}

        {showForm && (
          <>
            <ol className="dlg-steps">
              <li><a href="https://canvas.dankook.ac.kr/calendar" target="_blank" rel="noopener noreferrer">eclass 캘린더</a>를
                열어요 (로그인 필요).</li>
              <li>화면 오른쪽 아래의 <b>캘린더 피드</b>를 눌러요.</li>
              <li>나온 주소(<code>…/feeds/calendars/user_….ics</code>)를 복사해 아래에 붙여 넣어요.</li>
            </ol>
            <form className="dlg-form" onSubmit={submit}>
              <input type="url" inputMode="url" autoComplete="off" spellCheck={false} required maxLength={300}
                     placeholder="https://canvas.dankook.ac.kr/feeds/calendars/user_….ics" aria-label="캘린더 피드 주소"
                     value={url} onChange={(e) => setUrl(e.target.value)} />
              <button className="dlg-primary" type="submit" disabled={state === "sending" || !url.trim()}>
                {state === "sending" ? "확인 중…" : "연결"}
              </button>
            </form>
            <p className="dlg-note">
              이 주소를 아는 사람은 누구나 내 일정을 볼 수 있어요. 채팅창에는 붙여 넣지 마세요.
              단비는 주소를 암호화해 저장하고, 연결을 해제하면 바로 지워요.
            </p>
          </>
        )}

        {error && <p className="dlg-error" role="alert"><AlertIcon /> {error}</p>}
        {done && <p className="dlg-done" role="status"><CheckIcon /> {done}</p>}

        {connected && !editing && (
          <div className="dlg-actions">
            <button className="new-chat" type="button" onClick={() => setEditing(true)} disabled={state === "sending"}>
              주소 다시 등록
            </button>
            <button className="dlg-danger" type="button" onClick={disconnect} disabled={state === "sending"}>
              연결 해제
            </button>
          </div>
        )}
      </div>
    </dialog>
  );
}
