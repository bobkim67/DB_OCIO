"""
07G04 Py 누적 Brinson vs R 요인별_plot 일별 대조.

R Excel 요인별_plot은 누적 보정_총손익기여도 = cumsum(effect × correction × path_weight) × 단순차누적/상대누적.
"""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import compute_single_port_pa, _load_bm_daily_returns_by_class
from config.funds import FUND_BM
from datetime import timedelta

FUND = '07G04'
START = '20260101'
END   = '20260420'
R_XLSX = 'C:/Users/user/Downloads/PA_compare_07G04_vs_07G04_BM(2026-01-01 ~ 2026-04-20)_방법3_FXsplit=TRUE.xlsx'

asset_classes = ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성및기타']
_BRINSON_CLASSES = [ac for ac in asset_classes if ac != '유동성및기타']

single_pa = compute_single_port_pa(FUND, START, END, fx_split=True, mapping_method='방법3')
asset_daily = single_pa['asset_daily']
port_daily = single_pa['port_daily_returns']
dates_idx = pd.DatetimeIndex(sorted(port_daily.index.unique()))
port_daily = port_daily.reindex(dates_idx).fillna(0)

ap_ret_daily = asset_daily.pivot(index='기준일자', columns='자산군',
                                  values='자산군수익률_daily').reindex(dates_idx).fillna(0)
ap_wgt_daily = asset_daily.pivot(index='기준일자', columns='자산군',
                                  values='weight_PA').reindex(dates_idx).fillna(0)
for ac in asset_classes:
    if ac not in ap_ret_daily.columns: ap_ret_daily[ac] = 0.0
    if ac not in ap_wgt_daily.columns: ap_wgt_daily[ac] = 0.0

bm_info = FUND_BM.get(FUND)
_BM_ASSET_CLASSES = ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성']
_sd_dt = pd.Timestamp(f"{START[:4]}-{START[4:6]}-{START[6:8]}")
_bm_warmup_start = (_sd_dt - timedelta(days=45)).strftime('%Y%m%d')
bm_weights_raw, bm_daily_df, _ = _load_bm_daily_returns_by_class(
    bm_info, _bm_warmup_start, END, _BM_ASSET_CLASSES)
bm_weights = {('유동성및기타' if ac == '유동성' else ac): bm_weights_raw.get(ac, 0) for ac in _BM_ASSET_CLASSES}
if '기준일자' in bm_daily_df.columns:
    bm_daily_df = bm_daily_df.set_index('기준일자')
if '유동성' in bm_daily_df.columns:
    bm_daily_df = bm_daily_df.rename(columns={'유동성': '유동성및기타'})
bm_daily_df = bm_daily_df.reindex(dates_idx).fillna(0)

bm_composite_daily = pd.Series(0.0, index=dates_idx)
for ac in asset_classes:
    w = bm_weights.get(ac, 0) / 100
    if ac in bm_daily_df.columns:
        bm_composite_daily += bm_daily_df[ac] * w

ap_cum = (1 + port_daily).cumprod()
bm_cum = (1 + bm_composite_daily).cumprod()
relative_cum_excess = ap_cum / bm_cum - 1
prev_rel = relative_cum_excess.shift(1).fillna(0)
relative_excess_daily = (1 + relative_cum_excess) / (1 + prev_rel) - 1
daily_return_diff = port_daily - bm_composite_daily
excess_cum_simple = (ap_cum - 1) - (bm_cum - 1)   # 단순차누적

correction = pd.Series(0.0, index=dates_idx)
nz = daily_return_diff.abs() > 1e-15
correction[nz] = relative_excess_daily[nz] / daily_return_diff[nz]

path_weight = 1 + prev_rel

# 일별 Brinson raw (보정 전)
brinson_raw = {}
for ac in _BRINSON_CLASSES:
    ap_w = ap_wgt_daily[ac]; ap_r = ap_ret_daily[ac]
    bm_w = bm_weights.get(ac, 0) / 100
    bm_r = bm_daily_df[ac] if ac in bm_daily_df.columns else pd.Series(0.0, index=dates_idx)
    brinson_raw[ac] = {
        'alloc':  (ap_w - bm_w) * bm_r,
        'select': bm_w * (ap_r - bm_r),
        'cross':  (ap_w - bm_w) * (ap_r - bm_r),
    }

daily_brinson_sum = pd.Series(0.0, index=dates_idx)
for ac in _BRINSON_CLASSES:
    for k in ['alloc', 'select', 'cross']:
        daily_brinson_sum += brinson_raw[ac][k]
liquidity_raw = daily_return_diff - daily_brinson_sum

# 보정 + path_weight 누적 (R 공식)
# 보정_총손익기여도(T) = cumsum(effect × correction × path_weight) × 단순차_T / 상대_T
def corr_cum_series(eff_daily):
    cum = (eff_daily * correction * path_weight).cumsum()
    scaler = excess_cum_simple / relative_cum_excess.replace(0, np.nan)
    scaler = scaler.fillna(1.0)
    return cum * scaler

alloc_cum_sum = pd.Series(0.0, index=dates_idx)
select_cum_sum = pd.Series(0.0, index=dates_idx)
cross_cum_sum = pd.Series(0.0, index=dates_idx)
for ac in _BRINSON_CLASSES:
    alloc_cum_sum  += corr_cum_series(brinson_raw[ac]['alloc'])
    select_cum_sum += corr_cum_series(brinson_raw[ac]['select'])
    cross_cum_sum  += corr_cum_series(brinson_raw[ac]['cross'])
liq_cum = corr_cum_series(liquidity_raw)

# R 요인별_plot: Cross_effect에 유동성(NA name)이 포함된 듯
cross_cum_with_liq = cross_cum_sum + liq_cum
total_cum = alloc_cum_sum + select_cum_sum + cross_cum_sum + liq_cum  # = excess_cum_simple(기간말)

py_factor_df = pd.DataFrame({
    '기준일자': dates_idx,
    '초과수익률': excess_cum_simple.values,
    'Cross_effect': cross_cum_with_liq.values,
    'Allocation_effect': alloc_cum_sum.values,
    'Security_selction_effect': select_cum_sum.values,
    'liq_only_cum': liq_cum.values,
    'cross_only_cum': cross_cum_sum.values,
})

# R 로드
r_factor = pd.read_excel(R_XLSX, sheet_name='Brinson_초과성과_요인별_plot')
r_factor['기준일자'] = pd.to_datetime(r_factor['기준일자'])

merged = pd.merge(py_factor_df, r_factor, on='기준일자', how='inner', suffixes=('_py', '_r'))

print('=== Py 누적 vs R 요인별_plot (일별) ===')
print(f'{"Date":12s} | {"dret_R":>10s} {"dret_Py":>10s} | {"Cross_R":>10s} {"Cross_Py":>10s} {"Cross_Py_no_liq":>12s} | {"Alloc_R":>10s} {"Alloc_Py":>10s} | {"Sel_R":>10s} {"Sel_Py":>10s}')
for _, row in merged.iterrows():
    dt = row['기준일자'].strftime('%Y-%m-%d')
    print(f'{dt} | {row["초과수익률_r"]*100:>9.4f}% {row["초과수익률_py"]*100:>9.4f}% | {row["Cross_effect_r"]*100:>9.4f}% {row["Cross_effect_py"]*100:>9.4f}% {row["cross_only_cum"]*100:>11.4f}% | {row["Allocation_effect_r"]*100:>9.4f}% {row["Allocation_effect_py"]*100:>9.4f}% | {row["Security_selction_effect_r"]*100:>9.4f}% {row["Security_selction_effect_py"]*100:>9.4f}%')
    # 초기 divergence 찾기
    if abs(row["Cross_effect_r"] - row["Cross_effect_py"]) > 1e-5:
        pass

# 발산 시점 찾기
print('\n=== 발산 시점 (Cross diff > 0.001%) ===')
for _, row in merged.iterrows():
    diff = row["Cross_effect_r"] - row["Cross_effect_py"]
    if abs(diff) > 1e-5:
        print(f'{row["기준일자"].strftime("%Y-%m-%d")}: Cross R-Py = {diff*100:.6f}%')
        break
