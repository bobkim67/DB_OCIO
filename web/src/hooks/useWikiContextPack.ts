import { useQuery } from "@tanstack/react-query";
import {
  fetchWikiContextPack,
  fetchWikiContextPackPeriods,
  fetchWikiPage,
  type FetchWikiContextPackOptions,
  type WikiPackStage,
} from "../api/endpoints";

export const useWikiContextPackPeriods = () =>
  useQuery({
    queryKey: ["admin", "wiki-context-pack", "periods"],
    queryFn: fetchWikiContextPackPeriods,
    staleTime: 60_000,
  });

export const useWikiContextPack = (
  periodKey: string | null,
  stage: WikiPackStage,
  opts: FetchWikiContextPackOptions = {},
) =>
  useQuery({
    queryKey: [
      "admin",
      "wiki-context-pack",
      periodKey,
      stage,
      opts.fundCode ?? null,
      opts.maxPages ?? null,
      opts.bodyExcerptChars ?? null,
      opts.includeDebateMemory ?? null,
    ],
    enabled: Boolean(periodKey),
    queryFn: () => fetchWikiContextPack(periodKey as string, stage, opts),
  });

export const useWikiPage = (path: string | null) =>
  useQuery({
    queryKey: ["admin", "wiki-page", path],
    enabled: Boolean(path),
    queryFn: () => fetchWikiPage(path as string),
  });
