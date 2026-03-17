library(DBI)
library(RMariaDB)
library(dplyr)
library(lubridate)
options(digits = 15)

con_dt <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='dt', host='192.168.195.55')

# DWPM10510 for 08N81, 1/8~1/12
nast <- dbGetQuery(con_dt, "SELECT STD_DT, FUND_CD, NAST_AMT, MOD_STPR, OPNG_AMT FROM DWPM10510 WHERE FUND_CD='08N81' AND STD_DT>=20260108 AND STD_DT<=20260112")
cat("=== DWPM10510 08N81 ===\n")
print(nast)

# 관련 펀드 체크: 08N81을 모펀드로 하는 자펀드?
# CLSS_MTFD_CD = 모펀드코드
related <- dbGetQuery(con_dt, "SELECT FUND_CD, FUND_NM, CLSS_MTFD_CD, MNC_DS_CD FROM DWPI10011 WHERE IMC_CD='003228' AND CLSS_MTFD_CD='08N81' AND EFTV_END_DT='99991231'")
cat("\n=== 08N81을 모펀드로 하는 자펀드 ===\n")
print(related)

# 만약 자펀드가 있다면 그들의 NAST도 확인
if(nrow(related) > 0) {
  funds <- paste0("'", related$FUND_CD, "'", collapse=",")
  nast2 <- dbGetQuery(con_dt, sprintf("SELECT STD_DT, FUND_CD, NAST_AMT FROM DWPM10510 WHERE FUND_CD IN (%s) AND STD_DT=20260109", funds))
  cat("\n=== 자펀드 NAST(1/9) ===\n")
  print(nast2)
}

# R의 pulling_모자구조 → 모펀드통합
# 실제 R 코드에서는 DWPI10011의 모자 구조 정보를 사용
# 확인: 08N81의 MNC_DS_CD
self <- dbGetQuery(con_dt, "SELECT FUND_CD, FUND_NM, CLSS_MTFD_CD, MNC_DS_CD FROM DWPI10011 WHERE FUND_CD='08N81' AND IMC_CD='003228'")
cat("\n=== 08N81 자체 정보 ===\n")
print(self)

dbDisconnect(con_dt)
