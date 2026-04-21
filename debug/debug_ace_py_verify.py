"""
Python compute_single_port_pa 결과에서 ACE KR7365780006 2026-03-05~06 값 검증.
R 프로덕션 historical_performance_information_final 기준:
  03-06 평가시가평가액 = 1,703,187,160
  03-06 조정_평가시가평가액 = 1,703,187,160
  03-06 종목별당일수익률 = 6,901,180 / 1,703,187,160 = 0.004053
"""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import compute_single_port_pa

print("=== compute_single_port_pa 08K88 (2026-01-01 ~ 2026-04-16) ===")
res = compute_single_port_pa('08K88', '20260101', '20260416', fx_split=True)
sec_daily = res.get('sec_daily')
sec_sum = res.get('sec_summary')
asset_sum = res.get('asset_summary')

print("\nsec_daily columns:", list(sec_daily.columns))
print("\nsec_summary columns:", list(sec_sum.columns) if sec_sum is not None else 'none')
print("\nasset_summary columns:", list(asset_sum.columns) if asset_sum is not None else 'none')

# ACE sec_daily
id_col = '종목코드' if '종목코드' in sec_daily.columns else 'sec_id'
ace = sec_daily[sec_daily[id_col] == 'KR7365780006'].sort_values('기준일자').copy()
ace_win = ace[(ace['기준일자'] >= pd.Timestamp('2026-03-01')) & (ace['기준일자'] <= pd.Timestamp('2026-03-10'))]
print("\n=== ACE KR7365780006 2026-03-01~10 (sec_daily) ===")
print(ace_win.to_string(index=False))

# 03-06 단일 row 수익률 추출 (개별수익률)
ace_0306 = ace[ace['기준일자'] == pd.Timestamp('2026-03-06')]
if not ace_0306.empty:
    r = ace_0306.iloc[0]['개별수익률']
    print(f"\nACE 2026-03-06 개별수익률 (Python): {r:.8f}")
    print(f"R Excel 목표                        : 0.00405300")
    print(f"차이                                 : {(r - 0.004053)*1e4:.2f}bp")

# 자산군별 요약
print("\n=== asset_summary (전체) ===")
if asset_sum is not None:
    print(asset_sum.to_string(index=False))

# 저장
ace_win.to_csv('debug/debug_ace_08K88_Py_AFTER_FIX.csv', index=False)
print("\n✓ debug/debug_ace_08K88_Py_AFTER_FIX.csv 저장")
