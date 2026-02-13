# DB_OCIO_Webview Planning Document

> **Summary**: DB형 퇴직연금 OCIO 운용 현황 대시보드 - 대면보고를 웹으로 대체
>
> **Project**: DB_OCIO_Webview
> **Author**: Claude Code (CTO Lead)
> **Date**: 2026-02-12
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

DB형 퇴직연금 OCIO(Outsourced Chief Investment Officer) 운용 현황을 웹 대시보드로 시각화하여, 기존 대면보고를 대체하고 내부 운용팀과 고객 모두가 실시간으로 운용 정보에 접근할 수 있도록 한다.

### 1.2 Background

- 현재 고객 대상 운용보고는 대면 미팅 중심으로 진행되어 비효율적
- 내부 운용팀은 편입종목 비중, MP Gap, 성과분석을 수작업/엑셀로 관리
- 국내외 매크로 지표와 포트폴리오 연동 분석이 체계적이지 않음
- 웹 기반 대시보드로 전환하여 실시간성, 접근성, 보고 효율성을 개선

### 1.3 Related Documents

- 이전 프로젝트: 20260211 (퇴직 포트폴리오 인출률 백테스트 시스템)
- References: Brinson Attribution Model, OCIO 운용보고서 양식

---

## 2. Scope

### 2.1 In Scope

- [ ] **내부 운용 대시보드**: 편입종목 비중, MP 대비 Gap, Brinson 성과분석
- [ ] **고객 포털**: 로그인/인증, 본인 펀드 운용내역/보고서/운용계획 조회
- [ ] **매크로 지표 연동**: 국내외 매크로 지표와 자산군별 움직임 연동
- [ ] **성과 기여도 분석**: 종목별 수익률 기여도(Allocation/Selection/Interaction Effect)
- [ ] **운용보고서 뷰어**: 기존 대면보고 자료의 웹 버전
- [ ] **운용계획 표시**: 향후 운용 방향/전략 공유

### 2.2 Out of Scope

- 실시간 트레이딩/주문 집행 기능
- 리스크 관리 시스템 (별도 시스템)
- 모바일 네이티브 앱 (반응형 웹으로 대체)
- 결제/과금 기능

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 고객 로그인/패스워드 인증 | High | Pending |
| FR-02 | 고객별 사모OCIO 펀드 매핑 (로그인 → 본인 펀드만 조회) | High | Pending |
| FR-03 | 편입종목 현황 (종목명, 비중, 수량, 평가금액) | High | Pending |
| FR-04 | MP(Model Portfolio) 대비 Gap 분석 (Over/Under weight 표시) | High | Pending |
| FR-05 | Brinson 성과분석 (Allocation, Selection, Interaction Effect) | High | Pending |
| FR-06 | 종목별 수익률 기여도 (어떤 종목이 얼마만큼 영향) | High | Pending |
| FR-07 | 운용보고서 열람 (PDF 또는 웹 렌더링) | Medium | Pending |
| FR-08 | 향후 운용계획/전략 표시 | Medium | Pending |
| FR-09 | 국내외 매크로 지표 대시보드 (금리, 환율, PMI, CPI 등) | Medium | Pending |
| FR-10 | 매크로 지표 ↔ 보유 자산군 연동 분석 | Medium | Pending |
| FR-11 | 기간별 성과 비교 (1M, 3M, 6M, YTD, 1Y, Since Inception) | Medium | Pending |
| FR-12 | BM 대비 초과수익률 추이 차트 | Medium | Pending |
| FR-13 | 내부 운용팀 전용 뷰 (전체 펀드 현황, 크로스 펀드 분석) | Low | Pending |
| FR-14 | 데이터 엑셀 다운로드 기능 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | 페이지 로딩 < 3초 (초기), 차트 렌더링 < 1초 | Streamlit profiling |
| Security | 고객별 데이터 격리, 비밀번호 해싱 | 코드 리뷰 |
| Usability | 비개발자(고객)도 직관적으로 사용 가능 | 사용자 피드백 |
| Availability | 고객 접속 시간대(09~18시) 안정적 운영 | 모니터링 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 고객이 로그인 후 본인 펀드 운용현황 조회 가능
- [ ] 내부 운용팀이 전 펀드의 MP Gap과 Brinson 분석 확인 가능
- [ ] 매크로 지표와 보유 자산의 연동 차트 동작
- [ ] 기존 대면보고 자료 수준의 정보가 웹에서 제공됨

### 4.2 Quality Criteria

- [ ] 주요 기능 테스트 통과
- [ ] 고객 데이터 격리 검증
- [ ] Streamlit 앱 정상 구동 확인

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Streamlit 인증 기능 한계 | High | Medium | streamlit-authenticator 라이브러리 또는 커스텀 세션 관리 |
| 대용량 데이터 로딩 지연 | Medium | Medium | 데이터 전처리/캐싱, pkl 파일 사전 생성 |
| 매크로 데이터 소싱 안정성 | Medium | Medium | FRED API, 한국은행 API 등 공식 소스 + 로컬 캐시 |
| 고객별 데이터 보안 | High | Low | 세션 기반 격리, 비밀번호 해싱, HTTPS |
| Brinson 분석 구현 복잡성 | Medium | Medium | 단계적 구현 (단일 기간 → 다기간 → Geometric linking) |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites, portfolios | |
| **Dynamic** | Feature-based modules, BaaS integration | Web apps with backend, SaaS | **V** |
| **Enterprise** | Strict layer separation, microservices | High-traffic, complex arch | |

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| Framework | Streamlit | Streamlit | 이전 프로젝트 경험, 빠른 프로토타이핑, Python 데이터 분석 생태계 |
| Authentication | streamlit-authenticator / custom | streamlit-authenticator | 검증된 라이브러리, YAML 기반 사용자 관리 |
| Data Storage | pkl / SQLite / PostgreSQL | pkl + Excel | 분석 프로젝트 특성상 파일 기반이 적합, DB 추후 고려 |
| Charting | Plotly / Altair / Matplotlib | Plotly | 인터랙티브 차트, hover 기능, 이전 프로젝트 일관성 |
| Macro Data | FRED API / 한국은행 API / Yahoo Finance | FRED + yfinance + 한국은행 | 다양한 매크로 지표 커버리지 |
| Deployment | Local / Cloud (Streamlit Cloud) | Local → Streamlit Cloud | 초기 로컬 개발, 추후 클라우드 배포 |

### 6.3 Clean Architecture Approach

```
Selected Level: Dynamic

Folder Structure:
DB_OCIO_Webview/
├── app.py                    # Streamlit 메인 앱 (인증 + 라우팅)
├── data/                     # 데이터 파일 (pkl, xlsx, csv)
│   ├── portfolios/           # 펀드별 포트폴리오 데이터
│   ├── macro/                # 매크로 지표 데이터
│   └── reports/              # 운용보고서 (PDF)
├── modules/
│   ├── auth.py               # 인증/세션 관리
│   ├── data_loader.py        # 데이터 로딩/전처리
│   ├── brinson.py            # Brinson 성과분석 엔진
│   ├── macro_tracker.py      # 매크로 지표 수집/분석
│   └── portfolio_analytics.py # 포트폴리오 분석 (MP Gap 등)
├── tabs/
│   ├── tab_overview.py       # 탭1: 펀드 Overview
│   ├── tab_holdings.py       # 탭2: 편입종목 현황 & MP Gap
│   ├── tab_attribution.py    # 탭3: Brinson 성과분석
│   ├── tab_macro.py          # 탭4: 매크로 지표 연동
│   ├── tab_report.py         # 탭5: 운용보고서 & 운용계획
│   └── tab_admin.py          # 탭6: 내부 운용팀 전용 (관리)
├── config/
│   └── users.yaml            # 사용자 인증 정보
├── CLAUDE.md
├── requirements.txt
└── docs/
    ├── 01-plan/
    ├── 02-design/
    ├── 03-analysis/
    └── 04-report/
```

---

## 7. Convention Prerequisites

### 7.1 Conventions to Define

| Category | Rule | Priority |
|----------|------|:--------:|
| **Naming** | snake_case (Python), 한국어 주석 + 영문 금융용어 병기 | High |
| **Folder structure** | modules/ (엔진), tabs/ (UI), data/ (데이터) 분리 | High |
| **Data format** | pkl (대용량), xlsx (입력), csv (매크로) | High |
| **Chart style** | Plotly 기본, PORT_COLORS 통일, 한글 라벨 | Medium |
| **Error handling** | 데이터 미존재 시 st.warning/st.error 표시 | Medium |

### 7.2 Environment Variables

| Variable | Purpose | Scope |
|----------|---------|-------|
| `FRED_API_KEY` | FRED 매크로 데이터 API 키 | Server |
| `BOK_API_KEY` | 한국은행 API 키 | Server |
| `ADMIN_PASSWORD` | 내부 관리자 비밀번호 | Server |

---

## 8. User Roles & Workflow

### 8.1 User Roles

| Role | Access | Features |
|------|--------|----------|
| **고객 (Client)** | 본인 펀드만 | Overview, Holdings, Attribution, Macro, Report |
| **내부 운용팀 (Ops)** | 전체 펀드 | 모든 탭 + Admin 탭 + 크로스 펀드 분석 |
| **관리자 (Admin)** | 시스템 관리 | 사용자 관리, 데이터 업로드 |

### 8.2 Client Workflow

```
로그인 → 본인 펀드 선택 (다수 가입 시) → 탭 탐색
  ├── Overview: 펀드 요약, NAV 추이, 수익률
  ├── Holdings: 편입종목, 비중, MP Gap
  ├── Attribution: Brinson 분석, 종목 기여도
  ├── Macro: 관련 매크로 지표 연동
  └── Report: 운용보고서, 향후 운용계획
```

---

## 9. Implementation Phases

| Phase | Description | Priority | Dependency |
|-------|-------------|----------|------------|
| Phase 1 | 데이터 구조 설계 + 샘플 데이터 생성 | High | - |
| Phase 2 | 인증 시스템 (로그인/세션/권한) | High | Phase 1 |
| Phase 3 | Overview + Holdings 탭 (편입종목, MP Gap) | High | Phase 1 |
| Phase 4 | Brinson 성과분석 엔진 + Attribution 탭 | High | Phase 3 |
| Phase 5 | 매크로 지표 수집 + Macro 탭 | Medium | Phase 1 |
| Phase 6 | 운용보고서/계획 탭 | Medium | Phase 2 |
| Phase 7 | 내부 운용팀 Admin 탭 | Low | Phase 2,3,4 |
| Phase 8 | 통합 테스트 + 폴리시 | Low | All |

---

## 10. R Shiny Benchmark (General_Backtest 코드베이스 분석)

### 10.1 데이터 인프라 (마이그레이션 대상)

| R 모듈 | 기능 | Python 대응 |
|--------|------|-------------|
| `module_00_data_loading.R` | MariaDB 3개(SCIP,dt,cream)+ECOS API | `modules/data_loader.py` — pymysql/SQLAlchemy |
| 6+1 데이터 소스 | SCIP/BOS/ZEROIN/ECOS/RATB/CUSTOM/USER | 동일 DB 테이블 직접 쿼리 |
| 한국 영업일 캘린더 | dt.DWCI10220 | pandas 영업일 처리 + DB 캘린더 |
| USDKRW 환율 | ECOS API + SCIP F_USDKRW | 동일 API/DB 소스 |

### 10.2 핵심 계산 로직 (1:1 Python 변환)

| R 함수 | 핵심 로직 | Python 구현 노트 |
|--------|----------|-----------------|
| `long_form_raw_data_input()` | 6개 소스 → wide-form 가격 시계열, T-1 lag | pandas pivot + shift(1) for foreign assets |
| `calculate_BM_results_bulk_for_users()` | 일별 수익률, FX 조정, 비용 차감, Fixed/Drift weight | numpy vectorized 계산 |
| `backtesting_for_users_input()` | 리밸런싱 구간별 백테스트, 턴오버 계산 | 동일 로직 pandas 구현 |
| FX 조정 공식 | `(1+r)*(1+FX_r*(1-hedge)*(region!="KR"))-1` | 동일 수식 |
| 환헤지 비용 | `hedge_ratio * (spot_return - forward_return)` | 동일 수식 |
| 비용 차감 | `-cost_bp/10000/365` 일별 | 동일 수식 |

### 10.3 Brinson PA (1:1 Python 변환)

| R 함수 | 핵심 로직 | Python 구현 노트 |
|--------|----------|-----------------|
| `BM_preprocessing()` | 백테스트 결과 → PA 입력 변환 | pandas DataFrame 변환 |
| `General_PA()` | Brinson 3-factor (Alloc/Select/Cross) + 보정인자 | 동일 수식, FX_split 옵션 포함 |
| `Portfolio_analysis()` | sec별/자산군별 기여수익률, Normalized 수익률 | pandas groupby + cumulative return |
| `get_PA_source_data()` | dt.MA000410 펀드 PA 원천 데이터 | pymysql 직접 쿼리 |
| `PA_from_MOS()` | DWPM10530 보유종목, 모자펀드, ETF 보정 | 동일 DB 쿼리 + 로직 |
| 자산군 분류체계 | `universe_non_derivative_table.classification_method` | solution DB 매핑 테이블 |

### 10.4 시각화 매핑 (R → Python)

| R 라이브러리 | 용도 | Python 대응 |
|-------------|------|-------------|
| echarts4r | 누적수익률/기여수익률 차트 | Plotly (line/bar chart) |
| highcharter | 순자산비중 stacked area + drilldown | Plotly (stacked area) |
| gt | Brinson 결과 테이블 | pandas Styler / st.dataframe |
| reactable | 자산군→종목 확장 테이블 | st.dataframe with AgGrid |
| DT | 편집 가능 테이블 | st_aggrid / st.data_editor |

### 10.5 DB 테이블 참조 (직접 쿼리 대상)

| DB.Table | 용도 | 주요 컬럼 |
|----------|------|----------|
| SCIP.back_datapoint | 지수/가격 원천 | dataset_id, dataseries_id, data(JSON) |
| dt.DWPM10510 | 펀드 수정기준가 | FUND_CD, STD_DT, MOD_STPR |
| dt.DWPM10530 | 펀드 보유종목 | FUND_CD, ISIN, 순자산비중 |
| dt.MA000410 | 펀드 PA 원천 | FUND_CD, 자산구분, 평가금액, 수익률 |
| dt.DWCI10220 | 한국 영업일 캘린더 | CAL_DT, HOLI_FG |
| cream.data | 제로인 펀드 데이터 | 기준일자, SUIK_JISU |
| solution.universe_non_derivative | 자산 유니버스 + 분류체계 | dataset_id, classification_method, classification |

---

## 11. Next Steps

1. [x] Plan 문서 작성
2. [x] R 코드베이스 벤치마크 분석 완료
3. [ ] Design 문서 작성 (`DB_OCIO_Webview.design.md`)
4. [ ] 팀 리뷰 및 승인
5. [ ] 구현 시작 (Phase 1부터)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-12 | Initial draft | Claude Code (CTO Lead) |
| 0.2 | 2026-02-12 | R 코드베이스 벤치마크 분석 추가 (Section 10) | Claude Code |
