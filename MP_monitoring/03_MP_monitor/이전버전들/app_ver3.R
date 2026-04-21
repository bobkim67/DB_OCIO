library(shiny)
library(writexl) # Excel 파일 작성을 위해
#setwd('/home/scip-r/MP_monitoring')

# 각 패널 탭 스크립트 소스
#source("03_MP_monitor/calculate_PP.R")
#source("03_MP_monitor/connect_Database.R")
#source("03_MP_monitor/connect_Database_full_auto.R")

setwd("/home/scip-r/MP_monitoring")
tictoc::tic()
source("./03_MP_monitor/Function 모듈_ACETDF.R")
source("/home/scip-r/MP_monitoring/03_MP_monitor/데이터 loading 모듈 ACETDF추가.R")
source("/home/scip-r/MP_monitoring/03_MP_monitor/데이터 Preprocessing 모듈 ACETDF_v3.R")
source("/home/scip-r/MP_monitoring/03_MP_monitor/inform_module.R")
source("./03_MP_monitor/performance_module_ACETDF.R")
# source("./03_MP_monitor/position_module_ACETDF_v2.R")
source("./03_MP_monitor/position_module_ACETDF_v3.R")
source("/home/scip-r/MP_monitoring/05_Performance_Attribution/brinson_shiny_default_v6.R")
source("/home/scip-r/MP_monitoring/05_Performance_Attribution/brinson_module_v5.R")
tictoc::toc()

excludedDates<- KOREA_holidays

# UI 정의
# 전체 UI 정의
ui <- fluidPage(
  tags$head(
    tags$style(HTML("
      .scrollable-graph-horizontal {
        width: 100; /* Set the height according to your needs */
        overflow-x: auto;
        overflow-y: hidden;
        border: 1px solid #ccc; /* Optional: Add a border for visual clarity */
        padding: 10px;
      }
      /* 네비게이션 바 고정 및 스타일 조정 */
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
      /* 상단 공백 제거 */
      body {
        margin-top: 0;
        padding-top: 50px; /* 네비게이션 바 높이에 맞게 조정 */
      }
      body > div.container-fluid > div {
       margin: 0 15px;
      }
    "))
  ),
  
  # 전역 날짜 선택기를 항상 표시
  navbarPage(
    title = "MP monitoring",
    id = "navbar",
    header = tagList(
      conditionalPanel(
        width = 2,
        style = "position: fixed;top: 80px;width: 250px;  overflow: auto;", 
        condition = "input.navbar == 'performance' || input.navbar == 'position'",
        div(
          dateInput("globalDateInput", "기준일자 선택:", value = max(AP_performance_preprocessing %>% 
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
                                pull(기준일자)), datesdisabled = excludedDates),
          div(
            checkboxGroupInput("TDF_BF", label = "유형 선택:", inline = TRUE, choices = unique(Fund_Information$구분), selected = c("TDF", "BF"))
          )
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
  # 각 탭의 서버 로직 호출
  
  
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

