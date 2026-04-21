# R 프로덕션 PA_from_MOS 함수 headless 호출 (08N81)
# ACE 종합채권(AA-이상) KR7356540005 2026-03-16 BA정산 정확한 값 확인
library(tidyverse)
library(DBI)
library(RMariaDB)
library(lubridate)
library(blob)
library(fuzzyjoin)
library(timetk)
library(tictoc)
options(digits = 15)

con_dt  <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='dt', host='192.168.195.55')
con_sol <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='solution', host='192.168.195.55')

universe_non_derivative_table <- dbGetQuery(con_sol, "SELECT * FROM universe_non_derivative")
universe_derivative_table <- dbGetQuery(con_sol, "SELECT * FROM universe_derivative")

USDKRW <- dbGetQuery(con_dt, "SELECT STD_DT, TR_STD_RT FROM DWCI10260 WHERE CURR_DS_CD='USD' AND STD_DT>='20251101'") %>%
  mutate(기준일자 = ymd(STD_DT), `USD/KRW` = as.numeric(TR_STD_RT)) %>%
  select(기준일자, `USD/KRW`) %>% arrange(기준일자) %>%
  pad_by_time(.date_var = 기준일자, .by = "day", .fill_na_direction = "down")

T_move_date_calc <- function(date, n) date + days(n)

모펀드_mapping <- tbl(con_dt, "DWPI10011") %>%
  select(FUND_CD, EFTV_ST_DT, FUND_WHL_NM, FRST_OPNG_DT,
         NXT_STOA_DT, RGBF_STOA_DT, MNR_EMNO, CLSS_MTFD_CD,
         ASCT_FUND_CD, MCF_DS_CD, NEW_ASCT_CLSF_CD, DEPT_CD) %>%
  filter(DEPT_CD %in% c('166','061','064')) %>%
  select(FUND_CD, CLSS_MTFD_CD, FUND_WHL_NM, FRST_OPNG_DT, MNR_EMNO) %>%
  collect() %>%
  mutate(CLSS_MTFD_CD = if_else(is.na(CLSS_MTFD_CD), FUND_CD, CLSS_MTFD_CD)) %>%
  group_by(CLSS_MTFD_CD) %>%
  mutate(FUND_WHL_NM = FUND_WHL_NM[FUND_CD == CLSS_MTFD_CD]) %>%
  mutate(설정일 = min(FRST_OPNG_DT, na.rm = TRUE)) %>%
  ungroup()

cat("08N81 모펀드_mapping:\n")
print(모펀드_mapping %>% filter(FUND_CD == "08N81"))

historical_universe_DWPM10530_TOTAL <- tbl(con_dt, "DWPM10530") %>%
  filter(STD_DT >= "20210101") %>%
  select(FUND_CD, ITEM_CD) %>%
  distinct() %>%
  collect() %>%
  left_join(모펀드_mapping %>% select(FUND_CD, 모펀드 = CLSS_MTFD_CD))

pulling_모자구조 <- 모펀드_mapping %>%
  select(FUND_CD, CLSS_MTFD_CD, 설정일) %>%
  left_join(
    historical_universe_DWPM10530_TOTAL %>% select(-FUND_CD) %>% distinct() %>%
      mutate(ITEM_CD = if_else(str_detect(ITEM_CD, "0322800"), str_remove_all(ITEM_CD, "0322800"), ITEM_CD)) %>%
      filter(nchar(ITEM_CD) == 5, ITEM_CD != 모펀드) %>%
      rename(운용모펀드 = ITEM_CD),
    by = join_by(FUND_CD == 모펀드)
  ) %>%
  mutate(모펀드통합 = if_else(is.na(운용모펀드), CLSS_MTFD_CD, 운용모펀드))

cat("\n08N81 pulling_모자구조:\n")
print(pulling_모자구조 %>% filter(FUND_CD == "08N81"))

source("debug/PA_module_funcs_only.R")
cat("\nPA_from_MOS source loaded\n")

cat("\n=== PA_from_MOS('08N81', 2026-01-08 ~ 2026-04-20) 실행 ===\n")
result <- PA_from_MOS(from = as.Date("2026-01-08"), to = as.Date("2026-04-20"), fund_cd = "08N81")

if (!is.null(result) && is.list(result)) {
  cat("\nresult names:\n")
  print(names(result))

  # ETF_환매_평가시가평가액보정 (KR7356540005 대상 — R groupby 결과)
  if ("historical_trade" %in% names(result)) {
    cat("\n=== historical_trade ACE 종합채권 환매 관련 ===\n")
    ht <- result$historical_trade %>%
      filter(item_cd == "KR7356540005", str_detect(tr_whl_nm, "ETF발행시장환매"))
    print(ht %>% select(std_dt, item_cd, tr_upr, trd_pl_amt, trd_amt, trd_qty, tr_whl_nm))
  }

  # historical_performance_information_final
  if ("historical_performance_information_final" %in% names(result)) {
    cat("\n=== historical_performance_information_final: ACE 종합채권 2026-03-13~18 ===\n")
    tmp <- result$historical_performance_information_final %>%
      filter(sec_id == "KR7356540005", pr_date >= as.Date("2026-03-13"), pr_date <= as.Date("2026-03-18"))
    cols <- intersect(colnames(tmp), c("pr_date","시가평가액","평가시가평가액","총손익금액_당일","평가시가평가액보정","순설정액","조정_평가시가평가액","종목별당일수익률","position_gb"))
    print(tmp %>% select(all_of(cols)))
  }

  if ("sec_return_weight" %in% names(result)) {
    cat("\n=== sec_return_weight: ACE 종합채권 2026-03-13~18 ===\n")
    print(result$sec_return_weight %>%
          filter(sec_id == "KR7356540005", pr_date >= as.Date("2026-03-13"), pr_date <= as.Date("2026-03-18")))
  }
}

# ── Portfolio_analysis 단계 trace ──
cat("\n\n", paste(rep("=", 80), collapse=""), "\n")
cat("=== Portfolio_analysis(08N81) 실행 ===\n")
cat(paste(rep("=", 80), collapse=""), "\n\n")

# mapped_status: R module_03 line 684-707 로직 (is_bos=TRUE 분기)
# temp = AP check_mapping_classification
temp <- result$check_mapping_classification %>%
  mutate(dataset_id = as.character(if ("dataset_id" %in% names(.)) .data[["dataset_id"]] else rep(NA, nrow(.)))) %>%
  distinct()

mapped_status <- bind_rows(
  temp %>%
    fuzzyjoin::regex_left_join(universe_derivative_table, by = c("ITEM_NM" = "keyword")) %>%
    filter(!is.na(keyword)) %>%
    filter(asset_gb.x == asset_gb.y) %>%
    mutate(dataset_id = if ("dataset_id" %in% names(.)) .data[["dataset_id"]] else rep(NA, nrow(.))) %>%
    select(ISIN = sec_id, name = ITEM_NM, 노출통화,
           asset_gb = asset_gb.x, matched_keyword = keyword,
           classification_method, classification,
           primary_source_id = dataset_id),
  universe_non_derivative_table %>%
    filter((ISIN %in% temp$sec_id[!is.na(temp$sec_id)]) |
           (primary_source_id %in% temp$dataset_id[!is.na(temp$dataset_id)])) %>%
    filter(!is.na(classification_method)) %>%
    distinct()
) %>%
  tidyr::pivot_wider(id_cols = c(name, ISIN, primary_source_id, asset_gb),
                     names_from = classification_method,
                     values_from = classification) %>%
  rename(노출통화 = `Currency Exposure`)

mapped_status <- bind_rows(
  mapped_status,
  temp %>% filter(
    !(sec_id %in% mapped_status$ISIN[!is.na(mapped_status$ISIN)]) &
    !(dataset_id %in% mapped_status$primary_source_id[!is.na(mapped_status$primary_source_id)])
  ) %>% select(ISIN = sec_id, name = ITEM_NM, 노출통화, asset_gb)
)

cat("mapped_status cols:\n"); print(colnames(mapped_status))

# AP_roll_portfolio 형식: PA_from_MOS 결과 그대로 사용 가능
source("debug/PA_combine_funcs_only.R")

pa_res <- Portfolio_analysis(
  res_list_portfolio = result,
  from = as.Date("2026-01-08"),
  to = as.Date("2026-04-20"),
  mapping_method = "방법3",
  mapped_status = mapped_status,
  FX_split = TRUE
)

cat("\n\n=== Portfolio_analysis 결과 keys ===\n")
print(names(pa_res))

if ("normalized_performance_by_sec" %in% names(pa_res)) {
  cat("\n=== normalized_performance_by_sec: ACE 종합채권 2026-03-13~18 ===\n")
  print(pa_res$normalized_performance_by_sec %>%
        filter(sec_id == "KR7356540005", 기준일자 >= as.Date("2026-03-13"), 기준일자 <= as.Date("2026-03-18")))
}

if ("sec별_기여수익률" %in% names(pa_res)) {
  cat("\n=== sec별_기여수익률: ACE 종합채권 2026-03-13~18 ===\n")
  print(pa_res$sec별_기여수익률 %>%
        filter(sec_id == "KR7356540005", 기준일자 >= as.Date("2026-03-13"), 기준일자 <= as.Date("2026-03-18")))
}

# Excel export에 쓰이는 single_port_historical_weight 함수 직접 호출
cat("\n\n=== single_port_historical_weight 호출 (Excel export 원천) ===\n")

# 의존성 임시 stub (gt, reactable 등은 Excel export 관련 plot 생성 부분이라 불필요)
single_port_historical_weight <- function(res_list_portfolio, mapping_method, Portfolio_name) {
  for_reordering_classification <- universe_non_derivative_table %>%
    dplyr::filter(classification_method == mapping_method, !is.na(classification)) %>%
    dplyr::pull(classification) %>% unique()
  korean_items <- sort(for_reordering_classification[stringr::str_detect(for_reordering_classification, "[가-힣]")])
  non_korean_items <- sort(for_reordering_classification[!stringr::str_detect(for_reordering_classification, "[가-힣]")])
  sorted_data <- c("포트폴리오", korean_items[korean_items != "유동성및기타"], non_korean_items, "유동성및기타")

  table_data_sec <-
    res_list_portfolio$sec별_비중 %>%
    group_by(sec_id) %>%
    mutate(순자산비중_시작 = first(weight_순자산), .before = weight_순자산) %>%
    select(기준일자, sec_id, 순자산비중_시작, weight_순자산, `weight_PA(T)`) %>% ungroup() %>%
    left_join(
      res_list_portfolio$normalized_performance_by_sec %>%
        select(기준일자, sec_id, 개별수익률 = 누적수익률),
      by = join_by(기준일자, sec_id)) %>%
    left_join(res_list_portfolio$sec별_기여수익률, by = join_by(기준일자, sec_id)) %>%
    group_by(sec_id) %>%
    fill(ITEM_NM, 자산군, .direction = "downup") %>%
    mutate(종목명 = ITEM_NM[n()]) %>% ungroup() %>%
    select(자산군, 기준일자, 분석시작일, 분석종료일, 종목코드 = sec_id, 종목명,
           개별수익률, 기여수익률 = 총손익기여도,
           순자산비중_시작, 순자산비중_종료 = weight_순자산, 평가자산비중 = `weight_PA(T)`)

  table_data_classification <-
    res_list_portfolio$자산군별_비중 %>%
    group_by(자산군) %>%
    mutate(순자산비중_시작 = first(weight_순자산), .before = weight_순자산) %>% ungroup() %>%
    left_join(res_list_portfolio$normalized_performance_by_자산군 %>%
                select(기준일자, 자산군, 개별수익률 = 누적수익률), by = join_by(자산군, 기준일자)) %>%
    left_join(res_list_portfolio$자산군별_기여수익률) %>%
    select(자산군, 기준일자, 분석시작일, 분석종료일, 개별수익률, 기여수익률 = 총손익기여도,
           순자산비중_시작, 순자산비중_종료 = weight_순자산, 평가자산비중 = `weight_PA(T)`)

  raw_data <- bind_rows(table_data_classification, table_data_sec) %>%
    arrange(자산군) %>%
    mutate(across(contains("수익률"), .fns = ~replace_na(.x, 0))) %>%
    mutate(비중변화 = 순자산비중_종료 - 순자산비중_시작) %>%
    mutate(종목명 = if_else(is.na(종목명), 자산군, 종목명)) %>%
    mutate(자산군 = factor(자산군, levels = sorted_data))

  return(list(raw_data = raw_data, table_data_sec = table_data_sec,
              table_data_classification = table_data_classification))
}

sphw <- single_port_historical_weight(pa_res, "방법3", "08N81")

cat("\n=== raw_data ACE 종합채권 2026-03-13~18 (Excel _sec별_plot 원천) ===\n")
print(sphw$raw_data %>% filter(종목코드=="KR7356540005",
                                기준일자 >= as.Date("2026-03-13"), 기준일자 <= as.Date("2026-03-18")) %>%
      select(기준일자, 종목코드, 개별수익률, 기여수익률, 순자산비중_시작, 순자산비중_종료, 평가자산비중))

cat("\n=== table_data_sec ACE 종합채권 2026-03-13~18 ===\n")
print(sphw$table_data_sec %>% filter(종목코드=="KR7356540005",
                                     기준일자 >= as.Date("2026-03-13"), 기준일자 <= as.Date("2026-03-18")))

dbDisconnect(con_dt); dbDisconnect(con_sol)
cat("\n✓ 완료\n")
