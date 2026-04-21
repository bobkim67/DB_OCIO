# app.R -----------------------------------------------------------------
# 필요한 패키지를 설치하고 로드합니다.
# install.packages(c("shiny", "tidyverse", "DT", "lubridate", "shinyjs", "inspectdf"))
library(shiny)
library(tidyverse)
library(DT)
library(lubridate)
library(shinyjs)
library(inspectdf) # inspect_na() 함수를 위해 추가


# ────────── 모듈 UI 함수 ──────────

# app.R -----------------------------------------------------------------
# ... (라이브러리 로드는 동일) ...

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
      # ... (오른쪽 컬럼 UI는 동일) ...
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
              style = "background-color: #3399FF; color: white; border: none;"
            )
          ),
          column(
            width = 4,
            fluidRow(
              column(
                width = 5,
                numericInput(ns("trading_cost"), "거래 비용(bp)", value = 0, min = 0, width = "100%")
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
      
      # Step 1: 기본 셀 편집 내용 우선 적용
      # 날짜 칼럼 편집 시 Date로 변환
      if (colnames(new_data)[j] %in% c("리밸런싱날짜", "분석시작가능일")) {
        new_val <- try(as.Date(v), silent = TRUE)
        if (!inherits(new_val, "try-error")) {
          v <- new_val
        }
      }
      new_data[i, j] <- v
      
      # Step 2: [핵심 로직] 'region'이 변경된 경우, '분석시작가능일' 연동 업데이트
      edited_col_name <- colnames(values$data)[j]
      
      # 편집된 열이 'region'이고, 해당 행이 'User_input' 데이터일 경우에만 실행
      if (edited_col_name == "region" && new_data$dataseries_id[i] == "User_input") {
        
        target_id <- new_data$dataset_id[i]
        new_region <- v
        
        # 원본 custom_ts_list에서 원본 날짜를 가져와야 중복 계산을 방지할 수 있음
        original_date <- custom_ts_list()[[target_id]]$metadata$분석시작가능일
        
        # 새로운 region 값에 따라 분석시작가능일 재계산
        new_analysis_date <- if (new_region != "KR") {
          T_move_date_calc(input_date = original_date,move = 1)
        } else {
          T_move_date_calc(input_date = original_date,move = -1) # KR로 돌아오면 원본 날짜로 복원
        }
        
        # values$data 업데이트: 동일 dataset_id를 가진 모든 행을 한번에 변경
        new_data$분석시작가능일[new_data$dataset_id == target_id] <- new_analysis_date
        new_data$리밸런싱날짜[new_data$dataset_id == target_id] <- new_analysis_date
        # custom_ts_list도 동기화
        temp_list <- custom_ts_list()
        temp_list[[target_id]]$metadata$분석시작가능일 <- new_analysis_date
        temp_list[[target_id]]$metadata$리밸런싱날짜 <- new_analysis_date
        custom_ts_list(temp_list)
        
        showNotification(paste0("'", target_id, "'의 분석시작가능일이 ", new_analysis_date, " (으)로 업데이트 되었습니다."), type = "message")
      }
      
      # Step 3: 최종 결과를 reactiveValues에 할당하여 UI에 반영
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
        # [복원] 데이터 타입 선택 UI
        radioButtons(ns("clipboard_type"), "추가할 데이터 종류 선택",
                     choices = c("설정값 템플릿" = "settings", "가격 시계열 (Wide Form)" = "timeseries"),
                     selected = "settings", inline = TRUE),
        
        # [신규] '설정값 템플릿' 선택 시 UI
        conditionalPanel(
          condition = paste0("input['", ns("clipboard_type"), "'] == 'settings'"),
          helpText("A ~ I 까지 열이름을 포함하여 복사 후 붙여넣으세요."),
        ),
        
        # [신규] '가격 시계열' 선택 시 UI
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
      
      # ---------- 1. 설정값 템플릿 추가 (기존 로직 복원) ----------
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
        
        # [수정된 부분] any() 함수를 사용하여 조건 확인
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
          # 컬럼명과 타입 일치시키기
          current_cols <- colnames(values$data)
          new_data <- new_data[, current_cols] # 순서 및 컬럼 일치
          
          # 타입 변환
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
        
        # ---------- 2. 가격 시계열 추가 (Wide Form) ----------
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
        
        
        # 1. 첫 번째 열(날짜) 유효성 검사
        # ymd() 함수로 변환을 시도하고, 변환에 실패하여 NA가 된 값이 있는지 확인합니다.
        # 단, 원래부터 비어있던 셀(NA)은 오류로 간주하지 않습니다.
        date_col <- ts_data_wide[[1]]
        converted_dates <- suppressWarnings(ymd(date_col))
        
        if (any(is.na(converted_dates) & !is.na(date_col))) {
          showModal(modalDialog(
            title = "데이터 형식 오류",
            "첫 번째 열에 날짜로 변환할 수 없는 값이 포함되어 있습니다.",
            "YYYY-MM-DD 형식을 확인해주세요.",
            easyClose = TRUE
          ))
          return() # 오류 발생 시 함수 실행 중단
        }
        
        # 2. 나머지 열(가격) 유효성 검사
        # 2번째 열부터 마지막 열까지 반복하며 숫자형으로 변환 가능한지 확인합니다.
        non_numeric_cols <- c() # 오류가 발생한 열 이름을 저장할 벡터
        for (i in 2:ncol(ts_data_wide)) {
          price_col <- ts_data_wide[[i]]
          # as.numeric으로 변환을 시도하고, 변환에 실패하여 NA가 된 값이 있는지 확인합니다.
          # 역시 원래 비어있던 셀은 오류로 간주하지 않습니다.
          converted_prices <- suppressWarnings(as.numeric(price_col))
          
          if (any(is.na(converted_prices) & !is.na(price_col))) {
            # 변환 실패 시, 해당 열의 이름을 non_numeric_cols에 추가합니다.
            non_numeric_cols <- c(non_numeric_cols, colnames(ts_data_wide)[i])
          }
        }
        
        # 숫자형 변환에 실패한 열이 하나라도 있으면 오류 메시지를 표시합니다.
        if (length(non_numeric_cols) > 0) {
          error_message <- paste0(
            "다음 열에 숫자형이 아닌 값이 포함되어 있습니다: <br><b>",
            paste(non_numeric_cols, collapse = ", "),
            "</b>"
          )
          showModal(modalDialog(
            title = "데이터 형식 오류",
            HTML(error_message), # HTML 태그를 사용하기 위해 HTML() 함수로 감쌉니다.
            easyClose = TRUE
          ))
          return() # 오류 발생 시 함수 실행 중단
        }
        
        
        # [개선된 코드 시작]
        
        # 1. Wide form 데이터를 Long form으로 변환하고 기본 전처리 수행
        ts_data_long <- ts_data_wide %>%
          rename(기준일자 = 1) %>%
          mutate(기준일자 = ymd(기준일자)) %>%
          filter(!is.na(기준일자)) %>% # 유효하지 않은 날짜 형식 제거
          pivot_longer(
            cols = -기준일자,
            names_to = "dataset_id",
            values_to = "price_custom"
          ) %>%
          mutate(price_custom = as.numeric(price_custom)) %>%
          filter(!is.na(price_custom)) %>% # 유효하지 않은 가격 형식 제거
          mutate(dataseries_id = "User_input") # 요청하신 대로 dataseries_id는 고정값으로 설정
        
        if (nrow(ts_data_long) == 0) {
          showModal(modalDialog(title = "데이터 오류", "유효한 날짜와 가격 데이터가 없습니다.", easyClose = TRUE))
          return()
        }
        
        # 2. 각 시계열(dataset_id)별로 메타데이터 생성
        new_series_metadata <- ts_data_long %>% 
          group_by(dataset_id, dataseries_id) %>%
          reframe(분석시작가능일 = ymd(nth(sort(기준일자), 2, default = NA))) %>% 
          mutate(리밸런싱날짜 =분석시작가능일) %>% 
          mutate(
            name = dataset_id,
            dataseries_name = dataseries_id, # combined_universe()에서 필요한 컬럼
            source = "USER",
            symbol = dataset_id,
            region = "KR"
          )
        
        # 3. 새로 입력된 데이터를 `custom_ts_list`가 요구하는 형식(명명된 리스트)으로 구성
        #    - 리스트의 이름: dataset_id
        #    - 리스트의 내용: list(metadata = ..., data = ...)
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
          setNames(new_dataset_ids) # 리스트의 각 항목에 dataset_id를 이름으로 부여
        
        # 4. 기존 리스트와 새 리스트를 병합하여 reactiveVal 업데이트
        #    c() 함수는 이름이 같은 항목이 있으면 새 데이터로 덮어씁니다.
        #    이것이 첫 입력, 재입력 모두를 처리하는 핵심입니다.
        updated_list <- c(custom_ts_list(), new_ts_list)
        custom_ts_list(updated_list)
        
        # [개선된 코드 끝]
        
        showNotification(
          paste(length(new_ts_list), "개의 시계열이 유니버스에 추가/업데이트 되었습니다."),
          type = "message",
          duration = 5
        )
        removeModal()
      }
    })
    
    
    
    # [수정] 필터링 로직을 담당하는 별도의 reactive
    filtered_data_reactive <- reactive({
      data_to_filter <- combined_universe() %>% 
        dplyr::select(-colname_backtest)
      
      if (nchar(trimws(input$search_universe)) > 0) {
        
        search_terms <- str_trim(unlist(strsplit(input$search_universe, split = ",")))
        
        include_terms <- search_terms[!stringr::str_starts(search_terms, "!")]
        exclude_terms <- sub("^!", "", search_terms[stringr::str_starts(search_terms, "!")])
        
        include_terms <- include_terms[include_terms != ""]
        exclude_terms <- exclude_terms[exclude_terms != ""]
        
        # '포함' 필터링
        if (length(include_terms) > 0) {
          for (term in include_terms) {
            data_to_filter <- data_to_filter %>%
              filter(
                if_any(
                  everything(), 
                  # <<< 핵심 수정: NA를 FALSE로 처리하여 모든 행이 평가되도록 함
                  ~ replace_na(str_detect(as.character(.), fixed(term, ignore_case = TRUE)), FALSE)
                )
              )
          }
        }
        
        # '제외' 필터링
        if (length(exclude_terms) > 0) {
          for (term in exclude_terms) {
            data_to_filter <- data_to_filter %>%
              filter(
                !if_any(
                  everything(), 
                  # <<< 핵심 수정: NA를 FALSE로 처리하여 모든 행이 평가되도록 함
                  ~ replace_na(str_detect(as.character(.), fixed(term, ignore_case = TRUE)), FALSE)
                )
              )
          }
        }
      }
      
      return(data_to_filter)
    })
    
    # 검색 결과 건수 출력
    output$universe_count_text <- renderText({
      req(filtered_data_reactive(), combined_universe())
      result_count <- nrow(filtered_data_reactive())
      total_count <- nrow(combined_universe())
      paste0("(", result_count, " / ", total_count, " 건)")
    })
    
    # 테이블 렌더링
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
    
    
    
    # 유니버스에서 선택된 종목 편집테이블에 추가
    observeEvent(input$add_selected, {
      sel_row <- input$universe_table_rows_selected
      if(length(sel_row) > 0) {
        filtered_data <- selected_universe()
        selected_data <- filtered_data[sel_row, ]
        
        # 만약 테이블이 비어있다면 새로 한행 생성
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
          # 기존 마지막 행의 리밸런싱일자를 복제, 나머지는 선택된 종목 정보 기본값으로 대체
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
    # "검색된 모든 행을 유니버스에 추가" 버튼
    observeEvent(input$add_all, {
      filtered_data <- selected_universe()
      if (nrow(filtered_data) > 0) {
        # 기존 데이터와 병합하여 추가
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
        
        # 데이터를 values$data에 추가
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
      
      # (1) 중복 체크
      duplicates <- values$data %>%
        group_by(리밸런싱날짜, Portfolio, dataset_id, dataseries_id) %>%
        filter(n() > 1)
      
      if (nrow(duplicates) > 0) {
        showModal(modalDialog(title = "중복 오류", "동일 리밸런싱 날짜에 중복된 자산이 존재합니다.", easyClose = TRUE))
        return()
      }
      
      # (2) 날짜 < 분석시작가능일 체크
      data_not_available <- values$data %>% filter(리밸런싱날짜 < 분석시작가능일)
      
      if (nrow(data_not_available) > 0) {
        showModal(modalDialog(title = "분석기간 오류", "리밸런싱 날짜가 분석시작가능일보다 빠른 항목이 있습니다.", easyClose = TRUE))
        return()
      }
      
      
      
      # (3) weight = 0인 경우
      
      weight_is_zero <- values$data %>% 
        
        filter(weight == 0)
      
      
      
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
        
        # 1. 로컬 변수에 데이터를 먼저 준비합니다.
        user_price_data <- purrr::map_dfr(custom_ts_list(), ~ .x$data, .id = "dataset_id")
        user_meta_data <- purrr::map_dfr(custom_ts_list(), ~ .x$metadata, .id = "dataset_id")
        
        # 2. assign() 함수를 사용하여 .GlobalEnv에 명시적으로 할당합니다.
        # assign("변수이름", 저장할 값, envir = .GlobalEnv)
        
        assign("USER_historical_price", user_price_data, envir = .GlobalEnv)
        
        # user_data_inform 도 동일하게 처리합니다.
        assign("user_data_inform", user_meta_data, envir = .GlobalEnv) 
        
        # data_information_integrated 도 마찬가지입니다.
        integrated_info <- data_information %>% 
          bind_rows(user_meta_data) %>% 
          mutate(colname_backtest = if_else(is.na(ISIN), name, symbol)) %>% 
          mutate(colname_backtest = if_else(grepl("^[0-9]+$", colname_backtest), name, colname_backtest))
        
        assign("data_information_integrated", integrated_info, envir = .GlobalEnv)
        
        # 디버깅을 위해 할당 후 확인 메시지를 출력할 수 있습니다.
        message("사용자 데이터가 전역 환경에 할당되었습니다.")
        
      } else {
        # 사용자 데이터가 없을 경우, 전역 변수를 NULL로 초기화합니다.
        assign("USER_historical_price", NULL, envir = .GlobalEnv)
        assign("user_data_inform", NULL, envir = .GlobalEnv)
        assign("data_information_integrated", NULL, envir = .GlobalEnv)
        
        message("사용자 데이터가 없어 전역 변수를 NULL로 초기화합니다.")
      }
      
      
      res <- backtesting_for_users_input(
        backtest_prep_table = data_to_use %>% select(-contains("colname_backtest")),
        rebalancing_option = if_else(str_detect(input$rebalance_setting, "A"), "A", "B"),
        `trading_cost(bp)` = input$trading_cost # <<< 이 줄이 추가되었습니다.
      )
      
      
      backtest_results(res)
      # 4) 자동으로 "결과 페이지" 탭으로 이동
      #    parent_session 이 넘어왔다면 그걸 이용, 없으면 fallback
      if(!is.null(parent_session)) {
        updateTabsetPanel(session = parent_session, 
                          inputId = "tabs", 
                          selected = "결과 페이지")
      } else {
        # fallback
        updateTabsetPanel(session = getDefaultReactiveDomain()$parent,
                          inputId = "tabs", 
                          selected = "결과 페이지")
      }
    })
    
    return(
      list(
        settings = reactive(values$data),
        custom_data = custom_ts_list
      )
    )
  })
}