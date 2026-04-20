# Entity page redesign — 실행안 (v2, 지시서 반영)

- 작성: 2026-04-20 초안 / 2026-04-20 v2 (지시서 반영)
- 선행 설계: `docs/entity_page_redesign.md` (방향)
- 본 문서: **v2 — 실데이터 검증 후 수정**

> 변경의 핵심 한 줄: "entity redesign을 포기하는 것이 아니라, **node metadata 중심 설계에서 graph structure 중심 설계로 전환**하는 것."

---

## 0. v1 대비 주요 변경 (why)

실제 `insight_graph/2026-04.json` 샘플 확인 결과:

| v1 가정 | 실데이터 | v2 대응 |
|---------|----------|---------|
| `node_severity 0.82` 계산 | `severity_weight`: 전부 0 / `severity`: 전부 `neutral` | **severity 완전 폐기** |
| `node.topic`으로 taxonomy 유도 | `inferred`(74)·`news_daily`(20)·`news`(6) — provenance일 뿐 | `PHRASE_ALIAS exact gate`로만 부여 |
| metadata 풍부 | `{label, topic, severity}` 3필드만 | **importance는 edge에서 계산** |
| severity >= 0.3 필터 | 모두 0이라 필터 무용 | **graph structure 기반 필터** |

Edge metadata는 유효 (`effective_score`, `support_count`, `last_seen`, `decay_class`, `weight`), transmission path의 trigger/target은 이미 canonical label 형태.

---

## 1. 목적

`02_Entities/`의 base 페이지를 **GraphRAG 노드 중 taxonomy 연결이 명시적이며 graph 구조에서 중요한 entity**로 채운다. 매체(source) 기반 entity 페이지는 이번 배치에서 제거하고, 집계용 페이지 신설은 유보.

**범위 외**:
- transmission path 상세 본문 노출 (07_Graph_Evidence/가 소유, base page는 요약 provenance만)
- GraphRAG 노드 자체 품질 개선 (P1 결과 수용)
- 주차별 mention trend 그래프 (별도 배치)
- canonical regime / debate_memory / graph_evidence writer 경계 — 불변

---

## 2. 핵심 원칙

1. **severity 완전 제외** — 선별·스키마·본문 모두에서 제거
2. **node.topic 비사용** — taxonomy source로 쓰지 않음
3. **Graph structure 기반 entity 선별** — edge/path를 importance/rank 신호로 활용
4. **taxonomy_topic은 PHRASE_ALIAS exact gate만 허용** — `extract_taxonomy_tags` 결과 정확히 1개일 때만 부여, miss/ambiguous는 후보 탈락
5. **base page 본문엔 transmission path 상세 없음** — 요약 수치 + 07 링크만
6. **automatic alias expansion 금지** — miss 노드를 살리려 node.topic fallback 금지

---

## 3. 스키마 (frontmatter)

```yaml
---
type: entity
status: base
entity_id: graphnode__<node_id>
label: "유가"
taxonomy_topic: 에너지_원자재              # TOPIC_TAXONOMY 14 exact
node_importance: 1.742                      # edge effective_score sum
importance_basis: edge_effective_score_sum
support_count_sum: 6
path_count: 3
path_role_hit: true
unique_article_count: 4
first_seen: 2026-04-03
last_seen: 2026-04-20
primary_articles: [026f47ad7538, ...]      # article_id 기준
graph_node_id: 유가
period: 2026-04
has_graph_signal: true
source_of_truth: pipeline_refine+graphrag
---
```

**제거된 필드** (v1 대비): `node_severity`, `has_draft_evidence`, `draft_sources`
**유지**: `entity_id` prefix `graphnode__` (stable, demo 1:1 호환)

---

## 4. 본문 렌더링 (base page factual-only)

```
# Entity — 유가

**Canonical label**: `유가`
**Taxonomy**: `에너지_원자재` · **Graph node**: `유가`

## Confirmed facts
- Mention summary: 2026-04-03 ~ 2026-04-20 · 4 articles
- Linked events: event_4, event_5, ...
- Related asset classes (derived): 원자재

### Recent articles
- 호르무즈 긴장에 유가 반등…WTI 6%↑ (ref:`a1b2c3`)
- ...

## Graph provenance
- node_importance: 1.742 (edge_effective_score_sum)
- support_count_sum: 6
- path_count: 3
- path_role_hit: true

> Detailed adjacency and transmission paths are available in `07_Graph_Evidence/`.
```

**제거 (v1 대비)**: Graph adjacency top-5 상세, Transmission paths 본문 나열, Draft evidence 섹션
**사유**: base page 경계 유지 (01~04는 factual aggregation only)

---

## 5. 선별 알고리즘

### 5.1 필터 (hard gate + evidence)
```
hard_gate: taxonomy_topic is not None        # PHRASE_ALIAS exact hit
evidence (OR):
  unique_article_count >= 2
  OR linked_event_count >= 1
  OR path_role_hit is True
```

### 5.2 랭킹
```
ORDER BY:
  path_role_hit DESC,
  node_importance DESC,
  unique_article_count DESC
```

### 5.3 Cap
```
max_entities = 12
per_taxonomy_cap = 3   # 같은 taxonomy_topic 과밀 방지
```

### 5.4 node_importance 정의
```python
node_importance = sum(e.effective_score for e in incident_edges(node_id))
```
초기 버전은 단순 합. path_count, support_count_sum 등은 provenance용 보조 지표.

---

## 6. 구현 단계

### Step 1. `wiki/entity_builder.py` 신규 (독립 모듈)
- `load_graph_snapshot(month_str) -> dict` — insight_graph/{month}.json 로드
- `map_node_to_taxonomy(label) -> str | None` — PHRASE_ALIAS exact gate
  - extract_taxonomy_tags → hit 1개면 반환, 0/2+는 None
- `compute_node_importance(node_id, label, edges, paths) -> dict`
  - `edge_score_sum`, `support_count_sum`, `path_count`, `path_role_hit`
- `collect_entity_articles(label, articles) -> dict`
  - `unique_article_ids`, `first_seen`, `last_seen`, `primary_articles` (dedupe + primary + salience desc + 최신 tie-break)
  - `linked_events` = 매칭 기사 `_event_group_id` unique
- `select_entity_candidates(...) -> list[dict]`
  - hard gate + evidence + 랭킹 + cap 적용

### Step 2. `wiki/draft_pages.py::write_entity_page()` 스키마·본문 교체
- 신규 파라미터: `taxonomy_topic`, `node_importance`, `importance_basis`,
  `support_count_sum`, `path_count`, `path_role_hit`, `unique_article_count`,
  `first_seen`, `last_seen`, `primary_articles`
- 제거 파라미터: `topic`(기존), `adjacent_nodes`, `paths_involving`, `graph_node_meta`
- 본문: Confirmed facts + Graph provenance 2섹션만. Draft evidence 섹션 삭제

### Step 3. `refresh_base_pages_after_refine()` 루프 교체
- media entity 루프 **제거** (source__*)
- graph node top-3 hardcoding **제거**
- `entity_builder.select_entity_candidates(...)` 호출 → 반환 후보 전체 렌더
- 예상 8~12개/월

### Step 4. 기존 파일 처리
- `data/wiki/02_Entities/2026-04_source__*.md` 5건 → **삭제**
- `data/wiki/02_Entities/2026-04_graphnode__{유가,환율,달러}.md` 3건 → 재생성으로 덮어쓰기
- backup 디렉토리는 만들지 않음 (git history로 복구 가능)

### Step 5. 테스트 `tests/test_entity_builder.py`
케이스:
1. PHRASE_ALIAS exact hit → taxonomy_topic 부여
2. miss / ambiguous → 후보 제외
3. edge effective_score 합산 정확성 (fixture 엣지 5건)
4. path_role_hit 계산 (trigger/target 직접 등장)
5. article 매칭 후 first_seen/last_seen/primary_articles 순서 정확성
6. taxonomy cap 적용 확인 (같은 topic 4건 → 3건으로 잘림)
7. media entity 미생성 확인 (refresh 후 source__ 없음)

### Step 6. 회귀
- `test_taxonomy_contract.py` 3/3
- `test_regime_decision_v12.py` 4/4
- `test_alias_review.py` 6/6
- `test_regime_monitor.py` 7/7
- `test_entity_demo_render.py` 5/5 (기존 3 demo 포맷 호환 필요 — 스키마 변경으로 영향 있음, 업데이트 여부 결정)
- `test_regime_replay.py` 8/8

---

## 7. 수용 기준 (done definition)

- [x] severity 기반 로직 제거
- [x] taxonomy_topic은 `extract_taxonomy_tags` 기반으로만 부여
- [x] node_importance가 edge effective_score_sum으로 계산
- [x] `02_Entities/`가 graphnode 중심 8~12개 수준 생성
- [x] media entity (source__*) 생성 중단
- [x] entity page 본문에서 adjacency/path 상세 제거
- [x] primary_articles가 article_id 기준 기록
- [x] 신규 테스트 PASS
- [x] 기존 taxonomy/regime/graph evidence 회귀 PASS

---

## 8. 하지 않는 것 (명시)

- GraphRAG 노드 정규화 개선
- Mention trend 주차별 그래프
- canonical regime / debate_memory / graph_evidence writer 수정
- media_coverage.md 신규 생성 — 다음 배치 유보
- taxonomy miss 노드 구제용 alias 확장
- node.topic fallback
- importance에 대한 절대값 threshold (cap/rank 중심)

---

## 9. 리스크 & 주의

- **entity 수 부족 가능성**: 101 node 중 taxonomy hit가 소수일 수 있음. 4월 실측 확인 후 per_taxonomy_cap 조정 가능성 있음. 초기에는 12 cap 그대로 두고 관찰.
- **path_role_hit 해석**: transmission_paths의 trigger/target은 canonical label(예: `지정학`, `유가`) — 일부는 노드 id와 일치하지 않을 수 있음. label 기준 매칭 구현.
- **Article 매칭 비용**: 월 23,495 articles × N nodes = O(NM). label alias hit 먼저 → normalized contains fallback으로 효율화.
- **기존 demo 페이지 스키마 변경**: `test_entity_demo_render.py`의 기대값을 신규 frontmatter로 갱신 필요 가능성. 회귀에서 확인.
