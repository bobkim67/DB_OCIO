import Plot from "react-plotly.js";
import type { HoldingAssetClassDTO } from "../../api/endpoints";

interface Props {
  weights: HoldingAssetClassDTO[];
}

export default function AssetClassPie({ weights }: Props) {
  if (weights.length === 0) {
    return (
      <div style={{ padding: 16, color: "#6b7280" }}>데이터 없음</div>
    );
  }
  const labels = weights.map((w) => w.asset_class);
  const values = weights.map((w) => w.weight);
  const colors = weights.map((w) => w.color ?? "#9ca3af");

  return (
    // wrapper div로 명시 크기 확보 — 첫 마운트 시 Plotly가 container 크기 인식 못하고
    // 기본 사이즈(700×450)로 렌더되어 과도하게 커지는 증상 회피
    <div style={{ width: "100%", height: 360 }}>
      <Plot
        data={[
          {
            type: "pie",
            labels,
            values,
            textinfo: "label+percent",
            hovertemplate: "%{label}<br>%{percent}<extra></extra>",
            marker: { colors },
            sort: false,
          },
        ]}
        layout={{
          autosize: true,
          margin: { t: 16, r: 16, b: 16, l: 16 },
          showlegend: false,
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
