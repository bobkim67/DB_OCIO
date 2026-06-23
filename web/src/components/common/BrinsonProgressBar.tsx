import { useEffect, useRef, useState } from "react";
import LoadingBar from "./LoadingBar";

/**
 * Brinson 계산 진행바 — 실제 compute 단계를 시간기반으로 보여주는 determinate 막대.
 *
 * 백엔드가 단일 동기 요청이라 실제 단계 신호는 없지만, 프로파일링으로 측정한
 * 단계별 소요시간(콜드 ~18s 기준)을 따라 막대를 진행시킨다. warm(캐시 히트)이면
 * 요청이 곧 끝나 부모가 언마운트하므로 막대도 사라진다. 콜드면 단계 라벨이 바뀌며
 * 99% 까지 진행 → "대기 중 막대가 돈다"는 체감 제공(과도한 정확성보다 안심이 목적).
 *
 * 단계/시간 근거(modules/data_loader 프로파일, 08K88 콜드):
 *   ① MA000410 PA 소스 ~9s  ② 기준가·환율 ~1.5s  ③ 일별 PA 계산 ~6s
 *   ④ BM/SAA 분해 ~2s  ⑤ Brinson 집계 ~3s
 */
const STAGES: { label: string; end: number; ms: number }[] = [
  { label: "PA 원천데이터 로드 (MA000410)", end: 45, ms: 9000 },
  { label: "기준가·순자산·환율 로드", end: 55, ms: 1500 },
  { label: "일별 수익률·비중 계산", end: 82, ms: 6000 },
  { label: "벤치마크(BM/SAA) 수익률 분해", end: 93, ms: 2000 },
  { label: "Brinson 3-Factor 집계", end: 99, ms: 3000 },
];
const TOTAL_MS = STAGES.reduce((a, s) => a + s.ms, 0);

interface Props {
  label?: string;
  height?: number;
}

export default function BrinsonProgressBar({ label, height }: Props) {
  const [pct, setPct] = useState(2);
  const [stageIdx, setStageIdx] = useState(0);
  const startRef = useRef<number>(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    const id = setInterval(() => {
      const elapsed = Date.now() - startRef.current;
      let acc = 0;
      let prevEnd = 2;
      let idx = STAGES.length - 1;
      let p = 99;
      for (let i = 0; i < STAGES.length; i++) {
        const segEnd = acc + STAGES[i].ms;
        if (elapsed < segEnd) {
          idx = i;
          const frac = (elapsed - acc) / STAGES[i].ms;
          p = prevEnd + frac * (STAGES[i].end - prevEnd);
          break;
        }
        acc = segEnd;
        prevEnd = STAGES[i].end;
      }
      // 예상(TOTAL_MS)보다 오래 걸리면 마지막 단계 99% 에 머무름
      if (elapsed >= TOTAL_MS) {
        idx = STAGES.length - 1;
        p = 99;
      }
      setStageIdx(idx);
      setPct(Math.min(99, p));
    }, 150);
    return () => clearInterval(id);
  }, []);

  const stageLabel = `${stageIdx + 1}/${STAGES.length} · ${STAGES[stageIdx].label}`;
  return (
    <LoadingBar
      label={label ? `${label} — ${stageLabel}` : stageLabel}
      percent={pct}
      height={height}
    />
  );
}
