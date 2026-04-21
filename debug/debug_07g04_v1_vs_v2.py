"""07G04 Brinson v1 vs v2 비교 + single_pa 원시 데이터 확인."""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import (
    compute_brinson_attribution, compute_brinson_attribution_v2,
    compute_single_port_pa, _get_class_mother_fund,
)

FUND = '07G04'
START = '20260101'
END   = '20260416'

print(f"=== {FUND} class_m_fund: {_get_class_mother_fund(FUND)} ===\n")

print("--- v1 결과 ---")
r1 = compute_brinson_attribution(FUND, START, END)
if r1 is not None:
    pa1 = r1.get('pa_df')
    print(f"AP={r1.get('period_ap_return',0)*100:.4f}%  BM={r1.get('period_bm_return',0)*100:.4f}%  초과={r1.get('total_excess',0)*100:.4f}%")
    if pa1 is not None:
        print(pa1.to_string(index=False))
else:
    print("v1 None 반환")

print("\n--- v2 결과 ---")
r2 = compute_brinson_attribution_v2(FUND, START, END)
if r2 is not None:
    pa2 = r2.get('pa_df')
    print(f"AP={r2.get('period_ap_return',0)*100:.4f}%  BM={r2.get('period_bm_return',0)*100:.4f}%  초과={r2.get('total_excess',0)*100:.4f}%")
    if pa2 is not None:
        print(pa2.to_string(index=False))

print("\n--- single_pa 원시 데이터 ---")
sp = compute_single_port_pa(FUND, START, END, fx_split=True, mapping_method='방법3')
if sp is not None:
    asset_sum = sp.get('asset_summary')
    if asset_sum is not None:
        print("asset_summary:")
        print(asset_sum.to_string(index=False))
    asset_daily = sp.get('asset_daily')
    if asset_daily is not None and not asset_daily.empty:
        # 자산군별 최초 / 최후 비중
        first_dt = asset_daily['기준일자'].min()
        last_dt = asset_daily['기준일자'].max()
        for ac in asset_daily['자산군'].unique():
            ad = asset_daily[asset_daily['자산군']==ac].sort_values('기준일자')
            wfirst = ad.iloc[0]['순자산비중'] if not ad.empty else None
            wlast  = ad.iloc[-1]['순자산비중'] if not ad.empty else None
            rfirst = ad.iloc[0].get('daily_return', 0)
            print(f"  {ac:10s}: weight_first={wfirst:.4f}  weight_last={wlast:.4f}")
