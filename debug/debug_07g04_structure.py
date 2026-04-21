"""07G04 구조 분석: 모펀드(FoF) 여부 확인."""
import sys
import pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import (
    _get_class_mother_fund, _load_holdings_for_pa, get_pandas_connection,
    load_fund_holdings_classified, load_pa_source,
)

FUND = '07G04'
class_m = _get_class_mother_fund(FUND)
print(f"=== {FUND} 구조 분석 ===")
print(f"class_m_fund: {class_m}")

# 1) DWPI10011에서 CLSS_MTFD_CD, MNC_DS_CD 확인
with get_pandas_connection('dt') as conn:
    q = f"""
        SELECT FUND_CD, FUND_WHL_NM, CLSS_MTFD_CD, MNC_DS_CD, MCF_DS_CD,
               FUND_PH1_CLSF_CD, FUND_PH2_CLSF_CD, FRST_OPNG_DT
        FROM DWPI10011
        WHERE FUND_CD IN ('{FUND}', '{class_m}')
          AND DEPT_CD IN ('166','061','064')
    """
    info = pd.read_sql(q, conn)
    print("\n-- DWPI10011 (펀드 정보) --")
    print(info.to_string(index=False))

# 2) 07G04 + class_m DWPM10530 보유종목 (최근 영업일)
with get_pandas_connection('dt') as conn:
    q = f"""
        SELECT STD_DT, FUND_CD, ITEM_CD, ITEM_NM, AST_CLSF_CD_NM, EVL_AMT, NAST_TAMT_AGNST_WGH
        FROM DWPM10530
        WHERE FUND_CD IN ('{FUND}', '{class_m}')
          AND STD_DT = (SELECT MAX(STD_DT) FROM DWPM10530 WHERE FUND_CD='{FUND}' AND STD_DT<='20260416')
          AND ITEM_NM NOT LIKE '%미지급%' AND ITEM_NM NOT LIKE '%미수%'
          AND EVL_AMT > 0
        ORDER BY FUND_CD, EVL_AMT DESC
    """
    hold = pd.read_sql(q, conn)
    print(f"\n-- DWPM10530 최근 영업일 {FUND} + {class_m} 보유 (EVL_AMT > 0) --")
    print(hold.to_string(index=False))

# 3) ITEM_CD 패턴 분석: 03228000XXXXX (모펀드) 비율
if not hold.empty:
    hold['is_모펀드_ITEM'] = hold['ITEM_CD'].str.startswith('0322800')
    total_amt = hold['EVL_AMT'].sum()
    mo_amt = hold.loc[hold['is_모펀드_ITEM'], 'EVL_AMT'].sum()
    print(f"\n총 보유: {total_amt:,.0f}")
    print(f"모펀드 ITEM(0322800...) 보유: {mo_amt:,.0f}  ({mo_amt/total_amt*100:.2f}%)")

# 4) _load_holdings_for_pa 결과 (compute_single_port_pa가 실제 사용하는 데이터)
print("\n-- _load_holdings_for_pa (compute_single_port_pa 입력) --")
buf_start = '20251001'
hp = _load_holdings_for_pa(class_m, buf_start, '20260416')
print(f"shape: {hp.shape}")
if not hp.empty:
    # 03-31 같은 말일 기준 표본
    latest = hp['기준일자'].max()
    print(f"최근 기준일자: {latest}")
    hp_latest = hp[hp['기준일자'] == latest].sort_values('EVL_AMT', ascending=False)
    print(hp_latest.to_string(index=False))

# 5) MA000410 (load_pa_source) class_m 기준 자산 분포
print("\n-- MA000410 (load_pa_source for class_m) --")
pa = load_pa_source(class_m, buf_start, '20260416')
print(f"shape: {pa.shape}")
if not pa.empty:
    # asset_gb 분포
    print("asset_gb 분포:")
    print(pa.groupby('asset_gb').size())
    print("\nsec_id prefix 분포 (sec_id 앞 7자리):")
    print(pa['sec_id'].str[:7].value_counts().head(10))
