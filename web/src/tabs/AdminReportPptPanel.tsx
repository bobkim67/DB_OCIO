import { useCallback, useEffect, useMemo, useState } from "react";
import "../styles/sentreports.css";
import "../styles/transactions.css";
import { useFunds } from "../hooks/useFunds";

/**
 * Admin > 운용보고 PPT (2026-07-14 신설, 당일 워크플로우 개편).
 * 기간 위젯 = 거래내역 탭 서식(tx-ctrl/tx-chip/tx-date) 이식.
 * 흐름: 코멘트 재생성(LLM) 또는 기존 캐시 로드 → 수정 → 코멘트 저장(JSON + 아카이브)
 *       → 저장된 상태에서만 "PPT 생성" 활성화. 저장 이력은 아카이브에서 불러오기 가능.
 */
type S4Block = { label: string; lines: string[] };
type S4 = { headline: string; comments: S4Block[] };
type S6 = { bullets: string[]; digest?: string | null };
type PptComments = { s4_file: string; s4: S4 | null; s6_file: string; s6: S6 | null };
type PptFile = { file: string; size_kb: number; mtime: string };
type ArcEntry = { file: string; saved_at: string; fund_code: string; end_date: string; start_date?: string | null };

type Preset = "1M" | "3M" | "6M" | "YTD" | "custom";
const PRESETS: { key: Preset; label: string }[] = [
  { key: "1M", label: "1개월" },
  { key: "3M", label: "3개월" },
  { key: "6M", label: "6개월" },
  { key: "YTD", label: "연초이후" },
];

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const prevMonthEnd = () => { const n = new Date(); return iso(new Date(n.getFullYear(), n.getMonth(), 0)); };
const monthsBack = (endIso: string, n: number) => {
  const [y, m, d] = endIso.split("-").map(Number);
  return iso(new Date(y, m - 1 - n, d));
};
const prevYearEnd = (endIso: string) => `${Number(endIso.slice(0, 4)) - 1}-12-31`;

const EMPTY_S4_BLOCKS = ["글로벌<br>주식", "글로벌<br>채권", "대체/<br>통화"];

export default function AdminReportPptPanel() {
  const { data: fundsResp } = useFunds();
  const fundList = useMemo(
    () => (fundsResp?.data ?? []).slice().sort((a, b) => a.code.localeCompare(b.code)),
    [fundsResp],
  );

  const [fund, setFund] = useState("");
  useEffect(() => { if (!fund && fundList.length) setFund(fundList[0].code); }, [fundList, fund]);

  // ---- 기간 (거래내역 위젯 이식): 연초이후=YTD(빌더 기본), 상대 프리셋은 종료일 기준 역산 ----
  const [preset, setPreset] = useState<Preset>("YTD");
  const [endDate, setEndDate] = useState(prevMonthEnd());
  const [customStart, setCustomStart] = useState("");
  const startDate = useMemo(() => {           // ''=YTD(빌더가 전년말 앵커)
    switch (preset) {
      case "YTD": return "";
      case "1M": return monthsBack(endDate, 1);
      case "3M": return monthsBack(endDate, 3);
      case "6M": return monthsBack(endDate, 6);
      case "custom": return customStart;
    }
  }, [preset, endDate, customStart]);
  const dispStart = startDate || prevYearEnd(endDate);   // 인풋 표시용 (YTD=전년말)

  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [pptxFile, setPptxFile] = useState("");
  const [files, setFiles] = useState<PptFile[]>([]);
  const [archive, setArchive] = useState<ArcEntry[]>([]);
  const [arcSel, setArcSel] = useState("");

  // ---- 코멘트 상태: exists(캐시/저장됨) + dirty(미저장 수정) ----
  const [cm, setCm] = useState<PptComments | null>(null);
  const [hasSaved, setHasSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [s4Head, setS4Head] = useState("");
  const [s4Blocks, setS4Blocks] = useState<{ label: string; text: string }[]>([]);
  const [s6Text, setS6Text] = useState("");

  const applyComments = useCallback((d: PptComments, markDirty: boolean) => {
    setCm(d);
    setS4Head(d.s4?.headline ?? "");
    setS4Blocks(
      d.s4?.comments?.length
        ? d.s4.comments.map((b) => ({ label: b.label, text: b.lines.join("\n") }))
        : EMPTY_S4_BLOCKS.map((label) => ({ label, text: "" })),
    );
    setS6Text((d.s6?.bullets ?? []).join("\n"));
    setHasSaved(!!(d.s4 || d.s6));
    setDirty(markDirty);
  }, []);

  const loadComments = useCallback((f: string, e: string, s: string) => {
    if (!f || !e) return;
    const q = new URLSearchParams({ fund: f, end: e });
    if (s) q.set("start", s);
    fetch(`/api/admin/report-ppt/comments?${q}`)
      .then((r) => r.json())
      .then((d) => applyComments(d, false))
      .catch(() => setCm(null));
  }, [applyComments]);

  const loadFiles = useCallback(() => {
    fetch("/api/admin/report-ppt/files")
      .then((r) => r.json()).then((d) => setFiles(d.files)).catch(() => setFiles([]));
  }, []);
  const loadArchive = useCallback((f: string) => {
    if (!f) return;
    fetch(`/api/admin/report-ppt/comments/archive?fund=${encodeURIComponent(f)}`)
      .then((r) => r.json()).then((d) => { setArchive(d.entries); setArcSel(""); })
      .catch(() => setArchive([]));
  }, []);

  useEffect(() => {
    setPptxFile(""); setMsg("");
    loadComments(fund, endDate, startDate);
  }, [fund, endDate, startDate, loadComments]);
  useEffect(() => { loadFiles(); }, [loadFiles]);
  useEffect(() => { loadArchive(fund); }, [fund, loadArchive]);

  const periodBody = () => ({
    fund_code: fund, end_date: endDate, start_date: startDate || null,
  });

  // ---- 코멘트 재생성 (LLM — 캐시 삭제 후 생성. 생성분은 즉시 캐시 저장됨) ----
  const regenerate = async () => {
    if (hasSaved && !window.confirm("기존 코멘트를 지우고 LLM 으로 재생성할까요?")) return;
    setBusy("코멘트 생성 (LLM, ~1분)"); setMsg("");
    try {
      const r = await fetch("/api/admin/report-ppt/comments/generate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(periodBody()),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      applyComments(d, false);
      setMsg("✔ 코멘트 생성 완료 — 검수·수정 후 저장하세요");
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  // ---- 코멘트 저장 (활성 캐시 + 아카이브 이력) ----
  const saveComments = async () => {
    if (!cm) return;
    setBusy("코멘트 저장"); setMsg("");
    try {
      const body: Record<string, unknown> = {
        ...periodBody(),
        s4_file: cm.s4_file,
        s4: {
          headline: s4Head,
          comments: s4Blocks.map((b) => ({
            label: b.label,
            lines: b.text.split("\n").map((l) => l.trim()).filter(Boolean),
          })),
        },
        s6_file: cm.s6_file,
        s6: {
          bullets: s6Text.split("\n").map((l) => l.trim()).filter(Boolean),
          digest: cm.s6?.digest ?? null,
        },
      };
      const r = await fetch("/api/admin/report-ppt/comments", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setHasSaved(true); setDirty(false);
      setMsg("✔ 저장 완료 (이력 보관됨)");
      loadArchive(fund);
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  // ---- PPT 생성 (저장된 코멘트 사용 — LLM 미호출) ----
  const build = async () => {
    setBusy("PPT 생성"); setMsg(""); setPptxFile("");
    try {
      const r = await fetch("/api/admin/report-ppt/build", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...periodBody(), regen_comments: false }),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setPptxFile(d.pptx_file);
      setMsg(`✔ PPT 생성 완료 (${d.elapsed_sec}s)`);
      loadFiles();
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  // ---- 아카이브 불러오기 → 폼 반영 (dirty — 저장해야 활성 캐시에 반영) ----
  const loadArchived = async () => {
    if (!arcSel) return;
    if (dirty && !window.confirm("저장하지 않은 수정이 있습니다. 이력으로 덮어쓸까요?")) return;
    try {
      const r = await fetch(`/api/admin/report-ppt/comments/archive/${encodeURIComponent(arcSel)}`);
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      applyComments({ s4_file: cm?.s4_file ?? d.s4_file, s4: d.s4, s6_file: cm?.s6_file ?? d.s6_file, s6: d.s6 }, true);
      setMsg(`✔ 이력 불러옴 (${d.saved_at}) — "코멘트 저장" 해야 PPT 에 반영됩니다`);
    } catch (e) { setMsg(`✖ ${String(e)}`); }
  };

  const canBuild = !busy && !!fund && hasSaved && !dirty;

  return (
    <div className="afp-root rpt">
      {/* ===== 컨트롤: 펀드 + 기간 (거래내역 위젯 서식) ===== */}
      <div className="tx-card">
        <div className="tx-ctrl">
          <span className="lab">펀드</span>
          <select value={fund} onChange={(e) => setFund(e.target.value)}>
            {fundList.map((f) => <option key={f.code} value={f.code}>{f.code} — {f.name}</option>)}
          </select>
          <span className="div" />
          <span className="lab">기간</span>
          <span className="tx-date">
            <input
              type="date" value={dispStart} max={endDate}
              onChange={(e) => { setCustomStart(e.target.value); setPreset("custom"); }}
            />
            ~
            <input
              type="date" value={endDate} min={dispStart}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </span>
          {PRESETS.map((p) => (
            <button
              key={p.key}
              className={`tx-chip ${preset === p.key ? "on" : ""}`}
              onClick={() => setPreset(p.key)}
            >
              {p.label}
            </button>
          ))}
          {fund && fund !== "07G07" && (
            <span className="err">⚠ 표지·목차 문구는 현재 07G07 기준 — 타 펀드는 PPT 에서 수정 필요</span>
          )}
        </div>
      </div>

      {/* ===== 코멘트 검수 (생성→수정→저장→PPT) ===== */}
      <div className="sra-genout">
        <div className="gh">
          {fund} · {startDate || `연초이후(${prevYearEnd(endDate)})`} ~ {endDate} 코멘트
          {busy && <span className="ref">⏳ {busy} 진행 중…</span>}
          {msg && <span className="ref">{msg}</span>}
          {pptxFile && (
            <a href={`/api/admin/report-ppt/download?file=${encodeURIComponent(pptxFile)}`}
              style={{ marginLeft: 12, fontWeight: 600 }} download>
              ⬇ {pptxFile} 다운로드
            </a>
          )}
        </div>

        {!hasSaved && !dirty && (
          <div className="sra-empty" style={{ marginBottom: 8 }}>
            이 기간의 코멘트 이력 없음 — "코멘트 재생성"으로 LLM 생성하거나 직접 입력 후 저장하세요.
          </div>
        )}

        <div className="afp-wf">
          <div className="stage">
            <div className="sh">s4 — 시장 코멘트 {cm && <span className="ref">{cm.s4_file}</span>}</div>
            <label style={{ display: "block", marginBottom: 6 }}>
              헤드라인
              <input style={{ width: "100%", boxSizing: "border-box" }} value={s4Head}
                onChange={(e) => { setS4Head(e.target.value); setDirty(true); }} />
            </label>
            {s4Blocks.map((b, i) => (
              <label key={b.label} style={{ display: "block", marginBottom: 6 }}>
                {b.label.replace(/<br\s*\/?>/g, " ")}
                <textarea rows={4} style={{ width: "100%", boxSizing: "border-box" }} value={b.text}
                  onChange={(e) => { setDirty(true); setS4Blocks((prev) => prev.map((x, j) => (j === i ? { ...x, text: e.target.value } : x))); }} />
              </label>
            ))}
          </div>
          <div className="stage">
            <div className="sh">s6 — 운용 경과 불릿 {cm && <span className="ref">{cm.s6_file}</span>}</div>
            <textarea rows={6} style={{ width: "100%", boxSizing: "border-box" }} value={s6Text}
              onChange={(e) => { setS6Text(e.target.value); setDirty(true); }}
              placeholder="불릿 3개 (줄당 1개)" />
            {cm?.s6?.digest && (
              <details style={{ marginTop: 6 }}>
                <summary>근거 데이터(digest — 읽기 전용)</summary>
                <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{cm.s6.digest}</pre>
              </details>
            )}
          </div>

          {/* 버튼: [코멘트 재생성] [코멘트 저장] [PPT 생성] */}
          <div className="btns" style={{ marginTop: 8, alignItems: "center" }}>
            <button type="button" disabled={!!busy || !fund} onClick={regenerate}
              title="s4/s6 캐시를 지우고 LLM 으로 재생성 (~1분)">
              코멘트 재생성
            </button>
            <button type="button" disabled={!!busy || !cm} onClick={saveComments}>
              코멘트 저장{dirty ? " *" : ""}
            </button>
            <button type="button" disabled={!canBuild} onClick={build}
              title={!hasSaved ? "코멘트 저장 후 생성 가능" : dirty ? "수정 중 — 저장 후 생성 가능" : "저장된 코멘트로 PPT 생성 (1~2분)"}>
              PPT 생성 (1~2분 소요)
            </button>
            {/* 저장 이력 불러오기 */}
            <span style={{ marginLeft: 16 }} className="hint">저장 이력</span>
            <select value={arcSel} onChange={(e) => setArcSel(e.target.value)} style={{ maxWidth: 320 }}>
              <option value="">— 선택 —</option>
              {archive.map((a) => (
                <option key={a.file} value={a.file}>
                  {a.saved_at} · {a.fund_code} · {(a.start_date ?? "연초")}~{a.end_date}
                </option>
              ))}
            </select>
            <button type="button" disabled={!arcSel || !!busy} onClick={loadArchived}>불러오기</button>
          </div>
        </div>
      </div>

      {/* ===== 생성된 파일 목록 ===== */}
      <div className="sra-genout" style={{ marginTop: 12 }}>
        <div className="gh">생성된 보고서 파일 ({files.length})</div>
        {files.length === 0 ? (
          <div className="sra-empty">생성된 pptx 없음</div>
        ) : (
          <table className="files-tbl">
            <tbody>
              {files.map((f) => (
                <tr key={f.file}>
                  <td>
                    <a href={`/api/admin/report-ppt/download?file=${encodeURIComponent(f.file)}`} download>
                      ⬇ {f.file}
                    </a>
                  </td>
                  <td className="meta">{Math.round(f.size_kb / 1024 * 10) / 10} MB</td>
                  <td className="meta">{f.mtime}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
