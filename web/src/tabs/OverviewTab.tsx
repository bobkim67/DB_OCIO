import { useOverview } from "../hooks/useOverview";
import MetaBadge from "../components/common/MetaBadge";
import MetricCard from "../components/common/MetricCard";
import NavChart from "../components/charts/NavChart";

interface Props {
  fundCode: string;
}

export default function OverviewTab({ fundCode }: Props) {
  const { data, isLoading, error } = useOverview(fundCode);

  if (isLoading) return <div>loading overview...</div>;
  if (error || !data) {
    return (
      <div style={{ color: "#dc2626" }}>failed to load overview</div>
    );
  }

  return (
    <section>
      <div
        style={{
          display: "flex",
          alignItems: "center",
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

      <NavChart points={data.nav_series} title="수정기준가" />
    </section>
  );
}
