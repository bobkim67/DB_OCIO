# research_v2 FULL backtest — 2026-05 (전수)

- 분류: 1142건 (keyword 샘플링 없음). LLM region v2 prompt + validator + hybrid.
- production write 0 (adapted 미수정). flag OFF 유지.

## 1. validator / 메커니즘

| check | value |
| --- | ---: |
| asset_enum_valid_rate | 1142/1142 (100.0%) |
| region_enum_valid_rate | 1142/1142 (100.0%) |
| fallback_rate | 70/1142 (6.1%) |
| unknown_rate (hybrid None) | 13/1142 (1.1%) |
| multi_asset_rate | 374/1142 (32.7%) |
| consistency_violation_rate | 236/1142 (20.7%) |

## 2. 자산 분포 정상화 (v1 → v2 hybrid)

| asset | v1 count | v1 % | v2 count | v2 % | Δ%p |
| --- | ---: | ---: | ---: | ---: | ---: |
| 국내주식 | 225 | 22.0% | 581 | 51.5% | +29.5 |
| 해외주식 | 276 | 27.0% | 281 | 24.9% | -2.1 |
| 원자재금 | 77 | 7.5% | 97 | 8.6% | +1.1 |
| 국내채권 | 91 | 8.9% | 67 | 5.9% | -3.0 |
| 해외채권 | 330 | 32.2% | 51 | 4.5% | -27.7 |
| 환율(FX) | 25 | 2.4% | 30 | 2.7% | +0.2 |
| 크레딧 | 0 | 0.0% | 13 | 1.2% | +1.2 |
| 현금성 | 0 | 0.0% | 9 | 0.8% | +0.8 |

## 3. KR-equity recovery (title KR주식 keyword reference)

- reference set (코스피/삼성/하이닉스/반도체/마감/팔천피 등): 123건
- v1 국내주식 분류: 70/123 (56.9%)
- **v2 국내주식 분류: 102/123 (82.9%)**

## 4. region 분포

| region | count | % |
| --- | ---: | ---: |
| KR | 648 | 56.7% |
| US | 222 | 19.4% |
| GLOBAL | 203 | 17.8% |
| NON_US_OVERSEAS | 57 | 5.0% |
| UNKNOWN | 12 | 1.1% |

## 5. acceptance 판정 (자동 proxy)

| 기준 | 목표 | 실측 | 판정 |
| --- | --- | --- | --- |
| KR 주식 국내주식 정분류 | ≥90% | 82.9% | CHECK |
| 국내주식 비중 정상화 (v1→v2) | 상승 | 22.0%→51.5% | PASS |
| asset enum valid | ≥95% | 100.0% | PASS |
| fallback 과도 아님 | <30% | 6.1% | PASS |