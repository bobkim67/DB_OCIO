library(reactable)
library(tidyverse)
library(scales)
#res_list_portfolio <- AP_roll_portfolio_res
single_port_table_summary <- function(res_list_portfolio,mapping_method
                                      #Portfolio_name
){
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
  
  roll_over_going_item <- res_list_portfolio$sec별_기여수익률 %>% 
    group_by(기준일자,ITEM_NM) %>% 
    filter(n()>1) %>% pull(ITEM_NM) %>% unique()
  
  # res_list_portfolio$sec별_기여수익률 %>% 
  #   group_by(기준일자,ITEM_NM) %>% 
  #   filter(n()>1) %>% 
  #   group_by(sec_id) %>% 
  #   reframe(분석시작일,분석종료일) %>% distinct()
  
  if(length(roll_over_going_item)!=0){
    
    res_list_portfolio$sec별_기여수익률<- bind_rows(
      res_list_portfolio$sec별_기여수익률 %>% 
        filter(ITEM_NM %in% roll_over_going_item) %>% 
        group_by(기준일자,자산군,ITEM_NM) %>% 
        reframe(sec_id = sec_id[n()],
                분석시작일 = min(분석시작일,na.rm = TRUE),
                분석종료일 = max(분석종료일,na.rm = TRUE),
                자산군 = 자산군[1],
                cum_return = cum_return[1],
                총손익기여도 = sum(총손익기여도),
                총손익금액 = sum(총손익금액)) ,
      res_list_portfolio$sec별_기여수익률 %>% 
        filter(!(ITEM_NM %in% roll_over_going_item))
    )
    
    res_list_portfolio$normalized_performance_by_sec %>% 
      filter(ITEM_NM %in% roll_over_going_item) %>% 
      group_by(기준일자,자산군,ITEM_NM) %>% 
      reframe(sec_id = sec_id[n()],
              분석시작일 = min(분석시작일),
              분석종료일 = max(분석종료일),
              자산군 = 자산군[1],
              누적수익률 = prod(누적수익률+1)-1) %>% tail()
    
    res_list_portfolio$normalized_performance_by_sec <- bind_rows(
      res_list_portfolio$normalized_performance_by_sec %>% 
        filter(ITEM_NM %in% roll_over_going_item) %>% 
        group_by(기준일자,자산군,ITEM_NM) %>% 
        reframe(sec_id = sec_id[n()],
                분석시작일 = min(분석시작일),
                분석종료일 = max(분석종료일),
                자산군 = 자산군[1],
                누적수익률 = prod(누적수익률+1)-1)  ,
      res_list_portfolio$normalized_performance_by_sec %>% 
        filter(!(ITEM_NM %in% roll_over_going_item))
    )
    
    res_list_portfolio$sec별_비중 <- bind_rows(
      res_list_portfolio$sec별_비중 %>% 
        filter(ITEM_NM %in% roll_over_going_item) %>% 
        group_by(자산군,ITEM_NM) %>% 
        mutate(sec_id = sec_id[n()]) %>% 
        ungroup(),
      res_list_portfolio$sec별_비중 %>% 
        filter(!(ITEM_NM %in% roll_over_going_item)) 
      
    ) 
  }
  
  
  # res_list_portfolio$sec별_비중 %>%
  #   group_by(sec_id) %>%
  #   mutate(순자산비중_시작 = first(weight_순자산), .before = weight_순자산) %>% view()
  
  #table_data_sec %>% view()
  
  analysis_start_date<- min(res_list_portfolio$자산군별_비중$기준일자)
  analysis_end_date<- max(res_list_portfolio$sec별_기여수익률$기준일자)
  
  table_data_sec <- 
    res_list_portfolio$sec별_기여수익률 %>%
    left_join(
      res_list_portfolio$normalized_performance_by_sec %>%
        select(기준일자, sec_id, 개별수익률 = 누적수익률),
      by = join_by(기준일자, sec_id)
    ) %>%
    left_join(
      res_list_portfolio$sec별_비중 %>%
        select(기준일자, sec_id,  weight_순자산, `weight_PA(T)`) ,
      by = join_by(기준일자, sec_id)
    ) %>% 
    complete(기준일자, sec_id, 
             fill = list(weight_순자산 = 0, `weight_PA(T)` = 0)) %>% 
    group_by(sec_id) %>%
    mutate(across(where(is.numeric), .fns = ~replace_na(.x,0))) %>% 
    mutate(
      자산군 = first(자산군[!is.na(자산군)]),
      ITEM_NM = last(ITEM_NM[!is.na(ITEM_NM)]),
      분석시작일 = first(분석시작일[!is.na(분석시작일)]),
      분석종료일 = first(분석종료일[!is.na(분석종료일)])
    ) %>% 
    mutate(순자산비중_시작 = weight_순자산[1])  %>% 
    ungroup() %>% 
    mutate(across(.cols = c("weight_순자산","weight_PA(T)"),
                  .fns = ~if_else(자산군=="유동성및기타"& ITEM_NM== "유동성및기타" , .x, replace_na(.x,0)))) %>% 
    select(
      자산군, 기준일자, 분석시작일, 분석종료일,
      종목코드 = sec_id, 종목명 = ITEM_NM,
      개별수익률, 기여수익률 = 총손익기여도,
      순자산비중_시작, 순자산비중_종료 = weight_순자산,
      평가자산비중 = `weight_PA(T)`
    ) 
  #mutate(across(.cols = contains("비중"),.fns = ~replace_na(.x,0))) %>% view()
  #filter(자산군 != "유동성및기타")
  
  table_data_classification <- res_list_portfolio$자산군별_기여수익률 %>%
    left_join(
      res_list_portfolio$normalized_performance_by_자산군 %>%
        select(기준일자, 자산군, 개별수익률 = 누적수익률), by = join_by(자산군, 기준일자)
    ) %>%
    left_join(
      res_list_portfolio$자산군별_비중 %>%
        complete(기준일자, 자산군, 
                 # 2. 새로 생성된 행의 특정 컬럼 값을 채워줍니다.
                 #    weight_순자산이 비어있는(NA) 경우 0으로 채웁니다.
                 #    다른 가중치(weight_PA(T))도 0으로 채우는 것이 일반적입니다.
                 fill = list(weight_순자산 = 0, `weight_PA(T)` = 0)) %>% 
        group_by(자산군) %>%
        mutate(순자산비중_시작 = weight_순자산[1])  %>% 
        ungroup() %>% 
        select(기준일자, 자산군, 순자산비중_시작, weight_순자산, `weight_PA(T)`) 
    ) %>%
    select(
      자산군, 기준일자, 분석시작일, 분석종료일,
      개별수익률, 기여수익률 = 총손익기여도,
      순자산비중_시작, 순자산비중_종료 = weight_순자산,
      평가자산비중 = `weight_PA(T)`
    )
  
  
  
  
  
  res_list_portfolio$sec별_기여수익률 %>% 
    mutate(분석시작일 = min(분석시작일),
           분석종료일 = max(분석종료일)) %>% 
    select(기준일자,분석시작일,분석종료일,개별수익률 = cum_return, 기여수익률 = cum_return) %>% 
    distinct() %>% 
    mutate(자산군 = "포트폴리오") %>% 
    left_join(
      res_list_portfolio$자산군별_비중 %>%
        group_by(기준일자) %>%
        reframe(순자산비중_시작 = sum(weight_순자산[자산군!="FX"]),
                순자산비중_종료 = sum(weight_순자산[자산군!="FX"])) ,by = join_by(기준일자)
    ) ->table_total
  
  
  raw_data <- bind_rows(table_total,table_data_classification, table_data_sec) %>%
    arrange(자산군) %>%
    mutate(across(.cols = contains("순자산"), .fns = ~replace_na(.x,0))) %>% 
    mutate(비중변화 = 순자산비중_종료 - 순자산비중_시작) %>% 
    mutate( 자산군 = factor(자산군, levels = sorted_data)) %>%
    dplyr::arrange(자산군)
  
  
  
  # --- 2. 테이블 렌더링을 위한 최종 데이터 가공 ---
  filtered_data <- raw_data %>%
    filter(기준일자 == max(기준일자))
  #filtered_data %>% view()
  date_info <- filtered_data %>% 
    select(분석시작일, 분석종료일, 기준일자) %>% 
    reframe(across(everything(),.fns = ~min(.x,na.rm = TRUE)))
  
  # title_text <- paste0(Portfolio_name," 성과 분석 (", 
  #                      format(as.Date(date_info$분석시작일), "%Y-%m-%d"), " ~ ", 
  #                      format(as.Date(date_info$분석종료일), "%Y-%m-%d"), ")")
  # 
  
  
  subtitle_text <- str_glue("비중변화 = ({date_info$분석종료일} 순자산비중) - ({date_info$분석시작일-days(1)} 순자산비중)")
  
  parent_data <- filtered_data %>%
    filter(is.na(종목코드)) %>%
    select(자산군, 개별수익률, 기여수익률, 순자산비중_종료, 비중변화)
  
  child_data <- filtered_data %>% filter(!is.na(종목코드))
  
  nested_child_data <- child_data %>%
    group_by(자산군) %>%
    nest() %>%
    rename(details = data)
  
  final_data <- parent_data %>%
    left_join(nested_child_data, by = "자산군")
  
  # --- 3. Reactable 시각화 Helper 함수 및 변수 ---
  diverging_bar_cell <- function(value, max_abs_value) {
    if (is.na(value)) return(div("N/A", style = list(color = "#aaa")))
    width_percent <- abs(value) / max_abs_value * 50
    color <- if (value > 0) "#dc3545" else"#0d6efd"
    if (value > 0) {
      bar_left <- div(style = list(width = "50%"))
      bar_right <- div(style = list(width = paste0(width_percent, "%"), height = "16px", background = color, borderRadius = "4px"))
    } else if (value < 0) {
      bar_left <- div(style = list(width = paste0(width_percent, "%"), height = "16px", background = color, borderRadius = "4px", marginLeft = paste0(50 - width_percent, "%")))
      bar_right <- div(style = list(width = "50%"))
    } else {
      bar_left <- div(style = list(width = "50%"))
      bar_right <- div(style = list(width = "50%"))
    }
    div(style = list(display = "flex", alignItems = "center"), span(format(round(value * 100, 2), nsmall = 2), "%", style = list(minWidth = "60px", textAlign = "right")), div(style = list(display = "flex", width = "100%", marginLeft = "8px", background = "#e9ecef", borderRadius = "4px", height = "16px"), bar_left, bar_right))
  }
  max_abs_ind_perf <- max(abs(filtered_data$개별수익률), na.rm = TRUE); if (!is.finite(max_abs_ind_perf) || max_abs_ind_perf == 0) max_abs_ind_perf <- 1 
  max_abs_contrib <- max(abs(filtered_data$기여수익률), na.rm = TRUE); if (!is.finite(max_abs_contrib) || max_abs_contrib == 0) max_abs_contrib <- 1 
  max_abs_change <- max(abs(filtered_data$비중변화), na.rm = TRUE); if (!is.finite(max_abs_change) || max_abs_change == 0) max_abs_change <- 1
  max_num <- c(max_abs_ind_perf,max_abs_contrib,max_abs_change)
  max_num <- max(max_num[max_num!=1])
  shared_columns <- list(개별수익률 = colDef(name = "수익률(Norm)",
                                        align = "right", width = 150,
                                        cell = function(value) diverging_bar_cell(value, max_num)),
                         기여수익률 = colDef(name = "수익률(기여)", 
                                        align = "right", width = 150, 
                                        cell = function(value) diverging_bar_cell(value, max_num)),
                         순자산비중_종료 = colDef(name = "순자산비중", 
                                           align = "right", width = 100,
                                           format = colFormat(percent = TRUE, digits = 2)),
                         비중변화 = colDef(name = "비중변화", 
                                       align = "right", width = 150,
                                       cell = function(value) diverging_bar_cell(value, max_num)))
  
  
  # --- 4. 최종 Reactable 테이블 생성 (부제목 추가) ---
  
  # 4-1. reactable 객체를 먼저 생성합니다.
  portfolio_table <- reactable(
    final_data,
    fullWidth = FALSE,
    rowStyle = function(index) {
      list(background = "#f2f8ff", fontWeight = "bold")
    },
    columns = c(
      list(
        자산군 = colDef(
          name = "자산군/종목명", width = 180,
          details = function(index) {
            detail_table_data <- final_data$details[[index]]
            if (is.null(detail_table_data) || nrow(detail_table_data) == 0) return()
            reactable(detail_table_data %>% select(종목명, 개별수익률, 기여수익률, 순자산비중_종료, 비중변화), outlined = TRUE, fullWidth = FALSE, columns = c(list(종목명 = colDef(name = "종목명", width = 180, cell = function(value) div(style = list(paddingLeft = "1.5rem"), value))), shared_columns))
          }
        ),
        details = colDef(show = FALSE)
      ),
      shared_columns
    ),
    defaultPageSize = 10, striped = TRUE, highlight = TRUE, bordered = TRUE,
    theme = reactableTheme(headerStyle = list(background = "#f7f7f8", borderColor = "#e1e1e1"))
  )
  # 
  # # 4-2. 제목과 부제목으로 사용할 HTML 태그를 각각 만듭니다.
  # title_tag <- htmltools::tags$h3(
  #   style = "font-weight: bold; margin-bottom: 5px;", # 제목 아래 여백을 줄임
  #   title_text
  # )
  # 
  # subtitle_tag <- htmltools::tags$h5(
  #   style = "color: #6c757d; font-weight: normal; margin-top: 0; margin-bottom: 15px;", # 회색 계열, 보통 굵기, 위아래 여백 조절
  #   subtitle_text
  # )
  # 
  # # 4-3. div()를 사용해 제목과 부제목을 하나의 컨테이너로 묶습니다.
  # header_container <- htmltools::tags$div(
  #   title_tag,
  #   subtitle_tag
  # )
  # 
  # # 4-4. prependContent() 함수에 이 컨테이너를 전달하여 반환합니다.
  # return(
  #   htmlwidgets::prependContent(portfolio_table, header_container)
  # )
  return(list(portfolio_table,
              parent_data %>% 
                mutate(분석시작일 = date_info$분석시작일[1],
                       분석종료일 = date_info$분석종료일[1],.after = 자산군),
              child_data)) 
  
}
#res_list_portfolio <- AP_roll_portfolio_res
single_port_historical_return <- function(res_list_portfolio, mapping_method){
  # 1. 포트폴리오 / 자산군별 기여수익률 <-> Norm수익률
  # 2. 자산군별로 포트폴리오 /개별 sec  기여수익률 <->Norm수익률
  
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
  
  roll_over_going_item <- res_list_portfolio$sec별_기여수익률 %>% 
    group_by(기준일자,ITEM_NM) %>% 
    filter(n()>1) %>% pull(ITEM_NM) %>% unique()
  
  # res_list_portfolio$sec별_기여수익률 %>% 
  #   group_by(기준일자,ITEM_NM) %>% 
  #   filter(n()>1) %>% 
  #   group_by(sec_id) %>% 
  #   reframe(분석시작일,분석종료일) %>% distinct()
  if(length(roll_over_going_item)!=0){
    res_list_portfolio$sec별_기여수익률<- bind_rows(
      res_list_portfolio$sec별_기여수익률 %>% 
        filter(ITEM_NM %in% roll_over_going_item) %>% 
        group_by(기준일자,자산군,ITEM_NM) %>% 
        reframe(sec_id = sec_id[n()],
                분석시작일 = min(분석시작일),
                분석종료일 = max(분석종료일),
                자산군 = 자산군[1],
                cum_return = cum_return[1],
                총손익기여도 = sum(총손익기여도),
                총손익금액 = sum(총손익금액)) ,
      res_list_portfolio$sec별_기여수익률 %>% 
        filter(!(ITEM_NM %in% roll_over_going_item))
    )
    
    res_list_portfolio$normalized_performance_by_sec %>% 
      filter(ITEM_NM %in% roll_over_going_item) %>% 
      group_by(기준일자,자산군,ITEM_NM) %>% 
      reframe(sec_id = sec_id[n()],
              분석시작일 = min(분석시작일),
              분석종료일 = max(분석종료일),
              자산군 = 자산군[1],
              누적수익률 = prod(누적수익률+1)-1) %>% tail()
    
    res_list_portfolio$normalized_performance_by_sec <- bind_rows(
      res_list_portfolio$normalized_performance_by_sec %>% 
        filter(ITEM_NM %in% roll_over_going_item) %>% 
        group_by(기준일자,자산군,ITEM_NM) %>% 
        reframe(sec_id = sec_id[n()],
                분석시작일 = min(분석시작일),
                분석종료일 = max(분석종료일),
                자산군 = 자산군[1],
                누적수익률 = prod(누적수익률+1)-1)  ,
      res_list_portfolio$normalized_performance_by_sec %>% 
        filter(!(ITEM_NM %in% roll_over_going_item))
    )
    
    res_list_portfolio$sec별_비중 <- bind_rows(
      res_list_portfolio$sec별_비중 %>% 
        filter(ITEM_NM %in% roll_over_going_item) %>% 
        group_by(자산군,ITEM_NM) %>% 
        mutate(sec_id = sec_id[n()]) %>% 
        ungroup(),
      res_list_portfolio$sec별_비중 %>% 
        filter(!(ITEM_NM %in% roll_over_going_item)) 
      
    )
  }
  
  
  # --- 1. 데이터 준비 ---
  table_data_sec <- res_list_portfolio$sec별_기여수익률 %>%
    left_join(
      res_list_portfolio$normalized_performance_by_sec %>%
        select(기준일자, sec_id, `Normalized 수익률` = 누적수익률),
      by = join_by(기준일자, sec_id)
    ) %>%
    group_by(sec_id) %>% 
    mutate(종목명 = ITEM_NM[n()]) %>% 
    select(
      자산군, 기준일자, 분석시작일, 분석종료일,
      종목코드 = sec_id, 종목명 ,
      `Normalized 수익률`, `기여 수익률` = 총손익기여도
    ) #%>% 
  #filter(자산군 != "유동성및기타")
  
  table_data_classification <- res_list_portfolio$자산군별_기여수익률 %>%
    left_join(
      res_list_portfolio$normalized_performance_by_자산군 %>%
        select(기준일자, 자산군, `Normalized 수익률` = 누적수익률), by = join_by(자산군, 기준일자)
    ) %>%
    select(
      자산군, 기준일자, 분석시작일, 분석종료일,
      `Normalized 수익률`, `기여 수익률` = 총손익기여도
    )
  
  
  raw_data <- 
    bind_rows(res_list_portfolio$자산군별_기여수익률 %>% 
                select(기준일자,분석시작일,분석종료일,cum_return) %>% 
                distinct() %>% 
                mutate(자산군 = "포트폴리오") %>% 
                mutate(`Normalized 수익률` = cum_return,
                       `기여 수익률` = cum_return) %>% 
                select(-cum_return),
              table_data_classification,
              table_data_sec) %>%
    mutate(종목명 = coalesce(종목명,자산군)) %>% 
    mutate( 자산군 = factor(자산군, levels = sorted_data)) %>%
    mutate(종목코드 = if_else(!is.na(종목코드) &종목코드 == "유동성및기타","유동성및기타(미분류종목 제외)",종목코드),
           종목명 = if_else(!is.na(종목코드) &종목코드 == "유동성및기타(미분류종목 제외)","유동성및기타(미분류종목 제외)",종목명)) %>% 
    dplyr::arrange(자산군) 
  
  
  # 1. 포트폴리오 / 자산군별 기여수익률 <-> Norm수익률
  plot_list <- list()
  list_components<- unique(raw_data$자산군)
  for(i in seq_along(list_components)){
    if(list_components[i]== "포트폴리오"){
      plot_list[i] <- list( raw_data %>% 
                              filter(is.na(종목코드)) %>% 
                              pivot_longer(cols = contains("수익률"),names_to = "설명",values_to = "value") %>% 
                              group_by(종목명) %>% 
                              filter(분석시작일 == min(분석시작일)) %>% 
                              ungroup() %>% 
                              pivot_wider(id_cols = c(기준일자,설명),names_from = 자산군,values_from = value))
    }else{
      plot_list[i] <- list(raw_data %>% 
                             filter(자산군!= "포트폴리오") %>% 
                             filter(자산군==  list_components[i] ) %>% 
                             pivot_longer(cols = contains("수익률"),names_to = "설명",values_to = "value") %>% 
                             pivot_wider(id_cols = c(기준일자,설명),names_from = 종목명,values_from = value))
    }
  }
  plot_list<- setNames(plot_list,list_components)
  
  
  # plot_list$국내주식 %>% view()
  return(plot_list)
  
  
}

single_port_historical_return_echarts4r <- function(plot_component) {
  
  # # type(개별수익률/기여수익률)에 따라 데이터 필터링
  # plot_component <-   plot_list[[2]]
  # 
  plot_component<- bind_rows(plot_component %>% 
                               group_by(설명) %>% 
                               reframe(기준일자 = min(기준일자)-days(1),
                                       across(where(is.numeric),.fns = ~ 0)),
                             plot_component)
  
  
  # 차트의 시리즈가 될 컬럼 이름들 (기준일자, 설명 제외)
  series_cols <- colnames(plot_component)[!colnames(plot_component) %in% c("기준일자", "설명")]
  
  # e-charts 객체 생성
  p <- plot_component %>%
    arrange(기준일자) %>% 
    group_by(설명) %>% 
    e_charts(기준일자,timeline = TRUE)
  
  # 각 시리즈(자산군 또는 종목)에 대해 e_line 추가
  for (col in series_cols) {
    p <- p %>% e_line_(col, symbol = "none", smooth = FALSE)
  }
  
  p %>%
    e_x_axis(min = min(plot_component$기준일자) - days(1),
             max = max(plot_component$기준일자) + days(1)) %>%
    e_y_axis(formatter = e_axis_formatter("percent", digits = 3)) %>%
    e_tooltip(
      trigger = "axis",
      axisPointer = list(type = "cross"),
      formatter = e_tooltip_pointer_formatter(style = c("percent"), digits = 3)
    ) %>% 
    
    # 🔹 제목을 맨 위에 고정 + 패딩으로 하단 여백 확보
    e_title(
      str_glue("{colnames(plot_component)[3] } 구성 요소 분석:  ( {min(unique(plot_component$기준일자)[-1])} ~ {max(unique(plot_component$기준일자)[-1])} )"),
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
single_port_historical_weight <- function(res_list_portfolio, mapping_method, Portfolio_name) {
  # historical --------------------------------------------------------------
  
  for_reordering_classification <- universe_non_derivative_table %>%
    dplyr::filter(classification_method == mapping_method, !is.na(classification)) %>%
    dplyr::pull(classification) %>%
    unique()
  
  korean_items <- sort(for_reordering_classification[stringr::str_detect(for_reordering_classification, "[가-힣]")])
  non_korean_items <- sort(for_reordering_classification[!stringr::str_detect(for_reordering_classification, "[가-힣]")])
  sorted_data <- c(
    "포트폴리오",
    korean_items[korean_items != "유동성및기타"],
    non_korean_items,
    "유동성및기타"
  )
  
  # --- 1. 데이터 준비 ---
  table_data_sec <- 
    res_list_portfolio$sec별_비중 %>%
    group_by(sec_id) %>%
    mutate(순자산비중_시작 = first(weight_순자산), .before = weight_순자산) %>%
    select(기준일자, sec_id, 순자산비중_시작, weight_순자산, `weight_PA(T)`) %>% 
    ungroup() %>% 
    left_join(
      res_list_portfolio$normalized_performance_by_sec %>%
        select(기준일자, sec_id, 개별수익률 = 누적수익률),
      by = join_by(기준일자, sec_id)
    ) %>%
    left_join(
      res_list_portfolio$sec별_기여수익률,
      by = join_by(기준일자, sec_id)
    ) %>%
    group_by(sec_id) %>% 
    fill(ITEM_NM,자산군, .direction = "downup") %>% 
    mutate(종목명 = ITEM_NM[n()]) %>% 
    ungroup() %>% 
    select(
      자산군, 기준일자, 분석시작일, 분석종료일,
      종목코드 = sec_id, 종목명 ,
      개별수익률, 기여수익률 = 총손익기여도,
      순자산비중_시작, 순자산비중_종료 = weight_순자산,
      평가자산비중 = `weight_PA(T)`
    )# %>%
  #filter(자산군 != "유동성및기타")
  
  table_data_classification <- 
    res_list_portfolio$자산군별_비중 %>%
    group_by(자산군) %>%
    mutate(순자산비중_시작 = first(weight_순자산), .before = weight_순자산) %>% 
    ungroup() %>% 
    left_join(
      res_list_portfolio$normalized_performance_by_자산군 %>%
        select(기준일자, 자산군, 개별수익률 = 누적수익률),
      by = join_by(자산군, 기준일자)
    ) %>%
    left_join(res_list_portfolio$자산군별_기여수익률 ) %>%
    select(
      자산군, 기준일자, 분석시작일, 분석종료일,
      개별수익률, 기여수익률 = 총손익기여도,
      순자산비중_시작, 순자산비중_종료 = weight_순자산,
      평가자산비중 = `weight_PA(T)`
    )
  
  raw_data <- bind_rows(table_data_classification, table_data_sec) %>%
    arrange(자산군) %>%
    mutate(across(contains("수익률"),.fns = ~replace_na(.x,0))) %>% 
    mutate(비중변화 = 순자산비중_종료 - 순자산비중_시작) %>%
    mutate(종목명 = if_else(is.na(종목명), 자산군, 종목명)) %>%
    mutate(자산군 = factor(자산군, levels = sorted_data)) %>%
    dplyr::arrange(자산군,기준일자)
  
  to_epoch_ms <- function(date) {
    as.numeric(as.POSIXct(date)) * 1000
  }
  
  # 1-1. 상위 레벨(자산군) 색상 맵 생성
  all_asset_classes <- levels(raw_data$자산군)
  non_fx_classes <- all_asset_classes[!all_asset_classes %in% c("FX", "포트폴리오")]
  
  palette_colors <- colorRampPalette(c('#5470c6','#91cc75', '#fac858','#ee6666'))(length(non_fx_classes))
  
  color_map <- setNames(palette_colors, non_fx_classes)
  color_map["FX"] <- "black"
  color_map["포트폴리오"] <- "#777777" # 예시 색상
  
  # 1-2. 상위 레벨(자산군) 시리즈 데이터 생성
  asset_series <- raw_data %>%
    filter(is.na(종목코드)) %>%
    replace_na(list(순자산비중_종료 = 0)) %>%
    mutate(x = to_epoch_ms(기준일자), y = 순자산비중_종료) %>%
    group_by(name = 자산군) %>%
    summarise(data = list(list_parse2(select(cur_data(), x, y))), .groups = "drop") %>%
    mutate(
      type = if_else(name == "FX", "line", "area"),
      color = color_map[as.character(name)],
      zIndex = if_else(name == "FX", 1, 0)
    ) %>%
    list_parse()
  
  # 2-1. 하위 레벨(드릴다운) 데이터 준비
  nested_drilldown <- 
    raw_data %>%
    filter(!is.na(종목코드) ) %>%
    replace_na(list(순자산비중_종료 = 0)) %>%
    mutate(x = to_epoch_ms(기준일자), y = 순자산비중_종료) %>% 
    group_nest(parent = 자산군) %>% 
    filter(!is.na(parent))
  
  # 2-2. 동적 색상을 적용한 드릴다운 시리즈 생성
  drilldown_series_list <- purrr::map2(
    .x = nested_drilldown$data,
    .y = nested_drilldown$parent,
    .f = function(df, parent_name) {
      base_color <- color_map[[as.character(parent_name)]]
      if (is.null(base_color)) base_color <- "#808080"
      
      sorted_df <- df %>%
        group_by(name = 종목명) %>%
        summarise(
          data = list(list_parse2(select(cur_data(), x, y))),
          last_weight = last(y, default = 0),
          .groups = "drop"
        ) %>%
        arrange(desc(last_weight))
      
      n_colors <- nrow(sorted_df)
      
      drilldown_colors <- if (n_colors > 1) {
        colorRampPalette(c('#5470c6','#91cc75', '#fac858','#ee6666'))(n_colors)
      } else {
        base_color
      }
      
      sorted_df %>%
        mutate(
          type = "area",
          index = row_number() - 1,
          color = drilldown_colors
        ) %>%
        select(-last_weight) %>%
        list_parse()
    }
  )
  
  names(drilldown_series_list) <- nested_drilldown$parent
  drilldown_data_json <- jsonlite::toJSON(drilldown_series_list, auto_unbox = TRUE)
  
  # --- 3. highcharter 최종 차트 생성 ---
  highchart() %>%
    hc_title(text = str_glue("{Portfolio_name} 순자산비중 : {min(raw_data$기준일자)} ~ {max(raw_data$기준일자)}")) %>%
    hc_subtitle(text = "자산군별 비중 추이 (영역 경계 클릭 시 상세 보기)") %>%
    hc_chart(
      events = list(
        load = JS("
          function() {
            var chart = this;
            chart.initialSeries = chart.series.map(s => s.options);
            chart.initialSubtitle = chart.subtitle.options.text;
          }
        ")
      )
    ) %>%
    hc_xAxis(type = "datetime") %>%
    hc_yAxis(
      title = list(text = "비중 (%)"),
      showLastLabel = FALSE,
      labels = list(formatter = JS("function() { return (this.value * 100).toFixed(0) + '%' }"))
    ) %>%
    hc_tooltip(
      shared = TRUE,
      crosshairs = TRUE,
      formatter = JS("
        function() {
          var s = '<b>' + Highcharts.dateFormat('%Y-%m-%d', this.x) + '</b>';
          this.points.forEach(function (point) {
            s += '<br/><span style=\"color:' + point.color + '\">\u25CF</span> ' + 
                 point.series.name + ': <b>' + 
                 (point.y * 100).toFixed(2) + '%</b>';
          });
          return s;
        }
      ")
    ) %>%
    hc_plotOptions(
      area = list(stacking = "normal", lineWidth = 1, marker = list(enabled = FALSE)),
      line = list(lineWidth = 2, marker = list(enabled = FALSE)),
      series = list(
        colorByPoint = FALSE,
        cursor = "pointer",
        point = list(
          events = list(
            click = JS("
              function() {
                var chart = this.series.chart; 
                var seriesName = this.series.name;
                var allDetailData = ", drilldown_data_json, ";
                var detailSeries = allDetailData[seriesName];

                if (detailSeries) {
                  while (chart.series.length > 0) chart.series[0].remove(false);
                  
                  detailSeries.forEach(function(s) { chart.addSeries(s, false); });
                  
                  chart.setTitle(null, { text: seriesName + ' 내 개별 종목 비중' });
                  
                  if (!chart.customBackButton) {
                    chart.customBackButton = chart.renderer.button('◁ Back', 10, 30, function() {
                        while (chart.series.length > 0) chart.series[0].remove(false);
                        chart.initialSeries.forEach(function(s) { chart.addSeries(s, false); });
                        chart.setTitle(null, { text: chart.initialSubtitle });
                        chart.redraw();
                        
                        this.destroy();
                        chart.customBackButton = null;
                    }).add();
                  }
                  
                  chart.redraw();
                }
              }
            ")
          )
        )
      )
    ) %>%
    hc_add_series_list(asset_series) ->pp
  
  list(pp,
       raw_data %>% filter(is.na(종목코드)) ,
       raw_data %>% filter(!is.na(종목코드)) )
}
# 
