"""R6-A 회귀: fund_comment_service evidence pass-through + comment_trace draft_comment_raw 인식.

LLM 호출 0. DB 의존 0. 디스크: tmp_path 만 사용.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────
# fund_comment_service._market_comment_to_inputs
# ──────────────────────────────────────────────────────────────────

def test_market_to_inputs_passes_evidence_annotations():
    """market_payload.evidence_annotations → inputs.evidence_annotations."""
    from market_research.report.fund_comment_service import (
        _market_comment_to_inputs,
    )
    payload = {
        "final_comment": "시장 코멘트 본문 [ref:1].",
        "consensus_points": ["A", "B"],
        "evidence_annotations": [
            {"ref": 1, "article_id": "a1", "title": "T1"},
            {"ref": 2, "article_id": "a2", "title": "T2"},
        ],
    }
    inputs = _market_comment_to_inputs(payload)
    assert inputs["market_view"].startswith("시장 코멘트")
    assert "evidence_annotations" in inputs
    assert len(inputs["evidence_annotations"]) == 2
    assert inputs["evidence_annotations"][0]["article_id"] == "a1"


def test_market_to_inputs_no_evidence():
    """ann 없을 때 evidence_annotations key 미생성 (legacy 호환)."""
    from market_research.report.fund_comment_service import (
        _market_comment_to_inputs,
    )
    inputs = _market_comment_to_inputs({"final_comment": "X"})
    assert "evidence_annotations" not in inputs


def test_market_to_inputs_empty_payload():
    from market_research.report.fund_comment_service import (
        _market_comment_to_inputs,
    )
    assert _market_comment_to_inputs({}) == {}
    assert _market_comment_to_inputs(None) == {}  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────
# build_report_prompt evidence_block
# ──────────────────────────────────────────────────────────────────

def test_build_report_prompt_includes_evidence_block(monkeypatch):
    """inputs.evidence_annotations 가 있으면 prompt 에 인용 가이드 + ref 목록 포함."""
    from market_research.report import comment_engine
    inputs = {
        "market_view": "시장",
        "evidence_annotations": [
            {"ref": 1, "article_id": "a1", "title": "유가 100달러", "source": "Reuters", "date": "2026-04-15"},
            {"ref": 2, "article_id": "a2", "title": "금 하락", "source": "Bloomberg", "date": "2026-04-20"},
        ],
    }
    data_ctx = {
        "bm": {}, "fund_ret": None, "pa": {},
        "holdings_end": {}, "holdings_diff": [],
        "price_patterns": {},
    }
    p = comment_engine.build_report_prompt(
        "08K88", 2026, 1, data_ctx, inputs,
    )
    assert "인용 가능한 증거 자료" in p
    assert "[ref:1] 유가 100달러" in p
    assert "[ref:2] 금 하락" in p
    assert "Reuters" in p
    assert "증거 인용 규칙" in p


def test_build_report_prompt_no_evidence_block_when_empty():
    """evidence_annotations 없으면 evidence_block 미생성."""
    from market_research.report import comment_engine
    p = comment_engine.build_report_prompt(
        "08K88", 2026, 1,
        {"bm": {}, "fund_ret": None, "pa": {}, "holdings_end": {},
         "holdings_diff": [], "price_patterns": {}},
        {"market_view": "X"},
    )
    assert "인용 가능한 증거 자료" not in p
    assert "증거 인용 규칙" not in p


# ──────────────────────────────────────────────────────────────────
# comment_trace.build_trace 가 draft_comment_raw 우선 사용
# ──────────────────────────────────────────────────────────────────

def _write_draft(tmp_path: Path, period: str, fund: str, payload: dict) -> Path:
    """report_output/{period}/{fund}.draft.json 작성."""
    pdir = tmp_path / "market_research" / "data" / "report_output" / period
    pdir.mkdir(parents=True, exist_ok=True)
    fp = pdir / f"{fund}.draft.json"
    fp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return fp


def test_comment_trace_uses_draft_comment_raw(tmp_path, monkeypatch):
    """R6-A draft schema (draft_comment_raw + comment_citations + citation_validation)
    인식 → attribution_method=explicit_ref + citation_validation surface."""
    import importlib
    import tools.comment_trace as ct
    importlib.reload(ct)
    monkeypatch.setattr(ct, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ct, "REPORT_OUTPUT_DIR",
                        tmp_path / "market_research" / "data" / "report_output")
    monkeypatch.setattr(ct, "INCIDENTS_DIR", tmp_path / "debug" / "incidents")

    period = "2026-Q1"
    fund = "08K88"
    payload = {
        "fund_code": fund,
        "period": period,
        "report_type": "fund",
        "status": "draft",
        "debate_run_id": "RUN_TEST",
        # 고객용 (sanitized)
        "draft_comment": "■ 시장\nWTI 는 100달러를 돌파했습니다.\n\n■ 펀드\n수익률 +2%.",
        # admin/trace 용 (raw, [ref:N] 포함)
        "draft_comment_raw": "■ 시장\nWTI 는 100달러를 돌파했습니다 [ref:1].\n\n■ 펀드\n수익률 +2%.",
        "comment_citations": [
            {"section_id": "00_시장", "section_title": "시장", "ref_ids": [1],
             "evidence_ids": ["a1"], "citation_type": "explicit_ref"},
            {"section_id": "01_펀드", "section_title": "펀드", "ref_ids": [],
             "evidence_ids": [], "citation_type": "section_default"},
        ],
        "citation_validation": {
            "explicit_ref_count": 1, "invalid_ref_count": 0,
            "sections_with_ref_count": 1, "sections_without_ref_count": 1,
            "warnings": [],
        },
        "evidence_annotations": [
            {"ref": 1, "article_id": "a1", "title": "유가 100달러", "source": "Reuters"},
        ],
        "data_snapshot": {"fund_return": 2.0, "pa_classes": ["국내주식"],
                          "holdings_top3": [], "trades": {}, "bm_count": 5},
        "inputs_used": {},
    }
    _write_draft(tmp_path, period, fund, payload)

    trace = ct.build_trace(period, fund, market_source_mode="auto")

    # raw 가 우선되어 ref:1 매칭 → 시장 section explicit_ref
    methods = trace["attribution_method_summary"]
    assert methods.get("explicit_ref", 0) == 1
    assert methods.get("section_default", 0) == 1

    # citation_validation surfaced
    assert trace["citation_validation"] is not None
    assert trace["citation_validation"]["explicit_ref_count"] == 1
    assert trace["citation_validation"]["invalid_ref_count"] == 0


def test_comment_trace_legacy_draft_still_works(tmp_path, monkeypatch):
    """legacy draft (draft_comment 만 있음, [ref:N] 없음) → section_default fallback."""
    import importlib
    import tools.comment_trace as ct
    importlib.reload(ct)
    monkeypatch.setattr(ct, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ct, "REPORT_OUTPUT_DIR",
                        tmp_path / "market_research" / "data" / "report_output")
    monkeypatch.setattr(ct, "INCIDENTS_DIR", tmp_path / "debug" / "incidents")

    period = "2026-Q1"
    fund = "07G04"
    payload = {
        "fund_code": fund, "period": period, "report_type": "fund",
        "status": "draft",
        "debate_run_id": "RUN_LEGACY",
        # legacy: draft_comment 만, [ref:N] 없음
        "draft_comment": "■ 시장\n본문.\n\n■ 펀드\n본문.",
        "data_snapshot": {"fund_return": None, "pa_classes": [],
                          "holdings_top3": [], "trades": {}, "bm_count": 0},
        "inputs_used": {},
    }
    _write_draft(tmp_path, period, fund, payload)

    trace = ct.build_trace(period, fund, market_source_mode="auto")
    methods = trace["attribution_method_summary"]
    # 둘 다 section_default
    assert methods.get("section_default", 0) == 2
    assert methods.get("explicit_ref", 0) == 0
    # citation_validation 은 없음 (legacy)
    assert trace["citation_validation"] is None


def test_comment_trace_invalid_ref_in_raw(tmp_path, monkeypatch):
    """draft_comment_raw 의 ref 가 evidence_annotations 에 없으면 warning 발생,
    ref_ids 는 그대로, evidence_ids 비어있음."""
    import importlib
    import tools.comment_trace as ct
    importlib.reload(ct)
    monkeypatch.setattr(ct, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ct, "REPORT_OUTPUT_DIR",
                        tmp_path / "market_research" / "data" / "report_output")
    monkeypatch.setattr(ct, "INCIDENTS_DIR", tmp_path / "debug" / "incidents")

    period = "2026-04"
    fund = "08K88"
    payload = {
        "fund_code": fund, "period": period, "report_type": "fund",
        "status": "draft",
        "debate_run_id": "RUN_X",
        "draft_comment": "본문.",
        "draft_comment_raw": "본문 [ref:99].",
        "evidence_annotations": [{"ref": 1, "article_id": "a1", "title": "T1"}],
        "data_snapshot": {"fund_return": None, "pa_classes": [],
                          "holdings_top3": [], "trades": {}, "bm_count": 0},
        "inputs_used": {},
    }
    _write_draft(tmp_path, period, fund, payload)

    trace = ct.build_trace(period, fund, market_source_mode="auto")
    attrs = trace["section_attribution"]
    # 단일 main section, ref:99 unmatched → ref_ids=[99] but evidence_ids 비어있고 warning
    s = attrs[0]
    assert 99 in s["ref_ids"]
    assert s["evidence_ids"] == []
    assert any("ref:99" in w for w in s["warnings"])
