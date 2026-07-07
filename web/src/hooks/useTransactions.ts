import { useQuery } from "@tanstack/react-query";
import {
  fetchAssetClassReturn,
  fetchFxPosition,
  fetchSecurities,
  fetchSecurityReturn,
  fetchTransactions,
  fetchWeightHistory,
  type WeightHistoryLevel,
} from "../api/endpoints";

export const useTransactions = (code: string, start: string, end: string) =>
  useQuery({
    queryKey: ["transactions", code, start, end],
    queryFn: () => fetchTransactions(code, start, end),
    enabled: !!code && !!start && !!end,
  });

export const useWeightHistory = (
  code: string,
  start: string,
  level: WeightHistoryLevel,
  end?: string,
) =>
  useQuery({
    queryKey: ["weight-history", code, start, level, end ?? ""],
    queryFn: () => fetchWeightHistory(code, start, level, end),
    enabled: !!code && !!start,
  });

export const useFxPosition = (code: string, start: string, end?: string) =>
  useQuery({
    queryKey: ["fx-position", code, start, end ?? ""],
    queryFn: () => fetchFxPosition(code, start, end),
    enabled: !!code && !!start,
  });

export const useSecurities = (code: string, start?: string) =>
  useQuery({
    queryKey: ["securities", code, start ?? ""],
    queryFn: () => fetchSecurities(code, start),
    enabled: !!code,
  });

export const useSecurityReturn = (
  code: string,
  itemCd: string,
  itemNm: string,
  start: string,
  end: string,
) =>
  useQuery({
    queryKey: ["security-return", code, itemCd, start, end],
    queryFn: () => fetchSecurityReturn(code, itemCd, itemNm, start, end),
    enabled: !!code && !!itemCd && !!start && !!end,
  });

export const useAssetClassReturn = (
  code: string,
  assetClass: string,
  start: string,
  end: string,
) =>
  useQuery({
    queryKey: ["asset-class-return", code, assetClass, start, end],
    queryFn: () => fetchAssetClassReturn(code, assetClass, start, end),
    enabled: !!code && !!assetClass && !!start && !!end,
  });
