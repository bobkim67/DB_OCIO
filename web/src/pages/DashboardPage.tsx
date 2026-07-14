import { useEffect, useState } from "react";
import { useFunds } from "../hooks/useFunds";
import { useIsAdmin } from "../lib/auth";
import "../styles/shell.css";
import LoadingBar from "../components/common/LoadingBar";
import WarmupGate from "../components/common/WarmupGate";
import OverviewTab from "../tabs/OverviewTab";
import HoldingsTab from "../tabs/HoldingsTab";
import TransactionsTab from "../tabs/TransactionsTab";
import BrinsonTab from "../tabs/BrinsonTab";
import ReportTab from "../tabs/ReportTab";
import AdminTab from "../tabs/AdminTab";
import MemoTab from "../tabs/MemoTab";

type TabKey =
  | "overview"
  | "holdings"
  | "transactions"
  | "brinson"
  | "report"
  | "admin"
  | "memo";

export default function DashboardPage() {
  const { data, isLoading, error } = useFunds();
  const isAdmin = useIsAdmin(); // 클라이언트는 false → Admin 탭 숨김 (TODO: 실제 인증 연동)
  const [selected, setSelected] = useState<string>("08K88");
  const [tab, setTab] = useState<TabKey>("overview");
  // keep-alive: 방문한 탭은 언마운트하지 않고 display:none 으로 숨겨 로컬 상태
  // (기간 preset, 토글 등)를 보존한다. 미방문 탭은 마운트하지 않음(불필요 조회 방지).
  const [visited, setVisited] = useState<TabKey[]>(["overview"]);

  const selectTab = (key: TabKey) => {
    setTab(key);
    setVisited((v) => (v.includes(key) ? v : [...v, key]));
  };

  // 숨김(display:none) 상태에서 창 크기가 바뀌면 Plotly 가 width 를 0/구값으로
  // 계산할 수 있어, 탭이 다시 보일 때 resize 이벤트로 재계산을 유도한다.
  useEffect(() => {
    window.dispatchEvent(new Event("resize"));
  }, [tab]);

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
      onClick={() => selectTab(key)}
      className={`shell-tab ${tab === key ? "on" : ""}`}
    >
      {label}
    </button>
  );

  const tabBody = (key: TabKey) =>
    key === "overview" ? (
      <OverviewTab fundCode={selected} />
    ) : key === "holdings" ? (
      <HoldingsTab fundCode={selected} />
    ) : key === "transactions" ? (
      <TransactionsTab fundCode={selected} />
    ) : key === "brinson" ? (
      <BrinsonTab fundCode={selected} />
    ) : key === "report" ? (
      <ReportTab fundCode={selected} />
    ) : key === "memo" ? (
      <MemoTab />
    ) : (
      <AdminTab />
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
        {tabBtn("holdings", "편입종목(PDF)")}
        {tabBtn("transactions", "거래내역")}
        {tabBtn("brinson", "성과분석")}
        {tabBtn("report", "운용보고")}
        {/* Admin·메모 탭은 관리자에게만 노출. 클라이언트(비관리자)는 나머지 탭 전부 접근. */}
        {isAdmin && tabBtn("admin", "Admin")}
        {isAdmin && tabBtn("memo", "메모")}
      </div>

      {visited.map((key) =>
        (key === "admin" || key === "memo") && !isAdmin ? null : (
          <div key={key} style={{ display: tab === key ? undefined : "none" }}>
            {tabBody(key)}
          </div>
        )
      )}
    </div>
  );
}
