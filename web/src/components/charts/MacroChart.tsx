import Plot from "react-plotly.js";
import type { MacroSeriesDTO } from "../../api/endpoints";

interface Props {
  series: MacroSeriesDTO[];
}

const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed"];

export default function MacroChart({ series }: Props) {
  if (series.length === 0) {
    return <div style={{ padding: 16, color: "#6b7280" }}>데이터 없음</div>;
  }
  const traces: Plotly.Data[] = series.map((s, i) => ({
    x: s.points.map((p) => p.date),
    y: s.points.map((p) => p.value),
    type: "scatter",
    mode: "lines",
    name: s.label,
    line: { color: PALETTE[i % PALETTE.length], width: 2 },
    hovertemplate: `%{x}<br>${s.label} %{y}<extra></extra>`,
  }));
  return (
    <Plot
      data={traces}
      layout={{
        autosize: true,
        height: 420,
        margin: { t: 20, r: 16, b: 40, l: 56 },
        xaxis: { title: { text: "" } },
        yaxis: { title: { text: "" } },
        hovermode: "x unified",
        legend: { orientation: "h", y: 1.08 },
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
