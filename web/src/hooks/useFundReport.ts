import { useQuery } from "@tanstack/react-query";
import {
  fetchFundReport,
  fetchFundReportApprovedPeriods,
} from "../api/endpoints";

export const useFundReport = (fundCode?: string, period?: string) =>
  useQuery({
    queryKey: ["report", "fund", fundCode ?? null, period ?? null],
    queryFn: () => fetchFundReport(fundCode as string, period as string),
    enabled: Boolean(fundCode && period),
    retry: false,
  });

export const useFundReportApprovedPeriods = (fundCode?: string) =>
  useQuery({
    queryKey: ["report", "fund", fundCode ?? null, "approved-periods"],
    queryFn: () => fetchFundReportApprovedPeriods(fundCode as string),
    enabled: Boolean(fundCode),
    staleTime: 60_000,
  });
