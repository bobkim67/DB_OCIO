import type { MetricCardDTO } from "../../api/endpoints";

interface Props {
  card: MetricCardDTO;
}

function formatValue(v: number, unit: MetricCardDTO["unit"]): string {
  if (unit === "pct") return `${(v * 100).toFixed(2)}%`;
  if (unit === "bp") return `${(v * 10000).toFixed(0)}bp`;
  if (unit === "currency") return v.toLocaleString("ko-KR");
  return v.toFixed(4);
}

export default function MetricCard({ card }: Props) {
  const positive = card.value >= 0;
  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 6,
        padding: "12px 16px",
        minWidth: 160,
        background: "#fff",
      }}
    >
      <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>
        {card.label}
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: positive ? "#dc2626" : "#2563eb",
        }}
      >
        {formatValue(card.value, card.unit)}
      </div>
    </div>
  );
}
