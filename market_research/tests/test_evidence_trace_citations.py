"""R6-A 회귀: evidence_trace 의 split_sections / strip_refs / validate_citations.

LLM 호출 0. 디스크 / DB 의존 0. 순수 단위 테스트.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────
# split_sections
# ──────────────────────────────────────────────────────────────────

def test_split_sections_with_headers():
    from market_research.report.evidence_trace import split_sections
    txt = "■ A\n본문 1\n■ B\n본문 2"
    sections = split_sections(txt)
    assert len(sections) == 2
    assert [s["section_title"] for s in sections] == ["A", "B"]


def test_split_sections_empty():
    from market_research.report.evidence_trace import split_sections
    s = split_sections("")
    assert len(s) == 1
    assert s[0]["section_id"] == "00_main"


def test_split_sections_parity_with_comment_trace():
    """evidence_trace.split_sections == tools.comment_trace.split_sections.

    R6-A 신규 fund_comment_service 가 evidence_trace 로 section_id 를 생성하고
    comment_trace 가 같은 section_id 로 attribution 매핑하므로 parity 필수.
    """
    from market_research.report.evidence_trace import (
        split_sections as et_split,
    )
    from tools.comment_trace import split_sections as ct_split
    txt = "■ 시장 평가\n본문[ref:1]\n\n■ 펀드 성과\n본문2[ref:2]"
    et = et_split(txt)
    ct = ct_split(txt)
    assert len(et) == len(ct)
    for a, b in zip(et, ct):
        assert a["section_id"] == b["section_id"]
        assert a["section_title"] == b["section_title"]
        assert a["char_range"] == b["char_range"]


# ──────────────────────────────────────────────────────────────────
# strip_refs
# ──────────────────────────────────────────────────────────────────

def test_strip_refs_basic():
    from market_research.report.evidence_trace import strip_refs
    assert strip_refs("유가는 100달러를 돌파했습니다 [ref:2].") \
        == "유가는 100달러를 돌파했습니다."


def test_strip_refs_multi():
    from market_research.report.evidence_trace import strip_refs
    out = strip_refs("A [ref:1] B [ref:2] C [ref:3].")
    assert "[ref:" not in out
    assert out == "A B C."


def test_strip_refs_no_refs():
    from market_research.report.evidence_trace import strip_refs
    txt = "유가가 상승했습니다."
    assert strip_refs(txt) == txt


def test_strip_refs_empty():
    from market_research.report.evidence_trace import strip_refs
    assert strip_refs("") == ""
    assert strip_refs(None) == ""  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────
# validate_citations
# ──────────────────────────────────────────────────────────────────

def test_validate_citations_explicit_ref():
    from market_research.report.evidence_trace import validate_citations
    txt = "■ 시장\nWTI 는 100달러를 돌파했습니다 [ref:1]. 금은 하락했습니다 [ref:2].\n\n■ 펀드\n펀드 수익률 +5%."
    ann = [
        {"ref": 1, "article_id": "a1", "title": "유가"},
        {"ref": 2, "article_id": "a2", "title": "금"},
    ]
    out = validate_citations(txt, ann)
    cc = out["comment_citations"]
    cv = out["citation_validation"]
    # 시장 section: explicit_ref, refs=[1,2], evidence=[a1,a2]
    s_market = next(c for c in cc if "시장" in c["section_title"])
    assert s_market["citation_type"] == "explicit_ref"
    assert s_market["ref_ids"] == [1, 2]
    assert s_market["evidence_ids"] == ["a1", "a2"]
    # 펀드 section: section_default (no ref)
    s_fund = next(c for c in cc if "펀드" in c["section_title"])
    assert s_fund["citation_type"] == "section_default"
    assert s_fund["ref_ids"] == []
    assert cv["explicit_ref_count"] == 2
    assert cv["invalid_ref_count"] == 0
    assert cv["sections_with_ref_count"] == 1
    assert cv["sections_without_ref_count"] == 1
    assert cv["warnings"] == []


def test_validate_citations_invalid_ref():
    """ann 에 없는 ref:99 → invalid_ref_count + warning."""
    from market_research.report.evidence_trace import validate_citations
    txt = "■ 시장\n어쩌고 [ref:99]."
    ann = [{"ref": 1, "article_id": "a1", "title": "T1"}]
    out = validate_citations(txt, ann)
    cv = out["citation_validation"]
    assert cv["explicit_ref_count"] == 1
    assert cv["invalid_ref_count"] == 1
    assert cv["sections_with_ref_count"] == 1
    assert any("ref:99" in w for w in cv["warnings"])
    cc = out["comment_citations"][0]
    # invalid ref 라도 ref_ids 에는 등장 (관측용), evidence_ids 만 비어있음
    assert cc["ref_ids"] == [99]
    assert cc["evidence_ids"] == []


def test_validate_citations_duplicate_ref_in_section():
    """같은 ref 가 한 section 에서 여러번 → ref_ids unique, count 는 등장 수."""
    from market_research.report.evidence_trace import validate_citations
    txt = "■ 시장\n첫 [ref:1]. 두 [ref:1]. 세 [ref:1]."
    ann = [{"ref": 1, "article_id": "a1", "title": "T1"}]
    out = validate_citations(txt, ann)
    cc = out["comment_citations"][0]
    cv = out["citation_validation"]
    assert cc["ref_ids"] == [1]
    assert cc["evidence_ids"] == ["a1"]
    assert cv["explicit_ref_count"] == 3  # 등장 횟수
    assert cv["invalid_ref_count"] == 0


def test_validate_citations_no_refs_at_all():
    from market_research.report.evidence_trace import validate_citations
    txt = "■ 시장\n인용 없음.\n\n■ 펀드\n인용 없음."
    out = validate_citations(txt, [])
    cv = out["citation_validation"]
    assert cv["explicit_ref_count"] == 0
    assert cv["sections_with_ref_count"] == 0
    assert cv["sections_without_ref_count"] == 2
    for c in out["comment_citations"]:
        assert c["citation_type"] == "section_default"


def test_validate_citations_empty_text():
    from market_research.report.evidence_trace import validate_citations
    out = validate_citations("", [])
    assert out["citation_validation"]["explicit_ref_count"] == 0
    # split_sections 가 단일 main section 반환 → without_ref=1
    assert out["citation_validation"]["sections_without_ref_count"] == 1


def test_validate_citations_no_header_with_refs():
    """■ 헤더 없이도 단일 main section 으로 ref 추출."""
    from market_research.report.evidence_trace import validate_citations
    txt = "유가 상승 [ref:1]. 금 하락 [ref:2]."
    ann = [
        {"ref": 1, "article_id": "a1"},
        {"ref": 2, "article_id": "a2"},
    ]
    out = validate_citations(txt, ann)
    cc = out["comment_citations"]
    assert len(cc) == 1
    assert cc[0]["section_id"] == "00_main"
    assert cc[0]["ref_ids"] == [1, 2]
    assert cc[0]["evidence_ids"] == ["a1", "a2"]
