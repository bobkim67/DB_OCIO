# -*- coding: utf-8 -*-
"""07G04 BM 시기별 구성 적재 (solution.saa_bm_components).

전산 BM(dt.DWPM10041)은 구성이 두 번 바뀌었다 — 원본(`C:\\Users\\user\\Downloads\\python\\07G04BM`)
헤더에 12개 지수가 3블록으로 찍혀 있고, 2023-12-30 / 2026-01-01 행에서 일수익률이 리셋된다.

  2022-01-04(=07G07 편입일, 07G04 설정 2021-09-27 부터 소급 적용)
      KTBTR 67.5 / KOSPI200 11 / MSCI ACWI 10 / US REITs 0.75 / SummerHaven 0.75 / BBG Agg(H) 10
  2023-12-30  KIS 10Y KTB 56.1 / MSCI ACWI Gross 33.9 / BBG Agg(H) 10
  2026-01-01  KIS 10Y KTB 41.0 / MSCI ACWI Gross 34.0 / BBG Agg H(KRW) 25.0   ← 현행(FUND_BM 과 동일)

구 구성을 전 기간에 적용하면 설정후 BM 이 전산 대비 +2.03%p 어긋난다(2021~2023 구간).
weight 는 % 단위로 저장(기존 SAA 행과 동일 규약). 사용자 제공 표 2026-07-30.
idempotent — 07G04 행을 지우고 다시 넣는다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.data_loader import get_connection

TABLE = 'saa_bm_components'
PORTFOLIO = '07G04_BM'
FUND = '07G04'

# (rebal_date, dataset_id, dataseries_id, region, weight%, hedge_ratio, cost, track, bizadj, name)
ROWS = [
    ('2022-01-04', 315,  9, 'KR',    67.50, 0, 0, 1,  0, 'KTBTR Index'),
    ('2022-01-04', 225, 15, 'KR',    11.00, 0, 0, 1,  0, 'KOSPI200-KRX'),
    ('2022-01-04', 35,  15, 'ex_KR', 10.00, 0, 0, 1, -1, 'MSCI ACWI Index'),
    ('2022-01-04', 317, 15, 'ex_KR',  0.75, 0, 0, 1, -1, 'MSCI US REITs Index'),
    ('2022-01-04', 235,  9, 'ex_KR',  0.75, 0, 0, 1, -1, 'SummerHaven Dynamic Commodity (TR) Index'),
    ('2022-01-04', 58,   9, 'ex_KR', 10.00, 1, 0, 1, -1, 'Bloomberg Global Aggregate Total Return Index'),
    ('2023-12-30', 209, 33, 'KR',    56.10, 0, 0, 1,  0, 'KIS 10Y KTB Index'),
    ('2023-12-30', 57,   9, 'ex_KR', 33.90, 0, 0, 1, -1, 'MSCI ACWI Gross Total Return Index'),
    ('2023-12-30', 58,   9, 'ex_KR', 10.00, 1, 0, 1, -1, 'Bloomberg Global Aggregate Total Return Index'),
    ('2026-01-01', 209, 33, 'KR',    41.00, 0, 0, 1,  0, 'KIS 10Y KTB Index'),
    ('2026-01-01', 57,   9, 'ex_KR', 34.00, 0, 0, 1, -1, 'MSCI ACWI Gross Total Return Index'),
    ('2026-01-01', 256,  9, 'ex_KR', 25.00, 1, 0, 1, -1, 'Bloomberg Global Aggregate Total Return Index_H(KRW)'),
]


def main():
    conn = get_connection('solution')
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE fund_cd = %s", (FUND,))
            deleted = cur.rowcount
            cur.executemany(
                f"INSERT INTO {TABLE} (rebal_date, portfolio, fund_cd, dataset_id, "
                f"dataseries_id, region, weight, hedge_ratio, cost_adjust, "
                f"tracking_multiple, biz_day_adj, name) "
                f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(r[0], PORTFOLIO, FUND, str(r[1]), str(r[2]), r[3], r[4],
                  r[5], r[6], r[7], r[8], r[9]) for r in ROWS])
        conn.commit()
        print(f"삭제 {deleted}행 → 적재 {len(ROWS)}행")
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT rebal_date, COUNT(*), ROUND(SUM(weight),4) FROM {TABLE} "
                f"WHERE fund_cd=%s GROUP BY rebal_date ORDER BY rebal_date", (FUND,))
            for rb, n, sw in cur.fetchall():
                print(f"   {rb}  {n}개  비중합 {sw}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
