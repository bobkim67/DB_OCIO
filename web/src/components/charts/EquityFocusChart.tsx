import Plot from "react-plotly.js";
import type { EquityFocusDTO } from "../../api/endpoints";
import { secAlias } from "../../lib/securityAlias";

interface Props {
  focus: EquityFocusDTO;
  instanceKey?: string;
}

const C_KR = "#E8473B";
const C_OV = "#557EAA";
const Y_CAP = 50;
const Y_TOP = 66;   // y축 상단 여유 — 큰 버블(고비중·캡)이 잘리지 않게
const PER_MIN = 5, PER_MAX = 35;
const PER_MID = 20, GR_MID = 12;

const fmtPer = (v: number) => `${v.toFixed(1)}x`;
const fmtGr = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(0)}%`;
const fmtW = (v: number) => `${(v * 100).toFixed(1)}%`;

/** 주식 포커스 — PER(x) × EPS성장 YoY(y). 좌상단=저PER·고성장. */
export default function EquityFocusChart({ focus, instanceKey }: Props) {
  const held = new Set(
    focus.holdings.map((h) => h.proxy_ticker).filter(Boolean) as string[],
  );
  const refs = (focus.references ?? []).filter(
    (r) => !held.has(r.ticker) && r.per != null && r.eps_growth != null,
  );
  const hs = focus.holdings.filter((h) => h.per != null && h.eps_growth != null);
  const clamp = (g: number) => Math.max(-9, Math.min(g * 100, Y_CAP));
  const sizeOf = (w: number) => Math.max(19, Math.sqrt(w * 100) * 8.5);

  const traces: Plotly.Data[] = [];
  if (refs.length) {
    traces.push({
      x: refs.map((r) => r.per as number),
      y: refs.map((r) => clamp(r.eps_growth as number)),
      text: refs.map((r) => r.ticker),
      customdata: refs.map((r) => [fmtPer(r.per as number), fmtGr(r.eps_growth as number)]),
      type: "scatter", mode: "text+markers", textposition: "top center",
      textfont: { size: 12, color: "#98A0AD" },
      marker: { size: 13, color: "#C4CBD4", line: { color: "#fff", width: 1 } },
      hovertemplate: "%{text} <i>(참조 스타일)</i><br>PER %{customdata[0]} · EPS %{customdata[1]}<extra></extra>",
      name: "참조",
    });
  }
  // 티커명은 마커 우측에 표기(상하 배치 겹침 회피). 우측 끝 근처는 왼쪽으로.
  const sidePos = (per: number) => (per > PER_MAX - 8 ? "middle left" : "middle right");
  for (const [ac, col] of [["국내주식", C_KR], ["해외주식", C_OV]] as const) {
    const g = hs.filter((h) => h.asset_class === ac);
    if (!g.length) continue;
    // 동일 proxy(같은 좌표) 종목은 라벨/버블이 포개지므로 y를 미세 분리
    const seen: Record<string, number> = {};
    const ys = g.map((h) => {
      const by = clamp(h.eps_growth as number);
      const k = `${(h.per as number).toFixed(1)}|${by.toFixed(0)}`;
      const n = (seen[k] = (seen[k] ?? 0) + 1);
      const step = Math.ceil((n - 1) / 2) * 3.6;
      return by + ((n - 1) % 2 ? step : -step);
    });
    traces.push({
      x: g.map((h) => h.per as number),
      y: ys,
      text: g.map((h) => { const a = secAlias(h.item_nm); return a.length > 14 ? a.slice(0, 13) + "…" : a; }),
      customdata: g.map((h) => [
        fmtW(h.weight), fmtPer(h.per as number), fmtGr(h.eps_growth as number),
        h.item_nm, h.proxy_ticker ?? "",
      ]),
      type: "scatter", mode: "text+markers",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      textposition: g.map((h) => sidePos(h.per as number)) as any,
      textfont: { size: 13, color: col },
      marker: { size: g.map((h) => sizeOf(h.weight)), color: col, opacity: 0.85, line: { color: "#fff", width: 2 } },
      hovertemplate:
        "<b>%{customdata[3]}</b>  %{customdata[0]}<br>PER %{customdata[1]} · EPS %{customdata[2]}<br>proxy %{customdata[4]}<extra></extra>",
      name: ac,
    });
  }

  const rect = (x0: number, x1: number, y0: number, y1: number, fill: string) => ({
    type: "rect" as const, xref: "x" as const, yref: "y" as const,
    x0, x1, y0, y1, fillcolor: fill, line: { width: 0 }, layer: "below" as const,
  });

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true, height: 460,
        margin: { t: 12, r: 30, b: 40, l: 48 },
        xaxis: { title: { text: "PER (저평가 ← → 고평가)", font: { size: 12 } }, range: [PER_MIN, PER_MAX], zeroline: false, gridcolor: "#F0F2F5", tickfont: { size: 11 } },
        yaxis: { title: { text: "EPS 성장 (YoY)", font: { size: 12 } }, ticksuffix: "%", range: [-9, Y_TOP], zeroline: false, gridcolor: "#F0F2F5", tickfont: { size: 11 } },
        shapes: [
          rect(PER_MIN, PER_MID, GR_MID, Y_TOP, "rgba(46,125,82,0.07)"),
          rect(PER_MID, PER_MAX, GR_MID, Y_TOP, "rgba(85,126,170,0.045)"),
          rect(PER_MIN, PER_MID, -9, GR_MID, "rgba(0,0,0,0.012)"),
          rect(PER_MID, PER_MAX, -9, GR_MID, "rgba(192,57,43,0.045)"),
          { type: "line", xref: "x", yref: "y", x0: PER_MID, x1: PER_MID, y0: -9, y1: Y_TOP, line: { color: "#E3E6EB", width: 1 }, layer: "below" },
          { type: "line", xref: "x", yref: "y", x0: PER_MIN, x1: PER_MAX, y0: GR_MID, y1: GR_MID, line: { color: "#E3E6EB", width: 1 }, layer: "below" },
        ] as Partial<Plotly.Shape>[],
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
