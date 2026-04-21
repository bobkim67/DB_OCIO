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
                        '07J91', '07J96', '07J41', '07J34', '2MP24', '1MP30', 
                        '1MP35', '1MP40', '1MP45', '1MP50', '1MP55', '1MP60', 
                        '3MP01', '3MP02', '07J48', '07J49', 
                        '07P70', '6MP07', '07Q93', '4MP80')

query_fund_cd_ACETDF <- c('4MP25', '4MP30', '4MP35',
                          '4MP40', '4MP45', '4MP50', '4MP55', '4MP60', '4MP65',
                          '4MP70', '4MP75', '4MP80')
# query_fund_cd_list <- c(query_fund_cd_list,query_fund_cd_ACETDF)


# Query 8183 using dplyr
table_8183 <- tbl(con_dt, "DWPM10510") %>%
  inner_join(tbl(con_dt, "DWPI10011"), by = c("FUND_CD", "IMC_CD")) %>%
  filter(
    STD_DT >= '20221004',
    FUND_CD %in% !!c(query_fund_cd_list,query_fund_cd_ACETDF)
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, FUND_NM , MOD_STPR) %>%
  collect()

table_8183_ACETDF <- table_8183 %>% filter( FUND_CD %in% !! query_fund_cd_ACETDF)
table_8183_ACETDF <- table_8183_ACETDF %>% mutate(FUND_CD = case_when(FUND_CD == "4MP80"~ "4MP80_AT", TRUE ~ FUND_CD))

table_8183 <- table_8183 %>% filter(FUND_CD %in% !!query_fund_cd_list)

#ACETDF 추가 실험 중
#--------------------------------------------------------
# query_fund_cd_ACETDF <- c('4MP25', '4MP30', '4MP35',
#                           '4MP40', '4MP45', '4MP50', '4MP55', '4MP60', '4MP65',
#                           '4MP70', '4MP75', '4MP80')
# 
# table_8183_ACETDF <- tbl(con_dt, "DWPM10510") %>%
#   inner_join(tbl(con_dt, "DWPI10011"), by = c("FUND_CD", "IMC_CD")) %>%
#   filter(
#     STD_DT >= '20221004',
#     FUND_CD %in% !!query_fund_cd_ACETDF
#   ) %>%
#   select(STD_DT, IMC_CD, FUND_CD, FUND_NM , MOD_STPR) %>%
#   collect()
# 
# table_8183_ACETDF <- table_8183_ACETDF %>% mutate(FUND_CD = case_when(FUND_CD == "4MP80"~ "4MP80_AT", TRUE ~ FUND_CD))
# table_8183 <- bind_rows(table_8183,table_8183_ACETDF)

#--------------------------------------------------------


# __1.1.3 펀드정보_명세부 ------------------------------------------------------------------
# Query 8004 using dplyr
table_8004 <- tbl(con_dt, "DWPM10530") %>%
  inner_join(tbl(con_dt, "DWPM10510"), by = c("FUND_CD", "IMC_CD", "STD_DT")) %>%
  filter(
    STD_DT >= '20221005',
    FUND_CD %in%  !!c(query_fund_cd_list,query_fund_cd_ACETDF)
  ) %>%
  select(STD_DT, IMC_CD, FUND_CD, ITEM_CD, ITEM_NM, EVL_AMT, NAST_AMT) %>%
  collect() %>%
  filter(!(str_detect(ITEM_NM, "미지급") | str_detect(ITEM_NM, "미수")))

table_8004_ACETDF <- table_8004 %>% filter(FUND_CD %in% query_fund_cd_ACETDF)
table_8004_ACETDF <- table_8004_ACETDF %>% mutate(FUND_CD = case_when(FUND_CD == "4MP80"~ "4MP80_AT", TRUE ~ FUND_CD))

table_8004 <- table_8004 %>% filter(FUND_CD %in% query_fund_cd_list)

#ACETDF 추가 실험 중
#--------------------------------------------------------
# table_8004_ACETDF <- tbl(con_dt, "DWPM10530") %>%
#   inner_join(tbl(con_dt, "DWPM10510"), by = c("FUND_CD", "IMC_CD", "STD_DT")) %>%
#   filter(FUND_CD %in%  !!query_fund_cd_ACETDF) %>%
#   select(STD_DT, IMC_CD, FUND_CD, ITEM_CD, ITEM_NM, EVL_AMT, NAST_AMT) %>%
#   collect() %>%
#   filter(!(str_detect(ITEM_NM, "미지급") | str_detect(ITEM_NM, "미수")))
# 
# table_8004_ACETDF <- table_8004_ACETDF %>% mutate(FUND_CD = case_when(FUND_CD == "4MP80"~ "4MP80_AT", TRUE ~ FUND_CD))
# table_8004 <- bind_rows(table_8004,table_8004_ACETDF)
#--------------------------------------------------------

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


url_mapping = list(
  "MXWD Index"    = list("dataset_id"= as.integer(35), "dataseries_id"= as.integer(9)), #Bloomberg
  "KOSPI2 Index"  = list("dataset_id"= as.integer(145), "dataseries_id"= as.integer(9)), #Bloomberg
  "KBPMMMIN Index"= list("dataset_id"= as.integer(146), "dataseries_id"= as.integer(9)), #Bloomberg
  "M1EF Index"    = list("dataset_id"= as.integer(147), "dataseries_id"= as.integer(9)), #Bloomberg
  "M2WD Index"    = list("dataset_id"= as.integer(57), "dataseries_id"= as.integer(9)), #Bloomberg
  "M1WD Index"    = list("dataset_id"= as.integer(260), "dataseries_id"= as.integer(9)), #Bloomberg
  "LEGATRUU Index"= list("dataset_id"= as.integer(58), "dataseries_id"= as.integer(9)), #Bloomberg
  "KST0000T Index"= list("dataset_id"= as.integer(59), "dataseries_id"= as.integer(9)), #Bloomberg
  "KISABBAA- Index"= list("dataset_id"= as.integer(161), "dataseries_id"= as.integer(33)), #KIS Bond Index
  "US9229087369"  = list("dataset_id"= as.integer(11), "dataseries_id" = as.integer(6)),
  "US9229087443"  = list("dataset_id"= as.integer(12), "dataseries_id" = as.integer(6)),
  "US9219438580"  = list("dataset_id"= as.integer(36), "dataseries_id" = as.integer(6)),
  "US9220428588"  = list("dataset_id"= as.integer(37), "dataseries_id" = as.integer(6)),
  "US4642861037"  = list("dataset_id"= as.integer(38), "dataseries_id" = as.integer(6)),
  "US9229085538"  = list("dataset_id"= as.integer(15), "dataseries_id" = as.integer(6)),
  "US9220426764"  = list("dataset_id"= as.integer(39), "dataseries_id" = as.integer(6)),
  "US78463X8552"  = list("dataset_id"= as.integer(40), "dataseries_id" = as.integer(6)),
  "US46090F1003"  = list("dataset_id"= as.integer(41), "dataseries_id" = as.integer(6)),
  "KR7273130005"  = list("dataset_id"= as.integer(42), "dataseries_id" = as.integer(6)),
  "KR7356540005"  = list("dataset_id"= as.integer(43), "dataseries_id" = as.integer(6)),
  "KR7385540000"  = list("dataset_id"= as.integer(44), "dataseries_id" = as.integer(6)),
  "KR7385550009"  = list("dataset_id"= as.integer(45), "dataseries_id" = as.integer(6)),
  "KR7152380002"  = list("dataset_id"= as.integer(46), "dataseries_id" = as.integer(6)),# KODEX 국채선물10년
  "US4642871762"  = list("dataset_id"= as.integer(47), "dataseries_id" = as.integer(6)),
  "KR7332500008"  = list("dataset_id"= as.integer(48), "dataseries_id" = as.integer(6)),
  "US78468R6229"  = list("dataset_id"= as.integer(49), "dataseries_id" = as.integer(6)),
  "KR7365780006"  = list("dataset_id"= as.integer(50), "dataseries_id" = as.integer(6)),
  "KR7438570004"  = list("dataset_id"= as.integer(51), "dataseries_id" = as.integer(6)),
  "KR7471230003"  = list("dataset_id"= as.integer(52), "dataseries_id" = as.integer(6)),
  "US78463V1070"  = list("dataset_id"= as.integer(53), "dataseries_id" = as.integer(6)),
  "KR7411060007"  = list("dataset_id"= as.integer(54), "dataseries_id" = as.integer(6)),
  "US98149E3036"  = list("dataset_id"= as.integer(55), "dataseries_id" = as.integer(6)),
  "US46436F1030"  = list("dataset_id"= as.integer(56), "dataseries_id" = as.integer(6)),
  "KR7278540000" = list("dataset_id"= as.integer(106), "dataseries_id" = as.integer(6)),# KODEX MSCI TR
  "KR7114460009" = list("dataset_id"= as.integer(107), "dataseries_id" = as.integer(6)),# ACE국고채3년
  "AU000000I0Z4" = list("dataset_id"= as.integer(118), "dataseries_id" = as.integer(6)),# AUD로 계산
  "KR7272570003" = list("dataset_id"= as.integer(119), "dataseries_id" = as.integer(6)),
  "US4642877397" = list("dataset_id"= as.integer(120), "dataseries_id" = as.integer(6)),
  "US8085247067" = list("dataset_id"= as.integer(121), "dataseries_id" = as.integer(6)),
  "KR7190620005" = list("dataset_id"= as.integer(122), "dataseries_id" = as.integer(6)),
  "KR7440640001" = list("dataset_id"= as.integer(123), "dataseries_id" = as.integer(6)),
  "KR7438330003" = list("dataset_id"= as.integer(124), "dataseries_id" = as.integer(6)),
  "KR7448880005" = list("dataset_id"= as.integer(125), "dataseries_id" = as.integer(6)),
  "KR7461270001" = list("dataset_id"= as.integer(126), "dataseries_id" = as.integer(6)),
  "KR7133690008" = list("dataset_id"= as.integer(127), "dataseries_id" = as.integer(6)),
  "KR7304940000" = list("dataset_id"= as.integer(128), "dataseries_id" = as.integer(6)),
  "KR7310960000" = list("dataset_id"= as.integer(129), "dataseries_id" = as.integer(6)),
  "KR7367380003" = list("dataset_id"= as.integer(130), "dataseries_id" = as.integer(6)),
  "KR7468380001" = list("dataset_id"= as.integer(131), "dataseries_id" = as.integer(6)),
  "KR7455030007" = list("dataset_id"= as.integer(132), "dataseries_id" = as.integer(6)),
  "KR7272910001" = list("dataset_id"= as.integer(111), "dataseries_id" = as.integer(6)),
  "US46435U8532" = list("dataset_id"= as.integer(112), "dataseries_id" = as.integer(6)),
  "US78462F1030" = list("dataset_id"= as.integer(24), "dataseries_id" = as.integer(6)),
  "US46434V6478" = list("dataset_id"= as.integer(136), "dataseries_id" = as.integer(6)),
  "US78464A4094" = list("dataset_id"= as.integer(114), "dataseries_id" = as.integer(6)),
  "US4642875987" = list("dataset_id"= as.integer(117), "dataseries_id" = as.integer(6)),
  "US4642876142" = list("dataset_id"= as.integer(115), "dataseries_id" = as.integer(6)),
  "US78464A5083" = list("dataset_id"= as.integer(116), "dataseries_id" = as.integer(6)),
  "KR7114260003" = list("dataset_id"= as.integer(82), "dataseries_id" = as.integer(6))
  
)
url_mapping<- url_mapping %>% enframe() %>%  
  unnest_wider(col = value)

mp_dataid<- url_mapping %>% 
  filter(dataseries_id==6) %>% pull(dataset_id)

MP_historical<- tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id %in% mp_dataid,dataseries_id==6) %>%   
  filter(timestamp_observation>="2022-10-03") %>% 
  collect()


# __1.2.2 BM 종목별 데이터 ------------------------------------------------------

# ACETDF 추가 실험 중
BM_raw <- tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id %in% c(57:59,161,260)) %>% 
  filter(timestamp_observation>="2022-10-03") %>% 
  collect() %>% 
  left_join(url_mapping) %>% 
  mutate(기준일자 = ymd(timestamp_observation)) %>% 
  arrange(기준일자)

BM_from_BB <- BM_raw %>% filter(dataset_id %in% c(57:59,260)) %>%
  mutate(data = map_dbl(.x= data, .f = ~as.numeric(rawToChar(unlist(.x))))) %>% 
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = data) %>%  
  mutate(across(.cols = c(2,3,5), .fns = ~lag(.x ,n=1)))

BM_from_KIS <- BM_raw %>% filter(dataset_id == 161) %>%
  mutate(data = map(.x= data, .f = ~jsonlite::parse_json((rawToChar(unlist(.x)))) )) %>% 
  mutate(data = map_chr(.x= data, .f = ~.x[[1]] ) %>% as.numeric()) %>%
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = data)

BM_historical <- BM_from_BB %>% left_join(BM_from_KIS, by = '기준일자')

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
           "MS STABLE",	"MS GROWTH","Golden Growth"),
  구분= c("TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","BF","BF","BF")
)

# ACETDF 추가 실험 중
#-------------------------------------------------
Fund_Info_ACETDF <-  tibble(
  펀드설명 = c('ACETDF2025', 'ACETDF2030', 'ACETDF2035',
           'ACETDF2040', 'ACETDF2045', 'ACETDF2050', 'ACETDF2055', 'ACETDF2060', 'ACETDF2065',
           'ACETDF2070', 'ACETDF2075', 'ACETDF2080'),
  구분= rep("ACE TDF",length(펀드설명))
)
Fund_Information$펀드설명 %>% unique()
Fund_Information <- bind_rows(Fund_Information, Fund_Info_ACETDF) %>% 
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                       "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                       "ACETDF2025" ,"ACETDF2030","ACETDF2035","ACETDF2040","ACETDF2045","ACETDF2050" ,  
                                       "ACETDF2055" ,"ACETDF2060","ACETDF2065","ACETDF2070","ACETDF2075","ACETDF2080"   
                                       )))
#-------------------------------------------------

#_2.2 펀드설명 및 설정일----
AP_fund_name<- tibble(
  펀드 = c("07M02",	"07J66",	"07J71",	"07J76",	"07J81",	"07J86",	"07J91",	"07J96",	"07Q93",
         "07J41",	"07J34", "07P70" ),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  설정일 = ymd(c("2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2024-04-08",
              "2022-10-05","2022-10-05","2023-12-28"))) 


VP_fund_name<- tibble(
  펀드 = c("2MP24",	"1MP30",	"1MP35",	"1MP40",	"1MP45",	"1MP50",	"1MP55",	"1MP60", "4MP80",
         "3MP01",	"3MP02", "6MP07" ),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  설정일 = ymd(c("2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2022-10-05","2024-04-08",
              "2022-10-05","2022-10-05","2023-12-28"))) 

# ACETDF 추가 실험 중
#-------------------------------------------------
VP_fund_name_ACETDF <- tibble(
  펀드 =c('4MP25', '4MP30', '4MP35', '4MP40', '4MP45', '4MP50', '4MP55', '4MP60', '4MP65',
        '4MP70', '4MP75', '4MP80_AT'),
  펀드설명 = c('ACETDF2025', 'ACETDF2030', 'ACETDF2035',
           'ACETDF2040', 'ACETDF2045', 'ACETDF2050', 'ACETDF2055', 'ACETDF2060', 'ACETDF2065',
           'ACETDF2070', 'ACETDF2075', 'ACETDF2080'),
  설정일 = ymd(rep("2023-05-12",length(펀드)))
)

AP_fund_name <- bind_rows(AP_fund_name,VP_fund_name_ACETDF) %>% 
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                       "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                       "ACETDF2025" ,"ACETDF2030","ACETDF2035","ACETDF2040","ACETDF2045","ACETDF2050" ,  
                                       "ACETDF2055" ,"ACETDF2060","ACETDF2065","ACETDF2070","ACETDF2075","ACETDF2080"   
  )))
VP_fund_name <- bind_rows(VP_fund_name,VP_fund_name_ACETDF) %>% 
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                       "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                       "ACETDF2025" ,"ACETDF2030","ACETDF2035","ACETDF2040","ACETDF2045","ACETDF2050" ,  
                                       "ACETDF2055" ,"ACETDF2060","ACETDF2065","ACETDF2070","ACETDF2075","ACETDF2080"   
  )))
#-------------------------------------------------

# 3. 자산군 분류체계 ----------------------------------------------------------------

# ACETDF 추가: KODEX 국채선물
universe_criteria <- 
  read_csv("./00_data_updating/new_universe_criteria.csv", locale = locale(encoding = "CP949")) %>%
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
             "KR7152380002",  "KODEX 국채선물10년","채권", "한국 채권", "한국 10년국고채권",
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

# 4. 리밸런싱내역 업데이트 -----------------------------------------------------------


MP_LTCMA<- bind_rows(
  read_csv("./00_data_updating/rebalancing/rebalancing_20221005.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") ,
  read_csv("./00_data_updating/rebalancing/rebalancing_20231129.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") ,
  read_csv("./00_data_updating/rebalancing/rebalancing_20231226.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") ,
  read_csv("./00_data_updating/rebalancing/rebalancing_20231229.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") 
  
) %>% 
  group_by(펀드설명) %>% 
  mutate(설정일 = min(리밸런싱날짜)) %>% 
  ungroup()
#_수시 리밸런싱 반영(LTCMA 변경, 경기국면 등)----

MP_LTCMA<- 
  MP_LTCMA %>%
  #reframe(daily_weight_MP = sum(weight)) %>% 
  filter(!(펀드설명 =="TDF2030"&리밸런싱날짜 =="2023-12-26")) %>% 
  bind_rows(
    
    
    tribble(
      ~"리밸런싱날짜", ~"펀드설명", ~"ISIN",~"weight",
      "2023-12-26" ,  "TDF2030",  "US9229087369", 0.189492 ,
      "2023-12-26" ,  "TDF2030",  "US98149E3036", 0.018949,
      "2023-12-26" ,  "TDF2030",  "US9229087443", 0.132528 ,
      "2023-12-26" ,  "TDF2030",  "US9219438580", 0.063835,
      "2023-12-26" ,  "TDF2030",  "US9220428588", 0.040151,
      "2023-12-26" ,  "TDF2030",  "KR7273130005", 0.500070/3 ,
      "2023-12-26" ,  "TDF2030",  "KR7356540005", 0.500070/3 ,
      "2023-12-26" ,  "TDF2030",  "KR7385540000", 0.500070/3 ,
      "2023-12-26" ,  "TDF2030",  "KR7152380002", 0.054975,
      # 골든그로스 둔화국면
      "2023-12-28" ,  "Golden Growth", "US9229087369"   ,0.369361 ,
      "2023-12-28" ,  "Golden Growth", "KR7278540000"  ,0.054345 ,
      "2023-12-28" ,  "Golden Growth", "US78468R6229" ,0.070000 ,
      "2023-12-28" ,  "Golden Growth", "KR7114460009" ,0.265768 ,
      "2023-12-28" ,  "Golden Growth", "KR7365780006"  ,0.066669 ,
      "2023-12-28" ,  "Golden Growth", "US78463V1070"  ,0.173857 ,
      # 골든그로스 팽창국면      
      "2024-01-26" ,  "Golden Growth", "US9229087369"   ,0.3977 ,
      "2024-01-26" ,  "Golden Growth", "KR7278540000"  ,0.0571 ,
      "2024-01-26" ,  "Golden Growth", "US78468R6229" ,0.070000 ,
      "2024-01-26" ,  "Golden Growth", "KR7114460009" ,0.1953 ,
      "2024-01-26" ,  "Golden Growth", "KR7365780006"  ,0.0938 ,
      "2024-01-26" ,  "Golden Growth", "US78463V1070"  ,0.1861 ,
      
      # 골든그로스 둔화국면
      "2024-07-05" ,  "Golden Growth", "US9229087369"   ,0.369361 ,
      "2024-07-05" ,  "Golden Growth", "KR7278540000"  ,0.054345 ,
      "2024-07-05" ,  "Golden Growth", "US78468R6229" ,0.070000 ,
      "2024-07-05" ,  "Golden Growth", "KR7114460009" ,0.265768 ,
      "2024-07-05" ,  "Golden Growth", "KR7365780006"  ,0.066669 ,
      "2024-07-05" ,  "Golden Growth", "US78463V1070"  ,0.173857 ,
      
      # 골드2080 신규상장
      "2024-04-08" ,  "TDF2080",  "US9229087369", 0.422077835 ,
      "2024-04-08" ,  "TDF2080",  "US78463V1070", 0.140692612,
      "2024-04-08" ,  "TDF2080",  "US9229087443", 0.307379033 ,
      "2024-04-08" ,  "TDF2080",  "US9219438580", 0.030518196,
      "2024-04-08" ,  "TDF2080",  "US9220428588", 0.089332324,
      "2024-04-08" ,  "TDF2080",  "KR7356540005", 0.004638298 ,
      "2024-04-08" ,  "TDF2080",  "KR7152380002", 0.005361702,
      # 골든그로스 팽창국면 
      "2024-11-08" ,  "Golden Growth", "US9229087369"   ,0.3977 ,
      "2024-11-08" ,  "Golden Growth", "KR7278540000"  ,0.0571 ,
      "2024-11-08" ,  "Golden Growth", "US78468R6229" ,0.070000 ,
      "2024-11-08" ,  "Golden Growth", "KR7114460009" ,0.1953 ,
      "2024-11-08" ,  "Golden Growth", "KR7365780006"  ,0.0938 ,
      "2024-11-08" ,  "Golden Growth", "US78463V1070"  ,0.1861 
      
    ) %>% 
      mutate(리밸런싱날짜 = ymd(리밸런싱날짜)) %>% 
      mutate(설정일 = ymd("2022-10-05"))
  ) %>%
  arrange(리밸런싱날짜) %>% 
  left_join(universe_criteria %>%
              select(종목코드, 자산군_대,자산군_소) %>% distinct(),
            by = join_by(ISIN ==종목코드))


# ACETDF 추가 실험 중
#-------------------------------------------------
MP_LTCMA_ACETDF <- read_csv("./00_data_updating/rebalancing/rebalancing_ACETDF_inform.csv",locale = locale(encoding = "CP949")) %>%
    mutate(펀드설명=str_replace_all(펀드설명,"_",""))%>% 
  group_by(펀드설명) %>% 
  mutate(설정일 = min(리밸런싱날짜)) %>% 
  ungroup() %>% arrange(리밸런싱날짜)

MP_LTCMA <- bind_rows(MP_LTCMA,MP_LTCMA_ACETDF) %>% 
  mutate(펀드설명 = factor(펀드설명, levels =c("Golden Growth","MS GROWTH","MS STABLE",
                                       "TIF", "TDF2030","TDF2035","TDF2040","TDF2045","TDF2050","TDF2055","TDF2060","TDF2080",
                                       "ACETDF2025" ,"ACETDF2030","ACETDF2035","ACETDF2040","ACETDF2045","ACETDF2050" ,  
                                       "ACETDF2055" ,"ACETDF2060","ACETDF2065","ACETDF2070","ACETDF2075","ACETDF2080"   
  )))

#-------------------------------------------------