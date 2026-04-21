"""2026-01-07 KR70127M0006 Py sec_agg 내부 값 추적."""
import sys
import pandas as pd
sys.path.insert(0, '.')

# compute_single_port_pa 내부 재현 (핵심 부분만)
from modules.data_loader import (
    load_pa_source, _load_daily_nast, _load_net_subscription_pa,
    _get_관련_fund_list, _get_class_mother_fund,
    _load_holdings_for_pa, _load_etf_redemption_adjustment,
)

FUND = '07G04'
START = '20260101'
END = '20260131'

class_m = _get_class_mother_fund(FUND)
related = _get_관련_fund_list(class_m)
print(f'class_m={class_m}, related={related}')

# pa_raw (MA410)
pa_raw = load_pa_source(class_m, START, END)
pa_raw_target = pa_raw[(pa_raw['sec_id'] == 'KR70127M0006')]
print(f'\n=== pa_raw (MA410) 07G04 KR70127M0006 (1/5 ~ 1/9) ===')
pa_raw_target = pa_raw_target.copy()
pa_raw_target['pr_date'] = pa_raw_target['pr_date'].astype(int)
mask = (pa_raw_target['pr_date'] >= 20260105) & (pa_raw_target['pr_date'] <= 20260109)
print(pa_raw_target[mask][['pr_date', 'fund_id', 'sec_id', 'asset_gb', 'position_gb', 'pl_gb', 'crrncy_cd', 'os_gb', 'amt', 'val', 'std_val']].to_string(index=False))

# holdings (DWPM10530)
holdings = _load_holdings_for_pa(related, '20260105', '20260110')
print(f'\n=== holdings (DWPM10530 FoF agg) KR70127M0006 ===')
h_t = holdings[holdings['ITEM_CD'] == 'KR70127M0006']
print(h_t[['기준일자', 'FUND_CD', 'ITEM_CD', 'ITEM_NM', 'POS_DS_CD', 'EVL_AMT', 'PDD_QTY', 'BUY_QTY', 'SELL_QTY']].to_string(index=False))

# DB에서 raw DWPM10530 직접 조회 (FoF agg 전)
from modules.data_loader import get_pandas_connection
conn = get_pandas_connection('dt')
placeholders = ','.join(['%s'] * len(related))
sql = f"""
    SELECT STD_DT, FUND_CD, ITEM_CD, ITEM_NM, POS_DS_CD,
           COALESCE(EVL_AMT, 0) AS EVL_AMT,
           COALESCE(PDD_QTY, 0) AS PDD_QTY,
           COALESCE(BUY_QTY, 0) AS BUY_QTY,
           COALESCE(SELL_QTY, 0) AS SELL_QTY
    FROM DWPM10530
    WHERE FUND_CD IN ({placeholders})
      AND STD_DT BETWEEN %s AND %s
      AND ITEM_CD = 'KR70127M0006'
      AND ITEM_NM NOT LIKE '%%미지급%%'
      AND ITEM_NM NOT LIKE '%%미수%%'
    ORDER BY STD_DT, FUND_CD
"""
raw_db = pd.read_sql(sql, conn, params=[*related, '20260105', '20260110'])
conn.close()
print(f'\n=== DWPM10530 raw (FoF agg 전) KR70127M0006 ===')
print(raw_db.to_string(index=False))
