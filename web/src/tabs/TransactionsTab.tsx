import { useEffect, useMemo, useState } from "react";
import {
  useFxPosition,
  useSecurities,
  useSecurityReturn,
  useTransactions,
  useWeightHistory,
} from "../hooks/useTransactions";
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

type TxnPreset = "MTD" | "1M" | "3M" | "6M" | "YTD" | "custom";
type ChartPeriod = "1M" | "3M" | "6M" | "YTD";

const TXN_PRESETS: { key: TxnPreset; label: string }[] = [
  { key: "MTD", label: "당월(MTD)" },
  { key: "1M", label: "직전 1개월" },
  { key: "3M", label: "직전 3개월" },
  { key: "6M", label: "직전 6개월" },
  { key: "YTD", label: "연초이후" },
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

export default function TransactionsTab({ fundCode }: Props) {
  const today = fmtLocal(new Date());

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
      case "custom":
        return { txnStart: customStart, txnEnd: customEnd };
    }
  }, [preset, customStart, customEnd, today]);

  const txnQ = useTransactions(fundCode, txnStart, txnEnd);

  // ---- 영역차트 ----
  const [level, setLevel] = useState<WeightHistoryLevel>("asset");
  const [chartPeriod, setChartPeriod] = useState<ChartPeriod>("YTD");
  const [topNInput, setTopNInput] = useState<string>(""); // "" = 전체

  const chartStart = useMemo(() => {
    switch (chartPeriod) {
      case "1M": return fmtLocal(monthsAgo(1));
      case "3M": return fmtLocal(monthsAgo(3));
      case "6M": return fmtLocal(monthsAgo(6));
      case "YTD": return fmtLocal(startOfYear());
    }
  }, [chartPeriod]);

  const whQ = useWeightHistory(fundCode, chartStart, level);

  const topN = useMemo(() => {
    const n = parseInt(topNInput, 10);
    return Number.isFinite(n) && n > 0 ? n : 0; // 0 = 전체
  }, [topNInput]);

  // ---- FX 포지션 (달러선물) ----
  const fxQ = useFxPosition(fundCode, chartStart);

  // ---- 종목별 수익률 ----
  const secQ = useSecurities(fundCode);
  const priceItems = useMemo(
    () => (secQ.data?.items ?? []).filter((it) => it.has_price),
    [secQ.data],
  );
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

  const isFofTxn = txnQ.data?.lookthrough_applied ?? false;
  const showFundCol = isFofTxn;
  const fmtD = (d: string) =>
    d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : d;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* ====================== 거래내역 ====================== */}
      <section>
        <h2 style={{ fontSize: 15, margin: "0 0 8px" }}>거래내역</h2>

        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, marginBottom: 8 }}>
          {TXN_PRESETS.map((p) => (
            <label
              key={p.key}
              style={{
                fontSize: 12,
                padding: "4px 10px",
                border: "1px solid #e5e7eb",
                borderRadius: 4,
                background: preset === p.key ? "#eff6ff" : "#fff",
                cursor: "pointer",
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
                type="date"
                value={customStart}
                max={customEnd}
                onChange={(e) => setCustomStart(e.target.value)}
                style={{ fontSize: 12, padding: "3px 6px" }}
              />
              ~
              <input
                type="date"
                value={customEnd}
                min={customStart}
                onChange={(e) => setCustomEnd(e.target.value)}
                style={{ fontSize: 12, padding: "3px 6px" }}
              />
            </span>
          )}
        </div>

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
          <div style={{ maxHeight: 360, overflow: "auto", border: "1px solid #e5e7eb", borderRadius: 4 }}>
            <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#f9fafb", position: "sticky", top: 0 }}>
                  <th style={thStyle}>날짜</th>
                  {showFundCol && <th style={thStyle}>펀드</th>}
                  <th style={{ ...thStyle, textAlign: "left" }}>종목명</th>
                  <th style={thStyle}>자산군</th>
                  <th style={thStyle}>매수/매도</th>
                  <th style={{ ...thStyle, textAlign: "right" }}>금액(억)</th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((r, i) => (
                  <tr key={i} style={{ borderTop: "1px solid #f3f4f6" }}>
                    <td style={tdStyle}>{fmtD(r.date)}</td>
                    {showFundCol && <td style={tdStyle}>{r.fund_code}</td>}
                    <td style={{ ...tdStyle, textAlign: "left" }}>{r.item_nm}</td>
                    <td style={tdStyle}>{r.asset_class}</td>
                    <td style={{ ...tdStyle, color: sideColor(r.side) }}>
                      {r.side}
                    </td>
                    <td
                      style={{
                        ...tdStyle,
                        textAlign: "right",
                        color: sideColor(r.side),
                      }}
                    >
                      {r.amount_eok.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ====================== 일별 비중 영역차트 ====================== */}
      <section>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <h2 style={{ fontSize: 15, margin: 0 }}>일별 비중 추이</h2>

          {/* 종목/자산군 토글 */}
          <div style={{ display: "inline-flex", border: "1px solid #e5e7eb", borderRadius: 4, overflow: "hidden" }}>
            {(["asset", "security"] as WeightHistoryLevel[]).map((lv) => (
              <button
                key={lv}
                onClick={() => setLevel(lv)}
                style={{
                  fontSize: 12,
                  padding: "5px 12px",
                  border: "none",
                  background: level === lv ? "#2563eb" : "#fff",
                  color: level === lv ? "#fff" : "#374151",
                  cursor: "pointer",
                }}
              >
                {lv === "asset" ? "자산군 기준" : "종목 기준"}
              </button>
            ))}
          </div>

          {/* 기간 */}
          <label style={{ fontSize: 12, color: "#374151" }}>
            기간:&nbsp;
            <select
              value={chartPeriod}
              onChange={(e) => setChartPeriod(e.target.value as ChartPeriod)}
              style={{ fontSize: 12, padding: "3px 6px" }}
            >
              <option value="1M">직전 1개월</option>
              <option value="3M">직전 3개월</option>
              <option value="6M">직전 6개월</option>
              <option value="YTD">연초이후</option>
            </select>
          </label>

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
            instanceKey={`${fundCode}-${level}-${chartPeriod}`}
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
            instanceKey={`${fundCode}-fx-${chartPeriod}`}
          />
        </section>
      )}

      {/* ====================== 종목별 수익률 + 매매 태깅 ====================== */}
      <section>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <h2 style={{ fontSize: 15, margin: 0 }}>종목 수익률 · 매매 시점</h2>
          <label style={{ fontSize: 12, color: "#374151" }}>
            종목:&nbsp;
            <select
              value={selItemCd}
              onChange={(e) => setSelItemCd(e.target.value)}
              style={{ fontSize: 12, padding: "3px 6px", maxWidth: 320 }}
            >
              {priceItems.length === 0 && <option value="">가격 종목 없음</option>}
              {priceItems.map((it) => (
                <option key={it.item_cd} value={it.item_cd}>
                  [{it.bucket}] {it.item_nm} ({it.weight.toFixed(1)}%)
                </option>
              ))}
            </select>
          </label>
          <span style={{ fontSize: 12, color: "#9ca3af" }}>
            ▲ 매수/발행 · ▼ 매도/환매 (기타·환전 제외)
          </span>
        </div>

        <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 6, lineHeight: 1.6 }}>
          <div>source: SCIP FG Return(KRW 총수익 지수, 미커버 시 Total Return Index)</div>
          <div>
            수익률 지수: 조회 시작일=100 누적지수 (종목 자체 수익률,{" "}
            <b>편입비중 미반영</b> — 매매 타이밍 비교용) · 보조축(우): 편입비중 %
          </div>
        </div>

        {!selItemCd ? (
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
            instanceKey={`${fundCode}-${selItemCd}-${chartPeriod}`}
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
