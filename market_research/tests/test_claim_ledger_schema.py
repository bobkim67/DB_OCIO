# -*- coding: utf-8 -*-
"""R9-A.4 Commit 3 (C3-β) — ledger row schema + monthly cost compute 회귀.

file write 0 — tmp_path 로 row read 검증만.
"""
from __future__ import annotations

import json

from market_research.pipeline.claim_ledger_schema import (
    LEDGER_ROW_FIELDS,
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
