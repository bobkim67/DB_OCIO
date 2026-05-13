# -*- coding: utf-8 -*-
"""R9-A.4 Commit 3 (C3-β) — ledger row schema + monthly cost compute 회귀.

file write 0 — tmp_path 로 row read 검증만.
"""
from __future__ import annotations

import json

from market_research.pipeline.claim_ledger_schema import (
    LEDGER_ROW_FIELDS,
    LEDGER_ROW_FIELDS_C3,
    LEDGER_ROW_OPTIONAL_FIELDS_R9A22,
    MONITORING_MODE_VALUES,
    MONTHLY_CAP_USD,
    STABLE_CANDIDATE_COUNT_KEYS,
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

def test_c4_schema_fields_count_with_c3_subset():
    """C4.1 schema 는 33필드 (C4 initial 32 + isolated_write).

    C3 24필드는 처음 24 위치에 동일 순서로 정확한 subset.
    """
    assert len(LEDGER_ROW_FIELDS) == 33
    assert len(LEDGER_ROW_FIELDS_C3) == 24
    assert set(LEDGER_ROW_FIELDS_C3) <= set(LEDGER_ROW_FIELDS)
    # C3 의 모든 필드가 C4 의 처음 24 위치에 동일 순서 (key order 보존)
    assert LEDGER_ROW_FIELDS[:24] == LEDGER_ROW_FIELDS_C3


def test_c4_new_9_fields_distinct_from_c3():
    """C4 + C4.1 신규 9필드 (8 monitoring + 1 isolated_write)."""
    c4_only = set(LEDGER_ROW_FIELDS) - set(LEDGER_ROW_FIELDS_C3)
    expected_new = {
        "write_allowed", "write_block_reason", "allow_out_of_band",
        "write_claims", "monthly_cost_before",
        "monthly_cost_after_estimate", "candidate_count",
        "canonical_existing_conflict_count",
        "isolated_write",  # Commit 4.1
    }
    assert c4_only == expected_new


def test_c4_build_preview_returns_all_33_fields():
    """build_ledger_row_preview 가 default 호출에서도 33필드 모두 채움."""
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
    # Commit 4.1 — target_suffix=None default → isolated_write=False
    assert row["isolated_write"] is False


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


# ──────────────────────────────────────────────────────────────────
# R9-A.22B — Group monitoring traceability optional fields
# ──────────────────────────────────────────────────────────────────

def test_r9a22b_default_call_excludes_optional_fields():
    """default 호출은 33필드만 — optional field 키 자체가 row 에 없음.

    이 회귀가 깨지면 기존 `_promotion_quality.jsonl` 소비자 / 33필드 strict
    검증이 깨진다. 강조 항목: 기본 실행 시 기존 row 구조와 호환.
    """
    row = build_ledger_row_preview(period="2026-04")
    assert set(row.keys()) == set(LEDGER_ROW_FIELDS)
    assert len(row) == 33
    for opt in LEDGER_ROW_OPTIONAL_FIELDS_R9A22:
        assert opt not in row, (
            f"optional field {opt} must not appear in default row"
        )


def test_r9a22b_group_monitoring_summary_path_recorded():
    """group_monitoring_summary_path 전달 시 row 에 추가."""
    row = build_ledger_row_preview(
        period="2026-04",
        group_monitoring_summary_path=(
            "debug/claims/out/claim_group_monitoring_2026-04_daily.json"
        ),
    )
    assert "group_monitoring_summary_path" in row
    assert row["group_monitoring_summary_path"].endswith(
        "_2026-04_daily.json")
    # 다른 optional 은 여전히 부재
    for other in (
        "related_group_ids", "linked_wiki_claim_ids",
        "monitoring_mode", "stable_candidate_counts",
    ):
        assert other not in row


def test_r9a22b_related_group_ids_recorded():
    row = build_ledger_row_preview(
        period="2026-04",
        related_group_ids=["group:2026-04:cfee0ff342"],
    )
    assert row["related_group_ids"] == ["group:2026-04:cfee0ff342"]
    # str coercion 검증 (input 이 비-str 이라도 변환)
    row2 = build_ledger_row_preview(
        period="2026-04",
        related_group_ids=[1, "group:2026-04:cfee0ff342"],
    )
    assert row2["related_group_ids"] == ["1", "group:2026-04:cfee0ff342"]


def test_r9a22b_linked_wiki_claim_ids_recorded():
    row = build_ledger_row_preview(
        period="2026-04",
        linked_wiki_claim_ids=["de1729b413", "e78dc83a1e"],
    )
    assert row["linked_wiki_claim_ids"] == ["de1729b413", "e78dc83a1e"]


def test_r9a22b_monitoring_mode_recorded_and_validated():
    row = build_ledger_row_preview(
        period="2026-04",
        monitoring_mode="multi_run",
    )
    assert row["monitoring_mode"] == "multi_run"
    assert validate_ledger_row_preview(row) == []

    row2 = build_ledger_row_preview(
        period="2026-04",
        monitoring_mode="single_batch",
    )
    assert validate_ledger_row_preview(row2) == []


def test_r9a22b_stable_candidate_counts_recorded():
    counts = {
        "total_groups": "57",   # str → int coercion 검증
        "stable_candidates": 12,
        "strong_stable_candidates": 4,
        "within_run_duplicate_count": 0,
    }
    row = build_ledger_row_preview(
        period="2026-04",
        stable_candidate_counts=counts,
    )
    assert isinstance(row["stable_candidate_counts"], dict)
    # 권장 sub-key 는 int 로 coerce
    for k in STABLE_CANDIDATE_COUNT_KEYS:
        assert isinstance(row["stable_candidate_counts"][k], int)
    assert row["stable_candidate_counts"]["total_groups"] == 57


def test_r9a22b_full_traceability_payload_recorded():
    """5 field 모두 전달 — 38필드 (33 strict + 5 optional)."""
    row = build_ledger_row_preview(
        period="2026-04",
        group_monitoring_summary_path="debug/claims/out/x.json",
        related_group_ids=["group:2026-04:cfee0ff342"],
        linked_wiki_claim_ids=["de1729b413", "e78dc83a1e"],
        monitoring_mode="multi_run",
        stable_candidate_counts={"total_groups": 57},
    )
    assert set(row.keys()) >= set(LEDGER_ROW_FIELDS)
    assert set(row.keys()) - set(LEDGER_ROW_FIELDS) == set(
        LEDGER_ROW_OPTIONAL_FIELDS_R9A22)
    assert len(row) == 38
    assert validate_ledger_row_preview(row) == []


def test_r9a22b_validator_type_errors_on_bad_optional():
    """optional field 가 잘못된 타입이면 validate 가 errors 반환."""
    base = build_ledger_row_preview(period="2026-04")
    bad1 = {**base, "group_monitoring_summary_path": 42}
    assert any(
        e.startswith("type_error:group_monitoring_summary_path")
        for e in validate_ledger_row_preview(bad1)
    )
    bad2 = {**base, "related_group_ids": "not-a-list"}
    assert any(
        e.startswith("type_error:related_group_ids")
        for e in validate_ledger_row_preview(bad2)
    )
    bad3 = {**base, "linked_wiki_claim_ids": [1, 2, 3]}
    assert any(
        e.startswith("type_error:linked_wiki_claim_ids")
        for e in validate_ledger_row_preview(bad3)
    )
    bad4 = {**base, "monitoring_mode": "unknown_mode"}
    errs = validate_ledger_row_preview(bad4)
    assert any(e.startswith("value_error:monitoring_mode_invalid") for e in errs)
    bad5 = {**base, "stable_candidate_counts": "not a dict"}
    assert any(
        e.startswith("type_error:stable_candidate_counts")
        for e in validate_ledger_row_preview(bad5)
    )


def test_r9a22b_unknown_consumer_fields_pass_through_validator():
    """현재 _promotion_quality.jsonl 소비자가 unknown 키를 만났을 때 graceful
    해야 함. validate_ledger_row_preview 도 unknown 키는 무시한다."""
    row = build_ledger_row_preview(period="2026-04")
    row["future_metadata"] = {"foo": "bar"}
    assert validate_ledger_row_preview(row) == []
    # legacy 모드도 unknown 키 무시
    assert validate_ledger_row_preview(row, allow_legacy_c3=True) == []


def test_r9a22b_optional_fields_set_introspection():
    """LEDGER_ROW_OPTIONAL_FIELDS_R9A22 5종이 strict required 와 disjoint."""
    assert len(LEDGER_ROW_OPTIONAL_FIELDS_R9A22) == 5
    assert set(LEDGER_ROW_OPTIONAL_FIELDS_R9A22).isdisjoint(
        set(LEDGER_ROW_FIELDS))
    assert MONITORING_MODE_VALUES == frozenset({"single_batch", "multi_run"})


def test_r9a22b_jsonl_serialization_with_optional_fields(tmp_path):
    """append → read → 동일 row. unknown 소비자가 graceful 해야 한다는 정신
    검증 (file write 격리, 운영 ledger 무영향)."""
    row = build_ledger_row_preview(
        period="2026-04",
        group_monitoring_summary_path="debug/claims/out/x.json",
        monitoring_mode="single_batch",
        stable_candidate_counts={"total_groups": 5},
    )
    path = tmp_path / "_promotion_quality.test.jsonl"
    path.write_text(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    line = path.read_text(encoding="utf-8").strip()
    restored = json.loads(line)
    assert restored["group_monitoring_summary_path"] == row[
        "group_monitoring_summary_path"]
    assert restored["monitoring_mode"] == "single_batch"
    assert restored["stable_candidate_counts"]["total_groups"] == 5


def test_r9a22b_compute_monthly_cost_unaffected_by_optional_fields(tmp_path):
    """optional field 가 채워진 row 들이 ledger 에 섞여 있어도 cost 합산은
    동일. _promotion_quality.jsonl 소비자 (compute_monthly_cost_usd) 가 unknown
    key 에 graceful 한지 검증."""
    ledger = tmp_path / "_promotion_quality.jsonl"
    rows = [
        build_ledger_row_preview(
            period="2026-04", cost_usd=0.014, status="ok_plan_ready",
        ),
        build_ledger_row_preview(
            period="2026-04", cost_usd=0.020, status="ok_plan_ready",
            group_monitoring_summary_path="debug/claims/out/x.json",
            related_group_ids=["group:2026-04:cfee0ff342"],
            monitoring_mode="multi_run",
        ),
    ]
    with ledger.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    total = compute_monthly_cost_usd("2026-04", ledger_path=ledger)
    assert total == 0.034  # 0.014 + 0.020, optional fields 무관
