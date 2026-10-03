import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

// ---------- 상태 표시 (색만으로 구분하지 않게 아이콘 + 문구) ----------
const STATUS: Record<string, [string, string, string]> = {
  ok: ["정상", "good", "●"], error: ["오류", "critical", "▲"], limit: ["상한 도달", "warning", "■"],
  aborted: ["중단", "serious", "◆"], refused: ["거부", "serious", "◆"], max_tokens: ["길이 초과", "warning", "■"],
  running: ["진행 중", "muted", "○"],
};
export function StatusBadge({ status }: { status: string }) {
  const [label, tone, ico] = STATUS[status] || [status, "muted", "○"];
  return (
    <span className="status">
      <span className="ico" style={{ color: `var(--${tone})` }} aria-hidden="true">{ico}</span>{label}
    </span>
  );
}
export const CHANNEL: Record<string, string> = { web: "웹", kakao: "카카오", cli: "CLI", eval: "평가" };

// ---------- 툴팁 (화면에 하나) ----------
export interface TipRow { value: string; label: string; color?: string }
interface TipState { x: number; y: number; title?: string; rows: TipRow[] }
const TipContext = createContext<{ show: (x: number, y: number, title: string | undefined, rows: TipRow[]) => void; hide: () => void }>({
  show: () => {}, hide: () => {},
});
export const useTooltip = () => useContext(TipContext);

export function TooltipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<TipState | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const show = useCallback((x: number, y: number, title: string | undefined, rows: TipRow[]) => setTip({ x, y, title, rows }), []);
  const hide = useCallback(() => setTip(null), []);
  const [pos, setPos] = useState({ left: 0, top: 0 });
  useEffect(() => {
    if (!tip || !box.current) return;
    const w = box.current.offsetWidth, h = box.current.offsetHeight;
    setPos({ left: Math.min(tip.x + 14, window.innerWidth - w - 8), top: Math.min(tip.y + 14, window.innerHeight - h - 8) });
  }, [tip]);
  return (
    <TipContext.Provider value={{ show, hide }}>
      {children}
      <div id="tooltip" ref={box} role="status" aria-live="polite"
           style={{ display: tip ? "block" : "none", left: pos.left, top: pos.top }}>
        {tip?.title && <div className="t-title">{tip.title}</div>}
        {tip?.rows.map((r, i) => (
          <div className="t-row" key={i}>
            {r.color && <span className="t-key" style={{ background: `var(${r.color})` }} />}
            <strong>{r.value}</strong><span className="muted">{r.label}</span>
          </div>
        ))}
      </div>
    </TipContext.Provider>
  );
}

/** 요소 너비를 따라가는 훅 (차트를 컨테이너 폭에 맞춘다). */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => setW(Math.round(entries[0].contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export function Legend({ items, kind }: { items: { name: string; color: string }[]; kind: "rect" | "line" }) {
  return (
    <div className="legend">
      {items.map((s) => (
        <span className="key" key={s.name}><span className={kind} style={{ background: `var(${s.color})` }} />{s.name}</span>
      ))}
    </div>
  );
}

export function TableView({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <details className="tableview">
      <summary>표로 보기</summary>
      <table>
        <thead><tr>{head.map((h, i) => <th key={h} className={i ? "num" : ""}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, i) => <td key={i} className={i ? "num" : ""}>{c}</td>)}</tr>)}</tbody>
      </table>
    </details>
  );
}
