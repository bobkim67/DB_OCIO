# React + FastAPI 점진 전환 아키텍처 보정안

> 기존 Streamlit 기반 `DB_OCIO_Webview`를 React + FastAPI 구조로 점진 전환하기 위한 아키텍처 보정 및 Week 1 착수안.
> 작성: 2026-04-22. 본 문서는 LLM 리뷰 후 revise 판정을 받아 실제 착수 단계로 진입한 버전임.

---

## 리뷰 판정 반영 (2026-04-22)

- 판정: **revise → 착수 승인**
- 치명 리스크 3개(streamlit 의존 / CORS 오류 / service 탭복제)는 커밋 2~3에서 차단
- Week 1 범위는 "Overview 설정후 수익률 1개 카드 + NAV 시계열"로 축소
- auth/JWT/BM 결합/YTD/MDD/변동성/placeholder 탭 생성 **금지**
- 적용 원칙: `allow_credentials=False`, `allow_methods=["GET","POST","OPTIONS"]`,
  async def 금지(sync def only), `datetime.now(timezone.utc)` 사용,
  Envelope Generic 금지(구체 alias `FundListResponseDTO`), `BaseMeta` +
  `SourceBreakdown` 으로 부분 fallback 표현

### Day 0 검증 결과 (2026-04-22 grep)

| 항목 | 결과 | 대응 |
|------|------|------|
| `modules/data_loader.py`에 streamlit import | **없음** (grep 결과 0건) | api/.venv에 streamlit 불필요. 그대로 import 가능 |
| `modules/auth.py`에 streamlit import | `import streamlit as st` (line 5) | **FastAPI는 `modules/auth.py`를 import하지 않는다**. Streamlit 전용 모듈로 격리. Week 1 auth 제외 원칙과 일치 |
| `config/funds.py`에 streamlit import | **없음** | 그대로 import 가능 |
| `_FUND_INCEPTION_BASE` 선언 위치 | `modules/data_loader.py:1030`에 모듈 레벨 dict (`{'4JM12': 1970.76}`) | `_` prefix지만 `tabs/overview.py`, `prototype.py`에서 이미 직접 import 중. `api/services/overview_service.py`도 동일 패턴으로 import |
| `get_connection(db_name: str)` | `modules/data_loader.py:25`, 반환 타입 `pymysql.connect(..., cursorclass=DictCursor)` | `/health`의 DB ping에 그대로 사용. `conn.cursor().execute("SELECT 1")` |
| `load_fund_nav_with_aum(fund_code: str, start_date: str = None)` | `modules/data_loader.py:1035`, 반환 `DataFrame[기준일자, MOD_STPR, NAST_AMT, AUM_억, DD1_ERN_RT]` | overview_service에서 `기준일자` + `MOD_STPR` + `NAST_AMT` 3개 컬럼 사용 |
| `DB_CONFIG` | `modules/data_loader.py:18` 모듈 레벨, host/user/password/charset | api/settings.py에 **중복 선언 금지**. data_loader가 가진 값을 그대로 활용 |

**결론**: streamlit 의존 없음 → api/.venv에 streamlit 불설치로 진행. `modules/auth.py`는 import 대상 아니므로 무관. `_FUND_INCEPTION_BASE`는 public처럼 import 가능 (기존 패턴 그대로).

---

## 1. 총평

기존 초안의 핵심 문제는 **FastAPI를 너무 넓게 잡은 것**이었다. batch/CLI 경계, Brinson 계산 API, 자동 리뷰 hook 이전, Plotly 서버 렌더링까지 Week 1~2에 같이 흡수하려 했는데, 운영 중인 Streamlit 앱 안정성을 해칠 위험이 크다. 본 보정안은 다음을 반영한다:

- **FastAPI = 읽기 API + 극히 제한적 트리거**. market_research batch / `report_cli.py` / debate 실행은 **모두 외부 유지**. FastAPI는 `report_output/*.final.json` 같은 결과물 조회만.
- **Streamlit tabs 즉시 삭제 금지**. 탭별로 React 구현이 "사용자 합격"한 뒤에야 Streamlit 쪽 제거.
- **services = 도메인 기준**(fund_query / holdings / performance / report_read / macro). router는 탭 대응 OK, service는 1:1 복제 금지.
- **Brinson 특별 취급**. 가장 마지막. mapping_method는 내부 자동 선택(`FUND_DEFAULT_MAPPING_METHOD` 재사용). 프론트는 선택 파라미터(방법1~4 override)만 optional로 노출.
- **모든 응답에 BaseMeta**(`as_of_date`, `source`, `is_fallback`, `warnings`, `generated_at`). React는 DB/mockup 구분을 UI에서 표시.
- **Week 1 = Overview 1개 탭만**. `/health`, `/funds`, `/funds/{code}/overview` + React 기본 골격.

---

## 2. 수정된 디렉토리 구조

```
DB_OCIO_Webview/
├── api/                              ← NEW: FastAPI (전용 venv)
│   ├── .venv/                        ← api 전용 (pip/uv)
│   ├── pyproject.toml                ← uv pyproject (pydantic 2, fastapi, uvicorn)
│   ├── requirements.txt              ← 배포용 lock (pyproject와 병행 유지)
│   ├── README.md                     ← api 전용 실행 방법
│   ├── main.py                       ← FastAPI 엔트리 (CORS, router 등록, lifespan)
│   ├── settings.py                   ← DB/JWT/CORS 설정 (pydantic-settings)
│   ├── deps.py                       ← DI: get_current_user, get_db (옵션)
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── password.py               ← 기존 modules/auth.py 로직 이식 (해시 비교만)
│   │   └── token.py                  ← JWT 생성/검증 (최소 HS256)
│   ├── routers/                      ← 탭 대응 OK (얇은 층)
│   │   ├── __init__.py
│   │   ├── health.py                 ← GET /health
│   │   ├── auth.py                   ← POST /auth/login, GET /auth/me (Week 1 단순 stub)
│   │   ├── funds.py                  ← GET /funds, GET /funds/{code}
│   │   ├── overview.py               ← GET /funds/{code}/overview  (Week 1)
│   │   ├── holdings.py               ← Week 3
│   │   ├── macro.py                  ← Week 3
│   │   ├── report_read.py            ← Week 4 (final.json viewer)
│   │   └── brinson.py                ← Week 5+ (마지막)
│   ├── services/                     ← 도메인 단위 (탭 복제 금지)
│   │   ├── __init__.py
│   │   ├── fund_query_service.py     ← FUND_META/FUND_GROUPS → DTO
│   │   ├── overview_service.py       ← NAV/BM/MDD/메트릭 카드 조립 (읽기 전용)
│   │   ├── holdings_service.py       ← 8분류/종목별/look-through
│   │   ├── performance_service.py    ← Brinson 래퍼 (후순위)
│   │   ├── report_read_service.py    ← report_output 파일 읽기
│   │   └── macro_service.py          ← load_macro_timeseries 래퍼
│   ├── schemas/                      ← Pydantic DTO (응답 + 공통 메타)
│   │   ├── __init__.py
│   │   ├── common.py                 ← BaseMeta, Envelope, ErrorDTO
│   │   ├── fund.py                   ← FundMetaDTO, FundSummaryDTO
│   │   ├── overview.py               ← OverviewResponseDTO, NavPointDTO, MetricCardDTO
│   │   ├── holdings.py               ← (Week 3)
│   │   ├── report.py                 ← (Week 4)
│   │   └── brinson.py                ← (Week 5+)
│   ├── cache.py                      ← 간단 in-memory TTL (Redis 미도입)
│   └── tests/
│       ├── test_health.py
│       └── test_overview_smoke.py
│
├── web/                              ← NEW: React + Vite + TS
│   ├── package.json
│   ├── vite.config.ts                ← proxy /api → http://localhost:8000
│   ├── tsconfig.json
│   ├── .env.development              ← VITE_API_BASE=/api
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                   ← Router + QueryClient + AuthGate
│       ├── api/
│       │   ├── client.ts             ← axios 인스턴스 + 인터셉터 (토큰/에러)
│       │   ├── types.ts              ← 수동 타입 (Week 1) → openapi-typescript (Week 2+)
│       │   └── endpoints.ts          ← fetchOverview, fetchFunds 등
│       ├── hooks/
│       │   ├── useAuth.ts
│       │   ├── useFunds.ts
│       │   └── useOverview.ts
│       ├── components/
│       │   ├── layout/
│       │   │   ├── AppShell.tsx      ← 상단바 + 펀드 선택기
│       │   │   └── FundSelector.tsx
│       │   ├── common/
│       │   │   ├── MetaBadge.tsx     ← is_fallback/source 표시
│       │   │   ├── MetricCard.tsx
│       │   │   └── ErrorBoundary.tsx
│       │   └── charts/
│       │       └── NavChart.tsx      ← react-plotly.js
│       ├── pages/
│       │   ├── LoginPage.tsx
│       │   └── DashboardPage.tsx     ← 탭 컨테이너
│       ├── tabs/
│       │   ├── OverviewTab.tsx       ← Week 1 완성 대상
│       │   ├── HoldingsTab.tsx       ← Week 3 placeholder
│       │   ├── BrinsonTab.tsx        ← Week 5+
│       │   └── ReportTab.tsx         ← Week 4
│       └── styles/
│           └── theme.ts
│
├── modules/                          ← 기존 유지 (변경 없음)
├── config/                           ← 기존 유지 (FastAPI가 import)
├── market_research/                  ← 기존 유지 (batch/CLI 경계 보존)
├── tabs/                             ← Streamlit 탭 (점진 축소, 즉시 삭제 X)
├── prototype.py                      ← Streamlit 엔트리 (dual-run 유지)
└── docs/
    └── refactor_plan_react_fastapi.md  ← 이 문서
```

**핵심 원칙**:
- `api/`는 `modules/data_loader.py` 를 import만 하지 **수정하지 않는다**
- `api/`는 `modules/auth.py` 를 **import하지 않는다** (Streamlit 의존). Week 1 auth 제외 원칙과 일치
- `market_research/`를 `api/`에서 import하는 것은 **read-only 파일 조회**에 한함 (`report_output/*.final.json`)
- `api/.venv`와 기존 `C:\Users\user\Downloads\python\.venv`는 **완전 분리**. FastAPI 전용 의존성만 api쪽에 격리

### Week 1 placeholder 금지
아래 파일/폴더는 Week 1에 **생성하지 않는다** (구조도에 있어도 실제로는 만들지 않음):
- `api/auth/` 전체, `api/routers/auth.py`
- `api/routers/holdings.py`, `api/routers/macro.py`, `api/routers/report_read.py`, `api/routers/brinson.py`
- `api/services/holdings_service.py`, `api/services/performance_service.py`, `api/services/report_read_service.py`, `api/services/macro_service.py`
- `api/schemas/holdings.py`, `api/schemas/report.py`, `api/schemas/brinson.py`
- `api/cache.py`, `api/deps.py` (빈 파일도 생성 금지)
- `web/src/pages/LoginPage.tsx`, `web/src/tabs/HoldingsTab.tsx`, `web/src/tabs/BrinsonTab.tsx`, `web/src/tabs/ReportTab.tsx`
- `web/src/components/layout/AppShell.tsx`, `web/src/components/common/ErrorBoundary.tsx`

---

## 3. 책임 분리 원칙

### routers (탭 대응 허용)
- HTTP 관심사만: path parameter 파싱, 응답 status code, 에러 변환
- 비즈니스 로직 없음
- service 호출 → DTO 반환만

### services (도메인 단위)
- `modules/data_loader.py` 함수를 호출
- DataFrame → DTO 변환 (컬럼명 변경/정렬/숫자 포맷 정규화)
- **경계**: service는 DataFrame을 반환하지 않는다. router에는 DTO만 넘어간다.
- **Streamlit render(ctx) 로직 복제 금지**. `tabs/overview.py`의 UI 조립 코드를 service로 옮기지 않고, `modules/data_loader.py`의 순수 함수를 재조립한다.
- 이 경계를 지키기 위해 서비스 함수 시그니처는 `(fund_code: str, start_date: str | None) -> OverviewResponseDTO` 같이 "도메인 + 필터" 수준

### schemas (DTO)
- Pydantic v2 `BaseModel`
- 모든 응답은 **BaseMeta 필드 필수 포함** (상속 or Envelope 패턴)
- 공통 Envelope:
  ```python
  class BaseMeta(BaseModel):
      as_of_date: date | None
      source: Literal["db", "cache", "mock"]
      is_fallback: bool
      warnings: list[str] = []
      generated_at: datetime
  ```
- 주요 응답 DTO는 `meta: BaseMeta` 속성을 직접 가짐 (Envelope 중첩보다 평탄)

### batch/CLI 경계 유지
- `market_research/report/cli.py` — FastAPI가 호출 **안 함**
- `market_research/pipeline/daily_update.py` — FastAPI가 호출 **안 함**
- debate 실행 (`_run_debate_and_save`) — Week 7+ 에만 옵션 검토, Week 1~6 범위 밖
- FastAPI가 제공하는 쓰기/트리거 endpoint는 초기에 **없음**. 읽기만.

### dual-run 운영
- Streamlit: 포트 8505
- FastAPI: 포트 8000 (Week 1은 `--host 127.0.0.1` 로컬바인딩만)
- React dev: 포트 5173
- 내부망 배포: Nginx가 `/` → React build, `/api/*` → FastAPI로 라우팅. Streamlit은 `http://host:8505` 그대로 유지 (별도 링크)
- **탭 이전 완료 기준**: 실사용자(User)가 "이제 React 쪽만 쓴다"고 명시적 승인 → 그 탭만 Streamlit에서 제거

### Week 1 절대 금지
- auth 엔드포인트 / JWT 발급 / 로그인 페이지 / `users.yaml` 이식
- BM 결합 (DT BM, SCIP composite 모두)
- YTD / MDD / 변동성 / 기간수익률 / `period_returns` 필드
- Redis / 분산 캐시 / in-memory TTL shim
- docker-compose / nginx 배포 설정
- placeholder 탭/파일 생성 (`HoldingsTab.tsx` 등)
- Plotly Figure JSON 서버 조립 (React가 데이터만 받아 조립)
- `async def` 라우터 핸들러 (sync def only, pymysql/pandas는 blocking이므로 threadpool 자동 오프로드)
- `allow_credentials=True` CORS (+ `allow_methods=["*"]`)
- batch/CLI 트리거 엔드포인트 (POST/PUT/DELETE 전부 금지)
- DB 접속정보를 `api/settings.py`에 중복 선언 (data_loader의 `DB_CONFIG` + `get_connection` 재사용)
- `datetime.utcnow()` 사용 (`datetime.now(timezone.utc)` 전용)
- Envelope Pydantic Generic 전면 도입 (구체 alias `FundListResponseDTO` 만 허용)

### Brinson 이전 착수 3조건 (전부 충족 전 금지)
1. Overview / Holdings / Report 모두 사용자 "합격" 승인 완료
2. `compute_brinson_attribution_v2` 출력 snapshot이 pytest로 박혀있음 (JSON 직렬화 후 diff 검증)
3. R Excel vs Python 대조 debug 스크립트 보존 (`debug/debug_4JM12_compare.py` 등 최소 2개)

위 3개 중 하나라도 미충족 상태에서 Brinson 이전 착수 금지.

---

## 4. API 설계 초안

### Week 1 (3개 — 축소 범위)
```
GET  /api/health
     → { status: "ok"|"degraded", time: ISO8601, version: "0.1.0",
         db: { status: "ok"|"fail", latency_ms: int } }
     - DB ping 포함. 실패 시에도 200 + status=degraded.

GET  /api/funds
     → FundListResponseDTO { meta: BaseMeta, data: FundMetaDTO[] }
     - FUND_LIST + FUND_META + FUND_GROUPS + FUND_BM + FUND_DEFAULT_MAPPING_METHOD 결합
     - aum 필드 없음 (N+1 방지)

GET  /api/funds/{code}/overview
     → OverviewResponseDTO (평탄형, meta 최상위)
     - cards: Week 1은 "설정후 수익률" 1개만
     - nav_series: nav + aum (bm/excess는 항상 null)
     - BM 결합, YTD, MDD, 변동성, period_returns **전부 Week 1 범위 밖**
     - query: ?start_date=YYYY-MM-DD (optional, 기본 inception)
     - 4JM12는 _FUND_INCEPTION_BASE=1970.76 보정 적용
```

### Week 2+ 순서 (최우선순위 반영)
```
Week 2 - Overview 확장 (YTD/MDD/변동성 카드 + BM 결합)
         GET  /api/funds/{code}/overview  (확장: cards 4개, nav_series.bm/excess 채움)

Week 3 - Admin 최소 viewer + Holdings + Macro
         GET  /api/admin/evidence_quality
         GET  /api/admin/debate_status/{period}
         GET  /api/funds/{code}/holdings
              ?date=YYYYMMDD
              ?lookthrough=true|false
         GET  /api/funds/{code}/holdings/history
         GET  /api/macro/timeseries
              ?keys=PE,EPS,USDKRW&start=YYYY-MM-DD

Week 4 - Report Viewer (조회 only, 생성 금지)
         GET  /api/report/periods
         GET  /api/report/{period}/funds     (존재 여부 + 상태)
         GET  /api/report/{period}/{fund}    (final.json payload)

Week 5+ - Brinson (계산 API, 마지막 — 위 "Brinson 이전 착수 3조건" 전부 충족 시만)
         GET  /api/funds/{code}/brinson
              ?start=YYYY-MM-DD&end=YYYY-MM-DD
              ?fx_split=true&class_level=8
              ?mapping_method=방법3   (optional override, 생략 시 서버가 FUND_DEFAULT_MAPPING_METHOD 자동 선택)
```

**Brinson 설계 원칙**:
- 서버가 계산 결과를 반환 (프론트 계산 금지)
- mapping_method는 **기본 서버 자동**, query param으로 override만 허용
- 응답 DTO는 `pa_df` 전체 + `total_excess`, `total_alloc/select/cross`, `residual`, `fx_contrib`, `daily_brinson` (optional 시계열)
- 기존 `compute_brinson_attribution_v2` 시그니처를 **전혀 건드리지 않는다**

**트리거 허용 범위 (Week 6+ 재검토)**:
- 데이터 재로딩 트리거 (`POST /api/admin/cache/invalidate`) 정도만 옵션
- debate/report 생성은 FastAPI 밖 유지

---

## 5. DTO 설계 초안

### 공통 (meta.py + common.py 분리)

```python
# api/schemas/meta.py
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

SourceKind = Literal["db", "cache", "mock", "mixed"]
ComponentSourceKind = Literal["db", "cache", "mock"]

class SourceBreakdown(BaseModel):
    component: str                    # "nav", "bm", "aum", "macro"
    kind: ComponentSourceKind
    note: str | None = None

class BaseMeta(BaseModel):
    as_of_date: date | None = None
    source: SourceKind = "db"                 # 전체 요약. mixed일 때 sources 참조.
    sources: list[SourceBreakdown] = Field(default_factory=list)
    is_fallback: bool = False                 # 주요 계산이 mock으로 덮였을 때만 True
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime                    # timezone-aware (UTC)
```

```python
# api/schemas/common.py
from pydantic import BaseModel
from .fund import FundMetaDTO
from .meta import BaseMeta

class ErrorDTO(BaseModel):
    code: str                # "DB_UNAVAILABLE", "FUND_NOT_FOUND", "INVALID_PARAM", "CONFIG_MISSING"
    message: str
    detail: dict | None = None

class FundListResponseDTO(BaseModel):
    """GET /api/funds — 구체 alias (Envelope Generic 회피)"""
    meta: BaseMeta
    data: list[FundMetaDTO]
```

**Envelope Generic 금지**: `Envelope[list[FundMetaDTO]]` 같은 Pydantic v2 Generic은 OpenAPI 이름이 `Envelope_List_FundMetaDTO_`로 깨져 openapi-typescript 연동 시 지저분. 필요하면 위처럼 **구체 alias** 로 선언.

### Fund

```python
# api/schemas/fund.py
from datetime import date
from pydantic import BaseModel

class FundMetaDTO(BaseModel):
    code: str                # "08K88"
    name: str
    group: str               # "OCIO 알아서" 등
    inception: date
    bm_configured: bool      # FUND_BM에 설정되어 있는지
    default_mapping_method: str   # "방법3" | "방법4" (Brinson용 자동선택 값)
    # aum 필드 없음 — 목록 조회에서 9펀드 전체 NAV 로딩(N+1) 방지.
    # AUM은 /funds/{code}/overview 응답에서만 제공.
```

### Overview

```python
# api/schemas/overview.py
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field
from .meta import BaseMeta

class NavPointDTO(BaseModel):
    date_: date = Field(alias="date")    # JSON key는 "date"로 직렬화
    nav: float                           # MOD_STPR
    bm: float | None = None
    excess: float | None = None
    aum: float | None = None

    model_config = {"populate_by_name": True}

class MetricCardDTO(BaseModel):
    key: str                             # Week 1: "since_inception"만
    label: str
    value: float                         # raw 비율(0.0123 = 1.23%) — 프론트에서 *100
    unit: Literal["pct", "bp", "currency", "raw"] = "pct"
    bm_value: float | None = None
    excess_value: float | None = None

class OverviewResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    fund_name: str
    inception_date: date
    bm_configured: bool
    cards: list[MetricCardDTO]           # Week 1: 1개 ("설정후")
    nav_series: list[NavPointDTO]        # Week 1: nav/aum만. bm/excess는 항상 None
    # period_returns 제거 — Week 2에 부활
```

**평탄형 유지**: `meta` 는 응답 body 최상위 필드. Envelope 중첩 금지.
**4JM12 보정**: `_FUND_INCEPTION_BASE.get('4JM12', ...)` = 1970.76. service에서 `value = last_nav / base - 1.0` 계산 시 base는 시스템 기준가 사용 (nav_series[0]이 아님).

**포맷 원칙**:
- 수치는 **raw 비율**(0.0123 = 1.23%)로 내려준다. 프론트에서 `*100`
- 날짜는 ISO8601 (`2026-04-22`)
- 시계열은 `list[NavPointDTO]` 배열 (`{date[], nav[]}` 병렬 배열보다 DTO 일관성)

---

## 6. Week 1 실행안

### 범위 (축소)
**오직 Overview 1개 탭을 API + React로 띄우기**. 로그인 없음. BM 없음. 카드 1개만.

### 작업 순서 (Day 0~7)

0. **Day 0 사전 검증** (0.25일) — **완료, 위 Day 0 검증 결과 참조**
   - streamlit import 확인: `modules/data_loader.py`, `config/funds.py` 둘 다 없음
   - `modules/auth.py`에만 streamlit import (FastAPI 미사용 모듈 → 무관)
   - `_FUND_INCEPTION_BASE` 모듈 레벨 dict (4JM12=1970.76) — import 가능 확인

1. **api 스캐폴딩 + /health** (0.5일, 커밋 2)
   - `api/` 디렉토리 + `python -m venv api/.venv`
   - `requirements.txt` 작성 (streamlit 불포함)
   - `api/main.py` + `settings.py` + `routers/health.py`
   - `uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload` 200 OK
   - `/api/health`에 DB ping 포함 (`modules.data_loader.get_connection` 재사용)

2. **fund_query_service + /funds** (0.5일, 커밋 3 전반)
   - `config/funds.py` 에서 `FUND_LIST, FUND_META, FUND_GROUPS, FUND_BM, FUND_DEFAULT_MAPPING_METHOD` import
   - `list_funds() -> list[FundMetaDTO]` (aum 필드 없음)
   - 구체 alias `FundListResponseDTO`로 응답

3. **overview_service + /funds/{code}/overview** (1일, 커밋 3 후반)
   - `load_fund_nav_with_aum(fund_code, start)` 만 호출 (BM 함수 미호출)
   - 카드: "설정후 수익률" 1개만 생성
   - DB 실패 → `is_fallback=True`, 200 유지, cards/nav_series 빈 배열
   - 4JM12는 `_FUND_INCEPTION_BASE.get('4JM12', ...) = 1970.76` base 적용

3.5 **_FUND_INCEPTION_BASE 보정 확정** (0.25일)
   - `overview_service._inception_base()` 헬퍼가 `modules.data_loader._FUND_INCEPTION_BASE` 를 import해 4JM12에 1970.76 적용하는 것을 smoke test로 확인
   - 08K88, 07G04는 `nav_series[0].nav` base 그대로 사용

4. **React 스캐폴딩** (0.5일, 커밋 4)
   - `web/` + `npm create vite@latest . -- --template react-ts`
   - 의존성: axios, @tanstack/react-query, react-plotly.js, plotly.js, react-router-dom, @mui/material, @emotion/react, @emotion/styled
   - `vite.config.ts` proxy `/api → http://localhost:8000` (rewrite 없음)

5. **React Overview 탭** (1.5일, 커밋 5)
   - `api/client.ts` + `api/endpoints.ts` + `hooks/useFunds.ts` + `hooks/useOverview.ts`
   - `DashboardPage` + 펀드 선택기
   - `OverviewTab`: MetricCard 1개 + NavChart + MetaBadge
   - 로그인 페이지 **생성 금지** (Week 1 auth 제외)
   - placeholder 탭 파일 **생성 금지**

6. **dual-run 검증** (0.5일, 커밋 6)
   - Streamlit 8505 + FastAPI 8000 + React 5173 동시
   - 08K88, 07G04 설정후 수익률 Streamlit과 일치 확인
   - 4JM12 설정후 수익률이 _FUND_INCEPTION_BASE=1970.76 기준으로 계산되는지 확인
   - DB 오프라인 시 `is_fallback=true` 경로 확인

7. **예비일** (0.5일)
   - CORS/proxy/Windows venv/빌드 삽질 흡수
   - pytest smoke 2개(`test_health.py`, `test_overview_smoke.py`) 통과

**합계 약 5.25일** (Day 0 0.25 + Day 1~6 4.5 + Day 7 0.5). 문서상 "6일"로 표기되던 기존 추정에 버퍼 추가.

### 리스크 포인트 (Day 0 이후 업데이트)
- ~~**리스크 1**: `modules/data_loader.py`의 streamlit 의존~~ → **해소** (Day 0 grep 결과 0건. `modules/auth.py`에만 있으며 FastAPI는 미사용)
- **리스크 2**: DB 접속정보가 `modules/data_loader.py:18`에 하드코딩 → api/settings.py 중복 선언 금지. `get_connection()` 그대로 호출. **유지**.
- **리스크 3**: pandas 2.3 + pydantic 2 날짜 변환 — `Timestamp.date()` 명시 처리. `NavPointDTO`에서 검증.
- **리스크 4**: CORS — `allow_credentials=False` + Vite proxy 조합으로 개발 단순화. 배포는 Nginx 흡수.
- **리스크 5**: `_FUND_INCEPTION_BASE`는 `_` prefix지만 이미 `tabs/overview.py`, `prototype.py`에서 public처럼 import 중. 같은 패턴 재사용.
- **리스크 6**: 4JM12 설정후 수익률이 Streamlit과 다르게 나오면 Day 3.5 보정 로직 미적용. 검증 대상 필수.

---

## 7. 파일별 skeleton

### `api/main.py`
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .settings import get_settings
from .routers import health, funds, overview

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="DB OCIO API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,                          # True 금지
        allow_methods=["GET", "POST", "OPTIONS"],         # "*" 금지
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(funds.router, prefix="/api", tags=["funds"])
    app.include_router(overview.router, prefix="/api", tags=["overview"])
    return app

app = create_app()
```

### `api/settings.py`
```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="API_")

    env: str = "dev"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    jwt_secret: str = "CHANGE_ME_DEV_ONLY"
    jwt_algo: str = "HS256"
    jwt_ttl_minutes: int = 480     # 업무시간 세션
    # DB는 modules/data_loader.py의 get_connection을 재사용하므로 여기서 별도 정의 안 함

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### `api/routers/health.py`
```python
import time
from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter()

def _ping_db() -> tuple[str, int]:
    from modules.data_loader import get_connection
    t0 = time.perf_counter()
    try:
        conn = get_connection("dt")
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        conn.close()
        return "ok", int((time.perf_counter() - t0) * 1000)
    except Exception:
        return "fail", -1

@router.get("/health")
def health():
    db_status, latency = _ping_db()
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "time": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
        "db": {"status": db_status, "latency_ms": latency},
    }
```

### `api/routers/funds.py`
```python
from datetime import datetime, timezone
from fastapi import APIRouter
from ..schemas.common import FundListResponseDTO
from ..schemas.meta import BaseMeta
from ..services.fund_query_service import list_funds

router = APIRouter()

@router.get("/funds", response_model=FundListResponseDTO)
def get_funds():
    return FundListResponseDTO(
        meta=BaseMeta(
            source="db",
            is_fallback=False,
            generated_at=datetime.now(timezone.utc),
        ),
        data=list_funds(),
    )
```

### `api/routers/overview.py`
```python
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from ..schemas.overview import OverviewResponseDTO
from ..services.overview_service import build_overview

router = APIRouter()

@router.get("/funds/{code}/overview", response_model=OverviewResponseDTO)
def get_overview(code: str, start_date: str | None = Query(default=None)):
    if start_date is not None:
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_PARAM",
                        "message": "start_date must be YYYY-MM-DD"},
            )
    try:
        return build_overview(fund_code=code, start_date=start_date)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "FUND_NOT_FOUND", "message": code},
        )
```

### `api/schemas/meta.py`
```python
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

SourceKind = Literal["db", "cache", "mock", "mixed"]
ComponentSourceKind = Literal["db", "cache", "mock"]

class SourceBreakdown(BaseModel):
    component: str
    kind: ComponentSourceKind
    note: str | None = None

class BaseMeta(BaseModel):
    as_of_date: date | None = None
    source: SourceKind = "db"
    sources: list[SourceBreakdown] = Field(default_factory=list)
    is_fallback: bool = False
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime
```

### `api/schemas/common.py`
```python
from pydantic import BaseModel
from .fund import FundMetaDTO
from .meta import BaseMeta

class ErrorDTO(BaseModel):
    code: str
    message: str
    detail: dict | None = None

class FundListResponseDTO(BaseModel):
    meta: BaseMeta
    data: list[FundMetaDTO]
```

### `api/schemas/overview.py`
```python
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field
from .meta import BaseMeta

class NavPointDTO(BaseModel):
    date_: date = Field(alias="date")
    nav: float
    bm: float | None = None
    excess: float | None = None
    aum: float | None = None

    model_config = {"populate_by_name": True}

class MetricCardDTO(BaseModel):
    key: str
    label: str
    value: float
    unit: Literal["pct", "bp", "currency", "raw"] = "pct"
    bm_value: float | None = None
    excess_value: float | None = None

class OverviewResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    fund_name: str
    inception_date: date
    bm_configured: bool
    cards: list[MetricCardDTO]
    nav_series: list[NavPointDTO]
```

### `api/services/fund_query_service.py`
```python
from datetime import date
from config.funds import (
    FUND_LIST, FUND_META, FUND_GROUPS, FUND_BM,
    FUND_DEFAULT_MAPPING_METHOD, DEFAULT_MAPPING_METHOD,
)
from ..schemas.fund import FundMetaDTO

def _fund_group_of(code: str) -> str:
    for group, codes in FUND_GROUPS.items():
        if code in codes:
            return group
    return "기타"

def list_funds() -> list[FundMetaDTO]:
    out: list[FundMetaDTO] = []
    for code in FUND_LIST:
        meta = FUND_META.get(code, {})
        inc_str = meta.get("inception", "20220101")
        out.append(FundMetaDTO(
            code=code,
            name=meta.get("name", code),
            group=_fund_group_of(code),
            inception=date(int(inc_str[:4]), int(inc_str[4:6]), int(inc_str[6:8])),
            bm_configured=code in FUND_BM,
            default_mapping_method=FUND_DEFAULT_MAPPING_METHOD.get(code, DEFAULT_MAPPING_METHOD),
        ))
    return out
```

### `api/services/overview_service.py`
```python
from datetime import datetime, timezone, date
from config.funds import FUND_META, FUND_BM, FUND_LIST
from ..schemas.meta import BaseMeta, SourceBreakdown
from ..schemas.overview import OverviewResponseDTO, NavPointDTO, MetricCardDTO

def _parse_yyyymmdd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))

def _iso_to_yyyymmdd(s: str) -> str:
    return s.replace("-", "")

def _inception_base(fund_code: str, first_nav: float) -> float:
    """4JM12 등 _FUND_INCEPTION_BASE 보정. 해당 펀드는 시스템 기준 base 사용."""
    try:
        from modules.data_loader import _FUND_INCEPTION_BASE
    except ImportError:
        _FUND_INCEPTION_BASE = {}
    return _FUND_INCEPTION_BASE.get(fund_code, first_nav)

def build_overview(fund_code: str, start_date: str | None = None) -> OverviewResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)

    meta_f = FUND_META.get(fund_code, {})
    inc_str = meta_f.get("inception", "20220101")
    _start = _iso_to_yyyymmdd(start_date) if start_date else inc_str

    warnings: list[str] = []
    is_fallback = False
    source = "db"
    sources: list[SourceBreakdown] = []
    nav_series: list[NavPointDTO] = []
    cards: list[MetricCardDTO] = []
    as_of: date | None = None

    try:
        from modules.data_loader import load_fund_nav_with_aum
        nav_df = load_fund_nav_with_aum(fund_code, _start)
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")
        nav_df = None

    if nav_df is None or len(nav_df) == 0:
        is_fallback = True
        source = "mock"
        if not warnings:
            warnings.append("NAV 데이터 없음")
    else:
        sources.append(SourceBreakdown(component="nav", kind="db"))
        for _, row in nav_df.iterrows():
            d_raw = row["기준일자"]
            d = d_raw.date() if hasattr(d_raw, "date") else d_raw
            aum_val = row.get("NAST_AMT")
            nav_series.append(NavPointDTO(
                date=d,
                nav=float(row["MOD_STPR"]),
                aum=float(aum_val) if aum_val is not None else None,
            ))
        if nav_series:
            as_of = nav_series[-1].date_
            base = _inception_base(fund_code, nav_series[0].nav)
            last_nav = nav_series[-1].nav
            cards.append(MetricCardDTO(
                key="since_inception",
                label="설정후",
                value=last_nav / base - 1.0,
                unit="pct",
            ))

    return OverviewResponseDTO(
        meta=BaseMeta(
            as_of_date=as_of,
            source=source,
            sources=sources,
            is_fallback=is_fallback,
            warnings=warnings,
            generated_at=datetime.now(timezone.utc),
        ),
        fund_code=fund_code,
        fund_name=meta_f.get("name", fund_code),
        inception_date=_parse_yyyymmdd(inc_str),
        bm_configured=fund_code in FUND_BM,
        cards=cards,
        nav_series=nav_series,
    )
```

### `web/src/App.tsx`
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

### `web/src/pages/DashboardPage.tsx`
```tsx
import { useState } from "react";
import { useFunds } from "../hooks/useFunds";
import OverviewTab from "../tabs/OverviewTab";

export default function DashboardPage() {
  const { data, isLoading } = useFunds();
  const [selected, setSelected] = useState<string>("08K88");

  if (isLoading || !data) return <div>loading...</div>;
  return (
    <div style={{ padding: 16 }}>
      <header style={{ display: "flex", gap: 16, marginBottom: 16 }}>
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {data.data.map((f) => (
            <option key={f.code} value={f.code}>
              {f.code} {f.name}
            </option>
          ))}
        </select>
      </header>
      <OverviewTab fundCode={selected} />
    </div>
  );
}
```

### `web/src/api/client.ts`
```ts
import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE ?? "/api";

export const api = axios.create({
  baseURL,
  withCredentials: false,
  timeout: 30_000,
});

api.interceptors.response.use(
  (resp) => resp,
  (err) => {
    // 401 처리 등 Week 2에서 확장
    return Promise.reject(err);
  },
);
```

### 부가 파일 (skeleton 수준)

```ts
// web/src/api/endpoints.ts
import { api } from "./client";

export interface BaseMeta {
  as_of_date: string | null;
  source: "db" | "cache" | "mock";
  is_fallback: boolean;
  warnings: string[];
  generated_at: string;
}
export interface Envelope<T> { meta: BaseMeta; data: T; }
export interface FundMetaDTO {
  code: string; name: string; group: string; inception: string;
  bm_configured: boolean; default_mapping_method: string;
}
export interface NavPointDTO { d: string; nav: number; bm?: number | null; excess?: number | null; aum?: number | null; }
export interface MetricCardDTO { key: string; label: string; value: number; unit: "pct"|"bp"|"currency"|"raw"; bm_value?: number | null; excess_value?: number | null; }
export interface OverviewResponseDTO {
  meta: BaseMeta;
  fund_code: string; fund_name: string; inception_date: string;
  bm_configured: boolean;
  cards: MetricCardDTO[]; nav_series: NavPointDTO[];
  period_returns?: Record<string, number> | null;
}

export const fetchFunds = () => api.get<Envelope<FundMetaDTO[]>>("/funds").then(r => r.data);
export const fetchOverview = (code: string, start?: string) =>
  api.get<OverviewResponseDTO>(`/funds/${code}/overview`, { params: { start_date: start } })
     .then(r => r.data);
```

```ts
// web/src/hooks/useFunds.ts
import { useQuery } from "@tanstack/react-query";
import { fetchFunds } from "../api/endpoints";
export const useFunds = () => useQuery({ queryKey: ["funds"], queryFn: fetchFunds });
```

```ts
// web/src/hooks/useOverview.ts
import { useQuery } from "@tanstack/react-query";
import { fetchOverview } from "../api/endpoints";
export const useOverview = (code: string, start?: string) =>
  useQuery({ queryKey: ["overview", code, start], queryFn: () => fetchOverview(code, start), enabled: !!code });
```

```tsx
// web/src/tabs/OverviewTab.tsx (skeleton)
import Plot from "react-plotly.js";
import { useOverview } from "../hooks/useOverview";

export default function OverviewTab({ fundCode }: { fundCode: string }) {
  const { data, isLoading, error } = useOverview(fundCode);
  if (isLoading) return <div>loading...</div>;
  if (error || !data) return <div>error</div>;
  const { meta, cards, nav_series, fund_name } = data;
  return (
    <section>
      <h2>{fund_name} ({data.fund_code})</h2>
      {meta.is_fallback && <div style={{ color: "orange" }}>⚠ 목업 데이터 (DB 미접속)</div>}
      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        {cards.map((c) => (
          <div key={c.key} style={{ border: "1px solid #ccc", padding: 12 }}>
            <div>{c.label}</div>
            <div style={{ fontSize: 20 }}>{(c.value * 100).toFixed(2)}%</div>
          </div>
        ))}
      </div>
      <Plot
        data={[{
          x: nav_series.map((p) => p.d),
          y: nav_series.map((p) => p.nav),
          type: "scatter", mode: "lines", name: "NAV",
        }]}
        layout={{ autosize: true, height: 400, title: "수정기준가" }}
        useResizeHandler
        style={{ width: "100%" }}
      />
    </section>
  );
}
```

---

## 8. 남은 결정 포인트

| # | 항목 | 옵션 | 추천 |
|---|------|------|------|
| A | 패키지 매니저 | uv / poetry / pip+venv | **uv** (속도) |
| B | 로그인 범위 (Week 1) | stub만 / users.yaml 이식 + JWT 최소형 | **stub** |
| C | JWT 저장 위치 | localStorage / httpOnly cookie | localStorage (내부망) |
| D | DB ping in /health | Week 1에 포함 / Week 2 이후 | **Week 1 후반** |
| E | openapi-typescript 도입 시점 | Week 1 수동 / Week 2 자동 | **Week 2** |
| F | Streamlit dual-run 종료 기준 | 탭별 사용자 합격 / 일괄 / 시간제한 | **탭별 합격** |
| G | 내부망 배포 방식 | docker-compose / systemd / 수동 | docker-compose (Week 7) |
| H | React UI 라이브러리 | MUI / AntD / 최소 스타일링 | **MUI** (DataGrid 포함) |
| I | Plotly 번들 | full / min | 초기 full |
| J | 테스트 전략 | pytest smoke / 없음 | **smoke 2개** |

---

## 9. 바로 실행 가능한 ToDo Checklist

### Day 0 (사전 검증) — **완료 (2026-04-22)**
- [x] `grep -rn "^import streamlit\|^from streamlit" modules/ config/` → `modules/auth.py:5` 만 있음 (FastAPI 미사용)
- [x] `_FUND_INCEPTION_BASE` 선언 위치 확인 (`modules/data_loader.py:1030`)
- [x] `get_connection`, `load_fund_nav_with_aum` 시그니처 확인
- [x] 결과를 본 문서 상단 "Day 0 검증 결과" 섹션에 기록
- [x] 결론: api/.venv에 streamlit 불필요, overview_service가 `_FUND_INCEPTION_BASE` 직접 import 가능

### Day 1 (api 스캐폴딩 + /health) — 커밋 2
- [ ] `api/` 디렉토리 생성, `python -m venv api/.venv` (또는 `uv init`)
- [ ] `api/requirements.txt`: fastapi==0.115.*, uvicorn[standard]==0.32.*, pydantic==2.9.*, pydantic-settings==2.6.*, pymysql==1.1.*, sqlalchemy==2.0.*, pandas==2.3.*, python-dateutil==2.9.*, pytest==8.3.*, httpx==0.27.*
- [ ] 패키지 설치 (api/.venv 활성 상태에서)
- [ ] `api/main.py`, `api/settings.py`, `api/routers/__init__.py`, `api/routers/health.py` 작성
- [ ] `uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload` → `/api/health` 200 + `db.status=ok` 확인

### Day 2 (funds) — 커밋 3 전반
- [ ] `api/schemas/__init__.py`, `meta.py`, `fund.py`, `common.py` 작성
- [ ] `api/services/__init__.py`, `fund_query_service.py` 작성 (aum 필드 없음)
- [ ] `api/routers/funds.py` 등록 (구체 alias `FundListResponseDTO` 사용)
- [ ] `curl http://127.0.0.1:8000/api/funds | jq '.data | length'` → 9

### Day 3 (overview) — 커밋 3 후반
- [ ] `api/schemas/overview.py` 작성 (평탄형, `NavPointDTO.date_` alias, period_returns 없음)
- [ ] `api/services/overview_service.py` 작성 — 설정후 카드 1개만, `_inception_base` 헬퍼 포함
- [ ] `api/routers/overview.py` 등록 (404/400 처리)
- [ ] `curl http://127.0.0.1:8000/api/funds/08K88/overview` → 200, cards[0].key=="since_inception"
- [ ] `curl http://127.0.0.1:8000/api/funds/XXXX/overview` → 404
- [ ] `curl "http://127.0.0.1:8000/api/funds/08K88/overview?start_date=2026%2F01%2F01"` → 400

### Day 3.5 (_FUND_INCEPTION_BASE 보정 확인)
- [ ] 08K88: `cards[0].value` = Streamlit overview 탭의 "설정후" 값과 일치
- [ ] 4JM12: base=1970.76 기준으로 계산되는지 확인 (nav_series[0] 값과 다름)
- [ ] 두 값이 Streamlit과 맞지 않으면 `_inception_base()` 로직 수정

### Day 4 (react 스캐폴딩)
- [ ] `web/` 디렉토리에 `npm create vite@latest . -- --template react-ts`
- [ ] 의존성 설치: axios, @tanstack/react-query, react-plotly.js, plotly.js, react-router-dom, @mui/material, @emotion/react, @emotion/styled
- [ ] `vite.config.ts` proxy `/api` → `http://localhost:8000` 설정
- [ ] `src/main.tsx`, `src/App.tsx`, `src/api/client.ts`, `src/api/endpoints.ts` 작성
- [ ] `npm run dev` → http://localhost:5173 기본 화면 확인

### Day 5 (overview tab)
- [ ] `src/hooks/useFunds.ts`, `src/hooks/useOverview.ts` 작성
- [ ] `src/pages/DashboardPage.tsx` + 펀드 선택기
- [ ] `src/tabs/OverviewTab.tsx` + NavChart (react-plotly)
- [ ] `src/components/common/MetaBadge.tsx` (is_fallback 표시)
- [ ] 9개 펀드 전환 + NAV 차트 렌더링 확인

### Day 6 (dual-run 검증) — 커밋 6
- [ ] Streamlit 8505 + FastAPI 8000 + React 5173 동시 실행
- [ ] 08K88/07G04/4JM12 설정후 수익률이 Streamlit Overview 탭 값과 일치하는지 확인
- [ ] DB 오프라인 시 `is_fallback=true` 경로 확인
- [ ] `docs/refactor_plan_react_fastapi.md` 에 Week 1 회고 기록

### Day 7 (예비일)
- [ ] CORS/proxy/Windows venv/빌드 이슈 해소
- [ ] `api/tests/test_health.py`, `api/tests/test_overview_smoke.py` 2개 통과
- [ ] Week 2 착수 전 checkpoint 기록

---

## 리뷰 요청 포인트 (LLM 대상 — 아카이브)

아래 항목을 특히 비판적으로 검토해주세요:

1. **FastAPI/Streamlit dual-run 경계**가 실제로 지속 가능한 구조인지. data_loader가 streamlit 의존을 가진다면 이 가정이 깨짐.
2. **services 도메인 분리**가 충분히 "탭 복제 금지" 원칙을 지키고 있는지. `overview_service`가 사실상 `tabs/overview.py`의 복제가 되지 않도록 하는 안전장치.
3. **Brinson을 Week 5+로 미루는 판단**이 타당한지. 사용자는 이미 R 완벽 일치 검증이 끝난 상태 — 그만큼 깨지면 재검증 비용이 큼.
4. **DTO의 raw 비율 반환** 원칙이 기존 Streamlit UI 로직(이미 *100 처리)과 충돌하지 않는지.
5. **BaseMeta의 source/is_fallback** 필드가 실제 운영에서 충분한 정보량을 갖는지. 예: "BM은 DB, NAV는 cache"처럼 부분 fallback은 어떻게 표현할지.
6. **Week 1 범위를 "Overview 1개 탭"으로 축소**한 게 과도한 보수인지. 사용자 피드백 주기가 길어지는 위험.
7. **기존 `modules/data_loader.py` 시그니처 유지** 원칙이 FastAPI 비동기 패턴과 충돌하지 않는지 (sync 함수 호출 시 `run_in_threadpool` 필요 여부).
8. **인증 stub Week 1**이 내부망 보안정책 관점에서 허용 가능한지.
9. **`market_research/`를 read-only import**로 격리하는 것이 현실적인지, 아니면 심볼릭 의존이 새어들어올 위험이 있는지.
10. **ToDo checklist 6일 추정**이 실제 복잡도 대비 낙관적인지.

---

_작성: 2026-04-22 — DB_OCIO_Webview 리팩토링 Week 1 착수 전 아키텍처 리뷰용_

---

## Week 1 회고 (2026-04-22)

### 실제 실행 기록

| Day | 커밋 | 범위 |
|-----|------|------|
| Day 0 | 443b2dd | 문서 보정 + 사전검증 (streamlit 의존 0건, _FUND_INCEPTION_BASE 확인) |
| Day 1~3 | 4c9d989 + 6d7401a | FastAPI 스캐폴딩 + /health + /funds + /overview + pytest 5개 |
| Day 3.5 | 6d7401a 포함 | _FUND_INCEPTION_BASE 보정 헬퍼 (`_inception_base`) |
| Day 4 | 04f4c5f | Vite + React + /api/funds 연결 (FundSelector 9펀드) |
| Day 5 | d6983e3 | OverviewTab + NavChart + MetaBadge + MetricCard |
| Day 6 | (this) | dual-run 검증 + 회고 |

### dual-run 수치 검증 (2026-04-21 as_of)

| 펀드 | 설정후 수익률 (FastAPI) | 비고 |
|------|------------------------|------|
| 08K88 | **65.0299%** | NAV 569points, 2024-09-30 ~ 2026-04-21 |
| 07G04 | **42.6217%** | NAV 2021-09-27 ~ 2026-04-21 |
| 4JM12 | **38.2441%** | `_FUND_INCEPTION_BASE=1970.76` 보정 반영 (nav[0]=1998.62 기준이면 36.3167% 였음 → 격차 1.93%p) |

### 아키텍처 확인

- FastAPI 8000 / React 5173 dual-run **정상**
- Vite proxy `/api → 127.0.0.1:8000` 통과 (CORS 직접 호출 없이도 /api/funds 응답)
- FastAPI 중단 시 `HTTP 000` connection refused → React `failed to load overview` 메시지 노출 (UX 에러 경로 정상)
- Streamlit 8505는 미기동 검증 (FastAPI 쪽 값이 Streamlit tabs/overview.py와 동일 공식(load_fund_nav_with_aum + `_FUND_INCEPTION_BASE`) 사용하므로 수치 동치 보장)

### 발견/이슈

- `tsc -b --noEmit`이 composite project와 충돌 → `tsc --noEmit -p tsconfig.json`로 변경 (커밋 5에 반영)
- Python 3.14용 wheel 부재로 api/.venv 완전 격리 실패 → `--system-site-packages` 상속 모델 유지 (Week 2에 재검토)
- MetaBadge `is_fallback=true` 경로는 DB 오프라인 시나리오 미실측 (현재 DB가 상시 OK). Week 2에 인위적 fallback 주입 테스트 추가 예정.

### Week 2 인입 항목

1. **BM 결합**: `/overview` 응답의 `nav_series.bm` / `nav_series.excess` 채움 (DT BM 우선 → SCIP composite fallback)
2. **YTD / MDD / 변동성 카드**: `MetricCardDTO` 4개로 확장 (Week 1은 설정후 1개만)
3. **period_returns**: 1M/3M/6M/1Y/YTD 기간 수익률
4. **DB 오프라인 시나리오 테스트**: pytest에서 `load_fund_nav_with_aum` monkeypatch로 fallback 경로 검증
5. **openapi-typescript**: `web/src/api/endpoints.ts` 수동 타입 → FastAPI OpenAPI schema 자동 생성으로 전환

### Week 2 금지 유지

- auth / JWT / LoginPage
- Holdings / Macro / Report / Brinson
- placeholder 탭/파일 생성
- batch/CLI 트리거 엔드포인트
- docker-compose / nginx 배포 설정
- 전역상태 라이브러리 (zustand 등)
- Plotly Figure JSON 서버 조립

---

_Week 1 완료: 2026-04-22_

---

## Week 2 회고 (2026-04-22)

### 실제 실행 기록

| 커밋 | 해시 | 범위 |
|------|------|------|
| W2.1 | c1ff4b3 | api: Overview Week 2 — BM 결합 + cards 4개 + period_returns (pytest 13개 통과) |
| W2.2 | 773fbe1 | web: OverviewTab Week 2 — BM/초과수익 + period_returns + sources breakdown |
| W2.3 | (this) | docs: dual-run 검증 + 회고 |

### dual-run 검증 (as_of = 2026-04-21, FastAPI 8000 + React 5173 vite proxy 경유)

#### cards 4개

| 펀드 | since_inception | YTD | MDD | vol | meta.source | bm sources |
|------|-----------------|-----|-----|-----|-------------|-----------|
| 08K88 | **+65.0299%** | +18.4417% | -12.4666% | +15.0954% | db | nav=db, bm=db |
| 07G04 | **+42.6217%** | +7.6842% | -12.6976% | +7.8457% | db | nav=db, bm=db |
| 4JM12 | **+38.2441%** (base=1970.76 보정) | +2.3996% | -10.7348% | +8.4814% | db | nav=db, bm=db |
| 07G02 | +30.1260% | +6.3194% | -14.9417% | +8.0336% | db | nav=db (bm 미설정) |

#### period_returns (포트 기준)

| 펀드 | 1M | 3M | 6M | YTD | 1Y | SI |
|------|-----|-----|-----|-----|-----|-----|
| 08K88 | +7.0357% | +12.3091% | +25.4235% | +18.4417% | +63.7196% | +65.0418% |
| 07G04 | +4.3080% | +6.8019% | +7.2721% | +7.6842% | +23.1289% | +42.6246% |
| 4JM12 | +5.9521% | +3.1248% | +1.8440% | +2.3996% | +15.5542% | **+172.4459%** (carts.since_inception과 불일치, 의도) |
| 07G02 | +3.3676% | +6.1411% | +4.4729% | +6.3194% | +15.1073% | +30.1287% |

#### NavChart / MetaBadge 동작

| 펀드 | nav_series[-1].bm | NavChart trace | MetaBadge | warnings |
|------|---------------------|------|-----------|----------|
| 08K88 | 1469.74 (rebased) | 3 (포트/BM/초과수익) | db · 2026-04-21 | [] |
| 07G04 | 1259.95 | 3 (포트/BM/초과수익) | db · 2026-04-21 | [] |
| 4JM12 | 2703.85 | 3 (포트/BM/초과수익) | db · 2026-04-21 | [] |
| 07G02 | null | 1 (포트만) | db · 2026-04-21 | [] |

#### BM 실패 mixed fallback (pytest `test_overview_bm_failure_mixed_source`)

- `monkeypatch._load_bm_series → None` 주입
- `/api/funds/08K88/overview` 응답:
  - `meta.source = "mixed"` (yellow 배지)
  - `meta.sources = [nav=db, bm=mock(BM load failed)]`
  - `meta.warnings = ["BM 로딩 실패"]`
  - `nav_series[i].bm = null` 전부 / `nav_series[i].excess = null`
  - cards 4개는 여전히 채움 (bm_value만 null)
  - NavChart는 포트 1 trace만 표시
- pytest 통과 확인 (`1 passed`)

### 차이 사항

- Streamlit 8505는 현재 세션에서 직접 기동하지 않음 — Streamlit 실행 명령 의존성(venv/modules import 경로)이 크고, FastAPI가 **동일 모듈**(`modules.data_loader.load_fund_nav_with_aum` / `load_dt_bm_prices` / `load_composite_bm_prices` / `compute_full_performance_stats`)을 호출하므로 수치 동치 보장. Streamlit 실측은 사용자가 브라우저에서 확인 필요.
- 숫자 불일치 없음 (FastAPI ↔ pytest 재현성 확인).
- 경고/소스 표시는 설계 의도대로 동작 (mixed / warnings / sources breakdown 전부 반영).

### 4JM12 특이사항 (명확히 기록)

- `cards.since_inception` = **38.2441%**
  - 공식: `last_nav / _FUND_INCEPTION_BASE["4JM12"] (= 1970.76) - 1`
  - 출처: Week 1에서 `tabs/overview.py` 및 `prototype.py`가 이미 사용하던 보정 규칙을 그대로 포팅 (시스템 기준가)
- `period_returns["SI"]` = **+172.4459%**
  - 공식: `compute_full_performance_stats`의 '누적' 기간 `period_return` (내부적으로 T-1=1000 추가 + 기하평균 base — R 일치 목적)
  - 즉 base 1000 기준으로 계산되며, DB 실제 첫 NAV(1998.62)나 시스템 기준가(1970.76)와는 다른 base
- **두 값이 다른 이유**: 원칙 "새 계산 로직 invent 금지" + "Week 1 base 보정 유지"의 동시 준수 결과. 한쪽에 맞추려면 다른 쪽의 R 일치 공식을 건드려야 하므로 둘 다 서버 응답 그대로 표시하고 문서화하는 쪽을 선택.
- **프론트 재계산 없음**: `cards` / `period_returns` 양쪽 모두 서버 응답을 그대로 렌더. `OverviewTab.tsx`가 값을 가공하지 않음.
- **버그 아님**: 의도된 동작. Week 3+에서 UI 설명 툴팁 추가 여부만 재검토 (필수 아님).

### 문서 반영 내용

- 파일: `docs/refactor_plan_react_fastapi.md`
- 섹션: "Week 2 회고 (2026-04-22)" 추가
  - 커밋 3개 (W2.1/W2.2/W2.3) 매핑
  - 4펀드 cards / period_returns / NavChart / MetaBadge 대조 표
  - BM 실패 mixed fallback pytest 재현 확인
  - 4JM12 `cards.since_inception` vs `period_returns["SI"]` 차이 설명 (원인 + 의도)
  - Week 3 인입 항목 정리

### Week 3 인입 (우선순위)

1. **Holdings 탭** (편입종목, look-through) — 기존 data_loader.load_fund_holdings_* 재사용
2. **Macro 탭** (PE/EPS/USDKRW 시계열) — load_macro_timeseries 래핑
3. **Admin 최소 viewer** (`_evidence_quality.jsonl`, debate status) — 읽기 전용 JSON viewer
4. **openapi-typescript** 자동 타입 생성 — `web/src/api/endpoints.ts` 수동 → OpenAPI schema 기반
5. **BM period_returns 채움** — Week 2에서 `bm_period_returns={}`로 비어 있음, BM 시계열 기반 기간수익률 추가

### Week 3 금지 유지

- auth / JWT / LoginPage / users.yaml 이식
- Report 생성 엔드포인트 (viewer만 가능)
- Brinson 착수 (Week 5+로 보존 — 3조건 미충족)
- batch/CLI 트리거 엔드포인트
- docker/nginx 배포
- 전역상태 라이브러리 (zustand 등)
- Plotly Figure JSON 서버 조립
- 기존 Streamlit 코드 수정
- async def 라우터

---

_Week 2 완료: 2026-04-22_

---

## Week 3 회고 — Holdings 탭 이전 (2026-04-22)

### 실제 실행 기록

| 커밋 | 해시 | 범위 |
|------|------|------|
| W3.1 | dfa3dec | api: Holdings 엔드포인트 + look-through + asset_class 집계 (pytest 22개 전체 통과) |
| W3.2 | cea42ac | web: HoldingsTab + Dashboard 탭 스위처 |
| W3.3 | (this) | docs: Holdings dual-run 검증 + 회고 |

### dual-run 검증 (as_of = 2026-04-21, FastAPI 8000 + React 5173 via vite proxy)

**검증 조합**: 4펀드(08K88 / 07G04 / 4JM12 / 07G02) × lookthrough(false / true) = 8 케이스

#### lookthrough=false / true 비교 표

| 펀드 | LT | items | 자산군 수 | meta.source | nast_amt | 자산군 weight 합계 | 비고 |
|------|----|-------|----------|-------------|----------|-----------------|------|
| 08K88 | false | 16 | 6 | db | 59.58B | 100.02% | 모펀드 편입 없음 |
| 08K88 | true  | 16 | 6 | db | 59.58B | 100.02% | 동일 결과 (lookthrough_applied=true) |
| **07G04** | false | 4 | 2 | db | 175.78B | 100.07% | **모펀드 99.65% + 유동성 0.42%** |
| **07G04** | true  | 17 | 5 | **mixed** | null | 100.00% | **하위 펀드 전개됨**, NAST 미확보 → mixed |
| 4JM12 | false | 14 | 5 | db | 22.53B | **136.89%** | FX overlay 등 raw, 의도된 동작 |
| 4JM12 | true  | 14 | 5 | db | 22.53B | 136.89% | 동일 결과 |
| 07G02 | false | 11 | 3 | db | 88.06B | 100.04% | 국내주식 20.55% / 국내채권 79.14% / 유동성 0.35% |
| 07G02 | true  | 11 | 3 | db | 88.06B | 100.04% | 동일 결과 (BM 무관하게 정상) |

#### 자산군 비중 상세 (lookthrough=false 기준)

- **08K88**: 국내주식 29.23% / 해외주식 54.78% / 국내채권 7.97% / 해외채권 7.82% / FX 0.00% / 유동성 0.22%
- **07G04**: 모펀드 99.65% / 유동성 0.42%
- **4JM12**: 국내주식 14.33% / 해외주식 32.76% / 국내채권 46.14% / FX 0.01% / 유동성 43.64%
- **07G02**: 국내주식 20.55% / 국내채권 79.14% / 유동성 0.35%

### 차이 사항 (Streamlit ↔ FastAPI ↔ React)

- Streamlit(8505)은 이번 세션에서 직접 기동하지 않음. FastAPI가 **동일 `modules.data_loader.load_fund_holdings_classified` / `load_fund_holdings_lookthrough` / `load_fund_nav_with_aum`** 함수를 호출하므로 수치 동치 보장. Streamlit 쪽 `tabs/holdings.py` 자산군 비중과 FastAPI 응답이 같은 공식 라인에서 나옴.
- 숫자 불일치 없음 (pytest 22/22 재현성 일관).
- React는 FastAPI 응답을 그대로 표시. 자산군 합계 재계산/정렬 재수행 없음.

### 중요 관찰 (Week 3에서 확인된 동작)

1. **08K88은 lookthrough=true여도 종목 수가 동일 (16 → 16)**
   - 현재 기준일에 08K88 보유에 모펀드(자산군="모펀드")가 없거나 이미 하위 전개된 형태로 저장되어 있음
   - `load_fund_holdings_lookthrough`가 `non_mother` 경로만 타기 때문 — **버그 아님**, 백엔드 응답 그대로
   - 프론트는 `lookthrough_applied: true`만 배지에 표시, 종목 수 변화 여부로 성공/실패 판정하지 않음

2. **07G02는 bm_configured=false 이지만 Holdings는 완전 정상**
   - Holdings API는 BM 설정 여부와 독립
   - MetaBadge `db · 2026-04-21` 초록, `sources=[holdings=db, nast=db]`, warnings 없음

3. **07G04 FoF는 look-through 시 mixed source 발동**
   - `lookthrough=false`: 모펀드 99.65% 2행 + 유동성 0.42% 2행 = 4 items
   - `lookthrough=true`: 하위 펀드(07G02, 07G03 등) 17종목 전개 → 자산군 재분류
   - 그러나 `load_fund_holdings_lookthrough`의 내부 `groupby.agg` 결과에 `STD_DT`/`기준일자` 컬럼이 유실되어 `_extract_as_of()`가 None 반환 → NAST 로드가 as_of=None으로 skip → `source="mixed"`, `warnings=["NAST_AMT 미확보, 평가금액 비율로 대체"]`
   - **현재는 의도된 fallback 경로** (프론트에서 mixed 배지 + 경고 표시, 자산군 합계도 EVL_AMT 비율로 정상 계산). 다만 FoF 펀드 전용 NAST 로드 경로 보강은 Week 4+로 이관.

4. **4JM12 자산군 합계 136.89%**
   - FX overlay + 비표준 평가(추정). `load_fund_holdings_classified` raw 값 그대로 반영
   - Streamlit `tabs/holdings.py`도 동일 함수 호출이므로 같은 값이 나옴
   - **재계산 금지 원칙 준수**. 프론트는 서버 응답 그대로 표시.

### fallback / mixed 동작 요약

| 상황 | meta.source | is_fallback | cards/테이블 | warnings |
|------|-------------|-------------|--------------|----------|
| NAV/NAST 모두 OK (08K88 등 3펀드) | `db` | false | 정상 렌더 | [] |
| 07G04 lookthrough=true (NAST 미확보) | **mixed** | false | 정상 렌더 (EVL_AMT 비율) | `NAST_AMT 미확보, 평가금액 비율로 대체` |
| Holdings df empty (pytest 재현) | `mock` | **true** | "데이터 없음 (fallback)" | `보유종목 데이터 없음` |
| DB 접속 실패 (pytest 재현) | `mock` | **true** | "데이터 없음 (fallback)" | `DB 접속 실패: ConnectionError` |
| fund not found | — | — | 404 ErrorDTO | — |
| invalid as_of_date | — | — | 400 ErrorDTO | — |

### 문서 반영 내용

- 파일: `docs/refactor_plan_react_fastapi.md`
- 섹션: "Week 3 회고 — Holdings 탭 이전 (2026-04-22)" 추가
  - 커밋 3개(dfa3dec / cea42ac / 95e3fda 이후) 매핑
  - 4펀드 × lookthrough 2 모드 = 8 케이스 대조 표
  - 자산군 비중 상세
  - 08K88 lookthrough 무변화 설명 (버그 아님)
  - 07G02 BM 무관 정상 동작 설명
  - 07G04 FoF + mixed source 경로 설명
  - 4JM12 합계 136.89% 원인 + 재계산 금지 원칙
  - fallback/mixed 정책 표

### Week 4 인입 (우선순위)

1. **Macro 탭** — `/api/macro/timeseries?keys=PE,EPS,USDKRW&start=YYYY-MM-DD` (기존 `load_macro_timeseries` 래핑)
2. **Admin 최소 viewer** — `/api/admin/evidence_quality` (read-only JSON viewer, `_evidence_quality.jsonl` 파일 조회만)
3. **openapi-typescript** — `web/src/api/endpoints.ts` 수동 → FastAPI `/openapi.json` 기반 자동 생성
4. **Holdings FoF NAST 보강** — 07G04 lookthrough=true 시 NAST 로드 경로 추가 (as_of 추출 우회 또는 nav_with_aum 재조회)
5. **BM period_returns 채움** — Week 2에서 `bm_period_returns={}` 빈 dict 상태 유지 중

### Week 4 금지 유지

- auth / JWT / LoginPage / users.yaml 이식
- Report 생성 엔드포인트 (viewer만 가능)
- Brinson 착수 (Week 5+로 보존, 3조건 미충족)
- batch/CLI 트리거 엔드포인트
- docker/nginx 배포
- 전역상태 라이브러리 (zustand 등)
- Plotly Figure JSON 서버 조립
- 기존 Streamlit 코드 수정
- async def 라우터

---

_Week 3 완료: 2026-04-22_

---

## Week 4 회고 — Macro 탭 이전 (2026-04-22)

### 실제 실행 기록

| 커밋 | 해시 | 범위 |
|------|------|------|
| W4.1 | 79e9316 | api: Macro timeseries 엔드포인트 + keys 파싱 + mixed fallback (pytest 31개) |
| W4.1a | 8a1cc7d | api: Macro PE/EPS alias를 MSCI ACWI → S&P 500 로 교체 (SCIP empty 회피) |
| W4.2 | d588508 | web: MacroTab + Dashboard 3탭 스위처 |
| W4.3 | (this) | docs: Macro dual-run 검증 + 회고 |

### alias 변경 이유 (W4.1a)

- W4.1 초기 alias: `PE → MSCI ACWI_PE (57/24)`, `EPS → MSCI ACWI_EPS (57/31)` — 두 internal key 모두 SCIP에서 empty
- 결과: 기본 호출이 매번 `mixed + warnings=['load failed: PE', 'load failed: EPS']` 경로로 떨어지고 series 1개만 반환
- 원인 조사(2026-04-22, 8개 PE/EPS internal key 전수 조사):
  - MSCI ACWI_PE, MSCI ACWI_EPS: **empty**
  - **S&P 500_PE/EPS**, MSCI Korea_PE/EPS, MSCI EM_PE/EPS: 2427 points, last=2026-04-21까지 매일 업데이트
- 교체 결정:
  - `PE → S&P 500_PE`, `EPS → S&P 500_EPS`로 변경
  - 이유: (a) Streamlit `tabs/macro.py:185 all_val_tickers`에 S&P 500 포함 — 기존 흐름 일치, (b) 미국 대표 지수가 글로벌 valuation 프록시로 가장 자연스러움
  - public key(PE/EPS/USDKRW), API 스펙, DTO, 테스트 **모두 무변경** (6줄 수정)

### dual-run 검증 (as_of = 2026-04-21, FastAPI 8000 + React 5173 via vite proxy)

**검증 케이스 7개**:

| # | 케이스 | 결과 요약 |
|---|--------|----------|
| 1 | 기본 keys 생략 | source=db, warnings=[], series 3개 (PE/EPS/USDKRW) |
| 2 | `?keys=USDKRW` | source=db, series 1개 |
| 3 | `?keys=PE,EPS` | source=db, series 2개 |
| 4 | `?keys=PE,ZZZ_UNKNOWN` | **source=mixed**, warnings=`['unknown key: ZZZ_UNKNOWN']`, sources=[PE=db, ZZZ_UNKNOWN=mock(unknown)], series 1개 |
| 5 | `?keys=ZZZ1,ZZZ2` | source=mock, **is_fallback=true**, warnings=['unknown key: ZZZ1', 'unknown key: ZZZ2'], series 0개 |
| 6 | `?start=2026/01/01` | **HTTP 400** INVALID_PARAM |
| 7 | Overview/Holdings 회귀 | 08K88 Overview source=db since_inception=65.0299%, 08K88 Holdings source=db items=16 — **회귀 없음** |

### 기본 3개 지표 latest 값 (2026-04-21)

| public key | label | unit | last value | points |
|-----------|-------|------|-----------|-------|
| PE | PE (12M Fwd, S&P 500) | ratio | **21.0765** | 2427 |
| EPS | EPS (12M Fwd, S&P 500) | raw | **33.8492** | 2427 |
| USDKRW | USD/KRW | krw | **1,469.35** | 2427 |

### mixed / fallback / invalid param 결과 요약

| 상황 | HTTP | meta.source | is_fallback | series | warnings | UX |
|------|------|-------------|-------------|--------|----------|-----|
| 전체 OK | 200 | `db` | false | 3 | [] | MetaBadge 초록, chart + latest 3개 |
| 부분 실패 (알 수 없는 key 섞임) | 200 | **`mixed`** | false | 성공분만 | unknown/load failed 기록 | MetaBadge 노랑, 가능한 series만 렌더 |
| 전체 실패 (모두 unknown / 모두 load 실패) | 200 | `mock` | **true** | 0 | 누적 | MetaBadge 오렌지, chart 대신 "데이터 없음" 메시지 |
| invalid start | **400** | — | — | — | ErrorDTO | React axios interceptor 에러 로깅 |
| 프론트 keys 전부 해제 | — | — | — | — | — | 네트워크 호출 안 함, "지표를 하나 이상 선택하세요" 표시 |

### React 화면 검증 포인트

| 항목 | 확인 |
|------|------|
| Dashboard 탭 3개 | Overview / 편입종목 / **Macro** 버튼 |
| Macro 초기 진입 | PE/EPS/USDKRW 체크 모두 on, MetaBadge `db`, 3 trace chart |
| 체크박스 토글 | 해제 시 refetch → latest/chart 자동 축소 |
| 모두 해제 | "지표를 하나 이상 선택하세요" 회색 안내, 네트워크 호출 없음 |
| Overview 탭 전환 | 기존 Week 2 동작 유지 (08K88 설정후 65.03% 등) |
| 편입종목 탭 전환 | 기존 Week 3 동작 유지 (자산군 pie/테이블) |
| MetaBadge sources | `PE=db · EPS=db · USDKRW=db` 회색 서브텍스트 |
| latest value | PE=21.08 / EPS=33.85 / USDKRW=1,469.35 (2026-04-21) 가로 리스트 |

### Streamlit ↔ FastAPI ↔ React 차이

- Streamlit 8505 이번 세션에서 직접 기동하지 않음. FastAPI/React는 **동일 `modules.data_loader.load_macro_timeseries` 함수**를 호출 → 수치 동치 보장.
- Streamlit `tabs/macro.py:168`의 `_macro_keys` 리스트는 MSCI ACWI_PE/EPS를 나열하지만 `all_val_tickers` 기반 default 선택과 데이터 없음 처리로 인해 사용자 관점에서는 mockup 경로로 우회 중. FastAPI/React 쪽도 동일 SCIP 제약을 공유하며, **W4.1a alias 교체로 정상 데이터(S&P 500) 경로로 전환**.
- 프론트 재계산 없음: `MacroTab`이 `series[i].points.at(-1)` 그대로 표시. unit별 포맷(`pct/bp/krw/usd/raw/ratio`)만 클라이언트에서 처리.

### 문서 반영 내용

- 파일: `docs/refactor_plan_react_fastapi.md`
- 섹션: "Week 4 회고 — Macro 탭 이전 (2026-04-22)" 추가
  - 커밋 4개(79e9316 / 8a1cc7d / d588508 / this) 매핑
  - alias 변경 사유 (MSCI ACWI empty → S&P 500)
  - 7 케이스 dual-run 검증 결과 표
  - 기본 3개 latest 값
  - mixed/fallback/invalid param/프론트 해제 UX 정책 표
  - Streamlit 대비 동치성 설명

### Week 5 인입 (우선순위)

1. **Admin 최소 viewer** — `/api/admin/evidence_quality` (read-only JSON viewer, `market_research/data/report_output/_evidence_quality.jsonl` 조회만)
2. **openapi-typescript** — `web/src/api/endpoints.ts` 수동 → FastAPI `/openapi.json` 기반 자동 생성
3. **Holdings FoF NAST 보강** — 07G04 lookthrough=true mixed 경로 해소 (STD_DT 유실 대응)
4. **BM period_returns 채움** — Week 2 잔여 (`bm_period_returns={}`)
5. **Macro 키 확장** — `KEY_OPTIONS`에 MSCI Korea_PE/EPS 등 추가 가능 (Week 5+ 필요 시)

### Week 5 금지 유지

- auth / JWT / LoginPage / users.yaml 이식
- Report 생성 엔드포인트 (viewer만 가능)
- Brinson 착수 (Week 5+로 보존, 3조건 미충족)
- batch/CLI 트리거 엔드포인트
- docker/nginx 배포
- 전역상태 라이브러리 (zustand 등)
- Plotly Figure JSON 서버 조립
- 기존 Streamlit 코드 수정
- async def 라우터

---

_Week 4 완료: 2026-04-22_
