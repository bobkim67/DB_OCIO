import Plot from "react-plotly.js";

interface Props {
  alloc: number;       // %
  select: number;      // %
  cross: number;       // %
  excess: number;      // %
}

export default function BrinsonWaterfall({ alloc, select, cross, excess }: Props) {
  const vals = [alloc, select, cross, excess];
  // y축 range = waterfall **누적 위치** 기반.
  // 각 relative 막대는 직전 누적값 ~ (직전 누적값 + value) 구간을 차지하므로,
  // 막대 자체의 값(value)이 아니라 누적 끝점들이 y축을 결정한다.
  //   alloc 막대   : 0           ~ alloc
  //   select 막대  : alloc       ~ alloc + select
  //   cross 막대   : alloc+select~ alloc + select + cross
  //   excess 막대  : 0           ~ excess        (measure='total')
  const cumAlloc = alloc;
  const cumSelect = alloc + select;
  const cumCross = alloc + select + cross;
  const positions = [0, cumAlloc, cumSelect, cumCross, excess];
  const dataMin = Math.min(...positions);
  const dataMax = Math.max(...positions);
  const span = (dataMax - dataMin) || Math.max(1, ...vals.map((v) => Math.abs(v)));
  const pad = span * 0.18; // outside 텍스트 라벨 공간 확보
  const ymin = dataMin - pad;
  const ymax = dataMax + pad;
  const labels = vals.map((v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);

  return (
    <Plot
      data={[
        {
          type: "waterfall",
          orientation: "v",
          x: ["Allocation", "Selection", "Cross", "Excess"],
          y: vals,
          measure: ["relative", "relative", "relative", "total"],
          text: labels,
          textposition: "outside",
          connector: { line: { color: "#888" } },
          increasing: { marker: { color: "#636EFA" } },
          decreasing: { marker: { color: "#EF553B" } },
          totals: { marker: { color: "#00CC96" } },
        } as Plotly.Data,
      ]}
      layout={{
        title: { text: "초과성과 요인분해" },
        height: 360,
        margin: { t: 40, r: 20, b: 40, l: 50 },
        yaxis: { title: { text: "기여도 (%)" }, range: [ymin, ymax] },
        autosize: true,
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
