import { useState, type CSSProperties } from "react";
import MarketReportPanel from "./MarketReportPanel";
import FundReportPanel from "./FundReportPanel";

type SubView = "market" | "fund";

const TAB_BTN_BASE: CSSProperties = {
  padding: "6px 14px",
  fontSize: 13,
  border: "1px solid #d1d5db",
  background: "#fff",
  cursor: "pointer",
  borderRadius: 4,
};

const TAB_BTN_ACTIVE: CSSProperties = {
  ...TAB_BTN_BASE,
  background: "#1f2937",
  color: "#fff",
  borderColor: "#1f2937",
};

/**
 * 운용보고 탭 — approved final.json 노출 (client-facing).
 *
 * 시장 코멘트는 펀드 독립 매크로 산출물, 펀드 코멘트는 fund-scoped 산출물.
 * URL 분리에 맞춰 sub-view 토글로 제공.
 */
export default function ReportTab({ fundCode }: { fundCode: string }) {
  const [view, setView] = useState<SubView>("market");

  return (
    <section>
      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 16,
          borderBottom: "1px solid #e5e7eb",
          paddingBottom: 12,
        }}
      >
        <button
          style={view === "market" ? TAB_BTN_ACTIVE : TAB_BTN_BASE}
          onClick={() => setView("market")}
        >
          시장 코멘트
        </button>
        <button
          style={view === "fund" ? TAB_BTN_ACTIVE : TAB_BTN_BASE}
          onClick={() => setView("fund")}
        >
          펀드 코멘트
        </button>
      </div>

      {view === "market" && <MarketReportPanel />}
      {view === "fund" && <FundReportPanel fundCode={fundCode} />}
    </section>
  );
}
