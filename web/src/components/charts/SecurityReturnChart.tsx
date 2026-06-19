import { useEffect, useState } from "react";
import Plot from "react-plotly.js";
import type {
  SecurityReturnPointDTO,
  SecurityTradeMarkerDTO,
  SecurityWeightPointDTO,
} from "../../api/endpoints";

const BUY_COLOR = "#EF553B";  // 매수/발행 ▲ 빨강
const SELL_COLOR = "#636EFA"; // 매도/환매 ▼ 파랑
const UP_COLOR = "#EF553B";   // 지수 상승 = 빨강(국내 관행)
const DOWN_COLOR = "#636EFA"; // 지수 하락 = 파랑

// 자산군 편입비중 종목별 stacked area 팔레트 (일별 비중추이 차트와 동일 계열)
const PALETTE = [
  "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
  "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
  "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
  "#c49c94", "#f7b6d2", "#dbdb8d", "#9edae5", "#393b79",
];
function withAlpha(hex: string, a: number): string {
  const h = hex.replace("#", "");
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
}

interface Props {
  points: SecurityReturnPointDTO[];
  trades: SecurityTradeMarkerDTO[];
  weights?: SecurityWeightPointDTO[];
  itemNm: string;
  instanceKey?: string;
  xRange?: [string, string];    // 공통 x 날짜 도메인 (일별 비중추이 차트와 정렬용)
  markupMode?: boolean;         // true=드래그로 %변화율 측정, false=드래그 줌(y 자동보정)
  // 자산군 차트 전용: 툴팁 종목별 분해 (편입비중 하단 / 순매수 하단)
  weightComponents?: { date: string; name: string; weight: number }[];
  tradeComponents?: { date: string; name: string; side: string; amount: number }[];
}

// 종목 수익률 지수(시작=100) 라인 + 매수(▲)/매도(▼) 마커 + 통합 툴팁(x-unified).
// 드래그 줌 시 y축 auto-fit, markupMode 면 드래그=구간 %변화율 markup(↑/↓).
export default function SecurityReturnChart({
  points, trades, weights = [], itemNm, instanceKey, xRange, markupMode = false,
  weightComponents = [], tradeComponents = [],
}: Props) {
  // 줌(x/y) + 측정 상태. 종목/기간(instanceKey) 변경 시 초기화.
  const [xr, setXr] = useState<[string, string] | null>(null);
  const [yRange, setYRange] = useState<[number, number] | null>(null);
  const [measure, setMeasure] =
    useState<{ x0: string; x1: string; y0: number; y1: number; pct: number } | null>(null);
  useEffect(() => { setXr(null); setYRange(null); setMeasure(null); }, [instanceKey]);
  // markup 모드를 끄면 측정 표시 제거
  useEffect(() => { if (!markupMode) setMeasure(null); }, [markupMode]);

  if (points.length === 0) {
    return <div style={{ padding: 12, color: "#6b7280" }}>가격 데이터 없음</div>;
  }

  const dates = points.map((p) => p.date);
  const values = points.map((p) => p.value);

  const yAt = (d: string): number | null => {
    let best: number | null = null;
    for (const p of points) {
      if (p.date <= d) best = p.value;
      else break;
    }
    return best;
  };

  const isBuy = (s: string) => s.includes("매수") || s.includes("발행");
  const buys = trades.filter((t) => isBuy(t.side));
  const sells = trades.filter((t) => !isBuy(t.side));

  const markerTrace = (
    ts: SecurityTradeMarkerDTO[],
    name: string,
    color: string,
    symbol: string,
  ): Plotly.Data => ({
    x: ts.map((t) => t.date),
    y: ts.map((t) => yAt(t.date)),
    type: "scatter",
    mode: "markers",
    name,
    marker: { color, size: 11, symbol, line: { width: 1, color: "#fff" } },
    hoverinfo: "skip",
  });

  const hasWeight = weights.length > 0;
  const traces: Plotly.Data[] = [];

  // 자산군 차트: 종목별 편입비중 색상 맵 (stacked area + 툴팁 swatch 공유)
  const wcTot = new Map<string, number>();
  for (const c of weightComponents) wcTot.set(c.name, (wcTot.get(c.name) ?? 0) + c.weight);
  const compNames = [...wcTot.keys()].sort((a, b) => (wcTot.get(b) ?? 0) - (wcTot.get(a) ?? 0));
  const compColor = new Map<string, string>();
  compNames.forEach((nm, i) => compColor.set(nm, PALETTE[i % PALETTE.length]));

  if (compNames.length > 0) {
    // 자산군: 종목별 stacked area (색상 구분) — 보조축 y2
    const wkey = new Map<string, number>();
    for (const c of weightComponents) wkey.set(`${c.date}|${c.name}`, c.weight);
    const wcDates = [...new Set(weightComponents.map((c) => c.date))].sort();
    for (const nm of compNames) {
      const col = compColor.get(nm) as string;
      traces.push({
        x: wcDates,
        y: wcDates.map((d) => wkey.get(`${d}|${nm}`) ?? 0),
        type: "scatter",
        mode: "lines",
        name: nm,
        yaxis: "y2",
        stackgroup: "wstack",
        line: { color: col, width: 0.3 },
        fillcolor: withAlpha(col, 0.45),
        hoverinfo: "skip",
      });
    }
  } else if (hasWeight) {
    traces.push({
      x: weights.map((w) => w.date),
      y: weights.map((w) => w.weight),
      type: "scatter",
      mode: "lines",
      name: "편입비중",
      yaxis: "y2",
      line: { color: "rgba(129,140,248,0.45)", width: 0.5 },
      fill: "tozeroy",
      fillcolor: "rgba(129,140,248,0.13)",
      hoverinfo: "skip",
    });
  }

  traces.push({
    x: dates,
    y: values,
    type: "scatter",
    mode: "lines",
    name: itemNm,
    line: { color: "#374151", width: 1.5 },
    hoverinfo: "skip",
  });
  if (buys.length) traces.push(markerTrace(buys, "매수/발행", BUY_COLOR, "triangle-up"));
  if (sells.length) traces.push(markerTrace(sells, "매도/환매", SELL_COLOR, "triangle-down"));

  // ── 통합 툴팁(x-unified): 지수 + 편입비중 + 매수/매도 한 박스(일별 비중추이 서식).
  //    dense(모든 날짜) trace 라 인접일 누수 없음. 라인/마커/비중은 hover skip.
  const vByDate = new Map(points.map((p) => [p.date, p.value]));
  const wByDate = new Map(weights.map((w) => [w.date, w.weight]));
  const tradeLinesByDate = new Map<string, string[]>();
  for (const t of trades) {
    const tri = isBuy(t.side)
      ? `<span style="color:${BUY_COLOR}">▲</span>`
      : `<span style="color:${SELL_COLOR}">▼</span>`;
    const arr = tradeLinesByDate.get(t.date) ?? [];
    arr.push(`${tri} ${t.side} ${t.amount.toFixed(2)}억`);
    tradeLinesByDate.set(t.date, arr);
  }
  // 자산군 차트 종목별 분해 맵 (편입비중 하단 / 순매수 하단)
  const wcByDate = new Map<string, { name: string; weight: number }[]>();
  for (const c of weightComponents) {
    const arr = wcByDate.get(c.date) ?? [];
    arr.push({ name: c.name, weight: c.weight });
    wcByDate.set(c.date, arr);
  }
  const tcByDate = new Map<string, { name: string; side: string; amount: number }[]>();
  for (const c of tradeComponents) {
    const arr = tcByDate.get(c.date) ?? [];
    arr.push({ name: c.name, side: c.side, amount: c.amount });
    tcByDate.set(c.date, arr);
  }
  const composed = dates.map((d) => {
    const v = vByDate.get(d) ?? 0;
    const pct = v - 100; // 지수 시작=100 → 시작일 대비 %변화
    const lines = [`지수 ${v.toFixed(1)} (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`];
    if (hasWeight && wByDate.has(d)) {
      lines.push(`편입비중 ${(wByDate.get(d) as number).toFixed(2)}%`);
      const wc = wcByDate.get(d);
      if (wc) {
        for (const c of [...wc].filter((x) => x.weight > 0).sort((a, b) => b.weight - a.weight)) {
          const col = compColor.get(c.name) ?? "#9ca3af";
          lines.push(`&nbsp;<span style="color:${col}">■</span> ${c.name} ${c.weight.toFixed(2)}%`);
        }
      }
    }
    const tr = tradeLinesByDate.get(d);
    if (tr) lines.push(...tr);
    const tc = tcByDate.get(d);
    if (tc) {
      for (const c of tc) {
        const tri = c.side.includes("매수")
          ? `<span style="color:${BUY_COLOR}">▲</span>`
          : `<span style="color:${SELL_COLOR}">▼</span>`;
        lines.push(`&nbsp;${tri} ${c.name} ${c.amount.toFixed(2)}억`);
      }
    }
    return lines.join("<br>");
  });
  traces.push({
    x: dates,
    y: values,
    text: composed,
    type: "scatter",
    mode: "markers",
    name: "",
    marker: { color: "rgba(0,0,0,0)", size: 0.1 },
    showlegend: false,
    hovertemplate: "%{text}<extra></extra>",
  });

  // ── y auto-fit: 주어진 x범위 내 지수 min/max + 8% 패딩 ──
  const fitY = (x0: string, x1: string): [number, number] | null => {
    const t0 = new Date(x0).getTime(), t1 = new Date(x1).getTime();
    const lo = Math.min(t0, t1), hi = Math.max(t0, t1);
    const vs = points
      .filter((p) => { const t = new Date(p.date).getTime(); return t >= lo && t <= hi; })
      .map((p) => p.value);
    if (!vs.length) return null;
    let mn = Math.min(...vs), mx = Math.max(...vs);
    if (mn === mx) { mn -= 1; mx += 1; }
    const pad = (mx - mn) * 0.08;
    return [mn - pad, mx + pad];
  };

  const nearest = (xv: number | string) => {
    const t = typeof xv === "number" ? xv : new Date(xv).getTime();
    let best = points[0], bd = Infinity;
    for (const p of points) {
      const d = Math.abs(new Date(p.date).getTime() - t);
      if (d < bd) { bd = d; best = p; }
    }
    return best;
  };

  // 드래그 줌(markup off) → x범위 갱신 + y auto-fit. 더블클릭(autorange) → 리셋.
  const onRelayout = (e: Record<string, unknown>) => {
    if (markupMode) return;
    if (e["xaxis.autorange"]) { setXr(null); setYRange(null); return; }
    const x0 = e["xaxis.range[0]"], x1 = e["xaxis.range[1]"];
    if (x0 !== undefined && x1 !== undefined) {
      setXr([String(x0).slice(0, 10), String(x1).slice(0, 10)]);
      const fy = fitY(String(x0), String(x1));
      if (fy) setYRange(fy);
    }
  };

  // markup 모드 드래그(select) → 시작/종료 지수 %변화율 측정
  const onSelected = (e: { range?: { x?: (number | string)[] } } | undefined) => {
    if (!markupMode || !e?.range?.x) return;
    const [a, b] = e.range.x;
    const p0 = nearest(a), p1 = nearest(b);
    const pct = p0.value ? (p1.value / p0.value - 1) * 100 : 0;
    setMeasure({ x0: p0.date, x1: p1.date, y0: p0.value, y1: p1.value, pct });
  };

  const up = measure ? measure.pct >= 0 : true;
  const mColor = up ? UP_COLOR : DOWN_COLOR;
  const annotations = measure
    ? [{
        x: measure.x1, y: measure.y1, xref: "x" as const, yref: "y" as const,
        text: `${up ? "▲" : "▼"} ${measure.pct >= 0 ? "+" : ""}${measure.pct.toFixed(2)}%`,
        showarrow: true, arrowhead: 3, arrowwidth: 1.5, arrowcolor: mColor,
        ax: 0, ay: up ? -34 : 34,
        font: { color: mColor, size: 13 },
        bgcolor: "rgba(255,255,255,0.9)", bordercolor: mColor, borderwidth: 1, borderpad: 3,
      }]
    : [];
  const shapes = measure
    ? [{
        type: "line" as const, xref: "x" as const, yref: "y" as const,
        x0: measure.x0, y0: measure.y0, x1: measure.x1, y1: measure.y1,
        line: { color: mColor, width: 1, dash: "dot" as const },
      }]
    : [];

  const xAxisRange = xr ?? xRange;

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true,
        height: 360,
        margin: { t: 40, r: 62, b: 36, l: 56 },
        dragmode: markupMode ? "select" : "zoom",
        selectdirection: "h",
        xaxis: {
          title: { text: "" }, type: "date",
          ...(xAxisRange ? { range: xAxisRange, autorange: false } : {}),
        },
        yaxis: {
          title: { text: "수익률 지수 (시작=100)" },
          ...(yRange ? { range: yRange, autorange: false } : { autorange: true }),
        },
        ...(hasWeight
          ? {
              yaxis2: {
                title: { text: "편입비중 %", standoff: 8 },
                overlaying: "y", side: "right", rangemode: "tozero",
                ticksuffix: "%", showgrid: false, automargin: false,
              },
            }
          : {}),
        annotations,
        shapes,
        hovermode: "x unified",
        hoverlabel: { align: "left" },   // 값 우측정렬 들여쓰기 제거
        legend: { orientation: "h", x: 0, y: 1.04, xanchor: "left", yanchor: "bottom", font: { size: 11 } },
      }}
      onRelayout={onRelayout}
      onSelected={onSelected}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
