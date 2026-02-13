library(tidyverse)
library(scales)
library(DBI)
library(RMariaDB) 
library(lubridate)



con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')
con_solution <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'solution', host = '192.168.195.55')

tbl(con_SCIP,"back_dataset") %>%
  filter(!is.na(ISIN) | str_detect(name,"Index")) %>% 
  collect()%>% 
  mutate(colname_backtest = if_else(is.na(ISIN), name,symbol)) %>% 
  mutate(colname_backtest = if_else(grepl("^[0-9]+$", colname_backtest), name, colname_backtest))   ->Data_List


historical_MP_released<- tbl(con_solution,"sol_MP_released_inform") %>% collect()

historical_VP_inform<- tbl(con_solution,"sol_VP_rebalancing_inform") %>% collect()

# 템플릿 ---------------------------------------------------------------------

# 템플릿(ACE) ---------------------------------------------------------------------
historical_VP_inform %>% 
  filter(str_detect(펀드설명,"ACE") |str_detect(펀드설명,"2080") ) %>% 
  filter(version == max( version)) %>% 
  filter(리밸런싱날짜  == max( 리밸런싱날짜 )) %>% 
  #리밸런싱날짜 및 경기국면 반영
  mutate(리밸런싱날짜= ymd(today()),.before = 펀드설명) %>%
  mutate(rebalancing_reason = "수시-괴리율",
         경기국면 = NA) ->reb_data

# 템플릿(Golend Growth) ---------------------------------------------------------------------
historical_VP_inform %>% 
  filter(str_detect(펀드설명,"Golden")  )%>% 
  filter(version == max( version)) %>% 
  filter(리밸런싱날짜 == max(리밸런싱날짜)) %>% 
  #리밸런싱날짜 및 경기국면 반영
  mutate(리밸런싱날짜= ymd(today()),.before = 펀드설명) %>%
  mutate(rebalancing_reason = "수시-괴리율",
         경기국면 = 1) ->reb_data # 경기국면 4사분면중 어디 위치하는지 업데이트 1 팽창, 2 회복 3 침체 4 둔화

# 템플릿(MySuper) ---------------------------------------------------------------------
historical_VP_inform %>% 
  filter(str_detect(펀드설명,"MS")) %>% 
  filter(version == max( version)) %>%  
  filter(리밸런싱날짜 == max(리밸런싱날짜)) %>% 
  #리밸런싱날짜 및 경기국면 반영
  mutate(리밸런싱날짜= ymd(today()),.before = 펀드설명) %>%
  mutate(rebalancing_reason = "수시-괴리율",
         경기국면 = NA) ->reb_data

# 템플릿(TIF) ---------------------------------------------------------------------
historical_VP_inform %>% 
  filter(str_detect(펀드설명,"TIF")) %>% 
  filter(version == max( version)) %>%  
  filter(리밸런싱날짜 == max(리밸런싱날짜)) %>% 
  #리밸런싱날짜 및 경기국면 반영
  mutate(리밸런싱날짜= ymd(today()),.before = 펀드설명) %>%
  mutate(rebalancing_reason = "수시-괴리율",
         경기국면 = NA) ->reb_data



# 전체포트 --------------------------------------------------------------------

historical_VP_inform %>% 
  filter(펀드설명 != "SK EMP70") %>% 
  group_by(펀드설명) %>% 
  filter(version == max( version)) %>% 
  filter(리밸런싱날짜 == max(리밸런싱날짜)) %>% 
    #리밸런싱날짜 및 경기국면 반영
    mutate(Recalculate_date= 리밸런싱날짜,.before = 펀드설명) %>%
    mutate(리밸런싱날짜 = today(),
           port = "VP",
           rebalancing_reason = "ETF교체(to ACE)",
           for_ACE = 1,
           경기국면 = 경기국면) %>% 
  ungroup()->reb_data



dbWriteTable(con_solution,
             name = "sol_VP_rebalancing_inform",
             value =  reb_data,
             append = TRUE,
             row.names = FALSE)



# 특정행 제거 ------------------------------------------------------------------

historical_VP_inform %>% 
  filter(리밸런싱날짜 ==today())

# 사용할 변수 정의

rebal_date <- '2025-09-12'

# 여러 조건을 사용하는 SQL DELETE 쿼리
sql_query <- "DELETE FROM sol_VP_rebalancing_inform WHERE 리밸런싱날짜 = ?"

# 쿼리 실행 (파라미터 순서가 중요합니다)
dbExecute(con_solution, sql_query, params = list(rebal_date))

cat("조건에 맞는 행들이 삭제되었습니다.\n")


