library(DBI)
library(RMariaDB)
library(dplyr)
library(lubridate)
options(digits = 15)

# KR7411060007: 총손익=3774183, 조정평가=2791600817, 종목별수익률=0.001352
# DB return_USDKRW(1/9) = 0.004826

총손익 <- 3774183
조정평가 <- 2791600817
종목별수익률 <- 총손익/조정평가
r_fx <- 0.004825589411278086

r_sec_with_fx <- (1 + 종목별수익률) / (1 + r_fx) - 1
cat("종목별수익률 (원본):", 종목별수익률, "\n")
cat("r_sec (FX adj):", r_sec_with_fx, "\n")
cat("r_fx:", r_fx, "\n")
cat("\n")

# R Excel 결과: KR7411060007 1/9 개별수익률 = 0.001352 (= 원본 수익률)
# → R Excel에서 이 종목은 FX adj 안 한 것
# 가능성: R Excel 생성 시 ECOS 환율 데이터 매칭 실패 → NA → FX adj 스킵

# 확인: R 원본 코드의 FX split 조건
# line 549: if_else(노출통화=="USD", FX_adj, 원본)
# 노출통화 = "USD" (DB 확인)
# → R에서도 FX adj 적용해야 하지만, ECOS API 호출 시 1/9에 해당하는 return이 없었을 수 있음

# ECOS는 영업일만 반환 → pad_by_time(.by="day") → 1/8(수)에 값 존재, 1/9(목) 존재
# → return = 1457.6/1450.6 - 1 = 0.004826
# → 매칭 될 것임

# 다른 가능성: R에서 pr_date 타입과 기준일자 타입 불일치로 join 실패
# pr_date는 Date, ECOS 기준일자도 Date → 정상 매칭

# 결론: R Excel과 Python 모두 FX split 적용시 동일값 산출 가능
# R Excel이 실제로 FX split을 다른 방식으로 적용했을 수 있음
# 또는 R Excel 생성 당시 universe_non_derivative에 KR7411060007의 Currency Exposure가 없었을 수 있음

cat("=== 검증 ===\n")
cat("Python r_sec (FX adj) = -0.003457\n")
cat("R calc r_sec (FX adj) =", r_sec_with_fx, "\n")
cat("R Excel 개별수익률    = 0.001352 (= 원본, FX adj 미적용)\n")
cat("\n=> R Excel은 이 종목에 FX adj를 적용하지 않았음\n")
cat("=> 원인: universe DB 매핑 변경 or R 코드의 조건 차이\n")
