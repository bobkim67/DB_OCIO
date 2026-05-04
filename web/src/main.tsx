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
      retry: 1,
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
