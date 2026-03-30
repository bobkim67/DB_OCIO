# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

DB형 퇴직연금 OCIO(Outsourced CIO) 운용 현황 웹 대시보드.
Streamlit 기반 프로토타입으로, R Shiny 기존 시스템(General_Backtest/)을 Python으로 재구현 중.
21개 펀드 (총 AUM ~1.4조원)의 성과 모니터링, 자산배분, Brinson PA, 매크로 지표 분석 제공.

## Running the App

```bash
# 프로토타입 실행 (포트 지정)
streamlit run prototype.py --server.port 8505

# 구문 검증만 (UI 실행 없이)
python -c "import ast; ast.parse(open('prototype.py', encoding='utf-8').read())"

# 모듈 import 검증
python -c "from modules.data_loader import parse_data_blob, load_fund_holdings_lookthrough, load_vp_weights_8class, load_vp_nav; print('OK')"

# DB 접속 검증
python -c "from modules.data_loader import get_connection; c=get_connection('dt'); print(c); c.close()"
```

## Architecture

### 프로젝트 구조

```
DB_OCIO_Webview/
├── prototype.py           ← 메인 Streamlit 앱 (v6, ~2560줄, 7개 탭)
├── config/
│   ├── funds.py           ← 21개 펀드 메타정보, BM/MP 매핑, 8개 그룹, DB 설정
│   └── users.yaml         ← 사용자 인증 정보
├── modules/
│   ├── auth.py            ← 로그인 인증 모듈
│   └── data_loader.py     ← 30+ DB 로딩 함수 (MariaDB) + 자산분류 + look-through + VP + Brinson + 매크로
├── debug/                 ← R/Python PA 검증용 디버그 파일 (R 스크립트, CSV)
├── devlog/                ← 일별 개발일지
└── General_Backtest/      ← R Shiny 원본 (참조용, 수정 금지)
```

### prototype.py 탭 구조

| Tab Index | 탭명 | 핵심 기능 | DB 연동 |
|-----------|------|-----------|---------|
| tabs[0] | Overview | 기준가, 누적수익률, 기간성과, 편입현황 도넛 | **Done** |
| tabs[1] | 편입종목 & MP Gap | 자산군/종목 토글, 파이+테이블, 비중추이 | **Done** |
| tabs[2] | AP vs VP 분석 | AP/VP/MP 비중비교, Gap 추이 | **Done** (Gap추이 DB) |
| tabs[3] | 성과분석(Brinson) | 3-Factor Attribution, 워터폴, 기여도 | **Done** (MA000410 + FUND_BM) |
| tabs[4] | 매크로 지표 | TR Decomposition, EPS/PE, FX, 금리, 벤치마크 히트맵 | **Done** (SCIP) |
| tabs[5] | 운용보고 | 시장환경, 성과요약, Brinson, 리스크 종합 | **Done** (DB 기반 보고서) |
| tabs[6] | Admin | 전체 펀드 현황 (admin 전용) | **Done** |

### 데이터 흐름

**DB 연동 완료 (전체 탭)**:
- NAV/AUM: `dt.DWPM10510` → `load_fund_nav_with_aum()`
- BM 지수: **DT 우선** (`DWPM10040/10041`) → SCIP fallback (`load_composite_bm_prices()`)
  - DT BM 매핑: `data_loader.py::_DT_BM_CONFIG` (12개 펀드), `load_dt_bm_prices()`
  - SCIP fallback: 나머지 9개 펀드 (`load_composite_bm_prices()`)
- 보유종목: `dt.DWPM10530` → `load_fund_holdings_classified()` + `_classify_6class()`
- Look-through: 모펀드 전개 → `load_fund_holdings_lookthrough()`
- MP 비중: `solution.sol_MP_released_inform` → `load_mp_weights_8class()` + FUND_MP_DIRECT
- VP 비중: `solution.sol_DWPM10530` → `load_vp_holdings_8class()` (VP 전용 코드)
- VP NAV: `solution.sol_DWPM10510` → `load_vp_nav()` (fund_desc → VP 코드 자동변환)
- VP 리밸런싱: `solution.sol_VP_rebalancing_inform` → `load_vp_rebal_date()`
- Brinson PA: `dt.MA000410` → `compute_brinson_attribution()` (3-Factor, 종목 기여도)
- 매크로 지표: `SCIP.back_datapoint` → `load_macro_timeseries()` (PE/EPS/TR/FX/금리)
- Gap 추이: `dt.DWPM10530` → `load_holdings_history_8class()` (월별 자산군 비중 이력)
- 전체 펀드 요약: `load_fund_summary()` → Tab 6

**Fallback**: 모든 탭에서 DB 실패 시 mockup 자동 전환 + 실패 원인 표시

**Fallback 패턴**:
```python
DB_CONNECTED = True/False  # 앱 시작 시 접속 테스트
if DB_CONNECTED:
    try:
        real_data = cached_load_xxx(...)
    except Exception:
        st.toast("DB 오류, 목업 사용", icon="⚠️")
        # fallback to mockup
```

### 자산 분류 체계 (8분류)

| 순서 | 자산군 | 색상 | 분류 기준 |
|------|--------|------|-----------|
| 0 | 국내주식 | #EF553B | AST에 '주식'/'지수' + KR ISIN |
| 1 | 해외주식 | #636EFA | AST에 '주식'/'지수' + 해외 |
| 2 | 국내채권 | #00CC96 | AST에 '채권' + KR ISIN |
| 3 | 해외채권 | #AB63FA | AST에 '채권' + 해외 |
| 4 | 대체투자 | #FFA15A | 금/리츠/인프라/부동산 |
| 5 | FX | #19D3F3 | 달러선물/NDF/통화선물 |
| 6 | 모펀드 | #FF6692 | ITEM_CD가 '0322800'으로 시작 (자사 모투자신탁) |
| 7 | 유동성 | #B6E880 | 콜론/예금/MMF/REPO/현금 등 |

정렬 순서: `ASSET_CLASS_ORDER` dict로 관리. 테이블/차트 모두 이 순서 적용.

### Look-through 기능

- 상단 펀드 선택 바에 토글 (모펀드 편입 펀드에서만 표시)
- 모펀드 ITEM_CD 형식: `03228000{FUND_CD}` (예: `032280007J48` → `07J48`)
- `_extract_fund_code_from_item_cd()` → 하위 펀드 보유종목 로드 → 비중 가중 스케일 → 동일 종목 합산
- 1단계 전개만 (재귀 아님)

### 펀드 선택기

- 상단 바: 펀드 그룹 → 펀드 선택 (코드 오름차순) → Look-through 토글 → 펀드 정보 → 로그아웃
- 표시 형식: `{코드}  {펀드명}` (AUM 미표시)
- 정렬: 펀드코드 기준 오름차순

## Dependencies

```
streamlit, pandas, numpy, plotly, openpyxl, pymysql, python-dateutil
```

## Coding Conventions

- 한국어 변수명/주석 사용 (금융 전문용어는 영문 병기)
- Streamlit 위젯 key는 고유 문자열로 지정 (예: `key='env_krw_toggle'`)
- DataFrame 계층 구조: 대분류/중분류/소분류가 빈 문자열이면 이전 행 값 상속 (forward-fill 패턴)
- 색상 규칙: 음수=#636EFA(파랑), 양수=#EF553B(빨강) — Bloomberg 스타일
- Source 배경색: Factset=#e8f0fe, Bloomberg=#fef7e0, KIS=#e8f5e9
- 분석 코드이므로 과도한 모듈화 금지. 선형적이고 읽기 쉬운 코드 지향.
- prototype.py 수정 후 반드시 `ast.parse()` 구문 검증 수행
- DB 함수에서 `pd.read_sql` 사용 시 반드시 `get_pandas_connection()` (DictCursor 사용 금지)

## Key Patterns

### DB Caching Layer

```python
@st.cache_data(ttl=600)
def cached_load_fund_nav(fund_code, start_date=None):
    return load_fund_nav_with_aum(fund_code, start_date)
```

TTL 600초. NAV, BM(DT+SCIP), Holdings, Holdings History, Fund Summary, All Fund Data, VP Weights, VP NAV, VP Rebal Date, Brinson PA, Macro Timeseries, Holdings History 8class, DT BM 총 14개 캐시 함수.

### SCIP blob 파싱

`back_datapoint.data`는 longblob — 3가지 형태:
```python
{"USD": 608.66, "KRW": 868066.70}   # dict (가격/수익률 지수)
2451.187912                           # 단일 숫자
"13.06"                               # 문자열 숫자
```
`parse_data_blob(blob, currency)` 함수로 통일 파싱. currency 지정 시 해당 키 반환.

### 모펀드 ITEM_CD → 펀드코드 추출

DWPM10530의 모펀드 ITEM_CD는 `03228000{FUND_CD}` 형식:
```python
def _extract_fund_code_from_item_cd(item_cd):
    s = str(item_cd).strip()
    if len(s) > 5 and s.startswith('0322800'):
        return s[-5:]
    return s[-5:] if len(s) >= 5 else s
```

### 자산군별 정렬

```python
ASSET_CLASS_ORDER = {ac: i for i, ac in enumerate(ASSET_CLASSES)}
df['_sort'] = df['자산군'].map(ASSET_CLASS_ORDER).fillna(99)
df = df.sort_values(['_sort', '비중(%)'], ascending=[True, False]).drop(columns='_sort')
```

### VP 데이터 아키텍처

VP 데이터는 AP/MP와 다른 구조:
- `sol_VP_rebalancing_inform`: 리밸런싱 이벤트 로그 (ISIN/weight **없음**, 날짜/사유만)
- `sol_DWPM10530`: VP 보유종목 (VP 전용 코드로 조회, NAST_TAMT_AGNST_WGH 비중 사용)
- `sol_DWPM10510`: VP 기준가 (VP 전용 코드로 조회, MOD_STPR)

```python
# fund_desc → VP 전용 펀드코드
_FUND_DESC_TO_VP_CODE = {
    'MS GROWTH': '3MP01', 'MS STABLE': '3MP02',
    'TDF2050': '1MP50', 'TIF': '2MP24', 'Golden Growth': '6MP07', ...
}
```

Tab 2 VP 로딩 우선순위:
1. `FUND_MP_DIRECT` (사모펀드) → VP = MP 비중 사용
2. `FUND_MP_MAPPING` → `load_vp_weights_8class(fund_desc)` → DB
3. fallback hardcoded

### BM 로딩 아키텍처 (DT 우선 → SCIP fallback)

```python
# data_loader.py
_DT_BM_CONFIG = {
    '07G04': ('10041', 'BM1'),   # 서브BM1
    '06X08': ('10041', 'BM1'),   # 서브BM1
    '07G02': ('10041', 'BM1'),   # 서브BM1
    '07G03': ('10041', 'BM1'),   # 서브BM1
    '07J20': ('10041', 'BM2'),   # 서브BM2
    '07J27': ('10041', 'BM2'),   # 서브BM2
    '07J34': ('10041', 'BM2'),   # 서브BM2
    '07J41': ('10041', 'BM2'),   # 서브BM2
    '08K88': ('10041', 'BM2'),   # 서브BM2
    '1JM96': ('10040', 'B'),     # 기본BM
    '1JM98': ('10040', 'B'),     # 기본BM
    '4JM12': ('10040', 'B'),     # 기본BM
}
```

- Tab 0(Overview), Tab 3(Brinson PA), Tab 5(운용보고)에서 동일 우선순위 적용
- `cached_load_dt_bm()` → `load_dt_bm_prices()` (MOD_STPR 시계열)
- DT 빈 결과 시 자동으로 `cached_load_bm_prices()` (SCIP) fallback

### 기간수익률 계산 (DT 일치)

달력월 기반 `relativedelta` 사용 (DT DWPM10040과 정확 일치):
```python
from dateutil.relativedelta import relativedelta
_period_targets = {
    '1M': _end_dt - relativedelta(months=1),   # 3/15 → 2/15
    '3M': _end_dt - relativedelta(months=3),
    '6M': _end_dt - relativedelta(months=6),
    '1Y': _end_dt - relativedelta(years=1),
}
```
기존 고정일수(`timedelta(days=30)`) 방식은 DT와 불일치 발생.

### 설정후 수익률 기준가 보정

```python
_FUND_INCEPTION_BASE = {'4JM12': 1970.76}
```
- 4JM12 DB 첫 MOD_STPR=1998.62이지만 시스템 기준 1970.76
- `설정 후` 수익률, 메트릭 카드, 누적수익률 차트 모두 이 기준가 사용
- BM은 1000에서 시작 (DT DWPM10040 MOD_STPR 첫값)

### 자산군별 벤치마크 수익률 테이블 (tabs[4])

- 42행 x 7기간(`1D, 1W, 1M, 3M, 6M, 1Y, YTD`) 수치 데이터
- 행 유형별 포맷: `return`(%), `bp`(bp), `vol`(포인트), `econ`(%p)
- `_make_env_formatter(row_types, src_data)` 함수로 유형별 포맷 문자열 생성
- 원화환산 토글: 해외 자산에 +1.5% 가산 (mockup, 실 DB 연동 시 FX 수익률로 교체)

## Important Notes

- `General_Backtest/` 디렉토리는 R Shiny 원본 참조용. 수정하지 말 것.
- prototype.py는 단일 파일 프로토타입. 향후 tabs/ 모듈로 분리 예정.
- DB 접속 정보가 코드/config에 하드코딩 (내부망 전용).
- `users.yaml`에 사용자 비밀번호 포함 — 커밋 시 주의.
- Streamlit의 Pandas Styler 지원이 제한적: `.bar()` 등 일부 기능 미지원.
- `pd.read_sql`에 DictCursor 사용하면 컬럼명이 값으로 들어가는 버그 → 반드시 `get_pandas_connection()` 사용.
- BM 매핑: DT BM 우선 (12개 펀드 `_DT_BM_CONFIG`), SCIP fallback (9개 펀드 `FUND_BM`). SCIP 미설정: 07P70, 07W15, 08N33, 08N81, 08P22, 09L94, 2JM23.
- NAV 로딩 시작일: `FUND_META[fund]['inception']` 사용 (이전 하드코딩 '20240101' 제거)
- 기간수익률: `relativedelta` 달력월 기준 (DT DWPM10040 완벽 일치). `python-dateutil` 의존성 추가.
- MP 비중: DB 연동 완료 (`sol_MP_released_inform` + `FUND_MP_DIRECT`). 19개 펀드 MP 설정, ABL 2개 미설정.
- VP 데이터: `sol_DWPM10530/10510` 사용 (VP 전용 코드: 3MP01, 2MP24 등). `sol_VP_rebalancing_inform`은 이벤트 로그만.
- VP 코드 매핑: `data_loader.py::_FUND_DESC_TO_VP_CODE` dict로 관리.
- Brinson PA: `dt.MA000410` 테이블의 컬럼명은 영문(`sec_id`, `modify_unav_chg`), 보유종목(`load_fund_holdings_classified`)의 컬럼명도 영문(`ITEM_CD`, `ITEM_NM`)이므로 매핑 시 영문 컬럼명 사용.
- 매크로 지표: `data_loader.py::MACRO_DATASETS` dict에 SCIP dataset_id/dataseries_id 매핑.

## 연율화 성과지표 (결과4/5/6 — R 동일 로직 구현 완료)

### 구현 함수 (`modules/data_loader.py`)

| 함수 | 역할 |
|------|------|
| `compute_annualized_metrics()` | 결과4(연율화수익률) + 결과5(연율화위험) |
| `compute_rf_annualized_metrics()` | 결과6(무위험연율화수익률) |
| `compute_full_performance_stats()` | 결과4+5+6+샤프비율 통합 |
| `compute_sharpe_ratio()` | 샤프비율 = (수익률-RF)/위험 |
| `load_rf_index_from_db()` | KIS CD Index 총수익 (SCIP dataset_id=194) |
| `load_korea_holidays_weekday()` | 평일 공휴일 set (R의 KOREA_holidays) |
| `_build_weekly_returns()` | 기준가→공휴일NA→pad→ffill→주간수익률 |
| `_return_first_weekly_date()` | 불완전 주 건너뛰기 (R 동일) |
| `_calc_ref_dates()` | 기간별 기준일 (1D/1W/1M/3M/.../YTD/누적) |

### 연율화 방법 (R Shiny 기본값과 동일)

- **연율화수익률**: `return_method='v3'` (기간수익률 기하평균, 기본값)
  - v1: `mean(주간수익률) * 52`
  - v2: `mean(주간로그수익률) * 52`
  - v3: `(1+기간수익률)^(365.25/일수) - 1`
- **연율화위험**: `risk_method='v1'` (주간수익률 표준편차, 기본값)
  - v1: `sd(주간수익률, ddof=1) * sqrt(52)`
  - v2: `sd(주간로그수익률, ddof=1) * sqrt(52)`

### 무위험수익률 소스

KIS CD Index 총수익 (SCIP dataset_id=194, dataseries_id=33) 사용.
- blob: `{"totRtnIndex": "12538.6535", ...}` → `totRtnIndex / 10` (1000 리베이스)
- ECOS CD(91일) 대비 0.01~0.02bp 차이 (실무상 무시 가능)
- KAP CD 총수익지수(dataset_id=300)는 ~12bp 차이로 부적합

### Excel 검증 결과 (08N81, end=20260311)

| 항목 | Python | Excel | 차이 |
|------|--------|-------|------|
| 결과4 누적 | 0.184514756315 | 0.184515 | <0.001bp |
| 결과5 누적 | 0.102454989224 | 0.102455 | <0.001bp |
| 결과6 누적 | 0.027936009744 | 0.027937 | 0.01bp |

### 주간수익률 파이프라인 (R 동일)

```
기준가(MOD_STPR) → T-1에 1000 추가 → 평일공휴일 NA → 캘린더일 pad(ffill)
→ 요일별 group → lag(1) → 주간수익률/주간로그수익률
→ 기간 필터(end_date 요일, first_weekly_date~end_date) → 연율화
```

### DB 컬럼명 주의

DWCI10220 실제 컬럼명은 소문자: `std_dt`, `hldy_yn`, `day_ds_cd`.
`load_holiday_calendar()`에서 `AS CAL_DT`, `AS HOLI_FG`로 alias 처리.
`hldy_yn`은 'Y'/'N' 값 (CLAUDE.md 기존 설명의 '0'/'1'과 다름).

## PA 정밀화 계획 (Phase 4 — R 동일 로직 구현)

### 현재 Python PA의 한계
- 기간 전체 합산 (R은 일별 x 종목별)
- 비중: 기간말 val.last() (R은 T-1 시가평가액 / (T-1순자산+순설정금액))
- FX 분리 미구현 (R은 pl_gb='환산'으로 증권/환산 분리)
- 누적기여도: 단순 합산 (R은 경로의존적 누적)

### 핵심 검증 완료 (2026-03-06)
- `modify_unav_chg` 합산 = 기준가 변동 (완벽 일치, 08K88 20260305 검증)
- `pl_gb` 6종류: 평가, 환산, 이자, 배당, 매매, 기타 — FX 분리 가능
- 필요 데이터 전부 확보: MA000410(전컬럼), DWPM10510(순자산), DWCI10260(환율), DWPM12880(순설정)

### 구현 순서
1. `load_pa_source()` 확장 — position_gb, pl_gb, crrncy_cd, os_gb 추가
2. 일별 T-1 비중 — val(T-1) / NAST_AMT(T-1), SHORT 음수 처리
3. FX 분리 — pl_gb='환산' 필터
4. 일별 종목 기여수익률 — 수익률 x 비중(T-1), 유동성잔차
5. 누적기여도 — 경로의존적 공식
6. Brinson 3-Factor 일별화
7. 검증 — sum(종목기여도) + FX + 유동성 = 포트수익률

### R 코드 참조 파일
- `General_Backtest/04_사후분석/func_펀드_PA_모듈_adj_GENERAL_final.R` — PA 데이터 전처리, 비중계산, FX분리
- `General_Backtest/04_사후분석/func_PA_결합및요약용_final.R` — Brinson 3-Factor, 누적기여도

### Single Portfolio PA FX Split (R 동일 로직)

FX_split=TRUE일 때 증권 수익률에서 환효과 분리:
```python
# R line 552 동일: 금액 기반 환산_adjust
환산_adjust = 시가평가액(T-1) × r_FX × (1 + r_sec)
수익률(FX_제외) = (총손익 - 환산_adjust) / 조정_평가시가평가액
```
- `시가평가액(T-1)=0` (종목 첫 등장일) → `환산_adjust=0` → FX 미제거 (R 동일)
- 수학적 수식 `r_sec=(1+R)/(1+r_FX)-1`과 달리, **실제 환노출 기간에 대해서만** 환효과 인식
- 08N81 기준 R Excel과 자산군 8개 + 종목 11개 전부 0.000000 차이 검증 완료

## PDCA Status

- Feature: DB_OCIO_Webview
- Phase: Do (Phase 5 UI 개선 진행 중)
- Phase 3 완료: 전체 탭 DB 연동
- Phase 4.1 완료: 연율화수익률/위험/RF/샤프 (R 동일 로직, Excel 검증 통과)
- Phase 4.2 완료: PA 정밀화 — FX split R 완벽 일치 (환산_adjust 금액 기반)
- Phase 4.3 완료: DT BM 연동, 기간수익률 DT 일치, 설정후 수익률 보정
- Phase 5 진행: UI 개선 — BM 미설정 처리, 모펀드 분류 수정, 변동성 추가, 스파크라인 개선
- 개발일지: `devlog/` 디렉토리 (일별)
- 디버그 파일: `debug/` 디렉토리 (R/Python PA 검증용)
  - `debug_pa_original.R` — R 원본 PA_from_MOS 핵심 파이프라인 (파생 그룹핑 포함, Shiny 제거)
  - `debug_pa_full.R` — R 간소화 PA (DB 직접 조회)
  - `debug_pa_R_original_intermediate.csv` — R 원본 파이프라인 중간 데이터 (714rows, 종목별 일별)
  - `debug_pa_R_intermediate.csv` — R 간소화 버전 중간 데이터 (848rows)
  - `debug_fx_*.R` — FX split 환율/환산_adjust 디버깅
  - `debug_nast.R` — NAST_AMT 모자구조 확인

## 2026-03-24 주요 변경사항

### 모펀드 분류 수정
- 기존: `ITEM_NM`에 '모펀드'/'모투자' 포함 여부 → "사모투자신탁"도 매칭되는 오분류 발생
- 변경: `ITEM_CD.startswith('0322800')` — 자사 모투자신탁만 정확히 분류
- 영향: 08P22 월넛은행채플러스일반사모투자신탁 → 모펀드에서 국내채권으로 정정

### BM 미설정 펀드 처리
- 11개 펀드(07G02, 07G03, 07J48, 07J49, 07P70, 07W15, 08N33, 08N81, 08P22, 09L94, 2JM23) BM 미설정
- 기존: BM 없으면 mockup fallback → 변경: NAV만 표시, BM/초과수익 빈칸
- 카드: vs BM delta 제거, BM 스파크라인 → "BM 미설정"
- 기간수익률: BM/초과수익 행 조건부 삭제
- 누적수익률 차트: BM/초과수익 선 조건부 제거

### Overview 변경
- 전체 보유종목 테이블 삭제 (편입종목 탭에서 확인)
- 변동성 행 추가 (주간수익률 표준편차 × √52, R 동일)
- 미니카드 delta(전월대비 등) 제거
- 스파크라인 modebar(zoom/download 등) 제거
- 스파크라인 hovering: 소숫점 둘째자리 + 수익률 % 접미사
- 스파크라인 y축: 데이터 min/max에 5% 여유로 꽉 맞춤

### 성과분석(Brinson) 변경
- 분석기간 기본값: YTD (1/1~어제). 설정일이 당해년도면 설정일 시작
- PA 차트 데이터 레이블: 소숫점 둘째자리
- PA 종목 테이블: `.round(2)` + `.format`
- FX 레이블 잘림: 차트 높이 400, margin 확대, automargin
