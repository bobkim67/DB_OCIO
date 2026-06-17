# -*- coding: utf-8 -*-
"""build_research_synthesis_context (Phase 2) 테스트.

순수 헬퍼(_parse_synth_page/_extract_synth_sections) + 실파일(2026-05) 통합.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.report.debate_engine import (  # noqa: E402
    _parse_synth_page, _extract_synth_sections, _extract_synth_claims,
    build_research_synthesis_context,
)
from market_research.report.debate_context_policy import (  # noqa: E402
    RESEARCH_ONLY_POLICY, LEGACY_POLICY,
)
import dataclasses  # noqa: E402
from market_research.wiki.paths import RESEARCH_SYNTHESIS_DIR  # noqa: E402

_SAMPLE = """---
period: 2026-05
asset_class: 국내주식
consensus_stance: bullish
consensus_strength: 0.636
n_claims: 545 (broker 519 / monygeek 26)
---

# 2026-05 국내주식 — 리서치 종합

## 1. 컨센서스 (stance: bullish, strength 0.636)
반도체 슈퍼사이클이 인플레 충격을 상쇄.
- vote(증권사): {'bullish': 330}

## 2. 이견 (dissent / tail-risk)
monygeek은 구조적 공급부족을 상승 근거로 본다.
- [claim:abc] (bullish, medium, monygeek) AI 슈퍼사이클

## 3. 리스크
- 반도체 사이클 역전 위험

## 4. 근거 claim (broker)
- [claim:xyz] (bullish, medium, iM증권) 반도체 호조

## 5. monygeek 관점
- [claim:abc] (bullish, medium, monygeek) AI 슈퍼사이클
"""


def test_parse_synth_page_frontmatter_and_body():
    fm, body = _parse_synth_page(_SAMPLE)
    assert fm["asset_class"] == "국내주식"
    assert fm["consensus_stance"] == "bullish"
    assert fm["consensus_strength"] == "0.636"
    assert body.startswith("# 2026-05 국내주식")


def test_extract_sections_keeps_1to3_drops_4to5():
    _, body = _parse_synth_page(_SAMPLE)
    sec = _extract_synth_sections(body, char_cap=5000)
    # §1~§3 유지
    assert "컨센서스" in sec and "이견" in sec and "리스크" in sec
    assert "반도체 슈퍼사이클이 인플레" in sec
    # §4/§5 (claim 리스트) 제외 → 08_Claims 중복 방지
    assert "## 4. 근거 claim" not in sec
    assert "## 5. monygeek 관점" not in sec
    assert "[claim:xyz]" not in sec      # broker claim list 미포함


def test_extract_claims_keeps_4and5_bullets():
    # Phase 2.7 — §4/§5 원자 claim bullet 만 발췌 (08 대체)
    _, body = _parse_synth_page(_SAMPLE)
    claims = _extract_synth_claims(body, char_cap=5000)
    assert "## 4. 근거 claim" in claims and "## 5. monygeek" in claims
    assert "[claim:xyz]" in claims          # broker claim
    assert "[claim:abc]" in claims          # monygeek claim
    # synthesis prose(§1 컨센서스 본문)는 claims 발췌에 미포함
    assert "반도체 슈퍼사이클이 인플레" not in claims


def test_include_claims_flag_toggles_4and5():
    # RESEARCH_ONLY = include_claims True → §4 헤더 포함
    assert RESEARCH_ONLY_POLICY.research_synthesis_include_claims is True
    # include_claims=False preset → claim 미포함 (synthesis 만)
    pol_off = dataclasses.replace(RESEARCH_ONLY_POLICY, name="ro_no_claims",
                                  research_synthesis_include_claims=False)
    assert pol_off.research_synthesis_include_claims is False


def test_extract_sections_fallback_on_unknown_headers():
    body = "본문에 ## 1. 같은 헤더가 전혀 없는 자유 텍스트입니다." * 3
    sec = _extract_synth_sections(body, char_cap=40)
    assert sec and len(sec) <= 40       # fallback = 앞부분 발췌


def test_extract_sections_char_cap():
    _, body = _parse_synth_page(_SAMPLE)
    sec = _extract_synth_sections(body, char_cap=30)
    assert len(sec) <= 30


def test_build_missing_dir_graceful(tmp_path, monkeypatch):
    import market_research.report.debate_engine as de
    monkeypatch.setattr("market_research.wiki.paths.RESEARCH_SYNTHESIS_DIR",
                        tmp_path / "nonexistent", raising=False)
    tr: dict = {}
    # 존재하지 않는 period → '' + trace status=missing (fail 안 함)
    out = build_research_synthesis_context(1999, 1, policy=RESEARCH_ONLY_POLICY, trace=tr)
    assert out == ""
    assert tr.get("status") == "missing"


@pytest.mark.skipif(not (RESEARCH_SYNTHESIS_DIR.exists()
                         and list(RESEARCH_SYNTHESIS_DIR.glob("2026-05_*.md"))),
                    reason="09 2026-05 페이지 없음")
def test_build_real_2026_05_integration():
    tr: dict = {}
    out = build_research_synthesis_context(2026, 5, policy=RESEARCH_ONLY_POLICY, trace=tr)
    assert tr["status"] == "ok"
    assert tr["selected_files"]                 # 자산군 파일 선택됨
    assert "09 Research Synthesis" in out
    assert "컨센서스" in out
    # Phase 2.7 — 08_Claims 제외 → 09 §4/§5 원자 claim 이 포함되어야 함
    assert "[claim:" in out                     # 원자 claim bullet 포함
    assert "## 4. 근거 claim" in out            # §4 broker claim 헤더
    # asset_scope 필터
    tr2: dict = {}
    out2 = build_research_synthesis_context(2026, 5, policy=RESEARCH_ONLY_POLICY,
                                            asset_scope=["국내주식"], trace=tr2)
    assert tr2["selected_assets"] == ["국내주식"]
