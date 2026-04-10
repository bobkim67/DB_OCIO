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
# 컨텍스트 빌더
# ===================================================================

def _build_shared_context(year: int, month: int, fund_code: str = None,
                          start_idx: int = 1) -> dict:
    """4인 에이전트 공유 컨텍스트 빌드. start_idx: evidence 번호 시작값 (분기 통번호용)"""
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

        # 주요 뉴스: diversity guardrail (토픽별 상한 5건, event_group 상한 2건)
        # + 당일 기사 슬롯 (TIER1 매체 최대 2건 보장)
        from datetime import date as _date
        today_str = _date.today().isoformat()

        candidates = sorted(
            [a for a in primary_classified if a.get('intensity', 0) >= 6],
            key=lambda x: (-x.get('_event_salience', 0), -x.get('intensity', 0)),
        )
        high_impact = []
        topic_count = {}   # topic → 선발 수
        event_count = {}   # event_group_id → 선발 수
        MAX_PER_TOPIC = 5
        MAX_PER_EVENT = 2
        TARGET = 15
        LATEST_SLOT = 2    # 당일 기사 전용 슬롯

        # Phase 1: 당일 TIER1/TIER2 기사 우선 배정
        _tier1_sources = {'Reuters', 'Bloomberg', 'AP', 'Financial Times', 'WSJ',
                          'CNBC', 'MarketWatch', '연합뉴스', '연합뉴스TV', '뉴시스', '뉴스1'}
        _tier2_partial = {'헤럴드경제', '매일경제', '한경', '서울경제', '머니투데이', '이데일리', 'SBS'}
        latest_candidates = sorted(
            [a for a in candidates if a.get('date', '') == today_str],
            key=lambda x: (-x.get('_event_salience', 0)),
        )
        latest_added_ids = set()
        for a in latest_candidates:
            if len(high_impact) >= LATEST_SLOT:
                break
            src = a.get('source', '')
            is_authoritative = src in _tier1_sources or any(t2 in src for t2 in _tier2_partial)
            if not is_authoritative:
                continue
            high_impact.append(a)
            latest_added_ids.add(a.get('_article_id', ''))
            topic = a.get('primary_topic', '')
            topic_count[topic] = topic_count.get(topic, 0) + 1
            egid = a.get('_event_group_id', '')
            if egid:
                event_count[egid] = event_count.get(egid, 0) + 1

        # Phase 2: 나머지 salience 순 (기존 로직)
        for a in candidates:
            if len(high_impact) >= TARGET:
                break
            if a.get('_article_id', '') in latest_added_ids:
                continue
            topic = a.get('primary_topic', '')
            egid = a.get('_event_group_id', '')
            if topic_count.get(topic, 0) >= MAX_PER_TOPIC:
                continue
            if egid and event_count.get(egid, 0) >= MAX_PER_EVENT:
                continue
            high_impact.append(a)
            topic_count[topic] = topic_count.get(topic, 0) + 1
            if egid:
                event_count[egid] = event_count.get(egid, 0) + 1

        if high_impact:
            n_topics = len(set(a.get('primary_topic', '') for a in high_impact))
            lines.append(f'\n주요 뉴스 ({len(high_impact)}건, {n_topics}개 토픽, diversity 적용):')
            for idx, a in enumerate(high_impact, start_idx):
                sal = a.get('_event_salience', 0)
                aid = a.get('_article_id', '')
                src_cnt = a.get('_event_source_count', 1)
                corr = f', 교차보도:{src_cnt}건' if src_cnt >= 2 else ''
                lines.append(
                    f'  [ref:{idx}] [{a.get("primary_topic","")}] {a.get("title","")[:80]} '
                    f'({a.get("source","")}, {a.get("date","")}) [sal:{sal}{corr}]')
                if aid:
                    evidence_ids.append(aid)
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

    # GraphRAG 전이경로
    graph_file = BASE_DIR / 'data' / 'insight_graph' / f'{year}-{month:02d}.json'
    if graph_file.exists():
        graph = json.loads(graph_file.read_text(encoding='utf-8'))
        paths = graph.get('transmission_paths', [])
        if paths:
            lines = ['주요 전이경로:']
            for p in paths[:10]:
                labels = p.get('path_labels', p.get('path', []))
                conf = p.get('confidence', 0)
                lines.append(f'  {" -> ".join(labels[:5])} (신뢰도 {conf})')
            context['graph_paths_text'] = '\n'.join(lines)

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

    return context


def _build_agent_prompt(agent_type: str, context: dict) -> str:
    """에이전트별 프롬프트 생성"""
    shared = (
        f'## {context["year"]}년 {context["month"]}월 시장 분석\n\n'
        f'{context.get("news_summary_text", "(뉴스 데이터 없음)")}\n\n'
        f'{context.get("indicators_text", "(지표 데이터 없음)")}\n\n'
        f'{context.get("timeseries_narrative_text", "")}\n\n'
        f'{context.get("graph_paths_text", "")}\n'
    )

    if agent_type == 'monygeek':
        shared += (
            f'\n## 블로거 분석 프레임워크\n'
            f'{context.get("blog_context_text", "(블로그 데이터 없음)")}\n'
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
    system_msg = '당신은 기관 투자자를 위한 글로벌 매크로 시장 분석 전문가입니다.'

    # ── Step 1: 고객용 매크로 코멘트 (Opus) ──
    target_month = f'{context["year"]}년 {context["month"]}월'
    comment_prompt = (
        '4명의 분석가가 각각 다른 시각에서 시장을 분석했습니다.\n\n'
        f'## 분석가별 의견\n{debate_text}\n\n'
        '## 문서 성격\n'
        f'이 문서는 "{target_month} 매크로 시장 브리핑"입니다.\n'
        f'반드시 "{target_month}" 기준으로 작성하세요. 다른 월을 언급하지 마세요.\n'
        '특정 펀드의 운용보고가 아닌, 글로벌/국내 거시환경 분석문입니다.\n\n'
        '## 문단 구조 (반드시 이 순서로 3~4문단 작성)\n'
        '1문단: 월중 핵심 변화 — 시장을 움직인 가장 큰 변수 1~2개, 주요 자산 반응\n'
        '2문단: 안도와 리스크의 공존 — 단기 완화 요인과 중기 구조적 불확실성 균형 서술\n'
        '3문단: 금리/환율/유동성 해석 — 통화정책 딜레마, 금리 구조, 환율 방향성\n'
        '4문단: 향후 체크포인트 — 확인해야 할 변수 나열로 마무리 (투자 액션 금지)\n\n'
        '## 작성 규칙\n'
        '1. 기관 고객용 전문적이고 절제된 톤, 경어체.\n'
        '2. 크로스 자산 인과관계로 연결 (자산별 개별 나열 금지).\n'
        '3. 숫자 사용 시 반드시 단위와 의미를 명확히 (%, 달러, 원, bp 등).\n'
        '4. 분석가 의견이 상충하면 한쪽을 채택하지 말고 조건부 문장으로 서술.\n'
        '   예: "단기 안도와 중기 불확실성이 병존하는 구도"\n'
        '5. 마지막 문단은 반드시 "향후 관찰 변수"로 끝낼 것. 투자 액션으로 끝내지 말 것.\n\n'
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
        '## 필수: 출처 태그\n'
        '뉴스에서 가져온 사실을 언급할 때 해당 문장 끝에 [ref:N] 태그를 붙이세요.\n'
        '위 "주요 뉴스" 목록에 [ref:1], [ref:2], ... 식별자가 이미 붙어 있습니다.\n'
        '해당 식별자를 그대로 복사하세요. 번호를 재해석하거나 임의 부여하지 마세요.\n'
        '목록에 없는 ref 번호를 만들지 마세요.\n'
        '문장 내용과 직접 관련된 기사에만 ref를 붙이세요. 확신이 없으면 ref를 생략하세요.\n'
        '최소 3개 이상의 [ref:N] 태그를 포함하세요.\n\n'
        '순수 텍스트만 출력하세요.\n'
        '문단 사이에 반드시 빈 줄(\\n\\n)을 넣어 구분하세요.'
    )

    customer_comment = ''
    try:
        customer_comment = _call_llm(
            model='claude-opus-4-6',
            system=system_msg,
            prompt=comment_prompt,
            max_tokens=2000,
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


def _update_regime_memory(agent_responses: dict, year: int, month: int):
    """에이전트 합의에서 Haiku로 지배적 내러티브 추출 -> regime 업데이트"""
    regime = _load_regime_memory()

    # 4인의 key_points를 Haiku로 요약하여 지배적 내러티브 추출
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
                log_label='regime_narrative',
            ).strip('"\'').strip()
        except Exception:
            new_narrative = '분석 중'

    current = regime.get('current', {})
    prev_narrative = current.get('dominant_narrative', '')

    date_str = f'{year}-{month:02d}'
    if prev_narrative and prev_narrative != new_narrative:
        regime['previous'] = {
            'dominant_narrative': prev_narrative,
            'ended': date_str,
        }
        regime['shift_detected'] = True
        regime['shift_description'] = f'{prev_narrative} -> {new_narrative}'
        regime['history'].append({
            'narrative': prev_narrative,
            'period': f'{current.get("since", "?")} ~ {date_str}',
        })
        regime['current'] = {
            'dominant_narrative': new_narrative,
            'weeks': 1,
            'since': date_str,
        }
    else:
        regime['current']['dominant_narrative'] = new_narrative
        regime['current']['weeks'] = current.get('weeks', 0) + 1
        if not regime['current'].get('since'):
            regime['current']['since'] = date_str
        regime['shift_detected'] = False

    regime['history'] = regime['history'][-12:]

    REGIME_FILE.write_text(json.dumps(regime, ensure_ascii=False, indent=2), encoding='utf-8')
    return regime


# ===================================================================
# 메인: Debate 실행
# ===================================================================

def run_market_debate(year: int, month: int) -> dict:
    """
    시장 전체 debate (월 1회, 펀드 무관).
    4인 에이전트 병렬 실행 -> Opus 2단계 종합 -> 자산군별 분석 결과.
    펀드별 캐시에서는 이 결과를 참조하여 보유 비중에 맞는 코멘트만 사용.
    """
    print(f'\n-- Market Debate: {year}-{month:02d} --')

    context = _build_shared_context(year, month)
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

    # Regime memory 업데이트
    regime = _update_regime_memory(agent_responses, year, month)
    if regime.get('shift_detected'):
        print(f'  레짐 전환 감지: {regime["shift_description"]}')
    else:
        print(f'  레짐: {regime["current"]["dominant_narrative"]}')

    # Opus 종합 (시장 전체)
    print(f'  Opus 종합 중...')
    synthesis = _synthesize_debate(agent_responses, None, context)
    print(f'  종합 완료')

    result = {
        'year': year,
        'month': month,
        'debated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'agents': agent_responses,
        'synthesis': synthesis,
        'regime': regime,
        '_evidence_ids': context.get('_evidence_ids', []),
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


def run_quarterly_debate(year: int, quarter: int) -> dict:
    """
    분기 통합 debate.
    해당 분기 3개월의 뉴스/지표를 종합하여 debate 실행.
    """
    months = [(quarter - 1) * 3 + i for i in range(1, 4)]
    print(f'\n-- Quarterly Debate: {year}Q{quarter} ({months[0]}~{months[2]}월) --')

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

    for m in months:
        ctx = _build_shared_context(year, m, start_idx=next_idx)
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

    regime = _update_regime_memory(agent_responses, year, months[-1])
    if regime.get('shift_detected'):
        print(f'  레짐 전환 감지: {regime["shift_description"]}')

    print(f'  Opus 종합 중...')
    synthesis = _synthesize_debate(agent_responses, None, merged_context)
    print(f'  종합 완료')

    result = {
        'year': year,
        'quarter': quarter,
        'months': months,
        'debated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'agents': agent_responses,
        'synthesis': synthesis,
        'regime': regime,
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
