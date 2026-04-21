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
