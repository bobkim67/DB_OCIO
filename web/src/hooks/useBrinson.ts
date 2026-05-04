import { useQuery } from "@tanstack/react-query";
import {
  fetchBrinson,
  type BrinsonMappingMethod,
  type BrinsonPaMethod,
  type FetchBrinsonOptions,
} from "../api/endpoints";

export interface UseBrinsonArgs {
  code: string;
  startDate?: string;
  endDate?: string;
  mappingMethod?: BrinsonMappingMethod;
  paMethod?: BrinsonPaMethod;
  fxSplit?: boolean;
}

export const useBrinson = (args: UseBrinsonArgs) => {
  const { code, startDate, endDate, mappingMethod, paMethod, fxSplit } = args;
  const opts: FetchBrinsonOptions = {
    startDate,
    endDate,
    mappingMethod,
    paMethod,
    fxSplit,
  };
  return useQuery({
    queryKey: [
      "brinson",
      code,
      startDate ?? null,
      endDate ?? null,
      mappingMethod ?? null,
      paMethod ?? "8",
      fxSplit ?? true,
    ],
    queryFn: () => fetchBrinson(code, opts),
    enabled: !!code,
    staleTime: 5 * 60 * 1000,
  });
};
