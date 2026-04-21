
# historical_results_PA_GENERAL %>% 
#   filter(기준일자 == max(기준일자)) %>% pull(총손익기여도) %>% sum()
#Port_B_name <- "08K88_BM"
Brinson_result_table<- function(Brinson_res,Port_A_name, Port_B_name ){
  
  
  historical_results_PA_GENERAL<- Brinson_res$historical_results_PA_GENERAL
  
  historical_results_PA_GENERAL<- historical_results_PA_GENERAL %>% 
    mutate(cum_return = 초과누적수익률,
           총손익기여도 = 총손익기여도 * `BM누적수익률+1`) %>% 
    group_by(기준일자,자산군) %>% 
    # mutate(총손익기여도보정 = coalesce(보정인자2/sum(총손익기여도,na.rm = T),0)) %>% 
    mutate(총손익기여도보정 = coalesce(보정인자2/sum(총손익기여도,na.rm = T))) %>% 
    ungroup() 
  #mutate(총손익기여도 =총손익기여도 * 총손익기여도보정 )   
  
  
  historical_results_PA_GENERAL  %>%
    filter(기준일자 == max(기준일자))-> for_table_summary
  
  유동성및_기타총손익기여도<- for_table_summary %>% filter(sec_id=="유동성및기타") %>% pull(총손익기여도)
  if(length(유동성및_기타총손익기여도)==0){
    유동성및_기타총손익기여도 <- 0
  }
  
  for_table_summary<- bind_rows(
    for_table_summary %>% filter(자산군!="FX"),
    for_table_summary %>% filter(자산군=="FX")
  ) %>% 
    filter(자산군 != "유동성및기타")
  
  
  # 1) 데이터 전처리
  df_prepped <- for_table_summary %>% 
    filter(!is.na(자산군)) %>% 
    pivot_wider(id_cols    = 자산군,
                names_from  = name,
                values_from = 총손익기여도) %>% 
    bind_rows(tribble(~자산군 ,~Cross_effect ,~Allocation_effect ,~Security_selction_effect,
                      "유동성및기타",유동성및_기타총손익기여도,0,0)) %>% 
    #replace_na(across(where(is.numeric), 0)) %>% 
    rowwise() %>% 
    mutate(자산군별 = sum(c_across(where(is.numeric)), na.rm = TRUE)) %>% 
    ungroup() %>% 
    select(자산군,Allocation_effect,Security_selction_effect,Cross_effect ,자산군별) %>% 
    set_names(c("자산군","Allocation Effect","Security Selection Effect","Cross Effect","자산군별" ))
  
  # 숫자형 칼럼 벡터, 마지막 열 이름
  num_cols <- names(df_prepped)[-1]
  last_col <- tail(num_cols, 1)
  
  # 2) gt 테이블 생성 + 포맷 + 타이틀
  tbl <- df_prepped %>%
    gt(rowname_col = "자산군") %>%
    tab_header(
      title    = md(str_glue("**Performance Attribution ({Port_A_name} vs {Port_B_name})**")),
      subtitle = md(str_glue("분석기간 : {min(historical_results_PA_GENERAL$기준일자)} ~ {max(historical_results_PA_GENERAL$기준일자)}"))
      
    ) %>%
    # tab_spanner(
    #   label = md("**성과 요인별 기여도**"),
    #   columns = c("Allocation Effect", "Security Selection Effect", "Cross Effect")
    # ) %>%
    fmt_percent(columns = num_cols, decimals = 3) %>%
    grand_summary_rows(
      columns = num_cols,
      fns     = list(요인별 = ~sum(., na.rm = TRUE)),
      fmt     = ~fmt_percent(., decimals = 3)
    )
  
  
  tbl<- tbl %>%
    tab_style(
      style = cell_borders(
        sides  = "left",
        color  = "gray50",
        weight = px(2)
      ),
      locations = list(
        cells_column_labels(columns = last_col),
        cells_body(          columns = last_col),
        cells_grand_summary( columns = last_col)
      )
    )
  
  
  
  # 4) 양/음수 색상 적용 (body + grand summary)
  for (col in num_cols) {
    # body
    tbl <- tbl %>%
      tab_style(
        style     = cell_text(color="red"),
        locations = cells_body(columns=col, rows = !!sym(col) >  0)
      ) %>%
      tab_style(
        style     = cell_text(color="blue"),
        locations = cells_body(columns=col, rows = !!sym(col) <  0)
      )
    # grand summary
    sum_val <- sum(df_prepped[[col]], na.rm = TRUE)
    tbl <- tbl %>%
      tab_style(
        style     = cell_text(color = if (sum_val>0) "red" else if (sum_val<0) "blue" else "black"),
        locations = cells_grand_summary(columns = col)
      )
  }
  
  # 5) 마지막 정렬
  tbl <- tbl %>% cols_align(align="center", columns=everything())
  
  
  # (이전 코드 생략)
  
  tbl <- tbl %>%
    # ─── ➊ 오른쪽 마지막 열(헤더 + body) 굵은 글씨 ─────────────────
    tab_style(
      style = cell_text(weight = "bold"),
      locations = list(
        cells_column_labels(columns = last_col),
        cells_body(         columns = last_col)
      )
    ) %>%
    
    # ─── ➋ 맨 마지막(grand summary) 행 전체 굵은 글씨 ───────────────
    tab_style(
      style     = cell_text(weight = "bold"),
      locations = list(
        
        cells_grand_summary(columns = names(df_prepped))
      )
    ) %>%
    tab_style(
      style     = cell_text(weight = "bold", align = "center"),
      locations = cells_stub_grand_summary()
    ) %>%
    
    # ── 2) 합계 행(values) 굵은·가운데 정렬 ──────────────────
    tab_style(
      style     = cell_text(weight = "bold", align = "center"),
      locations = cells_grand_summary(columns = num_cols)
    ) %>% 
    tab_style(
      style = cell_fill(color = "gray95"),
      locations = list(
        #cells_column_labels(columns    = last_col),
        cells_body(         columns    = last_col),
        cells_grand_summary(columns    = num_cols)
      )
    )%>%
    # (3-1) 배경색 좀 더 진하게
    tab_style(
      style     = cell_fill(color = "yellow"),
      locations = cells_grand_summary(columns = last_col)
    ) %>% 
    # ➊ 테이블 레이아웃을 fixed로 고정 (폭이 자동으로 줄어들지 않음)
    # ──────────────────────────────────────────
    tab_options(
      table.layout = "fixed"
    ) %>%
    
    # ──────────────────────────────────────────
    # ➋ 헤더에 NBSP 적용 (줄바꿈 방지)
    # ──────────────────────────────────────────
    cols_label(
      `Cross Effect`             = "Cross\u00A0Effect",
      `Allocation Effect`        = "Allocation\u00A0Effect",
      `Security Selection Effect`= "Security\u00A0Selection\u00A0Effect",
      `자산군별`                  = "자산군별"
    ) %>% 
    # ─── ➌ effect 관련 3개 열 너비를 px 단위로 동일하게 설정 ─────────
    cols_width(
      contains("Effect")~ px(150)
    ) %>% 
    # ─── ➍ (이전까지 하셨던 +/– 색상, 분리선, 정렬 등) ─────────────
    cols_align(align="center", columns=everything()) 
  
  
  # 3. gt 테이블에 각주로 추가 (기존과 동일)
  return(list("HTML"=tbl, 
              "DF" = bind_rows(
                df_prepped,
                df_prepped %>% reframe(across(where(is.numeric),.fns = ~sum(.x)))
              ) %>% 
                mutate(자산군 = coalesce(자산군,"요인별")) ))
  
}


# 표 1 구성 (complete 안전 버전)
brinson_tbl_return_summary <- function(AP_roll_portfolio_res, BM_roll_portfolio_res,
                                       Port_A_name, Port_B_name, mapping_method, func = "기여",FX_split) {
  
  df_top <- AP_roll_portfolio_res$자산군별_기여수익률 %>%
    dplyr::mutate(구분 = Port_A_name) %>%
    dplyr::bind_rows(BM_roll_portfolio_res$자산군별_기여수익률 %>% dplyr::mutate(구분 = Port_B_name)) %>%
    dplyr::filter(기준일자 == max(기준일자)) %>%
    dplyr::select(구분, cum_return) %>%
    dplyr::distinct() %>%
    tidyr::pivot_wider(
      id_cols = c(),
      names_from = 구분, values_from = cum_return,
      values_fill = 0
    ) %>%
    dplyr::mutate(구분 = "포트폴리오")
  
  if(func =="기여"){
    
    df_body <- AP_roll_portfolio_res$자산군별_기여수익률 %>%
      dplyr::mutate(구분 = Port_A_name) %>%
      dplyr::bind_rows(BM_roll_portfolio_res$자산군별_기여수익률 %>% dplyr::mutate(구분 = Port_B_name)) %>%
      dplyr::filter(기준일자 == max(기준일자)) %>%
      tidyr::pivot_wider(
        id_cols = c(자산군),
        names_from = 구분, values_from = 총손익기여도,
        values_fill = 0
      ) %>%
      dplyr::rename(구분 = 자산군)
  }else{
    
    df_body <- AP_roll_portfolio_res$normalized_performance_by_자산군 %>%
      dplyr::mutate(구분 = Port_A_name) %>%
      dplyr::bind_rows(BM_roll_portfolio_res$normalized_performance_by_자산군 %>% dplyr::mutate(구분 = Port_B_name)) %>%
      dplyr::filter(기준일자 == max(기준일자)) %>%
      tidyr::pivot_wider(
        id_cols = c( 자산군),
        names_from = 구분, values_from = 누적수익률,
        values_fill = 0
      ) %>%
      dplyr::rename(구분 = 자산군)
  }
  
  
  table_brinson_left_top <- dplyr::bind_rows(df_top, df_body) 
  
  for_reordering_classification <- universe_non_derivative_table %>%
    dplyr::filter(classification_method == mapping_method, !is.na(classification)) %>%
    dplyr::pull(classification) %>% unique()
  
  korean_items<- sort(for_reordering_classification[stringr::str_detect(for_reordering_classification, "[가-힣]")])
  non_korean_items <- sort(for_reordering_classification[!stringr::str_detect(for_reordering_classification, "[가-힣]")])
  sorted_data <- c(
    "포트폴리오",
    korean_items[korean_items!="유동성및기타"],
    non_korean_items,
    "유동성및기타"
  )
  
  nm <- unique(c(Port_A_name, Port_B_name))
  for (n in nm) {
    if (!n %in% names(table_brinson_left_top)) {
      table_brinson_left_top[[n]] <- 0
    }
  }
  fill_list <- rlang::set_names(rep(list(0), length(nm)), nm)
  
  table_brinson_left_top_sorted <- table_brinson_left_top %>%
    dplyr::mutate(구분 = dplyr::coalesce(구분, "포트폴리오")) %>%
    #tidyr::complete(구분 = sorted_data, fill = fill_list) %>%
    dplyr::mutate(
      
      구분 = factor(구분, levels = sorted_data)
    ) %>%
    dplyr::arrange(구분) %>% 
    mutate(초과수익률 =.[[1]]-.[[2]])
  if(FX_split != TRUE){
    table_brinson_left_top_sorted <- table_brinson_left_top_sorted %>% filter(구분 != "FX") 
  }
  return(table_brinson_left_top_sorted)
}


#Port_A_name <- AP_roll_portfolio$backtest_result$portfolio_return$Portfolio[1]
#Port_B_name <- BM_roll_portfolio$backtest_result$portfolio_return$Portfolio[1]

brinson_tbl_weight_summary <- function(AP_roll_portfolio_res, BM_roll_portfolio_res,
                                       Port_A_name, Port_B_name, mapping_method,FX_split) {
  
  
  df_top_weight <- AP_roll_portfolio_res$자산군별_비중 %>%
    mutate(구분 = Port_A_name) %>%
    bind_rows(BM_roll_portfolio_res$자산군별_비중 %>% mutate(구분 = Port_B_name)) %>%
    filter(기준일자 == max(기준일자)) %>%
    distinct() %>%
    pivot_wider(
      id_cols = c(기준일자, 자산군),
      names_from = 구분, values_from = weight_순자산,
      values_fill = 0
    ) %>% 
    rename(구분 = 자산군) 
  
  
  table_brinson_left_top <- df_top_weight
  
  # 3) 정렬 기준 벡터
  for_reordering_classification <- universe_non_derivative_table %>%
    filter(classification_method == mapping_method, !is.na(classification)) %>%
    pull(classification) %>% unique()
  
  
  korean_items<- sort(for_reordering_classification[stringr::str_detect(for_reordering_classification, "[가-힣]")])
  non_korean_items <- sort(for_reordering_classification[!stringr::str_detect(for_reordering_classification, "[가-힣]")])
  sorted_data <- c(
    "포트폴리오",
    korean_items[korean_items!="유동성및기타"],
    non_korean_items,
    "유동성및기타"
  )
  
  # 4) 동적 컬럼명 보장 + fill 리스트 생성
  nm <- unique(c(Port_A_name, Port_B_name))
  for (n in nm) {
    if (!n %in% names(table_brinson_left_top)) {
      table_brinson_left_top[[n]] <- 0
    }
  }
  table_brinson_left_top_sorted <- table_brinson_left_top %>%
    
    mutate(구분 = factor(구분, levels = sorted_data)) %>%
    arrange(구분) %>% 
    mutate(`Active Weight` =.[[3]]-.[[4]])
  
  
  if(FX_split != TRUE){
    table_brinson_left_top_sorted<- table_brinson_left_top_sorted %>% filter(구분 != "FX")
  }
  
  return(table_brinson_left_top_sorted)
}

brinson_plot_port_return <- function(AP_roll_portfolio_res, BM_roll_portfolio_res,
                                     Port_A_name, Port_B_name,mapping_method) {
  
  
  
  original_df_normalized <- bind_rows(
    AP_roll_portfolio_res$normalized_performance_by_자산군 %>% mutate(구분 = Port_A_name),
    BM_roll_portfolio_res$normalized_performance_by_자산군 %>% mutate(구분 = Port_B_name)
  )
  
  original_df_기여<- bind_rows(
    AP_roll_portfolio_res$자산군별_기여수익률 %>% mutate(구분 = Port_A_name),
    BM_roll_portfolio_res$자산군별_기여수익률 %>% mutate(구분 = Port_B_name)
  ) %>% 
    select(기준일자,분석시작일,분석종료일,자산군,총손익기여도,구분)
  
  
  # 3) 정렬 기준 벡터
  for_reordering_classification <- universe_non_derivative_table %>%
    filter(classification_method == mapping_method, !is.na(classification)) %>%
    pull(classification) %>% unique()
  
  
  korean_items<- sort(for_reordering_classification[stringr::str_detect(for_reordering_classification, "[가-힣]")])
  non_korean_items <- sort(for_reordering_classification[!stringr::str_detect(for_reordering_classification, "[가-힣]")])
  sorted_data <- c(
    "포트폴리오",
    korean_items[korean_items!="유동성및기타"],
    non_korean_items,
    "유동성및기타"
  )
  # 1. 초과 성과 계산을 위한 데이터 준비
  # 각 날짜, 자산군별로 AP와 BM의 누적수익률을 나란히 둡니다.
  excess_perf_df <- 
    bind_rows(
      original_df_normalized %>%
        pivot_wider(
          id_cols = c(기준일자, 자산군),
          names_from = 구분,
          values_from = 누적수익률
        ) %>%
        bind_rows(
          AP_roll_portfolio_res$sec별_기여수익률 %>% select(기준일자,cum_return) %>% distinct() %>% 
            set_names(c("기준일자",Port_A_name)) %>% 
            left_join(BM_roll_portfolio_res$sec별_기여수익률 %>% select(기준일자,cum_return) %>% distinct() %>% 
                        set_names(c("기준일자",Port_B_name))) %>% 
            mutate( 자산군 = "포트폴리오")
        ) %>% 
        mutate(설명 = "Normalized 수익률"),
      original_df_기여 %>%
        pivot_wider(
          id_cols = c(기준일자, 자산군),
          names_from = 구분,
          values_from = 총손익기여도
        ) %>%
        bind_rows(
          AP_roll_portfolio_res$sec별_기여수익률 %>% select(기준일자,cum_return) %>% distinct() %>% 
            set_names(c("기준일자",Port_A_name)) %>% 
            left_join(BM_roll_portfolio_res$sec별_기여수익률 %>% select(기준일자,cum_return) %>% distinct() %>% 
                        set_names(c("기준일자",Port_B_name))) %>% 
            mutate( 자산군 = "포트폴리오")
        ) %>% 
        mutate(설명 = "기여 수익률")
    ) %>% 
    
    mutate(across(.cols= where(is.numeric), .f = ~replace_na(.x,0))) %>% 
    mutate(
      초과수익률 = .[[3]] - .[[4]]
    ) %>%
    mutate(자산군  = factor(자산군 , levels = sorted_data)) %>%
    arrange(자산군 ) 
  
  
  
  
  # 시작일 전일에 0 값 채워넣기
  plot_data<- excess_perf_df %>% 
    bind_rows(
      excess_perf_df %>% 
        group_by(자산군,설명) %>% 
        reframe(기준일자 = min(기준일자)-days(1),
                across(where(is.numeric),.fns = ~ 0))
    ) %>% 
    mutate(자산군  = factor(자산군 , levels = sorted_data)) %>%
    arrange(기준일자,자산군 ) 
  
  
  return(plot_data)
}
# plot_data %>% 
#   filter(자산군 == "FX")->filtered_plot_data
#plot_data->filtered_plot_data
brinson_plot_port_return_echarts4r<- function(filtered_plot_data){
  
  
  # 1. 사용할 컬럼 이름을 변수에 명시적으로 저장합니다.
  ap_col_name <- names(filtered_plot_data)[3] # "07G04_BM"
  bm_col_name <- names(filtered_plot_data)[4] # "08K88_BM"
  
  # 2. e_charts 파이프라인을 구성합니다.
  
  filtered_plot_data %>% 
    arrange(기준일자) %>% 
    group_by(설명) %>% 
    e_charts(기준일자, timeline = TRUE) %>%
    e_area(초과수익률, name = "Excess Return", showSymbol = FALSE) %>% 
    e_line_(ap_col_name, name = ap_col_name, showSymbol = FALSE) %>% 
    e_line_(bm_col_name, name = bm_col_name, showSymbol = FALSE) %>% 
    
    e_x_axis(min = min(filtered_plot_data$기준일자) - days(1),
             max = max(filtered_plot_data$기준일자) + days(1)) %>%
    e_y_axis(formatter = e_axis_formatter("percent", digits = 3)) %>%
    e_tooltip(
      trigger = "axis",
      axisPointer = list(type = "cross"),
      formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 3)
    ) %>% 
    
    # 🔹 제목을 맨 위에 고정 + 패딩으로 하단 여백 확보
    e_title(
      str_glue("{filtered_plot_data$자산군[1]} 수익률 비교 : {ap_col_name} vs {bm_col_name} ( {min(unique(filtered_plot_data$기준일자)[-1])} ~ {max(unique(filtered_plot_data$기준일자)[-1])} )"),
      top = 0,
      padding = c(10, 12, 8, 12),              # 상/우/하/좌 (하단 8px 여백)
      textStyle = list(fontSize = 16, lineHeight = 22)
    ) %>% 
    
    # 🔹 레전드를 타이틀보다 한참 아래로 + 스크롤
    e_legend(
      type = "scroll",
      top = 58,                                 # 타이틀과 간격 (픽셀값, 필요시 더 키우세요)
      left = "center",
      padding = c(4, 8, 4, 8),
      itemGap = 12                              # 항목 간 간격
    ) %>%
    
    # 🔹 플롯 영역도 위쪽 여백을 더 넓힘 (타이틀+레전드 공간 확보)
    e_grid(top = 110, bottom = 70) %>%
    
    
    e_timeline_opts(
      # ✅ 타임라인 전체 길이를 줄여 간격을 촘촘하게
      left = "center",
      width = 420,         # 예: 420 처럼 px 고정해도 되고 "50%"도 가능
      bottom = 0, height = 36,
      axisType = "category",
      
      label = list(
        show = TRUE,
        
        color = '#6b7280',
        fontSize = 11,
        padding = 20
      ),
      emphasis = list(
        label = list(color = '#111827', fontWeight = 'bold', fontSize = 12)
      ),
      
      checkpointStyle = list(
        symbol = "pin",
        symbolSize = 20,     # 핀은 조금 작게
        color = '#3b82f6', borderColor = '#ffffff', borderWidth = 2
      ),
      
      # 연결선은 은은하게 유지
      lineStyle = list(color = '#d1d5db', width = 2, opacity = 0.85),
      
      # 진행선은 헷갈리면 숨김
      progress = list(
        lineStyle = list(color = "transparent"),
        itemStyle = list(color = "transparent")
      ),
      
      itemStyle = list(color = '#cbd5e1'),
      controlStyle = list(showPlayBtn = FALSE)
    ) %>% e_toolbox_feature(feature = "saveAsImage",title = "이미지로 저장")
  
  
}


brinson_plot_port_weight <- function(AP_roll_portfolio_res, BM_roll_portfolio_res,
                                     Port_A_name, Port_B_name,mapping_method) {
  
  
  
  original_df <- bind_rows(
    AP_roll_portfolio_res$자산군별_비중 %>% mutate(구분 = Port_A_name),
    BM_roll_portfolio_res$자산군별_비중 %>% mutate(구분 = Port_B_name)
  ) %>% 
    pivot_longer(cols = contains("weight"),names_to = "설명",values_to = "비중")
  
  
  
  # 3) 정렬 기준 벡터
  for_reordering_classification <- universe_non_derivative_table %>%
    filter(classification_method == mapping_method, !is.na(classification)) %>%
    pull(classification) %>% unique()
  
  
  korean_items<- sort(for_reordering_classification[stringr::str_detect(for_reordering_classification, "[가-힣]")])
  non_korean_items <- sort(for_reordering_classification[!stringr::str_detect(for_reordering_classification, "[가-힣]")])
  sorted_data <- c(
    "포트폴리오",
    korean_items[korean_items!="유동성및기타"],
    non_korean_items,
    "유동성및기타"
  )
  # 1. 초과 성과 계산을 위한 데이터 준비
  # 각 날짜, 자산군별로 AP와 BM의 누적수익률을 나란히 둡니다.
  excess_weight_df <- 
    
    original_df %>%
    pivot_wider(
      id_cols = c(기준일자, 자산군,설명),
      names_from = 구분,
      values_from = 비중
    ) %>% 
    mutate(across(.cols= where(is.numeric), .f = ~replace_na(.x,0))) %>% 
    mutate(`Active Weight` = .[[4]] - .[[5]]) %>%
    mutate(자산군  = factor(자산군 , levels = sorted_data)) %>%
    arrange(자산군 ) 
  
  # 시작일 전일에 0 값 채워넣기
  plot_data<- excess_weight_df %>% 
    mutate(설명 = case_when(설명 == "weight_순자산" ~ "순자산 비중",
                          설명 == "weight_PA(T)" ~ "평가자산 비중"))
  
  
  return(plot_data)
  
}
# plot_data %>%
#    filter(자산군 == "FX")->filtered_plot_data

brinson_plot_port_weight_echarts4r<- function(filtered_plot_data){
  
  
  # 1. 사용할 컬럼 이름을 변수에 명시적으로 저장합니다.
  ap_col_name <- names(filtered_plot_data)[4] # "07G04_BM"
  bm_col_name <- names(filtered_plot_data)[5] # "08K88_BM"
  
  # 2. e_charts 파이프라인을 구성합니다.
  
  filtered_plot_data %>% 
    arrange(기준일자) %>% 
    group_by(설명) %>% 
    e_charts(기준일자, timeline = TRUE) %>%
    e_area(`Active Weight`, name = "Active Weight", showSymbol = FALSE) %>% 
    e_line_(ap_col_name, name = ap_col_name, showSymbol = FALSE) %>% 
    e_line_(bm_col_name, name = bm_col_name, showSymbol = FALSE) %>% 
    e_x_axis(min = min(filtered_plot_data$기준일자) - days(1),
             max = max(filtered_plot_data$기준일자) + days(1)) %>%
    e_y_axis(formatter = e_axis_formatter("percent", digits = 3)) %>%
    e_tooltip(
      trigger = "axis",
      axisPointer = list(type = "cross"),
      formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 3)
    ) %>% 
    
    # 🔹 제목을 맨 위에 고정 + 패딩으로 하단 여백 확보
    e_title(
      str_glue("{filtered_plot_data$자산군[1]} 비중 비교 : {ap_col_name} vs {bm_col_name} ( {min(unique(filtered_plot_data$기준일자))} ~ {max(unique(filtered_plot_data$기준일자))} )"),
      top = 0,
      padding = c(10, 12, 8, 12),              # 상/우/하/좌 (하단 8px 여백)
      textStyle = list(fontSize = 16, lineHeight = 22)
    ) %>% 
    
    # 🔹 레전드를 타이틀보다 한참 아래로 + 스크롤
    e_legend(
      type = "scroll",
      top = 58,                                 # 타이틀과 간격 (픽셀값, 필요시 더 키우세요)
      left = "center",
      padding = c(4, 8, 4, 8),
      itemGap = 12                              # 항목 간 간격
    ) %>%
    
    # 🔹 플롯 영역도 위쪽 여백을 더 넓힘 (타이틀+레전드 공간 확보)
    e_grid(top = 110, bottom = 70) %>%
    
    
    e_timeline_opts(
      # ✅ 타임라인 전체 길이를 줄여 간격을 촘촘하게
      left = "center",
      width = 420,         # 예: 420 처럼 px 고정해도 되고 "50%"도 가능
      bottom = 0, height = 36,
      axisType = "category",
      
      label = list(
        show = TRUE,
        
        color = '#6b7280',
        fontSize = 11,
        padding = 20
      ),
      emphasis = list(
        label = list(color = '#111827', fontWeight = 'bold', fontSize = 12)
      ),
      
      checkpointStyle = list(
        symbol = "pin",
        symbolSize = 20,     # 핀은 조금 작게
        color = '#3b82f6', borderColor = '#ffffff', borderWidth = 2
      ),
      
      # 연결선은 은은하게 유지
      lineStyle = list(color = '#d1d5db', width = 2, opacity = 0.85),
      
      # 진행선은 헷갈리면 숨김
      progress = list(
        lineStyle = list(color = "transparent"),
        itemStyle = list(color = "transparent")
      ),
      
      itemStyle = list(color = '#cbd5e1'),
      controlStyle = list(showPlayBtn = FALSE)
    ) %>% e_toolbox_feature(feature = "saveAsImage",title = "이미지로 저장")
  
  
}

# plot_data %>% view()
# filtered_plot_data %>%brinson_plot_port_return_echarts4r()


brinson_plot_port_excess_factor <- function(Brinson_res,mapping_method) {
  
  #mapping_method <- "방법1"
  # 3) 정렬 기준 벡터
  for_reordering_classification <- universe_non_derivative_table %>%
    filter(classification_method == mapping_method, !is.na(classification)) %>%
    pull(classification) %>% unique()
  
  
  korean_items<- sort(for_reordering_classification[stringr::str_detect(for_reordering_classification, "[가-힣]")])
  non_korean_items <- sort(for_reordering_classification[!stringr::str_detect(for_reordering_classification, "[가-힣]")])
  sorted_data <- c(
    "포트폴리오",
    korean_items[korean_items!="유동성및기타"],
    non_korean_items,
    "유동성및기타"
  )
  
  historical_results_PA_GENERAL<- Brinson_res$historical_results_PA_GENERAL
  
  historical_results_PA_GENERAL<- historical_results_PA_GENERAL %>% 
    mutate(cum_return = 초과누적수익률,
           총손익기여도 = 총손익기여도 * `BM누적수익률+1`) %>% 
    group_by(기준일자,자산군) %>% 
    # mutate(총손익기여도보정 = coalesce(보정인자2/sum(총손익기여도,na.rm = T),0)) %>% 
    mutate(총손익기여도보정 = coalesce(보정인자2/sum(총손익기여도,na.rm = T))) %>% 
    ungroup() 
  
  PA_자산군별 <- historical_results_PA_GENERAL %>% 
    mutate(자산군 = coalesce(자산군,"유동성및기타"),
           name = coalesce(name, "Cross_effect")) %>% 
    group_by(기준일자,자산군) %>% 
    reframe(총손익기여도 = sum(총손익기여도))  %>% 
    bind_rows(historical_results_PA_GENERAL %>% 
                select(기준일자,총손익기여도 = cum_return) %>% distinct() %>% 
                mutate(자산군 = "초과수익률")
    ) %>% 
    mutate(자산군  = factor(자산군 , levels = c("초과수익률",sorted_data))) %>%
    arrange(자산군 ) 
  
  
  PA_요인별 <- historical_results_PA_GENERAL %>% 
    select(기준일자,초과수익률 = cum_return) %>% distinct() %>% 
    left_join(historical_results_PA_GENERAL %>% 
                mutate(자산군 = coalesce(자산군,"유동성및기타"),
                       name = coalesce(name, "Cross_effect")) %>% 
                group_by(기준일자,name) %>% 
                reframe(총손익기여도 = sum(총손익기여도)) %>% 
                mutate(name  = factor(name , levels =c("Cross_effect","Allocation_effect","Security_selction_effect") )) %>%
                arrange(name ) %>% 
                pivot_wider(id_cols = 기준일자,names_from = name,values_from = 총손익기여도))  
  
  PA_자산군별<- PA_자산군별 %>% 
    bind_rows(PA_자산군별 %>% 
                group_by(자산군) %>% 
                filter(row_number()==1) %>% 
                mutate(across(where(is.numeric),.fns = ~0)) %>% 
                mutate(기준일자 =기준일자 -days(1) ) %>% 
                ungroup()) %>% 
    arrange(기준일자)
  
  PA_요인별<- PA_요인별 %>% 
    bind_rows(PA_요인별 %>% 
                filter(row_number()==1) %>% 
                mutate(across(where(is.numeric),.fns = ~0)) %>% 
                mutate(기준일자 =기준일자 -days(1) )) %>% 
    arrange(기준일자)
  
  # 시작일 전일에 0 값 채워넣기
  plot_data<- list("자산군별" = PA_자산군별,
                   "요인별" = PA_요인별)
  
  
  return(plot_data)
  
}


# 자산군별 --------------------------------------------------------------------
brinson_plot_port_excess_자산군별_echarts4r <- function(plot_data_자산군별,ap_col_name,bm_col_name){
  
  # 1. 데이터를 Long-form으로 변환하고 시각화
  plot_data_자산군별 %>% 
    arrange(기준일자) %>% 
    rename(수익률 = 총손익기여도) %>% 
    # 2. 새로 만든 '구분' 열로 그룹핑합니다.
    group_by(자산군) %>%
    # 3. e_charts로 시각화합니다.
    e_charts(기준일자) %>%
    e_line(
      수익률,              # y축 값
      showSymbol = FALSE   # 점(symbol)을 표시하지 않음
    ) %>%
    e_x_axis(min = min(plot_data_자산군별$기준일자) - days(1), max = max(plot_data_자산군별$기준일자) + days(1)) %>%
    e_y_axis(formatter = e_axis_formatter("percent", digits = 3)) %>%
    e_tooltip(
      trigger = "axis",
      axisPointer = list(type = "cross"),
      formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 3)
    ) %>%
    # 🔹 제목을 맨 위에 고정 + 패딩으로 하단 여백 확보
    e_title(
      str_glue("자산군별 성과분해 : {ap_col_name} vs {bm_col_name} ( {min(unique(plot_data_자산군별$기준일자)[-1])} ~ {max(unique(plot_data_자산군별$기준일자)[-1])} )"),
      top = 0,
      padding = c(10, 12, 8, 12),              # 상/우/하/좌 (하단 8px 여백)
      textStyle = list(fontSize = 16, lineHeight = 22)
    ) %>% 
    e_legend(
      type = "scroll",
      top = 30,                                 # 타이틀과 간격 (픽셀값, 필요시 더 키우세요)
      left = "center",
      padding = c(4, 8, 4, 8),
      itemGap = 12) %>% # 항목 간 간격 
    e_toolbox_feature(feature = "saveAsImage")
  
}


# 요인별 ---------------------------------------------------------------------
brinson_plot_port_excess_요인별_echarts4r <- function(plot_data_요인별,ap_col_name,bm_col_name){
  #plot_data_요인별<- plot_data$요인별
  plot_data_요인별 %>% 
    arrange(기준일자) %>% 
    e_charts(기준일자) %>% 
    e_line(초과수익률 , name = "초과수익률 ", showSymbol = FALSE) %>%
    e_line(Cross_effect , name = "Cross Effect", showSymbol = FALSE) %>%
    e_line(Allocation_effect , name = "Allocation Effect", showSymbol = FALSE) %>%
    e_line(Security_selction_effect, name = "Security Selction Effect", showSymbol = FALSE) %>%
    e_x_axis(min = min(plot_data_요인별$기준일자) - days(1), max = max(plot_data_요인별$기준일자) + days(1)) %>%
    e_y_axis(formatter = e_axis_formatter("percent", digits = 3)) %>%
    e_tooltip(
      trigger = "axis",
      axisPointer = list(type = "cross"),
      formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 3)
    ) %>% 
    e_title(str_glue("요인별 성과분해 : {ap_col_name} vs {bm_col_name} ( {min(unique(plot_data_요인별$기준일자)[-1])} ~ {max(unique(plot_data_요인별$기준일자)[-1])} )"),
            top = 0,
            padding = c(10, 12, 8, 12),              # 상/우/하/좌 (하단 8px 여백)
            textStyle = list(fontSize = 16, lineHeight = 22)
    ) %>% 
    # 🔹 레전드를 타이틀보다 한참 아래로 + 스크롤
    e_legend(
      type = "scroll",
      top = 30,                                 # 타이틀과 간격 (픽셀값, 필요시 더 키우세요)
      left = "center",
      padding = c(4, 8, 4, 8),
      itemGap = 12) %>% # 항목 간 간격 
    e_toolbox_feature(feature = "saveAsImage")
}

