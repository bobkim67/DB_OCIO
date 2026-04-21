"""
compute_brinson_attribution_v2 다중 펀드 regression/sanity check.
- 08K88 (수정 검증 완료 → regression)
- 08N81, 07G04 (타 펀드)
- 07G02, 2JM23 (소규모 펀드 sanity)

출력: 포트 AP/BM/초과 + 자산군별 Alloc/Select/Cross 합산 검증.
"""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import compute_brinson_attribution_v2

FUNDS = ['08K88', '08N81', '07G04', '07G02', '2JM23']
START = '20260101'
END   = '20260416'

print("="*100)
print(f"Brinson v2 회귀: {START} ~ {END}")
print("="*100)

summary_rows = []
for f in FUNDS:
    try:
        r = compute_brinson_attribution_v2(f, START, END)
        if r is None:
            print(f"\n[{f}] None 반환")
            continue
        ap = r.get('period_ap_return', 0)
        bm = r.get('period_bm_return', 0)
        excess = r.get('total_excess', 0)
        alloc = r.get('total_alloc', 0)
        select = r.get('total_select', 0)
        cross = r.get('total_cross', 0)
        residual = r.get('residual', 0)
        pa_df = r.get('pa_df')

        # Sanity: alloc+select+cross+residual ≈ excess?
        sum_factors = alloc + select + cross + residual
        diff = abs(excess - sum_factors)

        print(f"\n[{f}] AP={ap*100:.4f}%  BM={bm*100:.4f}%  초과={excess*100:.4f}%")
        print(f"     Alloc={alloc*100:.4f}%  Select={select*100:.4f}%  Cross={cross*100:.4f}%  Residual={residual*100:.4f}%")
        print(f"     합(A+S+C+R)={sum_factors*100:.4f}%  vs 초과: diff={diff*1e4:.4f}bp")

        if pa_df is not None and '자산군' in pa_df.columns:
            print(f"     자산군 테이블:")
            print(pa_df.to_string(index=False).replace('\n', '\n     '))

        summary_rows.append({
            'fund': f,
            'AP': ap*100, 'BM': bm*100, '초과': excess*100,
            'Alloc': alloc*100, 'Select': select*100, 'Cross': cross*100,
            'Residual': residual*100, 'sum_diff_bp': diff*1e4,
        })
    except Exception as e:
        print(f"\n[{f}] EXCEPTION: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()

print("\n" + "="*100)
print("SUMMARY")
print("="*100)
if summary_rows:
    print(pd.DataFrame(summary_rows).to_string(index=False))
