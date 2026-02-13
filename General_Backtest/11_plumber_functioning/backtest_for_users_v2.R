library(tidyverse)
library(shiny)
library(plotly)
library(scales)
library(ecos)
library(rlang) # sym() 함수를 사용하기 위해 필요
library(DBI)
library(RMariaDB) 
library(lubridate)
library(blob)
ecos.setKey("FWC2IZWA5YD459SQ7RJM")

con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')
con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
con_solution <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'solution', host = '192.168.195.55')

tbl(con_SCIP,"back_dataset") %>%
  filter(!is.na(ISIN) | str_detect(name,"Index") | str_detect(name,"KIS")) %>% 
  collect()%>% 
  mutate(id= as.character(id))  ->Data_List


tbl(con_SCIP,"back_datapoint") %>%
  filter(dataset_id %in% local(Data_List$id)) %>% 
  select(dataset_id,dataseries_id) %>% 
  filter(dataseries_id %in% c(6,9,15,33)) %>% distinct() %>% 
  left_join(tbl(con_SCIP,"back_dataseries") %>% 
              select(-formula,dataseries_name = name),by = join_by(dataseries_id == id)) %>% 
  left_join(tbl(con_SCIP,"back_source") %>% 
              select(id,source=name),by = join_by(source_id == id)) %>% 
  select(-source_id) %>% 
  collect() %>% 
  mutate(across(.cols = where(is.numeric), .f = ~as.character(.x))) %>% 
  left_join(Data_List ,by = join_by( dataset_id == id)) %>% 
  select(-c(visibleInDatamart) ) %>% 
  mutate(region = case_when(str_sub(ISIN,1,2)=="KR"~ "KR",
                            source == "KIS Pricing"~ "KR",
                            str_detect(name,"KIS")|str_detect(name,"KOSPI")|str_detect(name,"Korea") ~ "KR",
                            TRUE ~ "ex_KR"
  ))-> data_information_SCIP


tbl(con_dt,"DWPI10011") %>%
  filter(DEPT_CD %in% c('166','061')) %>% 
  select(dataset_id=FUND_CD,name=FUND_WHL_NM) %>% collect() %>% 
  mutate(dataseries_id = "MOD_STPR",
         dataseries_name = "수정기준가",
         source = "BOS",
         region = "KR") ->data_information_BOS

data_information<- bind_rows(data_information_SCIP,data_information_BOS) %>% 
  mutate(colname_backtest = if_else(is.na(ISIN), name,symbol)) %>% 
  mutate(colname_backtest = if_else(grepl("^[0-9]+$", colname_backtest), name, colname_backtest)) 


pulled_data_universe_SCIP <- data_information %>% select(dataset_id,dataseries_id) %>% 
  inner_join(tbl(con_SCIP,"back_datapoint") %>%
               select(timestamp_observation,data,dataset_id,dataseries_id) %>% 
               mutate(dataset_id =as.character(dataset_id),
                      dataseries_id =as.character(dataseries_id)),
             copy = TRUE,
             by = join_by(dataset_id,dataseries_id))


BOS_historical_price <-data_information %>% select(dataset_id,dataseries_id) %>% 
  inner_join(tbl(con_dt,"DWPM10510") %>% 
               select(STD_DT,dataset_id=FUND_CD,MOD_STPR),
             copy = TRUE
  ) %>% collect()

BOS_historical_price<- BOS_historical_price %>% 
  bind_rows(
    BOS_historical_price %>% 
      group_by(dataset_id,dataseries_id) %>% 
      reframe(STD_DT = str_remove_all(min(ymd(STD_DT))-days(1),"-"),
              MOD_STPR = 1000)
  ) %>% 
  arrange(dataset_id,STD_DT)




bind_rows(
  pulled_data_universe_SCIP %>% 
    group_by(dataset_id,dataseries_id) %>% 
    reframe(분석시작가능일 = ymd(nth(sort(timestamp_observation), 2, default = NA))),
    #reframe(분석시작가능일=ymd(min(timestamp_observation)))  -- 가격데이터밖에 없어서 첫날 수익률 계산 못함.,
  BOS_historical_price %>% 
    group_by(dataset_id,dataseries_id) %>% 
    reframe(분석시작가능일 = ymd(nth(sort(STD_DT), 2, default = NA)))
    # reframe(분석시작가능일=ymd(min(STD_DT))) 
  
)-> 분석시작가능일_inform

data_information <- data_information %>% 
  left_join(분석시작가능일_inform) %>% 
  select(symbol,ISIN,name,분석시작가능일,everything())


tbl(con_dt,"DWCI10220") %>% 
  select(기준일자 = std_dt,요일코드 = day_ds_cd,hldy_yn,hldy_nm,월말일여부=mm_lsdd_yn,전영업일=pdd_sals_dt,다음영업일 =nxt_sals_dt) %>% 
  filter( 기준일자>="20000101") %>% 
  collect() %>% 
  mutate(기준일자 = ymd(기준일자))->holiday_calendar

holiday_calendar %>% 
  filter(hldy_yn=="Y" &!(요일코드 %in% c("1","7"))) %>% 
  pull(기준일자)->KOREA_holidays

# ECOS 데이터의 날짜가 더 길다.
USDKRW <- ecos::statSearch(stat_code = "731Y003","0000003",cycle ="D",
                           start_time = "19000101",
                           end_time =today() %>% str_remove_all("-") ) %>% tibble() %>%
  select(기준일자=time,`USD/KRW`  = data_value) %>%
  mutate(기준일자= ymd(기준일자)) %>% 
  timetk::pad_by_time(.date_var = 기준일자,.by = "day",.fill_na_direction = "down")




# dataset_id_vector=MP_VP_BM_prep$dataset_id_vector[[1]]
# dataseries_id_vector=MP_VP_BM_prep$dataseries_id_vector[[1]]
# region_vector=MP_VP_BM_prep$region_vector[[1]]
# weight_vector=MP_VP_BM_prep$weight_vector[[1]]
# hedge_ratio_vector=MP_VP_BM_prep$hedge_ratio_vector[[1]]
# cost_adjust_vector=MP_VP_BM_prep$cost_adjust_vector[[1]]


calculate_BM_results_bulk_for_users<- function(dataset_id_vector, dataseries_id_vector, region_vector,
                                               weight_vector, hedge_ratio_vector, cost_adjust_vector,
                                               start_date, end_date ) {
  
  cost_adjust_vector_for_calc <-  -cost_adjust_vector /10000 /365 # `비용조정(연bp)`
  # 1. 제약 조건 체크
  if (!(length(dataset_id_vector) == length(dataseries_id_vector) &&
        length(region_vector) == length(weight_vector) &&
        length(hedge_ratio_vector) == length(cost_adjust_vector) && 
        length(dataset_id_vector) == length(cost_adjust_vector) )) {
    stop("Error: 모든 입력 벡터의 길이가 동일해야 합니다.")
  }
  
  Data_variable_list <-tibble(dataset_id_vector,dataseries_id_vector,region_vector,
                              weight_vector,hedge_ratio_vector,cost_adjust_vector)
  
  
  for_pulling_universe_data <- Data_variable_list %>% 
    left_join(data_information %>% select(dataset_id, name=colname_backtest,ISIN), by = join_by(dataset_id_vector==dataset_id)) %>% 
    distinct() %>% 
    mutate(symbol = str_glue("{name}{if_else(region_vector != 'KR', '(t-1)', '')}{if_else( !(hedge_ratio_vector %in% c(0,1)) & region_vector != 'KR',
                         paste0( '*(USDKRW)*(',(1-hedge_ratio_vector)*100, '%)' ),
                         if_else((hedge_ratio_vector == 0 & region_vector != 'KR') , '*(USDKRW)' , '')) }")) 
  
  # pulled_data 생성
  pulled_data_SCIP <- for_pulling_universe_data %>%
    inner_join(pulled_data_universe_SCIP,by = join_by(dataset_id_vector==dataset_id,
                                                      dataseries_id_vector == dataseries_id))
  
  pulled_data_BOS <- for_pulling_universe_data %>%
    inner_join(BOS_historical_price,by = join_by(dataset_id_vector==dataset_id,
                                                 dataseries_id_vector == dataseries_id))
  
  
  # Source_factset 생성
  Source_factset <- pulled_data_SCIP %>%
    filter(dataseries_id_vector %in% c(6,15)) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% 
    arrange(기준일자) %>% 
    select(-c(timestamp_observation)) %>% 
    mutate(data = map(data, ~jsonlite::parse_json(rawToChar(unlist(.x))))) %>% 
    mutate(USD = map_dbl(data, ~unlist(.x)[1]),
           KRW = map_dbl(data, ~unlist(.x)[2])) %>% 
    mutate(pulling_value = if_else(region_vector == "KR", KRW, USD)) %>%
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = pulling_value) %>% 
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_Bloomberg 생성
  Source_Bloomberg <- pulled_data_SCIP %>%
    filter(dataseries_id_vector == 9) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% 
    arrange(기준일자) %>% 
    mutate(data = map_dbl(data, ~as.numeric(rawToChar(unlist(.x))))) %>% 
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = data) %>%  
    mutate(across(.cols =contains("(t-1)") , .fns = ~lag(.x ,n=1) ))
  
  # Source_KIS 생성
  Source_KIS <- pulled_data_SCIP %>%
    filter(dataseries_id_vector == 33) %>%
    mutate(기준일자 = ymd(timestamp_observation)) %>% 
    arrange(기준일자) %>% 
    select(-c(timestamp_observation)) %>%
    mutate(data = map(data, ~jsonlite::parse_json(rawToChar(unlist(.x))))) %>% 
    mutate(data = map_dbl(data, ~as.numeric(.x[[1]]))) %>% 
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = data)
  
  # Source_BOS 생성
  
  Source_BOS <- pulled_data_BOS %>% 
    mutate(기준일자 = ymd(STD_DT)) %>% 
    pivot_wider(id_cols = 기준일자,
                names_from = symbol,
                values_from = MOD_STPR)
  # Source_combined 생성
  Source_factset %>% 
    full_join(Source_Bloomberg , by = join_by(기준일자)) %>% 
    full_join(Source_KIS , by = join_by(기준일자)) %>% 
    full_join(Source_BOS , by = join_by(기준일자)) %>% 
    full_join(USDKRW %>% 
                mutate(`return_USD/KRW`=`USD/KRW`/lag(`USD/KRW`)-1), by = join_by(기준일자)) %>% 
    arrange(기준일자)->Source_combined
  
  # 최종 결과 계산 및 가중 합계 계산
  results <-
    Source_combined %>%
    select(기준일자, for_pulling_universe_data$symbol,`USD/KRW`,`return_USD/KRW`) %>% 
    mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays,1,0)) %>% 
    mutate(across(.cols = (which(if_else(for_pulling_universe_data$region_vector=="KR",1,0)==0)+1),
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
                                      FX_adjust<- (1-for_pulling_universe_data$hedge_ratio_vector)*(1-(for_pulling_universe_data$region_vector=="KR"))
                                      
                                      for_pulling_universe_data$hedge_ratio_vector
                                      return_vector <- ..1/..2 - 1  # 요소별 이름만 필요한것이기 때문에 .x이용
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
                                                  rep(0,length(for_pulling_universe_data$weight_vector)) %>% 
                                                    set_names(for_pulling_universe_data$symbol))), .after = 기준일자 ) %>% 
    # 2. Driftweight 계산 (갱신된 가중치 벡터 생성)
    mutate(`Weight_fixed(T)` = map(
      cummulative_return_list, 
      ~ {
        (1 + .x*0) * for_pulling_universe_data$weight_vector # 요소별 이름만 필요한것이기 때문에 .x이용
      }
    ), .after = 기준일자) %>% 
    mutate(`Weight_drift(T-1)` = map(
      lagged_cummulative_return_list, 
      ~ {
        비중 <- (1 + .x) * for_pulling_universe_data$weight_vector
        비중 / sum(비중) # 합이 1이 되도록 정규화
      }
    ), .after = 기준일자) %>% 
    mutate(`Weight_drift(T)` = map(
      cummulative_return_list, 
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
    ), .after = 기준일자)  
  
  return(list(results,for_pulling_universe_data))
}


backtesting_for_users<- function(backtest_prep_table){
  print("### backtesting_for_users 함수 시작 ###")
  print("입력 데이터:")
  print(head(backtest_prep_table)) 
  
  colnames(backtest_prep_table) <- c("리밸런싱날짜", "Portfolio","dataset_id","dataseries_id","region", 
                                     "weight",  "hedge_ratio", "cost_adjust" )
  backtest_prep_table<- backtest_prep_table %>% as_tibble()
  
  
  backtest_prep_table %>% 
    select(dataseries_id,dataset_id) %>% distinct() %>% 
    mutate(across(where(is.numeric),.fns = ~as.integer(.x)))->universe_list
  
  
  backtest_prep_table %>% 
    group_by(리밸런싱날짜, Portfolio) %>% 
    nest() %>% 
    mutate(dataset_id_vector    = map(data, ~ .x$dataset_id),
           dataseries_id_vector    = map(data, ~ .x$dataseries_id ),
           region_vector     =  map(data, ~ .x$region),
           weight_vector     =  map(data, ~ .x$weight),
           hedge_ratio_vector = map(data, ~ .x$hedge_ratio),
           cost_adjust_vector = map(data, ~ .x$cost_adjust)
    ) %>%
    ungroup() %>%
    group_by(Portfolio) %>%
    mutate(리밸런싱마감일= lead(리밸런싱날짜,n=1)) %>%
    mutate(리밸런싱마감일= if_else(is.na(리밸런싱마감일),ymd(today()-days(1)), 리밸런싱마감일 )) %>%
    ungroup() %>%
    arrange(Portfolio)->MP_VP_BM_prep
  
  
  tictoc::tic()
  MP_VP_BM_prep  %>% 
    arrange(Portfolio,리밸런싱날짜) %>% 
    mutate(backtest= pmap(list(dataset_id_vector,dataseries_id_vector,region_vector,
                               weight_vector,hedge_ratio_vector,cost_adjust_vector,
                               리밸런싱날짜,리밸런싱마감일),
                          .f = ~calculate_BM_results_bulk_for_users(dataset_id_vector    = ..1,
                                                                    dataseries_id_vector = ..2,
                                                                    region_vector        = ..3,
                                                                    weight_vector        = ..4,
                                                                    hedge_ratio_vector   = ..5,
                                                                    cost_adjust_vector   = ..6,
                                                                    start_date        = ..7,
                                                                    end_date          = ..8)))  ->MP_VP_BM_results
  tictoc::toc()
  
  
  
  MP_VP_BM_results %>% select(리밸런싱날짜,Portfolio,backtest) %>% 
    mutate(backtest_descriptrion = map(backtest,.f= ~.x[[2]]),.keep = "unused") %>% 
    unnest(backtest_descriptrion) ->MP_VP_BM_results_descriptrion
  
  MP_VP_BM_results %>% 
    select(리밸런싱날짜,Portfolio,backtest) %>% 
    mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
    group_by(Portfolio) %>% 
    unnest(backtest_res) %>% 
    # 그룹화: 기준일자별로 리밸런싱날짜가 빠른/늦은 경우 처리
    group_by(Portfolio, 기준일자)  %>% 
    reframe(
      리밸런싱날짜 = 리밸런싱날짜[1],
      weighted_sum_drift = first(weighted_sum_drift), # 리밸런싱날짜 빠른 값
      weighted_sum_fixed = first(weighted_sum_fixed), # 리밸런싱날짜 빠른 값
      `Weight_drift(T)`   = list(last(`Weight_drift(T)`)),               # 리밸런싱날짜 늦은 값
      #`Weight_drift(T-1)` = list(last(`Weight_drift(T-1)`)) ,            # 리밸런싱날짜 늦은 값
      `Weight_fixed(T)`   = list(last(`Weight_fixed(T)`)) ) ->MP_VP_BM_results_core 
   # unnest_wider(col = starts_with("Weight_"),names_sep = "-") -> MP_VP_BM_results_core
  
  
  MP_VP_BM_results %>% 
    select(리밸런싱날짜,Portfolio,backtest) %>% 
    mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
    unnest(backtest_res) %>% 
    select(-contains("weighted_sum"),-contains("Weight_")) ->MP_VP_BM_results_raw 
    #unnest_wider(col = ends_with("_list"),names_sep = "-") ->MP_VP_BM_results_raw
  
  res <- list("백테스트내역"=MP_VP_BM_results_descriptrion,
              "백테스트계산_Perform&Position"=MP_VP_BM_results_core,
              "백테스트계산_raw"=MP_VP_BM_results_raw)
  return(res)  
}

# 
# # # 
# # # 
# # tribble(~리밸런싱날짜, ~Portfolio,~dataset_id, ~dataseries_id, ~region, ~weight , ~hedge_ratio,~cost_adjust,
# #         
# #         "2023-12-08","Test1", 253, 9, "KR", 0.7, 0, 0,
# #         "2023-12-08","Test1", 187, 33, "KR", 0.3, 0,0,
# #         "2024-10-24","Test1 ", 253, 9, "KR", 0.3, 0,0,
# #         "2024-10-24","Test1 ", 187, 33, "KR", 0.7, 0, 0,
# #         #--
# #         "2023-12-08","Test2 ", 253, 9, "KR", 0.3, 0,0,
# #         "2023-12-08","Test2 ", 187, 33, "KR", 0.7, 0, 0,
# #         "2024-10-24","Test2", 253, 9, "KR", 0.7, 0, 0,
# #         "2024-10-24","Test2", 187, 33, "KR", 0.3,  0,0
# # ) %>%
# #   mutate(리밸런싱날짜 = ymd(리밸런싱날짜)) %>%
# #   mutate(dataset_id = as.integer(dataset_id),
# #          dataseries_id = as.integer(dataseries_id)
# #          )->sb_back
# 
# # res<- backtesting_for_users(sb_back)
# # res$`백테스트계산_Perform&Position`
# # res$백테스트계산_raw
# # # 
# # # long form, wide form 선택해서 다운 가능하게 .
# #   
# # list("백테스트내역"=MP_VP_BM_results_descriptrion,
# #      "백테스트계산_Perform&Position"=MP_VP_BM_results_core,
# #      "백테스트계산_raw"=MP_VP_BM_results_raw) %>% writexl::write_xlsx("11_plumber_functioning/dsf.xlsx")
# # # 
# # 
# #   

cum_return_and_Drawdown_plot<- function(Perform_position_data,input_date){
  Perform_position_data %>% select(Portfolio,기준일자,contains("weighted_sum")) %>% 
    filter(기준일자<=input_date) %>% 
    group_by(Portfolio) %>% 
    mutate(누적수익률_drift = cumprod(weighted_sum_drift+1)-1,
           누적수익률_fixed = cumprod(weighted_sum_fixed+1)-1,
           draw_down_drift =( (1+누적수익률_drift)/((1+cummax(누적수익률_drift)))-1),
           draw_down_fixed =( (1+누적수익률_fixed)/((1+cummax(누적수익률_fixed)))-1),
           MDD_drift = min(draw_down_drift),
           MDD_fixed = min(draw_down_fixed)
    ) %>% 
    ungroup() -> perform_historical
  
  
  df_wide <- perform_historical %>%
    select(기준일자, Portfolio, 누적수익률_drift, draw_down_drift) %>%
    # names_from=과 values_from= 에 자신이 원하는 이름(누적수익률 or drawdown 등) 매핑
    pivot_wider(
      names_from = Portfolio,
      values_from = c(누적수익률_drift, draw_down_drift),
      # 필요시, 중복될 수 있으므로 구분자 지정
      names_sep = "|"
    )
  
  # 예: df_wide 컬럼
  # 기준일자, 누적수익률_drift|A, draw_down_drift|A, 누적수익률_drift|B, draw_down_drift|B, ...
  
  # ------------------------------------------------------------------------------#
  # 2) echarts4r로 라인 그리기
  #    - 같은 포트폴리오는 같은 color
  #    - y축 index(0 vs 1)에 따라 라인타입(solid vs dashed) 다름
  # ------------------------------------------------------------------------------#
  
  # 2-1) 포트폴리오 목록과 색상 팔레트 지정
  portfolios <- unique(perform_historical$Portfolio)  # 예: 실제 데이터에 맞게 수정
  n_port <- length(portfolios)
  
  # Dark2 팔레트를 필요한 개수(n_port)만큼 확장
  palette <- colorRampPalette(c("red","blue","green"))(n_port)
  
  # 2-2) 차트 시작
  p <- df_wide %>%
    e_charts(x = 기준일자) 
  
  
  Perform_position_data %>% 
    group_by(Portfolio) %>% 
    distinct(리밸런싱날짜) %>% 
    filter(row_number()!=1) %>% ungroup()
  # 2-3) 각 포트폴리오마다 "누적수익률_drift" / "draw_down_drift" 라인 차례대로 추가
  for(i in seq_along(portfolios)){
    p <- p %>%
      # (1) 누적수익률 라인: y_index=0, solid
      e_line_(
        serie     = paste0("누적수익률_drift|", portfolios[i]),
        name      = paste0(portfolios[i], " 누적수익률"),
        y_index   = 0,showSymbol = FALSE,
        lineStyle = list(type = "solid",width = 2, opacity = 1),
        color     = palette[i]
      ) %>%
      # (2) drawdown 라인: y_index=1, dashed
      e_area_(
        serie     = paste0("draw_down_drift|", portfolios[i]),
        name      = paste0(portfolios[i], " Drawdown"),
        y_index   = 1,showSymbol = FALSE,
        color     = palette[i],
        opacity = 0.1
        
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
      min = min(perform_historical$기준일자),
      max = max(perform_historical$기준일자)
    ) %>%
    # 툴팁 설정
    e_tooltip(
      trigger     = "axis",
      axisPointer = list(type = "cross"),
      formatter   = e_tooltip_pointer_formatter(style = c("percent"), digits = 2)
    ) %>%
    e_title("누적수익률 & Drawdown 추이", "") %>% 
    e_legend(top = "bottom") %>%
    e_toolbox_feature(feature = "saveAsImage")
  
  # 2-5) 완성된 차트 출력
  return(p)
  
}