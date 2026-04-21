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
#ecos.setKey("FWC2IZWA5YD459SQ7RJM")


# 1.DB에서 데이터 Loading --------------------------------------------------------
con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
# _1.1 DT DB ------------------------------------------------------------------
# __1.1.1 휴장일 ------------------------------------------------------------------
tbl(con_dt,"DWCI10220") %>% 
  select(기준일자 = std_dt,요일코드 = day_ds_cd,hldy_yn,hldy_nm,월말일여부=mm_lsdd_yn,전영업일=pdd_sals_dt,다음영업일 =nxt_sals_dt) %>% 
  filter( 기준일자>="20000101") %>% 
  collect() %>% 
  mutate(기준일자 = ymd(기준일자))->holiday_calendar

holiday_calendar %>% 
  filter(hldy_yn=="Y" &!(요일코드 %in% c("1","7"))) %>% 
  pull(기준일자)->KOREA_holidays

# __1.1.2 펀드정보_기준가 ------------------------------------------------------------------

query_fund_cd_list <- c('07M02', '07J66', '07J71', '07J76', '07J81', '07J86', 
                        '07J91', '07J96', '07J41', '07J34', '07J48', '07J49', 
                        '07P70', "07Q93")
# Query 8183 using dplyr
table_8183 <- tbl(con_dt, "DWPM10510") %>%
  inner_join(tbl(con_dt, "DWPI10011"), by = c("FUND_CD", "IMC_CD")) %>%
  filter(
    STD_DT >= '20221004',
    FUND_CD %in% !!query_fund_cd_list
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, FUND_NM , MOD_STPR) %>%
  collect()

# __1.1.3 펀드정보_명세부 ------------------------------------------------------------------
# Query 8004 using dplyr
table_8004 <- tbl(con_dt, "DWPM10530") %>%
  inner_join(tbl(con_dt, "DWPM10510"), by = c("FUND_CD", "IMC_CD", "STD_DT")) %>%
  filter(
    STD_DT >= '20221005',
    FUND_CD %in%  !!query_fund_cd_list
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, ITEM_CD, ITEM_NM, EVL_AMT, NAST_AMT) %>%
  collect() %>%
  filter(!(str_detect(ITEM_NM, "미지급") | str_detect(ITEM_NM, "미수")))

# __1.1.4 환율 ------------------------------------------------------------------
# ECOS 데이터의 날짜가 더 길다.
# USDKRW <- ecos::statSearch(stat_code = "731Y003","0000003",cycle ="D",
#                            start_time = "20221004",
#                            end_time =today() %>% str_remove_all("-") ) %>% tibble() %>%
#   select(기준일자=time,`USD/KRW`  = data_value) %>%
#   mutate(기준일자= ymd(기준일자))

USDKRW <- tbl(con_dt,"DWCI10260") %>% 
  select(STD_DT,CURR_DS_CD,TR_STD_RT) %>% 
  filter( STD_DT>="20221001",CURR_DS_CD %in% c('USD')) %>%
  rename(기준일자=STD_DT) %>%
  collect() %>% 
  mutate(기준일자= ymd(기준일자)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = CURR_DS_CD,values_from = TR_STD_RT) %>% 
  select(기준일자, `USD/KRW`=USD)

# _1.2 SCIP DB ------------------------------------------------------------
# __1.2.1 MP 종목별 데이터 -------------------------------------------------------

con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')


tbl(con_SCIP,"back_dataset") %>%
  filter(!is.na(ISIN) | str_detect(name,"Index")) %>% 
  left_join(tbl(con_SCIP,"back_dataseriesupdate")%>%
              select(dataset_id,dataseries_id, sourceID),by = join_by(id==dataset_id,symbol==sourceID))%>%
  #filter(dataseries_id %in% c(6,9,15,33)) %>%
  collect() %>% 
  mutate(dataseries_id = case_when(
    is.na(dataseries_id) & str_detect(symbol, " Index") ~ as.integer(9),
    is.na(dataseries_id) ~ as.integer(33),
    TRUE ~ dataseries_id  # 기존 값 유지
  )) ->Data_List


Data_List %>% 
  group_by(id)%>%
  mutate(국가= if_else(!is.na(ISIN), str_sub(ISIN,1,2),
                     if_else(dataseries_id==33| str_detect(str_to_upper(name),"KIS")|str_detect(str_to_upper(name),"KOSPI")|str_detect(str_to_upper(name),"KOREA"),"KR",
                             "not_KR")  ))%>% 
  ungroup() %>% 
  select(dataset_id=id,name,ISIN,symbol,국가)%>%
  distinct()-> Mapping_nation


MP_monitor_universe <- tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id ==61 )  %>% 
  collect() %>% 
  mutate(리밸런싱날짜 = ymd(timestamp_observation)) %>% 
  arrange(리밸런싱날짜) %>% 
  mutate(data = map(data, ~jsonlite::parse_json(rawToChar(unlist(.x))))) %>% 
  select(리밸런싱날짜,data) %>% 
  unnest_wider(data) %>% 
  filter(펀드설명 %in% c("TIF","TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060",
                     "MS STABLE", "MS GROWTH", "Golden Growth", "TDF2080"  )) 

MP_monitor_universe %>% 
  left_join(Data_List %>% 
              select(dataset_id=id,symbol)%>% distinct(),by = join_by(symbol)) %>% 
  select(dataseries_id,dataset_id) %>% distinct() ->universe_list


# df에있는 universe 불러오기
pulled_data_universe <- universe_list %>%
  inner_join(tbl(con_SCIP,"back_datapoint") %>%
               select(timestamp_observation,data,dataset_id,dataseries_id) %>%
               filter(timestamp_observation> "2022-01-01"),
             copy = TRUE,
             by = join_by(dataset_id,dataseries_id))


MP_monitor_universe %>% 
  left_join(Data_List %>% select(symbol,dataset_id = id) %>% distinct(),by = join_by(symbol)) %>% 
  #filter(펀드설명 == "Golden Growth") %>% 
  group_by(리밸런싱날짜, 펀드설명,port) %>% 
  nest() %>% 
  mutate(dataset_id_vector    = map(data, ~ .x$dataset_id),
         dataseries_id_vector    = map(data, ~ .x$dataseries_id ),
         weight_vector     =  map(data, ~ .x$weight),
         total_return_check_vector = map(data, ~ .x$total_return_check ),
         unhedge_check_vector = map(data, ~ .x$unhedge_check )
  ) %>%  
  ungroup() %>% 
  group_by(펀드설명,port) %>% 
  mutate(리밸런싱마감일= lead(리밸런싱날짜,n=1)) %>% 
  mutate(리밸런싱마감일= if_else(is.na(리밸런싱마감일),ymd(today()-days(1)), 리밸런싱마감일 )) %>% 
  ungroup() %>% 
  arrange(펀드설명)->MP_VP_BM_prep



tictoc::tic()

MP_VP_BM_prep %>% 
  arrange(펀드설명,port,리밸런싱날짜) %>% 
  mutate(backtest= pmap(list(dataset_id_vector,dataseries_id_vector,weight_vector,total_return_check_vector,unhedge_check_vector,
                             리밸런싱날짜,리밸런싱마감일),
                        .f = ~calculate_BM_results_bulk(filtering_universe=..1,
                                                        dataseries_specify=..2,
                                                        weight_vector     =..3,
                                                        total_return_check=..4,
                                                        unhedge_check     =..5,
                                                        start_date        =..6,
                                                        end_date          =..7,
                                                        `보수조정(연bp)` = 0)))  ->MP_VP_BM_results
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
    `Weight_drift(T)`   = list(last(`Weight_drift(T)`)),               # 리밸런싱날짜 늦은 값
    `Weight_drift(T-1)` = list(last(`Weight_drift(T-1)`)) ,            # 리밸런싱날짜 늦은 값
    `Weight_fixed(T)`   = list(last(`Weight_fixed(T)`)) 
  ) -> MP_VP_BM_results_core


MP_VP_BM_results %>% 
  select(리밸런싱날짜,펀드설명,port,backtest) %>% 
  mutate(backtest_res= map(backtest,.f= ~.x[[1]]),.keep = "unused") %>% 
  unnest(backtest_res) %>% 
  select(-contains("weighted_sum"),-contains("Weight_")) ->MP_VP_BM_results_raw

# MP_VP_BM_results_raw %>% 
#   select(리밸런싱날짜,펀드설명,port,기준일자,daily_return_list,raw_data_list) %>% 
#   unnest_wider(col = c(daily_return_list,raw_data_list),names_sep = "_") %>% view()
# __1.2.2 BM 종목별 데이터 ------------------------------------------------------



# __1.2.3 채권듀레이션 데이터 Loading ----

# 열 이름에 따른 dataset과 dataseries ID 매핑
bond_url_mapping = list(
  "한국 종합채권"               = list("dataset_id"= as.integer(43), "dataseries_id"= as.integer(22)),#"ACE 종합채권(AA-이상)KIS액티브"
  "한국 중장기국공채권"         = list("dataset_id"= as.integer(111), "dataseries_id"= as.integer(22)),#"ACE 중장기국공채액티브"
  "한국 3년국고채권"            = list("dataset_id"= as.integer(107), "dataseries_id"= as.integer(22)),#"ACE 국고채3년"
  "한국 10년국고채권"           = list("dataset_id"= as.integer(50), "dataseries_id"= as.integer(22)),#"ACE 국고채10년"
  "미국 하이일드채권"           = list("dataset_id"= as.integer(112), "dataseries_id"= as.integer(22)), # USHY
  "미국 물가채권"               = list("dataset_id"= as.integer(47), "dataseries_id"= as.integer(22)) #iShares TIPS Bond ETF (TIP)
  
  # 다른 열에 대한 매핑도 추가할 수 있습니다.
)


bond_url_mapping<- bond_url_mapping %>% enframe() %>%  
  unnest_wider(col = value)

db_dataid<- bond_url_mapping$dataset_id


duration_historical<- tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id %in% db_dataid, dataseries_id ==22 ) %>%   
  collect()


# 2. 펀드정보 매핑 -----------------------------------------------------------------

#_2.1 TDF, BF여부----
Fund_Information <-  tibble(
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  구분= c("TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","BF","BF","BF")
)
#_2.2 펀드설명 및 설정일----
AP_fund_name<- tibble(
  펀드 = c("07M02",	"07J66",	"07J71",	"07J76",	"07J81",	"07J86",	"07J91",	"07J96",	"07Q93",
         "07J41",	"07J34", "07P70" ),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  설정일 = ymd(c("2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2024-04-08",
              "2022-10-05","2022-10-05","2023-12-28")))
VP_fund_name<- tibble(
  
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  설정일 = ymd(c("2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2024-04-08",
              "2022-10-05","2022-10-05","2023-12-28"))) %>%
  mutate(펀드 = 펀드설명,.before = 펀드설명)



# 3. 자산군 분류체계 ----------------------------------------------------------------


universe_criteria <- 
  read_csv("/home/scip-r/MP_monitoring/00_data_updating/new_universe_criteria.csv", locale = locale(encoding = "CP949")) %>%
  distinct() %>% 
  # 23년 말 기준으로 새롭게 편입된 US 금 두 종목 존재. universe DB에 업데이트
  bind_rows(
    tribble( ~종목코드, ~종목명,~자산군_대,~자산군_중,~자산군_소,
             "US98149E3036", "SPDR GOLD MINISHARES TRUST" , "대체","원자재","금",  
             "US46436F1030", "ISHARES GOLD TRUST MICRO"   , "대체","원자재","금",
             "US46435U8532", "iShares Broad USD High Yield Corporate B", "채권","미국 채권","미국 하이일드채권",
             "KR7114460009", "ACE 국고채3년", "채권","한국 채권", "한국 3년국고채권",
             "KR7278540000", "KODEX MSCI Korea TR", "주식","한국 주식","한국 주식",
             "KR7114260003",	"KODEX 국고채3년","채권",	"한국 채권",	"한국 3년국고채권",
             "KR7133690008",	"TIGER 미국나스닥100","주식",	"미국 주식",	"미국 성장주",
             "KR7304940000",	"KODEX 미국나스닥100선물(H)","주식",	"미국 주식","미국 성장주",
             "KR7310960000",	"TIGER 200TR", "주식",	"한국 주식",	"한국 주식",
             "KR7367380003",	"ACE 미국나스닥100","주식",	"미국 주식",	"미국 성장주",
             "KR7468380001",	"KODEX iShares미국하이일드액티브", "채권",	"미국 채권",	"미국 하이일드채권",
             "KR7455030007",	"KODEX 미국달러SOFR금리액티브(합성)","채권",	"미국 채권",	"미국 채권",
             "US78462F1030",  "SPDR TRUST SERIES 1", "주식", "미국 주식", "미국 주식"#,
             
    )
  ) %>%
  mutate(자산군_소 = factor(자산군_소, levels = c("글로벌 주식","미국 주식","미국 성장주","미국 가치주","미국 중형주",
                                          "선진국 주식","신흥국 주식","한국 주식","호주 주식","글로벌 채권",
                                          "미국 채권","미국 채권 3개월","미국 채권 2년","미국 채권 5년","미국 채권 10년",
                                          "미국 물가채권", "미국 투자등급 회사채","미국 하이일드채권","미국외 글로벌채권","신흥국 달러채권",
                                          "한국 종합채권","한국 단기채권","한국 중장기국공채권","한국 3년국고채권","한국 10년국고채권","한국 회사채권","글로벌 원자재","금","미국 부동산","미국외 부동산","글로벌 인프라","원달러환율",
                                          "외화 유동성","원화 유동성","07J48","07J49"))) 





