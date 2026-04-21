"""compute_single_port_pa 내부 sec_agg 직접 재현 — 1/7 KR70127M0006."""
import sys
import pandas as pd
import numpy as np
sys.path.insert(0, '.')

from modules.data_loader import (
    load_pa_source, _load_daily_nast, _load_net_subscription_pa,
    _get_관련_fund_list, _get_class_mother_fund,
    _load_holdings_for_pa, _load_etf_redemption_adjustment,
)

FUND = '07G04'
class_m = _get_class_mother_fund(FUND)
related = _get_관련_fund_list(class_m)

pa_raw = load_pa_source(class_m, '20260101', '20260131')
nast = _load_daily_nast(class_m, '20260101', '20260131')
net_sub = nast[['기준일자']].copy()  # placeholder

# Target: 1/7 KR70127M0006
td = pd.Timestamp('2026-01-07')
pa_t = pa_raw[(pa_raw['기준일자'] == td) & (pa_raw['sec_id'] == 'KR70127M0006')].copy()
pa_t['pr_date'] = pa_t['pr_date'].astype(int)
print(f'=== pa_raw (MA410) 1/7 KR70127M0006 ===')
print(pa_t[['pr_date', 'sec_id', 'pl_gb', 'position_gb', 'amt', 'val', 'std_val']].to_string(index=False))

holdings = _load_holdings_for_pa(related, '20260105', '20260110')
h_t = holdings[(holdings['기준일자'] == td) & (holdings['ITEM_CD'] == 'KR70127M0006')]
print(f'\n=== holdings 1/7 KR70127M0006 (FoF agg 후) ===')
print(h_t[['기준일자', 'FUND_CD', 'ITEM_CD', 'POS_DS_CD', 'EVL_AMT', 'PDD_QTY', 'BUY_QTY', 'SELL_QTY']].to_string(index=False))

# NAST/순자산 T-1
n_t = nast[nast['기준일자'].isin([pd.Timestamp('2026-01-06'), pd.Timestamp('2026-01-07')])]
print(f'\n=== nast 1/6 1/7 ===')
print(n_t[['기준일자', 'NAST_AMT', 'MOD_STPR', 'DD1_ERN_RT']].to_string(index=False))

# 순설정
net_sub_real = _load_net_subscription_pa(class_m, '20260101', '20260131')
ns_t = net_sub_real[net_sub_real['기준일자'] == td]
print(f'\n=== 순설정 1/7 ===')
print(ns_t.to_string(index=False))

# 수동 계산 (예상)
print(f'\n=== 수동 계산 (예상) ===')
print(f'시가 = max(val) = 8.538B')
print(f'총손익 = sum(amt) = 63.08M')
print(f'PDD=655300, BUY=150000 → else 분기')
print(f'평가시가 = max(std_val) = 8.450B')
print(f'순설정액 = 8.538 - (0.063 + 8.450) = 0.025B (양수)')
print(f'position=LONG, 순설정액>0 → 조정_평가시가 = 시가 - 총손익 = 8.475B')
nast_t1 = n_t[n_t['기준일자'] == pd.Timestamp('2026-01-06')]['NAST_AMT'].iloc[0]
ns_amt = ns_t['순설정금액'].iloc[0] if not ns_t.empty else 0
denom = nast_t1 + ns_amt
print(f'분모 = NAST(T-1) + 순설정 = {nast_t1:.4e} + {ns_amt:.4e} = {denom:.4e}')
print(f'weight_PA 예상 = 8.475B / {denom/1e9:.2f}B = {8.475e9/denom*100:.2f}%')

# full compute_single_port_pa 후 weight_PA 확인
from modules.data_loader import compute_single_port_pa
sp = compute_single_port_pa('07G04', '20260101', '20260131', fx_split=True, mapping_method='방법3')
sec_daily = sp['sec_daily']
print(f'\n=== compute_single_port_pa sec_daily 1/7 해외주식 ===')
sub = sec_daily[(sec_daily['기준일자'] == td) & (sec_daily['자산군'] == '해외주식')]
print(sub[['기준일자', '종목코드', '종목명', '개별수익률', '기여수익률']].to_string(index=False))

# asset_daily 1/7 해외주식 weight_PA
asset_daily = sp['asset_daily']
ac_t = asset_daily[(asset_daily['기준일자'] == td) & (asset_daily['자산군'] == '해외주식')]
print(f'\n=== asset_daily 1/7 해외주식 ===')
print(ac_t.to_string(index=False))
