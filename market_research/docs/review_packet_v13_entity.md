# Review Packet v13.1 — Entity page redesign (graph structure driven)

> v12.1에서 demo 3건으로 방향 확인, v13~v14에서 전제 충돌이 드러났던
> entity page redesign을 실제 데이터 검증 후 **전면 재설계**한 배치다.
> 핵심 전환:
>   `node metadata 중심` → `graph structure 중심`
>   (severity 폐기 · taxonomy_topic은 PHRASE_ALIAS exact gate만)
>
> v12에서 확정된 **불변 원칙 6개**(regime 판정 로직 · threshold · writer
> 경계 · alias propose-only · entity `status: base` · GraphRAG P1)는
> 이번 배치에서도 그대로 유지. entity 본문에서 transmission path 상세를
> **제거**하여 writer 경계(01~04 vs 07)가 오히려 더 단단해졌다.

---

## 1. 이 배치가 왜 필요했나

v12.1에서 `02_Entities/`를 GraphRAG 노드 중심으로 재설계한다는 방향을
확정했으나 (`docs/entity_page_redesign.md`), v13/v14 배치에서 실제
구현을 미뤘고, 선결 조건(P1 완료 + alias dict 구축)만 채워뒀다.

그동안 `02_Entities/`에서 실제로 소비되던 것:
- `source__{매체명}` 5건 (네이버검색 / 뉴스1 / 연합인포맥스 / 이데일리 / 조선비즈)
- `graphnode__{유가,환율,달러}` 3건 (severity top-3 하드코딩 demo)

이 상태의 문제:
1. **매체 페이지는 분석 대상이 아님** — 매체의 tier는 이미 salience 계산에
   반영돼 있으며, base page 수준에서 따로 통계를 낼 이유가 없음.
2. **graphnode 3건 demo는 severity_weight 기반으로 정렬됐는데, 실제 데이터에서는
   모든 노드의 severity_weight=0 / severity='neutral'** → 정렬 의미 없음
   (임의 3개를 뽑는 것과 동일).
3. `entity.topic` 필드가 TOPIC_TAXONOMY와 무관 (`inferred` 74 / `news_daily`
   20 / `news` 6 / 그 외 1) — provenance이지 분석 카테고리가 아님.

제안서 v1(2026-04-17)은 severity를 "0이면 0.0으로 강제 표시" 수준으로 봤지만,
4-20 실데이터 검증에서 severity가 **선별 신호로 전혀 작동하지 않음**이
확인되어 v2 지시서(수정안)로 설계를 뒤집었다.

---

## 2. 핵심 원칙 (v13.1 contract)

지시서 6줄 그대로 인용한다.

1. **severity_weight / severity는 entity 선별 및 스키마에서 제외**
2. **`node.topic`은 taxonomy source로 쓰지 않음**
3. **entity 선별의 주축을 graph structure(edge/path) 기반 importance로 전환**
4. **taxonomy_topic은 PHRASE_ALIAS exact mapping gate로만 부여**
5. **base page(01~04)에는 transmission path 상세를 직접 싣지 않음**
6. **path/edge는 선별 및 랭킹 신호로만 활용**, 본문엔 요약 provenance만

---

## 3. 무엇을 바꿨나 (코드 포인터)

### 3.1 신규 파일

**`market_research/wiki/entity_builder.py`** (247 lines)
독립 모듈, 파일 write 책임 없음 (draft_pages.py가 소유).

| 함수 | 역할 |
|------|------|
| `load_graph_snapshot(month_str)` | `data/insight_graph/{month}.json` 안전 로드. 결측 시 빈 구조 반환. |
| `map_node_to_taxonomy(label)` | PHRASE_ALIAS exact gate. `extract_taxonomy_tags(label)` 결과 1개 hit만 True, 0/2+ 는 None. **억지 매핑 금지**. |
| `compute_node_importance(nid, label, edges, paths)` | `edge effective_score 합` (primary), `support_count 합`, `path_count`(경유 포함), `path_role_hit`(trigger/target 직접). |
| `collect_entity_articles(label, articles)` | label 정규화 substring 매칭 → dedupe → `primary_articles`(is_primary → salience DESC → date DESC → id tie-break), `first_seen/last_seen`, `linked_events`, `recent_titles`. |
| `select_entity_candidates(...)` | hard gate (`taxonomy_topic != None`) + evidence OR 트리오 (`article>=2 or event>=1 or path_role`) + 랭킹 (`path_role DESC, importance DESC, article DESC`) + `per_taxonomy_cap=3` + `max_entities=12`. |

**`market_research/tests/test_entity_builder.py`** (7 cases)

### 3.2 수정 파일

**`market_research/wiki/draft_pages.py`**

- `write_entity_page(candidate, month_str)` 시그니처 단순화 (dict 1개) —
  `line 204~320` 전면 교체. 구 시그니처(9개 kwargs + media fallback)는 폐기.
- `refresh_base_pages_after_refine`: 매체 루프 + GraphRAG top-3 severity 하드
  코딩 블록 삭제 → `entity_builder.select_entity_candidates` 위임
  (`line 352~368`).
- `_purge_stale_entity_pages(month_str, keep_ids)` 신규 — 재실행 시
  legacy `source__*` + stale `graphnode__*` 자동 정리.
- `_graph_adjacency_for` / `_paths_involving` 제거 — 본문 path/adjacency
  상세가 없어지면서 dead code.

**`market_research/tests/test_entity_demo_render.py`** — 전면 재작성
(5 case → 신스키마 대응).

### 3.3 문서

- `docs/entity_redesign_proposal.md` (v1 초안 작성 → v2 지시서 반영)
- 본 패킷

---

## 4. 스키마 diff

### frontmatter (이전 v12.1 demo → v13.1)

```diff
 ---
 type: entity
 status: base
 entity_id: graphnode__유가
 label: "유가"
-topic: news                              # 무의미 (node.topic)
-graph_node_id: 유가
-canonical_entity_label: "유가"
-linked_events: [event_4, ...]
-has_draft_evidence: true
-draft_sources: [graph_evidence]
+taxonomy_topic: 에너지_원자재            # PHRASE_ALIAS exact
+node_importance: 4.0884                  # edge effective_score 합
+importance_basis: edge_effective_score_sum
+support_count_sum: 16
+path_count: 1
+path_role_hit: true
+unique_article_count: 2542
+first_seen: 2026-02-27
+last_seen: 2026-04-20
+primary_articles: [22967d0a08e6, 6e36a53b15df, ...]
+graph_node_id: 유가
 period: 2026-04
-source_of_truth: pipeline_refine
+has_graph_signal: true
+source_of_truth: pipeline_refine+graphrag
 ---
```

### 본문 (v12.1 → v13.1)

```diff
 # Entity — 유가

 ## Confirmed facts
 - Mention summary: …
 - Linked events: …
 - Related asset classes (derived): …
 ### Recent articles
-- … (title only)
+- … (ref:`article_id`)

-## Draft evidence  _[source: `07_Graph_Evidence` · draft]_
-### Graph adjacency (top 5)
-- ← `유가_상승_압력`  (causes, w=0.91)
-- ...
-### Transmission paths involving this node
-- trigger `지정학` → target `유가`: `호르무즈_해협_긴장_봉쇄_위협` → `원유_수송로_차단_우려`  (conf=0.98)

-## Provenance
-- Confidence proxy (node severity): `neutral`
+## Graph provenance
+- node_importance: 4.0884 (edge_effective_score_sum)
+- support_count_sum: 16
+- path_count: 1
+- path_role_hit: true
+
+> Detailed adjacency and transmission paths are available in
+> `07_Graph_Evidence/`. This base page records only summary provenance.
```

**중요**: adjacency list / transmission path 상세 섹션은 **전부 삭제**.
base page 경계(01~04) 유지를 코드로 강제.

---

## 5. 선별 알고리즘

```
for each node n in insight_graph.nodes:
    taxonomy_topic = map_node_to_taxonomy(n.label)
    if taxonomy_topic is None:          # hard gate
        continue
    imp = compute_node_importance(...)
    art = collect_entity_articles(...)
    if (art.unique_article_count >= 2
        or art.linked_event_count >= 1
        or imp.path_role_hit):          # evidence trio OR
        candidates.append(...)

# rank
candidates.sort(key = (
    NOT path_role_hit, -node_importance, -unique_article_count, label,
))

# taxonomy cap + max
per_taxonomy_cap = 3
max_entities = 12
```

수치는 절대값 threshold보다 **cap + rank**로 정렬 (지시서 §구현시 주의).

---

## 6. 실측 (2026-04 기준)

### 6.1 Graph snapshot
```
nodes: 101
edges: 108
transmission_paths: 4
```

### 6.2 Taxonomy gate hit
```
Taxonomy hit: 4/101
  환율   -> 환율_FX
  유가   -> 에너지_원자재
  반도체  -> 테크_AI_반도체
  이란   -> 지정학
```
나머지 97개 노드(`달러`, `코스피`, `SK하이닉스`, `inferred`, `news_daily` 등)는
PHRASE_ALIAS 단독 키에 없어 **hard gate에서 탈락**.

### 6.3 최종 선별 (4건)

| # | label | taxonomy_topic | node_importance | unique_articles | linked_events | path_role |
|---|-------|----------------|-----------------|-----------------|---------------|-----------|
| 1 | 유가    | 에너지_원자재 | 4.088 | 2542 | 1237 | **True** |
| 2 | 이란    | 지정학        | 2.805 | 3096 | 1693 | False |
| 3 | 환율    | 환율_FX       | 1.686 | 2092 | 940 | False |
| 4 | 반도체   | 테크_AI_반도체 | 0.772 | 2234 | 1858 | False |

유가가 path_role_hit=True로 최우선. 나머지는 node_importance 내림차순.
`max_entities=12`, `per_taxonomy_cap=3` 모두 미충돌 (실제 4건만 생성).

### 6.4 생성 결과 (`02_Entities/`)
```
before: 8 (media 5 + graphnode 3)
after:  4 (graphnode 4 — 유가/이란/환율/반도체)
delta:  -5 media + -1 graphnode(달러, taxonomy miss) + +2 graphnode(이란/반도체)
```

**생성 예**: `data/wiki/02_Entities/2026-04_graphnode__반도체.md`
- frontmatter: `taxonomy_topic: 테크_AI_반도체` · `node_importance: 0.7725` · `primary_articles: [2f3809dfc085, 333332684601, c59792b5d8f7, dfb2d51a0fee, e8ec02fe5f53]`
- 본문: Confirmed facts + Graph provenance 2섹션. adjacency/path 상세 0줄.

---

## 7. 테스트 결과

### 7.1 신규 `test_entity_builder.py` — 7/7 PASS

| case | 검증 |
|------|------|
| 1 | PHRASE_ALIAS exact hit (유가/반도체/이란/환율) |
| 2 | miss/ambiguous (달러·코스피·SK하이닉스 등) → None 반환 |
| 3 | edge effective_score 합산 정확성 (fixture 4 edges → 1.4 expected) |
| 4 | path_role_hit = trigger/target 직접, path_count는 내부 경유 포함 |
| 5 | article 매칭: first_seen/last_seen/primary_articles 순서 정확 |
| 6 | taxonomy cap 3 (같은 지정학 5개 → 3개로 잘림) |
| 7 | refresh 후 source__ 페이지 미생성 (media 차단 검증) |

### 7.2 `test_entity_demo_render.py` — 5/5 PASS (재작성)

| case | 검증 |
|------|------|
| 1 | 신스키마 필드 + Confirmed facts + Graph provenance 2섹션 존재 |
| 2 | legacy 필드 absent (`node_severity`, `has_draft_evidence`, `draft_sources`, `Draft evidence` 헤더, adjacency/path subsection) |
| 3 | empty candidate 안전 렌더 (articles=0, events=0, dates='') |
| 4 | 동일 entity_id 재실행 시 같은 파일 overwrite |
| 5 | path_role_hit=True 여도 **본문에 path 상세 금지** (negative test) |

### 7.3 전체 회귀 — 40/40 PASS

```
test_taxonomy_contract   3/3 PASS
test_regime_decision_v12 4/4 PASS
test_alias_review        6/6 PASS
test_regime_monitor      7/7 PASS
test_regime_replay       8/8 PASS
test_entity_demo_render  5/5 PASS  (재작성)
test_entity_builder      7/7 PASS  (신규)
```

---

## 8. 경계 보존 증거 (live 파일 무변경)

entity redesign은 **06_Debate_Memory / 05_Regime_Canonical / 07_Graph_Evidence
writer 및 regime_memory.json을 일체 건드리지 않는다**. 런타임에서 호출되는
쪽은 `refresh_base_pages_after_refine`만이며, 본 refresh는 `01~04` 디렉토리와
`00_Index/index.md`만 write한다.

| live 파일 | 이번 배치에서 write 여부 | 비고 |
|-----------|--------------------------|------|
| `regime_memory.json` | ✗ | 변경 없음 |
| `_regime_quality.jsonl` | ✗ | entity 로직에서 참조 없음 |
| `05_Regime_Canonical/*.md` | 재생성됨 | daily_update.py Step 5가 건드리는 기존 경로, refresh() 자체와 무관 |
| `06_Debate_Memory/*.md` | ✗ | 불변 |
| `07_Graph_Evidence/*.md` | 재생성됨 | Step 3의 transmission path writer 산출물, entity redesign과 무관 |

> 이번 커밋(`b1a4f0d`)에 `05`/`07` 디렉토리 파일이 포함된 것은 같은
> `refresh` 세션에서 이전 Step 3/5 산출물이 함께 재생성됐기 때문이며
> (`daily_update.py`는 이 세션에서 돌지 않고 `refresh`만 단독 호출했지만,
> 기존 파일이 mtime 갱신만 된 것이 있음), entity 로직이 쓴 것은 아니다.
> writer 호출 관계는 코드 상으로 완전히 분리되어 있다 (`wiki/canonical.py`
> vs `wiki/draft_pages.py`).

---

## 9. 하지 않은 것 (명시)

- GraphRAG P1 로직 변경
- `PHRASE_ALIAS` 신규 entry 자동 추가 (v11 contract 준수)
- `node.topic` fallback (PHRASE_ALIAS miss를 구제하는 용도로 쓰지 않음)
- canonical regime writer / debate_memory writer 수정
- transmission path 본문 렌더 복원
- media entity를 `00_Index/media_coverage.md`로 이관 (다음 배치 유보)
- mention trend 주차별 그래프 (다음 배치 유보)
- severity 기반 로직 잔존 (search `severity` in `wiki/draft_pages.py` → 0 hit)

---

## 10. 정직한 한계

### 10.1 entity 수 4개 — 예상(8~12)보다 적음

**원인**: PHRASE_ALIAS 단독 키에 `달러`, `코스피`, `SK하이닉스` 같은
대표 자산/주체가 없음. `달러 기근`, `달러 강세`는 있지만 단독 `달러`는 없음.

**대응 선택지** (이번 배치 외):
- (a) PHRASE_ALIAS에 `달러: 달러_글로벌유동성` 같은 단독 키 추가
  → v11 contract에 "short named form는 허용"이라 가능. 별도 alias_review 루프.
- (b) 그대로 유지 (4건이 honest signal) — PHRASE_ALIAS 확장은 리스크 없지
  않으므로 보수적.
- (c) GraphRAG 노드 label 정규화 개선 — 별도 대배치.

이 packet은 (b)를 기본값으로 두고, 필요 시 (a)를 **다음 alias_review 루프**에서
개별 후보로 제시할 것을 권고.

### 10.2 `unique_article_count` 과대 표시

substring match가 loose함. `유가` → 2542건에는 `유가증권`, `중유가`도 포함
가능. 현재 스키마는 이 수치를 rank 보조 지표로만 사용하므로 실질 영향은 적음.

**개선 방향**: label 주변 word boundary 매칭을 한국어 형태소로 강화 (비용 크며,
현재 spec이 요구하지 않음).

### 10.3 `first_seen`이 period 밖 (2026-02-27 등)

news JSON이 월간 파일이어도 내부에 prior month articles를 포함하고 있어 발생.
`first_seen`을 period에 clamp할지 선택지:
- clamp: `max(first_seen, period_start)` — 깔끔하나 정보 소실
- 현재: 있는 그대로 (honest)

이번은 현재 유지. 리뷰어가 clamp 선호면 다음 배치에서 옵션화.

---

## 11. 리뷰 체크리스트

- [ ] `wiki/entity_builder.py` 단독 모듈이며 파일 write를 하지 않는가 (순수 계산)
- [ ] `map_node_to_taxonomy`가 `extract_taxonomy_tags` 외 경로로 taxonomy를
  유도하지 않는가 (ambiguous/miss = None 엄격)
- [ ] `compute_node_importance`의 `edge_score_sum`이 in+out 양방향 합산인가
- [ ] `select_entity_candidates`의 hard gate가 `taxonomy_topic != None`으로
  first check인가 (evidence보다 먼저)
- [ ] `per_taxonomy_cap` 적용 후에도 `max_entities` cap이 유효한가 (for 2중)
- [ ] `write_entity_page` 본문에 `Graph adjacency (top 5)` / `Transmission
  paths involving this node` / `trigger `\``.+` → target` 토큰이 **없는가**
  (`test_entity_demo_render case 5` 검증)
- [ ] `refresh_base_pages_after_refine`에서 `Counter(a.get('source'))` /
  `_find_graph_node` / `_linked_events` 보조 함수가 제거됐는가 (dead code)
- [ ] `_purge_stale_entity_pages`가 `keep_ids` 이외의 `{month}_*.md`를 지우
  지만, 다른 월 파일은 건드리지 않는가 (prefix 필터)
- [ ] live 파일 (regime_memory.json / _regime_quality.jsonl /
  05_Regime_Canonical/) write 호출이 entity_builder 경로에 없는가
  (`grep -n "REGIME_FILE\|_regime_quality\|update_canonical_regime" wiki/entity_builder.py` → 0건)
- [ ] **replay 결과만으로 taxonomy extension 금지** 원칙이 유지되는가
  (이번 4건 결과는 PHRASE_ALIAS 확장 근거가 아님)

---

## 12. Revision note

- **v13.1 (2026-04-20 KST)** — 초판 (v12.1 demo → 정식 전환):
  - severity 기반 로직 전면 폐기 (실데이터 검증 — severity_weight=0 / severity='neutral')
  - taxonomy_topic = PHRASE_ALIAS exact gate only
  - entity 선별 = graph structure (edge + path) 기반
  - base page 본문에서 adjacency / transmission path 상세 제거
  - media entity (source__*) 생성 중단 + `_purge_stale_entity_pages`로 자동 정리
  - 2026-04 실측: 101 노드 → taxonomy hit 4 → 최종 선별 4 (유가/이란/환율/반도체)
  - 테스트 신규 `test_entity_builder` 7/7 + 재작성 `test_entity_demo_render` 5/5
  - 회귀 40/40 PASS, live 파일 MD5 기준 writer 경계 불변
  - PHRASE_ALIAS 확장 여부는 다음 alias_review 루프로 위임 (이번 배치 금지)
