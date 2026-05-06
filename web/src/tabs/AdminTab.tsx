import { useState, type CSSProperties } from "react";
import AdminEvidenceQualityPanel from "./AdminEvidenceQualityPanel";
import AdminDebateStatusPanel from "./AdminDebateStatusPanel";
import AdminReportEnrichmentPanel from "./AdminReportEnrichmentPanel";
import AdminCommentTracePanel from "./AdminCommentTracePanel";

type SubView = "evidence" | "debate" | "report-enrichment" | "comment-trace";

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

export default function AdminTab() {
  const [view, setView] = useState<SubView>("evidence");

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
          style={view === "evidence" ? TAB_BTN_ACTIVE : TAB_BTN_BASE}
          onClick={() => setView("evidence")}
        >
          Evidence Quality
        </button>
        <button
          style={view === "debate" ? TAB_BTN_ACTIVE : TAB_BTN_BASE}
          onClick={() => setView("debate")}
        >
          Debate Status
        </button>
        <button
          style={view === "report-enrichment" ? TAB_BTN_ACTIVE : TAB_BTN_BASE}
          onClick={() => setView("report-enrichment")}
        >
          Report Enrichment
        </button>
        <button
          style={view === "comment-trace" ? TAB_BTN_ACTIVE : TAB_BTN_BASE}
          onClick={() => setView("comment-trace")}
        >
          Comment Trace
        </button>
      </div>

      {view === "evidence" && <AdminEvidenceQualityPanel />}
      {view === "debate" && <AdminDebateStatusPanel />}
      {view === "report-enrichment" && <AdminReportEnrichmentPanel />}
      {view === "comment-trace" && <AdminCommentTracePanel />}
    </section>
  );
}
