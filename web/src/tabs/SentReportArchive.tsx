import { useEffect, useMemo, useState } from "react";
import "../styles/sentreports.css";

/**
 * 발송 운용보고 아카이브 (2026-07-09) — Outlook 발신 메일에서 취합한 고객사 운용보고.
 * 원본(DRM, 사내 PC 전용) 다운로드 + 추출 텍스트의 디자인 뷰 + standalone HTML 저장.
 * 데이터: PC 배치(sent_report_collector/text) 산출 → 서버는 read-only.
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

function renderTextBlocks(text: string): JSX.Element[] {
  // 추출 텍스트 → 디자인 블록: 슬라이드/시트 헤더, 탭 구분 행=표, 나머지=문단
  const out: JSX.Element[] = [];
  let table: string[][] = [];
  const flushTable = (key: string) => {
    if (!table.length) return;
    const rows = table;
    table = [];
    out.push(
      <div key={key} style={{ overflowX: "auto", margin: "6px 0" }}>
        <table className="sra-table">
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
  };
  text.split("\n").forEach((ln, i) => {
    const line = ln.trimEnd();
    const hdr = line.match(/^---\s*(.+?)\s*---$|^===\s*(.+?)\s*===$/);
    if (hdr) {
      flushTable(`t${i}`);
      out.push(<div key={`h${i}`} className="sra-sec">{hdr[1] || hdr[2]}</div>);
      return;
    }
    if (line.includes("\t")) {
      table.push(line.split("\t"));
      return;
    }
    flushTable(`t${i}`);
    if (line.trim()) out.push(<p key={`p${i}`} className="sra-p">{line}</p>);
  });
  flushTable("tend");
  return out;
}

function buildStandaloneHtml(title: string, meta: string, text: string): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const body = text.split("\n").map((ln) => {
    const hdr = ln.match(/^---\s*(.+?)\s*---$|^===\s*(.+?)\s*===$/);
    if (hdr) return `<h2>${esc(hdr[1] || hdr[2] || "")}</h2>`;
    if (ln.includes("\t"))
      return `<table class="r"><tr>${ln.split("\t").map((c) => `<td>${esc(c)}</td>`).join("")}</tr></table>`;
    return ln.trim() ? `<p>${esc(ln)}</p>` : "";
  }).join("\n");
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>${esc(title)}</title><style>
body{font-family:'Malgun Gothic',sans-serif;max-width:860px;margin:24px auto;padding:0 20px;color:#1f2430;line-height:1.6}
h1{font-size:20px;border-bottom:2px solid #1a4d8f;padding-bottom:8px}
.meta{color:#667085;font-size:12px;margin-bottom:18px}
h2{font-size:14px;background:#eef2f7;padding:5px 10px;border-left:3px solid #1a4d8f;margin:18px 0 6px}
p{font-size:13px;margin:4px 0}
table.r{border-collapse:collapse;width:100%;font-size:12px}
table.r td{border:1px solid #dde3ec;padding:3px 8px}
</style></head><body><h1>${esc(title)}</h1><div class="meta">${esc(meta)}</div>${body}</body></html>`;
}

export default function SentReportArchive({ fundCode }: { fundCode: string }) {
  const [data, setData] = useState<PeriodRow[] | null>(null);
  const [err, setErr] = useState("");
  const [openPath, setOpenPath] = useState("");
  const [text, setText] = useState("");
  const [previewPath, setPreviewPath] = useState(""); // 원본 캡쳐 보기 토글
  // 보고서 코멘트 생성 (발송본 서식 기반, isolated draft)
  const [genKind, setGenKind] = useState("월간");
  const [genPeriod, setGenPeriod] = useState("");
  const [genBusy, setGenBusy] = useState(false);
  const [genErr, setGenErr] = useState("");
  const [genOut, setGenOut] = useState<null | { period: string; comment: string; reference: string; warnings: string[] }>(null);

  useEffect(() => {
    setData(null); setErr(""); setOpenPath(""); setText("");
    fetch(`/api/funds/${fundCode}/sent-reports`)
      .then((r) => r.json())
      .then((d) => setData(d.periods ?? []))
      .catch((e) => setErr(String(e)));
  }, [fundCode]);

  const total = useMemo(() => (data ?? []).reduce((s, p) => s + p.files.length, 0), [data]);

  // 기간 옵션 — 월간: 최근 6개월(전월 기본) / 분기: 최근 4분기
  const periodOpts = useMemo(() => {
    const now = new Date();
    if (genKind === "분기") {
      const out: string[] = [];
      let y = now.getFullYear(), q = Math.floor(now.getMonth() / 3) + 1;
      for (let i = 0; i < 4; i++) {
        q -= 1; if (q === 0) { q = 4; y -= 1; }
        out.push(`${y}-Q${q}`);
      }
      return out;
    }
    const out: string[] = [];
    let y = now.getFullYear(), m = now.getMonth() + 1;
    for (let i = 0; i < 6; i++) {
      m -= 1; if (m === 0) { m = 12; y -= 1; }
      out.push(`${y}-${String(m).padStart(2, "0")}`);
    }
    return out;
  }, [genKind]);
  useEffect(() => { setGenPeriod(periodOpts[0] ?? ""); }, [periodOpts]);

  const runGenerate = async () => {
    setGenBusy(true); setGenErr(""); setGenOut(null);
    try {
      const r = await fetch(`/api/funds/${fundCode}/sent-reports/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: genKind, period: genPeriod }),
      });
      const d = await r.json();
      if (!r.ok) { setGenErr(d?.detail ?? `HTTP ${r.status}`); return; }
      setGenOut(d);
    } catch (e) {
      setGenErr(String(e));
    } finally {
      setGenBusy(false);
    }
  };

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

      {/* 보고서 코멘트 생성 — 직전 발송본 서식을 기준 원고로 잇는 생성 (isolated draft) */}
      <div className="sra-gen">
        <span className="lab">보고서 코멘트 생성</span>
        <select value={genKind} onChange={(e) => setGenKind(e.target.value)}>
          <option value="월간">월간</option>
          <option value="분기">분기</option>
        </select>
        <select value={genPeriod} onChange={(e) => setGenPeriod(e.target.value)}>
          {periodOpts.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <button type="button" className="go" onClick={runGenerate} disabled={genBusy || !genPeriod}>
          {genBusy ? "생성 중… (1~2분)" : "생성"}
        </button>
        <span className="hint">직전 발송본 서술을 그대로 잇고 이번 기간 내용만 교체 · 승인 워크플로우와 별도(검토용)</span>
        {genErr && <span className="err">{genErr}</span>}
      </div>
      {genOut && (
        <div className="sra-genout">
          <div className="gh">
            {fundCode} {genOut.period} 생성 코멘트
            {genOut.reference && <span className="ref"> · 기준 서식: {genOut.reference}</span>}
            <button type="button" onClick={() => {
              const html = buildStandaloneHtml(`${fundCode} 운용보고 코멘트 — ${genOut.period}`,
                `기준 서식: ${genOut.reference}`, genOut.comment);
              const blob = new Blob([html], { type: "text/html;charset=utf-8" });
              const a = document.createElement("a");
              a.href = URL.createObjectURL(blob);
              a.download = `${fundCode}_${genOut.period}_코멘트.html`;
              a.click(); URL.revokeObjectURL(a.href);
            }}>HTML 저장</button>
          </div>
          <div className="sra-view">{renderTextBlocks(genOut.comment)}</div>
          {genOut.warnings.length > 0 && (
            <div className="warns">{genOut.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}</div>
          )}
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
