import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "../styles/sentreports.css";
import "../styles/transactions.css";   // 대상 토글(.tx-seg) 재사용
import { useFunds } from "../hooks/useFunds";

/**
 * Admin > 코멘트 생성/관리 (2026-07-10 분리 신설).
 * 펀드·기간 선택 후 2단계 워크플로우:
 *   ① 펀드코멘트 생성→편집→승인 → (승인 게이트) → ② 보고서 생성→편집→승인 → client 노출.
 * (기존 AdminFundsPanel 확장 행에 묻혀 있던 워크플로우를 별도 서브탭으로 분리)
 */
type Stage = {
  status: string; text: string; approved_at: string; generated_at: string;
  excel_ready?: boolean;   // 4JM12 월간: DB생명 데이터 엑셀 생성 여부
};

const ST_LABEL: Record<string, string> = {
  not_generated: "미생성", draft_generated: "초안", edited: "수정됨", approved: "승인",
};
const ST_COLOR: Record<string, { bg: string; fg: string }> = {
  not_generated: { bg: "#eef0f3", fg: "#667085" },
  draft_generated: { bg: "#e8f0fe", fg: "#1a4d8f" },
  edited: { bg: "#fef3e0", fg: "#8a5a00" },
  approved: { bg: "#e6f4ea", fg: "#1e7b45" },
};

/** 내용 높이에 맞춰 자동으로 늘어나는 textarea — 세로 스크롤 제거 (2026-08-03 사용자 지시).
 *  코멘트가 1,300~1,700자라 rows 고정(10줄)으로는 계속 스크롤해야 했다.
 *  value 가 바뀔 때마다 scrollHeight 로 높이를 다시 잡는다. */
function AutoTextarea({ value, onChange, placeholder }: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";                     // 줄어들 때도 다시 계산되도록 초기화
    el.style.height = `${el.scrollHeight + 2}px`; // +2 = border 보정 (마지막 줄 잘림 방지)
  }, [value]);
  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      style={{ overflowY: "hidden", minHeight: 180 }}
    />
  );
}

function StBadge({ s }: { s: string }) {
  const c = ST_COLOR[s] ?? ST_COLOR.not_generated;
  return <span className="afp-badge" style={{ background: c.bg, color: c.fg }}>{ST_LABEL[s] ?? s}</span>;
}

/** 기간 유형. TD 계열은 "직전 기간말 ~ 최신 적재일" 누계 (2026-07-31 사용자 지시). */
const KINDS = ["월간", "분기", "QTD", "HTD", "YTD"] as const;
type Kind = (typeof KINDS)[number];

const KIND_HINT: Record<Kind, string> = {
  월간: "해당 월 (진행 중이면 MTD — 최신 적재일까지)",
  분기: "마감된 분기",
  QTD: "직전 분기말 ~ 최신 적재일",
  HTD: "직전 반기말 ~ 최신 적재일",
  YTD: "전년말 ~ 최신 적재일",
};

type PeriodOpt = { value: string; label: string };

/** 유형별 기간 목록. period 값은 백엔드 저장 키 규약과 1:1
 *  (월간=YYYY-MM · 분기=YYYY-QN · QTD=YYYY-QN.QTD · HTD=YYYY-HN.HTD · YTD=YYYY-YTD). */
function buildPeriodOpts(kind: Kind): PeriodOpt[] {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth() + 1;
  const q = Math.floor((m - 1) / 3) + 1;
  const h = m <= 6 ? 1 : 2;

  if (kind === "QTD") return [{ value: `${y}-Q${q}.QTD`, label: `${y}-Q${q} 분기누계 (${(q - 1) * 3 + 1}/1~최신)` }];
  if (kind === "HTD") return [{ value: `${y}-H${h}.HTD`, label: `${y}-H${h} 반기누계 (${h === 1 ? 1 : 7}/1~최신)` }];
  if (kind === "YTD") return [{ value: `${y}-YTD`, label: `${y} 연초누계 (1/1~최신)` }];

  const out: PeriodOpt[] = [];
  if (kind === "분기") {
    // 당분기는 QTD 가 담당 → 마감된 직전 4개 분기만
    let qy = y, qq = q;
    for (let i = 0; i < 4; i++) {
      qq -= 1; if (qq === 0) { qq = 4; qy -= 1; }
      out.push({ value: `${qy}-Q${qq}`, label: `${qy}-Q${qq}` });
    }
    return out;
  }
  // 월간 — 당월(MTD) 포함 7개
  let my = y, mm = m;
  for (let i = 0; i < 7; i++) {
    const key = `${my}-${String(mm).padStart(2, "0")}`;
    out.push({ value: key, label: i === 0 ? `${key} (진행 중 · MTD)` : key });
    mm -= 1; if (mm === 0) { mm = 12; my -= 1; }
  }
  return out;
}

export default function AdminCommentWorkflowPanel({ fundCode }: { fundCode?: string }) {
  const { data: fundsResp } = useFunds();
  const fundList = useMemo(
    () => (fundsResp?.data ?? []).slice().sort((a, b) => a.code.localeCompare(b.code)),
    [fundsResp],
  );

  const [kind, setKind] = useState<Kind>("월간");
  const periodOpts = useMemo(() => buildPeriodOpts(kind), [kind]);
  const [period, setPeriod] = useState(() => buildPeriodOpts("월간")[0].value);
  // 유형이 바뀌면 해당 유형의 첫 기간으로 이동 (이전 유형 키가 남지 않게)
  useEffect(() => {
    if (!periodOpts.some((o) => o.value === period)) setPeriod(periodOpts[0].value);
  }, [periodOpts, period]);

  // 펀드 기본값 = 상단 대시보드에서 고른 펀드 (2026-08-03 사용자 지시).
  // 상단을 바꾸면 이 패널도 따라간다. 목록에 없으면(권한/필터) 첫 펀드로 폴백.
  const [fund, setFund] = useState("");
  useEffect(() => {
    if (!fundList.length) return;
    const has = (c: string) => fundList.some((f) => f.code === c);
    if (fundCode && has(fundCode)) setFund(fundCode);
    else if (!fund) setFund(fundList[0].code);
  }, [fundList, fundCode, fund]);

  // 대상 = 시장(_market) | 펀드 (2026-08-03 사용자 지시).
  // 시장은 debate 를 직접 돌리며 ②발송용 보고서 단계가 없다(client 는 /market-report 조회).
  // TD(QTD/HTD/YTD)는 시장 debate 를 돌리지 않고 월간/분기 승인본을 재사용하므로 유형에서 제외.
  const [scope, setScope] = useState<"market" | "fund">("fund");
  const isMarket = scope === "market";
  const target = isMarket ? "_market" : fund;
  const kindOpts = useMemo<readonly Kind[]>(
    () => (isMarket ? (["월간", "분기"] as const) : KINDS), [isMarket]);
  useEffect(() => {
    if (!kindOpts.includes(kind)) setKind(kindOpts[0]);
  }, [kindOpts, kind]);

  // 기간 기본값 (월간) — **전월 코멘트가 아직 승인 전이면 전월**(마감 작업 중),
  // 이미 승인됐으면 **당월 MTD**. 대상(펀드/시장)·펀드가 바뀔 때마다 다시 판정한다.
  // (2026-08-03 사용자 지시). 조회 실패 시 기존 선택 유지 — 화면이 튀지 않게.
  useEffect(() => {
    if (kind !== "월간" || !target) return;
    const opts = buildPeriodOpts("월간");
    const [cur, prev] = [opts[0].value, opts[1].value];
    let stale = false;
    fetch(`/api/admin/funds/${target}/workflow?period=${prev}`)
      .then((r) => r.json())
      .then((d) => {
        if (!stale) setPeriod(d?.comment?.status === "approved" ? cur : prev);
      })
      .catch(() => { /* 유지 */ });
    return () => { stale = true; };
  }, [target, kind]);

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
  useEffect(() => { if (target) loadWf(target, period); }, [target, period, loadWf]);

  const act = async (path: string, body: object, label: string) => {
    setBusy(label); setMsg("");
    try {
      const method = path.includes("/draft") ? "PUT" : "POST";
      const r = await fetch(`/api/admin/funds/${target}/${path}`, {
        method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setMsg(`✔ ${label} 완료`);
      loadWf(target, period);
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  // 승인 = 현재 편집 내용 저장 → 승인 (2026-08-03 fix).
  //   종전엔 승인 요청이 {period} 만 보내서, textarea 를 고친 뒤 수정저장 없이
  //   승인하면 서버가 디스크의 **구 draft** 를 승인했다(편집분 유실).
  const approveStage = async (kind: "comment" | "report") => {
    const text = kind === "comment" ? editText : editRpt;
    setBusy("승인"); setMsg("");
    try {
      const pre = await fetch(`/api/admin/funds/${target}/${kind}/draft`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period, text }),
      });
      if (!pre.ok) {
        const e = await pre.json().catch(() => null);
        setMsg(`✖ 편집분 저장 실패 — ${e?.detail ?? `HTTP ${pre.status}`}`);
        return;
      }
      const r = await fetch(`/api/admin/funds/${target}/${kind}/approve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period }),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setMsg("✔ 승인 완료 (편집분 반영)");
      loadWf(target, period);
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  return (
    <div className="afp-root">
      <div className="sra-gen">
        <span className="lab">코멘트 · 보고서 생성/관리</span>
        {/* 대상 토글 — 시장(_market) / 펀드 */}
        <div className="tx-seg" title="시장 = 월간 시장 debate(_market) · 펀드 = 펀드별 코멘트">
          <button type="button" className={isMarket ? "on" : ""}
            onClick={() => setScope("market")}>시장</button>
          <button type="button" className={!isMarket ? "on" : ""}
            onClick={() => setScope("fund")}>펀드</button>
        </div>
        <select value={fund} onChange={(e) => setFund(e.target.value)} disabled={isMarket}
          title={isMarket ? "시장 코멘트는 펀드 선택과 무관합니다" : "펀드 선택"}>
          {fundList.map((f) => <option key={f.code} value={f.code}>{f.code} — {f.name}</option>)}
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value as Kind)} title="기간 유형">
          {kindOpts.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <select value={period} onChange={(e) => setPeriod(e.target.value)}
          disabled={periodOpts.length <= 1} title={KIND_HINT[kind]}>
          {periodOpts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <span className="hint">{KIND_HINT[kind]} · 프로세스: {isMarket
          ? "시장 debate 생성→승인 → 펀드 코멘트가 이 승인본을 사용"
          : "펀드코멘트 생성→승인 → 보고서 생성→승인 → client 노출"}</span>
        {err && <span className="err">{err}</span>}
      </div>

      <div className="sra-genout">
        <div className="gh">{isMarket ? "시장(_market)" : fund} · {kind} {period} 워크플로우 {busy &&<span className="ref">⏳ {busy} 진행 중…</span>} {msg && <span className="ref">{msg}</span>}</div>
        {!wf ? <div className="sra-empty">로드 중…</div> : (
          <div className="afp-wf">
            {/* 1단계 — 시장 debate(_market) 또는 펀드코멘트 */}
            <div className="stage">
              <div className="sh">① {isMarket ? "시장 코멘트" : "펀드코멘트"} <StBadge s={wf.comment.status} />
                {wf.comment.approved_at && <span className="ref">승인 {wf.comment.approved_at.slice(0, 16)}</span>}
              </div>
              <div className="btns">
                <button type="button" disabled={!!busy}
                  onClick={() => act("comment/generate", { kind, period },
                    isMarket ? "시장 debate 생성 (1~2분)" : "코멘트 생성 (1~2분)")}>
                  {wf.comment.status === "not_generated" ? "생성" : "재생성"}
                </button>
                <button type="button" disabled={!!busy || wf.comment.status === "not_generated"}
                  onClick={() => act("comment/draft", { period, text: editText }, "코멘트 수정 저장")}>수정 저장</button>
                <button type="button" className="approve" disabled={!!busy || wf.comment.status === "not_generated"}
                  onClick={() => approveStage("comment")}>승인</button>
              </div>
              <AutoTextarea value={editText} onChange={setEditText}
                placeholder="코멘트 생성 후 편집" />
            </div>
            {/* 2단계 — 보고서 (코멘트 승인 게이트). 시장 코멘트는 발송용 단계가 없다. */}
            {!isMarket && (
            <div className="stage">
              <div className="sh">② 보고서 (발송용) <StBadge s={wf.report.status} />
                {wf.report.approved_at && <span className="ref">승인 {wf.report.approved_at.slice(0, 16)}</span>}
              </div>
              <div className="btns">
                <button type="button" disabled={!!busy || wf.comment.status !== "approved"}
                  title={wf.comment.status !== "approved" ? "펀드코멘트 승인 후 생성 가능" : "① 승인본을 복사해 발송용 초안 생성"}
                  onClick={() => act("report/generate", { kind, period }, "보고서 생성 (①승인본 복사)")}>
                  {wf.report.status === "not_generated" ? "생성" : "재생성"}
                </button>
                <button type="button" disabled={!!busy || wf.report.status === "not_generated"}
                  onClick={() => act("report/draft", { period, text: editRpt }, "보고서 수정 저장")}>수정 저장</button>
                <button type="button" className="approve" disabled={!!busy || wf.report.status === "not_generated"}
                  onClick={() => approveStage("report")}>승인</button>
                {/* 4JM12 월간: 보고서 생성 시 DB생명 데이터 엑셀 동시 산출 (s6=승인 코멘트) */}
                {wf.report.excel_ready && (
                  <a href={`/api/admin/funds/${fund}/report/excel?period=${period}`}>
                    <button type="button">DB생명 엑셀 다운로드</button>
                  </a>
                )}
                {fund === "4JM12" && kind === "월간" && !wf.report.excel_ready && (
                  <span className="ref">보고서 생성 시 DB생명 월간보고 엑셀이 함께 생성됩니다</span>
                )}
              </div>
              <AutoTextarea value={editRpt} onChange={setEditRpt}
                placeholder="① 승인 후 생성 → 편집" />
            </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
