T1_date_calc <- function(input_date){
  holiday_calendar %>% 
    filter(기준일자>ymd(input_date)) %>% 
    filter(hldy_yn=="N") %>% 
    slice(1) %>% 
    pull(기준일자) 
}

T_move_date_calc <- function(input_date,move){
  if(move ==0){
    ymd(input_date)
  }else if(move>0){
    holiday_calendar %>% 
      arrange(기준일자) %>% 
      filter(기준일자>ymd(input_date)) %>% 
      filter(hldy_yn=="N") %>% 
      slice(move) %>% 
      pull(기준일자) 
  }else{
    holiday_calendar %>% 
      arrange(기준일자) %>% 
      filter(기준일자<ymd(input_date)) %>% 
      filter(hldy_yn=="N") %>% 
      slice_tail(n = abs(move)) %>% 
      slice(1) %>% 
      pull(기준일자) 
  }
  
}

### 1. calculate_BM_results_bulk_for_users 함수 수정 ###
# - historical_user_data_long 인자 추가
# - "USER" 소스 처리 로직 추가

long_form_raw_data_input<- function(combined_data) { # ### 수정된 부분 ###: 인자 추가
  
  dataset_id_vector <- combined_data$dataset_id 
  dataseries_id_vector <- combined_data$dataseries_id 
  region_vector <- combined_data$region
  분석시작일_vector <- combined_data$분석시작일
  
  # 1. 제약 조건 체크
  if (!(length(dataset_id_vector) == length(dataseries_id_vector) &&
        length(dataset_id_vector) == length(region_vector) &&
        length(dataset_id_vector) == length(분석시작일_vector) 
  )) {
    stop("Error: 모든 입력 벡터의 길이가 동일해야 합니다.")
  }
  
  Data_variable_list <-tibble("dataset_id"=dataset_id_vector,
                              "dataseries_id" =dataseries_id_vector,
                              "region"=region_vector,
                              "분석시작일" = 분석시작일_vector)
  if(!is.null(USER_historical_price)  ){
    
    for_pulling_universe_data <- Data_variable_list %>% 
      left_join(data_information_integrated %>% select(dataset_id, name=colname_backtest,ISIN), by = join_by(dataset_id)) %>% 
      mutate(name = coalesce(name, dataset_id)) %>% 
      distinct() %>% 
      mutate(symbol = str_glue("{name}{if_else(region != 'KR', '(t-1)', '')}"))
    
  }else{
    
    for_pulling_universe_data <- Data_variable_list %>% 
      left_join(data_information %>% select(dataset_id, name=colname_backtest,ISIN), by = join_by(dataset_id)) %>% 
      distinct() %>% 
      mutate(symbol = str_glue("{name}{if_else(region != 'KR', '(t-1)', '')}")) 
  } 
  
  
  
  # pulled_data 생성 (기존 소스)
  pulled_data_SCIP <- for_pulling_universe_data %>%
    inner_join(pulled_data_universe_SCIP,by = join_by(dataset_id,dataseries_id))
  
  pulled_data_BOS <- for_pulling_universe_data %>%
    inner_join(BOS_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_ZEROIN <- for_pulling_universe_data %>%
    inner_join(ZEROIN_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_ECOS <- for_pulling_universe_data %>%
    inner_join(ECOS_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_RATB <- for_pulling_universe_data %>%
    inner_join(RATB_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_CUSTOM <- for_pulling_universe_data %>%
    inner_join(CUSTOM_historical_price,by = join_by(dataset_id, dataseries_id))
  
  if(!is.null(USER_historical_price)  ){
    
    pulled_data_USER <- for_pulling_universe_data %>%
      inner_join(USER_historical_price %>% mutate(dataseries_id = "User_input"),by = join_by(dataset_id, dataseries_id))
    
  } 
  
  # Source_* 생성 (기존 소스)
  Source_factset <- pulled_data_SCIP %>%
    filter(dataseries_id %in% unique(data_information %>% filter(source=="Factset") %>% pull(dataseries_id))) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% 
    arrange(기준일자) %>% 
    select(-c(timestamp_observation)) %>% 
    mutate(data = map(data, ~jsonlite::parse_json(rawToChar(unlist(.x))))) %>% 
    mutate(USD = map_dbl(data, ~unlist(.x)[1]), KRW = map_dbl(data, ~unlist(.x)[2])) %>% 
    mutate(pulling_value = if_else(region == "KR", KRW, USD)) %>%
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = pulling_value) %>% 
    bind_rows(tibble(기준일자 = 최근영업일)) %>% group_by(기준일자) %>% filter(row_number()==1) %>% ungroup() %>%
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  Source_Bloomberg <- pulled_data_SCIP %>%
    filter(dataseries_id %in% unique(data_information %>% filter(source=="Bloomberg") %>% pull(dataseries_id))) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% arrange(기준일자) %>% 
    mutate(data = map_dbl(data, ~as.numeric(rawToChar(unlist(.x))))) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = data) %>%  
    bind_rows(tibble(기준일자 = 최근영업일)) %>% group_by(기준일자) %>% filter(row_number()==1) %>% ungroup() %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_KIS <- pulled_data_SCIP %>%
    filter(dataseries_id == 33) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% arrange(기준일자) %>% select(-c(timestamp_observation)) %>%
    mutate(data = map(data, ~{ json_string <- rawToChar(unlist(.x)); json_string_clean <- str_replace_all(json_string, "NaN", "null"); jsonlite::parse_json(json_string_clean) })) %>% 
    mutate(data = map_dbl(data, ~as.numeric(.x$totRtnIndex))) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = data) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_BOS <- pulled_data_BOS %>% mutate(기준일자 = ymd(STD_DT)) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = MOD_STPR) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_ZEROIN <- pulled_data_ZEROIN %>% mutate(기준일자 = ymd(기준일자)) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = SUIK_JISU) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_ECOS <- pulled_data_ECOS %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = 기준가_custom) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_RATB <- pulled_data_RATB %>% mutate(기준일자 = ymd(기준일자)) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = standardPrice) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_CUSTOM <- pulled_data_CUSTOM %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = 기준가_custom) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  if(!is.null(USER_historical_price)){
    
    Source_USER <- pulled_data_USER %>% 
      pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = price_custom) %>% 
      mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
    
    
  }else{
    Source_USER <- tibble(기준일자 = ymd(today())) %>% 
      filter(기준일자!=today())
  }
  
  # ### 수정된 부분 끝 ###
  
  # Source_combined 생성
  Source_factset %>% 
    full_join(Source_Bloomberg , by = join_by(기준일자)) %>% 
    full_join(Source_KIS , by = join_by(기준일자)) %>% 
    full_join(Source_BOS , by = join_by(기준일자)) %>% 
    full_join(Source_ZEROIN , by = join_by(기준일자)) %>% 
    full_join(Source_ECOS , by = join_by(기준일자)) %>% 
    full_join(Source_RATB , by = join_by(기준일자)) %>% 
    full_join(Source_CUSTOM , by = join_by(기준일자)) %>% 
    full_join(Source_USER, by = join_by(기준일자)) %>% # ### 수정된 부분 ###: 사용자 데이터 결합
    arrange(기준일자) %>% 
    full_join(USDKRW %>% mutate(`return_USD/KRW`=`USD/KRW`/lag(`USD/KRW`)-1), by = join_by(기준일자)) %>% 
    arrange(기준일자)->Source_combined
  
  Source_combined %>% 
    pivot_longer(cols = -기준일자,names_to = 'symbol',values_to = 'value') %>% 
    left_join(for_pulling_universe_data) %>% 
    filter(!is.na(value)) %>% 
    filter(기준일자>= min(분석시작일,na.rm = TRUE)) -> long_form_raw_data
  
  return(long_form_raw_data)
}


calculate_BM_results_bulk_for_users_input<- function(dataset_id_vector, dataseries_id_vector, region_vector,
                                                     weight_vector, hedge_ratio_vector, cost_adjust_vector, tracking_multiple_vector,
                                                     start_date, end_date) { # ### 수정된 부분 ###: 인자 추가
  
  cost_adjust_vector_for_calc <-  -cost_adjust_vector /10000 /365 # `비용조정(연bp)`
  # 1. 제약 조건 체크
  if (!(length(dataset_id_vector) == length(dataseries_id_vector) &&
        length(region_vector) == length(weight_vector) &&
        length(hedge_ratio_vector) == length(cost_adjust_vector) && 
        length(dataset_id_vector) == length(cost_adjust_vector) &&
        length(tracking_multiple_vector) == length(cost_adjust_vector) )) {
    stop("Error: 모든 입력 벡터의 길이가 동일해야 합니다.")
  }
  weight_vector <- weight_vector/sum(weight_vector)
  
  Data_variable_list <-tibble("dataset_id"=dataset_id_vector,
                              "dataseries_id" =dataseries_id_vector,
                              "region"=region_vector,
                              "weight"=weight_vector,
                              "hedge_ratio"=hedge_ratio_vector,
                              "cost_adjust"=cost_adjust_vector,
                              "tracking_multiple" = tracking_multiple_vector)
  if(!is.null(USER_historical_price)  ){
    
    for_pulling_universe_data <- Data_variable_list %>% 
      left_join(data_information_integrated %>% select(dataset_id, name=colname_backtest,ISIN), by = join_by(dataset_id)) %>% 
      mutate(name = coalesce(name, dataset_id)) %>% 
      distinct() %>% 
      mutate(symbol = str_glue("{name}{if_else(region != 'KR', '(t-1)', '')}{if_else( !(hedge_ratio %in% c(0,1)) & region != 'KR',
                         paste0( '*(USDKRW)*(',(1-hedge_ratio)*100, '%)' ),
                         if_else((hedge_ratio == 0 & region != 'KR') , '*(USDKRW)' , '')) }")) %>% 
      mutate(symbol = if_else(tracking_multiple !=1,str_glue("{symbol}(X{tracking_multiple})"),symbol ))
    
  }else{
    
    for_pulling_universe_data <- Data_variable_list %>% 
      left_join(data_information %>% select(dataset_id, name=colname_backtest,ISIN), by = join_by(dataset_id)) %>% 
      distinct() %>% 
      mutate(symbol = str_glue("{name}{if_else(region != 'KR', '(t-1)', '')}{if_else( !(hedge_ratio %in% c(0,1)) & region != 'KR',
                         paste0( '*(USDKRW)*(',(1-hedge_ratio)*100, '%)' ),
                         if_else((hedge_ratio == 0 & region != 'KR') , '*(USDKRW)' , '')) }")) %>% 
      mutate(symbol = if_else(tracking_multiple !=1,str_glue("{symbol}(X{tracking_multiple})"),symbol ))
  } 
  
  
  
  # pulled_data 생성 (기존 소스)
  pulled_data_SCIP <- for_pulling_universe_data %>%
    inner_join(pulled_data_universe_SCIP,by = join_by(dataset_id,dataseries_id))
  
  pulled_data_BOS <- for_pulling_universe_data %>%
    inner_join(BOS_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_ZEROIN <- for_pulling_universe_data %>%
    inner_join(ZEROIN_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_ECOS <- for_pulling_universe_data %>%
    inner_join(ECOS_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_RATB <- for_pulling_universe_data %>%
    inner_join(RATB_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_CUSTOM <- for_pulling_universe_data %>%
    inner_join(CUSTOM_historical_price,by = join_by(dataset_id, dataseries_id))
  
  if(!is.null(USER_historical_price)  ){
    
    pulled_data_USER <- for_pulling_universe_data %>%
      inner_join(USER_historical_price %>% mutate(dataseries_id = "User_input"),by = join_by(dataset_id, dataseries_id))
    
  } 
  
  # Source_* 생성 (기존 소스)
  Source_factset <- pulled_data_SCIP %>%
    filter(dataseries_id %in% unique(data_information %>% filter(source=="Factset") %>% pull(dataseries_id))) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% 
    arrange(기준일자) %>% 
    select(-c(timestamp_observation)) %>% 
    mutate(data = map(data, ~jsonlite::parse_json(rawToChar(unlist(.x))))) %>% 
    mutate(USD = map_dbl(data, ~unlist(.x)[1]), KRW = map_dbl(data, ~unlist(.x)[2])) %>% 
    mutate(pulling_value = if_else(region == "KR", KRW, USD)) %>%
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = pulling_value) %>% 
    bind_rows(tibble(기준일자 = 최근영업일)) %>% group_by(기준일자) %>% filter(row_number()==1) %>% ungroup() %>%
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  Source_Bloomberg <- pulled_data_SCIP %>%
    filter(dataseries_id %in% unique(data_information %>% filter(source=="Bloomberg") %>% pull(dataseries_id))) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% arrange(기준일자) %>% 
    mutate(data = map_dbl(data, ~as.numeric(rawToChar(unlist(.x))))) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = data) %>%  
    bind_rows(tibble(기준일자 = 최근영업일)) %>% group_by(기준일자) %>% filter(row_number()==1) %>% ungroup() %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_KIS <- pulled_data_SCIP %>%
    filter(dataseries_id == 33) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% arrange(기준일자) %>% select(-c(timestamp_observation)) %>%
    mutate(data = map(data, ~{ json_string <- rawToChar(unlist(.x)); json_string_clean <- str_replace_all(json_string, "NaN", "null"); jsonlite::parse_json(json_string_clean) })) %>% 
    mutate(data = map_dbl(data, ~as.numeric(.x$totRtnIndex))) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = data) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_BOS <- pulled_data_BOS %>% mutate(기준일자 = ymd(STD_DT)) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = MOD_STPR) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_ZEROIN <- pulled_data_ZEROIN %>% mutate(기준일자 = ymd(기준일자)) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = SUIK_JISU) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_ECOS <- pulled_data_ECOS %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = 기준가_custom) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_RATB <- pulled_data_RATB %>% mutate(기준일자 = ymd(기준일자)) %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = standardPrice) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  Source_CUSTOM <- pulled_data_CUSTOM %>% 
    pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = 기준가_custom) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
  
  if(!is.null(USER_historical_price)){
    
    Source_USER <- pulled_data_USER %>% 
      pivot_wider(id_cols = 기준일자, names_from = symbol, values_from = price_custom) %>% 
      mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) 
    
    
  }else{
    Source_USER <- tibble(기준일자 = ymd(today())) %>% 
      filter(기준일자!=today())
  }
  
  # ### 수정된 부분 끝 ###
  
  # Source_combined 생성
  Source_factset %>% 
    full_join(Source_Bloomberg , by = join_by(기준일자)) %>% 
    full_join(Source_KIS , by = join_by(기준일자)) %>% 
    full_join(Source_BOS , by = join_by(기준일자)) %>% 
    full_join(Source_ZEROIN , by = join_by(기준일자)) %>% 
    full_join(Source_ECOS , by = join_by(기준일자)) %>% 
    full_join(Source_RATB , by = join_by(기준일자)) %>% 
    full_join(Source_CUSTOM , by = join_by(기준일자)) %>% 
    full_join(Source_USER, by = join_by(기준일자)) %>% # ### 수정된 부분 ###: 사용자 데이터 결합
    arrange(기준일자) %>% 
    full_join(USDKRW %>% mutate(`return_USD/KRW`=`USD/KRW`/lag(`USD/KRW`)-1), by = join_by(기준일자)) %>% 
    arrange(기준일자)->Source_combined
  
  # ... (이하 계산 로직은 수정 없이 그대로 사용) ...
  
  results <-
    Source_combined %>%
    select(기준일자, for_pulling_universe_data$symbol,`USD/KRW`,`return_USD/KRW`) %>% 
    mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays,1,0)) %>%
    mutate(across(.cols = (which(if_else(for_pulling_universe_data$region=="KR",1,0)==0)+1),
                  .fns = ~if_else(korea_holiday==1, NA, .x) )) %>%
    select(-korea_holiday) %>%
    timetk::pad_by_time(.date_var = 기준일자,.by = "day", .fill_na_direction = "down") %>% 
    mutate(raw_data_list = pmap(select(.,-c(기준일자),-contains("USD/KRW")),.f= ~c(...)),.after = 기준일자) %>%
    select(기준일자,raw_data_list,contains("USD/KRW")) %>% 
    mutate(lag_raw_data_list = lag(raw_data_list),.after = 기준일자) %>% 
    mutate(`return_USD/KRW_list` = map(`return_USD/KRW`, ~ rep(.x, nrow(for_pulling_universe_data)))) %>% 
    mutate(daily_return_list = pmap(list(raw_data_list,lag_raw_data_list,`return_USD/KRW_list`), 
                                    ~ {
                                      FX_adjust<- (1-for_pulling_universe_data$hedge_ratio)*(1-(for_pulling_universe_data$region=="KR"))
                                      return_vector <- ..1/..2 - 1
                                      return_vector <- return_vector*for_pulling_universe_data$tracking_multiple
                                      return_vector_hedge_ratio_considered<-(1+return_vector)*(1+..3*FX_adjust)-1
                                      return_vector_final<- (1+return_vector_hedge_ratio_considered)*(1+cost_adjust_vector_for_calc)-1
                                      return(return_vector_final)
                                    }
    ), .after = 기준일자) %>% 
    select(-`return_USD/KRW_list`) %>% 
    filter(dplyr::between(기준일자,left = ymd(start_date),right = ymd(end_date))) %>% 
    unnest_wider(col = daily_return_list ) %>% 
    mutate(across(.cols =all_of(for_pulling_universe_data$symbol), .fns = ~ (cumprod(.x+1)-1), .names = "cum_{.col}"  ),.after = 기준일자 ) %>% 
    mutate(daily_return_list = pmap(select(.,all_of(for_pulling_universe_data$symbol)),.f= ~c(...)  ),.after = 기준일자) %>% 
    select(-all_of(for_pulling_universe_data$symbol))  %>% 
    mutate(cummulative_return_list = pmap(select(., starts_with("cum_")),.f= ~c(...) %>% set_names(for_pulling_universe_data$symbol)),.after = 기준일자) %>% 
    select(-contains("cum_")) %>% 
    mutate(lagged_cummulative_return_list = lag(cummulative_return_list, default = list(rep(0,length(for_pulling_universe_data$weight)) %>% set_names(for_pulling_universe_data$symbol))), .after = 기준일자 ) %>% 
    mutate(`Weight_fixed(T)` = map(cummulative_return_list, ~ {(1 + .x*0) * for_pulling_universe_data$weight}), .after = 기준일자) %>% 
    mutate(`Weight_drift(T-1)` = map(lagged_cummulative_return_list, ~ { 비중 <- (1 + .x) * for_pulling_universe_data$weight; 비중 / sum(비중) }), .after = 기준일자) %>% 
    mutate(`Weight_drift(T)` = map(cummulative_return_list, ~ { 비중 <- (1 + .x) * for_pulling_universe_data$weight; 비중 / sum(비중) }), .after = 기준일자) %>%   
    mutate(weighted_sum_fixed = map_dbl(daily_return_list, ~ sum(c(.x) * for_pulling_universe_data$weight)), .after = 기준일자) %>% 
    mutate(weighted_sum_drift = map2_dbl(.x = `Weight_drift(T-1)`,.y =daily_return_list , ~ sum(.x * (.y))), .after = 기준일자)  
  
  return(list(results,for_pulling_universe_data))
}


calculate_BM_results_bulk_for_users<- function(dataset_id_vector, dataseries_id_vector, region_vector,
                                               weight_vector, hedge_ratio_vector, cost_adjust_vector, tracking_multiple_vector,
                                               start_date, end_date ) {
  
  cost_adjust_vector_for_calc <-  -cost_adjust_vector /10000 /365 # `비용조정(연bp)`
  # 1. 제약 조건 체크
  if (!(length(dataset_id_vector) == length(dataseries_id_vector) &&
        length(region_vector) == length(weight_vector) &&
        length(hedge_ratio_vector) == length(cost_adjust_vector) &&
        length(dataset_id_vector) == length(cost_adjust_vector) &&
        length(tracking_multiple_vector) == length(cost_adjust_vector) )) {
    stop("Error: 모든 입력 벡터의 길이가 동일해야 합니다.")
  }
  weight_vector <- weight_vector/sum(weight_vector)
  
  Data_variable_list <-tibble("dataset_id"=dataset_id_vector,
                              "dataseries_id" =dataseries_id_vector,
                              "region"=region_vector,
                              "weight"=weight_vector,
                              "hedge_ratio"=hedge_ratio_vector,
                              "cost_adjust"=cost_adjust_vector,
                              "tracking_multiple" = tracking_multiple_vector)
  
  
  for_pulling_universe_data <- Data_variable_list %>%
    left_join(data_information %>% select(dataset_id, name=colname_backtest,ISIN), by = join_by(dataset_id)) %>%
    distinct() %>%
    mutate(symbol = str_glue("{name}{if_else(region != 'KR', '(t-1)', '')}{if_else( !(hedge_ratio %in% c(0,1)) & region != 'KR',
                         paste0( '*(USDKRW)*(',(1-hedge_ratio)*100, '%)' ),
                         if_else((hedge_ratio == 0 & region != 'KR') , '*(USDKRW)' , '')) }")) %>% 
    mutate(symbol = if_else(tracking_multiple !=1,str_glue("{symbol}(X{tracking_multiple})"),symbol ))
  
  
  # pulled_data 생성
  pulled_data_SCIP <- for_pulling_universe_data %>%
    inner_join(pulled_data_universe_SCIP,by = join_by(dataset_id,dataseries_id))
  
  pulled_data_BOS <- for_pulling_universe_data %>%
    inner_join(BOS_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_ZEROIN <- for_pulling_universe_data %>%
    inner_join(ZEROIN_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_ECOS <- for_pulling_universe_data %>%
    inner_join(ECOS_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_RATB <- for_pulling_universe_data %>%
    inner_join(RATB_historical_price,by = join_by(dataset_id, dataseries_id))
  
  pulled_data_CUSTOM <- for_pulling_universe_data %>%
    inner_join(CUSTOM_historical_price,by = join_by(dataset_id, dataseries_id))
  
  
  # Source_factset 생성
  Source_factset <- pulled_data_SCIP %>%
    filter(dataseries_id %in% unique(data_information %>%
                                       filter(source=="Factset") %>%
                                       pull(dataseries_id))) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>%
    arrange(기준일자) %>%
    select(-c(timestamp_observation)) %>%
    mutate(data = map(data, ~jsonlite::parse_json(rawToChar(unlist(.x))))) %>%
    mutate(USD = map_dbl(data, ~unlist(.x)[1]),
           KRW = map_dbl(data, ~unlist(.x)[2])) %>%
    mutate(pulling_value = if_else(region == "KR", KRW, USD)) %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = pulling_value) %>%
    bind_rows(tibble(기준일자 = 최근영업일)) %>%
    group_by(기준일자) %>%
    filter(row_number()==1) %>%
    ungroup() %>% # 포트폴리오 단위로 계산하기 때문에, Factset에서 업데이트하는 지수의 경우 최근영업일이 있어야 lagging된 값 사용 가능
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) # 이건 블룸버그의 경우에 T-1데이터가 뭉개질 수 있음. 데이터 업데이트시간이 오후 12시30분이기 때문에
  
  # Source_Bloomberg 생성
  Source_Bloomberg <- pulled_data_SCIP %>%
    filter(dataseries_id %in% unique(data_information %>%
                                       filter(source=="Bloomberg") %>%
                                       pull(dataseries_id))) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>%
    arrange(기준일자) %>%
    mutate(data = map_dbl(data, ~as.numeric(rawToChar(unlist(.x))))) %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = data) %>%
    bind_rows(tibble(기준일자 = 최근영업일)) %>%
    group_by(기준일자) %>%
    filter(row_number()==1) %>%
    ungroup() %>%
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  #
  
  # Source_KIS 생성
  Source_KIS <-
    pulled_data_SCIP %>%
    filter(dataseries_id == 33) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>%
    arrange(기준일자) %>%
    select(-c(timestamp_observation)) %>%
    mutate(
      data = map(
        data,
        ~{
          json_string <- rawToChar(unlist(.x))
          # NaN을 null로 대체
          json_string_clean <- str_replace_all(json_string, "NaN", "null")
          jsonlite::parse_json(json_string_clean)
        }
      )
    ) %>%
    mutate(data = map_dbl(data, ~as.numeric(.x$totRtnIndex))) %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = data) %>%
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_BOS 생성
  
  Source_BOS <- pulled_data_BOS %>%
    mutate(기준일자 = ymd(STD_DT)) %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = MOD_STPR) %>%
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_ZEROIN 생성
  
  Source_ZEROIN <- pulled_data_ZEROIN %>%
    mutate(기준일자 = ymd(기준일자)) %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = SUIK_JISU) %>%
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_ECOS 생성
  Source_ECOS <- pulled_data_ECOS %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = 기준가_custom) %>%
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_RATB 생성
  
  
  Source_RATB <- pulled_data_RATB %>%
    mutate(기준일자 = ymd(기준일자)) %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = standardPrice) %>%
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_CUSTOM 생성
  Source_CUSTOM <- pulled_data_CUSTOM %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = 기준가_custom) %>%
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_combined 생성
  Source_factset %>%
    full_join(Source_Bloomberg , by = join_by(기준일자)) %>%
    full_join(Source_KIS , by = join_by(기준일자)) %>%
    full_join(Source_BOS , by = join_by(기준일자)) %>%
    full_join(Source_ZEROIN , by = join_by(기준일자)) %>%
    full_join(Source_ECOS , by = join_by(기준일자)) %>%
    full_join(Source_RATB , by = join_by(기준일자)) %>%
    full_join(Source_CUSTOM , by = join_by(기준일자)) %>%
    arrange(기준일자) %>%
    # mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) )) %>% #이건 주말에도 데이터가 있는 BOS, 특정 index의 경우가 있어 각 source별로 처리
    full_join(USDKRW %>%
                mutate(`return_USD/KRW`=`USD/KRW`/lag(`USD/KRW`)-1), by = join_by(기준일자)) %>%
    arrange(기준일자)->Source_combined
  
  #Source_combined %>% view()
  # 최종 결과 계산 및 가중 합계 계산
  results <-
    Source_combined %>%
    select(기준일자, for_pulling_universe_data$symbol,`USD/KRW`,`return_USD/KRW`) %>%
    # Korea_holiday 적용시 분석가능일이 뒤틀리는 경우 생기면 제거할것(아래4줄)
    mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays,1,0)) %>%
    mutate(across(.cols = (which(if_else(for_pulling_universe_data$region=="KR",1,0)==0)+1),
                  .fns = ~if_else(korea_holiday==1, NA, .x) )) %>%
    select(-korea_holiday) %>%
    timetk::pad_by_time(.date_var = 기준일자,.by = "day", .fill_na_direction = "down") %>%
    #mutate(across(.cols = contains("(USDKRW)"), .fns = ~.x * `USD/KRW`)) %>%
    mutate(raw_data_list = pmap(select(.,-c(기준일자),-contains("USD/KRW")),.f= ~c(...)),.after = 기준일자) %>%
    select(기준일자,raw_data_list,contains("USD/KRW")) %>%
    mutate(lag_raw_data_list = lag(raw_data_list),.after = 기준일자) %>%
    mutate(`return_USD/KRW_list` = map(`return_USD/KRW`, ~ rep(.x, nrow(for_pulling_universe_data)))) %>%
    mutate(daily_return_list = pmap(list(raw_data_list,lag_raw_data_list,`return_USD/KRW_list`),
                                    ~ {
                                      # (1-헤지비중)* (KR은 무조건 USD/KRW곱하는것  제외)
                                      FX_adjust<- (1-for_pulling_universe_data$hedge_ratio)*(1-(for_pulling_universe_data$region=="KR"))
                                      
                                      return_vector <- ..1/..2 - 1  # 요소별 이름만 필요한것이기 때문에 .x이용
                                      # 추적 배수 곱해주기. (-1, 2 등등 가능)
                                      return_vector <- return_vector*for_pulling_universe_data$tracking_multiple
                                      return_vector_hedge_ratio_considered<-(1+return_vector)*(1+..3*FX_adjust)-1
                                      return_vector_final<- (1+return_vector_hedge_ratio_considered)*(1+cost_adjust_vector_for_calc)-1
                                      return(return_vector_final)
                                    }
    ), .after = 기준일자) %>%
    select(-`return_USD/KRW_list`) %>%
    filter(dplyr::between(기준일자,left = ymd(start_date),right = ymd(end_date))) %>%
    #pull(daily_return_list) %>% head(6)
    #pull(raw_data_list) %>% head()
    #pull(lag_raw_data_list) %>% head(10)->ttt
    
    unnest_wider(col = daily_return_list ) %>%
    mutate(across(.cols =all_of(for_pulling_universe_data$symbol), .fns = ~ (cumprod(.x+1)-1), .names = "cum_{.col}"  ),.after = 기준일자 ) %>%
    mutate(daily_return_list = pmap(select(.,all_of(for_pulling_universe_data$symbol)),.f= ~c(...)  ),.after = 기준일자) %>%
    select(-all_of(for_pulling_universe_data$symbol))  %>%
    mutate(cummulative_return_list = pmap(select(., starts_with("cum_")),.f= ~c(...) %>% set_names(for_pulling_universe_data$symbol)),.after = 기준일자) %>%
    select(-contains("cum_")) %>%
    mutate(lagged_cummulative_return_list = lag(cummulative_return_list,
                                                default = list(
                                                  rep(0,length(for_pulling_universe_data$weight)) %>%
                                                    set_names(for_pulling_universe_data$symbol))), .after = 기준일자 ) %>%
    # 2. Driftweight 계산 (갱신된 가중치 벡터 생성)
    mutate(`Weight_fixed(T)` = map(
      cummulative_return_list,
      ~ {
        (1 + .x*0) * for_pulling_universe_data$weight # 요소별 이름만 필요한것이기 때문에 .x이용
      }
    ), .after = 기준일자) %>%
    mutate(`Weight_drift(T-1)` = map(
      lagged_cummulative_return_list,
      ~ {
        비중 <- (1 + .x) * for_pulling_universe_data$weight
        비중 / sum(비중) # 합이 1이 되도록 정규화
      }
    ), .after = 기준일자) %>%
    mutate(`Weight_drift(T)` = map(
      cummulative_return_list,
      ~ {
        비중 <- (1 + .x) * for_pulling_universe_data$weight
        비중 / sum(비중) # 합이 1이 되도록 정규화
      }
    ), .after = 기준일자) %>%
    # Fixed weight 수익률 계산
    mutate(weighted_sum_fixed = map_dbl(
      daily_return_list,
      ~ sum(c(.x) * for_pulling_universe_data$weight)
    ), .after = 기준일자) %>%
    # Drift weight 수익률 계산
    mutate(weighted_sum_drift = map2_dbl(.x = `Weight_drift(T-1)`,.y =daily_return_list ,
                                         ~ sum(.x * (.y))
    ), .after = 기준일자)
  
  return(list(results,for_pulling_universe_data))
}

# 
# 
# backtest_prep_table <- clipr::read_clip_tbl() %>% tibble() %>%
#   mutate(리밸런싱날짜 = ymd(리밸런싱날짜)) %>%
#   mutate(across(contains("datase"),.fns = ~as.character(.x)))
# backtest_prep_table<- sb_back %>%    select(-name,-분석시작가능일) %>%
#   mutate(리밸런싱날짜 = ymd("2000-01-04")) %>% 
# mutate(dataset_id="277",
#        dataseries_id="15") %>%
#  slice(2)
backtesting_for_users_input<- function(backtest_prep_table,rebalancing_option = "A",`trading_cost(bp)` = 0){
  print("### backtesting_for_users 함수 시작 ###")
  print("입력 데이터:")
  print(head(backtest_prep_table)) 
  
  colnames(backtest_prep_table) <- c("리밸런싱날짜", "Portfolio","dataset_id","dataseries_id","region", 
                                     "weight",  "hedge_ratio", "cost_adjust" ,"tracking_multiple")
  print(head(backtest_prep_table))
  backtest_prep_table<- backtest_prep_table %>% as_tibble()
  
  backtest_prep_table %>% 
    group_by(리밸런싱날짜, Portfolio) %>% 
    nest() %>% 
    mutate(dataset_id_vector    = map(data, ~ .x$dataset_id),
           dataseries_id_vector    = map(data, ~ .x$dataseries_id ),
           region_vector     =  map(data, ~ .x$region),
           weight_vector     =  map(data, ~ .x$weight),
           hedge_ratio_vector = map(data, ~ .x$hedge_ratio),
           cost_adjust_vector = map(data, ~ .x$cost_adjust),
           tracking_multiple_vector = map(data, ~ .x$tracking_multiple)
    ) %>%
    ungroup() %>%
    arrange(리밸런싱날짜,Portfolio) %>% 
    group_by(Portfolio) %>%
    mutate(리밸런싱마감일= lead(리밸런싱날짜,n=1)) %>%
    mutate(리밸런싱마감일= if_else(is.na(리밸런싱마감일),ymd(최근영업일), 리밸런싱마감일 )) %>%
    ungroup() %>%
    arrange(Portfolio)->MP_VP_BM_prep
  
  
  tictoc::tic()
  MP_VP_BM_prep  %>% 
    arrange(Portfolio,리밸런싱날짜) %>% 
    mutate(backtest= pmap(list(dataset_id_vector,dataseries_id_vector,region_vector,
                               weight_vector,hedge_ratio_vector,cost_adjust_vector,tracking_multiple_vector,
                               리밸런싱날짜,리밸런싱마감일),
                          .f = ~calculate_BM_results_bulk_for_users_input(dataset_id_vector    = ..1,
                                                                          dataseries_id_vector = ..2,
                                                                          region_vector        = ..3,
                                                                          weight_vector        = ..4,
                                                                          hedge_ratio_vector   = ..5,
                                                                          cost_adjust_vector   = ..6,
                                                                          tracking_multiple_vector = ..7,
                                                                          start_date        = ..8,
                                                                          end_date          = ..9),
                          .progress = TRUE))  ->MP_VP_BM_results
  tictoc::toc()
  
  
  
  
  MP_VP_BM_results %>% select(리밸런싱날짜,Portfolio,backtest) %>% 
    mutate(backtest_descriptrion = map(backtest,.f= ~.x[[2]]),.keep = "unused") %>% 
    unnest(backtest_descriptrion) ->MP_VP_BM_results_descriptrion
  
  if(rebalancing_option == "A"){
    MP_VP_BM_results %>% 
      select(리밸런싱날짜,Portfolio,backtest) %>% 
      mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
      group_by(Portfolio) %>% 
      unnest(backtest_res) %>% 
      # 그룹화: 기준일자별로 리밸런싱날짜가 빠른/늦은 경우 처리
      group_by(Portfolio, 기준일자)  %>% 
      reframe(
        리밸런싱날짜 = last(리밸런싱날짜),
        weighted_sum_drift = first(weighted_sum_drift), # 리밸런싱날짜 빠른 값
        weighted_sum_fixed = first(weighted_sum_fixed), # 리밸런싱날짜 빠른 값
        `Weight_drift(T)`   = list(first(`Weight_drift(T)`)),
        `Weight_fixed(T)`   = list(first(`Weight_fixed(T)`)),
        `Weight_drift(T-1)` = list(first(`Weight_drift(T-1)`)), # 리밸런싱날짜 빠른 값(수익률계산에 사용된 비중이어야됨.))
        `Weight_fixed(T-1)` = list(first(`Weight_fixed(T)`)) # 리밸런싱날짜 빠른 값(수익률계산에 사용된 비중이어야됨.) fixed의 경우 T-1변수 안만들었기 때문에 T 그대로 사용 
      )->MP_VP_BM_results_core 
    
    MP_VP_BM_results %>% 
      select(리밸런싱날짜,Portfolio,backtest) %>% 
      mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
      unnest(backtest_res) %>% 
      select(-contains("weighted_sum"),-contains("Weight_")) %>% 
      group_by(Portfolio,기준일자) %>% 
      filter(row_number()==1) %>% # (A,A) = 포지션도 리밸런싱전일자꺼, 수익률도 리밸런싱전일꺼로 계산 
      ungroup() ->MP_VP_BM_results_raw 
    
  }else{
    MP_VP_BM_results %>% 
      select(리밸런싱날짜,Portfolio,backtest) %>% 
      mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
      group_by(Portfolio) %>% 
      unnest(backtest_res) %>% 
      # 그룹화: 기준일자별로 리밸런싱날짜가 빠른/늦은 경우 처리
      group_by(Portfolio, 기준일자)  %>% 
      reframe(
        리밸런싱날짜 = last(리밸런싱날짜),
        weighted_sum_drift = last(weighted_sum_drift), # 리밸런싱날짜 늦은 값
        weighted_sum_fixed = last(weighted_sum_fixed), # 리밸런싱날짜 늦은 값
        `Weight_drift(T)`   = list(last(`Weight_drift(T)`)),  # 리밸런싱날짜 늦은 값
        `Weight_fixed(T)`   = list(last(`Weight_fixed(T)`)),
        `Weight_drift(T-1)` = list(last(`Weight_drift(T-1)`)), # 리밸런싱날짜 늦은 값
        `Weight_fixed(T-1)` = list(last(`Weight_fixed(T)`)) # 리밸런싱날짜 늦은 값, fixed의 경우 T-1변수 안만들었기 때문에 T 그대로 사용 
        
      ) ->MP_VP_BM_results_core 
    # unnest_wider(col = starts_with("Weight_"),names_sep = "-") -> MP_VP_BM_results_core
    
    MP_VP_BM_results %>% 
      select(리밸런싱날짜,Portfolio,backtest) %>% 
      mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
      unnest(backtest_res) %>% 
      select(-contains("weighted_sum"),-contains("Weight_")) %>% 
      group_by(Portfolio,기준일자) %>% 
      filter(row_number()==2) %>% # (B,B) = 포지션도 리밸런싱일자, 수익률도 리밸런싱일로 계산 
      ungroup() ->MP_VP_BM_results_raw 
  }
  
  
  MP_VP_BM_results %>% 
    select(리밸런싱날짜,Portfolio,backtest) %>% 
    mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
    group_by(Portfolio) %>% 
    unnest(backtest_res) %>% 
    group_by(Portfolio, 기준일자)  %>% 
    filter(n()>=2) %>% # 리밸런싱일자에 턴오버 계산하기
    ungroup() %>% 
    group_by(Portfolio,리밸런싱날짜,기준일자) %>% 
    mutate(symbol = list(names(unlist(`Weight_fixed(T)`)))) %>% 
    ungroup() %>% 
    select(리밸런싱날짜,Portfolio,기준일자,contains("Weight_"),symbol) %>% 
    unnest(c(`Weight_drift(T)`,`Weight_drift(T-1)`,`Weight_fixed(T)`,symbol)) %>% 
    inner_join(MP_VP_BM_results_descriptrion %>% 
                 select(리밸런싱날짜, Portfolio, dataset_id, dataseries_id,symbol), by = join_by(리밸런싱날짜,symbol, Portfolio)) %>% 
    group_by(기준일자,Portfolio,리밸런싱날짜,dataset_id,dataseries_id) %>% 
    reframe(across(.cols = contains("Weight"),.f = ~sum(.x,na.rm = TRUE))) %>% 
    mutate(key = paste0(dataset_id, "_",dataseries_id)) %>% 
    group_by(기준일자,Portfolio) %>%
    complete(리밸런싱날짜,key,fill = list(`Weight_drift(T)`=0,
                                    `Weight_drift(T-1)`=0,
                                    `Weight_fixed(T)`=0)) %>% 
    group_by(기준일자,Portfolio,key)  %>% 
    reframe(turn_over_drift = first(`Weight_drift(T-1)`)-last(`Weight_fixed(T)`),
            turn_over_fixed = first(`Weight_fixed(T)`)-last(`Weight_fixed(T)`) )  %>% 
    group_by(기준일자,Portfolio) %>% 
    reframe(turn_over_drift = sum(abs(turn_over_drift))/2, 
            turn_over_fixed = sum(abs(turn_over_fixed))/2)->turn_over_res
  
  MP_VP_BM_results_core<- MP_VP_BM_results_core %>% 
    left_join(turn_over_res) %>% 
    mutate(across(.cols = contains("turn_over"),.fns = ~replace_na(.x,0))) %>% 
    mutate(weighted_sum_drift =weighted_sum_drift - turn_over_drift*`trading_cost(bp)`/10000,
           weighted_sum_fixed =weighted_sum_fixed - turn_over_fixed*`trading_cost(bp)`/10000) 
  
  # MP_VP_BM_results %>% 
  #   select(리밸런싱날짜,Portfolio,backtest) %>% 
  #   mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
  #   unnest(backtest_res) %>% 
  #   select(-contains("weighted_sum"),-contains("Weight_")) ->MP_VP_BM_results_raw 
  #unnest_wider(col = ends_with("_list"),names_sep = "-") ->MP_VP_BM_results_raw
  
  res <- list("백테스트내역"=MP_VP_BM_results_descriptrion,
              "백테스트계산_Perform&Position"=MP_VP_BM_results_core,
              "백테스트계산_raw"=MP_VP_BM_results_raw)
  return(res)  
}
backtesting_for_users<- function(backtest_prep_table,rebalancing_option = "A",`trading_cost(bp)` = 0){
  print("### backtesting_for_users 함수 시작 ###")
  print("입력 데이터:")
  print(head(backtest_prep_table)) 
  
  colnames(backtest_prep_table) <- c("리밸런싱날짜", "Portfolio","dataset_id","dataseries_id","region", 
                                     "weight",  "hedge_ratio", "cost_adjust" ,"tracking_multiple")
  print(head(backtest_prep_table))
  backtest_prep_table<- backtest_prep_table %>% as_tibble()
  
  backtest_prep_table %>% 
    group_by(리밸런싱날짜, Portfolio) %>% 
    nest() %>% 
    mutate(dataset_id_vector    = map(data, ~ .x$dataset_id),
           dataseries_id_vector    = map(data, ~ .x$dataseries_id ),
           region_vector     =  map(data, ~ .x$region),
           weight_vector     =  map(data, ~ .x$weight),
           hedge_ratio_vector = map(data, ~ .x$hedge_ratio),
           cost_adjust_vector = map(data, ~ .x$cost_adjust),
           tracking_multiple_vector = map(data, ~ .x$tracking_multiple)
    ) %>%
    ungroup() %>%
    arrange(리밸런싱날짜,Portfolio) %>% 
    group_by(Portfolio) %>%
    mutate(리밸런싱마감일= lead(리밸런싱날짜,n=1)) %>%
    mutate(리밸런싱마감일= if_else(is.na(리밸런싱마감일),ymd(최근영업일), 리밸런싱마감일 )) %>%
    ungroup() %>%
    arrange(Portfolio)->MP_VP_BM_prep
  
  
  tictoc::tic()
  MP_VP_BM_prep  %>% 
    arrange(Portfolio,리밸런싱날짜) %>% 
    mutate(backtest= pmap(list(dataset_id_vector,dataseries_id_vector,region_vector,
                               weight_vector,hedge_ratio_vector,cost_adjust_vector,tracking_multiple_vector,
                               리밸런싱날짜,리밸런싱마감일),
                          .f = ~calculate_BM_results_bulk_for_users(dataset_id_vector    = ..1,
                                                                    dataseries_id_vector = ..2,
                                                                    region_vector        = ..3,
                                                                    weight_vector        = ..4,
                                                                    hedge_ratio_vector   = ..5,
                                                                    cost_adjust_vector   = ..6,
                                                                    tracking_multiple_vector = ..7,
                                                                    start_date        = ..8,
                                                                    end_date          = ..9),
                          .progress = TRUE))  ->MP_VP_BM_results
  tictoc::toc()
  
  
  
  
  MP_VP_BM_results %>% select(리밸런싱날짜,Portfolio,backtest) %>% 
    mutate(backtest_descriptrion = map(backtest,.f= ~.x[[2]]),.keep = "unused") %>% 
    unnest(backtest_descriptrion) ->MP_VP_BM_results_descriptrion
  
  if(rebalancing_option == "A"){
    MP_VP_BM_results %>% 
      select(리밸런싱날짜,Portfolio,backtest) %>% 
      mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
      group_by(Portfolio) %>% 
      unnest(backtest_res) %>% 
      # 그룹화: 기준일자별로 리밸런싱날짜가 빠른/늦은 경우 처리
      group_by(Portfolio, 기준일자)  %>% 
      reframe(
        리밸런싱날짜 = last(리밸런싱날짜),
        weighted_sum_drift = first(weighted_sum_drift), # 리밸런싱날짜 빠른 값
        weighted_sum_fixed = first(weighted_sum_fixed), # 리밸런싱날짜 빠른 값
        `Weight_drift(T)`   = list(first(`Weight_drift(T)`)),
        `Weight_fixed(T)`   = list(first(`Weight_fixed(T)`)),
        `Weight_drift(T-1)` = list(first(`Weight_drift(T-1)`)), # 리밸런싱날짜 빠른 값(수익률계산에 사용된 비중이어야됨.))
        `Weight_fixed(T-1)` = list(first(`Weight_fixed(T)`)) # 리밸런싱날짜 빠른 값(수익률계산에 사용된 비중이어야됨.) fixed의 경우 T-1변수 안만들었기 때문에 T 그대로 사용 
      )->MP_VP_BM_results_core 
    
    MP_VP_BM_results %>% 
      select(리밸런싱날짜,Portfolio,backtest) %>% 
      mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
      unnest(backtest_res) %>% 
      select(-contains("weighted_sum"),-contains("Weight_")) %>% 
      group_by(Portfolio,기준일자) %>% 
      filter(row_number()==1) %>% # (A,A) = 포지션도 리밸런싱전일자꺼, 수익률도 리밸런싱전일꺼로 계산 
      ungroup() ->MP_VP_BM_results_raw 
    
  }else{
    MP_VP_BM_results %>% 
      select(리밸런싱날짜,Portfolio,backtest) %>% 
      mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
      group_by(Portfolio) %>% 
      unnest(backtest_res) %>% 
      # 그룹화: 기준일자별로 리밸런싱날짜가 빠른/늦은 경우 처리
      group_by(Portfolio, 기준일자)  %>% 
      reframe(
        리밸런싱날짜 = last(리밸런싱날짜),
        weighted_sum_drift = last(weighted_sum_drift), # 리밸런싱날짜 늦은 값
        weighted_sum_fixed = last(weighted_sum_fixed), # 리밸런싱날짜 늦은 값
        `Weight_drift(T)`   = list(last(`Weight_drift(T)`)),  # 리밸런싱날짜 늦은 값
        `Weight_fixed(T)`   = list(last(`Weight_fixed(T)`)),
        `Weight_drift(T-1)` = list(last(`Weight_drift(T-1)`)), # 리밸런싱날짜 늦은 값
        `Weight_fixed(T-1)` = list(last(`Weight_fixed(T)`)) # 리밸런싱날짜 늦은 값, fixed의 경우 T-1변수 안만들었기 때문에 T 그대로 사용 
        
      ) ->MP_VP_BM_results_core 
    # unnest_wider(col = starts_with("Weight_"),names_sep = "-") -> MP_VP_BM_results_core
    
    MP_VP_BM_results %>% 
      select(리밸런싱날짜,Portfolio,backtest) %>% 
      mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
      unnest(backtest_res) %>% 
      select(-contains("weighted_sum"),-contains("Weight_")) %>% 
      group_by(Portfolio,기준일자) %>% 
      filter(row_number()==2) %>% # (B,B) = 포지션도 리밸런싱일자, 수익률도 리밸런싱일로 계산 
      ungroup() ->MP_VP_BM_results_raw 
  }
  
  
  MP_VP_BM_results %>% 
    select(리밸런싱날짜,Portfolio,backtest) %>% 
    mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
    group_by(Portfolio) %>% 
    unnest(backtest_res) %>% 
    group_by(Portfolio, 기준일자)  %>% 
    filter(n()>=2) %>% # 리밸런싱일자에 턴오버 계산하기
    ungroup() %>% 
    group_by(Portfolio,리밸런싱날짜,기준일자) %>% 
    mutate(symbol = list(names(unlist(`Weight_fixed(T)`)))) %>% 
    ungroup() %>% 
    select(리밸런싱날짜,Portfolio,기준일자,contains("Weight_"),symbol) %>% 
    unnest(c(`Weight_drift(T)`,`Weight_drift(T-1)`,`Weight_fixed(T)`,symbol)) %>% 
    inner_join(MP_VP_BM_results_descriptrion %>% 
                 select(리밸런싱날짜, Portfolio, dataset_id, dataseries_id,symbol), by = join_by(리밸런싱날짜,symbol, Portfolio)) %>% 
    group_by(기준일자,Portfolio,리밸런싱날짜,dataset_id,dataseries_id) %>% 
    reframe(across(.cols = contains("Weight"),.f = ~sum(.x,na.rm = TRUE))) %>% 
    mutate(key = paste0(dataset_id, "_",dataseries_id)) %>% 
    group_by(기준일자,Portfolio) %>%
    complete(리밸런싱날짜,key,fill = list(`Weight_drift(T)`=0,
                                    `Weight_drift(T-1)`=0,
                                    `Weight_fixed(T)`=0)) %>% 
    group_by(기준일자,Portfolio,key)  %>% 
    reframe(turn_over_drift = first(`Weight_drift(T-1)`)-last(`Weight_fixed(T)`),
            turn_over_fixed = first(`Weight_fixed(T)`)-last(`Weight_fixed(T)`) )  %>% 
    group_by(기준일자,Portfolio) %>% 
    reframe(turn_over_drift = sum(abs(turn_over_drift))/2, 
            turn_over_fixed = sum(abs(turn_over_fixed))/2)->turn_over_res
  
  MP_VP_BM_results_core<- MP_VP_BM_results_core %>% 
    left_join(turn_over_res) %>% 
    mutate(across(.cols = contains("turn_over"),.fns = ~replace_na(.x,0))) %>% 
    mutate(weighted_sum_drift =weighted_sum_drift - turn_over_drift*`trading_cost(bp)`/10000,
           weighted_sum_fixed =weighted_sum_fixed - turn_over_fixed*`trading_cost(bp)`/10000) 
  
  # MP_VP_BM_results %>% 
  #   select(리밸런싱날짜,Portfolio,backtest) %>% 
  #   mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
  #   unnest(backtest_res) %>% 
  #   select(-contains("weighted_sum"),-contains("Weight_")) ->MP_VP_BM_results_raw 
  #unnest_wider(col = ends_with("_list"),names_sep = "-") ->MP_VP_BM_results_raw
  
  res <- list("백테스트내역"=MP_VP_BM_results_descriptrion,
              "백테스트계산_Perform&Position"=MP_VP_BM_results_core,
              "백테스트계산_raw"=MP_VP_BM_results_raw)
  return(res)  
}



plot_bubble_chart <- function(annualized_inform_df, period){
  
  annualized_inform_df %>%
    filter(name == period) ->filtered_data
  
  # 전체 데이터에서 Sharpe Ratio의 전역 범위 계산
  global_range <- range(filtered_data$adjusted_sharpe_ratio, na.rm = TRUE)
  # 예: 전역 스케일링 함수 정의 (점 크기를 5~30으로 조정)
  my_scale <- function(x){
    scales::rescale(x, to = c(min(global_range), max(global_range)), 
                    from = global_range)
  } 
  
  filtered_data %>%
    group_by(Portfolio) %>%
    e_charts(annualized_risk) %>%
    # e_effect_scatter(annualized_return, size = adjusted_sharpe_ratio, scale = my_scale,
    #           symbol_size = 25) %>% 
    e_scatter(annualized_return, size = adjusted_sharpe_ratio, scale = my_scale,
              symbol_size = 25) %>%
    #e_title("Risk - Return Profile") %>%
    e_x_axis(name = "연율화 변동성(%)", 
             nameLocation = "middle",   # 축 이름의 위치를 가운데로 설정
             nameGap = 25,   
             formatter = e_axis_formatter("percent", digits = 2)) %>%
    e_y_axis(name = "연율화 수익률(%)", 
             nameLocation = "middle",   # 축 이름의 위치를 가운데로 설정
             nameGap = 50,   
             nameRotate = 90,
             formatter = e_axis_formatter("percent", digits = 2)) %>%
    e_legend(top = "bottom",type = "scroll") %>% 
    e_grid(bottom = "20%") %>%# 차트의 하단 여백을 추가하여 레전드를 더 아래로 배치
    e_color(colorRampPalette(c('#5470c6','#91cc75', '#fac858','#ee6666'))(length(unique(annualized_inform_df$Portfolio)))) %>% 
    e_add_nested('extra', adjusted_sharpe_ratio) %>%
    e_add_nested('PortfolioName', Portfolio) %>%  # Ensure Portfolio is a character vector
    e_tooltip(trigger = "item", formatter = htmlwidgets::JS("
    function(params) {
    
      var portfolioColor = params.color;
      var portfolioName = params.data.PortfolioName.Portfolio;  // Access PortfolioName directly
      return('<div style=\"color:' + portfolioColor + ';\"><strong>' + portfolioName + ' :' +  '</strong></div>' +
      '<div>연율화수익률: ' + (params.value[1] * 100).toFixed(2) + '%' + 
      '</div><div>연율화변동성: ' + (params.value[0] * 100).toFixed(2) + '%' +
      '</div><div>수정샤프지수: ' + params.data.extra.adjusted_sharpe_ratio.toFixed(2) + '</div>');
    }
  ")) %>% 
    e_toolbox_feature(feature = "saveAsImage")
  
}


plot_cum_return_and_Drawdown<- function(perform_data,input_date){
  
  
  df_wide <- perform_data %>%
    filter(기준일자<=input_date) %>% 
    select(기준일자, Portfolio, 누적수익률, draw_down) %>%
    # names_from=과 values_from= 에 자신이 원하는 이름(누적수익률 or drawdown 등) 매핑
    pivot_wider(
      names_from = Portfolio,
      values_from = c(누적수익률, draw_down),
      # 필요시, 중복될 수 있으므로 구분자 지정
      names_sep = "|"
    )
  
  # 예: df_wide 컬럼
  # 기준일자, 누적수익률|A, draw_down|A, 누적수익률|B, draw_down|B, ...
  
  # ------------------------------------------------------------------------------#
  # 2) echarts4r로 라인 그리기
  #    - 같은 포트폴리오는 같은 color
  #    - y축 index(0 vs 1)에 따라 라인타입(solid vs dashed) 다름
  # ------------------------------------------------------------------------------#
  
  # 2-1) 포트폴리오 목록과 색상 팔레트 지정
  portfolios <- unique(perform_data$Portfolio)  # 예: 실제 데이터에 맞게 수정
  n_port <- length(portfolios)
  
  # Dark2 팔레트를 필요한 개수(n_port)만큼 확장
  palette <- colorRampPalette(c('#5470c6','#91cc75', '#fac858','#ee6666'))(n_port)
  color_mapping_df<- tibble(color_mapping = sort(as.factor(portfolios))) %>% 
    arrange(color_mapping) %>% 
    mutate(palette = palette)
  
  # 2-2) 차트 시작
  p <- df_wide %>%
    e_charts(x = 기준일자) 
  
  # 2-3) 각 포트폴리오마다 "누적수익률" / "draw_down" 라인 차례대로 추가
  for(i in seq_along(portfolios)){
    color_mapped = color_mapping_df %>% filter(color_mapping == portfolios[i]) %>% pull(palette)
    
    p <- p %>%
      # (1) 누적수익률 라인: y_index=0, solid
      e_line_(
        serie     = paste0("누적수익률|", portfolios[i]),
        name      = paste0(portfolios[i], " 누적수익률"),
        y_index   = 0,showSymbol = FALSE,
        lineStyle = list(type = "solid",width = 2, opacity = 1),
        color     = color_mapped
      ) %>%
      # (2) drawdown 라인: y_index=1, dashed
      e_area_(
        serie     = paste0("draw_down|", portfolios[i]),
        name      = paste0(portfolios[i], " Drawdown"),
        y_index   = 1,showSymbol = FALSE,
        color     = color_mapped,
        areaStyle = list(opacity = 0.2),
        lineStyle = list(opacity = 0.1),
        itemStyle = list(opacity = 0.1)
        
      ) 
  }
  
  # 2-4) Y축 두 개 추가 (0번: 누적수익률, 1번: Drawdown)
  p <- p %>%
    e_y_axis_(
      index      = 0,
      name       = "누적수익률(%)",
      formatter  = e_axis_formatter("percent", digits = 2)
    ) %>%
    e_y_axis_(
      index      = 1,
      name       = "Drawdown(%)",
      # 필요시 min, max 등 지정
      min        = -1,
      max        = 0,
      scale      = FALSE,
      formatter  = e_axis_formatter("percent", digits = 2)
    ) %>%
    # 필요시 X축 범위
    e_x_axis(
      min = min(df_wide$기준일자),
      max = max(df_wide$기준일자)
    ) %>%
    # 툴팁 설정
    e_tooltip(
      trigger     = "axis",
      axisPointer = list(type = "cross"),
      formatter   = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
    ) %>%
    e_title("누적수익률 & Drawdown ", "") %>% 
    e_legend(top = "bottom",type = "scroll") %>% 
    e_toolbox_feature(feature = "saveAsImage")%>%
    e_datazoom(
      type = "slider",x_index = c(0, 1), show = TRUE,
      height = 15#,   # 슬라이더 두께를 얇게 설정
    ) 
  #e_datazoom(type = c("slider", "inside"), x_index = 0)
  # 만약 Y축에 대해서도 줌을 적용하고 싶다면 y_index 옵션을 활용할 수도 있습니다.
  # 예: e_datazoom(type = c("slider", "inside"), x_index = 0, y_index = 0)
  
  
  
  # 2-5) 완성된 차트 출력
  return(p)
  
}



return_ref_date<- function(input_date,period){
  
  # input_date <- "2025-02-09"
  input_date <- ymd(input_date)
  # print("날짜입력중입니다:")
  # print(input_date)
  start_of_month <- floor_date(input_date, "month")
  end_of_month <- (ceiling_date(input_date, "month") - days(1))
  # 해당 월의 모든 날짜
  all_dates <- seq(start_of_month, end_of_month, by = "day")
  
  # 평일만 추출
  weekdays_only <- all_dates[!(wday(all_dates) %in% c(1,7))]
  # 휴장일 제외
  tradingdays_only <- weekdays_only[! (weekdays_only %in% KOREA_holidays)]
  last_day_of_month<- input_date == max(tradingdays_only)
  
  calendar_date <- case_when(period == "1M"~ add_with_rollback(input_date ,months(-1)),
                             period == "3M"~ add_with_rollback(input_date ,months(-3)),
                             period == "6M"~ add_with_rollback(input_date ,months(-6)),
                             period == "1Y"~ add_with_rollback(input_date ,months(-12)),
                             period == "YTD"~ make_date(year(input_date))-days(1)
  )
  
  if(last_day_of_month==TRUE){
    calendar_date<-  ceiling_date(calendar_date,unit = "month") -days(1)
  }
  calendar_date<- calendar_date#+days(1)
  return(calendar_date)
}


return_ref_date_v2<- function(input_date,period_num,period_term){
  
  # input_date <- "2025-02-09"
  input_date <- ymd(input_date)
  
  
  input_date %>% enframe(name = NULL,value = "기준일자") %>% 
    mutate(마지막영업일= (기준일자 %in% 연월별마지막영업일) | month(기준일자)!=month(기준일자+days(1)),
           calendar_date = case_when(period_term == "D"~ add_with_rollback(기준일자 ,days(-period_num)),
                                     period_term == "W"~ add_with_rollback(기준일자 ,weeks(-period_num)),
                                     period_term == "M"~ add_with_rollback(기준일자 ,months(-period_num)),
                                     period_term == "Y"~ add_with_rollback(기준일자 ,years(-period_num)),
                                     period_term == "YTD"~ make_date(year(기준일자))-days(1),
                                     period_term == "MTD" ~ make_date(year(기준일자), month(기준일자), 1) - days(1),
                                     period_term == "QTD" ~ make_date(year(기준일자), (quarter(기준일자) - 1) * 3 + 1, 1) - days(1),
                                     period_term == "HTD" ~ make_date(year(기준일자), if_else(month(기준일자) <= 6, 1, 7), 1) - days(1)
           )) %>% 
    mutate( calendar_date = if_else(마지막영업일==TRUE & period_term %in%c("M","Y") ,
                                    ceiling_date(calendar_date,unit = "month") -days(1) ,calendar_date )  ) %>% 
    pull(calendar_date)  ->calendar_date
  
  calendar_date<- calendar_date#+days(1)
  return(ymd(calendar_date))
}




return_first_weekly_date <- function(start_date,end_date){
  #end_date<- "2024-11-29";start_date <- "2024-05-31"
  if(!is.na(start_date) & !is.na(end_date)){
    
    start_date <- ymd(start_date)
    end_date <- ymd(end_date)
    
  }else{
    return(NA)
  }
  
  timetk::tk_make_timeseries(start_date,end_date,by = "day") %>% 
    enframe(value = "Date") %>% 
    filter(wday(Date,label = T) == wday(end_date,label = T)) %>% 
    filter(Date==nth(Date,n=1)) %>% pull(Date) ->first_wday
  
  holiday_calendar %>% 
    mutate(across(.cols = contains("영업일"), .fns = ~ymd(.x))) %>% 
    filter(hldy_yn =="N") %>% 
    filter(기준일자>first_wday-days(7), 기준일자 <= start_date) %>% nrow()-> filtering_first_row
  
  if(filtering_first_row != 0){
    first_wday <- first_wday+days(7)
  }
  return(first_wday)
}


# 무위험수익률 구해서 밑의 함수 적용
weekly_calculation_Portfolio <- function(weekly_return_df,Port_name,start_date,end_date,annualized_factor){
  
  filtered_weekly_return<- weekly_return_df %>% 
    filter(기준일자 <= end_date ) %>% # 새로 추가됨
    filter(wday(기준일자)==wday(end_date)) %>% 
    filter(기준일자 >= start_date) %>% 
    filter(Portfolio == Port_name)
  # version 추가되면 여기에 추가
  filtered_vec_주간수익률<- filtered_weekly_return %>% pull(주간수익률) 
  filtered_vec_주간로그수익률<- filtered_weekly_return %>% pull(주간로그수익률) 
  
  res <- list(
    "연율화수익률_v1"=mean(filtered_vec_주간수익률,na.rm=FALSE)*annualized_factor,
    "연율화변동성_v1"=sd(filtered_vec_주간수익률,na.rm=FALSE)*sqrt(annualized_factor),
    "연율화수익률_v2"=mean(filtered_vec_주간로그수익률,na.rm=FALSE)*annualized_factor,
    "연율화변동성_v2"=sd(filtered_vec_주간로그수익률,na.rm=FALSE)*sqrt(annualized_factor)
    
  )
  return(res)
}


#end_date  <- ymd("2025-02-13")
#start_date <- ymd("2025-02-01")
weekly_calculation_Risk_free <- function(start_date,end_date,annualized_factor){
  
  if(!is.na(start_date) & !is.na(end_date) &start_date>=end_date){
    res<- ECOS_historical_주간수익률 %>% 
      group_by(dataset_id) %>% 
      reframe(
        연율화수익률_v1=NA,
        연율화변동성_v1=NA,
        연율화수익률_v2=NA,
        연율화변동성_v2=NA
      )
    
  }else{
    
    filtered_weekly_return<- ECOS_historical_주간수익률 %>% 
      filter(기준일자 <= end_date ) %>% # 새로 추가됨
      filter(wday(기준일자)==wday(end_date)) %>% 
      filter(기준일자 >= start_date)
    
    res <- filtered_weekly_return %>% 
      group_by(dataset_id) %>% 
      reframe(
        연율화수익률_v1=mean(주간수익률,na.rm=FALSE)*annualized_factor,
        연율화변동성_v1=sd(주간수익률,na.rm=FALSE)*sqrt(annualized_factor),
        연율화수익률_v2=mean(주간로그수익률,na.rm=FALSE)*annualized_factor,
        연율화변동성_v2=sd(주간로그수익률,na.rm=FALSE)*sqrt(annualized_factor)
      ) 
  }
  
  return(res)
}

return_rf_index <- function(itemcode){
  # 한국은행기준금리만 stat_code가 다름
  stat_code_set <- if_else(itemcode =="0101000","722Y001","817Y002")
  colname_set <-  case_when(
    itemcode =="0101000"   ~"한국은행기준금리",
    itemcode =="010101000" ~"콜금리",
    itemcode =="010901000" ~"KOFR(공시RFR)",
    itemcode =="010150000" ~"KORIBOR(3개월)",
    itemcode =="010502000" ~"CD(91일)",
    itemcode =="010503000" ~"CP(91일)",
    itemcode =="010400000" ~"통안증권(91일)"
  )
  
  rf <- ecos::statSearch(stat_code = stat_code_set,item_code1 = itemcode ,cycle ="D",
                         start_time = "19000101",
                         end_time =최근영업일 %>% str_remove_all("-") ) %>% tibble() %>% 
    select(기준일자=time,Rf_Return = data_value) %>%
    mutate(기준일자= ymd(기준일자)) %>% 
    timetk::pad_by_time(.fill_na_direction = "down",.by = "day",.date_var = "기준일자") %>% 
    mutate(일별수익률 = Rf_Return/100/365) %>% 
    mutate(data_cum =1000*(cumprod(일별수익률+1)) ) %>% 
    select(기준일자, data_cum) %>% 
    set_names(c("기준일자",colname_set)) %>% 
    mutate(dataset_id = colnames(.)[2],
           dataseries_id = "Custom_index" ) %>% 
    set_names(c("기준일자","기준가_custom","dataset_id","dataseries_id"))
  # group_by(wday(기준일자)) %>% 
  # mutate(직전주_KR_CD91지수 = lag(KR_CD91지수, n = 1)) %>%
  # mutate(주별수익률_rf = (KR_CD91지수 / 직전주_KR_CD91지수 - 1)) %>% 
  # ungroup() %>% 
  # select(-`wday(기준일자)`,-직전주_KR_CD91지수) %>% 
  # filter(!is.na(주별수익률_rf))
}
annualized_geometric_return <- function(period_return_table, total_days_table,총일수 = 365.25){
  
  period_return_table %>% 
    rename(start= 누적) %>% 
    pivot_longer(-c(Portfolio,분석시작일,분석종료일),values_to = "period_return") %>% 
    left_join(total_days_table %>% 
                select(Portfolio,분석시작일,분석종료일,name,total_days=value)) %>% 
    mutate(연율화수익률_v3 = (1+period_return)^(총일수/total_days )-1)
  
}

return_res_tables<- function(result_core_prep,
                             input_date , 
                             rf_dataset_id ="CD(91일)", # if custom 이면 직접 입력가능하게.
                             rf_custom_input = NULL,
                             annualized_return_method="v3",
                             annualized_risk_method="v2",
                             annualized_factor=52
){
  
  #result_core_prep <- result_core_prep %>% 
  # filter(기준일자>=start_date)
  # 한국휴장일 처리를 여기서? -> 맨처음 기준가 1000원 추가한다음 한국휴장일 NA처리 후 ffill하면될듯 
  result_core_prep%>% select(-`Weight(T)`) %>% 
    #set_names(c("Portfolio","기준일자","리밸런싱날짜","Return(T)","Weight(T)")) %>% 
    bind_rows(
      result_core_prep %>% select(-`Weight(T)`) %>% 
        #set_names(c("Portfolio","기준일자","리밸런싱날짜","Return(T)","Weight(T)")) %>% 
        group_by(Portfolio) %>% 
        filter(기준일자 == min(기준일자)) %>% 
        ungroup() %>% 
        mutate(기준일자 = 기준일자-days(1)) %>% 
        mutate(across(.cols = `Return(T)`,.fns = ~0))
      
    ) %>% 
    arrange(기준일자) %>% 
    group_by(Portfolio) %>% 
    mutate(누적수익률 = cumprod(`Return(T)`+1)-1,
           draw_down =( (1+누적수익률)/((1+cummax(누적수익률)))-1),
           MDD = min(draw_down)
    ) %>% 
    ungroup() -> perform_historical
  
  #한국휴장일 처리 유무에 따른 활성/비활성   
  # perform_historical %>% 
  #   mutate(기준가 = 1000*(1+누적수익률)) %>% 
  #   select(Portfolio,기준일자,리밸런싱날짜,기준가) ->results_기준가
  # # 
  # clipr::read_clip_tbl()->tete
  # tete %>% tibble() %>%
  #   mutate(기준일자 = ymd(기준일자)) %>%
  #   pivot_longer(cols = -기준일자,names_to = "Portfolio",values_to = "기준가") %>% 
  #   mutate(리밸런싱날짜=min(기준일자)) %>%
  #   mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays,1,0)) %>%
  #   mutate(across(.cols = 기준가,.fns = ~if_else(korea_holiday==1, NA, .x) )) %>%
  #   timetk::pad_by_time(.date_var = 기준일자,.by = "day", .fill_na_direction = "down") %>%
  #   ungroup() %>%
  #   select(-korea_holiday) ->results_기준가
  perform_historical %>% 
    group_by(Portfolio) %>% 
    mutate(기준가 = 1000*(1+누적수익률)) %>% 
    select(Portfolio,기준일자,리밸런싱날짜,기준가) %>% 
    mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays,1,0)) %>%
    mutate(across(.cols = 기준가,.fns = ~if_else(korea_holiday==1, NA, .x) )) %>%
    timetk::pad_by_time(.date_var = 기준일자,.by = "day", .fill_na_direction = "down") %>% 
    ungroup() %>% 
    select(-korea_holiday) ->results_기준가
  
  
  results_기준가 %>% 
    group_by(Portfolio,요일=wday(기준일자,label=TRUE)) %>% 
    mutate(lagged_기준가 = lag(기준가,n=1)) %>% 
    ungroup() %>% 
    mutate(주간수익률 = if_else(is.na(lagged_기준가),
                           기준가/1000-1,
                           기준가/lagged_기준가-1),
           주간로그수익률 = if_else(is.na(lagged_기준가),
                             log(기준가/1000),
                             log(기준가/lagged_기준가)),
    )-> results_주간수익률
  
  
  
  results_주간수익률 %>% 
    group_by(Portfolio) %>% 
    reframe(분석시작일 = nth(기준일자,n=2),
            분석종료일 = lubridate::ymd(input_date)) %>% 
    dplyr::rowwise() %>% 
    mutate(
      `1D` = return_ref_date_v2(분석종료일,1,"D"),
      `1W` = return_ref_date_v2(분석종료일,1,"W"),
      `1M` = return_ref_date_v2(분석종료일,1,"M"),
      `3M` = return_ref_date_v2(분석종료일,3,"M"),
      `6M` = return_ref_date_v2(분석종료일,6,"M"),
      `9M` = return_ref_date_v2(분석종료일,9,"M"),
      `1Y` = return_ref_date_v2(분석종료일,1,"Y"),
      `2Y` = return_ref_date_v2(분석종료일,2,"Y"),
      `30M`= return_ref_date_v2(분석종료일,30,"M"),
      `3Y` = return_ref_date_v2(분석종료일,3,"Y"),
      `4Y` = return_ref_date_v2(분석종료일,4,"Y"),
      `5Y` = return_ref_date_v2(분석종료일,5,"Y"),
      `YTD`= return_ref_date_v2(분석종료일,0,"YTD"),
      `MTD`= return_ref_date_v2(분석종료일,0,"MTD"),
      `QTD`= return_ref_date_v2(분석종료일,0,"QTD"),
      `HTD`= return_ref_date_v2(분석종료일,0,"HTD"),
      start = 분석시작일-days(1),
      end  = 분석종료일
    ) %>% 
    # mutate(
    #   `YTD`= return_ref_date(분석종료일,"YTD"),
    #   `1M` = return_ref_date(분석종료일,"1M"),
    #   `3M` = return_ref_date(분석종료일,"3M"),
    #   `6M` = return_ref_date(분석종료일,"6M"),
    #   `1Y` = return_ref_date(분석종료일,"1Y"),
    #   start = 분석시작일-days(1),
    #   end  = 분석종료일
    # ) %>% 
    ungroup() %>% 
    mutate(across(.cols = -c(Portfolio,분석시작일,분석종료일,start),
                  .fns = ~if_else(.x < start, NA,.x)))-> ref_date_inform
  
  ref_date_inform %>% 
    pivot_longer(-c(Portfolio,분석시작일,분석종료일),values_to = "ref_date")  %>% 
    mutate(total_days = difftime(분석종료일,ref_date,units = "days") %>% as.numeric()) %>% 
    pivot_longer(cols = c(total_days),names_to = "구분",values_to = "value") ->for_geometric_return
  
  #[1] "Portfolio"  "분석시작일" "분석종료일" "name"       "ref_date"   "구분"       "value"  
  
  for_geometric_return %>% 
    pivot_wider(id_cols = c(Portfolio,분석시작일,분석종료일,구분),
                names_from = name,
                values_from = c(value)) %>% 
    select(-c(end,구분)) %>% 
    rename(누적=start) -> ref_date_total_days
  # print("ref_date_total_days완료")
  
  ref_date_inform %>% 
    pivot_longer(-c(Portfolio,분석시작일,분석종료일),values_to = "ref_date")  %>% 
    left_join(results_기준가, by = c("Portfolio", "ref_date" = "기준일자")) %>% 
    pivot_longer(cols = c(기준가),names_to = "구분",values_to = "value") %>% 
    pivot_wider(id_cols = c(Portfolio,분석시작일,분석종료일,구분),
                names_from = name,
                values_from = c(value)) %>% 
    mutate(누적 = 1000) %>% 
    mutate(across(.cols = where(is.numeric),.fns = ~(end/.x -1) )) %>% 
    #mutate(across(.cols = where(is.numeric),.fns = ~percent(end/.x -1,accuracy = 0.01) )) %>% 
    select(-c(start,end,구분)) -> ref_date_수익률
  
  # print("ref_date_수익률완료")
  
  if(rf_dataset_id != "직접입력(%)"){
    ref_date_inform %>% 
      pivot_longer(-c(Portfolio,분석시작일,분석종료일),values_to = "ref_date")  %>% 
      left_join(ECOS_historical_price %>% 
                  filter(dataset_id == rf_dataset_id) %>% 
                  rename(기준가= 기준가_custom)
                , by = c("ref_date" = "기준일자")) %>% 
      pivot_longer(cols = c(기준가),names_to = "구분",values_to = "value") %>% 
      pivot_wider(id_cols = c(Portfolio,분석시작일,분석종료일,구분),
                  names_from = name,
                  values_from = c(value)) %>% 
      mutate(누적 = start) %>% 
      mutate(across(.cols = where(is.numeric),.fns = ~(end/.x -1) )) %>% 
      select(-c(start,end,구분)) -> ref_date_rf수익률
  }else{
    ref_date_inform %>% 
      pivot_longer(-c(Portfolio,분석시작일,분석종료일),values_to = "ref_date")  %>% 
      #  filter(!is.na(ref_date)) %>%
      pivot_wider(id_cols = c(Portfolio,분석시작일,분석종료일),
                  names_from = name,
                  values_from = c(ref_date)) %>%
      mutate(누적 = start) %>% 
      mutate(across(.cols = -c(Portfolio,분석시작일,분석종료일),.fns = ~if_else(is.na(.x),NA,(rf_custom_input/100)) )) %>%
      select(-c(start,end)) -> ref_date_rf수익률
  }
  
  # print("ref_date_rf수익률완료")
  ref_date_inform %>% 
    select(-c(end)) %>% 
    pivot_longer(-c(Portfolio,분석시작일,분석종료일),values_to = "ref_date") %>% 
    rowwise() %>% 
    mutate(first_wday = if_else(is.na(ref_date),NA,
                                return_first_weekly_date(start_date = ref_date,end_date =분석종료일 ))) -> ref_date_first_wday_inform
  
  
  
  
  ref_date_first_wday_inform %>%   
    mutate(주간수익률및변동성 =if_else(is.na(ref_date),NA,
                              pmap(list(Portfolio,first_wday,분석종료일),
                                   .f = ~weekly_calculation_Portfolio(
                                     weekly_return_df =results_주간수익률,
                                     Port_name = ..1,
                                     start_date = ..2,
                                     end_date = ..3,
                                     annualized_factor = 52)))  ) %>% 
    unnest_wider(col = 주간수익률및변동성) %>% 
    left_join(annualized_geometric_return(ref_date_수익률,for_geometric_return) %>% 
                select(Portfolio,분석시작일,분석종료일,name,연율화수익률_v3) ,
              by = join_by(Portfolio, 분석시작일, 분석종료일, name)
    ) %>% 
    select(Portfolio,분석시작일,분석종료일,name,ref_date,
           str_glue("연율화수익률_{annualized_return_method}"),
           str_glue("연율화변동성_{annualized_risk_method}")) %>% 
    set_names(c("Portfolio","분석시작일","분석종료일",
                "name","ref_date","연율화수익률","연율화변동성")) -> ref_date_weekly_calc
  
  # print("ref_date_weekly_calc완료")
  # annualized_geometric_return(ref_date_rf수익률,for_geometric_return) %>% 
  #   select(Portfolio,분석시작일,분석종료일,name,연율화수익률_v3)
  # 
  
  if(rf_dataset_id != "직접입력(%)"){
    ref_date_first_wday_inform %>% 
      select(-Portfolio) %>% 
      distinct() %>% 
      mutate(주간수익률및변동성 =if_else(is.na(ref_date),NA,
                                pmap(list(first_wday,분석종료일),
                                     .f = ~weekly_calculation_Risk_free(start_date = ..1,
                                                                        end_date = ..2,
                                                                        annualized_factor = annualized_factor))) ) %>%  
      unnest(col = 주간수익률및변동성) %>%
      filter(dataset_id == rf_dataset_id) %>% # 사용자 입력1. RF종류----
    
    left_join(annualized_geometric_return(ref_date_rf수익률,for_geometric_return) %>% 
                select(Portfolio,분석시작일,분석종료일,name,연율화수익률_v3) ,
              by = join_by(분석시작일, 분석종료일, name)
    ) %>% 
      
      select(분석시작일,분석종료일,name,ref_date,
             str_glue("연율화수익률_{annualized_return_method}"),
             str_glue("연율화변동성_{annualized_risk_method}")) %>% 
      distinct() %>%
      set_names(c("분석시작일","분석종료일",
                  "name","ref_date","연율화수익률","연율화변동성")) %>% 
      pivot_wider(id_cols = c(분석시작일,분석종료일),
                  names_from = name,
                  values_from = c(연율화수익률)) ->ref_date_annualize_return_RF
  }else{
    ref_date_rf수익률 %>% 
      rename(start= 누적)->ref_date_annualize_return_RF
  }
  print("ref_date_annualize_return_RF완료")
  
  ref_date_annualize_return_RF<- ref_date_inform %>% select(Portfolio,contains("분석")) %>% 
    left_join(ref_date_annualize_return_RF)
  
  
  ref_date_weekly_calc %>% 
    pivot_wider(id_cols = c(Portfolio,분석시작일,분석종료일),
                names_from = name,
                values_from = c(연율화수익률)) ->ref_date_annualize_return
  ref_date_weekly_calc %>% 
    pivot_wider(id_cols = c(Portfolio,분석시작일,분석종료일),
                names_from = name,
                values_from = c(연율화변동성)) ->ref_date_annualize_risk
  
  ref_date_annualize_return %>% rename(누적=start) %>% 
    pivot_longer(-c(Portfolio,분석시작일,분석종료일),values_to = "annualized_return") %>% 
    left_join(
      ref_date_annualize_risk %>% rename(누적=start) %>% 
        pivot_longer(-c(Portfolio,분석시작일,분석종료일),values_to = "annualized_risk") ,
      by = join_by(Portfolio, 분석시작일, 분석종료일, name)
    ) %>% 
    left_join(
      ref_date_annualize_return_RF %>% rename(누적=start) %>% 
        pivot_longer(-c(Portfolio ,분석시작일,분석종료일),values_to = "annualized_return_RF") ,#%>% 
      #mutate(annualized_return_RF = if_else(rf_dataset_id =="입력:",num,annualized_return_RF)),
      by = join_by(Portfolio,분석시작일, 분석종료일, name)
      
    ) %>% 
    mutate(adjusted_sharpe_ratio = if_else(annualized_return - annualized_return_RF>0,
                                           (annualized_return - annualized_return_RF)/annualized_risk,
                                           (annualized_return - annualized_return_RF)*annualized_risk
    )) ->for_bubble_charts
  
  for_bubble_charts %>% 
    pivot_wider(id_cols = c(Portfolio,분석시작일,분석종료일),
                names_from = name,
                values_from = c(adjusted_sharpe_ratio)) ->ref_date_sharpe_ratio
  
  ref_date_inform %>% 
    pivot_longer(-c(Portfolio,분석시작일,분석종료일),values_to = "ref_date") %>% 
    filter(name!="end") %>% 
    mutate(MDD = pmap_dbl(list(Portfolio,ref_date,분석종료일),
                          .f = ~ MDD_Calculation(perform_historical,
                                                 Portfolio_name = ..1,
                                                 start_date = ..2,end_date = ..3) )) %>%  
    pivot_wider(id_cols = c(Portfolio,분석시작일,분석종료일),
                names_from = name,
                values_from = c(MDD)) ->ref_date_MDD
  
  
  
  res_list<- list(
    "결과1.Reference Date"    =ref_date_inform %>% rename(누적=start) %>% select(-end) ,
    "결과2.Total Days"        =ref_date_total_days,
    "결과3.수익률"            =ref_date_수익률 ,# ref_date_수익률_RF 계산해서, 연율화 수익률 기하평균버전계산 하기
    "결과4.연율화수익률"      =ref_date_annualize_return %>% rename(누적=start),
    "결과5.연율화위험"        =ref_date_annualize_risk %>% rename(누적=start),
    "결과6.무위험연율화수익률"=ref_date_annualize_return_RF %>% rename(누적=start),
    "결과7.수정샤프비율"      =ref_date_sharpe_ratio,
    "결과8.MDD"               =ref_date_MDD %>% rename(누적=start) ,
    "그래프1.Drawdown & Cummulative Return" = perform_historical,
    "그래프2.Bubble" = for_bubble_charts
    
  ) 
  # 결과1 --> Reference Date
  # 결과2 --> Total Days
  # 결과3 --> 수익률
  # 결과4 --> 연율화수익률
  # 결과5 --> 연율화위험
  # 결과6 --> 무위험연율화수익률
  # 결과7 --> 수정샤프비율
  
  return(res_list)
} 


# Portfolio / 리밸런싱구간 / 구간 시작일 / 구간종료일 / metric /RF종류 /연율화방식 ----
# 
# function(start_date = min(results_기준가$리밸런싱날짜),분석종료일 = input_date , metric=NULL){
#   
# }


MDD_Calculation <- function(perform_historical,Portfolio_name,start_date,end_date){
  
  if(is.na(start_date)){
    
    return(NA)
    
  }else{
    
    res <- perform_historical %>% 
      filter(Portfolio == Portfolio_name) %>% 
      filter(기준일자 <= end_date) %>% 
      filter(기준일자 > start_date) %>% 
      group_by(Portfolio) %>% 
      mutate(누적수익률 = cumprod(`Return(T)`+1)-1,
             draw_down =( (1+누적수익률)/((1+cummax(누적수익률)))-1)) %>% 
      reframe(MDD = min(draw_down)) %>% pull(MDD)
    
    
    return(res) 
  }
}
