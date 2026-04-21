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
print(timestamp())
setwd("/home/scip-r/MP_monitoring")
rm(list=ls())
source("./03_MP_monitor/Function 모듈_ACETDF_통합.R")

VP_fund_name<- tibble(
  펀드 = c("2MP24",	"1MP30",	"1MP35",	"1MP40",	"1MP45",	"1MP50",	"1MP55",	"1MP60", "4MP80",
         "3MP01",	"3MP02", "6MP07" ),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  설정일 = ymd(c("2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2024-04-08",
              "2022-10-05","2022-10-05","2023-12-28")))

# 1.DB에서 데이터 Loading --------------------------------------------------------
con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
con_solution <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'solution', host = '192.168.195.55')

query_fund_cd_list_AP <- c('07M02', '07J66', '07J71', '07J76', '07J81', '07J86', 
                           '07J91', '07J96', '07J41', '07J34', '07J48', '07J49', '07P70', '07Q93')
# 별도 DB에서 관리되는 MP들. 2024-12-23일까지의 정보 포함/ 2024-12-24일부터 백테스트모듈로 전환
query_fund_cd_list_VP <- c('2MP24', '1MP30', '1MP35', '1MP40', '1MP45', '1MP50', '1MP55', '1MP60', 
                           '3MP01', '3MP02', '6MP07', '4MP80')
# MOS 상으로 관리되는 MP들
query_fund_cd_ACETDF <- c('4MP25', '4MP30', '4MP35','4MP40', '4MP45', '4MP50', '4MP55', '4MP60', '4MP65',
                          '4MP70', '4MP75', '4MP80')

# 기존테이블에서 새로운테이블 저장할 것 추려서 저장하기 -------------------------------------------


# 1.DB에서 데이터 Loading --------------------------------------------------------
con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')
con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
con_solution <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'solution', host = '192.168.195.55')

sol_VP_rebalancing_inform <- tbl(con_solution,"sol_VP_rebalancing_inform") %>% collect()
sol_MP_released_inform <- tbl(con_solution,"sol_MP_released_inform") %>% collect()


USDKRW <- tbl(con_dt,"DWCI10260") %>% 
  select(STD_DT,CURR_DS_CD,TR_STD_RT) %>% 
  filter( STD_DT>="20221001",CURR_DS_CD %in% c('USD')) %>%
  rename(기준일자=STD_DT) %>%
  collect() %>% 
  mutate(기준일자= ymd(기준일자)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = CURR_DS_CD,values_from = TR_STD_RT) %>% 
  select(기준일자, `USD/KRW`=USD)

tbl(con_dt,"DWCI10220") %>% 
  select(기준일자 = std_dt,요일코드 = day_ds_cd,hldy_yn,hldy_nm,월말일여부=mm_lsdd_yn,전영업일=pdd_sals_dt,다음영업일 =nxt_sals_dt) %>% 
  filter( 기준일자>="20000101") %>% 
  collect() %>% 
  mutate(기준일자 = ymd(기준일자))->holiday_calendar

holiday_calendar %>% 
  filter(hldy_yn=="Y" &!(요일코드 %in% c("1","7"))) %>% 
  pull(기준일자)->KOREA_holidays

MP_rebalancing_historical <- sol_VP_rebalancing_inform %>%
  inner_join(sol_MP_released_inform, by = join_by(펀드설명,version==Release_date,경기국면),relationship = "many-to-many") %>% 
  select(리밸런싱날짜,펀드설명,ISIN,weight,rebalancing_reason)


tbl(con_SCIP,"back_dataset") %>%
  filter(!is.na(ISIN) | str_detect(name,"Index") | str_detect(name,"KIS")) %>% 
  collect()%>% 
  mutate(colname_backtest = if_else(is.na(ISIN), name,symbol)) %>% 
  mutate(colname_backtest = if_else(grepl("^[0-9]+$", colname_backtest), name, colname_backtest))   ->Data_List

MP_rebalancing_historical %>% 
  left_join(Data_List %>% select(dataset_id = id,ISIN)) %>% 
  mutate(dataseries_id= as.integer(6),
         region= if_else(str_sub(ISIN,1,2)=="KR","KR","not_KR"),
         port = "MP",
         hedge_ratio=0,cost_adjust=0) %>% 
  select(-ISIN) %>% 
  select(리밸런싱날짜,펀드설명,dataset_id ,dataseries_id, region,
         weight,port,hedge_ratio,  rebalancing_reason, cost_adjust ) %>% 
  filter(펀드설명 %in% c("TIF","TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060",
                     "MS STABLE", "MS GROWTH", "Golden Growth", "TDF2080"  )) ->MP_monitor_universe

  

MP_monitor_universe %>% 
  select(dataseries_id,dataset_id) %>% distinct() ->universe_list


# df에있는 universe 불러오기
pulled_data_universe <- universe_list %>%
  inner_join(tbl(con_SCIP,"back_datapoint") %>%
               select(timestamp_observation,data,dataset_id,dataseries_id) %>%
               filter(timestamp_observation> "2022-01-01"),
             copy = TRUE,
             by = join_by(dataset_id,dataseries_id))


MP_monitor_universe %>% 
  group_by(리밸런싱날짜, 펀드설명,port) %>% 
  nest() %>% 
  mutate(dataset_id_vector    = map(data, ~ .x$dataset_id),
         dataseries_id_vector    = map(data, ~ .x$dataseries_id ),
         region_vector     =  map(data, ~ .x$region),
         weight_vector     =  map(data, ~ .x$weight),
         hedge_ratio_vector = map(data, ~ .x$hedge_ratio),
         cost_adjust_vector = map(data, ~ .x$cost_adjust)
  ) %>%
  ungroup() %>%
  group_by(펀드설명,port) %>%
  mutate(리밸런싱마감일= lead(리밸런싱날짜,n=1)) %>%
  mutate(리밸런싱마감일= if_else(is.na(리밸런싱마감일),ymd(today()-days(1)), 리밸런싱마감일 )) %>%
  ungroup() %>%
  arrange(펀드설명)->MP_VP_BM_prep




tictoc::tic()
MP_VP_BM_prep  %>% 
  arrange(펀드설명,port,리밸런싱날짜) %>% 
  group_by(펀드설명) %>% 
  slice_tail(n=2) %>% 
  mutate(backtest= pmap(list(dataset_id_vector,dataseries_id_vector,region_vector,
                             weight_vector,hedge_ratio_vector,cost_adjust_vector,
                             리밸런싱날짜,리밸런싱마감일),
                        .f = ~calculate_BM_results_bulk(dataset_id_vector    = ..1,
                                                        dataseries_id_vector = ..2,
                                                        region_vector        = ..3,
                                                        weight_vector        = ..4,
                                                        hedge_ratio_vector   = ..5,
                                                        cost_adjust_vector   = ..6,
                                                        start_date        = ..7,
                                                        end_date          = ..8)))  ->MP_VP_BM_results
tictoc::toc()



MP_VP_BM_results %>% select(리밸런싱날짜,펀드설명,port,backtest) %>% 
  mutate(backtest_descriptrion = map(backtest,.f= ~.x[[2]]),.keep = "unused") %>% 
  unnest(backtest_descriptrion) ->MP_VP_BM_results_descriptrion

MP_VP_BM_results %>% 
  mutate(backtest_res= map(backtest,.f= ~.x[[1]])) %>% 
  select(리밸런싱날짜,펀드설명,port,backtest_res) %>%
  unnest(backtest_res) %>% 
  # 그룹화: 기준일자별로 리밸런싱날짜가 빠른/늦은 경우 처리
  group_by(펀드설명, 기준일자,port)  %>% 
  reframe(
    port= port[1],
    리밸런싱날짜 = 리밸런싱날짜[1],
    weighted_sum_drift = first(weighted_sum_drift), # 리밸런싱날짜 빠른 값
    weighted_sum_fixed = first(weighted_sum_fixed), # 리밸런싱날짜 빠른 값
    `Weight_drift(T)`   = list(first(`Weight_drift(T)`)),               # 리밸런싱날짜 빠른 값
    `Weight_drift(T-1)` = list(first(`Weight_drift(T-1)`)) ,            # 리밸런싱날짜 빠른 값
    `Weight_fixed(T)`   = list(first(`Weight_fixed(T)`))
    # `Weight_drift(T)`   = list(last(`Weight_drift(T)`)),               # 리밸런싱날짜 늦은 값
    # `Weight_drift(T-1)` = list(last(`Weight_drift(T-1)`)) ,            # 리밸런싱날짜 늦은 값
    # `Weight_fixed(T)`   = list(last(`Weight_fixed(T)`))
  ) -> MP_VP_BM_results_core


MP_VP_BM_results %>% 
  select(리밸런싱날짜,펀드설명,port,backtest) %>% 
  mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
  unnest(backtest_res) %>% 
  select(-contains("weighted_sum"),-contains("Weight_")) ->MP_VP_BM_results_raw



MP_VP_BM_results_core %>% 
  filter(port=="MP") %>% 
  select(리밸런싱날짜,펀드설명,port,기준일자,`Weight_drift(T)`) %>% 
  unnest_longer(`Weight_drift(T)`, values_to = "weight", indices_to = "symbol") %>% 
  left_join(MP_VP_BM_results_descriptrion %>% 
              select(symbol,ISIN) %>% distinct()) %>% 
  select(펀드설명,기준일자,VP_weight=weight, symbol,ISIN) %>% 
  left_join(
    
    MP_VP_BM_results_core %>% 
      filter(port=="MP") %>% 
      select(리밸런싱날짜,펀드설명,port,기준일자,`Weight_fixed(T)`) %>% 
      unnest_longer(`Weight_fixed(T)`, values_to = "weight", indices_to = "symbol") %>% 
      left_join(MP_VP_BM_results_descriptrion %>% 
                  select(symbol,ISIN) %>% distinct()) %>% 
      select(펀드설명,기준일자,MP_weight=weight, symbol,ISIN)
    
  ) %>% 
  select(펀드설명,기준일자, symbol,ISIN,MP_weight,VP_weight) -> position_VP_update

#AP현황에서 이름, 유형 가져오는 모듈 ----------------------------------------------------------


query_fund_cd_list_AP <- c('07M02', '07J66', '07J71', '07J76', '07J81', '07J86', 
                           '07J91', '07J96', '07J41', '07J34', '07J48', '07J49', '07P70', '07Q93')
# 별도 DB에서 관리되는 MP들. 2024-12-23일까지의 정보 포함/ 2024-12-24일부터 백테스트모듈로 전환
query_fund_cd_list_VP <- c('2MP24', '1MP30', '1MP35', '1MP40', '1MP45', '1MP50', '1MP55', '1MP60', 
                           '3MP01', '3MP02', '6MP07', '4MP80')


HOLD_AST_DS_CD_NM_inform <- tbl(con_dt, "DWPM10530") %>%
  filter(STD_DT >= local(str_remove_all(today()-days(3),pattern = "-"))) %>% 
  filter(FUND_CD %in%  !!c(query_fund_cd_list_AP,query_fund_cd_list_VP)) %>%
  select(HOLD_AST_DS_CD,ITEM_CD,ITEM_NM) %>% distinct() %>% 
  collect() %>% 
  group_by(ITEM_CD) %>% 
  filter(row_number()==max(row_number())) %>% 
  ungroup()


# 수정사항 2. sol_10530테이블의 마지막날짜 가져와서 이후 업데이트할것만 추리기

last_update_table_sol_DWPM10530<- 
  tbl(con_solution,"sol_DWPM10530") %>% 
  select(STD_DT,IMC_CD,FUND_CD) %>% distinct() %>% 
  group_by(FUND_CD) %>% 
  filter(STD_DT == max(STD_DT)) %>% 
  ungroup() %>% collect() %>% 
  mutate(STD_DT= ymd(STD_DT))

last_update_table_sol_DWPM10510<- 
  tbl(con_solution,"sol_DWPM10510") %>% 
  select(STD_DT,IMC_CD, FUND_CD,MOD_STPR,DD1_ERN_RT,NAST_AMT) %>% distinct() %>% 
  group_by(FUND_CD) %>% 
  filter(STD_DT == max(STD_DT)) %>% 
  ungroup() %>% collect() %>% 
  mutate(STD_DT= ymd(STD_DT))

fund_name_mapping<- tbl(con_solution,"sol_DWPM10530") %>% 
  select(FUND_CD,FUND_NM) %>% distinct() %>% collect()

last_update_table_sol_DWPM10530 %>% 
  inner_join(
    position_VP_update %>% 
      select(펀드설명, 기준일자,symbol,ISIN,VP_weight) %>% 
      left_join(MP_VP_BM_results_descriptrion %>% select(name,ISIN) %>% distinct()) %>% 
      left_join(VP_fund_name %>% select(-설정일)) , by = c("FUND_CD" = "펀드")) %>% # FUND_CD와 펀드가 일치
  filter(기준일자 > STD_DT) %>% # 기준일자가 STD_DT보다 큰 경우만 필터링
  mutate(STD_DT = str_remove_all(기준일자,"-")) %>% 
  mutate(VP_weight = VP_weight*100) %>% 
  mutate(IMC_CD = "M03228",
         POS_DS_CD = "매수",
         SEQ = 1) %>% 
  select(STD_DT,IMC_CD, FUND_CD,ITEM_CD = ISIN, POS_DS_CD,SEQ,NAST_TAMT_AGNST_WGH= VP_weight) %>% 
  mutate(EVL_AMT = NAST_TAMT_AGNST_WGH) %>% 
  left_join(HOLD_AST_DS_CD_NM_inform) %>% 
  left_join(fund_name_mapping)->uploading_DB_10530 # %>% 

print("solution10530 업데이트 목록")
uploading_DB_10530

# 데이터 추가
dbWriteTable(con_solution,
             name = "sol_DWPM10530",
             value = uploading_DB_10530,
             append = TRUE,
             row.names = FALSE)

last_update_table_sol_DWPM10510 %>% 
  left_join(MP_VP_BM_results_core %>% 
              filter(port=="MP") %>% 
              select(리밸런싱날짜,펀드설명,port,기준일자 ,weighted_sum_drift ) %>% 
              left_join(VP_fund_name %>% select(-설정일)) , by = c("FUND_CD" = "펀드")) %>% 
  filter(기준일자 > STD_DT) %>% 
  mutate(STD_DT = str_remove_all(기준일자,"-")) %>% 
  mutate(DD1_ERN_RT = weighted_sum_drift *100) %>% 
  mutate(NAST_AMT = 100) %>% 
  mutate(IMC_CD = "M03228") %>% 
  select(STD_DT,IMC_CD, FUND_CD,DD1_ERN_RT,NAST_AMT) -> uploading_DB_10510
  


# 데이터 추가

if(nrow(uploading_DB_10510)>=1){
  
  last_update_table_sol_DWPM10510 %>% 
    filter(FUND_CD %in% unique(uploading_DB_10510$FUND_CD)) %>% 
    mutate(STD_DT = str_remove_all(STD_DT,"-")) %>% 
    mutate(DD1_ERN_RT = 0) %>% 
    bind_rows(uploading_DB_10510) %>% 
    arrange(STD_DT) %>% 
    group_by(FUND_CD) %>% 
    mutate(last_MOD_STPR = MOD_STPR[1] ) %>% 
    mutate(cum_return =cumprod(1+DD1_ERN_RT/100) ) %>% 
    mutate(MOD_STPR = last_MOD_STPR*cum_return) %>% ungroup() %>% 
    select(-last_MOD_STPR,-cum_return) %>% 
    group_by(FUND_CD) %>% 
    filter(STD_DT!= min(STD_DT)) %>% 
    ungroup()-> uploading_DB_10510_수정기준가

  
  dbWriteTable(con_solution,
               name = "sol_DWPM10510",
               value = uploading_DB_10510_수정기준가,
               append = TRUE,row.names = FALSE)
  
  print("solution10510 업데이트 목록")
  uploading_DB_10510_수정기준가
    
}else{
  print("solution10510 업데이트 목록")
  print("이미 전부 업데이트되었습니다.")
}
print(timestamp())

