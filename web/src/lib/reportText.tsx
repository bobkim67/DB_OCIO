/**
 * 발송 보고서 추출 텍스트 → 디자인 블록 렌더 / standalone HTML 빌드.
 * SentReportArchive(구 리스트 뷰)와 SentReportReader(카드 모달)가 공유.
 *
 * 표 처리 규칙 (2026-07-28) — 엑셀 시트 덤프가 원본이라 그대로 그리면 못 읽는다:
 *  · 연속된 탭 구분 행을 **하나의 표**로 묶는다 (줄마다 표를 만들면 열이 안 맞는다)
 *  · 전 행이 비어 있는 열은 제거 (엑셀 병합셀 흔적)
 *  · 선두의 '숫자가 없는 행'들은 다단 헤더로 간주해 thead 로 묶는다
 *  · 숫자는 소수 2자리·천단위 콤마로 정리하고 우측 정렬 (원본은 18.31334026053541)
 *  · 표는 자기 컨테이너에서만 가로 스크롤 (nowrap — 세로쓰기 방지)
 */

const NUM_RE = /^-?\d+(\.\d+)?$/;
const MAX_HEAD_ROWS = 4;

export function isNumericCell(c: string): boolean {
  return NUM_RE.test(c.trim());
}

export function formatCell(c: string): string {
  const s = c.trim();
  if (!NUM_RE.test(s)) return s;
  const v = Number(s);
  if (!Number.isFinite(v)) return s;
  return Number.isInteger(v)
    ? v.toLocaleString("ko-KR")
    : v.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** 탭 구분 행 묶음 → 빈 열 제거 + 다단 헤더 분리 */
export function normalizeTable(rows: string[][]): { head: string[][]; body: string[][] } {
  const w = Math.max(...rows.map((r) => r.length));
  const padded = rows.map((r) => [...r, ...Array(Math.max(0, w - r.length)).fill("")]);
  const keep = Array.from({ length: w }, (_, i) => i).filter((i) =>
    padded.some((r) => (r[i] ?? "").trim()),
  );
  const pruned = padded.map((r) => keep.map((i) => r[i] ?? ""));
  if (!pruned.length) return { head: [], body: [] };
  let h = 0;
  while (h < Math.min(MAX_HEAD_ROWS, pruned.length - 1) && !pruned[h].some(isNumericCell)) h += 1;
  h = Math.max(h, 1);
  return { head: pruned.slice(0, h), body: pruned.slice(h) };
}

export function renderTextBlocks(text: string): JSX.Element[] {
  const out: JSX.Element[] = [];
  let table: string[][] = [];
  const flushTable = (key: string) => {
    if (!table.length) return;
    const { head, body } = normalizeTable(table);
    table = [];
    if (!head.length) return;
    out.push(
      <div key={key} className="sra-tw">
        <table className="sra-table">
          <thead>
            {head.map((r, i) => (
              <tr key={i}>{r.map((c, j) => <th key={j}>{c.trim()}</th>)}</tr>
            ))}
          </thead>
          <tbody>
            {body.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) => (
                  <td key={j} className={isNumericCell(c) ? "n" : undefined}>{formatCell(c)}</td>
                ))}
              </tr>
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
    if (line.trim()) out.push(<p key={`p${i}`} className="sra-p">{line.trim()}</p>);
  });
  flushTable("tend");
  return out;
}

const HTML_CSS = `
body{font-family:'Malgun Gothic','Segoe UI',sans-serif;max-width:1180px;margin:24px auto;padding:0 20px;color:#2A2E34;line-height:1.6}
h1{font-size:20px;border-bottom:2px solid #557EAA;padding-bottom:8px;margin-bottom:4px}
.meta{color:#98A0AD;font-size:12px;margin-bottom:20px}
h2{font-size:14px;background:#F4F6F8;color:#557EAA;padding:6px 12px;border-left:3px solid #557EAA;margin:22px 0 8px;border-radius:0 4px 4px 0}
p{font-size:13px;margin:4px 0;color:#5B6573}
.tw{overflow-x:auto;margin:8px 0 14px;border:1px solid #E3E6EB;border-radius:6px}
table{border-collapse:collapse;font-size:12px;width:auto;min-width:100%}
th,td{border-bottom:1px solid #ECEEF1;border-right:1px solid #ECEEF1;padding:5px 10px;white-space:nowrap;text-align:left}
th{background:#F4F6F8;font-weight:700;color:#5B6573;font-size:11.5px}
thead tr:last-child th{border-bottom:1.5px solid #D5DAE2}
td.n{text-align:right;font-variant-numeric:tabular-nums}
tbody tr:nth-child(even){background:#FAFBFC}
th:last-child,td:last-child{border-right:0}
`;

export function buildStandaloneHtml(title: string, meta: string, text: string): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const parts: string[] = [];
  let buf: string[][] = [];
  const flush = () => {
    if (!buf.length) return;
    const { head, body } = normalizeTable(buf);
    buf = [];
    if (!head.length) return;
    const thead = head
      .map((r) => `<tr>${r.map((c) => `<th>${esc(c.trim())}</th>`).join("")}</tr>`)
      .join("");
    const tbody = body
      .map((r) => `<tr>${r.map((c) => (isNumericCell(c)
        ? `<td class="n">${esc(formatCell(c))}</td>`
        : `<td>${esc(c.trim())}</td>`)).join("")}</tr>`)
      .join("");
    parts.push(`<div class="tw"><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`);
  };
  text.split("\n").forEach((ln) => {
    const hdr = ln.match(/^---\s*(.+?)\s*---$|^===\s*(.+?)\s*===$/);
    if (hdr) {
      flush();
      parts.push(`<h2>${esc(hdr[1] || hdr[2] || "")}</h2>`);
      return;
    }
    if (ln.includes("\t")) {
      buf.push(ln.trimEnd().split("\t"));
      return;
    }
    flush();
    if (ln.trim()) parts.push(`<p>${esc(ln.trim())}</p>`);
  });
  flush();
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>${esc(title)}</title><style>${HTML_CSS}</style></head><body><h1>${esc(title)}</h1><div class="meta">${esc(meta)}</div>${parts.join("\n")}</body></html>`;
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
