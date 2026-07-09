import { useCallback, useEffect, useMemo, useState } from "react";
import "../styles/sentreports.css";

/**
 * Admin 펀드 운용 콘솔 (2026-07-09) — 상단 펀드 선택과 무관하게 전 펀드 표시.
 * 컴플/가이드 위반 + 기간수익률 + 2단계 승인 워크플로우:
 *   펀드코멘트 생성→편집→승인 → (승인 후) 보고서 생성→편집→승인 → client 노출.
 */

type Row = {
  fund_code: string;
  fund_name: string;
  compliance_status: string;
  compliance_breaches: string[];
  returns: Record<string, number>;
  comment_status: string;
  report_status: string;
};
type Stage = { status: string; text: string; approved_at: string; generated_at: string };

const ST_LABEL: Record<string, string> = {
  not_generated: "미생성", draft_generated: "초안", edited: "수정됨", approved: "승인",
};
const ST_COLOR: Record<string, { bg: string; fg: string }> = {
  not_generated: { bg: "#eef0f3", fg: "#667085" },
  draft_generated: { bg: "#e8f0fe", fg: "#1a4d8f" },
  edited: { bg: "#fef3e0", fg: "#8a5a00" },
  approved: { bg: "#e6f4ea", fg: "#1e7b45" },
};
const COMP_COLOR: Record<string, { bg: string; fg: string; label: string }> = {
  breach: { bg: "#fee2e2", fg: "#9a3412", label: "위반" },
  warn: { bg: "#fef3c7", fg: "#92400e", label: "주의" },
  ok: { bg: "#e6f4ea", fg: "#1e7b45", label: "양호" },
  none: { bg: "#eef0f3", fg: "#667085", label: "—" },
  error: { bg: "#eef0f3", fg: "#667085", label: "?" },
};
const RET_COLS = ["1M", "3M", "6M", "YTD", "1Y", "SI"];

function pct(v: number | undefined): string {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
}

function StBadge({ s }: { s: string }) {
  const c = ST_COLOR[s] ?? ST_COLOR.not_generated;
  return <span className="afp-badge" style={{ background: c.bg, color: c.fg }}>{ST_LABEL[s] ?? s}</span>;
}

export default function AdminFundsPanel() {
  const now = new Date();
  const periodOpts = useMemo(() => {
    const out: string[] = [];
    let y = now.getFullYear(), m = now.getMonth() + 1;
    for (let i = 0; i < 6; i++) { m -= 1; if (m === 0) { m = 12; y -= 1; } out.push(`${y}-${String(m).padStart(2, "0")}`); }
    let qy = now.getFullYear(), q = Math.floor(now.getMonth() / 3) + 1;
    for (let i = 0; i < 3; i++) { q -= 1; if (q === 0) { q = 4; qy -= 1; } out.push(`${qy}-Q${q}`); }
    return out;
  }, []);
  const [period, setPeriod] = useState(periodOpts[0]);
  const kind = period.includes("Q") ? "분기" : "월간";

  const [rows, setRows] = useState<Row[] | null>(null);
  const [err, setErr] = useState("");
  const [sel, setSel] = useState("");           // 펼친 펀드
  const [wf, setWf] = useState<{ comment: Stage; report: Stage } | null>(null);
  const [editText, setEditText] = useState("");
  const [editRpt, setEditRpt] = useState("");
  const [busy, setBusy] = useState("");          // 진행 중 작업 라벨
  const [msg, setMsg] = useState("");

  const loadRows = useCallback(() => {
    setRows(null); setErr("");
    fetch(`/api/admin/funds-overview?period=${period}`)
      .then((r) => r.json())
      .then((d) => setRows(d.rows ?? []))
      .catch((e) => setErr(String(e)));
  }, [period]);
  useEffect(loadRows, [loadRows]);

  const loadWf = useCallback((fund: string) => {
    setWf(null);
    fetch(`/api/admin/funds/${fund}/workflow?period=${period}`)
      .then((r) => r.json())
      .then((d) => { setWf(d); setEditText(d.comment?.text ?? ""); setEditRpt(d.report?.text ?? ""); })
      .catch((e) => setErr(String(e)));
  }, [period]);

  const act = async (fund: string, path: string, body: object, label: string) => {
    setBusy(label); setMsg("");
    try {
      const method = path.includes("/draft") ? "PUT" : "POST";
      const r = await fetch(`/api/admin/funds/${fund}/${path}`, {
        method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setMsg(`✔ ${label} 완료`);
      loadWf(fund); loadRows();
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  return (
    <div className="afp-root">
      <div className="sra-gen">
        <span className="lab">전 펀드 운용 현황 · 워크플로우</span>
        <select value={period} onChange={(e) => { setPeriod(e.target.value); setSel(""); setWf(null); }}>
          {periodOpts.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <span className="hint">프로세스: 펀드코멘트 생성→승인 → 보고서 생성→승인 → client 노출 (운용보고/발송 보고서 뷰)</span>
        {err && <span className="err">{err}</span>}
      </div>

      {rows === null ? (
        <div className="sra-empty">전 펀드 컴플·수익률 집계 중… (콜드 시 수십 초)</div>
      ) : (
        <div className="afp-tablewrap">
          <table className="afp-table">
            <thead>
              <tr>
                <th>펀드</th><th>컴플/가이드</th>
                {RET_COLS.map((c) => <th key={c} className="num">{c}</th>)}
                <th>코멘트</th><th>보고서</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const cc = COMP_COLOR[r.compliance_status] ?? COMP_COLOR.none;
                return (
                  <tr key={r.fund_code} className={sel === r.fund_code ? "on" : ""}>
                    <td><b>{r.fund_code}</b><div className="fname">{r.fund_name}</div></td>
                    <td>
                      <span className="afp-badge" style={{ background: cc.bg, color: cc.fg }}
                        title={r.compliance_breaches.join(", ")}>{cc.label}</span>
                      {r.compliance_breaches.length > 0 && (
                        <div className="fname">{r.compliance_breaches.join(", ")}</div>
                      )}
                    </td>
                    {RET_COLS.map((c) => (
                      <td key={c} className={`num ${r.returns[c] != null ? (r.returns[c] >= 0 ? "up" : "dn") : ""}`}>
                        {pct(r.returns[c])}
                      </td>
                    ))}
                    <td><StBadge s={r.comment_status} /></td>
                    <td><StBadge s={r.report_status} /></td>
                    <td>
                      <button type="button" className="afp-open"
                        onClick={() => { const f = sel === r.fund_code ? "" : r.fund_code; setSel(f); if (f) loadWf(f); }}>
                        {sel === r.fund_code ? "닫기" : "작업"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {sel && (
        <div className="sra-genout">
          <div className="gh">{sel} · {period} 워크플로우 {busy && <span className="ref">⏳ {busy} 진행 중…</span>} {msg && <span className="ref">{msg}</span>}</div>
          {!wf ? <div className="sra-empty">로드 중…</div> : (
            <div className="afp-wf">
              {/* 1단계 — 펀드코멘트 */}
              <div className="stage">
                <div className="sh">① 펀드코멘트 <StBadge s={wf.comment.status} />
                  {wf.comment.approved_at && <span className="ref">승인 {wf.comment.approved_at.slice(0, 16)}</span>}
                </div>
                <div className="btns">
                  <button type="button" disabled={!!busy}
                    onClick={() => act(sel, "comment/generate", { kind, period }, "코멘트 생성 (1~2분)")}>
                    {wf.comment.status === "not_generated" ? "생성" : "재생성"}
                  </button>
                  <button type="button" disabled={!!busy || wf.comment.status === "not_generated"}
                    onClick={() => act(sel, "comment/draft", { period, text: editText }, "코멘트 수정 저장")}>수정 저장</button>
                  <button type="button" className="approve" disabled={!!busy || wf.comment.status === "not_generated"}
                    onClick={() => act(sel, "comment/approve", { period }, "코멘트 승인")}>승인</button>
                </div>
                <textarea value={editText} onChange={(e) => setEditText(e.target.value)}
                  placeholder="코멘트 생성 후 편집" rows={10} />
              </div>
              {/* 2단계 — 보고서 (코멘트 승인 게이트) */}
              <div className="stage">
                <div className="sh">② 보고서 (발송용) <StBadge s={wf.report.status} />
                  {wf.report.approved_at && <span className="ref">승인 {wf.report.approved_at.slice(0, 16)}</span>}
                </div>
                <div className="btns">
                  <button type="button" disabled={!!busy || wf.comment.status !== "approved"}
                    title={wf.comment.status !== "approved" ? "펀드코멘트 승인 후 생성 가능" : ""}
                    onClick={() => act(sel, "report/generate", { kind, period }, "보고서 생성 (1~2분)")}>
                    {wf.report.status === "not_generated" ? "생성" : "재생성"}
                  </button>
                  <button type="button" disabled={!!busy || wf.report.status === "not_generated"}
                    onClick={() => act(sel, "report/draft", { period, text: editRpt }, "보고서 수정 저장")}>수정 저장</button>
                  <button type="button" className="approve" disabled={!!busy || wf.report.status === "not_generated"}
                    onClick={() => act(sel, "report/approve", { period }, "보고서 승인")}>승인</button>
                </div>
                <textarea value={editRpt} onChange={(e) => setEditRpt(e.target.value)}
                  placeholder="① 승인 후 생성 → 편집" rows={10} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
