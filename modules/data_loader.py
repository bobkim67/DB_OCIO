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
    펀드 PA 원천 데이터 로드.
    R: get_PA_source_data(fund_cd, start_date, end_date)
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
