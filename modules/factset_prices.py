# -*- coding: utf-8 -*-
"""FactSet Formula API 가격 시계열 — BM 구성지수 대체 소스용 (로컬 캐시 경유).

배경: SCIP 에 없는 지수(현재 NASDAQ100 = `NDX`)를 BM 대체 소스로 쓰기 위한 최소 클라이언트.
Bloomberg 피드가 월 데이터 리밋으로 멈춘 구간을 메우는 용도이므로, 매 요청마다 외부
호출을 하지 않도록 **`.cache/factset_prices.sqlite` 에 영속 캐시**하고 하루 1회만
증분 갱신한다(최근 15영업일 재조회로 정정 흡수).

인증: TDF 프로젝트의 `.env`(NAME_SERIAL / API_KEY) 재사용 — 경로는 env
`FACTSET_ENV_PATH` 로 덮어쓸 수 있다. 사내 SSL 검사 프록시 때문에 `truststore` 가
있으면 Windows 인증서 저장소를 쓴다(없으면 그대로 시도하고, 실패 시 캐시만 사용).

env `OCIO_DISABLE_FACTSET=1` → 외부 호출 금지(캐시만).
"""
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / '.cache'
_CACHE_PATH = _CACHE_DIR / 'factset_prices.sqlite'
_DEFAULT_ENV = Path(r'C:\Users\user\Downloads\python\TDF\.env')
_URL = 'https://api.factset.com/formula-api/v1/time-series'
_REFRESH_DAYS = 15           # warm 갱신 시 재조회 구간(정정 흡수)
_HISTORY_DAYS = 2000         # 콜드 최초 적재 구간


def _conn() -> sqlite3.Connection:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_CACHE_PATH))
    c.execute(
        "CREATE TABLE IF NOT EXISTS fs_prices ("
        " fs_id TEXT NOT NULL, d TEXT NOT NULL, value REAL,"
        " PRIMARY KEY (fs_id, d))")
    c.execute("CREATE TABLE IF NOT EXISTS fs_meta ("
              " fs_id TEXT PRIMARY KEY, fetched_at TEXT)")
    return c


def _fetch(fs_id: str, days: int) -> pd.DataFrame:
    """FactSet time-series 호출 → DataFrame(d, value). 실패 시 빈 DF."""
    if os.environ.get('OCIO_DISABLE_FACTSET') == '1':
        return pd.DataFrame(columns=['d', 'value'])
    try:
        import requests
        try:
            import truststore
            truststore.inject_into_ssl()
        except Exception:
            pass                     # 프록시 CA 미설정 환경 — 그대로 시도
        env_path = Path(os.environ.get('FACTSET_ENV_PATH') or _DEFAULT_ENV)
        creds = {}
        if env_path.exists():
            for line in env_path.read_text(encoding='utf-8').splitlines():
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.split('=', 1)
                    creds[k.strip()] = v.strip()
        user = creds.get('NAME_SERIAL') or os.environ.get('NAME_SERIAL')
        key = creds.get('API_KEY') or os.environ.get('API_KEY')
        if not user or not key:
            logger.warning('FactSet 인증정보 없음 — 캐시만 사용 (%s)', env_path)
            return pd.DataFrame(columns=['d', 'value'])
        formula = f'P_PRICE(0,-{int(days)}D,D)'
        resp = requests.post(
            _URL, json={'data': {'ids': [fs_id], 'formulas': [formula],
                                 'flatten': 'Y'}},
            auth=(user, key), headers={'Accept': 'application/json'}, timeout=90)
        if resp.status_code != 200:
            logger.warning('FactSet %s HTTP %s', fs_id, resp.status_code)
            return pd.DataFrame(columns=['d', 'value'])
        rows = []
        for item in (resp.json() or {}).get('data', []):
            d = item.get('date')
            v = item.get(formula)
            if d is not None and v is not None:
                rows.append({'d': str(d)[:10], 'value': float(v)})
        return pd.DataFrame(rows, columns=['d', 'value'])
    except Exception as exc:
        logger.warning('FactSet %s 호출 실패: %s', fs_id, type(exc).__name__)
        return pd.DataFrame(columns=['d', 'value'])


def load_factset_price_series(fs_id: str, start_date: str = None) -> pd.DataFrame:
    """FactSet 가격 시계열 (캐시 우선, 하루 1회 증분 갱신).

    Returns: DataFrame(기준일자, value) — load_scip_bm_prices 동일 포맷.
    """
    con = _conn()
    try:
        row = con.execute("SELECT fetched_at FROM fs_meta WHERE fs_id=?",
                          (fs_id,)).fetchone()
        today = datetime.now().strftime('%Y-%m-%d')
        need = row is None or (row[0] or '')[:10] < today
        if need:
            days = _HISTORY_DAYS if row is None else _REFRESH_DAYS
            df = _fetch(fs_id, days)
            if not df.empty:
                con.executemany(
                    "INSERT OR REPLACE INTO fs_prices(fs_id,d,value) VALUES(?,?,?)",
                    [(fs_id, r.d, r.value) for r in df.itertuples()])
                con.execute(
                    "INSERT OR REPLACE INTO fs_meta(fs_id,fetched_at) VALUES(?,?)",
                    (fs_id, datetime.now().isoformat(timespec='seconds')))
                con.commit()
                logger.info('FactSet %s 캐시 갱신 %d건', fs_id, len(df))
        q = "SELECT d, value FROM fs_prices WHERE fs_id=?"
        params = [fs_id]
        if start_date:
            s = str(start_date).replace('-', '')
            q += " AND d >= ?"
            params.append(f'{s[:4]}-{s[4:6]}-{s[6:8]}')
        out = pd.read_sql_query(q + " ORDER BY d", con, params=params)
    finally:
        con.close()
    if out.empty:
        return pd.DataFrame(columns=['기준일자', 'value'])
    return pd.DataFrame({
        '기준일자': pd.to_datetime(out['d']),
        'value': out['value'].astype(float),
    })


def factset_series_max_date(fs_id: str):
    """캐시 갱신 포함 최신일 (없으면 None)."""
    df = load_factset_price_series(fs_id)
    if df.empty:
        return None
    return pd.Timestamp(df['기준일자'].max()).normalize()


# 하위호환/디버그용
def cache_path() -> Path:
    return _CACHE_PATH


def purge(fs_id: str = None) -> None:
    con = _conn()
    try:
        if fs_id:
            con.execute("DELETE FROM fs_prices WHERE fs_id=?", (fs_id,))
            con.execute("DELETE FROM fs_meta WHERE fs_id=?", (fs_id,))
        else:
            con.execute("DELETE FROM fs_prices")
            con.execute("DELETE FROM fs_meta")
        con.commit()
    finally:
        con.close()


# start_date 로부터 며칠 전까지 필요한지 계산할 때 쓰는 근사(참고용)
def _days_since(start_date: str) -> int:
    try:
        s = str(start_date).replace('-', '')
        d = datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return max(30, (datetime.now() - d).days + 10)
    except Exception:
        return _HISTORY_DAYS


__all__ = ['load_factset_price_series', 'factset_series_max_date',
           'cache_path', 'purge', '_days_since']
