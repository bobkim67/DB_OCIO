"""Wiki Context Pack gateway (R9-B viewer).

`market_research.report.wiki_context_pack_builder.build_wiki_context_pack`
wrapper. read-only — LLM 호출 0, 운영 파일 변경 0.

`list_periods` 는 `market_research/data/claims/*.json` 를 스캔해 claim store
가 존재하는 monthly period 후보를 노출한다 (builder 가 monthly only).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# market_research 패키지 import. pymysql 등 무거운 의존성을 끌고 오지
# 않는 builder 만 직접 import.
from market_research.report.wiki_context_pack_builder import (
    DEFAULT_BODY_EXCERPT_CHARS,
    DEFAULT_MAX_PAGES,
    build_wiki_context_pack,
)


# api/services/wiki_context_pack_gateway.py → 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLAIMS_DIR = PROJECT_ROOT / "market_research" / "data" / "claims"

# YYYY-MM
PERIOD_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")


VALID_STAGES: frozenset[str] = frozenset({
    "market_debate", "fund_comment", "quarterly_debate", "admin_preview",
})


def validate_period_key(period: str) -> str:
    if not period or not PERIOD_RE.fullmatch(period):
        raise ValueError(
            f"invalid period_key {period!r}: expected YYYY-MM"
        )
    return period


def validate_stage(stage: str) -> str:
    if stage not in VALID_STAGES:
        raise ValueError(
            f"invalid stage {stage!r}: expected one of {sorted(VALID_STAGES)}"
        )
    return stage


def list_periods() -> list[dict[str, Any]]:
    """claim store 파일 목록을 통해 사용 가능한 period 후보 노출.

    production filename: ``{YYYY-MM}.json`` — replay variant (점 포함)는 제외.
    builder 는 monthly only.
    """
    if not CLAIMS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for fp in sorted(CLAIMS_DIR.glob("*.json")):
        stem = fp.stem  # "2026-04" or "2026-04.r9a4-replay"
        if "." in stem:
            continue
        if not PERIOD_RE.fullmatch(stem):
            continue
        claim_count: int | None = None
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                claims = data.get("claims")
                if isinstance(claims, list):
                    claim_count = len(claims)
        except (OSError, json.JSONDecodeError):
            claim_count = None
        out.append({
            "period_key": stem,
            "claim_store_exists": True,
            "claim_count": claim_count,
        })
    # 최신 우선
    out.sort(key=lambda x: x["period_key"], reverse=True)
    return out


def build_pack(
    *,
    period_key: str,
    stage: str,
    fund_code: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    body_excerpt_chars: int = DEFAULT_BODY_EXCERPT_CHARS,
    include_debate_memory: bool = False,
) -> dict[str, Any]:
    """builder thin wrapper. 입력 검증은 router 가 수행."""
    return build_wiki_context_pack(
        period_key=period_key,
        period_type="monthly",
        stage=stage,
        fund_code=fund_code,
        max_pages=max_pages,
        body_excerpt_chars=body_excerpt_chars,
        include_debate_memory=include_debate_memory,
    )


def extract_summary(pack: dict[str, Any]) -> dict[str, Any]:
    """source_trace 핵심 필드만 추려 DTO summary 로 변환."""
    st = pack.get("source_trace") or {}
    return {
        "wiki_pages_considered": int(st.get("wiki_pages_considered", 0)),
        "wiki_pages_selected": int(st.get("wiki_pages_selected", 0)),
        "selected_wiki_paths": list(st.get("selected_wiki_paths", []) or []),
        "selected_by_directory": dict(st.get("selected_by_directory", {}) or {}),
        "source_type_counts": dict(st.get("source_type_counts", {}) or {}),
        "selected_claim_ids": list(st.get("selected_claim_ids", []) or []),
        "selected_related_group_ids": list(
            st.get("selected_related_group_ids", []) or []
        ),
        "claim_store_selected_count": int(
            st.get("claim_store_selected_count", 0)
        ),
        "matched_wiki_claim_count": int(
            st.get("matched_wiki_claim_count", 0)
        ),
        "claim_store_to_wiki_join_rate": st.get(
            "claim_store_to_wiki_join_rate"
        ),
        "source_cutoff_violations": int(
            st.get("source_cutoff_violations", 0)
        ),
    }
