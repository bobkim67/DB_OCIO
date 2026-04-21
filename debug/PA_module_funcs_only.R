library(tidyverse)


library(scales)

library(rlang) # sym() 함수를 사용하기 위해 필요
library(DBI)
library(RMariaDB) # 또는 library(RMySQL)
library(lubridate)
library(blob)
library(fuzzyjoin)   # install.packages("fuzzyjoin") 필요

#source("04_사후분석/data_OCIO_universe_GENERAL.R")
#fund_cd="08K88"; start_date="20241101";end_date="20241130"
library(tidyverse)


library(scales)

library(rlang) # sym() 함수를 사용하기 위해 필요
library(DBI)
library(RMariaDB) # 또는 library(RMySQL)
library(lubridate)
library(blob)
library(fuzzyjoin)   # install.packages("fuzzyjoin") 필요

#source("04_사후분석/data_OCIO_universe_GENERAL.R")
#fund_cd="08K88"; start_date="20241101";end_date="20241130"

get_PA_source_data <- function(fund_cd, start_date,end_date){
  start_date <- start_date- days(1) # T-1 weight가 필요하기 때문이다.
  start_date<- str_remove_all(start_date,"-")
  end_date<- str_remove_all(end_date,"-")
  
  con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
  
  tbl(con_dt,"MA000410") %>% 
    filter(pr_date>=!!start_date) %>% 
    filter(pr_date<=!!end_date) %>% 
    filter(fund_id == !!fund_cd) %>% 
    collect() %>% 
    mutate(pr_date = ymd(pr_date))->PA_history_data 
  
  # SELECT * FROM dt.MA000410
  # where fund_id = '07G04'
  # and sec_id = 'GBM101642001' 등등 이상한 관측값들이 계속 껴있어서 필터링하는 로직 추가
  
  PA_history_data  %>% 
    group_by(sec_id) %>% 
    reframe(error_sec = sum(abs(amt))) %>% 
    filter(error_sec==0) %>% pull(sec_id )-> error_sec
  
  PA_history_data %>% 
    filter( !(sec_id %in% error_sec)) %>% 
    arrange(pr_date)->PA_history_data
  
  return(PA_history_data)
}

get_fund_inform_data <-function(fund_cd , start_date, end_date){
  options(digits = 15) #이 옵션이 없으면 DB의 값을 자동으로 절삭해서 불러오게됨. 소수점15자리까지 불러오기
  start_date <- start_date- days(1) # T-1 weight가 필요하기 때문이다.
  start_date<- str_remove_all(start_date,"-")
  end_date<- str_remove_all(end_date,"-")
  
  con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
  
  tbl(con_dt,"DWPM10510") %>% 
    filter(STD_DT>=!!start_date) %>% 
    filter(STD_DT<=!!end_date) %>% 
    filter(FUND_CD == !!fund_cd) %>% 
    select( STD_DT,IMC_CD,FUND_CD, NAST_AMT,OPNG_AMT,MNR_EMNO,MNR_EMNO2,DEPT_CD,MOD_STPR,PDD_CHNG_STPR,DD1_ERN_RT ) %>% 
    #filter(DEPT_CD %in% c('166','061'),IMC_CD=='003228') %>% 
    collect()-> temp
  
  if(temp$PDD_CHNG_STPR[1]==0){
    temp %>% 
      mutate(STD_DT = ymd(STD_DT)) %>% 
      mutate(DD1_ERN_RT = DD1_ERN_RT/100) %>% 
      mutate(PDD_CHNG_STPR = if_else(MOD_STPR>9500,lag(MOD_STPR,1,default = 10000),lag(MOD_STPR,1,default = 1000)  ) ,#ETF의 기준가는 10000원으로 시작
             수정기준가 =MOD_STPR )->fund_inform_history # PDD_CHNG_STPR은 소숫점 6자리여서 그냥 수정기준가 lagging해서 사용 
  }else{
    temp %>% 
      mutate(STD_DT = ymd(STD_DT)) %>% 
      mutate(DD1_ERN_RT = DD1_ERN_RT/100) %>% 
      #mutate(MOD_STPR3 = cumprod(DD1_ERN_RT+1)*1000) %>% 
      mutate(수정기준가 =MOD_STPR,
             MOD_STPR = (MOD_STPR/MOD_STPR[1])*1000, # 1000환산
             PDD_CHNG_STPR = lag(MOD_STPR,default = 1000*(1-DD1_ERN_RT[1])))->fund_inform_history # PDD_CHNG_STPR은 소숫점 6자리여서 그냥 수정기준가 lagging해서 사용 
  }
  return(fund_inform_history)  
}



# PA 최종 함수 ----------------------------------------------------------------------
# fund_cd <- "2JM23"
# from <- ymd("2025-06-01")
# to <- ymd("2025-09-07")

PA_from_MOS<- function(from,to,fund_cd){
  tictoc::tic()
  
  class_M_fund <- 모펀드_mapping %>% 
    filter(FUND_CD == fund_cd) %>% pull(CLSS_MTFD_CD)
  
  historical_PA_source_data  <- get_PA_source_data(fund_cd = class_M_fund,start_date = from,end_date = to)
  historical_fund_inform_data_class_M_fund <- get_fund_inform_data(fund_cd = class_M_fund,start_date = from,end_date = to)
  historical_fund_inform_data_fund_cd <- get_fund_inform_data(fund_cd = fund_cd,start_date = from,end_date = to)
  historical_fund_inform_data<- historical_fund_inform_data_class_M_fund %>% 
    select(-c(FUND_CD,MOD_STPR, PDD_CHNG_STPR)) %>% 
    left_join(historical_fund_inform_data_fund_cd %>% select(STD_DT,FUND_CD,MOD_STPR, PDD_CHNG_STPR))
  
  #데이터 정합성 검증: 모든날짜 데이터 존재여부
  if(var(c(length(timetk::tk_make_timeseries(from,to,by = "day")),
           length(unique(historical_PA_source_data$pr_date[historical_PA_source_data$pr_date>=from])),
           length(unique(historical_fund_inform_data$STD_DT[historical_fund_inform_data$STD_DT>=from])))) !=0){
    
    return(print("비어있는 DB 확인 필요"))
  }else(print("모든날짜 데이터 존재 확인"))
  
  print("데이터로딩완료")
  con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
  
  historical_position_DWPM10530 <- 
    tbl(con_dt,"DWPM10530") %>%
    select(STD_DT,SEQ,FUND_CD,ITEM_NM,ITEM_CD,POS_DS_CD,EVL_AMT,PDD_QTY,BUY_QTY,SELL_QTY) %>%
    filter(STD_DT>=local(str_remove_all(from-days(10),"-")) ) %>% 
    filter(FUND_CD %in% c(local(pulling_모자구조 %>% select(FUND_CD,모펀드통합) %>% 
                                  filter(FUND_CD == class_M_fund)%>% pull(모펀드통합)),class_M_fund) ) %>%
    filter(!(str_detect(ITEM_NM,"미지급")|str_detect(ITEM_NM,"미수"))) %>% distinct() %>% 
    collect() %>%
    mutate(기준일자 = ymd(STD_DT)) %>% 
    select(-STD_DT) 
  
  
  #하루에 사고팔고한 내역 삭제 - 4JM12 , 2025-06-11 선물
  historical_position_DWPM10530<- historical_position_DWPM10530 %>% 
    mutate(across(.cols = c(EVL_AMT,PDD_QTY,BUY_QTY,SELL_QTY),.fns = ~replace_na(.x,0))) %>% 
    group_by(기준일자,FUND_CD,ITEM_CD) %>% 
    reframe(POS_DS_CD =POS_DS_CD[1],
            ITEM_NM =ITEM_NM[1],
            across(.cols = c(EVL_AMT,PDD_QTY,BUY_QTY,SELL_QTY),.fns = ~sum(.x))) %>% 
    filter(EVL_AMT+PDD_QTY+BUY_QTY+SELL_QTY!=0) %>% 
    # 일부청산은 그대로 매도처리/ 롤오버때 전월물 전량 청산시 매수처리
    mutate(POS_DS_CD = if_else(POS_DS_CD == "매도" & PDD_QTY+BUY_QTY <=SELL_QTY , "매수",POS_DS_CD),
           EVL_AMT = if_else(POS_DS_CD == "매도", - EVL_AMT, EVL_AMT))
  
  
  
  pulling_모자구조 %>% select(FUND_CD,모펀드통합) %>% 
    filter(FUND_CD == class_M_fund)%>% pull(모펀드통합) ->related_funds
  
  
  historical_설정액_DWPM10510 <- tbl(con_dt,"DWPM10510") %>% 
    select( STD_DT,IMC_CD,FUND_CD,NAST_AMT,OPNG_AMT,MNR_EMNO,MNR_EMNO2,DEPT_CD,FXHG_RT) %>% 
    filter(STD_DT  >=!!str_remove_all(T_move_date_calc(from,-5),"-"),STD_DT  <=!!str_remove_all(to,"-") ) %>% 
    filter(FUND_CD %in% local(related_funds)) %>% 
    collect()
  
  tbl(con_dt,"DWCI10160") %>%
    select(tr_cd,synp_cd,tr_whl_nm,synp_cd_nm) %>% distinct() %>% 
    collect()->mapping_trade_code
  
  
  tbl(con_dt,"DWPM10520") %>%
    filter(std_dt  >=!!str_remove_all(T_move_date_calc(from,-5),"-"),std_dt  <=!!str_remove_all(to,"-") ) %>% 
    filter(fund_cd %in% !!related_funds) %>% 
    select(!!(c("STD_DT","FUND_CD","ITEM_CD", "TR_CD", "SYNP_CD","SEQ","BUY_SELL_DS_CD","ITEM_NM","TRD_QTY",
                "TRD_AMT","STL_AMT","TR_UPR","TRD_PL_AMT","KRW_ADPY_EXP_AMT",
                "KRW_STL_AMT","KRW_TRD_PL_AMT","KRW_SELL_INT","KRW_ERPL_AMT") %>% str_to_lower())
    ) %>%  
    collect() %>% 
    left_join(mapping_trade_code)->historical_trade
  
  
  ETF_환매_평가시가평가액보정<- historical_trade %>% 
    filter(str_detect(tr_whl_nm, "ETF발행시장환매") ) %>% 
    group_by(fund_cd,item_cd,tr_upr, trd_pl_amt) %>% 
    reframe(기준일자 = max(ymd(std_dt),na.rm = TRUE),
            item_nm = item_nm[n()],
            평가시가평가액보정= trd_amt[1],
            tr_whl_nm = tr_whl_nm[n()]) 
  
  
  if(prod(fund_cd == c(related_funds))==1){
    ETF_환매_평가시가평가액보정 <- ETF_환매_평가시가평가액보정 %>% 
      select(기준일자,FUND_CD=fund_cd,평가시가평가액보정,item_cd,item_nm)
    
  }else{
    ETF_환매_평가시가평가액보정<- ETF_환매_평가시가평가액보정 %>% 
      left_join(
        
        historical_position_DWPM10530 %>% 
          filter(FUND_CD ==class_M_fund) %>% 
          mutate(모펀드 = str_remove_all(ITEM_CD,"0322800")) %>% 
          filter(nchar(모펀드)==5) %>% 
          left_join(historical_설정액_DWPM10510 %>% rename(모펀드 = FUND_CD) %>% 
                      mutate(기준일자 = ymd(STD_DT)) %>% 
                      select(기준일자,모펀드,OPNG_AMT)) %>% 
          mutate(추적배수 = PDD_QTY/OPNG_AMT) %>% 
          select(기준일자,FUND_CD,모펀드,추적배수) 
        , by = join_by(기준일자,fund_cd==모펀드)
      ) %>% 
      mutate(평가시가평가액보정 = 평가시가평가액보정*추적배수) %>% 
      select(기준일자,FUND_CD,평가시가평가액보정,item_cd,item_nm) %>% 
      group_by(기준일자,FUND_CD,item_cd) %>% 
      reframe(평가시가평가액보정 = sum(평가시가평가액보정),
              item_nm = item_nm[1])
  }
  
  
  
  
  
  
  
  # 비중 ---------------------------------------------------------------------
  
  historical_PA_source_data %>% 
    left_join(historical_position_DWPM10530 %>% distinct(),
              by = join_by(pr_date == 기준일자,sec_id ==ITEM_CD))   %>% 
    mutate(position_gb = if_else(position_gb =="LONG" & POS_DS_CD =="매도" , "SHORT",position_gb)) %>% 
    mutate(POS_DS_CD = if_else(position_gb =="SHORT" & POS_DS_CD =="매수" , "매도",POS_DS_CD)) %>% 
    group_by(fund_id,pr_date, sec_id) %>% 
    reframe(ITEM_NM= ITEM_NM[1],
            POS_DS_CD = POS_DS_CD[1],
            시가평가액 = max(val),
            # 평가시가평가액은, 신규매수의 경우 별도로 취급.(4JM12펀드의 2025-06-11 KR4 75W70003종목 평가시가평가액이 오류로 보여서 별도 처리)
            평가시가평가액 =  case_when(PDD_QTY ==0 & BUY_QTY !=0 ~ max(val)-sum(amt),  # 당일평가시가평가액 + 당일 총손익 = 당일 시가평가액
                                 TRUE ~ max(std_val)),
            asset_gb = asset_gb[1],
            position_gb = if_else((n() >= 2) & (sum(pl_gb == "평가") != 0), # 기타손익이 -인경우 매도로 찍히는 경우가 존재
                                  # Use first() or similar to ensure a single value
                                  first(position_gb[pl_gb == "평가"]),
                                  position_gb[1])
    ) %>% distinct() %>% 
    group_by(sec_id) %>%
    # ETF BA정산금 등등의 경우에 기준평가액을 평가시가평가액으로 잡아서 수익률계산에 사용
    mutate(평가시가평가액= case_when(시가평가액 == 0 & 평가시가평가액 == 0 & sec_id !="000000000000" ~ lag(평가시가평가액),
                              시가평가액 == 0 ~ lag(시가평가액),
                              TRUE ~ 평가시가평가액)) %>%
    fill(ITEM_NM ,.direction = "up") %>% 
    ungroup() %>% 
    #filter(position_gb =="LONG" & POS_DS_CD =="매도") %>% view()
    #filter(position_gb =="SHORT" & POS_DS_CD =="매수") %>% view()
    relocate(ITEM_NM, .after = sec_id) %>%
    mutate(ITEM_NM = if_else(is.na(ITEM_NM) & sec_id =="000000000000", "기타비용",ITEM_NM),
           POS_DS_CD = if_else(is.na(POS_DS_CD) & sec_id =="000000000000", "매수",POS_DS_CD)) %>%
    left_join(historical_fund_inform_data %>% 
                rename(pr_date = STD_DT, 순자산총액 = NAST_AMT,설정액=OPNG_AMT,수정기준가=MOD_STPR,수정기준가_raw =수정기준가 ) %>% 
                select(-contains("MNR_EMNO"),-DEPT_CD,-IMC_CD), by = join_by(pr_date)) %>% 
    group_by(sec_id ) %>%
    fill(c(ITEM_NM, POS_DS_CD), .direction = "down") %>% 
    ungroup()-> 기초정보요약# 전량 매도된 경우 전일 시가평가액은 있지만, 당일 포지션엔 데이터가 없어서 채우기.
  
  # ITEM_NM 에 특정 키워드 포함하면 같은 sec으로 묶어주기 => 롤오버시 위험평가액 괴리가 크기 때문. ex) "미국달러 F " 포함하는, 코스피 포함하는 등
  
  
  
  # Universe에 추가할 요소가 있는지 확인 
  기초정보요약 %>% 
    # 추후에는 DB에 적재된 테이블과 조인하여 가져오기. 자산군관련 열이 여러개가 될텐데 ..
    left_join(universe_non_derivative_table %>% 
                select(ISIN,classification_method,classification) %>% 
                filter(classification_method == "Currency Exposure", !is.na(classification),!is.na(classification_method)) %>% 
                select(-classification_method) %>% 
                rename(노출통화 =classification) %>% 
                distinct(),by = join_by(sec_id==ISIN)) -> non_derivative_mapped
  
  
  # (1-2) derivative 규칙 테이블(자산군+키워드+노출통화) 정리
  deriv_rules <- universe_derivative_table %>%
    filter(classification_method == "Currency Exposure",
           !is.na(classification), !is.na(classification_method)) %>%
    transmute(
      asset_gb,                      # 예: '기타선물','주식선물','채권선물'
      keyword,                       # 예: "미국달러 F ", "코스피", "10년국채"
      rule_ccy = classification,
      priority = dplyr::row_number() # 충돌시 우선순위(원하는 기준으로 바꿔도 됨)
    ) %>%
    mutate(asset_gb = coalesce(asset_gb, "")) %>%
    distinct()
  
  # (3) ② derivative 규칙으로 미매핑 보완 --------------------------------------
  need_deriv <- non_derivative_mapped %>% filter(is.na(노출통화))
  
  # ITEM_NM ~ keyword(정규식) 매칭 + asset_gb 조건 일치(또는 규칙이 공통일 때 "")
  deriv_candidates <- need_deriv %>%
    select(sec_id, ITEM_NM, asset_gb) %>%
    mutate(asset_gb = coalesce(asset_gb, "")) %>%
    regex_left_join(deriv_rules, by = c("ITEM_NM" = "keyword")) %>%
    filter(asset_gb.y == "" | asset_gb.x == asset_gb.y) %>%
    group_by(sec_id) %>%
    slice_min(order_by = priority, n = 1, with_ties = FALSE) %>%
    ungroup() %>%
    transmute(sec_id, deriv_ccy = rule_ccy)
  
  deriv_mapped <- need_deriv %>%
    left_join(deriv_candidates, by = "sec_id") %>%
    mutate(노출통화 = coalesce(노출통화, deriv_ccy)) %>%
    select(-deriv_ccy)
  
  non_derivative_mapped %>%
    filter(!is.na(노출통화)) %>%            # 이미 ①에서 매핑된 것
    bind_rows(deriv_mapped) %>% 
    mutate(노출통화 = coalesce(노출통화,case_when(
      asset_gb == "유동" & str_sub(sec_id,1,2) == "US" ~ "USD",
      asset_gb == "유동" & str_sub(sec_id,1,2) %in% c("KR","00") ~ "KRW",
      asset_gb == "기타비용" ~ "KRW",
      TRUE ~ 노출통화))) -> check_mapping_classification
  
  
  print("자산군매핑완료")
  
  
  check_mapping_classification %>% 
    filter(is.na(노출통화)) %>% 
    select(sec_id,ITEM_NM,노출통화,asset_gb)%>% distinct() -> should_be_mapping
  
  
  bind_rows(
    should_be_mapping %>% 
      mutate(노출통화 = if_else(str_sub(sec_id,1,2)=="KR","KRW","USD")),
    check_mapping_classification %>% 
      filter(!is.na(노출통화)) %>% 
      select(sec_id,ITEM_NM,노출통화,asset_gb)%>% distinct()  
  ) -> mapped_results
  
  # if(nrow(should_be_mapping)!=0){
  #   print("자산군 매핑이 필요합니다.")
  #   return(should_be_mapping)
  # }else{
  
  check_mapping_classification %>% 
    mutate(노출통화 = if_else(is.na(노출통화),
                          if_else(str_sub(sec_id,1,2)=="KR","KRW","USD"),
                          노출통화
    )) %>% 
    #filter(!is.na(노출통화)) %>% 
    # 콜론인데 전일자에 당일 시가평가액 =0 인것들은 제외해야함.-->이유가 뭐였더라..?
    filter( !(str_detect(ITEM_NM,"\\(콜")& 시가평가액==0) ) %>%
    mutate(평가시가평가액 = if_else(is.na(평가시가평가액), 0 ,평가시가평가액)) %>% 
    arrange(pr_date, desc(시가평가액)) %>% 
    mutate(순자산비중 = if_else(position_gb=="SHORT",-시가평가액 / (순자산총액), 시가평가액 / (순자산총액))) %>% 
    select(pr_date,sec_id,asset_gb,position_gb,시가평가액,평가시가평가액,ITEM_NM, 순자산총액,순자산비중,수정기준가,PDD_CHNG_STPR,설정액,POS_DS_CD,노출통화) -> historical_information
  
  
  # ── [DEBUG TRACE] historical_information 진입 시 ACE 03-06 상태 ──
  cat("\n================================================================\n")
  cat("[TRACE] historical_information 진입 시 ACE 03-01~10\n")
  cat("================================================================\n")
  print(historical_information %>% filter((sec_id=="KR7365780006" & pr_date >= as.Date("2026-03-01") & pr_date <= as.Date("2026-03-10")) | (sec_id=="KR7356540005" & pr_date >= as.Date("2026-03-10") & pr_date <= as.Date("2026-03-20"))) %>% select(sec_id, pr_date, position_gb, 시가평가액, 평가시가평가액))

  historical_information %>%
    select(pr_date,sec_id,asset_gb,position_gb,ITEM_NM,시가평가액,평가시가평가액,순자산총액,순자산비중,POS_DS_CD,노출통화) %>%
    mutate(시가평가액 = if_else(position_gb=="SHORT",-시가평가액,시가평가액),
           평가시가평가액 = if_else(position_gb=="SHORT",-평가시가평가액,평가시가평가액)) %>%
    { cat("\n[STEP_A] select + SHORT inversion 후 ACE 03-06\n"); print(filter(., (sec_id=="KR7365780006" & pr_date == as.Date("2026-03-06")) | (sec_id=="KR7356540005" & pr_date == as.Date("2026-03-16"))) %>% select(pr_date, position_gb, 시가평가액, 평가시가평가액)); . } %>%
    left_join(historical_PA_source_data %>%
                group_by(pr_date,sec_id)%>%
                reframe(총손익금액_당일= sum(amt),
                        # `배당금+기타` = sum(amt[pl_gb=="배당"],amt[pl_gb=="기타"],na.rm = TRUE)) ,
                        `환산`   = sum(amt[pl_gb=="환산"],na.rm = TRUE),
                        `배당금` = sum(amt[pl_gb=="배당"],na.rm = TRUE),
                        `기타` = sum(amt[pl_gb=="기타"],na.rm = TRUE)) ,
              by=join_by(pr_date, sec_id)) %>%
    { cat("\n[STEP_B] left_join PA_source reframe (총손익/환산/배당/기타) 후 ACE 03-06\n"); print(filter(., (sec_id=="KR7365780006" & pr_date == as.Date("2026-03-06")) | (sec_id=="KR7356540005" & pr_date == as.Date("2026-03-16"))) %>% select(pr_date, 시가평가액, 평가시가평가액, 총손익금액_당일, 환산, 배당금, 기타)); . } %>%
    left_join(ETF_환매_평가시가평가액보정 %>% select(-item_nm,-FUND_CD),
              by=join_by(pr_date==기준일자, sec_id==item_cd)) %>%
    { cat("\n[STEP_C] left_join ETF 환매 평가시가평가액보정 후 ACE 03-05/06\n"); print(filter(., (sec_id=="KR7365780006" & pr_date >= as.Date("2026-03-05") & pr_date <= as.Date("2026-03-06")) | (sec_id=="KR7356540005" & pr_date >= as.Date("2026-03-13") & pr_date <= as.Date("2026-03-16"))) %>% select(pr_date, 시가평가액, 평가시가평가액, 평가시가평가액보정, 총손익금액_당일)); . } %>%
    mutate(순설정액= if_else(abs((시가평가액-(총손익금액_당일+평가시가평가액)))<100, 0,
                         (시가평가액-(총손익금액_당일+평가시가평가액)))) %>%
    { cat("\n[STEP_D] 순설정액 계산 후 ACE 03-06\n"); print(filter(., (sec_id=="KR7365780006" & pr_date == as.Date("2026-03-06")) | (sec_id=="KR7356540005" & pr_date == as.Date("2026-03-16"))) %>% select(pr_date, 시가평가액, 평가시가평가액, 평가시가평가액보정, 총손익금액_당일, 순설정액)); . } %>%
    mutate(across(.cols= c(contains("시가평가액"),"순설정액"), .fns = ~replace_na(.x,0))) %>%
    { cat("\n[STEP_E] replace_na(across contains 시가평가액) 후 ACE 03-06\n"); print(filter(., (sec_id=="KR7365780006" & pr_date == as.Date("2026-03-06")) | (sec_id=="KR7356540005" & pr_date == as.Date("2026-03-16"))) %>% select(pr_date, 시가평가액, 평가시가평가액, 평가시가평가액보정, 순설정액)); . } %>%
    mutate(position_gb = coalesce(position_gb,"LONG")) %>%
    { cat("\n[STEP_F] position_gb coalesce 후 ACE 03-06\n"); print(filter(., (sec_id=="KR7365780006" & pr_date == as.Date("2026-03-06")) | (sec_id=="KR7356540005" & pr_date == as.Date("2026-03-16"))) %>% select(pr_date, position_gb, 평가시가평가액, 평가시가평가액보정)); . } %>%
    mutate(평가시가평가액 =평가시가평가액+평가시가평가액보정)  %>%
    { cat("\n[STEP_G] 평가시가평가액 + 평가시가평가액보정 후 ACE 03-06  ← 핵심 reset 지점\n"); print(filter(., (sec_id=="KR7365780006" & pr_date == as.Date("2026-03-06")) | (sec_id=="KR7356540005" & pr_date == as.Date("2026-03-16"))) %>% select(pr_date, position_gb, 시가평가액, 평가시가평가액, 평가시가평가액보정, 순설정액, 총손익금액_당일)); . } %>%
    # 배당이 있는경우 배당락 만큼 순설정액이 -방향으로 집계됨,
    # BA정산금 증가(추가납입 필요)의 경우에는 순설정액이 +로 집계
    # BA정산금 감소(비싸게산만큼 돌려받는것 필요)의 경우에는 순설정액이 -로 집계
    mutate(조정_평가시가평가액 = case_when(position_gb=="SHORT" ~ 평가시가평가액,
                                  position_gb=="LONG" ~ if_else( (순설정액 <0 ) | (시가평가액==0 &평가시가평가액>0) ,
                                                                 평가시가평가액,# 순설정액이 -이거나 전액매도인 경우 평가시가평가액 (배당금 수령일도 포함됨)
                                                                 시가평가액-(총손익금액_당일) )) ) %>%   # 순설정액이 0 or +인경우
    { cat("\n[STEP_H] 조정_평가시가평가액 case_when 후 ACE 03-06\n"); print(filter(., (sec_id=="KR7365780006" & pr_date == as.Date("2026-03-06")) | (sec_id=="KR7356540005" & pr_date == as.Date("2026-03-16"))) %>% select(pr_date, position_gb, 시가평가액, 평가시가평가액, 순설정액, 조정_평가시가평가액)); . } %>%
    mutate(종목별당일수익률= if_else(position_gb=="LONG",총손익금액_당일/조정_평가시가평가액,총손익금액_당일/(-조정_평가시가평가액))) %>%
    mutate(노출통화 = if_else(is.na(노출통화), "KRW",노출통화)) -> historical_performance_information

  cat("\n[TRACE] historical_performance_information 최종 ACE 03-06\n")
  options(tibble.width = Inf)
  print(historical_performance_information %>% filter((sec_id=="KR7365780006" & pr_date == as.Date("2026-03-06")) | (sec_id=="KR7356540005" & pr_date == as.Date("2026-03-16"))) %>% select(sec_id, pr_date, position_gb, 시가평가액, 평가시가평가액, 총손익금액_당일, 순설정액, 조정_평가시가평가액, 종목별당일수익률), width = Inf)
  cat("================================================================\n\n")
  
  #select(pr_date, sec_id,ITEM_NM,자산군,조정_평가시가평가액,평가시가평가액,시가평가액 ,총손익금액_당일,종목별당일수익률,`배당금+기타`,노출통화) -> historical_performance_information
  
  
  # 선물 롤오버 보정을 위해 데이터 분리 및, 전처리 후 다시합치기 --------------
  # Case 1. 롤오버를 하루만에 하는게 아니라 절반씩 하는경우 어떻게 계산 등등 확장성을 고려하여 그룹핑 체계 정의
  # Grouping_dictionary<- list(
  #   #~sec_id  ,~ ITEM_NM에서 str_detect할것,
  #   "미국달러_선도환" = c("KRW/USD "), # KRW/USD의 경우 POS_DS_CD = 매수,노출통화 KRW로 되어있음. -->position_gb변수 = short 이용
  #   "미국달러_선물"   = c("미국달러"), 
  #   "채권선물_10년" = c("10년국채"),
  #   "KOSPI_선물" = c("코스피200"),
  #   "KOSPI_미니선물" = c("미니코스피")
  # )
  Grouping_dictionary <- deriv_rules %>%
    mutate(group = paste0(asset_gb, "_", keyword)) %>%
    group_by(group) %>%
    summarise(patterns = list(unique(keyword)), .groups = "drop") %>%
    tibble::deframe()
  
  asset_파생_keywords <- unique(deriv_rules$asset_gb)#c("선물","선도환")
  # asset_gb열을 통해 파생 필터링 후, 단어로 Grouping
  historical_performance_information %>% 
    filter(grepl(paste(unlist(asset_파생_keywords), collapse = "|"), asset_gb))->Grouping_파생
  
  historical_performance_information %>% 
    filter(!grepl(paste(unlist(asset_파생_keywords), collapse = "|"), asset_gb))->Grouping_ex_파생
  
  
  Grouping_파생 %>% 
    filter(!grepl(paste(unlist(Grouping_dictionary), collapse = "|"), ITEM_NM))->new_key_Grouping_dictionary
  if(nrow(new_key_Grouping_dictionary)>0){
    print("매핑이 필요한 선물 종목이 있습니다.")
    return(new_key_Grouping_dictionary)
  }
  
  # 중간 결과물을 저장할 리스트
  derivatives_list <- list()
  #group <-"주식선물_코스피"# "기타선물_미국달러 F "
  #group <- "선도환"
  # for문을 사용하여 각 항목에 대해 처리 (일자별로 2개 이상인것들만 보정하면 됨.(단순히 청산하는거에 순설정액 보정시 괴리 발생) 따라서 Grouping_dictionary는 최대한 세세하게 쪼개야함)
  for (group in names(Grouping_dictionary)) {
    #group <- names(Grouping_dictionary)[2]
    # Grouping_dictionary의 각 그룹에 해당하는 ITEM_NM 필터링
    if((Grouping_파생 %>% 
        filter(grepl(paste(Grouping_dictionary[[group]], collapse = "|"), ITEM_NM)) %>% 
        nrow())==0){
      # 중간 결과물로 저장
      Grouping_파생 %>% 
        filter(grepl(paste(Grouping_dictionary[[group]], collapse = "|"), ITEM_NM)) ->temp_data
      
    }else{
      
      roll_over_date <- 
        Grouping_파생 %>%
        filter(grepl(paste(Grouping_dictionary[[group]], collapse = "|"), ITEM_NM)) %>%
        group_by(pr_date) %>% 
        filter(n()>=2) %>% 
        #mutate(position_tracking = sum(abs(조정_평가시가평가액))-sum(abs(조정_평가시가평가액[시가평가액==0]))) %>% #포지션이 확대된경우 잘잡음. 축소된경우 전일자시가평가액 합으로 대체.
        ungroup() %>% 
        group_by(pr_date, sec_id,노출통화) %>%
        reframe(
          sec_id = sec_id[1], # 자산군매핑할때 dataset_id 중 1개 선택해서 복제하기 위함
          asset_gb = asset_gb[1],
          ITEM_NM = ITEM_NM[1],
          시가평가액 = sum(시가평가액),
          # 포지션 방향중 큰 방향의 평가시가평가액, 롤오버 후에 시가평가액의 방향 따름.
          조정_평가시가평가액 = 조정_평가시가평가액,
          # 조정_평가시가평가액 =case_when( str_detect(group,"선도환") ~ sum(abs(조정_평가시가평가액))*sign(시가평가액),
          #                        TRUE ~max(abs(조정_평가시가평가액))*sign(시가평가액) )  ,
          순자산총액 = 순자산총액[1],
          순자산비중 = sum(순자산비중),
          총손익금액_당일 = sum(총손익금액_당일),
          환산 = sum(환산)
        ) %>% 
        mutate(POS_DS_CD = if_else(조정_평가시가평가액<0, "매도","매수"),
               position_gb = if_else(조정_평가시가평가액<0, "SHORT","LONG"))
      
      
      Grouping_파생 %>%
        filter(grepl(paste(Grouping_dictionary[[group]], collapse = "|"), ITEM_NM)) %>%
        group_by(pr_date) %>% 
        filter(n() ==1) %>% 
        mutate(  sec_id = sec_id[1],
                 ITEM_NM = ITEM_NM[1]) %>% 
        bind_rows(roll_over_date) %>%
        arrange(pr_date) %>% 
        # Case 1. 2JM23 2024-10-08 미니코스피 축소 롤오버 -> 무시
        # Case 2. 확대 롤오버가 있을 수 있음. -> 무시 . 
        ungroup() %>% 
        group_by(sec_id) %>% 
        #mutate(temp_변수 = lag(시가평가액, n = 1),.before = 평가시가평가액) %>% view()
        #rowwise() %>% 
        mutate(
          #조정_평가시가평가액 = if_else(temp_변수* 시가평가액<=0 , max( abs(temp_변수), abs(시가평가액),na.rm = TRUE),
          # abs( 시가평가액 -총손익금액_당일 )),
          종목별당일수익률 = 총손익금액_당일/abs(조정_평가시가평가액)
          
        ) %>% #select(-temp_변수) %>% 
        ungroup() ->temp_data
    }
    
    
    # 중간 결과물로 저장
    derivatives_list[[group]] <- temp_data
  }
  # Grouping_ex_파생와 합치기
  bind_rows(derivatives_list) -> derivatives_list_position_gb#%>% 
  #mutate(ITEM_NM = case_when(position_gb == "SHORT"~ str_glue("{ITEM_NM}(매도)"),
  #                           position_gb == "LONG" ~ str_glue("{ITEM_NM}(매수)")
  #)) ->derivatives_list_position_gb
  historical_performance_information_final<- bind_rows(Grouping_ex_파생,derivatives_list_position_gb)  
  #derivatives_list_position_gb %>% view()
  # derivatives_list$`기타선물_미국달러 F ` %>% view()
  
  # daily_return 분해과정 ---------------------------------------------------------------
  #유동성이 아닌경우, 전일자 외화평가액에 대해서만 환손익 계산 하면 됨. 당일 변동분은 총손익에서 전부 달러항목에 반영되기 때문. 
  # -> 전일자 시가평가액,환노출비중 가지고 당일의 환손익 발라내기.
  # Step 1.MOS로직은 r_sec * r_FX + r_FX가 환손익으로 잡히는중
  # Step 2.R = (1+r_sec)*(1+r_FX)-1 라고할때, 총손익에서 r_sec에 해당하는 금액을 제하면 됨.
  # Step 3. r_sec = (1+R)/(1+r_FX)-1 = (1+당일총손익/조정평가시가평가액)/(1+당일환율/전일환율)-1
  # Step 4.환산손익 = 총손익 -  r_sec*조정평가시가평가액
  con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
  
  
  tbl(con_dt,"DWCI10160") %>%
    select(tr_cd,synp_cd,tr_whl_nm,synp_cd_nm) %>% distinct() %>% 
    collect()->mapping_trade_code
  
  tbl(con_dt,"DWPM12880") %>% 
    filter(tr_dt>=!!str_remove_all(from,"-"),tr_dt<=!!str_remove_all(to,"-") ) %>% 
    filter(fund_cd ==local(class_M_fund)) %>% 
    collect() -> historical_redemption
  
  historical_redemption %>% 
    left_join(mapping_trade_code) %>%
    select(tr_dt,fund_cd,tr_cd,synp_cd,scom_cd,
           원본변동금액=ocpy_flct_amt,
           이월순자산변동금액=bf_nast_flct_amt,
           일부해지원본금액 = part_clsr_ocpy_amt,
           contains("nm")) %>% 
    mutate(이월순자산변동금액 = if_else(str_detect(tr_whl_nm,"해지"),-이월순자산변동금액,이월순자산변동금액)) %>% 
    mutate(기준일자 = ymd(tr_dt)) %>% 
    group_by(기준일자)  %>% 
    reframe(순설정금액 = sum(이월순자산변동금액))->pure_redemption
  
  
  # __수익률 및 비중(자산군별)--------------------------------------------------------------
  
  
  historical_performance_information_final %>% 
    #filter(is.na(조정_평가시가평가액) & asset) %>% 
    filter( !(asset_gb == "유동" | str_detect(ITEM_NM,"미국달러") | asset_gb == "기타비용" | asset_gb == "선도환") ) %>%   #유동성과 기타는 합쳐서 보는버전
    filter(!is.na(조정_평가시가평가액)) %>%  # 20250922, 07J34 에서 발생한 에러(전량매도 후 배당금입금경우 시 기타로 잡기)
    arrange(pr_date) %>%
    select(pr_date,sec_id,asset_gb,position_gb,ITEM_NM,시가평가액,조정_평가시가평가액,순자산총액,순자산비중,총손익금액_당일,환산,노출통화) %>% 
    left_join(pure_redemption,by = join_by(pr_date ==기준일자)) %>% 
    mutate(순설정금액 = if_else(is.na(순설정금액),0,순설정금액)) %>% 
    left_join(historical_performance_information_final %>% 
                group_by(pr_date) %>% 
                reframe(순자산총액 = 순자산총액[1]) %>% 
                mutate(`순자산총액(T-1)` = lag(순자산총액,default = 0,n=1))) %>% 
    group_by(sec_id) %>% 
    mutate(`시가평가액(T-1)`=  lag(시가평가액,default = 0,n=1)) %>%
    mutate(`순자산총액(T-1)+당일순설정금액`=  `순자산총액(T-1)`+순설정금액) %>% 
    mutate(weight_PA = 조정_평가시가평가액/`순자산총액(T-1)+당일순설정금액`) %>% 
    ungroup() %>% 
    #filter(pr_date >= from) %>% 
    left_join(USDKRW %>% 
                mutate(`return_USD/KRW`=`USD/KRW`/lag(`USD/KRW`)-1),by = join_by(pr_date==기준일자)) %>% 
    # Step 3. r_sec = (1+R)/(1+r_FX)-1 = (1+총손익금액_당일/조정_평가시가평가액)/(1+당일환율/전일환율)-1
    # Step 4.환산손익 = 총손익 -  r_sec*조정평가시가평가액
    mutate(r_sec = if_else(노출통화=="USD",(1+총손익금액_당일/조정_평가시가평가액)/(1+`return_USD/KRW`)-1 ,총손익금액_당일/조정_평가시가평가액 )) %>% 
    #mutate(환산_adjust = if_else(노출통화=="USD", `시가평가액(T-1)`*`return_USD/KRW`,환산)) %>% 
    #mutate(환산_adjust = if_else(노출통화=="USD", 환산,환산)) %>% 
    mutate(환산_adjust =  if_else(노출통화=="USD",`시가평가액(T-1)`*`return_USD/KRW`+`return_USD/KRW`*r_sec*`시가평가액(T-1)` ,환산)) %>% 
    mutate(총손익금액_당일_FX_adjust = 총손익금액_당일-환산_adjust) ->before_exclude_FX_효과_in_sec
  
  
  
  before_exclude_FX_효과_in_sec %>% 
    select(pr_date,sec_id,ITEM_NM,시가평가액,조정_평가시가평가액,순자산비중,`순자산총액(T-1)+당일순설정금액`,총손익금액_당일,
           총손익금액_당일_FX_adjust,환산_adjust,노출통화,contains("weight")) %>% 
    group_by(pr_date,sec_id) %>% # group by 자산군분류체계(sec_id도 자산군분류체계중 1개)
    reframe(`수익률(FX_제외)` = sum(총손익금액_당일_FX_adjust,na.rm = TRUE)/ sum(조정_평가시가평가액,na.rm = TRUE),
            `수익률(FX_포함)` = sum(총손익금액_당일,na.rm = TRUE)/ sum(조정_평가시가평가액,na.rm = TRUE),
            weight_순자산= 순자산비중[1],
            `weight_PA(T)`= sum(weight_PA,na.rm = TRUE),
            조정_평가시가평가액 = sum(조정_평가시가평가액,na.rm = TRUE),
            총손익금액_당일 = sum(총손익금액_당일,na.rm = TRUE),
            총손익금액_당일_FX_adjust = sum(총손익금액_당일_FX_adjust,na.rm = TRUE),
            ITEM_NM = ITEM_NM[1],
            노출통화 = 노출통화[1]
    ) ->sec_return_weight #%>% 
  #filter(pr_date>=from) -> sec_return_weight
  
  # __ 수익률 및 비중(FX) ---------------------------------------------------------
  
  bind_rows(
    
    # ____환산손익(자산군) -----------------------------------------------------------
    before_exclude_FX_효과_in_sec %>% 
      select(pr_date,sec_id,asset_gb,position_gb,ITEM_NM,시가평가액,조정_평가시가평가액,순자산비중,순자산총액,`순자산총액(T-1)+당일순설정금액`,
             환산_adjust,노출통화,contains("weight")) %>% 
      filter(노출통화!="KRW") %>% 
      rename(weight_순자산 = 순자산비중) %>% 
      mutate(asset_gb = "유동"),
    
    # ____환산손익(FX(롤오버 Grouping 완료되어있음) & 유동성) (여기는 환산 손익 그대로 사용) -----------------------------------------------------------
    historical_performance_information_final %>% 
      left_join(historical_performance_information_final %>% 
                  group_by(pr_date) %>% 
                  reframe(순자산총액 = 순자산총액[1]) %>% 
                  mutate(`순자산총액(T-1)` = lag(순자산총액,default = 0,n=1))) %>% 
      filter( (asset_gb == "유동" | str_detect(ITEM_NM,"미국달러") | str_detect(ITEM_NM,"KRW/USD ")) & (sec_id != "000000000000" & 노출통화!="KRW") ) %>%   #유동성과 기타는 합쳐서 보는버전
      arrange(pr_date) %>% 
      left_join(pure_redemption,by = join_by(pr_date ==기준일자)) %>% 
      mutate(순설정금액 = if_else(is.na(순설정금액),0,순설정금액)) %>% 
      group_by(sec_id) %>% 
      mutate(`시가평가액(T-1)`=  lag(시가평가액,default = 0,n=1)) %>% 
      mutate(`순자산총액(T-1)+당일순설정금액`=  `순자산총액(T-1)`+순설정금액) %>% 
      mutate(weight_PA = 조정_평가시가평가액/`순자산총액(T-1)+당일순설정금액`) %>% 
      ungroup() %>% 
      # filter(pr_date >= from) %>%
      rename(weight_순자산 = 순자산비중) %>% 
      select(pr_date,sec_id,asset_gb,position_gb,ITEM_NM,시가평가액,조정_평가시가평가액,순자산총액,`순자산총액(T-1)+당일순설정금액`,
             환산_adjust = 총손익금액_당일,노출통화,contains("weight"))
  ) %>% 
    mutate(자산군 = "FX") %>% 
    mutate(sec_id = if_else(asset_gb == "유동",노출통화,sec_id)) %>% 
    group_by(pr_date,sec_id,position_gb,자산군,노출통화) %>% 
    reframe(ITEM_NM = if_else(asset_gb[1] == "유동",노출통화[1],ITEM_NM[1]),
            `수익률(FX)` = sum(환산_adjust,na.rm = TRUE)/ sum(abs(조정_평가시가평가액),na.rm = TRUE) ,
            weight_순자산 = sum(weight_순자산,na.rm = TRUE),
            `weight_PA(T)`= sum(weight_PA,na.rm = TRUE),
            조정_평가시가평가액 = sum(abs(조정_평가시가평가액),na.rm = TRUE),
            총손익금액_당일 = sum(환산_adjust,na.rm = TRUE)) %>%
    group_by(pr_date) %>% 
    mutate(
      환노출비중_순자산 = sum(weight_순자산,na.rm = TRUE),
      환노출비중_PA = sum(`weight_PA(T)`,na.rm = TRUE),
      환헷지비중_순자산 = -sum(weight_순자산[weight_순자산<0],na.rm = TRUE)/sum(weight_순자산[weight_순자산>0],na.rm = TRUE),
      환헷지비중_PA = -sum(`weight_PA(T)`[`weight_PA(T)`<0],na.rm = TRUE)/sum(`weight_PA(T)`[`weight_PA(T)`>0],na.rm = TRUE)
    ) %>% ungroup() -> FX_return_weight #%>% 
  #filter(pr_date>=from) -> FX_return_weight
  
  # Actual Return vs 검증 ----------------------------------------------------------------------
  
  historical_information %>% 
    select(pr_date,수정기준가,PDD_CHNG_STPR) %>% distinct() %>% 
    mutate(daily_return_AP = 수정기준가/PDD_CHNG_STPR-1) %>% 
    left_join(
      bind_rows(
        sec_return_weight %>% 
          rename(daily_return = "수익률(FX_제외)",`daily_weight(T)`=`weight_PA(T)`) %>% 
          select(-contains("노출통화비중")),
        FX_return_weight %>% 
          group_by(pr_date,자산군) %>%
          reframe(daily_return = sum(총손익금액_당일)/sum(abs(조정_평가시가평가액)),
                  `daily_weight(T)`=sum(abs(`weight_PA(T)`))) 
      ) %>% 
        arrange(pr_date) %>% 
        group_by(pr_date) %>% 
        reframe(daily_return = sum(daily_return*`daily_weight(T)`,na.rm = TRUE))
      #  daily_turnover = sum( abs(`daily_weight(T)`-`daily_weight(T-1)`) )) %>% 
    ) %>% 
    #filter(pr_date>=from) %>% 
    mutate(daily_return = if_else(is.na(daily_return), 0 ,daily_return)) %>% 
    mutate(`gap(AP-유동성및기타제외수익률)` = daily_return_AP - daily_return ) %>% 
    mutate(gap_percent = scales::percent_format(accuracy = 0.0000001)(daily_return_AP - daily_return)) -> for_validation_results
  
  
  
  historical_PA_source_data %>% 
    filter(asset_gb == "유동") %>% 
    filter(val !=0) %>% 
    mutate(val = case_when(position_gb =="LONG" ~ val,
                           position_gb =="SHORT" ~ -val)) %>% 
    group_by(fund_id,pr_date, sec_id) %>% 
    reframe(시가평가액 = max(val)) %>% 
    left_join(historical_performance_information_final %>% 
                group_by(pr_date) %>% 
                reframe(순자산총액 = 순자산총액[1])) %>% 
    group_by(pr_date) %>% 
    reframe(순자산비중 = sum(시가평가액/순자산총액[1])) ->historical_유동성순자산
  
  
  return_res <- list(
    "historical_PA_source_data" = historical_PA_source_data,
    "historical_fund_inform_data" = historical_fund_inform_data ,
    #"historical_results_PA" = historical_results_PA,
    "historical_redemption" = historical_redemption,
    "historical_trade" = historical_trade,
    "historical_performance_information_final" = historical_performance_information_final,
    "sec_return_weight" = sec_return_weight,
    "FX_return_weight" = FX_return_weight,
    "for_validation_results" = for_validation_results,
    "check_mapping_classification" = mapped_results,
    "historical_cash_NAV" = historical_유동성순자산
  )
  
  
  
  return(return_res)
}
