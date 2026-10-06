import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { makeApi, Unauthorized } from "./api";
import { Audit } from "./Audit";
import { Overview } from "./Overview";
import { RunDetail, RunsList } from "./Runs";
import { GoogleButton } from "../components/GoogleButton";
import { Logo } from "../components/Logo";
import { TooltipProvider } from "./ui";
import "./dev.css";

type Tab = "overview" | "runs" | "audit";
const RANGES: [string, string][] = [["24h", "24시간"], ["7d", "7일"], ["30d", "30일"], ["90d", "90일"], ["all", "전체"]];
const TOKEN_KEY = "danbi_admin_token";
const THEME_KEY = "danbi_dev_theme";
const safe = <T,>(fn: () => T, fallback: T): T => { try { return fn(); } catch { return fallback; } };

export default function DevPage() {
  const [token, setToken] = useState<string | null>(() => safe(() => sessionStorage.getItem(TOKEN_KEY), null));
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [actor, setActor] = useState("");
  const [loginError, setLoginError] = useState("");
  const api = useMemo(() => makeApi(token), [token]);

  const [tab, setTab] = useState<Tab>("overview");
  const [range, setRange] = useState("7d");
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [tool, setTool] = useState("");
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const [tools, setTools] = useState<string[]>([]);
  const [tick, setTick] = useState(0);
  const [auto, setAuto] = useState(false);

  useEffect(() => { document.title = "단비 LLMOps"; }, []);
  useEffect(() => {
    const th = safe(() => localStorage.getItem(THEME_KEY), null);
    if (th) document.documentElement.dataset.theme = th;
  }, []);

  const logout = useCallback((msg = "") => {
    safe(() => sessionStorage.removeItem(TOKEN_KEY), undefined);
    setToken(null); setAuthed(false); setLoginError(msg);
  }, []);
  const signOut = async () => {
    if (!token) await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    logout();
  };
  const onError = useCallback((e: unknown) => {
    if (e instanceof Unauthorized) logout(e.message);
    else console.error(e);
  }, [logout]);

  // Google 로그인 쿠키(또는 비상용 토큰)로 관리자인지 확인한다 (로그인은 감사 로그에 남는다)
  useEffect(() => {
    setChecking(true);
    api.json<{ actor: string }>("/api/admin/whoami")
      .then((r) => { setAuthed(true); setActor(r.actor); })
      .catch((e) => {
        setAuthed(false);
        if (token) logout(e instanceof Error ? e.message : "");
        else if (e instanceof Error && e.message !== "로그인이 필요합니다.") setLoginError(e.message);
      })
      .finally(() => setChecking(false));
  }, [api, token, logout]);

  useEffect(() => { const t = setTimeout(() => setQDebounced(q.trim()), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => { setOffset(0); }, [range, channel, status, tool, qDebounced]);
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(() => setTick((n) => n + 1), 30000);
    return () => clearInterval(t);
  }, [auto]);

  const baseQuery = useMemo(() => {
    const p = new URLSearchParams({ range });
    if (channel) p.set("channel", channel);
    return p.toString();
  }, [range, channel]);
  const runsQuery = useMemo(() => {
    const p = new URLSearchParams(baseQuery);
    if (status) p.set("status", status);
    if (tool) p.set("tool", tool);
    if (qDebounced) p.set("q", qDebounced);
    return p.toString();
  }, [baseQuery, status, tool, qDebounced]);

  const submitLogin = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const value = String(new FormData(e.currentTarget).get("token") || "").trim();
    safe(() => sessionStorage.setItem(TOKEN_KEY, value), undefined);
    setLoginError("");
    setToken(value);
  };

  const toggleTheme = () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    safe(() => localStorage.setItem(THEME_KEY, root.dataset.theme!), undefined);
  };

  const exportRuns = async () => {
    const res = await api.request(`/api/admin/export?range=${encodeURIComponent(range)}`).catch(onError);
    if (!res) return;
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `danbi_runs_${range}.jsonl` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  if (!authed) {
    return (
      <div className="dev-root">
        <section className="login">
          <div className="login-brand"><Logo height={30} /><h1>LLMOps</h1></div>
          {checking ? <p>확인 중…</p> : <>
            <p>개발자 전용 페이지입니다. 관리자로 등록된 학교 Google 계정으로 로그인하세요. 접근은 감사 로그에 남습니다.</p>
            <GoogleButton next="/dev" />
            <div className="err">{loginError}</div>
            <details className="token-login">
              <summary>비상용 토큰으로 들어가기</summary>
              <form onSubmit={submitLogin}>
                <input name="token" type="password" autoComplete="current-password" placeholder="DANBI_ADMIN_TOKEN" required />
                <button className="ghost" type="submit">들어가기</button>
              </form>
            </details>
          </>}
        </section>
      </div>
    );
  }

  return (
    <div className="dev-root">
      <TooltipProvider>
        <header>
          <div className="bar">
            <h1><Logo height={20} /> LLMOps<small>개발자 전용</small></h1>
            <nav role="tablist">
              {([["overview", "개요"], ["runs", "실행 기록"], ["audit", "감사 로그"]] as [Tab, string][]).map(([k, label]) => (
                <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>
              ))}
            </nav>
            <span className="spacer" />
            <button className="ghost" type="button" onClick={exportRuns} title="선택한 기간의 실행 전체를 JSONL로 내려받습니다 (감사 기록됨)">내보내기</button>
            <button className="ghost" type="button" onClick={toggleTheme} aria-label="테마 전환">테마</button>
            <span className="actor" title="감사 로그에 남는 이름">{actor.replace(/^google:/, "")}</span>
            <button className="ghost" type="button" onClick={signOut}>{token ? "나가기" : "로그아웃"}</button>
          </div>
        </header>
        <div className="wrap">
          {tab !== "audit" && (
            <div className="filters">
              <div className="seg" role="group" aria-label="기간">
                {RANGES.map(([k, label]) => (
                  <button key={k} aria-pressed={range === k} onClick={() => setRange(k)}>{label}</button>
                ))}
              </div>
              <select aria-label="채널" value={channel} onChange={(e) => setChannel(e.target.value)}>
                <option value="">모든 채널</option><option value="web">웹</option><option value="kakao">카카오</option><option value="cli">CLI</option><option value="eval">평가</option>
              </select>
              {tab === "runs" && (
                <>
                  <select aria-label="상태" value={status} onChange={(e) => { setStatus(e.target.value); setRunId(null); }}>
                    <option value="">모든 상태</option><option value="ok">정상</option><option value="error">오류</option>
                    <option value="limit">상한 도달</option><option value="aborted">중단</option><option value="refused">거부</option>
                    <option value="max_tokens">길이 초과</option>
                  </select>
                  <select aria-label="도구" value={tool} onChange={(e) => { setTool(e.target.value); setRunId(null); }}>
                    <option value="">모든 도구</option>{tools.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                  <input type="search" placeholder="질문·답변·실행 ID·IP 검색" aria-label="검색" value={q}
                         onChange={(e) => { setQ(e.target.value); setRunId(null); }} />
                </>
              )}
              <button className="ghost" type="button" onClick={() => setTick((n) => n + 1)}>새로고침</button>
              <label className="check"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> 30초마다</label>
            </div>
          )}
          {tab === "overview" && <Overview api={api} query={baseQuery} tick={tick} onTools={setTools} onError={onError} />}
          {tab === "runs" && (runId
            ? <RunDetail api={api} id={runId} onBack={() => setRunId(null)} onOpen={setRunId} onError={onError} />
            : <RunsList api={api} query={runsQuery} tick={tick} offset={offset} setOffset={setOffset} onOpen={setRunId} onError={onError} />)}
          {tab === "audit" && <Audit api={api} tick={tick} onError={onError} />}
        </div>
      </TooltipProvider>
    </div>
  );
}
