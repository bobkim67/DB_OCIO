library(tidyverse)
library(shiny)
library(plotly)
library(scales)
library(ecos)
library(rlang) # sym() 함수를 사용하기 위해 필요
library(DBI)
library(RMariaDB) # 또는 library(RMySQL)
library(lubridate)
library(blob)



# Performance -------------------------------------------------------------


# _AP, VP ------------------------------------------------------------------

# Set the locale to Korean
korean_locale <- locale(encoding = "CP949")

AP_performance_preprocessing<- table_8183_AP %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  mutate(MOD_STPR = as.double(MOD_STPR)) %>% 
  rename(기준일자=STD_DT,`펀드`= FUND_CD, 펀드명 = FUND_NM ,수정기준가=MOD_STPR) %>% 
  left_join(AP_fund_name,by = join_by(펀드)) %>% 
  filter(IMC_CD=="003228") %>% 
  select(-IMC_CD) 


VP_performance_preprocessing<- table_8183_VP %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  mutate(MOD_STPR = as.double(MOD_STPR)) %>% 
  rename(기준일자=STD_DT,`펀드`= FUND_CD, 펀드명 = FUND_NM ,수정기준가=MOD_STPR) %>% 
  left_join(VP_fund_name,by = join_by(펀드)) %>% 
  group_by(펀드) %>% 
  # 보통 VP는 설정이전부터 값이 존재해서 기준값이 필요. 하지만 백테스트기반인 경우 설정일부터 데이터가 있기 때문에 기준값을 1000원으로 예외처리 
  mutate(
    기준값 = if_else(any(기준일자 == (설정일[1] - days(1))),
                  first(수정기준가[기준일자 == (설정일[1] - days(1))], default = NA_real_),
                  1000)
  ) %>% 
  mutate(수정기준가 = 수정기준가/기준값*1000 ) %>% 
  filter(기준일자>=설정일) %>% 
  ungroup() %>% 
  filter(IMC_CD=="M03228") %>%  
  select(-IMC_CD,-기준값)


#ACETDF 추가 실험 중
#--------------------------------------------------------
VP_performance_preprocessing_ACETDF<- table_8183_ACETDF %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  mutate(MOD_STPR = as.double(MOD_STPR)) %>% 
  rename(기준일자=STD_DT,`펀드`= FUND_CD, 펀드명 = FUND_NM ,수정기준가=MOD_STPR) %>% 
  left_join(VP_fund_name,by = join_by(펀드)) %>% 
  group_by(펀드) %>% 
  mutate(
    기준값 = if_else(any(기준일자 == (설정일[1] - days(1))),
                  first(수정기준가[기준일자 == (설정일[1] - days(1))], default = NA_real_),
                  1000)
  ) %>% 
  mutate(수정기준가 = 수정기준가/기준값*1000 ) %>% 
  filter(기준일자>=설정일) %>% 
  ungroup() %>% 
  filter(IMC_CD=="M03228") %>%  
  select(-IMC_CD,-기준값)



AP_performance_preprocessing <- bind_rows(AP_performance_preprocessing,VP_performance_preprocessing_ACETDF %>% 
                                            filter(!(펀드설명%in%c("ACETDF2030","ACETDF2050","ACETDF2080"))) )
VP_performance_preprocessing <- bind_rows(VP_performance_preprocessing,VP_performance_preprocessing_ACETDF)



# _MP ----------------------------


MP_historical_temp_for_recent_VP <- MP_historical %>% 
  left_join(Data_List %>% select(dataset_id=id, name=ISIN)) %>% 
  mutate(기준일자 = ymd(timestamp_observation)) %>% 
  arrange(기준일자) %>% 
  select(-c(1:4)) %>% 
  mutate(data = map(.x= data, .f = ~jsonlite::parse_json((rawToChar(unlist(.x)))))  ) %>% 
  mutate(USD = map_dbl(.x= data, .f = ~unlist(.x)[1]) ) %>% 
  mutate(KRW = map_dbl(.x= data, .f = ~unlist(.x)[2]) ) %>%# distinct() %>% 
  mutate(pulling_value = if_else(str_sub(name,1,2) =="KR",KRW,USD)) %>% select(기준일자,name,pulling_value) 

MP_historical_prep <- MP_historical_temp_for_recent_VP %>%
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = pulling_value) %>% 
  mutate(across(.cols =!(contains("KR")|기준일자) , .fns = ~lag(.x ,n=1) ))


crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                           end_date = max(MP_historical_prep$기준일자) ,
                                           by = "day") ,
         ISIN = colnames(MP_historical_prep)[-1]) %>% 
  # 고려사항 1. Data source : Factset 데이터 사용.
  left_join(MP_historical_prep %>% 
              pivot_longer(cols = -기준일자, names_to = "ISIN", values_to = "종가") %>% 
              filter(기준일자>="2022-10-04"),
            by = join_by(기준일자,ISIN)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = ISIN,values_from = 종가) %>% 
  #  고려사항 3. 한국휴일 반영
  mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays,1,0)) %>% 
  mutate(across(.cols = !(contains("KR")|기준일자), .fns = ~if_else(korea_holiday==1, NA, .x) )) %>% 
  select(-korea_holiday) %>% 
  pivot_longer(cols = -기준일자,names_to = "ISIN",values_to = "종가") %>% 
  left_join(USDKRW,by =  join_by(기준일자)) %>% 
  left_join(universe_criteria %>% select(종목코드, 자산군_대,자산군_소) %>% distinct(),by = join_by(ISIN ==종목코드)) %>% 
  mutate(Country = str_sub(ISIN,start=1,end=2)) %>% 
  group_by(ISIN) %>% 
  mutate(first_valid_date = min(기준일자[!is.na(종가)], na.rm = TRUE)) %>%
  filter(기준일자 >= first_valid_date) %>%
  select(-first_valid_date) %>% 
  mutate(종가 = zoo::na.locf(종가)) %>% 
  # 고려사항 4. 환율은 당일 값 사용.
  mutate(`USD/KRW` = zoo::na.locf(`USD/KRW`)) %>% 
  mutate(price_KRW = if_else(Country=="US", 종가*`USD/KRW`,종가)) %>% 
  mutate(last_price_KRW = lag(price_KRW,n=1),
         전일대비등락률 = price_KRW/last_price_KRW-1) %>%
  select(기준일자,ISIN, 전일대비등락률,자산군_대, 자산군_소) %>% 
  filter(기준일자>="2022-10-05") %>% ungroup()  -> MP_performance_preprocessing

MP_LTCMA_all_comb <- 
  MP_LTCMA %>% 
  filter(리밸런싱날짜<today()) %>% 
  group_by(리밸런싱날짜,펀드설명) %>%group_keys() %>% 
  group_by(펀드설명) %>% 
  mutate(rebalancing_index= row_number()) %>% 
  # 리밸런싱날짜 당일까지는 이전 비중을 통한 수익률 계산 
  mutate(가중치날짜 = lead(리밸런싱날짜,n=1)) %>% 
  mutate(가중치날짜 = replace_na(가중치날짜,max(AP_performance_preprocessing$기준일자))) %>% 
  mutate(기준일자 = map2(.x = 리밸런싱날짜,.y = 가중치날짜 , .f = ~timetk::tk_make_timeseries(start_date = .x,
                                                                               end_date = .y ,
                                                                               by = "day"))) %>% 
  unnest(cols = 기준일자) %>% 
  ungroup() %>% 
  filter( !(리밸런싱날짜==기준일자 & rebalancing_index!=1) ) %>% 
  inner_join(
    MP_LTCMA %>% 
      filter(weight>0)
    ,by = join_by(리밸런싱날짜, 펀드설명),relationship = "many-to-many"
  ) 




MP_LTCMA_all_comb %>% 
  left_join(MP_performance_preprocessing , by = join_by(기준일자,ISIN,자산군_대,자산군_소)) %>% 
  group_by(기준일자,펀드설명) %>% 
  reframe(전일대비등락률 = sum(weight*전일대비등락률),
          last_rebalance = 리밸런싱날짜[1]) %>% 
  group_by(펀드설명) %>%
  filter(!(펀드설명 %in% c("ACETDF2030","ACETDF2050","ACETDF2080") & 기준일자<="2025-03-06" ) ) %>% 
  mutate(수정기준가 = 1000*cumprod(전일대비등락률+1)) %>% 
  ungroup()%>% select(-c(전일대비등락률,last_rebalance)) %>% 
  left_join(VP_fund_name,by = join_by(펀드설명)) ->MP_performance_preprocessing_final


# _BM ----------------------------

BM_daily_price<- 
  
  tibble(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                           end_date = BM_historical$기준일자 %>% max(),
                                           by = "day")) %>% 
  left_join( BM_historical,
             by = join_by(기준일자))



BM_daily_price %>% 
  mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays,1,0)) %>% 
  mutate(across(.cols = c(2,3), .fns = ~if_else(korea_holiday==1, NA, .x) )) %>%
  select(-korea_holiday) %>% 
  pivot_longer(cols = -기준일자,names_to = "자산군",values_to = "기준가") %>% 
  group_by(자산군) %>% 
  mutate(기준가 = zoo::na.locf(기준가)) %>% ungroup() %>% 
  #pivot_wider(id_cols = 기준일자,names_from = 자산군,values_from = 기준가) %>% view()
  left_join(USDKRW,by =  join_by(기준일자))  %>% 
  mutate(`USD/KRW` = zoo::na.locf(`USD/KRW`)) %>% 
  #mutate(price_KRW = if_else(자산군 %in% c("M2WD Index","LEGATRUU Index"), 기준가*`USD/KRW`,기준가)) %>% 
  mutate(price_KRW = if_else(자산군 %in% c("M2WD Index","M1WD Index"), 기준가*`USD/KRW`,기준가)) %>% 
  group_by(자산군) %>%
  mutate(last_price_KRW = lag(price_KRW,n=1),
         전일대비등락률 = price_KRW/last_price_KRW-1) %>%
  select(기준일자,자산군, 전일대비등락률) %>% 
  filter(기준일자>="2022-10-05") %>% ungroup()  -> BM_performance_preprocessing


BM_weight<- 
  MP_LTCMA %>%
  #left_join(universe_criteria %>% select(종목코드,자산군_대, 자산군_소) %>% distinct(), by = join_by(ISIN==종목코드)) %>%
  mutate(자산군 = if_else(자산군_대 == "대체", "주식", 자산군_대)) %>%
  group_by(리밸런싱날짜,펀드설명, 자산군) %>%
  reframe(weight = round(sum(weight),2) ) %>% 
  left_join(AP_fund_name %>% select(펀드설명,설정일)) %>% 
  mutate(weight = if_else((펀드설명 =="MS STABLE" & 리밸런싱날짜=="2022-10-05" & 자산군=="주식"),0.3,weight )) %>% 
  mutate(weight = if_else((펀드설명 =="MS STABLE" & 리밸런싱날짜=="2022-10-05" & 자산군=="채권"),0.7,weight )) %>% 
  mutate(weight = if_else((펀드설명 =="Golden Growth" & 자산군=="주식"),0.6,weight )) %>% 
  mutate(weight = if_else((펀드설명 =="Golden Growth" & 자산군=="채권"),0.4,weight )) %>% 
  mutate(자산군 = case_when(
    자산군 == "주식" & str_detect(펀드설명,"ACE") ~ "M1WD Index",
    자산군 == "주식" ~ "M2WD Index",
    자산군 == "채권" & 펀드설명 %in% c("MS GROWTH", "MS STABLE","Golden Growth") ~ "KST0000T Index",#"KIS 종합 총수익지수",
    자산군 == "채권" & str_detect(펀드설명,"ACE") ~ "KISABBAA- Index", # KIS 종합채권 AA-이상 총수익지수
    자산군 == "채권" ~ "LEGATRUU Index",
    TRUE ~ 자산군
  )) %>% 
  rename(ISIN= 자산군) %>% 
  filter(!(펀드설명=="MS GROWTH" & 리밸런싱날짜!="2022-10-05")) %>% 
  filter(!(펀드설명=="MS STABLE" & 리밸런싱날짜=="2023-11-29"))# %>% 
#mutate(weight = if_else((펀드설명=="MS GROWTH" & ISIN=="M2WD Index"),0.7,
#                        if_else((펀드설명=="MS GROWTH" & ISIN=="KST0000T Index"),0.3,weight)))

BM_weight_all_comb <- 
  BM_weight %>% 
  filter(리밸런싱날짜<today()) %>% 
  group_by(리밸런싱날짜,펀드설명) %>%group_keys() %>% 
  group_by(펀드설명) %>% 
  mutate(rebalancing_index= row_number()) %>% 
  # 리밸런싱날짜 당일까지는 이전 비중을 통한 수익률 계산 
  mutate(가중치날짜 = lead(리밸런싱날짜,n=1)) %>% 
  mutate(가중치날짜 = replace_na(가중치날짜,max(AP_performance_preprocessing$기준일자))) %>% 
  mutate(기준일자 = map2(.x = 리밸런싱날짜,.y = 가중치날짜 , .f = ~timetk::tk_make_timeseries(start_date = .x,
                                                                               end_date = .y ,
                                                                               by = "day"))) %>% 
  unnest(cols = 기준일자) %>% 
  ungroup() %>% 
  filter( !(리밸런싱날짜==기준일자 & rebalancing_index!=1) ) %>% 
  inner_join(
    BM_weight %>% 
      select(-설정일) %>%
      filter(weight>0)
    ,by = join_by(리밸런싱날짜, 펀드설명),relationship = "many-to-many"
  ) %>% 
  group_by(펀드설명) %>%
  filter(!(펀드설명 %in% c("ACETDF2030","ACETDF2050","ACETDF2080") & 기준일자<="2025-03-06" ) ) %>% 
  ungroup()


BM_weight_all_comb %>% filter(weight>0) %>%
  left_join(BM_performance_preprocessing , by = join_by(기준일자,ISIN==자산군)) %>%
  group_by(기준일자,펀드설명) %>% 
  reframe(전일대비등락률 = sum(weight*전일대비등락률),
          last_rebalance = 리밸런싱날짜[1]) %>%
  group_by(펀드설명) |> 
  mutate(수정기준가 = 1000*cumprod(전일대비등락률+1)) %>%
  ungroup()%>% select(-c(전일대비등락률,last_rebalance)) %>% 
  left_join(VP_fund_name,by = join_by(펀드설명)) ->BM_performance_preprocessing_final



#left_join(rf_data_KORIBOR_3_month %>% select(-c(Rf,unit_name)),by = "기준일자") %>% 
#mutate(Rf_Return = zoo::na.locf(Rf_Return))->BM_performance_preprocessing_final

# Position ----------------------------------------------------------------




Market_Cap_GV %>% 
  mutate(기준일자 = ymd(timestamp_observation)) %>% 
  arrange(기준일자) %>% 
  select(기준일자,dataset_id,data) %>% 
  filter(기준일자>="2020-01-01") %>% 
  mutate(data = map(data, ~jsonlite::parse_json(rawToChar(unlist(.x))))) %>% 
  mutate(marketcap= map_dbl(data, ~unlist(.x)[1])) %>% 
  mutate(name = case_when(dataset_id == "250" ~ "미국 성장주",
                          dataset_id == "251" ~ "미국 가치주")) %>% 
  bind_rows(tibble(기준일자 = holiday_calendar %>% 
                     filter(기준일자==today()) %>% pull(전영업일) %>% ymd(),
                   name = c("미국 성장주","미국 가치주"))) %>% 
  group_by(기준일자,name)%>%
  filter( row_number()==1) %>%
  group_by(name) %>% 
  mutate(`marketcap(T-1)` = lag(marketcap,n=1)) %>% 
  filter(!is.na(`marketcap(T-1)`)) %>% 
  group_by(기준일자) %>% 
  mutate(비중 = `marketcap(T-1)`/sum(`marketcap(T-1)`)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = 비중) %>% 
  ungroup() -> historical_MarketCap_GV


# 데이터 불러오기
AP_total <- table_8004_AP %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  filter(IMC_CD=="003228") %>% 
  select(-IMC_CD) %>% 
  rename(기준일자=STD_DT,펀드 = FUND_CD,종목=ITEM_CD,종목명=ITEM_NM,시가평가액 = EVL_AMT,순자산=NAST_AMT) %>% 
  mutate(across(.cols = c(시가평가액,순자산),.fns = ~as.double(.x)))


VP_total <- table_8004_VP %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  filter(IMC_CD=="M03228") %>% 
  select(-IMC_CD) %>% 
  rename(기준일자=STD_DT,펀드 = FUND_CD,종목=ITEM_CD,종목명=ITEM_NM,시가평가액 = EVL_AMT,순자산=NAST_AMT) %>% 
  mutate(across(.cols = c(시가평가액,순자산),.fns = ~as.double(.x)))


AP_asset_adjust<- asset_classification_and_adjust(AP_total) %>% 
  mutate(
    자산군_대 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "유동성", 자산군_대),
    자산군_중 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "원화 유동성", 자산군_중),
    자산군_소 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), factor("원화 유동성"), 자산군_소)
  )

VP_asset_adjust<- asset_classification_and_adjust(VP_total) %>% 
  mutate(
    자산군_대 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "유동성", 자산군_대),
    자산군_중 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "원화 유동성", 자산군_중),
    자산군_소 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), factor("원화 유동성"), 자산군_소)
  )


union(
  
  AP_asset_adjust %>% 
    filter(is.na(자산군_대)) %>% 
    select(종목,종목명) %>% distinct()
  ,
  VP_asset_adjust %>% 
    filter(is.na(자산군_대)) %>% 
    select(종목,종목명) %>% distinct()
  
)# %>% 
# write.csv("new_criteria.csv", row.names = FALSE, fileEncoding = "euc-kr")

#ACETDF 추가 실험 중
#--------------------------------------------------------
VP_total_ACETDF <- table_8004_ACETDF %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>%
  select(-IMC_CD) %>% 
  rename(기준일자=STD_DT,펀드 = FUND_CD,종목=ITEM_CD,종목명=ITEM_NM,시가평가액 = EVL_AMT,순자산=NAST_AMT) %>% 
  mutate(across(.cols = c(시가평가액,순자산),.fns = ~as.double(.x)))

VP_ACETDF_asset_adjust<- asset_classification_and_adjust(VP_total_ACETDF) %>% 
  mutate(
    자산군_대 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "유동성", 자산군_대),
    자산군_중 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "원화 유동성", 자산군_중),
    자산군_소 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), factor("원화 유동성"), 자산군_소)
  )

# AP_ACETDF_asset_adjust <- VP_ACETDF_asset_adjust %>% mutate(시가평가액=NA_real_) %>% mutate(순자산=NA_real_)
# AP_asset_adjust <- bind_rows(AP_asset_adjust, AP_ACETDF_asset_adjust)
AP_asset_adjust <- bind_rows(AP_asset_adjust, VP_ACETDF_asset_adjust)


AP_asset_adjust<- bind_rows(
  
  AP_asset_adjust %>% 
    filter(!str_detect(자산군_소,"분해필요")) ,
  
  AP_asset_adjust %>% 
    filter(str_detect(자산군_소,"분해필요")) %>% 
    left_join(historical_MarketCap_GV) %>% 
    pivot_longer(cols = c(`미국 성장주`,`미국 가치주`),names_to = "자산군_소_weight") %>% 
    mutate(시가평가액 = 시가평가액*value,
           자산군_소 = factor(자산군_소_weight)) %>% 
    select(-c(자산군_소_weight,value))
  
) %>% 
  arrange(기준일자,펀드,자산군_소)




VP_asset_adjust <- bind_rows(VP_asset_adjust, VP_ACETDF_asset_adjust)
#--------------------------------------------------------


# 복제율 ----
#replicate_disparate_rate <- reactive({


# AP와 VP의 포지션 데이터 계산을 위한 reactive 표현식
position_AP_summarised <- 
  calculate_portfolio_weights(
    data = AP_asset_adjust,
    asset_group = "자산군_소",
    division = "AP"
  )

# position_AP_summarised <- position_AP_summarised %>% mutate(daily_weight=case_when(str_detect(펀드,"MP") ~ NA_real_, TRUE ~ daily_weight))
# position_AP_summarised <- position_AP_summarised %>% mutate(daily_weight = case_when(str_detect(펀드,"4MP") ~  0, TRUE ~ daily_weight))

position_VP_summarised <-
  calculate_portfolio_weights(
    data = VP_asset_adjust,
    asset_group = "자산군_소",
    division = "VP"
  )

# 여기에 daily_return lag안한거 환율도 고려 X 수익률반영하여 weight 산출하기..----

position_VP_summarised_당일아침 <-
  calculate_portfolio_weights(
    data =   VP_asset_adjust %>% 
      left_join(MP_historical_temp_for_recent_VP %>% 
                  arrange(기준일자) %>% 
                  group_by(name) %>%
                  mutate(daily_return = pulling_value/lag(pulling_value)-1) %>%
                  select(-pulling_value) %>%
                  filter(!is.na(daily_return)) %>% ungroup() ,by = join_by(기준일자,"종목"=="name")
      )%>% 
      mutate(daily_return = if_else(is.na(daily_return)| str_sub(종목,1,2)=="KR", 0,daily_return )) %>% 
      mutate(T_price_조정시가평가액 = 시가평가액 * (1+daily_return)) %>% 
      group_by(기준일자,펀드)%>%
      mutate(`순자산증감액(해외주식_T일가격base)` = sum(T_price_조정시가평가액-시가평가액)) %>%
      mutate(T_price_조정순자산= 순자산+`순자산증감액(해외주식_T일가격base)`) %>%
      select(기준일자,펀드,종목,종목명,
             시가평가액 = T_price_조정시가평가액,
             순자산 = T_price_조정순자산, contains("자산군")) ,
    asset_group = "자산군_소",
    division = "VP"
  )

#position_VP_summarised %>% 
#  bind_cols(position_VP_summarised_당일아침 %>% select(`daily_weight(당일)`=daily_weight)) %>% 
#  mutate(daily_weight_diff = daily_weight -`daily_weight(당일)`)

# ACE TDF 추가 실험 중
# position_AP와 position_VP를 펀드설명을 기준으로 full_join하고 차이 계산
crossing(기준일자 =unique(AP_asset_adjust$기준일자),
         펀드설명 =  Fund_Information %>% filter(구분 %in% c("TDF","BF","ACE TDF")) %>% pull(펀드설명),
         universe_criteria %>%
           filter(자산군_대!="유동성") %>% 
           filter(!(자산군_소%in%c("07J48","07J49",NA)) ) %>%
           select(자산군_대,자산군_소) %>% distinct()
         #펀드설정일 = "??-??-??"
) %>%
  left_join(full_join(position_AP_summarised %>%
                        left_join(AP_fund_name,by = join_by(펀드)),
                      position_VP_summarised %>%
                        left_join(VP_fund_name,by = join_by(펀드)),
                      by = join_by(기준일자, 펀드설명, 자산군_소),
                      suffix = c("_AP", "_VP")) %>%
              left_join(
                position_VP_summarised_당일아침 %>%
                  left_join(VP_fund_name,by = join_by(펀드)) %>% 
                  select(기준일자,펀드_VP=펀드,자산군_소,`daily_weight_VP*`=daily_weight),
                by = join_by(기준일자,펀드_VP, 자산군_소)
                
              )
            , by=join_by(기준일자,펀드설명,자산군_소)) %>% 
  left_join(
    
    MP_LTCMA %>%
      group_by(리밸런싱날짜,펀드설명,자산군_소) %>%
      reframe(daily_weight_MP = sum(weight)) ,
    by = join_by(기준일자>=리밸런싱날짜,펀드설명,자산군_소)
    
  )  %>% 
  
  filter(!is.na(리밸런싱날짜)| (is.na(리밸런싱날짜)&!is.na(설정일_AP)&!is.na(daily_weight_AP) ) ) %>%
  group_by(기준일자,펀드설명) %>% 
  filter(리밸런싱날짜==max(리밸런싱날짜,na.rm = TRUE)| (is.na(리밸런싱날짜)&!is.na(설정일_AP)&!is.na(daily_weight_AP) ) ) %>% 
  mutate(across(starts_with("daily_weight"), ~replace_na(., 0))) %>%
  
  # reframe(across(starts_with("daily"),.fns = ~sum(.x)))
  # mutate(`비중(AP-VP)` = if_else(str_detect(펀드설명,"ACE"),NA_real_,daily_weight_AP - daily_weight_VP)) %>% 
  mutate(`비중(AP-VP)` = daily_weight_AP - daily_weight_VP) %>% 
  mutate(`비중(VP-MP)` = daily_weight_VP - daily_weight_MP) %>%
  mutate(`비중(VP*-MP)` = `daily_weight_VP*` - daily_weight_MP) %>%
  ungroup()->AP_VP_MP_diff_summarised

# AP_VP_MP_diff_summarised <- AP_VP_MP_diff_summarised %>% mutate(daily_weight_AP=case_when(str_detect(펀드설명,"ACE") ~ NA_real_, TRUE ~ daily_weight_AP))
AP_VP_MP_diff_summarised %>%
  select(-펀드_AP,-펀드_VP) %>% 
  mutate(new_대분류 =if_else(자산군_대=="채권","채권","주식+대체") ) %>% 
  group_by(기준일자,펀드설명) %>% 
  mutate(
    `주식+대체비중_AP` =sum(daily_weight_AP[new_대분류=="주식+대체"]),
    `주식+대체비중_VP` =sum(daily_weight_VP[new_대분류=="주식+대체"]),
    `주식+대체비중_VP*` =sum(`daily_weight_VP*`[new_대분류=="주식+대체"]),
    채권비중_AP = sum(daily_weight_AP[new_대분류=="채권"]),
    채권비중_VP = sum(daily_weight_VP[new_대분류=="채권"]),
    `채권비중_VP*` = sum(`daily_weight_VP*`[new_대분류=="채권"]),
  ) %>%  
  mutate(위험자산비중_상한 = case_when(펀드설명 %in% c("MS GROWTH","TDF2080","ACETDF2080") ~ 1 , 
                               펀드설명 %in% c("TIF") ~ 0.4 ,
                               TRUE ~ 0.8 
  )) %>% 
  filter(new_대분류!="채권") %>% 
  group_by(기준일자,펀드설명) %>% 
  mutate(normalize_AP = sum(daily_weight_AP),
         normalize_VP = sum(daily_weight_VP),
         `normalize_VP*` = sum(`daily_weight_VP*`),
         normalize_MP = sum(daily_weight_MP)) %>%
  ungroup() %>% 
  rowwise() %>% 
  # ACETDF 추가 수정:
  mutate(min_AP_VP = min(daily_weight_AP/normalize_AP,daily_weight_VP/normalize_VP),
         `min_AP_VP*` = min(daily_weight_AP/normalize_AP,`daily_weight_VP*`/`normalize_VP*`),
         `min_주식+대체_대분류`= min(normalize_AP,normalize_VP),
         `min_주식+대체_대분류*`= min(normalize_AP,`normalize_VP*`),
         min_채권_대분류= min(채권비중_AP,채권비중_VP),
         `min_채권_대분류*`= min(채권비중_AP,`채권비중_VP*`),
  ) %>% ungroup() %>% 
  mutate(`괴N.(VP&MP)_temp` = if_else(is.na(daily_weight_VP/normalize_VP - daily_weight_MP/normalize_MP),0,daily_weight_VP/normalize_VP - daily_weight_MP/normalize_MP),
         `괴N.(VP*&MP)_temp` = if_else(is.na(`daily_weight_VP*`/`normalize_VP*` - daily_weight_MP/normalize_MP),0,`daily_weight_VP*`/`normalize_VP*` - daily_weight_MP/normalize_MP),
         `괴N.(AP&MP)_temp` = if_else(is.na(daily_weight_AP/normalize_AP - daily_weight_MP/normalize_MP),0,daily_weight_AP/normalize_AP - daily_weight_MP/normalize_MP)) %>% 
  group_by(기준일자,펀드설명) %>% 
  reframe(`괴리율(VP&MP, 주식+대체 대분류)` = normalize_VP-normalize_MP,
          `괴리율(VP*&MP, 주식+대체 대분류)` = `normalize_VP*`-normalize_MP,
          # `괴리율(AP&MP, 주식+대체 대분류)` = if_else(str_detect(펀드설명,"ACE"),NA_real_,normalize_AP-normalize_MP) ,
          `괴리율(AP&MP, 주식+대체 대분류)` = normalize_AP-normalize_MP,
          `괴리율N.(VP&MP,주식+대체 소분류)`= max(abs(`괴N.(VP&MP)_temp`))*sign(`괴N.(VP&MP)_temp`[which.max(abs(`괴N.(VP&MP)_temp`))]) ,#`max[Normalize_(VP-MP)주식+대체_소분류]`
          `괴리율N.(VP*&MP,주식+대체 소분류)`= max(abs(`괴N.(VP*&MP)_temp`))*sign(`괴N.(VP*&MP)_temp`[which.max(abs(`괴N.(VP*&MP)_temp`))]) ,#`max[Normalize_(VP-MP)주식+대체_소분류]`
          `괴리율N.(AP&MP,주식+대체 소분류)`= max(abs(`괴N.(AP&MP)_temp`))*sign(`괴N.(AP&MP)_temp`[which.max(abs(`괴N.(AP&MP)_temp`))]) ,#`max[Normalize_(VP-MP)주식+대체_소분류]` ,#`max[Normalize_(AP-MP)주식+대체_소분류]`
          `복제율N.(AP&VP,주식+대체 소분류)` = sum(min_AP_VP) ,
          `복제율N.(AP&VP*,주식+대체 소분류)` = sum(`min_AP_VP*`) ,
          `복제율(AP&VP,주식+대체 & 채권 대분류)`= sum(`min_주식+대체_대분류`[1],min_채권_대분류[1]) ,
          `복제율(AP&VP*,주식+대체 & 채권 대분류)`= sum(`min_주식+대체_대분류*`[1],`min_채권_대분류*`[1]) ,
          `위험자산비중 상한` = 위험자산비중_상한[1],
          `위험자산비중(AP)` = `주식+대체비중_AP`[1],
          `위험자산비중(VP)` = `주식+대체비중_VP`[1],
          `위험자산비중(VP*)` = `주식+대체비중_VP*`[1]
          
  ) %>% distinct() %>% 
  select(-contains("_temp")) -> replicate_disparate_rate



replicate_long_form<-
  replicate_disparate_rate %>%
  pivot_longer(cols = -c(기준일자, 펀드설명), names_to = "구분", values_to = "복제율&괴리율") %>% 
  mutate(구분= factor(구분,levels=c("괴리율(VP&MP, 주식+대체 대분류)","괴리율(VP*&MP, 주식+대체 대분류)","괴리율(AP&MP, 주식+대체 대분류)",
                                "괴리율N.(VP&MP,주식+대체 소분류)","괴리율N.(VP*&MP,주식+대체 소분류)","괴리율N.(AP&MP,주식+대체 소분류)",
                                "복제율N.(AP&VP,주식+대체 소분류)","복제율N.(AP&VP*,주식+대체 소분류)","복제율(AP&VP,주식+대체 & 채권 대분류)","복제율(AP&VP*,주식+대체 & 채권 대분류)",
                                "위험자산비중 상한","위험자산비중(VP)","위험자산비중(VP*)","위험자산비중(AP)" ))) %>% 
  mutate(구분= fct_rev(구분))  %>% 
  mutate(복제율 = str_detect(구분,"복제율"),
         위험자산 = str_detect(구분,"위험자산")
  ) %>%
  filter(!(str_detect(구분,"\\*") & ! str_detect(구분,"괴리율"))) %>%
  group_by(기준일자, 펀드설명) %>%
  mutate(위험자산_signal_orange_AP = `복제율&괴리율`[구분=="위험자산비중 상한"]*0.975- `복제율&괴리율`[구분=="위험자산비중(AP)"] < 0 ,
         위험자산_signal_red_AP = `복제율&괴리율`[구분=="위험자산비중 상한"]*1- `복제율&괴리율`[구분=="위험자산비중(AP)"] < 0 ,
         위험자산_signal_orange_VP = `복제율&괴리율`[구분=="위험자산비중 상한"]*0.975- `복제율&괴리율`[구분=="위험자산비중(VP)"] < 0 ,
         위험자산_signal_red_VP = `복제율&괴리율`[구분=="위험자산비중 상한"]*1- `복제율&괴리율`[구분=="위험자산비중(VP)"] < 0 
  ) %>% 
  ungroup() %>% 
  mutate(
    # 부호 정보 추가
    original_sign = sign(`복제율&괴리율`),
    `복제율&괴리율`=abs(`복제율&괴리율`),
    impact_color = case_when(
      (str_detect(구분,"AP")&위험자산==TRUE & 위험자산_signal_red_AP) ~ "red",
      (str_detect(구분,"AP")&위험자산==TRUE & 위험자산_signal_orange_AP) ~ "#FFA500",
      (str_detect(구분,"AP")&위험자산==TRUE & 위험자산_signal_red_VP) ~ "red",
      (str_detect(구분,"AP")&위험자산==TRUE & 위험자산_signal_orange_VP) ~ "#FFA500",
      (위험자산==TRUE ) ~ "white",
      ((펀드설명=="TIF") &(복제율==FALSE) &(abs(`복제율&괴리율`) >= 0.03)) ~ "red",
      ((펀드설명=="TIF") &(복제율==FALSE) &(abs(`복제율&괴리율`) >= 0.02))  ~ "#FFA500",
      ((복제율==TRUE) &(abs(`복제율&괴리율`) <= 0.95)) ~ "red",
      ((복제율==TRUE) &(abs(`복제율&괴리율`) <= 0.97))  ~ "#FFA500",
      ((복제율==FALSE) &(abs(`복제율&괴리율`) >= 0.05)) ~ "red",
      ((복제율==FALSE) &(abs(`복제율&괴리율`) >= 0.03))  ~ "#FFA500",
      str_detect(구분,"\\*") ~ "#B0E57C",
      TRUE ~ "white"
    ),
    # 부호에 따른 텍스트 색상 설정
    text_color = case_when(
      (original_sign==0 |복제율==TRUE|위험자산==TRUE)  ~ "black",                # 0은 검은색
      (impact_color=="red") ~ "yellow",
      original_sign > 0 ~ "red",   # 양수는 파란색
      original_sign < 0 ~ "blue"    # 음수는 빨간색
    ),
    text_label = label_percent(accuracy = 0.01)(`복제율&괴리율`)
  ) %>% 
  ungroup()




# 듀레이션복제율 -----------------------------------------------------------------

duration_historical_prep<- 
  duration_historical %>% 
  left_join(bond_url_mapping %>% select(-dataseries_id),by = join_by(dataset_id)) %>% 
  mutate(기준일자 = ymd(timestamp_observation)) %>% 
  arrange(기준일자) %>% 
  select(-c(1:4)) %>% 
  mutate(data = map(.x= data, .f = ~jsonlite::parse_json((rawToChar(unlist(.x)))))  ) %>% 
  mutate(duration = map_dbl(.x= data, .f = ~unlist(.x)[1]) ) %>% 
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = duration) %>% 
  mutate(across(.cols =!(contains("한국")|기준일자) , .fns = ~lag(.x ,n=1) )) %>% 
  filter(기준일자>=ymd("2024-06-10")) %>% 
  mutate(across(.cols =everything() , .fns = ~zoo::na.locf(.x) )) %>%  
  pivot_longer(cols = -기준일자,names_to = "자산군_소",values_to = "duration") 




AP_VP_MP_diff_summarised %>% 
  filter(자산군_대 == "채권") %>% 
  left_join(duration_historical_prep,by = join_by(기준일자,자산군_소)) %>% 
  filter(기준일자>="2024-06-10") %>% 
  group_by(기준일자,펀드설명) %>%  
  reframe(across(.cols = contains("daily_weight"),
                 .fns = ~sum(.x*duration),
                 .names = "{str_sub(col, nchar(col)-1, nchar(col))}_duration" ),
          across(.cols = contains("daily_weight"),
                 .fns = ~sum(.x*duration)/sum(.x),
                 .names = "{str_sub(col, nchar(col)-1, nchar(col))}_duration.N" ))  %>% 
  mutate(
    `펀드듀레이션(AP/VP)`= AP_duration/VP_duration,
    `펀드듀레이션(AP/MP)`= AP_duration/MP_duration,
    `펀드듀레이션(VP/MP)`= VP_duration/MP_duration,
    `채권듀레이션(AP/VP)`= AP_duration.N/VP_duration.N,
    `채권듀레이션(AP/MP)`= AP_duration.N/MP_duration.N,
    `채권듀레이션(VP/MP)`= VP_duration.N/MP_duration.N)  ->bond_duration_replicate


