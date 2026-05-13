# -*- coding: utf-8 -*-
"""R9-A.17 — claim_group_monitoring utility unit tests.

LLM 0, filesystem write 0. R9-A.16 fixture-level 재현은 별도 smoke
(debug/claims/r9a17_*) 에서. 본 unit test 는 utility 의 결정적 동작 검증.
"""
from __future__ import annotations

import pytest

from market_research.pipeline.claim_group_monitoring import (
    DEFAULT_STABLE_MIN_RUNS,
    DEFAULT_STRONG_MIN_RUNS,
    build_claim_group_monitoring_summary,
)


def _claim(
    *,
    run_id: str,
    group_id: str,
    claim_id: str,
    text: str = "sample claim text",
    assets=None,
    evset_hash: str = "evh000",
    direction: str = "positive",
    horizon: str = "short",
    claim_type: str = "outlook_view",
    promotion_rule: str | None = None,
    promoted: bool = False,
) -> dict:
    return {
        "run_id": run_id,
        "canonical_group_id": group_id,
        "claim_id": claim_id,
        "claim_text": text,
        "affected_assets": assets if assets is not None else ["국내주식"],
        "evidence_set_hash": evset_hash,
        "direction": direction,
        "horizon": horizon,
        "claim_type": claim_type,
        "promotion_rule": promotion_rule,
        "promoted": promoted,
    }


# ──────────────────────────────────────────────────────────────────
# Empty / minimal input
# ──────────────────────────────────────────────────────────────────

def test_empty_input():
    s = build_claim_group_monitoring_summary([])
    assert s["total_groups"] == 0
    assert s["stable_candidates"] == 0
    assert s["strong_stable_candidates"] == 0
    assert s["total_claims"] == 0
    assert s["total_runs"] == 0
    assert s["groups"] == []
    assert s["overmerge_warnings"] == []


def test_default_thresholds():
    s = build_claim_group_monitoring_summary([])
    assert s["stable_min_runs"] == DEFAULT_STABLE_MIN_RUNS == 2
    assert s["strong_min_runs"] == DEFAULT_STRONG_MIN_RUNS == 3


def test_single_claim_minimal():
    s = build_claim_group_monitoring_summary([
        _claim(run_id="r1", group_id="group:2026-04:aaaaaaaa01",
               claim_id="claim:2026-04:cid0000001"),
    ])
    assert s["total_groups"] == 1
    assert s["stable_candidates"] == 0   # run_count=1 < 2
    assert s["strong_stable_candidates"] == 0
    g = s["groups"][0]
    assert g["canonical_group_id"] == "group:2026-04:aaaaaaaa01"
    assert g["run_count"] == 1
    assert g["claim_count"] == 1
    assert g["stable_candidate"] is False
    assert g["strong_stable_candidate"] is False


# ──────────────────────────────────────────────────────────────────
# Stable / strong stable thresholds (R9-A.16 재현 기본 패턴)
# ──────────────────────────────────────────────────────────────────

def test_stable_threshold_run_count_2():
    """같은 group_id 가 2 run 에서 등장 → stable, strong 아님."""
    claims = [
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1"),
        _claim(run_id="r2", group_id="group:p:gA",
               claim_id="claim:p:cA2"),
    ]
    s = build_claim_group_monitoring_summary(claims)
    assert s["total_groups"] == 1
    assert s["stable_candidates"] == 1
    assert s["strong_stable_candidates"] == 0
    g = s["groups"][0]
    assert g["stable_candidate"] is True
    assert g["strong_stable_candidate"] is False
    assert g["run_count"] == 2
    assert g["claim_count"] == 2
    assert g["runs_touched"] == ["r1", "r2"]


def test_strong_stable_threshold_run_count_3():
    """3 run 에서 등장 → strong stable."""
    claims = [
        _claim(run_id=f"r{i}", group_id="group:p:gA",
               claim_id=f"claim:p:cA{i}")
        for i in range(1, 4)
    ]
    s = build_claim_group_monitoring_summary(claims)
    assert s["stable_candidates"] == 1
    assert s["strong_stable_candidates"] == 1
    g = s["groups"][0]
    assert g["strong_stable_candidate"] is True


def test_all_run_group_count():
    """run_count == total_runs 인 group 카운트."""
    claims = (
        [_claim(run_id=f"r{i}", group_id="group:p:gA",
                claim_id=f"claim:p:cA{i}") for i in range(1, 4)]
        + [_claim(run_id="r1", group_id="group:p:gB",
                  claim_id="claim:p:cB1")]
    )
    s = build_claim_group_monitoring_summary(claims)
    # 3 runs 총, gA 는 모든 run 등장, gB 는 1 run 만
    assert s["total_runs"] == 3
    assert s["all_run_groups"] == 1   # gA 만


# ──────────────────────────────────────────────────────────────────
# Custom thresholds
# ──────────────────────────────────────────────────────────────────

def test_custom_thresholds():
    claims = [
        _claim(run_id=f"r{i}", group_id="group:p:gA",
               claim_id=f"claim:p:cA{i}")
        for i in range(1, 4)
    ]
    s = build_claim_group_monitoring_summary(
        claims, stable_min_runs=3, strong_min_runs=5,
    )
    assert s["stable_candidates"] == 1     # run_count 3 ≥ 3
    assert s["strong_stable_candidates"] == 0  # 3 < 5
    assert s["stable_min_runs"] == 3
    assert s["strong_min_runs"] == 5


# ──────────────────────────────────────────────────────────────────
# Overmerge guardrail (워크오더 §6)
# ──────────────────────────────────────────────────────────────────

def test_overmerge_warning_same_run_same_group():
    """같은 run 안에서 같은 canonical_group_id 가 2개 이상 → warning."""
    claims = [
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1"),
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA2"),
    ]
    s = build_claim_group_monitoring_summary(claims)
    assert s["within_run_duplicate_count"] == 1
    assert len(s["overmerge_warnings"]) == 1
    w = s["overmerge_warnings"][0]
    assert w["run_id"] == "r1"
    assert w["canonical_group_id"] == "group:p:gA"
    assert w["duplicate_claim_count"] == 2
    # group dict 의 overmerge_warning flag 도 True
    g = s["groups"][0]
    assert g["overmerge_warning"] is True


def test_no_overmerge_different_runs():
    """다른 run 의 같은 group_id 는 overmerge X."""
    claims = [
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1"),
        _claim(run_id="r2", group_id="group:p:gA",
               claim_id="claim:p:cA2"),
    ]
    s = build_claim_group_monitoring_summary(claims)
    assert s["within_run_duplicate_count"] == 0
    assert s["overmerge_warnings"] == []
    assert s["groups"][0]["overmerge_warning"] is False


# ──────────────────────────────────────────────────────────────────
# Stable candidate sorting (워크오더 §5)
# ──────────────────────────────────────────────────────────────────

def test_strong_stable_sorts_above_stable():
    """strong stable 이 일반 stable 위로."""
    claims = (
        # 일반 stable (run_count=2)
        [_claim(run_id="r1", group_id="group:p:stable",
                claim_id="claim:p:s1")]
        + [_claim(run_id="r2", group_id="group:p:stable",
                  claim_id="claim:p:s2")]
        # strong stable (run_count=3) — list 에서 뒤에 위치
        + [_claim(run_id=f"r{i}", group_id="group:p:strong",
                  claim_id=f"claim:p:str{i}") for i in range(1, 4)]
    )
    s = build_claim_group_monitoring_summary(claims)
    # 첫 group 은 strong, 두 번째는 stable
    assert s["groups"][0]["canonical_group_id"] == "group:p:strong"
    assert s["groups"][1]["canonical_group_id"] == "group:p:stable"
    assert s["groups"][0]["strong_stable_candidate"] is True
    assert s["groups"][1]["strong_stable_candidate"] is False


def test_run_count_desc_within_same_tier():
    """같은 tier (stable / strong) 안에서는 run_count 내림차순."""
    claims = (
        # stable (run=2)
        [_claim(run_id=f"r{i}", group_id="group:p:run2",
                claim_id=f"claim:p:r2_{i}") for i in range(1, 3)]
        # stable (run=4)
        + [_claim(run_id=f"r{i}", group_id="group:p:run4",
                  claim_id=f"claim:p:r4_{i}") for i in range(1, 5)]
        # stable (run=3)
        + [_claim(run_id=f"r{i}", group_id="group:p:run3",
                  claim_id=f"claim:p:r3_{i}") for i in range(1, 4)]
    )
    s = build_claim_group_monitoring_summary(claims)
    # 모두 strong (run≥3) 이거나 stable — 정렬 순서: run_count desc
    # run=4 (strong), run=3 (strong), run=2 (stable)
    ordered = [g["canonical_group_id"] for g in s["groups"]]
    assert ordered == ["group:p:run4", "group:p:run3", "group:p:run2"]


def test_promoted_rate_secondary_sort():
    """같은 tier + 같은 run_count 면 promoted_rate desc."""
    claims_high_promote = [
        _claim(run_id=f"r{i}", group_id="group:p:gHigh",
               claim_id=f"claim:p:gH{i}", promoted=True)
        for i in range(1, 3)
    ]
    claims_low_promote = [
        _claim(run_id=f"r{i}", group_id="group:p:gLow",
               claim_id=f"claim:p:gL{i}", promoted=False)
        for i in range(1, 3)
    ]
    s = build_claim_group_monitoring_summary(
        claims_low_promote + claims_high_promote
    )
    # 둘 다 stable (run=2), promoted_rate 1.0 > 0.0 → high 가 위
    assert s["groups"][0]["canonical_group_id"] == "group:p:gHigh"
    assert s["groups"][1]["canonical_group_id"] == "group:p:gLow"


# ──────────────────────────────────────────────────────────────────
# Enum distribution / variance
# ──────────────────────────────────────────────────────────────────

def test_enum_distribution_multi_value_group():
    """같은 group 안 다른 enum 값 → distribution 정확 집계 + variance 플래그."""
    claims = [
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1",
               direction="positive", horizon="short", claim_type="risk"),
        _claim(run_id="r2", group_id="group:p:gA",
               claim_id="claim:p:cA2",
               direction="negative", horizon="medium",
               claim_type="event_to_macro"),
    ]
    s = build_claim_group_monitoring_summary(claims)
    g = s["groups"][0]
    assert g["direction_distribution"] == {"positive": 1, "negative": 1}
    assert g["horizon_distribution"] == {"short": 1, "medium": 1}
    assert g["claim_type_distribution"] == {
        "risk": 1, "event_to_macro": 1
    }
    assert g["has_direction_variance"] is True
    assert g["has_horizon_variance"] is True
    assert g["has_claim_type_variance"] is True


def test_enum_distribution_single_value_no_variance():
    """모든 claim 의 enum 동일 → variance 플래그 False."""
    claims = [
        _claim(run_id=f"r{i}", group_id="group:p:gA",
               claim_id=f"claim:p:cA{i}",
               direction="positive", horizon="short", claim_type="risk")
        for i in range(1, 4)
    ]
    s = build_claim_group_monitoring_summary(claims)
    g = s["groups"][0]
    assert g["direction_distribution"] == {"positive": 3}
    assert g["has_direction_variance"] is False
    assert g["has_horizon_variance"] is False
    assert g["has_claim_type_variance"] is False


def test_promotion_rule_distribution():
    """promotion_rule 분포 집계."""
    claims = [
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1", promotion_rule="A", promoted=True),
        _claim(run_id="r2", group_id="group:p:gA",
               claim_id="claim:p:cA2", promotion_rule="B", promoted=True),
        _claim(run_id="r3", group_id="group:p:gA",
               claim_id="claim:p:cA3", promotion_rule=None,
               promoted=False),
    ]
    s = build_claim_group_monitoring_summary(claims)
    g = s["groups"][0]
    assert g["promotion_rule_distribution"] == {"A": 1, "B": 1, "None": 1}
    assert g["promoted_count"] == 2
    assert g["promoted_rate"] == round(2/3, 4)


# ──────────────────────────────────────────────────────────────────
# Representative claim selection (워크오더 §4)
# ──────────────────────────────────────────────────────────────────

def test_representative_prefers_promoted():
    """promoted=True claim 이 우선."""
    claims = [
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1",
               text="긴 텍스트인데 promoted 아님 매우매우 긴 텍스트",
               promoted=False),
        _claim(run_id="r2", group_id="group:p:gA",
               claim_id="claim:p:cA2",
               text="짧은 promoted 텍스트", promoted=True),
    ]
    s = build_claim_group_monitoring_summary(claims)
    assert s["groups"][0]["representative_claim"] == "짧은 promoted 텍스트"


def test_representative_longest_when_no_promoted():
    """promoted 없으면 가장 긴 text 선택."""
    claims = [
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1",
               text="짧은 a", promoted=False),
        _claim(run_id="r2", group_id="group:p:gA",
               claim_id="claim:p:cA2",
               text="가장 긴 텍스트 — 워크오더 §4 우선순위 2",
               promoted=False),
        _claim(run_id="r3", group_id="group:p:gA",
               claim_id="claim:p:cA3",
               text="중간 길이", promoted=False),
    ]
    s = build_claim_group_monitoring_summary(claims)
    rep = s["groups"][0]["representative_claim"]
    assert "가장 긴 텍스트" in rep


def test_representative_longest_among_promoted():
    """promoted=True 중 가장 긴 text."""
    claims = [
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1",
               text="짧 promoted", promoted=True),
        _claim(run_id="r2", group_id="group:p:gA",
               claim_id="claim:p:cA2",
               text="긴 promoted 텍스트 — 더 정보 풍부", promoted=True),
        _claim(run_id="r3", group_id="group:p:gA",
               claim_id="claim:p:cA3",
               text="가장 긴 텍스트인데 promoted 아님 매우 긴 ",
               promoted=False),
    ]
    s = build_claim_group_monitoring_summary(claims)
    rep = s["groups"][0]["representative_claim"]
    assert "긴 promoted 텍스트" in rep
    # promoted 아닌 가장 긴 것은 선택되지 않음
    assert "promoted 아님" not in rep


# ──────────────────────────────────────────────────────────────────
# Runs ordering / first/last seen
# ──────────────────────────────────────────────────────────────────

def test_runs_touched_insertion_ordered():
    """runs_touched 는 등장 순서 보존, dedup."""
    claims = [
        _claim(run_id="r3", group_id="group:p:gA",
               claim_id="claim:p:cA3a"),
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1"),
        _claim(run_id="r3", group_id="group:p:gA",
               claim_id="claim:p:cA3b"),
        _claim(run_id="r2", group_id="group:p:gA",
               claim_id="claim:p:cA2"),
    ]
    s = build_claim_group_monitoring_summary(claims)
    g = s["groups"][0]
    # 등장 순서: r3, r1, r2 (r3 중복 제거)
    assert g["runs_touched"] == ["r3", "r1", "r2"]
    assert g["first_seen_run"] == "r3"
    assert g["last_seen_run"] == "r2"
    assert g["run_count"] == 3


# ──────────────────────────────────────────────────────────────────
# Custom run_id_field
# ──────────────────────────────────────────────────────────────────

def test_custom_run_id_field():
    """run_id_field 커스터마이즈 — 다른 field 이름 사용."""
    claims = [
        {**_claim(run_id="ignore", group_id="group:p:gA",
                  claim_id="claim:p:cA1"),
         "batch_id": "b1"},
        {**_claim(run_id="ignore", group_id="group:p:gA",
                  claim_id="claim:p:cA2"),
         "batch_id": "b2"},
    ]
    s = build_claim_group_monitoring_summary(
        claims, run_id_field="batch_id"
    )
    g = s["groups"][0]
    assert g["runs_touched"] == ["b1", "b2"]
    assert g["run_count"] == 2


# ──────────────────────────────────────────────────────────────────
# Robustness — non-dict / missing fields
# ──────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────
# R9-A.19 — monitoring_mode semantics
# ──────────────────────────────────────────────────────────────────

def test_r9a19_default_mode_is_multi_run():
    """default monitoring_mode 는 'multi_run' — backward compat (R9-A.17
    호출자들의 의도)."""
    from market_research.pipeline.claim_group_monitoring import (
        DEFAULT_MONITORING_MODE, MONITORING_MODE_MULTI_RUN,
    )
    assert DEFAULT_MONITORING_MODE == MONITORING_MODE_MULTI_RUN
    s = build_claim_group_monitoring_summary([])
    assert s["monitoring_mode"] == "multi_run"
    assert s["stable_candidate_enabled"] is True
    assert s["within_run_duplicate_semantics"] == "overmerge_warning"


def test_r9a19_single_batch_mode_semantics():
    """single_batch mode — stable disabled, within_dup 는 diagnostic 만."""
    from market_research.pipeline.claim_group_monitoring import (
        MONITORING_MODE_SINGLE_BATCH,
    )
    s = build_claim_group_monitoring_summary(
        [], monitoring_mode=MONITORING_MODE_SINGLE_BATCH,
    )
    assert s["monitoring_mode"] == "single_batch"
    assert s["stable_candidate_enabled"] is False
    assert s["within_run_duplicate_semantics"] == (
        "same_batch_repeated_group_diagnostic"
    )
    assert "single batch" in s["run_count_interpretation"] or \
           "reference-only" in s["run_count_interpretation"]


def test_r9a19_multi_run_mode_explicit():
    """multi_run mode 명시 — default 와 동일."""
    from market_research.pipeline.claim_group_monitoring import (
        MONITORING_MODE_MULTI_RUN,
    )
    s = build_claim_group_monitoring_summary(
        [], monitoring_mode=MONITORING_MODE_MULTI_RUN,
    )
    assert s["monitoring_mode"] == "multi_run"
    assert s["stable_candidate_enabled"] is True
    assert s["within_run_duplicate_semantics"] == "overmerge_warning"


def test_r9a19_invalid_mode_raises_valueerror():
    """ALLOWED_MONITORING_MODES 외 값 → ValueError."""
    with pytest.raises(ValueError, match="invalid monitoring_mode"):
        build_claim_group_monitoring_summary([], monitoring_mode="bogus")
    with pytest.raises(ValueError):
        build_claim_group_monitoring_summary([], monitoring_mode="")


def test_r9a19_mode_does_not_change_count_metrics():
    """mode 변경은 stable_count 등의 numeric 계산 결과를 바꾸지 않는다.

    mode 는 해석 layer 만 영향 — 같은 input 이면 두 mode 모두 같은
    stable_candidates / strong_stable_candidates / within_run_duplicate
    값을 산출 (단 stable_candidate_enabled 만 다름).
    """
    from market_research.pipeline.claim_group_monitoring import (
        MONITORING_MODE_MULTI_RUN, MONITORING_MODE_SINGLE_BATCH,
    )
    # 3 runs 에 같은 group 등장 → multi_run 에서는 stable+strong, single_batch
    # 에서도 numeric 동일하지만 stable_candidate_enabled 만 False.
    claims = [
        _claim(run_id=f"r{i}", group_id="group:p:gA",
               claim_id=f"claim:p:cA{i}")
        for i in range(1, 4)
    ]
    s_multi = build_claim_group_monitoring_summary(
        claims, monitoring_mode=MONITORING_MODE_MULTI_RUN,
    )
    s_single = build_claim_group_monitoring_summary(
        claims, monitoring_mode=MONITORING_MODE_SINGLE_BATCH,
    )
    # numeric 동일
    for k in ("total_groups", "stable_candidates",
              "strong_stable_candidates", "within_run_duplicate_count",
              "promoted_groups"):
        assert s_multi[k] == s_single[k], f"mode 가 {k} 를 변경시킴"
    # semantics flag 만 다름
    assert s_multi["stable_candidate_enabled"] is True
    assert s_single["stable_candidate_enabled"] is False
    assert s_multi["within_run_duplicate_semantics"] != \
           s_single["within_run_duplicate_semantics"]


def test_r9a19_single_batch_within_dup_diagnostic():
    """single_batch mode 에서 같은 run + 같은 group 의 multi-claim 은
    overmerge 가 아니라 same-batch repeated group diagnostic 으로 분류."""
    from market_research.pipeline.claim_group_monitoring import (
        MONITORING_MODE_SINGLE_BATCH,
    )
    claims = [
        _claim(run_id="batch1", group_id="group:p:gA",
               claim_id="claim:p:c1"),
        _claim(run_id="batch1", group_id="group:p:gA",
               claim_id="claim:p:c2"),
    ]
    s = build_claim_group_monitoring_summary(
        claims, monitoring_mode=MONITORING_MODE_SINGLE_BATCH,
    )
    # numeric 은 그대로 — within_run_duplicate_count=1
    assert s["within_run_duplicate_count"] == 1
    # 그러나 semantics label 이 단순 diagnostic
    assert s["within_run_duplicate_semantics"] == (
        "same_batch_repeated_group_diagnostic"
    )


def test_r9a19_render_markdown_shows_mode_banner():
    """render_monitoring_markdown 가 mode 를 표시. single_batch 는 경고 박스."""
    from market_research.pipeline.claim_group_monitoring import (
        MONITORING_MODE_SINGLE_BATCH,
        render_monitoring_markdown,
    )
    s_single = build_claim_group_monitoring_summary(
        [], monitoring_mode=MONITORING_MODE_SINGLE_BATCH,
    )
    md = render_monitoring_markdown("2026-04", "test", s_single)
    assert "single_batch" in md
    assert "stable_candidate_enabled" in md
    assert "monitoring_mode" in md
    # single_batch 경고 박스
    assert "single_batch mode" in md or "참고값" in md

    s_multi = build_claim_group_monitoring_summary([])
    md_multi = render_monitoring_markdown("2026-04", "test", s_multi)
    assert "multi_run" in md_multi
    # multi_run 에는 single_batch 경고 박스 없음
    assert "single_batch mode" not in md_multi


def test_non_dict_entries_skipped():
    claims = [
        _claim(run_id="r1", group_id="group:p:gA",
               claim_id="claim:p:cA1"),
        "not a dict",
        None,
        {"no_group_id": True},   # missing canonical_group_id → skip
    ]
    s = build_claim_group_monitoring_summary(claims)
    # non-dict 항목 ("not a dict", None) skip → list 4 중 dict 2 만 카운트
    # 그 중 1 개는 canonical_group_id 없어 group aggregation 에서도 skip,
    # 다만 total_claims 는 dict 카운트
    assert s["total_groups"] == 1
    assert s["total_claims"] == 2   # _claim 1 + dict-without-gid 1
    # group 에는 group_id 있는 것만
    assert s["groups"][0]["claim_count"] == 1
