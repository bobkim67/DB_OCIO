import Plot from "react-plotly.js";
import type {
  FxForeignWeightPointDTO,
  FxPositionPointDTO,
  FxRatePointDTO,
} from "../../api/endpoints";

const FX_COLOR = "#19D3F3";      // FX 순비중(달러선물 헤지)
const FW_COLOR = "#FFA15A";      // 해외자산 비중
const RATE_COLOR = "#6b7280";    // USD/KRW (보조축)

interface Props {
  points: FxPositionPointDTO[];          // 계약별 순비중 % (매도=양수)
  keys: string[];                        // 계약명 (참고)
  usdkrw?: FxRatePointDTO[];             // 보조축(우) USD/KRW
  foreignWeight?: FxForeignWeightPointDTO[]; // 해외자산 비중 레이어
  instanceKey?: string;
}

// FX 포지션 차트: 달러선물 순비중(헤지=양수) + 해외자산 비중 오버레이 + USD/KRW(우축).
// 월간 선물 계약은 시간순 분리(롤오버) → 계약별 실선 + 롤오버 구간 점선 연결.
export default function FxPositionChart({
  points, usdkrw = [], foreignWeight = [], instanceKey,
}: Props) {
  if (points.length === 0) {
    return <div style={{ padding: 12, color: "#6b7280" }}>FX 포지션 없음</div>;
  }

  // 계약별 (date, weight) 묶음 → 날짜순 정렬, 계약은 첫 거래일순 정렬
  const byContract = new Map<string, { x: string; y: number }[]>();
  for (const p of points) {
    const arr = byContract.get(p.key) ?? [];
    arr.push({ x: p.date, y: p.weight });
    byContract.set(p.key, arr);
  }
  const contracts = [...byContract.entries()]
    .map(([k, v]) => ({ k, pts: v.sort((a, b) => (a.x < b.x ? -1 : 1)) }))
    .sort((a, b) => (a.pts[0].x < b.pts[0].x ? -1 : 1));

  const traces: Plotly.Data[] = [];

  // 계약별 실선 (동일 색, 범례는 첫 계약만)
  contracts.forEach((c, i) => {
    traces.push({
      x: c.pts.map((p) => p.x),
      y: c.pts.map((p) => p.y),
      type: "scatter",
      mode: "lines",
      name: "FX 순비중(환헤지)",
      legendgroup: "fx",
      showlegend: i === 0,
      line: { width: 1.8, color: FX_COLOR },
      hovertemplate: "FX 순비중 %{y:.2f}%<extra></extra>",
    });
  });

  // 롤오버 구간 점선 연결 (이전 계약 마지막 점 → 다음 계약 첫 점)
  const cx: (string | null)[] = [];
  const cy: (number | null)[] = [];
  for (let i = 0; i < contracts.length - 1; i++) {
    const a = contracts[i].pts[contracts[i].pts.length - 1];
    const b = contracts[i + 1].pts[0];
    cx.push(a.x, b.x, null);
    cy.push(a.y, b.y, null);
  }
  if (cx.length) {
    traces.push({
      x: cx,
      y: cy,
      type: "scatter",
      mode: "lines",
      name: "롤오버",
      legendgroup: "fx",
      showlegend: false,
      line: { width: 1.5, color: FX_COLOR, dash: "dot" },
      hoverinfo: "skip",
    });
  }

  // 해외자산 비중 (좌축 %)
  if (foreignWeight.length) {
    traces.push({
      x: foreignWeight.map((p) => p.date),
      y: foreignWeight.map((p) => p.weight),
      type: "scatter",
      mode: "lines",
      name: "해외자산 비중",
      line: { width: 1.8, color: FW_COLOR },
      hovertemplate: "해외자산 %{y:.2f}%<extra></extra>",
    });
  }

  // USD/KRW (우축 보조)
  if (usdkrw.length) {
    traces.push({
      x: usdkrw.map((p) => p.date),
      y: usdkrw.map((p) => p.rate),
      type: "scatter",
      mode: "lines",
      name: "USD/KRW",
      yaxis: "y2",
      line: { width: 1.4, color: RATE_COLOR },
      hovertemplate: "USD/KRW %{y:,.1f}<extra></extra>",
    });
  }

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true,
        height: 320,
        margin: { t: 28, r: 60, b: 36, l: 52 },
        xaxis: { title: { text: "" }, type: "date" },
        yaxis: {
          title: { text: "비중" },
          ticksuffix: "%",
          rangemode: "tozero",
          zeroline: true,
          zerolinecolor: "#9ca3af",
          zerolinewidth: 1,
        },
        yaxis2: {
          title: { text: "USD/KRW" },
          overlaying: "y",
          side: "right",
          showgrid: false,
        },
        hovermode: "x unified",
        hoverlabel: { align: "left" },
        legend: { orientation: "h", x: 0, y: 1.1, xanchor: "left", yanchor: "bottom", font: { size: 11 } },
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
