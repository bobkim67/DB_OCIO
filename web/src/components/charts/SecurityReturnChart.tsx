import Plot from "react-plotly.js";
import type {
  SecurityReturnPointDTO,
  SecurityTradeMarkerDTO,
  SecurityWeightPointDTO,
} from "../../api/endpoints";

const BUY_COLOR = "#EF553B";  // 매수/발행 ▲ 빨강
const SELL_COLOR = "#636EFA"; // 매도/환매 ▼ 파랑

interface Props {
  points: SecurityReturnPointDTO[];
  trades: SecurityTradeMarkerDTO[];
  weights?: SecurityWeightPointDTO[];
  itemNm: string;
  instanceKey?: string;
}

// 종목 수익률 지수(시작=100) 라인 + 일별 매수(▲)/매도(▼) 마커.
// 보조축(우): 편입비중 % — 옅은 파스텔 영역 레이어(뒤).
export default function SecurityReturnChart({
  points, trades, weights = [], itemNm, instanceKey,
}: Props) {
  if (points.length === 0) {
    return <div style={{ padding: 12, color: "#6b7280" }}>가격 데이터 없음</div>;
  }

  const dates = points.map((p) => p.date);
  const values = points.map((p) => p.value);

  // 거래일 → 수익률값 매핑 (없으면 직전 영업일 값)
  const yAt = (d: string): number | null => {
    let best: number | null = null;
    for (const p of points) {
      if (p.date <= d) best = p.value;
      else break;
    }
    return best;
  };

  const isBuy = (s: string) => s.includes("매수") || s.includes("발행");
  const buys = trades.filter((t) => isBuy(t.side));
  const sells = trades.filter((t) => !isBuy(t.side));

  const markerTrace = (
    ts: SecurityTradeMarkerDTO[],
    name: string,
    color: string,
    symbol: string,
  ): Plotly.Data => ({
    x: ts.map((t) => t.date),
    y: ts.map((t) => yAt(t.date)),
    type: "scatter",
    mode: "markers",
    name,
    marker: { color, size: 11, symbol, line: { width: 1, color: "#fff" } },
    text: ts.map((t) => `${t.side} ${t.amount.toFixed(2)}억`),
    hovertemplate: "%{x}<br>%{text}<extra></extra>",
  });

  const hasWeight = weights.length > 0;
  const traces: Plotly.Data[] = [];

  // 보조축 비중 레이어 (가장 뒤에 그림 — 옅은 파스텔 영역)
  if (hasWeight) {
    traces.push({
      x: weights.map((w) => w.date),
      y: weights.map((w) => w.weight),
      type: "scatter",
      mode: "lines",
      name: "편입비중",
      yaxis: "y2",
      line: { color: "rgba(129,140,248,0.45)", width: 0.5 },
      fill: "tozeroy",
      fillcolor: "rgba(129,140,248,0.13)",
      hovertemplate: "%{x}<br>비중 %{y:.2f}%<extra></extra>",
    });
  }

  traces.push({
    x: dates,
    y: values,
    type: "scatter",
    mode: "lines",
    name: itemNm,
    line: { color: "#374151", width: 1.5 },
    hovertemplate: "%{x}<br>지수 %{y:.1f}<extra></extra>",
  });
  if (buys.length) traces.push(markerTrace(buys, "매수/발행", BUY_COLOR, "triangle-up"));
  if (sells.length) traces.push(markerTrace(sells, "매도/환매", SELL_COLOR, "triangle-down"));

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true,
        height: 360,
        margin: { t: 20, r: 52, b: 36, l: 52 },
        xaxis: { title: { text: "" } },
        yaxis: { title: { text: "수익률 지수 (시작=100)" } },
        ...(hasWeight
          ? {
              yaxis2: {
                title: { text: "편입비중 %", standoff: 8 },
                overlaying: "y",
                side: "right",
                rangemode: "tozero",
                ticksuffix: "%",
                showgrid: false,
                automargin: true,
              },
            }
          : {}),
        hovermode: "closest",
        legend: { orientation: "h", y: 1.12, font: { size: 11 } },
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
