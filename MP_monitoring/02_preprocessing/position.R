library(tidyverse)
library(rlang) # sym() 함수를 사용하기 위해 필요

# 데이터 불러오기
AP_total <- 
  bind_rows(
    readxl::read_excel("00_data/통합 명세_AP.xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)),
    readxl::read_excel("00_data/통합 명세_AP_(20231202_20240109).xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)) %>% 
      filter(기준일자<="2024-01-09")
  )

AP_fund_name<- tibble(
  펀드 = c("07M02",	"07J66",	"07J71",	"07J76",	"07J81",	"07J86",	"07J91",	"07J96",	"07J41",	"07J34"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"MS STABLE",	"MS GROWTH"))

VP_total <- 
  bind_rows(
    readxl::read_excel("00_data/통합 명세_VP.xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)),
    readxl::read_excel("00_data/통합 명세_VP_(20231202_20240109).xlsx") |> 
      mutate(기준일자= ymd(기준일자)) %>% select(-c(순번,발행일)) %>% 
      filter(기준일자<="2024-01-09")
  )

VP_fund_name<- tibble(
  펀드 = c("2MP24",	"1MP30",	"1MP35",	"1MP40",	"1MP45",	"1MP50",	"1MP55",	"1MP60",	"3MP01",	"3MP02"),
  펀드설명 = c("TIF",	"TDF2030",	"TDF2035",	"TDF2040",	"TDF2045",	"TDF2050",	"TDF2055",	"TDF2060",	"MS STABLE",	"MS GROWTH"))



universe_criteria <- read_csv("00_data/universe_criteria.csv", locale = locale(encoding = "CP949")) |> 
  distinct() %>% 
  # 23년 말 기준으로 새롭게 편입된 US 금 두 종목 존재. universe DB에 업데이트
  bind_rows(
    tribble( ~종목코드, ~종목명,~자산군_대,~자산군_중,~자산군_소,
             "US98149E3036", "SPDR GOLD MINISHARES TRUST" , "대체","원자재","금",  
             "US46436F1030", "ISHARES GOLD TRUST MICRO"   , "대체","원자재","금"
    )
  )


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


AP_asset_adjust<- asset_classification_and_adjust(AP_total)
VP_asset_adjust<- asset_classification_and_adjust(VP_total)



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
    
    
    master_fund %>% inner_join(feeder_fund,relationship = "many-to-many") %>% 
      mutate(daily_weight = ratio_07J48*`07J48`+ratio_07J49*`07J49`) %>% 
      select(기준일자,펀드,!!sym(asset_group),daily_weight)->mysuper_position
    
    # 최종 포트폴리오 가중치 데이터 프레임 생성
    
    daily_weights %>% 
      filter(!(펀드 %in% c("07J34","07J41","07J48","07J49"))) %>% 
      bind_rows(mysuper_position)  ->final_weights
    
    return(final_weights)
  }
  
  
}


asset_group <- "자산군_소"
position_AP <- 
  calculate_portfolio_weights(
    data = AP_asset_adjust,
    asset_group = asset_group,
    division = "AP"
  )



position_VP <- 
  calculate_portfolio_weights(
    data = VP_asset_adjust,
    asset_group = asset_group,
    division = "VP"
  )

# position_AP와 position_VP를 펀드설명을 기준으로 full_join하고 차이 계산
AP_VP_MP_diff <-
  
  crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-05",
                                             end_date = "2024-03-13",
                                             by = "day"),
           펀드설명 =  AP_fund_name$펀드설명,
           universe_criteria %>%
                    filter(!(자산군_소%in%c("07J48","07J49",NA)) ) %>%
                    select(자산군_대,자산군_소) %>% distinct()
           #펀드설정일 = "??-??-??"
  ) %>%
  left_join(full_join(position_AP %>%
                        left_join(AP_fund_name),
                      position_VP %>%
                        left_join(VP_fund_name),
                      by = c("기준일자", "펀드설명", asset_group),
                      suffix = c("_AP", "_VP"))  , by=join_by(기준일자,펀드설명,!!sym(asset_group))) %>% 
  
  left_join(
    
    MP_LTCMA %>%
      group_by(리밸런싱날짜,펀드설명,!!sym(asset_group)) %>%
      reframe(daily_weight_MP = sum(weight)) ,
    by = join_by(기준일자>=리밸런싱날짜,펀드설명,!!sym(asset_group))
    
  ) %>%  
  group_by(기준일자,펀드설명) %>% 
  filter(리밸런싱날짜==max(리밸런싱날짜,na.rm = TRUE) ) %>% 
  mutate(across(starts_with("daily_weight"), ~replace_na(., 0))) %>%view()
  # reframe(across(starts_with("daily"),.fns = ~sum(.x)))
  mutate(`비중(AP-VP)` = daily_weight_AP - daily_weight_VP) %>% 
  mutate(`비중(VP-MP)` =daily_weight_VP -daily_weight_MP ) %>% 
  ungroup()

# 효율화 시도   
  # crossing(기준일자 = timetk::tk_make_timeseries(start_date = "2022-10-05",
  #                                            end_date = "2024-03-13",
  #                                            by = "day"),
  #          펀드설명 =  AP_fund_name$펀드설명,
  #          universe_criteria %>%
  #            filter(!(자산군_소%in%c("07J48","07J49",NA)) ) %>%
  #            select(자산군_대,자산군_소) %>% distinct()
  #          #펀드설정일 = "??-??-??"
  # ) %>% left_join(
  #   
  #   MP_LTCMA %>%
  #     group_by(리밸런싱날짜,펀드설명,!!sym(asset_group)) %>%
  #     reframe(daily_weight_MP = sum(weight)), by = join_by(기준일자==리밸런싱날짜, 펀드설명,자산군_소)
  # ) %>%  
  #   left_join(
  #     MP_LTCMA %>% 
  #       group_by(리밸런싱날짜,펀드설명,!!sym(asset_group)) %>%
  #       reframe(daily_weight_MP = sum(weight)) ,by = join_by(펀드설명,자산군_소,daily_weight_MP)
  #     
  #   )
  # mutate(리밸런싱날짜 = 기준일자[!is.na(daily_weight_MP)])
  # group_by(펀드설명,자산군_대,자산군_소) %>% 
  #   mutate(daily_weight_MP = if_else(row_number() == 1 & is.na(daily_weight_MP), 0, daily_weight_MP)) %>% # 첫 번째 관측치가 NA일 경우 0으로 대체
  #   mutate(daily_weight_MP = zoo::na.locf(daily_weight_MP, na.rm = FALSE)) %>% # 나머지 NA를 이전 값으로 채움
  #   ungroup() # 그룹화 해제
  
  

MP_LTCMA %>% inner_join(
  AP_VP_MP_diff %>% 
    filter(기준일자=="2023-12-27") %>%
    group_by(펀드설명) %>% 
    reframe(리밸런싱날짜 =리밸런싱날짜[1])
  
) %>% 
  group_by(펀드설명,자산군_대) %>% 
  reframe(s=sum(weight))




# 
# 
# # 면적 차트 생성
# position |> 
#   ggplot(aes(x = 기준일자, y = daily_weight, fill = !!sym(asset_group))) +
#   geom_area(alpha = 0.8) +
#   scale_x_date(date_labels = "%Y-%m-%d", date_breaks = "3 month") +
#   theme_minimal() +
#   labs(title = "펀드의 일별 자산군 비중 변화 추이",
#        x = "기준일자",
#        y = "비중",
#        fill = "자산군")+
#   facet_wrap(~펀드,nrow = 2)+
#   theme(axis.text.x = element_text(angle = 30, hjust = 1))
# 
# 
# # ggplot 객체 생성
# p <- position %>% 
#   #filter(펀드=="07J96") |> 
#   ggplot(aes(x = 기준일자, y = daily_weight, fill = !!sym(asset_group))) +
#   geom_area(alpha = 0.8) +
#   scale_x_date(date_labels = "%Y-%m-%d", date_breaks = "3 month") +
#   theme_minimal() +
#   theme(axis.text.x = element_text(angle = 45, hjust = 1)) +
#   labs(title = "펀드의 일별 자산군 비중 변화 추이",
#        x = "기준일자",
#        y = "비중",
#        fill = "자산군") +
#   facet_wrap(~펀드)
# 
# # plotly 객체로 변환
# plotly_obj <- ggplotly(p)
# 
# # plotly 객체 출력 (노트북, RStudio 등에서 바로 볼 수 있음)
# plotly_obj
# 
#   
