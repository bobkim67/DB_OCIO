import { useCallback, useEffect, useMemo, useState } from "react";
import "../styles/sentreports.css";

/**
 * Admin > 자산군 시드 (2026-08-05 사용자 지시).
 *
 * 시장동향·전망 공통 문단을 **기간당 1본** 만들어 전 펀드가 공유한다.
 * 펀드 코멘트 생성은 **승인된 시드만** 사용하고, 보유하지 않은 자산군 문장은
 * 통째로 삭제한다(대체 문장 없음). 워크플로우:
 *   시장 debate 승인 → **시드 생성·승인** → 펀드 코멘트 생성
 *
 * 종전엔 펀드마다 LLM 이 공통 문단을 새로 써서 미세하게 갈렸고, 2026-07 은
 * 7개 펀드를 손으로 통일해 발송했다.
 */
export type SeedSections = { market: Record<string, string>; outlook: Record<string, string> };
export type Seed = {
  period: string;
  status: string;
  sections: SeedSections;
  outlook_period: string;
  generated_at: string;
  approved_at: string;
  model: string;
  cost_usd: number;
  over_budget: { section: string; key: string; chars: number; limit: number }[];
  classes: string[];
  market_order: string[];
  outlook_order: string[];
};

const TOTAL_KEY = "_총론";

const SEED_ST_LABEL: Record<string, string> = {
  not_generated: "미생성", draft: "초안", approved: "승인",
};
const SEED_ST_COLOR: Record<string, { bg: string; fg: string }> = {
  not_generated: { bg: "#eef0f3", fg: "#667085" },
  draft: { bg: "#e8f0fe", fg: "#1a4d8f" },
  approved: { bg: "#e6f4ea", fg: "#1e7b45" },
};

/** 2026-07 08N81 승인본 실측 — 자산군 6개가 모두 살아 있을 때의 목표 분량. */
const TARGET = { market: 653, outlook: 545 };

function Badge({ s }: { s: string }) {
  const c = SEED_ST_COLOR[s] ?? SEED_ST_COLOR.not_generated;
  return <span className="afp-badge" style={{ background: c.bg, color: c.fg }}>{SEED_ST_LABEL[s] ?? s}</span>;
}

/** 서버 조립(market_seed.assemble)과 같은 규칙으로 미리보기.
 *  전망은 첫 문장에만 기간 라벨을 붙인다. */
function preview(sec: Record<string, string>, order: string[],
                 section: "market" | "outlook", label: string): string {
  const parts: string[] = [];
  if (section === "market") {
    const head = (sec[TOTAL_KEY] ?? "").trim();
    if (head) parts.push(head);
  }
  for (const c of order) {
    const s = (sec[c] ?? "").trim();
    if (s) parts.push(s);
  }
  if (!parts.length) return "";
  if (section === "outlook" && label) {
    parts[0] = `${label} ${parts[0].replace(/^(?:\d{4}년\s*)?(?:\d{1,2}월|\d분기|[상하]반기)\s+/, "")}`;
  }
  return parts.join(" ");
}

function Field({ label, hint, value, onChange, limit }: {
  label: string; hint?: string; value: string;
  onChange: (v: string) => void; limit: number;
}) {
  const n = value.length;
  const over = n > limit;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 3 }}>
        <strong style={{ fontSize: 13 }}>{label}</strong>
        {hint && <span className="ref" style={{ fontSize: 11 }}>{hint}</span>}
        <span style={{ marginLeft: "auto", fontSize: 11, color: over ? "#b42318" : "#667085" }}>
          {n}자{over ? ` (상한 ${limit} 초과)` : ""}
        </span>
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        placeholder="비워두면 이 자산군 문장은 조립에서 제외됩니다"
        style={{ width: "100%", resize: "vertical", borderColor: over ? "#f0a3a3" : undefined }}
      />
    </div>
  );
}

export default function AdminMarketSeedPanel({ kind, period }: { kind: string; period: string }) {
  const [seed, setSeed] = useState<Seed | null>(null);
  const [draft, setDraft] = useState<SeedSections>({ market: {}, outlook: {} });
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback((p: string) => {
    setSeed(null); setMsg("");
    fetch(`/api/admin/market-seed?period=${encodeURIComponent(p)}`)
      .then((r) => r.json())
      .then((d: Seed) => {
        setSeed(d);
        setDraft({ market: { ...d.sections.market }, outlook: { ...d.sections.outlook } });
      })
      .catch((e) => setMsg(`✖ ${String(e)}`));
  }, []);
  useEffect(() => { load(period); }, [period, load]);

  const call = async (path: string, body: object, label: string, method = "POST") => {
    setBusy(label); setMsg("");
    try {
      const r = await fetch(`/api/admin/market-seed${path}`, {
        method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(`✖ ${d?.detail ?? `HTTP ${r.status}`}`); return; }
      setSeed(d);
      setDraft({ market: { ...d.sections.market }, outlook: { ...d.sections.outlook } });
      setMsg(`✔ ${label} 완료`);
    } catch (e) { setMsg(`✖ ${String(e)}`); } finally { setBusy(""); }
  };

  const set = (section: "market" | "outlook", key: string, v: string) =>
    setDraft((d) => ({ ...d, [section]: { ...d[section], [key]: v } }));

  const previews = useMemo(() => {
    if (!seed) return null;
    return {
      market: preview(draft.market, seed.market_order, "market", ""),
      outlook: preview(draft.outlook, seed.outlook_order, "outlook", seed.outlook_period),
    };
  }, [draft, seed]);

  if (!seed) return <div className="sra-empty">로드 중…</div>;

  const notGen = seed.status === "not_generated";
  const isTD = kind === "QTD" || kind === "HTD" || kind === "YTD";

  return (
    <div className="sra-genout">
      <div className="gh">
        자산군 시드 · {kind} {period} <Badge s={seed.status} />
        {seed.approved_at && <span className="ref">승인 {seed.approved_at.slice(0, 16)}</span>}
        {seed.cost_usd > 0 && <span className="ref">${seed.cost_usd.toFixed(3)}</span>}
        {busy && <span className="ref">⏳ {busy} 진행 중…</span>}
        {msg && <span className="ref">{msg}</span>}
      </div>

      <div className="btns" style={{ marginBottom: 10 }}>
        <button type="button" disabled={!!busy}
          onClick={() => call("/generate", { kind, period }, "시드 생성 (1~2분)")}>
          {notGen ? "생성" : "재생성"}
        </button>
        <button type="button" disabled={!!busy || notGen}
          onClick={() => call("/draft", { period, sections: draft }, "수정 저장", "PUT")}>
          수정 저장
        </button>
        <button type="button" className="approve" disabled={!!busy || notGen}
          onClick={async () => {
            await call("/draft", { period, sections: draft }, "수정 저장", "PUT");
            await call("/approve", { period }, "승인");
          }}>
          승인
        </button>
      </div>

      <div className="hint" style={{ marginBottom: 12 }}>
        승인된 시드만 펀드 코멘트에 쓰입니다. 펀드가 보유하지 않은 자산군 문장은
        <strong> 통째로 삭제</strong>되고 대체 문장은 넣지 않습니다.
        {isTD && " TD 기간은 시장 debate 승인본(월간·분기)을 재사용해 시드를 만듭니다."}
        {seed.over_budget.length > 0 && (
          <span style={{ color: "#b42318" }}>
            {" "}· 분량 초과 {seed.over_budget.length}건 — 조립 결과가 발송본보다 길어집니다.
          </span>
        )}
      </div>

      {notGen ? (
        <div className="sra-empty">시드가 없습니다. 시장 코멘트 승인 후 “생성”을 누르세요.</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
          {(["market", "outlook"] as const).map((section) => {
            const order = section === "market" ? seed.market_order : seed.outlook_order;
            const title = section === "market" ? "시장동향" : `전망 (${seed.outlook_period || "다음 기간"})`;
            const pv = previews?.[section] ?? "";
            return (
              <div key={section}>
                <div className="sh" style={{ marginBottom: 8 }}>
                  {title}
                  <span className="ref">
                    조립 {pv.length}자 / 목표 {TARGET[section]}자 (전 자산군 보유 기준)
                  </span>
                </div>
                {section === "market" && (
                  <Field label="_총론" hint="자산군에 속하지 않는 매크로 드라이버 · 항상 포함"
                    value={draft.market[TOTAL_KEY] ?? ""}
                    onChange={(v) => set("market", TOTAL_KEY, v)} limit={170} />
                )}
                {order.map((c) => (
                  <Field key={c} label={c}
                    value={draft[section][c] ?? ""}
                    onChange={(v) => set(section, c, v)}
                    limit={section === "market" ? 145 : 165} />
                ))}
                <details style={{ marginTop: 6 }}>
                  <summary style={{ cursor: "pointer", fontSize: 12 }}>
                    조립 미리보기 (전 자산군 보유 펀드 기준)
                  </summary>
                  <div style={{ fontSize: 12, lineHeight: 1.65, padding: "8px 0", whiteSpace: "pre-wrap" }}>
                    {pv || <span className="ref">내용 없음</span>}
                  </div>
                </details>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
