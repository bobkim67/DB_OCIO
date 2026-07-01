import { useState } from "react";
import { useFunds } from "../hooks/useFunds";
import "../styles/shell.css";
import LoadingBar from "../components/common/LoadingBar";
import WarmupGate from "../components/common/WarmupGate";
import OverviewTab from "../tabs/OverviewTab";
import HoldingsTab from "../tabs/HoldingsTab";
import TransactionsTab from "../tabs/TransactionsTab";
import BrinsonTab from "../tabs/BrinsonTab";
import ReportTab from "../tabs/ReportTab";
import AdminTab from "../tabs/AdminTab";

type TabKey =
  | "overview"
  | "holdings"
  | "transactions"
  | "brinson"
  | "report"
  | "admin";

export default function DashboardPage() {
  const { data, isLoading, error } = useFunds();
  const [selected, setSelected] = useState<string>("08K88");
  const [tab, setTab] = useState<TabKey>("overview");

  if (isLoading) return <LoadingBar label="loading funds..." />;
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
      className={`shell-tab ${tab === key ? "on" : ""}`}
    >
      {label}
    </button>
  );

  return (
    <div className="app-shell">
      <header className="shell-header">
        <h1 className="shell-title">DB OCIO Dashboard</h1>
        <label className="shell-fund">
          펀드
          <select
            className="shell-select"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
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
        <img src="/ki-logo.png" alt="한국투자신탁운용" className="shell-logo" />
      </header>

      <WarmupGate />

      <div className="shell-tabs">
        {tabBtn("overview", "Overview")}
        {tabBtn("holdings", "편입종목")}
        {tabBtn("transactions", "거래내역")}
        {tabBtn("brinson", "성과분석")}
        {tabBtn("report", "운용보고")}
        {tabBtn("admin", "Admin")}
      </div>

      {tab === "overview" ? (
        <OverviewTab fundCode={selected} />
      ) : tab === "holdings" ? (
        <HoldingsTab fundCode={selected} />
      ) : tab === "transactions" ? (
        <TransactionsTab fundCode={selected} />
      ) : tab === "brinson" ? (
        <BrinsonTab fundCode={selected} />
      ) : tab === "report" ? (
        <ReportTab fundCode={selected} />
      ) : (
        <AdminTab />
      )}
    </div>
  );
}
