library(tidyverse)
library(ecos)

USDKRW <- ecos::statSearch(stat_code = "731Y003","0000003",cycle ="D",
                           start_time = "20221004",end_time = "20240112") %>% tibble() %>% 
  select(기준일자=time,`USD/KRW`  = data_value) %>% 
  mutate(기준일자= ymd(기준일자))

 


MP_daily_price<- read_csv("00_data/combined_MP_data.csv")



MP_daily_price<- 
  crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-03",
                                             end_date = "2024-01-12",
                                             by = "day") ,
           ISIN = unique(MP_daily_price$ISIN)) %>% 
  full_join(MP_daily_price,by =  join_by(기준일자==date,ISIN )) %>% 
  group_by(ISIN) %>% 
  filter(!(str_sub(ISIN,1,2)=="KR" & row_number(ISIN)==1)) %>% 
  mutate(PX_LAST = zoo::na.locf(PX_LAST)) %>% ungroup()
 
MP_daily_price %>% 
  left_join(universe_criteria,by =  join_by(ISIN == 종목코드)) %>% 
  
  mutate(Country = str_sub(ISIN,start=1,end=2)) %>% 
  
  group_by(ISIN) %>% 
  # 미국 종목의 경우 전날 종가를 사용함.
  mutate(PX_LAST = if_else(Country=="US", lag(PX_LAST,n=1),PX_LAST)) %>% 
  ungroup() %>% 
  filter(기준일자>="2022-10-04") %>% 
  left_join(USDKRW,by =  join_by(기준일자)) %>% 
  mutate(`USD/KRW` = zoo::na.locf(`USD/KRW`)) %>% 
  mutate(price_KRW = if_else(Country=="US", PX_LAST*`USD/KRW`,PX_LAST)) %>% 
  group_by(ISIN) %>% 
  # 전날 설정일 전날 종가를 1000원으로 환산하는 작업.
  mutate(regularized_price_KRW = price_KRW/price_KRW[1]*1000) %>% 
  select(기준일자,ISIN, 수정기준가=regularized_price_KRW, 자산군_소) %>% 
  filter(기준일자>="2022-10-05") %>% ungroup()  -> MP_performance_preprocessing




MP_LTCMA_2023<- read_csv("00_data/MP_LTCMA_2023.csv", locale = locale(encoding = "CP949")) 

colnames(MP_LTCMA_2023) <- c("펀드설명","US9229087369",	"US9229087443",	"US9219438580",
                             "US9220428588",	"US4642861037",	"US9229085538",	
                             "US9220426764",	"US78463X8552",	"US46090F1003",
                             "KR7273130005",	"KR7356540005",	"KR7385540000",
                             "KR7385550009",	"KR7152380002",	"US4642871762")

#MP_LTCMA_2023 %>% write_csv("MP_LTCMA_2023.csv")

MP_LTCMA_2023<- MP_LTCMA_2023 %>%   
  pivot_longer(cols = -`펀드설명`,names_to = "ISIN",values_to = "weight") %>% 
  left_join(MP_performance_preprocessing %>% select(ISIN,자산군_소) %>% distinct(),
            by = join_by(ISIN))


# 리밸런싱 날짜 기점으로 crossing 다르게 하여, bind_row로 합치면 기준가 계산가능
crossing(기준일자 = MP_performance_preprocessing$기준일자,
         MP_LTCMA_2023) %>% 
  left_join(MP_performance_preprocessing , by = join_by(기준일자,ISIN,자산군_소)) %>% 
  group_by(기준일자,펀드설명) %>% 
  reframe(수정기준가 = sum(weight*수정기준가)) %>% 
  left_join(VP_fund_name,by = join_by(펀드설명)) %>% 
  left_join(rf_data_KORIBOR_3_month %>% select(-c(Rf,unit_name)),by = "기준일자") %>% 
  
  mutate(Rf_Return = zoo::na.locf(Rf_Return))->MP_performance_preprocessing_final


MP_performance_preprocessing_final %>% 
  group_by(펀드설명) %>% 
  mutate(전일기준가 = lag(수정기준가),
         수익률 = (수정기준가/전일기준가-1)*100) %>% view()


MP_performance<- MP_performance_preprocessing_final %>% 
  return_performance(input_date = "2023-09-12",from_when = "ITD") 








