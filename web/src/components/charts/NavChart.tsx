import { useMemo, useState } from "react";
import Plot from "react-plotly.js";
import type { NavPointDTO } from "../../api/endpoints";

type BenchmarkKind = "BM" | "SAA" | "none";

interface Props {
  points: NavPointDTO[];
  benchmarkKind?: BenchmarkKind;
  benchmarkLabel?: string | null;
  showBm?: boolean;          // SAA/BM 라인 + 초과수익(우축) 표시
  showTarget?: boolean;      // 목표수익률 곡선 + 면적 음영
  targetAnnual?: number | null;  // 목표수익률 (연, fraction)
  inceptionDate?: string;    // 목표 곡선 일수 기준 (YYYY-MM-DD)
  instanceKey?: string;      // fund 변경 시 Plot 리마운트 + rebase 초기화
}

const C_PORT = "#557EAA";   // 브랜드 스틸블루
const C_BENCH = "#B07A2B";  // SAA/BM brown
const C_EXCESS = "rgba(232,71,59,0.5)";
const C_EXCESS_FILL = "rgba(232,71,59,0.13)";
const C_OK = "#2E7D52";
const C_BAD = "#C0392B";

/**
 * 누적수익률 차트 (리디자인) — 좌축=수익률%(포트·SAA/BM), 우축=초과수익%p(코랄 영역).
 * 목표 토글 시 포트↔목표 면적 음영(달성=초록/미달=빨강). 시안: Overview Redesign v2.
 *
 * 드래그 줌 → 가시 시작점으로 rebase(좌측=0%) + y auto-fit. 더블클릭 → 전체 리셋.
 */
export default function NavChart({
  points,
  benchmarkKind = "none",
  benchmarkLabel,
  showBm = true,
  showTarget = false,
  targetAnnual = null,
  inceptionDate,
  instanceKey,
}: Props) {
  const [baseIdx, setBaseIdx] = useState(0);
  const [xRange, setXRange] = useState<[string, string] | null>(null);
  const [yRange, setYRange] = useState<[number, number] | null>(null);

  const hasBench = benchmarkKind !== "none" && points.some((p) => p.bm != null);
  const benchName = benchmarkLabel ?? (benchmarkKind === "BM" ? "BM" : "SAA");
  const ageDays0 = inceptionDate ? Date.parse(inceptionDate) : null;
  const wantTarget = showTarget && targetAnnual != null && ageDays0 != null;

  const { x, navRet, benchRet, excessRet, targetRet } = useMemo(() => {
    const x = points.map((p) => p.date);
    const navBase = points[baseIdx]?.nav ?? points[0]?.nav ?? 1;
    let bBase: number | null = points[baseIdx]?.bm ?? null;
    if (hasBench && bBase == null) {
      for (let i = baseIdx; i < points.length; i++) {
        if (points[i].bm != null) { bBase = points[i].bm!; break; }
      }
    }
    const navRet = points.map((p) => (p.nav != null && navBase ? (p.nav / navBase - 1) * 100 : null));
    const benchRet = points.map((p) =>
      hasBench && p.bm != null && bBase ? (p.bm / bBase - 1) * 100 : null,
    );
    const excessRet = navRet.map((v, i) =>
      v != null && benchRet[i] != null ? v - (benchRet[i] as number) : null,
    );
    // 목표 곡선: (1+annual)^(age/365) 레벨을 rebase 기준점 대비 수익률(%)로.
    let targetRet: (number | null)[] = [];
    if (wantTarget) {
      const lvl = (iso: string) => {
        const age = (Date.parse(iso) - (ageDays0 as number)) / 86400000;
        return Math.pow(1 + (targetAnnual as number), Math.max(age, 0) / 365);
      };
      const tBase = lvl(points[baseIdx]?.date ?? points[0].date) || 1;
      targetRet = points.map((p) => (lvl(p.date) / tBase - 1) * 100);
    }
    return { x, navRet, benchRet, excessRet, targetRet };
  }, [points, baseIdx, hasBench, wantTarget, targetAnnual, ageDays0]);

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
    let lo = Infinity, hi = -Infinity;
    for (const p of points) {
      if (p.date < xs0 || p.date > xs1) continue;
      const nr = p.nav != null && nb ? (p.nav / nb - 1) * 100 : null;
      const br = p.bm != null && bb ? (p.bm / bb - 1) * 100 : null;
      for (const v of [nr, br]) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    }
    setBaseIdx(idx);
    setXRange([xs0, xs1]);
    if (lo < hi) { const pad = (hi - lo) * 0.08 || 0.5; setYRange([lo - pad, hi + pad]); }
  };

  if (points.length === 0) {
    return <div style={{ padding: 16, color: "var(--ace-ink-3)" }}>데이터 없음</div>;
  }

  const useGL = points.length > 1000;
  const scatterType: "scatter" | "scattergl" = useGL ? "scattergl" : "scatter";
  const traces: Plotly.Data[] = [];
  const showBench = hasBench && showBm;

  // 1) 초과수익 영역 (우축, 항상 SVG — scattergl fill 왜곡 회피)
  if (showBench) {
    traces.push({
      x, y: excessRet as (number | null)[], type: "scatter", mode: "lines",
      name: `초과수익 (${benchName})`, yaxis: "y2",
      line: { color: C_EXCESS, width: 1 }, fill: "tozeroy", fillcolor: C_EXCESS_FILL,
      connectgaps: false, hovertemplate: "초과 %{y:.2f}%p<extra></extra>",
    });
  }

  // 2) 목표 곡선 + 포트↔목표 면적 (목표 토글 시)
  if (wantTarget) {
    const lastN = navRet[navRet.length - 1] ?? 0;
    const lastT = targetRet[targetRet.length - 1] ?? 0;
    const achieved = (lastN ?? 0) >= (lastT ?? 0);
    const fillCol = achieved ? "rgba(46,125,82,0.12)" : "rgba(192,57,43,0.12)";
    traces.push({
      x, y: targetRet, type: "scatter", mode: "lines", name: "목표",
      line: { color: achieved ? C_OK : C_BAD, width: 1.4, dash: "dash" },
      connectgaps: false, hovertemplate: "목표 %{y:.2f}%<extra></extra>",
    });
    // 포트 복제선(보이지 않음) — 직전 목표선과의 사이를 채움
    traces.push({
      x, y: navRet, type: "scatter", mode: "lines", name: "_targetfill",
      line: { color: "rgba(0,0,0,0)", width: 0 }, fill: "tonexty", fillcolor: fillCol,
      connectgaps: false, hoverinfo: "skip", showlegend: false,
    });
  }

  // 3) 포트 라인
  traces.push({
    x, y: navRet, type: scatterType, mode: "lines", name: "포트",
    line: { color: C_PORT, width: 2.6, shape: "linear" }, connectgaps: false,
    hovertemplate: "포트 %{y:.2f}%<extra></extra>",
  });

  // 4) SAA/BM 라인
  if (showBench) {
    traces.push({
      x, y: benchRet as (number | null)[], type: scatterType, mode: "lines", name: benchName,
      line: { color: C_BENCH, width: 1.8 }, connectgaps: false,
      hovertemplate: `${benchName} %{y:.2f}%<extra></extra>`,
    });
  }

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true,
        margin: { t: 20, r: 52, b: 28, l: 50 },
        xaxis: {
          title: { text: "" },
          ...(xRange ? { range: xRange, autorange: false } : { autorange: true }),
        },
        yaxis: {
          title: { text: "수익률" }, ticksuffix: "%", hoverformat: ".2f",
          zeroline: true, zerolinecolor: "#C9CED6", zerolinewidth: 1,
          gridcolor: "#ECEEF1",
          ...(yRange ? { range: yRange, autorange: false } : { autorange: true }),
        },
        yaxis2: {
          title: { text: "초과 (%p)", font: { color: "#C66" } },
          overlaying: "y", side: "right", showgrid: false,
          ticksuffix: "", tickfont: { color: "#C66" }, hoverformat: ".2f",
          zeroline: false,
        },
        hovermode: "x unified",
        hoverlabel: { align: "left" },
        legend: { orientation: "h", y: 1.1, x: 0 },
        font: { family: "Pretendard, system-ui, sans-serif", color: "#2A2E34" },
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
      onRelayout={onRelayout}
    />
  );
}
