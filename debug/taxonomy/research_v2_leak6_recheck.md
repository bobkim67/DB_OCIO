# 마감시황 leak 6건 recheck (rule 7 region-pinning patch)

- leak 6건 재분류 (full backtest 재실행 X). adapted read-only.

## 결과

| id | title | before_primary | after_primary | affected_assets_after | pass |
| --- | --- | --- | --- | --- | --- |
| 0 | 국내주식 마감 시황 (26.04.30) - Big-Event  | US/해외주식 | KR/국내주식 | 국내주식(prim), 해외주식(seco) | ✅ |
| 1 | 국내주식 마감 시황 (26.05.06) - 온 세상이 전닉이다 | GLOBAL/해외주식 | KR/국내주식 | 국내주식(prim), 해외주식(seco), 원자재금(seco) | ✅ |
| 2 | 국내주식 마감 시황 (26.05.08) - ‘투톱’ 휴식에도  | US/해외주식 | KR/국내주식 | 국내주식(prim), 해외주식(seco) | ✅ |
| 3 | 국내주식 마감 시황 (26.05.15) - 8천피 돌파 후 후 | US/해외주식 | KR/국내주식 | 국내주식(prim), 해외주식(seco) | ✅ |
| 4 | 국내주식 마감 시황 (26.05.18) - 삼성전자에 쏠리는  | GLOBAL/해외주식 | KR/국내주식 | 국내주식(prim), 원자재금(seco) | ✅ |
| 5 | 국내주식 마감 시황 (26.05.28) - 이걸 말아 올린 국 | US/해외주식 | KR/국내주식 | 국내주식(prim), 해외주식(seco), 원자재금(seco) | ✅ |

## 회귀 체크

| 항목 | 결과 |
| --- | --- |
| primary 국내주식 교정 | 6/6 |
| 교정건 driver secondary 유지 (affected≥2) | 6/6 |
| asset enum valid 100% | 6/6 |
| region enum valid 100% | 6/6 |
| fallback (route_source!=llm) | 0/6 |