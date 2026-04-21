performanceUI <- function(id) {
  ns <- NS(id)
  tagList(
    tags$head(
      tags$style(HTML("
        /* 고정된 사이드바 스타일 */
        #fixedSidebar {
          position: fixed;  /* 스크롤 시에도 고정 */
          top: 150px;       /* 페이지 상단과의 간격 */
          left: 0;         /* 페이지 왼쪽과 붙여 배치 */
          bottom: 0;       /* 하단까지 늘어나도록 설정 */
          overflow-y: auto; /* 내용이 많을 경우 스크롤 허용 */
          width: 250px;    /* 사이드바의 너비 */
          padding: 10px;   /* 내용과 테두리 사이의 간격 */
          z-index: 1000;   /* 다른 요소들 위에 표시되도록 z-index 설정 */
        }
        
        /* 고정 사이드바와 겹치지 않도록 메인 패널의 마진 조정 */
        .main-container {
          margin-left: 270px; /* 고정된 사이드바의 너비 + 여백에 맞춤 */
        }
      "))
    ),
    div(id="fixedSidebar",
        # 사이드바의 내용은 여기에 위치
        selectInput(ns("fromWhenInput"), "기간 선택:", 
                    choices = c("YTD", "ITD", "최근 1년",
                                "최근 1주","최근 1개월","최근 3개월","최근 6개월"), 
                    selected = "YTD"),
        checkboxGroupInput(ns("selectedPlots"), "보고 싶은 분석 선택:",
                           choices = list("수익률" = "performance",
                                          "누적 수익률 추이" = "performance_historical",
                                          "변동성" = "volatility",
                                          "Return-to-Risk" = "riskAdjusted",
                                          "추적오차" = "trackingError",
                                          "정보비율" = "informationRatio",
                                          "샤프비율" = "sharpeRatio"),
                           selected = "performance"),
        # Excel 파일 다운로드 버튼 추가
        downloadButton(ns("downloadExcel"), "Download Excel")
    ),
    div(class="main-container",
        # 여기에 메인 패널의 내용을 위치
        uiOutput(ns("plotsOutput"))  # 선택된 플롯들을 보여줄 UI Output
    )
    # 기타 UI 요소들...
  )
}
