"""08N81 ACE 종합채권 Python vs R Excel 일별 개별수익률 divergence 지점 찾기."""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import compute_single_port_pa

pd.set_option('display.max_rows', 200)
pd.set_option('display.width', 200)
pd.set_option('display.float_format', lambda x: f'{x:.8f}')

# R Excel 로드
fp = 'C:/Users/user/Downloads/PA_single_한국투자OCIO알아서액티브일반사모투자신탁_(2026-01-08 ~ 2026-04-20)_방법3_FXsplit=TRUE.xlsx'
r = pd.read_excel(fp, sheet_name='AP_한국투자OCIO알아서액티브일반사모투자신탁_se_1')
r = r[r['종목코드']=='KR7356540005'].sort_values('기준일자').copy()
r = r[['기준일자','개별수익률','기여수익률','순자산비중_시작','순자산비중_종료']].rename(columns={
    '개별수익률':'r_개별','기여수익률':'r_기여','순자산비중_시작':'r_비중시작','순자산비중_종료':'r_비중종료'})
r['기준일자'] = pd.to_datetime(r['기준일자'])

# Python 결과
sp = compute_single_port_pa('08N81', '20260108', '20260420', fx_split=True, mapping_method='방법3')
py = sp['sec_daily'][sp['sec_daily']['종목코드']=='KR7356540005'].sort_values('기준일자').copy()
py = py[['기준일자','개별수익률','기여수익률','순자산비중_시작','순자산비중_끝']].rename(columns={
    '개별수익률':'py_개별','기여수익률':'py_기여','순자산비중_시작':'py_비중시작','순자산비중_끝':'py_비중종료'})
py['기준일자'] = pd.to_datetime(py['기준일자'])

cmp = r.merge(py, on='기준일자', how='outer').sort_values('기준일자')
cmp['개별_diff'] = cmp['py_개별'] - cmp['r_개별']
cmp['기여_diff'] = cmp['py_기여'] - cmp['r_기여']
cmp['비중_diff'] = cmp['py_비중종료'] - cmp['r_비중종료']

print(f"{'='*100}")
print("08N81 ACE 종합채권(AA-이상) 일별 R vs Py")
print(f"{'='*100}\n")
# 전체 표
print(cmp.to_string(index=False))

# divergence 시작 지점
print(f"\n{'='*100}\n## 개별수익률 divergence (|diff| > 1e-4) 첫 시작점")
big = cmp[cmp['개별_diff'].abs() > 1e-4]
if not big.empty:
    print(f"첫 divergence 날짜: {big['기준일자'].iloc[0].date()}")
    print(big.head(5).to_string(index=False))

print(f"\n## 비중 divergence (|diff| > 1e-5) 첫 시작점")
bigw = cmp[cmp['비중_diff'].abs() > 1e-5]
if not bigw.empty:
    print(f"첫 divergence 날짜: {bigw['기준일자'].iloc[0].date()}")
    print(bigw.head(5).to_string(index=False))
