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
import time
import functools
from modules import db_cache
warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)


# ============================================================
# 인메모리 TTL 캐시 (FastAPI 로딩 단축용 — 외부 의존성 없음)
# 데이터는 EOD 1회 갱신 + 캐시 키에 날짜 포함 → 일자 변경 시 자동 무효.
# ============================================================
_CACHE_TTL = 21600  # 6시간


def _ttl_cache(ttl: int = _CACHE_TTL):
    def deco(fn):
        store: dict = {}

        @functools.wraps(fn)
        def wrap(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            hit = store.get(key)
            if hit is not None and (now - hit[0]) < ttl:
                return hit[1]
            val = fn(*args, **kwargs)
            store[key] = (now, val)
            return val

        wrap.cache_clear = store.clear
        return wrap
    return deco

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

@_ttl_cache()
def load_holiday_calendar() -> pd.DataFrame:
    """한국 공휴일/영업일 캘린더 로드 (펀드무관·무인자, 호출처는 필터만 → 캐싱 안전. TTL 6h)"""
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
                   AST_CLSF_CD_NM, CURR_DS_CD, POS_DS_CD,
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


# ============================================================
# 펀드 PA 원천 데이터
# R benchmark: dt.MA000410 → get_PA_source_data()
# ============================================================

@_ttl_cache()
def load_pa_source(fund_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    펀드 PA 원천 데이터 로드 (확장).
    R: get_PA_source_data(fund_cd, start_date, end_date)

    Phase 4: position_gb, pl_gb, crrncy_cd, os_gb 추가.

    캐시: brinson 최대 병목(MA000410, ~9.6s/콜). 유일 호출처(compute_single_port_pa)가
    결과를 즉시 필터+copy(2764) 하므로 원본 mutation 없음 → (fund,start,end) 키 캐싱 안전.
    같은 날짜범위에서 분류/FX/SAA 토글 시 재조회 생략. (TTL 6h)
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


def _derive_trade_side(bs, tr_nm: str) -> str:
    """거래 방향 라벨. buy_sell_ds_cd(M/D) 우선, 없으면 거래코드명(tr_nm)으로 판별.

    - M→매수, D→매도
    - 환전(외화매입/매도원화) → '환전'
    - ETF발행시장매입 BA정산 → '발행(BA정산)', 발행시장환매 → '환매(BA정산)'
    - 선물 포지션(신규매수/신규매도/환매수/전매도) → 해당 라벨
    - 그 외 → '기타'
    """
    if bs == 'M':
        return '매수'
    if bs == 'D':
        return '매도'
    trn = str(tr_nm or '')
    if '환전' in trn:
        return '환전'
    if '발행시장매입' in trn:
        return '발행(BA정산)'
    if '발행시장환매' in trn:
        return '환매(BA정산)'
    for kw in ['신규매수', '신규매도', '환매수', '전매도']:
        if kw in trn:
            return kw
    return '기타'


def load_fund_trade_detail(fund_code: str, start_date: int, end_date: int) -> pd.DataFrame:
    """DWPM10520에서 날짜별 거래내역 상세. 자산군 분류 + 거래코드(DWCI10160) 라벨 포함.

    Returns: DataFrame [날짜, 종목명, 자산군, 매수매도, 금액(억), item_cd]
    """
    def _fetch(lo, hi):
        conn = get_pandas_connection('dt')
        try:
            return pd.read_sql("""
                SELECT t.std_dt, t.item_cd, t.item_nm, t.curr_ds_cd,
                       t.buy_sell_ds_cd, t.trd_amt, t.stl_amt, t.krw_stl_amt,
                       t.tr_cd, c.tr_nm
                FROM DWPM10520 t
                LEFT JOIN DWCI10160 c ON t.tr_cd = c.tr_cd AND t.synp_cd = c.synp_cd
                WHERE t.fund_cd = %s AND t.std_dt BETWEEN %s AND %s
                  AND t.imc_cd = '003228'
                ORDER BY t.std_dt, t.item_nm
            """, conn, params=[fund_code, str(lo), str(hi)])
        finally:
            conn.close()

    # 과거 거래는 불변 → SQLite 영속 캐시(최근 N영업일만 재조회)
    df = db_cache.get_cached_range(db_cache.TRADES, fund_code,
                                   int(start_date), int(end_date), _fetch)

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
    df['매수매도'] = df.apply(lambda r: _derive_trade_side(r['buy_sell_ds_cd'], r['tr_nm']), axis=1)
    # 매매금액 원화 환산: 해외통화(USD/HKD/EUR/…)는 trd_amt 가 외화단위 → 실제 체결환율
    # (원화결제금액/외화결제금액)로 환산. 국내(KRW/NULL)는 trd_amt 가 이미 원화라 그대로.
    # 결제금액=0(예수금 등 정산성)인 해외행은 원화결제금액을 직접 사용.
    trd = pd.to_numeric(df['trd_amt'], errors='coerce').fillna(0.0)
    stl = pd.to_numeric(df['stl_amt'], errors='coerce').fillna(0.0)
    krw_stl = pd.to_numeric(df['krw_stl_amt'], errors='coerce').fillna(0.0)
    is_fx = ~df['curr_ds_cd'].astype(str).str.upper().isin(['KRW', '', 'NAN', 'NONE'])
    rate = (krw_stl / stl.where(stl != 0)).fillna(0.0)
    krw_amt = trd.copy()
    krw_amt[is_fx] = (trd * rate)[is_fx]
    fallback = is_fx & (stl == 0)
    krw_amt[fallback] = krw_stl[fallback]
    df['금액(억)'] = krw_amt / 1e8
    df['날짜'] = df['std_dt'].astype(str)
    df['종목명'] = df['item_nm']

    return df[['날짜', '종목명', '자산군', '매수매도', '금액(억)', 'item_cd']].round(2)


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
        """, conn, params=[fund_code, str(date)])  # std_dt=varchar(8): int이면 인덱스 미사용 full scan(~9.8s)
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

# universe(방법3) 분류 → 거래내역/보유 6분류 매핑
_UNIVERSE_6CLASS = {
    '국내주식': '국내주식', '해외주식': '해외주식',
    '국내채권': '국내채권', '해외채권': '해외채권',
    '대체': '대체투자', 'FX': 'FX', '유동성및기타': '유동성',
}


@_ttl_cache()
def _load_universe_class_map() -> dict:
    """solution.universe_non_derivative 방법3 → {ISIN: 6class}. 자산군 source of truth.

    거래내역은 AST_CLSF_CD_NM 이 비어(='') 들어와 _classify_6class 휴리스틱이 KR상장
    해외 ETF(예: ACE 미국S&P500)를 유동성으로 오분류 → universe DB 로 1순위 보정.
    조회 실패 시 빈 dict (휴리스틱 fallback)."""
    try:
        conn = get_pandas_connection('solution')
        try:
            df = pd.read_sql(
                "SELECT ISIN, classification FROM universe_non_derivative "
                "WHERE classification_method='방법3' AND ISIN IS NOT NULL", conn)
        finally:
            conn.close()
    except Exception:
        return {}
    out = {}
    for _, r in df.iterrows():
        isin = str(r['ISIN']).strip()
        cls = _UNIVERSE_6CLASS.get(str(r['classification']).strip())
        if isin and cls:
            out[isin] = cls
    return out


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

    # universe DB(방법3) source of truth — 수동 override/name 패턴 다음, 휴리스틱 이전.
    ucls = _load_universe_class_map().get(item_cd)
    if ucls:
        return ucls

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
    # AST_CLSF_CD_NM 기준 우선 (예: '달러선물', '통화선물', '선물환')
    if any(kw in ast for kw in ['달러선물', '통화선물', '선물환', 'FX FORWARD']):
        return 'FX'
    if any(kw in item_nm for kw in ['달러선물', '달러 선물', '미국달러 F', 'USD F', 'USD선물', 'NDF', '통화선물', 'FX FORWARD']):
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


@_ttl_cache()
def _load_fund_holdings_classified_cached(fund_code: str, date: str = None) -> pd.DataFrame:
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


def load_fund_holdings_classified(fund_code: str, date: str = None) -> pd.DataFrame:
    """`_load_fund_holdings_classified_cached`의 공개 래퍼.
    TTL 캐시된 DataFrame을 호출자가 in-place로 변형해 캐시를 오염시키지 않도록
    항상 copy를 반환한다."""
    df = _load_fund_holdings_classified_cached(fund_code, date)
    return df.copy() if isinstance(df, pd.DataFrame) else df


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


@_ttl_cache()
def _load_fund_holdings_lookthrough_cached(fund_code: str, date: str = None) -> pd.DataFrame:
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


def load_fund_holdings_lookthrough(fund_code: str, date: str = None) -> pd.DataFrame:
    """`_load_fund_holdings_lookthrough_cached`의 공개 래퍼.
    캐시 오염 방지를 위해 항상 copy를 반환한다."""
    df = _load_fund_holdings_lookthrough_cached(fund_code, date)
    return df.copy() if isinstance(df, pd.DataFrame) else df


# ============================================================
# NAV + AUM 시계열 (확장)
# ============================================================

# 설정후 수익률 계산용 설정일 기준가 (시스템 일치용)
_FUND_INCEPTION_BASE = {
    '4JM12': 1970.76,  # 시스템 설정후 수익률 기준가
}


@_ttl_cache()
def _load_fund_nav_with_aum_cached(fund_code: str, start_date: str = None) -> pd.DataFrame:
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


def load_fund_nav_with_aum(fund_code: str, start_date: str = None) -> pd.DataFrame:
    """`_load_fund_nav_with_aum_cached`의 공개 래퍼.
    캐시 오염 방지를 위해 항상 copy를 반환한다."""
    df = _load_fund_nav_with_aum_cached(fund_code, start_date)
    return df.copy() if isinstance(df, pd.DataFrame) else df


@_ttl_cache()
def load_fund_meta(fund_code: str) -> dict:
    """펀드 기본정보(정적) — Overview 메타바용.

    KSD 표준코드(ticker 대용)·설정일·펀드타입·운용사·총보수(bp).
    소스: DWPI10011(펀드 마스터) + BOS3203(보수 컴포넌트 합). OCIO 사모펀드라
    협회 공시(ST_KITCA_DS)·거래소 티커(DWPI10021)엔 데이터 없음 → KSD코드로 대체.
    NAV(기준가)·설정액(순자산)은 nav_df 최신값을 서비스단에서 채움.
    """
    out = {'ticker': None, 'inception': None, 'fund_type': None,
           'manager': '한국투자신탁운용', 'fee_bp': None}
    try:
        conn = get_pandas_connection('dt')
        try:
            m = pd.read_sql(
                "SELECT KSD_ITEM_CD, FRST_OPNG_DT, PBOF_PROFF_DS_CD, TRST_DS_CD "
                "FROM DWPI10011 WHERE FUND_CD=%s AND IMC_CD='003228' LIMIT 1",
                conn, params=[fund_code])
            if len(m):
                r = m.iloc[0]
                out['ticker'] = str(r['KSD_ITEM_CD']).strip() or None if r['KSD_ITEM_CD'] else None
                fo = str(r['FRST_OPNG_DT'] or '').strip()
                out['inception'] = fo if len(fo) == 8 and fo.isdigit() else None
                parts = [str(r['PBOF_PROFF_DS_CD'] or '').strip(), str(r['TRST_DS_CD'] or '').strip()]
                out['fund_type'] = ' · '.join([p for p in parts if p]) or None
            fee = pd.read_sql(
                "SELECT fee_rate_bp, apply_frdate FROM BOS3203 WHERE fund_cd=%s "
                "ORDER BY apply_frdate DESC", conn, params=[fund_code])
            if len(fee):
                latest = fee.iloc[0]['apply_frdate']
                out['fee_bp'] = round(float(fee[fee['apply_frdate'] == latest]['fee_rate_bp'].sum()), 3)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(f"[load_fund_meta] {fund_code} 실패: {exc}")
    return out


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

    # ex_KR 컴포넌트 환산용 USDKRW (SCIP 31/6, 관측일=한국 영업일).
    # Brinson BM 경로(_load_bm_daily_returns_by_class)와 동일 관례 — unhedged 는
    # 외화가격(T-1) × USDKRW(T), hedged 는 T-1 shift 만. 미반영 시 unhedged 외화 비중만큼
    # SAA/BM 수익률이 과소 계상 (2026-07-03 08N33: SAA YTD +1.29% vs Brinson +4.07% 확인).
    _fx = None
    if any(c.get('region') == 'ex_KR' for c in components):
        _fx_df = load_scip_bm_prices(31, 6, start_date, 'USD')
        if not _fx_df.empty and len(_fx_df) >= 2:
            _fx_s = _fx_df.set_index('기준일자').sort_index()
            _fx = _fx_s[~_fx_s.index.duplicated(keep='last')]['value']

    # 각 component 시계열 로드
    comp_series = {}
    for comp in components:
        _is_ex_kr = comp.get('region') == 'ex_KR' and _fx is not None
        _hedged = bool(comp.get('hedged', False))
        _cur = 'USD' if (_is_ex_kr and not _hedged) else comp.get('currency')
        df = load_scip_bm_prices(
            comp['dataset_id'], comp['dataseries_id'],
            start_date, _cur
        )
        if df.empty or len(df) < 2:
            logger.warning(f"복합BM component 데이터 부족: {comp.get('name', comp['dataset_id'])}")
            continue
        df = df.set_index('기준일자').sort_index()
        # 동일 날짜 중복 제거 (마지막 값 유지)
        df = df[~df.index.duplicated(keep='last')]
        ser = df['value']
        if _is_ex_kr:
            # 한국 영업일(USDKRW 관측일) 캘린더 정렬 + T-1 shift(해외 종가 시차),
            # unhedged 는 당일 환율 곱해 KRW 환산
            ser = ser.reindex(_fx.index).ffill().shift(1)
            if not _hedged:
                ser = ser * _fx
            ser = ser.dropna()
            if len(ser) < 2:
                logger.warning(f"복합BM component 환산 후 데이터 부족: {comp.get('name', comp['dataset_id'])}")
                continue
        comp_series[comp['name']] = {'returns': ser.pct_change(), 'weight': comp['weight']}

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
# Brinson PA 계산
# ============================================================

BRINSON_METHOD_CLASSES = {
    '방법1': ['주식', '채권', '대체', 'FX', '유동성및기타'],
    '방법2': ['주식', '채권', 'FX', '유동성및기타'],
    '방법3': ['국내주식', '해외주식', '국내채권', '해외채권', '대체', 'FX', '유동성및기타'],
    '방법4': ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성및기타'],
}

BRINSON_METHOD_BM_CLASSES = {
    '방법1': ['주식', '채권', '대체', 'FX', '유동성'],
    '방법2': ['주식', '채권', 'FX', '유동성'],
    '방법3': ['국내주식', '해외주식', '국내채권', '해외채권', '대체', 'FX', '유동성'],
    '방법4': ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성'],
}


def _collapse_asset_class(ac: str, method: str) -> str:
    """방법3/4 라벨을 방법1/2 라벨로 축소.

    방법1: 대체 유지, 국내/해외 병합
    방법2: 대체를 주식에 흡수, 국내/해외 병합
    """
    if method in ('방법3', '방법4') or ac is None:
        return ac
    if ac in ('국내주식', '해외주식'):
        return '주식'
    if ac in ('국내채권', '해외채권'):
        return '채권'
    if ac == '대체':
        return '주식' if method == '방법2' else '대체'
    return ac  # FX / 유동성 / 유동성및기타 / 그외


def _map_bm_component_to_asset_class(comp_name: str, method: str = '방법3') -> str:
    """BM 컴포넌트명 → 자산군 매핑 (방법별 분기).

    방법3/4는 국내/해외 분리. 방법1/2는 주식/채권으로 병합.
    방법2는 대체도 주식으로 흡수.
    """
    nm = comp_name.upper()
    if 'KOSPI' in nm:
        base = '국내주식'
    elif ('KIS' in nm or 'KAP' in nm) and ('CALL' in nm or 'MONEY' in nm):
        base = '유동성'
    elif 'KIS' in nm or 'KAP' in nm:
        base = '국내채권'
    elif 'KOREA' in nm and 'BOND' not in nm:
        # MSCI Korea 계열(KODEX MSCI Korea TR 등) — 'MSCI' 패턴보다 먼저 국내주식 판정
        base = '국내주식'
    elif 'BLOOMBERG' in nm or 'AGG' in nm:
        base = '해외채권'
    elif 'GOLD' in nm:
        base = '대체'
    elif 'HIGH YIELD' in nm or 'HIGH-YIELD' in nm:
        base = '해외채권'
    elif 'GOVERNMENT BOND' in nm or 'GOVT BOND' in nm or ('EMERGING' in nm and 'BOND' in nm):
        base = '해외채권'
    elif any(k in nm for k in ['MSCI', 'S&P', 'ACWI']):
        base = '해외주식'
    else:
        base = '해외주식'
    return _collapse_asset_class(base, method)


def _load_bm_daily_returns_by_class(bm_info: dict, start_date: str, end_date: str,
                                     asset_classes_8: list,
                                     mapping_method: str = '방법3',
                                     fx_split: bool = True) -> tuple:
    """
    BM 컴포넌트 일별 수익률 → 자산군별 집계.

    Args:
        mapping_method: '방법1'~'방법4' (자산군 분류 방법)
        fx_split: True 면 unhedged ex_KR 환효과를 별도 FX 자산군으로 분리(해외주식=stock_ret).
                  False('FX 포함') 면 오버레이 스킵 → 해외주식 BM 이 환효과 포함 원수익률 유지,
                  FX 자산군 없음 (AP 측 compute_single_port_pa(fx_split=False) 와 대칭).

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
    _bm_fx_weight = 0.0  # FX 오버레이 비중 (unhedged ex_KR 해외주식 BM만)
    # FX 오버레이는 방법 공통 — 방법1/2는 '주식'이 ex_KR unhedged 해외주식 포함
    _stock_class_unhedged = '주식' if mapping_method in ('방법1', '방법2') else '해외주식'
    for comp in components:
        ac = _map_bm_component_to_asset_class(comp['name'], mapping_method)
        if ac not in bm_weights:
            bm_weights[ac] = 0.0
        bm_weights[ac] += comp['weight'] * 100
        comp_class_map[comp['name']] = ac
        # ex_KR unhedged만 FX 오버레이 기여
        if ac == _stock_class_unhedged and not comp.get('hedged', False) and comp.get('region') == 'ex_KR':
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
    if fx_split and _bm_fx_weight > 0 and _fx_on_kr_ret is not None:
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


@_ttl_cache()
def load_saa_components(fund_code: str, as_of_date=None) -> dict:
    """solution.saa_bm_components 에서 SAA 벤치마크 컴포넌트 로드 (리밸 날짜 버전형).

    as_of_date(YYYYMMDD/YYYY-MM-DD/date) 이하 최신 리밸런싱 적용(없으면 최초/최신).
    Returns: {'components': [{dataset_id,dataseries_id,weight(fraction),name,region,hedged,currency}]}
             — FUND_BM 와 동일 구조라 compute 의 bm_info 로 그대로 사용. 없으면 None.
    """
    import datetime as _dt
    aod = None
    if as_of_date is not None:
        s = str(as_of_date).replace('-', '')
        if len(s) >= 8:
            try:
                aod = _dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            except ValueError:
                aod = None
    try:
        conn = get_pandas_connection('solution')
        try:
            df = pd.read_sql(
                "SELECT rebal_date, dataset_id, dataseries_id, region, weight, "
                "hedge_ratio, name FROM saa_bm_components WHERE fund_cd=%s "
                "ORDER BY rebal_date", conn, params=[fund_code])
        finally:
            conn.close()
    except Exception:
        return None
    if df.empty:
        return None
    df['rebal_date'] = pd.to_datetime(df['rebal_date']).dt.date
    rebals = sorted(set(df['rebal_date']))
    if aod is not None:
        applicable = [r for r in rebals if r <= aod]
        pick = applicable[-1] if applicable else rebals[0]
    else:
        pick = rebals[-1]
    sub = df[df['rebal_date'] == pick]
    comps = []
    for _, r in sub.iterrows():
        region = str(r['region'] or 'KR')
        comps.append({
            'dataset_id': int(r['dataset_id']),
            'dataseries_id': int(r['dataseries_id']),
            'weight': float(r['weight']) / 100.0,
            'name': str(r['name']),
            'region': region,
            'hedged': bool(int(r['hedge_ratio'] or 0)),
            'currency': 'USD' if region == 'ex_KR' else 'KRW',
        })
    return {'components': comps} if comps else None


def _is_risk_bond_name(nm) -> bool:
    """안전자산 제외 대상 채권: HY(하이일드) + EM 국공채(VWOB 등)."""
    u = str(nm).upper()
    return ('HIGH YIELD' in u or 'HIGH-YIELD' in u or ' HY ' in f' {u} ' or '하이일드' in str(nm)
            or 'EMERGING' in u or 'VWOB' in u)


@_ttl_cache()
def _build_proxy_bm_info(fund_code: str, start_yyyymmdd: str) -> dict:
    """SAA proxy 벤치마크: 안전자산(채권 ex-HY·EM) → KAP All, 나머지 → MSCI ACWI.

    비중(2026-07-03 사용자 지시): **등록 SAA(saa_bm_components) 리밸 비중을 주식/채권으로
    매핑한 고정 비중** 사용 (예: 08P22 = 채권 75.8 / 주식 24.2). HY·EM 채권 컴포넌트는
    위험자산(ACWI 측)으로 분류. 등록 SAA 없는 펀드만 기존 '기간 시작일 AP 보유 기준'
    동적 계산 fallback 유지.
    안전자산 인덱스 = KAP All (dataset 257/ds 9) — 2026-07-03 사용자 지시로 KIS 종합채권
    (188/33, 2026-06-23 지시)에서 재변경 (R 프로덕션 08P22_BM 기준 일치).
    MSCI ACWI 는 ex_KR(T-1×USDKRW, biz_day_adj=-1) — BM 경로가 자동 처리.
    """
    sw = None
    # 1순위: 등록 SAA 리밸 비중 → 주식/채권 고정 비중
    try:
        saa = load_saa_components(fund_code, start_yyyymmdd)
    except Exception:
        saa = None
    if saa and saa.get('components'):
        tot = sum(float(c.get('weight', 0.0)) for c in saa['components'])
        safe = 0.0
        for c in saa['components']:
            ac = _map_bm_component_to_asset_class(str(c.get('name', '')), '방법3')
            if ac in ('국내채권', '해외채권') and not _is_risk_bond_name(c.get('name', '')):
                safe += float(c.get('weight', 0.0))
        if tot > 0:
            sw = max(0.0, min(1.0, safe / tot))

    # fallback: 기간 시작일 AP 보유 기준 (등록 SAA 없는 펀드)
    if sw is None:
        base = datetime.strptime(str(start_yyyymmdd), '%Y%m%d')
        df = None
        # 시작일(휴일이면 직전 영업일), 없으면 앞쪽(설정일까지 ~45일) 탐색.
        # 설정 직후 현금 100%·정산 과도기 스냅샷은 건너뛰고 '투자 개시'(비유동성 비중
        # 충분 + 유동성 과도분 적음) 첫 날을 사용 → 안전자산 비중이 0 으로 잡히는 문제 방지.
        offsets = [0] + [-i for i in range(1, 8)] + list(range(1, 46))
        for off in offsets:
            d = (base + timedelta(days=off)).strftime('%Y%m%d')
            try:
                cand = load_fund_holdings_weight(fund_code, str(d))
            except Exception:
                cand = None
            if cand is None or cand.empty:
                continue
            invested = cand[~cand['자산군'].isin(['유동성', 'FX'])]['비중(%)'].sum()
            liq = cand[cand['자산군'] == '유동성']['비중(%)'].sum()
            if invested >= 50 and liq <= 30:  # 투자 개시 + 정산 과도기 아님
                df = cand
                break
        if df is None or df.empty:
            return None
        safe = 0.0
        for _, r in df.iterrows():
            ac = r['자산군']
            w = float(r['비중(%)'])
            if ac == '국내채권':
                safe += w
            elif ac == '해외채권' and not _is_risk_bond_name(r['종목명']):
                safe += w
        sw = max(0.0, min(100.0, safe)) / 100.0

    return {'components': [
        {'dataset_id': 257, 'dataseries_id': 9, 'weight': sw,
         'name': 'KAP Korea Bond Pricing All Bonds Index',
         'region': 'KR', 'hedged': False, 'currency': 'KRW'},
        {'dataset_id': 35, 'dataseries_id': 15, 'weight': 1.0 - sw,
         'name': 'MSCI ACWI Index', 'region': 'ex_KR', 'hedged': False, 'currency': 'USD'},
    ]}


def compute_brinson_attribution_v2(fund_code: str,
                                   start_date: str, end_date: str,
                                   asset_classes: list = None,
                                   mapping_method: str = '방법3',
                                   saa_mode: str = 'auto',
                                   fx_split: bool = True) -> dict:
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

    Returns: dict (기존 v1과 호환되는 keys)
    """
    if asset_classes is None:
        asset_classes = BRINSON_METHOD_CLASSES.get(mapping_method,
            ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성및기타'])

    start_date = str(start_date)
    end_date = str(end_date)

    # ── 1) Single PA 호출 (R PA_from_MOS exact) ──
    single_pa = compute_single_port_pa(
        fund_code, start_date, end_date,
        fx_split=fx_split, mapping_method=mapping_method,
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
    if saa_mode in ('proxy', 'proxy_drift'):
        # SAA proxy(안전자산→KIS 종합채권 / 나머지→MSCI ACWI). proxy_drift 는 비중만 일별 변동.
        bm_info = _build_proxy_bm_info(fund_code, start_date)
    else:
        bm_info = FUND_BM.get(fund_code)
        if bm_info is None:
            # BM 미설정 펀드 → SAA 벤치마크(solution.saa_bm_components) 시도.
            # 컴포넌트가 있으면 BM 과 동일 경로로 SAA 수익률/기여 분해.
            bm_info = load_saa_components(fund_code, end_date)

    _BM_ASSET_CLASSES = BRINSON_METHOD_BM_CLASSES.get(mapping_method,
        ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성'])
    bm_weights_raw = {ac: 0.0 for ac in _BM_ASSET_CLASSES}
    bm_daily_df = pd.DataFrame()

    if bm_info:
        _sd_dt = pd.Timestamp(f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}")
        _bm_warmup_start = (_sd_dt - timedelta(days=45)).strftime('%Y%m%d')
        bm_weights_raw, bm_daily_df, _ = _load_bm_daily_returns_by_class(
            bm_info, _bm_warmup_start, end_date, _BM_ASSET_CLASSES, mapping_method,
            fx_split=fx_split)

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

    # 일별 BM 비중(fraction). fixed=고정 broadcast(constant-mix, =기존 스칼라와 동일).
    # drift=buy-and-hold: 리밸 target 에서 각 인덱스 누적수익률대로 비중 표류.
    bm_w_daily = {ac: pd.Series(bm_weights.get(ac, 0) / 100.0, index=dates_idx)
                  for ac in asset_classes}
    if saa_mode.endswith('_drift') and bm_available:
        _cum_prev = {}
        for ac in bm_daily_df.columns:
            _cum_prev[ac] = (1 + bm_daily_df[ac]).cumprod().shift(1).fillna(1.0)
        _eq = '주식' if mapping_method in ('방법1', '방법2') else '해외주식'
        # 펀드(funded) 자산 = FX 오버레이 제외, target>0
        _funded = [ac for ac in asset_classes
                   if ac != 'FX' and bm_weights.get(ac, 0) != 0 and ac in _cum_prev]
        _denom = pd.Series(0.0, index=dates_idx)
        for ac in _funded:
            _denom = _denom + (bm_weights[ac] / 100.0) * _cum_prev[ac]
        _denom = _denom.where(_denom.abs() > 1e-12, 1.0)
        for ac in _funded:
            bm_w_daily[ac] = (bm_weights[ac] / 100.0) * _cum_prev[ac] / _denom
        # FX 오버레이: 해외주식(unhedged) 비중 표류 추종 (FX_target/equity_target 비율 유지)
        if bm_weights.get('FX', 0) != 0 and _eq in bm_w_daily and bm_weights.get(_eq, 0) > 0:
            _ratio = (bm_weights['FX'] / 100.0) / (bm_weights[_eq] / 100.0)
            bm_w_daily['FX'] = bm_w_daily[_eq] * _ratio

    # ── 4) BM 복합 일별 수익률 (RAW + 펀드별 cost) ──
    # R 프로덕션: -34bp/yr cost는 08K88에만 적용
    _BM_COST_DAILY = 34 / 10000 / 365
    _BM_COST_FUNDS = {'08K88'}
    bm_composite_daily = pd.Series(0.0, index=dates_idx)
    for ac in asset_classes:
        if ac in bm_daily_df.columns:
            bm_composite_daily += bm_daily_df[ac] * bm_w_daily[ac]
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
        bm_w = bm_w_daily.get(ac, pd.Series(0.0, index=dates_idx))  # 고정 broadcast / drift 일별
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
    # FX 포함(fx_split=False): 환효과를 해외 수익률에 multiplicative 로 접으면 통화 cross-term
    # 잔차가 남아 자산군 기여 합이 period_ap_return 과 ~0.1%p 어긋난다. BM 측(아래 _bm_resid)과
    # 동일하게 유동성및기타(잔차)에 귀속해 합 = AP수익률 보장. fx_split=True(분리) 는 잔차가 ~0 이라
    # 미적용(골든 스냅샷 불변). ap_period_contribs 는 fraction, period_ap_return 은 percent.
    if not fx_split:
        # asset_summary 엔 '포트폴리오' 총합 행이 있으므로 표시 자산군(asset_classes)만 합산(이중계상 방지).
        _ap_resid = period_ap_return / 100.0 - sum(
            ap_period_contribs.get(ac, 0.0) for ac in asset_classes)
        _ap_resid_ac = '유동성및기타' if '유동성및기타' in asset_classes else (
            asset_classes[-1] if asset_classes else None)
        if _ap_resid_ac is not None:
            ap_period_contribs[_ap_resid_ac] = ap_period_contribs.get(_ap_resid_ac, 0.0) + _ap_resid

    bm_period_returns = {}
    for ac in asset_classes:
        if bm_available and ac in bm_daily_df.columns:
            bm_period_returns[ac] = ((1 + bm_daily_df[ac]).cumprod().iloc[-1] - 1) * 100
        else:
            bm_period_returns[ac] = 0

    # 자산군별 BM 기여 (경로의존: 합 = period_bm_return).
    # 단순 BM비중×BM수익률 은 산술 분해라 복리·교차항만큼 합이 BM수익률과 안 맞음
    # → daily(ac)×weight×누적_{t-1} 로 정확 분해(검증식상 합 = (bm_cum[-1]-1)).
    bm_cum_prev = bm_cum.shift(1).fillna(1.0)
    bm_period_contrib = {}
    for ac in asset_classes:
        w = bm_w_daily.get(ac, pd.Series(0.0, index=dates_idx))
        if bm_available and ac in bm_daily_df.columns:
            bm_period_contrib[ac] = float((bm_daily_df[ac] * w * bm_cum_prev).sum() * 100)
        else:
            bm_period_contrib[ac] = 0.0
    # composite 보정(-34bp cost 등) 잔차는 유동성및기타에 귀속 → 합이 period_bm_return 과 일치
    if bm_available:
        _bm_resid = period_bm_return - sum(bm_period_contrib.values())
        _resid_ac = '유동성및기타' if '유동성및기타' in bm_period_contrib else (
            asset_classes[-1] if asset_classes else None)
        if _resid_ac is not None:
            bm_period_contrib[_resid_ac] = bm_period_contrib.get(_resid_ac, 0.0) + _bm_resid

    # ── 9) 결과 테이블 조립 ──
    results = []
    for ac in asset_classes:
        ap_w = ap_period_weights.get(ac, 0) * 100
        # drift 면 표시 BM비중은 일별 평균(대표값)
        bm_w = ((bm_w_daily[ac].mean() * 100) if (saa_mode.endswith('_drift') and ac in bm_w_daily)
                else bm_weights.get(ac, 0))
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
            'BM기여': round(bm_period_contrib.get(ac, 0.0), 4),
            'Allocation': round(alloc, 4), 'Selection': round(sel, 4),
            'Cross': round(crs, 4), '기여수익률': round(contrib, 4),
        })

    result_df = pd.DataFrame(results)

    total_alloc = result_df['Allocation'].sum()
    total_select = result_df['Selection'].sum()
    total_cross = result_df['Cross'].sum()

    # ── 10) 종목별 기여도 (전체 종목, 비중 포함) ──
    _sec_cols_in = ['자산군', '종목명', '개별수익률', '기여수익률']
    if '순자산비중' in single_pa['sec_summary'].columns:
        _sec_cols_in.append('순자산비중')
    sec_contrib_data = single_pa['sec_summary'][_sec_cols_in].copy()
    sec_contrib_data['수익률(%)'] = sec_contrib_data['개별수익률'] * 100
    sec_contrib_data['기여수익률(%)'] = sec_contrib_data['기여수익률'] * 100
    if '순자산비중' in sec_contrib_data.columns:
        sec_contrib_data['비중(%)'] = sec_contrib_data['순자산비중'] * 100
        sec_contrib_data = sec_contrib_data[
            ['자산군', '종목명', '비중(%)', '수익률(%)', '기여수익률(%)']
        ].round(4)
    else:
        sec_contrib_data = sec_contrib_data[
            ['자산군', '종목명', '수익률(%)', '기여수익률(%)']
        ].round(4)
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
    # AP/BM 누적수익(%) — 이미 계산된 ap_cum/bm_cum 노출(B4 우측 차트). 기존 값 불변.
    daily_sum_chart['ap_cum'] = (ap_cum.values - 1) * 100
    daily_sum_chart['bm_cum'] = ((bm_cum.values - 1) * 100) if bm_available else 0.0

    # ── 12) 자산군별 일별 시계열 (B4: AP비중 추이 + 자산군 기여 선택). 출력만 추가 ──
    ap_cum_prev = ap_cum.shift(1).fillna(1.0)
    _daily_class = []
    for ac in asset_classes:
        # AP 기여(누적): 일별 weight×return×AP누적_{t-1} → cumsum, 기간값(table1 AP기여)에 스케일
        ap_contrib_raw = (ap_ret_daily[ac] * ap_wgt_daily[ac] * ap_cum_prev).cumsum() * 100
        ap_target = ap_period_contribs.get(ac, 0) * 100
        ap_last = float(ap_contrib_raw.iloc[-1]) if len(ap_contrib_raw) else 0.0
        if abs(ap_last) > 1e-12:
            # 정상: weight×return 누적을 기간 AP기여(table1)에 스케일
            ap_contrib_cum = ap_contrib_raw * (ap_target / ap_last)
        elif abs(ap_target) > 1e-12 and len(dates_idx):
            # 잔차성 자산군(유동성및기타 등): raw≈0 → 목표값으로 선형 보간(끝점 일치)
            ramp = pd.Series(range(1, len(dates_idx) + 1), index=dates_idx) / len(dates_idx)
            ap_contrib_cum = ramp * ap_target
        else:
            ap_contrib_cum = ap_contrib_raw
        # BM 기여(누적): bm_period_contrib(table1 BM기여)에 끝점 정합 (AP 쪽과 동일 처리).
        # 유동성및기타엔 composite cost/분해 잔차(_bm_resid)가 귀속돼 raw cumsum 끝점과
        # 표값이 달라지므로, AP_contrib 처럼 표값으로 스케일/선형보간해 차트↔표 끝점 일치.
        w = bm_w_daily.get(ac, pd.Series(0.0, index=dates_idx))
        if bm_available and ac in bm_daily_df.columns:
            bm_contrib_raw = (bm_daily_df[ac] * w * bm_cum_prev).cumsum() * 100
        else:
            bm_contrib_raw = pd.Series(0.0, index=dates_idx)
        bm_target = bm_period_contrib.get(ac, 0.0)
        bm_last = float(bm_contrib_raw.iloc[-1]) if len(bm_contrib_raw) else 0.0
        if abs(bm_last) > 1e-12:
            bm_contrib_cum = bm_contrib_raw * (bm_target / bm_last)
        elif abs(bm_target) > 1e-12 and len(dates_idx):
            # 잔차성 자산군(raw≈0, 잔차만 있는 유동성및기타): 목표값으로 선형 보간(끝점 일치)
            ramp = pd.Series(range(1, len(dates_idx) + 1), index=dates_idx) / len(dates_idx)
            bm_contrib_cum = ramp * bm_target
        else:
            bm_contrib_cum = bm_contrib_raw
        ap_w_series = ap_wgt_daily[ac] * 100
        bm_w_pct = bm_w_daily.get(ac, pd.Series(0.0, index=dates_idx)) * 100  # 고정/일별 BM비중(%)
        # 자산군 실제(마켓) 누적수익률 % (0% 시작, 비중 미반영) — Allocation/Selection 진단용
        ap_ret_cum_s = ((1 + ap_ret_daily[ac]).cumprod() - 1) * 100
        if bm_available and ac in bm_daily_df.columns:
            bm_ret_cum_s = ((1 + bm_daily_df[ac]).cumprod() - 1) * 100
        else:
            bm_ret_cum_s = pd.Series(0.0, index=dates_idx)
        for i in range(len(dates_idx)):
            _daily_class.append({
                'date': dates_idx[i],
                'asset_class': ac,
                'ap_weight': float(ap_w_series.iloc[i]),
                'bm_weight': float(bm_w_pct.iloc[i]),
                'ap_contrib_cum': float(ap_contrib_cum.iloc[i]),
                'bm_contrib_cum': float(bm_contrib_cum.iloc[i]),
                'ap_ret_cum': float(ap_ret_cum_s.iloc[i]),
                'bm_ret_cum': float(bm_ret_cum_s.iloc[i]),
            })
    daily_class_df = pd.DataFrame(_daily_class)

    return {
        'pa_df': result_df,
        'total_alloc': total_alloc,
        'total_select': total_select,
        'total_cross': total_cross,
        'total_excess': period_excess,
        'total_excess_relative': period_excess_relative,
        'period_ap_return': period_ap_return,
        'period_bm_return': period_bm_return,
        'sec_contrib': sec_contrib_data if not sec_contrib_data.empty else pd.DataFrame(),
        'daily_brinson': daily_sum_chart,
        'daily_class': daily_class_df,
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


@functools.lru_cache(maxsize=64)
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


@_ttl_cache()
def _load_usdkrw_from_ecos(start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """ECOS API로 USDKRW 매매기준율 로드 (R 동일: stat_code=731Y003, item=0000003).

    캐시: 펀드무관(날짜키)·네트워크 콜 → 9펀드 워밍업서 1회만 호출. 호출처 read-only. TTL 6h."""
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


@_ttl_cache()
def _load_usdkrw_from_db(start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """DWCI10260에서 USDKRW 매매기준율 로드 (DB 소스). 펀드무관·read-only → 캐싱 안전. TTL 6h."""
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
    # 나머지 fallback (asset_gb 기반) — method별 국내/해외 병합 여부 분기
    _merge_domestic_foreign = mapping_method in ('방법1', '방법2')
    na_cls = sec_agg['자산군'].isna()
    for idx in sec_agg[na_cls].index:
        ag = str(sec_agg.loc[idx, 'asset_gb'])
        ccy = sec_agg.loc[idx, '노출통화']
        if ag in ('유동', '기타비용'):
            sec_agg.loc[idx, '자산군'] = '유동성및기타'
        elif '선물' in ag or '선도환' in ag:
            sec_agg.loc[idx, '자산군'] = 'FX' if ccy != 'KRW' else '유동성및기타'
        elif '주식' in ag:
            if _merge_domestic_foreign:
                sec_agg.loc[idx, '자산군'] = '주식'
            else:
                sec_agg.loc[idx, '자산군'] = '해외주식' if ccy != 'KRW' else '국내주식'
        elif '채권' in ag:
            if _merge_domestic_foreign:
                sec_agg.loc[idx, '자산군'] = '채권'
            else:
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
    # placeholder=0(int) 으로 만든 컬럼이 strict pandas(>=2.2 raise_on_upcast=True)
    # 환경에서 float 대입 거부되므로 사전 캐스팅.
    result_df['개별수익률'] = result_df['개별수익률'].astype(float)
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

    # asset_summary 순서: method별 자산군 리스트
    _asset_summary_order = BRINSON_METHOD_CLASSES.get(mapping_method,
        ['국내주식', '국내채권', '대체', '해외주식', '해외채권', 'FX', '유동성및기타'])
    for ac in _asset_summary_order:
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
    # 주식 지수 (TR) — 모두 USD 기준 (blob dict에서 USD 키 선택)
    'MSCI ACWI': {'dataset_id': 57, 'dataseries_id': 9, 'type': 'index', 'currency': 'USD'},
    'S&P 500': {'dataset_id': 24, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'MSCI Korea': {'dataset_id': 144, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'MSCI EM': {'dataset_id': 37, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'MSCI World ex US': {'dataset_id': 36, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'MSCI EAFE': {'dataset_id': 63, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'MSCI Japan': {'dataset_id': 66, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'Vanguard Growth': {'dataset_id': 11, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'Vanguard Value': {'dataset_id': 12, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'S&P 500 Growth': {'dataset_id': 114, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'S&P 500 Value': {'dataset_id': 116, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'Russell 1000 Growth': {'dataset_id': 115, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    'Russell 1000 Value': {'dataset_id': 117, 'dataseries_id': 6, 'type': 'index', 'currency': 'USD'},
    # PE/EPS
    'MSCI ACWI_PE': {'dataset_id': 57, 'dataseries_id': 24, 'type': 'valuation'},
    'MSCI ACWI_EPS': {'dataset_id': 57, 'dataseries_id': 31, 'type': 'valuation'},
    'S&P 500_PE': {'dataset_id': 24, 'dataseries_id': 24, 'type': 'valuation'},
    'S&P 500_EPS': {'dataset_id': 24, 'dataseries_id': 31, 'type': 'valuation'},
    'MSCI Korea_PE': {'dataset_id': 144, 'dataseries_id': 24, 'type': 'valuation'},
    'MSCI Korea_EPS': {'dataset_id': 144, 'dataseries_id': 31, 'type': 'valuation'},
    'MSCI EM_PE': {'dataset_id': 37, 'dataseries_id': 24, 'type': 'valuation'},
    'MSCI EM_EPS': {'dataset_id': 37, 'dataseries_id': 31, 'type': 'valuation'},
    'MSCI EAFE_PE': {'dataset_id': 63, 'dataseries_id': 24, 'type': 'valuation'},
    'MSCI EAFE_EPS': {'dataset_id': 63, 'dataseries_id': 31, 'type': 'valuation'},
    'MSCI Japan_PE': {'dataset_id': 66, 'dataseries_id': 24, 'type': 'valuation'},
    'MSCI Japan_EPS': {'dataset_id': 66, 'dataseries_id': 31, 'type': 'valuation'},
    'Vanguard Growth_PE': {'dataset_id': 11, 'dataseries_id': 24, 'type': 'valuation'},
    'Vanguard Growth_EPS': {'dataset_id': 11, 'dataseries_id': 31, 'type': 'valuation'},
    'Vanguard Value_PE': {'dataset_id': 12, 'dataseries_id': 24, 'type': 'valuation'},
    'Vanguard Value_EPS': {'dataset_id': 12, 'dataseries_id': 31, 'type': 'valuation'},
    'S&P 500 Growth_PE': {'dataset_id': 114, 'dataseries_id': 24, 'type': 'valuation'},
    'S&P 500 Growth_EPS': {'dataset_id': 114, 'dataseries_id': 31, 'type': 'valuation'},
    'S&P 500 Value_PE': {'dataset_id': 116, 'dataseries_id': 24, 'type': 'valuation'},
    'S&P 500 Value_EPS': {'dataset_id': 116, 'dataseries_id': 31, 'type': 'valuation'},
    'Russell 1000 Growth_PE': {'dataset_id': 115, 'dataseries_id': 24, 'type': 'valuation'},
    'Russell 1000 Growth_EPS': {'dataset_id': 115, 'dataseries_id': 31, 'type': 'valuation'},
    'Russell 1000 Value_PE': {'dataset_id': 117, 'dataseries_id': 24, 'type': 'valuation'},
    'Russell 1000 Value_EPS': {'dataset_id': 117, 'dataseries_id': 31, 'type': 'valuation'},
    # FX
    'USD/KRW': {'dataset_id': 31, 'dataseries_id': 6, 'type': 'fx', 'currency': 'USD'},
    # 변동성/스프레드
    'VIX': {'dataset_id': 403, 'dataseries_id': 9, 'type': 'volatility'},
    'MOVE': {'dataset_id': 405, 'dataseries_id': 9, 'type': 'volatility'},
    'US HY OAS': {'dataset_id': 404, 'dataseries_id': 9, 'type': 'spread'},
    # 금
    'Gold': {'dataset_id': 408, 'dataseries_id': 15, 'type': 'commodity'},
}


# ============================================================
# 주식 밸류에이션 proxy (편입종목 탭 주식 포커스 — PER × EPS성장)
# 보유 ETF 를 지역/스타일 proxy ETF 로 매핑해 SCIP PE(ds24)/EPS(ds31) 사용.
# (개별종목이 아닌 ETF 래퍼라 proxy 근사 — reference_macro_etf_proxy)
# ============================================================
# proxy → (dataset_id, PE dataseries_id, EPS dataseries_id).
# 전부 Bloomberg 12M Fwd P/E(ds52)·12M Fwd EPS(ds45) 지수로 통일.
EQUITY_PROXY_DATASETS = {
    'KOSPI200':  (225, 52, 45),   # 국내주식 (KOSPI 200 Index)
    '미국대형성장': (431, 52, 45),   # CRSP US Large Cap Growth Index
    '미국대형가치': (433, 52, 45),   # CRSP US Large Cap Value Index
    'NASDAQ100': (272, 52, 45),   # 나스닥 (NASDAQ100 Total Return Index)
    'S&P500':    (271, 52, 45),   # 그외 해외 (S&P 500 Index)
    'MSCI신흥':  (340, 52, 45),   # 신흥 (MXEF INDEX = MSCI Emerging Markets)
    'MSCI선진':  (339, 52, 45),   # 선진 ex-US (MXWOU INDEX = MSCI World ex-US)
}


def _classify_equity_proxy(item_cd: str, item_nm: str, asset_class: str):
    """보유 주식 → proxy 지수/ETF. 국내=KOSPI200, 해외=스타일/지역 키워드 분기(기본 S&P500)."""
    nm = (item_nm or '').upper()
    if asset_class == '국내주식':
        return 'KOSPI200'
    if asset_class == '해외주식':
        if '나스닥' in nm or 'NASDAQ' in nm or 'NDX' in nm:
            return 'NASDAQ100'
        # GROW/VALU 부분매칭 — DB ITEM_NM 잘림("...Grow"=Growth) 대응
        if '성장' in nm or 'GROW' in nm:
            return '미국대형성장'
        if '가치' in nm or 'VALU' in nm:
            return '미국대형가치'
        if '신흥' in nm or 'EMERGING' in nm or 'EM ' in nm:
            return 'MSCI신흥'
        if '선진' in nm or 'EAFE' in nm or 'DEVELOPED' in nm:
            return 'MSCI선진'
        return 'S&P500'   # 미국/광의 기본
    return None


@_ttl_cache()
def load_equity_proxy_valuations() -> dict:
    """proxy 지수별 최신 12M Fwd PER + 12M Fwd EPS YoY 성장률.

    Returns: {ticker: {'per': float|None, 'eps_growth': float|None(fraction), 'as_of': str|None}}
    EPS 성장 = 최신 12M Fwd EPS / (~365일 전 12M Fwd EPS) - 1.
    dataseries 는 proxy 별 (pe_ds, eps_ds) — 지수=Bloomberg ds52/45.
    """
    import datetime as _dt
    out: dict = {}
    try:
        conn = get_pandas_connection('SCIP')
    except Exception:
        return {tk: {'per': None, 'eps_growth': None, 'as_of': None}
                for tk in EQUITY_PROXY_DATASETS}
    try:
        for tk, (dsid, pe_ds, eps_ds) in EQUITY_PROXY_DATASETS.items():
            rec = {'per': None, 'eps_growth': None, 'as_of': None}
            try:
                pe = pd.read_sql(
                    "SELECT DATE(timestamp_observation) d, data FROM back_datapoint "
                    "WHERE dataset_id=%s AND dataseries_id=%s AND timestamp_ineffective IS NULL "
                    "ORDER BY timestamp_observation", conn, params=[dsid, pe_ds])
                if len(pe):
                    rec['per'] = float(parse_data_blob(pe['data'].iloc[-1]))
                    rec['as_of'] = str(pe['d'].iloc[-1])
                ep = pd.read_sql(
                    "SELECT DATE(timestamp_observation) d, data FROM back_datapoint "
                    "WHERE dataset_id=%s AND dataseries_id=%s AND timestamp_ineffective IS NULL "
                    "ORDER BY timestamp_observation", conn, params=[dsid, eps_ds])
                if len(ep) >= 2:
                    ep['v'] = ep['data'].apply(lambda b: float(parse_data_blob(b)))
                    last_v, last_d = ep['v'].iloc[-1], ep['d'].iloc[-1]
                    tgt = last_d - _dt.timedelta(days=365)
                    prior = ep[ep['d'] <= tgt]
                    if len(prior) and prior['v'].iloc[-1]:
                        rec['eps_growth'] = last_v / float(prior['v'].iloc[-1]) - 1.0
            except Exception:
                pass
            out[tk] = rec
    finally:
        conn.close()
    return out


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


def _load_holdings_range(fund_code: str, start_yyyymmdd: str = None) -> pd.DataFrame:
    """DWPM10530에서 날짜 범위 보유종목 로드 + 6분류. 거래내역 탭 영역차트용.

    Returns: DataFrame [STD_DT(int), ITEM_CD, ITEM_NM, 자산군, EVL_AMT(float)]
    """
    def _fetch(lo, hi):
        conn = get_pandas_connection('dt')
        try:
            sql = """
                SELECT STD_DT, ITEM_CD, ITEM_NM, AST_CLSF_CD_NM, CURR_DS_CD,
                       SUM(EVL_AMT) AS EVL_AMT
                FROM DWPM10530
                WHERE FUND_CD = %s AND IMC_CD = '003228' AND EVL_AMT > 0
                  AND ITEM_NM NOT LIKE '%%미지급%%'
                  AND ITEM_NM NOT LIKE '%%미수%%'
                  AND STD_DT BETWEEN %s AND %s
                GROUP BY STD_DT, ITEM_CD, ITEM_NM, AST_CLSF_CD_NM, CURR_DS_CD
            """
            # STD_DT 는 varchar(8) PK — 문자열 바운드로 넘겨야 인덱스 사용(int면 full scan)
            return pd.read_sql(sql, conn, params=[fund_code, str(lo), str(hi)])
        finally:
            conn.close()

    # 과거 보유는 사실상 불변 → SQLite 영속 캐시(최근 N영업일만 재조회). end=오늘
    start_int = int(start_yyyymmdd) if start_yyyymmdd else None
    today_int = int(datetime.now().strftime('%Y%m%d'))
    df = db_cache.get_cached_range(db_cache.HOLDINGS, fund_code,
                                   start_int, today_int, _fetch)

    if df.empty:
        return df

    # 분류는 distinct ITEM_CD 단위로 1회만 (행별 apply 대비 효율)
    uniq = df[['ITEM_CD', 'ITEM_NM', 'AST_CLSF_CD_NM', 'CURR_DS_CD']].drop_duplicates('ITEM_CD')
    cls_map = {}
    for _, r in uniq.iterrows():
        icd = str(r['ITEM_CD']).strip()
        cls_map[icd] = _classify_6class({
            'AST_CLSF_CD_NM': r['AST_CLSF_CD_NM'], 'ITEM_CD': icd,
            'ITEM_NM': r['ITEM_NM'], 'CURR_DS_CD': r['CURR_DS_CD'],
        })
    df['자산군'] = df['ITEM_CD'].astype(str).str.strip().map(cls_map)
    df['EVL_AMT'] = pd.to_numeric(df['EVL_AMT'], errors='coerce').fillna(0.0)
    return df[['STD_DT', 'ITEM_CD', 'ITEM_NM', '자산군', 'EVL_AMT']]


# 영역차트 6버킷 (사용자 합의 2026-06-15): 1국내주식 2해외주식 3국내채권 4해외채권
# 5금/대체 6유동성. 1~5 아니면(FX·모펀드·현금성 등) 전부 유동성.
_SIX_BUCKET_ORDER = ['국내주식', '해외주식', '국내채권', '해외채권', '금/대체', '유동성']
_EIGHT_TO_SIX = {
    '국내주식': '국내주식', '해외주식': '해외주식',
    '국내채권': '국내채권', '해외채권': '해외채권',
    '대체투자': '금/대체',
    'FX': '유동성', '모펀드': '유동성', '유동성': '유동성',
}


def _collapse_to_6bucket(ac: str) -> str:
    return _EIGHT_TO_SIX.get(str(ac), '유동성')


@_ttl_cache()
def load_business_days_set(start_yyyymmdd: str, end_yyyymmdd: str) -> frozenset:
    """DWCI10220 영업일(hldy_yn='N')의 'YYYY-MM-DD' 집합. 주말+평일공휴일 제외.
    조회 실패 시 빈 set → 호출부에서 주말 fallback."""
    try:
        conn = get_pandas_connection('dt')
        try:
            df = pd.read_sql(
                "SELECT std_dt FROM DWCI10220 WHERE hldy_yn='N' "
                "AND std_dt BETWEEN %s AND %s",
                conn, params=[str(start_yyyymmdd), str(end_yyyymmdd)])
        finally:
            conn.close()
        if not df.empty:
            return frozenset(
                pd.to_datetime(df['std_dt'].astype(str), format='%Y%m%d')
                .dt.strftime('%Y-%m-%d'))
    except Exception:
        pass
    return frozenset()


@_ttl_cache()
def load_weight_history_lookthrough(fund_code: str, start_date: str = None,
                                    level: str = 'security') -> tuple:
    """일별 비중 시계열 (FoF look-through, 6버킷). 거래내역 탭 영역차트용.

    FoF(예: 07G04)는 모펀드 행을 자펀드(07G02/07G03) 보유종목으로 전개하되,
    각 자펀드를 모펀드의 편입금액(EVL)으로 스케일 → 편입비율 반영 가중평균.

    6버킷: 자산군은 국내주식/해외주식/국내채권/해외채권/금·대체/유동성으로 축소.
      - level='asset': key=버킷
      - level='security': 버킷 1~5 종목은 종목명 개별, 그 외(유동성·FX·모펀드)는 '유동성'으로 묶음
    FX(달러선물)는 영역에서 유동성으로 흡수되며, 포지션은 load_fx_position_history 로 별도 표시.

    Returns:
        (DataFrame[date(YYYY-MM-DD), key, weight(%)], is_fof: bool, keys: list[str])
        keys 는 (버킷 순서, 평균비중 desc) 정렬.
    """
    start_yyyymmdd = start_date.replace('-', '') if start_date else None
    related = _get_관련_fund_list(fund_code)
    children = [f for f in related if f != fund_code]
    is_fof = bool(children)

    parent = _load_holdings_range(fund_code, start_yyyymmdd)
    if parent.empty:
        return pd.DataFrame(), is_fof, []

    is_mother = parent['ITEM_CD'].astype(str).str.startswith('0322800')
    frames = [parent.loc[~is_mother, ['STD_DT', 'ITEM_NM', '자산군', 'EVL_AMT']]]

    if is_fof:
        mother = parent[is_mother].copy()
        mother['child'] = mother['ITEM_CD'].apply(_extract_fund_code_from_item_cd)
        mother_evl = (mother.groupby(['STD_DT', 'child'], as_index=False)['EVL_AMT']
                      .sum().rename(columns={'EVL_AMT': 'mother_evl'}))
        for child in children:
            cdf = _load_holdings_range(child, start_yyyymmdd)
            if cdf.empty:
                continue
            ctot = (cdf.groupby('STD_DT', as_index=False)['EVL_AMT']
                    .sum().rename(columns={'EVL_AMT': 'child_tot'}))
            me = mother_evl.loc[mother_evl['child'] == child, ['STD_DT', 'mother_evl']]
            m = cdf.merge(ctot, on='STD_DT').merge(me, on='STD_DT')
            if m.empty:
                continue
            # 자펀드 보유종목 EVL → 모펀드 편입금액 비율로 스케일
            m['EVL_AMT'] = m['EVL_AMT'] * m['mother_evl'] / m['child_tot']
            frames.append(m[['STD_DT', 'ITEM_NM', '자산군', 'EVL_AMT']])

    allrows = pd.concat(frames, ignore_index=True)
    if allrows.empty:
        return pd.DataFrame(), is_fof, []

    allrows['bucket'] = allrows['자산군'].map(_collapse_to_6bucket)
    if level == 'asset':
        allrows['key'] = allrows['bucket']
    else:
        # 버킷 1~5 → 종목명 개별, 유동성(=비1~5) → '유동성' 단일 밴드
        allrows['key'] = allrows.apply(
            lambda r: r['ITEM_NM'] if r['bucket'] != '유동성' else '유동성', axis=1)

    agg = allrows.groupby(['STD_DT', 'key'], as_index=False)['EVL_AMT'].sum()
    agg['_tot'] = agg.groupby('STD_DT')['EVL_AMT'].transform('sum')
    agg = agg[agg['_tot'] > 0].copy()
    agg['weight'] = (agg['EVL_AMT'] / agg['_tot'] * 100.0).round(3)
    agg['date'] = pd.to_datetime(agg['STD_DT'].astype(str), format='%Y%m%d').dt.strftime('%Y-%m-%d')
    out = (agg[['date', 'key', 'weight']]
           .sort_values(['date', 'key']).reset_index(drop=True))

    # 영업일만 표시 — DWCI10220(hldy_yn='N')로 주말/평일공휴일 보유 스냅샷 제외.
    # (거래는 영업일만 발생 → 영역도 영업일로 맞춰 주말 carry 노이즈 제거)
    if not out.empty:
        _s = out['date'].min().replace('-', '')
        _e = out['date'].max().replace('-', '')
        _bdays = load_business_days_set(_s, _e)
        if _bdays:
            out = out[out['date'].isin(_bdays)].reset_index(drop=True)
        else:  # 캘린더 조회 실패 → 주말만 제거 fallback
            _wd = pd.to_datetime(out['date']).dt.dayofweek
            out = out[(_wd < 5).values].reset_index(drop=True)

    # keys 정렬: (버킷 순서, 평균비중 desc)
    kb = allrows.groupby('key')['bucket'].first()
    meanw = agg.groupby('key')['weight'].mean()

    def _ord(k):
        b = kb.get(k, '유동성')
        bi = _SIX_BUCKET_ORDER.index(b) if b in _SIX_BUCKET_ORDER else 99
        return (bi, -float(meanw.get(k, 0.0)))

    keys = sorted(meanw.index, key=_ord)
    return out, is_fof, keys


@_ttl_cache()
def load_weight_trade_markers(fund_code: str, start_date: str,
                              level: str = 'asset', end_date: str = None) -> pd.DataFrame:
    """일별 비중 영역차트용 매매 마커. (date, key) 순매수(억) 합산.

    key 규칙은 load_weight_history_lookthrough 와 동일:
      - level='asset': key=6버킷
      - level='security': 버킷 1~5 종목명, 그 외(유동성·FX·모펀드)는 '유동성' 묶음
    부호: 매수/발행=+, 매도/환매=−, 기타(환전 등)=0(제외). |net|≈0 행 제외.
    거래는 load_fund_trades_lookthrough 재사용(FoF 자펀드 치환·콜론/환전 제외 동일).

    Returns: DataFrame[date(YYYY-MM-DD), key, net_eok]
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    s_int = int(start_date.replace('-', ''))
    e_int = int(end_date.replace('-', ''))

    df, _funds, _fof = load_fund_trades_lookthrough(fund_code, s_int, e_int)
    cols = ['date', 'key', 'net_eok']
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    d = df.copy()
    # BA정산(발행/환매 정산성, qty=0)은 마커에서 제외 (사용자 요청)
    d = d[~d['매수매도'].astype(str).str.contains('BA정산')].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)

    d['bucket'] = d['자산군'].map(_collapse_to_6bucket)
    if level == 'asset':
        d['key'] = d['bucket']
    else:
        d['key'] = d.apply(
            lambda r: r['종목명'] if r['bucket'] != '유동성' else '유동성', axis=1)

    side = d['매수매도'].astype(str)
    is_buy = side.str.contains('매수') | side.str.contains('발행')
    is_sell = side.str.contains('매도') | side.str.contains('환매')
    d['signed'] = 0.0
    d.loc[is_buy, 'signed'] = d.loc[is_buy, '금액(억)']
    d.loc[is_sell, 'signed'] = -d.loc[is_sell, '금액(억)']

    g = d.groupby(['날짜', 'key'], as_index=False)['signed'].sum()
    g = g[g['signed'].abs() > 1e-9].copy()
    if g.empty:
        return pd.DataFrame(columns=cols)
    g['date'] = pd.to_datetime(g['날짜'].astype(str), format='%Y%m%d').dt.strftime('%Y-%m-%d')
    g['net_eok'] = g['signed'].round(2)
    return g[cols].sort_values(['date', 'key']).reset_index(drop=True)


@_ttl_cache()
def load_fund_trades_lookthrough(fund_code: str, start_date: int, end_date: int) -> tuple:
    """거래내역 (FoF look-through). 거래내역 탭용.

    FoF(07G04)는 자펀드(07G02/07G03)의 거래내역으로 치환. 그 외는 자기 거래.
    필터(사용자 합의): 콜론(call loan) 제외, 환전 제외. 발행/환매(BA정산)은 유지.

    Returns:
        (DataFrame[날짜, 펀드, 종목명, 자산군, 매수매도, 금액(억)],
         funds_queried: list[str], is_fof: bool)
    """
    related = _get_관련_fund_list(fund_code)
    children = [f for f in related if f != fund_code]
    is_fof = bool(children)
    funds_to_query = children if is_fof else [fund_code]

    frames = []
    for f in funds_to_query:
        d = load_fund_trade_detail(f, start_date, end_date)
        if d is None or d.empty:
            continue
        d = d.copy()
        d['펀드'] = f
        frames.append(d)

    if not frames:
        return pd.DataFrame(), funds_to_query, is_fof

    out = pd.concat(frames, ignore_index=True)
    # 콜론(MMF 롤링) + 환전(통화전환) 제외 — 포지션 관련만
    mask_call = out['종목명'].astype(str).str.contains('콜론', na=False)
    mask_fx_conv = out['매수매도'] == '환전'
    out = out[~(mask_call | mask_fx_conv)]
    out = out[['날짜', '펀드', '종목명', '자산군', '매수매도', '금액(억)']]
    out = out.sort_values(['날짜', '펀드', '종목명']).reset_index(drop=True)
    return out, funds_to_query, is_fof


@_ttl_cache()
def load_fx_position_history(fund_code: str, start_date: str = None) -> tuple:
    """달러선물 등 FX 포지션 일별 순비중(%) 시계열. **매도(숏)=양수**(헤지비중 표기).

    DWPM10530의 ast_clsf_cd_nm='달러선물' (또는 종목명 '달러 F') 행을 pos_ds_cd
    부호 적용해 일별/계약별 합산. NAST_TAMT_AGNST_WGH 를 그대로 비중으로 사용.
    달러선물은 환헤지 목적의 매도(숏)라 +로 표기(해외자산 비중과 비교 용이).

    Returns: (DataFrame[date, key(계약명), weight(%)], has_fx: bool)
    """
    start_yyyymmdd = start_date.replace('-', '') if start_date else None
    related = _get_관련_fund_list(fund_code)
    children = [f for f in related if f != fund_code]
    funds = children if children else [fund_code]

    conn = get_pandas_connection('dt')
    try:
        fmt = ','.join(['%s'] * len(funds))
        params = list(funds)
        date_filter = ""
        if start_yyyymmdd:
            date_filter = " AND std_dt >= %s"
            params.append(start_yyyymmdd)
        df = pd.read_sql(f"""
            SELECT std_dt, item_nm, pos_ds_cd, nast_tamt_agnst_wgh AS wgh
            FROM DWPM10530
            WHERE fund_cd IN ({fmt}) AND imc_cd = '003228' AND evl_amt <> 0
              AND (ast_clsf_cd_nm LIKE '%%달러선물%%' OR item_nm LIKE '%%달러 F%%')
              {date_filter}
        """, conn, params=params)
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame(), False

    # 매도(숏)=+1, 매수=−1 (헤지 순비중을 양수로 표기 — 해외자산 비중과 비교 용이)
    sign = df['pos_ds_cd'].astype(str).str.contains('매도').map({True: 1.0, False: -1.0})
    df['weight'] = pd.to_numeric(df['wgh'], errors='coerce').fillna(0.0) * sign.fillna(-1.0)
    df['date'] = pd.to_datetime(df['std_dt'].astype(str), format='%Y%m%d').dt.strftime('%Y-%m-%d')
    agg = (df.groupby(['date', 'item_nm'], as_index=False)['weight'].sum()
           .rename(columns={'item_nm': 'key'}))
    agg['weight'] = agg['weight'].round(3)
    return agg.sort_values(['date', 'key']).reset_index(drop=True), True


def load_usdkrw_series(start_date: str = None) -> pd.DataFrame:
    """USD/KRW 환율 일별 시계열 (dt.DWCI10260 거래기준율 TR_STD_RT1).

    Returns: DataFrame[date(YYYY-MM-DD), rate]
    """
    start_yyyymmdd = start_date.replace('-', '') if start_date else None
    conn = get_pandas_connection('dt')
    try:
        q = ("SELECT std_dt, tr_std_rt1 AS rate FROM DWCI10260 "
             "WHERE curr_ds_cd = 'USD'")
        params = []
        if start_yyyymmdd:
            q += " AND std_dt >= %s"
            params.append(start_yyyymmdd)
        q += " ORDER BY std_dt"
        df = pd.read_sql(q, conn, params=params)
    finally:
        conn.close()
    if df.empty:
        return pd.DataFrame(columns=['date', 'rate'])
    df['rate'] = pd.to_numeric(df['rate'], errors='coerce')
    df = df.dropna(subset=['rate'])
    df['date'] = pd.to_datetime(df['std_dt'].astype(str), format='%Y%m%d').dt.strftime('%Y-%m-%d')
    return df[['date', 'rate']].sort_values('date').reset_index(drop=True)


def load_foreign_asset_weight_history(fund_code: str, start_date: str = None) -> pd.DataFrame:
    """해외자산(해외주식 + 해외채권 + 외화예금[USD deposit 등]) 일별 합산 비중(%) 시계열.

    FX 포지션 차트 보조 레이어용. _classify_6class(universe-first) 로 분류 후
    해외주식/해외채권 + 외화표시 예금/예치금(DEPOSIT·외화예치금)을 합산.
    (USD deposit 은 종목명 'USD' 패턴 때문에 6분류상 FX 로 떨어져 별도 포함.)

    Returns: DataFrame[date(YYYY-MM-DD), weight(%)]
    """
    start_yyyymmdd = start_date.replace('-', '') if start_date else None
    related = _get_관련_fund_list(fund_code)
    children = [f for f in related if f != fund_code]
    funds = children if children else [fund_code]

    conn = get_pandas_connection('dt')
    try:
        fmt = ','.join(['%s'] * len(funds))
        params = list(funds)
        date_filter = ""
        if start_yyyymmdd:
            date_filter = " AND std_dt >= %s"
            params.append(start_yyyymmdd)
        df = pd.read_sql(f"""
            SELECT std_dt, item_cd, item_nm, ast_clsf_cd_nm, curr_ds_cd,
                   nast_tamt_agnst_wgh AS wgh
            FROM DWPM10530
            WHERE fund_cd IN ({fmt}) AND imc_cd = '003228' AND evl_amt <> 0
              {date_filter}
        """, conn, params=params)
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame(columns=['date', 'weight'])

    def _is_foreign(row):
        cls = _classify_6class({
            'AST_CLSF_CD_NM': row.get('ast_clsf_cd_nm') or '',
            'ITEM_CD': str(row.get('item_cd') or ''),
            'ITEM_NM': row.get('item_nm') or '',
            'CURR_DS_CD': row.get('curr_ds_cd') or '',
        })
        if cls in ('해외주식', '해외채권'):
            return True
        # 외화표시 예금/예치금 (USD deposit) — 6분류상 FX/유동성으로 떨어져도 포함
        curr = str(row.get('curr_ds_cd') or '').upper()
        if curr not in ('KRW', '', 'NAN', 'NONE'):
            nm = str(row.get('item_nm') or '').upper()
            ast = str(row.get('ast_clsf_cd_nm') or '')
            if 'DEPOSIT' in nm or '외화' in ast or '예금' in ast:
                return True
        return False

    df = df[df.apply(_is_foreign, axis=1)]
    if df.empty:
        return pd.DataFrame(columns=['date', 'weight'])
    df['wgh'] = pd.to_numeric(df['wgh'], errors='coerce').fillna(0.0)
    g = (df.groupby('std_dt', as_index=False)['wgh'].sum()
         .rename(columns={'wgh': 'weight'}))
    g['date'] = pd.to_datetime(g['std_dt'].astype(str), format='%Y%m%d').dt.strftime('%Y-%m-%d')
    g['weight'] = g['weight'].round(3)
    return g[['date', 'weight']].sort_values('date').reset_index(drop=True)


def _scip_covered_isins(isins: list) -> set:
    """SCIP back_dataset 에 가격(ISIN)이 있는 종목 집합."""
    isins = [s for s in isins if s]
    if not isins:
        return set()
    conn = get_pandas_connection('SCIP')
    try:
        fmt = ','.join(['%s'] * len(isins))
        df = pd.read_sql(
            f"SELECT DISTINCT ISIN FROM back_dataset WHERE ISIN IN ({fmt})",
            conn, params=isins)
    finally:
        conn.close()
    return set(df['ISIN'].astype(str)) if not df.empty else set()


@_ttl_cache()
def load_fund_securities(fund_code: str, start_date: str = None) -> pd.DataFrame:
    """수익률 차트용 보유종목 목록 (버킷 1~5, 가격 커버리지 플래그).

    start_date 지정 시 [start_date, 오늘] 편입이력은 있으나 현재 미보유 종목을
    하단에 추가(currently_held=False). 현재/과거 각 그룹 내 버킷순→비중(현재)/
    EVL_AMT(과거) 내림차순 정렬.

    Returns: DataFrame[item_cd, item_nm, bucket, weight, has_price, currently_held]
    """
    frames = []
    current_codes = set()

    # 1) 현재 보유 (look-through, FoF 전개)
    df = load_fund_holdings_lookthrough(fund_code)
    if df is not None and not df.empty:
        d = df.copy()
        d['bucket'] = d['자산군'].map(_collapse_to_6bucket)
        d = d[d['bucket'] != '유동성']
        if not d.empty:
            cur = pd.DataFrame({
                'item_cd': d['ITEM_CD'].astype(str).str.strip(),
                'item_nm': d['ITEM_NM'].astype(str),
                'bucket': d['bucket'].astype(str),
                'weight': pd.to_numeric(d.get('비중(%)'), errors='coerce').fillna(0.0),
            })
            cur['currently_held'] = True
            cur['_sortw'] = cur['weight']
            current_codes = set(cur['item_cd'])
            frames.append(cur)

    # 2) 편입이력(현재 미보유) — start_date 지정 시. FoF 면 자펀드 기준.
    if start_date:
        related = _get_관련_fund_list(fund_code)
        children = [f for f in related if f != fund_code]
        hist_funds = children if children else [fund_code]
        s_int = str(start_date).replace('-', '')
        parts = []
        for f in hist_funds:
            h = _load_holdings_range(f, s_int)
            if h is not None and not h.empty:
                parts.append(h)
        if parts:
            hist = pd.concat(parts, ignore_index=True)
            hist['item_cd'] = hist['ITEM_CD'].astype(str).str.strip()
            hist['bucket'] = hist['자산군'].map(_collapse_to_6bucket)
            hist = hist[(hist['bucket'] != '유동성')
                        & (~hist['item_cd'].isin(current_codes))]
            if not hist.empty:
                agg = (hist.groupby('item_cd')
                       .agg(item_nm=('ITEM_NM', 'first'), bucket=('bucket', 'first'),
                            _sortw=('EVL_AMT', 'max')).reset_index())
                agg['weight'] = 0.0          # 현재 미보유 → 비중 0
                agg['currently_held'] = False
                frames.append(agg[['item_cd', 'item_nm', 'bucket', 'weight',
                                   'currently_held', '_sortw']])

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    isins = [str(x).strip() for x in out['item_cd'].dropna().unique()]
    covered = _scip_covered_isins(isins)
    out['has_price'] = out['item_cd'].isin(covered)
    out['_held'] = (~out['currently_held']).astype(int)   # 현재(0) 먼저, 과거(1) 하단
    out['_b'] = out['bucket'].map(
        lambda b: _SIX_BUCKET_ORDER.index(b) if b in _SIX_BUCKET_ORDER else 99)
    out = (out.sort_values(['_held', '_b', '_sortw'], ascending=[True, True, False])
           .drop(columns=['_held', '_b', '_sortw']).reset_index(drop=True))
    return out


def _load_scip_return_index(item_cd: str, start_date: str = None) -> pd.DataFrame:
    """SCIP FG Return(6) KRW 지수, 없으면 Total Return(39). 시작일=100 리베이스.

    Returns: DataFrame[date(YYYY-MM-DD), value]
    """
    conn = get_pandas_connection('SCIP')
    try:
        params = [str(item_cd).strip()]
        date_filter = ""
        if start_date:
            date_filter = " AND dp.timestamp_observation >= %s"
            params.append(start_date)
        df = pd.read_sql(f"""
            SELECT DATE(dp.timestamp_observation) AS date, dp.dataseries_id AS dsid, dp.data
            FROM back_datapoint dp
            JOIN back_dataset d ON dp.dataset_id = d.id
            WHERE d.ISIN = %s AND dp.dataseries_id IN (6, 39){date_filter}
            ORDER BY dp.timestamp_observation
        """, conn, params=params)
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame()

    use = df[df['dsid'] == 6]
    cur = 'KRW'
    if use.empty:
        use = df[df['dsid'] == 39]
        cur = None
    use = use.drop_duplicates('date', keep='last').sort_values('date').copy()
    use['val'] = use['data'].apply(lambda b: _safe_parse_blob(b, cur))
    use = use.dropna(subset=['val'])
    if use.empty:
        return pd.DataFrame()
    base = float(use['val'].iloc[0])
    if base == 0:
        return pd.DataFrame()
    return pd.DataFrame({
        'date': pd.to_datetime(use['date']).dt.strftime('%Y-%m-%d'),
        'value': (use['val'].astype(float) / base * 100.0).round(3),
    }).reset_index(drop=True)


def _safe_parse_blob(blob, currency):
    try:
        v = parse_data_blob(blob, currency) if currency else parse_data_blob(blob)
        return float(v)
    except Exception:
        return None


@_ttl_cache()
def load_security_return_with_trades(fund_code: str, item_cd: str,
                                     start_date: str, end_date: str) -> tuple:
    """종목 수익률 지수(100 리베이스) + 매수/매도 마커. ('기타'/'환전' 마커 제외)

    Returns: (DataFrame[date, value], trades: list[{date, side, amount}])
    """
    price = _load_scip_return_index(item_cd, start_date)

    related = _get_관련_fund_list(fund_code)
    children = [f for f in related if f != fund_code]
    funds = children if children else [fund_code]
    s_int = int(start_date.replace('-', ''))
    e_int = int(end_date.replace('-', ''))

    target = str(item_cd).strip()
    # 같은 날·같은 방향 거래는 합산(겹쳐서 하나만 보이는 문제 해소).
    # 제외: 기타/환전, BA정산(발행/환매 정산성) — 마커 정책 일관.
    agg = {}  # (date_iso, '매수'|'매도') -> amount 합
    for f in funds:
        d = load_fund_trade_detail(f, s_int, e_int)
        if d is None or d.empty:
            continue
        d = d[d['item_cd'].astype(str).str.strip() == target]
        for _, r in d.iterrows():
            side = str(r['매수매도'])
            if side in ('기타', '환전') or 'BA정산' in side:
                continue
            ds = str(r['날짜'])
            date_iso = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}" if len(ds) == 8 else ds
            direction = '매수' if ('매수' in side or '발행' in side) else '매도'
            agg[(date_iso, direction)] = agg.get((date_iso, direction), 0.0) + float(r['금액(억)'])
    trades = [{'date': dt, 'side': dr, 'amount': round(amt, 2)}
              for (dt, dr), amt in sorted(agg.items())]
    return price, trades


def _load_scip_prices_batch(isins, start_date: str = None) -> pd.DataFrame:
    """여러 ISIN 의 FG Return(6) KRW 가격, 없으면 Total Return(39). 종목별 우선순위 적용.

    Returns: DataFrame[date(YYYY-MM-DD), item_cd, price]
    """
    isins = [str(x).strip() for x in isins if str(x).strip()]
    if not isins:
        return pd.DataFrame(columns=['date', 'item_cd', 'price'])
    conn = get_pandas_connection('SCIP')
    try:
        ph = ','.join(['%s'] * len(isins))
        params = list(isins)
        date_filter = ""
        if start_date:
            date_filter = " AND dp.timestamp_observation >= %s"
            params.append(start_date)
        df = pd.read_sql(f"""
            SELECT d.ISIN AS item_cd, DATE(dp.timestamp_observation) AS date,
                   dp.dataseries_id AS dsid, dp.data
            FROM back_datapoint dp
            JOIN back_dataset d ON dp.dataset_id = d.id
            WHERE d.ISIN IN ({ph}) AND dp.dataseries_id IN (6, 39){date_filter}
            ORDER BY d.ISIN, dp.timestamp_observation
        """, conn, params=params)
    finally:
        conn.close()
    if df.empty:
        return pd.DataFrame(columns=['date', 'item_cd', 'price'])
    rows = []
    for icd, g in df.groupby('item_cd'):
        use = g[g['dsid'] == 6]
        cur = 'KRW'
        if use.empty:
            use = g[g['dsid'] == 39]
            cur = None
        use = use.drop_duplicates('date', keep='last').copy()
        use['price'] = use['data'].apply(lambda b: _safe_parse_blob(b, cur))
        use = use.dropna(subset=['price'])
        for _, r in use.iterrows():
            rows.append({
                'date': pd.to_datetime(r['date']).strftime('%Y-%m-%d'),
                'item_cd': str(icd).strip(), 'price': float(r['price']),
            })
    return pd.DataFrame(rows)


def _asset_class_member_names(fund_code: str, asset_class: str,
                              start_date: str) -> set:
    """[start_date, 오늘] 동안 해당 자산군에 편입된 종목명 집합 (FoF 자펀드 union).
    자산군 툴팁 종목별 분해용 (weight/trade 필터 키)."""
    related = _get_관련_fund_list(fund_code)
    children = [f for f in related if f != fund_code]
    funds = children if children else [fund_code]
    s_int = str(start_date).replace('-', '')
    names = set()
    for f in funds:
        h = _load_holdings_range(f, s_int)
        if h is None or h.empty:
            continue
        b = h['자산군'].map(_collapse_to_6bucket)
        names |= set(h.loc[b == asset_class, 'ITEM_NM'].astype(str))
    return names


def load_asset_class_return_index(fund_code: str, asset_class: str,
                                  start_date: str, end_date: str = None) -> tuple:
    """자산군 바스켓 수익지수(시작=100). 클래스 내 정규화 value-weighted.

    일별 r_class(t) = Σ val_i(t-1)·r_i(t) / Σ val_i(t-1)  (해당 자산군·가격커버 종목만,
    val=EVL_AMT 전일 보유액, r=SCIP FG Return 일별수익률). 누적 → 지수 100.
    FoF 는 자펀드 보유 union. 유동성은 가격 무의미 → 빈 결과.

    Returns: (DataFrame[date, value], warning|None)
    """
    if asset_class == '유동성':
        return pd.DataFrame(columns=['date', 'value']), '유동성은 수익지수 제외'

    related = _get_관련_fund_list(fund_code)
    children = [f for f in related if f != fund_code]
    funds = children if children else [fund_code]
    s_int = str(start_date).replace('-', '')
    parts = []
    for f in funds:
        h = _load_holdings_range(f, s_int)
        if h is not None and not h.empty:
            parts.append(h)
    if not parts:
        return pd.DataFrame(columns=['date', 'value']), '보유 데이터 없음'

    h = pd.concat(parts, ignore_index=True)
    h['item_cd'] = h['ITEM_CD'].astype(str).str.strip()
    h['bucket'] = h['자산군'].map(_collapse_to_6bucket)
    h = h[h['bucket'] == asset_class]
    if h.empty:
        return pd.DataFrame(columns=['date', 'value']), f'{asset_class} 보유 없음'
    h['date'] = pd.to_datetime(h['STD_DT'].astype(str), format='%Y%m%d').dt.strftime('%Y-%m-%d')
    if end_date:
        h = h[h['date'] <= end_date]
    # 같은 날·같은 종목(여러 자펀드) 보유액 합산
    val = h.groupby(['date', 'item_cd'])['EVL_AMT'].sum().reset_index()

    isins = sorted(val['item_cd'].unique())
    px = _load_scip_prices_batch(isins, start_date)
    if px.empty:
        return pd.DataFrame(columns=['date', 'value']), '가격 데이터 없음'
    if end_date:
        px = px[px['date'] <= end_date]

    pxp = px.pivot_table(index='date', columns='item_cd', values='price', aggfunc='last').sort_index()
    valp = val.pivot_table(index='date', columns='item_cd', values='EVL_AMT', aggfunc='sum')
    # 타임라인=가격 영업일. 보유액은 마지막 스냅샷 ffill. 공통 종목만.
    common = [c for c in pxp.columns if c in valp.columns]
    if not common:
        return pd.DataFrame(columns=['date', 'value']), '가격·보유 교집합 종목 없음'
    pxp = pxp[common]
    valp = valp.reindex(pxp.index)[common].ffill()

    rets = pxp.pct_change()
    w_prev = valp.shift(1)
    mask = rets.notna() & w_prev.notna() & (w_prev > 0)
    num = (w_prev.where(mask) * rets.where(mask)).sum(axis=1, min_count=1)
    den = w_prev.where(mask).sum(axis=1, min_count=1)
    r_class = num / den
    valid = den.notna() & (den > 0)
    if not valid.any():
        return pd.DataFrame(columns=['date', 'value']), '계산 가능 구간 없음'
    first = valid.idxmax()
    r_class = r_class.loc[first:].fillna(0.0)
    r_class.iloc[0] = 0.0  # 시작일=기준(100)
    idx = (1.0 + r_class).cumprod() * 100.0
    out = pd.DataFrame({'date': list(idx.index), 'value': idx.round(3).values})
    return out.reset_index(drop=True), None


@_ttl_cache()
def load_fund_total_return_index(fund_code: str, start_date: str,
                                 end_date: str = None) -> pd.DataFrame:
    """펀드 기준가(MOD_STPR) 수익지수 (시작=100) — 자산군 차트 '전체' 옵션용.

    펀드 전체 포트폴리오의 실제 운용수익(현금·환손익·비용 모두 포함). FoF 도
    부모펀드 기준가 하나로 표현되므로 자펀드 전개 불필요.

    Returns: DataFrame[date(YYYY-MM-DD), value]
    """
    s8 = str(start_date).replace('-', '') if start_date else None
    df = load_fund_nav_with_aum(fund_code, s8)
    if df is None or df.empty:
        return pd.DataFrame(columns=['date', 'value'])
    d = df[['기준일자', 'MOD_STPR']].dropna().copy()
    d['date'] = pd.to_datetime(d['기준일자']).dt.strftime('%Y-%m-%d')
    if end_date:
        d = d[d['date'] <= end_date]
    d = d[pd.to_numeric(d['MOD_STPR'], errors='coerce') > 0].sort_values('date')
    if d.empty:
        return pd.DataFrame(columns=['date', 'value'])
    base = float(d['MOD_STPR'].iloc[0])
    if base == 0:
        return pd.DataFrame(columns=['date', 'value'])
    return pd.DataFrame({
        'date': d['date'].values,
        'value': (d['MOD_STPR'].astype(float) / base * 100.0).round(3),
    }).reset_index(drop=True)


def load_fund_cashflow_markers(fund_code: str, start_date: str,
                               end_date: str) -> list:
    """펀드 설정/해지(DWPM12880) 현금흐름 — 자산군 '전체' 차트 + 거래내역 세부.

    방향은 **tr_cd** 로 판별 (ocpy_flct_amt 는 항상 양수 magnitude):
      A010=설정(자금 유입) / A030 일부해지·A230 외화일부해지=해지(자금 유출).
    같은 날·같은 방향 합산. 0.005억 미만(반올림 0)은 노이즈로 제외.
    Returns: list[{date, side('설정'|'해지'), amount(억, 양수)}] (날짜·설정먼저 정렬)
    """
    s8 = str(start_date).replace('-', '')
    e8 = str(end_date).replace('-', '')
    conn = get_pandas_connection('dt')
    try:
        df = pd.read_sql(
            """
            SELECT tr_dt, tr_cd, SUM(ocpy_flct_amt) AS amt
            FROM DWPM12880
            WHERE fund_cd = %s AND tr_dt >= %s AND tr_dt <= %s
            GROUP BY tr_dt, tr_cd
            """, conn, params=[fund_code, s8, e8])
    finally:
        conn.close()
    if df is None or df.empty:
        return []
    df['side'] = df['tr_cd'].map(lambda c: '설정' if str(c).strip() == 'A010' else '해지')
    g = df.groupby(['tr_dt', 'side'])['amt'].sum().reset_index()
    out = []
    for _, r in g.iterrows():
        eok = round(float(r['amt']) / 1e8, 2)
        if eok == 0:
            continue
        ds = str(r['tr_dt'])
        date_iso = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}" if len(ds) == 8 else ds
        out.append({'date': date_iso, 'side': str(r['side']), 'amount': eok})
    out.sort(key=lambda x: (x['date'], 0 if x['side'] == '설정' else 1))
    return out


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
