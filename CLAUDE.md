# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Streamlit 자동 리셋 규칙

**아래 파일을 수정한 후에는 반드시 Streamlit 프로세스를 kill + 재시작하세요:**
- `prototype.py`, `tabs/*.py`, `modules/*.py`, `config/*.py`

```bash
# 리셋 명령 (포트 8505 기준)
netstat -ano | grep ":8505 .*LISTENING"  # PID 확인
taskkill //F //PID <PID>
sleep 3
find . -name "__pycache__" -exec rm -rf {} +
python -m streamlit run prototype.py --server.port 8505 &
```

Streamlit은 `session_state`에 이전 위젯 값을 유지하므로 **코드만 수정하고 브라우저 새로고침하면 반영 안 됨**. 반드시 프로세스 kill 후 새 브라우저 탭으로 접속.

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

## 2026-04-14 Status Update

### 탭 구조

```
[공통] Overview | 편입종목 | 성과분석 | 운용보고(펀드) | 운용보고(매크로)
[Admin] Admin(운용보고_매크로) | Admin(운용보고_펀드)
```

상단 펀드 선택: 7개 (07G04, 08K88, 08N33, 08N81, 08P22, 2JM23, 4JM12), 기본값 08K88.
삭제된 탭: Admin(펀드현황), 매크로지표.

### Architecture: 3-Tier Runtime Boundary

```
[외부 배치 — market_research]     [Streamlit Admin]              [Client]
 뉴스 수집/분류/정제/GraphRAG      시장 debate 실행/검수/승인        approved final만 조회
 timeseries narrative             펀드 코멘트 생성/검수/승인
 debate input package             거래내역/비중 변화 테이블
```

- **시장 debate**: `debate_service.py` → `_market.draft.json`
- **펀드 코멘트**: `fund_comment_service.py` → `{fund}.draft.json` (시장 debate + PA/보유/거래)
- legacy `debate_published` fallback 제거

### Current Priorities

- **debate 품질 개선 완료**: evidence card, 분기 월별 quota, coverage rule, 네이버 매체명 복원.
- **펀드 코멘트 자동생성 완료**: 시장 debate + PA + 보유비중 + 거래내역 결합 → Opus.
- **UI 대폭 개편 완료**: 탭 구조, Overview MDD, 편입종목 자산군/종목 동시표시, 성과분석 레이아웃.
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

### 정제 레이어 핵심 파일

- `market_research/core/dedupe.py` — article_id + 중복제거 + event clustering (TOPIC_NEIGHBORS 8그룹)
- `market_research/core/salience.py` — bm_anomaly(z>1.5, 7일캡) + 3단계 source + fallback(키워드필수)
- `market_research/pipeline/daily_update.py` — Step 2.5 `_step_refine()` (정제 오케스트레이션)
- `market_research/analyze/graph_rag.py` — `_stratified_sample()` (dynamic cap 300~500)
- `market_research/report/debate_engine.py` — diversity guardrail (토픽5/이벤트2) + evidence_ids
- `market_research/analyze/news_vectordb.py` — hybrid_score (cosine + salience×0.3)

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
- `market_research/core/dedupe.py` — article_id + dedup + event clustering (TOPIC_NEIGHBORS)
- `market_research/core/salience.py` — salience(bm_anomaly+3단계source) + fallback(키워드필수)
- `market_research/analyze/news_classifier.py` — 21주제 + 13키 자산영향도 (Haiku)
- `market_research/analyze/graph_rag.py` — stratified sample + Self-Regulating TKG
- `market_research/analyze/news_vectordb.py` — ChromaDB + hybrid_score
- `market_research/report/debate_engine.py` — 4인 debate + diversity guardrail + evidence
- `market_research/report/comment_engine.py` — BM/PA/digest → LLM 프롬프트 + 코멘트 생성
  - 8개 펀드: A포맷(08P22,08N81,08N33,07G02,07G03), C포맷(07G04), D포맷(2JM23,4JM12)
- `market_research/report/cli.py` — 통합 CLI (build/list, 대화형/auto/edit)
- `market_research/tests/ablation_test.py` — 정제 효과 비교 프레임워크

### Known Issues

- `NewsAPI` 무료 플랜 약관 위반 가능성 → 대체 소스 미구현.
- evidence ref 오매핑률 누적 데이터 부족 (debate 2회+ 필요).

### 해결 완료

- ~~토픽 whitelist~~ → `_sanitize_topic()` + `_TOPIC_ALIAS` (깨진 토픽 0건)
- ~~영어 전용 임베딩~~ → `paraphrase-multilingual-MiniLM-L12-v2` 전환 완료
- ~~GraphRAG monthly/daily 불일치~~ → monthly TKG + daily transmission_paths 추가
- ~~V1/V2 토픽 혼용~~ → 5개 파일 V2 일관성 수정 완료
- ~~수치 가드레일~~ → debate_engine 연동 + 금리 오판 수정 (키워드 1순위)
- ~~evidence trace~~ → [ref:N] 프롬프트 + 파싱 유틸 + 누적 추적 체계
- ~~vectorDB + GraphRAG 리빌드~~ → 4개월 완료
- ~~아키텍처 정리~~ → 3-Tier (외부 배치/admin/client) + report_store + IO contract

### TODO (P0 — 다음 세션)

1. **debate 재실행 2회+** → `_evidence_quality.jsonl` 누적 기록 확보
2. **pilot_checklist 13항목 전수 확인** → 전부 PASS 후 파일럿 시작

## Project Purpose

DB형 퇴직연금 OCIO(Outsourced CIO) 운용 현황 웹 대시보드.
Streamlit 기반 프로토타입으로, R Shiny 기존 시스템(General_Backtest/)을 Python으로 재구현 중.
9개 펀드의 성과 모니터링, 자산배분, Brinson PA, 매크로 지표 분석 제공 (2026-04-21: 12개 펀드 제거 — 06X08, 07J20/27/34/41, 07J48/49, 07P70, 07W15, 09L94, 1JM96/98).

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

# 월별 report cache 재생성
python -m market_research.report_cache_builder 2026 3
```

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
- BM 매핑: DT BM 우선 (5개 펀드 `_DT_BM_CONFIG`: 07G02, 07G03, 07G04, 08K88, 4JM12), SCIP fallback (`FUND_BM`: 07G04, 08K88, 4JM12 — 3개 설정). BM 미설정: 07G02, 07G03, 08N33, 08N81, 08P22, 2JM23.
- NAV 로딩 시작일: `FUND_META[fund]['inception']` 사용 (이전 하드코딩 '20240101' 제거)
- 기간수익률: `relativedelta` 달력월 기준 (DT DWPM10040 완벽 일치). `python-dateutil` 의존성 추가.
- MP 비중: DB 연동 완료 (`sol_MP_released_inform` + `FUND_MP_DIRECT`). 2026-04-21 12펀드 제거 후 FUND_MP_MAPPING 3개(07G02/03/04) + FUND_MP_DIRECT 6개(08K88, 08N33, 08N81, 08P22, 2JM23, 4JM12).
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

### 검증 v2 (08K88, 2026-01-01~2026-04-16)
| 항목 | Python v2 | R | 차이 |
|------|-----------|---|------|
| AP | 17.1928% | 17.1926% | +0.0002%p ✅ |
| BM | 13.2015% | 13.2015% | 0%p ✅ |
| **초과** | **3.9913%** | **3.9910%** | **+0.0003%p** ✅ |
| Alloc | 3.0147% | 3.0206% | -0.006%p ✅ |
| Select | 0.9177% | 0.8865% | +0.031%p |
| Cross | 0.0590% | 0.0839% | -0.025%p |
| Sum | 3.9914% | 3.9910% | +0.0004%p ✅ |

**자산군별 3-Factor**: 국내주식/해외주식/FX의 Allocation **완벽 일치(0bp)**. 국내주식 3-Factor 전체 완벽 일치. FX Select/Cross, 유동성 Cross에서 미세 차이(0.02~0.11%p).

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

- 08K88 (2026-01-01~04-16): 4개 방법 모두 `AP=17.1926% / BM=13.2015% / 초과=3.9910%` 불변 (R 완벽일치 회귀 없음)
- 4JM12 (2026-01-01~04-16): 4개 방법 모두 `총초과=-0.5523%` 불변
- **GDX (US92189F1066) 분류 확인 ✅**:
  - 방법1: 대체 / 방법2: 주식 / **방법3: 대체** / **방법4: 해외주식** / 방법5: NULL
  - `universe_non_derivative` DB 값과 `compute_single_port_pa` 결과 완전 일치

## PDCA Status

- Feature: DB_OCIO_Webview
- Phase: Do (Phase 5 UI 개선 진행 중)
- Phase 3 완료: 전체 탭 DB 연동
- Phase 4.1 완료: 연율화수익률/위험/RF/샤프 (R 동일 로직, Excel 검증 통과)
- Phase 4.2 완료: PA 정밀화 — FX split R 완벽 일치 (환산_adjust 금액 기반)
- Phase 4.3 완료: DT BM 연동, 기간수익률 DT 일치, 설정후 수익률 보정
- Phase 4.4 완료: Brinson PA R일치 — 보정인자1, NAST비중, FX오버레이, 잔차0, BM R동일설정
- Phase 4.5 완료: Brinson v2 — compute_single_port_pa 재활용, 보정인자2 추가, 초과수익률 R 완벽 일치(+0.0003%p)
- Phase 4.6 완료 (2026-04-22): 자산군 분류 방법 4종 (방법1~4) 지원, 사용자 드롭다운 선택, 펀드별 기본값 자동
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
- 6개 펀드(07G02, 07G03, 08N33, 08N81, 08P22, 2JM23) BM 미설정
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
