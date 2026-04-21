# /home/scip-r/running_MP_monitor.sh
library(shiny)
library(writexl) # Excel 파일 작성을 위해
library(tidyverse)
library(ecos)
# 각 패널 탭 스크립트 소스
#source("03_MP_monitor/calculate_PP.R")
#source("03_MP_monitor/connect_Database.R")
#source("03_MP_monitor/connect_Database_full_auto.R")
Fund_Information <-  tibble(
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  구분= c("TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","BF","BF","BF")
)

tictoc::tic()


source("/home/scip-r/MP_monitoring/03_MP_monitor/connect_Database_full_auto_ver6.R")
source("/home/scip-r/MP_monitoring/03_MP_monitor/panel3_tab.R")
source("/home/scip-r/MP_monitoring/03_MP_monitor/performance_module_v6.R")
source("/home/scip-r/MP_monitoring/03_MP_monitor/position_module_v6.R")
tictoc::toc()


excludedDates<- KOREA_holidays$`Holiday Date`

# UI 정의

ui <- fluidPage(
  # 전역 날짜 선택기를 항상 표시
  
  tagList(
    navbarPage(
      title = "MP monitoring",
      header = tagList(
        dateInput("globalDateInput", "기준일자 선택:", value = max(AP_performance_preprocessing %>% 
                                                               filter(!(wday(기준일자,label=FALSE) %in%c(1,7)) & 
                                                                        !(기준일자 %in% KOREA_holidays$`Holiday Date`) ) %>% 
                                                               pull(기준일자)),daysofweekdisabled = c(0,6),
                  min = min(AP_performance_preprocessing %>% 
                              filter(!(wday(기준일자,label=TRUE) %in%c("Sat","Sun")) & 
                                       !(기준일자 %in% KOREA_holidays$`Holiday Date`)) %>% 
                              pull(기준일자)),
                  max = max(AP_performance_preprocessing %>% 
                              filter(!(wday(기준일자,label=TRUE) %in%c("Sat","Sun")) & 
                                       !(기준일자 %in% KOREA_holidays$`Holiday Date`)) %>% 
                              pull(기준일자)),datesdisabled = excludedDates ),
        div(
          checkboxGroupInput("TDF_BF", label = "유형 선택:",inline = TRUE,choices = unique(Fund_Information$구분),selected = c("TDF","BF"))
        )
      ),
      
      tabPanel("Performance & Risk", performanceUI("performanceTab")),
      tabPanel("Position", positionUI("positionTab")),
      tabPanel("Inform", panel3UI("panel3"))
      
      # 필터링된 데이터를 표시할 탭# Inform 탭에 panel3UI를 사용합니다.
    )
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
  panel3Server("panel3")
}
# Shiny 앱 실행
shinyApp(ui = ui, server = server, options = list(host = '0.0.0.0', port = 7600))

