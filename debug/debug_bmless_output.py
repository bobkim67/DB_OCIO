"""BM 미설정 펀드의 자산군별 + 종목별 수익률 출력 확인."""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import compute_single_port_pa, compute_brinson_attribution_v2

pd.set_option('display.max_rows', 100)
pd.set_option('display.width', 200)
pd.set_option('display.float_format', lambda x: f'{x:.6f}')

FUND = '08N81'
START = '20260101'
END = '20260416'

print(f"{'='*100}\n=== {FUND} BM 미설정 펀드: {START} ~ {END} ===\n{'='*100}")

# Single PA
sp = compute_single_port_pa(FUND, START, END, fx_split=True, mapping_method='방법3')
print(f"\n## 자산군별 요약 (asset_summary) — 개별수익률=Normalized, 기여수익률=path-weighted")
print(sp['asset_summary'].to_string(index=False))

print(f"\n## 종목별 요약 (sec_summary) — 개별수익률=Normalized, 기여수익률=path-weighted")
cols = [c for c in ['종목코드','종목명','자산군','기준일자','개별수익률','기여수익률','순자산비중_시작','순자산비중_끝','순비중변화']
        if c in sp['sec_summary'].columns]
sec_sorted = sp['sec_summary'][cols].sort_values(['자산군','기여수익률'], ascending=[True, False])
print(sec_sorted.to_string(index=False))

# 종목 기여 합계 vs 자산군 기여 비교
print(f"\n## 자산군별 기여수익률 검증 (종목 합계 vs asset_summary)")
check = sp['sec_summary'].groupby('자산군')['기여수익률'].sum().reset_index()
check.columns = ['자산군','종목합']
as_sum = sp['asset_summary'][['자산군','기여수익률']].rename(columns={'기여수익률':'asset_val'})
check = check.merge(as_sum, on='자산군', how='outer')
check['diff_bp'] = (check['종목합'] - check['asset_val']) * 10000
print(check.to_string(index=False))

# Brinson v2 호출 — BM 없으면 비어있어야
print(f"\n## compute_brinson_attribution_v2 (BM 없으므로 factor=0, Cross만 잡힘 예상)")
br = compute_brinson_attribution_v2(FUND, START, END)
print(br['pa_df'][['자산군','AP비중','BM비중','AP수익률','BM수익률','Allocation','Selection','Cross','기여수익률']].to_string(index=False))
print(f"  AP={br['period_ap_return']:.4f}%  BM={br['period_bm_return']:.4f}%  초과={br['total_excess']:.4f}%")
