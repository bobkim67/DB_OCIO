# R 프로덕션 PA_from_MOS 내부 파이프라인을 step-by-step 추적
# ACE 2026-03-06 평가시가평가액이 어떻게 1,703,187,160이 되는지 확인
library(tidyverse)
library(DBI)
library(RMariaDB)
library(lubridate)
library(blob)
library(fuzzyjoin)
library(timetk)
options(digits = 15)

con_dt <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='dt', host='192.168.195.55')
con_sol <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='solution', host='192.168.195.55')

USDKRW <- dbGetQuery(con_dt, "SELECT STD_DT, TR_STD_RT FROM DWCI10260 WHERE CURR_DS_CD='USD' AND STD_DT>='20251101'") %>%
  mutate(기준일자 = ymd(STD_DT), `USD/KRW` = as.numeric(TR_STD_RT)) %>%
  select(기준일자, `USD/KRW`) %>% arrange(기준일자) %>%
  pad_by_time(.date_var = 기준일자, .by = "day", .fill_na_direction = "down")

# 모펀드_mapping, pulling_모자구조
모펀드_mapping <- tbl(con_dt, "DWPI10011") %>%
  select(FUND_CD, EFTV_ST_DT, FUND_WHL_NM, FRST_OPNG_DT, NXT_STOA_DT, RGBF_STOA_DT, MNR_EMNO, CLSS_MTFD_CD, ASCT_FUND_CD, MCF_DS_CD, NEW_ASCT_CLSF_CD, DEPT_CD) %>%
  filter(DEPT_CD %in% c('166','061','064')) %>%
  select(FUND_CD, CLSS_MTFD_CD, FUND_WHL_NM, FRST_OPNG_DT, MNR_EMNO) %>%
  collect() %>%
  mutate(CLSS_MTFD_CD = if_else(is.na(CLSS_MTFD_CD), FUND_CD, CLSS_MTFD_CD)) %>%
  group_by(CLSS_MTFD_CD) %>%
  mutate(FUND_WHL_NM = FUND_WHL_NM[FUND_CD == CLSS_MTFD_CD]) %>%
  mutate(설정일 = min(FRST_OPNG_DT, na.rm = TRUE)) %>%
  ungroup()

hu <- tbl(con_dt, "DWPM10530") %>% filter(STD_DT >= "20210101") %>% select(FUND_CD, ITEM_CD) %>% distinct() %>% collect() %>%
  left_join(모펀드_mapping %>% select(FUND_CD, 모펀드 = CLSS_MTFD_CD))

pulling_모자구조 <- 모펀드_mapping %>% select(FUND_CD, CLSS_MTFD_CD, 설정일) %>%
  left_join(hu %>% select(-FUND_CD) %>% distinct() %>%
            mutate(ITEM_CD = if_else(str_detect(ITEM_CD, "0322800"), str_remove_all(ITEM_CD, "0322800"), ITEM_CD)) %>%
            filter(nchar(ITEM_CD) == 5, ITEM_CD != 모펀드) %>% rename(운용모펀드 = ITEM_CD),
            by = join_by(FUND_CD == 모펀드)) %>%
  mutate(모펀드통합 = if_else(is.na(운용모펀드), CLSS_MTFD_CD, 운용모펀드))

universe_non_derivative_table <- dbGetQuery(con_sol, "SELECT * FROM universe_non_derivative")
universe_derivative_table <- dbGetQuery(con_sol, "SELECT * FROM universe_derivative")

source("debug/PA_module_funcs_only.R")

# PA_from_MOS 직접 복사해서 중간 결과 확인
from <- as.Date("2026-01-01"); to <- as.Date("2026-04-16"); fund_cd <- "08K88"
class_M_fund <- "08K88"

historical_PA_source_data <- get_PA_source_data(class_M_fund, from, to)
historical_fund_inform_data_class_M_fund <- get_fund_inform_data(class_M_fund, from, to)
historical_fund_inform_data_fund_cd <- get_fund_inform_data(fund_cd, from, to)
historical_fund_inform_data <- historical_fund_inform_data_class_M_fund %>%
  select(-c(FUND_CD, MOD_STPR, PDD_CHNG_STPR)) %>%
  left_join(historical_fund_inform_data_fund_cd %>% select(STD_DT, FUND_CD, MOD_STPR, PDD_CHNG_STPR))

historical_position_DWPM10530 <- tbl(con_dt, "DWPM10530") %>%
  select(STD_DT, SEQ, FUND_CD, ITEM_NM, ITEM_CD, POS_DS_CD, EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY) %>%
  filter(STD_DT >= local(str_remove_all(from - days(10), "-"))) %>%
  filter(FUND_CD %in% c(local(pulling_모자구조 %>% select(FUND_CD, 모펀드통합) %>% filter(FUND_CD == class_M_fund) %>% pull(모펀드통합)), class_M_fund)) %>%
  filter(!(str_detect(ITEM_NM, "미지급") | str_detect(ITEM_NM, "미수"))) %>% distinct() %>% collect() %>%
  mutate(기준일자 = ymd(STD_DT)) %>% select(-STD_DT) %>%
  mutate(across(.cols = c(EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY), .fns = ~replace_na(.x, 0))) %>%
  group_by(기준일자, FUND_CD, ITEM_CD) %>%
  reframe(POS_DS_CD = POS_DS_CD[1], ITEM_NM = ITEM_NM[1],
          across(.cols = c(EVL_AMT, PDD_QTY, BUY_QTY, SELL_QTY), .fns = ~sum(.x))) %>%
  filter(EVL_AMT + PDD_QTY + BUY_QTY + SELL_QTY != 0) %>%
  mutate(POS_DS_CD = if_else(POS_DS_CD == "매도" & PDD_QTY + BUY_QTY <= SELL_QTY, "매수", POS_DS_CD),
         EVL_AMT = if_else(POS_DS_CD == "매도", -EVL_AMT, EVL_AMT))

# Step 1: R 프로덕션 reframe (case_when 적용)
step1 <- historical_PA_source_data %>%
  left_join(historical_position_DWPM10530 %>% distinct(), by = join_by(pr_date == 기준일자, sec_id == ITEM_CD)) %>%
  mutate(position_gb = if_else(position_gb == "LONG" & POS_DS_CD == "매도", "SHORT", position_gb)) %>%
  mutate(POS_DS_CD = if_else(position_gb == "SHORT" & POS_DS_CD == "매수", "매도", POS_DS_CD)) %>%
  group_by(fund_id, pr_date, sec_id) %>%
  reframe(ITEM_NM = ITEM_NM[1], POS_DS_CD = POS_DS_CD[1],
          시가평가액 = max(val),
          평가시가평가액 = case_when(PDD_QTY == 0 & BUY_QTY != 0 ~ max(val) - sum(amt),
                                TRUE ~ max(std_val)),
          asset_gb = asset_gb[1],
          position_gb = if_else((n() >= 2) & (sum(pl_gb == "평가") != 0),
                                first(position_gb[pl_gb == "평가"]), position_gb[1])) %>%
  distinct()

cat("=== Step1 reframe (case_when): ACE 2026-03-01~10 ===\n")
print(step1 %>% filter(sec_id == "KR7365780006", pr_date >= as.Date("2026-03-01"), pr_date <= as.Date("2026-03-10")))

# Step 2: lag 보정
step2 <- step1 %>%
  group_by(sec_id) %>%
  mutate(평가시가평가액 = case_when(
    시가평가액 == 0 & 평가시가평가액 == 0 & sec_id != "000000000000" ~ lag(평가시가평가액),
    시가평가액 == 0 ~ lag(시가평가액),
    TRUE ~ 평가시가평가액))

cat("\n=== Step2 lag 보정 후: ACE 2026-03-01~10 ===\n")
print(step2 %>% filter(sec_id == "KR7365780006", pr_date >= as.Date("2026-03-01"), pr_date <= as.Date("2026-03-10")))

# Step 3: fill down (R 프로덕션 라인 254)
step3 <- step2 %>%
  fill(ITEM_NM, .direction = "up") %>%
  ungroup() %>%
  relocate(ITEM_NM, .after = sec_id) %>%
  mutate(ITEM_NM = if_else(is.na(ITEM_NM) & sec_id == "000000000000", "기타비용", ITEM_NM),
         POS_DS_CD = if_else(is.na(POS_DS_CD) & sec_id == "000000000000", "매수", POS_DS_CD)) %>%
  left_join(historical_fund_inform_data %>% rename(pr_date = STD_DT, 순자산총액 = NAST_AMT) %>% select(pr_date, 순자산총액),
            by = join_by(pr_date)) %>%
  group_by(sec_id) %>%
  fill(c(ITEM_NM, POS_DS_CD), .direction = "down") %>%
  ungroup()

cat("\n=== Step3 fill down 후: ACE 2026-03-01~10 ===\n")
print(step3 %>% filter(sec_id == "KR7365780006", pr_date >= as.Date("2026-03-01"), pr_date <= as.Date("2026-03-10")))

dbDisconnect(con_dt); dbDisconnect(con_sol)
