"""
07G04 Brinson v2 일별 중간값 dump + R Excel 대조.

R Excel 시트:
- Brinson_수익률비교_plot: 일별 자산군별 AP/BM Normalized 수익률
- Brinson_비중비교_plot: 일별 자산군별 AP/BM 비중
- Brinson_초과성과_요인별_plot: 일별 초과수익률 / Cross / Alloc / Select
- Brinson_초과성과_자산군별_plot: 일별 자산군별 총손익기여도 누적
"""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import (
    compute_single_port_pa, _load_bm_daily_returns_by_class
)
from config.funds import FUND_BM
from datetime import timedelta

FUND = '07G04'
START = '20260101'
END   = '20260420'
R_XLSX = 'C:/Users/user/Downloads/PA_compare_07G04_vs_07G04_BM(2026-01-01 ~ 2026-04-20)_방법3_FXsplit=TRUE.xlsx'

# ============ 1) Python v2 내부 재현 (dump용) ============
asset_classes = ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성및기타']
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
    if ac not in ap_ret_daily.columns:
        ap_ret_daily[ac] = 0.0
    if ac not in ap_wgt_daily.columns:
        ap_wgt_daily[ac] = 0.0

# BM
bm_info = FUND_BM.get(FUND)
_BM_ASSET_CLASSES = ['국내주식', '해외주식', '국내채권', '해외채권', 'FX', '유동성']
_sd_dt = pd.Timestamp(f"{START[:4]}-{START[4:6]}-{START[6:8]}")
_bm_warmup_start = (_sd_dt - timedelta(days=45)).strftime('%Y%m%d')
bm_weights_raw, bm_daily_df, _ = _load_bm_daily_returns_by_class(
    bm_info, _bm_warmup_start, END, _BM_ASSET_CLASSES)

bm_weights = {}
for ac in _BM_ASSET_CLASSES:
    target = '유동성및기타' if ac == '유동성' else ac
    bm_weights[target] = bm_weights_raw.get(ac, 0)

if '기준일자' in bm_daily_df.columns:
    bm_daily_df = bm_daily_df.set_index('기준일자')
if '유동성' in bm_daily_df.columns:
    bm_daily_df = bm_daily_df.rename(columns={'유동성': '유동성및기타'})
bm_daily_df = bm_daily_df.reindex(dates_idx).fillna(0)

# BM composite
bm_composite_daily = pd.Series(0.0, index=dates_idx)
for ac in asset_classes:
    w = bm_weights.get(ac, 0) / 100
    if ac in bm_daily_df.columns:
        bm_composite_daily += bm_daily_df[ac] * w

# 보정인자1
ap_cum = (1 + port_daily).cumprod()
bm_cum = (1 + bm_composite_daily).cumprod()
relative_cum_excess = ap_cum / bm_cum - 1
prev_rel = relative_cum_excess.shift(1).fillna(0)
relative_excess_daily = (1 + relative_cum_excess) / (1 + prev_rel) - 1
daily_return_diff = port_daily - bm_composite_daily

correction = pd.Series(0.0, index=dates_idx)
nz = daily_return_diff.abs() > 1e-15
correction[nz] = relative_excess_daily[nz] / daily_return_diff[nz]

# Brinson raw (보정 전)
_BRINSON_CLASSES = [ac for ac in asset_classes if ac != '유동성및기타']
brinson_raw = {ac: {'alloc': pd.Series(0.0, index=dates_idx),
                    'select': pd.Series(0.0, index=dates_idx),
                    'cross': pd.Series(0.0, index=dates_idx)} for ac in _BRINSON_CLASSES}
for ac in _BRINSON_CLASSES:
    ap_w = ap_wgt_daily[ac]
    ap_r = ap_ret_daily[ac]
    bm_w = bm_weights.get(ac, 0) / 100
    bm_r = bm_daily_df[ac] if ac in bm_daily_df.columns else pd.Series(0.0, index=dates_idx)
    brinson_raw[ac]['cross']  = (ap_w - bm_w) * (ap_r - bm_r)
    brinson_raw[ac]['alloc']  = (ap_w - bm_w) * bm_r
    brinson_raw[ac]['select'] = bm_w * (ap_r - bm_r)

daily_brinson_sum = pd.Series(0.0, index=dates_idx)
for ac in _BRINSON_CLASSES:
    daily_brinson_sum += brinson_raw[ac]['alloc'] + brinson_raw[ac]['select'] + brinson_raw[ac]['cross']
liquidity_daily_raw = daily_return_diff - daily_brinson_sum

# 보정인자1 적용 (raw → corrected)
brinson_corr = {ac: {k: v * correction for k, v in brinson_raw[ac].items()} for ac in _BRINSON_CLASSES}
liquidity_corr = liquidity_daily_raw * correction

# ============ 2) 일별 요약 테이블 (Py) ============
summary_rows = []
for dt_ in dates_idx:
    row = {'기준일자': dt_.strftime('%Y-%m-%d')}
    row['ap_daily'] = port_daily.loc[dt_]
    row['bm_daily'] = bm_composite_daily.loc[dt_]
    row['daily_return_diff'] = daily_return_diff.loc[dt_]
    row['relative_excess_daily'] = relative_excess_daily.loc[dt_]
    row['correction'] = correction.loc[dt_]
    for ac in _BRINSON_CLASSES:
        row[f'ap_w_{ac}'] = ap_wgt_daily[ac].loc[dt_]
        row[f'bm_w_{ac}'] = bm_weights.get(ac, 0) / 100
        row[f'ap_r_{ac}'] = ap_ret_daily[ac].loc[dt_]
        row[f'bm_r_{ac}'] = bm_daily_df[ac].loc[dt_] if ac in bm_daily_df.columns else 0
        row[f'cross_raw_{ac}']  = brinson_raw[ac]['cross'].loc[dt_]
        row[f'alloc_raw_{ac}']  = brinson_raw[ac]['alloc'].loc[dt_]
        row[f'select_raw_{ac}'] = brinson_raw[ac]['select'].loc[dt_]
        row[f'cross_corr_{ac}']  = brinson_corr[ac]['cross'].loc[dt_]
        row[f'alloc_corr_{ac}']  = brinson_corr[ac]['alloc'].loc[dt_]
        row[f'select_corr_{ac}'] = brinson_corr[ac]['select'].loc[dt_]
    row['liq_raw']  = liquidity_daily_raw.loc[dt_]
    row['liq_corr'] = liquidity_corr.loc[dt_]
    summary_rows.append(row)
py_daily = pd.DataFrame(summary_rows)
py_daily.to_csv('debug/debug_07g04_py_daily.csv', index=False, encoding='utf-8-sig')
print(f'✓ Py daily dump: debug/debug_07g04_py_daily.csv  ({len(py_daily)}행)')

# ============ 3) R 일별 데이터 로드 ============
r_ret = pd.read_excel(R_XLSX, sheet_name='Brinson_수익률비교_plot')
r_wgt = pd.read_excel(R_XLSX, sheet_name='Brinson_비중비교_plot')
r_factor = pd.read_excel(R_XLSX, sheet_name='Brinson_초과성과_요인별_plot')
r_by_ac = pd.read_excel(R_XLSX, sheet_name='Brinson_초과성과_자산군별_plot')

# ============ 4) 일별 비교: 2026-01-02 기준 ============
test_dates = ['2026-01-02', '2026-01-05', '2026-01-30', '2026-02-27', '2026-03-31', '2026-04-20']
print('\n=== 일별 비교 (주요 날짜) ===')
for td_str in test_dates:
    td = pd.Timestamp(td_str)
    print(f'\n-- {td_str} --')
    # R factor
    rf = r_factor[r_factor['기준일자'] == td]
    if not rf.empty:
        r = rf.iloc[0]
        py_row = py_daily[py_daily['기준일자'] == td_str]
        if not py_row.empty:
            py_r = py_row.iloc[0]
            print(f'  [daily_return_diff]    R={r["초과수익률"]:.6e}   Py={py_r["daily_return_diff"]:.6e}')
            # R Cross/Alloc/Select는 aggregated (아마 다음 수식:  sum across asset_classes)
            py_cross_sum = sum(py_r[f'cross_raw_{ac}'] for ac in _BRINSON_CLASSES)
            py_alloc_sum = sum(py_r[f'alloc_raw_{ac}'] for ac in _BRINSON_CLASSES)
            py_select_sum = sum(py_r[f'select_raw_{ac}'] for ac in _BRINSON_CLASSES)
            print(f'  [Cross sum raw]        R={r["Cross_effect"]:.6e}   Py_raw={py_cross_sum:.6e}')
            print(f'  [Alloc sum raw]        R={r["Allocation_effect"]:.6e}   Py_raw={py_alloc_sum:.6e}')
            print(f'  [Select sum raw]       R={r["Security_selction_effect"]:.6e}   Py_raw={py_select_sum:.6e}')

# ============ 5) 자산군별 수익률 대조 (2026-01-02) ============
print('\n=== 자산군별 수익률 대조 (2026-01-02) ===')
td = pd.Timestamp('2026-01-02')
r_row = r_ret[(r_ret['기준일자'] == td) & (r_ret['설명'] == 'Normalized 수익률')]
py_row = py_daily[py_daily['기준일자'] == '2026-01-02'].iloc[0] if not py_daily[py_daily['기준일자'] == '2026-01-02'].empty else None
if py_row is not None:
    for ac in _BRINSON_CLASSES:
        r_ap = r_row[r_row['자산군'] == ac]['07G04'].values
        r_bm = r_row[r_row['자산군'] == ac]['07G04_BM'].values
        r_ap = r_ap[0] if len(r_ap) > 0 else 0
        r_bm = r_bm[0] if len(r_bm) > 0 else 0
        print(f'  {ac:8s}: R_AP={r_ap:.6e}  Py_AP={py_row[f"ap_r_{ac}"]:.6e}  | R_BM={r_bm:.6e}  Py_BM={py_row[f"bm_r_{ac}"]:.6e}')

# ============ 6) 자산군별 비중 대조 (2026-01-02) ============
print('\n=== 자산군별 비중 대조 (2026-01-02) ===')
r_row = r_wgt[(r_wgt['기준일자'] == td) & (r_wgt['설명'] == '평가자산 비중')]
if py_row is not None:
    for ac in _BRINSON_CLASSES:
        r_ap = r_row[r_row['자산군'] == ac]['07G04'].values
        r_bm = r_row[r_row['자산군'] == ac]['07G04_BM'].values
        r_ap = r_ap[0] if len(r_ap) > 0 else 0
        r_bm = r_bm[0] if len(r_bm) > 0 else 0
        print(f'  {ac:8s}: R_AP={r_ap:.6e}  Py_AP={py_row[f"ap_w_{ac}"]:.6e}  | R_BM={r_bm:.6e}  Py_BM={py_row[f"bm_w_{ac}"]:.6e}')
