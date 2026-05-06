# -*- coding: utf-8 -*-
"""
운용보고 코멘트 생성 엔진
SCIP 벤치마크 + 펀드 포지션/PA → 펀드별 운용보고 코멘트
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from decimal import Decimal
from dateutil.relativedelta import relativedelta

import pymysql
import pandas as pd
import numpy as np
import anthropic

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
DIGEST_DIR = BASE_DIR / "data" / "monygeek" / "monthly_digests"

# ── core/ 에서 공유 설정 임포트 ──
from market_research.core.db import DB_CONFIG, get_conn as _get_conn_core, parse_blob as _parse_blob_core
from market_research.core.benchmarks import BENCHMARK_MAP
from market_research.core.constants import FUND_CONFIGS, ANTHROPIC_API_KEY, LLM_MODEL, PA_CLASSIFICATION_RULES


# ═══════════════════════════════════════════════════════
# 1. 설정
# ═══════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════
# 2. 데이터 로딩 — core/ 래퍼
# ═══════════════════════════════════════════════════════

def _get_conn(db='SCIP'):
    return _get_conn_core(db)


def _parse_blob(blob, blob_key=None):
    return _parse_blob_core(blob, blob_key)


def load_business_days(year, month):
    """영업일 조회 — 해당월 첫/마지막, 전월 마지막"""
    conn = _get_conn('dt')
    cur = conn.cursor()

    # 전월~해당월 영업일
    if month == 1:
        prev_start = f'{year-1}1201'
    else:
        prev_start = f'{year}{month-1:02d}01'
    end = f'{year}{month:02d}31'

    cur.execute("""SELECT CAST(std_dt AS UNSIGNED) as d FROM DWCI10220
                   WHERE hldy_yn='N' AND day_ds_cd IN (2,3,4,5,6)
                   AND std_dt BETWEEN %s AND %s ORDER BY std_dt""", (prev_start, end))
    bdays = [r['d'] for r in cur.fetchall()]
    conn.close()

    month_start = year * 10000 + month * 100 + 1
    month_end = year * 10000 + month * 100 + 31

    prev_month_last = max(d for d in bdays if d < month_start)
    cur_month_days = [d for d in bdays if month_start <= d <= month_end]
    cur_month_last = max(cur_month_days) if cur_month_days else None

    return {
        'prev_month_last': prev_month_last,
        'cur_month_first': min(cur_month_days) if cur_month_days else None,
        'cur_month_last': cur_month_last,
        'business_days': len(cur_month_days),
    }


def _quarter_dates(year, quarter):
    """분기 시작/끝 월 반환. Q1→(1,3), Q2→(4,6), Q3→(7,9), Q4→(10,12)"""
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    return start_month, end_month


def load_business_days_quarter(year, quarter):
    """분기 영업일 — 전분기말, 분기말 영업일 반환"""
    start_month, end_month = _quarter_dates(year, quarter)
    # 전분기말 영업일
    if start_month == 1:
        prev_bdays = load_business_days(year - 1, 12)
    else:
        prev_bdays = load_business_days(year, start_month - 1)
    # 분기말 영업일
    end_bdays = load_business_days(year, end_month)
    return {
        'prev_month_last': prev_bdays['cur_month_last'],   # 전분기말
        'cur_month_last': end_bdays['cur_month_last'],     # 분기말
        'cur_month_first': load_business_days(year, start_month).get('cur_month_first'),
        'start_dt': f'{year}{start_month:02d}01',
        'end_dt': f'{year}{end_month:02d}31',
    }


def load_benchmark_returns_quarter(year, quarter):
    """32개 벤치마크 분기 누적 수익률 — 지수값 직접 비교"""
    qdays = load_business_days_quarter(year, quarter)
    # load_benchmark_returns와 동일 로직이지만 날짜 범위가 분기
    # 기존 함수의 bdays를 qdays로 대체하여 호출
    class _FakeBdays:
        pass
    bdays = _FakeBdays()
    # monkey-patch 대신 직접 계산
    return _load_bm_returns_for_range(qdays['prev_month_last'], qdays['cur_month_last'])


def _load_bm_returns_for_range(prev_last_int, cur_last_int):
    """지정 기간의 벤치마크 수익률 (공용 내부 함수)"""
    def _int_to_date(d):
        return f'{d // 10000}-{(d % 10000) // 100:02d}-{d % 100:02d}'

    prev_dt = _int_to_date(prev_last_int)
    cur_dt = _int_to_date(cur_last_int)

    ds_ids = list(set(cfg['dataset_id'] for cfg in BENCHMARK_MAP.values()))
    dser_ids = list(set(cfg['ds_id'] for cfg in BENCHMARK_MAP.values()))

    conn = _get_conn('SCIP')
    cur = conn.cursor()
    ds_ph = ','.join(str(d) for d in ds_ids)
    dser_ph = ','.join(str(d) for d in dser_ids)
    cur.execute(f"""SELECT dataset_id, dataseries_id, data, timestamp_observation
                    FROM back_datapoint
                    WHERE dataset_id IN ({ds_ph})
                    AND dataseries_id IN ({dser_ph})
                    AND timestamp_observation BETWEEN DATE_SUB(%s, INTERVAL 5 DAY) AND DATE_ADD(%s, INTERVAL 1 DAY)
                    ORDER BY dataset_id, dataseries_id, timestamp_observation""",
                (prev_dt, cur_dt))
    all_rows = cur.fetchall()
    conn.close()

    ts_data = {}
    for r in all_rows:
        key = (r['dataset_id'], r['dataseries_id'])
        dt_str = str(r['timestamp_observation'])[:10]
        val = _parse_blob(r['data'])
        if isinstance(val, dict):
            for ccy, v in val.items():
                ts_data.setdefault((*key, ccy), []).append((dt_str, v))
            default_val = val.get('USD', val.get('KRW', list(val.values())[0]))
            ts_data.setdefault((*key, None), []).append((dt_str, default_val))
        else:
            ts_data.setdefault((*key, None), []).append((dt_str, val))

    results = {}
    for name, cfg in BENCHMARK_MAP.items():
        blob_key = cfg.get('blob_key')
        key = (cfg['dataset_id'], cfg['ds_id'], blob_key)
        series = ts_data.get(key, [])
        if not series:
            key_fallback = (cfg['dataset_id'], cfg['ds_id'], None)
            series = ts_data.get(key_fallback, [])
        if not series:
            results[name] = {'return': None}
            continue

        prev_val = _closest_value(series, prev_dt)
        cur_val = _closest_value(series, cur_dt)

        if prev_val and cur_val and prev_val != 0:
            results[name] = {
                'return': (cur_val / prev_val - 1) * 100,
                'level': cur_val,
                'prev': prev_val,
            }
        else:
            results[name] = {'return': None}

    return results


def load_bm_price_patterns(prev_last_int, cur_last_int, targets=None):
    """기간 내 BM 일별 시계열 패턴 분석 (저점/고점/MDD/반등).

    Parameters
    ----------
    prev_last_int, cur_last_int : int (YYYYMMDD)
    targets : list[str] | None — 분석 대상 BM 이름. None이면 주요 12개

    Returns
    -------
    dict: {bm_name: {low_date, low_ret, high_date, high_ret, mdd, rebound, pattern}}
    """
    if targets is None:
        targets = ['S&P500', '미국성장주', '미국가치주', 'KOSPI', '미국외선진국', '신흥국주식',
                   '미국종합채권', 'KAP종합채권', 'Gold', 'WTI', 'DXY', 'USDKRW']

    def _int_to_date(d):
        return f'{d // 10000}-{(d % 10000) // 100:02d}-{d % 100:02d}'

    prev_dt = _int_to_date(prev_last_int)
    cur_dt = _int_to_date(cur_last_int)

    # 전체 기간 일별 데이터 로드
    target_configs = {n: BENCHMARK_MAP[n] for n in targets if n in BENCHMARK_MAP}
    ds_ids = list(set(c['dataset_id'] for c in target_configs.values()))
    dser_ids = list(set(c['ds_id'] for c in target_configs.values()))

    conn = _get_conn('SCIP')
    cur = conn.cursor()
    ds_ph = ','.join(str(d) for d in ds_ids)
    dser_ph = ','.join(str(d) for d in dser_ids)
    cur.execute(f"""SELECT dataset_id, dataseries_id, data, timestamp_observation
                    FROM back_datapoint
                    WHERE dataset_id IN ({ds_ph})
                    AND dataseries_id IN ({dser_ph})
                    AND timestamp_observation BETWEEN DATE_SUB(%s, INTERVAL 5 DAY) AND DATE_ADD(%s, INTERVAL 1 DAY)
                    ORDER BY dataset_id, dataseries_id, timestamp_observation""",
                (prev_dt, cur_dt))
    all_rows = cur.fetchall()
    conn.close()

    # 시계열 구축
    ts_data = {}
    for r in all_rows:
        key = (r['dataset_id'], r['dataseries_id'])
        dt_str = str(r['timestamp_observation'])[:10]
        val = _parse_blob(r['data'])
        if isinstance(val, dict):
            for ccy, v in val.items():
                ts_data.setdefault((*key, ccy), []).append((dt_str, v))
            default_val = val.get('USD', val.get('KRW', list(val.values())[0]))
            ts_data.setdefault((*key, None), []).append((dt_str, default_val))
        else:
            ts_data.setdefault((*key, None), []).append((dt_str, val))

    results = {}
    for name, cfg in target_configs.items():
        blob_key = cfg.get('blob_key')
        key = (cfg['dataset_id'], cfg['ds_id'], blob_key)
        series = ts_data.get(key, [])
        if not series:
            key_fallback = (cfg['dataset_id'], cfg['ds_id'], None)
            series = ts_data.get(key_fallback, [])
        if len(series) < 3:
            continue

        # 기간 시작값 (prev_dt에 가장 가까운)
        base_val = _closest_value(series, prev_dt)
        if not base_val or base_val == 0:
            continue

        # 일별 수익률 시계열
        daily = []
        for dt_str, val in sorted(series):
            if dt_str <= prev_dt:
                continue
            ret = (val / base_val - 1) * 100
            daily.append({'date': dt_str, 'value': val, 'return': ret})

        if not daily:
            continue

        # 패턴 분석
        returns = [d['return'] for d in daily]
        min_idx = returns.index(min(returns))
        max_idx = returns.index(max(returns))

        low_d = daily[min_idx]
        high_d = daily[max_idx]
        end_d = daily[-1]

        # MDD: 기간 내 최대 낙폭
        running_max = base_val
        mdd = 0
        for d in daily:
            if d['value'] > running_max:
                running_max = d['value']
            dd = (d['value'] / running_max - 1) * 100
            if dd < mdd:
                mdd = dd

        # 저점 이후 반등 (저점이 기간 후반 30% 이전에 있을 때만)
        rebound = end_d['return'] - low_d['return'] if min_idx < len(daily) - 1 else 0

        results[name] = {
            'low_date': low_d['date'],
            'low_return': round(low_d['return'], 2),
            'high_date': high_d['date'],
            'high_return': round(high_d['return'], 2),
            'end_return': round(end_d['return'], 2),
            'mdd': round(mdd, 2),
            'rebound': round(rebound, 2),
        }

    return results


def load_fund_return_quarter(fund_code, year, quarter):
    """펀드 분기 수익률 — MOD_STPR 분기초/분기말 비교"""
    qdays = load_business_days_quarter(year, quarter)
    conn = _get_conn('dt')
    cur = conn.cursor()

    # 분기말 최신 가용일
    cur.execute("""SELECT MAX(STD_DT) as max_dt FROM DWPM10510
                   WHERE FUND_CD=%s AND STD_DT BETWEEN %s AND %s""",
                (fund_code, qdays['start_dt'], qdays['end_dt']))
    max_row = cur.fetchone()
    actual_last = max_row['max_dt'] if max_row and max_row['max_dt'] else qdays['cur_month_last']

    cur.execute("""SELECT STD_DT, MOD_STPR, NAST_AMT
                   FROM DWPM10510 WHERE FUND_CD=%s AND STD_DT IN (%s, %s)
                   ORDER BY STD_DT""",
                (fund_code, qdays['prev_month_last'], actual_last))
    rows = cur.fetchall()
    conn.close()

    if len(rows) == 2:
        prev_stpr = float(rows[0]['MOD_STPR'])
        cur_stpr = float(rows[1]['MOD_STPR'])
        ret = (cur_stpr / prev_stpr - 1) * 100
        result = {
            'return': ret,
            'prev_stpr': prev_stpr,
            'cur_stpr': cur_stpr,
            'aum': float(rows[1]['NAST_AMT']),
        }
        cfg = FUND_CONFIGS.get(fund_code, {})
        if cfg.get('sub_portfolios'):
            conn2 = _get_conn('dt')
            cur2 = conn2.cursor()
            result['sub_returns'] = {}
            for label, sub_code in cfg['sub_portfolios'].items():
                cur2.execute("""SELECT MOD_STPR FROM DWPM10510
                               WHERE FUND_CD=%s AND STD_DT IN (%s, %s) ORDER BY STD_DT""",
                             (sub_code, qdays['prev_month_last'], qdays['cur_month_last']))
                sub_rows = cur2.fetchall()
                if len(sub_rows) == 2:
                    sub_ret = (float(sub_rows[1]['MOD_STPR']) / float(sub_rows[0]['MOD_STPR']) - 1) * 100
                    result['sub_returns'][label] = sub_ret
            conn2.close()
        return result
    return None


def load_all_pa_attributions_quarter(fund_codes, year, quarter):
    """복수 펀드 PA 분기 일괄 — 날짜 범위만 분기로 확장"""
    qdays = load_business_days_quarter(year, quarter)
    start_dt = qdays['start_dt']
    end_dt = qdays['end_dt']

    conn = _get_conn('dt')
    cur = conn.cursor()

    fc_ph = ','.join(f"'{f}'" for f in fund_codes)
    cur.execute(f"""SELECT FUND_CD, MOD_STPR FROM DWPM10510
                    WHERE FUND_CD IN ({fc_ph}) AND STD_DT={qdays['prev_month_last']}""")
    stpr_map = {r['FUND_CD']: float(r['MOD_STPR']) for r in cur.fetchall()}

    cur.execute(f"""SELECT FUND_ID, ASSET_GB, OS_GB, SEC_ID, SUM(MODIFY_UNAV_CHG) as chg
                    FROM MA000410 WHERE FUND_ID IN ({fc_ph})
                    AND PR_DATE BETWEEN '{start_dt}' AND '{end_dt}'
                    GROUP BY FUND_ID, ASSET_GB, OS_GB, SEC_ID""")
    pa_rows = cur.fetchall()

    sec_ids = list(set(r['SEC_ID'] for r in pa_rows))
    item_names = {}
    if sec_ids:
        for i in range(0, len(sec_ids), 50):
            batch = sec_ids[i:i+50]
            sec_ph = ','.join(f"'{s}'" for s in batch)
            cur.execute(f"""SELECT ITEM_CD, ITEM_NM FROM DWPM10530
                           WHERE ITEM_CD IN ({sec_ph})
                           AND STD_DT BETWEEN {start_dt} AND {end_dt}
                           ORDER BY STD_DT DESC""")
            for r in cur.fetchall():
                if r['ITEM_CD'] not in item_names:
                    item_names[r['ITEM_CD']] = r['ITEM_NM']

    universe_map = {}
    try:
        conn_sol = _get_conn('solution')
        cur_sol = conn_sol.cursor()
        if sec_ids:
            for i in range(0, len(sec_ids), 50):
                batch = sec_ids[i:i+50]
                sec_ph = ','.join(f"'{s}'" for s in batch)
                cur_sol.execute(f"""SELECT ISIN, classification FROM universe_non_derivative
                                   WHERE classification_method='방법3'
                                   AND ISIN IN ({sec_ph})
                                   AND classification IS NOT NULL""")
                for r in cur_sol.fetchall():
                    universe_map[r['ISIN']] = r['classification']
        conn_sol.close()
    except Exception:
        pass

    conn.close()

    results = {}
    for fund_code in fund_codes:
        base_stpr = stpr_map.get(fund_code, 1000)
        fund_rows = [r for r in pa_rows if r['FUND_ID'] == fund_code]
        asset_contrib = {}
        for r in fund_rows:
            nm = item_names.get(r['SEC_ID'], '')
            cls = universe_map.get(r['SEC_ID'])
            if not cls:
                cls = _classify_pa_item(r['ASSET_GB'], r['OS_GB'], nm)
            asset_contrib[cls] = asset_contrib.get(cls, 0) + float(r['chg'])
        results[fund_code] = {cls: round(chg / base_stpr * 100, 2)
                              for cls, chg in asset_contrib.items()}
    return results


def load_fund_holdings_summary_quarter(fund_code, year, quarter):
    """분기말 보유비중 — 분기 마지막 월 기준"""
    _, end_month = _quarter_dates(year, quarter)
    return load_fund_holdings_summary(fund_code, year, end_month)


def load_benchmark_returns(year, month):
    """32개 벤치마크 월간 수익률 계산 — 일괄 쿼리"""
    bdays = load_business_days(year, month)
    prev_last = bdays['prev_month_last']
    cur_last = bdays['cur_month_last']

    def _int_to_date(d):
        return f'{d // 10000}-{(d % 10000) // 100:02d}-{d % 100:02d}'

    prev_dt = _int_to_date(prev_last)
    cur_dt = _int_to_date(cur_last)

    # dataset_id 목록
    ds_ids = list(set(cfg['dataset_id'] for cfg in BENCHMARK_MAP.values()))
    dser_ids = list(set(cfg['ds_id'] for cfg in BENCHMARK_MAP.values()))

    conn = _get_conn('SCIP')
    cur = conn.cursor()

    # dataset_id IN (...) + dataseries_id IN (...) 로 일괄 조회
    ds_ph = ','.join(str(d) for d in ds_ids)
    dser_ph = ','.join(str(d) for d in dser_ids)
    cur.execute(f"""SELECT dataset_id, dataseries_id, data, timestamp_observation
                    FROM back_datapoint
                    WHERE dataset_id IN ({ds_ph})
                    AND dataseries_id IN ({dser_ph})
                    AND timestamp_observation BETWEEN DATE_SUB(%s, INTERVAL 5 DAY) AND DATE_ADD(%s, INTERVAL 1 DAY)
                    ORDER BY dataset_id, dataseries_id, timestamp_observation""",
                (prev_dt, cur_dt))
    all_rows = cur.fetchall()
    conn.close()

    # (dataset_id, dataseries_id) → 시계열 dict
    ts_data = {}
    for r in all_rows:
        key = (r['dataset_id'], r['dataseries_id'])
        dt_str = str(r['timestamp_observation'])[:10]
        val = _parse_blob(r['data'])
        # dict인 경우 통화별로 별도 저장
        if isinstance(val, dict):
            for ccy, v in val.items():
                ts_data.setdefault((*key, ccy), []).append((dt_str, v))
            # 기본값도 저장 (USD 우선)
            default_val = val.get('USD', val.get('KRW', list(val.values())[0]))
            ts_data.setdefault((*key, None), []).append((dt_str, default_val))
        else:
            ts_data.setdefault((*key, None), []).append((dt_str, val))

    # 벤치마크별 전월말/당월말 값 추출
    results = {}
    for name, cfg in BENCHMARK_MAP.items():
        blob_key = cfg.get('blob_key')  # 'KRW', 'USD', None
        key = (cfg['dataset_id'], cfg['ds_id'], blob_key)
        series = ts_data.get(key, [])
        if not series:
            # fallback: None 키
            key_fallback = (cfg['dataset_id'], cfg['ds_id'], None)
            series = ts_data.get(key_fallback, [])
        if not series:
            results[name] = {'return': None}
            continue

        prev_val = _closest_value(series, prev_dt)
        cur_val = _closest_value(series, cur_dt)

        if prev_val and cur_val and prev_val != 0:
            results[name] = {
                'return': (cur_val / prev_val - 1) * 100,
                'level': cur_val,
                'prev': prev_val,
            }
        else:
            results[name] = {'return': None}

    return results


INDEX_CONTEXT_MAP = {
    'KOSPI': {'dataset_id': 253, 'ds_id': 15, 'blob_key': 'KRW', 'unit': '포인트'},
    'S&P500': {'dataset_id': 271, 'ds_id': 6, 'blob_key': 'USD', 'unit': '포인트'},
    'USDKRW': {'dataset_id': 31, 'ds_id': 6, 'blob_key': 'USD', 'unit': '원'},
    'WTI': {'dataset_id': 98, 'ds_id': 15, 'blob_key': None, 'unit': '달러'},
    'Gold': {'dataset_id': 408, 'ds_id': 48, 'blob_key': None, 'unit': '달러'},
    'DXY': {'dataset_id': 105, 'ds_id': 6, 'blob_key': 'USD', 'unit': ''},
}

# 12M Fwd EPS 매핑 (dataseries_id=31)
EPS_MAP = {
    'S&P500': {'dataset_id': 24, 'name': 'S&P 500'},
    'MSCI Korea': {'dataset_id': 144, 'name': 'MSCI South Korea'},
    'US Growth': {'dataset_id': 11, 'name': 'Vanguard Growth'},
    'US Value': {'dataset_id': 12, 'name': 'Vanguard Value'},
    'MSCI EAFE': {'dataset_id': 63, 'name': 'MSCI EAFE'},
    'MSCI EM': {'dataset_id': 37, 'name': 'Vanguard EM'},
}


def load_index_context(year, month):
    """주요 지수의 전월~당월 고점/저점/MDD 등 맥락 데이터 로드."""
    # 전월 1일 ~ 당월 말일 범위로 조회
    if month == 1:
        prev_start = f'{year-1}-12-01'
    else:
        prev_start = f'{year}-{month-1:02d}-01'
    end = f'{year}-{month:02d}-31'
    month_start = f'{year}-{month:02d}-01'

    conn = _get_conn('SCIP')
    cur = conn.cursor()

    results = {}
    for name, cfg in INDEX_CONTEXT_MAP.items():
        cur.execute("""SELECT DATE(timestamp_observation) as dt, data
                       FROM back_datapoint WHERE dataset_id=%s AND dataseries_id=%s
                       AND timestamp_observation BETWEEN %s AND %s
                       ORDER BY timestamp_observation""",
                    (cfg['dataset_id'], cfg['ds_id'], prev_start, end))
        rows = cur.fetchall()
        if not rows:
            continue

        vals = []
        for r in rows:
            v = _parse_blob(r['data'], cfg.get('blob_key'))
            if v is not None and not isinstance(v, dict):
                vals.append((str(r['dt']), float(v)))
            elif isinstance(v, dict):
                key = cfg.get('blob_key') or list(v.keys())[0]
                vals.append((str(r['dt']), float(v.get(key, 0))))

        if not vals:
            continue

        # 전체 범위 고점/저점
        peak = max(vals, key=lambda x: x[1])
        trough = min(vals, key=lambda x: x[1])

        # 당월만
        month_vals = [(d, v) for d, v in vals if d >= month_start]
        month_last = month_vals[-1] if month_vals else vals[-1]

        # 전월말
        prev_vals = [(d, v) for d, v in vals if d < month_start]
        prev_last = prev_vals[-1] if prev_vals else vals[0]

        # 월간 수익률
        monthly_ret = (month_last[1] / prev_last[1] - 1) * 100 if prev_last[1] != 0 else 0

        # 고점 대비 당월말 하락률
        peak_to_end = (month_last[1] / peak[1] - 1) * 100 if peak[1] != 0 else 0

        # 당월 내 고점/저점
        month_peak = max(month_vals, key=lambda x: x[1]) if month_vals else peak
        month_trough = min(month_vals, key=lambda x: x[1]) if month_vals else trough

        results[name] = {
            'prev_last': {'date': prev_last[0], 'value': round(prev_last[1], 2)},
            'month_last': {'date': month_last[0], 'value': round(month_last[1], 2)},
            'peak': {'date': peak[0], 'value': round(peak[1], 2)},
            'trough': {'date': trough[0], 'value': round(trough[1], 2)},
            'month_peak': {'date': month_peak[0], 'value': round(month_peak[1], 2)},
            'month_trough': {'date': month_trough[0], 'value': round(month_trough[1], 2)},
            'monthly_return': round(monthly_ret, 2),
            'peak_to_end': round(peak_to_end, 2),
            'unit': cfg['unit'],
        }

    # ── EPS 변화 추가 ──
    eps_data = {}
    cur2 = _get_conn('SCIP').cursor()
    for eps_name, eps_cfg in EPS_MAP.items():
        cur2.execute("""SELECT DATE(timestamp_observation) as dt, data
                        FROM back_datapoint WHERE dataset_id=%s AND dataseries_id=31
                        AND timestamp_observation BETWEEN %s AND %s
                        ORDER BY timestamp_observation""",
                     (eps_cfg['dataset_id'], prev_start, end))
        eps_rows = cur2.fetchall()
        eps_vals = []
        for r in eps_rows:
            v = _parse_blob(r['data'])
            if v is not None and not isinstance(v, dict):
                eps_vals.append((str(r['dt']), float(v)))
        if eps_vals:
            prev_eps = [(d, v) for d, v in eps_vals if d < month_start]
            cur_eps = [(d, v) for d, v in eps_vals if d >= month_start]
            if prev_eps and cur_eps:
                prev_v = prev_eps[-1][1]
                cur_v = cur_eps[-1][1]
                chg = (cur_v / prev_v - 1) * 100 if prev_v != 0 else 0
                eps_data[eps_name] = {
                    'prev': round(prev_v, 2),
                    'current': round(cur_v, 2),
                    'change_pct': round(chg, 2),
                }
    cur2.connection.close()
    results['_eps'] = eps_data

    conn.close()
    return results


def load_benchmark_period_returns(ref_date=None):
    """32개 벤치마크의 다기간 수익률 계산 (1D, 1W, 1M, 3M, 6M, 1Y, YTD)

    SCIP DB에서 직접 조회. ref_date가 None이면 가장 최근 영업일 기준.

    Returns: dict of {benchmark_name: {'1D': x, '1W': x, '1M': x, ..., 'level': x, 'ref_date': 'YYYY-MM-DD'}}
    """
    conn = _get_conn('SCIP')
    cur = conn.cursor()

    ds_ids = list(set(cfg['dataset_id'] for cfg in BENCHMARK_MAP.values()))
    dser_ids = list(set(cfg['ds_id'] for cfg in BENCHMARK_MAP.values()))
    ds_ph = ','.join(str(d) for d in ds_ids)
    dser_ph = ','.join(str(d) for d in dser_ids)

    # ── ref_date 결정 ──
    if ref_date is None:
        cur.execute(f"""SELECT MAX(DATE(timestamp_observation)) AS max_dt
                        FROM back_datapoint
                        WHERE dataset_id IN ({ds_ph})
                        AND dataseries_id IN ({dser_ph})""")
        row = cur.fetchone()
        ref_date = row['max_dt']
        if ref_date is None:
            conn.close()
            return {}
    if isinstance(ref_date, str):
        ref_date = datetime.strptime(ref_date, '%Y-%m-%d').date()

    ref_dt_str = ref_date.strftime('%Y-%m-%d')

    # ── 기간별 목표일 계산 ──
    period_targets = {
        '1D': ref_date - timedelta(days=1),
        '1W': ref_date - timedelta(days=7),
        '1M': ref_date - relativedelta(months=1),
        '3M': ref_date - relativedelta(months=3),
        '6M': ref_date - relativedelta(months=6),
        '1Y': ref_date - relativedelta(years=1),
        'YTD': date(ref_date.year, 1, 1),
    }

    # ── 기간별로 개별 쿼리 (각 목표일 ±5일) ──
    ts_data = {}  # (dataset_id, dataseries_id, blob_key) → [(dt_str, value), ...]

    def _ingest_rows(rows):
        for r in rows:
            key = (r['dataset_id'], r['dataseries_id'])
            dt_str = str(r['timestamp_observation'])[:10]
            val = _parse_blob(r['data'])
            if isinstance(val, dict):
                for ccy, v in val.items():
                    ts_data.setdefault((*key, ccy), []).append((dt_str, v))
                default_val = val.get('USD', val.get('KRW', list(val.values())[0]))
                ts_data.setdefault((*key, None), []).append((dt_str, default_val))
            elif val is not None:
                ts_data.setdefault((*key, None), []).append((dt_str, val))

    # ref_date 쿼리 (±5일)
    cur.execute(f"""SELECT dataset_id, dataseries_id, data, timestamp_observation
                    FROM back_datapoint
                    WHERE dataset_id IN ({ds_ph})
                    AND dataseries_id IN ({dser_ph})
                    AND timestamp_observation BETWEEN DATE_SUB(%s, INTERVAL 5 DAY) AND DATE_ADD(%s, INTERVAL 1 DAY)
                    ORDER BY dataset_id, dataseries_id, timestamp_observation""",
                (ref_dt_str, ref_dt_str))
    _ingest_rows(cur.fetchall())

    # 각 기간 시작일 쿼리 (±5일)
    for period, target_dt in period_targets.items():
        t_str = target_dt.strftime('%Y-%m-%d')
        cur.execute(f"""SELECT dataset_id, dataseries_id, data, timestamp_observation
                        FROM back_datapoint
                        WHERE dataset_id IN ({ds_ph})
                        AND dataseries_id IN ({dser_ph})
                        AND timestamp_observation BETWEEN DATE_SUB(%s, INTERVAL 5 DAY) AND DATE_ADD(%s, INTERVAL 5 DAY)
                        ORDER BY dataset_id, dataseries_id, timestamp_observation""",
                    (t_str, t_str))
        _ingest_rows(cur.fetchall())

    conn.close()

    # ── 벤치마크별 다기간 수익률 계산 ──
    results = {}
    for name, cfg in BENCHMARK_MAP.items():
        blob_key = cfg.get('blob_key')
        key = (cfg['dataset_id'], cfg['ds_id'], blob_key)
        series = ts_data.get(key, [])
        if not series:
            key_fallback = (cfg['dataset_id'], cfg['ds_id'], None)
            series = ts_data.get(key_fallback, [])
        if not series:
            results[name] = {'ref_date': ref_dt_str}
            continue

        # 중복 제거 (같은 날짜 여러 쿼리에서 로드)
        seen = {}
        for dt_str, val in series:
            seen[dt_str] = val
        series_dedup = sorted(seen.items())

        ref_val = _closest_value(series_dedup, ref_dt_str)
        entry = {'ref_date': ref_dt_str, 'level': ref_val}

        for period, target_dt in period_targets.items():
            t_str = target_dt.strftime('%Y-%m-%d')
            start_val = _closest_value(series_dedup, t_str)
            if ref_val and start_val and start_val != 0:
                entry[period] = (ref_val / start_val - 1) * 100
            else:
                entry[period] = None

        results[name] = entry

    return results


def _closest_value(series, target_dt):
    """시계열에서 target_dt에 가장 가까운 값"""
    if not series:
        return None
    best = min(series, key=lambda x: abs((datetime.strptime(x[0], '%Y-%m-%d') - datetime.strptime(target_dt, '%Y-%m-%d')).days))
    return best[1]


def load_fund_return(fund_code, year, month):
    """펀드 월간 수익률"""
    bdays = load_business_days(year, month)
    conn = _get_conn('dt')
    cur = conn.cursor()

    # 당월 최신 가용일 조회 (cur_month_last에 데이터 없을 수 있음)
    cur.execute("""SELECT MAX(STD_DT) as max_dt FROM DWPM10510
                   WHERE FUND_CD=%s AND STD_DT BETWEEN %s AND %s""",
                (fund_code, f'{year}{month:02d}01', f'{year}{month:02d}31'))
    max_row = cur.fetchone()
    actual_last = max_row['max_dt'] if max_row and max_row['max_dt'] else bdays['cur_month_last']

    cur.execute("""SELECT STD_DT, MOD_STPR, NAST_AMT
                   FROM DWPM10510 WHERE FUND_CD=%s AND STD_DT IN (%s, %s)
                   ORDER BY STD_DT""",
                (fund_code, bdays['prev_month_last'], actual_last))
    rows = cur.fetchall()
    conn.close()

    if len(rows) == 2:
        prev_stpr = float(rows[0]['MOD_STPR'])
        cur_stpr = float(rows[1]['MOD_STPR'])
        ret = (cur_stpr / prev_stpr - 1) * 100
        result = {
            'return': ret,
            'prev_stpr': prev_stpr,
            'cur_stpr': cur_stpr,
            'aum': float(rows[1]['NAST_AMT']),
        }
        # 서브 포트폴리오 수익률 (07G04 등)
        cfg = FUND_CONFIGS.get(fund_code, {})
        if cfg.get('sub_portfolios'):
            conn2 = _get_conn('dt')
            cur2 = conn2.cursor()
            result['sub_returns'] = {}
            for label, sub_code in cfg['sub_portfolios'].items():
                cur2.execute("""SELECT MOD_STPR FROM DWPM10510
                               WHERE FUND_CD=%s AND STD_DT IN (%s, %s) ORDER BY STD_DT""",
                             (sub_code, bdays['prev_month_last'], bdays['cur_month_last']))
                sub_rows = cur2.fetchall()
                if len(sub_rows) == 2:
                    sub_ret = (float(sub_rows[1]['MOD_STPR']) / float(sub_rows[0]['MOD_STPR']) - 1) * 100
                    result['sub_returns'][label] = sub_ret
            conn2.close()
        return result
    return None


def load_all_pa_attributions(fund_codes, year, month):
    """복수 펀드 PA 일괄 로딩 (쿼리 최소화)"""
    bdays = load_business_days(year, month)
    start_dt = f'{year}{month:02d}01'
    end_dt = f'{year}{month:02d}31'

    conn = _get_conn('dt')
    cur = conn.cursor()

    # 기준가 일괄 조회
    fc_ph = ','.join(f"'{f}'" for f in fund_codes)
    cur.execute(f"""SELECT FUND_CD, MOD_STPR FROM DWPM10510
                    WHERE FUND_CD IN ({fc_ph}) AND STD_DT={bdays['prev_month_last']}""")
    stpr_map = {r['FUND_CD']: float(r['MOD_STPR']) for r in cur.fetchall()}

    # PA 일괄 조회 (전 펀드)
    cur.execute(f"""SELECT FUND_ID, ASSET_GB, OS_GB, SEC_ID, SUM(MODIFY_UNAV_CHG) as chg
                    FROM MA000410 WHERE FUND_ID IN ({fc_ph})
                    AND PR_DATE BETWEEN '{start_dt}' AND '{end_dt}'
                    GROUP BY FUND_ID, ASSET_GB, OS_GB, SEC_ID""")
    pa_rows = cur.fetchall()

    # SEC_ID → ITEM_NM 일괄 조회 (최신 가용일 fallback)
    sec_ids = list(set(r['SEC_ID'] for r in pa_rows))
    item_names = {}
    if sec_ids:
        for i in range(0, len(sec_ids), 50):
            batch = sec_ids[i:i+50]
            sec_ph = ','.join(f"'{s}'" for s in batch)
            cur.execute(f"""SELECT ITEM_CD, ITEM_NM FROM DWPM10530
                           WHERE ITEM_CD IN ({sec_ph})
                           AND STD_DT BETWEEN {start_dt} AND {end_dt}
                           ORDER BY STD_DT DESC""")
            for r in cur.fetchall():
                if r['ITEM_CD'] not in item_names:
                    item_names[r['ITEM_CD']] = r['ITEM_NM']

    # solution.universe_non_derivative에서 자산군 매핑 (R 동일)
    universe_map = {}  # ISIN → 자산군
    try:
        conn_sol = _get_conn('solution')
        cur_sol = conn_sol.cursor()
        if sec_ids:
            for i in range(0, len(sec_ids), 50):
                batch = sec_ids[i:i+50]
                sec_ph = ','.join(f"'{s}'" for s in batch)
                cur_sol.execute(f"""SELECT ISIN, classification FROM universe_non_derivative
                                   WHERE classification_method='방법3'
                                   AND ISIN IN ({sec_ph})
                                   AND classification IS NOT NULL""")
                for r in cur_sol.fetchall():
                    universe_map[r['ISIN']] = r['classification']
        conn_sol.close()
    except Exception:
        pass  # universe 조회 실패 시 키워드 fallback

    conn.close()

    # 펀드별 분류 및 집계
    results = {}
    for fund_code in fund_codes:
        base_stpr = stpr_map.get(fund_code, 1000)
        fund_rows = [r for r in pa_rows if r['FUND_ID'] == fund_code]

        asset_contrib = {}
        for r in fund_rows:
            nm = item_names.get(r['SEC_ID'], '')
            # universe DB 우선 → 키워드 fallback
            cls = universe_map.get(r['SEC_ID'])
            if not cls:
                cls = _classify_pa_item(r['ASSET_GB'], r['OS_GB'], nm)
            asset_contrib[cls] = asset_contrib.get(cls, 0) + float(r['chg'])

        results[fund_code] = {cls: round(chg / base_stpr * 100, 2)
                              for cls, chg in asset_contrib.items()}

    return results


def load_pa_attribution(fund_code, year, month):
    """단일 펀드 PA — load_all_pa_attributions 래퍼"""
    return load_all_pa_attributions([fund_code], year, month).get(fund_code, {})


def _prev_business_day(dt_int):
    """dt_int(YYYYMMDD) 직전 영업일 조회"""
    conn = _get_conn('dt')
    cur = conn.cursor()
    cur.execute("""SELECT MAX(CAST(std_dt AS UNSIGNED)) as d FROM DWCI10220
                   WHERE hldy_yn='N' AND day_ds_cd IN (2,3,4,5,6)
                   AND std_dt < %s""", (dt_int,))
    row = cur.fetchone()
    conn.close()
    return row['d'] if row and row['d'] else dt_int


def load_pa_by_daterange(fund_code, start_date, end_date):
    """날짜 범위 기반 PA 자산군 합산.

    Parameters
    ----------
    fund_code : str
    start_date : date or str  (YYYY-MM-DD or YYYYMMDD)
    end_date : date or str

    Returns
    -------
    dict : {자산군: 기여수익률(%)} + {'_fund_ret': 펀드수익률, '_holdings': 보유비중}
    """
    if hasattr(start_date, 'strftime'):
        start_int = int(start_date.strftime('%Y%m%d'))
        end_int = int(end_date.strftime('%Y%m%d'))
    else:
        start_int = int(str(start_date).replace('-', ''))
        end_int = int(str(end_date).replace('-', ''))

    # 시작일 직전 영업일 = 기준가 분모
    base_dt = _prev_business_day(start_int)

    conn = _get_conn('dt')
    cur = conn.cursor()

    # 기준가 (분모)
    cur.execute("SELECT MOD_STPR FROM DWPM10510 WHERE FUND_CD=%s AND STD_DT=%s",
                (fund_code, base_dt))
    row = cur.fetchone()
    base_stpr = float(row['MOD_STPR']) if row else 1000

    # 종료일 기준가 (펀드 수익률용) — 최신 가용일 fallback
    cur.execute("""SELECT MOD_STPR, NAST_AMT FROM DWPM10510
                   WHERE FUND_CD=%s AND STD_DT BETWEEN %s AND %s
                   ORDER BY STD_DT DESC LIMIT 1""",
                (fund_code, start_int, end_int))
    end_row = cur.fetchone()
    end_stpr = float(end_row['MOD_STPR']) if end_row else None
    aum = float(end_row['NAST_AMT']) if end_row and end_row['NAST_AMT'] else None
    fund_ret = ((end_stpr / base_stpr - 1) * 100) if end_stpr else None

    # PA 집계
    cur.execute("""SELECT ASSET_GB, OS_GB, SEC_ID, SUM(MODIFY_UNAV_CHG) as chg
                   FROM MA000410 WHERE FUND_ID=%s
                   AND PR_DATE BETWEEN %s AND %s
                   GROUP BY ASSET_GB, OS_GB, SEC_ID""",
                (fund_code, start_int, end_int))
    pa_rows = cur.fetchall()

    # 종목명 조회
    sec_ids = list(set(r['SEC_ID'] for r in pa_rows))
    item_names = {}
    if sec_ids:
        for i in range(0, len(sec_ids), 50):
            batch = sec_ids[i:i+50]
            sec_ph = ','.join(f"'{s}'" for s in batch)
            cur.execute(f"""SELECT ITEM_CD, ITEM_NM FROM DWPM10530
                           WHERE ITEM_CD IN ({sec_ph})
                           AND STD_DT BETWEEN {start_int} AND {end_int}
                           ORDER BY STD_DT DESC""")
            for r in cur.fetchall():
                if r['ITEM_CD'] not in item_names:
                    item_names[r['ITEM_CD']] = r['ITEM_NM']

    # universe 조회
    universe_map = {}
    try:
        conn_sol = _get_conn('solution')
        cur_sol = conn_sol.cursor()
        for i in range(0, len(sec_ids), 50):
            batch = sec_ids[i:i+50]
            sec_ph = ','.join(f"'{s}'" for s in batch)
            cur_sol.execute(f"""SELECT ISIN, classification FROM universe_non_derivative
                               WHERE classification_method='방법3'
                               AND ISIN IN ({sec_ph}) AND classification IS NOT NULL""")
            for r in cur_sol.fetchall():
                universe_map[r['ISIN']] = r['classification']
        conn_sol.close()
    except Exception:
        pass

    # holdings (종료일 기준)
    cur.execute("""SELECT MAX(STD_DT) as max_dt FROM DWPM10530
                   WHERE FUND_CD=%s AND STD_DT BETWEEN %s AND %s""",
                (fund_code, start_int, end_int))
    max_row = cur.fetchone()
    hold_dt = max_row['max_dt'] if max_row and max_row['max_dt'] else end_int

    cur.execute("""SELECT ITEM_CD, ITEM_NM, AST_CLSF_CD_NM, NAST_TAMT_AGNST_WGH
                   FROM DWPM10530 WHERE FUND_CD=%s AND STD_DT=%s AND EVL_AMT > 0""",
                (fund_code, hold_dt))
    hold_rows = cur.fetchall()

    conn.close()

    # PA 분류 + 집계
    asset_contrib = {}
    for r in pa_rows:
        nm = item_names.get(r['SEC_ID'], '')
        cls = universe_map.get(r['SEC_ID'])
        if not cls:
            cls = _classify_pa_item(r['ASSET_GB'], r['OS_GB'], nm)
        asset_contrib[cls] = asset_contrib.get(cls, 0) + float(r['chg'])

    pa = {cls: round(chg / base_stpr * 100, 2) for cls, chg in asset_contrib.items()}

    # holdings 분류 — 모펀드 구조면 sub_portfolios look-through
    cfg = FUND_CONFIGS.get(fund_code, {})
    if cfg.get('sub_portfolios'):
        holdings = _holdings_lookthrough(cfg['sub_portfolios'], start_int, end_int)
    else:
        holdings = _classify_holdings(hold_rows)

    # 비중 변화 (전월말 vs 당월말)
    if cfg.get('sub_portfolios'):
        # 모펀드는 서브 합산이라 diff 계산이 복잡 — 서브별로 합산
        holdings_diff = {}
        for label, sub_code in cfg['sub_portfolios'].items():
            sub_diff = _load_holdings_diff(sub_code, start_int, end_int)
            for cls, info in sub_diff.items():
                if cls not in holdings_diff:
                    holdings_diff[cls] = {'prev': 0, 'cur': 0, 'change': 0}
                n = len(cfg['sub_portfolios'])
                holdings_diff[cls]['prev'] += info['prev'] / n
                holdings_diff[cls]['cur'] += info['cur'] / n
                holdings_diff[cls]['change'] += info['change'] / n
        holdings_diff = {k: {kk: round(vv, 1) for kk, vv in v.items()}
                         for k, v in holdings_diff.items() if abs(v['change']) > 0.3}
    else:
        holdings_diff = _load_holdings_diff(fund_code, start_int, end_int)

    return {
        'pa': pa,
        'fund_ret': fund_ret,
        'aum': aum,
        'base_dt': base_dt,
        'holdings': holdings,
        'holdings_diff': holdings_diff,
    }


def load_pa_items_by_daterange(fund_code, start_date, end_date):
    """날짜 범위 기반 종목별 PA 기여도."""
    if hasattr(start_date, 'strftime'):
        start_int = int(start_date.strftime('%Y%m%d'))
        end_int = int(end_date.strftime('%Y%m%d'))
    else:
        start_int = int(str(start_date).replace('-', ''))
        end_int = int(str(end_date).replace('-', ''))

    base_dt = _prev_business_day(start_int)

    conn = _get_conn('dt')
    cur = conn.cursor()

    cur.execute("SELECT MOD_STPR FROM DWPM10510 WHERE FUND_CD=%s AND STD_DT=%s",
                (fund_code, base_dt))
    row = cur.fetchone()
    base_stpr = float(row['MOD_STPR']) if row else 1000

    # 영업일수 (비중 계산용)
    cur.execute("""SELECT COUNT(*) as cnt FROM DWCI10220
                   WHERE hldy_yn='N' AND day_ds_cd IN (2,3,4,5,6)
                   AND std_dt BETWEEN %s AND %s""", (start_int, end_int))
    bday_count = cur.fetchone()['cnt'] or 1

    # NAST_AMT (비중 분모)
    cur.execute("""SELECT NAST_AMT FROM DWPM10510 WHERE FUND_CD=%s
                   AND STD_DT BETWEEN %s AND %s ORDER BY STD_DT DESC LIMIT 1""",
                (fund_code, start_int, end_int))
    nast_row = cur.fetchone()
    nast_amt = float(nast_row['NAST_AMT']) if nast_row and nast_row['NAST_AMT'] else 0

    cur.execute("""SELECT ASSET_GB, OS_GB, SEC_ID,
                          SUM(MODIFY_UNAV_CHG) as chg,
                          SUM(VAL) as total_val,
                          SUM(AMT) as total_amt
                   FROM MA000410 WHERE FUND_ID=%s
                   AND PR_DATE BETWEEN %s AND %s
                   GROUP BY ASSET_GB, OS_GB, SEC_ID
                   ORDER BY ABS(SUM(MODIFY_UNAV_CHG)) DESC""",
                (fund_code, start_int, end_int))
    rows = cur.fetchall()

    sec_ids = list(set(r['SEC_ID'] for r in rows))
    item_names = {}
    for i in range(0, len(sec_ids), 50):
        batch = sec_ids[i:i+50]
        sec_ph = ','.join(f"'{s}'" for s in batch)
        cur.execute(f"""SELECT ITEM_CD, ITEM_NM FROM DWPM10530
                       WHERE ITEM_CD IN ({sec_ph})
                       AND STD_DT BETWEEN {start_int} AND {end_int}
                       ORDER BY STD_DT DESC""")
        for r in cur.fetchall():
            if r['ITEM_CD'] not in item_names:
                item_names[r['ITEM_CD']] = r['ITEM_NM']

    # fallback: DWPI10021
    missing = [s for s in sec_ids if s not in item_names]
    for i in range(0, len(missing), 50):
        batch = missing[i:i+50]
        if not batch:
            continue
        sec_ph = ','.join(f"'{s}'" for s in batch)
        cur.execute(f"""SELECT DISTINCT ITEM_CD, ITEM_NM FROM DWPI10021
                       WHERE ITEM_CD IN ({sec_ph}) AND IMC_CD='003228'""")
        for r in cur.fetchall():
            item_names[r['ITEM_CD']] = r['ITEM_NM']

    universe_map = {}
    try:
        conn_sol = _get_conn('solution')
        cur_sol = conn_sol.cursor()
        for i in range(0, len(sec_ids), 50):
            batch = sec_ids[i:i+50]
            sec_ph = ','.join(f"'{s}'" for s in batch)
            cur_sol.execute(f"""SELECT ISIN, classification FROM universe_non_derivative
                               WHERE classification_method='방법3'
                               AND ISIN IN ({sec_ph}) AND classification IS NOT NULL""")
            for r in cur_sol.fetchall():
                universe_map[r['ISIN']] = r['classification']
        conn_sol.close()
    except Exception:
        pass

    conn.close()

    items = []
    for r in rows:
        chg = float(r['chg'])
        pct = round(chg / base_stpr * 100, 4)
        nm = item_names.get(r['SEC_ID'], r['SEC_ID'])
        cls = universe_map.get(r['SEC_ID'])
        if not cls:
            cls = _classify_pa_item_v2(r['ASSET_GB'], r['OS_GB'], nm)
        if cls in ('보수비용', '유동성') and abs(pct) < 0.01:
            continue

        total_val = float(r['total_val']) if r['total_val'] else 0
        total_amt = float(r['total_amt']) if r['total_amt'] else 0
        avg_val = total_val / bday_count
        weight_pct = round(avg_val / nast_amt * 100, 2) if nast_amt > 0 else 0.0
        item_return = round(total_amt / avg_val * 100, 2) if avg_val != 0 else 0.0

        items.append({
            'asset_class': cls,
            'item_name': nm,
            'item_cd': r['SEC_ID'],
            'contrib_pct': pct,
            'weight_pct': weight_pct,
            'item_return_pct': item_return,
        })

    return items


def _classify_holdings(hold_rows):
    """DWPM10530 행 → 자산군별 비중 합산"""
    holdings = {}
    for r in hold_rows:
        nm = r['ITEM_NM'].upper() if r['ITEM_NM'] else ''
        wt = float(r['NAST_TAMT_AGNST_WGH']) if r['NAST_TAMT_AGNST_WGH'] else 0

        if any(k in nm for k in ['미국', '나스닥', 'NASDAQ', 'S&P', 'GROWTH', 'VALUE', 'SPDR', 'VANGUARD']):
            if any(k in nm for k in ['BOND', 'HIGH Y', 'TREASURY', 'EMERG']):
                cls = '해외채권' if ('GOV' in nm or 'BOND' in nm) else '해외주식'
            else:
                cls = '해외주식'
        elif any(k in nm for k in ['GOLD', 'KRX금', '금현물', '금선물', '골드']):
            cls = '원자재'
        elif any(k in nm for k in ['채권', '국고채', 'TMF', '만기', '은행채', '사모투자신탁']) or ('채권' in str(r.get('AST_CLSF_CD_NM', ''))):
            cls = '국내채권'
        elif any(k in nm for k in ['200', 'KOSPI', '코스피', '주식']) or ('주식' in str(r.get('AST_CLSF_CD_NM', ''))):
            cls = '국내주식'
        elif any(k in nm for k in ['콜론', '예금', 'DEPOSIT', 'MMF', '미지급', '미수금', '증권금융']):
            cls = '유동성'
        else:
            cls = '기타'

        holdings[cls] = holdings.get(cls, 0) + wt
    return holdings


def _load_holdings_diff(fund_code, start_int, end_int):
    """전월말 vs 당월말 보유비중 변화 계산."""
    conn = _get_conn('dt')
    cur = conn.cursor()

    # 시작일 직전 보유비중
    prev_dt = _prev_business_day(start_int)
    cur.execute("""SELECT ITEM_CD, ITEM_NM, AST_CLSF_CD_NM, NAST_TAMT_AGNST_WGH
                   FROM DWPM10530 WHERE FUND_CD=%s AND STD_DT=%s AND EVL_AMT > 0""",
                (fund_code, prev_dt))
    prev_holdings = _classify_holdings(cur.fetchall())

    # 종료일 보유비중
    cur.execute("""SELECT MAX(STD_DT) as max_dt FROM DWPM10530
                   WHERE FUND_CD=%s AND STD_DT BETWEEN %s AND %s""",
                (fund_code, start_int, end_int))
    max_row = cur.fetchone()
    hold_dt = max_row['max_dt'] if max_row and max_row['max_dt'] else end_int
    cur.execute("""SELECT ITEM_CD, ITEM_NM, AST_CLSF_CD_NM, NAST_TAMT_AGNST_WGH
                   FROM DWPM10530 WHERE FUND_CD=%s AND STD_DT=%s AND EVL_AMT > 0""",
                (fund_code, hold_dt))
    cur_holdings = _classify_holdings(cur.fetchall())

    conn.close()

    # 차이 계산
    all_classes = set(list(prev_holdings.keys()) + list(cur_holdings.keys()))
    diff = {}
    for cls in all_classes:
        prev_wt = prev_holdings.get(cls, 0)
        cur_wt = cur_holdings.get(cls, 0)
        change = cur_wt - prev_wt
        if abs(change) > 0.3:  # 0.3%p 이상 변화만
            diff[cls] = {'prev': round(prev_wt, 1), 'cur': round(cur_wt, 1), 'change': round(change, 1)}
    return diff


def _holdings_lookthrough(sub_portfolios, start_int, end_int):
    """모펀드 구조 → sub_portfolios의 holdings 합산 (equal weight 가정)."""
    conn = _get_conn('dt')
    cur = conn.cursor()
    combined = {}
    n_subs = len(sub_portfolios)

    for label, sub_code in sub_portfolios.items():
        cur.execute("""SELECT MAX(STD_DT) as max_dt FROM DWPM10530
                       WHERE FUND_CD=%s AND STD_DT BETWEEN %s AND %s""",
                    (sub_code, start_int, end_int))
        max_row = cur.fetchone()
        hold_dt = max_row['max_dt'] if max_row and max_row['max_dt'] else end_int

        cur.execute("""SELECT ITEM_CD, ITEM_NM, AST_CLSF_CD_NM, NAST_TAMT_AGNST_WGH
                       FROM DWPM10530 WHERE FUND_CD=%s AND STD_DT=%s AND EVL_AMT > 0""",
                    (sub_code, hold_dt))
        sub_holdings = _classify_holdings(cur.fetchall())

        for cls, wt in sub_holdings.items():
            combined[cls] = combined.get(cls, 0) + wt / n_subs

    conn.close()
    return combined


def load_pa_by_item(fund_code, year, month):
    """종목별 PA 기여도 — 자산군 분류 포함"""
    bdays = load_business_days(year, month)
    start_dt = f'{year}{month:02d}01'
    end_dt = f'{year}{month:02d}31'

    conn = _get_conn('dt')
    cur = conn.cursor()

    cur.execute("SELECT MOD_STPR FROM DWPM10510 WHERE FUND_CD=%s AND STD_DT=%s",
                (fund_code, bdays['prev_month_last']))
    stpr_row = cur.fetchone()
    base_stpr = float(stpr_row['MOD_STPR']) if stpr_row else 1000

    cur.execute(f"""SELECT ASSET_GB, OS_GB, SEC_ID,
                           SUM(MODIFY_UNAV_CHG) as chg,
                           SUM(VAL) as total_val,
                           SUM(AMT) as total_amt
                    FROM MA000410 WHERE FUND_ID='{fund_code}'
                    AND PR_DATE BETWEEN '{start_dt}' AND '{end_dt}'
                    GROUP BY ASSET_GB, OS_GB, SEC_ID
                    ORDER BY ABS(SUM(MODIFY_UNAV_CHG)) DESC""")
    rows = cur.fetchall()

    sec_ids = list(set(r['SEC_ID'] for r in rows))
    item_names = {}
    for i in range(0, len(sec_ids), 50):
        batch = sec_ids[i:i+50]
        sec_ph = ','.join(f"'{s}'" for s in batch)
        cur.execute(f"""SELECT DISTINCT ITEM_CD, ITEM_NM FROM DWPM10530
                       WHERE ITEM_CD IN ({sec_ph}) AND STD_DT BETWEEN {start_dt} AND {end_dt}""")
        for r in cur.fetchall():
            item_names[r['ITEM_CD']] = r['ITEM_NM']

    missing_ids = [sec_id for sec_id in sec_ids if sec_id not in item_names]
    for i in range(0, len(missing_ids), 50):
        batch = missing_ids[i:i+50]
        if not batch:
            continue
        sec_ph = ','.join(f"'{s}'" for s in batch)
        cur.execute(f"""SELECT DISTINCT ITEM_CD, ITEM_NM FROM DWPI10021
                       WHERE ITEM_CD IN ({sec_ph}) AND IMC_CD='003228'""")
        for r in cur.fetchall():
            item_names[r['ITEM_CD']] = r['ITEM_NM']

    # solution.universe_non_derivative 조회 (R 동일)
    universe_map = {}
    try:
        conn_sol = _get_conn('solution')
        cur_sol = conn_sol.cursor()
        for i in range(0, len(sec_ids), 50):
            batch = sec_ids[i:i+50]
            sec_ph = ','.join(f"'{s}'" for s in batch)
            cur_sol.execute(f"""SELECT ISIN, classification FROM universe_non_derivative
                               WHERE classification_method='방법3'
                               AND ISIN IN ({sec_ph})
                               AND classification IS NOT NULL""")
            for r in cur_sol.fetchall():
                universe_map[r['ISIN']] = r['classification']
        conn_sol.close()
    except Exception:
        pass

    conn.close()

    # NAST_AMT 조회 (비중 계산용)
    cur2 = _get_conn('dt').cursor()
    cur2.execute("""SELECT NAST_AMT FROM DWPM10510 WHERE FUND_CD=%s
                    AND STD_DT BETWEEN %s AND %s ORDER BY STD_DT DESC LIMIT 1""",
                 (fund_code, start_dt, end_dt))
    nast_row = cur2.fetchone()
    nast_amt = float(nast_row['NAST_AMT']) if nast_row and nast_row['NAST_AMT'] else 0
    cur2.connection.close()

    items = []
    for r in rows:
        chg = float(r['chg'])
        pct = round(chg / base_stpr * 100, 4)
        nm = item_names.get(r['SEC_ID'], r['SEC_ID'])
        # universe DB 우선 → 키워드 fallback
        cls = universe_map.get(r['SEC_ID'])
        if not cls:
            cls = _classify_pa_item_v2(r['ASSET_GB'], r['OS_GB'], nm)
        if cls in ('보수비용', '유동성') and abs(pct) < 0.01:
            continue

        # 비중: 기간 평균 평가액 / 순자산
        total_val = float(r['total_val']) if r['total_val'] else 0
        total_amt = float(r['total_amt']) if r['total_amt'] else 0
        # total_val은 일별 합산이므로 영업일수로 나눠 평균
        bday_count = bdays['business_days'] or 1
        avg_val = total_val / bday_count
        weight_pct = round(avg_val / nast_amt * 100, 2) if nast_amt > 0 else 0.0
        # normalized 수익률 (비중 미반영): chg / avg_val
        item_return = round(total_amt / avg_val * 100, 2) if avg_val != 0 else 0.0

        items.append({
            'asset_class': cls,
            'item_name': nm,
            'item_cd': r['SEC_ID'],
            'contrib_pct': pct,
            'weight_pct': weight_pct,
            'item_return_pct': item_return,
        })

    return items


def _classify_pa_item(asset_gb, os_gb, item_nm):
    """PA 종목 → 코멘트 자산군 분류"""
    nm = (item_nm or '').upper()

    # 보수/비용
    if '보수' in asset_gb or '비용' in asset_gb:
        return '보수비용'

    # 유동성
    if asset_gb == '유동':
        return '유동성'

    # 기타자산부채
    if '기타자산' in asset_gb:
        return '유동성'

    # 주식ETF
    if asset_gb == '주식ETF':
        if any(k in nm for k in ['미국', '나스닥', 'NASDAQ', 'S&P', 'GROWTH', 'VALUE']):
            return '해외주식'
        return '국내주식'

    # 채권ETF
    if asset_gb == '채권ETF':
        if any(k in nm for k in ['미국', 'US ', 'TREASURY', 'BARCLAYS']):
            return '해외채권'
        return '국내채권'

    # 기타ETF (금, 해외주식 등)
    if asset_gb == '기타ETF':
        if any(k in nm for k in ['금', 'GOLD', 'KRX금']):
            return '원자재'
        if any(k in nm for k in ['미국', '성장', 'GROWTH', '나스닥', 'NASDAQ']):
            return '해외주식'
        return '기타'

    # 수익증권 (해외)
    if asset_gb == '수익증권' and os_gb == '해외':
        if any(k in nm for k in ['GOLD', '금']):
            return '원자재'
        if any(k in nm for k in ['BOND', 'HIGH Y', 'TREASURY', 'VANGUARD EMERG']):
            return '해외채권'
        return '해외주식'

    # 수익증권 (국내)
    if asset_gb == '수익증권' and os_gb == '국내':
        if any(k in nm for k in ['채권', '은행채', 'TMF', '만기형', '사모투자신탁']):
            return '국내채권'
        if any(k in nm for k in ['주식', '성장', '배당']):
            return '국내주식'
        return '기타'

    return '기타'


def _classify_pa_item_v2(asset_gb, os_gb, item_nm):
    """PA 종목별 코멘트용 자산군 분류 v2."""
    asset_gb = asset_gb or ''
    os_gb = os_gb or ''
    nm = (item_nm or '').upper()

    if '보수' in asset_gb or '비용' in asset_gb:
        return '보수비용'

    if asset_gb == '유동' or '기타자산' in asset_gb:
        return '유동성'

    if asset_gb == '주식ETF':
        if any(k in nm for k in ['미국', 'NASDAQ', 'S&P', 'GROWTH', 'VALUE']):
            return '해외주식'
        return '국내주식'

    if asset_gb == '채권ETF':
        if any(k in nm for k in ['미국', 'US ', 'TREASURY', 'BARCLAYS']):
            return '해외채권'
        return '국내채권'

    if asset_gb == '기타ETF':
        if any(k in nm for k in ['금', 'GOLD', 'KRX금']):
            return '대체투자'
        if any(k in nm for k in ['미국', '성장', 'GROWTH', 'NASDAQ']):
            return '해외주식'
        return '기타'

    if '주식' in asset_gb and 'ETF' not in asset_gb:
        return '해외주식' if os_gb == '해외' else '국내주식'

    if '채권' in asset_gb and 'ETF' not in asset_gb:
        return '해외채권' if os_gb == '해외' else '국내채권'

    if any(k in asset_gb for k in ['파생', '선물', '통화', 'FX']):
        return 'FX/파생'

    if asset_gb == '수익증권' and os_gb == '해외':
        if any(k in nm for k in ['GOLD', '금']):
            return '대체투자'
        if any(k in nm for k in ['BOND', 'HIGH Y', 'TREASURY', 'VANGUARD EMERG']):
            return '해외채권'
        return '해외주식'

    if asset_gb == '수익증권' and os_gb == '국내':
        if any(k in nm for k in ['채권', '국고채', 'TMF', '만기', '은행채', '사모투자신탁']):
            return '국내채권'
        if any(k in nm for k in ['주식', 'STOCK', 'EQUITY', 'KOSPI', 'MSCI', '200']):
            return '국내주식'
        return '기타'

    return '기타'


def load_fund_holdings_summary(fund_code, year, month):
    """펀드 보유종목 자산군 비중 요약 — universe DB 우선, _classify_pa_item_v2 fallback."""
    bdays = load_business_days(year, month)
    conn = _get_conn('dt')
    cur = conn.cursor()

    # 최신 가용일 fallback (cur_month_last에 데이터 없으면 직전 영업일)
    cur.execute("""SELECT MAX(STD_DT) as max_dt FROM DWPM10530
                   WHERE FUND_CD=%s AND STD_DT BETWEEN %s AND %s""",
                (fund_code, f'{year}{month:02d}01', f'{year}{month:02d}31'))
    max_row = cur.fetchone()
    hold_dt = max_row['max_dt'] if max_row and max_row['max_dt'] else bdays['cur_month_last']

    cur.execute("""SELECT ITEM_CD, ITEM_NM, AST_CLSF_CD_NM, CURR_DS_CD,
                          EVL_AMT, NAST_TAMT_AGNST_WGH
                   FROM DWPM10530 WHERE FUND_CD=%s AND STD_DT=%s AND EVL_AMT > 0
                   ORDER BY EVL_AMT DESC""",
                (fund_code, hold_dt))
    rows = cur.fetchall()
    conn.close()

    # universe DB에서 ISIN → classification 매핑 로드
    isin_map = {}
    try:
        conn_sol = _get_conn('solution')
        cur_sol = conn_sol.cursor()
        cur_sol.execute("""SELECT ISIN, classification FROM universe_non_derivative
                          WHERE classification_method = '방법3'""")
        for row in cur_sol.fetchall():
            if row['ISIN']:
                isin_map[row['ISIN']] = row['classification']
        conn_sol.close()
    except Exception:
        pass

    # 분류값 → 코멘트 자산군 매핑 (universe DB 값 + _classify_pa_item_v2 값 모두 커버)
    _CLASS_MAP = {
        '국내주식': '국내주식', '해외주식': '해외주식',
        '국내채권': '국내채권', '해외채권': '해외채권',
        '대체': '대체투자', '대체투자': '대체투자',
        'FX': 'FX', 'FX/파생': 'FX',
        '유동성': '유동성', '유동성및기타': '유동성', '보수비용': '유동성',
        '모펀드': '기타', '기타': '기타',
    }

    holdings = {}
    for r in rows:
        item_cd = r['ITEM_CD'] or ''
        nm = r['ITEM_NM'] or ''
        ast = r['AST_CLSF_CD_NM'] or ''
        wt = float(r['NAST_TAMT_AGNST_WGH']) if r['NAST_TAMT_AGNST_WGH'] else 0

        # 1순위: universe DB (ISIN 매칭)
        cls = isin_map.get(item_cd)
        if cls:
            cls = _CLASS_MAP.get(cls, cls)
        else:
            # 2순위: _classify_pa_item_v2 로직 (asset_gb=AST_CLSF_CD_NM, os_gb 추론)
            is_kr = item_cd.startswith('KR') or (len(item_cd) == 6 and item_cd.isdigit())
            os_gb = '국내' if is_kr else '해외'
            raw_cls = _classify_pa_item_v2(ast, os_gb, nm)
            cls = _CLASS_MAP.get(raw_cls, raw_cls)

        holdings[cls] = holdings.get(cls, 0) + wt

    return holdings


# ═══════════════════════════════════════════════════════
# 3. 코멘트 생성
# ═══════════════════════════════════════════════════════

# ── Digest 로딩 및 활용 ──

# 주제 → 코멘트 자산 섹션 매핑
# V2 Taxonomy (14개) 기준
_TOPIC_TO_SECTION = {
    '통화정책':         'equity_context',
    '금리_채권':        'bond',
    '물가_인플레이션':   'macro_bg',
    '경기_소비':        'macro_bg',
    '유동성_크레딧':     'bond',
    '환율_FX':          'fx',
    '달러_글로벌유동성': 'macro_bg',
    '에너지_원자재':     'commodity',
    '귀금속_금':        'commodity',
    '지정학':           'equity_context',
    '부동산':           'alternative',
    '관세_무역':        'equity_context',
    '크립토':           None,
    '테크_AI_반도체':   'equity_detail',
}


def load_digest(year, month):
    """월별 블로그 digest 로딩"""
    path = DIGEST_DIR / f'{year}-{month:02d}.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return None


def _pick_short_claims(claims, max_len=100, max_count=2):
    """짧고 핵심적인 claims만 선별"""
    result = []
    for c in claims:
        # 날짜만 있는 것, 너무 긴 것, 이모지 과다한 것 제거
        if len(c) < 15 or len(c) > max_len:
            continue
        if c.count('🚨') > 0 or c.count('🔴') > 0:
            continue
        # 숫자/퍼센트 포함된 것 우선
        has_data = any(ch in c for ch in ['%', '포인트', '달러', '원', 'bp'])
        if has_data:
            result.insert(0, c)
        else:
            result.append(c)
        if len(result) >= max_count * 2:
            break
    return result[:max_count]


def _pick_short_events(events, max_len=100, max_count=2):
    """핵심 이벤트 선별 — 날짜+행위 포함된 짧은 문장"""
    result = []
    for ev in events:
        if len(ev) < 15 or len(ev) > max_len:
            continue
        # 날짜 패턴이나 행위 동사 포함
        if any(k in ev for k in ['판결', '공습', '인상', '인하', '발표', '지명',
                                   '봉쇄', '돌파', '급등', '급락', '위헌', '선거']):
            result.append(ev)
        if len(result) >= max_count:
            break
    return result


def _build_context_from_digest(digest, section_filter=None):
    """digest에서 특정 섹션의 배경 문맥 추출"""
    if not digest:
        return ''
    pieces = []
    for topic, info in digest.get('topics', {}).items():
        section = _TOPIC_TO_SECTION.get(topic)
        if section_filter and section != section_filter:
            continue
        events = _pick_short_events(info.get('key_events', []))
        claims = _pick_short_claims(info.get('key_claims', []))
        for ev in events:
            pieces.append(ev)
        for cl in claims:
            pieces.append(cl)
    return pieces


def _build_outlook_from_digest(next_digest, holdings):
    """익월 digest에서 전망 문맥 추출 (편입 자산 기반 필터)"""
    if not next_digest:
        return []

    has_kr_equity = holdings.get('국내주식', 0) > 1
    has_overseas_equity = holdings.get('해외주식', 0) > 1
    has_bond = holdings.get('국내채권', 0) > 1 or holdings.get('해외채권', 0) > 1
    has_commodity = holdings.get('원자재', 0) > 1

    relevant_topics = []
    if has_kr_equity:
        relevant_topics.extend(['환율_FX', '테크_AI_반도체'])
    if has_overseas_equity:
        relevant_topics.extend(['환율_FX', '관세_무역', '테크_AI_반도체', '통화정책'])
    if has_bond:
        relevant_topics.extend(['금리_채권', '통화정책'])
    if has_commodity:
        relevant_topics.extend(['에너지_원자재', '귀금속_금'])
    # 항상 포함
    relevant_topics.extend(['물가_인플레이션', '경기_소비'])
    relevant_topics = list(set(relevant_topics))

    pieces = []
    for topic in relevant_topics:
        info = next_digest.get('topics', {}).get(topic, {})
        if not info:
            continue
        claims = _pick_short_claims(info.get('key_claims', []), max_len=120, max_count=1)
        events = _pick_short_events(info.get('key_events', []), max_count=1)
        for ev in events:
            pieces.append(ev)
        for cl in claims:
            pieces.append(cl)

    # cross_themes
    themes = next_digest.get('cross_themes', [])
    if themes:
        relevant_themes = [t for t in themes if t not in ['디플레이션', '엔 캐리']]  # 너무 일반적인 것 제외
        if relevant_themes:
            pieces.append(f'시장의 주요 테마로 {", ".join(relevant_themes[:3])}이(가) 부각되고 있습니다.')

    return pieces


def _dir_text(ret, threshold=0.5):
    """수익률 → 방향 텍스트"""
    if ret is None:
        return ''
    if ret > threshold:
        return '(+)수익률을 기록'
    elif ret < -threshold:
        return '(-)수익률을 기록'
    else:
        return '소폭 (+)수익률을 기록' if ret >= 0 else '소폭 (-)수익률을 기록'


def _sign_text(ret):
    """수익률 → 부호 포함 문자열"""
    if ret is None:
        return 'N/A'
    return f'{ret:+.2f}%'


def _asset_direction(ret, asset_name):
    """자산군 수익률 → 문장"""
    if ret is None:
        return ''
    if ret > 1:
        return f'{asset_name}은 양호한 성과를 기록하였습니다'
    elif ret > 0:
        return f'{asset_name}은 소폭 상승하였습니다'
    elif ret > -1:
        return f'{asset_name}은 소폭 하락하였습니다'
    else:
        return f'{asset_name}은 부진한 성과를 기록하였습니다'


def generate_common_market(bm_returns, year, month, digest=None):
    """공통 시장환경 코멘트 생성 (digest 정성 분석 포함)"""
    m = month

    # 주요 수익률
    eq_global = bm_returns.get('글로벌주식', {}).get('return')
    fi_global = bm_returns.get('글로벌채권UH', {}).get('return')
    kospi = bm_returns.get('KOSPI', {}).get('return')
    kospi_level = bm_returns.get('KOSPI', {}).get('level')
    sp500 = bm_returns.get('S&P500', {}).get('return')
    growth = bm_returns.get('미국성장주', {}).get('return')
    value = bm_returns.get('미국가치주', {}).get('return')
    dm_exus = bm_returns.get('미국외선진국', {}).get('return')
    em = bm_returns.get('신흥국주식', {}).get('return')

    fi_kr_3y = bm_returns.get('매경채권국채3년', {}).get('return')
    fi_kr_10y = bm_returns.get('KRX10년채권', {}).get('return')
    fi_us = bm_returns.get('미국종합채권', {}).get('return')

    gold = bm_returns.get('Gold', {}).get('return')
    wti = bm_returns.get('WTI', {}).get('return')
    dxy = bm_returns.get('DXY', {}).get('return')
    usdkrw = bm_returns.get('USDKRW', {}).get('return')

    # ── 시장 개황 ──
    lines = []

    # 1문단: 글로벌 주식/채권/원자재 종합
    eq_dir = '(+)수익률을 기록' if eq_global and eq_global > 0 else '(-)수익률을 기록'
    fi_dir = '(+)수익률을 기록' if fi_global and fi_global > 0 else '(-)수익률을 기록'

    commodity_avg = np.nanmean([x for x in [gold, wti] if x is not None])
    cmd_dir = '(+)수익률을 기록' if commodity_avg > 0 else '(-)수익률을 기록'

    overview = f'{m}월 금융시장은 글로벌 주식시장과 글로벌 채권시장이 소폭 {eq_dir}한 반면, 원자재 시장은 {cmd_dir}하였습니다.'
    lines.append(overview)

    # 2문단: 주식 세부
    eq_details = []
    if sp500 is not None:
        eq_details.append(f'미국 S&P500은 {sp500:+.1f}%')
    if growth is not None and value is not None:
        if growth < value:
            eq_details.append(f'성장주({growth:+.1f}%)가 가치주({value:+.1f}%) 대비 부진')
        else:
            eq_details.append(f'성장주({growth:+.1f}%)가 가치주({value:+.1f}%) 대비 양호')
    if dm_exus is not None and dm_exus > 0:
        eq_details.append(f'미국 외 선진국({dm_exus:+.1f}%)이 양호')
    if em is not None and em > 0:
        eq_details.append(f'신흥국({em:+.1f}%)이 양호한 성과')

    if eq_details:
        eq_line = '글로벌 주식시장은 ' + ', '.join(eq_details) + '를 기록하였습니다.'
        # digest에서 주식 배경 추가
        eq_context = _build_context_from_digest(digest, 'equity_detail')
        if eq_context:
            # 가장 핵심적인 이벤트 1개를 배경으로 삽입
            eq_line = '글로벌 주식시장은 ' + eq_context[0] + '의 영향 속에서, ' + ', '.join(eq_details) + '를 기록하였습니다.'
        lines.append(eq_line)

    # 한국시장 — Price 지수(포인트) 사용
    kospi_price_level = bm_returns.get('KOSPI_PRICE', {}).get('level')
    if kospi is not None:
        if kospi_price_level:
            kospi_text = f'한국시장은 KOSPI 지수가 {kospi_price_level:,.0f}포인트를 기록하며 {kospi:+.1f}%의 수익률을 보였습니다.'
        else:
            kospi_text = f'한국시장은 {kospi:+.1f}%의 수익률을 기록하였습니다.'
        lines.append(kospi_text)

    # 달러 — digest 배경 포함
    if dxy is not None:
        dxy_dir = '강세' if dxy > 0 else '약세'
        fx_context = _build_context_from_digest(digest, 'fx')
        fx_reason = ''
        if fx_context:
            # 달러 방향 관련 클레임 중 짧은 것
            for ctx in fx_context:
                if any(k in ctx for k in ['달러', '워시', '연준', 'Fed', '위안', '엔']):
                    fx_reason = ctx
                    break
        if fx_reason and len(fx_reason) < 80:
            lines.append(f'달러는 {fx_reason}의 영향으로 전월 대비 {dxy_dir}({dxy:+.1f}%)를 보였습니다.')
        else:
            lines.append(f'달러는 전월 대비 {dxy_dir}({dxy:+.1f}%)를 보였습니다.')

    # 원/달러
    if usdkrw is not None:
        krw_dir = '약세(원화 가치 하락)' if usdkrw > 0 else '강세(원화 가치 상승)'
        lines.append(f'원/달러 환율은 {krw_dir}하며 {usdkrw:+.1f}% 변동하였습니다.')

    # 채권
    fi_parts = []
    if fi_us is not None:
        fi_parts.append(f'미국 채권시장은 {fi_us:+.2f}%')
    if fi_kr_3y is not None:
        fi_parts.append(f'한국 국채 3년 {fi_kr_3y:+.2f}%')
    if fi_kr_10y is not None:
        fi_parts.append(f'국채 10년 {fi_kr_10y:+.2f}%')
    if fi_parts:
        bond_context = _build_context_from_digest(digest, 'bond')
        if bond_context and len(bond_context[0]) < 80:
            lines.append(f'채권시장은 {bond_context[0]}의 영향으로 ' + ', '.join(fi_parts) + '를 기록하였습니다.')
        else:
            lines.append('채권시장은 ' + ', '.join(fi_parts) + '를 기록하였습니다.')

    # 원자재
    cmd_parts = []
    if gold is not None:
        cmd_parts.append(f'금 {gold:+.1f}%')
    if wti is not None:
        cmd_parts.append(f'WTI 유가 {wti:+.1f}%')
    if cmd_parts:
        lines.append('원자재는 ' + ', '.join(cmd_parts) + '를 기록하였습니다.')

    return '\n\t'.join(lines)


def generate_fund_performance(fund_code, fund_ret, pa, holdings, month):
    """펀드 성과 코멘트"""
    ret_pct = fund_ret['return']

    # 자산군 기여도 (보수비용/유동성 제외, 절대값 큰 순)
    major_classes = ['국내주식', '해외주식', '국내채권', '해외채권', '원자재']
    contrib_parts = []
    positive_classes = []
    negative_classes = []

    for cls in major_classes:
        if cls in pa and abs(pa[cls]) >= 0.01:
            contrib_parts.append(f'{cls} {pa[cls]:+.2f}%')
            if pa[cls] > 0.05:
                positive_classes.append(cls)
            elif pa[cls] < -0.05:
                negative_classes.append(cls)

    lines = []
    lines.append(f'{month}월 중 펀드는 {ret_pct:+.1f}%의 수익률을 기록하였습니다.')

    if positive_classes and negative_classes:
        pos_text = '과 '.join(positive_classes) if len(positive_classes) <= 2 else ', '.join(positive_classes)
        neg_text = '과 '.join(negative_classes) if len(negative_classes) <= 2 else ', '.join(negative_classes)
        lines.append(f'{pos_text}의 기여도가 컸으며, {neg_text}의 기여도는 부정적으로 작용하였습니다.')

    return '\n\t'.join(lines)


def generate_fund_performance_detailed(fund_code, fund_ret, pa, month):
    """상세 기여도 포함 펀드 성과 (포맷 D용)"""
    ret_pct = fund_ret['return']

    major = ['국내주식', '해외주식', '국내채권', '해외채권', '원자재']
    parts = []
    for cls in major:
        if cls in pa:
            parts.append(f'{cls} {pa[cls]:+.2f}%')

    text = f'펀드는 {month}월 중 {ret_pct:.2f}%(보수 차감전)의 수익률을 기록했습니다.'
    if parts:
        text += f' 자산군별 성과기여도는 {", ".join(parts)} 이었습니다.'

    return text


def generate_outlook(fund_code, bm_returns, holdings, year, month, next_digest=None):
    """향후 시장전망 및 운용계획 (익월 digest 기반 전망 포함)"""
    cfg = FUND_CONFIGS[fund_code]
    next_month = month + 1 if month < 12 else 1

    lines = []

    # 익월 digest 기반 시장 전망
    outlook_pieces = _build_outlook_from_digest(next_digest, holdings)
    if outlook_pieces:
        # 이벤트/전망을 자연스럽게 연결
        market_outlook_parts = []
        for p in outlook_pieces[:4]:  # 최대 4개
            if len(p) < 120:
                market_outlook_parts.append(p)

        if market_outlook_parts:
            lines.append(f'{next_month}월 시장은 ' + ' '.join(market_outlook_parts[:2]))
            if len(market_outlook_parts) > 2:
                lines.append(' '.join(market_outlook_parts[2:]))

    # 운용 계획
    lines.append(f'{next_month}월 중 펀드는 투자목적을 안정적으로 달성하기 위해 현재의 포트폴리오를 기본적으로 유지하되, 중동 사태의 전개 양상과 유가 추이를 면밀히 모니터링할 계획입니다.' if next_digest and '스태그플레이션' in next_digest.get('cross_themes', []) else f'{next_month}월 중 펀드는 투자목적을 안정적으로 달성하기 위해 현재의 포트폴리오를 기본적으로 유지할 계획입니다.')
    lines.append('시장 변동성의 확대로 실제 포트폴리오와 목표 포트폴리오 간 괴리가 과도하게 발생할 경우에는 리밸런싱을 통해 포트폴리오를 재조정할 계획입니다.')

    return '\n\t'.join(lines)


def generate_manager_comment(fund_code, pa, bm_returns):
    """매니저 코멘트 (포맷 A용)"""
    cfg = FUND_CONFIGS[fund_code]
    if not cfg.get('target_return') or not cfg.get('philosophy'):
        return ''

    lines = []
    lines.append(f'본 펀드는 연 {cfg["target_return"]:.0f}%의 목표수익률을 안정적으로 달성하는 데 주안을 두고 있습니다.')
    lines.append(f'이를 위해, {cfg["philosophy"]}')

    # 자산군별 전망 (편입 자산 기반)
    if pa.get('해외주식', 0) != 0:
        growth_ret = bm_returns.get('미국성장주', {}).get('return')
        if growth_ret is not None and growth_ret < 0:
            lines.append('미국 성장주의 경우 단기 변동성이 확대되고 있으나, 기업이익 전망치가 지속적으로 상승하고 있어 중기적으로는 다시 상승 전환할 것으로 보입니다.')
        elif growth_ret is not None:
            lines.append('미국 성장주는 기업이익 전망치의 지속적인 상승에 힘입어 양호한 성과 흐름이 지속될 것으로 기대합니다.')

    if pa.get('원자재', 0) != 0:
        gold_ret = bm_returns.get('Gold', {}).get('return')
        if gold_ret is not None:
            lines.append('금은 중앙은행들의 꾸준한 매수 수요와 맞물려 양호한 성과 흐름이 지속될 것으로 기대합니다.')

    return '\n  \t'.join(lines)


# ═══════════════════════════════════════════════════════
# 4. 포맷팅
# ═══════════════════════════════════════════════════════

def format_A(fund_code, common_market, fund_perf, outlook, manager_comment, holdings, month):
    """포맷 A: 08P22, 08N81, 08N33"""
    # 공통 마켓에서 펀드 미편입 자산 관련 내용 필터링
    filtered_market = _filter_by_holdings(common_market, holdings)

    text = f"""### {fund_code}
■ 월간 시장동향과 펀드의 움직임
\t{filtered_market}
\t{fund_perf}

■ 향후 시장전망과 펀드의 움직임
   \t{outlook}

■ 매니저 코멘트
  \t{manager_comment}
"""
    return text


def format_C(fund_code, common_market, fund_perf, outlook, holdings, month, fund_ret=None):
    """포맷 C: 07G04"""
    filtered_market = _filter_by_holdings(common_market, holdings)

    # 서브 포트폴리오 수익률
    sub_text = ''
    if fund_ret and fund_ret.get('sub_returns'):
        cfg = FUND_CONFIGS[fund_code]
        sub_parts = []
        for label, ret in fund_ret['sub_returns'].items():
            sub_parts.append(f'{label} 포트폴리오 {ret:+.2f}%')
        sub_text = f'\n- {month}월 중 ' + '와 '.join(sub_parts) + '을 기록하였습니다.'
        if cfg.get('sub_ratio'):
            sub_text += f' {cfg["sub_ratio"]} 비중을 유지하였습니다.'

    text = f"""### {fund_code}
[운용경과]
1. 시장 동향
- {filtered_market}

2. 운용경과
- {fund_perf}{sub_text}

[운용계획]
1. 시장 전망
- {outlook}

2. 포지션
- 현재의 포트폴리오를 기본적으로 유지하되, 시장 변동성 확대로 실제 포트폴리오와 목표 포트폴리오 간 괴리가 과도하게 확대될 경우에는 리밸런싱을 통해 재조정할 예정입니다.
"""
    return text


def format_D(fund_code, common_market, fund_perf_detailed, outlook, holdings, month):
    """포맷 D: 2JM23"""
    filtered_market = _filter_by_holdings(common_market, holdings)

    text = f"""### {fund_code}
1. 운용성과 요약
{filtered_market}
{fund_perf_detailed}

2. 시장환경 분석 및 펀드운용계획
시장환경 분석: {outlook}
펀드 운용 계획: 현재 구축되어 있는 최적 포트폴리오를 유지할 계획입니다. 변동성 확대 시에는 리밸런싱 기회로 활용하여 저평가된 자산 비중을 확대하고, 고평가된 자산의 비중을 축소할 계획입니다.
"""
    return text


def _filter_by_holdings(market_text, holdings):
    """펀드 미편입 자산군 관련 문장 제거"""
    lines = market_text.split('\n')
    filtered = []

    has_overseas_equity = holdings.get('해외주식', 0) > 1
    has_domestic_equity = holdings.get('국내주식', 0) > 1
    has_domestic_bond = holdings.get('국내채권', 0) > 1
    has_overseas_bond = holdings.get('해외채권', 0) > 1
    has_commodity = holdings.get('원자재', 0) > 1

    for line in lines:
        # 금/원자재 관련 — 원자재 미편입 시 제거
        if not has_commodity and any(k in line for k in ['금 ', '원자재', 'WTI', '유가']):
            continue
        # 해외주식 관련 — 미편입 시 제거
        if not has_overseas_equity and any(k in line for k in ['미국 외 선진국', '신흥국']):
            continue
        filtered.append(line)

    return '\n'.join(filtered)


# ═══════════════════════════════════════════════════════
# 6. LLM 기반 코멘트 생성
# ═══════════════════════════════════════════════════════

# 샘플 보고서 (포맷 참조용)
_SAMPLE_REPORTS = {
    'A': """■ 월간 시장동향과 펀드의 움직임
\t2월 금융시장은 글로벌 주식시장과 글로벌 채권시장이 소폭 (+)수익률을 기록한 반면, 원자재 시장은 (-)수익률을 기록하였습니다. 글로벌 주식시장은 양호한 기업실적에도 불구하고, 과도한 AI 인프라 투자와 AI의 기존 소프트웨어 시장 잠식에 대한 우려가 부각되면서 빅테크 및 소프트웨어 업체들이 부진한 성과를 보인 반면, 반도체 주식과 미국 외 선진국, 신흥국 시장이 양호한 성과를 기록하였습니다. 특히 한국시장은 KOSPI 지수가 6,300포인트를 돌파하면서 1월의 강세 흐름을 이어갔습니다. 달러는 케빈 워시의 차기 연준 의장 후보 지명으로 강세로 전환되었으며, 이에 따라 원자재시장은 약세로 전환하였습니다. 미국 주식시장의 변동성 확대로 미국 채권시장은 상대적으로 양호하였으며, 한국 채권시장도 금통위에서 한국은행 총재의 비둘기파적 발언에 힘입어 양호한 성과를 보여주었습니다.
\t2월 중 펀드는 0.5%의 수익률을 기록하였습니다. 국내 주식시장과 채권시장의 기여도가 컸으며, 미국 성장주와 금의 기여도는 부정적으로 작용하였습니다.

■ 향후 시장전망과 펀드의 움직임
   \t3월 국내주식시장은 실적전망치 상향조정과 정부의 친시장 조처에도 불구하고, 2월 28일 미국·이스라엘의 이란 공습과 이란의 호르무즈 해협 봉쇄로 인해 단기적으로 큰 변동성에 직면할 것으로 예상합니다. 글로벌 주식시장도 유가 급등과 지정학적 불확실성 확대로 위험자산 회피 심리가 강화되고 있어, 안정화까지 시간이 필요할 것으로 보입니다. 미국 대법원의 관세부과 위헌 판결로 무역불확실성이 커지고 있으나, 영향력은 제한적으로 보입니다. 3월 중 펀드는 투자목적을 안정적으로 달성하기 위해 현재의 포트폴리오를 기본적으로 유지하되, 중동 사태의 전개 양상과 유가 추이를 면밀히 모니터링할 계획입니다. 시장 변동성의 확대로 실제 포트폴리오와 목표 포트폴리오 간 괴리가 과도하게 발생할 경우에는 리밸런싱을 통해 포트폴리오를 재조정할 계획입니다.

■ 매니저 코멘트
  \t본 펀드는 연 5%의 목표수익률을 안정적으로 달성하는 데 주안을 두고 있습니다. 이를 위해, 분산투자에 초점을 두는 한편, 기대수익률이 높은 미국 성장주와 금의 비중을 상대적으로 높게 가져가고 있습니다.""",

    'C': """[운용경과]
1. 시장 동향
 4분기 글로벌 주식시장은 양호한 수익률을 기록한 반면, 국내 채권시장은 장기금리 상승의 영향으로 상대적으로 부진한 흐름을 보였습니다. 미국 주식시장은 연준의 금리인하와 견조한 경제성장 기대를 바탕으로 상승세를 이어갔으나, AI 관련 버블 논쟁과 밸류에이션 부담으로 기술주 중심의 변동성이 확대되었으며, 분기 후반에는 성장주 대비 가치주가 상대적으로 강세를 보였습니다. 채권시장은 미국의 금리인하에도 불구하고, 각국 정부와 기업들이 채권발행을 늘리면서 장기금리가 상승한 결과, 금리인하 효과가 희석되었습니다. 원자재시장에서는 원유가 큰 폭의 하락을 보인 반면, 금값은 큰 폭의 상승을 보였습니다.

2. 운용경과
 펀드는 4분기 0.74%의 수익률을 기록하였습니다. 채권대비 주식의 성과가 좋은 가운데, 주식비중을 높게 유지하여 자산배분효과가 긍정적으로 나타났으며, 해외주식에서 미국 성장주 비중을 높게 유지하여 종목선택효과는 불리하게 작용하였습니다. 채권은 비중을 벤치마크보다 낮게 유지하여 자산배분효과가 긍정적이었으나, 듀레이션을 높게 유지하여 종목선택효과는 부정적이었습니다.

[운용계획]
1. 시장 전망
 1분기 중 경기 둔화 국면으로 전환될 가능성이 높습니다. 그러나 글로벌 경제의 양극화 심화에 대응하여 각국이 부진한 업종을 지원하기 위한 통화 및 재정 정책을 발동할 것으로 예상합니다. 이에 따라 글로벌 유동성이 재차 확대되며 주식과 채권 시장이 동시에 강세를 보이는 랠리를 전망합니다.

2. 포지션
 현재의 미국 성장주 위주의 주식 비중 확대 포지션과 채권내 바벨 포지션을 유지할 계획입니다. 시장 변동성의 확대로 실제 포트폴리오와 목표 포트폴리오 간 괴리가 과도하게 발생할 경우에는 리밸런싱을 통해 포트폴리오를 재조정할 계획입니다.""",

    'D': """1. 운용성과 요약
2월 글로벌주식시장은 양호한 기업실적에도 불구하고 빅테크 업체들이 부진한 성과를 보인 반면, 반도체 주식과 미국외 선진국, 신흥국 시장이 양호한 성과를 기록하였습니다.
펀드는 2월 중 1.90%(보수 차감전)의 수익률을 기록했습니다. 자산군별 성과기여도는 국내주식 +0.39%, 국내채권 +0.35%, 해외주식 -1.45%, 해외채권 +0.00%, 원자재 -1.11% 이었습니다.

2. 시장환경 분석 및 펀드운용계획
시장환경 분석: 3월 국내주식시장은 실적전망치 상향조정과 정부의 친시장 조치에도 불구하고 변동성에 직면할 것으로 예상합니다.
펀드 운용 계획: 현재 구축되어 있는 최적 포트폴리오를 유지할 계획입니다.""",
}


def _build_llm_prompt(fund_code, year, month, bm_returns, fund_ret, pa, holdings,
                      digest, next_digest):
    """LLM 코멘트 생성용 프롬프트 조립"""
    cfg = FUND_CONFIGS[fund_code]
    fmt = cfg['format']
    m = month
    next_m = month + 1 if month < 12 else 1

    # ── 벤치마크 수익률 테이블 ──
    bm_lines = []
    for name in ['글로벌주식', 'KOSPI', 'KOSPI_PRICE', 'S&P500', '미국성장주', '미국가치주',
                  'Russell2000', '고배당', '미국외선진국', '신흥국주식',
                  '글로벌채권UH', '매경채권국채3년', 'KRX10년채권', 'KAP종합채권',
                  '미국종합채권', '미국IG', '미국HY', '신흥국채권',
                  'Gold', 'WTI', '미국리츠',
                  'DXY', 'USDKRW', 'EURUSD', 'JPYUSD']:
        info = bm_returns.get(name, {})
        ret = info.get('return')
        level = info.get('level')
        if ret is not None:
            lv_str = f', 수준={level:,.2f}' if level else ''
            bm_lines.append(f'  {name}: {ret:+.2f}%{lv_str}')
    bm_table = '\n'.join(bm_lines)

    # ── 펀드 성과 ──
    fund_ret_pct = fund_ret['return'] if fund_ret else None
    if fund_ret_pct is not None:
        fund_data = f'펀드 월수익률: {fund_ret_pct:+.2f}%'
    else:
        fund_data = '펀드 월수익률: 데이터 없음'

    # 서브 포트폴리오
    sub_text = ''
    if fund_ret and fund_ret.get('sub_returns'):
        parts = [f'{label}: {ret:+.2f}%' for label, ret in fund_ret['sub_returns'].items()]
        sub_text = f'\n서브 포트폴리오: {", ".join(parts)} (비중 {cfg.get("sub_ratio", "N/A")})'

    # ── PA 기여도 ──
    pa_lines = []
    for cls in ['국내주식', '해외주식', '국내채권', '해외채권', '원자재', '유동성', '보수비용']:
        if cls in pa:
            pa_lines.append(f'  {cls}: {pa[cls]:+.2f}%')
    pa_table = '\n'.join(pa_lines)

    # ── 보유종목 비중 ──
    hold_lines = [f'  {cls}: {wt:.1f}%' for cls, wt in sorted(holdings.items(), key=lambda x: -x[1]) if wt > 0.5]
    hold_table = '\n'.join(hold_lines)

    # ── Digest 요약 ──
    digest_text = ''
    if digest:
        d_parts = []
        for topic, info in digest.get('topics', {}).items():
            events = info.get('key_events', [])[:2]
            claims = info.get('key_claims', [])[:2]
            direction = info.get('direction', '')
            if events or claims:
                d_parts.append(f'[{topic}] ({direction})')
                for ev in events:
                    if 15 < len(ev) < 120:
                        d_parts.append(f'  - {ev}')
                for cl in claims:
                    if 15 < len(cl) < 120:
                        d_parts.append(f'  - {cl}')
        digest_text = '\n'.join(d_parts[:30])  # 토큰 절약

    next_digest_text = ''
    if next_digest:
        nd_parts = []
        themes = next_digest.get('cross_themes', [])
        if themes:
            nd_parts.append(f'주요 테마: {", ".join(themes[:5])}')
        for topic, info in next_digest.get('topics', {}).items():
            claims = info.get('key_claims', [])[:1]
            events = info.get('key_events', [])[:1]
            for item in events + claims:
                if 15 < len(item) < 120:
                    nd_parts.append(f'  [{topic}] {item}')
        next_digest_text = '\n'.join(nd_parts[:20])

    # ── 펀드 설정 ──
    fund_info = f'펀드코드: {fund_code}'
    if cfg.get('target_return'):
        fund_info += f'\n목표수익률: 연 {cfg["target_return"]:.0f}%'
    if cfg.get('philosophy'):
        fund_info += f'\n운용철학: {cfg["philosophy"]}'

    # ── 포지션 제약 ──
    constraint_text = ''
    if cfg.get('position_constraints'):
        constraint_text = f'\n\n## 포지션 제약 (반드시 준수)\n{cfg["position_constraints"]}'

    # ── 운용역 월별 narrative 로드 ──
    narrative_text = ''
    try:
        import yaml
        narrative_file = Path(__file__).resolve().parent / 'data' / 'narratives.yaml'
        if narrative_file.exists():
            with open(narrative_file, encoding='utf-8') as _nf:
                narratives = yaml.safe_load(_nf)
            month_key = f'{year}-{m:02d}'
            n = narratives.get(month_key, {})
            if n:
                parts = []
                if n.get('market_view'):
                    parts.append(f'[시장 판단]\n{n["market_view"].strip()}')
                if n.get('position_rationale'):
                    parts.append(f'[포지션 근거]\n{n["position_rationale"].strip()}')
                if n.get('upcoming_themes'):
                    parts.append(f'[향후 주요 테마]\n' + '\n'.join(f'- {t}' for t in n['upcoming_themes']))
                narrative_text = '\n'.join(parts)
    except Exception:
        pass

    narrative_section = ''
    if narrative_text:
        narrative_section = f'\n\n## 운용역 시장 판단 (반드시 반영)\n{narrative_text}'

    # ── 프롬프트 조립 ──
    prompt = f"""당신은 DB형 퇴직연금 OCIO 운용보고서 코멘트 작성자입니다.
아래 데이터를 바탕으로 {year}년 {m}월 운용보고 코멘트를 작성하세요.

## 작성 규칙 — 문체
1. 경어체 사용 ("~하였습니다", "~예상합니다", "~계획입니다")
2. **서술형 문단**: 마크다운 기호(#, ##, **, ---, -, 1.)를 절대 쓰지 마세요. [운용경과], [운용계획] 같은 섹션 구분자와 들여쓰기만 사용하세요. 글머리 기호나 볼드 없이, 순수 텍스트 문단으로 작성하세요.
3. **대비 구조 활용**: "A가 양호한 수익률을 기록한 반면, B는 상대적으로 부진한 흐름을 보였습니다" 패턴을 적극 사용하세요.
4. **인과 서술**: 단순 수치 나열이 아닌, "원인 + 결과"를 한 문장에 담으세요. 예: "각국 정부와 기업들이 채권발행을 늘리면서 장기금리가 상승한 결과, 금리인하 효과가 희석되었습니다"
5. 블로그 digest의 이벤트/분석을 자연스럽게 녹여서 서술 (출처 언급 금지)

## 작성 규칙 — 데이터
6. 벤치마크 수치는 제공된 데이터만 사용 (절대 수치를 만들어내지 마세요)
7. KOSPI 포인트는 KOSPI_PRICE의 수준값 사용 (TR 지수 아님)
8. PA 기여도 수치는 정확히 제공된 값 사용
9. 펀드에 편입되지 않은 자산군은 제외하거나 간략히만 언급

## 작성 규칙 — 균형과 분량
10. **자산군 균등 서술**: 주식뿐 아니라 채권, 원자재, 통화의 등락 원인도 반드시 서술하되, 각 자산군 1~2문장으로 간결하게.
11. **PA 기여도 전 자산군 언급**: 운용경과에서 기여도 0.05% 이상인 모든 자산군의 원인을 서술하세요. 구체적 종목명/전략명을 함께 언급하면 좋습니다.
12. **전망은 구체적 메커니즘 포함**: "변동성 모니터링" 같은 일반론이 아닌, "SLR 완화에 따른 유동성 공급 확대" 같은 구체적 인과 체인을 서술하세요. 익월 digest 테마를 활용하세요.
13. **포지션은 액션 포함**: "리밸런싱 계획" 수준이 아닌, 어떤 자산의 비중을 왜 어떻게 조정할 계획인지 서술하세요.

## 포맷
{_SAMPLE_REPORTS[fmt]}

## 벤치마크 월간 수익률 ({year}년 {m}월)
{bm_table}

## 펀드 데이터
{fund_info}
{fund_data}{sub_text}

## PA 자산군별 기여도
{pa_table}

## 펀드 보유 자산 비중
{hold_table}

## {m}월 시장 이벤트/분석 (블로그 기반)
{digest_text}

## {next_m}월 전망 소스 (익월 블로그)
{next_digest_text}{constraint_text}{narrative_section}

위 포맷 샘플과 동일한 구조, 톤, 분량으로 ### {fund_code} 보고서를 작성하세요.
수치는 반드시 제공된 데이터만 사용하세요."""

    return prompt


def _build_pa_focused_prompt(fund_code, year, month, bm_returns, fund_ret, pa,
                             holdings, selected_factors, holdings_diff=None,
                             brinson=None, index_context=None, pa_items=None):
    """PA 기여도 중심 프롬프트 — Brinson + 종목별 기여도 + 지수 맥락"""
    cfg = FUND_CONFIGS[fund_code]
    fmt = cfg['format']
    m = month

    # ── [시장동향용] 벤치마크 수익률 ──
    bm_lines = []
    for name in ['글로벌주식', 'KOSPI', 'KOSPI_PRICE', 'S&P500', '미국성장주', '미국가치주',
                  'Russell2000', '고배당', '미국외선진국', '신흥국주식',
                  '글로벌채권UH', '매경채권국채3년', 'KRX10년채권', 'KAP종합채권',
                  '미국종합채권', '미국IG', '미국HY', '신흥국채권',
                  'Gold', 'WTI', '미국리츠',
                  'DXY', 'USDKRW', 'EURUSD', 'JPYUSD']:
        info = bm_returns.get(name, {})
        ret = info.get('return')
        level = info.get('level')
        if ret is not None:
            lv_str = f', 수준={level:,.2f}' if level else ''
            bm_lines.append(f'  {name}: {ret:+.2f}%{lv_str}')
    bm_table = '\n'.join(bm_lines)

    # ── [시장동향용] 주요 지수 맥락 (고점/저점/MDD) ──
    idx_text = ''
    if index_context:
        idx_lines = []
        for name, info in index_context.items():
            if name.startswith('_'):
                continue
            unit = info.get('unit', '')
            line = f'  {name}: 전월말 {info["prev_last"]["value"]:,.2f}{unit}'
            line += f' → 당월말 {info["month_last"]["value"]:,.2f}{unit}'
            line += f' (월간 {info["monthly_return"]:+.2f}%)'
            if abs(info.get('peak_to_end', 0)) > 3:
                line += f', 고점({info["peak"]["date"][-5:]} {info["peak"]["value"]:,.2f}) 대비 {info["peak_to_end"]:+.1f}%'
            idx_lines.append(line)
        idx_text = '\n'.join(idx_lines)

    # ── [시장동향/운용계획용] EPS 변화 ──
    eps_text = ''
    if index_context and index_context.get('_eps'):
        eps_lines = []
        for name, info in index_context['_eps'].items():
            direction = '상향' if info['change_pct'] > 0 else '하향'
            eps_lines.append(f'  {name}: 12M Fwd EPS {info["prev"]} → {info["current"]} ({info["change_pct"]:+.1f}% {direction})')
        eps_text = '\n'.join(eps_lines)

    # ── 펀드 성과 ──
    fund_ret_pct = fund_ret['return'] if fund_ret else None
    fund_data = f'펀드 월수익률: {fund_ret_pct:+.2f}%' if fund_ret_pct is not None else '펀드 월수익률: 데이터 없음'

    sub_text = ''
    if fund_ret and fund_ret.get('sub_returns'):
        parts = [f'{label}: {ret:+.2f}%' for label, ret in fund_ret['sub_returns'].items()]
        sub_text = f'\n서브 포트폴리오: {", ".join(parts)} (비중 {cfg.get("sub_ratio", "N/A")})'

    # ── [운용경과용] Brinson Attribution ──
    brinson_text = ''
    if brinson:
        brin = brinson
        brinson_lines = [
            f'  펀드수익률: {brin.get("period_ap_return", 0):+.2f}%, BM수익률: {brin.get("period_bm_return", 0):+.2f}%, 초과수익: {brin.get("total_excess", 0):+.2f}%',
            f'  Allocation Effect 합계: {brin.get("total_alloc", 0):+.2f}%, Selection Effect 합계: {brin.get("total_select", 0):+.2f}%',
        ]
        pa_df = brin.get('pa_df')
        if pa_df is not None:
            if isinstance(pa_df, dict):
                import pandas as _pd
                pa_df = _pd.DataFrame(pa_df)
            for _, row in pa_df.iterrows():
                brinson_lines.append(
                    f'  {row["자산군"]}: AP비중 {row["AP비중"]:.1f}% vs BM비중 {row["BM비중"]:.1f}%, '
                    f'AP수익률 {row["AP수익률"]:+.2f}% vs BM수익률 {row["BM수익률"]:+.2f}%, '
                    f'Alloc {row["Allocation"]:+.2f}%, Select {row["Selection"]:+.2f}%'
                )
        brinson_text = '\n'.join(brinson_lines)

    # ── [운용경과용] 종목별 기여도 (상위 10개) ──
    items_text = ''
    if pa_items:
        items_lines = []
        sorted_items = sorted(pa_items, key=lambda x: abs(x.get('contrib_pct', 0)), reverse=True)
        for it in sorted_items[:10]:
            nm = it.get('item_name', '?')
            cls = it.get('asset_class', '?')
            wt = it.get('weight_pct', 0)
            ret = it.get('item_return_pct', 0)
            contrib = it.get('contrib_pct', 0)
            items_lines.append(f'  {nm} [{cls}] 비중 {wt:.1f}%, 수익률 {ret:+.2f}%, 기여도 {contrib:+.2f}%')
        items_text = '\n'.join(items_lines)

    # ── [운용경과용] PA 자산군 합산 ──
    pa_lines = [f'  {cls}: {pa[cls]:+.2f}%' for cls in
                ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', '대체', '원자재', '유동성', '보수비용']
                if cls in pa and abs(pa[cls]) >= 0.005]
    pa_table = '\n'.join(pa_lines)

    # ── [포지셔닝] 비중 + 변화 ──
    hold_lines = [f'  {cls}: {wt:.1f}%' for cls, wt in sorted(holdings.items(), key=lambda x: -x[1]) if wt > 0.5]
    hold_table = '\n'.join(hold_lines)

    diff_text = ''
    if holdings_diff:
        diff_lines = []
        for cls, info in sorted(holdings_diff.items(), key=lambda x: abs(x[1]['change']), reverse=True):
            direction = "확대" if info['change'] > 0 else "축소"
            diff_lines.append(f'  {cls}: {info["prev"]:.1f}% → {info["cur"]:.1f}% ({info["change"]:+.1f}%p {direction})')
        diff_text = '\n'.join(diff_lines)

    # ── 선택 요인 ──
    factor_text = ''
    for asset_class, factors in selected_factors.items():
        factor_text += f'\n[{asset_class}]:\n'
        for f in factors:
            factor_text += f'  - {f}\n'

    # ── 펀드 정보 ──
    fund_info = f'펀드코드: {fund_code}'
    if cfg.get('target_return'):
        fund_info += f'\n목표수익률: 연 {cfg["target_return"]:.0f}%'
    if cfg.get('philosophy'):
        fund_info += f'\n운용철학: {cfg["philosophy"]}'

    # ── 프롬프트 조립 ──
    prompt = f"""당신은 DB형 퇴직연금 OCIO 운용보고서 코멘트 작성자입니다.
아래 데이터와 선택된 요인을 바탕으로 {year}년 {m}월 운용보고 코멘트를 작성하세요.

## 작성 규칙
1. 경어체 사용 ("~하였습니다", "~예상합니다", "~계획입니다")
2. 제공된 데이터의 수치만 사용 (절대 만들어내지 마세요)
3. 선택되지 않은 요인은 넣지 마세요

## 시장동향 작성 규칙
4. **[시장동향용] 데이터만 활용**: 벤치마크 수익률, 지수 맥락(고점/저점/MDD), 선택 요인의 원인 부분
5. 글로벌 주식, 채권, 원자재, 통화 각각의 움직임과 원인을 구체적으로 서술 (4~6문장)
6. **지수 포인트를 적극 활용**: "KOSPI 지수가 X포인트에서 Y포인트로 하락", "2/26 고점 대비 Z% 하락" 등 임팩트 있는 표현
7. 포지셔닝 변화도 시장동향 말미에 서술 ("국내채권 비중을 X%에서 Y%로 확대")

## 운용경과 작성 규칙 (핵심)
8. **[운용경과용] 데이터만 활용**: PA 기여도, Brinson Attribution, 종목별 기여도. **BM 지수 수익률(S&P500 -5% 등)을 직접 인용하지 마세요.**
9. **Brinson 활용**: "BM 대비 국내채권 비중을 높게(AP X% vs BM Y%) 가져간 결과 Selection Effect Z%", "전체 포트폴리오 성과는 BM을 X%p 상회/하회"
10. **종목별 기여도 활용**: "ACE 200TR이 -8.76% 하락하며 국내주식 기여도 -1.08%를 기록"
11. PA 기여도가 큰 자산군부터 순서대로, 자산군당 1~3문장

## 운용계획 작성 규칙 (매우 중요)
12. **시장 전망은 데이터 기반 판단으로 마무리**: 단순 "변동성 지속 예상"이 아니라, EPS 변화와 밸류에이션을 근거로 구체적 판단을 내리세요.
    - 예: "기업실적(12M Fwd EPS) 상향 추세가 유지되고 있어 펀더멘털 훼손 없이 단기 조정에 머물 것으로 판단합니다"
    - 예: "EPS 하향 조정(-18%)이 진행 중이어서 추가 하락 가능성을 열어두고 있습니다"
13. **포지션은 조건부 행동 계획**: "시장이 A하면 B하겠다" 구조로 작성하세요.
    - 예: "BM 대비 해외주식 비중이 크게 벗어나 있어(AP 20% vs BM 34%), 지정학적 리스크 완화 시 해외주식 비중을 BM 수준으로 회복할 계획입니다"
    - 예: "원화 약세 지속 시 환헤지 비중을 확대하고, 안정화 시 현 수준을 유지할 계획입니다"
14. 비중 변화 데이터와 Brinson의 AP/BM 비중 괴리를 활용하세요.

## 포맷 (이 샘플의 구조, 톤, 분량을 따르세요)
{_SAMPLE_REPORTS[fmt]}

## ═══ [시장동향용 데이터] — 시장동향 섹션에서만 사용 ═══

### 벤치마크 월간 수익률 ({year}년 {m}월)
{bm_table}

### 주요 지수 맥락 (고점/저점/MDD)
{idx_text if idx_text else '데이터 없음'}

### 12M Forward EPS 변화 (전월말 → 당월말)
{eps_text if eps_text else '데이터 없음'}

## ═══ [운용경과용 데이터] — 운용경과 섹션에서만 사용 ═══

### 펀드 성과
{fund_info}
{fund_data}{sub_text}

### Brinson Attribution (BM 대비 운용 성과)
{brinson_text if brinson_text else 'BM 미설정 — PA 기여도만으로 서술하세요'}

### PA 자산군별 기여도
{pa_table}

### 종목별 기여도 (상위 10개)
{items_text if items_text else '데이터 없음'}

## ═══ [운용계획용 데이터] ═══

### 보유 비중
{hold_table}

### 기간 중 비중 변화
{diff_text if diff_text else '유의미한 비중 변화 없음'}

### EPS 기반 펀더멘털 판단 참고
{eps_text if eps_text else '데이터 없음'}

## ═══ [선택 요인] — 시장동향(원인)과 운용경과(결과)에서 근거로 활용 ═══
{factor_text}

위 샘플과 동일한 구조, 톤, **분량**으로 작성하세요.
수치는 반드시 제공된 데이터만 사용하세요."""

    return prompt


def _build_macro_overview_prompt(year, month, bm_returns, selected_factors,
                                 cross_themes=None, news_themes=None):
    """매크로 오버뷰 프롬프트 — 시장 전반 테마 중심"""
    m = month

    # 벤치마크 테이블
    bm_lines = []
    for name in ['글로벌주식', 'KOSPI', 'KOSPI_PRICE', 'S&P500', '미국성장주', '미국가치주',
                  'Russell2000', '미국외선진국', '신흥국주식',
                  '글로벌채권UH', '매경채권국채3년', '미국종합채권', '미국HY',
                  'Gold', 'WTI', '미국리츠',
                  'DXY', 'USDKRW', 'EURUSD', 'JPYUSD']:
        info = bm_returns.get(name, {})
        ret = info.get('return')
        level = info.get('level')
        if ret is not None:
            lv_str = f', 수준={level:,.2f}' if level else ''
            bm_lines.append(f'  {name}: {ret:+.2f}%{lv_str}')
    bm_table = '\n'.join(bm_lines)

    # 크로스 테마
    theme_text = ''
    if cross_themes:
        theme_text = f'블로그 크로스 테마: {", ".join(cross_themes[:7])}'

    # 뉴스 핵심 테마
    news_theme_text = ''
    if news_themes:
        parts = []
        for t in news_themes[:10]:
            parts.append(f'  - {t.get("summary_kr", t.get("label", ""))} ({t["article_count"]}건)')
        news_theme_text = '\n'.join(parts)

    # 선택된 요인 (테마별)
    factor_text = ''
    for theme, factors in selected_factors.items():
        factor_text += f'\n[{theme}]:\n'
        for f in factors:
            factor_text += f'  - {f}\n'

    prompt = f"""당신은 DB형 퇴직연금 OCIO 시장환경 분석가입니다.
아래 데이터를 바탕으로 {year}년 {m}월 **매크로 시장환경 오버뷰**를 작성하세요.

## 작성 규칙
1. 경어체 사용 ("~하였습니다", "~전망됩니다")
2. 벤치마크 수치는 제공된 데이터만 사용
3. **테마 중심 서술**: 개별 자산군이 아니라 시장을 관통하는 매크로 테마로 구성
4. 주식 → 채권 → 대체/원자재 → 통화 순서로 시장환경 서술
5. 각 테마는 선택된 요인을 근거로 서술
6. 선택되지 않은 요인은 넣지 마세요
7. 전체 분량: 400~600자

## 구조
### 시장환경
(전반적 매크로 환경 + 주요 테마별 시장 동향)

### 향후 전망
(다음 달 주요 이벤트 + 리스크 요인)

## 벤치마크 월간 수익률 ({year}년 {m}월)
{bm_table}

## 매크로 크로스 테마
{theme_text}

## 뉴스 핵심 테마 (빈도순)
{news_theme_text}

## 선택 요인
{factor_text}

위 구조로 시장환경 오버뷰를 작성하세요. 수치는 반드시 제공된 데이터만 사용하세요."""

    return prompt


def generate_report_llm(fund_code, year, month, bm_returns, fund_ret, pa, holdings,
                        digest, next_digest):
    """Claude API로 코멘트 생성"""
    prompt = _build_llm_prompt(fund_code, year, month, bm_returns, fund_ret, pa, holdings,
                                digest, next_digest)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text
    usage = response.usage
    cost_in = usage.input_tokens * 3 / 1_000_000   # Sonnet $3/1M input
    cost_out = usage.output_tokens * 15 / 1_000_000  # Sonnet $15/1M output
    total_cost = cost_in + cost_out

    print(f'    LLM: {usage.input_tokens} in + {usage.output_tokens} out = ${total_cost:.4f}', flush=True)

    return text, total_cost


# ═══════════════════════════════════════════════════════
# 5. 메인
# ═══════════════════════════════════════════════════════

def generate_report(fund_code, year, month, bm_returns=None, pa_all=None,
                    digest=None, next_digest=None, use_llm=False, quarter=None):
    """단일 펀드 보고서 생성. quarter=1~4 지정 시 분기 모드."""
    cfg = FUND_CONFIGS[fund_code]

    if quarter:
        # ── 분기 모드 ──
        if bm_returns is None:
            bm_returns = load_benchmark_returns_quarter(year, quarter)
        fund_ret = load_fund_return_quarter(fund_code, year, quarter)
        pa = (pa_all.get(fund_code, {}) if pa_all
              else load_all_pa_attributions_quarter([fund_code], year, quarter).get(fund_code, {}))
        holdings = load_fund_holdings_summary_quarter(fund_code, year, quarter)

        if not fund_ret:
            return f'### {fund_code}\n[데이터 부족: 펀드 수익률 조회 실패]\n', 0

        # 분기용 digest: 분기 마지막 월
        _, end_month = _quarter_dates(year, quarter)
        if digest is None:
            digest = load_digest(year, end_month)
        if next_digest is None:
            next_q_month = end_month + 1 if end_month < 12 else 1
            next_q_year = year if end_month < 12 else year + 1
            next_digest = load_digest(next_q_year, next_q_month)

        if use_llm:
            text, cost = generate_report_llm(fund_code, year, end_month, bm_returns, fund_ret, pa,
                                              holdings, digest, next_digest)
            # 프롬프트에서 월 → 분기 프레이밍 치환
            q_label = f'{quarter}분기'
            text = text.replace(f'{end_month}월', q_label).replace(f'{year}년 {end_month}월', f'{year}년 {q_label}')
            return f'### {fund_code}\n{text}', cost

        # 템플릿 모드 fallback (월간과 동일 구조, 마지막 월 기준)
        return generate_report(fund_code, year, end_month, bm_returns=bm_returns,
                               pa_all={fund_code: pa}, digest=digest, next_digest=next_digest,
                               use_llm=False, quarter=None), 0

    # ── 월간 모드 (기존) ──
    if bm_returns is None:
        bm_returns = load_benchmark_returns(year, month)
    fund_ret = load_fund_return(fund_code, year, month)
    pa = pa_all.get(fund_code, {}) if pa_all else load_pa_attribution(fund_code, year, month)
    holdings = load_fund_holdings_summary(fund_code, year, month)

    if not fund_ret:
        return f'### {fund_code}\n[데이터 부족: 펀드 수익률 조회 실패]\n', 0

    # LLM 모드
    if use_llm:
        text, cost = generate_report_llm(fund_code, year, month, bm_returns, fund_ret, pa,
                                          holdings, digest, next_digest)
        return f'### {fund_code}\n{text}', cost

    # 템플릿 모드 (기존)
    common_market = generate_common_market(bm_returns, year, month, digest=digest)
    fund_perf = generate_fund_performance(fund_code, fund_ret, pa, holdings, month)
    outlook = generate_outlook(fund_code, bm_returns, holdings, year, month, next_digest=next_digest)

    fmt = cfg['format']
    if fmt == 'A':
        manager = generate_manager_comment(fund_code, pa, bm_returns)
        return format_A(fund_code, common_market, fund_perf, outlook, manager, holdings, month), 0
    elif fmt == 'C':
        return format_C(fund_code, common_market, fund_perf, outlook, holdings, month, fund_ret=fund_ret), 0
    elif fmt == 'D':
        fund_perf_d = generate_fund_performance_detailed(fund_code, fund_ret, pa, month)
        return format_D(fund_code, common_market, fund_perf_d, outlook, holdings, month), 0
    else:
        return f'### {fund_code}\n[미지원 포맷: {fmt}]\n', 0


def run(year=2026, month=2, use_llm=False):
    """전체 샘플 펀드 보고서 생성. use_llm=True면 Claude API 사용."""
    mode = 'LLM (Claude API)' if use_llm else '템플릿'
    print(f'=== {year}년 {month}월 운용보고 코멘트 생성 [{mode}] ===\n')

    # 공통 데이터 사전 로딩
    print('  벤치마크 로딩...', flush=True)
    bm_returns = load_benchmark_returns(year, month)
    print(f'  벤치마크 {len(bm_returns)}개 완료', flush=True)

    print('  PA 일괄 로딩...', flush=True)
    fund_codes = list(FUND_CONFIGS.keys())
    pa_all = load_all_pa_attributions(fund_codes, year, month)
    print(f'  PA {len(pa_all)}개 펀드 완료', flush=True)

    # 블로그 digest 로딩 (당월 + 익월)
    print('  블로그 digest 로딩...', flush=True)
    digest = load_digest(year, month)
    next_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    next_digest = load_digest(next_year, next_month)
    print(f'  당월 digest: {"있음" if digest else "없음"}, 익월 digest: {"있음" if next_digest else "없음"}', flush=True)

    all_reports = []
    total_cost = 0
    for fund_code in FUND_CONFIGS:
        print(f'  [{fund_code}] 생성 중...', flush=True)
        report, cost = generate_report(fund_code, year, month, bm_returns=bm_returns, pa_all=pa_all,
                                        digest=digest, next_digest=next_digest, use_llm=use_llm)
        all_reports.append(report)
        total_cost += cost
        print(f'  [{fund_code}] 완료', flush=True)

    if use_llm:
        print(f'\n  총 API 비용: ${total_cost:.4f}', flush=True)

    output = '\n'.join(all_reports)

    # 파일 저장
    suffix = '_llm' if use_llm else ''
    outfile = OUTPUT_DIR / f'report_{year}{month:02d}{suffix}.txt'
    outfile.write_text(output, encoding='utf-8')
    print(f'\n[저장] {outfile}')

    # 콘솔 출력
    print('\n' + '=' * 80)
    print(output)

    return output


# ═══════════════════════════════════════════════════════
# 통합 CLI용 — 인터뷰/inputs 기반 프롬프트 빌드 + 생성
# ═══════════════════════════════════════════════════════

def build_report_prompt(fund_code, year, quarter, data_ctx, inputs,
                        past_comments=None, detail=False,
                        start_date=None, end_date=None):
    """inputs dict + data_ctx → LLM 프롬프트 빌드.

    Parameters
    ----------
    fund_code : str
    year, quarter : int
    data_ctx : dict  — keys: bm, fund_ret, pa, holdings_end, holdings_diff
    inputs : dict    — keys: market_view, position_rationale, outlook, risk, additional
    past_comments : list[dict] | None — [{file, code, text}, ...]
    detail : bool — True면 과거 코멘트 few-shot 상세 양식
    start_date, end_date : date | None — 분석 기간. None이면 분기 기준 fallback.
    """
    cfg = FUND_CONFIGS.get(fund_code, {})
    fmt = cfg.get('format', 'C')
    _, end_month = _quarter_dates(year, quarter)

    # 기간 레이블: start_date/end_date 그대로 사용
    if start_date and end_date:
        period_desc = f'{start_date} ~ {end_date}'
    else:
        period_desc = f'{year}년 {quarter}분기'

    # BM 테이블
    bm = data_ctx.get('bm', {})
    bm_lines = []
    for name in ['글로벌주식', 'KOSPI', 'KOSPI_PRICE', 'S&P500', '미국성장주', '미국가치주',
                  'Russell2000', '고배당', '미국외선진국', '신흥국주식',
                  '글로벌채권UH', '매경채권국채3년', 'KRX10년채권', 'KAP종합채권',
                  '미국종합채권', '미국IG', '미국HY', '신흥국채권',
                  'Gold', 'WTI', '미국리츠', 'DXY', 'USDKRW']:
        info = bm.get(name, {})
        ret = info.get('return')
        level = info.get('level')
        if ret is not None:
            lv_str = f', 수준={level:,.2f}' if level else ''
            bm_lines.append(f'  {name}: {ret:+.2f}%{lv_str}')
    bm_table = '\n'.join(bm_lines)

    # 펀드 성과
    fund_ret = data_ctx.get('fund_ret')
    fund_data = f'펀드 수익률 ({period_desc}): {fund_ret["return"]:+.2f}%' if fund_ret else '데이터 없음'
    sub_text = ''
    if fund_ret and fund_ret.get('sub_returns'):
        parts = [f'{k}: {v:+.2f}%' for k, v in fund_ret['sub_returns'].items()]
        sub_text = f'\n서브 포트폴리오: {", ".join(parts)} (비중 {cfg.get("sub_ratio", "N/A")})'

    # PA
    pa = data_ctx.get('pa', {})
    pa_lines = [f'  {cls}: {v:+.2f}%' for cls, v in sorted(pa.items(), key=lambda x: -abs(x[1])) if abs(v) >= 0.01]
    pa_table = '\n'.join(pa_lines)

    # 비중변화
    diff_lines = []
    for d in data_ctx.get('holdings_diff', []):
        diff_lines.append(f'  {d["asset_class"]}: {d["prev"]}% → {d["cur"]}% ({d["change"]:+.1f}%p {d["direction"]})')
    diff_table = '\n'.join(diff_lines) if diff_lines else '  유의미한 변동 없음'

    # 보유비중 (분기말)
    holdings = data_ctx.get('holdings_end', {})
    hold_lines = [f'  {cls}: {wt:.1f}%' for cls, wt in sorted(holdings.items(), key=lambda x: -x[1]) if wt > 0.5]
    hold_table = '\n'.join(hold_lines)

    # 펀드 정보
    fund_info = f'펀드코드: {fund_code}'
    if cfg.get('target_return'):
        fund_info += f'\n목표수익률: 연 {cfg["target_return"]:.0f}%'
    if cfg.get('philosophy'):
        fund_info += f'\n운용철학: {cfg["philosophy"]}'

    # evidence list ([ref:N] 인용용, R6-A) — inputs.evidence_annotations 우선,
    # 없으면 빈 섹션. ref 번호는 ann 의 'ref' 필드 값을 그대로 사용 (시장 debate
    # 가 부여한 번호를 펀드 코멘트에서도 재사용 → comment_trace 매핑 일관)
    evidence_lines = []
    evidence_annotations = inputs.get('evidence_annotations') or []
    for ann in evidence_annotations:
        ref = ann.get('ref')
        if ref is None:
            continue
        title = (ann.get('title') or '')[:80]
        source = ann.get('source') or ''
        date = ann.get('date') or ''
        meta_parts = [p for p in (source, date) if p]
        meta = f' ({", ".join(meta_parts)})' if meta_parts else ''
        evidence_lines.append(f'- [ref:{ref}] {title}{meta}')
    evidence_block = ''
    if evidence_lines:
        evidence_block = (
            '\n\n## 인용 가능한 증거 자료 (시장 debate 의 evidence)\n'
            + '\n'.join(evidence_lines)
            + '\n\n## 증거 인용 규칙\n'
            '- 시장 동향/외부 사실(가격 움직임, 정책, 사건)을 서술할 때 문장 끝에 [ref:N] 을 붙이세요.\n'
            '- 펀드 데이터(수익률/PA/보유/거래)에는 [ref:N] 을 붙이지 마세요.\n'
            '- 운용역 의견 / 전망 / 일반론에는 붙이지 마세요.\n'
            '- N 은 위 목록의 번호만 사용하세요 (목록에 없는 번호 금지).\n'
            '- 문장당 최대 2개까지만 인용하세요.'
        )

    # inputs 섹션 (운용역 판단 / debate 결과)
    input_sections = []
    if inputs.get('market_view'):
        input_sections.append(f'[운용역 시장 판단]\n{inputs["market_view"]}')
    if inputs.get('position_rationale'):
        input_sections.append(f'[포지션 변경 근거]\n{inputs["position_rationale"]}')
    if inputs.get('outlook'):
        input_sections.append(f'[향후 전망/테마]\n{inputs["outlook"]}')
    if inputs.get('risk'):
        input_sections.append(f'[리스크 요인]\n{inputs["risk"]}')
    if inputs.get('additional'):
        input_sections.append(f'[추가 강조]\n{inputs["additional"]}')
    if inputs.get('history_diff'):
        input_sections.append(f'[전분기 대비 변화]\n{inputs["history_diff"]}')
    input_text = '\n\n'.join(input_sections) if input_sections else '(입력 없음 — 데이터 기반으로 자동 생성)'

    # 과거 코멘트 (few-shot)
    past_sample = ''
    past_comments = past_comments or []
    fund_comments = [c for c in past_comments if c['code'] == fund_code]
    if fund_comments:
        latest = fund_comments[-1]
        past_sample = f'\n\n## 과거 코멘트 문체 참고 ({latest["file"]})\n아래 과거 코멘트의 톤, 구조, 표현 방식을 참고하되 내용은 현재 분석 기간 데이터와 운용역 판단만 사용하세요.\n\n{latest["text"][:1500]}'

    # 포지션 제약
    constraint_text = ''
    if cfg.get('position_constraints'):
        constraint_text = f'\n\n## 포지션 제약 (반드시 준수)\n{cfg["position_constraints"]}'

    # 시계열 내러티브 (교차 분석 레이어)
    narrative_text = ''
    narrative = data_ctx.get('timeseries_narrative', '')
    if narrative:
        narrative_text = f'\n\n{narrative}\n위 시계열 변동은 기간 내 실제 가격 움직임과 관련 뉴스입니다. 주요 변곡점(급락→반등 등)이 있으면 "~와 맞물려", "~속에서" 등 표현으로 코멘트에 반영하세요. 인과관계를 단정하지 마세요.'

    # 기간 내 가격 패턴 (저점/반등/MDD) — 통계만 제공, 패턴 라벨 제거
    pattern_text = ''
    patterns = data_ctx.get('price_patterns', {})
    notable = {k: v for k, v in patterns.items()
               if abs(v.get('mdd', 0)) > 5 or abs(v.get('end_return', 0)) > 5}
    if notable:
        p_lines = []
        for name, p in notable.items():
            p_lines.append(
                f'  {name}: '
                f'저점 {p["low_date"]}({p["low_return"]:+.1f}%), '
                f'고점 {p["high_date"]}({p["high_return"]:+.1f}%), '
                f'MDD {p["mdd"]:.1f}%, 반등 {p["rebound"]:+.1f}%, '
                f'기간종료 {p["end_return"]:+.1f}%'
            )
        pattern_text = '\n\n## 기간 내 가격 통계 (저점/고점/MDD)\n' + '\n'.join(p_lines)

    # 양식 결정
    if detail and fund_comments:
        format_sample = fund_comments[-1]['text'][:3000]
        format_instruction = """## 양식 샘플 (이 구조와 톤을 정확히 따르세요)
아래는 이전 기간의 실제 보고서입니다. 동일한 섹션 구조, 번호 체계(1/2, -, ㅇ, ①②③, A.B.C.), 톤을 따르되 내용은 현재 분석 기간 데이터만 사용하세요.
성과요인분해 테이블, SAA대비 운용현황 테이블은 데이터가 제공된 경우에만 작성하세요.

""" + format_sample
        format_markers = '구분 기호는 -, ㅇ, ①②③, A.B.C. 만 사용하세요 (아래 양식 샘플 참고).'
    else:
        format_sample = _SAMPLE_REPORTS.get(fmt, _SAMPLE_REPORTS['C'])
        format_instruction = f"""## 포맷 (이 양식을 따르세요)
{format_sample}"""
        format_markers = '[운용경과], [운용계획] 같은 섹션 구분자와 들여쓰기만 사용하세요. 순수 텍스트 문단으로 작성하세요.'

    prompt = f"""당신은 DB형 퇴직연금 OCIO 운용보고서 코멘트 작성자입니다.
아래 데이터와 운용역 인터뷰 응답을 바탕으로 분석 기간 {period_desc}의 운용보고 코멘트를 작성하세요.
"분기", "월간" 등의 표현은 실제 분석 기간에 맞춰 사용하세요. 기간이 1개월이면 "월간/당월"로, 분기면 "분기 중"으로 서술하세요.

## 작성 규칙 — 문체
1. 경어체 사용 ("~하였습니다", "~예상합니다", "~계획입니다")
2. 마크다운 기호(#, ##, **, ---, 불릿)를 절대 쓰지 마세요.
3. {format_markers}
4. 대비 구조 활용: "A가 양호한 반면, B는 부진" 패턴을 적극 사용하세요.
5. 인과 서술: "원인 + 결과"를 한 문장에 담으세요.

## 작성 규칙 — 데이터
6. 벤치마크 수치는 제공된 데이터만 사용 (절대 수치를 만들어내지 마세요)
7. KOSPI 포인트는 KOSPI_PRICE의 수준값 사용 (TR 지수 아님)
8. PA 기여도 수치는 정확히 제공된 값 사용

## 작성 규칙 — 핵심
9. 운용역 인터뷰 응답을 최우선으로 반영하되, 데이터와 교차 검증하여 자연스럽게 서술하세요.
10. 전망과 포지션은 운용역 답변의 구체적 메커니즘과 액션을 반영하세요. 일반론("모니터링 계획") 금지.
11. PA 기여도 0.05% 이상인 모든 자산군의 원인을 서술하세요.

{format_instruction}

## 벤치마크 수익률 ({period_desc})
{bm_table}

## 펀드 데이터
{fund_info}
{fund_data}{sub_text}

## PA 자산군별 기여도
{pa_table}

## 기간 비중 변화
{diff_table}

## 펀드 보유 자산 비중 (기간말)
{hold_table}

## 운용역 판단 (반드시 반영)
{input_text}{constraint_text}{past_sample}{narrative_text}{pattern_text}{evidence_block}

위 포맷과 동일한 구조, 톤, 분량으로 {fund_code} ({period_desc}) 보고서를 작성하세요.
수치는 반드시 제공된 데이터만 사용하세요."""

    return prompt


def generate_report_from_inputs(fund_code, year, quarter, data_ctx, inputs,
                                past_comments=None, detail=False,
                                model=None,
                                start_date=None, end_date=None):
    """inputs + data → 프롬프트 빌드 → LLM 호출 → (comment, cost) 반환.

    Parameters
    ----------
    model : str | None — 기본값 LLM_MODEL (claude-sonnet-4-6)
    start_date, end_date : date | None — 분석 기간. None이면 분기 기준 fallback.
    """
    if model is None:
        model = LLM_MODEL

    prompt = build_report_prompt(
        fund_code, year, quarter, data_ctx, inputs,
        past_comments=past_comments, detail=detail,
        start_date=start_date, end_date=end_date,
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=model,
        max_tokens=5000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    usage = response.usage
    cost_in = usage.input_tokens * 3 / 1_000_000
    cost_out = usage.output_tokens * 15 / 1_000_000
    cost = cost_in + cost_out

    return {
        'comment': text,
        'model': model,
        'cost': cost,
        'token_usage': {
            'input_tokens': usage.input_tokens,
            'output_tokens': usage.output_tokens,
        },
    }


if __name__ == '__main__':
    run()
