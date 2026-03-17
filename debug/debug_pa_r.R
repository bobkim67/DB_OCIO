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

# ── 모펀드 확인 ──
clss <- dbGetQuery(con_dt, sprintf("SELECT CLSS_MTFD_CD FROM DWPI10011 WHERE FUND_CD='%s' AND EFTV_END_DT='99991231'", fund_cd))
cat("Raw CLSS_MTFD_CD:", clss$CLSS_MTFD_CD, "| length:", length(clss$CLSS_MTFD_CD), "| class:", class(clss$CLSS_MTFD_CD), "\n")
if(nrow(clss)==0 || is.null(clss$CLSS_MTFD_CD) || is.na(clss$CLSS_MTFD_CD[1]) || nchar(trimws(clss$CLSS_MTFD_CD[1]))==0) {
  class_M_fund <- fund_cd
} else {
  class_M_fund <- clss$CLSS_MTFD_CD[1]
}
cat("class_M_fund:", class_M_fund, "\n")

# ── MA000410 로드 ──
buf_start <- from - days(10)
pa_sql <- sprintf("SELECT * FROM MA000410 WHERE fund_id='%s' AND pr_date>='%s' AND pr_date<='%s'",
                  class_M_fund, format(buf_start, "%Y%m%d"), format(to, "%Y%m%d"))
pa_raw <- dbGetQuery(con_dt, pa_sql) %>%
  mutate(pr_date = ymd(pr_date))

cat("MA410 rows:", nrow(pa_raw), "\n")

# ── DWPM10510 ──
fi_sql <- sprintf("SELECT STD_DT, FUND_CD, MOD_STPR, PDD_CHNG_STPR, NAST_AMT, OPNG_AMT FROM DWPM10510 WHERE FUND_CD='%s' AND STD_DT>='%s' AND STD_DT<='%s'",
                  class_M_fund, format(buf_start, "%Y%m%d"), format(to, "%Y%m%d"))
fund_info <- dbGetQuery(con_dt, fi_sql) %>%
  mutate(STD_DT = ymd(STD_DT)) %>%
  arrange(STD_DT)

# MOD_STPR rebase to 1000
if(fund_info$PDD_CHNG_STPR[1]==0){
  base <- ifelse(fund_info$MOD_STPR[1]>9500, 10000, 1000)
  fund_info <- fund_info %>%
    mutate(수정기준가 = MOD_STPR,
           PDD_CHNG_STPR = lag(MOD_STPR, default=base))
}

fund_info <- fund_info %>%
  mutate(daily_return = 수정기준가/PDD_CHNG_STPR - 1)

cat("\n=== Fund Info (first 5) ===\n")
print(fund_info %>% select(STD_DT, NAST_AMT, 수정기준가, daily_return) %>% head(5))

# ── DWPM10530 positions ──
pos_sql <- sprintf("SELECT STD_DT, FUND_CD, ITEM_CD, ITEM_NM, POS_DS_CD, EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY
                    FROM DWPM10530 WHERE FUND_CD='%s' AND STD_DT>='%s' AND STD_DT<='%s'
                    AND ITEM_NM NOT LIKE '%%%%미지급%%%%' AND ITEM_NM NOT LIKE '%%%%미수%%%%'",
                   class_M_fund, format(buf_start - days(5), "%Y%m%d"), format(to, "%Y%m%d"))
positions <- dbGetQuery(con_dt, pos_sql) %>%
  mutate(기준일자 = ymd(STD_DT),
         across(c(EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY), ~replace_na(.x, 0))) %>%
  group_by(기준일자, FUND_CD, ITEM_CD) %>%
  reframe(POS_DS_CD = POS_DS_CD[1],
          ITEM_NM = ITEM_NM[1],
          across(c(EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY), ~sum(.x))) %>%
  filter(EVL_AMT + PDD_QTY + BUY_QTY + SELL_QTY != 0) %>%
  mutate(POS_DS_CD = if_else(POS_DS_CD == "매도" & PDD_QTY + BUY_QTY <= SELL_QTY, "매수", POS_DS_CD),
         EVL_AMT = if_else(POS_DS_CD == "매도", -EVL_AMT, EVL_AMT))

# ── MA410 + DWPM10530 join → 기초정보요약 ──
기초정보요약 <- pa_raw %>%
  left_join(positions %>% distinct(),
            by = join_by(pr_date == 기준일자, sec_id == ITEM_CD)) %>%
  mutate(position_gb = if_else(position_gb == "LONG" & POS_DS_CD == "매도", "SHORT", position_gb)) %>%
  group_by(fund_id, pr_date, sec_id) %>%
  reframe(ITEM_NM = ITEM_NM[1],
          POS_DS_CD = POS_DS_CD[1],
          시가평가액 = max(val),
          평가시가평가액 = case_when(PDD_QTY[1] == 0 & BUY_QTY[1] != 0 ~ max(val) - sum(amt),
                              TRUE ~ max(std_val)),
          asset_gb = asset_gb[1],
          position_gb = if_else((n() >= 2) & (sum(pl_gb == "평가") != 0),
                                first(position_gb[pl_gb == "평가"]),
                                position_gb[1])
  ) %>% distinct() %>%
  group_by(sec_id) %>%
  mutate(평가시가평가액 = case_when(시가평가액 == 0 & 평가시가평가액 == 0 & sec_id != "000000000000" ~ lag(평가시가평가액),
                              시가평가액 == 0 ~ lag(시가평가액),
                              TRUE ~ 평가시가평가액)) %>%
  ungroup()

# Join fund info for 순자산총액
기초정보요약 <- 기초정보요약 %>%
  left_join(fund_info %>% select(pr_date = STD_DT, 순자산총액 = NAST_AMT, 설정액 = OPNG_AMT, 수정기준가, PDD_CHNG_STPR),
            by = "pr_date")

# 총손익금액 per sec per date
총손익 <- pa_raw %>%
  group_by(pr_date, sec_id) %>%
  reframe(총손익금액_당일 = sum(amt),
          환산 = sum(amt[pl_gb == "환산"], na.rm = TRUE))

기초정보요약 <- 기초정보요약 %>%
  left_join(총손익, by = c("pr_date", "sec_id"))

# SHORT sign
기초정보요약 <- 기초정보요약 %>%
  mutate(시가평가액 = if_else(position_gb == "SHORT", -시가평가액, 시가평가액),
         평가시가평가액 = if_else(position_gb == "SHORT", -평가시가평가액, 평가시가평가액))

# 순설정액 (종목 레벨)
기초정보요약 <- 기초정보요약 %>%
  mutate(순설정액 = if_else(abs(시가평가액 - (총손익금액_당일 + 평가시가평가액)) < 100, 0,
                         시가평가액 - (총손익금액_당일 + 평가시가평가액)))

# 조정_평가시가평가액
기초정보요약 <- 기초정보요약 %>%
  mutate(조정_평가시가평가액 = case_when(
    position_gb == "SHORT" ~ 평가시가평가액,
    position_gb == "LONG" ~ if_else((순설정액 < 0) | (시가평가액 == 0 & 평가시가평가액 > 0),
                                     평가시가평가액,
                                     시가평가액 - 총손익금액_당일)
  ))

# 순자산총액(T-1) + 순설정금액(펀드레벨)
nast_by_date <- 기초정보요약 %>%
  group_by(pr_date) %>%
  reframe(순자산총액 = 순자산총액[1]) %>%
  mutate(`순자산총액_T1` = lag(순자산총액, default = 0, n = 1))

# 순설정금액 (펀드 레벨, DWPM12880)
mapping_trade_code <- dbGetQuery(con_dt, "SELECT DISTINCT tr_cd, synp_cd, tr_whl_nm, synp_cd_nm FROM DWCI10160")

red_sql <- sprintf("SELECT * FROM DWPM12880 WHERE fund_cd='%s' AND tr_dt>='%s' AND tr_dt<='%s'",
                   class_M_fund, format(from, "%Y%m%d"), format(to, "%Y%m%d"))
historical_redemption <- dbGetQuery(con_dt, red_sql)

if(nrow(historical_redemption) > 0) {
  pure_redemption <- historical_redemption %>%
    left_join(mapping_trade_code) %>%
    mutate(이월순자산변동금액 = if_else(str_detect(tr_whl_nm, "해지"), -bf_nast_flct_amt, bf_nast_flct_amt)) %>%
    mutate(기준일자 = ymd(tr_dt)) %>%
    group_by(기준일자) %>%
    reframe(순설정금액 = sum(이월순자산변동금액))
} else {
  pure_redemption <- data.frame(기준일자 = as.Date(character()), 순설정금액 = numeric())
}

cat("\n=== 순설정금액 (fund level) ===\n")
print(pure_redemption %>% head(10))

# Merge
기초정보요약 <- 기초정보요약 %>%
  left_join(nast_by_date, by = "pr_date") %>%
  left_join(pure_redemption, by = join_by(pr_date == 기준일자)) %>%
  mutate(순설정금액 = if_else(is.na(순설정금액), 0, 순설정금액))

기초정보요약 <- 기초정보요약 %>%
  mutate(`순자산총액_T1_plus_설정` = 순자산총액_T1 + 순설정금액,
         weight_PA = 조정_평가시가평가액 / `순자산총액_T1_plus_설정`)

# Print ACE200 weight details
cat("\n=== ACE200 (KR7105190003) weight_PA ===\n")
ace200 <- 기초정보요약 %>%
  filter(sec_id == "KR7105190003") %>%
  select(pr_date, 시가평가액, 평가시가평가액, 총손익금액_당일, 순설정액, 조정_평가시가평가액,
         순자산총액.x, 순자산총액_T1, 순설정금액, `순자산총액_T1_plus_설정`, weight_PA) %>%
  head(10)
print(ace200, width = 200)

# Average weight for ACE200 over analysis period
ace200_period <- 기초정보요약 %>% filter(sec_id == "KR7105190003" & pr_date >= from & pr_date <= to)
cat("\nACE200 avg weight_PA:", mean(ace200_period$weight_PA, na.rm = TRUE), "\n")
cat("ACE200 first weight_PA:", ace200_period$weight_PA[1], "\n")
cat("ACE200 last weight_PA:", ace200_period$weight_PA[nrow(ace200_period)], "\n")

# All secs on 20260109 (second trading day, so T-1 exists)
cat("\n=== All sec weight_PA on 2026-01-09 ===\n")
w0109 <- 기초정보요약 %>%
  filter(pr_date == as.Date("2026-01-09")) %>%
  select(sec_id, ITEM_NM, 조정_평가시가평가액, `순자산총액_T1_plus_설정`, weight_PA, position_gb) %>%
  arrange(desc(abs(weight_PA)))
print(w0109, width = 200)

# Sum of weights on each date
cat("\n=== Sum of weight_PA by date (first 10) ===\n")
wsum <- 기초정보요약 %>%
  group_by(pr_date) %>%
  summarise(sum_weight = sum(weight_PA, na.rm = TRUE), n_secs = n()) %>%
  head(10)
print(wsum)

dbDisconnect(con_dt)
cat("\nDone.\n")
