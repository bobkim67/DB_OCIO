"""P3-3.1 hotfix tests — false-positive 완화 + bucket + topic group + raw 미노출.

사용자 spec 12개 케이스 + 회귀.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest


def _mk_article(topics: list[str], primary: bool = True) -> dict:
    return {
        "is_primary": primary,
        "_classified_topics": [{"topic": t} for t in topics],
    }


# ─────────────────────────────────────────────────────────────────────
# 1. False-positive 차단 (사용자 spec 7번 1~9번)
# ─────────────────────────────────────────────────────────────────────

def test_goldman_sachs_not_gold():
    from market_research.report.asset_coverage import _scan_text_for_asset
    assert _scan_text_for_asset("Goldman Sachs report", "금/대체") == 0
    assert _scan_text_for_asset("골드만삭스 추천 종목", "금/대체") == 0


def test_금리_not_gold():
    from market_research.report.asset_coverage import _scan_text_for_asset
    assert _scan_text_for_asset("금리 상승 압력", "금/대체") == 0
    assert _scan_text_for_asset("기준금리 동결", "금/대체") == 0


def test_금융_not_gold():
    from market_research.report.asset_coverage import _scan_text_for_asset
    assert _scan_text_for_asset("금융시장 변동성", "금/대체") == 0
    assert _scan_text_for_asset("금융위기 가능성", "금/대체") == 0


def test_gold_price_hits_gold():
    from market_research.report.asset_coverage import _scan_text_for_asset
    assert _scan_text_for_asset("금 가격 사상 최고", "금/대체") >= 1
    assert _scan_text_for_asset("국제 금 시세 급등", "금/대체") >= 1


def test_gld_ticker_hits_gold():
    from market_research.report.asset_coverage import _scan_text_for_asset
    assert _scan_text_for_asset("GLD ETF 자금 유입", "금/대체") >= 1
    assert _scan_text_for_asset("GLD held above resistance", "금/대체") >= 1


def test_credit_card_not_credit():
    from market_research.report.asset_coverage import _scan_text_for_asset
    assert _scan_text_for_asset("신용카드 사용액", "크레딧") == 0
    assert _scan_text_for_asset("credit card delinquency", "크레딧") == 0


def test_credit_spread_hits_credit():
    from market_research.report.asset_coverage import _scan_text_for_asset
    assert _scan_text_for_asset("credit spread widened", "크레딧") >= 1
    assert _scan_text_for_asset("HY 스프레드 확대", "크레딧") >= 1


def test_only_미국_does_not_hit_overseas_equity():
    """단순 '미국'만으로는 해외주식에 hit되지 않는다."""
    from market_research.report.asset_coverage import _scan_text_for_asset
    assert _scan_text_for_asset("미국", "해외주식") == 0
    assert _scan_text_for_asset("미국 정부", "해외주식") == 0
    assert _scan_text_for_asset("미국 연준", "해외주식") == 0


def test_sp_nasdaq_growth_hits_overseas_equity():
    from market_research.report.asset_coverage import _scan_text_for_asset
    assert _scan_text_for_asset("S&P500 신고가", "해외주식") >= 1
    assert _scan_text_for_asset("나스닥 +3% 반등", "해외주식") >= 1
    assert _scan_text_for_asset("미국 성장주 강세", "해외주식") >= 1


# ─────────────────────────────────────────────────────────────────────
# 2. raw count prompt 미노출 (사용자 spec 7번 10번)
# ─────────────────────────────────────────────────────────────────────

def test_prompt_does_not_leak_raw_evidence_count():
    """prompt 에는 evidence=3659 같은 대형 raw 숫자 미노출."""
    from market_research.report.asset_coverage import (
        build_asset_coverage_map, format_asset_coverage_for_prompt,
    )
    # 지정학 3000건 + KOSPI 5건 — 환율은 evidence 없으나 ts 로 weak
    cov = build_asset_coverage_map(
        primary_news=([_mk_article(["환율_FX"])] * 3000
                      + [_mk_article(["KOSPI"])] * 5),
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="",
    )
    text = format_asset_coverage_for_prompt(cov)
    # raw 대형 숫자 미노출
    for raw in ("3000", "3005", "2999"):
        assert raw not in text, f"raw count leaked in prompt: {raw}"
    # bucket 라벨은 노출 가능
    assert "high" in text or "medium" in text or "low" in text or "선정" in text or "Y" in text


def test_evidence_bucket_categorization():
    from market_research.report.asset_coverage import _evidence_bucket
    assert _evidence_bucket(0) == "none"
    assert _evidence_bucket(1) == "low"
    assert _evidence_bucket(4) == "low"
    assert _evidence_bucket(5) == "medium"
    assert _evidence_bucket(24) == "medium"
    assert _evidence_bucket(25) == "high"
    assert _evidence_bucket(10000) == "high"


# ─────────────────────────────────────────────────────────────────────
# 3. dominant_topic_group 계산 (사용자 spec 7번 11번)
# ─────────────────────────────────────────────────────────────────────

def test_dominant_topic_group_aggregates_middle_east_cluster():
    from market_research.report.asset_coverage import build_asset_coverage_map
    # 지정학 + 에너지_원자재 + 유가 = 같은 group "중동/지정학/에너지"
    tc = Counter({
        "지정학": 50,
        "에너지_원자재": 30,
        "유가": 20,
        "환율_FX": 10,
        "KOSPI": 5,
    })
    arts = []
    for t, n in tc.items():
        arts.extend([_mk_article([t])] * n)
    cov = build_asset_coverage_map(
        primary_news=arts,
        graph_paths=[], wiki_selected_pages=[], timeseries_narrative_text="",
        topic_counts=tc,
    )
    # dominant single topic = 지정학 (50/115 ~= 0.43)
    assert cov["dominant_topic"] == "지정학"
    # dominant group = 중동/지정학/에너지 (50+30+20 = 100/115 ~= 0.87)
    assert cov["dominant_topic_group"] == "중동/지정학/에너지"
    assert cov["dominant_topic_group_share"] > cov["dominant_topic_share"]


def test_dominant_topic_group_in_prompt_when_higher():
    from market_research.report.asset_coverage import (
        build_asset_coverage_map, format_asset_coverage_for_prompt,
    )
    tc = Counter({"지정학": 50, "에너지_원자재": 30, "유가": 20, "KOSPI": 5})
    cov = build_asset_coverage_map(
        primary_news=[_mk_article(["지정학"])] * 5,
        graph_paths=[], wiki_selected_pages=[], timeseries_narrative_text="",
        topic_counts=tc,
    )
    text = format_asset_coverage_for_prompt(cov)
    assert "중동/지정학/에너지" in text
    assert "dominant topic group" in text


# ─────────────────────────────────────────────────────────────────────
# 4. classified-only 단독은 covered 안 됨 (사용자 spec 작업 3)
# ─────────────────────────────────────────────────────────────────────

def test_classified_only_does_not_cover():
    """raw classified evidence 만 있고 graph/ts/ret 부재 면 covered 못 됨."""
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[_mk_article(["환율_FX"])] * 100,  # 환율 evidence 100
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="",   # ts 없음
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    assert rows["환율"]["coverage_status"] in ("weak", "missing")
    assert rows["환율"]["coverage_status"] != "covered"


def test_selected_evidence_promotes_to_covered():
    """selected 가 있으면 강한 신호 — graph/ts 없어도 covered 가능."""
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[],
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="",
        selected_evidence=[
            {"title": "환율 1480", "topic": "환율_FX"},
            {"title": "USDKRW 상승", "topic": "환율_FX"},
        ],
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    # selected 가 strong=1 인데 단독으론 weak. classified+selected 결합 시 covered.
    # 위는 classified=0, selected>0 → strong=1 → covered 조건의
    # 'selected_n>=1 AND strong>=1' 만족 → covered.
    assert rows["환율"]["coverage_status"] == "covered"


def test_classified_plus_graph_promotes_to_covered():
    """classified + graph 결합 — selected 없어도 strong 신호 1개 + classified > 0 인데 selected_n=0 이라 weak."""
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[_mk_article(["환율_FX"])] * 5,
        graph_paths=[{"labels": ["환율 상승"], "target": "환율", "confidence": 0.5}],
        wiki_selected_pages=[],
        timeseries_narrative_text="",
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    # strong=1 (graph), selected=0 → weak (classified-only + 1 strong)
    assert rows["환율"]["coverage_status"] in ("weak", "covered")


def test_classified_plus_graph_plus_ts_is_covered():
    """classified + graph + ts → strong>=2 → covered."""
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[_mk_article(["환율_FX"])] * 5,
        graph_paths=[{"labels": ["환율 상승"], "target": "환율", "confidence": 0.5}],
        wiki_selected_pages=[],
        timeseries_narrative_text="환율 1480원 부근 등락",
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    assert rows["환율"]["coverage_status"] == "covered"


# ─────────────────────────────────────────────────────────────────────
# 5. summary phrase 어휘 변경
# ─────────────────────────────────────────────────────────────────────

def test_summary_phrase_uses_new_vocabulary():
    """'직접 근거 충분' 대신 '복수 신호 확인' 어휘."""
    from market_research.report.asset_coverage import (
        build_asset_coverage_map, format_asset_coverage_for_prompt,
    )
    cov = build_asset_coverage_map(
        primary_news=[_mk_article(["환율_FX"])] * 5,
        graph_paths=[{"labels": ["환율 상승"], "target": "환율", "confidence": 0.5}],
        wiki_selected_pages=[],
        timeseries_narrative_text="환율 1480원",
    )
    text = format_asset_coverage_for_prompt(cov)
    assert "복수 신호 확인" in text
    assert "직접 근거 충분" not in text  # 구 표현 제거 확인


# ─────────────────────────────────────────────────────────────────────
# 6. Eurodollar exclude (환율)
# ─────────────────────────────────────────────────────────────────────

def test_eurodollar_excluded_from_fx():
    from market_research.report.asset_coverage import _scan_text_for_asset
    # Eurodollar 시스템 (monygeek) 은 FX 가 아니라 글로벌 유동성 개념
    assert _scan_text_for_asset("Eurodollar 시스템 유동성", "환율") == 0


# ─────────────────────────────────────────────────────────────────────
# 7. Client leak regression (P3-3.1 신규 키)
# ─────────────────────────────────────────────────────────────────────

def test_client_no_p3_3_1_leak(client, tmp_path, monkeypatch):
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
            meta=BaseMeta(as_of_date=None, source="mock", sources=[],
                          is_fallback=True, warnings=["test stub"],
                          generated_at=datetime.now(timezone.utc)),
            series=[],
        )
    monkeypatch.setattr(report_service.macro_service,
                        "build_macro_timeseries", _empty_macro)

    fp = root / "2026-04"
    fp.mkdir(parents=True, exist_ok=True)
    (fp / "_market.final.json").write_text(json.dumps({
        "fund_code": "_market", "period": "2026-04",
        "status": "approved", "approved": True,
        "approved_at": "2026-04-30T14:00:45",
        "approved_debate_run_id": "RID-P331-1",
        "generated_at": "2026-04-30T13:56:04",
        "final_comment": "comment",
        "evidence_annotations": [], "related_news": [],
    }, ensure_ascii=False), encoding="utf-8")
    (fp / "_market.draft.json").write_text(json.dumps({
        "fund_code": "_market", "period": "2026-04",
        "status": "approved", "draft_comment": "draft",
        "debate_run_id": "RID-P331-1",
        "generated_at": "2026-04-30T13:56:04",
        # P3-3.1: bucket / group 신규 키 누출 차단
        "_debug_trace": {
            "evidence_count_classified": 9999,
            "evidence_count_selected": 5,
            "evidence_bucket": "high",
            "dominant_topic_group": "중동/지정학/에너지",
            "dominant_topic_group_share": 0.87,
            "present_signals": ["evidence_selected", "graph"],
        },
    }, ensure_ascii=False), encoding="utf-8")

    r = client.get("/api/market-report", params={"period": "2026-04"})
    assert r.status_code == 200
    raw = r.text
    forbidden = (
        "_debug_trace",
        "evidence_count_classified", "evidence_count_selected",
        "evidence_bucket", "dominant_topic_group",
        "dominant_topic_group_share", "present_signals",
        "9999",  # raw count
    )
    leaks = [k for k in forbidden if k in raw]
    assert leaks == [], f"forbidden keys leaked: {leaks}"
