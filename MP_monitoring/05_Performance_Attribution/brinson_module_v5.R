# 필요한 라이브러리 로드
library(shiny)
library(dplyr)
library(lubridate)
library(writexl)
library(kableExtra)
library(scales)
library(shinyjs)
library(echarts4r)
library(glue)

# Custom CSS for height adjustment and spacing
customCSS <- "
  .sidebar {
    height: 100vh;
    overflow-y: auto;
  }
  .main-panel {
    height: 100vh;
    overflow-y: auto;
  }
  .plot-container {
    height: 85vh;
  }
  .plot-output {
    height: 85% !important;
  }
  .summary-table {
    margin-bottom: 70px;
  }
"

PAUI <- function(id) {
  ns <- NS(id)
  tagList(
    useShinyjs(),
    tags$head(
      tags$style(HTML(customCSS))
    ),
    sidebarLayout(
      sidebarPanel(
        width = 2, # Adjust width
        class = "sidebar",
        
        h4("Portfolio A"),
        fluidRow(
          column(8, selectInput(ns("fund_desc_a"), "펀드", choices = Fund_Information$펀드설명)),
          column(4, selectInput(ns("name_a"), "구분", choices = c("AP", "VP", "MP", "BM")))
        ),
        fluidRow(
          column(12, htmlOutput(ns("fund_date_a")))
        ),
        
        hr(style = "border-top: 2px solid #000000;"),
        
        h4("Portfolio B"),
        fluidRow(
          column(8, selectInput(ns("fund_desc_b"), "펀드", choices = Fund_Information$펀드설명)),
          column(4, selectInput(ns("name_b"), "구분", choices = c("AP", "VP", "MP", "BM")))
        ),
        fluidRow(
          column(12, htmlOutput(ns("fund_date_b")))
        ),
        
        hr(style = "border-top: 2px solid #000000;"),
        
        h4("분석기간"),
        fluidRow(
          column(6, dateInput(ns("from_when"), "From", value = NULL)),
          column(6, dateInput(ns("to_when"), "To", value = NULL, daysofweekdisabled = c(0, 6)))
        ),
        
        hr(style = "border-top: 2px solid #000000;"),
        
        actionButton(ns("update"), "Update"),
        downloadButton(ns("downloadData"), "Download Results"),
        downloadButton(ns("downloadReport"), "Brinson logic") # PDF 다운로드 버튼 추가
      ),
      mainPanel(
        width = 10, # Adjust width
        class = "main-panel",
        fluidRow(
          column(4,
                 div(class = "summary-table",
                     h3("포트폴리오 수익률 비교"),
                     tableOutput(ns("summary1"))
                 ),
                 div(class = "summary-table",
                     h3("Holding base's Excess Return성과 분해"),
                     htmlOutput(ns("summary2")),
                     uiOutput(ns("explanation")) # 설명 추가
                 )
          ),
          column(8,
                 h3("Graph"),
                 div(class = "plot-container",
                     tabsetPanel(
                       tabPanel("포트폴리오 수익률 비교차트",
                                tabsetPanel(
                                  tabPanel("포트폴리오", echarts4rOutput(ns("actual_chart"), height = "650px")),
                                  tabPanel("기타 수익률", echarts4rOutput(ns("etc_chart"), height = "650px")),
                                  tabPanel("Holding base 수익률", echarts4rOutput(ns("holdingbase_chart"), height = "650px")),
                                  tabPanel("주식 기여수익률", echarts4rOutput(ns("stock_chart"), height = "650px")),
                                  tabPanel("대체 기여수익률", echarts4rOutput(ns("alternative_chart"), height = "650px")),
                                  tabPanel("채권 및 유동성 기여수익률", echarts4rOutput(ns("bond_liquidity_chart"), height = "650px"))
                                )
                       ),
                       tabPanel("Holding base Excess Return 성과 분해 차트",
                                tabsetPanel(
                                  tabPanel("요인별 성과", echarts4rOutput(ns("factor_chart"), height = "650px")),
                                  tabPanel("자산군별 성과", echarts4rOutput(ns("asset_class_chart"), height = "650px"))
                                )
                       )
                     )
                 )
          )
        )
      )
    )
  )
}

PA_Server <- function(id) {
  moduleServer(id, function(input, output, session) {
    get_fund_date <- reactive({
      
      req(input$fund_desc_a, input$fund_desc_b)
      
      # 2. ★가장 중요★ 내용물이 비어있는지(길이가 0인지) 확인
      # 이 부분이 없으면 "size 0" 에러가 발생합니다.
      if (length(input$fund_desc_a) == 0 || input$fund_desc_a == "") return(NULL)
      if (length(input$fund_desc_b) == 0 || input$fund_desc_b == "") return(NULL)
      
      # 3. 데이터프레임이 로드되었는지 확인 (방어 코드)
      if (!exists("AP_fund_name")) return(NULL)
      date_a <- AP_fund_name %>%
        filter(펀드설명 == input$fund_desc_a) %>%
        pull(설정일)
      date_b <- AP_fund_name %>%
        filter(펀드설명 == input$fund_desc_b) %>%
        pull(설정일)
      
      list(date_a = date_a, date_b = date_b)
    })
    
    observeEvent(input$fund_desc_a, {
      date_a <- get_fund_date()$date_a
      output$fund_date_a <- renderUI({
        if(!is.null(date_a)) {
          HTML(paste("<small>펀드 설정일: ", date_a, "</small>"))
        } else {
          HTML("")
        }
      })
    })
    
    observeEvent(input$fund_desc_b, {
      date_b <- get_fund_date()$date_b
      output$fund_date_b <- renderUI({
        if(!is.null(date_b)) {
          HTML(paste("<small>펀드 설정일: ", date_b, "</small>"))
        } else {
          HTML("")
        }
      })
    })
    
    observeEvent(list(input$fund_desc_a, input$fund_desc_b), {
      fund_dates <- get_fund_date()
      from_date <- max(fund_dates$date_a, fund_dates$date_b, na.rm = TRUE)
      max_date <- max(AP_performance_preprocessing %>%
                        filter(!(wday(기준일자, label = FALSE) %in% c(1, 7)) & 
                                 !(기준일자 %in% KOREA_holidays)) %>%
                        pull(기준일자))
      
      updateDateInput(session, "from_when", value = from_date, min = from_date, max = max_date)
      updateDateInput(session, "to_when", value = max_date, min = from_date, max = max_date)
    })
    
    result <- eventReactive(input$update, {
      processed_data <- brinson_preprocess(isolate(input$fund_desc_a), isolate(input$name_a), isolate(input$fund_desc_b), isolate(input$name_b))
      brinson_results(processed_data, isolate(input$from_when), isolate(input$to_when))
    })
    
    output$summary1 <- renderTable({
      req(input$update)
      summary <- brinson_summary(result())[[2]] %>% 
        mutate(`Excess Return` = `Port a` - `Port b`) %>% 
        mutate(across(where(is.numeric), percent_format(accuracy = 0.01)))
      
      colnames(summary) <- c(
        "구분",
        glue("{isolate(input$fund_desc_a)}({isolate(input$name_a)})"),
        glue("{isolate(input$fund_desc_b)}({isolate(input$name_b)})"),
        "Excess Return"
      )
      
      summary
    })
    
    output$summary2 <- renderUI({
      req(input$update)
      table2 <- brinson_summary(result())[[3]]
      
      processed_table <- table2 %>% 
        filter(row_number() >= 7) %>% 
        pivot_wider(names_from = 세부정보, values_from = `수익률(%)`) %>% 
        pivot_longer(cols = everything(), names_to = c("category", "type"), names_sep = "_") %>%
        pivot_wider(names_from = category, values_from = value) %>%
        mutate(type = factor(type, levels = c("주식", "대체", "채권및유동성"))) %>%
        arrange(type) %>% 
        column_to_rownames(var = "type")
      
      summarized_table <- addmargins(as.matrix(processed_table))
      
      # Convert to percentage format
      summarized_df <- as.data.frame(summarized_table) %>%
        mutate(across(everything(), percent_format(accuracy = 0.01)))
      
      highlighted_cell <- summarized_df[nrow(summarized_df), ncol(summarized_df)]
      summarized_df[nrow(summarized_df), ncol(summarized_df)] <- paste0(
        "<b><span style='background-color: yellow; color: red;'>", highlighted_cell, "</span></b>"
      )
      
      html_table <- summarized_df %>%
        rownames_to_column("type") %>%
        mutate(type = if_else(type =="Sum","합계(요인별)",type)) %>% 
        rename(` `= type,`상호작용효과`=A, `자산배분효과`=B, `종목선택효과`=C, `합계(자산군별)`=Sum ) %>% 
        kbl(escape = FALSE) %>%
        kable_styling(bootstrap_options = c("striped", "hover", "condensed", "responsive"), full_width = F, position = "center") %>%
        row_spec(nrow(summarized_df), bold = T, background = "#D3D3D3") %>%
        column_spec(ncol(summarized_df) + 1, bold = T, background = "#D3D3D3")
      
      HTML(as.character(html_table))
    })
    
    
    output$explanation <- renderUI({
      tags$div(
        style = "color: black; font-weight: bold; text-align: center; padding: 20px;",
        "유동성 Position에 대한 수익률은 해당되는 일자의 콜금리/365를 사용"
      )
    })
    # Helper function to create chart titles
    create_chart_title <- function(chart_title) {
      glue("{chart_title} : {isolate(input$fund_desc_a)}({isolate(input$name_a)}) vs {isolate(input$fund_desc_b)}({isolate(input$name_b)}) ( {isolate(input$from_when)} ~ {isolate(input$to_when)} )")
    }
    
    # Helper function to create series names
    create_series_name_a <- function(prefix) {
      glue("{isolate(input$fund_desc_a)}({isolate(input$name_a)}) {prefix}")
    }
    create_series_name_b <- function(prefix) {
      glue("{isolate(input$fund_desc_b)}({isolate(input$name_b)}) {prefix}")
    }
    create_series_name <-  function(prefix) {
      glue("{prefix}: {isolate(input$fund_desc_a)}({isolate(input$name_a)}) - {isolate(input$fund_desc_b)}({isolate(input$name_b)}) ")
    }
    
    output$actual_chart <- renderEcharts4r({
      req(input$update)
      time_series <- brinson_summary(result())[[1]]
      time_series %>%
        mutate(Actual_Port_diff_ab = Actual_Port_a_수익률 - Actual_Port_b_수익률) %>%
        e_charts(기준일자) %>%
        e_area(Actual_Port_diff_ab, name = ("Excess Return"), showSymbol = FALSE) %>%
        e_line(Actual_Port_a_수익률, name = create_series_name_a("포트폴리오"), showSymbol = FALSE) %>%
        e_line(Actual_Port_b_수익률, name = create_series_name_b("포트폴리오"), showSymbol = FALSE) %>%
        e_x_axis(min = min(time_series$기준일자) - days(1), max = max(time_series$기준일자) + days(1)) %>%
        e_y_axis(formatter = e_axis_formatter("percent", digits = 2)) %>%
        e_tooltip(
          trigger = "axis",
          axisPointer = list(type = "cross"),
          formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
        ) %>%
        e_title(create_chart_title("포트폴리오 비교")) %>%
        e_legend(top = "bottom") %>%
        e_toolbox_feature(feature = "saveAsImage")
    })
    
    
    output$etc_chart <- renderEcharts4r({
      req(input$update)
      time_series <- brinson_summary(result())[[1]]
      time_series %>%
        mutate(기타_Port_diff_ab = R_Port_a_기타 - R_Port_b_기타) %>%
        e_charts(기준일자) %>%
        e_area(기타_Port_diff_ab, name = ("Excess Return"), showSymbol = FALSE) %>%
        e_line(R_Port_a_기타, name = create_series_name_a("기타 수익률"), showSymbol = FALSE) %>%
        e_line(R_Port_b_기타, name = create_series_name_b("기타 수익률"), showSymbol = FALSE) %>%
        e_x_axis(min = min(time_series$기준일자) - days(1), max = max(time_series$기준일자) + days(1)) %>%
        e_y_axis(formatter = e_axis_formatter("percent", digits = 2)) %>%
        e_tooltip(
          trigger = "axis",
          axisPointer = list(type = "cross"),
          formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
        ) %>%
        e_title(create_chart_title("기타 수익률 비교")) %>%
        e_legend(top = "bottom") %>%
        e_toolbox_feature(feature = "saveAsImage")
    })
    
    
    output$holdingbase_chart <- renderEcharts4r({
      req(input$update)
      time_series <- brinson_summary(result())[[1]]
      time_series %>%
        mutate(Holding_base_Port_diff_ab = R_Port_a_Holding_base - R_Port_b_Holding_base) %>%
        e_charts(기준일자) %>%
        e_area(Holding_base_Port_diff_ab, name = ("Excess Return"), showSymbol = FALSE) %>%
        e_line(R_Port_a_Holding_base, name = create_series_name_a("Holding base 수익률"), showSymbol = FALSE) %>%
        e_line(R_Port_b_Holding_base, name = create_series_name_b("Holding base 수익률"), showSymbol = FALSE) %>%
        e_x_axis(min = min(time_series$기준일자) - days(1), max = max(time_series$기준일자) + days(1)) %>%
        e_y_axis(formatter = e_axis_formatter("percent", digits = 2)) %>%
        e_tooltip(
          trigger = "axis",
          axisPointer = list(type = "cross"),
          formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
        ) %>%
        e_title(create_chart_title("Holding base 수익률 비교")) %>%
        e_legend(top = "bottom") %>%
        e_toolbox_feature(feature = "saveAsImage")
    })
    
    output$stock_chart <- renderEcharts4r({
      req(input$update)
      time_series <- brinson_summary(result())[[1]]
      time_series %>%
        mutate(주식_Port_diff_ab = 주식_Port_a_수익률 - 주식_Port_b_수익률) %>%
        e_charts(기준일자) %>%
        e_area(주식_Port_diff_ab, name = ("Excess Return"), showSymbol = FALSE) %>%
        e_line(주식_Port_a_수익률, name = create_series_name_a("주식 수익률"), showSymbol = FALSE) %>%
        e_line(주식_Port_b_수익률, name = create_series_name_b("주식 수익률"), showSymbol = FALSE) %>%
        e_x_axis(min = min(time_series$기준일자) - days(1), max = max(time_series$기준일자) + days(1)) %>%
        e_y_axis(formatter = e_axis_formatter("percent", digits = 2)) %>%
        e_tooltip(
          trigger = "axis",
          axisPointer = list(type = "cross"),
          formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
        ) %>%
        e_title(create_chart_title("주식 기여 수익률 비교")) %>%
        e_legend(top = "bottom") %>%
        e_toolbox_feature(feature = "saveAsImage")
    })
    
    output$alternative_chart <- renderEcharts4r({
      req(input$update)
      time_series <- brinson_summary(result())[[1]]
      time_series %>%
        mutate(대체_Port_diff_ab = 대체_Port_a_수익률 - 대체_Port_b_수익률) %>%
        e_charts(기준일자) %>%
        e_area(대체_Port_diff_ab, name = ("Excess Return"), showSymbol = FALSE) %>%
        e_line(대체_Port_a_수익률, name = create_series_name_a("대체 수익률"), showSymbol = FALSE) %>%
        e_line(대체_Port_b_수익률, name = create_series_name_b("대체 수익률"), showSymbol = FALSE) %>%
        e_x_axis(min = min(time_series$기준일자) - days(1), max = max(time_series$기준일자) + days(1)) %>%
        e_y_axis(formatter = e_axis_formatter("percent", digits = 2)) %>%
        e_tooltip(
          trigger = "axis",
          axisPointer = list(type = "cross"),
          formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
        ) %>%
        e_title(create_chart_title("대체 기여 수익률 비교")) %>%
        e_legend(top = "bottom") %>%
        e_toolbox_feature(feature = "saveAsImage")
    })
    
    output$bond_liquidity_chart <- renderEcharts4r({
      req(input$update)
      time_series <- brinson_summary(result())[[1]]
      time_series %>%
        mutate(채권및유동성_Port_diff_ab = 채권및유동성_Port_a_수익률 - 채권및유동성_Port_b_수익률) %>%
        e_charts(기준일자) %>%
        e_area(채권및유동성_Port_diff_ab, name = ("Excess Return"), showSymbol = FALSE) %>%
        e_line(채권및유동성_Port_a_수익률, name = create_series_name_a("채권 및 유동성 수익률"), showSymbol = FALSE) %>%
        e_line(채권및유동성_Port_b_수익률, name = create_series_name_b("채권 및 유동성 수익률"), showSymbol = FALSE) %>%
        e_x_axis(min = min(time_series$기준일자) - days(1), max = max(time_series$기준일자) + days(1)) %>%
        e_y_axis(formatter = e_axis_formatter("percent", digits = 2)) %>%
        e_tooltip(
          trigger = "axis",
          axisPointer = list(type = "cross"),
          formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
        ) %>%
        e_title(create_chart_title("채권 및 유동성 기여 수익률 비교")) %>%
        e_legend(top = "bottom") %>%
        e_toolbox_feature(feature = "saveAsImage")
    })
    
    output$factor_chart <- renderEcharts4r({
      req(input$update)
      time_series <- brinson_summary(result())[[1]]
      time_series %>%
        mutate(holding_base_ER = R_Port_a_Holding_base - R_Port_b_Holding_base) %>%
        e_charts(기준일자) %>%
        e_line(holding_base_ER, name = create_series_name("Holding base Excess Return"), showSymbol = FALSE) %>%
        e_line(A, name = "상호작용효과", showSymbol = FALSE) %>%
        e_line(B, name = "자산배분효과", showSymbol = FALSE) %>%
        e_line(C, name = "종목선택효과", showSymbol = FALSE) %>%
        e_x_axis(min = min(time_series$기준일자) - days(1), max = max(time_series$기준일자) + days(1)) %>%
        e_y_axis(formatter = e_axis_formatter("percent", digits = 2)) %>%
        e_tooltip(
          trigger = "axis",
          axisPointer = list(type = "cross"),
          formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
        ) %>%
        e_title(create_chart_title("요인별 성과 분해")) %>%
        e_legend(top = "bottom") %>%
        e_toolbox_feature(feature = "saveAsImage")
    })
    
    output$asset_class_chart <- renderEcharts4r({
      req(input$update)
      time_series <- brinson_summary(result())[[1]]
      time_series %>%
        mutate(
          holding_base_ER = R_Port_a_Holding_base - R_Port_b_Holding_base,
          주식_ER = 주식_Port_a_수익률 - 주식_Port_b_수익률,
          대체_ER = 대체_Port_a_수익률 - 대체_Port_b_수익률,
          채권및유동성_ER = 채권및유동성_Port_a_수익률 - 채권및유동성_Port_b_수익률
        ) %>%
        e_charts(기준일자) %>%
        e_line(holding_base_ER, name = create_series_name("Holding base Excess Return"), showSymbol = FALSE) %>%
        e_line(주식_ER, name = "주식", showSymbol = FALSE) %>%
        e_line(대체_ER, name = "대체", showSymbol = FALSE) %>%
        e_line(채권및유동성_ER, name = "채권 및 유동성", showSymbol = FALSE) %>%
        e_x_axis(min = min(time_series$기준일자) - days(1), max = max(time_series$기준일자) + days(1)) %>%
        e_y_axis(formatter = e_axis_formatter("percent", digits = 2)) %>%
        e_tooltip(
          trigger = "axis",
          axisPointer = list(type = "cross"),
          formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
        ) %>%
        e_title(create_chart_title("자산군별 성과 분해")) %>%
        e_legend(top = "bottom") %>%
        e_toolbox_feature(feature = "saveAsImage")
    })
    output$downloadReport <- downloadHandler(
      filename = function() {
        "PA_logic.pdf"
      },
      content = function(file) {
        file.copy("www/PA_logic.pdf", file)
      }
    )
    output$downloadData <- downloadHandler(
      filename = function() {
        paste("brinson_performance_analysis_", Sys.Date(), ".xlsx", sep = "")
      },
      content = function(file) {
        results <- brinson_summary(result())
        write_xlsx(
          list(
            "PA_results" = results[[1]],
            "Summary1" = results[[2]],
            "Summary2" = results[[3]]
          ),
          path = file
        )
      }
    )
  })
}

ui <- fluidPage(
  PAUI("pa")
)

server <- function(input, output, session) {
  PA_Server("pa")
}

shinyApp(ui, server)

