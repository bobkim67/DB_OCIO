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
├── prototype.py           ← 메인 Streamlit 앱 (v5, ~2260줄, 7개 탭)
├── config/
│   ├── funds.py           ← 21개 펀드 메타정보, BM/MP 매핑, 8개 그룹, DB 설정
│   └── users.yaml         ← 사용자 인증 정보
├── modules/
│   ├── auth.py            ← 로그인 인증 모듈
│   └── data_loader.py     ← 25+ DB 로딩 함수 (MariaDB) + 자산분류 + look-through + VP
├── tabs/                  ← (예정) 탭별 모듈 분리
├── docs/
│   ├── 01-plan/features/  ← Plan 문서
│   └── 02-design/features/ ← Design 문서
├── devlog/                ← 일별 개발일지
└── General_Backtest/      ← R Shiny 원본 (참조용, 수정 금지)
```

### prototype.py 탭 구조

| Tab Index | 탭명 | 핵심 기능 | DB 연동 |
|-----------|------|-----------|---------|
| tabs[0] | Overview | 기준가, 누적수익률, 기간성과, 편입현황 도넛 | **Done** |
| tabs[1] | 편입종목 & MP Gap | 자산군/종목 토글, 파이+테이블, 비중추이 | **Done** |
| tabs[2] | AP vs VP 분석 | AP/VP/MP 비중비교, Gap 추이 | **Done** (Gap추이 mockup) |
| tabs[3] | 성과분석(Brinson) | 3-Factor Attribution, 워터폴, 기여도 | mockup |
| tabs[4] | 매크로 지표 | TR Decomposition, EPS/PE, FX, 금리, 벤치마크 히트맵 | mockup |
| tabs[5] | 운용보고 | 시장환경, 성과요약, Brinson, 리스크 종합 | mockup |
| tabs[6] | Admin | 전체 펀드 현황 (admin 전용) | **Done** |

### 데이터 흐름

**DB 연동 완료 (Tab 0, 1, 2, 6)**:
- NAV/AUM: `dt.DWPM10510` → `load_fund_nav_with_aum()`
- BM 지수: `SCIP.back_datapoint` → `load_composite_bm_prices()` (복합 BM 지원)
- 보유종목: `dt.DWPM10530` → `load_fund_holdings_classified()` + `_classify_6class()`
- Look-through: 모펀드 전개 → `load_fund_holdings_lookthrough()`
- MP 비중: `solution.sol_MP_released_inform` → `load_mp_weights_8class()` + FUND_MP_DIRECT
- VP 비중: `solution.sol_DWPM10530` → `load_vp_holdings_8class()` (VP 전용 코드)
- VP NAV: `solution.sol_DWPM10510` → `load_vp_nav()` (fund_desc → VP 코드 자동변환)
- VP 리밸런싱: `solution.sol_VP_rebalancing_inform` → `load_vp_rebal_date()`
- 전체 펀드 요약: `load_fund_summary()` → Tab 6

**Mockup 잔존 (Tab 3~5)**:
- Brinson PA, 매크로 지표, 운용보고 — `np.random` 기반 샘플 데이터
- Tab 2 Gap 추이 차트 — random walk (일별 역사적 VP 비중 구축 필요)

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
| 6 | 모펀드 | #FF6692 | ITEM_NM에 '모펀드'/'모투자' |
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
streamlit, pandas, numpy, plotly, openpyxl, pymysql
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

TTL 600초. NAV, BM, Holdings, Holdings History, Fund Summary, All Fund Data, VP Weights, VP NAV, VP Rebal Date 총 10개 캐시 함수.

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
- BM 매핑: `config/funds.py::FUND_BM`에 11개 펀드 복합 BM 설정 완료. 미설정 7개: 07P70, 07W15, 08N33, 08N81, 08P22, 09L94, 2JM23.
- MP 비중: DB 연동 완료 (`sol_MP_released_inform` + `FUND_MP_DIRECT`). 19개 펀드 MP 설정, ABL 2개 미설정.
- VP 데이터: `sol_DWPM10530/10510` 사용 (VP 전용 코드: 3MP01, 2MP24 등). `sol_VP_rebalancing_inform`은 이벤트 로그만.
- VP 코드 매핑: `data_loader.py::_FUND_DESC_TO_VP_CODE` dict로 관리.

## PDCA Status

- Feature: DB_OCIO_Webview
- Phase: Do (DB 연동 Phase 2 완료 — BM/MP/VP 연동 + Tab 2)
- Plan/Design 문서: `docs/` 디렉토리
- 개발일지: `devlog/` 디렉토리 (일별)
