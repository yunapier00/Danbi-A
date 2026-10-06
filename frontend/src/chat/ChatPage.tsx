import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  AlertIcon, CheckIcon, ClockIcon, ExternalIcon, LinkIcon, PlusIcon, SearchIcon, SendIcon, ThumbDownIcon, ThumbUpIcon,
} from "../components/icons";
import { GoogleButton, LOGIN_ERRORS } from "../components/GoogleButton";
import { Logo, LogoMark } from "../components/Logo";
import { Markdown } from "../lib/markdown";
import { readSSE } from "../lib/sse";
import "./chat.css";

interface Source { title: string; url: string }
interface BotMessage {
  id: number;
  role: "bot";
  status: string | null;   // 도구 실행 중 문구 (null이면 숨김)
  text: string;
  sources: Source[];
  meta: { toolCalls: number; elapsed: number; runId: string | null } | null;
  error: string | null;
}
interface UserMessage { id: number; role: "user"; text: string }
type Message = UserMessage | BotMessage;
interface Me {
  user: { email: string; name: string | null } | null;
  login_enabled: boolean;
  anonymous_allowed: boolean;
  domain: string;
  remaining: number | null;
}

const SESSION_KEY = "danbi_session";
const storage = {
  get: () => { try { return sessionStorage.getItem(SESSION_KEY); } catch { return null; } },
  set: (v: string) => { try { sessionStorage.setItem(SESSION_KEY, v); } catch { /* 저장 불가 환경 */ } },
  clear: () => { try { sessionStorage.removeItem(SESSION_KEY); } catch { /* 저장 불가 환경 */ } },
};

let nextId = 1;

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(null);  // 오늘 남은 질문 수 (서버가 done에 실어 보냄)
  const [me, setMe] = useState<Me | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);
  const sessionId = useRef<string | null>(storage.get());
  const scroller = useRef<HTMLElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { document.title = "단비 — 단국대 비서"; }, []);
  // 로그인 상태. Google 로그인 실패는 ?login_error=코드 로 돌아오므로 읽고 주소에서 지운다
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const code = params.get("login_error");
    if (code) {
      setLoginError(LOGIN_ERRORS[code] || "로그인하지 못했어요. 다시 시도해 주세요.");
      params.delete("login_error");
      history.replaceState(null, "", location.pathname + (params.size ? `?${params}` : "") + location.hash);
    }
    fetch("/api/me").then((r) => (r.ok ? r.json() : null)).then((m: Me | null) => {
      if (!m) { setMe({ user: null, login_enabled: false, anonymous_allowed: true, domain: "", remaining: null }); return; }
      setMe(m);
      if (typeof m.remaining === "number") setRemaining(m.remaining);
    }).catch(() => setMe({ user: null, login_enabled: false, anonymous_allowed: true, domain: "", remaining: null }));
  }, []);
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  const updateBot = (id: number, patch: (m: BotMessage) => Partial<BotMessage>) =>
    setMessages((all) => all.map((m) => (m.id === id && m.role === "bot" ? { ...m, ...patch(m) } : m)));

  const ask = useCallback(async (text: string) => {
    if (busy || !text.trim()) return;
    setBusy(true);
    const botId = nextId + 1;
    setMessages((all) => [
      ...all,
      { id: nextId, role: "user", text },
      { id: botId, role: "bot", status: "질문을 살펴보는 중", text: "", sources: [], meta: null, error: null },
    ]);
    nextId += 2;
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId.current }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        if (res.status === 429 && String(body.detail || "").includes("번까지")) setRemaining(0);
        if (res.status === 401) setMe((m) => (m ? { ...m, user: null } : m));  // 로그인이 풀렸으면 로그인 화면으로
        throw new Error(body.detail || `요청 실패 (${res.status})`);
      }
      for await (const { event, data } of readSSE(res)) {
        const d = data as Record<string, unknown>;
        if (event === "session") {
          sessionId.current = String(d.session_id);
          storage.set(sessionId.current);
        } else if (event === "status") {
          updateBot(botId, () => ({ status: String(d.text) }));
        } else if (event === "token") {
          updateBot(botId, (m) => ({ text: m.text + String(d.text), status: null }));
        } else if (event === "sources") {
          updateBot(botId, () => ({ sources: d.items as Source[] }));
        } else if (event === "done") {
          if (typeof d.remaining === "number") setRemaining(d.remaining);
          updateBot(botId, () => ({
            meta: { toolCalls: Number(d.tool_calls), elapsed: Number(d.elapsed), runId: (d.run_id as string) || null },
          }));
        } else if (event === "error") {
          updateBot(botId, () => ({ error: String(d.message) }));
        }
      }
    } catch (e) {
      updateBot(botId, () => ({ error: e instanceof Error && e.message ? e.message : "서버에 연결할 수 없습니다." }));
    } finally {
      updateBot(botId, () => ({ status: null }));
      setBusy(false);
      textarea.current?.focus();
    }
  }, [busy]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = input;
    setInput("");
    void ask(text);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  };

  // 입력창 높이를 내용에 맞춘다
  useEffect(() => {
    const t = textarea.current;
    if (t) { t.style.height = ""; t.style.height = `${t.scrollHeight}px`; }
  }, [input]);

  const reset = () => {
    if (sessionId.current) {
      void fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ session_id: sessionId.current }) }).catch(() => {});
    }
    sessionId.current = null;
    storage.clear();
    setMessages([]);
    textarea.current?.focus();
  };

  const logout = async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    reset();
    setRemaining(null);
    setMe((m) => (m ? { ...m, user: null } : m));
  };
  const needLogin = me !== null && !me.user && !me.anonymous_allowed;

  return (
    <div className="chat-root">
      <header className="topbar">
        <div className="brand">
          <Logo height={26} />
          <span className="brand-sep" aria-hidden="true" />
          <small className="brand-sub">단국대학교 비서 AI</small>
        </div>
        <div className="top-actions">
          {!needLogin && (
            <button className="new-chat" type="button" onClick={reset} disabled={messages.length === 0 && !busy}>
              <PlusIcon /> 새 대화
            </button>
          )}
          {me && !me.user && me.login_enabled && !needLogin && (  // 비로그인으로도 쓸 수 있을 때도 로그인할 길은 열어 둔다
            <a className="new-chat login-link" href="/api/auth/login?next=/">로그인</a>
          )}
          {me?.user && (
            <span className="account">
              <span className="account-name" title={me.user.email}>{me.user.name || me.user.email}</span>
              <button className="link-btn" type="button" onClick={logout}>로그아웃</button>
            </span>
          )}
        </div>
      </header>
      {needLogin ? (
        <main className="gate-wrap">
          <section className="gate">
            <Logo height={40} />
            <h1>단국대학교 비서 AI</h1>
            {me.login_enabled ? <>
              <p>단국대학교 Google 계정(<b>@{me.domain}</b>)으로 로그인하면 이용할 수 있어요.</p>
              <GoogleButton next="/" label="학교 Google 계정으로 로그인" />
            </> : <p>로그인이 아직 준비되지 않았어요. 잠시 후 다시 시도해 주세요.</p>}
            {loginError && <p className="gate-error" role="alert"><AlertIcon /> {loginError}</p>}
          </section>
        </main>
      ) : <>
      <main ref={scroller}>
        {loginError && <p className="gate-error banner" role="alert"><AlertIcon /> {loginError}</p>}
        <div className="log" aria-live="polite">
          {/* 첫 화면 안내·예시 질문 (2026-10-03 숨김. 다시 쓰려면 아래 줄의 주석을 풀면 된다)
          {messages.length === 0 && <Welcome onAsk={ask} />}
          */}
          {messages.map((m) => (m.role === "user"
            ? <div key={m.id} className="row row-user"><div className="bubble user">{m.text}</div></div>
            : <BotBubble key={m.id} m={m} />))}
        </div>
      </main>
      <footer className="composer-wrap">
        <form className="composer" onSubmit={submit}>
          <textarea ref={textarea} rows={1} maxLength={1000} value={input} placeholder="질문을 입력하세요"
                    aria-label="질문 입력" onChange={(e) => setInput(e.target.value)} onKeyDown={onKeyDown} />
          <button className="send" type="submit" disabled={busy || !input.trim()} aria-label="보내기" title="보내기 (Enter)">
            <SendIcon />
          </button>
        </form>
        <div className="hint">
          {remaining !== null && <>
            <span className={remaining === 0 ? "hint-quota empty" : "hint-quota"}>오늘 남은 질문 {remaining}회</span>
            <span className="hint-sep" aria-hidden="true">·</span>
          </>}
          <span className="hint-keys">Enter 보내기 · Shift+Enter 줄바꿈</span>
          <span className="hint-sep" aria-hidden="true">·</span>
          <span>학교 자료를 근거로 답하지만 틀릴 수 있어요. 중요한 일정은 원문을 확인하세요.</span>
          <span className="hint-sep" aria-hidden="true">·</span>
          <span>질문 기록은 서비스 개선을 위해 저장돼요.</span>
        </div>
      </footer>
      </>}
    </div>
  );
}

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

function BotBubble({ m }: { m: BotMessage }) {
  const thinking = m.status !== null && !m.text && !m.error;
  return (
    <div className="row row-bot">
      <span className="avatar" aria-hidden="true"><LogoMark size={18} /></span>
      <div className="bubble bot">
        {thinking && (
          <div className="thinking" role="status">
            <span className="dots" aria-hidden="true"><i /><i /><i /></span>
            <span className="thinking-text"><SearchIcon /> {m.status}</span>
          </div>
        )}
        {m.text && <Markdown className="answer" text={m.text} />}
        {m.error && <p className="error"><AlertIcon /> {m.error}</p>}
        {m.sources.length > 0 && (
          <div className="sources">
            <div className="sources-title"><LinkIcon /> 원문 {m.sources.length}개</div>
            <ul>
              {m.sources.map((s) => (
                <li key={s.url}>
                  <a href={s.url} target="_blank" rel="noopener noreferrer">
                    <span className="src-title">{s.title || s.url}</span>
                    <span className="src-host">{hostOf(s.url)} <ExternalIcon /></span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
        {m.meta && (
          <div className="meta">
            <span className="meta-item"><ClockIcon /> {m.meta.elapsed.toFixed(1)}초</span>
            {m.meta.toolCalls > 0 && <span className="meta-item"><SearchIcon /> 자료 {m.meta.toolCalls}회 확인</span>}
            {m.meta.runId && <Feedback runId={m.meta.runId} />}
          </div>
        )}
      </div>
    </div>
  );
}

function Feedback({ runId }: { runId: string }) {
  const [state, setState] = useState<"idle" | "sending" | "ok" | "fail">("idle");
  const [picked, setPicked] = useState<1 | -1 | null>(null);
  const send = async (rating: 1 | -1) => {
    setPicked(rating);
    setState("sending");
    try {
      const res = await fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
                                                 body: JSON.stringify({ run_id: runId, rating }) });
      setState(res.ok ? "ok" : "fail");
    } catch { setState("fail"); }
  };
  if (state === "ok") return <span className="fb fb-done"><CheckIcon /> 평가 고마워요</span>;
  if (state === "fail") return <span className="fb fb-fail">평가를 저장하지 못했어요</span>;
  return (
    <span className="fb">
      <button type="button" title="도움이 됐어요" aria-label="도움이 됐어요" aria-pressed={picked === 1}
              disabled={state === "sending"} onClick={() => send(1)}><ThumbUpIcon /></button>
      <button type="button" title="아쉬워요" aria-label="아쉬워요" aria-pressed={picked === -1}
              disabled={state === "sending"} onClick={() => send(-1)}><ThumbDownIcon /></button>
    </span>
  );
}

const EXAMPLES = ["죽전역 셔틀 첫차 시간은?", "다전공 이수가 제한되는 단과대는?", "모시공 최근 공지 뭐 있어?", "모바일시스템공학과 졸업 요건 알려줘"];

// 첫 화면 안내 — 지금은 쓰지 않는다 (ChatPage의 주석 참고)
export function Welcome({ onAsk }: { onAsk: (q: string) => void }) {
  return (
    <div className="welcome">
      <h2>무엇이 궁금하세요?</h2>
      <div>학칙·학사일정·셔틀·캠퍼스, 등록된 학과의 공지·교수·교과과정을 찾아 출처와 함께 답합니다.</div>
      <div className="chips">
        {EXAMPLES.map((q) => <button key={q} className="chip" type="button" onClick={() => onAsk(q)}>{q}</button>)}
      </div>
    </div>
  );
}
