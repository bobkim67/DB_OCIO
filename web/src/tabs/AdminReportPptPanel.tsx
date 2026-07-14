import { useCallback, useEffect, useMemo, useState } from "react";
import "../styles/sentreports.css";
import { useFunds } from "../hooks/useFunds";

/**
 * Admin > 운용보고 PPT (2026-07-14 신설).
 * 기간(종료일 + 선택 시작일)·펀드 선택 → 서버 빌드(reporting.builder) → pptx 다운로드.
 * s4(시장 코멘트)/s6(운용경과 불릿) 캐시(JSON)를 폼에서 검수·수정 → 저장 후 재빌드하면
 * LLM 재호출 없이 편집본이 PPT 에 반영된다.
 */
type S4Block = { label: string; lines: string[] };
type S4 = { headline: string; comments: S4Block[] };
type S6 = { bullets: string[]; digest?: string | null };
type PptComments = { s4_file: string; s4: S4 | null; s6_file: string; s6: S6 | null };
type PptFile = { file: string; size_kb: number; mtime: string };

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 최근 월말 n개 (전월말부터 과거로) */
function monthEnds(n: number): string[] {
  const now = new Date();
  return Array.from({ length: n }, (_v, i) => iso(new Date(now.getFullYear(), now.getMonth() - i, 0)));
}

export default function AdminReportPptPanel() {
  const { data: fundsResp } = useFunds();
  const fundList = useMemo(
    () => (fundsResp?.data ?? []).slice().sort((a, b) => a.code.localeCompare(b.code)),
    [fundsResp],
  );

  const [fund, setFund] = useState("");
  useEffect(() => { if (!fund && fundList.length) setFund(fundList[0].code); }, [fundList, fund]);
  const [endDate, setEndDate] = useState(monthEnds(1)[0]);
  const [startDate, setStartDate] = useState(""); // ''=전년말(YTD)
  const [regen, setRegen] = useState(false);

  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [pptxFile, setPptxFile] = useState("");
  const [files, setFiles] = useState<PptFile[]>([]);

  const loadFiles = useCallback(() => {
    fetch("/api/admin/report-ppt/files")
      .then((r) => r.json())
      .then((d) => setFiles(d.files))
      .catch(() => setFiles([]));
  }, []);
  useEffect(() => { loadFiles(); }, [loadFiles]);

  // 코멘트 검수 폼 상태 (s4: headline + 블록별 lines / s6: bullets)
  const [cm, setCm] = useState<PptComments | null>(null);
  const [s4Head, setS4Head] = useState("");
  const [s4Blocks, setS4Blocks] = useState<{ label: string; text: string }[]>([]);
  const [s6Text, setS6Text] = useState("");

  const applyComments = useCallback((d: PptComments) => {
    setCm(d);
    setS4Head(d.s4?.headline ?? "");
    setS4Blocks((d.s4?.comments ?? []).map((b) => ({ label: b.label, text: b.lines.join("\n") })));
    setS6Text((d.s6?.bullets ?? []).join("\n"));
  }, []);

  const loadComments = useCallback((f: string, e: string, s: string) => {
    if (!f || !e) return;
    const q = new URLSearchParams({ fund: f, end: e });
    if (s) q.set("start", s);
    fetch(`/api/admin/report-ppt/comments?${q}`)
      .then((r) => r.json())
      .then((d) => applyComments(d))
      .catch(() => setCm(null));
  }, [applyComments]);
  useEffect(() => {
    setPptxFile(""); setMsg("");
    loadComments(fund, endDate, startDate);
  }, [fund, endDate, startDate, loadComments]);

  const build = async () => {
    setBusy("PPT 빌드"); setMsg(""); setPptxFile("");
    try {
      const r = await fetch("/api/admin/report-ppt/build", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fund_code: fund, end_date: endDate,
          start_date: startDate || null, regen_comments: regen,
        }),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setPptxFile(d.pptx_file);
      applyComments(d.comments);
      setRegen(false);
      setMsg(`✔ 빌드 완료 (${d.elapsed_sec}s)`);
      loadFiles();
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  const saveComments = async () => {
    if (!cm) return;
    setBusy("코멘트 저장"); setMsg("");
    try {
      const body: Record<string, unknown> = {};
      if (cm.s4) {
        body.s4_file = cm.s4_file;
        body.s4 = {
          headline: s4Head,
          comments: s4Blocks.map((b) => ({
            label: b.label,
            lines: b.text.split("\n").map((l) => l.trim()).filter(Boolean),
          })),
        };
      }
      if (cm.s6) {
        body.s6_file = cm.s6_file;
        body.s6 = {
          bullets: s6Text.split("\n").map((l) => l.trim()).filter(Boolean),
          digest: cm.s6.digest ?? null,
        };
      }
      const r = await fetch("/api/admin/report-ppt/comments", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setMsg("✔ 코멘트 저장 완료 — '재빌드' 하면 PPT 에 반영됩니다");
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  const hasComments = !!(cm && (cm.s4 || cm.s6));

  return (
    <div className="afp-root">
      <div className="sra-gen">
        <span className="lab">운용보고 PPT 생성</span>
        <select value={fund} onChange={(e) => setFund(e.target.value)}>
          {fundList.map((f) => <option key={f.code} value={f.code}>{f.code} — {f.name}</option>)}
        </select>
        <label>종료일
          <select value={monthEnds(8).includes(endDate) ? endDate : ""} onChange={(e) => e.target.value && setEndDate(e.target.value)} title="최근 월말 프리셋">
            <option value="">직접 입력…</option>
            {monthEnds(8).map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
        <label>시작일 <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} title="비우면 전년말(YTD)" /></label>
        {startDate && <button type="button" onClick={() => setStartDate("")}>YTD로</button>}
        <label title="s4/s6 코멘트 캐시를 지우고 LLM 으로 재생성">
          <input type="checkbox" checked={regen} onChange={(e) => setRegen(e.target.checked)} /> 코멘트 재생성
        </label>
        <button type="button" disabled={!!busy || !fund} onClick={build}>
          {pptxFile || hasComments ? "재빌드" : "PPT 생성"} (1~2분 소요)
        </button>
        <span className="hint">16장(표지·목차·섹션 + 데이터 10장) — s9~16 은 종료일 기준 YTD 고정</span>
        {fund && fund !== "07G07" && (
          <span className="err" title="표지 펀드명·수익자·위험등급, 목차 부제가 아직 07G07 기준 고정 텍스트입니다">
            ⚠ 표지·목차 문구는 현재 07G07 기준 — 타 펀드는 PPT 에서 수정 필요
          </span>
        )}
      </div>

      <div className="sra-genout">
        <div className="gh">
          {fund} · {startDate || "전년말(YTD)"} ~ {endDate}
          {busy && <span className="ref">⏳ {busy} 진행 중…</span>}
          {msg && <span className="ref">{msg}</span>}
          {pptxFile && (
            <a href={`/api/admin/report-ppt/download?file=${encodeURIComponent(pptxFile)}`}
              style={{ marginLeft: 12, fontWeight: 600 }} download>
              ⬇ {pptxFile} 다운로드
            </a>
          )}
        </div>

        {!hasComments ? (
          <div className="sra-empty">
            코멘트 캐시 없음 — PPT 생성 시 s4(시장)·s6(운용경과) 코멘트가 자동 생성됩니다 (LLM).
          </div>
        ) : (
          <div className="afp-wf">
            {cm?.s4 && (
              <div className="stage">
                <div className="sh">s4 — 시장 코멘트 <span className="ref">{cm.s4_file}</span></div>
                <label style={{ display: "block", marginBottom: 6 }}>
                  헤드라인
                  <input style={{ width: "100%", boxSizing: "border-box" }} value={s4Head}
                    onChange={(e) => setS4Head(e.target.value)} />
                </label>
                {s4Blocks.map((b, i) => (
                  <label key={b.label} style={{ display: "block", marginBottom: 6 }}>
                    {b.label.replace(/<br\s*\/?>/g, " ")}
                    <textarea rows={4} style={{ width: "100%", boxSizing: "border-box" }} value={b.text}
                      onChange={(e) => setS4Blocks((prev) => prev.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
                  </label>
                ))}
              </div>
            )}
            {cm?.s6 && (
              <div className="stage">
                <div className="sh">s6 — 운용 경과 불릿 <span className="ref">{cm.s6_file}</span></div>
                <textarea rows={6} style={{ width: "100%", boxSizing: "border-box" }} value={s6Text}
                  onChange={(e) => setS6Text(e.target.value)} placeholder="불릿 3개 (줄당 1개)" />
                {cm.s6.digest && (
                  <details style={{ marginTop: 6 }}>
                    <summary>근거 데이터(digest — 읽기 전용)</summary>
                    <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{cm.s6.digest}</pre>
                  </details>
                )}
              </div>
            )}
            <div className="btns" style={{ marginTop: 8 }}>
              <button type="button" disabled={!!busy} onClick={saveComments}>코멘트 저장</button>
              <span className="hint">저장 후 "재빌드" 를 눌러야 PPT 에 반영됩니다</span>
            </div>
          </div>
        )}
      </div>

      {/* 생성된 파일 목록 — 재빌드 없이 기존 산출물 다운로드 */}
      <div className="sra-genout" style={{ marginTop: 12 }}>
        <div className="gh">생성된 보고서 파일 ({files.length})</div>
        {files.length === 0 ? (
          <div className="sra-empty">생성된 pptx 없음</div>
        ) : (
          <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
            <tbody>
              {files.map((f) => (
                <tr key={f.file} style={{ borderBottom: "1px solid #f1f2f4" }}>
                  <td style={{ padding: "4px 16px 4px 4px" }}>
                    <a href={`/api/admin/report-ppt/download?file=${encodeURIComponent(f.file)}`} download>
                      ⬇ {f.file}
                    </a>
                  </td>
                  <td style={{ padding: "4px 16px", color: "#667085" }}>{Math.round(f.size_kb / 1024 * 10) / 10} MB</td>
                  <td style={{ padding: "4px 4px", color: "#667085" }}>{f.mtime}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
