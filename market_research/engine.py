# -*- coding: utf-8 -*-
"""
블로거 뷰 추론 엔진
포스팅-지표 매칭 → 주제 태깅 → 패턴 DB → 현재 지표 기반 추론
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 경로 ──
BASE_DIR = Path(__file__).resolve().parent
POSTS_FILE = BASE_DIR / "data" / "monygeek" / "posts.json"
INDICATORS_CSV = BASE_DIR / "data" / "macro" / "indicators.csv"
WORLDVIEW_FILE = BASE_DIR / "data" / "monygeek" / "analysis_worldview.json"
PATTERN_DB_FILE = BASE_DIR / "data" / "macro" / "pattern_db.json"


# ═══════════════════════════════════════════════════════
# 1. 주제 태깅 — 12개 매크로 변수 + 세부 키워드
# ═══════════════════════════════════════════════════════

TOPIC_KEYWORDS = {
    '금리': [
        '금리', '국채', 'Treasury', '10년', '2년', '30년', 'yield', '수익률',
        '불스티프닝', 'bull steep', 'bear flat', '텀프리미엄', 'term premium',
        '금리 역전', 'inversion', 'FOMC', '점도표', 'dot plot', 'Fed',
    ],
    '달러': [
        '달러', 'dollar', 'DXY', '달러 인덱스', '달러 강세', '달러 약세',
        '달러 부족', '달러 기근', '달러 유동성',
    ],
    '이민_노동': [
        '고용', '실업', 'NFP', '비농업', 'payroll', 'BLS', 'JOLTS',
        '퇴사율', 'Quits', '이민', '노동', '일자리', '생성-소멸',
    ],
    '물가': [
        '인플레', 'CPI', 'PCE', '물가', '브레이크이븐', 'breakeven',
        '디플레', '스태그플레이션', 'stagflation',
    ],
    '관세': [
        '관세', 'tariff', '무역', '무역전쟁', '무역적자', 'trade war',
        '트럼프', '디커플링', '리쇼어링',
    ],
    '안전자산': [
        '안전자산', 'safe asset', 'flight to safety', '유동성 선호',
        '미국 예외주의', 'exceptionalism', '자본 유입',
    ],
    '미국채': [
        '미국채', 'Treasury', '국채 매도', '커스터디', 'custody',
        'TIC', '노린추킨', '평가손실',
    ],
    '엔화_캐리': [
        '엔화', '엔 캐리', 'carry trade', '일본', 'BOJ', 'BoJ',
        '노린추킨', 'CFTC', '엔 포지션',
    ],
    '중국_위안화': [
        '중국', '위안', 'CNY', 'CNH', 'PBOC', '인민은행',
        '좀비 은행', '부동산', '디플레',
    ],
    '유로달러': [
        '유로달러', 'eurodollar', '역외 달러', '그림자', 'shadow',
        'SOFR', '레포', 'repo', '역레포', 'RRP', '지급준비금',
        'reserve', 'SRF', 'QT', 'QE', '대차대조표', 'TGA',
        'MMF', '침묵의 공황',
    ],
    '유가_에너지': [
        '유가', '원유', 'WTI', '브렌트', 'Brent', 'OPEC',
        '에너지', '호르무즈', '이란', '석유',
    ],
    'AI_반도체': [
        'AI', '반도체', '엔비디아', 'NVIDIA', 'HBM', '하이닉스',
        '삼성전자', 'TSMC', 'GPU', '데이터센터', 'J커브',
    ],
    '한국_원화': [
        '원화', 'KOSPI', '한국 증시', '코리아 디스카운트', 'ATM',
        '외국인', 'MSCI', '원/달러', '환율',
    ],
    '유럽_ECB': [
        '유럽', '독일', 'ECB', '유로', 'Bunds', '부채 브레이크',
        'debt brake', 'BOE', '라가르드',
    ],
    '부동산': [
        '부동산', '집값', '주택', '전세', '슈퍼스타', '아파트',
        '주거', '월세',
    ],
    '저출산_인구': [
        '저출산', '출산', '인구', '고령화', '인구 감소',
    ],
    '비트코인_크립토': [
        '비트코인', 'BTC', '코인', '크립토', 'XRP', '스테이블',
        'ETF', '디지털 금',
    ],
    '금': [
        '금 가격', '금값', 'gold', '골드', '금 현물', '불확실성 프리미엄',
    ],
}


def tag_topics(title, content):
    """포스팅에서 주제 태깅 — 키워드 매칭 기반"""
    text = (title + ' ' + content).lower()
    topics = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score >= 2:  # 최소 2개 키워드 매칭
            topics[topic] = score
    return topics


# ═══════════════════════════════════════════════════════
# 2. 포스팅-지표 매칭
# ═══════════════════════════════════════════════════════

# 지표를 주제별로 그룹핑 (대시보드/추론에서 사용)
INDICATOR_TOPIC_MAP = {
    '금리': ['UST_2Y', 'UST_5Y', 'UST_10Y', 'UST_20Y', 'UST_1M', 'UST_3M', 'UST_1Y',
             'DGS2', 'DGS10', 'US_2Y10Y', 'UST_7_10Y_TR', 'LUATTRUU'],
    '달러': ['DXY', 'BROAD_DOLLAR', 'EM_DOLLAR'],
    '유로달러': ['SOFR', 'EFFR', 'RRP', 'RESERVE_BAL', 'TGA',
                'REPO_FAILS_DEL', 'REPO_FAILS_RCV'],
    '물가': ['CPIAUCSL', 'PCEPI', 'T5YIE', 'T10YIE'],
    '이민_노동': ['UNRATE', 'PAYEMS', 'JTSJOL', 'JTSQUR', 'MFG_EMPLOYMENT'],
    '유가_에너지': ['WTI', 'BRENT'],
    '엔화_캐리': ['USDJPY'],
    '중국_위안화': ['USDCNY'],
    '한국_원화': ['USDKRW', 'F_USDKRW', 'MSCI_KOREA'],
    '안전자산': ['VIX', 'MOVE', 'US_HY_OAS', 'GOLD'],
    'AI_반도체': ['SP500_TR', 'MSCI_EAFE', 'MSCI_EM', 'MSCI_JAPAN'],
}

# 지표별 방향 해석 (블로거 관점)
# +1 = 상승이 스트레스/부정적, -1 = 상승이 완화/긍정적
INDICATOR_DIRECTION = {
    'DXY': +1,           # 달러 강세 = 유동성 부족
    'EM_DOLLAR': +1,     # EM 달러 강세 = 이머징 스트레스
    'BROAD_DOLLAR': +1,
    'USDKRW': +1,        # 원화 약세 = 부정적
    'USDCNY': +1,        # 위안화 약세 = 부정적
    'USDJPY': -1,        # 엔 강세(숫자 하락) = 달러 약세 신호
    'VIX': +1,           # VIX 상승 = 불안
    'MOVE': +1,          # MOVE 상승 = 채권 변동성
    'US_HY_OAS': +1,     # 스프레드 확대 = 크레딧 스트레스
    'SOFR': +1,          # 상승 = 자금 타이트
    'RRP': -1,           # 감소 = 유동성 변화 (블로거는 중립)
    'REPO_FAILS_DEL': +1,  # 증가 = 달러 스트레스
    'REPO_FAILS_RCV': +1,
    'WTI': +1,           # 유가 상승 = 인플레 압력
    'BRENT': +1,
    'GOLD': +1,          # 금 상승 = 불확실성
    'UST_10Y': +1,       # 금리 상승 = 글로벌 매도 압력
    'US_2Y10Y': -1,      # 스프레드 확대 = 정상화 (블로거 관점에선 복합)
    'SP500_TR': -1,      # 상승 = 긍정
    'MSCI_EM': -1,       # 상승 = 이머징 회복
    'MSCI_KOREA': -1,
    'EM_DOLLAR': +1,     # 상승 = 이머징 약세 (달러 강세)
    'UNRATE': +1,        # 실업률 상승 = 고용 악화
    'T5YIE': +1,         # 인플레 기대 상승 = 인플레 우려
}


def load_data():
    """포스팅 + 지표 로드"""
    posts = json.load(open(POSTS_FILE, 'r', encoding='utf-8'))
    indicators = pd.read_csv(INDICATORS_CSV, index_col=0)
    return posts, indicators


def match_posts_to_indicators(posts, indicators):
    """포스팅 날짜에 지표값 매칭 + 주제 태깅"""
    matched = []

    for p in posts:
        dt = p.get('date', '')
        if not dt.startswith('20'):
            continue

        # 주제 태깅
        topics = tag_topics(p.get('title', ''), p.get('content', ''))
        if not topics:
            continue

        # 지표 매칭 (당일 없으면 직전 영업일)
        if dt in indicators.index:
            row = indicators.loc[dt]
        else:
            prior = indicators.index[indicators.index < dt]
            if len(prior) == 0:
                continue
            row = indicators.loc[prior[-1]]

        # 지표 변동률 (5일 전 대비)
        idx_pos = list(indicators.index).index(row.name) if row.name in indicators.index else -1
        changes = {}
        if idx_pos >= 5:
            prev_row = indicators.iloc[idx_pos - 5]
            for col in indicators.columns:
                cur, prev = row[col], prev_row[col]
                if pd.notna(cur) and pd.notna(prev) and prev != 0:
                    changes[col] = (cur - prev) / abs(prev) * 100

        matched.append({
            'date': dt,
            'title': p.get('title', ''),
            'log_no': p.get('log_no', ''),
            'topics': topics,
            'top_topic': max(topics, key=topics.get),
            'indicator_date': row.name,
            'indicators': {k: v for k, v in row.to_dict().items() if pd.notna(v)},
            'changes_5d': changes,
        })

    return matched


# ═══════════════════════════════════════════════════════
# 3. 패턴 DB 생성
# ═══════════════════════════════════════════════════════

def build_pattern_db(matched):
    """주제별 지표 통계 패턴 생성"""
    patterns = {}

    for topic in TOPIC_KEYWORDS:
        # 해당 주제 포스팅만 필터
        topic_posts = [m for m in matched if topic in m['topics']]
        if len(topic_posts) < 3:
            continue

        # 관련 지표들의 통계
        related_indicators = INDICATOR_TOPIC_MAP.get(topic, [])
        indicator_stats = {}

        for ind in related_indicators:
            values = [m['indicators'].get(ind) for m in topic_posts if ind in m['indicators']]
            changes = [m['changes_5d'].get(ind) for m in topic_posts if ind in m['changes_5d']]
            values = [v for v in values if v is not None]
            changes = [c for c in changes if c is not None]

            if values:
                indicator_stats[ind] = {
                    'mean': np.mean(values),
                    'median': np.median(values),
                    'std': np.std(values),
                    'min': np.min(values),
                    'max': np.max(values),
                    'count': len(values),
                }
            if changes:
                indicator_stats[ind + '_chg5d'] = {
                    'mean': np.mean(changes),
                    'median': np.median(changes),
                    'std': np.std(changes),
                }

        patterns[topic] = {
            'post_count': len(topic_posts),
            'indicator_stats': indicator_stats,
            'sample_titles': [m['title'][:60] for m in topic_posts[:5]],
        }

    return patterns


# ═══════════════════════════════════════════════════════
# 4. 현재 지표 기반 추론
# ═══════════════════════════════════════════════════════

# 블로거 프레임워크 기반 진단 룰
DIAGNOSIS_RULES = [
    # ── 달러/유동성 ──
    {
        'name': '달러 기근 심화',
        'condition': lambda r, c: r.get('EM_DOLLAR', 0) > 47 and c.get('EM_DOLLAR', 0) > 0.5,
        'message': 'EM 달러 인덱스 상승 → 이머징 통화 약세 → 글로벌 달러 유동성 부족 심화',
        'severity': 'warning',
        'topic': '달러',
    },
    {
        'name': '달러 유동성 개선',
        'condition': lambda r, c: r.get('EM_DOLLAR', 99) < 44 or c.get('EM_DOLLAR', 0) < -1.5,
        'message': 'EM 달러 인덱스 하락 → 이머징 통화 강세 → 유로달러 르네상스 진행 중',
        'severity': 'positive',
        'topic': '달러',
    },
    {
        'name': 'DXY 약세 전환',
        'condition': lambda r, c: r.get('DXY', 999) < 100 and c.get('DXY', 0) < -1,
        'message': 'DXY 100 하회 + 하락 추세 → 선진국 달러 약세 → 리스크온 환경',
        'severity': 'positive',
        'topic': '달러',
    },

    # ── 유로달러/레포 ──
    {
        'name': '레포 스트레스',
        'condition': lambda r, c: r.get('REPO_FAILS_DEL', 0) > 80000,
        'message': '레포 실패 8만+ → 국채 담보 부족 → 달러 조달 스트레스 경고',
        'severity': 'warning',
        'topic': '유로달러',
    },
    {
        'name': '자금시장 안정',
        'condition': lambda r, c: (r.get('SOFR', 99) < r.get('EFFR', 99) + 0.05 and
                                    r.get('REPO_FAILS_DEL', 999) < 80000),
        'message': 'SOFR ≈ EFFR + 레포 실패 정상 → 자금시장 안정',
        'severity': 'neutral',
        'topic': '유로달러',
    },
    {
        'name': 'RRP 고갈 근접',
        'condition': lambda r, c: r.get('RRP', 999) < 100,
        'message': 'Fed 역레포 $100B 미만 → 유동성 쿠션 소진 근접 (블로거: 증시 직접 영향은 아님)',
        'severity': 'neutral',
        'topic': '유로달러',
    },

    # ── 금리 ──
    {
        'name': '장기금리 급등',
        'condition': lambda r, c: c.get('UST_10Y', 0) > 2 or c.get('DGS10', 0) > 2,
        'message': '10년 금리 5일간 급등 → 글로벌 중앙은행 미국채 매도(달러 확보) 가능성',
        'severity': 'warning',
        'topic': '금리',
    },
    {
        'name': '수익률 곡선 정상화',
        'condition': lambda r, c: r.get('US_2Y10Y', -1) > 0.3,
        'message': '10Y-2Y 스프레드 +30bp 이상 → 수익률 곡선 정상화 진행',
        'severity': 'neutral',
        'topic': '금리',
    },
    {
        'name': 'MOVE 상승 (채권 변동성)',
        'condition': lambda r, c: r.get('MOVE', 0) > 100,
        'message': f'MOVE {r.get("MOVE",0):.0f} → 채권시장 변동성 확대',
        'severity': 'warning' if r.get('MOVE', 0) > 120 else 'neutral',
        'topic': '금리',
    } if False else  # 람다 안에서 분기 불가 — 아래로 분리
    {
        'name': 'MOVE 경계',
        'condition': lambda r, c: 100 < r.get('MOVE', 0) <= 120,
        'message': 'MOVE 100~120 → 채권시장 변동성 상승 중, 주시 필요',
        'severity': 'neutral',
        'topic': '금리',
    },
    {
        'name': 'MOVE 경고',
        'condition': lambda r, c: r.get('MOVE', 0) > 120,
        'message': 'MOVE 120+ → 채권시장 변동성 경고 → 유동성 스트레스 가능',
        'severity': 'warning',
        'topic': '금리',
    },

    # ── 유가/에너지 ──
    {
        'name': '유가 급등 (공급 충격)',
        'condition': lambda r, c: r.get('BRENT', 0) > 90,
        'message': '브렌트유 $90+ → 에너지 공급 충격 → 스태그플레이션 우려',
        'severity': 'critical' if r.get('BRENT', 0) > 110 else 'warning',
        'topic': '유가_에너지',
    } if False else
    {
        'name': '유가 위기',
        'condition': lambda r, c: r.get('BRENT', 0) > 110,
        'message': '브렌트유 $110+ → 호르무즈 위기 수준 → 스태그플레이션 현실화',
        'severity': 'critical',
        'topic': '유가_에너지',
    },
    {
        'name': '유가 경고',
        'condition': lambda r, c: 90 < r.get('BRENT', 0) <= 110,
        'message': '브렌트유 $90~110 → 에너지 비용 인상 압력 → 인플레 우려',
        'severity': 'warning',
        'topic': '유가_에너지',
    },
    {
        'name': '유가 하락 (수요 부진)',
        'condition': lambda r, c: r.get('BRENT', 99) < 65 and c.get('BRENT', 0) < -3,
        'message': '브렌트유 하락 → 글로벌 수요 부진 → OPEC 자기파괴적 덫',
        'severity': 'warning',
        'topic': '유가_에너지',
    },

    # ── 금 ──
    {
        'name': '금 불확실성 프리미엄',
        'condition': lambda r, c: r.get('GOLD', 0) > 4000 and r.get('DXY', 0) > 99,
        'message': '달러 강세 + 금 $4,000+ → 불확실성이 달러를 압도하는 신호',
        'severity': 'warning',
        'topic': '금',
    },
    {
        'name': '금 피크아웃 가능성',
        'condition': lambda r, c: c.get('EM_DOLLAR', 0) < -2 and c.get('GOLD', 0) < -3,
        'message': 'EM 달러 약세 + 금 급락 → 불확실성 프리미엄 감소 → 금 피크아웃 신호',
        'severity': 'positive',
        'topic': '금',
    },

    # ── 변동성/크레딧 ──
    {
        'name': 'VIX 공포 구간',
        'condition': lambda r, c: r.get('VIX', 0) > 30,
        'message': 'VIX 30+ → 시장 공포 구간',
        'severity': 'critical',
        'topic': '안전자산',
    },
    {
        'name': 'VIX 경계 구간',
        'condition': lambda r, c: 22 < r.get('VIX', 0) <= 30,
        'message': 'VIX 22~30 → 시장 불안 고조, 헤지 수요 증가',
        'severity': 'warning',
        'topic': '안전자산',
    },
    {
        'name': '크레딧 스프레드 확대',
        'condition': lambda r, c: r.get('US_HY_OAS', 0) > 4.0 or c.get('US_HY_OAS', 0) > 10,
        'message': 'HY OAS 확대 → 크레딧 리스크 확산 → 사모대출/좀비기업 경계',
        'severity': 'warning',
        'topic': '안전자산',
    },

    # ── 환율 ──
    {
        'name': '원화 급락',
        'condition': lambda r, c: r.get('USDKRW', 0) > 1450,
        'message': '원/달러 1,450+ → 한국 ATM 구조 작동 → 외국인 자금 이탈 압력',
        'severity': 'critical' if r.get('USDKRW', 0) > 1500 else 'warning',
        'topic': '한국_원화',
    } if False else
    {
        'name': '원화 위기',
        'condition': lambda r, c: r.get('USDKRW', 0) > 1500,
        'message': '원/달러 1,500+ → 원화 위기 수준 → ATM 구조 극대화',
        'severity': 'critical',
        'topic': '한국_원화',
    },
    {
        'name': '원화 약세',
        'condition': lambda r, c: 1400 < r.get('USDKRW', 0) <= 1500,
        'message': '원/달러 1,400~1,500 → 원화 약세 지속 → 이머징 달러 스트레스 반영',
        'severity': 'warning',
        'topic': '한국_원화',
    },
    {
        'name': '위안화 스트레스',
        'condition': lambda r, c: r.get('USDCNY', 0) > 7.2,
        'message': 'USD/CNY 7.2+ → PBOC 방어선 압박 → 글로벌 달러 부족 심화',
        'severity': 'critical',
        'topic': '중국_위안화',
    },
    {
        'name': '위안화 강세 전환',
        'condition': lambda r, c: r.get('USDCNY', 99) < 7.0 and c.get('USDCNY', 0) < -0.5,
        'message': 'USD/CNY 7.0 하회 → 위안화 강세 → 이머징 유동성 개선 신호 (탄광의 카나리아)',
        'severity': 'positive',
        'topic': '중국_위안화',
    },
    {
        'name': '엔화 약세 지속',
        'condition': lambda r, c: r.get('USDJPY', 0) > 155,
        'message': 'USD/JPY 155+ → 엔 약세 지속 → 일본 달러 조달 스트레스',
        'severity': 'warning',
        'topic': '엔화_캐리',
    },

    # ── 물가 ──
    {
        'name': '인플레 기대 상승',
        'condition': lambda r, c: r.get('T5YIE', 0) > 2.7,
        'message': '5Y 브레이크이븐 2.7%+ → 인플레이션 기대 고조',
        'severity': 'warning',
        'topic': '물가',
    },
    {
        'name': '스태그플레이션 복합 신호',
        'condition': lambda r, c: (r.get('BRENT', 0) > 90 and
                                    r.get('VIX', 0) > 22 and
                                    r.get('USDKRW', 0) > 1400),
        'message': '유가 급등 + VIX 고조 + 원화 약세 → 스태그플레이션 복합 신호',
        'severity': 'critical',
        'topic': '물가',
    },

    # ── 일간 급등/급락 (c1 = 1일 변동률) ──
    {
        'name': '글로벌 증시 급락',
        'condition': lambda r, c, c1: c1.get('SP500_TR', 0) < -2 or c1.get('MSCI_EM', 0) < -3,
        'message': 'S&P500 또는 MSCI EM 일간 급락 → 리스크오프 전환',
        'severity': 'critical',
        'topic': '안전자산',
    },
    {
        'name': '글로벌 증시 급등 (안도 랠리)',
        'condition': lambda r, c, c1: c1.get('SP500_TR', 0) > 1.5,
        'message': 'S&P500 일간 급등 → 안도 랠리, 유동성 빅테크 집중',
        'severity': 'positive',
        'topic': '안전자산',
    },
    {
        'name': 'KOSPI 급락 (ATM 작동)',
        'condition': lambda r, c, c1: c1.get('MSCI_KOREA', 0) < -3,
        'message': 'MSCI Korea 일간 급락 → ATM 구조 작동 — 에너지 수입국 + 신흥국 이중 노출',
        'severity': 'critical',
        'topic': '한국_원화',
    },
    {
        'name': '유가 일간 급등',
        'condition': lambda r, c, c1: c1.get('BRENT', 0) > 3,
        'message': '브렌트유 일간 3%+ 급등 → 공급 충격 심화',
        'severity': 'warning',
        'topic': '유가_에너지',
    },
    {
        'name': '유가 일간 급락 (안도)',
        'condition': lambda r, c, c1: c1.get('BRENT', 0) < -5,
        'message': '브렌트유 일간 5%+ 급락 → 지정학 리스크 완화 기대',
        'severity': 'positive',
        'topic': '유가_에너지',
    },
    {
        'name': '원화 일간 급변',
        'condition': lambda r, c, c1: abs(c1.get('USDKRW', 0)) > 1,
        'message': '원/달러 일간 1%+ 변동 → 외환시장 변동성 급등',
        'severity': 'warning',
        'topic': '한국_원화',
    },
    {
        'name': 'MOVE 일간 급등',
        'condition': lambda r, c, c1: c1.get('MOVE', 0) > 10,
        'message': 'MOVE 일간 10%+ 급등 → 채권시장 급변동, 유동성 이벤트 경계',
        'severity': 'warning',
        'topic': '금리',
    },
    {
        'name': '금리 급변 (2년)',
        'condition': lambda r, c, c1: abs(c.get('UST_2Y', 0)) > 5,
        'message': '미국채 2년 금리 5일간 5%+ 변동 → 정책 기대 급변',
        'severity': 'warning',
        'topic': '금리',
    },
]


# ═══════════════════════════════════════════════════════
# 4-1. 주요국 기준금리 (수동 업데이트)
# ═══════════════════════════════════════════════════════

CENTRAL_BANK_RATES = {
    'Fed':  {'rate': 3.625, 'range': '3.50~3.75%', 'date': '2026-03-18', 'action': '동결', 'next_meeting': '2026-05-07'},
    'ECB':  {'rate': 2.00,  'range': '2.00%',       'date': '2026-03-19', 'action': '동결', 'next_meeting': '2026-04-17'},
    'BOJ':  {'rate': 0.75,  'range': '0.75%',       'date': '2026-03-19', 'action': '동결', 'next_meeting': '2026-04-30'},
    'BoE':  {'rate': 3.75,  'range': '3.75%',       'date': '2026-03-19', 'action': '동결', 'next_meeting': '2026-05-08'},
    'RBA':  {'rate': 4.10,  'range': '4.10%',       'date': '2026-03-17', 'action': '+25bp 인상', 'next_meeting': '2026-05-20'},
    'BOK':  {'rate': 2.75,  'range': '2.75%',       'date': '2026-02-27', 'action': '-25bp 인하', 'next_meeting': '2026-04-17'},
}


def diagnose_current(indicators_df):
    """현재 지표 기반 블로거 관점 진단"""
    # ffill로 NaN 채운 후 최신 행 사용
    filled = indicators_df.ffill()
    latest = filled.iloc[-1]
    latest_vals = {k: v for k, v in latest.to_dict().items() if pd.notna(v)}

    # 5일 변동률 (ffill 기준)
    if len(filled) >= 6:
        prev = filled.iloc[-6]
        changes = {}
        for col in filled.columns:
            cur, prv = latest[col], prev[col]
            if pd.notna(cur) and pd.notna(prv) and prv != 0:
                changes[col] = (cur - prv) / abs(prv) * 100
    else:
        changes = {}

    # 20일 변동률
    changes_20d = {}
    if len(filled) >= 21:
        prev20 = filled.iloc[-21]
        for col in filled.columns:
            cur, prv = latest[col], prev20[col]
            if pd.notna(cur) and pd.notna(prv) and prv != 0:
                changes_20d[col] = (cur - prv) / abs(prv) * 100

    # 1일 변동률 (일간 급등/급락 감지용)
    changes_1d = {}
    if len(filled) >= 2:
        prev1 = filled.iloc[-2]
        for col in filled.columns:
            cur, prv = latest[col], prev1[col]
            if pd.notna(cur) and pd.notna(prv) and prv != 0:
                changes_1d[col] = (cur - prv) / abs(prv) * 100

    # 룰 평가 — c=5일 변동, c1=1일 변동
    triggered = []
    import inspect
    for rule in DIAGNOSIS_RULES:
        try:
            cond = rule['condition']
            if len(inspect.signature(cond).parameters) >= 3:
                hit = cond(latest_vals, changes, changes_1d)
            else:
                hit = cond(latest_vals, changes)
            if hit:
                triggered.append({
                    'name': rule['name'],
                    'message': rule['message'],
                    'severity': rule['severity'],
                    'topic': rule['topic'],
                })
        except Exception:
            pass

    return {
        'date': latest.name,
        'values': latest_vals,
        'changes_1d': changes_1d,
        'changes_5d': changes,
        'changes_20d': changes_20d,
        'central_banks': CENTRAL_BANK_RATES,
        'diagnoses': triggered,
    }


# ═══════════════════════════════════════════════════════
# 5. 실행
# ═══════════════════════════════════════════════════════

def build():
    """패턴 DB 빌드"""
    print("[엔진] 데이터 로드...")
    posts, indicators = load_data()

    print("[엔진] 포스팅-지표 매칭 + 주제 태깅...")
    matched = match_posts_to_indicators(posts, indicators)
    print(f"  매칭 완료: {len(matched)}건")

    # 주제 분포
    topic_counts = defaultdict(int)
    for m in matched:
        for t in m['topics']:
            topic_counts[t] += 1
    print("\n  주제별 포스팅 수:")
    for t, c in sorted(topic_counts.items(), key=lambda x: -x[1]):
        print(f"    {t}: {c}건")

    print("\n[엔진] 패턴 DB 생성...")
    patterns = build_pattern_db(matched)

    # 저장
    output = {
        'built_at': pd.Timestamp.now().isoformat(),
        'matched_count': len(matched),
        'patterns': patterns,
    }
    PATTERN_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PATTERN_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"[저장] {PATTERN_DB_FILE}")

    return matched, patterns


def infer():
    """현재 지표 기반 추론"""
    indicators = pd.read_csv(INDICATORS_CSV, index_col=0)
    result = diagnose_current(indicators)

    print(f"\n[추론] 기준일: {result['date']}")

    # 주요국 기준금리
    print(f"\n── 주요국 기준금리 ──")
    for name, info in result['central_banks'].items():
        print(f"  {name:4s} {info['range']:>12s} ({info['action']}, {info['date']}) 다음: {info['next_meeting']}")

    # 주요 지표 1일 변동
    print(f"\n── 주요 지표 일간 변동 ──")
    key_indicators = ['SP500_TR', 'MSCI_KOREA', 'MSCI_EM', 'MSCI_EAFE',
                      'BRENT', 'GOLD', 'DXY', 'EM_DOLLAR', 'USDKRW',
                      'UST_10Y', 'VIX', 'MOVE']
    for ind in key_indicators:
        val = result['values'].get(ind)
        chg1 = result['changes_1d'].get(ind)
        chg5 = result['changes_5d'].get(ind)
        if val is not None:
            c1 = f"{chg1:+.2f}%" if chg1 is not None else "   n/a"
            c5 = f"{chg5:+.2f}%" if chg5 is not None else "   n/a"
            print(f"  {ind:<15s} {val:>10,.2f}  1D: {c1}  5D: {c5}")

    # 진단
    print(f"\n── 진단 ({len(result['diagnoses'])}건) ──\n")
    severity_icon = {'critical': '🔴', 'warning': '🟡', 'positive': '🟢', 'neutral': '⚪'}
    for d in sorted(result['diagnoses'], key=lambda x: {'critical':0,'warning':1,'positive':2,'neutral':3}[x['severity']]):
        icon = severity_icon.get(d['severity'], '⚪')
        print(f"  {icon} [{d['topic']}] {d['name']}")
        print(f"     {d['message']}")

    return result


if __name__ == '__main__':
    matched, patterns = build()
    print("\n" + "=" * 60)
    result = infer()
