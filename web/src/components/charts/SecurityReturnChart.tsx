import { useEffect, useRef, useState } from "react";
import Plot from "react-plotly.js";
import type {
  SecurityReturnPointDTO,
  SecurityTradeMarkerDTO,
  SecurityWeightPointDTO,
} from "../../api/endpoints";

const BUY_COLOR = "#EF553B";  // 매수/발행/설정 ▲ 빨강
const SELL_COLOR = "#636EFA"; // 매도/환매/해지 ▼ 파랑
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

// 매수성(유입) 거래/현금흐름 판별: 매수·발행·설정·유입
const isBuySide = (s: string) =>
  s.includes("매수") || s.includes("발행") || s.includes("설정") || s.includes("유입");

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
  // true=펀드 NAV("전체" 선택) → 마커 legend=설정/해지, false=종목/자산군 → 매수/매도
  navMode?: boolean;
}

// 수익지수(시작=100) 라인 + 매수(▲)/매도(▼) 마커 + 통합 툴팁(x-unified).
// 가격(points)이 없으면 편입비중 영역만으로 폴백(유동성·가격미커버 종목/자산군).
export default function SecurityReturnChart({
  points, trades, weights = [], itemNm, instanceKey, xRange, markupMode = false,
  weightComponents = [], tradeComponents = [], navMode = false,
}: Props) {
  // 줌(x/y) + 측정 상태. 종목/기간(instanceKey) 변경 시 초기화.
  const [xr, setXr] = useState<[string, string] | null>(null);
  const [yRange, setYRange] = useState<[number, number] | null>(null);
  const [measure, setMeasure] =
    useState<{ x0: string; x1: string; y0: number; y1: number; pct: number } | null>(null);
  const lastDown = useRef<{ t: number; x: number; y: number } | null>(null);
  useEffect(() => { setXr(null); setYRange(null); setMeasure(null); }, [instanceKey]);
  // markup 모드를 끄면 측정 표시 제거
  useEffect(() => { if (!markupMode) setMeasure(null); }, [markupMode]);

  const hasPrice = points.length > 0;

  // ── 편입비중 영역: 종목별 stacked(weightComponents) 또는 단일(weights) ──
  const hasWeight = weights.length > 0;
  const wcTot = new Map<string, number>();
  for (const c of weightComponents) wcTot.set(c.name, (wcTot.get(c.name) ?? 0) + c.weight);
  const compNames = [...wcTot.keys()].sort((a, b) => (wcTot.get(b) ?? 0) - (wcTot.get(a) ?? 0));
  const compColor = new Map<string, string>();
  compNames.forEach((nm, i) => compColor.set(nm, PALETTE[i % PALETTE.length]));
  const hasArea = compNames.length > 0 || hasWeight;

  // 가격도 비중도 없으면 표시할 게 없음
  if (!hasPrice && !hasArea) {
    return <div style={{ padding: 12, color: "#6b7280" }}>데이터 없음</div>;
  }

  // 일별 총편입비중(영역 앵커/툴팁 총비중) — weights 우선, 없으면 components 합.
  const wTotByDate = new Map<string, number>();
  if (hasWeight) {
    for (const w of weights) wTotByDate.set(w.date, w.weight);
  } else {
    for (const c of weightComponents)
      wTotByDate.set(c.date, (wTotByDate.get(c.date) ?? 0) + c.weight);
  }

  const dates = points.map((p) => p.date);
  const values = points.map((p) => p.value);

  // 가격 라인 위 값(나란히 정렬된 prior). 가격 없을 땐 총비중 prior 값.
  const priceAt = (d: string): number | null => {
    let best: number | null = null;
    for (const p of points) {
      if (p.date <= d) best = p.value;
      else break;
    }
    return best;
  };
  const wTotDates = [...wTotByDate.keys()].sort();
  const wTotAt = (d: string): number | null => {
    let best: number | null = null;
    for (const dd of wTotDates) {
      if (dd <= d) best = wTotByDate.get(dd) ?? best;
      else break;
    }
    return best;
  };
  // 마커/툴팁 앵커: 가격 있으면 지수축, 없으면 총비중축.
  const anchorDates = hasPrice ? dates : wTotDates;
  const anchorAt = hasPrice ? priceAt : wTotAt;

  const buys = trades.filter((t) => isBuySide(t.side));
  const sells = trades.filter((t) => !isBuySide(t.side));

  const traces: Plotly.Data[] = [];

  if (compNames.length > 0) {
    // 자산군: 종목별 stacked area (색상 구분) — 보조축 y(base)
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
      line: { color: "rgba(129,140,248,0.45)", width: 0.5 },
      fill: "tozeroy",
      fillcolor: "rgba(129,140,248,0.13)",
      hoverinfo: "skip",
    });
  }

  // 영역(편입비중)이 있고 가격도 있으면 수익률 라인/마커를 overlay 축(y2)에 둬 영역 위로.
  // 가격이 없으면(weight-only) 라인 없이 마커만 base y(편입비중)에 둔다.
  const retAxis: "y" | "y2" = hasPrice && hasArea ? "y2" : "y";

  if (hasPrice) {
    traces.push({
      x: dates,
      y: values,
      type: "scatter",
      mode: "lines",
      name: itemNm,
      yaxis: retAxis,
      line: { color: "#374151", width: 1.5 },
      hoverinfo: "skip",
    });
  }

  const markerTrace = (
    ts: SecurityTradeMarkerDTO[],
    name: string,
    color: string,
    symbol: string,
  ): Plotly.Data => ({
    x: ts.map((t) => t.date),
    y: ts.map((t) => anchorAt(t.date)),
    type: "scatter",
    mode: "markers",
    name,
    yaxis: retAxis,
    marker: { color, size: 11, symbol, line: { width: 1, color: "#fff" } },
    hoverinfo: "skip",
  });
  const buyLabel = navMode ? "설정" : "매수";
  const sellLabel = navMode ? "해지" : "매도";
  if (buys.length) traces.push(markerTrace(buys, buyLabel, BUY_COLOR, "triangle-up"));
  if (sells.length) traces.push(markerTrace(sells, sellLabel, SELL_COLOR, "triangle-down"));

  // ── 통합 툴팁(x-unified): 지수 + 편입비중 + 매수/매도 한 박스(일별 비중추이 서식).
  const tradeLinesByDate = new Map<string, string[]>();
  for (const t of trades) {
    const tri = isBuySide(t.side)
      ? `<span style="color:${BUY_COLOR}">▲</span>`
      : `<span style="color:${SELL_COLOR}">▼</span>`;
    const arr = tradeLinesByDate.get(t.date) ?? [];
    arr.push(`${tri} ${t.side} ${t.amount.toFixed(2)}억`);
    tradeLinesByDate.set(t.date, arr);
  }
  // 종목별 분해 맵 (편입비중 하단 / 순매수 하단)
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
  const vByDate = new Map(points.map((p) => [p.date, p.value]));
  const composed = anchorDates.map((d) => {
    const lines: string[] = [];
    if (hasPrice) {
      const v = vByDate.get(d) ?? 0;
      const pct = v - 100; // 지수 시작=100 → 시작일 대비 %변화
      lines.push(`지수 ${v.toFixed(1)} (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`);
    }
    const totW = wTotByDate.get(d);
    if (totW != null) lines.push(`편입비중 ${totW.toFixed(2)}%`);
    const wc = wcByDate.get(d);
    if (wc) {
      for (const c of [...wc].filter((x) => x.weight > 0).sort((a, b) => b.weight - a.weight)) {
        const col = compColor.get(c.name) ?? "#9ca3af";
        lines.push(`&nbsp;<span style="color:${col}">■</span> ${c.name} ${c.weight.toFixed(2)}%`);
      }
    }
    const tr = tradeLinesByDate.get(d);
    if (tr) lines.push(...tr);
    const tc = tcByDate.get(d);
    if (tc) {
      for (const c of tc) {
        const tri = isBuySide(c.side)
          ? `<span style="color:${BUY_COLOR}">▲</span>`
          : `<span style="color:${SELL_COLOR}">▼</span>`;
        lines.push(`&nbsp;${tri} ${c.name} ${c.amount.toFixed(2)}억`);
      }
    }
    return lines.join("<br>");
  });
  traces.push({
    x: anchorDates,
    y: anchorDates.map((d) => anchorAt(d)),
    text: composed,
    type: "scatter",
    mode: "markers",
    name: "",
    yaxis: retAxis,
    marker: { color: "rgba(0,0,0,0)", size: 0.1 },
    showlegend: false,
    hovertemplate: "%{text}<extra></extra>",
  });

  // ── y auto-fit (가격 모드 한정): 주어진 x범위 내 지수 min/max + 8% 패딩 ──
  const fitY = (x0: string, x1: string): [number, number] | null => {
    if (!hasPrice) return null;
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
    // ★ 리셋(더블클릭)은 markup 모드에서도 처리한다 (2026-08-24 사용자 리포트).
    // 여기서 먼저 early-return 하면 ON 상태에서 더블클릭이 먹지 않아 줌이 고정되고,
    // Plotly 내부적으로만 autorange 된 뒤 **다음 렌더에서 묵은 xr 이 재적용**되어
    // OFF 에서 줌을 풀어도 ON 으로 돌아가면 줌 상태가 되살아난다.
    if (e["xaxis.autorange"]) { setXr(null); setYRange(null); setMeasure(null); return; }
    if (markupMode) return;  // select 드래그는 축 범위를 바꾸지 않는다
    const x0 = e["xaxis.range[0]"], x1 = e["xaxis.range[1]"];
    if (x0 !== undefined && x1 !== undefined) {
      setXr([String(x0).slice(0, 10), String(x1).slice(0, 10)]);
      const fy = fitY(String(x0), String(x1));
      if (fy) setYRange(fy);
    }
  };

  // markup 모드 드래그(select) → 시작/종료 지수 %변화율 측정 (가격 모드 한정)
  const onSelected = (e: { range?: { x?: (number | string)[] } } | undefined) => {
    if (!markupMode || !hasPrice || !e?.range?.x) return;
    const [a, b] = e.range.x;
    const p0 = nearest(a), p1 = nearest(b);
    if (p0.date === p1.date) return;  // 폭 0 선택(더블클릭 부산물) → 측정 아님
    const pct = p0.value ? (p1.value / p0.value - 1) * 100 : 0;
    setMeasure({ x0: p0.date, x1: p1.date, y0: p0.value, y1: p1.value, pct });
  };

  const up = measure ? measure.pct >= 0 : true;
  const mColor = up ? UP_COLOR : DOWN_COLOR;
  const annotations = measure
    ? [{
        x: measure.x1, y: measure.y1, xref: "x" as const, yref: retAxis,
        text: `${up ? "▲" : "▼"} ${measure.pct >= 0 ? "+" : ""}${measure.pct.toFixed(2)}%`,
        showarrow: true, arrowhead: 3, arrowwidth: 1.5, arrowcolor: mColor,
        ax: 0, ay: up ? -34 : 34,
        font: { color: mColor, size: 13 },
        bgcolor: "rgba(255,255,255,0.9)", bordercolor: mColor, borderwidth: 1, borderpad: 3,
      }]
    : [];
  const shapes = measure
    ? [{
        type: "line" as const, xref: "x" as const, yref: retAxis,
        x0: measure.x0, y0: measure.y0, x1: measure.x1, y1: measure.y1,
        line: { color: mColor, width: 1, dash: "dot" as const },
      }]
    : [];

  const xAxisRange = xr ?? xRange;

  // 축 구성: 가격+영역=이중축(비중 right base / 수익률 left overlay),
  // 가격만=수익률 단일축, 비중만=편입비중 단일축(left).
  const weightAxis = {
    title: { text: "편입비중", standoff: 8 },
    rangemode: "tozero" as const, ticksuffix: "%", showgrid: false,
  };
  const retYAxis = {
    title: { text: "수익률 지수 (시작=100)" },
    ...(yRange ? { range: yRange, autorange: false as const } : { autorange: true as const }),
  };
  const yAxes =
    hasPrice && hasArea
      ? {
          yaxis: { ...weightAxis, side: "right" as const, automargin: false },
          yaxis2: { ...retYAxis, overlaying: "y" as const, side: "left" as const },
        }
      : hasPrice
        ? { yaxis: retYAxis }
        : { yaxis: { ...weightAxis, side: "left" as const } };

  // ★ 더블클릭 = 줌 리셋. Plotly 에 맡길 수 없어 직접 판정한다 (2026-08-24 사용자 리포트).
  // 실측으로 확인한 제약 2개:
  //  ① select 모드(변화율 ON)에서 Plotly 는 더블클릭을 '선택 해제'로 소비하고
  //     plotly_relayout / plotly_doubleclick 을 **하나도 내보내지 않는다**(이벤트 0건).
  //  ② Plotly 드래그 레이어가 mousedown 에 preventDefault 를 걸어 **native dblclick 자체가
  //     발생하지 않는다** — document capture 단계에서도 안 잡힌다. onDoubleClick 은 무용.
  // 그래서 살아있는 mousedown 2회의 간격·좌표로 직접 판정한다. 축 범위의 단일 소스는
  // xr/yRange state 이므로 이걸 비우는 게 유일하게 확실한 리셋 경로다.
  const onMouseDownCapture = (e: React.MouseEvent) => {
    if ((e.target as Element | null)?.closest?.(".legend")) return;  // 범례는 계열 isolate 용
    const prev = lastDown.current;
    lastDown.current = { t: e.timeStamp, x: e.clientX, y: e.clientY };
    if (prev && e.timeStamp - prev.t < 400
        && Math.abs(e.clientX - prev.x) < 6 && Math.abs(e.clientY - prev.y) < 6) {
      lastDown.current = null;
      setXr(null);
      setYRange(null);
      setMeasure(null);
    }
  };

  return (
    <div style={{ width: "100%", height: "100%" }} onMouseDownCapture={onMouseDownCapture}>
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true,
        height: 480,
        // 하단 margin 을 WeightAreaChart 와 동일(40)하게 → side-by-side x축 baseline 정렬
        margin: { t: 40, r: 62, b: 40, l: 56 },
        dragmode: markupMode ? "select" : "zoom",
        selectdirection: "h",
        xaxis: {
          title: { text: "" }, type: "date",
          ...(xAxisRange ? { range: xAxisRange, autorange: false } : {}),
        },
        ...yAxes,
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
    </div>
  );
}
