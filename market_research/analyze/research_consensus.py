# -*- coding: utf-8 -*-
"""Research consensus → 09_Research_Synthesis page builder (P4).

wiki_from_naver_research P4. P3 자산군 집계 → 자산군별 consensus/dissent/risk
페이지(staging/audit). 결정적 claim trace(감사용) + 선택적 LLM 종합 narrative.

D5: consensus narrative = broker 만. monygeek = §2 이견 / §5 관점 분리.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from market_research.analyze.research_aggregator import (
    load_research_claims, aggregate_by_asset, distribution_report,
)
from market_research.wiki.paths import RESEARCH_SYNTHESIS_DIR

SYNTH_MODEL = "claude-haiku-4-5-20251001"
SYNTH_MAX_TOKENS = 1200

_ASSET_FILE_STEM = {
    "국내주식": "국내주식", "해외주식": "해외주식",
    "국내채권": "국내채권", "해외채권": "해외채권",
    "유동성": "유동성",
    "환율(FX)": "환율FX", "대체": "대체",
}


def _claim_ref(claim: dict) -> str:
    """claim_id 'claim:2026-05:abcd1234ef' → [claim:abcd1234ef]."""
    cid = claim.get("claim_id") or ""
    h = cid.split(":")[-1] if ":" in cid else cid
    return f"[claim:{h}]"


def _claim_line(claim: dict) -> str:
    stance = claim.get("stance") or "-"
    hz = claim.get("horizon") or "-"
    view = claim.get("view") or claim.get("claim_text") or ""
    broker = claim.get("broker_author") or claim.get("source_type") or ""
    return f"- {_claim_ref(claim)} ({stance}, {hz}, {broker}) {view}".rstrip()


def _default_llm_call(prompt: dict) -> str:
    from market_research.report.debate_engine import _call_llm
    return _call_llm(model=prompt["model"], system=prompt["system"],
                     prompt=prompt["user"], max_tokens=prompt["max_tokens"],
                     log_label="research_consensus")


def synthesize_asset_narrative(asset: str, a: dict[str, Any], *,
                               llm_call: Callable[[dict], str] | None = None) -> dict[str, str]:
    """자산군 consensus/dissent narrative (LLM). llm_call None → 빈 narrative."""
    if llm_call is None:
        return {"consensus_narrative": "", "dissent_narrative": ""}
    broker = a.get("broker_claims") or []
    monygeek = a.get("monygeek_claims") or []
    if not broker and not monygeek:
        return {"consensus_narrative": "", "dissent_narrative": ""}

    def _fmt(cs):
        return "\n".join(
            f"- ({c.get('stance')}, {c.get('horizon')}) {c.get('view') or c.get('claim_text')}"
            f" :: {c.get('rationale_text') or ''}"[:300] for c in cs[:12]) or "(없음)"

    # Phase 2.8 — broker-only causal skeleton (narrative 에 인과경로 반영용)
    causal = a.get("causal_paths") or []
    causal_block = ("\n".join(f"- {p.get('path')}" for p in causal)
                    if causal else "(인과 경로 없음)")
    causal_instr = (
        " consensus_narrative 와 리스크 서술은 위 '주요 인과 경로(broker)'를 따라 "
        "이벤트→지표→자산 전파를 자연어로 반영하세요(없으면 생략)." if causal else "")

    user = (
        f"자산군: {asset}\n"
        f"증권사 컨센서스 stance={a.get('consensus_stance')} "
        f"(vote={a.get('vote_distribution')}, strength={a.get('consensus_strength')})\n\n"
        f"## 증권사 리서치 claim (consensus 본류)\n{_fmt(broker)}\n\n"
        f"## 주요 인과 경로 (broker, top{len(causal)})\n{causal_block}\n\n"
        f"## monygeek 관점 (dissent/contrarian — consensus 산정 제외)\n{_fmt(monygeek)}\n\n"
        "위를 바탕으로 두 단락을 작성하세요(JSON):\n"
        '{"consensus_narrative": "증권사 컨센서스 2~3문장(stance 근거 중심)", '
        '"dissent_narrative": "이견/리스크/monygeek 관점 1~2문장"}\n'
        f"{causal_instr}\n"
        "순수 JSON 만, 마크다운 금지."
    )
    prompt = {"system": "당신은 OCIO 운용 리서치 종합 보조 모델입니다. 증권사 컨센서스를 "
                        "본류로, monygeek 은 보조 dissent 로 분리해 종합합니다.",
              "user": user, "model": SYNTH_MODEL, "max_tokens": SYNTH_MAX_TOKENS}
    try:
        raw = llm_call(prompt) or ""
        s = raw.find("{"); e = raw.rfind("}")
        obj = json.loads(raw[s:e + 1]) if s >= 0 and e > s else {}
        return {"consensus_narrative": str(obj.get("consensus_narrative", "")),
                "dissent_narrative": str(obj.get("dissent_narrative", ""))}
    except Exception:
        return {"consensus_narrative": "", "dissent_narrative": ""}


def build_research_synthesis_page(period: str, asset: str, a: dict[str, Any],
                                  narrative: dict[str, str]) -> str:
    """09_Research_Synthesis/{period}_{stem}.md 본문."""
    themes = list((a.get("by_theme") or {}).keys())
    horizons = list((a.get("by_horizon") or {}).keys())
    front = (
        "---\n"
        f"period: {period}\n"
        f"asset_class: {asset}\n"
        "source_type: research_synthesis\n"
        "generated_by: research_consensus\n"
        f"consensus_stance: {a.get('consensus_stance')}\n"
        f"vote_distribution: {json.dumps(a.get('vote_distribution', {}), ensure_ascii=False)}\n"
        f"consensus_strength: {a.get('consensus_strength')}\n"
        f"n_claims: {a.get('n_claims')} (broker {a.get('n_broker')} / monygeek {a.get('n_monygeek')})\n"
        f"themes: {json.dumps(themes, ensure_ascii=False)}\n"
        f"horizons: {json.dumps(horizons, ensure_ascii=False)}\n"
        "---\n\n"
    )
    b: list[str] = [f"# {period} {asset} — 리서치 종합", ""]

    b.append(f"## 1. 컨센서스 (stance: {a.get('consensus_stance')}, "
             f"strength {a.get('consensus_strength')})")
    if narrative.get("consensus_narrative"):
        b.append(narrative["consensus_narrative"])
    b.append(f"- vote(증권사): {a.get('vote_distribution')}")
    b.append("")

    b.append("## 2. 이견 (dissent / tail-risk)")
    if narrative.get("dissent_narrative"):
        b.append(narrative["dissent_narrative"])
    dissent = a.get("dissent") or []
    for c in dissent[:8]:
        b.append(_claim_line(c))
    if not dissent:
        b.append("- (유의미한 이견 없음)")
    b.append("")

    b.append("## 3. 리스크")
    # Phase 2.8 — broker-only 인과 경로(causal skeleton) 를 §3 상단에 명시(traceable).
    causal = a.get("causal_paths") or []
    if causal:
        b.append("주요 인과 경로(broker):")
        for p in causal:
            ref = _claim_ref({"claim_id": p.get("claim_id")}) if p.get("claim_id") else ""
            b.append(f"- {p.get('path')} {ref}".rstrip())
    for rf in (a.get("risk_factors") or [])[:6]:
        b.append(f"- {rf}")
    if not a.get("risk_factors") and not causal:
        b.append("- (명시 리스크 제한적)")
    b.append("")

    b.append("## 4. 근거 claim (broker)")
    for c in (a.get("broker_claims") or [])[:12]:
        b.append(_claim_line(c))
    b.append("")

    b.append("## 5. monygeek 관점")
    mg = a.get("monygeek_claims") or []
    for c in mg[:6]:
        b.append(_claim_line(c))
    if not mg:
        b.append("- (본월 monygeek 직접 매핑 제한적)")
    b.append("")

    return front + "\n".join(b)


def run_research_synthesis(month: str, *, use_llm: bool = True,
                           dry_run: bool = False, include_causal: bool = True,
                           llm_call: Callable[[dict], str] | None = None) -> dict[str, Any]:
    """월별 09_Research_Synthesis 페이지 생성. dry_run=True → 파일 미저장.

    include_causal (Phase 2.8): broker-only causal_chain 집계를 §1 narrative + §3 에
      반영(on/off). False 면 인과 경로 미반영(기존 동작).
    """
    claims = load_research_claims(month)
    agg = aggregate_by_asset(claims, include_causal=include_causal)
    report = distribution_report(agg)

    call = (llm_call or _default_llm_call) if use_llm else None
    pages: dict[str, str] = {}
    for asset, a in agg.items():
        narrative = synthesize_asset_narrative(asset, a, llm_call=call)
        pages[asset] = build_research_synthesis_page(month, asset, a, narrative)

    written: list[str] = []
    if not dry_run:
        RESEARCH_SYNTHESIS_DIR.mkdir(parents=True, exist_ok=True)
        for asset, body in pages.items():
            stem = _ASSET_FILE_STEM.get(asset, asset.replace("/", "_"))
            p = RESEARCH_SYNTHESIS_DIR / f"{month}_{stem}.md"
            p.write_text(body, encoding="utf-8")
            written.append(str(p))

    return {"month": month, "n_assets": len(agg), "report": report,
            "pages": pages, "written": written,
            "total_claims": report["total_claims"]}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Research consensus → 09_Research_Synthesis (P4)")
    ap.add_argument("month")
    ap.add_argument("--no-llm", action="store_true", help="LLM narrative 생략(결정적만)")
    ap.add_argument("--no-causal", action="store_true",
                    help="Phase 2.8 causal_chain 집계 비활성(기존 동작)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    r = run_research_synthesis(args.month, use_llm=not args.no_llm, dry_run=args.dry_run,
                              include_causal=not args.no_causal)
    print(f"[research_synthesis] {args.month} assets={r['n_assets']} "
          f"claims={r['total_claims']} pages_written={len(r['written'])}")
    for w in r["report"]["warnings"]:
        print(f"  ⚠ {w}")
    for row in r["report"]["rows"]:
        print(f"  {row['asset_class']}: n={row['n_claims']} "
              f"(broker {row['broker']}/mg {row['monygeek']}) "
              f"consensus={row['consensus']} str={row['strength']} vote={row['vote']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
