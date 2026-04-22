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
  const nav = points.map((p) => p.nav);
  const bm = points.map((p) => p.bm);
  const excess = points.map((p) => p.excess);
  const hasBm = bm.some((v) => v !== null && v !== undefined);

  const traces: Plotly.Data[] = [
    {
      x,
      y: nav,
      type: "scatter",
      mode: "lines",
      name: "포트",
      line: { color: "#2563eb", width: 2 },
      hovertemplate: "%{x}<br>%{y:.2f}<extra></extra>",
      connectgaps: false,
    },
  ];

  if (hasBm) {
    traces.push({
      x,
      y: bm as (number | null)[],
      type: "scatter",
      mode: "lines",
      name: "BM",
      line: { color: "#dc2626", width: 1.5, dash: "dot" },
      connectgaps: false,
      hovertemplate: "%{x}<br>BM %{y:.2f}<extra></extra>",
    });
    traces.push({
      x,
      y: excess as (number | null)[],
      type: "scatter",
      mode: "lines",
      name: "초과수익",
      yaxis: "y2",
      line: { color: "#16a34a", width: 1 },
      fill: "tozeroy",
      fillcolor: "rgba(22,163,74,0.12)",
      connectgaps: false,
      hovertemplate: "%{x}<br>초과 %{y:.2%}<extra></extra>",
    });
  }

  return (
    <Plot
      data={traces}
      layout={{
        title: { text: title },
        autosize: true,
        height: 460,
        margin: { t: 40, r: 56, b: 40, l: 56 },
        xaxis: { title: { text: "" } },
        yaxis: { title: { text: "NAV / BM" } },
        yaxis2: hasBm
          ? {
              title: { text: "초과수익 (ratio)" },
              overlaying: "y",
              side: "right",
              tickformat: ".2%",
              showgrid: false,
            }
          : undefined,
        hovermode: "x unified",
        legend: { orientation: "h", y: 1.08 },
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
