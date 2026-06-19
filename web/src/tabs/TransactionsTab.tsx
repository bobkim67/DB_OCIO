import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  useFxPosition,
  useSecurities,
  useSecurityReturn,
  useTransactions,
  useWeightHistory,
  useAssetClassReturn,
} from "../hooks/useTransactions";
import { useFunds } from "../hooks/useFunds";
import WeightAreaChart from "../components/charts/WeightAreaChart";
import FxPositionChart from "../components/charts/FxPositionChart";
import SecurityReturnChart from "../components/charts/SecurityReturnChart";
import type { WeightHistoryLevel } from "../api/endpoints";

interface Props {
  fundCode: string;
}

// 로컬 타임존 기준 YYYY-MM-DD (toISOString UTC 보정 회피)
function fmtLocal(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function monthsAgo(n: number): Date {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return d;
}
function startOfMonth(): Date {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1);
}
function startOfYear(): Date {
  const d = new Date();
  return new Date(d.getFullYear(), 0, 1);
}

type TxnPreset = "MTD" | "1M" | "3M" | "6M" | "YTD" | "since" | "custom";

const TXN_PRESETS: { key: TxnPreset; label: string }[] = [
  { key: "MTD", label: "당월(MTD)" },
  { key: "1M", label: "직전 1개월" },
  { key: "3M", label: "직전 3개월" },
  { key: "6M", label: "직전 6개월" },
  { key: "YTD", label: "연초이후" },
  { key: "since", label: "설정후" },
  { key: "custom", label: "직접 지정" },
];

const BUY_COLOR = "#EF553B"; // 매수 빨강
const SELL_COLOR = "#636EFA"; // 매도 파랑
const NEUTRAL_COLOR = "#6b7280"; // 기타(코드 없음) 회색

const sideColor = (side: string) =>
  side.includes("매수") || side.includes("발행")
    ? BUY_COLOR
    : side.includes("매도") || side.includes("환매")
      ? SELL_COLOR
      : NEUTRAL_COLOR;

// 자산군 정렬 순서 (거래내역 asset_class 값 기준). 미정의는 뒤로(99).
const ASSET_ORDER: Record<string, number> = {
  국내주식: 0, 해외주식: 1, 국내채권: 2, 해외채권: 3,
  대체투자: 4, "금·대체": 4, FX: 5, 모펀드: 6, 유동성: 7,
};

export default function TransactionsTab({ fundCode }: Props) {
  const today = fmtLocal(new Date());

  // 설정일(inception) — 펀드 목록(useFunds)에서 해당 펀드 메타로 조회. "YYYY-MM-DD".
  const fundsQ = useFunds();
  const inceptionDate = useMemo(
    () => fundsQ.data?.data.find((f) => f.code === fundCode)?.inception ?? null,
    [fundsQ.data, fundCode],
  );

  // ---- 거래내역 기간 ----
  const [preset, setPreset] = useState<TxnPreset>("MTD");
  const [customStart, setCustomStart] = useState<string>(fmtLocal(startOfMonth()));
  const [customEnd, setCustomEnd] = useState<string>(today);

  const { txnStart, txnEnd } = useMemo(() => {
    switch (preset) {
      case "MTD":
        return { txnStart: fmtLocal(startOfMonth()), txnEnd: today };
      case "1M":
        return { txnStart: fmtLocal(monthsAgo(1)), txnEnd: today };
      case "3M":
        return { txnStart: fmtLocal(monthsAgo(3)), txnEnd: today };
      case "6M":
        return { txnStart: fmtLocal(monthsAgo(6)), txnEnd: today };
      case "YTD":
        return { txnStart: fmtLocal(startOfYear()), txnEnd: today };
      case "since":
        // 설정일~현재. inception 미로드 시 매우 이른 날짜로 fallback(전체 포함).
        return { txnStart: inceptionDate ?? "2000-01-01", txnEnd: today };
      case "custom":
        return { txnStart: customStart, txnEnd: customEnd };
    }
  }, [preset, customStart, customEnd, today, inceptionDate]);

  const txnQ = useTransactions(fundCode, txnStart, txnEnd);

  // ---- 마스터 토글 (자산군↔종목) + 마스터 기간: 거래내역·비중추이·수익률 차트 공통 ----
  const [level, setLevel] = useState<WeightHistoryLevel>("asset");

  // ---- 영역차트: 기간은 마스터(거래내역 preset)와 공유 → chartStart = txnStart ----
  const [topNInput, setTopNInput] = useState<string>(""); // "" = 전체
  const chartStart = txnStart;

  const whQ = useWeightHistory(fundCode, chartStart, level);

  // ---- 세부내역 표 높이: 기본=요약 표 높이, 펼치기=전체 높이 ----
  const summaryBoxRef = useRef<HTMLDivElement>(null);
  const detailTableRef = useRef<HTMLTableElement>(null);
  const [summaryH, setSummaryH] = useState(0);
  const [detailFullH, setDetailFullH] = useState(0);
  const [detailExpanded, setDetailExpanded] = useState(false);

  const topN = useMemo(() => {
    const n = parseInt(topNInput, 10);
    return Number.isFinite(n) && n > 0 ? n : 0; // 0 = 전체
  }, [topNInput]);

  // ---- FX 포지션 (달러선물) ----
  const fxQ = useFxPosition(fundCode, chartStart);

  // ---- 종목별 수익률 ---- (start=chartStart → 편입이력(현재 미보유) 종목 하단 포함)
  const secQ = useSecurities(fundCode, chartStart);
  const priceItems = useMemo(
    () => (secQ.data?.items ?? []).filter((it) => it.has_price),
    [secQ.data],
  );
  const currentItems = useMemo(
    () => priceItems.filter((it) => it.currently_held !== false), [priceItems]);
  const pastItems = useMemo(
    () => priceItems.filter((it) => it.currently_held === false), [priceItems]);
  // 수익률 차트 markup(구간 %변화율 측정) 모드 토글
  const [retMarkup, setRetMarkup] = useState(false);
  const [selItemCd, setSelItemCd] = useState<string>("");
  // 펀드 변경/목록 로드 시 비중 최상위 종목 자동 선택
  useEffect(() => {
    if (priceItems.length && !priceItems.some((it) => it.item_cd === selItemCd)) {
      const top = priceItems.reduce((a, b) => (b.weight > a.weight ? b : a));
      setSelItemCd(top.item_cd);
    }
    if (!priceItems.length) setSelItemCd("");
  }, [priceItems, selItemCd]);
  const selItem = priceItems.find((it) => it.item_cd === selItemCd);
  const secRetQ = useSecurityReturn(
    fundCode, selItemCd, selItem?.item_nm ?? "", chartStart, today,
  );

  // ---- 자산군 수익률 (자산군 모드): 일별 비중×종목가격 바스켓 지수 ----
  const assetKeys = useMemo(
    () => (level === "asset" ? (whQ.data?.keys ?? []) : []).filter((k) => k !== "유동성"),
    [level, whQ.data],
  );
  const [selAsset, setSelAsset] = useState<string>("");
  useEffect(() => {
    if (assetKeys.length && !assetKeys.includes(selAsset)) setSelAsset(assetKeys[0]);
    if (!assetKeys.length && level === "asset") setSelAsset("");
  }, [assetKeys, selAsset, level]);
  const assetRetQ = useAssetClassReturn(
    fundCode, level === "asset" ? selAsset : "", chartStart, today,
  );

  // ---- 거래내역 집계/정렬 ----
  const txnRows = txnQ.data?.rows ?? [];
  const sortedRows = useMemo(
    () =>
      [...txnRows].sort((a, b) => {
        if (a.date !== b.date) return b.date < a.date ? -1 : 1; // 최신 우선
        if (a.fund_code !== b.fund_code) return a.fund_code < b.fund_code ? -1 : 1;
        return a.item_nm < b.item_nm ? -1 : 1;
      }),
    [txnRows],
  );
  const { buySum, sellSum } = useMemo(() => {
    let buy = 0, sell = 0;
    for (const r of txnRows) {
      if (r.side === "매수") buy += r.amount_eok;
      else if (r.side === "매도") sell += r.amount_eok;
    }
    return { buySum: buy, sellSum: sell };
  }, [txnRows]);

  // 종목별/자산군별 매수·매도·순매수 (기간 합계) — 마스터 토글 기준.
  // 합계 의미는 위 한 줄 요약과 동일(매수/매도만, BA정산·환전 제외)하여 총계가 일치한다.
  // 정렬: 자산군 순서 → 자산군 내 순매수 내림차순.
  const txnSummary = useMemo(() => {
    const map = new Map<string, { asset: string; buy: number; sell: number }>();
    for (const r of txnRows) {
      const key = level === "asset" ? r.asset_class : r.item_nm;
      const cur = map.get(key) ?? { asset: r.asset_class, buy: 0, sell: 0 };
      if (r.side === "매수") cur.buy += r.amount_eok;
      else if (r.side === "매도") cur.sell += r.amount_eok;
      map.set(key, cur);
    }
    return [...map.entries()]
      .map(([key, v]) => ({ key, asset: v.asset, buy: v.buy, sell: v.sell, net: v.buy - v.sell }))
      .filter((g) => g.buy !== 0 || g.sell !== 0)
      .sort((a, b) => {
        const oa = ASSET_ORDER[a.asset] ?? 99;
        const ob = ASSET_ORDER[b.asset] ?? 99;
        if (oa !== ob) return oa - ob;
        return b.net - a.net; // 자산군 내 순매수 내림차순
      });
  }, [txnRows, level]);

  // 요약 표 높이(좌) + 세부내역 표 전체 높이(우) 측정 — 데이터 변경 시 재측정.
  useLayoutEffect(() => {
    if (summaryBoxRef.current) setSummaryH(summaryBoxRef.current.offsetHeight);
    if (detailTableRef.current) setDetailFullH(detailTableRef.current.offsetHeight);
  }, [txnSummary, sortedRows, level]);

  const isFofTxn = txnQ.data?.lookthrough_applied ?? false;
  const showFundCol = isFofTxn;
  const fmtD = (d: string) =>
    d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : d;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* ============ 마스터 컨트롤: 기준(자산군↔종목) + 기간 (공통 적용) ============ */}
      <div
        style={{
          display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
          padding: "8px 10px", background: "#f9fafb",
          border: "1px solid #e5e7eb", borderRadius: 6,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: "#111827" }}>기준</span>
        <div style={{ display: "inline-flex", border: "1px solid #d1d5db", borderRadius: 4, overflow: "hidden" }}>
          {(["asset", "security"] as WeightHistoryLevel[]).map((lv) => (
            <button
              key={lv}
              onClick={() => setLevel(lv)}
              style={{
                fontSize: 12, padding: "5px 14px", border: "none",
                background: level === lv ? "#2563eb" : "#fff",
                color: level === lv ? "#fff" : "#374151", cursor: "pointer",
              }}
            >
              {lv === "asset" ? "자산군 기준" : "종목 기준"}
            </button>
          ))}
        </div>

        <span style={{ width: 1, height: 20, background: "#e5e7eb", margin: "0 4px" }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: "#111827" }}>기간</span>
        {TXN_PRESETS.map((p) => (
          <label
            key={p.key}
            style={{
              fontSize: 12, padding: "4px 10px",
              border: "1px solid #e5e7eb", borderRadius: 4,
              background: preset === p.key ? "#eff6ff" : "#fff", cursor: "pointer",
            }}
          >
            <input
              type="radio"
              name="txn-preset"
              checked={preset === p.key}
              onChange={() => setPreset(p.key)}
              style={{ marginRight: 4 }}
            />
            {p.label}
          </label>
        ))}
        {preset === "custom" && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12 }}>
            <input
              type="date" value={customStart} max={customEnd}
              onChange={(e) => setCustomStart(e.target.value)}
              style={{ fontSize: 12, padding: "3px 6px" }}
            />
            ~
            <input
              type="date" value={customEnd} min={customStart}
              onChange={(e) => setCustomEnd(e.target.value)}
              style={{ fontSize: 12, padding: "3px 6px" }}
            />
          </span>
        )}
      </div>

      {/* ====================== 거래내역 ====================== */}
      <section>
        <h2 style={{ fontSize: 15, margin: "0 0 8px" }}>거래내역</h2>

        <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 6 }}>
          조회기간 {txnStart} ~ {txnEnd}
          {isFofTxn && (
            <span style={{ marginLeft: 8, color: "#7c3aed" }}>
              · FoF look-through: 자펀드 {(txnQ.data?.funds_queried ?? []).join(", ")} 거래 표시
            </span>
          )}
          <span style={{ marginLeft: 8 }}>
            · 매수 {buySum.toFixed(1)}억 / 매도 {sellSum.toFixed(1)}억 / 순매수{" "}
            {(buySum - sellSum).toFixed(1)}억 ({txnRows.length}건)
          </span>
        </div>

        {txnQ.isLoading ? (
          <div style={{ padding: 12, color: "#6b7280" }}>로딩 중…</div>
        ) : sortedRows.length === 0 ? (
          <div style={{ padding: 12, color: "#6b7280" }}>해당 기간 거래내역 없음</div>
        ) : (
          <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
            {/* 좌: 종목별/자산군별 매수·매도·순매수 (기간 합계) — 자산군 순 → 순매수 내림차순 */}
            <div style={{ flex: "1 1 340px", minWidth: 0 }}>
              <div style={{ height: 26, display: "flex", alignItems: "center", fontSize: 13, fontWeight: 600, color: "#374151", marginBottom: 6 }}>
                {level === "asset" ? "자산군별" : "종목별"} 매수·매도·순매수
              </div>
              <div ref={summaryBoxRef} style={{ border: "1px solid #e5e7eb", borderRadius: 4, overflow: "hidden" }}>
                <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: "#f9fafb" }}>
                      <th style={{ ...thStyle, textAlign: "left" }}>자산군</th>
                      {level === "security" && (
                        <th style={{ ...thStyle, textAlign: "left" }}>종목명</th>
                      )}
                      <th style={{ ...thStyle, textAlign: "right" }}>매수(억)</th>
                      <th style={{ ...thStyle, textAlign: "right" }}>매도(억)</th>
                      <th style={{ ...thStyle, textAlign: "right" }}>순매수(억)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {txnSummary.map((g) => (
                      <tr key={g.key} style={{ borderTop: "1px solid #f3f4f6" }}>
                        <td style={{ ...tdStyle, textAlign: "left" }}>{g.asset}</td>
                        {level === "security" && (
                          <td style={{ ...tdStyle, textAlign: "left" }}>{g.key}</td>
                        )}
                        <td style={{ ...tdStyle, textAlign: "right", color: g.buy ? BUY_COLOR : "#9ca3af" }}>
                          {g.buy.toFixed(2)}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: g.sell ? SELL_COLOR : "#9ca3af" }}>
                          {g.sell.toFixed(2)}
                        </td>
                        <td style={{
                          ...tdStyle, textAlign: "right", fontWeight: 600,
                          color: g.net > 0 ? BUY_COLOR : g.net < 0 ? SELL_COLOR : "#9ca3af",
                        }}>
                          {g.net >= 0 ? "+" : ""}{g.net.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                    <tr style={{ borderTop: "2px solid #e5e7eb", background: "#fcfcfd" }}>
                      <td style={{ ...tdStyle, textAlign: "left", fontWeight: 600 }}
                          colSpan={level === "security" ? 2 : 1}>합계</td>
                      <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600, color: BUY_COLOR }}>
                        {buySum.toFixed(2)}
                      </td>
                      <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600, color: SELL_COLOR }}>
                        {sellSum.toFixed(2)}
                      </td>
                      <td style={{
                        ...tdStyle, textAlign: "right", fontWeight: 700,
                        color: buySum - sellSum >= 0 ? BUY_COLOR : SELL_COLOR,
                      }}>
                        {buySum - sellSum >= 0 ? "+" : ""}{(buySum - sellSum).toFixed(2)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* 우: 세부내역 (일별 거래 상세, 날짜 내림차순) — 자산군→종목명 순 */}
            <div style={{ flex: "2 1 460px", minWidth: 0 }}>
              <div style={{ height: 26, display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: "#374151" }}>
                  세부내역 ({sortedRows.length}건)
                </span>
                <button
                  onClick={() => setDetailExpanded((o) => !o)}
                  style={{
                    fontSize: 11, padding: "2px 8px", border: "1px solid #d1d5db",
                    borderRadius: 4, background: "#fff", color: "#374151", cursor: "pointer",
                  }}
                >
                  {detailExpanded ? "접기" : "펼치기"}
                </button>
              </div>
              <div style={{
                maxHeight: detailExpanded ? (detailFullH || undefined) : (summaryH || 420),
                overflow: "auto", border: "1px solid #e5e7eb", borderRadius: 4,
              }}>
                <table ref={detailTableRef} style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: "#f9fafb", position: "sticky", top: 0 }}>
                      <th style={thStyle}>날짜</th>
                      {showFundCol && <th style={thStyle}>펀드</th>}
                      <th style={thStyle}>자산군</th>
                      <th style={{ ...thStyle, textAlign: "left" }}>종목명</th>
                      <th style={thStyle}>매수/매도</th>
                      <th style={{ ...thStyle, textAlign: "right" }}>금액(억)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedRows.map((r, i) => (
                      <tr key={i} style={{ borderTop: "1px solid #f3f4f6" }}>
                        <td style={tdStyle}>{fmtD(r.date)}</td>
                        {showFundCol && <td style={tdStyle}>{r.fund_code}</td>}
                        <td style={tdStyle}>{r.asset_class}</td>
                        <td style={{ ...tdStyle, textAlign: "left" }}>{r.item_nm}</td>
                        <td style={{ ...tdStyle, color: sideColor(r.side) }}>
                          {r.side}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: sideColor(r.side) }}>
                          {r.amount_eok.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* ====================== 일별 비중 영역차트 ====================== */}
      <section>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <h2 style={{ fontSize: 15, margin: 0 }}>일별 비중 추이</h2>

          {/* 상위 N (종목 기준에서만) */}
          {level === "security" && (
            <label style={{ fontSize: 12, color: "#374151" }}>
              상위 N:&nbsp;
              <input
                type="number"
                min={1}
                placeholder="전체"
                value={topNInput}
                onChange={(e) => setTopNInput(e.target.value)}
                style={{ fontSize: 12, padding: "3px 6px", width: 64 }}
              />
              <span style={{ marginLeft: 4, color: "#9ca3af" }}>
                {topN > 0
                  ? `상위 ${topN}개 + 기타`
                  : `전체 ${whQ.data?.keys.length ?? 0}개`}
              </span>
            </label>
          )}
        </div>

        <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>
          {chartStart} ~ 현재
          <span style={{ marginLeft: 8, color: "#9ca3af" }}>
            · ▲ 순매수 / ▼ 순매도 (밴드 상단, 일자·{level === "asset" ? "자산군" : "종목"}별 순액)
          </span>
          {whQ.data?.lookthrough_applied && (
            <span style={{ marginLeft: 8, color: "#7c3aed" }}>
              · FoF look-through: 자펀드 종목 편입비율 가중평균
            </span>
          )}
        </div>

        {whQ.isLoading ? (
          <div style={{ padding: 12, color: "#6b7280" }}>로딩 중…</div>
        ) : (
          <WeightAreaChart
            points={whQ.data?.points ?? []}
            keys={whQ.data?.keys ?? []}
            level={level}
            topN={topN}
            markers={whQ.data?.markers ?? []}
            instanceKey={`${fundCode}-${level}-${preset}`}
            xRange={[chartStart, today]}
          />
        )}
      </section>

      {/* ====================== FX 포지션 (달러선물) ====================== */}
      {fxQ.data?.has_fx && (
        <section>
          <h2 style={{ fontSize: 15, margin: "0 0 4px" }}>FX 포지션 (달러선물)</h2>
          <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>
            {chartStart} ~ 현재 · 매도(숏) = 음수, 순비중(% NAV)
          </div>
          <FxPositionChart
            points={fxQ.data.points}
            keys={fxQ.data.keys}
            instanceKey={`${fundCode}-fx-${preset}`}
          />
        </section>
      )}

      {/* ============ 종목별 수익률 + 매매 태깅 (종목 기준에서만 노출) ============ */}
      <section>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <h2 style={{ fontSize: 15, margin: 0 }}>
            {level === "asset" ? "자산군 수익률 · 매매 시점" : "종목 수익률 · 매매 시점"}
          </h2>
          {level === "security" ? (
            <label style={{ fontSize: 12, color: "#374151" }}>
              종목:&nbsp;
              <select
                value={selItemCd}
                onChange={(e) => setSelItemCd(e.target.value)}
                style={{ fontSize: 12, padding: "3px 6px", maxWidth: 320 }}
              >
                {priceItems.length === 0 && <option value="">가격 종목 없음</option>}
                {currentItems.map((it) => (
                  <option key={it.item_cd} value={it.item_cd}>
                    [{it.bucket}] {it.item_nm} ({it.weight.toFixed(1)}%)
                  </option>
                ))}
                {pastItems.length > 0 && (
                  <optgroup label="── 과거 편입 (현재 미보유) ──">
                    {pastItems.map((it) => (
                      <option key={it.item_cd} value={it.item_cd}>
                        [{it.bucket}] {it.item_nm} · 과거
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            </label>
          ) : (
            <label style={{ fontSize: 12, color: "#374151" }}>
              자산군:&nbsp;
              <select
                value={selAsset}
                onChange={(e) => setSelAsset(e.target.value)}
                style={{ fontSize: 12, padding: "3px 6px" }}
              >
                {assetKeys.length === 0 && <option value="">자산군 없음</option>}
                {assetKeys.map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </label>
          )}
          <span style={{ fontSize: 12, color: "#9ca3af" }}>
            ▲ {level === "asset" ? "순매수" : "매수/발행"} · ▼ {level === "asset" ? "순매도" : "매도/환매"}
          </span>
          <button
            onClick={() => setRetMarkup((v) => !v)}
            style={{
              fontSize: 12, padding: "4px 10px", borderRadius: 4, cursor: "pointer",
              border: `1px solid ${retMarkup ? "#2563eb" : "#d1d5db"}`,
              background: retMarkup ? "#2563eb" : "#fff",
              color: retMarkup ? "#fff" : "#374151",
            }}
            title="드래그로 두 시점 사이 지수 변화율(%)을 표시. OFF 시 드래그=줌(y 자동보정)"
          >
            변화율 측정 {retMarkup ? "ON" : "OFF"}
          </button>
          <span style={{ fontSize: 11, color: "#9ca3af" }}>
            {retMarkup ? "드래그: 구간 %변화율" : "드래그: 줌(y 자동보정) · 더블클릭 리셋"}
          </span>
        </div>

        <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 6, lineHeight: 1.6 }}>
          {level === "asset" ? (
            <>
              <div>source: 일별 보유비중(DWPM10530) × 종목가격(SCIP FG Return)</div>
              <div>
                자산군 바스켓 수익지수: 시작일=100, 클래스 내 비중가중(Σ wᵢ·rᵢ / Σ wᵢ)
                일별 누적 · 보조축(우): 자산군 편입비중 %
              </div>
            </>
          ) : (
            <>
              <div>source: SCIP FG Return(KRW 총수익 지수, 미커버 시 Total Return Index)</div>
              <div>
                수익률 지수: 조회 시작일=100 누적지수 (종목 자체 수익률,{" "}
                <b>편입비중 미반영</b> — 매매 타이밍 비교용) · 보조축(우): 편입비중 %
              </div>
            </>
          )}
        </div>

        {level === "security" ? (
          !selItemCd ? (
            <div style={{ padding: 12, color: "#6b7280" }}>
              가격 커버리지가 있는 보유종목이 없습니다.
            </div>
          ) : secRetQ.isLoading ? (
            <div style={{ padding: 12, color: "#6b7280" }}>로딩 중…</div>
          ) : (
            <SecurityReturnChart
              points={secRetQ.data?.points ?? []}
              trades={secRetQ.data?.trades ?? []}
              weights={secRetQ.data?.weights ?? []}
              itemNm={selItem?.item_nm ?? ""}
              instanceKey={`${fundCode}-${selItemCd}-${preset}`}
              xRange={[chartStart, today]}
              markupMode={retMarkup}
            />
          )
        ) : !selAsset ? (
          <div style={{ padding: 12, color: "#6b7280" }}>표시할 자산군이 없습니다.</div>
        ) : assetRetQ.isLoading ? (
          <div style={{ padding: 12, color: "#6b7280" }}>로딩 중…</div>
        ) : (
          <SecurityReturnChart
            points={assetRetQ.data?.points ?? []}
            trades={assetRetQ.data?.trades ?? []}
            weights={assetRetQ.data?.weights ?? []}
            weightComponents={assetRetQ.data?.weight_components ?? []}
            tradeComponents={assetRetQ.data?.trade_components ?? []}
            itemNm={selAsset}
            instanceKey={`${fundCode}-asset-${selAsset}-${preset}`}
            xRange={[chartStart, today]}
            markupMode={retMarkup}
          />
        )}
      </section>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: "6px 10px",
  textAlign: "center",
  fontWeight: 600,
  color: "#374151",
  borderBottom: "1px solid #e5e7eb",
  whiteSpace: "nowrap",
};
const tdStyle: React.CSSProperties = {
  padding: "4px 10px",
  textAlign: "center",
  whiteSpace: "nowrap",
};
