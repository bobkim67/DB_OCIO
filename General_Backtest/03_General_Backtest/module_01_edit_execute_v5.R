# app.R -----------------------------------------------------------------
# 필요한 패키지를 설치하고 로드합니다.
# install.packages(c("shiny", "tidyverse", "DT", "lubridate", "shinyjs", "inspectdf", "writexl"))
library(shiny)
library(tidyverse)
library(DT)
library(lubridate)
library(shinyjs)
library(inspectdf) # inspect_na() 함수를 위해 추가
library(writexl)   # 엑셀 다운로드를 위해 writexl 패키지를 로드합니다.


# ────────── 모듈 UI 함수 ──────────

mod_edit_execute_ui <- function(id) {
  ns <- NS(id)
  
  tagList(
    useShinyjs(),
    fluidRow(
      column(
        width = 5,
        style = "border-right: 2px solid #cccccc; padding-right: 20px;",
        
        
        fluidRow(
          column(width = 8,
                 textInput(ns("search_universe"), "유니버스 검색", "")
          ),
          column(width = 4, 
                 style = "text-align: right; padding-top: 30px; font-weight: bold;",
                 # 검색 결과 건수를 표시할 UI
                 textOutput(ns("universe_count_text"))
          )
        ),
        
        
        DTOutput(ns("universe_table")),
        
        fluidRow(
          column(
            width = 6,
            actionButton(ns("add_selected"), "선택 행 추가 →",
                         style = "background-color: #727272; color: white; border-radius: 5px; width: 100%;")
          ),
          column(
            width = 6,
            actionButton(ns("add_all"), "검색된 모든 행 추가 →",
                         style = "background-color: #4CAF50; color: white; border-radius: 5px; width: 100%;")
          )
        )
      ),
      column(
        width = 7,
        style = "padding-left: 20px;",
        fluidRow(
          column(
            width = 8,
            actionButton(ns("add_from_clipboard"), "클립보드에서 데이터 추가",
                         style = "background-color: #4CAF50; color: white; border-radius: 5px;"),
            actionButton(ns("remove_row"), "선택 행 제거",
                         style = "background-color: #FF9800; color: white; border-radius: 5px;"),
            actionButton(ns("remove_all_rows"), "모든 행 제거",
                         style = "background-color: #f44336; color: white; border-radius: 5px;"),
            
            actionButton(
              ns("run"), "백테스트 실행",
              style = "background-color: #3399FF; color: white; border: none; vertical-align: top;"
            ),
            shinyjs::disabled(
              downloadButton(
                ns("download_settings"), "Raw data",
                icon = icon("file-excel"),  style = "background-color: black; color: white; border-color: black;margin-top: 0px;",
                width = "100%"
              )
            )
          ),
          column(
            width = 4,
            fluidRow(
              column(
                width = 5,
                numericInput(ns("trading_cost"), "거래 비용(bp)", value = 0, min = 0, width = "100%")
              ),
              column(5,
                     # Source: BOS 체크박스를 오른쪽에 배치
                     checkboxInput(ns("hedge_cost_strictly"), "환헷지비용", value = FALSE)
              ),
              column(
                width = 7,
                selectInput(ns("rebalance_setting"),
                            "리밸런싱-세부설정",
                            choices = c("(수익률A , 포지션 A)", "(수익률B , 포지션B)"),
                            selected = "(수익률A , 포지션 A)",
                            width = "100%")
              )
            )
          )
        ),
        h3("백테스트 데이터 편집", style = "color: #333333; font-weight: bold;"),
        DTOutput(ns("edit_table"))
      )
    )
  )
}
# ────────── 모듈 서버 함수 ──────────
mod_edit_execute_server <- function(
    id,
    sb_back,
    data_information,
    backtest_results,
    parent_session = NULL
) {
  moduleServer(id, function(input, output, session) {
    
    ns <- session$ns
    
    values <- reactiveValues(data = sb_back)
    custom_ts_list <- reactiveVal(list())
    selected_universe <- reactiveVal(NULL)
    
    combined_universe <- reactive({
      custom_meta <- map_df(custom_ts_list(), ~ .x$metadata)
      req_cols <- c("dataset_id", "dataseries_id","dataseries_name","source" ,"name", "symbol","region", "분석시작가능일")
      
      bind_rows(
        data_information ,
        custom_meta 
      ) %>% 
        distinct(dataset_id,dataseries_id, .keep_all = TRUE)
    })
    
    # [핵심 수정 1] data_information_integrated를 생성하는 로직을 reactive로 분리합니다.
    # 이렇게 하면 '백테스트 실행'과 '설정 다운로드' 양쪽에서 안전하게 호출할 수 있습니다.
    data_information_integrated_reactive <- reactive({
      base_info <- data_information
      
      if (is.list(custom_ts_list()) && length(custom_ts_list()) > 0) {
        user_meta_data <- purrr::map_dfr(custom_ts_list(), ~ .x$metadata, .id = "dataset_id")
        base_info <- bind_rows(base_info, user_meta_data)
      }
      
      integrated_info <- base_info %>%
        mutate(colname_backtest = if_else(is.na(ISIN), name, symbol)) %>%
        mutate(colname_backtest = if_else(grepl("^[0-9]+$", colname_backtest), name, colname_backtest))
      
      return(integrated_info)
    })
    
    output$edit_table <- renderDT({
      datatable(
        values$data,
        editable = list(target = "cell", disable = list(columns = c(3, 4, 5, 6))),
        selection = "multiple",
        options = list(dom = 'tp', pageLength = 10, scrollX = TRUE, scrollY = "600px", paging = FALSE),
        style = "bootstrap",
        class = "display"
      ) %>%
        formatStyle(
          columns = c("name", "분석시작가능일", "dataset_id", "dataseries_id"),
          cursor = "not-allowed",
          backgroundColor = "lightgrey"
        )
    })
    
    observeEvent(input$edit_table_cell_edit, {
      info <- input$edit_table_cell_edit
      i <- info$row
      j <- info$col
      v <- info$value
      
      new_data <- values$data
      
      if (colnames(new_data)[j] %in% c("리밸런싱날짜", "분석시작가능일")) {
        new_val <- try(as.Date(v), silent = TRUE)
        if (!inherits(new_val, "try-error")) {
          v <- new_val
        }
      }
      new_data[i, j] <- v
      
      edited_col_name <- colnames(values$data)[j]
      
      if (edited_col_name == "region" && new_data$dataseries_id[i] == "User_input") {
        
        target_id <- new_data$dataset_id[i]
        new_region <- v
        
        original_date <- custom_ts_list()[[target_id]]$metadata$분석시작가능일
        
        new_analysis_date <- if (new_region != "KR") {
          T_move_date_calc(input_date = original_date,move = 1)
        } else {
          T_move_date_calc(input_date = original_date,move = -1)
        }
        
        new_data$분석시작가능일[new_data$dataset_id == target_id] <- new_analysis_date
        new_data$리밸런싱날짜[new_data$dataset_id == target_id] <- new_analysis_date
        
        temp_list <- custom_ts_list()
        temp_list[[target_id]]$metadata$분석시작가능일 <- new_analysis_date
        temp_list[[target_id]]$metadata$리밸런싱날짜 <- new_analysis_date
        custom_ts_list(temp_list)
        
        showNotification(paste0("'", target_id, "'의 분석시작가능일이 ", new_analysis_date, " (으)로 업데이트 되었습니다."), type = "message")
      }
      
      values$data <- new_data
    })
    
    observeEvent(input$remove_row, {
      selected_rows <- input$edit_table_rows_selected
      if (length(selected_rows) > 0) {
        values$data <- values$data[-selected_rows, , drop = FALSE]
      } else {
        showModal(modalDialog(title = "삭제 오류", "삭제할 행을 선택해주세요.", easyClose = TRUE))
      }
    })
    
    observeEvent(input$remove_all_rows, {
      values$data <- values$data[0, , drop = FALSE]
    })
    
    observeEvent(input$add_from_clipboard, {
      showModal(modalDialog(
        title = "클립보드에서 데이터 추가",
        radioButtons(ns("clipboard_type"), "추가할 데이터 종류 선택",
                     choices = c("설정값 템플릿" = "settings", "가격 시계열 (Wide Form)" = "timeseries"),
                     selected = "settings", inline = TRUE),
        
        conditionalPanel(
          condition = paste0("input['", ns("clipboard_type"), "'] == 'settings'"),
          helpText("A ~ I 까지 열이름을 포함하여 복사 후 붙여넣으세요."),
        ),
        
        conditionalPanel(
          condition = paste0("input['", ns("clipboard_type"), "'] == 'timeseries'"),
          helpText("형식: 첫 열은 날짜(YYYY-MM-DD), 나머지 열은 각 시계열의 가격 데이터입니다.",
                   "각 시계열의 이름이 되는 헤더(첫 행)가 반드시 있어야 합니다. 데이터는 각각 분리되어 User_input 이라는 dataseries_id로 추가됩니다. "),
        ),
        
        textAreaInput(ns("clipboard_input"), "붙여넣기 할 내용", "", rows = 10, width = "100%"),
        
        actionButton(ns("save_clip_data"), "데이터 추가하기"),
        easyClose = TRUE,
        footer = NULL
      ))
    })
    
    observeEvent(input$save_clip_data, {
      input_data <- input$clipboard_input
      if (nchar(trimws(input_data)) == 0) {
        showModal(modalDialog(title = "입력 오류", "붙여넣은 데이터가 없습니다.", easyClose = TRUE))
        return()
      }
      
      if (input$clipboard_type == "settings") {
        new_data <- tryCatch({
          read.table(text = input_data, header = TRUE, sep = "\t", stringsAsFactors = FALSE, check.names = FALSE) %>% as_tibble()
        }, error = function(e) {
          showModal(modalDialog(title = "오류", "입력된 데이터를 처리하는 중 오류가 발생했습니다.", easyClose = TRUE))
          return(NULL)
        })
        
        if (is.null(new_data) || nrow(new_data) == 0) return()
        
        if (ncol(new_data) != ncol(values$data %>% select(-name, -분석시작가능일))) {
          showModal(modalDialog(title = "형식 오류", "클립보드의 데이터 열 개수 혹은 순서를 확인해주세요.", easyClose = TRUE))
          return()
        }
        
        if (any(inspectdf::inspect_na(new_data)$pcnt > 0)) {
          showModal(modalDialog(title = "결측치 오류", "비어있는 셀이 있습니다. 모든 셀의 값을 채워주세요.", easyClose = TRUE))
          return()
        }
        
        new_data <- new_data %>%
          mutate(across(.cols = everything(), .fns = as.character)) %>%
          left_join(
            combined_universe() %>% select(dataset_id, dataseries_id, name, 분석시작가능일) %>% distinct(),
            by = c("dataset_id", "dataseries_id")
          ) %>%
          relocate(name, 분석시작가능일, .before = dataset_id)
        
        tryCatch({
          current_cols <- colnames(values$data)
          new_data <- new_data[, current_cols]
          
          new_data <- new_data %>%
            mutate(
              리밸런싱날짜 = ymd(리밸런싱날짜),
              분석시작가능일 = ymd(분석시작가능일),
              weight = as.numeric(weight),
              hedge_ratio = as.numeric(hedge_ratio),
              cost_adjust = as.numeric(cost_adjust),
              tracking_multiple = as.numeric(tracking_multiple)
            )
          
          values$data <- bind_rows(values$data, new_data)
          showNotification("설정값 템플릿이 성공적으로 추가되었습니다.", type = "message")
          removeModal()
        }, error = function(e) {
          showModal(modalDialog(title = "데이터 추가 오류", paste("데이터를 추가하는 중 오류 발생:", e$message), easyClose = TRUE))
        })
        
      } else if (input$clipboard_type == "timeseries") {
        ts_data_wide <- tryCatch({
          read.table(text = input_data, header = TRUE, sep = "\t", stringsAsFactors = FALSE, check.names = FALSE) %>% as_tibble()
        }, error = function(e) {
          showModal(modalDialog(title = "파싱 오류", "데이터를 읽는 데 실패했습니다. 탭(Tab)으로 구분된 형식이 맞는지 확인해주세요.", easyClose = TRUE))
          return(NULL)
        })
        
        if(is.null(ts_data_wide) || ncol(ts_data_wide) < 2) {
          showModal(modalDialog(title = "형식 오류", "데이터는 최소 2개 열(날짜, 가격)이 필요합니다.", easyClose = TRUE))
          return()
        }
        
        date_col <- ts_data_wide[[1]]
        converted_dates <- suppressWarnings(ymd(date_col))
        
        if (any(is.na(converted_dates) & !is.na(date_col))) {
          showModal(modalDialog(
            title = "데이터 형식 오류",
            "첫 번째 열에 날짜로 변환할 수 없는 값이 포함되어 있습니다.",
            "YYYY-MM-DD 형식을 확인해주세요.",
            easyClose = TRUE
          ))
          return()
        }
        
        non_numeric_cols <- c()
        for (i in 2:ncol(ts_data_wide)) {
          price_col <- ts_data_wide[[i]]
          converted_prices <- suppressWarnings(as.numeric(price_col))
          
          if (any(is.na(converted_prices) & !is.na(price_col))) {
            non_numeric_cols <- c(non_numeric_cols, colnames(ts_data_wide)[i])
          }
        }
        
        if (length(non_numeric_cols) > 0) {
          error_message <- paste0(
            "다음 열에 숫자형이 아닌 값이 포함되어 있습니다: <br><b>",
            paste(non_numeric_cols, collapse = ", "),
            "</b>"
          )
          showModal(modalDialog(
            title = "데이터 형식 오류",
            HTML(error_message),
            easyClose = TRUE
          ))
          return()
        }
        
        ts_data_long <- ts_data_wide %>%
          rename(기준일자 = 1) %>%
          mutate(기준일자 = ymd(기준일자)) %>%
          filter(!is.na(기준일자)) %>%
          pivot_longer(
            cols = -기준일자,
            names_to = "dataset_id",
            values_to = "price_custom"
          ) %>%
          mutate(price_custom = as.numeric(price_custom)) %>%
          filter(!is.na(price_custom)) %>%
          mutate(dataseries_id = "User_input")
        
        if (nrow(ts_data_long) == 0) {
          showModal(modalDialog(title = "데이터 오류", "유효한 날짜와 가격 데이터가 없습니다.", easyClose = TRUE))
          return()
        }
        
        new_series_metadata <- ts_data_long %>% 
          group_by(dataset_id, dataseries_id) %>%
          reframe(분석시작가능일 = ymd(nth(sort(기준일자), 2, default = NA))) %>% 
          mutate(리밸런싱날짜 =분석시작가능일) %>% 
          mutate(
            name = dataset_id,
            dataseries_name = dataseries_id,
            source = "USER",
            symbol = dataset_id,
            region = "KR"
          )
        
        new_dataset_ids <- unique(new_series_metadata$dataset_id)
        
        new_ts_list <- purrr::map(new_dataset_ids, function(id) {
          list(
            metadata = new_series_metadata %>% filter(dataset_id == id),
            data = ts_data_long %>%
              filter(dataset_id == id) %>%
              select(기준일자, price_custom) %>%
              arrange(기준일자)
          )
        }) %>%
          setNames(new_dataset_ids)
        
        updated_list <- c(custom_ts_list(), new_ts_list)
        custom_ts_list(updated_list)
        
        showNotification(
          paste(length(new_ts_list), "개의 시계열이 유니버스에 추가/업데이트 되었습니다."),
          type = "message",
          duration = 5
        )
        removeModal()
      }
    })
    
    filtered_data_reactive <- reactive({
      data_to_filter <- combined_universe() %>% 
        dplyr::select(-colname_backtest)
      
      if (nchar(trimws(input$search_universe)) > 0) {
        
        search_terms <- str_trim(unlist(strsplit(input$search_universe, split = ",")))
        
        include_terms <- search_terms[!stringr::str_starts(search_terms, "!")]
        exclude_terms <- sub("^!", "", search_terms[stringr::str_starts(search_terms, "!")])
        
        include_terms <- include_terms[include_terms != ""]
        exclude_terms <- exclude_terms[exclude_terms != ""]
        
        if (length(include_terms) > 0) {
          for (term in include_terms) {
            data_to_filter <- data_to_filter %>%
              filter(
                if_any(
                  everything(), 
                  ~ replace_na(str_detect(as.character(.), fixed(term, ignore_case = TRUE)), FALSE)
                )
              )
          }
        }
        
        if (length(exclude_terms) > 0) {
          for (term in exclude_terms) {
            data_to_filter <- data_to_filter %>%
              filter(
                !if_any(
                  everything(), 
                  ~ replace_na(str_detect(as.character(.), fixed(term, ignore_case = TRUE)), FALSE)
                )
              )
          }
        }
      }
      
      return(data_to_filter)
    })
    
    output$universe_count_text <- renderText({
      req(filtered_data_reactive(), combined_universe())
      result_count <- nrow(filtered_data_reactive())
      total_count <- nrow(combined_universe())
      paste0("(", result_count, " / ", total_count, " 건)")
    })
    
    output$universe_table <- renderDT({
      filtered_data <- filtered_data_reactive()
      selected_universe(filtered_data)
      datatable(
        filtered_data,
        selection = "single",
        options = list(dom = 'tp', pageLength = 10, scrollX = TRUE, scrollY = "600px", paging = FALSE),
        rownames = FALSE
      )
    })
    
    observeEvent(input$add_selected, {
      sel_row <- input$universe_table_rows_selected
      if(length(sel_row) > 0) {
        filtered_data <- selected_universe()
        selected_data <- filtered_data[sel_row, ]
        
        if (nrow(values$data) == 0) {
          new_row <- tibble(
            리밸런싱날짜 = floor_date(today(), unit = "year"),
            Portfolio = if_else(is.na(selected_data$symbol),selected_data$name,selected_data$symbol),
            name = as.character(selected_data$name),
            분석시작가능일 = ymd(selected_data$분석시작가능일),
            dataset_id = as.character(selected_data$dataset_id),
            dataseries_id = as.character(selected_data$dataseries_id),
            region = selected_data$region,
            weight = 1,
            hedge_ratio = 0,
            cost_adjust = 0,
            tracking_multiple =1
          )
        } else {
          new_row <- tail(values$data, 1)
          new_row$Portfolio <- if_else(is.na(selected_data$symbol),selected_data$name,selected_data$symbol)
          new_row$name <- as.character(selected_data$name)
          new_row$분석시작가능일 <- ymd(selected_data$분석시작가능일)
          new_row$dataset_id <- as.character(selected_data$dataset_id)
          new_row$dataseries_id <- as.character(selected_data$dataseries_id)
          new_row$region <- selected_data$region
          new_row$weight <- 1
          new_row$hedge_ratio <- 0
          new_row$cost_adjust <- 0
          new_row$tracking_multiple  <- 1
          
        }
        values$data <- bind_rows(values$data, new_row) 
      } else {
        showModal(modalDialog(
          title = "선택 오류",
          "유니버스를 선택해주세요.",
          easyClose = TRUE
        ))
      }
    })
    
    observeEvent(input$add_all, {
      filtered_data <- selected_universe()
      if (nrow(filtered_data) > 0) {
        new_data <- filtered_data %>%
          mutate(
            리밸런싱날짜 = 분석시작가능일,
            Portfolio = if_else(is.na(symbol), name, symbol),
            weight = 1,
            hedge_ratio = 0,
            cost_adjust = 0,
            tracking_multiple = 1
          ) %>% 
          select(-c(symbol,ISIN,dataseries_name,source)) 
        
        values$data <- bind_rows(values$data, new_data)
        
        showModal(modalDialog(
          title = "모든 데이터 추가 완료",
          "검색된 모든 데이터가 유니버스에 추가되었습니다.",
          easyClose = TRUE
        ))
      } else {
        showModal(modalDialog(
          title = "검색된 데이터 없음",
          "검색된 데이터가 없습니다.",
          easyClose = TRUE
        ))
      }
    })
    
    observeEvent(input$run, {
      req(nrow(values$data) > 0)
      
      duplicates <- values$data %>%
        group_by(리밸런싱날짜, Portfolio, dataset_id, dataseries_id,hedge_ratio, tracking_multiple) %>%
        filter(n() > 1)
      
      if (nrow(duplicates) > 0) {
        showModal(modalDialog(title = "중복 오류", "동일 리밸런싱 날짜에 중복된 자산이 존재합니다.", easyClose = TRUE))
        return()
      }
      
      data_not_available <- values$data %>% filter(리밸런싱날짜 < 분석시작가능일)
      
      if (nrow(data_not_available) > 0) {
        showModal(modalDialog(title = "분석기간 오류", "리밸런싱 날짜가 분석시작가능일보다 빠른 항목이 있습니다.", easyClose = TRUE))
        return()
      }
      
      weight_is_zero <- values$data %>% filter(weight == 0)
      
      if (nrow(weight_is_zero) > 0) {
        weight_is_zero_message <- paste0(unique(weight_is_zero$Portfolio), collapse = ", ")
        showModal(modalDialog(
          title = "비중 입력 확인",
          HTML(paste("아래 Portfolio에 weight 가 0인 데이터셋 존재: <br>", weight_is_zero_message)),
          easyClose = TRUE
        ))
        return()
      }
      
      data_to_use <- values$data %>%
        arrange(리밸런싱날짜) %>%
        select(-name, -분석시작가능일) %>%
        group_by(리밸런싱날짜, Portfolio) %>%
        mutate(weight = weight / sum(weight)) %>%
        ungroup()
      
      if (is.list(custom_ts_list()) && length(custom_ts_list()) > 0) {
        
        user_price_data <- purrr::map_dfr(custom_ts_list(), ~ .x$data, .id = "dataset_id")
        user_meta_data <- purrr::map_dfr(custom_ts_list(), ~ .x$metadata, .id = "dataset_id")
        
        assign("USER_historical_price", user_price_data, envir = .GlobalEnv)
        assign("user_data_inform", user_meta_data, envir = .GlobalEnv) 
        
        # [핵심 수정 2] '백테스트 실행' 시에도 위에서 만든 reactive를 사용하여 일관성을 유지합니다.
        assign("data_information_integrated", data_information_integrated_reactive(), envir = .GlobalEnv)
        
        message("사용자 데이터가 전역 환경에 할당되었습니다.")
        
      } else {
        assign("USER_historical_price", NULL, envir = .GlobalEnv)
        assign("user_data_inform", NULL, envir = .GlobalEnv)
        assign("data_information_integrated", NULL, envir = .GlobalEnv)
        message("사용자 데이터가 없어 전역 변수를 NULL로 초기화합니다.")
      }
      
      res <- backtesting_for_users_input(
        backtest_prep_table = data_to_use %>% select(-contains("colname_backtest")),
        rebalancing_option = if_else(str_detect(input$rebalance_setting, "A"), "A", "B"),
        `trading_cost(bp)` = input$trading_cost,
        hedge_cost_strictly = input$hedge_cost_strictly
      )
      
      backtest_results(res)
      
      if(!is.null(parent_session)) {
        updateTabsetPanel(session = parent_session, 
                          inputId = "tabs", 
                          selected = "결과 페이지")
      } else {
        updateTabsetPanel(session = getDefaultReactiveDomain()$parent,
                          inputId = "tabs", 
                          selected = "결과 페이지")
      }
    })
    
    # [핵심 수정 3] 다운로드 핸들러 로직을 수정합니다.
    output$download_settings <- downloadHandler(
      filename = function() {
        paste0("Raw_data_", Sys.time(), ".xlsx")
      },
      content = function(file) {
        req(values$data, nrow(values$data) > 0)
        
        # --- 첫 번째 시트: Input_Summary ---
        # 사용자가 편집한 테이블(values$data)을 요약합니다.
        # (long_form_raw_data_input 함수가 있다고 가정하고 코드를 작성했습니다.)
        input_summary_data <- values$data %>%
          group_by(dataset_id, dataseries_id, region) %>%
          summarise(분석시작일 = min(리밸런싱날짜, na.rm = TRUE), .groups = 'drop') 
        data_to_download<- long_form_raw_data_input(
          combined_data = input_summary_data
        )
        # long_form_raw_data_input 함수가 있다면 아래 주석을 해제하세요.
        # input_summary_data <- long_form_raw_data_input(
        #   combined_data = input_summary_data
        # )
        
        # --- 두 번째 시트: Total_Universe ---
        # 위에서 만든 reactive를 호출하여 전체 유니버스 정보를 가져옵니다.
        # 이렇게 하면 '백테스트 실행'을 누르지 않아도 항상 최신 데이터를 가져옵니다.
        universe_data <- data_information_integrated_reactive()
        
        # --- 엑셀 파일 생성 ---
        # 시트 이름(예: "Input_Summary")과 데이터프레임(input_summary_data)을
        # 짝지어 리스트로 만듭니다.
        writexl::write_xlsx(
          list(
            "Template" = values$data,
            "Input_Summary" = data_to_download, 
            "Total_Universe" = universe_data
          ), 
          file
        )
      }
    )
    
    return(
      list(
        settings = reactive(values$data),
        custom_data = custom_ts_list
      )
    )
  })
}