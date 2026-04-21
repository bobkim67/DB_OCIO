"""
compute_brinson_attribution_v2 호출 → 08K88 Brinson 3-Factor 출력.
R Excel 목표 (handoff):
  국내채권 Alloc=0.0191%, Select=0.0291%, Cross=-0.0078%, 합=0.0404%
"""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import compute_brinson_attribution_v2

print("=== Brinson v2: 08K88 (2026-01-01 ~ 2026-04-16) ===")
res = compute_brinson_attribution_v2('08K88', '20260101', '20260416')
if res is None:
    print("[ERR] None 반환")
    sys.exit(1)

print("\nres keys:", list(res.keys()))

# 전체 결과 스칼라
for k in ('total_alloc', 'total_select', 'total_cross', 'total_excess', 'total_excess_relative',
          'period_ap_return', 'period_bm_return', 'residual'):
    if k in res:
        print(f"  {k}: {res[k]*100:.4f}%" if res[k] is not None else f"  {k}: None")

# pa_df = 자산군별 3-Factor 테이블
pa_df = res.get('pa_df')
if pa_df is not None and hasattr(pa_df, 'columns'):
    print("\n--- pa_df (자산군별 3-Factor) ---")
    print(pa_df.to_string(index=False))
    # 국내채권 상세
    if '자산군' in pa_df.columns:
        kr = pa_df[pa_df['자산군'] == '국내채권']
        print("\n=== 국내채권 vs R Excel ===")
        print(kr.to_string(index=False))
