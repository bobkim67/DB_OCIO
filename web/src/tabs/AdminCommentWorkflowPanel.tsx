import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "../styles/sentreports.css";
import "../styles/transactions.css";   // 대상 토글(.tx-seg) 재사용
import { useFunds } from "../hooks/useFunds";
import AdminMarketSeedPanel from "./AdminMarketSeedPanel";
import AdminResearchWikiPanel from "./AdminResearchWikiPanel";

/**
 * Admin > 코멘트 생성/관리 (2026-07-10 분리 신설).
 * 펀드·기간 선택 후 2단계 워크플로우:
 *   ① 펀드코멘트 생성→편집→승인 → (승인 게이트) → ② 보고서 생성→편집→승인 → client 노출.
 * (기존 AdminFundsPanel 확장 행에 묻혀 있던 워크플로우를 별도 서브탭으로 분리)
 */
type Stage = {
  status: string; text: string; approved_at: string; generated_at: string;
  excel_ready?: boolean;      // 보고서 단계 산출물 존재 여부 (EXCEL_SPEC 참조)
  build_warnings?: string[];  // 산출물 빌더 경고 — 승인 응답에만 실린다
};

// 보고서 단계에 딸린 산출물 — 백엔드 `admin_funds._EXCEL_SPECS` 와 1:1 대응.
// on = 어느 단계에서 구워지는지 — 2026-08-06 전 펀드 '승인 시'로 통일.
const EXCEL_SPEC: Record<string, { label: string; on: "generate" | "approve" }> = {
  "4JM12": { label: "DB생명 엑셀", on: "approve" },
  "08N33": { label: "월간운용보고서 엑셀", on: "approve" },
  "08N81": { label: "월간운용보고서 엑셀", on: "approve" },
  "08P22": { label: "월간운용보고서 엑셀", on: "approve" },
  "08K88": { label: "월간운용보고서 엑셀", on: "approve" },
  // 발송본 PPT 표에 블록 복사로 붙여넣는 데이터 시트 (Comment + 자산배분현황)
  "2JM23": { label: "신한라이프 엑셀", on: "approve" },
  // 발송본 워드 표에 블록 복사로 붙여넣는 데이터 시트 (표 + 서술)
  "07G07": { label: "KB 워드 엑셀", on: "approve" },
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

/** 내용 높이에 맞춰 자동으로 늘어나는 textarea — 스크롤 없이 전문을 펼쳐 본다
 *  (2026-08-03 사용자 지시. 코멘트가 1,300~1,700자라 rows 고정으론 계속 스크롤해야 했다).
 *
 *  ★ 2026-08-06 수정 — 바닥이 잘리던 문제.
 *   - `height` 를 직접 박으면 그 순간의 `scrollHeight` 로 고정된다. 폰트가 늦게 로드되거나
 *     폭이 바뀌어 줄 수가 늘면 **높이는 그대로라 마지막 줄이 잘린다**
 *     (실측 ①펀드코멘트 481px / 내용 499px → 18px 잘림, overflowY:hidden 이라 접근 불가).
 *     → `minHeight` 로 바꾸고 `flex:1` 로 칸을 채운다. 좌우 stage 가 그리드에서 같은 높이로
 *       늘어나므로 ①이 ②(보고서)만큼 커진다.
 *   - `overflowY:auto` + 상한(70vh) — 아주 긴 코멘트는 패널을 무한정 늘리지 않고 스크롤한다.
 *   - `ResizeObserver` 로 폭 변화에도 다시 잰다.
 */
function AutoTextarea({ value, onChange, placeholder }: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      el.style.minHeight = "0px";                  // 줄어들 때도 다시 계산되도록 초기화
      el.style.minHeight = `${el.scrollHeight + 2}px`;  // +2 = border 보정
    };
    fit();
    const ro = new ResizeObserver(fit);            // 폭 변화 → 줄바꿈 수 변화
    ro.observe(el);
    return () => ro.disconnect();
  }, [value]);
  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
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

  // 대상 펀드 = **상단 대시보드 선택** 단일 소스 (2026-08-05 사용자 지시).
  //
  // ★ 종전엔 이 패널에도 펀드 select 가 있었는데 **동작하지 않았다**:
  //   effect 의 deps 에 `fund` 가 들어 있어, 로컬 select 로 바꾸는 즉시 effect 가
  //   다시 돌며 `setFund(fundCode)` 로 상단 값으로 되돌렸다(상단 선택이 유효한
  //   한 항상). 선택지가 둘인데 하나가 무력화된 상태라 select 를 제거하고
  //   상단 하나로 일원화한다. 목록에 없으면(권한/필터) 첫 펀드로 폴백.
  const fund = useMemo(() => {
    if (fundCode && fundList.some((f) => f.code === fundCode)) return fundCode;
    return fundList[0]?.code ?? "";
  }, [fundCode, fundList]);

  // 대상 = 시장(_market) | 펀드 (2026-08-03 사용자 지시).
  // 시장은 debate 를 직접 돌리며 ②발송용 보고서 단계가 없다(client 는 /market-report 조회).
  // TD(QTD/HTD/YTD)는 시장 debate 를 돌리지 않고 월간/분기 승인본을 재사용하므로 유형에서 제외.
  // 2026-08-05: '시드' 추가 — 시장 debate 승인 → **시드 생성·승인** → 펀드 코멘트.
  // 시드는 공통 문단(시장동향·전망)의 단일 소스이고, 펀드는 보유 자산군 문장만
  // 골라 조립한다. TD 기간도 시드는 만들 수 있다(월간·분기 승인본 재사용).
  // 2026-08-06: 'wiki' 추가 — 자산군별 09 원문 + claim 전량 + 원본 링크(조회 전용).
  const [scope, setScope] = useState<"market" | "seed" | "wiki" | "fund">("fund");
  const isMarket = scope === "market";
  const isSeed = scope === "seed";
  const isWiki = scope === "wiki";
  const target = isMarket ? "_market" : fund;
  const kindOpts = useMemo<readonly Kind[]>(
    () => (isMarket ? (["월간", "분기"] as const) : KINDS), [isMarket]);
  useEffect(() => {
    if (!kindOpts.includes(kind)) setKind(kindOpts[0]);
  }, [kindOpts, kind]);

  // 기간 기본값 (월간) — **전월 코멘트가 아직 승인 전이면 전월**(마감 작업 중),
  // 이미 승인됐으면 **당월 MTD**. (2026-08-03 사용자 지시)
  // 조회 실패 시 기존 선택 유지 — 화면이 튀지 않게.
  //
  // ★ 시드는 기간 단위 산출물이라 펀드와 무관하다 → 판정 기준도 `_market` 을 쓴다.
  //   `target`(=펀드)로 판정하면 상단 펀드를 바꿀 때마다 시드 탭의 기간이 따라
  //   움직여, 펀드 무관이라는 성질이 깨진다 (2026-08-05).
  const periodProbe = isMarket || isSeed || isWiki ? "_market" : target;
  useEffect(() => {
    if (kind !== "월간" || !periodProbe) return;
    const opts = buildPeriodOpts("월간");
    const [cur, prev] = [opts[0].value, opts[1].value];
    let stale = false;
    fetch(`/api/admin/funds/${periodProbe}/workflow?period=${prev}`)
      .then((r) => r.json())
      .then((d) => {
        if (!stale) setPeriod(d?.comment?.status === "approved" ? cur : prev);
      })
      .catch(() => { /* 유지 */ });
    return () => { stale = true; };
  }, [periodProbe, kind]);

  // 시드 승인 여부 — 펀드 코멘트가 공통 문단을 시드로 조립할지 미리 알려준다.
  // 미승인이면 종전처럼 LLM 이 전문을 쓰므로 펀드 간 편차가 남는다.
  const [seedStatus, setSeedStatus] = useState<string>("");
  useEffect(() => {
    if (isMarket || !period) return;
    let stale = false;
    fetch(`/api/admin/market-seed?period=${encodeURIComponent(period)}`)
      .then((r) => r.json())
      .then((d) => { if (!stale) setSeedStatus(d?.status ?? ""); })
      .catch(() => { if (!stale) setSeedStatus(""); });
    return () => { stale = true; };
  }, [period, isMarket, scope]);

  // 보고서 승인이 산출물(엑셀/PPT)까지 굽는 조합인지 — 승인이 오래 걸린다는 안내용.
  const artifactOnApprove = kind === "월간" && EXCEL_SPEC[fund]?.on === "approve";

  const [wf, setWf] = useState<{ comment: Stage; report: Stage } | null>(null);
  // 산출물 빌더 경고 — 승인 응답에만 실려 오므로 별도로 붙들어 둔다.
  // (2JM23 PPT 의 템플릿 승계·현금 잔여 경고처럼 발송 전 눈으로 봐야 하는 것들)
  const [buildWarn, setBuildWarn] = useState<string[]>([]);
  const [editText, setEditText] = useState("");
  const [editRpt, setEditRpt] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const loadWf = useCallback((f: string, p: string) => {
    if (!f) return;
    setWf(null); setMsg(""); setBuildWarn([]);
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
      const w: string[] = d?.build_warnings ?? [];
      loadWf(target, period);            // loadWf 가 경고를 비우므로 그 뒤에 세운다
      if (w.length) setBuildWarn(w);
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  // 승인 = 현재 편집 내용 저장 → 승인 (2026-08-03 fix).
  //   종전엔 승인 요청이 {period} 만 보내서, textarea 를 고친 뒤 수정저장 없이
  //   승인하면 서버가 디스크의 **구 draft** 를 승인했다(편집분 유실).
  const approveStage = async (stage: "comment" | "report") => {
    const text = stage === "comment" ? editText : editRpt;
    // 승인이 산출물까지 굽는 조합은 오래 걸린다 — 멈춘 걸로 오해하지 않게 알린다
    setBusy(stage === "report" && artifactOnApprove
      ? `승인 + ${EXCEL_SPEC[fund].label} 생성`
      : "승인");
    setMsg("");
    try {
      const pre = await fetch(`/api/admin/funds/${target}/${stage}/draft`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period, text }),
      });
      if (!pre.ok) {
        const e = await pre.json().catch(() => null);
        setMsg(`✖ 편집분 저장 실패 — ${e?.detail ?? `HTTP ${pre.status}`}`);
        return;
      }
      const r = await fetch(`/api/admin/funds/${target}/${stage}/approve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period }),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setMsg("✔ 승인 완료 (편집분 반영)");
      const w: string[] = d?.build_warnings ?? [];
      loadWf(target, period);            // loadWf 가 경고를 비우므로 그 뒤에 세운다
      if (w.length) setBuildWarn(w);
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  return (
    <div className="afp-root">
      <div className="sra-gen">
        <span className="lab">코멘트 · 보고서 생성/관리</span>
        {/* 대상 토글 — 시장(_market) / 펀드 */}
        <div className="tx-seg" title="시장 debate → 자산군 시드 → 펀드 코멘트 순서로 진행합니다">
          <button type="button" className={isMarket ? "on" : ""}
            onClick={() => setScope("market")}>시장</button>
          <button type="button" className={isSeed ? "on" : ""}
            onClick={() => setScope("seed")}>시드</button>
          <button type="button" className={isWiki ? "on" : ""}
            onClick={() => setScope("wiki")}>wiki</button>
          <button type="button" className={scope === "fund" ? "on" : ""}
            onClick={() => setScope("fund")}>펀드</button>
        </div>
        {/* 펀드 선택·표시는 **상단 대시보드 드롭다운 단일 소스** (2026-08-05 사용자 지시).
            여기 두면 중복 노출이라 아예 두지 않는다. 시장·시드가 펀드 무관이라는
            사실은 아래 hint 의 프로세스 문구가 이미 설명한다. */}
        <select value={kind} onChange={(e) => setKind(e.target.value as Kind)} title="기간 유형">
          {kindOpts.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <select value={period} onChange={(e) => setPeriod(e.target.value)}
          disabled={periodOpts.length <= 1} title={KIND_HINT[kind]}>
          {periodOpts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <span className="hint">{KIND_HINT[kind]} · 프로세스: {isMarket
          ? "시장 debate 생성→승인 → 시드 생성→승인 → 펀드 코멘트"
          : isSeed
          ? "시장 승인본 → 자산군별 문장 분해 → 승인 → 전 펀드 공통 문단으로 사용"
          : isWiki
          ? "시장 debate 가 실제로 본 근거 — 09 원문 + 자산군별 claim 전량(컷 포함) + 원본 리포트"
          : "펀드코멘트 생성→승인 → 보고서 생성→승인 → client 노출"}</span>
        {err && <span className="err">{err}</span>}
      </div>

      {isWiki ? <AdminResearchWikiPanel period={period} />
        : isSeed ? <AdminMarketSeedPanel kind={kind} period={period} /> : (
      <div className="sra-genout">
        <div className="gh">{isMarket ? "시장(_market)" : fund} · {kind} {period} 워크플로우 {busy &&<span className="ref">⏳ {busy} 진행 중…</span>} {msg && <span className="ref">{msg}</span>}</div>
        {!wf ? <div className="sra-empty">로드 중…</div> : (
          <div className="afp-wf">
            {/* 1단계 — 시장 debate(_market) 또는 펀드코멘트 */}
            <div className="stage">
              <div className="sh">① {isMarket ? "시장 코멘트" : "펀드코멘트"} <StBadge s={wf.comment.status} />
                {wf.comment.approved_at && <span className="ref">승인 {wf.comment.approved_at.slice(0, 16)}</span>}
                {!isMarket && (
                  <span className="ref" style={{ color: seedStatus === "approved" ? "#1e7b45" : "#8a5a00" }}>
                    {seedStatus === "approved"
                      ? "시드 승인됨 — 공통 문단은 시드로 조립"
                      : "시드 미승인 — 공통 문단을 LLM 이 새로 씁니다 (펀드 간 편차 발생)"}
                  </span>
                )}
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
                  title={artifactOnApprove
                    ? `승인 시 ${EXCEL_SPEC[fund].label}이 재생성됩니다`
                    : undefined}
                  onClick={() => approveStage("report")}>승인</button>
                {/* 보고서 단계 산출물(엑셀/PPT) — 월간에만, EXCEL_SPEC 등록 펀드만 노출 */}
                {kind === "월간" && EXCEL_SPEC[fund] && (
                  wf.report.excel_ready ? (
                    <a href={`/api/admin/funds/${fund}/report/excel?period=${period}`}>
                      <button type="button">{EXCEL_SPEC[fund].label} 다운로드</button>
                    </a>
                  ) : (
                    <span className="ref">
                      보고서 {EXCEL_SPEC[fund].on === "approve" ? "승인" : "생성"} 시{" "}
                      {EXCEL_SPEC[fund].label}이 함께 생성됩니다
                    </span>
                  )
                )}
              </div>
              {/* 빌더 경고 — 템플릿 승계 항목·현금 잔여 등 발송 전 눈으로 확인할 것 */}
              {!!buildWarn.length && (
                <div style={{ fontSize: 11, color: "#8a5a00", margin: "4px 0 6px", lineHeight: 1.6 }}>
                  {buildWarn.map((w, i) => <div key={i}>⚠ {w}</div>)}
                </div>
              )}
              <AutoTextarea value={editRpt} onChange={setEditRpt}
                placeholder="① 승인 후 생성 → 편집" />
            </div>
            )}
          </div>
        )}
      </div>
      )}
    </div>
  );
}
