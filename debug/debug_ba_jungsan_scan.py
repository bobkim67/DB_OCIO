"""08K88/07G04/08N81에서 ETF 환매 거래 후 잔존 보유가 있는 종목 전체 스캔."""
import sys, pandas as pd
sys.path.insert(0, '.')
from modules.data_loader import get_pandas_connection, _get_관련_fund_list

for class_m in ['08K88', '07G04', '08N81']:
    related = _get_관련_fund_list(class_m)
    print(f"\n{'='*100}\n=== {class_m} (related={related}) ===\n{'='*100}")

    with get_pandas_connection('dt') as conn:
        placeholders = ','.join(['%s'] * len(related))
        # 2026 ETF 환매 거래 전체
        q = f"""
            SELECT t.std_dt, t.fund_cd, t.item_cd, t.item_nm, t.trd_amt, t.trd_qty
            FROM DWPM10520 t
            LEFT JOIN DWCI10160 c ON t.tr_cd = c.tr_cd AND t.synp_cd = c.synp_cd
            WHERE t.fund_cd IN ({placeholders})
              AND t.std_dt >= '20260101' AND t.std_dt <= '20260420'
              AND c.tr_whl_nm LIKE '%%ETF발행시장환매%%'
            ORDER BY t.std_dt, t.item_cd
        """
        trades = pd.read_sql(q, conn, params=[*related])
    print(f"ETF 환매 거래: {len(trades)}건")
    if trades.empty:
        continue
    # 같은 item의 총 trd_amt + max trd_qty
    by_item = trades.groupby(['item_cd','item_nm']).agg(
        n=('trd_amt','count'), trd_amt_합=('trd_amt','sum'), trd_qty_합=('trd_qty','sum'),
        first_dt=('std_dt','min'), last_dt=('std_dt','max')
    ).reset_index().sort_values('trd_amt_합', ascending=False)
    print(by_item.to_string(index=False))

    # 각 종목의 환매 후 잔존 상태
    print("\n각 환매 종목 환매 후 1~5일 DWPM10530 보유 상태:")
    with get_pandas_connection('dt') as conn:
        for _, row in by_item.head(5).iterrows():
            q2 = f"""
                SELECT STD_DT, FUND_CD, PDD_QTY, BUY_QTY, SELL_QTY, EVL_AMT
                FROM DWPM10530 WHERE FUND_CD IN ({placeholders})
                  AND ITEM_CD = %s AND STD_DT BETWEEN %s AND %s
                ORDER BY STD_DT, FUND_CD
            """
            start = row['first_dt']
            end_dt = str(int(row['last_dt']) + 10)
            h = pd.read_sql(q2, conn, params=[*related, row['item_cd'], start, end_dt])
            if not h.empty:
                print(f"\n[{row['item_cd']}] {row['item_nm']} 환매 {row['first_dt']}~{row['last_dt']} 전후:")
                print(h.to_string(index=False))
