# -*- coding: utf-8 -*-
"""R9-A.2 — Wiki promotion writer for normalized claims (08_Claims).

Phase 2 boundary:
- LLM 호출 0 (deterministic promotion rules only)
- 외부 R9-A.1 pilot artifact (debug/claims/*) 또는 in-memory claim list 를
  입력 받아 wiki page 와 canonical store 양쪽으로 저장
- daily_update / debate / fund_comment / asset_movement_anchor 미수정
- read-side consumer 부재 (R9-A.3 까지 dormant)

Public API:
    write_claim_page(claim, dry_run=False, promotion_rule=None) -> Path | None
    promote_claims(claims, rule="auto", force_ids=(), dry_run=False) -> dict
    _is_claim_wiki(fp) -> bool

CLI:
    python -m market_research.wiki.claim_pages promote \
        --period 2026-04 \
        --from <jsonl> \
        [--dry-run] [--force-promote ID]... [--rule auto|A|B|both]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

from market_research.analyze.claim_extractor import (
    read_claims_jsonl,
    serialize_claim,
    validate_claim,
)
from market_research.analyze.claim_store import (
    PROMOTION_LEDGER_PATH,
    append_promotion_ledger,
    save_claims_canonical,
)
from market_research.wiki.paths import CLAIMS_WIKI_DIR


CLAIM_HEADING_MAX_LEN = 120
CLAIM_WIKI_SCHEMA_VERSION = "r9a-claim-1.0.0"

# R9-A.4 Commit 4.1 — target_suffix 검증 패턴 (claim_store 와 동일 규칙).
import re as _re
_TARGET_SUFFIX_RE = _re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_target_suffix(target_suffix: str | None) -> None:
    """target_suffix 가 None 이면 통과. 비정상 포맷이면 ValueError."""
    if target_suffix is None:
        return
    if not isinstance(target_suffix, str) or not target_suffix:
        raise ValueError(
            f"target_suffix must be non-empty string, got {target_suffix!r}")
    if not _TARGET_SUFFIX_RE.match(target_suffix):
        raise ValueError(
            f"target_suffix must be alphanumeric / underscore / hyphen, "
            f"got {target_suffix!r}")

# Acceptance band for promotion_rate when running CLI live write.
# Out-of-band live runs are aborted unless --allow-out-of-band is passed.
# dry-run never aborts. Threshold itself is fixed by spec — do not modify.
ACCEPTANCE_BAND: tuple[float, float] = (30.0, 70.0)

# R9-A.4 Commit 5 — Rule B calibration (workorder "commit5_ruleb").
# 9.3b real Haiku 분석:
#   - chain length 분포 (chain=2/3/4 = 1/16/1) 가 너무 집중되어 chain≥2 단독은
#     18/18 rate 100% 전수 통과 → out_of_band.
#   - chain≥3 단독 시 17/18 (94.4%) 여전히 out_of_band.
#   - chain≥3 + supporting_ev_count≥2 조합만 12/18 (66.7%) acceptance band 진입.
# 본 commit 은 임계 변경만 (prompt / Rule A / band 유지).
RULE_B_CHAIN_MIN: int = 3
RULE_B_SUPPORTING_EV_MIN: int = 2


# ──────────────────────────────────────────────────────────────────
# Promotion rules (deterministic, no LLM)
# ──────────────────────────────────────────────────────────────────

def _meets_rule_a(claim: dict) -> bool:
    """Rule A (cross-asset, A3): salience >= 0.7 AND confidence >= 0.7 AND
    len(affected_assets) >= 3.

    R9-A.2 후속 — 단순 고신뢰 claim 이 아니라 '여러 자산군을 관통하는
    설명축' 만 wiki 승격하도록 좁힘. pilot 22건 기준 8건 / 36.4% 통과
    (acceptance band [30%, 70%] 내).
    """
    try:
        s = float(claim.get("salience", 0.0))
        c = float(claim.get("confidence", 0.0))
    except (TypeError, ValueError):
        return False
    aas = claim.get("affected_assets") or []
    return s >= 0.7 and c >= 0.7 and isinstance(aas, list) and len(aas) >= 3


def _rule_b_diagnose(claim: dict) -> tuple[bool, str | None]:
    """Rule B 통과 여부 + 실패 사유.

    R9-A.4 Commit 5 calibration:
      - chain length >= RULE_B_CHAIN_MIN (3)
      - AND supporting_evidence_ids 길이 >= RULE_B_SUPPORTING_EV_MIN (2)

    Returns:
        (passed, fail_reason)
        fail_reason ∈ {"chain_too_short", "insufficient_supporting_evidence",
                        None}
    """
    cc = claim.get("causal_chain") or []
    if not isinstance(cc, list) or len(cc) < RULE_B_CHAIN_MIN:
        return False, "chain_too_short"
    sup = claim.get("supporting_evidence_ids") or []
    if not isinstance(sup, list) or len(sup) < RULE_B_SUPPORTING_EV_MIN:
        return False, "insufficient_supporting_evidence"
    return True, None


def _meets_rule_b(claim: dict) -> bool:
    """Rule B (calibrated): chain≥3 + supporting_evidence_ids≥2.

    Commit 5 (workorder commit5_ruleb) — 9.3b real Haiku 분석 기반 임계 보정.
    Rule A / prompt / acceptance band 는 변경 0.
    """
    return _rule_b_diagnose(claim)[0]


def _evaluate_rules(claim: dict, rule: str,
                    force_ids: set[str]) -> tuple[bool, str | None]:
    """Decide whether a claim should be promoted under given rule selector.

    Returns:
        (promoted: bool, applied_rule: "A"|"B"|"C"|None)
    """
    cid = claim.get("claim_id")
    if cid in force_ids:
        return True, "C"

    if rule == "auto" or rule == "both":
        if _meets_rule_a(claim):
            return True, "A"
        if _meets_rule_b(claim):
            return True, "B"
        return False, None
    if rule == "A":
        return (_meets_rule_a(claim), "A" if _meets_rule_a(claim) else None)
    if rule == "B":
        return (_meets_rule_b(claim), "B" if _meets_rule_b(claim) else None)
    raise ValueError(f"unknown promotion rule: {rule!r}")


# ──────────────────────────────────────────────────────────────────
# Page identification (idempotency / guard)
# ──────────────────────────────────────────────────────────────────

def _is_claim_wiki(fp: Path) -> bool:
    """Detect 08_Claims/ wiki page by frontmatter signature."""
    if not fp.exists():
        return False
    try:
        head = fp.read_text(encoding="utf-8", errors="ignore")[:600]
    except OSError:
        return False
    return "source_type: claim_wiki" in head


def _hash10_of(claim_id: str) -> str:
    """Extract trailing 10-hex from 'claim:{period}:{hash10}'."""
    return claim_id.rsplit(":", 1)[-1]


def _page_path(claim: dict, target_suffix: str | None = None) -> Path:
    """Wiki page path. target_suffix 가 주어지면 운영 path 와 분리된 file.

    `target_suffix=None` → `{period}_claim_{h}.md` (R9-A.2 운영 동작)
    `target_suffix='r9a4-replay'` → `{period}_claim_{h}.r9a4-replay.md`
    """
    _validate_target_suffix(target_suffix)
    period = claim.get("period") or "unknown"
    h = _hash10_of(claim.get("claim_id") or "claim:unknown:0000000000")
    if target_suffix:
        return CLAIMS_WIKI_DIR / f"{period}_claim_{h}.{target_suffix}.md"
    return CLAIMS_WIKI_DIR / f"{period}_claim_{h}.md"


def _read_existing_supporting_ids(fp: Path) -> list[str] | None:
    """Existing wiki page 에서 supporting_evidence_ids 를 frontmatter+body 로
    추출. 실패 시 None."""
    if not fp.exists():
        return None
    try:
        text = fp.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    # Body marker: '## Evidence' 섹션의 list 항목 'supporting_evidence_ids:' 라인
    marker = "supporting_evidence_ids:"
    idx = text.find(marker)
    if idx < 0:
        return None
    line_end = text.find("\n", idx)
    line = text[idx + len(marker):line_end if line_end >= 0 else None].strip()
    # JSON-style list 또는 comma-separated
    try:
        if line.startswith("["):
            return [str(x) for x in json.loads(line)]
        return [s.strip() for s in line.strip("[]").split(",") if s.strip()]
    except (json.JSONDecodeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────────
# Body rendering
# ──────────────────────────────────────────────────────────────────

def _truncate_heading(text: str, limit: int = CLAIM_HEADING_MAX_LEN) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def _render_affected_assets(claim: dict) -> list[str]:
    out: list[str] = []
    for a in claim.get("affected_assets", []) or []:
        if isinstance(a, dict):
            ac = a.get("asset_class", "")
            d = a.get("direction", "")
            ch = a.get("channel")
            tail = f" (channel: {ch})" if isinstance(ch, str) and ch else ""
            out.append(f"- {ac}: {d}{tail}")
        elif isinstance(a, str):
            out.append(f"- {a}")
    if not out:
        out = ["- (없음)"]
    return out


def _render_causal_chain(claim: dict) -> list[str]:
    cc = claim.get("causal_chain") or []
    if not cc:
        return ["없음"]
    out: list[str] = []
    for edge in cc:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source", "?")
        rel = edge.get("relation", "?")
        tgt = edge.get("target", "?")
        out.append(f"- {src} --[{rel}]--> {tgt}")
    return out or ["없음"]


def _render_evidence(claim: dict) -> list[str]:
    sup = claim.get("supporting_evidence_ids") or []
    cnt = claim.get("counter_evidence_ids") or []
    lines = [f"- supporting_evidence_ids: {json.dumps(list(sup), ensure_ascii=False)}"]
    if cnt:
        lines.append(
            f"- counter_evidence_ids: {json.dumps(list(cnt), ensure_ascii=False)}"
        )
    return lines


def _is_path_traversal(p: str) -> bool:
    if not isinstance(p, str):
        return True
    if ".." in p:
        return True
    if p.startswith("/") or p.startswith("\\"):
        return True
    if len(p) >= 2 and p[1] == ":":
        return True
    return False


def _render_linked_wiki(claim: dict) -> list[str]:
    pages = claim.get("linked_wiki_pages") or []
    out: list[str] = []
    for lp in pages:
        if not isinstance(lp, str):
            continue
        if _is_path_traversal(lp):
            # writer 2차 방어 — R9-A.0 validator 도 거르지만 안전망
            continue
        out.append(f"- {lp}")
    if not out:
        out = ["(없음)"]
    return out


def _render_metadata(claim: dict) -> list[str]:
    return [
        f"- confidence: {claim.get('confidence')}",
        f"- salience: {claim.get('salience')}",
        f"- horizon: {claim.get('horizon')}",
        f"- direction: {claim.get('direction')}",
        f"- claim_type: {claim.get('claim_type')}",
        f"- schema_version: {claim.get('schema_version')}",
        f"- extractor_version: {claim.get('extractor_version')}",
        f"- extraction_method: {claim.get('extraction_method')}",
    ]


def _render_page(claim: dict, promotion_rule: str | None) -> str:
    heading = _truncate_heading(claim.get("claim_text") or "(제목 없음)")
    fm = [
        "---",
        "type: claim",
        "source_type: claim_wiki",
        f"schema_version: {CLAIM_WIKI_SCHEMA_VERSION}",
        f"claim_id: {claim.get('claim_id')}",
        f"period: {claim.get('period')}",
        f"extractor_version: {claim.get('extractor_version')}",
        f"promoted_at: {datetime.now().isoformat(timespec='seconds')}",
        f"promotion_rule: {promotion_rule or 'unknown'}",
        "---",
        "",
    ]
    # Taxonomy v2 wiring — region×sector frontmatter. 값 있을 때만 emit →
    # 신규필드 없는 claim 은 키 생략(불필요 drift 방지). flow-list/quoted scalar
    # 는 wiki_context_pack_builder._parse_frontmatter 가 수용.
    v2_fm: list[str] = []
    pa = claim.get("primary_asset")
    if pa:
        v2_fm.append(f"primary_asset: {json.dumps(pa, ensure_ascii=False)}")
    aa_classes = [
        (a.get("asset_class") if isinstance(a, dict) else a)
        for a in (claim.get("affected_assets") or [])
    ]
    aa_classes = [str(a) for a in aa_classes if a]
    if aa_classes:
        v2_fm.append(
            f"affected_assets: {json.dumps(aa_classes, ensure_ascii=False)}")
    regions = [str(r) for r in (claim.get("regions") or []) if r]
    if regions:
        v2_fm.append(f"regions: {json.dumps(regions, ensure_ascii=False)}")
    sectors = [str(s) for s in (claim.get("sectors") or []) if s]
    if sectors:
        v2_fm.append(f"sectors: {json.dumps(sectors, ensure_ascii=False)}")
    if v2_fm:  # 닫는 '---'/'' 앞에 삽입
        fm = fm[:-2] + v2_fm + fm[-2:]
    body = [
        f"# {heading}",
        "",
        "## Summary",
        f"- {claim.get('claim_text', '')}",
        f"- claim_type: {claim.get('claim_type')}",
        f"- direction: {claim.get('direction')}",
        f"- horizon: {claim.get('horizon')}",
        "",
        "## Affected Assets",
        *_render_affected_assets(claim),
        "",
        "## Causal Chain",
        *_render_causal_chain(claim),
        "",
        "## Evidence",
        *_render_evidence(claim),
        "",
        "## Linked Wiki",
        *_render_linked_wiki(claim),
        "",
        "## Metadata",
        *_render_metadata(claim),
        "",
        "> Promoted claim — daily_update base draft 가 overwrite 하지 않음.",
    ]
    return "\n".join(fm + body) + "\n"


# ──────────────────────────────────────────────────────────────────
# write_claim_page
# ──────────────────────────────────────────────────────────────────

def write_claim_page(claim: dict,
                     dry_run: bool = False,
                     promotion_rule: str | None = None,
                     target_suffix: str | None = None) -> Path | None:
    """Write a single claim's wiki page (idempotent).

    target_suffix : R9-A.4 Commit 4.1 — replay/smoke 산출물 분리. 운영 wiki
        file 과 충돌하지 않는 별 path 로 write. None 이면 운영 동작 그대로.

    Returns:
        Path written, or None if skipped (idempotent / dry-run).
    """
    v = validate_claim(claim)
    if not v["valid"]:
        raise ValueError(
            f"claim failed validation before write: {v['errors']}")

    out = _page_path(claim, target_suffix=target_suffix)
    if dry_run:
        return None

    if out.exists() and _is_claim_wiki(out):
        # idempotent: same supporting_evidence_ids → silent skip
        # different → conservative skip (caller decides via promote_claims)
        return None

    CLAIMS_WIKI_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(_render_page(claim, promotion_rule), encoding="utf-8")
    return out


# ──────────────────────────────────────────────────────────────────
# promote_claims
# ──────────────────────────────────────────────────────────────────

def promote_claims(claims: list[dict],
                   rule: str = "auto",
                   force_ids: Iterable[str] = (),
                   dry_run: bool = False,
                   target_suffix: str | None = None) -> dict:
    """Apply promotion rules and write wiki pages for qualifying claims.

    Returns:
        {
          "input_count": int,
          "promoted": [claim_id, ...],
          "skipped": [claim_id, ...],
          "skip_reasons": {"rule_a_b_unmet": int, "duplicate_existing": int,
                            "supporting_diff_existing": int,
                            "validation_failed": int},
          "rule_breakdown": {"A": int, "B": int, "C": int},
          "promoted_count": int, "skipped_count": int,
          "rule": str, "dry_run": bool
        }
    """
    force_set = {x for x in (force_ids or ()) if isinstance(x, str)}
    promoted: list[str] = []
    skipped: list[str] = []
    skip_reasons = {
        "rule_a_b_unmet": 0,
        "duplicate_existing": 0,
        "supporting_diff_existing": 0,
        "validation_failed": 0,
    }
    rule_breakdown = {"A": 0, "B": 0, "C": 0}

    for claim in (claims or []):
        cid = claim.get("claim_id") or "(no id)"

        v = validate_claim(claim)
        if not v["valid"]:
            skipped.append(cid)
            skip_reasons["validation_failed"] += 1
            continue

        ok, applied = _evaluate_rules(claim, rule, force_set)
        if not ok:
            skipped.append(cid)
            skip_reasons["rule_a_b_unmet"] += 1
            continue

        out = _page_path(claim, target_suffix=target_suffix)
        if out.exists() and _is_claim_wiki(out):
            existing_sup = _read_existing_supporting_ids(out) or []
            new_sup = list(claim.get("supporting_evidence_ids") or [])
            if sorted(existing_sup) == sorted(map(str, new_sup)):
                skipped.append(cid)
                skip_reasons["duplicate_existing"] += 1
            else:
                # conservative skip — overwrite 금지, update 는 후행 phase
                skipped.append(cid)
                skip_reasons["supporting_diff_existing"] += 1
            continue

        if not dry_run:
            write_claim_page(
                claim, dry_run=False, promotion_rule=applied,
                target_suffix=target_suffix,
            )
        promoted.append(cid)
        if applied in rule_breakdown:
            rule_breakdown[applied] += 1

    return {
        "input_count": len(claims or []),
        "promoted": promoted,
        "skipped": skipped,
        "skip_reasons": skip_reasons,
        "rule_breakdown": rule_breakdown,
        "promoted_count": len(promoted),
        "skipped_count": len(skipped),
        "rule": rule,
        "dry_run": bool(dry_run),
    }


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m market_research.wiki.claim_pages",
        description="R9-A.2 promote canonical claims to 08_Claims wiki.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("promote", help="Promote claims from a JSONL source.")
    pr.add_argument("--period", required=True, help="YYYY-MM or YYYY-Q[1-4]")
    pr.add_argument("--from", dest="from_path", required=True,
                    help="Path to claims JSONL (R9-A.1 pilot artifact).")
    pr.add_argument("--rule", choices=("auto", "A", "B", "both"),
                    default="auto")
    pr.add_argument("--force-promote", action="append", default=[],
                    metavar="CLAIM_ID",
                    help="Claim IDs to force-promote regardless of rules.")
    pr.add_argument("--dry-run", action="store_true",
                    help="Plan only; no file writes, no ledger append.")
    pr.add_argument("--allow-out-of-band", action="store_true",
                    help=("Allow live write when promotion_rate is outside "
                          f"acceptance band {ACCEPTANCE_BAND}. "
                          "dry-run is never aborted regardless."))
    pr.add_argument("--source", default="manual_pilot_r9a1",
                    help="Source tag stored in canonical store + ledger.")
    pr.add_argument("--extractor-version", default="r9a.1-haiku",
                    help="Extractor version tag.")
    return p


def _promotion_rate(result: dict) -> float:
    n = int(result.get("input_count", 0) or 0)
    if n == 0:
        return 0.0
    return result.get("promoted_count", 0) / n * 100.0


def _check_band_or_abort(result: dict, *,
                         allow_out_of_band: bool,
                         dry_run: bool) -> None:
    """Block live write when promotion_rate is out of acceptance band.

    - dry-run never aborts (diagnostics-only path).
    - --allow-out-of-band override suppresses abort.
    - Empty input (input_count=0) never aborts (rate=0 is degenerate).
    Raises SystemExit on abort with a structured message.
    """
    if dry_run or allow_out_of_band:
        return
    n = int(result.get("input_count", 0) or 0)
    if n == 0:
        return
    rate = _promotion_rate(result)
    lo, hi = ACCEPTANCE_BAND
    if rate < lo or rate > hi:
        raise SystemExit(
            "[promote_claims] ABORT: promotion_rate out of acceptance band — "
            f"input_count={n} "
            f"promoted_count={result.get('promoted_count', 0)} "
            f"promotion_rate={rate:.1f}% "
            f"allowed_band=[{lo:.0f}%, {hi:.0f}%] — "
            "use --allow-out-of-band to override."
        )


def _print_result(period: str, result: dict, *, dry_run: bool) -> None:
    rate = (result["promoted_count"] / result["input_count"] * 100
            if result["input_count"] else 0.0)
    print(f"[promote_claims] period={period} rule={result['rule']} "
          f"dry_run={dry_run}")
    print(f"  input_count    = {result['input_count']}")
    print(f"  promoted_count = {result['promoted_count']} "
          f"({rate:.1f}%)")
    print(f"  skipped_count  = {result['skipped_count']}")
    print(f"  skip_reasons   = {result['skip_reasons']}")
    print(f"  rule_breakdown = {result['rule_breakdown']}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd != "promote":
        return 2

    period = args.period
    src_path = Path(args.from_path)
    raw = read_claims_jsonl(src_path)
    if not raw:
        print(f"[promote_claims] no claims loaded from {src_path}",
              file=sys.stderr)

    valid_claims: list[dict] = []
    for i, c in enumerate(raw):
        v = validate_claim(c)
        if v["valid"]:
            valid_claims.append(serialize_claim(c))
        else:
            print(f"[promote_claims] skip invalid claim[{i}]: {v['errors']}",
                  file=sys.stderr)

    # Plan: never writes to disk (dry_run=True passes through to
    # write_claim_page which short-circuits before any file I/O).
    plan = promote_claims(
        valid_claims,
        rule=args.rule,
        force_ids=args.force_promote,
        dry_run=True,
    )
    _print_result(period, plan, dry_run=args.dry_run)

    # Out-of-band guard runs BEFORE any wiki / canonical / ledger write.
    _check_band_or_abort(
        plan,
        allow_out_of_band=args.allow_out_of_band,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        return 0

    # Apply: writes wiki pages for promoted claims (idempotent).
    result = promote_claims(
        valid_claims,
        rule=args.rule,
        force_ids=args.force_promote,
        dry_run=False,
    )

    save_claims_canonical(
        period=period,
        claims=valid_claims,
        source=args.source,
        extractor_version=args.extractor_version,
        promotion_result=result,
    )

    ledger_row = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "period": period,
        "rule": result["rule"],
        "input_count": result["input_count"],
        "promoted_count": result["promoted_count"],
        "skipped_count": result["skipped_count"],
        "skip_reasons": result["skip_reasons"],
        "rule_breakdown": result["rule_breakdown"],
        "extractor_version": args.extractor_version,
        "source": args.source,
        "out_of_band_override": bool(args.allow_out_of_band),
    }
    append_promotion_ledger(ledger_row)
    print(f"[promote_claims] ledger appended → {PROMOTION_LEDGER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
