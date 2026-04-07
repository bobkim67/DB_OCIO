# -*- coding: utf-8 -*-
"""
DEPRECATED: report_cli.py로 대체됨. 아래 명령어를 사용하세요:
    python -m market_research.report_cli build 07G04 -q 1 -y 2026
    python -m market_research.report_cli build 07G04 -q 1 --edit

(기존 코드는 참조용으로 유지)

기존 Usage:
    python -m market_research.report_interview 07G04 --quarter 1 --year 2026
"""

import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import anthropic

BASE_DIR = Path(__file__).resolve().parent
COMMENTS_DIR = BASE_DIR.parent / 'comments'
OUTPUT_DIR = BASE_DIR / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

from market_research.comment_engine import (
    load_benchmark_returns_quarter,
    load_fund_return_quarter,
    load_all_pa_attributions_quarter,
    load_fund_holdings_summary,
    load_digest,
    _quarter_dates,
    FUND_CONFIGS,
    _SAMPLE_REPORTS,
    ANTHROPIC_API_KEY,
)

# insight-engine 워크트리 경로 (debate_engine 임포트용)
_INSIGHT_DIR = BASE_DIR.parent.parent / 'DB_OCIO_Webview_insight'

# 동일 펀드 관련 코드 매핑 (약식 보고서 등)
_RELATED_FUNDS = {
    '07G04': ['07G07'],
    '07G07': ['07G04'],
}


# ═══════════════════════════════════════════════════════
# Step 1: 데이터 로딩 + 요약
# ═══════════════════════════════════════════════════════

def _compute_holdings_diff(start, end, threshold=2.0):
    """분기초/분기말 비중 비교. threshold(%) 이상만 반환."""
    all_classes = set(list(start.keys()) + list(end.keys()))
    diffs = []
    for ac in sorted(all_classes):
        prev = start.get(ac, 0)
        cur = end.get(ac, 0)
        change = cur - prev
        if abs(change) >= threshold:
            diffs.append({
                'asset_class': ac,
                'prev': round(prev, 1),
                'cur': round(cur, 1),
                'change': round(change, 1),
                'direction': '확대' if change > 0 else '축소',
            })
    diffs.sort(key=lambda x: -abs(x['change']))
    return diffs


def step1_load_and_summarize(fund_code, year, quarter):
    """분기 데이터 로딩 → 콘솔 요약 출력."""
    start_month, end_month = _quarter_dates(year, quarter)

    print(f'\n{"═" * 56}')
    print(f'  {year}년 {quarter}분기 | {fund_code} | 포맷 {FUND_CONFIGS.get(fund_code, {}).get("format", "?")}')
    print(f'{"═" * 56}')

    # BM
    print('\n  데이터 로딩 중...', end='', flush=True)
    bm = load_benchmark_returns_quarter(year, quarter)
    print(' BM', end='', flush=True)

    # 펀드 수익률
    fund_ret = load_fund_return_quarter(fund_code, year, quarter)
    print(' 펀드', end='', flush=True)

    # PA
    pa = load_all_pa_attributions_quarter([fund_code], year, quarter).get(fund_code, {})
    print(' PA', end='', flush=True)

    # 비중변화
    holdings_start = load_fund_holdings_summary(fund_code, year, start_month)
    holdings_end = load_fund_holdings_summary(fund_code, year, end_month)
    holdings_diff = _compute_holdings_diff(holdings_start, holdings_end)
    print(' 비중 완료\n')

    # ── BM 출력 ──
    print('── 벤치마크 분기 수익률 ──')
    bm_display = ['S&P500', 'KOSPI', '미국성장주', '미국가치주', '미국외선진국', '신흥국주식',
                   '미국종합채권', 'KAP종합채권', 'KRX10년채권', 'Gold', 'WTI', 'DXY', 'USDKRW']
    for name in bm_display:
        info = bm.get(name, {})
        ret = info.get('return')
        level = info.get('level')
        if ret is not None:
            lv = f'  (수준 {level:,.1f})' if level else ''
            print(f'  {name:16s} {ret:+7.2f}%{lv}')

    # ── 펀드 성과 ──
    print('\n── 펀드 성과 ──')
    if fund_ret:
        print(f'  분기수익률: {fund_ret["return"]:+.2f}%')
        if fund_ret.get('sub_returns'):
            parts = [f'{k}: {v:+.2f}%' for k, v in fund_ret['sub_returns'].items()]
            print(f'  서브: {", ".join(parts)}')

    # ── PA ──
    print('\n── PA 기여도 ──')
    for cls in ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', '유동성', '보수비용']:
        if cls in pa and abs(pa[cls]) >= 0.01:
            print(f'  {cls:8s} {pa[cls]:+6.2f}%')

    # ── 비중변화 ──
    if holdings_diff:
        print('\n── 비중 변화 (2%p 이상) ──')
        for d in holdings_diff:
            arrow = '▲' if d['change'] > 0 else '▼'
            print(f'  {d["asset_class"]:8s} {d["prev"]:5.1f}% → {d["cur"]:5.1f}% ({d["change"]:+.1f}%p {arrow})')
    else:
        print('\n── 비중 변화: 유의미한 변동 없음 ──')

    return {
        'bm': bm, 'fund_ret': fund_ret, 'pa': pa,
        'holdings_start': holdings_start, 'holdings_end': holdings_end,
        'holdings_diff': holdings_diff,
    }


# ═══════════════════════════════════════════════════════
# Step 2: 과거 코멘트 + 뉴스/블로그 하이라이트
# ═══════════════════════════════════════════════════════

def _load_past_comments(fund_code, year, quarter):
    """과거 코멘트 로드 — 해당 펀드 + 관련 펀드."""
    codes = [fund_code] + _RELATED_FUNDS.get(fund_code, [])
    comments = []
    for code in codes:
        for f in sorted(COMMENTS_DIR.glob(f'{code}_*')):
            try:
                text = f.read_text(encoding='utf-8')
                comments.append({'file': f.name, 'code': code, 'text': text})
            except Exception:
                pass
    return comments


def _get_quarter_comments(comments, year, quarter):
    """분기 내 월별 코멘트 필터."""
    start_month, end_month = _quarter_dates(year, quarter)
    result = []
    for c in comments:
        name = c['file']
        # 월별: 07G04_202601 → year=2026, month=01
        if len(name.split('_')[1]) == 6:
            try:
                y = int(name.split('_')[1][:4])
                m = int(name.split('_')[1][4:6])
                if y == year and start_month <= m <= end_month:
                    result.append(c)
            except ValueError:
                pass
        # 분기별: 2JM23_20254Q
        elif 'Q' in name.split('_')[1]:
            try:
                y = int(name.split('_')[1][:4])
                q = int(name.split('_')[1][4])
                if y == year and q == quarter:
                    result.append(c)
            except (ValueError, IndexError):
                pass
    return result


def _merge_quarter_digests(year, quarter):
    """3개월 digest 통합 → 토픽 단위 요약 하이라이트."""
    start_month, end_month = _quarter_dates(year, quarter)
    # 토픽별 월간 정보 수집
    topic_data = {}  # topic → {months, direction, claims, events, corr_score, corr_news_count}

    for m in range(start_month, end_month + 1):
        digest = load_digest(year, m)
        if not digest:
            continue

        enriched_file = BASE_DIR / 'data' / 'enriched_digests' / f'{year}-{m:02d}.json'
        enriched = None
        if enriched_file.exists():
            try:
                enriched = json.loads(enriched_file.read_text(encoding='utf-8'))
            except Exception:
                pass

        topics = (enriched or digest).get('topics', {})
        for topic, info in topics.items():
            if topic not in topic_data:
                topic_data[topic] = {
                    'months': [], 'directions': [],
                    'claims': [], 'events': [],
                    'corr_scores': [], 'corr_news_total': 0,
                }
            td = topic_data[topic]
            td['months'].append(m)
            td['directions'].append(info.get('direction', ''))
            # 이벤트/주장 중 구체적인 것만 (숫자/고유명사 포함)
            for claim in info.get('key_claims', [])[:3]:
                if 20 < len(claim) < 120 and any(c.isdigit() or c == '%' for c in claim):
                    td['claims'].append(claim)
            for event in info.get('key_events', [])[:2]:
                if 20 < len(event) < 120:
                    td['events'].append(event)
            if enriched:
                corr = info.get('corroboration_score', 0)
                td['corr_scores'].append(corr)
                td['corr_news_total'] += len(info.get('corroborating_news', []))

    # 토픽별 1줄 요약 생성
    highlights = []
    for topic, td in topic_data.items():
        freq = len(td['months'])
        avg_corr = sum(td['corr_scores']) / len(td['corr_scores']) if td['corr_scores'] else 0

        # 방향 판단 (최빈)
        dirs = [d for d in td['directions'] if d]
        direction = max(set(dirs), key=dirs.count) if dirs else ''

        # 대표 텍스트: 가장 구체적인 이벤트 또는 claim 1개
        best = ''
        for e in td['events']:
            if len(e) > len(best):
                best = e
        if not best:
            for c in td['claims']:
                if len(c) > len(best):
                    best = c
        if not best:
            best = f'{topic} 관련 동향'

        # 요약 라인
        dir_tag = f' ({direction})' if direction else ''
        summary = f'{best}'

        highlights.append({
            'text': summary,
            'topic': topic,
            'direction': direction,
            'type': '토픽요약',
            'freq': freq,
            'corr_score': avg_corr,
            'corr_news_count': td['corr_news_total'],
            'claims': td['claims'][:3],  # 보조 상세
            'events': td['events'][:3],
        })

    # 정렬: 반복 빈도 → 교차검증 점수
    highlights.sort(key=lambda x: (-x['freq'], -x['corr_score']))
    return highlights[:15]


def step2_highlights(fund_code, year, quarter):
    """과거 코멘트 + 뉴스/블로그 하이라이트 출력 → 선택."""
    # 과거 코멘트
    all_comments = _load_past_comments(fund_code, year, quarter)
    quarter_comments = _get_quarter_comments(all_comments, year, quarter)

    print(f'\n── 과거 코멘트 ({len(all_comments)}건 로드, 분기 내 {len(quarter_comments)}건) ──')
    for c in quarter_comments[:3]:
        preview = c['text'][:80].replace('\n', ' ')
        print(f'  [{c["file"]}] {preview}...')

    # 직전 분기 코멘트 (few-shot용)
    prev_q = quarter - 1 if quarter > 1 else 4
    prev_y = year if quarter > 1 else year - 1
    prev_comments = _get_quarter_comments(all_comments, prev_y, prev_q)

    # 뉴스/블로그 하이라이트
    highlights = _merge_quarter_digests(year, quarter)

    if highlights:
        print(f'\n── 뉴스/블로그 하이라이트 ({quarter}분기, 토픽별 요약) ──')
        for i, h in enumerate(highlights, 1):
            corr = f' | 뉴스 {h["corr_news_count"]}건 교차검증' if h['corr_news_count'] > 0 else ''
            freq_tag = f' | {h["freq"]}개월 연속' if h['freq'] >= 2 else ''
            dir_tag = f' ({h["direction"]})' if h.get('direction') else ''
            star = '★' if h['freq'] >= 3 or h['corr_score'] > 0.4 else ' '
            print(f'  {star}{i:2d}. [{h["topic"]}]{dir_tag} {h["text"][:65]}{freq_tag}{corr}')
            # 보조 상세 (있으면 1줄만)
            details = h.get('claims', []) + h.get('events', [])
            if details:
                detail = details[0][:70]
                print(f'       └ {detail}')

        print(f'\n  반영할 항목 선택 (번호, 쉼표 구분 / Enter=전체 / 0=없음): ', end='')
        choice = input().strip()
        if choice == '0':
            selected = []
        elif choice == '':
            selected = highlights
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(',') if x.strip().isdigit()]
                selected = [highlights[i] for i in indices if 0 <= i < len(highlights)]
            except (ValueError, IndexError):
                selected = highlights
    else:
        print('\n── 뉴스/블로그 하이라이트: 없음 ──')
        selected = []

    return {
        'all_comments': all_comments,
        'quarter_comments': quarter_comments,
        'prev_comments': prev_comments,
        'selected_highlights': selected,
        'all_highlights': highlights,
    }


# ═══════════════════════════════════════════════════════
# Debate 연동
# ═══════════════════════════════════════════════════════

def _run_debate_for_quarter(fund_code, year, quarter):
    """debate 엔진 실행 → 분기 마지막 월 기준."""
    _, end_month = _quarter_dates(year, quarter)
    try:
        # insight 워크트리에서 debate_engine 임포트
        import importlib.util
        debate_path = _INSIGHT_DIR / 'market_research' / 'debate_engine.py'
        if not debate_path.exists():
            print(f'  [경고] debate_engine.py 없음: {debate_path}')
            return None
        spec = importlib.util.spec_from_file_location('debate_engine', debate_path)
        mod = importlib.util.module_from_spec(spec)
        # insight 워크트리의 market_research를 path에 추가 (의존성 해결)
        if str(_INSIGHT_DIR) not in sys.path:
            sys.path.insert(0, str(_INSIGHT_DIR))
        spec.loader.exec_module(mod)
        print(f'\n  debate 실행 중 ({year}-{end_month:02d})...', flush=True)
        result = mod.run_market_debate(year, end_month)
        print(f'  debate 완료')
        return result
    except Exception as e:
        print(f'  [경고] debate 실행 실패: {e}')
        return None


def _debate_to_default_answers(debate_result):
    """debate 결과 → 인터뷰 기본답변 dict 변환."""
    if not debate_result:
        return {}

    syn = debate_result.get('synthesis', {})
    agents = debate_result.get('agents', {})

    defaults = {}

    # Q1 시장판단: customer_comment에서 시장 분석 부분
    comment = syn.get('customer_comment', '')
    if comment:
        # 앞 500자를 시장판단으로
        defaults['market_view'] = comment[:500]

    # 합의점 + 쟁점을 전망/리스크에 활용
    consensus = syn.get('consensus_points', [])
    disagreements = syn.get('disagreements', [])

    if consensus:
        defaults['outlook'] = ' '.join(consensus[:3])

    if disagreements:
        risk_parts = []
        for d in disagreements[:3]:
            if isinstance(d, dict):
                topic = d.get('topic', '')
                bear = d.get('bear', '')
                risk_parts.append(f'{topic}: {bear}')
            else:
                risk_parts.append(str(d))
        defaults['risk'] = ' '.join(risk_parts)

    # 에이전트별 핵심 포인트를 추가 정보로
    for agent_key in ['Bull', 'Bear', 'Quant', 'monygeek']:
        agent = agents.get(agent_key, {})
        key_points = agent.get('key_points', [])
        if key_points and agent_key == 'monygeek':
            # monygeek의 유로달러 관점은 추가사항으로
            defaults['additional'] = ' '.join(key_points[:2])

    return defaults


def step2_highlights_auto(fund_code, year, quarter):
    """비대화형 — 하이라이트 전체 선택, input() 없음."""
    all_comments = _load_past_comments(fund_code, year, quarter)
    quarter_comments = _get_quarter_comments(all_comments, year, quarter)
    prev_q = quarter - 1 if quarter > 1 else 4
    prev_y = year if quarter > 1 else year - 1
    prev_comments = _get_quarter_comments(all_comments, prev_y, prev_q)
    highlights = _merge_quarter_digests(year, quarter)

    print(f'\n── 과거 코멘트 ({len(all_comments)}건 로드) ──')
    print(f'── 뉴스/블로그 하이라이트 ({len(highlights)}건, 전체 선택) ──')

    return {
        'all_comments': all_comments,
        'quarter_comments': quarter_comments,
        'prev_comments': prev_comments,
        'selected_highlights': highlights,
        'all_highlights': highlights,
    }


# ═══════════════════════════════════════════════════════
# Step 3: 인터뷰
# ═══════════════════════════════════════════════════════

def _find_topic_reason(highlights, topic_keywords):
    """하이라이트에서 토픽 키워드 매칭 → 원인 텍스트 + 건수."""
    for h in highlights:
        if h['topic'] in topic_keywords:
            news_tag = f' (뉴스 {h["corr_news_count"]}건)' if h.get('corr_news_count', 0) > 0 else ''
            freq_tag = f' [{h["freq"]}개월]' if h.get('freq', 0) >= 2 else ''
            return h['text'][:50] + news_tag + freq_tag
    return ''


def _build_data_driven_candidates(data_ctx, highlight_ctx, question_type):
    """현 분기 데이터 + 뉴스/블로그 원인을 결합한 객관식 후보."""
    bm = data_ctx.get('bm', {})
    pa = data_ctx.get('pa', {})
    highlights = highlight_ctx.get('all_highlights', [])
    candidates = []

    if question_type == 'market':
        # ── 주식: 수치 + 원인 ──
        kospi = bm.get('KOSPI', {}).get('return')
        reason_kr = _find_topic_reason(highlights, ['한국_원화', 'AI_반도체'])
        if kospi is not None:
            reason = reason_kr or '국내 시장 동향'
            candidates.append(f'[주식/국내] KOSPI {kospi:+.1f}% — {reason}')

        growth = bm.get('미국성장주', {}).get('return')
        reason_us = _find_topic_reason(highlights, ['AI_반도체', '관세'])
        if growth is not None:
            reason = reason_us or '미국 성장주 동향'
            candidates.append(f'[주식/해외] 미국성장주 {growth:+.1f}% — {reason}')

        value = bm.get('미국가치주', {}).get('return')
        if growth is not None and value is not None and abs(growth - value) > 3:
            candidates.append(f'[주식/스타일] 성장 {growth:+.1f}% vs 가치 {value:+.1f}% 차별화')

        # ── 채권: 수치 + 원인 ──
        krx10 = bm.get('KRX10년채권', {}).get('return')
        us_bond = bm.get('미국종합채권', {}).get('return')
        reason_bond = _find_topic_reason(highlights, ['금리', '물가', '유로달러'])
        if krx10 is not None:
            reason = reason_bond or '금리 동향'
            candidates.append(f'[채권] KRX10Y {krx10:+.1f}%, 미국 {us_bond:+.1f}% — {reason}')

        # ── 원자재: 수치 + 원인 ──
        wti = bm.get('WTI', {}).get('return')
        gold = bm.get('Gold', {}).get('return')
        reason_oil = _find_topic_reason(highlights, ['유가_에너지'])
        reason_gold = _find_topic_reason(highlights, ['금', '안전자산'])
        if wti is not None:
            reason = reason_oil or '에너지 시장'
            candidates.append(f'[원자재/유가] WTI {wti:+.1f}% — {reason}')
        if gold is not None:
            reason = reason_gold or '안전자산 수요'
            candidates.append(f'[원자재/금] 금 {gold:+.1f}% — {reason}')

        # ── 통화: 수치 + 원인 ──
        usdkrw = bm.get('USDKRW', {}).get('return')
        reason_fx = _find_topic_reason(highlights, ['달러', '한국_원화'])
        if usdkrw is not None:
            won_dir = '원화약세' if usdkrw > 0 else '원화강세'
            reason = reason_fx or '환율 동향'
            candidates.append(f'[통화] USD/KRW {usdkrw:+.1f}%({won_dir}) — {reason}')

    elif question_type == 'outlook':
        # 전망: 블로그 테마 + PA 방향
        outlook_topics = ['금리', '달러', '물가', '유가_에너지', 'AI_반도체', '한국_원화']
        for h in highlights:
            if h['topic'] in outlook_topics:
                news_tag = f' (뉴스 {h["corr_news_count"]}건)' if h.get('corr_news_count', 0) > 0 else ''
                candidates.append(f'[{h["topic"]}] {h["text"][:55]}{news_tag}')
        for cls in ['국내주식', '해외주식', '국내채권']:
            if cls in pa and abs(pa[cls]) >= 0.3:
                direction = '긍정' if pa[cls] > 0 else '부정'
                candidates.append(f'[기여도] {cls} {pa[cls]:+.2f}% — {direction}적 요인 지속?')

    elif question_type == 'risk':
        # 리스크: 데이터 이상치 + 블로그 경고
        wti = bm.get('WTI', {}).get('return')
        usdkrw = bm.get('USDKRW', {}).get('return')
        if wti and wti > 20:
            reason = _find_topic_reason(highlights, ['유가_에너지']) or '에너지 공급 충격'
            candidates.append(f'[유가] WTI {wti:+.1f}% → {reason}')
        if usdkrw and usdkrw > 3:
            reason = _find_topic_reason(highlights, ['한국_원화', '달러']) or '원화 절하 압력'
            candidates.append(f'[환율] 원화 {usdkrw:+.1f}% 약세 → {reason}')
        risk_topics = ['관세', '안전자산', '중국_위안화', '엔화_캐리', '물가']
        for h in highlights:
            if h['topic'] in risk_topics:
                news_tag = f' (뉴스 {h["corr_news_count"]}건)' if h.get('corr_news_count', 0) > 0 else ''
                candidates.append(f'[{h["topic"]}] {h["text"][:55]}{news_tag}')
        for cls, v in sorted(pa.items(), key=lambda x: x[1]):
            if v < -0.5:
                candidates.append(f'[손실] {cls} {v:+.2f}% — 추가 하락 가능성?')

    return candidates[:8]


def _build_history_summary(data_ctx, highlight_ctx, fund_code, year, quarter):
    """Q5 히스토리: 비중변화 + 수익률 + 이슈를 자동 분석."""
    lines = []

    # 비중변화
    diffs = data_ctx.get('holdings_diff', [])
    if diffs:
        lines.append('[비중변화]')
        for d in diffs:
            lines.append(f'  {d["asset_class"]}: {d["prev"]}% → {d["cur"]}% ({d["change"]:+.1f}%p)')

    # PA 기여도 상위/하위
    pa = data_ctx.get('pa', {})
    sorted_pa = sorted(pa.items(), key=lambda x: x[1], reverse=True)
    if sorted_pa:
        best = sorted_pa[0]
        worst = sorted_pa[-1]
        lines.append(f'[기여도] 최대: {best[0]} {best[1]:+.2f}%, 최소: {worst[0]} {worst[1]:+.2f}%')

    # 전분기 코멘트에서 포지션 키워드 추출
    prev_comments = highlight_ctx.get('prev_comments', [])
    if prev_comments:
        prev_text = prev_comments[-1]['text']
        # OW/UW, 확대/축소, 전환 키워드 추출
        position_kw = ['OW', 'UW', '확대', '축소', '전환', '듀레이션', '바벨', '비중']
        prev_positions = []
        for line in prev_text.split('\n'):
            line = line.strip()
            if any(kw in line for kw in position_kw) and 15 < len(line) < 150:
                clean = line.lstrip('①②③④⑤ㅇ-·\t □')
                if clean and len(clean) > 10:
                    prev_positions.append(clean[:80])
        if prev_positions:
            lines.append('[전분기 포지션]')
            for p in prev_positions[:4]:
                lines.append(f'  {p}')

    # BM 수익률 핵심
    bm = data_ctx.get('bm', {})
    bm_summary = []
    for name in ['KOSPI', 'S&P500', '미국성장주', 'KAP종합채권', 'Gold', 'WTI', 'USDKRW']:
        ret = bm.get(name, {}).get('return')
        if ret is not None:
            bm_summary.append(f'{name} {ret:+.1f}%')
    if bm_summary:
        lines.append(f'[분기 BM] {", ".join(bm_summary)}')

    return '\n'.join(lines)


def _ask_question(q_id, category, question, candidates=None, default=None):
    """단일 질문 — 객관식 후보 + 주관식 입력 + debate 기본답변."""
    print(f'\n[{q_id}] {category}')
    print(f'  {question}')

    if default:
        print(f'\n  [debate 분석]')
        for line in default[:300].split('\n'):
            if line.strip():
                print(f'  │ {line.strip()}')
        if len(default) > 300:
            print(f'  │ ... ({len(default)}자)')

    if candidates:
        print(f'\n  [참고 데이터]')
        for i, c in enumerate(candidates, 1):
            print(f'    [{i}] {c}')

    if default:
        print(f'\n  Enter=debate 채택 / 수정 입력 / 번호+추가: ', end='')
    elif candidates:
        print(f'\n  번호 선택 + 추가 입력 (예: 1,3 추가의견) / Enter=스킵: ', end='')
    else:
        print(f'  → (Enter=스킵): ', end='')

    raw = input().strip()
    if not raw:
        return default  # debate 있으면 채택, 없으면 None

    if not candidates:
        return raw

    # 번호 + 주관식 파싱
    parts = raw.split(' ', 1)
    nums_part = parts[0]
    free_text = parts[1] if len(parts) > 1 else ''

    selected_texts = []
    for token in nums_part.split(','):
        token = token.strip()
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(candidates):
                selected_texts.append(candidates[idx])
        else:
            free_text = token + ' ' + free_text

    result = '. '.join(selected_texts)
    if free_text.strip():
        result = (result + '. ' if result else '') + free_text.strip()
    return result if result else None


def step3_interview(data_ctx, highlight_ctx, fund_code='', year=2026, quarter=1, debate_defaults=None):
    """인터뷰 실행 → 응답 수집. debate_defaults가 있으면 기본답변으로 제시."""
    print(f'\n{"─" * 56}')
    if debate_defaults:
        print('  인터뷰 시작 (debate 분석 → 확인/수정 모드)')
        print('  Enter=debate 답변 채택, 텍스트=수정/보충')
    else:
        print('  인터뷰 시작 (Enter=스킵, 번호=선택, 텍스트=직접입력)')
    print(f'{"─" * 56}')

    dd = debate_defaults or {}
    answers = {}

    # Q1: 시장 판단
    candidates = _build_data_driven_candidates(data_ctx, highlight_ctx, 'market')
    answers['market_view'] = _ask_question(
        'Q1', '시장판단 (주식/채권/원자재/통화)',
        '당분기 시장에 대한 판단과 근거는?',
        candidates, default=dd.get('market_view')
    )

    # Q2: 포지션 변경 근거 (비중변화 일괄)
    diffs = data_ctx.get('holdings_diff', [])
    if diffs:
        diff_desc = ', '.join(f'{d["asset_class"]} {d["change"]:+.1f}%p' for d in diffs)
        answers['position_rationale'] = _ask_question(
            'Q2', '포지션근거',
            f'분기 중 비중 변화: {diff_desc} — 변경 근거는?',
            default=dd.get('position_rationale')
        )
    else:
        answers['position_rationale'] = _ask_question(
            'Q2', '포지션근거',
            '분기 중 포지션 변경이나 전략 변화가 있었다면?',
            default=dd.get('position_rationale')
        )

    # Q3: 전망/테마
    candidates = _build_data_driven_candidates(data_ctx, highlight_ctx, 'outlook')
    answers['outlook'] = _ask_question(
        'Q3', '전망/테마',
        '다음 분기 시장 전망과 주목할 테마는?',
        candidates, default=dd.get('outlook')
    )

    # Q4: 리스크
    candidates = _build_data_driven_candidates(data_ctx, highlight_ctx, 'risk')
    answers['risk'] = _ask_question(
        'Q4', '리스크',
        '현재 가장 큰 리스크 요인은?',
        candidates, default=dd.get('risk')
    )

    # Q5: 히스토리 — 비중/수익률/이슈 자동 분석 제시
    history_summary = _build_history_summary(data_ctx, highlight_ctx, fund_code, year, quarter)
    if history_summary:
        print(f'\n[Q5] 히스토리 분석 (자동)')
        print(f'  아래는 분기 데이터와 전분기 포지션을 자동 분석한 결과입니다.')
        for line in history_summary.split('\n'):
            print(f'  {line}')
        answers['history_diff'] = _ask_question(
            'Q5', '히스토리',
            '위 분석 대비 추가 설명이나 달라진 점은?',
        )
    else:
        answers['history_diff'] = None

    # Q6: 추가
    answers['additional'] = _ask_question(
        'Q6', '추가사항',
        '보고서에 추가로 강조할 사항은?',
        default=dd.get('additional')
    )

    return answers


# ═══════════════════════════════════════════════════════
# Step 4: 저장
# ═══════════════════════════════════════════════════════

def step4_save(fund_code, year, quarter, data_ctx, highlight_ctx, answers):
    """인터뷰 결과 → narratives.yaml + interview_log JSON."""
    _, end_month = _quarter_dates(year, quarter)

    # narratives.yaml 업데이트
    narrative_file = BASE_DIR / 'data' / 'narratives.yaml'
    try:
        import yaml
        existing = {}
        if narrative_file.exists():
            existing = yaml.safe_load(narrative_file.read_text(encoding='utf-8')) or {}

        month_key = f'{year}-{end_month:02d}'
        entry = {}
        if answers.get('market_view'):
            entry['market_view'] = answers['market_view']
        if answers.get('position_rationale'):
            entry['position_rationale'] = answers['position_rationale']
        themes = []
        if answers.get('outlook'):
            themes.append(answers['outlook'])
        if answers.get('risk'):
            themes.append(f'리스크: {answers["risk"]}')
        if themes:
            entry['upcoming_themes'] = themes
        entry['interview_source'] = True

        if entry:
            existing[month_key] = entry
            with open(narrative_file, 'w', encoding='utf-8') as f:
                yaml.dump(existing, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            print(f'\n  [저장] narratives.yaml ({month_key})')
    except Exception as e:
        print(f'\n  [경고] narratives.yaml 저장 실패: {e}')

    # interview_log JSON
    log = {
        'fund_code': fund_code,
        'year': year,
        'quarter': quarter,
        'timestamp': datetime.now().isoformat(),
        'data_summary': {
            'fund_return': data_ctx['fund_ret']['return'] if data_ctx.get('fund_ret') else None,
            'pa': data_ctx.get('pa', {}),
            'holdings_diff': data_ctx.get('holdings_diff', []),
        },
        'selected_highlights': [h['text'] for h in highlight_ctx.get('selected_highlights', [])],
        'interview': answers,
    }
    log_file = OUTPUT_DIR / f'interview_{fund_code}_{year}Q{quarter}.json'
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f'  [저장] {log_file.name}')


# ═══════════════════════════════════════════════════════
# Step 5: 보고서 생성
# ═══════════════════════════════════════════════════════

def _build_interview_prompt(fund_code, year, quarter, data_ctx, highlight_ctx, answers, model, detail=False):
    """인터뷰 기반 프롬프트 빌드."""
    cfg = FUND_CONFIGS.get(fund_code, {})
    fmt = cfg.get('format', 'C')
    _, end_month = _quarter_dates(year, quarter)
    q_label = f'{quarter}분기'

    # BM 테이블
    bm = data_ctx['bm']
    bm_lines = []
    for name in ['글로벌주식', 'KOSPI', 'KOSPI_PRICE', 'S&P500', '미국성장주', '미국가치주',
                  'Russell2000', '고배당', '미국외선진국', '신흥국주식',
                  '글로벌채권UH', '매경채권국채3년', 'KRX10년채권', 'KAP종합채권',
                  '미국종합채권', '미국IG', '미국HY', '신흥국채권',
                  'Gold', 'WTI', '미국리츠', 'DXY', 'USDKRW']:
        info = bm.get(name, {})
        ret = info.get('return')
        level = info.get('level')
        if ret is not None:
            lv_str = f', 수준={level:,.2f}' if level else ''
            bm_lines.append(f'  {name}: {ret:+.2f}%{lv_str}')
    bm_table = '\n'.join(bm_lines)

    # 펀드 성과
    fund_ret = data_ctx['fund_ret']
    fund_data = f'펀드 {q_label} 수익률: {fund_ret["return"]:+.2f}%' if fund_ret else '데이터 없음'
    sub_text = ''
    if fund_ret and fund_ret.get('sub_returns'):
        parts = [f'{k}: {v:+.2f}%' for k, v in fund_ret['sub_returns'].items()]
        sub_text = f'\n서브 포트폴리오: {", ".join(parts)} (비중 {cfg.get("sub_ratio", "N/A")})'

    # PA
    pa = data_ctx['pa']
    pa_lines = [f'  {cls}: {v:+.2f}%' for cls, v in sorted(pa.items(), key=lambda x: -abs(x[1])) if abs(v) >= 0.01]
    pa_table = '\n'.join(pa_lines)

    # 비중변화
    diff_lines = []
    for d in data_ctx.get('holdings_diff', []):
        diff_lines.append(f'  {d["asset_class"]}: {d["prev"]}% → {d["cur"]}% ({d["change"]:+.1f}%p {d["direction"]})')
    diff_table = '\n'.join(diff_lines) if diff_lines else '  유의미한 변동 없음'

    # 보유비중 (분기말)
    holdings = data_ctx['holdings_end']
    hold_lines = [f'  {cls}: {wt:.1f}%' for cls, wt in sorted(holdings.items(), key=lambda x: -x[1]) if wt > 0.5]
    hold_table = '\n'.join(hold_lines)

    # 펀드 정보
    fund_info = f'펀드코드: {fund_code}'
    if cfg.get('target_return'):
        fund_info += f'\n목표수익률: 연 {cfg["target_return"]:.0f}%'
    if cfg.get('philosophy'):
        fund_info += f'\n운용철학: {cfg["philosophy"]}'

    # 인터뷰 답변 섹션
    interview_sections = []
    if answers.get('market_view'):
        interview_sections.append(f'[운용역 시장 판단]\n{answers["market_view"]}')
    if answers.get('position_rationale'):
        interview_sections.append(f'[포지션 변경 근거]\n{answers["position_rationale"]}')
    if answers.get('outlook'):
        interview_sections.append(f'[향후 전망/테마]\n{answers["outlook"]}')
    if answers.get('risk'):
        interview_sections.append(f'[리스크 요인]\n{answers["risk"]}')
    if answers.get('additional'):
        interview_sections.append(f'[추가 강조]\n{answers["additional"]}')
    if answers.get('history_diff'):
        interview_sections.append(f'[전분기 대비 변화]\n{answers["history_diff"]}')
    interview_text = '\n\n'.join(interview_sections) if interview_sections else '(인터뷰 응답 없음 — 데이터 기반으로 자동 생성)'

    # 선택된 하이라이트
    selected = highlight_ctx.get('selected_highlights', [])
    highlight_text = '\n'.join(f'  - [{h["topic"]}] {h["text"]}' for h in selected[:10]) if selected else '  (선택 없음)'

    # 과거 코멘트 (few-shot)
    past_sample = ''
    # 07G04 형식 최근 보고서를 few-shot으로
    all_comments = highlight_ctx.get('all_comments', [])
    fund_comments = [c for c in all_comments if c['code'] == fund_code]
    if fund_comments:
        latest = fund_comments[-1]
        # 너무 길면 앞 1500자만
        past_sample = f'\n\n## 과거 코멘트 문체 참고 ({latest["file"]})\n아래 과거 코멘트의 톤, 구조, 표현 방식을 참고하되 내용은 현 분기 데이터와 운용역 판단만 사용하세요.\n\n{latest["text"][:1500]}'

    # 포지션 제약
    constraint_text = ''
    if cfg.get('position_constraints'):
        constraint_text = f'\n\n## 포지션 제약 (반드시 준수)\n{cfg["position_constraints"]}'

    # 양식 결정
    if detail:
        # --detail: 과거 코멘트에서 07G04 상세 양식을 few-shot으로
        fund_comments = [c for c in highlight_ctx.get('all_comments', []) if c['code'] == fund_code]
        format_sample = fund_comments[-1]['text'][:3000] if fund_comments else _SAMPLE_REPORTS.get(fmt, _SAMPLE_REPORTS['C'])
        format_instruction = """## 양식 샘플 (이 구조와 톤을 정확히 따르세요)
아래는 이전 월의 실제 보고서입니다. 동일한 섹션 구조, 번호 체계(1/2, -, ㅇ, ①②③, A.B.C.), 톤을 따르되 내용은 현 분기 데이터만 사용하세요.
성과요인분해 테이블, SAA대비 운용현황 테이블은 데이터가 제공된 경우에만 작성하세요.

""" + format_sample
        format_markers = '구분 기호는 -, ㅇ, ①②③, A.B.C. 만 사용하세요 (아래 양식 샘플 참고).'
    else:
        # 기본: 간결 C포맷
        format_sample = _SAMPLE_REPORTS.get(fmt, _SAMPLE_REPORTS['C'])
        format_instruction = f"""## 포맷 (이 양식을 따르세요)
{format_sample}"""
        format_markers = '[운용경과], [운용계획] 같은 섹션 구분자와 들여쓰기만 사용하세요. 순수 텍스트 문단으로 작성하세요.'

    prompt = f"""당신은 DB형 퇴직연금 OCIO 운용보고서 코멘트 작성자입니다.
아래 데이터와 운용역 인터뷰 응답을 바탕으로 {year}년 {q_label} 운용보고 코멘트를 작성하세요.

## 작성 규칙 — 문체
1. 경어체 사용 ("~하였습니다", "~예상합니다", "~계획입니다")
2. 마크다운 기호(#, ##, **, ---, 불릿)를 절대 쓰지 마세요.
3. {format_markers}
4. 대비 구조 활용: "A가 양호한 반면, B는 부진" 패턴을 적극 사용하세요.
5. 인과 서술: "원인 + 결과"를 한 문장에 담으세요.

## 작성 규칙 — 데이터
6. 벤치마크 수치는 제공된 데이터만 사용 (절대 수치를 만들어내지 마세요)
7. KOSPI 포인트는 KOSPI_PRICE의 수준값 사용 (TR 지수 아님)
8. PA 기여도 수치는 정확히 제공된 값 사용

## 작성 규칙 — 핵심
9. 운용역 인터뷰 응답을 최우선으로 반영하되, 데이터와 교차 검증하여 자연스럽게 서술하세요.
10. 선택된 뉴스/블로그는 보조 근거로만 활용하세요 (출처 언급 금지).
11. 전망과 포지션은 운용역 답변의 구체적 메커니즘과 액션을 반영하세요. 일반론("모니터링 계획") 금지.
12. PA 기여도 0.05% 이상인 모든 자산군의 원인을 서술하세요.

{format_instruction}

## 벤치마크 {q_label} 수익률
{bm_table}

## 펀드 데이터
{fund_info}
{fund_data}{sub_text}

## PA 자산군별 기여도
{pa_table}

## 분기 비중 변화
{diff_table}

## 펀드 보유 자산 비중 (분기말)
{hold_table}

## 운용역 인터뷰 (반드시 반영)
{interview_text}

## 선택된 뉴스/블로그 근거 (보조 활용)
{highlight_text}{constraint_text}{past_sample}

위 포맷과 동일한 구조, 톤, 분량으로 {fund_code} {q_label} 보고서를 작성하세요.
수치는 반드시 제공된 데이터만 사용하세요."""

    return prompt


def step5_generate(fund_code, year, quarter, data_ctx, highlight_ctx, answers, model='claude-sonnet-4-6', interactive=True, detail=False):
    """보고서 생성 + 수정 루프."""
    prompt = _build_interview_prompt(fund_code, year, quarter, data_ctx, highlight_ctx, answers, model, detail=detail)

    print(f'\n  보고서 생성 중 ({model})...', flush=True)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    messages = [{"role": "user", "content": prompt}]
    total_cost = 0

    while True:
        response = client.messages.create(
            model=model,
            max_tokens=5000,
            messages=messages,
        )
        text = response.content[0].text
        usage = response.usage
        cost_in = usage.input_tokens * 3 / 1_000_000
        cost_out = usage.output_tokens * 15 / 1_000_000
        cost = cost_in + cost_out
        total_cost += cost
        print(f'  ({usage.input_tokens} in + {usage.output_tokens} out = ${cost:.3f})\n')

        print('=' * 56)
        print(text)
        print('=' * 56)

        # 수정 루프
        if not interactive:
            break
        print(f'\n  수정 지시사항 (Enter=완료): ', end='')
        revision = input().strip()
        if not revision:
            break

        # 수정 요청을 대화에 추가
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": f'아래 수정사항을 반영하여 보고서 전체를 다시 작성해주세요:\n{revision}'})
        print(f'\n  재생성 중...', flush=True)

    # 최종 저장
    _, end_month = _quarter_dates(year, quarter)
    out_file = OUTPUT_DIR / f'report_{fund_code}_{year}Q{quarter}.txt'
    out_file.write_text(text, encoding='utf-8')
    print(f'\n  [저장] {out_file.name}')
    print(f'  [총 비용] ${total_cost:.3f}')

    return text, total_cost


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='운용보고서 인터뷰 CLI')
    parser.add_argument('fund_code', help='펀드코드 (예: 07G04)')
    parser.add_argument('--quarter', '-q', type=int, required=True, help='분기 (1~4)')
    parser.add_argument('--year', '-y', type=int, default=datetime.now().year, help='연도')
    parser.add_argument('--opus', action='store_true', help='Opus 모델 사용 (기본: Sonnet)')
    parser.add_argument('--answers', type=str, help='비대화형: 미리 작성한 답변 JSON 파일 경로')
    parser.add_argument('--select-all', action='store_true', help='하이라이트 전체 선택')
    parser.add_argument('--detail', action='store_true', help='상세 양식 (07G04 월별 보고서 양식, 기본: 간결 C포맷)')
    parser.add_argument('--debate', action='store_true', help='debate 엔진으로 기본답변 생성 후 확인/수정 모드')
    args = parser.parse_args()

    model = 'claude-opus-4-6' if args.opus else 'claude-sonnet-4-6'

    # Step 1
    data_ctx = step1_load_and_summarize(args.fund_code, args.year, args.quarter)

    # Debate (옵션)
    debate_defaults = None
    if args.debate:
        debate_result = _run_debate_for_quarter(args.fund_code, args.year, args.quarter)
        debate_defaults = _debate_to_default_answers(debate_result)

    # Step 2
    if args.answers:
        highlight_ctx = step2_highlights_auto(args.fund_code, args.year, args.quarter)
    else:
        highlight_ctx = step2_highlights(args.fund_code, args.year, args.quarter)

    # Step 3
    if args.answers:
        answers_file = Path(args.answers)
        answers = json.loads(answers_file.read_text(encoding='utf-8'))
        print(f'\n  [비대화형] 답변 로드: {answers_file.name}')
        for k, v in answers.items():
            if v:
                print(f'    {k}: {str(v)[:60]}...' if len(str(v)) > 60 else f'    {k}: {v}')
    else:
        answers = step3_interview(data_ctx, highlight_ctx, args.fund_code, args.year, args.quarter, debate_defaults)

    # Step 4
    step4_save(args.fund_code, args.year, args.quarter, data_ctx, highlight_ctx, answers)

    # Step 5
    interactive = not bool(args.answers)
    step5_generate(args.fund_code, args.year, args.quarter, data_ctx, highlight_ctx, answers, model, interactive=interactive, detail=args.detail)


if __name__ == '__main__':
    main()
