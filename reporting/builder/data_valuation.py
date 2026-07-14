"""밸류에이션 데이터 — SCIP Bloomberg 라인 (실제 지수, ETF proxy 아님).

ds52=12M Fwd PE / ds45=12M Fwd EPS / ds48=PX_LAST. 매핑 정본 = Bloomberg/server.py
VAL_META ([[reference_scip_bloomberg_valuation]]). valuation.js 와 소수점 일치 검증(2026-07-13).
⚠️ 2024-09-30 이전 ds45/52 히스토리는 1FY 오염(재적재 대기) — 발송본도 동일 소스라 재현 무영향.
"""
import pymysql

from . import common  # noqa: F401
from modules.data_loader import parse_data_blob

# dataset_id → 심볼 (Bloomberg/server.py VAL_META + ds52 전수조사 2026-07-13)
DATASETS = {
    225: 'KOSPI2', 271: 'SPX', 272: 'XNDX', 334: 'MXWD', 335: 'MXUS',
    336: 'MXUS000G', 337: 'MXUS000V', 338: 'RTY', 339: 'MXWOU', 340: 'MXEF',
    341: 'MXKR', 342: 'MXCN', 343: 'MXJP', 344: 'MXDE', 345: 'MXGB',
    346: 'MXIN', 347: 'MXRU', 348: 'MXBR', 349: 'MXID', 350: 'MXZA',
    429: 'SOX', 430: 'BUBT7P',
}
_SYM2DID = {v: k for k, v in DATASETS.items()}


def load_valuation(end_date: str, syms=None) -> dict:
    """{sym: {'series': [(iso, pe, eps)], 'px': [(iso, v)]}} — pe 일자 기준, eps ffill."""
    dids = [_SYM2DID[s] for s in (syms or _SYM2DID)]
    conn = pymysql.connect(host='192.168.195.55', user='solution', password='Solution123!',
                           db='SCIP', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
    try:
        cur = conn.cursor()
        ph = ','.join(['%s'] * len(dids))
        cur.execute(f"""
            SELECT dataset_id did, dataseries_id sid,
                   DATE(timestamp_observation) d, data
            FROM back_datapoint
            WHERE dataset_id IN ({ph}) AND dataseries_id IN (45, 52, 48)
              AND DATE(timestamp_observation) <= %s
            ORDER BY dataset_id, timestamp_observation
        """, dids + [end_date])
        rows = cur.fetchall()
    finally:
        conn.close()

    acc = {}
    for r in rows:
        sym = DATASETS[r['did']]
        try:
            v = parse_data_blob(r['data'])
            if isinstance(v, dict):
                continue
        except Exception:
            continue
        d = r['d'].strftime('%Y-%m-%d')
        acc.setdefault(sym, {'pe': {}, 'eps': {}, 'px': {}})
        key = {52: 'pe', 45: 'eps', 48: 'px'}[r['sid']]
        if key == 'pe' and v <= 0:
            continue
        acc[sym][key][d] = float(v)

    out = {}
    for sym, a in acc.items():
        pe_d, eps_d = sorted(a['pe']), sorted(a['eps'])
        if len(pe_d) < 2 or not eps_d:
            continue
        start = max(pe_d[0], eps_d[0])
        series, last_eps, ei = [], None, 0
        for d in pe_d:
            if d < start:
                continue
            while ei < len(eps_d) and eps_d[ei] <= d:
                last_eps = a['eps'][eps_d[ei]]; ei += 1
            if last_eps is None:
                continue
            series.append((d, round(a['pe'][d], 4), round(last_eps, 4)))
        out[sym] = {
            'series': series,
            'px': sorted((d, v) for d, v in a['px'].items() if d >= start),
        }
    return out
