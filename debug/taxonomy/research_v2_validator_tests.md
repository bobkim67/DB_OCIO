# research_v2 Validator — Test Plan

> 상태: 계획 (validator prototype 미작성). dry 결과로 floor 확정 후 구현.
> 대상 함수(가칭): `validate_classification_item(item) -> (clean_item, warnings)` + `resolve_assets(item)` (§design §5).
> 기존 자산: claim `validate_claim`(`analyze/claim_extractor.py:~540`)은 그대로 — v2 validator는 분류 단계 전처리.

## 1. validator 책임 (design §4.3)

LLM 출력을 그대로 신뢰하지 않고 enum/floor/구조 정합을 강제. **차단(hard)** vs **경고(soft)** 구분.

## 2. test cases

### A. enum 검증 (hard)

| # | 입력 | 기대 |
|---|---|---|
| A1 | region="KOREA" | region→"UNKNOWN" + warning |
| A2 | region="KR" | 통과 |
| A3 | sector="반도체" (enum 밖) | sectors에서 drop + warning |
| A4 | asset="금대체" (selector명, 8-class 밖) | `_remap_to_8class`로 "원자재금" 교정 후 통과 |
| A5 | asset="크립토" | 8-class 밖 → 항목 제거 + warning (크립토는 자산군 없음) |
| A6 | asset="원자재금" | 통과 |
| A7 | impact="up" | "unknown"으로 강등 |

### B. confidence floor (hard, §6 초안값)

| # | 입력 | 기대 |
|---|---|---|
| B1 | asset confidence=0.55 (<0.60) | 해당 asset 제거 |
| B2 | asset confidence=0.62 | 유지 |
| B3 | primary confidence=0.65 (<0.70) | primary 자격 박탈 → 차순위 재지정 or None |
| B4 | region_confidence=0.5 | region→UNKNOWN |
| B5 | sector_confidence=0.5 | sectors에서 해당 sector drop |

### C. 구조 정합 (hard)

| # | 입력 | 기대 |
|---|---|---|
| C1 | primary_asset="해외채권"인데 affected_assets에 해외채권 없음 | confidence 최고 asset으로 primary 재지정 |
| C2 | role=primary가 0개 | confidence 최고에 primary 부여 |
| C3 | role=primary가 2개 | 1개만 유지 (confidence 최고), 나머지→secondary |
| C4 | affected_assets 4개 | confidence desc로 상위 3개 trim |
| C5 | affected_assets=[] (순수 종목 리포트) | 통과 (빈 배열 허용), primary_asset=None |

### D. consistency (soft, 차단 안 함)

| # | 입력 | 기대 |
|---|---|---|
| D1 | region=KR, sector=테크, primary=해외주식 | trace `consistency_warning="rule_conflict"` (제거 X) |
| D2 | region=US, sector=통화정책, primary=해외채권 | 충돌 없음, warning 없음 |
| D3 | region=GLOBAL, sector=지정학, affected=[원자재금, 환율(FX)] | 충돌 없음 (cross-asset 정상) |

### E. fallback priority (resolve_assets, §5)

| # | 입력 상태 | 기대 route_source / final |
|---|---|---|
| E1 | LLM affected+primary valid | "llm" / LLM primary |
| E2 | LLM 비어있음, region=KR·sector=테크 | "rule" / 국내주식 (route_by_region→remap) |
| E3 | LLM 비어있음, region=UNKNOWN·sector=테크 | route_by_region→None → "v1" (article_primary_asset) or "none" |
| E4 | region=GLOBAL·sector=금리_채권, LLM 없음 | (§8 보정 전) "rule"/해외채권 — ★dry에서 None화 검토 표기 |
| E5 | LLM primary=국내주식 vs rule=해외주식 | "llm"/국내주식 + consistency_warning="rule_conflict" |

### F. remap (`_remap_to_8class`)

| 입력(selector명) | 출력(8-class) |
|---|---|
| 환율 | 환율(FX) |
| 금대체 | 원자재금 |
| 원자재에너지 | 원자재금 |
| 크립토 | None |
| 국내주식 | 국내주식 (동일) |
| 현금성 | 현금성 |
| 크레딧 | 크레딧 |

### G. 회귀 (기존 계약 불변)

| # | 검증 | 기대 |
|---|---|---|
| G1 | 기존 claim(affected_assets=[{asset_class,direction}], confidence/role 없음) validate_claim | 여전히 valid (confidence/role optional) |
| G2 | primary_asset/regions/sectors 없는 claim | valid (OPTIONAL_FIELDS) |
| G3 | `claim_primary_asset` 기존 동작 (affected_assets[0]) | 불변 |
| G4 | `route_by_region`/`article_primary_asset_v2` (step1-3 test) | 12 test 회귀 PASS |

## 3. 단위테스트 파일 (구현 시)

- `market_research/tests/test_research_v2_validator.py` — A~F (validator/resolve/remap)
- 기존 `test_taxonomy_v2_region.py` (route_by_region/article_primary_asset_v2) 유지 + G4 회귀
- `test_claim_extractor_schema.py`에 G1~G3 추가 (confidence/role/primary optional 호환)

## 4. floor 캘리브레이션 의존성

§6 floor(0.60/0.70)는 **초안** — dry `low_confidence_rate`·`fallback_rate` 보고 조정. floor 높으면
fallback 폭증(rule/v1 의존↑), 낮으면 환각 통과↑. test의 임계값은 floor 확정 후 fixture 갱신.
