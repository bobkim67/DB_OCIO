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
        height: 360,
        margin: { t: 16, r: 16, b: 16, l: 16 },
        showlegend: false,
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
