library(shiny)
library(writexl) # Excel 파일 작성을 위해
# 각 패널 탭 스크립트 소스
#source("03_MP_monitor/calculate_PP.R")
#source("03_MP_monitor/connect_Database.R")
source("03_MP_monitor/connect_Database_full_auto.R")
source("03_MP_monitor/panel3_tab.R")
source("03_MP_monitor/performance_module_v2.R")
# source("03_MP_monitor/position_module.R")
source("03_MP_monitor/position_module_v3.R")
# UI 정의



ui <- fluidPage(
  # 전역 날짜 선택기를 항상 표시
  tagList(
    navbarPage(
      title = "MP monitoring",
      header = tagList(
        dateInput("globalDateInput", "기준일자 선택:", value = max(AP_performance_preprocessing %>% 
                                                               filter(!(wday(기준일자,label=TRUE) %in%c("Sat","Sun"))) %>% 
                                                               pull(기준일자)),daysofweekdisabled = c(0,6),
                  min = min(AP_performance_preprocessing %>% 
                              filter(!(wday(기준일자,label=TRUE) %in%c("Sat","Sun"))) %>% 
                              pull(기준일자)),
                  max = max(AP_performance_preprocessing %>% 
                              filter(!(wday(기준일자,label=TRUE) %in%c("Sat","Sun"))) %>% 
                              pull(기준일자)) )  # 주말 선택불가)
      ),
      tabPanel("Performance & Risk", performanceUI("performanceTab")),
      tabPanel("Position", positionUI("positionTab")),
      tabPanel("Inform", panel3UI("panel3"))  # Inform 탭에 panel3UI를 사용합니다.
    )
  )
)

# 서버 함수 정의
server <- function(input, output, session) {
  # 각 탭의 서버 로직 호출
  global_date <- reactive({ input$globalDateInput })
  
  performanceServer("performanceTab", global_date)
  positionServer("positionTab", global_date)
  panel3Server("panel3")  # panel3 모듈을 호출합니다.
}

# Shiny 앱 실행
#shinyApp(ui, server)
shinyApp(ui = ui, server = server, options = list(host = '0.0.0.0', port = 7600))

