library(shiny)
library(dplyr)
library(lubridate)
library(writexl)

PAUI <- function(id) {
  ns <- NS(id)
  tagList(
    sidebarLayout(
      sidebarPanel(
        width = 3,
        
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
        width = 9,
        h3("Summary Table 1"),
        tableOutput(ns("summary1")),
        h3("Summary Table 2"),
        tableOutput(ns("summary2"))
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
                                 !(기준일자 %in% KOREA_holidays$`Holiday Date`)) %>%
                        pull(기준일자))
      
      updateDateInput(session, "from_when", value = from_date, min = from_date, max = max_date)
      updateDateInput(session, "to_when", value = max_date, min = from_date, max = max_date)
    })
    
    result <- eventReactive(input$update, {
      processed_data <- brinson_preprocess(input$fund_desc_a, input$name_a, input$fund_desc_b, input$name_b)
      brinson_results(processed_data, input$from_when, input$to_when)
    })
    
    output$summary1 <- renderTable({
      brinson_summary(result())[[2]]
    })
    
    output$summary2 <- renderTable({
      brinson_summary(result())[[3]]
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

