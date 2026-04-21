"""2026-01-07 종목 레벨 대조."""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import compute_single_port_pa, _load_holdings_for_pa, _get_관련_fund_list, _get_class_mother_fund

FUND = '07G04'
START = '20260101'
END   = '20260420'

# Py sec_daily
single_pa = compute_single_port_pa(FUND, START, END, fx_split=True, mapping_method='방법3')
sec_daily = single_pa.get('sec_daily')
if sec_daily is not None and not sec_daily.empty:
    for date_str in ['2026-01-06', '2026-01-07']:
        td = pd.Timestamp(date_str)
        rows = sec_daily[sec_daily['기준일자'] == td]
        print(f'\n=== Py sec_daily {date_str} (shape={rows.shape}) ===')
        print(rows[['기준일자', '자산군', '종목코드', '종목명', '개별수익률', '기여수익률']].to_string(index=False))

# Py raw holdings (pulling_모자구조 확장 후)
cmf = _get_class_mother_fund(FUND)
related = _get_관련_fund_list(cmf)
print(f'\n07G04 관련 펀드: {related}')

for date_str in ['20260106', '20260107']:
    holdings = _load_holdings_for_pa(related, date_str, date_str)
    holdings = holdings[holdings['EVL_AMT'] != 0]
    print(f'\n=== Py raw holdings {date_str} (shape={holdings.shape}) ===')
    # 자산군 분류 없이 sec만 확인
    print(holdings[['기준일자', 'FUND_CD', 'ITEM_CD', 'ITEM_NM', 'POS_DS_CD', 'EVL_AMT', 'PDD_QTY', 'BUY_QTY', 'SELL_QTY']].to_string(index=False))
