import { useState, type CSSProperties } from "react";
import { useHoldings } from "../hooks/useHoldings";
import MetaBadge from "../components/common/MetaBadge";
import AssetClassPie from "../components/charts/AssetClassPie";

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
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(300px, 1fr) minmax(300px, 1fr)",
              gap: 16,
              marginBottom: 16,
            }}
          >
            <AssetClassPie weights={data.asset_class_weights} />
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
            </div>
          </div>

          <h3 style={{ fontSize: 14, margin: "8px 0" }}>
            종목별 상세 ({data.holdings_items.length})
          </h3>
          <div
            style={{
              maxHeight: 480,
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
                  }}
                >
                  <th style={th}>자산군</th>
                  <th style={th}>종목코드</th>
                  <th style={th}>종목명</th>
                  <th style={thr}>비중</th>
                  <th style={thr}>평가금액</th>
                </tr>
              </thead>
              <tbody>
                {data.holdings_items.map((it, i) => (
                  <tr key={`${it.item_cd}-${i}`}>
                    <td style={td}>{it.asset_class}</td>
                    <td style={td}>{it.item_cd}</td>
                    <td style={td}>{it.item_nm}</td>
                    <td style={tdr}>{fmtPct(it.weight)}</td>
                    <td style={tdr}>{fmtKrw(it.evl_amt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
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
