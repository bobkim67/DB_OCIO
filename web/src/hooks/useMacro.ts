import { useQuery } from "@tanstack/react-query";
import { fetchMacro } from "../api/endpoints";

export const useMacro = (keys: string[], start?: string) =>
  useQuery({
    queryKey: ["macro", keys.slice().sort().join(","), start ?? null],
    queryFn: () => fetchMacro(keys, start),
    enabled: keys.length > 0,
  });
