# ============================================================
# Brinson 3-Factor 비교: R vs Python (08K88, 2026-01-01~03-12)
# Python 동일 데이터 소스 + R 보정인자1 로직
# DB credentials: 기존 debug_pa_full.R과 동일 (내부망 전용)
# ============================================================

library(DBI)
library(RMariaDB)
library(dplyr)
library(tidyr)
library(lubridate)

options(digits = 15)

fund_cd <- "08K88"
from <- as.Date("2026-01-01")
to   <- as.Date("2026-03-12")

# ── DB 접속 (내부망, debug_pa_full.R 동일) ──
con_dt   <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!',
                      dbname='dt', host='192.168.195.55')
con_scip <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!',
                      dbname='SCIP', host='192.168.195.55')
con_sol  <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!',
                      dbname='solution', host='192.168.195.55')

# ── 1. 모펀드 확인 ──
class_M_fund <- dbGetQuery(con_dt, sprintf(
  "SELECT CLSS_MTFD_CD FROM DWPI10011 WHERE FUND_CD='%s' AND IMC_CD='003228' LIMIT 1", fund_cd
))$CLSS_MTFD_CD
if(is.null(class_M_fund) || is.na(class_M_fund)) class_M_fund <- fund_cd
cat("모펀드:", class_M_fund, "\n")

# ── 2. MA000410 로드 ──
pa_raw <- dbGetQuery(con_dt, sprintf(
  "SELECT pr_date, sec_id, asset_gb, pl_gb, crrncy_cd, os_gb, position_gb,
          modify_unav_chg, val, std_val
   FROM MA000410
   WHERE fund_id='%s' AND pr_date>='%s' AND pr_date<='%s'",
  class_M_fund, format(from - days(10), "%Y%m%d"), format(to, "%Y%m%d")
)) %>% mutate(pr_date = ymd(pr_date))
cat("MA410:", nrow(pa_raw), "rows,", n_distinct(pa_raw$pr_date), "days\n")

# ── 3. DWPM10510 (기준가, 순자산) ──
nav_df <- dbGetQuery(con_dt, sprintf(
  "SELECT STD_DT, MOD_STPR, NAST_AMT FROM DWPM10510
   WHERE FUND_CD='%s' AND IMC_CD='003228'
   AND STD_DT >= '%s' AND STD_DT <= '%s'",
  class_M_fund, format(from - days(30), "%Y%m%d"), format(to, "%Y%m%d")
)) %>% mutate(STD_DT = ymd(STD_DT)) %>% arrange(STD_DT)
cat("NAV:", nrow(nav_df), "rows\n")

# ── 4. 자산분류 (solution.universe_non_derivative) ──
universe <- dbGetQuery(con_sol,
  "SELECT ISIN, classification FROM universe_non_derivative WHERE classification_method='방법3'")

holdings <- dbGetQuery(con_dt, sprintf(
  "SELECT ITEM_CD, ITEM_NM, AST_CLSF_CD_NM FROM DWPM10530
   WHERE FUND_CD='%s' AND IMC_CD='003228'
   AND STD_DT = (SELECT MAX(STD_DT) FROM DWPM10530 WHERE FUND_CD='%s' AND IMC_CD='003228' AND STD_DT<='%s')
   GROUP BY ITEM_CD, ITEM_NM, AST_CLSF_CD_NM",
  class_M_fund, class_M_fund, format(to, "%Y%m%d")
))

classify_item <- function(item_cd, item_nm, ast_nm) {
  u <- universe %>% filter(ISIN == item_cd)
  if(nrow(u) > 0) return(u$classification[1])
  if(grepl("^0322800", item_cd)) return("모펀드")
  nm <- paste0(ast_nm, item_nm)
  if(grepl("주식|지수|ETF|ETP", nm) & !grepl("채권", nm)) {
    if(grepl("^KR", item_cd)) return("국내주식") else return("해외주식")
  }
  if(grepl("채권|국채|회사채|금융채", nm)) {
    if(grepl("^KR", item_cd)) return("국내채권") else return("해외채권")
  }
  if(grepl("금현물|리츠|부동산|인프라", nm)) return("대체투자")
  if(grepl("달러|NDF|통화|선물환|USD.*DEPOSIT", nm, ignore.case=TRUE)) return("FX")
  return("유동성")
}

item_class_map <- holdings %>%
  rowwise() %>%
  mutate(ac = classify_item(ITEM_CD, ITEM_NM, AST_CLSF_CD_NM)) %>%
  ungroup() %>%
  select(ITEM_CD, ac)

pa <- pa_raw %>%
  left_join(item_class_map, by = c("sec_id" = "ITEM_CD")) %>%
  mutate(ac = if_else(is.na(ac), "유동성", ac))

asset_classes <- c("국내주식","해외주식","국내채권","해외채권","대체투자","FX","모펀드","유동성")

# ── 6. 일별 AP 자산군별 비중/수익률 ──
dates <- sort(unique(pa$pr_date))
dates <- dates[dates >= from]

daily_ap <- list()
sec_val_prev <- list()

for(idx in seq_along(dates)) {
  dt <- dates[idx]
  day <- pa %>% filter(pr_date == dt)
  prev_nav <- nav_df %>% filter(STD_DT < dt) %>% tail(1)
  if(nrow(prev_nav) == 0) next
  mod_stpr_prev <- prev_nav$MOD_STPR

  sec_agg <- day %>%
    group_by(sec_id, ac) %>%
    summarise(modify_sum = sum(modify_unav_chg, na.rm=TRUE),
              val_last = last(val), .groups="drop")
  sec_agg$val_t1 <- sapply(sec_agg$sec_id, function(s) {
    v <- sec_val_prev[[s]]; if(is.null(v)) 0 else v
  })

  class_agg <- sec_agg %>%
    group_by(ac) %>%
    summarise(modify = sum(modify_sum), val_t1 = sum(val_t1), .groups="drop")

  total_val_t1 <- sum(class_agg$val_t1)
  if(total_val_t1 == 0) total_val_t1 <- 1

  port_ret <- sum(day$modify_unav_chg, na.rm=TRUE) / mod_stpr_prev
  rec <- list(pr_date = dt, port_ret = port_ret)
  for(ac_name in asset_classes) {
    row <- class_agg %>% filter(ac == ac_name)
    w <- if(nrow(row)>0) row$val_t1 / total_val_t1 else 0
    r <- if(nrow(row)>0 && row$val_t1 > 0) row$modify / row$val_t1 else 0
    rec[[paste0(ac_name, "_w")]] <- w
    rec[[paste0(ac_name, "_r")]] <- r
  }
  daily_ap[[length(daily_ap)+1]] <- as.data.frame(rec, check.names=FALSE)
  for(i in seq_len(nrow(sec_agg))) {
    sid <- sec_agg$sec_id[i]; v <- sec_agg$val_last[i]
    if(!is.na(v)) sec_val_prev[[sid]] <- v
  }
}

daily_ap_df <- bind_rows(daily_ap)
cat("AP 일별:", nrow(daily_ap_df), "일\n")

# ── 7. BM 일별 수익률 (SCIP, Python 동일 컴포넌트) ──
bm_components <- list(
  list(name="KOSPI", ds=253, dseries=9, weight=0.216, cl="국내주식"),
  list(name="MSCI_ACWI", ds=35, dseries=39, weight=0.504, cl="해외주식"),
  list(name="BBG_AGG", ds=256, dseries=9, weight=0.10, cl="해외채권"),
  list(name="KIS_total", ds=279, dseries=40, weight=0.10, cl="국내채권"),
  list(name="KIS_Call", ds=288, dseries=40, weight=0.08, cl="유동성")
)

bm_weights_vec <- setNames(rep(0, length(asset_classes)), asset_classes)
for(comp in bm_components) bm_weights_vec[comp$cl] <- bm_weights_vec[comp$cl] + comp$weight * 100

load_scip_daily <- function(dataset_id, dataseries_id) {
  q <- sprintf(
    "SELECT DATE(timestamp_observation) as dt, data FROM back_datapoint
     WHERE dataset_id=%d AND dataseries_id=%d AND timestamp_observation >= '2025-12-01'
     ORDER BY timestamp_observation", dataset_id, dataseries_id)
  df <- dbGetQuery(con_scip, q)
  df$dt <- as.Date(df$dt)
  df$value <- sapply(df$data, function(b) {
    s <- rawToChar(b); s <- trimws(s)
    if(grepl("^\\{", s)) {
      j <- jsonlite::fromJSON(s)
      if("KRW" %in% names(j)) return(as.numeric(j$KRW))
      return(as.numeric(j[[1]]))
    }
    return(as.numeric(gsub(",","",gsub('"','',s))))
  })
  df %>% select(dt, value) %>% distinct(dt, .keep_all=TRUE) %>% arrange(dt) %>%
    mutate(daily_ret = value / lag(value) - 1) %>% filter(!is.na(daily_ret))
}

bm_daily_list <- list()
for(comp in bm_components) {
  df <- load_scip_daily(comp$ds, comp$dseries)
  bm_daily_list[[comp$name]] <- df %>% select(dt, daily_ret) %>%
    mutate(cl = comp$cl, weight = comp$weight)
}

all_bm <- bind_rows(bm_daily_list) %>%
  group_by(dt, cl) %>%
  summarise(bm_r = sum(daily_ret * weight) / sum(weight), .groups="drop") %>%
  pivot_wider(id_cols = dt, names_from = cl, values_from = bm_r)

# NA 제거: 모든 BM 자산군이 값 있는 날짜만 사용
all_bm <- all_bm %>% filter(complete.cases(.))
common_dates <- intersect(daily_ap_df$pr_date, all_bm$dt)
common_dates <- sort(as.Date(common_dates, origin="1970-01-01"))
daily_ap_df <- daily_ap_df %>% filter(pr_date %in% common_dates) %>% arrange(pr_date)
all_bm <- all_bm %>% filter(dt %in% common_dates) %>% arrange(dt)
cat("공통 날짜 (NA제거):", length(common_dates), "일\n")

# ── 8. BM 복합 + 보정인자1 + Brinson ──
bm_composite <- rep(0, nrow(all_bm))
for(ac_name in asset_classes) {
  w <- bm_weights_vec[ac_name] / 100
  if(ac_name %in% names(all_bm)) bm_composite <- bm_composite + all_bm[[ac_name]] * w
}

ap_cum <- cumprod(1 + daily_ap_df$port_ret)
bm_cum <- cumprod(1 + bm_composite)
rel_cum <- ap_cum / bm_cum - 1
prev_rel <- c(0, rel_cum[-length(rel_cum)])
rel_daily <- (1 + rel_cum) / (1 + prev_rel) - 1
simple_daily <- daily_ap_df$port_ret - bm_composite
correction <- ifelse(abs(simple_daily) > 1e-15, rel_daily / simple_daily, 0)

brinson_list <- list()
for(i in seq_len(nrow(daily_ap_df))) {
  cf <- correction[i]
  for(ac_name in asset_classes) {
    ap_w <- daily_ap_df[[paste0(ac_name, "_w")]][i]
    ap_r <- daily_ap_df[[paste0(ac_name, "_r")]][i]
    bm_w <- bm_weights_vec[ac_name] / 100
    bm_r <- if(ac_name %in% names(all_bm)) all_bm[[ac_name]][i] else 0
    brinson_list[[length(brinson_list)+1]] <- data.frame(
      ac = ac_name,
      alloc = (ap_w - bm_w) * bm_r * cf,
      sel = bm_w * (ap_r - bm_r) * cf,
      crs = (ap_w - bm_w) * (ap_r - bm_r) * cf,
      alloc_raw = (ap_w - bm_w) * bm_r,
      sel_raw = bm_w * (ap_r - bm_r),
      crs_raw = (ap_w - bm_w) * (ap_r - bm_r)
    )
  }
}
brinson_df <- bind_rows(brinson_list)

# ── 결과 출력 ──
pb <- brinson_df %>% group_by(ac) %>%
  summarise(A=sum(alloc)*100, S=sum(sel)*100, C=sum(crs)*100,
            A_raw=sum(alloc_raw)*100, S_raw=sum(sel_raw)*100, C_raw=sum(crs_raw)*100, .groups="drop")

pap <- (tail(ap_cum,1)-1)*100; pbm <- (tail(bm_cum,1)-1)*100
rel_ex <- tail(rel_cum,1)*100; arith_ex <- pap - pbm
ta <- sum(pb$A); ts <- sum(pb$S); tc <- sum(pb$C); bs <- ta+ts+tc; res <- rel_ex - bs
ta_r <- sum(pb$A_raw); ts_r <- sum(pb$S_raw); tc_r <- sum(pb$C_raw); bs_r <- ta_r+ts_r+tc_r; res_r <- arith_ex - bs_r

cat("\n========== R Brinson (08K88, 01/01~03/12) ==========\n")
cat(sprintf("포트: %.4f%%, BM: %.4f%%\n", pap, pbm))
cat(sprintf("초과(산술): %.4f%%, 초과(상대): %.4f%%\n", arith_ex, rel_ex))
cat("\n--- 보정전 ---\n")
cat(sprintf("A: %.4f, S: %.4f, C: %.4f, 합: %.4f, Res: %.4f\n", ta_r, ts_r, tc_r, bs_r, res_r))
cat("\n--- 보정후 ---\n")
cat(sprintf("A: %.4f, S: %.4f, C: %.4f, 합: %.4f, Res: %.4f\n", ta, ts, tc, bs, res))
cat(sprintf("검증: %.6f = %.6f\n", bs+res, rel_ex))

cat("\n자산군별:\n")
print(pb %>% select(ac, A, S, C))

write.csv(pb, "debug/debug_brinson_R_result.csv", row.names=FALSE)
write.csv(data.frame(dt=common_dates, ap=daily_ap_df$port_ret, bm=bm_composite,
  ex_simple=simple_daily, ex_rel=rel_daily, cf=correction),
  "debug/debug_brinson_R_daily.csv", row.names=FALSE)
cat("\n[저장] debug_brinson_R_result.csv, debug_brinson_R_daily.csv\n")

dbDisconnect(con_dt); dbDisconnect(con_scip); dbDisconnect(con_sol)
