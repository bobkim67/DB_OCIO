"""08N81 Python vs R 대조. 설정일 2026-01-08 ~ 2026-04-20."""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import compute_single_port_pa

pd.set_option('display.max_rows', 120)
pd.set_option('display.width', 220)
pd.set_option('display.float_format', lambda x: f'{x:.6f}')

FUND = '08N81'
START = '20260108'
END = '20260420'

print(f"{'='*100}\n=== {FUND} Python: {START} ~ {END} (설정일 기준) ===\n{'='*100}")

sp = compute_single_port_pa(FUND, START, END, fx_split=True, mapping_method='방법3')

print(f"\n## 자산군별 요약 (Python asset_summary)")
print(sp['asset_summary'].to_string(index=False))

print(f"\n## 종목별 요약 (Python sec_summary)")
cols = [c for c in ['종목코드','종목명','자산군','기준일자','분석시작일','분석종료일','개별수익률','기여수익률','순자산비중_시작','순자산비중_끝','순비중변화']
        if c in sp['sec_summary'].columns]
sec = sp['sec_summary'][cols].sort_values(['자산군','기여수익률'], ascending=[True, False])
print(sec.to_string(index=False))

# R 데이터 로드
fp = 'C:/Users/user/Downloads/PA_single_한국투자OCIO알아서액티브일반사모투자신탁_(2026-01-08 ~ 2026-04-20)_방법3_FXsplit=TRUE.xlsx'
r_asset = pd.read_excel(fp, sheet_name='AP_한국투자OCIO알아서액티브일반사모투자신탁_자산')
r_sec = pd.read_excel(fp, sheet_name='AP_한국투자OCIO알아서액티브일반사모투자신탁_se')

# 자산군 비교
py_a = sp['asset_summary'][['자산군','개별수익률','기여수익률','순자산비중']].copy()
py_a.columns = ['자산군','py_개별','py_기여','py_비중']
r_a = r_asset[['자산군','개별수익률','기여수익률','순자산비중_종료']].copy()
r_a.columns = ['자산군','r_개별','r_기여','r_비중']
cmp_a = r_a.merge(py_a, on='자산군', how='outer')
cmp_a['개별_diff_bp'] = (cmp_a['py_개별'] - cmp_a['r_개별'])*10000
cmp_a['기여_diff_bp'] = (cmp_a['py_기여'] - cmp_a['r_기여'])*10000
cmp_a['비중_diff_bp'] = (cmp_a['py_비중'] - cmp_a['r_비중'])*10000
print(f"\n{'='*100}\n## 자산군별 대조 (Py vs R, diff bp)\n{'='*100}")
print(cmp_a.to_string(index=False))

# 종목 비교
py_s = sp['sec_summary'][['종목코드','개별수익률','기여수익률','순자산비중_끝']].copy()
py_s.columns = ['종목코드','py_개별','py_기여','py_비중끝']
r_s = r_sec[['종목코드','종목명','자산군','개별수익률','기여수익률','순자산비중_종료']].copy()
r_s.columns = ['종목코드','종목명','자산군','r_개별','r_기여','r_비중끝']
cmp_s = r_s.merge(py_s, on='종목코드', how='outer')
cmp_s['개별_diff_bp'] = (cmp_s['py_개별'] - cmp_s['r_개별'])*10000
cmp_s['기여_diff_bp'] = (cmp_s['py_기여'] - cmp_s['r_기여'])*10000
cmp_s['비중_diff_bp'] = (cmp_s['py_비중끝'] - cmp_s['r_비중끝'])*10000
print(f"\n{'='*100}\n## 종목별 대조 (Py vs R, diff bp)\n{'='*100}")
print(cmp_s.to_string(index=False))
