// 라이브러리 없이 SVG로 그리는 차트 (dataviz 기준: 막대 ≤24px·4px 둥근 끝, 쌓인 막대 2px 간격, 선 2px,
// 끝점 r4 + 2px 표면색 테두리, 실선 헤어라인 격자, 차트마다 툴팁과 '표로 보기'). 색은 series 1·2만 쓴다.
import { useRef, useState, type PointerEvent } from "react";
import { compact, ms, niceMax } from "../lib/format";
import type { LLMCall, RunDetail, ToolCallRow } from "./api";
import { Legend, TableView, useTooltip, useWidth, type TipRow } from "./ui";

export interface Series { name: string; color: string; values: (number | null)[] }
type Fmt = (v: number | null | undefined) => string;

const shortLabel = (t: string, bucket: "hour" | "day") => (bucket === "hour" ? t.slice(11, 16) : t.slice(5));

function roundedTop(x: number, y: number, w: number, h: number, r: number) {
  r = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}
function roundedRight(x: number, y: number, w: number, h: number, r: number) {
  r = Math.min(r, w / 2, h / 2);
  return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
}

function Empty({ text = "이 기간에 기록이 없습니다" }: { text?: string }) {
  return <div className="empty">{text}</div>;
}

function Grid({ L, R, T, plotH, W, max, fmt }: { L: number; R: number; T: number; plotH: number; W: number; max: number; fmt: Fmt }) {
  return (
    <>
      {[0, 1, 2, 3, 4].map((k) => {
        const y = T + plotH - (plotH * k) / 4;
        return (
          <g key={k}>
            <line x1={L} x2={W - R} y1={y} y2={y} stroke={k ? "var(--grid)" : "var(--axis)"} strokeWidth={1} />
            <text x={L - 6} y={y + 4} textAnchor="end">{fmt((max * k) / 4)}</text>
          </g>
        );
      })}
    </>
  );
}

export function ColumnChart({ labels, series, bucket, fmt = compact }: { labels: string[]; series: Series[]; bucket: "hour" | "day"; fmt?: Fmt }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const tip = useTooltip();
  if (!labels.length) return <div ref={ref} className="chart"><Empty /></div>;
  const W = Math.max(width, 280), H = 190, L = 44, R = 8, T = 10, B = 24;
  const totals = labels.map((_, i) => series.reduce((s, se) => s + (se.values[i] || 0), 0));
  const max = niceMax(Math.max(...totals)), plotH = H - T - B, band = (W - L - R) / labels.length;
  const bw = Math.max(2, Math.min(24, band * 0.6));
  const every = Math.ceil(labels.length / Math.max(1, Math.floor((W - L) / 64)));
  return (
    <div ref={ref} className="chart">
      {series.length > 1 && <Legend items={series} kind="rect" />}
      <svg viewBox={`0 0 ${W} ${H}`} height={H} role="img">
        <Grid {...{ L, R, T, plotH, W, max, fmt }} />
        {labels.map((lab, i) => {
          const cx = L + band * i + band / 2;
          let y = T + plotH;
          const rows: TipRow[] = series.map((se) => ({ color: se.color, value: fmt(se.values[i] || 0), label: se.name }));
          return (
            <g key={lab}>
              {series.map((se, si) => {
                const v = se.values[i] || 0;
                if (!v) return null;
                const h = Math.max(1, (plotH * v) / max), gap = si > 0 ? 2 : 0, yTop = y - h;
                const top = series.slice(si + 1).every((s2) => !(s2.values[i] || 0));
                y = yTop;
                return top
                  ? <path key={se.name} d={roundedTop(cx - bw / 2, yTop, bw, h - gap, 4)} fill={`var(${se.color})`} />
                  : <rect key={se.name} x={cx - bw / 2} y={yTop} width={bw} height={Math.max(0, h - gap)} fill={`var(${se.color})`} />;
              })}
              {i % every === 0 && <text x={cx} y={H - 6} textAnchor="middle">{shortLabel(lab, bucket)}</text>}
              <rect x={L + band * i} y={T} width={band} height={plotH} fill="transparent" tabIndex={0}
                    onPointerMove={(e) => tip.show(e.clientX, e.clientY, lab, rows)} onPointerLeave={tip.hide}
                    onFocus={(e) => { const r = e.currentTarget.getBoundingClientRect(); tip.show(r.x + r.width / 2, r.y, lab, rows); }}
                    onBlur={tip.hide} />
            </g>
          );
        })}
      </svg>
      <TableView head={["구간", ...series.map((s) => s.name)]}
                 rows={labels.map((l, i) => [l, ...series.map((s) => fmt(s.values[i] || 0))])} />
    </div>
  );
}

export function LineChart({ labels, series, bucket, fmt = compact }: { labels: string[]; series: Series[]; bucket: "hour" | "day"; fmt?: Fmt }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const tip = useTooltip();
  const svgRef = useRef<SVGSVGElement>(null);
  const [cross, setCross] = useState<number | null>(null);
  if (!labels.length) return <div ref={ref} className="chart"><Empty /></div>;
  const W = Math.max(width, 280), H = 190, L = 48, R = 56, T = 10, B = 24;
  const all = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  const max = niceMax(Math.max(1, ...all)), plotH = H - T - B, plotW = W - L - R;
  const xAt = (i: number) => L + (labels.length === 1 ? plotW / 2 : (plotW * i) / (labels.length - 1));
  const yAt = (v: number) => T + plotH - (plotH * v) / max;
  const every = Math.ceil(labels.length / Math.max(1, Math.floor(plotW / 64)));
  const ends = series.map((se) => {
    let last = se.values.length - 1;
    while (last >= 0 && se.values[last] == null) last--;
    return last >= 0 ? { x: xAt(last), y: yAt(se.values[last]!), v: se.values[last]!, color: se.color } : null;
  }).filter((e): e is NonNullable<typeof e> => e != null);
  // 끝 값 라벨은 서로 겹치지 않을 때만 (겹치면 범례·툴팁에 맡긴다)
  const apart = ends.length < 2 || Math.abs(ends[0].y - ends[1].y) >= 14;
  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const r = svgRef.current!.getBoundingClientRect();
    const px = (e.clientX - r.left) * (W / r.width);
    const i = Math.max(0, Math.min(labels.length - 1, Math.round((px - L) / (plotW / Math.max(1, labels.length - 1)))));
    setCross(i);
    tip.show(e.clientX, e.clientY, labels[i], series.map((se) => ({ color: se.color, value: fmt(se.values[i]), label: se.name })));
  };
  return (
    <div ref={ref} className="chart">
      <Legend items={series} kind="line" />
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} height={H} role="img">
        <Grid {...{ L, R, T, plotH, W, max, fmt }} />
        {labels.map((lab, i) => (i % every === 0
          ? <text key={lab} x={xAt(i)} y={H - 6} textAnchor="middle">{shortLabel(lab, bucket)}</text> : null))}
        {series.map((se) => {
          let d = "", pen = false;
          se.values.forEach((v, i) => {
            if (v == null) { pen = false; return; }
            d += (pen ? "L" : "M") + xAt(i) + "," + yAt(v);
            pen = true;
          });
          return <path key={se.name} d={d} fill="none" stroke={`var(${se.color})`} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />;
        })}
        {ends.map((e) => (
          <g key={e.color}>
            <circle cx={e.x} cy={e.y} r={4} fill={`var(${e.color})`} stroke="var(--surface)" strokeWidth={2} />
            {apart && <text x={e.x + 8} y={e.y + 4} className="val">{fmt(e.v)}</text>}
          </g>
        ))}
        {cross != null && <line x1={xAt(cross)} x2={xAt(cross)} y1={T} y2={T + plotH} stroke="var(--axis)" strokeWidth={1} />}
        <rect x={L} y={T} width={plotW} height={plotH} fill="transparent" onPointerMove={onMove}
              onPointerLeave={() => { setCross(null); tip.hide(); }} />
      </svg>
      <TableView head={["구간", ...series.map((s) => s.name)]}
                 rows={labels.map((l, i) => [l, ...series.map((s) => fmt(s.values[i]))])} />
    </div>
  );
}

export interface BarItem { label: string; value: number; tip?: TipRow[] }

export function HBarChart({ items, fmt = compact, empty = "기록이 없습니다" }: { items: BarItem[]; fmt?: Fmt; empty?: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const tip = useTooltip();
  if (!items.length) return <div ref={ref} className="chart"><Empty text={empty} /></div>;
  const W = Math.max(width, 280), rowH = 28, LBL = Math.min(170, W * 0.38), R = 52;
  const H = items.length * rowH + 4, max = niceMax(Math.max(...items.map((i) => i.value))), plotW = W - LBL - R;
  return (
    <div ref={ref} className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} height={H} role="img">
        <line x1={LBL} x2={LBL} y1={0} y2={H} stroke="var(--axis)" strokeWidth={1} />
        {items.map((it, i) => {
          const y = i * rowH + (rowH - 16) / 2, w = Math.max(2, (plotW * it.value) / max);
          return (
            <g key={it.label}>
              <text x={LBL - 8} y={y + 12} textAnchor="end" className="lbl">
                {it.label.length > 22 ? it.label.slice(0, 21) + "…" : it.label}<title>{it.label}</title>
              </text>
              <path d={roundedRight(LBL, y, w, 16, 4)} fill="var(--series-1)" />
              <text x={LBL + w + 6} y={y + 12} className="val">{fmt(it.value)}</text>
              <rect x={0} y={i * rowH} width={W} height={rowH} fill="transparent" tabIndex={0}
                    onPointerMove={(e) => tip.show(e.clientX, e.clientY, it.label, it.tip || [{ value: fmt(it.value), label: "" }])}
                    onPointerLeave={tip.hide} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

interface Span { kind: "llm" | "tool"; s: number; e: number; label: string; err: string | null; tip: TipRow[] }

export function Waterfall({ detail }: { detail: RunDetail }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const tip = useTooltip();
  const run = detail.run, t0 = run.started_at;
  // 시간축 끝 = 실행 종료와 모든 호출 종료 중 가장 늦은 시각 (막대가 카드 밖으로 넘치지 않게)
  const t1 = Math.max(t0, run.ended_at || 0, ...detail.tool_calls.map((x) => x.ended_at), ...detail.llm_calls.map((x) => x.ended_at));
  const span = Math.max(0.001, t1 - t0);
  const rows: Span[] = [
    ...detail.llm_calls.map((c: LLMCall): Span => ({
      kind: "llm", s: c.started_at, e: c.ended_at, err: c.error,
      label: `LLM ${c.seq}` + (c.attempt ? ` (재시도 ${c.attempt})` : ""),
      tip: [{ value: ms(c.latency_ms), label: "소요" }, { value: compact(c.input_tokens), label: "입력 토큰" },
            { value: compact(c.output_tokens), label: "출력 토큰" },
            { value: c.error ? "오류" : c.stop_reason || "", label: c.error ? c.error.slice(0, 80) : "종료 사유" }],
    })),
    ...detail.tool_calls.map((c: ToolCallRow): Span => ({
      kind: "tool", s: c.started_at, e: c.ended_at, err: c.is_error ? "오류" : null, label: c.name,
      tip: [{ value: ms(c.latency_ms), label: "소요" }, { value: c.status_text || "", label: "" },
            { value: compact(c.result_chars), label: "결과 글자 수" }],
    })),
  ].sort((a, b) => a.s - b.s);
  const W = Math.max(width, 320), LBL = Math.min(190, W * 0.36), R = 56, rowH = 24, T = 18;
  const H = T + rows.length * rowH + 4, plotW = W - LBL - R;
  const xAt = (t: number) => LBL + (plotW * (t - t0)) / span;
  return (
    <div ref={ref} className="chart">
      <Legend items={[{ name: "LLM 호출", color: "--series-1" }, { name: "도구 호출", color: "--series-2" }]} kind="rect" />
      <svg viewBox={`0 0 ${W} ${H}`} height={H} role="img">
        {[0, 1, 2, 3, 4].map((k) => {
          const x = LBL + (plotW * k) / 4;
          return (
            <g key={k}>
              <line x1={x} x2={x} y1={T - 4} y2={H} stroke="var(--grid)" strokeWidth={1} />
              <text x={x} y={11} textAnchor="middle">{ms((span * 1000 * k) / 4)}</text>
            </g>
          );
        })}
        {rows.map((r, i) => {
          const y = T + i * rowH, x = xAt(r.s), w = Math.max(3, xAt(r.e) - x);
          return (
            <g key={i}>
              <text x={LBL - 8} y={y + 15} textAnchor="end" className="lbl">
                {(r.err ? "⚠ " : "") + (r.label.length > 24 ? r.label.slice(0, 23) + "…" : r.label)}
              </text>
              <rect x={x} y={y + 5} width={w} height={14} rx={Math.min(4, w / 2)} fill={`var(${r.kind === "llm" ? "--series-1" : "--series-2"})`} />
              <text x={x + w + 6} y={y + 16} className="val">{ms((r.e - r.s) * 1000)}</text>
              <rect x={0} y={y} width={W} height={rowH} fill="transparent"
                    onPointerMove={(e) => tip.show(e.clientX, e.clientY, r.label + (r.err ? " — 오류" : ""), r.tip)}
                    onPointerLeave={tip.hide} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}
