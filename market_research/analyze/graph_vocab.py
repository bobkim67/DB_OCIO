# -*- coding: utf-8 -*-
"""Graph trigger/target vocabulary + alias dict (Phase 3 P1).

Canonical labels와 그 aliases를 한 곳에 정의. graph_rag.precompute_transmission_paths에서
트리거/타겟 탐색 시 alias까지 전부 시도하고, 출력은 canonical label로 통일.
"""
from __future__ import annotations

from market_research.analyze.news_classifier import TOPIC_TAXONOMY

# ══════════════════════════════════════════
# Asset taxonomy (target용)
# ══════════════════════════════════════════
ASSET_TAXONOMY: list[str] = [
    '국내주식', '해외주식', '국내채권', '해외채권',
    '금', '유가', '환율', '금리', '부동산', '크립토',
]

# ══════════════════════════════════════════
# Driver taxonomy (trigger용) — 거시 드라이버 중심
# ══════════════════════════════════════════
DRIVER_TAXONOMY: list[str] = [
    '통화정책', '물가_인플레이션', '지정학', '관세_무역',
    '달러_글로벌유동성', '유동성_크레딧', '경기_소비',
    '테크_AI_반도체', '에너지_원자재',
]

# ══════════════════════════════════════════
# Alias dict — canonical label → [aliases]
# ══════════════════════════════════════════
# 원칙:
#   - 각 alias는 canonical label로 lookup 가능해야 함
#   - 부분 매칭(word-boundary) 규칙과 조합 — alias가 정확히 들어가지 않아도
#     파생형(유가_급등, 국제유가_상승)은 기존 word-boundary 로직이 처리
TRIGGER_ALIAS: dict[str, list[str]] = {
    # drivers
    '통화정책': ['통화정책', '연준', 'Fed', 'FOMC', '기준금리', '한국은행', '금통위', 'ECB', 'BOJ'],
    '물가_인플레이션': ['물가_인플레이션', '인플레', '인플레이션', 'CPI', 'PCE', 'PPI', '인플레이션_압력'],
    '지정학': ['지정학', '지정학적', '중동', '이란', '호르무즈', '휴전', '전쟁'],
    '관세_무역': ['관세_무역', '관세', '무역', '수출입', '통상'],
    '달러_글로벌유동성': ['달러_글로벌유동성', '달러_부족', '달러_기근', '유로달러', '스왑라인'],
    '유동성_크레딧': ['유동성_크레딧', '유동성', '레포', '크레딧', '회사채'],
    '경기_소비': ['경기_소비', '경기', '소비', 'GDP', '고용', '실업', 'PMI'],
    '테크_AI_반도체': ['테크_AI_반도체', 'AI', '반도체', '빅테크', 'NVIDIA'],
    '에너지_원자재': ['에너지_원자재', '유가', 'WTI', '브렌트', '원유', 'OPEC'],
}

TARGET_ALIAS: dict[str, list[str]] = {
    # specific assets
    '국내주식': ['국내주식', 'KOSPI', '코스피', 'KOSDAQ', '코스닥'],
    '해외주식': ['해외주식', 'SP500', 'S&P', '나스닥', 'NASDAQ', '다우'],
    '국내채권': ['국내채권', '국고채', 'KTB'],
    '해외채권': ['해외채권', '미국채', 'UST', 'Treasury'],
    '금': ['금', '금가격', '골드', '귀금속'],
    '유가': ['유가', '국제유가', '원유', 'WTI', '브렌트'],
    '환율': ['환율', '원달러', 'USDKRW', '달러인덱스', 'DXY'],
    '금리': ['금리', '기준금리', '채권수익률', '수익률_커브'],
    '부동산': ['부동산', '주택가격', '리츠'],
    '크립토': ['크립토', '비트코인', '이더리움', 'BTC', 'ETH'],
}


def all_trigger_canonicals() -> list[str]:
    return list(TRIGGER_ALIAS.keys())


def all_target_canonicals() -> list[str]:
    return list(TARGET_ALIAS.keys())


def aliases_for_trigger(canon: str) -> list[str]:
    return TRIGGER_ALIAS.get(canon, [canon])


def aliases_for_target(canon: str) -> list[str]:
    return TARGET_ALIAS.get(canon, [canon])
