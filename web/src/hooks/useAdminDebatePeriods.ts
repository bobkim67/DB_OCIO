import { useQuery } from "@tanstack/react-query";
import { fetchAdminDebatePeriods } from "../api/endpoints";

export const useAdminDebatePeriods = () =>
  useQuery({
    queryKey: ["admin", "debate-periods"],
    queryFn: fetchAdminDebatePeriods,
    staleTime: 60_000,
  });
