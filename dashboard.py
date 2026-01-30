"""
자산배분 대시보드 (통합 버전)

Features:
- 자산 자동 분류
- 마스터 데이터 관리
- SCIP DB 기반 영업일 수익률 계산
- 모펀드 수익률 계산 (DWPM10510 MOD_STPR 기반)
- 인터랙티브 피봇 분석 (탭 상태 유지)
"""

import pandas as pd
import numpy as np
import json
from sqlalchemy import create_engine, text
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta

import dash
from dash import dcc, html, Input, Output, State, dash_table
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from dash_pivottable import PivotTable

# =========================
# 0) Parameters
# =========================
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"
CONN_STR_SCIP = "mysql+pymysql://solution:Solution123!@192.168.195.55/SCIP?charset=utf8mb4"
START_STD_DT = "20241201"

FUND_LIST = [
    '06X08','07G02','07G03','07G04','07J20','07J27','07J34','07J41',
    '07J48','07J49','07P70','07W15','08K88','08N33','08N81','08P22','09L94',
    '1JM96','1JM98','2JM23','4JM12'
]

# 대분류 순서 정의 (전역)
CATEGORY_ORDER = ['주식', '채권', '대체', '모펀드', '통화', '기타', '현금']
CATEGORY_ORDER_MAP = {cat: i for i, cat in enumerate(CATEGORY_ORDER)}

# =========================
# 1) 자동 분류 함수 (auto_classify.py 통합)
# =========================
def auto_classify_item(item_cd, item_nm):
    """
    종목명 기반 자동 분류

    Returns:
    --------
    dict or None
        {'대분류': str, '지역': str, '소분류': str} 또는 None (자동 분류 불가)
    """
    item_nm_upper = str(item_nm).upper()
    item_cd_upper = str(item_cd).upper()

    # 1. 콜론 (최우선)
    if '콜론' in item_nm_upper or '증권(콜론)' in item_nm_upper:
        return {'대분류': '현금', '지역': '국내', '소분류': '현금 등'}

    # 2. 금 관련
    if 'GOLD' in item_nm_upper or '금현물' in item_nm_upper or 'KRX금' in item_nm_upper:
        if 'KR' in item_cd_upper[:2]:
            return {'대분류': '대체', '지역': '국내', '소분류': '금'}
        else:
            return {'대분류': '대체', '지역': '글로벌', '소분류': '금'}

    # 3. 달러 선물
    if '달러 F' in item_nm_upper or 'USD F' in item_nm_upper or '미국달러 F' in item_nm_upper:
        return {'대분류': '통화', '지역': '미국', '소분류': '달러 선물'}

    # 4. 코스피 선물
    if '코스피' in item_nm_upper and ' F ' in item_nm_upper:
        return {'대분류': '주식', '지역': '국내', '소분류': '코스피 선물'}

    # 5. REPO
    if 'REPO' in item_nm_upper:
        return {'대분류': '채권', '지역': '국내', '소분류': 'REPO'}

    # 6. 예금/증거금
    if any(word in item_nm_upper for word in ['예금', '증거금', 'DEPOSIT']):
        if 'USD' in item_nm_upper or '외화' in item_nm_upper or 'DOLLAR' in item_nm_upper:
            return {'대분류': '현금', '지역': '미국', '소분류': '현금 등'}
        else:
            return {'대분류': '현금', '지역': '국내', '소분류': '현금 등'}

    # 7. 미수금/미지급금/청약금 등
    if any(word in item_nm_upper for word in ['미수', '미지급', '청약금', '원천세', '분배금', '기타자산']):
        return {'대분류': '현금', '지역': '국내', '소분류': '현금 등'}

    return None


# =========================
# 1-2) 현금/통화 필터링 함수 (비중/기여율 왜곡 제거용)
# =========================
def filter_holdings_for_weight(df):
    """
    비중/기여율 계산을 위해 holdings를 4개 그룹으로 분리

    정책:
    - 주식, 채권, 대체, 모펀드: 비중/기여율에 포함
    - 현금: "USD Deposit" 또는 "예금" 포함된 종목만 유지, 나머지 drop
    - 통화(달러 선물): 비중/기여율에서 제외, 환차손익 계산에만 사용

    Returns:
    --------
    tuple: (df_main, df_cash_keep, df_fx_hedge, df_cash_drop)
        - df_main: 주식/채권/대체/모펀드 종목
        - df_cash_keep: 유지할 현금 종목 (USD Deposit, 예금)
        - df_fx_hedge: 통화(달러선물) 종목 (비중 계산 제외)
        - df_cash_drop: 제외할 현금 종목 (디버깅용)
    """
    if df.empty:
        return df.copy(), df.iloc[:0].copy(), df.iloc[:0].copy(), df.iloc[:0].copy()

    # 대분류별 마스크 생성
    mask_main_categories = df['대분류'].isin(['주식', '채권', '대체', '모펀드'])
    mask_cash = df['대분류'] == '현금'
    mask_currency = df['대분류'] == '통화'

    # 현금 중 유지할 조건: "USD Deposit" 또는 "예금" 포함
    def is_keepable_cash(item_nm):
        item_nm_str = str(item_nm).upper()
        return 'USD DEPOSIT' in item_nm_str or '예금' in item_nm_str

    mask_cash_keep_condition = df['ITEM_NM'].apply(is_keepable_cash)

    # 통화 중 달러 선물만 유지
    mask_fx_hedge = mask_currency & (df['소분류'] == '달러 선물')

    # 4개 그룹으로 분리
    df_main = df[mask_main_categories].copy()
    df_cash_keep = df[mask_cash & mask_cash_keep_condition].copy()
    df_fx_hedge = df[mask_fx_hedge].copy()
    df_cash_drop = df[mask_cash & ~mask_cash_keep_condition].copy()

    # 디버깅 로그
    print(f"\n[INFO] 현금/통화 필터링 결과:")
    print(f"  - df_main (주식/채권/대체/모펀드): {len(df_main)} rows")
    print(f"  - df_cash_keep (USD Deposit/예금): {len(df_cash_keep)} rows")
    print(f"  - df_fx_hedge (달러선물): {len(df_fx_hedge)} rows")
    print(f"  - df_cash_drop (제외된 현금): {len(df_cash_drop)} rows")

    # drop된 현금 예시 출력 (최대 10개)
    if len(df_cash_drop) > 0:
        print(f"\n[DEBUG] 제외된 현금 종목 (최대 10개):")
        display_cols = ['ITEM_CD', 'ITEM_NM', 'EVL_AMT']
        display_cols = [c for c in display_cols if c in df_cash_drop.columns]
        print(df_cash_drop[display_cols].head(10).to_string(index=False))

    return df_main, df_cash_keep, df_fx_hedge, df_cash_drop


# =========================
# 2) 초기 마스터 생성 함수 (create_initial_master.py 통합)
# =========================

# 마스터 데이터 원본 (버전 관리용)
# [2026-01-30] 삭제됨: 1751100 미수ETF분배금, 1912100 기타자산, 000000000000 미지급외화거래비용
MASTER_DATA_RAW = """KR7332500008	ACE 200TR	주식	국내	일반
KR7367380003	ACE 미국나스닥100	주식	미국	일반
KR7453850000	ACE 미국30년국채액티브(H)	채권	미국	장기채
KR7356540005	ACE 종합채권(AA-이상)액티브	채권	국내	종합채권
KR7360200000	ACE 미국S&P500	주식	미국	일반
KR7363570003	KODEX 장기종합채권(AA-이상)액티브	채권	국내	종합채권
KR7365780006	ACE 국고채10년	채권	국내	장기채
KR7402970008	ACE 미국배당다우존스	주식	미국	일반
KR7438330003	TIGER 우량회사채액티브	채권	국내	투자등급
KR7458250008	TIGER 미국30년국채스트립액티브(합성 H)	채권	미국	장기채
KRZ501529957	한국투자크레딧포커스ESG자1호(채권)(C-W)	채권	국내	투자등급
KR7461270001	ACE 26-06 회사채(AA-이상)액티브	채권	국내	종합채권
US78464A5083	SPDR S&P 500 VALUE ETF	주식	미국	가치
US78464A4094	SPDR S&P 500 Growth	주식	미국	성장
US9229087443	VANGUARD VALUE ETF	주식	미국	가치
US9219438580	VANGUARD FTSE DEVELOPED ETF	주식	선진국	일반
US9220428588	VANGUARD FTSE EMERGING MARKETS	주식	신흥국	일반
US9219468850	Vanguard Emerging Markets Government Bond Index Fund	채권	신흥국	일반
US92206C6646	Vanguard Russell 2000 ETF	주식	미국	중소형
US9229087369	VANGUARD GROWTH ETF	주식	미국	성장
US9219468850	VANGUARD EMERG MKTS GOV BND	채권	신흥국	국채
032280007G02	한국투자인컴추구증권모투자신탁(채권혼합-	모펀드	모펀드	모펀드
032280007G03	한국투자수익추구증권모투자신탁(혼합-재간	모펀드	모펀드	모펀드
032280007J48	한국투자MySuper수익추구증권모투자신탁(혼	모펀드	모펀드	모펀드
032280007J49	한국투자MySuper인컴추구증권모투자신탁(채	모펀드	모펀드	모펀드
US46090F1003	INVESCO OPTIMUM YIELD DIVERS	대체	글로벌	혼합
US4642861037	ISHARES MSCI AUSTRALIA ETF	주식	호주	일반
US4642876142	ISHARES RUSSELL 1000 GROWTH	주식	미국	중소형
US4642877397	ISHARES US REAL ESTATE ETF	대체	미국	부동산
US46434V6478	ISHARES GLOBAL REIT ETF	대체	글로벌	부동산
US78463X8552	SPDR S&P Global Infrastructure	대체	글로벌	인프라
KR7152380002	KODEX 국채선물10년	채권	국내	장기채
KR7438570004	SOL 국고채10년	채권	국내	장기채
KR7471230003	KODEX 국고채10년액티브	채권	국내	장기채
US4642871762	ISHARES BARCLAYS TIPS BOND	채권	미국	물가채
US46435U8532	iShares Broad USD High Yield Corporate B	채권	미국	하이일드
US78468R6229	SPDR Bloomberg High Yield Bond ETF	채권	미국	하이일드
KR7114260003	KODEX 국고채3년	채권	국내	단기채
KR7114460009	ACE 국고채3년	채권	국내	단기채
KR7310960000	TIGER 200TR	주식	국내	일반
LU0772969993	FIDELITY GLOBAL DIVIDEND FUND A ACC USD	주식	글로벌	고배당
KR7273130005	KODEX 종합채권(AA-이상)액티브	채권	국내	종합채권
KR7484790001	KODEX 미국30년국채액티브(H)	채권	미국	장기채
KR7487340002	ACE 머니마켓액티브	채권	국내	단기채
KR7481430007	RISE 국고채10년액티브	채권	국내	장기채
KR7451530000	TIGER 국고채30년스트립액티브	채권	국내	장기채
KR70085N0005	ACE 미국10년국채액티브(H)	채권	미국	장기채
KR70085P0003	ACE 미국10년국채액티브	채권	미국	장기채
KR7105190003	ACE 200	주식	국내	일반
KR70127M0006	ACE 미국대형가치주액티브	주식	미국	가치
KR70127P0003	ACE 미국대형성장주액티브	주식	미국	성장
KRZ502649912	한국투자TMF26-12만기형증권투자신탁(채권)	채권	국내	단기채
KRZ502649922	한국투자TMF28-12만기형증권투자신탁(채권)	채권	국내	단기채"""


# =========================
# 3) 마스터 테이블 관리
# =========================
def load_master_mapping():
    """MASTER_DATA_RAW에서 마스터 테이블 로드"""
    lines = [line.split('\t') for line in MASTER_DATA_RAW.strip().split('\n')]
    df = pd.DataFrame(lines, columns=['ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류'])
    df['등록일'] = ''
    df['비고'] = ''
    print(f"[✓] 마스터 테이블 로드: {len(df)}개 종목")
    return df


def classify_with_master(holding_df, master_df):
    """마스터 테이블 기반 분류 + 자동 분류"""

    print(f"\n[DEBUG] Holding 총 {len(holding_df)}개 행, 고유 ITEM_CD {holding_df['ITEM_CD'].nunique()}개")
    print(f"[DEBUG] Master 총 {len(master_df)}개 행")

    # ITEM_CD를 문자열로 통일
    holding_df['ITEM_CD'] = holding_df['ITEM_CD'].astype(str).str.strip()
    master_df['ITEM_CD'] = master_df['ITEM_CD'].astype(str).str.strip()

    result = holding_df.merge(
        master_df[['ITEM_CD', '대분류', '지역', '소분류']],
        on='ITEM_CD',
        how='left'
    )

    matched = result['소분류'].notna().sum()
    total = len(result)
    print(f"[DEBUG] Merge 결과: {matched}/{total} ({matched/total*100:.1f}%) 매칭됨")

    # 미분류 종목
    unmapped = result[result['소분류'].isna()][
        ['STD_DT', 'ITEM_CD', 'ITEM_NM', 'AST_CLSF_CD_NM', 'EVL_AMT']
    ].drop_duplicates(subset=['ITEM_CD'])

    print(f"[DEBUG] 미분류 종목: {len(unmapped)}개")

    # 자동 분류 시도
    auto_classified = []
    for _, row in unmapped.iterrows():
        auto_result = auto_classify_item(row['ITEM_CD'], row['ITEM_NM'])
        if auto_result:
            auto_classified.append({
                'ITEM_CD': str(row['ITEM_CD']),
                'ITEM_NM': row['ITEM_NM'],
                '대분류': auto_result['대분류'],
                '지역': auto_result['지역'],
                '소분류': auto_result['소분류'],
                '등록일': datetime.now().strftime('%Y-%m-%d'),
                '비고': '자동분류'
            })

    # 자동 분류된 것 마스터에 추가
    if auto_classified:
        new_items_df = pd.DataFrame(auto_classified)

        # 중복 제거
        existing_codes = set(master_df['ITEM_CD'].astype(str).values)
        new_codes = set(new_items_df['ITEM_CD'].astype(str).values)
        duplicate_codes = new_codes & existing_codes

        if duplicate_codes:
            print(f"[AUTO] {len(duplicate_codes)}개 중복 종목 제외")

        new_items_df = new_items_df[~new_items_df['ITEM_CD'].isin(duplicate_codes)]

        if len(new_items_df) > 0:
            master_df = pd.concat([master_df, new_items_df], ignore_index=True)
            print(f"[AUTO] {len(new_items_df)}개 신규 종목 자동 분류됨")

        # result에도 자동 분류 반영
        for item in auto_classified:
            mask = result['ITEM_CD'] == item['ITEM_CD']
            result.loc[mask, '소분류'] = item['소분류']
            result.loc[mask, '대분류'] = item['대분류']
            result.loc[mask, '지역'] = item['지역']

        # unmapped에서 제외
        auto_codes = [item['ITEM_CD'] for item in auto_classified]
        unmapped = unmapped[~unmapped['ITEM_CD'].isin(auto_codes)]

    # 나머지 미분류는 '기타'로 임시 처리
    result['소분류'] = result['소분류'].fillna('기타')
    result['대분류'] = result['대분류'].fillna('기타')
    result['지역'] = result['지역'].fillna('기타')

    print(f"[DEBUG] 최종 '기타' 처리: {(result['대분류'] == '기타').sum()}개\n")

    return result, unmapped, master_df


# =========================
# 4) 수익률 계산 (SCIP DB 영업일 기준)
# =========================
def get_currency_from_item_cd(item_cd):
    """
    ITEM_CD 앞자리로 통화 구분
    KR로 시작: KRW
    US로 시작: USD
    """
    item_cd_str = str(item_cd).upper()
    if item_cd_str.startswith('KR'):
        return 'KRW'
    if item_cd_str.startswith('US'):
        return 'USD'
    return 'KRW'


def parse_price_blob(blob_data, currency):
    """
    Blob에서 통화별 가격 추출
    - currency: 'USD' 또는 'KRW'
    - blob 키는 소문자('usd', 'krw')일 수 있음
    """
    if blob_data is None:
        return None

    if isinstance(blob_data, (bytes, bytearray)):
        s = blob_data.decode('utf-8')
    else:
        s = str(blob_data)

    s = s.strip()

    if s.startswith('{') or s.startswith('['):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                # 대소문자 모두 시도 (blob이 소문자 키 사용할 수 있음)
                value = obj.get(currency) or obj.get(currency.lower())
                return float(value) if value is not None else None
            return float(obj)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    try:
        return float(s.replace(',', ''))
    except (ValueError, AttributeError):
        return None


def get_fx_rate(blob_data):
    """
    Blob에서 USD/KRW 환율 추출 (1 USD = X KRW)

    dataset_id=31의 blob에서 "USD" 값이 이미 환율 (KRW per 1 USD)
    """
    if blob_data is None:
        return None

    if isinstance(blob_data, (bytes, bytearray)):
        s = blob_data.decode('utf-8')
    else:
        s = str(blob_data)

    s = s.strip()

    if s.startswith('{') or s.startswith('['):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                # "USD" 값이 환율 (대소문자 모두 시도)
                value = obj.get('USD') or obj.get('usd')
                return float(value) if value is not None else None
            return float(obj)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    try:
        return float(s.replace(',', ''))
    except (ValueError, AttributeError):
        return None


def should_exclude_for_scip_return(item_nm, category):
    """SCIP 수익률 계산에서 제외할 종목 판단 (모펀드는 별도 계산)"""
    item_nm_upper = str(item_nm).upper()

    # 모펀드는 SCIP에서 제외 (별도 DWPM10510에서 계산)
    if category == '모펀드' or '모투자신탁' in item_nm:
        return True

    # 콜론, 선물, REPO, 예금/증거금, 미수/미지급 등 제외
    if '콜론' in item_nm_upper:
        return True
    if ('달러 F' in item_nm_upper or 'USD F' in item_nm_upper or
        ('코스피' in item_nm_upper and ' F ' in item_nm_upper)):
        return True
    if 'REPO' in item_nm_upper:
        return True
    if any(word in item_nm_upper for word in ['예금', '증거금', 'DEPOSIT']):
        return True
    if any(word in item_nm_upper for word in ['미수', '미지급', '청약금', '원천세', '분배금', '기타자산']):
        return True

    return False


def fetch_scip_available_dates(engine_scip, isin_list):
    """
    SCIP DB에서 실제 데이터가 존재하는 날짜 목록 조회
    Returns: sorted list of date objects (내림차순, 최신이 먼저)
    """
    if not isin_list:
        return []

    query = text("""
    SELECT DISTINCT DATE(dp.timestamp_observation) as date_value
    FROM SCIP.back_datapoint dp
    INNER JOIN SCIP.back_dataset d ON dp.dataset_id = d.id
    WHERE d.ISIN IN :isin_list
      AND dp.dataseries_id = 6
    ORDER BY date_value DESC
    """)

    try:
        with engine_scip.connect() as conn:
            result = pd.read_sql(query, conn, params={'isin_list': tuple(isin_list)})

        if result.empty:
            return []

        # date 객체로 변환하여 반환
        dates = pd.to_datetime(result['date_value']).dt.date.tolist()
        return sorted(dates, reverse=True)
    except Exception as e:
        print(f"[ERROR] fetch_scip_available_dates: {e}")
        return []


def find_business_day(target_date, available_dates, direction='on_or_before'):
    """
    target_date에 가장 가까운 영업일 찾기

    Parameters:
    -----------
    target_date : date
        찾고자 하는 기준 날짜
    available_dates : list of date
        실제 데이터가 존재하는 날짜 목록 (내림차순 정렬)
    direction : str
        'on_or_before' - target_date 이하 중 가장 최근
        'before' - target_date 미만 중 가장 최근

    Returns:
    --------
    date or None
    """
    if not available_dates:
        return None

    if isinstance(target_date, datetime):
        target_date = target_date.date()

    for d in available_dates:
        if direction == 'on_or_before':
            if d <= target_date:
                return d
        elif direction == 'before':
            if d < target_date:
                return d

    return None


def calculate_period_base_dates(latest_date, available_dates):
    """
    각 기간별 기준일 계산 (영업일 기준)

    Parameters:
    -----------
    latest_date : date
        최신 영업일
    available_dates : list of date
        실제 데이터가 존재하는 날짜 목록

    Returns:
    --------
    dict: {'1D': date, '1W': date, '1M': date, '3M': date, '6M': date, 'YTD': date}
    """
    if isinstance(latest_date, datetime):
        latest_date = latest_date.date()

    # YTD 시작일: 당해년도 첫 영업일
    ytd_start_target = date(latest_date.year, 1, 1)

    # 각 기간별 타겟 날짜 계산
    period_targets = {
        '1D': latest_date - timedelta(days=1),
        '1W': latest_date - timedelta(days=7),
        '1M': latest_date - relativedelta(months=1),
        '3M': latest_date - relativedelta(months=3),
        '6M': latest_date - relativedelta(months=6),
        'YTD': ytd_start_target
    }

    # 각 타겟 날짜에서 가장 가까운 영업일 찾기
    base_dates = {}
    for period, target in period_targets.items():
        if period == '1D':
            # 1D는 최신일의 직전 영업일
            base_dates[period] = find_business_day(target, available_dates, 'on_or_before')
        elif period == 'YTD':
            # YTD는 해당년도 첫 영업일 (1/1 이후 첫 데이터)
            ytd_date = None
            for d in reversed(available_dates):  # 오름차순으로 순회
                if d >= ytd_start_target:
                    ytd_date = d
                    break
            base_dates[period] = ytd_date
        else:
            base_dates[period] = find_business_day(target, available_dates, 'on_or_before')

    return base_dates


def fetch_factset_returns_with_dates(master_df, engine_scip):
    """
    SCIP DB에서 FactSet 수익률 데이터 조회 (영업일 기반)
    모펀드는 제외 (별도 DWPM10510에서 조회)

    Returns:
    --------
    tuple: (return_df, available_dates, latest_date, base_dates)
    """
    # 수익률 계산 대상 종목 필터링 (모펀드 제외)
    items_for_return = master_df[
        ~master_df.apply(lambda row: should_exclude_for_scip_return(row['ITEM_NM'], row.get('대분류', '')), axis=1)
    ].copy()

    if len(items_for_return) == 0:
        print("[INFO] SCIP 수익률 계산 대상 종목이 없습니다")
        return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index']), [], None, {}

    isin_list = items_for_return['ITEM_CD'].tolist()

    print(f"[INFO] SCIP 수익률 조회 대상: {len(isin_list)}개 종목 (모펀드 제외)")

    # Step 1: 실제 데이터 존재 날짜 조회
    available_dates = fetch_scip_available_dates(engine_scip, isin_list)

    if not available_dates:
        print("[WARNING] SCIP DB에서 데이터를 찾을 수 없습니다")
        return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index']), [], None, {}

    latest_date = available_dates[0]  # 최신 영업일
    print(f"[INFO] SCIP 최신 영업일: {latest_date}")
    print(f"[INFO] SCIP 데이터 기간: {available_dates[-1]} ~ {latest_date}")

    # Step 2: 기간별 기준일 계산
    base_dates = calculate_period_base_dates(latest_date, available_dates)
    print(f"[INFO] 기간별 기준일:")
    for period, base_date in base_dates.items():
        print(f"  - {period}: {base_date}")

    # Step 3: 데이터 조회 (1년 + buffer)
    start_date = latest_date - timedelta(days=400)

    query = text("""
    SELECT
        d.ISIN as ITEM_CD,
        DATE(dp.timestamp_observation) as date,
        dp.data
    FROM SCIP.back_datapoint dp
    INNER JOIN SCIP.back_dataset d ON dp.dataset_id = d.id
    WHERE d.ISIN IN :isin_list
      AND dp.dataseries_id = 6
      AND dp.timestamp_observation >= :start_date
      AND dp.timestamp_observation <= :end_date
    ORDER BY d.ISIN, dp.timestamp_observation
    """)

    try:
        with engine_scip.connect() as conn:
            df_raw = pd.read_sql(
                query, conn,
                params={
                    'isin_list': tuple(isin_list),
                    'start_date': start_date,
                    'end_date': latest_date
                }
            )

        print(f"[INFO] SCIP 조회된 raw datapoints: {len(df_raw)}개")

        if df_raw.empty:
            return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index']), available_dates, latest_date, base_dates

        # 데이터 파싱 (통화별)
        df_raw['currency'] = df_raw['ITEM_CD'].apply(get_currency_from_item_cd)
        df_raw['return_index'] = df_raw.apply(
            lambda row: parse_price_blob(row['data'], row['currency']),
            axis=1
        )

        # 디버그: 통화별 파싱 결과 확인
        currency_counts = df_raw['currency'].value_counts()
        print(f"[DEBUG] 통화별 종목 수: {currency_counts.to_dict()}")

        # USD 종목 샘플 확인
        usd_sample = df_raw[df_raw['currency'] == 'USD'].head(3)
        if not usd_sample.empty:
            print(f"[DEBUG] USD 종목 샘플:")
            for _, row in usd_sample.iterrows():
                print(f"  - {row['ITEM_CD']}: currency={row['currency']}, return_index={row['return_index']}")

        df_raw = df_raw.dropna(subset=['return_index'])
        df_raw = df_raw.sort_values(['ITEM_CD', 'date'])
        df_raw = df_raw.drop_duplicates(subset=['ITEM_CD', 'date'], keep='last')

        result = df_raw[['ITEM_CD', 'date', 'return_index']].copy()
        print(f"[INFO] SCIP 파싱된 데이터: {len(result)}개 ({result['ITEM_CD'].nunique()}개 종목)")

        return result, available_dates, latest_date, base_dates

    except Exception as e:
        print(f"[ERROR] fetch_factset_returns_with_dates: {e}")
        return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index']), [], None, {}


# =========================
# 4-1) 환율 조회 (SCIP)
# =========================
def fetch_fx_rates(engine_scip, target_dates):
    """
    SCIP DB에서 USD/KRW 환율 데이터 조회 (dataset_id=31, dataseries_id=6)

    blob의 "USD" 값이 환율 (KRW per 1 USD)

    Returns:
    --------
    dict: {date: fx_rate (1 USD = X KRW)}
    """
    if not target_dates:
        return {}

    query_fx = text("""
    SELECT
        DATE(dp.timestamp_observation) AS date,
        dp.data
    FROM SCIP.back_datapoint dp
    WHERE dp.dataset_id = 31
      AND dp.dataseries_id = 6
      AND DATE(dp.timestamp_observation) IN :target_dates
    ORDER BY DATE(dp.timestamp_observation)
    """)

    try:
        with engine_scip.connect() as conn:
            df_fx = pd.read_sql(query_fx, conn, params={'target_dates': tuple(target_dates)})

        fx_rates = {}
        for _, row in df_fx.iterrows():
            fx_rate = get_fx_rate(row['data'])
            if fx_rate is not None:
                fx_rates[row['date']] = fx_rate

        return fx_rates
    except Exception as e:
        print(f"[ERROR] fetch_fx_rates: {e}")
        return {}


# =========================
# 5) 모펀드 수익률 계산 (DWPM10510 MOD_STPR 기반)
# =========================
def fetch_mofund_returns(master_df, engine, latest_date, base_dates):
    """
    모펀드 수익률 계산 (DWPM10510의 MOD_STPR 기반)

    모펀드 ITEM_CD 마지막 5자리를 FUND_CD로 변환하여 조회

    Returns:
    --------
    DataFrame with columns: ITEM_CD, 1D, 1W, 1M, 3M, 6M, YTD, Last Updated
    """
    # 모펀드 종목 추출
    mofund_items = master_df[master_df['대분류'] == '모펀드'].copy()

    if mofund_items.empty:
        print("[INFO] 모펀드 종목이 없습니다")
        return pd.DataFrame(columns=['ITEM_CD', '1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated'])

    # ITEM_CD 마지막 5자리를 FUND_CD로 변환
    mofund_items['FUND_CD'] = mofund_items['ITEM_CD'].apply(lambda x: str(x)[-5:] if len(str(x)) >= 5 else str(x))
    mofund_fund_codes = mofund_items['FUND_CD'].tolist()
    item_to_fund_map = dict(zip(mofund_items['ITEM_CD'], mofund_items['FUND_CD']))

    print(f"[INFO] 모펀드 수익률 조회 대상: {len(mofund_fund_codes)}개 펀드")
    print(f"[INFO] 모펀드 FUND_CD 목록: {mofund_fund_codes}")

    if not latest_date or not base_dates:
        print("[WARNING] 기준일 정보가 없어 모펀드 수익률 계산 불가")
        return pd.DataFrame(columns=['ITEM_CD', '1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated'])

    # YTD 시작일 ~ 최신일까지 데이터 조회
    ytd_start = base_dates.get('YTD')
    if ytd_start is None:
        ytd_start = date(latest_date.year, 1, 1)

    # 날짜를 YYYYMMDD 형식으로 변환
    start_dt_int = int(ytd_start.strftime('%Y%m%d'))
    end_dt_int = int(latest_date.strftime('%Y%m%d'))

    query = text("""
    SELECT
        STD_DT,
        FUND_CD,
        MOD_STPR
    FROM dt.DWPM10510
    WHERE STD_DT BETWEEN :start_dt AND :end_dt
      AND FUND_CD IN :fund_list
    ORDER BY FUND_CD, STD_DT
    """)

    try:
        with engine.connect() as conn:
            df_metrics = pd.read_sql(
                query, conn,
                params={
                    'start_dt': start_dt_int,
                    'end_dt': end_dt_int,
                    'fund_list': tuple(mofund_fund_codes)
                }
            )

        print(f"[INFO] 모펀드 MOD_STPR 조회: {len(df_metrics)}개 레코드")

        if df_metrics.empty:
            return pd.DataFrame(columns=['ITEM_CD', '1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated'])

        # 날짜를 date 객체로 변환
        df_metrics['date'] = df_metrics['STD_DT'].apply(lambda x: datetime.strptime(str(int(x)), '%Y%m%d').date())

        results = []

        # 각 FUND_CD별로 수익률 계산
        for item_cd, fund_cd in item_to_fund_map.items():
            fund_data = df_metrics[df_metrics['FUND_CD'] == fund_cd].sort_values('date')

            if fund_data.empty:
                print(f"[WARNING] 모펀드 {fund_cd} ({item_cd}) 데이터 없음")
                continue

            # 최신 데이터
            latest_data = fund_data[fund_data['date'] <= latest_date]
            if latest_data.empty:
                continue

            latest_price = latest_data.iloc[-1]['MOD_STPR']
            last_updated = latest_data.iloc[-1]['date']

            row = {
                'ITEM_CD': item_cd,
                'Last Updated': last_updated.strftime('%Y-%m-%d') if last_updated else '-'
            }

            # 각 기간별 수익률 계산
            for period_name, base_date in base_dates.items():
                if base_date is None:
                    row[period_name] = np.nan
                    continue

                # base_date 이하의 가장 최근 데이터
                period_data = fund_data[fund_data['date'] <= base_date]

                if period_data.empty:
                    row[period_name] = np.nan
                else:
                    base_price = period_data.iloc[-1]['MOD_STPR']
                    if base_price > 0:
                        row[period_name] = round((latest_price / base_price - 1) * 100, 2)
                    else:
                        row[period_name] = np.nan

            results.append(row)

        result_df = pd.DataFrame(results)
        print(f"[INFO] 모펀드 수익률 계산 완료: {len(result_df)}개 종목")

        return result_df

    except Exception as e:
        print(f"[ERROR] fetch_mofund_returns: {e}")
        return pd.DataFrame(columns=['ITEM_CD', '1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated'])


def calculate_return_periods_v2(return_df, latest_date, base_dates, fx_rates=None):
    """
    영업일 기준 수익률 계산 (v2) - SCIP 데이터용

    USD 자산의 경우 미국 시장 시차 반영:
    - KRW 기준가(T) = USD 가격(T-1) × 환율(T)
    - 수익률 = [USD(T-1) × FX(T)] / [USD(T-2) × FX(T-1)] - 1

    Returns:
    --------
    DataFrame with columns: ITEM_CD, 1D, 1W, 1M, 3M, 6M, YTD, Last Updated
    """
    if return_df.empty or latest_date is None:
        return pd.DataFrame(columns=['ITEM_CD', '1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated'])

    return_df = return_df.copy()
    return_df['date'] = pd.to_datetime(return_df['date']).dt.date

    # 전체 날짜 목록 (정렬)
    all_dates = sorted(return_df['date'].unique())

    def get_prev_date(target_date, dates_list):
        """target_date 이전 날짜 반환"""
        prev_dates = [d for d in dates_list if d < target_date]
        return prev_dates[-1] if prev_dates else None

    results = []

    for item_cd in return_df['ITEM_CD'].unique():
        item_data = return_df[return_df['ITEM_CD'] == item_cd].sort_values('date')
        currency = get_currency_from_item_cd(item_cd)

        if item_data.empty:
            continue

        # USD 자산: T-1 시차 적용
        if currency == 'USD':
            # USD 자산의 경우 T-1 가격을 사용
            # latest_date 이전의 가장 최근 데이터가 "오늘의 USD 가격"
            latest_data = item_data[item_data['date'] < latest_date]
            if latest_data.empty:
                # T-1 데이터가 없으면 latest_date 데이터 사용 (fallback)
                latest_data = item_data[item_data['date'] <= latest_date]
                if latest_data.empty:
                    continue

            latest_value = latest_data.iloc[-1]['return_index']  # USD(T-1)
            last_updated = latest_data.iloc[-1]['date']

            row = {
                'ITEM_CD': item_cd,
                'Last Updated': last_updated.strftime('%Y-%m-%d') if last_updated else '-'
            }

            # 각 기간별 수익률 계산
            for period_name, base_date in base_dates.items():
                if base_date is None:
                    row[period_name] = np.nan
                    continue

                # USD 자산: base_date도 하루 이전 데이터 사용 (T-2 for 1D)
                # base_date 이전의 가장 최근 데이터
                period_data = item_data[item_data['date'] < base_date]
                if period_data.empty:
                    # fallback: base_date 이하
                    period_data = item_data[item_data['date'] <= base_date]

                if period_data.empty:
                    row[period_name] = np.nan
                else:
                    period_value = period_data.iloc[-1]['return_index']  # USD(T-2 for 1D)
                    if period_value > 0:
                        # 순수 USD 수익률 (T-2 → T-1)
                        usd_return = (latest_value / period_value - 1) * 100
                        row[period_name] = round(usd_return, 2)
                    else:
                        row[period_name] = np.nan

            results.append(row)

        else:
            # KRW 자산: 기존 로직 그대로
            latest_data = item_data[item_data['date'] <= latest_date]
            if latest_data.empty:
                continue

            latest_value = latest_data.iloc[-1]['return_index']
            last_updated = latest_data.iloc[-1]['date']

            row = {
                'ITEM_CD': item_cd,
                'Last Updated': last_updated.strftime('%Y-%m-%d') if last_updated else '-'
            }

            # 각 기간별 수익률 계산
            for period_name, base_date in base_dates.items():
                if base_date is None:
                    row[period_name] = np.nan
                    continue

                # base_date 이하의 가장 최근 데이터
                period_data = item_data[item_data['date'] <= base_date]

                if period_data.empty:
                    row[period_name] = np.nan
                else:
                    period_value = period_data.iloc[-1]['return_index']
                    if period_value > 0:
                        row[period_name] = round((latest_value / period_value - 1) * 100, 2)
                    else:
                        row[period_name] = np.nan

            results.append(row)

    result_df = pd.DataFrame(results)
    print(f"[INFO] SCIP 수익률 계산 완료: {len(result_df)}개 종목 (USD 자산 T-1 시차 적용)")

    return result_df


# =========================
# 6) 데이터 로드
# =========================
print("\n" + "="*80)
print("[INFO] 데이터 로딩 시작")
print("="*80)

# 마스터 데이터 로드
print("[INFO] Loading master mapping...")
master_mapping = load_master_mapping()
print(f"[INFO] Master mapping loaded: {len(master_mapping)} items")

# DB 연결
print("[INFO] Loading data from DB...")
engine = create_engine(CONN_STR)
engine_scip = create_engine(CONN_STR_SCIP)

# 영업일 캘린더
query_BDay = """
SELECT std_dt
FROM dt.DWCI10220
WHERE std_dt >= :start_dt
  AND hldy_yn = 'N'
  AND day_ds_cd IN (2,3,4,5,6)
ORDER BY std_dt;
"""
with engine.connect() as conn:
    bdays = pd.read_sql(text(query_BDay), conn, params={"start_dt": START_STD_DT})

if bdays.empty:
    raise ValueError("영업일 캘린더 조회 결과가 없습니다.")

END_STD_DT = str(int(bdays["std_dt"].max()))
print(f"[INFO] Date range: {START_STD_DT} ~ {END_STD_DT}")

# Holdings
query_holding = """
SELECT
    STD_DT,
    FUND_CD,
    FUND_NM,
    ITEM_CD,
    ITEM_NM,
    MAX(AST_CLSF_CD_NM) AS AST_CLSF_CD_NM,
    SUM(EVL_AMT) AS EVL_AMT
FROM dt.DWPM10530
WHERE STD_DT BETWEEN :start_dt AND :end_dt
  AND EVL_AMT > 0
  AND FUND_CD IN :fund_list
GROUP BY STD_DT, FUND_CD, FUND_NM, ITEM_CD, ITEM_NM
ORDER BY STD_DT, FUND_CD;
"""

# Fund metrics (FUND_LIST + 모펀드용)
# 모펀드 FUND_CD 추출 (ITEM_CD 마지막 5자리)
mofund_items = master_mapping[master_mapping['대분류'] == '모펀드']
mofund_fund_codes = mofund_items['ITEM_CD'].apply(lambda x: str(x)[-5:] if len(str(x)) >= 5 else str(x)).tolist()
all_fund_codes = list(set(FUND_LIST + mofund_fund_codes))

query_metrics = """
SELECT
    STD_DT,
    FUND_CD,
    MOD_STPR,
    NAST_AMT
FROM dt.DWPM10510
WHERE STD_DT BETWEEN :start_dt AND :end_dt
  AND FUND_CD IN :fund_list
ORDER BY STD_DT, FUND_CD;
"""

fund_tuple = tuple(FUND_LIST)
metrics_fund_tuple = tuple(all_fund_codes)
with engine.connect() as conn:
    holding = pd.read_sql(
        text(query_holding), conn,
        params={"start_dt": START_STD_DT, "end_dt": END_STD_DT, "fund_list": fund_tuple}
    )
    metrics = pd.read_sql(
        text(query_metrics), conn,
        params={"start_dt": START_STD_DT, "end_dt": END_STD_DT, "fund_list": metrics_fund_tuple}
    )

print(f"[INFO] Loaded {len(holding)} holding records, {len(metrics)} metric records")

# 펀드명 매핑 생성
FUND_NAMES = holding[['FUND_CD', 'FUND_NM']].drop_duplicates().set_index('FUND_CD')['FUND_NM'].to_dict()
print(f"[INFO] Fund names mapped: {len(FUND_NAMES)} funds")

# 날짜 변환
holding['STD_DT_INT'] = holding['STD_DT']
holding['STD_DT'] = holding['STD_DT'].apply(lambda x: datetime.strptime(str(int(x)), '%Y%m%d').date())
metrics['STD_DT_DATE'] = metrics['STD_DT'].apply(lambda x: datetime.strptime(str(int(x)), '%Y%m%d'))

# 자산군 분류
print("[INFO] Classifying assets with master mapping...")
holding, unmapped, master_mapping = classify_with_master(holding, master_mapping)
print(f"[INFO] Master now contains {len(master_mapping)} items")

# 날짜 리스트
available_dates = sorted(holding['STD_DT'].unique())
holding_latest_date = available_dates[-1]

# =========================
# 7) 수익률 데이터 로드 (SCIP + 모펀드)
# =========================
print("\n[INFO] Fetching return data (SCIP + 모펀드)...")

# Step 1: SCIP에서 일반 종목 수익률 조회
factset_returns, scip_available_dates, scip_latest_date, base_dates = fetch_factset_returns_with_dates(
    master_mapping, engine_scip
)

# SCIP 수익률 계산
scip_return_periods = calculate_return_periods_v2(factset_returns, scip_latest_date, base_dates)
print(f"[INFO] SCIP return data: {len(scip_return_periods)} items")

# =========================
# DEBUG: VANGUARD FTSE EMERGING MARKETS 상세 분석
# =========================
DEBUG_ITEM_CD = 'US9220428588'  # VANGUARD FTSE EMERGING MARKETS
DEBUG_ITEM_NM = 'VANGUARD FTSE EMERGING MARKETS'

print(f"\n{'='*70}")
print(f"[DEBUG] === {DEBUG_ITEM_NM} (Fund: 08K88) ===")
print(f"{'='*70}")

# 최근 5영업일 가격 데이터 조회
debug_price_data = factset_returns[factset_returns['ITEM_CD'] == DEBUG_ITEM_CD].copy()
if not debug_price_data.empty:
    debug_price_data = debug_price_data.sort_values('date', ascending=False).head(5)
    print(f"\nLast 5 Days Price History (USD):")
    for _, row in debug_price_data.iterrows():
        print(f"  {row['date']}: USD {row['return_index']:.4f}")

    # 1D 수익률 계산 상세
    if len(debug_price_data) >= 2:
        latest_row = debug_price_data.iloc[0]
        prev_row = debug_price_data.iloc[1]

        t0_price = latest_row['return_index']
        t1_price = prev_row['return_index']
        t0_date = latest_row['date']
        t1_date = prev_row['date']

        usd_return = (t0_price / t1_price - 1) * 100

        print(f"\n1D Return Calculation ({t0_date}):")
        print(f"  T-1 Date:  {t1_date}")
        print(f"  T-1 Price: USD {t1_price:.4f}")
        print(f"  T-0 Date:  {t0_date}")
        print(f"  T-0 Price: USD {t0_price:.4f}")
        print(f"  USD Return: ({t0_price:.4f} / {t1_price:.4f} - 1) = {usd_return:.4f}%")
else:
    print(f"[WARNING] {DEBUG_ITEM_CD} 가격 데이터 없음")

# FX 환율 조회 (최근 5일)
print(f"\nFX Rate Query for Last 5 Days...")
query_fx_debug = text("""
SELECT
    DATE(dp.timestamp_observation) AS date,
    dp.data
FROM SCIP.back_datapoint dp
WHERE dp.dataset_id = 31
  AND dp.dataseries_id = 6
ORDER BY dp.timestamp_observation DESC
LIMIT 10
""")
with engine_scip.connect() as conn:
    fx_debug_df = pd.read_sql(query_fx_debug, conn)

if not fx_debug_df.empty:
    print(f"\nLast 5 Days FX Rate (KRW/USD):")
    fx_debug_rates = {}
    for _, row in fx_debug_df.head(5).iterrows():
        fx_val = get_fx_rate(row['data'])
        fx_debug_rates[row['date']] = fx_val
        print(f"  {row['date']}: {fx_val:,.2f} KRW/USD" if fx_val else f"  {row['date']}: N/A")

    # FX 수익률 계산 (1D)
    fx_dates = sorted(fx_debug_rates.keys(), reverse=True)
    if len(fx_dates) >= 2 and fx_debug_rates.get(fx_dates[0]) and fx_debug_rates.get(fx_dates[1]):
        fx_t0 = fx_debug_rates[fx_dates[0]]
        fx_t1 = fx_debug_rates[fx_dates[1]]
        fx_return = (fx_t0 / fx_t1 - 1) * 100

        print(f"\n1D FX Return Calculation:")
        print(f"  T-1 FX ({fx_dates[1]}): {fx_t1:,.2f}")
        print(f"  T-0 FX ({fx_dates[0]}): {fx_t0:,.2f}")
        print(f"  FX Return: ({fx_t0:,.2f} / {fx_t1:,.2f} - 1) = {fx_return:.4f}%")

        # Combined KRW Return
        if not debug_price_data.empty and len(debug_price_data) >= 2:
            combined_return = ((1 + usd_return/100) * (1 + fx_return/100) - 1) * 100
            print(f"\nCombined KRW Return:")
            print(f"  (1 + {usd_return:.4f}%) × (1 + {fx_return:.4f}%) - 1")
            print(f"  = ({1 + usd_return/100:.6f}) × ({1 + fx_return/100:.6f}) - 1")
            print(f"  = {combined_return:.4f}%")

# scip_return_periods에서 해당 종목 확인
debug_return = scip_return_periods[scip_return_periods['ITEM_CD'] == DEBUG_ITEM_CD]
if not debug_return.empty:
    print(f"\nSCIP Return Periods (before FX):")
    for col in ['1D', '1W', '1M', '3M', '6M', 'YTD']:
        val = debug_return.iloc[0].get(col, 'N/A')
        print(f"  {col}: {val}")

print(f"{'='*70}\n")

# Step 2: 모펀드 수익률 계산 (DWPM10510)
mofund_return_periods = fetch_mofund_returns(master_mapping, engine, scip_latest_date, base_dates)
print(f"[INFO] 모펀드 return data: {len(mofund_return_periods)} items")

# Step 3: SCIP + 모펀드 수익률 병합
return_periods = pd.concat([scip_return_periods, mofund_return_periods], ignore_index=True)

# 중복 ITEM_CD 제거 (first 유지)
if return_periods['ITEM_CD'].duplicated().any():
    dup_count = return_periods['ITEM_CD'].duplicated().sum()
    print(f"[WARNING] return_periods에 중복 ITEM_CD {dup_count}개 발견 → 제거")
    return_periods = return_periods.drop_duplicates(subset=['ITEM_CD'], keep='first')

print(f"[INFO] Total return data: {len(return_periods)} items")

# Step 4: 환율 반영 (USD 종목 KRW 환산)
fx_target_dates = [scip_latest_date] + [d for d in base_dates.values() if d is not None]
fx_target_dates = sorted(set([d for d in fx_target_dates if d is not None]))
fx_rates = fetch_fx_rates(engine_scip, fx_target_dates)

# 디버그: FX 환율 조회 결과
print(f"\n[DEBUG] === FX 환율 디버그 ===")
print(f"[DEBUG] FX 조회 대상 날짜: {fx_target_dates}")
print(f"[DEBUG] FX 조회 결과: {fx_rates}")

fx_return_by_period = {}
fx_latest = fx_rates.get(scip_latest_date)
print(f"[DEBUG] FX 최신일({scip_latest_date}) 환율: {fx_latest}")

for period, base_date in base_dates.items():
    fx_base = fx_rates.get(base_date)
    if fx_latest is not None and fx_base is not None and fx_base != 0:
        fx_return_by_period[period] = (fx_latest / fx_base - 1) * 100
        print(f"[DEBUG] FX {period}: base_date={base_date}, fx_base={fx_base}, fx_return={fx_return_by_period[period]:.4f}%")
    else:
        fx_return_by_period[period] = 0
        print(f"[DEBUG] FX {period}: base_date={base_date}, fx_base={fx_base}, fx_return=0 (데이터 없음)")

print(f"[DEBUG] 최종 FX 수익률: {fx_return_by_period}")

# FX 수익률을 전역 변수로 저장 (대시보드에서 사용)
# NOTE: apply_fx_to_returns 제거 - 순수 USD 수익률 유지, FX는 별도 행으로 표시
FX_RETURN_BY_PERIOD = fx_return_by_period

# 디버그: USD 종목 순수 수익률 확인
print(f"\n[DEBUG] === USD 종목 순수 수익률 (FX 미적용) ===")
usd_items_debug = return_periods[return_periods['ITEM_CD'].apply(lambda x: str(x).upper().startswith('US'))]
if not usd_items_debug.empty:
    print(f"[DEBUG] USD 종목 수: {len(usd_items_debug)}개")
    for _, row in usd_items_debug.head(5).iterrows():
        print(f"  - {row['ITEM_CD']}: 1D={row.get('1D', 'N/A')}, 1W={row.get('1W', 'N/A')}, 1M={row.get('1M', 'N/A')}")

# DEBUG: VANGUARD FTSE EMERGING MARKETS 순수 USD 수익률
debug_final = return_periods[return_periods['ITEM_CD'] == DEBUG_ITEM_CD]
if not debug_final.empty:
    print(f"\n{'='*70}")
    print(f"[DEBUG] === {DEBUG_ITEM_NM} 순수 USD 수익률 ===")
    print(f"{'='*70}")
    row = debug_final.iloc[0]
    print(f"  1D:  {row.get('1D', 'N/A')}%")
    print(f"  1W:  {row.get('1W', 'N/A')}%")
    print(f"  1M:  {row.get('1M', 'N/A')}%")
    print(f"  3M:  {row.get('3M', 'N/A')}%")
    print(f"  6M:  {row.get('6M', 'N/A')}%")
    print(f"  YTD: {row.get('YTD', 'N/A')}%")
    print(f"{'='*70}\n")

# Merge return data with holding
if not return_periods.empty:
    holding = holding.merge(return_periods, on='ITEM_CD', how='left')

# Merge 후 중복 확인 (STD_DT, FUND_CD, ITEM_CD 기준)
dup_check = holding.duplicated(subset=['STD_DT', 'FUND_CD', 'ITEM_CD'], keep=False)
if dup_check.any():
    dup_count = dup_check.sum()
    print(f"[WARNING] holding merge 후 중복 발견: {dup_count}개 행")
    print(f"[WARNING] 중복 샘플:")
    print(holding[dup_check][['STD_DT', 'FUND_CD', 'ITEM_CD', 'ITEM_NM']].head(5))
    # 중복 제거 (first 유지)
    holding = holding.drop_duplicates(subset=['STD_DT', 'FUND_CD', 'ITEM_CD'], keep='first')
    print(f"[INFO] 중복 제거 후: {len(holding)}개 행")

# 펀드 수익률 계산 (차트용)
metrics_for_chart = metrics[metrics['FUND_CD'].isin(FUND_LIST)].copy()
metrics_for_chart = metrics_for_chart.sort_values(['FUND_CD', 'STD_DT'])
metrics_for_chart['RET'] = metrics_for_chart.groupby('FUND_CD')['MOD_STPR'].transform(
    lambda x: (x / x.iloc[0] - 1) * 100
)

print(f"[INFO] Holdings latest date: {holding_latest_date}")
print(f"[INFO] SCIP latest date: {scip_latest_date}")
print(f"[INFO] Unmapped items: {len(unmapped)}")

# =========================
# DEBUG: 08K88 펀드 수익률 분해 (1D 기준)
# =========================
DEBUG_FUND = '08K88'
debug_holding = holding[(holding['FUND_CD'] == DEBUG_FUND) & (holding['STD_DT'] == holding_latest_date)].copy()

if not debug_holding.empty:
    debug_total = debug_holding['EVL_AMT'].sum()
    debug_holding['WEIGHT'] = (debug_holding['EVL_AMT'] / debug_total * 100)
    debug_holding['IS_USD'] = debug_holding['ITEM_CD'].apply(lambda x: str(x).upper().startswith('US'))

    print(f"\n{'='*70}")
    print(f"[DEBUG] === {DEBUG_FUND} 수익률 분해 (1D 기준, {holding_latest_date}) ===")
    print(f"{'='*70}")

    # 대분류별 집계
    for cat in ['주식', '채권', '대체', '현금', '모펀드']:
        cat_data = debug_holding[debug_holding['대분류'] == cat]
        if cat_data.empty:
            continue

        cat_weight = cat_data['WEIGHT'].sum()
        krw_data = cat_data[~cat_data['IS_USD']]
        usd_data = cat_data[cat_data['IS_USD']]

        krw_weight = krw_data['WEIGHT'].sum()
        usd_weight = usd_data['WEIGHT'].sum()

        # KRW 자산 가중수익률
        krw_return_sum = 0
        if not krw_data.empty:
            for _, row in krw_data.iterrows():
                ret = row.get('1D', 0)
                if pd.notna(ret) and ret != '':
                    krw_return_sum += float(ret) * row['WEIGHT'] / 100

        # USD 자산 가중수익률 (순수 USD)
        usd_return_sum = 0
        if not usd_data.empty:
            for _, row in usd_data.iterrows():
                ret = row.get('1D', 0)
                if pd.notna(ret) and ret != '':
                    usd_return_sum += float(ret) * row['WEIGHT'] / 100

        cat_return_sum = krw_return_sum + usd_return_sum

        if krw_weight > 0:
            print(f"  {cat}(KRW): {krw_weight:.2f}% × {krw_return_sum/krw_weight*100:.2f}% = {krw_return_sum:.4f}%")
        if usd_weight > 0:
            print(f"  {cat}(USD): {usd_weight:.2f}% × {usd_return_sum/usd_weight*100:.2f}% = {usd_return_sum:.4f}% (순수 USD)")
        if cat_weight > 0:
            print(f"  ▶ {cat}소계: {cat_weight:.2f}% 비중, {cat_return_sum:.4f}% 수익률")
        print()

    # 전체 USD 비중 및 환차익
    total_usd_weight = debug_holding[debug_holding['IS_USD']]['WEIGHT'].sum()
    fx_1d = FX_RETURN_BY_PERIOD.get('1D', 0)
    fx_impact_1d = total_usd_weight * fx_1d / 100

    print(f"  환차익: {total_usd_weight:.2f}% × {fx_1d:.4f}% = {fx_impact_1d:.4f}%")

    # 순수 자산 총수익률
    total_pure_return = 0
    for _, row in debug_holding.iterrows():
        ret = row.get('1D', 0)
        if pd.notna(ret) and ret != '':
            total_pure_return += float(ret) * row['WEIGHT'] / 100

    total_return = total_pure_return + fx_impact_1d
    print(f"\n  순수자산수익률: {total_pure_return:.4f}%")
    print(f"  + 환차익: {fx_impact_1d:.4f}%")
    print(f"  = 총수익률: {total_return:.4f}%")
    print(f"{'='*70}\n")

# =========================
# 8) Pivot 분석용 데이터 준비
# =========================
def prepare_pivot_data(holding_df, metrics_df, return_periods_df):
    """피봇 분석용 데이터 준비 (수익률, 비중)

    [NEW] 현금/통화 필터링 적용:
    - 주식/채권/대체/모펀드: 포함
    - 현금: "USD Deposit" 또는 "예금" 포함된 종목만 유지
    - 통화(달러선물): 제외
    """
    pivot_data = holding_df.copy()

    # =========================
    # [NEW] 현금/통화 필터링 적용
    # =========================
    mask_main = pivot_data['대분류'].isin(['주식', '채권', '대체', '모펀드'])
    mask_cash = pivot_data['대분류'] == '현금'
    mask_cash_keep = mask_cash & pivot_data['ITEM_NM'].apply(
        lambda x: 'USD DEPOSIT' in str(x).upper() or '예금' in str(x).upper()
    )
    # 통화(달러선물)는 피봇에서도 제외
    pivot_data = pivot_data[mask_main | mask_cash_keep].copy()

    print(f"[PIVOT] 필터링 후 데이터: {len(pivot_data)} rows")

    # 펀드별/날짜별 총액 계산하여 비중(%) 계산 - 필터링된 데이터 기준
    fund_totals = pivot_data.groupby(['STD_DT', 'FUND_CD'])['EVL_AMT'].transform('sum')
    pivot_data['비중(%)'] = (pivot_data['EVL_AMT'] / fund_totals * 100).round(2)

    # 수익률 컬럼 준비
    return_cols = ['1D', '1W', '1M', '3M', '6M', 'YTD']
    for col in return_cols:
        if col not in pivot_data.columns:
            pivot_data[col] = np.nan

    # % 표시 컬럼명으로 변경
    pivot_data = pivot_data.rename(columns={
        '1D': '1D(%)', '1W': '1W(%)', '1M': '1M(%)',
        '3M': '3M(%)', '6M': '6M(%)', 'YTD': 'YTD(%)'
    })

    # NaN을 빈 문자열로 (수익률 제외 가능 종목)
    for col in ['1D(%)', '1W(%)', '1M(%)', '3M(%)', '6M(%)', 'YTD(%)']:
        pivot_data[col] = pivot_data[col].apply(lambda x: x if pd.notna(x) else '')

    # 필요한 컬럼만 정리
    pivot_data = pivot_data[[
        'FUND_CD', 'FUND_NM', 'STD_DT',
        '대분류', '지역', 'ITEM_NM',
        '비중(%)',
        '1D(%)', '1W(%)', '1M(%)', '3M(%)', '6M(%)', 'YTD(%)'
    ]].copy()

    # 대분류 순서 적용하여 정렬
    pivot_data['대분류_순서'] = pivot_data['대분류'].map(CATEGORY_ORDER_MAP).fillna(99)
    pivot_data = pivot_data.sort_values(['대분류_순서', '지역', 'ITEM_NM'])
    pivot_data = pivot_data.drop(columns=['대분류_순서'])

    return pivot_data

pivot_data_global = prepare_pivot_data(holding, metrics, return_periods)

# 최신 날짜 (Pivot 기본 필터용)
pivot_latest_date = str(holding_latest_date)

# Pivot에 사용할 컬럼
pivot_cols = ['FUND_CD', 'FUND_NM', 'STD_DT',
              '대분류', '지역', 'ITEM_NM',
              '비중(%)',
              '1D(%)', '1W(%)', '1M(%)', '3M(%)', '6M(%)', 'YTD(%)']
# 변경: Pivot 데이터는 2026년만 유지하고 STD_DT 내림차순 정렬
pivot_data_for_table = pivot_data_global[[c for c in pivot_cols if c in pivot_data_global.columns]].copy()
pivot_data_for_table = pivot_data_for_table[pivot_data_for_table['STD_DT'].apply(lambda d: d.year == 2026)]
pivot_data_for_table = pivot_data_for_table.sort_values(['STD_DT'], ascending=False)

# 변경: 디폴트 모드(최신일 + FUND_CD=07G03)용 데이터 별도 준비
pivot_latest_date_2026 = pivot_data_for_table['STD_DT'].max()
pivot_data_default = pivot_data_for_table[
    (pivot_data_for_table['STD_DT'] == pivot_latest_date_2026) &
    (pivot_data_for_table['FUND_CD'] == '07G03')
].copy()


# =========================
# 9) Dash App
# =========================

# 파스텔 톤 테이블 스타일 정의
PASTEL_TABLE = {
    "style_table": {
        "borderRadius": "12px",
        "overflow": "hidden",
        "border": "1px solid #E6E8EE",
        "boxShadow": "0 1px 6px rgba(20, 20, 20, 0.06)",
    },
    "style_header": {
        "backgroundColor": "#F3F5F9",
        "color": "#1F2937",
        "fontWeight": "700",
        "borderBottom": "1px solid #DCE1EA",
        "fontSize": "12.5px",
        "letterSpacing": "0.2px",
        "padding": "10px",
        "textAlign": "center",
    },
    "style_cell": {
        "backgroundColor": "#FFFFFF",
        "color": "#2B2F36",
        "padding": "10px",
        "fontSize": "12px",
        "fontFamily": '"Inter","Apple SD Gothic Neo","Noto Sans KR",sans-serif',
        "borderBottom": "1px solid #EEF1F6",
        "borderLeft": "0px",
        "borderRight": "0px",
        "whiteSpace": "nowrap",
        "textAlign": "left",
    },
}

# 숫자 컬럼 목록 (우측 정렬 대상)
NUMERIC_COLS = ['비중(%)', '1D', '1W', '1M', '3M', '6M', 'YTD']

PASTEL_DATA_COND = [
    # 지브라 스트라이프
    {"if": {"row_index": "odd"}, "backgroundColor": "#FBFCFE"},
    # hover/selected 상태
    {"if": {"state": "active"}, "backgroundColor": "#EEF3FF", "border": "1px solid #D6E4FF"},
    {"if": {"state": "selected"}, "backgroundColor": "#E9F0FF", "border": "1px solid #C7DAFF"},
    # subtotal 행: _is_subtotal = "subtotal"
    {"if": {"filter_query": '{_is_subtotal} = "subtotal"'},
     "backgroundColor": "#EEF2F7", "fontWeight": "700", "color": "#243044", "borderTop": "1px solid #D8DEE9"},
    # total 행: _is_subtotal = "total"
    {"if": {"filter_query": '{_is_subtotal} = "total"'},
     "backgroundColor": "#E3E9F5", "fontWeight": "800", "color": "#162033", "borderTop": "2px solid #B8C6E3"},
    # 숫자 컬럼 우측 정렬 + tabular-nums
    {"if": {"column_id": "비중(%)"}, "textAlign": "right", "fontVariantNumeric": "tabular-nums"},
    {"if": {"column_id": "1D"}, "textAlign": "right", "fontVariantNumeric": "tabular-nums"},
    {"if": {"column_id": "1W"}, "textAlign": "right", "fontVariantNumeric": "tabular-nums"},
    {"if": {"column_id": "1M"}, "textAlign": "right", "fontVariantNumeric": "tabular-nums"},
    {"if": {"column_id": "3M"}, "textAlign": "right", "fontVariantNumeric": "tabular-nums"},
    {"if": {"column_id": "6M"}, "textAlign": "right", "fontVariantNumeric": "tabular-nums"},
    {"if": {"column_id": "YTD"}, "textAlign": "right", "fontVariantNumeric": "tabular-nums"},
    # 변경: 보유 종목 테이블의 Last Updated 정렬을 우측으로 통일
    {"if": {"column_id": "Last Updated"}, "textAlign": "right", "fontVariantNumeric": "tabular-nums"},
]

app = dash.Dash(__name__, suppress_callback_exceptions=True)

# 탭 상태 유지를 위해 모든 탭 컨텐츠를 항상 렌더링하고 display:none으로 제어
app.layout = html.Div([
    html.H1("자산배분 대시보드", style={'textAlign': 'center', 'marginBottom': 30}),

    # 탭 구조
    dcc.Tabs(id='tabs', value='tab-dashboard', children=[
        dcc.Tab(label='📊 자산배분 현황', value='tab-dashboard'),
        dcc.Tab(label='🔍 피봇 분석', value='tab-pivot'),
        dcc.Tab(label='📋 종목 리스트', value='tab-itemlist'),
    ]),

    # 모든 탭 컨텐츠를 항상 렌더링 (display로 제어)
    # Tab 1: 자산배분 현황
    html.Div(id='tab-dashboard-content', children=[
        html.Div([
            html.Div([
                html.Label("날짜 선택:", style={'fontWeight': 'bold', 'marginRight': 10, 'display': 'inline-block', 'verticalAlign': 'middle', 'fontSize': '14px'}),
                dcc.DatePickerSingle(
                    id='date-picker',
                    min_date_allowed=available_dates[0],
                    max_date_allowed=available_dates[-1],
                    initial_visible_month=holding_latest_date,
                    date=holding_latest_date,
                    display_format='YYYY-MM-DD',
                    style={'display': 'inline-block', 'verticalAlign': 'middle', 'fontSize': '14px'}
                )
            ], style={'display': 'inline-block', 'marginRight': 40}),

            html.Div([
                html.Label("펀드 선택:", style={'fontWeight': 'bold', 'marginRight': 10, 'display': 'inline-block', 'verticalAlign': 'middle', 'fontSize': '14px'}),
                dcc.Dropdown(
                    id='fund-dropdown',
                    options=[{'label': f, 'value': f} for f in FUND_LIST],
                    value=FUND_LIST[0],
                    style={'width': '200px', 'display': 'inline-block', 'verticalAlign': 'middle', 'fontSize': '14px'}
                ),
                html.Span(id='fund-name-display', style={'marginLeft': '15px', 'display': 'inline-block', 'verticalAlign': 'middle', 'fontWeight': 'bold', 'fontSize': '14px', 'color': '#333'})
            ], style={'display': 'inline-block'})
        ], style={'textAlign': 'left', 'marginLeft': '30px', 'marginBottom': 30}),

        # 보유 종목 테이블 (파스텔 톤 스타일 적용)
        html.Div([
            html.Div([
                html.H3("보유 종목 내역", style={'textAlign': 'center', 'display': 'inline-block', 'marginRight': 30}),
                html.Div([
                    html.Label("수익률 표시:", style={'fontWeight': 'bold', 'marginRight': 10, 'fontSize': '13px'}),
                    dcc.RadioItems(
                        id='return-display-toggle',
                        options=[
                            {'label': '원본 수익률', 'value': 'raw'},
                            {'label': '기여율 (비중×수익률)', 'value': 'contribution'},
                        ],
                        value='raw',
                        inline=True,
                        style={'display': 'inline-block', 'fontSize': '13px'},
                        inputStyle={'marginRight': '5px'},
                        labelStyle={'marginRight': '15px'}
                    )
                ], style={'display': 'inline-block', 'verticalAlign': 'middle'})
            ], style={'textAlign': 'center', 'marginBottom': 10}),
            dash_table.DataTable(
                id='holdings-table',
                style_table=PASTEL_TABLE["style_table"],
                style_header=PASTEL_TABLE["style_header"],
                style_cell=PASTEL_TABLE["style_cell"],
                style_data_conditional=PASTEL_DATA_COND,
                page_size=100,
                sort_action='native',
                filter_action='native'
            )
        ], style={'marginBottom': 30}),

        # 변경: 시계열 차트 분류 기준 토글 추가
        html.Div([
            dcc.RadioItems(
                id='area-groupby',
                options=[
                    {'label': '대분류', 'value': '대분류'},
                    {'label': '소분류', 'value': '소분류'},
                    {'label': '지역', 'value': '지역'},
                ],
                value='대분류',
                inline=True
            ),
            dcc.Graph(id='area-chart')
        ], style={'marginTop': 20}),

        # 수익률 차트
        html.Div([dcc.Graph(id='performance-chart')], style={'marginTop': 20}),

        # 변경: 자산배분 상세 테이블 제거
    ]),

    # Tab 2: 피봇 분석
    html.Div(id='tab-pivot-content', children=[
        html.Div([
            html.H2("🔍 인터랙티브 피봇 분석", style={'textAlign': 'center', 'marginBottom': 20}),
            html.P([
                "💡 사용 팁: ",
                html.Br(),
                "• 좌측 필드를 드래그하여 행/열/값 영역에 배치하세요",
                html.Br(),
                "• Aggregator에서 집계 방식 선택 (Sum, Average, Count 등)",
                html.Br(),
                "• Renderer에서 표시 방식 선택 (Table, Heatmap, Bar Chart 등)",
                html.Br(),
                "• 사용 가능 컬럼: 비중(%), 1D(%), 1W(%), 1M(%), 3M(%), 6M(%), YTD(%)"
            ], style={'textAlign': 'center', 'color': '#666', 'fontSize': 14, 'marginBottom': 30}),
        ]),

        # 변경: Pivot 기본/전체(2026) 토글 UI 추가
        html.Div([
            dcc.RadioItems(
                id='pivot-data-mode',
                options=[
                    {'label': '디폴트 (최신일 + 07G03)', 'value': 'default'},
                    {'label': '전체 (2026년)', 'value': 'all'},
                ],
                value='default',
                inline=True
            )
        ], style={'textAlign': 'center', 'marginBottom': 10}),

        html.Div([
            PivotTable(
                id='pivot-table',
                # 변경: data는 콜백에서 주입 (디폴트/전체 토글)
                data=pivot_data_default.to_dict('records'),
                # 디폴트 설정
                rows=['FUND_NM', '대분류', '지역', 'ITEM_NM', '1D(%)', '1W(%)', '1M(%)', '3M(%)', '6M(%)', 'YTD(%)'],
                cols=[],
                vals=['비중(%)'],
                aggregatorName='Sum',
                rendererName='Table',
            )
        ], style={'marginTop': 20})
    ]),

    # Tab 3: 종목 리스트
    html.Div(id='tab-itemlist-content', children=[
        html.H2("📋 종목 분류 리스트", style={'textAlign': 'center', 'marginBottom': 30}),

        html.Div(id='itemlist-status', style={'textAlign': 'center', 'marginBottom': 20}),

        html.Div([
            dash_table.DataTable(
                id='item-list-table',
                columns=[
                    {'name': '종목코드', 'id': 'ITEM_CD'},
                    {'name': '종목명', 'id': 'ITEM_NM'},
                    {'name': '대분류', 'id': '대분류'},
                    {'name': '지역', 'id': '지역'},
                    {'name': '소분류', 'id': '소분류'},
                    {'name': '1D(%)', 'id': '1D'},
                    {'name': '1W(%)', 'id': '1W'},
                    {'name': '1M(%)', 'id': '1M'},
                    {'name': '3M(%)', 'id': '3M'},
                    {'name': '6M(%)', 'id': '6M'},
                    {'name': 'YTD(%)', 'id': 'YTD'},
                    {'name': 'Last Updated', 'id': 'Last Updated'},
                ],
                data=[],
                style_cell={'textAlign': 'left', 'padding': '10px', 'fontSize': '13px', 'whiteSpace': 'nowrap'},
                style_header={'backgroundColor': '#4CAF50', 'fontWeight': 'bold', 'color': 'white'},
                style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': 'rgb(248, 248, 248)'}],
                page_size=50,
                sort_action='native',
                filter_action='native',
                export_format='xlsx',
                export_headers='display',
            )
        ], style={'marginBottom': 30, 'maxWidth': '1400px', 'margin': '0 auto'}),
    ])

], style={'padding': '20px', 'maxWidth': '1600px', 'margin': '0 auto'})


# =========================
# 10) 탭 표시/숨김 콜백
# =========================
@app.callback(
    [Output('tab-dashboard-content', 'style'),
     Output('tab-pivot-content', 'style'),
     Output('tab-itemlist-content', 'style')],
    Input('tabs', 'value')
)
def toggle_tab_visibility(tab):
    """탭 선택에 따라 display 속성으로 표시/숨김 제어"""
    dashboard_style = {'display': 'block'} if tab == 'tab-dashboard' else {'display': 'none'}
    pivot_style = {'display': 'block'} if tab == 'tab-pivot' else {'display': 'none'}
    itemlist_style = {'display': 'block'} if tab == 'tab-itemlist' else {'display': 'none'}

    return dashboard_style, pivot_style, itemlist_style


# 변경: Pivot 데이터 토글 (디폴트/전체)
@app.callback(
    Output('pivot-table', 'data'),
    Input('pivot-data-mode', 'value')
)
def update_pivot_data(mode):
    if mode == 'all':
        return pivot_data_for_table.to_dict('records')
    return pivot_data_default.to_dict('records')


# =========================
# 11) 대시보드 콜백
# =========================
@app.callback(
    Output('fund-name-display', 'children'),
    Input('fund-dropdown', 'value')
)
def display_fund_name(fund_code):
    if fund_code in FUND_NAMES:
        return f"({FUND_NAMES[fund_code]})"
    return ""


@app.callback(
    [Output('holdings-table', 'data'),
     Output('holdings-table', 'columns'),
     Output('area-chart', 'figure'),
     Output('performance-chart', 'figure')],
    [Input('date-picker', 'date'),
     Input('fund-dropdown', 'value'),
     Input('area-groupby', 'value'),
     Input('return-display-toggle', 'value')]
)
def update_dashboard(selected_date, selected_fund, area_groupby, return_display_mode):
    # 날짜 변환
    if isinstance(selected_date, str):
        selected_date = datetime.strptime(selected_date, '%Y-%m-%d').date()

    # 필터링
    df_holding_all = holding[
        (holding['STD_DT'] == selected_date) &
        (holding['FUND_CD'] == selected_fund)
    ].copy()

    return_cols = ['1D', '1W', '1M', '3M', '6M', 'YTD']

    # =========================
    # [NEW] 현금/통화 필터링 적용 - 비중/기여율 왜곡 제거
    # =========================
    df_main, df_cash_keep, df_fx_hedge, df_cash_drop = filter_holdings_for_weight(df_holding_all)

    # 비중 계산 기준 = 주식/채권/대체/모펀드 + 유지할 현금(USD Deposit, 예금)
    df_weight_base = pd.concat([df_main, df_cash_keep], ignore_index=True)
    weight_base_total = df_weight_base['EVL_AMT'].sum()

    # 수익률 데이터 존재 여부 확인
    has_return_data = all(col in df_weight_base.columns for col in return_cols)

    # 비중 검증 로그
    print(f"\n[CHECK] weight_base_total = {weight_base_total:,.0f} 원")
    print(f"[CHECK] df_weight_base rows = {len(df_weight_base)}")

    # 대분류 순서 정의 (주식, 채권, 대체, 모펀드, 통화, 기타, 현금)
    df_weight_base['대분류_순서'] = df_weight_base['대분류'].map(CATEGORY_ORDER_MAP).fillna(99)
    df_weight_base = df_weight_base.sort_values(['대분류_순서', '지역', 'ITEM_NM'])

    # 비중 계산 (df_weight_base 기준)
    if weight_base_total > 0:
        df_weight_base['WEIGHT_PCT'] = (df_weight_base['EVL_AMT'] / weight_base_total * 100).round(6)
    else:
        df_weight_base['WEIGHT_PCT'] = 0

    # 비중합 검증
    total_weight_check = df_weight_base['WEIGHT_PCT'].sum()
    print(f"[CHECK] total weight = {total_weight_check:.6f}%")
    if weight_base_total > 0:
        assert abs(total_weight_check - 100) < 1e-4, f"비중합이 100%가 아님: {total_weight_check}"

    # USD 종목 판정 (ITEM_CD가 'US'로 시작) - df_weight_base 기준
    df_weight_base['IS_USD'] = df_weight_base['ITEM_CD'].apply(
        lambda x: str(x).upper().startswith('US')
    )

    # USD 종목 총 비중 계산 (환차익 계산용)
    total_usd_weight = df_weight_base[df_weight_base['IS_USD']]['WEIGHT_PCT'].sum()

    # 환차익 계산: USD 비중 × FX 수익률
    # FX_RETURN_BY_PERIOD는 전역 변수 (예: {'1D': -1.62, '1W': 0.5, ...})
    fx_impact = {col: (total_usd_weight * FX_RETURN_BY_PERIOD.get(col, 0) / 100) for col in return_cols}

    # =========================
    # [NEW] FX Hedge (달러선물) 평가손익 계산 (별도 표시용)
    # =========================
    fx_hedge_pnl = 0
    if len(df_fx_hedge) > 0:
        fx_hedge_pnl = df_fx_hedge['EVL_AMT'].sum()
        print(f"[INFO] FX Hedge (달러선물) 평가금액: {fx_hedge_pnl:,.0f} 원")

    # 보유 종목 테이블 (대분류 소계 + 총계 포함) - df_weight_base만 사용
    holdings_list = []
    current_category = None
    category_pct = 0
    category_weighted_returns = {col: 0 for col in return_cols}
    category_valid_weight = {col: 0 for col in return_cols}

    # 총계 계산용 변수
    total_weighted_returns = {col: 0 for col in return_cols}
    total_valid_weight = {col: 0 for col in return_cols}

    def format_return(value):
        if pd.isna(value) or value == '':
            return ''
        try:
            return round(float(value), 2)
        except (ValueError, TypeError):
            return ''

    for idx, row in df_weight_base.iterrows():
        pct = (row['EVL_AMT'] / weight_base_total * 100) if weight_base_total > 0 else 0

        # 대분류가 바뀌면 이전 대분류 소계 추가
        if current_category and row['대분류'] != current_category:
            subtotal_row = {
                '대분류': f'▶ {current_category} 소계',
                'ITEM_NM': '',
                '비중(%)': round(category_pct, 2),
                '_is_subtotal': 'subtotal',
                'Last Updated': '-'
            }
            # 토글에 따라 소계 계산
            for col in return_cols:
                if category_valid_weight[col] > 0:
                    if return_display_mode == 'contribution':
                        # 기여율 모드: 해당 카테고리의 기여율 합계
                        category_contribution = category_weighted_returns[col] / 100
                        subtotal_row[col] = round(category_contribution, 4)
                    else:
                        # 원본 수익률 모드: 가중평균
                        weighted_avg = category_weighted_returns[col] / category_valid_weight[col]
                        subtotal_row[col] = round(weighted_avg, 2)
                else:
                    subtotal_row[col] = '-'
            holdings_list.append(subtotal_row)

            # 초기화
            category_pct = 0
            category_weighted_returns = {col: 0 for col in return_cols}
            category_valid_weight = {col: 0 for col in return_cols}

        current_category = row['대분류']
        category_pct += pct

        item_row = {
            '대분류': row['대분류'],
            'ITEM_NM': row['ITEM_NM'],
            '비중(%)': round(pct, 2),
            '_is_subtotal': '',
            'Last Updated': row.get('Last Updated', '') if has_return_data else ''
        }

        # 수익률 컬럼 추가 및 가중평균 누적
        if has_return_data:
            for col in return_cols:
                val = row.get(col)
                formatted_val = format_return(val)

                # 가중평균 계산을 위한 누적 (유효한 값만)
                if formatted_val != '' and pd.notna(val):
                    val_float = float(val)
                    category_weighted_returns[col] += val_float * pct
                    category_valid_weight[col] += pct
                    # 총계용 누적
                    total_weighted_returns[col] += val_float * pct
                    total_valid_weight[col] += pct

                    # 토글에 따라 표시 값 결정
                    if return_display_mode == 'contribution':
                        # 기여율: 비중 × 수익률 / 100
                        contribution = val_float * pct / 100
                        item_row[col] = round(contribution, 4)
                    else:
                        # 원본 수익률
                        item_row[col] = formatted_val
                else:
                    item_row[col] = formatted_val if return_display_mode == 'raw' else ''
        else:
            for col in return_cols:
                item_row[col] = ''

        holdings_list.append(item_row)

    # 마지막 대분류 소계 추가
    if current_category and category_pct > 0:
        subtotal_row = {
            '대분류': f'▶ {current_category} 소계',
            'ITEM_NM': '',
            '비중(%)': round(category_pct, 2),
            '_is_subtotal': 'subtotal',
            'Last Updated': '-'
        }
        for col in return_cols:
            if category_valid_weight[col] > 0:
                if return_display_mode == 'contribution':
                    # 기여율 모드: 해당 카테고리의 기여율 합계
                    category_contribution = category_weighted_returns[col] / 100
                    subtotal_row[col] = round(category_contribution, 4)
                else:
                    # 원본 수익률 모드: 가중평균
                    weighted_avg = category_weighted_returns[col] / category_valid_weight[col]
                    subtotal_row[col] = round(weighted_avg, 2)
            else:
                subtotal_row[col] = '-'
        holdings_list.append(subtotal_row)

    # 환차익 행 추가 (총계 바로 위)
    # FX impact = USD 비중 × FX 수익률 (이미 fx_impact에 계산됨)
    if has_return_data:
        fx_gain_row = {
            '대분류': '통화',
            'ITEM_NM': '환차손익',
            '비중(%)': round(total_usd_weight, 2) if return_display_mode == 'raw' else '-',
            '_is_subtotal': 'subtotal',
            'Last Updated': '-'
        }
        for col in return_cols:
            if return_display_mode == 'contribution':
                # 기여율 모드: FX 기여율 (이미 계산됨)
                fx_gain_row[col] = round(fx_impact.get(col, 0), 4)
            else:
                # 원본 수익률 모드: FX 수익률 자체
                fx_gain_row[col] = round(FX_RETURN_BY_PERIOD.get(col, 0), 2)
        holdings_list.append(fx_gain_row)

    # 총계 행 추가 (맨 마지막)
    # 총계 = 순수 자산 수익률 + 환차익
    total_row = {
        '대분류': '■ 총계',
        'ITEM_NM': '',
        '비중(%)': 100.0,
        '_is_subtotal': 'total',
        'Last Updated': '-'
    }
    for col in return_cols:
        # 순수 자산 가중평균 수익률
        if total_valid_weight[col] > 0:
            pure_asset_return = total_weighted_returns[col] / 100  # 가중합 / 100
        else:
            pure_asset_return = 0

        # 총계 = 순수 자산 수익률 + FX impact
        total_return = pure_asset_return + fx_impact.get(col, 0)

        if return_display_mode == 'contribution':
            # 기여율 모드: 총 기여율
            total_row[col] = round(total_return, 4) if total_return != 0 else '-'
        else:
            # 원본 수익률 모드: 총 수익률
            total_row[col] = round(total_return, 2) if total_return != 0 else '-'
    holdings_list.append(total_row)

    holdings_table_data = holdings_list

    # 토글에 따라 컬럼 헤더 변경
    if return_display_mode == 'contribution':
        return_header_suffix = '(기여%)'
    else:
        return_header_suffix = '(%)'

    holdings_table_columns = [
        {'name': '대분류', 'id': '대분류'},
        {'name': '종목명', 'id': 'ITEM_NM'},
        {'name': '비중(%)', 'id': '비중(%)'},
        {'name': f'1D{return_header_suffix}', 'id': '1D'},
        {'name': f'1W{return_header_suffix}', 'id': '1W'},
        {'name': f'1M{return_header_suffix}', 'id': '1M'},
        {'name': f'3M{return_header_suffix}', 'id': '3M'},
        {'name': f'6M{return_header_suffix}', 'id': '6M'},
        {'name': f'YTD{return_header_suffix}', 'id': 'YTD'},
        {'name': 'Last Updated', 'id': 'Last Updated'}
    ]

    # 자산배분 현황 차트: 비중(%) 시계열 추이
    # [NEW] 현금/통화 필터링 적용 - 제외 대상 종목 제거
    df_timeseries = holding[holding['FUND_CD'] == selected_fund].copy()

    # 시계열 데이터에도 동일한 필터링 로직 적용
    mask_main_ts = df_timeseries['대분류'].isin(['주식', '채권', '대체', '모펀드'])
    mask_cash_ts = df_timeseries['대분류'] == '현금'
    mask_cash_keep_ts = mask_cash_ts & df_timeseries['ITEM_NM'].apply(
        lambda x: 'USD DEPOSIT' in str(x).upper() or '예금' in str(x).upper()
    )
    # 통화(달러선물)는 시계열 차트에서도 제외
    df_timeseries_filtered = df_timeseries[mask_main_ts | mask_cash_keep_ts].copy()

    group_key = area_groupby if area_groupby in ['대분류', '지역', '소분류'] else '대분류'
    df_ts_agg = df_timeseries_filtered.groupby(['STD_DT', group_key], as_index=False)['EVL_AMT'].sum()
    df_pivot = df_ts_agg.pivot(index='STD_DT', columns=group_key, values='EVL_AMT').fillna(0)
    df_pivot = (df_pivot.div(df_pivot.sum(axis=1), axis=0) * 100).fillna(0)

    fig_area = go.Figure()
    for col in df_pivot.columns:
        fig_area.add_trace(go.Scatter(
            x=df_pivot.index,
            y=df_pivot[col],
            mode='lines',
            name=col,
            stackgroup='one',
            hovertemplate='<b>%{fullData.name}</b><br>%{y:.2f}%<extra></extra>'
        ))
    fig_area.update_layout(
        title='자산배분 현황',
        xaxis_title='날짜',
        yaxis_title='비중(%)',
        height=400,
        hovermode='x unified',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig_area.update_yaxes(range=[0, 100])

    df_metrics_fund = metrics_for_chart[metrics_for_chart['FUND_CD'] == selected_fund].copy()

    fig_perf = make_subplots(
        rows=2, cols=1,
        subplot_titles=('누적수익률', 'NAV 추이'),
        vertical_spacing=0.12,
        row_heights=[0.5, 0.5]
    )

    fig_perf.add_trace(
        go.Scatter(
            x=df_metrics_fund['STD_DT_DATE'],
            y=df_metrics_fund['RET'],
            mode='lines',
            name='수익률',
            line=dict(color='#4ECDC4', width=2),
            hovertemplate='%{x}<br>수익률: %{y:.2f}%<extra></extra>'
        ),
        row=1, col=1
    )

    fig_perf.add_trace(
        go.Scatter(
            x=df_metrics_fund['STD_DT_DATE'],
            y=df_metrics_fund['NAST_AMT'] / 100_000_000,
            mode='lines',
            name='NAV',
            line=dict(color='#FF6B6B', width=2),
            fill='tozeroy',
            hovertemplate='%{x}<br>NAV: %{y:,.0f}억원<extra></extra>'
        ),
        row=2, col=1
    )

    fig_perf.update_xaxes(title_text="날짜", row=2, col=1)
    fig_perf.update_yaxes(title_text="수익률 (%)", row=1, col=1)
    fig_perf.update_yaxes(title_text="NAV (억원)", row=2, col=1)
    fig_perf.update_layout(height=500, showlegend=False)

    return holdings_table_data, holdings_table_columns, fig_area, fig_perf


# =========================
# 12) 종목 리스트 탭 콜백
# =========================
@app.callback(
    [Output('item-list-table', 'data'),
     Output('itemlist-status', 'children')],
    Input('tabs', 'value')
)
def update_item_list(tab):
    # 마스터 테이블 로드
    master = load_master_mapping()

    if master.empty:
        status = html.Div(
            "⚠️ 등록된 종목이 없습니다",
            style={'color': 'orange', 'fontSize': 18, 'fontWeight': 'bold'}
        )
        return [], status

    # 수익률 데이터 merge
    master_with_returns = master.merge(return_periods, on='ITEM_CD', how='left')

    # 대분류 순서 적용
    master_with_returns['대분류_순서'] = master_with_returns['대분류'].map(CATEGORY_ORDER_MAP).fillna(99)

    # 종목 리스트 데이터 준비
    cols_to_show = ['ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류',
                    '1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated']
    available_cols = [c for c in cols_to_show if c in master_with_returns.columns]

    item_list = master_with_returns[available_cols + ['대분류_순서']].copy()
    item_list = item_list.sort_values(['대분류_순서', '지역', '소분류', 'ITEM_NM'])
    item_list = item_list.drop(columns=['대분류_순서'])

    # NaN을 빈 문자열로
    for col in ['1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated']:
        if col in item_list.columns:
            item_list[col] = item_list[col].apply(lambda x: x if pd.notna(x) else '')

    data = item_list.to_dict('records')

    status = html.Div(
        f"✅ 총 {len(item_list)}개 종목이 등록되어 있습니다",
        style={'color': 'green', 'fontSize': 18, 'fontWeight': 'bold'}
    )

    return data, status


# =========================
# 13) Run
# =========================
if __name__ == '__main__':
    print("\n" + "="*80)
    print("자산배분 대시보드 시작")
    print("="*80)
    print(f"마스터 종목 수: {len(master_mapping)}")
    print(f"미분류 종목 수: {len(unmapped)}")
    print(f"SCIP 최신 영업일: {scip_latest_date}")
    print(f"대시보드 URL: http://127.0.0.1:8050")
    print("="*80 + "\n")

    app.run(debug=True, host='0.0.0.0', port=8050)

