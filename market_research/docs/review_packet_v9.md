# Review Packet v9 — 펀드 코멘트 자동생성 + Debate 품질 개선 + UI 대폭 개편

> 작성일: 2026-04-14
> 범위: fund_comment_service, debate 품질(evidence card/월별quota/coverage), 네이버 매체명 복원, 지표 추가, UI 전면 개편
> 이전: v8 (3-Tier 탭 구조)

---

## Part I. 핵심 변경

### 1. 펀드 코멘트 자동생성 (`fund_comment_service.py`)

시장 debate 결과 + 펀드별 데이터(PA/보유/거래)를 결합해 Opus로 펀드 맞춤 코멘트 생성.

- 시장 debate와 완전 분리된 별도 service
- 시장 payload 로딩 정책: approved final 우선 → edited draft fallback → 없으면 차단
- 펀드 미편입 자산군 자동 감지 → `market_view` 상단에 제외 지시 삽입
- 거래내역 요약을 `inputs['additional']`에 주입
- 비용: ~$0.05~0.50/펀드 (Opus)

### 2. Debate 품질 개선

| 개선 | 파일 | 내용 |
|------|------|------|
| evidence card | `debate_engine.py` | 제목+1줄 요약 → 토픽/월/매체/제목/핵심사실 카드형 |
| 분기 월별 quota | `debate_engine.py` | 월별 최소 5건 확보 → 마지막 달 편중 방지 |
| 분기 시간순 구조 | `debate_engine.py` | synthesis 프롬프트에 1월→2월→3월→종합 구조 강제 |
| coverage rule | `debate_service.py` | `compute_coverage_metrics` (가용/인용 토픽, 수치 무출처) |
| ref 재부여 | `debate_service.py` | `renumber_refs` — 등장순 1번부터 + 미사용→관련뉴스 |
| ref_mismatch 비활성 | `debate_service.py` | false positive only → 비활성화 |
| 분기 max_tokens | `debate_engine.py` | 2000 → 4000 |

### 3. 네이버 매체명 복원 (`source_mapping.py`)

- URL 도메인 → 매체명 매핑 (34개 도메인)
- 2025-01 ~ 2026-04 전체 뉴스 JSON 일괄 패치 (31,942건)
- salience 재계산 → 네이버 기사 debate 입력 가능

### 4. 지표 추가 (indicators.csv)

| 컬럼 | 소스 | SCIP ID |
|------|------|---------|
| KOSPI | KOSPI Index FG Price KRW | 253 |
| SP500 | S&P 500 Index FG Return USD | 271 |
| VWO | Vanguard EM FG Price USD | 37 |
| USHY | iShares Broad USD HY FG Price USD | 112 |
| US_GROWTH | VUG FG Price USD | 11 |
| US_VALUE | VTV FG Price USD | 12 |
| EM_BOND | VWOB FG Return USD | 141 |

### 5. UI 대폭 개편

**탭 구조**: Overview / 편입종목 / 성과분석 / 운용보고(펀드) / 운용보고(매크로) + Admin 2개

**Overview**: 설정이후카드→설정일, 편입현황→MDD차트(누적수익률 반반)
**편입종목**: 좌=자산군별/우=종목별 동시. MP Gap 삭제. 유동성→현금성/기타 분리. 비중추이 100% 환산.
**성과분석**: BPA 타이틀 삭제, 비중비교 삭제, 일별누적Brinson 삭제. 좌=테이블/우=차트 2단.
**운용보고(매크로)**: 펀드 드롭다운 삭제(_market 고정). 분기 차트 기간 수정.
**운용보고(펀드)**: report_output 직접 읽기. 상단 펀드 연동.
**Admin(운용보고_펀드)**: 거래내역/비중 테이블 (자산군 소계+종목 상세).

### 6. 분류 개선

- `_classify_6class`에 `_TRADE_ITEM_CLASSIFY` override 최우선 적용 (보유종목+거래 공통)
- iShares HY → 해외채권, KODEX HY → 해외채권, TMF → 국내채권
- `load_holdings_history_8class` 비중추이에도 override 반영

---

## Part II. 파일 목록

### 신규 (3개)

| 파일 | 줄수 | 역할 |
|------|------|------|
| `market_research/report/fund_comment_service.py` | 322 | 펀드 코멘트 생성 서비스 |
| `market_research/core/source_mapping.py` | ~70 | 네이버 매체명 복원 |
| `tabs/admin_fund.py` | ~250 | 펀드 코멘트 admin + 거래내역 테이블 |

### 수정 (10개+)

| 파일 | 주요 변경 |
|------|-----------|
| `prototype.py` | 탭 구조 개편, 펀드 선택 7개, 08K88 FUND_META 추가 |
| `tabs/overview.py` | 설정일 카드, MDD 차트 |
| `tabs/holdings.py` | 자산군+종목 동시, MP Gap 삭제, 유동성 분리, 8class 비중추이 |
| `tabs/brinson.py` | 레이아웃 재구성, 정밀PA 삭제, 비중비교 삭제, y축 여유 |
| `tabs/report.py` | 매크로 _market 고정, 펀드 상단 연동, report_output 직접 읽기 |
| `tabs/admin_macro.py` | 기간 디폴트 자동, coverage metrics |
| `modules/data_loader.py` | 거래내역 로더, override 공통 적용, load_fund_holdings_weight |
| `market_research/report/debate_engine.py` | evidence card, 월별 quota, 시간순 구조, max_tokens |
| `market_research/report/debate_service.py` | coverage metrics, renumber_refs |
| `market_research/report/report_store.py` | legacy 제거, 빈 디렉토리 필터, latest_period 헬퍼 |

---

## Part III. 검증 상태

| 항목 | 결과 |
|------|------|
| 거래내역 로더 (07G02 3월) | PASS — 국내채권 +161억, 해외채권 -131억 |
| 종목 분류 override (35건) | 사용자 수동 확인 완료 |
| `_classify_6class` override 적용 | PASS — KODEX HY→해외채권, iShares HY→해외채권 |
| 펀드 코멘트 생성 (07G02 4월) | PASS — 2,568자, $0.055 |
| 펀드 미편입 자산군 제외 (08K88) | 코드 반영 완료, UI 확인 필요 |
| debate 2회 실행 | PASS — Q1 + 4월 |
| Streamlit 기동 | PASS (HTTP 200) |
| 네이버 매체명 복원 | PASS — 31,942건 |

### 미검증

- R Brinson residual 비교 (08K88 동일 기간)
- 비중추이 차트 override 반영 확인
- debate 품질 비교 (기존 vs 개선)

---

## Part IV. 남은 작업

| # | 항목 | 우선순위 |
|---|------|---------|
| 1 | R Brinson residual 비교 | P0 |
| 2 | 비중추이 override 확인 | P0 |
| 3 | 5분류/8분류 토글 정리 (Single Port PA에도 적용) | P1 |
| 4 | WGBI 등 토픽 다양성 보장 | P1 |
| 5 | comment_engine에 trades 전용 프롬프트 섹션 | P1 |
| 6 | Reuters Google News URL 리졸브 | P2 |

---

*2026-04-14 | 펀드 코멘트 자동생성 + debate 품질 개선 + 네이버 복원 + 지표 추가 + UI 전면 개편*
