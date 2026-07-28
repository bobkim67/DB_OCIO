import { useEffect, useMemo, useState } from "react";
import { buildStandaloneHtml, renderTextBlocks } from "../lib/reportText";
import "../styles/sentreports.css";

/**
 * 발송 운용보고 아카이브 (2026-07-09) — Outlook 발신 메일에서 취합한 고객사 운용보고.
 * 원본(DRM, 사내 PC 전용) 다운로드 + 추출 텍스트의 디자인 뷰 + standalone HTML 저장.
 * 데이터: PC 배치(sent_report_collector/text) 산출 → 서버는 read-only.
 *
 * ⚠️ 2026-07-28 카드뉴스 개편으로 라우팅에서 분리됨 (ReportTab → ReportCardHome).
 *    리스트형 뷰가 다시 필요할 때를 위해 보존. 렌더 함수는 lib/reportText 공유.
 */

type FileRow = {
  filename: string;
  rel_path: string;
  kind: string;
  mail_date: string;
  mail_subject: string;
  has_text: boolean;
  text_chars: number;
  preview_pages: number;
};
type PeriodRow = { period: string; files: FileRow[] };

const KIND_COLOR: Record<string, { bg: string; fg: string }> = {
  월간: { bg: "#e8f0fe", fg: "#1a4d8f" },
  분기: { bg: "#fef3e0", fg: "#8a5a00" },
  비정기: { bg: "#f3e8fd", fg: "#6b2fa0" },
};

export default function SentReportArchive({ fundCode }: { fundCode: string }) {
  const [data, setData] = useState<PeriodRow[] | null>(null);
  const [err, setErr] = useState("");
  const [openPath, setOpenPath] = useState("");
  const [text, setText] = useState("");
  const [previewPath, setPreviewPath] = useState(""); // 원본 캡쳐 보기 토글
  // 승인된 생성 보고서 (Admin 워크플로우 승인본만 노출)
  const [genReports, setGenReports] = useState<{ period: string; comment: string; approved_at: string }[]>([]);
  const [openGen, setOpenGen] = useState("");

  useEffect(() => {
    setData(null); setErr(""); setOpenPath(""); setText("");
    fetch(`/api/funds/${fundCode}/sent-reports`)
      .then((r) => r.json())
      .then((d) => setData(d.periods ?? []))
      .catch((e) => setErr(String(e)));
  }, [fundCode]);

  const total = useMemo(() => (data ?? []).reduce((s, p) => s + p.files.length, 0), [data]);

  useEffect(() => {
    setGenReports([]); setOpenGen("");
    fetch(`/api/funds/${fundCode}/sent-reports/generated`)
      .then((r) => r.json())
      .then((d) => setGenReports(d.reports ?? []))
      .catch(() => {});
  }, [fundCode]);

  const loadText = async (f: FileRow) => {
    if (openPath === f.rel_path) { setOpenPath(""); return; }
    const r = await fetch(`/api/funds/${fundCode}/sent-reports/text?rel_path=${encodeURIComponent(f.rel_path)}`);
    const d = await r.json();
    setText(d.text ?? "");
    setOpenPath(f.rel_path);
  };

  const saveHtml = async (f: FileRow, period: string) => {
    const r = await fetch(`/api/funds/${fundCode}/sent-reports/text?rel_path=${encodeURIComponent(f.rel_path)}`);
    const d = await r.json();
    const html = buildStandaloneHtml(
      `${fundCode} 운용보고 — ${period}`,
      `${f.filename} · 발송 ${f.mail_date} · ${f.kind}`,
      d.text ?? "",
    );
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = f.filename.replace(/\.[^.]+$/, "") + ".html";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (err) return <div className="sra-empty">아카이브 로드 실패: {err}</div>;
  if (data === null) return <div className="sra-empty">불러오는 중…</div>;
  if (!data.length)
    return <div className="sra-empty">이 펀드의 발송 보고서가 없습니다. (PC 에서 취합 배치 실행 후 서버 동기화 필요)</div>;

  return (
    <div className="sra-root">
      <div className="sra-head">
        발송 운용보고 아카이브 <span className="cnt">{data.length}개 기간 · {total}개 파일</span>
        <span className="note">원본은 사내 문서보안(DRM) 파일 — 사내 PC에서만 열립니다</span>
      </div>

      {/* 승인된 생성 보고서 — 생성/편집/승인은 Admin 탭 (코멘트 승인 → 보고서 생성 → 승인 → 노출) */}
      {genReports.length > 0 && (
        <div className="sra-genout">
          <div className="gh">생성 보고서 (승인본) <span className="ref">Admin 승인 완료분만 표시</span></div>
          {genReports.map((g) => (
            <div key={g.period} className="sra-file">
              <div className="fn">{fundCode} {g.period} 운용보고 코멘트
                <span className="dt num"> 승인 {g.approved_at.slice(0, 10)}</span>
              </div>
              <div className="acts">
                <button type="button" className="primary"
                  onClick={() => setOpenGen(openGen === g.period ? "" : g.period)}>
                  {openGen === g.period ? "닫기" : "보기"}
                </button>
                <button type="button" onClick={() => {
                  const html = buildStandaloneHtml(`${fundCode} 운용보고 코멘트 — ${g.period}`,
                    `승인 ${g.approved_at}`, g.comment);
                  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
                  const a = document.createElement("a");
                  a.href = URL.createObjectURL(blob);
                  a.download = `${fundCode}_${g.period}_코멘트.html`;
                  a.click(); URL.revokeObjectURL(a.href);
                }}>HTML 저장</button>
              </div>
              {openGen === g.period && <div className="sra-view">{renderTextBlocks(g.comment)}</div>}
            </div>
          ))}
        </div>
      )}
      {data.map((p) => (
        <div key={p.period} className="sra-period">
          <div className="sra-ph">
            <span className="pd num">{p.period}</span>
            {p.files[0] && (
              <span className="kd" style={{
                background: KIND_COLOR[p.files[0].kind]?.bg ?? "#eef2f7",
                color: KIND_COLOR[p.files[0].kind]?.fg ?? "#475467",
              }}>{p.files[0].kind}</span>
            )}
          </div>
          {p.files.map((f) => (
            <div key={f.rel_path} className="sra-file">
              <div className="fn" title={f.mail_subject}>{f.filename}
                <span className="dt num"> 발송 {f.mail_date}</span>
              </div>
              <div className="acts">
                {f.preview_pages > 0 && (
                  <button type="button" className="primary"
                    onClick={() => setPreviewPath(previewPath === f.rel_path ? "" : f.rel_path)}>
                    {previewPath === f.rel_path ? "닫기" : `원본 보기 (${f.preview_pages}p)`}
                  </button>
                )}
                {f.filename.toLowerCase().endsWith(".pdf") && (
                  <a href={`/api/funds/${fundCode}/sent-reports/file?rel_path=${encodeURIComponent(f.rel_path)}&inline=true`}
                    target="_blank" rel="noreferrer">
                    <button type="button" className="primary">원본 보기 (PDF)</button>
                  </a>
                )}
                {f.has_text && (
                  <button type="button" onClick={() => loadText(f)}>
                    {openPath === f.rel_path ? "닫기" : "텍스트"}
                  </button>
                )}
                {f.has_text && <button type="button" onClick={() => saveHtml(f, p.period)}>HTML 저장</button>}
                <a href={`/api/funds/${fundCode}/sent-reports/file?rel_path=${encodeURIComponent(f.rel_path)}`}>
                  <button type="button">원본 다운로드</button>
                </a>
              </div>
              {previewPath === f.rel_path && (
                <div className="sra-preview">
                  {Array.from({ length: f.preview_pages }, (_, i) => (
                    <img key={i} loading="lazy" alt={`${f.filename} p${i + 1}`}
                      src={`/api/funds/${fundCode}/sent-reports/preview?rel_path=${encodeURIComponent(f.rel_path)}&page=${i + 1}`} />
                  ))}
                </div>
              )}
              {openPath === f.rel_path && (
                <div className="sra-view">{renderTextBlocks(text)}</div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
