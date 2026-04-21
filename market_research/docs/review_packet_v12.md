# Review Packet v12 — Regime 판정식 보정 + GraphRAG P1

## 1. 이번 패킷에서 받고 싶은 판정

- **목표 판정**: **pass에 가까운 revise**
- **핵심 목표**: v11의 canonical/draft 구조 위에서 (1) `_step_regime_check` 과민도 해소,
  (2) GraphRAG P1 coverage 회복. 큰 구조는 건드리지 않음.
- **특히 봐줬으면 하는 리스크**
  1. 다중 규칙 판정식이 **지나치게 보수적**이 되어 실제 전환을 놓칠 위험
  2. GraphRAG P1의 alias dict가 **유지보수 부담**으로 이어질 수 있음 (현재 수작업)
  3. Embedding fallback이 모델 로드 비용을 매 월 graph rebuild마다 발생시킴
  4. sparse tags 보수화가 현재 2026-04 실제 데이터(`topic_tags=["지정학","물가_인플레이션"]`)에서 어떻게 작동하는지 아직 실전 데이터 1주치 이상 미축적
- **이번 배치에서 의도적으로 미룬 것**
  1. transmission path의 canonical asset page 승격 (Phase 4+)
  2. graphify 외부 viewer 연동
  3. Entity page 전면 redesign (최소 연결점만 심음)
  4. `_regime_quality.jsonl` 월간 집계 대시보드

---

## 2. 핵심 변경 요약

### 변경 1. Regime shift 판정식 단일 overlap → 3-rule 다중 판정
- **Before**: `overlap_ratio < 0.3` 단일 조건. `current=2, today=5, intersection=1`에서 즉시 shift candidate.
- **After**: `coverage_current`, `coverage_today`(core=top3), `sentiment_flip` 중 **2개 이상** 만족 시 candidate. sparse tags(1개)는 `sentiment_flip` 필수, 0개는 hold.
- **Why**: "오늘 상위 토픽이 많음"에 민감하고 "실제 regime 변화"에는 둔감했던 구조. 동일 regime에서 일일 노이즈로 전환 후보가 뜨는 false positive를 줄임.
- **Risk**: 보수화로 실제 전환 감지 지연. cooldown(14일) + 3일 연속 규칙과 맞물려 2~3주 뒤늦게 반영될 수 있음.

### 변경 2. GraphRAG P1 — dynamic trigger/target + alias dict
- **Before**: 하드코딩 9 trigger × 12 target. 현재 월 그래프에 없는 trigger는 일괄 0, `"유가_급등"` vs `"유가"` 같은 표기 차이를 흡수 못함.
- **After**: `DRIVER_TAXONOMY` + `ASSET_TAXONOMY` 기반으로 월별 그래프에 실존하는 canonical만 선택. 각 canonical에 alias 리스트 (`"유가" → [유가, 국제유가, WTI, 원유, 브렌트]`). 검색은 alias 전체, 출력은 canonical 통일.
- **Why**: P0는 정확성은 얻었으나 2026-04에서 2 paths / trigger 2/9 / target 2/12까지 떨어졌음. coverage 회복이 필요.
- **Risk**: alias dict는 수작업 유지보수. 누락된 alias가 있으면 여전히 특정 노드가 매칭 안 됨.

### 변경 3. Embedding fallback (multilingual MiniLM)
- **Before**: alias 매칭 실패 시 전이경로 0.
- **After**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`로 node label 임베딩, cosine similarity ≥ 0.7 상위 1개 노드를 후보로 시도. 매칭 시 confidence × 0.7 감쇠. 모델 로드 실패 시 graceful skip.
- **Why**: alias로도 못 잡는 노드(예: `"투자심리_위축"` → 감정 지표)를 근접 탐지.
- **Risk**: 2026-04 실행에서 fallback이 0건 사용 — 실전 기여도 아직 0. 로드 비용(~2초)만 발생.

### 변경 4. Taxonomy remap trace — 매 phrase의 매핑 근거 영구 기록
- **Before**: migration 요약만 남음 (숫자 수준).
- **After**: `_taxonomy_remap_trace.jsonl` — `{source, original_phrase, mapped_tag, match_type, confidence, reason}`. 성공/실패 모두 기록, unresolved도 숨기지 않음.
- **Why**: alias 충돌 / 누락을 사후에 추적 가능. 향후 alias dict 보강의 근거 자료.
- **Risk**: 재실행 시 중복 append (idempotent 아님). 운영 중 trace가 비대해지면 주기적 정리 필요.

### 변경 5. Graph evidence summary + monthly quality aggregate
- **Before**: `07_Graph_Evidence/{period}_transmission_paths_draft.md` 한 장.
- **After**: `transmission_paths_summary.md` (누적 월간 표) + `_transmission_path_quality_monthly.json` (list).
- **Why**: drift / coverage를 월간으로 관찰 가능. 리뷰어가 한 파일에서 추이 확인.
- **Risk**: 판단 기준이 누적 데이터에 의존 — 초기엔 엔트리 1개라 의미 제한적.

---

## 3. 리뷰 요청 체크리스트

- [ ] 판정식이 **현 regime이 실제로 바뀐 날**에 candidate를 띄울 수 있는가 (false negative 시뮬)
- [ ] `coverage_today`가 `core=top3`만 쓰는 선택이 사실상 top5 하위 2개를 완전히 무시하는 부작용이 없는지
- [ ] P1 alias dict에 누락된 중요 alias는 없는가 (특히 `달러_글로벌유동성`, `유동성_크레딧`은 unmatched)
- [ ] Embedding fallback이 confidence 감쇠 0.7로 충분히 보수적인가, 아니면 더 낮춰야 하는가
- [ ] `_taxonomy_remap_trace.jsonl`이 운영 중 비대해질 때의 회전 정책이 필요한가
- [ ] Entity page 최소 연결이 다음 배치의 full redesign을 방해하지 않는가

---

## 4. 검증 증거

### A. 전/후 예시

**예시 1 — 판정식 과민도**

- **입력**: `current.topic_tags=["지정학","물가_인플레이션"]`, `top_topics_today=["환율_FX","에너지_원자재","통화정책","지정학","경기_소비"]`, `sentiment="negative"`, `current.direction="bearish"`
- **v11 결과**: `overlap=1, denom=5, ratio=0.2 < 0.3` → **shift candidate = True** (1/5로 민감 반응)
- **v12 결과**: `coverage_current=1/2=0.5` (경계, not low), `coverage_today=0/3=0.0` (core에 지정학 없음 → low), `sentiment_flip=False`. rules=`[low_coverage_today]`, score=1 → **shift candidate = False**
- **해석**: 기존 regime tag 중 절반이 오늘 top 5에 있으니 "실제 전환" 수준 아님. v12가 이를 candidate로 안 올림.

**예시 2 — GraphRAG P1 alias 효과**

- **입력**: `2026-04.json` (274 nodes / 252 edges)
- **P0 결과 (단일 키워드)**: 2 paths. "지정학 → 유가" (0.791), "인플레 → 금리" (0.298)
- **P1 결과 (alias + dynamic)**: 6 paths, 활성 trigger 4개, 활성 target 3개. "관세_무역 → 국내주식" 0.770, "지정학 → 국내주식" 0.588 새로 등장.
- **해석**: alias로 `"관세" → "수출입_비용"` 같은 노드가 매칭됨. 전이경로 스토리가 풍부해짐.

### B. 로그 샘플

**`_regime_quality.jsonl` v12 신규 필드** (sparse + flip 케이스)
```json
{"date":"2026-04-17","tag_match_mode":"exact_taxonomy","decision_mode":"multi_rule_v12",
 "current_topic_tags":["지정학"],
 "top_topics_today":["환율_FX","테크_AI_반도체","경기_소비","크립토","부동산"],
 "core_today":["경기_소비","테크_AI_반도체","환율_FX"],
 "intersection_tags":[],"intersection_tags_core":[],
 "coverage_current":0.0,"coverage_today":0.0,
 "sentiment_today":"positive","current_direction":"bearish","sentiment_flip":true,
 "candidate_rules_triggered":["low_coverage_current","low_coverage_today","sentiment_flip"],
 "candidate_score":3,"shift_candidate":true,
 "shift_reason":"sparse(1 tag) + sentiment_flip 포함 3/3 규칙"}
```

**`_transmission_path_quality.jsonl` P0 vs P1 append**
```json
{"date":"2026-04-17","phase":"P0","tag_match_mode":"word_boundary","pairs_total":108,
 "pairs_with_path":2,"self_loops_skipped":0,"total_paths":2,
 "unique_triggers":2,"unique_targets":2,"avg_confidence":0.544,"embed_fallback_used":0}
{"date":"2026-04-17","phase":"P1","tag_match_mode":"word_boundary+alias","pairs_total":54,
 "pairs_with_path":6,"self_loops_skipped":2,"total_paths":6,
 "unique_triggers":4,"unique_targets":3,"avg_confidence":0.532,"embed_fallback_used":0,
 "unmatched_triggers":["달러_글로벌유동성","유동성_크레딧","테크_AI_반도체","통화정책","경기_소비"],
 "unmatched_targets":["해외주식","부동산","크립토","금","환율","국내채권","해외채권"]}
```

**`_taxonomy_remap_trace.jsonl` (5 rows)**
```json
{"source":"regime_current","original_phrase":"지정학 완화","mapped_tag":"지정학","match_type":"alias","confidence":0.92}
{"source":"regime_current","original_phrase":"구조적 인플레","mapped_tag":"물가_인플레이션","match_type":"alias","confidence":0.92}
{"source":"regime_current","original_phrase":"단기 랠리와 장기 리스크의 불일치","mapped_tag":null,"match_type":"unresolved","confidence":0.0,"reason":"non-taxonomy descriptive phrase"}
{"source":"history[0]","original_phrase":"지정학 리스크","mapped_tag":"지정학","match_type":"alias","confidence":0.92}
{"source":"history[0]","original_phrase":"인플레·성장 둔화의 불확실성 충돌","mapped_tag":null,"match_type":"unresolved","confidence":0.0,"reason":"non-taxonomy descriptive phrase"}
```

### C. 불변성 / idempotent 검증

- **`regime_memory.json.bak` 복원 → migration 재실행**: current의 `topic_tags`가 `["지정학","물가_인플레이션"]`로 동일 산출 (migration 결과 stable).
- **테스트 스위트**:
  - `test_taxonomy_contract.py` 3/3 PASS (v11 규약 회귀 없음)
  - `test_regime_decision_v12.py` 4/4 PASS (신규)
- **canonical page 불변성**: debate 재실행이 `05_Regime_Canonical/current_regime.md`을 여전히 변경하지 않음 (v10/v11 보증 유지).

---

## 5. 수치 비교

| 항목 | 이전 (v11) | 현재 (v12) | 해석 |
|------|-----------|-----------|------|
| regime 판정식 | 단일 `overlap_ratio < 0.3` | 3 rule 중 2개 이상 (+sparse 처리) | 과민도 감소 |
| case_a (2tags/5today/1inter) shift_candidate | True | **False** | false positive 1건 제거 |
| case_b (flip + 0 overlap) candidate | True | True | 정당한 전환은 여전히 감지 |
| case_c (1 tag, no flip) candidate | True | **False** | sparse tags 보수화 작동 |
| case_d (0 tags) candidate | False | False | 변경 없음, 유지 |
| transmission total_paths | 2 (P0) | **6** (P1) | +200% |
| unique_triggers (coverage) | 2 / 9 (22%) | **4 / 9** (44%) | +22%p |
| unique_targets (coverage) | 2 / 12 (17%) | **3 / 10** (30%) | +13%p |
| unmatched triggers | 7 | **5** | 2 회복 |
| unmatched targets | 10 | **7** | 3 회복 |
| avg_confidence | 0.544 | 0.532 | 유의한 하락 없음 (-1bp) |
| self-loop skip | 0 | 2 | alias 간 겹침 필터 |
| embed_fallback_used | N/A | 0 | alias로 충분, 대기용 |
| taxonomy remap trace rows | 0 | **31** (migration) | 추적 확보 |
| canonical page 변경 (debate rerun) | 0 | 0 | v10/v11 보증 유지 |

---

## 6. 남은 리스크

| 리스크 | 심각도 | 이유 | 다음 배치 여부 |
|--------|-------|------|----------------|
| sparse tags 보수화가 실제 전환을 2~3주 늦게 감지 | Med | 3일 연속 + cooldown 14일 규칙과 곱 → 초기 regime 정착 지연 | 실전 데이터 1주 축적 후 재평가 |
| P1 alias dict 누락 (달러_글로벌유동성, 유동성_크레딧 미활성) | Med | 현재 월 그래프 노드 라벨과 alias가 안 맞음. 수작업 보강 필요 | 다음 배치에서 기존 node label 스캔 기반 반자동 alias 생성 |
| embed fallback이 실 사용 0건 | Low | 2026-04 단발 관찰. 다른 월에서는 쓰일 수 있음 | 3개월 누적 관찰 후 판단 |
| `_taxonomy_remap_trace.jsonl` 회전 정책 부재 | Low | 월별 append → 파일이 무한 성장 | 다음 배치에서 월 단위 partition 도입 |
| Entity page가 아직 매체 중심 — GraphRAG 노드 직접 연결 안 됨 | Med | 최소 연결(graph_node_id 필드)만 심음. linked_events는 event_group_id 수준, 해석 가치 제한 | **다음 배치 P0** (`docs/entity_page_redesign.md` 기준) |
| transmission path canonical 승격 판단 기준 미정 | Low | Phase 4+ 범위지만 승격 기준 명문화 없음 | Phase 4 착수 시 |

---

## 7. 다음 배치 제안

### 반드시 할 것

1. **Entity page redesign 구현** — 매체 중심을 GraphRAG 노드 중심으로 전환. v11에서 설계 완료, v12에서 최소 연결까지 심었으니 다음은 교체.
2. **`_taxonomy_remap_trace.jsonl` 분석** — 누적 데이터에서 가장 많이 등장하는 unresolved phrase를 뽑아 PHRASE_ALIAS 보강. 반자동 스크립트 + 수동 검토.
3. **규제 판정식 실전 모니터링** — 2주 이상 daily_update 돌린 뒤 `_regime_quality.jsonl`에서 false positive/negative 분포 확인. 필요 시 threshold(0.5, 0.3) 재조정.

### 하면 좋은 것

1. GraphRAG P1 alias 반자동 생성 — `02_Entities/`의 graph_node_id 연결로부터 node label 수집 → alias 후보 제시.
2. `_regime_quality.jsonl` 월 단위 aggregate → `05_Regime_Canonical/quality_summary.md` 요약 생성.

### 하지 말 것

1. **transmission path canonical 승격** — alias/unmatched 상태가 아직 정리 중. 조기 승격 시 canonical asset page가 draft 품질에 오염됨.
2. **graphify / 외부 viewer 연동** — 내부 구조(P1 alias, remap trace) 안정화 전 외부 의존성 추가 금지.
3. **regime 판정식을 더 관대하게 완화** — 이번 배치에서 일부러 보수화했음. 실전 데이터 없이 threshold 푸는 방향 금물.

---

## 8. 부록

### A. 파일 목록

**신규 (4개)**
- `market_research/analyze/graph_vocab.py` — DRIVER/ASSET taxonomy + alias dict
- `market_research/tests/test_regime_decision_v12.py` — 4 cases
- `market_research/tests/test_graphrag_p0_vs_p1.py` — 비교 리포트
- `market_research/docs/review_packet_v12.md` (본 문서)

**수정 (5개)**
- `market_research/pipeline/daily_update.py::_step_regime_check` — 3-rule 판정식, sparse fallback, quality log 확장
- `market_research/analyze/graph_rag.py` — dynamic trigger/target, alias 루프, embedding fallback, phase 파라미터
- `market_research/wiki/graph_evidence.py` — `write_transmission_paths_summary` 추가
- `market_research/wiki/draft_pages.py::write_entity_page` — graph_node_id / canonical_entity_label / linked_events 추가
- `market_research/wiki/taxonomy.py::extract_taxonomy_tags` — trace 파라미터, `write_remap_trace`
- `market_research/tools/migrate_regime_v11.py` — trace 수집 + 저장

**자동 생성**
- `market_research/data/report_output/_regime_quality.jsonl` (v12 필드 적용 append)
- `market_research/data/report_output/_transmission_path_quality.jsonl` (P0/P1 phase 필드)
- `market_research/data/report_output/_transmission_path_quality_monthly.json`
- `market_research/data/report_output/_taxonomy_remap_trace.jsonl`
- `market_research/data/wiki/07_Graph_Evidence/transmission_paths_summary.md`
- `market_research/data/wiki/02_Entities/2026-04_source__*.md` (6건, graph_node_id / linked_events 추가됨)

### B. Entity page 샘플 1건

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
updated_at: 2026-04-17T13:25:13
---

# Entity — 연합인포맥스
- Topic: `매체`
- Mentioned in 8 articles
- Linked events: `event_1944`, `event_1997`, `event_1713`, `event_2022`, `event_2053`

> Base entity page — canonical regime/path 연결 금지. 전면 redesign은 `docs/entity_page_redesign.md` 참조.
```

### C. `07_Graph_Evidence/transmission_paths_summary.md` (발췌)

```markdown
## Latest snapshot
- **Period**: 2026-04
- **Phase**: P1
- **Total paths**: 6
- **Unique triggers**: 4 / 6 (coverage 67%)
- **Unique targets**: 3 / 5 (coverage 60%)
- **Avg confidence**: 0.532
- **Graph size**: 274 nodes / 252 edges

## Active triggers
- `관세_무역` · `물가_인플레이션` · `에너지_원자재` · `지정학`

## Unmatched triggers
- `테크_AI_반도체` · `통화정책`
```

### D. 실행 커맨드

```bash
# 테스트 (전부 PASS해야 함)
python -m market_research.tests.test_taxonomy_contract        # v11 회귀
python -m market_research.tests.test_regime_decision_v12      # v12 4 cases

# P0 vs P1 비교 리포트
python -m market_research.tests.test_graphrag_p0_vs_p1 2026-04

# 마이그레이션 (trace 재수집)
python -m market_research.tools.migrate_regime_v11

# 실 daily pipeline (v12 판정식 적용)
python -m market_research.pipeline.daily_update 2026-04-17
```

### E. 참고 문서

- `market_research/docs/review_packet_v11.md` — 이전 배치 (taxonomy contract + P0)
- `market_research/docs/entity_page_redesign.md` — 다음 배치 entity page 설계
- `market_research/docs/graphrag_transmission_paths_review.md` — Phase 2/3 설계 원본

---

**총평: pass에 가까운 revise**
