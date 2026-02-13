
BM_daily_price<- 
  
  tibble(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-03",
                                           end_date = "2024-01-12",
                                           by = "day")) %>% 
  left_join(read_csv("00_data/BM_historical_upto_20240112_data.csv", locale = locale(encoding = "CP949")),
            by = join_by(기준일자==date)) 



#KST0000T Index 는 KIS 종합 총수익지수를 의미.


BM_daily_price %>% 
  pivot_longer(cols = -기준일자,names_to = "자산군",values_to = "기준가") %>% 
  group_by(자산군) %>% 
  # 미국 종목의 경우 전날 종가를 사용함.
  mutate(기준가 = if_else(자산군!="KST0000T Index", lag(기준가,n=1),기준가)) %>% 
  filter(기준일자>="2022-10-04" )  %>% 
  mutate(기준가 = zoo::na.locf(기준가)) %>% ungroup() %>% 
  left_join(USDKRW,by =  join_by(기준일자))  %>% 
  mutate(`USD/KRW` = zoo::na.locf(`USD/KRW`)) %>% 
  mutate(price_KRW = if_else(자산군!="KST0000T Index", 기준가*`USD/KRW`,기준가)) %>% 
  group_by(자산군) %>% 
  # 전날 설정일 전날 종가를 1000원으로 환산하는 작업.
  mutate(regularized_price_KRW = price_KRW/price_KRW[1]*1000) %>% 
  select(기준일자,자산군, 수정기준가=regularized_price_KRW) %>% 
  filter(기준일자>="2022-10-05") %>% ungroup()  -> BM_performance_preprocessing


BM_weight_2023<- MP_LTCMA_2023 %>%
  left_join(universe_criteria %>% select(자산군_대, 자산군_소) %>% distinct(), by = "자산군_소") %>%
  mutate(자산군 = if_else(자산군_대 == "대체", "주식", 자산군_대)) %>%
  group_by(펀드설명, 자산군) %>%
  reframe(weight = round(sum(weight),4) ) %>% 
  mutate(자산군 = case_when(
    자산군 == "주식" ~ "M2WD Index",
    자산군 == "채권" & 펀드설명 %in% c("MS GROWTH", "MS STABLE") ~ "KST0000T Index",
    자산군 == "채권" ~ "LEGATRUU Index",
    TRUE ~ 자산군
  ))



# 리밸런싱 날짜 기점으로 crossing 다르게 하여, bind_row로 합치면 기준가 계산가능
crossing(기준일자 = unique(BM_performance_preprocessing$기준일자),
         BM_weight_2023) %>% 
  left_join(BM_performance_preprocessing , by = join_by(기준일자,자산군)) %>% 
  group_by(기준일자,펀드설명)  %>% 
  reframe(수정기준가 = sum(weight*수정기준가)) %>% 
  left_join(VP_fund_name,by = join_by(펀드설명)) %>% 
  left_join(rf_data_KORIBOR_3_month %>% select(-c(Rf,unit_name)),by = "기준일자") %>% 
  
  mutate(Rf_Return = zoo::na.locf(Rf_Return))->BM_performance_preprocessing_final


BM_performance_preprocessing_final %>% 
  filter(펀드설명 == "MS GROWTH") %>% 
  mutate(last_day = lag(수정기준가)) %>% 
  mutate(일별수익률 =(수정기준가 /last_day -1) *100) %>% view()


BM_performance<- BM_performance_preprocessing_final %>% 
  return_performance(input_date = "2023-09-12",from_when = "ITD") 

BM_performance




# 추적오차 = (주간수익률 AP-주간수익률VP) 의 표준편차 *sqrt(52)
