import { useOverview } from "../hooks/useOverview";
import MetaBadge from "../components/common/MetaBadge";
import MetricCard from "../components/common/MetricCard";
import NavChart from "../components/charts/NavChart";

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

  if (isLoading) return <div>loading overview...</div>;
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

      <NavChart
        points={data.nav_series}
        title="수정기준가 / BM / 초과수익"
        instanceKey={`${fundCode}-${data.nav_series.length}`}
      />
    </section>
  );
}
