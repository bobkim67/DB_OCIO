"""SAA(전략적 자산배분) 벤치마크 구성 테이블 생성 + 적재.

BM 없는 펀드(SAA)에 실제 인덱스 컴포넌트를 부여해 AP vs SAA 수익률/기여 분해를 가능케 한다.
저장소: solution.saa_bm_components (리밸런싱날짜 버전형).

스키마(사용자 제공 포맷):
  rebal_date, portfolio, fund_cd, dataset_id, dataseries_id, region,
  weight(%), hedge_ratio, cost_adjust, tracking_multiple, biz_day_adj, name

- portfolio = '{fund}_SAA' 행이 벤치마크 컴포넌트. '{fund}' 행(dataset=fund, ds=MOD_STPR)은 AP 출처 메타.
- 멱등: 기존 fund_cd 행 삭제 후 재적재.

실행: python -m tools.setup_saa_components
"""
import pymysql

TABLE = "saa_bm_components"

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  rebal_date DATE NOT NULL,
  portfolio VARCHAR(40) NOT NULL,
  fund_cd VARCHAR(10) NOT NULL,
  dataset_id VARCHAR(20) NOT NULL,
  dataseries_id VARCHAR(20) NOT NULL,
  region VARCHAR(10),
  weight DOUBLE,
  hedge_ratio DOUBLE,
  cost_adjust DOUBLE,
  tracking_multiple DOUBLE,
  biz_day_adj INT,
  name VARCHAR(160),
  INDEX idx_fund_date (fund_cd, rebal_date)
) DEFAULT CHARSET=utf8mb4
"""

# (rebal_date, dataset_id, dataseries_id, region, weight%, hedge, cost, track, bizadj, name)
# fund NAV(AP) 메타행은 components 에서 제외 — 벤치마크 컴포넌트만 적재.
SAA = {
    "08N33": [
        ("2025-09-30", 188, 33, "KR",    58.8, 0, 0, 1,  0, "KIS 종합채권시장 총수익지수(AA-이상)"),
        ("2025-09-30", 253,  9, "KR",     4.8, 0, 0, 1,  0, "KOSPI Index"),
        ("2025-09-30", 248,  6, "ex_KR",  3.8, 0, 0, 1, -1, "ICE BofA US High Yield Constrained Index"),
        ("2025-09-30", 134,  6, "ex_KR", 21.2, 0, 0, 1, -1, "MSCI US Large Cap Growth Index"),
        ("2025-09-30", 408, 48, "ex_KR", 11.4, 0, 0, 1, -1, "Gold Spot Price"),
        ("2025-12-30", 188, 33, "KR",    59.8, 0, 0, 1,  0, "KIS 종합채권시장 총수익지수(AA-이상)"),
        ("2025-12-30", 253,  9, "KR",     4.9, 0, 0, 1,  0, "KOSPI Index"),
        ("2025-12-30", 248,  6, "ex_KR",  7.0, 0, 0, 1, -1, "ICE BofA US High Yield Constrained Index"),
        ("2025-12-30", 134,  6, "ex_KR", 16.6, 0, 0, 1, -1, "MSCI US Large Cap Growth Index"),
        ("2025-12-30", 408, 48, "ex_KR", 11.7, 0, 0, 1, -1, "Gold Spot Price"),
    ],
    # 사용자 데이터 오타 교정: 08N81 블록의 portfolio 가 08N33_SAA 로 잘못 라벨됨 → 08N81.
    "08N81": [
        ("2026-01-08", 188, 33, "KR",    16.0, 0, 0, 1,  0, "KIS 종합채권시장 총수익지수(AA-이상)"),
        ("2026-01-08", 253,  9, "KR",     4.3, 0, 0, 1,  0, "KOSPI Index"),
        ("2026-01-08", 248,  6, "ex_KR",  7.0, 0, 0, 1, -1, "ICE BofA US High Yield Constrained Index"),
        ("2026-01-08", 134,  6, "ex_KR", 32.0, 0, 0, 1, -1, "MSCI US Large Cap Growth Index"),
        ("2026-01-08", 408, 48, "ex_KR", 20.9, 0, 0, 1, -1, "Gold Spot Price"),
        ("2026-01-08", 322,  9, "KR",    19.8, 0, 0, 1,  0, "KAP Korea Bond Pricing All Index 10y-20y Index"),
    ],
    "08P22": [
        ("2026-01-23", 188, 33, "KR",    75.8, 0, 0, 1,  0, "KIS 종합채권시장 총수익지수(AA-이상)"),
        ("2026-01-23", 253,  9, "KR",     3.5, 0, 0, 1,  0, "KOSPI Index"),
        ("2026-01-23", 134,  6, "ex_KR", 12.8, 0, 0, 1, -1, "MSCI US Large Cap Growth Index"),
        ("2026-01-23", 408, 48, "ex_KR",  7.8, 0, 0, 1, -1, "Gold Spot Price"),
        ("2026-01-23", 141,  6, "ex_KR",  0.1, 0, 0, 1, -1, "Vanguard Emerging Markets Government Bond Index Fund"),
    ],
}


def main():
    conn = pymysql.connect(host="192.168.195.55", user="solution",
                           password="Solution123!", db="solution", charset="utf8mb4")
    cur = conn.cursor()
    cur.execute(DDL)
    for fund, rows in SAA.items():
        cur.execute(f"DELETE FROM {TABLE} WHERE fund_cd=%s", (fund,))
        for (rdate, ds_id, dseries, region, w, hedge, cost, track, biz, name) in rows:
            cur.execute(
                f"INSERT INTO {TABLE} (rebal_date, portfolio, fund_cd, dataset_id, "
                f"dataseries_id, region, weight, hedge_ratio, cost_adjust, "
                f"tracking_multiple, biz_day_adj, name) "
                f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (rdate, f"{fund}_SAA", fund, str(ds_id), str(dseries), region,
                 w, hedge, cost, track, biz, name),
            )
    conn.commit()
    cur.execute(f"SELECT fund_cd, COUNT(*) , COUNT(DISTINCT rebal_date) FROM {TABLE} GROUP BY fund_cd")
    for r in cur.fetchall():
        print("적재:", r)
    conn.close()


if __name__ == "__main__":
    main()
