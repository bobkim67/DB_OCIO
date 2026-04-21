
# --- 2. highcharter 연동 차트 생성 ---
library(highcharter)
library(jsonlite)
library(htmltools) # 여러 위젯을 함께 렌더링
library(shiny)
library(shinyjs)
library(DT)
library(rhandsontable)
library(dplyr)
library(lubridate)
library(bslib)
library(shinyWidgets)
library(fuzzyjoin)  # regex_left_join
library(tidyr)      # pivot_wider
library(inspectdf)  # inspect_na
library(gt)
library(echarts4r)
library(colorspace)


con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
con_solution <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'solution', host = '192.168.195.55')
universe_non_derivative_table<- tbl(con_solution,"universe_non_derivative") %>% collect()
universe_derivative_table<- tbl(con_solution,"universe_derivative") %>% collect()
# 도움말 아이콘과 팝업창 정의
methods_status<- unique(universe_derivative_table$classification_method[str_detect(universe_derivative_table$classification_method,"방법")])


# 1. '방법'이 포함된 모든 분류 방법 이름 가져오기
methods_status <- universe_non_derivative_table %>%
  filter(str_detect(classification_method, "방법")) %>%
  pull(classification_method) %>%
  unique() %>%
  sort() # 방법1, 방법2, ... 순서로 정렬

# 2. 각 방법별로 하위 분류 요소들을 조회하여 리스트로 만들기
#   결과물 예시: list("방법1" = c("국내주식", "해외주식"), "방법2" = c(...))
classification_details <- lapply(methods_status, function(method) {
  universe_non_derivative_table %>%
    filter(classification_method == method, !is.na(classification)) %>%
    pull(classification) %>%
    unique() ->temp
  
  korean_items<- sort(temp[stringr::str_detect(temp, "[가-힣]")])
  non_korean_items <- sort(temp[!stringr::str_detect(temp, "[가-힣]")])
  sorted_data <- c(
    "포트폴리오",
    korean_items[korean_items!="유동성및기타"],
    non_korean_items,
    "유동성및기타"
  )
  
  sort(factor(temp, levels = sorted_data))
  # 가나다 순으로 정렬
})
names(classification_details) <- methods_status # 리스트의 각 항목에 '방법' 이름 부여

# 3. 위에서 만든 데이터 리스트를 기반으로 HTML 태그(팝업 내용) 동적 생성
popover_content_list <- lapply(seq_along(classification_details), function(i) {
  method_name <- names(classification_details)[i]
  elements <- classification_details[[i]]
  
  # tagList를 사용하여 각 섹션을 하나의 묶음으로 만듦
  tagList(
    # 제목 (예: "방법1")
    tags$h5(method_name, style = "font-weight:bold; color:#0d6efd;"),
    
    # 하위 요소 목록 (ul/li 태그로 글머리 기호 목록 생성)
    tags$ul(
      style = "padding-left: 20px; margin-bottom: 15px; column-count: 2; column-gap: 20px;",
      # lapply를 사용해 각 요소에 대해 <li> 태그를 생성
      lapply(elements, tags$li)
    ),
    
    # 마지막 항목이 아니면 구분선(<hr>) 추가
    if (i < length(classification_details)) tags$hr() else NULL
  )
})



mod_performance_attribution_ui <- function(id) {
  ns <- NS(id)
  
  div(
    useShinyjs(),
    
    # <<-- 추가: selectInput 플레이스홀더를 위한 CSS -->>
    tags$style(HTML(sprintf("
      #%s-single_port_selector_ui_left .selectize-input .item[data-value=''],
      #%s-single_port_selector_ui_right .selectize-input .item[data-value=''],
      #%s-single_port_left_analysis_type .selectize-input .item[data-value=''] {
        color: #888; /* 플레이스홀더 텍스트 색상 */
      }
    ", ns(""), ns(""), ns("")))),
    layout_columns(
      col_widths = c(2, 10),  # 좌측:우측 = 1:5로 변경
      
      # ───────── 좌측: 설정/제어 (기존 유지) ─────────
      card(
        card_header(class = "bg-primary text-white", "설정 및 실행 (Control Panel)"),
        card_body(
          padding = "10px",
          
          accordion(
            open = TRUE,
            accordion_panel(
              "Step 1: 기본 설정", icon = icon("gear"),
              tagList(
                # 필요시 기존 CSS 삽입
                tags$style(HTML(sprintf("
                  #%s-brinson_left_top_ui .dataTables_wrapper { font-size: 13px; }
                  #%s-brinson_left_top_ui table.dataTable td,
                  #%s-brinson_left_top_ui table.dataTable th { padding: 4px 8px; }
                  #%s-brinson_left_top_ui .dataTables_wrapper .caption { padding-bottom: 5px; }
                ", ns(""), ns(""), ns(""), ns("")))),
                
                div(
                  class = "analysis-mode-btn",
                  radioButtons(
                    inputId = ns("analysis_mode"), label = "포트폴리오 분석 모드", 
                    choices = c("단일" = "single", "2개 비교" = "compare"),
                    selected = "compare", inline = TRUE,  # 버튼을 한 줄로 배치
                    width = "100%"
                  )
                )
              ),
              
              dateRangeInput(
                ns("analysis_dates"), "분석 기간",
                start = floor_date(최근영업일, unit = "year"),
                end = 최근영업일, language = "ko"
              )
            )
          ),
          
          accordion(
            open = TRUE,
            accordion_panel(
              "Step 2: 포트폴리오 설정", icon = icon("folder-tree"),
              
              strong("분석할 포트폴리오"),
              fluidRow(
                # 분석할 포트폴리오와 Source: BOS를 한 행에 배치
                column(8,
                       selectInput(ns("ap_portfolio"), NULL, choices = NULL)
                ),
                column(4,
                       # Source: BOS 체크박스를 오른쪽에 배치
                       checkboxInput(ns("ap_is_bos"), "Fund", value = TRUE)
                )
              ),
              
              shinyjs::hidden(
                div(
                  id = ns("ap_non_bos_options"),
                  style = "display: flex; gap: 10px;",  # 한 줄로 보이도록 수정
                  numericInput(ns("ap_cost_bp"), "Cost (bp)", 0),
                  selectInput(ns("ap_weight_type"), "Weight Type", c("Fixed", "Drift"))
                )
              ),
              
              hr(),
              
              shinyjs::hidden(
                div(
                  id = ns("bm_block"),
                  strong("비교할 포트폴리오 (BM)"),
                  fluidRow(
                    # 비교할 포트폴리오와 Fund를 한 행에 배치
                    column(8,
                           selectInput(ns("bm_portfolio"), NULL, choices = NULL)
                    ),
                    column(4,
                           # Fund 체크박스를 오른쪽에 배치
                           checkboxInput(ns("bm_is_bos"), "Fund", value = TRUE)
                    )
                  ),
                  
                  shinyjs::hidden(
                    div(
                      id = ns("bm_non_bos_options"),
                      style = "display: flex; gap: 10px;",  # 한 줄로 보이도록 수정
                      numericInput(ns("bm_cost_bp"), "Cost (bp)", 0),
                      selectInput(ns("bm_weight_type"), "Weight Type", c("Fixed", "Drift"))
                    )
                  )
                )
              )
            )
          ),
          
          
          
          # <<-- 코드 수정: 실행 버튼과 다운로드 버튼을 함께 배치 -->>
          div(
            class = "fixed-action-btn",
            actionButton(
              ns("run_pa"), "3. 성과분석 실행",
              icon = icon("chart-line"), class = "btn-info", width = "100%"
            ),
            # shinyjs::disabled() 로 감싸서 앱 시작 시 비활성화 상태로 만듭니다.
            shinyjs::disabled(
              downloadButton(
                ns("download_excel"), "결과 다운로드",
                icon = icon("file-excel"), class = "btn-success",
                width = "100%", style = "margin-top: 8px;" # 위 버튼과 간격 추가
              )
            )
          )
        )
      ),
      
      # ───────── 오른쪽: 결과 패널 (리뉴얼) ─────────
      card(
        card_header(class = "bg-dark text-white", "결과"),
        card_body(
          
          # 레이아웃: 상단 10% / 하단 90%
          tags$style(HTML(sprintf("
            #%s_result_container { display:flex; flex-direction:column; }
            #%s_result_toolbar   { flex: 0 0 auto; min-height: 64px; }
            #%s_result_body      { flex: 1 1 auto; overflow-y: auto; }
            .toolbar-grid { display:grid; grid-template-columns: 1.2fr 0.8fr 1.2fr 1.2fr; gap:8px; align-items:end; }
            .toolbar-grid .form-group { margin-bottom:0; }
          ", ns(""), ns(""), ns("")))),
          
          div(id = ns("result_container"),
              # 상단 10%: 옵션 바
              div(id = ns("result_toolbar"),
                  div(class = "toolbar-grid",
                      # a) 하위 분석기간
                      uiOutput(ns("subperiod_ui")),
                      
                      # b) FX 분리 On/Off
                      shinyWidgets::materialSwitch(
                        inputId = ns("fx_split"),
                        label = "FX 분리", value = TRUE, status = "info", right = TRUE
                      ),
                      
                      
                      # --- 새 코드 ---
                      
                      # c) 자산군 분류방법 + 도움말 아이콘
                      div(
                        style = "display: flex; align-items: flex-end; gap: 5px;", # 가로 정렬을 위한 div
                        
                        
                        
                        
                        # 도움말 아이콘과 팝업창 정의
                        bslib::popover(
                          trigger = actionButton(
                            inputId = ns("asset_class_info_trigger"),
                            label = NULL,
                            icon = icon("circle-question"),
                            class = "btn-light btn-sm"
                          ),
                          
                          title = "자산군 분류 방법별 구성요소",
                          
                          # ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ 이 부분이 핵심입니다 ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
                          # 미리 생성해 둔 HTML 태그 리스트를 팝업 내용으로 전달합니다.
                          tags$div(
                            style = "max-width: 400px; max-height: 450px; overflow-y: auto; padding-right: 15px;",
                            
                            # Step 1에서 만든 popover_content_list 변수를 여기에 넣습니다.
                            popover_content_list
                            
                          ) # tags$div 끝
                          # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲ 수정 완료 ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
                        ) ,# bslib::popover 끝
                        # 기존 selectInput (flex-grow로 남는 공간을 모두 차지하게 함)
                        div(
                          style = "flex-grow: 1;",
                          selectInput(
                            ns("asset_class_method"), "자산군 분류",
                            choices = universe_non_derivative_table %>% 
                              filter(!(classification_method %in% c(NA,"Currency Exposure"))) %>% 
                              pull(classification_method) %>% unique(),
                            selected = "방법1"
                          )
                        ),
                      ) ,# 전체 div 끝
                      
                      # d) 분석결과(페이지) — 모드에 따라 동적
                      uiOutput(ns("analysis_view_ui"))
                  )
              ),
              
              tags$hr(style = "margin:10px 0;"),
              
              # 실행 상태 메시지
              textOutput(ns("status_text")),
              
              # 하단 90%: 페이지 컨텐츠
              div(id = ns("result_body"),
                  # Brinson 결과 (비교모드에서만)
                  # Brinson 결과 (비교모드에서만)
                  
                  # <<-- 여기부터 수정 -->>
                  tagList( # tagList로 세 개의 conditionalPanel을 묶어줍니다.
                    conditionalPanel(
                      condition = sprintf("input['%s'] == 'brinson'", ns("analysis_view")),
                      card(
                        card_header(icon("table"), "Brinson 결과"),
                        card_body(
                          fluidRow(
                            # 좌측 1/3: 두 개의 표 (위아래)
                            
                            # (변경)
                            # column(5,
                            #        div(class = "mb-3",
                            #            h5("표 1: 포트폴리오 수익률 비교"),
                            #            DT::DTOutput(ns("tbl_brinson_1"))
                            #        ),
                            #        div(class = "mb-3",
                            #            h5("표 2: 초과성과요인 분해"),
                            #            gt::gt_output(ns("tbl_brinson_3"))
                            #        )
                            # ),
                            column(5,
                                   # ⬇ 왼쪽-위 블록: 드롭다운 + 동적 표 자리
                                   div(class = "mb-3",
                                       # 제목 + 선택 박스
                                       div(style = "display:flex; align-items:flex-end; gap:8px; justify-content:space-between;",
                                           h5(textOutput(ns("brinson_left_top_title")), style = "margin:0;"),
                                           selectInput(
                                             ns("brinson_left_top_select"),
                                             label = NULL,
                                             choices = c(
                                               "기여수익률" = "tbl1",
                                               "Normalized수익률" = "tbl1_1",
                                               "순자산비중" = "tbl_weight"
                                             ),
                                             selected = "tbl1",
                                             width = "40%"
                                           )
                                       ),
                                       # 선택된 표가 렌더링될 자리
                                       uiOutput(ns("brinson_left_top_ui"))
                                   ),
                                   
                                   # ⬇ 왼쪽-아래 블록: 기존 gt_output 그대로 FIX
                                   div(class = "mb-3",
                                       h5("초과성과 요인분해"),
                                       gt::gt_output(ns("tbl_brinson_3"))
                                   )
                            ),
                            
                            
                            # 우측 2/3: 탭 패널을 사용해 다양한 그래프들 표시
                            column(7,
                                   tabsetPanel(
                                     type = "tabs",
                                     tabPanel("포트폴리오 수익률 비교", uiOutput(ns("brinson_charts_ui"),height = "500px")),
                                     tabPanel("포트폴리오 비중 비교", uiOutput(ns("brinson_weight_charts_ui"),height = "500px")),
                                     tabPanel("초과성과 요인분해", uiOutput(ns("brinson_excess_charts_ui"),height = "500px"))
                                     
                                   )
                                   
                            )
                          )
                        )
                      ))
                    ,
                    
                    # 개별포트 분석 (공통)
                    # conditionalPanel( ... input ... == 'single_port' ... ) 내부를 아래 코드로 교체하세요.
                    
                    conditionalPanel(
                      condition = sprintf("input['%s'] == 'single_port'", ns("analysis_view")),
                      card(
                        card_header(icon("chart-line"), "개별포트 분석"),
                        card_body(
                          fluidRow(
                            # ────────── 좌측 영역 ──────────
                            column(6,
                                   div(style = "display: flex; align-items: flex-end; gap: 8px; margin-bottom: 10px;",
                                       # [수정] 'compare' 모드일 때만 포트폴리오 선택 UI 표시
                                       conditionalPanel(
                                         condition = sprintf("input['%s'] == 'compare'", ns("analysis_mode")),
                                         div(style = "flex: 1;",
                                             selectInput(ns("selected_single_portfolio_left"), NULL, choices = NULL)
                                         )
                                       ),
                                       # 분석 종류
                                       div(style = "flex: 1.2;",
                                           selectInput(ns("single_port_left_analysis_type"), NULL,
                                                       choices = c("포트폴리오 요약" = "portfolio_summary",
                                                                   "수익률 분석" = "return_analysis",
                                                                   "비중 분석" = "weight_analysis",
                                                                   "성과 지표" = "performance_metrics",
                                                                   "리스크 지표" = "risk_metrics"))
                                       ),
                                       # 표/그래프 선택
                                       div(style = "flex: 0.8;",
                                           shinyWidgets::radioGroupButtons(ns("single_port_left_display_type"), NULL,
                                                                           choiceNames = list(icon("table-list"), icon("chart-pie")),
                                                                           choiceValues = list("table", "plot"),
                                                                           justified = TRUE, status = "primary", size = "sm"))
                                   ),
                                   uiOutput(ns("single_port_left_output"))
                            ),
                            # ────────── 우측 영역 ──────────
                            column(6,
                                   div(style = "display: flex; align-items: flex-end; gap: 8px; margin-bottom: 10px;",
                                       # [수정] 'compare' 모드일 때만 포트폴리오 선택 UI 표시
                                       conditionalPanel(
                                         condition = sprintf("input['%s'] == 'compare'", ns("analysis_mode")),
                                         div(style = "flex: 1;",
                                             selectInput(ns("selected_single_portfolio_right"), NULL, choices = NULL)
                                         )
                                       ),
                                       # 분석 종류
                                       div(style = "flex: 1.2;",
                                           selectInput(ns("single_port_right_analysis_type"), NULL,
                                                       choices = c("포트폴리오 요약" = "portfolio_summary",
                                                                   "수익률 분석" = "return_analysis",
                                                                   "비중 분석" = "weight_analysis",
                                                                   "성과 지표" = "performance_metrics",
                                                                   "리스크 지표" = "risk_metrics"))
                                       ),
                                       # 표/그래프 선택
                                       div(style = "flex: 0.8;",
                                           shinyWidgets::radioGroupButtons(ns("single_port_right_display_type"), NULL,
                                                                           choiceNames = list(icon("table-list"), icon("chart-pie")),
                                                                           choiceValues = list("table", "plot"),
                                                                           justified = TRUE, status = "primary", size = "sm"))
                                   ),
                                   uiOutput(ns("single_port_right_output"))
                            )
                          )
                        )
                      )
                    ),
                    
                    # mod_performance_attribution_ui 내 mapping conditionalPanel 부분을 아래로 업데이트
                    conditionalPanel(
                      condition = sprintf("input['%s'] == 'mapping'", ns("analysis_view")),
                      card(
                        card_header(icon("sitemap"), "매핑현황"),
                        card_body(
                          style = "overflow-y: auto;", # 이 줄 추가!
                          DT::DTOutput(ns("tbl_mapping"))
                          
                        )
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


# 모듈 Server

mod_performance_attribution_server <- function(id, backtest_results) {
  moduleServer(id, function(input, output, session) {
    ns <- session$ns
    validate <- shiny::validate
    need     <- shiny::need
    
    # 상태 메시지
    status_message <- reactiveVal("좌측 패널에서 옵션을 선택하고 '성과분석 실행' 버튼을 눌러주세요.")
    output$status_text <- renderText({ status_message() })
    
    # 분석 결과 보관
    analysis_results <- reactiveValues(ap = NULL, bm = NULL)
    
    # NEW: 실행 여부 + 좌측 패널 스냅샷
    has_run    <- reactiveVal(FALSE)
    run_params <- reactiveVal(NULL)
    run_id <- reactiveVal(0L)
    # 모드(라이브/스냅샷)
    is_compare_live <- reactive({ identical(input$analysis_mode, "compare") })
    is_compare_run  <- reactive({
      rp <- run_params()
      !is.null(rp) && identical(rp$analysis_mode, "compare")
    })
    
    # 포트폴리오 셀렉트 채우기 (초기화)
    observe({
      req(backtest_results())
      portfolio_list_df <- try(backtest_results()[[1]], silent = TRUE)
      req(!inherits(portfolio_list_df, "try-error"))
      portfolio_list <- unique(portfolio_list_df$Portfolio)
      updateSelectInput(session, "ap_portfolio", choices = portfolio_list, selected = portfolio_list[1])
      if (length(unique(portfolio_list)) > 1) {
        updateSelectInput(session, "bm_portfolio", choices = portfolio_list, selected = portfolio_list[2])
      }
    })
    
    # BOS 토글에 따라 비BOS 옵션 노출
    observeEvent(input$ap_is_bos, {
      shinyjs::toggle(id = "ap_non_bos_options", anim = TRUE, condition = !input$ap_is_bos)
    })
    observeEvent(input$bm_is_bos, {
      shinyjs::toggle(id = "bm_non_bos_options", anim = TRUE, condition = !input$bm_is_bos)
    })
    
    # BM 블럭 노출은 "라이브" 모드 기준 (UI 편의)
    observeEvent(input$analysis_mode, {
      shinyjs::toggle(id = "bm_block", anim = TRUE, condition = is_compare_live())
    }, ignoreInit = FALSE)
    
    output$subperiod_ui <- renderUI({
      # analysis_dates를 읽되, 반응성 의존은 제거
      ad <- isolate(input$analysis_dates)
      dateRangeInput(
        ns("sub_period"), "하위 분석기간",
        start = if (!is.null(ad)) ad[1] else Sys.Date() - 30,
        end   = if (!is.null(ad)) ad[2] else Sys.Date(),
        language = "ko"
      )
    })
    
    
    # NEW: 분석결과(페이지) 선택지는 "마지막 실행 모드" 기준으로 노출
    output$analysis_view_ui <- renderUI({
      if (!has_run()) {
        choices <- c("개별포트 분석" = "single_port", "매핑현황" = "mapping")
        sel <- "single_port"
      } else if (is_compare_run()) {
        choices <- c("Brinson result" = "brinson", "개별포트 분석" = "single_port", "매핑현황" = "mapping")
        sel <- "brinson"
      } else {
        choices <- c("개별포트 분석" = "single_port", "매핑현황" = "mapping")
        sel <- "single_port"
      }
      selectInput(ns("analysis_view"), "분석결과", choices = choices, selected = sel)
    })
    
    # NEW: 왼쪽 패널이 바뀌어도 결과는 유지(메시지만 안내)
    observeEvent(
      list(input$analysis_mode, input$analysis_dates, input$ap_portfolio, input$ap_is_bos,
           input$ap_cost_bp, input$ap_weight_type, input$bm_portfolio, input$bm_is_bos,
           input$bm_cost_bp, input$bm_weight_type),
      {
        if (has_run()) {
          status_message("설정이 변경되었습니다. 현재 화면은 '마지막 실행' 기준입니다. '성과분석 실행'을 눌러 반영하세요.")
        }
      },
      ignoreInit = TRUE
    )
    
    # ───────── 실행 버튼: 좌측 패널 스냅샷 → 무거운 계산 → 공개 ─────────
    observeEvent(input$run_pa, {
      
      
      # ───────── [추가] 실행 전 유효성 검사 ─────────
      # '2개 비교' 모드에서 두 포트폴리오가 동일한지 확인합니다.
      if (identical(input$analysis_mode, "compare")) {
        # req()를 사용해 두 입력값이 모두 존재하는지(NULL이 아닌지) 확인합니다.
        req(input$ap_portfolio, input$bm_portfolio)
        
        if (input$ap_portfolio == input$bm_portfolio) {
          # 동일하다면, 사용자에게 알림을 표시하고 여기서 실행을 중단합니다.
          showNotification(
            "오류: 같은 포트폴리오를 비교 대상으로 설정할 수 없습니다.",
            type = "error", # 'error' 타입으로 더 강조
            duration = 7    # 메시지를 7초간 표시
          )
          return() # 이 return()이 핵심입니다. 여기서 함수 실행을 즉시 종료합니다.
        }
      }
      
      status_message("분석을 실행 중입니다...")
      has_run(FALSE)   # 계산 중엔 결과 잠깐 잠금
      shinyjs::disable("download_excel") # <<-- 코드 추가: 계산 중 다운로드 버튼 비활성화
      
      # 좌측 패널 스냅샷 만들기 전/후 아무 위치 가능
      ad <- isolate(input$analysis_dates)
      if (!is.null(ad) && length(ad) == 2 && !any(is.na(ad))) {
        updateDateRangeInput(session, "sub_period", start = ad[1], end = ad[2])
      }
      # 1) 좌측 패널 스냅샷
      rp <- list(
        analysis_mode   = input$analysis_mode,
        analysis_dates  = input$analysis_dates,
        ap_portfolio    = input$ap_portfolio,
        ap_is_bos       = isTRUE(input$ap_is_bos),
        ap_cost_bp      = input$ap_cost_bp,
        ap_weight_type  = input$ap_weight_type,
        bm_portfolio    = if (is_compare_live()) input$bm_portfolio else NULL,
        bm_is_bos       = if (is_compare_live()) isTRUE(input$bm_is_bos) else NULL,
        bm_cost_bp      = input$bm_cost_bp,
        bm_weight_type  = input$bm_weight_type
      )
      run_params(rp)
      
      # 2) 무거운 계산: 오직 스냅샷 기반으로 수행
      analysis_results$ap <- NULL
      analysis_results$bm <- NULL
      req(backtest_results(), rp$ap_portfolio, rp$analysis_dates)
      
      if (isTRUE(rp$ap_is_bos)) {
        fund_code_ap <- backtest_results()[[1]] %>%
          dplyr::filter(Portfolio == rp$ap_portfolio) %>% distinct() %>% dplyr::pull(dataset_id)
        analysis_results$ap <- PA_from_MOS(from = rp$analysis_dates[1], to = rp$analysis_dates[2], fund_cd = fund_code_ap)
      } else {
        analysis_results$ap <- BM_preprocessing(res = backtest_results(),
                                                weight_type = rp$ap_weight_type,
                                                Portfolio_name = rp$ap_portfolio,
                                                cost_bp = rp$ap_cost_bp)
      }
      
      if (identical(rp$analysis_mode, "compare")) {
        req(rp$bm_portfolio)
        if (isTRUE(rp$bm_is_bos)) {
          fund_code_bm <- backtest_results()[[1]] %>%
            dplyr::filter(Portfolio == rp$bm_portfolio) %>% distinct() %>% dplyr::pull(dataset_id)
          analysis_results$bm <- PA_from_MOS(from = rp$analysis_dates[1], to = rp$analysis_dates[2], fund_cd = fund_code_bm)
        } else {
          analysis_results$bm <- BM_preprocessing(res = backtest_results(),
                                                  weight_type = rp$bm_weight_type,
                                                  Portfolio_name = rp$bm_portfolio,
                                                  cost_bp = rp$bm_cost_bp)
        }
      } else {
        analysis_results$bm <- NULL
      }
      
      # 3) 완료
      has_run(TRUE)
      shinyjs::enable("download_excel") # <<-- 코드 추가: 계산 완료 후 다운로드 버튼 활성화
      status_message("분석 완료! 상단 옵션으로 결과 페이지를 선택/조정하세요.")
      showNotification("성과분석 실행이 완료되었습니다.", type = "message")
      # << 여기 추가: 이번 실행을 식별하는 트리거 증가 >>
      run_id(isolate(run_id()) + 1L)
      
    })
    
    
    # ───────── 매핑현황 계산 (버튼 이후에만) ─────────
    mapping_calc <- reactive({
      req(has_run(), run_id())          # ← 이 줄로 이번 실행이 끝났을 때만 재계산
      rp <- isolate(run_params())       # ← 이번 실행의 스냅샷만 사용 (중간에 좌측 변경 무시)
      
      
      AP_roll_portfolio <- analysis_results$ap
      BM_roll_portfolio <- analysis_results$bm
      
      ap_map <- AP_roll_portfolio$check_mapping_classification
      bm_map <- if (is_compare_run() && !is.null(BM_roll_portfolio)) BM_roll_portfolio$check_mapping_classification else NULL
      
      if ((isTRUE(rp$ap_is_bos) + isTRUE(rp$bm_is_bos)) == 0) {
        temp <- dplyr::bind_rows(if (!is.null(ap_map)) ap_map, if (!is.null(bm_map)) bm_map)
        validate(need(nrow(temp) > 0, "매핑 대상 데이터가 없습니다."))
        validate(need(exists("universe_derivative_table", inherits = TRUE), "universe_derivative_table이 환경에 없습니다."))
        validate(need(exists("universe_non_derivative_table", inherits = TRUE), "universe_non_derivative_table이 환경에 없습니다."))
        
        mapped_status <- bind_rows(
          universe_non_derivative_table %>%
            dplyr::filter((primary_source_id %in% temp$dataset_id[!is.na(temp$dataset_id)])) %>%
            dplyr::filter(!is.na(classification_method)) %>% dplyr::distinct()
        ) %>%
          tidyr::pivot_wider(id_cols = c(name, primary_source_id),
                             names_from = classification_method,
                             values_from = classification) %>%
          dplyr::rename(노출통화 = `Currency Exposure`)
        
        mapped_status <- bind_rows(
          mapped_status,
          temp %>%
            dplyr::filter(!(dataset_id %in% mapped_status$primary_source_id[!is.na(mapped_status$primary_source_id)])) %>%
            dplyr::select(name = symbol, 노출통화)
        )
      } else {
        temp <- dplyr::bind_rows(if (!is.null(ap_map)) ap_map, if (!is.null(bm_map)) bm_map) %>% 
          # dplyr::mutate(dataset_id = if ("dataset_id" %in% names(.)) .data[["dataset_id"]] else rep(NA, nrow(.))) 
          dplyr::mutate(dataset_id = as.character(if ("dataset_id" %in% names(.)) .data[["dataset_id"]] else rep(NA, nrow(.))) ) %>% 
          distinct()
        validate(need(nrow(temp) > 0, "매핑 대상 데이터가 없습니다."))
        validate(need(exists("universe_derivative_table", inherits = TRUE), "universe_derivative_table이 환경에 없습니다."))
        validate(need(exists("universe_non_derivative_table", inherits = TRUE), "universe_non_derivative_table이 환경에 없습니다."))
        
        mapped_status <- dplyr::bind_rows(
          temp %>%
            fuzzyjoin::regex_left_join(universe_derivative_table, by = c("ITEM_NM" = "keyword")) %>%
            dplyr::filter(!is.na(keyword)) %>%
            dplyr::filter(asset_gb.x == asset_gb.y) %>%
            dplyr::mutate(dataset_id = if ("dataset_id" %in% names(.)) .data[["dataset_id"]] else rep(NA, nrow(.))) %>% 
            dplyr::select(
              ISIN = sec_id, name = ITEM_NM, 노출통화,
              asset_gb = asset_gb.x, matched_keyword = keyword,
              classification_method, classification,
              primary_source_id =dataset_id
            ),
          universe_non_derivative_table %>%
            dplyr::filter(
              (ISIN %in% (temp$sec_id[!is.na(temp$sec_id)])) |
                (primary_source_id %in% temp$dataset_id[!is.na(temp$dataset_id)])
            ) %>%
            dplyr::filter(!is.na(classification_method)) %>%
            dplyr::distinct()
        ) %>%
          tidyr::pivot_wider(id_cols = c(name, ISIN, primary_source_id, asset_gb),
                             names_from = classification_method,
                             values_from = classification) %>%
          dplyr::rename(노출통화 = `Currency Exposure`)
        
        mapped_status <- bind_rows(
          mapped_status,
          temp %>% dplyr::filter(
            !(sec_id %in% mapped_status$ISIN[!is.na(mapped_status$ISIN)]) &
              !(dataset_id %in% mapped_status$primary_source_id[!is.na(mapped_status$primary_source_id)])
          ) %>%
            dplyr::select(ISIN = sec_id, name = ITEM_NM, 노출통화, asset_gb)
        )
      }
      
      # 사용 가능 분류방법 (결측 0% 인 컬럼만)
      available <- tryCatch({
        if ((isTRUE(rp$ap_is_bos) + isTRUE(rp$bm_is_bos)) == 0) {
          cols <- mapped_status %>% dplyr::select(tidyselect::contains("방법"))
        }else{
          cols <- mapped_status %>% dplyr::filter(!(asset_gb %in% c("유동","기타비용"))) %>%
            dplyr::select(tidyselect::contains("방법"))
        }
        
        
        if (ncol(cols) == 0) character(0) else
          inspectdf::inspect_na(cols) %>%
          #dplyr::filter(pcnt == 0) %>%
          dplyr::pull(col_name)
      }, error = function(e) character(0))
      
      # 맨 마지막 list()를 반환하기 직전에 아래 코드 삽입
      cat("\n--- Debugging mapping_calc ---\n")
      if (exists("mapped_status")) {
        cat("Object 'mapped_status' exists.\n")
        cat("Class:", class(mapped_status), "\n")
        cat("Dimensions:", dim(mapped_status), "\n")
        print(head(mapped_status, 3)) # 데이터 앞부분 3줄 출력
      } else {
        cat("Object 'mapped_status' does NOT exist.\n")
      }
      cat("----------------------------\n\n")
      
      list(mapped_status = mapped_status, available = available)
    })
    
    # 분류방법 드롭다운을 '가능한 방법'으로만 제한 (버튼 이후에만 동작)
    observeEvent(mapping_calc(), {
      av <- mapping_calc()$available
      prev <- isolate(input$asset_class_method)
      if (length(av) == 0) {
        updateSelectInput(session, "asset_class_method", choices = character(0), selected = NULL)
      } else if (!is.null(prev) && prev %in% av) {
        updateSelectInput(session, "asset_class_method", choices = av, selected = prev)
      } else {
        updateSelectInput(session, "asset_class_method", choices = av, selected = av[1])
      }
    }, ignoreInit = TRUE)
    
    
    # ───────── Brinson / 포트분석 데이터 (버튼 이후에만) ─────────
    # eventReactive를 사용하여 계산 시점을 명확히 제어합니다.
    # '실행' 버튼을 누르거나(run_id 변경), 상단 옵션이 변경될 때만 재계산됩니다.
    brinson_data <- eventReactive(list(run_id(), input$sub_period, input$asset_class_method, input$fx_split), {
      # req 조건은 동일하게 유지
      req(has_run(), is_compare_run())
      
      # tryCatch로 감싸서 예외 상황에 대한 추가적인 안정성을 확보합니다.
      tryCatch({
        rp <- isolate(run_params())
        
        # 상단 옵션은 즉시 반영
        from_to <- if (!is.null(input$sub_period) && length(input$sub_period) == 2)
          input$sub_period else rp$analysis_dates
        
        mc     <- mapping_calc()
        req(mc, mc$mapped_status, input$asset_class_method) 
        map_df <- mc$mapped_status
        
        # 선택된 자산군 분류가 현재 유효한지 확인
        validate(
          need(input$asset_class_method %in% mc$available, 
               "선택된 자산군 분류 방법이 유효하지 않습니다. 잠시 후 다시 시도됩니다.")
        )
        
        
        AP_roll_portfolio_res <- Portfolio_analysis(
          analysis_results$ap,
          from = from_to[1], to = from_to[2],
          mapping_method = input$asset_class_method,
          mapped_status  = map_df,
          FX_split       = input$fx_split
        )
        
        BM_roll_portfolio_res <- Portfolio_analysis(
          analysis_results$bm,
          from = from_to[1], to = from_to[2],
          mapping_method = input$asset_class_method,
          mapped_status  = map_df,
          FX_split       = input$fx_split
        )
        # 필요 시 General_PA도 호출 (남겨둠)
        Brinson_res <- General_PA(AP_roll_portfolio = analysis_results$ap,
                                  BM_roll_portfolio = analysis_results$bm,
                                  AP_roll_portfolio_res = AP_roll_portfolio_res,
                                  BM_roll_portfolio_res = BM_roll_portfolio_res,
                                  from = from_to[1], to = from_to[2],
                                  mapped_status = map_df,
                                  mapping_method = input$asset_class_method,
                                  FX_split = input$fx_split)
        
        list(
          tbl_1 = brinson_tbl_return_summary(
            AP_roll_portfolio_res = AP_roll_portfolio_res,
            BM_roll_portfolio_res = BM_roll_portfolio_res,
            Port_A_name = rp$ap_portfolio,
            Port_B_name = rp$bm_portfolio,
            mapping_method = input$asset_class_method,func = "기여",
            FX_split=input$fx_split
          ),
          tbl_1_1 = brinson_tbl_return_summary(
            AP_roll_portfolio_res = AP_roll_portfolio_res,
            BM_roll_portfolio_res = BM_roll_portfolio_res,
            Port_A_name = rp$ap_portfolio,
            Port_B_name = rp$bm_portfolio,
            mapping_method = input$asset_class_method,func = "normalized",
            FX_split=input$fx_split
          ),
          tbl_2 = brinson_tbl_weight_summary(
            AP_roll_portfolio_res = AP_roll_portfolio_res,
            BM_roll_portfolio_res = BM_roll_portfolio_res,
            Port_A_name = rp$ap_portfolio,
            Port_B_name = rp$bm_portfolio,
            mapping_method = input$asset_class_method,
            FX_split = input$fx_split
          ),
          tbl_3 = Brinson_result_table(Brinson_res = Brinson_res,
                                       Port_A_name = rp$ap_portfolio,
                                       Port_B_name = rp$bm_portfolio),
          plot_1 = brinson_plot_port_return(
            AP_roll_portfolio_res = AP_roll_portfolio_res,
            BM_roll_portfolio_res = BM_roll_portfolio_res,
            Port_A_name = rp$ap_portfolio,
            Port_B_name = rp$bm_portfolio,
            mapping_method = input$asset_class_method
          ),
          plot_2 = brinson_plot_port_weight(
            AP_roll_portfolio_res = AP_roll_portfolio_res,
            BM_roll_portfolio_res = BM_roll_portfolio_res,
            Port_A_name = rp$ap_portfolio,
            Port_B_name = rp$bm_portfolio,
            mapping_method = input$asset_class_method
          ),
          plot_3 = brinson_plot_port_excess_factor(Brinson_res = Brinson_res,
                                                   mapping_method = input$asset_class_method)
        )
      }, error = function(e) {
        # 오류 발생 시 사용자에게 메시지를 보이지 않고 NULL을 반환
        cat("brinson_data 계산 중 일시적 오류:", e$message, "\n")
        return(NULL)
      })
      
    }, ignoreNULL = FALSE) # 앱 시작 시 초기 실행을 위해 ignoreNULL = FALSE 설정
    # ───────── 출력(렌더) — 실행 후만 보여줌, 상단 옵션 즉시 반영 ─────────
    
    # output-tbl_brinson_1 ----------------------------------------------------
    
    
    output$tbl_brinson_1 <- DT::renderDT({
      req(has_run(), is_compare_run(), input$analysis_view == "brinson")
      from_to <- if (!is.null(input$sub_period) && length(input$sub_period) == 2){
        input$sub_period 
      }else{ run_params()$analysis_dates } # rp 대신 run_params() 사용
      
      table_data <- brinson_data()$tbl_1
      caption_tag <- htmltools::tags$caption(
        style = "caption-side: top; text-align: left; font-weight: 600;",
        sprintf("분석 기간 (%s)", paste(from_to, collapse = " ~ "))
      )
      
      # 실제로 그릴 데이터프레임 (보일 열만)
      df <- table_data %>%
        #dplyr::select(-c("분석시작일","분석종료일")) %>%
        dplyr::select(구분, dplyr::everything()) %>%
        as.data.frame(check.names = FALSE)   # ← 하이픈 등 특수문자 보존
      
      # 포맷 대상: '구분'을 제외한 모든 열의 인덱스
      cols_fmt <- setdiff(seq_along(df), which(names(df) %in% c("구분")))
      
      DT::datatable(
        df,
        options = list(
          dom = 't',
          paging = FALSE,
          info = FALSE,
          lengthChange = FALSE,
          ordering = TRUE,
          scrollX = TRUE
        ),
        rownames = FALSE,
        caption = caption_tag
      ) %>%
        DT::formatPercentage(columns = cols_fmt, digits = 3) %>%
        DT::formatStyle(columns = cols_fmt, color = styleInterval(0, c("blue","red"))) %>%
        DT::formatStyle('구분', target='row',
                        fontWeight = DT::styleEqual('포트폴리오','bold'))
    })
    
    output$tbl_brinson_1_1 <- DT::renderDT({
      req(has_run(), is_compare_run(), input$analysis_view == "brinson")
      from_to <- if (!is.null(input$sub_period) && length(input$sub_period) == 2){
        input$sub_period 
      }else{ run_params()$analysis_dates }
      table_data <- brinson_data()$tbl_1_1
      caption_tag <- htmltools::tags$caption(
        style = "caption-side: top; text-align: left; font-weight: 600;",
        sprintf("분석 기간 (%s)", paste(from_to, collapse = " ~ "))
      )
      
      # 실제로 그릴 데이터프레임 (보일 열만)
      df <- table_data %>%
        #dplyr::select(-c("분석시작일","분석종료일")) %>%
        dplyr::select(구분, dplyr::everything()) %>%
        as.data.frame(check.names = FALSE)   # ← 하이픈 등 특수문자 보존
      
      # 포맷 대상: '구분'을 제외한 모든 열의 인덱스
      cols_fmt <- setdiff(seq_along(df), which(names(df) %in% c("구분")))
      
      DT::datatable(
        df,
        options = list(
          dom = 't',
          paging = FALSE,
          info = FALSE,
          lengthChange = FALSE,
          ordering = TRUE,
          scrollX = TRUE
        ),
        rownames = FALSE,
        caption = caption_tag
      ) %>%
        DT::formatPercentage(columns = cols_fmt, digits = 3) %>%
        DT::formatStyle(columns = cols_fmt, color = styleInterval(0, c("blue","red"))) %>%
        DT::formatStyle('구분', target='row',
                        fontWeight = DT::styleEqual('포트폴리오','bold'))
    })
    
    
    output$tbl_brinson_2 <- DT::renderDT({
      req(has_run(), is_compare_run(), input$analysis_view == "brinson")
      
      table_data <- brinson_data()$tbl_2
      caption_tag <- htmltools::tags$caption(
        style = "caption-side: top; text-align: left; font-weight: 600;",
        sprintf("기준일자 (%s)", table_data$기준일자[1])
      )
      
      df <- table_data %>%
        dplyr::select(-c("기준일자")) %>%
        dplyr::select(구분, dplyr::everything()) %>%
        as.data.frame(check.names = FALSE)
      
      cols_fmt <- setdiff(seq_along(df), which(names(df) %in% c("구분")))
      
      DT::datatable(
        df,
        options = list(
          dom = 't',
          paging = FALSE,
          info = FALSE,
          lengthChange = FALSE,
          ordering = TRUE,
          scrollX = TRUE
        ),
        rownames = FALSE,
        caption = caption_tag
      ) %>%
        DT::formatPercentage(columns = cols_fmt, digits = 3) %>%
        DT::formatStyle(columns = cols_fmt, color = styleInterval(0, c("blue","red")))
    })
    
    
    # 왼쪽-위 제목
    output$brinson_left_top_title <- renderText({
      if (identical(input$brinson_left_top_select, "tbl1")) {
        "포트폴리오 기여수익률 비교"
      } else if (identical(input$brinson_left_top_select, "tbl1_1")) {
        "포트폴리오 Normalized수익률 비교"
      } else {
        "포트폴리오 순자산비중 비교"
      }
    })
    
    # 왼쪽-위 표 자리 스위칭
    output$brinson_left_top_ui <- renderUI({
      req(has_run(), is_compare_run(), input$analysis_view == "brinson")
      if (identical(input$brinson_left_top_select, "tbl1")) {
        DT::DTOutput(ns("tbl_brinson_1"))
      } else if(identical(input$brinson_left_top_select, "tbl1_1")) {
        DT::DTOutput(ns("tbl_brinson_1_1"))
      } else{
        DT::DTOutput(ns("tbl_brinson_2"))
      }
    })
    
    
    output$tbl_brinson_3 <- gt::render_gt({
      req(has_run(), is_compare_run(), input$analysis_view == "brinson")
      x <- brinson_data()$tbl_3
      
      soften_gt <- function(gt_tbl) {
        gt_tbl %>%
          gt::tab_options(table.font.size = gt::px(13)) %>%   # 12px → 14px (가독성 확보)
          gt::opt_vertical_padding(scale = 0.8) %>%           # 디폴트 대비 20%만 축소
          gt::opt_horizontal_padding(scale = 0.8)             # 가로 패딩도 20%만 축소
      }
      
      # gt 객체 내부의 원본 데이터프레임을 사용하도록 수정
      if (is.list(x) && !is.null(x$DF) && is.data.frame(x$DF)) {
        return(soften_gt(x$HTML))
      }
      if (is.list(x) && !is.null(x$HTML) && inherits(x$HTML, "gt_tbl")) return(soften_gt(x$HTML))
      if (inherits(x, "gt_tbl")) return(soften_gt(x))
      if (is.data.frame(x)) return(gt::gt(x) |> soften_gt())
      gt::gt(data.frame(메시지 = "표 2를 렌더링할 수 없습니다: 지원하지 않는 형식입니다."))
    })
    
    
    
    # output-plot1 ------------------------------------------------------------
    
    # ───────── (신규) 동적 차트 UI 생성 로직 ─────────
    output$brinson_charts_ui <- renderUI({
      req(brinson_data())
      plot_data <- brinson_data()$plot_1
      if(input$fx_split == TRUE){
        plot_data
      }else{
        plot_data<- plot_data %>% 
          filter(자산군 != "FX")
      }
      validate(need(plot_data, "차트 데이터를 불러오는 중입니다..."),
               need(nrow(plot_data) > 0, "표시할 차트 데이터가 없습니다."))
      
      # 자산군 목록을 가져옵니다.
      asset_classes <- sort(unique(plot_data$자산군))
      
      # 각 자산군에 대해 tabPanel을 생성합니다.
      # lapply를 사용하여 각 자산군별로 탭 패널 UI 구성요소를 리스트로 만듭니다.
      chart_tabs <- lapply(seq_along(asset_classes), function(i) {
        asset_name <- asset_classes[i]
        # echarts4rOutput의 ID를 동적으로 생성합니다.
        tabPanel(
          title = as.character(asset_name),
          echarts4rOutput(ns(paste0("brinson_chart_asset_", i)), height = "600px")
        )
      })
      
      # 생성된 탭 패널 리스트를 tabsetPanel에 삽입합니다.
      do.call(tabsetPanel, c(id = ns("brinson_dynamic_tabs"), chart_tabs))
    })
    # output-plot2 ------------------------------------------------------------    
    # ───────── (신규) 동적 차트 UI 생성 로직 ─────────
    output$brinson_weight_charts_ui <- renderUI({
      req(brinson_data())
      plot_data <- brinson_data()$plot_2
      if(input$fx_split == TRUE){
        plot_data
      }else{
        plot_data<- plot_data %>% 
          filter(자산군 != "FX")
      }
      validate(need(plot_data, "차트 데이터를 불러오는 중입니다..."),
               need(nrow(plot_data) > 0, "표시할 차트 데이터가 없습니다."))
      
      # 자산군 목록을 가져옵니다.
      asset_classes <- sort(unique(plot_data$자산군))
      
      # 각 자산군에 대해 tabPanel을 생성합니다.
      # lapply를 사용하여 각 자산군별로 탭 패널 UI 구성요소를 리스트로 만듭니다.
      chart_tabs <- lapply(seq_along(asset_classes), function(i) {
        asset_name <- asset_classes[i]
        # echarts4rOutput의 ID를 동적으로 생성합니다.
        tabPanel(
          title = as.character(asset_name),
          echarts4rOutput(ns(paste0("brinson_weight_chart_asset_", i)), height = "600px")
        )
      })
      
      # 생성된 탭 패널 리스트를 tabsetPanel에 삽입합니다.
      do.call(tabsetPanel, c(id = ns("brinson_weight_dynamic_tabs"), chart_tabs))
    })
    # output-plot3 ------------------------------------------------------------
    output$brinson_excess_charts_ui <- renderUI({
      req(has_run(), is_compare_run(), input$analysis_view == "brinson")
      
      tabsetPanel(
        id   = ns("excess_tabs"),
        type = "tabs",
        tabPanel("자산군별",
                 echarts4rOutput(ns("excess_by_asset_chart"),  height = "600px")),
        tabPanel("요인별",
                 echarts4rOutput(ns("excess_by_factor_chart"), height = "600px"))
      )
    })
    # ───────── (신규) 동적 차트 렌더링 로직 ─────────
    # brinson_data가 업데이트 될 때마다 차트를 다시 그립니다.
    observeEvent(brinson_data(), {
      b_data <- brinson_data()
      req(b_data, b_data$plot_1, nrow(b_data$plot_1) > 0)
      
      plot_data <- b_data$plot_1
      asset_classes <- sort(unique(plot_data$자산군))
      
      # for 루프를 사용하여 각 output 슬롯에 차트를 할당합니다.
      for (i in seq_along(asset_classes)) {
        # local()을 사용하여 각 루프 반복의 변수(i, current_asset)를 "고정"시킵니다.
        # 이렇게 하지 않으면 모든 차트가 마지막 자산군으로 그려지는 문제가 발생합니다.
        local({
          my_i <- i
          current_asset <- asset_classes[my_i]
          output_id <- paste0("brinson_chart_asset_", my_i)
          
          output[[output_id]] <- renderEcharts4r({
            plot_data %>%
              filter(자산군 == current_asset) %>%
              brinson_plot_port_return_echarts4r()
          })
        })
      }
    })    
    
    observeEvent(brinson_data(), {
      b_data <- brinson_data()
      req(b_data, b_data$plot_2, nrow(b_data$plot_2) > 0)
      
      plot_data <- b_data$plot_2
      asset_classes <- sort(unique(plot_data$자산군))
      
      # for 루프를 사용하여 각 output 슬롯에 차트를 할당합니다.
      for (i in seq_along(asset_classes)) {
        # local()을 사용하여 각 루프 반복의 변수(i, current_asset)를 "고정"시킵니다.
        # 이렇게 하지 않으면 모든 차트가 마지막 자산군으로 그려지는 문제가 발생합니다.
        local({
          my_i <- i
          current_asset <- asset_classes[my_i]
          output_id <- paste0("brinson_weight_chart_asset_", my_i)
          
          output[[output_id]] <- renderEcharts4r({
            plot_data %>%
              filter(자산군 == current_asset) %>%
              brinson_plot_port_weight_echarts4r()
          })
        })
      }
    }) 
    
    
    observeEvent(brinson_data(), {
      req(has_run(), is_compare_run())
      # 실행 시점의 파라미터(포트폴리오 이름)를 가져옵니다.
      rp <- isolate(run_params())
      pd <- brinson_data()$plot_3
      
      validate(
        need(!is.null(pd) && is.list(pd), "plot_3 데이터가 없습니다."),
        need(!is.null(pd[["자산군별"]]),   "'자산군별' 데이터가 없습니다."),
        need(!is.null(pd[["요인별"]]),     "'요인별' 데이터가 없습니다.")
      )
      
      # 자산군별 라인차트
      output$excess_by_asset_chart <- renderEcharts4r({
        brinson_plot_port_excess_자산군별_echarts4r(pd[["자산군별"]],
                                                ap_col_name = rp$ap_portfolio,
                                                bm_col_name = rp$bm_portfolio)
      })
      
      # 요인별 라인차트
      output$excess_by_factor_chart <- renderEcharts4r({
        brinson_plot_port_excess_요인별_echarts4r(pd[["요인별"]],
                                               ap_col_name = rp$ap_portfolio,
                                               bm_col_name = rp$bm_portfolio)
      })
    })
    
    
    #  SINGLE PORT ANALYSIS SECTION ----
    
    
    # Step 1: 데이터 준비 (기존 코드와 동일, 실제 함수명으로 교체 필요)
    # Step 1: 데이터 준비 (문제가 의심되는 함수를 안전한 더미 데이터로 교체)
    single_port_data <- eventReactive(list(run_id(),input$analysis_view,  input$sub_period, input$asset_class_method, input$fx_split), {
      cat("\n--- [DEBUG] 1. Recalculating single_port_data() ---\n")
      #req(has_run(), input$analysis_view == 'single_port')
      req(has_run())
      
      tryCatch({
        rp <- isolate(run_params())
        from_to <- if (!is.null(input$sub_period) && length(input$sub_period) == 2) input$sub_period else rp$analysis_dates
        mc <- mapping_calc()
        req(mc, mc$mapped_status, input$asset_class_method)
        map_df <- mc$mapped_status
        #validate(need(input$asset_class_method %in% mc$available, "자산군 분류 방법이 유효하지 않습니다."))
        
        # --- AP 데이터 계산 ---
        ap_res <- Portfolio_analysis(analysis_results$ap, from = from_to[1], to = from_to[2], mapping_method = input$asset_class_method, mapped_status = map_df, FX_split = input$fx_split)
        cat("[DEBUG] ap_res calculated? ", !is.null(ap_res), "\n")
        
        # [핵심 수정] 문제가 되는 함수들을 임시로 안전한 더미 함수로 교체
        ap_data_list <- list(
          # 일단 동작하는 더미 테이블로 교체해서 확인
          portfolio_summary_tbl   = single_port_table_summary(res_list_portfolio = ap_res, 
                                                              mapping_method = input$asset_class_method)[[1]],#create_dummy_table("AP 수익률 테이블 (임시)"),
          portfolio_summary_tbl_for_excel_자산군   = single_port_table_summary(res_list_portfolio = ap_res, 
                                                                            mapping_method = input$asset_class_method)[[2]],#create_dummy_table("AP 수익률 테이블 (임시)"),
          portfolio_summary_tbl_for_excel_sec   = single_port_table_summary(res_list_portfolio = ap_res, 
                                                                            mapping_method = input$asset_class_method)[[3]],#create_dummy_table("AP 수익률 테이블 (임시)"),
          # 동작하는 더미 플롯 함수로 교체
          return_analysis_plot  = single_port_historical_return(res_list_portfolio = ap_res,
                                                                mapping_method = input$asset_class_method),
          weight_analysis_plot  = single_port_historical_weight(res_list_portfolio = ap_res, 
                                                                Portfolio_name = rp$ap_portfolio,
                                                                mapping_method = input$asset_class_method)[[1]],
          weight_analysis_plot_for_excel_자산군  = single_port_historical_weight(res_list_portfolio = ap_res, 
                                                                              Portfolio_name = rp$ap_portfolio,
                                                                              mapping_method = input$asset_class_method)[[2]],
          weight_analysis_plot_for_excel_sec  = single_port_historical_weight(res_list_portfolio = ap_res, 
                                                                              Portfolio_name = rp$ap_portfolio,
                                                                              mapping_method = input$asset_class_method)[[3]]
          #performance_metrics_tbl = create_dummy_gt("AP 성과 지표"),
          #risk_metrics_tbl        = create_dummy_gt("AP 리스크 지표")
        )
        
        # --- BM 데이터 계산 ---
        bm_data_list <- NULL
        if (is_compare_run() && !is.null(analysis_results$bm)) {
          bm_res <- Portfolio_analysis(analysis_results$bm, from = from_to[1], to = from_to[2], mapping_method = input$asset_class_method, mapped_status  = map_df, FX_split = input$fx_split)
          cat("[DEBUG] bm_res calculated? ", !is.null(bm_res), "\n")
          bm_data_list <- list(
            portfolio_summary_tbl   = single_port_table_summary(res_list_portfolio = bm_res, 
                                                                mapping_method = input$asset_class_method)[[1]],#create_dummy_table("AP 수익률 테이블 (임시)"),
            portfolio_summary_tbl_for_excel_자산군   = single_port_table_summary(res_list_portfolio = bm_res, 
                                                                              mapping_method = input$asset_class_method)[[2]],#create_dummy_table("AP 수익률 테이블 (임시)"),
            portfolio_summary_tbl_for_excel_sec   = single_port_table_summary(res_list_portfolio = bm_res, 
                                                                              mapping_method = input$asset_class_method)[[3]],#create_dummy_table("AP 수익률 테이블 (임시)"),
            # 동작하는 더미 플롯 함수로 교체
            return_analysis_plot  = single_port_historical_return(res_list_portfolio = bm_res,
                                                                  mapping_method = input$asset_class_method),
            weight_analysis_plot  = single_port_historical_weight(res_list_portfolio = bm_res, 
                                                                  Portfolio_name = rp$bm_portfolio,
                                                                  mapping_method = input$asset_class_method)[[1]],
            weight_analysis_plot_for_excel_자산군  = single_port_historical_weight(res_list_portfolio = bm_res, 
                                                                                Portfolio_name = rp$bm_portfolio,
                                                                                mapping_method = input$asset_class_method)[[2]],
            weight_analysis_plot_for_excel_sec  = single_port_historical_weight(res_list_portfolio = bm_res, 
                                                                                Portfolio_name = rp$bm_portfolio,
                                                                                mapping_method = input$asset_class_method)[[3]]
          )
        }
        
        cat("--- [DEBUG] 1. single_port_data() calculation SUCCEEDED. ---\n")
        list(ap = ap_data_list, bm = bm_data_list)
        
      }, error = function(e) {
        cat("--- [DEBUG] 1. single_port_data() calculation FAILED. Error:", e$message, "\n")
        
        # --- 오류 경로 추적 ---
        cat("--- Traceback ---\n")
        print(traceback())
        cat("------------------\n\n")
        showNotification(paste("데이터 계산 중 오류:", e$message), type = "error")
        return(NULL)
      })
    }, ignoreNULL = FALSE)
    
    
    # Step 2: UI 동적 제어
    
    # [수정] '성과분석 실행' 시 UI 상태를 강제로, 그리고 올바른 순서로 설정
    observeEvent(run_id(), {
      req(run_id() > 0)
      
      
      cat("--- [DEBUG] 2. run_id() observer triggered. Initializing UI... ---\n")
      
      
      rp <- isolate(run_params())
      
      # 지연을 둬서 UI 업데이트가 순차적으로 이루어지도록
      shiny::invalidateLater(100, session)
      # 2-A. '표/그래프' 버튼을 먼저 설정합니다. (매우 중요)
      # 이 값이 변경되어야 아래의 '분석 종류' observeEvent가 올바르게 연쇄 반응합니다.
      updateRadioGroupButtons(session, "single_port_left_display_type", selected = "table")
      updateRadioGroupButtons(session, "single_port_right_display_type", selected = "plot")
      
      # 2-B. '분석 종류'를 설정합니다.
      # '표'에 맞는 선택지 중 '수익률 분석'을 선택
      updateSelectInput(session, "single_port_left_analysis_type", selected = "portfolio_summary")
      # '그래프'에 맞는 선택지 중 '수익률 분석'을 선택
      updateSelectInput(session, "single_port_right_analysis_type", selected = "return_analysis")
      
      # 2-C. 포트폴리오 선택 UI를 마지막으로 설정합니다. (`compare` 모드일 때만)
      if (rp$analysis_mode == 'compare') {
        choices <- setNames(c("ap", "bm"), c(rp$ap_portfolio, rp$bm_portfolio))
        updateSelectInput(session, "selected_single_portfolio_left", choices = choices, selected = "ap")
        updateSelectInput(session, "selected_single_portfolio_right", choices = choices, selected = "ap")
      }else{
        choices <- setNames(c("ap"), c(rp$ap_portfolio))
        updateSelectInput(session, "selected_single_portfolio_left", choices = choices, selected = "ap")
        updateSelectInput(session, "selected_single_portfolio_right", choices = choices, selected = "ap")
      }
      
    }, ignoreInit = TRUE)
    
    
    # [수정] '표/그래프' 선택에 따른 '분석 종류' 동적 변경 로직 (안정성 강화)
    observeEvent(list(input$single_port_left_display_type, input$single_port_right_display_type), {
      
      # --- 왼쪽 패널 ---
      req(input$single_port_left_display_type)
      current_selection_left <- isolate(input$single_port_left_analysis_type)
      table_choices <- c("포트폴리오 요약" = "portfolio_summary") # 만약 리스크관련 테이블 추가하려면 여기에 요소 추가 및 UI, single_port_data와 연동
      plot_choices <- c("수익률 분석" = "return_analysis", "비중 분석" = "weight_analysis")
      new_choices_left <- if (input$single_port_left_display_type == "table") table_choices else plot_choices
      new_selected_left <- if (!is.null(current_selection_left) && current_selection_left %in% new_choices_left) current_selection_left else new_choices_left[1]
      updateSelectInput(session, "single_port_left_analysis_type", choices = new_choices_left, selected = new_selected_left)
      
      # --- 오른쪽 패널 ---
      req(input$single_port_right_display_type)
      current_selection_right <- isolate(input$single_port_right_analysis_type)
      new_choices_right <- if (input$single_port_right_display_type == "table") table_choices else plot_choices
      new_selected_right <- if (!is.null(current_selection_right) && current_selection_right %in% new_choices_right) current_selection_right else new_choices_right[1]
      updateSelectInput(session, "single_port_right_analysis_type", choices = new_choices_right, selected = new_selected_right)
      
    }, ignoreNULL = TRUE, ignoreInit = TRUE)
    
    
    
    
    # [핵심 수정] Step 3: 렌더링할 데이터를 준비하는 중간 단계 추가
    # UI 컨트롤 값들이 바뀔 때마다 즉시 반응하여 최종 데이터를 가져옵니다.
    # 이 eventReactive는 run_id가 바뀔 때도 자동으로 다시 실행됩니다.
    left_panel_data <- eventReactive({
      # 왼쪽 패널의 모든 UI 컨트롤 값들을 의존성으로 등록
      run_id()
      input$single_port_left_display_type
      input$single_port_left_analysis_type
      input$selected_single_portfolio_left
      input$sub_period
      input$analysis_view              # 탭 전환 감지
      input$asset_class_method
      input$fx_split
    }, {
      cat("\n--- [DEBUG] Preparing left_panel_data ---\n")
      # get_selected_data는 이제 여기서만 호출됩니다.
      get_selected_data("left")
    })
    
    right_panel_data <- eventReactive({
      # 오른쪽 패널의 모든 UI 컨트롤 값들을 의존성으로 등록
      run_id()
      input$single_port_right_display_type
      input$single_port_right_analysis_type
      input$selected_single_portfolio_right
      input$sub_period
      input$analysis_view              # 탭 전환 감지
      input$asset_class_method
      input$fx_split
    }, {
      cat("\n--- [DEBUG] Preparing right_panel_data ---\n")
      get_selected_data("right")
    })
    
    # Step 3: 최종 컨텐츠 렌더링
    
    # [수정] 데이터 가져오는 헬퍼 함수 (디버깅 메시지 추가)
    
    # [핵심 수정] get_selected_data 함수를 더 강력하게 만듭니다.
    get_selected_data <- function(panel_side) {
      cat(paste0("\n--- [DEBUG] 3. Calling get_selected_data('", panel_side, "') ---\n"))
      
      # 1. 필수 입력값 확인
      req(has_run(), input$analysis_view == 'single_port')
      if (is.null(single_port_data())) {
        showNotification("분석 데이터가 아직 준비되지 않았습니다.", type = "warning")
        return(NULL)
      }
      
      analysis_type_input <- if (panel_side == "left") input$single_port_left_analysis_type else input$single_port_right_analysis_type
      display_type_input  <- if (panel_side == "left") input$single_port_left_display_type else input$single_port_right_display_type
      portfolio_sel_input <- if (panel_side == "left") input$selected_single_portfolio_left else input$selected_single_portfolio_right
      
      cat(paste0("   - analysis_type: '", analysis_type_input, "'\n"))
      cat(paste0("   - display_type: '", display_type_input, "'\n"))
      cat(paste0("   - portfolio_sel: '", portfolio_sel_input, "'\n"))
      
      # 2. 선택값이 유효한지 확인 (빈 값이면 조용히 종료)
      if (is.null(analysis_type_input) || analysis_type_input == "") return(NULL)
      
      rp <- run_params()
      p_key <- if (rp$analysis_mode == 'single') {
        'ap'  # 단일 모드에서는 항상 AP 사용
      } else {
        # 비교 모드에서만 사용자 선택에 따라 결정
        if (is.null(portfolio_sel_input) || portfolio_sel_input == "") {
          #showNotification("포트폴리오를 선택해주세요.", type = "warning")
          return(NULL)
        }
        portfolio_sel_input
      }
      
      # 3. 데이터 리스트에서 필요한 부분 추출
      data_for_portfolio <- single_port_data()[[p_key]]
      if (is.null(data_for_portfolio)) {
        showNotification(paste(p_key, "에 대한 분석 데이터를 찾을 수 없습니다."), type = "error")
        return(NULL)
      }
      
      # 4. 최종 데이터 키 생성
      # 성과/리스크 지표는 테이블만 있으므로 예외 처리
      data_key <- if (analysis_type_input %in% c("performance_metrics", "risk_metrics")) {
        paste0(analysis_type_input, "_tbl")
      } else {
        paste0(analysis_type_input, "_", if (display_type_input == "table") "tbl" else "plot")
      }
      
      final_data <- data_for_portfolio[[data_key]]
      
      # 5. 최종 데이터 유효성 검사 (실패 시 사용자에게 알림)
      if (is.null(final_data)) {
        msg <- paste0("'", analysis_type_input, "'에 대한 '", display_type_input, "' 결과를 찾을 수 없습니다. (key: ", data_key, ")")
        showNotification(msg, type = "warning", duration = 7)
        return(NULL)
      }
      
      cat(paste0("--- [DEBUG] 3. get_selected_data('", panel_side, "') SUCCEEDED. Returning data.\n"))
      return(final_data)
    }
    
    
    # [유지] UI 렌더링 함수 (수정 필요 없음)
    
    # [수정] renderUI는 이제 준비된 데이터에만 반응합니다.
    output$single_port_left_output <- renderUI({
      # try-catch로 감싸서, eventReactive가 계산 중일 때 발생하는 에러를 방지
      data <- try(left_panel_data(), silent = TRUE)
      req(!inherits(data, "try-error") && !is.null(data))
      
      cat("--- [DEBUG] Rendering left_panel_output ---\n")
      
      
      # [핵심 수정] 오른쪽 패널에도 동일한 로직을 적용합니다.
      if (is.list(data) && !inherits(data, "htmlwidget") && !is.data.frame(data)) {
        tab_names <- names(data)
        tabs <- lapply(seq_along(tab_names), function(i) {
          tab_name <- tab_names[i]
          # ID가 겹치지 않도록 "right"를 포함하여 생성합니다.
          output_id <- ns(paste0("return_chart_left_", i))
          tabPanel(title = tab_name, echarts4rOutput(output_id, height = "500px"))
        })
        do.call(tabsetPanel, tabs)
        
      }else{
        
        # 데이터 종류에 따라 적절한 UI 출력 함수를 호출
        if (inherits(data, "highchart")) {
          # ★★★ highchart 렌더링 추가 ★★★
          highcharter::renderHighchart({data})
          
        } else if (inherits(data, "reactable")) {
          # ★★★ reactable 렌더링 추가 ★★★
          
          # 1. 필요한 정보 가져오기 (실행 파라미터, 분석 기간)
          rp <- run_params()
          dates <- input$sub_period
          req(rp, dates) # 정보가 준비될 때까지 대기
          
          # 2. 표시할 포트폴리오 이름 결정
          # '비교' 모드일 때는 드롭다운 선택값을 따르고, '단일' 모드일 때는 항상 AP를 사용합니다.
          portfolio_name <- if (rp$analysis_mode == 'compare') {
            req(input$selected_single_portfolio_left)
            if (input$selected_single_portfolio_left == "ap") rp$ap_portfolio else rp$bm_portfolio
          } else {
            rp$ap_portfolio
          }
          
          # 3. 제목 문자열 생성
          title_text <- sprintf(
            "%s 요약 (%s ~ %s)",
            portfolio_name,
            format(dates[1], "%Y-%m-%d"),
            format(dates[2], "%Y-%m-%d")
          )
          
          # 4. 동적 제목과 함께 reactable 렌더링
          tagList(
            tags$h5(title_text, style = "font-weight: bold; margin-bottom: 10px;"),
            reactable::renderReactable({data})
          )
          
          
        } else if (inherits(data, "gt_tbl")) {
          gt::render_gt(expr = {data})
          
        } else if (inherits(data, "plotly")) {
          renderPlotly({data})
          
        } else if (inherits(data, "echarts4r") || inherits(data, "htmlwidget")) { 
          renderEcharts4r({ data })
          
        } else if (is.data.frame(data)) {
          # reactable, gt_tbl 객체도 data.frame이므로 이 조건은 가장 마지막에 와야 합니다.
          DT::renderDT(data, options = list(dom = 't', paging = FALSE, info = FALSE))
          
        } else {
          "지원하지 않는 데이터 형식입니다."
        }
        
      }
      
      
    })
    
    output$single_port_right_output <- renderUI({
      data <- try(right_panel_data(), silent = TRUE)
      req(!inherits(data, "try-error") && !is.null(data))
      
      cat("--- [DEBUG] Rendering right_panel_output ---\n")
      
      # [핵심 수정] 오른쪽 패널에도 동일한 로직을 적용합니다.
      if (is.list(data) && !inherits(data, "htmlwidget") && !is.data.frame(data)) {
        tab_names <- names(data)
        tabs <- lapply(seq_along(tab_names), function(i) {
          tab_name <- tab_names[i]
          # ID가 겹치지 않도록 "right"를 포함하여 생성합니다.
          output_id <- ns(paste0("return_chart_right_", i))
          tabPanel(title = tab_name, echarts4rOutput(output_id, height = "500px"))
        })
        do.call(tabsetPanel, tabs)
        
      }else{
        
        
        # 데이터 종류에 따라 적절한 UI 출력 함수를 호출
        if (inherits(data, "highchart")) {
          # ★★★ highchart 렌더링 추가 ★★★
          highcharter::renderHighchart({data})
          
        } else if (inherits(data, "reactable")) {
          # ★★★ reactable 렌더링 추가 ★★★
          # 1. 필요한 정보 가져오기 (실행 파라미터, 분석 기간)
          rp <- run_params()
          dates <- input$sub_period
          req(rp, dates) # 정보가 준비될 때까지 대기
          
          # 2. 표시할 포트폴리오 이름 결정
          # '비교' 모드일 때는 드롭다운 선택값을 따르고, '단일' 모드일 때는 항상 AP를 사용합니다.
          portfolio_name <- if (rp$analysis_mode == 'compare') {
            req(input$selected_single_portfolio_right)
            if (input$selected_single_portfolio_right == "ap") rp$ap_portfolio else rp$bm_portfolio
          } else {
            rp$ap_portfolio
          }
          
          # 3. 제목 문자열 생성
          title_text <- sprintf(
            "%s 요약 (%s ~ %s)",
            portfolio_name,
            format(dates[1], "%Y-%m-%d"),
            format(dates[2], "%Y-%m-%d")
          )
          
          # 4. 동적 제목과 함께 reactable 렌더링
          tagList(
            tags$h5(title_text, style = "font-weight: bold; margin-bottom: 10px;"),
            reactable::renderReactable({data})
          )
          
          
        } else if (inherits(data, "gt_tbl")) {
          gt::render_gt(expr = {data})
          
        } else if (inherits(data, "plotly")) {
          renderPlotly({data})
          
        } else if (inherits(data, "echarts4r") || inherits(data, "htmlwidget")) { 
          renderEcharts4r({ data })
          
        } else if (is.data.frame(data)) {
          # reactable, gt_tbl 객체도 data.frame이므로 이 조건은 가장 마지막에 와야 합니다.
          DT::renderDT(data, options = list(dom = 't', paging = FALSE, info = FALSE))
          
        } else {
          "지원하지 않는 데이터 형식입니다."
        }
        
      }
      
      
      
    })
    
    # 왼쪽 패널의 동적 차트를 렌더링합니다.
    observeEvent(left_panel_data(), {
      data <- left_panel_data()
      # 데이터가 유효한 리스트 형태일 때만 실행합니다.
      req(is.list(data) && !inherits(data, "htmlwidget") && !is.data.frame(data) && length(data) > 0)
      
      # for 루프를 사용해 각 탭에 대한 차트를 생성합니다.
      for (i in seq_along(data)) {
        # local()은 Shiny에서 루프를 사용할 때 각 변수(i)의 값을 "고정"시키는 중요한 역할을 합니다.
        # 이것이 없으면 모든 차트가 마지막 데이터로 그려지는 문제가 발생할 수 있습니다.
        local({
          my_i <- i
          # renderUI에서 생성한 ID와 동일한 규칙으로 output ID를 만듭니다.
          output_id <- paste0("return_chart_left_", my_i)
          
          # 해당 output 슬롯에 echarts4r 그래프를 렌더링합니다.
          output[[output_id]] <- renderEcharts4r({
            # 리스트의 my_i 번째 데이터를 가져와 그래프 함수에 전달합니다.
            data[[my_i]] %>% 
              single_port_historical_return_echarts4r()
          })
        })
      }
    })
    
    # 오른쪽 패널의 동적 차트를 렌더링합니다.
    observeEvent(right_panel_data(), {
      data <- right_panel_data()
      req(is.list(data) && !inherits(data, "htmlwidget") && !is.data.frame(data) && length(data) > 0)
      
      for (i in seq_along(data)) {
        local({
          my_i <- i
          output_id <- paste0("return_chart_right_", my_i)
          
          output[[output_id]] <- renderEcharts4r({
            data[[my_i]] %>% 
              single_port_historical_return_echarts4r()
          })
        })
      }
    })
    
    # 자산군매핑 SECTION -----------------------------------------------------------
    
    
    output$tbl_mapping <- DT::renderDT({
      
      has_run_val <- has_run()
      #is_mapping_view <- (input$analysis_view == "mapping")
      req(has_run_val) # 이제 원래 req()를 실행합니다.
      mc <- mapping_calc()
      # ... 나머지 코드는 동일 ...
      req(is.list(mc), !is.null(mc$mapped_status))
      validate(need(NROW(mc$mapped_status) > 0, "매핑 데이터가 없습니다."))
      
      DT::datatable(
        mc$mapped_status,
        options = list(scrollX = TRUE,  
                       pageLength = 15, searching = TRUE),
        rownames = FALSE
      )
    })
    
    
    # 엑셀다운로드 ------------------------------------------------------------------
    
    
    output$download_excel <- downloadHandler(
      filename = function() {
        rp <- isolate(run_params())
        if (is_compare_run()) {
          paste0("PA_compare_",
                 rp$ap_portfolio,"_vs_",rp$bm_portfolio,
                 str_glue("({input$sub_period[1]} ~ {input$sub_period[2]})"),
                 str_glue("_{input$asset_class_method}_FXsplit={input$fx_split}"),".xlsx")
        }else{
          paste0("PA_single_",
                 rp$ap_portfolio,"_",
                 str_glue("({input$sub_period[1]} ~ {input$sub_period[2]})"),
                 str_glue("_{input$asset_class_method}_FXsplit={input$fx_split}"),".xlsx")
        }
        
      },
      content = function(file) {
        req(has_run())
        
        # 사용자에게 다운로드 준비 중임을 알림
        withProgress(message = '엑셀 파일 생성 중...', value = 0, {
          
          data_to_export <- list()
          
          # --- 1. Brinson 데이터 수집 (비교 모드일 때만) ---
          incProgress(0.1, detail = "Brinson 데이터 수집 중...")
          if (is_compare_run()) {
            tryCatch({
              b_data <- brinson_data()
              if (!is.null(b_data)) {
                
                if(is.list(b_data$tbl_3) && !is.null(b_data$tbl_3$DF)) {
                  data_to_export[["Brinson_초과성과_요인분해_tbl"]] <- b_data$tbl_3$DF
                }
                data_to_export[["Brinson_수익률요약_tbl"]] <- bind_rows(b_data$tbl_1 %>% mutate(설명 = "수익률(기여)"),
                                                                   b_data$tbl_1_1 %>% mutate(설명 = "수익률(Norm)")) %>% 
                  select(구분,설명,everything())
                data_to_export[["Brinson_비중요약_tbl"]] <- b_data$tbl_2
                
                if(is.data.frame(b_data$plot_1)) data_to_export[["Brinson_수익률비교_plot"]] <- b_data$plot_1
                if(is.data.frame(b_data$plot_2)) data_to_export[["Brinson_비중비교_plot"]] <- b_data$plot_2
                if(is.list(b_data$plot_3)){
                  if(is.data.frame(b_data$plot_3[["자산군별"]])) data_to_export[["Brinson_초과성과_자산군별_plot"]] <- b_data$plot_3[["자산군별"]]
                  if(is.data.frame(b_data$plot_3[["요인별"]])) data_to_export[["Brinson_초과성과_요인별_plot"]] <- b_data$plot_3[["요인별"]]
                }
              }
            }, error = function(e) {
              showNotification("Brinson 데이터 생성 중 오류 발생. 이 부분은 제외됩니다.", type = "warning")
              message("Error in Brinson data for excel: ", e$message)
            })
          }
          
          # --- 2. 개별 포트폴리오 데이터 수집 ---
          incProgress(0.4, detail = "개별 포트폴리오 데이터 수집 중...")
          
          if (is_compare_run()) {
            tryCatch({
              sp_data <- single_port_data()
              if (!is.null(sp_data)) {
                rp <- isolate(run_params())
                # AP 데이터
                if (!is.null(sp_data$ap)) {
                  ap_name <- rp$ap_portfolio # 시트 이름에 부적합한 문자 제거?
                  if(is.data.frame(sp_data$ap$portfolio_summary_tbl_for_excel_자산군)) data_to_export[[paste0("AP_", ap_name, "_자산군별요약_tbl")]] <- sp_data$ap$portfolio_summary_tbl_for_excel_자산군
                  if(is.data.frame(sp_data$ap$portfolio_summary_tbl_for_excel_sec)) data_to_export[[paste0("AP_", ap_name, "_sec별요약_tbl")]] <- sp_data$ap$portfolio_summary_tbl_for_excel_sec
                  # 아래 weight 에 return도 같이 있음
                  if(is.data.frame(sp_data$ap$weight_analysis_plot_for_excel_자산군)) data_to_export[[paste0("AP_", ap_name, "_자산군별_plot")]] <- sp_data$ap$weight_analysis_plot_for_excel_자산군
                  if(is.data.frame(sp_data$ap$weight_analysis_plot_for_excel_sec)) data_to_export[[paste0("AP_", ap_name, "_sec별_plot")]] <- sp_data$ap$weight_analysis_plot_for_excel_sec
                }
                # BM 데이터 (존재할 경우)
                if (!is.null(sp_data$bm)) {
                  bm_name <- rp$bm_portfolio
                  if(is.data.frame(sp_data$bm$portfolio_summary_tbl_for_excel_자산군)) data_to_export[[paste0("bm_", bm_name, "_자산군별요약_tbl")]] <- sp_data$bm$portfolio_summary_tbl_for_excel_자산군
                  if(is.data.frame(sp_data$bm$portfolio_summary_tbl_for_excel_sec)) data_to_export[[paste0("bm_", bm_name, "_sec별요약_tbl")]] <- sp_data$bm$portfolio_summary_tbl_for_excel_sec
                  # 아래 weight 에 return도 같이 있음
                  if(is.data.frame(sp_data$bm$weight_analysis_plot_for_excel_자산군)) data_to_export[[paste0("bm_", bm_name, "_자산군별_plot")]] <- sp_data$bm$weight_analysis_plot_for_excel_자산군
                  if(is.data.frame(sp_data$bm$weight_analysis_plot_for_excel_sec)) data_to_export[[paste0("bm_", bm_name, "_sec별_plot")]] <- sp_data$bm$weight_analysis_plot_for_excel_sec
                }
              }
            }, error = function(e) {
              showNotification("개별 포트폴리오 데이터 생성 중 오류 발생. 이 부분은 제외됩니다.", type = "warning")
              message("Error in Single Port data for excel: ", e$message)
            })
          }else{
            
            tryCatch({
              sp_data <- single_port_data()
              if (!is.null(sp_data)) {
                rp <- isolate(run_params())
                # AP 데이터
                if (!is.null(sp_data$ap)) {
                  ap_name <- rp$ap_portfolio # 시트 이름에 부적합한 문자 제거?
                  if(is.data.frame(sp_data$ap$portfolio_summary_tbl_for_excel_자산군)) data_to_export[[paste0("AP_", ap_name, "_자산군별요약_tbl")]] <- sp_data$ap$portfolio_summary_tbl_for_excel_자산군
                  if(is.data.frame(sp_data$ap$portfolio_summary_tbl_for_excel_sec)) data_to_export[[paste0("AP_", ap_name, "_sec별요약_tbl")]] <- sp_data$ap$portfolio_summary_tbl_for_excel_sec
                  # 아래 weight 에 return도 같이 있음
                  if(is.data.frame(sp_data$ap$weight_analysis_plot_for_excel_자산군)) data_to_export[[paste0("AP_", ap_name, "_자산군별_plot")]] <- sp_data$ap$weight_analysis_plot_for_excel_자산군
                  if(is.data.frame(sp_data$ap$weight_analysis_plot_for_excel_sec)) data_to_export[[paste0("AP_", ap_name, "_sec별_plot")]] <- sp_data$ap$weight_analysis_plot_for_excel_sec
                }
                
              }
            }, error = function(e) {
              showNotification("개별 포트폴리오 데이터 생성 중 오류 발생. 이 부분은 제외됩니다.", type = "warning")
              message("Error in Single Port data for excel: ", e$message)
            })
          }
          
          
          
          # --- 3. 매핑 데이터 수집 ---
          incProgress(0.3, detail = "매핑 데이터 수집 중...")
          tryCatch({
            mc_data <- mapping_calc()
            if (!is.null(mc_data) && is.data.frame(mc_data$mapped_status)) {
              data_to_export[["매핑_현황"]] <- mc_data$mapped_status
            }
          }, error = function(e) {
            showNotification("매핑 데이터 생성 중 오류 발생. 이 부분은 제외됩니다.", type = "warning")
            message("Error in Mapping data for excel: ", e$message)
          })
          
          # --- 4. 엑셀 파일로 저장 ---
          incProgress(0.2, detail = "파일 저장 중...")
          validate(need(length(data_to_export) > 0, "내보낼 데이터가 없습니다. 분석을 다시 실행해주세요."))
          
          writexl::write_xlsx(data_to_export, path = file)
        })
      }
    )
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    
    
    # 숨겨져 있을 때 렌더 중지 방지(선택 사항이지만 권장)
    outputOptions(output, "tbl_mapping", suspendWhenHidden = FALSE)
    outputOptions(output, suspendWhenHidden = FALSE)
    
  })
}


