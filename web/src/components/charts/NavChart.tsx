import Plot from "react-plotly.js";
import type { NavPointDTO } from "../../api/endpoints";

interface Props {
  points: NavPointDTO[];
  title?: string;
}

export default function NavChart({ points, title = "수정기준가" }: Props) {
  if (points.length === 0) {
    return <div style={{ padding: 16, color: "#6b7280" }}>데이터 없음</div>;
  }
  const x = points.map((p) => p.date);
  const y = points.map((p) => p.nav);
  return (
    <Plot
      data={[
        {
          x,
          y,
          type: "scatter",
          mode: "lines",
          name: "NAV",
          line: { color: "#2563eb", width: 2 },
          hovertemplate: "%{x}<br>%{y:.2f}<extra></extra>",
        },
      ]}
      layout={{
        title: { text: title },
        autosize: true,
        height: 420,
        margin: { t: 40, r: 16, b: 40, l: 56 },
        xaxis: { title: { text: "" } },
        yaxis: { title: { text: "NAV" } },
        hovermode: "x unified",
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
