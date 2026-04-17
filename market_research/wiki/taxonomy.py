# -*- coding: utf-8 -*-
"""Taxonomy contract for canonical regime / wiki pages.

**Single source of truth** for `topic_tags`: must be exact TOPIC_TAXONOMY labels
(re-exported from news_classifier). Free-text phrases like "지정학 완화" or
"구조적 인플레" must NOT appear in `topic_tags` — those belong in
`narrative_description` instead.

Utility:
  - `extract_taxonomy_tags(raw)` → (exact_tags, unresolved_phrases)
  - `validate_tags(tags)` → (valid, invalid)
  - `is_taxonomy_tag(tag)`
"""
from __future__ import annotations

import json as _json
from pathlib import Path

from market_research.analyze.news_classifier import TOPIC_TAXONOMY

TAXONOMY_SET = frozenset(TOPIC_TAXONOMY)


# ══════════════════════════════════════════
# Phrase → taxonomy alias map
# ══════════════════════════════════════════

# Controlled mapping only. Ambiguous phrases (e.g., 단독 "달러") must NOT
# appear here — let them fall through to `unresolved` rather than guessing.
PHRASE_ALIAS: dict[str, str] = {
    # 지정학
    '지정학': '지정학',
    '지정학적': '지정학',
    '지정학적 리스크': '지정학',
    '지정학적 완화': '지정학',
    '지정학적 안도감': '지정학',
    '지정학 리스크': '지정학',
    '지정학 완화': '지정학',
    '지정학 위기': '지정학',
    '중동': '지정학',
    '이란': '지정학',
    '휴전': '지정학',
    '휴전 완화': '지정학',
    '휴전 안도감': '지정학',

    # 물가/인플레
    '인플레': '물가_인플레이션',
    '인플레이션': '물가_인플레이션',
    '구조적 인플레': '물가_인플레이션',
    '인플레 재점화': '물가_인플레이션',
    '에너지 인플레이션': '물가_인플레이션',

    # 에너지/원자재
    '유가': '에너지_원자재',
    '유가 급등': '에너지_원자재',
    '유가 충격': '에너지_원자재',
    '원유': '에너지_원자재',
    '에너지_원자재': '에너지_원자재',

    # 환율
    '환율': '환율_FX',
    '환율_FX': '환율_FX',
    '원달러': '환율_FX',
    '엔화 캐리': '환율_FX',
    '엔화 캐리트레이드': '환율_FX',

    # 달러 유동성
    '달러 기근': '달러_글로벌유동성',
    '달러 부족': '달러_글로벌유동성',
    '유로달러': '달러_글로벌유동성',
    '달러_글로벌유동성': '달러_글로벌유동성',

    # 유동성 크레딧
    '유동성 경색': '유동성_크레딧',
    '유동성_크레딧': '유동성_크레딧',
    '크레딧 스프레드': '유동성_크레딧',
    '레포': '유동성_크레딧',

    # 귀금속
    '금값': '귀금속_금',
    '금 가격': '귀금속_금',
    '귀금속': '귀금속_금',
    '안전자산': '귀금속_금',
    '귀금속_금': '귀금속_금',

    # 통화정책
    '연준': '통화정책',
    'Fed': '통화정책',
    'FOMC': '통화정책',
    '기준금리': '통화정책',
    '통화정책': '통화정책',
    '한국은행': '통화정책',
    '금통위': '통화정책',

    # 금리_채권
    '금리': '금리_채권',
    '금리_채권': '금리_채권',
    '국채': '금리_채권',
    '채권': '금리_채권',
    '수익률 커브': '금리_채권',

    # 관세/무역
    '관세': '관세_무역',
    '무역': '관세_무역',
    '관세_무역': '관세_무역',

    # 테크/AI
    'AI': '테크_AI_반도체',
    '반도체': '테크_AI_반도체',
    '빅테크': '테크_AI_반도체',
    '테크_AI_반도체': '테크_AI_반도체',

    # 경기/부동산/크립토 직결 매핑
    '경기_소비': '경기_소비',
    '경기': '경기_소비',
    '부동산': '부동산',
    '크립토': '크립토',
    '비트코인': '크립토',
}


# ══════════════════════════════════════════
# Approved alias overlay (config/phrase_alias_approved.yaml)
# ══════════════════════════════════════════

def _load_approved_alias() -> dict[str, str]:
    """Optional runtime merge of ``config/phrase_alias_approved.yaml``.

    Returns ``{}`` when:
      - the file does not exist
      - PyYAML is not installed
      - the file fails to parse

    Only entries whose *value* is an exact TOPIC_TAXONOMY label are kept.
    Anything else is silently dropped here — the validator in
    ``tools/alias_review.py --apply`` is what surfaces the full reject list
    to the reviewer.
    """
    yaml_path = (Path(__file__).resolve().parent.parent
                 / 'config' / 'phrase_alias_approved.yaml')
    if not yaml_path.exists():
        return {}
    try:
        import yaml  # PyYAML
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding='utf-8')) or {}
    except Exception:
        return {}
    approved = data.get('approved') if isinstance(data, dict) else None
    if not isinstance(approved, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in approved.items():
        ks = str(k).strip()
        vs = str(v).strip()
        if not ks or not vs:
            continue
        if vs not in TAXONOMY_SET:
            continue
        out[ks] = vs
    return out


# Overlay approved aliases without overriding built-in entries.
# Built-in PHRASE_ALIAS wins on conflict (setdefault semantics).
_APPROVED_ALIAS = _load_approved_alias()
for _k, _v in _APPROVED_ALIAS.items():
    PHRASE_ALIAS.setdefault(_k, _v)


# ══════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════

def is_taxonomy_tag(tag: str) -> bool:
    return tag in TAXONOMY_SET


def validate_tags(tags: list[str]) -> tuple[list[str], list[str]]:
    """(valid_taxonomy_tags, invalid_tags) 반환. 중복 제거 (순서 유지)."""
    seen: set = set()
    valid: list[str] = []
    invalid: list[str] = []
    for t in tags or []:
        t = (t or '').strip()
        if not t or t in seen:
            continue
        seen.add(t)
        if t in TAXONOMY_SET:
            valid.append(t)
        else:
            invalid.append(t)
    return valid, invalid


def extract_taxonomy_tags(raw: str | list | None,
                          trace: list | None = None,
                          source: str = '') -> tuple[list[str], list[str]]:
    """서술형 또는 혼합 입력에서 taxonomy tag만 추출.

    Returns
    -------
    (taxonomy_tags, unresolved_phrases)
      - taxonomy_tags: TOPIC_TAXONOMY에 포함된 exact label (중복 제거, 순서 유지)
      - unresolved_phrases: 매핑 실패한 raw phrase

    Parameters
    ----------
    trace : list | None
        주어지면 각 매핑 결과를 append (dict). 호출자가 나중에 jsonl 기록.
    source : str
        trace에 기록할 출처 태그 ('regime_current', 'history_entry[3]' 등).

    Rules
    -----
    1. 이미 taxonomy tag면 그대로 포함 (match_type=exact)
    2. PHRASE_ALIAS로 매핑 시도 (match_type=alias)
    3. 공백 정규화 후 재시도 (match_type=alias_normalized)
    4. 실패한 phrase는 unresolved (억지 매핑 금지)
    """
    if raw is None:
        return [], []

    # 리스트로 정규화
    if isinstance(raw, str):
        s = raw.replace(' + ', '|').replace(' vs ', '|') \
               .replace(',', '|').replace(':', '|').replace(' | ', '|')
        phrases = [p.strip() for p in s.split('|') if p.strip()]
    else:
        phrases = [str(p).strip() for p in raw if p and str(p).strip()]

    tags: list[str] = []
    unresolved: list[str] = []
    seen_tags: set = set()

    for phrase in phrases:
        # 1. exact taxonomy match
        if phrase in TAXONOMY_SET:
            if phrase not in seen_tags:
                tags.append(phrase)
                seen_tags.add(phrase)
            if trace is not None:
                trace.append({
                    'source': source,
                    'original_phrase': phrase,
                    'mapped_tag': phrase,
                    'match_type': 'exact',
                    'confidence': 1.0,
                })
            continue

        # 2. alias map lookup
        mapped = PHRASE_ALIAS.get(phrase)
        if mapped and mapped in TAXONOMY_SET:
            if mapped not in seen_tags:
                tags.append(mapped)
                seen_tags.add(mapped)
            if trace is not None:
                trace.append({
                    'source': source,
                    'original_phrase': phrase,
                    'mapped_tag': mapped,
                    'match_type': 'alias',
                    'confidence': 0.92,
                })
            continue

        # 3. 공백 정규화 재시도
        norm = phrase.replace('  ', ' ').strip()
        if norm != phrase and norm in PHRASE_ALIAS:
            mapped = PHRASE_ALIAS[norm]
            if mapped not in seen_tags:
                tags.append(mapped)
                seen_tags.add(mapped)
            if trace is not None:
                trace.append({
                    'source': source,
                    'original_phrase': phrase,
                    'mapped_tag': mapped,
                    'match_type': 'alias_normalized',
                    'confidence': 0.85,
                })
            continue

        # 실패
        unresolved.append(phrase)
        if trace is not None:
            trace.append({
                'source': source,
                'original_phrase': phrase,
                'mapped_tag': None,
                'match_type': 'unresolved',
                'confidence': 0.0,
                'reason': 'non-taxonomy descriptive phrase',
            })

    return tags, unresolved


def write_remap_trace(trace: list, out_path) -> int:
    """trace 리스트를 jsonl로 append. Returns appended row count."""
    if not trace:
        return 0
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'a', encoding='utf-8') as fh:
        for row in trace:
            fh.write(_json.dumps(row, ensure_ascii=False) + '\n')
    return len(trace)
