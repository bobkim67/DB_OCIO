import { useEffect, useState } from "react";
import { useFunds } from "../hooks/useFunds";
import MarketReportPanel from "./MarketReportPanel";
import FundReportPanel from "./FundReportPanel";
import ReportCardHome from "./ReportCardHome";
import "../styles/sentreports.css";

type SubView = "cards" | "appendix" | "market" | "fund";

/**
 * 운용보고 탭 — 기본 화면은 월별 카드 홈(고객사 발송 보고서).
 * 시장/펀드 코멘트(승인본)는 상단 전환으로 유지. (2026-07-28 카드뉴스 개편)
 */
export default function ReportTab({ fundCode }: { fundCode: string }) {
  const [view, setView] = useState<SubView>("cards");
  const funds = useFunds();
  const meta = funds.data?.data?.find((f) => f.code === fundCode);

  // 펀드 변경 시 카드 홈으로 복귀 (다른 펀드의 코멘트 화면에 남지 않도록)
  useEffect(() => { setView("cards"); }, [fundCode]);

  return (
    <section className="rch-root">
      <div className="rch-top">
        <h2 className="fund-title">
          운용보고 <span className="code">{fundCode}</span>
        </h2>
        {meta?.beneficiary && <span className="rch-client">{meta.beneficiary}</span>}
        <div className="rch-seg">
          {([["cards", "월별 보고"], ["appendix", "Appendix"],
             ["market", "시장 코멘트"], ["fund", "펀드 코멘트"]] as const)
            .map(([k, label]) => (
              <button key={k} type="button" className={view === k ? "on" : ""}
                onClick={() => setView(k)}>{label}</button>
            ))}
        </div>
      </div>

      {(view === "cards" || view === "appendix") && (
        <ReportCardHome
          key={view}                                   /* 탭 전환 시 상태 초기화 */
          fundCode={fundCode}
          beneficiary={meta?.beneficiary}
          category={view === "cards" ? "main" : "appendix"}
          onGoFundComment={() => setView("fund")}
        />
      )}
      {view === "market" && <MarketReportPanel />}
      {view === "fund" && <FundReportPanel fundCode={fundCode} />}
    </section>
  );
}
