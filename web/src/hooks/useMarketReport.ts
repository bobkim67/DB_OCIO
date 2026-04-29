import { useQuery } from "@tanstack/react-query";
import {
  fetchMarketReport,
  fetchMarketReportApprovedPeriods,
} from "../api/endpoints";

export const useMarketReport = (period?: string) =>
  useQuery({
    queryKey: ["report", "market", period ?? null],
    queryFn: () => fetchMarketReport(period as string),
    enabled: Boolean(period),
    retry: false,
  });

export const useMarketReportApprovedPeriods = () =>
  useQuery({
    queryKey: ["report", "market", "approved-periods"],
    queryFn: fetchMarketReportApprovedPeriods,
    staleTime: 60_000,
  });
