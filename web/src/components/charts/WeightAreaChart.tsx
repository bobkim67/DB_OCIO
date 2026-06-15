import Plot from "react-plotly.js";
import type { WeightHistoryPointDTO } from "../../api/endpoints";

// 6버킷 고정 색상 (국내주식/해외주식/국내채권/해외채권/금·대체/유동성)
const BUCKET_COLORS: Record<string, string> = {
  국내주식: "#EF553B",
  해외주식: "#636EFA",
  국내채권: "#00CC96",
  해외채권: "#AB63FA",
  "금/대체": "#FFA15A",
  유동성: "#B6E880",
};

// 종목 기준용 팔레트 (반복)
const PALETTE = [
  "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
  "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
  "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
  "#c49c94", "#f7b6d2", "#dbdb8d", "#9edae5", "#393b79",
];

interface Props {
  points: WeightHistoryPointDTO[];
  keys: string[];               // 정렬된 key (security: 평균비중 desc, asset: 고정순)
  level: "security" | "asset";
  topN?: number;                // security 한정. 0/undefined → 전체
  instanceKey?: string;         // fund/level 변경 시 리마운트
}

export default function WeightAreaChart({
  points, keys, level, topN, instanceKey,
}: Props) {
  if (points.length === 0) {
    return <div style={{ padding: 16, color: "#6b7280" }}>데이터 없음</div>;
  }

  const dates = Array.from(new Set(points.map((p) => p.date))).sort();

  // (date, key) → weight 피벗
  const byDate = new Map<string, Map<string, number>>();
  for (const p of points) {
    let m = byDate.get(p.date);
    if (!m) { m = new Map(); byDate.set(p.date, m); }
    m.set(p.key, (m.get(p.key) ?? 0) + p.weight);
  }

  // 표시 key 결정 (security + topN 이면 나머지 '기타' 묶음)
  let displayKeys = keys;
  let etcKeys: string[] = [];
  if (level === "security" && topN && topN > 0 && keys.length > topN) {
    displayKeys = keys.slice(0, topN);
    etcKeys = keys.slice(topN);
  }

  const colorOf = (k: string, i: number) => {
    if (k === "유동성") return BUCKET_COLORS["유동성"]; // 묶음 밴드는 고정 색
    if (level === "asset") return BUCKET_COLORS[k] ?? PALETTE[i % PALETTE.length];
    return PALETTE[i % PALETTE.length];
  };

  // 누적 영역은 scattergl fill 왜곡 이슈로 항상 SVG scatter (NavChart 주석 참조)
  const traces: Plotly.Data[] = displayKeys.map((k, i) => ({
    x: dates,
    y: dates.map((d) => byDate.get(d)?.get(k) ?? 0),
    type: "scatter",
    mode: "lines",
    name: k,
    stackgroup: "one",
    line: { width: 0.5, color: colorOf(k, i) },
    fillcolor: colorOf(k, i),
    hovertemplate: `%{x}<br>${k} %{y:.2f}%<extra></extra>`,
  }));

  if (etcKeys.length > 0) {
    const etcY = dates.map((d) => {
      const m = byDate.get(d);
      if (!m) return 0;
      let s = 0;
      for (const k of etcKeys) s += m.get(k) ?? 0;
      return s;
    });
    traces.push({
      x: dates,
      y: etcY,
      type: "scatter",
      mode: "lines",
      name: `기타 (${etcKeys.length})`,
      stackgroup: "one",
      line: { width: 0.5, color: "#9ca3af" },
      fillcolor: "#9ca3af",
      hovertemplate: `%{x}<br>기타 %{y:.2f}%<extra></extra>`,
    });
  }

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true,
        height: 480,
        margin: { t: 24, r: 16, b: 40, l: 48 },
        xaxis: { title: { text: "" } },
        yaxis: { title: { text: "비중 (%)" }, range: [0, 100], ticksuffix: "%" },
        hovermode: "x unified",
        legend: { orientation: "v", x: 1.02, y: 1, font: { size: 11 } },
        showlegend: true,
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
