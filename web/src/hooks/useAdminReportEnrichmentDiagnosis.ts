import { useQuery } from "@tanstack/react-query";
import { fetchAdminReportEnrichmentDiagnosis } from "../api/endpoints";

/**
 * Admin/debug 전용 enrichment 진단 endpoint.
 *
 * client report (`useMarketReport` / `useFundReport`) 와 다름:
 *   - approved=false 인 final 도 final_unapproved 로 노출
 *   - InternalReportEnrichmentDTO (internal_source + raw reason 포함)
 *   - debate_run_id / approved_debate_run_id 노출
 */
export const useAdminReportEnrichmentDiagnosis = (
  period?: string,
  fund?: string,
  limit?: number,
) =>
  useQuery({
    queryKey: [
      "admin", "report-enrichment",
      period ?? null, fund ?? null, limit ?? null,
    ],
    queryFn: () => fetchAdminReportEnrichmentDiagnosis(
      period as string, fund as string, limit,
    ),
    enabled: Boolean(period && fund),
  });
