library(DBI)
library(RMariaDB)
library(dplyr)
library(lubridate)
options(digits = 15)

con_dt <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='dt', host='192.168.195.55')

# DB USDKRW 비교
usdkrw_db <- dbGetQuery(con_dt, "SELECT STD_DT, TR_STD_RT FROM DWCI10260 WHERE CURR_DS_CD='USD' AND STD_DT>=20260101 AND STD_DT<=20260115") %>%
  mutate(STD_DT = ymd(STD_DT)) %>% arrange(STD_DT) %>%
  mutate(return_fx = TR_STD_RT/lag(TR_STD_RT) - 1)

cat("\n=== DB USDKRW 1/7~1/12 ===\n")
print(usdkrw_db %>% filter(STD_DT >= "2026-01-07", STD_DT <= "2026-01-12"))

# KR7411060007 (ACE KRX금현물) FX split 계산
# MA410 1/9 데이터
pa <- dbGetQuery(con_dt, "SELECT pr_date, pl_gb, amt, val, std_val FROM MA000410 WHERE fund_id='08N81' AND sec_id='KR7411060007' AND pr_date='20260109'")
cat("\n=== KR7411060007 MA410 1/9 ===\n")
print(pa)

총손익 <- sum(pa$amt)
시가평가 <- max(pa$val)
기준평가 <- max(pa$std_val)
조정평가 <- 시가평가 - 총손익

cat("\n총손익:", 총손익, "\n")
cat("조정_평가시가평가액:", 조정평가, "\n")
cat("종목별수익률:", 총손익/조정평가, "\n")

# ECOS return on 1/9
r_fx_ecos <- USDKRW$`return_USD/KRW`[USDKRW$기준일자 == as.Date("2026-01-09")]
cat("\nECOS return_USDKRW(1/9):", r_fx_ecos, "\n")
cat("r_sec (FX adj):", (1 + 총손익/조정평가) / (1 + r_fx_ecos) - 1, "\n")
cat("Without FX adj:", 총손익/조정평가, "\n")

dbDisconnect(con_dt)
