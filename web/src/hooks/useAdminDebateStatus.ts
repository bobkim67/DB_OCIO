import { useQuery } from "@tanstack/react-query";
import { fetchAdminDebateStatus } from "../api/endpoints";

export const useAdminDebateStatus = (period?: string, fund?: string) =>
  useQuery({
    queryKey: ["admin", "debate-status", period ?? null, fund ?? null],
    queryFn: () => fetchAdminDebateStatus(period as string, fund as string),
    enabled: Boolean(period && fund),
  });
