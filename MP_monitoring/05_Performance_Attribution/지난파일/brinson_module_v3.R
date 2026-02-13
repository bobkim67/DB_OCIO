library(shiny)
library(dplyr)
library(lubridate)
library(writexl)
library(kableExtra)
library(scales)

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
    height: 90vh;
  }
  .plot-output {
    height: 90% !important;
  }
.summary-table {
    margin-bottom: 70px;
}
"

PAUI <- function(id) {
  ns <- NS(id)
  tagList(
    tags$head(
      tags$style(HTML(customCSS))
    ),
    sidebarLayout(
      sidebarPanel(
        width = 2, # Adjust width
        class = "sidebar",
        
        h4("Portfolio A"),
        fluidRow(
          column(6, selectInput(ns("fund_desc_a"), "펀드", choices = Fund_Information$펀드설명)),
          column(6, selectInput(ns("name_a"), "구분", choices = c("AP", "VP", "MP", "BM")))
        ),
        fluidRow(
          column(12, htmlOutput(ns("fund_date_a")))
        ),
        
        hr(style = "border-top: 2px solid #000000;"),
        
        h4("Portfolio B"),
        fluidRow(
          column(6, selectInput(ns("fund_desc_b"), "펀드", choices = Fund_Information$펀드설명)),
          column(6, selectInput(ns("name_b"), "구분", choices = c("AP", "VP", "MP", "BM")))
        ),
        fluidRow(
          column(12, htmlOutput(ns("fund_date_b")))
        ),
        
        hr(style = "border-top: 2px solid #000000;"),
        
        h4("분석기간"),
        fluidRow(
          column(6, dateInput(ns("from_when"), "From", value = NULL)),
          column(6, dateInput(ns("to_when"), "To", value = NULL, 
                              daysofweekdisabled = c(0, 6)))
        ),
        
        hr(style = "border-top: 2px solid #000000;"),
        
        actionButton(ns("update"), "Update"),
        downloadButton(ns("downloadData"), "Download Excel")
      ),
      mainPanel(
        width = 10, # Adjust width
        class = "main-panel",
        fluidRow(
          column(4,
                 div(class = "summary-table",
                     h3("Summary Table 1"),
                     tableOutput(ns("summary1"))
                 ),
                 div(class = "summary-table",
                     h3("Holding base 성과 분해"),
                     htmlOutput(ns("summary2"))
                 )
          ),
          column(8,
                 h3("Graph(개발 중 입니다.)"),
                 div(class = "plot-container",
                     plotOutput(ns("graph"), height = "90%") # Adjust plot height
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
      processed_data <- brinson_preprocess(input$fund_desc_a, input$name_a, input$fund_desc_b, input$name_b)
      brinson_results(processed_data, input$from_when, input$to_when)
    })
    
    output$summary1 <- renderTable({
      brinson_summary(result())[[2]]  %>% 
        mutate(`Excess Return` = `Port a`- `Port b`) %>% 
        mutate(across(where(is.numeric), percent_format(accuracy = 0.01)))
    })
    
    output$summary2 <- renderUI({
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
    
    output$graph <- renderPlot({
      # 여기에 그래프 그리는 코드 추가
      plot(cars)
    })
    
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
# 
# # Example Shiny app
# ui <- fluidPage(
#   PAUI("pa")
# )
# 
# server <- function(input, output, session) {
#   PA_Server("pa")
# }
# 
# shinyApp(ui, server)
# 
