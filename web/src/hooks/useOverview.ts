import { useQuery } from "@tanstack/react-query";
import { fetchOverview } from "../api/endpoints";

export const useOverview = (code: string, startDate?: string) =>
  useQuery({
    queryKey: ["overview", code, startDate ?? null],
    queryFn: () => fetchOverview(code, startDate),
    enabled: !!code,
  });
