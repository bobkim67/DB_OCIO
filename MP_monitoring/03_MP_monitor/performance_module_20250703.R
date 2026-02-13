
performanceUI <- function(id) {
  ns <- NS(id)
  tagList(
    sidebarLayout(
      sidebarPanel(
        selectInput(ns("fromWhenInput"), "기간 선택:", 
                    choices = c("YTD", "ITD", "최근 1년",
                                "최근 1개월", "최근 3개월", "최근 6개월", "Base date"), 
                    selected = "YTD"),
        conditionalPanel(
          width = 2,
          condition = sprintf("input['%s'] == 'Base date'", ns("fromWhenInput")),
          dateInput(ns("baseDateInput"), "Base Date 선택:", value = max(AP_performance_preprocessing %>% 
                                                                        filter(!(wday(기준일자,label=FALSE) %in%c(1,7)) & 
                                                                                 !(기준일자 %in% KOREA_holidays) ) %>% 
                                                                        pull(기준일자)),daysofweekdisabled = c(0,6),
                    min = min(AP_performance_preprocessing %>% 
                                filter(!(wday(기준일자,label=TRUE) %in%c("Sat","Sun")) & 
                                         !(기준일자 %in% KOREA_holidays)) %>% 
                                pull(기준일자)),
                    max = max(AP_performance_preprocessing %>% 
                                filter(!(wday(기준일자,label=TRUE) %in%c("Sat","Sun")) & 
                                         !(기준일자 %in% KOREA_holidays)) %>% 
                                pull(기준일자)),datesdisabled = excludedDates )
        ),
        checkboxGroupInput(ns("selectedPlots"), "보고 싶은 분석 선택:",
                           choices = list("수익률" = "performance",
                                          "누적 수익률 추이" = "performance_historical",
                                          "변동성" = "volatility",
                                          "Return-to-Risk" = "riskAdjusted",
                                          "추적오차" = "trackingError",
                                          "정보비율" = "informationRatio",
                                          "샤프비율" = "sharpeRatio"),
                           selected = "performance"),
        downloadButton(ns("downloadExcel"), "Download Excel"),
        
        width = 2,
        style = "position: fixed; top: 320px; width: 250px;  overflow: auto;"  # 너비 설정 추가
        
      ),
      mainPanel(
        # div(class = "scrollable-graph-horizontal",
          uiOutput(ns("plotsOutput"))
        # )
        ,
        width = 10,
        style = "margin-left: 300px;"
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
      base_date <- if (from_when == "Base date") input$baseDateInput else NULL
      shallow_data <- AP_performance_preprocessing_filtered() %>%
        return_performance_shallow(global_date(), from_when, base_date)
      shallow_data
    })
    
    AP_performance_deep <- reactive({
      from_when <- input$fromWhenInput
      deep_data <- AP_performance_shallow() %>% 
        return_performance_deep(global_date(), from_when)
      deep_data
    })
    
    VP_performance_preprocessing_filtered <- reactive({
      filtered_data <- VP_performance_preprocessing %>% filter(펀드설명 %in% selectedCategory())
      filtered_data
    })
    
    VP_performance_shallow <- reactive({
      from_when <- input$fromWhenInput
      base_date <- if (from_when == "Base date") input$baseDateInput else NULL
      shallow_data <- VP_performance_preprocessing_filtered() %>%
        return_performance_shallow(global_date(), from_when, base_date)
      shallow_data
    })
    
    VP_performance_deep <- reactive({
      from_when <- input$fromWhenInput
      deep_data <- VP_performance_shallow() %>% 
        return_performance_deep(global_date(), from_when)
      deep_data
    })
    
    MP_performance_preprocessing_filtered <- reactive({
      filtered_data <- MP_performance_preprocessing_final %>% filter(펀드설명 %in% selectedCategory())
      filtered_data
    })
    
    MP_performance_shallow <- reactive({
      from_when <- input$fromWhenInput
      base_date <- if (from_when == "Base date") input$baseDateInput else NULL
      shallow_data <- MP_performance_preprocessing_filtered() %>%
        return_performance_shallow(global_date(), from_when, base_date)
      shallow_data
    })
    
    MP_performance_deep <- reactive({
      from_when <- input$fromWhenInput
      deep_data <- MP_performance_shallow() %>% 
        return_performance_deep(global_date(), from_when)
      deep_data
    })
    
    BM_performance_preprocessing_filtered <- reactive({
      filtered_data <- BM_performance_preprocessing_final %>% filter(펀드설명 %in% selectedCategory())
      filtered_data
    })
    
    BM_performance_shallow <- reactive({
      from_when <- input$fromWhenInput
      base_date <- if (from_when == "Base date") input$baseDateInput else NULL
      shallow_data <- BM_performance_preprocessing_filtered() %>%
        return_performance_shallow(global_date(), from_when, base_date)
      shallow_data
    })
    
    BM_performance_deep <- reactive({
      from_when <- input$fromWhenInput
      deep_data <- BM_performance_shallow() %>% 
        return_performance_deep(global_date(), from_when)
      deep_data
    })
    
    output$modalContent <- renderUI({
      HTML(modalContent())
    })
    
    output$plotsOutput <- renderUI({
      plot_list <- input$selectedPlots
      plot_ui_list <- lapply(plot_list, function(plot_name) {
        plot_output_id <- str_glue("{plot_name}Plot")
        div(class = "scrollable-graph-horizontal", plotlyOutput(outputId = ns(plot_output_id)))
      })
      do.call(tagList, plot_ui_list)
    })
    
    results_except_TE <- reactive({
      from_when <- input$fromWhenInput
      results_except_TE <- bind_rows(
        AP_performance_deep() %>% mutate(구분 = "AP"),
        VP_performance_deep() %>% mutate(구분 = "VP"),
        MP_performance_deep() %>% mutate(구분 = "MP"),
        BM_performance_deep() %>% mutate(구분 = "BM")
      ) %>% arrange(펀드설명)
      results_except_TE
    })
    
    metric_except_TE <- reactive({
      results_except_TE() %>% 
        pivot_longer(cols = 3:7, names_to = "Metric") %>% 
        filter(Metric != "Return_annualized")
    })
    
    results_TE <- reactive({
      from_when <- input$fromWhenInput
      results_TE <- results_except_TE() %>% 
        left_join(
          bind_rows(
            AP_performance_shallow() %>% mutate(구분="AP"),
            VP_performance_shallow() %>% mutate(구분="VP"),
            MP_performance_shallow() %>% mutate(구분="MP"),
            BM_performance_shallow() %>% mutate(구분="BM")
          ) %>% 
            select(펀드설명, 기준일자, 주별수익률, 구분) %>% 
            filter(!is.na(주별수익률)) %>% 
            pivot_wider(
              names_from = 구분, 
              values_from = 주별수익률,
              values_fill = list(주별수익률 = NA)
            ) %>%  
            mutate(`(AP-BM)` = AP - BM,
                   `(VP-BM)` = VP - BM) %>% 
            group_by(펀드설명) %>% 
            summarise(AP = sd(`(AP-BM)`, na.rm = TRUE) * sqrt(52),
                      VP = sd(`(VP-BM)`, na.rm = TRUE) * sqrt(52)) %>% 
            pivot_longer(cols = -펀드설명, names_to = "구분", values_to = "Tracking_error"),
          by = join_by(펀드설명, 구분)
        ) %>% filter(구분 %in% c("AP", "VP", "BM")) %>% 
        select(펀드설명, 기준일자, Return_annualized, Tracking_error, 구분) %>% 
        pivot_wider(id_cols = c(펀드설명, 기준일자), names_from = 구분, values_from = c(Return_annualized, Tracking_error)) %>% 
        mutate(IR_AP = (Return_annualized_AP - Return_annualized_BM) / Tracking_error_AP,
               IR_VP = (Return_annualized_VP - Return_annualized_BM) / Tracking_error_VP) %>% 
        select(펀드설명, 기준일자, IR_AP, IR_VP, Tracking_error_AP, Tracking_error_VP) %>% 
        pivot_longer(
          cols = starts_with("IR_") | starts_with("Tracking_error_"),
          names_to = c("Metric", "구분"),
          names_pattern = "(.+)_(.+)",
          values_to = "value"
        )
      results_TE
    })
    
    Return_performance <- reactive({
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
        mutate(구분 = factor(구분, levels = c("AP", "VP", "MP", "BM", "(AP-VP)", "(VP-MP)", "(MP-BM)", "(AP-BM)"))) %>% 
        mutate(label_text = ifelse(!is.na(Return), sprintf("%.2f%%", Return * 100), ""))
      Return_results
    })
    
    output$performancePlot <- renderPlotly({
      req(Return_performance())
      if (is_update_failed){
        stop("Some data may have not been updated. Check the status of the data update and manually update any missing parts.")
      } else {
      plot_title <- str_glue("{as.character(input$fromWhenInput)} 수익률")
      bar_width <- 0.75
      dodge <- position_dodge(width = bar_width)
      plot_width <- calculate_plot_width(Return_performance())
      p <- ggplot(Return_performance(), aes(x = 펀드설명, y = Return, fill = 구분)) +
        geom_bar(stat = "identity", width = bar_width, position = dodge) +
        geom_text(aes(label = label_text, y = Return), 
                  position = dodge, vjust = -0.3, size = 3, angle = 90) +
        scale_y_continuous(labels = scales::percent) +
        theme_minimal() +
        labs(title = plot_title, x = "펀드 설명", y = "수익률 (%)")
      
      ggplotly(p, width = plot_width)
      }
    })
    
    Return_historical <- reactive({
      from_when <- input$fromWhenInput
      base_date <- if (from_when == "Base date") input$baseDateInput else NULL
      # base_date가 NULL일 경우 처리
      
      
      
      start_of_month <- floor_date(global_date(), "month")
      end_of_month <- ceiling_date(global_date(), "month") - days(1)
      # 해당 월의 모든 날짜
      all_dates <- seq(start_of_month, end_of_month, by = "day")
      
      # 평일만 추출
      weekdays_only <- all_dates[!(wday(all_dates) %in% c(1,7))]
      # 휴장일 제외
      tradingdays_only <- weekdays_only[! (weekdays_only %in% KOREA_holidays)]
      
      
      last_day_of_month<- global_date() ==max(tradingdays_only)
      print(paste("return_performance_shallow: input_date =", global_date(), "from_when =", from_when))
      
      
      if (is.null(base_date)) {
        base_date <- NA_Date_
      } else {
        base_date <- ymd(base_date)
      }
      Return_historical <- bind_rows(
        crossing(AP_fund_name %>% 
                   filter(펀드설명 %in% selectedCategory()) %>% 
                   mutate(기준일자 = 설정일 - days(1)) %>% 
                   select(-펀드), 
                 수정기준가 = 1000, 구분 = c("AP", "VP", "MP", "BM")),
        bind_rows(
          AP_performance_preprocessing_filtered() %>% mutate(구분 = "AP") %>% 
            filter(!is.na(펀드설명)) %>%
            select(기준일자, 설정일, 펀드설명, 수정기준가, 구분),
          VP_performance_preprocessing_filtered() %>% mutate(구분 = "VP") %>% select(기준일자, 설정일, 펀드설명, 수정기준가, 구분),
          MP_performance_preprocessing_filtered() %>% mutate(구분 = "MP") %>% select(기준일자, 설정일, 펀드설명, 수정기준가, 구분),
          BM_performance_preprocessing_filtered() %>% mutate(구분 = "BM") %>% select(기준일자, 설정일, 펀드설명, 수정기준가, 구분)
        )
      ) %>% 
        group_by(펀드설명, 구분) %>% 
        dplyr::mutate(filtered_first_date = 
                        case_when(
                          from_when == "YTD" ~ make_date(year(global_date()))-days(1),
                          from_when == "ITD" ~ 설정일-days(1),
                          from_when == "최근 1년" ~ add_with_rollback(global_date(), -months(12)),
                          #from_when == "최근 1주" ~ global_date() - weeks(1),
                          from_when == "최근 1개월" ~ add_with_rollback(global_date(), -months(1)),
                          from_when == "최근 3개월" ~ add_with_rollback(global_date(), -months(3)),
                          from_when == "최근 6개월" ~ add_with_rollback(global_date(), -months(6)),
                          from_when == "Base date" ~ ymd(base_date)-days(1)
                        )
        ) %>% 
        group_by(펀드설명) %>%
        mutate(filtered_first_date = if_else((last_day_of_month ==TRUE & !(from_when %in% c("Base date","ITD")) ), 
                                             (ceiling_date(filtered_first_date[1], unit = "month") - days(1)),
                                             filtered_first_date[1] ) ) %>% 
        group_by(펀드설명, 구분) %>% 
        dplyr::filter( (if_else(from_when =="ITD",TRUE,FALSE) | 설정일-days(1)<=filtered_first_date) & 기준일자<=global_date() & 기준일자>=filtered_first_date  )%>%
        mutate(설정직전날= if_else(sum(설정일>기준일자)!=0,TRUE,FALSE )) %>% 
        mutate(설정직전날가격=  if_else(설정직전날,last(수정기준가[기준일자<설정일]),1000 ) ) %>% 
        mutate(수정기준가_first =if_else((from_when =="ITD" & 설정직전날==TRUE),설정직전날가격,
                                    if_else((from_when =="ITD" & 설정직전날==FALSE),1000,수정기준가[1]))) %>% 
        mutate(누적수익률 = 수정기준가 / 수정기준가_first - 1) %>% 
        ungroup() 
      
      
      
      
      Return_historical
    })
    
    
    output$performance_historicalPlot <- renderPlotly({
      if (is_update_failed){
        stop("Some data may have not been updated. Check the status of the data update and manually update any missing parts.")
      } else {
      p <- ggplot(Return_historical(), aes(x = 기준일자, y = 누적수익률, color = 구분)) +
        geom_line() +
        facet_wrap(~펀드설명) +
        scale_y_continuous(labels = percent_format(accuracy = 1)) +
        labs(y = "누적 수익률 (%)", x = "기준 일자") +
        theme_minimal()
      ggplotly(p)
      }
    })
    
    output$volatilityPlot <- renderPlotly({
      
      plot_width <- calculate_plot_width(Return_performance())
      
      p <- map(.x = "Risk_annualized", .f = ~ plot_metric_except_TE(metric_except_TE(), .x)) %>% pluck(1) +
        labs(title = str_glue("{as.character(input$fromWhenInput)} 변동성"))
      ggplotly(p, width = plot_width)
    })
    
    output$riskAdjustedPlot <- renderPlotly({
      
      plot_width <- calculate_plot_width(Return_performance())
      
      p <- map(.x = "Return_to_Risk", .f = ~ plot_metric_except_TE(metric_except_TE(), .x)) %>% pluck(1) +
        labs(title = str_glue("{as.character(input$fromWhenInput)} Return-to-Risk"))
      ggplotly(p, width = plot_width)
    })
    
    output$sharpeRatioPlot <- renderPlotly({
      
      plot_width <- calculate_plot_width(Return_performance())
      
      p <- map(.x = "Sharpe_ratio", .f = ~ plot_metric_except_TE(metric_except_TE(), .x)) %>% pluck(1) +
        labs(title = str_glue("{as.character(input$fromWhenInput)} Sharpe Ratio"))
      ggplotly(p, width = plot_width)
    })
    
    output$informationRatioPlot <- renderPlotly({
      
      plot_width <- calculate_plot_width(Return_performance())
      
      p <- map(.x = "IR", .f = ~ plot_metric_TE(results_TE(), .x)) %>% pluck(1) +
        labs(title = str_glue("{as.character(input$fromWhenInput)} Information Ratio"))
      ggplotly(p, width = plot_width)
    })
    
    output$trackingErrorPlot <- renderPlotly({
      
      plot_width <- calculate_plot_width(Return_performance())
      
      p <- map(.x = "Tracking_error", .f = ~ plot_metric_TE(results_TE(), .x)) %>% pluck(1) +
        labs(title = str_glue("{as.character(input$fromWhenInput)} Tracking error"))
      ggplotly(p, width = plot_width)
    })
    
    output$downloadExcel <- downloadHandler(
      filename = function() {
        str_glue("Performance&Risk-{global_date()}-{input$fromWhenInput}.xlsx", sep="")
      },
      content = function(file) {
        writexl::write_xlsx(
          list(
            "Performance&Risk" =bind_rows(metric_except_TE(), results_TE()) %>%
              arrange(펀드설명, 구분) %>% 
              mutate(기간 = input$fromWhenInput) ,
            "historical_price" = Return_historical()
          ),file)
        #mutate(기간 = if_else(is.null(input$baseDateInput), input$fromWhenInput, str_glue("Base date : {input$baseDateInput}") )), file)
      }
    )
    
  })
}
