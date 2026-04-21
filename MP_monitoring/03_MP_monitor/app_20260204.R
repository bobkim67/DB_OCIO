library(shiny)
library(writexl) # Excel 파일 작성을 위해
setwd('/home/scip-r/MP_monitoring')

# 각 패널 탭 스크립트 소스
#source("03_MP_monitor/calculate_PP.R")
#source("03_MP_monitor/connect_Database.R")
#source("03_MP_monitor/connect_Database_full_auto.R")
rm(list=ls())
tictoc::tic()
options(digits = 15) #이 옵션이 없으면 DB의 값을 자동으로 절삭해서 불러오게됨. 소수점15자리까지 불러오기
source("./03_MP_monitor/Function 모듈 20250703.R")
source("./03_MP_monitor/데이터 loading 모듈 확장성고려_260204.R")
source("./03_MP_monitor/데이터 Preprocessing 모듈 20260204.R")
source("./03_MP_monitor/inform_module_20250703.R")
source("./03_MP_monitor/performance_module_20250703.R")
source("./03_MP_monitor/position_module_20260204.R")
source("./05_Performance_Attribution/brinson_shiny_default_v7.R")
source("./05_Performance_Attribution/brinson_module_v5.R")
tictoc::toc()

excludedDates<- KOREA_holidays

# UI 정의
# 전체 UI 정의
ui <- fluidPage(
  tags$head(
    tags$style(HTML("
      /* --- 기존 스타일 유지 --- */
      .scrollable-graph-horizontal {
        width: 100;
        overflow-x: auto;
        overflow-y: hidden;
        border: 1px solid #ccc;
        padding: 10px;
      }
      .navbar {
        position: fixed;
        top: 0;
        width: 100%;
        z-index: 1000;
        margin-bottom: 0;
        border-radius: 0;
      }
      body > div.container-fluid {
        padding: 0;
      }
      body {
        margin-top: 0;
        padding-top: 50px;
      }
      body > div.container-fluid > div {
       margin: 0 15px;
      }
      
      /* ★★★★★ [수정됨] 체크박스 자동 줄바꿈 스타일 ★★★★★ */
      /* inline=TRUE로 설정된 체크박스 그룹을 강제로 줄바꿈 허용(wrap)하게 만듭니다 */
      #TDF_BF .shiny-options-group {
        display: flex;
        flex-wrap: wrap;  /* 공간이 부족하면 다음 줄로 내림 */
        gap: 10px;        /* 간격 조정 */
      }
      
      #TDF_BF .checkbox {
        margin: 0 !important; /* 불필요한 여백 제거 */
        display: flex;       /* 내용물 정렬 */
        align-items: center;
      }
      /* ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★ */
    "))
  ),
  
  navbarPage(
    title = "MP monitoring",
    id = "navbar",
    header = tagList(
      conditionalPanel(
        width = 2,
        # 사이드바 스크롤 설정 (내용이 길어지면 스크롤 생김)
        style = "position: fixed; top: 80px; width: 250px; overflow-y: auto; max-height: 85vh; padding-right: 5px;", 
        condition = "input.navbar == 'performance' || input.navbar == 'position'",
        
        # --- [1] 원래 날짜 로직 복구 ---
        div(
          dateInput("globalDateInput", "기준일자 선택:", 
                    value = max(AP_performance_preprocessing %>% 
                                  filter(!(wday(기준일자, label = FALSE) %in% c(1, 7)) & 
                                           !(기준일자 %in% KOREA_holidays)) %>% 
                                  pull(기준일자)), 
                    daysofweekdisabled = c(0, 6),
                    min = min(AP_performance_preprocessing %>% 
                                filter(!(wday(기준일자, label = TRUE) %in% c("Sat", "Sun")) & 
                                         !(기준일자 %in% KOREA_holidays)) %>% 
                                pull(기준일자)),
                    max = max(AP_performance_preprocessing %>% 
                                filter(!(wday(기준일자, label = TRUE) %in% c("Sat", "Sun")) & 
                                         !(기준일자 %in% KOREA_holidays)) %>% 
                                pull(기준일자)), 
                    datesdisabled = excludedDates)
        ),
        
        # --- [2] 원래 유형 선택 로직 복구 + inline=TRUE 유지 ---
        div(
          checkboxGroupInput("TDF_BF", 
                             label = "유형 선택:", 
                             inline = TRUE,  # ★중요: TRUE로 둬야 CSS flex가 잘 먹힘
                             choices = unique(Fund_Information$구분), # 원래 데이터 복구
                             selected = c("TDF", "BF", "ACETDF", "ActiveTDF", "Wrap"))
          
        )
      )
    ),
    tabPanel("Performance & Risk", performanceUI("performanceTab"), value = "performance"),
    tabPanel("Position", positionUI("positionTab"), value = "position"),
    tabPanel("Performance Attribution", PAUI("paTab"), value = "performance_attribution"),
    tabPanel("Inform", panel3UI("panel3"), value = "inform")
  )
)

# 서버 함수 정의
server <- function(input, output, session) {
  # 앱 종료 시 DB 연결 해제
  onStop(function() {
    try(dbDisconnect(con_dt), silent = TRUE)
    try(dbDisconnect(con_solution), silent = TRUE)
    try(dbDisconnect(con_SCIP), silent = TRUE)
  })
  
  global_date <- reactive({ input$globalDateInput })
  selectedCategory <- reactive({
    
    Fund_Information %>%
      filter(구분 %in% input$TDF_BF) %>% pull(펀드설명)
  })
  
  performanceServer("performanceTab", global_date,selectedCategory)
  positionServer("positionTab", global_date,selectedCategory)
  PA_Server("paTab")
  panel3Server("panel3")
}
# Shiny 앱 실행
# shinyApp(ui, server)
shinyApp(ui = ui, server = server, options = list(host = '0.0.0.0', port = 7600))

