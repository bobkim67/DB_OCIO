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

AP_performance_preprocessing<- table_8183 %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  mutate(MOD_STPR = as.double(MOD_STPR)) %>% 
  rename(기준일자=STD_DT,`펀드`= FUND_CD, 펀드명 = FUND_NM ,수정기준가=MOD_STPR) %>% 
  left_join(AP_fund_name,by = join_by(펀드)) %>% 
  filter(IMC_CD=="003228") %>% 
  select(-IMC_CD) 

VP_performance_preprocessing <-MP_VP_BM_results_core %>% 
  arrange(기준일자) %>% 
  filter(port =="MP") %>% 
  group_by(펀드설명) %>% 
  mutate(수정기준가 = cumprod(1+weighted_sum_drift)*1000 ) %>% 
  ungroup() %>% 
  select(기준일자,펀드=펀드설명,펀드명=펀드설명, 수정기준가,펀드설명=펀드설명) %>%  
  left_join(VP_fund_name %>% select(펀드설명,설정일), by = join_by(펀드설명))

# _MP ----------------------------


MP_performance_preprocessing_final <-MP_VP_BM_results_core %>% 
  arrange(기준일자) %>% 
  filter(port =="MP") %>% 
  group_by(펀드설명) %>% 
  mutate(수정기준가 = cumprod(1+weighted_sum_fixed)*1000 ) %>% 
  ungroup() %>% 
  select(기준일자,펀드=펀드설명,펀드명=펀드설명, 수정기준가,펀드설명=펀드설명) %>%  
  left_join(AP_fund_name %>% select(펀드설명,설정일), by = join_by(펀드설명)) 


# _BM ----------------------------

BM_performance_preprocessing_final <-MP_VP_BM_results_core %>% 
  arrange(기준일자) %>% 
  filter(port =="BM") %>% 
  group_by(펀드설명) %>% 
  mutate(수정기준가 = cumprod(1+weighted_sum_fixed)*1000 ) %>% 
  ungroup() %>% 
  select(기준일자,펀드=펀드설명,펀드명=펀드설명, 수정기준가,펀드설명=펀드설명) %>%  
  left_join(AP_fund_name %>% select(펀드설명,설정일), by = join_by(펀드설명)) 

# Position ----------------------------------------------------------------

# 데이터 불러오기
AP_total <- table_8004 %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  filter(IMC_CD=="003228") %>% 
  select(-IMC_CD) %>% 
  rename(기준일자=STD_DT,펀드 = FUND_CD,종목=ITEM_CD,종목명=ITEM_NM,시가평가액 = EVL_AMT,순자산=NAST_AMT) %>% 
  mutate(across(.cols = c(시가평가액,순자산),.fns = ~as.double(.x)))


# VP_total <- table_8004 %>% tibble() %>% 
#   mutate(STD_DT = ymd(STD_DT)) %>% 
#   arrange(STD_DT) %>% 
#   filter(IMC_CD=="M03228") %>% 
#   select(-IMC_CD) %>% 
#   rename(기준일자=STD_DT,펀드 = FUND_CD,종목=ITEM_CD,종목명=ITEM_NM,시가평가액 = EVL_AMT,순자산=NAST_AMT) %>% 
#   mutate(across(.cols = c(시가평가액,순자산),.fns = ~as.double(.x)))

AP_asset_adjust<- asset_classification_and_adjust(AP_total) %>% 
  mutate(
    자산군_대 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "유동성", 자산군_대),
    자산군_중 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "원화 유동성", 자산군_중),
    자산군_소 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), factor("원화 유동성"), 자산군_소)
  )



# 복제율 ----
#replicate_disparate_rate <- reactive({


# AP와 VP의 포지션 데이터 계산을 위한 reactive 표현식
position_AP_summarised <- 
  calculate_portfolio_weights(
    data = AP_asset_adjust,
    asset_group = "자산군_소",
    division = "AP"
  ) %>% 
  left_join(universe_criteria %>% select(자산군_대,자산군_소) %>% distinct()) %>% 
  left_join(AP_fund_name %>% select(-설정일)) %>% 
  mutate(구분 = "AP") %>% 
  select(-펀드) %>% 
  select(기준일자,펀드=펀드설명,자산군_소,daily_weight, 자산군_대 ,구분)


position_VP_summarised <-
  
  MP_VP_BM_results_core %>%
  filter(port == "MP") %>%
  select(펀드설명,기준일자,`Weight_drift(T)`) %>%
  unnest_wider(`Weight_drift(T)`) %>%
  pivot_longer(cols = -c(펀드설명,기준일자),names_to = "symbol" ,values_to = "weight",values_drop_na = TRUE) %>%
  left_join(MP_VP_BM_results_descriptrion %>%
              select(종목=ISIN,symbol)%>% distinct()) %>%
  asset_classification_and_adjust() %>%
  select(기준일자,펀드=펀드설명,자산군_소,daily_weight = weight) %>% 
  left_join(universe_criteria %>% select(자산군_대,자산군_소) %>% distinct()) %>% 
  mutate(구분 = "VP")


position_MP_summarised<- MP_VP_BM_results_core %>%
  filter(port == "MP") %>%
  select(펀드설명,기준일자,`Weight_fixed(T)`) %>%
  unnest_wider(`Weight_fixed(T)`) %>%
  pivot_longer(cols = -c(펀드설명,기준일자),names_to = "symbol" ,values_to = "weight",values_drop_na = TRUE) %>%
  left_join(MP_VP_BM_results_descriptrion %>%
              select(종목=ISIN,symbol)%>% distinct()) %>%
  asset_classification_and_adjust() %>%
  select(기준일자,펀드=펀드설명,자산군_소,daily_weight = weight) %>%
  left_join(universe_criteria %>% select(자산군_대,자산군_소) %>% distinct()) %>% 
  mutate(구분 = "MP")


bind_rows(
  position_AP_summarised,
  position_VP_summarised,
  position_MP_summarised
) %>% 
  group_by(기준일자,펀드,자산군_소) %>% 
  reframe(daily_weight_AP = sum(daily_weight[구분=="AP"]),
          daily_weight_VP = sum(daily_weight[구분=="VP"]),
          daily_weight_MP = sum(daily_weight[구분=="MP"]),
          `비중(AP-VP)` = daily_weight_AP-daily_weight_VP,
          `비중(VP-MP)` = daily_weight_VP-daily_weight_MP,
          자산군_대= 자산군_대[1]
          ) -> AP_VP_MP_diff_summarised



AP_VP_MP_diff_summarised %>%
  rename(펀드설명=펀드) %>% 
  mutate(new_대분류 =if_else(자산군_대=="채권","채권","주식+대체") ) %>% 
  group_by(기준일자,펀드설명) %>% 
  mutate(채권비중_AP = sum(daily_weight_AP[new_대분류=="채권"]),
         채권비중_VP = sum(daily_weight_VP[new_대분류=="채권"])) %>%  
  filter(new_대분류!="채권") %>% 
  group_by(기준일자,펀드설명) %>% 
  mutate(normalize_AP = sum(daily_weight_AP),
         normalize_VP = sum(daily_weight_VP),
         normalize_MP = sum(daily_weight_MP)) %>%
  ungroup() %>% 
  rowwise() %>% 
  mutate(min_AP_VP = min(daily_weight_AP/normalize_AP ,daily_weight_VP/normalize_VP),
         `min_주식+대체_대분류`= min(normalize_AP,normalize_VP),
         min_채권_대분류= min(채권비중_AP,채권비중_VP)) %>% ungroup() %>% 
  group_by(기준일자,펀드설명) %>% 
  reframe(`괴리율(VP&MP, 주식+대체 대분류)` = (normalize_VP-normalize_MP) ,
          `괴리율(AP&MP, 주식+대체 대분류)` = (normalize_AP-normalize_MP) ,
          `괴리율N.(VP&MP,주식+대체 소분류)`= max((daily_weight_VP/normalize_VP - daily_weight_MP/normalize_MP )) ,#`max[Normalize_(VP-MP)주식+대체_소분류]`
          `괴리율N.(AP&MP,주식+대체 소분류)`= max((daily_weight_AP/normalize_AP - daily_weight_MP/normalize_MP )) ,#`max[Normalize_(AP-MP)주식+대체_소분류]`
          `복제율N.(AP&VP,주식+대체 소분류)` = sum(min_AP_VP) ,#`Sum[min(Normalize_(AP,VP)주식+대체_소분류)]`
          `복제율(AP&VP,주식+대체 & 채권 대분류)`= sum(`min_주식+대체_대분류`[1],min_채권_대분류[1]) #`Sum[min(Normalize_(AP,VP)주식+대체&채권_대분류)]`
  ) %>% distinct() -> replicate_disparate_rate
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
  rename(펀드설명=펀드) %>% 
  left_join(universe_criteria %>% select(자산군_대,자산군_소) %>% distinct()) %>% 
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
  mutate(`펀드듀레이션(AP/VP)`=AP_duration/VP_duration,
         `펀드듀레이션(AP/MP)`=AP_duration/MP_duration,
         `펀드듀레이션(VP/MP)`=VP_duration/MP_duration,
         `채권듀레이션(AP/VP)`=AP_duration.N/VP_duration.N,
         `채권듀레이션(AP/MP)`=AP_duration.N/MP_duration.N,
         `채권듀레이션(VP/MP)`=VP_duration.N/MP_duration.N)  ->bond_duration_replicate




