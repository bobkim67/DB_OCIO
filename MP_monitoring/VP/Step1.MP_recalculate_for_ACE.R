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
#rm(list=ls())
source("./03_MP_monitor/Function 모듈_ACETDF_통합.R")

# 1.DB에서 데이터 Loading --------------------------------------------------------
con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')
con_solution <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'solution', host = '192.168.195.55')
tbl(con_SCIP,"back_dataset") %>%
  filter(!is.na(ISIN) | str_detect(name,"Index")) %>% 
  collect()%>% 
  mutate(colname_backtest = if_else(is.na(ISIN), name,symbol)) %>% 
  mutate(colname_backtest = if_else(grepl("^[0-9]+$", colname_backtest), name, colname_backtest))   ->Data_List


tbl(con_SCIP,"back_datapoint") %>%
  filter(dataseries_id == 36) %>% 
  filter(dataset_id %in% c(250,251)  ) %>%  
  collect() -> Market_Cap_GV

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

historical_MarketCap_GV %>% tail()

# 기존테이블에서 새로운테이블 저장할 것 추려서 저장하기 -------------------------------------------
from <- ymd("2025-08-20")
historical_position_DWPM10530 <- tbl(con_dt,"DWPM10530") %>%
  filter(STD_DT>=local(str_remove_all(from-days(1),"-")) ) %>% 
  select(ITEM_NM,ITEM_CD) %>%
  #filter(FUND_CD %in% c(local(c(query_fund_cd_list_AP,query_fund_cd_list_VP)) ) %>%
  filter(!(str_detect(ITEM_NM,"미지급")|str_detect(ITEM_NM,"미수"))) %>% distinct() %>% 
  collect() 

historical_position_DWPM10530 %>% 
  select()

sol_VP_rebalancing_inform <- tbl(con_solution,"sol_VP_rebalancing_inform") %>% collect()
sol_MP_released_inform <- tbl(con_solution,"sol_MP_released_inform") %>% collect()


# ACE Maximum 버전 ----------------------------------------------------------


passive_maximum_weight <- 0.25
active_etf_maximum_weight <- 0.18


sol_MP_released_inform %>% 
  filter(펀드설명 != "SK EMP70") %>% 
  group_by(펀드설명) %>% 
  filter(Release_date ==max(Release_date)) %>% 
  ungroup() %>%
  left_join(sol_VP_rebalancing_inform %>%
              filter(펀드설명 != "SK EMP70") %>% 
              group_by(펀드설명) %>% 
              filter(리밸런싱날짜 ==max(리밸런싱날짜 )) %>% ungroup() %>% 
              select(리밸런싱날짜,펀드설명)) %>% 
  group_by(펀드설명,경기국면,자산군_소) %>% 
  mutate(component_n = n()) %>% 
  ungroup() %>% 
  #group_by(펀드설명) %>% 
  complete(Release_date,자산군_소,펀드설명,경기국면,fill= list(weight = 0)) %>% 
  #mutate(Release_date= ymd("2025-09-01")) %>% 
  filter(!(펀드설명 != "Golden Growth" & !is.na(경기국면))) %>% 
  filter(!(펀드설명 == "Golden Growth" & is.na(경기국면))) %>% 
  filter(!is.na(ISIN)) %>% 
  left_join(historical_MarketCap_GV %>% 
              select(기준일자,성장주대가치주비중 = `미국 성장주`), by = join_by(리밸런싱날짜 == 기준일자)) %>% 
  group_by(펀드설명,경기국면) %>% 
  #complete자산군 -> 0으로 채우고 
  mutate(`미국성장주+미국가치주_S&P대체가능비중` = min( max(sum(weight[자산군_소== "미국 성장주"],-active_etf_maximum_weight), 0 )  /성장주대가치주비중,
                                        max(sum(weight[자산군_소=="미국 가치주"],-active_etf_maximum_weight),0) /(1-성장주대가치주비중))) %>% 
  # 미국가치주 없으면 그냥 나스닥100만 담으면 됨.
  mutate(`미국성장주+미국가치주비중` = sum(weight[자산군_소 %in% c("미국 성장주", "미국 가치주")])) %>%
  mutate(`ACE 미국S&P500` = min(`미국성장주+미국가치주_S&P대체가능비중`,1)) %>% 
  mutate(`ACE 미국나스닥100` = min( max(sum(weight[자산군_소 =="미국 성장주"],-active_etf_maximum_weight),0)- 성장주대가치주비중*`ACE 미국S&P500`[1],1) ) %>% 
  mutate(`ACE 종합채권` = min(sum(weight[자산군_소 =="한국 종합채권"]),1) ) %>% 
  mutate(`ACE KRX금현물` = min(sum(weight[자산군_소 =="금"]),passive_maximum_weight) ) %>% 
  mutate(`ACE 국고채10년` = min(sum(weight[자산군_소 =="한국 10년국고채권"]),1) ) %>% 
  filter(weight!=0) %>% 
  #group_by(펀드설명,경기국면) %>% 
  mutate(weight_post = case_when(자산군_소 == "미국 성장주" ~ weight-`ACE 미국S&P500`*성장주대가치주비중/component_n -`ACE 미국나스닥100`/component_n,
                                 자산군_소 == "미국 가치주" ~ weight-`ACE 미국S&P500`*(1-성장주대가치주비중)/component_n ,
                                 자산군_소 == "한국 종합채권" ~ weight-`ACE 종합채권`/component_n ,
                                 자산군_소 == "금" ~ weight-`ACE KRX금현물`/component_n ,
                                 자산군_소 == "한국 10년국고채권" ~ (sum(weight[자산군_소== "한국 10년국고채권"])-`ACE 국고채10년`)/(component_n-1) ,
                                 TRUE ~ weight
  ) ,.after = weight) %>% 
  
  ungroup()->temp_maximum

temp_maximum %>% select(Release_date,펀드설명,자산군_소,ISIN,weight ,weight_post,경기국면,리밸런싱날짜) %>% 
  bind_rows(temp_maximum %>% 
              select(펀드설명,경기국면,contains("ACE"),리밸런싱날짜) %>%  distinct() %>% 
              pivot_longer(cols = contains("ACE"),names_to = "ISIN", values_to = "weight_post") 
            
  ) %>% 
  mutate(weight = coalesce(weight,0)) %>% 
  mutate(weight_post = round(coalesce(weight_post,0),10) ) %>% 
  left_join(historical_position_DWPM10530,by = join_by(ISIN == ITEM_CD)) -> prepped_for비중변화기록_maximum



prepped_for비중변화기록_maximum %>%
  group_by(펀드설명) %>% 
  fill(Release_date,.direction = "downup") %>% 
  ungroup() %>% 
  mutate(자산군_소 = case_when(ISIN =="ACE 미국나스닥100" ~ "미국 성장주",
                           ISIN =="ACE 미국S&P500" ~ "미국 성장주/미국 가치주",
                           ISIN =="ACE 종합채권" ~ "한국 종합채권",
                           ISIN =="ACE KRX금현물" ~ "금",
                           ISIN =="ACE 국고채10년" ~ "한국 10년국고채권",
                           
                           TRUE ~ 자산군_소
  )) %>% 
  mutate(ISIN = case_when(ISIN =="ACE 미국나스닥100" ~ "KR7367380003",
                          ISIN =="ACE 미국S&P500" ~ "KR7360200000",
                          ISIN =="ACE 종합채권" ~ "KR7356540005",
                          ISIN =="ACE KRX금현물" ~ "KR7411060007",
                          ISIN =="ACE 국고채10년" ~ "KR7365780006",
                          TRUE ~ ISIN
  )) %>% 
  group_by(펀드설명,ISIN,경기국면) %>% 
  reframe(Release_date = Release_date[1],
          자산군_소 = 자산군_소[1],
          ISIN = ISIN[1],
          weight = weight[1],
          weight_post = weight_post[n()],
          리밸런싱날짜 = 리밸런싱날짜[1]
  ) %>% 
  filter(weight_post >=0.00001) %>% 
  bind_rows(prepped_for비중변화기록_maximum %>% 
              filter(weight_post ==0 & !str_detect(ITEM_NM,"ACE")) %>% 
              select(-ITEM_NM)) %>% 
  # bind_rows(prepped_for비중변화기록 %>% 
  #             filter(ISIN %in% c("KR7152380002","US78463V1070")) %>% 
  #             mutate(weight_post = 0)) %>% 
  left_join(historical_position_DWPM10530,by = join_by(ISIN == ITEM_CD)) %>% 
  relocate(Release_date,.before = 펀드설명) %>% 
  arrange(펀드설명,경기국면,자산군_소,weight) %>%
  filter(weight+weight_post !=0 )->almost_finish_maximum

# almost_finish_maximum %>% 
#   group_by(펀드설명) %>% 
#   #filter(round(sum(weight),5)!=1 ) %>% view()
#   reframe(weight = sum(weight),
#           weight_post = sum(weight_post)) %>% view()

almost_finish_maximum %>% 
  filter(weight_post !=0) %>% 
  select(-weight) %>% 
  rename(weight= weight_post) %>% 
  mutate(Portfolio = if_else(!is.na(경기국면),paste0(펀드설명,"_",경기국면), 펀드설명)) %>% 
  #rename(리밸런싱날짜 = Release_date) %>% 
  left_join(Data_List %>% select(dataset_id=id, ISIN)) %>% 
  mutate(dataseries_id = 6,
         region = case_when(str_sub(ISIN,1,2) == "US" ~ "US",
                            TRUE ~ "KR"),
         hedge_ratio = 0,
         cost_adjust = 0, 
         tracking_multiple= 1) %>% 
  select(리밸런싱날짜,Portfolio,dataset_id,dataseries_id,region,weight,hedge_ratio,cost_adjust,tracking_multiple) %>% 
  clipr::write_clip()


almost_finish_maximum %>% 
  writexl::write_xlsx("펀드별_ACEMP_최근리밸런싱날짜기준.xlsx")


res<- clipr::read_clip_tbl() %>% tibble()

res %>% 
  left_join(almost_finish_maximum %>% select(ISIN,ITEM_NM,자산군_소) %>% distinct()) %>% writexl::write_xlsx("펀드별_ACEMP의_20250915기준_VP.xlsx")

res %>% 
  left_join(almost_finish_maximum %>% select(ISIN,ITEM_NM,자산군_소) %>% distinct()) %>%
  filter(Portfolio == "MS GROWTH") %>% 
  group_by(자산군_소) %>% 
  reframe(s= sum(weight))

# 새로운 MP db에 업데이트 ---------------------------------------------------------

sol_MP_released_inform

almost_finish_maximum %>% 
  filter(weight_post !=0) %>% 
  #filter(펀드설명 %in% c())
  mutate(Recalculate_date = 리밸런싱날짜) %>% 
  select(-weight,-리밸런싱날짜,-ITEM_NM) %>% 
  rename(weight= weight_post) %>% 
  mutate(for_ACE = TRUE) -> recalculated_MP



dbWriteTable(con_solution,
             name = "sol_MP_released_inform",
             value = recalculated_MP,
             append = TRUE,row.names = FALSE)


# 2. 원하는 DELETE 쿼리 실행
# for_ACE가 TRUE(1)인 행을 삭제
delete_query <- "DELETE FROM solution.sol_MP_released_inform WHERE for_ACE = TRUE;" 
# 참고: for_ACE != 0, for_ACE = 1, for_ACE = TRUE 모두 MySQL에서는 동일하게 작동합니다.
# TRUE가 의미상 더 명확해서 추천합니다.

#affected_rows <- dbExecute(con_solution, delete_query)
# 