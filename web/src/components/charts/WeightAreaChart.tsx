import Plot from "react-plotly.js";
import type { WeightHistoryPointDTO, WeightMarkerDTO } from "../../api/endpoints";

// 6버킷 고정 색상 (국내주식/해외주식/국내채권/해외채권/금·대체/유동성)
const BUCKET_COLORS: Record<string, string> = {
  국내주식: "#EF553B",
  해외주식: "#636EFA",
  국내채권: "#00CC96",
  해외채권: "#AB63FA",
  "금/대체": "#FFA15A",
  유동성: "#B6E880",
};

// 종목 기준용 팔레트 (반복)
const PALETTE = [
  "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
  "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
  "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
  "#c49c94", "#f7b6d2", "#dbdb8d", "#9edae5", "#393b79",
];

// 매매 마커 색 (종목수익률 차트와 동일)
const BUY_COLOR = "#EF553B";  // 순매수 ▲ 빨강
const SELL_COLOR = "#636EFA"; // 순매도 ▼ 파랑
const FILL_ALPHA = 0.65;      // 영역 톤 다운 — 마커 가독성 확보

function withAlpha(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

interface Props {
  points: WeightHistoryPointDTO[];
  keys: string[];               // 정렬된 key (security: 평균비중 desc, asset: 고정순)
  level: "security" | "asset";
  topN?: number;                // security 한정. 0/undefined → 전체
  markers?: WeightMarkerDTO[];  // 일자·key별 순매수 마커 (▲▼)
  instanceKey?: string;         // fund/level 변경 시 리마운트
  xRange?: [string, string];    // 공통 x 날짜 도메인 (종목수익률 차트와 정렬용)
}

export default function WeightAreaChart({
  points, keys, level, topN, markers = [], instanceKey, xRange,
}: Props) {
  if (points.length === 0) {
    return <div style={{ padding: 16, color: "#6b7280" }}>데이터 없음</div>;
  }

  const dates = Array.from(new Set(points.map((p) => p.date))).sort();

  // (date, key) → weight 피벗
  const byDate = new Map<string, Map<string, number>>();
  for (const p of points) {
    let m = byDate.get(p.date);
    if (!m) { m = new Map(); byDate.set(p.date, m); }
    m.set(p.key, (m.get(p.key) ?? 0) + p.weight);
  }

  // 표시 key 결정 (security + topN 이면 나머지 '기타' 묶음)
  let displayKeys = keys;
  let etcKeys: string[] = [];
  if (level === "security" && topN && topN > 0 && keys.length > topN) {
    displayKeys = keys.slice(0, topN);
    etcKeys = keys.slice(topN);
  }

  const colorOf = (k: string, i: number) => {
    if (k === "유동성") return BUCKET_COLORS["유동성"]; // 묶음 밴드는 고정 색
    if (level === "asset") return BUCKET_COLORS[k] ?? PALETTE[i % PALETTE.length];
    return PALETTE[i % PALETTE.length];
  };

  // 일자별 거래 요약 — 표시되는 key(displayKeys)의 거래만. 건별 줄바꿈(<br>),
  // 정렬: 매수 먼저 → 금액 내림차순. (BA정산 제외된 markers 사용)
  const shownKeySet = new Set(displayKeys);
  const dayTrades = new Map<string, { buy: boolean; key: string; amt: number }[]>();
  for (const mm of markers) {
    if (!shownKeySet.has(mm.key) || mm.net_eok === 0) continue;
    const arr = dayTrades.get(mm.date) ?? [];
    arr.push({ buy: mm.net_eok > 0, key: mm.key, amt: Math.abs(mm.net_eok) });
    dayTrades.set(mm.date, arr);
  }
  // 줄머리 도형: 매수=빨강▲ / 매도=파랑▼ (차트 마커와 동일)
  const tri = (buy: boolean) =>
    buy
      ? `<span style="color:${BUY_COLOR}">▲</span>`
      : `<span style="color:${SELL_COLOR}">▼</span>`;
  const daySummary = new Map<string, string>();
  for (const [d, arr] of dayTrades) {
    arr.sort((a, b) => (a.buy !== b.buy ? (a.buy ? -1 : 1) : b.amt - a.amt));
    daySummary.set(
      d,
      arr
        .map((t) => `${tri(t.buy)} ${t.buy ? "매수" : "매도"} ${t.key} ${t.amt.toFixed(1)}억`)
        .join("<br>"),
    );
  }

  // 누적 영역은 scattergl fill 왜곡 이슈로 항상 SVG scatter (NavChart 주석 참조).
  // 영역 trace 는 렌더 전용(hoverinfo skip). 0% 행을 툴팁에서 빼기 위해 hover 는
  // 아래 invisible trace 가 담당(0%=y null → x-unified 행 미노출).
  const traces: Plotly.Data[] = displayKeys.map((k, i) => ({
    x: dates,
    y: dates.map((d) => byDate.get(d)?.get(k) ?? 0),
    type: "scatter",
    mode: "lines",
    name: k,
    stackgroup: "one",
    line: { width: 0.5, color: colorOf(k, i) },
    fillcolor: withAlpha(colorOf(k, i), FILL_ALPHA),
    hoverinfo: "skip",
  }));

  if (etcKeys.length > 0) {
    const etcY = dates.map((d) => {
      const m = byDate.get(d);
      if (!m) return 0;
      let s = 0;
      for (const k of etcKeys) s += m.get(k) ?? 0;
      return s;
    });
    traces.push({
      x: dates,
      y: etcY,
      type: "scatter",
      mode: "lines",
      name: `기타 (${etcKeys.length})`,
      stackgroup: "one",
      line: { width: 0.5, color: "#9ca3af" },
      fillcolor: withAlpha("#9ca3af", FILL_ALPHA),
      hoverinfo: "skip",
    });
  }

  // (호버는 아래 단일 composed trace 가 담당 — 자산군 차트 서식 동일)

  // ── 매매 마커 (밴드 상단 경계에 ▲/▼) ─────────────────────────
  // 누적 스택 순서 = displayKeys 순서. 밴드 k 상단 = displayKeys[0..idx(k)] 합.
  // 표시 안 되는 key(기타로 묶인 종목)의 마커는 드롭.
  const idxOf = new Map(displayKeys.map((k, i) => [k, i]));
  // 마커 날짜가 스냅샷 날짜에 정확히 없으면 직전 영업일(≤) 사용 (dates 는 오름차순)
  const lastDateLE = (d: string): string | null => {
    let best: string | null = null;
    for (const dd of dates) {
      if (dd <= d) best = dd;
      else break;
    }
    return best;
  };
  const cumTopAt = (date: string, key: string): number | null => {
    const i = idxOf.get(key);
    if (i === undefined) return null;
    let m = byDate.get(date);
    if (!m) {
      const d2 = lastDateLE(date);
      if (d2) m = byDate.get(d2);
    }
    if (!m) return null;
    let s = 0;
    for (let j = 0; j <= i; j++) s += m.get(displayKeys[j]) ?? 0;
    return s;
  };

  const shown = markers.filter((mm) => idxOf.has(mm.key));
  const buyM = shown.filter((mm) => mm.net_eok > 0);
  const sellM = shown.filter((mm) => mm.net_eok < 0);

  const markerTrace = (
    arr: WeightMarkerDTO[],
    name: string,
    color: string,
    symbol: string,
  ): Plotly.Data => ({
    x: arr.map((mm) => mm.date),
    y: arr.map((mm) => cumTopAt(mm.date, mm.key)),
    type: "scatter",
    mode: "markers",
    name,
    // 밴드색과 겹쳐도 보이도록 크게 + 흰 테두리
    marker: { color, size: 12, symbol, line: { width: 1.5, color: "#fff" } },
    // x-unified 호버는 각 trace의 '커서 x에 가장 가까운 점'을 표시 → 마커가
    // 거래일(예: 2/23) 이후 날짜 툴팁까지 계속 새어 나옴. 마커는 호버 비교에서
    // 제외(시각 삼각형만 유지). 금액은 상단 거래내역 표 참조.
    hoverinfo: "skip",
  });

  if (buyM.length) traces.push(markerTrace(buyM, "순매수", BUY_COLOR, "triangle-up"));
  if (sellM.length) traces.push(markerTrace(sellM, "순매도", SELL_COLOR, "triangle-down"));

  // ── 통합 툴팁(x-unified, 자산군 차트와 동일 서식): dense composed text.
  //   종목별 비중 = ■색 swatch(비중>0, 내림차순) + 거래일 매매줄. 매매없는 날은
  //   비중줄만(상단 빈줄 없음). dense(모든 날짜 점)라 인접일 누수 없음.
  const composed = dates.map((d) => {
    const m = byDate.get(d);
    const rows: { k: string; w: number; color: string }[] = [];
    displayKeys.forEach((k, i) => {
      const w = m?.get(k) ?? 0;
      if (w > 0) rows.push({ k, w, color: colorOf(k, i) });
    });
    if (etcKeys.length > 0) {
      const s = etcKeys.reduce((a, kk) => a + (m?.get(kk) ?? 0), 0);
      if (s > 0) rows.push({ k: `기타 (${etcKeys.length})`, w: s, color: "#9ca3af" });
    }
    rows.sort((a, b) => b.w - a.w);
    const lines = rows.map(
      (r) => `<span style="color:${r.color}">■</span> ${r.k} ${r.w.toFixed(1)}%`);
    const ts = daySummary.get(d);
    if (ts) lines.push(ts);
    return lines.join("<br>");
  });
  traces.push({
    x: dates,
    y: dates.map(() => 100),
    text: composed,
    type: "scatter",
    mode: "markers",
    name: "",
    marker: { color: "rgba(0,0,0,0)", size: 0.1 },
    showlegend: false,
    hovertemplate: "%{text}<extra></extra>",
  });

  return (
    <Plot
      key={instanceKey ?? ""}
      data={traces}
      layout={{
        autosize: true,
        height: 480,
        // l/r margin 을 종목수익률 차트와 동일하게 → x 날짜 눈금 위치 정렬
        margin: { t: 40, r: 62, b: 40, l: 56 },
        // 공통 x 날짜 도메인 고정 → 종목수익률 차트와 날짜 눈금 x위치 정렬
        xaxis: { title: { text: "" }, type: "date",
                 ...(xRange ? { range: xRange, autorange: false } : {}) },
        // 상단 5% 패딩 — 100% 밴드 상단의 순매수/순매도 ▲▼ 마커가 잘리지 않게.
        yaxis: { title: { text: "비중 (%)" }, range: [0, 105], ticksuffix: "%", dtick: 20 },
        hovermode: "x unified",
        hoverlabel: { align: "left" },   // 값 우측정렬 들여쓰기 제거
        // legend 상단 가로 (종목수익률 차트와 동일 스타일)
        legend: { orientation: "h", x: 0, y: 1.04, xanchor: "left", yanchor: "bottom", font: { size: 11 } },
        showlegend: true,
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
