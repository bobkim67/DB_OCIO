
# Backtest module(MP,VP,BM계산) ---------------------------------------------


calculate_BM_results_bulk <- function(filtering_universe, dataseries_specify, weight_vector, total_return_check, unhedge_check,
                                 start_date, end_date, `보수조정(연bp)` = 0) {
  
  `보수조정(연bp)` <- if_else(`보수조정(연bp)`!=0, `보수조정(연bp)`/10000/365 ,`보수조정(연bp)`)
  # 1. 제약 조건 체크
  if (!(length(filtering_universe) == length(weight_vector) &&
        length(filtering_universe) == length(dataseries_specify) &&
        length(weight_vector) == length(total_return_check) &&
        length(total_return_check) == length(unhedge_check))) {
    stop("Error: 모든 입력 벡터의 길이가 동일해야 합니다.")
  }
  
  # Data_variable_list 생성
  # filtering_universe <- test[1,]$dataset_id_vector[[1]]
  # dataseries_specify <- test[1,]$dataseries_id_vector[[1]]
  # weight_vector <- test[1,]$weight_vector[[1]]
  # total_return_check <- test[1,]$total_return_check_vector[[1]]
  # unhedge_check <- test[1,]$unhedge_check_vector[[1]]
  # 
  
  Data_variable_list <-tibble(filtering_universe,dataseries_specify,weight_vector,total_return_check,unhedge_check)
  
  # for_pulling_universe_data 생성
  for_pulling_universe_data <- Mapping_nation %>%
    filter(dataset_id %in% filtering_universe) %>%
    left_join(Data_variable_list,
              by = join_by(dataset_id == filtering_universe)) %>%
    rename(dataseries_id = dataseries_specify) %>%
    mutate(dataseries_id = as.integer(dataseries_id)) %>%
    mutate(symbol = if_else(dataseries_id == 33, name, symbol)) %>%
    mutate(symbol = str_glue("{symbol}{if_else(국가 != 'KR', '(t-1)', '')}{if_else(total_return_check == 1,'(TR)','')}{if_else(unhedge_check == 1 & 국가 != 'KR', '*(USDKRW)', '')}"),
           .after = ISIN)
  
  # pulled_data 생성
  pulled_data <- for_pulling_universe_data %>%
    inner_join(pulled_data_universe,by = join_by(dataset_id,dataseries_id))
  
  # Source_factset 생성
  Source_factset <- pulled_data %>%
    filter(dataseries_id %in% c(6,15)) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% 
    arrange(기준일자) %>% 
    select(-c(timestamp_observation)) %>% 
    mutate(data = map(data, ~jsonlite::parse_json(rawToChar(unlist(.x))))) %>% 
    mutate(USD = map_dbl(data, ~unlist(.x)[1]),
           KRW = map_dbl(data, ~unlist(.x)[2])) %>% 
    mutate(pulling_value = if_else(국가 == "KR", KRW, USD)) %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = pulling_value) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_Bloomberg 생성
  Source_Bloomberg <- pulled_data %>%
    filter(dataseries_id == 9) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% 
    arrange(기준일자) %>% 
    mutate(data = map_dbl(data, ~as.numeric(rawToChar(unlist(.x))))) %>% 
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = data) %>%  
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_KIS 생성
  Source_KIS <- pulled_data %>%
    filter(dataseries_id == 33) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% 
    arrange(기준일자) %>% 
    select(-c(timestamp_observation)) %>%
    mutate(data = map(data, ~jsonlite::parse_json(rawToChar(unlist(.x))))) %>% 
    mutate(data = map_dbl(data, ~as.numeric(.x[[1]]))) %>% 
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = data)
  
  # Source_combined 생성
  Source_factset %>% 
    full_join(Source_Bloomberg , by = join_by(기준일자)) %>% 
    full_join(Source_KIS , by = join_by(기준일자)) %>% 
    full_join(USDKRW , by = join_by(기준일자)) %>% 
    arrange(기준일자)->Source_combined
  
  # 최종 결과 계산 및 가중 합계 계산
  results <-
    Source_combined %>%
    select(기준일자, for_pulling_universe_data$symbol,`USD/KRW`) %>% 
    mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays,1,0)) %>% 
    mutate(across(.cols = (which(if_else(for_pulling_universe_data$국가=="KR",1,0)==0)+1),
                  .fns = ~if_else(korea_holiday==1, NA, .x) )) %>%
    select(-korea_holiday) %>%
    timetk::pad_by_time(.date_var = 기준일자,.by = "day", .fill_na_direction = "down") %>% 
    mutate(across(.cols = contains("(USDKRW)"), .fns = ~.x * `USD/KRW`)) %>% 
    mutate(raw_data_list = pmap(select(.,-c(기준일자)),.f= ~c(...)),.after = 기준일자) %>% 
    mutate(across(.cols = -c(기준일자,`USD/KRW`,raw_data_list), .fns = ~.x/lag(.x)-1, .names = "return_{.col}"  ),.after = 기준일자 ) %>% 
    filter(dplyr::between(기준일자,left = ymd(start_date),right = ymd(end_date))) %>% 
    mutate(across(.cols = starts_with("return_"), .fns = ~ (cumprod(.x+1)-1), .names = "cum_{.col}"  ),.after = 기준일자 ) %>% 
    mutate(across(.cols = starts_with("return_"), .fns = ~ lag(cumprod(.x+1)-1,default = 0), .names = "lagged_cum_{.col}"  ),.after = 기준일자 ) %>% 
    mutate(daily_return_list = pmap(select(., starts_with("return_")),.f= ~c(...) %>% set_names(for_pulling_universe_data$symbol) ),.after = 기준일자) %>%
    mutate(cummulative_return_since_rebalanced_date_list = pmap(select(., starts_with("cum_return_")),.f= ~c(...) %>% set_names(for_pulling_universe_data$symbol)),.after = 기준일자) %>%  
    mutate(lagged_cummulative_return_since_rebalanced_date_list = pmap(select(., starts_with("lagged_cum_return_")),.f= ~c(...) %>% set_names(for_pulling_universe_data$symbol)),.after = 기준일자) %>% 
    select(기준일자, contains("list")) %>% 
    # 2. Driftweight 계산 (갱신된 가중치 벡터 생성)
    mutate(`Weight_fixed(T)` = map(
      cummulative_return_since_rebalanced_date_list, 
      ~ {
        (1 + .x*0) * for_pulling_universe_data$weight_vector # 요소별 이름만 필요한것이기 때문에 .x이용
      }
    ), .after = 기준일자) %>% 
    mutate(`Weight_drift(T-1)` = map(
      lagged_cummulative_return_since_rebalanced_date_list, 
      ~ {
        비중 <- (1 + .x) * for_pulling_universe_data$weight_vector
        비중 / sum(비중) # 합이 1이 되도록 정규화
      }
    ), .after = 기준일자) %>% 
    mutate(`Weight_drift(T)` = map(
      cummulative_return_since_rebalanced_date_list, 
      ~ {
        비중 <- (1 + .x) * for_pulling_universe_data$weight_vector
        비중 / sum(비중) # 합이 1이 되도록 정규화
      }
    ), .after = 기준일자) %>%   
    # Fixed weight 수익률 계산
    mutate(weighted_sum_fixed = map_dbl(
      daily_return_list, 
      ~ sum(c(.x) * for_pulling_universe_data$weight_vector)
    ), .after = 기준일자) %>% 
    # Drift weight 수익률 계산
    mutate(weighted_sum_drift = map2_dbl(.x = `Weight_drift(T-1)`,.y =daily_return_list ,
                                         ~ sum(.x * (.y))
    ), .after = 기준일자)  %>% 
    mutate(across(.cols = contains("weighted_sum"),.fns = ~(.x+`보수조정(연bp)`)))
  
  
  return(list(results,for_pulling_universe_data))
}



# Performance_function ----------------------------------------------------


return_performance_shallow <- function(data, input_date, from_when, base_date = NULL) {
  
  #input_date <- "2024-06-28"
  input_date <- ymd(input_date)
  start_of_month <- floor_date(input_date, "month")
  end_of_month <- ceiling_date(input_date, "month") - days(1)
  # 해당 월의 모든 날짜
  all_dates <- seq(start_of_month, end_of_month, by = "day")
  
  # 평일만 추출
  weekdays_only <- all_dates[!(wday(all_dates) %in% c(1,7))]
  # 휴장일 제외
  tradingdays_only <- weekdays_only[! (weekdays_only %in% KOREA_holidays)]
  
  
  last_day_of_month<- input_date ==max(tradingdays_only)
  print(paste("return_performance_shallow: input_date =", input_date, "from_when =", from_when))
  
  
  # base_date가 NULL일 경우 처리
  if (is.null(base_date)) {
    base_date <- NA_Date_
  } else {
    base_date <- ymd(base_date)
  }
  
  data %>%
    #AP_performance_preprocessing %>% filter(펀드설명%in% c("TDF2080","Golden Growth")) %>% 
    mutate(요일 = wday(기준일자, label = TRUE)) %>%
    filter(!(펀드 %in% c("07J48", "07J49"))) %>%
    dplyr::mutate(filtered_first_date = 
                    case_when(
                      from_when == "YTD" ~   make_date(year(input_date))-days(1),
                      from_when == "ITD" ~ 설정일-days(1),
                      from_when == "최근 1년" ~ add_with_rollback(input_date, -months(12)),
                      #from_when == "최근 1주" ~ input_date - weeks(1),
                      from_when == "최근 1개월" ~ add_with_rollback(input_date, -months(1)),
                      from_when == "최근 3개월" ~ add_with_rollback(input_date, -months(3)),
                      from_when == "최근 6개월" ~ add_with_rollback(input_date, -months(6)),
                      from_when == "Base date" ~ ymd(base_date)-days(1)
                    )
    ) %>%
    mutate(total_days = difftime(input_date,filtered_first_date,units = "days") %>% as.numeric()) %>% 
    mutate(filtered_first_date = if_else((last_day_of_month ==TRUE & !(from_when %in% c("Base date","ITD")) ), 
                                         (ceiling_date(filtered_first_date[1], unit = "month") - days(1)),
                                         filtered_first_date[1] ) ) %>% 
    mutate(total_days = if((last_day_of_month ==TRUE & !(from_when %in% c("Base date","ITD")) )){
      difftime(input_date,filtered_first_date,units = "days") %>% as.numeric()
    } else{total_days}) %>% 
    group_by(펀드설명,wday(기준일자)) %>% 
    mutate(직전주_수정기준가 = lag(수정기준가, n = 1)) %>%
    mutate(주별수익률 = (수정기준가 / 직전주_수정기준가 - 1)) %>% 
    ungroup() %>% 
    group_by(펀드설명) %>% 
    dplyr::filter( (if_else(from_when =="ITD",TRUE,FALSE) | 설정일-days(1)<=filtered_first_date) & 기준일자<=input_date & 기준일자>=filtered_first_date  )%>%
    mutate(
      설정직전날 = sum(설정일 > filtered_first_date) != 0,
      주별수익률 = if_else(is.na(직전주_수정기준가) & 설정직전날, 수정기준가/1000-1, 주별수익률),
      직전주_수정기준가 = if_else(is.na(직전주_수정기준가) & 설정직전날, 1000, 직전주_수정기준가)
    ) %>% 
    mutate(수정기준가_first =if_else(설정직전날==TRUE,1000,수정기준가[1])) %>% 
    dplyr::filter(요일 == wday(input_date, label = TRUE)) -> before_filtering_first_row
  
  
  check_look_forward<- seq(min(before_filtering_first_row$기준일자)-weeks(1)+days(1),min(before_filtering_first_row$기준일자) , by = "day")
  check_look_forward<- check_look_forward[!(wday(check_look_forward) %in% c(1,7)) & check_look_forward<before_filtering_first_row$filtered_first_date[1]]
  filtering_boolean <- length(check_look_forward[! (check_look_forward %in% KOREA_holidays)])!=0
  
  if(filtering_boolean){
    after_filtering_process <- before_filtering_first_row %>% 
      filter(row_number()!=1 |(기준일자==input_date) ) %>% 
      ungroup() %>% 
      select(기준일자,펀드,펀드설명, 수정기준가, 수정기준가_first, 주별수익률,total_days)
  }else{
    after_filtering_process <- before_filtering_first_row %>% 
      ungroup() %>% 
      select(기준일자,펀드,펀드설명, 수정기준가, 수정기준가_first, 주별수익률,total_days)
  }
  
  
  
  
  print("return_performance_shallow result:")
  print(after_filtering_process )
  
  
}

return_performance_deep<- function(data,input_date,from_when){
  
  data %>% 
    group_by(펀드설명) %>% 
    summarise(
      기준일자 = input_date,
      Return = 수정기준가[n()]/수정기준가_first[1]-1,
      #Return_annualized = mean(주별수익률,na.rm = TRUE)*52, 
      Return_annualized = (수정기준가[n()]/수정기준가_first[1])^(365/total_days[1])-1, 
      Risk_annualized = sd(주별수익률,na.rm=TRUE)*sqrt(52),
      Return_to_Risk = Return_annualized / Risk_annualized,
      # Sharpe_ratio = (Return_annualized-Rf_Return[n()]/100)/Risk_annualized,
      # 무위험 수익률은 2.25로 고정. 혹시 나중에 수정할 일이 있으면 위에 코드 사용
      Sharpe_ratio = (Return_annualized-2.25/100)/Risk_annualized,
      구분 = from_when)
}



# Position_function -------------------------------------------------------

asset_classification_and_adjust <- function(data){
  # 조인 조건 정의
  join_condition <- join_by(종목 == 종목코드)
  
  # 조인 수행
  data_joined <- data %>% 
    left_join(universe_criteria %>% select(-종목명) %>% distinct(), by = join_condition) 
  
  return(data_joined)
  # data_asset_adjust<- data_joined %>% 
  #   mutate(자산군_중 = if_else(자산군_대=="대체","대체",자산군_중)) %>% 
  #   mutate(자산군_소 = if_else(자산군_대=="대체","대체",자산군_소))
  
  #return(data_asset_adjust)
}



calculate_portfolio_weights <- function(data, asset_group ,division) {
  # 먼저, 자산군 별로 순자산비중을 계산
  daily_weights <- data %>%
    filter(자산군_대 != "유동성") %>% 
    mutate(순자산비중 = 시가평가액 / 순자산) %>%
    group_by(기준일자, 펀드, !!sym(asset_group)) %>%
    summarise(daily_weight = sum(순자산비중, na.rm = TRUE), .groups = 'drop')
  
  if(division=="VP"){
    return(daily_weights)
  }else{
    feeder_fund <- daily_weights %>% 
      # 자펀드 비중
      filter(펀드 %in% c("07J48","07J49")) %>% 
      pivot_wider(
        names_from = 펀드,
        values_from = daily_weight,
        values_fill = list(daily_weight = 0)) 
    
    master_fund<- daily_weights %>% 
      #모펀드 비중
      filter(펀드 %in% c("07J34","07J41")) %>%
      pivot_wider(
        names_from = !!sym(asset_group),
        values_from = daily_weight,
        names_prefix = "ratio_")
    if(nrow(master_fund)==0 ){
      daily_weights %>% 
        filter(!(펀드 %in% c("07J34","07J41","07J48","07J49"))) ->final_weights
    }else{
      master_fund %>% inner_join(feeder_fund,relationship = "many-to-many") %>% 
        mutate(daily_weight = `ratio_07J48`*`07J48`+`ratio_07J49`*`07J49`) %>% 
        select(기준일자,펀드,!!sym(asset_group),daily_weight)->mysuper_position
      
      # 최종 포트폴리오 가중치 데이터 프레임 생성
      
      daily_weights %>% 
        filter(!(펀드 %in% c("07J34","07J41","07J48","07J49"))) %>% 
        bind_rows(mysuper_position)  ->final_weights
    }
    
    return(final_weights)
  }
  
  
}

calculate_portfolio_weights_from_MP_to_VP <- function(data, asset_group ,division) {
  # 먼저, 자산군 별로 순자산비중을 계산
  daily_weights <- data %>%
    #ideal_VP_position %>% 
    #group_by(기준일자, 펀드설명, !!sym(asset_group)) %>%
    group_by(기준일자, 펀드설명) %>%
    reframe(daily_weight = 리밸런싱이후누적비중/sum(리밸런싱이후누적비중, na.rm = TRUE),
            자산군_소,자산군_대) %>% 
    group_by(기준일자, 펀드설명, !!sym(asset_group)) %>%
    reframe(daily_weight = sum(daily_weight, na.rm = TRUE))
  
  
  return(daily_weights)
  
}


# Plotting_function -------------------------------------------------------


plot_metric_except_TE <- function(df, metric) {
  # 해당 Metric의 데이터 필터링
  metric_data <- df %>%
    filter(Metric == metric) %>%
    mutate(구분 = factor(구분, levels = c("AP", "VP", "MP", "BM")))
  
  # percent_rank를 사용하여 백분위 계산
  metric_data <- metric_data %>%
    mutate(percent_rank = percent_rank(value))
  
  # 텍스트 레이블을 위한 조건부 처리
  metric_data <- metric_data %>%
    mutate(text_label = ifelse(Metric %in% c("Sharpe_ratio","Return_to_Risk"),
                               sprintf("%.2f", value),
                               label_percent(accuracy = 0.01)(value)))
  
  # 히트맵 생성
  ggplot(metric_data, aes(x = 펀드설명, y = 구분, fill = percent_rank)) +
    geom_tile() +
    geom_text(aes(label = text_label), vjust = 1.5) +
    scale_fill_gradient2(low = "blue", mid = "white", high = "red", 
                         midpoint = 0.5, 
                         guide = guide_legend(title = NULL)) +
    scale_y_discrete(limits = rev(levels(metric_data$구분))) +
    labs(title = paste("Metric:", metric), x = "펀드설명", y = "구분") +
    theme_minimal()
}

# 글자색 조정할 수 있는 함수
# plot_metric_except_TE <- function(df, metric) {
#   # 해당 Metric의 데이터 필터링
#   metric_data <- df %>%
#     filter(Metric == metric) %>%
#     mutate(구분 = factor(구분, levels = c("AP", "VP", "MP", "BM")))
#   
#   # percent_rank를 사용하여 백분위 계산
#   metric_data <- metric_data %>%
#     mutate(percent_rank = percent_rank(value))
#   
#   # 텍스트 레이블과 색상을 위한 조건부 처리
#   metric_data <- metric_data %>%
#     mutate(text_label = ifelse(Metric %in% c("Sharpe_ratio","Return_to_Risk"),
#                                sprintf("%.2f", value),
#                                label_percent(accuracy = 0.01)(value)),
#            text_color = ifelse(abs(percent_rank-0.5) > 0.35, "white", "black"))
#   
#   # 히트맵 생성
#   ggplot(metric_data, aes(x = 펀드설명, y = 구분, fill = percent_rank)) +
#     geom_tile() +
#     geom_text(aes(label = text_label, color = text_color), vjust = 1.5, show.legend = FALSE) +
#     scale_fill_gradient2(low = "blue", mid = "white", high = "red", 
#                          midpoint = 0.5, 
#                          guide = guide_legend(title = NULL)) +
#     scale_color_identity() +
#     guides(color = FALSE) +  # 텍스트 색상에 대한 범례 제거
#     scale_y_discrete(limits = rev(levels(metric_data$구분))) +
#     labs(title = paste("Metric:", metric), x = "펀드설명", y = "구분") +
#     theme_minimal()
# }

plot_metric_TE <- function(df, metric) {
  # 해당 Metric의 데이터 필터링
  metric_data <- df %>% 
    filter(Metric == metric) %>% 
    mutate(구분 = factor(구분, levels = c("AP", "VP"))) %>% 
    # percent_rank를 사용하여 백분위 계산
    mutate(percent_rank = percent_rank(value))  
  
  
  # 텍스트 레이블을 위한 조건부 처리
  metric_data <- metric_data %>%
    mutate(text_label = ifelse(Metric %in%c("IR") ,
                               sprintf("%.2f", value),
                               label_percent(accuracy = 0.01)(value)))
  
  # 히트맵 생성
  ggplot(metric_data, aes(x = 펀드설명, y = 구분, fill = percent_rank)) +
    geom_tile() +
    geom_text(aes(label = text_label), vjust = 1.5) +
    scale_fill_gradient2(low = "blue", mid = "white", high = "red", 
                         midpoint = 0.5, 
                         guide = guide_legend(title = NULL)) +
    scale_y_discrete(limits = rev(levels(metric_data$구분))) +
    labs(title = paste("Metric:",metric ), x = "펀드설명", y = "구분") +
    theme_minimal()
}



