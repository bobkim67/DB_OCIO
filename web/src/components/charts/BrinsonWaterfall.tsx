import Plot from "react-plotly.js";

interface Props {
  alloc: number;       // %
  select: number;      // %
  cross: number;       // %
  excess: number;      // %
  height?: number;     // 차트 높이(px). 기본 360.
}

// ACE 토큰 (tokens.css): 양수=코랄, 음수=스틸블루, 합계=다크 잉크.
const UP = "#E8473B";
const DOWN = "#557EAA";
const TOTAL = "#2A2E34";

export default function BrinsonWaterfall({ alloc, select, cross, excess, height = 360 }: Props) {
  const vals = [alloc, select, cross, excess];
  const labels = vals.map((v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);

  // y축 range = waterfall 누적 끝점 기반 (막대 값이 아니라 누적 위치가 축을 결정).
  const positions = [0, alloc, alloc + select, alloc + select + cross, excess];
  const dataMin = Math.min(...positions);
  const dataMax = Math.max(...positions);
  const span = (dataMax - dataMin) || Math.max(1, ...vals.map((v) => Math.abs(v)));
  const pad = span * 0.2; // outside 라벨 여백

  return (
    <Plot
      data={[
        {
          type: "waterfall",
          orientation: "v",
          x: ["자산배분효과", "종목선택효과", "교차효과", "초과수익"],
          y: vals,
          measure: ["relative", "relative", "relative", "total"],
          text: labels,
          textposition: "outside",
          textfont: { size: 12, color: "#2A2E34" },
          // 단일 라인 툴팁 (기본 waterfall 의 delta/running-total 중복 제거)
          customdata: labels,
          hovertemplate: "%{x}  <b>%{customdata}</b><extra></extra>",
          connector: { line: { color: "#C9CED6", width: 1, dash: "dot" } },
          increasing: { marker: { color: UP } },
          decreasing: { marker: { color: DOWN } },
          totals: { marker: { color: TOTAL } },
          width: 0.58,
        } as Plotly.Data,
      ]}
      layout={{
        height,
        autosize: true,
        margin: { t: 18, r: 16, b: 34, l: 44 },
        font: { family: "inherit" },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        xaxis: { tickfont: { size: 12, color: "#2A2E34" }, fixedrange: true },
        yaxis: {
          title: { text: "기여도" }, ticksuffix: "%",
          range: [dataMin - pad, dataMax + pad],
          gridcolor: "#F1F3F5", zeroline: true, zerolinecolor: "#C9CED6", zerolinewidth: 1,
          tickfont: { size: 11, color: "#98A0AD" }, fixedrange: true,
        },
        hoverlabel: { bgcolor: "#fff", bordercolor: "#E3E6EB", font: { color: "#2A2E34", size: 12.5 } },
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height }}
    />
  );
}
