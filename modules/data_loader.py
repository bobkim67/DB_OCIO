# === data_loader.py ===
# DB 접속 및 데이터 로딩 레이어
# R benchmark: module_00_data_loading.R
import pandas as pd
import numpy as np
import pymysql
from datetime import datetime, timedelta
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# DB 접속
# ============================================================

DB_CONFIG = {
    'host': '192.168.195.55',
    'user': 'solution',
    'password': 'Solution123!',
    'charset': 'utf8mb4',
}

def get_connection(db_name: str):
    """MariaDB 접속. R: dbConnect(RMariaDB::MariaDB(), ...)"""
    return pymysql.connect(**DB_CONFIG, db=db_name, cursorclass=pymysql.cursors.DictCursor)


# ============================================================
# 한국 영업일 캘린더
# R benchmark: dt.DWCI10220 → holiday_calendar, selectable_dates
# ============================================================

def load_holiday_calendar() -> pd.DataFrame:
    """한국 공휴일/영업일 캘린더 로드"""
    conn = get_connection('dt')
    try:
        sql = """
            SELECT CAL_DT, HOLI_FG
            FROM DWCI10220
            WHERE CAL_DT >= '20000101'
            ORDER BY CAL_DT
        """
        df = pd.read_sql(sql, conn)
        df['CAL_DT'] = pd.to_datetime(df['CAL_DT'], format='%Y%m%d')
        return df
    finally:
        conn.close()


def get_business_days(holiday_df: pd.DataFrame) -> pd.DatetimeIndex:
    """영업일만 추출. R: selectable_dates"""
    bdays = holiday_df[holiday_df['HOLI_FG'] == '0']['CAL_DT']
    return pd.DatetimeIndex(bdays)


def get_latest_business_day(holiday_df: pd.DataFrame) -> pd.Timestamp:
    """최근 영업일. R: 최근영업일"""
    bdays = get_business_days(holiday_df)
    today = pd.Timestamp.now().normalize()
    past = bdays[bdays <= today]
    return past[-1] if len(past) > 0 else today


# ============================================================
# 펀드 기준가 (수정기준가)
# R benchmark: dt.DWPM10510 → BOS_historical_price
# ============================================================

def load_fund_nav(fund_codes: list, start_date: str = None) -> pd.DataFrame:
    """
    펀드 수정기준가 시계열 로드.
    R: BOS_historical_price (MOD_STPR)

    Returns: DataFrame(기준일자, FUND_CD, MOD_STPR, NAST_AMT, DD1_ERN_RT)
    """
    conn = get_connection('dt')
    try:
        placeholders = ','.join(['%s'] * len(fund_codes))
        where_date = f"AND STD_DT >= '{start_date}'" if start_date else ""
        sql = f"""
            SELECT STD_DT, FUND_CD, MOD_STPR, NAST_AMT, DD1_ERN_RT
            FROM DWPM10510
            WHERE FUND_CD IN ({placeholders}) {where_date}
            ORDER BY FUND_CD, STD_DT
        """
        df = pd.read_sql(sql, conn, params=fund_codes)
        df['기준일자'] = pd.to_datetime(df['STD_DT'], format='%Y%m%d')
        return df
    finally:
        conn.close()


def load_fund_nav_wide(fund_codes: list, start_date: str = None) -> pd.DataFrame:
    """
    펀드 기준가를 wide form으로 변환 (기준일자 x FUND_CD).
    """
    df = load_fund_nav(fund_codes, start_date)
    pivot = df.pivot_table(index='기준일자', columns='FUND_CD', values='MOD_STPR')
    pivot = pivot.sort_index()
    return pivot


# ============================================================
# 펀드 보유종목
# R benchmark: dt.DWPM10530
# ============================================================

def load_fund_holdings(fund_code: str, date: str = None) -> pd.DataFrame:
    """
    펀드 보유종목 상세. R: DWPM10530
    date 미지정 시 최근일 조회.
    """
    conn = get_connection('dt')
    try:
        if date is None:
            sql_date = f"""
                SELECT MAX(STD_DT) as max_dt FROM DWPM10530 WHERE FUND_CD = %s
            """
            with conn.cursor() as cur:
                cur.execute(sql_date, (fund_code,))
                date = cur.fetchone()['max_dt']

        sql = """
            SELECT STD_DT, FUND_CD, FUND_NM, ITEM_CD, ITEM_NM,
                   AST_CLSF_CD_NM, CURR_DS_CD,
                   EVL_AMT, NAST_TAMT_AGNST_WGH, AST_AGNST_WGH,
                   EVL_ERN_RT, QTY, ACQ_AMT, DUR, MOD_DUR
            FROM DWPM10530
            WHERE FUND_CD = %s AND STD_DT = %s
            ORDER BY EVL_AMT DESC
        """
        df = pd.read_sql(sql, conn, params=[fund_code, date])
        df['기준일자'] = pd.to_datetime(df['STD_DT'], format='%Y%m%d')
        return df
    finally:
        conn.close()


def load_fund_holdings_history(fund_code: str, start_date: str = None) -> pd.DataFrame:
    """보유종목 비중 히스토리 (자산군별 집계)"""
    conn = get_connection('dt')
    try:
        where_date = f"AND STD_DT >= '{start_date}'" if start_date else ""
        sql = f"""
            SELECT STD_DT, AST_CLSF_CD_NM,
                   SUM(EVL_AMT) as total_evl,
                   SUM(NAST_TAMT_AGNST_WGH) as total_weight
            FROM DWPM10530
            WHERE FUND_CD = %s {where_date}
            GROUP BY STD_DT, AST_CLSF_CD_NM
            ORDER BY STD_DT, AST_CLSF_CD_NM
        """
        df = pd.read_sql(sql, conn, params=[fund_code])
        df['기준일자'] = pd.to_datetime(df['STD_DT'], format='%Y%m%d')
        return df
    finally:
        conn.close()


# ============================================================
# 펀드 PA 원천 데이터
# R benchmark: dt.MA000410 → get_PA_source_data()
# ============================================================

def load_pa_source(fund_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    펀드 PA 원천 데이터 로드.
    R: get_PA_source_data(fund_cd, start_date, end_date)
    """
    conn = get_connection('dt')
    try:
        conditions = ["fund_id = %s"]
        params = [fund_code]
        if start_date:
            conditions.append("pr_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("pr_date <= %s")
            params.append(end_date)
        where = " AND ".join(conditions)

        sql = f"""
            SELECT pr_date, fund_id, asset_gb, sec_id,
                   amt, val, std_val, modify_unav_chg
            FROM MA000410
            WHERE {where}
            ORDER BY pr_date, asset_gb
        """
        df = pd.read_sql(sql, conn, params=params)
        df['기준일자'] = pd.to_datetime(df['pr_date'], format='%Y%m%d')
        return df
    finally:
        conn.close()


# ============================================================
# 자산군 분류체계
# R benchmark: solution.universe_non_derivative → classification
# ============================================================

def load_classification_mapping() -> pd.DataFrame:
    """
    자산 유니버스 분류 매핑 테이블.
    R: universe_non_derivative_table
    """
    conn = get_connection('solution')
    try:
        sql = """
            SELECT primary_source_id as dataset_id, ISIN,
                   classification_method, classification,
                   colname_backtest, primary_source
            FROM universe_non_derivative
            WHERE classification_method IS NOT NULL
        """
        return pd.read_sql(sql, conn)
    finally:
        conn.close()


# ============================================================
# SCIP 가격 데이터
# R benchmark: SCIP.back_datapoint
# ============================================================

def load_scip_prices(dataset_ids: list, dataseries_ids: list = None) -> pd.DataFrame:
    """
    SCIP 지수/가격 데이터 로드.
    R: pulled_data_universe_SCIP
    """
    conn = get_connection('SCIP')
    try:
        placeholders = ','.join(['%s'] * len(dataset_ids))
        sql = f"""
            SELECT dataset_id, dataseries_id, timestamp_observation, data
            FROM back_datapoint
            WHERE dataset_id IN ({placeholders})
            ORDER BY dataset_id, timestamp_observation
        """
        df = pd.read_sql(sql, conn, params=dataset_ids)
        df['기준일자'] = pd.to_datetime(df['timestamp_observation'])
        return df
    finally:
        conn.close()


# ============================================================
# 환율 데이터
# R benchmark: USDKRW (ECOS API), F_USDKRW_Index (SCIP)
# ============================================================

def load_usdkrw_from_ecos(api_key: str = '7FA9V1N76SFHX6GXHI58') -> pd.DataFrame:
    """
    원달러 환율 (ECOS API 731Y003).
    R: USDKRW
    """
    import requests
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/10000/731Y003/D/20000101/99991231/0000001"
    try:
        resp = requests.get(url, timeout=30)
        data = resp.json()
        rows = data.get('StatisticSearch', {}).get('row', [])
        if not rows:
            return pd.DataFrame(columns=['기준일자', 'USD/KRW'])
        df = pd.DataFrame(rows)
        df['기준일자'] = pd.to_datetime(df['TIME'], format='%Y%m%d')
        df['USD/KRW'] = pd.to_numeric(df['DATA_VALUE'], errors='coerce')
        return df[['기준일자', 'USD/KRW']].dropna().sort_values('기준일자').reset_index(drop=True)
    except Exception as e:
        print(f"ECOS API error: {e}")
        return pd.DataFrame(columns=['기준일자', 'USD/KRW'])


# ============================================================
# 펀드 요약 정보 (최근일 기준)
# ============================================================

def load_fund_summary(fund_codes: list) -> pd.DataFrame:
    """전체 펀드 최근 요약 정보 (AUM, 기준가, 수익률)"""
    conn = get_connection('dt')
    try:
        placeholders = ','.join(['%s'] * len(fund_codes))
        sql = f"""
            SELECT a.FUND_CD, a.STD_DT, a.MOD_STPR, a.NAST_AMT, a.DD1_ERN_RT,
                   a.STK_EVL_AMT, a.BND_EVL_AMT, a.CASH_EVL_AMT,
                   a.OVS_STK_EVL_AMT, a.OVS_BND_EVL_AMT,
                   a.FUND_DUR, a.FUND_MOD_DUR
            FROM DWPM10510 a
            INNER JOIN (
                SELECT FUND_CD, MAX(STD_DT) as max_dt
                FROM DWPM10510
                WHERE FUND_CD IN ({placeholders})
                GROUP BY FUND_CD
            ) b ON a.FUND_CD = b.FUND_CD AND a.STD_DT = b.max_dt
            ORDER BY a.NAST_AMT DESC
        """
        df = pd.read_sql(sql, conn, params=fund_codes)
        df['기준일자'] = pd.to_datetime(df['STD_DT'], format='%Y%m%d')
        df['AUM_억'] = df['NAST_AMT'] / 1e8
        return df
    finally:
        conn.close()


def load_fund_period_return(fund_code: str, start_date: str, end_date: str) -> float:
    """특정 기간 펀드 수익률 계산 (기준가 기반)"""
    conn = get_connection('dt')
    try:
        sql = """
            SELECT STD_DT, MOD_STPR
            FROM DWPM10510
            WHERE FUND_CD = %s AND STD_DT BETWEEN %s AND %s
            ORDER BY STD_DT
        """
        df = pd.read_sql(sql, conn, params=[fund_code, start_date, end_date])
        if len(df) < 2:
            return np.nan
        return df['MOD_STPR'].iloc[-1] / df['MOD_STPR'].iloc[0] - 1
    finally:
        conn.close()


# ============================================================
# 통합 로더 (캐시용)
# ============================================================

def load_all_fund_data(fund_codes: list) -> dict:
    """
    전체 펀드 데이터 한번에 로드. Streamlit @st.cache_data 용.
    """
    result = {
        'summary': load_fund_summary(fund_codes),
        'holiday': load_holiday_calendar(),
    }
    result['latest_bday'] = get_latest_business_day(result['holiday'])
    return result
