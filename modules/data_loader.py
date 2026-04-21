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

    blob 형태:
      {"USD": 608.66, "KRW": 868066.70}                       → dict (FX/TR)
      {"totRtnIndex": "16177", "cleanPriceIndex": "10232", ...} → dict (KIS)
      2451.187912                                              → float
      "13.06"                                                   → float

    currency 지정 시 해당 키 값만 반환, 미지정 시 dict 또는 float.
    dict 안에 숫자 변환 불가 value(예: indexName='KIS 10Y KTB')는 skip.
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
                parsed = {}
                for k, v in obj.items():
                    try:
                        parsed[k] = float(v)
                    except (ValueError, TypeError):
                        continue  # 문자열 field(indexName 등) 무시
                if not parsed:
                    return np.nan
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
            SELECT std_dt AS CAL_DT, hldy_yn AS HOLI_FG
            FROM DWCI10220
            WHERE std_dt >= '20000101'
            ORDER BY std_dt
        """
        df = pd.read_sql(sql, conn)
        df['CAL_DT'] = pd.to_datetime(df['CAL_DT'], format='%Y%m%d')
        return df
    finally:
        conn.close()


def get_business_days(holiday_df: pd.DataFrame) -> pd.DatetimeIndex:
    """영업일만 추출. R: selectable_dates"""
    col = 'HOLI_FG'
    vals = holiday_df[col].unique()
    if 'N' in vals:
        bdays = holiday_df[holiday_df[col] == 'N']['CAL_DT']
    else:
        bdays = holiday_df[holiday_df[col] == '0']['CAL_DT']
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
            SELECT STD_DT, MOD_STPR, NAST_AMT, PDD_CHNG_STPR, DD1_ERN_RT
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
        resp = requests.get(url, timeout=30, verify=False)
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

        # dict 반환 처리 (currency 미지정 시 KIS blob 등): totRtnIndex → USD → KRW → 첫값
        def _pick_scalar(v):
            if isinstance(v, dict):
                for key in ('totRtnIndex', 'USD', 'KRW'):
                    if key in v:
                        return v[key]
                return next(iter(v.values()), np.nan) if v else np.nan
            return v
        df['value'] = df['value'].apply(_pick_scalar)

        df = df[df['value'].notna() & df['value'].apply(lambda v: isinstance(v, (int, float)))]
        df['value'] = df['value'].astype(float)
        return df[['기준일자', 'value']].reset_index(drop=True)
    finally:
        conn.close()


# ============================================================
# DT BM 지수 (DWPM10041 서브BM / DWPM10040 기본BM)
# ============================================================

# DT BM 매핑: (테이블, BM유형)
# DWPM10041: 서브BM1/서브BM2 (BM_DS_CD LIKE '%BMn%')
# DWPM10040: 기본BM (FUND_BM_DS_CD='B', DD1_ERN_RT != 0인 펀드만)
_DT_BM_CONFIG = {
    # DWPM10041 서브BM
    '07G04': ('10041', 'BM1'),   # 서브BM1
    '07G02': ('10041', 'BM1'),   # 서브BM1만 존재
    '07G03': ('10041', 'BM1'),   # 서브BM1만 존재
    '08K88': ('10041', 'BM2'),
    # DWPM10040 기본BM
    '4JM12': ('10040', 'B'),
}


def load_dt_bm_prices(fund_code: str, start_date: str = None) -> pd.DataFrame:
    """
    DT에서 BM 기준가 시계열 로드.
    DWPM10041(서브BM) 또는 DWPM10040(기본BM)에서 조회.
    _DT_BM_CONFIG에 등록된 펀드만 지원.

    Returns: DataFrame(기준일자, value) — load_scip_bm_prices와 동일 포맷
    """
    cfg = _DT_BM_CONFIG.get(fund_code)
    if cfg is None:
        return pd.DataFrame(columns=['기준일자', 'value'])

    table, bm_type = cfg
    conn = get_pandas_connection('dt')
    try:
        start_int = int(start_date.replace('-', '')) if start_date else None
        if table == '10041':
            params = [fund_code, f'%{bm_type}%']
            where_date = ""
            if start_int:
                where_date = " AND STD_DT >= %s"
                params.append(start_int)
            sql = f"""
                SELECT STD_DT, MOD_STPR
                FROM DWPM10041
                WHERE FUND_CD = %s AND BM_DS_CD LIKE %s {where_date}
                ORDER BY STD_DT
            """
        else:  # 10040
            params = [fund_code, 'B']
            where_date = ""
            if start_int:
                where_date = " AND STD_DT >= %s"
                params.append(start_int)
            sql = f"""
                SELECT STD_DT, MOD_STPR
                FROM DWPM10040
                WHERE FUND_CD = %s AND FUND_BM_DS_CD = %s {where_date}
                ORDER BY STD_DT
            """
        df = pd.read_sql(sql, conn, params=params)
        if df.empty:
            return pd.DataFrame(columns=['기준일자', 'value'])
        df['기준일자'] = pd.to_datetime(df['STD_DT'].astype(str), format='%Y%m%d')
        df['value'] = df['MOD_STPR'].astype(float)
        df = df[df['value'] != 0]  # 더미(0) 제거
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
# 거래내역 순매수/매도 (DWPM10520)
# ============================================================

# HOLD_AST_DS_CD → AST_CLSF_CD_NM 대리 매핑 (거래내역에 AST_CLSF_CD_NM 없음)
# 거래종목 분류 override (ETF 자동분류 오류 방지, 2026-04-13 수동 확인)
_TRADE_ITEM_CLASSIFY = {
    # 국내채권
    'KR103502GE97': '국내채권', 'KR103502GE30': '국내채권',
    'KR103502GC65': '국내채권', 'KR103502GD98': '국내채권',
    'KR6169379E88': '국내채권',  # 메리츠캐피탈
    'KR7365780006': '국내채권',  # ACE 국고채10년
    'KR7487340002': '국내채권',  # ACE 머니마켓액티브
    'KR7356540005': '국내채권',  # ACE 종합채권(AA-이상)액티브
    'KR7439870007': '국내채권',  # KODEX 국고채30년액티브
    'KR7385560008': '국내채권',  # RISE KIS국고채30년Enhanced
    'KR7451530000': '국내채권',  # TIGER 국고채30년스트립액티브
    'KRZ502659020': '국내채권',  # 월넛은행채플러스
    # 해외채권
    'KR7453850000': '해외채권',  # ACE 미국30년국채액티브(H)
    'KR7468380001': '해외채권',  # KODEX iShares미국하이일드액티브
    'KR7484790001': '해외채권',  # KODEX 미국30년국채액티브(H)
    'KR7458250008': '해외채권',  # TIGER 미국30년국채스트립액티브(합성 H)
    'US46435U8532': '해외채권',  # iShares Broad USD HY
    'US9219468850': '해외채권',  # VANGUARD EMERG MKTS GOV BND
    # 해외주식
    'KR7367380003': '해외주식',  # ACE 미국나스닥100
    'KR70127M0006': '해외주식',  # ACE 미국대형가치주액티브
    'KR70127P0003': '해외주식',  # ACE 미국대형성장주액티브
    'US78464A4094': '해외주식',  # SPDR S&P 500 Growth
    'US9219438580': '해외주식',  # VANGUARD FTSE DEVELOPED
    'US9220428588': '해외주식',  # VANGUARD FTSE EM
    'US9229087443': '해외주식',  # VANGUARD VALUE
    # 국내주식
    'KR7105190003': '국내주식',  # ACE 200
    'KR7332500008': '국내주식',  # ACE 200TR
    # 대체투자
    'KR7411060007': '대체투자',  # ACE KRX금현물
    'US46436F1030': '대체투자',  # ISHARES GOLD TRUST MICRO
    'US92189F1066': '대체투자',  # VANECK GOLD MINERS
    # FX
    'KR4A75610001': 'FX', 'KR4A75620000': 'FX',
    'KR4A75630009': 'FX', 'KR4A75640008': 'FX',
    # 유동성
    'USMUSD022001': 'FX',  # USD DEPOSIT
    # 국내채권 (TMF 펀드)
    'KRZ502659020': '국내채권',  # 월넛은행채플러스 (이미 위에 있지만 중복 안전)
}

# 국내채권으로 분류할 종목명 패턴 (ISIN이 고정되지 않는 경우)
_TRADE_ITEM_NAME_CLASSIFY = {
    '한국투자TMF': '국내채권',
}


def load_fund_net_trades(fund_code: str, start_date: int, end_date: int) -> dict:
    """DWPM10520에서 기간 중 자산군별 순매수/매도 요약.

    Returns:
        dict: {자산군: {'buy': 억원, 'sell': 억원, 'net': 억원}}
        빈 dict이면 거래 없음.
    """
    conn = get_pandas_connection('dt')
    try:
        df = pd.read_sql(f"""
            SELECT item_cd, item_nm, hold_ast_ds_cd, curr_ds_cd,
                   buy_sell_ds_cd, trd_amt
            FROM DWPM10520
            WHERE fund_cd = %s AND std_dt BETWEEN %s AND %s
              AND imc_cd = '003228'
        """, conn, params=[fund_code, start_date, end_date])
    finally:
        conn.close()

    if df.empty:
        return {}

    # 분류: override 우선 → _classify_6class fallback
    def _classify_trade(row):
        icd = str(row.get('item_cd', '')).strip()
        override = _TRADE_ITEM_CLASSIFY.get(icd)
        if override:
            return override
        inm = str(row.get('item_nm', ''))
        # 종목명 패턴 매칭
        for pattern, cls in _TRADE_ITEM_NAME_CLASSIFY.items():
            if pattern in inm:
                return cls
        # 콜론/REPO/모펀드는 유동성/모펀드
        if any(kw in inm for kw in ['콜론', 'REPO', '예금', 'DEPOSIT']):
            return '유동성'
        if icd.startswith('0322800'):
            return '모펀드'
        # fallback
        row2 = dict(row)
        row2['AST_CLSF_CD_NM'] = ''
        row2['ITEM_CD'] = icd
        row2['ITEM_NM'] = inm
        row2['CURR_DS_CD'] = row.get('curr_ds_cd', '')
        return _classify_6class(row2)

    df['자산군'] = df.apply(_classify_trade, axis=1)

    # 매수(M)/매도(D)별 금액 합산
    df['trd_amt'] = pd.to_numeric(df['trd_amt'], errors='coerce').fillna(0)
    result = {}
    for asset_class in df['자산군'].unique():
        sub = df[df['자산군'] == asset_class]
        buy = sub.loc[sub['buy_sell_ds_cd'] == 'M', 'trd_amt'].sum()
        sell = sub.loc[sub['buy_sell_ds_cd'] == 'D', 'trd_amt'].sum()
        result[asset_class] = {
            'buy': round(buy / 1e8, 1),
            'sell': round(sell / 1e8, 1),
            'net': round((buy - sell) / 1e8, 1),
        }
    return result


def load_fund_trade_detail(fund_code: str, start_date: int, end_date: int) -> pd.DataFrame:
    """DWPM10520에서 날짜별 거래내역 상세. 자산군 분류 포함.

    Returns: DataFrame [날짜, 종목명, 자산군, 매수매도, 금액(억)]
    """
    conn = get_pandas_connection('dt')
    try:
        df = pd.read_sql("""
            SELECT std_dt, item_cd, item_nm, hold_ast_ds_cd, curr_ds_cd,
                   buy_sell_ds_cd, trd_amt
            FROM DWPM10520
            WHERE fund_cd = %s AND std_dt BETWEEN %s AND %s
              AND imc_cd = '003228'
            ORDER BY std_dt, item_nm
        """, conn, params=[fund_code, start_date, end_date])
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame()

    def _classify(row):
        icd = str(row.get('item_cd', '')).strip()
        override = _TRADE_ITEM_CLASSIFY.get(icd)
        if override:
            return override
        inm = str(row.get('item_nm', ''))
        if any(kw in inm for kw in ['콜론', 'REPO', '예금', 'DEPOSIT']):
            return '유동성'
        if icd.startswith('0322800'):
            return '모펀드'
        row2 = {'AST_CLSF_CD_NM': '', 'ITEM_CD': icd, 'ITEM_NM': inm,
                'CURR_DS_CD': row.get('curr_ds_cd', '')}
        return _classify_6class(row2)

    df['자산군'] = df.apply(_classify, axis=1)
    df['매수매도'] = df['buy_sell_ds_cd'].map({'M': '매수', 'D': '매도'}).fillna(df['buy_sell_ds_cd'])
    df['금액(억)'] = pd.to_numeric(df['trd_amt'], errors='coerce').fillna(0) / 1e8
    df['날짜'] = df['std_dt'].astype(str)
    df['종목명'] = df['item_nm']

    return df[['날짜', '종목명', '자산군', '매수매도', '금액(억)']].round(2)


def load_fund_holdings_weight(fund_code: str, date: int) -> pd.DataFrame:
    """특정일 보유종목 비중. 자산군 분류 포함.

    Returns: DataFrame [종목명, 자산군, 비중(%), 평가금액(억)]
    """
    conn = get_pandas_connection('dt')
    try:
        df = pd.read_sql("""
            SELECT item_cd, item_nm, nast_tamt_agnst_wgh as wgh, evl_amt,
                   hold_ast_ds_cd, curr_ds_cd
            FROM DWPM10530
            WHERE fund_cd = %s AND std_dt = %s AND imc_cd = '003228' AND evl_amt > 0
            ORDER BY evl_amt DESC
        """, conn, params=[fund_code, date])
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame()

    def _classify(row):
        icd = str(row.get('item_cd', '')).strip()
        override = _TRADE_ITEM_CLASSIFY.get(icd)
        if override:
            return override
        inm = str(row.get('item_nm', ''))
        for pattern, cls in _TRADE_ITEM_NAME_CLASSIFY.items():
            if pattern in inm:
                return cls
        if any(kw in inm for kw in ['콜론', 'REPO', '예금', 'DEPOSIT', '증거금', '미수']):
            return '유동성'
        if icd.startswith('0322800'):
            return '모펀드'
        row2 = {'AST_CLSF_CD_NM': '', 'ITEM_CD': icd, 'ITEM_NM': inm,
                'CURR_DS_CD': row.get('curr_ds_cd', '')}
        return _classify_6class(row2)

    df['자산군'] = df.apply(_classify, axis=1)
    df['비중(%)'] = pd.to_numeric(df['wgh'], errors='coerce').fillna(0).round(2)
    df['평가금액(억)'] = pd.to_numeric(df['evl_amt'], errors='coerce').fillna(0) / 1e8
    df['종목명'] = df['item_nm']

    return df[['종목명', '자산군', '비중(%)', '평가금액(억)']].round(2)


# ============================================================
# 보유종목 + 6분류 매핑
# Monitoring/auto_classify.py 패턴 + AST_CLSF_CD_NM 결합
# ============================================================

def _classify_6class(row) -> str:
    """
    AST_CLSF_CD_NM + ITEM_CD + ITEM_NM 조합으로 6분류 매핑.
    국내주식 / 해외주식 / 국내채권 / 해외채권 / 대체투자 / 유동성
    """
    item_cd = str(row.get('ITEM_CD', '')).strip()
    # 수동 확인 override (거래내역 + 보유종목 공통)
    override = _TRADE_ITEM_CLASSIFY.get(item_cd)
    if override:
        return override
    item_nm_raw = str(row.get('ITEM_NM', ''))
    for pattern, cls in _TRADE_ITEM_NAME_CLASSIFY.items():
        if pattern in item_nm_raw:
            return cls

    ast = str(row.get('AST_CLSF_CD_NM', '')).upper()
    item_cd = item_cd.upper()
    item_nm = item_nm_raw.upper()
    curr = str(row.get('CURR_DS_CD', '')).upper()

    # 특수 종목 처리 (auto_classify 패턴)
    if any(kw in item_nm for kw in ['콜론', '예금', '증거금', 'MMF', '미수', '미지급',
                                      '청약금', '원천세', '분배금', '기타자산', 'DEPOSIT',
                                      'CMA', '수시입출금']):
        return '유동성'
    if 'REPO' in item_nm:
        return '유동성'
    if item_cd.startswith('0322800'):
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
    DWPM10530의 모펀드 ITEM_CD 형식: '03228000{FUND_CD}' (예: 0322800007G02 → 07G02)
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

# 설정후 수익률 계산용 설정일 기준가 (시스템 일치용)
_FUND_INCEPTION_BASE = {
    '4JM12': 1970.76,  # 시스템 설정후 수익률 기준가
}


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
    if ('KIS' in nm or 'KAP' in nm) and ('CALL' in nm or 'MONEY' in nm):
        return '유동성'
    if 'KIS' in nm or 'KAP' in nm:
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
    _bm_fx_weight = 0.0  # FX 오버레이 비중 (해외주식 unhedged BM만, hedged 제외)
    for comp in components:
        ac = _map_bm_component_to_asset_class(comp['name'])
        bm_weights[ac] += comp['weight'] * 100
        comp_class_map[comp['name']] = ac
        # 해외주식 **unhedged만** FX 오버레이 기여
        if ac == '해외주식' and not comp.get('hedged', False) and comp.get('region') == 'ex_KR':
            _bm_fx_weight += comp['weight'] * 100

    # USDKRW 로드 (ex_KR 컴포넌트의 T-1×FX 변환에 사용)
    # R 동일: ECOS API (731Y003) → DT DWCI10260 fallback → SCIP ds=31 fallback
    _usdkrw_series = None
    _fx_on_kr_ret = None  # FX 스트립용: _kr_dates 기준 USDKRW 수익률
    _has_ex_kr = any(c.get('region') == 'ex_KR' for c in components)
    if _has_ex_kr:
        try:
            _ecos_df = _load_usdkrw_from_ecos(start_date, end_date)
            if not _ecos_df.empty and 'USD_KRW' in _ecos_df.columns:
                _fx_s = _ecos_df.set_index('기준일자')[['USD_KRW']].sort_index()
                _fx_s = _fx_s[~_fx_s.index.duplicated(keep='last')]
                _usdkrw_series = _fx_s['USD_KRW']
        except Exception:
            pass
        # ECOS/DT 모두 실패 시 SCIP fallback
        if _usdkrw_series is None:
            _fx_df = load_scip_bm_prices(31, 6, start_date, 'USD')
            if not _fx_df.empty and len(_fx_df) >= 2:
                _fx_s = _fx_df.set_index('기준일자').sort_index()
                _fx_s = _fx_s[~_fx_s.index.duplicated(keep='last')]
                _usdkrw_series = _fx_s['value']

    # 1단계: KR 컴포넌트 로드 → 한국 영업일 캘린더 확보
    _kr_dates = None
    _kr_comp_prices = {}
    for comp in components:
        if comp.get('region') == 'ex_KR':
            continue
        df = load_scip_bm_prices(comp['dataset_id'], comp['dataseries_id'],
                                  start_date, comp.get('currency'))
        if df.empty or len(df) < 2:
            continue
        df = df.set_index('기준일자').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        _kr_comp_prices[comp['name']] = df['value']
        if _kr_dates is None:
            _kr_dates = df.index
        else:
            _kr_dates = _kr_dates.union(df.index)
    # _kr_dates: R의 selectable_dates 동일 — DWCI10220 영업일 캘린더 직접 사용
    try:
        _cal_conn = get_pandas_connection('dt')
        _cal_df = pd.read_sql(
            "SELECT std_dt FROM DWCI10220 WHERE hldy_yn='N' AND std_dt >= %s AND std_dt <= %s "
            "ORDER BY std_dt", _cal_conn, params=[start_date, end_date])
        _cal_conn.close()
        if not _cal_df.empty:
            _kr_dates = pd.DatetimeIndex(
                pd.to_datetime(_cal_df['std_dt'].astype(str)).sort_values(), name=None)
    except Exception:
        # DB 실패 시 컴포넌트 날짜 union + 주말 제거 fallback
        if _kr_dates is not None:
            _kr_dates = _kr_dates.sort_values()
            _kr_dates = _kr_dates[_kr_dates.dayofweek < 5]

    # 2단계: 모든 컴포넌트 수익률 계산
    comp_returns = {}
    for comp in components:
        ac = comp_class_map[comp['name']]
        if comp.get('region') == 'ex_KR' and _kr_dates is not None:
            if comp.get('hedged'):
                # Hedged KRW: KRW 가격 T-1 shift만 (FX 변환 불필요)
                df_h = load_scip_bm_prices(comp['dataset_id'], comp['dataseries_id'],
                                            start_date, comp.get('currency'))
                if df_h.empty or len(df_h) < 2:
                    continue
                df_h = df_h.set_index('기준일자').sort_index()
                df_h = df_h[~df_h.index.duplicated(keep='last')]
                val_on_kr = df_h['value'].reindex(_kr_dates).ffill()
                val_t1 = val_on_kr.shift(1)  # T-1 (한국BD 기준)
                daily_ret = val_t1.pct_change().fillna(0)
            elif _usdkrw_series is not None:
                # Unhedged: USD가격(T-1, 한국BD) × USDKRW(T) → KRW → 수익률
                df_usd = load_scip_bm_prices(comp['dataset_id'], comp['dataseries_id'],
                                              start_date, 'USD')
                if df_usd.empty or len(df_usd) < 2:
                    continue
                df_usd = df_usd.set_index('기준일자').sort_index()
                df_usd = df_usd[~df_usd.index.duplicated(keep='last')]
                usd_on_kr = df_usd['value'].reindex(_kr_dates).ffill()
                usd_t1 = usd_on_kr.shift(1)  # T-1 (한국BD 기준)
                fx_on_kr = _usdkrw_series.reindex(_kr_dates).ffill()
                krw_price = usd_t1 * fx_on_kr
                daily_ret = krw_price.pct_change().fillna(0)
                # FX 스트립용: 동일 _kr_dates 기준 FX 수익률 저장
                if _fx_on_kr_ret is None:
                    _fx_on_kr_ret = fx_on_kr.pct_change().fillna(0)
            else:
                continue
        elif comp['name'] in _kr_comp_prices:
            # 국내: 그대로
            daily_ret = _kr_comp_prices[comp['name']].pct_change()
        else:
            df = load_scip_bm_prices(comp['dataset_id'], comp['dataseries_id'],
                                      start_date, comp.get('currency'))
            if df.empty or len(df) < 2:
                continue
            df = df.set_index('기준일자').sort_index()
            df = df[~df.index.duplicated(keep='last')]
            daily_ret = df['value'].pct_change()

        comp_returns[comp['name']] = {
            'daily_ret': daily_ret,
            'weight': comp['weight'],
            'class': ac
        }

    if not comp_returns:
        return bm_weights, pd.DataFrame()

    # 영업일 캘린더 기준 (R 동일: intersection 아닌 union, 누락일=0 수익률)
    # _kr_dates가 있으면 사용 (ex_KR 컴포넌트도 이미 _kr_dates 기준으로 계산됨)
    if _kr_dates is not None and len(_kr_dates) >= 2:
        all_dates = _kr_dates
    else:
        all_dates = None
        for cr in comp_returns.values():
            idx = cr['daily_ret'].dropna().index
            all_dates = idx if all_dates is None else all_dates.union(idx)
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

    # FX 오버레이: unhedged ex_KR 컴포넌트만 FX 분리 (hedged 컴포넌트는 이미 FX 없음)
    # 각 unhedged 컴포넌트 x: stock_ret = (1+x_ret)/(1+r_fx) - 1; fx_only = x_ret - stock_ret
    # 해외주식 자산군에서 unhedged 기여를 원수익률 → stock_ret로 교체
    # FX 자산군 = unhedged 컴포넌트들의 fx_only 수익률 (weight 비례 평균)
    if _bm_fx_weight > 0 and _fx_on_kr_ret is not None:
        try:
            fx_ret = _fx_on_kr_ret.reindex(all_dates).fillna(0)
            _unhedged_entries = [
                (cn, cr) for cn, cr in comp_returns.items()
                if any(c['name'] == cn and c.get('region') == 'ex_KR' and not c.get('hedged', False)
                       for c in components)
            ]
            _total_unhedged_w = sum(cr['weight'] for _, cr in _unhedged_entries)
            fx_return_series = pd.Series(0.0, index=all_dates)
            for cn, cr in _unhedged_entries:
                ac = cr['class']
                w = cr['weight']
                unhedged_ret = cr['daily_ret'].reindex(all_dates).fillna(0)
                stock_ret = (1 + unhedged_ret) / (1 + fx_ret) - 1
                total_w_ac = bm_weights[ac] / 100 if bm_weights[ac] > 0 else 1
                # 해외주식 자산군에서 unhedged 원수익률 제거 후 stock_ret 추가
                bm_daily[ac] -= unhedged_ret * (w / total_w_ac)
                bm_daily[ac] += stock_ret * (w / total_w_ac)
                # FX 자산군 수익률 = weight 비례 fx_only
                if _total_unhedged_w > 0:
                    fx_return_series += (unhedged_ret - stock_ret) * (w / _total_unhedged_w)
            bm_daily['FX'] = fx_return_series
            bm_weights['FX'] = _bm_fx_weight
        except Exception:
            pass

    # BM cost: 컴포넌트별 미적용 (R 동일)
    # R은 BM 복합 수익률에만 -34bp 적용, 자산군별은 RAW
    # cost는 Brinson 유동성/기타 잔차에 자연 흡수됨

    # 날짜 필터 (int 방어)
    start_date = str(start_date)
    end_date = str(end_date)
    sd = pd.Timestamp(f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}") if len(start_date) == 8 else pd.Timestamp(start_date)
    ed = pd.Timestamp(f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}") if len(end_date) == 8 else pd.Timestamp(end_date)
    bm_daily = bm_daily[(bm_daily.index >= sd) & (bm_daily.index <= ed)]

    bm_daily.index.name = None  # DatetimeIndex 이름 초기화
    bm_daily = bm_daily.reset_index().rename(columns={'index': '기준일자'})
    # FX 일별 수익률도 반환 (AP FX split에 사용)
    _fx_daily_for_ap = None
    if _fx_on_kr_ret is not None:
        _fx_daily_for_ap = _fx_on_kr_ret.copy()
    return bm_weights, bm_daily, _fx_daily_for_ap


def compute_brinson_attribution(fund_code: str,
                                start_date: str, end_date: str,
                                asset_classes_8: list = None) -> dict:
    """
    Brinson 3-Factor Attribution 계산 (Phase 4: 일별 정밀 로직).
    BM은 config.funds.FUND_BM에서 fund_code 기준으로 자동 매핑.

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

    # int 날짜 방어 (예: 20260101 → '20260101')
    start_date = str(start_date)
    end_date = str(end_date)

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
    # T-1 기준가가 필요하므로 start_date보다 100일 이전부터 로드 (달력 기반)
    _nast_start = max((pd.Timestamp(start_date) - pd.Timedelta(days=100)).strftime('%Y%m%d'), '20200101')
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

        # 자산군별 일별 비중 및 수익률 (NAST_AMT 기준 — Brinson 잔차 최소화)
        # modify_unav_chg는 기준가(per-unit) 단위, val은 총액(원) 단위
        # 비중 = val(T-1) / NAST_AMT(T-1), 수익률 = 기여수익률 / 비중
        # 이렇게 하면 sum(w × r) = sum(기여수익률) = port_ret → 잔차=0
        nast_amt_prev = nav_dict.get(prev_nast_dt, {}).get('nast_amt', None)
        if nast_amt_prev is None or nast_amt_prev == 0:
            nast_amt_prev = sum(c['val_t1'] for c in class_day.values()) or 1

        # AP FX 비중 = 해외자산(해외주식+해외채권+FX) val_t1 합 / NAST (오버레이)
        # FX 분리: 비-FX 자산군의 환산효과를 FX 자산군으로 이전 (R 동일)
        total_fx_from_others = sum(
            class_day[ac]['fx_modify'] for ac in asset_classes_8 if ac != 'FX'
        )

        # AP FX 비중 = 해외자산(해외주식+해외채권+FX) val_t1 합 / NAST (오버레이)
        _overseas_classes = ('해외주식', '해외채권', 'FX')
        _ap_fx_val_t1 = sum(class_day[ac]['val_t1'] for ac in _overseas_classes if ac in class_day)

        rec = {'pr_date': dt, 'port_ret': daily_port_ret}
        for ac in asset_classes_8:
            m = class_day[ac]['modify']
            fx_m = class_day[ac]['fx_modify']
            v = class_day[ac]['val_t1']

            if ac == 'FX':
                # FX 오버레이: 자체 modify + 타 자산군 환산효과
                m_brinson = m + total_fx_from_others
                # FX 비중 = 전체 해외자산 val_t1 / NAST (오버레이)
                w = _ap_fx_val_t1 / nast_amt_prev if nast_amt_prev > 0 else 0
            else:
                # 비-FX: 환산 제외한 증권 수익만
                m_brinson = m - fx_m
                w = v / nast_amt_prev if nast_amt_prev > 0 else 0

            contrib = m_brinson / mod_stpr_prev
            r = contrib / w if w > 0 else 0
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
    _usdkrw_daily_ret = None

    if bm_info:
        # BM 로드 시 웜업 기간 확보 (T-1 shift + pct_change에 필요)
        from datetime import timedelta
        _sd_dt = pd.Timestamp(f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}") if len(str(start_date)) == 8 else pd.Timestamp(start_date)
        _bm_warmup_start = (_sd_dt - timedelta(days=45)).strftime('%Y%m%d')
        bm_weights, bm_daily_df, _usdkrw_daily_ret = _load_bm_daily_returns_by_class(
            bm_info, _bm_warmup_start, end_date, asset_classes_8)

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

    # 일별 Brinson 효과 (유동성 제외 — R 동일: 유동성=잔차로 처리)
    _BRINSON_CLASSES = [ac for ac in asset_classes_8 if ac != '유동성']
    brinson_daily = []
    for ac in _BRINSON_CLASSES:
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

    # ── 6.5) 보정인자1 적용 (R 동일: 경로의존적 상대초과수익률 스케일링) ──
    # R ref: func_PA_결합및요약용_final.R lines 483-535
    # 보정인자1 = 상대초과수익률(기하) / 단순초과수익률(산술)
    # 모든 Brinson 효과에 곱하여 합계가 상대초과수익률에 정확히 분해되도록 함
    _bm_composite_daily = None
    _relative_excess_pct = None
    if bm_available and not brinson_df.empty:
        # BM 복합 일별 수익률 (RAW 컴포넌트 가중합 + cost)
        # R 동일: 복합에만 -34bp/365 적용, 컴포넌트별은 RAW
        _BM_COST_DAILY = 34 / 10000 / 365
        _bm_composite_daily = pd.Series(0.0, index=common_dates)
        for ac in asset_classes_8:
            w = bm_weights.get(ac, 0) / 100
            if ac in bm_daily_df.columns:
                _bm_composite_daily += bm_daily_df[ac] * w
        _bm_composite_daily -= _BM_COST_DAILY  # 복합에만 cost 적용

        ap_cum = (1 + daily_df['port_ret']).cumprod()
        bm_cum = (1 + _bm_composite_daily).cumprod()
        relative_cum_excess = ap_cum / bm_cum - 1

        prev_rel = relative_cum_excess.shift(1).fillna(0)
        relative_excess_daily = (1 + relative_cum_excess) / (1 + prev_rel) - 1

        simple_excess_daily = daily_df['port_ret'] - _bm_composite_daily

        correction = pd.Series(0.0, index=common_dates)
        nonzero = simple_excess_daily.abs() > 1e-15
        correction[nonzero] = relative_excess_daily[nonzero] / simple_excess_daily[nonzero]

        cf_map = correction.to_dict()
        brinson_df['_cf'] = brinson_df['기준일자'].map(cf_map).fillna(0)
        brinson_df['alloc'] *= brinson_df['_cf']
        brinson_df['select'] *= brinson_df['_cf']
        brinson_df['cross'] *= brinson_df['_cf']
        brinson_df.drop(columns='_cf', inplace=True)

        _relative_excess_pct = relative_cum_excess.iloc[-1] * 100

    # ── 7) 기간 집계 ──
    # 누적 수익률 (경로의존적)
    daily_df['cum_port_ret'] = (1 + daily_df['port_ret']).cumprod() - 1
    period_ap_return = daily_df['cum_port_ret'].iloc[-1] * 100 if len(daily_df) > 0 else 0

    # BM 누적 수익률: _bm_composite_daily (RAW + cost) 기준
    if bm_available:
        if _bm_composite_daily is None:
            _BM_COST_DAILY = 34 / 10000 / 365
            _bm_composite_daily = pd.Series(0.0, index=common_dates)
            for ac in asset_classes_8:
                w = bm_weights.get(ac, 0) / 100
                if ac in bm_daily_df.columns:
                    _bm_composite_daily += bm_daily_df[ac] * w
            _bm_composite_daily -= _BM_COST_DAILY
        period_bm_return = ((1 + _bm_composite_daily).cumprod().iloc[-1] - 1) * 100
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

    # Brinson 기간 합계 (일별 합산, 유동성 제외)
    if not brinson_df.empty:
        period_brinson = brinson_df.groupby('자산군').agg(
            alloc=('alloc', 'sum'), select=('select', 'sum'), cross=('cross', 'sum')
        ).reindex(_BRINSON_CLASSES).fillna(0)
    else:
        period_brinson = pd.DataFrame(0, index=_BRINSON_CLASSES, columns=['alloc', 'select', 'cross'])

    # ── 8) 상대초과수익률 ──
    if _relative_excess_pct is not None:
        total_excess = _relative_excess_pct
    else:
        total_excess = period_ap_return - period_bm_return

    # 결과 테이블 조립 (유동성=잔차, R 동일)
    results = []
    _brinson_alloc_sum = 0
    _brinson_select_sum = 0
    _brinson_cross_sum = 0
    for ac in asset_classes_8:
        ap_w = ap_period_weights.get(ac, 0)
        bm_w = bm_weights.get(ac, 0)
        ap_r = ap_period_returns.get(ac, 0)
        bm_r = bm_period_returns.get(ac, 0)
        contrib_col = f'{ac}_contrib'
        cum_contrib = daily_df[contrib_col].sum() * 100 if contrib_col in daily_df.columns else 0

        if ac == '유동성':
            # 유동성: A=0, S=0, Cross=잔차 (R 동일)
            alloc, sel, crs = 0, 0, 0  # 잔차는 아래에서 계산
        elif ac in period_brinson.index:
            alloc = period_brinson.loc[ac, 'alloc'] * 100
            sel = period_brinson.loc[ac, 'select'] * 100
            crs = period_brinson.loc[ac, 'cross'] * 100
            _brinson_alloc_sum += alloc
            _brinson_select_sum += sel
            _brinson_cross_sum += crs
        else:
            alloc, sel, crs = 0, 0, 0

        results.append({
            '자산군': ac, 'AP비중': round(ap_w, 2), 'BM비중': round(bm_w, 2),
            'AP수익률': round(ap_r, 2), 'BM수익률': round(bm_r, 2),
            'Allocation': round(alloc, 4), 'Selection': round(sel, 4),
            'Cross': round(crs, 4), '기여수익률': round(cum_contrib, 4)
        })

    result_df = pd.DataFrame(results)

    # 유동성 잔차 = 초과수익률 - 5개 자산군 Brinson 합
    _brinson_5_sum = _brinson_alloc_sum + _brinson_select_sum + _brinson_cross_sum
    _liquidity_residual = total_excess - _brinson_5_sum
    _liq_idx = result_df[result_df['자산군'] == '유동성'].index
    if len(_liq_idx) > 0:
        result_df.loc[_liq_idx[0], 'Cross'] = round(_liquidity_residual, 4)

    total_alloc = result_df['Allocation'].sum()
    total_select = result_df['Selection'].sum()
    total_cross = result_df['Cross'].sum()
    residual = 0  # 잔차가 유동성 Cross에 흡수됨

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


def compute_brinson_attribution_v2(fund_code: str,
                                   start_date: str, end_date: str,
                                   asset_classes: list = None,
                                   mapping_method: str = '방법3') -> dict:
    """
    Brinson 3-Factor Attribution — R 완벽 일치 버전.

    R reference: func_PA_결합및요약용_final.R lines 429-558
    - comparable_period: 자산군별 수익률(Normalized)_FX분리 = sum(수익률×|weight_PA(T)|)/sum(|weight_PA(T)|)
    - 비중_PA = sum(|weight_PA(T)|) — NAST-based (조정_평가시가평가액/(순자산T-1+순설정))
    - 초과수익률(daily_return_diff) = AP일별 - BM일별 (단순차)
    - 초과누적상대수익률 = (1+AP누적)/(1+BM누적)-1, 일별분해 = (1+상대T)/(1+상대T-1)-1
    - 보정인자1 = 초과수익률(상대) / 초과수익률(단순)
    - Cross = (w_AP - w_BM)(r_AP - r_BM), Alloc = (w_AP - w_BM)×r_BM, Select = w_BM×(r_AP-r_BM)
    - 유동성및기타 = daily_return_diff - sum(Cross+Alloc+Select) (일별)
    - 모든 effect × 보정인자1

    Returns: dict (keys는 기존 compute_brinson_attribution과 호환)
    """
    if asset_classes is None:
        asset_classes = ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성및기타']

    start_date = str(start_date)
    end_date = str(end_date)

    # ── 1) Single PA 호출 (R PA_from_MOS exact) ──
    single_pa = compute_single_port_pa(
        fund_code, start_date, end_date,
        fx_split=True, mapping_method=mapping_method,
    )
    if single_pa is None:
        logger.warning(f"[BrinsonV2] {fund_code} Single PA 실패")
        return None

    asset_daily = single_pa['asset_daily']
    asset_summary = single_pa['asset_summary']
    port_daily = single_pa['port_daily_returns']

    if port_daily.empty:
        return None

    dates_idx = pd.DatetimeIndex(sorted(port_daily.index.unique()))
    port_daily = port_daily.reindex(dates_idx).fillna(0)

    # ── 2) AP 자산군별 일별 수익률/비중 피벗 (R 동일: weight_PA) ──
    ap_ret_daily = asset_daily.pivot(index='기준일자', columns='자산군',
                                     values='자산군수익률_daily').reindex(dates_idx).fillna(0)
    ap_wgt_daily = asset_daily.pivot(index='기준일자', columns='자산군',
                                     values='weight_PA').reindex(dates_idx).fillna(0)

    for ac in asset_classes:
        if ac not in ap_ret_daily.columns:
            ap_ret_daily[ac] = 0
        if ac not in ap_wgt_daily.columns:
            ap_wgt_daily[ac] = 0

    # ── 3) BM 일별 수익률 로드 ──
    from config.funds import FUND_BM
    bm_info = FUND_BM.get(fund_code)

    _BM_ASSET_CLASSES = ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성']
    bm_weights_raw = {ac: 0.0 for ac in _BM_ASSET_CLASSES}
    bm_daily_df = pd.DataFrame()

    if bm_info:
        _sd_dt = pd.Timestamp(f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}")
        _bm_warmup_start = (_sd_dt - timedelta(days=45)).strftime('%Y%m%d')
        bm_weights_raw, bm_daily_df, _ = _load_bm_daily_returns_by_class(
            bm_info, _bm_warmup_start, end_date, _BM_ASSET_CLASSES)

    # BM '유동성' → '유동성및기타'로 매핑
    bm_weights = {}
    for ac in _BM_ASSET_CLASSES:
        target = '유동성및기타' if ac == '유동성' else ac
        bm_weights[target] = bm_weights_raw.get(ac, 0)

    if not bm_daily_df.empty:
        bm_daily_df = bm_daily_df.set_index('기준일자') if '기준일자' in bm_daily_df.columns else bm_daily_df
        if '유동성' in bm_daily_df.columns:
            bm_daily_df = bm_daily_df.rename(columns={'유동성': '유동성및기타'})
        bm_daily_df = bm_daily_df.reindex(dates_idx).fillna(0)
        bm_available = True
    else:
        bm_daily_df = pd.DataFrame(0.0, index=dates_idx, columns=asset_classes)
        bm_available = False

    # ── 4) BM 복합 일별 수익률 (RAW + 펀드별 cost) ──
    # R 프로덕션: -34bp/yr cost는 08K88에만 적용
    _BM_COST_DAILY = 34 / 10000 / 365
    _BM_COST_FUNDS = {'08K88'}
    bm_composite_daily = pd.Series(0.0, index=dates_idx)
    for ac in asset_classes:
        w = bm_weights.get(ac, 0) / 100
        if ac in bm_daily_df.columns:
            bm_composite_daily += bm_daily_df[ac] * w
    if bm_available and fund_code in _BM_COST_FUNDS:
        bm_composite_daily -= _BM_COST_DAILY

    # ── 5) 보정인자1 (R line 491-505) ──
    # 초과누적상대수익률 = (1+AP_cum)/(1+BM_cum) - 1
    ap_cum = (1 + port_daily).cumprod()
    bm_cum = (1 + bm_composite_daily).cumprod()
    relative_cum_excess = ap_cum / bm_cum - 1

    # 초과수익률(상대 일별) = (1+상대T)/(1+상대T-1)-1
    prev_rel = relative_cum_excess.shift(1).fillna(0)
    relative_excess_daily = (1 + relative_cum_excess) / (1 + prev_rel) - 1

    # 초과수익률(daily_return_diff) = AP일별 - BM일별 (단순차)
    daily_return_diff = port_daily - bm_composite_daily

    # 보정인자1 = 상대/단순
    correction = pd.Series(0.0, index=dates_idx)
    nonzero = daily_return_diff.abs() > 1e-15
    correction[nonzero] = relative_excess_daily[nonzero] / daily_return_diff[nonzero]

    # ── 6) 일별 Brinson (R line 529-536) — 유동성 제외한 5개 자산군 ──
    _BRINSON_CLASSES = [ac for ac in asset_classes if ac != '유동성및기타']

    # 각 날짜별로 5개 자산군 Brinson effect 합 계산
    brinson_raw = {ac: {'alloc': pd.Series(0.0, index=dates_idx),
                        'select': pd.Series(0.0, index=dates_idx),
                        'cross': pd.Series(0.0, index=dates_idx)} for ac in _BRINSON_CLASSES}

    for ac in _BRINSON_CLASSES:
        ap_w = ap_wgt_daily[ac]
        ap_r = ap_ret_daily[ac]
        bm_w = bm_weights.get(ac, 0) / 100  # 기간 고정 (R Fixed weight)
        bm_r = bm_daily_df[ac] if ac in bm_daily_df.columns else pd.Series(0.0, index=dates_idx)

        # R 공식 (line 529-531)
        brinson_raw[ac]['cross'] = (ap_w - bm_w) * (ap_r - bm_r)
        brinson_raw[ac]['alloc'] = (ap_w - bm_w) * bm_r
        brinson_raw[ac]['select'] = bm_w * (ap_r - bm_r)

    # 일별 Brinson 합 (5개 자산군)
    daily_brinson_sum = pd.Series(0.0, index=dates_idx)
    for ac in _BRINSON_CLASSES:
        daily_brinson_sum += brinson_raw[ac]['alloc'] + brinson_raw[ac]['select'] + brinson_raw[ac]['cross']

    # 유동성및기타 일별 = daily_return_diff - sum(Brinson)
    liquidity_daily_raw = daily_return_diff - daily_brinson_sum

    # ── 7) 보정인자1 곱 (R line 534-535) ──
    for ac in _BRINSON_CLASSES:
        brinson_raw[ac]['alloc'] *= correction
        brinson_raw[ac]['select'] *= correction
        brinson_raw[ac]['cross'] *= correction
    liquidity_daily = liquidity_daily_raw * correction

    # ── 8) 기간 집계 (R line 583-596: path-dependent weighting + 2차 스케일) ──
    period_ap_return = (ap_cum.iloc[-1] - 1) * 100
    period_bm_return = (bm_cum.iloc[-1] - 1) * 100 if bm_available else 0
    # 단순차 기반 초과수익률 (R line 501)
    period_excess = period_ap_return - period_bm_return
    # 상대누적 초과 (R line 484 초과누적수익률 수준의 이론치)
    period_excess_relative = relative_cum_excess.iloc[-1] * 100

    # R 공식 (line 586, 594):
    # 총손익기여도 = cumsum(sec기여도)/1000 = sum(일별효과 × (1+상대누적_{T-1}))
    # 보정_총손익기여도 = 총손익기여도 × 단순차누적 / 상대누적
    rel_cum_prev = relative_cum_excess.shift(1).fillna(0)
    path_weight = 1 + rel_cum_prev  # (1 + 상대누적_{T-1})
    _final_scaler = (period_excess / period_excess_relative) if abs(period_excess_relative) > 1e-12 else 1.0

    # 자산군별 Brinson 기간 합 (path-weighted + 단순/상대 스케일)
    period_brinson = {}
    for ac in _BRINSON_CLASSES:
        period_brinson[ac] = {
            'alloc': (brinson_raw[ac]['alloc'] * path_weight).sum() * 100 * _final_scaler,
            'select': (brinson_raw[ac]['select'] * path_weight).sum() * 100 * _final_scaler,
            'cross': (brinson_raw[ac]['cross'] * path_weight).sum() * 100 * _final_scaler,
        }
    liquidity_period = (liquidity_daily * path_weight).sum() * 100 * _final_scaler

    # AP 기간 수익률/비중 (asset_summary: R 경로의존 누적)
    ap_period_returns = dict(zip(asset_summary['자산군'], asset_summary['개별수익률']))
    ap_period_weights = dict(zip(asset_summary['자산군'], asset_summary['순자산비중']))
    ap_period_contribs = dict(zip(asset_summary['자산군'], asset_summary['기여수익률']))

    bm_period_returns = {}
    for ac in asset_classes:
        if bm_available and ac in bm_daily_df.columns:
            bm_period_returns[ac] = ((1 + bm_daily_df[ac]).cumprod().iloc[-1] - 1) * 100
        else:
            bm_period_returns[ac] = 0

    # ── 9) 결과 테이블 조립 ──
    results = []
    for ac in asset_classes:
        ap_w = ap_period_weights.get(ac, 0) * 100
        bm_w = bm_weights.get(ac, 0)
        ap_r = ap_period_returns.get(ac, 0) * 100
        bm_r = bm_period_returns.get(ac, 0)
        contrib = ap_period_contribs.get(ac, 0) * 100

        if ac == '유동성및기타':
            alloc, sel, crs = 0, 0, liquidity_period
        else:
            b = period_brinson[ac]
            alloc, sel, crs = b['alloc'], b['select'], b['cross']

        results.append({
            '자산군': ac, 'AP비중': round(ap_w, 2), 'BM비중': round(bm_w, 2),
            'AP수익률': round(ap_r, 2), 'BM수익률': round(bm_r, 2),
            'Allocation': round(alloc, 4), 'Selection': round(sel, 4),
            'Cross': round(crs, 4), '기여수익률': round(contrib, 4),
        })

    result_df = pd.DataFrame(results)

    total_alloc = result_df['Allocation'].sum()
    total_select = result_df['Selection'].sum()
    total_cross = result_df['Cross'].sum()

    # ── 10) 종목별 기여도 ──
    sec_contrib_data = single_pa['sec_summary'][['자산군', '종목명', '개별수익률', '기여수익률']].copy()
    sec_contrib_data['수익률(%)'] = sec_contrib_data['개별수익률'] * 100
    sec_contrib_data['기여수익률(%)'] = sec_contrib_data['기여수익률'] * 100
    sec_contrib_data = sec_contrib_data[['자산군', '종목명', '수익률(%)', '기여수익률(%)']].round(4)
    sec_contrib_data = sec_contrib_data.sort_values('기여수익률(%)', ascending=False)

    # ── 11) 일별 누적 Brinson (차트용) ──
    daily_sum_chart = pd.DataFrame({'기준일자': dates_idx})
    alloc_sum = pd.Series(0.0, index=dates_idx)
    sel_sum = pd.Series(0.0, index=dates_idx)
    crs_sum = pd.Series(0.0, index=dates_idx)
    for ac in _BRINSON_CLASSES:
        alloc_sum += brinson_raw[ac]['alloc']
        sel_sum += brinson_raw[ac]['select']
        crs_sum += brinson_raw[ac]['cross']
    daily_sum_chart['alloc_cum'] = alloc_sum.cumsum().values * 100
    daily_sum_chart['select_cum'] = sel_sum.cumsum().values * 100
    daily_sum_chart['cross_cum'] = (crs_sum + liquidity_daily).cumsum().values * 100
    daily_sum_chart['excess_cum'] = (alloc_sum + sel_sum + crs_sum + liquidity_daily).cumsum().values * 100

    return {
        'pa_df': result_df,
        'total_alloc': total_alloc,
        'total_select': total_select,
        'total_cross': total_cross,
        'total_excess': period_excess,
        'total_excess_relative': period_excess_relative,
        'period_ap_return': period_ap_return,
        'period_bm_return': period_bm_return,
        'sec_contrib': sec_contrib_data.head(20) if not sec_contrib_data.empty else pd.DataFrame(),
        'daily_brinson': daily_sum_chart,
        'fx_contrib': ap_period_contribs.get('FX', 0) * 100,
        'residual': 0,
    }


# ============================================================
# Single Portfolio PA (R 동일 로직)
# R reference: func_펀드_PA_모듈_adj_GENERAL_final.R + func_PA_결합및요약용_final.R
# ============================================================

def _get_class_mother_fund(fund_code: str) -> str:
    """모펀드 코드 조회 (DWPI10011.CLSS_MTFD_CD). 없으면 자기 자신 반환."""
    conn = get_pandas_connection('dt')
    try:
        sql = """
            SELECT CLSS_MTFD_CD FROM DWPI10011
            WHERE FUND_CD = %s AND IMC_CD = '003228'
            AND EFTV_END_DT = '99991231'
            LIMIT 1
        """
        df = pd.read_sql(sql, conn, params=[fund_code])
        if df.empty or pd.isna(df.iloc[0, 0]):
            return fund_code
        return str(df.iloc[0, 0]).strip()
    finally:
        conn.close()


def _get_관련_fund_list(class_m_fund: str) -> list:
    """
    R pulling_모자구조 동등 — class_m_fund 보유 ITEM_CD에서
    `0322800XXXXX` 패턴을 5자리 운용모펀드로 추출, 자기 자신과 함께 반환.

    R ref (func_펀드_PA_모듈_adj_GENERAL_final.R):
        historical_universe_DWPM10530_TOTAL %>% select(-FUND_CD) %>% distinct() %>%
          mutate(ITEM_CD = if_else(str_detect(ITEM_CD, "0322800"),
                                   str_remove_all(ITEM_CD, "0322800"), ITEM_CD)) %>%
          filter(nchar(ITEM_CD) == 5, ITEM_CD != 모펀드)

    07G04 (FoF) 예시: ['07G04', '07G02', '07G03'].
    일반 펀드: ['08K88'].
    """
    conn = get_pandas_connection('dt')
    try:
        sql = """
            SELECT DISTINCT ITEM_CD
            FROM DWPM10530
            WHERE FUND_CD = %s AND STD_DT >= '20210101'
              AND ITEM_CD LIKE '0322800%%'
        """
        df = pd.read_sql(sql, conn, params=[class_m_fund])
        related = set()
        for item in df['ITEM_CD'].dropna():
            s = str(item).strip()
            if s.startswith('0322800'):
                tail = s[7:]
                if len(tail) == 5 and tail != class_m_fund:
                    related.add(tail)
        return [class_m_fund] + sorted(related)
    finally:
        conn.close()


def _load_net_subscription_pa(fund_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    순설정금액 로드 (R 동일 로직).
    R: bf_nast_flct_amt (이월순자산변동금액), 해지 거래 부호 반전.
    """
    conn = get_pandas_connection('dt')
    try:
        sql = """
            SELECT r.tr_dt, r.bf_nast_flct_amt, t.tr_whl_nm
            FROM DWPM12880 r
            LEFT JOIN DWCI10160 t ON r.tr_cd = t.tr_cd AND r.synp_cd = t.synp_cd
            WHERE r.fund_cd = %s AND r.tr_dt >= %s AND r.tr_dt <= %s
        """
        df = pd.read_sql(sql, conn, params=[fund_code, start_date, end_date])
        if df.empty:
            return pd.DataFrame(columns=['기준일자', '순설정금액'])
        # 해지 거래 부호 반전 (R: if_else(str_detect(tr_whl_nm,"해지"), -이월순자산변동금액, ...))
        df['adj_amt'] = df.apply(
            lambda r: -r['bf_nast_flct_amt'] if '해지' in str(r.get('tr_whl_nm', '')) else r['bf_nast_flct_amt'],
            axis=1
        )
        result = df.groupby('tr_dt')['adj_amt'].sum().reset_index()
        result.columns = ['tr_dt', '순설정금액']
        result['기준일자'] = pd.to_datetime(result['tr_dt'].astype(str), format='%Y%m%d')
        return result[['기준일자', '순설정금액']]
    finally:
        conn.close()


def _load_holdings_for_pa(fund_codes, start_date: str, end_date: str) -> pd.DataFrame:
    """
    PA용 DWPM10530 보유종목 로드. 단일 fund_code 또는 리스트 지원.
    R: historical_position_DWPM10530 (lines 125-147)
    R은 class_m_fund + 운용모펀드 리스트로 조회 (FoF 펀드 대응).
    PDD_QTY, BUY_QTY, SELL_QTY로 신규매수/전량매도 판별, POS_DS_CD로 position_gb 크로스체크.
    """
    if isinstance(fund_codes, str):
        fund_codes = [fund_codes]
    if not fund_codes:
        return pd.DataFrame()
    conn = get_pandas_connection('dt')
    try:
        placeholders = ','.join(['%s'] * len(fund_codes))
        sql = f"""
            SELECT STD_DT, FUND_CD, ITEM_CD, ITEM_NM, POS_DS_CD,
                   COALESCE(EVL_AMT, 0) AS EVL_AMT,
                   COALESCE(PDD_QTY, 0) AS PDD_QTY,
                   COALESCE(BUY_QTY, 0) AS BUY_QTY,
                   COALESCE(SELL_QTY, 0) AS SELL_QTY
            FROM DWPM10530
            WHERE FUND_CD IN ({placeholders})
              AND STD_DT >= %s AND STD_DT <= %s
              AND ITEM_NM NOT LIKE '%%미지급%%'
              AND ITEM_NM NOT LIKE '%%미수%%'
            ORDER BY STD_DT, ITEM_CD
        """
        df = pd.read_sql(sql, conn, params=[*fund_codes, start_date, end_date])
        if df.empty:
            return df

        df['기준일자'] = pd.to_datetime(df['STD_DT'].astype(str), format='%Y%m%d')

        # 1차: 하루에 사고팔고 합산 (R: group_by(기준일자, FUND_CD, ITEM_CD) → reframe(sum))
        # FoF 재간접 펀드에서도 R과 동일하게 fund-wise row 유지 (2차 합산 없음).
        # pa_raw merge 시 Cartesian 발생 → _agg_sec_group이 (sec_id, FUND_CD_holdings) 별 처리.
        agg = df.groupby(['기준일자', 'FUND_CD', 'ITEM_CD']).agg(
            POS_DS_CD=('POS_DS_CD', 'first'),
            ITEM_NM=('ITEM_NM', 'first'),
            EVL_AMT=('EVL_AMT', 'sum'),
            PDD_QTY=('PDD_QTY', 'sum'),
            BUY_QTY=('BUY_QTY', 'sum'),
            SELL_QTY=('SELL_QTY', 'sum'),
        ).reset_index()

        # R: filter(EVL_AMT+PDD_QTY+BUY_QTY+SELL_QTY != 0)
        agg = agg[agg['EVL_AMT'] + agg['PDD_QTY'] + agg['BUY_QTY'] + agg['SELL_QTY'] != 0].copy()

        # R: 전량청산시 매수처리 (POS_DS_CD=="매도" & PDD_QTY+BUY_QTY<=SELL_QTY → "매수")
        rollover_mask = (agg['POS_DS_CD'] == '매도') & (agg['PDD_QTY'] + agg['BUY_QTY'] <= agg['SELL_QTY'])
        agg.loc[rollover_mask, 'POS_DS_CD'] = '매수'
        # R: EVL_AMT = if_else(POS_DS_CD=="매도", -EVL_AMT, EVL_AMT)
        agg.loc[agg['POS_DS_CD'] == '매도', 'EVL_AMT'] *= -1

        return agg
    finally:
        conn.close()


def _load_etf_redemption_adjustment(fund_codes, start_date: str, end_date: str) -> pd.DataFrame:
    """
    ETF 발행시장환매 평가시가평가액 보정 (R lines 177-183). 단일 fund_code 또는 리스트 지원.
    R은 class_m_fund + 운용모펀드 리스트로 DWPM10520을 조회.
    """
    if isinstance(fund_codes, str):
        fund_codes = [fund_codes]
    if not fund_codes:
        return pd.DataFrame(columns=['기준일자', 'item_cd', '평가시가평가액보정'])
    conn = get_pandas_connection('dt')
    try:
        placeholders = ','.join(['%s'] * len(fund_codes))
        sql = f"""
            SELECT t.std_dt, t.fund_cd, t.item_cd, t.item_nm,
                   t.trd_amt, t.tr_upr, t.trd_pl_amt,
                   c.tr_whl_nm
            FROM DWPM10520 t
            LEFT JOIN DWCI10160 c ON t.tr_cd = c.tr_cd AND t.synp_cd = c.synp_cd
            WHERE t.fund_cd IN ({placeholders})
              AND t.std_dt >= %s AND t.std_dt <= %s
              AND c.tr_whl_nm LIKE '%%ETF발행시장환매%%'
        """
        df = pd.read_sql(sql, conn, params=[*fund_codes, start_date, end_date])
        if df.empty:
            return pd.DataFrame(columns=['기준일자', 'item_cd', '평가시가평가액보정'])

        df['기준일자'] = pd.to_datetime(df['std_dt'].astype(str), format='%Y%m%d')
        # R: group_by(fund_cd, item_cd, tr_upr, trd_pl_amt) → reframe(기준일자=max, 평가시가평가액보정=trd_amt[1])
        result = df.groupby(['fund_cd', 'item_cd', 'tr_upr', 'trd_pl_amt']).agg(
            기준일자=('기준일자', 'max'),
            평가시가평가액보정=('trd_amt', 'first'),
        ).reset_index()

        # FoF 재간접: R line 191-210 추적배수 적용
        # 추적배수 = (모펀드가 보유한 하위펀드 PDD_QTY) / (하위펀드 자체 OPNG_AMT)
        #   → 모펀드가 하위펀드를 100% 보유하지 않는 경우 거래금액을 비례 축소
        if len(fund_codes) > 1:
            class_m_fund = fund_codes[0]
            sub_funds = [f for f in fund_codes if f != class_m_fund]
            if sub_funds:
                sub_placeholders = ','.join(['%s'] * len(sub_funds))

                # 모펀드 포지션 (class_m_fund 보유 내역의 하위펀드 PDD_QTY)
                sql_mf = """
                    SELECT STD_DT, ITEM_CD, PDD_QTY
                    FROM DWPM10530
                    WHERE FUND_CD = %s AND STD_DT >= %s AND STD_DT <= %s
                      AND ITEM_CD LIKE '0322800%%'
                """
                mf_pos = pd.read_sql(sql_mf, conn, params=[class_m_fund, start_date, end_date])
                if not mf_pos.empty:
                    mf_pos['기준일자'] = pd.to_datetime(mf_pos['STD_DT'].astype(str), format='%Y%m%d')
                    mf_pos['sub_fund'] = mf_pos['ITEM_CD'].str.replace('0322800', '', regex=False)
                    mf_pos = mf_pos[mf_pos['sub_fund'].str.len() == 5][['기준일자', 'sub_fund', 'PDD_QTY']]
                else:
                    mf_pos = pd.DataFrame(columns=['기준일자', 'sub_fund', 'PDD_QTY'])

                # 하위펀드 OPNG_AMT
                sql_sub = f"""
                    SELECT STD_DT, FUND_CD, OPNG_AMT
                    FROM DWPM10510
                    WHERE FUND_CD IN ({sub_placeholders})
                      AND STD_DT >= %s AND STD_DT <= %s
                """
                sub_aum = pd.read_sql(sql_sub, conn, params=[*sub_funds, start_date, end_date])
                if not sub_aum.empty:
                    sub_aum['기준일자'] = pd.to_datetime(sub_aum['STD_DT'].astype(str), format='%Y%m%d')
                    sub_aum = sub_aum.rename(columns={'FUND_CD': 'sub_fund'})[['기준일자', 'sub_fund', 'OPNG_AMT']]
                else:
                    sub_aum = pd.DataFrame(columns=['기준일자', 'sub_fund', 'OPNG_AMT'])

                track = mf_pos.merge(sub_aum, on=['기준일자', 'sub_fund'], how='left')
                track['추적배수'] = track['PDD_QTY'] / track['OPNG_AMT']

                result = result.merge(
                    track[['기준일자', 'sub_fund', '추적배수']],
                    left_on=['기준일자', 'fund_cd'],
                    right_on=['기준일자', 'sub_fund'],
                    how='left',
                )
                # 추적배수 결측 (모펀드가 해당일 해당 하위펀드 미보유) → 0으로 간주(R 동일 NA×값 = NA 제거 효과)
                result['추적배수'] = result['추적배수'].fillna(0.0)
                result['평가시가평가액보정'] = result['평가시가평가액보정'] * result['추적배수']

            result = result.groupby(['기준일자', 'item_cd']).agg(
                평가시가평가액보정=('평가시가평가액보정', 'sum'),
            ).reset_index()

        return result[['기준일자', 'item_cd', '평가시가평가액보정']]
    finally:
        conn.close()


def _load_usdkrw_rate(start_date: str = None, end_date: str = None,
                      source: str = 'ECOS') -> pd.DataFrame:
    """
    USDKRW 매매기준율 로드.

    source 태깅:
        'ECOS' — 한국은행 ECOS API (R 동일 소스, stat_code=731Y003)
        'DWCI10260' — dt.DWCI10260 테이블 (DB 대체 소스)
    나중에 source='DWCI10260'으로 교체 가능.
    """
    if source == 'ECOS':
        return _load_usdkrw_from_ecos(start_date, end_date)
    else:
        return _load_usdkrw_from_db(start_date, end_date)


def _load_usdkrw_from_ecos(start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """ECOS API로 USDKRW 매매기준율 로드 (R 동일: stat_code=731Y003, item=0000003)."""
    import requests
    import warnings
    warnings.filterwarnings('ignore', message='Unverified HTTPS request')

    api_key = "FWC2IZWA5YD459SQ7RJM"
    # 충분한 버퍼 포함 (R: start_time=19000101)
    st = start_date or '20100101'
    ed = end_date or pd.Timestamp.now().strftime('%Y%m%d')
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/"
           f"1/10000/731Y003/D/{st}/{ed}/0000003")

    try:
        resp = requests.get(url, timeout=15, verify=False)
        data = resp.json()
    except Exception as e:
        logger.warning(f"[ECOS API] 요청 실패, DWCI10260 fallback: {e}")
        return _load_usdkrw_from_db(start_date, end_date)

    if 'StatisticSearch' not in data:
        logger.warning(f"[ECOS API] 응답 없음, DWCI10260 fallback")
        return _load_usdkrw_from_db(start_date, end_date)

    rows = data['StatisticSearch']['row']
    df = pd.DataFrame(rows)
    df = df[['TIME', 'DATA_VALUE']].copy()
    df.columns = ['STD_DT', 'USD_KRW']
    df['STD_DT'] = df['STD_DT'].astype(int)
    df['USD_KRW'] = df['USD_KRW'].str.replace(',', '').astype(float)
    df['기준일자'] = pd.to_datetime(df['STD_DT'].astype(str), format='%Y%m%d')
    df = df.sort_values('기준일자').reset_index(drop=True)

    # R 동일: pad_by_time(.by="day", .fill_na_direction="down")
    full_range = pd.date_range(df['기준일자'].min(), df['기준일자'].max(), freq='D')
    df = df.set_index('기준일자').reindex(full_range).ffill().reset_index()
    df.columns = ['기준일자'] + list(df.columns[1:])
    df['return_USDKRW'] = df['USD_KRW'].pct_change()
    df['_source'] = 'ECOS'  # 소스 태깅

    return df


def _load_usdkrw_from_db(start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """DWCI10260에서 USDKRW 매매기준율 로드 (DB 소스)."""
    conn = get_pandas_connection('dt')
    try:
        conditions = ["CURR_DS_CD = 'USD'"]
        params = []
        if start_date:
            conditions.append("STD_DT >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("STD_DT <= %s")
            params.append(end_date)
        sql = f"SELECT STD_DT, TR_STD_RT FROM DWCI10260 WHERE {' AND '.join(conditions)} ORDER BY STD_DT"
        df = pd.read_sql(sql, conn, params=params)
        if not df.empty:
            df['기준일자'] = pd.to_datetime(df['STD_DT'].astype(str), format='%Y%m%d')
            df['return_USDKRW'] = df['TR_STD_RT'].pct_change()
            df['_source'] = 'DWCI10260'  # 소스 태깅
        return df
    finally:
        conn.close()


def _load_currency_exposure_mapping() -> dict:
    """통화 노출 매핑 (solution.universe_non_derivative → ISIN:노출통화 dict)."""
    conn = get_pandas_connection('solution')
    try:
        sql = """
            SELECT ISIN, classification as 노출통화
            FROM universe_non_derivative
            WHERE classification_method = 'Currency Exposure'
            AND classification IS NOT NULL AND ISIN IS NOT NULL
        """
        df = pd.read_sql(sql, conn)
        return dict(zip(df['ISIN'], df['노출통화']))
    finally:
        conn.close()


def _load_asset_classification_mapping(method: str = '방법3') -> dict:
    """자산군 분류 매핑 (solution.universe_non_derivative → ISIN:자산군 dict)."""
    conn = get_pandas_connection('solution')
    try:
        sql = """
            SELECT ISIN, classification as 자산군
            FROM universe_non_derivative
            WHERE classification_method = %s
            AND classification IS NOT NULL AND ISIN IS NOT NULL
        """
        df = pd.read_sql(sql, conn, params=[method])
        return dict(zip(df['ISIN'], df['자산군']))
    finally:
        conn.close()


def _load_derivative_mapping(method: str = '방법3') -> tuple:
    """
    파생 자산군/통화 매핑 (solution.universe_derivative).
    ITEM_NM keyword 매칭 기반이라 list[(asset_gb, keyword, classification)] 반환.

    Returns:
        (asset_rules, ccy_rules) — asset_gb + keyword 규칙으로 ITEM_NM 매칭
    """
    conn = get_pandas_connection('solution')
    try:
        q = """
            SELECT asset_gb, keyword, classification_method, classification
            FROM universe_derivative
            WHERE classification_method IN (%s, 'Currency Exposure')
              AND classification IS NOT NULL
        """
        df = pd.read_sql(q, conn, params=[method])
    finally:
        conn.close()
    asset_rules = [(r['asset_gb'], r['keyword'], r['classification'])
                   for _, r in df[df['classification_method'] == method].iterrows()]
    ccy_rules = [(r['asset_gb'], r['keyword'], r['classification'])
                 for _, r in df[df['classification_method'] == 'Currency Exposure'].iterrows()]
    return asset_rules, ccy_rules


def _match_derivative_rule(rules: list, asset_gb: str, item_nm: str) -> str:
    """(asset_gb, keyword, classification) 리스트에서 ITEM_NM에 keyword 포함된 첫 매치 반환. 미매치 None."""
    if not item_nm or not asset_gb:
        return None
    ag = str(asset_gb)
    inm = str(item_nm)
    for rule_ag, rule_kw, cls in rules:
        if (rule_ag == ag) and (rule_kw in inm):
            return cls
    return None


def compute_single_port_pa(fund_code: str, start_date: str, end_date: str,
                           fx_split: bool = True, mapping_method: str = '방법3') -> dict:
    """
    단일 포트폴리오 PA (R 동일 로직).

    R reference:
    - PA_from_MOS(): 비중/수익률 계산, FX 분리
    - Portfolio_analysis(): 기여수익률, 누적기여도

    Parameters:
        fund_code: 펀드코드 (예: '08N81')
        start_date: 분석시작일 (YYYYMMDD)
        end_date: 분석종료일 (YYYYMMDD)
        fx_split: FX 분리 여부 (True=증권/FX 분리)
        mapping_method: 자산군 분류 방법 ('방법1'~'방법5')

    Returns: dict with keys:
        'asset_summary': DataFrame (자산군별 요약 — Excel Sheet 1)
        'sec_summary': DataFrame (종목별 요약 — Excel Sheet 2)
        'asset_daily': DataFrame (자산군별 일별 — Excel Sheet 3)
        'sec_daily': DataFrame (종목별 일별 — Excel Sheet 4)
        'classification': DataFrame (분류현황 — Excel Sheet 5)
    """
    # ── 1) 모펀드 코드 ──
    class_m_fund = _get_class_mother_fund(fund_code)
    logger.info(f"[SinglePA] fund={fund_code}, class_m={class_m_fund}, {start_date}~{end_date}")

    # ── 2) 데이터 로드 (T-1 버퍼 포함, 달력 기반 -100일) ──
    buf_start = max((pd.Timestamp(start_date) - pd.Timedelta(days=100)).strftime('%Y%m%d'), '20200101')

    # MA000410
    pa_raw = load_pa_source(class_m_fund, buf_start, end_date)
    if pa_raw.empty:
        logger.warning(f"[SinglePA] MA000410 데이터 없음: {class_m_fund}")
        return None

    # Error sec 필터링 (R: sum(abs(amt))==0인 종목 제거)
    sec_err = pa_raw.groupby('sec_id')['amt'].apply(lambda x: x.abs().sum())
    error_secs = sec_err[sec_err == 0].index.tolist()
    pa_raw = pa_raw[~pa_raw['sec_id'].isin(error_secs)].copy()

    # DWPM10510 (class_m_fund + fund_code)
    nast_class_m = _load_daily_nast(class_m_fund, buf_start, end_date)
    if class_m_fund != fund_code:
        nast_fund = _load_daily_nast(fund_code, buf_start, end_date)
    else:
        nast_fund = nast_class_m

    if nast_class_m.empty or nast_fund.empty:
        logger.warning(f"[SinglePA] DWPM10510 데이터 없음")
        return None

    # Merge: class_m의 NAST_AMT + fund의 MOD_STPR/PDD_CHNG_STPR
    nast_class_m = nast_class_m.sort_values('기준일자').reset_index(drop=True)
    nast_fund = nast_fund.sort_values('기준일자').reset_index(drop=True)

    if class_m_fund != fund_code:
        fund_info = nast_class_m[['기준일자', 'NAST_AMT']].merge(
            nast_fund[['기준일자', 'MOD_STPR', 'PDD_CHNG_STPR', 'DD1_ERN_RT']],
            on='기준일자', how='inner'
        )
    else:
        fund_info = nast_class_m[['기준일자', 'NAST_AMT', 'MOD_STPR', 'PDD_CHNG_STPR', 'DD1_ERN_RT']].copy()

    fund_info = fund_info.sort_values('기준일자').reset_index(drop=True)

    # MOD_STPR → 1000 리베이스 (R: PDD_CHNG_STPR[1]==0 분기)
    if fund_info['PDD_CHNG_STPR'].iloc[0] == 0:
        base = 10000 if fund_info['MOD_STPR'].iloc[0] > 9500 else 1000
        fund_info['PDD_CHNG_STPR'] = fund_info['MOD_STPR'].shift(1).fillna(base)
        fund_info['수정기준가'] = fund_info['MOD_STPR']
    else:
        fund_info['수정기준가'] = fund_info['MOD_STPR']
        first_mod = fund_info['MOD_STPR'].iloc[0]
        first_dd1 = fund_info['DD1_ERN_RT'].iloc[0] / 100
        fund_info['MOD_STPR'] = (fund_info['MOD_STPR'] / first_mod) * 1000
        fund_info['PDD_CHNG_STPR'] = fund_info['MOD_STPR'].shift(1)
        fund_info.loc[fund_info.index[0], 'PDD_CHNG_STPR'] = 1000 * (1 - first_dd1)

    fund_info['daily_return'] = fund_info['MOD_STPR'] / fund_info['PDD_CHNG_STPR'] - 1

    # 순설정금액
    net_sub = _load_net_subscription_pa(class_m_fund, start_date, end_date)

    # USDKRW 환율
    usdkrw = _load_usdkrw_rate(buf_start, end_date)

    # 통화 노출 & 자산군 매핑
    ccy_dict = _load_currency_exposure_mapping()
    asset_dict = _load_asset_classification_mapping(mapping_method)

    # DWPM10530 보유내역 (R: historical_position_DWPM10530)
    # R은 class_m_fund + 운용모펀드 전체로 조회 (FoF 재간접 대응)
    related_funds = _get_관련_fund_list(class_m_fund)
    logger.info(f"[SinglePA] {fund_code} related_funds={related_funds}")
    holdings_buf_start = max((pd.Timestamp(buf_start) - pd.Timedelta(days=50)).strftime('%Y%m%d'), '20200101')
    holdings_pa = _load_holdings_for_pa(related_funds, holdings_buf_start, end_date)
    has_holdings = not holdings_pa.empty

    # ETF 발행시장환매 보정 (R lines 177-183)
    etf_adj = _load_etf_redemption_adjustment(related_funds, buf_start, end_date)

    # ── 3) 일별 종목별 집계 (MA000410 + DWPM10530 조인) ──
    pa_raw['pr_date'] = pa_raw['pr_date'].astype(int)

    # pl_gb별 환산금액 분리를 위한 마킹
    pa_raw['is_환산'] = (pa_raw['pl_gb'] == '환산').astype(int)
    pa_raw['환산amt'] = pa_raw['amt'] * pa_raw['is_환산']

    # R line 221: MA410 + DWPM10530 left_join → position_gb 보정 + 평가시가평가액 조건부 계산
    if has_holdings:
        # FoF 재간접: holdings_pa는 fund-wise row 유지 → merge 시 Cartesian 발생.
        # 같은 sec_id가 여러 FUND_CD에 걸쳐 있으면 per-(sec, fund) row로 sec_agg에 전개.
        # R 동일 동작 (line 222 left_join distinct 후 per-fund rows 유지).
        _holdings_for_merge = holdings_pa[['기준일자', 'FUND_CD', 'ITEM_CD', 'ITEM_NM',
                                            'POS_DS_CD', 'PDD_QTY', 'BUY_QTY', 'SELL_QTY']].rename(
            columns={'FUND_CD': 'FUND_CD_holdings'})
        pa_raw = pa_raw.merge(
            _holdings_for_merge,
            left_on=['기준일자', 'sec_id'],
            right_on=['기준일자', 'ITEM_CD'],
            how='left',
        )
        # R line 223: position_gb = if_else(position_gb=="LONG" & POS_DS_CD=="매도", "SHORT", position_gb)
        # R if_else NA 전파: TRUE & NA → NA → if_else(NA, ...) → NA
        # (DWPM10530 left_join 결과 POS_DS_CD=NA인 경우 position_gb도 NA가 됨)
        cross_short = (pa_raw['position_gb'] == 'LONG') & (pa_raw['POS_DS_CD'] == '매도')
        pa_raw.loc[cross_short, 'position_gb'] = 'SHORT'
        long_na_posds = (pa_raw['position_gb'] == 'LONG') & pa_raw['POS_DS_CD'].isna()
        pa_raw.loc[long_na_posds, 'position_gb'] = np.nan
    else:
        pa_raw['POS_DS_CD'] = np.nan
        pa_raw['PDD_QTY'] = np.nan
        pa_raw['BUY_QTY'] = np.nan
        pa_raw['ITEM_NM'] = np.nan
        pa_raw['FUND_CD_holdings'] = np.nan

    # R lines 225-236: group_by(fund_id, pr_date, sec_id) → reframe with conditional 평가시가평가액
    def _agg_sec_group(g):
        """R 동일: sec_id 그룹 집계 (lines 225-236)."""
        시가 = g['val'].max()
        총손익 = g['amt'].sum()
        환산 = (g['amt'] * (g['pl_gb'] == '환산').astype(int)).sum()
        ag = g['asset_gb'].iloc[0]

        # 평가시가평가액: R line 230 — 신규매수(PDD_QTY==0 & BUY_QTY!=0) → max(val)-sum(amt)
        pdd_qty = g['PDD_QTY'].iloc[0] if pd.notna(g['PDD_QTY'].iloc[0]) else -1
        buy_qty = g['BUY_QTY'].iloc[0] if pd.notna(g['BUY_QTY'].iloc[0]) else 0
        if pdd_qty == 0 and buy_qty != 0:
            평가시가 = 시가 - 총손익
        else:
            평가시가 = g['std_val'].max()

        # position_gb: R lines 233-236 — 2행 이상이고 '평가' 존재 → 평가 row의 position_gb
        if len(g) >= 2 and (g['pl_gb'] == '평가').any():
            pos = g.loc[g['pl_gb'] == '평가', 'position_gb'].iloc[0]
        else:
            pos = g['position_gb'].iloc[0]

        item_nm = g['ITEM_NM'].iloc[0] if pd.notna(g['ITEM_NM'].iloc[0]) else None
        pos_ds = g['POS_DS_CD'].iloc[0] if 'POS_DS_CD' in g.columns and pd.notna(g['POS_DS_CD'].iloc[0]) else None

        return pd.Series({
            '시가평가액': 시가,
            '평가시가평가액': 평가시가,
            '총손익금액': 총손익,
            '환산금액': 환산,
            'asset_gb': ag,
            'position_gb': pos,
            'ITEM_NM_pos': item_nm,
            'POS_DS_CD': pos_ds,
        })

    # FoF 재간접 대응: groupby에 FUND_CD_holdings 포함 (NaN 별도 그룹)
    sec_agg = pa_raw.groupby(
        ['pr_date', '기준일자', 'sec_id', 'FUND_CD_holdings'], dropna=False
    ).apply(_agg_sec_group).reset_index()

    # R distinct() 재현: reframe 결과에서 FUND_CD는 output에 포함 안 되므로,
    # fund-wise row가 생성되어도 _agg_sec_group output 값이 모두 같으면 중복 제거.
    # case_when 분기 결과(평가시가평가액)가 다른 경우(신규매수 + 기존 혼합)만 multi-row 유지.
    _distinct_cols = [c for c in sec_agg.columns if c != 'FUND_CD_holdings']
    sec_agg = sec_agg.drop_duplicates(subset=_distinct_cols).reset_index(drop=True)

    # R lines 238-242: 전량매도 lag 보정 (group_by sec_id → lag)
    # FoF: per-(sec_id, FUND_CD_holdings) 단위로 lag.
    sec_agg = sec_agg.sort_values(
        ['sec_id', 'FUND_CD_holdings', '기준일자'], na_position='last'
    ).reset_index(drop=True)
    for (sid, fcd), grp in sec_agg.groupby(['sec_id', 'FUND_CD_holdings'], dropna=False):
        if sid == '000000000000':
            continue
        idx = grp.index
        if len(idx) < 2:
            continue
        시가 = sec_agg.loc[idx, '시가평가액'].values
        평가시가 = sec_agg.loc[idx, '평가시가평가액'].values
        for i in range(1, len(idx)):
            # R line 240: 시가평가액==0 & 평가시가평가액==0 → lag(평가시가평가액)
            if 시가[i] == 0 and 평가시가[i] == 0:
                sec_agg.loc[idx[i], '평가시가평가액'] = 평가시가[i - 1]
            # R line 241: 시가평가액==0 → lag(시가평가액)
            elif 시가[i] == 0:
                sec_agg.loc[idx[i], '평가시가평가액'] = 시가[i - 1]

    # 통화 노출 매핑
    sec_agg['노출통화'] = sec_agg['sec_id'].map(ccy_dict)
    # ── derivative fallback (R line 285-302): ISIN 접두어 fallback 이전에 universe_derivative 매칭 ──
    # 미국달러 F 등 파생상품은 ISIN이 KR 접두어라도 실제 노출통화는 USD. 순서 중요.
    _deriv_asset_rules, _deriv_ccy_rules = _load_derivative_mapping(mapping_method)
    na_ccy = sec_agg['노출통화'].isna()
    for idx in sec_agg[na_ccy].index:
        matched = _match_derivative_rule(
            _deriv_ccy_rules,
            sec_agg.loc[idx, 'asset_gb'],
            sec_agg.loc[idx, 'ITEM_NM_pos'],
        )
        if matched:
            sec_agg.loc[idx, '노출통화'] = matched
    # fallback: ISIN 접두어 기반
    na_ccy = sec_agg['노출통화'].isna()
    sec_agg.loc[na_ccy & sec_agg['sec_id'].str.startswith('KR'), '노출통화'] = 'KRW'
    sec_agg.loc[na_ccy & sec_agg['sec_id'].str.startswith('00'), '노출통화'] = 'KRW'
    sec_agg.loc[sec_agg['노출통화'].isna() & (sec_agg['asset_gb'] == '기타비용'), '노출통화'] = 'KRW'
    # R line 308-309: 유동 항목은 sec_id 접두어로 구분 (US→USD, KR/00→KRW)
    유동_na = sec_agg['노출통화'].isna() & (sec_agg['asset_gb'] == '유동')
    sec_agg.loc[유동_na & sec_agg['sec_id'].str[:2].isin(['KR', '00']), '노출통화'] = 'KRW'
    sec_agg.loc[유동_na & sec_agg['sec_id'].str.startswith('US'), '노출통화'] = 'USD'
    sec_agg.loc[유동_na & sec_agg['노출통화'].isna(), '노출통화'] = 'KRW'  # 기타 유동
    sec_agg['노출통화'] = sec_agg['노출통화'].fillna('USD')

    # 자산군 매핑
    sec_agg['자산군'] = sec_agg['sec_id'].map(asset_dict)
    # ── derivative fallback (universe_derivative 키워드 매칭) ──
    na_cls = sec_agg['자산군'].isna()
    for idx in sec_agg[na_cls].index:
        matched = _match_derivative_rule(
            _deriv_asset_rules,
            sec_agg.loc[idx, 'asset_gb'],
            sec_agg.loc[idx, 'ITEM_NM_pos'],
        )
        if matched:
            sec_agg.loc[idx, '자산군'] = matched
    # 나머지 fallback (asset_gb 기반)
    na_cls = sec_agg['자산군'].isna()
    for idx in sec_agg[na_cls].index:
        ag = str(sec_agg.loc[idx, 'asset_gb'])
        ccy = sec_agg.loc[idx, '노출통화']
        if ag in ('유동', '기타비용'):
            sec_agg.loc[idx, '자산군'] = '유동성및기타'
        elif '선물' in ag or '선도환' in ag:
            sec_agg.loc[idx, '자산군'] = 'FX' if ccy != 'KRW' else '유동성및기타'
        elif '주식' in ag:
            sec_agg.loc[idx, '자산군'] = '해외주식' if ccy != 'KRW' else '국내주식'
        elif '채권' in ag:
            sec_agg.loc[idx, '자산군'] = '해외채권' if ccy != 'KRW' else '국내채권'
        else:
            sec_agg.loc[idx, '자산군'] = '유동성및기타'

    # R 로직: 유동 USD 종목 → FX 재분류 (R line 591: asset_gb=="유동" & 노출통화!="KRW")
    fx_reclass_mask = (
        (sec_agg['asset_gb'] == '유동') &
        (sec_agg['노출통화'] != 'KRW') &
        (sec_agg['sec_id'] != '000000000000')
    )
    sec_agg.loc[fx_reclass_mask, '자산군'] = 'FX'

    # ── R line 342: 콜론 필터 (historical_information 구성 단계) ──
    if 'ITEM_NM_pos' in sec_agg.columns:
        콜론_mask = sec_agg['ITEM_NM_pos'].fillna('').str.contains(r'\(콜', regex=True) & (sec_agg['시가평가액'] == 0)
        sec_agg = sec_agg[~콜론_mask].copy()

    # ── STEP A (R line 351-352): SHORT 부호반전 + position_gb=NA → 시가/평가시가 = NaN ──
    # R `if_else(position_gb=="SHORT", -x, x)`: position_gb=NA이면 결과 NA.
    # Python short_mask는 NaN을 False로 평가해 건너뛰므로 NaN 전파를 명시적으로 구현.
    short_mask = sec_agg['position_gb'] == 'SHORT'
    na_pos_mask = sec_agg['position_gb'].isna()
    sec_agg.loc[short_mask, '시가평가액'] *= -1
    sec_agg.loc[short_mask, '평가시가평가액'] *= -1
    sec_agg.loc[na_pos_mask, '시가평가액'] = np.nan
    sec_agg.loc[na_pos_mask, '평가시가평가액'] = np.nan

    # ── STEP B: 총손익금액은 _agg_sec_group에서 이미 attached ──

    # ── STEP C (R line 361-362): ETF 환매 평가시가평가액보정 left_join ──
    if not etf_adj.empty:
        sec_agg = sec_agg.merge(
            etf_adj, left_on=['기준일자', 'sec_id'], right_on=['기준일자', 'item_cd'], how='left'
        )
    if '평가시가평가액보정' not in sec_agg.columns:
        sec_agg['평가시가평가액보정'] = 0.0

    # ── STEP E (R line 365): replace_na(0) for contains("시가평가액") ──
    # STEP A의 NaN 전파된 시가/평가시가도 0으로 변환
    for _c in ('시가평가액', '평가시가평가액', '평가시가평가액보정'):
        if _c in sec_agg.columns:
            sec_agg[_c] = sec_agg[_c].fillna(0)

    # ── STEP F (R line 366): position_gb coalesce → LONG ──
    sec_agg['position_gb'] = sec_agg['position_gb'].fillna('LONG')

    # ── STEP G (R line 367): 평가시가평가액 += 평가시가평가액보정 ──
    # R 프로덕션 동작: STEP G를 D보다 먼저. BA정산(trd_whl_nm="ETF발행시장환매 BA정산")일에
    # 보정 후 평가시가로 순설정액 계산해야 R Excel -5.83% 재현.
    sec_agg['평가시가평가액'] = sec_agg['평가시가평가액'] + sec_agg['평가시가평가액보정']

    # ── STEP D' (R line 363-364, 순서 수정): 순설정액 = 시가 - (총손익 + 평가시가_보정후) ──
    sec_agg['순설정액'] = sec_agg['시가평가액'] - (sec_agg['총손익금액'] + sec_agg['평가시가평가액'])
    sec_agg.loc[sec_agg['순설정액'].abs() < 100, '순설정액'] = 0
    sec_agg['순설정액'] = sec_agg['순설정액'].fillna(0)

    sec_agg.drop(columns=['item_cd', '평가시가평가액보정'], inplace=True, errors='ignore')

    # ── STEP H (R line 371-374): 조정_평가시가평가액 case_when ──
    sec_agg['조정_평가시가평가액'] = np.where(
        sec_agg['position_gb'] == 'SHORT',
        sec_agg['평가시가평가액'],
        np.where(
            (sec_agg['순설정액'] < 0) | ((sec_agg['시가평가액'] == 0) & (sec_agg['평가시가평가액'] > 0)),
            sec_agg['평가시가평가액'],
            sec_agg['시가평가액'] - sec_agg['총손익금액']
        )
    )

    # ── 5) 순자산총액(T-1) + 순설정금액 → weight_PA ──
    fi = fund_info[['기준일자', 'NAST_AMT', 'daily_return', 'MOD_STPR']].copy()
    fi['순자산총액_T1'] = fi['NAST_AMT'].shift(1).fillna(0)  # R: lag(default=0)

    sec_agg = sec_agg.merge(fi[['기준일자', '순자산총액_T1', 'daily_return']], on='기준일자', how='left')

    if not net_sub.empty:
        sec_agg = sec_agg.merge(net_sub, on='기준일자', how='left')
        sec_agg['순설정금액'] = sec_agg['순설정금액'].fillna(0)
    else:
        sec_agg['순설정금액'] = 0

    denom = sec_agg['순자산총액_T1'] + sec_agg['순설정금액']
    sec_agg['weight_PA'] = np.where(denom.abs() > 0, sec_agg['조정_평가시가평가액'] / denom, 0)

    # 순자산비중 (시가평가액 / 순자산총액)
    sec_agg = sec_agg.merge(fi[['기준일자', 'NAST_AMT']], on='기준일자', how='left', suffixes=('', '_cur'))
    sec_agg['순자산비중'] = np.where(
        sec_agg['NAST_AMT'].abs() > 0,
        sec_agg['시가평가액'] / sec_agg['NAST_AMT'],
        0
    )

    # ── 6) FX split ──
    # R 로직: 증권(유동/기타비용/선도환/미국달러 제외) vs FX(overlay+직접포지션) vs 유동성잔차

    sec_agg['종목별수익률'] = np.where(
        sec_agg['조정_평가시가평가액'].abs() > 0,
        sec_agg['총손익금액'] / sec_agg['조정_평가시가평가액'].abs(),
        0
    )

    # 시가평가액(T-1) 계산 (R: lag(시가평가액))
    # FoF: per-(sec_id, FUND_CD_holdings) 단위로 shift.
    sec_agg = sec_agg.sort_values(['sec_id', 'FUND_CD_holdings', '기준일자'], na_position='last')
    sec_agg['시가평가액_T1'] = sec_agg.groupby(
        ['sec_id', 'FUND_CD_holdings'], dropna=False
    )['시가평가액'].shift(1).fillna(0)

    if fx_split and not usdkrw.empty:
        sec_agg = sec_agg.merge(usdkrw[['기준일자', 'return_USDKRW']], on='기준일자', how='left')
        sec_agg['return_USDKRW'] = sec_agg['return_USDKRW'].fillna(0)

        # is_sec: 증권 여부 — sort/merge 후 재계산 (인덱스 정합성)
        is_sec = ~sec_agg['자산군'].isin(['FX', '유동성및기타'])

        # 증권에 대해: r_sec = (1+R_total)/(1+r_FX)-1 (내부 계산용)
        usd_sec_mask = (sec_agg['노출통화'] == 'USD') & is_sec
        sec_agg['r_sec'] = sec_agg['종목별수익률']
        sec_agg.loc[usd_sec_mask, 'r_sec'] = (
            (1 + sec_agg.loc[usd_sec_mask, '종목별수익률']) /
            (1 + sec_agg.loc[usd_sec_mask, 'return_USDKRW']) - 1
        )

        # FX 환산_adjust (R line 552, R 동일):
        # 환산_adjust = 시가평가액(T-1) * r_FX * (1 + r_sec)
        # 시가평가액(T-1)=0이면 환산_adjust=0 (종목 첫 등장일)
        sec_agg['FX효과금액'] = 0.0
        sec_agg.loc[usd_sec_mask, 'FX효과금액'] = (
            sec_agg.loc[usd_sec_mask, '시가평가액_T1'] *
            sec_agg.loc[usd_sec_mask, 'return_USDKRW'] *
            (1 + sec_agg.loc[usd_sec_mask, 'r_sec'])
        )

        # 수익률_사용 = 총손익금액_FX_adjust / 조정_평가시가평가액 (R line 561 동일)
        # 총손익금액_FX_adjust = 총손익금액 - 환산_adjust
        sec_agg['수익률_사용'] = sec_agg['종목별수익률']
        sec_agg.loc[usd_sec_mask, '수익률_사용'] = np.where(
            sec_agg.loc[usd_sec_mask, '조정_평가시가평가액'].abs() > 0,
            (sec_agg.loc[usd_sec_mask, '총손익금액'] - sec_agg.loc[usd_sec_mask, 'FX효과금액']) /
            sec_agg.loc[usd_sec_mask, '조정_평가시가평가액'].abs(),
            0
        )
    else:
        sec_agg['수익률_사용'] = sec_agg['종목별수익률']
        sec_agg['return_USDKRW'] = 0
        sec_agg['FX효과금액'] = 0

    # ── 7) 기여수익률 (일별) ──
    # 증권: 기여수익률 = 수익률_사용(FX제외) × abs(weight_PA)
    sec_agg['기여수익률_daily'] = sec_agg['수익률_사용'] * sec_agg['weight_PA'].abs()

    # FX 직접포지션: 종목별수익률 × abs(weight_PA)
    fx_direct_mask = sec_agg['자산군'] == 'FX'
    sec_agg.loc[fx_direct_mask, '기여수익률_daily'] = (
        sec_agg.loc[fx_direct_mask, '종목별수익률'] * sec_agg.loc[fx_direct_mask, 'weight_PA'].abs()
    )

    # ── 8) 분석기간 필터링 ──
    from_dt = pd.Timestamp(start_date)
    to_dt = pd.Timestamp(end_date)
    analysis = sec_agg[(sec_agg['기준일자'] >= from_dt) & (sec_agg['기준일자'] <= to_dt)].copy()

    if analysis.empty:
        logger.warning(f"[SinglePA] 분석기간 내 데이터 없음")
        return None

    fi_period = fund_info[(fund_info['기준일자'] >= from_dt) & (fund_info['기준일자'] <= to_dt)].copy()
    fi_period = fi_period.sort_values('기준일자').reset_index(drop=True)

    # is_sec 재계산 (analysis 기준)
    anal_is_sec = ~analysis['자산군'].isin(['FX', '유동성및기타'])

    # ── 9) FX 자산군 통합 구성 (R line 605-613 공식) ──
    # R 동일: 모든 USD 노출 row (증권 환산 + 유동 USD)를 sec_id="USD" 단일 sec로 통합
    # 수익률(FX) = sum(환산_adjust) / sum(|조정_평가시가평가액|)
    #   증권: 환산_adjust = FX효과금액 (곱셈분해)
    #   유동 USD: 환산_adjust = 총손익금액 전체

    # 증권 USD 노출 row 집계 (환산효과)
    _usd_sec_mask = anal_is_sec & (analysis['노출통화'] != 'KRW')
    usd_sec_agg = analysis[_usd_sec_mask].groupby('기준일자').agg(
        sec_FX효과=('FX효과금액', 'sum'),
        sec_조정시가=('조정_평가시가평가액', lambda x: x.abs().sum()),
        sec_weight_PA=('weight_PA', lambda x: x.abs().sum()),
        sec_순자산비중=('순자산비중', 'sum'),
    ).reset_index()

    # FX 자산군 직접포지션 (유동 USD 등) 집계
    fx_direct_mask_anal = analysis['자산군'] == 'FX'
    fx_direct_agg = analysis[fx_direct_mask_anal].groupby('기준일자').agg(
        direct_총손익=('총손익금액', 'sum'),
        direct_조정시가=('조정_평가시가평가액', lambda x: x.abs().sum()),
        direct_weight_PA=('weight_PA', lambda x: x.abs().sum()),
        direct_순자산비중=('순자산비중', 'sum'),
    ).reset_index()

    # denom (순자산T-1 + 순설정금액)
    denom_by_date = analysis.groupby('기준일자').agg(denom=('순자산총액_T1', 'first')).reset_index()
    if not net_sub.empty:
        denom_by_date = denom_by_date.merge(net_sub, on='기준일자', how='left')
        denom_by_date['순설정금액'] = denom_by_date['순설정금액'].fillna(0)
        denom_by_date['denom'] = denom_by_date['denom'] + denom_by_date['순설정금액']

    # USD sec 통합 (R line 605-613)
    usd_combined = fi_period[['기준일자']].merge(usd_sec_agg, on='기준일자', how='left').fillna(0)
    usd_combined = usd_combined.merge(fx_direct_agg, on='기준일자', how='left').fillna(0)
    usd_combined = usd_combined.merge(denom_by_date[['기준일자', 'denom']], on='기준일자', how='left')

    usd_combined['USD_총손익'] = usd_combined['sec_FX효과'] + usd_combined['direct_총손익']
    usd_combined['USD_조정시가'] = usd_combined['sec_조정시가'] + usd_combined['direct_조정시가']
    usd_combined['USD_weight_PA'] = usd_combined['sec_weight_PA'] + usd_combined['direct_weight_PA']
    usd_combined['USD_순자산비중'] = usd_combined['sec_순자산비중'] + usd_combined['direct_순자산비중']
    # R 공식: 수익률(FX) = sum(환산_adjust) / sum(|조정평가액|)
    usd_combined['USD_수익률'] = np.where(
        usd_combined['USD_조정시가'].abs() > 0,
        usd_combined['USD_총손익'] / usd_combined['USD_조정시가'],
        0
    )
    # 기여수익률 = 총손익 / denom
    usd_combined['USD_기여'] = np.where(
        usd_combined['denom'].abs() > 0,
        usd_combined['USD_총손익'] / usd_combined['denom'],
        0
    )

    # ── 10) 자산군별/종목별 일별 집계 (R 동일 구조) ──
    # 증권 (FX, 유동성 제외) — 기존 로직 유지 (FX효과는 이미 수익률_사용에서 제외됨)
    sec_기여 = analysis[anal_is_sec].groupby(['기준일자', 'sec_id']).agg(
        기여수익률=('기여수익률_daily', 'sum'),
        weight_PA=('weight_PA', lambda x: x.abs().sum()),
        순자산비중=('순자산비중', 'sum'),
        자산군=('자산군', 'first'),
        종목별수익률=('수익률_사용', 'first'),
    ).reset_index()

    all_sec_daily = sec_기여.merge(fi_period[['기준일자', 'daily_return']], on='기준일자', how='left')

    # 유동성잔차 = port_return - 증권기여(FX제외) - USD기여
    daily_port_ret = fi_period.set_index('기준일자')['daily_return']
    daily_sec_sum = all_sec_daily.groupby('기준일자')['기여수익률'].sum()
    usd_기여_series = usd_combined.set_index('기준일자')['USD_기여'].reindex(daily_port_ret.index, fill_value=0)
    유동성잔차 = daily_port_ret - daily_sec_sum.reindex(daily_port_ret.index, fill_value=0) - usd_기여_series

    # USD row + 유동성 row 추가
    유동성_rows = []
    usd_rows = []
    for _, r in usd_combined.iterrows():
        dt = r['기준일자']
        유동성_rows.append({
            '기준일자': dt, 'sec_id': '유동성및기타', '자산군': '유동성및기타',
            '기여수익률': 유동성잔차.get(dt, 0),
            'weight_PA': 0, '순자산비중': 0,
            '종목별수익률': 0,
            'daily_return': daily_port_ret.get(dt, 0),
        })
        if fx_split:
            usd_rows.append({
                '기준일자': dt, 'sec_id': 'USD', '자산군': 'FX',
                '기여수익률': r['USD_기여'],
                'weight_PA': r['USD_weight_PA'],
                '순자산비중': r['USD_순자산비중'],
                '종목별수익률': r['USD_수익률'],
                'daily_return': daily_port_ret.get(dt, 0),
            })

    all_sec_daily = pd.concat([
        all_sec_daily,
        pd.DataFrame(유동성_rows),
        pd.DataFrame(usd_rows) if fx_split else pd.DataFrame(),
    ], ignore_index=True)

    # ── 11) 경로의존적 누적기여도 ──
    dates_sorted = sorted(fi_period['기준일자'].unique())
    port_returns = fi_period.set_index('기준일자')['daily_return'].to_dict()

    # 기준가격 계산
    기준가격 = [1000.0]
    for dt in dates_sorted:
        기준가격.append(기준가격[-1] * (1 + port_returns.get(dt, 0)))
    기준가격 = 기준가격[1:]  # 첫 번째 1000 제거
    기준가증감 = [기준가격[0] - 1000] + [기준가격[i] - 기준가격[i-1] for i in range(1, len(기준가격))]
    cum_기준가증감 = np.cumsum(기준가증감)
    cum_return = [(g / 1000) for g in cum_기준가증감]  # = 기준가격/1000 - 1

    dt_to_idx = {dt: i for i, dt in enumerate(dates_sorted)}

    # ITEM_NM 매핑 (sec_id → 종목명) — DWPM10530 조인에서 이미 확보
    if has_holdings and 'ITEM_NM_pos' in sec_agg.columns:
        _nm = sec_agg[sec_agg['ITEM_NM_pos'].notna()].drop_duplicates('sec_id')
        item_name_dict = dict(zip(_nm['sec_id'], _nm['ITEM_NM_pos']))
    else:
        try:
            _holdings = load_fund_holdings_classified(class_m_fund)
            if _holdings is not None and not _holdings.empty:
                item_name_dict = dict(zip(_holdings['ITEM_CD'], _holdings['ITEM_NM']))
            else:
                item_name_dict = {}
        except Exception:
            item_name_dict = {}

    # 종목별 누적기여도 계산
    sec_ids = all_sec_daily['sec_id'].unique()
    result_rows = []

    for sid in sec_ids:
        sid_data = all_sec_daily[all_sec_daily['sec_id'] == sid].sort_values('기준일자')
        if sid_data.empty:
            continue

        ac = sid_data['자산군'].iloc[0]
        item_nm = item_name_dict.get(sid, sid)
        if sid == '유동성및기타':
            item_nm = '유동성및기타'
        elif sid == 'USD(FX)':
            item_nm = 'USD(FX)'

        cum_sec기여도 = 0.0
        first_date = sid_data['기준일자'].iloc[0]
        last_date = sid_data['기준일자'].iloc[-1]

        for _, row in sid_data.iterrows():
            dt = row['기준일자']
            idx = dt_to_idx.get(dt)
            if idx is None:
                continue
            port_ret = port_returns.get(dt, 0)
            contrib = row['기여수익률']
            기가증 = 기준가증감[idx]

            # sec_id기여도 = (기여수익률/port_return) × 기준가증감
            if port_ret != 0:
                sec기여도 = (contrib / port_ret) * 기가증
            else:
                sec기여도 = 0
            cum_sec기여도 += sec기여도

            # 총손익기여도 = cum_return × cumsum(sec기여도) / cumsum(기준가증감)
            if cum_기준가증감[idx] != 0:
                총손익기여도 = cum_return[idx] * cum_sec기여도 / cum_기준가증감[idx]
            else:
                총손익기여도 = 0

            result_rows.append({
                '기준일자': dt,
                '분석시작일': first_date,
                '분석종료일': last_date,
                '개별수익률': 0,  # placeholder, 아래에서 계산
                '기여수익률': 총손익기여도,
                '자산군': ac,
                '순자산비중': row['순자산비중'],
                '종목코드': sid,
                '종목명': item_nm,
                'weight_PA': row['weight_PA'],
                '기여수익률_daily': contrib,
                '종목별수익률_daily': row['종목별수익률'],
            })

    result_df = pd.DataFrame(result_rows)
    if result_df.empty:
        return None

    # ── 12) 개별수익률 (누적) ──
    # 일별 수익률로부터 누적수익률 계산
    # 증권/FX: cumprod(1+daily_return)-1
    for sid in result_df['종목코드'].unique():
        mask = result_df['종목코드'] == sid
        daily_rets = result_df.loc[mask, '종목별수익률_daily'].values
        cum_rets = np.cumprod(1 + daily_rets) - 1
        result_df.loc[mask, '개별수익률'] = cum_rets

    # ── 13) 비중 시작/끝 ──
    # R 명명:
    #   순자산비중_시작 = 분석 시작일 기준 비중 (기간 내 전 row 동일)
    #   순자산비중_종료 = 해당 기준일자의 종료 비중 (일별 변동) → Python은 '순자산비중_끝' 이름 사용
    # sec_summary(기간 요약)는 groupby.last()로 생성되므로 자동으로 최종일 값이 됨.
    for sid in result_df['종목코드'].unique():
        mask = result_df['종목코드'] == sid
        weights = result_df.loc[mask, '순자산비중'].values
        if len(weights) > 0:
            result_df.loc[mask, '순자산비중_시작'] = weights[0]
            # 일별 종료 비중 = 당일 순자산비중 (R 순자산비중_종료와 동일)
            result_df.loc[mask, '순자산비중_끝'] = weights
            result_df.loc[mask, '순자산비중_평균'] = np.mean(weights)
            result_df.loc[mask, '순비중변화'] = weights - weights[0]

    # ── 14) 출력 테이블 구성 ──
    # Sheet 4: 종목별 일별
    sec_daily_out = result_df[['기준일자', '분석시작일', '분석종료일', '개별수익률', '기여수익률',
                                '자산군', '순자산비중_시작', '순자산비중_끝', '순자산비중',
                                '종목코드', '종목명', '순비중변화']].copy()

    # Sheet 2: 종목별 요약 (마지막 행 — 비중은 종료일 기준)
    sec_summary = sec_daily_out.groupby('종목코드').last().reset_index()
    sec_summary['분석시작일'] = from_dt
    sec_summary['분석종료일'] = to_dt
    # 순자산비중 = 종료일 기준 (R Excel 출력과 동일)
    for sid in sec_summary['종목코드'].unique():
        m = result_df[result_df['종목코드'] == sid]
        sec_summary.loc[sec_summary['종목코드'] == sid, '순자산비중'] = m['순자산비중_끝'].iloc[-1] if len(m) > 0 else 0

    # Sheet 3: 자산군별 일별
    # 자산군별 개별수익률: weight 가중평균 daily return → cumprod
    asset_daily_list = []
    for ac in result_df['자산군'].unique():
        ac_data = all_sec_daily[all_sec_daily['자산군'] == ac].copy()
        if ac_data.empty:
            continue

        ac_by_date = ac_data.groupby('기준일자').agg(
            기여수익률_daily=('기여수익률', 'sum'),
            weight_PA=('weight_PA', lambda x: x.abs().sum()),
            순자산비중=('순자산비중', 'sum'),
        ).reset_index().sort_values('기준일자')

        # 자산군 개별수익률: weight 가중평균
        ac_sec = ac_data.groupby('기준일자').apply(
            lambda g: np.average(g['종목별수익률'], weights=g['weight_PA'].abs()) if g['weight_PA'].abs().sum() > 0 else 0
        ).reset_index()
        ac_sec.columns = ['기준일자', '자산군수익률_daily']
        ac_by_date = ac_by_date.merge(ac_sec, on='기준일자', how='left')
        ac_by_date['자산군수익률_daily'] = ac_by_date['자산군수익률_daily'].fillna(0)

        # 누적
        ac_by_date['개별수익률'] = np.cumprod(1 + ac_by_date['자산군수익률_daily'].values) - 1

        # 기여수익률 (path-dependent, 자산군별)
        ac_result = result_df[result_df['자산군'] == ac].groupby('기준일자').agg(
            기여수익률=('기여수익률', 'sum'),
            순자산비중=('순자산비중', 'sum'),
        ).reset_index()

        ac_by_date = ac_by_date.merge(ac_result[['기준일자', '기여수익률']], on='기준일자', how='left', suffixes=('_raw', ''))
        ac_by_date['기여수익률'] = ac_by_date['기여수익률'].fillna(0)

        weights = ac_by_date['순자산비중'].values
        asset_daily_list.append(pd.DataFrame({
            '기준일자': ac_by_date['기준일자'],
            '분석시작일': from_dt,
            '분석종료일': to_dt,
            '개별수익률': ac_by_date['개별수익률'],
            '자산군수익률_daily': ac_by_date['자산군수익률_daily'],
            '기여수익률': ac_by_date['기여수익률'],
            '자산군': ac,
            '순자산비중_시작': weights[0] if len(weights) > 0 else 0,
            '순자산비중_끝': weights[-1] if len(weights) > 0 else 0,
            '순자산비중': ac_by_date['순자산비중'],
            'weight_PA': ac_by_date['weight_PA'],
            '순비중변화': (weights[-1] - weights[0]) if len(weights) > 0 else 0,
        }))

    asset_daily_out = pd.concat(asset_daily_list, ignore_index=True) if asset_daily_list else pd.DataFrame()

    # Sheet 1: 자산군별 요약 (sec_summary에서 자산군별 합산 — 정합성 보장)
    asset_summary_list = []
    total_cum_ret = cum_return[-1] if cum_return else 0
    asset_summary_list.append({
        '자산군': '포트폴리오',
        '분석시작일': from_dt,
        '분석종료일': to_dt,
        '개별수익률': total_cum_ret,
        '기여수익률': total_cum_ret,
        '순자산비중': 1.0,
        '순비중변화': 0,
    })

    for ac in ['국내주식', '국내채권', '대체', '해외주식', '해외채권', 'FX', '유동성및기타']:
        ac_secs = sec_summary[sec_summary['자산군'] == ac] if not sec_summary.empty else pd.DataFrame()
        ac_daily = asset_daily_out[asset_daily_out['자산군'] == ac] if not asset_daily_out.empty else pd.DataFrame()
        if ac_secs.empty and ac_daily.empty:
            asset_summary_list.append({
                '자산군': ac, '분석시작일': from_dt, '분석종료일': to_dt,
                '개별수익률': 0, '기여수익률': 0, '순자산비중': 0, '순비중변화': 0,
            })
        else:
            # 기여수익률: sec_summary에서 합산 (경로의존 누적기여도, 정합성 보장)
            ac_contrib = ac_secs['기여수익률'].sum() if not ac_secs.empty else 0
            # 개별수익률, 비중: asset_daily 마지막 행 (있으면)
            if not ac_daily.empty:
                last_row = ac_daily.iloc[-1]
                ac_ret = last_row['개별수익률']
                ac_weight = last_row['순자산비중']
                ac_wchg = last_row['순비중변화']
            else:
                ac_ret = 0
                ac_weight = ac_secs['순자산비중'].sum() if not ac_secs.empty else 0
                ac_wchg = 0
            asset_summary_list.append({
                '자산군': ac, '분석시작일': from_dt, '분석종료일': to_dt,
                '개별수익률': ac_ret, '기여수익률': ac_contrib,
                '순자산비중': ac_weight, '순비중변화': ac_wchg,
            })

    asset_summary = pd.DataFrame(asset_summary_list)

    # Sheet 5: 분류현황
    classification_df = pd.DataFrame()
    try:
        conn = get_pandas_connection('solution')
        sql = """
            SELECT ISIN, classification_method, classification
            FROM universe_non_derivative
            WHERE ISIN IS NOT NULL
        """
        cls_raw = pd.read_sql(sql, conn)
        conn.close()

        # 분석 기간 sec_id들에 대해서만
        used_secs = analysis['sec_id'].unique()
        cls_filtered = cls_raw[cls_raw['ISIN'].isin(used_secs)]
        if not cls_filtered.empty:
            cls_pivot = cls_filtered.pivot_table(
                index='ISIN', columns='classification_method',
                values='classification', aggfunc='first'
            ).reset_index()
            cls_pivot.columns.name = None

            # asset_gb, 기준통화 추가
            sec_info = analysis[['sec_id', 'asset_gb', '노출통화']].drop_duplicates(subset='sec_id')
            classification_df = cls_pivot.merge(sec_info, left_on='ISIN', right_on='sec_id', how='left')
            classification_df = classification_df.drop(columns=['sec_id'], errors='ignore')
            classification_df = classification_df.rename(columns={'ISIN': 'ISIN', 'asset_gb': 'asset_gb', '노출통화': '기준통화'})
    except Exception as e:
        logger.warning(f"[SinglePA] 분류현황 로드 실패: {e}")

    logger.info(f"[SinglePA] 완료: {fund_code} {start_date}~{end_date}, "
                f"종목수={len(sec_ids)}, 자산군={asset_summary['자산군'].tolist()}")

    return {
        'asset_summary': asset_summary,
        'sec_summary': sec_summary,
        'asset_daily': asset_daily_out,
        'sec_daily': sec_daily_out,
        'classification': classification_df,
        'port_daily_returns': fi_period.set_index('기준일자')['daily_return'].copy(),
        'fund_code': fund_code,
        'class_m_fund': class_m_fund,
        'start_date': start_date,
        'end_date': end_date,
        'fx_split': fx_split,
        'mapping_method': mapping_method,
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


# ============================================================
# 결과4/5/6: 연율화수익률, 연율화위험, 무위험연율화수익률
# R benchmark: module_00_Function_v3.R (return_res_tables, weekly_calculation_Portfolio 등)
# ============================================================

def load_korea_holidays_weekday() -> set:
    """
    한국 평일 공휴일 set 반환.
    R: KOREA_holidays <- holiday_calendar %>% filter(hldy_yn=="Y") %>%
       filter(!day_ds_cd %in% c("1","7"))
    토/일(1,7)은 제외하고 평일 공휴일만.
    """
    conn = get_pandas_connection('dt')
    try:
        sql = """
            SELECT std_dt, day_ds_cd
            FROM DWCI10220
            WHERE hldy_yn = 'Y'
              AND day_ds_cd NOT IN ('1', '7')
              AND std_dt >= '20000101'
        """
        df = pd.read_sql(sql, conn)
        holidays = set(pd.to_datetime(df['std_dt'].astype(str), format='%Y%m%d'))
        return holidays
    finally:
        conn.close()


def _return_first_weekly_date(start_date: pd.Timestamp, end_date: pd.Timestamp,
                              business_days: pd.DatetimeIndex) -> pd.Timestamp:
    """
    R: return_first_weekly_date() — 주간수익률 시작일 결정.
    end_date와 같은 요일 중 start_date 이후 첫 번째 날짜를 찾되,
    (첫째주-7일, start_date] 구간에 영업일이 있으면 7일 뒤로 밀림.
    (첫 불완전 주를 건너뛰는 로직)
    """
    if pd.isna(start_date) or pd.isna(end_date):
        return pd.NaT

    target_weekday = end_date.weekday()  # 0=Mon ... 6=Sun

    # start_date 이후 같은 요일 첫 날짜
    all_days = pd.date_range(start_date, end_date, freq='D')
    same_wday = all_days[all_days.map(lambda d: d.weekday()) == target_weekday]
    if len(same_wday) == 0:
        return pd.NaT
    first_wday = same_wday[0]

    # (first_wday - 7일, start_date] 구간에 영업일이 있는지
    window_start = first_wday - pd.Timedelta(days=7)
    bdays_in_window = business_days[(business_days > window_start) & (business_days <= start_date)]
    if len(bdays_in_window) > 0:
        first_wday = first_wday + pd.Timedelta(days=7)

    return first_wday


def _build_weekly_returns(nav_series: pd.Series, dates: pd.DatetimeIndex,
                          korea_holidays: set) -> pd.DataFrame:
    """
    R: return_res_tables() 내 기준가→주간수익률 파이프라인.

    1. 기준가 = 1000 * (1 + 누적수익률) — 이미 nav_series가 기준가(MOD_STPR)
    2. 한국 평일 공휴일 → NA 처리
    3. 전체 캘린더일 pad (ffill)
    4. 요일별 group → lag(1) → 주간수익률 / 주간로그수익률

    Args:
        nav_series: 기준가 시계열 (index=날짜, values=기준가)
        dates: 원본 영업일 DatetimeIndex
        korea_holidays: 평일 공휴일 set

    Returns:
        DataFrame(기준일자, 기준가, 주간수익률, 주간로그수익률)
    """
    df = pd.DataFrame({'기준일자': dates, '기준가': nav_series.values})
    df = df.set_index('기준일자').sort_index()

    # 한국 평일 공휴일 → NA
    holiday_mask = df.index.isin(korea_holidays)
    df.loc[holiday_mask, '기준가'] = np.nan

    # 전체 캘린더일 pad + ffill
    full_range = pd.date_range(df.index.min(), df.index.max(), freq='D')
    df = df.reindex(full_range)
    df.index.name = '기준일자'
    df['기준가'] = df['기준가'].ffill()

    # 요일 칼럼
    df['weekday'] = df.index.weekday  # 0=Mon ... 6=Sun

    # 요일별 group → lag(1)
    df['lagged_기준가'] = df.groupby('weekday')['기준가'].shift(1)

    # 주간수익률 / 주간로그수익률
    df['주간수익률'] = np.where(
        df['lagged_기준가'].isna(),
        df['기준가'] / 1000 - 1,  # 첫 주 (lag 없음)
        df['기준가'] / df['lagged_기준가'] - 1
    )
    df['주간로그수익률'] = np.where(
        df['lagged_기준가'].isna(),
        np.log(df['기준가'] / 1000),
        np.log(df['기준가'] / df['lagged_기준가'])
    )

    df = df.reset_index().rename(columns={'index': '기준일자'})
    return df


def compute_annualized_metrics(fund_code: str, end_date: str,
                               start_date: str = None,
                               return_method: str = 'v3',
                               risk_method: str = 'v1',
                               annualized_factor: int = 52,
                               periods: list = None) -> dict:
    """
    결과4/5 계산: 연율화수익률 + 연율화위험.

    R: return_res_tables → weekly_calculation_Portfolio + annualized_geometric_return

    Args:
        fund_code: 펀드코드 (예: '08N81')
        end_date: 분석종료일 (YYYYMMDD 또는 YYYY-MM-DD)
        start_date: 분석시작일 (None이면 전체)
        return_method: 'v1'=주간수익률평균, 'v2'=주간로그수익률평균, 'v3'=기간수익률기하평균
        risk_method: 'v1'=주간수익률표준편차, 'v2'=주간로그수익률표준편차
        annualized_factor: 연환산 계수 (기본 52주)
        periods: 계산할 기간 리스트 (기본: ['누적','1M','3M','6M','1Y','YTD'])

    Returns:
        dict with keys: 'annualized_return', 'annualized_risk', 'period_returns'
        각 값은 {기간: 수치} dict
    """
    if periods is None:
        periods = ['누적', '1M', '3M', '6M', '1Y', 'YTD']

    end_dt = pd.Timestamp(str(end_date).replace('-', '')[:8])

    # 1) 기준가 로드
    nav_df = load_fund_nav([fund_code], start_date)
    if nav_df.empty:
        return {'annualized_return': {}, 'annualized_risk': {}, 'period_returns': {}}

    nav_df = nav_df.sort_values('기준일자')
    # T-1일에 1000 추가 (R: bind_rows로 T-1=1000 추가)
    first_date = nav_df['기준일자'].iloc[0]
    t_minus_1 = first_date - pd.Timedelta(days=1)
    row_t1 = pd.DataFrame({
        '기준일자': [t_minus_1], 'FUND_CD': [fund_code],
        'MOD_STPR': [1000.0], 'NAST_AMT': [np.nan], 'DD1_ERN_RT': [0.0],
        'STD_DT': [int(t_minus_1.strftime('%Y%m%d'))]
    })
    nav_df = pd.concat([row_t1, nav_df], ignore_index=True).sort_values('기준일자')

    # 2) 영업일 / 공휴일
    hol_df = load_holiday_calendar()
    bdays = get_business_days(hol_df)
    korea_holidays = load_korea_holidays_weekday()

    # 3) 주간수익률 빌드
    weekly_df = _build_weekly_returns(
        nav_series=nav_df.set_index('기준일자')['MOD_STPR'],
        dates=nav_df['기준일자'],
        korea_holidays=korea_holidays
    )

    # 4) 기간별 ref_date 계산
    ref_dates = _calc_ref_dates(end_dt, periods, bdays)

    # 5) 기간별 수익률 / 연율화
    results_return = {}
    results_risk = {}
    results_period_ret = {}

    # 기준가 lookup용
    price_df = weekly_df[['기준일자', '기준가']].drop_duplicates('기준일자').set_index('기준일자')

    end_price = _lookup_price(price_df, end_dt)

    for period_name, ref_date in ref_dates.items():
        if period_name == '누적':
            # 누적: 기준가 1000 대비
            ref_price = 1000.0
            ref_date = t_minus_1
        elif pd.isna(ref_date):
            results_return[period_name] = np.nan
            results_risk[period_name] = np.nan
            results_period_ret[period_name] = np.nan
            continue
        else:
            ref_price = _lookup_price(price_df, ref_date)

        if np.isnan(ref_price) or np.isnan(end_price) or ref_price == 0:
            results_return[period_name] = np.nan
            results_risk[period_name] = np.nan
            results_period_ret[period_name] = np.nan
            continue

        # 기간 수익률
        period_return = end_price / ref_price - 1
        results_period_ret[period_name] = period_return

        # 기간 캘린더 일수
        total_days = (end_dt - ref_date).days

        # 주간수익률 필터 (해당 기간, end_date와 같은 요일만)
        target_weekday = end_dt.weekday()
        first_weekly = _return_first_weekly_date(ref_date, end_dt, bdays)
        mask = (
            (weekly_df['기준일자'] <= end_dt) &
            (weekly_df['기준일자'] >= first_weekly) &
            (weekly_df['weekday'] == target_weekday)
        )
        period_weekly = weekly_df[mask]

        simple_rets = period_weekly['주간수익률'].dropna().values
        log_rets = period_weekly['주간로그수익률'].dropna().values

        # 연율화수익률
        if return_method == 'v1':
            ann_ret = np.mean(simple_rets) * annualized_factor if len(simple_rets) > 0 else np.nan
        elif return_method == 'v2':
            ann_ret = np.mean(log_rets) * annualized_factor if len(log_rets) > 0 else np.nan
        elif return_method == 'v3':
            # 기하평균: (1 + period_return)^(365.25/total_days) - 1
            if total_days > 0:
                ann_ret = (1 + period_return) ** (365.25 / total_days) - 1
            else:
                ann_ret = np.nan
        else:
            ann_ret = np.nan
        results_return[period_name] = ann_ret

        # 연율화위험
        if risk_method == 'v1':
            ann_risk = np.std(simple_rets, ddof=1) * np.sqrt(annualized_factor) if len(simple_rets) > 1 else np.nan
        elif risk_method == 'v2':
            ann_risk = np.std(log_rets, ddof=1) * np.sqrt(annualized_factor) if len(log_rets) > 1 else np.nan
        else:
            ann_risk = np.nan
        results_risk[period_name] = ann_risk

    return {
        'annualized_return': results_return,
        'annualized_risk': results_risk,
        'period_returns': results_period_ret,
    }


def _lookup_price(price_df: pd.DataFrame, target_date: pd.Timestamp) -> float:
    """기준가 DataFrame에서 target_date에 가장 가까운 값 조회 (당일 또는 이전)."""
    if target_date in price_df.index:
        return float(price_df.loc[target_date, '기준가'])
    # ffill된 데이터이므로 이전 날짜에서 찾기
    prior = price_df[price_df.index <= target_date]
    if len(prior) > 0:
        return float(prior.iloc[-1]['기준가'])
    return np.nan


def _calc_ref_dates(end_date: pd.Timestamp, periods: list,
                    business_days: pd.DatetimeIndex) -> dict:
    """
    R: return_ref_date_v2() — 기간별 기준일 계산.

    '누적': None (특수 처리)
    '1M': end_date - 1개월 이전 영업일
    'YTD': 전년말 영업일
    """
    from dateutil.relativedelta import relativedelta
    import re

    ref = {}
    for p in periods:
        if p == '누적':
            ref[p] = None  # 특수 처리: 1000 기준
        elif p == 'YTD':
            year_start = pd.Timestamp(f'{end_date.year}0101')
            prior = business_days[business_days < year_start]
            ref[p] = prior[-1] if len(prior) > 0 else pd.NaT
        elif p == 'MTD':
            month_start = pd.Timestamp(f'{end_date.year}{end_date.month:02d}01')
            prior = business_days[business_days < month_start]
            ref[p] = prior[-1] if len(prior) > 0 else pd.NaT
        elif p == '1D':
            prior = business_days[business_days < end_date]
            ref[p] = prior[-1] if len(prior) > 0 else pd.NaT
        elif p == '1W':
            target = end_date - pd.Timedelta(days=7)
            near = business_days[business_days <= target]
            ref[p] = near[-1] if len(near) > 0 else pd.NaT
        else:
            # 'nM', 'nY' 패턴 파싱
            m = re.match(r'(\d+)([MY])', p)
            if m:
                n, unit = int(m.group(1)), m.group(2)
                if unit == 'M':
                    target = end_date - relativedelta(months=n)
                else:
                    target = end_date - relativedelta(years=n)
                near = business_days[business_days <= target]
                ref[p] = near[-1] if len(near) > 0 else pd.NaT
            else:
                ref[p] = pd.NaT

    return ref


def load_rf_index_from_db(start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    무위험수익률 지수 (KIS CD Index 총수익) 로드.
    SCIP.back_datapoint dataset_id=194, dataseries_id=33
    blob의 totRtnIndex 사용 (10000 기준 → 1000 리베이스).
    """
    conn = get_pandas_connection('SCIP')
    try:
        where_parts = ["dp.dataset_id = 194", "dp.dataseries_id = 33"]
        if start_date:
            s = str(start_date).replace('-', '')[:8]
            where_parts.append(f"dp.timestamp_observation >= '{s[:4]}-{s[4:6]}-{s[6:8]}'")
        if end_date:
            e = str(end_date).replace('-', '')[:8]
            where_parts.append(f"dp.timestamp_observation <= '{e[:4]}-{e[4:6]}-{e[6:8]}'")

        sql = f"""
            SELECT DATE(dp.timestamp_observation) AS 기준일자, dp.data
            FROM back_datapoint dp
            WHERE {' AND '.join(where_parts)}
            ORDER BY dp.timestamp_observation
        """
        df = pd.read_sql(sql, conn)
        if df.empty:
            logger.warning("KIS CD Index 데이터 없음")
            return pd.DataFrame()

        df['기준일자'] = pd.to_datetime(df['기준일자'])
        df['기준가'] = df['data'].apply(lambda b: float(
            json.loads(b.decode('utf-8') if isinstance(b, (bytes, bytearray)) else b)['totRtnIndex']
        ))
        # 10000 기준 → 1000 리베이스
        df['기준가'] = df['기준가'] / 10

        # 전체 캘린더일 pad + ffill
        full_range = pd.date_range(df['기준일자'].min(), df['기준일자'].max(), freq='D')
        df = df[['기준일자', '기준가']].set_index('기준일자').reindex(full_range).ffill().reset_index()
        df = df.rename(columns={'index': '기준일자'})

        return df[['기준일자', '기준가']]
    except Exception as e:
        logger.error(f"KIS CD Index 로드 실패: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


def compute_rf_annualized_metrics(end_date: str, start_date: str = None,
                                  return_method: str = 'v3',
                                  risk_method: str = 'v1',
                                  annualized_factor: int = 52,
                                  periods: list = None) -> dict:
    """
    결과6: 무위험 연율화수익률 계산.
    R: weekly_calculation_Risk_free + annualized_geometric_return

    ECOS CD(91일) 복리지수 → 주간수익률 → 연율화.
    """
    if periods is None:
        periods = ['누적', '1M', '3M', '6M', '1Y', 'YTD']

    end_dt = pd.Timestamp(str(end_date).replace('-', '')[:8])

    # RF 지수 로드
    rf_df = load_rf_index_from_db(start_date, end_date)
    if rf_df.empty:
        return {'annualized_return': {}, 'annualized_risk': {}}

    # 영업일 / 공휴일
    hol_df = load_holiday_calendar()
    bdays = get_business_days(hol_df)
    korea_holidays = load_korea_holidays_weekday()

    # 주간수익률 빌드 (RF 지수에 대해)
    weekly_df = _build_weekly_returns(
        nav_series=rf_df.set_index('기준일자')['기준가'],
        dates=rf_df['기준일자'],
        korea_holidays=korea_holidays
    )

    # 기간별 ref_date
    ref_dates = _calc_ref_dates(end_dt, periods, bdays)

    # 기준가 lookup
    price_df = weekly_df[['기준일자', '기준가']].drop_duplicates('기준일자').set_index('기준일자')
    end_price = _lookup_price(price_df, end_dt)

    results_return = {}
    results_risk = {}

    for period_name, ref_date in ref_dates.items():
        if period_name == '누적':
            # 누적: start 시점 기준가 사용
            if start_date:
                s_dt = pd.Timestamp(str(start_date).replace('-', '')[:8])
            else:
                s_dt = weekly_df['기준일자'].iloc[0]
            ref_price = _lookup_price(price_df, s_dt)
            ref_date = s_dt
        elif pd.isna(ref_date):
            results_return[period_name] = np.nan
            results_risk[period_name] = np.nan
            continue
        else:
            ref_price = _lookup_price(price_df, ref_date)

        if np.isnan(ref_price) or np.isnan(end_price) or ref_price == 0:
            results_return[period_name] = np.nan
            results_risk[period_name] = np.nan
            continue

        period_return = end_price / ref_price - 1
        total_days = (end_dt - ref_date).days

        # 주간수익률 필터
        target_weekday = end_dt.weekday()
        first_weekly = _return_first_weekly_date(ref_date, end_dt, bdays)
        mask = (
            (weekly_df['기준일자'] <= end_dt) &
            (weekly_df['기준일자'] >= first_weekly) &
            (weekly_df['weekday'] == target_weekday)
        )
        period_weekly = weekly_df[mask]

        simple_rets = period_weekly['주간수익률'].dropna().values
        log_rets = period_weekly['주간로그수익률'].dropna().values

        # 연율화수익률
        if return_method == 'v3' and total_days > 0:
            ann_ret = (1 + period_return) ** (365.25 / total_days) - 1
        elif return_method == 'v1' and len(simple_rets) > 0:
            ann_ret = np.mean(simple_rets) * annualized_factor
        elif return_method == 'v2' and len(log_rets) > 0:
            ann_ret = np.mean(log_rets) * annualized_factor
        else:
            ann_ret = np.nan
        results_return[period_name] = ann_ret

        # 연율화위험
        if risk_method == 'v1' and len(simple_rets) > 1:
            ann_risk = np.std(simple_rets, ddof=1) * np.sqrt(annualized_factor)
        elif risk_method == 'v2' and len(log_rets) > 1:
            ann_risk = np.std(log_rets, ddof=1) * np.sqrt(annualized_factor)
        else:
            ann_risk = np.nan
        results_risk[period_name] = ann_risk

    return {
        'annualized_return': results_return,
        'annualized_risk': results_risk,
    }


def compute_sharpe_ratio(annualized_return: float, annualized_risk: float,
                         rf_annualized_return: float) -> float:
    """샤프 비율 = (연율화수익률 - 무위험연율화수익률) / 연율화위험"""
    if annualized_risk is None or np.isnan(annualized_risk) or annualized_risk == 0:
        return np.nan
    if any(np.isnan(x) for x in [annualized_return, rf_annualized_return]):
        return np.nan
    return (annualized_return - rf_annualized_return) / annualized_risk


def compute_full_performance_stats(fund_code: str, end_date: str,
                                   start_date: str = None,
                                   return_method: str = 'v3',
                                   risk_method: str = 'v1',
                                   periods: list = None) -> dict:
    """
    결과4+5+6 통합 계산.
    연율화수익률, 연율화위험, 무위험연율화수익률, 샤프비율을 한번에 반환.

    Returns:
        {
            'periods': {기간: {
                'annualized_return': float,
                'annualized_risk': float,
                'rf_annualized_return': float,
                'sharpe_ratio': float,
                'period_return': float
            }}
        }
    """
    fund_metrics = compute_annualized_metrics(
        fund_code, end_date, start_date,
        return_method=return_method, risk_method=risk_method,
        periods=periods
    )
    rf_metrics = compute_rf_annualized_metrics(
        end_date, start_date,
        return_method=return_method, risk_method=risk_method,
        periods=periods
    )

    all_periods = periods or ['누적', '1M', '3M', '6M', '1Y', 'YTD']
    result = {}
    for p in all_periods:
        ann_ret = fund_metrics['annualized_return'].get(p, np.nan)
        ann_risk = fund_metrics['annualized_risk'].get(p, np.nan)
        rf_ret = rf_metrics['annualized_return'].get(p, np.nan)
        period_ret = fund_metrics['period_returns'].get(p, np.nan)

        result[p] = {
            'annualized_return': ann_ret,
            'annualized_risk': ann_risk,
            'rf_annualized_return': rf_ret,
            'sharpe_ratio': compute_sharpe_ratio(ann_ret, ann_risk, rf_ret),
            'period_return': period_ret,
        }

    return {'periods': result}
