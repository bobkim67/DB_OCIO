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

from market_research.report.debate_context_policy import (
    DebateContextPolicy, LEGACY_POLICY, resolve_policy,
    summarize_prompt_sections, active_sections, validate_research_only_clean,
)

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
        'model': 'claude-opus-4-8',
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
        'model': 'claude-opus-4-8',
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
        'model': 'claude-opus-4-8',
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
        'model': 'claude-opus-4-8',
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
              log_label: str = '',
              *, stream: bool = False) -> str:
    """Anthropic Messages API wrapper.

    R9-B.4.1 hotfix — ``stream=True`` 사용 시 ``messages.stream()`` 으로
    누적 응답을 만든 후 동일 ``text`` 문자열을 반환한다. non-streaming
    Opus 호출이 10분 한계를 초과하는 quarterly synthesis 회귀를 해결.
    default ``stream=False`` 는 기존 ``messages.create()`` 동작 그대로
    (binary-identical 행동). 토큰/cost 로깅 schema 도 동일.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=_get_api_key())
    if not stream:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = response.content[0].text.strip()
        usage = response.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
    else:
        # streaming: 청크를 누적해 동일한 text 를 만든다. final message 에서
        # usage 를 가져와 기존 로깅 schema 그대로 유지.
        parts: list[str] = []
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{'role': 'user', 'content': prompt}],
        ) as s:
            for chunk in s.text_stream:
                parts.append(chunk)
            final_message = s.get_final_message()
        text = ''.join(parts).strip()
        usage = final_message.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
    _log('llm_call', label=log_label, model=model, max_tokens=max_tokens,
         input_tokens=input_tokens, output_tokens=output_tokens,
         stream=bool(stream),
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


def _months_in_range(start_iso: str, end_iso: str) -> list[str]:
    """'YYYY-MM-DD' 범위가 걸치는 'YYYY-MM' 목록 (오름차순). 윈도우드 debate 용."""
    y, m = int(start_iso[:4]), int(start_iso[5:7])
    ey, em = int(end_iso[:4]), int(end_iso[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append(f'{y}-{m:02d}')
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _build_evidence_candidates(year: int, month: int, target_count: int,
                               start_idx: int,
                               *,
                               force_window_ids: set[str] | None = None,
                               policy: DebateContextPolicy = LEGACY_POLICY,
                               window: tuple[str, str] | None = None,
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

    # 윈도우드 debate: window=(start,end) 지정 시 evidence 를 그 날짜창으로 필터.
    # 창이 월경계를 넘으면 걸치는 모든 월의 adapted 를 로드. 미지정 시 당월(MTD) 그대로.
    _win_months = (_months_in_range(window[0], window[1]) if window
                   else [f'{year}-{month:02d}'])

    def _in_window(a: dict) -> bool:
        if not window:
            return True
        d = a.get('date') or ''
        return window[0] <= d <= window[1]

    # ── Lane A: research primary (is_primary + classified + TIER1/2) ──
    research_pool: list[dict] = []
    try:
        from market_research.collect.naver_research_adapter import load_adapted
        adapted = []
        for _m in _win_months:
            adapted.extend(load_adapted(_m))
        for a in adapted:
            if not a.get('_classified_topics'):
                continue
            if not a.get('is_primary', True):
                continue
            band = a.get('_research_quality_band', '')
            if band not in ('TIER1', 'TIER2'):
                continue
            if not _in_window(a):
                continue
            research_pool.append(a)
    except Exception:
        research_pool = []
    # salience 내림차순, 동점이면 최신 날짜 우선(tie-breaker). salience 가 상위에서
    # 포화(동점 다수)되면 기존엔 파일순서(≈이른 날짜)가 tie 를 이겨 late-month 가 top-N
    # 에서 배제됐다 — "같은 중요도면 더 최신 evidence 우선"으로 시간편향 해소. (2026-07-01)
    research_pool.sort(key=lambda x: (float(x.get('_event_salience', 0) or 0),
                                      x.get('date', '')), reverse=True)

    # ── Lane B: news corroboration (primary + intensity>=6 + filter) ──
    # policy.news_evidence_lane_enabled=False (research-only) 면 news lane 전면 차단
    # → research_pool 만으로 evidence 구성.
    news_pool: list[dict] = []
    if policy.news_evidence_lane_enabled:
        _news_articles = []
        for _m in _win_months:
            _nf = BASE_DIR / 'data' / 'news' / f'{_m}.json'
            if _nf.exists():
                _news_articles.extend(
                    json.loads(_nf.read_text(encoding='utf-8')).get('articles', []))
        for a in _news_articles:
            if not a.get('_classified_topics'):
                continue
            if not a.get('is_primary', True):
                continue
            if int(a.get('intensity', 0) or 0) < 6:
                continue
            if not _news_passes_corroboration(a):
                continue
            if not _in_window(a):
                continue
            news_pool.append(a)
    news_pool.sort(
        key=lambda x: (-float(x.get('_event_salience', 0) or 0),
                       -int(x.get('intensity', 0) or 0)),
    )

    # ── Quota 산정 (policy 기반) ──
    research_quota = int(round(target_count * policy.research_quota))
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
        if topic and topic_count.get(topic, 0) >= policy.max_per_topic:
            return False
        if egid and event_count.get(egid, 0) >= policy.max_per_event:
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

    # (b) research lane: research_pool(salience 공정순, 동점=최신우선) 우선 → BEW(nr) 보충.
    # BEW 는 anomaly(이상변동일) 기반이라 salience 의 bm_overlap 과 동일한 시간편향 계열 —
    # BEW 우선이면 anomaly 가 몰린 시기(예: 월전반)로 evidence 가 쏠려 late-month 배제.
    # salience 공정화(bm_overlap 제거)와 일관되게 research_pool 을 우선으로. (2026-07-01)
    research_taken = 0
    for a in research_pool:
        if len(high_impact) >= target_count or research_taken >= research_quota:
            break
        if a.get('_article_id', '') in picked_ids:
            continue
        if not _guardrails_ok(a):
            continue
        _commit_bew_aware(a, 'research')
        research_taken += 1
    for a in bew_nr_ordered:
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
        for a in research_pool:
            if len(high_impact) >= target_count:
                break
            if a.get('_article_id', '') in picked_ids:
                continue
            if not _guardrails_ok(a):
                continue
            _commit_bew_aware(a, 'research')
            research_taken += 1
        for a in bew_nr_ordered:
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

# 09_Research_Synthesis 섹션 (research_consensus.build_research_synthesis_page):
#   §1 컨센서스(broker) / §2 이견(monygeek dissent) / §3 리스크 / §4 broker claim / §5 monygeek 관점
# Phase 2.7: 08_Claims(뉴스) 제외 → 원자 claim 은 09 §4 에서 직접 공급.
# Phase 2.7.1: **monygeek 분리** — monygeek 블로그 견해(§2 이견 / §5 monygeek 관점)는 shared
#   debate 컨텍스트에서 제외. monygeek 은 monygeek **persona** 의 blog_context_text 로만 사용.
#   shared 09 = broker 만: §1 컨센서스 + §3 리스크 + §4 broker claim.
#   (§3 리스크는 전체 claim risk_factor 익명 집계 → 일부 monygeek 출처 잔존하나 견해 아닌 risk fact.)
_SYNTH_PRIMARY_PREFIXES = ('## 1.', '## 3.')   # §2(monygeek dissent) 제외
_SYNTH_CLAIM_PREFIXES = ('## 4.',)             # §5(monygeek 관점) 제외


def _parse_synth_page(text: str) -> tuple[dict, str]:
    """09 페이지 → (frontmatter dict, body). 포맷 변동에 robust (best-effort)."""
    fm: dict = {}
    body = text
    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            for ln in parts[1].splitlines():
                if ':' in ln:
                    k, v = ln.split(':', 1)
                    fm[k.strip()] = v.strip()
            body = parts[2]
    return fm, body.strip()


def _extract_synth_sections(body: str, char_cap: int) -> str:
    """body 에서 §1~§3 (컨센서스/이견/리스크) synthesis prose 만 발췌. fallback=앞부분."""
    lines = body.splitlines()
    kept: list[str] = []
    keep = False
    for ln in lines:
        st = ln.strip()
        if st.startswith('## '):
            keep = st.startswith(_SYNTH_PRIMARY_PREFIXES)  # 그 외(§4/§5/미지) 제외
        if keep and st and not st.startswith('# '):
            kept.append(ln)
    out = '\n'.join(kept).strip()
    if not out:                      # 헤더 패턴 불일치 → 본문 앞부분 fallback
        out = body[:char_cap].strip()
    return out[:char_cap].strip()


def _extract_synth_claims(body: str, char_cap: int) -> str:
    """body 에서 §4(broker)/§5(monygeek) 원자 claim bullet 만 발췌 (Phase 2.7).

    08_Claims(뉴스 트랙) 제외에 따라 research-only debate 의 원자 claim 레이어를 09 에서
    공급. claim bullet(`- [claim:..]`) 줄만 모아 char_cap 까지. 없으면 빈 문자열.
    """
    lines = body.splitlines()
    kept: list[str] = []
    in_claim = False
    for ln in lines:
        st = ln.strip()
        if st.startswith('## '):
            in_claim = st.startswith(_SYNTH_CLAIM_PREFIXES)
            if in_claim:
                kept.append(ln)        # §4/§5 헤더 유지(broker vs monygeek 구분)
            continue
        if in_claim and st.startswith('- '):
            kept.append(ln)
    out = '\n'.join(kept).strip()
    return out[:char_cap].strip()


def build_research_synthesis_context(year: int, month: int,
                                     policy: "DebateContextPolicy | None" = None,
                                     asset_scope: list[str] | None = None,
                                     trace: dict | None = None) -> str:
    """09_Research_Synthesis 정식 context builder (Phase 2 — 1급 소스 승격).

    naver_research 분해→재종합 결과를 debate 의 **primary synthesis** 로 주입한다.
    자산군별 §1 컨센서스(base view) + §2 이견(dissent/tail-risk) + §3 리스크 만 발췌
    (§4/§5 claim 리스트는 08_Claims 중복 → 제외). 100% research claim 계보라 news/graph
    누수 없음. 파일 없거나 비면 fail 하지 않고 trace 에 기록.

    asset_scope: 특정 자산군만 (None=전체). trace: 채워줄 dict(source/selected/chars).
    """
    if policy is None:
        policy = LEGACY_POLICY
    period = f'{year}-{month:02d}'
    try:
        from market_research.wiki.paths import RESEARCH_SYNTHESIS_DIR
        synth_dir = RESEARCH_SYNTHESIS_DIR
    except Exception:
        synth_dir = BASE_DIR / 'data' / 'wiki' / '09_Research_Synthesis'
    tr = trace if trace is not None else {}
    tr.update({'period': period, 'dir': str(synth_dir),
               'selected_files': [], 'selected_assets': [], 'total_chars': 0})
    pages = sorted(synth_dir.glob(f'{period}_*.md')) if synth_dir.exists() else []
    if asset_scope:
        scope = set(asset_scope)
        pages = [p for p in pages if p.stem.split('_', 1)[-1] in scope]
    if not pages:
        tr['status'] = 'missing'
        _log('research_synthesis_missing', period=period,
             dir=str(synth_dir), exists=synth_dir.exists())
        return ''
    blocks = [f'## 09 Research Synthesis — naver_research 재종합 ({period})',
              '아래는 증권사 리서치 claim 을 자산군별로 재종합한 base view / 이견 / 리스크입니다 '
              '(news·graph 미포함, primary synthesis source).']
    for fp in pages[:policy.research_synthesis_max_assets]:
        try:
            fm, body = _parse_synth_page(fp.read_text(encoding='utf-8'))
        except Exception:
            continue
        asset = fm.get('asset_class') or fp.stem.split('_', 1)[-1]
        stance = fm.get('consensus_stance')
        strength = fm.get('consensus_strength')
        nclaims = fm.get('n_claims')
        head = f'### {asset}'
        if stance:
            head += f' — consensus={stance}'
            if strength:
                head += f' (strength {strength})'
        if nclaims:
            # broker/monygeek 내역 제외 — 총계만 (monygeek 토큰 노출 방지)
            head += f' | n_claims={str(nclaims).split("(")[0].strip()}'
        section = _extract_synth_sections(body, policy.research_synthesis_asset_chars)
        blocks.append(head)
        blocks.append(section)
        # Phase 2.7 — 08_Claims 제외 보완: 원자 claim(§4/§5)을 09 에서 직접 공급.
        if getattr(policy, 'research_synthesis_include_claims', False):
            claims = _extract_synth_claims(body, policy.research_synthesis_claims_chars)
            if claims:
                blocks.append(claims)
        tr['selected_files'].append(fp.name)
        tr['selected_assets'].append(asset)
    text = '\n'.join(blocks)
    tr['status'] = 'ok'
    tr['total_chars'] = len(text)
    _log('research_synthesis_loaded', period=period,
         files=tr['selected_files'], chars=tr['total_chars'])
    return text


def _build_shared_context(year: int, month: int, fund_code: str = None,
                          start_idx: int = 1, target_count: int = 15,
                          *,
                          force_window_ids: set[str] | None = None,
                          research_only: bool = False,
                          policy: DebateContextPolicy | None = None,
                          window: tuple[str, str] | None = None,
                          evidence_window: tuple[str, str] | None = None) -> dict:
    """4인 에이전트 공유 컨텍스트 빌드.

    start_idx: evidence 번호 시작값 (분기 통번호용)
    target_count: (legacy) evidence quota. policy.evidence_target_count 우선.
    force_window_ids: BEW lane 내부 filter (None=전체)
    policy: 컨텍스트 소스 정책. None 이면 research_only(bool) 로 legacy resolve
      (backward-compatible). 소스별 on/off 와 quota/guardrail knob 을 담는다.
    """
    if policy is None:
        policy = resolve_policy("legacy", research_only=research_only)
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

    # evidence cards (research lane + optional news lane) — mode 무관 항상 빌드.
    #   research-only 면 policy 가 news lane 만 차단 → research_pool 로 카드 구성.
    #   카드는 [ref:N] citation 근거라 prompt 에 노출돼야 한다 → evidence_cards_text.
    evidence_ids = []  # 프롬프트에 포함된 기사 ID 추적
    # evidence 는 별도 창(evidence_window)으로 필터 가능 — 짧은 window(1W)에서 리서치가
    # 얇으면 러너가 evidence_window 를 뒤로 넓혀 인용을 확보(시계열/테이블은 window 유지).
    _ev = evidence_window or window
    high_impact, lane_evidence_ids, card_lines, _sel_debug = \
        _build_evidence_candidates(year, month, policy.evidence_target_count, start_idx,
                                   force_window_ids=force_window_ids, policy=policy,
                                   window=_ev)
    evidence_ids.extend(lane_evidence_ids)
    if high_impact:
        context['_next_idx'] = start_idx + len(high_impact)
    context['evidence_cards_text'] = '\n'.join(card_lines)

    # 뉴스 분류 요약 (토픽 카운트 + asset_impact 집계) — policy.news_summary_enabled.
    # legacy parity: 헤더 + 카드 + 집계를 한 string 으로 묶어 기존 출력 그대로 유지.
    news_file = BASE_DIR / 'data' / 'news' / f'{year}-{month:02d}.json'
    if policy.news_summary_enabled and news_file.exists():
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

        lines.extend(card_lines)

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
    # research-only mode 면 graph_paths 차단 (insight_graph = news+naver mixed-source).
    graph_file = BASE_DIR / 'data' / 'insight_graph' / f'{year}-{month:02d}.json'
    if policy.graph_paths_enabled and graph_file.exists():
        graph = json.loads(graph_file.read_text(encoding='utf-8'))
        all_paths = graph.get('transmission_paths', []) or []
        graph_trace['candidate_path_count'] = len(all_paths)
        # confidence threshold 이상 우선, 부족하면 보조로 채워 graph_path_min 까지
        _thr = policy.graph_confidence_threshold
        confident = [p for p in all_paths if (p.get('confidence') or 0) >= _thr]
        weak = [p for p in all_paths if 0 < (p.get('confidence') or 0) < _thr]
        graph_trace['dropped_low_confidence_count'] = len(weak)
        confident.sort(key=lambda p: -(p.get('confidence') or 0))
        weak.sort(key=lambda p: -(p.get('confidence') or 0))
        # 최소 graph_path_min ~ 최대 graph_path_max 개 안정화
        TARGET_MIN, TARGET_MAX = policy.graph_path_min, policy.graph_path_max
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
    if not policy.wiki_keyword_retriever_enabled:
        # research-only: keyword retriever 는 build_wiki_context_pack 과 중복 → 미실행(차단).
        context['wiki_context_text'] = ''
        context['_wiki_trace'] = wiki_trace
    else:
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
        wiki_trace['wiki_excluded_dirs'] = retrieval.get('excluded_dirs', [])
        wiki_trace['wiki_excluded_dir_page_count'] = retrieval.get('excluded_dir_page_count', 0)
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

    # Blog insight — monygeek **persona** 전용 소스 (monygeek_blog_source).
    # ⚠️ persona(유로달러 분석가) 와 다른 개념. policy.monygeek_blog_enabled 로 게이트.
    if policy.monygeek_blog_enabled:
        try:
            from market_research.analyze.blog_analyst import build_monygeek_context
            context['blog_context_text'] = build_monygeek_context(year, month)
        except Exception:
            pass

    # 09_Research_Synthesis — primary synthesis source (Phase 2 1급 승격).
    if policy.research_synthesis_enabled:
        _rs_trace: dict = {}
        context['research_synthesis_text'] = build_research_synthesis_context(
            year, month, policy=policy, trace=_rs_trace)
        context['_research_synthesis_trace'] = _rs_trace

    # indicators.csv — policy.macro_indicators_enabled
    indicators_file = BASE_DIR / 'data' / 'macro' / 'indicators.csv'
    if policy.macro_indicators_enabled and indicators_file.exists():
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

    # 시계열 내러티브 (교차 분석 레이어). window 지정 시 그 날짜창으로 직접 생성.
    try:
        from market_research.report.timeseries_narrator import (
            build_debate_narrative, build_narrative_blocks)
        if window:
            _si = int(window[0].replace('-', ''))
            _ei = int(window[1].replace('-', ''))
            context['timeseries_narrative_text'] = build_narrative_blocks(
                _si, _ei, news_months=_months_in_range(window[0], window[1]))
        else:
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

    # R9-A.3: canonical claim store read-only load. write 0, LLM 호출 0.
    # claim store 결손 / promotion 0 모두 graceful → context['claims'] = [].
    # Phase 2.7: operational_claims_enabled=False(research-only) 면 뉴스-트랙 claim 제외
    #            (09 §4/§5 research claim 으로 대체).
    period_str = f"{year}-{month:02d}"
    promoted_claims: list[dict] = []
    if policy.operational_claims_enabled:
        try:
            from market_research.analyze.claim_store import (
                select_promoted_claims_for_period,
            )
            promoted_claims = select_promoted_claims_for_period(
                period=period_str,
                fund_code=fund_code,
                max_claims=8,
            ) or []
        except Exception as e:
            promoted_claims = []
            print(f'[claim_store] read-side 오류: {e}')
    context['_canonical_claims'] = promoted_claims
    context['claims_text'] = _format_claims_for_context(promoted_claims)

    # R8-B-impl: Asset Movement Anchor — 자산군 기준 anchor + evidence/path nesting.
    # evidence_annotations 가 아직 채워지기 전 단계라 evidence 는 빈 list.
    # debate_service / _synthesize_debate 에서 evidence 생성 후 다시 채울 수 있음.
    # 이 단계에서는 BM 변동 + GraphRAG transmission_paths 매칭만 시도.
    try:
        from market_research.report.asset_movement_anchor import (
            build_asset_movement_anchors, format_anchors_for_prompt,
        )
        ind_csv = BASE_DIR / 'data' / 'macro' / 'indicators.csv'
        # transmission_paths 를 R7 path-shaped 로 변환 — selected_path_labels 의
        # path_id 가 GraphRAG (not R7 PATH_TEMPLATES) 라 매칭률은 낮지만 유효
        anchor_paths = []
        for p in (graph_trace.get('selected_path_labels') or []):
            anchor_paths.append({
                'path_id': str(p.get('idx', '?')),
                'label': str((p.get('labels') or '?')),
                'confidence': p.get('confidence'),
                'covered_chain_nodes': [],
                'supporting_evidence_ids': [],
                'chain': [],
            })
        anchors = build_asset_movement_anchors(
            period=period_str,
            fund_code=fund_code,
            causal_paths=anchor_paths,
            evidence_annotations=[],  # debate 단계 이전에 빈 list
            indicators_csv_path=ind_csv if ind_csv.exists() else None,
            claims=promoted_claims,  # R9-A.3 read-only attach
        )
        context['asset_movement_anchors_text'] = format_anchors_for_prompt(anchors)
        context['_asset_movement_anchors'] = anchors
    except Exception as e:
        context['asset_movement_anchors_text'] = ''
        context['_asset_movement_anchors'] = None
        print(f'[asset_movement_anchor] 오류: {e}')

    return context


# ──────────────────────────────────────────────────────────────────
# R9-A.3 — Canonical Claims block (debate shared context)
# ──────────────────────────────────────────────────────────────────


def _compact_claims_for_persistence(claims: list[dict] | None) -> list[dict]:
    """R9-A.3.x persistence — promoted claim 을 draft/final 보존용 compact 로
    축약. claim_id 형식 'claim:{period}:{hash10}' 에서 wiki_path 추정.

    Persisted fields (사용자 spec D-X-A 8필드):
      - claim_id, claim_text, claim_type
      - affected_assets, confidence, salience
      - supporting_evidence_ids
      - wiki_filename, wiki_path  (둘 다 보존 — wiki_filename 은 hash 만,
        wiki_path 는 디렉토리 prefix 포함)
    """
    if not isinstance(claims, list):
        return []
    out: list[dict] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        cid = c.get('claim_id') or ''
        h10 = (cid.rsplit(':', 1)[-1]
               if isinstance(cid, str) and cid.startswith('claim:')
               else '')
        period = c.get('period') or ''
        wiki_filename = (
            f'{period}_claim_{h10}.md'
            if period and h10 else None
        )
        wiki_path = (
            f'08_Claims/{wiki_filename}' if wiki_filename else None
        )
        out.append({
            'claim_id': cid,
            'claim_text': c.get('claim_text') or '',
            'claim_type': c.get('claim_type') or '',
            'affected_assets': list(c.get('affected_assets') or []),
            'confidence': c.get('confidence'),
            'salience': c.get('salience'),
            'supporting_evidence_ids':
                list(c.get('supporting_evidence_ids') or []),
            'wiki_filename': wiki_filename,
            'wiki_path': wiki_path,
        })
    return out

# R9-A.3.x (D-3-A) — claim 인용 규칙. agent / synthesis 양쪽 prompt 에 동일
# 문구로 부착해 LLM 이 [claim:hash10] 태그를 누락하지 않도록 강제. canonical
# claim 을 실제 논거로 사용한 경우에만 인용하고, 기사 근거가 필요한 사실
# 문장에는 기존 [ref:N] 을 유지한다 (claim 은 ref 를 대체하지 않음).
_CLAIM_CITATION_INSTRUCTION = (
    '\n## 필수: Canonical Claim 인용 규칙 (R9-A.3)\n'
    '- 위 "Canonical Claims" 블록의 항목을 실제 논거 (인과/리스크/해석) 로 '
    '사용한 문장에는 끝에 [claim:hash10] 형태로 인용하세요. '
    'hash10 은 [claim:xxxxxxxxxx] 의 10자 hex 부분 그대로입니다.\n'
    '- 기사 근거가 필요한 사실 문장에는 기존 [ref:N] 을 유지하세요. '
    'claim 은 ref 를 대체하지 않고, canonical 해석/인과 요약의 보조 trace 입니다.\n'
    '- 한 문장에 [ref:N] 과 [claim:hash10] 을 함께 표기할 수 있습니다 '
    '(예: "...A 가 B 로 전이되는 흐름이 관측되었습니다[ref:3][claim:de1729b413].").\n'
    '- 사용하지 않은 claim 은 억지로 인용하지 마세요. '
    'Canonical Claims 블록에 없는 hash10 을 새로 만들지 마세요.\n'
    '- claim_text 를 그대로 복사하지 말고, 본문 맥락에 맞춰 풀어 쓴 뒤 '
    '문장 끝에만 태그를 붙이세요.\n'
)


# ──────────────────────────────────────────────────────────────────
# R9-B.3 — Wiki Context Pack opt-in injection
#
# default OFF. opt-in 시 wiki_context_pack_builder 의 결과를 "primary
# context" 로 prompt 상단에 추가하고, 기존 raw evidence/news/graph/regime
# context 는 "validation/fallback" 으로 위계만 명시한다. raw block 제거 0.
# ──────────────────────────────────────────────────────────────────

WIKI_CONTEXT_PACK_SCHEMA_VERSION = "r9b-context-pack-1.0.0"
WIKI_CONTEXT_PRIMARY_HEADING = "## A. Wiki Primary Context (R9-B.3 opt-in)"
WIKI_CONTEXT_RAW_HEADING = "## B. Raw Validation / Fallback Context"

# research-only mode 전용 Opus 종합 원칙 (Phase 2 §6). legacy 면 미주입.
_RESEARCH_ONLY_SYNTHESIS_DIRECTIVE = (
    "## research-only 종합 원칙 (필수)\n"
    "- 위 '09 Research Synthesis(재종합)' 를 이번 종합의 primary synthesis source 로 사용하세요.\n"
    "- 데이터 분석가(quant)의 수치를 numeric anchor 로 우선하고, 제공된 수치는 반올림하지 마세요.\n"
    "- monygeek 이견(dissent)은 base view 와 구분해 tail-risk / 대안적 유동성 시각으로만 반영하세요 "
    "(주류 컨센서스와 혼동 금지).\n"
    "- raw 뉴스 또는 mixed graph 를 근거로 사용하지 마세요 (이번 모드에선 제공되지 않습니다)."
)

_WIKI_CONTEXT_HIERARCHY_NOTE = (
    "> **위계 안내** — A. Wiki Primary Context (canonical wiki 메모) 가 "
    "기본 해석 베이스입니다. B. Raw Validation/Fallback 은 최신성·수치 "
    "검증 자료이며, A 와 명백한 수치/시계열 충돌이 있을 때만 raw 를 "
    "우선합니다. 일반 해석은 A 를, 단정 수치 인용은 B 의 indicators/PA "
    "를 사용하세요.\n"
)


class WikiContextPackError(ValueError):
    """opt-in path load 시 schema_version / period_key / stage 불일치."""


def _validate_wiki_context_pack(
    pack: dict, *,
    expected_period: str | None = None,
    expected_stage: str | None = None,
) -> None:
    """opt-in 으로 외부에서 load 된 pack 의 contract 확인. 통과 시 None,
    위반 시 WikiContextPackError. fields 누락도 동일 에러로 묶는다.
    """
    if not isinstance(pack, dict):
        raise WikiContextPackError(
            f"wiki_context_pack must be a dict, got {type(pack).__name__}")
    sv = pack.get("schema_version")
    if sv != WIKI_CONTEXT_PACK_SCHEMA_VERSION:
        raise WikiContextPackError(
            f"wiki_context_pack schema_version mismatch: "
            f"got {sv!r}, expected {WIKI_CONTEXT_PACK_SCHEMA_VERSION!r}")
    pk = pack.get("period_key")
    if expected_period is not None and pk != expected_period:
        raise WikiContextPackError(
            f"wiki_context_pack period_key mismatch: "
            f"got {pk!r}, expected {expected_period!r}")
    st = pack.get("stage")
    if expected_stage is not None and st != expected_stage:
        raise WikiContextPackError(
            f"wiki_context_pack stage mismatch: "
            f"got {st!r}, expected {expected_stage!r}")


def _build_wiki_context_pack_for_debate(
    *,
    period_key: str,
    stage: str,
    fund_code: str | None,
    max_pages: int,
    period_type: str = "monthly",
    period_keys: list[str] | None = None,
    restrict_dirs: tuple[str, ...] | None = None,
) -> dict:
    """R9-B.3 — builder 호출 wrapper. read-only, LLM 0.

    R9-B.5.6 — period_type='quarterly' + period_keys=list[str] 를 받아 그대로
    builder 에 전달. monthly default 는 회귀 없음.

    Lazy import — builder 가 wiki/paths.py 만 의존하므로 무거운 사이드
    이펙트 없음. failure 는 caller 에서 WikiContextPackError 로 묶지
    않고 그대로 surface (builder 내부 ValueError 도 회귀 0).
    """
    from market_research.report.wiki_context_pack_builder import (
        build_wiki_context_pack,
    )
    return build_wiki_context_pack(
        period_key=period_key,
        period_type=period_type,
        period_keys=period_keys,
        stage=stage,
        fund_code=fund_code,
        max_pages=max_pages,
        restrict_dirs=restrict_dirs,
    )


def _excerpt(text: str | None, limit: int) -> str:
    if not text:
        return ""
    t = str(text).strip()
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)].rstrip() + "…"


def _format_wiki_primary_context_for_prompt(
    pack: dict | None, *,
    excerpt_per_entry: int = 240,
    claim_excerpt: int = 200,
) -> str:
    """wiki_context_pack → A. Wiki Primary Context 블록 (markdown).

    빈 pack 이면 빈 문자열 반환 — caller 가 block 자체를 skip 한다.
    """
    if not isinstance(pack, dict):
        return ""
    market = pack.get("market_context") or {}
    fund_ctx = pack.get("fund_context") or {}
    fund_page = fund_ctx.get("fund_page") if isinstance(fund_ctx, dict) else None
    claims = market.get("claims") or []
    graph = market.get("graph_evidence") or []
    regime = market.get("regime") or []
    events = market.get("events") or []
    entities = market.get("entities") or []
    assets = market.get("assets") or []

    has_any = bool(
        claims or graph or regime or events or entities or assets or fund_page
    )
    if not has_any:
        return ""

    lines: list[str] = [WIKI_CONTEXT_PRIMARY_HEADING]
    lines.append(
        f"_pack_period={pack.get('period_key')} stage={pack.get('stage')} "
        f"window={pack.get('window_start')}~{pack.get('window_end')} "
        f"as_of={pack.get('as_of_date')} pages_selected="
        f"{(pack.get('source_trace') or {}).get('wiki_pages_selected', 0)}_"
    )
    lines.append("")

    if fund_page:
        lines.append("### A.0 Fund Pinned Page")
        title = fund_page.get("title") or fund_page.get("path")
        lines.append(
            f"- `{fund_page.get('path')}` — {title}"
        )
        body = _excerpt(fund_page.get("excerpt"), excerpt_per_entry)
        if body:
            lines.append(f"  > {body}")
        lines.append("")

    if claims:
        lines.append("### A.1 Canonical Claims (08_Claims, joined)")
        for c in claims:
            cid = c.get("claim_id") or "?"
            h10 = cid.rsplit(":", 1)[-1] if cid.startswith("claim:") else cid
            text = _excerpt(c.get("title") or c.get("excerpt"), claim_excerpt)
            ac = ", ".join(c.get("affected_assets") or []) or "(없음)"
            rule = c.get("promotion_rule") or "?"
            related = c.get("related_group_ids") or []
            related_s = f" related={','.join(related)}" if related else ""
            lines.append(
                f"- `[claim:{h10}]` ({rule}) assets=[{ac}]{related_s} — {text}"
            )
        lines.append("")

    if graph:
        lines.append("### A.2 Graph Evidence (07_Graph_Evidence)")
        for g in graph:
            title = g.get("title") or g.get("path")
            lines.append(f"- `{g.get('path')}` — {title}")
            body = _excerpt(g.get("excerpt"), excerpt_per_entry)
            if body:
                lines.append(f"  > {body}")
        lines.append("")

    if regime:
        lines.append("### A.3 Regime Canonical (05_Regime_Canonical)")
        for r in regime:
            title = r.get("title") or r.get("path")
            lines.append(f"- `{r.get('path')}` — {title}")
            body = _excerpt(r.get("excerpt"), excerpt_per_entry)
            if body:
                lines.append(f"  > {body}")
        lines.append("")

    if events:
        lines.append("### A.4 Events (01_Events)")
        for e in events:
            title = e.get("title") or e.get("path")
            lines.append(f"- `{e.get('path')}` — {title}")
            body = _excerpt(e.get("excerpt"), excerpt_per_entry)
            if body:
                lines.append(f"  > {body}")
        lines.append("")

    if entities:
        lines.append("### A.5 Entities (02_Entities)")
        for e in entities:
            title = e.get("title") or e.get("path")
            lines.append(f"- `{e.get('path')}` — {title}")
        lines.append("")

    if assets:
        lines.append("### A.6 Assets (03_Assets)")
        for a in assets:
            title = a.get("title") or a.get("path")
            lines.append(f"- `{a.get('path')}` — {title}")
            body = _excerpt(a.get("excerpt"), excerpt_per_entry)
            if body:
                lines.append(f"  > {body}")
        lines.append("")

    lines.append(_WIKI_CONTEXT_HIERARCHY_NOTE)
    return "\n".join(lines).rstrip() + "\n"


def _wiki_context_pack_trace(pack: dict | None) -> dict:
    """opt-in trace 필드만 추출. legacy mode 에선 호출 X — 호출자가 분기.

    R9-B.5.6 — quarterly union 시 period_type/period_keys/by_period 도
    surface (monthly 는 단일 원소 list / 빈 by_period 로 일관 노출).
    """
    if not isinstance(pack, dict):
        return {}
    st = pack.get("source_trace") or {}
    return {
        "wiki_context_pack_enabled": True,
        "wiki_context_pack_schema_version": pack.get("schema_version"),
        "wiki_context_pack_period_key": pack.get("period_key"),
        "wiki_context_pack_period_type": pack.get("period_type"),
        "wiki_context_pack_period_keys": list(pack.get("period_keys") or []),
        "wiki_context_pack_stage": pack.get("stage"),
        "wiki_pages_selected": st.get("wiki_pages_selected", 0),
        "selected_wiki_paths": list(st.get("selected_wiki_paths") or []),
        "wiki_source_type_counts": dict(st.get("source_type_counts") or {}),
        "selected_claim_ids": list(st.get("selected_claim_ids") or []),
        "selected_related_group_ids": list(
            st.get("selected_related_group_ids") or []
        ),
        "claim_store_to_wiki_join_rate": st.get(
            "claim_store_to_wiki_join_rate"
        ),
        "source_cutoff_violations": st.get("source_cutoff_violations", 0),
        "claim_store_selected_count_by_period": dict(
            st.get("claim_store_selected_count_by_period") or {}
        ),
    }


def _format_claims_for_context(
    claims: list[dict] | None,
    *, max_claims: int = 8, text_truncate: int = 180,
) -> str:
    """promoted claims → debate shared context block (read-only).

    Renders short lines per claim; preserves [claim:hash10] anchor for
    downstream evidence_trace surface. claims 비어있으면 빈 문자열 반환
    (block 전체 skip — 기존 prompt 길이/순서 변경 0).
    """
    if not isinstance(claims, list) or not claims:
        return ''
    items = claims[:max_claims]
    lines: list[str] = ['## Canonical Claims (R9-A.3, 참고용)']
    for c in items:
        if not isinstance(c, dict):
            continue
        cid = c.get('claim_id') or ''
        h10 = cid.rsplit(':', 1)[-1] if cid.startswith('claim:') else 'unknown'
        text = (c.get('claim_text') or '').strip()
        if len(text) > text_truncate:
            text = text[:text_truncate - 1].rstrip() + '…'
        ctype = c.get('claim_type') or '?'
        ac_list = []
        for a in c.get('affected_assets') or []:
            if isinstance(a, dict):
                v = a.get('asset_class')
                if v:
                    ac_list.append(str(v))
            elif isinstance(a, str):
                ac_list.append(a)
        cf = c.get('confidence')
        sal = c.get('salience')
        ev_ids = c.get('supporting_evidence_ids') or []
        lines.append(f'[claim:{h10}] {text}')
        lines.append(
            f'  - type: {ctype} / assets: {", ".join(ac_list) or "(없음)"}'
        )
        lines.append(
            f'  - confidence: {cf} / salience: {sal}'
        )
        if ev_ids:
            lines.append(f'  - evidence_ids: {", ".join(map(str, ev_ids))}')
    lines.append(
        '> 위 claim 은 canonical store 에 저장된 R9-A.2 promotion 통과 자료. '
        '단정 결론으로 인용하지 말고, 자산군 해석 근거가 필요할 때만 참고.'
    )
    return '\n'.join(lines)


def _build_agent_prompt(agent_type: str, context: dict) -> str:
    """에이전트별 프롬프트 생성"""
    # R8-B-impl: Asset Movement Anchors 가 가장 윗단 (자산군 1차 unit).
    # R9-A.3: anchor 직후 Canonical Claims 블록 (있을 때만, 빈 문자열이면 skip).
    # R9-A.3.x: claims block 이 있을 때만 _CLAIM_CITATION_INSTRUCTION 도 inline.
    # R9-B.3: wiki_primary_context_text (opt-in) 가 있으면 A 블록으로 prepend,
    #         기존 raw blocks 는 B 블록 heading 으로 라벨링. raw block 제거 0.
    anchor_block = context.get('asset_movement_anchors_text') or ''
    claims_block = context.get('claims_text') or ''
    wiki_primary_block = context.get('wiki_primary_context_text') or ''
    # 09_Research_Synthesis hook (research-only 면 채워짐, legacy 면 '').
    research_synth_block = context.get('research_synthesis_text') or ''
    raw_heading = (WIKI_CONTEXT_RAW_HEADING + '\n\n') if wiki_primary_block else ''
    # evidence cards: news_summary 가 있으면 그 안에 포함(legacy). research-only 면
    # news_summary='' 이라 research lane 카드(evidence_cards_text)로 대체.
    evidence_block = (context.get('news_summary_text')
                      or context.get('evidence_cards_text')
                      or '(뉴스 데이터 없음)')
    shared = (
        f'## {context["year"]}년 {context["month"]}월 시장 분석\n\n'
        + (wiki_primary_block + '\n' if wiki_primary_block else '')
        # research_synthesis(09) 는 primary synthesis → raw heading 위에 배치.
        + (research_synth_block + '\n\n' if research_synth_block else '')
        + raw_heading
        + (anchor_block + '\n\n' if anchor_block else '')
        + (claims_block + '\n\n' if claims_block else '')
        # citation 지시 — 08 claims_block 또는 09 §4/§5(research_synth) 에 claim 이 있으면 적용.
        + (_CLAIM_CITATION_INSTRUCTION + '\n' if (claims_block or research_synth_block) else '')
        + f'{evidence_block}\n\n'
        + f'{context.get("indicators_text", "(지표 데이터 없음)")}\n\n'
        + f'{context.get("timeseries_narrative_text", "")}\n\n'
        + f'{context.get("graph_paths_text", "")}\n\n'
        + f'{context.get("wiki_context_text", "")}\n\n'
        + f'{context.get("asset_coverage_text", "")}\n'
    )

    if agent_type == 'monygeek':
        shared += (
            f'\n## 블로거 분석 프레임워크\n'
            f'{context.get("blog_context_text", "(블로그 데이터 없음)")}\n'
        )

    # P3: 주요 인과 경로 / WikiTree 메모 활용 강제 (소량, JSON 응답 지시 직전에 삽입)
    # research-only mode 면 graph_paths 가 없으므로 graph 인용 강제 지시를 넣지 않는다
    # (없는 경로를 지어내게 만들기 때문). graph_paths_text 있을 때만 삽입.
    if context.get('graph_paths_text'):
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
        '## 응답 형식 (반드시 준수)\n'
        '응답은 유효한 JSON 객체 하나만 출력. 설명 텍스트 / 코드블록 / 주석 금지.\n'
        '각 문자열 값 안에 줄바꿈 금지. key_points 최대 5개(각 100자), '
        'tail_risks 최대 3개(각 80자), reasoning 200자 이내.\n\n'
        # R8-B-2: asset_movement_commentary 필수 강화
        '## asset_movement_commentary (필수, R8-B-2 강화)\n'
        '- 빈 배열 금지. 반드시 3개 이상의 자산군 항목을 작성.\n'
        '- 위 "Asset Movement Anchors" 의 importance rank 상위 자산군부터 선택.\n'
        '- 우선순위: 해외주식 / 국내채권 / 환율(FX) / 원자재금 / 국내주식.\n'
        '- 각 항목은 6개 필드를 모두 채울 것: '
        'asset_class / past_movement / drivers / causal_paths / outlook / portfolio_implication.\n'
        '- past_movement 의 수치는 anchor 에 있는 값만 그대로 사용. anchor 에 BM 값이 '
        '없으면 "수익률 미확인 — 정성 평가" 같은 정성 표현 사용 (수치 임의 생성 금지).\n'
        '- drivers 최대 3개 (각 30자), outlook 80자 이내, portfolio_implication 80자 이내.\n'
        '- causal_paths 는 anchor 의 path_id 또는 GraphRAG path label 그대로 인용.\n'
        '- fund BM 이 없는 자산군에 대해 alpha / 초과수익률 언급 금지.\n\n'
        '## 응답 schema (예시)\n'
        '{"stance":"bullish|bearish|neutral","key_points":["포인트1","포인트2"],'
        '"risk_assessment":"리스크요약",'
        '"asset_allocation_view":{"국내주식":"비중확대|유지|축소","국내채권":"비중확대|유지|축소",'
        '"해외주식":"비중확대|유지|축소","해외채권":"비중확대|유지|축소"},'
        '"asset_movement_commentary":['
        '{"asset_class":"해외주식","past_movement":"미국 성장주 -3%대 조정",'
        '"drivers":["성장주 밸류에이션 부담","금리 변동성","지정학 리스크"],'
        '"causal_paths":["geopolitical_oil_inflation_rates_growth"],'
        '"outlook":"조정 이후 밸류에이션 회복 가능성 주목",'
        '"portfolio_implication":"성장주 OW 유지, 변동성 확대 시 분할 조정"},'
        '{"asset_class":"국내채권","past_movement":"수익률 미확인 — 정성 평가",'
        '"drivers":["통화정책 기대 변화","WGBI 외국인 수급"],'
        '"causal_paths":["rates_domestic_bond"],'
        '"outlook":"금리 상단 인식 + 수급 우호적",'
        '"portfolio_implication":"국내채권 듀레이션 점진적 확대"},'
        '{"asset_class":"환율(FX)","past_movement":"USDKRW +1.7%",'
        '"drivers":["달러 강세","외인 자금 흐름"],'
        '"causal_paths":["fx_translation_overseas_assets"],'
        '"outlook":"단기 변동성 확대",'
        '"portfolio_implication":"해외자산 환헤지 비율 점검"}'
        '],'
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
            # R8-B-impl: 1500 → 2500 (asset_movement_commentary 추가).
            # R8-B-2 hotfix: 2500 → 5000. live smoke 에서 풍부한 amc (4 자산군
            # × 6 필드) 채울 때 ~3500자 응답이 잘려 outer dict `}` 미종료 →
            # parse fail (list 반환) → fallback path. 5000 으로 충분히 buffer.
            max_tokens=5000,
            log_label=f'agent_{agent_type}',
        )
        result = _parse_json_response(text)
        # parse_json_response 는 dict 또는 list 또는 None 반환 가능.
        # asset_movement_commentary 같은 nested array 가 있는 응답이 잘리면
        # 외부 object 가 깨져서 array 가 fallback 추출되는 케이스 있음 → dict 보호.
        if isinstance(result, dict):
            result['agent'] = agent_type
            result['agent_name'] = persona['name']
            # R8-B-2: amc 검증 + fallback surface (agent output 무수정)
            try:
                from market_research.report.asset_movement_anchor import (
                    validate_amc_response, build_amc_fallback,
                )
                amc_warnings = validate_amc_response(
                    result.get('asset_movement_commentary'),
                )
                if amc_warnings:
                    result['asset_movement_commentary_warnings'] = amc_warnings
                # fallback 은 항상 surface (admin 검수 자료 — agent amc 와 별개)
                fallback = build_amc_fallback(
                    context.get('_asset_movement_anchors'), top_n=3,
                )
                if fallback:
                    result['asset_movement_commentary_fallback'] = fallback
            except Exception as exc:
                result['asset_movement_commentary_warnings'] = [
                    f'guard/fallback failed: {exc}'
                ]
            return result
        else:
            # R8-B-2 hotfix: parse fail diagnostic — truncation 의심 시 hint
            warnings = [
                f'JSON 파싱 실패 또는 array 반환 (type='
                f'{type(result).__name__}): {text[:200]}'
            ]
            # response 가 잘려 outer dict 종료 안 된 패턴 (max_tokens 부족 의심)
            stripped = text.strip().rstrip('`').rstrip()
            if (stripped and not stripped.endswith('}')
                    and 'asset_movement_commentary' in text):
                warnings.append(
                    'parse_failed_by_truncation: response does not end with `}` '
                    'and contains asset_movement_commentary — consider increasing '
                    f'max_tokens (current response len={len(text)} chars)'
                )
            return {
                'agent': agent_type,
                'agent_name': persona['name'],
                'stance': 'neutral',
                'key_points': warnings,
                'raw_text': text,
                'asset_movement_commentary_warnings': warnings[1:] if len(warnings) > 1 else [],
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
    # R9-A.3.x: synthesis 단계에도 Canonical Claims block + 인용 규칙 주입.
    # R9-B.3: opt-in 시 wiki_primary_context_text 가 synthesis prompt 에도 들어감.
    graph_block = context.get("graph_paths_text", "") or ""
    wiki_block = context.get("wiki_context_text", "") or ""
    coverage_block = context.get("asset_coverage_text", "") or ""
    claims_block = context.get("claims_text", "") or ""
    wiki_primary_block = context.get("wiki_primary_context_text", "") or ""
    research_synth_block = context.get("research_synthesis_text", "") or ""
    # research-only 면 news_summary 가 비어 → research lane 카드(evidence_cards_text) 사용.
    evidence_block = (context.get("news_summary_text")
                      or context.get("evidence_cards_text") or "")
    is_research_only = (context.get('_context_source_trace') or {}).get('policy') == 'research_only'
    raw_heading = (WIKI_CONTEXT_RAW_HEADING + '\n\n') if wiki_primary_block else ''
    comment_prompt = (
        '4명의 분석가가 각각 다른 시각에서 시장을 분석했습니다.\n\n'
        + (wiki_primary_block + '\n' if wiki_primary_block else '')
        + (research_synth_block + '\n\n' if research_synth_block else '')
        + raw_heading
        + f'## 분석가별 의견\n{debate_text}\n\n'
        f'## 뉴스 evidence\n{evidence_block}\n\n'
        + (f'{claims_block}\n\n' if claims_block else '')
        + (_CLAIM_CITATION_INSTRUCTION + '\n' if (claims_block or research_synth_block) else '')
        + (f'{graph_block}\n\n' if graph_block else '')
        + (f'{wiki_block}\n\n' if wiki_block else '')
        + (f'{coverage_block}\n\n' if coverage_block else '')
        + (_RESEARCH_ONLY_SYNTHESIS_DIRECTIVE + '\n\n' if is_research_only else '')
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
        # R9-B.4.1 — Opus synthesis 는 stream 사용. quarterly + wiki primary
        # context 조합에서 prompt 가 길어져 non-streaming 10분 한계를 초과한
        # 회귀 (R9-B.4 backtest 2026-Q1 fail) 해결.
        customer_comment = _call_llm(
            model='claude-opus-4-8',
            system=system_msg,
            prompt=comment_prompt,
            max_tokens=comment_max_tokens,
            log_label='synthesis_step1_comment',
            stream=True,
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
        # R9-B.4.1 — Step 2 도 Opus. Step 1 과 동일 prompt 사이즈 누적 위험.
        text = _call_llm(
            model='claude-opus-4-8',
            system=system_msg,
            prompt=analysis_prompt,
            max_tokens=2500,
            log_label='synthesis_step2_analysis',
            stream=True,
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

def _record_context_source_trace(context: dict, policy: DebateContextPolicy) -> dict:
    """Phase 1 §6 — prompt 섹션 dump + research-only 차단 검증 로그.

    context['_context_source_trace'] 에 섹션별 char 수 + active 목록 + policy 이름을
    기록. research-only 면 금지 소스(news/graph/retriever) 누수 검증 후 로그/경고.
    """
    sizes = summarize_prompt_sections(context)
    trace = {
        'policy': policy.name,
        'section_chars': sizes,
        'active_sections': [s for s, n in sizes.items() if n > 0],
        'research_synthesis': context.get('_research_synthesis_trace'),
    }
    if policy.name == 'research_only':
        ok, violations = validate_research_only_clean(context)
        trace['research_only_clean'] = ok
        trace['research_only_violations'] = violations
        if ok:
            print('  [research-only] raw news/graph/retriever 차단 확인 ✓')
        else:
            print(f'  [research-only] ⚠️ 금지 소스 누수: {violations}')
        _log('context_source_trace', **trace)
    else:
        _log('context_source_trace', **trace)
    context['_context_source_trace'] = trace
    return trace


def run_market_debate(year: int, month: int,
                      *,
                      force_window_ids: set[str] | None = None,
                      research_only: bool = False,
                      context_mode: str = "research_only",
                      use_wiki_context_pack: bool = True,
                      wiki_context_pack: dict | None = None,
                      wiki_context_max_pages: int = 12,
                      window: tuple[str, str] | None = None,
                      evidence_window: tuple[str, str] | None = None) -> dict:
    """
    시장 전체 debate (월 1회, 펀드 무관).
    4인 에이전트 병렬 실행 -> Opus 2단계 종합 -> 자산군별 분석 결과.
    펀드별 캐시에서는 이 결과를 참조하여 보유 비중에 맞는 코멘트만 사용.

    context_mode (Phase 1): 'legacy'(default, 기존 출력 불변) | 'research_only'
      (naver_research wiki + synthesis 중심, news/graph/retriever 차단). 기존
      `research_only: bool` 은 backward-compatible 하게 흡수(resolve_policy).
      research-only 면 wiki_context_pack dir 도 research dir(03/05/08)로 제한.

    force_window_ids: BEW viewer 에서 선택된 window_id set (None=전체 BEW 사용).

    WIKI-DEFAULT.1 — wiki_context_pack 이 default ON:
      use_wiki_context_pack=True (default) 시 wiki_context_pack_builder 결과를
        prompt 의 "A. Wiki Primary Context" 블록으로 prepend. 기존 raw
        evidence/news/graph/regime block 은 "B. Raw Validation/Fallback"
        라벨로 보존 (raw 제거 0).
      use_wiki_context_pack=False (opt-out) 시 legacy raw-first prompt 그대로.
      wiki_context_pack: 외부에서 미리 build/load 된 pack. None 이면 builder
        를 inline 호출. schema_version / period_key 일치 검증 (mismatch 시
        WikiContextPackError).
      wiki_context_max_pages: builder 의 max_pages (default 12).
    """
    policy = resolve_policy(context_mode, research_only=research_only)
    print(f'\n-- Market Debate: {year}-{month:02d} (context_mode={policy.name}) --')
    if window:
        print(f'  [window] evidence/timeseries {window[0]} ~ {window[1]} '
              f'(구조 backbone={year}-{month:02d})')
    if force_window_ids:
        print(f'  [forced BEW] {len(force_window_ids)}개 window_id 만 evidence lane 에 허용')

    # WIKI-DEFAULT.1 — wiki_context_pack default ON. opt-out 시 raw-first.
    prompt_context_mode = 'legacy_raw_first_opt_out'
    wcp_trace_fields: dict = {'wiki_context_pack_enabled': False}
    wiki_primary_text = ''
    wcp_used: dict | None = None
    if use_wiki_context_pack and policy.research_wiki_enabled:
        period_key = f'{year}-{month:02d}'
        if wiki_context_pack is not None:
            _validate_wiki_context_pack(
                wiki_context_pack,
                expected_period=period_key,
                expected_stage='market_debate',
            )
            wcp_used = wiki_context_pack
        else:
            wcp_used = _build_wiki_context_pack_for_debate(
                period_key=period_key,
                stage='market_debate',
                fund_code=None,
                max_pages=wiki_context_max_pages,
                restrict_dirs=policy.wiki_context_pack_dirs,
            )
        wiki_primary_text = _format_wiki_primary_context_for_prompt(wcp_used)
        wcp_trace_fields = _wiki_context_pack_trace(wcp_used)
        prompt_context_mode = 'wiki_context_pack_default'
        print(f'  [wiki_context_pack] enabled (default), pages='
              f'{wcp_trace_fields.get("wiki_pages_selected", 0)}')

    context = _build_shared_context(year, month, force_window_ids=force_window_ids,
                                    policy=policy, window=window,
                                    evidence_window=evidence_window)
    context['wiki_primary_context_text'] = wiki_primary_text
    context['_wiki_context_pack'] = wcp_used
    context['_prompt_context_mode'] = prompt_context_mode
    # Phase 1 — context source trace + research-only 차단 검증 로그.
    _record_context_source_trace(context, policy)
    # Phase 2.5 — research-only 인데 09 가 없으면 **legacy 폴백하지 않고** 명확히 경고.
    #             (auto-fallback 미도입 — 정책상 09 없이 research_only 로 진행, degraded.)
    if policy.research_synthesis_enabled and not (context.get('research_synthesis_text') or '').strip():
        print(f'  ⚠️ [research-only] {year}-{month:02d} 09_Research_Synthesis 없음 — '
              f'primary synthesis 비어 degraded 진행(legacy 폴백 안 함). '
              f'09 생성: daily_update Step 2.9 또는 research_consensus 실행 필요.')
        _log('research_only_09_missing', period=f'{year}-{month:02d}',
             policy=policy.name, fallback='none')
    print(f'  컨텍스트 빌드 완료 (sections: {", ".join(active_sections(context))})')

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
        # R9-B.3 — wiki context pack trace (legacy 시 'wiki_context_pack_enabled'=False)
        'prompt_context_mode': prompt_context_mode,
        'wiki_context_pack_enabled': bool(use_wiki_context_pack),
        'wiki_primary_context_chars': len(wiki_primary_text or ''),
        'raw_validation_context_chars': (
            len(context.get('news_summary_text') or '')
            + len(context.get('indicators_text') or '')
            + len(context.get('timeseries_narrative_text') or '')
            + len(context.get('graph_paths_text') or '')
            + len(context.get('wiki_context_text') or '')
            + len(context.get('asset_coverage_text') or '')
        ),
        **{k: v for k, v in wcp_trace_fields.items()
           if k != 'wiki_context_pack_enabled'},
    }

    # R8-B-impl: agent 측 asset_movement_commentary union (dedupe by asset_class,
    # 각 자산군에서 confidence 가 가장 높은 항목을 채택. importance rank 정렬)
    amc_pool: dict[str, dict] = {}
    for resp in agent_responses.values():
        for item in (resp.get('asset_movement_commentary') or []):
            ac = (item or {}).get('asset_class')
            if not ac:
                continue
            # 첫 등장 우선. 추후 LLM extractor 시 점수 기반 dedup 가능.
            if ac not in amc_pool:
                amc_pool[ac] = item
    anchors = context.get('_asset_movement_anchors') or {}
    rank_by_ac = {a['asset_class']: a.get('movement_rank', 99)
                   for a in (anchors.get('asset_movements') or [])}
    asset_movement_commentary_union = sorted(
        amc_pool.values(),
        key=lambda x: rank_by_ac.get(x.get('asset_class'), 99),
    )

    # R8-B-2: per-agent amc warning 합산 (admin 검수용)
    amc_warnings_by_agent: dict[str, list[str]] = {}
    for ag, resp in agent_responses.items():
        ws = resp.get('asset_movement_commentary_warnings') or []
        if ws:
            amc_warnings_by_agent[ag] = list(ws)

    # R8-B-2: deterministic fallback (anchors 기반, agent 미생성 시 admin 보정 자료)
    try:
        from market_research.report.asset_movement_anchor import build_amc_fallback
        amc_fallback = build_amc_fallback(anchors, top_n=3) if anchors else []
    except Exception:
        amc_fallback = []

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
        # R8-B-impl: asset movement layer (input anchors + agent commentary union)
        'asset_movement_anchors': anchors or None,
        'asset_movement_commentary': asset_movement_commentary_union,
        # R8-B-2: agent 가 amc 를 비웠을 때 admin 검수용 별도 field
        'asset_movement_commentary_fallback': amc_fallback,
        'asset_movement_commentary_warnings_by_agent': amc_warnings_by_agent,
        # R9-A.3.x (D-X-A) — canonical claims persistence. fund_comment_service
        # 의 _market_comment_to_inputs 가 market_payload['claims'] 를 그대로
        # 받아 inputs['claims'] 로 전달 → comment_engine.build_report_prompt
        # 의 claim_block 까지 자동 흐름. 빈 list 면 키만 존재 (downstream 회귀 0).
        'claims': _compact_claims_for_persistence(
            context.get('_canonical_claims') or []),
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


def _evidence_month_distribution(evidence_ids: list, year: int,
                                   months: list[int]) -> dict[str, int]:
    """evidence_id (article_id) 의 month 별 분포. Q-FIX-1.

    LLM 호출 없이 디스크 read 만 — news json + naver research adapted 두 소스에서
    article_id → month 매핑 후 Counter. 매핑 실패는 'unknown' 으로 집계.
    """
    from collections import Counter
    id_to_month: dict[str, str] = {}
    for m in months:
        news_file = BASE_DIR / 'data' / 'news' / f'{year}-{m:02d}.json'
        if not news_file.exists():
            continue
        try:
            data = json.loads(news_file.read_text(encoding='utf-8'))
        except Exception:
            continue
        for a in data.get('articles', []):
            aid = a.get('_article_id')
            if aid and aid not in id_to_month:
                id_to_month[aid] = f'{year}-{m:02d}'
    # naver research adapted
    try:
        from market_research.collect.naver_research_adapter import load_adapted
        for m in months:
            for a in load_adapted(f'{year}-{m:02d}'):
                aid = a.get('_article_id')
                if aid and aid not in id_to_month:
                    id_to_month[aid] = f'{year}-{m:02d}'
    except Exception:
        pass
    counter = Counter(id_to_month.get(eid, 'unknown') for eid in evidence_ids)
    return dict(counter)


def run_quarterly_debate(year: int, quarter: int,
                         *,
                         force_window_ids: set[str] | None = None,
                         research_only: bool = False,
                         context_mode: str = "research_only",
                         use_wiki_context_pack: bool = True,
                         wiki_context_pack: dict | None = None,
                         wiki_context_max_pages: int = 12) -> dict:
    """
    분기 통합 debate.
    해당 분기 3개월의 뉴스/지표를 종합하여 debate 실행.

    force_window_ids: BEW viewer 에서 선택된 window_id set. 3개월 컨텍스트 각각에
    동일 set 이 전달되며, 월과 실제로 매칭되는 wid 만 해당 월 BEW lane 에 적용된다
    (다른 월의 contract 에는 매칭 안 되므로 자연스럽게 무효화 됨).

    WIKI-DEFAULT.1 — wiki_context_pack default ON. market_debate 와 동일 시맨틱.
    R9-B.5.6 — period_type="quarterly", period_key="YYYY-QX", period_keys=[3개월].
    builder 가 분기 전체 month 의 claim_store 를 union 하고 wiki page selection 도
    분기 window 기준으로 수행.
    """
    policy = resolve_policy(context_mode, research_only=research_only)
    months = [(quarter - 1) * 3 + i for i in range(1, 4)]
    print(f'\n-- Quarterly Debate: {year}Q{quarter} ({months[0]}~{months[2]}월) '
          f'(context_mode={policy.name}) --')
    if force_window_ids:
        print(f'  [forced BEW] {len(force_window_ids)}개 window_id 만 evidence lane 에 허용')

    # WIKI-DEFAULT.1 — wiki_context_pack default ON (quarterly).
    prompt_context_mode = 'legacy_raw_first_opt_out'
    wcp_trace_fields: dict = {'wiki_context_pack_enabled': False}
    wiki_primary_text_q = ''
    wcp_used_q: dict | None = None
    if use_wiki_context_pack and policy.research_wiki_enabled:
        # R9-B.5.6 — quarterly union pack.
        # period_key: YYYY-QX label (display + pack identifier)
        # period_keys: 분기 3개월 — builder 가 monthly claim_store 를 union.
        quarter_label = f'{year}-Q{quarter}'
        quarter_period_keys = [f'{year}-{m:02d}' for m in months]
        if wiki_context_pack is not None:
            _validate_wiki_context_pack(
                wiki_context_pack,
                expected_period=quarter_label,
                expected_stage='quarterly_debate',
            )
            wcp_used_q = wiki_context_pack
        else:
            wcp_used_q = _build_wiki_context_pack_for_debate(
                period_key=quarter_label,
                period_type='quarterly',
                period_keys=quarter_period_keys,
                stage='quarterly_debate',
                fund_code=None,
                max_pages=wiki_context_max_pages,
                restrict_dirs=policy.wiki_context_pack_dirs,
            )
        wiki_primary_text_q = _format_wiki_primary_context_for_prompt(wcp_used_q)
        wcp_trace_fields = _wiki_context_pack_trace(wcp_used_q)
        prompt_context_mode = 'wiki_context_pack_default'
        print(f'  [wiki_context_pack] enabled (default, quarterly union), '
              f'period_keys={quarter_period_keys}, '
              f'pages={wcp_trace_fields.get("wiki_pages_selected", 0)}')

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
    all_evidence_cards = []   # research-only: news_summary 비어도 evidence 카드 보존
    all_research_synth = []   # 09 synthesis (research-only)
    all_evidence_ids = []
    next_idx = 1  # 분기 통번호
    last_ctx = None  # Q-FIX-1: 마지막 월 ctx 의 trace 보존

    # 월별 최소 quota: 각 월 최소 5건, 나머지는 자유 배분 (총 ~15~20건)
    MONTHLY_QUOTA = 5
    for m in months:
        ctx = _build_shared_context(year, m, start_idx=next_idx, target_count=MONTHLY_QUOTA,
                                    force_window_ids=force_window_ids, policy=policy)
        next_idx = ctx.get('_next_idx', next_idx)
        if ctx.get('indicators_text') and not merged_context['indicators_text']:
            merged_context['indicators_text'] = ctx['indicators_text']
        if ctx.get('news_summary_text'):
            all_news_lines.append(f'--- {year}-{m:02d} ---')
            all_news_lines.append(ctx['news_summary_text'])
        elif ctx.get('evidence_cards_text'):
            all_evidence_cards.append(f'--- {year}-{m:02d} ---')
            all_evidence_cards.append(ctx['evidence_cards_text'])
        if ctx.get('research_synthesis_text'):
            all_research_synth.append(ctx['research_synthesis_text'])
        if ctx.get('graph_paths_text'):
            all_graph_lines.append(ctx['graph_paths_text'])
        if ctx.get('blog_context_text'):
            all_blog_lines.append(ctx['blog_context_text'])
        all_evidence_ids.extend(ctx.get('_evidence_ids', []))
        last_ctx = ctx

    merged_context['indicators_text'] = merged_context['indicators_text']
    merged_context['news_summary_text'] = '\n'.join(all_news_lines)
    merged_context['evidence_cards_text'] = '\n'.join(all_evidence_cards)
    merged_context['research_synthesis_text'] = '\n'.join(all_research_synth)
    merged_context['graph_paths_text'] = '\n'.join(all_graph_lines)
    merged_context['blog_context_text'] = '\n'.join(all_blog_lines)
    merged_context['_evidence_ids'] = all_evidence_ids
    merged_context['_quarterly'] = True
    merged_context['_quarter'] = quarter
    merged_context['_quarterly_months'] = months

    # Q-FIX-1 (2026-05-06): monthly run_market_debate 와 동일하게 wiki/graph/asset
    # trace + prompt text 를 merged_context 로 복사. wiki retrieval 은 _build_shared_context
    # 가 월별 1회씩 수행 — 마지막 월 (분기 end_month) 의 결과를 사용.
    # period filter 가 *분기 end_month + 1 월 이후* 를 자동 차단 (P1.5 적용).
    # 예: q=1 → 마지막 월=3 → wiki_period='2026-03' → 4/5월 page 제외, 1/2월 page 는
    # 과거 page 로 통과 (의도된 동작).
    if last_ctx is not None:
        merged_context['_wiki_trace'] = last_ctx.get('_wiki_trace', {})
        merged_context['_graph_trace'] = last_ctx.get('_graph_trace', {})
        merged_context['_asset_coverage'] = last_ctx.get('_asset_coverage', {})
        merged_context['wiki_context_text'] = last_ctx.get('wiki_context_text', '')
        merged_context['asset_coverage_text'] = last_ctx.get('asset_coverage_text', '')

    # R9-B.3 — quarterly wiki primary context (last month period_key 사용)
    merged_context['wiki_primary_context_text'] = wiki_primary_text_q
    merged_context['_wiki_context_pack'] = wcp_used_q
    merged_context['_prompt_context_mode'] = prompt_context_mode
    _record_context_source_trace(merged_context, policy)

    print(f'  컨텍스트 빌드 완료 (3개월 병합, sections: '
          f'{", ".join(active_sections(merged_context))})')

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

    # Q-FIX-1 (2026-05-06): monthly 와 동일한 _debug_trace + evidence_annotations 생성
    graph_trace = merged_context.get('_graph_trace') or {}
    wiki_trace = merged_context.get('_wiki_trace') or {}
    coverage = merged_context.get('_asset_coverage') or {}
    final_comment_text = (synthesis.get('customer_comment')
                          if isinstance(synthesis, dict) else '') or ''
    from market_research.report.asset_coverage import (
        REQUIRED_ASSET_CLASSES as _REQ, _scan_text_for_asset as _scan,
    )
    asset_mentions: dict[str, int] = {ac: _scan(final_comment_text, ac) for ac in _REQ}
    asset_pass = sum(1 for v in asset_mentions.values() if v > 0) >= 3
    ev_month_dist = _evidence_month_distribution(all_evidence_ids, year, months)

    debug_trace = {
        # quarterly 전용 metadata
        'debate_mode': 'quarterly',
        'period': f'{year}-Q{quarter}',
        'months': months,
        'evidence_ids_count': len(all_evidence_ids),
        'evidence_month_distribution': ev_month_dist,
        # monthly parity — graph
        'graph_paths_used_count': graph_trace.get('selected_path_count', 0),
        'graph_paths_used': graph_trace.get('selected_path_labels', []),
        'graph_paths_candidate_count': graph_trace.get('candidate_path_count', 0),
        # monthly parity — wiki
        'wiki_context_used_count': len(wiki_trace.get('wiki_selected_pages') or []),
        'wiki_context_pages': wiki_trace.get('wiki_selected_pages', []),
        'wiki_context_chars': wiki_trace.get('wiki_context_chars', 0),
        'wiki_retrieval_keywords': wiki_trace.get('wiki_retrieval_keywords', []),
        'wiki_skipped_short_pages': wiki_trace.get('wiki_skipped_short_pages', 0),
        'wiki_skipped_future_pages': wiki_trace.get('wiki_skipped_future_pages', 0),
        'wiki_skipped_cluster_cap': wiki_trace.get('wiki_skipped_cluster_cap', 0),
        'wiki_skipped_excluded': wiki_trace.get('wiki_skipped_excluded', 0),
        'wiki_excluded_dirs': wiki_trace.get('wiki_excluded_dirs', []),
        'wiki_excluded_dir_page_count': wiki_trace.get('wiki_excluded_dir_page_count', 0),
        'wiki_stage_used': wiki_trace.get('wiki_stage_used'),
        'wiki_period_used': wiki_trace.get('wiki_period_used'),
        # prompt 통계
        'prompt_graph_context_chars': len(merged_context.get('graph_paths_text') or ''),
        'prompt_wiki_context_chars': len(merged_context.get('wiki_context_text') or ''),
        'prompt_asset_coverage_chars': len(merged_context.get('asset_coverage_text') or ''),
        # asset coverage
        'dominant_topic': coverage.get('dominant_topic'),
        'covered_asset_classes': coverage.get('covered_asset_classes', []),
        'weak_asset_classes': coverage.get('weak_asset_classes', []),
        'missing_asset_classes': coverage.get('missing_asset_classes', []),
        'final_comment_asset_mentions': asset_mentions,
        'asset_coverage_pass': asset_pass,
        # R9-B.3 — quarterly wiki context pack trace
        'prompt_context_mode': prompt_context_mode,
        'wiki_context_pack_enabled': bool(use_wiki_context_pack),
        'wiki_primary_context_chars': len(wiki_primary_text_q or ''),
        'raw_validation_context_chars': (
            len(merged_context.get('news_summary_text') or '')
            + len(merged_context.get('indicators_text') or '')
            + len(merged_context.get('graph_paths_text') or '')
            + len(merged_context.get('wiki_context_text') or '')
            + len(merged_context.get('asset_coverage_text') or '')
        ),
        **{k: v for k, v in wcp_trace_fields.items()
           if k != 'wiki_context_pack_enabled'},
    }

    # evidence_annotations — debate_service 의 함수 재사용 (지연 import 로 circular 회피)
    try:
        from market_research.report.debate_service import build_evidence_annotations
        evidence_annotations = build_evidence_annotations(
            all_evidence_ids, year, months,
        )
    except Exception as exc:
        evidence_annotations = []
        print(f'  [경고] evidence_annotations 생성 실패: {exc}')

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
        'evidence_annotations': evidence_annotations,  # Q-FIX-1
        '_debug_trace': debug_trace,                    # Q-FIX-1
    }

    # R9-B.4.1 — monthly log schema 와 일치시켜 llm_calls 포함. 분기 비용
    # 추적이 가능하도록. monthly run_market_debate 와 동일 패턴.
    log_file = DEBATE_LOG_DIR / f'{year}-Q{quarter}.json'
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
