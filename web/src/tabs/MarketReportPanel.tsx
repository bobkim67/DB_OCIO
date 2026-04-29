import { useEffect, useMemo, useState } from "react";
import { useMarketReport, useMarketReportApprovedPeriods } from "../hooks/useMarketReport";
import ReportFinalView from "./ReportFinalView";

export default function MarketReportPanel() {
  const periodsQuery = useMarketReportApprovedPeriods();
  const periods = useMemo(
    () => periodsQuery.data?.periods ?? [],
    [periodsQuery.data],
  );

  const [period, setPeriod] = useState<string>("");
  useEffect(() => {
    if (period === "" && periods.length > 0) setPeriod(periods[0]);
  }, [period, periods]);

  const reportQuery = useMarketReport(period || undefined);

  return (
    <section>
      <div style={{ display: "flex", gap: 12, marginBottom: 16,
                    fontSize: 13, alignItems: "center" }}>
        <label>
          기간:&nbsp;
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            style={{ fontSize: 13, padding: "3px 6px", minWidth: 110 }}
            disabled={periods.length === 0}
          >
            {periods.length === 0 && <option value="">(승인본 없음)</option>}
            {periods.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        {periodsQuery.isLoading && (
          <span style={{ fontSize: 12, color: "#6b7280" }}>periods loading…</span>
        )}
      </div>

      {periods.length === 0 && !periodsQuery.isLoading ? (
        <div style={{ color: "#6b7280", fontSize: 13, padding: 16 }}>
          승인된 시장 코멘트가 없습니다.
        </div>
      ) : reportQuery.isLoading ? (
        <div>loading market report…</div>
      ) : reportQuery.error ? (
        <div style={{ color: "#b91c1c", padding: 12, background: "#fef2f2",
                      borderRadius: 6, fontSize: 13 }}>
          {(reportQuery.error as Error).message}
        </div>
      ) : reportQuery.data ? (
        <ReportFinalView data={reportQuery.data} />
      ) : null}
    </section>
  );
}
