import { useEffect, useState } from "react";
import { compact, ms, pct } from "../lib/format";
import type { Api, Overview as OverviewData } from "./api";
import { ColumnChart, HBarChart, LineChart } from "./charts";
import { StatusBadge } from "./ui";

export function Overview({ api, query, tick, onTools, onError }: {
  api: Api; query: string; tick: number; onTools: (names: string[]) => void; onError: (e: unknown) => void;
}) {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.json<OverviewData>(`/api/admin/overview?${query}`)
      .then((d) => { if (alive) { setData(d); onTools(d.tools.map((t) => t.name)); } })
      .catch(onError)
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [api, query, tick, onTools, onError]);

  if (!data) return null;
  const t = data.totals, labels = data.series.map((s) => s.t);
  const tiles: [string, string, string][] = [
    ["질문 수", compact(t.runs), `대화 ${compact(t.conversations)}개 · IP ${compact(t.client_ips)}개`],
    ["실패율", pct(t.failed, t.runs), `${compact(t.failed)}건 (오류·상한·중단·거부)`],
    ["응답 시간 p50", ms(t.p50_ms), `p95 ${ms(t.p95_ms)}`],
    ["첫 글자까지", ms(t.avg_first_token_ms), "평균"],
    ["평균 도구 호출", t.avg_tool_calls == null ? "–" : t.avg_tool_calls.toFixed(1) + "회", "질문당"],
    ["토큰", compact(t.input_tokens + t.output_tokens), `입력 ${compact(t.input_tokens)} · 출력 ${compact(t.output_tokens)} · 캐시 ${compact(t.cached_tokens)}`],
    ["추정 비용", t.cost_usd == null ? "–" : "$" + t.cost_usd.toFixed(4), t.cost_usd == null ? "settings.yaml llm.pricing 미설정" : "선택 기간 합계"],
    ["인용률", pct(t.source_cited, t.source_refs), `출처 ${compact(t.source_refs)}건 중 답변에 등장`],
    ["사용자 평가", `👍 ${t.feedback_up} · 👎 ${t.feedback_down}`,
     t.feedback_up + t.feedback_down ? `긍정 ${pct(t.feedback_up, t.feedback_up + t.feedback_down)}` : "평가 없음"],
  ];
  return (
    <section className={loading ? "loading" : ""}>
      <div className="tiles">
        {tiles.map(([l, v, s]) => (
          <div className="tile" key={l}><div className="label">{l}</div><div className="value">{v}</div><div className="sub">{s}</div></div>
        ))}
      </div>
      <div className="grid2">
        <Card title="질문 수" desc={data.bucket === "hour" ? "시간별 (마우스를 올리면 실패 수)" : "일별 (마우스를 올리면 실패 수)"}>
          <ColumnChart labels={labels} bucket={data.bucket} series={[
            { name: "정상", color: "--series-1", values: data.series.map((s) => s.runs - s.failed) },
            { name: "실패", color: "--series-2", values: data.series.map((s) => s.failed) }]} />
        </Card>
        <Card title="응답 시간" desc="질문 1개를 끝까지 답하는 데 걸린 시간 (p50·p95)">
          <LineChart labels={labels} bucket={data.bucket} fmt={ms} series={[
            { name: "p50", color: "--series-1", values: data.series.map((s) => s.p50_ms) },
            { name: "p95", color: "--series-2", values: data.series.map((s) => s.p95_ms) }]} />
        </Card>
        <Card title="토큰 사용량" desc="입력·출력 토큰 합계">
          <ColumnChart labels={labels} bucket={data.bucket} series={[
            { name: "입력", color: "--series-1", values: data.series.map((s) => s.input_tokens || 0) },
            { name: "출력", color: "--series-2", values: data.series.map((s) => s.output_tokens || 0) }]} />
        </Card>
        <Card title="도구 사용" desc="호출 수 (마우스를 올리면 오류·평균 시간)">
          <HBarChart items={data.tools.map((x) => ({ label: x.name, value: x.calls, tip: [
            { value: compact(x.calls), label: "호출" }, { value: compact(x.errors || 0), label: "오류" },
            { value: ms(x.avg_ms), label: "평균 시간" }] }))} />
        </Card>
        <Card title="자주 쓰인 출처" desc="도구 결과에 등장한 횟수 (답변에 인용된 수는 툴팁)">
          <HBarChart items={data.sources.map((x) => ({ label: `${x.source_id || "?"} (${x.kind === "rag" ? "문서" : "웹"})`, value: x.hits, tip: [
            { value: compact(x.hits), label: "등장" }, { value: compact(x.cited || 0), label: "답변에 인용" }] }))} />
        </Card>
        <Card title="종료 상태" desc="실행이 어떻게 끝났는지">
          {data.statuses.length ? (
            <table><tbody>
              {data.statuses.map((s) => (
                <tr key={s.status}><td><StatusBadge status={s.status} /></td><td className="num">{compact(s.n)}</td>
                  <td className="num muted">{pct(s.n, t.runs)}</td></tr>
              ))}
            </tbody></table>
          ) : <div className="empty">기록이 없습니다</div>}
        </Card>
      </div>
    </section>
  );
}

function Card({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return <div className="card"><h2>{title}</h2><div className="desc">{desc}</div>{children}</div>;
}
