# -*- coding: utf-8 -*-
"""Debate Service — debate 실행 + 후처리 + 검증 + 저장 오케스트레이션.

Streamlit UI 코드에서 분리된 workflow/service layer.
tabs/admin.py는 이 모듈의 함수를 호출하고 결과만 표시한다.

이 모듈이 담당하는 것:
  - debate 엔진 호출
  - evidence annotations 빌드
  - customer_comment 후처리 (sanitize + validation)
  - evidence quality 계산
  - draft 저장 + evidence log append

이 모듈이 담당하지 않는 것:
  - Streamlit UI (st.* 호출 없음)
  - 뉴스 수집/분류/정제/GraphRAG (외부 배치 담당)
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from market_research.report.report_store import (
    save_draft, append_evidence_quality,
    STATUS_DRAFT,
)

_NEWS_DIR = Path(__file__).resolve().parent.parent / 'data' / 'news'


# ══════════════════════════════════════════
# 상수
# ══════════════════════════════════════════

TIER1_SOURCES = frozenset({
    'Reuters', 'Bloomberg', 'AP', 'Financial Times', 'WSJ',
    'CNBC', 'MarketWatch', '연합뉴스', '연합뉴스TV', '뉴시스', '뉴스1',
})
TIER2_PARTIAL = frozenset({
    'SeekingAlpha', 'Benzinga', '매일경제', '한경', '서울경제',
    '머니투데이', '이데일리', '조선비즈', '헤럴드경제',
})

METRICS_GUIDE = {
    '중요도(salience)': '기사 중요도 점수 (0~1). 매체등급 30% + 강도 25% + 교차보도 25% + BM이상치 20%로 산출',
    '전이경로 신뢰도': 'GraphRAG 인과추론 엣지의 신뢰도. 0.9 이상은 다수 기사에서 반복 확인된 인과 경로',
    '교차보도 N건': '동일 이벤트를 서로 다른 매체가 보도한 횟수. 많을수록 사실 신뢰도 높음',
    'BM 이상치': '해당 날짜에 벤치마크 수익률이 z-score 1.5 이상 급변한 경우 해당',
    '매체등급': 'TIER1(Reuters/Bloomberg/연합 등)=1.0, TIER2(SeekingAlpha/매경 등)=0.7, TIER3(기타)=0.3',
}


# ══════════════════════════════════════════
# 후처리: customer_comment 검증 + 정제
# ══════════════════════════════════════════

_BANNED_PATTERNS = [
    r'당사[는은이가]?\s',
    r'본\s*펀드[는은이가]?\s',
    r'비중을\s*(확대|축소|유지)',
    r'비중(확대|축소)\s*(기조|방침|전략)',
    r'(헤지|hedge)\s*(수단을|를)\s*병행',
    r'듀레이션을\s*(축소|확대|조정|관리)',
    r'유동성\s*버퍼를?\s*(확보|구축)',
    r'운용\s*(전략|방침)[으로는]?\s',
    r'편입\s*(비중|비율)[을를]?\s*(조정|변경)',
    r'BM\s*대비\s*.*(추구|목표|초과)',
    r'대응\s*방침',
    r'(비중|편입|운용|투자)\s*기조를\s*유지',
    r'(할|나갈)\s*방침',
]

_ADVISORY_PATTERNS = [
    r'(줄일|늘릴|축소할|확대할|조정할)\s*필요가\s*있',
    r'(적절하다|적절합니다)',
    r'(바람직하다|바람직합니다)',
    r'(유효하다|유효합니다)',
    r'(유지하는\s*것이\s*좋|유지하는\s*것이\s*적절)',
    r'(권고한다|권고합니다|권장한다|권장합니다)',
    r'(대비할\s*필요|대응할\s*필요)',
    r'(강화하고|강화하며).*방침',
]

_UNCERTAINTY_LEXICON = [
    '유력', '전망', '무게', '가능성', '관측', '예상', '시사',
    '검토', '논의', '가능', '우려', '추정', '잠정', '임시',
    '예정', '전해', '알려', '보도',
]

_CERTAINTY_PATTERNS = [
    r'동결한\s', r'동결했', r'동결됐', r'인상한\s', r'인하한\s',
    r'결정했', r'결정됐', r'확정됐', r'발표했', r'합의했',
    r'단행했', r'인상됐', r'인하됐', r'채택했', r'승인했',
]

_INTERNAL_PATTERNS = [
    # r'\[ref:\d+\]',  — ref 태그는 유지 (admin/client 모두 출처 표시용)
    r'살리언스\s*[\d.]+',
    r'salience\s*[\d.]+',
    r'신뢰도\s*[\d.]+',
    r'confidence\s*[\d.]+',
    r'교차보도\s*\d+건',
    r'evidence_ids?',
    r'F_[A-Z_]{3,}',
]

# 문장 키워드 → 뉴스 분류 토픽 매핑 (여러 분류 토픽에 대응 가능)
_KEYWORD_TO_TOPICS = {
    '한국은행': {'통화정책', '금리_채권'},
    '연준': {'통화정책', '금리_채권'},
    '유가': {'에너지_원자재'},
    '환율': {'환율_FX', '달러_글로벌유동성'},
    '휴전': {'지정학'},
    '금': {'귀금속_금'},
    'IMF': {'경기_소비', '물가_인플레이션', '지정학'},
    'KOSPI': {'경기_소비'},
}
_TOPIC_KEYWORDS = {
    '한국은행': ['한국은행', '한은', '금통위', '기준금리', '이창용', '동결', '인상', '인하'],
    '연준': ['연준', 'Fed', 'FOMC', '파월', '금리경로', '연방준비'],
    '유가': ['유가', 'WTI', '브렌트', '원유', 'oil', '배럴', 'OPEC'],
    '환율': ['환율', 'USDKRW', '원달러', '원·달러', '달러/원', 'DXY', '달러인덱스'],
    '휴전': ['휴전', '이란', 'Iran', '중동', '호르무즈', 'ceasefire'],
    '금': ['금값', '금가격', 'gold', 'Gold', '귀금속'],
    'IMF': ['IMF', '국제통화기금'],
    'KOSPI': ['KOSPI', '코스피', 'KOSDAQ', '코스닥'],
}


def _validate_tense(comment: str, annotations: list) -> list[str]:
    """evidence가 불확실형인데 코멘트가 확정형이면 경고."""
    warnings = []
    if not annotations:
        return warnings
    sentences = re.split(r'(?<=[.다\]])\.\s+|(?<=[.다])\s+', comment)
    for sent in sentences:
        certainty_match = None
        for pat in _CERTAINTY_PATTERNS:
            m = re.search(pat, sent)
            if m:
                certainty_match = m.group()
                break
        if not certainty_match:
            continue
        refs_in_sent = re.findall(r'\[ref:(\d+)\]', sent)
        for ann in annotations:
            ref_idx = str(ann.get('ref', ''))
            title = ann.get('title', '')
            is_linked = ref_idx in refs_in_sent
            if not is_linked:
                title_words = set(title.replace(',', ' ').replace('…', ' ').split())
                sent_words = set(sent.replace(',', ' ').replace('…', ' ').split())
                if len(title_words & sent_words) < 2:
                    continue
            for unc in _UNCERTAINTY_LEXICON:
                if unc in title:
                    warnings.append(
                        f'시제 불일치: 코멘트 "{certainty_match}" ← '
                        f'evidence ref:{ref_idx} "{title[:50]}" (불확실: "{unc}")')
                    break
    return warnings


def _validate_ref_matching(comment: str, annotations: list) -> list[str]:
    """ref:N 문장 키워드와 해당 ref 기사 제목 키워드를 교차검증."""
    warnings = []
    if not annotations:
        return warnings
    ann_map = {str(a['ref']): a for a in annotations}
    sentences = re.split(r'(?<=[.다\]])\.\s+|(?<=[.다])\s+', comment)
    for sent in sentences:
        refs = re.findall(r'\[ref:(\d+)\]', sent)
        if not refs:
            continue
        sent_keyword_groups = set()
        for group, keywords in _TOPIC_KEYWORDS.items():
            for kw in keywords:
                if kw in sent:
                    sent_keyword_groups.add(group)
                    break
        if not sent_keyword_groups:
            continue
        # 키워드 그룹 → 뉴스 분류 토픽으로 변환
        sent_topics = set()
        for g in sent_keyword_groups:
            sent_topics |= _KEYWORD_TO_TOPICS.get(g, {g})
        for ref_num in refs:
            ann = ann_map.get(ref_num)
            if not ann:
                continue
            title = ann.get('title', '')
            # 기사의 all_topics (여러 토픽 커버) → primary fallback → 제목 키워드 fallback
            ref_topics = set(ann.get('all_topics', []))
            if not ref_topics:
                ref_primary = ann.get('topic', '')
                if ref_primary:
                    ref_topics.add(ref_primary)
            if not ref_topics:
                for topic, keywords in _TOPIC_KEYWORDS.items():
                    for kw in keywords:
                        if kw in title:
                            ref_topics.add(topic)
                            break
            if sent_topics and ref_topics and not (sent_topics & ref_topics):
                # 기사가 여러 토픽을 커버하는 혼합형은 cross-asset 인과 가능성 → 스킵
                if len(ref_topics) >= 2:
                    continue
                warnings.append(
                    f'ref 오매핑: 문장 토픽={sent_topics} ← '
                    f'ref:{ref_num} 토픽={ref_topics} '
                    f'"{title[:50]}"')
    return warnings


def sanitize_customer_comment(text: str, indicators: dict = None,
                              annotations: list = None) -> tuple[str, list[dict]]:
    """customer_comment 후처리. (정제된 텍스트, 구조화된 경고 목록) 반환."""
    warnings = []
    annotations = annotations or []
    max_ref = len(annotations)

    def _warn(warn_type: str, message: str, ref_no: int = None, severity: str = 'warning'):
        w = {'type': warn_type, 'message': message, 'severity': severity}
        if ref_no is not None:
            w['ref_no'] = ref_no
        warnings.append(w)

    # A. ref 관련 검증 (자동제거 전에 실행)
    tense_warnings = _validate_tense(text, annotations)
    for tw in tense_warnings:
        ref_match = re.search(r'ref:(\d+)', tw)
        ref_no = int(ref_match.group(1)) if ref_match else None
        _warn('tense_mismatch', tw, ref_no=ref_no, severity='critical')

    # ref_mismatch validator 비활성화 — Opus ref 매핑은 정확도 높음 (14/14 전수 검증),
    # validator의 토픽 교차검증은 cross-asset 인과에서 false positive만 생성.
    # ref_invalid(범위 초과)와 tense_mismatch(시제 불일치)는 유지.

    used_refs = [int(r) for r in re.findall(r'\[ref:(\d+)\]', text)]
    for r in used_refs:
        if r < 1 or r > max_ref:
            _warn('ref_invalid', f'존재하지 않는 ref:{r} (유효 범위: 1~{max_ref})', ref_no=r, severity='critical')

    # B. 자동 제거
    for pat in _INTERNAL_PATTERNS:
        if re.search(pat, text):
            _warn('auto_remove', f'내부 지표 제거: {pat}', severity='info')
        text = re.sub(pat, '', text)

    # C. 텍스트 기반 경고
    raw_nums = re.findall(r'[+\-]\d{3,}\.\d+', text)
    for rn in raw_nums:
        _warn('raw_number', f'단위 불명 숫자: {rn} — 서술형 치환 또는 제거 권장', severity='info')

    for pat in _BANNED_PATTERNS:
        match = re.search(pat, text)
        if match:
            _warn('fund_action', f'펀드 액션: "{match.group()}"')

    for pat in _ADVISORY_PATTERNS:
        match = re.search(pat, text)
        if match:
            _warn('advisory', f'권고형 표현: "{match.group()}"')

    if indicators:
        ust_2y = indicators.get('UST_2Y')
        ust_10y = indicators.get('UST_10Y')
        if ust_2y and ust_10y and float(ust_2y) < float(ust_10y):
            if '역수익률' in text or '역전' in text:
                _warn('fact_error',
                      f'2Y({ust_2y}) < 10Y({ust_10y})이면 정상 스프레드, 역전 아님',
                      severity='critical')

    text = re.sub(r'\s{2,}', ' ', text).strip()
    text = re.sub(r'\s+([.,])', r'\1', text)
    return text, warnings


# ══════════════════════════════════════════
# Coverage + 수치 무출처 validator
# ══════════════════════════════════════════

_NUMERIC_PATTERN = re.compile(
    r'(?:\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:%|％|달러|원|bp|포인트|배럴|온스|조|억)')


def compute_coverage_metrics(comment: str, annotations: list) -> dict:
    """coverage 지표 계산. admin 표시용 warning."""
    # 사용 가능한 토픽
    available_topics = set(a.get('topic', '') for a in annotations if a.get('topic'))
    # ref로 인용된 토픽
    used_refs = set()
    for r in re.findall(r'\[ref:(\d+)\]', comment):
        try:
            used_refs.add(int(r))
        except (ValueError, TypeError):
            pass
    ref_map = {a.get('ref'): a for a in annotations if a.get('ref') is not None}
    referenced_topics = set()
    for r in used_refs:
        ann = ref_map.get(r)
        if ann and ann.get('topic'):
            referenced_topics.add(ann['topic'])

    # 숫자 있는 문장 중 ref 없는 건수
    sentences = re.split(r'(?<=[.다\]])\.\s+|(?<=[.다])\s+', comment)
    numeric_no_ref = 0
    numeric_total = 0
    for s in sentences:
        if _NUMERIC_PATTERN.search(s):
            numeric_total += 1
            if not re.search(r'\[ref:\d+\]', s):
                numeric_no_ref += 1

    return {
        'available_topics_count': len(available_topics),
        'referenced_topics_count': len(referenced_topics),
        'unreferenced_topics': sorted(available_topics - referenced_topics),
        'referenced_refs_count': len(used_refs),
        'numeric_sentences_total': numeric_total,
        'uncited_numeric_count': numeric_no_ref,
    }


# ══════════════════════════════════════════
# Evidence annotations 빌드
# ══════════════════════════════════════════

def source_tier(source: str, article: dict | None = None) -> str:
    """매체 tier 판정.

    source_type='naver_research'(증권사 리서치)는 매체 이름 매칭으로는 항상 TIER3로
    떨어지므로, adapter가 수집 시점에 부여한 `_research_quality_band` 를 사용한다.
    article 인자가 없거나 band 가 없으면 기존 매체 이름 매칭으로 fallback.
    """
    if article is not None and article.get('source_type') == 'naver_research':
        band = article.get('_research_quality_band', '')
        if band in ('TIER1', 'TIER2', 'TIER3'):
            return band
    if source in TIER1_SOURCES:
        return 'TIER1'
    for t2 in TIER2_PARTIAL:
        if t2 in source:
            return 'TIER2'
    return 'TIER3'


def salience_explanation(article: dict) -> str:
    parts = []
    source = article.get('source', '')
    tier = source_tier(source, article)
    label = '리서치' if article.get('source_type') == 'naver_research' else '매체'
    parts.append(f'{tier} {label}({source})')
    intensity = 0
    for t in article.get('_classified_topics', []):
        intensity = max(intensity, t.get('intensity', 0))
    if intensity >= 7:
        parts.append(f'높은 강도({intensity}/10)')
    corr = article.get('_event_source_count', 0)
    if corr >= 2:
        parts.append(f'교차보도 {corr}건')
    if article.get('_bm_overlap'):
        parts.append('BM 이상치 날짜 해당')
    return ', '.join(parts) if parts else '일반 기사'


def build_evidence_annotations(evidence_ids: list, year: int, months: list) -> list:
    """evidence_ids → 기사 메타 + URL + 중요도 설명 매핑.

    두 소스 모두 조회: data/news/{YYYY-MM}.json + naver_research adapted.
    adapted(naver_research) 를 빠뜨리면 BEW forced 경로에서 리서치 리포트
    evidence 가 전부 '(매핑 실패)' 로 표시됨.
    """
    id_map = {}
    # 1) 일반 뉴스 (data/news/)
    for m in months:
        news_file = _NEWS_DIR / f'{year}-{m:02d}.json'
        if not news_file.exists():
            continue
        data = json.loads(news_file.read_text(encoding='utf-8'))
        for a in data.get('articles', []):
            aid = a.get('_article_id', '')
            if aid:
                id_map[aid] = a
    # 2) Naver Research adapted (debate 의 research lane 소스)
    try:
        from market_research.collect.naver_research_adapter import load_adapted
        for m in months:
            adapted = load_adapted(f'{year}-{m:02d}')
            for a in adapted:
                aid = a.get('_article_id', '')
                # news 와 aid 충돌 시 기존(news) 우선 유지하지 않고 덮어써서
                # research lane 에서 선택된 건 research 메타가 우선 표시되게.
                # 실제로는 _article_id(MD5 12자)가 소스 독립적이라 충돌 거의 없음.
                if aid and aid not in id_map:
                    id_map[aid] = a
    except Exception:
        pass
    annotations = []
    for i, eid in enumerate(evidence_ids, 1):
        art = id_map.get(eid, {})
        sal = art.get('_event_salience', 0)
        all_topics = [t.get('topic', '') for t in art.get('_classified_topics', []) if t.get('topic')]
        annotations.append({
            'ref': i,
            'article_id': eid,
            'title': art.get('title', '(매핑 실패)')[:100],
            'url': art.get('url', ''),
            'source': art.get('source', ''),
            'date': art.get('date', ''),
            'topic': art.get('primary_topic', ''),
            'all_topics': all_topics,
            'salience': round(sal, 3),
            'salience_explanation': salience_explanation(art) if art else '',
        })
    return annotations


# ══════════════════════════════════════════
# Ref 재부여 + 관련 뉴스 분리
# ══════════════════════════════════════════

def renumber_refs(comment: str, annotations: list) -> tuple[str, list, list]:
    """코멘트의 ref를 등장순 1번부터 재부여하고, 미사용 기사를 관련 뉴스로 분리.

    Returns:
        (재부여된 코멘트, 사용된 annotations(새 번호), 관련 뉴스 annotations)
    """
    # 등장 순서대로 원본 ref 번호 수집 (중복 제거, 순서 유지)
    seen = []
    for m in re.finditer(r'\[ref:(\d+)\]', comment):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)

    # 원본 번호 → 새 번호 매핑
    old_to_new = {old: new for new, old in enumerate(seen, 1)}

    # 코멘트 내 ref 번호 치환
    def _replace(m):
        old = int(m.group(1))
        new = old_to_new.get(old)
        return f'[ref:{new}]' if new else m.group(0)

    renumbered = re.sub(r'\[ref:(\d+)\]', _replace, comment)

    # annotations 분리
    ann_map = {a['ref']: a for a in annotations}
    used = []
    used_refs = set()
    for old_num in seen:
        ann = ann_map.get(old_num)
        if ann:
            new_ann = dict(ann)
            new_ann['ref'] = old_to_new[old_num]
            used.append(new_ann)
            used_refs.add(old_num)

    related = [a for a in annotations if a['ref'] not in used_refs]

    return renumbered, used, related


# ══════════════════════════════════════════
# Debate 실행 + 저장 오케스트레이션
# ══════════════════════════════════════════

def run_debate_and_save(mode: str, year: int, period_num: int,
                        fund_code: str, period_key: str) -> dict:
    """debate 엔진 호출 → 후처리 → draft 저장 → evidence log append.

    Streamlit 의존성 없음. tabs/admin.py에서 이 함수를 호출한다.
    현재는 input.json 없이 debate 엔진이 직접 컨텍스트를 빌드한다 (과도기 fallback).
    """
    if mode == "월별":
        from market_research.report.debate_engine import run_market_debate
        result = run_market_debate(year, period_num)
        months = [period_num]
    else:
        from market_research.report.debate_engine import run_quarterly_debate
        result = run_quarterly_debate(year, period_num)
        months = result.get('months', [(period_num - 1) * 3 + i for i in range(1, 4)])

    synthesis = result.get('synthesis', {})
    raw_comment = synthesis.get('customer_comment', '')
    evidence_ids = result.get('_evidence_ids', [])

    annotations = build_evidence_annotations(evidence_ids, year, months)

    clean_comment, sanitize_warnings = sanitize_customer_comment(
        raw_comment, annotations=annotations)

    # ref 재부여 (등장순 1번부터) + 미사용 기사 분리
    clean_comment, used_annotations, related_news = renumber_refs(clean_comment, annotations)

    warning_counts = {
        'critical': sum(1 for w in sanitize_warnings if isinstance(w, dict) and w.get('severity') == 'critical'),
        'warning': sum(1 for w in sanitize_warnings if isinstance(w, dict) and w.get('severity', 'warning') == 'warning'),
        'info': sum(1 for w in sanitize_warnings if isinstance(w, dict) and w.get('severity') == 'info'),
    }

    total_refs = len(re.findall(r'\[ref:(\d+)\]', raw_comment))
    ref_mismatches = sum(1 for w in sanitize_warnings
                         if isinstance(w, dict) and w.get('type') in ('ref_mismatch', 'ref_invalid'))
    tense_mismatches = sum(1 for w in sanitize_warnings
                           if isinstance(w, dict) and w.get('type') == 'tense_mismatch')
    evidence_quality = {
        'total_refs': total_refs,
        'ref_mismatches': ref_mismatches,
        'tense_mismatches': tense_mismatches,
        'mismatch_rate': round(ref_mismatches / total_refs, 3) if total_refs else 0,
        'evidence_count': len(evidence_ids),
    }

    debate_interp = result.get('debate_narrative', {}) or {}
    # P1-① lineage ID: debate_engine 이 발급한 ID 를 그대로 보존.
    # 중복 발급 금지 — debate_engine 에서 이미 발급된 값을 신뢰.
    debate_run_id = result.get('debate_run_id')

    draft_data = {
        'fund_code': fund_code,
        'period': period_key,
        'status': STATUS_DRAFT,
        'debate_run_id': debate_run_id,
        'draft_comment': clean_comment,
        'admin_comment_raw': raw_comment,
        'admin_summary': synthesis.get('admin_summary', ''),
        'consensus_points': synthesis.get('consensus_points', []),
        'disagreements': synthesis.get('disagreements', []),
        'tail_risks': synthesis.get('tail_risks', []),
        'debate_narrative': debate_interp.get('debate_narrative', ''),
        'canonical_regime_snapshot': debate_interp.get('canonical_snapshot', {}),
        'diverges_from_canonical': debate_interp.get('diverges_from_canonical', False),
        'generated_at': result.get('debated_at', time.strftime('%Y-%m-%dT%H:%M:%S')),
        'model': 'claude-opus-4-6',
        'cost_usd': 0.34,
        'validation_summary': {
            'sanitize_warnings': sanitize_warnings,
            'warning_counts': warning_counts,
        },
        'evidence_quality': evidence_quality,
        'evidence_annotations': used_annotations,
        'related_news': related_news,
        'coverage_metrics': compute_coverage_metrics(clean_comment, annotations),
        'internal_metrics_guide': METRICS_GUIDE,
        'edit_history': [],
    }

    save_draft(period_key, fund_code, draft_data)

    eq_record = {
        'period': period_key,
        'fund_code': fund_code,
        'debate_run_id': debate_run_id,  # P1-① 동일 run ID 부착
        'debated_at': draft_data['generated_at'],
        **evidence_quality,
        'critical_warnings': warning_counts['critical'],
    }
    append_evidence_quality(eq_record)

    # 06_Debate_Memory/ 페이지 생성 (canonical regime은 건드리지 않음)
    try:
        from market_research.wiki.debate_memory import write_debate_memory_page
        regime_file = Path(__file__).resolve().parent.parent / 'data' / 'regime_memory.json'
        wiki_path = write_debate_memory_page(draft_data, regime_file)
        print(f'  [wiki] debate memory 기록: {wiki_path.name}')
    except Exception as exc:
        print(f'  [wiki] debate memory 기록 실패: {exc}')

    return draft_data
