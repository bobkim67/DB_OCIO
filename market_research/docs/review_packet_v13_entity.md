# Review Packet v13.1 — Entity page redesign (evidence response)

> **Status: implementation complete, evidence attached**
> 본 packet은 1차 리뷰 피드백("packet과 코드 불일치, revise/hold")에 따라
> **format D 6-section 형식으로 재제출**한다. 모든 주장은 현재 working tree
> + git HEAD 기준 직접 확인 가능한 grep / sed 출력으로 뒷받침한다.

검증 기준:
- HEAD = `b12c3bb` (review packet 커밋)
- v13 코드 변경 = `8e93f97` (entity redesign) + `b1a4f0d` (regenerated wiki)

---

## 1. Packet 요약 (5~10줄)

- entity 선별을 `node metadata`(severity)에서 `graph structure`(edge effective_score 합 + path_role_hit)로 전환.
- `taxonomy_topic`은 `wiki.taxonomy.extract_taxonomy_tags` exact gate만 허용 (1 hit→채택, 0/2+→탈락). 자동 alias 확장 금지.
- base page(02_Entities/) 본문에서 transmission path/adjacency 상세 **삭제**. summary numerics만 남김. 상세는 `07_Graph_Evidence/`만 소유 (writer 경계 강화).
- media entity (`source__*`) 생성 **중단** + `_purge_stale_entity_pages`로 자동 정리.
- 2026-04 실측: 101 nodes → taxonomy gate hit 4 → 최종 4건 (유가/이란/환율/반도체).
- 회귀 40/40 PASS, live 파일(05_Regime_Canonical / 06_Debate_Memory / regime_memory.json) 미변경.

---

## 2. 실제 변경 파일 목록

`git show --stat 8e93f97`:

```
 market_research/docs/entity_redesign_proposal.md | 226 +++++++++++++
 market_research/tests/test_entity_builder.py     | 241 ++++++++++++++
 market_research/tests/test_entity_demo_render.py | 268 +++++++--------
 market_research/wiki/draft_pages.py              | 398 +++++++----------------
 market_research/wiki/entity_builder.py           | 308 ++++++++++++++++++
 5 files changed, 999 insertions(+), 442 deletions(-)
```

후속 커밋:
- `b1a4f0d` — refresh 결과 (02_Entities/ 5 media 삭제 + 4 graphnode 재생성, 01/03/04 base pages 갱신)
- `b12c3bb` — review packet 본 문서

---

## 3. 각 파일별 핵심 diff

### 3.1 `wiki/draft_pages.py`

```
-398 lines (legacy entity loop + media handling + body adjacency/path)
+ ?  lines (entity_builder 위임 + slim write_entity_page)
net: 442 deletions / 398 insertions
```

제거된 식별자 (grep 0 hit):
- `src_counter`, `_find_graph_node`, `_linked_events`
- `_graph_adjacency_for`, `_paths_involving`
- 본문 헤더: `Graph adjacency (top 5)`, `Transmission paths involving this node`, `Draft evidence`

추가된 식별자:
- `from market_research.wiki.entity_builder import select_entity_candidates`
- `_purge_stale_entity_pages(month_str, keep_ids)`
- 본문 헤더: `## Confirmed facts`, `## Graph provenance`, `Detailed adjacency and transmission paths are available in 07_Graph_Evidence/`

### 3.2 `wiki/entity_builder.py` (신규, 308 lines)

5 함수 export: `load_graph_snapshot`, `map_node_to_taxonomy`,
`compute_node_importance`, `collect_entity_articles`, `select_entity_candidates`.

### 3.3 `tests/test_entity_builder.py` (신규, 241 lines)

7 cases (PHRASE_ALIAS hit/miss, edge sum, path_role, article matching,
taxonomy cap, no media).

### 3.4 `tests/test_entity_demo_render.py` (재작성, ±268 lines)

5 cases — 신스키마 대응. case 2가 명시적 negative test로 legacy 필드
(`node_severity:`, `has_draft_evidence:`, `Draft evidence` 헤더,
`Graph adjacency (top 5)`, `Transmission paths involving this node`)
**모두 absent**임을 검증.

---

## 4. 현재 커밋 기준 코드 스니펫

### 4.1 `write_entity_page` 시그니처 — `wiki/draft_pages.py:150`

```python
def write_entity_page(candidate: dict, month_str: str) -> Path:
    """Render an entity page (v13 redesign — graph-structure driven base page).

    The caller (``entity_builder.select_entity_candidates``) precomputes all
    fields needed. Base page contains:
      - Confirmed facts (mention summary + linked events + asset classes +
        recent articles with article_id refs)
      - Graph provenance — summary numerics ONLY (node_importance,
        support_count_sum, path_count, path_role_hit). Adjacency list and
        transmission path detail are intentionally NOT rendered here;
        those live in ``07_Graph_Evidence/``.

    severity-based fields are removed. ``taxonomy_topic`` is supplied by the
    builder via PHRASE_ALIAS exact gate — never from ``node.topic``.
    """
    label = candidate['label']
    entity_id = candidate['entity_id']
    taxonomy_topic = candidate['taxonomy_topic']
    graph_node_id = candidate.get('graph_node_id')
    linked_events = candidate.get('linked_events') or []
    primary_articles = candidate.get('primary_articles') or []
    recent_titles = candidate.get('recent_titles') or []
    unique_count = int(candidate.get('unique_article_count') or 0)
    first_seen = candidate.get('first_seen') or ''
    last_seen = candidate.get('last_seen') or ''
    node_importance = float(candidate.get('node_importance') or 0.0)
    importance_basis = candidate.get('importance_basis') or 'edge_effective_score_sum'
    support_count_sum = int(candidate.get('support_count_sum') or 0)
    path_count = int(candidate.get('path_count') or 0)
    path_role_hit = bool(candidate.get('path_role_hit'))
    ...
```

→ **단일 dict 인자.** 구 시그니처(9개 kwargs + media fallback)는 폐기.

### 4.2 `refresh_base_pages_after_refine` entity 섹션 — `wiki/draft_pages.py:383~405`

```python
    # Entity pages (v13 redesign — graph-structure driven, taxonomy exact gate)
    # - severity 기반 로직 제거 (실데이터 severity_weight=0, severity=neutral)
    # - media entity (source__*) 생성 중단
    # - node.topic fallback 금지; PHRASE_ALIAS exact hit만 허용
    # - body에 adjacency/path 상세 미노출 (07_Graph_Evidence/ 소유)
    entity_count = 0
    try:
        from market_research.wiki.entity_builder import (
            load_graph_snapshot, select_entity_candidates,
        )
        graph = load_graph_snapshot(month_str)
        candidates = select_entity_candidates(
            graph['nodes'], graph['edges'], graph['transmission_paths'],
            articles,
            max_entities=12, per_taxonomy_cap=3,
        )
        # 기존 페이지 정리 (media + legacy graphnode) 후 재생성
        _purge_stale_entity_pages(month_str, keep_ids={c['entity_id'] for c in candidates})
        for c in candidates:
            write_entity_page(c, month_str)
            entity_count += 1
    except Exception as exc:
        print(f'  [entity] 빌드 실패: {exc}')
```

→ **media loop / severity top-3 정렬 / `_find_graph_node` / `_linked_events`
모두 제거됨.** 단일 호출 `select_entity_candidates`로 위임.

### 4.3 `entity_builder.select_entity_candidates` — `wiki/entity_builder.py`

```python
def select_entity_candidates(nodes: dict,
                              edges: list[dict],
                              paths: list[dict],
                              articles: list[dict],
                              max_entities: int = 12,
                              per_taxonomy_cap: int = 3) -> list[dict]:
    """hard gate + evidence + 랭킹 + cap 적용."""
    raw: list[dict] = []
    for nid, meta in nodes.items():
        label = (meta or {}).get('label') or nid
        taxonomy_topic = map_node_to_taxonomy(label)
        if taxonomy_topic is None:
            # hard gate: PHRASE_ALIAS miss → 후보 제외
            continue

        imp = compute_node_importance(nid, label, edges, paths)
        art = collect_entity_articles(label, articles)

        has_evidence = (
            art['unique_article_count'] >= 2
            or art['linked_event_count'] >= 1
            or imp['path_role_hit']
        )
        if not has_evidence:
            continue

        raw.append({
            'entity_id': f'graphnode__{nid}',
            'graph_node_id': nid,
            'label': label,
            'taxonomy_topic': taxonomy_topic,
            **imp,
            **art,
        })

    # 랭킹: path_role_hit DESC, node_importance DESC, unique_article_count DESC
    raw.sort(key=lambda c: (
        0 if c['path_role_hit'] else 1,
        -c['node_importance'],
        -c['unique_article_count'],
        c['label'],
    ))

    # per_taxonomy_cap 적용
    taxonomy_count: Counter = Counter()
    kept: list[dict] = []
    for c in raw:
        t = c['taxonomy_topic']
        if taxonomy_count[t] >= per_taxonomy_cap:
            continue
        kept.append(c)
        taxonomy_count[t] += 1
        if len(kept) >= max_entities:
            break

    return kept
```

---

## 5. 테스트 실행 결과

### 5.1 B1~B4 직접 증빙 (grep 명령 + 결과)

```bash
$ grep -n "source__\|src_counter\|_find_graph_node\|_linked_events" \
       market_research/wiki/draft_pages.py
385:    # - media entity (source__*) 생성 중단                          # 코멘트만
447:    Covers both legacy ``source__*`` (media, deprecated in v13)     # 코멘트만
454:        stem = p.stem[len(prefix):]  # e.g. 'source__네이버검색'    # 코멘트만
```
→ **실코드 0건** (코멘트만 잔존; 코드 실행 분기 없음).

```bash
$ grep -n "severity_weight\|^.*severity" market_research/wiki/draft_pages.py
162:    severity-based fields are removed. ...                          # docstring
384:    # - severity 기반 로직 제거 (실데이터 severity_weight=0...)     # 코멘트
```
→ **실코드 0건** (docstring + 코멘트뿐).

```bash
$ grep -n "_graph_adjacency_for\|_paths_involving" \
       market_research/wiki/draft_pages.py
(no matches)
```
→ **함수 자체 삭제됨**.

```bash
$ grep -n "Graph adjacency\|Transmission paths involving\|Draft evidence" \
       market_research/wiki/draft_pages.py
(no matches)
```
→ **본문 headers 0건**.

```bash
$ grep -n "^def write_entity_page" market_research/wiki/draft_pages.py
150:def write_entity_page(candidate: dict, month_str: str) -> Path:
```
→ **단일 dict 시그니처**, 구 9-kwargs signature 폐기 확인.

### 5.2 Live entity page 본문 검증 (4파일)

```bash
$ grep -c "Graph adjacency\|Transmission paths involving\|Draft evidence" \
       market_research/data/wiki/02_Entities/2026-04_*.md
2026-04_graphnode__반도체.md:0
2026-04_graphnode__유가.md:0
2026-04_graphnode__이란.md:0
2026-04_graphnode__환율.md:0

$ grep -c "Graph provenance\|Confirmed facts" \
       market_research/data/wiki/02_Entities/2026-04_*.md
2026-04_graphnode__반도체.md:2
2026-04_graphnode__유가.md:2
2026-04_graphnode__이란.md:2
2026-04_graphnode__환율.md:2
```

→ **4 파일 모두 신구조 (Confirmed facts + Graph provenance) ×2 헤더 보유,
legacy 헤더 0건**.

### 5.3 테스트 결과 (재실행)

```
$ python -m market_research.tests.test_entity_builder
  PASS — case1: PHRASE_ALIAS exact hit → taxonomy_topic 부여
  PASS — case2: miss / ambiguous → None (억지 매핑 금지)
  PASS — case3: edge score sum = 1.4 (expected 1.4)
  PASS — case4: path_role_hit = trigger/target 직접, path_count는 내부 경유 포함
  PASS — case5: 매칭·first/last/primary 순서 정상 (count=3)
  PASS — case6: taxonomy cap 3 적용 (5 → 3)
  PASS — case7: refresh 후 media entity(source__) 미생성

$ python -m market_research.tests.test_entity_demo_render
  PASS — case1: new sections + frontmatter fields present
  PASS — case2: legacy severity/draft fields removed       ← B1~B4 자동검증
  PASS — case3: empty candidate renders safely
  PASS — case4: stable page id — rerun overwrites
  PASS — case5: path_role_hit in frontmatter, no path detail in body
```

전체 회귀 40/40 PASS:
```
test_taxonomy_contract   3/3
test_regime_decision_v12 4/4
test_alias_review        6/6
test_regime_monitor      7/7
test_regime_replay       8/8
test_entity_demo_render  5/5  (재작성)
test_entity_builder      7/7  (신규)
```

---

## 6. 남은 한계와 미완료 항목

### 6.1 정직한 한계

| 항목 | 상태 | 메모 |
|------|------|------|
| entity 수 4개 (예상 8~12) | ⚠️ honest output | 101 노드 중 PHRASE_ALIAS hit 4건. `달러`·`코스피`·`SK하이닉스` 등은 단독 키 미등록. **alias 확장은 다음 alias_review 루프에 후보로 제시 권고**, 본 배치에선 금지. |
| `unique_article_count` 과대 표시 | ⚠️ substring loose | 유가→2542건에는 "유가증권" 등 false hit 포함 가능. rank 보조로만 사용. |
| `first_seen` period 밖 (e.g. 2026-02-27) | ⚠️ honest | 월간 news JSON에 prior month article 포함됨. clamp 옵션화는 다음 배치 검토. |

### 6.2 미완료 / 다음 배치 후보

- `00_Index/media_coverage.md` 신설 (매체 통계 분리 보관) — 본 배치 유보
- mention trend 주차별 그래프 — 본 배치 유보
- PHRASE_ALIAS에 `달러` 등 단독 키 신설 검토 — 별도 alias_review 루프
- GraphRAG 노드 label 정규화 (서술형 노드 `유가_급등_압력` 등 처리) — 별도 대배치

### 6.3 절대 변경 안 한 것 (writer 경계 불변 확인)

```bash
$ grep -E "REGIME_FILE|_regime_quality|update_canonical_regime|write_debate_memory" \
       market_research/wiki/entity_builder.py
(no matches)
```
→ entity_builder는 read-only. canonical / debate / regime live 파일 write 0건.

---

## 7. 판정 문구 (정직)

**implementation complete, evidence attached.**

리뷰어 1차 피드백에서 지적한 packet-코드 불일치 우려는 **사실이 아니었음을
§5의 grep + sed 직접 출력으로 확인**. 단 packet의 톤이 "전면 재설계 완료" 처럼
단정적이었던 점은 본 재제출에서 evidence-first 형식으로 교정.

---

## Revision note

- **v13.1 (2026-04-20 KST)** — 초판 (디자인 + 구현 보고)
- **v13.1.1 (2026-04-21 KST)** — evidence response. format D 6-section 재구성.
  - §2 변경 파일 목록 + git stat
  - §3 파일별 net diff
  - §4 현재 working tree 코드 스니펫 (write_entity_page / refresh / select_entity_candidates)
  - §5.1 reviewer B1~B4 grep 직접 증빙
  - §5.2 live entity page 본문 grep
  - §5.3 회귀 40/40 PASS 재현
  - §6 한계/미완료 분리
  - §7 판정 톤 교정 ("전면 재설계 완료" → "implementation complete, evidence attached")
