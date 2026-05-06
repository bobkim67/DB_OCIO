# -*- coding: utf-8 -*-
"""
Evidence Trace — 코멘트 문장 ↔ 기사 매핑
==========================================

Opus 코멘트에 포함된 [ref:N] 태그를 파싱하여
문장 단위로 어떤 뉴스 기사에 근거했는지 추적.

사용법:
    from market_research.report.evidence_trace import extract_refs, build_evidence_map
    refs = extract_refs(comment_text)
    evidence = build_evidence_map(refs, evidence_ids)
"""
from __future__ import annotations

import re


SECTION_HEADER_RE = re.compile(r"^■\s+(.+)$", re.MULTILINE)
SLUG_NONWORD_RE = re.compile(r"\W+")
REF_RE = re.compile(r"\[ref:(\d+)\]")


def split_sections(comment_text: str) -> list[dict]:
    """■ 헤더 기준 분할. tools/comment_trace.py 의 split_sections 와 동일 로직.

    comment_trace 가 attribution 시 같은 section_id 를 재계산해도 일치하도록
    동일 정규식 + 동일 slug 규칙. 단일 source-of-truth 로 여기에 둠.

    Returns:
        [{'section_id': '00_xxx', 'section_title': '...', 'char_range': [s, e], 'text': '...'}, ...]
    """
    matches = list(SECTION_HEADER_RE.finditer(comment_text or ""))
    if not matches:
        return [{
            "section_id": "00_main",
            "section_title": "본문",
            "char_range": [0, len(comment_text or "")],
            "text": comment_text or "",
        }]
    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(comment_text)
        title = m.group(1).strip()
        slug = SLUG_NONWORD_RE.sub("_", title)[:40].strip("_")
        if not slug:
            slug = f"section_{i}"
        sections.append({
            "section_id": f"{i:02d}_{slug}",
            "section_title": title,
            "char_range": [start, end],
            "text": comment_text[start:end],
        })
    return sections


def strip_refs(text: str) -> str:
    """LLM 원문에서 [ref:N] 태그 제거 (고객용). 앞 공백 한 칸까지 흡수."""
    if not text:
        return text or ""
    return re.sub(r"\s*\[ref:\d+\]", "", text)


def validate_citations(comment_text: str,
                        evidence_annotations: list[dict]) -> dict:
    """section 별 [ref:N] 파싱 + 유효성 검증.

    Parameters
    ----------
    comment_text : LLM 원문 ([ref:N] 포함)
    evidence_annotations : [{'ref': N, 'article_id': '...', 'title': ...}, ...]
        prompt 에 주입한 evidence list 와 동일한 ref 번호 부여

    Returns
    -------
    {
        'comment_citations': [
            {'section_id', 'section_title', 'ref_ids', 'evidence_ids', 'citation_type'},
            ...
        ],
        'citation_validation': {
            'explicit_ref_count':         # [ref:N] 등장 횟수 (중복 포함)
            'invalid_ref_count':          # evidence_annotations 에 없는 ref 등장 횟수
            'sections_with_ref_count':
            'sections_without_ref_count':
            'warnings': list[str]
        }
    }
    """
    sections = split_sections(comment_text or "")
    ann_by_ref = {a.get("ref"): a for a in (evidence_annotations or [])
                  if a.get("ref") is not None}

    comment_citations = []
    explicit_ref_count = 0
    invalid_ref_count = 0
    sections_with_ref_count = 0
    sections_without_ref_count = 0
    warnings: list[str] = []

    for sec in sections:
        text = sec["text"]
        all_refs = [int(m.group(1)) for m in REF_RE.finditer(text)]
        unique_refs = sorted(set(all_refs))
        explicit_ref_count += len(all_refs)

        if not unique_refs:
            sections_without_ref_count += 1
            comment_citations.append({
                "section_id": sec["section_id"],
                "section_title": sec["section_title"],
                "ref_ids": [],
                "evidence_ids": [],
                "citation_type": "section_default",
            })
            continue

        sections_with_ref_count += 1
        evidence_ids: list[str] = []
        for r in unique_refs:
            ann = ann_by_ref.get(r)
            if ann and ann.get("article_id"):
                evidence_ids.append(ann["article_id"])
            else:
                # invalid 등장 횟수는 중복 포함
                invalid_ref_count += all_refs.count(r)
                warnings.append(
                    f"section {sec['section_id']}: ref:{r} not in evidence_annotations"
                )

        comment_citations.append({
            "section_id": sec["section_id"],
            "section_title": sec["section_title"],
            "ref_ids": unique_refs,
            "evidence_ids": evidence_ids,
            "citation_type": "explicit_ref",
        })

    return {
        "comment_citations": comment_citations,
        "citation_validation": {
            "explicit_ref_count": explicit_ref_count,
            "invalid_ref_count": invalid_ref_count,
            "sections_with_ref_count": sections_with_ref_count,
            "sections_without_ref_count": sections_without_ref_count,
            "warnings": warnings,
        },
    }


def extract_refs(comment: str) -> list[dict]:
    """코멘트에서 [ref:N] 태그가 포함된 문장 추출.

    Returns:
        [{'sentence': '유가가 108달러를 돌파했다.', 'ref_idx': 2, 'pos': 142}, ...]
    """
    results = []
    # 문장 분리 (. 또는 다 기준)
    sentences = re.split(r'(?<=[.다])\s+', comment)

    pos = 0
    for sent in sentences:
        refs = re.findall(r'\[ref:(\d+)\]', sent)
        for ref in refs:
            clean_sent = re.sub(r'\[ref:\d+\]', '', sent).strip()
            results.append({
                'sentence': clean_sent,
                'ref_idx': int(ref),
                'pos': pos,
            })
        pos += len(sent) + 1

    return results


def build_evidence_map(refs: list[dict], evidence_ids: list[str]) -> list[dict]:
    """ref_idx → article_id 매핑.

    Parameters
    ----------
    refs : extract_refs() 결과
    evidence_ids : debate에서 수집된 article_id 리스트 (순서 = ref 번호)

    Returns
    -------
    [{'sentence': '...', 'article_id': 'b07523c195c0', 'ref_idx': 2}, ...]
    """
    results = []
    for r in refs:
        idx = r['ref_idx'] - 1  # 1-based → 0-based
        article_id = evidence_ids[idx] if 0 <= idx < len(evidence_ids) else None
        results.append({
            'sentence': r['sentence'],
            'ref_idx': r['ref_idx'],
            'article_id': article_id,
        })
    return results


def format_evidence_report(evidence_map: list[dict]) -> str:
    """사람 검수용 evidence 리포트."""
    if not evidence_map:
        return "evidence trace: 코멘트에 [ref:N] 태그 없음"

    lines = [f"evidence trace: {len(evidence_map)}건 매핑"]
    for e in evidence_map:
        aid = e['article_id'] or '(매핑 실패)'
        lines.append(f"  [ref:{e['ref_idx']}] {aid} — \"{e['sentence'][:60]}\"")
    return '\n'.join(lines)


if __name__ == '__main__':
    test = "3월 유가가 108달러를 돌파했다[ref:2]. 이란 분쟁이 5주차에 접어들었다[ref:1]. 금 가격은 15% 하락했다."
    refs = extract_refs(test)
    print(f'refs: {refs}')

    evidence_ids = ['b07523c195c0', 'c2715118960e', '0ff41e6f0792']
    emap = build_evidence_map(refs, evidence_ids)
    print(format_evidence_report(emap))
