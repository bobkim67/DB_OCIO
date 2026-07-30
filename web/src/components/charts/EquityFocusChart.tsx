import Plot from "react-plotly.js";
import type { EquityFocusDTO } from "../../api/endpoints";
import { secAlias } from "../../lib/securityAlias";

interface Props {
  focus: EquityFocusDTO;
  instanceKey?: string;
}

const C_KR = "#E8473B";
const C_OV = "#557EAA";
const Y_FLOOR = -9;          // y축 하단(저성장)
const OUTLIER_THRESH = 80;   // EPS성장 80%↑ = 기저효과 outlier → 상단 절단축으로 분리
const PER_MIN = 5, PER_MAX = 35;
const PER_MID = 20, GR_MID = 12;
// 절단축(broken axis) domain: 하단(정상)=[0,0.825], 상단(outlier)=[0.86,1.0], 사이=물결컷
const D_LO_TOP = 0.825, D_HI_BOT = 0.86;

// paper 좌표 전폭 sine 물결 path (broken axis 절단 경계선)
function wavePath(y: number, amp: number, n: number): string {
  const seg = 1 / n;
  let d = `M 0 ${y.toFixed(4)}`;
  for (let i = 0; i < n; i++) {
    const cx = (seg * (i + 0.5)).toFixed(4);
    const ex = (seg * (i + 1)).toFixed(4);
    const cy = (y + (i % 2 === 0 ? -amp : amp)).toFixed(4);
    d += ` Q ${cx} ${cy} ${ex} ${y.toFixed(4)}`;
  }
  return d;
}

const fmtPer = (v: number) => `${v.toFixed(1)}x`;
const fmtGr = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(0)}%`;
const fmtW = (v: number) => `${(v * 100).toFixed(1)}%`;

type Pt = { per: number; g: number; w: number; nm: string; proxy: string; ac: string; ref: boolean; label: string };

/** 주식 포커스 — PER(x) × EPS성장 YoY(y). 좌상단=저PER·고성장. outlier 는 상단 절단축. */
export default function EquityFocusChart({ focus, instanceKey }: Props) {
  const held = new Set(
    focus.holdings.map((h) => h.proxy_ticker).filter(Boolean) as string[],
  );
  const refs = (focus.references ?? []).filter(
    (r) => !held.has(r.ticker) && r.per != null && r.eps_growth != null,
  );
  const hs = focus.holdings.filter((h) => h.per != null && h.eps_growth != null);
  const sizeOf = (w: number) => Math.max(19, Math.sqrt(w * 100) * 8.5);
  const aliasTrunc = (nm: string) => { const a = secAlias(nm); return a.length > 14 ? a.slice(0, 13) + "…" : a; };

  // ── 포인트 구성 ──
  const heldPts: Pt[] = hs.map((h) => ({
    per: h.per as number, g: h.eps_growth as number, w: h.weight,
    nm: h.item_nm, proxy: h.proxy_ticker ?? "", ac: h.asset_class, ref: false, label: aliasTrunc(h.item_nm),
  }));
  const refPts: Pt[] = refs.map((r) => ({
    per: r.per as number, g: r.eps_growth as number, w: 0,
    nm: r.ticker, proxy: r.ticker, ac: "참조", ref: true, label: r.ticker,
  }));

  // ── 절단축 범위 ──
  const allEps = [...heldPts, ...refPts].map((p) => p.g * 100);
  const normals = allEps.filter((v) => v <= OUTLIER_THRESH);
  const normalMax = normals.length ? Math.max(...normals) : OUTLIER_THRESH;
  const outs = allEps.filter((v) => v > OUTLIER_THRESH);
  const hasOutlier = outs.length > 0;
  const normalTop = Math.max(20, Math.ceil((normalMax * 1.08) / 10) * 10);
  const outLo = hasOutlier ? Math.floor((Math.min(...outs) * 0.96) / 5) * 5 : 0;
  const outHi = hasOutlier ? Math.ceil((Math.max(...outs) * 1.04) / 5) * 5 : 0;
  const isOut = (g: number) => g * 100 > OUTLIER_THRESH;

  const sidePos = (per: number) => (per > PER_MAX - 8 ? "middle left" : "middle right");

  // ── x축 범위: 경계 버블 잘림 방지 (2026-07-30) ──
  // 버블 반지름(px)을 PER 단위로 근사(≈15px/단위)해, 경계에 걸치는 점이 있으면 그만큼 확장.
  const padOf = (p: Pt) => (p.ref ? 13 : sizeOf(p.w)) / 30 + 0.3;
  const allPts = [...heldPts, ...refPts];
  const perLo = Math.min(PER_MIN, ...allPts.map((p) => p.per - padOf(p)));
  const perHi = Math.max(PER_MAX, ...allPts.map((p) => p.per + padOf(p)));

  // 동일 좌표 겹침 분리(jitter) + trace 생성. axis='y'(하단) | 'y2'(상단 outlier)
  const scatter = (pts: Pt[], color: string, axis: "y" | "y2", ref: boolean): Plotly.Data | null => {
    if (!pts.length) return null;
    const seen: Record<string, number> = {};
    const upper = axis === "y2";
    const ys = pts.map((p) => {
      const base = upper ? p.g * 100 : Math.max(Y_FLOOR, p.g * 100);
      const k = `${p.per.toFixed(1)}|${base.toFixed(0)}`;
      const n = (seen[k] = (seen[k] ?? 0) + 1);
      const step = Math.ceil((n - 1) / 2) * (upper ? 1.2 : 3.6);
      return base + ((n - 1) % 2 ? step : -step);
    });
    return {
      x: pts.map((p) => p.per), y: ys, yaxis: axis,
      text: pts.map((p) => p.label),
      customdata: ref
        ? pts.map((p) => [fmtPer(p.per), fmtGr(p.g)])
        : pts.map((p) => [fmtW(p.w), fmtPer(p.per), fmtGr(p.g), p.nm, p.proxy]),
      type: "scatter", mode: "text+markers",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      textposition: (ref ? "top center" : pts.map((p) => sidePos(p.per))) as any,
      textfont: ref ? { size: 12, color: "#98A0AD" } : { size: 13, color },
      marker: ref
        ? { size: 13, color: "#C4CBD4", line: { color: "#fff", width: 1 } }
        : { size: pts.map((p) => sizeOf(p.w)), color, opacity: 0.85, line: { color: "#fff", width: 2 } },
      hovertemplate: ref
        ? "%{text} <i>(참조 스타일)</i><br>PER %{customdata[0]} · EPS %{customdata[1]}<extra></extra>"
        : "<b>%{customdata[3]}</b>  %{customdata[0]}<br>PER %{customdata[1]} · EPS %{customdata[2]}<br>proxy %{customdata[4]}<extra></extra>",
      name: ref ? "참조" : pts[0].ac,
      showlegend: false,
    };
  };

  const traces: Plotly.Data[] = [];
  const push = (t: Plotly.Data | null) => { if (t) traces.push(t); };
  // 참조(회색)
  push(scatter(refPts.filter((p) => !isOut(p.g)), "#C4CBD4", "y", true));
  if (hasOutlier) push(scatter(refPts.filter((p) => isOut(p.g)), "#C4CBD4", "y2", true));
  // 국내/해외 (보유)
  for (const [ac, col] of [["국내주식", C_KR], ["해외주식", C_OV]] as const) {
    const g = heldPts.filter((p) => p.ac === ac);
    push(scatter(g.filter((p) => !isOut(p.g)), col, "y", false));
    if (hasOutlier) push(scatter(g.filter((p) => isOut(p.g)), col, "y2", false));
  }

  const rect = (x0: number, x1: number, y0: number, y1: number, fill: string) => ({
    type: "rect" as const, xref: "x" as const, yref: "y" as const,
    x0, x1, y0, y1, fillcolor: fill, line: { width: 0 }, layer: "below" as const,
  });

  const shapes: Partial<Plotly.Shape>[] = [
    rect(perLo, PER_MID, GR_MID, normalTop, "rgba(46,125,82,0.07)"),
    rect(PER_MID, perHi, GR_MID, normalTop, "rgba(85,126,170,0.045)"),
    rect(perLo, PER_MID, Y_FLOOR, GR_MID, "rgba(0,0,0,0.012)"),
    rect(PER_MID, perHi, Y_FLOOR, GR_MID, "rgba(192,57,43,0.045)"),
    { type: "line", xref: "x", yref: "y", x0: PER_MID, x1: PER_MID, y0: Y_FLOOR, y1: normalTop, line: { color: "#E3E6EB", width: 1 }, layer: "below" },
    { type: "line", xref: "x", yref: "y", x0: perLo, x1: perHi, y0: GR_MID, y1: GR_MID, line: { color: "#E3E6EB", width: 1 }, layer: "below" },
  ];
  if (hasOutlier) {
    // 절단 gap: 음영 없이 빈칸 + 전폭 물결 점선 2개(상·하 경계)
    shapes.push(
      { type: "path", xref: "paper", yref: "paper", path: wavePath(D_LO_TOP, 0.007, 22), line: { color: "rgba(192,57,43,0.45)", width: 1.2, dash: "dot" }, layer: "below" },
      { type: "path", xref: "paper", yref: "paper", path: wavePath(D_HI_BOT, 0.007, 22), line: { color: "rgba(192,57,43,0.45)", width: 1.2, dash: "dot" }, layer: "below" },
    );
  }

  // 레이아웃 (절단 시 yaxis2 추가)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const layout: any = {
    autosize: true, height: 460,
    margin: { t: 12, r: 30, b: 40, l: 50 },
    xaxis: { title: { text: "PER (저평가 ← → 고평가)", font: { size: 12 } }, range: [perLo, perHi], anchor: "y", zeroline: false, gridcolor: "#F0F2F5", tickfont: { size: 11 } },
    yaxis: {
      title: { text: "EPS 성장 (YoY)", font: { size: 12 } }, ticksuffix: "%",
      domain: hasOutlier ? [0, D_LO_TOP] : [0, 1], range: [Y_FLOOR, normalTop],
      anchor: "x", zeroline: false, gridcolor: "#F0F2F5", tickfont: { size: 11 },
    },
    shapes,
    showlegend: false, hovermode: "closest",
    hoverlabel: { align: "left", bgcolor: "#fff", bordercolor: "#E3E6EB", font: { family: "Pretendard, system-ui, sans-serif", size: 12, color: "#2A2E34" } },
    font: { family: "Pretendard, system-ui, sans-serif", color: "#2A2E34" },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  };
  if (hasOutlier) {
    layout.yaxis2 = {
      domain: [D_HI_BOT, 1], range: [outLo, outHi], ticksuffix: "%",
      anchor: "x", zeroline: false, gridcolor: "#F0F2F5", tickfont: { size: 11 }, nticks: 3,
    };
  }

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={layout}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "460px" }}
    />
  );
}
