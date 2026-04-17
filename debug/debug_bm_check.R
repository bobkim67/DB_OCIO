library(DBI); library(RMariaDB); library(dplyr); library(tidyr)
con <- dbConnect(RMariaDB::MariaDB(), username='solution', password='Solution123!', dbname='SCIP', host='192.168.195.55')

bm_components <- list(
  list(name="KOSPI", ds=253, dseries=9, weight=0.216, cl="국내주식"),
  list(name="MSCI_ACWI", ds=35, dseries=39, weight=0.504, cl="해외주식"),
  list(name="BBG_AGG", ds=256, dseries=9, weight=0.10, cl="해외채권"),
  list(name="KIS_total", ds=279, dseries=40, weight=0.10, cl="국내채권"),
  list(name="KIS_Call", ds=288, dseries=40, weight=0.08, cl="유동성")
)

bm_daily_list <- list()
for(comp in bm_components) {
  q <- sprintf("SELECT DATE(timestamp_observation) as dt, data FROM back_datapoint WHERE dataset_id=%d AND dataseries_id=%d AND timestamp_observation >= '2025-12-01' ORDER BY timestamp_observation", comp$ds, comp$dseries)
  df <- dbGetQuery(con, q)
  df$dt <- as.Date(df$dt)
  df$value <- sapply(df$data, function(b) as.numeric(rawToChar(b)))
  df <- df %>% select(dt, value) %>% distinct(dt, .keep_all=TRUE) %>% arrange(dt) %>%
    mutate(daily_ret = value / lag(value) - 1) %>% filter(!is.na(daily_ret))
  cat(comp$name, "(", comp$cl, "):", nrow(df), "rows, NAs:", sum(is.na(df$daily_ret)), "\n")
  bm_daily_list[[comp$name]] <- df %>% select(dt, daily_ret) %>%
    mutate(cl = comp$cl, weight = comp$weight)
}

all_bm <- bind_rows(bm_daily_list) %>%
  group_by(dt, cl) %>%
  summarise(bm_r = sum(daily_ret * weight) / sum(weight), .groups="drop") %>%
  pivot_wider(id_cols = dt, names_from = cl, values_from = bm_r)

cat("\nall_bm colnames:", paste(names(all_bm), collapse=", "), "\n")
cat("all_bm rows:", nrow(all_bm), "\n")
cat("NAs per col:\n")
print(sapply(all_bm, function(x) sum(is.na(x))))
cat("\nSample:\n")
print(head(all_bm, 3))
dbDisconnect(con)
