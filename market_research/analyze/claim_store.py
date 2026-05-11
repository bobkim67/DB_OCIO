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

_TARGET_SUFFIX_RE = __import__("re").compile(r"^[A-Za-z0-9_-]+$")


def _canonical_path(period: str, target_suffix: str | None = None) -> Path:
    if not isinstance(period, str) or not period:
        raise ValueError(f"period must be non-empty string, got {period!r}")
    if "/" in period or "\\" in period or ".." in period:
        raise ValueError(f"unsafe period: {period!r}")
    if target_suffix is not None:
        if not isinstance(target_suffix, str) or not target_suffix:
            raise ValueError(
                f"target_suffix must be non-empty string, got {target_suffix!r}")
        if not _TARGET_SUFFIX_RE.match(target_suffix):
            raise ValueError(
                f"target_suffix must be alphanumeric / underscore / hyphen, "
                f"got {target_suffix!r}")
    CLAIMS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    name = (
        f"{period}.{target_suffix}.json" if target_suffix
        else f"{period}.json"
    )
    return CLAIMS_DATA_DIR / name


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
                          promotion_result: dict | None = None,
                          target_suffix: str | None = None) -> Path:
    """Validate-then-save canonical claim store for a period.

    Parameters
    ----------
    target_suffix : optional alphanumeric/underscore/hyphen suffix. None 이면
        운영 file `{period}.json` 에 저장 (R9-A.2 기존 동작). Non-None 이면
        `{period}.{suffix}.json` 분리 저장 (R9-A.4 Commit 4 / 9.3 controlled
        write smoke 용도).

    Raises:
        ValueError if any claim fails R9-A.0 validator OR target_suffix
        포맷이 비정상.
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
        "target_suffix": target_suffix,
        "claims": serialized,
        "stats": _compute_stats(serialized, promotion_result),
    }

    out = _canonical_path(period, target_suffix=target_suffix)
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

def select_promoted_claims_for_period(
    period: str,
    asset_class: str | None = None,
    fund_code: str | None = None,
    max_claims: int = 8,
) -> list[dict]:
    """Read-side: load canonical store and return promotion-passing claims.

    R9-A.3 read-only helper. canonical store / wiki / ledger 어디에도 write 0.
    fund_code 는 R9-A 후행 (R9-A.4+) 매핑용 reserved — 현재는 affected_assets
    교집합 필터만 사용한다.

    Filtering / ranking:
      1. period 의 canonical store 로드 (없으면 [])
      2. R9-A.2 promotion rule (Rule A 또는 Rule B) 통과만 유지
      3. asset_class 가 주어지면 affected_assets 에 포함된 claim 만
      4. confidence × salience 내림차순, causal_chain 길이 내림차순으로 정렬
      5. 상위 max_claims 만 반환

    절대 raise 없음 — store 결손 / 매칭 0 / 잘못된 schema 모두 빈 list 로 graceful.
    """
    try:
        store = load_claims_canonical(period)
    except Exception:
        return []
    claims = store.get("claims", []) if isinstance(store, dict) else []
    if not isinstance(claims, list) or not claims:
        return []

    # Lazy import 로 wiki.claim_pages 와의 circular dep 회피.
    try:
        from market_research.wiki.claim_pages import _meets_rule_a, _meets_rule_b
    except Exception:
        return []

    promoted = [c for c in claims
                if isinstance(c, dict)
                and (_meets_rule_a(c) or _meets_rule_b(c))]

    if asset_class:
        target = asset_class

        def _matches(c: dict) -> bool:
            for a in c.get("affected_assets", []) or []:
                ac = a.get("asset_class") if isinstance(a, dict) else a
                if ac == target:
                    return True
            return False

        promoted = [c for c in promoted if _matches(c)]

    def _sort_key(c: dict):
        try:
            cf = float(c.get("confidence", 0.0))
            sal = float(c.get("salience", 0.0))
        except (TypeError, ValueError):
            cf, sal = 0.0, 0.0
        cc_len = len(c.get("causal_chain") or [])
        return (-(cf * sal), -cc_len)

    promoted.sort(key=_sort_key)
    try:
        cap = int(max_claims) if max_claims is not None else 8
    except (TypeError, ValueError):
        cap = 8
    return promoted[: max(0, cap)]


def claim_wiki_path(claim_id: str | None) -> str | None:
    """`claim:{period}:{hash10}` → `08_Claims/{period}_claim_{hash10}.md`.

    Read-only path 추정 — 파일 존재 여부는 별도 확인 책임. R9-A.3 trace
    surface 에서 사용.
    """
    if not isinstance(claim_id, str) or not claim_id.startswith("claim:"):
        return None
    parts = claim_id.split(":")
    if len(parts) != 3:
        return None
    _, period, h = parts
    if not period or not h:
        return None
    return f"08_Claims/{period}_claim_{h}.md"


def _ledger_path(target_suffix: str | None = None) -> Path:
    """ledger path resolver. target_suffix 가 주어지면 운영 ledger 와 분리.

    `target_suffix=None` → `_promotion_quality.jsonl` (운영, R9-A.2 동작)
    `target_suffix='r9a4-replay'` → `_promotion_quality.r9a4-replay.jsonl`
    """
    if target_suffix is None:
        return PROMOTION_LEDGER_PATH
    if not isinstance(target_suffix, str) or not target_suffix:
        raise ValueError(
            f"target_suffix must be non-empty string, got {target_suffix!r}")
    if not _TARGET_SUFFIX_RE.match(target_suffix):
        raise ValueError(
            f"target_suffix must be alphanumeric / underscore / hyphen, "
            f"got {target_suffix!r}")
    return CLAIMS_DATA_DIR / f"_promotion_quality.{target_suffix}.jsonl"


def append_promotion_ledger(row: dict,
                            target_suffix: str | None = None) -> Path:
    """Append a single promotion run row to ledger jsonl.

    target_suffix : R9-A.4 Commit 4.1 — replay/smoke 산출물을 운영 ledger 와
        분리. None 이면 운영 `_promotion_quality.jsonl` 에 append.
    """
    if not isinstance(row, dict):
        raise TypeError("ledger row must be dict")
    CLAIMS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _ledger_path(target_suffix)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
        f.write("\n")
    return path
