# Salience 점수체계 보강 설계 — corroboration + bm_overlap (별도 트랙)

> 상태: **설계 (DESIGN ONLY)**. production 미수정. backtest 선행 필수.
> 작성: 2026-06-01. 근거: 2026-05 코스피 8000 under-scoring 진단.

## 0. 한 줄 요지

salience 공식이 **"급변·집중보도" 신호엔 민감하고 "광범위하지만 분산 보도된 완만한 신고가"엔 둔감**하다. corroboration(동일사건 보도밀도)과 bm_overlap(BM 이벤트)을 보강해, 코스피 사상최고 같은 **구조적 긍정 마일스톤이 점수에서 저평가되지 않게** 한다. 단, **dominance(도배) 제어는 salience가 아니라 selector의 몫** — 이 원칙을 어기면 역효과(아래 §3).

## 1. 배경 / 증거 (2026-05 실측)

salience = `0.30·source_quality + 0.25·intensity + 0.25·corroboration + 0.20·bm_overlap`

| 항목 | 7천 claim 기사 (연합뉴스 5/06) | 8000 record 기사 (조선비즈 5/26) | 차이 |
|---|---|---|---|
| source_quality | 0.30 (TIER1) | 0.21 (TIER2) | -0.09 |
| intensity | 0.20 (=8) | 0.20 (=8) | **0** |
| **corroboration** | 0.25 (evt_src=6) | **0.05 (evt_src=1)** | **-0.20** |
| **bm_overlap** | 0.20 (5/06 anomaly) | **0.00 (5/26 비anomaly)** | **-0.20** |
| **합계** | **0.95** | **0.46** | -0.49 |

→ intensity 동일. **corroboration(-0.20) + bm_overlap(-0.20)**이 결정적. 8000 record(82건 보도)가 0.46/rank ~336 → claim 추출 pool 미진입 → "8000 claim" 자체가 생성 불가.

## 2. 근본 원인

### 2-A. corroboration — 동일사건 대량보도가 클러스터링에서 분산
- `corroboration = min(event_source_count / 5, 1.0)`. event_source_count 는 `core/dedupe.py::cluster_events`(TOPIC_NEIGHBORS 교차)가 산출.
- 5/26 코스피 8000: 82건 보도인데 **evt_src=1~2** (각자 별개 이벤트). 원인 후보: ① 5/26 분류율 낮음(111/201) → 미분류는 클러스터 키 부족 ② 코스피 기사가 경기_소비/테크_AI_반도체 등 여러 토픽으로 흩어져 TOPIC_NEIGHBORS 교차 미흡 ③ headline 유사도 미사용.
- 5/06 7천: evt_src=6 정상 클러스터.

### 2-B. bm_overlap — 5일 z-score top-7 이 완만한 record 를 못 잡음
- `bm_overlap = 1.0 if date in bm_anomaly_dates`. anomaly = 6개 BM(S&P/KOSPI/Gold/DXY/USDKRW/미국채) **5일수익률 z>1.5 상위 7일**.
- 5월 anomaly = `5/06,07,08,11,12,27,28`. **5/26(코스피 record) 없음.** 이유: ① 완만한 우상향 랠리 → 5일 z 낮음 ② 상위 7일 cap이 변동성 큰 이란·초반일에 점유.
- 즉 **"신고가"라는 level milestone 자체를 신호로 안 봄** (변동성만 봄).

## 3. ★설계 원칙 (직전 시도 backfire 교훈)

2026-06-01 1차 시도(`debug/.../salience_revision_backtest.py`): corroboration=max(evt_src, **same-day-same-asset density**), bm_overlap=max(anomaly, **top-mover-asset**, milestone). **결과: 역효과** — 지정학 dominant share 48%→82%, asset 7/7→3/7. 8000은 0.46→0.86(부스트됐으나 여전히 7천 < 0.95).

**왜 역효과**: density·mover 부스트가 **이미 지배적인 이란 클러스터를 더 키움**(이란 5/12 대량보도 + 이란 기사가 mover 자산=해외주식/원자재). 즉 "importance"가 아니라 "volume/변동성"을 보상.

**도출 원칙:**
1. **importance ≠ volume/변동성.** 보강 신호는 **under-scoring된 특정 사건만 타겟**해야 하고, 광범위 부스트(모든 mover-asset, 모든 busy-day)는 금지.
2. **dominance(도배) 제어는 selector(asset quota + topic CAP)의 몫.** salience로 dominance를 잡으려 하지 말 것. salience는 순수 "중요도" 점수로.
3. corroboration 보강은 **cap(=1.0) 유지** — 이미 클러스터된 대형사건(이란 evt_src=5~6=1.0)을 더 키우지 않고, **잘못 분산된 사건(코스피 evt_src=1)을 parity(1.0)까지** 끌어올리는 방향.
4. bm_overlap 보강은 **날짜·자산 특정**(record일에 해당 자산 기사만), **자산 전체 부스트 금지**.

## 4. 설계안

### A. corroboration 보강 — clustering 개선 (주) + same-event density (보조)

**A1 (주): event clustering 개선 (`core/dedupe.py::cluster_events`)**
- 동일사건 판정에 **headline 핵심 키워드/엔티티 + 동일일자** 병합 추가 (현 TOPIC_NEIGHBORS 교차에 더해).
- 효과: 5/26 코스피 8000 82건 → 하나의 event_group (evt_src≥5) → corroboration=1.0. **이란(이미 1.0)은 불변.** parity 도달, over-amplify 없음.
- 리스크: 과병합(서로 다른 사건이 같은 키워드로 묶임). → 같은 날 + 같은 primary asset + headline 토큰 overlap 임계(예: ≥2 공통 핵심명사) 동시 충족 시만 병합.

**A2 (보조, A1 미흡 시): same-day-same-event density floor**
- `corroboration = max(evt_src/5, same_event_density)` where same_event_density = `min(동일일자·동일 primary_asset·headline 핵심키워드 공유 기사수 / DENSITY_FULL, 1.0)`.
- ★1차 backfire 회피: density 키를 **same-asset(너무 넓음)이 아니라 same-asset+headline핵심키워드 공유**로 좁힘. 이란처럼 이미 evt_src 높은 건 max로 변화 없음. 코스피처럼 분산된 것만 회복.
- DENSITY_FULL: 캘리브레이션(예: 15~20).

### B. bm_overlap 보강 — record-high date (주) + 월간 |return| (보조)

**B1 (주): 신고가/신저가 date 신호 (`core/salience.py` + indicators.csv)**
- 각 BM 시계열에서 **해당 기간(월) 내 최고/최저를 경신한 날짜**를 record_dates 로 추출(자산별).
- `bm_overlap = max(date_in_5d_anomaly, article_date_is_record_for_its_asset)`.
- ★날짜·자산 특정: 5/26(코스피 period-high date) + 코스피 기사 → bm_overlap=1. **모든 국내주식 기사가 아니라 record일 기사만.** 이란(해외주식/원자재)엔 영향 없음.
- 완만한 랠리도 "신고가 경신일"이면 잡힘 (변동성 무관).

**B2 (보조): 월간 |return| 상위 자산 — 단, 약한 가중**
- 1차 backfire의 주범. **채택 신중.** 쓰더라도 bm_overlap 만점(1.0)이 아니라 **0.3~0.5 부분 가중**으로, record date(B1)·anomaly가 주 신호. 또는 B2 제외하고 B1만으로 backtest 후 판단.

### C. dominance 는 건드리지 않음
- §3-2 원칙. salience 보강은 점수만 올바르게. **도배 방지는 기존 selector(balanced_selector: 자산 quota + topic CAP)가 담당** (이미 구현·커밋 `08c4736`).

## 5. backfire 회피 검증 논리

| 신호 | 이란(이미 고salience) 영향 | 코스피 8000(under-scored) 영향 |
|---|---|---|
| A1 clustering | 불변 (이미 evt_src≥5=cap) | evt_src 1→≥5, corroboration 0.05→0.25 ✅ |
| A2 density(좁힌 키) | 불변 (max, 이미 높음) | 회복 ✅ |
| B1 record-date | 불변 (record일 아님) | 5/26 record일 → bm 0→0.20 ✅ |
| B2 월간 mover | ⚠️ 이란자산도 영향 → **약가중/제외** | 보조 |

→ A1+B1 조합은 **코스피만 parity로 올리고 이란은 불변** → dominance 악화 없음. (1차 backfire는 A2-넓은키 + B2를 주신호로 써서 발생.)

## 6. backtest 계획 (production 전 필수)

대상: **2026-01 ~ 2026-05** (dry, LLM 0, 운영 무변경).

| period | current top topics | revised top topics | asset coverage(raw50) | dominant share(raw50) | 코스피류 record rank | false-positive(intensity<3 비율) |
|---|---|---|---|---|---|---|

**acceptance 기준:**
1. dominant share(raw top-50) **악화 없음** (1차처럼 82%로 튀면 reject).
2. under-scored record(코스피 8000 등)가 **해당 자산 내 상위로 진입** (asset-stratified top-2 안).
3. false-positive(저-intensity 부스트) ≤ 현행 수준.
4. 2026-01~04 회귀: 기존 상위 사건 순위 급변동 없음(안정성).
- 미달 시 파라미터(DENSITY_FULL, 키워드 임계, B2 가중) 재조정 또는 해당 신호 폐기.

## 7. 구현 phasing

1. **dedupe clustering (A1)** — `core/dedupe.py::cluster_events` 병합 규칙 + unit test(과병합 가드). flag/파라미터화.
2. **salience bm_overlap (B1)** — `core/salience.py::compute_event_salience` + record_dates 헬퍼(indicators.csv, 기 수정된 anchor 로직 재사용). `compute_salience_batch`에 record_dates 주입.
3. **backtest harness** — §6 표 산출. (`debug/.../salience_redesign_backtest.py`)
4. acceptance 통과 시에만 production. **flag(기본 OFF) → 1개월 shadow 후 ON** 권장.
5. 회귀: `market_research/tests` 전체 + corroboration/bm_overlap unit + invariant(운영 salience 변경은 모든 downstream 재계산 유발 → claim/wiki/pack 영향 광범위).

## 8. 리스크 / rollback

- **광범위 영향**: salience는 pool/event/claim/pack 모든 downstream의 입력. 변경 시 기존 운영 산출물(claim store, wiki) 재생성 필요 가능 → 별도 운영 사이클로.
- **과병합(A1)**: 서로 다른 사건 병합 → corroboration 허위 상승. unit test + 임계로 가드.
- **record-date 오탐(B1)**: 데이터 결손(주말/공백)으로 잘못된 record일. anchor의 last-valid 로직 재사용으로 완화.
- rollback: flag OFF 즉시 복귀. dedupe 변경은 commit revert.

## 9. 비고 — 이번 5월 교정과의 관계

- 이번 5월 report는 **selector(balanced)로 balance 달성**, "8000 정량"은 미반영(claim 텍스트 7,300). 본 트랙은 그 잔여(record under-scoring)의 root fix.
- 본 트랙 적용 후엔 8000 기사가 pool 진입 → claim 추출이 8000 claim 생성 → 자연 반영. **selector(완료)와 salience 보강(본 트랙)이 상보적.**
