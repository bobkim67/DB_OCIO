import { useQuery } from "@tanstack/react-query";
import { fetchEvidenceQuality } from "../api/endpoints";

export const useAdminEvidenceQuality = (limit: number, fundCode?: string) =>
  useQuery({
    queryKey: ["admin", "evidence-quality", limit, fundCode ?? null],
    queryFn: () => fetchEvidenceQuality(limit, fundCode),
  });
