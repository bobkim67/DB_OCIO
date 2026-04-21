"""2026-01-07 자산군별 일별 대조: Py vs R."""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import compute_single_port_pa
from config.funds import FUND_BM

FUND = '07G04'
START = '20260101'
END   = '20260420'
R_XLSX = 'C:/Users/user/Downloads/PA_compare_07G04_vs_07G04_BM(2026-01-01 ~ 2026-04-20)_방법3_FXsplit=TRUE.xlsx'

single_pa = compute_single_port_pa(FUND, START, END, fx_split=True, mapping_method='방법3')
asset_daily = single_pa['asset_daily']

r_ret = pd.read_excel(R_XLSX, sheet_name='Brinson_수익률비교_plot')
r_wgt = pd.read_excel(R_XLSX, sheet_name='Brinson_비중비교_plot')
r_ret['기준일자'] = pd.to_datetime(r_ret['기준일자'])
r_wgt['기준일자'] = pd.to_datetime(r_wgt['기준일자'])

for date_str in ['2026-01-05', '2026-01-06', '2026-01-07', '2026-01-08']:
    td = pd.Timestamp(date_str)
    print(f'\n{"="*70}\n=== {date_str} 자산군별 대조 ===')
    r_ret_row = r_ret[(r_ret['기준일자'] == td) & (r_ret['설명'] == 'Normalized 수익률')]
    r_wgt_row = r_wgt[(r_wgt['기준일자'] == td) & (r_wgt['설명'] == '평가자산 비중')]
    py_row = asset_daily[asset_daily['기준일자'] == td]

    print(f'\n{"자산군":10s} | {"R_AP_w":>10s} {"Py_AP_w":>10s} {"Δw":>10s} | {"R_AP_r":>10s} {"Py_AP_r":>10s} {"Δr":>10s}')
    for ac in ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성및기타']:
        r_w = r_wgt_row[r_wgt_row['자산군'] == ac]['07G04'].values
        r_r = r_ret_row[r_ret_row['자산군'] == ac]['07G04'].values
        r_w = r_w[0] if len(r_w) > 0 else 0
        r_r = r_r[0] if len(r_r) > 0 else 0
        if pd.isna(r_w) or r_w == float('inf'):
            r_w = 0
        py_ac = py_row[py_row['자산군'] == ac]
        py_w = py_ac['weight_PA'].iloc[0] if not py_ac.empty else 0
        py_r = py_ac['자산군수익률_daily'].iloc[0] if not py_ac.empty else 0
        dw = py_w - r_w
        dr = py_r - r_r
        flag_w = ' ⚠' if abs(dw) > 1e-6 else ''
        flag_r = ' ⚠' if abs(dr) > 1e-6 else ''
        print(f'{ac:10s} | {r_w*100:>9.4f}% {py_w*100:>9.4f}% {dw*100:>9.4f}%{flag_w} | {r_r*100:>9.4f}% {py_r*100:>9.4f}% {dr*100:>9.4f}%{flag_r}')
