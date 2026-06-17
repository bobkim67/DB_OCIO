# -*- coding: utf-8 -*-
"""R9-A.0 — Normalized claim schema, deterministic ID, validator, JSONL helpers.

LLM 호출 0. Phase 0 범위는 "데이터 형상의 단일 source-of-truth" 만 정의한다.
실제 LLM extractor 는 Phase 1 (claim_extractor_pilot) 에서 별도 GO 후 추가.

R9-A.8/A.10/A.12 — Canonical claim identity 재설계 (LLM 0).

R9-A.8 layered identity:
    _normalize_claim_text  (NFKC + ws + lower + trailing/multi punct squash)
    _build_evidence_set_hash  (sorted unique md5[:10])
    _build_content_signature  (norm_text + assets + dir/hor/type, md5[:12])
    compute_claim_id          (period + ev_hash + content_sig, md5[:10])

R9-A.10 fallback: normalize_claim() 에서 source_evidence_ids 비어있고
supporting_evidence_ids 있으면 copy (운영 prompt schema 누락 보정, LLM 0).

R9-A.12 group_id 재정의 (text-based 폐기) →
R9-A.14 G1 채택 (taxonomy enum 도 제거):
    _build_canonical_group_signature
        (evidence_set_hash + assets, md5[:12])
        ← claim_text/normalized_text 미포함 (R9-A.12)
        ← direction/horizon/claim_type 도 미포함 (R9-A.14, G1 정의)
    compute_canonical_group_id
        (period + group_signature → md5[:10])
        ← Haiku wording 및 enum variance 와 무관
        ← 같은 evidence + 같은 assets 면 동일 group

원칙 (사용자 design):
    - LLM claim 은 후보 생성, group_id 가 운영 identity
    - claim_text 는 display only
    - 과소병합 > 과대병합 (다른 evidence set 이면 다른 group)
    - 1차 deterministic, 2차 entity/topic/embedding 은 별 단계

format 은 backward-compat: claim_id "claim:{period}:{md5[:10]}", group_id
"group:{period}:{md5[:10]}". 다운스트림 `_hash10_of`, `_wiki_page_filename`,
`[claim:hash10]` anchor (debate / comment_engine / evidence_trace) 모두 무영향.

Public API:
    SCHEMA_VERSION, EXTRACTOR_VERSION
    ALLOWED_ASSET_CLASSES, ALLOWED_CLAIM_TYPES, ALLOWED_DIRECTIONS,
    ALLOWED_HORIZONS, ALLOWED_RELATIONS, ALLOWED_EXTRACTION_METHODS
    REQUIRED_FIELDS, OPTIONAL_FIELDS

    compute_claim_id(period, claim_text, source_evidence_ids,
                     affected_assets, *, direction, horizon, claim_type) -> str
    compute_canonical_group_id(period, claim_text, affected_assets, *,
                               source_evidence_ids, direction, horizon,
                               claim_type) -> str
    normalize_claim(raw: dict) -> dict
    validate_claim(claim: dict) -> dict
    serialize_claim(claim: dict) -> dict
    write_claims_jsonl(path, claims) -> Path
    read_claims_jsonl(path) -> list[dict]
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────────
# Versions
# ──────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0.0"
EXTRACTOR_VERSION = "r9a.0"


# ──────────────────────────────────────────────────────────────────
# Allowed taxonomies
# ──────────────────────────────────────────────────────────────────

# 운영 7 자산군 (2026-06-17): 크레딧 제거(→region 따라 국내/해외채권),
# 현금성→유동성, 원자재금→대체. asset_movement_anchor._ASSET_TO_INDICATOR 와 동기.
ALLOWED_ASSET_CLASSES: frozenset[str] = frozenset({
    "국내주식", "해외주식", "국내채권", "해외채권",
    "유동성", "환율(FX)", "대체",
})

ALLOWED_CLAIM_TYPES: frozenset[str] = frozenset({
    "event_to_macro",
    "macro_to_asset",
    "asset_to_fund",
    "outlook_view",
    "risk",
    "counterpoint",
})

ALLOWED_DIRECTIONS: frozenset[str] = frozenset({
    "positive", "negative", "neutral", "mixed", "unknown",
})

ALLOWED_HORIZONS: frozenset[str] = frozenset({
    "short", "medium", "long", "unknown",
})

ALLOWED_RELATIONS: frozenset[str] = frozenset({
    "raises", "lowers",
    "supports", "pressures",
    "offsets", "hedges",
    "weakens", "strengthens",
    "increases_volatility", "decreases_volatility",
})

ALLOWED_EXTRACTION_METHODS: frozenset[str] = frozenset({
    "llm", "rule", "manual", "fallback",
})

# ── Research claim 전용 (wiki_from_naver_research P0) ──
# stance = 리서치 전망 어조(해당 자산 보유 관점), direction = 자산가격 영향 방향.
# 둘은 독립 (금리상승 전망 → 채권 stance=bearish 이나 금리 direction=positive). 일치강제 X.
ALLOWED_STANCES: frozenset[str] = frozenset({
    "bullish", "neutral", "bearish", "mixed",
})

# research claim 출처 레인. 기존 운영 claim 은 source_type 미보유 → soft 검증이라 무영향.
ALLOWED_SOURCE_TYPES: frozenset[str] = frozenset({
    "naver_research", "monygeek", "news",
})

REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "claim_id",
    "period",
    "source_evidence_ids",
    "claim_text",
    "claim_type",
    "affected_assets",
    "causal_chain",
    "direction",
    "horizon",
    "confidence",
    "salience",
    "supporting_evidence_ids",
    "counter_evidence_ids",
    "linked_wiki_pages",
    "extractor_version",
    "extraction_method",
    "warnings",
)

# R9-A.8 — optional fields. REQUIRED_FIELDS 에 포함하지 않아 기존 운영 데이터
# (R9-A.1 manual pilot 22 claim 등) 가 validate_claim 에서 미존재로 fail 되지
# 않는다. normalize_claim() 통과 시 자동 부착되지만, 운영 파일을 그대로 read
# 만 하면 md5 변경 0.
#
# R9-B.6C — `promotion_rule` 추가. Rule A/B 자연 통과는 read-side
# (`select_promoted_claims_for_period`) 가 룰 평가로 surface 하지만, Rule C
# (force) 는 룰 평가만으로 surface 되지 않으므로 canonical store metadata
# 에 명시. 값: "A" | "B" | "C" (대소문자 무관). 미설정 → 룰 평가만.
OPTIONAL_FIELDS: tuple[str, ...] = (
    "canonical_group_id",
    "promotion_rule",
    # Taxonomy v2 wiring — region×sector. REQUIRED 승격 금지: 기존 운영 claim
    # 이 미존재로 validate fail 하지 않고, serialize_claim 이 `if k in claim`
    # 으로만 dump → 신규필드 없는 기존 claim md5 불변. canonical_group_id /
    # claim_id 계산 입력에도 미포함 → group identity 무영향.
    "primary_asset",
    "regions",
    "sectors",
)

# Research claim 전용 OPTIONAL 필드 (wiki_from_naver_research P0). OPTIONAL_FIELDS 와
# 동일 규약: REQUIRED 승격 금지 → 기존 운영 claim(미보유)은 serialize 시 `if k in claim`
# 으로 dump 제외되어 md5 불변. theme 은 신설 안 함 (기존 `sectors` 재사용).
#   source_type   : "naver_research" | "monygeek" | "news"  (출처 레인)
#   broker_author : 증권사명 또는 블로거(author)            (귀속)
#   stance        : bullish/neutral/bearish/mixed           (전망 어조, direction 과 독립)
#   view          : 한 줄 view title (claim_text 와 별도)
#   rationale_text: 장문 논거 (causal_chain 보완)
#   risk_factor   : 리스크 서술 (str)
#   evidence_text : 인용 원문 발췌
RESEARCH_OPTIONAL_FIELDS: tuple[str, ...] = (
    "source_type",
    "broker_author",
    "stance",
    "view",
    "rationale_text",
    "risk_factor",
    "evidence_text",
)

# serialize_claim / 호환 surface 가 단일 OPTIONAL 집합을 보도록 합본 (순서 보존).
OPTIONAL_FIELDS = OPTIONAL_FIELDS + RESEARCH_OPTIONAL_FIELDS

# Threshold heuristics (validator soft warnings)
CLAIM_TEXT_MIN_LEN = 8
CLAIM_TEXT_MAX_LEN = 500

# period regex: YYYY-MM or YYYY-Q[1-4]
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2]|Q[1-4])$")


# ──────────────────────────────────────────────────────────────────
# Deterministic claim_id
# ──────────────────────────────────────────────────────────────────

# R9-A.8 — normalize_claim_text 강화 regex.
# trailing punctuation: 한·영·일 마침표 / 물음표 / 느낌표 / whitespace.
# multi punctuation squash: 연속 .!? → 단일.
_TRAILING_PUNCT_RE = re.compile(r"[.!?。!?\s]+$")
_MULTI_PUNCT_RE = re.compile(r"([.!?。!?])\1+")


def _normalize_claim_text(text: Any) -> str:
    """ID 산출의 deterministic 입력 — wording variance 흡수 (R9-A.8).

    파이프라인:
        1. NFKC unicode 정규화
        2. trim + 연속 whitespace 단일화
        3. lower (영문 대소문자 통일)
        4. 연속 punctuation squash ("..." → ".", "?!?" → "?")
        5. trailing punctuation 제거 ("문장.", "문장!" → "문장")

    주의: 한국어 명사 어미/조사 변화는 normalize 하지 않는다 (다른 의미가
    같은 signature 되는 위험 차단 — 워크오더 §1 "너무 공격적으로 normalize
    하지 말 것").
    """
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    s = unicodedata.normalize("NFKC", text).strip()
    s = " ".join(s.split())            # whitespace squash
    s = s.lower()                       # 영문 소문자 (한글 무영향)
    s = _MULTI_PUNCT_RE.sub(r"\1", s)   # ".." → "."
    s = _TRAILING_PUNCT_RE.sub("", s)   # trailing punctuation / ws strip
    return s


def _extract_asset_class_strings(affected_assets: Any) -> list[str]:
    """affected_assets 입력에서 asset_class 문자열만 sorted dedupe 추출."""
    out: set[str] = set()
    if not isinstance(affected_assets, list):
        return []
    for a in affected_assets:
        if isinstance(a, dict):
            ac = a.get("asset_class")
            if isinstance(ac, str) and ac:
                out.add(ac)
        elif isinstance(a, str) and a:
            out.add(a)
    return sorted(out)


def _build_evidence_set_hash(evidence_ids: list[Any] | None) -> str:
    """Sorted+unique evidence_ids 의 md5[:10]. R9-A.8 layered identity.

    empty evidence set 은 sentinel 문자열 "empty" 로 통일 — distinct claim
    들이 evidence 부재만으로 같은 hash 가 되는 것을 방지.
    """
    if not isinstance(evidence_ids, list):
        return "empty"
    sorted_unique = sorted({str(e) for e in evidence_ids if e})
    if not sorted_unique:
        return "empty"
    blob = "|".join(sorted_unique).encode("utf-8")
    return hashlib.md5(blob).hexdigest()[:10]


def _build_content_signature(
    claim_text: Any,
    affected_assets: Any,
    *,
    direction: Any = "unknown",
    horizon: Any = "unknown",
    claim_type: Any = "outlook_view",
) -> str:
    """R9-A.8 content signature (LLM wording variance 흡수 + semantics).

    포함 재료:
        - normalize_claim_text(claim_text)
        - sorted affected_assets (asset_class strings)
        - direction / horizon / claim_type (taxonomy enum 들)

    제외 재료 (LLM 흔들림이 큼):
        - evidence_ids (별도 evidence_set_hash 로 분리)
        - causal_chain 본문 (source/target/relation 자체는 안정적이지만
          natural language → wording variance 큼)
        - rationale / summary 등 장문 보조 필드
    """
    payload = {
        "text": _normalize_claim_text(claim_text or ""),
        "assets": _extract_asset_class_strings(affected_assets),
        "direction": str(direction or "unknown"),
        "horizon": str(horizon or "unknown"),
        "claim_type": str(claim_type or "outlook_view"),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)\
        .encode("utf-8")
    return hashlib.md5(blob).hexdigest()[:12]


def compute_claim_id(
    period: str,
    claim_text: str,
    source_evidence_ids: list[str] | None,
    affected_assets: list[Any] | None,
    *,
    direction: Any = "unknown",
    horizon: Any = "unknown",
    claim_type: Any = "outlook_view",
) -> str:
    """Deterministic claim_id (R9-A.8 layered identity).

    layered: period + evidence_set_hash + content_signature → md5[:10].

    backward compat: 기존 4-positional 호출 (R9-A.0~A.7) 동일 시그니처.
    direction/horizon/claim_type 은 kwargs 로만 노출, 미지정 시 unknown/
    outlook_view default. 출력 format `claim:{period}:{md5_hex10}` 동일.

    같은 (period, sorted source_evidence_ids, normalize(claim_text), sorted
    asset_class, direction, horizon, claim_type) 입력 → 같은 ID.
    """
    p = period if isinstance(period, str) and period else "unknown"
    ev_hash = _build_evidence_set_hash(source_evidence_ids)
    sig = _build_content_signature(
        claim_text, affected_assets,
        direction=direction, horizon=horizon, claim_type=claim_type,
    )
    payload = f"{p}|{ev_hash}|{sig}"
    h = hashlib.md5(payload.encode("utf-8")).hexdigest()[:10]
    return f"claim:{p}:{h}"


def _build_canonical_group_signature(
    source_evidence_ids: list[Any] | None,
    affected_assets: Any,
    *,
    direction: Any = "unknown",   # R9-A.14 — kwarg 받지만 hash 입력 X (호환)
    horizon: Any = "unknown",     # R9-A.14 — kwarg 받지만 hash 입력 X (호환)
    claim_type: Any = "outlook_view",  # R9-A.14 — 동일
) -> str:
    """R9-A.12/A.14 canonical group signature — G1 정의 (evset + assets).

    R9-A.13 sensitivity matrix (LLM 0, R9-A.11 raw 73 rows 재분석) 결과:
        G8 (current) mean overlap 0.0481 ↔ G1 (evset+assets) 0.0737
        repeat≥2: G8 7 → G1 12, within_dup: 둘 다 0.00%
        split 주범: claim_type 33% / horizon 25% / direction 8%
        → enum variance 가 group 을 쪼개는 주범 → group_id 에서 제거.

    R9-A.14 — G8 → G1 채택:
        포함 재료:
            - evidence_set_hash (sorted+unique evidence_ids → md5[:10])
            - sorted affected_assets (asset_class strings)
        제외 재료 (이전 R9-A.12 G8 에서 제거):
            - direction / horizon / claim_type (Haiku enum variance 회피)
            - claim_text / normalized_text (R9-A.12 부터 이미 제외)
            - causal_chain natural language 부분

    direction/horizon/claim_type 은 compute_canonical_group_id 의 kwarg 로
    여전히 받지만 (시그니처 backward compat) hash 입력에 미사용 — diagnostic
    field 로만 유지 (운영 monitoring 에서 enum 분포 추적 가능).
    """
    payload = {
        "evset": _build_evidence_set_hash(source_evidence_ids),
        "assets": _extract_asset_class_strings(affected_assets),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)\
        .encode("utf-8")
    return hashlib.md5(blob).hexdigest()[:12]


def compute_canonical_group_id(
    period: str,
    claim_text: str,           # backward compat (사용 X, signature 보존)
    affected_assets: list[Any] | None,
    *,
    source_evidence_ids: list[Any] | None = None,
    direction: Any = "unknown",       # R9-A.14 — kwarg 보존, hash 입력 X
    horizon: Any = "unknown",         # R9-A.14 — kwarg 보존, hash 입력 X
    claim_type: Any = "outlook_view",  # R9-A.14 — kwarg 보존, hash 입력 X
) -> str:
    """Canonical group_id (R9-A.12 → R9-A.14 G1) — evidence + assets only.

    layered: period + canonical_group_signature → md5[:10]. signature 는
    R9-A.14 부터 **evidence_set_hash + sorted affected_assets** 만.

    R9-A.13 sensitivity matrix 결과로 direction/horizon/claim_type 은
    Haiku run-to-run enum variance 의 주범 (claim_type 33% / horizon 25% /
    direction 8% split) 으로 확인 → G8 → G1 채택.

    backward compat (시그니처 유지):
        - positional: (period, claim_text, affected_assets) 그대로
        - claim_text 는 인수만 받고 hash 입력 X (R9-A.12)
        - direction/horizon/claim_type 는 kwarg 만 받고 hash 입력 X (R9-A.14)
        - source_evidence_ids kwarg (R9-A.12 신규)
        - output format `group:{period}:{md5_hex10}` 동일 (다운스트림 무영향)

    Use cases:
        - 같은 evidence subset + 같은 assets → 같은 group_id
          (wording / dir / horizon / claim_type 모두 무관)
        - LLM claim 은 후보, group_id 가 운영 identity
        - claim_text / direction / horizon / claim_type 은 display +
          diagnostic field 로만 유지 (운영 monitoring 에서 enum 분포 추적)
        - 과소병합 > 과대병합 원칙 (다른 evidence set or assets 이면 distinct)
    """
    p = period if isinstance(period, str) and period else "unknown"
    sig = _build_canonical_group_signature(
        source_evidence_ids, affected_assets,
        direction=direction, horizon=horizon, claim_type=claim_type,
    )
    payload = f"{p}|{sig}"
    h = hashlib.md5(payload.encode("utf-8")).hexdigest()[:10]
    return f"group:{p}:{h}"


# ──────────────────────────────────────────────────────────────────
# Normalize (defaults + auto ID)
# ──────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────
# Taxonomy v2 wiring — lazy taxonomy lookups (모듈 import-time 순수성 유지)
# ──────────────────────────────────────────────────────────────────

def _remap_to_8class_lazy():
    """core.asset_taxonomy._remap_to_8class lazy import (실패 시 None)."""
    try:
        from market_research.core.asset_taxonomy import _remap_to_8class
        return _remap_to_8class
    except Exception:
        return None


def _region_set() -> frozenset:
    try:
        from market_research.core.asset_taxonomy import REGION_SET
        return REGION_SET
    except Exception:
        return frozenset({"KR", "US", "NON_US_OVERSEAS", "GLOBAL", "UNKNOWN"})


def _topic_set() -> frozenset:
    try:
        from market_research.wiki.taxonomy import TAXONOMY_SET
        return TAXONOMY_SET
    except Exception:
        return frozenset()  # 비면 sector 검증 skip (validator 측 guard)


def normalize_claim(raw: dict | None) -> dict:
    """raw partial dict → 기본값 채워진 schema-conformant dict.

    - missing field 는 default 로 채움 (validator 가 충족하는 형태)
    - claim_id 미지정 시 deterministic ID 자동 산출
    - canonical_group_id 미지정 시 자동 산출 (R9-A.8)
    - source_evidence_ids 비어있고 supporting_evidence_ids 있으면 fallback
      copy (R9-A.10) — 기존 source 값은 덮어쓰지 않음
    - schema_version / extractor_version / extraction_method 자동 채움
    - 기존 값은 보존 (override 안 함)
    """
    out: dict[str, Any] = dict(raw or {})

    out.setdefault("schema_version", SCHEMA_VERSION)
    out.setdefault("extractor_version", EXTRACTOR_VERSION)
    out.setdefault("extraction_method", "manual")
    out.setdefault("warnings", [])

    out.setdefault("period", "unknown")
    out.setdefault("claim_text", "")
    out.setdefault("claim_type", "outlook_view")
    out.setdefault("source_evidence_ids", [])
    out.setdefault("supporting_evidence_ids", [])
    out.setdefault("counter_evidence_ids", [])

    # R9-A.10 — source_evidence_ids fallback. R9-A.4 운영 prompt 가
    # output schema 에 `source_evidence_ids` 를 명시하지 않아 LLM 출력에서
    # 항상 비어 있다 (R9-A.9 N=5 5/5 run 전부 'empty' sentinel 재현). 그러나
    # `supporting_evidence_ids` 는 prompt schema 에 명시되어 정상적으로 채워짐.
    # R9-A.0 contract 에 따르면 `supporting ⊆ source` — fallback 으로 source
    # 가 비어있을 때만 supporting 의 copy 로 채운다. 기존 source 가 채워진
    # 데이터 (R9-A.1 manual pilot 22 claim 등) 는 영향 0 (덮어쓰기 X).
    if not out["source_evidence_ids"] and out["supporting_evidence_ids"]:
        out["source_evidence_ids"] = list(out["supporting_evidence_ids"])

    out.setdefault("affected_assets", [])
    out.setdefault("causal_chain", [])
    out.setdefault("linked_wiki_pages", [])
    out.setdefault("direction", "unknown")
    out.setdefault("horizon", "unknown")
    out.setdefault("confidence", 0.0)
    out.setdefault("salience", 0.0)

    # Taxonomy v2 wiring — claim 진입 경계: affected_assets[].asset_class /
    # primary_asset 를 8-class 로 collapse (selector label → 8-class). 이미
    # 8-class 면 idempotent → 기존 운영 claim 의 hash 입력 불변(md5 drift 0).
    # confidence/role 은 LLM 산출분만 보존 — normalize 에서 default 부여 안 함
    # (기존 항목 변경 금지).
    _remap = _remap_to_8class_lazy()
    if _remap is not None:
        for a in out.get("affected_assets") or []:
            if isinstance(a, dict) and a.get("asset_class"):
                m = _remap(a["asset_class"])
                if m:
                    a["asset_class"] = m
        if out.get("primary_asset"):
            m = _remap(out["primary_asset"])
            if m:
                out["primary_asset"] = m

    if not out.get("claim_id"):
        out["claim_id"] = compute_claim_id(
            out.get("period") or "unknown",
            out.get("claim_text") or "",
            out.get("source_evidence_ids") or [],
            out.get("affected_assets") or [],
            direction=out.get("direction") or "unknown",
            horizon=out.get("horizon") or "unknown",
            claim_type=out.get("claim_type") or "outlook_view",
        )
    # R9-A.8/A.12 — canonical_group_id 자동 부착 (optional field).
    # R9-A.12 — source_evidence_ids 도 입력. fallback 이 위에서 supporting 의
    # copy 로 채워지므로 본 시점에서는 evidence layer 가 살아있음.
    if not out.get("canonical_group_id"):
        out["canonical_group_id"] = compute_canonical_group_id(
            out.get("period") or "unknown",
            out.get("claim_text") or "",
            out.get("affected_assets") or [],
            source_evidence_ids=out.get("source_evidence_ids") or [],
            direction=out.get("direction") or "unknown",
            horizon=out.get("horizon") or "unknown",
            claim_type=out.get("claim_type") or "outlook_view",
        )
    return out


# ──────────────────────────────────────────────────────────────────
# Validator
# ──────────────────────────────────────────────────────────────────

def _is_path_traversal(p: str) -> bool:
    """Path traversal / absolute / Windows drive letter 방어."""
    if not isinstance(p, str):
        return True
    if ".." in p:
        return True
    if p.startswith("/") or p.startswith("\\"):
        return True
    # Windows drive (C:\... or C:/) 거부
    if len(p) >= 2 and p[1] == ":":
        return True
    return False


def validate_claim(claim: Any) -> dict:
    """claim dict 검증.

    Returns:
        {"valid": bool, "errors": list[str], "warnings": list[str]}
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(claim, dict):
        return {"valid": False,
                "errors": [f"claim must be a dict, got {type(claim).__name__}"],
                "warnings": []}

    # required fields presence
    for f in REQUIRED_FIELDS:
        if f not in claim:
            errors.append(f"missing required field: {f}")
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    # schema_version
    sv = claim.get("schema_version")
    if sv != SCHEMA_VERSION:
        warnings.append(
            f"schema_version mismatch: expected {SCHEMA_VERSION!r}, got {sv!r}")

    # period
    p = claim.get("period")
    if not isinstance(p, str):
        errors.append(f"period must be a string, got {type(p).__name__}")
    elif not _PERIOD_RE.match(p):
        warnings.append(f"period format unusual (expect YYYY-MM or YYYY-Q[1-4]): {p!r}")

    # claim_id
    cid = claim.get("claim_id")
    if not isinstance(cid, str) or not cid.startswith("claim:"):
        errors.append(f"claim_id must start with 'claim:', got {cid!r}")

    # R9-A.8 — canonical_group_id (optional). 존재 시 format 만 검증.
    gid = claim.get("canonical_group_id")
    if gid is not None:
        if not isinstance(gid, str) or not gid.startswith("group:"):
            warnings.append(
                f"canonical_group_id format unusual: expected 'group:...', "
                f"got {gid!r}"
            )

    # claim_text
    txt = claim.get("claim_text")
    if not isinstance(txt, str):
        errors.append(f"claim_text must be a string, got {type(txt).__name__}")
    else:
        n = len(txt.strip())
        if n < CLAIM_TEXT_MIN_LEN:
            warnings.append(
                f"claim_text too short ({n} < {CLAIM_TEXT_MIN_LEN} chars)")
        elif n > CLAIM_TEXT_MAX_LEN:
            warnings.append(
                f"claim_text too long ({n} > {CLAIM_TEXT_MAX_LEN} chars)")

    # claim_type
    ct = claim.get("claim_type")
    if ct not in ALLOWED_CLAIM_TYPES:
        errors.append(
            f"invalid claim_type: {ct!r}, allowed={sorted(ALLOWED_CLAIM_TYPES)}")

    # direction / horizon
    d = claim.get("direction")
    if d not in ALLOWED_DIRECTIONS:
        errors.append(f"invalid direction: {d!r}, allowed={sorted(ALLOWED_DIRECTIONS)}")
    h = claim.get("horizon")
    if h not in ALLOWED_HORIZONS:
        errors.append(f"invalid horizon: {h!r}, allowed={sorted(ALLOWED_HORIZONS)}")

    # confidence / salience 0~1
    for k in ("confidence", "salience"):
        v = claim.get(k)
        try:
            vf = float(v)
            if not (0.0 <= vf <= 1.0):
                errors.append(f"{k} out of range [0,1]: {vf}")
        except (TypeError, ValueError):
            errors.append(f"{k} must be numeric in [0,1], got {v!r}")

    # source_evidence_ids
    eids = claim.get("source_evidence_ids")
    if not isinstance(eids, list):
        errors.append("source_evidence_ids must be a list")
        eids = []
    elif len(eids) == 0:
        warnings.append("source_evidence_ids is empty")

    # affected_assets
    aas = claim.get("affected_assets")
    if not isinstance(aas, list):
        errors.append("affected_assets must be a list")
    else:
        for i, a in enumerate(aas):
            if isinstance(a, dict):
                ac = a.get("asset_class")
                if ac not in ALLOWED_ASSET_CLASSES:
                    errors.append(
                        f"affected_assets[{i}].asset_class invalid: {ac!r}, "
                        f"allowed={sorted(ALLOWED_ASSET_CLASSES)}")
                # nested direction (optional)
                ad = a.get("direction")
                if ad is not None and ad not in ALLOWED_DIRECTIONS:
                    warnings.append(
                        f"affected_assets[{i}].direction unusual: {ad!r}")
                # v2 optional: confidence / role (값 있을 때만 soft 검증)
                acf = a.get("confidence")
                if acf is not None:
                    try:
                        if not (0.0 <= float(acf) <= 1.0):
                            warnings.append(
                                f"affected_assets[{i}].confidence out of [0,1]: {acf!r}")
                    except (TypeError, ValueError):
                        warnings.append(
                            f"affected_assets[{i}].confidence non-numeric: {acf!r}")
                arole = a.get("role")
                if arole is not None and arole not in ("primary", "secondary"):
                    warnings.append(
                        f"affected_assets[{i}].role unusual: {arole!r}")
            elif isinstance(a, str):
                if a not in ALLOWED_ASSET_CLASSES:
                    errors.append(
                        f"affected_assets[{i}] invalid: {a!r}, "
                        f"allowed={sorted(ALLOWED_ASSET_CLASSES)}")
            else:
                errors.append(
                    f"affected_assets[{i}] must be str or dict, "
                    f"got {type(a).__name__}")

    # causal_chain
    cc = claim.get("causal_chain")
    if not isinstance(cc, list):
        errors.append("causal_chain must be a list")
    else:
        for i, edge in enumerate(cc):
            if not isinstance(edge, dict):
                errors.append(
                    f"causal_chain[{i}] must be a dict, got {type(edge).__name__}")
                continue
            for f in ("source", "target", "relation"):
                if f not in edge:
                    errors.append(f"causal_chain[{i}] missing field: {f}")
                elif not isinstance(edge[f], str) or not edge[f]:
                    errors.append(f"causal_chain[{i}].{f} must be non-empty string")
            r = edge.get("relation")
            if isinstance(r, str) and r not in ALLOWED_RELATIONS:
                warnings.append(
                    f"causal_chain[{i}].relation unusual: {r!r}, "
                    f"allowed={sorted(ALLOWED_RELATIONS)}")

    # supporting_evidence_ids ⊂ source_evidence_ids
    sup = claim.get("supporting_evidence_ids")
    if not isinstance(sup, list):
        errors.append("supporting_evidence_ids must be a list")
    else:
        seids = set(eids) if isinstance(eids, list) else set()
        for s in sup:
            if s not in seids:
                warnings.append(
                    f"supporting_evidence_id outside source_evidence_ids set: {s!r}")

    # counter_evidence_ids
    cnt = claim.get("counter_evidence_ids")
    if not isinstance(cnt, list):
        errors.append("counter_evidence_ids must be a list")

    # linked_wiki_pages — path traversal
    lwp = claim.get("linked_wiki_pages")
    if not isinstance(lwp, list):
        errors.append("linked_wiki_pages must be a list")
    else:
        for i, lp in enumerate(lwp):
            if not isinstance(lp, str):
                errors.append(
                    f"linked_wiki_pages[{i}] must be str, got {type(lp).__name__}")
                continue
            if _is_path_traversal(lp):
                errors.append(
                    f"linked_wiki_pages[{i}] invalid path "
                    f"(traversal/absolute/drive): {lp!r}")

    # extraction_method
    em = claim.get("extraction_method")
    if em not in ALLOWED_EXTRACTION_METHODS:
        errors.append(
            f"invalid extraction_method: {em!r}, "
            f"allowed={sorted(ALLOWED_EXTRACTION_METHODS)}")

    # warnings field
    w_field = claim.get("warnings")
    if not isinstance(w_field, list):
        errors.append("warnings field must be a list")

    # ── Taxonomy v2 optional fields — soft 검증, 값 없으면 skip (REQUIRED 아님) ──
    # 전부 warning 만 → 신규필드 없는 기존 claim 은 valid 불변 (회귀 0).
    pa = claim.get("primary_asset")
    if pa is not None:
        if not isinstance(pa, str) or pa not in ALLOWED_ASSET_CLASSES:
            warnings.append(
                f"primary_asset invalid: {pa!r}, "
                f"allowed={sorted(ALLOWED_ASSET_CLASSES)}")
        elif isinstance(aas, list):
            asset_set = {
                (x.get("asset_class") if isinstance(x, dict) else x) for x in aas
            }
            if pa not in asset_set:
                warnings.append(
                    f"primary_asset {pa!r} not in affected_assets asset_class set")

    rg = claim.get("regions")
    if rg is not None:
        if not isinstance(rg, list):
            warnings.append("regions must be a list")
        else:
            _rset = _region_set()
            for r in rg:
                if r not in _rset:
                    warnings.append(f"region invalid: {r!r}")

    sc = claim.get("sectors")
    if sc is not None:
        if not isinstance(sc, list):
            warnings.append("sectors must be a list")
        else:
            _tset = _topic_set()
            if _tset:  # 비면 sector 검증 skip (import 실패 등)
                for s in sc:
                    if s not in _tset:
                        warnings.append(f"sector invalid: {s!r}")

    # role=primary 정확히 1개 (role 부여된 항목이 있을 때만)
    if isinstance(aas, list):
        roles = [a.get("role") for a in aas
                 if isinstance(a, dict) and a.get("role")]
        if roles and roles.count("primary") != 1:
            warnings.append(
                f"role=primary count expected 1, got {roles.count('primary')}")

    # ── Research claim optional fields — soft 검증 (값 없으면 skip, REQUIRED 아님) ──
    # stance↔direction 일치는 의도적으로 검증하지 않음(정의 분리: 전망 어조 vs 가격방향).
    st = claim.get("stance")
    if st is not None and st not in ALLOWED_STANCES:
        warnings.append(
            f"stance invalid: {st!r}, allowed={sorted(ALLOWED_STANCES)}")
    src = claim.get("source_type")
    if src is not None and src not in ALLOWED_SOURCE_TYPES:
        warnings.append(
            f"source_type invalid: {src!r}, allowed={sorted(ALLOWED_SOURCE_TYPES)}")
    for _f in ("broker_author", "view", "rationale_text", "risk_factor",
               "evidence_text"):
        _v = claim.get(_f)
        if _v is not None and not isinstance(_v, str):
            warnings.append(f"{_f} must be a string, got {type(_v).__name__}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


# ──────────────────────────────────────────────────────────────────
# Serializer + JSONL helpers
# ──────────────────────────────────────────────────────────────────

def serialize_claim(claim: dict) -> dict:
    """Stable field order — REQUIRED_FIELDS 순서 + OPTIONAL_FIELDS 후행.

    R9-A.8 — canonical_group_id 등 OPTIONAL_FIELDS 도 존재 시 직렬화에 포함.
    기존 데이터 호환 (REQUIRED 순서 보존), 새 데이터는 OPTIONAL 도 dump.
    """
    out: dict[str, Any] = {k: claim[k] for k in REQUIRED_FIELDS if k in claim}
    for k in OPTIONAL_FIELDS:
        if k in claim:
            out[k] = claim[k]
    return out


def write_claims_jsonl(path: str | Path, claims: list[dict]) -> Path:
    """JSONL 저장. path traversal 방어 + parent dir auto-mkdir.

    Phase 0 helper — 실제 운영 저장 경로 (data/claims/{YYYY-MM}.json) 결정은
    R9-A.1 에서. 본 helper 는 unit test 와 manual export 용.
    """
    p = Path(path)
    # absolute path 거부 + .. 거부 (heuristic; tmp_path 는 absolute 라 허용 필요 →
    # 호출 측에서 trusted root 를 넘겨주는 책임. 여기서는 .. 만 명시 거부.)
    p_str = str(p)
    if ".." in p.parts:
        raise ValueError(f"refusing path with '..': {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for c in claims:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True))
            f.write("\n")
    return p


def read_claims_jsonl(path: str | Path) -> list[dict]:
    """JSONL 로드. 파일 부재 시 빈 list."""
    p = Path(path)
    if ".." in p.parts:
        raise ValueError(f"refusing path with '..': {p}")
    out: list[dict] = []
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out
