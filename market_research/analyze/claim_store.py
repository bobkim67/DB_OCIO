# -*- coding: utf-8 -*-
"""R9-A.2 — Canonical claim store under data/claims/{YYYY-MM}.json.

Phase 2 boundary:
- LLM 호출 0
- claim 은 R9-A.0 validator 를 반드시 통과한 것만 저장
- daily_update / debate / fund_comment / asset_movement_anchor 미수정
- read-side consumer 부재 (R9-A.3 까지 dormant)

Public API:
    save_claims_canonical(period, claims, source, extractor_version,
                          promotion_result=None) -> Path
    load_claims_canonical(period) -> dict
    merge_claims(existing, incoming, policy="prefer_higher_confidence")
        -> list[dict]

Storage layout:
    market_research/data/claims/{YYYY-MM}.json   ← canonical store (single JSON)
    market_research/data/claims/_promotion_quality.jsonl  ← promotion ledger
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from market_research.analyze.claim_extractor import (
    SCHEMA_VERSION,
    serialize_claim,
    validate_claim,
)


BASE_DIR = Path(__file__).resolve().parent.parent
CLAIMS_DATA_DIR = BASE_DIR / "data" / "claims"
PROMOTION_LEDGER_PATH = CLAIMS_DATA_DIR / "_promotion_quality.jsonl"


# ──────────────────────────────────────────────────────────────────
# Internal — paths / stats
# ──────────────────────────────────────────────────────────────────

def _canonical_path(period: str) -> Path:
    if not isinstance(period, str) or not period:
        raise ValueError(f"period must be non-empty string, got {period!r}")
    if "/" in period or "\\" in period or ".." in period:
        raise ValueError(f"unsafe period: {period!r}")
    CLAIMS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return CLAIMS_DATA_DIR / f"{period}.json"


def _compute_stats(claims: list[dict],
                   promotion_result: dict | None) -> dict:
    """summary stats — promotion_result 가 있으면 반영."""
    total = len(claims)
    by_asset: Counter = Counter()
    by_horizon: Counter = Counter()
    by_type: Counter = Counter()
    for c in claims:
        for a in c.get("affected_assets", []) or []:
            ac = a.get("asset_class") if isinstance(a, dict) else a
            if isinstance(ac, str) and ac:
                by_asset[ac] += 1
        h = c.get("horizon")
        if isinstance(h, str):
            by_horizon[h] += 1
        ct = c.get("claim_type")
        if isinstance(ct, str):
            by_type[ct] += 1

    promoted = 0
    skipped = 0
    if isinstance(promotion_result, dict):
        promoted = int(promotion_result.get("promoted_count", 0) or 0)
        skipped = int(promotion_result.get("skipped_count", 0) or 0)

    return {
        "total": total,
        "promoted": promoted,
        "skipped": skipped,
        "by_asset_class": dict(sorted(by_asset.items())),
        "by_horizon": dict(sorted(by_horizon.items())),
        "by_claim_type": dict(sorted(by_type.items())),
    }


# ──────────────────────────────────────────────────────────────────
# save / load
# ──────────────────────────────────────────────────────────────────

def save_claims_canonical(period: str,
                          claims: list[dict],
                          source: str,
                          extractor_version: str,
                          promotion_result: dict | None = None) -> Path:
    """Validate-then-save canonical claim store for a period.

    Raises:
        ValueError if any claim fails R9-A.0 validator.
    """
    if not isinstance(claims, list):
        raise TypeError(f"claims must be list, got {type(claims).__name__}")

    serialized: list[dict] = []
    for i, c in enumerate(claims):
        v = validate_claim(c)
        if not v["valid"]:
            raise ValueError(
                f"claim[{i}] failed validation before canonical save: "
                f"{v['errors']}")
        serialized.append(serialize_claim(c))

    payload = {
        "schema_version": SCHEMA_VERSION,
        "period": period,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "extractor_version": extractor_version,
        "claims": serialized,
        "stats": _compute_stats(serialized, promotion_result),
    }

    out = _canonical_path(period)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    return out


def load_claims_canonical(period: str) -> dict:
    """Load canonical store. Missing file → empty dict."""
    p = _canonical_path(period)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


# ──────────────────────────────────────────────────────────────────
# merge
# ──────────────────────────────────────────────────────────────────

def merge_claims(existing: list[dict] | None,
                 incoming: list[dict] | None,
                 policy: str = "prefer_higher_confidence") -> list[dict]:
    """Merge two claim lists by claim_id.

    Policies:
        - "prefer_higher_confidence": on conflict, keep claim with higher
          confidence (ties → keep existing).
        - "prefer_existing": existing wins.
        - "prefer_incoming": incoming wins.

    Stable order: existing order first (preserved or updated in place),
    then new incoming claim_ids appended.
    """
    if policy not in ("prefer_higher_confidence",
                      "prefer_existing",
                      "prefer_incoming"):
        raise ValueError(f"unknown merge policy: {policy!r}")

    ex_list = list(existing or [])
    in_list = list(incoming or [])

    by_id: dict[str, dict] = {}
    order: list[str] = []
    for c in ex_list:
        cid = c.get("claim_id")
        if not isinstance(cid, str) or not cid:
            continue
        if cid not in by_id:
            order.append(cid)
        by_id[cid] = dict(c)

    for c in in_list:
        cid = c.get("claim_id")
        if not isinstance(cid, str) or not cid:
            continue
        if cid not in by_id:
            order.append(cid)
            by_id[cid] = dict(c)
            continue
        # conflict
        if policy == "prefer_existing":
            continue
        if policy == "prefer_incoming":
            by_id[cid] = dict(c)
            continue
        # prefer_higher_confidence
        try:
            existing_conf = float(by_id[cid].get("confidence", 0.0))
        except (TypeError, ValueError):
            existing_conf = 0.0
        try:
            incoming_conf = float(c.get("confidence", 0.0))
        except (TypeError, ValueError):
            incoming_conf = 0.0
        if incoming_conf > existing_conf:
            by_id[cid] = dict(c)

    return [by_id[cid] for cid in order]


# ──────────────────────────────────────────────────────────────────
# promotion ledger
# ──────────────────────────────────────────────────────────────────

def append_promotion_ledger(row: dict) -> Path:
    """Append a single promotion run row to _promotion_quality.jsonl."""
    if not isinstance(row, dict):
        raise TypeError("ledger row must be dict")
    CLAIMS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with PROMOTION_LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
        f.write("\n")
    return PROMOTION_LEDGER_PATH
