# 분류 Taxonomy v2 — Region × Sector 2D 분류 (설계)

> 상태: **설계 (DESIGN ONLY)**. production 미수정. 재분류 + backtest 선행 필수.
> 작성: 2026-06-02. 근거: 한국 반도체(코스피 8000) 자산 오분류 진단.

## 0. 한 줄 요지

현재 분류는 **섹터/테마 14토픽만** 있고 **지역(region) 차원이 없다.** 국내/해외 구분이
`TOPIC_ASSET_SENSITIVITY`(US-centric)에 암묵적으로 박혀, **한국 반도체(삼성·하이닉스·KOSPI)가
국내주식이 아니라 미국/해외 자산으로 매핑**된다. **지역을 1차 분류 차원으로 승격**(region → sector)해
`asset = region × sector`로 도출한다.

## 1. 배경 / 증거

- 현재 14 토픽 (전부 섹터/테마, region 無):
  `통화정책 · 금리_채권 · 물가_인플레이션 · 경기_소비 · 유동성_크레딧 · 환율_FX ·
   달러_글로벌유동성 · 에너지_원자재 · 귀금속_금 · 지정학 · 부동산 · 관세_무역 · 크립토 · 테크_AI_반도체`
- `_asset_impact_vector = Σ TOPIC_ASSET_SENSITIVITY[topic] × direction × intensity` (하드코딩 매트릭스).
- **증거 — "국내 주식 마감 시황 - 마침내 팔천피 (5/26)"** (KOSPI 8000 record, sal 0.71):
  - `_classified_topics`: 테크_AI_반도체(+8), 지정학(+6) ← LLM 토픽은 정상.
  - `_asset_impact_vector`: `{해외채권_EM:-0.42, 미국주식_성장:0.36, 원자재_금:0.42, 원자재_원유:0.3}`
    — **국내주식 키 자체가 없음.** argmax=해외채권.
  - 원인: `TOPIC_ASSET_SENSITIVITY['테크_AI_반도체']`가 미국주식_성장/해외 자산엔 매핑하나 **국내주식엔 미매핑** (테크=미국테크 가정).
- 결과: 삼성/하이닉스/KOSPI 기사가 국내주식 버킷에 못 들어가 → asset-stratified 선별·claim에서 국내주식 record 누락.

## 2. 설계 목표 / 원칙

1. **region을 1차 분류 차원으로** (LLM이 의미론적으로 판단; 키워드/숫자 하드코딩 금지).
2. **asset = region × sector** — region이 국내/해외를 가르는 1차 키, sector는 자산 성격(주식/채권/원자재…).
3. **region은 "영향받는 시장"의 지역** (발행 매체 아님). "삼성전자 급등"→KR, "엔비디아"→US, "연준"→US, "한은 금통위"→KR.
4. cross-asset 글로벌 토픽(환율/원자재/금/지정학/달러/크립토)은 **region 무관** — 글로벌 자산에 직접 매핑.
5. OCIO 8자산(국내·해외 × 주식·채권 + 대체·FX·유동성) 체계와 정합.

## 3. Region taxonomy (제안)

| region | 의미 | asset 라우팅 |
|---|---|---|
| `KR` | 한국 | 국내주식 / 국내채권 |
| `US` | 미국 | 해외주식(미국) / 해외채권(UST·IG·HY) |
| `DM_ex` | 선진 ex-US (유럽·일본) | 해외주식 / 해외채권 |
| `CN` | 중국 | 해외주식 / (해외채권) |
| `EM` | 기타 신흥국 | 해외주식(EM) / 해외채권_EM |
| `GLOBAL` | 글로벌/공통 (매크로·원자재·환율 등) | region 무관 자산(환율·원자재금·크레딧 등) |

- 멀티-region 기사: primary region 1개 + 보조 list 허용 (예: "미중 반도체" → US+CN).
- 최소 구현은 **KR / 해외 / GLOBAL 3분류**로도 가능 (국내/해외 핵심만). 세분(US/DM/CN/EM)은 해외주식·EM채권 tilt용 — 단계적 도입.

## 4. asset 도출 재설계 (region × sector)

현 단일 매트릭스(TOPIC_ASSET_SENSITIVITY)를 **2단계**로 분리:

```
(A) SECTOR_NATURE_SENSITIVITY[sector] → region-free "성격 벡터"
     예) 테크_AI_반도체 → {주식: +0.8}
         금리_채권     → {주식: -0.4, 채권: -0.9}
         통화정책      → {주식: -0.5, 채권: -0.7, 환율: ...}
         경기_소비     → {주식: ±, 채권: ...}
         부동산        → {주식(건설/리츠): ...}
     (글로벌 sector: 환율_FX→{환율}, 에너지_원자재→{원자재}, 귀금속_금→{금대체},
      지정학→{원자재금·리스크}, 달러_글로벌유동성→{환율·해외채권}, 크립토→{크립토})

(B) route_by_region(성격벡터, region):
     주식 + KR        → 국내주식
     주식 + US/DM/CN/EM → 해외주식 (EM 이면 신흥 tilt)
     채권 + KR        → 국내채권
     채권 + US/DM     → 해외채권 (US HY/IG sub)
     채권 + EM        → 해외채권_EM
     환율/원자재/금/크립토 → region 무관 (GLOBAL 자산 그대로)
```

→ 테크_AI_반도체 + KR = **국내주식**, + US = **해외주식**. 동일 sector라도 region이 자산을 가름.
→ 매트릭스 크기: 14 sector × 성격(~5) + region 라우팅 규칙(~10) → 현 14×13 단일표보다 **작고 해석가능**.

## 5. 분류 프롬프트 변경 (LLM)

현재: 기사 → topics[] (sector only).
변경: 기사 → **per-topic (region, sector, direction, intensity)**.

```json
"_classified_topics": [
  {"region": "KR", "sector": "테크_AI_반도체", "direction": "positive", "intensity": 8},
  {"region": "GLOBAL", "sector": "지정학", "direction": "positive", "intensity": 6}
]
```
- region enum 명시 + "영향받는 시장 기준" 지침 + GLOBAL 사용 조건(매크로/원자재/환율).
- backward-compat: region 없는 기존 데이터는 `region=UNKNOWN` → 보수적으로 GLOBAL 또는 키워드 fallback(코스피/삼성→KR, 연준→US) 1회 마이그레이션.

## 6. downstream 영향 (광범위)

| 모듈 | 변경 |
|---|---|
| `news_classifier.py` | 프롬프트 region 출력 + `SECTOR_NATURE_SENSITIVITY` + `route_by_region` (TOPIC_ASSET_SENSITIVITY 대체) |
| `wiki/taxonomy.py` | TAXONOMY_SET = sector 유지 + REGION_SET 신설 + validator |
| `core/asset_taxonomy.py` | article_primary_asset 을 (region, sector) 기반으로 (벡터 argmax + region) |
| `core/salience.py` | _asset_impact_vector 소비부 (구조 동일, 값 출처만) |
| claim/wiki/selector | affected_assets/region 반영. balanced_selector adapter region 인지 |

## 7. 재분류 + backtest 계획 (production 전 필수)

- 2026-01~05 **재분류** (LLM, region 추가) — 비용·정확도 추정.
- **region 정확도 검증**: 샘플 N건 수동 라벨 대비 region 정확도 (특히 KR/US 경계).
- **자산 오분류 회복 측정**: "팔천피" 류 한국 반도체 기사 → 국내주식 정분류율 (현 0% → 목표 ≥90%).
- top-50/claim 자산 분포 current vs v2 (국내주식 비중 정상화 확인).
- 회귀: 기존 토픽 분포·salience 안정성 (sector 차원 불변).

| period | KR 주식 정분류율 | top-50 국내주식 비중 (v1→v2) | 자산 커버 | 비용 |
|---|---|---|---|---|

**acceptance**: ①KR 반도체/코스피 기사 국내주식 정분류 ≥90% ②국내주식 비중 정상화 ③기존 sector 분포 회귀 없음 ④비용 수용 범위.

## 8. Phasing

1. **region taxonomy 정의** + `wiki/taxonomy.py` REGION_SET + validator + unit test.
2. **분류 프롬프트 region 출력** (`news_classifier`) — flag 뒤, 소량 sub-smoke.
3. **SECTOR_NATURE_SENSITIVITY + route_by_region** (TOPIC_ASSET_SENSITIVITY 대체) + unit test (테크 KR/US 분기 검증).
4. **재분류 backtest** 2026-01~05 (§7) → acceptance 통과 시만.
5. **마이그레이션**: 기존 분류 데이터 region 부착 (LLM 재분류 or 키워드 fallback).
6. flag OFF→shadow→ON. downstream(claim/wiki/selector) 순차.

## 9. 리스크 / rollback

- **광범위 영향**: 분류는 모든 downstream 입력. 재분류 필요(비용) + 운영 산출물 재생성.
- **region 오판**: LLM이 region 틀릴 수 있음 (글로벌 기사, 다국적 기업). primary region + 보조 list + GLOBAL fallback 으로 완화. 수동 검증 샘플.
- **over-engineering**: 6-region 세분이 과할 수 있음 → **KR/해외/GLOBAL 3분류 MVP**로 시작, 세분은 효과 확인 후.
- rollback: flag OFF → v1 (TOPIC_ASSET_SENSITIVITY) 복귀. region 필드는 optional 이라 기존 데이터 호환.

## 10. 기존 트랙과의 관계

- 이 v2(region×sector)는 **자산 오분류의 근본 해결** — salience 트랙(corroboration/bm_overlap)·selector(balanced)·anchor 위에 있는 **분류 레이어 근본**.
- region 정분류되면: ① 한국 반도체→국내주식 정상화 ② selector 자산 quota가 제대로 작동 ③ "팔천피 record" 가 국내주식 claim 으로 자연 진입 (record-rescue 하드코딩 불요).
- 우선순위: 영향 최대(분류 전체 + 재분류). **MVP(KR/해외/GLOBAL) → backtest → 세분** 단계적 권장.

## 11. 비고 — 한국 반도체 = 전략자산 인식

사용자 관점(반도체가 경기민감재→전략자산 인식변화)은 **region(KR) + sector(테크_AI_반도체)** 조합으로
국내주식에 정상 귀속되면 자연 반영. 현재는 테크=미국 가정으로 한국 반도체의 국내주식 정체성이
소실됨 — region 차원이 이를 복원.
