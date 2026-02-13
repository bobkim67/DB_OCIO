# app_Backtest.R ---------------------
library(shiny)
library(tidyverse)
library(lubridate)
library(DT)
library(clipr)
library(echarts4r)
library(writexl)
library(bslib)
library(reactable)
rm(list=ls())
options(digits = 15) #이 옵션이 없으면 DB의 값을 자동으로 절삭해서 불러오게됨. 소수점15자리까지 불러오기
#e_common(font_family = "helvetica", theme = "westeros")
setwd('/home/scip-r/General_Backtest')
gc()


# sb_back           : 기본 편집 테이블 초기값
sb_back <- tribble(
  ~리밸런싱날짜, ~Portfolio,~name,~분석시작가능일, ~dataset_id, ~dataseries_id, ~region, ~weight,  ~hedge_ratio, ~cost_adjust,
  
  "2024-04-08","KOSPI",         "KOSPI Index", ymd("2000-01-04")  , "253","9","KR",1,0,0,
  "2024-04-08","NASDAQ100",     "NASDAQ100 Total Return Index", ymd("2000-01-05")  , "272","9","ex_KR",1,0,0,
  "2024-04-08","S&P500",        "S&P 500 Index", ymd("2000-01-05")  , "271","6","ex_KR",1,0,0,
  "2024-04-08","골드 2080",     "한국투자TDF알아서골드2080증권투자신탁(혼합-재간접형)(모)", ymd("2024-04-08")  , "07Q93","MOD_STPR","KR",1,0,0,
  "2024-04-08","주식:채권=6:4", "MSCI ACWI Gross Total Return Index", ymd("2000-01-05")  , "57","9","ex_KR",0.6,0,0,
  "2024-04-08","주식:채권=6:4", "Bloomberg Global Aggregate Total Return Index (Unhedged)", ymd("2000-01-05")  , "58","9","ex_KR",0.4,1,0
  
) %>%
  mutate(리밸런싱날짜 = ymd(리밸런싱날짜)) %>% 
  mutate(tracking_multiple = 1)


# ---------------------------------------------------------
#source("03_General_Backtest/module_00_Function_v2.R")
source("03_General_Backtest/module_00_Function_v3.R")
source("03_General_Backtest/module_00_data_loading.R")
# 모듈 소스 불러오기
# source("03_General_Backtest/module_01_edit_execute_v4.R")
source("03_General_Backtest/module_01_edit_execute_v5.R")
source("03_General_Backtest/module_02_results_page_v2.R")
source("03_General_Backtest/module_03_post_analysis(PA).R")
source("04_사후분석/func_PA_결합및요약용_final.R")
source("04_사후분석/func_펀드_PA_모듈_adj_GENERAL_final.R")
source("04_사후분석/func_brinson_figures.R")
source("04_사후분석/func_single_port_figures.R")
# app.R 파일

# ────────── 전체 UI (전면 수정) ──────────
ui <- navbarPage(
  title = "Portfolio Analysis", # 제목 변경 (예시)
  id = "tabs",
  
  # bslib 테마 적용 (앱 전체의 룩앤필을 담당)
  theme = bs_theme(
    version = 5,
    bootswatch = "zephyr", # 세련된 테마 선택 (e.g., "cerulean", "litera", "zephyr", "vapor")
    base_font = font_google("Inter"),
    heading_font = font_google("Roboto Slab")
  ),
  
  # --- 1. 편집 & 실행 탭 ---
  tabPanel(
    "편집 & 실행",
    icon = icon("edit"), # 아이콘 추가
    mod_edit_execute_ui("edit_execute")
  ),
  
  # --- 2. 결과 페이지 탭 ---
  tabPanel(
    "결과 페이지",
    icon = icon("chart-pie"), # 아이콘 추가
    mod_results_page_ui("results_page")
  ),
  
  # --- 3. 사후분석 탭 (드롭다운 메뉴) ---
  navbarMenu(
    "사후분석",
    icon = icon("magnifying-glass-chart"), # 아이콘 추가
    tabPanel(
      "Performance Attribution",
      mod_performance_attribution_ui("performance_attribution")
    ),
    tabPanel(
      "포트폴리오 비교",
      h3("포트폴리오 비교 분석"),
      p("... 내용 ...")
    ),
    tabPanel(
      "롤링 분석",
      h3("롤링 윈도우 분석"),
      p("... 내용 ...")
    )
  )
)

# ... 서버 로직 및 shinyApp 호출은 동일 ...
# ────────── 전체 서버 ──────────
# app_Backtest.R
server <- function(input, output, session) {
  
  
  # 1) 메인 서버에서 결과를 저장할 reactiveVal 생성
  backtest_results <- reactiveVal(NULL)
  
  # 아래와 같이 callModule 대신 직접 모듈 함수를 부릅니다.
  mod_edit_execute_server(
    id               = "edit_execute",  # 모듈 ID
    sb_back          = sb_back,
    data_information = data_information,
    backtest_results = backtest_results,
    parent_session   = session  # ← 탭 전환 위해 부모 세션 전달
  )
  
  mod_results_page_server(
    id               = "results_page",
    backtest_results = backtest_results
  )
  
  mod_performance_attribution_server(
    id = "performance_attribution", 
    backtest_results = backtest_results)
}

USER_historical_price <- NULL
shinyApp(ui = ui, server = server, options = list(host = '0.0.0.0', port = 7601))


# region 대신 lagging으로 바꿔서 T-1 처리, T-2처리 등등 더욱 확장 및 한국주식에도 환노출 적용해보기 가능----