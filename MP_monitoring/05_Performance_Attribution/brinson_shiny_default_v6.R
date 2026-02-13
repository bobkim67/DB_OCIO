library(tidyverse)


# Port A, Port B입력받기 
#>1. 두 포트의 비교가능한 첫 날짜 이후로 필터링.
#>2. 데이터 객체, 포트정보 1 , 포트정보 2  입력받아서 필터링 하여 반환하는 함수 짜기.


con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')

# 
# 
# FX_historical <- tbl(con_dt,"DWCI10260") %>% 
#   select(STD_DT,CURR_DS_CD,TR_STD_RT) %>% 
#   filter( STD_DT>="20221001",CURR_DS_CD %in% c('AUD','USD')) %>%
#   rename(기준일자=STD_DT) %>% 
#   #mutate(기준일자 = ymd(기준일자)) %>% 
#   pivot_wider(id_cols = 기준일자,names_from = CURR_DS_CD,values_from = TR_STD_RT) %>% 
#   collect()
# 


# FX_historical <- tbl(con_dt,"DWCI10260") %>% 
#   select(STD_DT,CURR_DS_CD,TR_STD_RT) %>% 
#   filter( STD_DT>="20221001",CURR_DS_CD %in% c('AUD','USD')) %>%
#   rename(기준일자=STD_DT) %>% 
#   #mutate(기준일자 = ymd(기준일자)) %>% 
#   pivot_wider(id_cols = 기준일자,names_from = CURR_DS_CD,values_from = TR_STD_RT) %>% 
#   collect()
ecos.setKey("FWC2IZWA5YD459SQ7RJM")

# ECOS 데이터의 날짜가 더 길다.
USDKRW <- ecos::statSearch(stat_code = "731Y003","0000003",cycle ="D",
                           start_time = "19000101",
                           end_time =today() %>% str_remove_all("-") ) %>% tibble() %>%
  select(기준일자=time,`USD/KRW`  = data_value) %>%
  mutate(기준일자= ymd(기준일자)) %>% 
  timetk::pad_by_time(.date_var = 기준일자,.by = "day",.fill_na_direction = "down")


AUDKRW<- ecos::statSearch(stat_code = "731Y001","0000017",cycle ="D",
                          start_time = "19000101",
                          end_time =today() %>% str_remove_all("-") ) %>% tibble() %>% 
  select(기준일자=time,`AUD/KRW`  = data_value) %>%
  mutate(기준일자= ymd(기준일자)) %>% 
  timetk::pad_by_time(.date_var = 기준일자,.by = "day",.fill_na_direction = "down")

FX_historical<- USDKRW %>% 
  left_join(AUDKRW) %>% 
  setNames(c("기준일자","USD","AUD"))

ALL_historical_historical_prep<- MP_historical_prep





crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                           end_date = max(AP_performance_preprocessing$기준일자) ,
                                           by = "day") ,
         ISIN = colnames(ALL_historical_historical_prep)[-1]) %>% 
  # 고려사항 1. Data source : Factset 데이터 사용.
  left_join(ALL_historical_historical_prep %>% 
              pivot_longer(cols = -기준일자, names_to = "ISIN", values_to = "종가") %>% 
              filter(기준일자>="2022-10-04"),
            by = join_by(기준일자,ISIN)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = ISIN,values_from = 종가) %>% 
  #  고려사항 3. 한국휴일 반영
  mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays,1,0)) %>% 
  mutate(across(.cols = starts_with("US"), .fns = ~if_else(korea_holiday==1, NA, .x) )) %>% 
  select(-korea_holiday) %>% 
  pivot_longer(cols = -기준일자,names_to = "ISIN",values_to = "종가") %>% 
  #left_join(USDKRW,by =  join_by(기준일자)) 
  left_join(FX_historical %>% mutate(기준일자= ymd(기준일자)),by =  join_by(기준일자)) %>% 
  left_join(universe_criteria %>% select(종목코드, 자산군_대,자산군_소) %>% distinct(),by = join_by(ISIN ==종목코드)) %>% 
  mutate(Country = str_sub(ISIN,start=1,end=2)) %>% 
  group_by(ISIN) %>% 
  mutate(first_valid_date = min(기준일자[!is.na(종가)], na.rm = TRUE)) %>%
  filter(기준일자 >= first_valid_date) %>%
  select(-first_valid_date) %>% 
  mutate(종가 = zoo::na.locf(종가)) %>% 
  # 고려사항 4. 환율은 당일 값 사용.
  # mutate(`USD/KRW` = zoo::na.locf(`USD/KRW`)) %>% 
  mutate(across(.cols = c(AUD,USD),.fns = ~zoo::na.locf(.x) )) %>% 
  mutate(price_KRW = case_when(
    Country=="US" ~ 종가*USD,
    #Country=="AU" ~ 종가*AUD,
    Country=="AU" ~ 종가*USD,
    Country=="KR" ~ 종가)) %>% 
  mutate(last_price_KRW = lag(price_KRW,n=1),
         전일대비등락률 = price_KRW/last_price_KRW-1) %>%
  select(기준일자,ISIN, 전일대비등락률,자산군_대, 자산군_소) %>% 
  filter(기준일자>="2022-10-05") %>% ungroup() %>% 
  filter(!is.na(전일대비등락률))-> all_tickers_daily_return



# 콜금리가져오기 -----------------------------------------------------------------

library(ecos)
ecos.setKey("FWC2IZWA5YD459SQ7RJM")
call_rate <- ecos::statSearch(stat_code = "817Y002","010101000",cycle ="D",
                              start_time = "20220101",
                              end_time =today() %>% str_remove_all("-") ) %>% tibble() %>% 
  mutate(기준일자= ymd(time),
         `콜금리/365` = data_value/100/365) %>% 
  select(기준일자,`콜금리/365`) 


# 
# tbl(con_SCIP,"back_datapoint") %>% 
#   filter(dataset_id ==133,dataseries_id==7) %>%   
#   filter(timestamp_observation>="2022-10-03") %>% 
#   collect()->call_rate
# 
# 
# call_rate<- call_rate %>% 
#   mutate(data = map_dbl(.x= data, .f = ~jsonlite::parse_json((rawToChar(unlist(.x))))  )  ) %>% 
#   mutate(timestamp_observation=ymd(timestamp_observation),
#          data = data/100/365) %>% 
#   select(기준일자=timestamp_observation, `콜금리/365`=data) 
# 전처리 ---------------------------------------------------------------------

position_AP <- 
  calculate_portfolio_weights(
    data = AP_asset_adjust,
    asset_group = "자산군_대",
    division = "AP"
  )
position_VP <-
  calculate_portfolio_weights(
    data = VP_asset_adjust,
    asset_group = "자산군_대",
    division = "VP"
  )









Actual_return <- bind_rows(AP_performance_preprocessing %>% 
                             #filter((펀드설명=="MS GROWTH") |(펀드설명=="MS STABLE" )) %>% 
                             select(기준일자,수정기준가,펀드설명) %>% 
                             filter(!is.na(펀드설명)) %>% 
                             arrange(기준일자) %>% 
                             mutate(name = "AP"),
                           VP_performance_preprocessing %>% 
                             #filter((펀드설명=="MS GROWTH") |(펀드설명=="MS STABLE" )) %>% 
                             select(기준일자,수정기준가,펀드설명) %>% 
                             filter(!is.na(펀드설명)) %>% 
                             arrange(기준일자) %>% 
                             mutate(name = "VP"),
                           MP_performance_preprocessing_final %>% 
                             select(기준일자,수정기준가,펀드설명) %>% 
                             filter(!is.na(펀드설명)) %>% 
                             arrange(기준일자) %>% 
                             mutate(name = "MP"),
                           BM_performance_preprocessing_final %>% 
                             select(기준일자,수정기준가,펀드설명) %>% 
                             filter(!is.na(펀드설명)) %>% 
                             arrange(기준일자) %>% 
                             mutate(name = "BM"),
                           
) %>% 
  group_by(펀드설명,name) %>% 
  mutate(lag_p = lag(수정기준가,1),
         lag_p = replace_na(lag_p,1000),
         Actual_수익률 = 수정기준가/lag_p-1) %>% 
  ungroup() %>% 
  select(-lag_p)



AP_VP_MP_diff_PA_weight <-
  
  crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-05",
                                             end_date = max(BM_historical$기준일자),
                                             by = "day"),
           펀드설명 = VP_fund_name$펀드설명,
           universe_criteria %>%
             filter(자산군_대 != "유동성") %>%
             filter(!(자산군_대 %in% c("07J48", "07J49", NA))) %>% 
             select(자산군_대, 자산군_소) %>% distinct()) %>% 
  left_join(full_join(position_AP%>%
                        left_join(AP_fund_name),
                      position_VP %>%
                        left_join(VP_fund_name),
                      by = join_by(기준일자, 펀드설명, 자산군_대),
                      suffix = c("_AP", "_VP")), by = join_by(기준일자, 펀드설명, 자산군_대)) %>%
  left_join(
    left_join(MP_LTCMA_all_comb %>%
                group_by(기준일자, 펀드설명, 자산군_대) %>%
                reframe(daily_weight_MP = sum(weight)),
              BM_weight_all_comb %>%
                mutate(자산군_대 = if_else(ISIN %in% c("M2WD Index","M1WD Index"),"주식","채권")) %>%
                group_by(기준일자, 펀드설명, 자산군_대) %>%
                reframe(daily_weight_BM = sum(weight)), by = join_by(기준일자,펀드설명,자산군_대)
    ), by = join_by(기준일자, 펀드설명, 자산군_대)) %>%  
  group_by(기준일자, 펀드설명) %>%
  mutate(across(starts_with("daily_weight"), ~replace_na(., 0))) %>%
  group_by(기준일자,펀드설명,자산군_대) %>% 
  reframe(#`비중(AP-VP)` = sum(`비중(AP-VP)`),
    AP =daily_weight_AP[1],
    VP =daily_weight_VP[1],
    MP =daily_weight_MP[1],
    BM =daily_weight_BM[1]
  ) %>% 
  pivot_longer(cols = c(AP,VP,MP,BM))


AP_daily_weights_by_ticker <- AP_asset_adjust %>%
  filter(자산군_대 != "유동성") %>% 
  mutate(weight = 시가평가액 / 순자산) %>% 
  group_by(기준일자, 펀드, 종목) %>%
  summarise(weight = sum(weight, na.rm = TRUE), .groups = 'drop')

feeder_fund <- AP_daily_weights_by_ticker %>% 
  # 자펀드 비중
  filter(펀드 %in% c("07J48","07J49")) %>% 
  pivot_wider(
    names_from = 펀드,
    values_from = weight,
    values_fill = list(weight = 0)) 

master_fund<- AP_daily_weights_by_ticker %>% 
  #모펀드 비중
  filter(펀드 %in% c("07J34","07J41"),종목 %in%c("032280007J48","032280007J49") ) %>%
  pivot_wider(
    names_from = 종목,
    values_from = weight,
    names_prefix = "ratio_")

master_fund %>% inner_join(feeder_fund,relationship = "many-to-many") %>% 
  mutate(weight = `ratio_032280007J48`*`07J48`+`ratio_032280007J49`*`07J49`) %>% 
  select(기준일자,펀드,종목,weight)->mysuper_position

# 최종 포트폴리오 가중치 데이터 프레임 생성








return_information_PA <- 
  bind_rows(
    
    bind_rows(
      AP_daily_weights_by_ticker %>% 
        filter(!(펀드 %in% c("07J34","07J41","07J48","07J49"))) %>% 
        bind_rows(mysuper_position) %>% 
        left_join(AP_fund_name) %>% 
        rename(ISIN = 종목) %>% 
        group_by(펀드) %>% 
        filter(기준일자==기준일자[1]) %>% 
        ungroup() %>% 
        mutate(weight =0),
      AP_daily_weights_by_ticker %>% 
        filter(!(펀드 %in% c("07J34","07J41","07J48","07J49"))) %>% 
        bind_rows(mysuper_position) %>% 
        left_join(AP_fund_name) %>% 
        rename(ISIN = 종목) %>%
        filter(기준일자 %in% (holiday_calendar %>% filter(hldy_yn=="N") %>% pull(기준일자))) %>%
        left_join(holiday_calendar %>% 
                    mutate(다음영업일 = ymd(다음영업일)) %>% 
                    select(기준일자, 다음영업일)) %>% 
        select(-기준일자) %>% 
        select(기준일자 = 다음영업일,펀드,ISIN,weight,펀드설명,설정일) %>% 
        group_by(펀드,ISIN) %>% 
        timetk::pad_by_time(.fill_na_direction = "down",.by = "day",.date_var = "기준일자") %>% 
        arrange(기준일자) %>% 
        ungroup() %>% 
        filter(기준일자<today())
    )%>% 
      #left_join(MP_performance_preprocessing , by = join_by(기준일자,ISIN,자산군_대,자산군_소)) %>% 
      left_join(all_tickers_daily_return , by = join_by(기준일자,ISIN)) %>% 
      group_by(기준일자,펀드설명,자산군_대) %>% 
      reframe(전일대비등락률 = sum(weight*전일대비등락률) ) %>% 
      mutate(name = "AP"),
    bind_rows(
      VP_asset_adjust %>% 
        left_join(VP_fund_name) %>% 
        select(-펀드) %>% 
        filter(자산군_대 !="유동성") %>% 
        mutate(weight = 시가평가액 / 순자산) %>% 
        mutate(weight = replace_na(weight,0)) %>% 
        select(-c(종목명,시가평가액,순자산,자산군_중)) %>% 
        rename(ISIN = 종목) 
    ) %>% 
      filter(기준일자 %in% (holiday_calendar %>% filter(hldy_yn=="N") %>% pull(기준일자))) %>%
      left_join(holiday_calendar %>% 
                  mutate(다음영업일 = ymd(다음영업일)) %>% 
                  select(기준일자, 다음영업일)) %>% 
      select(-기준일자) %>% 
      select(기준일자 = 다음영업일,자산군_대,자산군_소,ISIN,weight,펀드설명,설정일) %>% 
      group_by(펀드설명,ISIN) %>% 
      timetk::pad_by_time(.fill_na_direction = "down",.by = "day",.date_var = "기준일자") %>% 
      arrange(기준일자) %>% 
      ungroup() %>% 
      filter(기준일자<today()) %>% 
      #left_join(all_tickers_daily_return , by = join_by(기준일자,ISIN,자산군_대,자산군_소)) %>% 
      left_join(all_tickers_daily_return %>% select(-contains("자산군")) , by = join_by(기준일자,ISIN)) %>% 
      group_by(기준일자,펀드설명,자산군_대) %>% 
      reframe(전일대비등락률 = sum(weight*전일대비등락률) ) %>% 
      mutate(name = "VP"),
    MP_LTCMA_all_comb %>% 
      left_join(MP_performance_preprocessing %>% select(기준일자,ISIN,전일대비등락률),
                by = join_by(기준일자,ISIN)) %>% 
      group_by(기준일자,펀드설명,자산군_대) %>% 
      reframe(전일대비등락률 = sum(weight*전일대비등락률) ) %>% 
      mutate(name = "MP"),
    BM_weight_all_comb %>% 
      mutate(자산군_대 = if_else(ISIN %in% c("M2WD Index","M1WD Index"),"주식","채권")) %>% 
      left_join(BM_performance_preprocessing%>% select(기준일자,ISIN=자산군,전일대비등락률),
                by = join_by(기준일자,ISIN)) %>% 
      group_by(기준일자,펀드설명,자산군_대) %>% 
      reframe(전일대비등락률 = sum(weight*전일대비등락률) ) %>% 
      mutate(name = "BM")
    
  )# %>% 



brinson_preprocess <- function(fund_desc_a, name_a, fund_desc_b, name_b) {
  # fund_desc_a="TIF"
  # name_a="AP"
  # fund_desc_b ="Golden Growth"
  # name_b = "AP"
  
  oldest_date_of_comparable_AB <- AP_fund_name %>% 
    filter(펀드설명 %in% c(fund_desc_a,fund_desc_b)) %>% pull(설정일) %>% max()
  
  weight_information_Port_AB <-bind_rows(
    AP_VP_MP_diff_PA_weight %>% 
      filter((펀드설명 == fund_desc_a & name == name_a)),
    AP_VP_MP_diff_PA_weight %>% 
      filter((펀드설명 == fund_desc_b & name == name_b))
  ) %>% 
    filter(기준일자>=oldest_date_of_comparable_AB) %>% 
    mutate(port_name = if_else((펀드설명 == fund_desc_a & name == name_a), "Port_a", "Port_b")) %>% 
    pivot_wider(id_cols = c(기준일자), 
                names_from = c(port_name, 자산군_대), values_from = value, names_glue = "{.name}_weight") %>% 
    mutate(Port_a_유동성_weight = 1 - (Port_a_대체_weight + Port_a_주식_weight + Port_a_채권_weight),
           Port_b_유동성_weight = 1 - (Port_b_대체_weight + Port_b_주식_weight + Port_b_채권_weight),
           Port_a_대체_weight = 1-(Port_a_주식_weight +Port_a_유동성_weight+Port_a_채권_weight),
           Port_b_대체_weight = 1-(Port_b_주식_weight +Port_b_유동성_weight+Port_b_채권_weight))
  
  return_information_Port_AB <- bind_rows(
    return_information_PA %>% 
      filter((펀드설명 == fund_desc_a & name == name_a)),
    return_information_PA %>% 
      filter((펀드설명 == fund_desc_b & name == name_b))
  ) %>% 
    filter(기준일자>=oldest_date_of_comparable_AB) %>% 
    mutate(port_name = if_else((펀드설명 == fund_desc_a & name == name_a), "Port_a", "Port_b")) %>% 
    mutate(전일대비등락률  = replace_na(전일대비등락률, 0)) %>% 
    complete(자산군_대, nesting(기준일자,펀드설명,name,port_name)) %>%
    filter(!is.na(자산군_대)) %>% 
    pivot_wider(id_cols = c(기준일자), 
                names_from = c(자산군_대, port_name), values_from = 전일대비등락률, names_glue = "{.name}_수익률") %>% 
    mutate(across(.cols = -기준일자, ~replace_na(., 0))) 
  
  
  
  brinson_information_Port_AB <- 
    weight_information_Port_AB %>% 
    left_join(call_rate) %>% 
    mutate(`콜금리/365` = zoo::na.locf(`콜금리/365`)) %>% 
    left_join(return_information_Port_AB, by = join_by(기준일자)) %>% 
    left_join(
      (bind_rows(
        Actual_return %>% 
          filter((펀드설명 == fund_desc_a & name == name_a)),
        Actual_return %>% 
          filter((펀드설명 == fund_desc_b & name == name_b))
      ) %>% 
        mutate(port_name = if_else((펀드설명 == fund_desc_a & name == name_a), "Port_a", "Port_b")) %>% 
        pivot_wider(id_cols = c(기준일자), 
                    names_from = c(port_name), values_from = Actual_수익률, names_glue = "Actual_{.name}_수익률")), 
      by = join_by(기준일자)
    ) %>% 
    mutate(across(.cols = -기준일자, ~replace_na(., 0))) 
  
  return(brinson_information_Port_AB)
}

brinson_results <- function(processed_data, from_when, to_when) {
  #from_when = '2024-01-01';to_when = '2024-08-13';
  result_data <- processed_data %>% 
    # brinson_information_Port_AB %>% 
    mutate(Port_a_채권및유동성_weight = Port_a_채권_weight + Port_a_유동성_weight,
           Port_b_채권및유동성_weight = Port_b_채권_weight + Port_b_유동성_weight,
           채권및유동성_Port_a_수익률 = 채권_Port_a_수익률 + `콜금리/365` * Port_a_유동성_weight,
           채권및유동성_Port_b_수익률 = 채권_Port_b_수익률 + `콜금리/365` * Port_b_유동성_weight) %>% 
    select(-c(채권_Port_a_수익률, 채권_Port_b_수익률, Port_a_채권_weight, Port_b_채권_weight)) %>% 
    filter(기준일자 >= from_when & 기준일자 <= to_when) %>% 
    mutate(across(
      .cols = contains("_weight"),
      .fns = ~ {
        first_non_zero <- which(.x != 0)[1]
        if (is.na(first_non_zero)) return(.x)
        c(rep(0, first_non_zero - 1), cummean(.x[first_non_zero:length(.x)]))
      }
    )) %>% 
    mutate(`주식+채권_Port_a`= 주식_Port_a_수익률+채권및유동성_Port_a_수익률 ,
           `채권+대체_Port_a`= 채권및유동성_Port_a_수익률+대체_Port_a_수익률 ,
           `주식+대체_Port_a`= 주식_Port_a_수익률+대체_Port_a_수익률 ,
           `주+대+채_Port_a`=주식_Port_a_수익률+채권및유동성_Port_a_수익률 +대체_Port_a_수익률,
           `주식+채권_Port_b`= 주식_Port_b_수익률+채권및유동성_Port_b_수익률 ,
           `채권+대체_Port_b`= 채권및유동성_Port_b_수익률+대체_Port_b_수익률 ,
           `주식+대체_Port_b`= 주식_Port_b_수익률+대체_Port_b_수익률 ,
           `주+대+채_Port_b`=주식_Port_b_수익률+채권및유동성_Port_b_수익률 +대체_Port_b_수익률
    ) %>% 
    mutate(across(.cols = -c(기준일자, contains("_weight")), .fns = ~(cumprod(1 + .x) - 1))) %>% 
    mutate(`comb_주+채_Port_a`= `주식+채권_Port_a`-주식_Port_a_수익률-채권및유동성_Port_a_수익률,
           `comb_주+대_Port_a`= `주식+대체_Port_a`-주식_Port_a_수익률-대체_Port_a_수익률,
           `comb_채+대_Port_a`= `채권+대체_Port_a`-채권및유동성_Port_a_수익률-대체_Port_a_수익률,
           `comb_주+채_Port_b`= `주식+채권_Port_b`-주식_Port_b_수익률-채권및유동성_Port_b_수익률,
           `comb_주+대_Port_b`= `주식+대체_Port_b`-주식_Port_b_수익률-대체_Port_b_수익률,
           `comb_채+대_Port_b`= `채권+대체_Port_b`-채권및유동성_Port_b_수익률-대체_Port_b_수익률,
    ) %>% 
    mutate(주식_Port_a_수익률 = 주식_Port_a_수익률+(`comb_주+채_Port_a`+`comb_주+대_Port_a`)/2+(`주+대+채_Port_a` -`채권+대체_Port_a`-(주식_Port_a_수익률+`comb_주+채_Port_a`+`comb_주+대_Port_a`))/3 ,
           채권및유동성_Port_a_수익률 = 채권및유동성_Port_a_수익률+(`comb_주+채_Port_a`+`comb_채+대_Port_a`)/2+ (`주+대+채_Port_a` -`주식+대체_Port_a`-(채권및유동성_Port_a_수익률+`comb_주+채_Port_a`+`comb_채+대_Port_a`))/3,
           대체_Port_a_수익률 = 대체_Port_a_수익률+(`comb_채+대_Port_a`+`comb_주+대_Port_a`)/2+ (`주+대+채_Port_a` -`주식+채권_Port_a`-(대체_Port_a_수익률+`comb_채+대_Port_a`+`comb_주+대_Port_a`))/3,
           주식_Port_b_수익률 = 주식_Port_b_수익률+(`comb_주+채_Port_b`+`comb_주+대_Port_b`)/2+(`주+대+채_Port_b` -`채권+대체_Port_b`-(주식_Port_b_수익률+`comb_주+채_Port_b`+`comb_주+대_Port_b`))/3 ,
           채권및유동성_Port_b_수익률 = 채권및유동성_Port_b_수익률+(`comb_주+채_Port_b`+`comb_채+대_Port_b`)/2+ (`주+대+채_Port_b` -`주식+대체_Port_b`-(채권및유동성_Port_b_수익률+`comb_주+채_Port_b`+`comb_채+대_Port_b`))/3,
           대체_Port_b_수익률 = 대체_Port_b_수익률+(`comb_채+대_Port_b`+`comb_주+대_Port_b`)/2+ (`주+대+채_Port_b` -`주식+채권_Port_b`-(대체_Port_b_수익률+`comb_채+대_Port_b`+`comb_주+대_Port_b`))/3) %>% 
    select(-contains("+")) %>% 
    mutate(across(.cols = -기준일자, ~replace_na(., 0))) %>%
    mutate(norm_Port_a_주식_R = if_else(Port_a_주식_weight != 0, 주식_Port_a_수익률 / Port_a_주식_weight, 0),
           norm_Port_a_대체_R = if_else(Port_a_대체_weight != 0, 대체_Port_a_수익률 / Port_a_대체_weight, 0),
           norm_Port_a_채권및유동성_R = if_else(Port_a_채권및유동성_weight != 0, 채권및유동성_Port_a_수익률 / Port_a_채권및유동성_weight, 0),
           norm_Port_b_주식_R = if_else(Port_b_주식_weight != 0, 주식_Port_b_수익률 / Port_b_주식_weight, 0),
           norm_Port_b_대체_R = if_else(Port_b_대체_weight != 0, 대체_Port_b_수익률 / Port_b_대체_weight, 0),
           norm_Port_b_채권및유동성_R = if_else(Port_b_채권및유동성_weight != 0, 채권및유동성_Port_b_수익률 / Port_b_채권및유동성_weight, 0)) %>% 
    mutate(A_대체 = (Port_a_대체_weight - Port_b_대체_weight) * (norm_Port_a_대체_R - norm_Port_b_대체_R),
           A_주식 = (Port_a_주식_weight - Port_b_주식_weight) * (norm_Port_a_주식_R - norm_Port_b_주식_R),
           A_채권및유동성 = (Port_a_채권및유동성_weight - Port_b_채권및유동성_weight) * (norm_Port_a_채권및유동성_R - norm_Port_b_채권및유동성_R),
           B_대체 = (Port_a_대체_weight - Port_b_대체_weight) * (norm_Port_b_대체_R),
           B_주식 = (Port_a_주식_weight - Port_b_주식_weight) * (norm_Port_b_주식_R),
           B_채권및유동성 = (Port_a_채권및유동성_weight - Port_b_채권및유동성_weight) * (norm_Port_b_채권및유동성_R),
           C_대체 = (Port_b_대체_weight) * (norm_Port_a_대체_R - norm_Port_b_대체_R),
           C_주식 = (Port_b_주식_weight) * (norm_Port_a_주식_R - norm_Port_b_주식_R),
           C_채권및유동성 = (Port_b_채권및유동성_weight) * (norm_Port_a_채권및유동성_R - norm_Port_b_채권및유동성_R),
           R_Port_a_Holding_base = 대체_Port_a_수익률 + 주식_Port_a_수익률 + 채권및유동성_Port_a_수익률,
           R_Port_b_Holding_base = 대체_Port_b_수익률 + 주식_Port_b_수익률 + 채권및유동성_Port_b_수익률,
           .after = 기준일자) %>% 
    select(기준일자, contains("Actual"), contains("_Holding_base"), matches("(?-i)A_|(?-i)B_|(?-i)C_"),
           주식_Port_a_수익률, 주식_Port_b_수익률, 대체_Port_a_수익률, 대체_Port_b_수익률, 채권및유동성_Port_a_수익률, 채권및유동성_Port_b_수익률) %>% 
    mutate(R_Port_a_기타 = Actual_Port_a_수익률 - R_Port_a_Holding_base,
           R_Port_b_기타 = Actual_Port_b_수익률 - R_Port_b_Holding_base,
           .after = Actual_Port_b_수익률)
  
  return(result_data)
}

brinson_summary<- function(brinson_result){
  #result %>% 
  brinson_result %>% 
    mutate(Excess_Return = Actual_Port_a_수익률-Actual_Port_b_수익률,
           A= rowSums(select(.,matches("(?-i)A_"))),
           B= rowSums(select(.,matches("(?-i)B_"))),
           C= rowSums(select(.,matches("(?-i)C_"))),
           X= A+B+C,
           Y=(Excess_Return)-X,.after = Actual_Port_b_수익률)  -> PA_results
  
  
  
  bind_cols( tibble(구분 = c("포트폴리오","기타 수익률","Holding base 수익률","주식 기여수익률","대체 기여수익률","채권 및 유동성 기여수익률")),
             PA_results %>% 
               filter(기준일자==max(기준일자)) %>% 
               select(contains("Port_a") & !contains("_weight")) %>% pivot_longer(cols = everything()),
             PA_results %>% 
               filter(기준일자==max(기준일자)) %>% 
               select(contains("Port_b") & !contains("_weight")) %>% pivot_longer(cols = everything())
  ) %>% select(1,3,5) %>% setNames(c("구분","Port a","Port b")) -> summary1
  
  
  PA_results %>%
    filter(기준일자 == max(기준일자)) %>%
    select(!contains("Port_a")&!contains("Port_b")) %>% 
    select(-기준일자) %>% 
    pivot_longer(cols = everything(), names_to = "name", values_to = "value") %>%
    mutate(name = factor(name, levels = c("A_대체", "A_주식", "A_채권및유동성", "A",
                                          "B_대체", "B_주식", "B_채권및유동성", "B",
                                          "C_대체", "C_주식", "C_채권및유동성", "C",
                                          "X", "Y", "Excess_Return"))) %>% 
    #mutate( value = scales::percent(value,accuracy = 0.01)) %>% 
    rename(세부정보 =name,  `수익률(%)`=value   )->summary2  
  
  return(list(PA_results,summary1,summary2))
}


# # 
# # # 예시 사용
# from_when <- "2024-01-01"
# to_when <- "2024-07-18"
# brinson_processed_data <- brinson_preprocess("TDF2030", "AP", "Golden Growth", "AP")
# result <- brinson_results(brinson_processed_data, from_when, to_when)
# # brinson_summary(result)[[1]] %>% tail()
# brinson_summary(result)[[2]]
# brinson_summary(result)[[3]]
# brinson_processed_data %>% colnames()
# result %>% colnames()
