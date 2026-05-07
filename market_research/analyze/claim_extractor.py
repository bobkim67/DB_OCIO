# -*- coding: utf-8 -*-
"""R9-A.0 — Normalized claim schema, deterministic ID, validator, JSONL helpers.

LLM 호출 0. Phase 0 범위는 "데이터 형상의 단일 source-of-truth" 만 정의한다.
실제 LLM extractor 는 Phase 1 (claim_extractor_pilot) 에서 별도 GO 후 추가.

Public API:
    SCHEMA_VERSION, EXTRACTOR_VERSION
    ALLOWED_ASSET_CLASSES, ALLOWED_CLAIM_TYPES, ALLOWED_DIRECTIONS,
    ALLOWED_HORIZONS, ALLOWED_RELATIONS, ALLOWED_EXTRACTION_METHODS
    REQUIRED_FIELDS

    compute_claim_id(period, claim_text, source_evidence_ids,
                     affected_assets) -> str
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

# R8-B asset_movement_anchor._ASSET_TO_INDICATOR keys 와 동일 8 자산군.
ALLOWED_ASSET_CLASSES: frozenset[str] = frozenset({
    "국내주식", "해외주식", "국내채권", "해외채권",
    "크레딧", "현금성", "환율(FX)", "원자재금",
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

# Threshold heuristics (validator soft warnings)
CLAIM_TEXT_MIN_LEN = 8
CLAIM_TEXT_MAX_LEN = 500

# period regex: YYYY-MM or YYYY-Q[1-4]
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2]|Q[1-4])$")


# ──────────────────────────────────────────────────────────────────
# Deterministic claim_id
# ──────────────────────────────────────────────────────────────────

def _normalize_claim_text(text: Any) -> str:
    """Unicode NFKC + whitespace squash. ID 산출의 deterministic 입력."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    text = unicodedata.normalize("NFKC", text).strip()
    return " ".join(text.split())


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


def compute_claim_id(period: str,
                     claim_text: str,
                     source_evidence_ids: list[str] | None,
                     affected_assets: list[Any] | None) -> str:
    """Deterministic claim_id.

    같은 (period, normalized claim_text, sorted source_evidence_ids,
    sorted affected_assets) 입력은 입력 순서/중복과 무관하게 같은 ID.
    claim_text 가 변하면 다른 ID.

    Returns: "claim:{period}:{md5_hex10}"
    """
    p = period if isinstance(period, str) and period else "unknown"
    norm_text = _normalize_claim_text(claim_text or "")

    eids: list[str] = []
    if isinstance(source_evidence_ids, list):
        eids = sorted({str(e) for e in source_evidence_ids if e})

    aas = _extract_asset_class_strings(affected_assets)

    payload = {
        "period": p,
        "claim_text": norm_text,
        "source_evidence_ids": eids,
        "affected_assets": aas,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    h = hashlib.md5(blob).hexdigest()[:10]
    return f"claim:{p}:{h}"


# ──────────────────────────────────────────────────────────────────
# Normalize (defaults + auto ID)
# ──────────────────────────────────────────────────────────────────

def normalize_claim(raw: dict | None) -> dict:
    """raw partial dict → 기본값 채워진 schema-conformant dict.

    - missing field 는 default 로 채움 (validator 가 충족하는 형태)
    - claim_id 미지정 시 deterministic ID 자동 산출
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
    out.setdefault("affected_assets", [])
    out.setdefault("causal_chain", [])
    out.setdefault("linked_wiki_pages", [])
    out.setdefault("direction", "unknown")
    out.setdefault("horizon", "unknown")
    out.setdefault("confidence", 0.0)
    out.setdefault("salience", 0.0)

    if not out.get("claim_id"):
        out["claim_id"] = compute_claim_id(
            out.get("period") or "unknown",
            out.get("claim_text") or "",
            out.get("source_evidence_ids") or [],
            out.get("affected_assets") or [],
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

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


# ──────────────────────────────────────────────────────────────────
# Serializer + JSONL helpers
# ──────────────────────────────────────────────────────────────────

def serialize_claim(claim: dict) -> dict:
    """Stable field order — REQUIRED_FIELDS 순서로 dict 재구성. 미존재 키는 skip."""
    return {k: claim[k] for k in REQUIRED_FIELDS if k in claim}


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
