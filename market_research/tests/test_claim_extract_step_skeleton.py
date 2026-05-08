# -*- coding: utf-8 -*-
"""R9-A.4 Commit 1 — Step 2.7 skeleton 회귀.

LLM 호출 0. file write 0. canonical store / wiki / ledger / report_output
미접근.
"""
from __future__ import annotations

from market_research.pipeline import claim_extract_step as ces


# ──────────────────────────────────────────────────────────────────
# Default OFF
# ──────────────────────────────────────────────────────────────────

def test_default_flag_off():
    """ENABLE_CLAIM_EXTRACTION 모듈 default 가 False 임을 보장 (운영 안전망)."""
    assert ces.ENABLE_CLAIM_EXTRACTION is False


def test_step_disabled_when_default_off():
    """flag default OFF 시 step_claim_extract 가 skip status 반환."""
    out = ces.step_claim_extract("2026-04")
    assert out["status"] == ces.STATUS_DISABLED
    assert out["enabled"] is False
    assert out["llm_calls"] == 0
    assert out["writes"] == 0
    assert out["period"] == "2026-04"
    assert out["target_suffix"] is None
    assert "R9-A.4 Commit 1 skeleton" in out["notes"]


def test_step_disabled_when_flag_explicit_false():
    """enabled=False 명시 override 도 동일 동작."""
    out = ces.step_claim_extract("2026-04", enabled=False)
    assert out["status"] == ces.STATUS_DISABLED
    assert out["enabled"] is False
    assert out["llm_calls"] == 0


# ──────────────────────────────────────────────────────────────────
# Flag ON 시에도 Commit 1 단계는 skeleton (no-op)
# ──────────────────────────────────────────────────────────────────

def test_step_skeleton_when_enabled_true():
    """flag override=True 라도 Commit 1 단계에선 skeleton no-op."""
    out = ces.step_claim_extract("2026-04", enabled=True)
    assert out["status"] == ces.STATUS_SKELETON
    assert out["enabled"] is True
    assert out["llm_calls"] == 0
    assert out["writes"] == 0


def test_module_flag_override_via_monkeypatch(monkeypatch):
    """ENABLE_CLAIM_EXTRACTION 모듈 상수 monkeypatch 시에도 동일 동작."""
    monkeypatch.setattr(ces, "ENABLE_CLAIM_EXTRACTION", True)
    out = ces.step_claim_extract("2026-04")
    assert out["status"] == ces.STATUS_SKELETON
    assert out["enabled"] is True
    assert out["llm_calls"] == 0


# ──────────────────────────────────────────────────────────────────
# target_suffix passthrough (D-2)
# ──────────────────────────────────────────────────────────────────

def test_target_suffix_echoed_in_status():
    out = ces.step_claim_extract(
        "2026-04", enabled=True, target_suffix="r9a4-replay")
    assert out["target_suffix"] == "r9a4-replay"
    # Commit 1 단계 — file write 0, suffix 는 echo 만
    assert out["writes"] == 0


# ──────────────────────────────────────────────────────────────────
# Graceful — 어떤 입력에서도 raise 0 (D-6)
# ──────────────────────────────────────────────────────────────────

def test_graceful_with_unusual_period_string():
    """period 문자열이 비정상이라도 raise 없이 status dict 반환."""
    out = ces.step_claim_extract("not-a-period", enabled=True)
    assert out["status"] == ces.STATUS_SKELETON
    assert out["period"] == "not-a-period"
    assert out["llm_calls"] == 0


def test_graceful_with_empty_period():
    out = ces.step_claim_extract("", enabled=False)
    assert out["status"] == ces.STATUS_DISABLED
    assert out["period"] == ""


# ──────────────────────────────────────────────────────────────────
# daily_update 진입점 회귀 (Step 2.7 호출 위치 확인)
# ──────────────────────────────────────────────────────────────────

def test_daily_update_imports_claim_extract_step_at_step_2_7():
    """daily_update.py 가 Step 2.7 자리에서 step_claim_extract 를 호출하는지
    구조적으로 확인. import 가능 + 함수 시그니처 안정."""
    from market_research.pipeline.daily_update import _step_refine  # noqa: F401
    # claim_extract_step import 가능
    from market_research.pipeline.claim_extract_step import (  # noqa: F401
        step_claim_extract, ENABLE_CLAIM_EXTRACTION,
        STATUS_DISABLED, STATUS_SKELETON,
    )
    assert callable(step_claim_extract)
    assert STATUS_DISABLED == "disabled"
    assert STATUS_SKELETON == "skeleton_no_op"


def test_step_2_7_is_called_between_2_6_and_3():
    """daily_update 소스 grep — Step 2.7 가 Step 2.6 직후, Step 3 직전에 호출됨."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "pipeline" / "daily_update.py").read_text(encoding="utf-8")
    pos_2_6 = src.find("[Step 2.6]")
    pos_2_7 = src.find("[Step 2.7]")
    pos_3 = src.find("[Step 3]")
    assert 0 < pos_2_6 < pos_2_7 < pos_3
    # Step 2.7 코드가 step_claim_extract import + 호출을 포함하는지
    block = src[pos_2_7:pos_3]
    assert "step_claim_extract" in block
    assert "claim_extract_step" in block
    # graceful 정책 — Exception catch 명시
    assert "graceful skip" in block or "except Exception" in block
