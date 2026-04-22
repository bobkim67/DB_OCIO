import { useState } from "react";
import { useFunds } from "../hooks/useFunds";

export default function DashboardPage() {
  const { data, isLoading, error } = useFunds();
  const [selected, setSelected] = useState<string>("08K88");

  if (isLoading) return <div style={{ padding: 16 }}>loading funds...</div>;
  if (error || !data) {
    return (
      <div style={{ padding: 16, color: "#dc2626" }}>
        failed to load /api/funds
      </div>
    );
  }

  return (
    <div style={{ padding: 16, fontFamily: "system-ui, sans-serif" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 16,
          paddingBottom: 12,
          borderBottom: "1px solid #e5e7eb",
        }}
      >
        <h1 style={{ fontSize: 18, margin: 0 }}>DB OCIO Dashboard</h1>
        <label style={{ fontSize: 13, color: "#374151" }}>
          펀드:&nbsp;
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            style={{ fontSize: 13, padding: "4px 8px" }}
          >
            {data.data
              .slice()
              .sort((a, b) => a.code.localeCompare(b.code))
              .map((f) => (
                <option key={f.code} value={f.code}>
                  {f.code} — {f.name}
                </option>
              ))}
          </select>
        </label>
      </header>
      <section style={{ color: "#6b7280" }}>
        TBD: OverviewTab (커밋 5에서 연결) — selected={selected}
      </section>
    </div>
  );
}
