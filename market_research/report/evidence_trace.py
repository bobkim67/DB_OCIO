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

# R9-A.3: claim reference matching `[claim:hash10]` (10 hex). Strict 10-char
# hex to avoid colliding with wider URL-like patterns. Hash10 은 R9-A.0
# compute_claim_id 의 md5[:10] 출력과 동형.
CLAIM_REF_RE = re.compile(r"\[claim:([0-9a-fA-F]{10})\]")


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


def strip_claim_refs(text: str) -> str:
    """LLM 원문에서 [claim:hash10] 태그 제거 (고객용). 앞 공백 한 칸까지."""
    if not text:
        return text or ""
    return re.sub(r"\s*\[claim:[0-9a-fA-F]{10}\]", "", text)


# ──────────────────────────────────────────────────────────────────
# R9-A.3 — Claim reference trace
# ──────────────────────────────────────────────────────────────────

def extract_claim_refs(comment_text: str) -> list[dict]:
    """[claim:hash10] 인용 추출 (트레이스용).

    Returns:
        [{'hash10': 'abc1234567', 'pos': 142}, ...]
    중복 등장은 그대로 유지 (count 정보 보존). 빈/None 입력은 [].
    """
    if not comment_text:
        return []
    out: list[dict] = []
    for m in CLAIM_REF_RE.finditer(comment_text):
        out.append({
            "hash10": m.group(1),
            "pos": m.start(),
        })
    return out


def build_claim_evidence_map(
    refs: list[dict] | None,
    canonical_claims: list[dict] | None,
) -> list[dict]:
    """[claim:hash10] → canonical claim metadata 매핑 (read-only).

    canonical_claims: build_report_prompt 에 주입된 inputs['claims'] 또는
    debate context 의 _canonical_claims (R9-A.3 promotion-passing).

    Returns:
        [{'hash10', 'claim_id', 'wiki_path', 'source_type', 'pos',
          'matched': bool}, ...]
    매칭 실패는 source_type='unmatched' / matched=False 로 row 유지
    (silent drop X — comment_trace 가 invalid claim ref 도 surface).
    """
    if not refs:
        return []
    by_h: dict[str, dict] = {}
    for c in canonical_claims or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("claim_id") or ""
        if isinstance(cid, str) and cid.startswith("claim:"):
            h = cid.rsplit(":", 1)[-1]
            by_h[h] = c

    out: list[dict] = []
    for r in refs:
        h = r.get("hash10")
        c = by_h.get(h) if isinstance(h, str) else None
        if c:
            cid = c.get("claim_id") or ""
            period = c.get("period") or ""
            wiki_path = (
                f"08_Claims/{period}_claim_{h}.md"
                if period and h else None
            )
            out.append({
                "hash10": h,
                "claim_id": cid,
                "wiki_path": wiki_path,
                "source_type": "claim_wiki",
                "pos": r.get("pos"),
                "matched": True,
            })
        else:
            out.append({
                "hash10": h,
                "claim_id": None,
                "wiki_path": None,
                "source_type": "unmatched",
                "pos": r.get("pos"),
                "matched": False,
            })
    return out


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


def validate_claim_citations(comment_text: str,
                              canonical_claims: list[dict] | None) -> dict:
    """R9-A.5 — section 별 [claim:hash10] 파싱 + canonical 매핑 검증.

    `validate_citations` 의 [claim:hash10] 미러. comment_trace 와 admin viewer
    가 동일 schema 로 ref/claim 양쪽을 surface 할 수 있도록 같은 모양 사용.

    Parameters
    ----------
    comment_text : LLM 원문 ([claim:hash10] 포함)
    canonical_claims : promotion-passing claim list. 보통
        market_research.analyze.claim_store.select_promoted_claims_for_period()
        결과를 사용한다.

    Returns
    -------
    {
        'claim_citations': [
            {
                'section_id', 'section_title',
                'claim_hashes': sorted unique 10-hex,
                'claim_ids':   sorted unique full claim_id (matched 만),
                'wiki_paths':  matched 의 wiki_path,
                'unmatched_hashes': matched 못한 hash10 list,
                'citation_type': 'claim_explicit' | 'claim_section_default',
            },
            ...
        ],
        'claim_citation_validation': {
            'total_claim_refs': int,         # [claim:X] 등장 횟수 (중복 포함)
            'matched_count': int,            # canonical 에 존재하는 등장
            'unmatched_count': int,          # canonical 에 없는 등장
            'unmatched_hashes': list[str],   # 고유 unmatched hash10
            'sections_with_claim_count': int,
            'sections_without_claim_count': int,
            'warnings': list[str],
        },
    }
    """
    sections = split_sections(comment_text or "")
    by_hash: dict[str, dict] = {}
    for c in canonical_claims or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("claim_id") or ""
        if isinstance(cid, str) and cid.startswith("claim:"):
            h = cid.rsplit(":", 1)[-1]
            by_hash[h] = c

    claim_citations: list[dict] = []
    total_claim_refs = 0
    matched_count = 0
    unmatched_count = 0
    unmatched_hashes_acc: set[str] = set()
    sections_with_claim_count = 0
    sections_without_claim_count = 0
    warnings: list[str] = []

    for sec in sections:
        text = sec["text"]
        all_hashes = [m.group(1) for m in CLAIM_REF_RE.finditer(text)]
        unique_hashes = sorted(set(all_hashes))
        total_claim_refs += len(all_hashes)

        if not unique_hashes:
            sections_without_claim_count += 1
            claim_citations.append({
                "section_id": sec["section_id"],
                "section_title": sec["section_title"],
                "claim_hashes": [],
                "claim_ids": [],
                "wiki_paths": [],
                "unmatched_hashes": [],
                "citation_type": "claim_section_default",
            })
            continue

        sections_with_claim_count += 1
        sec_matched_ids: list[str] = []
        sec_wiki_paths: list[str] = []
        sec_unmatched: list[str] = []
        for h in unique_hashes:
            c = by_hash.get(h)
            if c:
                cid = c.get("claim_id") or ""
                # R9-A.5.x — compact schema (R9-A.3.x persistence) 가 이미
                # wiki_path 필드를 갖고 있으면 그대로 사용. 그렇지 않은 경우
                # (full canonical 등) 만 period+hash 로 재추정. fund_comment
                # 가 받는 compact 에는 'period' 키가 없기 때문에 재추정만
                # 시도하면 빈 wiki_path 가 됨 → draft.claim_citations.
                # wiki_paths 가 비는 회귀 발생.
                preset = c.get("wiki_path")
                if isinstance(preset, str) and preset:
                    wiki_path = preset
                else:
                    period = c.get("period") or ""
                    wiki_path = (
                        f"08_Claims/{period}_claim_{h}.md"
                        if period and h else None
                    )
                sec_matched_ids.append(cid)
                if wiki_path:
                    sec_wiki_paths.append(wiki_path)
                matched_count += all_hashes.count(h)
            else:
                sec_unmatched.append(h)
                unmatched_count += all_hashes.count(h)
                unmatched_hashes_acc.add(h)
                warnings.append(
                    f"section {sec['section_id']}: "
                    f"[claim:{h}] not in canonical_claims"
                )

        claim_citations.append({
            "section_id": sec["section_id"],
            "section_title": sec["section_title"],
            "claim_hashes": unique_hashes,
            "claim_ids": sorted(set(sec_matched_ids)),
            "wiki_paths": sorted(set(sec_wiki_paths)),
            "unmatched_hashes": sorted(set(sec_unmatched)),
            "citation_type": "claim_explicit",
        })

    return {
        "claim_citations": claim_citations,
        "claim_citation_validation": {
            "total_claim_refs": total_claim_refs,
            "matched_count": matched_count,
            "unmatched_count": unmatched_count,
            "unmatched_hashes": sorted(unmatched_hashes_acc),
            "sections_with_claim_count": sections_with_claim_count,
            "sections_without_claim_count": sections_without_claim_count,
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
