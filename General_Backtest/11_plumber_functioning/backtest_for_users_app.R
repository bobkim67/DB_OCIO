library(shiny)
library(tidyverse)
library(DT)
library(lubridate)
library(clipr)
library(echarts4r)

source("11_plumber_functioning/backtest_for_users_v2.R")

# 우선순위----
#리밸런싱일자 분석가능일자 비교하여 이상있으면 오류 반환하기!!!!!(아직 해결 XXX)
#--> 최종으로 백테스트 실행버튼 눌렀을때의 최종 편집된 표와, universe표를 join하여 오류있는 행 수정하라고 언급해주기 
# weight가 0인거 있으면 알려주고 오류반환.
# ***현재 가용데이터의 첫 날에 대해 수익률 계산이 안됨. 가격종가만 가지고 있기 때문.***
#> 해결과제 6. 수익률/mdd,샤프 등등 지표 계산 및 시각화 모듈만들고, 결합하기 
# 추후 ----
#> 해결과제 4. 최종 결과 longform/wideform 선택가능하게
#> 해결과제 8. 현금/증거금 입력가능하여 cd/등등의 금리 적용할수있게 (증거금은 금리0)
#> 해결과제 9. 초기 비중과 괴리가 몇%벌어지면 리밸런싱자동으로할껀지. (수시리밸런싱 조건 적용 열 추가) 
#> ---> 순차적 계산 하여 리밸런싱트리거 날짜 추가해야됨. 초기 비중(Fix)과 drift 비중의 차이를 이용하여 수시 비율 계산 가능
#> ---> while문으로 리밸런싱트리거 열 에 True있으면 리밸런싱날짜 추가 후 재계산
#> 해결과제10. 리밸런싱간 순 매수/매도에 대해 국내/해외 수수료 부과 3bp/6bp
#> 해결과제11. 환헤지cost 지수 가져와서 합리적인 수익률 계산 
#> waiter 패키지 이용해서 로딩 얼마나걸리는지 가늠할수있게
#> MP history 정보가져오게끔?
#> 경기국면 Point in Time 데이터 레이어 추가
#> 자산군 분류 추가하여 리밸런싱 조건에 따른 트리거 반영
#> 행 전체 삭제 기능
#>  백테스트 실행시에 다른 화면으로 이동 하여 포트폴리오별로 / 각 통계지표 일목요연하게보여줄수있게하기. 자산군분류체계 확립시 더 좋을듯
# 3. universe테이블 변수위치 조정
# 4. 간단한 시각화 및 표 -> 리밸런싱일자별로 vertical line그리기 
# 5. 백테스트실행/행제거 옵션을 백테스트 데이터편집 표 위쪽으로 이동.


# 해결완료 ----
#> 해결과제 1. 아무 weight인풋받으면 펀드설명/리밸런싱날짜별로 groupby 해서 1로 조정??
#> 해결과제 5. 펀드데이터도 유니버스에 추가 가능하게 -> bf,TDF,펀드코드별 기준가데이터 받아서 cache파일 만들어놓고 사용하면 될듯
#> 중복 티커를 Input했을때 요약해서 해줄지 아니면 경고문으로 수정하라고함
#> 해결과제 7. clipboard이용한 데이터 input or 파일 이용하여 업로드할수잇게.
# 기본 데이터 설정 (업로드 없이 사용할 기본 골자) 및 전부삭제되어도 임의의 값 추가 가능


sb_back <- tribble(
  ~리밸런싱날짜, ~Portfolio, ~dataset_id, ~dataseries_id, ~region, ~weight,  ~hedge_ratio, ~cost_adjust,
  
  
  "2023-12-08","Test1", "253", "9", "KR", 0.7, 0, 0,
  "2023-12-08","Test1", "187", "33", "KR", 0.3,  0,0,
  "2023-12-08","Test1", "07J48", "MOD_STPR", "KR", 0.3, 0,0
 
  # #--
  # "2023-12-08","Test2 ", 253, 9, "KR", 0.3, "MP", 0,0,
  # "2023-12-08","Test2 ", 187, 33, "KR", 0.7, "MP", 0, 0,
  # "2024-10-24","Test2", 253, 9, "KR", 0.7, "MP", 0, 0,
  # "2024-10-24","Test2", 187, 33, "KR", 0.3, "MP", 0,0
) %>%
  mutate(리밸런싱날짜 = ymd(리밸런싱날짜)) 

backtest_prep_table <- sb_back


# UI&SERVER ---------------------------------------------------------------


ui <- navbarPage(
  title = "백테스트",    # 상단 바의 제목
  id = "tabs",          # 탭 식별자 (서버에서 updateTabsetPanel과 비슷한 updateNavbarPage 사용)
  
  # ────────── (1) 편집 & 실행 탭 ──────────
  tabPanel("편집 & 실행",
           # 여기서 fluidPage(또는 fluidRow) 등으로 레이아웃 구성
           fluidRow(
             column(
               width = 5,
               textInput("search_universe", "유니버스 검색", ""),
               DTOutput("universe_table"),
               
               actionButton("add_selected", "선택된 유니버스 추가하기")
             ),
             column(
               width = 7,
               fluidRow(
                 column(
                   width = 12,
                   actionButton("add_from_clipboard", "클립보드에서 데이터 추가"),
                   actionButton("remove_row", "행 제거"),
                   actionButton("remove_all_rows", "행 전부 제거"),
                   actionButton("run", "백테스트 실행",
                                style = "background-color: #3399FF; color: white; border: none;"
                   )
                 )
               ),
               h3("백테스트 데이터 편집"),
               DTOutput("edit_table")
             )
           )
  ),
  
  # ────────── (2) 결과 페이지 탭 ──────────
  tabPanel("결과 페이지",
           tags$head(
             tags$style(HTML("
        table.dataTable thead th {
          white-space: nowrap; 
          transform: rotate(0deg) !important;
        }
      "))
           ),
           fluidRow(
             style = "height: calc(100vh - 80px);",
             
             # 왼쪽 (width=5): flex로 1:3 분할
             column(
               width = 5,
               style = "
          height: 100%;
          display: flex; 
          flex-direction: column;
          padding: 0px; 
          margin: 0px;
        ",
               # 위쪽(1)
               div(
                 style = "
            flex: 1; 
            padding: 10px; 
            margin: 5px; 
            background-color: #f7f7f7; 
            border: 1px solid #ddd; 
            border-radius: 5px;
          ",
                 # 여기서 선택한 날짜를 서버에서 input$analysis_end_date로 접근 가능
                 dateInput("analysis_end_date", "분석 종료일", value = Sys.Date()),
                 radioButtons(
                   inputId = "weight_type", 
                   label = "Weight Type",
                   choices = c("Fixed Weight", "Drift Weight"),
                   inline = TRUE
                 ),
                 downloadButton("download", "결과 다운로드")
               ),
               # 아래(3)
               div(
                 style = "
            flex: 3; 
            overflow-y: auto; 
            padding: 10px; 
            margin: 5px; 
            background-color: #ffffff; 
            border: 1px solid #ddd;
            border-radius: 5px;
          ",
                 tabsetPanel(
                   tabPanel("결과표1", DTOutput("result_table1")),
                   tabPanel("결과표2", DTOutput("result_table2"))
                 )
               )
             ),
             
             # 오른쪽(width=7)
             column(
               width = 7,
               style = "height: 100%;",
               tabsetPanel(
                 # plotOutput -> echarts4rOutput 로 변경
                 tabPanel("그래프1", echarts4rOutput("plot_graph1", height = "600px")),
                 tabPanel("그래프2", plotOutput("plot_graph2", height = "600px"))
               )
             )
           )
  )
)

server <- function(input, output, session) {
  
  #------------------ 편집용 데이터 ------------------#
  values <- reactiveValues(data = sb_back)  # sb_back은 사용자 환경에서 정의되어 있다고 가정
  
  #------------------ 백테스트 결과 ------------------#
  backtest_results <- reactiveVal(NULL)
  
  #------------------ 선택된 유니버스 ------------------#
  selected_universe <- reactiveVal(NULL)
  
  #------ 편집 테이블 출력
  
  output$edit_table <- renderDT({
    datatable(
      values$data,
      editable = TRUE,
      selection = "multiple",
      options = list(
        pageLength = 10,
        scrollX = TRUE,
        autoWidth = TRUE
      ),
      style = "bootstrap",
      class = "display"
    )
  })
  
  # 편집 후 데이터 반영
  observeEvent(input$edit_table_cell_edit, {
    info <- input$edit_table_cell_edit
    i <- info$row
    j <- info$col
    v <- info$value
    if (colnames(values$data)[j] == "리밸런싱날짜" && !is.na(as.Date(v))) {
      v <- as.Date(v)
    }
    new_data <- values$data
    new_data[i, j] <- v
    values$data <- new_data
  })
  
  # 행 제거
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
  
  # 행 전부 제거
  observeEvent(input$remove_all_rows, {
    values$data <- values$data[0, , drop = FALSE]
  })
  
  # 클립보드에서 데이터 추가
  observeEvent(input$add_from_clipboard, {
    new_data <- tryCatch({
      clipr::read_clip_tbl() %>% tibble()
    }, error = function(e) {
      showModal(modalDialog(
        title = "오류",
        "클립보드에서 데이터를 읽을 수 없습니다. 클립보드 내용을 확인해주세요.",
        easyClose = TRUE,
        footer = NULL
      ))
      return(NULL)
    })
    
    if (!is.null(new_data)) {
      if (nrow(new_data) == 0) {
        showModal(modalDialog(
          title = "행 수 오류",
          "클립보드의 데이터가 비어 있습니다. 데이터를 확인해주세요.",
          easyClose = TRUE,
          footer = NULL
        ))
        return()
      }
      
      if (ncol(new_data) != ncol(values$data)) {
        showModal(modalDialog(
          title = "형식 오류",
          "클립보드의 데이터 열 개수/순서를 확인해주세요.",
          easyClose = TRUE,
          footer = NULL
        ))
        return()
      }
      
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
      
      colnames(new_data) <- colnames(values$data)
      new_data <- new_data %>%
        mutate(
          리밸런싱날짜 = ymd(리밸런싱날짜),
          weight = as.numeric(weight)
        )
      
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
  
  #------------------ 유니버스 테이블 ------------------
  output$universe_table <- renderDT({
    filtered_data <- data_information %>%
      dplyr::select(-colname_backtest)
    
    if (nchar(input$search_universe) > 0) {
      filtered_data <- filtered_data %>%
        dplyr::filter(
          grepl(input$search_universe, dataset_id, ignore.case = TRUE) |
            grepl(input$search_universe, dataseries_id, ignore.case = TRUE) |
            grepl(input$search_universe, name, ignore.case = TRUE) |
            grepl(input$search_universe, symbol, ignore.case = TRUE) |
            grepl(input$search_universe, ISIN, ignore.case = TRUE)
        )
    }
    selected_universe(filtered_data)
    
    datatable(
      filtered_data,
      selection = "single",
      options = list(
        dom = 'tp',
        pageLength = 5,
        scrollX = TRUE,
        scrollY = "400px",
        paging = FALSE
      )
    )
  })
  
  # 유니버스 추가
  observeEvent(input$add_selected, {
    sel_row <- input$universe_table_rows_selected
    if(length(sel_row) > 0) {
      filtered_data <- selected_universe()
      selected_data <- filtered_data[sel_row, ]
      # 만약 편집 테이블이 비어있다면(모두 제거된 상태)
      if (nrow(values$data) == 0) {
        new_row <- tibble(
          리밸런싱날짜 = floor_date(today(), unit = "year"),
          Portfolio = "Test1",
          dataset_id = as.character(selected_data$dataset_id),
          dataseries_id = as.character(selected_data$dataseries_id),
          region = selected_data$region,
          weight = 1,
          hedge_ratio = 0,
          cost_adjust = 0
        )
      } else {
        new_row <- tail(values$data, 1)
        new_row$dataset_id <- as.character(selected_data$dataset_id)
        new_row$dataseries_id <- as.character(selected_data$dataseries_id)
        new_row$region <- selected_data$region
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
  
  #------------------ 백테스트 실행 ------------------#
  observeEvent(input$run, {
    # 중복 확인
    duplicates <- values$data %>%
      group_by(리밸런싱날짜, Portfolio, dataset_id) %>%
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
    
    # 중복이 없으면 백테스트 실행
    data_to_use <- values$data %>%
      arrange(리밸런싱날짜) %>%
      group_by(리밸런싱날짜, Portfolio) %>%
      mutate(weight = weight / sum(weight)) %>%
      ungroup()
    
    res <- backtesting_for_users(data_to_use)
    backtest_results(res)
    
    # 실행 후 결과 페이지로 탭 전환
    updateTabsetPanel(session, "tabs", selected = "결과 페이지")
  })
  
  #------------------ 결과 테이블/그래프 출력 ------------------#
  output$result_table1 <- renderDT({
    req(backtest_results())
    datatable(backtest_results()[[1]])
  })
  
  output$result_table2 <- renderDT({
    req(backtest_results())
    datatable(backtest_results()[[2]])
  })
  
  # renderPlot -> renderEcharts4r 로 변경
  output$plot_graph1 <- renderEcharts4r({
    req(backtest_results())
    cum_return_and_Drawdown_plot(Perform_position_data = backtest_results()[[2]],
                                 input_date =input$analysis_end_date )
    
  })
  
  output$plot_graph2 <- renderPlot({
    plot(rnorm(100), col = "red")
  })
  
  #------------------ 다운로드 ------------------#
  output$download <- downloadHandler(
    filename = function() {
      paste0("backtest_results_", Sys.Date(), ".xlsx")
    },
    content = function(file) {
      req(backtest_results())
      write_xlsx(backtest_results(), file)
    }
  )
}

shinyApp(ui = ui, server = server, options = list(host = '0.0.0.0', port = 7601))
