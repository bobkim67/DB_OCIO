# R 프로덕션 PA_from_MOS 함수 headless 호출
# 08K88 ACE 2026-03-06 정확한 값 확인
library(tidyverse)
library(DBI)
library(RMariaDB)
library(lubridate)
library(blob)
library(fuzzyjoin)
library(timetk)
library(tictoc)
options(digits = 15)

# DB 연결 (func_PA 내부에서도 connect 하지만 전역도 필요)
con_dt  <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='dt', host='192.168.195.55')
con_sol <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='solution', host='192.168.195.55')

# 1) universe 테이블
universe_non_derivative_table <- dbGetQuery(con_sol, "SELECT * FROM universe_non_derivative")
universe_derivative_table <- dbGetQuery(con_sol, "SELECT * FROM universe_derivative")

# 2) USDKRW (pad_by_time)
USDKRW <- dbGetQuery(con_dt, "SELECT STD_DT, TR_STD_RT FROM DWCI10260 WHERE CURR_DS_CD='USD' AND STD_DT>='20251101'") %>%
  mutate(기준일자 = ymd(STD_DT), `USD/KRW` = as.numeric(TR_STD_RT)) %>%
  select(기준일자, `USD/KRW`) %>% arrange(기준일자) %>%
  pad_by_time(.date_var = 기준일자, .by = "day", .fill_na_direction = "down")

# 3) T_move_date_calc
T_move_date_calc <- function(date, n) date + days(n)

# 4) 모펀드_mapping (R 원본 line 746-756)
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

cat("08K88 모펀드_mapping:\n")
print(모펀드_mapping %>% filter(FUND_CD == "08K88"))

# 5) historical_universe_DWPM10530_TOTAL + pulling_모자구조
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

cat("\n08K88 pulling_모자구조:\n")
print(pulling_모자구조 %>% filter(FUND_CD == "08K88"))

# 6) PA_from_MOS source (주의: func 파일에 library() 있어서 다시 load)
# 핵심만 source하기 위해 직접 파일 source 후 함수만 쓰기
source("debug/PA_module_funcs_only.R")
cat("\nPA_from_MOS source loaded\n")

# 7) 실행
cat("\n=== PA_from_MOS('08K88', 2026-01-01 ~ 2026-04-16) 실행 ===\n")
result <- PA_from_MOS(from = as.Date("2026-01-01"), to = as.Date("2026-04-16"), fund_cd = "08K88")

if (!is.null(result) && is.list(result)) {
  cat("\nresult names:\n")
  print(names(result))

  # sec_return_weight (ACE 03-06)
  if ("sec_return_weight" %in% names(result)) {
    cat("\n=== sec_return_weight: ACE 2026-03-03~10 ===\n")
    print(result$sec_return_weight %>%
          filter(sec_id == "KR7365780006", pr_date >= as.Date("2026-03-03"), pr_date <= as.Date("2026-03-10")))
  }

  # historical_performance_information_final (조정평가/평가시가/ETF 보정)
  if ("historical_performance_information_final" %in% names(result)) {
    cat("\n=== historical_performance_information_final: ACE 2026-03-03~10 ===\n")
    tmp <- result$historical_performance_information_final %>%
      filter(sec_id == "KR7365780006", pr_date >= as.Date("2026-03-01"), pr_date <= as.Date("2026-03-10"))
    print(tmp %>% select(pr_date, 시가평가액, 평가시가평가액, 총손익금액_당일,
                          any_of(c("평가시가평가액보정")), 순설정액, 조정_평가시가평가액, 종목별당일수익률, position_gb))
    cat("\ntmp columns:\n")
    print(colnames(tmp))
  }

  # before_exclude_FX_효과_in_sec
  if ("before_exclude_FX_효과_in_sec" %in% names(result)) {
    cat("\n=== before_exclude_FX_효과_in_sec: ACE 2026-03-03~10 ===\n")
    tmp <- result$before_exclude_FX_효과_in_sec %>%
      filter(sec_id == "KR7365780006", pr_date >= as.Date("2026-03-03"), pr_date <= as.Date("2026-03-10"))
    print(tmp %>% select(pr_date, 시가평가액, 평가시가평가액, `시가평가액(T-1)`, 조정_평가시가평가액,
                          총손익금액_당일, 순설정금액, `순자산총액(T-1)+당일순설정금액`, weight_PA, `수익률(FX_제외)`))
    write.csv(tmp, "debug/debug_ace_08K88_R_PRODUCTION.csv", row.names = FALSE, fileEncoding = "UTF-8")
    cat("✓ debug_ace_08K88_R_PRODUCTION.csv 저장\n")
  }
}

dbDisconnect(con_dt)
dbDisconnect(con_sol)
cat("\n✓ 완료\n")
