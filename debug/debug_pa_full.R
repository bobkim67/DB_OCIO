# ============================================================
# PA 중간 데이터 추출 — Python 검증용
# RStudio에서 실행: Ctrl+Shift+Enter (전체 실행)
# ============================================================

library(DBI)
library(RMariaDB)
library(dplyr)
library(tidyr)
library(stringr)
library(lubridate)
library(timetk)
library(ecos)

options(digits = 15)

fund_cd <- "08N81"
from <- as.Date("2026-01-08")
to   <- as.Date("2026-03-12")

# ── DB 접속 ──
con_dt  <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='dt', host='192.168.195.55')
con_sol <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='solution', host='192.168.195.55')

# ── 1. 모펀드 확인 ──
class_M_fund <- dbGetQuery(con_dt, sprintf(
  "SELECT CLSS_MTFD_CD FROM DWPI10011 WHERE FUND_CD='%s' AND IMC_CD='003228' LIMIT 1", fund_cd
))$CLSS_MTFD_CD
if(is.null(class_M_fund) || is.na(class_M_fund)) class_M_fund <- fund_cd
cat("class_M_fund:", class_M_fund, "\n")

# ── 2. MA410 로드 ──
historical_PA_source_data <- dbGetQuery(con_dt, sprintf(
  "SELECT * FROM MA000410 WHERE fund_id='%s' AND pr_date>='%s' AND pr_date<='%s'",
  class_M_fund, format(from - days(10), "%Y%m%d"), format(to, "%Y%m%d")
)) %>% mutate(pr_date = ymd(pr_date))

cat("MA410 rows:", nrow(historical_PA_source_data), ", dates:", n_distinct(historical_PA_source_data$pr_date), "\n")

# ── 3. DWPM10510 (fund_inform) ──
get_fund_inform <- function(fc, s, e) {
  temp <- dbGetQuery(con_dt, sprintf(
    "SELECT STD_DT, FUND_CD, NAST_AMT, OPNG_AMT, MOD_STPR, PDD_CHNG_STPR, DD1_ERN_RT FROM DWPM10510 WHERE FUND_CD='%s' AND STD_DT>='%s' AND STD_DT<='%s'",
    fc, format(s, "%Y%m%d"), format(e, "%Y%m%d")
  )) %>% mutate(STD_DT = ymd(STD_DT), DD1_ERN_RT = DD1_ERN_RT/100) %>% arrange(STD_DT)

  if(temp$PDD_CHNG_STPR[1] == 0) {
    temp <- temp %>%
      mutate(수정기준가 = MOD_STPR,
             PDD_CHNG_STPR = if_else(MOD_STPR > 9500, lag(MOD_STPR, default=10000), lag(MOD_STPR, default=1000)))
  } else {
    temp <- temp %>%
      mutate(수정기준가 = MOD_STPR,
             MOD_STPR = (MOD_STPR / MOD_STPR[1]) * 1000,
             PDD_CHNG_STPR = lag(MOD_STPR, default = 1000*(1-DD1_ERN_RT[1])))
  }
  temp
}

historical_fund_inform_data_class_M <- get_fund_inform(class_M_fund, from - days(1), to)
if(class_M_fund != fund_cd) {
  historical_fund_inform_data_fund_cd <- get_fund_inform(fund_cd, from - days(1), to)
  historical_fund_inform_data <- historical_fund_inform_data_class_M %>%
    select(-c(FUND_CD, MOD_STPR, PDD_CHNG_STPR)) %>%
    left_join(historical_fund_inform_data_fund_cd %>% select(STD_DT, FUND_CD, MOD_STPR, PDD_CHNG_STPR))
} else {
  historical_fund_inform_data <- historical_fund_inform_data_class_M
}
historical_fund_inform_data <- historical_fund_inform_data %>% mutate(daily_return = MOD_STPR / PDD_CHNG_STPR - 1)

cat("fund_inform rows:", nrow(historical_fund_inform_data), "\n")

# ── 4. DWPM10530 (보유종목) ──
historical_position <- dbGetQuery(con_dt, sprintf(
  "SELECT STD_DT, FUND_CD, ITEM_CD, ITEM_NM, POS_DS_CD, COALESCE(EVL_AMT,0) AS EVL_AMT, COALESCE(PDD_QTY,0) AS PDD_QTY, COALESCE(BUY_QTY,0) AS BUY_QTY, COALESCE(SELL_QTY,0) AS SELL_QTY FROM DWPM10530 WHERE FUND_CD='%s' AND STD_DT>='%s' AND STD_DT<='%s' AND ITEM_NM NOT LIKE '%%미지급%%' AND ITEM_NM NOT LIKE '%%미수%%'",
  class_M_fund, format(from - days(10), "%Y%m%d"), format(to, "%Y%m%d")
)) %>% mutate(기준일자 = ymd(STD_DT)) %>% select(-STD_DT)

historical_position <- historical_position %>%
  mutate(across(.cols = c(EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY), .fns = ~replace_na(.x, 0))) %>%
  group_by(기준일자, FUND_CD, ITEM_CD) %>%
  reframe(POS_DS_CD = POS_DS_CD[1], ITEM_NM = ITEM_NM[1],
          across(.cols = c(EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY), .fns = ~sum(.x))) %>%
  filter(EVL_AMT + PDD_QTY + BUY_QTY + SELL_QTY != 0) %>%
  mutate(POS_DS_CD = if_else(POS_DS_CD == "매도" & PDD_QTY + BUY_QTY <= SELL_QTY, "매수", POS_DS_CD),
         EVL_AMT = if_else(POS_DS_CD == "매도", -EVL_AMT, EVL_AMT))

# ── 5. sec_id 그룹핑 (MA410 + 10530 join) ──
기초정보요약 <- historical_PA_source_data %>%
  mutate(기준일자 = pr_date) %>%
  left_join(historical_position %>% select(기준일자, ITEM_CD, ITEM_NM, POS_DS_CD, PDD_QTY, BUY_QTY, SELL_QTY),
            by = join_by(기준일자, sec_id == ITEM_CD)) %>%
  mutate(position_gb = case_when(
    !is.na(POS_DS_CD) & position_gb == "LONG" & POS_DS_CD == "매도" ~ "SHORT",
    TRUE ~ position_gb
  )) %>%
  group_by(pr_date, sec_id) %>%
  reframe(
    시가평가액 = max(val),
    평가시가평가액 = if_else(PDD_QTY[1] == 0 & BUY_QTY[1] != 0, max(val) - sum(amt), max(std_val))[1],
    총손익금액 = sum(amt),
    환산 = sum(amt[pl_gb == "환산"], na.rm = TRUE),
    asset_gb = asset_gb[1],
    position_gb = if_else((n() >= 2) & (sum(pl_gb == "평가") != 0),
                          first(position_gb[pl_gb == "평가"]), position_gb[1]),
    ITEM_NM = ITEM_NM[1],
    POS_DS_CD = POS_DS_CD[1]
  ) %>% distinct()

# Fill forward
기초정보요약 <- 기초정보요약 %>%
  group_by(sec_id) %>%
  mutate(평가시가평가액 = case_when(
    시가평가액 == 0 & 평가시가평가액 == 0 & sec_id != "000000000000" ~ lag(평가시가평가액),
    시가평가액 == 0 ~ lag(시가평가액),
    TRUE ~ 평가시가평가액)) %>%
  ungroup()

# Join fund_inform → 순자산총액
기초정보요약 <- 기초정보요약 %>%
  left_join(historical_fund_inform_data %>%
              rename(pr_date = STD_DT, 순자산총액 = NAST_AMT, 설정액 = OPNG_AMT) %>%
              select(pr_date, 순자산총액, 설정액, 수정기준가, PDD_CHNG_STPR),
            by = "pr_date")

# SHORT 처리
기초정보요약 <- 기초정보요약 %>%
  mutate(순자산비중 = if_else(position_gb == "SHORT", -시가평가액/순자산총액, 시가평가액/순자산총액)) %>%
  mutate(시가평가액 = if_else(position_gb == "SHORT", -시가평가액, 시가평가액),
         평가시가평가액 = if_else(position_gb == "SHORT", -평가시가평가액, 평가시가평가액))

# 순설정액 + 조정_평가시가평가액
기초정보요약 <- 기초정보요약 %>%
  mutate(순설정액 = if_else(abs(시가평가액 - (총손익금액 + 평가시가평가액)) < 100, 0,
                          시가평가액 - (총손익금액 + 평가시가평가액))) %>%
  mutate(조정_평가시가평가액 = case_when(
    position_gb == "SHORT" ~ 평가시가평가액,
    position_gb == "LONG" ~ if_else((순설정액 < 0) | (시가평가액 == 0 & 평가시가평가액 > 0),
                                     평가시가평가액, 시가평가액 - 총손익금액)
  ))

# ── 6. 순설정금액 (DWPM12880) ──
mapping_trade <- dbGetQuery(con_dt, "SELECT DISTINCT tr_cd, synp_cd, tr_whl_nm FROM DWCI10160")
hist_red <- dbGetQuery(con_dt, sprintf(
  "SELECT * FROM DWPM12880 WHERE fund_cd='%s' AND tr_dt>='%s' AND tr_dt<='%s'",
  class_M_fund, format(from, "%Y%m%d"), format(to, "%Y%m%d")
))

if(nrow(hist_red) > 0) {
  pure_red <- hist_red %>%
    left_join(mapping_trade) %>%
    mutate(이월순자산 = if_else(str_detect(tr_whl_nm, "해지"), -bf_nast_flct_amt, bf_nast_flct_amt),
           기준일자 = ymd(tr_dt)) %>%
    group_by(기준일자) %>%
    reframe(순설정금액 = sum(이월순자산))
} else {
  pure_red <- tibble(기준일자 = as.Date(character()), 순설정금액 = numeric())
}

# ── 7. weight_PA ──
# 순자산총액(T-1): 기초정보요약의 pr_date별 순자산총액 → lag
nast_by_date <- 기초정보요약 %>%
  group_by(pr_date) %>%
  reframe(순자산총액 = 순자산총액[1]) %>%
  mutate(`순자산총액_T1` = lag(순자산총액, default = 0, n = 1))

기초정보요약 <- 기초정보요약 %>%
  left_join(nast_by_date %>% select(pr_date, 순자산총액_T1), by = "pr_date") %>%
  left_join(pure_red, by = join_by(pr_date == 기준일자)) %>%
  mutate(순설정금액 = if_else(is.na(순설정금액), 0, 순설정금액)) %>%
  mutate(denom = 순자산총액_T1 + 순설정금액,
         weight_PA = 조정_평가시가평가액 / denom)

# ── 8. USDKRW ──
usdkrw <- dbGetQuery(con_dt, sprintf(
  "SELECT STD_DT, TR_STD_RT FROM DWCI10260 WHERE CURR_DS_CD='USD' AND STD_DT>='%s' AND STD_DT<='%s'",
  format(from - days(10), "%Y%m%d"), format(to, "%Y%m%d")
)) %>% mutate(STD_DT = ymd(STD_DT)) %>% arrange(STD_DT) %>%
  mutate(return_fx = TR_STD_RT / lag(TR_STD_RT) - 1)

# ── 9. 통화/자산군 매핑 ──
ccy_map <- dbGetQuery(con_sol, "SELECT ISIN, classification AS 노출통화 FROM universe_non_derivative WHERE classification_method='Currency Exposure' AND classification IS NOT NULL")
asset_map <- dbGetQuery(con_sol, "SELECT ISIN, classification AS 자산군 FROM universe_non_derivative WHERE classification_method='방법3' AND classification IS NOT NULL")

기초정보요약 <- 기초정보요약 %>%
  left_join(ccy_map, by = join_by(sec_id == ISIN)) %>%
  mutate(노출통화 = coalesce(노출통화,
                           case_when(str_sub(sec_id, 1, 2) == "KR" ~ "KRW",
                                     str_sub(sec_id, 1, 2) == "00" ~ "KRW",
                                     asset_gb == "기타비용" ~ "KRW",
                                     asset_gb == "유동" & str_sub(sec_id, 1, 2) %in% c("KR","00") ~ "KRW",
                                     asset_gb == "유동" & str_sub(sec_id, 1, 2) == "US" ~ "USD",
                                     asset_gb == "유동" ~ "KRW",
                                     TRUE ~ "USD"))) %>%
  left_join(asset_map, by = join_by(sec_id == ISIN)) %>%
  mutate(자산군 = coalesce(자산군,
                        case_when(
                          asset_gb %in% c("유동","기타비용") ~ "유동성및기타",
                          str_detect(asset_gb, "선물|선도환") & 노출통화 != "KRW" ~ "FX",
                          str_detect(asset_gb, "선물|선도환") ~ "유동성및기타",
                          str_detect(asset_gb, "주식") & 노출통화 != "KRW" ~ "해외주식",
                          str_detect(asset_gb, "주식") ~ "국내주식",
                          str_detect(asset_gb, "채권") & 노출통화 != "KRW" ~ "해외채권",
                          str_detect(asset_gb, "채권") ~ "국내채권",
                          TRUE ~ "유동성및기타")))

# FX: 유동 USD → FX 재분류
기초정보요약 <- 기초정보요약 %>%
  mutate(자산군 = if_else(asset_gb == "유동" & 노출통화 != "KRW" & sec_id != "000000000000", "FX", 자산군))

# ── 10. FX split (r_sec) ──
기초정보요약 <- 기초정보요약 %>%
  mutate(종목별수익률 = if_else(abs(조정_평가시가평가액) > 0, 총손익금액 / abs(조정_평가시가평가액), 0)) %>%
  group_by(sec_id) %>%
  mutate(`시가평가액_T1` = lag(시가평가액, default = 0, n = 1)) %>%
  ungroup() %>%
  left_join(usdkrw %>% select(pr_date = STD_DT, return_fx), by = "pr_date") %>%
  mutate(return_fx = if_else(is.na(return_fx), 0, return_fx))

is_sec <- !(기초정보요약$asset_gb %in% c("유동","기타비용")) & !str_detect(기초정보요약$asset_gb, "선물|선도환")
usd_mask <- 기초정보요약$노출통화 == "USD" & is_sec

기초정보요약$r_sec <- 기초정보요약$종목별수익률
기초정보요약$r_sec[usd_mask] <- (1 + 기초정보요약$종목별수익률[usd_mask]) / (1 + 기초정보요약$return_fx[usd_mask]) - 1

기초정보요약$FX효과 <- 0
기초정보요약$FX효과[usd_mask] <- 기초정보요약$`시가평가액_T1`[usd_mask] * 기초정보요약$return_fx[usd_mask] * (1 + 기초정보요약$r_sec[usd_mask])

# 기여수익률
기초정보요약$기여수익률 <- 기초정보요약$r_sec * abs(기초정보요약$weight_PA)
fx_mask <- 기초정보요약$자산군 == "FX"
기초정보요약$기여수익률[fx_mask] <- 기초정보요약$종목별수익률[fx_mask] * abs(기초정보요약$weight_PA[fx_mask])

# ── 11. 분석기간 필터 → CSV 저장 ──
analysis <- 기초정보요약 %>% filter(pr_date >= from & pr_date <= to)

# KR7411060007 상세
cat("\n=== KR7411060007 (1/9~1/12) ===\n")
kr411 <- analysis %>% filter(sec_id == "KR7411060007") %>%
  select(pr_date, sec_id, 자산군, 노출통화, 시가평가액, 조정_평가시가평가액, 순자산총액, 순자산비중,
         weight_PA, denom, 순자산총액_T1, 순설정금액, 종목별수익률, r_sec, return_fx, 기여수익률, FX효과)
print(head(kr411, 5))

# 전 종목 일별 데이터 CSV 저장
output <- analysis %>%
  select(pr_date, sec_id, ITEM_NM, 자산군, 노출통화, 시가평가액, 조정_평가시가평가액,
         순자산총액, 순자산비중, weight_PA, denom, 순자산총액_T1, 순설정금액,
         종목별수익률, r_sec, return_fx, 기여수익률, FX효과, `시가평가액_T1`)

write.csv(output, "debug_pa_R_intermediate.csv", row.names = FALSE)
cat("\n✓ debug_pa_R_intermediate.csv 저장 완료 (", nrow(output), "rows)\n")

# 자산군별 요약
cat("\n=== 자산군별 기여수익률 합계 ===\n")
asset_sum <- analysis %>%
  group_by(자산군) %>%
  summarise(기여합계 = sum(기여수익률, na.rm=TRUE),
            비중평균 = mean(순자산비중, na.rm=TRUE),
            FX효과합계 = sum(FX효과, na.rm=TRUE))
print(asset_sum)

# 포트폴리오 수익률
fi_period <- historical_fund_inform_data %>% filter(STD_DT >= from & STD_DT <= to)
port_cum <- tail(cumprod(1 + fi_period$daily_return) - 1, 1)
cat("\n포트폴리오 누적수익률:", port_cum, "\n")

dbDisconnect(con_dt)
dbDisconnect(con_sol)
cat("\n✓ 완료\n")
