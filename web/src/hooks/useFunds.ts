import { useQuery } from "@tanstack/react-query";
import { fetchFunds } from "../api/endpoints";

export const useFunds = () =>
  useQuery({
    queryKey: ["funds"],
    queryFn: fetchFunds,
  });
