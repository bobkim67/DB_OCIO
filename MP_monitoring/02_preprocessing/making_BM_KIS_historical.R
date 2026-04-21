library(httr)
library(jsonlite)
library(tidyverse)

input_date <- ymd("2022-10-03")
return_KIS_BM<- function(input_date){
  prep_date <-format(input_date, "%Y.%m.%d")
  res <- VERB("GET", url = str_glue("https://www.bond.co.kr/kisnet/100?baseDate={prep_date}"))
  # JSON 데이터를 R의 데이터 프레임으로 변환
  data <- fromJSON(content(res, "text", encoding = "UTF-8"))
  
  # 데이터 확인
  result <- data %>% filter(indexName=="종합채권지수") %>% pull(value01) %>% as.numeric()
  return(result)
}
format(ymd("2022-12-11"), "%Y.%m.%d")

KIS_BM<- tibble(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-04",
                                         end_date = "2024-01-12",
                                         by = "day")) %>% 
  mutate(`KIS 종합 총수익지수` = map_dbl(.x =기준일자 ,.f = ~return_KIS_BM(.x)))

KIS_BM %>% 
  write_csv("00_data/BM_KIS_historical_upto_20240112_data.csv")


# MSCI, Barclays Global은 블룸버그를 통해 데이터 저장 