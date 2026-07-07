import { useQuery } from "@tanstack/react-query";

import { fetchWarmupStatus, type WarmupStatusDTO } from "../api/endpoints";

const ACTIVE = new Set(["running"]);

/**
 * 앱 시작 시 백그라운드 워밍업 진행률을 폴링한다.
 * - status 가 running 인 동안만 ~1s 간격 refetch, 그 외(idle/done/error)면 폴링 중단.
 * - idle = startup 워밍업 비활성(OCIO_WARMUP_ON_STARTUP=false). 영구히 running 으로
 *   바뀌지 않으므로 폴링하지 않는다(무한 폴링 방지).
 * - 워밍업 endpoint 가 없거나 실패해도 UI 를 막지 않도록 retry 최소화.
 */
export const useWarmupStatus = () =>
  useQuery<WarmupStatusDTO>({
    queryKey: ["warmup-status"],
    queryFn: fetchWarmupStatus,
    refetchInterval: (query) => {
      // endpoint 부재/에러(정적 스냅샷 배포 등)면 폴링 중단 — 오버레이 깜빡임 방지.
      if (query.state.status === "error") return false;
      const status = query.state.data?.status;
      // 첫 응답 전(undefined) 또는 진행 중(running)이면 계속 폴링.
      if (status === undefined || ACTIVE.has(status)) return 1000;
      return false;
    },
    retry: 1,
    staleTime: 0,
  });
