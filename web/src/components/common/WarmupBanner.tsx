import type { CSSProperties } from "react";

import { useWarmupStatus } from "../../hooks/useWarmupStatus";

/**
 * 앱 시작 시 백그라운드 프리워밍 진행률 배너 (비차단).
 *
 * - DashboardPage 상단에 고정. 워밍업 진행 중에만 표시, 완료/유휴 시 자동 숨김.
 * - 앱 사용을 막지 않는다 (탭 전환/조회 가능).
 * - done_with_errors 면 실패 step 수(error_count)를 노출한다.
 */
export default function WarmupBanner() {
  const { data, isError } = useWarmupStatus();

  // 진행률 endpoint 자체가 없거나(구버전 백엔드) 아직 응답 전이면 숨김.
  if (isError || !data) return null;

  const { status, total, done, error_count, current } = data;

  // 표시 대상: running 만. idle(시작 전) / done(무오류 완료)은 숨김.
  // done_with_errors / error 는 사용자에게 결과를 잠깐 알린다.
  const isRunning = status === "running";
  const hasErrorOutcome = status === "done_with_errors" || status === "error";
  if (!isRunning && !hasErrorOutcome) return null;

  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const tone = hasErrorOutcome
    ? { bg: "#fef2f2", border: "#fecaca", fg: "#b91c1c", bar: "#ef4444" }
    : { bg: "#eff6ff", border: "#bfdbfe", fg: "#1d4ed8", bar: "#2563eb" };

  let label: string;
  if (status === "running") {
    label = `데이터 미리 불러오는 중… ${done}/${total} (${pct}%)`;
    if (current) label += ` · ${current}`;
  } else if (status === "done_with_errors") {
    label = `미리 불러오기 완료 — 일부 실패 ${error_count}건 (필요 시 해당 탭에서 자동 재시도)`;
  } else {
    label = "미리 불러오기 중단됨 — 각 탭 접속 시 개별 로드됩니다";
  }

  return (
    <div style={{ ...wrap, background: tone.bg, borderColor: tone.border }}>
      <div style={{ fontSize: 12, color: tone.fg, marginBottom: 6 }}>{label}</div>
      <div style={track}>
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: tone.bar,
            transition: "width 250ms linear",
          }}
        />
      </div>
    </div>
  );
}

const wrap: CSSProperties = {
  border: "1px solid",
  borderRadius: 8,
  padding: "8px 12px",
  marginBottom: 12,
};

const track: CSSProperties = {
  width: "100%",
  height: 6,
  background: "#e5e7eb",
  borderRadius: 999,
  overflow: "hidden",
};
