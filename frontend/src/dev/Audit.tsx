import { useEffect, useState } from "react";
import { num, when } from "../lib/format";
import type { Api, AuditResponse } from "./api";

export function Audit({ api, tick, onError }: { api: Api; tick: number; onError: (e: unknown) => void }) {
  const [d, setD] = useState<AuditResponse | null>(null);
  useEffect(() => {
    let alive = true;
    api.json<AuditResponse>("/api/admin/audit?limit=300").then((x) => alive && setD(x)).catch(onError);
    return () => { alive = false; };
  }, [api, tick, onError]);
  if (!d) return null;
  return (
    <section className="audit">
      <div className="banner">
        {d.verify.ok ? (
          <span className="status"><span className="ico" style={{ color: "var(--good)" }}>●</span>
            해시 체인 무결성 확인 — 검증 시점까지 {num(d.verify.rows)}행 모두 일치 (이번 검증 기록은 다음 검증부터 포함)</span>
        ) : (
          <span className="status"><span className="ico" style={{ color: "var(--critical)" }}>▲</span>
            무결성 경고 — {d.verify.broken_at}번 행부터 해시가 맞지 않습니다 (수정·삭제 의심)</span>
        )}
      </div>
      <div className="card">
        <table>
          <thead><tr><th>시각</th><th>행위자</th><th>동작</th><th>대상</th><th>상세</th><th>클라이언트</th><th>해시</th></tr></thead>
          <tbody>{d.items.map((a) => (
            <tr key={a.id}><td>{when(a.at)}</td><td>{a.actor}</td><td>{a.action}</td><td>{a.target || ""}</td>
              <td className="muted">{a.detail && a.detail !== "{}" ? a.detail : ""}</td><td>{a.client || ""}</td>
              <td className="muted" title={a.hash}>{a.hash.slice(0, 10)}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}
