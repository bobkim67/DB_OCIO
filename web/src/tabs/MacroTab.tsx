import { useState, useMemo } from "react";
import Plot from "react-plotly.js";
import { useMacro } from "../hooks/useMacro";
import MetaBadge from "../components/common/MetaBadge";
import type { MacroSeriesDTO, MacroPointDTO } from "../api/endpoints";

// 드롭다운 옵션 — 지수 11개 + FX 1개 (USDKRW).
// SCIP의 PE/EPS는 지수 자체가 아닌 대응 US-listed ETF 레벨에서 제공되므로
// 라벨에 추적 ETF 티커를 병기 (예: MSCI Korea ↔ EWY).
const INDEX_OPTIONS: { code: string; label: string; hasValuation: boolean }[] = [
  { code: "KR", label: "MSCI Korea (EWY)", hasValuation: true },
  { code: "SP500", label: "S&P 500 (SPY)", hasValuation: true },
  { code: "EM", label: "MSCI EM (VWO)", hasValuation: true },
  { code: "EAFE", label: "MSCI EAFE (EFA)", hasValuation: true },
  { code: "JP", label: "MSCI Japan (EWJ)", hasValuation: true },
  { code: "VG", label: "Vanguard Growth (VUG)", hasValuation: true },
  { code: "VV", label: "Vanguard Value (VTV)", hasValuation: true },
  { code: "SPG", label: "S&P 500 Growth (SPYG)", hasValuation: true },
  { code: "SPV", label: "S&P 500 Value (SPYV)", hasValuation: true },
  { code: "RG", label: "Russell 1000 Growth (IWF)", hasValuation: true },
  { code: "RV", label: "Russell 1000 Value (IWD)", hasValuation: true },
  { code: "FX", label: "USD/KRW", hasValuation: false },
];

function fmtValue(v: number, unit: MacroSeriesDTO["unit"]): string {
  if (unit === "pct") return `${(v * 100).toFixed(2)}%`;
  if (unit === "bp") return `${(v * 10000).toFixed(0)}bp`;
  if (unit === "krw" || unit === "usd") {
    return v.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  }
  if (unit === "ratio") return v.toFixed(2);
  if (unit === "idx") return v.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  return v.toFixed(2);
}

// YoY growth (달력 365일, 가장 가까운 과거 포인트 대비)
function toYoYGrowth(series: MacroSeriesDTO): MacroSeriesDTO {
  const points = series.points;
  if (points.length === 0) return { ...series, unit: "pct", points: [] };
  const out: MacroPointDTO[] = [];
  let j = 0;
  for (let i = 0; i < points.length; i++) {
    const cur = points[i];
    const curT = new Date(cur.date).getTime();
    const tgt = curT - 365 * 86400000;
    while (j + 1 < points.length && new Date(points[j + 1].date).getTime() <= tgt) j++;
    const past = points[j];
    if (!past || new Date(past.date).getTime() > tgt) continue;
    if (past.value === 0) continue;
    out.push({ date: cur.date, value: cur.value / past.value - 1 });
  }
  return {
    ...series,
    key: `${series.key}_YOY`,
    label: `${series.label} YoY`,
    unit: "pct",
    points: out,
  };
}

function LatestLine({ series }: { series: MacroSeriesDTO[] }) {
  if (series.length === 0) return null;
  return (
    <div
      style={{
        display: "flex",
        gap: 16,
        marginBottom: 12,
        padding: "8px 12px",
        background: "#f9fafb",
        borderRadius: 6,
        flexWrap: "wrap",
        fontSize: 13,
      }}
    >
      {series.map((s) => {
        const last = s.points[s.points.length - 1];
        return (
          <div key={s.key}>
            <span style={{ color: "#6b7280", marginRight: 4 }}>{s.label}:</span>
            <span style={{ fontWeight: 600 }}>
              {last ? fmtValue(last.value, s.unit) : "—"}
            </span>
            {last && (
              <span style={{ color: "#9ca3af", marginLeft: 4, fontSize: 11 }}>
                ({last.date})
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

const IDX_COLOR = "#2563eb";
const PE_COLOR = "#dc2626";
const EPS_COLOR = "#16a34a";

export default function MacroTab() {
  const [code, setCode] = useState<string>("KR");
  const [growth, setGrowth] = useState<boolean>(false);

  const selected = INDEX_OPTIONS.find((o) => o.code === code)!;
  const keys = selected.hasValuation
    ? [`IDX_${code}`, `PE_${code}`, `EPS_${code}`]
    : ["USDKRW"];

  const { data, isLoading, error } = useMacro(keys);

  // 시리즈 분리 및 growth 적용
  const { idxSeries, peSeries, epsSeries } = useMemo(() => {
    let idx: MacroSeriesDTO | null = null;
    let pe: MacroSeriesDTO | null = null;
    let eps: MacroSeriesDTO | null = null;
    if (data) {
      for (const s of data.series) {
        if (s.key.startsWith("IDX_") || s.key === "USDKRW") idx = s;
        else if (s.key.startsWith("PE_") || s.key === "PE") pe = s;
        else if (s.key.startsWith("EPS_") || s.key === "EPS") eps = s;
      }
    }
    if (growth) {
      if (idx) idx = toYoYGrowth(idx);
      if (pe) pe = toYoYGrowth(pe);
      if (eps) eps = toYoYGrowth(eps);
    }
    return { idxSeries: idx, peSeries: pe, epsSeries: eps };
  }, [data, growth]);

  const latestSeries: MacroSeriesDTO[] = [];
  if (idxSeries) latestSeries.push(idxSeries);
  if (peSeries) latestSeries.push(peSeries);
  if (epsSeries) latestSeries.push(epsSeries);

  const traces: Plotly.Data[] = [];
  if (idxSeries) {
    traces.push({
      x: idxSeries.points.map((p) => p.date),
      y: idxSeries.points.map((p) => p.value),
      type: "scatter",
      mode: "lines",
      name: idxSeries.label,
      yaxis: "y",
      line: { color: IDX_COLOR, width: 2 },
      hovertemplate: `%{x}<br>${idxSeries.label}: %{y:.2f}<extra></extra>`,
    });
  }
  if (peSeries) {
    traces.push({
      x: peSeries.points.map((p) => p.date),
      y: peSeries.points.map((p) => p.value),
      type: "scatter",
      mode: "lines",
      name: peSeries.label,
      yaxis: "y2",
      line: { color: PE_COLOR, width: 1.5, dash: "solid" },
      hovertemplate: `%{x}<br>${peSeries.label}: %{y:.3f}<extra></extra>`,
    });
  }
  if (epsSeries) {
    traces.push({
      x: epsSeries.points.map((p) => p.date),
      y: epsSeries.points.map((p) => p.value),
      type: "scatter",
      mode: "lines",
      name: epsSeries.label,
      yaxis: "y2",
      line: { color: EPS_COLOR, width: 1.5, dash: "dot" },
      hovertemplate: `%{x}<br>${epsSeries.label}: %{y:.3f}<extra></extra>`,
    });
  }

  const rightAxisTitle = selected.hasValuation
    ? growth
      ? "PE / EPS (YoY %)"
      : "PE (ratio) / EPS (level)"
    : "";
  const rightAxisTickFormat =
    selected.hasValuation && growth ? ".0%" : undefined;

  // growth 모드일 때만 0 라인 일치 (level 모드는 지수/PE/EPS 모두 양수라 0 정렬 무의미)
  // 각 축 range = [-M, M] (M = max(|min|,|max|)) → 0이 정확히 중앙 → 두 축 0 라인 동일 위치
  const alignZero = selected.hasValuation && growth;
  const leftVals = idxSeries ? idxSeries.points.map((p) => p.value) : [];
  const rightVals = [
    ...(peSeries ? peSeries.points.map((p) => p.value) : []),
    ...(epsSeries ? epsSeries.points.map((p) => p.value) : []),
  ];
  const absMax = (arr: number[]): number =>
    arr.length === 0 ? 1 : Math.max(...arr.map((v) => Math.abs(v)));
  const leftM = absMax(leftVals) * 1.05;
  const rightM = absMax(rightVals) * 1.05;

  return (
    <section>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>매크로 지표</h2>
        {data && <MetaBadge meta={data.meta} />}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          marginBottom: 12,
          fontSize: 13,
          flexWrap: "wrap",
        }}
      >
        <label>
          지수:&nbsp;
          <select
            value={code}
            onChange={(e) => setCode(e.target.value)}
            style={{ fontSize: 13, padding: "3px 6px" }}
          >
            {INDEX_OPTIONS.map((o) => (
              <option key={o.code} value={o.code}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        {selected.hasValuation && (
          <label
            style={{
              cursor: "pointer",
              background: "#eff6ff",
              padding: "3px 10px",
              borderRadius: 4,
              border: "1px solid #bfdbfe",
            }}
          >
            <input
              type="checkbox"
              checked={growth}
              onChange={(e) => setGrowth(e.target.checked)}
              style={{ marginRight: 6, verticalAlign: "middle" }}
            />
            지수·PE·EPS를 YoY growth로 표시
          </label>
        )}
      </div>

      {isLoading ? (
        <div>loading macro...</div>
      ) : error || !data ? (
        <div style={{ color: "#dc2626" }}>failed to load macro</div>
      ) : idxSeries === null ? (
        <div style={{ color: "#6b7280", padding: 16 }}>데이터 없음</div>
      ) : (
        <>
          <LatestLine series={latestSeries} />
          <Plot
            data={traces}
            layout={{
              autosize: true,
              height: 460,
              margin: { t: 20, r: selected.hasValuation ? 70 : 16, b: 40, l: 70 },
              xaxis: { title: { text: "" } },
              yaxis: {
                title: {
                  text: selected.hasValuation
                    ? (growth ? "지수 YoY" : "지수 (level)")
                    : "USD/KRW (KRW)",
                },
                color: IDX_COLOR,
                tickformat: selected.hasValuation && growth ? ".0%" : undefined,
                zeroline: alignZero,
                ...(alignZero ? { range: [-leftM, leftM] } : {}),
              },
              ...(selected.hasValuation
                ? {
                    yaxis2: {
                      title: { text: rightAxisTitle },
                      overlaying: "y",
                      side: "right",
                      tickformat: rightAxisTickFormat,
                      showgrid: false,
                      zeroline: alignZero,
                      ...(alignZero ? { range: [-rightM, rightM] } : {}),
                    },
                  }
                : {}),
              hovermode: "x unified",
              legend: { orientation: "h", y: 1.1 },
            }}
            config={{ displayModeBar: false, responsive: true }}
            useResizeHandler
            style={{ width: "100%", height: "100%" }}
          />
        </>
      )}
    </section>
  );
}
