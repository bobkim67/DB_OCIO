import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useOverview } from "../hooks/useOverview";
import MetaBadge from "../components/common/MetaBadge";
import MetricCard from "../components/common/MetricCard";
import NavChart from "../components/charts/NavChart";
import LoadingBar from "../components/common/LoadingBar";

interface Props {
  fundCode: string;
}

const PERIOD_ORDER = ["1M", "3M", "6M", "YTD", "1Y", "SI"] as const;
const PERIOD_LABEL: Record<string, string> = {
  "1M": "1M",
  "3M": "3M",
  "6M": "6M",
  YTD: "YTD",
  "1Y": "1Y",
  SI: "설정후",
};

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(2)}%`;
}

export default function OverviewTab({ fundCode }: Props) {
  const { data, isLoading, error } = useOverview(fundCode);

  // 조회기간(날짜 윈도우) — 기본 전체 구간. 펀드 변경 시 리셋.
  const series = data?.nav_series ?? [];
  const fullStart = series[0]?.date ?? "";
  const fullEnd = series.length ? series[series.length - 1].date : "";
  const [start, setStart] = useState(fullStart);
  const [end, setEnd] = useState(fullEnd);
  useEffect(() => {
    setStart(fullStart);
    setEnd(fullEnd);
  }, [fundCode, fullStart, fullEnd]);

  // 선택 구간 슬라이스 + 조회기간 수익률(포트/BM/초과)
  const sliced = useMemo(
    () => series.filter((p) => p.date >= start && p.date <= end),
    [series, start, end],
  );
  const periodRet = useMemo(() => {
    if (sliced.length < 2) return null;
    const f = sliced[0], l = sliced[sliced.length - 1];
    const port = f.nav ? l.nav / f.nav - 1 : null;
    const hasBm = f.bm != null && l.bm != null;
    const bm = hasBm ? (l.bm as number) / (f.bm as number) - 1 : null;
    const excess = port != null && bm != null ? port - bm : null;
    return { port, bm, excess, from: f.date, to: l.date };
  }, [sliced]);

  if (isLoading) return <LoadingBar label="loading overview..." />;
  if (error || !data) {
    return (
      <div style={{ color: "#dc2626" }}>failed to load overview</div>
    );
  }

  const pr = data.period_returns ?? {};
  const bmPr = data.bm_period_returns ?? {};
  const hasAnyPeriod = PERIOD_ORDER.some((k) => k in pr);

  return (
    <section>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
          marginBottom: 12,
        }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>
          {data.fund_name}{" "}
          <span style={{ color: "#6b7280" }}>({data.fund_code})</span>
        </h2>
        <MetaBadge meta={data.meta} />
      </div>

      <div
        style={{
          display: "flex",
          gap: 12,
          marginBottom: 16,
          flexWrap: "wrap",
        }}
      >
        {data.cards.length === 0 ? (
          <div style={{ color: "#6b7280" }}>카드 없음 (fallback)</div>
        ) : (
          data.cards.map((c) => <MetricCard key={c.key} card={c} />)
        )}
      </div>

      {hasAnyPeriod && (
        <div
          style={{
            display: "flex",
            gap: 16,
            padding: "8px 12px",
            background: "#f9fafb",
            borderRadius: 6,
            marginBottom: 16,
            flexWrap: "wrap",
            fontSize: 13,
          }}
        >
          {PERIOD_ORDER.filter((k) => k in pr).map((k) => {
            const portVal = pr[k];
            const hasBm = k in bmPr;
            return (
              <div key={k}>
                <span style={{ color: "#6b7280", marginRight: 4 }}>
                  {PERIOD_LABEL[k]}:
                </span>
                <span
                  style={{
                    color: portVal >= 0 ? "#dc2626" : "#2563eb",
                    fontWeight: 600,
                  }}
                >
                  {fmtPct(portVal)}
                </span>
                {hasBm && (
                  <span
                    style={{
                      color: "#9ca3af",
                      marginLeft: 4,
                      fontSize: 11,
                    }}
                  >
                    (BM {fmtPct(bmPr[k])})
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 조회기간(날짜 윈도우) 위젯 + 해당 기간 수익률 카드 */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 12,
        }}
      >
        <label style={lbl}>
          시작
          <input type="date" value={start} min={fullStart} max={end}
            onChange={(e) => setStart(e.target.value)} style={inp} />
        </label>
        <label style={lbl}>
          종료
          <input type="date" value={end} min={start} max={fullEnd}
            onChange={(e) => setEnd(e.target.value)} style={inp} />
        </label>
        <button
          type="button"
          onClick={() => { setStart(fullStart); setEnd(fullEnd); }}
          style={btn}
        >
          전체
        </button>
        {periodRet && (
          <div style={{ display: "flex", gap: 8, marginLeft: 4 }}>
            {[
              { label: "포트 수익률", v: periodRet.port },
              ...(periodRet.bm != null ? [{ label: "BM 수익률", v: periodRet.bm }] : []),
              ...(periodRet.excess != null ? [{ label: "초과수익", v: periodRet.excess, ex: true }] : []),
            ].map((c) => (
              <div key={c.label} style={card}>
                <div style={{ fontSize: 11, color: "#6b7280" }}>{c.label}</div>
                <div
                  style={{
                    fontSize: 16, fontWeight: 600, fontVariantNumeric: "tabular-nums",
                    color: c.v == null ? "#6b7280"
                      : c.ex ? (c.v >= 0 ? "#16a34a" : "#b91c1c")
                      : (c.v >= 0 ? "#dc2626" : "#2563eb"),
                  }}
                >
                  {c.v == null ? "—" : `${c.v >= 0 ? "+" : ""}${(c.v * 100).toFixed(2)}%`}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <NavChart
        points={sliced}
        title="누적수익률 / BM / 초과수익"
        instanceKey={`${fundCode}-${start}-${end}-${sliced.length}`}
      />
    </section>
  );
}

const lbl: CSSProperties = {
  display: "flex", flexDirection: "column", fontSize: 11, color: "#374151", gap: 4,
};
const inp: CSSProperties = {
  fontSize: 13, padding: "4px 6px", border: "1px solid #d1d5db", borderRadius: 4,
};
const btn: CSSProperties = {
  fontSize: 13, padding: "6px 14px", border: "1px solid #d1d5db", borderRadius: 4,
  background: "#fff", cursor: "pointer", color: "#374151",
};
const card: CSSProperties = {
  padding: "6px 12px", background: "#f9fafb", border: "1px solid #e5e7eb", borderRadius: 6,
};
