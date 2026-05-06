# -*- coding: utf-8 -*-
"""
Multi-Agent Debate Engine - 4인 교차 검증 + Opus 종합
=====================================================
4인 에이전트:
  Bull(낙관) / Bear(비관) / Quant(데이터) / monygeek(유로달러 학파)

핵심 규칙:
  - Quant = Priority Anchor (충돌 시 indicators.csv 수치 우선)
  - monygeek: 지표 괴리 +/-20% -> 'Tail Risk' 레이블
  - 수치 가드레일: indicators/PA 수치 100% 일치, LLM 반올림 금지

이중 출력:
  - customer_comment: 합의된 전문가 톤 -> 운용보고 탭
  - admin_debate_log: 4인 시각 + 합의/쟁점 -> admin 전용

사용법:
    python -m market_research.debate_engine 08N81 2026 3
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
REGIME_FILE = BASE_DIR / 'data' / 'regime_memory.json'
DEBATE_LOG_DIR = BASE_DIR / 'data' / 'debate_logs'
DEBATE_LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── 디버그 로그 수집 (실행 중 append, 실행 끝에 파일 저장) ──
_debug_log: list[dict] = []


def _log(event: str, **kwargs):
    """디버그 로그 항목 추가."""
    entry = {'event': event, 'ts': time.strftime('%H:%M:%S'), **kwargs}
    _debug_log.append(entry)


# ===================================================================
# 에이전트 페르소나 정의
# ===================================================================

AGENT_PERSONAS = {
    'bull': {
        'name': '낙관론자',
        'model': 'claude-haiku-4-5-20251001',
        'system_prompt': (
            '당신은 성장 촉매와 회복 신호를 중시하는 낙관적 시장 분석가입니다.\n'
            '[중요] 당신의 stance는 반드시 "bullish"여야 합니다. 이것이 당신의 역할입니다.\n'
            '- 어떤 시장 상황에서든 긍정적 해석을 먼저 제시하세요\n'
            '- 위기 속 기회, 과매도 반등, 정책 대응 기대, 기술 혁신 등에 주목\n'
            '- 리스크를 인정하되, 시장의 자정 능력과 정책 대응을 신뢰\n'
            '- 구체적 수치 근거를 반드시 제시\n'
            '- 자산배분 관점에서 비중 확대 기회를 중심으로 의견 제시'
        ),
    },
    'bear': {
        'name': '비관론자',
        'model': 'claude-haiku-4-5-20251001',
        'system_prompt': (
            '당신은 꼬리 리스크와 과열 신호를 중시하는 비관적 시장 분석가입니다.\n'
            '- 밸류에이션 과열, 유동성 위축, 지정학 리스크, 신용 스프레드 확대 등에 주목\n'
            '- 역사적 패턴과 구조적 취약점을 강조\n'
            '- "이번에는 다르다"는 논리에 회의적\n'
            '- 구체적 수치 근거를 반드시 제시\n'
            '- 자산배분 관점에서 방어적 포지셔닝 의견 제시'
        ),
    },
    'quant': {
        'name': '데이터 분석가',
        'model': 'claude-haiku-4-5-20251001',
        'system_prompt': (
            '당신은 데이터와 수치에만 기반하는 정량적 분석가입니다.\n'
            '- 내러티브나 감정을 배제하고 오직 숫자로만 판단\n'
            '- 통계적 이상치, 추세 이탈, 상관관계 변화에 주목\n'
            '- VIX, MOVE, 금리 스프레드, EPS 변화율 등 핵심 지표 중심\n'
            '- 제공된 수치를 절대 수정하거나 반올림하지 마세요 (원본 그대로 인용)\n'
            '- 다른 에이전트와 충돌 시, 당신의 수치 분석이 우선합니다 (Priority Anchor)'
        ),
    },
    'monygeek': {
        'name': '유로달러 학파 분석가',
        'model': 'claude-haiku-4-5-20251001',
        'system_prompt': (
            '당신은 유로달러 학파(Jeff Snider 계열) 관점의 매크로 분석가입니다.\n'
            '- 핵심 프레임워크: 유로달러 시스템의 구조적 붕괴가 모든 자산 가격의 근본 드라이버\n'
            '- "달러 유동성이 모든 것을 결정한다" - Fed는 전능하지 않다\n'
            '- 주류 해석에 대한 대안적 시각 제시 (예: 달러 강세 = 미국 경제 강세가 아닌 글로벌 유동성 부족)\n'
            '- 가격이 먼저 움직이고 내러티브가 뒤를 따른다\n'
            '- 당신의 리스크 분석이 실제 지표(MOVE, TED Spread 등)와 +/-20% 이상 괴리될 경우,\n'
            '  해당 리스크를 반드시 "Tail Risk"로 명시하세요'
        ),
    },
}


# ===================================================================
# API 헬퍼
# ===================================================================

def _get_api_key():
    key = os.getenv('ANTHROPIC_API_KEY')
    if not key:
        try:
            from market_research.core.constants import ANTHROPIC_API_KEY
            key = ANTHROPIC_API_KEY
        except ImportError:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                'ce', BASE_DIR / 'comment_engine.py')
            ce = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ce)
            key = ce.ANTHROPIC_API_KEY
    return key


def _call_llm(model: str, system: str, prompt: str, max_tokens: int = 1500,
              log_label: str = '') -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=_get_api_key())
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = response.content[0].text.strip()
    usage = response.usage
    _log('llm_call', label=log_label, model=model, max_tokens=max_tokens,
         input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
         system_preview=system[:200], prompt_preview=prompt[:500],
         response_preview=text[:500])
    return text


def _parse_json_response(text: str):
    try:
        from market_research.core.json_utils import parse_json_response
        return parse_json_response(text, expect='object')
    except ImportError:
        # importlib로 로드된 경우 상대 import 실패 → 직접 로드
        import importlib.util as _ilu
        _p = Path(__file__).resolve().parent / 'json_utils.py'
        _spec = _ilu.spec_from_file_location('json_utils', _p)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod.parse_json_response(text, expect='object')


# ===================================================================
# Source-aware evidence selection (2026-04-22)
# research=primary lane / news=corroboration lane
# ===================================================================

RESEARCH_QUOTA = 0.7    # research 목표 비율 (나머지 = news quota)
MAX_PER_TOPIC = 5
MAX_PER_EVENT = 2
LATEST_SLOT = 2         # 당일 TIER1/2 news 전용 슬롯 (news quota 내)

# news corroboration lane 필터: primary_topic 명시 리스트
# 부동산/크립토는 기본 제외
NEWS_CLEAR_TOPICS = frozenset({
    '통화정책', '금리_채권', '물가_인플레이션', '경기_소비',
    '유동성_크레딧', '환율_FX', '달러_글로벌유동성',
    '에너지_원자재', '귀금속_금',
    '지정학', '관세_무역', '테크_AI_반도체',
})

_TIER1_NEWS_SOURCES = frozenset({
    'Reuters', 'Bloomberg', 'AP', 'Financial Times', 'WSJ',
    'CNBC', 'MarketWatch', '연합뉴스', '연합뉴스TV', '뉴시스', '뉴스1',
})
_TIER2_NEWS_PARTIAL = frozenset({
    '헤럴드경제', '매일경제', '한경', '서울경제',
    '머니투데이', '이데일리', 'SBS',
})


def _is_news_tier12(article: dict) -> bool:
    src = article.get('source', '') or ''
    if src in _TIER1_NEWS_SOURCES:
        return True
    return any(t2 in src for t2 in _TIER2_NEWS_PARTIAL)


def _news_passes_corroboration(article: dict) -> bool:
    """news 후보 필터: TIER1/2 AND (bm_anomaly OR cross>=3 OR primary_topic 명시리스트)."""
    if not _is_news_tier12(article):
        return False
    if article.get('_bm_overlap'):
        return True
    if int(article.get('_event_source_count', 0) or 0) >= 3:
        return True
    return article.get('primary_topic', '') in NEWS_CLEAR_TOPICS


def _load_bew_contract(year: int, month: int) -> dict | None:
    """BEW visualization contract 로드. 없거나 깨졌으면 None.

    fallback 경로: 기존 quota lane으로 직행.
    """
    fp = BASE_DIR / 'data' / 'benchmark_events' / f'{year}-{month:02d}.json'
    if not fp.exists():
        return None
    try:
        c = json.loads(fp.read_text(encoding='utf-8'))
    except Exception:
        return None
    if not isinstance(c, dict) or not c.get('windows') or not c.get('evidence_cards'):
        return None
    return c


def _build_evidence_candidates(year: int, month: int, target_count: int,
                               start_idx: int,
                               *,
                               force_window_ids: set[str] | None = None,
                               ) -> tuple[list, list, list, dict]:
    """source-aware evidence 선발.

    우선순위 (2026-04-22 v2):
      1) BEW (Benchmark Event Window) contract 가 있으면 confidence 상위 window 순으로
         evidence 를 먼저 채움 (각 evidence 는 article_id 로 nr/news pool 에서 lookup).
      2) BEW 가 없거나 부족하면 기존 quota lane (research/news + 당일 TIER1/2 slot)으로 보충.
      3) topic/event guardrail (MAX_PER_TOPIC=5, MAX_PER_EVENT=2) 은 전체 합산 기준 유지.
      4) 총량은 target_count 고정 — BEW 경로가 있어도 늘리지 않음.

    force_window_ids (옵션):
      - None (기본): 전체 BEW contract 동작 그대로.
      - set[str] 제공 시, BEW lane 내부에서 해당 wid 만 evidence queue 에 남김.
        wid 에 해당하지 않는 evidence 는 bew_nr_ordered/bew_news_ordered 에서 제외.
        보충 lane(research_pool/news_pool) / quota / guardrail / fallback 는 불변.

    Returns:
        (high_impact, evidence_ids, card_lines, debug)
        - card_lines는 "주요 뉴스 ..." 헤더부터의 렌더 라인들
        - debug: 기존 키(research_picked/news_picked/...) 전부 유지 + bew_* 키 추가
    """
    from datetime import date as _date

    # ── Lane A: research primary (is_primary + classified + TIER1/2) ──
    research_pool: list[dict] = []
    try:
        from market_research.collect.naver_research_adapter import load_adapted
        adapted = load_adapted(f'{year}-{month:02d}')
        for a in adapted:
            if not a.get('_classified_topics'):
                continue
            if not a.get('is_primary', True):
                continue
            band = a.get('_research_quality_band', '')
            if band not in ('TIER1', 'TIER2'):
                continue
            research_pool.append(a)
    except Exception:
        research_pool = []
    research_pool.sort(key=lambda x: -float(x.get('_event_salience', 0) or 0))

    # ── Lane B: news corroboration (primary + intensity>=6 + filter) ──
    news_pool: list[dict] = []
    news_file = BASE_DIR / 'data' / 'news' / f'{year}-{month:02d}.json'
    if news_file.exists():
        data = json.loads(news_file.read_text(encoding='utf-8'))
        for a in data.get('articles', []):
            if not a.get('_classified_topics'):
                continue
            if not a.get('is_primary', True):
                continue
            if int(a.get('intensity', 0) or 0) < 6:
                continue
            if not _news_passes_corroboration(a):
                continue
            news_pool.append(a)
    news_pool.sort(
        key=lambda x: (-float(x.get('_event_salience', 0) or 0),
                       -int(x.get('intensity', 0) or 0)),
    )

    # ── Quota 산정 ──
    research_quota = int(round(target_count * RESEARCH_QUOTA))
    news_quota = target_count - research_quota

    high_impact: list[dict] = []
    topic_count: dict[str, int] = {}
    event_count: dict[str, int] = {}
    picked_ids: set[str] = set()
    research_taken_via_bew = 0
    news_taken_via_bew = 0
    bew_windows_consumed: set[str] = set()

    def _guardrails_ok(a: dict) -> bool:
        topic = a.get('primary_topic', '')
        egid = a.get('_event_group_id', '') or ''
        if topic and topic_count.get(topic, 0) >= MAX_PER_TOPIC:
            return False
        if egid and event_count.get(egid, 0) >= MAX_PER_EVENT:
            return False
        return True

    def _commit(a: dict):
        high_impact.append(a)
        aid = a.get('_article_id', '') or ''
        if aid:
            picked_ids.add(aid)
        topic = a.get('primary_topic', '')
        if topic:
            topic_count[topic] = topic_count.get(topic, 0) + 1
        egid = a.get('_event_group_id', '') or ''
        if egid:
            event_count[egid] = event_count.get(egid, 0) + 1

    # ── (BEW) contract 로드 — source-lane 내부 우선순위로만 사용 (option A v2) ──
    bew = _load_bew_contract(year, month)
    bew_used = bew is not None
    bew_pool_size = 0
    bew_nr_ordered: list[dict] = []
    bew_news_ordered: list[dict] = []
    bew_window_of_aid: dict[str, str] = {}
    # forced filter 적용 추적
    forced_set: set[str] = set(force_window_ids) if force_window_ids else set()
    forced_applied = False
    forced_windows_kept = 0
    forced_all_wids: set[str] = set()
    if bew_used:
        nr_index = {a.get('_article_id', ''): a for a in research_pool if a.get('_article_id')}
        news_index = {a.get('_article_id', ''): a for a in news_pool if a.get('_article_id')}
        _windows_raw = bew.get('windows', []) or []
        forced_all_wids = {w.get('window_id', '') for w in _windows_raw if w.get('window_id')}
        if forced_set:
            _windows_filtered = [w for w in _windows_raw
                                 if w.get('window_id', '') in forced_set]
            forced_applied = True
            forced_windows_kept = len(_windows_filtered)
        else:
            _windows_filtered = _windows_raw
        windows_sorted = sorted(
            _windows_filtered,
            key=lambda w: (-float(w.get('confidence', 0) or 0),
                           -abs(float(w.get('zscore', 0) or 0))),
        )
        wid_order = {w.get('window_id', ''): i for i, w in enumerate(windows_sorted)}
        kept_wid_set = set(wid_order.keys())
        cards_by_window: dict[str, list] = {}
        for c in bew.get('evidence_cards', []):
            _wid = c.get('window_id', '')
            if forced_applied and _wid not in kept_wid_set:
                continue
            cards_by_window.setdefault(_wid, []).append(c)
        bew_pool_size = sum(len(v) for v in cards_by_window.values())

        # window 순회로 source별 ordered queue 생성 (dedupe)
        seen_nr: set[str] = set()
        seen_news: set[str] = set()
        for w in windows_sorted:
            wid = w.get('window_id', '')
            for card in cards_by_window.get(wid, []):
                aid = card.get('evidence_id', '')
                if not aid:
                    continue
                src_type = card.get('source_type', '')
                if src_type == 'naver_research':
                    if aid in seen_nr:
                        continue
                    article = nr_index.get(aid)
                    if article is None:
                        continue
                    seen_nr.add(aid)
                    bew_nr_ordered.append(article)
                    bew_window_of_aid.setdefault(aid, wid)
                else:
                    if aid in seen_news:
                        continue
                    article = news_index.get(aid)
                    if article is None:
                        continue
                    seen_news.add(aid)
                    bew_news_ordered.append(article)
                    bew_window_of_aid.setdefault(aid, wid)

    def _commit_bew_aware(a: dict, lane: str):
        """commit + bew 출처면 lane별 카운터 증가."""
        _commit(a)
        aid = a.get('_article_id', '') or ''
        wid = bew_window_of_aid.get(aid)
        if wid is not None:
            bew_windows_consumed.add(wid)
            if lane == 'research':
                nonlocal_research_via_bew[0] += 1
            else:
                nonlocal_news_via_bew[0] += 1

    # nonlocal 우회 (Python 2-style)
    nonlocal_research_via_bew = [0]
    nonlocal_news_via_bew = [0]

    # (a) news quota 내 당일 TIER1/2 slot 우선 (기존 동작 유지)
    today_str = _date.today().isoformat()
    latest_news = [a for a in news_pool if a.get('date', '') == today_str]
    news_taken = 0
    slot_cap = min(LATEST_SLOT, news_quota)
    for a in latest_news:
        if len(high_impact) >= target_count or news_taken >= slot_cap:
            break
        if a.get('_article_id', '') in picked_ids:
            continue
        if not _guardrails_ok(a):
            continue
        _commit_bew_aware(a, 'news')
        news_taken += 1

    # (b) research lane: BEW(nr) 우선 → 기존 research_pool 보충
    research_taken = 0
    for a in bew_nr_ordered:
        if len(high_impact) >= target_count or research_taken >= research_quota:
            break
        if a.get('_article_id', '') in picked_ids:
            continue
        if not _guardrails_ok(a):
            continue
        _commit_bew_aware(a, 'research')
        research_taken += 1
    for a in research_pool:
        if len(high_impact) >= target_count or research_taken >= research_quota:
            break
        if a.get('_article_id', '') in picked_ids:
            continue
        if not _guardrails_ok(a):
            continue
        _commit_bew_aware(a, 'research')
        research_taken += 1

    # (c) news lane: BEW(news) 우선 → 기존 news_pool 보충
    for a in bew_news_ordered:
        if len(high_impact) >= target_count or news_taken >= news_quota:
            break
        if a.get('_article_id', '') in picked_ids:
            continue
        if not _guardrails_ok(a):
            continue
        _commit_bew_aware(a, 'news')
        news_taken += 1
    for a in news_pool:
        if len(high_impact) >= target_count or news_taken >= news_quota:
            break
        if a.get('_article_id', '') in picked_ids:
            continue
        if not _guardrails_ok(a):
            continue
        _commit_bew_aware(a, 'news')
        news_taken += 1

    research_taken_via_bew = nonlocal_research_via_bew[0]
    news_taken_via_bew = nonlocal_news_via_bew[0]

    # (d) 총량 미달 시 상대 lane으로 흡수 (BEW 동일 lane 큐 우선 → 풀 보충)
    if len(high_impact) < target_count:
        for a in bew_nr_ordered:
            if len(high_impact) >= target_count:
                break
            if a.get('_article_id', '') in picked_ids:
                continue
            if not _guardrails_ok(a):
                continue
            _commit_bew_aware(a, 'research')
            research_taken += 1
        for a in research_pool:
            if len(high_impact) >= target_count:
                break
            if a.get('_article_id', '') in picked_ids:
                continue
            if not _guardrails_ok(a):
                continue
            _commit_bew_aware(a, 'research')
            research_taken += 1
    if len(high_impact) < target_count:
        for a in bew_news_ordered:
            if len(high_impact) >= target_count:
                break
            if a.get('_article_id', '') in picked_ids:
                continue
            if not _guardrails_ok(a):
                continue
            _commit_bew_aware(a, 'news')
            news_taken += 1
        for a in news_pool:
            if len(high_impact) >= target_count:
                break
            if a.get('_article_id', '') in picked_ids:
                continue
            if not _guardrails_ok(a):
                continue
            _commit_bew_aware(a, 'news')
            news_taken += 1

    research_taken_via_bew = nonlocal_research_via_bew[0]
    news_taken_via_bew = nonlocal_news_via_bew[0]

    # ── card 렌더 + evidence_ids ──
    evidence_ids: list[str] = []
    card_lines: list[str] = []
    if high_impact:
        n_topics = len({a.get('primary_topic', '') for a in high_impact})
        nr_n = sum(1 for a in high_impact if a.get('source_type') == 'naver_research')
        news_n = len(high_impact) - nr_n
        card_lines.append(
            f'\n주요 뉴스 ({len(high_impact)}건, {n_topics}개 토픽, '
            f'source-aware quota: nr {nr_n} / news {news_n}):'
        )
        for idx, a in enumerate(high_impact, start_idx):
            aid = a.get('_article_id', '') or ''
            topic = a.get('primary_topic', '')
            src = a.get('source', '')
            dt = a.get('date', '')
            title = (a.get('title', '') or '')[:80]
            desc = (a.get('description', '') or '')[:120]
            tag = '[nr]' if a.get('source_type') == 'naver_research' else '[news]'
            card = f'  [ref:{idx}] {tag} {topic} | {dt[:7]} | {src} | {title}'
            if desc:
                card += f'\n    핵심: {desc}'
            card_lines.append(card)
            if aid:
                evidence_ids.append(aid)

    # forced filter evidence 수 집계 (bew lane 에서 실제로 남은 개수)
    forced_evidence_kept = len(bew_nr_ordered) + len(bew_news_ordered) if forced_applied else 0

    debug = {
        'target_count': target_count,
        'research_quota': research_quota,
        'news_quota': news_quota,
        'research_pool_size': len(research_pool),
        'news_pool_size': len(news_pool),
        'research_picked': research_taken,
        'news_picked': news_taken,
        'total_picked': len(high_impact),
        # BEW 우선 채움 추가 통계 (monitor 호환 — 신규 키만 추가)
        'bew_used': bew_used,
        'bew_pool_size': bew_pool_size,
        'bew_picked': research_taken_via_bew + news_taken_via_bew,
        'bew_windows_consumed': len(bew_windows_consumed),
        'bew_research_picked': research_taken_via_bew,
        'bew_news_picked': news_taken_via_bew,
        # forced BEW filter trace (viewer → debate export 경로)
        'bew_forced_applied': forced_applied,
        'bew_forced_window_ids': sorted(forced_set),
        'bew_forced_windows_kept': forced_windows_kept,
        'bew_forced_evidence_kept': forced_evidence_kept,
        'bew_forced_invalid_window_ids': sorted(forced_set - forced_all_wids)
            if forced_set else [],
    }
    _log('evidence_selection', month=f'{year}-{month:02d}', **debug)
    return high_impact, evidence_ids, card_lines, debug


# ===================================================================
# 컨텍스트 빌더
# ===================================================================

def _build_shared_context(year: int, month: int, fund_code: str = None,
                          start_idx: int = 1, target_count: int = 15,
                          *,
                          force_window_ids: set[str] | None = None) -> dict:
    """4인 에이전트 공유 컨텍스트 빌드.

    start_idx: evidence 번호 시작값 (분기 통번호용)
    target_count: 이 달에서 뽑을 뉴스 목표 건수 (분기 debate 시 월별 quota 적용)
    force_window_ids: BEW lane 내부 filter (None=전체)
    """
    context = {
        'year': year,
        'month': month,
        'fund_code': fund_code,
        'bm_text': '',
        'pa_text': '',
        'indicators_text': '',
        'news_summary_text': '',
        'graph_paths_text': '',
        'blog_context_text': '',
    }

    # 뉴스 분류 요약 (dedupe + salience 활용)
    evidence_ids = []  # 프롬프트에 포함된 기사 ID 추적
    news_file = BASE_DIR / 'data' / 'news' / f'{year}-{month:02d}.json'
    if news_file.exists():
        data = json.loads(news_file.read_text(encoding='utf-8'))
        articles = data.get('articles', [])
        classified = [a for a in articles if a.get('_classified_topics')]

        # primary 기사만 사용 (dedup 중복 제거)
        primary_classified = [a for a in classified if a.get('is_primary', True)]

        from collections import Counter
        topic_counts = Counter()
        for a in primary_classified:
            for t in a.get('_classified_topics', []):
                if isinstance(t, dict):
                    topic_counts[t.get('topic', '')] += 1

        lines = [f'뉴스 분류 요약 ({len(primary_classified)}건, 중복제거 후):']
        for topic, count in topic_counts.most_common(10):
            lines.append(f'  {topic}: {count}건')

        # 주요 뉴스: source-aware two-lane selection (research 70% / news 30%)
        high_impact, lane_evidence_ids, card_lines, _sel_debug = \
            _build_evidence_candidates(year, month, target_count, start_idx,
                                       force_window_ids=force_window_ids)
        lines.extend(card_lines)
        evidence_ids.extend(lane_evidence_ids)
        if high_impact:
            context['_next_idx'] = start_idx + len(high_impact)

        # 자산군별 영향 집계 (asset_impact_vector 합산)
        from collections import defaultdict as _dd
        asset_agg = _dd(float)
        for a in primary_classified:
            for k, v in a.get('_asset_impact_vector', {}).items():
                asset_agg[k] += v
        if asset_agg:
            lines.append(f'\n자산군별 뉴스 영향 집계 (MTD):')
            for k, v in sorted(asset_agg.items(), key=lambda x: -abs(x[1]))[:10]:
                sign = '+' if v > 0 else ''
                lines.append(f'  {k}: {sign}{v:.2f}')

        context['news_summary_text'] = '\n'.join(lines)
    context['_evidence_ids'] = evidence_ids

    # GraphRAG 전이경로 (P3 보강 — 포맷 강화 + 밀도 보강 + debug trace)
    graph_trace = {
        'candidate_path_count': 0,
        'selected_path_count': 0,
        'dropped_low_confidence_count': 0,
        'avg_selected_confidence': 0.0,
        'min_selected_confidence': 0.0,
        'max_selected_confidence': 0.0,
        'selected_path_labels': [],
    }
    graph_file = BASE_DIR / 'data' / 'insight_graph' / f'{year}-{month:02d}.json'
    if graph_file.exists():
        graph = json.loads(graph_file.read_text(encoding='utf-8'))
        all_paths = graph.get('transmission_paths', []) or []
        graph_trace['candidate_path_count'] = len(all_paths)
        # confidence 0.3 이상 우선, 부족하면 보조로 채워 최소 6개까지
        confident = [p for p in all_paths if (p.get('confidence') or 0) >= 0.3]
        weak = [p for p in all_paths if 0 < (p.get('confidence') or 0) < 0.3]
        graph_trace['dropped_low_confidence_count'] = len(weak)
        confident.sort(key=lambda p: -(p.get('confidence') or 0))
        weak.sort(key=lambda p: -(p.get('confidence') or 0))
        # 최소 6 ~ 최대 10 개 안정화
        TARGET_MIN, TARGET_MAX = 6, 10
        selected = list(confident[:TARGET_MAX])
        if len(selected) < TARGET_MIN:
            need = TARGET_MIN - len(selected)
            selected.extend(weak[:need])
        if selected:
            confs = [p.get('confidence', 0) or 0 for p in selected]
            graph_trace['selected_path_count'] = len(selected)
            graph_trace['avg_selected_confidence'] = round(sum(confs) / len(confs), 3)
            graph_trace['min_selected_confidence'] = round(min(confs), 3)
            graph_trace['max_selected_confidence'] = round(max(confs), 3)
            lines = [
                '## 주요 인과 경로 (GraphRAG transmission paths)',
                '아래는 본 월의 사건/요인이 자산군에 전파되는 인과 경로 후보입니다. '
                'confidence 가 낮은 경로는 단정 대신 "가능성/리스크"로 기술하세요.',
            ]
            for i, p in enumerate(selected, 1):
                labels = p.get('path_labels') or p.get('path') or []
                conf = p.get('confidence') or 0
                target = p.get('target') or '?'
                trigger = p.get('trigger') or (labels[0] if labels else '?')
                # 노드 라벨을 prose 친화 형태로 (underscore -> 공백)
                pretty = ' → '.join(
                    str(x).replace('_', ' ').replace('·', ' ') for x in labels[:6]
                ) if labels else f'{trigger} → {target}'
                tier = '핵심' if conf >= 0.5 else ('보조' if conf >= 0.3 else '약함')
                lines.append(f'[인과경로 {i} | confidence {conf:.2f} | {tier} | target={target}]')
                lines.append(f'  {pretty}')
                graph_trace['selected_path_labels'].append({
                    'idx': i, 'confidence': round(conf, 3),
                    'tier': tier, 'target': target,
                    'labels': [str(x) for x in labels[:6]],
                })
            context['graph_paths_text'] = '\n'.join(lines)
    context['_graph_trace'] = graph_trace

    # WikiTree retrieval (P3 보강 — stage 별 dir 분리, P0-1+3 2026-05-06)
    # F2 (P1-a, 2026-05-06): fund_comment 시 pinned_fund_context 별도 주입
    wiki_trace = {
        'wiki_candidate_pages': 0,
        'wiki_selected_pages': [],
        'wiki_context_chars': 0,
        'wiki_retrieval_keywords': [],
        'wiki_skipped_short_pages': 0,
        'wiki_skipped_fund_mismatch': 0,
        'wiki_stage_used': None,
        'pinned_fund_context_path': None,
        'pinned_fund_context_chars': 0,
        'pinned_fund_context_reason': None,
        'fund_specific_keywords_added': [],
    }
    try:
        from market_research.report.wiki_retriever import (
            retrieve_wiki_context, format_wiki_context_for_prompt,
            get_pinned_fund_context, format_pinned_fund_context_for_prompt,
            extract_fund_keywords_from_pinned,
        )
        # 키워드 소스: graph path 노드 라벨 + canonical regime tags + 상위 토픽
        kw_sources: list[str] = []
        for entry in graph_trace.get('selected_path_labels') or []:
            kw_sources.extend(entry.get('labels') or [])
        # canonical regime tags
        try:
            from market_research.wiki.canonical import load_canonical_regime
            regime = load_canonical_regime()
            for t in (regime or {}).get('topic_tags') or []:
                kw_sources.append(str(t))
        except Exception:
            pass
        # primary news 상위 토픽 (news block 미실행 시 topic_counts 부재)
        try:
            for t, _ in topic_counts.most_common(5):  # noqa: F821
                if t:
                    kw_sources.append(t)
        except NameError:
            pass
        # P0-1+3: stage 명시 — _market 면 market_debate, 펀드코드면 fund_comment.
        # market_debate stage 는 04_Funds 디렉토리 자체가 allowed 에서 제외됨
        # (시장 causal graph 와 fund-specific commentary graph 분리 — 5/6 commit
        # b6eec0d 의 over-permissive 변경을 stage 게이팅으로 보완).
        # P0-2: period 전달 — 미래 wiki page 제외 (future leakage 방지).
        wiki_stage = (
            'fund_comment' if (fund_code and fund_code != '_market')
            else 'market_debate'
        )
        wiki_period = f'{year}-{month:02d}'

        # F2 (P1-a): fund_comment stage 시 pinned_fund_context 별도 처리.
        # 04_Funds/{period}_{fund_code}.md 를 직접 read 해 prompt 에 별도 섹션
        # 으로 주입 (silent quota 가 아니라 stage contract). 동시에 그 페이지
        # 본문에서 fund-specific 키워드 (자산군/모펀드 코드 등) 추출해 retrieve
        # 키워드 풀에 합쳐 자연스러운 hit 보강.
        pinned: dict = {'text': '', 'page_path': None, 'chars': 0,
                        'reason': 'stage_not_fund_comment'}
        if wiki_stage == 'fund_comment':
            pinned = get_pinned_fund_context(
                fund_code=fund_code, period=wiki_period,
            )
            if pinned.get('text'):
                fund_kws = extract_fund_keywords_from_pinned(pinned, fund_code)
                # 중복 제거 후 추가
                already = {k.lower() for k in kw_sources}
                added = []
                for k in fund_kws:
                    if k.lower() not in already:
                        kw_sources.append(k)
                        already.add(k.lower())
                        added.append(k)
                wiki_trace['fund_specific_keywords_added'] = added
        wiki_trace['pinned_fund_context_path'] = pinned.get('page_path')
        wiki_trace['pinned_fund_context_chars'] = pinned.get('chars', 0)
        wiki_trace['pinned_fund_context_reason'] = pinned.get('reason')

        # F2 follow-up dedup: pinned 가 있으면 retrieved 에서 동일 path 제외 →
        # prompt 중복 주입 방지 (LLM 의 over-anchor 회피).
        excl_paths = {pinned['page_path']} if pinned.get('page_path') else None
        retrieval = retrieve_wiki_context(
            kw_sources,
            stage=wiki_stage,
            fund_code=fund_code,
            period=wiki_period,
            exclude_paths=excl_paths,
        )
        wiki_trace['wiki_candidate_pages'] = retrieval.get('candidate_count', 0)
        wiki_trace['wiki_selected_pages'] = retrieval.get('selected_pages', []) or []
        wiki_trace['wiki_context_chars'] = retrieval.get('context_chars', 0)
        wiki_trace['wiki_skipped_fund_mismatch'] = retrieval.get('skipped_fund_mismatch', 0)
        wiki_trace['wiki_skipped_future_pages'] = retrieval.get('skipped_future_pages', 0)
        wiki_trace['wiki_skipped_cluster_cap'] = retrieval.get('skipped_cluster_cap', 0)
        wiki_trace['wiki_skipped_excluded'] = retrieval.get('skipped_excluded', 0)
        wiki_trace['wiki_stage_used'] = retrieval.get('stage_used')
        wiki_trace['wiki_period_used'] = retrieval.get('period_used')
        wiki_trace['wiki_cluster_cap_used'] = retrieval.get('cluster_cap_used')
        wiki_trace['wiki_retrieval_keywords'] = retrieval.get('keywords', []) or []
        wiki_trace['wiki_skipped_short_pages'] = retrieval.get('skipped_short_pages', 0)
        # F2: pinned 가 먼저 (LLM 입장에서 우선순위 명확화), 그 다음 retrieved
        context['wiki_context_text'] = (
            format_pinned_fund_context_for_prompt(pinned)
            + format_wiki_context_for_prompt(retrieval)
        )
    except Exception as e:
        context['wiki_context_text'] = ''
        print(f'[wiki_retriever] 오류: {e}')
    context['_wiki_trace'] = wiki_trace

    # Blog insight (monygeek 전용)
    try:
        from market_research.analyze.blog_analyst import build_monygeek_context
        context['blog_context_text'] = build_monygeek_context(year, month)
    except Exception:
        pass

    # indicators.csv
    indicators_file = BASE_DIR / 'data' / 'macro' / 'indicators.csv'
    if indicators_file.exists():
        import csv
        with open(indicators_file, encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader, [])
            rows = list(reader)
        if rows:
            latest = rows[-1]
            lines = [f'최신 지표 ({latest[0] if latest else "?"}):']
            for h, v in zip(headers[1:20], latest[1:20]):
                if v:
                    lines.append(f'  {h}: {v}')
            context['indicators_text'] = '\n'.join(lines)

    # 시계열 내러티브 (교차 분석 레이어)
    try:
        from market_research.report.timeseries_narrator import build_debate_narrative
        context['timeseries_narrative_text'] = build_debate_narrative(year, month)
    except Exception as e:
        context['timeseries_narrative_text'] = ''
        print(f"[timeseries_narrator] 오류: {e}")

    # 수치 가드레일용 data_ctx 구축 (indicators.csv 최신 행에서 추출)
    guard_ctx = {}
    if context.get('indicators_text'):
        try:
            bm_returns = {}
            for line in context['indicators_text'].split('\n'):
                line = line.strip()
                if ':' in line:
                    key, val = line.split(':', 1)
                    key = key.strip()
                    val = val.strip()
                    try:
                        bm_returns[key] = float(val)
                    except ValueError:
                        pass
            if bm_returns:
                guard_ctx['bm_returns'] = bm_returns
        except Exception:
            pass
    context['_guard_data_ctx'] = guard_ctx

    # P3-3: Asset coverage guardrail — guard_ctx + timeseries 모두 채워진 시점에 합성
    coverage: dict = {}
    try:
        from market_research.report.asset_coverage import (
            build_asset_coverage_map, format_asset_coverage_for_prompt,
        )
        primary: list[dict] = []
        if news_file.exists():
            try:
                primary = [
                    a for a in (json.loads(news_file.read_text(encoding='utf-8'))
                                .get('articles') or [])
                    if a.get('_classified_topics') and a.get('is_primary', True)
                ]
            except Exception:
                primary = []
        # selected evidence: news block 의 high_impact 후보 (debate 가 실제 선정)
        selected_for_cov = locals().get('high_impact') or []
        coverage = build_asset_coverage_map(
            primary_news=primary,
            graph_paths=graph_trace.get('selected_path_labels') or [],
            wiki_selected_pages=wiki_trace.get('wiki_selected_pages') or [],
            timeseries_narrative_text=context.get('timeseries_narrative_text') or '',
            asset_returns=guard_ctx.get('bm_returns') if isinstance(guard_ctx, dict) else None,
            topic_counts=locals().get('topic_counts'),
            selected_evidence=selected_for_cov,
        )
        context['asset_coverage_text'] = format_asset_coverage_for_prompt(coverage)
    except Exception as e:
        context['asset_coverage_text'] = ''
        print(f'[asset_coverage] 오류: {e}')
    context['_asset_coverage'] = coverage

    return context


def _build_agent_prompt(agent_type: str, context: dict) -> str:
    """에이전트별 프롬프트 생성"""
    shared = (
        f'## {context["year"]}년 {context["month"]}월 시장 분석\n\n'
        f'{context.get("news_summary_text", "(뉴스 데이터 없음)")}\n\n'
        f'{context.get("indicators_text", "(지표 데이터 없음)")}\n\n'
        f'{context.get("timeseries_narrative_text", "")}\n\n'
        f'{context.get("graph_paths_text", "")}\n\n'
        f'{context.get("wiki_context_text", "")}\n\n'
        f'{context.get("asset_coverage_text", "")}\n'
    )

    if agent_type == 'monygeek':
        shared += (
            f'\n## 블로거 분석 프레임워크\n'
            f'{context.get("blog_context_text", "(블로그 데이터 없음)")}\n'
        )

    # P3: 주요 인과 경로 / WikiTree 메모 활용 강제 (소량, JSON 응답 지시 직전에 삽입)
    shared += (
        '\n## 분석 지시 (필수)\n'
        '- 단순한 뉴스 요약을 넘어, 위에 제시된 "주요 인과 경로"와 "관련 WikiTree 메모"를 활용해 '
        '이벤트가 자산군에 전파되는 경로를 해석하세요.\n'
        '- key_points 또는 reasoning 에 최소 1개 이상의 전파경로 (예: "A → B → C" 또는 자연어 인과 chain)를 '
        '명시적으로 언급하세요.\n'
        '- confidence 가 낮은 경로는 "가능성/리스크"로 표현하고, 단정 표현은 피하세요.\n'
    )

    shared += (
        f'\n위 데이터를 바탕으로 {context["year"]}년 {context["month"]}월 시장을 분석하세요.\n\n'
        '응답: 반드시 유효한 JSON 객체 하나만 출력. 설명 텍스트 금지.\n'
        '각 문자열 값 안에 줄바꿈 금지. key_points 최대 5개(각 100자), '
        'tail_risks 최대 3개(각 80자), reasoning 200자 이내.\n\n'
        '{"stance":"bullish|bearish|neutral","key_points":["포인트1","포인트2"],'
        '"risk_assessment":"리스크요약",'
        '"asset_allocation_view":{"국내주식":"비중확대|유지|축소","국내채권":"비중확대|유지|축소",'
        '"해외주식":"비중확대|유지|축소","해외채권":"비중확대|유지|축소"},'
        '"tail_risks":["꼬리리스크1"],"reasoning":"분석근거"}'
    )

    return shared


# ===================================================================
# 에이전트 실행
# ===================================================================

def _run_agent(agent_type: str, context: dict) -> dict:
    """단일 에이전트 실행"""
    persona = AGENT_PERSONAS[agent_type]
    prompt = _build_agent_prompt(agent_type, context)

    try:
        text = _call_llm(
            model=persona['model'],
            system=persona['system_prompt'],
            prompt=prompt,
            max_tokens=1500,
            log_label=f'agent_{agent_type}',
        )
        result = _parse_json_response(text)
        if result:
            result['agent'] = agent_type
            result['agent_name'] = persona['name']
            return result
        else:
            return {
                'agent': agent_type,
                'agent_name': persona['name'],
                'stance': 'neutral',
                'key_points': [f'JSON 파싱 실패: {text[:200]}'],
                'raw_text': text,
            }
    except Exception as exc:
        return {
            'agent': agent_type,
            'agent_name': persona['name'],
            'stance': 'neutral',
            'key_points': [f'에이전트 실행 실패: {exc}'],
            'error': str(exc),
        }


# ===================================================================
# Opus 종합
# ===================================================================

def _synthesize_debate(agent_responses: dict, fund_code: str, context: dict) -> dict:
    """4인 에이전트 결과 -> Opus 2단계 종합 -> 이중 출력"""

    debate_summary = []
    for agent_type, resp in agent_responses.items():
        persona = AGENT_PERSONAS[agent_type]
        stance = resp.get('stance', 'neutral')
        points = resp.get('key_points', [])
        risk = resp.get('risk_assessment', '')
        alloc = resp.get('asset_allocation_view', {})
        tails = resp.get('tail_risks', [])
        reasoning = resp.get('reasoning', '')

        debate_summary.append(
            f'[{persona["name"]}] 스탠스: {stance}\n'
            f'  핵심: {"; ".join(str(p) for p in points[:3])}\n'
            f'  리스크: {risk}\n'
            f'  자산배분: {json.dumps(alloc, ensure_ascii=False)}\n'
            f'  Tail Risk: {"; ".join(str(t) for t in tails) if tails else "없음"}\n'
            f'  근거: {reasoning}'
        )

    debate_text = '\n\n'.join(debate_summary)
    system_msg = (
        '당신은 기관 투자자를 위한 글로벌 매크로 시장 분석 전문가입니다. '
        '응답은 반드시 마침표(.)로 끝나는 완결된 문장으로 마무리하세요. '
        '문장이 미완성된 채로 출력이 끊기지 않도록, 마지막 문단을 자연스럽게 종결한 뒤 응답을 마치세요. '
        '체크포인트를 나열할 때는 항목 수를 사전에 결정해 (예: "셋째,"로 시작했으면 반드시 그 항목까지 마치고 종료) 미완 나열 상태로 끊지 마세요.'
    )

    # ── Step 1: 고객용 매크로 코멘트 (Opus) ──
    # 분기 vs 월별 판단
    is_quarterly = bool(context.get('_quarterly'))
    if is_quarterly:
        months_in_q = context.get('_quarterly_months', [])
        target_period = f'{context["year"]}년 {context.get("_quarter", "")}분기'
        period_instruction = (
            f'이 문서는 "{target_period} 매크로 시장 브리핑"입니다.\n'
            f'반드시 {months_in_q[0]}월부터 {months_in_q[-1]}월까지 시간 순서로 서술하세요.\n'
            '특정 펀드의 운용보고가 아닌, 글로벌/국내 거시환경 분석문입니다.\n'
        )
        structure_instruction = (
            '## 문단 구조 (반드시 시간 순서로 작성)\n'
            f'1문단: {months_in_q[0]}월 — 분기 초 시장 환경, 핵심 이벤트와 자산 반응\n'
            f'2문단: {months_in_q[1]}월 — 전개 심화 또는 전환, 새로운 변수 등장\n'
            f'3문단: {months_in_q[2]}월 — 마감 국면, 분기 말 포지션과 현재 함의\n'
            '4문단: 분기 종합 평가 + 향후 체크포인트 (투자 액션 금지)\n\n'
        )
    else:
        target_period = f'{context["year"]}년 {context["month"]}월'
        period_instruction = (
            f'이 문서는 "{target_period} 매크로 시장 브리핑"입니다.\n'
            f'반드시 "{target_period}" 기준으로 작성하세요. 다른 월을 언급하지 마세요.\n'
            '특정 펀드의 운용보고가 아닌, 글로벌/국내 거시환경 분석문입니다.\n'
        )
        structure_instruction = (
            '## 문단 구조 (반드시 이 순서로 3~4문단 작성)\n'
            '1문단: 월중 핵심 변화 — 시장을 움직인 가장 큰 변수 1~2개, 주요 자산 반응\n'
            '2문단: 안도와 리스크의 공존 — 단기 완화 요인과 중기 구조적 불확실성 균형 서술\n'
            '3문단: 금리/환율/유동성 해석 — 통화정책 딜레마, 금리 구조, 환율 방향성\n'
            '4문단: 향후 체크포인트 — 확인해야 할 변수 나열로 마무리 (투자 액션 금지)\n\n'
        )

    # P3: synthesis 단계에도 graph/wiki context 주입
    graph_block = context.get("graph_paths_text", "") or ""
    wiki_block = context.get("wiki_context_text", "") or ""
    coverage_block = context.get("asset_coverage_text", "") or ""
    comment_prompt = (
        '4명의 분석가가 각각 다른 시각에서 시장을 분석했습니다.\n\n'
        f'## 분석가별 의견\n{debate_text}\n\n'
        f'## 뉴스 evidence\n{context.get("news_summary_text", "")}\n\n'
        + (f'{graph_block}\n\n' if graph_block else '')
        + (f'{wiki_block}\n\n' if wiki_block else '')
        + (f'{coverage_block}\n\n' if coverage_block else '')
        + f'## 문서 성격\n{period_instruction}\n'
        f'{structure_instruction}'
        '## 작성 규칙\n'
        '1. 기관 고객용 전문적이고 절제된 톤, 경어체.\n'
        '2. 크로스 자산 인과관계로 연결 (자산별 개별 나열 금지).\n'
        '3. 숫자 사용 시 반드시 단위와 의미를 명확히 (%, 달러, 원, bp 등).\n'
        '4. 분석가 의견이 상충하면 한쪽을 채택하지 말고 조건부 문장으로 서술.\n'
        '   예: "단기 안도와 중기 불확실성이 병존하는 구도"\n'
        '5. 마지막 문단은 반드시 "향후 관찰 변수"로 끝낼 것. 투자 액션으로 끝내지 말 것.\n'
        '6. (P3) 위에 제시된 "주요 인과 경로"가 있으면, 본문에 최소 1개 이상의 '
        '이벤트 → 지표 → 자산군 연결을 자연어로 반영하세요. 예: "유가 상승이 인플레이션 기대를 '
        '자극하면서 장기금리 부담으로 이어졌고, 이는 성장주 밸류에이션에 압박 요인으로 작용하였습니다." '
        '단, 노골적인 arrow 표기 (A → B)는 피하고 자연스러운 문장으로 풀어 쓰세요. '
        'confidence 가 낮은 경로는 "가능성"/"리스크" 로 표현하세요.\n'
        '7. (P3-3) 핵심 지배 이슈를 중심으로 작성하되, 위 "자산군별 필수 점검" 목록을 활용해 '
        '최소 3개 이상의 주요 자산군 (예: 주식·채권·환율·금/대체) 영향을 자연스럽게 반영하세요. '
        '근거가 약한 자산군은 단정 표현을 피하고 "영향 제한" / "관찰 필요" / "직접 근거 부족" 으로 '
        '짧게만 점검하세요. 중동/지정학 이슈가 지배적이라도 유가→금리→환율→주식→채권→금 등으로 '
        '전파되는 경로를 구분해 한 문단 이상에 분산 배치하세요.\n\n'
        '## 절대 금지: 내부 지표\n'
        '아래는 분석 파이프라인 내부 지표이므로 절대 언급 금지:\n'
        '- 살리언스(salience), 중요도 점수, confidence, 신뢰도 수치\n'
        '- 교차보도 N건, 뉴스 건수, 전이경로 신뢰도\n'
        '- MTD 누적 인덱스 포인트 (+2043, -1341 등 raw number)\n'
        '- 내부 코드명 (F_USDKRW, DXY 코드 등은 "달러인덱스", "달러/원 선물환"으로 풀어쓸 것)\n\n'
        '## 절대 금지: 개별 펀드 운용 문장\n'
        '이 문서는 시장 해설이므로, 특정 펀드/당사의 실행 판단을 서술하면 안 됩니다.\n'
        '금지 예시:\n'
        '- "당사는 비중을 확대한다"\n'
        '- "본 펀드는 듀레이션을 축소한다"\n'
        '- "헤지 수단을 병행할 방침이다"\n'
        '- "유동성 버퍼를 확보해 나간다"\n'
        '- "BM 대비 초과수익을 추구한다"\n'
        '- "포트폴리오 운용 전략으로는 ~"\n'
        '- "편입 비중을 조정한다"\n\n'
        '허용 예시 (시장 현상 설명):\n'
        '- "듀레이션 부담이 커지고 있다"\n'
        '- "환 헤지 수요가 증가하는 추세"\n'
        '- "에너지 비중 확대에 대한 시장 기대"\n'
        '- "유동성 버퍼가 약화되고 있다"\n'
        '- "포트폴리오 리밸런싱 수요가 관측된다"\n\n'
        '## 좋은 코멘트 예시 (구조와 톤만 참고, 내용은 현재 월 데이터로 작성)\n'
        '> 4월 글로벌 시장은 미국-이란 간 2주 휴전 합의를 계기로 지정학적 리스크 프리미엄이 '
        '빠르게 완화되는 흐름을 보였습니다. 주요국 증시는 일제히 반등하여 미국 성장주와 해외 '
        '주식시장이 월중 뚜렷한 회복세를 기록하였고, KOSPI는 +14.4%, KOSPI200은 +16.3% 상승하며 '
        '국내 시장도 강한 안도 랠리를 보였습니다[ref:2].\n\n'
        '위 예시의 특징: 내부 지표 없음, 펀드 액션 없음, 수치에 단위와 맥락 포함, ref 태그 정확.\n'
        '이 구조를 따르되 반드시 현재 월의 실제 데이터와 분석가 의견으로 작성하세요.\n\n'
        '## 필수: 출처 태그\n'
        '뉴스에서 가져온 사실을 언급할 때 해당 문장 끝에 [ref:N] 태그를 붙이세요.\n'
        '위 "주요 뉴스" 목록에 [ref:1], [ref:2], ... 식별자가 이미 붙어 있습니다.\n'
        '해당 식별자를 그대로 복사하세요. 번호를 재해석하거나 임의 부여하지 마세요.\n'
        '목록에 없는 ref 번호를 만들지 마세요.\n'
        '기사에서 직접 확인 가능한 사실(수치, 이벤트, 발언)을 서술할 때 반드시 ref를 붙이세요.\n'
        '수치가 포함된 사실 서술(%, 달러, 원, 포인트 등)에는 가급적 해당 ref를 명시하세요.\n'
        '특정 1~2개 토픽에만 ref가 몰리지 않도록, 다양한 토픽의 evidence를 활용하세요.\n'
        '위 뉴스 evidence 목록에서 각 토픽의 핵심 기사를 최소 1건씩 인용하는 것을 목표로 하세요.\n\n'
        '순수 텍스트만 출력하세요.\n'
        '문단 사이에 반드시 빈 줄(\\n\\n)을 넣어 구분하세요.'
    )

    customer_comment = ''
    # 글자수 제한 사실상 무제한 (Opus output cap 까지 허용).
    # 본 코멘트가 잘리면 펀드 fan-out 컨텍스트로 전파되어 펀드 코멘트 표현이 오염됨 (관측 사례:
    # 2026-04 _market 의 "인플레이션 전망 수정 폭" 미완 종료 → 4JM12 펀드 코멘트가 동일 어구 인용).
    # 분기 32K / 월별 16K 로 상향. 자연 종료(마침표)는 system message 에서 강제.
    comment_max_tokens = 32000 if is_quarterly else 16000
    try:
        customer_comment = _call_llm(
            model='claude-opus-4-6',
            system=system_msg,
            prompt=comment_prompt,
            max_tokens=comment_max_tokens,
            log_label='synthesis_step1_comment',
        )
    except Exception as exc:
        customer_comment = f'코멘트 생성 실패: {exc}'

    # ── 수치 가드레일 ──
    guard_issues = []
    guard_data_ctx = context.get('_guard_data_ctx', {})
    if guard_data_ctx and customer_comment and not customer_comment.startswith('코멘트 생성 실패'):
        try:
            from market_research.report.numeric_guard import check_comment_numbers, format_guard_report
            guard_issues = check_comment_numbers(customer_comment, guard_data_ctx)
            if guard_issues:
                print(f'  [가드레일] {format_guard_report(guard_issues)}')
        except Exception as exc:
            print(f'  [가드레일] 검증 실패: {exc}')

    # ── Step 2: 합의/쟁점/Tail Risk 분석 (Opus) ──
    analysis_prompt = (
        '4명의 분석가 의견을 분석하여 합의점과 쟁점을 추출하세요.\n\n'
        f'## 분석가별 의견\n{debate_text}\n\n'
        '반드시 유효한 JSON 객체 하나만 출력. 설명 텍스트 금지.\n'
        '각 문자열 값 안에 줄바꿈 금지.\n\n'
        '{"consensus_points":["4인 합의 포인트1","합의2","합의3"],'
        '"disagreements":[{"topic":"쟁점주제","bull":"Bull입장 한줄","bear":"Bear입장 한줄",'
        '"quant":"Quant입장 한줄","monygeek":"monygeek입장 한줄"}],'
        '"tail_risks":["Tail Risk 1","Tail Risk 2"],'
        '"admin_summary":"Admin용 전체 쟁점 요약 2-3문장"}'
    )

    analysis = {}
    try:
        text = _call_llm(
            model='claude-opus-4-6',
            system=system_msg,
            prompt=analysis_prompt,
            max_tokens=2500,
            log_label='synthesis_step2_analysis',
        )
        analysis = _parse_json_response(text) or {}
        if not analysis:
            print(f'  [Step 2] JSON 파싱 실패. Raw 앞 300자: {text[:300]}')
        else:
            print(f'  [Step 2] 합의 {len(analysis.get("consensus_points",[]))}개, '
                  f'쟁점 {len(analysis.get("disagreements",[]))}개')
    except Exception as exc:
        print(f'  [Step 2] 실패: {exc}')
        analysis = {'error': str(exc)}

    return {
        'customer_comment': customer_comment,
        'consensus_points': analysis.get('consensus_points', []),
        'disagreements': analysis.get('disagreements', []),
        'tail_risks': analysis.get('tail_risks', []),
        'admin_summary': analysis.get('admin_summary', ''),
        '_guard_issues': guard_issues,
    }


# ===================================================================
# Regime Memory
# ===================================================================

def _load_regime_memory() -> dict:
    if REGIME_FILE.exists():
        return json.loads(REGIME_FILE.read_text(encoding='utf-8'))
    return {
        'current': {'dominant_narrative': '', 'weeks': 0, 'since': ''},
        'previous': {'dominant_narrative': '', 'ended': ''},
        'shift_detected': False,
        'shift_description': '',
        'history': [],
    }


def _summarize_debate_narrative(agent_responses: dict) -> dict:
    """에이전트 합의에서 Haiku로 debate 시점의 해석 narrative를 생성.

    **regime_memory.json을 수정하지 않음.** canonical regime 확정은
    `daily_update.py::_step_regime_check` 만 수행한다. 여기서는 debate의
    interpretation만 반환하고, 호출자는 이를 06_Debate_Memory/ wiki 페이지로
    저장해야 한다.

    Returns
    -------
    dict with keys:
      - debate_narrative: str (이번 debate의 해석)
      - canonical_snapshot: dict (debate 시점 canonical regime 복사본, 읽기 전용)
      - diverges_from_canonical: bool
    """
    canonical = _load_regime_memory()
    canonical_current = canonical.get('current', {})
    canonical_narr = canonical_current.get('dominant_narrative', '')

    all_points = []
    for agent, resp in agent_responses.items():
        name = AGENT_PERSONAS.get(agent, {}).get('name', agent)
        points = resp.get('key_points', [])
        if points:
            all_points.append(f'[{name}] {"; ".join(str(p) for p in points[:3])}')

    new_narrative = '데이터 부족'
    if all_points:
        try:
            prompt = (
                '다음은 4명의 시장 분석가가 제시한 핵심 포인트입니다.\n\n'
                + '\n'.join(all_points) + '\n\n'
                '이 분석들을 종합하여, 현재 시장을 지배하는 핵심 내러티브를 '
                '한 문장(20자 이내)으로 요약하세요.\n'
                '예: "이란 사태 + 유가 급등", "AI 투자 확대 + 달러 강세"\n\n'
                '한 문장만 응답:'
            )
            new_narrative = _call_llm(
                'claude-haiku-4-5-20251001', '', prompt, max_tokens=50,
                log_label='debate_narrative',
            ).strip('"\'').strip()
        except Exception:
            new_narrative = '분석 중'

    _current_snap = {
        'dominant_narrative': canonical_narr,
        'narrative_description': canonical_current.get('narrative_description', ''),
        'topic_tags': canonical_current.get('topic_tags', []),
        'since': canonical_current.get('since', ''),
        'direction': canonical_current.get('direction', 'neutral'),
        'weeks': canonical_current.get('weeks', 0),
    }
    return {
        'debate_narrative': new_narrative,
        # backward-compat: nested (current.*) + flat (최상위) 양쪽 제공.
        # 구 소비자가 `canonical_snapshot['dominant_narrative']` 로 직접 접근해도
        # KeyError 안 나도록 방어.
        'canonical_snapshot': {
            'current': _current_snap,
            **_current_snap,
        },
        'diverges_from_canonical': bool(canonical_narr and new_narrative != canonical_narr),
    }


# ===================================================================
# 메인: Debate 실행
# ===================================================================

def run_market_debate(year: int, month: int,
                      *,
                      force_window_ids: set[str] | None = None) -> dict:
    """
    시장 전체 debate (월 1회, 펀드 무관).
    4인 에이전트 병렬 실행 -> Opus 2단계 종합 -> 자산군별 분석 결과.
    펀드별 캐시에서는 이 결과를 참조하여 보유 비중에 맞는 코멘트만 사용.

    force_window_ids: BEW viewer 에서 선택된 window_id set (None=전체 BEW 사용).
    """
    print(f'\n-- Market Debate: {year}-{month:02d} --')
    if force_window_ids:
        print(f'  [forced BEW] {len(force_window_ids)}개 window_id 만 evidence lane 에 허용')

    context = _build_shared_context(year, month, force_window_ids=force_window_ids)
    print(f'  컨텍스트 빌드 완료')

    # 4인 에이전트 병렬 실행
    print(f'  4인 에이전트 실행 중...')
    agent_responses = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            agent: pool.submit(_run_agent, agent, context)
            for agent in AGENT_PERSONAS
        }
        for agent, future in futures.items():
            try:
                agent_responses[agent] = future.result(timeout=60)
                stance = agent_responses[agent].get('stance', '?')
                print(f'    {AGENT_PERSONAS[agent]["name"]}: {stance}')
            except Exception as exc:
                agent_responses[agent] = {
                    'agent': agent,
                    'stance': 'error',
                    'key_points': [str(exc)],
                }
                print(f'    {AGENT_PERSONAS[agent]["name"]}: 실패 - {exc}')

    # Debate 해석 narrative (canonical regime 덮어쓰지 않음 — 읽기만)
    debate_interp = _summarize_debate_narrative(agent_responses)
    if debate_interp.get('diverges_from_canonical'):
        print(f'  debate 해석: {debate_interp["debate_narrative"]} '
              f'(canonical `{debate_interp["canonical_snapshot"].get("current", {}).get("dominant_narrative", "")}`와 상이)')
    else:
        print(f'  debate 해석: {debate_interp["debate_narrative"]}')

    # Opus 종합 (시장 전체)
    print(f'  Opus 종합 중...')
    synthesis = _synthesize_debate(agent_responses, None, context)
    print(f'  종합 완료')

    # P3: graph/wiki retrieval debug trace (admin/debug 전용 — client DTO 미포함)
    graph_trace = context.get('_graph_trace') or {}
    wiki_trace = context.get('_wiki_trace') or {}
    coverage = context.get('_asset_coverage') or {}
    final_comment_text = (synthesis.get('customer_comment') if isinstance(synthesis, dict) else '') or ''
    # final_comment 에 자산군 키워드가 등장하는지 카운트 (P3-3 검증)
    from market_research.report.asset_coverage import (
        REQUIRED_ASSET_CLASSES as _REQ, _scan_text_for_asset as _scan,
    )
    asset_mentions: dict[str, int] = {
        ac: _scan(final_comment_text, ac) for ac in _REQ
    }
    asset_pass = sum(1 for v in asset_mentions.values() if v > 0) >= 3

    debug_trace = {
        'graph_paths_used_count': graph_trace.get('selected_path_count', 0),
        'graph_paths_used': graph_trace.get('selected_path_labels', []),
        'graph_paths_candidate_count': graph_trace.get('candidate_path_count', 0),
        'graph_paths_dropped_low_confidence': graph_trace.get(
            'dropped_low_confidence_count', 0),
        'graph_paths_avg_confidence': graph_trace.get('avg_selected_confidence', 0.0),
        'wiki_context_used_count': wiki_trace.get('wiki_selected_pages')
            and len(wiki_trace['wiki_selected_pages']) or 0,
        'wiki_context_pages': wiki_trace.get('wiki_selected_pages', []),
        'wiki_context_chars': wiki_trace.get('wiki_context_chars', 0),
        'wiki_retrieval_keywords': wiki_trace.get('wiki_retrieval_keywords', []),
        'wiki_skipped_short_pages': wiki_trace.get('wiki_skipped_short_pages', 0),
        'prompt_graph_context_chars': len(context.get('graph_paths_text') or ''),
        'prompt_wiki_context_chars': len(context.get('wiki_context_text') or ''),
        # P3-3 asset coverage
        'dominant_topic': coverage.get('dominant_topic'),
        'dominant_topic_share': coverage.get('dominant_topic_share', 0.0),
        'asset_coverage_map': coverage.get('asset_coverage_map', []),
        'covered_asset_classes': coverage.get('covered_asset_classes', []),
        'weak_asset_classes': coverage.get('weak_asset_classes', []),
        'missing_asset_classes': coverage.get('missing_asset_classes', []),
        'fallback_used_by_asset': coverage.get('fallback_used_by_asset', {}),
        'prompt_asset_coverage_chars': len(context.get('asset_coverage_text') or ''),
        'final_comment_asset_mentions': asset_mentions,
        'asset_coverage_pass': asset_pass,
    }

    result = {
        'year': year,
        'month': month,
        'debate_run_id': uuid.uuid4().hex,  # P1-① lineage ID (run당 1회 발급)
        'debated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'agents': agent_responses,
        'synthesis': synthesis,
        'debate_narrative': debate_interp,
        '_evidence_ids': context.get('_evidence_ids', []),
        '_debug_trace': debug_trace,  # admin/debug 전용 — client DTO 에 미노출
    }

    # ── 디버그 로그 저장 ──
    log_file = DEBATE_LOG_DIR / f'{year}-{month:02d}.json'
    log_payload = {
        'debated_at': result['debated_at'],
        'result': result,
        'llm_calls': _debug_log.copy(),
    }
    try:
        log_file.write_text(
            json.dumps(log_payload, ensure_ascii=False, indent=2, default=str),
            encoding='utf-8',
        )
        print(f'  로그 저장: {log_file}')
    except Exception as exc:
        print(f'  [경고] 로그 저장 실패: {exc}')
    _debug_log.clear()

    return result


# 하위 호환 alias
def run_debate(fund_code: str, year: int, month: int) -> dict:
    """하위 호환 — run_market_debate 래퍼"""
    result = run_market_debate(year, month)
    result['fund_code'] = fund_code
    return result


def run_quarterly_debate(year: int, quarter: int,
                         *,
                         force_window_ids: set[str] | None = None) -> dict:
    """
    분기 통합 debate.
    해당 분기 3개월의 뉴스/지표를 종합하여 debate 실행.

    force_window_ids: BEW viewer 에서 선택된 window_id set. 3개월 컨텍스트 각각에
    동일 set 이 전달되며, 월과 실제로 매칭되는 wid 만 해당 월 BEW lane 에 적용된다
    (다른 월의 contract 에는 매칭 안 되므로 자연스럽게 무효화 됨).
    """
    months = [(quarter - 1) * 3 + i for i in range(1, 4)]
    print(f'\n-- Quarterly Debate: {year}Q{quarter} ({months[0]}~{months[2]}월) --')
    if force_window_ids:
        print(f'  [forced BEW] {len(force_window_ids)}개 window_id 만 evidence lane 에 허용')

    # 3개월 컨텍스트 병합
    merged_context = {
        'year': year,
        'month': months[-1],  # 마지막 달 기준
        'fund_code': None,
        'indicators_text': '',
        'news_summary_text': '',
        'graph_paths_text': '',
        'blog_context_text': '',
        '_evidence_ids': [],
    }

    all_news_lines = []
    all_graph_lines = []
    all_blog_lines = []
    all_evidence_ids = []
    next_idx = 1  # 분기 통번호

    # 월별 최소 quota: 각 월 최소 5건, 나머지는 자유 배분 (총 ~15~20건)
    MONTHLY_QUOTA = 5
    for m in months:
        ctx = _build_shared_context(year, m, start_idx=next_idx, target_count=MONTHLY_QUOTA,
                                    force_window_ids=force_window_ids)
        next_idx = ctx.get('_next_idx', next_idx)
        if ctx.get('indicators_text') and not merged_context['indicators_text']:
            merged_context['indicators_text'] = ctx['indicators_text']
        if ctx.get('news_summary_text'):
            all_news_lines.append(f'--- {year}-{m:02d} ---')
            all_news_lines.append(ctx['news_summary_text'])
        if ctx.get('graph_paths_text'):
            all_graph_lines.append(ctx['graph_paths_text'])
        if ctx.get('blog_context_text'):
            all_blog_lines.append(ctx['blog_context_text'])
        all_evidence_ids.extend(ctx.get('_evidence_ids', []))

    merged_context['indicators_text'] = merged_context['indicators_text']
    merged_context['news_summary_text'] = '\n'.join(all_news_lines)
    merged_context['graph_paths_text'] = '\n'.join(all_graph_lines)
    merged_context['blog_context_text'] = '\n'.join(all_blog_lines)
    merged_context['_evidence_ids'] = all_evidence_ids
    merged_context['_quarterly'] = True
    merged_context['_quarter'] = quarter
    merged_context['_quarterly_months'] = months

    print(f'  컨텍스트 빌드 완료 (3개월 병합)')

    # 4인 에이전트
    print(f'  4인 에이전트 실행 중...')
    agent_responses = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            agent: pool.submit(_run_agent, agent, merged_context)
            for agent in AGENT_PERSONAS
        }
        for agent, future in futures.items():
            try:
                agent_responses[agent] = future.result(timeout=60)
                stance = agent_responses[agent].get('stance', '?')
                print(f'    {AGENT_PERSONAS[agent]["name"]}: {stance}')
            except Exception as exc:
                agent_responses[agent] = {
                    'agent': agent, 'stance': 'error',
                    'key_points': [str(exc)],
                }
                print(f'    {AGENT_PERSONAS[agent]["name"]}: 실패 - {exc}')

    debate_interp = _summarize_debate_narrative(agent_responses)
    if debate_interp.get('diverges_from_canonical'):
        print(f'  debate 해석: {debate_interp["debate_narrative"]} '
              f'(canonical `{debate_interp["canonical_snapshot"].get("current", {}).get("dominant_narrative", "")}`와 상이)')
    else:
        print(f'  debate 해석: {debate_interp["debate_narrative"]}')

    print(f'  Opus 종합 중...')
    synthesis = _synthesize_debate(agent_responses, None, merged_context)
    print(f'  종합 완료')

    result = {
        'year': year,
        'quarter': quarter,
        'months': months,
        'debate_run_id': uuid.uuid4().hex,  # P1-① lineage ID (run당 1회 발급)
        'debated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'agents': agent_responses,
        'synthesis': synthesis,
        'debate_narrative': debate_interp,
        '_evidence_ids': all_evidence_ids,
    }

    log_file = DEBATE_LOG_DIR / f'{year}-Q{quarter}.json'
    try:
        log_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding='utf-8',
        )
        print(f'  로그 저장: {log_file}')
    except Exception as exc:
        print(f'  [경고] 로그 저장 실패: {exc}')

    return result


# ===================================================================
# CLI
# ===================================================================

if __name__ == '__main__':
    if len(sys.argv) >= 4:
        fc = sys.argv[1]
        y = int(sys.argv[2])
        m = int(sys.argv[3])
    else:
        fc = '08N81'
        from datetime import datetime
        now = datetime.now()
        y, m = now.year, now.month

    result = run_debate(fc, y, m)

    print(f'\n=== Debate 결과: {fc} {y}-{m:02d} ===')
    for agent, resp in result['agents'].items():
        print(f'  {agent}: {resp.get("stance", "?")}')
    syn = result.get('synthesis', {})
    comment = syn.get('customer_comment', '')
    print(f'\n=== 고객용 코멘트 (앞 500자) ===')
    print(comment[:500])
    print(f'\n=== 합의점 ===')
    for cp in syn.get('consensus_points', []):
        print(f'  - {cp}')
    print(f'\n=== 쟁점 ===')
    for d in syn.get('disagreements', []):
        if isinstance(d, dict):
            print(f'  [{d.get("topic", "?")}]')
        else:
            print(f'  {d}')
