import { useEffect, useMemo, useState } from "react";
import { periodLabel } from "../lib/reportText";
import SentReportReader, {
  type FileRow, type GeneratedRow, type PeriodRow,
} from "./SentReportReader";

/**
 * 운용보고 카드 홈 (2026-07-28) — 고객사에 실제 발송된 운용보고를 월별 카드로.
 * 카드 = 원본 캡쳐 썸네일 + 기간 + 종류 배지. 클릭 → SentReportReader(모달).
 * 데이터: /api/funds/{fund}/sent-reports (PC 취합 배치 산출, 서버 read-only).
 */

const KIND_COLOR: Record<string, { bg: string; fg: string }> = {
  월간: { bg: "#e8f0fe", fg: "#1a4d8f" },
  분기: { bg: "#fef3e0", fg: "#8a5a00" },
  비정기: { bg: "#f3e8fd", fg: "#6b2fa0" },
};

/** 카드 썸네일용 — 캡쳐가 있는 첫 파일 (없으면 첫 파일) */
function thumbFile(files: FileRow[]): FileRow | undefined {
  return files.find((f) => f.preview_pages > 0) ?? files[0];
}

function extLabel(filename: string): string {
  const m = filename.toLowerCase().match(/\.([a-z0-9]+)$/);
  if (!m) return "FILE";
  return m[1].replace("pptx", "PPT").replace("xlsx", "XLS")
    .replace("docx", "DOC").toUpperCase();
}

export default function ReportCardHome({
  fundCode, beneficiary, onGoFundComment,
}: {
  fundCode: string;
  beneficiary?: string | null;
  onGoFundComment: () => void;
}) {
  const [periods, setPeriods] = useState<PeriodRow[] | null>(null);
  const [err, setErr] = useState("");
  const [generated, setGenerated] = useState<GeneratedRow[]>([]);
  const [openIdx, setOpenIdx] = useState(-1);
  // 캡쳐 PNG 가 DRM 래핑돼 렌더 실패하는 경우 → 확장자 플레이스홀더로 폴백
  const [brokenThumb, setBrokenThumb] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setPeriods(null); setErr(""); setOpenIdx(-1);
    fetch(`/api/funds/${fundCode}/sent-reports`)
      .then((r) => r.json())
      .then((d) => setPeriods(d.periods ?? []))
      .catch((e) => setErr(String(e)));
  }, [fundCode]);

  useEffect(() => {
    setGenerated([]);
    fetch(`/api/funds/${fundCode}/sent-reports/generated`)
      .then((r) => r.json())
      .then((d) => setGenerated(d.reports ?? []))
      .catch(() => {});
  }, [fundCode]);

  const genByPeriod = useMemo(() => {
    const m: Record<string, GeneratedRow> = {};
    generated.forEach((g) => { m[g.period] = g; });
    return m;
  }, [generated]);

  const total = useMemo(
    () => (periods ?? []).reduce((s, p) => s + p.files.length, 0),
    [periods],
  );

  if (err) return <div className="sra-empty">아카이브 로드 실패: {err}</div>;
  if (periods === null) return <div className="sra-empty">불러오는 중…</div>;

  if (!periods.length)
    return (
      <div className="rch-none">
        <div className="t">{fundCode}{beneficiary ? ` · ${beneficiary}` : ""} — 발송된 운용보고가 없습니다.</div>
        <div className="d">
          이 펀드는 고객사 개별 보고 대상이 아니거나, 취합 배치가 아직 실행되지 않았습니다.
          승인된 펀드 코멘트는 아래에서 볼 수 있습니다.
        </div>
        <button type="button" className="go" onClick={onGoFundComment}>펀드 코멘트 보기</button>
      </div>
    );

  return (
    <>
      <div className="rch-head">
        <span className="cnt">{periods.length}개 기간 · {total}개 파일</span>
        <span className="note">원본은 사내 문서보안(DRM) 파일 — 사내 PC에서만 열립니다</span>
      </div>

      <div className="rch-grid">
        {periods.map((p, i) => {
          const f = thumbFile(p.files);
          const { big, small } = periodLabel(p.period);
          const kc = KIND_COLOR[f?.kind ?? ""] ?? { bg: "#eef2f7", fg: "#475467" };
          return (
            <button key={p.period} type="button" className="rch-card"
              onClick={() => setOpenIdx(i)} title={f?.mail_subject}>
              <div className="thumb">
                {f && f.preview_pages > 0 && !brokenThumb[p.period] ? (
                  <img loading="lazy" alt={`${p.period} 표지`}
                    onError={() => setBrokenThumb((m) => ({ ...m, [p.period]: true }))}
                    src={`/api/funds/${fundCode}/sent-reports/preview?rel_path=${encodeURIComponent(f.rel_path)}&page=1&v=${f.preview_rev}`} />
                ) : (
                  <div className="noimg">{f ? extLabel(f.filename) : "—"}</div>
                )}
                <span className="kd" style={{ background: kc.bg, color: kc.fg }}>{f?.kind}</span>
              </div>
              <div className="meta">
                <div className="pd">
                  <span className="big">{big}</span>
                  <span className="yr num">{small}</span>
                </div>
                <div className="sub">
                  <span className="num">{f?.mail_date}</span>
                  {p.files.length > 1 && <span className="fc">· {p.files.length}개 파일</span>}
                  {genByPeriod[p.period] && <span className="gen">· 생성본</span>}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {openIdx >= 0 && (
        <SentReportReader
          fundCode={fundCode}
          periods={periods}
          index={openIdx}
          generated={genByPeriod[periods[openIdx].period]}
          onNav={setOpenIdx}
          onClose={() => setOpenIdx(-1)}
        />
      )}
    </>
  );
}
