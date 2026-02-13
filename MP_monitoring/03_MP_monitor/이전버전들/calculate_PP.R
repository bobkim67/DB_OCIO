library(tidyverse)
library(shiny)
library(plotly)
library(scales)
library(ecos)
library(rlang) # sym() 함수를 사용하기 위해 필요


universe_criteria <- read_csv("00_data/universe_criteria.csv", locale = locale(encoding = "CP949")) |> 
  distinct() %>% 
  # 23년 말 기준으로 새롭게 편입된 US 금 두 종목 존재. universe DB에 업데이트
  bind_rows(
    tribble( ~종목코드, ~종목명,~자산군_대,~자산군_중,~자산군_소,
             "US98149E3036", "SPDR GOLD MINISHARES TRUST" , "대체","원자재","금",  
             "US46436F1030", "ISHARES GOLD TRUST MICRO"   , "대체","원자재","금"
    )
  )

KOREA_holidays<- 
  tibble( `Holiday Date` = ymd(c("2022-10-03","2022-10-10","2022-12-30","2023-01-23","2023-01-24","2023-03-01",
                                                "2023-05-01","2023-05-05","2023-05-29","2023-06-06","2023-08-15","2023-09-28",
                                                "2023-09-29","2023-10-02","2023-10-03","2023-10-09","2023-12-25","2023-12-29",
                                                "2024-01-01","2024-02-09","2024-02-12","2024-03-01","2024-04-10","2024-05-01",
                                                "2024-05-06","2024-05-15","2024-06-06","2024-08-15","2024-09-16","2024-09-17",
                                                "2024-09-18","2024-10-03","2024-10-09","2024-12-25","2024-12-31")))

AP_fund_name<- tibble(
  펀드 = c("07M02",	"07J66",	"07J71",	"07J76",	"07J81",	"07J86",	"07J91",	"07J96",	"07J41",	"07J34"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"MS STABLE",	"MS GROWTH"))


VP_fund_name<- tibble(
  펀드 = c("2MP24",	"1MP30",	"1MP35",	"1MP40",	"1MP45",	"1MP50",	"1MP55",	"1MP60",	"3MP01",	"3MP02"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"MS STABLE",	"MS GROWTH"))

# Performance -------------------------------------------------------------


# rf_data_KORIBOR_3_month<- ecos::statSearch(stat_code = "817Y002","010150000",cycle ="D",
#                                            start_time = "20221005",end_time = "20231201") %>% tibble() %>% 
#   select(Rf = item_name1,unit_name,기준일자=time,Rf_Return = data_value) %>% 
#   mutate(기준일자= ymd(기준일자))


# _AP, VP ------------------------------------------------------------------


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

# Assign the new column names
colnames(AP_historical_price) <- column_names_AP_VP_historical_price
colnames(VP_historical_price) <- column_names_AP_VP_historical_price


AP_performance_preprocessing <- AP_historical_price %>% 
  select(기준일자 = 산출일자,펀드=`펀드코드`,펀드명,수정기준가) %>% 
  left_join(AP_fund_name)# %>% 
  #left_join(rf_data_KORIBOR_3_month,by = "기준일자") %>% 
  #mutate(Rf_Return = zoo::na.locf(Rf_Return))

VP_performance_preprocessing <- VP_historical_price %>% 
  select(기준일자 = 산출일자,펀드=`펀드코드`,펀드명,수정기준가) %>% 
  left_join(VP_fund_name) #%>% 
  #left_join(rf_data_KORIBOR_3_month,by = "기준일자") %>% 
  #mutate(Rf_Return = zoo::na.locf(Rf_Return))





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


# _MP ----------------------------

library(tidyverse)
library(ecos)

USDKRW <- ecos::statSearch(stat_code = "731Y003","0000003",cycle ="D",
                           start_time = "20221004",end_time = "20240314") %>% tibble() %>% 
  select(기준일자=time,`USD/KRW`  = data_value) %>% 
  mutate(기준일자= ymd(기준일자))



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


data_factset<- read_csv("00_data/data_upto_20240314.csv")


crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                           end_date = "2024-03-14",
                                           by = "day") ,
         ISIN = unique(data_factset$requestId)) %>% 
  # 고려사항 1. Data source : Factset 데이터 사용.
  left_join(data_factset |> 
              filter(formula =="P_PRICE(10/03/2022,03/14/2024)") |> 
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
                                                               end_date = "2024-03-14",
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
  left_join(VP_fund_name,by = join_by(펀드설명)) ->MP_performance_preprocessing_final
  #left_join(rf_data_KORIBOR_3_month %>% select(-c(Rf,unit_name)),by = "기준일자") %>% 
  #mutate(Rf_Return = zoo::na.locf(Rf_Return))->MP_performance_preprocessing_final



# _BM ----------------------------


BM_daily_price<- 
  
  tibble(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                           end_date = "2024-03-14",
                                           by = "day")) %>% 
  left_join(read_csv("00_data/BM_historical_upto_20240314_data.csv", locale = locale(encoding = "CP949")) %>% 
              mutate(across(.cols = c(2,3), .fns = ~lag(.x ,n=1))) %>% 
              filter(date>="2022-10-04" ),
            by = join_by(기준일자==date))# %>% 
#left_join(read_csv("00_data/BM_KIS_historical_upto_20240112_data.csv"),by = join_by(기준일자)) 




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
                                                                end_date = "2024-03-14",
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
  left_join(VP_fund_name,by = join_by(펀드설명)) ->BM_performance_preprocessing_final 
  #left_join(rf_data_KORIBOR_3_month %>% select(-c(Rf,unit_name)),by = "기준일자") %>% 
  #mutate(Rf_Return = zoo::na.locf(Rf_Return))->BM_performance_preprocessing_final




# Position ----------------------------------------------------------------


# 데이터 불러오기
AP_total <- 
  bind_rows(
    readxl::read_excel("00_data/통합 명세_AP.xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)),
    readxl::read_excel("00_data/통합 명세_AP_(20231202_20240109).xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)) %>% 
      filter(기준일자<="2024-01-09")
  ) %>% 
  select(기준일자,펀드,종목,종목명,시가평가액,순자산)

VP_total <- 
  bind_rows(
    readxl::read_excel("00_data/통합 명세_VP.xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)),
    readxl::read_excel("00_data/통합 명세_VP_(20231202_20240109).xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)) %>% 
      filter(기준일자<="2024-01-09")
  ) %>% 
  select(기준일자,펀드,종목,종목명,시가평가액,순자산)

asset_classification_and_adjust <- function(data){
  # 조인 조건 정의
  join_condition <- join_by(종목 == 종목코드, 종목명)
  
  # 조인 수행
  data_joined <- data %>% 
    left_join(universe_criteria, by = join_condition) 
  
  return(data_joined)
  # data_asset_adjust<- data_joined %>% 
  #   mutate(자산군_중 = if_else(자산군_대=="대체","대체",자산군_중)) %>% 
  #   mutate(자산군_소 = if_else(자산군_대=="대체","대체",자산군_소))
  
  #return(data_asset_adjust)
}


AP_asset_adjust<- asset_classification_and_adjust(AP_total) 
VP_asset_adjust<- asset_classification_and_adjust(VP_total)



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
    
    
    master_fund %>% inner_join(feeder_fund,relationship = "many-to-many") %>% 
      mutate(daily_weight = ratio_07J48*`07J48`+ratio_07J49*`07J49`) %>% 
      select(기준일자,펀드,!!sym(asset_group),daily_weight)->mysuper_position
    
    # 최종 포트폴리오 가중치 데이터 프레임 생성
    
    daily_weights %>% 
      filter(!(펀드 %in% c("07J34","07J41","07J48","07J49"))) %>% 
      bind_rows(mysuper_position)  ->final_weights
    
    return(final_weights)
  }
  
  
}


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
    mutate(text_label = ifelse(Metric %in% c("Sharpe_ratio","risk_adjusted_Return"),
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
#     mutate(text_label = ifelse(Metric %in% c("Sharpe_ratio","risk_adjusted_Return"),
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




