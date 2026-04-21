"""
07G04 FoF의 ETF발행시장환매 거래 + 추적배수 영향 조사.

1. 07G04 + 07G02 + 07G03의 2026-01-01 ~ 2026-04-20 ETF발행시장환매 거래 목록
2. 각 거래의 단순 sum vs R 추적배수(PDD_QTY/OPNG_AMT) 적용 후 값 비교
3. 자산군별 영향 추산
"""
import sys
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules.data_loader import (
    get_pandas_connection,
    _get_관련_fund_list,
    _load_asset_classification_mapping,
)

pd.set_option('display.width', 200)
pd.set_option('display.max_columns', 20)
pd.set_option('display.max_rows', 200)

FUND = '07G04'
START = '20260101'
END = '20260420'

related_funds = _get_관련_fund_list(FUND)
print(f"=== {FUND} related_funds: {related_funds} ===\n")

conn = get_pandas_connection('dt')
try:
    # 1) ETF발행시장환매 거래 전체 조회
    placeholders = ','.join(['%s'] * len(related_funds))
    sql = f"""
        SELECT t.std_dt, t.fund_cd, t.item_cd, t.item_nm,
               t.trd_qty, t.tr_upr, t.trd_amt, t.trd_pl_amt,
               c.tr_whl_nm
        FROM DWPM10520 t
        LEFT JOIN DWCI10160 c ON t.tr_cd = c.tr_cd AND t.synp_cd = c.synp_cd
        WHERE t.fund_cd IN ({placeholders})
          AND t.std_dt >= %s AND t.std_dt <= %s
          AND c.tr_whl_nm LIKE '%%ETF발행시장환매%%'
        ORDER BY t.std_dt, t.fund_cd, t.item_cd
    """
    trades = pd.read_sql(sql, conn, params=[*related_funds, START, END])
    print(f"[1] ETF발행시장환매 거래: {len(trades)} rows")
    if trades.empty:
        print("→ 거래 없음. 추적배수 로직 차이는 잔여 미세차 원인 아님.")
        sys.exit(0)
    print(trades)
    print()

    # 2) 단순 sum (현재 Python) vs 추적배수 적용 (R)
    trades['기준일자'] = pd.to_datetime(trades['std_dt'].astype(str), format='%Y%m%d')

    # R line 177-183 base aggregation: per (fund_cd, item_cd, tr_upr, trd_pl_amt) → trd_amt[1]
    base = trades.groupby(['fund_cd', 'item_cd', 'tr_upr', 'trd_pl_amt']).agg(
        기준일자=('기준일자', 'max'),
        item_nm=('item_nm', 'first'),
        평가시가평가액보정=('trd_amt', 'first'),
    ).reset_index()
    print(f"[2] base (R line 180-183 reframe): {len(base)} rows")
    print(base)
    print()

    # 3) 현재 Python: (기준일자, item_cd) 단순 sum
    current_py = base.groupby(['기준일자', 'item_cd']).agg(
        평가시가평가액보정_Py=('평가시가평가액보정', 'sum'),
        item_nm=('item_nm', 'first'),
    ).reset_index()
    print(f"[3] 현재 Python (단순 sum): {len(current_py)} rows")
    print(current_py)
    print()

    # 4) R 추적배수 적용:
    #    historical_position_DWPM10530에서 FUND_CD == class_m_fund(07G04)
    #    ITEM_CD가 0322800 prefix → 하위펀드코드 = ITEM_CD 마지막 5자
    #    historical_설정액_DWPM10510에서 하위펀드의 OPNG_AMT
    #    추적배수 = PDD_QTY / OPNG_AMT
    #    평가시가평가액보정 *= 추적배수 (fund_cd == 하위펀드 기준 join)

    # 모펀드 포지션 (07G04 기준, 하위펀드 보유)
    sql_mf = f"""
        SELECT STD_DT, FUND_CD, ITEM_CD, ITEM_NM, PDD_QTY
        FROM DWPM10530
        WHERE FUND_CD = %s
          AND STD_DT >= %s AND STD_DT <= %s
          AND ITEM_CD LIKE '0322800%%'
    """
    mf_pos = pd.read_sql(sql_mf, conn, params=[FUND, START, END])
    if not mf_pos.empty:
        mf_pos['기준일자'] = pd.to_datetime(mf_pos['STD_DT'].astype(str), format='%Y%m%d')
        mf_pos['하위펀드'] = mf_pos['ITEM_CD'].str.replace('0322800', '', regex=False)
        mf_pos = mf_pos[mf_pos['하위펀드'].str.len() == 5]
    print(f"[4a] 07G04 보유 모펀드 포지션: {len(mf_pos)} rows")
    if not mf_pos.empty:
        print(mf_pos[['기준일자', 'ITEM_NM', '하위펀드', 'PDD_QTY']].head(20))
    print()

    # 하위펀드 설정액
    sub_funds = [f for f in related_funds if f != FUND]
    placeholders_sub = ','.join(['%s'] * len(sub_funds))
    sql_sub = f"""
        SELECT STD_DT, FUND_CD, OPNG_AMT, NAST_AMT
        FROM DWPM10510
        WHERE FUND_CD IN ({placeholders_sub})
          AND STD_DT >= %s AND STD_DT <= %s
    """
    sub_aum = pd.read_sql(sql_sub, conn, params=[*sub_funds, START, END])
    sub_aum['기준일자'] = pd.to_datetime(sub_aum['STD_DT'].astype(str), format='%Y%m%d')
    print(f"[4b] 하위펀드 {sub_funds} OPNG_AMT: {len(sub_aum)} rows")
    print(sub_aum.groupby('FUND_CD')[['OPNG_AMT']].agg(['first', 'last', 'min', 'max']))
    print()

    # 추적배수 계산
    track = mf_pos.merge(
        sub_aum.rename(columns={'FUND_CD': '하위펀드'}),
        on=['기준일자', '하위펀드'],
        how='left',
    )
    track['추적배수'] = track['PDD_QTY'] / track['OPNG_AMT']
    print(f"[4c] 추적배수 = PDD_QTY / OPNG_AMT (07G04에서 하위펀드가 차지하는 비율):")
    print(track[['기준일자', 'ITEM_NM', '하위펀드', 'PDD_QTY', 'OPNG_AMT', '추적배수']].head(20))
    print(f"추적배수 분포: min={track['추적배수'].min():.4f}, max={track['추적배수'].max():.4f}, mean={track['추적배수'].mean():.4f}")
    print()

    # 5) R 로직 적용: base에 (기준일자, fund_cd==하위펀드) 기준 추적배수 join → 보정금액 × 추적배수
    r_base = base.merge(
        track[['기준일자', '하위펀드', '추적배수']],
        left_on=['기준일자', 'fund_cd'],
        right_on=['기준일자', '하위펀드'],
        how='left',
    )
    r_base['평가시가평가액보정_R'] = r_base['평가시가평가액보정'] * r_base['추적배수']
    print(f"[5] R 추적배수 적용 (per 거래):")
    print(r_base[['기준일자', 'fund_cd', 'item_cd', 'item_nm', '평가시가평가액보정', '추적배수', '평가시가평가액보정_R']])
    print()

    # R 최종 groupby(기준일자, item_cd) sum (FUND_CD=07G04로 통합, line 206-209)
    r_final = r_base.groupby(['기준일자', 'item_cd']).agg(
        평가시가평가액보정_R=('평가시가평가액보정_R', 'sum'),
        item_nm=('item_nm', 'first'),
    ).reset_index()
    print(f"[5b] R 최종 (추적배수 적용 + groupby sum):")
    print(r_final)
    print()

    # 6) 비교
    compare = current_py.merge(
        r_final[['기준일자', 'item_cd', '평가시가평가액보정_R']],
        on=['기준일자', 'item_cd'],
    )
    compare['차이'] = compare['평가시가평가액보정_Py'] - compare['평가시가평가액보정_R']
    compare['차이율'] = compare['차이'] / compare['평가시가평가액보정_Py']
    print(f"[6] Python 단순 sum vs R 추적배수 비교:")
    print(compare)
    print()

    # 7) 자산군 매핑
    asset_dict = _load_asset_classification_mapping()
    compare['자산군'] = compare['item_cd'].map(asset_dict).fillna('미분류')
    compare['item_nm_short'] = compare['item_nm'].str[:30]
    print(f"[7] 자산군별 영향 요약:")
    summary = compare.groupby('자산군').agg(
        거래건수=('item_cd', 'count'),
        Py_sum=('평가시가평가액보정_Py', 'sum'),
        R_sum=('평가시가평가액보정_R', 'sum'),
        차이_sum=('차이', 'sum'),
    ).reset_index()
    print(summary)
finally:
    conn.close()
