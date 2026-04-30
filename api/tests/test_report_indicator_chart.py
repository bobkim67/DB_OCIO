"""P1-③ indicator_chart normalized series 테스트.

정책 검증:
  - indicator_chart 는 read-time macro context 합성 (lineage guard 와 독립)
  - approved final 존재 시에만 client 노출
  - source = "macro_timeseries" 또는 "unavailable" (다른 enrichment 의 "approved"
    와 분리됨)
  - normalize: 첫 유효값 = 100
  - raw_value 보존
  - period 변환: YYYY-MM / YYYY-Q[1-4]
  - lineage newer_than_final 이어도 indicator_chart 는 노출
  - client endpoint 누출 회귀 없음
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    from market_research.report import report_store

    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)
    return root


def _stub_macro(monkeypatch, series_payload):
    """macro_service.build_macro_timeseries 를 결정적 mock 으로 치환.

    series_payload: list of dict {key, label, unit, points: [(date, value), ...]}
    """
    from api.services import report_service
    from api.schemas.macro import (
        MacroPointDTO, MacroSeriesDTO, MacroTimeseriesResponseDTO,
    )
    from api.schemas.meta import BaseMeta

    def _build(keys=None, start_date=None):
        out = []
        for s in series_payload:
            points = [
                MacroPointDTO(date=d, value=v) for d, v in s["points"]
            ]
            out.append(MacroSeriesDTO(
                key=s["key"], label=s["label"], unit=s.get("unit", "raw"),
                points=points,
            ))
        return MacroTimeseriesResponseDTO(
            meta=BaseMeta(
                as_of_date=None, source="db",
                sources=[], is_fallback=False, warnings=[],
                generated_at=datetime.now(timezone.utc),
            ),
            series=out,
        )

    monkeypatch.setattr(
        report_service.macro_service, "build_macro_timeseries", _build,
    )


def _stub_macro_empty(monkeypatch):
    _stub_macro(monkeypatch, [])


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _approved(period: str, fund: str, **extra) -> dict:
    base = {
        "fund_code": fund, "period": period,
        "status": "approved", "approved": True,
        "approved_at": "2026-04-30T12:00:00",
        "approved_by": "admin",
        "final_comment": f"final {fund} {period}",
        "generated_at": "2026-04-30T11:55:00",
        "model": "claude-opus-4-7",
    }
    base.update(extra)
    return base


# ────────────────────────────────────────────────────────────────────
# Period 변환 (단위 테스트, app 호출 없음)
# ────────────────────────────────────────────────────────────────────

def test_period_to_range_monthly():
    from api.services.report_service import _period_to_range
    assert _period_to_range("2026-04") == (date(2026, 4, 1), date(2026, 4, 30))
    assert _period_to_range("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))  # 윤년
    assert _period_to_range("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))


def test_period_to_range_quarterly():
    from api.services.report_service import _period_to_range
    assert _period_to_range("2026-Q1") == (date(2026, 1, 1), date(2026, 3, 31))
    assert _period_to_range("2026-Q2") == (date(2026, 4, 1), date(2026, 6, 30))
    assert _period_to_range("2026-Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert _period_to_range("2026-Q4") == (date(2026, 10, 1), date(2026, 12, 31))


def test_period_to_range_invalid_returns_none():
    from api.services.report_service import _period_to_range
    assert _period_to_range("invalid") is None
    assert _period_to_range("2026-13") is None
    assert _period_to_range("2026-Q5") is None


# ────────────────────────────────────────────────────────────────────
# Indicator chart 합성
# ────────────────────────────────────────────────────────────────────

def test_indicator_chart_built_for_approved_final(
    client, tmp_report_root, monkeypatch,
):
    """approved final + macro 시계열 mock → series 노출 + period_start/end + normalized."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund),
    )
    _stub_macro(monkeypatch, [
        {
            "key": "USDKRW", "label": "USD/KRW", "unit": "krw",
            "points": [
                (date(2026, 4, 1), 1450.0),
                (date(2026, 4, 15), 1475.0),
                (date(2026, 4, 30), 1480.0),
            ],
        },
        {
            "key": "PE_SP500", "label": "PE 12M Fwd (SPY)", "unit": "ratio",
            "points": [
                (date(2026, 4, 1), 20.0),
                (date(2026, 4, 30), 22.0),
            ],
        },
    ])
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]

    # source 는 별도 enum (approved 와 다름)
    assert enr["indicator_chart_source"] == "macro_timeseries"
    chart = enr["indicator_chart"]
    assert chart is not None
    assert chart["unavailable_reason"] is None
    assert chart["period_start"] == "2026-04-01"
    assert chart["period_end"] == "2026-04-30"
    assert len(chart["series"]) == 2

    # USDKRW
    usd = next(s for s in chart["series"] if s["key"] == "USDKRW")
    assert usd["label"] == "USD/KRW"
    assert usd["unit"] == "krw"
    assert usd["base_date"] == "2026-04-01"
    assert usd["base_value"] == 1450.0
    pts = usd["points"]
    assert len(pts) == 3
    # 첫 유효값 = 100
    assert pts[0]["date"] == "2026-04-01"
    assert pts[0]["value"] == pytest.approx(100.0)
    assert pts[0]["raw_value"] == 1450.0
    # 두번째: 1475/1450*100
    assert pts[1]["value"] == pytest.approx(1475.0 / 1450.0 * 100.0)
    assert pts[1]["raw_value"] == 1475.0
    # 세번째: 1480/1450*100
    assert pts[2]["value"] == pytest.approx(1480.0 / 1450.0 * 100.0)


def test_indicator_chart_skips_series_with_zero_first_value(
    client, tmp_report_root, monkeypatch,
):
    """첫 값이 0 인 series 는 다음 유효값을 base 로 잡거나, 모두 0 이면 skip."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund),
    )
    _stub_macro(monkeypatch, [
        {
            "key": "USDKRW", "label": "USD/KRW", "unit": "krw",
            "points": [
                (date(2026, 4, 1), 0.0),       # skip
                (date(2026, 4, 10), 1450.0),   # base = 100
                (date(2026, 4, 20), 1480.0),
            ],
        },
    ])
    r = client.get("/api/market-report", params={"period": period})
    chart = r.json()["data"]["enrichment"]["indicator_chart"]
    assert chart["unavailable_reason"] is None
    s = chart["series"][0]
    assert s["base_date"] == "2026-04-10"
    assert s["base_value"] == 1450.0
    # 첫 0 은 drop, 두번째가 100, 세번째가 1480/1450*100
    assert len(s["points"]) == 2
    assert s["points"][0]["value"] == pytest.approx(100.0)


def test_indicator_chart_filtered_to_period_range(
    client, tmp_report_root, monkeypatch,
):
    """macro_service 가 period 밖 데이터를 반환해도 service 단에서 잘라냄."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund),
    )
    _stub_macro(monkeypatch, [
        {
            "key": "USDKRW", "label": "USD/KRW", "unit": "krw",
            "points": [
                (date(2026, 3, 31), 9999.0),  # 범위 밖 (이전)
                (date(2026, 4, 1), 1450.0),
                (date(2026, 4, 30), 1480.0),
                (date(2026, 5, 1), 9999.0),  # 범위 밖 (이후)
            ],
        },
    ])
    r = client.get("/api/market-report", params={"period": period})
    chart = r.json()["data"]["enrichment"]["indicator_chart"]
    s = chart["series"][0]
    assert len(s["points"]) == 2
    assert s["points"][0]["raw_value"] == 1450.0
    assert s["points"][1]["raw_value"] == 1480.0


def test_indicator_chart_quarterly_period(
    client, tmp_report_root, monkeypatch,
):
    period, fund = "2026-Q1", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund),
    )
    _stub_macro(monkeypatch, [
        {
            "key": "USDKRW", "label": "USD/KRW", "unit": "krw",
            "points": [
                (date(2026, 1, 15), 1400.0),
                (date(2026, 3, 31), 1450.0),
            ],
        },
    ])
    r = client.get("/api/market-report", params={"period": period})
    chart = r.json()["data"]["enrichment"]["indicator_chart"]
    assert chart["period_start"] == "2026-01-01"
    assert chart["period_end"] == "2026-03-31"
    assert len(chart["series"]) == 1


def test_indicator_chart_empty_macro_returns_unavailable(
    client, tmp_report_root, monkeypatch,
):
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund),
    )
    _stub_macro_empty(monkeypatch)
    r = client.get("/api/market-report", params={"period": period})
    enr = r.json()["data"]["enrichment"]
    assert enr["indicator_chart_source"] == "unavailable"
    chart = enr["indicator_chart"]
    assert chart["series"] == []
    assert chart["unavailable_reason"] == "no_macro_data_in_period"
    # period_start/end 는 채워져 있음 (period 자체는 유효)
    assert chart["period_start"] == "2026-04-01"
    assert chart["period_end"] == "2026-04-30"


def test_indicator_chart_macro_service_failure(
    client, tmp_report_root, monkeypatch,
):
    """macro_service 가 예외를 던져도 200 반환 + unavailable_reason 명시."""
    from api.services import report_service

    def _boom(keys=None, start_date=None):
        raise RuntimeError("DB down")
    monkeypatch.setattr(
        report_service.macro_service, "build_macro_timeseries", _boom,
    )

    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["indicator_chart_source"] == "unavailable"
    assert enr["indicator_chart"]["unavailable_reason"] == "macro_service_failed"


# ────────────────────────────────────────────────────────────────────
# Lineage 와의 독립성
# ────────────────────────────────────────────────────────────────────

def test_indicator_chart_exposed_when_lineage_newer_than_final(
    client, tmp_report_root, monkeypatch,
):
    """draft.generated_at > approved_at (newer_than_final) 라도 indicator_chart 는 노출.

    다른 enrichment (evidence/related/quality/validation) 는 차단되어야 함.
    """
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund),  # approved_at=2026-04-30T12:00
    )
    # draft.generated_at 가 approved_at 이후 → lineage 차단
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        {
            "fund_code": fund, "period": period,
            "status": "draft_generated",
            "generated_at": "2026-05-10T10:00:00",
            "evidence_annotations": [
                {"ref": 1, "title": "x", "source": "Reuters"},
            ],
            "related_news": [
                {"ref": 99, "title": "rel", "source": "뉴시스"},
            ],
            "validation_summary": {
                "sanitize_warnings": [{"type": "x", "message": "y", "severity": "warning"}],
                "warning_counts": {"warning": 1, "critical": 0, "info": 0},
            },
            "evidence_quality": {
                "total_refs": 1, "ref_mismatches": 0, "evidence_count": 1,
                "mismatch_rate": 0.0,
            },
        },
    )
    _stub_macro(monkeypatch, [
        {"key": "USDKRW", "label": "USD/KRW", "unit": "krw",
         "points": [(date(2026, 4, 1), 1450.0)]},
    ])
    r = client.get("/api/market-report", params={"period": period})
    enr = r.json()["data"]["enrichment"]

    # 다른 enrichment 는 lineage 가드로 차단
    assert enr["evidence_annotations_source"] == "unavailable"
    assert enr["related_news_source"] == "unavailable"
    assert enr["evidence_quality_source"] == "unavailable"
    assert enr["validation_summary_source"] == "unavailable"
    assert enr["source_consistency_status"] == "newer_than_final"

    # indicator_chart 는 lineage 와 독립 → 노출됨
    assert enr["indicator_chart_source"] == "macro_timeseries"
    assert enr["indicator_chart"]["series"]


def test_indicator_chart_blocked_when_final_unapproved(
    client, tmp_report_root, monkeypatch,
):
    """client 라우터는 approved=false 면 404 — indicator_chart 도 노출 안 됨."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund, approved=False),
    )
    _stub_macro(monkeypatch, [
        {"key": "USDKRW", "label": "USD/KRW", "unit": "krw",
         "points": [(date(2026, 4, 1), 1450.0)]},
    ])
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 404


# ────────────────────────────────────────────────────────────────────
# Client / Admin 응답 누출 회귀
# ────────────────────────────────────────────────────────────────────

def test_client_no_internal_leak_when_indicator_present(
    client, tmp_report_root, monkeypatch,
):
    """indicator_chart 노출 시에도 client 응답에 internal_source / raw reason /
    debate_run_id 누출 없음."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund, approved_debate_run_id="a" * 32),
    )
    _stub_macro(monkeypatch, [
        {"key": "USDKRW", "label": "USD/KRW", "unit": "krw",
         "points": [(date(2026, 4, 1), 1450.0)]},
    ])
    r = client.get("/api/market-report", params={"period": period})
    body = r.json()
    payload_str = json.dumps(body, ensure_ascii=False)
    assert "internal_source" not in payload_str
    assert "approved_debate_run_id" not in payload_str
    assert "debate_run_id" not in payload_str
    assert "source_consistency_reason" not in payload_str
    # 그러나 indicator_chart 는 노출됨
    assert body["data"]["enrichment"]["indicator_chart_source"] == "macro_timeseries"


def test_admin_endpoint_exposes_indicator_chart(
    client, tmp_report_root, monkeypatch,
):
    """admin endpoint 도 indicator_chart 노출. internal_source 도 함께."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved(period, fund),
    )
    _stub_macro(monkeypatch, [
        {"key": "PE_SP500", "label": "PE 12M Fwd (SPY)", "unit": "ratio",
         "points": [(date(2026, 4, 1), 20.0), (date(2026, 4, 30), 22.0)]},
    ])
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund},
    )
    assert r.status_code == 200
    body = r.json()
    enr = body["enrichment"]
    assert enr is not None
    assert enr["indicator_chart_source"] == "macro_timeseries"
    assert enr["indicator_chart_internal_source"] == "macro_timeseries"
    s = enr["indicator_chart"]["series"][0]
    assert s["key"] == "PE_SP500"
    assert s["points"][0]["value"] == pytest.approx(100.0)
    assert s["points"][0]["raw_value"] == 20.0
    assert s["points"][1]["raw_value"] == 22.0
