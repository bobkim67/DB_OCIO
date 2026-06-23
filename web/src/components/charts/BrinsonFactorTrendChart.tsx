import Plot from "react-plotly.js";
import type { BrinsonDailyPointDTO } from "../../api/endpoints";

/**
 * Brinson 요인 누적 추이 — 초과수익을 Allocation/Selection/Cross 로 시간축 분해.
 *
 * 워터폴(기간 합)의 시계열 버전: "초과수익을 배분 스킬이 이끌었나 종목선택이 이끌었나"를
 * 한눈에. daily_brinson 의 alloc_cum/select_cum/cross_cum/excess_cum 그대로 사용.
 */
const COLORS = {
  excess: "#000080", // 초과(합) — 남색 굵게
  alloc: "#2563eb", // Allocation — 파랑
  select: "#16a34a", // Selection — 초록
  cross: "#9ca3af", // Cross — 회색
};
const plotConfig = { displayModeBar: false, responsive: true } as const;

interface Props {
  daily: BrinsonDailyPointDTO[];
}

export default function BrinsonFactorTrendChart({ daily }: Props) {
  if (daily.length === 0) {
    return <div style={{ padding: 12, color: "#6b7280" }}>추이 데이터 없음</div>;
  }
  const x = daily.map((d) => String(d.date));
  const line = (
    key: "excess_cum" | "alloc_cum" | "select_cum" | "cross_cum",
    name: string,
    color: string,
    width: number,
    dash?: "dash",
  ): Plotly.Data => ({
    x,
    y: daily.map((d) => d[key]),
    customdata: daily.map((d) => (d[key] >= 0 ? "+" : "") + d[key].toFixed(2)),
    type: "scatter",
    mode: "lines",
    name,
    line: { width, color, ...(dash ? { dash } : {}) },
    hovertemplate: `${name} %{customdata}%p<extra></extra>`,
  });

  const data: Plotly.Data[] = [
    line("excess_cum", "초과수익(합)", COLORS.excess, 2.4),
    line("alloc_cum", "Allocation", COLORS.alloc, 1.6),
    line("select_cum", "Selection", COLORS.select, 1.6),
    line("cross_cum", "Cross", COLORS.cross, 1.4, "dash"),
  ];

  const layout: Partial<Plotly.Layout> = {
    autosize: true,
    height: 340,
    margin: { t: 28, r: 16, b: 36, l: 52 },
    xaxis: { title: { text: "" }, type: "date" },
    yaxis: {
      title: { text: "누적 기여 (%p)" },
      ticksuffix: "%",
      hoverformat: ".2f",
      zeroline: true,
      zerolinecolor: "#9ca3af",
      zerolinewidth: 1,
    },
    hovermode: "x unified",
    hoverlabel: { align: "left" },
    legend: { orientation: "h", x: 0, y: 1.08, xanchor: "left", yanchor: "bottom", font: { size: 11 } },
  };

  return (
    <div>
      <h3 style={{ fontSize: 14, margin: "4px 0 8px", display: "flex", alignItems: "center", gap: 8 }}>
        요인별 초과수익 누적 추이
        <span style={{ fontSize: 11, color: "#9ca3af", fontWeight: 400 }}>
          초과수익 = Allocation + Selection + Cross
        </span>
      </h3>
      <Plot
        data={data}
        layout={layout}
        config={plotConfig}
        useResizeHandler
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
