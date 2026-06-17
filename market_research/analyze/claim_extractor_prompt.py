# -*- coding: utf-8 -*-
"""R9-A.4 Commit 2 (C2-α) — operational claim extractor prompt template.

R9-A.1 manual pilot 의 prompt 본문을 운영 batch 용으로 분리. version 라벨
(`r9a.4-haiku`) + source (`daily_update_r9a4`) 만 manual pilot 과 다름.
prompt 본문은 R9-A.0 schema 와 R9-A.1 산출물을 기준으로 deterministic ID
일관성 보장.

LLM 호출 0 (이 모듈은 프롬프트 builder 만). 실 호출은 claim_extractor_runner.py.
"""
from __future__ import annotations

from typing import Any, Iterable

from market_research.analyze.claim_extractor import (
    ALLOWED_ASSET_CLASSES,
    ALLOWED_CLAIM_TYPES,
    ALLOWED_DIRECTIONS,
    ALLOWED_HORIZONS,
    ALLOWED_RELATIONS,
)
from market_research.core.asset_taxonomy import REGION_TAXONOMY
from market_research.wiki.taxonomy import TOPIC_TAXONOMY


# ──────────────────────────────────────────────────────────────────
# Versions
# ──────────────────────────────────────────────────────────────────

EXTRACTOR_VERSION = "r9a.4-haiku"
SOURCE = "daily_update_r9a4"
LLM_MODEL = "claude-haiku-4-5-20251001"   # D-8 — Haiku 고정
MAX_TOKENS = 16384                         # R9-A.1 manual pilot 와 동일
MAX_INPUT_EVIDENCE = 50                    # R9-A.1 default


# ──────────────────────────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────────────────────────

SYSTEM_PROMPT: str = (
    "당신은 OCIO 운용 리서치 보조 모델입니다. 주어진 뉴스 evidence 목록에서 "
    "운용 의사결정에 의미 있는 'canonical claim' 을 추출하는 임무입니다. "
    "출력은 반드시 JSON 배열만, 마크다운 / 설명 / 코드 블록 표기 없이 순수 "
    "JSON 으로 응답하세요. "
    "각 claim 은 운용 자산군 영향이 명확한 인과/해석/리스크/관점 단위여야 "
    "하며, 단순 사실 나열은 제외합니다."
)


# ──────────────────────────────────────────────────────────────────
# User prompt builder
# ──────────────────────────────────────────────────────────────────

def _format_evidence_lines(evidence_items: Iterable[dict],
                            max_items: int = MAX_INPUT_EVIDENCE) -> str:
    lines: list[str] = []
    for i, e in enumerate(evidence_items):
        if i >= max_items:
            break
        if not isinstance(e, dict):
            continue
        aid = e.get("article_id") or e.get("_article_id") or f"row_{i}"
        title = (e.get("title") or "").strip()[:120]
        source = e.get("source", "")
        date = e.get("date", "")
        topic = e.get("topic") or ""
        if not topic:
            topics = e.get("_classified_topics") or []
            if topics and isinstance(topics, list):
                first = topics[0]
                if isinstance(first, dict):
                    topic = first.get("topic", "")
                elif isinstance(first, str):
                    topic = first
        sal = e.get("_event_salience") or e.get("salience")
        sal_s = f" / sal={sal:.2f}" if isinstance(sal, (int, float)) else ""
        lines.append(
            f"- [{aid}] ({source} / {date} / {topic}{sal_s}) {title}"
        )
    return "\n".join(lines)


def build_extraction_prompt(
    period: str,
    evidence_items: list[dict],
    *,
    max_items: int = MAX_INPUT_EVIDENCE,
) -> dict[str, Any]:
    """Operational extraction prompt for R9-A.4 daily_update Step 2.7.

    Returns a dict with keys: 'system', 'user', 'model', 'max_tokens'.
    LLM 호출 0 — runner 가 dict 를 받아 호출.
    """
    asset_list = ", ".join(sorted(ALLOWED_ASSET_CLASSES))
    type_list = ", ".join(sorted(ALLOWED_CLAIM_TYPES))
    dir_list = ", ".join(sorted(ALLOWED_DIRECTIONS))
    hor_list = ", ".join(sorted(ALLOWED_HORIZONS))
    rel_list = ", ".join(sorted(ALLOWED_RELATIONS))
    region_list = ", ".join(REGION_TAXONOMY)
    sector_list = ", ".join(TOPIC_TAXONOMY)

    evidence_block = _format_evidence_lines(evidence_items, max_items=max_items)

    user_prompt = (
        f"## Period: {period}\n\n"
        "## 입력 evidence 목록 (article_id 순)\n"
        f"{evidence_block}\n\n"
        "## 추출 규칙\n"
        "1. 위 evidence 목록만을 근거로 인과/해석/리스크/관점 unit 으로 추출.\n"
        "2. 각 claim 은 supporting_evidence_ids 에 사용한 article_id 1개 이상 명시.\n"
        "3. 동일 사건의 alias 표현은 단일 claim 으로 통합 (예: '원자재/금'/'원자재(금)' "
        "→ '대체').\n"
        "3-1. 크레딧/HY/IG/회사채/사모신용(private credit)은 별도 자산군이 아니라 "
        "발행 지역 기준으로 **국내채권**(원화 회사채·은행채·여전채 등) 또는 "
        "**해외채권**(미국 HY/IG·글로벌 크레딧)으로 분류한다. 유동성/MMF/단기금리는 "
        "'유동성', 금·원자재·에너지·리츠·인프라는 '대체'.\n"
        "4. 자산군 영향이 모호하거나 운용 의사결정 보조가 안 되면 추출 X.\n"
        "5. 여러 자산군에 의미 있는 영향이 있으면 affected_assets 에 3개 이상 "
        "명시 (예: 금리 충격 → 국내채권+해외채권+주식+달러).\n"
        "6. claim_id 는 출력 X — 시스템에서 deterministic 하게 자동 부여.\n"
        "7. affected_assets 각 항목에 confidence(0~1)·role(primary/secondary) 부여. "
        "role=primary 는 정확히 1개, primary_asset 은 그 자산과 동일하게 명시.\n"
        "8. regions(≤2)·sectors(≤3) 는 claim 이 영향을 주는 시장 지역·주제. region 은 "
        "'영향받는 시장' 기준(발행 매체 아님).\n\n"
        "## 출력 schema (JSON 배열만, 그 외 텍스트 금지)\n"
        "[\n"
        "  {\n"
        '    "claim_text": "한 줄 요약 (≤180자)",\n'
        '    "claim_type": "...",\n'
        '    "affected_assets": [{"asset_class": "...", "direction": "...", '
        '"confidence": 0.0~1.0, "role": "primary|secondary"}],\n'
        '    "primary_asset": "affected_assets 의 role=primary 자산",\n'
        '    "regions": ["..."], "sectors": ["..."],\n'
        '    "causal_chain": [{"source": "...", "target": "...", "relation": "..."}],\n'
        '    "direction": "...",\n'
        '    "horizon": "...",\n'
        '    "confidence": 0.0~1.0,\n'
        '    "salience": 0.0~1.0,\n'
        '    "supporting_evidence_ids": ["article_id", ...],\n'
        '    "counter_evidence_ids": []\n'
        "  },\n"
        "  ...\n"
        "]\n\n"
        "## Taxonomy 제약 (반드시 아래 값만 사용)\n"
        f"- asset_class: {asset_list}\n"
        f"- claim_type:  {type_list}\n"
        f"- direction:   {dir_list}\n"
        f"- horizon:     {hor_list}\n"
        f"- relation:    {rel_list}\n"
        f"- region:      {region_list}\n"
        f"- sector:      {sector_list}\n"
    )

    return {
        "system": SYSTEM_PROMPT,
        "user": user_prompt,
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS,
    }
