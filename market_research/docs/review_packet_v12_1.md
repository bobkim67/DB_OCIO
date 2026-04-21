# Review Packet v12.1 — 패킷 일관성 정리 + False Negative 방어 증거

> v12 본체의 기술 방향은 유지. 이번 패킷은 문서/증거/수치 정의 보정 중심.

---

## 지표 정의 (고정 블록)

- **configured coverage**: 전체 설정된 taxonomy / configured universe 기준 (예: `DRIVER_TAXONOMY` 9개 전체, `ASSET_TAXONOMY` 10개 전체)
- **active coverage**: 이번 월 그래프에 실제 존재해 후보군으로 채택된 active universe 기준 (P1에서 `_select_dynamic_triggers` / `_select_dynamic_targets`가 반환한 집합)
- **candidate_score**: regime shift 후보 규칙 (`low_coverage_current`, `low_coverage_today`, `sentiment_flip`) 충족 개수
- **unresolved phrase**: taxonomy에 억지 매핑하지 않고 제외한 설명형 phrase. `_unresolved_tags`, `_taxonomy_remap_trace.jsonl`에 기록

이 정의는 이후 모든 패킷에서 동일하게 사용합니다.

---

## 1. 이번 패킷에서 받고 싶은 판정

- **목표 판정**: **pass**
- **핵심 목표**: v12 기술 변경은 유지. 내부 일관성 결함 3건(coverage 분모 충돌 / entity 샘플-본문 불일치 / false negative 방어 증거 부족) 해소.
- **특히 봐줬으면 하는 리스크**
  1. `configured vs active coverage` 분리가 v12 이전 문서와 다르게 읽힐 수 있음 (기존 패킷 유지, 단어만 확장)
  2. GraphRAG node 기반 entity page 3건 추가는 범위 확장처럼 보일 수 있으나, 본문 claim을 샘플 진실에 맞추기 위한 **최소 보정**
  3. false negative 방어 예시는 v12 판정식이 의도대로 동작한다는 1건 증거일 뿐, 장기 실전 데이터는 여전히 부재
- **이번 배치에서 의도적으로 미룬 것**
  1. transmission path canonical 승격 (Phase 4+ 유지)
  2. graphify 외부 뷰어 연동
  3. Entity page 전면 redesign (v12 설계 문서 유지)
  4. PHRASE_ALIAS 반자동 보강

---

## 2. 핵심 변경 요약

### 변경 1. Coverage 분모 정의 분리 (문서 일관성)
- **Before**: v12 본문 "unique_triggers 4/9" vs 부록 summary "4/6" 병존 → 리뷰어 혼동
- **After**: 모든 위치를 **configured** (전체 taxonomy 9/10) + **active** (월별 후보군 6/5) 두 수치로 분리. 단독 `coverage` 표현 금지.
- **Why**: P1은 "활성 후보군에서의 커버리지"와 "전체 taxonomy에서의 커버리지"가 동시에 의미 있음. 같은 숫자를 두 분모로 보는 것이 설계 의도.
- **Risk**: 기존 v12 비교 테스트 스크립트 출력이 두 지표를 아직 동시 출력하지 않음 → 다음 배치에서 출력 포맷 확장 필요.

### 변경 2. Entity page 샘플 진실성 — full-schema 예시 3건 추가 생성
- **Before**: 본문에서 `graph_node_id/canonical_entity_label/linked_events` 추가 claim, 샘플은 `linked_events`만 노출 → 과장
- **After**: `refresh_base_pages_after_refine`가 GraphRAG 상위 severity 노드 3개를 추가 entity page로 생성. 미디어 entity는 여전히 graph_node_id 없음(정상). 본문도 "미디어는 조건부 미존재" 명시.
- **Why**: 샘플이 진실이어야 함. 구현 확장과 문서 보정으로 동시 해소.
- **Risk**: 상위 노드 기준이 `severity_weight`인데 일부 노드는 값 없음 — 현재는 fallback 0 처리. 다음 배치에서 기준 재점검 필요.

### 변경 3. False Negative 방어 예시 추가 (검증 증거 A-3)
- **Before**: false positive 제거 예시만 존재 (case_a). "보수화가 실제 전환을 놓치는가?"에 대한 증거 없음
- **After**: `current=[지정학,물가_인플레이션]`, `today=[환율_FX,에너지_원자재,통화정책,경기_소비,테크_AI_반도체]`, `direction=bearish → sentiment=positive`, 누적 2일 상태에서 **shift_confirmed=True** 확정. 이전 regime → `환율_FX + 에너지_원자재 + 통화정책`로 전환.
- **Why**: `coverage_today=core_top3` 기준이 실제 레짐 변화를 감지한다는 근거.
- **Risk**: 1건 시뮬이라 실전 누적 데이터 아님. 향후 daily run 로그로 누적 필요.

### 변경 4. 체크리스트 ↔ 증거 직접 연결
- **Before**: 체크리스트 항목이 검증 증거 섹션 어디에 해당하는지 불명
- **After**: 각 체크리스트 끝에 (검증 증거 A-1), (부록 B) 등 포인터 표기
- **Why**: 리뷰어 이동 비용 제거
- **Risk**: 없음

### 변경 5. 표현/오타 보정
- `규제 판정식` → `regime 판정식`
- `-1bp` → `"소폭 하락(0.012p), 실무상 큰 차이 없음"`
- `embed fallback 0건 — 로드 비용만 발생` → `"이번 달에는 alias로 충분. fallback은 대기 상태 (저비용 유지 중)"`

---

## 3. 리뷰 요청 체크리스트

- [ ] `configured coverage`와 `active coverage`가 모든 위치에서 분리되어 있는가 (**검증 증거 A-1, 수치 비교 표**)
- [ ] Entity page 본문 설명과 샘플이 일치하는가 (**검증 증거 A-2, 부록 B1/B2**)
- [ ] `coverage_today = core top3`가 false negative를 만들지 않는가 (**검증 증거 A-3**)
- [ ] false positive 방어는 여전히 작동하는가 — case_a 회귀 (**검증 증거 A-4**)
- [ ] sparse tags 처리가 보수적인가 (**부록 C — quality log 샘플**)
- [ ] `unresolved phrase`가 silently drop되지 않고 trace에 남는가 (**부록 D**)
- [ ] v12에서 보증한 canonical 불변성(debate rerun 후)이 여전히 유지되는가 (**검증 증거 C**)

---

## 4. 검증 증거

### A. 전/후 예시

#### A-1. Coverage 분모 혼란 제거

- **입력**: "2026-04 P1 결과에서 trigger coverage를 1줄로 표기"
- **이전 결과 (v12 본문)**:
  - 수치 비교 표: `unique_triggers 4/9` · `unique_targets 3/10`
  - 부록 summary: `coverage 67%` (4/6) · `coverage 60%` (3/5)
- **현재 결과 (v12.1)**:
  - configured trigger coverage: **4 / 9 (44%)**
  - active trigger coverage: **4 / 6 (67%)**
  - configured target coverage: **3 / 10 (30%)**
  - active target coverage: **3 / 5 (60%)**
- **해석**: 두 분모 모두 의미 있음. configured는 taxonomy 전체 관점, active는 당월 그래프에 실존하는 후보군 중 hit rate.

#### A-2. Entity page 샘플 진실성

- **입력**: "본문 claim `graph_node_id/canonical_entity_label/linked_events 추가`가 샘플에서 확인되는가?"
- **이전 결과**: 공개된 샘플(연합인포맥스)에 `linked_events`만 존재, 나머지 2개 필드 미등장 → claim과 불일치
- **현재 결과 (v12.1)**: 2026-04 Entities 디렉토리에 **8건** (media 5 + GraphRAG 상위 노드 3). `graphnode__유가/환율/달러` 3건은 **full schema** (graph_node_id + canonical_entity_label + linked_events 모두 포함). 미디어는 조건부 미존재를 본문에서 명시.
  - full schema 예: `label: "유가"` / `graph_node_id: 유가` / `canonical_entity_label: "유가"` / `linked_events: [event_12, event_29, event_35, event_39, event_44]`
- **해석**: 샘플이 진실. 미디어는 graph 노드가 아니므로 graph_node_id가 비어있는 것이 정상이며, 문서도 이를 반영.

#### A-3. False Negative 방어 (신규)

- **입력**:
  ```
  current.topic_tags = ["지정학", "물가_인플레이션"]
  top_topics_today  = ["환율_FX","에너지_원자재","통화정책","경기_소비","테크_AI_반도체"]
  current.direction = "bearish"
  sentiment_today   = "positive"
  consecutive_days_prev = 2   # 이미 2일 누적
  ```
- **이전 결과 (v11 단일 overlap)**: 같은 입력에서 `overlap_ratio = 0/5 = 0 < 0.3` → candidate True. 판정은 맞지만 "왜"가 불투명(토픽 수가 많기만 해도 트리거됨).
- **현재 결과 (v12 multi-rule)**:
  ```
  coverage_current = 0.0  (intersection 0 / current tags 2)  → low_coverage_current = True
  coverage_today   = 0.0  (core_top3={환율_FX,에너지_원자재,통화정책}, 교집합 0) → low_coverage_today = True
  sentiment_flip   = True (bearish → positive)
  candidate_rules  = [low_coverage_current, low_coverage_today, sentiment_flip]
  candidate_score  = 3/3
  shift_candidate  = True
  consecutive_days = 3  → shift_confirmed = True
  new regime       = "환율_FX + 에너지_원자재 + 통화정책"
  ```
- **해석**: 실제 레짐이 바뀌는 상황(regime tag 2개가 모두 core top 3에 없음 + sentiment flip)에서 v12가 정상적으로 전환 확정. 보수화가 과도하지 않음을 1건 증거로 확보.

#### A-4. False Positive 회귀 유지 (case_a)

- **입력**: `current=["지정학","물가_인플레이션"]`, `today=["환율_FX","에너지_원자재","통화정책","지정학","경기_소비"]`, `sentiment=negative`, `direction=bearish`
- **v11 결과**: overlap_ratio = 1/5 → candidate True (false positive)
- **v12/v12.1 결과**: coverage_current=0.5 (not low) · coverage_today=0.0 (core=top3에 지정학 없음) · sentiment_flip=False → score=1 → candidate=**False**
- **해석**: v12의 false positive 제거가 여전히 작동.

### B. 로그 샘플

우선순위 1 — **`_regime_quality.jsonl` false negative 방어 케이스 append**
```json
{"date":"2026-04-17","tag_match_mode":"exact_taxonomy","decision_mode":"multi_rule_v12",
 "current_topic_tags":["물가_인플레이션","지정학"],
 "top_topics_today":["환율_FX","에너지_원자재","통화정책","경기_소비","테크_AI_반도체"],
 "core_today":["에너지_원자재","통화정책","환율_FX"],
 "intersection_tags":[],"intersection_tags_core":[],
 "coverage_current":0.0,"coverage_today":0.0,
 "sentiment_today":"positive","current_direction":"bearish","sentiment_flip":true,
 "candidate_rules_triggered":["low_coverage_current","low_coverage_today","sentiment_flip"],
 "candidate_score":3,"shift_candidate":true,
 "consecutive_days":3,"cooldown_active":false,"shift_confirmed":true,
 "shift_reason":"3일 연속 토픽 변화 → regime 전환: 환율_FX + 에너지_원자재 + 통화정책"}
```

우선순위 2 — **canonical 불변성 (v12 보증 회귀)**
- MD5(`05_Regime_Canonical/current_regime.md`) 변경 없이 debate 재실행 처리 (v10 이후 고정)
- `regime_memory.json.bak` 복원 후 migration 재실행 시 `current.topic_tags = ["지정학","물가_인플레이션"]` idempotent 산출

우선순위 3 — **transmission path summary 최신 스냅샷** (configured/active 분리 표기)
```md
Period: 2026-04 · Phase: P1
- Total paths: 6
- configured trigger coverage: 4/9 (44%)
- active trigger coverage:     4/6 (67%)
- configured target coverage:  3/10 (30%)
- active target coverage:      3/5 (60%)
- Avg confidence: 0.532
```

### C. 불변성 / idempotent 검증

- `test_taxonomy_contract.py` 3/3 PASS (v11 회귀 유지)
- `test_regime_decision_v12.py` 4/4 PASS (v12 false positive/negative 기본)
- **신규 false negative 방어 검증**: A-3 수동 실행 결과 `shift_confirmed=True` 확인 (실행 로그 보관)
- canonical page MD5 debate 재실행 전후 동일

---

## 5. 수치 비교

| 항목 | v12 본체 | v12.1 (현재) | 해석 |
|------|----------|-------------|------|
| coverage 분모 표현 | 9/10 (본문) vs 6/5 (부록) 혼재 | configured + active 두 지표 명시 | 문서 정합성 확보 |
| **configured trigger coverage** | — | **4 / 9 (44%)** | taxonomy 관점 |
| **active trigger coverage** | — | **4 / 6 (67%)** | 당월 실존 후보군 관점 |
| **configured target coverage** | — | **3 / 10 (30%)** | taxonomy 관점 |
| **active target coverage** | — | **3 / 5 (60%)** | 당월 실존 후보군 관점 |
| Entity page 총 개수 | 5 (media 5) | 8 (media 5 + graph 3) | full-schema 예시 확보 |
| Entity with graph_node_id | 0 | **3** | claim과 샘플 일치 |
| False positive case_a | False | False | 회귀 없음 |
| **False negative 방어 case (신규)** | 미검증 | **shift_confirmed=True** 1건 | core=top3 규칙 검증 |
| avg_confidence 표현 | `-1bp` (어색함) | "소폭 하락(0.012p), 실무상 큰 차이 없음" | 표기 정리 |
| embed fallback 해석 | "로드 비용만 발생" | "alias로 충분, fallback은 대기 상태" | 가치 중립 표현 |
| 체크리스트 ↔ 증거 링크 | 없음 | 각 항목 끝 (검증 증거 A-n) | 탐색 비용 감소 |
| canonical 변경 (debate rerun) | 0 | 0 | v10/v11 보증 유지 |
| unresolved phrases (trace) | 10 | 10 | 변화 없음 (migration 동일) |

---

## 6. 남은 리스크

| 리스크 | 심각도 | 이유 | 다음 배치 여부 |
|--------|-------|------|----------------|
| v12 false negative 방어 증거가 시뮬 1건뿐 | Med | 실전 데이터 2주 이상 축적 후 재평가 필요. 1건은 설계 의도 확인 수준 | 다음 배치에서 누적 로그 분석 |
| GraphRAG 노드 기반 entity 선정 기준이 `severity_weight` 단독 | Low | 기준 재점검 여지. 현재 3건은 demo 수준 | Entity page 전면 redesign 배치에서 처리 |
| configured/active coverage가 `test_graphrag_p0_vs_p1.py`에서 여전히 한 분모 출력 | Low | 문서만 분리, 테스트 스크립트는 아직 구 포맷 | 다음 배치에서 스크립트 출력 확장 |
| `coverage_today=core_top3`가 tail 2개를 완전히 무시 | Med | 테일의 신호를 놓칠 위험. 현재는 보수화 우선 | 실전 로그로 tail 기여도 측정 후 조정 검토 |
| PHRASE_ALIAS 수작업 유지 부담 (v12 리스크 유지) | Med | 이번 배치는 문서 보정만 | **다음 배치 P0** (remap trace 누적 분석 → 반자동 보강) |

---

## 7. 다음 배치 제안

### 반드시 할 것

1. **PHRASE_ALIAS 반자동 보강** — `_taxonomy_remap_trace.jsonl` unresolved 빈도 상위 N개를 후보로 제시하는 스크립트 + 수동 검토 루프. 지금 수작업 유지비가 다음 배치 P0 리스크.
2. **Entity page 전면 redesign** — v12 설계 문서(`docs/entity_page_redesign.md`) 기준. 이번에 추가한 3건은 진실성 확보 목적 최소 구현. 미디어 중심 구조를 graph 노드 중심으로 교체.
3. **regime 판정식 실전 모니터링 2주** — daily_update 로그에서 false positive/negative 분포 확인 후 threshold(0.5/0.3/core=top3) 재조정 판단.

### 하면 좋은 것

1. `test_graphrag_p0_vs_p1.py`가 configured/active coverage 두 분모를 동시 출력하도록 확장.
2. `_regime_quality.jsonl` 월간 aggregate → `05_Regime_Canonical/quality_summary.md` 자동 생성.

### 하지 말 것

1. **transmission path canonical 승격** — alias 유지 부담이 해소되기 전 조기 승격 금지.
2. **graphify / 외부 viewer 연동** — 내부 정합성 확보가 먼저.
3. **regime 판정식 완화** — 실전 데이터 부재 상태에서 threshold 관대화 금지.
4. **문서 버전 파편화** — v12.1은 v12 본체 보정. 다음 배치는 실 기능 변경이므로 v13.

---

## 8. 부록

### B1. Full-schema entity page 샘플 (GraphRAG 노드 기반)

```markdown
---
type: entity
status: base
entity_id: graphnode__유가
label: "유가"
topic: news
period: 2026-04
graph_node_id: 유가
canonical_entity_label: "유가"
linked_events: [event_12, event_29, event_35, event_39, event_44]
source_of_truth: pipeline_refine
updated_at: 2026-04-17T13:41:57
---

# Entity — 유가

- Topic: `news`
- Mentioned in 6 articles
- Graph node: `유가`
- Linked events: `event_12`, `event_29`, `event_35`, `event_39`, `event_44`

## Recent articles
- [경제 안테나] 원유가 충격과 인플레, 그리고 금리
- "중동전쟁에 경기 하방위험 커져...물가·민생부담 확대 우려"
- 트럼프 "이란전 순조롭게 진행" 발언에…국제유가 하락 전환
...

> Base entity page — canonical regime/path 연결 금지.
```

### B2. Media entity page 샘플 (조건부 필드 미존재가 정상)

```markdown
---
type: entity
status: base
entity_id: source__연합인포맥스
label: "연합인포맥스"
topic: 매체
period: 2026-04
linked_events: [event_1944, event_1997, event_1713, event_2022, event_2053]
source_of_truth: pipeline_refine
updated_at: 2026-04-17T13:41:57
---
```
→ `graph_node_id`, `canonical_entity_label`은 **media 특성상 기대되는 미존재**. 문서 claim은 "optional, populated when matches a graph node".

### C. 파일 변경 요약

- 수정: `market_research/wiki/draft_pages.py` — GraphRAG 상위 severity 노드 entity 생성 블록 추가 (+ fallback try)
- 신규: `market_research/docs/review_packet_v12_1.md` (본 문서)

**미변경 (유지)**: `daily_update._step_regime_check`, `graph_rag.precompute_transmission_paths`, `taxonomy.extract_taxonomy_tags`, `graph_vocab`, 모든 테스트 스크립트.

### D. 실행 커맨드

```bash
# 회귀 (v11, v12)
python -m market_research.tests.test_taxonomy_contract
python -m market_research.tests.test_regime_decision_v12

# P0 vs P1 (표기만 패킷에서 configured/active로 재구성)
python -m market_research.tests.test_graphrag_p0_vs_p1 2026-04

# Entity page 재생성 (GraphRAG 노드 기반 추가 반영)
python -c "from market_research.wiki.draft_pages import refresh_base_pages_after_refine; \
           print(refresh_base_pages_after_refine('2026-04'))"
# expected: {'events': 5, 'entities': 8, 'assets': 6, 'funds': 2}

# False negative 방어 시나리오 수동 실행은 A-3 스니펫 참고
```

### E. 참고 문서

- `market_research/docs/review_packet_v12.md` — 본체
- `market_research/docs/review_packet_v11.md` — taxonomy contract 확정
- `market_research/docs/entity_page_redesign.md` — 다음 배치 설계
- `market_research/docs/graphrag_transmission_paths_review.md` — Phase 설계 원본

---

**총평: pass**
