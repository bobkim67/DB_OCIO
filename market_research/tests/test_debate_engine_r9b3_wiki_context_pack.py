# -*- coding: utf-8 -*-
"""R9-B.3 — Wiki Context Pack debate prompt opt-in injection tests.

Boundary:
  - LLM 호출 0 (모두 monkeypatch / 직접 helper 호출)
  - 운영 wiki / data/claims / report_output / regime_memory 미접근
  - default behavior unchanged 회귀 보장
"""
from __future__ import annotations

from pathlib import Path

import pytest

from market_research.report import debate_engine as de


# ──────────────────────────────────────────────────────────────────
# Pack fixture — minimal but covers all section types
# ──────────────────────────────────────────────────────────────────

def _make_pack(period_key: str = "2026-04",
               stage: str = "market_debate",
               *,
               include_fund: bool = False) -> dict:
    pack: dict = {
        "schema_version": de.WIKI_CONTEXT_PACK_SCHEMA_VERSION,
        "period_type": "monthly",
        "period_key": period_key,
        "window_start": f"{period_key}-01",
        "window_end": f"{period_key}-30",
        "as_of_date": f"{period_key}-30",
        "stage": stage,
        "fund_code": "07G04" if include_fund else None,
        "mode": "wiki_first_debug",
        "generated_at": "2026-05-13T00:00:00+00:00",
        "debate_run_id": None,
        "market_context": {
            "events": [{
                "page_id": "event:2026-04:2026-04_event_aaaaaaaaaa",
                "path": "01_Events/2026-04_event_aaaaaaaaaa.md",
                "page_type": "event",
                "title": "Event aaaaaaaaaa",
                "excerpt": "Geo event excerpt",
                "source_type": "wiki_event_memory",
            }],
            "entities": [{
                "page_id": "entity:2026-04:graphnode__AI",
                "path": "02_Entities/2026-04_graphnode__AI.md",
                "page_type": "entity",
                "title": "AI",
                "excerpt": "",
                "source_type": "wiki_entity_memory",
            }],
            "assets": [{
                "page_id": "asset:2026-04:국내주식",
                "path": "03_Assets/2026-04_국내주식.md",
                "page_type": "asset",
                "title": "국내주식",
                "excerpt": "국내주식 메모",
                "source_type": "wiki_asset_memory",
            }],
            "regime": [{
                "page_id": "regime:05_Regime_Canonical/current_regime.md",
                "path": "05_Regime_Canonical/current_regime.md",
                "page_type": "regime",
                "title": "Current regime",
                "excerpt": "regime excerpt",
                "source_type": "wiki_regime_memory",
            }],
            "graph_evidence": [{
                "page_id": "graph_evidence:2026-04:2026-04_transmission_paths_draft",
                "path": "07_Graph_Evidence/2026-04_transmission_paths_draft.md",
                "page_type": "graph_evidence",
                "title": "transmission paths draft",
                "excerpt": "graph excerpt",
                "source_type": "wiki_graph_memory",
            }],
            "claims": [{
                "page_id": "claim:2026-04:aaaaaaaaaa",
                "path": "08_Claims/2026-04_claim_aaaaaaaaaa.md",
                "claim_id": "claim:2026-04:aaaaaaaaaa",
                "canonical_group_id": "group:2026-04:gggggg0001",
                "related_group_ids": ["group:2026-04:gggggg0001"],
                "promotion_rule": "B",
                "title": "Claim aaaaaaaaaa",
                "affected_assets": ["국내주식", "해외주식"],
                "excerpt": "claim text excerpt",
                "source_type": "claim_memory",
            }],
        },
        "fund_context": {
            "fund_page": ({
                "page_id": "fund:2026-04:2026-04_07G04",
                "path": "04_Funds/2026-04_07G04.md",
                "fund_code": "07G04",
                "title": "07G04",
                "excerpt": "fund page excerpt",
                "source_type": "fund_context",
            } if include_fund else None),
            "fund_claims": [],
            "fund_asset_exposures": [],
        },
        "prior_memory": {
            "debate_memory": [],
            "include_policy": "disabled",
        },
        "validation_pack": {
            "raw_sources_used": [],
            "numeric_guardrails": [],
            "source_cutoff_date": f"{period_key}-30",
        },
        "source_trace": {
            "wiki_pages_considered": 12,
            "wiki_pages_selected": 7 if include_fund else 6,
            "selected_wiki_paths": [
                "01_Events/2026-04_event_aaaaaaaaaa.md",
                "02_Entities/2026-04_graphnode__AI.md",
                "03_Assets/2026-04_국내주식.md",
                "05_Regime_Canonical/current_regime.md",
                "07_Graph_Evidence/2026-04_transmission_paths_draft.md",
                "08_Claims/2026-04_claim_aaaaaaaaaa.md",
            ] + (["04_Funds/2026-04_07G04.md"] if include_fund else []),
            "selected_by_directory": {
                "01_Events": 1, "02_Entities": 1, "03_Assets": 1,
                "05_Regime_Canonical": 1, "07_Graph_Evidence": 1,
                "08_Claims": 1, **(
                    {"04_Funds": 1} if include_fund else {}
                ),
            },
            "source_type_counts": {
                "wiki_event_memory": 1, "wiki_entity_memory": 1,
                "wiki_asset_memory": 1, "wiki_regime_memory": 1,
                "wiki_graph_memory": 1, "claim_memory": 1,
                **({"fund_context": 1} if include_fund else {}),
            },
            "selected_claim_ids": ["claim:2026-04:aaaaaaaaaa"],
            "selected_related_group_ids": ["group:2026-04:gggggg0001"],
            "claim_store_selected_count": 1,
            "matched_wiki_claim_count": 1,
            "claim_store_to_wiki_join_rate": 1.0,
            "source_cutoff_violations": 0,
            "per_dir_stats": {},
        },
        "warnings": [],
    }
    return pack


def _bare_context(year: int = 2026, month: int = 4) -> dict:
    """legacy raw blocks 가 채워진 최소 context. _build_shared_context 미호출."""
    return {
        "year": year,
        "month": month,
        "fund_code": None,
        "asset_movement_anchors_text": "## Asset Movement Anchors\n- 해외주식 -1.2%\n",
        "claims_text": "",
        "news_summary_text": "뉴스 분류 요약 (12건)\n- 통화정책: 3건\n",
        "indicators_text": "최신 지표 (2026-04-30):\n  VIX: 25.0\n",
        "timeseries_narrative_text": "USDKRW 1480 부근에서 변동성 확대.",
        "graph_paths_text": "## 주요 인과 경로\n[인과경로 1] geo→oil→cpi",
        "wiki_context_text": "## 관련 WikiTree 메모\n- 02_Entities/2026-04_AI.md",
        "asset_coverage_text": "## 자산군 coverage\n- 국내주식: 강",
        "blog_context_text": "",
    }


# ──────────────────────────────────────────────────────────────────
# 1. default legacy behavior unchanged
# ──────────────────────────────────────────────────────────────────

def test_legacy_default_prompt_has_no_wiki_primary_block():
    ctx = _bare_context()
    # default: no wiki_primary_context_text key set
    prompt = de._build_agent_prompt("bull", ctx)
    assert de.WIKI_CONTEXT_PRIMARY_HEADING not in prompt
    assert de.WIKI_CONTEXT_RAW_HEADING not in prompt
    # raw blocks still present
    assert "뉴스 분류 요약" in prompt
    assert "최신 지표" in prompt
    assert "주요 인과 경로" in prompt
    assert "관련 WikiTree 메모" in prompt
    assert "Asset Movement Anchors" in prompt


def test_legacy_empty_string_primary_text_is_skipped_cleanly():
    ctx = _bare_context()
    ctx["wiki_primary_context_text"] = ""
    prompt = de._build_agent_prompt("bull", ctx)
    assert de.WIKI_CONTEXT_PRIMARY_HEADING not in prompt
    assert de.WIKI_CONTEXT_RAW_HEADING not in prompt


def test_run_market_debate_default_flag_does_not_invoke_builder(monkeypatch):
    """use_wiki_context_pack=False (default) → builder 호출 0."""
    called = {"count": 0}

    def _fake_build(**kw):  # pragma: no cover — should NOT be called
        called["count"] += 1
        return _make_pack()

    monkeypatch.setattr(
        "market_research.report.wiki_context_pack_builder.build_wiki_context_pack",
        _fake_build,
    )
    # Stub heavy downstream so test stays LLM-free
    monkeypatch.setattr(
        de, "_build_shared_context",
        lambda y, m, **kw: _bare_context(year=y, month=m),
    )
    monkeypatch.setattr(
        de, "_run_agent",
        lambda agent, context: {
            "agent": agent, "stance": "neutral", "key_points": [],
            "asset_movement_commentary": [],
        },
    )
    monkeypatch.setattr(
        de, "_synthesize_debate",
        lambda agents, fund, ctx: {
            "customer_comment": "ok.", "consensus_points": [],
            "disagreements": [], "tail_risks": [], "admin_summary": "",
        },
    )
    monkeypatch.setattr(
        de, "_summarize_debate_narrative",
        lambda resp: {"debate_narrative": "n", "canonical_snapshot": {},
                       "diverges_from_canonical": False},
    )

    result = de.run_market_debate(2026, 4)
    assert called["count"] == 0
    trace = result["_debug_trace"]
    assert trace["prompt_context_mode"] == "legacy"
    assert trace["wiki_context_pack_enabled"] is False
    assert trace["wiki_primary_context_chars"] == 0
    # legacy trace 필드는 키 자체가 들어가지만 enabled=False 분기
    assert "wiki_context_pack_schema_version" not in trace


# ──────────────────────────────────────────────────────────────────
# 2. opt-in: builder called
# ──────────────────────────────────────────────────────────────────

def test_run_market_debate_opt_in_invokes_builder(monkeypatch):
    pack = _make_pack()
    seen: dict = {}

    def _fake_build(*, period_key, stage, fund_code, max_pages,
                    **_extra):
        seen.update(period_key=period_key, stage=stage,
                    fund_code=fund_code, max_pages=max_pages)
        return pack

    monkeypatch.setattr(
        "market_research.report.wiki_context_pack_builder.build_wiki_context_pack",
        _fake_build,
    )
    monkeypatch.setattr(
        de, "_build_shared_context",
        lambda y, m, **kw: _bare_context(year=y, month=m),
    )
    monkeypatch.setattr(
        de, "_run_agent",
        lambda agent, context: {
            "agent": agent, "stance": "neutral", "key_points": [],
            "asset_movement_commentary": [],
        },
    )
    monkeypatch.setattr(
        de, "_synthesize_debate",
        lambda agents, fund, ctx: {
            "customer_comment": "ok.", "consensus_points": [],
            "disagreements": [], "tail_risks": [], "admin_summary": "",
        },
    )
    monkeypatch.setattr(
        de, "_summarize_debate_narrative",
        lambda resp: {"debate_narrative": "n", "canonical_snapshot": {},
                       "diverges_from_canonical": False},
    )

    result = de.run_market_debate(
        2026, 4,
        use_wiki_context_pack=True,
        wiki_context_max_pages=5,
    )
    assert seen == {
        "period_key": "2026-04",
        "stage": "market_debate",
        "fund_code": None,
        "max_pages": 5,
    }
    trace = result["_debug_trace"]
    assert trace["prompt_context_mode"] == "wiki_context_pack_opt_in"
    assert trace["wiki_context_pack_enabled"] is True
    assert trace["wiki_context_pack_schema_version"] == \
        de.WIKI_CONTEXT_PACK_SCHEMA_VERSION
    assert trace["wiki_context_pack_period_key"] == "2026-04"


# ──────────────────────────────────────────────────────────────────
# 3. opt-in prompt contains Wiki Primary block
# ──────────────────────────────────────────────────────────────────

def test_opt_in_prompt_contains_wiki_primary_block():
    pack = _make_pack()
    primary = de._format_wiki_primary_context_for_prompt(pack)
    assert de.WIKI_CONTEXT_PRIMARY_HEADING in primary
    # Selected claim_id surfaces
    assert "claim:aaaaaaaaaa" in primary
    # At least one selected path text is included
    assert "07_Graph_Evidence/2026-04_transmission_paths_draft.md" in primary
    # heading 위계
    assert "### A.1 Canonical Claims" in primary
    assert "### A.2 Graph Evidence" in primary
    assert "### A.3 Regime Canonical" in primary

    ctx = _bare_context()
    ctx["wiki_primary_context_text"] = primary
    prompt = de._build_agent_prompt("bull", ctx)
    assert de.WIKI_CONTEXT_PRIMARY_HEADING in prompt
    assert de.WIKI_CONTEXT_RAW_HEADING in prompt
    # A 가 B 보다 앞에 와야 한다
    assert prompt.index(de.WIKI_CONTEXT_PRIMARY_HEADING) < \
        prompt.index(de.WIKI_CONTEXT_RAW_HEADING)


# ──────────────────────────────────────────────────────────────────
# 4. opt-in keeps raw validation/fallback block
# ──────────────────────────────────────────────────────────────────

def test_opt_in_prompt_keeps_raw_validation_blocks():
    pack = _make_pack()
    primary = de._format_wiki_primary_context_for_prompt(pack)
    ctx = _bare_context()
    ctx["wiki_primary_context_text"] = primary
    prompt = de._build_agent_prompt("bull", ctx)
    # raw blocks 그대로 살아있어야 한다 (R9-B.3 는 라벨만 추가)
    assert "뉴스 분류 요약" in prompt
    assert "최신 지표" in prompt
    assert "주요 인과 경로" in prompt
    assert "관련 WikiTree 메모" in prompt
    assert "Asset Movement Anchors" in prompt
    # 위계 안내가 prompt 안에 있다
    assert "위계 안내" in prompt or "Wiki Primary Context" in prompt


# ──────────────────────────────────────────────────────────────────
# 5. trace propagation
# ──────────────────────────────────────────────────────────────────

def test_wiki_context_pack_trace_contains_all_required_fields():
    pack = _make_pack()
    trace = de._wiki_context_pack_trace(pack)
    for k in (
        "wiki_context_pack_enabled",
        "wiki_context_pack_schema_version",
        "wiki_context_pack_period_key",
        "wiki_context_pack_stage",
        "wiki_pages_selected",
        "selected_wiki_paths",
        "wiki_source_type_counts",
        "selected_claim_ids",
        "selected_related_group_ids",
        "claim_store_to_wiki_join_rate",
        "source_cutoff_violations",
    ):
        assert k in trace, f"missing trace key: {k}"
    assert trace["wiki_context_pack_enabled"] is True
    assert trace["wiki_pages_selected"] == 6
    assert trace["claim_store_to_wiki_join_rate"] == 1.0
    assert trace["source_cutoff_violations"] == 0
    assert "claim:2026-04:aaaaaaaaaa" in trace["selected_claim_ids"]


def test_run_market_debate_opt_in_debug_trace_carries_pack_fields(monkeypatch):
    pack = _make_pack()
    monkeypatch.setattr(
        "market_research.report.wiki_context_pack_builder.build_wiki_context_pack",
        lambda **kw: pack,
    )
    monkeypatch.setattr(
        de, "_build_shared_context",
        lambda y, m, **kw: _bare_context(year=y, month=m),
    )
    monkeypatch.setattr(
        de, "_run_agent",
        lambda agent, context: {"agent": agent, "stance": "neutral"},
    )
    monkeypatch.setattr(
        de, "_synthesize_debate",
        lambda *a, **kw: {"customer_comment": "ok.", "consensus_points": [],
                          "disagreements": [], "tail_risks": [],
                          "admin_summary": ""},
    )
    monkeypatch.setattr(
        de, "_summarize_debate_narrative",
        lambda resp: {"debate_narrative": "n", "canonical_snapshot": {},
                       "diverges_from_canonical": False},
    )

    result = de.run_market_debate(2026, 4, use_wiki_context_pack=True)
    trace = result["_debug_trace"]
    assert trace["selected_wiki_paths"] == pack["source_trace"][
        "selected_wiki_paths"
    ]
    assert trace["wiki_source_type_counts"] == pack["source_trace"][
        "source_type_counts"
    ]
    assert trace["selected_claim_ids"] == ["claim:2026-04:aaaaaaaaaa"]
    assert trace["selected_related_group_ids"] == ["group:2026-04:gggggg0001"]
    assert trace["wiki_primary_context_chars"] > 0
    assert trace["raw_validation_context_chars"] > 0


# ──────────────────────────────────────────────────────────────────
# 6. max_pages 경로 (builder kwarg 까지 전달)
# ──────────────────────────────────────────────────────────────────

def test_max_pages_kwarg_propagates_to_builder(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        "market_research.report.wiki_context_pack_builder.build_wiki_context_pack",
        lambda **kw: (seen.update(kw) or _make_pack()),
    )
    monkeypatch.setattr(
        de, "_build_shared_context",
        lambda y, m, **kw: _bare_context(year=y, month=m),
    )
    monkeypatch.setattr(
        de, "_run_agent",
        lambda agent, context: {"agent": agent, "stance": "neutral"},
    )
    monkeypatch.setattr(
        de, "_synthesize_debate",
        lambda *a, **kw: {"customer_comment": "ok.", "consensus_points": [],
                          "disagreements": [], "tail_risks": [],
                          "admin_summary": ""},
    )
    monkeypatch.setattr(
        de, "_summarize_debate_narrative",
        lambda resp: {"debate_narrative": "n", "canonical_snapshot": {},
                       "diverges_from_canonical": False},
    )

    de.run_market_debate(
        2026, 4,
        use_wiki_context_pack=True,
        wiki_context_max_pages=3,
    )
    assert seen.get("max_pages") == 3


# ──────────────────────────────────────────────────────────────────
# 7. pack path validation
# ──────────────────────────────────────────────────────────────────

def test_validate_pack_passes_when_matching():
    pack = _make_pack(period_key="2026-04", stage="market_debate")
    de._validate_wiki_context_pack(
        pack, expected_period="2026-04", expected_stage="market_debate"
    )


def test_validate_pack_rejects_period_mismatch():
    pack = _make_pack(period_key="2026-04")
    with pytest.raises(de.WikiContextPackError) as exc:
        de._validate_wiki_context_pack(
            pack, expected_period="2026-05", expected_stage="market_debate"
        )
    assert "period_key mismatch" in str(exc.value)


def test_validate_pack_rejects_stage_mismatch():
    pack = _make_pack(stage="market_debate")
    with pytest.raises(de.WikiContextPackError) as exc:
        de._validate_wiki_context_pack(
            pack, expected_period="2026-04", expected_stage="fund_comment"
        )
    assert "stage mismatch" in str(exc.value)


def test_validate_pack_rejects_schema_version_mismatch():
    pack = _make_pack()
    pack["schema_version"] = "r9b-context-pack-9.9.9"
    with pytest.raises(de.WikiContextPackError) as exc:
        de._validate_wiki_context_pack(
            pack, expected_period="2026-04", expected_stage="market_debate"
        )
    assert "schema_version mismatch" in str(exc.value)


def test_validate_pack_rejects_non_dict():
    with pytest.raises(de.WikiContextPackError):
        de._validate_wiki_context_pack(
            "not a dict",  # type: ignore[arg-type]
            expected_period="2026-04", expected_stage="market_debate",
        )


def test_run_market_debate_external_pack_path_with_period_mismatch_raises(
    monkeypatch,
):
    monkeypatch.setattr(
        de, "_build_shared_context",
        lambda y, m, **kw: _bare_context(year=y, month=m),
    )
    bad_pack = _make_pack(period_key="2026-03")  # different period
    with pytest.raises(de.WikiContextPackError):
        de.run_market_debate(
            2026, 4,
            use_wiki_context_pack=True,
            wiki_context_pack=bad_pack,
        )


# ──────────────────────────────────────────────────────────────────
# 8. no operational file mutation
# ──────────────────────────────────────────────────────────────────

def test_format_primary_context_is_pure_function():
    """순수 함수: 같은 입력 → 같은 출력. 파일 IO 없음."""
    pack = _make_pack()
    out1 = de._format_wiki_primary_context_for_prompt(pack)
    out2 = de._format_wiki_primary_context_for_prompt(pack)
    assert out1 == out2


def test_format_primary_context_handles_empty_pack():
    empty = {
        "schema_version": de.WIKI_CONTEXT_PACK_SCHEMA_VERSION,
        "period_key": "2026-04", "stage": "market_debate",
        "market_context": {"events": [], "entities": [], "assets": [],
                            "regime": [], "graph_evidence": [], "claims": []},
        "fund_context": {"fund_page": None},
        "source_trace": {},
    }
    out = de._format_wiki_primary_context_for_prompt(empty)
    assert out == ""


def test_format_primary_context_rejects_non_dict():
    assert de._format_wiki_primary_context_for_prompt(None) == ""
    assert de._format_wiki_primary_context_for_prompt("string") == ""
    assert de._format_wiki_primary_context_for_prompt(123) == ""


def test_wiki_context_pack_schema_version_is_aligned_with_builder():
    """debate_engine 의 schema_version 상수가 builder 와 정확히 일치해야 함."""
    from market_research.report import wiki_context_pack_builder as wcp
    assert de.WIKI_CONTEXT_PACK_SCHEMA_VERSION == wcp.SCHEMA_VERSION


# ──────────────────────────────────────────────────────────────────
# 9. quarterly opt-in (end-month period_key)
# ──────────────────────────────────────────────────────────────────

def test_quarterly_opt_in_uses_end_month_period_key(monkeypatch):
    pack = _make_pack(period_key="2026-03", stage="quarterly_debate")
    seen: dict = {}
    monkeypatch.setattr(
        "market_research.report.wiki_context_pack_builder.build_wiki_context_pack",
        lambda **kw: (seen.update(kw) or pack),
    )
    monkeypatch.setattr(
        de, "_build_shared_context",
        lambda y, m, **kw: _bare_context(year=y, month=m),
    )
    monkeypatch.setattr(
        de, "_run_agent",
        lambda agent, context: {"agent": agent, "stance": "neutral"},
    )
    monkeypatch.setattr(
        de, "_synthesize_debate",
        lambda *a, **kw: {"customer_comment": "ok.", "consensus_points": [],
                          "disagreements": [], "tail_risks": [],
                          "admin_summary": ""},
    )
    monkeypatch.setattr(
        de, "_summarize_debate_narrative",
        lambda resp: {"debate_narrative": "n", "canonical_snapshot": {},
                       "diverges_from_canonical": False},
    )
    # debate_service.build_evidence_annotations 도 stub 안 하면 운영 file read.
    # 분기 흐름에서만 호출되므로 monkeypatch (LLM 0 + IO 0).
    monkeypatch.setattr(
        "market_research.report.debate_service.build_evidence_annotations",
        lambda evs, y, ms: [],
    )

    result = de.run_quarterly_debate(2026, 1, use_wiki_context_pack=True)
    assert seen["period_key"] == "2026-03"
    assert seen["stage"] == "quarterly_debate"
    trace = result["_debug_trace"]
    assert trace["prompt_context_mode"] == "wiki_context_pack_opt_in"
    assert trace["wiki_context_pack_period_key"] == "2026-03"


# ──────────────────────────────────────────────────────────────────
# 10. CLI flag parsing (report/cli.py)
# ──────────────────────────────────────────────────────────────────

def test_related_group_ids_propagated_from_pack_to_debate_trace(monkeypatch):
    """R9-B.3 HOLD fix — pack 의 selected_related_group_ids 가 _debug_trace
    에 그대로 올라오는지 확인 (claim lineage surface 의 핵심).

    User-requested test: 만약 builder pack 에 related_group_id 가 들어가
    있다면, run_market_debate trace 에 동일 값이 propagate 되어야 한다.
    """
    pack = _make_pack()
    pack["source_trace"]["selected_related_group_ids"] = [
        "group:2026-04:cfee0ff342",
        "group:2026-04:abcd1234ef",
    ]
    monkeypatch.setattr(
        "market_research.report.wiki_context_pack_builder.build_wiki_context_pack",
        lambda **kw: pack,
    )
    monkeypatch.setattr(
        de, "_build_shared_context",
        lambda y, m, **kw: _bare_context(year=y, month=m),
    )
    monkeypatch.setattr(
        de, "_run_agent",
        lambda agent, context: {"agent": agent, "stance": "neutral"},
    )
    monkeypatch.setattr(
        de, "_synthesize_debate",
        lambda *a, **kw: {"customer_comment": "ok.", "consensus_points": [],
                          "disagreements": [], "tail_risks": [],
                          "admin_summary": ""},
    )
    monkeypatch.setattr(
        de, "_summarize_debate_narrative",
        lambda resp: {"debate_narrative": "n", "canonical_snapshot": {},
                       "diverges_from_canonical": False},
    )

    result = de.run_market_debate(2026, 4, use_wiki_context_pack=True)
    trace = result["_debug_trace"]
    assert trace["selected_related_group_ids"] == [
        "group:2026-04:cfee0ff342",
        "group:2026-04:abcd1234ef",
    ]
    # 동시에 claim_ids 도 살아 있어야 한다 (둘 다 surface — R9-A.21A
    # dual-anchor 패턴에서 anchor claim 자체 + lineage group 양쪽 trace).
    assert "claim:2026-04:aaaaaaaaaa" in trace["selected_claim_ids"]


def test_cli_parser_accepts_r9b3_flags():
    # report/cli.py 의 build sub-command parser 가 R9-B.3 flag 를 인식하는지
    # 직접 검사. 실행은 안 함 (다른 인자가 필요).
    import argparse as _ap
    # 동등한 parser 를 생성하지 않고 cli main 의 add_argument 결과를 직접 검증.
    # action 흐름이 무거우니 옵션 텍스트가 cli.py 안에 박혀 있는지로 대체.
    cli_text = (
        Path(__file__).resolve().parent.parent / "report" / "cli.py"
    ).read_text(encoding="utf-8")
    assert "--use-wiki-context-pack" in cli_text
    assert "--wiki-context-pack-path" in cli_text
    assert "--wiki-context-max-pages" in cli_text
    # build_report signature 에 kwarg 추가됨
    assert "use_wiki_context_pack: bool = False" in cli_text
    assert "wiki_context_pack: dict | None = None" in cli_text
