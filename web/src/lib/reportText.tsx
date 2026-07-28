/**
 * 발송 보고서 추출 텍스트 → 디자인 블록 렌더 / standalone HTML 빌드.
 * SentReportArchive(구 리스트 뷰)와 SentReportReader(카드 모달)가 공유.
 */

export function renderTextBlocks(text: string): JSX.Element[] {
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

export function buildStandaloneHtml(title: string, meta: string, text: string): string {
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

/** 파일 저장 (Blob → a[download]) */
export function downloadHtml(filename: string, html: string) {
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** '2026-06' → {big:'6월', small:'2026'} / '2026-Q2' → {big:'2분기', small:'2026'} */
export function periodLabel(period: string): { big: string; small: string } {
  const m = period.match(/^(\d{4})-(\d{2})$/);
  if (m) return { big: `${Number(m[2])}월`, small: m[1] };
  const q = period.match(/^(\d{4})-Q(\d)$/);
  if (q) return { big: `${q[2]}분기`, small: q[1] };
  const h = period.match(/^(\d{4})-H(\d)$/);
  if (h) return { big: `${h[2]}반기`, small: h[1] };
  return { big: period, small: "" };
}
