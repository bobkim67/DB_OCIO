import { useState, type CSSProperties } from "react";

import { useWarmupStatus } from "../../hooks/useWarmupStatus";

/**
 * 앱 시작 시 백그라운드 프리워밍이 끝날 때까지 대시보드 조작을 막는 게이트.
 *
 * - 워밍업 대상은 holdings/거래내역/비중/FX/보유목록. 완료(`essential_complete`)까지
 *   전체화면으로 막는다.
 * - brinson(성과분석)은 워밍업에서 제외(느림) → 성과분석 탭 진입 시 on-demand 계산.
 *   reload 범위 한정으로 한 번 계산되면 캐시 유지 → 두 번째 진입부터 즉시.
 * - fail-open: warmup endpoint 가 없거나(구버전 백엔드) 에러면 막지 않는다.
 * - idle(워밍업 비활성: OCIO_WARMUP_ON_STARTUP=false) 도 막지 않는다.
 */
// 완료 알림을 띄워 두는 시간. 워밍업 실패 스텝은 해당 탭 진입 시 자동 로드되므로
// 지나고 나면 알릴 내용이 없다.
const _NOTICE_TTL_MS = 5 * 60 * 1000;

export default function WarmupGate() {
  const { data, isError } = useWarmupStatus();
  const [dismissed, setDismissed] = useState(false);

  // 첫 응답 전(data undefined)에도 잠깐 막는다 → 진입 직후 클릭 방지.
  // endpoint 자체가 에러면 막지 않는다(fail-open).
  const blocking =
    !isError &&
    (data === undefined ||
      (data.status === "running" && !data.essential_complete));

  if (blocking) {
    const total = data?.essential_total ?? 0;
    const done = data?.essential_done ?? 0;
    const pct = total > 0 ? Math.round((done / total) * 100) : null;
    const current = data?.current ?? "";

    return (
      <div style={overlay} role="dialog" aria-modal="true" aria-busy="true">
        <div style={panel}>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#111827" }}>
            데이터 준비 중…
          </div>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
            {pct === null
              ? "워밍업 상태 확인 중"
              : `${done}/${total} (${pct}%)`}
            {current ? ` · ${current}` : ""}
          </div>
          <div style={track}>
            {pct === null ? (
              <>
                <style>{indeterminateKeyframes}</style>
                <div style={indeterminateBar} />
              </>
            ) : (
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: "#2563eb",
                  transition: "width 250ms linear",
                }}
              />
            )}
          </div>
          <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 8 }}>
            모든 펀드의 편입종목·거래내역·비중 데이터를 미리 불러오는 중입니다.
            (성과분석은 탭 진입 시 계산)
          </div>
        </div>
      </div>
    );
  }

  // 완료됐지만 일부 실패가 있으면 결과만 알린다 (조작은 허용).
  // ★ 서버 status 는 **재기동 전까지 done_with_errors 로 남는다** — 조건 없이 그리면
  //   하루 종일 빨간 띠가 붙어 있는다(2026-08-25 사용자 리포트). 실패 스텝은 해당 탭
  //   진입 시 자동 로드되므로, 완료 직후 잠깐만 띄우고 닫을 수 있게 한다.
  if (data && (data.status === "done_with_errors" || data.status === "error")) {
    const finished = data.finished_at ? Date.parse(data.finished_at) : NaN;
    const fresh = Number.isNaN(finished) || Date.now() - finished < _NOTICE_TTL_MS;
    if (dismissed || !fresh) return null;
    const msg =
      data.status === "done_with_errors"
        ? `미리 불러오기 완료 — 일부 실패 ${data.error_count}건 (해당 탭 접속 시 자동 재시도)`
        : "미리 불러오기 중단됨 — 각 탭은 접속 시 개별 로드됩니다";
    return (
      <div style={errorStrip}>
        <span>{msg}</span>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          style={closeBtn}
          aria-label="알림 닫기"
          title="닫기"
        >
          ×
        </button>
      </div>
    );
  }

  return null;
}

const overlay: CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 1000,
  background: "rgba(255,255,255,0.88)",
  backdropFilter: "blur(1px)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

const panel: CSSProperties = {
  width: "min(420px, 86vw)",
  border: "1px solid #e5e7eb",
  borderRadius: 12,
  background: "#fff",
  boxShadow: "0 10px 30px rgba(0,0,0,0.12)",
  padding: 20,
};

const track: CSSProperties = {
  position: "relative",
  width: "100%",
  height: 8,
  marginTop: 12,
  background: "#e5e7eb",
  borderRadius: 999,
  overflow: "hidden",
};

const indeterminateBar: CSSProperties = {
  position: "absolute",
  top: 0,
  left: 0,
  width: "30%",
  height: "100%",
  background:
    "linear-gradient(90deg, transparent 0%, #2563eb 50%, transparent 100%)",
  animation: "warmup-gate-slide 1.2s ease-in-out infinite",
};

const errorStrip: CSSProperties = {
  background: "#fef2f2",
  border: "1px solid #fecaca",
  color: "#b91c1c",
  fontSize: 12,
  borderRadius: 8,
  padding: "8px 12px",
  marginBottom: 12,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
};

const closeBtn: CSSProperties = {
  background: "none",
  border: "none",
  color: "inherit",
  cursor: "pointer",
  fontSize: 16,
  lineHeight: 1,
  padding: "0 2px",
};

const indeterminateKeyframes = `
@keyframes warmup-gate-slide {
  0%   { left: -30%; }
  100% { left: 100%; }
}
`;
