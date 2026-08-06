import { useEffect, useMemo, useState } from "react";
import "../styles/sentreports.css";

/**
 * Admin > 리서치 wiki 뷰어 (2026-08-06 사용자 지시). **조회 전용**.
 *
 * 자산군별로 09_Research_Synthesis 원문 + 그 자산군 claim **전량** + 원본 링크.
 *
 * 왜 전량인가: 09 는 자산군당 salience 상위 N(§2 8 / §4 12 / §5 6)만 싣는다.
 * 2026-07 환율(FX)은 111건 중 12건만 실려 엔캐리 청산 claim(45위)이 통째로
 * 빠졌고, 09 가 debate primary source 라 시장 코멘트에도 그 주제가 없었다.
 * **무엇이 잘렸는지** 눈으로 확인할 수 있어야 해서 컷된 것까지 보여준다.
 */
type Source = {
  title: string; date: string; broker: string;
  lane: string; url: string; attachments: string;
};
type ClaimRow = {
  claim_id: string; text: string; stance: string; direction: string;
  horizon: string; confidence: number; salience: number;
  source_type: string; broker: string;
  adopted: boolean; rank: number; sources: Source[];
  // claim_text 는 "한 줄 요약(≤180자)" — 원인분석은 아래에 있다.
  rationale: string; risk_factor: string; causal_chain: string[];
};
type Wiki = {
  period: string; asset: string; assets: string[];
  page_md: string; page_generated_at: string; page_stale: boolean;
  claims_total: number; adopted_total: number; claims: ClaimRow[];
};

const STANCE_COLOR: Record<string, string> = {
  bullish: "#1e7b45", bearish: "#b42318", neutral: "#667085", mixed: "#8a5a00",
};

function SourceLinks({ sources }: { sources: Source[] }) {
  if (!sources.length) return <span className="ref">원본 연결 없음</span>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {sources.map((s, i) => (
        <div key={i} style={{ fontSize: 11, color: "#667085" }}>
          <span style={{ opacity: 0.7 }}>{s.date}</span>{" "}
          <strong>{s.broker}</strong>{" "}
          {s.url ? (
            // naver_research — 네이버 금융 리서치 페이지로 바로 이동
            <a href={s.url} target="_blank" rel="noreferrer">{s.title} ↗</a>
          ) : (
            // broker_mail — URL 부재. 아웃룩에서 제목으로 찾도록 메타만 노출.
            <span title={s.attachments ? `첨부: ${s.attachments}` : "Outlook 메일 원본"}>
              {s.title}
              <span style={{ opacity: 0.6 }}>
                {s.attachments ? ` (첨부: ${s.attachments})` : " (메일)"}
              </span>
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export default function AdminResearchWikiPanel({ period }: { period: string }) {
  const [asset, setAsset] = useState("");
  const [data, setData] = useState<Wiki | null>(null);
  const [err, setErr] = useState("");
  const [onlyCut, setOnlyCut] = useState(false);
  const [q, setQ] = useState("");
  const [showPage, setShowPage] = useState(false);

  // 월간 기간만 09 가 존재한다 (분기·TD 는 월 페이지의 합성이라 별도 파일이 없음).
  const monthly = /^\d{4}-(0[1-9]|1[0-2])$/.test(period);

  // ★ 응답으로 asset 을 되쓰면 안 된다 (2026-08-06 fix).
  //   종전: 응답마다 무조건 setAsset(d.asset) + effect deps 에 asset →
//   사용자가 국내주식을 고르면 요청 B 가 나가는데, 먼저 나간 해외주식 요청 A 가
  //   **늦게 도착해** setAsset("해외주식") 으로 되돌리고 → effect 재실행 → 왕복.
  //   자산군 셀렉트가 해외주식↔국내주식 사이를 계속 오갔다(684건 payload 라 응답이
  //   느려 경쟁 구간이 넓었다).
  //   해결 ① 늦게 온 응답 폐기(stale 가드) ② asset 은 **비었거나 목록에 없을 때만**
  //   서버 값으로 채운다 — 유효한 사용자 선택은 절대 덮지 않는다.
  useEffect(() => {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(period)) { setData(null); return; }
    let stale = false;
    setErr("");
    const qs = new URLSearchParams({ period, ...(asset ? { asset } : {}) });
    fetch(`/api/admin/research-wiki?${qs}`)
      .then((r) => r.json())
      .then((d: Wiki) => {
        if (stale) return;
        setData(d);
        if (d.asset && (!asset || !d.assets.includes(asset))) setAsset(d.asset);
      })
      .catch((e) => { if (!stale) setErr(String(e)); });
    return () => { stale = true; };
  }, [period, asset]);

  const rows = useMemo(() => {
    const all = data?.claims ?? [];
    const needle = q.trim();
    return all.filter((r) =>
      (!onlyCut || !r.adopted) &&
      // 검색은 논거·인과까지 훑는다 — 요약 한 줄에는 없어도 근거에 있는 경우가 많다.
      (!needle || r.text.includes(needle) || r.rationale.includes(needle) ||
        r.risk_factor.includes(needle) ||
        r.causal_chain.some((s) => s.includes(needle)) ||
        r.sources.some((s) => s.title.includes(needle) || s.broker.includes(needle))));
  }, [data, onlyCut, q]);

  if (!monthly) {
    return (
      <div className="sra-empty">
        리서치 wiki 는 <strong>월간 기간</strong>만 조회할 수 있습니다
        (09_Research_Synthesis 가 월 단위 산출물). 유형을 “월간”으로 바꿔주세요.
      </div>
    );
  }
  if (err) return <div className="sra-empty">✖ {err}</div>;
  if (!data) return <div className="sra-empty">로드 중…</div>;
  if (!data.assets.length) {
    return <div className="sra-empty">{period} 리서치 claim 이 없습니다.</div>;
  }

  return (
    <div className="sra-genout">
      <div className="gh">
        리서치 wiki · {period}
        <span className="ref">
          09 생성 {data.page_generated_at || "없음"}
        </span>
        {data.page_stale && (
          <span className="ref" style={{ color: "#b42318" }}>
            ⚠ claims 가 09 보다 최신 — 다음 daily_update 캐치업에서 재생성됩니다
          </span>
        )}
      </div>

      <div className="sra-gen" style={{ marginBottom: 10 }}>
        <span className="lab">자산군</span>
        <select value={asset} onChange={(e) => setAsset(e.target.value)}>
          {data.assets.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <span className="ref">
          claim {data.claims_total}건 중 <strong>09 채택 {data.adopted_total}건</strong>
          {" "}({data.claims_total ? Math.round(data.adopted_total / data.claims_total * 100) : 0}%)
        </span>
        <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 4 }}>
          <input type="checkbox" checked={onlyCut}
            onChange={(e) => setOnlyCut(e.target.checked)} />
          컷된 것만
        </label>
        <input value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="claim·리포트 제목 검색 (예: 엔캐리)"
          style={{ minWidth: 220 }} />
        <button type="button" onClick={() => setShowPage((v) => !v)}>
          09 원문 {showPage ? "접기" : "보기"}
        </button>
      </div>

      {showPage && (
        <pre style={{
          fontSize: 12, lineHeight: 1.6, whiteSpace: "pre-wrap",
          background: "#f7f8fa", padding: 12, borderRadius: 6,
          maxHeight: 420, overflowY: "auto", marginBottom: 12,
        }}>{data.page_md || "(09 페이지 없음)"}</pre>
      )}

      <div style={{ overflowX: "auto" }}>
        <table className="afp-table" style={{ fontSize: 12, width: "100%" }}>
          <thead>
            <tr>
              <th style={{ width: 42 }}>순위</th>
              <th style={{ width: 52 }}>sal</th>
              <th style={{ width: 54 }}>09</th>
              <th style={{ width: 64 }}>stance</th>
              <th>claim</th>
              <th style={{ width: 300 }}>원본</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.claim_id} style={{ background: r.adopted ? "#f2f9f4" : undefined }}>
                <td style={{ textAlign: "right", color: "#667085" }}>{r.rank}</td>
                <td style={{ textAlign: "right" }}>{r.salience.toFixed(2)}</td>
                <td style={{ textAlign: "center" }}>
                  {r.adopted
                    ? <span style={{ color: "#1e7b45", fontWeight: 600 }}>★채택</span>
                    : <span style={{ color: "#b42318", opacity: 0.75 }}>컷</span>}
                </td>
                <td style={{ color: STANCE_COLOR[r.stance] ?? "#667085" }}>
                  {r.stance || "—"}
                  <div style={{ fontSize: 10, opacity: 0.7 }}>{r.horizon}</div>
                </td>
                <td style={{ lineHeight: 1.5 }}>
                  {r.text}
                  {r.source_type === "monygeek" && (
                    <span className="ref" style={{ marginLeft: 6 }}>monygeek</span>
                  )}
                  {/* claim_text 는 한 줄 요약이라 "사건 나열"로만 보인다.
                      실제 인과·리스크는 아래 펼침에 있다 (2026-08-06). */}
                  {(r.rationale || r.causal_chain.length > 0 || r.risk_factor) && (
                    <details style={{ marginTop: 4 }}>
                      <summary style={{ cursor: "pointer", fontSize: 11, color: "#667085" }}>
                        논거·인과{r.causal_chain.length ? ` (${r.causal_chain.length}단계)` : ""}
                      </summary>
                      <div style={{ fontSize: 11, lineHeight: 1.65, paddingTop: 4 }}>
                        {r.rationale && (
                          <div style={{ marginBottom: 4 }}>
                            <strong>논거</strong> {r.rationale}
                          </div>
                        )}
                        {r.causal_chain.map((step, i) => (
                          <div key={i} style={{ color: "#1a4d8f" }}>· {step}</div>
                        ))}
                        {r.risk_factor && (
                          <div style={{ marginTop: 4, color: "#8a5a00" }}>
                            <strong>리스크</strong> {r.risk_factor}
                          </div>
                        )}
                      </div>
                    </details>
                  )}
                </td>
                <td><SourceLinks sources={r.sources} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="sra-empty">조건에 맞는 claim 이 없습니다.</div>}
      </div>
    </div>
  );
}
