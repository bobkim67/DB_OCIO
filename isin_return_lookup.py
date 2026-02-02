"""
ISIN 코드별 일별 수익률 조회 모듈
- SCIP DB에서 Total Return Index (dataseries_id=6) 조회
- 일별 수익률 계산
"""

import json
import pandas as pd
from sqlalchemy import create_engine, text

# =========================
# 설정
# =========================
CONN_STR_SCIP = "mysql+pymysql://solution:Solution123!@192.168.195.55/SCIP?charset=utf8mb4"
START_STD_DT = "20241201"

# dataseries_id 정의
DS_TOTAL_RETURN = 6  # FG Return (Total Return Index)


def parse_price_blob(blob, currency: str = None) -> float | None:
    """
    data blob을 파싱하여 가격 추출
    - currency가 지정되면 해당 통화 가격 반환
    - 미지정시 USD 우선, 없으면 KRW
    """
    if blob is None:
        return None

    if isinstance(blob, (bytes, bytearray)):
        s = blob.decode('utf-8')
    else:
        s = str(blob)

    s = s.strip()

    # JSON 형식인 경우
    if s.startswith('{'):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                if currency:
                    val = parsed.get(currency)
                else:
                    # USD 우선, 없으면 KRW
                    val = parsed.get('USD') or parsed.get('KRW') or parsed.get('value')

                if val is not None:
                    if isinstance(val, str):
                        val = val.replace(',', '')
                    return float(val)
            return None
        except (json.JSONDecodeError, ValueError):
            return None

    # 단순 숫자인 경우
    try:
        return float(s.replace(',', ''))
    except ValueError:
        return None


def get_currency_from_isin(isin: str) -> str:
    """ISIN 코드에서 통화 추정"""
    if isin is None:
        return 'USD'
    if isin.startswith('KR'):
        return 'KRW'
    return 'USD'


def fetch_isin_daily_returns(
    isin_list: list = None,
    start_date: str = START_STD_DT,
    engine=None
) -> pd.DataFrame:
    """
    ISIN 코드별 일별 수익률 조회

    Parameters:
    -----------
    isin_list : list, optional
        조회할 ISIN 코드 리스트. None이면 전체 조회
    start_date : str
        조회 시작일 (YYYYMMDD 형식)
    engine : sqlalchemy.Engine, optional
        DB 엔진. None이면 새로 생성

    Returns:
    --------
    pd.DataFrame
        컬럼: date, ISIN, dataset_name, source_name, return_index, daily_return
    """
    if engine is None:
        engine = create_engine(CONN_STR_SCIP)

    # 날짜 형식 변환
    start_dt = pd.to_datetime(start_date, format='%Y%m%d')

    # 쿼리 작성
    if isin_list:
        query = text("""
        SELECT
            DATE(dp.timestamp_observation) as date,
            d.ISIN,
            d.name as dataset_name,
            s.name as source_name,
            dp.data
        FROM SCIP.back_datapoint dp
        INNER JOIN SCIP.back_dataset d ON dp.dataset_id = d.id
        INNER JOIN SCIP.back_dataseries ds ON dp.dataseries_id = ds.id
        INNER JOIN SCIP.back_source s ON ds.source_id = s.id
        WHERE d.ISIN IN :isin_list
          AND dp.dataseries_id = :ds_id
          AND dp.timestamp_observation >= :start_date
        ORDER BY d.ISIN, dp.timestamp_observation
        """)
        params = {
            'isin_list': tuple(isin_list),
            'ds_id': DS_TOTAL_RETURN,
            'start_date': start_dt
        }
    else:
        query = text("""
        SELECT
            DATE(dp.timestamp_observation) as date,
            d.ISIN,
            d.name as dataset_name,
            s.name as source_name,
            dp.data
        FROM SCIP.back_datapoint dp
        INNER JOIN SCIP.back_dataset d ON dp.dataset_id = d.id
        INNER JOIN SCIP.back_dataseries ds ON dp.dataseries_id = ds.id
        INNER JOIN SCIP.back_source s ON ds.source_id = s.id
        WHERE d.ISIN IS NOT NULL
          AND dp.dataseries_id = :ds_id
          AND dp.timestamp_observation >= :start_date
        ORDER BY d.ISIN, dp.timestamp_observation
        """)
        params = {
            'ds_id': DS_TOTAL_RETURN,
            'start_date': start_dt
        }

    # 데이터 조회
    with engine.connect() as conn:
        df_raw = pd.read_sql(query, conn, params=params)

    if df_raw.empty:
        print("조회된 데이터가 없습니다.")
        return pd.DataFrame()

    # 통화 결정 및 가격 파싱
    df_raw['currency'] = df_raw['ISIN'].apply(get_currency_from_isin)
    df_raw['return_index'] = df_raw.apply(
        lambda row: parse_price_blob(row['data'], row['currency']),
        axis=1
    )

    # 유효한 데이터만 필터링
    df = df_raw[df_raw['return_index'].notna()].copy()
    df = df.drop(columns=['data', 'currency'])

    # 일별 수익률 계산 (ISIN별로 pct_change)
    df = df.sort_values(['ISIN', 'date'])
    df['daily_return'] = df.groupby('ISIN')['return_index'].pct_change() * 100  # 백분율

    # 정리
    df = df.reset_index(drop=True)

    return df


def get_return_pivot(df: pd.DataFrame) -> pd.DataFrame:
    """
    일별 수익률을 피봇 테이블로 변환
    - 행: date
    - 열: ISIN (또는 dataset_name)
    - 값: daily_return
    """
    if df.empty:
        return pd.DataFrame()

    pivot = df.pivot_table(
        index='date',
        columns='ISIN',
        values='daily_return',
        aggfunc='last'
    )

    return pivot


# =========================
# 메인 실행
# =========================
if __name__ == "__main__":
    # 샘플 ISIN 리스트
    sample_isins = [
        'US78464A5083',  # SPDR S&P 500 VALUE ETF
        'US9229087443',  # VANGUARD VALUE ETF
        'KR7332500008',  # ACE 200TR
        'KR7367380003',  # ACE 미국나스닥100
    ]

    print("=" * 80)
    print("ISIN 코드별 일별 수익률 조회")
    print("=" * 80)
    print(f"시작일: {START_STD_DT}")
    print(f"조회 ISIN: {sample_isins}")
    print()

    # 데이터 조회
    df = fetch_isin_daily_returns(isin_list=sample_isins)

    if not df.empty:
        print(f"총 {len(df):,}개 레코드 조회")
        print()

        # 최근 10일 데이터 출력
        print("최근 데이터 (ISIN별 최근 5일):")
        print("-" * 80)
        for isin in df['ISIN'].unique():
            isin_df = df[df['ISIN'] == isin].tail(5)
            print(f"\n[{isin}] {isin_df['dataset_name'].iloc[0]}")
            print(isin_df[['date', 'return_index', 'daily_return']].to_string(index=False))

        # 피봇 테이블
        print("\n" + "=" * 80)
        print("일별 수익률 피봇 테이블 (최근 10일, %):")
        print("-" * 80)
        pivot = get_return_pivot(df)
        print(pivot.tail(10).round(2).to_string())

        # 통계
        print("\n" + "=" * 80)
        print("수익률 통계 (%):")
        print("-" * 80)
        stats = df.groupby('ISIN')['daily_return'].agg(['mean', 'std', 'min', 'max', 'count'])
        stats.columns = ['평균', '표준편차', '최소', '최대', '데이터수']
        print(stats.round(3).to_string())
