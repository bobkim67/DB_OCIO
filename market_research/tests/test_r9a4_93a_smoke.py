# -*- coding: utf-8 -*-
"""R9-A.4 9.3a — LLM 0 / write 0 plan smoke.

Commit 3 의 promotion plan + ledger preview + failure matrix + monthly cap
pre-abort + dry_run_debug_path 가 end-to-end 경로에서도 invariant 를 유지
하는지 검증한다. Commit 3 close 와 Commit 4 진입 사이의 안전망.

본 smoke 의 invariant:
  - LLM 호출 0 (모든 llm_call 인자는 stub)
  - canonical store / wiki / ledger 실 write 0
  - 보호 영역 6 file md5 변경 0
  - Step 2.7 default OFF 유지
  - 신규 production code 0 (test 만 추가)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from market_research.analyze.claim_extractor_runner import (
    estimate_pre_call_cost_usd,
)
from market_research.pipeline import claim_extract_step as ces
from market_research.pipeline.claim_ledger_schema import (
    LEDGER_ROW_FIELDS,
    MONTHLY_CAP_USD,
    build_ledger_row_preview,
    compute_monthly_cost_usd,
)
from market_research.pipeline.claim_promotion_plan import build_promotion_plan


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_92 = REPO_ROOT / "debug" / "claims" / "r9a4_92_dryrun_result.json"


# ──────────────────────────────────────────────────────────────────
# Synthetic fixture — 9.2 18-claim shape 모사 (LLM 산물 schema)
# ──────────────────────────────────────────────────────────────────

def _promotable_claim(idx: int) -> dict:
    return {
        "schema_version": "1.0.0",
        "claim_id": f"claim:2026-04:smoke{idx:05d}a",
        "period": "2026-04",
        "source_evidence_ids": [f"art_{idx}_a", f"art_{idx}_b"],
        "claim_text": f"smoke fixture promote-eligible claim {idx} — 다자산군 영향.",
        "claim_type": "event_to_macro",
        "affected_assets": [
            {"asset_class": "국내주식", "direction": "positive"},
            {"asset_class": "해외주식", "direction": "positive"},
            {"asset_class": "국내채권", "direction": "negative"},
        ],
        "causal_chain": [
            {"source": "x", "target": "y", "relation": "raises"},
            {"source": "y", "target": "z", "relation": "supports"},
        ],
        "direction": "positive",
        "horizon": "short",
        "confidence": 0.9,
        "salience": 0.9,
        "supporting_evidence_ids": [f"art_{idx}_a"],
        "counter_evidence_ids": [],
        "linked_wiki_pages": [],
        "extractor_version": "r9a.4-haiku",
        "extraction_method": "llm",
        "warnings": [],
    }


def _non_promotable_claim(idx: int) -> dict:
    c = _promotable_claim(idx)
    c["claim_id"] = f"claim:2026-04:smokefail{idx:03d}"
    c["affected_assets"] = [{"asset_class": "국내주식",
                              "direction": "positive"}]
    c["causal_chain"] = [{"source": "x", "target": "y",
                            "relation": "raises"}]
    return c


def _synthetic_evidence(n: int = 3) -> list[dict]:
    return [
        {"article_id": f"art_smoke_{i}", "title": f"smoke evidence {i}",
         "source": "Reuters", "date": "2026-04-15", "topic": "지정학"}
        for i in range(n)
    ]


# ──────────────────────────────────────────────────────────────────
# Smoke 1 — estimate_pre_call_cost_usd public helper 가시성 + 수치 sanity
# ──────────────────────────────────────────────────────────────────

def test_93a_estimate_pre_call_cost_public_helper():
    """C3-δ 가 추가한 helper 가 import 가능 + 입력 형태별 정상 동작."""
    # 빈 입력 → 0.0
    assert estimate_pre_call_cost_usd("2026-04", None) == 0.0
    assert estimate_pre_call_cost_usd("2026-04", []) == 0.0

    # 정상 입력 → > 0 (Haiku 단가 기반 추정)
    cost = estimate_pre_call_cost_usd("2026-04", _synthetic_evidence(3))
    assert isinstance(cost, float)
    assert cost > 0.0
    # MAX_TOKENS=16384 + prompt 으로 0.05 USD 미만 영역
    assert cost < 0.5


# ──────────────────────────────────────────────────────────────────
# Smoke 2 — end-to-end plan smoke (synthetic, no canonical_existing)
# ──────────────────────────────────────────────────────────────────

def test_93a_full_plan_smoke_synthetic():
    """promote 4 + non-promote 6 = 10 claims → plan rate 40% in-band.

    검증:
      - build_promotion_plan 결과 구조
      - would_save 의 canonical / wiki / ledger 3 entry detail
      - ledger row preview 24 필드 schema 충족
      - actually_saved == []
      - llm_call=stub (LLM 0)
    """
    promo = [_promotable_claim(i) for i in range(4)]
    skip_a3 = [_non_promotable_claim(i) for i in range(6)]
    raw = json.dumps(promo + skip_a3, ensure_ascii=False)

    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_synthetic_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        llm_call=lambda p: raw,
    )

    # 정상 plan 흐름
    assert out["status"] == ces.STATUS_OK_PLAN_READY
    assert out["warning_code"] is None
    assert out["writes"] == 0
    assert out["actually_saved"] == []
    plan = out["plan"]
    # runner 가 claim_id 를 normalize 후 재생성하므로 input_count 만 검증
    assert plan["input_count"] == 10
    assert plan["promoted_count"] == 4
    assert plan["skipped_count"] == 6
    assert plan["promotion_rate"] == 40.0
    assert plan["rule_breakdown"]["A"] == 4
    assert plan["out_of_band"] is False

    # would_save — 3 kind detail
    kinds = {w["kind"] for w in out["would_save"]}
    assert {"canonical_store", "wiki_08_claims", "promotion_ledger"} <= kinds
    for w in out["would_save"]:
        assert w["enabled_in_this_commit"] is False
    canonical = next(w for w in out["would_save"]
                     if w["kind"] == "canonical_store")
    assert canonical["would_add_count"] == 4
    assert canonical["merge_policy"] == "prefer_higher_confidence"
    wiki = next(w for w in out["would_save"]
                if w["kind"] == "wiki_08_claims")
    assert len(wiki["would_create_pages"]) == 4

    # ledger preview 24필드
    preview = out["ledger_row_preview"]
    for f in LEDGER_ROW_FIELDS:
        assert f in preview, f"ledger preview 필드 누락: {f}"
    assert preview["status"] == ces.STATUS_OK_PLAN_READY
    assert preview["dry_run"] is True
    assert preview["promoted_count"] == 4


# ──────────────────────────────────────────────────────────────────
# Smoke 3 — Monthly cap pre-abort + R9-A.1 row filter exclusion
# ──────────────────────────────────────────────────────────────────

def test_93a_monthly_cap_filter_excludes_r9a1_row(tmp_path):
    """R9-A.1 manual_pilot row (cost 가짜로 0.9) 가 ledger 에 있어도
    R9-A.4 source filter 가 자연 제외 → 그 row 단독으로는 pre-abort 미발생.
    """
    ledger = tmp_path / "_promotion_quality.jsonl"
    # R9-A.1 row — manual_pilot, cost 가상 0.9 (실제 R9-A.1 은 LLM 비용 미기록).
    r9a1_row = {
        "period": "2026-04",
        "source": "manual_pilot_r9a1",
        "extractor_version": "r9a.1-haiku",
        "cost_usd": 0.9,
    }
    ledger.write_text(
        json.dumps(r9a1_row, ensure_ascii=False) + "\n", encoding="utf-8",
    )

    # 단독 호출 — filter 가 R9-A.4 source 만 누적 → 0.0
    assert compute_monthly_cost_usd(
        "2026-04", ledger_path=ledger,
    ) == 0.0

    # step 호출 — pre-abort 미발생 (status != monthly pre-abort)
    promo = [_promotable_claim(i) for i in range(2)]
    skip_a3 = [_non_promotable_claim(i) for i in range(3)]
    raw = json.dumps(promo + skip_a3, ensure_ascii=False)
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_synthetic_evidence(3),
        monthly_cap_usd=1.0,
        ledger_path_override=ledger,
        llm_call=lambda p: raw,
    )
    assert out["status"] != ces.STATUS_COST_CAP_MONTHLY_PRE_ABORT
    assert out["monthly_cost_usd_so_far"] == 0.0


def test_93a_monthly_cap_pre_abort_with_r9a4_rows(tmp_path):
    """R9-A.4 source 의 cost 누적이 cap 을 초과 → pre-abort."""
    ledger = tmp_path / "_promotion_quality.jsonl"
    rows = [
        {"period": "2026-04", "source": "daily_update_r9a4",
         "extractor_version": "r9a.4-haiku", "cost_usd": 0.50},
        {"period": "2026-04", "source": "daily_update_r9a4",
         "extractor_version": "r9a.4-haiku", "cost_usd": 0.49},
    ]
    with ledger.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # so_far = 0.99, est_cost > 0.01 → 1.0 cap 초과
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_synthetic_evidence(3),
        monthly_cap_usd=1.0,
        ledger_path_override=ledger,
        llm_call=lambda p: json.dumps(
            [_promotable_claim(0)], ensure_ascii=False),
    )
    assert out["status"] == ces.STATUS_COST_CAP_MONTHLY_PRE_ABORT
    assert out["warning_code"] == "cost_cap_exceeded_monthly"
    assert out["llm_calls"] == 0
    assert out["writes"] == 0
    assert out["monthly_cost_usd_so_far"] == 0.99


# ──────────────────────────────────────────────────────────────────
# Smoke 4 — dry_run_debug_path 실 path 검증 + invalid_raw_dump entry
# ──────────────────────────────────────────────────────────────────

def test_93a_dry_run_debug_path_under_debug_claims(tmp_path):
    """tmp_path/debug/claims/... 형태는 _validate_debug_path 통과 (D-3)."""
    debug_dir = tmp_path / "debug" / "claims"
    debug_dir.mkdir(parents=True, exist_ok=True)
    safe_path = debug_dir / "smoke_93a.json"

    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_synthetic_evidence(3),
        dry_run_debug_path=safe_path,
        llm_call=lambda p: json.dumps(
            [_promotable_claim(0)], ensure_ascii=False),
    )
    # 정상 진입 (ValueError 0)
    assert out["status"] in (
        ces.STATUS_PROMOTION_OUT_OF_BAND,  # 1 promote = 100% rate
        ces.STATUS_OK_PLAN_READY,
    )
    # write_invalid_dump=False default → invalid_raw_dump 미진입
    assert not any(
        w.get("kind") == "invalid_raw_dump" for w in out["would_save"]
    )
    # Commit 3 invariant — 실 file 미생성
    assert not safe_path.exists()


def test_93a_invalid_dump_entry_when_flag_and_invalid_present(tmp_path):
    """write_invalid_dump=True + invalid_count>0 → would_save 에 entry 추가."""
    debug_dir = tmp_path / "debug" / "claims"
    debug_dir.mkdir(parents=True, exist_ok=True)
    safe_path = debug_dir / "smoke_invalid.json"

    invalid_claim = {
        "claim_type": "INVALID_TYPE",
        "affected_assets": [
            {"asset_class": "국내주식", "direction": "positive"}
        ],
        "causal_chain": [{"source": "x", "target": "y", "relation": "raises"}],
        "direction": "positive",
        "horizon": "short",
        "confidence": 0.5,
        "salience": 0.5,
        "supporting_evidence_ids": ["art_x"],
        "counter_evidence_ids": [],
    }
    raw = json.dumps([_promotable_claim(0), invalid_claim], ensure_ascii=False)

    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_synthetic_evidence(3),
        write_canonical=True,
        write_invalid_dump=True,
        dry_run_debug_path=safe_path,
        llm_call=lambda p: raw,
    )
    dump_entries = [w for w in out["would_save"]
                    if w.get("kind") == "invalid_raw_dump"]
    assert len(dump_entries) == 1
    assert dump_entries[0]["enabled_in_this_commit"] is False
    assert dump_entries[0]["invalid_count"] >= 1
    # 실 file 미생성 (Commit 3 invariant — Commit 4 에서 활성화)
    assert not safe_path.exists()


# ──────────────────────────────────────────────────────────────────
# Smoke 5 — Failure matrix 대표 path
# ──────────────────────────────────────────────────────────────────

def test_93a_failure_matrix_f1_llm_api_failure():
    def _raise(p):
        raise RuntimeError("smoke mock llm failure")
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_synthetic_evidence(3),
        llm_call=_raise,
    )
    assert out["status"] == ces.STATUS_RUNNER_ABORTED
    assert out["warning_code"] == "llm_api_failure"
    assert out["writes"] == 0


def test_93a_failure_matrix_f7_cost_cap_pre_estimate():
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_synthetic_evidence(3),
        cost_cap_usd=0.000001,
        llm_call=lambda p: json.dumps(
            [_promotable_claim(0)], ensure_ascii=False),
    )
    assert out["status"] == ces.STATUS_COST_CAP_PRE_ABORT
    assert out["warning_code"] == "cost_cap_exceeded_estimate"
    assert out["llm_calls"] == 0
    assert out["writes"] == 0


def test_93a_failure_matrix_f4_no_valid_claims():
    invalid = {
        "claim_type": "BAD",
        "affected_assets": [{"asset_class": "국내주식",
                              "direction": "positive"}],
        "causal_chain": [{"source": "x", "target": "y", "relation": "raises"}],
        "direction": "positive",
        "horizon": "short",
        "confidence": 0.5,
        "salience": 0.5,
        "supporting_evidence_ids": ["a"],
        "counter_evidence_ids": [],
    }
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_synthetic_evidence(3),
        llm_call=lambda p: json.dumps([invalid], ensure_ascii=False),
    )
    assert out["status"] == ces.STATUS_NO_VALID_CLAIMS
    assert out["warning_code"] == "no_claims_extracted"
    assert out["writes"] == 0


# ──────────────────────────────────────────────────────────────────
# Smoke 6 — 9.2 fixture passthrough (gitignored, optional)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not FIXTURE_92.exists(),
    reason=f"9.2 fixture not present: {FIXTURE_92}",
)
def test_93a_92_fixture_plan_passthrough():
    """9.2 의 18 valid claims 를 build_promotion_plan 에 직접 inject.

    LLM 호출 0 (이미 산출된 claim list 입력). canonical_existing 미주입 →
    merge_conflict 0 가 정상.
    """
    data = json.loads(FIXTURE_92.read_text(encoding="utf-8"))
    extraction = data.get("extraction") or {}
    claims = extraction.get("claims") or []
    assert len(claims) == 18, (
        f"9.2 fixture 변형 — 18 claims 예상, 실 {len(claims)}"
    )

    plan = build_promotion_plan(claims, rule="auto")
    # 구조 sanity
    assert plan["input_count"] == 18
    assert "promoted_count" in plan
    assert "skipped_count" in plan
    assert "promotion_rate" in plan
    assert "rule_breakdown" in plan
    assert "skip_reasons" in plan
    assert "out_of_band" in plan
    assert "would_write" in plan
    assert "merge_conflicts" in plan
    assert plan["merge_conflicts"] == []  # canonical_existing 미주입
    assert plan["canonical_existing_count"] == 0
    # promoted_count 는 LLM 산출 wording variance 에 따라 변동 — 구조만 보장.
    assert 0 <= plan["promoted_count"] <= 18
    assert plan["promoted_count"] + plan["skipped_count"] == 18


# ──────────────────────────────────────────────────────────────────
# Smoke 7 — Step 2.7 default OFF + 보호 영역 invariant 재확인
# ──────────────────────────────────────────────────────────────────

PROTECTED_FILES = {
    "data/claims/2026-04.json": (
        "da3fed58512829099a624ddb5fc1c85f",
        "market_research/data/claims/2026-04.json",
    ),
    "_market.final.json": (
        "81eb876ba8b82b23a2a3dcec3de2f5bc",
        "market_research/data/report_output/2026-04/_market.final.json",
    ),
    "07G04.final.json": (
        "f522cd673c8df342c21459990e86eff1",
        "market_research/data/report_output/2026-04/07G04.final.json",
    ),
    "regime_memory.json": (
        "1ee7151c8c381217c7b34393b0054daf",
        "market_research/data/regime_memory.json",
    ),
}


def test_93a_step_27_default_off():
    """Commit 3 가 끝나도 daily_update Step 2.7 default 는 OFF."""
    assert ces.ENABLE_CLAIM_EXTRACTION is False


def test_93a_promotion_ledger_row_count_unchanged():
    """`_promotion_quality.jsonl` 의 row 수가 1 (R9-A.1 manual pilot) 그대로."""
    from market_research.analyze.claim_store import PROMOTION_LEDGER_PATH
    if not PROMOTION_LEDGER_PATH.exists():
        pytest.skip("promotion ledger 부재 (CI 환경 가능성)")
    rows = sum(1 for _ in PROMOTION_LEDGER_PATH.open(encoding="utf-8"))
    assert rows == 1, f"ledger row 수 invariant 위반: {rows} (예상 1)"


def test_93a_wiki_08_claims_count_unchanged():
    """운영 08_Claims md count 만 검증 — target_suffix 산출물 (`.{suffix}.md`)
    은 명시적 replay artifact 이므로 제외 (C4.1 격리 정책).

    Commit 5 갱신: 9.3 controlled write smoke 가 18 개 `.r9a4-replay.md` 를
    생성해도 운영 count 는 8 그대로여야 한다.
    """
    from market_research.wiki.paths import CLAIMS_WIKI_DIR
    if not CLAIMS_WIKI_DIR.exists():
        pytest.skip("08_Claims 디렉토리 부재")
    # 운영 파일 = `.<suffix>.md` 패턴이 아닌 base `.md` 만.
    operational = [
        f for f in CLAIMS_WIKI_DIR.glob("*.md")
        if f.name.count(".") == 1   # `{period}_claim_{h}.md` 만 (suffix 1개)
    ]
    md_count = len(operational)
    assert md_count == 8, (
        f"운영 08_Claims md 수 invariant 위반: {md_count} (예상 8). "
        f"replay artifact 는 별 카운트."
    )


@pytest.mark.parametrize("label", list(PROTECTED_FILES.keys()))
def test_93a_protected_file_md5_unchanged(label):
    expected, rel = PROTECTED_FILES[label]
    p = REPO_ROOT / rel
    if not p.exists():
        pytest.skip(f"보호 파일 부재: {rel}")
    actual = hashlib.md5(p.read_bytes()).hexdigest()
    assert actual == expected, (
        f"보호 파일 md5 변경: {label} 예상={expected} 실제={actual}"
    )


def test_93a_monthly_cap_constant_stable():
    """workorder §5 D-4 — MONTHLY_CAP_USD 는 1.0 상수."""
    assert MONTHLY_CAP_USD == 1.0
