# Review Packet v13 — 운영 안정화 + 표시 품질 배치

> v12/v12.1에서 확정된 기술 방향(multi-rule 판정식 / exact taxonomy contract
> / GraphRAG P1 / canonical/debate/evidence 3-tier)은 **변경하지 않는다**.
> 이 배치는 "기능 확장"이 아니라 "운영 도구 + 표시 품질" 배치다.

---

## 0. 고정 규칙 준수 확인

| 규칙 | 이 배치에서의 조치 |
|------|-------------------|
| Regime canonical writer는 daily_update Step 5만 | `debate_engine`, `tools/*` 모두 canonical writer 호출 없음 |
| Debate는 `regime_memory.json` write 금지 | v10에서 이미 제거, 이번 배치 추가 write 경로 없음 |
| Transmission path는 `07_Graph_Evidence/` draft only | `write_entity_page`는 `07_`로 라벨만 표시하고 쓰기 하지 않음 |
| topic_tags는 exact TOPIC_TAXONOMY만 허용 | `_load_approved_alias`에서 taxonomy 외 값 silently drop |
| Descriptive phrase는 `narrative_description` 또는 unresolved trace | 유지 |
| Transmission path → canonical 승격 금지 | 없음 |
| graphify 외부 viewer 연동 금지 | 없음 |
| Regime threshold 완화/관대화 금지 | 판정 로직 코드 한 줄도 변경하지 않음 |

---

## 1. 이번 패킷에서 받고 싶은 판정

- **목표 판정: packet 기준 pass-leaning** (최종 pass는 코드 diff와 실행
  증거 재확인 전제)
- 본 패킷은 코드 diff 자체가 아니라 운영/표시 품질 보강 패킷이므로,
  판정은 **packet 기준**으로 요청한다. 실제 코드 동작/회귀는 §9 실행 증거로
  검증해주길 바란다.
- 핵심 목표는 3가지 운영성 산출물:
  1. PHRASE_ALIAS 반자동 제안 루프 (propose/apply CLI + YAML)
  2. Regime 판정식 2주 관측용 passive summariser
  3. Entity page 재설계 — Confirmed fact vs Draft evidence 섹션 분리

- 이 패킷은 기능 확장이 아니라 **운영 투명성** 개선. alias 자동 수정이나
  threshold 조정 같은 위험한 변경은 일부러 빼두었다.

- 특히 봐줬으면 하는 포인트:
  1. alias가 왜 "propose-only"로 설계되었는가 (§3)
  2. regime 판정식 threshold를 왜 건드리지 않았는가 (§4)
  3. entity page에서 canonical/draft 분리 방식이 충분히 명확한가 (§5)

- 의도적으로 미룬 것:
  - Transmission path canonical 승격 (Phase 4+ 유지)
  - Entity page 전면 확장 (graphnode 기반 대량 생성은 alias dict 안정화 후)
  - graphify viewer
  - regime threshold 재조정 → 2주 데이터 누적 후

- 특히 `regime_monitor` 수치는 현재 **row-level operational summary**로 읽어
  주길 요청한다. 같은 날짜에 여러 row가 append되는 운영/테스트 특성상
  `unique_dates_in_window`가 1인 상태이고, true day-level churn / false-negative
  판단은 unique date 누적 후 재평가 예정이다.

---

## 2. 변경 파일 목록

| 구분 | 파일 | 성격 |
|------|------|------|
| 신규 | `market_research/config/phrase_alias_approved.yaml` | 승인 규칙 YAML 시드 (주석 + 빈 값) |
| 신규 | `market_research/tools/alias_review.py` | `--propose` / `--apply` CLI |
| 신규 | `market_research/tools/regime_monitor.py` | `--days N` passive summariser |
| 수정 | `market_research/wiki/taxonomy.py` | `_load_approved_alias()` setdefault merge |
| 수정 | `market_research/wiki/draft_pages.py` | `write_entity_page` 재구성 + 그래프 컨텍스트 주입 |
| 신규 | `market_research/tests/test_alias_review.py` | 5 cases |
| 신규 | `market_research/tests/test_regime_monitor.py` | 5 cases |
| 신규 | `market_research/tests/test_entity_demo_render.py` | 5 cases |
| 신규 | `market_research/docs/review_packet_v13.md` | 본 문서 |

**변경 없음 (확인)**:
- `pipeline/daily_update.py::_step_regime_check` — regime 판정식 로직 그대로
- `analyze/graph_rag.py::precompute_transmission_paths` — P1 동작 그대로
- `wiki/canonical.py` — canonical writer 그대로
- `report/debate_engine.py`, `report/debate_service.py` — regime write 재도입 없음

커밋 단위 (브랜치 `feature/insight-v13`):
1. `v13: alias_review propose/apply + approved yaml loader`
2. `v13: regime_monitor CLI — passive 14-day summariser`
3. `v13: entity page redesign — Confirmed / Draft evidence 분리`
4. `v13: review packet + regression check`

---

## 3. 왜 v13을 "운영 안정화 배치"로 잡았는지

v12.1에서 확보된 것:
- multi-rule 판정식 (false positive/negative 방어)
- exact taxonomy contract (phrase 유입 차단)
- GraphRAG P1 (dynamic trigger/target + alias + embed fallback)
- 3-tier wiki (canonical/draft evidence 경계)

그러나 **실전 운영에서 반복되는 3가지 손실**이 남아 있었다:

1. **Trace log는 쌓이는데 alias 확장이 수작업** → `_taxonomy_remap_trace.jsonl`
   unresolved 누적이 그대로 방치. "구조적 인플레" 같은 반복 phrase를 수동으로
   alias map에 옮기는 주기가 불규칙.
2. **Regime 판정식이 잘 동작하는지 눈으로만 봄** — `_regime_quality.jsonl`
   22 rows가 쌓였지만 집계해본 사람은 없음. threshold 조정이 필요한지
   판단할 근거가 없음.
3. **Entity page에 graph 기반 draft 정보가 섞여 들어감** — 기사 수 같은
   "확정 사실"과 GraphRAG 전이경로 같은 "draft evidence"가 같은 bullet 목록에
   혼재 → 읽는 사람이 어디까지 신뢰할지 판단 불가.

이 세 가지는 전부 **기능 신설이 아니라 운영 투명성 개선**이다. 따라서
v13은 새 rule, 새 threshold, 새 write path를 추가하지 않는다. 대신:

- alias 확장을 "제안 → 검토 → yaml 승인" 루프로 절차화한다
- 판정식 동작을 14일 단위로 집계한다 (집계만, 변경 없음)
- entity page는 `status: base` 유지하면서 body 섹션만 재구성한다

이게 v13을 "확장"이 아닌 "안정화"로 부르는 이유다.

---

## 4. Alias를 왜 propose-only로 설계했는지

지시서 원문: "기본 동작은 '제안만 생성'이어야 하며 PHRASE_ALIAS를 자동
수정하면 안 된다. 별도 approved mapping 파일이 있을 때만 apply 가능하게
만들 것."

이 제약은 3가지 이유로 엄격하게 지켰다:

### 4.1 과거 phrase 유입 사건의 재발 방지

v10 이전에 debate가 `dominant_narrative`를 서술형으로 직접 덮어쓰던 시기,
"지정학 완화" · "구조적 인플레" 같은 설명형 phrase가 `topic_tags`에
유입되어 regime 판정을 흐렸다. v11 taxonomy contract로 차단했고, 지금도
`_taxonomy_remap_trace.jsonl`에는 "단기 랠리와 장기 리스크의 불일치" 같은
문장형 phrase가 unresolved로 남아 있다 (§7 참조).

자동 alias 확장은 이런 phrase를 "가장 가까운 taxonomy"로 밀어붙이는 압력을
만든다. 결과적으로 contract가 말로만 있고 실제로는 완화되는 구조가 된다.
그래서 propose-only — 제안은 쌓되, 매핑 결정은 반드시 사람이 한다.

### 4.2 Runtime merge는 setdefault (builtin 우선)

`taxonomy._load_approved_alias()`는 yaml에서 읽은 매핑을
`PHRASE_ALIAS.update()`가 아닌 `PHRASE_ALIAS.setdefault()`로 머지한다.
즉 이미 builtin에 존재하는 phrase는 **절대 override되지 않는다**.
이는 builtin PHRASE_ALIAS를 "금과옥조"로 남기고 yaml은 "추가만 가능한
overlay"로 취급하기 위함이다. `--apply`는 이 충돌을 감지해서 REJECTED로
출력한다.

### 4.3 Apply는 validator, 아니라 mutator

`--apply`는 yaml을 읽어서 어떤 entry가 어떻게 처리될지 preview만 출력한다.
실제 PHRASE_ALIAS는 yaml 파일 존재 자체가 source of truth — 다음 import
시점에 loader가 자동으로 overlay한다. `--apply`의 존재 이유는 "yaml이
문법적으로 올바른가" + "taxonomy 규칙을 위반하지 않는가" + "builtin과
충돌하지 않는가"를 알려주는 dry-run이다.

**결과**: yaml을 실수로 잘못 써도, taxonomy 외 값이나 충돌 entry는 loader가
silently drop하고, `--apply --strict`가 exit 1로 실패한다. taxonomy.py
소스는 어떤 경우에도 자동 수정되지 않는다.

---

## 5. Regime threshold를 왜 안 건드렸는지

v12.1 리뷰에서 명시된 "다음 배치 P0 중 하나"는 **regime 판정식 실전 모니터링
2주**였다. 단, 2주 데이터를 쌓기 전에 threshold를 조정하는 것은 **해결된
적 없는 문제를 미리 수정**하는 것과 같다.

### 5.1 초기 baseline 해석 (first packet cut)

아래 baseline 수치는 첫 집계 시점(22 rows) 기준의 설명이고, 최신 재실행
결과는 §7.2 실행 샘플(40 rows)로 갱신되었다. 해석의 **방향성은 동일**하나
**최종 숫자는 §7.2를 우선**한다. 본 섹션의 수치는 "왜 threshold를 건드리지
않았는지"라는 논리 전개용 baseline snapshot으로만 읽어주길 바란다.

- 유효 row: 22
- `shift_confirmed`: 1
- `shift_candidate` only: 7
- `empty_tag_days` (baseline 용어; 현재는 `empty_tag_rows`): 8
- `avg coverage_current`: 0.0833 / `avg coverage_today (core_top3)`: 0.0
- churn proxy (confirmed/candidate_row): **0.125**

churn proxy 0.125는 row-level 관찰에서 "candidate row 8건 중 confirmed 1건"
이라는 뜻이다. 이는 candidate가 쉽게 confirmed로 승격되지 않고 있다는
**운영 신호**에 가깝고, day-level "3일 연속 guard"가 설계대로 작동했음을
단언하는 근거로는 충분하지 않다 (동일 날짜 multi-append 로그이므로 day-level
consecutive 평가가 불가). 이 상태에서 threshold를 완화하면 false positive가
늘어난다. 보수적 운영이 맞는지는 `unique_dates_in_window`가 실질적으로
누적된 뒤(≥14 unique dates) false negative 분포를 확인하고 판단할 일이다.

따라서 v13은:
- `_step_regime_check`의 0.5 / core_top3 / sentiment_flip 기준을 건드리지 않음
- cooldown 14일도 그대로
- 3일 연속 확정 조건 그대로
- `tools/regime_monitor.py`는 **집계만** 수행

리스크: 2주 관측 기간이 지나도 운영자가 집계 리포트를 안 본다면 이
투자는 낭비된다. 대응책: `regime_monitor_summary.md`를 review packet의
실제 샘플 출력 섹션(§7.2) 옆에 항상 끼워넣어 리뷰어가 놓치지 않게 한다.

---

## 6. Entity page에서 canonical/draft를 어떻게 분리했는지

### 6.1 결정: status 필드는 늘리지 않는다

사용자와의 사전 합의: **frontmatter status는 `base` 유지, body 섹션 헤더 +
source badge로 분리**. 새 status 값을 추가하면 base/draft/canonical이라는
3-tier 의미가 다시 헷갈린다. 여기서 필요한 건 "페이지 lifecycle 변경"이
아니라 "페이지 내부 섹션의 출처 구분"이다.

### 6.2 섹션 구조

```
# Entity — {label}
Canonical label / Topic / Graph node (header)

## Confirmed facts  _[source: `pipeline_refine`]_
- Mentioned in N articles
- Linked events
- Related asset classes (derived)
- Related funds (future batch)
### Recent articles

## Draft evidence  _[source: `07_Graph_Evidence` · draft]_
> Do NOT treat as confirmed regime signal.
### Graph adjacency (top 5)
### Transmission paths involving this node

## Provenance
- Graph node / Confidence proxy / 경계 안내
```

### 6.3 보조 frontmatter 두 필드

선택적으로 `has_draft_evidence: true|false` + `draft_sources: [graph_evidence]`
(후자는 true일 때만). downstream 파서가 섹션 파싱 없이도 "이 페이지에
draft 블록이 있는가?"를 판별할 수 있게 한다. status를 늘리지 않는
대안이다.

### 6.4 Media entity는 draft 섹션이 빈다

`source__연합인포맥스` 같은 매체 entity는 `graph_node_id`가 없으므로
Draft evidence 섹션이 "_Not applicable — media entity, no graph node
attached._"로 비워진다. `has_draft_evidence: false`. 이는 설계 의도대로.
미디어를 graph 기반 분석 대상이 아니라 정보원(tier-quality에만 반영)으로
유지한다.

### 6.5 Stable page id

entity_id는 `source__{매체명}` 또는 `graphnode__{node_id}` — v12.1의
3 demo entity (`graphnode__유가/환율/달러`)와 파일명이 1:1 대응된다. rerun
시 같은 파일을 overwrite하며 새 파일이 생기지 않는다 (test case 4 증거).

---

## 7. 실제 샘플 출력 1개씩

### 7.1 Alias candidate report (실제 생성물)

경로: `data/report_output/alias_candidates_report.md` (발췌)

```markdown
# Alias candidates report

- Generated: `2026-04-17T14:28:15`
- Source: `data/report_output/_taxonomy_remap_trace.jsonl`
- Total trace rows: **31**
- Match type counts: exact=3, alias=18, unresolved=10

## Unresolved phrases (propose candidates)

| phrase | count | sources | suggested tag | score | action |
|---|---|---|---|---|---|
| `에너지 인플레이션 압박의 긴장.` | 1 | history[5] | 물가_인플레이션 | 0.90 | review_needed |
| `구조적 유가 급등의 불안정한 균형` | 1 | history[4] | 에너지_원자재 | 0.60 | review_needed |
| `구조적 인플레 딜레마` | 1 | history[1] | 물가_인플레이션 | 0.60 | review_needed |
| `에너지 인플레 압력 교차` | 1 | history[2] | 물가_인플레이션 | 0.30 | keep_unresolved |
| `유가 구조적 충격의 줄다리기` | 1 | history[11] | 에너지_원자재 | 0.30 | keep_unresolved |
| `유가 인플레 충격` | 1 | history[3] | 물가_인플레이션 | 0.30 | keep_unresolved |
| `이란 위기` | 1 | history[7] | 지정학 | 0.30 | keep_unresolved |
| `인플레 압력의 불확실성 충돌` | 1 | history[6] | 물가_인플레이션 | 0.30 | keep_unresolved |
| `인플레·성장 둔화의 불확실성 충돌` | 1 | history[0] | 물가_인플레이션 | 0.30 | keep_unresolved |
| `단기 랠리와 장기 리스크의 불일치` | 1 | regime_current | — | — | keep_unresolved |
```

**해석**:
- `propose_alias`: 0건 — 대부분 phrase가 count=1 (최근 1회만 등장)이라
  "신뢰도 ≥ 0.4 + count ≥ 2" 조건을 통과하지 못한다. 설계대로 보수적.
- `review_needed`: 3건 — 점수는 있으나 count=1이므로 사람 검토 필요.
- `keep_unresolved`: 7건 — 힌트가 약하거나 거의 문장 수준. 강제 매핑 금지.

### 7.2 Regime monitor summary (실제 생성물 — source of truth)

경로: `data/report_output/regime_monitor_summary.md` (실행: 2026-04-17T15:06)

본 섹션 수치가 **최신 재실행 결과**이며, §5.1의 baseline과 수치가 다를 경우
**여기 수치를 우선**한다.

```markdown
# Regime monitor summary

- Generated: `2026-04-17T15:06:16`
- Source: `data/report_output/_regime_quality.jsonl`
- Window: `2026-04-04` ~ `2026-04-17` (14 days)
- Source rows: 40  (window rows: 40, malformed skipped: 0)

> `source_rows` = 전체 집계 대상 row 수. `window_rows` = 윈도우 내 row.
> `unique_dates_in_window` = 실제 관측 일수. 동일 날짜에 여러 row가
> append될 수 있으므로 row 수와 관측 일수는 다를 수 있다.
> 지표 이름에 `_rows`가 붙은 것은 모두 **row-level count**이며,
> day-level 해석은 `unique_dates_in_window`가 충분히 커진 뒤에만
> 의미를 가진다.

## Aggregate indicators (row-level operational observation)

| indicator | value |
|---|---|
| source_rows | 40 |
| window_rows | 40 |
| unique_dates_in_window | 1 |
| malformed_skipped | 0 |
| shift_candidate_rows | 14 |
| shift_confirmed_count | 1 |
| sentiment_flip_rows | 13 |
| cooldown_block_rows | 14 |
| sparse_fallback_rows | 12 |
| empty_tag_rows | 14 |
| avg coverage_current | 0.0833 |
| avg coverage_today (core top3) | 0.0 |
| churn proxy (confirmed / candidate_row) | 0.0714 |

## consecutive_row_streak distribution

| consecutive_row_streak | rows |
|---|---|
| 0 | 26 |
| 1 | 13 |
| 3 | 1 |

## candidate_rule distribution

| rule | count |
|---|---|
| `low_coverage_today` | 36 |
| `low_coverage_current` | 30 |
| `sentiment_flip` | 13 |
```

**숫자 해석 주의 (row vs day)**:
- `source_rows: 40` ≠ `unique_dates_in_window: 1`. 현재 운영 단계에서
  `_step_regime_check`가 같은 날짜에 복수 시나리오·테스트·디버그 append를
  생성하므로, row 수와 실제 관측 일수는 자리수가 다르다.
- `window_days: 14`는 윈도우 **폭**이고, `unique_dates_in_window: 1`은
  그 윈도우 안에 실제로 기록된 **관측 일수**다. 2주 실전 누적 전에는
  `unique_dates_in_window`가 `window_days`에 접근하지 못하는 것이 정상.
- 지표 이름 `_rows`가 붙은 것은 전부 **row 기준 count**다.
  `consecutive_row_streak`는 연속된 jsonl row 개수이지 연속된 **날짜** 수가
  아니다. 따라서 v12의 "3-day consecutive guard"가 실제 일자 기준으로
  firing했는지를 이 표에서 단언할 수 없다.

**해석 (row-level 기준, 보수적)**:
- 현재 샘플은 동일 날짜 복수 append가 많아 day-level 판정보다는 **row-level
  운영 신호 관찰**에 가깝다.
- `candidate row 14건 중 confirmed 1건`(churn proxy 0.0714) — 현재 로그
  기준에서는 candidate가 쉽게 확정으로 승격되지 않음을 확인할 수 있다.
- `consecutive_row_streak` 분포상 대부분의 row(26/40)는 후보조차 아니며,
  이는 현 시점 판정식이 **보수적으로 동작하고 있음을 시사**한다.
- `sparse_fallback_rows 12건` — single-tag 상태에서 `sentiment_flip` 여부가
  candidate 판정을 좌우한 케이스들. sentiment_flip이 없으면 hold로 잡히는
  패턴이 row 단위로 확인된다.
- **단**, `unique_dates_in_window=1`이므로 true day-level churn / false-negative
  평가는 **2주 실전 누적 후 재판단** 대상이다. 위 해석은 어디까지나 row-level
  운영 관측이지 day-level regime drift 진단이 아니다.

### 7.3 Entity demo page (실제 생성물)

경로: `data/wiki/02_Entities/2026-04_graphnode__유가.md` (전체)

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
has_draft_evidence: true
draft_sources: [graph_evidence]
source_of_truth: pipeline_refine
updated_at: 2026-04-17T14:39:28
---

# Entity — 유가

**Canonical label**: `유가`
**Topic**: `news` · **Graph node**: `유가`

## Confirmed facts  _[source: `pipeline_refine`]_

- Mentioned in **6** articles this period
- Linked events: `event_12`, `event_29`, `event_35`, `event_39`, `event_44`
- Related asset classes (derived): `원자재`
- Related funds: —  _(populated in a later batch)_

### Recent articles
- [경제 안테나] 원유가 충격과 인플레, 그리고 금리
- "중동전쟁에 경기 하방위험 커져...물가·민생부담 확대 우려"
- 트럼프 "이란전 순조롭게 진행" 발언에…국제유가 하락 전환
- 미-이란 협상 교착… 호르무즈 해협 봉쇄 우려에 국제유가 2%대 상승
- 이란 전쟁 종료 기대에 국제 유가 하락
- 트럼프 약발 끝?...장중, 아시아 6개국 증시 '일제히 하락'

## Draft evidence  _[source: `07_Graph_Evidence` · draft]_

> Adjacency and transmission paths below are **draft evidence** produced
> by GraphRAG. Do NOT treat as confirmed regime signal.
> Canonical regime lives in `05_Regime_Canonical/`.

### Graph adjacency (top 5)
- ← `원유_선물_가격_급등`  (causes, w=0.83)
- ← `국제유가`  (correlates, w=0.69)
- ← `공급_차질_우려_심화`  (causes, w=0.66)
- → `에너지·소재_기업_수익성_변화`  (causes, w=0.63)
- → `에너지_비용_상승`  (causes, w=0.45)

### Transmission paths involving this node
- trigger `지정학` → target `유가`: `지정학적_리스크_상승` → `중동_산유국_공급_불안` → `원유_선물_가격_급등` → `유가`  (conf=0.79)
- trigger `유가_급등` → target `유가`: `유가_급등_압력` → `국제유가`  (conf=0.66)
- trigger `지정학` → target `유가`: `중동_지정학적_불안_고조` → `유가_상승_우려`  (conf=0.64)
- trigger `유가_급등` → target `유가`: `유가_급등_압력` → `국제유가` → `유가`  (conf=0.44)

## Provenance

- Base entity: `pipeline_refine` (daily_update Step 2.5 / 2.6)
- Graph node: `유가`
- Confidence proxy (node severity): `neutral`

> Base page. Canonical regime → `05_Regime_Canonical/`. Debate commentary → `06_Debate_Memory/`. Full transmission paths → `07_Graph_Evidence/`.
```

**해석**:
- Confirmed facts는 `pipeline_refine` 출처 배지로 라벨됨 — 기사 수, 이벤트,
  자산군 등 **집계된 사실**.
- Draft evidence는 `07_Graph_Evidence · draft` 배지 + 경고 blockquote —
  GraphRAG 결과가 여기 격리됨.
- Related asset classes `원자재`는 `유가` → `에너지_원자재` (taxonomy
  매핑) → `_ASSET_TOPIC_MAP` reverse로 자동 도출.
- Transmission path 4개 중 2개가 "유가 → 유가" self-loop에 가까워 보이는데,
  이는 P1에서 dynamic target으로 `유가` 노드가 활성화됐기 때문.
  canonical 승격 없이 draft로만 노출되므로 설계 경계 준수.

---

## 8. 리뷰 요청 체크리스트

- [ ] approved yaml loader가 setdefault로 builtin을 override하지 않는가
  (**§4.2, test_alias_review case 3+4**)
- [ ] `--apply --strict`가 non-taxonomy 값에 대해 exit 1로 실패하는가
  (**test_alias_review case 2**)
- [ ] trace가 없는 환경에서도 `--propose`가 crash하지 않는가
  (**test_alias_review case 5, 단 trace 없으면 skip**)
- [ ] `regime_monitor`가 malformed row를 skip + warn하는가
  (**test_regime_monitor case 2**)
- [ ] summary가 idempotent인가 (**case 4**)
- [ ] empty window가 zero summary를 반환하는가 (**case 1**)
- [ ] v12 판정식 로직에 코드 변경이 없는가 (**§2 변경 없음 확인, §5**)
- [ ] Entity page의 Confirmed vs Draft 섹션 분리가 시각적으로 충분한가
  (**§7.3 샘플 + test_entity_demo_render**)
- [ ] media entity가 draft 섹션에서 N/A로 graceful하게 표시되는가
  (**case 2**)
- [ ] stable page id가 rerun 간 유지되는가 (**case 4**)
- [ ] 기존 회귀 PASS (**§9**)

---

## 9. 회귀 테스트 결과 + 실행 증거

**실행 환경** (2026-04-17 세션):
- Branch: `feature/insight-v13` @ commit `e91e410` (v13 #4 시점 기준)
- Python: 3.14.3 · Platform: win32 (Windows 11)
- 실행 시각: 2026-04-17 14:54 ~ 14:55 KST
- pytest 미설치 → 기존 관행인 `python -m market_research.tests.<name>` 방식으로 실행

**실행 증거 (실제 출력 핵심 1~2줄만)**:

```
$ python -m market_research.tools.alias_review --propose
  total trace rows: 31
  unresolved unique phrases: 10  (keep_unresolved: 7, review_needed: 3)
  → wrote alias_candidates.json + alias_candidates_report.md

$ python -m market_research.tools.alias_review --apply --strict
  accepted (new aliases): 0   keep_unresolved entries: 0
  exit=0   (approved yaml is empty seed)

$ python -m market_research.tools.regime_monitor --days 14
  window: 2026-04-04 ~ 2026-04-17 (14 days)
  source_rows: 40  window_rows: 40  unique_dates_in_window: 1
  shift_candidate_rows: 14  shift_confirmed_count: 1
  churn proxy (confirmed / candidate_row): 0.0714
  → wrote regime_monitor_summary.{json,md}

$ python -m market_research.tests.test_alias_review
  5 PASS (case1..case5), exit=0

$ python -m market_research.tests.test_regime_monitor
  5 PASS — case5: live file scan consistent (confirmed=1, window_rows=40)
  exit=0

$ python -m market_research.tests.test_entity_demo_render
  5 PASS (case1..case5), exit=0

$ python -m market_research.tests.test_taxonomy_contract
  3 PASS (case1 overlap=3, case2 phrase blocked, case3 empty hold)

$ python -m market_research.tests.test_regime_decision_v12
  4 PASS (case_a ~ case_d)

$ python -m market_research.tests.test_graphrag_p0_vs_p1 2026-04
  total_paths   P0 2 → P1 6
  unique_trig   P0 2 → P1 4   (configured 4/9, active 4/6)
  unique_tgt    P0 2 → P1 3   (configured 3/10, active 3/5)
  avg_conf      P0 0.544 → P1 0.532
```

**집계**: 기존 회귀 3종 **10 케이스 모두 PASS**, 신규 3종 **15 케이스 모두
PASS**. GraphRAG P0→P1 metric 회귀 수치 변동 없음.

---

## 10. 남은 리스크

| 리스크 | 심각도 | 이유 | 다음 배치 |
|--------|-------|------|-----------|
| Unresolved phrase 대부분이 count=1 → propose_alias 후보 0건 | Low | 설계대로 (보수화 우선). 2주 이상 누적 뒤 재평가 | 누적 후 재검토 |
| regime 판정식 실전 증거가 여전히 `unique_dates_in_window=1` 수준 (같은 날짜 append 다수) | Med | 현재 monitor summary는 day-level regime drift 판단보다 **row-level append/debug 관측** 성격이 강하다. 지표 이름(`_rows`, `consecutive_row_streak`)도 row 기준으로 맞춰져 있고, 실전 threshold 판단은 `unique_dates_in_window`가 실질적으로 누적된 뒤 수행해야 한다 | 운영 스케줄 정착 + unique date 누적 후 재평가 |
| Entity redesign이 3 demo에만 적용 — top_entities=5 설정에서도 media 5건 + graphnode 3건 = 8건 | Low | 설계대로 (demo 기반 회귀 안정성 우선) | 전면 entity redesign 시 graphnode 선정 기준 재정비 |
| `_ASSET_TOPIC_MAP`이 7개 자산만 매핑 → "Related asset classes" 대부분 빈 값 | Low | v14에서 자산 매핑 테이블 확장 | 별도 배치 |
| Related funds 라벨이 placeholder | Low | 지시서에서 미요구 — docs/entity_page_redesign §2 해결은 다음 배치 | 다음 배치 |
| `regime_monitor`가 daily_update와 연동되지 않음 — 사람이 CLI 실행해야 함 | Low | 당장은 의도. Streamlit admin이나 cron 연동은 2주 뒤 재평가 | 별도 연동 배치 |
| self-loop성 draft transmission path 노출 가능 (예: `유가 → 유가`) | Low | P1 dynamic target이 entity node와 가까울 때 draft evidence에 유사 self-loop 경로가 표시될 수 있음. 현재는 `07_Graph_Evidence`/Draft 섹션에만 격리되어 canonical 오염은 없고, draft badge + 경고 blockquote로 노출 의미도 명시됨 | target dedupe / path presentation cleanup 검토 (canonical 승격 금지 유지) |

---

## 11. 다음 배치 제안

### 반드시 할 것

1. **regime 판정식 실전 2주 누적 후 집계 재실행** — `regime_monitor --days 14`
   을 daily batch 마지막 단계나 주간 검토에 끼워넣는다. 14일 실제 데이터
   기반으로 threshold 조정 여부 결정.
2. **alias propose 후 실제 승인 1회 순환** — `phrase_alias_approved.yaml`에
   최소 1개 항목 추가 → `--apply --strict` → runtime merge 확인. 이 루프가
   실전에서 돌아가는지 증명.

### 하면 좋은 것

1. `regime_monitor`를 `daily_update` Step 5.5로 연동 (선택) — 매일 summary
   갱신. 리뷰어가 별도 실행 안 해도 항상 최신.
2. Entity page redesign을 graphnode top-3 → top-10으로 확장 — 단,
   alias dict 안정화가 선결되어야 labels 품질이 보장됨.

### 하지 말 것

1. **regime threshold 조정** — 2주 실전 데이터 없이 금지.
2. **alias 자동 apply** — propose-only 설계 유지.
3. **draft evidence를 entity frontmatter에 confirmed처럼 노출** — badge
   유지.
4. **graphnode entity를 대량 생성** — severity_weight 기준 자체가 현재
   미완 (노드 일부가 severity_weight 미기재). 기준 정비가 선결.

---

**총평: packet 기준 pass-leaning.** 최종 pass는 코드 diff 및 §9 실행 증거
재확인 전제. 방향성·범위 통제·고정 규칙 준수 모두 문서 기준으로는
명료하지만, 이 패킷 자체는 review packet이지 code diff가 아니므로
"final pass"를 단정하지 않는다.

---

## Revision note

- **v13 → v13.1 (2026-04-17 14:55 KST)**:
  총평 톤 조정 (pass → pass-leaning, packet 기준). regime_monitor 필드
  분리 (`source_rows` / `window_rows` / `unique_dates_in_window` /
  `malformed_skipped`; `total_days` 제거) 및 §7.2 수치 재측정. §5의 죽은
  참조(`B. 로그 샘플`) → `§7.2` 교정. §9에 실제 실행 커맨드 + 핵심 출력 +
  실행 환경 메타 추가. §10 리스크 표에 self-loop성 draft path 행 추가.
  §1에 "packet 기준 판정 요청" 문구 추가.

  코드 변경 (패킷 외부):
  - `tools/regime_monitor.py`: 출력 필드 rename + `unique_dates_in_window`
    계산 추가. 판정식 로직 무변경.
  - `tests/test_regime_monitor.py`: 필드명 교체. 5/5 PASS 유지.

- **v13.1 → v13.2 (2026-04-17 15:06 KST)** — 패킷 신뢰도 마감:
  - `regime_monitor` 지표 명명을 **row-level**로 정리: `shift_candidate_days`
    → `shift_candidate_rows`, `empty_tag_days` → `empty_tag_rows`,
    `sentiment_flip_count` → `sentiment_flip_rows`, `cooldown_block_count`
    → `cooldown_block_rows`, `sparse_fallback_count` → `sparse_fallback_rows`,
    `consecutive_days_distribution` → `consecutive_row_streak_distribution`,
    `churn_proxy_...candidate` → `churn_proxy_...candidate_row`.
    `shift_confirmed_count`는 의미가 명확하므로 그대로 유지. 섹션 제목
    `Aggregate indicators (observation only)` → `Aggregate indicators
    (row-level operational observation)`.
  - §7.2 해석 문장에서 "3일 연속 guard가 설계대로 작동" 같이 day-level을
    단언하던 표현을 **row-level 보수 톤**으로 교체. `unique_dates_in_window=1`
    이므로 day-level 해석은 불가능하다는 경고를 명시.
  - §5에 **5.1 초기 baseline 해석 (first packet cut)** 서브섹션 추가.
    baseline 수치(22 rows)와 §7.2 최신 수치(40 rows)의 관계를 명시하고,
    **최종 숫자는 §7.2를 우선**으로 고정.
  - §1 판정 요청 블록에 "regime_monitor는 row-level operational summary로
    읽어달라"는 한 줄 추가.
  - §10 리스크 문구도 row/day 구분에 맞춰 보강 ("monitor summary는 day-level
    drift 판단보다 row-level append/debug 관측 성격이 강하다").
  - §9 실행 증거의 수치도 최신 재실행(40 rows) 기준으로 갱신.

  코드 변경 (패킷 외부):
  - `tools/regime_monitor.py`: summary/CLI/Markdown 전부 row-level naming
    반영. 판정식/threshold/writer 경계 전부 불변.
  - `tests/test_regime_monitor.py`: case 1의 필드 튜플을 `_rows` 접미사로
    교체. 5/5 PASS 유지.
