# -*- coding: utf-8 -*-
"""R9-A.4 Commit 3 (C3-β) — ledger row schema + monthly cost compute 회귀.

file write 0 — tmp_path 로 row read 검증만.
"""
from __future__ import annotations

import json

from market_research.pipeline.claim_ledger_schema import (
    LEDGER_ROW_FIELDS,
    LEDGER_ROW_FIELDS_C3,
    MONTHLY_CAP_USD,
    build_ledger_row_preview,
    compute_monthly_cost_usd,
    validate_ledger_row_preview,
)


# ──────────────────────────────────────────────────────────────────
# Case 1 — 정상 row schema (필수 24 필드 모두 채움)
# ──────────────────────────────────────────────────────────────────

def test_case1_full_row_schema():
    row = build_ledger_row_preview(
        period="2026-04",
        input_count=50,
        valid_claim_count=18,
        invalid_claim_count=0,
        promoted_count=8,
        skipped_count=10,
        promotion_rate=44.4,
        rule="auto",
        rule_breakdown={"A": 2, "B": 6, "C": 0},
        skip_reasons={"rule_a_b_unmet": 10},
        cost_usd=0.0138,
        monthly_cost_usd_so_far=0.0138,
        dry_run=True,
        write_canonical=False,
        status="ok_plan_ready",
        target_suffix=None,
    )
    # 24 fields present
    assert set(LEDGER_ROW_FIELDS).issubset(row.keys())
    assert len(row) == len(LEDGER_ROW_FIELDS)
    # 타입 안정성
    assert isinstance(row["input_count"], int)
    assert isinstance(row["cost_usd"], float)
    assert isinstance(row["dry_run"], bool)
    assert row["abort_reason"] is None
    assert validate_ledger_row_preview(row) == []
    # serializable
    s = json.dumps(row, ensure_ascii=False, sort_keys=True)
    assert "ok_plan_ready" in s


# ──────────────────────────────────────────────────────────────────
# Case 2 — R9-A.2 manual pilot row 와 호환 (filter 가 분리)
# ──────────────────────────────────────────────────────────────────

def test_case2_manual_pilot_row_does_not_contribute(tmp_path):
    ledger = tmp_path / "_promotion_quality.jsonl"
    # R9-A.1 manual pilot row (cost_usd 없음, source/extractor 다름)
    r9a1_row = {
        "ts": "2026-05-08T09:21:05",
        "period": "2026-04",
        "rule": "auto",
        "input_count": 22,
        "promoted_count": 8,
        "skipped_count": 14,
        "skip_reasons": {"rule_a_b_unmet": 14},
        "rule_breakdown": {"A": 2, "B": 6, "C": 0},
        "extractor_version": "r9a.1-haiku",
        "source": "manual_pilot_r9a1",
        "out_of_band_override": False,
    }
    ledger.write_text(
        json.dumps(r9a1_row, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    total = compute_monthly_cost_usd(
        "2026-04", ledger_path=ledger,
    )
    # R9-A.1 source/extractor 와 default filter 가 다름 → 0 누적
    assert total == 0.0


# ──────────────────────────────────────────────────────────────────
# Case 3 — monthly_cost_usd_so_far 누적 (동일 month + source filter)
# ──────────────────────────────────────────────────────────────────

def test_case3_monthly_cost_accumulation(tmp_path):
    ledger = tmp_path / "_promotion_quality.jsonl"
    rows = [
        # 2026-04 r9a.4 → 합산 대상
        {"period": "2026-04", "source": "daily_update_r9a4",
         "extractor_version": "r9a.4-haiku", "cost_usd": 0.014},
        {"period": "2026-04", "source": "daily_update_r9a4",
         "extractor_version": "r9a.4-haiku", "cost_usd": 0.020},
        # 2026-05 → 다른 month, 제외
        {"period": "2026-05", "source": "daily_update_r9a4",
         "extractor_version": "r9a.4-haiku", "cost_usd": 0.100},
        # 동일 month 이지만 manual_pilot — 제외
        {"period": "2026-04", "source": "manual_pilot_r9a1",
         "extractor_version": "r9a.1-haiku", "cost_usd": 0.500},
    ]
    with ledger.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = compute_monthly_cost_usd("2026-04", ledger_path=ledger)
    assert total == 0.034  # 0.014 + 0.020


def test_case3b_missing_ledger_file_returns_zero(tmp_path):
    missing = tmp_path / "nonexistent.jsonl"
    assert compute_monthly_cost_usd("2026-04", ledger_path=missing) == 0.0


# ──────────────────────────────────────────────────────────────────
# Case 4 — ledger row preview vs actual (Commit 3 단계 actual=None)
# ──────────────────────────────────────────────────────────────────

def test_case4_preview_does_not_write_anywhere(tmp_path):
    """build_ledger_row_preview 만 호출 — file write 0 보장."""
    ledger = tmp_path / "_promotion_quality.jsonl"
    assert not ledger.exists()

    row = build_ledger_row_preview(
        period="2026-04",
        ts="2026-05-09T10:00:00",
        cost_usd=0.0138,
        status="ok_plan_ready",
    )

    # 호출 이후에도 ledger file 미생성 (Commit 3 invariant)
    assert not ledger.exists()
    assert row["status"] == "ok_plan_ready"
    assert row["dry_run"] is True  # default


def test_validate_row_detects_missing_fields():
    bad = {"ts": "2026-05-09T10:00:00", "period": "2026-04"}
    errs = validate_ledger_row_preview(bad)
    # 22 필드 누락
    assert any(e.startswith("missing_field:") for e in errs)
    assert "missing_field:source" in errs


def test_monthly_cap_constant():
    assert MONTHLY_CAP_USD == 1.0


# ──────────────────────────────────────────────────────────────────
# Commit 4 — schema 24 → 32 backward compatibility
# ──────────────────────────────────────────────────────────────────

def test_c4_schema_fields_count_32_with_c3_subset():
    """C4 schema 는 32필드. C3 24필드는 정확한 subset."""
    assert len(LEDGER_ROW_FIELDS) == 32
    assert len(LEDGER_ROW_FIELDS_C3) == 24
    assert set(LEDGER_ROW_FIELDS_C3) <= set(LEDGER_ROW_FIELDS)
    # C3 의 모든 필드가 C4 의 처음 24 위치에 동일 순서 (key order 보존)
    assert LEDGER_ROW_FIELDS[:24] == LEDGER_ROW_FIELDS_C3


def test_c4_new_8_fields_distinct_from_c3():
    """C4 신규 8필드 — 8필드 모두 명확."""
    c4_only = set(LEDGER_ROW_FIELDS) - set(LEDGER_ROW_FIELDS_C3)
    expected_new = {
        "write_allowed", "write_block_reason", "allow_out_of_band",
        "write_claims", "monthly_cost_before",
        "monthly_cost_after_estimate", "candidate_count",
        "canonical_existing_conflict_count",
    }
    assert c4_only == expected_new


def test_c4_build_preview_returns_all_32_fields():
    """build_ledger_row_preview 가 default 호출에서도 32필드 모두 채움."""
    row = build_ledger_row_preview(period="2026-04")
    assert set(row.keys()) == set(LEDGER_ROW_FIELDS)
    # 신규 8필드 default 검증
    assert row["write_allowed"] is False
    assert row["write_block_reason"] is None
    assert row["allow_out_of_band"] is False
    assert row["write_claims"] is False
    assert row["monthly_cost_before"] == 0.0
    assert row["monthly_cost_after_estimate"] == 0.0
    assert row["candidate_count"] == 0
    assert row["canonical_existing_conflict_count"] == 0


def test_c4_legacy_c3_row_validates_with_allow_legacy_flag():
    """C3 24필드 row 가 allow_legacy_c3=True 로 validate 통과 (graceful read).

    사용자 강조 항목 — 운영 ledger 에 C3 row 가 섞여 있어도 read 측이 깨지지
    않아야 함. Commit 4 신규 row 는 strict=32 로 검증, 기존 row 는 graceful.
    """
    # C3 24필드 row 직접 구성 — _to_int/_to_float 으로 정상 타입
    c3_row = {
        "ts": "2026-05-08T09:21:05",
        "period": "2026-04",
        "source": "manual_pilot_r9a1",
        "extractor_version": "r9a.1-haiku",
        "input_count": 22,
        "valid_claim_count": 22,
        "invalid_claim_count": 0,
        "promoted_count": 8,
        "skipped_count": 14,
        "promotion_rate": 36.36,
        "rule": "auto",
        "rule_breakdown": {"A": 2, "B": 6, "C": 0},
        "skip_reasons": {"rule_a_b_unmet": 14},
        "cost_usd": 0.0,
        "monthly_cost_usd_so_far": 0.0,
        "dry_run": False,
        "write_canonical": True,
        "write_wiki": True,
        "write_ledger": True,
        "status": "ok_plan_ready",
        "abort_reason": None,
        "warnings": [],
        "out_of_band_override": False,
        "target_suffix": None,
    }
    assert set(c3_row.keys()) == set(LEDGER_ROW_FIELDS_C3)

    # legacy 모드 → 빈 list (PASS)
    assert validate_ledger_row_preview(c3_row, allow_legacy_c3=True) == []

    # strict 모드 → 신규 8필드 missing 으로 errors
    errs_strict = validate_ledger_row_preview(c3_row, allow_legacy_c3=False)
    assert any("missing_field:write_allowed" in e for e in errs_strict)
    assert any("missing_field:write_block_reason" in e for e in errs_strict)


def test_c4_c4_row_validates_strict_mode():
    """Commit 4 신규 row 는 strict 모드에서 PASS."""
    row = build_ledger_row_preview(period="2026-04")
    assert validate_ledger_row_preview(row, allow_legacy_c3=False) == []
    assert validate_ledger_row_preview(row, allow_legacy_c3=True) == []


def test_c4_monthly_cost_accumulates_both_c3_and_c4_rows(tmp_path):
    """compute_monthly_cost_usd 가 C3/C4 row 모두 read — source/extractor filter
    가 manual_pilot 만 자연 제외 (cost_usd 필드 누락 graceful)."""
    ledger = tmp_path / "_promotion_quality.jsonl"
    rows = [
        # C3 형태 (24필드, cost_usd 0.014) — daily_update_r9a4 → 합산 대상
        {"period": "2026-04", "source": "daily_update_r9a4",
         "extractor_version": "r9a.4-haiku", "cost_usd": 0.014,
         # 나머지 C3 필드는 일부만 (실제 운영 row 는 24 모두 채움)
         },
        # C4 형태 (32필드) — daily_update_r9a4 → 합산
        build_ledger_row_preview(
            period="2026-04", cost_usd=0.020, status="ok_plan_ready",
        ),
        # manual_pilot — filter 가 자연 제외
        {"period": "2026-04", "source": "manual_pilot_r9a1",
         "extractor_version": "r9a.1-haiku"},
    ]
    with ledger.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    total = compute_monthly_cost_usd("2026-04", ledger_path=ledger)
    assert total == 0.034  # 0.014 + 0.020 (manual_pilot 제외)


def test_c4_validate_invalid_legacy_field_still_errors():
    """C3 row 인데 source 누락 등 — allow_legacy_c3 에서도 errors."""
    bad = {"ts": "2026-05-09T10:00:00", "period": "2026-04"}
    errs = validate_ledger_row_preview(bad, allow_legacy_c3=True)
    assert "missing_field:source" in errs
    # 신규 C4 필드 누락은 graceful (legacy 모드)
    assert not any("missing_field:write_allowed" in e for e in errs)
