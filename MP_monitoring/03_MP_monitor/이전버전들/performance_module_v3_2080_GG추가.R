# performance_module.R 내의 performanceUI 함수
performanceUI <- function(id) {
  ns <- NS(id)
  tagList(
    sidebarLayout(
      sidebarPanel(
        selectInput(ns("fromWhenInput"), "기간 선택:", 
                    choices = c("YTD", "ITD", "최근 1년",
                                "최근 1주","최근 1개월","최근 3개월","최근 6개월"), 
                    selected = "YTD"),
        checkboxGroupInput(ns("selectedPlots"), "보고 싶은 분석 선택:",
                           choices = list("수익률" = "performance",
                                          "누적 수익률 추이" = "performance_historical",
                                          "변동성" = "volatility",
                                          "Return-to-Risk" = "riskAdjusted",
                                          "추적오차" = "trackingError",
                                          "정보비율" = "informationRatio",
                                          "샤프비율" = "sharpeRatio"),
                           selected = "performance"),
        # Excel 파일 다운로드 버튼 추가
        downloadButton(ns("downloadExcel"), "Download Excel"),
        width = 2  # sidebarPanel의 너비 조정
      ),
      mainPanel(
        uiOutput(ns("plotsOutput")) #, # 선택된 플롯들을 보여줄 UI Output
        #tableOutput(ns("filteredTable"))
      )
    )
  )
}

performanceServer <- function(id, global_date, selectedCategory) {
  moduleServer(id, function(input, output, session) {
    ns <- session$ns
    
    AP_performance_preprocessing_filtered <- reactive({
      filtered_data <- AP_performance_preprocessing %>% filter(펀드설명 %in% selectedCategory())
      filtered_data
    })
    
    AP_performance_shallow <- reactive({
      from_when <- input$fromWhenInput
      shallow_data <- AP_performance_preprocessing_filtered() %>%
        return_performance_shallow(global_date(), from_when)
      shallow_data
    })
    
    AP_performance_deep <- reactive({
      from_when <- input$fromWhenInput
      deep_data<- AP_performance_shallow() %>% 
        return_performance_deep(global_date(), from_when)
      deep_data
    })
    
    
    VP_performance_preprocessing_filtered <- reactive({
      filtered_data <- VP_performance_preprocessing %>% filter(펀드설명 %in% selectedCategory())
      filtered_data
    })
    
    VP_performance_shallow <- reactive({
      from_when <- input$fromWhenInput
      shallow_data <- VP_performance_preprocessing_filtered() %>%
        return_performance_shallow(global_date(), from_when)
      shallow_data
    })
    
    VP_performance_deep <- reactive({
      from_when <- input$fromWhenInput
      deep_data<- VP_performance_shallow() %>% 
        return_performance_deep(global_date(), from_when)
      deep_data
    })
    
    MP_performance_preprocessing_filtered <- reactive({
      filtered_data <- MP_performance_preprocessing_final %>% filter(펀드설명 %in% selectedCategory())
      filtered_data
    })
    
    MP_performance_shallow <- reactive({
      from_when <- input$fromWhenInput
      shallow_data <- MP_performance_preprocessing_filtered() %>%
        return_performance_shallow(global_date(), from_when)
      shallow_data
    })
    
    MP_performance_deep <- reactive({
      from_when <- input$fromWhenInput
      deep_data<- MP_performance_shallow() %>% 
        return_performance_deep(global_date(), from_when)
      deep_data
    })
    BM_performance_preprocessing_filtered <- reactive({
      filtered_data <- BM_performance_preprocessing_final %>% filter(펀드설명 %in% selectedCategory())
      filtered_data
    })
    
    BM_performance_shallow <- reactive({
      from_when <- input$fromWhenInput
      shallow_data <- BM_performance_preprocessing_filtered() %>%
        return_performance_shallow(global_date(), from_when)
      shallow_data
    })
    
    BM_performance_deep <- reactive({
      from_when <- input$fromWhenInput
      deep_data<- BM_performance_shallow() %>% 
        return_performance_deep(global_date(), from_when)
      deep_data
    })
    
    
    output$modalContent <- renderUI({
      HTML(modalContent())
    })
    
    
    # 선택된 플롯들에 대한 UI 출력을 동적으로 생성
    output$plotsOutput <- renderUI({
      # 사용자가 선택한 플롯들의 목록
      plot_list <- input$selectedPlots
      
      # 선택된 플롯들을 표시하기 위한 UI 객체 리스트 생성
      plot_ui_list <- lapply(plot_list, function(plot_name) {
        plot_output_id <- str_glue("{plot_name}Plot")
        plotlyOutput(outputId = ns(plot_output_id))
      })
      
      # 생성된 UI 객체 리스트를 반환
      do.call(tagList, plot_ui_list)
    })
    
    # 성능 데이터 계산 로직
    results_except_TE <- reactive({
      # 'from_when' 값 설정
      from_when <- input$fromWhenInput
      
      
      results_except_TE <- bind_rows(
        AP_performance_deep() %>% mutate(구분 = "AP"),
        VP_performance_deep() %>% mutate(구분 = "VP"),
        MP_performance_deep() %>% mutate(구분 = "MP"),
        BM_performance_deep() %>% mutate(구분 = "BM")
      )# %>% 
      #   filter(complete.cases(.))
      
      results_except_TE
    })
    
    
    metric_except_TE <- reactive({
      results_except_TE() %>% 
        pivot_longer(cols = 3:7,names_to = "Metric") %>% 
        filter(Metric !="Return_annualized")
    })
    
    
    results_TE <- reactive({
      from_when <- input$fromWhenInput
      
      
      results_TE <-  
        results_except_TE() %>% 
        left_join(
          
          bind_rows(
            AP_performance_shallow() %>% mutate(구분="AP"),
            VP_performance_shallow() %>% mutate(구분="VP"),
            MP_performance_shallow() %>% mutate(구분="MP"),
            BM_performance_shallow() %>% mutate(구분="BM")
          ) %>% 
            select(펀드설명, 기준일자, 주별수익률,구분) %>% 
            filter(!is.na(주별수익률)) %>% 
            pivot_wider(
              names_from = 구분, 
              values_from = 주별수익률,
              values_fill = list(주별수익률 = NA) # 주별수익률 값이 없는 경우 NA로 채움
            ) %>%  
            mutate(`(AP-BM)` = AP-BM,
                   `(VP-BM)` = VP-BM) %>% 
            group_by(펀드설명) %>% 
            summarise(AP = sd(`(AP-BM)`,na.rm=TRUE)*sqrt(52),
                      VP = sd(`(VP-BM)`,na.rm=TRUE)*sqrt(52)) %>% 
            pivot_longer(cols = -펀드설명,names_to = "구분",values_to = "Tracking_error" ),
          
          by = join_by(펀드설명,구분)
        ) %>% filter(구분 %in%c("AP","VP","BM")) %>% 
        select(펀드설명,기준일자, Return_annualized,Tracking_error,구분) %>% 
        pivot_wider(id_cols = c(펀드설명,기준일자),names_from = 구분,values_from = c(Return_annualized,Tracking_error) ) %>% 
        mutate(IR_AP=  (Return_annualized_AP-Return_annualized_BM)/Tracking_error_AP,
               IR_VP=  (Return_annualized_VP-Return_annualized_BM)/Tracking_error_VP,
        ) %>% 
        select(펀드설명,기준일자,IR_AP,IR_VP,Tracking_error_AP,Tracking_error_VP) %>% 
        # pivot_longer를 사용한 데이터 변환
        pivot_longer(
          cols = starts_with("IR_") | starts_with("Tracking_error_"),
          names_to = c("Metric", "구분"),
          names_pattern = "(.+)_(.+)", # 첫 번째 그룹과 두 번째 그룹으로 나눔
          values_to = "value"
        ) 
      
      results_TE
    })
    
    Return_performance <- reactive({
      # 'from_when' 값 설정
      # from_when <- input$fromWhenInput
      Return_results <- results_except_TE() %>%
        select(펀드설명, 기준일자, Return, 구분) %>%
        filter(!is.na(Return)) %>%
        pivot_wider(
          names_from = 구분, 
          values_from = Return,
          values_fill = list(Return = NA)
        ) %>%
        mutate(`(AP-VP)` = AP - VP,
               `(VP-MP)` = VP - MP,
               `(MP-BM)` = MP - BM,
               `(AP-BM)` = AP - BM) %>%
        pivot_longer(
          cols = -c(펀드설명, 기준일자),
          names_to = "구분", 
          values_to = "Return"
        ) %>% 
        mutate(구분 = factor(구분, levels = c("AP", "VP", "MP", "BM", "(AP-VP)", "(VP-MP)", "(MP-BM)","(AP-BM)"))) %>% 
        mutate(label_text = ifelse(!is.na(Return), sprintf("%.2f%%", Return * 100), ""))
      
      
      
      Return_results
    })
    
    # 수익률 summarized ----
    output$performancePlot <- renderPlotly({
      req(Return_performance())  # 데이터 존재 확인
      
      # 제목 생성
      plot_title <- str_glue("{as.character(input$fromWhenInput)} 수익률")
      
      # 막대의 너비
      bar_width <- 0.75
      
      # 막대의 위치를 조정하기 위한 position_dodge 객체
      dodge <- position_dodge(width = bar_width)
      
      #Return_performance() %>% filter(구분 %in% c("AP", "VP", "MP", "BM")) 
      
      p <- ggplot(Return_performance(), aes(x = 펀드설명, y = Return, fill = 구분)) +
        geom_bar(stat = "identity", width = bar_width, position = dodge) +
        geom_text(aes(label = label_text, y = Return), 
                  position = dodge, vjust = -0.3, size = 3) +
        scale_y_continuous(labels = scales::percent) +
        theme_minimal() +
        labs(title = plot_title, x = "펀드 설명", y = "수익률 (%)")
      ggplotly(p)
    })
    
    
    
    # 수익률 historical plot ----
    output$performance_historicalPlot <- renderPlotly({
      
      
      from_when <- input$fromWhenInput
      
      Return_historical<- bind_rows(
        
        crossing(AP_fund_name %>% 
                   mutate(기준일자=설정일-days(1)) %>% 
                   select(-펀드) ,
                 수정기준가 =1000,구분 = c("AP","VP","MP","BM")),
        bind_rows(
          # 22-10-04 에 1000원 삽입하여 1000원부터 같이 시작할 수 있게 그림 
          AP_performance_preprocessing_filtered() %>% mutate(구분 = "AP") %>% 
            filter(!is.na(펀드설명)) %>%
            select(기준일자,설정일,펀드설명,수정기준가,구분)  ,
          VP_performance_preprocessing_filtered() %>% mutate(구분 = "VP") %>% select(기준일자,설정일,펀드설명,수정기준가,구분)  ,
          MP_performance_preprocessing_filtered()  %>% mutate(구분 = "MP") %>% select(기준일자,설정일,펀드설명,수정기준가,구분) ,
          BM_performance_preprocessing_filtered()  %>% mutate(구분 = "BM") %>% select(기준일자,설정일,펀드설명,수정기준가,구분)
        )  
        
      ) %>% 
        group_by(펀드설명,구분) %>% 
        dplyr::mutate(filtered_first_date = 
                        case_when(
                          from_when == "YTD" ~
                            make_date(year(global_date())),
                          from_when == "ITD" ~
                            설정일,
                          from_when == "최근 1년" ~
                            global_date() - years(1)  ,
                          from_when == "최근 1주" ~
                            global_date() - weeks(1) ,
                          from_when == "최근 1개월" ~
                            global_date() - months(1) ,
                          from_when == "최근 3개월" ~
                            global_date() - months(3) ,
                          from_when == "최근 6개월" ~
                            global_date() - months(6) )
        ) %>% 
        group_by(펀드설명)%>%
        dplyr::filter(설정일<=filtered_first_date & 기준일자<=global_date() & 기준일자>=filtered_first_date  )%>%
        group_by(펀드설명,구분) %>% 
        mutate(누적수익률 = 수정기준가/first(수정기준가) -1) %>% 
        ungroup() %>% 
        mutate(label_text =str_glue("구분       :{구분}
                                     기준일자   :{기준일자}
                                     누적수익률 :{sprintf('%.2f%%', 누적수익률 * 100)}"))
      
      
      p <- ggplot(Return_historical, aes(x = 기준일자, y = 누적수익률, color = 구분  )) +#text=label_text
        geom_line() +
        facet_wrap(~펀드설명) +
        scale_y_continuous(labels = percent_format(accuracy = 1)) +
        #scale_x_date(date_breaks = "3 month", date_labels = "%Y-%m") + # 여기를 수정하여 x축 날짜 형식 지정
        labs(y = "누적 수익률 (%)", x = "기준 일자") +
        theme_minimal()#+
      #theme(axis.text.x = element_text(angle = 45, hjust = 1)) # x축 라벨을 45도로 기울임
      
      
      ggplotly(p)
    })
    
    # 변동성 plot ----
    output$volatilityPlot <- renderPlotly({
      
      
      
      p  <- map(.x ="Risk_annualized", .f = ~ plot_metric_except_TE(metric_except_TE(), .x)) %>% pluck(1)+
        labs(title = str_glue("{as.character(input$fromWhenInput)} 변동성"))
      
      # 플롯 출력 (예시)
      
      ggplotly(p)
    })
    # Return-to-Risk plot ----
    output$riskAdjustedPlot <- renderPlotly({
      
      
      
      p  <- map(.x ="Return_to_Risk", .f = ~ plot_metric_except_TE(metric_except_TE(), .x)) %>% pluck(1)+
        labs(title = str_glue("{as.character(input$fromWhenInput)} Return-to-Risk"))
      
      # 플롯 출력 (예시)
      
      ggplotly(p)
    })
    # Sharpe Ratio plot ----
    output$sharpeRatioPlot <- renderPlotly({
      
      
      
      p  <- map(.x ="Sharpe_ratio", .f = ~ plot_metric_except_TE(metric_except_TE(), .x)) %>% pluck(1)+
        labs(title = str_glue("{as.character(input$fromWhenInput)} Sharpe Ratio"))
      
      # 플롯 출력 (예시)
      
      ggplotly(p)
    })
    
    
    # Information Ratio plot ----
    output$informationRatioPlot <- renderPlotly({
      
      
      
      p  <- map(.x ="IR", .f = ~ plot_metric_TE(results_TE(), .x)) %>% pluck(1)+
        labs(title = str_glue("{as.character(input$fromWhenInput)} Information Ratio"))
      
      # 플롯 출력 (예시)
      
      ggplotly(p)
    })
    # Tracking Error plot ----
    output$trackingErrorPlot <- renderPlotly({
      
      
      
      p  <- map(.x ="Tracking_error", .f = ~ plot_metric_TE(results_TE(), .x)) %>% pluck(1)+
        labs(title = str_glue("{as.character(input$fromWhenInput)} Tracking error"))
      
      # 플롯 출력 (예시)
      
      ggplotly(p)
    })
    
    # Excel 파일 다운로드 핸들러
    output$downloadExcel <- downloadHandler(
      filename = function() {
        paste("Performance&Risk-", global_date(), ".xlsx", sep="")
      },
      content = function(file) {
        
        #writexl::write_xlsx(metric_except_TE(), file)
        writexl::write_xlsx(
          bind_rows(metric_except_TE(),results_TE()) %>%
            arrange(펀드설명,구분) %>% 
            mutate(기간 = input$fromWhenInput), file)
      }
    )
    
  })
}
