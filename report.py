#!/usr/bin/env python3
"""
펀드 요약 리포트 (터미널 출력용)

Usage:
    python report.py --fund 06X08
    python report.py  # 대화형 입력

Features:
    - 편입종목별 수정기준가(MOD_STPR) 최근 4영업일 출력
    - 수정기준가 기반 일별 수익률(최근 3영업일) 출력
    - USD 자산의 경우 환율 반영 전/후 수익률 분리

환율 반영 규칙:
    - USD 자산: 수정기준가(KRW) = 기준가_USD(T-1) * 환율(USDKRW, T)
    - 순수 USD 수익률과 환차손익(FX 기여분) 분리 출력
"""

import argparse
import json
import sys
from datetime import datetime, date, timedelta

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text


# =========================
# 0) Database Configuration
# =========================
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"
CONN_STR_SCIP = "mysql+pymysql://solution:Solution123!@192.168.195.55/SCIP?charset=utf8mb4"

FUND_LIST = [
    '06X08','07G02','07G03','07G04','07J20','07J27','07J34','07J41',
    '07J48','07J49','07P70','07W15','08K88','08N33','08N81','08P22','09L94',
    '1JM96','1JM98','2JM23','4JM12'
]


# =========================
# 1) Utility Functions
# =========================
def get_currency_from_item_cd(item_cd: str) -> str:
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


def parse_price_blob(blob_data, currency: str = None):
    """
    Blob에서 가격 추출
    - currency: 'USD', 'KRW' 또는 None (전체 반환)

    Returns:
        - currency 지정 시: float 또는 None
        - currency=None 시: dict {'USD': float, 'KRW': float} 또는 None
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
                if currency is None:
                    # 전체 반환
                    result = {}
                    for key in ['USD', 'usd']:
                        if key in obj:
                            result['USD'] = float(obj[key])
                            break
                    for key in ['KRW', 'krw']:
                        if key in obj:
                            result['KRW'] = float(obj[key])
                            break
                    return result if result else None
                else:
                    # 특정 통화만
                    value = obj.get(currency) or obj.get(currency.lower())
                    return float(value) if value is not None else None
            return float(obj)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    try:
        val = float(s.replace(',', ''))
        if currency is None:
            return {'value': val}
        return val
    except (ValueError, AttributeError):
        return None


def get_fx_rate(blob_data):
    """
    Blob에서 USD/KRW 환율 추출 (1 USD = X KRW)
    dataset_id=31의 blob에서 "USD" 값이 환율
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
                value = obj.get('USD') or obj.get('usd')
                return float(value) if value is not None else None
            return float(obj)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    try:
        return float(s.replace(',', ''))
    except (ValueError, AttributeError):
        return None


def format_number(val, decimals=2):
    """숫자 포맷팅 (천단위 콤마)"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 'NA'
    return f"{val:,.{decimals}f}"


def format_return(val):
    """수익률 포맷팅 (%, +/- 부호)"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 'NA'
    sign = '+' if val >= 0 else ''
    return f"{sign}{val:.2f}%"


# =========================
# 2) Data Query Functions
# =========================
def get_business_days(engine, n_days: int = 10):
    """
    최근 n_days개 영업일 조회
    Returns: list of date objects (내림차순, 최신이 먼저)
    """
    query = text("""
    SELECT std_dt
    FROM dt.DWCI10220
    WHERE hldy_yn = 'N'
      AND day_ds_cd IN (2,3,4,5,6)
    ORDER BY std_dt DESC
    LIMIT :n_days
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={'n_days': n_days})

    if df.empty:
        return []

    dates = [datetime.strptime(str(int(x)), '%Y%m%d').date() for x in df['std_dt']]
    return dates


def get_fund_holdings(engine, fund_cd: str, std_dt: date):
    """
    특정 펀드의 특정 일자 편입종목 조회
    """
    std_dt_int = int(std_dt.strftime('%Y%m%d'))

    query = text("""
    SELECT
        ITEM_CD,
        ITEM_NM,
        SUM(EVL_AMT) AS EVL_AMT
    FROM dt.DWPM10530
    WHERE STD_DT = :std_dt
      AND FUND_CD = :fund_cd
      AND EVL_AMT > 0
    GROUP BY ITEM_CD, ITEM_NM
    ORDER BY EVL_AMT DESC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={'std_dt': std_dt_int, 'fund_cd': fund_cd})

    return df


def get_fund_name(engine, fund_cd: str) -> str:
    """펀드명 조회"""
    query = text("""
    SELECT FUND_NM
    FROM dt.DWPM10530
    WHERE FUND_CD = :fund_cd
    LIMIT 1
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {'fund_cd': fund_cd})
        row = result.fetchone()

    return row[0] if row else fund_cd


def fetch_item_prices(engine_scip, isin_list: list, target_dates: list):
    """
    SCIP DB에서 종목별 가격 데이터 조회 (dataseries_id=6)

    Returns:
        DataFrame with columns: ITEM_CD, date, data (blob)
    """
    if not isin_list or not target_dates:
        return pd.DataFrame(columns=['ITEM_CD', 'date', 'data'])

    query = text("""
    SELECT
        d.ISIN as ITEM_CD,
        DATE(dp.timestamp_observation) as date,
        dp.data
    FROM SCIP.back_datapoint dp
    INNER JOIN SCIP.back_dataset d ON dp.dataset_id = d.id
    WHERE d.ISIN IN :isin_list
      AND dp.dataseries_id = 6
      AND DATE(dp.timestamp_observation) IN :target_dates
    ORDER BY d.ISIN, dp.timestamp_observation
    """)

    try:
        with engine_scip.connect() as conn:
            df = pd.read_sql(query, conn, params={
                'isin_list': tuple(isin_list),
                'target_dates': tuple(target_dates)
            })
        return df
    except Exception as e:
        print(f"[ERROR] fetch_item_prices: {e}")
        return pd.DataFrame(columns=['ITEM_CD', 'date', 'data'])


def fetch_fx_rates(engine_scip, target_dates: list):
    """
    SCIP DB에서 USD/KRW 환율 조회 (dataset_id=31, dataseries_id=6)

    Returns:
        dict: {date: fx_rate (1 USD = X KRW)}
    """
    if not target_dates:
        return {}

    query = text("""
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
            df = pd.read_sql(query, conn, params={'target_dates': tuple(target_dates)})

        fx_rates = {}
        for _, row in df.iterrows():
            fx_rate = get_fx_rate(row['data'])
            if fx_rate is not None:
                fx_rates[row['date']] = fx_rate

        return fx_rates
    except Exception as e:
        print(f"[ERROR] fetch_fx_rates: {e}")
        return {}


# =========================
# 3) Core NAV Calculation Function
# =========================
def get_adj_nav(item_cd: str, item_nm: str, date_val: date,
                price_data: dict, fx_rates: dict, prev_date: date = None):
    """
    수정기준가 및 수익률 계산

    Parameters:
    -----------
    item_cd : str
        종목코드
    item_nm : str
        종목명
    date_val : date
        기준일
    price_data : dict
        {(ITEM_CD, date): {'USD': float, 'KRW': float}}
    fx_rates : dict
        {date: fx_rate}
    prev_date : date, optional
        전일 (수익률 계산용)

    Returns:
    --------
    dict with keys:
        - usd_nav: USD 기준가 (USD 자산인 경우)
        - krw_nav: KRW 기준가 (원래 통화 기준가)
        - fx: 환율 (USDKRW)
        - adj_krw_nav: 환율 반영 KRW 기준가 (USD 자산의 경우)
        - pure_usd_return: 순수 USD 수익률 (%)
        - fx_return: 환율 기여 수익률 (%)
        - total_krw_return: 총 KRW 수익률 (%)
        - currency: 'USD' or 'KRW'
    """
    currency = get_currency_from_item_cd(item_cd)

    # 현재일 가격 조회
    current_key = (item_cd, date_val)
    current_prices = price_data.get(current_key, {})

    # 환율 조회
    fx = fx_rates.get(date_val)

    result = {
        'usd_nav': None,
        'krw_nav': None,
        'fx': fx,
        'adj_krw_nav': None,
        'pure_usd_return': None,
        'fx_return': None,
        'total_krw_return': None,
        'currency': currency
    }

    if currency == 'USD':
        # USD 자산
        result['usd_nav'] = current_prices.get('USD')
        result['krw_nav'] = current_prices.get('KRW')

        # 환율 반영 KRW 기준가 계산
        # 규칙: adj_krw_nav = usd_nav(T-1) * fx(T) 또는 직접 KRW 값 사용
        if result['krw_nav'] is not None:
            result['adj_krw_nav'] = result['krw_nav']
        elif result['usd_nav'] is not None and fx is not None:
            result['adj_krw_nav'] = result['usd_nav'] * fx

        # 수익률 계산 (전일 데이터 필요)
        if prev_date is not None:
            prev_key = (item_cd, prev_date)
            prev_prices = price_data.get(prev_key, {})
            prev_usd = prev_prices.get('USD')
            prev_krw = prev_prices.get('KRW')
            prev_fx = fx_rates.get(prev_date)

            # 순수 USD 수익률
            if result['usd_nav'] is not None and prev_usd is not None and prev_usd > 0:
                result['pure_usd_return'] = (result['usd_nav'] / prev_usd - 1) * 100

            # 환율 기여분
            if fx is not None and prev_fx is not None and prev_fx > 0:
                result['fx_return'] = (fx / prev_fx - 1) * 100

            # 총 KRW 수익률
            if result['krw_nav'] is not None and prev_krw is not None and prev_krw > 0:
                result['total_krw_return'] = (result['krw_nav'] / prev_krw - 1) * 100
            elif (result['pure_usd_return'] is not None and
                  result['fx_return'] is not None):
                # 근사 계산: (1+r_usd)*(1+r_fx) - 1
                r_usd = result['pure_usd_return'] / 100
                r_fx = result['fx_return'] / 100
                result['total_krw_return'] = ((1 + r_usd) * (1 + r_fx) - 1) * 100
    else:
        # KRW 자산
        result['krw_nav'] = current_prices.get('KRW') or current_prices.get('value')
        result['adj_krw_nav'] = result['krw_nav']

        # 수익률 계산
        if prev_date is not None:
            prev_key = (item_cd, prev_date)
            prev_prices = price_data.get(prev_key, {})
            prev_krw = prev_prices.get('KRW') or prev_prices.get('value')

            if result['krw_nav'] is not None and prev_krw is not None and prev_krw > 0:
                result['total_krw_return'] = (result['krw_nav'] / prev_krw - 1) * 100

    return result


# =========================
# 4) Report Generation
# =========================
def generate_report(fund_cd: str):
    """
    펀드 요약 리포트 생성 및 터미널 출력
    """
    print(f"\n[INFO] Initializing database connections...")
    engine = create_engine(CONN_STR)
    engine_scip = create_engine(CONN_STR_SCIP)

    # 1) 영업일 조회 (최근 10일 → 4영업일 + 버퍼)
    print("[INFO] Fetching business days...")
    bdays = get_business_days(engine, n_days=10)

    if len(bdays) < 4:
        print("[ERROR] 영업일 데이터가 부족합니다 (최소 4일 필요)")
        return

    # 최근 4영업일 (내림차순)
    target_dates = bdays[:4]
    latest_date = target_dates[0]

    print(f"[INFO] Target dates: {[str(d) for d in target_dates]}")

    # 2) 펀드 편입종목 조회
    print(f"[INFO] Fetching holdings for fund {fund_cd}...")
    holdings = get_fund_holdings(engine, fund_cd, latest_date)

    if holdings.empty:
        print(f"[ERROR] 펀드 {fund_cd}의 편입종목이 없습니다.")
        print(f"        유효한 펀드코드: {', '.join(FUND_LIST)}")
        return

    fund_nm = get_fund_name(engine, fund_cd)

    print(f"[INFO] Found {len(holdings)} items in fund")

    # 3) 종목별 가격 데이터 조회
    isin_list = holdings['ITEM_CD'].tolist()
    print(f"[INFO] Fetching price data for {len(isin_list)} items...")

    price_df = fetch_item_prices(engine_scip, isin_list, target_dates)

    # 가격 데이터 파싱
    price_data = {}
    for _, row in price_df.iterrows():
        item_cd = row['ITEM_CD']
        date_val = row['date']
        prices = parse_price_blob(row['data'], currency=None)
        if prices:
            price_data[(item_cd, date_val)] = prices

    print(f"[INFO] Parsed {len(price_data)} price data points")

    # 4) 환율 데이터 조회
    print("[INFO] Fetching FX rates...")
    fx_rates = fetch_fx_rates(engine_scip, target_dates)
    print(f"[INFO] FX rates loaded for {len(fx_rates)} days")

    # 5) 수정기준가 및 수익률 계산
    print("[INFO] Calculating adjusted NAV and returns...")

    # Section A 데이터 구성: 최근 4영업일 수정기준가
    section_a_data = []
    for _, item_row in holdings.iterrows():
        item_cd = item_row['ITEM_CD']
        item_nm = item_row['ITEM_NM']
        currency = get_currency_from_item_cd(item_cd)

        for date_val in target_dates:
            nav_result = get_adj_nav(item_cd, item_nm, date_val, price_data, fx_rates)

            if currency == 'USD':
                # USD 자산: USD와 KRW 모두 출력
                section_a_data.append({
                    'date': date_val,
                    'ITEM_CD': item_cd,
                    'ITEM_NM': item_nm[:30],  # 종목명 잘라내기
                    'CCY': 'USD',
                    'MOD_STPR': nav_result['usd_nav']
                })
                section_a_data.append({
                    'date': date_val,
                    'ITEM_CD': item_cd,
                    'ITEM_NM': item_nm[:30],
                    'CCY': 'KRW',
                    'MOD_STPR': nav_result['adj_krw_nav']
                })
            else:
                # KRW 자산
                section_a_data.append({
                    'date': date_val,
                    'ITEM_CD': item_cd,
                    'ITEM_NM': item_nm[:30],
                    'CCY': 'KRW',
                    'MOD_STPR': nav_result['krw_nav']
                })

    # Section B 데이터 구성: 최근 3영업일 수익률
    section_b_data = []
    for _, item_row in holdings.iterrows():
        item_cd = item_row['ITEM_CD']
        item_nm = item_row['ITEM_NM']
        currency = get_currency_from_item_cd(item_cd)

        # 최근 3영업일 (T-0, T-1, T-2) + 전일 데이터 필요 (T-3)
        for i in range(3):  # target_dates[0], [1], [2]
            date_val = target_dates[i]
            prev_date = target_dates[i + 1] if i + 1 < len(target_dates) else None

            nav_result = get_adj_nav(item_cd, item_nm, date_val, price_data, fx_rates, prev_date)

            if currency == 'USD':
                # USD 자산: 순수 USD 수익률 + 환율 기여 + 총 KRW 수익률
                section_b_data.append({
                    'date': date_val,
                    'ITEM_CD': item_cd,
                    'ITEM_NM': item_nm[:30],
                    'CCY': 'USD',
                    'return': nav_result['pure_usd_return'],
                    'type': 'Asset Return'
                })
                section_b_data.append({
                    'date': date_val,
                    'ITEM_CD': item_cd,
                    'ITEM_NM': item_nm[:30],
                    'CCY': 'FX',
                    'return': nav_result['fx_return'],
                    'type': 'FX Impact'
                })
                section_b_data.append({
                    'date': date_val,
                    'ITEM_CD': item_cd,
                    'ITEM_NM': item_nm[:30],
                    'CCY': 'KRW',
                    'return': nav_result['total_krw_return'],
                    'type': 'Total (KRW)'
                })
            else:
                # KRW 자산
                section_b_data.append({
                    'date': date_val,
                    'ITEM_CD': item_cd,
                    'ITEM_NM': item_nm[:30],
                    'CCY': 'KRW',
                    'return': nav_result['total_krw_return'],
                    'type': 'Total'
                })

    # 6) 터미널 출력
    print_report(fund_cd, fund_nm, latest_date, section_a_data, section_b_data, fx_rates, target_dates)


def print_report(fund_cd, fund_nm, latest_date, section_a_data, section_b_data, fx_rates, target_dates):
    """
    터미널 출력 포맷팅
    """
    width = 100

    # 헤더
    print("\n" + "=" * width)
    print(f" 펀드코드: {fund_cd} | 펀드명: {fund_nm}")
    print(f" 기준일: {latest_date}")
    print("=" * width)

    # 환율 정보
    print("\n[FX] USD/KRW 환율 (최근 4영업일)")
    print("-" * 50)
    for d in target_dates:
        fx = fx_rates.get(d)
        fx_str = f"{fx:,.2f}" if fx else "NA"
        print(f"  {d}  :  {fx_str} KRW/USD")

    # Section A: 수정기준가
    print("\n" + "-" * width)
    print("[A] 수정기준가(MOD_STPR) - 최근 4영업일")
    print("-" * width)

    if section_a_data:
        df_a = pd.DataFrame(section_a_data)

        # 피벗 테이블 생성: 행=종목, 열=날짜
        # 종목별로 그룹화하여 출력
        unique_items = df_a[['ITEM_CD', 'ITEM_NM']].drop_duplicates()

        # 헤더 출력
        date_headers = [d.strftime('%m-%d') for d in sorted(set(df_a['date']), reverse=True)]
        header = f"{'ITEM_CD':<15} {'CCY':<5} " + " ".join([f"{d:>12}" for d in date_headers])
        print(header)
        print("-" * len(header))

        for _, item in unique_items.iterrows():
            item_cd = item['ITEM_CD']
            item_nm = item['ITEM_NM']
            item_data = df_a[df_a['ITEM_CD'] == item_cd]

            # 통화별로 출력
            for ccy in item_data['CCY'].unique():
                ccy_data = item_data[item_data['CCY'] == ccy]

                # 날짜별 값 구성
                values = []
                for d in sorted(set(df_a['date']), reverse=True):
                    row = ccy_data[ccy_data['date'] == d]
                    if not row.empty and row.iloc[0]['MOD_STPR'] is not None:
                        val = row.iloc[0]['MOD_STPR']
                        if ccy == 'KRW':
                            values.append(f"{val:>12,.0f}")
                        else:
                            values.append(f"{val:>12,.4f}")
                    else:
                        values.append(f"{'NA':>12}")

                item_cd_display = item_cd[:15] if len(item_cd) > 15 else item_cd
                line = f"{item_cd_display:<15} {ccy:<5} " + " ".join(values)
                print(line)

            # 종목명 출력 (다음 줄에)
            print(f"  └─ {item_nm}")
    else:
        print("  데이터 없음")

    # Section B: 수익률
    print("\n" + "-" * width)
    print("[B] 수정기준가 기반 일별 수익률 - 최근 3영업일")
    print("    (USD 자산: Asset Return = 순수 USD 수익률, FX Impact = 환율 기여, Total = 환율 반영 KRW 수익률)")
    print("-" * width)

    if section_b_data:
        df_b = pd.DataFrame(section_b_data)

        unique_items = df_b[['ITEM_CD', 'ITEM_NM']].drop_duplicates()

        # 헤더 출력
        date_headers = [d.strftime('%m-%d') for d in sorted(set(df_b['date']), reverse=True)[:3]]
        header = f"{'ITEM_CD':<15} {'Type':<15} " + " ".join([f"{d:>10}" for d in date_headers])
        print(header)
        print("-" * len(header))

        for _, item in unique_items.iterrows():
            item_cd = item['ITEM_CD']
            item_nm = item['ITEM_NM']
            item_data = df_b[df_b['ITEM_CD'] == item_cd]

            # 타입별로 출력
            for ret_type in item_data['type'].unique():
                type_data = item_data[item_data['type'] == ret_type]

                # 날짜별 값 구성
                values = []
                for d in sorted(set(df_b['date']), reverse=True)[:3]:
                    row = type_data[type_data['date'] == d]
                    if not row.empty and row.iloc[0]['return'] is not None:
                        val = row.iloc[0]['return']
                        values.append(format_return(val).rjust(10))
                    else:
                        values.append(f"{'NA':>10}")

                item_cd_display = item_cd[:15] if len(item_cd) > 15 else item_cd
                line = f"{item_cd_display:<15} {ret_type:<15} " + " ".join(values)
                print(line)

            # 종목명 출력
            print(f"  └─ {item_nm}")
    else:
        print("  데이터 없음")

    print("\n" + "=" * width)
    print(f" 리포트 생성 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * width + "\n")


# =========================
# 5) CLI Entry Point
# =========================
def main():
    parser = argparse.ArgumentParser(
        description='펀드 요약 리포트 (터미널 출력용)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
    python report.py --fund 06X08
    python report.py --fund 08K88

Available funds:
    {', '.join(FUND_LIST)}
        """
    )
    parser.add_argument(
        '--fund', '-f',
        type=str,
        default='',
        help='펀드코드 (예: 06X08)'
    )

    args = parser.parse_args()

    fund_cd = args.fund.strip()

    # 빈칸 입력 시 대화형으로 입력 받기
    if not fund_cd:
        print("\n펀드 요약 리포트 (터미널 출력용)")
        print("-" * 40)
        print(f"유효한 펀드코드: {', '.join(FUND_LIST)}")
        print("-" * 40)
        fund_cd = input("펀드코드 입력 (빈칸=종료): ").strip()

        if not fund_cd:
            print("[INFO] 빈칸 입력으로 종료합니다.")
            return

    # 펀드코드 유효성 검사
    if fund_cd not in FUND_LIST:
        print(f"[WARNING] {fund_cd}는 FUND_LIST에 없습니다. 조회를 시도합니다...")

    generate_report(fund_cd)


if __name__ == '__main__':
    main()
