import { useEffect, useState } from "react";
import { compact, ms, num, when } from "../lib/format";
import { Markdown } from "../lib/markdown";
import type { Api, PromptVersion, RunDetail as Detail, RunRow } from "./api";
import { Waterfall } from "./charts";
import { CHANNEL, StatusBadge } from "./ui";

const LIMIT = 50;

export function RunsList({ api, query, tick, offset, setOffset, onOpen, onError }: {
  api: Api; query: string; tick: number; offset: number; setOffset: (n: number) => void;
  onOpen: (id: string) => void; onError: (e: unknown) => void;
}) {
  const [data, setData] = useState<{ total: number; items: RunRow[] } | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.json<{ total: number; items: RunRow[] }>(`/api/admin/runs?${query}&limit=${LIMIT}&offset=${offset}`)
      .then((d) => alive && setData(d)).catch(onError).finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [api, query, tick, offset, onError]);
  if (!data) return null;
  return (
    <div className={`card ${loading ? "loading" : ""}`}>
      <table className="runs-table">
        <thead><tr><th>시각</th><th>채널</th><th>IP</th><th>질문</th><th>상태</th><th className="num">응답</th>
          <th className="num">도구</th><th className="num">토큰</th><th>평가</th></tr></thead>
        <tbody>
          {data.items.length === 0 && <tr><td colSpan={9} className="empty">조건에 맞는 실행이 없습니다</td></tr>}
          {data.items.map((r) => (
            <tr key={r.id} tabIndex={0} onClick={() => onOpen(r.id)} onKeyDown={(e) => e.key === "Enter" && onOpen(r.id)}>
              <td>{when(r.started_at)}</td><td>{CHANNEL[r.channel] || r.channel}</td>
              <td className="muted">{r.client_ip || ""}</td>
              <td className="q" title={r.question}>{r.question}</td><td><StatusBadge status={r.status} /></td>
              <td className="num">{ms(r.latency_ms)}</td>
              <td className="num">{r.tool_calls}{r.tool_errors ? ` (오류 ${r.tool_errors})` : ""}</td>
              <td className="num">{compact((r.input_tokens || 0) + (r.output_tokens || 0))}</td>
              <td>{r.feedback == null ? "" : r.feedback > 0 ? "👍" : r.feedback < 0 ? "👎" : "±"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="pager">
        <span>{num(data.total)}건 중 {data.total ? offset + 1 : 0}–{Math.min(offset + LIMIT, data.total)}</span>
        <button className="ghost" type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>이전</button>
        <button className="ghost" type="button" disabled={offset + LIMIT >= data.total} onClick={() => setOffset(offset + LIMIT)}>다음</button>
      </div>
    </div>
  );
}

export function RunDetail({ api, id, onBack, onOpen, onError }: {
  api: Api; id: string; onBack: () => void; onOpen: (id: string) => void; onError: (e: unknown) => void;
}) {
  const [d, setD] = useState<Detail | null>(null);
  useEffect(() => {
    let alive = true;
    api.json<Detail>(`/api/admin/runs/${encodeURIComponent(id)}`).then((x) => alive && setD(x)).catch(onError);
    window.scrollTo({ top: 0 });
    return () => { alive = false; };
  }, [api, id, onError]);

  const openPrompt = async (h: string) => {
    const p = await api.json<PromptVersion>(`/api/admin/prompts/${encodeURIComponent(h)}`).catch(onError);
    if (!p) return;
    const w = window.open("", "_blank");
    if (w) {
      w.document.title = `${p.kind} ${p.hash}`;
      const pre = w.document.createElement("pre");
      pre.style.whiteSpace = "pre-wrap";
      pre.textContent = p.content;
      w.document.body.append(pre);
    }
  };
  const PromptLink = ({ h }: { h: string }) =>
    h ? <a href="#" onClick={(e) => { e.preventDefault(); void openPrompt(h); }}>{h}</a> : <>–</>;

  if (!d) return <button className="ghost back" type="button" onClick={onBack}>← 목록으로</button>;
  const r = d.run;
  const steps = [...d.llm_calls.map((c) => ({ t: c.started_at, k: "llm" as const, c })),
                 ...d.tool_calls.map((c) => ({ t: c.started_at, k: "tool" as const, c }))].sort((a, b) => a.t - b.t);
  return (
    <div>
      <button className="ghost back" type="button" onClick={onBack}>← 목록으로</button>
      <div className="card">
        <h2>{r.question}</h2>
        <div className="meta">
          <div><span>상태</span><StatusBadge status={r.status} /></div>
          <div><span>시각</span>{when(r.started_at)}</div>
          <div><span>채널</span>{CHANNEL[r.channel] || r.channel}</div>
          <div><span>클라이언트 IP</span>{r.client_ip || "–"}</div>
          {r.user_key && <div><span>사용자 키</span><code>{r.user_key}</code></div>}
          <div><span>모델</span>{r.provider}/{r.model}</div>
          <div><span>응답 시간</span>{ms(r.latency_ms)} (첫 글자 {ms(r.first_token_ms)})</div>
          <div><span>호출</span>LLM {r.llm_calls} · 도구 {r.tool_calls}{r.tool_errors ? ` (오류 ${r.tool_errors})` : ""}</div>
          <div><span>토큰</span>입력 {num(r.input_tokens)} · 출력 {num(r.output_tokens)} · 캐시 {num(r.cached_tokens)}</div>
          <div><span>비용</span>{r.cost_usd == null ? "–" : "$" + r.cost_usd.toFixed(6)}</div>
          <div><span>대화</span>{r.conversation_id ? `${r.conversation_id.slice(0, 8)}… ${r.turn}번째 질문` : "–"}</div>
          <div><span>시스템 프롬프트</span><PromptLink h={r.system_hash} /></div>
          <div><span>도구 정의</span><PromptLink h={r.tools_hash} /></div>
          <div><span>실행 ID</span>{r.id}</div>
          {Object.keys(r.tags || {}).length > 0 && <div><span>태그</span>{JSON.stringify(r.tags)}</div>}
        </div>
        {r.error && <pre>오류: {r.error}</pre>}
      </div>
      <div className="card gap">
        <h2>실행 타임라인</h2>
        <div className="desc">LLM 호출과 도구 호출의 시작·끝 (같은 줄에 겹치면 병렬 실행)</div>
        <Waterfall detail={d} />
      </div>
      <div className="card gap"><h2>답변</h2><Markdown className="answer" text={r.answer || "(답변 없음)"} /></div>
      <div className="card gap">
        <h2>단계별 기록</h2>
        {steps.map((s) => s.k === "llm" ? (
          <details className="step" key={`l${s.c.id}`}>
            <summary><strong>LLM 호출 {s.c.seq}{s.c.attempt ? ` · 재시도 ${s.c.attempt}` : ""}</strong>
              <span className="muted">{ms(s.c.latency_ms)} · 입력 {num(s.c.input_tokens)} / 출력 {num(s.c.output_tokens)} · {s.c.error ? "⚠ 오류" : s.c.stop_reason || ""}</span>
            </summary>
            {s.c.error && <pre>{s.c.error}</pre>}
            {s.c.text && <><div className="muted">생성한 텍스트</div><pre>{s.c.text}</pre></>}
            {s.c.tool_calls.length > 0 && <><div className="muted">요청한 도구 호출</div><pre>{JSON.stringify(s.c.tool_calls, null, 2)}</pre></>}
          </details>
        ) : (
          <details className="step" key={`t${s.c.id}`}>
            <summary><strong>{s.c.name}</strong><span className="pill">LLM {s.c.llm_seq}</span>
              <span className="muted">{ms(s.c.latency_ms)} · {s.c.is_error ? "⚠ 오류" : `결과 ${num(s.c.result_chars)}자`}</span>
              <span className="muted">{s.c.status_text || ""}</span>
            </summary>
            <div className="muted">인자</div><pre>{JSON.stringify(s.c.arguments, null, 2)}</pre>
            <div className="muted">결과 (모델이 받은 그대로)</div><pre>{s.c.result || ""}</pre>
          </details>
        ))}
      </div>
      <div className="card gap">
        <h2>출처 {d.sources.length}건</h2>
        <div className="desc">도구 결과에 나온 출처. '인용'은 답변 본문에 링크나 문서명이 나온 경우 (근사치)</div>
        {d.sources.length > 0 && (
          <table>
            <thead><tr><th>종류</th><th>소스</th><th>제목</th><th>인용</th></tr></thead>
            <tbody>{d.sources.map((s) => (
              <tr key={s.id}><td>{s.kind === "rag" ? "문서" : "웹"}</td><td>{s.source_id || ""}</td>
                <td>{s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title || s.url}</a> : s.title || ""}</td>
                <td>{s.cited ? "✓" : ""}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
      {d.feedback.length > 0 && (
        <div className="card gap"><h2>사용자 평가</h2>
          {d.feedback.map((f) => <div key={f.id}>{f.rating > 0 ? "👍" : "👎"} {when(f.created_at)} {f.comment || ""}</div>)}
        </div>
      )}
      {d.conversation.length > 1 && (
        <div className="card gap"><h2>같은 대화의 질문</h2>
          <table><tbody>{d.conversation.map((c) => (
            <tr key={c.id} tabIndex={0} className={c.id === r.id ? "current" : "link"} onClick={() => c.id !== r.id && onOpen(c.id)}>
              <td className="num">{c.turn}</td><td>{c.question}</td><td><StatusBadge status={c.status} /></td><td>{when(c.started_at)}</td>
            </tr>
          ))}</tbody></table>
        </div>
      )}
    </div>
  );
}
