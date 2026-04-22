import { useQuery } from "@tanstack/react-query";
import { fetchHoldings } from "../api/endpoints";

export const useHoldings = (
  code: string,
  lookthrough: boolean,
  asOfDate?: string,
) =>
  useQuery({
    queryKey: ["holdings", code, lookthrough, asOfDate ?? null],
    queryFn: () => fetchHoldings(code, lookthrough, asOfDate),
    enabled: !!code,
  });
