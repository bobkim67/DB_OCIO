library(DBI)
library(RMariaDB)
library(dplyr)
library(lubridate)
options(digits = 15)

con_dt <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='dt', host='192.168.195.55')
con_sol <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='solution', host='192.168.195.55')

# 1. KR7411060007 Currency Exposure
ccy <- dbGetQuery(con_sol, "SELECT ISIN, classification FROM universe_non_derivative WHERE ISIN='KR7411060007' AND classification_method='Currency Exposure'")
cat("Currency Exposure:", ccy$classification, "\n")

# 2. USDKRW from DB (DWCI10260)
usdkrw <- dbGetQuery(con_dt, "SELECT STD_DT, TR_STD_RT FROM DWCI10260 WHERE CURR_DS_CD='USD' AND STD_DT>=20260101 AND STD_DT<=20260115") %>%
  mutate(STD_DT = ymd(STD_DT)) %>% arrange(STD_DT) %>%
  mutate(return_fx = TR_STD_RT/lag(TR_STD_RT) - 1)

cat("\nUSDKRW 1/8~1/10:\n")
print(usdkrw %>% filter(STD_DT >= "2026-01-08", STD_DT <= "2026-01-10"))

# 3. MA410 data for KR7411060007
pa <- dbGetQuery(con_dt, "SELECT pr_date, pl_gb, amt, val, std_val, modify_unav_chg FROM MA000410 WHERE fund_id='08N81' AND sec_id='KR7411060007' AND pr_date='20260109'")
cat("\nMA410 1/9:\n")
print(pa)

total_pnl <- sum(pa$amt)
max_val <- max(pa$val)
max_std <- max(pa$std_val)
adj_val <- max_val - total_pnl

cat("\ntotal_pnl:", total_pnl, "\n")
cat("adj_val:", adj_val, "\n")
cat("raw_return:", total_pnl / adj_val, "\n")

# 4. FX adj calculation
r_fx <- usdkrw$return_fx[usdkrw$STD_DT == as.Date("2026-01-09")]
cat("r_fx(1/9):", r_fx, "\n")

if(!is.na(r_fx) & length(r_fx) > 0) {
  r_sec <- (1 + total_pnl/adj_val) / (1 + r_fx) - 1
  cat("r_sec (FX adj):", r_sec, "\n")
} else {
  cat("r_fx is NA or missing!\n")
}

# 5. Check if R original uses ECOS (calendar pad) vs DB (biz day only)
# DB only has business days → 1/9 return = (1457.6 - 1450.6)/1450.6
# ECOS pad_by_time(day) → same value for business days
# Key question: does R join pr_date (business day) with ECOS (calendar day)?

# In R original func_PA:
# line 545: left_join(USDKRW %>% mutate(return=USD_KRW/lag(USD_KRW)-1), by=join_by(pr_date==기준일자))
# USDKRW has been pad_by_time(day) → calendar dates
# pr_date is business day → join matches
# So same return_fx for business days

# 6. Verify: R original uses sec_id level loop or group_by?
# line 557-569: group_by(pr_date, sec_id, 노출통화)
# → per sec, per date → FX adj applied to each sec individually
# Same as Python

cat("\nConclusion: If 노출통화=USD, FX adj should be applied in both R and Python\n")
cat("R Excel shows raw return (0.001352) → possible R code path difference\n")

dbDisconnect(con_dt)
dbDisconnect(con_sol)
