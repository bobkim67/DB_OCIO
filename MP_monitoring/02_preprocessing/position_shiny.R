library(tidyverse)
library(shiny)
library(plotly)
library(scales)
library(rlang) # sym() 함수를 사용하기 위해 필요

# 데이터 불러오기
AP_total <- 
  bind_rows(
    readxl::read_excel("00_data/통합 명세_AP.xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)),
    readxl::read_excel("00_data/통합 명세_AP_(20231202_20240109).xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)) %>% 
      filter(기준일자<="2024-01-09")
  )

AP_fund_name<- tibble(
  펀드 = c("07M02",	"07J66",	"07J71",	"07J76",	"07J81",	"07J86",	"07J91",	"07J96",	"07J41",	"07J34"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"MS STABLE",	"MS GROWTH"))

VP_total <- 
  bind_rows(
    readxl::read_excel("00_data/통합 명세_VP.xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)),
    readxl::read_excel("00_data/통합 명세_VP_(20231202_20240109).xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)) %>% 
      filter(기준일자<="2024-01-09")
  )

VP_fund_name<- tibble(
  펀드 = c("2MP24",	"1MP30",	"1MP35",	"1MP40",	"1MP45",	"1MP50",	"1MP55",	"1MP60",	"3MP01",	"3MP02"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"MS STABLE",	"MS GROWTH"))



universe_criteria <- read_csv("00_data/universe_criteria.csv", locale = locale(encoding = "CP949")) |> 
  distinct() %>% 
  # 23년 말 기준으로 새롭게 편입된 US 금 두 종목 존재. universe DB에 업데이트
  bind_rows(
    tribble( ~종목코드, ~종목명,~자산군_대,~자산군_중,~자산군_소,
             "US98149E3036", "SPDR GOLD MINISHARES TRUST" , "대체","원자재","금",  
             "US46436F1030", "ISHARES GOLD TRUST MICRO"   , "대체","원자재","금"
    )
  )


asset_classification_and_adjust <- function(data){
  # 조인 조건 정의
  join_condition <- join_by(종목 == 종목코드, 종목명)
  
  # 조인 수행
  data_joined <- data %>% 
    left_join(universe_criteria, by = join_condition) 
  
  return(data_joined)
  # data_asset_adjust<- data_joined %>% 
  #   mutate(자산군_중 = if_else(자산군_대=="대체","대체",자산군_중)) %>% 
  #   mutate(자산군_소 = if_else(자산군_대=="대체","대체",자산군_소))
  
  #return(data_asset_adjust)
}


AP_asset_adjust<- asset_classification_and_adjust(AP_total)
VP_asset_adjust<- asset_classification_and_adjust(VP_total)



calculate_portfolio_weights <- function(data, asset_group ,division) {
  # 먼저, 자산군 별로 순자산비중을 계산
  daily_weights <- data %>%
    filter(자산군_대 != "유동성") %>% 
    mutate(순자산비중 = 시가평가액 / 순자산) %>%
    group_by(기준일자, 펀드, !!sym(asset_group)) %>%
    summarise(daily_weight = sum(순자산비중, na.rm = TRUE), .groups = 'drop')
  
  if(division=="VP"){
    return(daily_weights)
  }else{
    feeder_fund <- daily_weights %>% 
      # 자펀드 비중
      filter(펀드 %in% c("07J48","07J49")) %>% 
      pivot_wider(
        names_from = 펀드,
        values_from = daily_weight,
        values_fill = list(daily_weight = 0)) 
    
    master_fund<- daily_weights %>% 
      #모펀드 비중
      filter(펀드 %in% c("07J34","07J41")) %>%
      pivot_wider(
        names_from = !!sym(asset_group),
        values_from = daily_weight,
        names_prefix = "ratio_")
    
    
    master_fund %>% inner_join(feeder_fund,relationship = "many-to-many") %>% 
      mutate(daily_weight = ratio_07J48*`07J48`+ratio_07J49*`07J49`) %>% 
      select(기준일자,펀드,!!sym(asset_group),daily_weight)->mysuper_position
    
    # 최종 포트폴리오 가중치 데이터 프레임 생성
    
    daily_weights %>% 
      filter(!(펀드 %in% c("07J34","07J41","07J48","07J49"))) %>% 
      bind_rows(mysuper_position)  ->final_weights
    
    return(final_weights)
  }
  
  
}


# Shiny UI 정의
ui <- navbarPage(
  "MP monitoring",
  tabPanel("Performance", 
           # Performance 관련 내용을 여기에 추가
  ),
  tabPanel("Position", 
           sidebarLayout(
             sidebarPanel(
               dateInput("dateInput", "기준일자 선택:", value = Sys.Date()),
               radioButtons("assetGroupSelect", "자산군:",
                            choices = c("소" = "자산군_소", "대" = "자산군_대"),
                            inline = TRUE)
             ),
             mainPanel(
               plotlyOutput("plotAP"),
               plotlyOutput("plotVP"),
               plotlyOutput("diffPlot") # 히트맵 추가
             )
           )
  ),
  tabPanel("Risk", 
           # Risk 관련 내용을 여기에 추가
  )
  # 다른 탭들도 여기에 추가 가능
)


# Shiny 서버 로직 정의
server <- function(input, output) {
  
  # AP와 VP의 포지션 데이터 계산을 위한 reactive 표현식
  position_AP <- reactive({
    calculate_portfolio_weights(
      data = AP_asset_adjust,
      asset_group = input$assetGroupSelect,
      division = "AP"
    )
  })
  
  position_VP <- reactive({
    calculate_portfolio_weights(
      data = VP_asset_adjust,
      asset_group = input$assetGroupSelect,
      division = "VP"
    )
  })
  
  # AP 대시보드 출력
  
  output$plotAP <- renderPlotly({
    # AP 데이터 비중 계산
    asset_group_sym <- sym(input$assetGroupSelect)
    position_AP <- position_AP() %>%
      filter(기준일자 == input$dateInput) %>%
      left_join(AP_fund_name, by = "펀드")
    
    # AP 그래프 생성
    # ggplot 그래프 생성
    p <- ggplot(position_AP, aes_string(x = "펀드설명", y = "daily_weight", fill = as.character(asset_group_sym))) +
      geom_bar(stat = "identity", position = "stack", alpha = 0.8) +
      geom_text(aes(label = scales::percent(daily_weight, accuracy = 0.01)), 
                position = position_stack(vjust = 0.5), 
                color = "black", 
                size = 3) +
      scale_y_continuous(labels = scales::percent_format(), limits = c(0, 1)) +
      theme_minimal() +
      labs(title = paste("선택된 날짜:", input$dateInput, "- 펀드별 자산군 비중(AP)"),
           x = "펀드",
           y = "비중")
    
    ggplotly(p)
  })
  
  # VP 대시보드 출력
  output$plotVP <- renderPlotly({
    # VP 데이터 비중 계산
    asset_group_sym <- sym(input$assetGroupSelect)
    position_VP <- position_VP() %>%
      filter(기준일자 == input$dateInput) %>%
      left_join(VP_fund_name, by = "펀드")
    
    # VP 그래프 생성
    p <- ggplot(position_VP, aes_string(x = "펀드설명", y = "daily_weight", fill = as.character(asset_group_sym))) +
      geom_bar(stat = "identity", position = "stack", alpha = 0.8) +
      geom_text(aes(label = scales::percent(daily_weight, accuracy = 0.01)), 
                position = position_stack(vjust = 0.5), 
                color = "black", 
                size = 3) +
      scale_y_continuous(labels = scales::percent_format(), limits = c(0, 1)) +
      theme_minimal() +
      labs(title = paste("선택된 날짜:", input$dateInput, "- 펀드별 자산군 비중(VP)"),
           x = "펀드",
           y = "비중")
    
    ggplotly(p)
  })
  # AP와 VP의 비중 차이를 시각화하는 그래프 생성
  output$diffPlot <- renderPlotly({
    # 선택한 자산군에 따라 AP와 VP의 포지션 데이터를 계산
    position_AP <- position_AP()
    position_VP <- position_VP()
    
    
    # position_AP와 position_VP를 펀드설명을 기준으로 full_join하고 차이 계산
    AP_VP_diff <- full_join(position_AP %>% 
                              left_join(AP_fund_name),
                            position_VP %>% 
                              left_join(VP_fund_name), 
                            by = c("기준일자", "펀드설명", input$assetGroupSelect), 
                            suffix = c("_AP", "_VP")) %>%
      mutate(across(starts_with("daily_weight"), ~replace_na(., 0))) %>%
      mutate(Active_vs_VP = daily_weight_AP - daily_weight_VP) 
    
    
    
    if(input$assetGroupSelect=="자산군_대"){
      AP_VP_diff<- AP_VP_diff %>% 
        filter(기준일자 == input$dateInput) %>%
        group_by(펀드설명, !!sym(input$assetGroupSelect) ) %>%
        summarise(Active_vs_VP = sum(Active_vs_VP)) 
      
    }else{
      AP_VP_diff <- AP_VP_diff %>% 
        left_join(universe_criteria %>% select(자산군_대, 자산군_소) %>% distinct()) %>% 
        mutate(자산군_대 = if_else(is.na(자산군_대),"대체",자산군_대)) %>% 
        filter(기준일자 == input$dateInput) %>%
        group_by(펀드설명, !!sym(input$assetGroupSelect) ) %>%
        summarise(Active_vs_VP = sum(Active_vs_VP)) 
    }
    
    
    
    # ggplot 그래프 생성
    p <- ggplot(AP_VP_diff, aes(x = 펀드설명, y = Active_vs_VP, fill = !!sym(input$assetGroupSelect))) +
      geom_bar(stat = "identity", width = 0.75, position = "dodge") +
      geom_hline(yintercept = 0.05, color = "red", linetype = "dashed") +
      geom_hline(yintercept = -0.05, color = "red", linetype = "dashed") +
      scale_y_continuous(labels = scales::percent) + # y축 레이블을 백분율로 변경
      theme_minimal() +
      labs(title = "AP vs. VP Active Weight Difference", x = "Fund Description", y = "Weight Difference")
    
    ggplotly(p)
  })
  
}

# Shiny 애플리케이션 실행
shinyApp(ui = ui, server = server)
