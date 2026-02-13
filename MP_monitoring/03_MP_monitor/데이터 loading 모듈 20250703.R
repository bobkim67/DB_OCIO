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
con_solution <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'solution', host = '192.168.195.55')
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

최근영업일 <- holiday_calendar %>% filter(기준일자 == today()) %>% pull(전영업일) %>% ymd()

# __1.1.2 펀드정보_기준가 ------------------------------------------------------------------

query_fund_cd_list_AP <- c('07M02', '07J66', '07J71', '07J76', '07J81', '07J86', 
                           '07J91', '07J96', '07J41', '07J34', '07J48', '07J49', '07P70', '07Q93',
                           '9004Q', '9004R','9004S')
# 별도 DB에서 관리되는 MP들. 2024-12-23일까지의 정보 포함/ 2024-12-24일부터 백테스트모듈로 전환
query_fund_cd_list_VP <- c('2MP24', '1MP30', '1MP35', '1MP40', '1MP45', '1MP50', '1MP55', '1MP60', 
                           '3MP01', '3MP02', '6MP07', '4MP80')
# MOS 상으로 관리되는 MP들
query_fund_cd_ACETDF <- c('4MP25', '4MP30', '4MP35','4MP40', '4MP45', '4MP50', '4MP55', '4MP60', '4MP65',
                          '4MP70', '4MP75', '4MP80_AT')
# query_fund_cd_list <- c(query_fund_cd_list,query_fund_cd_ACETDF)


# Query 8183 using dplyr
table_8183_AP <- tbl(con_dt, "DWPM10510") %>%
  inner_join(tbl(con_dt, "DWPI10011"), by = c("FUND_CD", "IMC_CD")) %>%
  filter(
    STD_DT >= '20221004',
    FUND_CD %in% !!c(query_fund_cd_list_AP)
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, FUND_NM , MOD_STPR) %>%
  collect() %>% 
  mutate(MOD_STPR = if_else(str_detect(FUND_CD,"9004"),MOD_STPR/10,MOD_STPR))


#---- wrap 추가 파트----------------------------------------------------------------------------------------------
raw_8183_wrap_AP <- tbl(con_solution, "sol_wrap_pr") %>%
  collect()

# 비영업일 forward fill로 채우기
all_dates <- format(seq(ymd(min(raw_8183_wrap_AP$std_dt)), ymd(max(raw_8183_wrap_AP$std_dt)), by = "days"), "%Y%m%d")

table_8183_wrap_AP <- raw_8183_wrap_AP %>%
  # mutate(std_dt = as.character(std_dt)) %>%
  right_join(tibble(std_dt = all_dates), by = "std_dt") %>%
  arrange(std_dt) %>%
  rename_with(toupper)
table_8183_wrap_AP <- table_8183_wrap_AP %>% fill(everything(), .direction = "down")

table_8183_AP <- bind_rows(table_8183_AP, table_8183_wrap_AP)
#-----------------------------------------------------------------------------------------------------------------


table_8183_VP <- tbl(con_solution, "sol_DWPM10510") %>%
  inner_join(tbl(con_solution, "sol_DWPM10530") %>% select(FUND_CD,IMC_CD,FUND_NM) %>% distinct(),
             by = c("FUND_CD", "IMC_CD"), copy = TRUE) %>%
  filter(
    STD_DT >= '20221004',
    FUND_CD %in% !!c(query_fund_cd_list_VP)
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, FUND_NM , MOD_STPR) %>%
  collect()

#---- wrap 추가 파트----------------------------------------------------------------------------------------------
table_8183_wrap_VP <- tbl(con_solution, "sol_DWPM10510") %>%
  filter(FUND_CD == 'SK EMP70')%>%
  select(STD_DT, IMC_CD, FUND_CD, MOD_STPR) %>%
  collect()

table_8183_wrap_VP <- add_column(table_8183_wrap_VP, FUND_NM = "한국투자알아서자산배분70EMP랩", .before = ncol(table_8183_wrap_VP))

table_8183_VP <- bind_rows(table_8183_VP, table_8183_wrap_VP)
#-----------------------------------------------------------------------------------------------------------------

table_8183_ACETDF <- tbl(con_solution, "sol_DWPM10510") %>%
  inner_join(tbl(con_solution, "sol_DWPM10530") %>% select(FUND_CD,IMC_CD,FUND_NM) %>% distinct(),
             by = c("FUND_CD", "IMC_CD"), copy = TRUE) %>%
  filter(
    STD_DT >= '20221004',
    FUND_CD %in% !!c(query_fund_cd_ACETDF)
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, FUND_NM , MOD_STPR) %>%
  collect()

#table_8183_ACETDF <- table_8183_ACETDF %>% mutate(FUND_CD = case_when(FUND_CD == "4MP80"~ "4MP80_AT", TRUE ~ FUND_CD))

#--------------------------------------------------------


# __1.1.3 펀드정보_명세부 ------------------------------------------------------------------
# Query 8004 using dplyr
table_8004_AP <- tbl(con_dt, "DWPM10530") %>%
  inner_join(tbl(con_dt, "DWPM10510"), by = c("FUND_CD", "IMC_CD", "STD_DT")) %>%
  filter(
    STD_DT >= '20221005',
    FUND_CD %in%  !!c(query_fund_cd_list_AP)
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, ITEM_CD, ITEM_NM, EVL_AMT, NAST_AMT) %>%
  collect() %>%
  filter(!(str_detect(ITEM_NM, "미지급") | str_detect(ITEM_NM, "미수")))


#---- wrap 추가 파트----------------------------------------------------------------------------------------------
raw_8004_wrap_AP <- tbl(con_solution, "sol_wrap_details") %>%
  collect()

all_dates <- all_dates %>% tibble(std_dt = .)
all_dates <- all_dates %>% 
  mutate(
    latest_bday = sapply(std_dt, function(x) max(raw_8004_wrap_AP$std_dt[raw_8004_wrap_AP$std_dt <= x]))
  )

table_8004_wrap_AP <- all_dates %>%
  left_join(raw_8004_wrap_AP, by = c("latest_bday" = "std_dt"), relationship = "many-to-many") %>%
  select(-latest_bday) %>%
  rename_with(toupper)

table_8004_AP <- bind_rows(table_8004_AP, table_8004_wrap_AP)

table_8004_VP <- tbl(con_solution, "sol_DWPM10530") %>%
  inner_join(tbl(con_solution, "sol_DWPM10510"), by = c("FUND_CD", "IMC_CD", "STD_DT")) %>%
  filter(
    STD_DT >= '20221005',
    FUND_CD %in%  !!c(query_fund_cd_list_VP, "SK EMP70")
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, ITEM_CD, ITEM_NM, EVL_AMT, NAST_AMT) %>%
  collect()
#-----------------------------------------------------------------------------------------------------------------

table_8004_ACETDF <- tbl(con_solution, "sol_DWPM10530") %>%
  inner_join(tbl(con_solution, "sol_DWPM10510"), by = c("FUND_CD", "IMC_CD", "STD_DT")) %>%
  filter(
    STD_DT >= '20221005',
    FUND_CD %in%  !!c(query_fund_cd_ACETDF)
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, ITEM_CD, ITEM_NM, EVL_AMT, NAST_AMT) %>%
  collect() %>%
  filter(!(str_detect(ITEM_NM, "미지급") | str_detect(ITEM_NM, "미수"))|is.na(ITEM_NM))


#table_8004_ACETDF <- table_8004_ACETDF %>% mutate(FUND_CD = case_when(FUND_CD == "4MP80"~ "4MP80_AT", TRUE ~ FUND_CD))

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
# ecos.setKey("FWC2IZWA5YD459SQ7RJM")
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

# _1.2 SCIP DB ------------------------------------------------------------
# __1.2.1 MP 종목별 데이터 -------------------------------------------------------
con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')

tbl(con_SCIP,"back_dataset") %>%
  filter(!is.na(ISIN) | str_detect(name,"Index")) %>% 
  collect()%>% 
  mutate(colname_backtest = if_else(is.na(ISIN), name,symbol)) %>% 
  mutate(colname_backtest = if_else(grepl("^[0-9]+$", colname_backtest), name, colname_backtest))   ->Data_List

# ------ 20250620 ver ----------------------------------------------------------------------------
url_mapping = list(
  "MXWD Index"    = list("dataset_id"= as.integer(35), "dataseries_id"= as.integer(15)), # FG Price
  "KOSPI2 Index"  = list("dataset_id"= as.integer(225), "dataseries_id"= as.integer(15)), # FG Price
  "KBPMMMIN Index"= list("dataset_id"= as.integer(298), "dataseries_id"= as.integer(41)), # KAP 크롤링
  "M1EF Index"    = list("dataset_id"= as.integer(231), "dataseries_id"= as.integer(43)), # FG Net TR
  "M2WD Index"    = list("dataset_id"= as.integer(35), "dataseries_id"= as.integer(39)), # FG TR
  "M1WD Index"    = list("dataset_id"= as.integer(35), "dataseries_id"= as.integer(43)), # FG Net TR
  "LEGATRUU Index"= list("dataset_id"= as.integer(58), "dataseries_id"= as.integer(39)), # FG TR
  "KST0000T Index"= list("dataset_id"= as.integer(279), "dataseries_id"= as.integer(40)), # KIS 크롤링
  "KISABBAA- Index"= list("dataset_id"= as.integer(161), "dataseries_id"= as.integer(33)) #KIS Bond Index
)
# ------ 20250620 ver ----------------------------------------------------------------------------

url_mapping<- url_mapping %>% enframe() %>%  
  unnest_wider(col = value)

Data_List %>% filter(!is.na(ISIN)) %>% pull(id)->mp_dataid

MP_historical<- tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id %in% mp_dataid, dataseries_id==6) %>%   
  filter(timestamp_observation>="2022-10-03") %>% 
  collect()


# __1.2.1 * MSCI 성장 가치 비중 -------------------------------------------------


tbl(con_SCIP,"back_datapoint") %>%
  filter(dataseries_id == 36) %>% 
  filter(dataset_id %in% c(250,251)  ) %>%  
  collect() -> Market_Cap_GV

# __1.2.2 BM 종목별 데이터 ------------------------------------------------------

# (20250620)데이터 소스를 Bloomberg 에서 FactSet, KIS 및 KAP 크롤링 등으로 변경
# ------ 20250620 ver ----------------------------------------------------------------------------
BM_raw <- tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id %in% c(35,58,279,161)) %>% 
  filter(timestamp_observation>="2022-10-03") %>% 
  collect() %>% 
  left_join(url_mapping) %>% 
  mutate(기준일자 = ymd(timestamp_observation)) %>% 
  arrange(기준일자)

BM_from_KIS <- BM_raw %>% filter(dataset_id == 161) %>%
  mutate(data = map(.x= data, .f = ~jsonlite::parse_json((rawToChar(unlist(.x)))) )) %>% 
  mutate(data = map_chr(.x= data, .f = ~.x[[1]] ) %>% as.numeric()) %>%
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = data)

BM_from_KIS_new <- BM_raw %>% filter(dataseries_id %in% c(40, 41)) %>%
  mutate(data = map_dbl(.x= data, .f = ~as.numeric(rawToChar(unlist(.x))))) %>% 
  select(-id) %>% 
  distinct() %>% 
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = data)

BM_US <- BM_raw %>% filter(dataseries_id %in% c(39, 43)) %>%
  mutate(data = map_dbl(.x= data, .f = ~as.numeric(rawToChar(unlist(.x))))) %>% 
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = data)

if(BM_US %>% slice_tail(n = 1) %>% pull(기준일자) < 최근영업일) {
  BM_US <- BM_US %>%
    bind_rows(tibble::tibble(
      기준일자 = 최근영업일,
      !!!purrr::set_names(rep(list(NA), ncol(BM_US) - 1), names(BM_US)[-1])
    ))
}
BM_US <-BM_US %>% mutate(across(.cols = -기준일자, .fns = ~lag(.x, 1)))

BM_historical <- BM_US %>% left_join(BM_from_KIS, by = '기준일자') %>% left_join(BM_from_KIS_new, by = '기준일자')
# ------ 20250620 ver ----------------------------------------------------------------------------

BM_historical <- BM_historical %>% arrange(desc(기준일자))
is_update_failed <- FALSE #BM_historical %>% slice(1) %>%
#summarise(across(everything(), ~ any(is.na(.)))) %>% unlist() %>% any()


# __1.2.3 채권듀레이션 데이터 Loading ----

# ACETDF 추가: KODEX 국채선물
# 열 이름에 따른 dataset과 dataseries ID 매핑
bond_url_mapping = list(
  "한국 종합채권"               = list("dataset_id"= as.integer(43), "dataseries_id"= as.integer(22)),#"ACE 종합채권(AA-이상)KIS액티브"
  "한국 중장기국공채권"         = list("dataset_id"= as.integer(111), "dataseries_id"= as.integer(22)),#"ACE 중장기국공채액티브"
  "한국 3년국고채권"            = list("dataset_id"= as.integer(107), "dataseries_id"= as.integer(22)),#"ACE 국고채3년"
  "한국 10년국고채권"           = list("dataset_id"= as.integer(50), "dataseries_id"= as.integer(22)),#"ACE 국고채10년"
  "한국 10년국채선물"           = list("dataset_id"= as.integer(46), "dataseries_id" = as.integer(22)),# KODEX 국채선물10년
  "미국 하이일드채권"           = list("dataset_id"= as.integer(112), "dataseries_id"= as.integer(22)), # USHY
  "미국 물가채권"               = list("dataset_id"= as.integer(47), "dataseries_id"= as.integer(22)), #iShares TIPS Bond ETF (TIP)
  "미국 10년국고채권"           = list("dataset_id"= as.integer(354), "dataseries_id"= as.integer(22)),# ACE 미국10년국채액티브" 
  "미국 종합국채"               = list("dataset_id"= as.integer(384), "dataseries_id"= as.integer(22)) #GOVT
  # 다른 열에 대한 매핑도 추가할 수 있습니다.
)


bond_url_mapping<- bond_url_mapping %>% enframe() %>%  
  unnest_wider(col = value)

db_dataid<- bond_url_mapping$dataset_id


duration_historical<- tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id %in% db_dataid, dataseries_id ==22 ) %>%   
  collect()


#---- wrap 추가 파트----------------------------------------------------------------------------------------------
# 2. 펀드정보 매핑 -----------------------------------------------------------------

#_2.1 TDF, BF여부----
Fund_Information <-  tibble(
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth", "ACETDF2030", "ACETDF2050","ACETDF2080", "SK EMP70"),
  구분= c("TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","BF","BF","BF", "ACETDF", "ACETDF", "ACETDF", "Wrap")
  ) %>% 
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                       "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                       "ACETDF2030","ACETDF2050","ACETDF2080", "SK EMP70"   
  )))

# ACETDF 추가 실험 중
#-------------------------------------------------
Fund_Info_ACETDF <-  tibble(
  펀드설명 = c('ACETDF2025', 'ACETDF2030', 'ACETDF2035',
           'ACETDF2040', 'ACETDF2045', 'ACETDF2050', 'ACETDF2055', 'ACETDF2060', 'ACETDF2065',
           'ACETDF2070', 'ACETDF2075', 'ACETDF2080'),
  구분= rep("ACETDF",length(펀드설명))
)
# Fund_Information$펀드설명 %>% unique()
Fund_Information <- bind_rows(Fund_Information, Fund_Info_ACETDF) %>% 
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                       "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                       "ACETDF2025" ,"ACETDF2030","ACETDF2035","ACETDF2040","ACETDF2045","ACETDF2050" ,  
                                       "ACETDF2055" ,"ACETDF2060","ACETDF2065","ACETDF2070","ACETDF2075","ACETDF2080", "SK EMP70"   
  )))

Fund_Information <- Fund_Information %>% 
  filter(!(펀드설명 %in% c("ACETDF2025" ,"ACETDF2035","ACETDF2040",
                       "ACETDF2045","ACETDF2055" ,"ACETDF2060",
                       "ACETDF2065","ACETDF2070","ACETDF2075" )))
#-------------------------------------------------


#_2.2 펀드설명 및 설정일----
AP_fund_name<- tibble(
  펀드 = c("07M02",	"07J66",	"07J71",	"07J76",	"07J81",	"07J86",	"07J91",	"07J96",	"07Q93",
         "07J41",	"07J34", "07P70" ,
         "9004Q","9004R","9004S", "SKW70"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth",
           "ACETDF2030","ACETDF2050","ACETDF2080", "SK EMP70"),
  설정일 = ymd(c("2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2024-04-08",
              "2022-10-05","2022-10-05","2023-12-28",
              "2025-03-07","2025-03-07","2025-03-07", "2025-05-27"
              ))) %>%
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                                "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                                "ACETDF2030", "ACETDF2050","ACETDF2080", "SK EMP70"
           )))


VP_fund_name <- tibble(
  펀드 = c("2MP24",	"1MP30",	"1MP35",	"1MP40",	"1MP45",	"1MP50",	"1MP55",	"1MP60", "4MP80",
         "3MP01",	"3MP02", "6MP07", "4MP30", "4MP50", "4MP80_AT", "SK EMP70"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth",
           "ACETDF2030","ACETDF2050","ACETDF2080", "SK EMP70"),
  설정일 = ymd(c("2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2024-04-08",
              "2022-10-05","2022-10-05","2023-12-28",
              "2025-03-07","2025-03-07","2025-03-07", "2025-05-27"
              ))) %>%
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                       "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                       "ACETDF2030", "ACETDF2050","ACETDF2080", "SK EMP70"
  )))

# ACETDF 추가 실험 중
#-------------------------------------------------
# VP_fund_name_ACETDF <- tibble(
#   펀드 =c('4MP25', '4MP30', '4MP35', '4MP40', '4MP45', '4MP50', '4MP55', '4MP60', '4MP65',
#         '4MP70', '4MP75', '4MP80_AT'),
#   펀드설명 = c('ACETDF2025', 'ACETDF2030', 'ACETDF2035',
#            'ACETDF2040', 'ACETDF2045', 'ACETDF2050', 'ACETDF2055', 'ACETDF2060', 'ACETDF2065',
#            'ACETDF2070', 'ACETDF2075', 'ACETDF2080')) %>%
#   mutate(설정일 = case_when(펀드설명 %in% c("ACETDF2030","ACETDF2050","ACETDF2080") ~ ymd("2025-03-07"),
#                           TRUE ~ ymd("2023-05-12")))

# AP_fund_name <- bind_rows(AP_fund_name,VP_fund_name_ACETDF %>% filter(!(펀드설명%in% c("ACETDF2030","ACETDF2050","ACETDF2080")))) %>% 
#   mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
#                                        "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
#                                        "ACETDF2025" ,"ACETDF2030","ACETDF2035","ACETDF2040","ACETDF2045","ACETDF2050" ,  
#                                        "ACETDF2055" ,"ACETDF2060","ACETDF2065","ACETDF2070","ACETDF2075","ACETDF2080"   
#   ))) %>% 
#   filter(!(펀드설명 %in% c("ACETDF2025" ,"ACETDF2035","ACETDF2040",
#                        "ACETDF2045","ACETDF2055" ,"ACETDF2060",
#                        "ACETDF2065","ACETDF2070","ACETDF2075" )))

# VP_fund_name <- bind_rows(VP_fund_name,VP_fund_name_ACETDF) %>% 
#   mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
#                                        "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
#                                        "ACETDF2025" ,"ACETDF2030","ACETDF2035","ACETDF2040","ACETDF2045","ACETDF2050" ,  
#                                        "ACETDF2055" ,"ACETDF2060","ACETDF2065","ACETDF2070","ACETDF2075","ACETDF2080"   
#   ))) %>% 
#   filter(!(펀드설명 %in% c("ACETDF2025" ,"ACETDF2035","ACETDF2040",
#                        "ACETDF2045","ACETDF2055" ,"ACETDF2060",
#                        "ACETDF2065","ACETDF2070","ACETDF2075" )))

#-------------------------------------------------

# 3. 자산군 분류체계 ----------------------------------------------------------------

# ACETDF 추가: KODEX 국채선물
universe_criteria <- 
  read_csv("./00_data_updating/new_universe_criteria.csv", locale = locale(encoding = "CP949")) %>%
  distinct() %>% 
  mutate(종목코드 = if_else(종목코드=="AU000000I0Z4","AU000000IOZ4",종목코드)) %>% 
  # 23년 말 기준으로 새롭게 편입된 US 금 두 종목 존재. universe DB에 업데이트
  bind_rows(
    tribble( ~종목코드, ~종목명,~자산군_대,~자산군_중,~자산군_소,
             "AU000000I0Z4", "ISHARES CORE S&P/ASX 200 ETF", "주식", "호주 주식", "호주 주식",
             "US98149E3036", "SPDR GOLD MINISHARES TRUST" , "대체","원자재","금",  
             "US46436F1030", "ISHARES GOLD TRUST MICRO"   , "대체","원자재","금",
             "US46435U8532", "iShares Broad USD High Yield Corporate B", "채권","미국 채권","미국 하이일드채권",
             "KR7114460009", "ACE 국고채3년", "채권","한국 채권", "한국 3년국고채권",
             "KR7278540000", "KODEX MSCI Korea TR", "주식","한국 주식","한국 주식",
             "KR7114260003",	"KODEX 국고채3년","채권",	"한국 채권",	"한국 3년국고채권",
             "KR7152380002",  "KODEX 국채선물10년","채권", "한국 채권", "한국 10년국고채권",
             "KR7481430007",  "RISE 국고채10년액티브","채권", "한국 채권", "한국 10년국고채권",
             "KR7133690008",	"TIGER 미국나스닥100","주식",	"미국 주식",	"미국 성장주",
             "KR7304940000",	"KODEX 미국나스닥100선물(H)","주식",	"미국 주식","미국 성장주",
             "KR7310960000",	"TIGER 200TR", "주식",	"한국 주식",	"한국 주식",
             "KR7469150007",	"ACE AI반도체포커스", "주식",	"한국 주식",	"한국 주식",
             
             "KR7367380003",	"ACE 미국나스닥100","주식",	"미국 주식",	"미국 성장주",
             "KR7468380001",	"KODEX iShares미국하이일드액티브", "채권",	"미국 채권",	"미국 하이일드채권",
             "KR7455030007",	"KODEX 미국달러SOFR금리액티브(합성)","채권",	"미국 채권",	"미국 채권",
             "US78462F1030",  "SPDR TRUST SERIES 1", "주식", "미국 주식", "미국 주식(성장&가치 분해필요)",
             "KR7360200000",  "ACE 미국S&P500", "주식","미국 주식", "미국 주식(성장&가치 분해필요)",
             "US8085244098",  "Schwab U.S. Large-Cap Value ET","주식","미국 주식", "미국 가치주",
             "KR7105190003",  "ACE 200", "주식", "한국 주식", "한국 주식",
             "KR70085N0005", "ACE 미국10년국채액티브(H)","채권", "미국 채권", "미국 10년국고채권",
             "KR70085P0003", "ACE 미국10년국채액티브","채권", "미국 채권", "미국 10년국고채권",
             "KR70127M0006", "ACE 미국대형가치주액티브","주식",	"미국 주식",	"미국 가치주",
             "KR70127P0003", "ACE 미국대형성장주액티브","주식",	"미국 주식",	"미국 성장주",
             "KRZ502649912",	"한국투자TMF26-12만기형증권투자신탁(채권)","채권", "한국 채권", "한국 10년국고채권",
             "KRZ502649922",	"한국투자TMF28-12만기형증권투자신탁(채권)","채권", "한국 채권", "한국 10년국고채권",
             "US46429B2676", "iShares U.S. Treasury Bond ETF", "채권", "미국 채권", "미국 종합국채"
             
             
             #"1815100" , "선급외화비용","??","??","??"
             
    )
  ) %>%
  mutate(자산군_소 = factor(자산군_소, levels = c("글로벌 주식","미국 주식","미국 성장주","미국 가치주","미국 중형주",
                                          "선진국 주식","신흥국 주식","한국 주식","호주 주식","글로벌 채권",
                                          "미국 채권","미국 채권 3개월","미국 채권 2년","미국 채권 5년","미국 종합국채","미국 10년국고채권",
                                          "미국 물가채권", "미국 투자등급 회사채","미국 하이일드채권","미국외 글로벌채권","신흥국 달러채권",
                                          "한국 종합채권","한국 단기채권","한국 중장기국공채권","한국 3년국고채권","한국 10년국고채권","한국 회사채권","글로벌 원자재","금","미국 부동산","미국외 부동산","글로벌 인프라","원달러환율",
                                          "외화 유동성","원화 유동성","07J48","07J49","미국 주식(성장&가치 분해필요)"))) 

# 4. 리밸런싱내역 업데이트 -----------------------------------------------------------


sol_VP_rebalancing_inform <- tbl(con_solution,"sol_VP_rebalancing_inform") %>% collect()
sol_MP_released_inform <- tbl(con_solution,"sol_MP_released_inform") %>% collect()

rebalancing_historical<- sol_VP_rebalancing_inform %>%
  #inner_join(sol_MP_released_inform, by = join_by(펀드설명,version==Release_date,경기국면),relationship = "many-to-many") %>% 
  inner_join(sol_MP_released_inform, by = join_by(펀드설명,version==Release_date,경기국면,
                                                  for_ACE, Recalculate_date),relationship = "many-to-many") 



MP_rebalancing_historical <- 
  rebalancing_historical %>% 
  select(리밸런싱날짜,펀드설명,version,경기국면) %>% distinct() %>% 
  inner_join(sol_MP_released_inform %>% 
               filter(for_ACE ==0 | Release_date >=ymd("2025-12-29")) %>% # 2025-12-29부터는 for_ACE가 디폴트임
               distinct(), by = join_by(version == Release_date,펀드설명,경기국면),relationship = "many-to-many") %>% 
  select(리밸런싱날짜,펀드설명,경기국면,ISIN,weight,version) %>%
  filter(!(펀드설명 %in% c("ACETDF2025" ,"ACETDF2035","ACETDF2040",
                       "ACETDF2045","ACETDF2055" ,"ACETDF2060",
                       "ACETDF2065","ACETDF2070","ACETDF2075" )))

MP_LTCMA<- MP_rebalancing_historical %>% 
  arrange(리밸런싱날짜) %>% 
  left_join(universe_criteria %>%
              select(종목코드, 자산군_대,자산군_소) %>% distinct(),
            by = join_by(ISIN ==종목코드)) %>% 
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                       "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                       "ACETDF2030", "ACETDF2050", "ACETDF2080", "SK EMP70"
  ))) %>% 
  distinct()
# sol_VP_rebalancing_inform <- tbl(con_solution,"sol_VP_rebalancing_inform") %>% collect()
# sol_MP_released_inform <- tbl(con_solution,"sol_MP_released_inform") %>% collect()
# 
# MP_rebalancing_historical <- sol_VP_rebalancing_inform %>%
#   #inner_join(sol_MP_released_inform, by = join_by(펀드설명,version==Release_date,경기국면),relationship = "many-to-many") %>% 
#   inner_join(sol_MP_released_inform, by = join_by(펀드설명,version==Release_date,경기국면,
#                                                   for_ACE, Recalculate_date),relationship = "many-to-many") %>% 
#   filter(for_ACE ==0) %>% 
#   select(리밸런싱날짜,펀드설명,ISIN,weight) %>%
#   filter(!(펀드설명 %in% c("ACETDF2025" ,"ACETDF2035","ACETDF2040",
#                        "ACETDF2045","ACETDF2055" ,"ACETDF2060",
#                        "ACETDF2065","ACETDF2070","ACETDF2075" )))
# 
# MP_LTCMA<- MP_rebalancing_historical %>% 
#   arrange(리밸런싱날짜) %>% 
#   left_join(universe_criteria %>%
#               select(종목코드, 자산군_대,자산군_소) %>% distinct(),
#             by = join_by(ISIN ==종목코드)) %>% 
#   mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
#                                        "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
#                                        "ACETDF2030", "ACETDF2050", "ACETDF2080", "SK EMP70"
#   ))) 
#   # %>% 
#   # filter(!(펀드설명 %in% c("ACETDF2025" ,"ACETDF2035","ACETDF2040",
#   #                      "ACETDF2045","ACETDF2055" ,"ACETDF2060",
#   #                      "ACETDF2065","ACETDF2070","ACETDF2075" )))
# MP_rebalancing_historical$펀드설명 %>% unique()
#-------------------------------------------------

