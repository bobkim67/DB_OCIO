import { useQuery } from "@tanstack/react-query";
import {
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
) =>
  useQuery({
    queryKey: ["weight-history", code, start, level],
    queryFn: () => fetchWeightHistory(code, start, level),
    enabled: !!code && !!start,
  });

export const useFxPosition = (code: string, start: string) =>
  useQuery({
    queryKey: ["fx-position", code, start],
    queryFn: () => fetchFxPosition(code, start),
    enabled: !!code && !!start,
  });

export const useSecurities = (code: string) =>
  useQuery({
    queryKey: ["securities", code],
    queryFn: () => fetchSecurities(code),
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
