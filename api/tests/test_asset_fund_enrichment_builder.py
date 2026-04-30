"""P3-4 / P3-5 enrichment builder tests (read-only / dry-run only).

운영 wiki overwrite 0. LLM 호출 0. final/draft/jsonl 변경 0.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────
# Plan basics — 8 asset + 7 fund pages, 07G02/07G03 skip
# ─────────────────────────────────────────────────────────────────────

def test_plan_creates_8_asset_pages():
    from market_research.wiki.asset_fund_enrichment_builder import (
        REQUIRED_ASSET_CLASSES, ASSET_FILENAME_STEMS, build_enrichment_plan,
    )
    plan = build_enrichment_plan("2026-04")
    assert len(plan.asset_pages) == 8
    expected_stems = {ASSET_FILENAME_STEMS[ac] for ac in REQUIRED_ASSET_CLASSES}
    actual_stems = {Path(rel).stem.replace("2026-04_", "") for rel in plan.asset_pages}
    assert expected_stems == actual_stems


def test_required_assets_not_missing():
    """국내채권 / 해외채권 / 크레딧 / 현금성 은 누락되어선 안 됨."""
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    rels = list(plan.asset_pages.keys())
    for must in ("국내채권", "해외채권", "크레딧", "현금성"):
        assert any(must in rel for rel in rels), f"missing asset page: {must}"


def test_asset_page_chars_threshold():
    """P3-4.1: 핵심 6 자산 ≥1000ch, 보조 2 자산(크레딧/현금성) ≥700ch.

    1000ch 강제 아님. 700~1000ch 허용 + filler 회피.
    """
    from market_research.wiki.asset_fund_enrichment_builder import (
        build_enrichment_plan, BOUNDARY_ASSETS,
    )
    plan = build_enrichment_plan("2026-04")
    for rel, body in plan.asset_pages.items():
        is_boundary = any(b in rel for b in BOUNDARY_ASSETS)
        if is_boundary:
            assert len(body) >= 700, f"boundary asset below 700ch: {rel} ({len(body)})"
        else:
            assert len(body) >= 1000, f"core asset below 1000ch: {rel} ({len(body)})"


def test_credit_cash_event_disclaimer():
    """P3-4.1: 크레딧/현금성 page 에 직접 이벤트 제한 / 영향 제한 / 특이 이벤트 부재 류 문구 포함."""
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    DISCLAIMER_TOKENS = (
        "직접 이벤트 제한적", "이벤트 제한 가능성",
        "특이 이벤트 부재", "직접 관련 펀드 제한적",
        "영향 제한",
    )
    for stem in ("크레딧", "현금성"):
        rel = f"03_Assets/2026-04_{stem}.md"
        body = plan.asset_pages[rel]
        assert any(tok in body for tok in DISCLAIMER_TOKENS), \
            f"disclaimer 문구 누락: {rel}"


def test_credit_required_chips():
    """크레딧 page: HY / 회사채 / 신용스프레드 / credit spread 중 ≥2."""
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    body = plan.asset_pages["03_Assets/2026-04_크레딧.md"]
    chips = ("HY", "회사채", "신용스프레드", "credit spread")
    hits = [c for c in chips if c in body]
    assert len(hits) >= 2, f"크레딧 page 필수 chip <2: hits={hits}"


def test_cash_required_chips():
    """현금성 page: 단기금리 / CD / MMF / 유동성 / 리밸런싱 대기자금 / 대기성 자금 중 ≥2."""
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    body = plan.asset_pages["03_Assets/2026-04_현금성.md"]
    chips = ("단기금리", "CD", "MMF", "유동성", "리밸런싱", "대기성 자금")
    hits = [c for c in chips if c in body]
    assert len(hits) >= 2, f"현금성 page 필수 chip <2: hits={hits}"


def test_no_filler_repetition_in_any_page():
    """동일 문장/bullet 3회 이상 반복 0 — filler 회피."""
    from market_research.wiki.asset_fund_enrichment_builder import (
        build_enrichment_plan, detect_filler_repetition,
    )
    plan = build_enrichment_plan("2026-04")
    offenders: list[str] = []
    for rel, body in {**plan.asset_pages, **plan.fund_pages}.items():
        f = detect_filler_repetition(body)
        if f["repeated_sentences"] or f["repeated_bullets"]:
            offenders.append(rel)
    assert not offenders, f"filler 반복 발견: {offenders}"


def test_asset_page_has_event_entity_fund_links():
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
    for rel, body in plan.asset_pages.items():
        # 크레딧/현금성은 graph/event 매칭이 약해 link 적을 수 있음 — 그 외 자산은 검증
        if "크레딧" in rel or "현금성" in rel:
            continue
        toks = LINK_RE.findall(body)
        # event link OR entity link OR fund link 중 최소 1종 이상
        has_event = any(t.startswith("01_Events/") for t in toks)
        has_entity = any(t.startswith("02_Entities/") for t in toks)
        has_fund = any(t.startswith("04_Funds/") for t in toks)
        assert (has_event or has_entity), f"no event/entity link in {rel}"
        assert has_fund, f"no fund link in {rel}"


def test_plan_creates_7_fund_pages():
    from market_research.wiki.asset_fund_enrichment_builder import (
        FUND_TARGETS, build_enrichment_plan,
    )
    plan = build_enrichment_plan("2026-04")
    assert len(plan.fund_pages) == 7
    actual = {Path(rel).stem.replace("2026-04_", "") for rel in plan.fund_pages}
    assert actual == set(FUND_TARGETS)


def test_07g02_07g03_not_in_plan():
    """모펀드 페이지는 절대 생성되어선 안 됨."""
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    for rel in plan.fund_pages:
        assert "07G02" not in rel
        assert "07G03" not in rel
    assert "07G02" in plan.skipped_funds
    assert "07G03" in plan.skipped_funds


def test_07g04_lookthrough_section():
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    body = plan.fund_pages["04_Funds/2026-04_07G04.md"]
    assert "Look-through 구조" in body
    assert "07G02" in body
    assert "07G03" in body
    assert "별도 운용보고 생성 대상이 아니" in body
    # mother fund 04_Funds/2026-04_07G02 link 가 외부 파일로 broken 처리되지 않도록
    # 본문에는 wiki link 형태로 박지 않고 텍스트로만 등장해야 함
    LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
    toks = LINK_RE.findall(body)
    assert not any(t.endswith("/2026-04_07G02") for t in toks)
    assert not any(t.endswith("/2026-04_07G03") for t in toks)


def test_fund_page_chars_threshold():
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    for rel, body in plan.fund_pages.items():
        assert len(body) >= 1200, f"fund page below 1200ch: {rel} ({len(body)})"


def test_fund_page_has_asset_and_event_links():
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
    for rel, body in plan.fund_pages.items():
        toks = LINK_RE.findall(body)
        asset_links = [t for t in toks if t.startswith("03_Assets/")]
        event_or_entity = [t for t in toks if t.startswith("01_Events/") or t.startswith("02_Entities/")]
        assert len(asset_links) >= 2, f"<2 asset links in {rel}"
        assert len(event_or_entity) >= 2, f"<2 event/entity links in {rel}"


# ─────────────────────────────────────────────────────────────────────
# Internal link audit
# ─────────────────────────────────────────────────────────────────────

def test_internal_links_increase_significantly():
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    # 8 + 7 page 에서 최소 80 link
    assert plan.audit["total_links"] >= 80, plan.audit["total_links"]


def test_no_broken_links_within_plan():
    """plan 내부 page 끼리 또는 plan ↔ 디스크 wiki 페이지 사이 broken link 0."""
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    assert plan.audit["broken"] == [], plan.audit["broken"][:5]


def test_no_self_links():
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    plan = build_enrichment_plan("2026-04")
    assert plan.audit["self_links"] == [], plan.audit["self_links"]


# ─────────────────────────────────────────────────────────────────────
# wiki_retriever eligibility
# ─────────────────────────────────────────────────────────────────────

def test_retrieval_eligibility_threshold():
    """asset 대다수 + fund 모두 retrieval 기준 충족."""
    from market_research.wiki.asset_fund_enrichment_builder import (
        build_enrichment_plan, evaluate_retrieval_eligibility,
    )
    plan = build_enrichment_plan("2026-04")
    elig = evaluate_retrieval_eligibility(plan)
    # asset: 8 중 6 이상 (크레딧/현금성 보조점검은 제외 허용)
    assert elig["asset_eligible_count"] >= 6
    # fund: 7/7 모두 충족
    assert elig["fund_eligible_count"] == 7


def test_eligibility_threshold_is_lower_for_boundary_assets():
    """P3-4.1: boundary 자산(크레딧/현금성)은 700ch 기준으로, 핵심 자산은 1000ch 기준으로
    구분해서 eligibility 가 평가됨을 확인."""
    from market_research.wiki.asset_fund_enrichment_builder import (
        evaluate_retrieval_eligibility, build_enrichment_plan,
    )
    plan = build_enrichment_plan("2026-04")
    elig = evaluate_retrieval_eligibility(plan)
    assert elig["asset_min_chars_core"] == 1000
    assert elig["asset_min_chars_boundary"] == 700
    # 보강 후 모든 page 가 충족하는 것이 정상 ─ 실패 시 보강이 빠진 것
    assert elig["asset_eligible_count"] == 8
    assert elig["fund_eligible_count"] == 7


# ─────────────────────────────────────────────────────────────────────
# 운영 데이터 변경 0건 (dry-run only)
# ─────────────────────────────────────────────────────────────────────

def test_dryrun_does_not_touch_disk():
    """build_enrichment_plan 만 호출하면 wiki 디스크는 변하지 않아야 함."""
    from market_research.wiki.asset_fund_enrichment_builder import (
        build_enrichment_plan,
    )
    from market_research.wiki.paths import ASSETS_DIR, FUNDS_DIR

    before_assets = sorted(p.name for p in ASSETS_DIR.glob("*.md"))
    before_funds = sorted(p.name for p in FUNDS_DIR.glob("*.md"))

    _ = build_enrichment_plan("2026-04")  # plan only

    after_assets = sorted(p.name for p in ASSETS_DIR.glob("*.md"))
    after_funds = sorted(p.name for p in FUNDS_DIR.glob("*.md"))
    assert before_assets == after_assets
    assert before_funds == after_funds


def test_invalid_period_rejected():
    from market_research.wiki.asset_fund_enrichment_builder import build_enrichment_plan
    with pytest.raises(ValueError):
        build_enrichment_plan("2026-13")
    with pytest.raises(ValueError):
        build_enrichment_plan("invalid")


def test_build_fund_page_refuses_07G02():
    """07G02 / 07G03 은 build_fund_page 직접 호출도 거부."""
    from market_research.wiki.asset_fund_enrichment_builder import build_fund_page
    with pytest.raises(ValueError):
        build_fund_page("07G02", "2026-04")
    with pytest.raises(ValueError):
        build_fund_page("07G03", "2026-04")
