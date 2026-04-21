library(tidyverse)
Fund_cd <- "07J48"
Fund_Information <-  tibble(
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"TDF2080",
           "MS STABLE",	"MS GROWTH","Golden Growth" ),
  구분= c("TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","TDF","BF","BF","BF")
)


con_dt <- dbConnect(RMariaDB::MariaDB(), username = 'solution', password = 'Solution123!', dbname = 'dt', host = '192.168.195.55')

tbl(con_dt,"DWPI10021") %>% 
  select(ITEM_CD,ITEM_WHL_NM,TKR_CD) %>% 
  filter(str_sub(ITEM_CD,1,2)=="KR" |str_sub(ITEM_CD,1,2)=="US") %>% 
  filter(ITEM_CD %in% !!(AP_total$종목 %>% unique())) %>% 
  filter(!str_detect(ITEM_WHL_NM,"\\(콜")) %>% 
  distinct() %>%
  collect() %>% 
  mutate(TKR_CD = if_else(str_sub(ITEM_CD,1,2)=="US",TKR_CD, paste0(str_sub(ITEM_CD,4,9)," KR") )) %>% 
  rename(종목=ITEM_CD,ticker=TKR_CD) ->ticker_matching

return_RSP_ISP <- function(`매매금액(억)`=0,
                           Fund_cd, Date,
                           gap_setting_specific_conditions=NULL,
                           gap_setting_specific_values=NULL) {
  
  AP_total %>%
    filter(펀드 == Fund_cd) %>%
    left_join(ticker_matching,by = join_by(종목)) %>% 
    filter(기준일자 == ymd(Date)) %>%
    asset_classification_and_adjust() %>%
    mutate(
      자산군_대 = if_else(is.na(자산군_대) & str_detect(종목명, "콜론"), "유동성", 자산군_대),
      자산군_중 = if_else(is.na(자산군_중) & str_detect(종목명, "콜론"), "원화 유동성", 자산군_중),
      자산군_소 = if_else(is.na(자산군_소) & str_detect(종목명, "콜론"), factor("원화 유동성"), 자산군_소)
    ) %>%
    filter(자산군_대 != "유동성") %>%
    mutate(순자산비중 = 시가평가액 / 순자산)-> fund_AP
  
  # 데이터 처리 및 할당
  assign(str_glue("fund_AP_{Fund_cd}"), fund_AP, envir = .GlobalEnv)
  
  
  fund_AP %>% 
    group_by(자산군_소) %>%
    summarize(weight = sum(순자산비중),
              시가평가액 = sum(시가평가액),
              ticker_list = list(ticker) ) %>%  
    mutate(
      ticker_list = map_chr(ticker_list, ~ paste(.x, collapse = " , "))
    ) %>% mutate(유동성반영N.Weight = 시가평가액 / sum(시가평가액,`매매금액(억)` * 100000000)) -> RSP_weight
  
  VP_weight <- VP_total %>% 
    filter(펀드 %in% c("3MP01","3MP02")) %>% 
    #eft_join(ticker_matching,by = join_by(종목)) %>% 
    filter(기준일자==ymd(Date)) %>% 
    asset_classification_and_adjust() %>% 
    filter(자산군_대 != "유동성") %>% 
    mutate(순자산비중 = 시가평가액 / 순자산) %>% 
    group_by(펀드,자산군_소) %>% 
    reframe(
      자산군_대 = 자산군_대[1],
      weight = sum(순자산비중)) %>%
    filter(if(Fund_cd == "07J48") 자산군_대 !="채권" else 자산군_대 =="채권")  %>% 
    group_by(펀드) %>% 
    mutate(normalize_EQ = weight/sum(weight)) %>% 
    group_by(자산군_소) %>% 
    reframe(Avg.N.EQ = mean(normalize_EQ)) 
  
  result <- VP_weight %>%
    left_join(RSP_weight, by = "자산군_소") %>%
    mutate(Gap = Avg.N.EQ - 유동성반영N.Weight)
  
  if (!is.null(gap_setting_specific_conditions)) {
    for (i in seq_along(gap_setting_specific_conditions)) {
      
      result <- result %>%
        mutate(Gap = if_else(eval(parse(text = gap_setting_specific_conditions[[i]])),
                             gap_setting_specific_values[[i]], Gap))
    }
  }
  
  result %>%
    mutate(매매금액 = Gap / sum(Gap) * `매매금액(억)` * 100000000,
           `매매 후 N.Weight` = (시가평가액 + 매매금액) / sum(시가평가액 , `매매금액(억)` * 100000000))
}


recent_trade_date <- ymd("2024-10-30")


return_RSP_ISP(`매매금액(억)` = 4.2,
               Fund_cd = "07J48",Date = recent_trade_date,
               gap_setting_specific_conditions = list('자산군_소=="미국 성장주"',
                                                      '자산군_소=="한국 주식"'),
               gap_setting_specific_value=list(0.01,
                                               0.00)
               # gap_setting_specific_conditions = list('자산군_소=="한국 주식"'),
               # gap_setting_specific_value=list(0.00)
) -> buy_sell_list_RSP


# buy_sell_list_RSP %>% left_join(
#   return_RSP_ISP(`매매금액(억)` = 2.2,
#                  Fund_cd = "07J48",Date = recent_trade_date,
#                  gap_setting_specific_conditions = list('자산군_소=="한국 주식"'),
#                  gap_setting_specific_value=list(0.00)
#   ) %>% select(자산군_소, `매매 후 N.Weight_yesterday`= `매매 후 N.Weight`,매매금액_yesterday=매매금액)
#   
# ) %>% 
#   mutate(매매금액_today = 매매금액-매매금액_yesterday) 

buy_sell_list_RSP
#buy_sell_list_RSP %>% arrange(desc(자산군_소))
fund_AP_07J48

return_RSP_ISP(`매매금액(억)` =3,
               Fund_cd = "07J49",Date = recent_trade_date,
               #gap_setting_specific_conditions = list('자산군_소=="미국 하이일드채권"'),
               #gap_setting_specific_value=list(0)
) -> buy_sell_list_ISP
# select(자산군_소, 매매금액)

buy_sell_list_ISP
fund_AP_07J49

list("RSP_position" =buy_sell_list_RSP,
     "RSP_자산군_소"=fund_AP_07J48,
     "ISP_position" =buy_sell_list_ISP,
     "ISP_자산군_소"=fund_AP_07J49) %>% writexl::write_xlsx(str_glue("Mysuper_매매/rsp_isp_{today()}.xlsx"))

recent_trade_date

# fund_AP_07J48 %>% 
#   arrange(자산군_소,-순자산비중) %>% 
#   left_join(buy_sell_list_RSP,by = join_by(자산군_소)) %>% 
#   #left_join(MP_price_KRW(Date = "2024-04-18",`USD/KRW` = 1393),by = join_by(종목==name,자산군_소)) %>% 
#   group_by(자산군_소) %>% 
#   mutate(`주문 주수` = 매매금액/원화환산) %>% 
#   mutate(`매매 후 순자산 비중` = (시가평가액+매매금액)/(순자산+매매금액)) %>% 
#   filter(!(자산군_소=="미국 성장주"&종목명 !="SPDR S&P 500 Growth") ) %>% 
#   filter(!(자산군_소=="금"&종목명 !="ISHARES GOLD TRUST MICRO") )  %>% 
#   select(-value,-종목,-펀드) %>% view()
# 
# fund_AP_07J49 %>% 
#   arrange(자산군_소,-순자산비중) %>% 
#   left_join(buy_sell_list_ISP,by = join_by(자산군_소)) %>% 
#   left_join(MP_price_KRW(Date = "2024-04-18",`USD/KRW` = 1393),by = join_by(종목==name,자산군_소)) %>% 
#   group_by(자산군_소) %>% 
#   mutate(`주문 주수` = 매매금액/원화환산) %>% 
#   mutate(`매매 후 순자산 비중` = (시가평가액+매매금액)/(순자산+매매금액)) %>% view()





# 제약조건 : 하나의 운용사 50% 이내
fund_AP_07J48 %>% 
  arrange(자산군_소,-순자산비중) %>% 
  mutate(운용사명 = str_split(종목명," ",simplify = TRUE)[,1] ) %>% 
  mutate(운용사명 = str_to_upper(운용사명)) %>% 
  group_by(운용사명) %>% 
  reframe(w = sum(순자산비중)) %>% 
  arrange(-w)
# left_join(MP_price_KRW(Date = "2024-04-10",`USD/KRW` = 1365) , by = join_by(종목==name,자산군_소)) %>% view()


fund_AP_07J49 %>% 
  arrange(자산군_소,-순자산비중) %>% 
  mutate(운용사명 = str_split(종목명," ",simplify = TRUE)[,1] ) %>% 
  mutate(운용사명 = str_to_upper(운용사명)) %>% 
  group_by(운용사명) %>% 
  reframe(w = sum(순자산비중)) %>% 
  arrange(-w)





# ETF CU 주수 정보 ------------------------------------------------------------


