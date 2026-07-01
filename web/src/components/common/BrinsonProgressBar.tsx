import { useEffect, useRef, useState } from "react";
import LoadingBar from "./LoadingBar";

/**
 * Brinson 계산 로딩 — 정직한 경과 표시(가짜 % 아님).
 *
 * 백엔드가 단일 동기 요청이라 계산 중간 진행 신호가 없다. 그래서 내부 단계를 아는 척하는
 * 가짜 %를 만들지 않고:
 *   ① 실제 경과초를 센다.
 *   ② 예상시간(~ESTIMATE_S)까지는 경과 비율로 막대를 채우되 상한 95%(끝났다고 거짓말 안 함).
 *   ③ 예상을 넘기면 indeterminate 로 전환해 "예상보다 오래 걸리는 중"을 정직히 표시.
 * warm(캐시 히트)이면 요청이 곧 끝나 부모가 언마운트 → 막대도 사라진다. 콜드면 경과초가
 * 계속 올라가며, 콜드 상한(FoF 등 ~MAX_HINT_S)을 문구로 안내한다.
 */
const ESTIMATE_S = 20; // 대략적 warm~보통 콜드 예상(체감 기준, 계산과 무관)
const MAX_HINT_S = 120; // 콜드 상한 안내(FoF 등) — fetch 타임아웃과 동일

interface Props {
  label?: string;
  height?: number;
}

export default function BrinsonProgressBar({ label, height }: Props) {
  const [elapsedMs, setElapsedMs] = useState(0);
  const startRef = useRef<number>(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    const id = setInterval(() => {
      setElapsedMs(Date.now() - startRef.current);
    }, 200);
    return () => clearInterval(id);
  }, []);

  const sec = Math.floor(elapsedMs / 1000);
  const overEstimate = sec >= ESTIMATE_S;
  // 예상 이내: 경과 비율로 채우되 95% 상한. 초과: indeterminate(null).
  const pct = overEstimate ? null : Math.min(95, (sec / ESTIMATE_S) * 100);

  const base = label ?? "Brinson 계산 중";
  const text = overEstimate
    ? `${base} · 예상보다 오래 걸리는 중 — 경과 ${sec}s (콜드 캐시는 최대 ~${MAX_HINT_S}s)`
    : `${base} · 경과 ${sec}s (예상 ~${ESTIMATE_S}s)`;

  return <LoadingBar label={text} percent={pct} height={height} />;
}
