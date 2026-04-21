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
source("./03_MP_monitor/Function 모듈 20250703.R")

VP_fund_name<- tibble(
  펀드 = c("2MP24",	"1MP30",	"1MP35",	"1MP40",	"1MP45",	"1MP50",	"1MP55",	"1MP60", "4MP80",
         "3MP01",	"3MP02", "6MP07" ),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  설정일 = ymd(c("2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2024-04-08",
              "2022-10-05","2022-10-05","2023-12-28")))

VP_fund_name_ACETDF <- tibble(
  펀드 =c('4MP25', '4MP30', '4MP35', '4MP40', '4MP45', '4MP50', '4MP55', '4MP60', '4MP65',
        '4MP70', '4MP75', '4MP80_AT'),
  펀드설명 = c('ACETDF2025', 'ACETDF2030', 'ACETDF2035',
           'ACETDF2040', 'ACETDF2045', 'ACETDF2050', 'ACETDF2055', 'ACETDF2060', 'ACETDF2065',
           'ACETDF2070', 'ACETDF2075', 'ACETDF2080')) %>% 
  mutate(설정일 = case_when(펀드설명 %in% c("ACETDF2030","ACETDF2050","ACETDF2080") ~ ymd("2025-03-07"),
                         TRUE ~ ymd("2023-05-12")))

VP_fund_name_기타신상품 <-  tibble(
  펀드 =c('SK EMP70'),
  펀드설명 = c('SK EMP70')) %>% 
  mutate(설정일 = case_when(펀드설명 %in% c("SK EMP70") ~ ymd("2025-03-17"),
                         TRUE ~ ymd("2099-01-01")))

VP_fund_name_ActiveTDF <- tibble(
  펀드 =c("ActiveTDF2025(H)","ActiveTDF2030(H)","ActiveTDF2035(H)","ActiveTDF2040(H)","ActiveTDF2045(H)",
        "ActiveTDF2050(H)","ActiveTDF2050(UH)","ActiveTDF2055(H)","ActiveTDF2055(UH)","ActiveTDF2060(H)","ActiveTDF2060(UH)"),
  펀드설명 = c("ActiveTDF2025(H)","ActiveTDF2030(H)","ActiveTDF2035(H)","ActiveTDF2040(H)","ActiveTDF2045(H)",
           "ActiveTDF2050(H)","ActiveTDF2050(UH)","ActiveTDF2055(H)","ActiveTDF2055(UH)","ActiveTDF2060(H)","ActiveTDF2060(UH)")) %>% 
  mutate(설정일 = ymd("2025-12-29"))


VP_fund_name <- bind_rows(VP_fund_name,VP_fund_name_ACETDF,
                          VP_fund_name_ActiveTDF,
                          VP_fund_name_기타신상품) %>% 
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                       "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                       "ACETDF2025" ,"ACETDF2030","ACETDF2035","ACETDF2040","ACETDF2045","ACETDF2050" ,  
                                       "ACETDF2055" ,"ACETDF2060","ACETDF2065","ACETDF2070","ACETDF2075","ACETDF2080" ,
                                       "ActiveTDF2025(H)","ActiveTDF2030(H)","ActiveTDF2035(H)","ActiveTDF2040(H)","ActiveTDF2045(H)",
                                       "ActiveTDF2050(H)","ActiveTDF2050(UH)","ActiveTDF2055(H)","ActiveTDF2055(UH)","ActiveTDF2060(H)","ActiveTDF2060(UH)",
                                       "SK EMP70")))

# 1.DB에서 데이터 Loading --------------------------------------------------------
# query_fund_cd_list_AP <- c('07M02', '07J66', '07J71', '07J76', '07J81', '07J86', 
#                            '07J91', '07J96', '07J41', '07J34', '07J48', '07J49', '07P70', '07Q93')
# # 별도 DB에서 관리되는 MP들. 2024-12-23일까지의 정보 포함/ 2024-12-24일부터 백테스트모듈로 전환
# query_fund_cd_list_VP <- c('2MP24', '1MP30', '1MP35', '1MP40', '1MP45', '1MP50', '1MP55', '1MP60', 
#                            '3MP01', '3MP02', '6MP07', '4MP80')

# 기존테이블에서 새로운테이블 저장할 것 추려서 저장하기 -------------------------------------------

# 1.DB에서 데이터 Loading --------------------------------------------------------
con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')
con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
con_solution <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'solution', host = '192.168.195.55')

sol_VP_rebalancing_inform <- tbl(con_solution,"sol_VP_rebalancing_inform") %>% collect()
sol_MP_released_inform <- tbl(con_solution,"sol_MP_released_inform") %>% collect()


tbl(con_dt,"DWCI10220") %>% 
  select(기준일자 = std_dt,요일코드 = day_ds_cd,hldy_yn,hldy_nm,월말일여부=mm_lsdd_yn,전영업일=pdd_sals_dt,다음영업일 =nxt_sals_dt) %>% 
  filter( 기준일자>="20000101") %>% 
  collect() %>% 
  mutate(기준일자 = ymd(기준일자))->holiday_calendar

holiday_calendar %>% 
  filter(기준일자<today()) %>% 
  filter(hldy_yn=="N") %>% pull(기준일자) %>% max()->최근영업일


USDKRW <- tbl(con_dt,"DWCI10260") %>% 
  select(STD_DT,CURR_DS_CD,TR_STD_RT) %>% 
  filter( STD_DT>="20221001",CURR_DS_CD %in% c('USD')) %>%
  rename(기준일자=STD_DT) %>%
  collect() %>% 
  mutate(기준일자= ymd(기준일자)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = CURR_DS_CD,values_from = TR_STD_RT) %>% 
  arrange(기준일자) %>% 
  select(기준일자, `USD/KRW`=USD)
ecos.setKey("FWC2IZWA5YD459SQ7RJM")
USDKRW <- ecos::statSearch(stat_code = "731Y003","0000003",cycle ="D",
                           start_time = "19000101",
                           end_time =최근영업일 %>% str_remove_all("-") ) %>% tibble() %>%
  select(기준일자=time,`USD/KRW`  = data_value) %>%
  mutate(기준일자= ymd(기준일자)) %>% 
  bind_rows(tibble(기준일자=today()-days(1),`USD/KRW`=NA)) %>% 
  timetk::pad_by_time(.date_var = 기준일자,.by = "day",.fill_na_direction = "down") %>% 
  group_by(기준일자) %>% 
  filter(row_number()==1) %>% 
  ungroup()

holiday_calendar %>% 
  filter(hldy_yn=="Y" &!(요일코드 %in% c("1","7"))) %>% 
  pull(기준일자)->KOREA_holidays

MP_rebalancing_historical <- sol_VP_rebalancing_inform %>%
  inner_join(sol_MP_released_inform, by = join_by(펀드설명,version==Release_date,경기국면,
                                                  for_ACE,Recalculate_date),relationship = "many-to-many") %>% 
  select(리밸런싱날짜,펀드설명,port,ISIN,weight,rebalancing_reason,for_ACE,Recalculate_date,hedge_ratio)


tbl(con_SCIP,"back_dataset") %>%
  collect()%>% 
  filter(!is.na(ISIN) | str_detect(name,"Index") | str_detect(name,"KIS")) %>% 
  mutate(colname_backtest = if_else(is.na(ISIN), name,symbol)) %>% 
  mutate(colname_backtest = if_else(grepl("^[0-9]+$", colname_backtest), name, colname_backtest))   ->Data_List

MP_rebalancing_historical %>% 
  left_join(Data_List %>% select(dataset_id = id,ISIN)) %>% 
  mutate(dataseries_id= as.integer(6),
         region= if_else(str_sub(ISIN,1,2)=="KR","KR","not_KR"),
         port = port,cost_adjust=0,tracking_multiple=1) %>% 
  select(-ISIN) %>% 
  select(리밸런싱날짜,펀드설명,port, for_ACE, Recalculate_date,dataset_id ,dataseries_id, region,
         weight,port,hedge_ratio,  rebalancing_reason, cost_adjust,tracking_multiple ) ->MP_monitor_universe

# filter(펀드설명 %in% c("TIF","TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060",
#                    "MS STABLE", "MS GROWTH", "Golden Growth", "TDF2080"  )) ->MP_monitor_universe

hedge_cost_strictly <- TRUE

MP_monitor_universe %>% 
  select(dataseries_id,dataset_id) %>% distinct() ->universe_list


# df에있는 universe 불러오기
pulled_data_universe <- universe_list %>%
  inner_join(tbl(con_SCIP,"back_datapoint") %>%
               select(timestamp_observation,data,dataset_id,dataseries_id) %>%
               filter(timestamp_observation> "2022-01-01"),
             copy = TRUE,
             by = join_by(dataset_id,dataseries_id))


F_USDKRW_Index <- tbl(con_SCIP,"back_datapoint") %>%
  filter(dataset_id == 382, dataseries_id == 9) %>% collect() %>% 
  mutate(기준일자 = ymd(timestamp_observation)) %>%
  arrange(기준일자) %>%
  mutate(data = map_dbl(data, ~as.numeric(rawToChar(unlist(.x))))) %>%
  # bind_rows(tibble(기준일자 = 최근영업일)) %>%
  # group_by(기준일자) %>%
  # filter(row_number()==1) %>%
  # ungroup() %>% 
  select(기준일자, `F_USD/KRW`=data) %>% 
  timetk::pad_by_time(.date_var = 기준일자,.by = "day",.fill_na_direction = "down")

#if(1==2){
if(max(F_USDKRW_Index$기준일자) != 최근영업일){
  print("최근영업일 달러선물지수 업데이트가 필요합니다.")
}else{
  
  MP_monitor_universe %>% 
    #filter(!(str_detect(펀드설명,"\\(H\\)"))) %>%  # F-USDKRW수기로 업데이트 끝나면 다시원복
    filter(!(펀드설명 %in% c("ACETDF2025","ACETDF2035","ACETDF2040","ACETDF2045",
                         "ACETDF2055","ACETDF2060","ACETDF2065","ACETDF2070","ACETDF2075"))) %>% 
    #filter(펀드설명=="TIF") %>% 
    filter(!((리밸런싱날짜>=ymd("2025-09-16") & for_ACE ==0 ))) %>% # for_ACE로 바꾼 이후(250916)로는 , ACE MP만 필터링하기위함
    #mutate(리밸런싱날짜 = if_else(str_detect(펀드설명,"ActiveTDF"),ymd("2025-12-01"),리밸런싱날짜)) %>% 
    mutate(DB_반영리밸런싱날짜= 리밸런싱날짜) %>% 
    mutate(리밸런싱날짜 = case_when(port == "VP" ~ Recalculate_date,
                              TRUE ~ 리밸런싱날짜)) %>% 
    group_by(리밸런싱날짜, 펀드설명) %>% 
    #filter(port==port[n()]) %>%  # MP만 있는시점엔 MP, MP,VP동시에 있으면 VP가져오기
    group_by(리밸런싱날짜, 펀드설명,port) %>% 
    nest() %>% 
    mutate(Recalculate_date_vector = map(data, ~ .x$Recalculate_date),
           DB_반영리밸런싱날짜_vector = map(data, ~ .x$DB_반영리밸런싱날짜),
           dataset_id_vector    = map(data, ~ .x$dataset_id),
           dataseries_id_vector    = map(data, ~ .x$dataseries_id ),
           region_vector     =  map(data, ~ .x$region),
           weight_vector     =  map(data, ~ .x$weight),
           hedge_ratio_vector = map(data, ~ .x$hedge_ratio),
           cost_adjust_vector = map(data, ~ .x$cost_adjust),
           tracking_multiple_vector = map(data, ~ .x$tracking_multiple)
    ) %>%
    ungroup() %>% 
    group_by(펀드설명) %>%
    mutate(리밸런싱마감일= lead(리밸런싱날짜,n=1)) %>%
    mutate(리밸런싱마감일= if_else(is.na(리밸런싱마감일),ymd(today()-days(1)), 리밸런싱마감일 )) %>%
    ungroup() %>%
    arrange(펀드설명) %>% 
    arrange(펀드설명,리밸런싱날짜,port) %>% 
    group_by(펀드설명) %>% 
    filter(리밸런싱날짜<=today()) %>% 
    slice_tail(n=2) %>% 
    filter(리밸런싱날짜<=최근영업일)->MP_VP_BM_prep
  
  
  
  tictoc::tic()
  MP_VP_BM_prep  %>% 
    arrange(펀드설명,port,리밸런싱날짜) %>% 
    group_by(펀드설명) %>% 
    mutate(backtest= pmap(list(dataset_id_vector,dataseries_id_vector,region_vector,
                               weight_vector,hedge_ratio_vector,cost_adjust_vector,tracking_multiple_vector,
                               리밸런싱날짜,리밸런싱마감일),
                          #.f = ~calculate_BM_results_bulk(dataset_id_vector    = ..1,
                          .f = ~calculate_BM_results_bulk_hedge_cost_strictly(dataset_id_vector    = ..1,
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
  
  
  
  MP_VP_BM_results %>% select(리밸런싱날짜,펀드설명,port,backtest) %>% 
    mutate(backtest_descriptrion = map(backtest,.f= ~.x[[2]]),.keep = "unused") %>% 
    unnest(backtest_descriptrion) ->MP_VP_BM_results_descriptrion
  
  
  
  MP_VP_BM_results %>% 
    mutate(backtest_res= map(backtest,.f= ~.x[[1]]),
           Recalculate_date = map(Recalculate_date_vector, .f = ~.x[[1]]),
           DB_반영리밸런싱날짜 = map(DB_반영리밸런싱날짜_vector, .f = ~.x[[1]])) %>% 
    unnest(c(Recalculate_date,DB_반영리밸런싱날짜)) %>% 
    select(리밸런싱날짜,펀드설명,port,Recalculate_date,DB_반영리밸런싱날짜,backtest_res) %>% 
    mutate(DB_반영마지막날짜 = lead(DB_반영리밸런싱날짜, n =1,default = 최근영업일)) %>% 
    #filter(펀드설명 == "ACETDF2050") %>% 
    arrange(DB_반영리밸런싱날짜) %>%  # MP , VP 순서가 아닌,DB_반영리밸런싱날짜 기준 오름차순 정렬
    unnest(backtest_res) %>% # 그룹화: 기준일자별로 리밸런싱날짜가 빠른/늦은 경우 처리
    group_by(펀드설명) %>%
    #filter(!is.na(Recalculate_date)) %>% 
    filter(!is.na(Recalculate_date)|펀드설명=="SK EMP70") %>% 
    #filter(str_detect(펀드설명,"ActiveTDF")) %>% 
    filter(기준일자 > DB_반영리밸런싱날짜 | row_number()==1 ) %>% 
    group_by(펀드설명, 기준일자)  %>% 
    reframe(
      #port= port[n()],
      리밸런싱날짜 = 리밸런싱날짜[1],
      weighted_sum_drift = first(weighted_sum_drift), # 리밸런싱날짜 빠른 값
      weighted_sum_fixed = first(weighted_sum_fixed), # 리밸런싱날짜 빠른 값
      `Weight_drift(T)`   = list(first(`Weight_drift(T)`)),    # 리밸런싱날짜 빠른 값
      `Weight_drift(T-1)` = list(first(`Weight_drift(T-1)`)) , # 리밸런싱날짜 빠른 값
      `Weight_fixed(T)`   = list(first(`Weight_fixed(T)`))
      # `Weight_drift(T)`   = list(last(`Weight_drift(T)`)),               # 리밸런싱날짜 늦은 값
      # `Weight_drift(T-1)` = list(last(`Weight_drift(T-1)`)) ,            # 리밸런싱날짜 늦은 값
      # `Weight_fixed(T)`   = list(last(`Weight_fixed(T)`))
    ) ->MP_VP_BM_results_core
  
  # MP_VP_BM_results_core %>% 
  #   filter(str_detect(펀드설명, "ActiveTDF"))
  
  MP_VP_BM_results %>% 
    select(리밸런싱날짜,펀드설명,port,backtest) %>% 
    mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
    unnest(backtest_res) %>% 
    select(-contains("weighted_sum"),-contains("Weight_")) ->MP_VP_BM_results_raw
  
  
  
  MP_VP_BM_results_core %>% 
    #filter(port=="MP") %>% 
    select(리밸런싱날짜,펀드설명,기준일자,`Weight_drift(T)`) %>% 
    unnest_longer(`Weight_drift(T)`, values_to = "weight", indices_to = "symbol") %>% 
    left_join(MP_VP_BM_results_descriptrion %>% 
                select(symbol,ISIN) %>% distinct()) %>% 
    select(펀드설명,기준일자,VP_weight=weight, symbol,ISIN) %>% 
    left_join(
      
      MP_VP_BM_results_core %>% 
        #filter(port=="MP") %>% 
        select(리밸런싱날짜,펀드설명,기준일자,`Weight_fixed(T)`) %>% 
        unnest_longer(`Weight_fixed(T)`, values_to = "weight", indices_to = "symbol") %>% 
        left_join(MP_VP_BM_results_descriptrion %>% 
                    select(symbol,ISIN) %>% distinct()) %>% 
        select(펀드설명,기준일자,MP_weight=weight, symbol,ISIN)
      
    ) %>% 
    select(펀드설명,기준일자, symbol,ISIN,MP_weight,VP_weight) -> position_VP_update
  # position_VP_update %>% 
  #   filter(펀드설명=="MS STABLE") %>% view()
  #position_VP_update %>% view()
  #AP현황에서 이름, 유형 가져오는 모듈 ----------------------------------------------------------
  
  
  query_fund_cd_list_AP <- c('07M02', '07J66', '07J71', '07J76', '07J81', '07J86', 
                             '07J91', '07J96', '07J41', '07J34', '07J48', '07J49', '07P70', '07Q93',
                             '9004Q','9004R','9004S')
  # 별도 DB에서 관리되는 MP들. 2024-12-23일까지의 정보 포함/ 2024-12-24일부터 백테스트모듈로 전환
  query_fund_cd_list_VP <- unique(VP_fund_name$펀드)
  
  
  # HOLD_AST_DS_CD_NM_inform <- tbl(con_dt, "DWPM10530") %>%
  #   filter(STD_DT >= !!(str_remove_all(today()-days(3),pattern = "-"))) %>% 
  #   filter(FUND_CD %in%  !!c(query_fund_cd_list_AP,query_fund_cd_list_VP)) %>%
  #   select(HOLD_AST_DS_CD,ITEM_CD,ITEM_NM) %>% distinct() %>% 
  #   collect() %>% 
  #   group_by(ITEM_CD) %>% 
  #   filter(row_number()==max(row_number())) %>% 
  #   ungroup()
  
  tictoc::tic()
  HOLD_AST_DS_CD_NM_inform <- tbl(con_solution, "sol_DWPI10021") %>%
    filter(item_cd  %in%  !!c(unique(position_VP_update$ISIN))) %>%
    filter(imc_cd == '003228') %>% 
    group_by(imc_cd, item_cd) %>%
    filter(load_dttm==max(load_dttm)) %>%
    filter(eftv_end_dt == max(eftv_end_dt)) %>% 
    ungroup() %>% 
    select(HOLD_AST_DS_CD = hold_ast_ds_cd,ITEM_CD = item_cd,ITEM_NM =item_nm) %>% 
    collect() %>% distinct()
  tictoc::toc()
  
  
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
  
  new_fund<- setdiff(VP_fund_name %>% 
                       # filter(펀드!="4MP80_AT") %>% 
                       pull(펀드),last_update_table_sol_DWPM10530$FUND_CD)
  
  
  if(length(new_fund)!=0){
    
    sol_MP_released_inform %>% 
      filter(펀드설명 %in% new_fund) ->new_fund_information
    
    last_update_table_sol_DWPM10530 %>% 
      bind_rows(
        new_fund_information %>% 
          group_by(펀드설명) %>% 
          reframe(STD_DT = min(Release_date)-days(1),
                  IMC_CD = "M03228") %>% 
          rename(FUND_CD = 펀드설명)
      ) ->last_update_table_sol_DWPM10530
    
    last_update_table_sol_DWPM10510 %>% 
      bind_rows(
        new_fund_information %>% 
          group_by(펀드설명) %>% 
          reframe(STD_DT = min(Release_date)-days(1),
                  IMC_CD = "M03228") %>% 
          rename(FUND_CD = 펀드설명) %>% 
          mutate(MOD_STPR = 1000,DD1_ERN_RT = 0, NAST_AMT=100 )
      ) ->last_update_table_sol_DWPM10510
    
    fund_name_mapping %>% 
      bind_rows(
        new_fund_information %>% 
          group_by(펀드설명) %>% 
          reframe(FUND_NM = 펀드설명[1]) %>% 
          rename(FUND_CD = 펀드설명)
      )->fund_name_mapping
  }
  
  
  
  last_update_table_sol_DWPM10530 %>% # 신규 종목의 경우 없음. 이땐 어떻게??
    inner_join(
      position_VP_update %>% 
        select(펀드설명, 기준일자,symbol,ISIN,VP_weight) %>% 
        left_join(MP_VP_BM_results_descriptrion %>% select(name,ISIN,hedge_ratio) %>% distinct()) %>% 
        left_join(VP_fund_name %>% select(-설정일)) , by = c("FUND_CD" = "펀드")) %>% # FUND_CD와 펀드가 일치
    filter(기준일자 > STD_DT) %>%  # 기준일자가 STD_DT보다 큰 경우만 필터링
    mutate(STD_DT = str_remove_all(기준일자,"-")) %>% 
    mutate(VP_weight = VP_weight*100) %>% 
    mutate(IMC_CD = "M03228",
           POS_DS_CD = "매수",
           SEQ = 1) %>% 
    select(STD_DT,IMC_CD, FUND_CD,ITEM_CD = ISIN, POS_DS_CD,SEQ,NAST_TAMT_AGNST_WGH= VP_weight, hedge_ratio) %>% 
    mutate(EVL_AMT = NAST_TAMT_AGNST_WGH) %>% 
    left_join(HOLD_AST_DS_CD_NM_inform) %>% 
    left_join(fund_name_mapping) %>% 
    mutate(ITEM_NM = if_else(hedge_ratio == 1 , paste0("(H)",ITEM_NM), ITEM_NM )) %>% 
    select(-hedge_ratio) %>% 
    mutate(HOLD_AST_DS_CD = if_else(str_sub(ITEM_CD,1,2) == "KR","DET","OET"))  ->uploading_DB_10530 # %>% 
  #mutate(ITEM_NM = if_else(is.na(ITEM_NM),ITEM_CD,ITEM_NM))->uploading_DB_10530 # %>% 
  
  
  
  print("solution10530 업데이트 목록")
  print(uploading_DB_10530)
  
  # 데이터 추가
  dbWriteTable(con_solution,
               name = "sol_DWPM10530",
               value = uploading_DB_10530 %>% distinct(),
               append = TRUE,
               row.names = FALSE)
  
  last_update_table_sol_DWPM10510 %>% 
    left_join(MP_VP_BM_results_core %>% 
                # filter(port=="MP") %>% 
                select(리밸런싱날짜,펀드설명,기준일자 ,weighted_sum_drift ) %>% 
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
      arrange(STD_DT) %>% distinct() %>% 
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
                 value = uploading_DB_10510_수정기준가 ,
                 append = TRUE,row.names = FALSE)
    
    print("solution10510 업데이트 목록")
    print(uploading_DB_10510_수정기준가)
    
  }else{
    print("solution10510 업데이트 목록")
    print("이미 전부 업데이트되었습니다.")
  }
  print(timestamp())
  
  
}


# 매월초 백업 ------------------------------------------------------------------

if(month(최근영업일) != month(today())){
tbl(con_solution,"sol_DWPM10530") %>% collect() %>% saveRDS(str_glue("./VP/backup_sol_DWPM10530_{str_remove_all(최근영업일,'-')}.rds"))
tbl(con_solution,"sol_DWPM10510") %>% collect() %>% saveRDS(str_glue("./VP/backup_sol_DWPM10510_{str_remove_all(최근영업일,'-')}.rds"))
tbl(con_solution,"sol_VP_rebalancing_inform") %>% collect() %>% saveRDS(str_glue("./VP/backup_sol_VP_rebalancing_inform_{str_remove_all(최근영업일,'-')}.rds"))
tbl(con_solution,"sol_MP_released_inform") %>% collect() %>% saveRDS(str_glue("./VP/backup_sol_MP_released_inform_{str_remove_all(최근영업일,'-')}.rds"))
}
