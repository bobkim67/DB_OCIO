# -*- coding: utf-8 -*-
"""R8-B wiring smoke: debate_engine result 의 asset_movement_* + agents 필드가
debate_service.run_debate_and_save 의 draft.json 에 보존되고, fund_comment_service.
_market_comment_to_inputs 가 그대로 pass-through 하는지 검증.

배경: agent 단계는 amc 를 self-fill 하고 result.asset_movement_anchors / commentary 에
넣지만, 이전 debate_service 는 draft_data dict 에 해당 키를 복사하지 않아
fund_comment_service 가 빈 amc 만 받았다 (R8-B-2 live observe 2026-05-07).

LLM 호출 0. report_store OUTPUT_DIR / wiki / debate_logs 모두 tmp 격리.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ────────────────────────────────────────────────────────────────────
# fixture: report_store / wiki / debate_logs 격리
# ────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    from market_research.report import report_store
    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)
    monkeypatch.setattr(
        report_store, "EVIDENCE_TRACKER", root / "_evidence_quality.jsonl",
    )
    try:
        from market_research.wiki import debate_memory as wiki_debate_memory
        wiki_tmp = tmp_path / "wiki" / "06_Debate_Memory"
        wiki_tmp.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(wiki_debate_memory, "DEBATE_MEMORY_DIR", wiki_tmp)
    except ImportError:
        pass
    return root


def _build_result_with_r8b(fixed_run_id: str = "a" * 32) -> dict:
    """R8-B 5종 키 + agents 모두 채워진 stub result."""
    return {
        "year": 2026, "month": 4,
        "debate_run_id": fixed_run_id,
        "debated_at": "2026-04-20T10:00:00",
        "agents": {
            "bull": {
                "agent": "bull", "stance": "bullish",
                "asset_movement_commentary": [
                    {"asset_class": "국내주식", "past": "+30%", "outlook": "강세 지속"},
                    {"asset_class": "해외주식", "past": "+10%", "outlook": "AI 모멘텀"},
                ],
                "asset_movement_commentary_fallback": [],
            },
            "bear": {
                "agent": "bear", "stance": "bearish",
                "asset_movement_commentary": [
                    {"asset_class": "국내채권", "past": "+0.3%", "outlook": "인플레 부담"},
                ],
                "asset_movement_commentary_fallback": [],
            },
            "quant": {"agent": "quant", "stance": "neutral",
                      "asset_movement_commentary": []},
            "monygeek": {"agent": "monygeek", "stance": "neutral",
                         "asset_movement_commentary_warnings": ["empty response"]},
        },
        "asset_movement_anchors": {
            "asset_movements": [
                {"asset_class": "국내주식", "monthly_return": 0.3069,
                 "ytd_return": 0.5791, "importance": 0.95},
                {"asset_class": "해외주식", "monthly_return": 0.1042,
                 "ytd_return": 0.0531, "importance": 0.78},
            ],
            "snapshot_date": "2026-04-30",
        },
        "asset_movement_commentary": [
            {"asset_class": "국내주식", "summary": "이란 휴전 + 반도체 호조",
             "supporting_evidence": ["ref:1", "ref:3"]},
            {"asset_class": "해외주식", "summary": "AI 빅테크 반등",
             "supporting_evidence": ["ref:2"]},
        ],
        "asset_movement_commentary_fallback": [
            {"asset_class": "국내채권", "method": "deterministic",
             "summary": "anchor 기반 정성"},
        ],
        "asset_movement_commentary_warnings_by_agent": {
            "monygeek": ["empty response"],
        },
        "synthesis": {
            "customer_comment": "test market view",
            "consensus_points": ["c1"], "disagreements": [],
            "tail_risks": ["risk1"], "admin_summary": "",
        },
        "debate_narrative": {
            "debate_narrative": "", "canonical_snapshot": {},
            "diverges_from_canonical": False,
        },
        "_evidence_ids": [],
    }


def _patch_debate_engine(monkeypatch, stub_result):
    """debate_engine.run_market_debate 를 stub 으로 치환."""
    from market_research.report import debate_engine

    def _stub(year, month, **kw):
        return stub_result

    monkeypatch.setattr(debate_engine, "run_market_debate", _stub)
    monkeypatch.setattr(
        "market_research.report.debate_engine.run_market_debate", _stub,
    )


# ────────────────────────────────────────────────────────────────────
# 1) 모든 R8-B 키가 result 에 있을 때 draft 에 보존
# ────────────────────────────────────────────────────────────────────

def test_r8b_full_preservation_to_draft(monkeypatch, tmp_report_root):
    from market_research.report import debate_service, report_store

    stub = _build_result_with_r8b()
    _patch_debate_engine(monkeypatch, stub)

    period, fund = "2026-04", "_market"
    draft = debate_service.run_debate_and_save("월별", 2026, 4, fund, period)

    # in-memory draft 검증
    assert draft["asset_movement_anchors"] == stub["asset_movement_anchors"]
    assert draft["asset_movement_commentary"] == stub["asset_movement_commentary"]
    assert draft["asset_movement_commentary_fallback"] == \
        stub["asset_movement_commentary_fallback"]
    assert draft["asset_movement_commentary_warnings_by_agent"] == \
        stub["asset_movement_commentary_warnings_by_agent"]
    assert draft["agents"] == stub["agents"]

    # disk draft 검증 (raw → JSON 직렬화 round-trip)
    on_disk = report_store.load_draft(period, fund)
    assert "asset_movement_anchors" in on_disk
    assert isinstance(on_disk["asset_movement_anchors"], dict)
    assert "asset_movements" in on_disk["asset_movement_anchors"]
    assert len(on_disk["asset_movement_commentary"]) == 2
    assert len(on_disk["asset_movement_commentary_fallback"]) == 1
    assert "monygeek" in on_disk["asset_movement_commentary_warnings_by_agent"]
    assert "bull" in on_disk["agents"]
    # nested agent 필드도 round-trip 보존
    assert len(on_disk["agents"]["bull"]["asset_movement_commentary"]) == 2


# ────────────────────────────────────────────────────────────────────
# 2) R8-B 키가 일부만 있을 때 있는 것만 보존 (backward compat)
# ────────────────────────────────────────────────────────────────────

def test_r8b_partial_preservation(monkeypatch, tmp_report_root):
    from market_research.report import debate_service, report_store

    stub = _build_result_with_r8b()
    # 일부 키 의도적으로 제거 (debate_engine 의 옛 버전 또는 fallback 흐름 시나리오)
    del stub["asset_movement_commentary_fallback"]
    del stub["asset_movement_commentary_warnings_by_agent"]
    _patch_debate_engine(monkeypatch, stub)

    period, fund = "2026-04", "_market"
    draft = debate_service.run_debate_and_save("월별", 2026, 4, fund, period)

    # 있는 키만 박힘
    assert "asset_movement_anchors" in draft
    assert "asset_movement_commentary" in draft
    assert "agents" in draft
    # 없는 키는 추가되지 않음 (None / [] 자동 채움 금지)
    assert "asset_movement_commentary_fallback" not in draft
    assert "asset_movement_commentary_warnings_by_agent" not in draft

    on_disk = report_store.load_draft(period, fund)
    assert "asset_movement_anchors" in on_disk
    assert "asset_movement_commentary_fallback" not in on_disk


# ────────────────────────────────────────────────────────────────────
# 3) R8-B 키가 전혀 없을 때 (legacy debate result) 기존 draft 경로 무영향
# ────────────────────────────────────────────────────────────────────

def test_r8b_absent_legacy_compat(monkeypatch, tmp_report_root):
    from market_research.report import debate_service, report_store

    legacy_result = {
        "year": 2026, "month": 4,
        "debate_run_id": "b" * 32,
        "debated_at": "2026-04-20T10:00:00",
        "agents": {},   # empty dict — R8-B 도입 전 agent output 공백
        "synthesis": {
            "customer_comment": "legacy comment", "consensus_points": [],
            "disagreements": [], "tail_risks": [], "admin_summary": "",
        },
        "debate_narrative": {
            "debate_narrative": "", "canonical_snapshot": {},
            "diverges_from_canonical": False,
        },
        "_evidence_ids": [],
    }
    _patch_debate_engine(monkeypatch, legacy_result)

    period, fund = "2026-04", "_market"
    draft = debate_service.run_debate_and_save("월별", 2026, 4, fund, period)

    # 기존 필드 정상
    assert draft["draft_comment"] == "legacy comment"
    assert draft["debate_run_id"] == "b" * 32

    # R8-B amc 키 부재 (None / [] 으로 채우지 않음)
    assert "asset_movement_anchors" not in draft
    assert "asset_movement_commentary" not in draft
    assert "asset_movement_commentary_fallback" not in draft
    assert "asset_movement_commentary_warnings_by_agent" not in draft
    # agents 는 result 에 존재하므로 (빈 dict 라도) 보존
    assert draft["agents"] == {}

    on_disk = report_store.load_draft(period, fund)
    assert on_disk["draft_comment"] == "legacy comment"
    assert "asset_movement_anchors" not in on_disk


# ────────────────────────────────────────────────────────────────────
# 4) 보존된 draft 를 fund_comment_service._market_comment_to_inputs 가 pass-through
# ────────────────────────────────────────────────────────────────────

def test_market_comment_to_inputs_pass_through(monkeypatch, tmp_report_root):
    """draft 에 박힌 amc 가 fund_comment inputs 로 바로 흘러간다."""
    from market_research.report import debate_service, report_store
    from market_research.report.fund_comment_service import _market_comment_to_inputs

    stub = _build_result_with_r8b()
    _patch_debate_engine(monkeypatch, stub)

    period, fund = "2026-04", "_market"
    debate_service.run_debate_and_save("월별", 2026, 4, fund, period)
    market_payload = report_store.load_draft(period, fund)

    inputs = _market_comment_to_inputs(market_payload)

    assert "asset_movement_commentary" in inputs
    assert len(inputs["asset_movement_commentary"]) == 2
    assert inputs["asset_movement_commentary"][0]["asset_class"] == "국내주식"

    assert "asset_movement_anchors" in inputs
    assert "asset_movements" in inputs["asset_movement_anchors"]
    assert len(inputs["asset_movement_anchors"]["asset_movements"]) == 2


def test_market_comment_to_inputs_handles_empty_amc(monkeypatch, tmp_report_root):
    """legacy draft (amc 부재) 를 입력해도 inputs 변환이 깨지지 않고 amc 키 부재."""
    from market_research.report.fund_comment_service import _market_comment_to_inputs

    legacy_payload = {
        "draft_comment": "legacy",
        "consensus_points": [], "disagreements": [], "tail_risks": [],
        "evidence_annotations": [],
        # asset_movement_* 키 자체 부재
    }
    inputs = _market_comment_to_inputs(legacy_payload)

    assert "asset_movement_commentary" not in inputs
    assert "asset_movement_anchors" not in inputs
    assert inputs.get("market_view") == "legacy"
