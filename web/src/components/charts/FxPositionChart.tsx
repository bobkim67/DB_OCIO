import Plot from "react-plotly.js";
import type { FxPositionPointDTO } from "../../api/endpoints";

const PALETTE = ["#19D3F3", "#0ea5e9", "#6366f1", "#8b5cf6", "#0891b2"];

interface Props {
  points: FxPositionPointDTO[];
  keys: string[];
  instanceKey?: string;
}

// 달러선물 등 FX 포지션 순비중(%) 라인차트. 매도(숏)=음수.
export default function FxPositionChart({ points, keys, instanceKey }: Props) {
  if (points.length === 0) {
    return <div style={{ padding: 12, color: "#6b7280" }}>FX 포지션 없음</div>;
  }

  const dates = Array.from(new Set(points.map((p) => p.date))).sort();
  const byDate = new Map<string, Map<string, number>>();
  for (const p of points) {
    let m = byDate.get(p.date);
    if (!m) { m = new Map(); byDate.set(p.date, m); }
    m.set(p.key, p.weight);
  }

  const traces: Plotly.Data[] = keys.map((k, i) => ({
    x: dates,
    y: dates.map((d) => byDate.get(d)?.get(k) ?? null),
    type: "scatter",
    mode: "lines",
    name: k,
    line: { width: 1.8, color: PALETTE[i % PALETTE.length] },
    connectgaps: false,
    hovertemplate: `%{x}<br>${k} %{y:.2f}%<extra></extra>`,
  }));

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true,
        height: 300,
        margin: { t: 16, r: 16, b: 36, l: 52 },
        xaxis: { title: { text: "" } },
        yaxis: {
          title: { text: "순비중 (%)" },
          ticksuffix: "%",
          zeroline: true,
          zerolinecolor: "#9ca3af",
          zerolinewidth: 1,
        },
        hovermode: "x unified",
        legend: { orientation: "h", y: 1.12, font: { size: 11 } },
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
