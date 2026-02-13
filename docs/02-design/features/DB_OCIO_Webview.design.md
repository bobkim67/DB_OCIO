# DB_OCIO_Webview Design Document

> **Summary**: DB형 퇴직연금 OCIO 운용 대시보드 - 상세 설계
>
> **Project**: DB_OCIO_Webview
> **Author**: Claude Code (CTO Lead)
> **Date**: 2026-02-12
> **Status**: Draft
> **Plan Reference**: `docs/01-plan/features/DB_OCIO_Webview.plan.md`
> **Benchmark**: `General_Backtest/` R Shiny 코드베이스

---

## 1. Architecture Overview

### 1.1 System Architecture

```
[Client Browser]
       |
       v
[Streamlit App (app.py)]
  ├── Authentication Layer (streamlit-authenticator)
  ├── Session Manager (role-based routing)
  │
  ├── [Tab Layer - UI]
  │   ├── tab_overview.py      — 펀드 요약/NAV
  │   ├── tab_holdings.py      — 편입종목/MP Gap
  │   ├── tab_attribution.py   — Brinson PA
  │   ├── tab_macro.py         — 매크로 지표
  │   ├── tab_report.py        — 운용보고서/계획
  │   └── tab_admin.py         — 내부 운용팀
  │
  ├── [Module Layer - Business Logic]
  │   ├── data_loader.py       — DB 접속/데이터 로딩
  │   ├── portfolio_analytics.py — 수익률 계산/백테스트
  │   ├── brinson.py           — Brinson PA 엔진
  │   └── macro_tracker.py     — 매크로 데이터 수집
  │
  └── [Data Layer]
      ├── MariaDB (192.168.195.55)
      │   ├── SCIP DB  — 지수/가격 원천
      │   ├── dt DB    — 펀드 기준가/보유종목/PA
      │   ├── cream DB — 제로인 펀드
      │   └── solution DB — 유니버스/분류체계
      ├── ECOS API — 한국은행 금리/환율
      ├── FRED API — 미국 매크로 지표
      └── data/ — 캐시 파일 (pkl)
```

### 1.2 Data Flow

```
[시작]
  │
  v
data_loader.py
  ├── connect_mariadb() → SCIP, dt, cream, solution
  ├── load_price_data() → 6개 소스 가격 시계열
  ├── load_holiday_calendar() → 한국 영업일
  ├── load_exchange_rates() → USDKRW 현물/선물
  └── load_fund_info() → 펀드 기준가/보유종목
  │
  v
portfolio_analytics.py
  ├── combine_price_sources() → wide-form 가격 DataFrame (R: long_form_raw_data_input)
  ├── apply_t1_lag() → 해외자산 T-1 처리
  ├── calculate_daily_returns() → FX 조정 + 비용 차감
  ├── calculate_weights() → Fixed/Drift weight
  └── calculate_portfolio_return() → 가중 포트폴리오 수익률
  │
  v
brinson.py
  ├── preprocess_for_pa() → PA 입력 형식 변환 (R: BM_preprocessing)
  ├── align_comparable_period() → AP/BM 동시분석 기간 정렬
  ├── brinson_attribution() → Allocation/Selection/Cross Effect
  ├── contribution_analysis() → 종목별/자산군별 기여수익률
  └── excess_return_decomposition() → 초과성과 요인분해
  │
  v
[Streamlit Tabs] → 차트/테이블 렌더링
```

---

## 2. Module Design

### 2.1 data_loader.py — 데이터 로딩 레이어

**Benchmark**: `module_00_data_loading.R`

```python
# === DB 접속 ===
DB_CONFIG = {
    "host": "192.168.195.55",
    "user": "solution",
    "password": "Solution123!",
    "charset": "utf8mb4"
}

DATABASES = {
    "SCIP": {"db": "SCIP"},    # 지수/가격 원천
    "dt": {"db": "dt"},         # 펀드 기준가/보유종목/PA
    "cream": {"db": "cream"},   # 제로인 펀드
    "solution": {"db": "solution"}  # 유니버스/분류체계
}

# === 핵심 함수 ===

def get_connection(db_name: str) -> Connection:
    """MariaDB 접속. R: dbConnect(RMariaDB::MariaDB(), ...)"""

def load_data_information() -> pd.DataFrame:
    """전체 유니버스 마스터 테이블. R: data_information"""
    # solution.universe_non_derivative + universe_derivative

def load_holiday_calendar() -> pd.DataFrame:
    """한국 영업일 캘린더. R: dt.DWCI10220"""
    # SELECT * FROM dt.DWCI10220 WHERE CAL_DT >= '2000-01-01'

def load_scip_prices(dataset_ids: list, dataseries_ids: list) -> pd.DataFrame:
    """SCIP 가격 데이터 (Factset/Bloomberg/KIS). R: pulled_data_universe_SCIP"""
    # SELECT * FROM SCIP.back_datapoint WHERE dataset_id IN (...)

def load_bos_prices(fund_codes: list) -> pd.DataFrame:
    """BOS 펀드 수정기준가. R: BOS_historical_price"""
    # SELECT FUND_CD, STD_DT, MOD_STPR FROM dt.DWPM10510

def load_zeroin_prices() -> pd.DataFrame:
    """제로인 펀드 데이터. R: ZEROIN_historical_price"""
    # SELECT * FROM cream.data

def load_ecos_rates(stat_codes: list) -> pd.DataFrame:
    """한국은행 ECOS API 금리 데이터. R: ECOS_historical_price"""
    # ecos API 호출 → 복리지수 변환

def load_exchange_rates() -> tuple[pd.DataFrame, pd.DataFrame]:
    """USD/KRW 현물 + 선물 환율. R: USDKRW, F_USDKRW_Index"""
    # ECOS API (현물) + SCIP back_datapoint id=6 (선물)

def load_fund_holdings(fund_code: str, date: str) -> pd.DataFrame:
    """펀드 보유종목. R: dt.DWPM10530"""

def load_pa_source(fund_code: str, start: str, end: str) -> pd.DataFrame:
    """펀드 PA 원천 데이터. R: dt.MA000410"""

def load_classification_mapping() -> pd.DataFrame:
    """자산군 분류체계 (방법1, 방법2...). R: universe_non_derivative_table"""
    # solution.universe_non_derivative WHERE classification_method LIKE '방법%'
```

### 2.2 portfolio_analytics.py — 포트폴리오 분석 엔진

**Benchmark**: `module_00_Function_v3.R`

```python
# === 가격 데이터 결합 ===

def combine_price_sources(
    scip_prices: pd.DataFrame,
    bos_prices: pd.DataFrame,
    zeroin_prices: pd.DataFrame,
    ecos_prices: pd.DataFrame,
    ratb_prices: pd.DataFrame,
    custom_prices: pd.DataFrame,
    usdkrw: pd.DataFrame,
    f_usdkrw: pd.DataFrame,
    universe: pd.DataFrame
) -> pd.DataFrame:
    """
    6개 소스 → wide-form 가격 시계열 결합.
    R benchmark: long_form_raw_data_input()

    Steps:
    1. 각 소스별 pivot_wider (기준일자 x symbol)
    2. T-1 lag 적용 (region != "KR" 컬럼)
    3. full_join 으로 전체 결합
    4. USD/KRW 환율 merge
    5. timetk::pad_by_time 대응 → pd.date_range + ffill
    """

def apply_t1_lag(df: pd.DataFrame, foreign_cols: list) -> pd.DataFrame:
    """해외자산 T-1 lag. R: mutate(across(contains("(t-1)"), lag(n=1)))"""
    # df[foreign_cols] = df[foreign_cols].shift(1)

def calculate_daily_returns(
    prices: pd.DataFrame,
    universe: pd.DataFrame,
    usdkrw_return: pd.Series,
    f_usdkrw_return: pd.Series,
    hedge_cost_strictly: bool = False
) -> pd.DataFrame:
    """
    일별 수익률 계산 (FX 조정 + 비용 차감 포함).
    R benchmark: daily_return_list 계산 블록

    공식:
    1. base_return = price_t / price_t-1 - 1
    2. base_return *= tracking_multiple
    3. FX_adjust = (1 - hedge_ratio) * (region != "KR")
    4. return_fx = (1 + base_return) * (1 + usdkrw_return * FX_adjust) - 1
    5. if hedge_cost_strictly:
           hedge_cost = hedge_ratio * (usdkrw_return - f_usdkrw_return)
           return_fx = (1 + return_fx) * (1 + hedge_cost) - 1
    6. return_final = (1 + return_fx) * (1 + cost_daily) - 1
       where cost_daily = -cost_bp / 10000 / 365
    """

def calculate_weights(
    cumulative_returns: pd.DataFrame,
    initial_weights: np.ndarray,
    method: str = "fixed"  # "fixed" or "drift"
) -> pd.DataFrame:
    """
    Fixed/Drift weight 계산.
    R benchmark: Weight_fixed(T), Weight_drift(T-1)

    Fixed: 고정 비중 (리밸런싱일 비중 유지)
    Drift: (1 + cum_return) * initial_weight → 정규화
    """

def calculate_portfolio_return(
    daily_returns: pd.DataFrame,
    weights: pd.DataFrame
) -> pd.Series:
    """가중 포트폴리오 수익률. R: weighted_sum_fixed / weighted_sum_drift"""
    # return (daily_returns * weights).sum(axis=1)

def calculate_turnover(
    weights_before: pd.DataFrame,
    weights_after: pd.DataFrame
) -> float:
    """턴오버 계산. R: turn_over_res"""
    # return abs(weights_after - weights_before).sum() / 2
```

### 2.3 brinson.py — Brinson 성과분석 엔진

**Benchmark**: `func_PA_결합및요약용_final.R`

```python
# === PA 전처리 ===

def preprocess_for_pa(
    backtest_result: dict,
    weight_type: str,
    portfolio_name: str,
    cost_bp: float = 0
) -> dict:
    """
    백테스트 결과 → PA 입력 변환.
    R benchmark: BM_preprocessing()

    Returns:
        {
            "weight": DataFrame (기준일자, symbol, Weight(T), Weight(T-1)),
            "performance": DataFrame (기준일자, symbol, daily_return),
            "portfolio_return": DataFrame (기준일자, Return)
        }
    """

def align_comparable_period(
    ap_data: pd.DataFrame,
    bm_data: pd.DataFrame,
    start: str,
    end: str
) -> pd.DataFrame:
    """
    AP/BM 동시 분석 가능 기간 정렬.
    R benchmark: for_comparable_period()
    """

# === Brinson 3-Factor ===

def brinson_attribution(
    ap_weights: pd.Series,      # 자산군별 AP 비중
    bm_weights: pd.Series,      # 자산군별 BM 비중
    ap_returns: pd.Series,      # 자산군별 AP 수익률 (Normalized)
    bm_returns: pd.Series,      # 자산군별 BM 수익률 (Normalized)
    fx_split: bool = True
) -> dict:
    """
    Brinson 3-factor 분해 (일별).
    R benchmark: General_PA() 내 Brinson 계산 블록

    Allocation  = (w_AP - w_BM) * r_BM
    Selection   = w_BM * (r_AP - r_BM)
    Cross       = (w_AP - w_BM) * (r_AP - r_BM)

    Returns:
        {
            "allocation": Series (by 자산군),
            "selection": Series (by 자산군),
            "cross": Series (by 자산군),
            "residual": float (유동성및기타)
        }
    """

def calculate_correction_factor(
    excess_return_relative: float,
    excess_return_arithmetic: float
) -> float:
    """
    보정인자1: 상대 초과수익률 / 산술 초과수익률.
    R benchmark: for_초과수익률 블록
    복리 효과 보정 — 누적 기간이 길수록 차이 커짐
    """
    if excess_return_arithmetic == 0:
        return 0
    return excess_return_relative / excess_return_arithmetic

# === 기여수익률 ===

def contribution_by_security(
    performance_data: pd.DataFrame,
    weight_data: pd.DataFrame,
    portfolio_return: pd.Series,
    start: str,
    end: str,
    fx_split: bool = True
) -> pd.DataFrame:
    """
    종목별 기여수익률 계산.
    R benchmark: Portfolio_analysis() → sec별_기여수익률

    기여수익률 = 종목수익률 * 종목비중
    총손익기여도 = cum_return * cumsum(sec기여도) / cum_기준가증감
    """

def contribution_by_asset_class(
    sec_contribution: pd.DataFrame
) -> pd.DataFrame:
    """
    자산군별 기여수익률 (종목 → 자산군 집계).
    R benchmark: Portfolio_analysis() → 자산군별_기여수익률
    """

# === 초과성과 분해 ===

def excess_return_decomposition(
    pa_result: pd.DataFrame,
    correction_factor_2: pd.DataFrame
) -> pd.DataFrame:
    """
    초과수익률의 요인별 분해 (Allocation/Selection/Cross).
    R benchmark: excess_return_PA()

    보정_총손익기여도 = 총손익기여도 * 초과누적수익률 / cum_return
    """
```

### 2.4 macro_tracker.py — 매크로 지표 수집

```python
# === 데이터 소스 ===

MACRO_INDICATORS = {
    # 한국
    "BOK_BASE_RATE": {"source": "ecos", "stat_code": "722Y001", "name": "한국 기준금리"},
    "BOK_CALL_RATE": {"source": "ecos", "stat_code": "817Y002", "name": "콜금리"},
    "KOFR": {"source": "ecos", "stat_code": "817Y002", "name": "KOFR"},
    "KR_CPI": {"source": "ecos", "stat_code": "901Y009", "name": "한국 CPI"},

    # 미국
    "US_FED_RATE": {"source": "fred", "series_id": "FEDFUNDS", "name": "미국 기준금리"},
    "US_10Y": {"source": "fred", "series_id": "GS10", "name": "미국 10년물"},
    "US_CPI": {"source": "fred", "series_id": "CPIAUCSL", "name": "미국 CPI"},
    "US_PMI": {"source": "fred", "series_id": "MANEMP", "name": "미국 제조업 PMI"},

    # 환율
    "USDKRW": {"source": "ecos", "name": "원달러 환율"},

    # 시장 지수 (SCIP DB)
    "KOSPI": {"source": "scip", "dataset_id": "특정ID", "name": "KOSPI"},
    "SP500": {"source": "scip", "dataset_id": "특정ID", "name": "S&P 500"},
}

def fetch_fred_data(series_id: str, start: str, end: str) -> pd.DataFrame:
    """FRED API 매크로 데이터 조회"""

def fetch_ecos_data(stat_code: str, start: str, end: str) -> pd.DataFrame:
    """한국은행 ECOS API 조회. R benchmark: ecos::statSearch()"""

def get_macro_dashboard_data(start: str, end: str) -> dict:
    """전체 매크로 지표 한 번에 로드 + 캐싱"""

def correlate_macro_with_assets(
    macro_data: pd.DataFrame,
    asset_returns: pd.DataFrame,
    window: int = 60
) -> pd.DataFrame:
    """매크로 지표 ↔ 보유 자산군 롤링 상관관계"""
```

### 2.5 auth.py — 인증/세션 관리

```python
# streamlit-authenticator 기반
# config/users.yaml 구조:

# credentials:
#   usernames:
#     client_A:
#       email: client_a@example.com
#       name: A사 담당자
#       password: <hashed>
#       role: client
#       fund_codes: ["FUND001", "FUND002"]
#     ops_user:
#       email: ops@internal.com
#       name: 운용팀
#       password: <hashed>
#       role: ops
#       fund_codes: ["*"]  # 전체 접근

def load_auth_config() -> dict:
    """users.yaml 로드"""

def get_user_fund_codes(username: str) -> list:
    """로그인 사용자의 접근 가능 펀드 코드 반환"""

def is_ops_user(username: str) -> bool:
    """내부 운용팀 여부 확인"""

def require_auth(func):
    """인증 데코레이터 — 미로그인 시 로그인 페이지 표시"""
```

---

## 3. Tab UI Design

### 3.1 tab_overview.py — 펀드 Overview (FR-11, FR-12)

```
┌─────────────────────────────────────────────────────┐
│  [펀드 선택 드롭다운]    [기간: 1M 3M 6M YTD 1Y SI] │
├─────────────────────────────────────────────────────┤
│                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ 설정일이후    │  │ YTD 수익률   │  │ 최근 1M      │ │
│  │ +12.34%      │  │ +5.67%       │  │ -0.89%       │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                       │
│  [누적수익률 차트 — 포트폴리오 vs BM]                  │
│  (Plotly line chart, hover로 수치 확인)               │
│                                                       │
│  [BM 대비 초과수익률 추이]                             │
│  (Plotly area chart)                                  │
│                                                       │
│  [기간별 성과 테이블]                                  │
│  | 기간 | 포트 | BM | 초과 | 승률 |                  │
│  | 1M   | ...  | .. | ...  | ...  |                  │
│  | 3M   | ...  | .. | ...  | ...  |                  │
│                                                       │
└─────────────────────────────────────────────────────┘
```

### 3.2 tab_holdings.py — 편입종목 & MP Gap (FR-03, FR-04)

```
┌─────────────────────────────────────────────────────┐
│  [기준일 선택]  [비중유형: 순자산/평가]               │
├──────────────────────┬──────────────────────────────┤
│  편입종목 현황       │  MP 대비 Gap 분석             │
│                      │                              │
│  ┌────────────────┐  │  ┌────────────────────────┐  │
│  │ 자산군  │ 비중  │  │  │ 자산군│ 실제│ MP │ Gap │  │
│  │ 국내주식│ 25.3% │  │  │ 국내주│25.3│30.0│-4.7 │  │
│  │  ├ 삼성 │ 8.1%  │  │  │ 해외주│35.1│30.0│+5.1 │  │
│  │  ├ SK   │ 5.2%  │  │  │ 국내채│20.0│25.0│-5.0 │  │
│  │  └ ...  │       │  │  │ ...   │    │    │     │  │
│  │ 해외주식│ 35.1% │  │  └────────────────────────┘  │
│  │  ├ SPY  │ 15.0% │  │                              │
│  │  └ ...  │       │  │  [Gap 시각화 — 수평 바 차트]  │
│  └────────────────┘  │  (Over: 빨강, Under: 파랑)    │
│                      │                              │
│  [파이 차트]         │  [히스토리컬 Gap 추이]         │
│                      │                              │
└──────────────────────┴──────────────────────────────┘
```

### 3.3 tab_attribution.py — Brinson 성과분석 (FR-05, FR-06)

**Benchmark**: `module_03_post_analysis(PA).R`

```
┌─────────────────────────────────────────────────────┐
│ [분석기간] [FX분리 On/Off] [자산군분류: 방법1/방법2] │
├──────────────────────┬──────────────────────────────┤
│  Brinson 요인분해    │  차트                         │
│                      │                              │
│  ┌────────────────┐  │  [Tab: 포트폴리오 수익률 비교]│
│  │ 기여수익률 테이블│  │  (AP vs BM 누적수익률 차트)  │
│  │ (자산군별)      │  │                              │
│  │ 국내주식 +2.1%  │  │  [Tab: 비중 비교]            │
│  │ 해외주식 +3.5%  │  │  (stacked area AP vs BM)     │
│  │ ...             │  │                              │
│  └────────────────┘  │  [Tab: 초과성과 요인분해]     │
│                      │  (Alloc/Select/Cross 분해)    │
│  ┌────────────────┐  │                              │
│  │ 초과성과 분해   │  │                              │
│  │ Allocation +0.5%│  │                              │
│  │ Selection +1.2% │  │                              │
│  │ Cross     +0.3% │  │                              │
│  │ 합계     +2.0%  │  │                              │
│  └────────────────┘  │                              │
├──────────────────────┴──────────────────────────────┤
│  종목별 기여수익률                                    │
│  (확장 가능 테이블: 자산군 → 개별 종목)              │
│  R benchmark: single_port_table_summary()            │
└─────────────────────────────────────────────────────┘
```

### 3.4 tab_macro.py — 매크로 지표 (FR-09, FR-10)

```
┌─────────────────────────────────────────────────────┐
│ [지표 그룹: 금리 / 환율 / 경기 / 시장]              │
├─────────────────────────────────────────────────────┤
│                                                       │
│  ┌──────────────────────────────────────────────────┐ │
│  │  금리 대시보드                                    │ │
│  │  한국 기준금리 3.00% (▼ -0.25)                   │ │
│  │  미국 기준금리 4.50% (— 동결)                    │ │
│  │  [금리 추이 차트 — 한국/미국 기준금리 비교]       │ │
│  └──────────────────────────────────────────────────┘ │
│                                                       │
│  ┌──────────────────────────────────────────────────┐ │
│  │  매크로 ↔ 보유자산 연동 분석                      │ │
│  │  [60일 롤링 상관관계 히트맵]                      │ │
│  │  |       | 국내주식 | 해외주식 | 국내채권 | ...   │ │
│  │  | 기준금리|  -0.3   |  -0.1   |  +0.6   | ...   │ │
│  │  | USDKRW |  -0.2   |  +0.4   |  +0.1   | ...   │ │
│  │  | ...    |         |         |         |        │ │
│  └──────────────────────────────────────────────────┘ │
│                                                       │
└─────────────────────────────────────────────────────┘
```

### 3.5 tab_report.py — 운용보고서 & 운용계획 (FR-07, FR-08)

```
┌─────────────────────────────────────────────────────┐
│ [보고서 유형: 월간/분기/연간]  [기간 선택]           │
├──────────────────────┬──────────────────────────────┤
│  운용보고서 목록     │  보고서 뷰어                  │
│                      │                              │
│  ├ 2026-01 월간보고  │  [PDF/HTML 렌더링]           │
│  ├ 2025-Q4 분기보고  │  또는 구조화된 웹 뷰         │
│  └ ...               │                              │
├──────────────────────┴──────────────────────────────┤
│  향후 운용계획                                        │
│                                                       │
│  ┌──────────────────────────────────────────────────┐ │
│  │  2026년 1분기 운용 방향                           │ │
│  │  • 국내주식: KOSPI 2,700~2,900 밴드 예상, ...    │ │
│  │  • 해외주식: 미국 금리 인하 기대, ...             │ │
│  │  • 채권: 듀레이션 확대, ...                       │ │
│  └──────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### 3.6 tab_admin.py — 내부 운용팀 전용 (FR-13)

```
┌─────────────────────────────────────────────────────┐
│  [전체 펀드 현황]                                     │
│                                                       │
│  ┌──────────────────────────────────────────────────┐ │
│  │ 펀드코드 │ 펀드명 │ AUM │ YTD │ BM대비 │ MP Gap │ │
│  │ FUND001  │ A사    │ 500억│ +5% │ +1.2% │ 적합   │ │
│  │ FUND002  │ B사    │ 300억│ +3% │ -0.5% │ 주의   │ │
│  └──────────────────────────────────────────────────┘ │
│                                                       │
│  [크로스 펀드 비교]                                   │
│  (선택한 2-3개 펀드 수익률/비중 동시 비교)           │
│                                                       │
│  [데이터 관리]                                        │
│  • 수동 데이터 업로드 (Excel)                        │
│  • 사용자 관리 (추가/수정/삭제)                      │
│  • 캐시 갱신                                         │
└─────────────────────────────────────────────────────┘
```

---

## 4. Data Schema

### 4.1 Fund Portfolio Data (pkl cache)

```python
# fund_portfolio_{fund_code}.pkl
{
    "fund_code": "FUND001",
    "fund_name": "A사 DB OCIO",
    "inception_date": "2023-01-02",
    "benchmark": "국내주식40+해외주식30+국내채권30",
    "holdings": pd.DataFrame,  # 기준일, ISIN, 종목명, 자산군, 비중, 평가금액
    "mp_weights": pd.DataFrame,  # 자산군, MP비중, 허용범위
    "nav_history": pd.DataFrame,  # 기준일, 기준가, 수익률
    "pa_data": dict  # Brinson PA 결과 캐시
}
```

### 4.2 User Config (users.yaml)

```yaml
credentials:
  usernames:
    client_a:
      email: a@example.com
      name: A사 운용담당
      password: $2b$12$...  # bcrypt hashed
      role: client
      fund_codes:
        - FUND001
    ops_team:
      email: ops@internal.com
      name: 운용팀
      password: $2b$12$...
      role: ops
      fund_codes:
        - "*"  # 전체 펀드 접근
cookie:
  expiry_days: 30
  key: random_signature_key
  name: ocio_dashboard_cookie
```

---

## 5. Key Formulas (R → Python 변환 명세)

### 5.1 일별 수익률 (FX 조정 포함)

```python
# R: module_00_Function_v3.R 357-374행
def calc_daily_return(price_t, price_t1, usdkrw_ret, f_usdkrw_ret,
                      hedge_ratio, region, tracking_multiple,
                      cost_bp, hedge_cost_strictly):
    base_ret = price_t / price_t1 - 1
    base_ret *= tracking_multiple

    fx_adjust = (1 - hedge_ratio) * (1 if region != "KR" else 0)
    ret_fx = (1 + base_ret) * (1 + usdkrw_ret * fx_adjust) - 1

    if hedge_cost_strictly:
        hedge_cost = hedge_ratio * (usdkrw_ret - f_usdkrw_ret)
        ret_fx = (1 + ret_fx) * (1 + hedge_cost) - 1

    cost_daily = -cost_bp / 10000 / 365
    return (1 + ret_fx) * (1 + cost_daily) - 1
```

### 5.2 Brinson 3-Factor

```python
# R: func_PA_결합및요약용_final.R 529-531행
def brinson_daily(w_ap, w_bm, r_ap, r_bm):
    allocation = (w_ap - w_bm) * r_bm
    selection = w_bm * (r_ap - r_bm)
    cross = (w_ap - w_bm) * (r_ap - r_bm)
    return allocation, selection, cross
```

### 5.3 보정인자 (복리 효과)

```python
# R: func_PA_결합및요약용_final.R 491-505행
def correction_factor(cum_ap, cum_bm):
    """상대적 초과수익 vs 산술적 초과수익 보정"""
    excess_relative = (1 + cum_ap) / (1 + cum_bm) - 1
    excess_arithmetic = cum_ap - cum_bm

    # 일별 상대 초과수익률
    rel_daily = (1 + excess_relative) / (1 + lag_excess_relative) - 1
    arith_daily = daily_ap - daily_bm

    if arith_daily != 0:
        return rel_daily / arith_daily
    return 0
```

### 5.4 기여수익률

```python
# R: func_PA_결합및요약용_final.R 287-305행
def contribution_return(daily_contrib, portfolio_return, nav_change, cum_nav_change):
    """
    sec_기여도 = (daily_contrib / portfolio_return) * nav_change
    총손익기여도 = cum_return * cumsum(sec_기여도) / cum_nav_change
    """
    sec_contrib = (daily_contrib / portfolio_return) * nav_change if portfolio_return != 0 else 0
    cum_sec_contrib = np.cumsum(sec_contrib)
    total_contrib = cum_return * cum_sec_contrib / cum_nav_change if cum_nav_change != 0 else 0
    return total_contrib
```

---

## 6. Implementation Order

| Step | File | Description | Dependency | Est. LOC |
|------|------|-------------|------------|----------|
| 1 | `modules/data_loader.py` | DB 접속 + 데이터 로딩 함수 | - | ~300 |
| 2 | `modules/portfolio_analytics.py` | 가격 결합 + 수익률 계산 | Step 1 | ~400 |
| 3 | `modules/brinson.py` | Brinson PA 엔진 | Step 2 | ~500 |
| 4 | `modules/auth.py` | 인증/세션 관리 | - | ~100 |
| 5 | `modules/macro_tracker.py` | 매크로 데이터 수집 | Step 1 | ~200 |
| 6 | `app.py` | 메인 앱 (인증 + 라우팅) | Step 4 | ~100 |
| 7 | `tabs/tab_overview.py` | Overview 탭 | Step 2 | ~200 |
| 8 | `tabs/tab_holdings.py` | Holdings + MP Gap 탭 | Step 1,2 | ~250 |
| 9 | `tabs/tab_attribution.py` | Brinson PA 탭 | Step 3 | ~350 |
| 10 | `tabs/tab_macro.py` | 매크로 지표 탭 | Step 5 | ~200 |
| 11 | `tabs/tab_report.py` | 운용보고서/계획 탭 | Step 4 | ~150 |
| 12 | `tabs/tab_admin.py` | Admin 탭 | Step 4,1 | ~200 |
| 13 | `config/users.yaml` | 사용자 설정 | - | ~50 |

**총 예상**: ~3,000 LOC

---

## 7. Technology Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| Framework | Streamlit | >=1.32 | 웹 앱 프레임워크 |
| Auth | streamlit-authenticator | >=0.3 | 로그인/세션 |
| DB | PyMySQL / SQLAlchemy | latest | MariaDB 접속 |
| Data | pandas, numpy | latest | 데이터 처리 |
| Chart | Plotly | >=5.0 | 인터랙티브 차트 |
| Macro API | fredapi | latest | FRED 데이터 |
| KR API | ecos (or requests) | latest | 한국은행 API |
| Export | openpyxl | latest | Excel 다운로드 |
| Cache | streamlit cache | built-in | 데이터 캐싱 |

---

## 8. Security Considerations

| Aspect | Design | Implementation |
|--------|--------|----------------|
| 인증 | streamlit-authenticator + bcrypt | users.yaml 비밀번호 해싱 |
| 권한 | role-based (client/ops/admin) | 세션에 role 저장, 탭별 접근제어 |
| 데이터 격리 | fund_codes 기반 필터링 | 모든 쿼리에 fund_code 조건 포함 |
| DB 보안 | 내부망 전용 (192.168.195.55) | 외부 접속 차단 |
| 세션 | cookie 기반 만료 | expiry_days: 30 |

---

## 9. Testing Strategy

| Test Type | Scope | Method |
|-----------|-------|--------|
| 수익률 검증 | portfolio_analytics.py | R 결과와 1:1 비교 (소수점 6자리) |
| Brinson 검증 | brinson.py | R General_PA() 결과와 교차 검증 |
| FX 로직 검증 | 환율 조정/환헤지 비용 | 수동 계산 예제와 비교 |
| 인증 테스트 | auth.py | 권한별 접근 시나리오 |
| UI 테스트 | 각 탭 | 수동 + 스크린샷 비교 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-12 | Initial design based on R benchmark analysis | Claude Code (CTO Lead) |
