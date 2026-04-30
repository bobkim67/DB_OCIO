import Plot from "react-plotly.js";
import type { IndicatorSeriesDTO } from "../../api/endpoints";

interface Props {
  series: IndicatorSeriesDTO[];
}

const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed"];

/**
 * P1-③ — read-time 합성된 macro context normalized index chart.
 *
 * Y축: "기준일=100" (각 series 의 첫 유효값을 100 으로). Tooltip 에 raw_value /
 * unit 까지 표시. base_date / base_value 는 series 메타에 보존.
 *
 * Chart 자체는 client-side 렌더 (서버 Figure JSON 생성 금지 룰 준수).
 */
export default function IndicatorChart({ series }: Props) {
  if (series.length === 0) {
    return <div style={{ padding: 16, color: "#6b7280" }}>데이터 없음</div>;
  }
  const traces: Plotly.Data[] = series.map((s, i) => ({
    x: s.points.map((p) => p.date),
    y: s.points.map((p) => p.value),
    customdata: s.points.map((p) => [p.raw_value]),
    type: "scatter",
    mode: "lines",
    name: s.label,
    line: { color: PALETTE[i % PALETTE.length], width: 2 },
    hovertemplate:
      `%{x}<br>` +
      `${s.label}<br>` +
      `index: %{y:.2f}<br>` +
      `raw: %{customdata[0]}` +
      (s.unit ? ` ${s.unit}` : "") +
      `<extra></extra>`,
  }));
  return (
    <Plot
      data={traces}
      layout={{
        autosize: true,
        height: 360,
        margin: { t: 20, r: 16, b: 40, l: 56 },
        xaxis: { title: { text: "" } },
        yaxis: {
          title: { text: "Index (first valid = 100)" },
          zeroline: false,
        },
        hovermode: "x unified",
        legend: { orientation: "h", y: 1.08 },
        shapes: [
          {
            type: "line", xref: "paper", x0: 0, x1: 1,
            y0: 100, y1: 100,
            line: { color: "#9ca3af", width: 1, dash: "dot" },
          },
        ],
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
