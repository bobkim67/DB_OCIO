library(shiny)
library(shinyjs)
library(tidyverse)
library(DT)
library(lubridate)
library(echarts4r)
library(writexl)

mod_results_page_ui <- function(id) {
  ns <- NS(id)
  
  tabPanel(
    title = "결과 페이지",
    tags$head(
      # 테이블 헤더 스타일
      tags$style(HTML("
        table.dataTable thead th {
          white-space: nowrap; 
          transform: rotate(0deg) !important;
        }
      "))
    ),
    useShinyjs(),  # shinyjs 사용 선언
    
    # 상위 fluidRow: 높이를 고정하지 않고, 화면에 따라 스크롤
    fluidRow(
      style = "
        margin: 0; 
        padding: 15px;
      ",
      
      # ───────── 왼쪽 패널 ─────────
      column(
        width = 6,
        style = "
          background-color: #f7f7f7;
          border: 1px solid #ddd;
          border-radius: 5px;
          padding: 15px;
          margin-bottom: 15px;
        ",
        
        # 상단: 분석 시작일, 종료일과 그래프 선택
        fluidRow(
          # 왼쪽 반: 날짜 입력
          column(
            width = 6,
            style = "
            padding-right: 15px;
            border-right: 2px solid #ddd; /* 세로 선 추가 */",
            fluidRow(
              column(
                width = 6,
                dateInput(ns("analysis_start_date"), "분석 시작일",
                          value = ymd("1999-12-31"), 
                          #max = 최근영업일,
                          max = today()-days(1),
                          #daysofweekdisabled = c(0, 6), # 주말(일, 토) 비활성화
                          width = "90%")
              ),
              column(
                width = 6,
                dateInput(ns("analysis_end_date"), "분석 종료일",
                          value = today()-days(1),
                          #max = 최근영업일,
                          max = today()-days(1),
                          #daysofweekdisabled = c(0, 6), # 주말(일, 토) 비활성화
                          width = "90%")
              )
            ),
            radioButtons(
              inputId = ns("weight_type"), 
              label = "Weight Type",
              choices = c("Fixed Weight", "Drift Weight"),
              inline = TRUE
            )
          ),
          
          # 오른쪽 반: 그래프 종류 + Period(조건부) + 포트폴리오 선택
          column(
            width = 6,
            fluidRow(
              # 왼쪽: 개별 포트폴리오 그래프 선택
              column(
                width = 6,
                selectInput(ns("plot_choice"), "Performance 그래프 선택",
                            choices = c("누적수익률 & Drawdown", "Risk-Return Profile"))
              ),
              
              # 오른쪽: 포트폴리오 선택
              column(
                width = 6,
                conditionalPanel(
                  condition = sprintf("input['%s'] == 'Risk-Return Profile'", ns("plot_choice")),
                  selectInput(
                    ns("period"),
                    "Period 선택",
                    choices = c("YTD", "1M", "3M", "6M","9M" ,"1Y","18M","2Y","30M","3Y","4Y","5Y", "누적"),
                    selected = "누적"
                  )
                )
              )
            ),
            # selectInput(ns("plot_choice"), "Performance 그래프 선택",
            #             choices = c("누적수익률 & Drawdown", "Risk-Return Profile")),
            
            fluidRow(
              # 왼쪽: 개별 포트폴리오 그래프 선택
              column(
                width = 6,
                selectInput(ns("plot_choice_by_Portfolio"), "개별 포트폴리오 그래프 선택",
                            choices = c("Historical Position"#, "기여수익률"
                            ))
              ),
              
              # 오른쪽: 포트폴리오 선택
              column(
                width = 6,
                selectInput(ns("portfolio_select"), "포트폴리오 :",
                            choices = NULL,   # 동적 생성
                            selected = NULL)
              )
            )
          )
        ),
        
        # Weight Type, 세부사항(토글), 다운로드
        fluidRow(
          column(
            width = 12,
            
            actionButton(ns("toggle_advanced_settings"), "세부사항 조정", class = "btn-primary"),
            
            # 토글로 숨기는 세부사항 영역
            hidden(
              div(
                id = ns("advanced_settings"),
                selectInput(
                  ns("rf_dataset_id"), 
                  "Risk Free 수익률 선택",
                  choices = c(
                    unique(ECOS_historical_price$dataset_id),
                    "직접입력(%)"
                  ),
                  selected = "CD(91일)"
                ),
                conditionalPanel(
                  condition = sprintf("input['%s'] == '직접입력(%%)'", ns("rf_dataset_id")),
                  numericInput(ns("custom_rf"), "무위험수익률 상수값(%):", value = 0, width = "100%")
                ),
                selectInput(
                  ns("annualized_return_method"), 
                  "연율화수익률 방법",
                  choices = c(
                    "주간수익률평균" = "v1",
                    "주간로그수익률평균" = "v2",
                    "기간수익률기하평균" = "v3"
                  ),
                  selected = "v3"
                ),
                selectInput(
                  ns("annualized_risk_method"), 
                  "연율화위험 방법",
                  choices = c(
                    "주간수익률표준편차" = "v1",
                    "주간로그수익률표준편차" = "v2"
                  ),
                  selected = "v1"
                )
              )
            ),
            shinyjs::disabled(
              downloadButton(
                ns("download"), "결과 다운로드",
                icon = icon("file-excel"), class = "btn-success",
                width = "100%", style = "margin-top: 0px;" # 위 버튼과 간격 추가
              )
            )
            
          )
        ),
        
        # 결과 테이블 섹션
        fluidRow(
          column(
            width = 12,
            style = "
              padding: 15px;
              background-color: #ffffff;
              border: 1px solid #ddd;
              border-radius: 5px;
            ",
            selectInput(
              ns("result_table_select"), 
              "결과 테이블 선택",
              choices = c(
                "Reference Date"         = "결과1.Reference Date",
                "Total Days"             = "결과2.Total Days",
                "수익률"                 = "결과3.수익률",
                "연율화수익률"           = "결과4.연율화수익률",
                "연율화위험"             = "결과5.연율화위험",
                "무위험연율화수익률"     = "결과6.무위험연율화수익률",
                "수정샤프비율"           = "결과7.수정샤프비율",
                "Maximum Drawdown"       = "결과8.MDD"
              ),
              selected = "결과1"
            ),
            DTOutput(ns("result_table"))
          )
        )
      ),
      
      # ───────── 오른쪽 패널 ─────────
      column(
        width = 6,
        style = "
          background-color: #f7f7f7;
          border: 1px solid #ddd;
          border-radius: 5px;
          padding: 15px;
          margin-bottom: 10px;
        ",
        
        # 그래프 섹션 1
        fluidRow(
          column(
            width = 12,
            style = "
              padding: 15px;
              background-color: #ffffff;
              border: 1px solid #ddd;
              border-radius: 5px;
              margin-bottom: 15px;
            ",
            uiOutput(ns("plot_output"))
          )
        ),
        
        # 그래프 섹션 2 (Historical Position)
        fluidRow(
          column(
            width = 12,
            style = "
              padding: 15px;
              background-color: #ffffff;
              border: 1px solid #ddd;
              border-radius: 5px;
            ",
            echarts4rOutput(ns("historical_position_plot"))
          )
        )
      )
    )
  )
}



mod_results_page_server <- function(id, backtest_results) {
  moduleServer(id, function(input, output, session) {
    
    # result_tables_res를 reactiveValues로 정의
    result_tables_res_for_download <- reactiveVal()
    
    # 백테스트 결과가 변할 때마다 반응
    observeEvent(backtest_results(), {
      req(backtest_results())
      
      # 초기 날짜를 backtest_results에서 설정
      results <- backtest_results()
      
      # 예시: backtest_results()[[2]]에서 최소/최대 날짜 추출
      start_date <- ymd(min(backtest_results()[[1]]$리밸런싱날짜, na.rm = TRUE))
      # end_date <-최근영업일
      end_date <-today()-days(1)
      portfolio_lists <- unique(backtest_results()[[1]]$Portfolio)
      print(portfolio_lists)
      # 초기 날짜 설정 (여기서는 예시로 시작일을 최소값, 종료일을 최대값으로 설정)
      updateDateInput(session, "analysis_start_date", value = start_date)
      updateDateInput(session, "analysis_end_date", value = end_date)
      updateSelectInput(session, "portfolio_select",
                        choices = portfolio_lists,
                        selected =portfolio_lists[1] )
    })
    
    
    observeEvent(
      list(backtest_results(),
           input$analysis_start_date,  # start_date 추가
           input$analysis_end_date,
           input$weight_type,
           input$rf_dataset_id,           # 추가된 인자 반영
           input$custom_rf,
           input$annualized_return_method, # 추가된 인자 반영
           input$annualized_risk_method,    # 추가된 인자 반영
           input$period  # Period 추가
      ), {
        req(backtest_results())
        
        # 백테스트 결과 준비
        results_descriptrion <- backtest_results()[[1]]
        results_core         <- backtest_results()[[2]] %>% filter(기준일자>= ymd(input$analysis_start_date))
        results_raw          <- backtest_results()[[3]] %>% filter(기준일자>= ymd(input$analysis_start_date))
        
        # input$weight_type에 따라 다른 컬럼 선택
        if (input$weight_type == "Fixed Weight") {
          result_core_prep <- results_core %>%
            select(Portfolio, 기준일자, 리밸런싱날짜, contains("fixed")) %>%
            select(-(contains("Weight")&contains("T-1"))) %>% 
            set_names(c("Portfolio","기준일자","리밸런싱날짜","Return(T)","Weight(T)","turn_over"))
          
          
        } else {
          result_core_prep <- results_core %>%
            select(Portfolio, 기준일자, 리밸런싱날짜, contains("drift")) %>%
            select(-(contains("Weight")&contains("T-1"))) %>% 
            set_names(c("Portfolio","기준일자","리밸런싱날짜","Return(T)","Weight(T)","turn_over"))
          
        }
        
        # 사용자 RF 값 입력 처리
        rf_dataset_id_value <- if(input$rf_dataset_id == "직접입력(%)") {
          input$custom_rf # 사용자 정의 RF 값
        } else {
          NULL
        }
        
        # 결과 테이블 생성
        result_tables <- return_res_tables(
          result_core_prep = result_core_prep,
          input_date = input$analysis_end_date,
          rf_dataset_id = input$rf_dataset_id, 
          rf_custom_input = rf_dataset_id_value, # custom RF value 또는 선택된 dataset_id 사용
          annualized_return_method = input$annualized_return_method,  # 추가된 인자 반영
          annualized_risk_method = input$annualized_risk_method   # 추가된 인자 반영
        )
        result_tables_res_for_download(result_tables) # reactive 결과 저장
        # 결과 테이블 출력
        output$result_table <- renderDT({
          result_choice <- as.numeric(gsub("[^0-9]", "", input$result_table_select))
          
          selected_result <- 
            if (result_choice %in% c(1, 2)) {
              selected_result <- result_tables[[result_choice]]  # result_choice가 1 또는 2일 때는 그냥 데이터 반환
              datatable(selected_result,extensions = c('FixedColumns'),
                        options = list(
                          scrollX = TRUE,        # 가로 스크롤 활성화
                          scrollY = "500px",         # ✨ 1. 세로 스크롤 높이 지정
                          fixedColumns = list(leftColumns = 4),  # 왼쪽 세개 열을 고정(rowname때문에 +1)
                          pageLength = 10
                        )) 
              
            } else if (result_choice %in% c(3, 4, 5, 6, 8)) {
              selected_result <- result_tables[[result_choice]]    # result_choice가 3, 4, 5, 6일 때만 percent 적용
              datatable(selected_result,extensions = c('FixedColumns'),
                        options = list(
                          scrollX = TRUE,        # 가로 스크롤 활성화
                          scrollY = "500px",         # ✨ 1. 세로 스크롤 높이 지정
                          fixedColumns = list(leftColumns = 4),  # 왼쪽 세개 열을 고정(rowname때문에 +1)
                          pageLength = 10
                        )) %>%
                formatPercentage(columns = setdiff(names(selected_result), c("Portfolio", "분석시작일", "분석종료일")), digits = 2) %>% 
                formatStyle(
                  columns = setdiff(names(selected_result), c("Portfolio", "분석시작일", "분석종료일")),
                  color = styleInterval(0, c("blue", "red"))  # 값이 0보다 크면 빨간색, 작으면 파란색
                )
              
            } else if (result_choice == 7) {
              selected_result <- result_tables[[result_choice]] # result_choice가 7(샤프)일 때만 percent 미적용
              datatable(selected_result,extensions = c('FixedColumns'),
                        options = list(
                          scrollX = TRUE,        # 가로 스크롤 활성화
                          scrollY = "500px",         # ✨ 1. 세로 스크롤 높이 지정
                          fixedColumns = list(leftColumns = 4),  # 왼쪽 세개 열을 고정(rowname때문에 +1)
                          pageLength = 10       # 한 페이지에 표시할 행 수 (원하시는 대로 조정)
                          
                        )) %>%
                formatRound(columns = setdiff(names(selected_result), c("Portfolio", "분석시작일", "분석종료일")), digits = 2) %>% 
                formatStyle(
                  columns = setdiff(names(selected_result), c("Portfolio", "분석시작일", "분석종료일")),
                  color = styleInterval(0, c("blue", "red"))  # 값이 0보다 크면 빨간색, 작으면 파란색
                )
            }
        })
        
        
        # 그래프 1: 누적수익률 + Drawdown (echarts4r)
        output$plot_graph1 <- renderEcharts4r({
          plot_cum_return_and_Drawdown(
            perform_data = result_tables[["그래프1.Drawdown & Cummulative Return"]],
            input_date = input$analysis_end_date
          ) %>%
            e_title(paste("누적수익률 & Drawdown:", input$weight_type))
        })
        
        
        # 그래프 2: 임시 예시(base plot)
        output$plot_graph2 <- renderEcharts4r({
          plot_bubble_chart(annualized_inform_df = result_tables[["그래프2.Bubble"]],
                            period = input$period) %>% 
            e_title(text =str_glue("Risk-Return Profile: {isolate(input$weight_type)}({isolate(input$period)})" )) 
          
        })
      }
    )
    
    # -------- 그래프 선택에 따라 다른 output 보여주기 --------
    output$plot_output <- renderUI({
      req(input$plot_choice)
      # plot_choice에 따라 다른 그래프(Output)를 반환
      case_when(
        input$plot_choice == "누적수익률 & Drawdown" ~ echarts4rOutput(session$ns("plot_graph1")),
        input$plot_choice == "Risk-Return Profile" ~ echarts4rOutput(session$ns("plot_graph2"))
        # input$plot_choice == "누적수익률 & Drawdown" ~ echarts4rOutput(session$ns("plot_graph1"), height = "600px"),
        # input$plot_choice == "Risk-Return Profile" ~ echarts4rOutput(session$ns("plot_graph2"), height = "600px")
      ) 
    })
    
    
    
    # 2. 위에서 정의한 portfolio_data를 이용해 그래프를 렌더링 (reactive하게 업데이트됨)
    observeEvent(list(
      input$portfolio_select,
      input$weight_type,
      input$analysis_start_date,
      input$analysis_end_date
    ),
    {
      req(backtest_results())
      
      data <- backtest_results()[[2]] %>%
        filter(기준일자 >= ymd(input$analysis_start_date)) %>% 
        filter(기준일자 <= ymd(input$analysis_end_date))
      
      # 포트폴리오 선택에 따른 필터링
      if (!is.null(input$portfolio_select) && input$portfolio_select != "") {
        data <- data %>%
          filter(Portfolio == input$portfolio_select)
      }
      
      # input$weight_type에 따라 Fixed Weight 또는 Drift Weight 데이터로 필터링/가공
      if (input$weight_type == "Fixed Weight") {
        data <- data %>% 
          select(Portfolio, 기준일자, 리밸런싱날짜, contains("Weight_fixed")) %>%
          select(-(contains("Weight")&contains("T-1"))) %>% 
          set_names(c("Portfolio","기준일자","리밸런싱날짜","Weight(T)")) %>% 
          rename_with(~ gsub("\\(T\\)", "", .)) %>% 
          unnest_longer(col = Weight, values_to = "Weight", indices_to = "symbol")
        
        
      } else if (input$weight_type == "Drift Weight") {
        data <- data %>% 
          select(Portfolio, 기준일자, 리밸런싱날짜, contains("Weight_drift")) %>%
          select(-(contains("Weight")&contains("T-1"))) %>% 
          set_names(c("Portfolio","기준일자","리밸런싱날짜","Weight(T)")) %>% 
          rename_with(~ gsub("\\(T\\)", "", .)) %>% 
          unnest_longer(col = Weight, values_to = "Weight", indices_to = "symbol")
        
      }
      
      
      # 그래프 데이터 업데이트 (기존 그래프 코드에서 data 사용)
      output$historical_position_plot <- renderEcharts4r({
        data %>%
          mutate(기준일자 = as.factor(기준일자)) %>%
          group_by(symbol) %>%
          e_charts(기준일자) %>%
          e_bar(Weight, stack = "grp") %>%
          e_y_axis_(
            min = 0,
            max = 1,
            name = "비중(%)",
            formatter = e_axis_formatter("percent", digits = 2)
          ) %>%
          e_x_axis(
            min = min(ymd(data$기준일자)),
            max = max(ymd(data$기준일자))
          ) %>%
          e_tooltip(
            trigger = "axis",
            axisPointer = list(type = "cross"),
            formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
          ) %>%
          e_title("Historical Position", "") %>%
          e_legend(top = "bottom",type = "scroll") %>% 
          e_grid(bottom="20%") %>% 
          e_toolbox_feature(feature = "saveAsImage")
      })
    })
    
    
    # 다운로드 버튼
    output$download <- downloadHandler(
      filename = function() {
        paste0("backtest_results_", Sys.Date(),"_",isolate(input$weight_type), ".xlsx")
      },
      content = function(file) {
        req(backtest_results())
        req(result_tables_res_for_download())
        res<- backtest_results()
        
        #Performance
        res_performance <- res$`백테스트계산_Perform&Position` %>% 
          rename_with(~ gsub("weighted_sum", "Return", .)) %>% 
          select(-contains("Weight")) #%>% view() # Cummulative / MDD 성과 추가?
        
        #Position
        res_position <- res$`백테스트계산_Perform&Position` %>% 
          select(-contains("weighted_sum")) %>%
          rename_with(~ gsub("\\(T\\)", "", .)) %>% 
          pivot_longer(cols = starts_with("Weight_"),names_to = "구분") %>% 
          unnest_longer(col = value, values_to = "Weight", indices_to = "symbol") %>% 
          pivot_wider(id_cols = c(Portfolio,기준일자,리밸런싱날짜,symbol) , 
                      names_from = 구분, values_from = Weight) 
        
        #Raw   -raw_data열은 진짜 raw data이고 return은 환노출도에 따른 성과임.
        res_raw<- res$백테스트계산_raw %>% 
          select(-contains("lag")) %>% 
          rename_with(~ gsub("_list", "", .)) %>% 
          pivot_longer(cols = c(cummulative_return ,daily_return ,raw_data ),names_to = "구분") %>% 
          unnest_longer(col = value, values_to = "Raw_value", indices_to = "symbol") %>% 
          pivot_wider(id_cols = c(Portfolio,기준일자,리밸런싱날짜,symbol,`USD/KRW` ,`return_USD/KRW`) ,
                      names_from = 구분, 
                      values_from = Raw_value) 
        
        res_list = c(list("백테스트내역" = res$백테스트내역,
                          "Performance"  = res_performance,
                          "Position"     = res_position   ,
                          "Raw"          = res_raw),
                     result_tables_res_for_download())
        
        writexl::write_xlsx(res_list, file)
      }
    )
    
    # 세부사항 조정 토글 처리
    observeEvent(input$toggle_advanced_settings, {
      toggle(id = "advanced_settings")
    })
    
  })
}




