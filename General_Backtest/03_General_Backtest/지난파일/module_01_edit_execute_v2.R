# mod_edit_execute.R ---------------------
library(shiny)
library(tidyverse)
library(DT)
library(lubridate)
library(clipr)
#https://connect.appsilon.com/shiny-semantic-components/
# ────────── 모듈 UI 함수 ──────────

mod_edit_execute_ui <- function(id) {
  ns <- NS(id)
  
  tabPanel(
    title = "편집 & 실행",   # 상단 탭 제목
    fluidRow(
      column(
        width = 5,
        style = "border-right: 2px solid #cccccc; padding-right: 20px;",  # Right border for separation
        textInput(ns("search_universe"), "유니버스 검색", ""),
        DTOutput(ns("universe_table")),
        
        # 두 개의 버튼을 한 줄에 배치
        fluidRow(
          column(
            width = 6,  # 50% 너비
            actionButton(ns("add_selected"), "선택된 행을 유니버스에 추가 →", 
                         style = "background-color: #727272; color: white; border-radius: 5px; width: 100%;")
          ),
          column(
            width = 6,  # 50% 너비
            actionButton(ns("add_all"), "검색된 모든 행을 유니버스에 추가 →", 
                         style = "background-color: #4CAF50; color: white; border-radius: 5px; width: 100%;")
          )
        )
      ),
      column(
        width = 7,
        style = "padding-left: 20px;",  # Left padding to match the right border space
        fluidRow(
          column(
            width = 8,
            actionButton(ns("add_from_clipboard"), "클립보드에서 데이터 추가", 
                         style = "background-color: #4CAF50; color: white; border-radius: 5px;"),
            actionButton(ns("remove_row"), "선택된 행 제거", 
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
            # "리밸런싱날짜-세부설정" SelectInput 추가
            selectInput(ns("rebalance_setting"), 
                        "리밸런싱-세부설정", 
                        choices = c("(수익률A , 포지션 A)", "(수익률B , 포지션B)"), 
                        selected = "(수익률A , 포지션 A)",
                        width = "100%")
          )
        ),
        h3("백테스트 데이터 편집", style = "color: #333333; font-weight: bold;"),
        DTOutput(ns("edit_table"))
      )
    ),
  )
}



# ────────── 모듈 서버 함수 ──────────
mod_edit_execute_server <- function(
    id,
    sb_back,            # 초기 테이블(ex: sb_back) 
    data_information,   # 유니버스 정보
    backtest_results,    # 백테스트 결과를 저장할 reactiveVal(메인 서버에서 정의)
    parent_session = NULL  # 탭 전환 위해 부모 세션을 넘겨받기 (필요시)
) {
  moduleServer(id, function(input, output, session) {
    
    ns <- session$ns
    
    # 초기 데이터 로드
    values <- reactiveValues(data = sb_back)
    
    # 선택된 유니버스 (DT 테이블에서 하나만 선택되도록 설정)
    selected_universe <- reactiveVal(NULL)
    
    # ────────── 편집 테이블 출력 ──────────
    output$edit_table <- renderDT({
      datatable(
        values$data,
        editable = list(
          target = "cell",
          # (name, 분석시작가능일, dataset_id, dataseries_id)은 편집 비활성
          disable = list(columns = c(3,4,5,6))
        ),
        selection = "multiple",
        options = list(
          pageLength = 10,
          scrollX = TRUE,
          autoWidth = TRUE
        ),
        style = "bootstrap",
        class = "display"
      ) %>% 
        formatStyle(
          columns = c("name", "분석시작가능일","dataset_id","dataseries_id"),
          cursor = "not-allowed",
          backgroundColor = "lightgrey"
        )
    })
    
    # 테이블 셀 편집(리밸런싱날짜,weight 등) 후 반영
    observeEvent(input$edit_table_cell_edit, {
      info <- input$edit_table_cell_edit
      i <- info$row
      j <- info$col
      v <- info$value
      # 날짜 칼럼 편집 시 Date로 변환
      if (colnames(values$data)[j] == "리밸런싱날짜" && !is.na(as.Date(v))) {
        v <- as.Date(v)
      }
      new_data <- values$data
      new_data[i, j] <- v
      values$data <- new_data
      # 확인용 출력
      # print(values$data)
    })
    
    # 선택 행 제거
    observeEvent(input$remove_row, {
      selected_rows <- input$edit_table_rows_selected
      if(length(selected_rows) > 0) {
        new_data <- values$data[-selected_rows, , drop=FALSE]
        values$data <- new_data
      } else {
        showModal(modalDialog(
          title = "삭제 오류",
          "삭제할 행을 선택해주세요.",
          easyClose = TRUE
        ))
      }
    })
    
    # 모든 행 제거
    observeEvent(input$remove_all_rows, {
      values$data <- values$data[0, , drop = FALSE]
    })
    
    
    observeEvent(input$add_from_clipboard, {
      showModal(modalDialog(
        title = "클립보드 데이터 입력",
        textAreaInput(ns("clipboard_input"), "클립보드 텍스트", "", rows = 10),
        actionButton(ns("save_clip_data"), "데이터 추가하기"),
        easyClose = TRUE,
        footer = NULL
      ))
    })
    
    
    # 클립보드에서 데이터 추가
    observeEvent(input$save_clip_data, {
      input_data <- input$clipboard_input  # 사용자 입력 데이터
      
      # 입력된 텍스트 데이터를 data.frame으로 변환
      new_data <- tryCatch({
        read.table(text = input_data, header = TRUE, sep = "\t", stringsAsFactors = FALSE) %>% as_tibble()
      }, error = function(e) {
        showModal(modalDialog(
          title = "오류",
          "입력된 데이터를 처리하는 중 오류가 발생했습니다.",
          easyClose = TRUE,
          footer = NULL
        ))
        return(NULL)
      })
      
      # 문제 없을 시 기존 테이블에 추가
      if (!is.null(new_data)) {
        # 행 수가 0인 경우
        if (nrow(new_data) == 0) {
          showModal(modalDialog(
            title = "행 수 오류",
            "클립보드의 데이터가 비어 있습니다.",
            easyClose = TRUE,
            footer = NULL
          ))
          return()
        }
        
        # 편집 테이블에서 name/분석시작가능일 컬럼 제외 후 열 수와 비교
        if (ncol(new_data) != ncol(values$data %>% select(-name,-분석시작가능일))) {
          showModal(modalDialog(
            title = "형식 오류",
            "클립보드의 데이터 열 개수 혹은 순서를 확인해주세요.",
            easyClose = TRUE,
            footer = NULL
          ))
          return()
        }
        
        # 결측치 검사
        na_percentage <- new_data %>%
          inspectdf::inspect_na() %>%
          dplyr::pull(pcnt) %>%
          max()
        
        if (na_percentage != 0) {
          showModal(modalDialog(
            title = "결측치 오류",
            "비어있는 셀이 있습니다. 모든 셀의 값을 채워주세요.",
            easyClose = TRUE,
            footer = NULL
          ))
          return()
        }
        
        # dataset_id, dataseries_id를 기준으로 name,분석시작가능일 결합
        new_data <- new_data %>% 
          mutate(across(.cols = everything(), .fns = as.character)) %>% 
          left_join(
            data_information %>% 
              select(dataset_id, dataseries_id, name, 분석시작가능일),
            by = join_by(dataset_id, dataseries_id)
          ) %>% 
          relocate(c(name,분석시작가능일), .before = dataset_id)
        
        # 실제 컬럼명 맞춰주고 형 변환
        colnames(new_data) <- colnames(values$data)
        new_data <- new_data %>%
          mutate(
            리밸런싱날짜 = ymd(리밸런싱날짜),
            weight = as.numeric(weight),
            hedge_ratio = as.numeric(hedge_ratio),
            cost_adjust = as.numeric(cost_adjust)
          )
        
        # 최종 반영
        tryCatch({
          values$data <- bind_rows(values$data, new_data)
          showModal(modalDialog(
            title = "데이터 추가 완료",
            "클립보드에서 데이터가 성공적으로 추가되었습니다.",
            easyClose = TRUE,
            footer = NULL
          ))
        }, error = function(e) {
          showModal(modalDialog(
            title = "데이터 추가 오류",
            "데이터를 추가하는 중 오류가 발생했습니다.",
            easyClose = TRUE,
            footer = NULL
          ))
        })
      }
    })
    
    # 유니버스 테이블 (왼쪽)
    output$universe_table <- renderDT({
      filtered_data <- data_information %>%
        dplyr::select(-colname_backtest)  # 필요없는 컬럼 제외 (예시)
      
      # 검색어 입력 시 필터
      if (nchar(input$search_universe) > 0) {
        # 입력된 검색어를 "," 기준으로 분리
        search_terms <- unlist(strsplit(input$search_universe, split = ","))
        search_terms <- trimws(search_terms)  # 앞뒤 공백 제거
        
        # 순차적으로 각 키워드를 필터링
        for (term in search_terms) {
          filtered_data <- filtered_data %>%
            dplyr::filter(
              grepl(term, dataset_id, ignore.case = TRUE) |
                grepl(term, dataseries_id, ignore.case = TRUE) |
                grepl(term, name, ignore.case = TRUE) |
                grepl(term, symbol, ignore.case = TRUE) |
                grepl(term, ISIN, ignore.case = TRUE) |
                grepl(term, source, ignore.case = TRUE)
            )
        }
      }
      
      # 필터링된 결과를 출력
      selected_universe(filtered_data)
      
      datatable(
        filtered_data,
        selection = "single",
        options = list(
          dom = 'tp',
          pageLength = 5,
          scrollX = TRUE,
          scrollY = "600px",
          paging = FALSE
        )
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
            cost_adjust = 0
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
            cost_adjust = 0
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
    # 백테스트 실행 버튼
    observeEvent(input$run, {
      # (1) 중복(같은 리밸런싱날짜, Portfolio, dataset_id) 체크
      duplicates <- values$data %>%
        group_by(리밸런싱날짜, Portfolio, dataset_id,hedge_ratio) %>%
        summarise(count = n(), .groups="drop") %>%
        filter(count > 1)
      
      if (nrow(duplicates) > 0) {
        duplicate_message <- paste0(unique(duplicates$Portfolio), collapse = ", ")
        showModal(modalDialog(
          title = "중복 데이터 오류",
          HTML(paste("아래 Portfolio에 중복된 데이터셋 존재: <br>", duplicate_message)),
          easyClose = TRUE
        ))
        return()
      }
      
      # (2) 리밸런싱날짜가 분석시작가능일 이전인 경우
      data_not_available <- values$data %>% 
        filter(리밸런싱날짜 < 분석시작가능일)
      
      if (nrow(data_not_available) > 0) {
        not_available_message <- paste0(unique(data_not_available$Portfolio), collapse = ", ")
        showModal(modalDialog(
          title = "분석기간 오류",
          HTML(paste("아래 Portfolio에 리밸런싱일자가 분석시작가능일 이전인 데이터셋 존재: <br>", not_available_message)),
          easyClose = TRUE
        ))
        return()
      }
      
      # (3) weight = 0인 경우
      weight_is_zero <- values$data %>% 
        filter(weight == 0)
      
      if (nrow(weight_is_zero) > 0) {
        weight_is_zero_message <- paste0(unique(weight_is_zero$Portfolio), collapse = ", ")
        showModal(modalDialog(
          title = "분석기간 오류",
          HTML(paste("아래 Portfolio에 weight 가 0인 데이터셋 존재: <br>", weight_is_zero_message)),
          easyClose = TRUE
        ))
        return()
      }
      
      # (4) 백테스트 실행 (예시)
      #     모든 weight 합계가 1이 되도록 정규화
      data_to_use <- values$data %>%
        arrange(리밸런싱날짜) %>%
        select(-name,-분석시작가능일) %>%
        group_by(리밸런싱날짜, Portfolio) %>%
        mutate(weight = weight / sum(weight)) %>%
        ungroup()
      
      # 사용자 정의 백테스트 함수 (글로벌 영역 혹은 별도 R파일)
      # 예) res <- backtesting_for_users(data_to_use)
      
      res <- backtesting_for_users(backtest_prep_table = data_to_use,
                                   rebalancing_option = if_else(str_detect(input$rebalance_setting,"A"),"A","B"))
      
      # 결과를 메인서버의 reactiveVal에 저장
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
    
    # 모듈에서 최종적으로 편집된 테이블을 반환할 수도 있음
    return(reactive(values$data))
  })
}

