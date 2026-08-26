import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import "../styles/sentreports.css";
import "../styles/transactions.css";   // 거래내역 날짜패널(tx-date/tx-chip) 재사용
import type { ComplianceItemDTO, PendingSettlementDTO } from "../api/endpoints";
import { unreflectedSummary } from "../lib/pendingSettlement";

/**
 * Admin > 펀드 운용 (모니터링, 2026-07-10 재설계 v3).
 * 거래내역식 날짜패널(시작~종료 + 프리셋, 디폴트 당월) + 전 펀드 1행:
 *   펀드(코드·수익자) | 조회기간 | 1M~SI(BM펀드 BM초과 병기) | 채권Dur(펀드,년) | 채권YTM(펀드,%) | 컴플 가이드(가로 미니게이지)
 */
type Row = {
  fund_code: string;
  beneficiary: string | null;
  compliance: ComplianceItemDTO[];
  returns: Record<string, number>;
  bm_returns: Record<string, number>;
  benchmark_kind: string;
  duration_bond: number | null;
  ytm_bond: number | null;
  duration_overall: number | null;
  ytm_overall: number | null;
  unreflected_settlements?: PendingSettlementDTO[];
};

// 07G02(ISP)/07G03(RSP) 모펀드 표기 — 수익자 없음
const BENEF_OVERRIDE: Record<string, string> = {
  "07G02": "공모_모펀드(ISP)",
  "07G03": "공모_모펀드(RSP)",
};

const PRESETS: { key: string; label: string }[] = [
  { key: "MTD", label: "당월" },
  { key: "1M", label: "1개월" },
  { key: "3M", label: "3개월" },
  { key: "6M", label: "6개월" },
  { key: "YTD", label: "연초이후" },
  { key: "SI", label: "설정후" },
];
const TRAIL_COLS = ["1M", "3M", "6M", "YTD", "1Y", "SI"];

const pct = (v: number | undefined) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
const yr1 = (v: number | null) => (v == null ? "—" : v.toFixed(1));
const p2 = (v: number | null) => (v == null ? "—" : v.toFixed(2));
const fmt = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const todayStr = () => fmt(new Date());
// 프리셋별 시작일 (종료=기준일)
function presetStart(key: string, end: string): string {
  const e = end ? new Date(end) : new Date();
  if (key === "MTD") return fmt(new Date(e.getFullYear(), e.getMonth(), 1));
  if (key === "YTD") return fmt(new Date(e.getFullYear(), 0, 1));
  if (key === "SI") return "";
  const n = key === "1M" ? 1 : key === "3M" ? 3 : key === "6M" ? 6 : 0;
  const s = new Date(e); s.setMonth(s.getMonth() - n); return fmt(s);
}

const NUMFONT: CSSProperties = { fontVariantNumeric: "tabular-nums" };

// 수익률 셀 — 값 + (BM 펀드면) BM 대비 초과 병기
function RetCell({ v, bm, isBM, strong }: { v?: number; bm?: number; isBM: boolean; strong?: boolean }) {
  const cls = v == null ? "" : v >= 0 ? "up" : "dn";
  const exc = isBM && v != null && bm != null ? v - bm : null;
  return (
    <td className={`num ${cls}`} style={{ ...NUMFONT, fontSize: 13.5, ...(strong ? { fontWeight: 700 } : {}) }}>
      {pct(v)}
      {exc != null && (
        <div style={{ ...NUMFONT, fontSize: 11, fontWeight: 400, color: "#98a0ab", marginTop: 1 }}>
          BM{exc >= 0 ? "+" : ""}{(exc * 100).toFixed(2)}%p
        </div>
      )}
    </td>
  );
}

// 컴플 미니게이지 — 편입종목 가이드 카드 축소판:
//   현재값(편입비중)=핀 바로 위, 가이드라인 레이블=음영 경계선 위 (카드와 동일 위치 규칙).
const ST_HEX: Record<string, string> = { breach: "#C0392B", warn: "#C8862B", ok: "#2E9E7B", none: "#557EAA" };
// 타이틀 옆 상태 표기 (2026-08-26 사용자 지시). none=SAA 참고선이라 판정이 아닌 '비교'.
const ST_TXT: Record<string, string> = { breach: "위험", warn: "주의", ok: "적정", none: "비교" };
const pc0 = (v: number) => `${(v * 100).toFixed(0)}%`;
function MiniGauge({ c }: { c: ComplianceItemDTO }) {
  const lo = c.band_low, hi = c.band_high, V = c.value;
  const isRef = c.status === "none" && hi != null;
  const kind = lo != null && hi != null ? "band" : hi != null ? (isRef ? "ref" : "max") : lo != null ? "min" : "none";
  const clamp = (x: number) => Math.min(100, Math.max(0, x));
  // band 는 가이드 레인지를 트랙 중앙에 놓는 축(카드와 동일)
  const span = kind === "band" ? hi! - lo! : 0;
  const bandLo = kind === "band" ? Math.max(0, Math.min(lo! - span * 0.6, V - span * 0.2)) : 0;
  const axisRef = kind === "band" ? hi! : kind === "min" ? lo! : hi ?? V;
  const axisMax = Math.max(V, axisRef ?? V, 0.0001) * 1.18;
  const bandHi = kind === "band" ? Math.max(hi! + span * 0.6, V + span * 0.2) : axisMax;
  const P = (x: number) => kind === "band"
    ? clamp(((x - bandLo) / Math.max(bandHi - bandLo, 1e-9)) * 100)
    : clamp((x / axisMax) * 100);
  const cp = (x: number) => Math.min(92, Math.max(8, P(x)));  // 라벨 위치 클램프
  const col = ST_HEX[c.status] ?? ST_HEX.none;
  const G = "#d8efe0", R = "#fbe1de", N = "#e4eaf2";   // N = SAA 참고선 중립 음영
  const zones: CSSProperties[] = [];
  const marks: { x: number; label: string }[] = [];
  if (kind === "max") {
    zones.push({ left: 0, width: `${P(hi!)}%`, background: G }, { left: `${P(hi!)}%`, right: 0, background: R });
    marks.push({ x: hi!, label: `≤${pc0(hi!)}` });
  } else if (kind === "ref") {
    // SAA 는 한도가 아니라 참고선 — 위반 판정을 안 해(status="none", 핀=파랑) 초록/빨강 존을
    // 칠하면 핀은 파랑인데 존은 빨강이라 위반처럼 읽힌다 → 중립 음영 1색 + SAA 눈금
    // (2026-08-26 사용자 지시)
    zones.push({ left: 0, right: 0, background: N });
    marks.push({ x: hi!, label: `SAA ${pc0(hi!)}` });
  } else if (kind === "min") {
    zones.push({ left: 0, width: `${P(lo!)}%`, background: R }, { left: `${P(lo!)}%`, right: 0, background: G });
    marks.push({ x: lo!, label: `≥${pc0(lo!)}` });
  } else if (kind === "band") {
    zones.push({ left: 0, width: `${P(lo!)}%`, background: R },
      { left: `${P(lo!)}%`, width: `${P(hi!) - P(lo!)}%`, background: G },
      { left: `${P(hi!)}%`, right: 0, background: R });
    marks.push({ x: lo!, label: pc0(lo!) }, { x: hi!, label: pc0(hi!) });
  }
  return (
    <div style={{ flex: "1 1 0", minWidth: 150, maxWidth: 460 }}>
      <div style={{ fontSize: 11.5, color: "#5b626d", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", marginBottom: 3 }}>
        {c.label}<span style={{ color: col, fontWeight: 700 }}>({ST_TXT[c.status] ?? "—"})</span>
      </div>
      {/* 현재값 — 핀 바로 위 */}
      <div style={{ position: "relative", height: 15 }}>
        <span style={{ position: "absolute", left: `${cp(V)}%`, transform: "translateX(-50%)", ...NUMFONT, fontSize: 12, fontWeight: 700, color: col, whiteSpace: "nowrap" }}>{pc0(V)}</span>
      </div>
      {/* 트랙 */}
      <div style={{ position: "relative", height: 9, background: "#eef0f3", borderRadius: 3, overflow: "hidden" }}>
        {zones.map((z, i) => <div key={i} style={{ position: "absolute", top: 0, bottom: 0, ...z }} />)}
        {kind === "ref" && <div style={{ position: "absolute", top: 0, bottom: 0, left: `${P(hi!)}%`, width: 2, background: "#9FB1C6", transform: "translateX(-1px)" }} />}
        <div style={{ position: "absolute", top: -1, bottom: -1, left: `${P(V)}%`, width: 2, background: col, transform: "translateX(-1px)" }} />
      </div>
      {/* 가이드라인 레이블 — 음영 경계선 아래(하단) */}
      <div style={{ position: "relative", height: 13, marginTop: 1 }}>
        {marks.map((m, i) => (
          <span key={i} style={{ position: "absolute", left: `${cp(m.x)}%`, transform: "translateX(-50%)", ...NUMFONT, fontSize: 10, color: "#8a8f98", whiteSpace: "nowrap" }}>{m.label}</span>
        ))}
      </div>
    </div>
  );
}

export default function AdminFundsPanel() {
  const [preset, setPreset] = useState("MTD");
  const [date, setDate] = useState<string>("");           // 종료(기준일) "" = 최신
  const [asOfActual, setAsOfActual] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    setRows(null); setErr("");
    const q = date ? `?as_of=${date}` : "";
    fetch(`/api/admin/funds-overview${q}`)
      .then((r) => r.json())
      .then((d) => {
        setRows(d.rows ?? []);
        setAsOfActual(d.as_of_date ?? "");
        if (!date && d.as_of_date) setDate(d.as_of_date);
      })
      .catch((e) => setErr(String(e)));
  }, [date]);
  useEffect(load, [load]);

  const endDate = date || asOfActual || todayStr();
  const startDate = useMemo(() => presetStart(preset, endDate), [preset, endDate]);

  return (
    <div className="afp-root" style={{ fontSize: 13.5 }}>
      {/* 조회기간 패널 — 거래내역 날짜패널 이식 */}
      <div className="tx-controls" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        <span className="lab" style={{ fontSize: 13, fontWeight: 700, color: "#4b5563" }}>조회기간</span>
        <span className="tx-date" style={{ fontSize: 13 }}>
          <input type="date" style={NUMFONT} value={startDate} max={endDate} onChange={() => { /* 시작일 표시(범위조회 별도) */ }} />
          ~
          <input type="date" style={NUMFONT} value={endDate} max={todayStr()} onChange={(e) => setDate(e.target.value)} />
        </span>
        {PRESETS.map((p) => (
          <button key={p.key} type="button" className={`tx-chip ${preset === p.key ? "on" : ""}`} onClick={() => setPreset(p.key)}>
            {p.label}
          </button>
        ))}
        {asOfActual && <span style={{ fontSize: 12, color: "#98a0ab" }}>데이터 기준일 {asOfActual}</span>}
        {err && <span className="err">{err}</span>}
      </div>

      {rows === null ? (
        <div className="sra-empty">전 펀드 스냅샷 집계 중… (콜드 시 수십 초)</div>
      ) : (
        <div className="afp-tablewrap">
          <table className="afp-table" style={{ fontSize: 13.5 }}>
            <thead>
              <tr>
                <th>펀드</th>
                <th className="num">조회기간</th>
                {TRAIL_COLS.map((c) => <th key={c} className="num">{c}</th>)}
                <th className="num">채권Dur(펀드,년)</th>
                <th className="num">채권YTM(펀드,%)</th>
                <th>컴플라이언스 가이드</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const isBM = r.benchmark_kind === "BM";
                const benef = BENEF_OVERRIDE[r.fund_code] ?? r.beneficiary ?? "—";
                // 원장 미반영(해외 체결확인서) 카드 — 수익자 텍스트 하단 (2026-08-03 사용자 지시)
                const unref = unreflectedSummary(r.unreflected_settlements);
                return (
                  <tr key={r.fund_code}>
                    <td style={{ maxWidth: 128 }}>
                      <b style={{ fontSize: 14 }}>{r.fund_code}</b>
                      <div className="fname" style={{ fontSize: 11.5, color: "#6b7280", whiteSpace: "normal", wordBreak: "keep-all", lineHeight: 1.25 }}>
                        {benef}
                      </div>
                      {unref && (
                        <div title={unref.detail}
                          style={{ marginTop: 4, display: "inline-block", cursor: "help",
                            fontSize: 10.5, fontWeight: 600, lineHeight: 1.3, letterSpacing: "-0.1px",
                            padding: "2px 7px", borderRadius: 6, whiteSpace: "normal", wordBreak: "keep-all",
                            color: "#9a3412", background: "#ffedd5", border: "1px solid #fed7aa" }}>
                          ⚠ {unref.label}
                        </div>
                      )}
                    </td>
                    <RetCell v={r.returns[preset]} bm={r.bm_returns[preset]} isBM={isBM} strong />
                    {TRAIL_COLS.map((c) => (
                      <RetCell key={c} v={r.returns[c]} bm={r.bm_returns[c]} isBM={isBM} />
                    ))}
                    <td className="num" style={{ ...NUMFONT, fontSize: 13 }}>{yr1(r.duration_bond)}<span style={{ color: "#98a0ab" }}>({yr1(r.duration_overall)})</span></td>
                    <td className="num" style={{ ...NUMFONT, fontSize: 13 }}>{p2(r.ytm_bond)}<span style={{ color: "#98a0ab" }}>({p2(r.ytm_overall)})</span></td>
                    <td style={{ minWidth: 340 }}>
                      {r.compliance.length === 0
                        ? <span className="fname">가이드 미설정</span>
                        : /* nowrap: 좁은 화면에서 게이지 줄바꿈(3+1 등) 방지 —
                             넘치면 .afp-tablewrap 가로 스크롤이 받음 (2026-07-24) */
                          <div style={{ display: "flex", flexWrap: "nowrap", gap: "8px 18px" }}>
                            {r.compliance.map((c) => <MiniGauge key={c.key} c={c} />)}
                          </div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
