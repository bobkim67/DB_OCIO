import Plot from "react-plotly.js";
import type { HoldingItemDTO } from "../../api/endpoints";
import { secAlias } from "../../lib/securityAlias";

interface Props {
  bonds: HoldingItemDTO[];
  avgDuration?: number | null;
  instanceKey?: string;
}

const C_KR = "#2E9E7B";
const C_OV = "#8E7CC3";

/** 채권 포커스 — x=듀레이션(년), y=종목(가로 사다리), 버블 크기∝비중. */
export default function BondDurationChart({ bonds, avgDuration, instanceKey }: Props) {
  const rows = bonds
    .filter((b) => b.duration != null)
    .sort((a, b) => (a.duration as number) - (b.duration as number));
  if (!rows.length) {
    return <div style={{ padding: 16, color: "var(--ace-ink-3)", fontSize: 12 }}>채권 듀레이션 데이터 없음</div>;
  }
  const labels = rows.map((b) => { const a = secAlias(b.item_nm); return a.length > 18 ? a.slice(0, 17) + "…" : a; });
  // 작은 비중도 보이게: min 24px, 비중 비례 확대
  const sizeOf = (w: number) => Math.max(24, Math.sqrt(w * 100) * 11);
  const isOv = (b: HoldingItemDTO) => b.asset_class === "해외채권";
  const maxDur = Math.max(30, ...rows.map((b) => b.duration as number));

  const traces: Plotly.Data[] = [{
    x: rows.map((b) => b.duration as number),
    y: labels,
    customdata: rows.map((b) => [
      b.ytm != null ? `${b.ytm.toFixed(2)}%` : "—", `${(b.weight * 100).toFixed(1)}%`,
    ]),
    text: rows.map((b) => `${(b.weight * 100).toFixed(0)}%`),
    type: "scatter", mode: "text+markers", textposition: "middle center",
    textfont: { size: 11.5, color: "#fff" },
    marker: {
      size: rows.map((b) => sizeOf(b.weight)),
      color: rows.map((b) => (isOv(b) ? C_OV : C_KR)),
      opacity: 0.9, line: { color: "#fff", width: 2 },
    },
    hovertemplate: "<b>%{y}</b>  %{customdata[1]}<br>듀레이션 %{x:.1f}년 · YTM %{customdata[0]}<extra></extra>",
  }];

  const shapes: Partial<Plotly.Shape>[] = [];
  const annotations: Partial<Plotly.Annotations>[] = [];
  if (avgDuration != null) {
    shapes.push({ type: "line", xref: "x", yref: "paper", x0: avgDuration, x1: avgDuration, y0: 0, y1: 1, line: { color: "rgba(85,126,170,0.55)", width: 2, dash: "dot" } });
    annotations.push({ x: avgDuration, y: 1, xref: "x", yref: "paper", yanchor: "bottom", text: `평균 ${avgDuration.toFixed(1)}년`, showarrow: false, font: { size: 11, color: "#557EAA" } });
  }

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true, height: 460,
        margin: { t: 22, r: 18, b: 36, l: 168 },
        xaxis: { title: { text: "듀레이션 (년)", font: { size: 12 } }, range: [-(maxDur * 0.06), maxDur * 1.08], zeroline: false, gridcolor: "#F0F2F5", tickfont: { size: 11 } },
        yaxis: { automargin: true, tickfont: { size: 13 }, autorange: "reversed" },
        shapes, annotations,
        showlegend: false, hovermode: "closest",
        hoverlabel: { align: "left", bgcolor: "#fff", bordercolor: "#E3E6EB", font: { family: "Pretendard, system-ui, sans-serif", size: 12, color: "#2A2E34" } },
        font: { family: "Pretendard, system-ui, sans-serif", color: "#2A2E34" },
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "460px" }}
    />
  );
}
