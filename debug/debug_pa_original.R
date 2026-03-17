# ============================================================
# 원본 PA_from_MOS 핵심 파이프라인 (Shiny/plotly 제거)
# 08N81, 2026-01-08 ~ 2026-03-12
# ============================================================
library(tidyverse)
library(DBI)
library(RMariaDB)
library(lubridate)
library(blob)
library(fuzzyjoin)
library(timetk)
library(tictoc)
options(digits = 15)

fund_cd <- "08N81"
from <- as.Date("2026-01-08")
to   <- as.Date("2026-03-12")

con_dt  <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='dt', host='192.168.195.55')
con_sol <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='solution', host='192.168.195.55')

# ── 전역 데이터 로드 ──
universe_non_derivative_table <- dbGetQuery(con_sol, "SELECT * FROM universe_non_derivative")
universe_derivative_table <- dbGetQuery(con_sol, "SELECT * FROM universe_derivative")

모펀드_mapping <- tibble(FUND_CD = "08N81", CLSS_MTFD_CD = "08N81")
pulling_모자구조 <- tibble(FUND_CD = "08N81", 모펀드통합 = "08N81")

USDKRW <- dbGetQuery(con_dt, "SELECT STD_DT, TR_STD_RT FROM DWCI10260 WHERE CURR_DS_CD='USD' AND STD_DT>='20251201'") %>%
  mutate(기준일자 = ymd(STD_DT), `USD/KRW` = as.numeric(TR_STD_RT)) %>%
  select(기준일자, `USD/KRW`) %>%
  pad_by_time(.date_var = 기준일자, .by = "day", .fill_na_direction = "down")

T_move_date_calc <- function(date, n) date + days(n)

# ── 함수 정의 (원본 그대로) ──
get_PA_source_data <- function(fund_cd, start_date, end_date) {
  start_date <- str_remove_all(start_date - days(10), "-")
  end_date <- str_remove_all(end_date, "-")
  dbGetQuery(con_dt, sprintf(
    "SELECT * FROM MA000410 WHERE fund_id='%s' AND pr_date>='%s' AND pr_date<='%s'",
    fund_cd, start_date, end_date
  )) %>% mutate(pr_date = ymd(pr_date))
}

get_fund_inform_data <- function(fund_cd, start_date, end_date) {
  start_date <- start_date - days(1)
  start_date <- str_remove_all(start_date, "-")
  end_date <- str_remove_all(end_date, "-")
  temp <- dbGetQuery(con_dt, sprintf(
    "SELECT STD_DT, IMC_CD, FUND_CD, NAST_AMT, OPNG_AMT, MNR_EMNO, MNR_EMNO2, DEPT_CD, MOD_STPR, PDD_CHNG_STPR, DD1_ERN_RT, FXHG_RT FROM DWPM10510 WHERE FUND_CD='%s' AND STD_DT>='%s' AND STD_DT<='%s'",
    fund_cd, start_date, end_date
  )) %>% mutate(STD_DT = ymd(STD_DT), DD1_ERN_RT = DD1_ERN_RT/100) %>% arrange(STD_DT)
  if(temp$PDD_CHNG_STPR[1] == 0) {
    temp %>% mutate(수정기준가 = MOD_STPR, PDD_CHNG_STPR = if_else(MOD_STPR > 9500, lag(MOD_STPR, default=10000), lag(MOD_STPR, default=1000)))
  } else {
    temp %>% mutate(수정기준가 = MOD_STPR, MOD_STPR = (MOD_STPR/MOD_STPR[1])*1000, PDD_CHNG_STPR = lag(MOD_STPR, default = 1000*(1-DD1_ERN_RT[1])))
  }
}

# ── PA_from_MOS 본문 (line 101~670 핵심) ──
class_M_fund <- fund_cd  # 08N81 has no mother fund

historical_PA_source_data <- get_PA_source_data(fund_cd = class_M_fund, start_date = from, end_date = to)
historical_fund_inform_data_class_M_fund <- get_fund_inform_data(fund_cd = class_M_fund, start_date = from, end_date = to)
historical_fund_inform_data_fund_cd <- get_fund_inform_data(fund_cd = fund_cd, start_date = from, end_date = to)
historical_fund_inform_data <- historical_fund_inform_data_class_M_fund %>%
  select(-c(FUND_CD, MOD_STPR, PDD_CHNG_STPR)) %>%
  left_join(historical_fund_inform_data_fund_cd %>% select(STD_DT, FUND_CD, MOD_STPR, PDD_CHNG_STPR))

cat("데이터로딩완료\n")

# DWPM10530
related_funds <- "08N81"
historical_position_DWPM10530 <- dbGetQuery(con_dt, sprintf(
  "SELECT STD_DT, FUND_CD, ITEM_CD, ITEM_NM, POS_DS_CD, EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY FROM DWPM10530 WHERE FUND_CD='%s' AND STD_DT>='%s' AND ITEM_NM NOT LIKE '%%미지급%%' AND ITEM_NM NOT LIKE '%%미수%%'",
  class_M_fund, format(from - days(10), "%Y%m%d")
)) %>% mutate(기준일자 = ymd(STD_DT)) %>% select(-STD_DT)

historical_position_DWPM10530 <- historical_position_DWPM10530 %>%
  mutate(across(.cols = c(EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY), .fns = ~replace_na(.x, 0))) %>%
  group_by(기준일자, FUND_CD, ITEM_CD) %>%
  reframe(POS_DS_CD = POS_DS_CD[1], ITEM_NM = ITEM_NM[1],
          across(.cols = c(EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY), .fns = ~sum(.x))) %>%
  filter(EVL_AMT + PDD_QTY + BUY_QTY + SELL_QTY != 0) %>%
  mutate(POS_DS_CD = if_else(POS_DS_CD == "매도" & PDD_QTY + BUY_QTY <= SELL_QTY, "매수", POS_DS_CD),
         EVL_AMT = if_else(POS_DS_CD == "매도", -EVL_AMT, EVL_AMT))

# 순설정금액
mapping_trade_code <- dbGetQuery(con_dt, "SELECT DISTINCT tr_cd, synp_cd, tr_whl_nm, synp_cd_nm FROM DWCI10160")
hist_red <- dbGetQuery(con_dt, sprintf(
  "SELECT * FROM DWPM12880 WHERE fund_cd='%s' AND tr_dt>='%s' AND tr_dt<='%s'",
  class_M_fund, format(from, "%Y%m%d"), format(to, "%Y%m%d")
))
if(nrow(hist_red) > 0) {
  pure_redemption <- hist_red %>%
    left_join(mapping_trade_code) %>%
    mutate(이월순자산 = if_else(str_detect(tr_whl_nm, "해지"), -bf_nast_flct_amt, bf_nast_flct_amt),
           기준일자 = ymd(tr_dt)) %>%
    group_by(기준일자) %>% reframe(순설정금액 = sum(이월순자산))
} else {
  pure_redemption <- tibble(기준일자 = as.Date(character()), 순설정금액 = numeric())
}

# ETF환매 보정 (line 177-183)
ETF_환매_평가시가평가액보정 <- dbGetQuery(con_dt, sprintf(
  "SELECT t.std_dt, t.fund_cd, t.item_cd, t.item_nm, t.trd_amt, t.tr_upr, t.trd_pl_amt, c.tr_whl_nm FROM DWPM10520 t LEFT JOIN DWCI10160 c ON t.tr_cd=c.tr_cd AND t.synp_cd=c.synp_cd WHERE t.fund_cd='%s' AND t.std_dt>='%s' AND t.std_dt<='%s' AND c.tr_whl_nm LIKE '%%ETF발행시장환매%%'",
  class_M_fund, format(from - days(10), "%Y%m%d"), format(to, "%Y%m%d")
))
if(nrow(ETF_환매_평가시가평가액보정) > 0) {
  ETF_환매_평가시가평가액보정 <- ETF_환매_평가시가평가액보정 %>%
    mutate(기준일자 = ymd(std_dt)) %>%
    group_by(fund_cd, item_cd, tr_upr, trd_pl_amt) %>%
    reframe(기준일자 = max(기준일자), 평가시가평가액보정 = trd_amt[1])
} else {
  ETF_환매_평가시가평가액보정 <- tibble(기준일자 = as.Date(character()), item_cd = character(), 평가시가평가액보정 = numeric())
}

설정액_DWPM10510 <- dbGetQuery(con_dt, sprintf(
  "SELECT STD_DT, FUND_CD, NAST_AMT, OPNG_AMT FROM DWPM10510 WHERE STD_DT>='%s' AND STD_DT<='%s' AND FUND_CD IN ('%s')",
  format(T_move_date_calc(from, -5), "%Y%m%d"), format(to, "%Y%m%d"), class_M_fund
)) %>% mutate(STD_DT = ymd(STD_DT))

cat("보조데이터로딩완료\n")

# ── 핵심 파이프라인 (line 193~488) ──
# line 193-220: MA410 + DWPM10530 join → sec_id 그룹핑
기초정보요약 <- historical_PA_source_data %>%
  mutate(기준일자 = pr_date) %>%
  left_join(historical_position_DWPM10530 %>% select(기준일자, ITEM_CD, ITEM_NM, POS_DS_CD, EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY),
            by = join_by(기준일자, sec_id == ITEM_CD)) %>%
  mutate(position_gb = if_else(position_gb == "LONG" & POS_DS_CD == "매도", "SHORT", position_gb),
         POS_DS_CD = if_else(position_gb == "SHORT" & POS_DS_CD == "매수", "매도", POS_DS_CD)) %>%
  group_by(pr_date, sec_id) %>%
  reframe(
    시가평가액 = max(val),
    평가시가평가액 = if_else(PDD_QTY[1] == 0 & BUY_QTY[1] != 0, max(val) - sum(amt), max(std_val))[1],
    총손익금액_당일 = sum(amt),
    환산 = sum(amt[pl_gb == "환산"], na.rm = TRUE),
    asset_gb = asset_gb[1],
    position_gb = if_else((n() >= 2) & (sum(pl_gb == "평가") != 0),
                          first(position_gb[pl_gb == "평가"]), position_gb[1]),
    ITEM_NM = ITEM_NM[1],
    POS_DS_CD = POS_DS_CD[1]
  ) %>% distinct()

# Fill forward + fund_inform join
기초정보요약 <- 기초정보요약 %>%
  group_by(sec_id) %>%
  mutate(평가시가평가액 = case_when(
    시가평가액 == 0 & 평가시가평가액 == 0 & sec_id != "000000000000" ~ lag(평가시가평가액),
    시가평가액 == 0 ~ lag(시가평가액),
    TRUE ~ 평가시가평가액)) %>%
  fill(ITEM_NM, .direction = "up") %>%
  ungroup() %>%
  mutate(ITEM_NM = if_else(is.na(ITEM_NM) & sec_id == "000000000000", "기타비용", ITEM_NM),
         POS_DS_CD = if_else(is.na(POS_DS_CD) & sec_id == "000000000000", "매수", POS_DS_CD)) %>%
  left_join(historical_fund_inform_data %>%
              rename(pr_date = STD_DT, 순자산총액 = NAST_AMT, 설정액 = OPNG_AMT, 수정기준가_raw = 수정기준가) %>%
              select(-contains("MNR_EMNO"), -DEPT_CD, -IMC_CD), by = join_by(pr_date))

# 통화/자산군 매핑 (line 262-340)
기초정보요약 <- 기초정보요약 %>%
  left_join(universe_non_derivative_table %>%
              filter(classification_method == "Currency Exposure", !is.na(classification)) %>%
              select(ISIN, 노출통화 = classification) %>% distinct(),
            by = join_by(sec_id == ISIN))

# 파생 규칙
deriv_rules <- universe_derivative_table %>%
  filter(classification_method == "Currency Exposure", !is.na(classification)) %>%
  transmute(asset_gb, keyword, rule_ccy = classification, priority = row_number()) %>%
  mutate(asset_gb = coalesce(asset_gb, "")) %>% distinct()

need_deriv <- 기초정보요약 %>% filter(is.na(노출통화)) %>% select(sec_id, ITEM_NM, asset_gb) %>% distinct()
if(nrow(need_deriv) > 0 && nrow(deriv_rules) > 0) {
  deriv_candidates <- need_deriv %>%
    mutate(asset_gb_x = coalesce(asset_gb, "")) %>%
    regex_left_join(deriv_rules %>% rename(asset_gb_y = asset_gb), by = c("ITEM_NM" = "keyword")) %>%
    filter(asset_gb_y == "" | asset_gb_x == asset_gb_y) %>%
    group_by(sec_id) %>% slice_min(order_by = priority, n = 1, with_ties = FALSE) %>% ungroup() %>%
    transmute(sec_id, deriv_ccy = rule_ccy)
  기초정보요약 <- 기초정보요약 %>%
    left_join(deriv_candidates, by = "sec_id") %>%
    mutate(노출통화 = coalesce(노출통화, deriv_ccy)) %>% select(-deriv_ccy)
}

기초정보요약 <- 기초정보요약 %>%
  mutate(노출통화 = coalesce(노출통화, case_when(
    asset_gb == "유동" & str_sub(sec_id, 1, 2) == "US" ~ "USD",
    asset_gb == "유동" & str_sub(sec_id, 1, 2) %in% c("KR","00") ~ "KRW",
    asset_gb == "기타비용" ~ "KRW",
    TRUE ~ 노출통화))) %>%
  mutate(노출통화 = if_else(is.na(노출통화), if_else(str_sub(sec_id, 1, 2) == "KR", "KRW", "USD"), 노출통화))

# 콜론 필터 + 순자산비중 + SHORT 처리
기초정보요약 <- 기초정보요약 %>%
  filter(!(str_detect(ITEM_NM, "\\(콜") & 시가평가액 == 0)) %>%
  mutate(평가시가평가액 = if_else(is.na(평가시가평가액), 0, 평가시가평가액)) %>%
  arrange(pr_date, desc(시가평가액)) %>%
  mutate(순자산비중 = if_else(position_gb == "SHORT", -시가평가액/순자산총액, 시가평가액/순자산총액))

# 자산군 매핑
기초정보요약 <- 기초정보요약 %>%
  left_join(universe_non_derivative_table %>%
              filter(classification_method == "방법3", !is.na(classification)) %>%
              select(ISIN, 자산군 = classification) %>% distinct(),
            by = join_by(sec_id == ISIN)) %>%
  mutate(자산군 = coalesce(자산군, case_when(
    asset_gb %in% c("유동","기타비용") ~ "유동성및기타",
    str_detect(asset_gb, "선물|선도환") & 노출통화 != "KRW" ~ "FX",
    str_detect(asset_gb, "선물|선도환") ~ "유동성및기타",
    str_detect(asset_gb, "주식") & 노출통화 != "KRW" ~ "해외주식",
    str_detect(asset_gb, "주식") ~ "국내주식",
    str_detect(asset_gb, "채권") & 노출통화 != "KRW" ~ "해외채권",
    str_detect(asset_gb, "채권") ~ "국내채권",
    TRUE ~ "유동성및기타")))

# 유동 USD → FX
기초정보요약 <- 기초정보요약 %>%
  mutate(자산군 = if_else(asset_gb == "유동" & 노출통화 != "KRW" & sec_id != "000000000000", "FX", 자산군))

# SHORT, 순설정액, 조정_평가시가평가액, ETF보정
기초정보요약 <- 기초정보요약 %>%
  mutate(시가평가액 = if_else(position_gb == "SHORT", -시가평가액, 시가평가액),
         평가시가평가액 = if_else(position_gb == "SHORT", -평가시가평가액, 평가시가평가액)) %>%
  left_join(ETF_환매_평가시가평가액보정 %>% select(-any_of(c("item_nm","fund_cd"))),
            by = join_by(pr_date == 기준일자, sec_id == item_cd)) %>%
  mutate(순설정액 = if_else(abs(시가평가액 - (총손익금액_당일 + 평가시가평가액)) < 100, 0,
                          시가평가액 - (총손익금액_당일 + 평가시가평가액))) %>%
  mutate(across(.cols = c(contains("시가평가액"), "순설정액"), .fns = ~replace_na(.x, 0))) %>%
  mutate(position_gb = coalesce(position_gb, "LONG")) %>%
  mutate(평가시가평가액 = 평가시가평가액 + replace_na(평가시가평가액보정, 0)) %>%
  mutate(조정_평가시가평가액 = case_when(
    position_gb == "SHORT" ~ 평가시가평가액,
    position_gb == "LONG" ~ if_else((순설정액 < 0) | (시가평가액 == 0 & 평가시가평가액 > 0),
                                     평가시가평가액, 시가평가액 - 총손익금액_당일))) %>%
  mutate(종목별당일수익률 = if_else(position_gb == "LONG", 총손익금액_당일/조정_평가시가평가액, 총손익금액_당일/(-조정_평가시가평가액))) %>%
  mutate(노출통화 = if_else(is.na(노출통화), "KRW", 노출통화))

cat("자산군매핑완료\n")

# ── 파생 그룹핑 (line 391-488) ──
Grouping_dictionary <- deriv_rules %>%
  mutate(group = paste0(asset_gb, "_", keyword)) %>%
  group_by(group) %>% summarise(patterns = list(unique(keyword)), .groups = "drop") %>%
  tibble::deframe()

asset_파생_keywords <- unique(deriv_rules$asset_gb)

기초정보요약 %>% filter(grepl(paste(unlist(asset_파생_keywords), collapse = "|"), asset_gb)) -> Grouping_파생
기초정보요약 %>% filter(!grepl(paste(unlist(asset_파생_keywords), collapse = "|"), asset_gb)) -> Grouping_ex_파생

derivatives_list <- list()
for (group in names(Grouping_dictionary)) {
  grp_data <- Grouping_파생 %>% filter(grepl(paste(Grouping_dictionary[[group]], collapse = "|"), ITEM_NM))
  if(nrow(grp_data) == 0) {
    derivatives_list[[group]] <- grp_data
  } else {
    roll_over_date <- grp_data %>%
      group_by(pr_date) %>% filter(n() >= 2) %>% ungroup() %>%
      group_by(pr_date, sec_id, 노출통화) %>%
      reframe(sec_id = sec_id[1], asset_gb = asset_gb[1], ITEM_NM = ITEM_NM[1],
              시가평가액 = sum(시가평가액), 조정_평가시가평가액 = 조정_평가시가평가액,
              순자산총액 = 순자산총액[1], 순자산비중 = sum(순자산비중),
              총손익금액_당일 = sum(총손익금액_당일), 환산 = sum(환산)) %>%
      mutate(POS_DS_CD = if_else(조정_평가시가평가액 < 0, "매도", "매수"),
             position_gb = if_else(조정_평가시가평가액 < 0, "SHORT", "LONG"))

    grp_data %>%
      group_by(pr_date) %>% filter(n() == 1) %>%
      mutate(sec_id = sec_id[1], ITEM_NM = ITEM_NM[1]) %>%
      bind_rows(roll_over_date) %>% arrange(pr_date) %>% ungroup() %>%
      group_by(sec_id) %>%
      mutate(종목별당일수익률 = 총손익금액_당일 / abs(조정_평가시가평가액)) %>%
      ungroup() -> temp_data
    derivatives_list[[group]] <- temp_data
  }
}
bind_rows(derivatives_list) -> derivatives_list_position_gb
historical_performance_information_final <- bind_rows(Grouping_ex_파생, derivatives_list_position_gb)

cat("파생그룹핑완료, rows:", nrow(historical_performance_information_final), "\n")

# ── FX split (line 527-553) ──
historical_performance_information_final %>%
  filter(!is.na(조정_평가시가평가액)) %>%
  arrange(pr_date) %>%
  select(pr_date, sec_id, asset_gb, position_gb, ITEM_NM, 시가평가액, 조정_평가시가평가액, 순자산총액, 순자산비중, 총손익금액_당일, 환산, 노출통화) %>%
  left_join(pure_redemption, by = join_by(pr_date == 기준일자)) %>%
  mutate(순설정금액 = if_else(is.na(순설정금액), 0, 순설정금액)) %>%
  left_join(historical_performance_information_final %>%
              group_by(pr_date) %>% reframe(순자산총액 = 순자산총액[1]) %>%
              mutate(`순자산총액(T-1)` = lag(순자산총액, default = 0, n = 1))) %>%
  group_by(sec_id) %>%
  mutate(`시가평가액(T-1)` = lag(시가평가액, default = 0, n = 1)) %>%
  mutate(`순자산총액(T-1)+당일순설정금액` = `순자산총액(T-1)` + 순설정금액) %>%
  mutate(weight_PA = 조정_평가시가평가액 / `순자산총액(T-1)+당일순설정금액`) %>%
  ungroup() %>%
  left_join(USDKRW %>% mutate(`return_USD/KRW` = `USD/KRW`/lag(`USD/KRW`) - 1),
            by = join_by(pr_date == 기준일자)) %>%
  mutate(r_sec = if_else(노출통화 == "USD",
                         (1 + 총손익금액_당일/조정_평가시가평가액) / (1 + `return_USD/KRW`) - 1,
                         총손익금액_당일/조정_평가시가평가액)) %>%
  mutate(환산_adjust = if_else(노출통화 == "USD",
                              `시가평가액(T-1)` * `return_USD/KRW` + `return_USD/KRW` * r_sec * `시가평가액(T-1)`,
                              환산)) %>%
  mutate(총손익금액_당일_FX_adjust = 총손익금액_당일 - 환산_adjust) -> before_exclude_FX

cat("FX_split완료\n")

# ── CSV 출력 ──
output <- before_exclude_FX %>%
  filter(pr_date >= from & pr_date <= to) %>%
  select(pr_date, sec_id, ITEM_NM, 노출통화, 시가평가액, 조정_평가시가평가액, 순자산총액,
         순자산비중, weight_PA, `순자산총액(T-1)`, 순설정금액, `순자산총액(T-1)+당일순설정금액`,
         `시가평가액(T-1)`, 총손익금액_당일, 총손익금액_당일_FX_adjust, 환산, 환산_adjust,
         r_sec, `return_USD/KRW`)

write.csv(output, "debug_pa_R_original_intermediate.csv", row.names = FALSE)
cat("✓ debug_pa_R_original_intermediate.csv 저장 (", nrow(output), "rows)\n")

# 핵심 종목 확인
cat("\n=== KR7411060007 (1/9~1/12) ===\n")
output %>% filter(sec_id == "KR7411060007") %>% head(5) %>%
  select(pr_date, 순자산비중, weight_PA, `순자산총액(T-1)+당일순설정금액`, r_sec, `return_USD/KRW`) %>%
  print()

dbDisconnect(con_dt)
dbDisconnect(con_sol)
cat("\n✓ 완료\n")
