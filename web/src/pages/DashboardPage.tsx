import { useState } from "react";
import { useFunds } from "../hooks/useFunds";
import OverviewTab from "../tabs/OverviewTab";
import HoldingsTab from "../tabs/HoldingsTab";
import MacroTab from "../tabs/MacroTab";
import ReportTab from "../tabs/ReportTab";
import AdminTab from "../tabs/AdminTab";

type TabKey = "overview" | "holdings" | "macro" | "report" | "admin";

export default function DashboardPage() {
  const { data, isLoading, error } = useFunds();
  const [selected, setSelected] = useState<string>("08K88");
  const [tab, setTab] = useState<TabKey>("overview");

  if (isLoading) return <div style={{ padding: 16 }}>loading funds...</div>;
  if (error || !data) {
    return (
      <div style={{ padding: 16, color: "#dc2626" }}>
        failed to load /api/funds
      </div>
    );
  }

  const tabBtn = (key: TabKey, label: string) => (
    <button
      onClick={() => setTab(key)}
      style={{
        padding: "6px 14px",
        border: "1px solid #e5e7eb",
        borderBottom:
          tab === key ? "2px solid #2563eb" : "1px solid #e5e7eb",
        background: tab === key ? "#eff6ff" : "#fff",
        fontSize: 13,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ padding: 16, fontFamily: "system-ui, sans-serif" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 12,
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

      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {tabBtn("overview", "Overview")}
        {tabBtn("holdings", "편입종목")}
        {tabBtn("macro", "Macro")}
        {tabBtn("report", "운용보고")}
        {tabBtn("admin", "Admin")}
      </div>

      {tab === "overview" ? (
        <OverviewTab fundCode={selected} />
      ) : tab === "holdings" ? (
        <HoldingsTab fundCode={selected} />
      ) : tab === "macro" ? (
        <MacroTab />
      ) : tab === "report" ? (
        <ReportTab fundCode={selected} />
      ) : (
        <AdminTab />
      )}
    </div>
  );
}
