import { useMemo, useState } from "react";
import Plot from "react-plotly.js";
import type {
  BrinsonBmComponentDTO,
  BrinsonDailyClassDTO,
  BrinsonDailyPointDTO,
} from "../../api/endpoints";

// 자산군 색상 (Brinson 분류). 미정의는 팔레트 fallback.
const CLASS_COLORS: Record<string, string> = {
  국내주식: "#EF553B",
  해외주식: "#636EFA",
  국내채권: "#00CC96",
  해외채권: "#AB63FA",
  대체: "#FFA15A",
  대체투자: "#FFA15A",
  FX: "#19D3F3",
  유동성및기타: "#B6E880",
  유동성: "#B6E880",
  주식: "#EF553B",
  채권: "#00CC96",
};
const PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"];
const colorOf = (c: string, i: number) => CLASS_COLORS[c] ?? PALETTE[i % PALETTE.length];

const ROW_ORDER = [
  "주식", "채권", "국내주식", "국내채권", "해외주식", "해외채권",
  "대체", "대체투자", "FX", "유동성및기타", "유동성",
];
const ORDER_MAP = new Map(ROW_ORDER.map((c, i) => [c, i]));

const WGT_FILL = "rgba(135,206,250,0.45)"; // 비중/차이 영역 공통 — 하늘색 파스텔(테두리 없음)
const AP_LINE = "#000080"; // AP 라인 — 남색(navy)
const BM_LINE = "#8B4513"; // BM 라인 — 갈색(brown) 실선

// 좌/우 두 축의 0점을 같은 높이에 맞춰 범위 산출 (clipping 없이).
function alignZero(a: number[], b: number[]): [[number, number], [number, number]] {
  const aMin = Math.min(0, ...a), aMax = Math.max(0, ...a);
  const bMin = Math.min(0, ...b), bMax = Math.max(0, ...b);
  const aBelow = -aMin, aAbove = aMax, bBelow = -bMin, bAbove = bMax;
  const aTot = aBelow + aAbove || 1, bTot = bBelow + bAbove || 1;
  const belowFrac = Math.max(aBelow / aTot, bBelow / bTot);
  const aboveFrac = Math.max(aAbove / aTot, bAbove / bTot);
  const pn = belowFrac / (belowFrac + aboveFrac || 1); // zero 위치(아래로부터)
  const qn = 1 - pn;
  const pad = 1.06;
  const aH = (Math.max(pn > 0 ? aBelow / pn : 0, qn > 0 ? aAbove / qn : 0) || 1) * pad;
  const bH = (Math.max(pn > 0 ? bBelow / pn : 0, qn > 0 ? bAbove / qn : 0) || 1) * pad;
  return [[-pn * aH, qn * aH], [-pn * bH, qn * bH]];
}

// 부호 포함 2자리 문자열. Plotly 의 `%{y:+.2f}` 가 일부 버전서 무시돼 raw 값(20자리)이
// 노출되는 문제를 피하려 customdata 에 미리 포맷한 문자열을 넣고 `%{customdata}` 로 표기.
const signed2 = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2);

type Mode = "all" | "alloc" | "select";

interface Props {
  daily: BrinsonDailyPointDTO[];
  dailyClass: BrinsonDailyClassDTO[];
  bmSource: string; // "BM" | "SAA" | "none"
  bmComponents: BrinsonBmComponentDTO[];
}

const plotConfig = { displayModeBar: false, responsive: true } as const;
const legendCfg = { orientation: "h", x: 0, y: 1.08, xanchor: "left", yanchor: "bottom", font: { size: 11 } } as const;

export default function BrinsonTrendPanel({ daily, dailyClass, bmSource, bmComponents }: Props) {
  const classes = useMemo(() => {
    const set = new Set(dailyClass.map((r) => r.asset_class));
    return [...set].sort((a, b) => (ORDER_MAP.get(a) ?? 99) - (ORDER_MAP.get(b) ?? 99));
  }, [dailyClass]);

  // 자산군 → BM 지수명 (legend 표기). 여러 컴포넌트면 콤마. SAA(name=자산군명)는 스킵.
  const bmIndexByClass = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of bmComponents) {
      if (!c.name || c.name === c.asset_class) continue;
      const prev = m.get(c.asset_class);
      m.set(c.asset_class, prev ? `${prev}, ${c.name}` : c.name);
    }
    return m;
  }, [bmComponents]);
  const idxLabel = (c: string) => {
    const idx = bmIndexByClass.get(c);
    return idx ? `${c} (${idx})` : c;
  };

  const [mode, setMode] = useState<Mode>("all");
  const [sel, setSel] = useState<string>("");

  const dates = useMemo(() => daily.map((d) => String(d.date)), [daily]);
  const hasBm = bmSource !== "none";
  // BM 없는(SAA) 펀드는 라벨을 "SAA"로 표기. (그 외 "BM")
  const BM = bmSource === "SAA" ? "SAA" : "BM";

  const byClass = useMemo(() => {
    const m = new Map<string, BrinsonDailyClassDTO[]>();
    for (const r of dailyClass) {
      const arr = m.get(r.asset_class) ?? [];
      arr.push(r);
      m.set(r.asset_class, arr);
    }
    for (const arr of m.values()) arr.sort((a, b) => (a.date < b.date ? -1 : 1));
    return m;
  }, [dailyClass]);

  // 진단(alloc/select) 모드는 '전체 자산군' 없이 항상 한 자산군 선택 (기본=첫 자산군)
  const effSel = mode !== "all" && !sel && classes.length ? classes[0] : sel;
  const shownClasses = effSel ? classes.filter((c) => c === effSel) : classes;

  if (daily.length === 0) {
    return <div style={{ padding: 12, color: "#6b7280" }}>추이 데이터 없음</div>;
  }

  // ── 전체 모드 좌측: 차이(영역) + AP/BM 누적 라인(남색/갈색) ──
  const allCum: Plotly.Data[] = (() => {
    if (!sel) {
      const t: Plotly.Data[] = [];
      if (hasBm) {
        const ey = dates.map((_, i) => daily[i].ap_cum - daily[i].bm_cum);
        t.push({
          x: dates, y: ey, customdata: ey.map(signed2),
          type: "scatter", mode: "lines", name: `AP−${BM} 초과`, fill: "tozeroy",
          line: { width: 0 }, fillcolor: WGT_FILL,
          hovertemplate: "초과 %{customdata}%p<extra></extra>",
        });
      }
      t.push({
        x: dates, y: daily.map((d) => d.ap_cum), type: "scatter", mode: "lines",
        name: "AP 누적", line: { width: 2, color: AP_LINE },
        hovertemplate: "AP %{y:.2f}%<extra></extra>",
      });
      if (hasBm) t.push({
        x: dates, y: daily.map((d) => d.bm_cum), type: "scatter", mode: "lines",
        name: `${BM} 누적`, line: { width: 2, color: BM_LINE },
        hovertemplate: `${BM} %{y:.2f}%<extra></extra>`,
      });
      return t;
    }
    const rows = byClass.get(sel) ?? [];
    const x = rows.map((r) => String(r.date));
    const t: Plotly.Data[] = [];
    if (hasBm) {
      const ecy = rows.map((r) => r.ap_contrib_cum - r.bm_contrib_cum);
      t.push({
        x, y: ecy, customdata: ecy.map(signed2),
        type: "scatter", mode: "lines", name: `AP−${BM} 초과기여`, fill: "tozeroy",
        line: { width: 0 }, fillcolor: WGT_FILL,
        hovertemplate: "초과기여 %{customdata}%p<extra></extra>",
      });
    }
    t.push({
      x, y: rows.map((r) => r.ap_contrib_cum), type: "scatter", mode: "lines",
      name: `${sel} AP기여`, line: { width: 2, color: AP_LINE },
      hovertemplate: "AP기여 %{y:.2f}%<extra></extra>",
    });
    if (hasBm) t.push({
      x, y: rows.map((r) => r.bm_contrib_cum), type: "scatter", mode: "lines",
      name: `${sel} ${BM}기여`, line: { width: 2, color: BM_LINE },
      hovertemplate: `${BM}기여 %{y:.2f}%<extra></extra>`,
    });
    return t;
  })();

  // ── 전체 모드 우측: 비중추이 / AP vs BM(비중) ──
  const allWgt: Plotly.Data[] = (() => {
    if (!sel) {
      return classes.filter((c) => c !== "FX").map((c, i) => {
        const rows = byClass.get(c) ?? [];
        return {
          x: rows.map((r) => String(r.date)), y: rows.map((r) => r.ap_weight),
          type: "scatter", mode: "lines", name: c, stackgroup: "w",
          line: { width: 0.5, color: colorOf(c, i) }, fillcolor: colorOf(c, i),
          hovertemplate: `${c} %{y:.1f}%<extra></extra>`,
        } as Plotly.Data;
      });
    }
    const rows = byClass.get(sel) ?? [];
    const t: Plotly.Data[] = [{
      x: rows.map((r) => String(r.date)), y: rows.map((r) => r.ap_weight),
      type: "scatter", mode: "lines", name: `${sel} AP비중`,
      fill: "tozeroy", line: { width: 0 }, fillcolor: WGT_FILL,
      hovertemplate: "AP비중 %{y:.1f}%<extra></extra>",
    }];
    if (hasBm) t.push({
      x: rows.map((r) => String(r.date)), y: rows.map((r) => r.bm_weight),
      type: "scatter", mode: "lines", name: `${sel} ${BM} 비중`,
      line: { width: 1.8, color: BM_LINE, dash: "dash" }, hovertemplate: `${BM} 비중 %{y:.1f}%<extra></extra>`,
    });
    return t;
  })();

  // ── 진단(alloc/select): 단일 이중축 차트. 영역=좌축(base), 라인=우축(overlay,앞). ──
  const isAlloc = mode === "alloc";
  const diagCombined: Plotly.Data[] = shownClasses.flatMap((c) => {
    const rows = byClass.get(c) ?? [];
    const x = rows.map((r) => String(r.date));
    const idx = bmIndexByClass.get(c);
    if (isAlloc) {
      // 영역(좌축)=AP−BM 비중차 · 라인(우축)=BM지수 누적수익률(갈색)
      const wd = rows.map((r) => r.ap_weight - r.bm_weight);
      return [
        {
          x, y: wd, customdata: wd.map(signed2), type: "scatter", mode: "lines",
          name: `AP−${BM} 비중차(좌)`, fill: "tozeroy",
          line: { width: 0 }, fillcolor: WGT_FILL,
          hovertemplate: `AP−${BM} 비중차 %{customdata}%p<extra></extra>`,
        },
        {
          x, y: rows.map((r) => r.bm_ret_cum), type: "scatter", mode: "lines",
          name: idxLabel(c), yaxis: "y2", line: { width: 2, color: BM_LINE },
          hovertemplate: `${idxLabel(c)} %{y:.2f}%<extra></extra>`,
        },
      ] as Plotly.Data[];
    }
    // Selection: 영역(좌축)=AP−BM 수익률차 · 라인(우축)=AP수익률(남색)/BM수익률(갈색). BM비중은 범례.
    const bmW = rows.length ? rows[rows.length - 1].bm_weight : 0;
    const bmName = `${c} ${BM}수익률${idx ? ` (${idx})` : ""} ·비중 ${bmW.toFixed(1)}%`;
    // Selection 은 차이·라인 모두 %수익률 단위 → 단일축(동기화). 라인 간격이 곧 수익률차.
    const rd = rows.map((r) => r.ap_ret_cum - r.bm_ret_cum);
    return [
      {
        x, y: rd, customdata: rd.map(signed2), type: "scatter", mode: "lines",
        name: `AP−${BM} 수익률차`, fill: "tozeroy",
        line: { width: 0 }, fillcolor: WGT_FILL,
        hovertemplate: `AP−${BM} 수익률차 %{customdata}%p<extra></extra>`,
      },
      {
        x, y: rows.map((r) => r.ap_ret_cum), type: "scatter", mode: "lines",
        name: `${c} AP수익률`, line: { width: 2, color: AP_LINE },
        hovertemplate: `${c} AP %{y:.2f}%<extra></extra>`,
      },
      {
        x, y: rows.map((r) => r.bm_ret_cum), type: "scatter", mode: "lines",
        name: bmName, line: { width: 2, color: BM_LINE },
        hovertemplate: `${c} ${BM} %{y:.2f}%<extra></extra>`,
      },
    ] as Plotly.Data[];
  });

  // 전체 모드용 단순 레이아웃
  const baseLayout = (yTitle: string, rangeTo100?: boolean): Partial<Plotly.Layout> => ({
    autosize: true, height: 340, margin: { t: 28, r: 16, b: 36, l: 52 },
    xaxis: { title: { text: "" }, type: "date" },
    yaxis: {
      title: { text: yTitle }, ticksuffix: "%", hoverformat: ".2f",
      zeroline: true, zerolinecolor: "#9ca3af", zerolinewidth: 1,
      ...(rangeTo100 ? { range: [0, 100] as [number, number] } : {}),
    },
    hovermode: "x unified", hoverlabel: { align: "left" }, legend: legendCfg,
  });

  // 진단: 좌축(차이 영역)·우축(수익률 라인) 0점 동기화
  const diagRows = shownClasses.length ? byClass.get(shownClasses[0]) ?? [] : [];
  const diffData = isAlloc
    ? diagRows.map((r) => r.ap_weight - r.bm_weight)
    : diagRows.map((r) => r.ap_ret_cum - r.bm_ret_cum);
  const levelData = isAlloc
    ? diagRows.map((r) => r.bm_ret_cum)
    : diagRows.flatMap((r) => [r.ap_ret_cum, r.bm_ret_cum]);
  const [diffRange, levelRange] = diagRows.length
    ? alignZero(diffData, levelData)
    : [undefined, undefined];

  const dualLayout: Partial<Plotly.Layout> = {
    autosize: true, height: 400, margin: { t: 28, r: 60, b: 36, l: 56 },
    xaxis: { title: { text: "" }, type: "date" },
    yaxis: {
      title: { text: isAlloc ? `AP−${BM} 비중차 (%p)` : `AP−${BM} 수익률차 (%p)` }, ticksuffix: "%",
      hoverformat: ".2f",
      zeroline: true, zerolinecolor: "#9ca3af", zerolinewidth: 1,
      ...(diffRange ? { range: diffRange } : {}),
    },
    yaxis2: {
      title: { text: isAlloc ? `${BM} 누적수익률 (%)` : "자산군 누적수익률 (%)" }, ticksuffix: "%",
      hoverformat: ".2f",
      overlaying: "y", side: "right", showgrid: false, zeroline: false,
      ...(levelRange ? { range: levelRange } : {}),
    },
    hovermode: "x unified", hoverlabel: { align: "left" }, legend: legendCfg,
  };

  // Selection 전용 단일축 — 차이 영역과 AP/BM 수익률 라인이 같은 %수익률 축 공유(동기화).
  const selectLayout: Partial<Plotly.Layout> = {
    autosize: true, height: 400, margin: { t: 28, r: 16, b: 36, l: 56 },
    xaxis: { title: { text: "" }, type: "date" },
    yaxis: {
      title: { text: "수익률 (%)" }, ticksuffix: "%", hoverformat: ".2f",
      zeroline: true, zerolinecolor: "#9ca3af", zerolinewidth: 1,
    },
    hovermode: "x unified", hoverlabel: { align: "left" }, legend: legendCfg,
  };

  const hint = isAlloc
    ? `Allocation = Σ (AP−${BM} 비중차)ₜ × ${BM}일별수익ₜ (경로적분). 우축 라인=${BM}지수 누적수익률, 좌축 영역=AP−${BM} 비중차 (0점 동기화).`
    : mode === "select"
      ? `Selection = ${BM}비중(고정) × Σ (AP−${BM} 일별수익차)ₜ. 라인=AP·${BM} 자산군수익률(라인 간격=종목선택 효과), 영역=AP−${BM} 수익률차. 단일축(동기화). ${BM}비중은 범례.`
      : sel ? `좌: ${sel} AP·${BM} 누적기여 + 초과(영역) · 우: ${sel} 비중 vs ${BM}` : `AP·${BM} 누적수익 + 초과(영역)`;

  const radio = (m: Mode, label: string) => (
    <button
      key={m}
      onClick={() => setMode(m)}
      style={{
        fontSize: 12, padding: "4px 12px", border: "none", cursor: "pointer",
        background: mode === m ? "#2563eb" : "#fff",
        color: mode === m ? "#fff" : "#374151",
      }}
    >
      {label}
    </button>
  );

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        <h3 style={{ fontSize: 14, margin: 0 }}>수익률 분석</h3>
        <select
          value={effSel}
          onChange={(e) => setSel(e.target.value)}
          style={{ fontSize: 12, padding: "3px 6px" }}
          title="자산군 필터"
        >
          {mode === "all" && <option value="">전체 (AP vs {BM})</option>}
          {classes.map((c) => (
            <option key={c} value={c}>{idxLabel(c)}</option>
          ))}
        </select>
        <div style={{ display: "inline-flex", border: "1px solid #d1d5db", borderRadius: 4, overflow: "hidden" }}>
          {radio("all", "전체")}
          {radio("alloc", "Allocation")}
          {radio("select", "Selection")}
        </div>
      </div>
      <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 6 }}>{hint}</div>

      {mode === "all" ? (
        !sel ? (
          // 전체 자산군: 누적수익(+초과 영역)만 — 우측 비중 stacked 제거
          <Plot
            data={allCum}
            layout={baseLayout("누적 수익률 (%)")}
            config={plotConfig} useResizeHandler style={{ width: "100%", height: "100%" }}
          />
        ) : (
          <div style={{ display: "flex", gap: 16, alignItems: "stretch", flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 420px", minWidth: 0 }}>
              <Plot
                data={allCum}
                layout={baseLayout("누적 기여수익률 (%)")}
                config={plotConfig} useResizeHandler style={{ width: "100%", height: "100%" }}
              />
            </div>
            <div style={{ flex: "1 1 420px", minWidth: 0 }}>
              <Plot
                data={allWgt}
                layout={baseLayout("비중 (%)")}
                config={plotConfig} useResizeHandler style={{ width: "100%", height: "100%" }}
              />
            </div>
          </div>
        )
      ) : (
        <Plot
          data={diagCombined}
          layout={mode === "select" ? selectLayout : dualLayout}
          config={plotConfig} useResizeHandler style={{ width: "100%", height: "100%" }}
        />
      )}
    </div>
  );
}
