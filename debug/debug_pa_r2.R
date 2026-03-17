library(DBI)
library(RMariaDB)
library(dplyr)
library(tidyr)
library(stringr)
library(lubridate)

options(digits = 15)

fund_cd <- "08N81"
from <- as.Date("2026-01-08")
to   <- as.Date("2026-03-12")

con_dt <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='dt', host='192.168.195.55')

class_M_fund <- fund_cd  # 08N81 has no mother fund

# ── Load MA410 ──
pa_raw <- dbGetQuery(con_dt, sprintf(
  "SELECT * FROM MA000410 WHERE fund_id='%s' AND pr_date>='%s' AND pr_date<='%s'",
  class_M_fund, format(from - days(10), "%Y%m%d"), format(to, "%Y%m%d")
)) %>% mutate(pr_date = ymd(pr_date))

# ── Load Fund Info ──
fund_info <- dbGetQuery(con_dt, sprintf(
  "SELECT STD_DT, MOD_STPR, PDD_CHNG_STPR, NAST_AMT, OPNG_AMT FROM DWPM10510 WHERE FUND_CD='%s' AND STD_DT>='%s' AND STD_DT<='%s'",
  class_M_fund, format(from - days(10), "%Y%m%d"), format(to, "%Y%m%d")
)) %>% mutate(STD_DT = ymd(STD_DT)) %>% arrange(STD_DT)

if(fund_info$PDD_CHNG_STPR[1]==0){
  fund_info <- fund_info %>%
    mutate(수정기준가 = MOD_STPR,
           PDD_CHNG_STPR = lag(MOD_STPR, default=1000))
}

fund_info <- fund_info %>% mutate(daily_return = 수정기준가/PDD_CHNG_STPR - 1)

# ── Aggregate MA410 by (date, sec_id) ──
sec_agg <- pa_raw %>%
  group_by(pr_date, sec_id) %>%
  reframe(시가평가액 = max(val),
          평가시가평가액 = max(std_val),
          총손익금액 = sum(amt),
          환산 = sum(amt[pl_gb == "환산"], na.rm = TRUE),
          asset_gb = asset_gb[1],
          position_gb = if_else((n() >= 2) & (sum(pl_gb == "평가") != 0),
                                first(position_gb[pl_gb == "평가"]),
                                position_gb[1])
  ) %>% distinct()

# Fill forward 평가시가평가액 for zero-val dates
sec_agg <- sec_agg %>%
  group_by(sec_id) %>%
  mutate(평가시가평가액 = case_when(
    시가평가액 == 0 & 평가시가평가액 == 0 & sec_id != "000000000000" ~ lag(평가시가평가액),
    시가평가액 == 0 ~ lag(시가평가액),
    TRUE ~ 평가시가평가액)) %>%
  ungroup()

# SHORT sign flip
sec_agg <- sec_agg %>%
  mutate(시가평가액 = if_else(position_gb == "SHORT", -시가평가액, 시가평가액),
         평가시가평가액 = if_else(position_gb == "SHORT", -평가시가평가액, 평가시가평가액))

# 순설정액
sec_agg <- sec_agg %>%
  mutate(순설정액 = if_else(abs(시가평가액 - (총손익금액 + 평가시가평가액)) < 100, 0,
                         시가평가액 - (총손익금액 + 평가시가평가액)))

# 조정_평가시가평가액
sec_agg <- sec_agg %>%
  mutate(조정_평가시가평가액 = case_when(
    position_gb == "SHORT" ~ 평가시가평가액,
    position_gb == "LONG" ~ if_else((순설정액 < 0) | (시가평가액 == 0 & 평가시가평가액 > 0),
                                     평가시가평가액,
                                     시가평가액 - 총손익금액)
  ))

# Join fund info
sec_agg <- sec_agg %>%
  left_join(fund_info %>% select(pr_date = STD_DT, NAST_AMT, 수정기준가, PDD_CHNG_STPR, daily_return),
            by = "pr_date")

# 순자산비중 (weight_순자산) = 시가평가액 / NAST_AMT
sec_agg <- sec_agg %>%
  mutate(weight_순자산 = 시가평가액 / NAST_AMT)

# 순자산총액(T-1)
nast_dates <- sec_agg %>%
  group_by(pr_date) %>%
  reframe(순자산총액 = NAST_AMT[1]) %>%
  mutate(순자산총액_T1 = lag(순자산총액, default = 0, n = 1))

sec_agg <- sec_agg %>%
  left_join(nast_dates, by = "pr_date")

# 순설정금액 (DWPM12880)
mapping_trade_code <- dbGetQuery(con_dt, "SELECT DISTINCT tr_cd, synp_cd, tr_whl_nm, synp_cd_nm FROM DWCI10160")
hist_red <- dbGetQuery(con_dt, sprintf(
  "SELECT * FROM DWPM12880 WHERE fund_cd='%s' AND tr_dt>='%s' AND tr_dt<='%s'",
  class_M_fund, format(from, "%Y%m%d"), format(to, "%Y%m%d")
))

if(nrow(hist_red) > 0) {
  pure_red <- hist_red %>%
    left_join(mapping_trade_code) %>%
    mutate(이월순자산변동금액 = if_else(str_detect(tr_whl_nm, "해지"), -bf_nast_flct_amt, bf_nast_flct_amt)) %>%
    mutate(기준일자 = ymd(tr_dt)) %>%
    group_by(기준일자) %>%
    reframe(순설정금액 = sum(이월순자산변동금액))
} else {
  pure_red <- tibble(기준일자 = as.Date(character()), 순설정금액 = numeric())
}

sec_agg <- sec_agg %>%
  left_join(pure_red, by = join_by(pr_date == 기준일자)) %>%
  mutate(순설정금액 = if_else(is.na(순설정금액), 0, 순설정금액))

sec_agg <- sec_agg %>%
  mutate(denom = 순자산총액_T1 + 순설정금액,
         weight_PA = 조정_평가시가평가액 / denom)

# ── Filter to analysis period ──
analysis <- sec_agg %>% filter(pr_date >= from & pr_date <= to)

# ── ACE200 results ──
ace200 <- analysis %>% filter(sec_id == "KR7105190003")
cat("=== ACE200 (국내주식) ===\n")
cat("weight_순자산 avg:", mean(ace200$weight_순자산, na.rm=TRUE), "\n")
cat("weight_순자산 first:", ace200$weight_순자산[1], "\n")
cat("weight_순자산 last:", ace200$weight_순자산[nrow(ace200)], "\n")
cat("weight_PA avg:", mean(ace200$weight_PA, na.rm=TRUE), "\n")
cat("weight_PA first:", ace200$weight_PA[1], "\n")
cat("weight_PA last:", ace200$weight_PA[nrow(ace200)], "\n")

# Individual return (cumulative)
cat("\nACE200 cumulative return (FX excl):\n")
ace200_ret <- cumprod(1 + ace200$총손익금액 / abs(ace200$조정_평가시가평가액)) - 1
cat("  cum_ret:", tail(ace200_ret, 1), "\n")

# ── FX calculation ──
# Load USDKRW
usdkrw <- dbGetQuery(con_dt, sprintf(
  "SELECT STD_DT, TR_STD_RT FROM DWCI10260 WHERE CURR_DS_CD='USD' AND STD_DT>='%s' AND STD_DT<='%s'",
  format(from - days(10), "%Y%m%d"), format(to, "%Y%m%d")
)) %>% mutate(STD_DT = ymd(STD_DT)) %>% arrange(STD_DT) %>%
  mutate(return_fx = TR_STD_RT/lag(TR_STD_RT) - 1)

# Currency exposure mapping
con_sol <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='solution', host='192.168.195.55')
ccy_map <- dbGetQuery(con_sol, "SELECT ISIN, classification FROM universe_non_derivative WHERE classification_method='Currency Exposure' AND classification IS NOT NULL")

analysis <- analysis %>%
  left_join(ccy_map %>% rename(노출통화 = classification), by = join_by(sec_id == ISIN)) %>%
  mutate(노출통화 = coalesce(노출통화,
                           case_when(str_sub(sec_id, 1, 2) == "KR" ~ "KRW",
                                     str_sub(sec_id, 1, 2) == "00" ~ "KRW",
                                     asset_gb == "기타비용" ~ "KRW",
                                     asset_gb == "유동" ~ "KRW",
                                     TRUE ~ "USD")))

# For non-KRW, non-유동/기타비용 securities: apply FX split
analysis <- analysis %>%
  left_join(usdkrw %>% select(pr_date = STD_DT, return_fx), by = "pr_date") %>%
  mutate(return_fx = if_else(is.na(return_fx), 0, return_fx))

# r_sec = (1+R)/(1+r_FX)-1 for USD
is_sec <- !(analysis$asset_gb %in% c("유동", "기타비용")) & !str_detect(analysis$asset_gb, "선물|선도환")
usd_mask <- analysis$노출통화 == "USD" & is_sec

analysis$r_sec <- analysis$총손익금액 / abs(analysis$조정_평가시가평가액)
analysis$r_sec[usd_mask] <- (1 + analysis$총손익금액[usd_mask] / abs(analysis$조정_평가시가평가액[usd_mask])) / (1 + analysis$return_fx[usd_mask]) - 1

# FX effect per sec = total PL - r_sec * adj_val
analysis$FX효과 <- 0
analysis$FX효과[usd_mask] <- analysis$총손익금액[usd_mask] - analysis$r_sec[usd_mask] * abs(analysis$조정_평가시가평가액[usd_mask])

# ACE200 FX split return
ace200_split <- analysis %>% filter(sec_id == "KR7105190003")
cat("\nACE200 r_sec (first 5):", head(ace200_split$r_sec, 5), "\n")

# ── Summary by asset class ──
# Map asset classes
asset_map <- dbGetQuery(con_sol, "SELECT ISIN, classification AS 자산군 FROM universe_non_derivative WHERE classification_method='방법3' AND classification IS NOT NULL")
analysis <- analysis %>%
  left_join(asset_map, by = join_by(sec_id == ISIN))

# Fallback
analysis <- analysis %>%
  mutate(자산군 = coalesce(자산군,
                        case_when(
                          asset_gb %in% c("유동", "기타비용") ~ "유동성및기타",
                          str_detect(asset_gb, "선물|선도환") & 노출통화 != "KRW" ~ "FX",
                          str_detect(asset_gb, "선물|선도환") & 노출통화 == "KRW" ~ "유동성및기타",
                          str_detect(asset_gb, "주식") & 노출통화 != "KRW" ~ "해외주식",
                          str_detect(asset_gb, "주식") & 노출통화 == "KRW" ~ "국내주식",
                          str_detect(asset_gb, "채권") & 노출통화 != "KRW" ~ "해외채권",
                          str_detect(asset_gb, "채권") & 노출통화 == "KRW" ~ "국내채권",
                          TRUE ~ "유동성및기타")))

cat("\n=== Asset class weights (avg over period) ===\n")
asset_w <- analysis %>%
  group_by(자산군) %>%
  summarise(avg_weight_순자산 = mean(weight_순자산, na.rm=TRUE),
            avg_weight_PA = mean(abs(weight_PA), na.rm=TRUE),
            n_secs = n_distinct(sec_id)) %>%
  arrange(desc(avg_weight_순자산))
print(asset_w)

# ── Contribution calculation ──
# 기여수익률 = r_sec * weight_PA (for non-FX)
# For FX: FX효과 / denom + direct FX position contribution
analysis$기여수익률 <- analysis$r_sec * abs(analysis$weight_PA)

cat("\n=== Asset class daily contribution sum (avg) ===\n")
asset_contrib <- analysis %>%
  filter(!(자산군 %in% c("유동성및기타"))) %>%
  group_by(자산군) %>%
  summarise(avg_daily_contrib = mean(기여수익률, na.rm=TRUE))
print(asset_contrib)

# ── Path-dependent cumulative contribution (simplified for 국내주식) ──
fi_period <- fund_info %>% filter(STD_DT >= from & STD_DT <= to) %>% arrange(STD_DT)

기준가격 <- 1000 * cumprod(1 + fi_period$daily_return)
기준가증감 <- c(기준가격[1] - 1000, diff(기준가격))
cum_기준가증감 <- cumsum(기준가증감)
cum_return <- 기준가격/1000 - 1

dates <- fi_period$STD_DT
dt_idx <- setNames(seq_along(dates), as.character(dates))

# 국내주식 (ACE200) path-dependent
ace_daily <- analysis %>% filter(sec_id == "KR7105190003") %>% arrange(pr_date)
cum_sec기여도 <- 0
contrib_results <- c()
for(i in seq_len(nrow(ace_daily))) {
  dt <- ace_daily$pr_date[i]
  idx <- dt_idx[as.character(dt)]
  if(is.na(idx)) next
  port_ret <- fi_period$daily_return[idx]
  contrib <- ace_daily$기여수익률[i]
  가증 <- 기준가증감[idx]

  if(port_ret != 0) {
    sec기여도 <- (contrib / port_ret) * 가증
  } else {
    sec기여도 <- 0
  }
  cum_sec기여도 <- cum_sec기여도 + sec기여도

  if(cum_기준가증감[idx] != 0) {
    총손익기여도 <- cum_return[idx] * cum_sec기여도 / cum_기준가증감[idx]
  } else {
    총손익기여도 <- 0
  }
  contrib_results <- c(contrib_results, 총손익기여도)
}

cat("\n=== 국내주식 (ACE200) cumulative contribution ===\n")
cat("Final cum contribution:", tail(contrib_results, 1), "\n")

# FX total
# FX = sum of FX효과 / denom for all USD secs + direct FX positions
fx_daily <- analysis %>%
  filter(노출통화 != "KRW" | 자산군 == "FX") %>%
  group_by(pr_date) %>%
  summarise(FX효과합계 = sum(FX효과, na.rm=TRUE),
            denom = denom[1]) %>%
  mutate(FX기여_daily = FX효과합계 / denom)

# Direct FX positions
fx_direct <- analysis %>%
  filter(자산군 == "FX") %>%
  group_by(pr_date) %>%
  summarise(직접기여 = sum(기여수익률, na.rm=TRUE))

fx_merged <- fx_daily %>%
  left_join(fx_direct, by = "pr_date") %>%
  mutate(직접기여 = if_else(is.na(직접기여), 0, 직접기여),
         FX기여_total = FX기여_daily + 직접기여)

cat("\n=== FX daily contribution (first 10) ===\n")
print(head(fx_merged, 10))

cat("\n=== FX weight (avg abs weight_PA for USD secs) ===\n")
fx_weight <- analysis %>%
  filter(노출통화 != "KRW") %>%
  group_by(pr_date) %>%
  summarise(fx_weight = sum(abs(weight_PA), na.rm=TRUE))
cat("avg FX weight:", mean(fx_weight$fx_weight, na.rm=TRUE), "\n")

# Path-dependent FX contribution
fx_cum_sec기여도 <- 0
fx_contrib_results <- c()
for(i in seq_len(nrow(fx_merged))) {
  dt <- fx_merged$pr_date[i]
  idx <- dt_idx[as.character(dt)]
  if(is.na(idx)) next
  port_ret <- fi_period$daily_return[idx]
  contrib <- fx_merged$FX기여_total[i]
  가증 <- 기준가증감[idx]

  if(port_ret != 0) {
    sec기여도 <- (contrib / port_ret) * 가증
  } else {
    sec기여도 <- 0
  }
  fx_cum_sec기여도 <- fx_cum_sec기여도 + sec기여도

  if(cum_기준가증감[idx] != 0) {
    총손익기여도 <- cum_return[idx] * fx_cum_sec기여도 / cum_기준가증감[idx]
  } else {
    총손익기여도 <- 0
  }
  fx_contrib_results <- c(fx_contrib_results, 총손익기여도)
}

cat("\n=== FX cumulative contribution ===\n")
cat("Final FX cum contribution:", tail(fx_contrib_results, 1), "\n")

# ── Summary comparison with Excel ──
cat("\n\n========== COMPARISON WITH EXCEL ==========\n")
cat("포트폴리오 누적수익률:", tail(cum_return, 1), " (Excel: 0.02663)\n")
cat("국내주식 기여수익률:", tail(contrib_results, 1), " (Excel: 0.01000)\n")
cat("국내주식 비중(avg_weight_순자산):", mean(ace200$weight_순자산, na.rm=TRUE), " (Excel: 0.08959)\n")
cat("FX 기여수익률:", tail(fx_contrib_results, 1), " (Excel: 0.00926)\n")

dbDisconnect(con_dt)
dbDisconnect(con_sol)
cat("\nDone.\n")
