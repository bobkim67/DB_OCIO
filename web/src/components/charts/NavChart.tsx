import { useMemo, useState } from "react";
import Plot from "react-plotly.js";
import type { NavPointDTO } from "../../api/endpoints";

interface Props {
  points: NavPointDTO[];
  title?: string;
  instanceKey?: string; // fund 변경 시 Plot 리마운트 + rebase 상태 초기화 트리거
}

/**
 * 누적수익률 차트 — 기준가(NAV)/BM 가격레벨을 rebase 기준점 대비 수익률(%)로 표시.
 *
 * 드래그 줌 → 가시 구간 시작점으로 rebase(수익률 reset, 좌측=0%) + y auto-fit.
 * 더블클릭(autorange) → 전체 기간 기준으로 리셋. (BrinsonTrendPanel 전체모드처럼
 * 초과수익 영역 + 포트/BM 라인을 단일 수익률 축에 표시)
 */
export default function NavChart({ points, title = "누적수익률", instanceKey }: Props) {
  const [baseIdx, setBaseIdx] = useState(0);
  const [xRange, setXRange] = useState<[string, string] | null>(null);
  const [yRange, setYRange] = useState<[number, number] | null>(null);

  const { x, navRet, bmRet, excessRet, hasBm } = useMemo(() => {
    const x = points.map((p) => p.date);
    const navBase = points[baseIdx]?.nav ?? points[0]?.nav ?? 1;
    const hasBm = points.some((p) => p.bm != null);
    let bmBase: number | null = points[baseIdx]?.bm ?? null;
    if (hasBm && bmBase == null) {
      for (let i = baseIdx; i < points.length; i++) {
        if (points[i].bm != null) { bmBase = points[i].bm!; break; }
      }
    }
    const navRet = points.map((p) => (p.nav != null && navBase ? (p.nav / navBase - 1) * 100 : null));
    const bmRet = points.map((p) => (hasBm && p.bm != null && bmBase ? (p.bm / bmBase - 1) * 100 : null));
    const excessRet = navRet.map((v, i) => (v != null && bmRet[i] != null ? v - (bmRet[i] as number) : null));
    return { x, navRet, bmRet, excessRet, hasBm };
  }, [points, baseIdx]);

  // 드래그 줌 → 가시 시작점 rebase + y auto-fit. 더블클릭(autorange) → 전체 리셋.
  const onRelayout = (e: Record<string, unknown>) => {
    if (e["xaxis.autorange"]) { setBaseIdx(0); setXRange(null); setYRange(null); return; }
    const x0 = e["xaxis.range[0]"], x1 = e["xaxis.range[1]"];
    if (x0 === undefined || x1 === undefined) return;
    const xs0 = String(x0).slice(0, 10), xs1 = String(x1).slice(0, 10);
    let idx = points.findIndex((p) => p.date >= xs0);
    if (idx < 0) idx = 0;
    const nb = points[idx]?.nav ?? 1;
    let bb: number | null = points[idx]?.bm ?? null;
    if (bb == null) for (let i = idx; i < points.length; i++) { if (points[i].bm != null) { bb = points[i].bm!; break; } }
    // 가시 구간 rebased y 범위 (포트·BM·초과 모두 포함)
    let lo = Infinity, hi = -Infinity;
    for (const p of points) {
      if (p.date < xs0 || p.date > xs1) continue;
      const nr = p.nav != null && nb ? (p.nav / nb - 1) * 100 : null;
      const br = p.bm != null && bb ? (p.bm / bb - 1) * 100 : null;
      for (const v of [nr, br, nr != null && br != null ? nr - br : null]) {
        if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      }
    }
    setBaseIdx(idx);
    setXRange([xs0, xs1]);
    if (lo < hi) { const pad = (hi - lo) * 0.08 || 0.5; setYRange([lo - pad, hi + pad]); }
  };

  if (points.length === 0) {
    return <div style={{ padding: 16, color: "#6b7280" }}>데이터 없음</div>;
  }

  const useGL = points.length > 1000;
  const scatterType: "scatter" | "scattergl" = useGL ? "scattergl" : "scatter";
  const traces: Plotly.Data[] = [];

  // 초과수익 영역 (항상 SVG — scattergl fill 왜곡 회피)
  if (hasBm) {
    traces.push({
      x, y: excessRet as (number | null)[], type: "scatter", mode: "lines",
      name: "초과수익", line: { color: "rgba(22,163,74,0.35)", width: 0.5 },
      fill: "tozeroy", fillcolor: "rgba(22,163,74,0.10)", connectgaps: false,
      hovertemplate: "초과 %{y:.2f}%p<extra></extra>",
    });
  }
  traces.push({
    x, y: navRet, type: scatterType, mode: "lines", name: "포트",
    line: { color: "#2563eb", width: 2 }, connectgaps: false,
    hovertemplate: "포트 %{y:.2f}%<extra></extra>",
  });
  if (hasBm) {
    traces.push({
      x, y: bmRet as (number | null)[], type: scatterType, mode: "lines", name: "BM",
      line: { color: "#dc2626", width: 1.5, dash: "dot" }, connectgaps: false,
      hovertemplate: "BM %{y:.2f}%<extra></extra>",
    });
  }

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        title: { text: title },
        autosize: true,
        height: 460,
        margin: { t: 40, r: 24, b: 40, l: 60 },
        xaxis: {
          title: { text: "" },
          ...(xRange ? { range: xRange, autorange: false } : { autorange: true }),
        },
        yaxis: {
          title: { text: "수익률 (%)" }, ticksuffix: "%", hoverformat: ".2f",
          zeroline: true, zerolinecolor: "#9ca3af", zerolinewidth: 1,
          ...(yRange ? { range: yRange, autorange: false } : { autorange: true }),
        },
        hovermode: "x unified",
        hoverlabel: { align: "left" },
        legend: { orientation: "h", y: 1.08 },
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
      onRelayout={onRelayout}
    />
  );
}
