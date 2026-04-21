"""07G04 FoF: 07G02 + 07G03 holdings 중복 sec_id 확인."""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import _load_holdings_for_pa, _get_관련_fund_list

class_m = '07G04'
related = _get_관련_fund_list(class_m)
print(f"related_funds: {related}")

hp = _load_holdings_for_pa(related, '20260101', '20260416')
print(f"\nshape: {hp.shape}")
print(f"FUND_CD 분포: {hp['FUND_CD'].value_counts().to_dict()}")

# (기준일자, ITEM_CD) 기준 중복 확인
dup = hp.groupby(['기준일자', 'ITEM_CD']).size()
dup_mask = dup > 1
print(f"\n중복 (기준일자, ITEM_CD) 수: {dup_mask.sum()}")

if dup_mask.any():
    # 최근 영업일 중복 sample
    latest = hp['기준일자'].max()
    latest_hp = hp[hp['기준일자'] == latest]
    latest_dup = latest_hp.groupby('ITEM_CD').size()
    latest_dup_items = latest_dup[latest_dup > 1].index
    print(f"\n최근 {latest.date()} 중복 ITEM_CD 수: {len(latest_dup_items)}")
    if len(latest_dup_items) > 0:
        sample = latest_hp[latest_hp['ITEM_CD'].isin(latest_dup_items)].sort_values(['ITEM_CD', 'FUND_CD'])
        print("\n중복 샘플:")
        print(sample[['기준일자','FUND_CD','ITEM_CD','ITEM_NM','EVL_AMT','POS_DS_CD','PDD_QTY','BUY_QTY','SELL_QTY']].to_string(index=False))

# 국내채권 키워드 ITEM만 (혹은 ISIN KR74xxxxx 처럼)
print("\n=== 최근 영업일 FUND_CD × ITEM_CD 매트릭스 (KR 채권류만) ===")
latest = hp['기준일자'].max()
lh = hp[hp['기준일자']==latest].copy()
# 국고채/채권 ETF 키워드
bond = lh[lh['ITEM_NM'].str.contains('국고채|채권|국채|스트립|TMF|머니마켓', na=False)]
print(bond[['FUND_CD','ITEM_CD','ITEM_NM','EVL_AMT','POS_DS_CD']].sort_values(['ITEM_CD','FUND_CD']).to_string(index=False))

# FUND_CD별 총 EVL_AMT 합
print("\nFUND_CD별 최근 영업일 EVL_AMT 합:")
print(lh.groupby('FUND_CD')['EVL_AMT'].sum())
