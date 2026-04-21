library(tidyverse)
rnorm(100) %>% data.frame() %>% writexl::write_xlsx("/home/scip-r/MP_monitoring/03_MP_monitor/test_sh.xlsx")
