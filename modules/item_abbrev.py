# -*- coding: utf-8 -*-
"""종목명 약어 테이블. 차트/테이블 표시용."""

# ITEM_CD → 약어 (우선)
ABBREV_BY_CODE = {
    # 해외 ETF — symbol 사용
    'US9220428588': 'VWO',
    'US46435U8532': 'USHY',
    'US9219438580': 'VEA',
    'US92189F1066': 'GDX',
    'US46436F1030': 'IAUM',
    'US78464A4094': 'SPYG',
    'US9229087443': 'VTV',
    'US9219468850': 'VWOB',
    # 국내 ETF — 브랜드+핵심
    'KR70127P0003': 'ACE 미국성장',
    'KR70127M0006': 'ACE 미국가치',
    'KR7367380003': 'ACE 나스닥100',
    'KR7365780006': 'ACE 국고채10Y',
    'KR7356540005': 'ACE 종합채권AA+',
    'KR7487340002': 'ACE 머니마켓',
    'KR7411060007': 'ACE KRX금',
    'KR7105190003': 'ACE 200',
    'KR7332500008': 'ACE 200TR',
    'KR7453850000': 'ACE 미국30Y채권(H)',
    'KR7468380001': 'KODEX 미국HY',
    'KR7439870007': 'KODEX 국고채30Y',
    'KR7484790001': 'KODEX 미국30Y채권(H)',
    'KR7385560008': 'RISE 국고채30Y',
    'KR7451530000': 'TIGER 국고채30Y스트립',
    'KR7458250008': 'TIGER 미국30Y스트립(H)',
    # 국내 채권
    'KR103502GE97': '국고24-8(2.75%)',
    'KR103502GE30': '국고24-2(3.25%)',
    'KR103502GC65': '국고22-5(3.375%)',
    'KR103502GD98': '국고23-7(3.625%)',
    'KR6169379E88': '메리츠캐피탈262-3',
    # 펀드
    'KRZ502659020': '월넛은행채플러스',
    'KRZ502649912': '한투TMF26-12',
    'KRZ502649922': '한투TMF28-12',
    # 유동성
    'USMUSD022001': 'USD DEPOSIT',
}

# 종목명 패턴 → 약어 (ITEM_CD 매칭 실패 시 fallback)
ABBREV_BY_NAME = {
    '한국투자TMF26': '한투TMF26-12',
    '한국투자TMF28': '한투TMF28-12',
    '월넛은행채플러스': '월넛은행채',
    'VANGUARD FTSE EMERGING': 'VWO',
    'VANGUARD FTSE DEVELOPED': 'VEA',
    'VANGUARD VALUE': 'VTV',
    'VANGUARD EMERG MKTS GOV': 'VWOB',
    'VANECK VECTORS GOLD': 'GDX',
    'ISHARES GOLD TRUST': 'IAUM',
    'iShares Broad USD High': 'USHY',
    'State Street SPDR Portfolio S&P 500 Grow': 'SPYG',
    'KODEX iShares미국하이일드': 'KODEX 미국HY',
}


def abbreviate(item_cd: str = '', item_nm: str = '', max_len: int = 16) -> str:
    """종목명을 차트용 약어로 변환."""
    # 1. 코드 매칭
    if item_cd and item_cd in ABBREV_BY_CODE:
        return ABBREV_BY_CODE[item_cd]
    # 2. 이름 패턴 매칭
    for pattern, abbr in ABBREV_BY_NAME.items():
        if pattern in item_nm:
            return abbr
    # 3. 길이 제한 fallback
    if len(item_nm) > max_len:
        return item_nm[:max_len-2] + '..'
    return item_nm
