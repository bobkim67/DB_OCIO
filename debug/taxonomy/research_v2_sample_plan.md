# research_v2 Dry Sample 계획

> 상태: 계획 (실행 전). 30~50건 sample 우선, full backtest는 acceptance 후 별 GO.
> 데이터: `market_research/data/naver_research/adapted/2026-05.json` (이미 adapted+salience 부착).
> 출력: `debug/taxonomy/2026-05_research_v2_dry.json` (production write 0).

## 1. sample 크기 / 구성

- **목표 40건** (테마 9종 + desk 보강). 기존 dry(91건)보다 작게 — 수동 전수 검수 가능 규모.
- 분류 단위: 리서치 리포트(title+요약). PDF 문단 세그멘테이션은 후순위(미적용).

### 필수 포함 테마 (워크오더 §10)

| # | 테마 | 키워드(샘플 선정용) | 기대 region / asset |
|---|---|---|---|
| 1 | 한국 반도체/코스피 | 코스피, 삼성전자, 하이닉스, 반도체, 팔천피, 8천피, 국내 마감 | KR / 국내주식 |
| 2 | 미국 AI/빅테크 | 엔비디아, 나스닥, s&p, 미국 증시, AI | US / 해외주식 |
| 3 | 한은/국내금리 | 한국은행, 한은, 금통위, 국고채, 기준금리 | KR / 국내채권 |
| 4 | Fed/미국금리 | fed, 연준, 미국채, ust, 인플레이션, cpi | US / 해외채권 |
| 5 | 환율/달러 | 환율, 원/달러, 달러, fx, dxy | GLOBAL / 환율(FX) |
| 6 | 유가/원자재/금 | 유가, 원유, 에너지, 금, 원자재 | GLOBAL / 원자재금 |
| 7 | 관세/무역 | 관세, 무역, 공급망 | KR/GLOBAL / multi |
| 8 | 크레딧/스프레드 | 크레딧, 스프레드, 위험선호, hy | GLOBAL / 크레딧 |
| 9 | **복합 문단** | Fed+달러+환율 / 반도체+코스피+환율 / 지정학+유가+금 / 관세+주식+물가 | multi-asset |

- 각 테마 3~5건 + 복합 8~10건. 복합은 multi-asset 검증의 핵심이므로 비중↑.
- 팔천피("마침내 팔천피") 케이스 강제 포함 (회귀 핵심).

## 2. 비교 3-way (동일 sample)

| 방식 | primary 산출 | 비고 |
|---|---|---|
| Rule-only | `route_by_region(region, sector)` → `_remap_to_8class` | region은 v2 LLM 출력 재사용(같은 region 입력으로 공정 비교) |
| LLM-only | LLM `primary_asset`/`affected_assets` 직접 (validator만, fallback 없음) | enum invalid는 drop |
| Hybrid | LLM valid 우선 → rule → v1 (§design §5) | conflict trace |

→ 세 방식 각각 검증지표(§3) 산출, 표로 나란히 비교.

## 3. 평가 metric (워크오더 §9)

| metric | 정의 | 산출 |
|---|---|---|
| asset_enum_valid_rate | LLM asset이 8-class 안인 비율 | 자동 |
| region_enum_valid_rate | LLM region이 REGION_SET 안인 비율 | 자동 |
| low_confidence_rate | confidence floor(§6) 미달 비율 | 자동 |
| fallback_rate | LLM 실패→rule/v1로 넘어간 비율 | 자동 |
| UNKNOWN_rate | region/asset UNKNOWN/None 비율 | 자동 |
| **KR_equity_recovery** | 테마1 문단 국내주식 정분류율 (목표 ≥90%) | 수동 라벨 대비 |
| KR_rates_recovery | 테마3 문단 국내채권 정분류율 | 수동 라벨 대비 |
| US_rates_accuracy | 테마4 문단 해외채권 정분류율 | 수동 라벨 대비 |
| cross_asset_accuracy | 테마7/8/9 multi-asset 매핑 정확도 (정답 자산 set 교집합/합집합 Jaccard) | 수동 라벨 대비 |
| consistency_violation_rate | region·sector·asset 명백 충돌 비율 (validator #9) | 자동 trace |
| multi_asset_claim_rate | affected_assets ≥2 비율 | 자동 |

## 4. 수동 검수 방식

- 40건 전수에 대해 검수자가 (region, primary_asset, affected_assets set) 정답 라벨을 CSV로 작성.
- 자동 산출 vs 정답 라벨 diff 표 → 오분류 케이스만 발췌 리뷰.
- 특히: ① 테마1 한국 반도체가 국내주식으로 오는지 ② 복합 문단이 단일 asset으로 축소 안 되는지
  ③ GLOBAL+주식성 sector가 해외로 새는지(§8 None 보정 필요성).

## 5. acceptance (이 dry → backtest 진입 게이트)

- KR_equity_recovery ≥ 90%, KR_rates_recovery ≥ 85%
- asset_enum_valid_rate ≥ 95% (LLM 통제 가능 증거)
- multi_asset_claim_rate: 복합 테마에서 ≥ 60% (single 축소 방지 확인)
- consistency_violation_rate < 15% (높으면 prompt/region 지침 보강)
- 비용: 40건 1 batch(Haiku) ≪ $0.05 — 무시 가능

→ 통과 시 2026-05 full research backtest(§classification_..._v2.md §7) 별 GO.

## 6. 실행 메모 (코드 미작성 — 계획만)

- 드라이버: 기존 `region_sector_dry_classify.py` 복제 → `research_v2_dry_classify.py` (PROMPT=§prompt.md §2, 출력 파서 affected_assets 구조).
- production `news_classifier`/adapter/claim store 미접근. read-only로 adapted/2026-05.json 로드만.
