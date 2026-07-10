import { useCallback, useEffect, useMemo, useState } from "react";
import "../styles/sentreports.css";
import { useFunds } from "../hooks/useFunds";

/**
 * Admin > 코멘트 생성/관리 (2026-07-10 분리 신설).
 * 펀드·기간 선택 후 2단계 워크플로우:
 *   ① 펀드코멘트 생성→편집→승인 → (승인 게이트) → ② 보고서 생성→편집→승인 → client 노출.
 * (기존 AdminFundsPanel 확장 행에 묻혀 있던 워크플로우를 별도 서브탭으로 분리)
 */
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

function StBadge({ s }: { s: string }) {
  const c = ST_COLOR[s] ?? ST_COLOR.not_generated;
  return <span className="afp-badge" style={{ background: c.bg, color: c.fg }}>{ST_LABEL[s] ?? s}</span>;
}

export default function AdminCommentWorkflowPanel() {
  const { data: fundsResp } = useFunds();
  const fundList = useMemo(
    () => (fundsResp?.data ?? []).slice().sort((a, b) => a.code.localeCompare(b.code)),
    [fundsResp],
  );

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

  const [fund, setFund] = useState("");
  useEffect(() => { if (!fund && fundList.length) setFund(fundList[0].code); }, [fundList, fund]);

  const [wf, setWf] = useState<{ comment: Stage; report: Stage } | null>(null);
  const [editText, setEditText] = useState("");
  const [editRpt, setEditRpt] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const loadWf = useCallback((f: string, p: string) => {
    if (!f) return;
    setWf(null); setMsg("");
    fetch(`/api/admin/funds/${f}/workflow?period=${p}`)
      .then((r) => r.json())
      .then((d) => { setWf(d); setEditText(d.comment?.text ?? ""); setEditRpt(d.report?.text ?? ""); })
      .catch((e) => setErr(String(e)));
  }, []);
  useEffect(() => { if (fund) loadWf(fund, period); }, [fund, period, loadWf]);

  const act = async (path: string, body: object, label: string) => {
    setBusy(label); setMsg("");
    try {
      const method = path.includes("/draft") ? "PUT" : "POST";
      const r = await fetch(`/api/admin/funds/${fund}/${path}`, {
        method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setMsg(`✔ ${label} 완료`);
      loadWf(fund, period);
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  return (
    <div className="afp-root">
      <div className="sra-gen">
        <span className="lab">코멘트 · 보고서 생성/관리</span>
        <select value={fund} onChange={(e) => setFund(e.target.value)}>
          {fundList.map((f) => <option key={f.code} value={f.code}>{f.code} — {f.name}</option>)}
        </select>
        <select value={period} onChange={(e) => setPeriod(e.target.value)}>
          {periodOpts.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <span className="hint">프로세스: 펀드코멘트 생성→승인 → 보고서 생성→승인 → client 노출 (운용보고/발송 보고서 뷰)</span>
        {err && <span className="err">{err}</span>}
      </div>

      <div className="sra-genout">
        <div className="gh">{fund} · {period} 워크플로우 {busy && <span className="ref">⏳ {busy} 진행 중…</span>} {msg && <span className="ref">{msg}</span>}</div>
        {!wf ? <div className="sra-empty">로드 중…</div> : (
          <div className="afp-wf">
            {/* 1단계 — 펀드코멘트 */}
            <div className="stage">
              <div className="sh">① 펀드코멘트 <StBadge s={wf.comment.status} />
                {wf.comment.approved_at && <span className="ref">승인 {wf.comment.approved_at.slice(0, 16)}</span>}
              </div>
              <div className="btns">
                <button type="button" disabled={!!busy}
                  onClick={() => act("comment/generate", { kind, period }, "코멘트 생성 (1~2분)")}>
                  {wf.comment.status === "not_generated" ? "생성" : "재생성"}
                </button>
                <button type="button" disabled={!!busy || wf.comment.status === "not_generated"}
                  onClick={() => act("comment/draft", { period, text: editText }, "코멘트 수정 저장")}>수정 저장</button>
                <button type="button" className="approve" disabled={!!busy || wf.comment.status === "not_generated"}
                  onClick={() => act("comment/approve", { period }, "코멘트 승인")}>승인</button>
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
                  onClick={() => act("report/generate", { kind, period }, "보고서 생성 (1~2분)")}>
                  {wf.report.status === "not_generated" ? "생성" : "재생성"}
                </button>
                <button type="button" disabled={!!busy || wf.report.status === "not_generated"}
                  onClick={() => act("report/draft", { period, text: editRpt }, "보고서 수정 저장")}>수정 저장</button>
                <button type="button" className="approve" disabled={!!busy || wf.report.status === "not_generated"}
                  onClick={() => act("report/approve", { period }, "보고서 승인")}>승인</button>
              </div>
              <textarea value={editRpt} onChange={(e) => setEditRpt(e.target.value)}
                placeholder="① 승인 후 생성 → 편집" rows={10} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
