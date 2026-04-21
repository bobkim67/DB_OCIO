library(gt)
BM_preprocessing<- function(res ,weight_type,Portfolio_name, cost_bp =0){ # ,Version 2이고, 이 이후 for_comparale period 등등 쭉 수정 해야함
  
  results_desc <- res[[1]] %>% filter(Portfolio== Portfolio_name)
  results_core <- res[[2]] %>% filter(Portfolio== Portfolio_name)
  results_raw  <- res[[3]] %>% filter(Portfolio== Portfolio_name)
  if (str_detect(weight_type,"Fixed") ) {
    weight_by_ticker <- results_core %>% 
      select(-contains("weighted_sum")) %>% 
      #select(-(contains("Weight"))) %>% 
      select(-contains("drift")) %>% 
      set_names(c("Portfolio","기준일자","리밸런싱날짜","Weight(T)","Weight(T-1)","turn_over")) %>% 
      pivot_longer(cols = starts_with("Weight"),names_to = "구분") %>% 
      unnest_longer(col = value, values_to = "Weight", indices_to = "symbol") %>% 
      pivot_wider(id_cols = c(Portfolio,기준일자,리밸런싱날짜,symbol) , names_from = 구분, values_from = Weight) 
    
  } else {
    weight_by_ticker <- results_core %>% 
      select(-contains("weighted_sum")) %>% 
      #select(-(contains("Weight")&contains("(T)"))) %>% 
      select(-contains("fixed")) %>% 
      set_names(c("Portfolio","기준일자","리밸런싱날짜","Weight(T)","Weight(T-1)","turn_over")) %>% 
      pivot_longer(cols = starts_with("Weight"),names_to = "구분") %>% 
      unnest_longer(col = value, values_to = "Weight", indices_to = "symbol") %>% 
      pivot_wider(id_cols = c(Portfolio,기준일자,리밸런싱날짜,symbol) , names_from = 구분, values_from = Weight) 
  }
  
  
  # 2. Ticker별 performance
  perform_by_ticker<- results_raw %>% 
    select(-contains("lag")) %>% 
    rename_with(~ gsub("_list", "", .)) %>% 
    pivot_longer(cols = c(cummulative_return ,daily_return ,raw_data ),names_to = "구분") %>% 
    unnest_longer(col = value, values_to = "Raw_value", indices_to = "symbol") %>% 
    pivot_wider(id_cols = c(Portfolio,기준일자,리밸런싱날짜,symbol,`USD/KRW` ,`return_USD/KRW`) ,
                names_from = 구분, 
                values_from = Raw_value) %>% 
    select(Portfolio,기준일자, 리밸런싱날짜,symbol,`return_USD/KRW`,daily_return )
  
  # 3. 포트폴리오의 실제 일별 수익률
  #cost_bp <- 0# default 는 0
  
  if (str_detect(weight_type,"Fixed") ) {
    
    return_of_backtest<- results_core %>% 
      rename_with(~ gsub("weighted_sum", "Return", .)) %>% 
      select(-contains("Weight"),-contains("drift")) %>% 
      mutate(across(.cols = contains("Return_"),.fns = ~.x-cost_bp/10000/365)) %>% 
      set_names(c("Portfolio","기준일자","리밸런싱날짜","Return","turn_over")) 
    
    
  } else {
    
    return_of_backtest<- results_core %>% 
      rename_with(~ gsub("weighted_sum", "Return", .)) %>% 
      select(-contains("Weight"),-contains("fixed")) %>% 
      mutate(across(.cols = contains("Return_"),.fns = ~.x-cost_bp/10000/365)) %>% 
      set_names(c("Portfolio","기준일자","리밸런싱날짜","Return","turn_over"))  
  }
  
  
  
  backtest_result <- list("weight" = weight_by_ticker,
                          "performance" = perform_by_ticker,
                          "portfolio_return" = return_of_backtest)
  
  
  
  temp_mapping<- results_desc %>% 
    select(dataset_id,symbol,hedge_ratio) %>% distinct() %>% 
    left_join(universe_non_derivative_table %>% 
                select(primary_source,primary_source_id,ISIN,classification_method,classification) %>% 
                filter(classification_method == "Currency Exposure", !is.na(classification),!is.na(classification_method)) %>% distinct() %>% 
                select(primary_source_id,classification) %>% 
                rename(dataset_id = primary_source_id,
                       노출통화 = classification)) %>% 
    mutate(노출통화 = if_else(노출통화!= "KRW" & hedge_ratio ==1, "KRW", 노출통화))
  
  backtest_result$performance %>%  
    left_join( backtest_result$weight %>% 
                 select(-리밸런싱날짜) , by = join_by( Portfolio,기준일자,symbol)) %>% 
    left_join(temp_mapping ,
              by = join_by(symbol)) %>% 
    mutate(sec_id=symbol) %>% 
    select(기준일자 ,sec_id ,ITEM_NM= symbol,`수익률(FX_포함)`=daily_return ,everything(),-c(리밸런싱날짜) )  %>% 
    mutate(`수익률(FX_제외)` = if_else(노출통화=="USD",(1+`수익률(FX_포함)`)/(1+`return_USD/KRW`)-1,`수익률(FX_포함)` ),.before = `수익률(FX_포함)`) %>% 
    select(-`return_USD/KRW`) %>% 
    bind_rows(#FX 부분
      
      #포트폴리오는 이미 선택 가정
      backtest_result$performance %>%  
        left_join( backtest_result$weight %>% 
                     select(-리밸런싱날짜) , by = join_by( Portfolio,기준일자,symbol)) %>% 
        left_join(temp_mapping ,
                  by = join_by(symbol)) %>% 
        filter(노출통화 != "KRW") %>% 
        select(기준일자,`return_USD/KRW`,daily_return,contains("Weight"),symbol,노출통화,Portfolio ) %>% 
        mutate(자산군= "FX") %>% 
        mutate(`수익률(FX_제외)` = daily_return - ((1+daily_return)/(1+`return_USD/KRW`)-1)  ) %>% 
        group_by(기준일자,노출통화) %>% 
        reframe(`수익률(FX_제외)`= sum(`수익률(FX_제외)`*`Weight(T-1)`) / sum(`Weight(T-1)`),#각 symbol별 수익률 반영된 가중평균 FX
                across(contains("Weight"),.fns = ~sum(.x)),
                자산군=자산군[1],
                노출통화 = 노출통화[1],
                Portfolio = Portfolio[1])
    ) %>% 
    rename( `weight_PA(T)` = `Weight(T-1)` )->BM_prep
  
  
  return(list(
    "BM_prep"=BM_prep,
    "backtest_result"=backtest_result,
    "check_mapping_classification"=temp_mapping))
}
#res_list_portfolio <- AP_roll_portfolio
#res_list_portfolio <- BM_roll_portfolio
for_comparable_period <- function(res_list_portfolio,mapping_method,mapped_status){
  
  if(res_list_portfolio %>% enframe() %>% nrow()>3){
    
    
    res_list_portfolio$sec_return_weight %>%  
      left_join(mapped_status%>% 
                  select(sec_id=ISIN,!!mapping_method) %>% 
                  filter(!is.na(sec_id)) %>% distinct(),by = join_by(sec_id)) %>%
      rename(자산군 = !!mapping_method) %>% 
      bind_rows(res_list_portfolio$FX_return_weight %>% 
                  select(-contains("환노출"),-contains("환헷지")) %>% 
                  rename(`수익률(FX_제외)` = `수익률(FX)`) # 노출통화분석에 대한것은 개별 포트폴리오 시각화에서..?이건 너무 헤비
      ) %>% 
      select(기준일자 = pr_date,sec_id,contains("수익률"),weight_순자산,`weight_PA(T)`,contains("자산군"),ITEM_NM,노출통화) %>% 
      mutate(Portfolio = res_list_portfolio$historical_fund_inform_data$FUND_CD[1]) -> res_prep
    
    
    res_list_portfolio$for_validation_results %>% 
      select(기준일자=pr_date,Return= daily_return_AP) %>% 
      left_join(res_prep) %>% 
      mutate(across(.cols = c(`수익률(FX_제외)`, `수익률(FX_포함)`,weight_순자산, `weight_PA(T)`) , .fns = ~if_else(is.na(.x),0,.x))) %>% 
      mutate(Portfolio = res_list_portfolio$historical_fund_inform_data$FUND_CD[1]) %>% 
      #APㅇ서 asset_gb추가했으니 이거 이용해서 빈칸 채우기
      mutate(자산군 =if_else(is.na(자산군),"유동성및기타",자산군)) %>%
      distinct()  ->res
    res %>% 
      bind_rows(
        res_list_portfolio$historical_cash_NAV %>% 
          rename(기준일자 =pr_date, weight_순자산 = 순자산비중) %>% 
          mutate(자산군 = "유동성및기타")
      )->res
    
    
    
  }else{
    
    res_list_portfolio$BM_prep %>%
      rename(weight_순자산=`Weight(T)`) %>% 
      left_join(mapped_status %>% 
                  select(dataset_id=primary_source_id,!!mapping_method) %>% 
                  filter(!is.na(dataset_id)) %>% distinct(),by = join_by(dataset_id)) %>% 
      mutate(자산군 = coalesce(자산군, .data[[mapping_method]])) %>%  # if_else문과 같음 coalesce
      select(-!!all_of(mapping_method)) %>% 
      left_join(res_list_portfolio$backtest_result$portfolio_return %>% 
                  select(Portfolio,기준일자,Return) ) %>% 
      mutate(자산군 =if_else(is.na(자산군),"유동성및기타",자산군)) %>%
      distinct() ->res
  }
  
  
  
  return(res)
}
#res_list_portfolio <- AP_roll_portfolio
#res_list_portfolio <- BM_roll_portfolio
Portfolio_analysis <- function(res_list_portfolio,from,to,mapping_method,mapped_status,FX_split=TRUE){
  
  
  
  for_comparable_period(res_list_portfolio,mapping_method,mapped_status) %>% 
    mutate(across(.cols = contains("수익률"), .fns = ~if_else(is.infinite(.x)|is.na(.x),0,.x))) %>% 
    distinct() %>% 
    mutate(sec_id = coalesce(sec_id,노출통화),
           ITEM_NM = coalesce(ITEM_NM,노출통화))-> 기초정보_weight_performance
  #기초정보_weight_performance %>% view()
  # __normalized performance (sec별/자산군별) --------------------------------------
  
  
  기초정보_weight_performance %>% 
    filter(기준일자 >=from & 기준일자 <=to) %>% 
    mutate(sec_id = if_else(is.na(sec_id) & 자산군 == "유동성및기타","유동성및기타",sec_id)) %>% 
    mutate(ITEM_NM = if_else(is.na(ITEM_NM) & 자산군 == "유동성및기타","유동성및기타",ITEM_NM)) %>% 
    mutate(sec_id = if_else(is.na(sec_id) & 자산군 == "FX","FX",sec_id)) %>% 
    #mutate(sec_id= if_else(자산군 == "FX", ITEM_NM,sec_id)) %>% 
    mutate(ITEM_NM = if_else(is.na(ITEM_NM) & 자산군 == "FX","FX",ITEM_NM)) %>% 
    group_by(sec_id) %>% 
    reframe(분석시작일 = min(기준일자),
            분석종료일 = max(기준일자),
            기준일자,자산군,ITEM_NM,
            across(.cols = contains("수익률"), .fns= ~cumprod(1+.x)-1)) %>%  
    complete(기준일자,sec_id) %>% 
    group_by(sec_id) %>%
    fill(분석시작일,분석종료일, 자산군, ITEM_NM, .direction = "downup") %>% 
    filter(분석시작일<=기준일자) %>% 
    arrange(기준일자) %>% 
    fill( `수익률(FX_제외)`, `수익률(FX_포함)` , .direction = "down") %>% 
    ungroup() %>% 
    filter(!(자산군 == "유동성및기타" & ITEM_NM == "유동성및기타"))-> norm_performance_by_sec
  
  
  
  #filter(자산군 != "FX")# 이거는 환헷지 들어간 펀드들때문에 제거는 안함.
  
  기초정보_weight_performance %>%
    filter(기준일자 >=from & 기준일자 <=to) %>% 
    group_by(기준일자) %>%
    filter(
      # 이 행의 자산군이 '유동성및기타'가 아니면 무조건 통과
      자산군 != "유동성및기타" | 
        # 또는, 자산군이 '유동성및기타'인 경우 아래 조건을 만족하면 통과:
        # (그룹 전체에서 '유동성및기타' 자산군의 ITEM_NM을 봤을 때, '유동성및기타'가 아닌 이름이 하나라도 있는가?)
        any(ITEM_NM[자산군 == "유동성및기타"] != "유동성및기타")
    ) %>%
    ungroup() %>% 
    group_by(기준일자,자산군) %>% 
    reframe(`수익률(FX_제외)`= sum(`수익률(FX_제외)`*abs(`weight_PA(T)`))/sum(abs(`weight_PA(T)`)),
            `수익률(FX_포함)`= sum(`수익률(FX_포함)`*abs(`weight_PA(T)`))/sum(abs(`weight_PA(T)`))) %>% 
    arrange(기준일자) %>% 
    group_by(자산군) %>% 
    mutate(across(.cols = contains("수익률"), .fns= ~cumprod(1+.x)-1)) %>% 
    mutate(분석시작일 = min (기준일자),
           분석종료일 = max (기준일자),.after = 기준일자) %>% 
    ungroup() %>% 
    complete(기준일자,자산군) %>% 
    group_by(자산군) %>% 
    fill(분석시작일,분석종료일, .direction = "downup") %>% 
    filter(분석시작일<=기준일자) %>% 
    arrange(기준일자) %>% 
    fill( `수익률(FX_제외)`, `수익률(FX_포함)` , .direction = "down") %>% 
    ungroup() ->norm_performance_by_자산군
  
  
  # __기여수익률(sec별/자산군별) --------------------------------------------------------
  
  
  
  기초정보_weight_performance %>% 
    filter(기준일자 >=from & 기준일자 <=to) %>% 
    #mutate(sec_id= if_else(is.na(sec_id)&자산군 =="FX","FX",sec_id)) %>% 
    #mutate(sec_id= if_else(is.na(sec_id)&자산군 =="유동성및기타","유동성및기타",sec_id)) %>% 
    #mutate(sec_id= if_else(자산군 == "FX", ITEM_NM,sec_id)) %>% 
    group_by(기준일자,sec_id) %>% 
    reframe(Return = Return[1],
            ITEM_NM = ITEM_NM[1],
            `기여수익률(FX_제외)` = sum(`수익률(FX_제외)`*abs(`weight_PA(T)`),na.rm = TRUE),
            `기여수익률(FX_포함)` = sum(`수익률(FX_포함)`*abs(`weight_PA(T)`),na.rm = TRUE),
            자산군 = 자산군[1]) %>% 
    group_by(기준일자) %>% 
    mutate(`유동성및기타수익률(FX_제외)`= Return[1]- sum(`기여수익률(FX_제외)`),
           `유동성및기타수익률(FX_포함)`= Return[1]- sum(`기여수익률(FX_포함)`)) %>% ungroup() %>% 
    filter(!is.na(Return)) ->for_sec별_기여수익률
  #filter(!(자산군 == "유동성및기타" & ITEM_NM == "유동성및기타"))->for_sec별_기여수익률
  
  func_sec_historical_기여수익률<- function(for_sec별_기여수익률,FX_factor = FX_split){ #FX_factor=(FX_제외, FX_포함)
    
    # -contains()함수를 사용하기 때문에 switching
    FX_factor <- if_else(FX_split ==TRUE ,"FX_포함","FX_제외")
    for_sec별_기여수익률 %>% 
      select(-contains(FX_factor),-Return,-contains("유동성")) %>% 
      pivot_longer(cols = -c(기준일자,sec_id,ITEM_NM,자산군),values_to = "손익금액") %>% 
      #filter(자산군!="유동성및기타") %>% view()
      bind_rows(
        for_sec별_기여수익률 %>% 
          select(기준일자,contains("유동성"),-contains(FX_factor)) %>% distinct() %>% 
          mutate(자산군 = "유동성및기타") %>% 
          set_names(c("기준일자","손익금액","자산군"))
      ) %>% 
      left_join(
        for_sec별_기여수익률 %>% 
          select(기준일자,Return) %>% distinct() %>% 
          mutate(기준가격 = 1000*cumprod(1+Return)) %>% 
          mutate(기준가증감 = 기준가격-lag(기준가격,n=1,default = 1000)) %>% 
          mutate(cum_return = 기준가격/1000-1,
                 cum_기준가증감 = cumsum(기준가증감))
      ) %>% 
      arrange(기준일자) %>% 
      filter(!(자산군 == "유동성및기타" & 손익금액==0)) %>% 
      mutate(sec_id = if_else(is.na(sec_id) & 자산군 == "유동성및기타","유동성및기타",sec_id)) %>% 
      group_by(기준일자,sec_id) %>% 
      mutate(sec_id기여도 =if_else(Return[1]==0, 0 ,(손익금액/Return[1])*기준가증감[1] ) ) %>% 
      group_by(sec_id) %>%
      mutate(
        분석시작일 = min(기준일자),
        분석종료일 = max(기준일자),
        총손익기여도= cum_return*cumsum(sec_id기여도)/ (cum_기준가증감), # 펀드누적수익률* (cumsum(당일총손익/일별총손익*일별펀드기준가증감)/누적기준가증감 )
        총손익금액 = cumsum(손익금액)) %>% 
      ungroup() %>%
      select(분석시작일,분석종료일,기준일자,sec_id,자산군,ITEM_NM,cum_return,contains("총손익")) %>%
      mutate(ITEM_NM = if_else(is.na(ITEM_NM), sec_id,ITEM_NM)) %>% 
      complete(기준일자,sec_id) %>% 
      group_by(sec_id) %>%
      fill(분석시작일,분석종료일, 자산군, ITEM_NM, .direction = "downup") %>% 
      filter(분석시작일<=기준일자) %>% 
      arrange(기준일자) %>% 
      fill(총손익기여도,총손익금액 , .direction = "down") %>% 
      group_by(기준일자) %>% 
      fill(cum_return , .direction = "downup") %>% 
      ungroup() -> sec별_기여수익률
    
    return(sec별_기여수익률)
    
  }
  
  if(FX_split == TRUE){
    
    norm_performance_by_sec %>% 
      select(기준일자,분석시작일,분석종료일,sec_id,ITEM_NM,자산군,누적수익률 =`수익률(FX_제외)` ) ->`norm_performance_by_sec`
    
    norm_performance_by_자산군 %>% 
      select(기준일자,분석시작일,분석종료일,자산군,누적수익률 =`수익률(FX_제외)` ) ->`norm_performance_by_자산군`
    
    sec별_기여수익률 <- func_sec_historical_기여수익률(for_sec별_기여수익률,FX_factor = FX_split)
    
    
    자산군별_기여수익률 <- sec별_기여수익률 %>% 
      mutate(분석시작일 = min(분석시작일),
             분석종료일 = max(분석종료일)) %>% 
      group_by(자산군,기준일자) %>% 
      reframe(분석시작일 = 분석시작일[1],
              분석종료일 = 분석종료일[1],
              cum_return =cum_return[1],
              총손익기여도 = sum(총손익기여도,na.rm = TRUE),
              총손익금액 = sum(총손익금액,na.rm = TRUE)) %>% 
      mutate(자산군 = if_else(is.na(자산군), "유동성및기타",자산군))
    
    
    기초정보_weight_performance %>% 
      filter(기준일자 >=from -days(1) & 기준일자 <=to) %>% 
      group_by(기준일자,자산군) %>% 
      reframe(weight_순자산 = sum(weight_순자산,na.rm=TRUE),
              `weight_PA(T)` = sum(abs(`weight_PA(T)`),na.rm=TRUE)) -> 자산군별_비중
    #mutate(`weight_PA(T)` = if_else(자산군 == "유동성및기타",NA,`weight_PA(T)`))-> 자산군별_비중
    
    기초정보_weight_performance %>% 
      filter(기준일자 >=from -days(1) & 기준일자 <=to) %>% 
      select(기준일자,sec_id,자산군,ITEM_NM,weight_순자산,`weight_PA(T)`) %>% 
      mutate(ITEM_NM = if_else(is.na(ITEM_NM), sec_id,ITEM_NM)) %>% 
      filter(!(자산군 == "유동성및기타" & ITEM_NM == "유동성및기타")) -> sec별_비중
    #mutate(sec_id= if_else(is.na(sec_id)&자산군 =="FX","FX",sec_id)) %>% 
    #mutate(sec_id= if_else(자산군 == "FX", ITEM_NM,sec_id))  -> sec별_비중
    #sec별_비중 %>% view()
    
  }else{
    
    
    norm_performance_by_sec %>% 
      select(기준일자,분석시작일,분석종료일,sec_id,ITEM_NM,자산군,누적수익률 =`수익률(FX_포함)` ) %>% 
      filter(자산군 !="FX") ->`norm_performance_by_sec`
    
    norm_performance_by_자산군 %>% 
      select(기준일자,분석시작일,분석종료일,자산군,누적수익률 =`수익률(FX_포함)` ) %>% 
      filter(자산군 !="FX") ->`norm_performance_by_자산군`
    
    sec별_기여수익률 <- func_sec_historical_기여수익률(for_sec별_기여수익률,FX_factor = FX_split) %>% 
      filter(자산군 !="FX") 
    
    
    자산군별_기여수익률 <- sec별_기여수익률 %>% 
      group_by(자산군) %>% 
      mutate(분석시작일 = min(분석시작일),
             분석종료일 = max(분석종료일)) %>% 
      group_by(자산군,기준일자) %>% 
      reframe(분석시작일 = 분석시작일[1],
              분석종료일 = 분석종료일[1],
              cum_return =cum_return[1],
              총손익기여도 = sum(총손익기여도,na.rm = TRUE),
              총손익금액 = sum(총손익금액,na.rm = TRUE)) %>% 
      filter(자산군 !="FX") %>% 
      mutate(자산군 = if_else(is.na(자산군), "유동성및기타",자산군))
    
    
    기초정보_weight_performance %>% 
      filter(기준일자 >=from -days(1) & 기준일자 <=to) %>% 
      group_by(기준일자,자산군) %>% 
      reframe(weight_순자산 = sum(weight_순자산,na.rm=TRUE),
              `weight_PA(T)` = sum(abs(`weight_PA(T)`),na.rm=TRUE)) %>%
      filter(자산군 !="FX") -> 자산군별_비중
    #mutate(`weight_PA(T)` = if_else(자산군 == "유동성및기타",NA,`weight_PA(T)`))-> 자산군별_비중
    
    기초정보_weight_performance %>% 
      filter(기준일자 >=from -days(1) & 기준일자 <=to) %>% 
      select(기준일자,sec_id,자산군,ITEM_NM,weight_순자산,`weight_PA(T)`) %>% 
      mutate(ITEM_NM = if_else(is.na(ITEM_NM), sec_id,ITEM_NM)) %>% 
      filter(!(자산군 == "유동성및기타" & ITEM_NM == "유동성및기타")) %>% 
      filter(자산군 !="FX") -> sec별_비중
    #mutate(sec_id= if_else(is.na(sec_id)&자산군 =="FX","FX",sec_id)) %>% 
    #mutate(sec_id= if_else(자산군 == "FX", ITEM_NM,sec_id))  -> sec별_비중
    #sec별_비중 %>% view()
    
  }
  
  
  return(
    list(
      
      "sec별_기여수익률" = sec별_기여수익률,
      "자산군별_기여수익률" = 자산군별_기여수익률,
      "normalized_performance_by_sec"= `norm_performance_by_sec`,
      "normalized_performance_by_자산군"=`norm_performance_by_자산군`,
      "sec별_비중" = sec별_비중,
      "자산군별_비중" = 자산군별_비중
    )
  )
}
# from <- ymd("2025-08-01")
# AP_roll_portfolio <- BM3
#mapping_method <- "방법1"
General_PA<- function(AP_roll_portfolio,BM_roll_portfolio,
                      AP_roll_portfolio_res,BM_roll_portfolio_res,
                      from,to,
                      mapping_method,mapped_status,FX_split=TRUE){
  #from <- ymd("2017-07-01");to <- ymd("2025-07-31");
  for_comparable_period(AP_roll_portfolio,mapping_method,mapped_status) %>% 
    bind_rows(for_comparable_period(BM_roll_portfolio,mapping_method,mapped_status)) %>% 
    group_by(기준일자) %>% 
    filter(length(unique(Portfolio))>=2) %>%  # %>% # 두개날짜 동시분석 가능일 필터링 (시작일 뿐 아니라 종료일도 맞춰짐)
    ungroup() %>% 
    filter(기준일자<=to & 기준일자>=from)->comparable_period
  
  if(nrow(comparable_period)==0){
    return(print("조회된 기간에, 두개의 포트폴리오에 대한 정보가 존재하는 날짜가 존재하지 않습니다."))
  }
  Port_구분 <- factor(comparable_period$Portfolio %>% unique(),levels =comparable_period$Portfolio %>% unique() )
  # 여기서 FX 제외한 수익과 그냥 포함되어있는거 버전 각각 산출
  comparable_period %>% 
    group_by(기준일자,Portfolio,자산군) %>% 
    reframe(Portfolio수익률 = Return[1],
            `자산군별수익률(Normalized)_FX분리` = sum(`수익률(FX_제외)`*abs(`weight_PA(T)`),na.rm = TRUE)/sum(abs(`weight_PA(T)`),na.rm = TRUE),
            `자산군별수익률(Normalized)_FX포함` = sum(`수익률(FX_포함)`*abs(`weight_PA(T)`),na.rm = TRUE)/sum(abs(`weight_PA(T)`),na.rm = TRUE),
            비중_PA = sum(abs(`weight_PA(T)`)))  %>%
    complete(기준일자, Portfolio, 자산군 , 
             fill = list(`자산군별수익률(Normalized)_FX분리` = 0,
                         `자산군별수익률(Normalized)_FX포함` = 0,
                         비중_PA = 0)) %>% 
    group_by(기준일자,Portfolio) %>% 
    fill(Portfolio수익률, .direction = "downup") %>% 
    filter(자산군 != "유동성및기타") %>% 
    ungroup() %>% 
    mutate(AP_BM구분 = if_else(Portfolio==Port_구분[1],"AP","BM")) %>% 
    arrange(AP_BM구분) %>% 
    group_by(기준일자,Portfolio) %>% 
    mutate(유동성및기타_FX분리 = Portfolio수익률 - sum(`자산군별수익률(Normalized)_FX분리`*비중_PA),
           유동성및기타_FX포함 = Portfolio수익률 - sum(`자산군별수익률(Normalized)_FX포함`*비중_PA)) %>% 
    ungroup()->middle_result
  
  AP_roll_portfolio_res$자산군별_기여수익률 %>% 
    select(자산군,기준일자,총손익기여도) %>% 
    mutate(구분 = "AP") %>% 
    bind_rows(
      BM_roll_portfolio_res$자산군별_기여수익률 %>% 
        select(자산군,기준일자,총손익기여도) %>% 
        mutate(구분 = "BM")
    ) %>%
    pivot_wider(id_cols = c(기준일자,자산군),names_from = 구분,values_from = 총손익기여도) %>% 
    mutate(across(where(is.numeric),.fns = ~replace_na(.x,0))) %>% 
    mutate(누적기여수익률차이 = AP-BM) %>% 
    select(기준일자,자산군, 보정인자2 = 누적기여수익률차이)->for_보정인자2
  
  
  #active weight, 괴리율, 복제율도 계산해서 내뱉기
  middle_result %>% 
    group_by(기준일자,자산군) %>% 
    reframe(AP_roll_weight = (비중_PA[1]),
            BM_roll_weight = (비중_PA[2]),
            active_weight = (비중_PA[1]-비중_PA[2])) -> weight_inform
  
  middle_result %>% ungroup() %>%
    select(기준일자,Portfolio,AP_BM구분,Portfolio수익률) %>% distinct() %>%
    group_by(Portfolio) %>%
    reframe(AP_BM구분 = AP_BM구분[1],
            분석시작일 = 기준일자[1],
            기준일자,누적수익률 = cumprod(Portfolio수익률+1)-1) %>%
    arrange(AP_BM구분) %>%
    group_by(기준일자) %>%
    # *--'상대누적성과'의 일별 수익률로 분해--*
    reframe(초과누적상대수익률 = (1+누적수익률[1])/(1+누적수익률[2])-1,
            초과누적수익률 = 누적수익률[1]-누적수익률[2]) ->for_초과누적수익률
  
  # 
  #             수정기준가_초과누적상대 = (초과누적상대수익률+1)*1000) %>%  
  #     mutate(전일수정기준가 = lag(수정기준가_초과누적상대,n=1,default = 1000),
  #            초과수익률 = 수정기준가_초과누적상대/전일수정기준가-1) -> for_초과누적수익률
  
  for_초과누적수익률 %>% 
    select(기준일자,초과누적상대수익률) %>% 
    mutate(초과수익률 = (1+초과누적상대수익률)/(1+lag(초과누적상대수익률,n=1,default =0))-1) %>% 
    select(기준일자,초과수익률) %>% 
    left_join(
      
      middle_result %>% ungroup() %>%
        select(기준일자,Portfolio,AP_BM구분,Portfolio수익률) %>% distinct() %>%
        arrange(AP_BM구분) %>%
        group_by(기준일자) %>%
        reframe(`초과수익률(daily_return_diff)` = Portfolio수익률[1]-Portfolio수익률[2]) %>%
        distinct()
    ) %>% 
    mutate(보정인자1 =if_else(`초과수익률(daily_return_diff)` !=0,
                          초과수익률/`초과수익률(daily_return_diff)`,0 ))->for_초과수익률
  
  
  
  # 
  # middle_result %>% ungroup() %>%
  #   select(기준일자,Portfolio,AP_BM구분,Portfolio수익률) %>% distinct() %>%
  #   arrange(AP_BM구분) %>%
  #   pivot_wider(id_cols = 기준일자,names_from = Portfolio,values_from = Portfolio수익률) %>% 
  #   mutate(초과수익률 = .[[2]]-.[[3]]) %>%
  #   mutate(across(where(is.numeric),.fns = ~cumprod(.x+1)-1)) %>% tail()
  #   mutate(ss= cumprod(1+초과수익률)-1) %>% view()
  #   
  
  # for_초과수익률 %>%
  #   mutate(cr = cumprod(초과수익률+1)-1) %>% tail()
  if(FX_split==TRUE){
    middle_result %>% 
      arrange(AP_BM구분) %>% 
      left_join(for_초과수익률) %>% 
      group_by(기준일자,자산군) %>% 
      reframe(초과수익률 = 초과수익률[1] ,
              `초과수익률(daily_return_diff)` = `초과수익률(daily_return_diff)`[1],
              보정인자1 = 보정인자1[1],
              Cross_effect = (비중_PA[1]-비중_PA[2])*(`자산군별수익률(Normalized)_FX분리`[1]-`자산군별수익률(Normalized)_FX분리`[2]),
              Allocation_effect = (비중_PA[1]-비중_PA[2])*(`자산군별수익률(Normalized)_FX분리`[2]),
              Security_selction_effect = (비중_PA[2])*(`자산군별수익률(Normalized)_FX분리`[1]-`자산군별수익률(Normalized)_FX분리`[2])) %>%
      group_by(기준일자) %>% 
      mutate(유동성및기타 =`초과수익률(daily_return_diff)` -(sum(Cross_effect)+sum(Allocation_effect)+sum(Security_selction_effect))) %>% 
      mutate(across(.cols = c(Cross_effect ,Allocation_effect, Security_selction_effect,유동성및기타),
                    .fns = ~.x*보정인자1 )) %>% 
      mutate(검증용 = round(sum(Cross_effect)+ sum(Allocation_effect)+ sum(Security_selction_effect)+유동성및기타[1]-초과수익률[1],15) ) %>% 
      ungroup() %>% 
      filter(기준일자>=from,기준일자<=to) ->PA_portfolio
  }else{
    
    middle_result %>% 
      left_join(for_초과수익률) %>% 
      group_by(기준일자,자산군) %>% 
      reframe(초과수익률 = 초과수익률[1] ,
              `초과수익률(daily_return_diff)` = `초과수익률(daily_return_diff)`[1],
              보정인자1 = 보정인자1[1],
              Cross_effect = (비중_PA[1]-비중_PA[2])*(`자산군별수익률(Normalized)_FX포함`[1]-`자산군별수익률(Normalized)_FX포함`[2]),
              Allocation_effect = (비중_PA[1]-비중_PA[2])*(`자산군별수익률(Normalized)_FX포함`[2]),
              Security_selction_effect = (비중_PA[2])*(`자산군별수익률(Normalized)_FX포함`[1]-`자산군별수익률(Normalized)_FX포함`[2])) %>% 
      group_by(기준일자) %>% 
      mutate(유동성및기타 =`초과수익률(daily_return_diff)` -(sum(Cross_effect)+sum(Allocation_effect)+sum(Security_selction_effect))) %>% 
      mutate(across(.cols = c(Cross_effect ,Allocation_effect, Security_selction_effect,유동성및기타),
                    .fns = ~.x*보정인자1 )) %>% 
      mutate(검증용 = round(sum(Cross_effect)+ sum(Allocation_effect)+ sum(Security_selction_effect)+유동성및기타[1]-초과수익률[1],15) ) %>% 
      ungroup() %>% 
      filter(기준일자>=from,기준일자<=to) %>% 
      filter(자산군!="FX") ->PA_portfolio
  }
  
  
  # 7. 초과수익 성과분해 (초과성과의 1000환산 기준가, A,B,C * 자산군분류체계 weight 및 수익률)----
  excess_return_PA<- function(PA_portfolio){
    PA_portfolio %>% 
      select(-c(초과수익률,유동성및기타,검증용,보정인자1,`초과수익률(daily_return_diff)`)) %>% 
      pivot_longer(cols = -c(기준일자,자산군),values_to = "손익금액") %>% 
      mutate(sec_id = paste0(name, "_",자산군)) %>% 
      bind_rows(
        PA_portfolio %>% 
          select(기준일자,유동성및기타) %>% distinct() %>% 
          mutate(sec_id = "유동성및기타") %>% 
          rename(손익금액= 유동성및기타)
      ) %>% 
      left_join(
        PA_portfolio %>% 
          select(기준일자,초과수익률) %>% distinct() %>% 
          mutate(기준가격 = 1000*cumprod(1+초과수익률)) %>% 
          mutate(기준가증감 = 기준가격-lag(기준가격,n=1,default = 1000)) %>% 
          mutate(cum_return = 기준가격/1000-1,
                 cum_기준가증감 = cumsum(기준가증감))
      ) %>% 
      arrange(기준일자) %>% 
      group_by(기준일자,sec_id) %>% 
      mutate(sec_id기여도 = if_else(초과수익률[1]!=0,(손익금액/초과수익률[1])*기준가증감[1],0)) %>% 
      group_by(sec_id) %>% 
      mutate(
        총손익기여도= if_else(cum_기준가증감 !=0,cum_return*cumsum(sec_id기여도)/ (cum_기준가증감),0 ), # 펀드누적수익률* (cumsum(당일총손익/일별총손익*일별펀드기준가증감)/누적기준가증감 )
        총손익금액 = cumsum(손익금액)) %>% 
      ungroup() %>% 
      select(기준일자,자산군,name,sec_id,cum_return,contains("총손익")) %>% 
      left_join(for_초과누적수익률) %>% 
      # 상대적인 초과수익으로 각 요소의 기여도를 측정하고, 실제 누적수익률차이로 합산되게 보정. 
      # ex. 10000% 수익률이 난 portfolio와 10100% 수익률이 난 portfolio폴리오는 상대성과는 1%지만, 누적수익률차이는 100%임.
      # 실질적으로 보통 누적수익률차이에 대한 분해를 보기 때문에 보정.
      mutate(보정_총손익기여도 = if_else(cum_return !=0,
                                 총손익기여도* 초과누적수익률/cum_return ,
                                 총손익기여도) )  %>% 
      mutate(자산군 = coalesce(자산군,"유동성및기타")) %>% 
      inner_join(for_보정인자2) %>% 
      left_join(middle_result %>% ungroup() %>%
                  select(기준일자,Portfolio,AP_BM구분,Portfolio수익률) %>% distinct() %>%
                  filter(AP_BM구분 == "BM") %>% 
                  mutate(`BM누적수익률+1` = cumprod(Portfolio수익률+1)) %>% 
                  select(기준일자,`BM누적수익률+1`))->historical_results_PA_GENERAL
    
    
    
    return(historical_results_PA_GENERAL)
  }
  
  
  
  return(
    list(
      "comparable_period" = comparable_period,
      "PA_portfolio" = PA_portfolio,
      "historical_results_PA_GENERAL" = excess_return_PA(PA_portfolio),
      "weight_inform" = weight_inform
    )
  )
}
