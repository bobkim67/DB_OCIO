import { useState, type CSSProperties } from "react";
import { useHoldings } from "../hooks/useHoldings";
import MetaBadge from "../components/common/MetaBadge";
import AssetClassPie from "../components/charts/AssetClassPie";
import type { HoldingItemDTO } from "../api/endpoints";

const ASSET_CLASS_ORDER = [
  "국내주식", "해외주식", "국내채권", "해외채권",
  "대체투자", "FX", "모펀드", "유동성",
];

interface Props {
  fundCode: string;
}

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(2)}%`;
}

function fmtKrw(v: number): string {
  return (
    (v / 1e8).toLocaleString("ko-KR", { maximumFractionDigits: 1 }) + "억"
  );
}

// 유동성 자산군 내부에서 예금/USD Deposit 외 종목은 "기타 (N종목)" 1행으로 병합.
function _isCashKeep(it: HoldingItemDTO): boolean {
  const nm = (it.item_nm || "").toUpperCase();
  if (nm.includes("예금")) return true;
  if (nm.includes("DEPOSIT")) return true;
  if (it.item_cd.toUpperCase() === "USMUSD022001") return true;
  return false;
}

function collapseLiquidityOthers(items: HoldingItemDTO[]): HoldingItemDTO[] {
  const liq: HoldingItemDTO[] = [];
  const others: HoldingItemDTO[] = [];
  const rest: HoldingItemDTO[] = [];
  for (const it of items) {
    if (it.asset_class !== "유동성") {
      rest.push(it);
      continue;
    }
    if (_isCashKeep(it)) liq.push(it);
    else others.push(it);
  }
  if (others.length === 0) return items;
  const collapsed: HoldingItemDTO = {
    item_cd: "_OTHER_LIQUIDITY_",
    item_nm: `기타 (${others.length}종목)`,
    asset_class: "유동성",
    weight: others.reduce((s, x) => s + x.weight, 0),
    evl_amt: others.reduce((s, x) => s + x.evl_amt, 0),
    sub_fund_cd: null,
    is_short: false,
  };
  return [...rest, ...liq, collapsed];
}

export default function HoldingsTab({ fundCode }: Props) {
  const [lookthrough, setLookthrough] = useState(false);
  const { data, isLoading, error } = useHoldings(fundCode, lookthrough);

  if (isLoading) return <div>loading holdings...</div>;
  if (error || !data) {
    return (
      <div style={{ color: "#dc2626" }}>failed to load holdings</div>
    );
  }

  const isEmpty = data.holdings_items.length === 0;
  const displayItems = collapseLiquidityOthers(data.holdings_items);

  return (
    <section>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>
          {data.fund_name}{" "}
          <span style={{ color: "#6b7280" }}>({data.fund_code})</span>
        </h2>
        <MetaBadge meta={data.meta} />
        <label
          style={{
            fontSize: 13,
            color: "#374151",
            marginLeft: "auto",
            alignSelf: "center",
          }}
        >
          <input
            type="checkbox"
            checked={lookthrough}
            onChange={(e) => setLookthrough(e.target.checked)}
            style={{ marginRight: 6, verticalAlign: "middle" }}
          />
          look-through{" "}
          {data.lookthrough_applied && (
            <span style={{ color: "#6b7280", fontSize: 11 }}>
              (applied)
            </span>
          )}
        </label>
      </div>

      {isEmpty ? (
        <div style={{ color: "#6b7280", padding: 16 }}>
          데이터 없음 (fallback)
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(300px, 1fr) minmax(300px, 1fr)",
            gap: 16,
          }}
        >
          {/* 왼쪽 컬럼: Pie */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <AssetClassPie weights={data.asset_class_weights} />
          </div>

          {/* 오른쪽 컬럼: 자산군 표 + FX 헷지 요약 + 종목 상세 (자산군 그룹핑) */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <h3 style={{ fontSize: 14, margin: "4px 0 8px" }}>
                자산군별 비중
              </h3>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: 13,
                }}
              >
                <thead>
                  <tr style={{ background: "#f9fafb", textAlign: "left" }}>
                    <th style={th}>자산군</th>
                    <th style={thr}>비중</th>
                    <th style={thr}>평가금액</th>
                    <th style={thr}>종목수</th>
                  </tr>
                </thead>
                <tbody>
                  {data.asset_class_weights.map((w) => (
                    <tr key={w.asset_class}>
                      <td style={td}>
                        <span
                          style={{
                            display: "inline-block",
                            width: 10,
                            height: 10,
                            borderRadius: 2,
                            background: w.color ?? "#9ca3af",
                            marginRight: 6,
                            verticalAlign: "middle",
                          }}
                        />
                        {w.asset_class}
                      </td>
                      <td style={tdr}>{fmtPct(w.weight)}</td>
                      <td style={tdr}>{fmtKrw(w.evl_amt)}</td>
                      <td style={tdr}>{w.item_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.nast_amt != null && (
                <div
                  style={{
                    marginTop: 8,
                    fontSize: 12,
                    color: "#6b7280",
                  }}
                >
                  순자산: {fmtKrw(data.nast_amt)}
                </div>
              )}
              {data.fx_hedge && data.fx_hedge.usd_short_weight > 0 && (
                <div
                  style={{
                    marginTop: 10,
                    padding: "8px 10px",
                    background: "#f0f9ff",
                    border: "1px solid #bfdbfe",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                >
                  <div
                    style={{
                      fontWeight: 600,
                      marginBottom: 4,
                      color: "#1e40af",
                    }}
                  >
                    FX 헷지 요약
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr auto",
                      gap: "2px 8px",
                    }}
                  >
                    <span style={{ color: "#374151" }}>USD 자산비중</span>
                    <strong style={{ fontVariantNumeric: "tabular-nums" }}>
                      {fmtPct(data.fx_hedge.usd_asset_weight)}
                    </strong>
                    <span style={{ color: "#374151" }}>
                      달러매도포지션 비중
                    </span>
                    <strong
                      style={{
                        fontVariantNumeric: "tabular-nums",
                        color: "#b91c1c",
                      }}
                    >
                      −{fmtPct(data.fx_hedge.usd_short_weight)}
                    </strong>
                    <span style={{ color: "#374151" }}>헷지비율</span>
                    <strong
                      style={{
                        fontVariantNumeric: "tabular-nums",
                        color: "#1e40af",
                      }}
                    >
                      {data.fx_hedge.hedge_ratio !== null &&
                      data.fx_hedge.hedge_ratio !== undefined
                        ? fmtPct(data.fx_hedge.hedge_ratio)
                        : "—"}
                    </strong>
                  </div>
                </div>
              )}
            </div>

            {/* 종목별 상세 (자산군 그룹핑) */}
            <div>
              <h3 style={{ fontSize: 14, margin: "8px 0" }}>
                종목별 상세 ({displayItems.length})
              </h3>
              <div
                style={{
                  maxHeight: 720,
                  overflowY: "auto",
                  border: "1px solid #e5e7eb",
                  borderRadius: 6,
                }}
              >
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 13,
                  }}
                >
                  <thead>
                    <tr
                      style={{
                        background: "#f9fafb",
                        textAlign: "left",
                        position: "sticky",
                        top: 0,
                        zIndex: 1,
                      }}
                    >
                      <th style={th}>종목코드</th>
                      <th style={th}>종목명</th>
                      <th style={thr}>비중</th>
                      <th style={thr}>평가금액</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(() => {
                      const groups = new Map<string, HoldingItemDTO[]>();
                      for (const it of displayItems) {
                        const arr = groups.get(it.asset_class) ?? [];
                        arr.push(it);
                        groups.set(it.asset_class, arr);
                      }
                      const orderedClasses = [
                        ...ASSET_CLASS_ORDER.filter((ac) => groups.has(ac)),
                        ...Array.from(groups.keys()).filter(
                          (ac) => !ASSET_CLASS_ORDER.includes(ac),
                        ),
                      ];
                      const rows: JSX.Element[] = [];
                      for (const ac of orderedClasses) {
                        const bucket = groups.get(ac)!;
                        const acW = data.asset_class_weights.find(
                          (x) => x.asset_class === ac,
                        );
                        rows.push(
                          <tr key={`grp-${ac}`} style={groupHeaderRow}>
                            <td colSpan={4} style={groupHeaderCell}>
                              <span
                                style={{
                                  display: "inline-block",
                                  width: 10,
                                  height: 10,
                                  borderRadius: 2,
                                  background: acW?.color ?? "#9ca3af",
                                  marginRight: 6,
                                  verticalAlign: "middle",
                                }}
                              />
                              {ac}
                              <span
                                style={{
                                  marginLeft: 8,
                                  color: "#6b7280",
                                  fontWeight: 400,
                                }}
                              >
                                {acW ? fmtPct(acW.weight) : ""} ·{" "}
                                {bucket.length}종목
                              </span>
                            </td>
                          </tr>,
                        );
                        bucket.forEach((it, i) =>
                          rows.push(
                            <tr key={`${ac}-${it.item_cd}-${i}`}>
                              <td style={td}>
                                {it.item_cd === "_OTHER_LIQUIDITY_"
                                  ? "—"
                                  : it.item_cd}
                              </td>
                              <td style={td}>
                                {it.item_nm}
                                {it.is_short && (
                                  <span
                                    style={{
                                      marginLeft: 6,
                                      padding: "0 5px",
                                      fontSize: 10,
                                      background: "#fee2e2",
                                      color: "#b91c1c",
                                      borderRadius: 3,
                                      fontWeight: 600,
                                    }}
                                  >
                                    SHORT
                                  </span>
                                )}
                              </td>
                              <td style={tdr}>
                                {it.is_short ? "−" : ""}
                                {fmtPct(it.weight)}
                              </td>
                              <td style={tdr}>{fmtKrw(it.evl_amt)}</td>
                            </tr>,
                          ),
                        );
                      }
                      return rows;
                    })()}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

const th: CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid #e5e7eb",
};
const thr: CSSProperties = { ...th, textAlign: "right" };
const td: CSSProperties = {
  padding: "5px 8px",
  borderBottom: "1px solid #f3f4f6",
};
const tdr: CSSProperties = {
  ...td,
  textAlign: "right",
  fontVariantNumeric: "tabular-nums",
};
const groupHeaderRow: CSSProperties = {
  background: "#f3f4f6",
};
const groupHeaderCell: CSSProperties = {
  padding: "6px 8px",
  borderTop: "1px solid #d1d5db",
  borderBottom: "1px solid #d1d5db",
  fontWeight: 600,
  fontSize: 12.5,
  color: "#111827",
};
