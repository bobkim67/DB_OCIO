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
Fund_Information <-  tibble(
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  구분= c("TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","BF","BF","BF")
)

ecos.setKey("FWC2IZWA5YD459SQ7RJM")
# Replace 'db_user', 'db_password', 'db_name', and 'host_name' with your actual database credentials
con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')
con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')
query_8183 <- "
 /* 8183(수익, 모델) */
  SELECT 
A.STD_DT,
A.IMC_CD, /*003228(수익), M03228(모델)*/
A.FUND_CD,
B.FUND_NM ,
A.MOD_STPR	
FROM DWPM10510 A
JOIN DWPI10011 B
ON A.FUND_CD = B.FUND_CD 
AND A.IMC_CD = B.IMC_CD 
WHERE STD_DT >= '20221005'
AND A.FUND_CD IN (
    '07M02', '07J66', '07J71', '07J76', '07J81', '07J86', 
    '07J91', '07J96', '07J41', '07J34', '2MP24', '1MP30', 
    '1MP35', '1MP40', '1MP45', '1MP50', '1MP55', '1MP60', 
    '3MP01', '3MP02', '07J48', '07J49', 
    '07P70', '6MP07',/*골든그로스*/
    '07Q93', '4MP80' /*골드2080 */
)
"

query_8004 <- "
 /* 8004(수익, 모델) */
  SELECT 
A.STD_DT,
A.IMC_CD, /*003228(수익), M03228(모델)*/
  A.FUND_CD,
A.ITEM_CD,
A.ITEM_NM,
A.EVL_AMT,
B.NAST_AMT 	
FROM DWPM10530 A
JOIN DWPM10510 B
ON A.FUND_CD = B.FUND_CD 
AND A.IMC_CD = B.IMC_CD 
WHERE A.STD_DT >= '20221005'
AND A.STD_DT = B.STD_DT
AND A.FUND_CD IN (
    '07M02', '07J66', '07J71', '07J76', '07J81', '07J86', 
    '07J91', '07J96', '07J41', '07J34', '2MP24', '1MP30', 
    '1MP35', '1MP40', '1MP45', '1MP50', '1MP55', '1MP60', 
    '3MP01', '3MP02', '07J48', '07J49', 
    '07P70', '6MP07',/*골든그로스*/
    '07Q93', '4MP80' /*골드2080 */
)
"
tictoc::tic()
table_8004 <- dbGetQuery(con_dt, query_8004)
tictoc::toc()
tictoc::tic()
table_8183 <- dbGetQuery(con_dt, query_8183)
tictoc::toc()
dbDisconnect(con_dt)
table_8004 %>% tibble() %>% arrange((STD_DT)) %>% tail()
table_8183 %>% tibble() %>% arrange((STD_DT)) %>% tail()
# djisu<- tbl(con,"DWCI10260") %>% collect() # 환율

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
             "US78462F1030",  "SPDR TRUST SERIES 1", "주식", "미국 주식", "미국 주식"
             
             
             
    )
  ) %>%
  mutate(자산군_소 = factor(자산군_소, levels = c("글로벌 주식","미국 주식","미국 성장주","미국 가치주","미국 중형주",
                                          "선진국 주식","신흥국 주식","한국 주식","호주 주식","글로벌 채권",
                                          "미국 채권","미국 채권 3개월","미국 채권 2년","미국 채권 5년","미국 채권 10년",
                                          "미국 물가채권", "미국 투자등급 회사채","미국 하이일드채권","미국외 글로벌채권","신흥국 달러채권",
                                          "한국 종합채권","한국 단기채권","한국 중장기국공채권","한국 3년국고채권","한국 10년국고채권","한국 회사채권","글로벌 원자재","금","미국 부동산","미국외 부동산","글로벌 인프라","원달러환율",
                                          "외화 유동성","원화 유동성","07J48","07J49"))) 

KOREA_holidays<- 
  tibble( `Holiday Date` = ymd(c("2022-10-03","2022-10-10","2023-01-23","2023-01-24","2023-03-01",#"2022-12-30", 출근은하고 휴장일인 경우는 미국 가격 반영
                                 "2023-05-01","2023-05-05","2023-05-29","2023-06-06","2023-08-15","2023-09-28",
                                 "2023-09-29","2023-10-02","2023-10-03","2023-10-09","2023-12-25",#"2023-12-29",
                                 "2024-01-01","2024-02-09","2024-02-12","2024-03-01","2024-04-10","2024-05-01",
                                 "2024-05-06","2024-05-15","2024-06-06","2024-08-15","2024-09-16","2024-09-17",
                                 "2024-09-18","2024-10-03","2024-10-09","2024-12-25","2024-12-31")))

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



VP_performance_preprocessing<- table_8183 %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  mutate(MOD_STPR = as.double(MOD_STPR)) %>% 
  rename(기준일자=STD_DT,`펀드`= FUND_CD, 펀드명 = FUND_NM ,수정기준가=MOD_STPR) %>% 
  left_join(VP_fund_name,by = join_by(펀드)) %>% 
  filter(IMC_CD=="M03228") %>% 
  select(-IMC_CD)


return_performance_shallow <- function(data, input_date, from_when, base_date = NULL) {
  
  #input_date <- "2024-05-17"
  input_date <- ymd(input_date)
  start_of_month <- floor_date(input_date, "month")
  end_of_month <- ceiling_date(input_date, "month") - days(1)
  # 해당 월의 모든 날짜
  all_dates <- seq(start_of_month, end_of_month, by = "day")
  
  # 평일만 추출
  weekdays_only <- all_dates[!(wday(all_dates) %in% c(1,7))]
  # 휴장일 제외
  tradingdays_only <- weekdays_only[! (weekdays_only %in% KOREA_holidays$`Holiday Date`)]
  
  
  last_day_of_month<- input_date ==max(tradingdays_only)
  print(paste("return_performance_shallow: input_date =", input_date, "from_when =", from_when))
  
  
  # base_date가 NULL일 경우 처리
  if (is.null(base_date)) {
    base_date <- NA_Date_
  } else {
    base_date <- ymd(base_date)
  }
  
  data %>%
    mutate(요일 = wday(기준일자, label = TRUE)) %>%
    filter(!(펀드 %in% c("07J48", "07J49"))) %>%
    dplyr::mutate(filtered_first_date = 
                    case_when(
                      from_when == "YTD" ~   make_date(year(input_date))-days(1),
                      from_when == "ITD" ~ 설정일,
                      from_when == "최근 1년" ~ input_date - years(1),
                      #from_when == "최근 1주" ~ input_date - weeks(1),
                      from_when == "최근 1개월" ~ add_with_rollback(input_date, -months(1)),
                      from_when == "최근 3개월" ~ add_with_rollback(input_date, -months(3)),
                      from_when == "최근 6개월" ~ add_with_rollback(input_date, -months(6)),
                      from_when == "Base date" ~ base_date-days(1),
                      TRUE ~ NA_Date_
                    )
    ) %>%
    mutate(filtered_first_date = if_else((last_day_of_month ==TRUE & from_when !="Base date"), 
                                         (ceiling_date(filtered_first_date[1], unit = "month") - days(1)),
                                         filtered_first_date[1] ) ) %>% 
    group_by(펀드설명,wday(기준일자)) %>% 
    mutate(직전주_수정기준가 = lag(수정기준가, n = 1)) %>%
    mutate(주별수익률 = (수정기준가 / 직전주_수정기준가 - 1)) %>% 
    ungroup() %>% 
    group_by(펀드설명) %>% 
    dplyr::filter( (if_else(from_when =="ITD",TRUE,FALSE) | 설정일<=filtered_first_date) & 기준일자<=input_date & 기준일자>=filtered_first_date  )%>%
    mutate(설정직전날= if_else(sum(설정일>기준일자)!=0,TRUE,FALSE )) %>% 
    mutate(설정직전날가격=  if_else(설정직전날,last(수정기준가[기준일자<설정일]),1000 ) ) %>% 
    mutate(수정기준가_first =if_else((from_when =="ITD" & 설정직전날==TRUE),설정직전날가격,
                                if_else((from_when =="ITD" & 설정직전날==FALSE),1000,수정기준가[1])),
           total_days = difftime(max(기준일자),filtered_first_date,units = "days") %>% as.numeric()) %>% 
    dplyr::filter(요일 == wday(input_date, label = TRUE)) -> before_filtering_first_row
  
  
  check_look_forward<- seq(min(before_filtering_first_row$기준일자)-weeks(1)+days(1),min(before_filtering_first_row$기준일자) , by = "day")
  check_look_forward<- check_look_forward[!(wday(check_look_forward) %in% c(1,7)) & check_look_forward<before_filtering_first_row$filtered_first_date[1]]
  filtering_boolean <- length(check_look_forward[! (check_look_forward %in% KOREA_holidays$`Holiday Date`)])!=0
  
  if(filtering_boolean){
    after_filtering_process <- before_filtering_first_row %>% 
      filter(row_number()!=1 |(기준일자==input_date) ) %>% 
      ungroup() %>% 
      select(기준일자,펀드,펀드설명, 수정기준가, 수정기준가_first, 주별수익률,total_days)
  }else{
    after_filtering_process <- before_filtering_first_row %>% 
      ungroup() %>% 
      select(기준일자,펀드,펀드설명, 수정기준가, 수정기준가_first, 주별수익률,total_days)
  }
  
  
  
  
  print("return_performance_shallow result:")
  print(after_filtering_process )
  
  
}



return_performance_deep<- function(data,input_date,from_when){
  
  data %>% 
    group_by(펀드설명) %>% 
    summarise(
      기준일자 = input_date,
      Return = 수정기준가[n()]/수정기준가_first[1]-1,
      #Return_annualized = mean(주별수익률,na.rm = TRUE)*52, 
      Return_annualized = (수정기준가[n()]/수정기준가_first[1])^(365/total_days[1])-1, 
      Risk_annualized = sd(주별수익률,na.rm=TRUE)*sqrt(52),
      Return_to_Risk = Return_annualized / Risk_annualized,
      # Sharpe_ratio = (Return_annualized-Rf_Return[n()]/100)/Risk_annualized,
      # 무위험 수익률은 2.25로 고정. 혹시 나중에 수정할 일이 있으면 위에 코드 사용
      Sharpe_ratio = (Return_annualized-2.25/100)/Risk_annualized,
      구분 = from_when)
}

# _MP ----------------------------
tictoc::tic()
library(tidyverse)
library(ecos)

#USDKRW <- readRDS("/home/scip-r/MP_monitoring/temp_usdkrw.rds")
USDKRW <- ecos::statSearch(stat_code = "731Y003","0000003",cycle ="D",
                           start_time = "20221004",
                           end_time =max(AP_performance_preprocessing$기준일자) %>% str_remove_all("-") ) %>% tibble() %>%
  select(기준일자=time,`USD/KRW`  = data_value) %>%
  mutate(기준일자= ymd(기준일자))



MP_LTCMA<- bind_rows(
  read_csv("/home/scip-r/MP_monitoring/00_data_updating/rebalancing/rebalancing_20221005.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") ,
  read_csv("/home/scip-r/MP_monitoring/00_data_updating/rebalancing/rebalancing_20231129.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") ,
  read_csv("/home/scip-r/MP_monitoring/00_data_updating/rebalancing/rebalancing_20231226.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") ,
  read_csv("/home/scip-r/MP_monitoring/00_data_updating/rebalancing/rebalancing_20231229.csv",locale = locale(encoding = "CP949")) %>% 
    pivot_longer(cols = -c(`리밸런싱날짜`,`펀드설명`),names_to = "ISIN",values_to = "weight") 
  
) %>% 
  group_by(펀드설명) %>% 
  mutate(설정일 = min(리밸런싱날짜)) %>% 
  ungroup()


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
      
      
      
      "2024-04-08" ,  "TDF2080",  "US9229087369", 0.422077835 ,
      "2024-04-08" ,  "TDF2080",  "US78463V1070", 0.140692612,
      "2024-04-08" ,  "TDF2080",  "US9229087443", 0.307379033 ,
      "2024-04-08" ,  "TDF2080",  "US9219438580", 0.030518196,
      "2024-04-08" ,  "TDF2080",  "US9220428588", 0.089332324,
      "2024-04-08" ,  "TDF2080",  "KR7356540005", 0.004638298 ,
      "2024-04-08" ,  "TDF2080",  "KR7152380002", 0.005361702
    ) %>% 
      mutate(리밸런싱날짜 = ymd(리밸런싱날짜)) %>% 
      mutate(설정일 = ymd("2022-10-05"))
  ) %>% left_join(universe_criteria %>% select(종목코드, 자산군_대,자산군_소) %>% distinct(),by = join_by(ISIN ==종목코드))


con_SCIP <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'SCIP', host = '192.168.195.55')


url_mapping = list(
  "M2WD Index"    = list("dataset_id"= as.integer(57), "dataseries_id"= as.integer(9)),
  "LEGATRUU Index"= list("dataset_id"= as.integer(58), "dataseries_id"= as.integer(9)),
  "KST0000T Index"= list("dataset_id"= as.integer(59), "dataseries_id"= as.integer(9)),
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
  "KR7152380002"  = list("dataset_id"= as.integer(46), "dataseries_id" = as.integer(6)),
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
  # Golden Growth 새로운 Universe
  "KR7278540000" = list("dataset_id"= as.integer(106), "dataseries_id" = as.integer(6)),# KODEX MSCI TR
  "KR7114460009" = list("dataset_id"= as.integer(107), "dataseries_id" = as.integer(6))# ACE국고채3년
  
  
)



url_mapping<- url_mapping %>% enframe() %>%  
  unnest_wider(col = value)

mp_dataid<- url_mapping %>% 
  filter(dataseries_id==6) %>% pull(dataset_id)

MP_historical<- tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id %in% mp_dataid , dataseries_id==6) %>%   
  filter(timestamp_observation>="2022-10-03") %>% 
  collect()

MP_historical_prep<- MP_historical %>% 
  left_join(url_mapping %>% select(-dataseries_id),by = join_by(dataset_id)) %>% 
  mutate(기준일자 = ymd(timestamp_observation)) %>% 
  arrange(기준일자) %>% 
  select(-c(1:4)) %>% 
  mutate(data = map(.x= data, .f = ~jsonlite::parse_json((rawToChar(unlist(.x)))))  ) %>% 
  mutate(USD = map_dbl(.x= data, .f = ~unlist(.x)[1]) ) %>% 
  mutate(KRW = map_dbl(.x= data, .f = ~unlist(.x)[2]) ) %>% 
  mutate(pulling_value = if_else(str_sub(name,1,2) =="KR",KRW,USD)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = pulling_value) %>% 
  mutate(across(.cols =!(contains("KR")|기준일자) , .fns = ~lag(.x ,n=1) ))





crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                           end_date = max(MP_historical_prep$기준일자) ,
                                           by = "day") ,
         ISIN = colnames(MP_historical_prep)[-1]) %>% 
  # 고려사항 1. Data source : Factset 데이터 사용.
  left_join(MP_historical_prep %>% 
              pivot_longer(cols = -기준일자, names_to = "ISIN", values_to = "종가") %>% 
              filter(기준일자>="2022-10-04"),
            by = join_by(기준일자,ISIN)) %>% 
  pivot_wider(id_cols = 기준일자,names_from = ISIN,values_from = 종가) %>% 
  #  고려사항 3. 한국휴일 반영
  mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays$`Holiday Date`,1,0)) %>% 
  mutate(across(.cols = starts_with("US"), .fns = ~if_else(korea_holiday==1, NA, .x) )) %>% 
  select(-korea_holiday) %>% 
  pivot_longer(cols = -기준일자,names_to = "ISIN",values_to = "종가") %>% 
  left_join(USDKRW,by =  join_by(기준일자)) %>% 
  left_join(universe_criteria %>% select(종목코드, 자산군_대,자산군_소) %>% distinct(),by = join_by(ISIN ==종목코드)) %>% 
  mutate(Country = str_sub(ISIN,start=1,end=2)) %>% 
  group_by(ISIN) %>% 
  mutate(first_valid_date = min(기준일자[!is.na(종가)], na.rm = TRUE)) %>%
  filter(기준일자 >= first_valid_date) %>%
  select(-first_valid_date) %>% 
  mutate(종가 = zoo::na.locf(종가)) %>% 
  # 고려사항 4. 환율은 당일 값 사용.
  mutate(`USD/KRW` = zoo::na.locf(`USD/KRW`)) %>% 
  mutate(price_KRW = if_else(Country=="US", 종가*`USD/KRW`,종가)) %>% 
  mutate(last_price_KRW = lag(price_KRW,n=1),
         전일대비등락률 = price_KRW/last_price_KRW-1) %>%
  select(기준일자,ISIN, 전일대비등락률,자산군_대, 자산군_소) %>% 
  filter(기준일자>="2022-10-05") %>% ungroup()  -> MP_performance_preprocessing

MP_LTCMA_all_comb <- 
  MP_LTCMA %>% 
  group_by(리밸런싱날짜,펀드설명) %>%group_keys() %>% 
  group_by(펀드설명) %>% 
  mutate(rebalancing_index= row_number()) %>% 
  # 리밸런싱날짜 당일까지는 이전 비중을 통한 수익률 계산 
  mutate(가중치날짜 = lead(리밸런싱날짜,n=1)) %>% 
  mutate(가중치날짜 = replace_na(가중치날짜,max(AP_performance_preprocessing$기준일자))) %>% 
  mutate(기준일자 = map2(.x = 리밸런싱날짜,.y = 가중치날짜 , .f = ~timetk::tk_make_timeseries(start_date = .x,
                                                                               end_date = .y ,
                                                                               by = "day"))) %>% 
  unnest(cols = 기준일자) %>% 
  ungroup() %>% 
  filter( !(리밸런싱날짜==기준일자 & rebalancing_index!=1) ) %>% 
  inner_join(
    MP_LTCMA %>% 
      select(-설정일) %>%
      filter(weight>0)
    ,by = join_by(리밸런싱날짜, 펀드설명),relationship = "many-to-many"
  ) 

MP_LTCMA_all_comb %>% 
  left_join(MP_performance_preprocessing , by = join_by(기준일자,ISIN,자산군_대,자산군_소)) %>% 
  group_by(기준일자,펀드설명) %>% 
  reframe(전일대비등락률 = sum(weight*전일대비등락률),
          last_rebalance = 리밸런싱날짜[1]) %>% 
  group_by(펀드설명) %>%
  mutate(수정기준가 = 1000*cumprod(전일대비등락률+1)) %>% 
  ungroup()%>% select(-c(전일대비등락률,last_rebalance)) %>% 
  left_join(VP_fund_name,by = join_by(펀드설명)) ->MP_performance_preprocessing_final

MP_LTCMA_all_comb %>% 
  left_join(MP_performance_preprocessing %>% 
              arrange(기준일자)   , by = join_by(기준일자,ISIN,자산군_대,자산군_소)) %>% 
  group_by(펀드설명,ISIN,리밸런싱날짜) %>% 
  mutate(cum_return_since_rebalancing = cumprod(1+전일대비등락률)-1) %>% 
  ungroup() %>% 
  group_by(기준일자,펀드설명) %>% 
  reframe(리밸런싱이후누적수익률 = sum(weight*cum_return_since_rebalancing),
          리밸런싱날짜 = 리밸런싱날짜[1]) %>% 
  group_by(펀드설명,리밸런싱날짜) %>%
  mutate(rebalancing_index= cur_group_id()) %>% {.->temp;temp%>%
      summarise(last_cum_return = last(리밸런싱이후누적수익률)) %>% 
      mutate(cumulative_returns=cumprod(last_cum_return + 1) )->>ttt;temp}%>%
  ungroup() %>% 
  arrange(rebalancing_index, 기준일자) %>%
  left_join(ttt %>% 
              mutate(cumulative_returns = lag(cumulative_returns,n=1),
                     cumulative_returns= replace_na(cumulative_returns,1)
              ) %>% ungroup() %>% select(-last_cum_return), 
            by = join_by(펀드설명,리밸런싱날짜)) %>% 
  mutate(
    최종_누적수익률 = ((1 + 리밸런싱이후누적수익률) * cumulative_returns - 1),
    수정기준가 = (최종_누적수익률+1)*1000) %>%
  ungroup() -> ideal_VP_performance




VP_performance_preprocessing <- bind_rows(VP_performance_preprocessing %>% 
                                            filter(펀드설명 != "Golden Growth"),
                                          ideal_VP_performance %>% 
                                            filter(펀드설명 == "Golden Growth") %>% 
                                            mutate( 펀드 = "6MP07",
                                                    펀드명 = "골든그로스 ideal VP") %>% 
                                            select(기준일자,펀드,펀드명,수정기준가,펀드설명) %>% 
                                            mutate(설정일 = ymd("2023-12-28")))

# _BM ----------------------------



BM_historical<- tbl(con_SCIP,"back_datapoint") %>% 
  filter(dataset_id %in% 57:59) %>% 
  filter(timestamp_observation>="2022-10-03") %>% 
  collect() %>% 
  left_join(url_mapping) %>% 
  mutate(기준일자 = ymd(timestamp_observation)) %>% 
  arrange(기준일자) %>% 
  mutate(data = map_dbl(.x= data, .f = ~as.numeric(rawToChar(unlist(.x))))) %>% 
  pivot_wider(id_cols = 기준일자,names_from = name,values_from = data) %>%  
  mutate(across(.cols = c(2,3), .fns = ~lag(.x ,n=1)))


dbDisconnect(con_SCIP)

BM_daily_price<- 
  
  tibble(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                           end_date = BM_historical$기준일자 %>% max(),
                                           by = "day")) %>% 
  left_join( BM_historical,
             by = join_by(기준일자))





BM_daily_price %>% 
  mutate(korea_holiday = if_else(기준일자 %in% KOREA_holidays$`Holiday Date`,1,0)) %>% 
  mutate(across(.cols = c(2,3), .fns = ~if_else(korea_holiday==1, NA, .x) )) %>%
  select(-korea_holiday) %>% 
  pivot_longer(cols = -기준일자,names_to = "자산군",values_to = "기준가") %>% 
  group_by(자산군) %>% 
  mutate(기준가 = zoo::na.locf(기준가)) %>% ungroup() %>% 
  #pivot_wider(id_cols = 기준일자,names_from = 자산군,values_from = 기준가) %>% view()
  left_join(USDKRW,by =  join_by(기준일자))  %>% 
  mutate(`USD/KRW` = zoo::na.locf(`USD/KRW`)) %>% 
  #mutate(price_KRW = if_else(자산군 %in% c("M2WD Index","LEGATRUU Index"), 기준가*`USD/KRW`,기준가)) %>% 
  mutate(price_KRW = if_else(자산군 %in% c("M2WD Index"), 기준가*`USD/KRW`,기준가)) %>% 
  group_by(자산군) %>%
  mutate(last_price_KRW = lag(price_KRW,n=1),
         전일대비등락률 = price_KRW/last_price_KRW-1) %>%
  select(기준일자,자산군, 전일대비등락률) %>% 
  filter(기준일자>="2022-10-05") %>% ungroup()  -> BM_performance_preprocessing


#MOS 3420 화면에서 수익률 조회한 것과 일치. 소숫점자리가 달라 누적될수록 기준가는 조금씩 달라짐.
# BM_performance_preprocessing %>% 
#   group_by(자산군) %>% 
#   mutate(dd = lag(수정기준가),
#          일수익률 = (수정기준가/dd-1 )*100) %>% 
#   ungroup() %>% 
#   pivot_wider(id_cols = 기준일자,names_from = 자산군,values_from = 일수익률) %>% 
#   mutate(BM_수익률 = 0.4591*`M2WD Index`+0.5409*`LEGATRUU Index`) %>% view()
# 

BM_weight<- 
  MP_LTCMA %>%
  #left_join(universe_criteria %>% select(종목코드,자산군_대, 자산군_소) %>% distinct(), by = join_by(ISIN==종목코드)) %>%
  mutate(자산군 = if_else(자산군_대 == "대체", "주식", 자산군_대)) %>%
  group_by(리밸런싱날짜,펀드설명, 자산군) %>%
  reframe(weight = round(sum(weight),2),
          설정일=설정일[1] ) %>% 
  mutate(weight = if_else((펀드설명 =="MS STABLE" & 리밸런싱날짜=="2022-10-05" & 자산군=="주식"),0.3,weight )) %>% 
  mutate(weight = if_else((펀드설명 =="MS STABLE" & 리밸런싱날짜=="2022-10-05" & 자산군=="채권"),0.7,weight )) %>% 
  mutate(weight = if_else((펀드설명 =="Golden Growth" & 자산군=="주식"),0.6,weight )) %>% 
  mutate(weight = if_else((펀드설명 =="Golden Growth" & 자산군=="채권"),0.4,weight )) %>% 
  mutate(자산군 = case_when(
    자산군 == "주식" ~ "M2WD Index",
    자산군 == "채권" & 펀드설명 %in% c("MS GROWTH", "MS STABLE","Golden Growth") ~ "KST0000T Index",#"KIS 종합 총수익지수",
    자산군 == "채권" ~ "LEGATRUU Index",
    TRUE ~ 자산군
  )) %>% 
  rename(ISIN= 자산군) %>% 
  filter(!(펀드설명=="MS GROWTH" & 리밸런싱날짜!="2022-10-05")) %>% 
  filter(!(펀드설명=="MS STABLE" & 리밸런싱날짜=="2023-11-29"))# %>% 
#mutate(weight = if_else((펀드설명=="MS GROWTH" & ISIN=="M2WD Index"),0.7,
#                        if_else((펀드설명=="MS GROWTH" & ISIN=="KST0000T Index"),0.3,weight)))




BM_weight_all_comb <- 
  BM_weight %>% 
  group_by(리밸런싱날짜,펀드설명) %>%group_keys() %>% 
  group_by(펀드설명) %>% 
  mutate(rebalancing_index= row_number()) %>% 
  # 리밸런싱날짜 당일까지는 이전 비중을 통한 수익률 계산 
  mutate(가중치날짜 = lead(리밸런싱날짜,n=1)) %>% 
  mutate(가중치날짜 = replace_na(가중치날짜,max(AP_performance_preprocessing$기준일자))) %>% 
  mutate(기준일자 = map2(.x = 리밸런싱날짜,.y = 가중치날짜 , .f = ~timetk::tk_make_timeseries(start_date = .x,
                                                                               end_date = .y ,
                                                                               by = "day"))) %>% 
  unnest(cols = 기준일자) %>% 
  ungroup() %>% 
  filter( !(리밸런싱날짜==기준일자 & rebalancing_index!=1) ) %>% 
  inner_join(
    BM_weight %>% 
      select(-설정일) %>%
      filter(weight>0)
    ,by = join_by(리밸런싱날짜, 펀드설명),relationship = "many-to-many"
  )


BM_weight_all_comb %>% filter(weight>0) %>%
  left_join(BM_performance_preprocessing , by = join_by(기준일자,ISIN==자산군)) %>%
  group_by(기준일자,펀드설명) %>% 
  reframe(전일대비등락률 = sum(weight*전일대비등락률),
          last_rebalance = 리밸런싱날짜[1]) %>%
  group_by(펀드설명) |> 
  mutate(수정기준가 = 1000*cumprod(전일대비등락률+1)) %>%
  ungroup()%>% select(-c(전일대비등락률,last_rebalance)) %>% 
  left_join(VP_fund_name,by = join_by(펀드설명)) ->BM_performance_preprocessing_final 
#left_join(rf_data_KORIBOR_3_month %>% select(-c(Rf,unit_name)),by = "기준일자") %>% 
#mutate(Rf_Return = zoo::na.locf(Rf_Return))->BM_performance_preprocessing_final


# Position ----------------------------------------------------------------

# 데이터 불러오기
AP_total <- table_8004 %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  filter(IMC_CD=="003228") %>% 
  select(-IMC_CD) %>% 
  rename(기준일자=STD_DT,펀드 = FUND_CD,종목=ITEM_CD,종목명=ITEM_NM,시가평가액 = EVL_AMT,순자산=NAST_AMT) %>% 
  mutate(across(.cols = c(시가평가액,순자산),.fns = ~as.double(.x)))


VP_total <- table_8004 %>% tibble() %>% 
  mutate(STD_DT = ymd(STD_DT)) %>% 
  arrange(STD_DT) %>% 
  filter(IMC_CD=="M03228") %>% 
  select(-IMC_CD) %>% 
  rename(기준일자=STD_DT,펀드 = FUND_CD,종목=ITEM_CD,종목명=ITEM_NM,시가평가액 = EVL_AMT,순자산=NAST_AMT) %>% 
  mutate(across(.cols = c(시가평가액,순자산),.fns = ~as.double(.x)))


asset_classification_and_adjust <- function(data){
  # 조인 조건 정의
  join_condition <- join_by(종목 == 종목코드, 종목명)
  
  # 조인 수행
  data_joined <- data %>% 
    left_join(universe_criteria, by = join_condition) 
  
  return(data_joined)
  # data_asset_adjust<- data_joined %>% 
  #   mutate(자산군_중 = if_else(자산군_대=="대체","대체",자산군_중)) %>% 
  #   mutate(자산군_소 = if_else(자산군_대=="대체","대체",자산군_소))
  
  #return(data_asset_adjust)
}


AP_asset_adjust<- asset_classification_and_adjust(AP_total) %>% 
  mutate(
    자산군_대 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "유동성", 자산군_대),
    자산군_중 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "원화 유동성", 자산군_중),
    자산군_소 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), factor("원화 유동성"), 자산군_소)
  )

VP_asset_adjust<- asset_classification_and_adjust(VP_total) %>% 
  mutate(
    자산군_대 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "유동성", 자산군_대),
    자산군_중 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "원화 유동성", 자산군_중),
    자산군_소 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), factor("원화 유동성"), 자산군_소)
  )


union(
  
  AP_asset_adjust %>% 
    filter(is.na(자산군_대)) %>% 
    select(종목,종목명) %>% distinct()
  ,
  VP_asset_adjust %>% 
    filter(is.na(자산군_대)) %>% 
    select(종목,종목명) %>% distinct()
  
)# %>% 
# write.csv("new_criteria.csv", row.names = FALSE, fileEncoding = "euc-kr")



calculate_portfolio_weights <- function(data, asset_group ,division) {
  # 먼저, 자산군 별로 순자산비중을 계산
  daily_weights <- data %>%
    filter(자산군_대 != "유동성") %>% 
    mutate(순자산비중 = 시가평가액 / 순자산) %>%
    group_by(기준일자, 펀드, !!sym(asset_group)) %>%
    summarise(daily_weight = sum(순자산비중, na.rm = TRUE), .groups = 'drop')
  
  if(division=="VP"){
    return(daily_weights)
  }else{
    feeder_fund <- daily_weights %>% 
      # 자펀드 비중
      filter(펀드 %in% c("07J48","07J49")) %>% 
      pivot_wider(
        names_from = 펀드,
        values_from = daily_weight,
        values_fill = list(daily_weight = 0)) 
    
    master_fund<- daily_weights %>% 
      #모펀드 비중
      filter(펀드 %in% c("07J34","07J41")) %>%
      pivot_wider(
        names_from = !!sym(asset_group),
        values_from = daily_weight,
        names_prefix = "ratio_")
    if(nrow(master_fund)==0 ){
      daily_weights %>% 
        filter(!(펀드 %in% c("07J34","07J41","07J48","07J49"))) ->final_weights
    }else{
      master_fund %>% inner_join(feeder_fund,relationship = "many-to-many") %>% 
        mutate(daily_weight = `ratio_07J48`*`07J48`+`ratio_07J49`*`07J49`) %>% 
        select(기준일자,펀드,!!sym(asset_group),daily_weight)->mysuper_position
      
      # 최종 포트폴리오 가중치 데이터 프레임 생성
      
      daily_weights %>% 
        filter(!(펀드 %in% c("07J34","07J41","07J48","07J49"))) %>% 
        bind_rows(mysuper_position)  ->final_weights
    }
    
    return(final_weights)
  }
  
  
}

MP_LTCMA_all_comb %>% 
  left_join(MP_performance_preprocessing %>% 
              arrange(기준일자)   , by = join_by(기준일자,ISIN,자산군_대,자산군_소)) %>% 
  group_by(펀드설명,ISIN,리밸런싱날짜) %>% 
  mutate(cum_return_since_rebalancing = cumprod(1+전일대비등락률)-1) %>% 
  ungroup() %>% 
  group_by(기준일자,펀드설명,ISIN) %>% 
  reframe(리밸런싱이후누적비중 = weight*(1+cum_return_since_rebalancing),
          리밸런싱날짜 = 리밸런싱날짜[1],
          자산군_대,자산군_소) ->ideal_VP_position


calculate_portfolio_weights_from_MP_to_VP <- function(data, asset_group ,division) {
  # 먼저, 자산군 별로 순자산비중을 계산
  daily_weights <- data %>%
    #ideal_VP_position %>% 
    #group_by(기준일자, 펀드설명, !!sym(asset_group)) %>%
    group_by(기준일자, 펀드설명) %>%
    reframe(daily_weight = 리밸런싱이후누적비중/sum(리밸런싱이후누적비중, na.rm = TRUE),
            자산군_소,자산군_대) %>% 
    group_by(기준일자, 펀드설명, !!sym(asset_group)) %>%
    reframe(daily_weight = sum(daily_weight, na.rm = TRUE))
  
  
  return(daily_weights)
  
}

# 복제율 ----
#replicate_disparate_rate <- reactive({


# AP와 VP의 포지션 데이터 계산을 위한 reactive 표현식
position_AP_summarised <- 
  calculate_portfolio_weights(
    data = AP_asset_adjust,
    asset_group = "자산군_소",
    division = "AP"
  )


position_VP_summarised <-
  bind_rows(
    calculate_portfolio_weights_from_MP_to_VP(ideal_VP_position,asset_group = "자산군_소",division = "MP") %>% 
      filter(펀드설명 =="Golden Growth") %>% 
      rename(펀드=펀드설명) %>% 
      mutate(펀드 = "6MP07"),
    calculate_portfolio_weights(
      data = VP_asset_adjust,
      asset_group = "자산군_소",
      division = "VP"
    ) %>% 
      filter(펀드 != "6MP07")
  )
  


# position_AP와 position_VP를 펀드설명을 기준으로 full_join하고 차이 계산
crossing(기준일자 =unique(AP_asset_adjust$기준일자),
         펀드설명 =  Fund_Information %>% filter(구분 %in% c("TDF","BF")) %>% pull(펀드설명),
         universe_criteria %>%
           filter(자산군_대!="유동성") %>% 
           filter(!(자산군_소%in%c("07J48","07J49",NA)) ) %>%
           select(자산군_대,자산군_소) %>% distinct()
         #펀드설정일 = "??-??-??"
) %>% 
  left_join(full_join(position_AP_summarised %>%
                        left_join(AP_fund_name,by = join_by(펀드)),
                      position_VP_summarised %>%
                        left_join(VP_fund_name,by = join_by(펀드)),
                      by = join_by(기준일자, 펀드설명, 자산군_소),
                      suffix = c("_AP", "_VP"))  , by=join_by(기준일자,펀드설명,자산군_소)) %>% 
  
  left_join(
    
    MP_LTCMA %>%
      group_by(리밸런싱날짜,펀드설명,자산군_소) %>%
      reframe(daily_weight_MP = sum(weight)) ,
    by = join_by(기준일자>=리밸런싱날짜,펀드설명,자산군_소)
    
  ) %>% 
  filter(!is.na(리밸런싱날짜)) %>% 
  group_by(기준일자,펀드설명) %>% 
  filter(리밸런싱날짜==max(리밸런싱날짜,na.rm = TRUE) ) %>% 
  mutate(across(starts_with("daily_weight"), ~replace_na(., 0))) %>%
  # reframe(across(starts_with("daily"),.fns = ~sum(.x)))
  mutate(`비중(AP-VP)` = daily_weight_AP - daily_weight_VP) %>% 
  mutate(`비중(VP-MP)` =daily_weight_VP -daily_weight_MP ) %>% 
  ungroup()->AP_VP_MP_diff_summarised



AP_VP_MP_diff_summarised %>%
  select(-펀드_AP,-펀드_VP) %>% 
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
  reframe(`괴리율(VP&MP, 주식+대체 대분류)` = abs(normalize_VP-normalize_MP) ,
          `괴리율(AP&MP, 주식+대체 대분류)` = abs(normalize_AP-normalize_MP) ,
          `괴리율N.(VP&MP,주식+대체 소분류)`= max(abs(daily_weight_VP/normalize_VP - daily_weight_MP/normalize_MP )) ,#`max[Normalize_(VP-MP)주식+대체_소분류]`
          `괴리율N.(AP&MP,주식+대체 소분류)`= max(abs(daily_weight_AP/normalize_AP - daily_weight_MP/normalize_MP )) ,#`max[Normalize_(AP-MP)주식+대체_소분류]`
          `복제율N.(AP&VP,주식+대체 소분류)` = sum(min_AP_VP) ,#`Sum[min(Normalize_(AP,VP)주식+대체_소분류)]`
          `복제율(AP&VP,주식+대체 & 채권 대분류)`= sum(`min_주식+대체_대분류`[1],min_채권_대분류[1]) #`Sum[min(Normalize_(AP,VP)주식+대체&채권_대분류)]`
  ) %>% distinct() -> replicate_disparate_rate


plot_metric_except_TE <- function(df, metric) {
  # 해당 Metric의 데이터 필터링
  metric_data <- df %>%
    filter(Metric == metric) %>%
    mutate(구분 = factor(구분, levels = c("AP", "VP", "MP", "BM")))
  
  # percent_rank를 사용하여 백분위 계산
  metric_data <- metric_data %>%
    mutate(percent_rank = percent_rank(value))
  
  # 텍스트 레이블을 위한 조건부 처리
  metric_data <- metric_data %>%
    mutate(text_label = ifelse(Metric %in% c("Sharpe_ratio","Return_to_Risk"),
                               sprintf("%.2f", value),
                               label_percent(accuracy = 0.01)(value)))
  
  # 히트맵 생성
  ggplot(metric_data, aes(x = 펀드설명, y = 구분, fill = percent_rank)) +
    geom_tile() +
    geom_text(aes(label = text_label), vjust = 1.5) +
    scale_fill_gradient2(low = "blue", mid = "white", high = "red", 
                         midpoint = 0.5, 
                         guide = guide_legend(title = NULL)) +
    scale_y_discrete(limits = rev(levels(metric_data$구분))) +
    labs(title = paste("Metric:", metric), x = "펀드설명", y = "구분") +
    theme_minimal()
}

# 글자색 조정할 수 있는 함수
# plot_metric_except_TE <- function(df, metric) {
#   # 해당 Metric의 데이터 필터링
#   metric_data <- df %>%
#     filter(Metric == metric) %>%
#     mutate(구분 = factor(구분, levels = c("AP", "VP", "MP", "BM")))
#   
#   # percent_rank를 사용하여 백분위 계산
#   metric_data <- metric_data %>%
#     mutate(percent_rank = percent_rank(value))
#   
#   # 텍스트 레이블과 색상을 위한 조건부 처리
#   metric_data <- metric_data %>%
#     mutate(text_label = ifelse(Metric %in% c("Sharpe_ratio","Return_to_Risk"),
#                                sprintf("%.2f", value),
#                                label_percent(accuracy = 0.01)(value)),
#            text_color = ifelse(abs(percent_rank-0.5) > 0.35, "white", "black"))
#   
#   # 히트맵 생성
#   ggplot(metric_data, aes(x = 펀드설명, y = 구분, fill = percent_rank)) +
#     geom_tile() +
#     geom_text(aes(label = text_label, color = text_color), vjust = 1.5, show.legend = FALSE) +
#     scale_fill_gradient2(low = "blue", mid = "white", high = "red", 
#                          midpoint = 0.5, 
#                          guide = guide_legend(title = NULL)) +
#     scale_color_identity() +
#     guides(color = FALSE) +  # 텍스트 색상에 대한 범례 제거
#     scale_y_discrete(limits = rev(levels(metric_data$구분))) +
#     labs(title = paste("Metric:", metric), x = "펀드설명", y = "구분") +
#     theme_minimal()
# }

plot_metric_TE <- function(df, metric) {
  # 해당 Metric의 데이터 필터링
  metric_data <- df %>% 
    filter(Metric == metric) %>% 
    mutate(구분 = factor(구분, levels = c("AP", "VP"))) %>% 
    # percent_rank를 사용하여 백분위 계산
    mutate(percent_rank = percent_rank(value))  
  
  
  # 텍스트 레이블을 위한 조건부 처리
  metric_data <- metric_data %>%
    mutate(text_label = ifelse(Metric %in%c("IR") ,
                               sprintf("%.2f", value),
                               label_percent(accuracy = 0.01)(value)))
  
  # 히트맵 생성
  ggplot(metric_data, aes(x = 펀드설명, y = 구분, fill = percent_rank)) +
    geom_tile() +
    geom_text(aes(label = text_label), vjust = 1.5) +
    scale_fill_gradient2(low = "blue", mid = "white", high = "red", 
                         midpoint = 0.5, 
                         guide = guide_legend(title = NULL)) +
    scale_y_discrete(limits = rev(levels(metric_data$구분))) +
    labs(title = paste("Metric:",metric ), x = "펀드설명", y = "구분") +
    theme_minimal()
}





