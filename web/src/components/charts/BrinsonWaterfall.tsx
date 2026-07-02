import Plot from "react-plotly.js";

interface Props {
  alloc: number;       // %
  select: number;      // %
  cross: number;       // %
  excess: number;      // %
  height?: number;     // 차트 높이(px). 기본 360.
}

// 막대=파스텔톤, 라벨=동일 계열 원톤(ACE up/down + 초록) — 2026-07-03 사용자 지정.
// 양수=코랄 / 음수=스틸블루, 초과수익(합계)=초록.
const POS = "#F2A099";          // 양수 막대 (코랄 파스텔)
const NEG = "#A8C0DA";          // 음수 막대 (스틸블루 파스텔)
const TOTAL_POS = "#9FD3BE";    // 초과수익 + (초록 파스텔)
const TOTAL_NEG = "#D8BC94";    // 초과수익 − (브라운 파스텔, ACE saa 계열)
const POS_TXT = "#E8473B";      // 라벨 (원톤, tokens.css --ace-up)
const NEG_TXT = "#557EAA";      // 라벨 (원톤, --ace-down)
const TOTAL_POS_TXT = "#2E9E7B";  // 라벨 (원톤 초록)
const TOTAL_NEG_TXT = "#B07A2B";  // 라벨 (원톤 브라운, --ace-saa)

const BAR_W = 0.56;

export default function BrinsonWaterfall({ alloc, select, cross, excess, height = 360 }: Props) {
  const names = ["자산배분효과", "종목선택효과", "교차효과", "초과수익"];
  const vals = [alloc, select, cross, excess];
  // 요인 막대=부호 파스텔색(코랄/스틸블루), 초과수익(합계)=+초록/−브라운 파스텔
  const colors = [
    alloc >= 0 ? POS : NEG,
    select >= 0 ? POS : NEG,
    cross >= 0 ? POS : NEG,
    excess >= 0 ? TOTAL_POS : TOTAL_NEG,
  ];
  const labelColors = [
    alloc >= 0 ? POS_TXT : NEG_TXT,
    select >= 0 ? POS_TXT : NEG_TXT,
    cross >= 0 ? POS_TXT : NEG_TXT,
    excess >= 0 ? TOTAL_POS_TXT : TOTAL_NEG_TXT,
  ];
  const labels = vals.map((v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);

  // 누적 워터폴: 요인 막대=직전 누적~+값, 합계 막대=0~excess.
  // (waterfall 트레이스는 per-bar 색을 못 주므로 bar+base 로 직접 구성)
  const starts = [0, alloc, alloc + select, 0];
  const ends = [alloc, alloc + select, alloc + select + cross, excess];
  const base = ends.map((e, i) => Math.min(starts[i], e));
  const heights = ends.map((e, i) => Math.abs(e - starts[i]));

  // y축 range = 누적 끝점 기반
  const positions = [0, alloc, alloc + select, alloc + select + cross, excess];
  const dataMin = Math.min(...positions);
  const dataMax = Math.max(...positions);
  const span = (dataMax - dataMin) || Math.max(1, ...vals.map((v) => Math.abs(v)));
  const pad = span * 0.2;

  // 점선 연결선: 막대 i 누적 끝점(ends[i]) 에서 다음 막대까지 (i=0,1,2)
  const connectors = [0, 1, 2].map((i) => ({
    type: "line" as const, xref: "x" as const, yref: "y" as const,
    x0: i + BAR_W / 2, x1: i + 1 - BAR_W / 2, y0: ends[i], y1: ends[i],
    line: { color: "#C9CED6", width: 1, dash: "dot" as const },
    layer: "below" as const,
  }));

  return (
    <Plot
      data={[
        {
          type: "bar",
          x: names,
          y: heights,
          base,
          marker: { color: colors },
          text: labels,
          textposition: "outside",
          textfont: { size: 12, color: labelColors },
          customdata: labels,
          hovertemplate: "%{x}  <b>%{customdata}</b><extra></extra>",
          width: BAR_W,
        } as Plotly.Data,
      ]}
      layout={{
        height,
        autosize: true,
        margin: { t: 18, r: 16, b: 34, l: 44 },
        font: { family: "inherit" },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        xaxis: { type: "category", tickfont: { size: 12, color: "#2A2E34" }, fixedrange: true },
        yaxis: {
          title: { text: "기여도" }, ticksuffix: "%",
          range: [dataMin - pad, dataMax + pad],
          gridcolor: "#F1F3F5", zeroline: true, zerolinecolor: "#C9CED6", zerolinewidth: 1,
          tickfont: { size: 11, color: "#98A0AD" }, fixedrange: true,
        },
        shapes: connectors,
        hoverlabel: { bgcolor: "#fff", bordercolor: "#E3E6EB", font: { color: "#2A2E34", size: 12.5 } },
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height }}
    />
  );
}
