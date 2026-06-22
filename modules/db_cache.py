"""DB OCIO — 거래내역/보유 영속 캐시 (SQLite).

warm-up 시 DWPM10530(보유)·DWPM10520(거래)의 과거 영업일 데이터는 사후 정정이
드물어 사실상 불변이다. 이를 로컬 SQLite 에 영속화해 두고, 재기동(uvicorn 인메모리
캐시 소멸) 때는 **최근 N영업일만 재조회**(정정 흡수 + 신규일)하여 콜드 로드를 단축한다.

설계:
- 원시 SQL 결과 컬럼만 저장한다. 분류(_classify_6class 등)는 호출부가 읽을 때 수행 →
  분류 규칙이 바뀌어도 캐시가 stale 되지 않는다.
- 캐시 단위: (table, fund_cd). std_dt(YYYYMMDD int) 가 일자 키.
- 증분 정책: 캐시가 있으면 저장된 최근 N영업일(=std_dt 상위 N개)을 삭제 후 그 지점~end
  를 재조회(신규일 포함). 요청 start 가 캐시 최소일보다 앞서면 앞 구간만 백필.
- 동시성: warm-up 데몬 스레드 ↔ FastAPI 요청 동시 접근 → 모듈 Lock + WAL.
- 안전장치: env OCIO_DISABLE_DB_CACHE=1 → 캐시 우회(직접 DB). 증분 조회 실패 시
  기존 캐시본을 유지해 graceful fallback. 콜드(캐시 없음) 조회 실패는 그대로 전파
  (호출부가 mock fallback 처리).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)

# 정정 흡수 윈도우 — 저장된 최근 N영업일은 매 기동 시 재조회·덮어쓰기.
_N_OVERWRITE_BDAYS = 5

_DISABLED = os.environ.get("OCIO_DISABLE_DB_CACHE") == "1"

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".cache", "db_cache.sqlite",
)

_lock = threading.RLock()
_initialized = False


@dataclass(frozen=True)
class _TableSpec:
    name: str
    cols: tuple  # ((col, sqltype), ...) — 첫 컬럼이 일자(std_dt) 키

    @property
    def date_col(self) -> str:
        return self.cols[0][0]

    @property
    def col_names(self) -> list:
        return [c for c, _ in self.cols]


# 컬럼명은 각 호출부가 기대하는 이름과 동일하게 둔다(읽은 뒤 rename 불필요).
HOLDINGS = _TableSpec("holdings", (
    ("STD_DT", "INTEGER"), ("ITEM_CD", "TEXT"), ("ITEM_NM", "TEXT"),
    ("AST_CLSF_CD_NM", "TEXT"), ("CURR_DS_CD", "TEXT"), ("EVL_AMT", "REAL"),
))
# "trades_v2": stl_amt/krw_stl_amt(원화 환산용) 추가로 스키마 변경 → 신규 테이블명으로
# 콜드 재조회 강제(기존 "trades" 캐시는 외화 매매금액이 외화단위로 박혀 있어 폐기).
TRADES = _TableSpec("trades_v2", (
    ("std_dt", "INTEGER"), ("item_cd", "TEXT"), ("item_nm", "TEXT"),
    ("curr_ds_cd", "TEXT"), ("buy_sell_ds_cd", "TEXT"), ("trd_amt", "REAL"),
    ("stl_amt", "REAL"), ("krw_stl_amt", "REAL"),
    ("tr_cd", "TEXT"), ("tr_nm", "TEXT"),
))


def _ensure_init() -> None:
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
        con = sqlite3.connect(_DB_PATH)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            for spec in (HOLDINGS, TRADES):
                cols_sql = ", ".join(f'"{c}" {t}' for c, t in spec.cols)
                con.execute(
                    f'CREATE TABLE IF NOT EXISTS "{spec.name}" '
                    f'("fund_cd" TEXT, {cols_sql})')
                con.execute(
                    f'CREATE INDEX IF NOT EXISTS "idx_{spec.name}" '
                    f'ON "{spec.name}" ("fund_cd", "{spec.date_col}")')
            con.commit()
        finally:
            con.close()
        _initialized = True


def _coerce_for_store(spec: _TableSpec, df: pd.DataFrame) -> pd.DataFrame:
    """fetch 결과를 스키마 타입에 맞춰 정규화(NULL 보존)."""
    out = df[spec.col_names].copy()
    for col, typ in spec.cols:
        if typ == "INTEGER":
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("int64")
        elif typ == "REAL":
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:  # TEXT — NULL 은 None 으로 보존('None'/'nan' 문자열화 방지)
            out[col] = out[col].apply(lambda v: None if pd.isna(v) else str(v))
    return out


def _nth_recent_date(con, spec: _TableSpec, fund_cd: str, n: int):
    cur = con.execute(
        f'SELECT DISTINCT "{spec.date_col}" FROM "{spec.name}" '
        f'WHERE fund_cd=? ORDER BY "{spec.date_col}" DESC LIMIT ?',
        (fund_cd, n))
    rows = [r[0] for r in cur.fetchall()]
    return rows[-1] if rows else None  # N개면 N번째 최신, 부족하면 최소일


def _delete_range(con, spec: _TableSpec, fund_cd: str, lo: int, hi: int) -> None:
    con.execute(
        f'DELETE FROM "{spec.name}" WHERE fund_cd=? AND "{spec.date_col}" '
        f'BETWEEN ? AND ?', (fund_cd, lo, hi))


def _insert(con, spec: _TableSpec, fund_cd: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    d = _coerce_for_store(spec, df)
    d.insert(0, "fund_cd", fund_cd)
    d.to_sql(spec.name, con, if_exists="append", index=False)


def _read_range(con, spec: _TableSpec, fund_cd: str, lo: int, hi: int) -> pd.DataFrame:
    cols = ", ".join(f'"{c}"' for c in spec.col_names)
    return pd.read_sql(
        f'SELECT {cols} FROM "{spec.name}" WHERE fund_cd=? AND "{spec.date_col}" '
        f'BETWEEN ? AND ?', con, params=(fund_cd, lo, hi))


def _refresh(con, spec, fund_cd, lo, hi, fetch_fn, required: bool) -> None:
    """[lo,hi] 를 DB 에서 재조회해 교체(fetch→delete→insert→commit).
    required=False 이고 조회 실패 시 기존 캐시 유지(graceful)."""
    try:
        df_new = fetch_fn(lo, hi)
    except Exception:
        if required:
            raise
        logger.warning("db_cache: 증분 조회 실패 → 캐시 유지 (%s/%s [%s,%s])",
                       spec.name, fund_cd, lo, hi)
        return
    _delete_range(con, spec, fund_cd, lo, hi)
    _insert(con, spec, fund_cd, df_new)
    con.commit()


def get_cached_range(spec: _TableSpec, fund_cd: str,
                     start_int, end_int, fetch_fn) -> pd.DataFrame:
    """(spec, fund_cd) 의 [start_int, end_int] 행을 캐시 우선으로 반환.

    fetch_fn(lo, hi) -> DataFrame: 해당 일자범위의 원시 행(spec.col_names 컬럼).
    start_int=None → 0, end_int=None → 99999999 로 정규화.
    """
    s = 0 if start_int is None else int(start_int)
    e = 99999999 if end_int is None else int(end_int)

    if _DISABLED:
        return fetch_fn(s, e)

    _ensure_init()
    with _lock:
        con = sqlite3.connect(_DB_PATH)
        try:
            cur = con.execute(
                f'SELECT MIN("{spec.date_col}"), MAX("{spec.date_col}") '
                f'FROM "{spec.name}" WHERE fund_cd=?', (fund_cd,))
            cmin, cmax = cur.fetchone()

            if cmin is None:
                # 콜드: 요청 범위 전량 조회(실패 시 전파)
                _refresh(con, spec, fund_cd, s, e, fetch_fn, required=True)
            else:
                # 최근 N영업일 + 신규일 재조회(정정 흡수)
                cutoff = _nth_recent_date(con, spec, fund_cd, _N_OVERWRITE_BDAYS)
                _refresh(con, spec, fund_cd, cutoff, max(e, cmax),
                         fetch_fn, required=False)
                # 요청 시작이 캐시 이전이면 앞 구간 백필
                if s < cmin:
                    _refresh(con, spec, fund_cd, s, cmin - 1,
                             fetch_fn, required=False)

            return _read_range(con, spec, fund_cd, s, e)
        finally:
            con.close()
