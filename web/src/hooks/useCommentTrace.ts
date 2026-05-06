import { useQuery } from "@tanstack/react-query";
import {
  fetchCommentTraces,
  fetchCommentTraceLatest,
  fetchCommentTraceById,
} from "../api/endpoints";

export const useCommentTraceList = (period?: string, fund?: string) =>
  useQuery({
    queryKey: ["admin", "comment-trace", "list", period ?? null, fund ?? null],
    queryFn: () => fetchCommentTraces(period, fund),
  });

export const useCommentTraceLatest = (period?: string, fund?: string) =>
  useQuery({
    queryKey: ["admin", "comment-trace", "latest", period ?? null, fund ?? null],
    queryFn: () => fetchCommentTraceLatest(period, fund),
    retry: false, // 404 시 즉시
  });

export const useCommentTraceById = (traceId?: string) =>
  useQuery({
    queryKey: ["admin", "comment-trace", "by-id", traceId ?? null],
    queryFn: () => fetchCommentTraceById(traceId as string),
    enabled: Boolean(traceId),
    retry: false,
  });
