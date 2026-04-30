"""P3: Fund viewer 의 linked market evidence fan-out tests.

펀드 lineage 와 시장 lineage 분리 검증, 누출 회귀 차단.
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    """report_store.OUTPUT_DIR 을 tmp_path 로 치환 + macro_service stub."""
    from market_research.report import report_store
    from api.services import report_service

    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)

    def _empty_macro(keys=None, start_date=None):
        from api.schemas.macro import MacroTimeseriesResponseDTO
        from api.schemas.meta import BaseMeta
        from datetime import datetime, timezone
        return MacroTimeseriesResponseDTO(
            meta=BaseMeta(
                as_of_date=None, source="mock", sources=[],
                is_fallback=True, warnings=["test stub"],
                generated_at=datetime.now(timezone.utc),
            ),
            series=[],
        )
    monkeypatch.setattr(
        report_service.macro_service, "build_macro_timeseries", _empty_macro,
    )
    return root


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _market_final(period: str, run_id: str | None = "MARKET-RID-1") -> dict:
    return {
        "fund_code": "_market",
        "period": period,
        "status": "approved",
        "approved": True,
        "approved_at": "2026-04-30T14:00:45",
        "approved_by": "admin",
        "approved_debate_run_id": run_id,
        "generated_at": "2026-04-30T13:56:04",
        "final_comment": "market comment",
        "model": "claude-opus-4-7",
        "consensus_points": ["mkt cp1"],
        "tail_risks": ["mkt tr1"],
    }


def _market_draft(period: str, run_id: str | None = "MARKET-RID-1") -> dict:
    return {
        "fund_code": "_market",
        "period": period,
        "status": "approved",
        "draft_comment": "market draft",
        "debate_run_id": run_id,
        "generated_at": "2026-04-30T13:56:04",
        "evidence_annotations": [
            {"ref": 1, "article_id": "a1", "title": "T1", "url": "http://x/1",
             "source": "S1", "date": "2026-04-08", "topic": "지정학",
             "salience": 1.0},
            {"ref": 2, "article_id": "a2", "title": "T2", "url": "http://x/2",
             "source": "S2", "date": "2026-04-09", "topic": "에너지_원자재",
             "salience": 0.9},
        ],
        "related_news": [
            {"ref": 3, "article_id": "a3", "title": "RN1", "url": "http://x/3",
             "source": "S3", "date": "2026-04-10", "topic": "크립토",
             "salience": 0.7},
        ],
        "evidence_quality": {"total_refs": 2, "evidence_count": 3,
                             "ref_mismatches": 0},
        "validation_summary": {"sanitize_warnings": [], "warning_counts": {}},
    }


def _fund_final(period: str, fund: str, run_id: str = "FUND-RID-1",
                market_debate_period: str | None = None) -> dict:
    p = {
        "fund_code": fund,
        "period": period,
        "status": "approved",
        "approved": True,
        "approved_at": "2026-04-30T14:15:58",
        "approved_by": "admin",
        "approved_debate_run_id": run_id,
        "generated_at": "2026-04-30T13:58:00",
        "final_comment": f"fund comment for {fund}",
        "model": "claude-sonnet-4-6",
        "consensus_points": [],
        "tail_risks": [],
    }
    if market_debate_period:
        p["market_debate_period"] = market_debate_period
    return p


def _fund_draft(period: str, fund: str, run_id: str = "FUND-RID-1",
                market_debate_period: str | None = None) -> dict:
    d = {
        "fund_code": fund,
        "period": period,
        "report_type": "펀드",
        "status": "approved",
        "draft_comment": f"fund draft for {fund}",
        "debate_run_id": run_id,
        "generated_at": "2026-04-30T13:58:00",
    }
    if market_debate_period:
        d["market_debate_period"] = market_debate_period
    return d


# ─────────────────────────────────────────────────────────────────────
# Happy path: market_enrichment 가 _market final 에서 fan-out
# ─────────────────────────────────────────────────────────────────────

def test_market_enrichment_fanout_happy(client, tmp_report_root):
    _write(tmp_report_root / "2026-04" / "_market.final.json", _market_final("2026-04"))
    _write(tmp_report_root / "2026-04" / "_market.draft.json", _market_draft("2026-04"))
    _write(tmp_report_root / "2026-04" / "08K88.final.json", _fund_final("2026-04", "08K88"))
    _write(tmp_report_root / "2026-04" / "08K88.draft.json", _fund_draft("2026-04", "08K88"))

    r = client.get("/api/funds/08K88/report", params={"period": "2026-04"})
    assert r.status_code == 200
    me = r.json()["data"]["market_enrichment"]
    assert me is not None
    assert me["market_period"] == "2026-04"
    assert me["market_period_fallback"] is True   # market_debate_period 키 없음 → fallback
    assert me["source_consistency_status"] == "matched_by_id"
    assert me["evidence_annotations_source"] == "approved"
    assert me["related_news_source"] == "approved"
    assert len(me["evidence_annotations"]) == 2
    assert len(me["related_news"]) == 1
    refs = [it["ref"] for it in me["evidence_annotations"]]
    assert refs == [1, 2]


# ─────────────────────────────────────────────────────────────────────
# Fund 자체 evidence=0 이어도 market_enrichment 는 노출
# ─────────────────────────────────────────────────────────────────────

def test_market_fanout_independent_of_fund_lineage(client, tmp_report_root):
    """펀드 draft 에 자체 evidence 가 없어도(구조적 정상) market_enrichment 는 채워져야 함."""
    _write(tmp_report_root / "2026-04" / "_market.final.json", _market_final("2026-04"))
    _write(tmp_report_root / "2026-04" / "_market.draft.json", _market_draft("2026-04"))
    _write(tmp_report_root / "2026-04" / "07G04.final.json", _fund_final("2026-04", "07G04"))
    _write(tmp_report_root / "2026-04" / "07G04.draft.json", _fund_draft("2026-04", "07G04"))

    r = client.get("/api/funds/07G04/report", params={"period": "2026-04"})
    assert r.status_code == 200
    body = r.json()
    # 펀드 자체 enrichment 는 비어있을 수 있음 (펀드 draft 에 evidence 없음)
    assert len(body["data"]["enrichment"]["evidence_annotations"]) == 0
    # 그러나 market_enrichment 는 채워짐
    me = body["data"]["market_enrichment"]
    assert me["source_consistency_status"] == "matched_by_id"
    assert len(me["evidence_annotations"]) == 2


# ─────────────────────────────────────────────────────────────────────
# market final 부재 → unavailable
# ─────────────────────────────────────────────────────────────────────

def test_market_fanout_market_missing(client, tmp_report_root):
    _write(tmp_report_root / "2026-04" / "08K88.final.json", _fund_final("2026-04", "08K88"))
    _write(tmp_report_root / "2026-04" / "08K88.draft.json", _fund_draft("2026-04", "08K88"))

    r = client.get("/api/funds/08K88/report", params={"period": "2026-04"})
    assert r.status_code == 200
    me = r.json()["data"]["market_enrichment"]
    assert me["source_consistency_status"] == "unavailable"
    assert me["evidence_annotations"] == []
    assert me["related_news"] == []
    assert me["evidence_annotations_source"] == "unavailable"
    assert me["related_news_source"] == "unavailable"


# ─────────────────────────────────────────────────────────────────────
# market final 있으나 not approved → unavailable
# ─────────────────────────────────────────────────────────────────────

def test_market_fanout_market_not_approved(client, tmp_report_root):
    mp = _market_final("2026-04")
    mp["approved"] = False
    _write(tmp_report_root / "2026-04" / "_market.final.json", mp)
    _write(tmp_report_root / "2026-04" / "_market.draft.json", _market_draft("2026-04"))
    _write(tmp_report_root / "2026-04" / "08K88.final.json", _fund_final("2026-04", "08K88"))
    _write(tmp_report_root / "2026-04" / "08K88.draft.json", _fund_draft("2026-04", "08K88"))

    r = client.get("/api/funds/08K88/report", params={"period": "2026-04"})
    assert r.status_code == 200
    me = r.json()["data"]["market_enrichment"]
    assert me["source_consistency_status"] == "unavailable"
    assert me["evidence_annotations"] == []


# ─────────────────────────────────────────────────────────────────────
# market id_mismatch → market_enrichment 차단
# ─────────────────────────────────────────────────────────────────────

def test_market_fanout_id_mismatch_blocks_evidence(client, tmp_report_root):
    """market final.approved_debate_run_id 와 draft.debate_run_id 가 다르면 차단."""
    _write(tmp_report_root / "2026-04" / "_market.final.json",
           _market_final("2026-04", run_id="MARKET-RID-A"))
    _write(tmp_report_root / "2026-04" / "_market.draft.json",
           _market_draft("2026-04", run_id="MARKET-RID-B"))   # 다른 ID
    _write(tmp_report_root / "2026-04" / "08K88.final.json", _fund_final("2026-04", "08K88"))
    _write(tmp_report_root / "2026-04" / "08K88.draft.json", _fund_draft("2026-04", "08K88"))

    r = client.get("/api/funds/08K88/report", params={"period": "2026-04"})
    assert r.status_code == 200
    me = r.json()["data"]["market_enrichment"]
    assert me["source_consistency_status"] == "id_mismatch"
    assert me["evidence_annotations"] == []
    assert me["evidence_annotations_source"] == "unavailable"


# ─────────────────────────────────────────────────────────────────────
# market_debate_period 키 사용 (다른 기간 참조)
# ─────────────────────────────────────────────────────────────────────

def test_market_fanout_uses_explicit_market_debate_period(client, tmp_report_root):
    """fund draft 의 market_debate_period 가 있으면 그 기간을 사용 (fallback=False)."""
    _write(tmp_report_root / "2026-Q1" / "_market.final.json", _market_final("2026-Q1"))
    _write(tmp_report_root / "2026-Q1" / "_market.draft.json", _market_draft("2026-Q1"))
    _write(tmp_report_root / "2026-04" / "08K88.final.json",
           _fund_final("2026-04", "08K88"))
    _write(tmp_report_root / "2026-04" / "08K88.draft.json",
           _fund_draft("2026-04", "08K88", market_debate_period="2026-Q1"))

    r = client.get("/api/funds/08K88/report", params={"period": "2026-04"})
    assert r.status_code == 200
    me = r.json()["data"]["market_enrichment"]
    assert me["market_period"] == "2026-Q1"
    assert me["market_period_fallback"] is False
    assert me["source_consistency_status"] == "matched_by_id"
    assert len(me["evidence_annotations"]) == 2


# ─────────────────────────────────────────────────────────────────────
# 시장 코멘트 자체 응답에는 market_enrichment 가 없다
# ─────────────────────────────────────────────────────────────────────

def test_market_endpoint_does_not_include_market_enrichment(client, tmp_report_root):
    _write(tmp_report_root / "2026-04" / "_market.final.json", _market_final("2026-04"))
    _write(tmp_report_root / "2026-04" / "_market.draft.json", _market_draft("2026-04"))

    r = client.get("/api/market-report", params={"period": "2026-04"})
    assert r.status_code == 200
    assert r.json()["data"]["market_enrichment"] is None


# ─────────────────────────────────────────────────────────────────────
# Client leak regression (P3 추가 경로)
# ─────────────────────────────────────────────────────────────────────

FORBIDDEN_SUBSTRINGS = (
    "internal_source",
    "evidence_annotations_internal_source",
    "related_news_internal_source",
    "evidence_quality_internal_source",
    "validation_summary_internal_source",
    "indicator_chart_internal_source",
    "source_consistency_reason",
    "debate_run_id",
    "approved_debate_run_id",
    "draft_run_id",
)


def test_market_fanout_no_internal_leakage(client, tmp_report_root):
    _write(tmp_report_root / "2026-04" / "_market.final.json", _market_final("2026-04"))
    _write(tmp_report_root / "2026-04" / "_market.draft.json", _market_draft("2026-04"))
    _write(tmp_report_root / "2026-04" / "08K88.final.json", _fund_final("2026-04", "08K88"))
    _write(tmp_report_root / "2026-04" / "08K88.draft.json", _fund_draft("2026-04", "08K88"))

    r = client.get("/api/funds/08K88/report", params={"period": "2026-04"})
    assert r.status_code == 200
    raw = r.text
    leaks = [k for k in FORBIDDEN_SUBSTRINGS if k in raw]
    assert leaks == [], f"forbidden keys leaked: {leaks}"


def test_market_fanout_no_leakage_when_id_mismatch(client, tmp_report_root):
    """차단 경로에서도 source_consistency_reason / run_id 누출 0건."""
    _write(tmp_report_root / "2026-04" / "_market.final.json",
           _market_final("2026-04", run_id="MARKET-RID-A"))
    _write(tmp_report_root / "2026-04" / "_market.draft.json",
           _market_draft("2026-04", run_id="MARKET-RID-B"))
    _write(tmp_report_root / "2026-04" / "08K88.final.json", _fund_final("2026-04", "08K88"))
    _write(tmp_report_root / "2026-04" / "08K88.draft.json", _fund_draft("2026-04", "08K88"))

    r = client.get("/api/funds/08K88/report", params={"period": "2026-04"})
    raw = r.text
    leaks = [k for k in FORBIDDEN_SUBSTRINGS if k in raw]
    assert leaks == [], f"forbidden keys leaked on id_mismatch path: {leaks}"
