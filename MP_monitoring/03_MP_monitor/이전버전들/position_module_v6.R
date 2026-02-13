
# Shiny UI 정의
positionUI <- function(id) {
  ns <- NS(id)
  sidebarLayout(
    sidebarPanel(
      # dateInput(ns("dateInput"), "기준일자 선택:", value = "2024-01-09"),
      radioButtons(ns("assetGroupSelect"), "자산군:",
                   choices = c("소" = "자산군_소", "대" = "자산군_대"),
                   inline = TRUE),
      downloadButton(ns("downloadExcel_position"), "Download Excel"),
      width = 2  # sidebarPanel의 너비 조정 (12가 제일 넓은것)
    ),
    mainPanel(
      plotlyOutput(ns("replication_stock_AI")),
      uiOutput(ns("replication_bond")),  # plotlyOutput 대신 uiOutput 사용
      plotlyOutput(ns("plotAP")),
      plotlyOutput(ns("plotVP")),
      plotlyOutput(ns("plotMP")),
      plotlyOutput(ns("diffPlot")),
      plotlyOutput(ns("diffPlot_VPMP")),
      width = 8
      
      
    )
  )
}

positionServer <- function(id, global_date, selectedCategory) {
  moduleServer(id, function(input, output, session) {
    ns <- session$ns
    
    observe({
      req(global_date())
      print(global_date())
    })
    
    AP_asset_adjust_filtered <- reactive({
      fund_list <- AP_fund_name %>% filter(펀드설명 %in% selectedCategory()) %>% pull(펀드)
      filtered_data <- AP_asset_adjust %>% filter(펀드 %in% c(fund_list, "07J48", "07J49"))
      filtered_data
    })
    
    VP_asset_adjust_filtered <- reactive({
      fund_list <- VP_fund_name %>% filter(펀드설명 %in% selectedCategory()) %>% pull(펀드)
      filtered_data <- VP_asset_adjust %>% filter(펀드 %in% c(fund_list, "07J48", "07J49"))
      filtered_data
    })
    
    
    
    
    position_AP <- reactive({
      data <- AP_asset_adjust_filtered()
      calculate_portfolio_weights(
        data = data,
        asset_group = input$assetGroupSelect,
        division = "AP"
      )
    })
    
    position_VP <- reactive({
      data <- VP_asset_adjust_filtered()
      
      bind_rows(
        calculate_portfolio_weights_from_MP_to_VP(data = ideal_VP_position,asset_group = input$assetGroupSelect,division = "MP") %>% 
          filter(펀드설명 =="Golden Growth" & 펀드설명 %in% selectedCategory() ) %>% 
          rename(펀드=펀드설명) %>% 
          mutate(펀드 = "6MP07"),
        calculate_portfolio_weights(
          data = data,
          asset_group = input$assetGroupSelect,
          division = "VP"
        )%>% 
          filter(펀드 != "6MP07")
        
      )
      
      
    })
    
    
    output$plotAP <- renderPlotly({
      req(input$assetGroupSelect, global_date())
      asset_group_sym <- sym(input$assetGroupSelect)
      position_AP <- position_AP() %>%
        filter(기준일자 == global_date()) %>%
        left_join(AP_fund_name, by = "펀드")
      
      p <- ggplot(position_AP, aes_string(x = "펀드설명", y = "daily_weight", fill = as.character(asset_group_sym))) +
        geom_bar(stat = "identity", position = "stack", alpha = 0.8) +
        geom_text(aes(label = scales::percent(daily_weight, accuracy = 0.01)), 
                  position = position_stack(vjust = 0.5), 
                  color = "black", 
                  size = 3) +
        scale_y_continuous(labels = scales::percent_format(), limits = c(0, 1.05)) +
        theme_minimal() +
        labs(title = paste("선택된 날짜:", global_date(), "- 펀드별 자산군 비중(AP)"),
             x = "펀드",
             y = "비중")
      
      ggplotly(p)
    })
    
    output$plotVP <- renderPlotly({
      req(input$assetGroupSelect, global_date())
      asset_group_sym <- sym(input$assetGroupSelect)
      position_VP <- position_VP() %>%
        filter(기준일자 == global_date()) %>%
        left_join(VP_fund_name, by = "펀드")
      
      p <- ggplot(position_VP, aes_string(x = "펀드설명", y = "daily_weight", fill = as.character(asset_group_sym))) +
        geom_bar(stat = "identity", position = "stack", alpha = 0.8) +
        geom_text(aes(label = scales::percent(daily_weight, accuracy = 0.01)), 
                  position = position_stack(vjust = 0.5), 
                  color = "black", 
                  size = 3) +
        scale_y_continuous(labels = scales::percent_format(), limits = c(0, 1.05)) +
        theme_minimal() +
        labs(title = paste("선택된 날짜:", global_date(), "- 펀드별 자산군 비중(VP)"),
             x = "펀드",
             y = "비중")
      
      ggplotly(p)
    })
    
    AP_VP_MP_diff <- reactive({
      asset_group_sym <- sym(input$assetGroupSelect)
      
      
      if (!"자산군_소" %in% colnames(universe_criteria)) {
        stop("universe_criteria 데이터프레임에 자산군_소 열이 없습니다.")
      }
      
      crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-05",
                                                 end_date = max(AP_performance_preprocessing$기준일자),
                                                 by = "day"),
               펀드설명 = selectedCategory(),
               universe_criteria %>%
                 filter(자산군_대 != "유동성") %>%
                 filter(!(!!sym(asset_group_sym) %in% c("07J48", "07J49", NA))) %>%
                 select(자산군_대, 자산군_소) %>% distinct()
      ) %>%
        left_join(full_join(position_AP() %>%
                              left_join(AP_fund_name),
                            position_VP() %>%
                              left_join(VP_fund_name),
                            by = join_by(기준일자, 펀드설명, !!asset_group_sym),
                            suffix = c("_AP", "_VP")), by = join_by(기준일자, 펀드설명, !!sym(asset_group_sym))) %>%
        left_join(MP_LTCMA %>%
                    group_by(리밸런싱날짜, 펀드설명, !!sym(asset_group_sym)) %>%
                    reframe(daily_weight_MP = sum(weight)), by = join_by(기준일자 >= 리밸런싱날짜, 펀드설명, !!sym(asset_group_sym))) %>%
        filter(!is.na(리밸런싱날짜)) %>% 
        group_by(기준일자, 펀드설명) %>%
        filter(리밸런싱날짜 == max(리밸런싱날짜, na.rm = TRUE)) %>%
        mutate(across(starts_with("daily_weight"), ~replace_na(., 0))) %>%
        mutate(`비중(AP-VP)` = daily_weight_AP - daily_weight_VP) %>%
        mutate(`비중(VP-MP)` = daily_weight_VP - daily_weight_MP) %>%
        ungroup()
    })
    
    position_MP <- reactive({
      req(input$assetGroupSelect, global_date())
      asset_group_sym <- sym(input$assetGroupSelect)
      position_MP <- MP_LTCMA %>% inner_join(
        AP_VP_MP_diff() %>%
          filter(기준일자 == global_date()) %>%
          group_by(펀드설명) %>%
          reframe(리밸런싱날짜 = 리밸런싱날짜[1])
      ) %>%
        group_by(펀드설명, !!sym(asset_group_sym)) %>%
        reframe(daily_weight = sum(weight)) %>%
        filter(daily_weight > 0)
    })
    
    output$plotMP <- renderPlotly({
      req(input$assetGroupSelect, global_date())
      asset_group_sym <- sym(input$assetGroupSelect)
      p <- ggplot(position_MP(), aes_string(x = "펀드설명", y = "daily_weight", fill = as.character(asset_group_sym))) +
        geom_bar(stat = "identity", position = "stack", alpha = 0.8) +
        geom_text(aes(label = scales::percent(daily_weight, accuracy = 0.01)), 
                  position = position_stack(vjust = 0.5), 
                  color = "black", 
                  size = 3) +
        scale_y_continuous(labels = scales::percent_format(), limits = c(0, 1.05)) +
        theme_minimal() +
        labs(title = paste("선택된 날짜:", global_date(), "- 펀드별 자산군 비중(MP)"),
             x = "펀드",
             y = "비중")
      
      ggplotly(p)
    })
    
    
    
    # AP - VP ----
    
    # AP와 VP의 비중 차이를 시각화하는 그래프 생성
    output$diffPlot <- renderPlotly({
      # 'input$assetGroupSelect' 값이 NULL인지 확인
      req(input$assetGroupSelect,global_date())  
      
      # position_AP와 position_VP를 펀드설명을 기준으로 full_join하고 차이 계산
      
      
      if(input$assetGroupSelect=="자산군_대"){
        AP_VP_diff<- AP_VP_MP_diff() %>% 
          filter(기준일자 == global_date()) %>%
          group_by(펀드설명, !!sym(input$assetGroupSelect) ) %>%
          reframe(`비중(AP-VP)` = first(`비중(AP-VP)`)) 
        
      }else{
        AP_VP_diff <- AP_VP_MP_diff() %>% 
          mutate(자산군_대 = if_else(is.na(자산군_대),"대체",자산군_대)) %>% 
          filter(기준일자 == global_date()) %>%
          group_by(펀드설명, !!sym(input$assetGroupSelect) ) %>%
          reframe(`비중(AP-VP)` = sum(`비중(AP-VP)`)) 
      }
      
      
      
      # ggplot 그래프 생성
      p <- ggplot(AP_VP_diff, aes(x = 펀드설명, y = `비중(AP-VP)`, fill = !!sym(input$assetGroupSelect))) +
        geom_bar(stat = "identity", width = 0.75, position = "dodge") +
        geom_hline(yintercept = 0.05, color = "red", linetype = "dashed") +
        geom_hline(yintercept = -0.05, color = "red", linetype = "dashed") +
        scale_y_continuous(labels = scales::percent) + # y축 레이블을 백분율로 변경
        theme_minimal() +
        labs(title = "AP vs. VP Active Weight Difference", x = "Fund Description", y = "Weight Difference")
      
      ggplotly(p)#%>% layout(legend = list(orientation = "h", y = -0.3))
      
    })
    
    # VP - MP ----
    
    output$diffPlot_VPMP <- renderPlotly({
      # 'input$assetGroupSelect' 값이 NULL인지 확인
      req(input$assetGroupSelect,global_date())  
      
      # position_AP와 position_VP를 펀드설명을 기준으로 full_join하고 차이 계산
      if(input$assetGroupSelect=="자산군_대"){
        VP_MP_diff<- AP_VP_MP_diff() %>% 
          filter(기준일자 == global_date()) %>%
          group_by(펀드설명, !!sym(input$assetGroupSelect) ) %>%
          reframe(`비중(VP-MP)` = first(`비중(VP-MP)`) ) 
        
        # ggplot 그래프 생성
        p <- ggplot(VP_MP_diff, aes(x = 펀드설명, y = `비중(VP-MP)`, fill = !!sym(input$assetGroupSelect))) +
          geom_bar(stat = "identity", width = 0.75, position = "dodge") +
          geom_hline(yintercept = 0.05, color = "red", linetype = "dashed") +
          geom_hline(yintercept = -0.05, color = "red", linetype = "dashed") +
          scale_y_continuous(labels = scales::percent) + # y축 레이블을 백분율로 변경
          theme_minimal() +
          labs(title = "VP vs. MP Active Weight Difference", x = "Fund Description", y = "Weight Difference")
        ggplotly(p)
        
      }else{
        # VP_MP_diff <- AP_VP_MP_diff %>% 
        #   left_join(universe_criteria %>% select(자산군_대, 자산군_소) %>% distinct()) %>% 
        #   mutate(자산군_대 = if_else(is.na(자산군_대),"대체",자산군_대)) %>% 
        #   filter(기준일자 == global_date()) %>%
        #   group_by(펀드설명, !!sym(input$assetGroupSelect) ) %>%
        #   summarise(`비중(VP-MP)` = sum(`비중(VP-MP)`)) 
        VP_MP_diff <- 
          AP_VP_MP_diff() %>% 
          left_join(universe_criteria %>% select(자산군_대, 자산군_소) %>% distinct()) %>%
          filter(자산군_대%in%c("주식","대체")) %>% 
          #mutate(자산군_대 = if_else(is.na(자산군_대),"대체",자산군_대)) %>% 
          #mutate(자산군_대 = if_else(자산군_대=="대체","주식",자산군_대)) %>% 
          group_by(기준일자,펀드설명) %>% 
          mutate(normalize_factor_VP = sum(daily_weight_VP), 
                 normalize_factor_MP = sum(daily_weight_MP),
          ) %>% ungroup() %>% 
          filter(기준일자 == global_date()) %>%
          group_by(펀드설명, !!sym(input$assetGroupSelect) ) %>%
          summarise(`비중(VP-MP)` = daily_weight_VP/normalize_factor_VP-daily_weight_MP/normalize_factor_MP) 
        
        
        # ggplot 그래프 생성
        p <- ggplot(VP_MP_diff, aes(x = 펀드설명, y = `비중(VP-MP)`, fill = !!sym(input$assetGroupSelect))) +
          geom_bar(stat = "identity", width = 0.75, position = "dodge") +
          geom_hline(yintercept = 0.05, color = "red", linetype = "dashed") +
          geom_hline(yintercept = -0.05, color = "red", linetype = "dashed") +
          scale_y_continuous(labels = scales::percent) + # y축 레이블을 백분율로 변경
          theme_minimal() +
          labs(title = "VP vs. MP Active Weight Difference(Normalized)", x = "Fund Description", y = "Weight Difference")
        ggplotly(p)
      }
      
      
      
      
    })
    
    
    
    output$replication_stock_AI <- renderPlotly({
      # 'input$assetGroupSelect' 값이 NULL인지 확인
      req(global_date())
      
      long_data <- replicate_disparate_rate %>%
        pivot_longer(cols = -c(기준일자, 펀드설명), names_to = "구분", values_to = "복제율&괴리율") %>% 
        mutate(구분= factor(구분,levels=c("괴리율(VP&MP, 주식+대체 대분류)","괴리율(AP&MP, 주식+대체 대분류)",
                                      "괴리율N.(VP&MP,주식+대체 소분류)","괴리율N.(AP&MP,주식+대체 소분류)",
                                      "복제율N.(AP&VP,주식+대체 소분류)","복제율(AP&VP,주식+대체 & 채권 대분류)"))) %>% 
        mutate(구분= fct_rev(구분))  %>% 
        mutate(복제율 = str_detect(구분,"복제율") ) %>%
        group_by(기준일자, 펀드설명) %>%
        ungroup() %>% 
        mutate(
          impact_color = case_when(
            ((!str_detect(구분,".N"))&(펀드설명=="TIF") &(복제율==FALSE) &(`복제율&괴리율` >= 0.03)) ~ "red",    # 괴리율이 0.05 이상일 때 빨간색
            ((펀드설명=="TIF") &(복제율==FALSE) &(`복제율&괴리율` >= 0.02))  ~ "#FFA500", # 괴리율이 0.03 이상일 때 주황색
            ((복제율==TRUE) &(`복제율&괴리율` <= 0.95)) ~ "red",    # 복제율이 0.95 이하일 때 빨간색
            ((복제율==TRUE) &(`복제율&괴리율` <= 0.97))  ~ "#FFA500", # 복제율이 0.97 이하일 때 주황색
            ((복제율==FALSE) &(`복제율&괴리율` >= 0.05)) ~ "red",    # 괴리율이 0.05 이상일 때 빨간색
            ((복제율==FALSE) &(`복제율&괴리율` >= 0.03))  ~ "#FFA500", # 괴리율이 0.03 이상일 때 주황색
            TRUE ~ "white"            # 그 외의 경우 흰색
          ),
          text_label = label_percent(accuracy = 0.01)(`복제율&괴리율`) # 소수점 둘째자리까지 표시
        )
      
      
      
      # 히트맵 생성
      p <- ggplot(long_data %>% filter(기준일자==global_date(),펀드설명 %in% selectedCategory() ), aes(x = 펀드설명, y = 구분)) +
        geom_tile(aes(fill = impact_color)) +  # 조건에 따른 색상 적용
        geom_text(aes(label = text_label), vjust = 1.5, color = "black") +
        scale_fill_identity() +  # 'identity'를 사용하여 데이터의 'impact_color' 값을 직접 색상으로 사용
        guides(fill = FALSE) +  # 범례 제거
        labs(title = paste("선택된 날짜:", global_date(), "- 복제율 & 괴리율"), x = "펀드설명", y = "") +
        theme_minimal() +
        theme(axis.title.y = element_text(margin = margin(l = 10, unit = "pt")))
      
      
      
      ggplotly(p)
    })
    
    
    
    output$replication_bond <- renderUI({
      req(global_date())
      
      if(global_date() < ymd("2024-06-10")) {
        tags$div(
          style = "color: red; font-weight: bold; text-align: center; padding: 20px;",
          "채권 듀레이션 복제율은 2024.06.10 부터 확인할 수 있습니다."
        )
      } else {
        plotlyOutput(ns("replication_bond_plot"))
      }
    })
    
    output$replication_bond_plot <- renderPlotly({
      long_data <- bond_duration_replicate %>%
        select(-contains("duration")) %>% 
        pivot_longer(cols = -c(기준일자, 펀드설명), names_to = "구분", values_to = "복제율") %>% 
        mutate(구분 = factor(구분, levels = c("펀드듀레이션(AP/VP)", "펀드듀레이션(AP/MP)",
                                          "채권듀레이션(AP/VP)", "채권듀레이션(AP/MP)"))) %>%  
        mutate(구분 = fct_rev(구분))  %>% 
        group_by(기준일자, 펀드설명) %>%
        ungroup() %>% 
        mutate(
          impact_color = case_when(
            (abs(복제율 - 1) >= 0.20) ~ "red",    # 복제율이 0.95 이하일 때 빨간색
            (abs(복제율 - 1) >= 0.10) ~ "#FFA500", # 복제율이 0.97 이하일 때 주황색
            TRUE ~ "white"            # 그 외의 경우 흰색
          ),
          text_label = label_percent(accuracy = 0.01)(복제율) # 소수점 둘째자리까지 표시
        )
      
      # 히트맵 생성
      p <- ggplot(long_data %>% filter(기준일자 == global_date(), 펀드설명 %in% selectedCategory()), aes(x = 펀드설명, y = 구분)) +
        geom_tile(aes(fill = impact_color)) +  # 조건에 따른 색상 적용
        geom_text(aes(label = text_label), vjust = 1.5, color = "black") +
        scale_fill_identity() +  # 'identity'를 사용하여 데이터의 'impact_color' 값을 직접 색상으로 사용
        guides(fill = FALSE) +  # 범례 제거
        labs(title = paste("선택된 날짜:", global_date(), "- 듀레이션 복제율"), x = "펀드설명", y = "") +
        theme_minimal() +
        theme(axis.title.y = element_text(margin = margin(l = 10, unit = "pt")))
      
      ggplotly(p)
    })
    
    
    output$downloadExcel_position <- downloadHandler(
      filename = function() {
        paste("Position-",input$assetGroupSelect,"-",global_date(), ".xlsx", sep="")
      },
      content = function(file) {
        #writexl::write_xlsx(position_AP() , file)
        #writexl::write_xlsx(position_VP() , file)
        if(input$assetGroupSelect=="자산군_대"){
          return_xlsx <-  AP_VP_MP_diff() %>% 
            group_by(기준일자,펀드설명,자산군_대) %>% 
            summarise(`최근 MP리밸런싱날짜` =리밸런싱날짜[1],
                      daily_weight_AP = daily_weight_AP[1],
                      daily_weight_VP = daily_weight_VP[1],
                      daily_weight_MP = daily_weight_MP[1],
                      `비중(AP-VP)` = `비중(AP-VP)`[1],
                      `비중(VP-MP)` = `비중(VP-MP)`[1]
            ) %>% ungroup() %>% 
            filter(!(abs(daily_weight_AP)==0 & abs(daily_weight_VP)==0 & abs(daily_weight_MP)==0) )
          writexl::write_xlsx(list( "daily_weight" =return_xlsx,
                                    "듀레이션" = bond_duration_replicate) , file)
        }else{
          return_xlsx <-  AP_VP_MP_diff() %>% 
            select(-펀드_AP,-펀드_VP) %>% 
            select(기준일자,펀드설명,자산군_대,자산군_소,
                   `최근 MP리밸런싱날짜` =리밸런싱날짜,daily_weight_AP,daily_weight_VP,daily_weight_MP,
                   `비중(AP-VP)`,`비중(VP-MP)`) %>% 
            filter(!(abs(daily_weight_AP)==0 & abs(daily_weight_VP)==0 & abs(daily_weight_MP)==0) )
          
          writexl::write_xlsx(list( "daily_weight" = return_xlsx,
                                    "듀레이션" = bond_duration_replicate) , file)
        }
        
        #writexl::write_xlsx(replication_rate() , file)
      }
    )
    
  })
}

