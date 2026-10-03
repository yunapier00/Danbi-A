const nf = new Intl.NumberFormat("ko-KR");

export const num = (v: number | null | undefined) => (v == null ? "–" : nf.format(v));

export function compact(v: number | null | undefined): string {
  if (v == null) return "–";
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M";
  if (a >= 1e4) return (v / 1e3).toFixed(a >= 1e5 ? 0 : 1) + "K";
  return nf.format(Math.round(v));
}

/** 밀리초 → "850ms" / "1.2초". 0은 단위 없이 (축 눈금에서 단위가 섞이지 않게). */
export function ms(v: number | null | undefined): string {
  if (v == null) return "–";
  if (v === 0) return "0";
  return v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + "초" : Math.round(v) + "ms";
}

export const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) + "%" : "–");

export function when(ts: number | null | undefined): string {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleString("ko-KR", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function niceMax(v: number): number {
  if (!v || v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}
