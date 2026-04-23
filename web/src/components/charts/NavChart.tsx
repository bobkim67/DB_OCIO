import Plot from "react-plotly.js";
import type { NavPointDTO } from "../../api/endpoints";

interface Props {
  points: NavPointDTO[];
  title?: string;
  instanceKey?: string;  // fund 변경 시 Plot 리마운트 트리거
}

export default function NavChart({ points, title = "수정기준가", instanceKey }: Props) {
  if (points.length === 0) {
    return <div style={{ padding: 16, color: "#6b7280" }}>데이터 없음</div>;
  }

  const x = points.map((p) => p.date);
  const nav = points.map((p) => p.nav);
  const bm = points.map((p) => p.bm);
  const excess = points.map((p) => p.excess);
  const hasBm = bm.some((v) => v !== null && v !== undefined);

  // 긴 시계열(>1000 pts, 예: 2JM23 10년 3682 pts)에서 SVG 렌더가 지연/실패하는 증상 회피
  const useGL = points.length > 1000;
  const scatterType: "scatter" | "scattergl" = useGL ? "scattergl" : "scatter";

  // 초과수익 영역을 먼저 그려서 NAV/BM 라인이 위로 올라오도록 (layer 순서 주의)
  const traces: Plotly.Data[] = [];

  if (hasBm) {
    // 영역 trace는 scattergl의 fill='tozeroy'가 다각형으로 왜곡 렌더되는 이슈가 있어
    // 항상 SVG scatter로 강제 (nav/bm만 GL 가능).
    traces.push({
      x,
      y: excess as (number | null)[],
      type: "scatter",
      mode: "lines",
      name: "초과수익",
      yaxis: "y2",
      line: { color: "rgba(22,163,74,0.35)", width: 0.5, shape: "linear" },
      fill: "tozeroy",
      fillcolor: "rgba(22,163,74,0.08)",
      connectgaps: false,
      hovertemplate: "%{x}<br>초과 %{y:.2%}<extra></extra>",
    });
  }

  traces.push({
    x,
    y: nav,
    type: scatterType,
    mode: "lines",
    name: "포트",
    line: { color: "#2563eb", width: 2 },
    hovertemplate: "%{x}<br>%{y:.2f}<extra></extra>",
    connectgaps: false,
  });

  if (hasBm) {
    traces.push({
      x,
      y: bm as (number | null)[],
      type: scatterType,
      mode: "lines",
      name: "BM",
      line: { color: "#dc2626", width: 1.5, dash: "dot" },
      connectgaps: false,
      hovertemplate: "%{x}<br>BM %{y:.2f}<extra></extra>",
    });
  }

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        title: { text: title },
        autosize: true,
        height: 460,
        margin: { t: 40, r: 80, b: 40, l: 56 },
        xaxis: { title: { text: "" } },
        yaxis: { title: { text: "NAV / BM" } },
        ...(hasBm
          ? {
              yaxis2: {
                title: { text: "초과수익 (ratio)", standoff: 20 },
                overlaying: "y",
                side: "right",
                tickformat: ".2%",
                showgrid: false,
                automargin: true,
              },
            }
          : {}),
        hovermode: "x unified",
        legend: { orientation: "h", y: 1.08 },
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
