"""Regression: R2 G7 fix — fund_comment retrieve 에서 04_Funds 디렉토리 자체 차단.

정책 (2026-05-06):
  - 04_Funds 페이지는 pinned_fund_context 전용 (period exact + fund_code exact).
  - retrieved_wiki_context 에는 04_Funds/* 0건 (다른 month / 같은 month 모두).
  - market_debate stage 에서도 04_Funds 차단 (기존 정책 유지).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.report.wiki_retriever import (
    retrieve_wiki_context,
    get_pinned_fund_context,
    STAGE_ALLOWED_DIRS,
)


def _check_no_04_funds(selected_pages: list[str]) -> list[str]:
    return [p for p in selected_pages if p.startswith("04_Funds/")]


def test_stage_allowed_dirs_excludes_04_funds():
    """fund_comment / market_debate / quarterly_debate 모두 04_Funds 비포함."""
    for stage in ("market_debate", "fund_comment", "quarterly_debate"):
        assert "04_Funds" not in STAGE_ALLOWED_DIRS[stage], (
            f"{stage} 의 STAGE_ALLOWED_DIRS 에 04_Funds 가 있으면 안 됨"
        )
    # admin_preview 는 superset 이므로 04_Funds 포함 OK
    assert "04_Funds" in STAGE_ALLOWED_DIRS["admin_preview"]


def test_fund_comment_2026_05_07G04_no_04_funds_in_retrieved():
    """period=2026-05 fund=07G04 retrieve 결과에 04_Funds 페이지 0건."""
    keywords = ["환율", "지정학", "유가", "금리", "07G04", "국내채권"]
    r = retrieve_wiki_context(
        keywords, stage="fund_comment", fund_code="07G04",
        period="2026-05",
    )
    leaked = _check_no_04_funds(r["selected_pages"])
    assert not leaked, (
        f"04_Funds leak 발견 (정책 위반): {leaked}\n"
        f"  excluded_dirs={r.get('excluded_dirs')}\n"
        f"  excluded_dir_page_count={r.get('excluded_dir_page_count')}"
    )
    # 차단된 dir 목록 검증
    assert "04_Funds" in r.get("excluded_dirs", []), (
        "excluded_dirs trace 에 04_Funds 가 표시되어야 함"
    )
    # excluded_dir_page_count > 0 (실제 04_Funds 페이지 존재)
    assert r.get("excluded_dir_page_count", 0) >= 1


def test_fund_comment_2026_05_08K88_no_04_funds_in_retrieved():
    keywords = ["환율", "지정학", "유가", "금리", "08K88", "국내채권"]
    r = retrieve_wiki_context(
        keywords, stage="fund_comment", fund_code="08K88",
        period="2026-05",
    )
    leaked = _check_no_04_funds(r["selected_pages"])
    assert not leaked, f"04_Funds leak 발견: {leaked}"


def test_pinned_still_works_period_exact():
    """pinned_fund_context 는 영향 없음 (period exact + fund_code exact)."""
    pinned = get_pinned_fund_context(fund_code="07G04", period="2026-05")
    assert pinned["reason"] == "matched", (
        f"5월 07G04 pinned 정상 작동 — reason={pinned['reason']}"
    )
    assert pinned["page_path"] == "04_Funds/2026-05_07G04.md"
    assert pinned["chars"] > 0


def test_pinned_period_mismatch_no_match():
    """pinned 는 period 가 맞지 않으면 page_not_found (변동 없음)."""
    pinned = get_pinned_fund_context(fund_code="07G04", period="2025-12")
    assert pinned["page_path"] is None
    assert "page_not_found" in pinned["reason"]


def test_market_debate_no_04_funds():
    """market_debate stage 에서 04_Funds 차단 유지 (기존 정책)."""
    keywords = ["환율", "지정학", "유가", "금리"]
    r = retrieve_wiki_context(
        keywords, stage="market_debate", period="2026-05",
    )
    leaked = _check_no_04_funds(r["selected_pages"])
    assert not leaked, f"market_debate 에 04_Funds leak: {leaked}"


if __name__ == "__main__":
    for fn in [
        test_stage_allowed_dirs_excludes_04_funds,
        test_fund_comment_2026_05_07G04_no_04_funds_in_retrieved,
        test_fund_comment_2026_05_08K88_no_04_funds_in_retrieved,
        test_pinned_still_works_period_exact,
        test_pinned_period_mismatch_no_match,
        test_market_debate_no_04_funds,
    ]:
        fn()
        print(f"PASS {fn.__name__}")
    print("ALL PASS")
