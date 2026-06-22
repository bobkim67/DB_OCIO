import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 탭 이동(컴포넌트 unmount→remount) 시 cache hit 으로 즉시 표시.
      // 60초 → 5분: stale 도달 자체를 늦춰 background refetch 빈도 축소.
      staleTime: 5 * 60 * 1000,
      // gcTime: cache 유지 시간. 기본 5분 → 30분 으로 늘려 탭 오래 안 봐도 보존.
      gcTime: 30 * 60 * 1000,
      // mount 시 자동 refetch off — cached 데이터 즉시 노출 (수동 invalidate / staleTime 만료 시 refetch).
      refetchOnMount: false,
      refetchOnWindowFocus: false,
      // API error 해소될 때까지 계속 재시도 (지수 백오프, 최대 5초 간격).
      // 단발 404 의도 케이스는 각 훅에서 retry:false 로 개별 override 유지.
      retry: Infinity,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 5000),
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
