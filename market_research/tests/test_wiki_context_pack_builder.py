# -*- coding: utf-8 -*-
"""R9-B.2 — Tests for wiki_context_pack_builder.

LLM 호출 0, 운영 파일 변경 0. 모든 wiki 입력은 tmp_path 로 격리.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_research.report import wiki_context_pack_builder as wcp


# ──────────────────────────────────────────────────────────────────
# Fixtures — synthetic wiki tree
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def synthetic_wiki(tmp_path: Path) -> Path:
    """Build a minimal wiki tree with one page per directory.

    Returns the wiki_root path (== tmp_path / "wiki").
    """
    wiki = tmp_path / "wiki"
    for d in (
        "00_Index", "01_Events", "02_Entities", "03_Assets",
        "04_Funds", "05_Regime_Canonical", "06_Debate_Memory",
        "07_Graph_Evidence", "08_Claims",
    ):
        (wiki / d).mkdir(parents=True)

    def w(rel: str, text: str) -> None:
        (wiki / rel).write_text(text, encoding="utf-8")

    w("00_Index/index.md", "---\ntype: wiki_index\nupdated_at: 2026-05-01T00:00:00\n---\n# Index\n")
    w("01_Events/2026-04_event_aaaaaaaaaa.md",
      "---\ntype: event\nstatus: draft\nevent_id: aaaaaaaaaa\nperiod: 2026-04\n"
      "top_topics: [\"환율_FX\"]\nupdated_at: 2026-05-01T00:00:00\n---\n"
      "# Event aaaaaaaaaa\nbody")
    w("02_Entities/2026-04_graphnode__AI.md",
      "---\ntype: entity\nstatus: base\nentity_id: graphnode__AI\nlabel: \"AI\"\n"
      "taxonomy_topic: 테크_AI_반도체\nperiod: 2026-04\nupdated_at: 2026-05-01T00:00:00\n"
      "---\n# AI\nbody")
    w("03_Assets/2026-04_국내주식.md",
      "---\nperiod: 2026-04\nasset_class: 국내주식\n"
      "source_type: asset_wiki\ngenerated_by: builder\n---\n# 국내주식\nbody")
    w("04_Funds/2026-04_07G04.md",
      "---\nperiod: 2026-04\nfund_code: 07G04\n"
      "source_type: fund_wiki\ngenerated_by: builder\n---\n# 07G04\nbody")
    w("05_Regime_Canonical/current_regime.md",
      "---\ntype: regime\nstatus: confirmed\ndominant_narrative: \"지정학\"\n"
      "since: 2026-04-01\n---\n# Current regime\nbody")
    w("06_Debate_Memory/2026-04__market_20260420T100000.md",
      "---\ntype: debate_memory\nstatus: provisional\nfund_code: _market\n"
      "period: 2026-04\ndebate_date: 2026-04-20T10:00:00\n---\n# Debate memory\nbody")
    w("07_Graph_Evidence/2026-04_transmission_paths_draft.md",
      "---\ntype: graph_evidence\nstatus: draft\nperiod: 2026-04\n"
      "phase: P1\nupdated_at: 2026-05-01T00:00:00\n---\n# Paths\nbody")
    w("08_Claims/2026-04_claim_aaaaaaaaaa.md",
      "---\ntype: claim\nsource_type: claim_wiki\nschema_version: r9a-claim-1.0.0\n"
      "claim_id: claim:2026-04:aaaaaaaaaa\nperiod: 2026-04\n"
      "promoted_at: 2026-05-01T00:00:00\npromotion_rule: B\n"
      "canonical_group_id: group:2026-04:gggggg0001\n"
      "related_group_ids: [\"group:2026-04:gggggg0001\", \"group:2026-04:gggggg0002\"]\n"
      "---\n# Claim aaaaaaaaaa\n## Summary\n- claim text\n## Affected Assets\n- 국내주식: positive\n- 해외주식: negative\n")
    # Replay variant — should be filtered out by production guard
    w("08_Claims/2026-04_claim_bbbbbbbbbb.r9a4-replay.md",
      "---\ntype: claim\nsource_type: claim_wiki\n"
      "claim_id: claim:2026-04:bbbbbbbbbb\nperiod: 2026-04\n"
      "promoted_at: 2026-05-01T00:00:00\npromotion_rule: B\n---\n# Replay\nbody")
    return wiki


@pytest.fixture
def synthetic_claims_store(tmp_path: Path) -> Path:
    """Build a minimal claims store (data/claims/2026-04.json) under tmp_path."""
    # wiki_context_pack_builder._load_claim_store_passing defaults to
    # ``WIKI_ROOT.parent / 'claims'`` — but we will pass claims_dir kw only
    # to the private helper for direct tests. For the public API,
    # builder uses ``wiki_root.parent / 'claims'`` since 'claims' is
    # sibling of 'wiki' under data/. So put it at tmp_path / 'claims'.
    claims = tmp_path / "claims"
    claims.mkdir(parents=True)
    store = {
        "schema_version": "1.0.0",
        "period": "2026-04",
        "saved_at": "2026-05-01T00:00:00",
        "source": "synthetic",
        "extractor_version": "test",
        "claims": [
            # passes Rule A (sal/cf>=0.7 + assets>=3)
            {
                "schema_version": "1.0.0",
                "claim_id": "claim:2026-04:aaaaaaaaaa",
                "period": "2026-04",
                "supporting_evidence_ids": ["ev1"],
                "claim_text": "Rule A pass",
                "claim_type": "macro_to_asset",
                "affected_assets": [
                    {"asset_class": "국내주식", "direction": "negative"},
                    {"asset_class": "해외주식", "direction": "negative"},
                    {"asset_class": "환율(FX)", "direction": "positive"},
                ],
                "causal_chain": [
                    {"source": "s", "target": "t", "relation": "raises"},
                ],
                "direction": "negative",
                "horizon": "short",
                "confidence": 0.95,
                "salience": 0.90,
                "linked_wiki_pages": [],
                "extractor_version": "test",
                "extraction_method": "test",
            },
            # passes Rule B (chain>=3 + supporting>=2)
            {
                "schema_version": "1.0.0",
                "claim_id": "claim:2026-04:bbbbbbbbbb",
                "period": "2026-04",
                "supporting_evidence_ids": ["ev1", "ev2"],
                "claim_text": "Rule B pass",
                "claim_type": "macro_to_asset",
                "affected_assets": [
                    {"asset_class": "국내주식", "direction": "negative"},
                ],
                "causal_chain": [
                    {"source": "a", "target": "b", "relation": "raises"},
                    {"source": "b", "target": "c", "relation": "raises"},
                    {"source": "c", "target": "d", "relation": "raises"},
                ],
                "direction": "negative",
                "horizon": "short",
                "confidence": 0.5,
                "salience": 0.5,
                "linked_wiki_pages": [],
                "extractor_version": "test",
                "extraction_method": "test",
            },
            # fails both rules — must be excluded
            {
                "schema_version": "1.0.0",
                "claim_id": "claim:2026-04:cccccccccc",
                "period": "2026-04",
                "supporting_evidence_ids": ["ev1"],
                "claim_text": "Both rules fail",
                "claim_type": "macro_to_asset",
                "affected_assets": [
                    {"asset_class": "국내주식", "direction": "negative"},
                ],
                "causal_chain": [],
                "direction": "negative",
                "horizon": "short",
                "confidence": 0.5,
                "salience": 0.5,
                "linked_wiki_pages": [],
                "extractor_version": "test",
                "extraction_method": "test",
            },
        ],
        "stats": {},
    }
    (claims / "2026-04.json").write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return claims


# ──────────────────────────────────────────────────────────────────
# 1. monthly default window
# ──────────────────────────────────────────────────────────────────

def test_monthly_default_window_computes_full_month():
    w = wcp._resolve_request_window(
        period_key="2026-04", period_type="monthly",
        window_start=None, window_end=None, as_of_date=None,
    )
    assert w["window_start"] == "2026-04-01"
    assert w["window_end"] == "2026-04-30"
    assert w["as_of_date"] == "2026-04-30"
    assert w["source_cutoff_date"] == "2026-04-30"


def test_monthly_default_window_february_leap_and_non_leap():
    # 2024 is leap, 2025 is not
    w = wcp._resolve_request_window(
        period_key="2024-02", period_type="monthly",
        window_start=None, window_end=None, as_of_date=None,
    )
    assert w["window_end"] == "2024-02-29"
    w = wcp._resolve_request_window(
        period_key="2025-02", period_type="monthly",
        window_start=None, window_end=None, as_of_date=None,
    )
    assert w["window_end"] == "2025-02-28"


# ──────────────────────────────────────────────────────────────────
# 2. filename period fallback
# ──────────────────────────────────────────────────────────────────

def test_filename_period_fallback_marks_warning(synthetic_wiki: Path):
    # 03_Assets/2026-04_국내주식.md has period in frontmatter,
    # but no window_start/end → should derive from period_key and
    # NOT set used_filename_fallback unless period itself was filename-derived.
    fp = synthetic_wiki / "03_Assets" / "2026-04_국내주식.md"
    rec = wcp.parse_wiki_page(fp)
    assert rec is not None
    assert rec.period_key == "2026-04"
    assert rec.window_start == "2026-04-01"
    assert rec.window_end == "2026-04-30"
    # period was in frontmatter → fallback flag True only because window_start/end
    # were missing and derived. This is the warning condition.
    assert rec.used_filename_fallback is True


def test_filename_period_fallback_when_no_frontmatter(tmp_path: Path):
    # page with NO frontmatter at all → must fall back to filename
    fp = tmp_path / "01_Events" / "2026-04_event_xxxxxx.md"
    fp.parent.mkdir(parents=True)
    fp.write_text("# Bare\nbody only\n", encoding="utf-8")
    rec = wcp.parse_wiki_page(fp)
    assert rec is not None
    assert rec.period_key == "2026-04"
    assert rec.window_start == "2026-04-01"
    assert rec.window_end == "2026-04-30"
    assert rec.used_filename_fallback is True


# ──────────────────────────────────────────────────────────────────
# 3. date overlap true/false
# ──────────────────────────────────────────────────────────────────

def test_periods_overlap_true_false():
    # request: 2026-04
    req_ws, req_we = "2026-04-01", "2026-04-30"
    # full overlap
    assert wcp._periods_overlap("2026-04-01", "2026-04-30", req_ws, req_we) is True
    # partial overlap (page ends inside request)
    assert wcp._periods_overlap("2026-03-15", "2026-04-05", req_ws, req_we) is True
    # partial overlap (page starts inside request)
    assert wcp._periods_overlap("2026-04-25", "2026-05-10", req_ws, req_we) is True
    # disjoint before
    assert wcp._periods_overlap("2026-03-01", "2026-03-31", req_ws, req_we) is False
    # disjoint after
    assert wcp._periods_overlap("2026-05-01", "2026-05-31", req_ws, req_we) is False
    # missing window → False
    assert wcp._periods_overlap(None, None, req_ws, req_we) is False


# ──────────────────────────────────────────────────────────────────
# 4. source_cutoff_date violation 감지
# ──────────────────────────────────────────────────────────────────

def test_cutoff_violation_skips_page(tmp_path: Path):
    fp = tmp_path / "03_Assets" / "2026-04_test.md"
    fp.parent.mkdir(parents=True)
    fp.write_text(
        "---\nperiod: 2026-04\nwindow_start: 2026-04-01\nwindow_end: 2026-04-30\n"
        "source_cutoff_date: 2026-05-15\n---\n# T\nbody\n",
        encoding="utf-8",
    )
    rw = wcp._resolve_request_window(
        period_key="2026-04", period_type="monthly",
        window_start=None, window_end=None, as_of_date=None,
    )
    recs, stats = wcp._select_pages_for_window(
        "03_Assets", rw,
        builder_run_time="2030-01-01T00:00:00+00:00",
        body_excerpt_chars=200,
        wiki_root=tmp_path,
    )
    assert len(recs) == 0
    assert stats["skipped_cutoff_violation"] == 1


# ──────────────────────────────────────────────────────────────────
# 5. market_debate stage 에서 04_Funds 제외
# ──────────────────────────────────────────────────────────────────

def test_market_debate_excludes_04_funds(synthetic_wiki: Path, tmp_path: Path):
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    sel_by_dir = pack["source_trace"]["selected_by_directory"]
    assert "04_Funds" not in sel_by_dir
    assert pack["fund_context"]["fund_page"] is None


def test_fund_comment_pins_04_funds(synthetic_wiki: Path):
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="fund_comment", fund_code="07G04",
        wiki_root=synthetic_wiki,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    fp = pack["fund_context"]["fund_page"]
    assert fp is not None
    assert fp["fund_code"] == "07G04"
    assert "04_Funds" in pack["source_trace"]["selected_by_directory"]


# ──────────────────────────────────────────────────────────────────
# 6. 06_Debate_Memory 기본 제외
# ──────────────────────────────────────────────────────────────────

def test_debate_memory_disabled_by_default(synthetic_wiki: Path):
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    assert pack["prior_memory"]["include_policy"] == "disabled"
    assert pack["prior_memory"]["debate_memory"] == []
    assert "06_Debate_Memory" not in pack["source_trace"]["selected_by_directory"]


def test_debate_memory_opt_in_when_admin_preview(synthetic_wiki: Path):
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="admin_preview",
        wiki_root=synthetic_wiki,
        include_debate_memory=True,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    assert pack["prior_memory"]["include_policy"] == "summary_only"
    assert len(pack["prior_memory"]["debate_memory"]) >= 1


# ──────────────────────────────────────────────────────────────────
# 7. claim_store selected ↔ 08_Claims wiki page join
# ──────────────────────────────────────────────────────────────────

def test_claim_store_to_wiki_join_for_existing_pages(
    synthetic_wiki: Path, synthetic_claims_store: Path,
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    # claim_store는 wiki_root.parent / 'claims' 를 default 로 사용. 우리는
    # synthetic_wiki = tmp_path/'wiki' 이고 synthetic_claims_store = tmp_path/'claims'
    # 이므로 sibling 관계가 이미 성립.
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    st = pack["source_trace"]
    # store 에서 2건 (aaaa, bbbb) Rule A/B 통과
    assert st["claim_store_selected_count"] == 2
    # wiki 에는 aaaa 만 production page 가 있음 (bbbb 는 replay variant — 제외)
    assert st["matched_wiki_claim_count"] == 1
    # join rate = 1/2
    assert st["claim_store_to_wiki_join_rate"] == pytest.approx(0.5)
    # claim_memory entries
    claim_entries = pack["market_context"]["claims"]
    assert len(claim_entries) == 1
    assert claim_entries[0]["claim_id"] == "claim:2026-04:aaaaaaaaaa"


# ──────────────────────────────────────────────────────────────────
# 8. related_group_ids 파싱
# ──────────────────────────────────────────────────────────────────

def test_related_group_ids_parsed(
    synthetic_wiki: Path, synthetic_claims_store: Path,
):
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    sel = pack["source_trace"]["selected_related_group_ids"]
    # aaaaaaaaaa 의 wiki 에 2개 group 정의 — dedup 후 2개
    assert "group:2026-04:gggggg0001" in sel
    assert "group:2026-04:gggggg0002" in sel


# ──────────────────────────────────────────────────────────────────
# 9. source_type_counts 집계
# ──────────────────────────────────────────────────────────────────

def test_source_type_counts_separates_wiki_layers(
    synthetic_wiki: Path, synthetic_claims_store: Path,
):
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    cnt = pack["source_trace"]["source_type_counts"]
    # market_debate stage allowed dirs 6개 중 각 dir 에서 최소 1건 (regime은 2건)
    assert cnt.get("wiki_event_memory", 0) == 1
    assert cnt.get("wiki_entity_memory", 0) == 1
    assert cnt.get("wiki_asset_memory", 0) == 1
    assert cnt.get("wiki_regime_memory", 0) == 1
    assert cnt.get("wiki_graph_memory", 0) == 1
    assert cnt.get("claim_memory", 0) == 1
    # 04_Funds / 06_Debate_Memory / wiki_index 등 nonexistent
    assert "fund_context" not in cnt
    assert "interpreted_memory" not in cnt
    assert "wiki_index" not in cnt


# ──────────────────────────────────────────────────────────────────
# 10. claim_store_to_wiki_join_rate 계산 — selected=0 → None
# ──────────────────────────────────────────────────────────────────

def test_join_rate_is_none_when_store_empty(
    synthetic_wiki: Path, tmp_path: Path,
):
    # no claims store at all → selected=0, join rate = None
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    st = pack["source_trace"]
    assert st["claim_store_selected_count"] == 0
    assert st["claim_store_to_wiki_join_rate"] is None
    # warning emitted
    types = {w.get("warning_type") for w in pack["warnings"]}
    assert "claim_store_zero_selected" in types


# ──────────────────────────────────────────────────────────────────
# 11. empty wiki directory graceful handling
# ──────────────────────────────────────────────────────────────────

def test_empty_wiki_directory_returns_empty_pack(tmp_path: Path):
    wiki = tmp_path / "wiki"
    for d in (
        "01_Events", "02_Entities", "03_Assets", "04_Funds",
        "05_Regime_Canonical", "06_Debate_Memory", "07_Graph_Evidence",
        "08_Claims",
    ):
        (wiki / d).mkdir(parents=True)
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=wiki,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    assert pack["source_trace"]["wiki_pages_considered"] == 0
    assert pack["source_trace"]["wiki_pages_selected"] == 0
    assert pack["source_trace"]["source_cutoff_violations"] == 0
    # no exception raised


# ──────────────────────────────────────────────────────────────────
# Bonus — invariants
# ──────────────────────────────────────────────────────────────────

def test_schema_version_and_mode_are_stable(synthetic_wiki: Path):
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    assert pack["schema_version"] == wcp.SCHEMA_VERSION
    assert pack["mode"] == "wiki_first_debug"


def test_unknown_stage_raises():
    with pytest.raises(ValueError, match="unknown stage"):
        wcp.build_wiki_context_pack(
            period_key="2026-04", stage="not_a_stage",
        )


def test_unknown_period_type_raises():
    with pytest.raises(ValueError, match="unsupported period_type"):
        wcp.build_wiki_context_pack(
            period_key="2026-04", period_type="weird",
        )


# ──────────────────────────────────────────────────────────────────
# Global max_pages (R9-B.2 HOLD fix — workorder §"필수 수정")
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def synthetic_wiki_rich(tmp_path: Path) -> Path:
    """Larger synthetic wiki — multiple pages per dir + 3 claim wikis.

    Used to exercise global max_pages cap and priority/round-robin selection.
    """
    wiki = tmp_path / "wiki"
    for d in (
        "01_Events", "02_Entities", "03_Assets", "04_Funds",
        "05_Regime_Canonical", "07_Graph_Evidence", "08_Claims",
    ):
        (wiki / d).mkdir(parents=True)

    def w(rel: str, body: str) -> None:
        (wiki / rel).write_text(body, encoding="utf-8")

    # 4 events
    for h in ("aaa1", "aaa2", "aaa3", "aaa4"):
        w(f"01_Events/2026-04_event_{h}.md",
          f"---\ntype: event\nperiod: 2026-04\nevent_id: {h}\n---\n# E {h}\nbody")
    # 4 entities
    for label in ("AI", "관세", "금리", "환율"):
        w(f"02_Entities/2026-04_graphnode__{label}.md",
          f"---\ntype: entity\nperiod: 2026-04\nlabel: \"{label}\"\n---\n# {label}\nbody")
    # 3 assets
    for ac in ("국내주식", "해외주식", "국내채권"):
        w(f"03_Assets/2026-04_{ac}.md",
          f"---\nperiod: 2026-04\nasset_class: {ac}\n---\n# {ac}\nbody")
    # 1 regime
    w("05_Regime_Canonical/current_regime.md",
      "---\ntype: regime\ndominant_narrative: \"지정학\"\nsince: 2026-04-01\n---\n# Regime\nbody")
    # 2 graph
    w("07_Graph_Evidence/2026-04_transmission_paths_draft.md",
      "---\ntype: graph_evidence\nperiod: 2026-04\nphase: P1\n---\n# Paths\nbody")
    w("07_Graph_Evidence/transmission_paths_summary.md",
      "---\ntype: graph_evidence\nperiod: 2026-04\nphase: P1\n---\n# Summary\nbody")
    # 3 production claim wikis (rule-A passing, rule-B passing, rule-A passing)
    for h in ("aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc"):
        w(f"08_Claims/2026-04_claim_{h}.md",
          f"---\ntype: claim\nsource_type: claim_wiki\nclaim_id: claim:2026-04:{h}\n"
          f"period: 2026-04\npromoted_at: 2026-05-01T00:00:00\n"
          f"promotion_rule: B\n---\n# Claim {h}\nbody")
    # 1 fund page
    w("04_Funds/2026-04_07G04.md",
      "---\nperiod: 2026-04\nfund_code: 07G04\n---\n# 07G04\nbody")
    return wiki


@pytest.fixture
def synthetic_claims_store_rich(tmp_path: Path) -> Path:
    """3 claims all passing Rule A/B in store priority order (conf×sal desc).

    sibling of synthetic_wiki_rich (tmp_path/wiki and tmp_path/claims).
    """
    claims = tmp_path / "claims"
    claims.mkdir(parents=True)

    def _c(h: str, conf: float, sal: float) -> dict:
        return {
            "schema_version": "1.0.0",
            "claim_id": f"claim:2026-04:{h}",
            "period": "2026-04",
            "supporting_evidence_ids": ["ev1", "ev2"],
            "claim_text": f"claim {h}",
            "claim_type": "macro_to_asset",
            "affected_assets": [
                {"asset_class": "국내주식", "direction": "negative"},
                {"asset_class": "해외주식", "direction": "negative"},
                {"asset_class": "환율(FX)", "direction": "positive"},
            ],
            "causal_chain": [
                {"source": "a", "target": "b", "relation": "raises"},
                {"source": "b", "target": "c", "relation": "raises"},
                {"source": "c", "target": "d", "relation": "raises"},
            ],
            "direction": "negative",
            "horizon": "short",
            "confidence": conf,
            "salience": sal,
            "linked_wiki_pages": [],
            "extractor_version": "test",
            "extraction_method": "test",
        }

    store = {
        "schema_version": "1.0.0",
        "period": "2026-04",
        "saved_at": "2026-05-01T00:00:00",
        "source": "synthetic",
        "extractor_version": "test",
        "claims": [
            _c("aaaaaaaaaa", 0.95, 0.95),  # rank 1
            _c("bbbbbbbbbb", 0.90, 0.90),  # rank 2
            _c("cccccccccc", 0.85, 0.85),  # rank 3
        ],
        "stats": {},
    }
    (claims / "2026-04.json").write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return claims


def test_max_pages_applies_to_total_selected_pages(
    synthetic_wiki_rich: Path, synthetic_claims_store_rich: Path,
):
    """max_pages 는 전체 selected wiki page 수의 글로벌 상한."""
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki_rich,
        max_pages=5,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    st = pack["source_trace"]
    assert st["wiki_pages_selected"] <= 5
    assert len(st["selected_wiki_paths"]) <= 5
    mc = pack["market_context"]
    mc_total = (
        len(mc["events"]) + len(mc["entities"]) + len(mc["assets"])
        + len(mc["regime"]) + len(mc["graph_evidence"]) + len(mc["claims"])
    )
    if pack["fund_context"]["fund_page"]:
        mc_total += 1
    mc_total += len(pack["prior_memory"]["debate_memory"])
    assert mc_total <= 5
    # Should hit the cap (we have >5 pages in fixture)
    assert st["wiki_pages_selected"] == 5


def test_source_type_counts_sum_matches_selected_pages(
    synthetic_wiki_rich: Path, synthetic_claims_store_rich: Path,
):
    """sum(source_type_counts.values()) == wiki_pages_selected (모든 view 일치)."""
    for cap in (3, 5, 8, 12, 50):
        pack = wcp.build_wiki_context_pack(
            period_key="2026-04", stage="market_debate",
            wiki_root=synthetic_wiki_rich,
            max_pages=cap,
            builder_run_time="2030-01-01T00:00:00+00:00",
        )
        st = pack["source_trace"]
        sel = st["wiki_pages_selected"]
        assert sum(st["source_type_counts"].values()) == sel, (
            f"cap={cap}: source_type_counts sum != selected"
        )
        assert len(st["selected_wiki_paths"]) == sel, (
            f"cap={cap}: paths len != selected"
        )
        assert sum(st["selected_by_directory"].values()) == sel, (
            f"cap={cap}: by_directory sum != selected"
        )
        mc = pack["market_context"]
        mc_total = sum(
            len(mc[k]) for k in
            ("events", "entities", "assets", "regime", "graph_evidence", "claims")
        )
        if pack["fund_context"]["fund_page"]:
            mc_total += 1
        mc_total += len(pack["prior_memory"]["debate_memory"])
        assert mc_total == sel, f"cap={cap}: market_context buckets sum != selected"


def test_claim_pages_prioritized_within_max_pages(
    synthetic_wiki_rich: Path, synthetic_claims_store_rich: Path,
):
    """max_pages=3 + 3 store-passing claims (모두 wiki match) → claims 가 전부."""
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki_rich,
        max_pages=3,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    st = pack["source_trace"]
    assert st["wiki_pages_selected"] == 3
    # All 3 slots taken by 08_Claims
    assert st["selected_by_directory"].get("08_Claims") == 3
    # No other dir gets a slot
    other = {k: v for k, v in st["selected_by_directory"].items() if k != "08_Claims"}
    assert all(v == 0 for v in other.values()) or other == {}, (
        f"non-claim dirs should be empty when claims fill cap: {other}"
    )
    # source_type_counts: only claim_memory
    assert st["source_type_counts"] == {"claim_memory": 3}
    # claim ordering preserved (store conf×sal desc → aaa, bbb, ccc)
    claim_ids = [c["claim_id"] for c in pack["market_context"]["claims"]]
    assert claim_ids == [
        "claim:2026-04:aaaaaaaaaa",
        "claim:2026-04:bbbbbbbbbb",
        "claim:2026-04:cccccccccc",
    ]


def test_round_robin_balanced_fill_after_claims(
    synthetic_wiki_rich: Path, synthetic_claims_store_rich: Path,
):
    """claims 3개 reserved 후 남은 9 slot 이 priority round-robin 으로 배분."""
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="market_debate",
        wiki_root=synthetic_wiki_rich,
        max_pages=12,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    sbd = pack["source_trace"]["selected_by_directory"]
    assert sbd["08_Claims"] == 3  # reserved first
    # round-robin order: 07→05→01→03→02 with pools [2,1,4,3,4]
    # 9 picks: 07,05,01,03,02, 07(none left for 07 — actually 2 left? 0+1=1), 01,03,02, 01
    # 07 has 2 → 1 picked at slot 4 + 1 picked at slot 9 etc.
    # Simply assert distribution is non-degenerate (each present dir has >=1).
    for d in ("07_Graph_Evidence", "05_Regime_Canonical", "01_Events",
              "03_Assets", "02_Entities"):
        assert sbd.get(d, 0) >= 1, f"{d} should have at least 1 slot"
    assert sum(sbd.values()) == 12
    # 04_Funds (market_debate excluded) and 06_Debate_Memory absent
    assert "04_Funds" not in sbd
    assert "06_Debate_Memory" not in sbd


def test_fund_pinned_reserved_before_filldirs(
    synthetic_wiki_rich: Path, synthetic_claims_store_rich: Path,
):
    """fund_comment stage: fund_pinned + claims 가 먼저 reserve."""
    pack = wcp.build_wiki_context_pack(
        period_key="2026-04", stage="fund_comment", fund_code="07G04",
        wiki_root=synthetic_wiki_rich,
        max_pages=5,
        builder_run_time="2030-01-01T00:00:00+00:00",
    )
    st = pack["source_trace"]
    assert st["wiki_pages_selected"] == 5
    # fund_pinned (1) + claims (3) + 1 more from fill = 5
    assert st["selected_by_directory"].get("04_Funds") == 1
    assert st["selected_by_directory"].get("08_Claims") == 3
    # remaining 1 slot → 07_Graph_Evidence (highest in fill priority)
    assert st["selected_by_directory"].get("07_Graph_Evidence") == 1
    assert pack["fund_context"]["fund_page"] is not None
    assert pack["fund_context"]["fund_page"]["fund_code"] == "07G04"
