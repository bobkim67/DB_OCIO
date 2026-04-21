# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

R Shiny 기반 포트폴리오 백테스팅 및 사후분석(Performance Attribution) 웹 애플리케이션.
DB OCIO(Outsourced CIO) 자산운용 실무에서 사용하는 범용 백테스트 도구.

## Running the App

```bash
# 메인 Shiny 앱 실행 (서버 배포 경로: /home/scip-r/General_Backtest)
# app 파일이 setwd('/home/scip-r/General_Backtest')를 호출하므로 해당 경로에서 실행 필요
Rscript -e "shiny::runApp('03_General_Backtest/app_General_Backtest_사후모듈확장.R', port=7601, host='0.0.0.0')"

# 플러머 버전 (간소화된 독립 실행형)
Rscript -e "shiny::runApp('11_plumber_functioning/backtest_for_users_app.R')"
```

## Architecture

### Data Flow (시작 → 결과)

1. **DB 접속 → 원시 데이터 로딩** (`module_00_data_loading.R`): MariaDB 3개 DB(SCIP, dt, cream) + ECOS API + Custom 파일에서 가격 데이터/캘린더/환율 수집
2. **데이터 전처리** (`module_00_Function_v3.R::long_form_raw_data_input`): 6개 소스(SCIP/BOS/ZEROIN/ECOS/RATB/CUSTOM + 선택적 USER) → wide form 가격 시계열 결합, T-1 lag 처리(해외), 환율 병합
3. **백테스트 엔진** (`module_00_Function_v3.R::backtesting_for_users_input`): 리밸런싱 구간별 Fixed/Drift Weight 수익률 계산, 환헤지 비용 적용, 포트폴리오 가중합 → 결과 3-tuple (desc, core, raw)
4. **결과 시각화** (`module_02_results_page_v2.R`): 누적수익률, Drawdown, 버블차트, 주간/월간 성과 테이블
5. **사후분석** (`module_03_post_analysis(PA).R` + `04_사후분석/`): Brinson Attribution (Allocation/Selection/Cross Effect), 펀드 단위 PA

### Module Structure (Shiny Modules)

앱 진입점: `03_General_Backtest/app_General_Backtest_사후모듈확장.R`

| Module | UI/Server | Role |
|--------|-----------|------|
| `module_00_data_loading.R` | (startup script) | DB 접속, 6개 데이터 소스 로딩, `data_information` 마스터 테이블 생성 |
| `module_00_Function_v3.R` | (function library) | 핵심 계산 함수 모음 (~1700줄). 백테스트 엔진, 차트 생성, 성과지표 계산 |
| `module_01_edit_execute_v5.R` | `mod_edit_execute_*` | 유니버스 검색, 포트폴리오 편집 테이블(DT), 백테스트 실행 트리거 |
| `module_02_results_page_v2.R` | `mod_results_page_*` | 분석 기간 설정, 누적수익률/DD 차트(echarts4r), 성과 테이블, 엑셀 다운로드 |
| `module_03_post_analysis(PA).R` | `mod_performance_attribution_*` | Brinson PA: 펀드 선택 → BM 매핑 → 자산군별 기여도 분석 |

### Key Data Objects (Global Scope)

- `data_information`: 전체 유니버스 마스터 테이블 (dataset_id, dataseries_id, region, source, colname_backtest)
- `holiday_calendar` / `selectable_dates` / `KOREA_holidays`: 한국 영업일 캘린더
- `USDKRW` / `F_USDKRW_Index`: 원달러 현물/선물 환율 시계열
- `backtest_results`: reactiveVal — 모듈 간 백테스트 결과 전달 매개체
- `USER_historical_price`: 사용자 업로드 가격 데이터 (NULL이면 미사용)

### Data Sources (6+1)

| Source | DB/API | dataseries_id | Price Column |
|--------|--------|---------------|--------------|
| SCIP (Factset/Bloomberg/KIS) | MariaDB `SCIP.back_datapoint` | 6,9,15,33,45,48 | JSON parsed |
| BOS (펀드 수정기준가) | MariaDB `dt.DWPM10510` | MOD_STPR | MOD_STPR |
| ECOS (한국은행 금리) | ECOS API | Custom_index | 복리지수 변환 |
| ZEROIN (제로인 펀드) | MariaDB `cream.data` | SUIK_JISU | price |
| RATB (로보어드바이저) | MariaDB `SCIP.back_datapoint` id=62 | standardPrice | standardPrice |
| CUSTOM (현금 등) | 로컬 | Custom_index | 기준가_custom |
| USER (선택적) | 사용자 업로드 | User_input | price_custom |

### Backtest Calculation Logic

- **Region 기반 T-1 처리**: `region != "KR"` → 해외 자산은 전일(T-1) 가격 사용 (시차 반영)
- **Weight 방식**: Fixed Weight (리밸런싱일 비중 고정) vs Drift Weight (비중 자연 변동)
- **환헤지**: `hedge_ratio` 비율만큼 환 수익률 차감, `hedge_cost_strictly` 옵션으로 선물환 비용 적용
- **비용 조정**: `cost_adjust` (연 bp 단위) → 일별 차감
- **tracking_multiple**: 레버리지/인버스 배수 적용

### 04_사후분석/ (Performance Attribution)

- `func_펀드_PA_모듈_adj_GENERAL_final.R`: 펀드별 PA 소스 데이터 추출 (dt.MA000410), 자산군 매핑, Brinson 3-factor 분해
- `func_PA_결합및요약용_final.R`: `BM_preprocessing()` — 백테스트 결과를 PA 입력 형식으로 변환
- `func_brinson_figures.R`: Brinson Attribution 결과 테이블/차트 (gt, echarts4r)
- `func_single_port_figures.R`: 단일 포트폴리오 요약 테이블 (reactable), 자산군별 기여수익률

### 11_plumber_functioning/ (Standalone Version)

`backtest_for_users_app.R`: 사후분석 없는 간소화 버전. `backtest_for_users_v2.R`에서 자체 데이터 로딩 수행 (SCIP + BOS만 사용).

### 지난파일/ (Archive)

이전 버전 모듈들. 참조용으로만 사용. 현재 코드에서 source하지 않음.

## Dependencies

R packages: shiny, tidyverse, lubridate, DT, echarts4r, bslib, reactable, writexl, clipr, shinyjs, inspectdf, plotly, scales, ecos, DBI, RMariaDB, blob, RColorBrewer, jsonlite, timetk, fuzzyjoin, highcharter, htmltools, shinyWidgets, gt, rhandsontable, colorspace

External: MariaDB (192.168.195.55), ECOS API

## Coding Conventions

- 한국어 변수명/주석 사용 (금융 전문용어는 영문 병기)
- 함수명은 영문 snake_case, 한국어 설명을 주석으로 병기
- 버전 관리: 파일명에 v2, v3 등 버전 번호 포함 (최신 버전만 app에서 source)
- `options(digits = 15)` 필수 — DB 가격 데이터 소수점 정밀도 보존
- 분석 코드이므로 과도한 모듈화 금지. 선형적이고 읽기 쉬운 코드 지향.

## Important Notes

- DB 접속 정보가 코드에 하드코딩되어 있음 (내부망 전용 도구)
- `setwd('/home/scip-r/General_Backtest')` — 서버 배포 환경 기준 경로
- `module_00_data_loading.R`은 앱 시작 시 전체 실행되며 수 분 소요될 수 있음 (DB 전체 로딩)
- ECOS API 키가 코드에 포함되어 있음
