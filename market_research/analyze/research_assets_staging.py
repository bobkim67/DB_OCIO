# -*- coding: utf-8 -*-
"""P5 — 03_Assets 재배선 staging (운영 미반영, diff/dry 검증 전용).

wiki_from_naver_research P5. 재생성된 09 conviction + market_snapshot(DB) + claims 를
03_Assets 소비 규칙대로 결합해 **staging 경로에만** 생성한다. 운영 wiki overwrite/
commit/debate 일절 없음. provenance 4분리:
  stance/conviction ← 09 / market level ← market_db / rationale ← claims /
  secondary driver ← driver_region·us_driven_kr (+ credit_sleeve subsection 분리).

소비 규칙:
- directional stance: 국내주식/해외주식/국내채권/해외채권
- non-directional: 원자재금/환율(FX)  (bull/bear 강제 금지)
- 미공급: 기타/현금성
- 크레딧 흡수분: credit_sleeve subsection (채권 main stance vote 미오염)
- us_driven_kr: secondary driver (국내 main rationale 과 분리)
- 시장 레벨: market_snapshot 주입 (09 conviction 근거로 쓰지 않음)
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from market_research.analyze.research_aggregator import (
    load_research_claims, aggregate_by_asset, _base_primary,
)
from market_research.analyze.research_audit import LOW_CONVICTION_STRENGTH
from market_research.analyze.market_snapshot import market_snapshot
from market_research.wiki.paths import RESEARCH_SYNTHESIS_DIR

BASE_DIR = Path(__file__).resolve().parent.parent
STAGING_DIR = BASE_DIR / 'debug' / 'wiki' / 'p5_assets_staging'

DIRECTIONAL = ("국내주식", "해외주식", "국내채권", "해외채권")
NON_DIRECTIONAL = ("원자재금", "환율(FX)")
NOT_SUPPLIED = ("기타", "현금성")

# 자산군 → market_snapshot metric (등록된 것만; 나머지는 주입 보류)
ASSET_METRIC = {
    "국내주식": "KOSPI",
    "원자재금": "Gold",
    "환율(FX)": "USDKRW",
    # 해외주식(S&P)/국내채권/해외채권(금리): metric 미등록 → 보류
}

_ASSET_STEM = {
    "국내주식": "국내주식", "해외주식": "해외주식", "국내채권": "국내채권",
    "해외채권": "해외채권", "원자재금": "원자재금", "환율(FX)": "환율FX",
}


def _is_credit(claim: dict) -> bool:
    return _base_primary(claim) == "크레딧"


def _claim_line(c: dict) -> str:
    st = c.get("stance") or "-"
    hz = c.get("horizon") or "-"
    br = c.get("broker_author") or c.get("source_type") or ""
    v = c.get("view") or c.get("claim_text") or ""
    cid = (c.get("claim_id") or "").split(":")[-1]
    return f"- [claim:{cid}] ({st}, {hz}, {br}) {v}".rstrip()


def _read_09_consensus(period: str, asset: str) -> str:
    """09 §1 consensus narrative 산문(헤더/vote 줄 제외)."""
    stem = _ASSET_STEM.get(asset, asset.replace("/", "_"))
    p = RESEARCH_SYNTHESIS_DIR / f"{period}_{stem}.md"
    if not p.exists():
        return ""
    body = p.read_text(encoding="utf-8")
    if "## 1." not in body:
        return ""
    sec = body.split("## 1.")[-1].split("## 2.")[0]
    lines = [ln for ln in sec.splitlines()[1:] if not ln.strip().startswith("- vote")]
    return "\n".join(ln for ln in lines if ln.strip())


def _market_section(asset: str, period: str) -> tuple[str, dict | None]:
    metric = ASSET_METRIC.get(asset)
    if not metric:
        return ("## 1. 시장 레벨 (출처: market_db)\n"
                "- DB metric 미등록 — 시장 레벨 주입 보류 (S&P/Nasdaq/금리 series 확정 후)\n", None)
    snap = market_snapshot(metric, period)
    if not snap:
        return (f"## 1. 시장 레벨 (출처: market_db / {metric})\n- 데이터 없음\n", None)
    ms, me = snap["month_start"], snap["month_end"]
    hi, lo = snap["month_high"], snap["month_low"]
    txt = (f"## 1. 시장 레벨 (출처: market_db / {metric})\n"
           f"- {metric} 월말 {me['level']:,} (월초 {ms['level']:,}, "
           f"고 {hi['level']:,}/저 {lo['level']:,}, {snap['month_return_pct']:+.2f}%) "
           f"[{snap['source']}]\n")
    return txt, snap


def build_staging_asset_page(period: str, asset: str,
                             a: dict[str, Any]) -> tuple[str, dict]:
    """단일 staging 03_Assets 페이지 + trace row."""
    directional = asset in DIRECTIONAL
    strength = a.get("consensus_strength") or 0.0
    stance = a.get("consensus_stance")
    broker = a.get("broker_claims") or []
    credit = [c for c in broker if _is_credit(c)]
    non_credit = [c for c in broker if not _is_credit(c)]
    us_driven = [c for c in broker if asset in ("국내주식", "국내채권")
                 and c.get("_driver_region") in ("US", "overseas")]

    market_txt, snap = _market_section(asset, period)

    front = (
        "---\n"
        f"period: {period}\nasset_class: {asset}\n"
        "source_type: asset_staging\ngenerated_by: research_assets_staging\n"
        "stance_source: research_claims_09\n"
        f"market_level_source: {'market_db' if snap else 'none'}\n"
        f"directional: {str(directional).lower()}\n"
        f"consensus_stance: {stance}\nconsensus_strength: {strength}\n"
        f"credit_sleeve_claims: {len(credit)}\nus_driven_kr: {len(us_driven)}\n"
        "---\n\n"
    )
    b = [f"# {period} {asset} — 운용보고 자산군 (P5 staging)", "", market_txt]

    # 2. conviction (09)
    if directional:
        b.append(f"## 2. 컨센서스 / conviction (출처: research_claims 09)")
        b.append(f"- **stance: {stance}** (strength {strength}, directional)")
    else:
        b.append("## 2. 컨센서스 / conviction (출처: research_claims 09, **non-directional**)")
        b.append(f"- 의견 분산 (strength {strength} < {LOW_CONVICTION_STRENGTH}) — "
                 "방향성 미제시, 요약만 사용")
    nar = _read_09_consensus(period, asset)
    if nar:
        b.append(nar)
    b.append("")

    # 3. rationale (claims, credit 제외)
    b.append("## 3. 핵심 논거 (출처: research claims)")
    for c in non_credit[:8]:
        b.append(_claim_line(c))
    b.append("")

    # 4. credit_sleeve (채권만, main stance 미합산)
    if asset in ("국내채권", "해외채권"):
        b.append("## 4. credit_sleeve (출처: 크레딧 claims — 채권 main stance 미합산)")
        if credit:
            for c in credit[:6]:
                b.append(_claim_line(c))
        else:
            b.append("- (해당 월 크레딧 흡수분 없음)")
        b.append("")

    # 5. secondary driver (us_driven_kr)
    if asset in ("국내주식", "국내채권"):
        b.append("## 5. secondary driver (출처: driver_region=US/overseas — primary 아님)")
        if us_driven:
            for c in us_driven[:5]:
                b.append(_claim_line(c))
        else:
            b.append("- (US driver 인 국내자산 claim 없음)")
        b.append("")

    trace = {
        "asset": asset, "stance_source": "research_claims_09",
        "stance": stance if directional else "(non-directional)",
        "directional": directional,
        "market_snapshot_used": bool(snap),
        "market_metric": ASSET_METRIC.get(asset),
        "market_level_month_end": (snap["month_end"]["level"] if snap else None),
        "credit_sleeve": len(credit),
        "us_driven_kr": len(us_driven),
        "n_broker": len(broker),
    }
    return front + "\n".join(b), trace


def run_p5_staging(period: str) -> dict[str, Any]:
    """전체 staging 생성 + diff + trace. 운영 미반영."""
    from market_research.wiki.asset_fund_enrichment_builder import build_asset_page

    agg = aggregate_by_asset(load_research_claims(period))
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    (STAGING_DIR / "03_Assets").mkdir(parents=True, exist_ok=True)

    traces: list[dict] = []
    diffs: list[str] = []
    supplied = DIRECTIONAL + NON_DIRECTIONAL
    for asset in supplied:
        a = agg.get(asset)
        if not a:
            traces.append({"asset": asset, "note": "no claims (skip)"})
            continue
        staging, tr = build_staging_asset_page(period, asset, a)
        stem = _ASSET_STEM.get(asset, asset)
        (STAGING_DIR / "03_Assets" / f"{period}_{stem}.md").write_text(
            staging, encoding="utf-8")
        traces.append(tr)
        # diff vs 운영 03_Assets (build_asset_page, news 기반)
        try:
            before = build_asset_page(asset, period)
        except Exception as exc:
            before = f"(build_asset_page 실패: {exc})"
        d = difflib.unified_diff(
            before.splitlines(), staging.splitlines(),
            fromfile=f"BEFORE(운영)/{asset}", tofile=f"AFTER(staging)/{asset}",
            lineterm="", n=1)
        diffs.append("\n".join(d))

    # 미공급 자산 trace
    for asset in NOT_SUPPLIED:
        if asset in agg:
            traces.append({"asset": asset, "supplied": False,
                           "note": "정책상 미공급 (09 stance 미주입)",
                           "n_broker": agg[asset].get("n_broker", 0)})

    # 산출물 저장
    (STAGING_DIR / "p5_assets_trace.json").write_text(
        json.dumps({"period": period, "traces": traces}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (STAGING_DIR / "p5_assets_diff.md").write_text(
        f"# P5 03_Assets staging diff ({period})\n\n"
        "> 운영 wiki 미반영. staging 전용.\n\n"
        + "\n\n---\n\n".join(f"```diff\n{d}\n```" for d in diffs if d.strip()),
        encoding="utf-8")

    return {"period": period, "traces": traces,
            "staging_dir": str(STAGING_DIR), "n_pages": len(supplied)}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="P5 03_Assets staging (no operational write)")
    ap.add_argument("period")
    args = ap.parse_args()
    r = run_p5_staging(args.period)
    print(f"[P5 staging] {args.period} → {r['staging_dir']}")
    print(f"{'asset':10} {'src':16} {'stance':16} {'mkt':5} {'credit':6} {'us_kr':5}")
    for t in r["traces"]:
        if t.get("note") and "supplied" not in t and "stance" not in t:
            print(f"  {t['asset']:10} (skip: {t['note']})")
            continue
        if t.get("supplied") is False:
            print(f"  {t['asset']:10} 미공급 ({t.get('note','')})")
            continue
        print(f"  {t['asset']:10} {t['stance_source']:16} {str(t['stance'])[:14]:16} "
              f"{'Y' if t['market_snapshot_used'] else '-':5} "
              f"{t['credit_sleeve']:<6} {t['us_driven_kr']:<5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
