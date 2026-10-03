// 개발자 API (/api/admin/*) 타입과 요청. 인증: Authorization: Bearer <DANBI_ADMIN_TOKEN> (쿠키 없음).

export interface Totals {
  runs: number; conversations: number; client_ips: number; failed: number;
  p50_ms: number | null; p95_ms: number | null; avg_first_token_ms: number | null; avg_tool_calls: number | null;
  input_tokens: number; output_tokens: number; cached_tokens: number; cost_usd: number | null;
  feedback_up: number; feedback_down: number; source_refs: number; source_cited: number;
}
export interface SeriesPoint {
  t: string; runs: number; failed: number; input_tokens: number | null; output_tokens: number | null;
  p50_ms: number | null; p95_ms: number | null;
}
export interface Overview {
  totals: Totals; series: SeriesPoint[]; bucket: "hour" | "day";
  tools: { name: string; calls: number; errors: number | null; avg_ms: number | null }[];
  sources: { kind: string; source_id: string | null; hits: number; cited: number | null }[];
  statuses: { status: string; n: number }[];
}
export interface RunRow {
  id: string; conversation_id: string | null; turn: number | null; channel: string; question: string; status: string;
  model: string; started_at: number; latency_ms: number | null; tool_calls: number; tool_errors: number;
  input_tokens: number; output_tokens: number; client_ip: string | null; user_key?: string | null; feedback: number | null;
}
export interface Run extends RunRow {
  answer: string | null; stop_reason: string | null; error: string | null; provider: string;
  system_hash: string; tools_hash: string; ended_at: number | null; first_token_ms: number | null;
  llm_calls: number; cached_tokens: number; cost_usd: number | null; tags: Record<string, unknown>;
}
export interface LLMCall {
  id: number; seq: number; attempt: number; started_at: number; ended_at: number; latency_ms: number;
  input_tokens: number; output_tokens: number; stop_reason: string | null; text: string | null;
  tool_calls: { id: string; name: string; arguments: Record<string, unknown> }[]; error: string | null;
}
export interface ToolCallRow {
  id: number; llm_seq: number; name: string; arguments: Record<string, unknown>; status_text: string | null;
  started_at: number; ended_at: number; latency_ms: number; is_error: number; result: string | null; result_chars: number;
}
export interface RunDetail {
  run: Run; llm_calls: LLMCall[]; tool_calls: ToolCallRow[];
  sources: { id: number; kind: string; source_id: string | null; title: string | null; url: string | null; cited: number }[];
  feedback: { id: number; rating: number; comment: string | null; created_at: number }[];
  conversation: { id: string; turn: number; question: string; status: string; started_at: number }[];
}
export interface AuditRow { id: number; at: number; actor: string; action: string; target: string | null; detail: string | null; client: string | null; hash: string }
export interface AuditResponse { verify: { ok: boolean; rows: number; broken_at: number | null }; items: AuditRow[] }
export interface PromptVersion { hash: string; kind: string; content: string }

export class Unauthorized extends Error {}

export function makeApi(token: string) {
  async function request(path: string): Promise<Response> {
    const res = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
    if (res.status === 401 || res.status === 503) {
      const body = await res.json().catch(() => ({}));
      throw new Unauthorized(body.detail || "다시 로그인하세요.");
    }
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    return res;
  }
  const json = async <T,>(path: string) => (await request(path)).json() as Promise<T>;
  return { request, json };
}
export type Api = ReturnType<typeof makeApi>;
