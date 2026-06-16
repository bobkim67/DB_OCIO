# -*- coding: utf-8 -*-
"""09_Research_Synthesis monthly pipeline + debate default flip 테스트 (Phase 2.5).

요구사항: daily_update 09 step 배선 / readiness pass·fail / default=research_only /
09 missing 시 legacy 자동 폴백 안 함 / explicit legacy 동작.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.pipeline.daily_update import (  # noqa: E402
    daily_update, _step_research_synthesis, check_09_readiness,
    REQUIRED_09_ASSET_STEMS,
)
from market_research.report import debate_engine as de  # noqa: E402
from market_research.report import debate_service as ds  # noqa: E402
from market_research.report.debate_context_policy import (  # noqa: E402
    resolve_policy, RESEARCH_ONLY_POLICY, LEGACY_POLICY,
)
from market_research.wiki.paths import RESEARCH_SYNTHESIS_DIR  # noqa: E402

_HAS_05 = (RESEARCH_SYNTHESIS_DIR.exists()
           and bool(list(RESEARCH_SYNTHESIS_DIR.glob("2026-05_*.md"))))


# ── 1. daily_update 가 09 step + readiness 를 호출(배선) ──
def test_daily_update_wires_research_synthesis_step():
    names = daily_update.__code__.co_names
    assert "_step_research_synthesis" in names
    assert "check_09_readiness" in names


def test_step_research_synthesis_dry_run_skips():
    r = _step_research_synthesis("2026-05", dry_run=True)
    assert r["status"] == "skip" and r["reason"] == "dry_run"


# ── 2. readiness pass / fail ──
def test_check_09_readiness_failed_when_missing():
    r = check_09_readiness("1999-01")
    assert r["status"] == "failed"
    assert r["ready"] is False
    assert r["checks"]["files_exist"] is False


@pytest.mark.skipif(not _HAS_05, reason="2026-05 09 페이지 없음")
def test_check_09_readiness_ready_2026_05():
    r = check_09_readiness("2026-05")
    assert r["status"] == "ready"
    assert r["ready"] is True
    for k in ("files_exist", "asset_coverage", "claims_linkable",
              "research_only_source"):
        assert r["checks"][k] is True, f"{k} 실패: {r}"
    assert r["missing_assets"] == []
    assert r["bad_source_files"] == []


@pytest.mark.skipif(not _HAS_05, reason="2026-05 09 페이지 없음")
def test_readiness_degraded_on_missing_required_asset():
    # 필수 stem 에 존재하지 않는 가짜 자산을 추가 → coverage 실패 → degraded
    r = check_09_readiness("2026-05",
                           required_stems=REQUIRED_09_ASSET_STEMS + ("없는자산",))
    assert r["status"] == "degraded"        # 파일은 있으나 coverage 미흡
    assert "없는자산" in r["missing_assets"]


# ── 3. default debate = research_only ──
def test_default_debate_is_research_only():
    assert inspect.signature(de.run_market_debate).parameters["context_mode"].default == "research_only"
    assert inspect.signature(de.run_quarterly_debate).parameters["context_mode"].default == "research_only"
    assert inspect.signature(ds.run_debate_and_save).parameters["context_mode"].default == "research_only"


# ── 4. 09 missing 시 legacy 자동 폴백 안 함 ──
def test_no_auto_fallback_mode_exists():
    # 'auto' 같은 폴백 모드를 도입하지 않았음 — research_only 는 그대로 research_only
    assert resolve_policy("research_only") is RESEARCH_ONLY_POLICY
    with pytest.raises(ValueError):
        resolve_policy("auto")


def test_research_only_stays_research_only_when_09_missing():
    # 09 없는 기간이어도 policy 는 research_only 유지(legacy 로 안 바뀜) + 09 빈 문자열
    pol = resolve_policy("research_only")
    assert pol.name == "research_only"
    assert pol.news_summary_enabled is False     # news 여전히 차단
    tr: dict = {}
    out = de.build_research_synthesis_context(1999, 1, policy=pol, trace=tr)
    assert out == ""                              # 폴백으로 다른 소스 채우지 않음
    assert tr["status"] == "missing"


# ── 5. explicit legacy 는 여전히 동작 ──
def test_explicit_legacy_mode_works():
    pol = resolve_policy("legacy")
    assert pol is LEGACY_POLICY
    assert pol.news_summary_enabled is True
    assert pol.graph_paths_enabled is True
    assert pol.research_synthesis_enabled is False
