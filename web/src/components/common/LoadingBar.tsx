import type { CSSProperties } from "react";

interface Props {
  label?: string;
  /** 진행률 0~100 으로 알면 determinate, 미지정 시 indeterminate. */
  percent?: number | null;
  height?: number;
}

/**
 * 공통 loading 인디케이터 — indeterminate progress bar (CSS only).
 *
 * - 데이터 fetch 중 사용. percent 미지정 시 좌→우 흐르는 indeterminate 막대.
 * - 의존성 0 (Plotly/SVG 미사용), 가벼움.
 */
export default function LoadingBar({
  label = "loading...",
  percent = null,
  height = 6,
}: Props) {
  const isDet = percent !== null && percent !== undefined && !Number.isNaN(percent);
  const clampedPct = isDet ? Math.max(0, Math.min(100, percent!)) : null;

  return (
    <div style={wrap}>
      <div
        style={{
          position: "relative",
          width: "100%",
          height,
          background: "#e5e7eb",
          borderRadius: 999,
          overflow: "hidden",
        }}
        role="progressbar"
        aria-valuenow={clampedPct ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        {isDet ? (
          <div
            style={{
              width: `${clampedPct}%`,
              height: "100%",
              background: "#2563eb",
              transition: "width 200ms linear",
            }}
          />
        ) : (
          <>
            <style>{indeterminateKeyframes}</style>
            <div
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "30%",
                height: "100%",
                background:
                  "linear-gradient(90deg, transparent 0%, #2563eb 50%, transparent 100%)",
                animation: "loading-bar-slide 1.2s ease-in-out infinite",
              }}
            />
          </>
        )}
      </div>
      {label && (
        <div
          style={{
            marginTop: 6,
            fontSize: 12,
            color: "#6b7280",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {label}
          {isDet ? ` (${clampedPct!.toFixed(0)}%)` : ""}
        </div>
      )}
    </div>
  );
}

const wrap: CSSProperties = {
  width: "100%",
  maxWidth: 360,
  margin: "32px auto",
};

const indeterminateKeyframes = `
@keyframes loading-bar-slide {
  0%   { left: -30%; }
  100% { left: 100%; }
}
`;
