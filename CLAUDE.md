# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⛔ NEWS 데이터 미사용 (2026-06-17 사용자 확정 — 영구)

운영 wiki/코멘트/claim 의 소스는 **naver_research + monygeek + broker_mail(Outlook
리포트 메일, 2026-07-09 추가)** 이다. **news 데이터는 운영에서 쓰지 않는다** (data/news, news claims, news_classifier/vectordb/content_pool,
daily_update Step 1·2·2.5·2.6·2.7 news 산출물). 신규 작업에서 news 를 운영 소스로
끌어오거나 news claim 을 재생성/참조하지 말 것. fetch 코드는 보존만. 상세는
`market_research/CLAUDE.md` 상단 배너 참조. (근거: 2026-06-17 사용자 명시)

## ⚠️ STATUS (2026-05-13~): Streamlit 폐기 — web/ + api/ 만 사용

`prototype.py` / `tabs/` / Streamlit 기반 UI 는 **폐기**됐다. 신규 UI 작업은
전부 **`web/` (React) + `api/` (FastAPI)** 에서만 한다. 아래 "Running the App",
"Streamlit 자동 리셋 규칙" 등 Streamlit 관련 섹션은 **legacy 참조용**으로만
보존하며 현역이 아니다. 데이터 로더(`modules/data_loader.py`)는 폐기 대상이
아니라 `api/` 가 재사용한다. (근거: 2026-05-13 사용자 명시)

## 현행 상태 (2026-07-10 — React 앱)

- **펀드 11개** (`config/funds.py FUND_LIST`): **06X08**(신규 — 퇴직연금 알아서RSP, 설정 2022-02-14, 수익자 한국투자증권) + 07G02·07G03·07G04·07G07·08K88·08N33·08N81·08P22·2JM23·4JM12.
- **최상위 탭**: Overview / 편입종목(PDF) / 거래내역 / 성과분석 / 운용보고 / Admin. **Admin은 관리자 전용** (role-gate: `web/src/lib/auth.ts` `useIsAdmin()` 스텁, `?role=client`로 클라이언트 화면 미리보기 — 실인증 추후).
- **Admin 서브탭 3개**: `펀드 운용`(전 펀드 스냅샷 — 거래내역식 날짜패널 + 조회기간/기간수익률 + BM펀드 BM초과 병기 + 채권Dur(펀드)·YTM + 컴플 미니게이지) / `코멘트 생성·관리`(코멘트→보고서 2단계 승인 워크플로우. ★보고서 생성=①승인본 **시드 복사**(LLM 재생성 폐지, 2026-07-31 사용자 확정 — 편집·승인 사이클만 유지). ★4JM12 월간은 보고서 생성 시 `tools.dblife_monthly_excel`로 DB생명 데이터 엑셀 동시 산출 → `output/`, 다운로드 버튼. s6=승인 코멘트 자동 인용, 2026-07-31. ★기간 유형 5종=월간/분기/**QTD·HTD·YTD**(2026-07-31, 아래 §기간 유형) ) / `운용보고 PPT`(2026-07-14 — 펀드·기간 → `reporting.builder` 빌드·pptx 다운로드 + s4/s6 코멘트 캐시 검수·수정, `/api/admin/report-ppt/*`). 구 5개 패널(Evidence Quality~Wiki Context Pack) 제거.
- **BM(FUND_BM) 설정**: 07G04(=07G07 공유)·08K88·4JM12 + **06X08**(0.5×MSCI ACWI Gross TR 57/9 + 0.5×KIS 종합채권 TR 279/40) + **07G02**(0.2×MSCI ACWI + 0.8×KIS 종합채권 TR)·**07G03**(0.4×MSCI ACWI + 0.6×KIS 종합채권 TR — 둘 다 57/9 + 279/40, 2026-07-13 추가). 08N33/81/22는 SAA/proxy. **2JM23은 벤치마크 없음(AP 단독)** — `FUND_NO_BENCHMARK`, 2026-07-29.
- **컴플 가이드**(`holdings_service._build_compliance`): 07G02=ISP(주식≤20/위험≤20)·07G03/06X08=RSP(주식≤55/위험≤70)·07G04/07G07=07G04 내 서브펀드(07G02/03) 비중 가중평균 2행·08K88=자산군밴드·2JM23/4JM12=위험자산한도·SAA펀드(08N33/81/22)=SAA대비.
- ⚠️ **BM/설정 변경 시 `.cache/brinson/{fund}_*.pkl` 삭제 + 서버 재시작**(LRU) 필요 (DEPLOY.md §운영주의). 07G07 듀레이션은 `build_holdings` NAST를 `_portfolio_fund`(07G07→07G04)로 정규화해야 정상(2026-07-10 fix).

**2026-07-02 파일 삭제 완료**: `prototype.py`, `tabs/`, `modules/{auth,comment_ui,
charts,item_abbrev,mock_db_pension_data,snapshot_fallback}.py`, `config/users.yaml`,
`api/warmup_cli.py` + data_loader 내 tabs 전용/고아 14함수(VP 계열 등). 아래
Streamlit 관련 서술은 삭제된 파일을 가리키는 **역사 기록**이다 — git 이력으로만 복구 가능.

## Project Purpose

DB형 퇴직연금 OCIO(Outsourced CIO) 운용 현황 웹 대시보드.
**web/ (React) + api/ (FastAPI)** 로 구현. R Shiny 기존 시스템(General_Backtest/)을
Python 으로 재구현한 결과물이며, 초기 프로토타입은 Streamlit(`prototype.py`)이었으나
2026-05-13 폐기됐다(위 STATUS 참조).
9개 펀드의 성과 모니터링, 자산배분, Brinson PA, 매크로 지표 분석 제공 (2026-04-21: 12개 펀드 제거 — 06X08, 07J20/27/34/41, 07J48/49, 07P70, 07W15, 09L94, 1JM96/98).

## Running the App (2026-07-02 현행화 — LAN 배포)

```bash
# 운영 실행 (LAN 단일서버: web 빌드 + FastAPI 8020 이 SPA+API 서빙)
scripts/launch_dashboard.bat        # daily-update 질문 → npm build → uvicorn 8020

# dev (백엔드 --reload)
scripts/launch_fastapi.bat

# 모듈 import 검증
python -c "from modules.data_loader import parse_data_blob, load_fund_holdings_lookthrough; print('OK')"

# DB 접속 검증
python -c "from modules.data_loader import get_connection; c=get_connection('dt'); print(c); c.close()"

# 일일 배치 (수집~regime)
python -m market_research.pipeline.daily_update --naver-no-pdf
```

접속: `http://<LAN-IP>:8020/` (구 Streamlit 실행/리셋 규칙은 2026-07-02 파일 삭제와
함께 제거 — 필요 시 git 이력 참조)

## Wiki commit 주기 체크 (세션 시작 시)

`market_research/data/wiki/` 는 daily_update / debate / enrichment 가 자동으로
산출물을 쓰는 디렉토리. 매일 commit 하면 노이즈가 커서 **주간 batch** 정책을
운영한다. 자동 스케줄러는 두지 않고, 세션 시작 때 Claude 가 누적 상태를
체크해 **사용자에게 commit 진행 여부를 묻는다**.

세션 시작 시 다음을 점검:

```bash
git log -1 --format=%cs -- market_research/data/wiki/    # 마지막 wiki commit 일자
git -c core.quotePath=false status --porcelain -- market_research/data/wiki/ | wc -l  # 미커밋 변경 수
```

**질문 조건 (둘 다 참)**:
- 마지막 wiki commit 이 **7일 이상 전** (또는 wiki commit 이력 자체가 없음)
- 미커밋 변경분 **≥ 1**

**질문 양식 예**:
> "wiki 변경분 N건이 마지막 commit 이후 Md 누적되었습니다. weekly batch commit 진행할까요?"

**사용자 GO 시**:
```bash
python tools/weekly_wiki_commit.py
```

스크립트는 idempotent — 변경 없으면 no-op, 있으면 `git add market_research/data/wiki/`
명시 후 `chore(wiki): weekly batch (catchup={N}d, files={F})` 메시지로 commit.
다른 변경분(코드/설정 등)은 건드리지 않는다.

**침묵 조건**: 7일 이내거나 미커밋 변경 0이면 조용히 건너뛰기 (세션 노이즈 금지).

## Dependencies

```
pandas, numpy, plotly, openpyxl, pymysql, python-dateutil   # + api/requirements.txt (FastAPI)
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
    '07G02': ('10041', 'BM1'),   # 서브BM1
    '07G03': ('10041', 'BM1'),   # 서브BM1
    '08K88': ('10041', 'BM2'),   # 서브BM2
    '4JM12': ('10040', 'B'),     # 기본BM
}
```

- Tab 0(Overview), Tab 2(Brinson PA), Tab 4(운용보고)에서 동일 우선순위 적용
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
- ★ **BM 구성 버전 체인 (2026-07-30)** — 전산 BM 은 구성이 바뀐다. `saa_bm_components.rebal_date`
  를 **유효 시작일**로 보고 구간마다 해당 버전으로 일별 수익률을 계산해 이어붙인다
  (`load_bm_versions` + `_load_bm_daily_returns_versioned`). 버전 1개면 기존 경로 그대로(골든 불변).
  - **07G04 실측 구성 이력**(원본 `C:\Users\user\Downloads\python\07G04BM`, 사용자 제공 표):
    | 구간 | 구성 |
    |---|---|
    | ~2023-12-29 | KTBTR 67.5 · KOSPI200 11 · MSCI ACWI 10 · **US REITs 0.75** · **SummerHaven 0.75** · BBG Agg(H) 10 |
    | 2023-12-30~2025-12-31 | KIS 10Y KTB 56.1 · ACWI Gross 33.9 · BBG Agg(H) 10 |
    | 2026-01-01~ | KIS 10Y KTB 41 · ACWI Gross 34 · BBG Agg **H(KRW)** 25 (=현행 `FUND_BM`) |
    2026-01-01 의 지수 점프(501.83→232.23)는 리베이스가 아니라 **비헤지→원화헤지 교체**.
  - ★ **비중도 구간별이어야 한다** — `bm_composite_daily = Σ bm_daily_df[ac] × bm_w_daily[ac]` 라
    비중을 기간말 하나로 고정하면 구 구성 구간이 통째로 잘못 가중된다. 실측: 구간별로는 ±0.006%p
    인데 체인 전체가 **+0.955%p** 이탈 → `_bm_w_seg`(구간별 목표비중 일별 DataFrame)로 해결.
  - 검증(설정후 2021-09-27~2026-07-28): 전산 25.4522% vs Brinson **25.4553%(+0.0030%p)**.
    수정 전 +2.03%p. 자산군 분해에 국내주식(-1.1094)·대체(+0.2779)가 정상 출현.
  - `_map_bm_component_to_asset_class` 패턴 보강: **'KTB'→국내채권**(KTBTR Index 가 else→해외주식으로
    새던 것, 비중 67.5%), **'REIT'/'COMMODITY'→대체**(MSCI 판정보다 **앞**에 둘 것 — 'MSCI US REITs').
- BM 매핑: DT BM 우선 (5개 펀드 `_DT_BM_CONFIG`: 07G02, 07G03, 07G04, 08K88, 4JM12), SCIP composite fallback (`FUND_BM` 7개: 07G04·07G07·08K88·4JM12·06X08·07G02·07G03 — 이 중 **06X08 만 실제로 composite 경로**를 탄다). BM 미설정: 08N33, 08N81, 08P22(SAA) · 2JM23(벤치마크 없음).
  - ★ composite 경로는 `overview_service._load_bm_series` 에서 **30일 워밍업**을 두고 로드한다
    (2026-07-29). 복합지수는 pct_change 로 첫날을, ex_KR 레그는 T-1 정렬로 하루 더 잃어 설정일부터
    요청하면 BM 이 2~3영업일 늦게 시작했다(**06X08 설정후 BM 49.74 → 50.47%**, 설정일 2022-02-16
    → 2022-02-14 로 교정). SAA 경로(`_load_saa_series`)에는 원래 있던 워밍업이라 동일하게 맞춘 것.
- NAV 로딩 시작일: `FUND_META[fund]['inception']` 사용 (이전 하드코딩 '20240101' 제거)
- 기간수익률: `relativedelta` 달력월 기준 (DT DWPM10040 완벽 일치). `python-dateutil` 의존성 추가.
- MP 비중: DB 연동 완료 (`sol_MP_released_inform` + `FUND_MP_DIRECT`). 2026-04-21 12펀드 제거 후 FUND_MP_MAPPING 3개(07G02/03/04) + FUND_MP_DIRECT 6개(08K88, 08N33, 08N81, 08P22, 2JM23, 4JM12).
- VP 데이터: `sol_DWPM10530/10510` 사용 (VP 전용 코드: 3MP01, 2MP24 등). `sol_VP_rebalancing_inform`은 이벤트 로그만.
- VP 코드 매핑: `data_loader.py::_FUND_DESC_TO_VP_CODE` dict로 관리.
- Brinson PA: `dt.MA000410` 테이블의 컬럼명은 영문(`sec_id`, `modify_unav_chg`), 보유종목(`load_fund_holdings_classified`)의 컬럼명도 영문(`ITEM_CD`, `ITEM_NM`)이므로 매핑 시 영문 컬럼명 사용.
- 매크로 지표: `data_loader.py::MACRO_DATASETS` dict에 SCIP dataset_id/dataseries_id 매핑.

## Architecture

### 프로젝트 구조

```
DB_OCIO_Webview/
├── prototype.py           ← 메인 Streamlit 앱 쉘 (탭 모듈 라우팅 + 공통 ctx/cache)
├── config/
│   ├── funds.py           ← 9개 펀드 메타정보, BM/MP 매핑, 4개 그룹, DB 설정
│   └── users.yaml         ← 사용자 인증 정보
├── modules/
│   ├── auth.py            ← 로그인 인증 모듈
│   └── data_loader.py     ← 30+ DB 로딩 함수 (MariaDB) + 자산분류 + look-through + VP + Brinson + 매크로
├── debug/                 ← R/Python PA 검증용 디버그 파일 (R 스크립트, CSV)
├── devlog/                ← 일별 개발일지
└── General_Backtest/      ← R Shiny 원본 (참조용, 수정 금지)
```

### Report Runtime Boundary (3-Tier)

- **External batch** (`market_research`):
  - 뉴스 수집/분류/정제/GraphRAG/timeseries narrative
  - debate input package 생성 → `report_output/{period}/{fund}.input.json`
  - `transformers`, `sentence_transformers`, `chromadb` 등 무거운 라이브러리는 여기서만 사용
- **Streamlit admin** (`tabs/admin.py`):
  - debate 실행 트리거 (service wrapper `_run_debate_and_save()` 경유)
  - 시장 debate: `debate_service.py` → `_market.draft.json`
  - 펀드 코멘트: `fund_comment_service.py` → `{fund}.draft.json` (시장 debate + PA/보유/거래)
  - legacy `debate_published` fallback 제거
  - 결과 검토/수정/승인 → `report_output/{period}/{fund}.draft.json` / `.final.json`
  - evidence quality / warning severity 표시 (계산 아닌 읽기)
- **Streamlit client** (`tabs/report.py`):
  - approved final만 조회 → `report_output/{period}/{fund}.final.json`
  - PA 캐시 뷰어 → `report_cache/{YYYY-MM}/{fund}.json`
- **저장 관리**: `market_research/report/report_store.py` (draft/final 저장/로딩/상태)
- **IO Contract**: `market_research/docs/io_contract.md` (input/draft/final 스키마)

### prototype.py 탭 구조

| Tab Index | 탭명 | 핵심 기능 |
|-----------|------|-----------|
| tabs[0] | Overview | 설정일, YTD, 기준가, AUM 카드 + 누적수익률 + MDD 차트 |
| tabs[1] | 편입종목 | 좌=자산군별 도넛+테이블 / 우=종목별 도넛+테이블 + 비중추이(8class) |
| tabs[2] | 성과분석 | Brinson 3-Factor + 수익률비교 + 개별포트(자산군/지표 필터+약어) |
| tabs[3] | 운용보고(펀드) | report_output draft/final JSON 뷰어 (상단 펀드 연동) |
| tabs[4] | 운용보고(매크로) | 시장 debate 코멘트 + 출처 + 관련 지표 차트 (_market 고정) |
| tabs[5] | DB ALM 적합성 | 적립률/듀레이션/필요수익률 gauge/금리충격/CF bucket (mockup) |
| tabs[6] | 퇴직연금 DB 현황 | DBO/자산 워터폴 + 5개년 DBO증가분vs운용수익 + 미니바차트 (mockup) |
| tabs[7] | Peer 비교 | boxplot/scatter/stacked bar/ranking + 필터 (mockup) |
| tabs[8] | Admin(운용보고_매크로) | 시장 debate 실행/검수/승인 + coverage metrics (admin) |
| tabs[9] | Admin(운용보고_펀드) | 펀드 코멘트 생성/검수/승인 + 거래내역/비중 테이블 (admin) |

> 정본 충돌 (KEEP — 임의 해소 금지): 아래 "2026-04-14 Status Update > 탭 구조"는
> `[공통] 5탭 + [Admin] 2탭` 구조로 서술되어 위 11탭(tabs[0]~tabs[10]) 표와 충돌한다.
> 양쪽 모두 보존한다.

### 데이터 흐름

**DB 연동 완료 (전체 탭)**:
- NAV/AUM: `dt.DWPM10510` → `load_fund_nav_with_aum()`
- BM 지수: **DT 우선** (`DWPM10040/10041`) → SCIP fallback (`load_composite_bm_prices()`)
  - DT BM 매핑: `data_loader.py::_DT_BM_CONFIG` (5개 펀드: 07G02, 07G03, 07G04, 08K88, 4JM12), `load_dt_bm_prices()`
  - SCIP fallback: 나머지 9개 펀드 (`load_composite_bm_prices()`)
- 보유종목: `dt.DWPM10530` → `load_fund_holdings_classified()` + `_classify_6class()`
- Look-through: 모펀드 전개 → `load_fund_holdings_lookthrough()`
- MP 비중: `solution.sol_MP_released_inform` → `load_mp_weights_8class()` + FUND_MP_DIRECT
- VP 비중: `solution.sol_DWPM10530` → `load_vp_holdings_8class()` (VP 전용 코드)
- VP NAV: `solution.sol_DWPM10510` → `load_vp_nav()` (fund_desc → VP 코드 자동변환)
- VP 리밸런싱: `solution.sol_VP_rebalancing_inform` → `load_vp_rebal_date()`
- Brinson PA: `dt.MA000410` → `compute_brinson_attribution_v2()` (3-Factor, 종목 기여도, R 완벽 일치)
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
- 모펀드 ITEM_CD 형식: `03228000{FUND_CD}` (예: `0322800007G02` → `07G02`)
- `_extract_fund_code_from_item_cd()` → 하위 펀드 보유종목 로드 → 비중 가중 스케일 → 동일 종목 합산
- 1단계 전개만 (재귀 아님)

### 펀드 선택기

- 상단 바: 펀드 그룹 → 펀드 선택 (코드 오름차순) → Look-through 토글 → 펀드 정보 → 로그아웃
- 표시 형식: `{코드}  {펀드명}` (AUM 미표시)
- 정렬: 펀드코드 기준 오름차순

## 2026-04-14 Status Update

### 탭 구조

```
[공통] Overview | 편입종목 | 성과분석 | 운용보고(펀드) | 운용보고(매크로)
[Admin] Admin(운용보고_매크로) | Admin(운용보고_펀드)
```

상단 펀드 선택: 7개 (07G04, 08K88, 08N33, 08N81, 08P22, 2JM23, 4JM12), 기본값 08K88.
삭제된 탭: Admin(펀드현황), 매크로지표.

> 정본 충돌 (KEEP — 임의 해소 금지): 위 `[공통] 5탭 + [Admin] 2탭` 서술은
> "Architecture > prototype.py 탭 구조"의 tabs[0]~tabs[10] 11탭 표와 충돌한다.
> 양쪽 모두 보존한다.

### Current Priorities

- 다음: R과 Brinson residual 비교, 비중추이 override 확인, pilot checklist.

### Important Current State

- **펀드 7개 표시** (상단): 07G04, 08K88, 08N33, 08N81, 08P22, 2JM23, 4JM12.
- Tab modules: `tabs/overview.py`, `tabs/holdings.py`, `tabs/brinson.py`, `tabs/report.py`, `tabs/admin_macro.py`, `tabs/admin_fund.py`.
- `tabs/report.py` — 운용보고(매크로): `_market` 고정, 운용보고(펀드): 상단 펀드 연동. client=final만.
- `tabs/admin_fund.py` — 거래내역/비중변화 테이블 (자산군 소계+종목 상세).
- `tabs/admin_macro.py` — 시장 debate + evidence + coverage metrics.
- `tabs/admin.py`는 펀드 현황 + **debate workflow** (생성→검토→수정→승인). 전처리 로직 없음.
- `prototype.py` 탭 구조: Overview / 편입종목 / 성과분석 / 매크로 / **운용보고** / **운용보고(전체)** / Admin.

### Comment Engine v3 + 3-Tier 파이프라인

```
[외부 배치 — market_research]
  [일일 — daily_update.py]
  Step 0: 매크로 지표 (SCIP/FRED/NYFed/ECOS)
  Step 1: 뉴스 수집 (네이버 + Finnhub)
  Step 2: 뉴스 분류 (Haiku 21주제)
  Step 2.5: 정제 — dedupe → salience(bm_anomaly) → fallback
  Step 3: GraphRAG 증분 (primary + stratified → TKG decay/merge/prune)
  Step 4: MTD 델타 (토픽 카운트)
  Step 5: regime_memory (shift 감지)

  [월별]
  블로그 digest → enriched_digest_builder → 뉴스 벡터DB 교차검증
  뉴스 → news_content_pool_builder → KMeans 클러스터링 → Haiku 한국어 요약
         report_cache_builder → 펀드별 PA cache

  [CLI — report_cli.py]
  build --prepare: debate input package 생성 → report_output/{period}/{fund}.input.json
  build: 대화형/자동 모드 — debate + 코멘트 생성 (CLI 직접 실행도 가능)

[Streamlit Admin — tabs/admin.py]
  debate 실행 버튼 → _run_debate_and_save() → report_store.save_draft()
  → 후처리(sanitize) + evidence annotations + warning severity
  → admin 검토 textarea → draft 저장 / 최종 승인
  → report_store.approve_and_save_final() → .final.json

[Streamlit Client — tabs/report.py]
  report_store.load_final() → approved 코멘트 표시
  report_cache → PA 기여도 표시
  (draft/warning/evidence raw 미노출)
```

### 저장 구조 (report_output)

```
market_research/data/report_output/
├── {period}/
│   ├── {fund}.input.json      ← 외부 배치 생성
│   ├── {fund}.draft.json      ← admin debate 결과
│   └── {fund}.final.json      ← admin 승인 최종본 (client 조회 대상)
└── _evidence_quality.jsonl    ← 누적 evidence 추적
```

상태: `not_generated` → `draft_generated` → `edited` → `approved`

### 저장/로딩 (report_store)

- `market_research/report/report_store.py` — draft/final JSON 저장·로딩·상태 관리 (IO contract 구현)
- `market_research/docs/io_contract.md` — 외부 배치 ↔ Streamlit 데이터 인터페이스 정의

### 기존 파일 (comment engine)

- `market_research/pipeline/enriched_digest_builder.py` — 블로그 토픽별 뉴스 교차검증
- `market_research/pipeline/news_content_pool_builder.py` — 뉴스 클러스터링 + Haiku 요약
- `market_research/report/report_service.py` — factor_data 생성 (PA용 + 매크로용)

### PA 종목 분류 로직

- **1순위**: `solution.universe_non_derivative` (classification_method='방법3') — R 동일
- **2순위**: `asset_gb` + 종목명 키워드 fallback
- 분류 함수: `comment_engine._classify_pa_item()` (v1, 합산용), `_classify_pa_item_v2()` (종목상세용)
- holdings 분류: `load_fund_holdings_summary()` 내 키워드 매칭
  - `'금'` 키워드 오매칭 수정 (증권금융/미지급금/미수금 → 유동성)

### market_research Notes

- `market_research/collect/macro_data.py` — 뉴스 3소스(네이버/Finnhub/NewsAPI) + 매크로 지표 수집
- `market_research/collect/naver_blog.py` — monygeek 블로그 증분 스크래핑
- `market_research/core/dedupe.py` — article_id + 중복제거 + event clustering (TOPIC_NEIGHBORS 8그룹)
- `market_research/core/salience.py` — bm_anomaly(z>1.5, 7일캡) + 3단계 source + fallback(키워드필수)
- `market_research/pipeline/daily_update.py` — Step 2.5 `_step_refine()` (정제 오케스트레이션)
- `market_research/analyze/news_classifier.py` — 21주제 + 13키 자산영향도 (Haiku)
- `market_research/analyze/graph_rag.py` — `_stratified_sample()` (dynamic cap 300~500) + Self-Regulating TKG
- `market_research/analyze/news_vectordb.py` — ChromaDB + hybrid_score (cosine + salience×0.3)
- `market_research/report/debate_engine.py` — 4인 debate + diversity guardrail (토픽5/이벤트2) + evidence_ids
- `market_research/report/comment_engine.py` — BM/PA/digest → LLM 프롬프트 + 코멘트 생성
  - 8개 펀드: A포맷(08P22,08N81,08N33,07G02,07G03), C포맷(07G04), D포맷(2JM23,4JM12)
- `market_research/report/cli.py` — 통합 CLI (build/list, 대화형/auto/edit)
- `market_research/tests/ablation_test.py` — 정제 효과 비교 프레임워크

### Known Issues

- `NewsAPI` 무료 플랜 약관 위반 가능성 → 대체 소스 미구현.
- evidence ref 오매핑률 누적 데이터 부족 (debate 2회+ 필요).

### TODO (P0 — 다음 세션)

1. **debate 재실행 2회+** → `_evidence_quality.jsonl` 누적 기록 확보
2. **pilot_checklist 13항목 전수 확인** → 전부 PASS 후 파일럿 시작

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

### Excel 검증 결과

수치표(연율화 결과4/5/6 Excel 검증, 08N81 end=20260311)는 [`docs/pa_validation.md`](docs/pa_validation.md) 참조.

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

## Brinson PA R일치 (2026-04-17)

### v2 구현 (R 완벽 일치)
- **compute_brinson_attribution_v2**: compute_single_port_pa(R PA_from_MOS exact) 재활용 + BM 결합
- **AP per-security**: MA410 `총손익/조정_평가시가평가액` (R 곱셈분해 `(1+R)/(1+r_FX)-1`)
- **자산군 집계**: value-weighted 금액합/평가액합 (기존 modify_unav_chg per-unit 방식 대체)
- **FX 환산_adjust**: 시가평가액(T-1) × r_FX × (1+r_sec) (금액 기반, R 동일)
- **비중**: weight_PA (조정평가/(순자산T-1+순설정), R 동일) — 순자산비중 대신 사용
- **보정인자1**: 상대일별초과/단순일별초과 (R line 504)
- **보정인자2**: path-weighted × 단순누적/상대누적 (R line 594, `excess_return_PA`)

### BM 구현 (R 프로덕션 일치)
- **BM R동일 설정**: KOSPI(253/15), MSCI ACWI(35/15 USD T-1×USDKRW), BBG AGG(256/9 hedged T-1), KAP All(257/9), KAP Call(255/9)
- **BM -34bp/yr**: 복합 BM에만 적용 (자산군별 RAW, cost→유동성잔차 흡수)
- **_kr_dates**: DWCI10220 영업일 캘린더 직접 사용 (R selectable_dates 동일)
- **BM 날짜**: intersection→union (R 동일, 누락일=0)
- **BM FX 가산분해**: `FX_daily = total_ret - sec_ret` (R 동일)
- **USDKRW**: ECOS API(731Y003) → DT DWCI10260 fallback → SCIP fallback
- **BM 웜업**: start_date - 45일 로드 (T-1 shift 안정화)
- **KAP 매핑**: `_map_bm_component_to_asset_class`에 KAP 패턴 추가

### 검증 v2

R↔Python 일치 수치표(08K88, AP/BM/초과/Alloc/Select/Cross/Sum + 자산군별 3-Factor 요약)는 [`docs/pa_validation.md`](docs/pa_validation.md) 참조.

### FX 자산군 구조 통합 (2026-04-17 추가)
- 기존: USD(FX) overlay + USMUSD022001 등 직접포지션이 **별도 row**로 분리
- 수정: R line 605-613 공식 적용 — 모든 USD 노출 row (증권 환산 + 유동 USD)를 **sec_id="USD" 단일 row로 통합**
- 공식: `수익률(FX) = sum(환산_adjust) / sum(|조정_평가시가평가액|)` (증권 FX효과 + 유동 USD 총손익)
- sec_summary가 R과 동일 (FX 자산군 = USD 단 1개 sec)
- 그러나 수치 차이는 그대로 (FX 자산군 수익률 Py 1.47% vs R 1.67%, 0.20%p 차이 유지)

### 잔여 이슈
- **FX 자산군 일별 수익률 0.20%p systematic 차이**: sec 구조 통합으로도 해결 안 됨. 2026-01-02 Python 0.000009 vs R 0.003337 등 일별 값 자체 차이. 후보 원인: ① 한국 영업일 캘린더 기준일 차이 ② USDKRW T-1 참조 방식 ③ r_sec 곱셈분해 정밀도 ④ 시가평가액(T-1) 계산 세부
- **추적 방법**: R 실행 결과 일별 per-sec raw (환산_adjust, 조정평가액, r_sec) CSV 확보 후 1:1 비교 필요
- **국내채권 factor 0.0026%p 잔여 (FoF + std_val precision)**: 2026-04-21 세션에서 `_load_etf_redemption_adjustment`에 FoF 추적배수(R line 191-210) 적용 → 해외채권/해외주식/FX Alloc 잔여차 0 완전 해소. 남는 국내채권 0.0026%p는 07G04 FoF Cartesian + 신규매수+기존혼합 edge case 3건 중 KR7385560008(3/9, std_val fractional 0.026)에서 distinct 실패로 발생. R Excel도 Cartesian sum(amt) 2x 부풀림이 자기 일관 값이라 Py 정확값과의 본질적 격차 — 한계 인정. (memory: feedback_brinson_domestic_bond_residual.md)
- **4JM12 BM 정확 수정 ✅** (2026-04-21): 'KAP All(257/9, 0.495) + KAP MMI Call(255/9, 0.055) + MSCI ACWI(35/15) 0.225 unhedged + 0.225 hedged'. AP/BM/초과 R Excel 0bp 일치. 잔여: FX hedging 분리(R FX 비중 음수 처리) + 유동성 자산군 매핑.
- Brinson 시작일: 전년 12/31 자동 (2026-04-22, `tabs/brinson.py`에서 `datetime(_year-1, 12, 31)` + 설정일 late 비교)
- UI 연결: `compute_brinson_attribution_v2`만 사용, 구함수(v1) 삭제 완료 (2026-04-22)

## 자산군 분류 방법 4종 지원 (2026-04-22)

R Shiny UI의 `classification_method` 드롭다운을 Python에 이식. `solution.universe_non_derivative`/`universe_derivative`의 `classification_method` 컬럼 값을 그대로 사용.

### 방법 정의

| 방법 | 자산군 구성 | 특징 |
|------|------------|------|
| 방법1 | 주식 / 채권 / 대체 / FX / 유동성 | 국내외 병합, 대체 독립 |
| 방법2 | 주식 / 채권 / FX / 유동성 | 국내외 병합, 대체 → 주식 흡수 |
| **방법3** | 국내주식 / 해외주식 / 국내채권 / 해외채권 / 대체 / FX / 유동성 | **기본값** (기존) |
| 방법4 | 국내주식 / 해외주식 / 국내채권 / 해외채권 / FX / 유동성 | 대체 → 해외주식 흡수 (4JM12 기본) |

(방법5 = 지역 분류 / 파생 미지원 → 구현 제외)

### 구현

- `modules/data_loader.py`:
  - `BRINSON_METHOD_CLASSES`, `BRINSON_METHOD_BM_CLASSES` dict 상수
  - `_collapse_asset_class()` — 국내/해외 병합 및 대체 흡수 로직
  - `_map_bm_component_to_asset_class(comp_name, method)` — BM 컴포넌트 매핑 method별 분기
  - `_load_bm_daily_returns_by_class(..., mapping_method)` — FX 오버레이 대상 자산군 동적화
  - `compute_brinson_attribution_v2(..., mapping_method='방법3')` — 방법별 자산군 동적 처리
  - `compute_single_port_pa` fallback: 방법1/2일 때 '주식'/'채권'으로 병합, asset_summary 순서 method별
- `config/funds.py`:
  - `FUND_DEFAULT_MAPPING_METHOD = {'4JM12': '방법4'}` — 펀드별 기본값
  - `DEFAULT_MAPPING_METHOD = '방법3'`
- `prototype.py::cached_compute_brinson(..., mapping_method='방법3')` — 캐시 키에 method 포함
- `tabs/brinson.py`:
  - 드롭다운 "분류 방법" 추가 (방법1~4) + help tooltip
  - 펀드별 기본값 자동 선택, 사용자 수동 변경 가능
  - 5분류 축소 로직 method별 분기 (`_core5_by_method`)

### 검증 (08K88 / 4JM12)

- 회귀 검증 수치(08K88/4JM12 4개 방법 불변)는 [`docs/pa_validation.md`](docs/pa_validation.md) 참조.
- **GDX (US92189F1066) 분류 확인 ✅**:
  - 방법1: 대체 / 방법2: 주식 / **방법3: 대체** / **방법4: 해외주식** / 방법5: NULL
  - `universe_non_derivative` DB 값과 `compute_single_port_pa` 결과 완전 일치

## 도메인 노트 (모펀드 분류 / BM 미설정 / PA 디버그)

- **모펀드 분류**: `ITEM_CD.startswith('0322800')` — 자사 모투자신탁만 분류 (`ITEM_NM` '모펀드/모투자' 매칭은 "사모투자신탁" 오분류 유발). 영향: 08P22 월넛은행채플러스일반사모투자신탁 → 국내채권으로 정정.
- **BM 미설정 펀드 3개**: 08N33, 08N81, 08P22 → SAA 비교. (07G02/07G03은 2026-07-13 FUND_BM 추가됨.)
- **★ 2JM23 = 벤치마크 없음 (AP 단독, 2026-07-29 사용자 확정)**
  - 배경: `saa_bm_components` 에 2JM23 SAA 가 **2버전**(2016-03-24 / 2025-12-30) 있는데 버전 선택이
    '기간말 기준 단일 셋'이라 설정후 분석이 2025 구성을 2016 년까지 소급했다
    (SAA +356.83% vs AP +148.76%, 초과 **-208%p**). 사모 OCIO 는 정기 리밸런싱이 없고 SAA 구성이
    사후 부여된 참조선이라 장기 비교가 성립하지 않아 **벤치마크를 두지 않기로** 했다.
  - 구현: `config/funds.py FUND_NO_BENCHMARK = {'2JM23'}` 가 **전 경로 차단** —
    `load_saa_components` / `_build_proxy_bm_info`(data_loader) + `_build_bm_meta`(brinson_service) +
    `_load_bm_series`/`_load_saa_series`(overview_service). ⚠ 2JM23 은 `FUND_MP_DIRECT` 에도 있어
    brinson 쪽을 막지 않으면 **MP 목표비중이 SAA 로 표시**된다.
  - DB 행(`saa_bm_components`)·`FUND_MP_DIRECT` 항목은 **이력 보존용으로 남긴다**(삭제 금지).
  - 프론트(`BrinsonTab.tsx`): `hasBm = bm_source !== "none"` 로 BM수익률·초과 KPI 카드, 표1 BM 열/
    초과기여 열, Brinson 요인표(Alloc/Select/Cross), 워터폴, 기간별 BM·초과 행, 요인효과 토글을
    모두 감춘다. BM 이 없으면 BM비중 0 → 초과=AP 전액·전부 Cross 로 계산돼 오해를 준다.
- **debug/ 파일 인덱스** (R/Python PA 검증용):
  - `debug_pa_original.R` — R 원본 PA_from_MOS 핵심 파이프라인 (파생 그룹핑, Shiny 제거)
  - `debug_pa_full.R` — R 간소화 PA (DB 직접 조회)
  - `debug_pa_R_original_intermediate.csv` — R 원본 중간 데이터 (714rows, 종목별 일별)
  - `debug_pa_R_intermediate.csv` — R 간소화 중간 데이터 (848rows)
  - `debug_fx_*.R` — FX split 환율/환산_adjust 디버깅
  - `debug_nast.R` — NAST_AMT 모자구조 확인

## 거래내역 탭 (2026-06-15, React+FastAPI / origin/main 머지)

DashboardPage 신규 탭 "거래내역" — 거래내역 조회 + 일별 비중 영역차트 + FX 포지션 + 종목 수익률을 한 탭에 통합. (Streamlit 무관, web/+api/ 전용)

### API (`api/.../transactions.py` — 라우터/서비스/스키마)
| 엔드포인트 | 내용 |
|-----------|------|
| `GET /funds/{code}/transactions?start&end` | 거래내역. FoF는 자펀드 치환, 콜론·환전 제외, 발행/환매(BA정산) 라벨 |
| `GET /funds/{code}/weight-history?start&level` | 일별 비중(asset/security), 6버킷, FoF 가중 |
| `GET /funds/{code}/fx-position?start` | 달러선물 순비중(매도=음수). 4JM12만 has_fx |
| `GET /funds/{code}/securities` | 보유종목(버킷1~5, 가격커버 플래그) — 수익률 드롭다운용 |
| `GET /funds/{code}/security-returns?item_cd&item_nm&start&end` | SCIP FG Return 지수(시작=100) + 매수/매도 마커 + 보조축 편입비중 |

### 데이터 로더 (`modules/data_loader.py`)
- `load_fund_trades_lookthrough`, `load_weight_history_lookthrough`, `load_fx_position_history`,
  `load_fund_securities`, `load_security_return_with_trades`, `_load_holdings_range`
- `_derive_trade_side(bs, tr_nm)`: M/D 우선 → DWCI10160 거래코드명으로 발행/환매(BA정산)·환전 판별
- `_collapse_to_6bucket`: 국내·해외주식 / 국내·해외채권 / 금·대체 / 유동성 (FX·모펀드→유동성)
- **TTL 캐시**: `@_ttl_cache(6h)` + `_get_관련_fund_list` `lru_cache` → weight-history 3.6s→0.03s.
  단일 uvicorn 인메모리(워밍업 없음 — 첫 콜드 1회만 느림)

### 거래코드 의미 (DWPM10520 buy_sell_ds_cd=None)
- B060/B062 = ETF발행/환매 BA정산(qty=0 정산성) → '발행(BA정산)'/'환매(BA정산)' 라벨 유지
- B650/B652 = 환전, 콜론 = MMF → 포지션 뷰에서 제외

### 프론트 (`web/src/`)
- `tabs/TransactionsTab.tsx` + charts `WeightAreaChart`/`FxPositionChart`/`SecurityReturnChart`
- 거래내역: MTD 기본 + radio(1/3/6M·연초)+custom date. 영역차트: 자산군↔종목 토글, YTD 기본, 종목 상위N+유동성묶음
- 종목 수익률 = **종목 자체 수익률(편입비중 미반영)** + 보조축 비중 파스텔 레이어. 디폴트=비중 최상위 종목

### 미완
- 시각검증 08K88/07G04/4JM12 위주. (콜드 로드 워밍업은 아래 2026-06-17 에서 구현)

## 2026-06-17 세션 (영속캐시 · 워밍업 · 영역차트 마커 · 성과분석 개편)

### 영속 디스크 캐시 (재기동 콜드로드 단축)
- `modules/db_cache.py` 신설 — DWPM10530 일별범위(`_load_holdings_range`)·DWPM10520 거래
  (`load_fund_trade_detail`)를 `.cache/db_cache.sqlite`(gitignore)에 영속. warm 시 **최근
  5영업일만 재조회**(정정 흡수)+신규 증분. env `OCIO_DISABLE_DB_CACHE=1` 우회.
- ★ **STD_DT 는 varchar(8)** — 날짜 필터에 int 넘기면 인덱스 미사용 full scan(8s) → **반드시 `str()`**(0.02s).
- **편입종목(load_fund_holdings_lookthrough)·FX·보유목록은 db_cache 미적용**(최신일 스냅샷이라).

### Brinson 디스크 캐시 + 워밍업
- `brinson_service._compute_cached` 에 디스크 레이어(`.cache/brinson/{fund}_{start}_{end}_{method}.pkl`)
  + 기존 LRU. 재기동에도 유지. key=(fund,start,end,method) — end=어제라 새 날엔 새 키(자연 재계산).
  ⚠️ 스키마 변경(아래 BM기여 추가) 시 `.cache/brinson` 비워야 함.
- `api/warmup_cli.py` 신설 — cmd 진행바(tqdm 無, 수동 `\r` 바)로 전 9펀드 거래내역+Brinson 디폴트 선계산.
- `scripts/launch_dashboard.bat`: daily-update 질문 직후 `[4/5] python -m api.warmup_cli`(블로킹)
  → 완료 후 브라우저. `OCIO_WARMUP_ON_STARTUP=false`(서버 중복 워밍업 방지). **.bat 은 CRLF·ASCII 유지**.
- 브라우저 재계산: fetchBrinson 타임아웃 30s→**120s**, BrinsonTab 부정형 LoadingBar("재계산 중…").
- ⚠️ 워밍업 시간: brinson 콜드 펀드당 ~1–2분(FoF 더), 9펀드 블로킹이면 길다. 첫 스텝 느림=편입종목 콜드 DB조회 ~7s(임포트 0.8s 아님).

### 일별 비중추이(영역차트) 마커 + 영업일 필터
- `load_weight_trade_markers` 신설 — (date,key) 순매수(억). **BA정산 제외**. WeightHistoryResponseDTO.markers.
- 영역차트: 삼각형 마커(시각, hoverinfo skip) + **거래 요약을 x-unified 툴팁 최상단 별도 줄**(데이터 배열 끝 trace=역순 최상단, y=100, 투명마커=dot제거). 매수=빨강▲/매도=파랑▼ `<span color>`, 건별 줄바꿈, 매수먼저→금액내림차순.
- 영역 fill 톤 0.65. 영업일 필터: `load_business_days_set`(DWCI10220 hldy_yn='N') → 주말·공휴일 보유스냅샷 제외.
- 종목수익률 차트: 같은 날·같은 방향 거래 **합산**, BA정산 제외.

### 성과분석(Brinson) 탭 개편
- **BM기여 경로의존 분해**(`compute_brinson_attribution_v2`): `bm_daily×weight×누적_{t-1}` → **합=period_bm_return**(기존 BM비중×BM수익률 산술합 불일치 해소). cost 잔차는 유동성및기타 귀속. pa_df 'BM기여' 컬럼 + DTO `bm_contrib`.
- BrinsonTab: AP비중 옆 `(±%p vs BM)`, AP수익률/BM수익률 컬럼 삭제, BM기여=백엔드값.
- **BM/SAA 구성 표**(표0): `bm_source`('BM'|'SAA'|'none') + `bm_components`. BM=FUND_BM 컴포넌트(지수·목표비중·지역/헤지), **BM 없는 6펀드=SAA(FUND_MP_DIRECT/MAPPING) 목표비중**. SAA는 비중비교만(인덱스 수익률 정의 없어 기여분해 불가). 대체투자→대체·유동성→유동성및기타 정규화.

### 다음 세션 추가 작업 (사용자 지시 2026-06-17, 미구현)
1. **거래내역 탭 세부내역 접기**: 일별 거래 표를 숨김+"세부내역" 타이틀+"열기" 토글. 표 위에 **종목별 매수/매도/순매수(기간 합계)** 요약.
2. **마스터 토글(자산군↔종목)**: 현재 영역차트에만 있는 asset/security 토글을 **탭 전체(mother)** 로 승격 → 거래내역·일별비중추이·수익률차트 모두 동일 기준 적용.
3. **성과분석 표0 간소화**: 컬럼 = 자산군 / SAA(BM) ticker / SAA비중 / AP ticker / AP비중. **FX 제외**. (※ "AP ticker" 정의 불명확 — 자산군별 실제 대표 보유종목? 다음 세션 확인 필요.)
4. **성과분석 우측 라인차트**: (a) AP vs BM 누적수익 + 자산군별 기여수익률 선택, (b) 기간별 비중 AP vs SAA 추이.

## 2026-06-19 세션 (거래내역 탭 전면 개편 · 자산군 수익률 차트 · 분류 fix)

거래내역 탭(web/+api) 대규모 개편. 위 B1/B2 완료. (성과분석 B3/B4는 미착수)

### 거래내역 탭 (`TransactionsTab.tsx`)
- **마스터 컨트롤**: 상단에 `기준(자산군↔종목)` 토글 + `기간` 프리셋을 통합 → 거래내역·일별비중추이·종목수익률 **공통 기간**(`chartStart = txnStart`). 비중추이 개별 기간 드롭다운 제거.
- **설정후 프리셋**: 거래내역 기간 + 차트 기간에 "설정후"(inception~) 추가. inception=`useFunds` 메타.
- **거래내역 표**: 요약(좌)+세부내역(우) side-by-side, 높이 매칭(요약 높이=세부 기본, "펼치기"로 전체). 요약 컬럼=자산군→종목명, **자산군순→순매수 내림차순** 정렬. 세부=날짜desc, 자산군→종목명.
- **종목 수익률 드롭다운**: 현재 보유 + **과거 편입(현재 미보유)** optgroup 하단 추가 (`securities?start=`, `currently_held` 플래그).

### 자산군 분류 fix (`_classify_6class`)
- 거래 분류가 `AST_CLSF_CD_NM=''`로 호출 → KR상장 해외ETF(ACE 미국S&P500 등) 유동성 오분류. **universe DB(방법3) 1순위 조회** 추가(source of truth, `_load_universe_class_map`). 거래·보유·편입이력 일괄 보정.

### 자산군 수익률 차트 (자산군 모드)
- 일별 비중 × 종목가격 **바스켓 수익지수**(클래스 내 정규화 Σwᵢ·rᵢ/Σwᵢ, start=100). `load_asset_class_return_index` + `_load_scip_prices_batch` + `GET /funds/{code}/asset-class-return`. 종목 차트(`SecurityReturnChart`) 재사용.
- 편입비중 보조축 = **종목별 stacked 색상 영역**. 툴팁 종목별 분해(`weight_components`/`trade_components`).

### 차트 공통 (`SecurityReturnChart`/`WeightAreaChart`)
- 두 차트 **x축 날짜 정렬**(공통 `xRange` + l/r margin 고정), **legend 상단**.
- 툴팁 통일: x-unified **composed-text**(색상 ■ swatch, 0% 숨김, 인접일 누수방지, `hoverlabel align:left`). 지수 우측 `(+%)` 시작대비. 거래 마커 `[c#]`식 누수 fix.
- 종목수익률: 드래그 줌 시 **y auto-fit**, **변화율 측정** 버튼(드래그=구간 %변화율 markup ↑/↓).

### 기타
- `report_service._build_linked_market_enrichment`: 펀드 운용보고 "참고 시장 판단 근거" evidence를 stored→**read-time `_resolve_citations`** 로 복원(신규 _market 8기간 빈칸 fix). 관련 [[reference_report_enrichment_readtime]].
- 펀드 코멘트 56건(8기간×7펀드) Opus4.8 재생성+승인(data/ gitignore).

## 2026-06-22 세션 (거래내역 해외종목 원화 환산)

### 해외 종목 매매금액 원화 환산 (`load_fund_trade_detail`)
- 기존 `금액(억)=TRD_AMT/1e8` 은 해외종목 `TRD_AMT` 가 **외화단위(USD/HKD/EUR/…)** 라
  억 기준 ~0 으로 표시되던 버그. **행별 실제 체결환율**(`KRW_STL_AMT/STL_AMT`)로
  매매금액을 원화 환산. 국내(KRW/NULL)는 `TRD_AMT` 가 이미 원화라 그대로.
  결제금액=0(예수금 등 정산성)인 해외행은 `KRW_STL_AMT` 직접 사용. **통화 무관**
  (FX rate 조회 불필요 — 행별 결제환율이 곧 통화별 환율).
- SELECT 에 `STL_AMT`, `KRW_STL_AMT` 추가. 단일 소스라 세부내역·요약(종목별 순매수)·
  비중차트 마커·종목수익률 마커 **전부 일관 원화**로 전파.
- **캐시**: `db_cache.TRADES` 스펙에 두 컬럼 추가 + 테이블명 `trades`→`trades_v2`
  (외화단위로 박힌 기존 캐시 폐기 위해 콜드 재조회 강제). 구 `trades` 테이블은 orphan(무해).

### ★ BOS8856(원장 환율) vs 표시 환산값 — 동일한가?
- 검증 결과: 행별 환산환율(`KRW_STL_AMT/STL_AMT`) = **그 거래일의 BOS8856 환율**과 일치.
  대다수 **거래기준율(최종)**, 일부 종목만 **시초(매매기준율 시초)**.
  (예 2026-06-04: 284/285건 = 거래기준율 1,529.7, 1건만 시초 1,515.6.)
- **그럼에도 "참고값"인 이유** (사용자 설명 2026-06-22): 해외는 실제 **USD 로 매매**되고,
  원화 **환전은 운용역 재량의 별도 이벤트**(자금 유출입 시점·필요액에 맞춰 환전)라
  거래 1건당 환율과 1:1 대응하지 않는다. 따라서 표시 원화금액은 *거래일 환율로 환산한
  참고값*이며 펀드가 실제 들인/회수한 원화(환전 손익 반영)와는 차이가 있을 수 있다.
- UI 주석: `TransactionsTab.tsx` 거래내역 헤더 아래 안내문구로 명시.

## 2026-06-22 세션 (성과분석 Brinson — 수익률 분석 패널 + SAA 벤치마크 + proxy/drift)

### 수익률 분석 패널 (`BrinsonTrendPanel.tsx`)
- 자산군별 기여수익률 표 아래 "수익률 분석" 패널. **전체/Allocation/Selection 라디오**(헤더 우측)
  + 자산군 드롭다운(legend 에 BM 지수명 표기).
- 전체: AP·BM 누적수익 + 초과(영역). 자산군 선택 시 누적기여 + 비중 vs BM.
- Allocation/Selection: **단일 이중축**(영역=차이 좌축 base / 라인=수익률 우축 overlay,
  라인이 영역 앞에 렌더). 0점 동기화(`alignZero`). BM=갈색 실선, AP=남색, 영역=하늘 파스텔.
  경로적분(daily) 힌트 표기 — 끝점 곱과 부호 다를 수 있음.
- 백엔드 출력만 추가(R-락 불변): `daily_brinson` 에 `ap_cum/bm_cum`, 신규 `daily_class`
  (자산군별 일별 AP/BM 비중·누적기여·실제수익률 `ap_ret_cum/bm_ret_cum`).

### SAA 벤치마크 DB 테이블 (BM 없는 펀드 AP vs SAA 분해)
- **`solution.saa_bm_components`** (리밸 날짜 버전형). `tools/setup_saa_components.py` 로 적재
  (08N33/08N81/08P22 — 사용자 제공, 08N81 라벨 오타 교정). 스키마: rebal_date, portfolio,
  fund_cd, dataset_id, dataseries_id, region, weight(%), hedge_ratio, biz_day_adj, name …
- `load_saa_components(fund, as_of)`: ≤기간말 최신 리밸 컴포넌트 → **FUND_BM 와 동일 구조**.
  `compute_brinson_attribution_v2` 의 `bm_info` 주입점(`FUND_BM.get() or load_saa_components()`)
  → SAA 도 BM 경로로 수익률/기여/Allocation/Selection 분해. `_build_bm_meta` SAA-DB 분기.
- `_map_bm_component_to_asset_class`: HY→해외채권, Gold→대체, EM Gov Bond→해외채권 패턴 추가
  (골든 BM 펀드엔 해당 이름 없어 불변).
- ★ SAA 컴포넌트 자산군명 정규화(대체투자→대체, 유동성→유동성및기타) — 표0 중복행 fix.

### proxy 옵션 + 비중방식(고정/drift) — `saa_mode` 4값
- **소스 × 비중 직교 토글** (BrinsonTab). `saa_mode` = {auto, auto_drift, proxy, proxy_drift}.
  소스: 등록 SAA(auto) / proxy. 비중: **fixed=constant-mix(매일 목표비중 리밸)** /
  **drift=buy-and-hold(리밸 target 에서 인덱스 수익률대로 비중 표류)**. 소스 토글은 SAA 펀드만,
  비중 토글은 BM 펀드 포함 전체.
- **proxy**: 안전자산(채권 ex-HY·EM) → KAP All(257/9), 나머지 → MSCI ACWI
  (35/15 ex_KR T-1×USDKRW). `_build_proxy_bm_info`. **2026-07-03 사용자 지시**: 비중 = **등록
  SAA(saa_bm_components) 리밸 비중의 주식/채권 매핑 고정값** (08P22=75.8/24.2, R 프로덕션
  08P22_BM 일치. HY·EM 채권은 위험자산 측). 채권 인덱스도 KIS 종합채권(188/33, 6/23 지시)에서
  KAP All 로 재변경. 등록 SAA 없는 펀드만 기존 **투자개시일 AP 보유** 동적 계산 fallback
  (현금-only/정산 과도기 스냅샷 스킵: 비유동성≥50%·유동성≤30%).
- **drift(buy-and-hold)**: compute 의 BM 비중을 `bm_w_daily`(일별 dict)로 전환. fixed=상수
  broadcast(=기존 스칼라와 수치 동일 → **골든 18/18 불변**). drift=리밸 target × 인덱스 누적_{t-1}
  / Σ 정규화. FX 오버레이는 해외주식(unhedged) 표류 추종. `saa_mode` 캐시키(‘auto’는 기존 파일명 유지).

### 검증 / 미해결
- 골든 18/18 PASS(BM 펀드 불변, 다회 재확인). 08P22 AP 7.61 vs SAA 1.17(등록)/13.88(proxy).
  08N33 등록 SAA fixed 4.15 vs drift 5.49(외화 winner 비중 표류 상승).
- drift 안전자산은 국내채권 일별비중 기준(현 SAA 펀드 해외채권=HY/EM 제외 대상이라 일치).
  투자등급 해외채권 보유 펀드 생기면 일별 종목식별 확장 필요.
- BM(FUND_BM) 은 하드코딩 유지(테이블 미이전, 골든 안전). 필요 시 테이블 통합 가능.

## 신한라이프 월간보고 — 2JM23 데이터 엑셀 (2026-08-06)

★ **PPT COM 치환기는 폐기**했다(2026-08-06 사용자 지시). 발송본 PPT 는 그대로 쓰고,
표 값은 `tools/shinhan_monthly_excel.py` 가 만드는 **엑셀에서 블록 복사 → PPT 표에
붙여넣기** 한다. COM 자동화는 서버에 PowerPoint 가 떠야 했고 수 분 걸렸으며 DRM
래핑까지 겹쳐 취약했다. 빌드 49s (PA 3회).

**시트 2개** — `Comment` (승인 코멘트 ③/⑥) · `자산배분현황` (3p 자산배분 + 4p 주요 투자종목).

### ★ 붙여넣기 규약 — 열·행 순서를 발송본과 1:1 (2026-07 발송본 COM 덤프로 확정)

| 표 | 열 | 자동 산출 | 수기 |
|---|---|---|---|
| 3p 자산배분 (8열 14행) | 자산군·세부자산군·**TAA(%)**·당월말·전월말·변화·기여도·**비고** | **D~G 연속** | C, H |
| 4p 주요 투자종목 (7열) | 순번·종목명·세부자산군·비중·월수익률·연초후기여도·**향후 관리 방안** | **A~F 연속** | G |

자동 산출 열이 **연속**이라 `D:G` / `A:F` 블록만 복사하면 수기 열을 덮지 않는다.

- ⚠ **행 순서가 곧 정확도.** `SHINHAN_PPT_SKELETON` 의 채권 4행을 발송본 순서
  (하이일드/**미국장기**/**한국중기**/한국장기)로 교정했다 — 종전 상수는 미국장기와
  한국장기가 뒤바뀌어 있었다. PPT 치환기는 **라벨 매칭**이라 무해했지만 엑셀은
  값이 엉뚱한 행에 붙는다. `test_skeleton_row_order_matches_sent_report` 가 고정.
- ⚠ 값은 **문자열**로 쓴다(`39.45%`, `29.82`). 숫자+표시형식이면 '값만 붙여넣기'
  에서 원본 숫자가 튀어나와 발송본 표기와 달라진다.
- 표② 운용현황(펀드수익률·변동성·BM 2종)은 **엑셀 범위 밖** — 전량 수기.
  `FEE_ANNUAL_PCT`(0.7225) 는 빌더에서 사라졌고 검증값으로 `test_fund_meta_fee` 에만 남는다.

### 배선 = SAA 펀드 엑셀과 동일 경로

전용 엔드포인트 3종(`/shinhan-ppt` get·generate·download)을 걷어내고
**`_EXCEL_SPECS['2JM23']`** 에 얹었다.

- **② 보고서 승인 시 재생성** → 승인 버튼 우측 `신한라이프 엑셀 다운로드`
  (`GET /report/excel`). 재생성은 **승인을 다시 누르면** 된다(approve 는 멱등).
- ⚠ `_EXCEL_SPECS` 의 `name` 은 `shinhan_monthly_excel.OUT_NAME` 과 같아야 한다 —
  admin 은 경로를 넘겨주지만 CLI 는 기본 경로에 쓰므로, 어긋나면 두 산출물이 갈린다.
- 빌더 경고는 `WorkflowStageDTO.build_warnings` 로 **승인 응답에만** 실린다
  (GET workflow 는 빈 리스트) — 화면을 새로 열면 사라지므로 승인 직후에 확인할 것.
- 코멘트 승인본 게이트는 `_build_excel` 안 (Comment 시트 소스).

### 검증

- 2026-06 발송본 대조(PPT 시절): 표④ 9행 **전 행 일치** · 표⑤ **전 항목 일치** ·
  표② 1M·3M·6M·YTD **정확 일치**.
- 2026-08-06 엑셀 전환: 2026-07 발송본 COM 덤프와 대조 —
  자산배분 **13 데이터행**(소계·총계 포함) · 종목 **6행** 전부 값·행순서 일치.

### 확정된 규약

- **전월말 비중 = 전월 구간 PA `sec_summary.순자산비중_끝`** 을 TAA 집계
  (미국 성장주 41.21 = 나스닥100 31.36 + S&P500G 9.85). 당월 PA 의
  `순자산비중_시작`(0.269)이 **아니다** — R plot 은 전월말 스냅샷 행을 따로 붙인다.
- **보수 환원** = BOS3203 컴포넌트 합 **7.225 → 연 0.7225%** 일할 복리.
  (구 버그 — `load_fund_meta().fee_bp` 가 `MAX(apply_frdate)` 한 날짜만 걸러
  A50 단독 0.16 을 돌려주던 문제는 **2026-08-06 수정**. 유효기간 필터 + ×10 환산으로
  이제 72.25bp = 0.7225% 를 돌려준다. 아래 §BOS3203 참조.)
- **표② 앵커는 월말 기준**. `relativedelta(months=3)`(6/30→3/30)을 쓰면 3/31 이
  빠져 3개월 수익률이 0.77%p 어긋난다.
- **유동성은 잔여(100−Σ)**. 보유 합이 100 초과면 음수가 되며(결제 시차, 2026-07
  실측 -2.79%) 원장상 정상이지만 발송 전 확인하도록 경고한다.
- **TAA 분류** = `config/taa_classification.py` (136종목). R
  `new_universe_criteria.csv`(CP949) + `데이터 loading 모듈…R` tribble 병합 스냅샷.
  `universe_non_derivative` 방법1~5 로는 만들 수 없다(방법5=지역까지).
  ⚠ R 과 이중 관리 — 신규 편입 시 양쪽 갱신. 미매핑은 경고.
- ~~표④ 행 매칭은 라벨 기준~~ → 엑셀 전환으로 **행 순서 자체를 발송본에 맞췄다**
  (위 §붙여넣기 규약). 라벨 매칭이 감춰주던 순서 불일치가 이제는 그대로 드러난다.

### 미해결

- 표② **1년·설정후** 보수 환원이 발송본과 어긋남(+0.45 / +14.88). 단기 4개 열은 정확.
- 표② **연환산 변동성·BM 2종** 산식 미상 — 발송본 자체가 6M 16.02 vs YTD 11.60 으로
  모순(6월은 동일 기간)이라 특정 불가.
- ⚠ **2026-05 발송본의 표②는 2026-04 기준값**이었다(1M 13.28% = 202604 실측 13.23%).
  대조 기준으로 쓰지 말 것.

---

## ★ 08K88 월간 보고 기간 창 — 달력월 아님 (2026-08-05 사용자 확정)

08K88 만 **전월 마지막 영업일부터(포함) 당월 마지막 영업일 −1영업일까지**.
2026-07 → **6/30 ~ 7/30**, 펀드수익률 **-16.02%**(기준가 6/29 종가 → 7/30 종가).

정의는 **`market_research/core/period_window.py` 단일 소스** — 엑셀(성과분석)과
펀드 코멘트가 같은 함수를 쓴다. 한쪽만 고치면 **같은 보고서 안에서 수익률이
갈린다**: 실제로 엑셀만 먼저 바꿨을 때 엑셀 -16.02% vs 코멘트 -11.17% 로
4.85%p 어긋났다.

| | 달력 7월 (기본) | 08K88 창 |
|---|---|---|
| 구간 | 6/30 종가 → 7/31 종가 | 6/29 종가 → 7/30 종가 |
| 수익률 | -11.17% | **-16.02%** |

차이 4.85%p 의 정체: **6/30(+1.13%) 이 들어오고 7/31(+6.98%) 이 빠진다.**
7/31 은 월말 반등일이라 이 창에서는 펀드의 반등이 제외된다 — 코멘트 서술에
"월말 낙폭 되돌림"을 쓸 때 주의.

- ⚠ 기본 규약과 **반대로** 전월 마지막 영업일 손익을 **포함**한다
  (기본은 `(전월말, 기간말]` 로 제외 — [[reference_pa_period_start_offbyone]]).
- ⚠ `build_brinson(start, end)` 의 `start` 는 **첫 포함일**이지 기초일이 아니다.
  실측: `(7/1, 7/30)` → -16.9648% / `(6/30, 7/30)` → -16.0226%.
- 코멘트 경로는 **BM 로드보다 앞**에서 오버라이드해야 한다
  (`fund_comment_service` §1.5) — `prev_last`/`cur_last` 가
  `_load_bm_returns_for_range` 의 분모·분자라 뒤에서 바꾸면 BM 만 옛 창에 남는다.
- 적용 대상은 **월간만**. 분기·TD 는 무영향. 미등록 펀드도 전부 무영향.

---

## 자산군 시드 — 펀드 코멘트 공통 문단 단일화 (2026-08-05 사용자 지시)

**시장동향·전망 문단을 기간당 1본 만들어 전 펀드가 공유**하고, 펀드는 **보유
자산군 문장만 골라 조립**한다. 미보유 자산군은 **삭제만** 한다(대체 문장 없음).

근거: 2026-07 승인본 실측 — 08N81·08N33·08P22 의 시장동향 1문단과 전망 섹션은
**글자 그대로 동일**했고 금 미보유 08K88 만 금 문장이 빠져 있었다. 실무는 이미
"공통 뼈대 + 미보유 삭제"인데 파이프라인은 펀드마다 LLM 이 새로 써서 매달 손으로
통일해야 했다.

### 워크플로우 (Admin 대상 토글 3단)

```
시장 debate 생성·승인  →  자산군 시드 생성·승인  →  펀드 코멘트 생성
   (_market.final)        (_market.seed.json)      (보유 자산군만 조립)
```

시드는 **승인본만** 쓴다(`load_approved_seed`). 미승인이면 종전대로 LLM 이 전문을
쓴다 — 기능 무중단이지만 펀드 간 편차가 남으므로 Admin 이 배지로 경고한다.

### 4개 스테이지

| 스테이지 | 파일 | 내용 |
|---|---|---|
| 1 | `debate_engine._synthesize_debate` | synthesis **Step 3** 신설 → `asset_outlook{자산군: 전망문장}`. 본문 `structure_instruction` 은 **불변**(골든·client 노출) — 별도 필드로 낸다 |
| 2 | `report_store.approve_and_save_final` | `asset_outlook`·`asset_movement_*`·`disagreements` **if-present 보존**. 종전 고정 12키라 승인 순간 버려졌다(2026-07 실측 draft amc 5개 → final 0개) |
| 3 | `report/market_seed.py` | 승인 `_market` 본문 → LLM **1회**(기간당, 펀드 수 무관)로 자산군별 압축. **의미 기반 추출** — 문단 위치 파싱 아님(debate 문단 구조는 프롬프트가 보장 안 함) |
| 4 | `comment_engine` + `fund_comment_service` | LLM 은 **펀드 고유 블록만** 생성(`<<<성과>>>` 등), 공통 문단은 코드가 조립 |

### 포맷별 슬롯 (2026-07 승인본 원문에서 그대로 뜸)

| 포맷 | 시장동향 | 전망 | LLM 블록 |
|---|---|---|---|
| A | `■ 월간 시장동향…` 문단1 | `■ 향후 시장전망` | 성과 · 매니저 |
| C (07G04) | `[운용경과] 1. 시장 동향` | `[운용계획] 1. 시장 전망` | 성과 · 포지션 |
| D (2JM23·4JM12) | `1. 운용성과 요약` 문단1 | `시장환경 분석:` | 성과 · 계획 |
| K (07G07) | 첫 불릿 | B33 첫 불릿 | 매매 · 성과 · 계획 |

들여쓰기까지 승인본과 동일(A=탭, C=한 칸, D=없음). `test_market_seed_assembly.py`
가 골격을 라인 단위로 고정한다.

### ★ 자산군 어휘 2종 — `core/asset_class.py`

같은 자산군이 소스마다 다른 라벨로 온다. **이걸 안 맞추면 보유 판정이 틀린다.**

| 소스 | 대체자산 | 현금성 |
|---|---|---|
| PA·보유 (`compute_single_port_pa` 방법3) | `대체` | `유동성및기타` |
| 거래 (`load_fund_net_trades`) | `대체투자` | `유동성` |

종전 `fund_comment_service` 의 `all_asset_classes` 는 **거래 어휘** 상수인데
`holdings_end` 는 **보유 어휘**로 와서, 금을 *보유만 하고 매매하지 않은* 펀드는
`대체투자` 가 항상 "미편입" 판정이었다. 08N81 은 7월에 금을 *매매* 해서 우연히
정상 동작했다. → canonical = **PA·보유 어휘**로 통일.

### 분량 예산 (2026-07 08N81 승인본 실측)

시장동향 653자(총론 132 + 자산군 66~144) · 전망 545자. 조립이 결정론적이라
**시드 길이가 곧 최종 분량**이므로 `market_seed.BUDGET` 이 자산군당 cap 을 걸고,
초과 시 **1회 재압축**한다. 규칙 문장만으로는 안 지켜졌다(실측 1.5배 초과) —
JSON 스켈레톤에 자수를 박아야 지켜진다.

### 서술 순서 (섹션마다 다름)

- 시장동향 `MARKET_ORDER` = 해외주식→국내주식→해외채권→국내채권→대체→FX
- 전망 `OUTLOOK_ORDER` = 국내주식→해외주식→국내채권→해외채권→대체→FX

전망은 **첫 문장에만 기간 라벨**("8월 …")을 붙인다 — 시드에는 라벨 없이 저장하고
`assemble` 이 붙인다. 6문장이 모두 "8월"로 시작하면 발송본과 다르다.

### 검증 (2026-07 재현)

7월 `_market` 승인본으로 시드 생성 → 08N81(전 자산군)·08K88(금 미보유) 조립:
**공통 문장 전부 글자 그대로 동일**, 금 문장만 정확히 삭제. 시장동향 761/712자,
전망 664/561자. 운영 `2026-07` 산출물은 **미변경**(scratch period 로 격리 실행).

---

## 2JM23 코멘트 형태 override — 시장동향 400자 · 성과 1문장 (2026-08-06 사용자 지시)

신한라이프 발송본은 슬라이드 텍스트 상자가 좁아 공통 시드 문단(600~700자)이 통째로
안 들어간다. **2JM23 만** 아래 두 가지를 적용한다 — 설정은
`core/constants.py` (`MARKET_PARA_CAP` · `FIXED_PERF_SENTENCE_FUNDS` ·
`PERF_SENTENCE_EXCLUDE`). 미등록 펀드는 전 경로 불변.

### ① 시장동향 400자 캡 — LLM 재압축

`market_seed.compress_market_paragraph(text, cap)`. 문장 단위로 잘라내면 뒤쪽
자산군(FX 등)이 통째로 사라져서, **자산군을 모두 살린 채 다시 쓴다**(사용자 선택).

- 캐시 키가 기간이 아니라 **원문 해시 + cap** → 재조립해도 LLM 1회. 시드 재승인 시 자동 무효화
- ⚠ **"N자 이하"만으로는 안 지켜진다.** 실측 735→428자(초과 거부). 문장 수를 세어
  **문장당 자수 예산**을 박고 **1회 재시도**를 붙여야 통과한다 → 369자.
  시드 생성의 `_RULES` 와 같은 교훈이다.
- 실패하면 **원문 유지 + 경고**. 기계적 절단으로 자산군을 유실시키는 것보다,
  길게 두고 Admin 이 손으로 줄이는 편이 안전하다. `stop_reason == max_tokens` 도 거부.

### ② 성과 문단 = 코드 고정 생성

`comment_engine.build_perf_sentence()`. 순수 수치 나열이라 LLM 이 개입하면 오기·표현
흔들림만 생긴다. **해설 문장을 붙이지 않는다**(사용자: "여기까지만").

```
7월 중 펀드는 -8.55%의 성과를 기록하였으며, 자산군별 성과기여도는
국내주식 -3.07%, 해외주식 -4.55%, 국내채권 -0.28%, 대체 -0.55% 이었습니다.
```

- ★ 자산군은 **고정 순서**(`CANONICAL_CLASSES`) — **기여도 크기순이 아니다.**
  발송본 3건(2·5·6월) 대조 결과 크기순이 아니었다(6월만 우연히 둘 다 만족).
  크기순이면 매달 자산군 순서가 뒤바뀐다.
- **유동성및기타·유동성·보수비용 제외** → 기여도 합이 펀드 수익률과 어긋나지만 발송본 관행
- 라벨은 **PA 어휘 '대체' 유지** — 발송본은 '원자재'지만 대시보드·엑셀과 용어를 맞춘다
  (2026-08-06 사용자 확정)
- `(보수 차감전)` 문구 없음 — 사용자 제시 양식 그대로
- 수치가 없으면 `None` → LLM 블록을 그대로 쓴다(무중단)

---

## 코멘트 기간 유형 5종 — 월간/분기/QTD/HTD/YTD (2026-07-31 사용자 지시)

Admin `코멘트 생성·관리` 의 기간 선택이 **유형 select + 기간 select** 2단으로 바뀌었다.
종전 드롭다운은 직전월부터 6개월(당월 제외)이라 **월중에 당월을 고를 수 없었다**.

### period 키 규약 (저장 폴더명 = `report_output/{period}/`)

| 유형 | period 키 | 범위 | 목록 |
|---|---|---|---|
| 월간 | `2026-07` | 전월말 ~ 월말 (진행 중이면 **MTD**) | 당월 포함 7개 |
| 분기 | `2026-Q2` | 전분기말 ~ 분기말 | 마감된 직전 4개 |
| QTD | `2026-Q3.QTD` | 직전 분기말 ~ 최신 적재일 | 당분기 1개 |
| HTD | `2026-H2.HTD` | 직전 반기말 ~ 최신 적재일 | 당반기 1개 |
| YTD | `2026-YTD` | 전년말 ~ 최신 적재일 | 당해 1개 |

TD 계열은 확정 기간 키(`2026-Q3`)와 **폴더가 분리**돼 마감 산출물을 덮지 않는다.
같은 분기 안에서 재생성하면 같은 키를 갱신 = 항상 최신 TD 1본.

### 종료일 clamp (MTD 의 핵심)

⚠️ `DWCI10220` 영업일 캘린더에는 **미래 영업일도 등록**돼 있다(2026-12-31 까지).
clamp 없이 당월을 넣으면 종료일이 미래 월말로 잡혀 데이터 없는 날짜를 참조한다.
→ `comment_engine.load_latest_data_date()`(= `DWPM10510` MAX(STD_DT), 통상 T-1)로
`_resolve_dates` 가 종료일을 clamp. 마감된 과거 기간은 기간말 < 최신적재일이라
**clamp 무영향 = 기존 산출물 불변**(2026-06 은 20260529~20260630 그대로).
시작일 ≥ 종료일이면(아직 시작 안 한 기간) `None` 반환.

### 시장 코멘트(`_market`) 게이트 — TD 는 승인본 재사용

펀드 코멘트 생성은 같은 기간 `_market` 승인본을 요구하는데(없으면 409), TD 기간으로는
시장 debate 를 돌리지 않는다(사용자 확정). `_resolve_market_payload` 가:
1. 같은 키 승인본 → 있으면 그대로 (기존 경로 100% 불변)
2. TD 면 기간 전체를 덮는 상위 키(`2026-Q3` / `2026-H2`) 승인본 → 있으면 단독 사용
3. 없으면 기간 내 **월간** 승인본을 시간순으로 병합

병합 시 본문은 `[2026-01]` 식 기간 라벨을 붙여 잇고, **`[ref:N]` 은 제거**한다 —
기간마다 독립 번호라 합치면 충돌하고 병합본 기준 evidence 가 없어 복원 불가.
전망성 항목(consensus/tail_risks/disagreements/asset_movement_*)은 **최근 기간 것**.

### 병합본 압축 — 기간 내러티브 재구성 (`market_digest.py`)

월별 나열을 그대로 넘기면 6~12개월치가 1.3~2.6만자라 펀드 코멘트 프롬프트를
압도한다. **8,000자 초과 시** Sonnet(`claude-sonnet-4-6`)이 월별 나열을
**기간 전체를 관통하는 시장 내러티브 1본**으로 재구성한다 (본문 생성은 Opus 4.8
유지 — [[reference_llm_model_config]]).

- 임계 8,000자 = 월간 1건 ≈ 2,100자 기준 **QTD(3개월 ≈ 6.4천자)까지는 원문 그대로**,
  HTD/YTD 부터 압축.
- 캐시 `.cache/market_digest/{sha}.json` — 키가 기간이 아니라 **원문 해시**라
  전 펀드가 공유하고(TD 1기간당 LLM 1회), 시장 코멘트 재승인 시 자동 무효화.
- ⚠️ `stop_reason == 'max_tokens'` 면 **채택도 캐시도 하지 않고** 원문 병합본을 쓴다.
  실측에서 cap 2,500 이 목표 3,000자보다 작아 마지막 문장이 잘렸다
  ([[reference_debate_token_cap]] 의 cap 잘림 오염과 같은 함정) → cap 4,000.
- LLM 실패·임계 미만은 전부 `None` → 원문 유지. 압축은 **기능 무중단 부가 단계**.

### 구현 위치

- `market_research/report/comment_engine.py` — `load_latest_data_date()` 신설
- `market_research/report/fund_comment_service.py` — `_resolve_dates` 5-mode + clamp, `_month_last_bday`
- `api/routers/admin_funds.py` — `_PERIOD_PATTERNS` / `PERIOD_RE` / `_market_source_periods` /
  `_merge_market_payloads` / `_resolve_market_payload`
- `api/routers/report.py` — 펀드 보고서 조회 pattern 에 TD 추가 (client 노출용).
  시장 코멘트 조회(`/market-report`)는 TD 생성이 없으므로 **그대로**
- `web/src/tabs/AdminCommentWorkflowPanel.tsx` — `KINDS` / `buildPeriodOpts`

### 검증 (2026-07-31)

- `_resolve_dates` 7케이스: MTD 6/30~7/30 · 2026-06 골든 불변 · Q2 골든 불변 ·
  QTD/HTD 6/30~7/30 · YTD 2025-12-31~7/30 · 미래 월 None
- YTD 병합 실측: 2026-01~06 6건 → 12,822자, `[ref:N]` 0건
  → 압축 후 **2,556자(20%)·4문단**, 소요 54s / 캐시 2회차 0.01s
- api 219 / mr 842 = **1,061 PASS** (기존과 동일), `tsc --noEmit` 클린
