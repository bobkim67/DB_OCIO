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
library(RColorBrewer)
library(jsonlite)
ecos.setKey("FWC2IZWA5YD459SQ7RJM")


con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')
con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
con_cream <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'cream', host = '192.168.195.55')




tbl(con_dt,"DWCI10220") %>% 
  select(기준일자 = std_dt,요일코드 = day_ds_cd,hldy_yn,hldy_nm,월말일여부=mm_lsdd_yn,전영업일=pdd_sals_dt,다음영업일 =nxt_sals_dt) %>% 
  filter( 기준일자>="20000101") %>% 
  collect() %>% 
  mutate(기준일자 = ymd(기준일자))->holiday_calendar


holiday_calendar %>% 
  filter(hldy_yn=="N") %>% 
  group_by(year(기준일자),month(기준일자)) %>% 
  filter(row_number()==max(row_number())) %>% pull(기준일자)->연월별마지막영업일

holiday_calendar %>% 
  filter(hldy_yn=="N") %>% pull(기준일자) -> selectable_dates
holiday_calendar %>% 
  filter(hldy_yn=="Y") %>% pull(기준일자) -> diabaled_dates

holiday_calendar %>% 
  filter(기준일자<today()) %>% 
  filter(hldy_yn=="N") %>% pull(기준일자) %>% max()->최근영업일


holiday_calendar %>% 
  filter(hldy_yn=="Y" &!(요일코드 %in% c("1","7"))) %>% 
  #filter(hldy_yn=="Y") %>% 
  pull(기준일자)->KOREA_holidays

# Source_ECOS ---------------------------------------------------------------
# 

기준금리        <- return_rf_index("0101000")
콜금리          <- return_rf_index("010101000")
`KOFR(공시RFR)` <- return_rf_index("010901000")
`KORIBOR(3개월)`<- return_rf_index("010150000")
`CD(91일)`      <- return_rf_index("010502000")
`CP(91일)`      <- return_rf_index("010503000")
`통안증권(91일)`<- return_rf_index("010400000")

bind_rows(
  기준금리,
  콜금리,
  `KOFR(공시RFR)`,
  `KORIBOR(3개월)`,
  `CD(91일)`,
  `CP(91일)`,
  `통안증권(91일)`
)-> ECOS_historical_price

ECOS_historical_price %>% 
  bind_rows(
    ECOS_historical_price %>% 
      group_by(dataset_id,dataseries_id) %>% 
      reframe(기준일자 = min(ymd(기준일자))-days(1),
              기준가_custom = 1000)
  ) %>% 
  bind_rows(
    ECOS_historical_price %>% 
      group_by(dataset_id,dataseries_id) %>% 
      reframe(기준일자 = today()-days(1))
  ) %>%
  group_by(기준일자,dataset_id,dataseries_id) %>%
  filter(row_number()==1) %>%
  ungroup() %>% 
  group_by(dataset_id,dataseries_id) %>% 
  timetk::pad_by_time(.date_var = 기준일자,.by = "day", .fill_na_direction = "down") %>%
  arrange(dataset_id,기준일자) ->ECOS_historical_price


ECOS_historical_price %>%
  filter(dataset_id %in% c("한국은행기준금리","콜금리","KOFR(공시RFR)",
                           "KORIBOR(3개월)","CD(91일)","CP(91일)","통안증권(91일)") ) %>%
  group_by(dataset_id,요일=wday(기준일자,label=TRUE)) %>%
  rename(기준가=기준가_custom) %>%
  mutate(lagged_기준가 = lag(기준가,n=1)) %>%
  ungroup() %>%
  mutate(주간수익률 = if_else(is.na(lagged_기준가),
                         기준가/1000-1,
                         기준가/lagged_기준가-1),
         주간로그수익률 = if_else(is.na(lagged_기준가),
                           log(기준가/1000),
                           log(기준가/lagged_기준가)),
  )-> ECOS_historical_주간수익률

ECOS_historical_price %>%
  mutate(name = dataset_id,
         dataseries_name = "Custom_index(일단위YTM 365일기준 복리)",
         source = "ECOS",
         region = "KR") %>%
  select(dataset_id,name,dataseries_id,dataseries_name,source,region) %>%
  distinct()->data_information_ECOS

# ECOS_historical_price <- NULL
# data_information_ECOS <- NULL
# ECOS_historical_주간수익률 <- NULL
# Source_SCIP -------------------------------------------------------------


tbl(con_SCIP,"back_dataset") %>%
  filter(id %in% local(tbl(con_SCIP,"back_datapoint") %>%
                         #filter(dataset_id %in% local(Data_List$id)) %>% 
                         select(dataset_id,dataseries_id) %>% distinct() %>% 
                         filter(dataseries_id %in% c(6,9,15,33,45,48)) %>% pull(dataset_id)) ) %>% 
  collect() %>% 
  mutate(id= as.character(id))  ->Data_List



tbl(con_SCIP,"back_datapoint") %>%
  select(dataset_id,dataseries_id) %>% 
  filter(dataseries_id %in% c(6,9,15,33,45,48)) %>% distinct() %>% 
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
                            str_detect(name,"KIS|KOSPI|Korea|[가-힣]") ~ "KR",
                            TRUE ~ "ex_KR"
  ))-> data_information_SCIP




# Source_BOS --------------------------------------------------------------




tbl(con_dt,"DWPI10011") %>%
  filter(IMC_CD == "003228") %>% 
  filter(DEPT_CD %in% c('166','061','064')) %>% 
  select(dataset_id=FUND_CD,name=FUND_WHL_NM,DEPT_CD) %>% collect() %>% 
  mutate(dataseries_id = "MOD_STPR",
         dataseries_name = "수정기준가",
         source = "BOS",
         region = "KR") ->data_information_BOS

BOS_historical_price <-data_information_BOS %>% select(dataset_id,dataseries_id,DEPT_CD) %>% 
  inner_join(tbl(con_dt,"DWPM10510") %>% 
               select(STD_DT,dataset_id=FUND_CD,MOD_STPR),
             copy = TRUE
  ) %>% collect() %>% 
  mutate(MOD_STPR = if_else(DEPT_CD == c("064"), MOD_STPR/10,MOD_STPR)) %>% #ETF운용부껀 수정기준가 10000원이어서 나누기 10 처리.
  select(-DEPT_CD)

BOS_historical_price<- BOS_historical_price %>% 
  bind_rows(
    BOS_historical_price %>% 
      group_by(dataset_id,dataseries_id) %>% 
      reframe(STD_DT = str_remove_all(min(ymd(STD_DT))-days(1),"-"),
              MOD_STPR = 1000)
  ) %>% 
  arrange(dataset_id,STD_DT)


data_information_BOS<- data_information_BOS %>% 
  select(-DEPT_CD)

# Source_ZEROIN -----------------------------------------------------------


ZEROIN_data <- tbl(con_cream,"data") %>% 
  left_join(tbl(con_cream,"fundlist")) %>% 
  collect()

ZEROIN_historical_price<- bind_rows(
  
  ZEROIN_data  %>% 
    arrange(date) %>% 
    group_by(fundCode) %>% 
    reframe(date = min(ymd(date))-days(1),
            price = 1000), # 첫영업일에 1000이 기본적으로 쌓여있었다가 lead함수로 제거됐는데 이를 보완하기 위함
  
  ZEROIN_data %>%
    arrange(date) %>% 
    select(date,fundCode,price)  %>% 
    group_by(fundCode) %>% 
    mutate(price = lead(price,n=1)) %>%  # 1영업일 씩 앞당기기
    filter(!is.na(price)) %>% 
    ungroup() 
) %>% 
  rename(dataset_id = fundCode, 기준일자 =date, SUIK_JISU= price) %>% 
  mutate(dataseries_id = "SUIK_JISU")


ZEROIN_data %>% 
  group_by(fundCode) %>% 
  filter(date == max(date)) %>% 
  select(dataset_id=fundCode,name=fundName)  %>% 
  ungroup() %>% 
  mutate(dataseries_id = "SUIK_JISU",
         dataseries_name = "수정기준가",
         source = "ZEROIN",
         region = "KR") -> data_information_ZEROIN


# Source_RATB -------------------------------------------------------------

tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id==62) %>% collect() %>% 
  mutate(data = map(.x= data, .f = ~jsonlite::parse_json(gsub("NaN", "null", (rawToChar(unlist(.x))))))) -> robo_peer


robo_peer %>%
  mutate(
    standardPrice = map_dbl(.x = data, .f = ~ ifelse(!is.null(.x$standardPrice), .x$standardPrice, NA_real_), .progress = TRUE),
    algo = map_chr(.x = data, .f = ~ ifelse(!is.null(.x$algo), .x$algo, NA_character_), .progress = TRUE),
    company = map_chr(.x = data, .f = ~ ifelse(!is.null(.x$company), .x$company, NA_character_), .progress = TRUE),
    initialCap = map_chr(.x = data, .f = ~ ifelse(!is.null(.x$initialCap), .x$initialCap, NA_character_), .progress = TRUE),
    risk = map_chr(.x = data, .f = ~ ifelse(!is.null(.x$risk), .x$risk, NA_character_), .progress = TRUE)
  ) %>%
  mutate(date = ymd(timestamp_observation)) %>%
  arrange(date) %>%
  select(-contains("id"), -contains("time"), -data, -contains("datas")) %>% 
  mutate(fundCode = paste0(company,"_",algo,"_",risk) )-> robo_preprocessing


RATB_historical_price<- bind_rows(
  
  robo_preprocessing  %>% 
    arrange(date) %>% 
    group_by(fundCode) %>% 
    reframe(date = min(ymd(date))-days(1),
            standardPrice  = 1000), # 첫영업일에 1000이 기본적으로 쌓여있었다가 lead함수로 제거됐는데 이를 보완하기 위함
  
  robo_preprocessing %>%
    arrange(date) %>% 
    select(date,fundCode,standardPrice )  %>% 
    group_by(fundCode) %>% 
    mutate(standardPrice  = lead(standardPrice ,n=1)) %>%  # 1영업일 씩 앞당기기
    filter(!is.na(standardPrice )) %>% 
    ungroup() 
) %>% 
  rename(dataset_id = fundCode, 기준일자 =date) %>% 
  mutate(dataseries_id = "standardPrice")


robo_preprocessing %>% 
  group_by(fundCode) %>% 
  filter(date == max(date)) %>% filter(!is.na(risk)) %>% 
  select(dataset_id=fundCode,name=fundCode)  %>% 
  ungroup() %>% 
  mutate(dataseries_id = "standardPrice",
         dataseries_name = "수정기준가",
         source = "RATB",
         region = "KR") -> data_information_RATB


# Source_Custom -----------------------------------------------------------

timetk::tk_make_timeseries(start_date = ymd("1950-01-01"),end_date = 최근영업일,by = "day") %>% 
  enframe(name = NULL,value = "기준일자") %>% 
  mutate( 기준가_custom= 1000,
          dataset_id = "현금(금리X)",
          dataseries_id = "Custom_index")->CUSTOM_historical_price

#2025년 7월 31일꺼까지 있음. 
# bind_rows(read_rds("4JM12_KBP동부생명.rds"),
#           clipr::read_clip_tbl() %>% tibble()) %>% 
#   distinct() %>%  saveRDS("4JM12_KBP동부생명.rds")
read_rds("4JM12_KBP동부생명.rds") %>%
  mutate(기준일자 = ymd(일자)) %>%
  mutate(daily_return = KBP.동부생명7/lag(KBP.동부생명7)-1) %>%
  mutate(daily_return = if_else(is.na(daily_return),0,daily_return)) %>%
  mutate(기준가_custom = cumprod(1+daily_return)*1000) %>%
  mutate(dataset_id = "KBP-동부생명7",
         dataseries_id = "Custom_index") %>%
  select(-c(일자,KBP.동부생명7,daily_return)) -> 동부생명7

CUSTOM_historical_price <- bind_rows(CUSTOM_historical_price,동부생명7)

CUSTOM_historical_price %>% 
  mutate(name = dataset_id,
         dataseries_name = dataset_id,
         source = "Custom",
         region = "KR") %>% 
  select(dataset_id,name,dataseries_id,dataseries_name,source,region) %>% 
  distinct()->data_information_CUSTOM

# 결합 ----------------------------------------------------------------------

data_information<- bind_rows(data_information_SCIP,
                             data_information_BOS,
                             data_information_ECOS,
                             data_information_ZEROIN,
                             data_information_RATB,
                             data_information_CUSTOM) %>% 
  mutate(colname_backtest = if_else(is.na(ISIN), name,symbol)) %>% 
  mutate(colname_backtest = if_else(grepl("^[0-9]+$", colname_backtest), name, colname_backtest)) 


pulled_data_universe_SCIP <- data_information %>% select(dataset_id,dataseries_id) %>% 
  inner_join(tbl(con_SCIP,"back_datapoint") %>%
               select(timestamp_observation,data,dataset_id,dataseries_id) %>% distinct() %>% 
               mutate(dataset_id =as.character(dataset_id),
                      dataseries_id =as.character(dataseries_id)),
             copy = TRUE,
             by = join_by(dataset_id,dataseries_id))




bind_rows(
  pulled_data_universe_SCIP %>% 
    group_by(dataset_id,dataseries_id) %>% 
    reframe(분석시작가능일 = ymd(nth(sort(timestamp_observation), 2, default = NA))),
  #reframe(분석시작가능일=ymd(min(timestamp_observation)))  -- 가격데이터밖에 없어서 첫날 수익률 계산 못함.,
  BOS_historical_price %>% 
    group_by(dataset_id,dataseries_id) %>% 
    reframe(분석시작가능일 = ymd(nth(sort(STD_DT), 2, default = NA))),
  ZEROIN_historical_price %>% 
    group_by(dataset_id,dataseries_id) %>% 
    reframe(분석시작가능일 = ymd(nth(sort(기준일자), 2, default = NA))),
  ECOS_historical_price %>% 
    group_by(dataset_id,dataseries_id) %>% 
    reframe(분석시작가능일 = ymd(nth(sort(기준일자), 2, default = NA))),
  RATB_historical_price %>% 
    group_by(dataset_id,dataseries_id) %>% 
    reframe(분석시작가능일 = ymd(nth(sort(기준일자), 2, default = NA))),
  CUSTOM_historical_price %>% 
    group_by(dataset_id,dataseries_id) %>% 
    reframe(분석시작가능일 = ymd(nth(sort(기준일자), 2, default = NA)))
  
)-> 분석시작가능일_inform



holiday_calendar %>% 
  filter(hldy_yn=="N") %>% pull(기준일자)->영업일

data_information <-
  data_information %>% 
  left_join(분석시작가능일_inform, by = c("dataset_id", "dataseries_id")) %>%
  filter(!is.na(분석시작가능일)) %>% 
  group_by(dataset_id,dataseries_id) %>% 
  mutate(분석시작가능일 = if_else(region[1] != "KR", T1_date_calc(분석시작가능일[1]),분석시작가능일[1] )) %>% ungroup() %>% 
  rowwise() %>%
  mutate(분석시작가능일 = {
    # 1. NA인 경우를 먼저 처리
    if (is.na(분석시작가능일)) {
      NA_Date_ # 날짜 타입의 NA
    } else if(분석시작가능일 %in% KOREA_holidays){
      
      # 2. 다음 영업일의 인덱스를 찾음
      idx <- which.max(T1_date_calc(ymd(분석시작가능일)) < 영업일)
      
      # 3. 인덱스를 찾았는지(길이가 0이 아닌지) 확인
      if (length(idx) > 0 && idx > 0) { # idx > 0 조건도 추가하면 더 안전
        영업일[idx]
      } else {
        # 못 찾았을 경우 (마지막 영업일보다 크거나 같은 날짜) NA 처리
        NA_Date_
      }
      
      
    } else{
      분석시작가능일
    }
  }) %>%
  ungroup() 

# 
# 

USDKRW <- tbl(con_dt,"DWCI10260") %>% 
  select(STD_DT,CURR_DS_CD,TR_STD_RT) %>% 
  filter( STD_DT>="20110101",CURR_DS_CD %in% c('USD')) %>%
  rename(기준일자=STD_DT) %>%
  collect() %>% 
  mutate(기준일자= ymd(기준일자)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = CURR_DS_CD,values_from = TR_STD_RT) %>% 
  select(기준일자, `USD/KRW`=USD)
# # ECOS 데이터의 날짜가 더 길다.
USDKRW <- ecos::statSearch(stat_code = "731Y003","0000003",cycle ="D",
                           start_time = "19000101",
                           end_time =최근영업일 %>% str_remove_all("-") ) %>% tibble() %>%
  select(기준일자=time,`USD/KRW`  = data_value) %>%
  mutate(기준일자= ymd(기준일자)) %>% tail()
  # 연말은 ECOS에서 불러오지 않음. 따라서 12-31일 값을 임의로 채워야됨. 하지만 보통 영업일일수있기때문에 아래와 같이 처리
  bind_rows(tibble(기준일자=today()-days(1),`USD/KRW`=NA)) %>% 
  timetk::pad_by_time(.date_var = 기준일자,.by = "day",.fill_na_direction = "down") %>% 
  group_by(기준일자) %>% 
  filter(row_number()==1) %>% 
  ungroup()


F_USDKRW_Index <- pulled_data_universe_SCIP %>%
  filter(dataset_id == 382, dataseries_id == 9) %>% 
  mutate(기준일자 = ymd(timestamp_observation)) %>%
  arrange(기준일자) %>%
  mutate(data = map_dbl(data, ~as.numeric(rawToChar(unlist(.x))))) %>%
  bind_rows(tibble(기준일자 = 최근영업일)) %>%
  group_by(기준일자) %>%
  filter(row_number()==1) %>%
  ungroup() %>% 
  select(기준일자, `F_USD/KRW`=data) %>% 
  timetk::pad_by_time(.date_var = 기준일자,.by = "day",.fill_na_direction = "down")

