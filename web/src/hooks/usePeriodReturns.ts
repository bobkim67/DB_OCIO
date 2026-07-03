import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchPeriodReturns } from "../api/endpoints";

// 기간별 수익률 표 — 조회 종료일(endDate) 앵커. endDate 미지정 시 최신 영업일.
// keepPreviousData: 종료일 변경 시 이전 값 유지(표 깜빡임 방지).
export const usePeriodReturns = (code: string, endDate?: string) =>
  useQuery({
    queryKey: ["period-returns", code, endDate ?? null],
    queryFn: () => fetchPeriodReturns(code, endDate),
    enabled: !!code,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  });
