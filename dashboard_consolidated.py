"""
자산배분 대시보드 (통합 버전)

3개 파일(dashboard_with_master.py, create_initial_master.py, auto_classify.py)을
하나로 통합한 버전입니다.

Features:
- 자산 자동 분류
- 마스터 데이터 관리
- SCIP DB 기반 영업일 수익률 계산
- 인터랙티브 피봇 분석 (탭 상태 유지)
"""

import pandas as pd
import numpy as np
import pickle
import os
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
MASTER_FILE = "master_asset_mapping.pkl"

FUND_LIST = [
    '06X08','07G02','07G03','07G04','07J20','07J27','07J34','07J41',
    '07J48','07J49','07P70','07W15','08K88','08N33','08N81','09L94',
    '1JM96','1JM98','2JM23','4JM12'
]

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


def get_auto_classify_stats(items_df):
    """자동 분류 통계 계산"""
    stats = {
        '콜론': 0, '금': 0, '달러 선물': 0, '코스피 선물': 0,
        'REPO': 0, '예금/증거금': 0, '미수/청약': 0,
    }

    for _, row in items_df.iterrows():
        result = auto_classify_item(row['ITEM_CD'], row['ITEM_NM'])
        if result:
            item_nm_upper = str(row['ITEM_NM']).upper()
            if '콜론' in item_nm_upper:
                stats['콜론'] += 1
            elif 'GOLD' in item_nm_upper or '금' in item_nm_upper:
                stats['금'] += 1
            elif '달러 F' in item_nm_upper:
                stats['달러 선물'] += 1
            elif '코스피' in item_nm_upper and ' F ' in item_nm_upper:
                stats['코스피 선물'] += 1
            elif 'REPO' in item_nm_upper:
                stats['REPO'] += 1
            elif any(w in item_nm_upper for w in ['예금', '증거금', 'DEPOSIT']):
                stats['예금/증거금'] += 1
            elif any(w in item_nm_upper for w in ['미수', '미지급', '청약금']):
                stats['미수/청약'] += 1

    return {k: v for k, v in stats.items() if v > 0}


# =========================
# 2) 초기 마스터 생성 함수 (create_initial_master.py 통합)
# =========================
def create_initial_master():
    """초기 마스터 데이터 생성 (마스터 파일이 없을 때만 실행)"""

    data = """1751100	미수ETF분배금	현금	국내	현금 등
KR7332500008	ACE 200TR	주식	국내	일반
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
US92206C6646	Vanguard Russell 2000 ETF	주식	미국	중소형
US9229087369	VANGUARD GROWTH ETF	주식	미국	성장
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
KRZ502649922	한국투자TMF28-12만기형증권투자신탁(채권)	채권	국내	단기채
1912100	기타자산	기타	국내	기타
000000000000	미지급외화거래비용	현금	국내	현금 등"""

    lines = [line.split('\t') for line in data.strip().split('\n')]
    df = pd.DataFrame(lines, columns=['ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류'])

    # 자동 분류 적용
    for idx, row in df.iterrows():
        result = auto_classify_item(row['ITEM_CD'], row['ITEM_NM'])
        if result:
            df.loc[idx, '대분류'] = result['대분류']
            df.loc[idx, '지역'] = result['지역']
            df.loc[idx, '소분류'] = result['소분류']

    df['등록일'] = datetime.now().strftime('%Y-%m-%d')
    df['비고'] = ''

    df.to_pickle(MASTER_FILE)
    print(f"[✓] 초기 마스터 테이블 생성 완료: {len(df)}개 종목")

    return df


# =========================
# 3) 마스터 테이블 관리
# =========================
def load_master_mapping():
    """마스터 분류 테이블 로드"""
    if not os.path.exists(MASTER_FILE):
        print(f"[WARNING] {MASTER_FILE} 파일이 없습니다. 초기 마스터 생성...")
        return create_initial_master()

    return pd.read_pickle(MASTER_FILE)


def save_master_mapping(df):
    """마스터 테이블 저장"""
    df.to_pickle(MASTER_FILE)
    print(f"[✓] 마스터 테이블 저장 완료: {len(df)}개 종목")


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
            save_master_mapping(master_df)
            print(f"[AUTO] {len(new_items_df)}개 신규 종목 자동 분류 → 마스터에 추가됨")

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
def parse_data_blob(blob):
    """FactSet data blob을 숫자로 파싱"""
    if blob is None:
        return None

    if isinstance(blob, (bytes, bytearray)):
        s = blob.decode('utf-8')
    else:
        s = str(blob)

    s = s.strip()

    # JSON 파싱 시도
    if s.startswith('{') or s.startswith('['):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return float(obj.get('USD', obj.get('KRW', None)))
            return float(obj)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # 직접 숫자 변환 시도
    try:
        return float(s.replace(',', ''))
    except (ValueError, AttributeError):
        return None


def should_exclude_for_return(item_nm):
    """수익률 계산에서 제외할 종목 판단"""
    item_nm_upper = str(item_nm).upper()

    # 모펀드, 콜론, 선물, REPO, 예금/증거금, 미수/미지급 등 제외
    if '모투자신탁' in item_nm:
        return True
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
      AND dp.dataseries_id IN (6, 39)
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
        SCIP DB의 최신 영업일
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
            # YTD는 해당일 또는 이후 가장 가까운 영업일 (여기서는 on_or_before 방식으로 처리)
            # 실제로는 1/1 이후 첫 영업일이어야 하므로, available_dates에서 ytd_start_target 이상 중 가장 작은 값
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

    Returns:
    --------
    tuple: (return_df, available_dates, latest_date, base_dates)
        - return_df: ITEM_CD, date, return_index 컬럼
        - available_dates: 데이터 존재 날짜 목록
        - latest_date: 최신 영업일
        - base_dates: 기간별 기준일 dict
    """
    # 수익률 계산 대상 종목 필터링
    items_for_return = master_df[~master_df['ITEM_NM'].apply(should_exclude_for_return)].copy()

    if len(items_for_return) == 0:
        print("[INFO] 수익률 계산 대상 종목이 없습니다")
        return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index']), [], None, {}

    isin_list = items_for_return['ITEM_CD'].tolist()

    print(f"[INFO] 수익률 조회 대상: {len(isin_list)}개 종목")

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
        dp.dataseries_id,
        dp.data
    FROM SCIP.back_datapoint dp
    INNER JOIN SCIP.back_dataset d ON dp.dataset_id = d.id
    WHERE d.ISIN IN :isin_list
      AND dp.dataseries_id IN (6, 39)
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

        print(f"[INFO] 조회된 raw datapoints: {len(df_raw)}개")

        if df_raw.empty:
            return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index']), available_dates, latest_date, base_dates

        # 데이터 파싱
        df_raw['return_index'] = df_raw['data'].apply(parse_data_blob)
        df_raw = df_raw.dropna(subset=['return_index'])

        # dataseries_id = 6 우선, 없으면 39 사용
        df_raw = df_raw.sort_values(['ITEM_CD', 'date', 'dataseries_id'])
        df_raw = df_raw.drop_duplicates(subset=['ITEM_CD', 'date'], keep='first')

        result = df_raw[['ITEM_CD', 'date', 'return_index']].copy()
        print(f"[INFO] 파싱된 데이터: {len(result)}개 ({result['ITEM_CD'].nunique()}개 종목)")

        return result, available_dates, latest_date, base_dates

    except Exception as e:
        print(f"[ERROR] fetch_factset_returns_with_dates: {e}")
        return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index']), [], None, {}


def calculate_return_periods_v2(return_df, latest_date, base_dates):
    """
    영업일 기준 수익률 계산 (v2)

    Returns:
    --------
    DataFrame with columns: ITEM_CD, 1D, 1W, 1M, 3M, 6M, YTD, Last Updated
    """
    if return_df.empty or latest_date is None:
        return pd.DataFrame(columns=['ITEM_CD', '1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated'])

    return_df = return_df.copy()
    return_df['date'] = pd.to_datetime(return_df['date']).dt.date

    results = []

    for item_cd in return_df['ITEM_CD'].unique():
        item_data = return_df[return_df['ITEM_CD'] == item_cd].sort_values('date')

        if item_data.empty:
            continue

        # 최신 데이터 (latest_date 이하)
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
    print(f"[INFO] 수익률 계산 완료: {len(result_df)}개 종목")

    return result_df


# =========================
# 5) 데이터 로드
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
    AST_CLSF_CD_NM,
    SUM(EVL_AMT) AS EVL_AMT
FROM dt.DWPM10530
WHERE STD_DT BETWEEN :start_dt AND :end_dt
  AND EVL_AMT > 0
  AND FUND_CD IN :fund_list
GROUP BY STD_DT, FUND_CD, FUND_NM, ITEM_CD, ITEM_NM, AST_CLSF_CD_NM
ORDER BY STD_DT, FUND_CD;
"""

# Fund metrics
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
with engine.connect() as conn:
    holding = pd.read_sql(
        text(query_holding), conn,
        params={"start_dt": START_STD_DT, "end_dt": END_STD_DT, "fund_list": fund_tuple}
    )
    metrics = pd.read_sql(
        text(query_metrics), conn,
        params={"start_dt": START_STD_DT, "end_dt": END_STD_DT, "fund_list": fund_tuple}
    )

print(f"[INFO] Loaded {len(holding)} holding records, {len(metrics)} metric records")

# 펀드명 매핑 생성
FUND_NAMES = holding[['FUND_CD', 'FUND_NM']].drop_duplicates().set_index('FUND_CD')['FUND_NM'].to_dict()
print(f"[INFO] Fund names mapped: {len(FUND_NAMES)} funds")

# 날짜 변환
def convert_to_date(dt_int):
    """YYYYMMDD int를 date 객체로 변환"""
    dt_str = str(int(dt_int))
    return datetime.strptime(dt_str, '%Y%m%d').date()

holding['STD_DT_INT'] = holding['STD_DT']
holding['STD_DT'] = holding['STD_DT'].apply(convert_to_date)
metrics['STD_DT'] = metrics['STD_DT'].apply(lambda x: datetime.strptime(str(int(x)), '%Y%m%d'))

# 자산군 분류
print("[INFO] Classifying assets with master mapping...")
holding, unmapped, master_mapping = classify_with_master(holding, master_mapping)
print(f"[INFO] Master now contains {len(master_mapping)} items")

# 날짜 리스트
available_dates = sorted(holding['STD_DT'].unique())
holding_latest_date = available_dates[-1]

# =========================
# 6) SCIP 기반 수익률 데이터 로드
# =========================
print("\n[INFO] Fetching SCIP return data (영업일 기준)...")
factset_returns, scip_available_dates, scip_latest_date, base_dates = fetch_factset_returns_with_dates(
    master_mapping, engine_scip
)

# 수익률 계산
return_periods = calculate_return_periods_v2(factset_returns, scip_latest_date, base_dates)
print(f"[INFO] Return data loaded for {len(return_periods)} items")

# Merge return data with holding
if not return_periods.empty:
    holding = holding.merge(return_periods, on='ITEM_CD', how='left')

# 펀드 수익률 계산
metrics = metrics.sort_values(['FUND_CD', 'STD_DT'])
metrics['RET'] = metrics.groupby('FUND_CD')['MOD_STPR'].transform(
    lambda x: (x / x.iloc[0] - 1) * 100
)

print(f"[INFO] Holdings latest date: {holding_latest_date}")
print(f"[INFO] SCIP latest date: {scip_latest_date}")
print(f"[INFO] Unmapped items: {len(unmapped)}")

# =========================
# 7) Pivot 분석용 데이터 준비
# =========================
def prepare_pivot_data(holding_df, return_periods_df):
    """피봇 분석용 데이터 준비 (수익률 포함)"""
    pivot_data = holding_df.copy()
    pivot_data['날짜'] = pivot_data['STD_DT'].astype(str)
    pivot_data['금액(억)'] = (pivot_data['EVL_AMT'] / 100_000_000).round(2)
    pivot_data['금액(원)'] = pivot_data['EVL_AMT'].astype(int)

    # 수익률 컬럼 추가 (holding에 이미 merge된 경우)
    return_cols = ['1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated']
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

    return pivot_data

pivot_data_global = prepare_pivot_data(holding, return_periods)

# 최신 날짜 (Pivot 기본 필터용)
pivot_latest_date = str(holding_latest_date)

# Pivot에 사용할 컬럼
pivot_cols = ['날짜', 'FUND_CD', 'FUND_NM', '대분류', '지역', '소분류',
              'ITEM_NM', '금액(억)', '금액(원)',
              '1D(%)', '1W(%)', '1M(%)', '3M(%)', '6M(%)', 'YTD(%)', 'Last Updated']
pivot_data_for_table = pivot_data_global[[c for c in pivot_cols if c in pivot_data_global.columns]]


# =========================
# 8) Dash App
# =========================
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

        # 보유 종목 테이블
        html.Div([
            html.H3("보유 종목 내역", style={'textAlign': 'center'}),
            dash_table.DataTable(
                id='holdings-table',
                style_cell={
                    'textAlign': 'center',
                    'padding': '8px',
                    'fontSize': '12px',
                    'whiteSpace': 'normal',
                    'height': 'auto'
                },
                style_header={
                    'backgroundColor': '#4CAF50',
                    'fontWeight': 'bold',
                    'color': 'white',
                    'border': '1px solid white'
                },
                style_cell_conditional=[
                    {'if': {'column_id': 'ITEM_NM'}, 'minWidth': '200px', 'maxWidth': '300px', 'textAlign': 'left', 'textOverflow': 'ellipsis'},
                    {'if': {'column_id': '대분류'}, 'width': '80px'},
                    {'if': {'column_id': '비중(%)'}, 'width': '70px', 'textAlign': 'right'},
                    {'if': {'column_id': '1D'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': '1W'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': '1M'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': '3M'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': '6M'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': 'YTD'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': 'Last Updated'}, 'width': '110px', 'textAlign': 'center'},
                ],
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': 'rgb(248, 248, 248)'},
                    {
                        'if': {'filter_query': '{_is_subtotal} = true'},
                        'backgroundColor': '#FFE082',
                        'fontWeight': 'bold',
                        'borderTop': '2px solid #FF6F00',
                        'borderBottom': '2px solid #FF6F00'
                    }
                ],
                page_size=50,
                sort_action='native',
                filter_action='native'
            )
        ], style={'marginBottom': 30}),

        # 시계열 차트
        html.Div([dcc.Graph(id='area-chart')], style={'marginTop': 20}),

        # 수익률 차트
        html.Div([dcc.Graph(id='performance-chart')], style={'marginTop': 20}),

        # 자산배분 상세
        html.Div([
            html.H3("자산배분 상세", style={'textAlign': 'center'}),
            dash_table.DataTable(
                id='allocation-table',
                style_cell={'textAlign': 'center', 'padding': '8px'},
                style_header={'backgroundColor': 'lightgrey', 'fontWeight': 'bold'},
                style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': 'rgb(248, 248, 248)'}]
            )
        ], style={'marginTop': 30, 'marginBottom': 50})
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
                "• 수익률 컬럼: 1D(%), 1W(%), 1M(%), 3M(%), 6M(%), YTD(%)"
            ], style={'textAlign': 'center', 'color': '#666', 'fontSize': 14, 'marginBottom': 30}),
        ]),

        html.Div([
            PivotTable(
                id='pivot-table',
                data=pivot_data_for_table.to_dict('records'),
                # 디폴트 설정
                rows=['FUND_NM', '대분류', '지역', 'ITEM_NM'],
                cols=[],
                vals=['금액(억)'],
                aggregatorName='Sum as Fraction of Total',
                rendererName='Table',
                # 초기 필터: FUND_CD는 '07G03', 날짜는 최신
                hiddenFromDragDrop=['_is_subtotal'] if '_is_subtotal' in pivot_data_for_table.columns else [],
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
                style_cell={'textAlign': 'center', 'padding': '10px', 'fontSize': '13px'},
                style_header={'backgroundColor': '#4CAF50', 'fontWeight': 'bold', 'color': 'white'},
                style_cell_conditional=[
                    {'if': {'column_id': 'ITEM_NM'}, 'minWidth': '180px', 'textAlign': 'left'},
                    {'if': {'column_id': '1D'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': '1W'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': '1M'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': '3M'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': '6M'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': 'YTD'}, 'width': '65px', 'textAlign': 'right'},
                    {'if': {'column_id': 'Last Updated'}, 'width': '110px', 'textAlign': 'center'},
                ],
                style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': 'rgb(248, 248, 248)'}],
                page_size=50,
                sort_action='native',
                filter_action='native',
                export_format='xlsx',
                export_headers='display',
            )
        ], style={'marginBottom': 30, 'maxWidth': '1200px', 'margin': '0 auto'}),
    ])

], style={'padding': '20px', 'maxWidth': '1400px', 'margin': '0 auto'})


# =========================
# 9) 탭 표시/숨김 콜백
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


# =========================
# 10) 대시보드 콜백
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
     Output('performance-chart', 'figure'),
     Output('allocation-table', 'data'),
     Output('allocation-table', 'columns')],
    [Input('date-picker', 'date'),
     Input('fund-dropdown', 'value')]
)
def update_dashboard(selected_date, selected_fund):
    # 날짜 변환
    if isinstance(selected_date, str):
        selected_date = datetime.strptime(selected_date, '%Y-%m-%d').date()

    # 필터링
    df_holding_selected = holding[
        (holding['STD_DT'] == selected_date) &
        (holding['FUND_CD'] == selected_fund)
    ].copy()

    total_amt = df_holding_selected['EVL_AMT'].sum()

    # 정렬 순서 정의
    category_order = {'주식': 1, '채권': 2, '모펀드': 3, '현금': 4, '대체': 5, '통화': 6, '기타': 7}
    df_holding_selected['대분류_순서'] = df_holding_selected['대분류'].map(category_order).fillna(99)
    df_holding_selected = df_holding_selected.sort_values(['대분류_순서', 'EVL_AMT'], ascending=[True, False])

    # 보유 종목 테이블 (대분류 소계 포함)
    holdings_list = []
    current_category = None
    category_pct = 0
    category_weighted_returns = {col: 0 for col in ['1D', '1W', '1M', '3M', '6M', 'YTD']}
    category_valid_weight = {col: 0 for col in ['1D', '1W', '1M', '3M', '6M', 'YTD']}

    return_cols = ['1D', '1W', '1M', '3M', '6M', 'YTD']
    has_return_data = all(col in df_holding_selected.columns for col in return_cols)

    def format_return(value):
        if pd.isna(value) or value == '':
            return ''
        try:
            return round(float(value), 2)
        except (ValueError, TypeError):
            return ''

    for idx, row in df_holding_selected.iterrows():
        pct = (row['EVL_AMT'] / total_amt * 100) if total_amt > 0 else 0

        # 대분류가 바뀌면 이전 대분류 소계 추가
        if current_category and row['대분류'] != current_category:
            subtotal_row = {
                '대분류': f'▶ {current_category} 소계',
                'ITEM_NM': '',
                '비중(%)': round(category_pct, 2),
                '_is_subtotal': True,
                'Last Updated': ''
            }
            # 가중평균 수익률 계산
            for col in return_cols:
                if category_valid_weight[col] > 0:
                    weighted_avg = category_weighted_returns[col] / category_valid_weight[col]
                    subtotal_row[col] = round(weighted_avg, 2)
                else:
                    subtotal_row[col] = ''
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
            '_is_subtotal': False,
            'Last Updated': row.get('Last Updated', '') if has_return_data else ''
        }

        # 수익률 컬럼 추가 및 가중평균 누적
        if has_return_data:
            for col in return_cols:
                val = row.get(col)
                formatted_val = format_return(val)
                item_row[col] = formatted_val

                # 가중평균 계산을 위한 누적 (유효한 값만)
                if formatted_val != '' and pd.notna(val):
                    category_weighted_returns[col] += float(val) * pct
                    category_valid_weight[col] += pct
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
            '_is_subtotal': True,
            'Last Updated': ''
        }
        for col in return_cols:
            if category_valid_weight[col] > 0:
                weighted_avg = category_weighted_returns[col] / category_valid_weight[col]
                subtotal_row[col] = round(weighted_avg, 2)
            else:
                subtotal_row[col] = ''
        holdings_list.append(subtotal_row)

    holdings_table_data = holdings_list

    holdings_table_columns = [
        {'name': '대분류', 'id': '대분류'},
        {'name': '종목명', 'id': 'ITEM_NM'},
        {'name': '비중(%)', 'id': '비중(%)'},
        {'name': '1D(%)', 'id': '1D'},
        {'name': '1W(%)', 'id': '1W'},
        {'name': '1M(%)', 'id': '1M'},
        {'name': '3M(%)', 'id': '3M'},
        {'name': '6M(%)', 'id': '6M'},
        {'name': 'YTD(%)', 'id': 'YTD'},
        {'name': 'Last Updated', 'id': 'Last Updated'}
    ]

    # 소분류별 집계 (allocation table용)
    df_agg = df_holding_selected.groupby('소분류', as_index=False)['EVL_AMT'].sum()
    df_agg = df_agg[df_agg['EVL_AMT'] > 0].sort_values('EVL_AMT', ascending=False)
    df_agg['비중%'] = (df_agg['EVL_AMT'] / df_agg['EVL_AMT'].sum() * 100).round(2)
    df_agg['EVL_AMT_억'] = (df_agg['EVL_AMT'] / 100_000_000).round(2)

    # 시계열 스택 영역차트
    df_timeseries = holding[holding['FUND_CD'] == selected_fund].copy()
    df_ts_agg = df_timeseries.groupby(['STD_DT', '소분류'], as_index=False)['EVL_AMT'].sum()
    df_pivot = df_ts_agg.pivot(index='STD_DT', columns='소분류', values='EVL_AMT').fillna(0)

    fig_area = go.Figure()
    for col in df_pivot.columns:
        fig_area.add_trace(go.Scatter(
            x=df_pivot.index,
            y=df_pivot[col],
            mode='lines',
            name=col,
            stackgroup='one',
            hovertemplate='<b>%{fullData.name}</b><br>%{y:,.0f}원<extra></extra>'
        ))
    fig_area.update_layout(
        title='자산배분 추이',
        xaxis_title='날짜',
        yaxis_title='평가금액 (원)',
        height=400,
        hovermode='x unified',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    # 수익률/NAV 차트
    df_metrics_fund = metrics[metrics['FUND_CD'] == selected_fund].copy()

    fig_perf = make_subplots(
        rows=2, cols=1,
        subplot_titles=('누적수익률', 'NAV 추이'),
        vertical_spacing=0.12,
        row_heights=[0.5, 0.5]
    )

    fig_perf.add_trace(
        go.Scatter(
            x=df_metrics_fund['STD_DT'],
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
            x=df_metrics_fund['STD_DT'],
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

    # 테이블
    table_data = df_agg[['소분류', 'EVL_AMT_억', '비중%']].to_dict('records')
    table_columns = [
        {'name': '소분류', 'id': '소분류'},
        {'name': '금액 (억원)', 'id': 'EVL_AMT_억'},
        {'name': '비중 (%)', 'id': '비중%'}
    ]

    return holdings_table_data, holdings_table_columns, fig_area, fig_perf, table_data, table_columns


# =========================
# 11) 종목 리스트 탭 콜백
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

    # 종목 리스트 데이터 준비
    cols_to_show = ['ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류',
                    '1D', '1W', '1M', '3M', '6M', 'YTD', 'Last Updated']
    available_cols = [c for c in cols_to_show if c in master_with_returns.columns]

    item_list = master_with_returns[available_cols].copy()
    item_list = item_list.sort_values(['대분류', '지역', '소분류', 'ITEM_NM'])

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
# 12) Run
# =========================
if __name__ == '__main__':
    print("\n" + "="*80)
    print("자산배분 대시보드 시작 (통합 버전)")
    print("="*80)
    print(f"마스터 종목 수: {len(master_mapping)}")
    print(f"미분류 종목 수: {len(unmapped)}")
    print(f"SCIP 최신 영업일: {scip_latest_date}")
    print(f"대시보드 URL: http://127.0.0.1:8050")
    print("="*80 + "\n")

    app.run(debug=True, host='0.0.0.0', port=8050)
