# -*- coding: utf-8 -*-
"""Research claim aggregator — 자산군 × 테마 × 기간 재종합 (P3).

wiki_from_naver_research P3. {month}.research.json 의 원자 claim 을 자산군별로 묶어
consensus / dissent / risk 구조로 집계한다. P4(09_Research_Synthesis)·게이트 리포트
입력. LLM 0 — 순수 집계.

D5 오염 방지: consensus vote 는 **broker(naver_research) 만**. monygeek 은 vote 에서
제외하고 dissent/tail-risk 레이어로만 수집.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from market_research.analyze.claim_extractor import ALLOWED_ASSET_CLASSES

BASE_DIR = Path(__file__).resolve().parent.parent
CLAIMS_DIR = BASE_DIR / 'data' / 'claims'

_STANCE_ORDER = ("bullish", "neutral", "bearish", "mixed")


def load_research_claims(month: str) -> list[dict]:
    """{month}.research.json 의 claims 로드. 없으면 []."""
    p = CLAIMS_DIR / f"{month}.research.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return []
    return data.get("claims", [])


def _base_primary(claim: dict) -> str | None:
    """canonical 8-class primary. LLM primary_asset 세부업종 괄호/오타는
    하드검증된 affected_assets[].asset_class(role=primary 우선)로 collapse."""
    aa = claim.get("affected_assets") or []
    for a in aa:
        if isinstance(a, dict) and a.get("role") == "primary":
            ac = a.get("asset_class")
            if ac in ALLOWED_ASSET_CLASSES:
                return ac
    pa = claim.get("primary_asset")
    if pa in ALLOWED_ASSET_CLASSES:
        return pa
    for a in aa:
        ac = a.get("asset_class") if isinstance(a, dict) else a
        if ac in ALLOWED_ASSET_CLASSES:
            return ac
    return None


def _primary(claim: dict) -> str | None:
    """research routing 정책 적용 primary (사용자 D4 결정, 2026-06-15):
    - 크립토(sectors='크립토') → '기타' (OCIO 8자산 밖, 채권/현금성 오염 방지).
    - 크레딧(HY/신용) → region 으로 채권 슬리브 분리: KR→국내채권, 그 외→해외채권
      (크레딧 = 미국 HY/회사채 자산군이라 국내/해외 회사채로 귀속).
    - 현금성: 크립토 제거 후 잔여(단기금리/유동성)만 유지.
    """
    base = _base_primary(claim)
    # 크립토 = 기타 (base 무관, 우선 적용)
    if "크립토" in (claim.get("sectors") or []):
        return "기타"
    # 크레딧 → 국내/해외 채권 슬리브
    if base == "크레딧":
        rg = claim.get("regions") or []
        return "국내채권" if "KR" in rg else "해외채권"
    return base


def aggregate_by_asset(claims: list[dict]) -> dict[str, dict[str, Any]]:
    """primary_asset 기준 자산군별 집계.

    각 자산군:
      broker_claims / monygeek_claims, vote_distribution(broker only),
      consensus_stance / consensus_strength, by_horizon, by_theme,
      risk_factors, dissent(monygeek + broker 소수 stance).
    """
    by_asset: dict[str, list[dict]] = defaultdict(list)
    for c in claims:
        pa = _primary(c)
        if pa:
            by_asset[pa].append(c)

    out: dict[str, dict[str, Any]] = {}
    for asset, cs in by_asset.items():
        broker = [c for c in cs if c.get("source_type") != "monygeek"]
        monygeek = [c for c in cs if c.get("source_type") == "monygeek"]

        # D5 — vote 는 broker 만
        vote = Counter(c.get("stance") for c in broker if c.get("stance"))
        consensus_stance = None
        strength = 0.0
        if vote:
            consensus_stance = max(_STANCE_ORDER, key=lambda s: (vote.get(s, 0), s == "neutral"))
            consensus_stance = vote.most_common(1)[0][0]
            strength = round(vote.most_common(1)[0][1] / max(1, sum(vote.values())), 3)

        by_horizon: dict[str, list[dict]] = defaultdict(list)
        for c in cs:
            by_horizon[c.get("horizon") or "unknown"].append(c)
        by_theme: Counter = Counter()
        for c in cs:
            for s in (c.get("sectors") or []):
                by_theme[s] += 1

        risk_factors = [c.get("risk_factor") for c in cs
                        if (c.get("risk_factor") or "").strip()]

        # dissent: monygeek 전체 + broker 중 consensus 와 다른 stance
        dissent = list(monygeek)
        if consensus_stance:
            dissent += [c for c in broker if c.get("stance") not in (consensus_stance, None)]

        out[asset] = {
            "asset_class": asset,
            "n_claims": len(cs),
            "n_broker": len(broker),
            "n_monygeek": len(monygeek),
            "vote_distribution": dict(vote),
            "consensus_stance": consensus_stance,
            "consensus_strength": strength,
            "by_horizon": {k: len(v) for k, v in by_horizon.items()},
            "by_theme": dict(by_theme.most_common(5)),
            "risk_factors": risk_factors[:8],
            "broker_claims": broker,
            "monygeek_claims": monygeek,
            "dissent": dissent,
        }
    return out


def distribution_report(agg: dict[str, dict[str, Any]],
                        *, min_claims: int = 3, max_claims: int = 40) -> dict[str, Any]:
    """P4 GO 체크용 분포 리포트 — 자산군별 claim 수 부족/과다 경고."""
    rows = []
    warnings = []
    for asset, a in sorted(agg.items(), key=lambda kv: -kv[1]["n_claims"]):
        rows.append({
            "asset_class": asset, "n_claims": a["n_claims"],
            "broker": a["n_broker"], "monygeek": a["n_monygeek"],
            "consensus": a["consensus_stance"], "strength": a["consensus_strength"],
            "vote": a["vote_distribution"],
        })
        if a["n_claims"] < min_claims:
            warnings.append(f"{asset}: claim 부족 ({a['n_claims']} < {min_claims})")
        if a["n_claims"] > max_claims:
            warnings.append(f"{asset}: claim 과다 ({a['n_claims']} > {max_claims})")
        if a["n_broker"] == 0:
            warnings.append(f"{asset}: broker claim 0 (consensus 산정 불가, monygeek-only)")
    return {"rows": rows, "warnings": warnings,
            "n_assets": len(agg), "total_claims": sum(a["n_claims"] for a in agg.values())}
