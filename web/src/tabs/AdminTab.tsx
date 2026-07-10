import { useState, type CSSProperties } from "react";
import AdminFundsPanel from "./AdminFundsPanel";
import AdminCommentWorkflowPanel from "./AdminCommentWorkflowPanel";

// Admin 서브탭 2개: 펀드 운용(모니터링) / 코멘트 생성·관리(워크플로우).
// (Evidence Quality ~ Wiki Context Pack 5개 패널은 2026-07-10 제거)
type SubView = "funds" | "comment";

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
  const [view, setView] = useState<SubView>("funds");

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
          style={view === "funds" ? TAB_BTN_ACTIVE : TAB_BTN_BASE}
          onClick={() => setView("funds")}
        >
          펀드 운용
        </button>
        <button
          style={view === "comment" ? TAB_BTN_ACTIVE : TAB_BTN_BASE}
          onClick={() => setView("comment")}
        >
          코멘트 생성/관리
        </button>
      </div>

      {view === "funds" && <AdminFundsPanel />}
      {view === "comment" && <AdminCommentWorkflowPanel />}
    </section>
  );
}
