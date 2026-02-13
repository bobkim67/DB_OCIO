library(tidyverse)
library(ecos)
#usethis::edit_r_environ() #API발급된 key 저장(보안을 위해 따로 저장후 로드)
# my_key <- Sys.getenv("ECOS_API_KEY")
# ecos::ecos.setKey(api_key = my_key)
# keyStatList<- ecos::keyStatList()

rf_data_KORIBOR_3_month<- ecos::statSearch(stat_code = "817Y002","010150000",cycle ="D",
                                           start_time = "20221005",end_time = "20231201") %>% tibble() %>% 
  select(Rf = item_name1,unit_name,기준일자=time,Rf_Return = data_value) %>% 
  mutate(기준일자= ymd(기준일자))


universe_criteria <- read_csv("00_data/universe_criteria.csv", locale = locale(encoding = "CP949")) |> 
  distinct() %>% 
  # 23년 말 기준으로 새롭게 편입된 US 금 두 종목 존재. universe DB에 업데이트
  bind_rows(
    tribble( ~종목코드, ~종목명,~자산군_대,~자산군_중,~자산군_소,
             "US98149E3036", "SPDR GOLD MINISHARES TRUST" , "대체","원자재","금",  
             "US46436F1030", "ISHARES GOLD TRUST MICRO"   , "대체","원자재","금"
    )
  )


# "0101000"   #한국은행 기준금리
# "010101000" #콜금리
# "010150000" #KORIBOR(3개월)   ------> [무위험수익률로 사용] 
# "010502000" #CD수익률(91일),
# "010400001" #통안증권(1년),
# "010200000" #국고채수익률(3년)
# "010200001" #국고채수익률(5년)
# "010300000" #회사채수익률(3년,AA-)


# AP, VP ------------------------------------------------------------------


# Set the locale to Korean
korean_locale <- locale(encoding = "CP949")

# Read the data with the Korean locale, skipping the first row
AP_historical_price <- read_csv("00_data/AP 기준가 추이.csv", skip = 1, locale = korean_locale)
VP_historical_price <- read_csv("00_data/VP 기준가 추이.csv", skip = 1, locale = korean_locale)

# Rest of the code for processing the column names goes here...

# Define the column names manually
column_names_AP_VP_historical_price <- c("순번","산출일자","펀드코드","펀드명","펀드유형","기준가격증감",
                                         "기준가격","과표기준가증감","과표기준가","Column10","Column11","Column12",
                                         "Column13","Column14","Column15","Column16","좌수","원본",
                                         "순자산","Column20","Column21","Column22","수정기준가","Column24",
                                         "Column25","Column26","Column27","Column28","Column29","Column30")


AP_fund_name<- tibble(
  펀드 = c("07M02",	"07J66",	"07J71",	"07J76",	"07J81",	"07J86",	"07J91",	"07J96",	"07J41",	"07J34"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"MS STABLE",	"MS GROWTH"))


VP_fund_name<- tibble(
  펀드 = c("2MP24",	"1MP30",	"1MP35",	"1MP40",	"1MP45",	"1MP50",	"1MP55",	"1MP60",	"3MP01",	"3MP02"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"MS STABLE",	"MS GROWTH"))

# Assign the new column names
colnames(AP_historical_price) <- column_names_AP_VP_historical_price
colnames(VP_historical_price) <- column_names_AP_VP_historical_price


AP_performance_preprocessing <- AP_historical_price %>% 
  select(기준일자 = 산출일자,펀드=`펀드코드`,펀드명,기준가격,수정기준가) %>% 
  left_join(AP_fund_name) %>% 
  left_join(rf_data_KORIBOR_3_month,by = "기준일자") %>% 
  mutate(Rf_Return = zoo::na.locf(Rf_Return))

VP_performance_preprocessing <- VP_historical_price %>% 
  select(기준일자 = 산출일자,펀드=`펀드코드`,펀드명,기준가격,수정기준가) %>% 
  left_join(VP_fund_name) %>% 
  left_join(rf_data_KORIBOR_3_month,by = "기준일자") %>% 
  mutate(Rf_Return = zoo::na.locf(Rf_Return))





return_performance_shallow <- function(data, input_date, from_when) {
  
  input_date <- ymd(input_date)
  data%>%
    mutate(요일 = wday(기준일자, label = TRUE)) %>%
    filter(!(펀드 %in% c("07J48", "07J49"))) %>%
    group_by(펀드설명) %>%
    mutate(설정일 = 기준일자[1]) %>%
    dplyr::filter(
      case_when(
        from_when == "YTD" ~
          (기준일자 <= input_date) & (기준일자 >= make_date(year(input_date))),
        from_when == "ITD" ~
          기준일자 <= input_date,
        from_when == "최근 1년" ~
          (기준일자 <= input_date) & (기준일자 >= input_date - years(1)  ),
        from_when == "최근 1주" ~
          (기준일자 <= input_date) & (기준일자 >= input_date - weeks(1)  ),
        from_when == "최근 1개월" ~
          (기준일자 <= input_date) & (기준일자 >= input_date - months(1) ),
        from_when == "최근 3개월" ~
          (기준일자 <= input_date) & (기준일자 >= input_date - months(3) ),
        from_when == "최근 6개월" ~
          (기준일자 <= input_date) & (기준일자 >= input_date - months(6) )
      )
    ) %>% 
    mutate(수정기준가_first = if_else( min(기준일자)==설정일, 1000, 수정기준가[1])) %>% 
    dplyr::filter(요일 == wday(input_date, label = TRUE)) %>%
    mutate(직전주_수정기준가 = lag(수정기준가, n = 1)) %>%
    mutate(주별수익률 = (수정기준가 / 직전주_수정기준가 - 1)) %>%
    select(기준일자,펀드설명, 수정기준가, 수정기준가_first, 주별수익률) %>% 
    ungroup() 
  
  
}


return_performance_deep<- function(data,input_date,from_when){
  
  data %>% 
    group_by(펀드설명) %>% 
    summarise(
      기준일자 = input_date,
      Return = 수정기준가[n()]/수정기준가_first[1]-1,
      Return_annualized = mean(주별수익률,na.rm = TRUE)*52, 
      Risk_annualized = sd(주별수익률,na.rm=TRUE)*sqrt(52),
      risk_adjusted_Return = Return_annualized / Risk_annualized,
      # Sharpe_ratio = (Return_annualized-Rf_Return[n()]/100)/Risk_annualized,
      # 무위험 수익률은 2.25로 고정. 혹시 나중에 수정할 일이 있으면 위에 코드 사용
      Sharpe_ratio = (Return_annualized-2.25/100)/Risk_annualized,
      구분 = from_when)
}


# MP ----------------------------

library(tidyverse)
library(ecos)

USDKRW <- ecos::statSearch(stat_code = "731Y003","0000003",cycle ="D",
                           start_time = "20221004",end_time = "20240112") %>% tibble() %>% 
  select(기준일자=time,`USD/KRW`  = data_value) %>% 
  mutate(기준일자= ymd(기준일자))

KOREA_holidays<- read_csv("00_data/KOREA_holidays.csv", locale = locale(encoding = "CP949"))


MP_LTCMA<- bind_rows(
  read_csv("00_data/rebalancing/rebalancing_20221005.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") ,
  read_csv("00_data/rebalancing/rebalancing_20231129.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") ,
  read_csv("00_data/rebalancing/rebalancing_20231226.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") ,
  read_csv("00_data/rebalancing/rebalancing_20231229.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") 
  
)

MP_LTCMA<- MP_LTCMA %>% 
  left_join(universe_criteria %>% select(종목코드, 자산군_대,자산군_소),by = join_by(ISIN ==종목코드))

data_factset<- read_csv("00_data/data_long.csv")


crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                           end_date = "2024-01-12",
                                           by = "day") ,
         ISIN = unique(data_factset$requestId)) %>% 
  # 고려사항 1. Data source : Factset 데이터 사용.
  left_join(data_factset |> 
              filter(formula =="P_PRICE(10/03/2022,01/12/2024)") |> 
              select(기준일자=result.dates , ISIN = requestId ,PX_LAST = result.values) %>% 
              pivot_wider(id_cols = 기준일자,names_from = ISIN,values_from = PX_LAST) %>% 
              # 고려사항2. 미국은 전일종가 사용
              mutate(across(.cols = starts_with("US") , .fn = ~lag(.x,n=1))) %>% 
              pivot_longer(cols = -기준일자, names_to = "ISIN", values_to = "종가") %>% 
              filter(기준일자>="2022-10-04"),
            by = join_by(기준일자,ISIN)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = ISIN,values_from = 종가) %>% 
  #  고려사항 3. 한국휴일 반영
  mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays$`Holiday Date`,1,0)) %>% 
  mutate(across(.cols = starts_with("US"), .fns = ~if_else(korea_holiday==1, NA, .x) )) %>% 
  select(-korea_holiday) %>% 
  pivot_longer(cols = -기준일자,names_to = "ISIN",values_to = "종가") %>% 
  left_join(USDKRW,by =  join_by(기준일자)) %>% 
  left_join(universe_criteria,by =  join_by(ISIN == 종목코드)) %>% 
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


get_rebalanced_weight<- function(date, fund, weight_table){
  #MP_LTCMA %>% 
  weight_table %>% 
    # 리밸런싱날짜 당일까지는 이전 비중을 통한 수익률 계산 (부등호가 리밸런싱날짜<date인 이유)
    filter(리밸런싱날짜<date,펀드설명 ==fund) |> 
    filter(리밸런싱날짜==last(리밸런싱날짜)) |> 
    select(ISIN,weight,last_rebalance =리밸런싱날짜)
  
}




MP_LTCMA_all_comb<- crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-05",
                                                               end_date = "2024-01-12",
                                                               by = "day"),
                             펀드설명 = unique(MP_LTCMA$펀드설명) ,
                             #펀드설정일 = "??-??-??"
) %>%
  #펀드설정일이 다를 경우, 확장성 고려
  # group_by(펀드설명) |> 
  # filter(기준일자>=펀드설정일) |> 
  # ungroup() |> 
  mutate(temp = map2(.x = 기준일자, .y = 펀드설명, .f =~get_rebalanced_weight(.x,.y,weight_table = MP_LTCMA))) %>%
  unnest(cols = temp) 


MP_LTCMA_all_comb %>% filter(weight>0) %>%
  left_join(MP_performance_preprocessing , by = join_by(기준일자,ISIN)) %>%
  group_by(기준일자,펀드설명) %>% 
  reframe(전일대비등락률 = sum(weight*전일대비등락률),
          last_rebalance = last_rebalance[1]) %>%
  group_by(펀드설명) |> 
  mutate(수정기준가 = 1000*cumprod(전일대비등락률+1)) %>%
  ungroup()%>% select(-c(전일대비등락률,last_rebalance)) %>% 
  left_join(VP_fund_name,by = join_by(펀드설명)) %>% 
  left_join(rf_data_KORIBOR_3_month %>% select(-c(Rf,unit_name)),by = "기준일자") %>% 
  mutate(Rf_Return = zoo::na.locf(Rf_Return))->MP_performance_preprocessing_final



# BM ----------------------------


BM_daily_price<- 
  
  tibble(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                           end_date = "2024-01-12",
                                           by = "day")) %>% 
  left_join(read_csv("00_data/BM_historical_upto_20240112_data.csv", locale = locale(encoding = "CP949")) %>% 
              mutate(across(.cols = c(2,3), .fns = ~lag(.x ,n=1))) %>% 
              filter(date>="2022-10-04" ),
            by = join_by(기준일자==date))# %>% 
#left_join(read_csv("00_data/BM_KIS_historical_upto_20240112_data.csv"),by = join_by(기준일자)) 


KOREA_holidays<- read_csv("00_data/KOREA_holidays.csv", locale = locale(encoding = "CP949"))




BM_daily_price %>% 
  mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays$`Holiday Date`,1,0)) %>% 
  mutate(across(.cols = c(2,3), .fns = ~if_else(korea_holiday==1, NA, .x) )) %>%
  select(-korea_holiday) %>% 
  pivot_longer(cols = -기준일자,names_to = "자산군",values_to = "기준가") %>% 
  group_by(자산군) %>% 
  mutate(기준가 = zoo::na.locf(기준가)) %>% ungroup() %>% 
  #pivot_wider(id_cols = 기준일자,names_from = 자산군,values_from = 기준가) %>% view()
  left_join(USDKRW,by =  join_by(기준일자))  %>% 
  mutate(`USD/KRW` = zoo::na.locf(`USD/KRW`)) %>% 
  mutate(price_KRW = if_else(자산군 %in% c("M2WD Index","LEGATRUU Index"), 기준가*`USD/KRW`,기준가)) %>% 
  group_by(자산군) %>%
  mutate(last_price_KRW = lag(price_KRW,n=1),
         전일대비등락률 = price_KRW/last_price_KRW-1) %>%
  select(기준일자,자산군, 전일대비등락률) %>% 
  filter(기준일자>="2022-10-05") %>% ungroup()  -> BM_performance_preprocessing


#MOS 3420 화면에서 수익률 조회한 것과 일치. 소숫점자리가 달라 누적될수록 기준가는 조금씩 달라짐.
# BM_performance_preprocessing %>% 
#   group_by(자산군) %>% 
#   mutate(dd = lag(수정기준가),
#          일수익률 = (수정기준가/dd-1 )*100) %>% 
#   ungroup() %>% 
#   pivot_wider(id_cols = 기준일자,names_from = 자산군,values_from = 일수익률) %>% 
#   mutate(BM_수익률 = 0.4591*`M2WD Index`+0.5409*`LEGATRUU Index`) %>% view()
# 

BM_weight<- MP_LTCMA %>%
  #left_join(universe_criteria %>% select(종목코드,자산군_대, 자산군_소) %>% distinct(), by = join_by(ISIN==종목코드)) %>%
  mutate(자산군 = if_else(자산군_대 == "대체", "주식", 자산군_대)) %>%
  group_by(리밸런싱날짜,펀드설명, 자산군) %>%
  reframe(weight = round(sum(weight),4) ) %>% 
  mutate(자산군 = case_when(
    자산군 == "주식" ~ "M2WD Index",
    자산군 == "채권" & 펀드설명 %in% c("MS GROWTH", "MS STABLE") ~ "KST0000T Index",#"KIS 종합 총수익지수",
    자산군 == "채권" ~ "LEGATRUU Index",
    TRUE ~ 자산군
  )) %>% 
  rename(ISIN= 자산군)


BM_weight_all_comb<- crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-05",
                                                                end_date = "2024-01-12",
                                                                by = "day"),
                              펀드설명 = unique(BM_weight$펀드설명) ,
                              #펀드설정일 = "??-??-??"
) %>%
  #펀드설정일이 다를 경우, 확장성 고려
  # group_by(펀드설명) |> 
  # filter(기준일자>=펀드설정일) |> 
  # ungroup() |> 
  mutate(temp = map2(.x = 기준일자, .y = 펀드설명, .f =~get_rebalanced_weight(.x,.y,weight_table = BM_weight))) %>%
  unnest(cols = temp) 

BM_weight_all_comb %>% filter(weight>0) %>%
  left_join(BM_performance_preprocessing , by = join_by(기준일자,ISIN==자산군)) %>%
  group_by(기준일자,펀드설명) %>% 
  reframe(전일대비등락률 = sum(weight*전일대비등락률),
          last_rebalance = last_rebalance[1]) %>%
  group_by(펀드설명) |> 
  mutate(수정기준가 = 1000*cumprod(전일대비등락률+1)) %>%
  ungroup()%>% select(-c(전일대비등락률,last_rebalance)) %>% 
  left_join(VP_fund_name,by = join_by(펀드설명)) %>% 
  left_join(rf_data_KORIBOR_3_month %>% select(-c(Rf,unit_name)),by = "기준일자") %>% 
  mutate(Rf_Return = zoo::na.locf(Rf_Return))->BM_performance_preprocessing_final


# 연초대비/설정일이후 수익률  ---------------------------------------------------------



# 최종적으로는 MP, BM각각의 수익률데이터도 오른쪽으로 덧붙인다음 pivot_longer후 시각화
AP_performance_shallow<- AP_performance_preprocessing %>% 
  return_performance_shallow(input_date = "2023-09-12",from_when = "YTD") 

AP_performance_deep<- AP_performance_shallow %>% 
  return_performance_deep(input_date = "2023-09-12",from_when = "YTD") 

VP_performance_shallow<- VP_performance_preprocessing %>% 
  return_performance_shallow(input_date = "2023-09-12",from_when = "YTD") 

VP_performance_deep<- VP_performance_shallow %>% 
  return_performance_deep(input_date = "2023-09-12",from_when = "YTD") 

MP_performance_shallow<- MP_performance_preprocessing_final %>% 
  return_performance_shallow(input_date = "2023-09-12",from_when = "YTD") 

MP_performance_deep <- MP_performance_shallow %>% 
  return_performance_deep(input_date = "2023-09-12",from_when = "YTD") 

BM_performance_shallow <- BM_performance_preprocessing_final %>% 
  return_performance_shallow(input_date = "2023-09-12",from_when = "YTD") 

BM_performance_deep <- BM_performance_shallow %>% 
  return_performance_deep(input_date = "2023-09-12",from_when = "YTD") 



results_except_TE<- bind_rows(
  AP_performance_deep %>% mutate(구분="AP"),
  VP_performance_deep %>% mutate(구분="VP"),
  MP_performance_deep %>% mutate(구분="MP"),
  BM_performance_deep %>% mutate(구분="BM")
)



Return_results<- results_except_TE %>% 
  select(펀드설명, 기준일자, Return,구분) %>% 
  filter(!is.na(Return)) %>% 
  pivot_wider(
    names_from = 구분, 
    values_from = Return,
    values_fill = list(Return = NA) # 주별수익률 값이 없는 경우 NA로 채움
  ) %>%  
  mutate(`(AP-VP)` = AP-VP,
         `(VP-BM)` = VP-BM,
         `(AP-BM)` = AP-BM) %>% 
  pivot_longer(cols = -c(펀드설명,기준일자),
               names_to = "구분", values_to = "Return")

Return_results %>% 
  filter(!(구분 %in% c("AP", "VP", "MP", "BM"))) %>% 
  ggplot(aes(x=펀드설명,y=Return,fill = 구분))+
  geom_bar(stat = "identity", width = 0.75, position = "dodge") 

#######################################################################
#######################################################################

# 추적오차 ----------------------------------------------------------------
results_TE<- 
  results_except_TE %>% 
  left_join(
    
    bind_rows(
      AP_performance_shallow %>% mutate(구분="AP"),
      VP_performance_shallow %>% mutate(구분="VP"),
      MP_performance_shallow %>% mutate(구분="MP"),
      BM_performance_shallow %>% mutate(구분="BM")
    ) %>% 
      select(펀드설명, 기준일자, 주별수익률,구분) %>% 
      filter(!is.na(주별수익률)) %>% 
      pivot_wider(
        names_from = 구분, 
        values_from = 주별수익률,
        values_fill = list(주별수익률 = NA) # 주별수익률 값이 없는 경우 NA로 채움
      ) %>%  
      mutate(`(AP-BM)` = AP-BM,
             `(VP-BM)` = VP-BM) %>% 
      group_by(펀드설명) %>% 
      summarise(AP = sd(`(AP-BM)`)*sqrt(52),
                VP = sd(`(VP-BM)`)*sqrt(52)) %>% 
      pivot_longer(cols = -펀드설명,names_to = "구분",values_to = "Tracking_error" ),
    
    by = join_by(펀드설명,구분)
  ) %>% filter(구분 %in%c("AP","VP","BM")) %>% 
  select(펀드설명,기준일자, Return_annualized,Tracking_error,구분) %>% 
  pivot_wider(id_cols = c(펀드설명,기준일자),names_from = 구분,values_from = c(Return_annualized,Tracking_error) ) %>% 
  mutate(IR_AP=  (Return_annualized_AP-Return_annualized_BM)/Tracking_error_AP,
         IR_VP=  (Return_annualized_VP-Return_annualized_BM)/Tracking_error_VP,
         ) %>% 
  select(펀드설명,기준일자,IR_AP,IR_VP,Tracking_error_AP,Tracking_error_VP) %>% 
    # pivot_longer를 사용한 데이터 변환
  pivot_longer(
    cols = starts_with("IR_") | starts_with("Tracking_error_"),
    names_to = c("Metric", "구분"),
    names_pattern = "(.+)_(.+)", # 첫 번째 그룹과 두 번째 그룹으로 나눔
    values_to = "value"
  ) 

results_TE

# 계산된 _performance에서 참고할 열 선택해서 그래프 그리기 

AP_performance_deep %>% 
  select(펀드설명,기준일자,구분,Return_AP=Return)->a1
VP_performance_deep %>% 
  select(펀드설명,기준일자,구분,Return_VP=Return)->a2
MP_performance_deep %>% 
  select(펀드설명,기준일자,구분,Return_MP=Return)->a3
BM_performance_deep %>% 
  select(펀드설명,기준일자,구분,Return_BM=Return)->a4
a1 %>%
  left_join(a2,by = join_by(펀드설명, 기준일자, 구분)) %>% 
  left_join(a3,by = join_by(펀드설명, 기준일자, 구분)) %>% 
  left_join(a4,by = join_by(펀드설명, 기준일자, 구분)) %>% 
  mutate(Return_AP_VP = Return_AP-Return_VP,
         Return_VP_BM = Return_VP-Return_BM,
         Return_AP_BM = Return_AP-Return_BM
  ) %>% 
  pivot_longer(cols =contains("Return_"),names_to = "Portfolio" ) %>% view()



# # historical performance
# crossing(
#   기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-07",end_date = "2023-12-01",by = "day"),
#   구분 = c("YTD","ITD")
#     ) %>%
#   mutate(test = map2(.x = 기준일자,
#                      .y = 구분 ,
#                      .f= ~return_performance(AP_performance_preprocessing,
#                                              input_date = .x,
#                                              from_when = .y ))) %>%
#   select(test) %>%
#   unnest(cols = c(test))->historical_performance

#
# historical_performance %>% view()
# 
# historical_performance %>% 
#   filter(구분=="ITD") %>% view()



# 시각화 ---------------------------------------------------------------------

AP_performance_preprocessing %>% 
  return_performance(input_date = "2023-09-12",from_when = "YTD")

VP_performance_preprocessing %>% 
  return_performance(input_date = "2023-09-12",from_when = "YTD") 


MP_performance_preprocessing_final

bind_rows(
  AP_performance_preprocessing %>% mutate(Portfolio = "AP"),
  VP_performance_preprocessing %>% mutate(Portfolio = "VP"),
  #MP_performance_preprocessing,
  #BM_performance_preprocessing
) %>% 
  filter(!is.na(펀드설명)) %>%
  select(-c(펀드명,unit_name,Rf_Return,Rf)) %>% # 22-10-04 에 1000원 삽입하여 1000원부터 같이 시작할 수 있게 그림 
  group_by(펀드) %>% 
  mutate(base = 1000,
         수정기준가=수정기준가/base*1000) %>% 
  filter(row_number()>=3) %>%
  ungroup() %>% 
  ggplot(aes(x=기준일자,y=수정기준가,color = Portfolio))+
  geom_line()+
  facet_wrap(~펀드설명)




