import Plot from "react-plotly.js";
import type {
  FxForeignWeightPointDTO,
  FxPositionPointDTO,
  FxRatePointDTO,
} from "../../api/endpoints";

const GAP_COLOR = "#7c3aed";     // 헤지갭(해외−FX) 영역
const RATE_COLOR = "#6b7280";    // USD/KRW (보조축)
const GUIDE_COLOR = "#EF553B";   // 가이드 상한 (빨간 점선)

// 가이드: FX 매도포지션 ≤ 해외자산비중 + 10% → (해외 − FX) ≥ −10%p.
// 영역이 (해외−FX) 차이값이므로 위배선 = y −10%p 수평선.
const GUIDE_GAP = -10;

interface Props {
  points: FxPositionPointDTO[];               // 계약별 FX 순비중 % (매도=양수)
  foreignWeight?: FxForeignWeightPointDTO[];  // 해외자산 비중 %
  usdkrw?: FxRatePointDTO[];                  // USD/KRW (보조축)
  instanceKey?: string;
}

// 오른쪽 차트: 헤지갭(해외자산비중 − FX순비중) 영역 + USD/KRW(우축) + 가이드상한 점선.
export default function FxHedgeGapChart({
  points, foreignWeight = [], usdkrw = [], instanceKey,
}: Props) {
  if (points.length === 0) {
    return <div style={{ padding: 12, color: "#6b7280" }}>FX 포지션 없음</div>;
  }

  // 일자별 FX 순비중 합(계약 합산) + 해외자산비중 → 헤지갭(해외 − FX)
  const fxByDate = new Map<string, number>();
  for (const p of points) fxByDate.set(p.date, (fxByDate.get(p.date) ?? 0) + p.weight);
  const fwByDate = new Map<string, number>();
  for (const p of foreignWeight) fwByDate.set(p.date, p.weight);

  const dates = [...new Set([...fxByDate.keys(), ...fwByDate.keys()])]
    .filter((d) => fxByDate.has(d) && fwByDate.has(d))
    .sort();
  const gap = dates.map((d) => (fwByDate.get(d)! - fxByDate.get(d)!));

  const traces: Plotly.Data[] = [];

  // 헤지갭 영역 (해외 − FX). +=과소헤지 / −=과대헤지
  traces.push({
    x: dates,
    y: gap,
    type: "scatter",
    mode: "lines",
    name: "헤지갭 (해외−FX)",
    fill: "tozeroy",
    line: { width: 1.6, color: GAP_COLOR },
    fillcolor: "rgba(124,58,237,0.18)",
    hovertemplate: "헤지갭 %{y:.2f}%p<extra></extra>",
  });

  // 가이드 상한 (FX ≤ 해외+10% ⇔ 헤지갭 ≥ −10%p) — 빨간 점선
  if (dates.length) {
    traces.push({
      x: [dates[0], dates[dates.length - 1]],
      y: [GUIDE_GAP, GUIDE_GAP],
      type: "scatter",
      mode: "lines",
      name: "가이드상한 (FX≤해외+10%)",
      line: { width: 1.6, color: GUIDE_COLOR, dash: "dash" },
      hoverinfo: "skip",
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
          title: { text: "헤지갭" },
          ticksuffix: "%",
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
