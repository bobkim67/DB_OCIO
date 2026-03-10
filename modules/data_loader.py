# === data_loader.py ===
# DB 접속 및 데이터 로딩 레이어
# R benchmark: module_00_data_loading.R
import pandas as pd
import numpy as np
import pymysql
from datetime import datetime, timedelta
import json
import warnings
import logging
warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)

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
    """MariaDB 접속 (DictCursor). cursor 직접 사용 시."""
    return pymysql.connect(**DB_CONFIG, db=db_name, cursorclass=pymysql.cursors.DictCursor)


def get_pandas_connection(db_name: str):
    """MariaDB 접속 (일반 커서). pd.read_sql 용 — DictCursor는 pd.read_sql과 호환 안됨."""
    return pymysql.connect(**DB_CONFIG, db=db_name)


# ============================================================
# SCIP blob 파싱 (공용)
# Monitoring/market.py:54 패턴 재사용
# ============================================================

def parse_data_blob(blob, currency: str = None):
    """
    SCIP back_datapoint.data longblob 파싱.

    blob 형태 3가지:
      {"USD": 608.66, "KRW": 868066.70}  → dict
      2451.187912                          → float
      "13.06"                              → float

    currency 지정 시 해당 키 값만 반환, 미지정 시 dict 또는 float.
    """
    if blob is None:
        return np.nan
    if isinstance(blob, (bytes, bytearray)):
        s = blob.decode('utf-8')
    else:
        s = str(blob)
    s = s.strip().strip('"')
    try:
        if s.startswith('{'):
            obj = json.loads(s)
            if isinstance(obj, dict):
                parsed = {k: float(v) for k, v in obj.items()}
                if currency and currency in parsed:
                    return parsed[currency]
                return parsed
        return float(s.replace(',', ''))
    except (ValueError, json.JSONDecodeError):
        return np.nan


# ============================================================
# 한국 영업일 캘린더
# R benchmark: dt.DWCI10220 → holiday_calendar, selectable_dates
# ============================================================

def load_holiday_calendar() -> pd.DataFrame:
    """한국 공휴일/영업일 캘린더 로드"""
    conn = get_pandas_connection('dt')
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
    conn = get_pandas_connection('dt')
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
    if date is None:
        conn_dict = get_connection('dt')
        try:
            with conn_dict.cursor() as cur:
                cur.execute("SELECT MAX(STD_DT) as max_dt FROM DWPM10530 WHERE FUND_CD = %s", (fund_code,))
                date = cur.fetchone()['max_dt']
        finally:
            conn_dict.close()

    conn = get_pandas_connection('dt')
    try:
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
    conn = get_pandas_connection('dt')
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
    펀드 PA 원천 데이터 로드 (확장).
    R: get_PA_source_data(fund_cd, start_date, end_date)

    Phase 4: position_gb, pl_gb, crrncy_cd, os_gb 추가.
    """
    conn = get_pandas_connection('dt')
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
                   position_gb, pl_gb, crrncy_cd, os_gb,
                   amt, val, std_val, modify_unav_chg
            FROM MA000410
            WHERE {where}
            ORDER BY pr_date, sec_id
        """
        df = pd.read_sql(sql, conn, params=params)
        df['기준일자'] = pd.to_datetime(df['pr_date'], format='%Y%m%d')
        return df
    finally:
        conn.close()


def _load_daily_nast(fund_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """일별 순자산/기준가 (DWPM10510)."""
    conn = get_pandas_connection('dt')
    try:
        conditions = ["FUND_CD = %s", "IMC_CD = '003228'"]
        params = [fund_code]
        if start_date:
            conditions.append("STD_DT >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("STD_DT <= %s")
            params.append(end_date)
        where = " AND ".join(conditions)
        sql = f"""
            SELECT STD_DT, MOD_STPR, NAST_AMT, PDD_CHNG_STPR
            FROM DWPM10510
            WHERE {where}
            ORDER BY STD_DT
        """
        df = pd.read_sql(sql, conn, params=params)
        df['기준일자'] = pd.to_datetime(df['STD_DT'].astype(str), format='%Y%m%d')
        return df
    finally:
        conn.close()


def _load_net_subscription(fund_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """일별 순설정금액 (DWPM12880)."""
    conn = get_pandas_connection('dt')
    try:
        conditions = ["fund_cd = %s"]
        params = [fund_code]
        if start_date:
            conditions.append("tr_dt >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("tr_dt <= %s")
            params.append(end_date)
        where = " AND ".join(conditions)
        sql = f"""
            SELECT tr_dt,
                   SUM(ocpy_flct_amt) as net_subscription
            FROM DWPM12880
            WHERE {where}
            GROUP BY tr_dt
            ORDER BY tr_dt
        """
        df = pd.read_sql(sql, conn, params=params)
        if not df.empty:
            df['기준일자'] = pd.to_datetime(df['tr_dt'].astype(str), format='%Y%m%d')
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
    conn = get_pandas_connection('solution')
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

def load_scip_prices(dataset_ids: list, dataseries_ids: list = None,
                     start_date: str = None) -> pd.DataFrame:
    """
    SCIP 지수/가격 데이터 로드.
    R: pulled_data_universe_SCIP

    dataseries_ids: 필터할 dataseries id 리스트 (None이면 전체)
    start_date: 'YYYY-MM-DD' 형식 시작일 필터
    """
    conn = get_pandas_connection('SCIP')
    try:
        params = list(dataset_ids)
        placeholders = ','.join(['%s'] * len(dataset_ids))
        where_extra = ""
        if dataseries_ids:
            ds_ph = ','.join(['%s'] * len(dataseries_ids))
            where_extra += f" AND dataseries_id IN ({ds_ph})"
            params.extend(dataseries_ids)
        if start_date:
            where_extra += " AND timestamp_observation >= %s"
            params.append(start_date)
        sql = f"""
            SELECT dataset_id, dataseries_id, timestamp_observation, data
            FROM back_datapoint
            WHERE dataset_id IN ({placeholders}) {where_extra}
            ORDER BY dataset_id, timestamp_observation
        """
        df = pd.read_sql(sql, conn, params=params)
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
    conn = get_pandas_connection('dt')
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
    conn = get_pandas_connection('dt')
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

def load_all_fund_data(fund_codes: list, start_date: str = None) -> dict:
    """
    전체 펀드 데이터 한번에 로드. Streamlit @st.cache_data 용.
    nav 데이터도 포함.
    """
    result = {
        'summary': load_fund_summary(fund_codes),
        'holiday': load_holiday_calendar(),
        'nav': load_fund_nav(fund_codes, start_date),
    }
    result['latest_bday'] = get_latest_business_day(result['holiday'])
    return result


# ============================================================
# SCIP BM 지수 시계열
# ============================================================

def load_scip_bm_prices(dataset_id: int, dataseries_id: int,
                        start_date: str = None, currency: str = None) -> pd.DataFrame:
    """
    SCIP에서 BM 지수 시계열 로드.
    dataseries_id=39(FG Total Return Index)는 단일 숫자,
    dataseries_id=6(FG Return)은 {"USD":x, "KRW":y} JSON.

    Returns: DataFrame(기준일자, value)
    """
    conn = get_pandas_connection('SCIP')
    try:
        params = [dataset_id, dataseries_id]
        where_date = ""
        if start_date:
            where_date = " AND timestamp_observation >= %s"
            params.append(start_date)
        sql = f"""
            SELECT timestamp_observation, data
            FROM back_datapoint
            WHERE dataset_id = %s AND dataseries_id = %s {where_date}
            ORDER BY timestamp_observation
        """
        df = pd.read_sql(sql, conn, params=params)
        if df.empty:
            return pd.DataFrame(columns=['기준일자', 'value'])
        df['기준일자'] = pd.to_datetime(df['timestamp_observation']).dt.normalize()
        df['value'] = df['data'].apply(lambda b: parse_data_blob(b, currency))
        df = df[df['value'].notna() & df['value'].apply(lambda v: isinstance(v, (int, float)))]
        df['value'] = df['value'].astype(float)
        return df[['기준일자', 'value']].reset_index(drop=True)
    finally:
        conn.close()


# ============================================================
# SCIP 환율 (USD/KRW)
# Monitoring/report.py:112 get_fx_rate() 참조
# ============================================================

def load_usdkrw_from_scip(start_date: str = None) -> pd.DataFrame:
    """
    SCIP에서 USD/KRW 환율 로드.
    dataset_id=31, dataseries_id=6, blob에서 "USD" 키.

    Returns: DataFrame(기준일자, USD/KRW)
    """
    conn = get_pandas_connection('SCIP')
    try:
        params = [31, 6]
        where_date = ""
        if start_date:
            where_date = " AND timestamp_observation >= %s"
            params.append(start_date)
        sql = f"""
            SELECT timestamp_observation, data
            FROM back_datapoint
            WHERE dataset_id = %s AND dataseries_id = %s {where_date}
            ORDER BY timestamp_observation
        """
        df = pd.read_sql(sql, conn, params=params)
        if df.empty:
            return pd.DataFrame(columns=['기준일자', 'USD/KRW'])
        df['기준일자'] = pd.to_datetime(df['timestamp_observation']).dt.normalize()
        df['USD/KRW'] = df['data'].apply(lambda b: parse_data_blob(b, 'USD'))
        df = df[df['USD/KRW'].notna()]
        df['USD/KRW'] = df['USD/KRW'].astype(float)
        return df[['기준일자', 'USD/KRW']].reset_index(drop=True)
    finally:
        conn.close()


# ============================================================
# 보유종목 + 6분류 매핑
# Monitoring/auto_classify.py 패턴 + AST_CLSF_CD_NM 결합
# ============================================================

def _classify_6class(row) -> str:
    """
    AST_CLSF_CD_NM + ITEM_CD + ITEM_NM 조합으로 6분류 매핑.
    국내주식 / 해외주식 / 국내채권 / 해외채권 / 대체투자 / 유동성
    """
    ast = str(row.get('AST_CLSF_CD_NM', '')).upper()
    item_cd = str(row.get('ITEM_CD', '')).upper()
    item_nm = str(row.get('ITEM_NM', '')).upper()
    curr = str(row.get('CURR_DS_CD', '')).upper()

    # 특수 종목 처리 (auto_classify 패턴)
    if any(kw in item_nm for kw in ['콜론', '예금', '증거금', 'MMF', '미수', '미지급',
                                      '청약금', '원천세', '분배금', '기타자산', 'DEPOSIT',
                                      'CMA', '수시입출금']):
        return '유동성'
    if 'REPO' in item_nm:
        return '유동성'
    if any(kw in item_nm for kw in ['모펀드', '모투자']):
        return '모펀드'
    # FX: 달러선물, 통화선물, NDF 등
    if any(kw in item_nm for kw in ['달러선물', '달러 선물', 'USD선물', 'NDF', '통화선물', 'FX FORWARD']):
        return 'FX'

    is_kr = item_cd.startswith('KR') or (len(item_cd) == 6 and item_cd.isdigit())
    # AST_CLSF_CD_NM에 '해외' 포함 여부로 해외 자산 판별 (KR ISIN인 해외투자 ETF 처리)
    is_overseas_by_ast = '해외' in ast or '미국' in item_nm or 'US' in item_nm or '글로벌' in item_nm

    if '주식' in ast or 'EQUITY' in ast or '지분증권' in ast or '지수' in ast:
        if is_overseas_by_ast or (not is_kr):
            return '해외주식'
        return '국내주식'
    if '채권' in ast or 'BOND' in ast or '채무증권' in ast:
        if is_overseas_by_ast or (not is_kr):
            return '해외채권'
        return '국내채권'
    if any(kw in ast for kw in ['대체', '부동산', '인프라', '리츠', 'REIT', '실물']):
        return '대체투자'
    if any(kw in item_nm for kw in ['GOLD', '금현물', 'KRX금', '인프라', 'REIT', '리츠']):
        return '대체투자'
    if '현금' in ast or 'CASH' in ast:
        return '유동성'

    # fallback: 통화 기준
    if curr in ('USD', 'EUR', 'JPY', 'GBP') or (not is_kr and not is_overseas_by_ast):
        return '해외주식'
    return '유동성'


def load_fund_holdings_classified(fund_code: str, date: str = None) -> pd.DataFrame:
    """
    보유종목 로드 + 6분류 매핑.
    미수/미지급 필터 적용.

    Returns: DataFrame with '자산군' 컬럼 추가
    """
    df = load_fund_holdings(fund_code, date)
    if df.empty:
        return df

    # 미수/미지급 필터
    mask = ~(df['ITEM_NM'].str.contains('미지급|미수', na=False, case=False))
    df = df[mask].copy()

    # 6분류 매핑
    df['자산군'] = df.apply(_classify_6class, axis=1)

    # 콜론 종목 → "콜론"으로 통합 표기
    _col_mask = df['ITEM_NM'].str.contains('콜론', na=False, case=False)
    df.loc[_col_mask, 'ITEM_NM'] = '콜론'

    # 콜론 그룹핑 (여러 콜론 종목 → 합산)
    _col_rows = df[_col_mask]
    if len(_col_rows) > 1:
        _col_sum = _col_rows.iloc[0:1].copy()
        _col_sum['EVL_AMT'] = _col_rows['EVL_AMT'].sum()
        _col_sum['QTY'] = _col_rows['QTY'].sum() if 'QTY' in _col_rows.columns else 0
        df = pd.concat([df[~_col_mask], _col_sum], ignore_index=True)

    # 비중 계산 (EVL_AMT 기반, NAST_TAMT_AGNST_WGH가 없는 경우 대비)
    total_evl = df['EVL_AMT'].sum()
    if total_evl > 0:
        df['비중(%)'] = (df['EVL_AMT'] / total_evl * 100).round(2)
    else:
        df['비중(%)'] = 0.0
    df['평가금액(억)'] = (df['EVL_AMT'] / 1e8).round(1)

    return df


# ============================================================
# Look-through: 모펀드 → 하위 종목 전개
# ============================================================

def _extract_fund_code_from_item_cd(item_cd: str) -> str:
    """
    모펀드 ITEM_CD에서 펀드코드 추출.
    DWPM10530의 모펀드 ITEM_CD 형식: '03228000{FUND_CD}' (예: 032280007J48 → 07J48)
    """
    s = str(item_cd).strip()
    if len(s) > 5 and s.startswith('0322800'):
        return s[-5:]
    # fallback: 뒤 5자리
    if len(s) >= 5:
        return s[-5:]
    return s


def load_fund_holdings_lookthrough(fund_code: str, date: str = None) -> pd.DataFrame:
    """
    보유종목 로드 + 모펀드 look-through.
    모펀드 ITEM_CD에서 하위 펀드코드 추출 후 보유종목을 비중 가중하여 전개.

    Returns: DataFrame with 모펀드 rows replaced by underlying holdings
    """
    df = load_fund_holdings_classified(fund_code, date)
    if df.empty:
        return df

    # 모펀드 행 식별
    mother_mask = df['자산군'] == '모펀드'
    if not mother_mask.any():
        return df

    non_mother = df[~mother_mask].copy()
    expanded_rows = []

    for _, row in df[mother_mask].iterrows():
        raw_item_cd = str(row['ITEM_CD']).strip()
        child_fund_cd = _extract_fund_code_from_item_cd(raw_item_cd)
        mother_evl = float(row['EVL_AMT'])

        # 하위 펀드 보유종목 로드 시도
        try:
            child_df = load_fund_holdings_classified(child_fund_cd, date)
            if not child_df.empty:
                child_df = child_df.copy()
                # 하위에도 모펀드가 있을 수 있음 — 여기서는 1단계만 전개
                child_total_evl = child_df['EVL_AMT'].sum()
                if child_total_evl > 0:
                    scale = mother_evl / child_total_evl
                    child_df['EVL_AMT'] = child_df['EVL_AMT'] * scale
                    child_df['평가금액(억)'] = (child_df['EVL_AMT'] / 1e8).round(1)
                expanded_rows.append(child_df)
                continue
        except Exception:
            pass

        # look-through 실패 → 모펀드 행 그대로 유지
        expanded_rows.append(pd.DataFrame([row]))

    if expanded_rows:
        result = pd.concat([non_mother] + expanded_rows, ignore_index=True)
    else:
        result = non_mother

    # 동일 종목 합산 (여러 모펀드에서 동일 종목이 올 수 있음)
    keep_cols = [c for c in ['ITEM_NM', 'AST_CLSF_CD_NM', 'FUND_CD', 'FUND_NM', 'CURR_DS_CD']
                 if c in result.columns]

    if 'ITEM_CD' in result.columns and len(result) > 0:
        agg_dict = {c: 'first' for c in keep_cols}
        agg_dict['EVL_AMT'] = 'sum'
        if 'QTY' in result.columns:
            agg_dict['QTY'] = 'sum'
        grp = result.groupby(['ITEM_CD', '자산군'], as_index=False).agg(agg_dict)
    else:
        grp = result

    # 비중 재계산
    total_evl = grp['EVL_AMT'].sum()
    if total_evl > 0:
        grp['비중(%)'] = (grp['EVL_AMT'] / total_evl * 100).round(2)
    else:
        grp['비중(%)'] = 0.0
    grp['평가금액(억)'] = (grp['EVL_AMT'] / 1e8).round(1)

    return grp


# ============================================================
# NAV + AUM 시계열 (확장)
# ============================================================

def load_fund_nav_with_aum(fund_code: str, start_date: str = None) -> pd.DataFrame:
    """
    펀드 NAV(MOD_STPR) + AUM(NAST_AMT) 시계열.
    load_fund_nav의 단일 펀드 확장 버전.

    Returns: DataFrame(기준일자, MOD_STPR, NAST_AMT, AUM_억, DD1_ERN_RT)
    """
    df = load_fund_nav([fund_code], start_date)
    if df.empty:
        return df
    df['AUM_억'] = df['NAST_AMT'] / 1e8
    return df[['기준일자', 'MOD_STPR', 'NAST_AMT', 'AUM_억', 'DD1_ERN_RT']].sort_values('기준일자').reset_index(drop=True)


# ============================================================
# 복합 BM (Composite Benchmark)
# 여러 지수의 가중합으로 구성된 벤치마크
# ============================================================

def load_composite_bm_prices(components: list, start_date: str = None) -> pd.DataFrame:
    """
    복합 BM 시계열 생성.
    각 component의 SCIP 시계열 → 일별 수익률 → 가중합 → 복합지수 복원.

    components: [{'dataset_id', 'dataseries_id', 'weight', 'name', 'currency'}, ...]
    Returns: DataFrame(기준일자, value) — load_scip_bm_prices와 동일 포맷
    """
    if not components:
        return pd.DataFrame(columns=['기준일자', 'value'])

    # 각 component 시계열 로드
    comp_series = {}
    for comp in components:
        df = load_scip_bm_prices(
            comp['dataset_id'], comp['dataseries_id'],
            start_date, comp.get('currency')
        )
        if df.empty or len(df) < 2:
            logger.warning(f"복합BM component 데이터 부족: {comp.get('name', comp['dataset_id'])}")
            continue
        df = df.set_index('기준일자').sort_index()
        # 동일 날짜 중복 제거 (마지막 값 유지)
        df = df[~df.index.duplicated(keep='last')]
        comp_series[comp['name']] = {'returns': df['value'].pct_change(), 'weight': comp['weight']}

    if not comp_series:
        return pd.DataFrame(columns=['기준일자', 'value'])

    # 공통 날짜 기준 정렬
    all_dates = None
    for cs in comp_series.values():
        idx = cs['returns'].dropna().index
        all_dates = idx if all_dates is None else all_dates.intersection(idx)

    if all_dates is None or len(all_dates) < 2:
        return pd.DataFrame(columns=['기준일자', 'value'])

    all_dates = all_dates.sort_values()

    # 가중 수익률 합산
    composite_ret = pd.Series(0.0, index=all_dates)
    for cs in comp_series.values():
        composite_ret += cs['returns'].reindex(all_dates).fillna(0) * cs['weight']

    # 복합지수 복원 (base=1000)
    composite_idx = (1 + composite_ret).cumprod() * 1000

    result = pd.DataFrame({
        '기준일자': composite_idx.index,
        'value': composite_idx.values
    }).reset_index(drop=True)
    return result


# ============================================================
# MP (Model Portfolio) from DB
# solution.sol_MP_released_inform + universe_non_derivative
# ============================================================

def load_mp_weights_from_db(fund_desc: str, reference_date: str = None,
                            cycle_phase: int = None) -> pd.DataFrame:
    """
    sol_MP_released_inform에서 MP 비중 로드.
    reference_date 이하의 최신 Release_date 기준.

    fund_desc: 펀드설명 (예: 'MS GROWTH', 'TIF', 'Golden Growth')
    reference_date: 기준일 'YYYY-MM-DD' (None → 최신)
    cycle_phase: 경기국면 (Golden Growth용, 기본=1)

    Returns: DataFrame(ISIN, weight, Release_date) 또는 빈 DataFrame
    """
    conn = get_pandas_connection('solution')
    try:
        # 최신 Release_date 결정
        if reference_date:
            date_sql = """
                SELECT MAX(Release_date) as rd
                FROM sol_MP_released_inform
                WHERE `펀드설명` = %s AND Release_date <= %s
            """
            date_params = [fund_desc, reference_date]
        else:
            date_sql = """
                SELECT MAX(Release_date) as rd
                FROM sol_MP_released_inform
                WHERE `펀드설명` = %s
            """
            date_params = [fund_desc]

        rd_df = pd.read_sql(date_sql, conn, params=date_params)
        if rd_df.empty or pd.isna(rd_df['rd'].iloc[0]):
            return pd.DataFrame(columns=['ISIN', 'weight', 'Release_date'])
        release_date = rd_df['rd'].iloc[0]

        # MP 비중 로드
        conditions = ["`펀드설명` = %s", "Release_date = %s"]
        params = [fund_desc, release_date]

        if cycle_phase is not None:
            conditions.append("`경기국면` = %s")
            params.append(cycle_phase)

        where = " AND ".join(conditions)
        sql = f"""
            SELECT DISTINCT ISIN, weight, Release_date
            FROM sol_MP_released_inform
            WHERE {where}
            ORDER BY weight DESC
        """
        df = pd.read_sql(sql, conn, params=params)
        return df
    except Exception as e:
        logger.error(f"MP 로드 실패 ({fund_desc}): {e}")
        return pd.DataFrame(columns=['ISIN', 'weight', 'Release_date'])
    finally:
        conn.close()


# 8분류 매핑 (universe_non_derivative.방법3 → 8분류)
# DB의 classification_method 컬럼값은 '방법3' (NOT '분류3')
_UNIV_TO_8CLASS = {
    '국내주식': '국내주식',
    '해외주식': '해외주식',
    '국내채권': '국내채권',
    '해외채권': '해외채권',
    '대체': '대체투자',
    'FX': 'FX',
    '유동성및기타': '유동성',
}


def load_mp_weights_8class(fund_desc: str, reference_date: str = None,
                           cycle_phase: int = 1) -> dict:
    """
    MP 비중을 8자산군으로 집계.
    1) sol_MP_released_inform → ISIN별 weight
    2) universe_non_derivative (분류3) → ISIN → 자산군
    3) 8자산군 집계

    fund_desc: 펀드설명 (예: 'MS GROWTH')
    Returns: dict {'국내주식': 5.0, '해외주식': 30.0, ...} (% 단위) 또는 None
    """
    mp_df = load_mp_weights_from_db(fund_desc, reference_date, cycle_phase)
    if mp_df.empty:
        # 경기국면 없는 펀드는 cycle_phase=None로 재시도
        if cycle_phase is not None:
            mp_df = load_mp_weights_from_db(fund_desc, reference_date, None)
        if mp_df.empty:
            return None

    # universe_non_derivative에서 ISIN → 분류3 매핑 로드
    conn = get_pandas_connection('solution')
    try:
        isin_list = mp_df['ISIN'].tolist()
        placeholders = ','.join(['%s'] * len(isin_list))
        sql = f"""
            SELECT ISIN, classification
            FROM universe_non_derivative
            WHERE classification_method = '방법3'
              AND ISIN IN ({placeholders})
              AND classification IS NOT NULL
        """
        cls_df = pd.read_sql(sql, conn, params=isin_list)
    finally:
        conn.close()

    # ISIN → 8분류 매핑
    isin_to_class = {}
    for _, row in cls_df.iterrows():
        cls_val = str(row['classification']).strip()
        mapped = _UNIV_TO_8CLASS.get(cls_val)
        if mapped:
            isin_to_class[row['ISIN']] = mapped

    # 8분류별 비중 집계
    from config.funds import ASSET_6CLASS
    asset_classes_8 = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', 'FX', '모펀드', '유동성']
    result = {ac: 0.0 for ac in asset_classes_8}

    for _, row in mp_df.iterrows():
        isin = row['ISIN']
        weight_pct = float(row['weight']) * 100  # 소수 → %
        ac = isin_to_class.get(isin, '해외주식')  # fallback: 해외주식 (대부분 해외 ETF)
        if ac in result:
            result[ac] += weight_pct

    # 반올림
    result = {k: round(v, 2) for k, v in result.items()}
    return result


# ============================================================
# VP (Virtual Portfolio) from DB
# sol_DWPM10530 (보유종목), sol_DWPM10510 (기준가), sol_VP_rebalancing_inform (이벤트)
# ============================================================

# fund_desc → VP 펀드코드 매핑
# sol_DWPM10510/10530의 VP 전용 펀드코드
_FUND_DESC_TO_VP_CODE = {
    'MS GROWTH': '3MP01',
    'MS STABLE': '3MP02',
    'TDF2050': '1MP50',
    'TDF2045': '1MP45',
    'TDF2040': '1MP40',
    'TDF2035': '1MP35',
    'TDF2030': '1MP30',
    'TDF2055': '1MP55',
    'TDF2060': '1MP60',
    'TIF': '2MP24',
    'Golden Growth': '6MP07',
}


def load_vp_rebal_date(fund_desc: str) -> str:
    """
    sol_VP_rebalancing_inform에서 최근 VP 리밸런싱 날짜 조회.
    Returns: 날짜 문자열 또는 None
    """
    conn = get_pandas_connection('solution')
    try:
        sql = """
            SELECT MAX(`리밸런싱날짜`) as rd
            FROM sol_VP_rebalancing_inform
            WHERE `펀드설명` = %s AND port = 'VP'
        """
        df = pd.read_sql(sql, conn, params=[fund_desc])
        if not df.empty and pd.notna(df['rd'].iloc[0]):
            return str(df['rd'].iloc[0])
        return None
    except Exception:
        return None
    finally:
        conn.close()


def load_vp_holdings_8class(vp_fund_code: str, date: str = None) -> dict:
    """
    VP 보유종목(sol_DWPM10530)에서 NAST_TAMT_AGNST_WGH 기반 8분류 비중 집계.

    vp_fund_code: VP 전용 펀드코드 (예: '3MP01')
    date: 기준일 YYYYMMDD (None → 최근일)

    Returns: dict {'국내주식': 5.0, '해외주식': 30.0, ...} (% 단위) 또는 None
    """
    conn = get_pandas_connection('solution')
    try:
        # 최근일 결정
        if date is None:
            conn_dict = get_connection('solution')
            try:
                with conn_dict.cursor() as cur:
                    cur.execute(
                        "SELECT MAX(STD_DT) as max_dt FROM sol_DWPM10530 WHERE FUND_CD = %s",
                        (vp_fund_code,)
                    )
                    row = cur.fetchone()
                    if not row or row['max_dt'] is None:
                        return None
                    date = row['max_dt']
            finally:
                conn_dict.close()

        sql = """
            SELECT ITEM_CD, ITEM_NM, NAST_TAMT_AGNST_WGH
            FROM sol_DWPM10530
            WHERE FUND_CD = %s AND STD_DT = %s
            ORDER BY NAST_TAMT_AGNST_WGH DESC
        """
        df = pd.read_sql(sql, conn, params=[vp_fund_code, date])
        if df.empty:
            return None

        # ISIN → universe_non_derivative 방법3 매핑
        isin_list = df['ITEM_CD'].tolist()
        placeholders = ','.join(['%s'] * len(isin_list))
        cls_sql = f"""
            SELECT ISIN, classification
            FROM universe_non_derivative
            WHERE classification_method = '방법3'
              AND ISIN IN ({placeholders})
              AND classification IS NOT NULL
        """
        cls_df = pd.read_sql(cls_sql, conn, params=isin_list)

        isin_to_class = {}
        for _, row in cls_df.iterrows():
            cls_val = str(row['classification']).strip()
            mapped = _UNIV_TO_8CLASS.get(cls_val)
            if mapped:
                isin_to_class[row['ISIN']] = mapped

        # 8분류별 비중 집계
        asset_classes_8 = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', 'FX', '모펀드', '유동성']
        result = {ac: 0.0 for ac in asset_classes_8}

        for _, r in df.iterrows():
            isin = r['ITEM_CD']
            wgt = float(r['NAST_TAMT_AGNST_WGH']) if pd.notna(r['NAST_TAMT_AGNST_WGH']) else 0.0
            ac = isin_to_class.get(isin, '해외주식')  # fallback: 해외주식
            if ac in result:
                result[ac] += wgt

        result = {k: round(v, 2) for k, v in result.items()}
        return result
    except Exception as e:
        logger.error(f"VP holdings 8class 실패 ({vp_fund_code}): {e}")
        return None
    finally:
        conn.close()


def load_vp_weights_8class(fund_desc: str, reference_date: str = None,
                           cycle_phase: int = 1) -> dict:
    """
    VP 비중을 8자산군으로 집계.
    fund_desc → VP 펀드코드 → sol_DWPM10530 보유종목 → 8분류 집계.

    fund_desc: 펀드설명 (예: 'MS GROWTH')
    Returns: dict {'국내주식': 5.0, '해외주식': 30.0, ...} (% 단위) 또는 None
    """
    vp_code = _FUND_DESC_TO_VP_CODE.get(fund_desc)
    if not vp_code:
        return None
    return load_vp_holdings_8class(vp_code)


def load_vp_nav(fund_desc_or_code: str, start_date: str = None) -> pd.DataFrame:
    """
    VP 기준가 시계열 로드.
    테이블: solution.sol_DWPM10510

    fund_desc_or_code: fund_desc (예: 'MS GROWTH') 또는 VP 코드 (예: '3MP01')
    Returns: DataFrame(기준일자, MOD_STPR) 또는 빈 DataFrame
    """
    # fund_desc → VP 코드 변환
    vp_code = _FUND_DESC_TO_VP_CODE.get(fund_desc_or_code, fund_desc_or_code)

    conn = get_pandas_connection('solution')
    try:
        params = [vp_code]
        where_date = ""
        if start_date:
            where_date = " AND STD_DT >= %s"
            params.append(start_date)
        sql = f"""
            SELECT STD_DT, MOD_STPR
            FROM sol_DWPM10510
            WHERE FUND_CD = %s {where_date}
            ORDER BY STD_DT
        """
        df = pd.read_sql(sql, conn, params=params)
        if df.empty:
            return pd.DataFrame(columns=['기준일자', 'MOD_STPR'])
        df['기준일자'] = pd.to_datetime(df['STD_DT'], format='%Y%m%d')
        return df[['기준일자', 'MOD_STPR']].reset_index(drop=True)
    except Exception as e:
        logger.error(f"VP NAV 로드 실패 ({vp_code}): {e}")
        return pd.DataFrame(columns=['기준일자', 'MOD_STPR'])
    finally:
        conn.close()


# ============================================================
# Brinson PA 계산
# ============================================================

def _map_bm_component_to_asset_class(comp_name: str) -> str:
    """BM 컴포넌트명 → 자산군 매핑."""
    nm = comp_name.upper()
    if 'KOSPI' in nm:
        return '국내주식'
    if 'KIS' in nm and 'CALL' in nm:
        return '유동성'
    if 'KIS' in nm:
        return '국내채권'
    if 'BLOOMBERG' in nm or 'AGG' in nm:
        return '해외채권'
    if any(k in nm for k in ['MSCI', 'S&P', 'ACWI']):
        return '해외주식'
    return '해외주식'


def _load_bm_daily_returns_by_class(bm_info: dict, start_date: str, end_date: str,
                                     asset_classes_8: list) -> tuple:
    """
    BM 컴포넌트 일별 수익률 → 자산군별 집계.

    Returns: (bm_weights_static, bm_daily_df)
        bm_weights_static: {자산군: 비중(%)}
        bm_daily_df: DataFrame(기준일자, 자산군별 일별 수익률 컬럼들)
    """
    bm_weights = {ac: 0.0 for ac in asset_classes_8}
    components = bm_info.get('components', [])
    if not components:
        return bm_weights, pd.DataFrame()

    # 컴포넌트 → 자산군 매핑 및 비중 합산
    comp_class_map = {}
    for comp in components:
        ac = _map_bm_component_to_asset_class(comp['name'])
        bm_weights[ac] += comp['weight'] * 100
        comp_class_map[comp['name']] = ac

    # 각 컴포넌트의 SCIP 일별 수익률 로드
    comp_returns = {}
    for comp in components:
        df = load_scip_bm_prices(comp['dataset_id'], comp['dataseries_id'],
                                  start_date, comp.get('currency'))
        if df.empty or len(df) < 2:
            continue
        df = df.set_index('기준일자').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        comp_returns[comp['name']] = {
            'daily_ret': df['value'].pct_change(),
            'weight': comp['weight'],
            'class': comp_class_map[comp['name']]
        }

    if not comp_returns:
        return bm_weights, pd.DataFrame()

    # 공통 날짜
    all_dates = None
    for cr in comp_returns.values():
        idx = cr['daily_ret'].dropna().index
        all_dates = idx if all_dates is None else all_dates.intersection(idx)
    if all_dates is None or len(all_dates) < 2:
        return bm_weights, pd.DataFrame()
    all_dates = all_dates.sort_values()

    # 자산군별 일별 수익률 (가중평균)
    bm_daily = pd.DataFrame(index=all_dates)
    for ac in asset_classes_8:
        bm_daily[ac] = 0.0

    for cr in comp_returns.values():
        ac = cr['class']
        w = cr['weight']
        total_w = bm_weights[ac] / 100 if bm_weights[ac] > 0 else 1
        # 자산군 내 비중 비례
        bm_daily[ac] += cr['daily_ret'].reindex(all_dates).fillna(0) * (w / total_w)

    # 날짜 필터
    sd = pd.Timestamp(start_date) if len(start_date) == 8 else pd.Timestamp(start_date)
    ed = pd.Timestamp(end_date) if len(end_date) == 8 else pd.Timestamp(end_date)
    if len(start_date) == 8:
        sd = pd.Timestamp(f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}")
    if len(end_date) == 8:
        ed = pd.Timestamp(f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}")
    bm_daily = bm_daily[(bm_daily.index >= sd) & (bm_daily.index <= ed)]

    bm_daily = bm_daily.reset_index().rename(columns={'index': '기준일자'})
    return bm_weights, bm_daily


def compute_brinson_attribution(fund_code: str, bm_code: str,
                                start_date: str, end_date: str,
                                asset_classes_8: list = None) -> dict:
    """
    Brinson 3-Factor Attribution 계산 (Phase 4: 일별 정밀 로직).

    R 동일 로직:
    - 일별 x 종목별 기여수익률
    - T-1 비중 기준
    - pl_gb='환산'으로 FX 분리
    - 경로의존적 누적기여도
    - 유동성잔차 = 포트수익률 - sum(종목기여도)

    Returns: dict with keys:
      'pa_df': DataFrame (자산군, AP비중, BM비중, AP수익률, BM수익률, Allocation, Selection, Cross, 기여수익률)
      'total_alloc', 'total_select', 'total_cross', 'total_excess'
      'period_ap_return', 'period_bm_return'
      'sec_contrib': DataFrame (종목별 기여도, top 20)
      'daily_brinson': DataFrame (일별 누적 Brinson)
      'fx_contrib': float (FX 기여수익률 %)
      'residual': float (유동성/기타 잔차 %)
    """
    if asset_classes_8 is None:
        asset_classes_8 = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', 'FX', '모펀드', '유동성']

    # ── 1) PA 원천 데이터 로드 (확장 컬럼) ──
    pa_df = load_pa_source(fund_code, start_date, end_date)
    if pa_df.empty:
        logger.warning(f"[Brinson] MA000410에 {fund_code} 기간 {start_date}~{end_date} 데이터 없음")
        return None

    # ── 2) 보유종목 → 자산군 매핑 ──
    holdings = load_fund_holdings_classified(fund_code)
    if holdings is None or holdings.empty:
        logger.warning(f"[Brinson] {fund_code} 보유종목 로드 실패")
        return None

    item_to_class = dict(zip(holdings['ITEM_CD'], holdings['자산군']))
    item_to_name = dict(zip(holdings['ITEM_CD'], holdings['ITEM_NM']))
    pa_df['자산군'] = pa_df['sec_id'].map(item_to_class).fillna('유동성')

    # ── 3) 일별 순자산 로드 (T-1 비중 기준, start_date 이전 1일 포함) ──
    # T-1 기준가가 필요하므로 start_date보다 30일 이전부터 로드
    _nast_start = str(max(int(start_date) - 100, 20200101))  # 여유분
    nast_df = _load_daily_nast(fund_code, _nast_start, end_date)

    # pr_date를 int로 통일 (DB에서 str/int 혼재 가능)
    pa_df['pr_date'] = pa_df['pr_date'].astype(int)
    dates = sorted(pa_df['pr_date'].unique())
    if len(dates) < 2:
        logger.warning(f"[Brinson] {fund_code} 기간 내 데이터 2일 미만")
        return None

    # ── 4) 일별 종목별 기여수익률 계산 ──
    # modify_unav_chg는 기준가 변동 기여분 (검증: sum = MOD_STPR 변동)
    # 기여수익률(%) = modify_unav_chg / MOD_STPR(T-1) * 100

    # 일별 기준가 dict + 정렬된 날짜 리스트 (T-1 탐색용)
    nav_dict = {}
    nav_dates_sorted = []
    if not nast_df.empty:
        nast_df['_dt_int'] = nast_df['STD_DT'].astype(int)
        for _, r in nast_df.iterrows():
            nav_dict[r['_dt_int']] = {'mod_stpr': r['MOD_STPR'], 'nast_amt': r['NAST_AMT']}
        nav_dates_sorted = sorted(nav_dict.keys())

    # FX 분리: pl_gb='환산' 행의 modify_unav_chg
    fx_total = 0.0
    ex_fx_total = 0.0

    daily_records = []  # 일별 자산군별 집계

    # 종목별 기여도 누적 (전 기간)
    sec_contrib_acc = {}  # sec_id → {modify_sum, val_last, fx_sum}

    for i, dt in enumerate(dates):
        day_data = pa_df[pa_df['pr_date'] == dt]
        # T-1 기준가: NAST 테이블에서 dt보다 작은 최근 날짜
        prev_nast_dates = [d for d in nav_dates_sorted if d < dt]
        prev_nast_dt = prev_nast_dates[-1] if prev_nast_dates else None
        mod_stpr_prev = nav_dict.get(prev_nast_dt, {}).get('mod_stpr', None) if prev_nast_dt else None

        if mod_stpr_prev is None or mod_stpr_prev == 0:
            # 첫 날이거나 T-1 기준가 없음 → 비중 계산 불가, skip
            # 하지만 종목 val 축적은 계속
            for _, row in day_data.iterrows():
                sid = row['sec_id']
                if sid not in sec_contrib_acc:
                    sec_contrib_acc[sid] = {'modify_sum': 0, 'val_last': 0, 'fx_sum': 0, '자산군': row['자산군']}
                sec_contrib_acc[sid]['val_last'] = row['val'] if pd.notna(row['val']) else 0
            continue

        # 일별 포트 수익률 = sum(modify_unav_chg) / MOD_STPR(T-1)
        day_total_modify = day_data['modify_unav_chg'].sum()
        daily_port_ret = day_total_modify / mod_stpr_prev

        # FX 분리
        day_fx = day_data[day_data['pl_gb'] == '환산']['modify_unav_chg'].sum()
        day_ex_fx = day_total_modify - day_fx
        fx_total += day_fx
        ex_fx_total += day_ex_fx

        # 종목별 T-1 평가액 → 비중
        # MA000410의 val은 시가평가액. T-1 val로 비중 계산
        # 동일 sec_id의 pl_gb별로 여러 행 존재 → sec_id 그룹핑
        sec_day = day_data.groupby(['sec_id', '자산군']).agg(
            modify_sum=('modify_unav_chg', 'sum'),
            fx_modify=('modify_unav_chg', lambda x: x[day_data.loc[x.index, 'pl_gb'] == '환산'].sum()),
            val_last=('val', 'last'),
        ).reset_index()

        # 자산군별 집계
        class_day = {ac: {'modify': 0.0, 'fx_modify': 0.0, 'val_t1': 0.0} for ac in asset_classes_8}

        for _, sr in sec_day.iterrows():
            sid = sr['sec_id']
            ac = sr['자산군']

            # T-1 val 사용 (이전 누적 정보)
            val_t1 = sec_contrib_acc.get(sid, {}).get('val_last', 0)
            class_day[ac]['val_t1'] += val_t1
            class_day[ac]['modify'] += sr['modify_sum']
            class_day[ac]['fx_modify'] += sr['fx_modify']

            # 누적 업데이트
            if sid not in sec_contrib_acc:
                sec_contrib_acc[sid] = {'modify_sum': 0, 'val_last': 0, 'fx_sum': 0, '자산군': ac}
            sec_contrib_acc[sid]['modify_sum'] += sr['modify_sum']
            sec_contrib_acc[sid]['fx_sum'] += sr['fx_modify']
            sec_contrib_acc[sid]['val_last'] = sr['val_last'] if pd.notna(sr['val_last']) else sec_contrib_acc[sid]['val_last']

        # 자산군별 일별 비중 (T-1 val 기준) 및 수익률
        total_val_t1 = sum(c['val_t1'] for c in class_day.values())
        if total_val_t1 == 0:
            total_val_t1 = 1

        rec = {'pr_date': dt, 'port_ret': daily_port_ret}
        for ac in asset_classes_8:
            w = class_day[ac]['val_t1'] / total_val_t1  # 비중 (0~1)
            m = class_day[ac]['modify']
            v = class_day[ac]['val_t1']
            r = m / v if v > 0 else 0  # 자산군 수익률
            contrib = m / mod_stpr_prev  # 기여수익률 (기준가 대비)
            rec[f'{ac}_w'] = w
            rec[f'{ac}_r'] = r
            rec[f'{ac}_contrib'] = contrib
        daily_records.append(rec)

    if not daily_records:
        logger.warning(f"[Brinson] {fund_code} 일별 레코드 생성 실패")
        return None

    daily_df = pd.DataFrame(daily_records)
    daily_df['기준일자'] = pd.to_datetime(daily_df['pr_date'].astype(str), format='%Y%m%d')

    # ── 5) BM 일별 수익률 로드 ──
    from config.funds import FUND_BM
    bm_info = FUND_BM.get(fund_code)

    bm_weights = {ac: 0.0 for ac in asset_classes_8}
    bm_daily_df = pd.DataFrame()

    if bm_info:
        bm_weights, bm_daily_df = _load_bm_daily_returns_by_class(
            bm_info, start_date, end_date, asset_classes_8)

    # ── 6) 일별 Brinson 3-Factor 계산 ──
    # 공통 날짜 매칭
    if not bm_daily_df.empty:
        bm_daily_df = bm_daily_df.set_index('기준일자')
        daily_df = daily_df.set_index('기준일자')
        common_dates = daily_df.index.intersection(bm_daily_df.index).sort_values()

        if len(common_dates) < 2:
            # BM 데이터 매칭 실패 → AP 데이터만으로 진행
            common_dates = daily_df.index.sort_values()
            daily_df = daily_df.loc[common_dates]
            bm_available = False
        else:
            daily_df = daily_df.loc[common_dates]
            bm_daily_df = bm_daily_df.loc[common_dates]
            bm_available = True
    else:
        daily_df = daily_df.set_index('기준일자')
        common_dates = daily_df.index.sort_values()
        daily_df = daily_df.loc[common_dates]
        bm_available = False

    # 일별 Brinson 효과 (비중은 %, 수익률은 소수)
    brinson_daily = []
    for ac in asset_classes_8:
        ap_w_col = f'{ac}_w'
        ap_r_col = f'{ac}_r'

        for dt in common_dates:
            ap_w = daily_df.loc[dt, ap_w_col] if ap_w_col in daily_df.columns else 0
            ap_r = daily_df.loc[dt, ap_r_col] if ap_r_col in daily_df.columns else 0
            bm_w = bm_weights.get(ac, 0) / 100  # % → 소수
            bm_r = bm_daily_df.loc[dt, ac] if (bm_available and ac in bm_daily_df.columns) else 0

            brinson_daily.append({
                '기준일자': dt, '자산군': ac,
                'ap_w': ap_w, 'bm_w': bm_w, 'ap_r': ap_r, 'bm_r': bm_r,
                'alloc': (ap_w - bm_w) * bm_r,
                'select': bm_w * (ap_r - bm_r),
                'cross': (ap_w - bm_w) * (ap_r - bm_r),
            })

    brinson_df = pd.DataFrame(brinson_daily)

    # ── 7) 기간 집계 ──
    # 누적 수익률 (경로의존적)
    daily_df['cum_port_ret'] = (1 + daily_df['port_ret']).cumprod() - 1
    period_ap_return = daily_df['cum_port_ret'].iloc[-1] * 100 if len(daily_df) > 0 else 0

    # BM 누적 수익률
    if bm_available:
        bm_composite_ret = pd.Series(0.0, index=common_dates)
        for ac in asset_classes_8:
            w = bm_weights.get(ac, 0) / 100
            if ac in bm_daily_df.columns:
                bm_composite_ret += bm_daily_df[ac] * w
        period_bm_return = ((1 + bm_composite_ret).cumprod().iloc[-1] - 1) * 100
    else:
        period_bm_return = 0

    # 자산군별 기간 집계 (AP 비중: 평균, AP 수익률: 누적)
    ap_period_weights = {}
    ap_period_returns = {}
    for ac in asset_classes_8:
        w_col = f'{ac}_w'
        contrib_col = f'{ac}_contrib'
        if w_col in daily_df.columns:
            ap_period_weights[ac] = daily_df[w_col].mean() * 100  # 기간 평균 비중
        else:
            ap_period_weights[ac] = 0
        if contrib_col in daily_df.columns:
            # 누적 기여수익률 = sum(일별 기여) (기준가 대비이므로 합산 가능)
            cum_contrib = daily_df[contrib_col].sum() * 100
            avg_w = ap_period_weights[ac]
            ap_period_returns[ac] = (cum_contrib / avg_w * 100) if avg_w > 0 else 0
        else:
            ap_period_returns[ac] = 0

    # BM 자산군별 기간 수익률
    bm_period_returns = {}
    for ac in asset_classes_8:
        if bm_available and ac in bm_daily_df.columns:
            bm_period_returns[ac] = ((1 + bm_daily_df[ac]).cumprod().iloc[-1] - 1) * 100
        else:
            bm_period_returns[ac] = 0

    # Brinson 기간 합계 (일별 합산)
    if not brinson_df.empty:
        period_brinson = brinson_df.groupby('자산군').agg(
            alloc=('alloc', 'sum'), select=('select', 'sum'), cross=('cross', 'sum')
        ).reindex(asset_classes_8).fillna(0)
    else:
        period_brinson = pd.DataFrame(0, index=asset_classes_8, columns=['alloc', 'select', 'cross'])

    # 결과 테이블 조립
    results = []
    for ac in asset_classes_8:
        ap_w = ap_period_weights.get(ac, 0)
        bm_w = bm_weights.get(ac, 0)
        ap_r = ap_period_returns.get(ac, 0)
        bm_r = bm_period_returns.get(ac, 0)
        alloc = period_brinson.loc[ac, 'alloc'] * 100 if ac in period_brinson.index else 0
        sel = period_brinson.loc[ac, 'select'] * 100 if ac in period_brinson.index else 0
        crs = period_brinson.loc[ac, 'cross'] * 100 if ac in period_brinson.index else 0
        # 기여수익률: 자산군 내 modify_unav_chg 합계 / 기준가(첫날) 기반
        contrib_col = f'{ac}_contrib'
        cum_contrib = daily_df[contrib_col].sum() * 100 if contrib_col in daily_df.columns else 0
        results.append({
            '자산군': ac, 'AP비중': round(ap_w, 2), 'BM비중': round(bm_w, 2),
            'AP수익률': round(ap_r, 2), 'BM수익률': round(bm_r, 2),
            'Allocation': round(alloc, 4), 'Selection': round(sel, 4),
            'Cross': round(crs, 4), '기여수익률': round(cum_contrib, 4)
        })

    result_df = pd.DataFrame(results)
    total_alloc = result_df['Allocation'].sum()
    total_select = result_df['Selection'].sum()
    total_cross = result_df['Cross'].sum()

    # ── 8) 유동성/기타 잔차 ──
    total_excess = period_ap_return - period_bm_return
    brinson_sum = total_alloc + total_select + total_cross
    residual = total_excess - brinson_sum

    # ── 9) FX 기여수익률 ──
    # 기간 시작 기준가 (T-1 of first date)
    first_date_prev = [d for d in nav_dates_sorted if d < dates[0]]
    first_nav_dt = first_date_prev[-1] if first_date_prev else dates[0]
    first_nav = nav_dict.get(first_nav_dt, {}).get('mod_stpr', None)
    if first_nav is None or first_nav == 0:
        first_nav = nav_dict.get(dates[0], {}).get('mod_stpr', 1)
    fx_contrib_pct = (fx_total / first_nav * 100) if first_nav > 0 else 0

    # ── 10) 종목별 기여도 (전 기간 누적) ──
    sec_rows = []
    for sid, info in sec_contrib_acc.items():
        val = info['val_last']
        modify = info['modify_sum']
        ret_pct = (modify / val * 100) if val > 0 else 0
        contrib_pct = (modify / first_nav * 100) if first_nav > 0 else 0
        sec_rows.append({
            '자산군': info['자산군'],
            'sec_id': sid,
            '종목명': item_to_name.get(sid, sid),
            '수익률(%)': round(ret_pct, 4),
            '기여수익률(%)': round(contrib_pct, 4),
            'FX기여(%)': round((info['fx_sum'] / first_nav * 100) if first_nav > 0 else 0, 4),
        })
    sec_contrib_data = pd.DataFrame(sec_rows)
    if not sec_contrib_data.empty:
        sec_contrib_data = sec_contrib_data.sort_values('기여수익률(%)', ascending=False)

    # ── 11) 일별 누적 Brinson (차트용) ──
    daily_brinson_chart = None
    if not brinson_df.empty:
        dbc = brinson_df.groupby('기준일자').agg(
            alloc=('alloc', 'sum'), select=('select', 'sum'), cross=('cross', 'sum')
        ).sort_index()
        dbc['alloc_cum'] = dbc['alloc'].cumsum() * 100
        dbc['select_cum'] = dbc['select'].cumsum() * 100
        dbc['cross_cum'] = dbc['cross'].cumsum() * 100
        dbc['excess_cum'] = dbc['alloc_cum'] + dbc['select_cum'] + dbc['cross_cum']
        daily_brinson_chart = dbc.reset_index()

    return {
        'pa_df': result_df,
        'total_alloc': total_alloc,
        'total_select': total_select,
        'total_cross': total_cross,
        'total_excess': total_excess,
        'period_ap_return': period_ap_return,
        'period_bm_return': period_bm_return,
        'sec_contrib': sec_contrib_data[['자산군', '종목명', '수익률(%)', '기여수익률(%)']].head(20) if not sec_contrib_data.empty else pd.DataFrame(),
        'daily_brinson': daily_brinson_chart,
        'fx_contrib': fx_contrib_pct,
        'residual': residual,
    }


# ============================================================
# 매크로 지표 로딩 (SCIP 기반)
# ============================================================

# 매크로 지표 dataset_id 매핑
MACRO_DATASETS = {
    # 주식 지수 (TR)
    'MSCI ACWI': {'dataset_id': 57, 'dataseries_id': 9, 'type': 'index'},
    'S&P 500': {'dataset_id': 24, 'dataseries_id': 6, 'type': 'index'},
    'MSCI Korea': {'dataset_id': 144, 'dataseries_id': 6, 'type': 'index'},
    'MSCI EM': {'dataset_id': 37, 'dataseries_id': 6, 'type': 'index'},
    'MSCI World ex US': {'dataset_id': 36, 'dataseries_id': 6, 'type': 'index'},
    # PE/EPS
    'MSCI ACWI_PE': {'dataset_id': 57, 'dataseries_id': 24, 'type': 'valuation'},
    'MSCI ACWI_EPS': {'dataset_id': 57, 'dataseries_id': 31, 'type': 'valuation'},
    'S&P 500_PE': {'dataset_id': 24, 'dataseries_id': 24, 'type': 'valuation'},
    'S&P 500_EPS': {'dataset_id': 24, 'dataseries_id': 31, 'type': 'valuation'},
    'MSCI Korea_PE': {'dataset_id': 144, 'dataseries_id': 24, 'type': 'valuation'},
    'MSCI Korea_EPS': {'dataset_id': 144, 'dataseries_id': 31, 'type': 'valuation'},
    'MSCI EM_PE': {'dataset_id': 37, 'dataseries_id': 24, 'type': 'valuation'},
    'MSCI EM_EPS': {'dataset_id': 37, 'dataseries_id': 31, 'type': 'valuation'},
    # FX
    'USD/KRW': {'dataset_id': 31, 'dataseries_id': 6, 'type': 'fx', 'currency': 'USD'},
    # 변동성/스프레드
    'VIX': {'dataset_id': 403, 'dataseries_id': 9, 'type': 'volatility'},
    'MOVE': {'dataset_id': 405, 'dataseries_id': 9, 'type': 'volatility'},
    'US HY OAS': {'dataset_id': 404, 'dataseries_id': 9, 'type': 'spread'},
    # 금
    'Gold': {'dataset_id': 408, 'dataseries_id': 15, 'type': 'commodity'},
}


def load_macro_timeseries(indicator_keys: list = None,
                          start_date: str = '2017-01-01') -> dict:
    """
    SCIP에서 매크로 지표 시계열 로드.

    Returns: dict[indicator_name] = pd.DataFrame(기준일자, value)
    """
    if indicator_keys is None:
        indicator_keys = list(MACRO_DATASETS.keys())

    # dataset_id → dataseries_id 그룹핑 (쿼리 최소화)
    queries = {}  # (dataset_id, dataseries_id) → [indicator_key, ...]
    for key in indicator_keys:
        if key not in MACRO_DATASETS:
            continue
        info = MACRO_DATASETS[key]
        q_key = (info['dataset_id'], info['dataseries_id'])
        if q_key not in queries:
            queries[q_key] = []
        queries[q_key].append(key)

    # 고유 dataset_ids 수집
    all_dataset_ids = list(set(ds for ds, _ in queries.keys()))
    all_dataseries_ids = list(set(ser for _, ser in queries.keys()))

    try:
        raw = load_scip_prices(all_dataset_ids, all_dataseries_ids, start_date)
    except Exception as e:
        logger.error(f"매크로 지표 로드 실패: {e}")
        return {}

    result = {}
    for (ds_id, ser_id), keys in queries.items():
        subset = raw[(raw['dataset_id'] == ds_id) & (raw['dataseries_id'] == ser_id)].copy()
        if subset.empty:
            continue

        for key in keys:
            info = MACRO_DATASETS[key]
            currency = info.get('currency')

            values = []
            dates = []
            for _, row in subset.iterrows():
                v = parse_data_blob(row['data'], currency)
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    if isinstance(v, dict):
                        # dict인 경우: KRW 우선, 없으면 USD
                        v = v.get('KRW', v.get('USD', list(v.values())[0] if v else np.nan))
                    values.append(float(v))
                    dates.append(row['기준일자'])

            if values:
                result[key] = pd.DataFrame({
                    '기준일자': dates,
                    'value': values
                }).sort_values('기준일자').reset_index(drop=True)

    return result


def load_macro_period_returns(macro_data: dict, reference_date: str = None) -> dict:
    """
    매크로 시계열 → 기간별 수익률(%) 계산.

    Returns: dict[indicator] = {'1D':, '1W':, '1M':, '3M':, '6M':, '1Y':, 'YTD':, 'current':}
    """
    if reference_date:
        ref = pd.Timestamp(reference_date)
    else:
        ref = pd.Timestamp.now().normalize()

    period_bdays = {'1D': 1, '1W': 5, '1M': 22, '3M': 66, '6M': 132, '1Y': 252}

    result = {}
    for key, df in macro_data.items():
        if df.empty:
            continue
        ts = df.set_index('기준일자')['value'].sort_index()
        # 가장 가까운 기준일로 이동
        if ref not in ts.index:
            closest = ts.index[ts.index <= ref]
            if closest.empty:
                continue
            ref_actual = closest[-1]
        else:
            ref_actual = ref

        current_val = ts.loc[ref_actual]
        info = MACRO_DATASETS.get(key, {})
        is_level = info.get('type') in ('volatility', 'spread', 'rate')

        periods = {}
        for pname, bdays in period_bdays.items():
            past_idx = ts.index[ts.index <= ref_actual - pd.Timedelta(days=bdays * 1.5)]
            if past_idx.empty:
                periods[pname] = np.nan
                continue
            past_val = ts.loc[past_idx[-1]]
            if is_level:
                periods[pname] = current_val - past_val  # 레벨 변화
            else:
                periods[pname] = ((current_val / past_val) - 1) * 100 if past_val != 0 else 0

        # YTD
        ytd_start = pd.Timestamp(f'{ref_actual.year}-01-01')
        ytd_idx = ts.index[ts.index >= ytd_start]
        if len(ytd_idx) > 0:
            ytd_val = ts.loc[ytd_idx[0]]
            if is_level:
                periods['YTD'] = current_val - ytd_val
            else:
                periods['YTD'] = ((current_val / ytd_val) - 1) * 100 if ytd_val != 0 else 0
        else:
            periods['YTD'] = np.nan

        periods['current'] = current_val
        result[key] = periods

    return result


def load_holdings_history_8class(fund_code: str, start_date: str = None) -> pd.DataFrame:
    """
    자산군별 비중 이력 (8분류).
    sol_DWPM10530에서 월별 비중 추이 로드.

    Returns: DataFrame(기준일자, 국내주식, 해외주식, ..., 유동성)
    """
    conn = get_pandas_connection('dt')
    try:
        params = [fund_code]
        date_filter = ""
        if start_date:
            date_filter = " AND STD_DT >= %s"
            params.append(start_date.replace('-', ''))

        sql = f"""
            SELECT STD_DT, ITEM_CD, ITEM_NM, AST_CLSF_CD_NM,
                   SUM(NAST_TAMT_AGNST_WGH) as 비중
            FROM DWPM10530
            WHERE FUND_CD = %s AND IMC_CD = '003228'
              AND EVL_AMT > 0
              AND ITEM_NM NOT LIKE '%%미지급%%'
              AND ITEM_NM NOT LIKE '%%미수%%'
              {date_filter}
            GROUP BY STD_DT, ITEM_CD, ITEM_NM, AST_CLSF_CD_NM
            ORDER BY STD_DT
        """
        df = pd.read_sql(sql, conn, params=params)
        if df.empty:
            return pd.DataFrame()

        # 자산군 분류 적용
        asset_classes_8 = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', 'FX', '모펀드', '유동성']
        df['자산군'] = df.apply(_classify_6class, axis=1)
        df['기준일자'] = pd.to_datetime(df['STD_DT'].astype(str), format='%Y%m%d')

        pivot = df.groupby(['기준일자', '자산군'])['비중'].sum().unstack(fill_value=0)
        pivot = pivot.reindex(columns=asset_classes_8, fill_value=0)
        return pivot.reset_index()
    except Exception as e:
        logger.error(f"비중 이력 로드 실패 ({fund_code}): {e}")
        return pd.DataFrame()
    finally:
        conn.close()
