# Review Packet v11 — Taxonomy Contract Fix + GraphRAG P0

> 작성일: 2026-04-17
> 범위: topic_tags taxonomy 강제, narrative/tag 분리, _step_regime_check 강화,
>       용어 통일(base pages), GraphRAG Phase 3 P0, entity page redesign 설계
> 이전: v10 (canonical/draft 분리 + regime writer 단일화 + wiki 2-tier)

---

## Part I. v10 유지 / 수정 / 미룬 점

### ✅ v10에서 유지

- canonical/draft wiki 2-tier 디렉토리 분리 (`00_Index`~`07_Graph_Evidence`)
- debate engine의 `regime_memory.json` 직접 쓰기 제거
- regime canonical writer는 `daily_update._step_regime_check` 단일화
- `regime_memory.json = machine SSOT`, canonical page = read model/projection
- debate 결과는 `06_Debate_Memory/` draft-tier에만 축적
- cooldown(14일) / weeks 자동 계산 / history guard / `_regime_quality.jsonl`

### 🔧 v10에서 수정

| 이슈 | 수정 내용 |
|------|-----------|
| `topic_tags`에 서술형 phrase 유입 (`"지정학 완화"`) | taxonomy contract 강제 — TOPIC_TAXONOMY 14 labels만 허용 |
| `narrative_description`이 `dominant_narrative`로 덮어쓰이는 버그 | `narrative_description` 보존 로직 추가 (idempotent migration) |
| Step 5 overlap이 서술형 phrase 기준 | exact taxonomy intersection만 사용 (`tag_match_mode: exact_taxonomy`) |
| empty `topic_tags` 상태에서 shift 후보 자동 생성 | 보수화 — empty면 shift 보류 + warning |
| `_regime_quality.jsonl` 필드 부족 | `current_topic_tags`, `top_topics_today`, `unknown_or_non_taxonomy_tags`, `tag_match_mode`, `shift_reason` 추가 |
| 용어 혼용 ("draft pages" vs "canonical draft pages") | `base pages`로 통일 (01~04) |
| GraphRAG transmission path 중복/self-loop/오매칭 | P0 적용: word-boundary 매칭 + self-loop 필터 + pair당 1경로 |

### ⏭ 다음 배치로 미룬 점

- GraphRAG **P1** (dynamic trigger/target, alias dict, embedding fallback)
- Selected transmission path → canonical asset page 승격 (Phase 4+)
- **Entity page redesign** — GraphRAG 노드 연동 구현 (설계만 완료, `docs/entity_page_redesign.md`)
- graphify 외부 뷰어 연동 (Phase 4+)

---

## Part II. Taxonomy Contract 전후 비교

### TOPIC_TAXONOMY (14개, SSOT)

`market_research/analyze/news_classifier.py::TOPIC_TAXONOMY`에서 import.

```
통화정책, 금리_채권, 물가_인플레이션, 경기_소비, 유동성_크레딧,
환율_FX, 달러_글로벌유동성, 에너지_원자재, 귀금속_금, 지정학,
부동산, 관세_무역, 크립토, 테크_AI_반도체
```

### Before (v10)

```yaml
dominant_narrative: "지정학 완화 + 구조적 인플레 + 단기 랠리와 장기 리스크의 불일치"
topic_tags: ["지정학 완화", "구조적 인플레", "단기 랠리와 장기 리스크의 불일치"]
# ↑ taxonomy도 아니고 free-text도 아닌 phrase — Step 5 overlap 항상 0
```

### After (v11)

```yaml
tag_match_mode: exact_taxonomy
dominant_narrative: "지정학 + 물가_인플레이션"
topic_tags: ["지정학", "물가_인플레이션"]                                       # exact taxonomy only
narrative_description: "지정학 완화 vs 구조적 인플레: 단기 랠리와 장기 리스크의 불일치"  # 서술형 원문 보존
```

**Step 5 overlap 효과**:

| 상황 | v10 overlap | v11 overlap |
|------|------------|------------|
| `top_topics = ['지정학','환율_FX','에너지_원자재',...]` <br> vs `tags=['지정학 완화','구조적 인플레','단기 랠리...']` | **0** (phrase 매칭 실패) | **1** (지정학 exact match) |

→ false shift candidate 감소.

---

## Part III. Migration Summary (v11)

### 실행

```bash
python -m market_research.tools.migrate_regime_v11
```

백업: `regime_memory.json.bak` (v10에서 생성된 원본) → 복원 후 v11 규칙으로 재정규화.

### Summary (`_migration_v11_summary.json`)

```json
{
  "current": {
    "before_topic_tags": [],
    "before_non_taxonomy_count": 0,
    "after_topic_tags": ["지정학", "물가_인플레이션"],
    "unresolved": ["단기 랠리와 장기 리스크의 불일치"]
  },
  "history_entries_normalized": 12,
  "history_with_tags": 12,
  "history_unresolved_only": 0,
  "debate_pages_updated": 1,
  "debate_pages_with_taxonomy_tags": 1,
  "debate_pages_unresolved_only": 0,
  "total_remapped_phrases": 21,
  "total_unresolved_phrases": 10
}
```

| 항목 | 값 |
|------|-----|
| Current regime — 매핑된 taxonomy tag | 2 (지정학, 물가_인플레이션) |
| Current regime — 매핑 실패 phrase | 1 (단기 랠리와 장기 리스크의 불일치) |
| History 정규화 entry | 12 / 12 |
| History 중 taxonomy 매핑 성공 | 12 / 12 |
| History unresolved-only entry | 0 |
| Debate memory 페이지 업데이트 | 1 / 1 |
| 총 remap된 phrase | 21 |
| 총 unresolved phrase | 10 |

**unresolved 예시** (억지 매핑 금지 원칙):
- `"단기 랠리와 장기 리스크의 불일치"` — 시장 의견 서술이라 taxonomy 미매핑
- `"글로벌 위험자산 회피"`, `"외국인 자금 이탈"` — 현상 묘사, 14토픽과 직결 안 됨

모두 `_unresolved_tags`에 기록, shift 판정에서 배제.

---

## Part IV. 샘플 JSONL / MD

### `_regime_quality.jsonl` (2건)

```json
{"date":"2026-04-17","tag_match_mode":"exact_taxonomy","current_topic_tags":["물가_인플레이션","지정학"],"top_topics_today":["지정학","환율_FX","에너지_원자재","금리_채권","테크_AI_반도체"],"overlap_count":1,"overlap_ratio":0.2,"unknown_or_non_taxonomy_tags":[],"shift_candidate":true,"consecutive_days":1,"cooldown_active":false,"shift_confirmed":false,"shift_reason":"토픽 불일치 80% (상위: 지정학, 환율_FX, 에너지_원자재)"}
{"date":"2026-04-17","tag_match_mode":"exact_taxonomy","current_topic_tags":["물가_인플레이션","지정학"],"top_topics_today":["지정학","환율_FX","에너지_원자재","금리_채권","테크_AI_반도체"],"overlap_count":1,"overlap_ratio":0.2,"unknown_or_non_taxonomy_tags":[],"shift_candidate":true,"consecutive_days":2,"cooldown_active":false,"shift_confirmed":false,"shift_reason":"토픽 불일치 80% (상위: 지정학, 환율_FX, 에너지_원자재)"}
```

### `_transmission_path_quality.jsonl` (1건)

```json
{"date":"2026-04-17","tag_match_mode":"word_boundary","pairs_total":108,"pairs_with_path":2,"self_loops_skipped":2,"total_paths":2,"unique_triggers":2,"unique_targets":2,"triggers_active":["인플레","지정학"],"targets_active":["금리","유가"],"unmatched_triggers":["관세","금리_상승","달러_부족","레포","엔화","위안화","유가_급등"],"unmatched_targets":["KOSPI","SP500","국내주식","국내채권","금","원자재","통화","해외주식","해외채권","환율"],"avg_confidence":0.544}
```

**P0 효과**: 기존 v10 출력 **8개 path** (중복/self-loop/오매칭 포함) → v11 P0 **2개 path** (노이즈 제거).

P1이 없으므로 커버리지는 제한적 (trigger 2/9, target 2/12). Part VI 참조.

### `07_Graph_Evidence/2026-04_transmission_paths_draft.md`

```markdown
---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-04
total_paths: 2
node_count: 274
edge_count: 252
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-04-17T13:04:57
---

# Transmission Paths (DRAFT) — 2026-04

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `인플레` | `금리` | 0.298 | 인플레이션_압력_상승 → 기준금리_조정_검토 |
| 2 | `지정학` | `유가` | 0.791 | 지정학적_리스크_상승 → 중동_산유국_공급_불안 → 원유_선물_가격_급등 → 유가 |
```

### `05_Regime_Canonical/current_regime.md` (frontmatter 최종)

```yaml
---
type: regime
status: confirmed
tag_match_mode: exact_taxonomy
dominant_narrative: "지정학 + 물가_인플레이션"
topic_tags: ["지정학", "물가_인플레이션"]
narrative_description: "지정학 완화 vs 구조적 인플레: 단기 랠리와 장기 리스크의 불일치"
since: 2026-04-01
direction: neutral
weeks: 2
source_of_truth: daily_update
updated_at: 2026-04-17T13:00:35
---
```

### `06_Debate_Memory/2026-04__market_*.md` (frontmatter 최종)

```yaml
---
type: debate_memory
status: provisional
tag_match_mode: exact_taxonomy
fund_code: _market
period: 2026-04
debate_date: 2026-04-17T11:55:27
linked_regime_since: 2026-04-01
linked_regime_narrative: "지정학 + 물가_인플레이션"
linked_regime_description: "지정학 완화 vs 구조적 인플레: 단기 랠리와 장기 리스크의 불일치"
linked_regime_tags: ["지정학", "물가_인플레이션"]
source_of_truth: debate_engine
---
```

→ `linked_regime_tags`가 canonical snapshot의 **exact taxonomy tags와 일치**함.

---

## Part V. 파일 목록

### 신규 (4개)

| 파일 | 줄수 | 역할 |
|------|------|------|
| `market_research/wiki/taxonomy.py` | ~170 | TOPIC_TAXONOMY 재수출 + PHRASE_ALIAS + extract/validate utils |
| `market_research/wiki/graph_evidence.py` | ~60 | `07_Graph_Evidence/` draft 페이지 writer |
| `market_research/tests/test_taxonomy_contract.py` | ~130 | 3케이스 테스트 (정상/phrase 유입/empty) |
| `market_research/tools/migrate_regime_v11.py` | ~130 | v11 규칙으로 regime/history/debate-page 재마이그레이션 |

### 수정 (5개)

| 파일 | 주요 변경 |
|------|-----------|
| `market_research/wiki/canonical.py` | `normalize_regime_memory`: taxonomy 강제, narrative_description 보존, unresolved 기록. frontmatter에 `tag_match_mode/narrative_description` 추가 |
| `market_research/wiki/debate_memory.py` | frontmatter에 `tag_match_mode`, `linked_regime_description` 추가. linked_regime_tags는 taxonomy 이중 검증 |
| `market_research/wiki/draft_pages.py` | 용어 "draft pages" → "base pages". `refresh_base_pages_after_refine` 공식화 (alias 유지) |
| `market_research/pipeline/daily_update.py::_step_regime_check` | exact taxonomy intersection, empty tags fallback, quality log 필드 확장 (`tag_match_mode/unknown_or_non_taxonomy_tags/shift_reason`) |
| `market_research/analyze/graph_rag.py` | `_matches_keyword`(word-boundary), self-loop 필터, pair당 1경로, quality log, draft page 호출 |

### 자동 생성

| 경로 | 상태 |
|------|------|
| `regime_memory.json` | v11 정규화 완료 |
| `wiki/05_Regime_Canonical/current_regime.md` | taxonomy 2건 + description 보존 |
| `wiki/05_Regime_Canonical/regime_history.md` | 12 entry, topic_tags 컬럼 추가 |
| `wiki/06_Debate_Memory/*.md` | linked_regime_* 재생성 |
| `wiki/07_Graph_Evidence/2026-04_transmission_paths_draft.md` | P0 draft |
| `data/report_output/_regime_quality.jsonl` | 신규 필드 적용 append |
| `data/report_output/_transmission_path_quality.jsonl` | 신규 파일 (P0) |
| `data/report_output/_migration_v11_summary.json` | 마이그레이션 결과 |

---

## Part VI. P0 제한 및 P1 예정

P0의 한계 (의도된 상태):

| 지표 | v11 P0 | P1 목표 |
|------|--------|---------|
| 활성 trigger | 2/9 | ≥ 6/9 (또는 taxonomy 14개 기반으로 재설계) |
| 활성 target | 2/12 | ≥ 6/12 |
| self-loop | 0 (완전 제거) | 0 유지 |
| pair 중복 | 0 (완전 제거) | 0 유지 |
| 오매칭 | 0 (word-boundary) | 0 유지 |

P1 작업 (다음 배치):
1. **Dynamic trigger/target** — TOPIC_TAXONOMY의 14토픽 + 월별 salience 상위 노드로 대체
2. **Alias dict** — `"유가"` ↔ `"국제유가"` ↔ `"WTI"` ↔ `"원유"` 표준화
3. **Embedding fallback** — 부분 매칭 실패 시 multilingual embedding nearest-neighbor
4. **길이 다양성 보너스** — depth 3~4 경로 소폭 가점

---

## Part VII. 완료 기준 체크

| # | 기준 | 검증 | 결과 |
|---|------|------|------|
| 1 | `topic_tags`에 서술형 phrase가 더 이상 저장되지 않음 | case2 테스트 + migration 후 canonical page 확인 | ✅ `tags=['지정학', '물가_인플레이션']` 순수 taxonomy |
| 2 | Step 5 overlap이 taxonomy 기준으로 계산됨 | `_step_regime_check` + `_regime_quality.jsonl` `tag_match_mode="exact_taxonomy"` | ✅ |
| 3 | debate memory의 `linked_regime_tags`가 canonical exact tags와 일치 | 06_Debate_Memory/*.md frontmatter 확인 | ✅ `["지정학","물가_인플레이션"]` 일치 |
| 4 | 용어가 base pages로 통일 | draft_pages.py / 00_Index/index.md / review packet | ✅ "base pages" 단일 용어 |
| 5 | transmission path P0 적용 + draft evidence page 생성 | 2026-04 graph 재실행 + `07_Graph_Evidence/2026-04_transmission_paths_draft.md` | ✅ 8 → 2 path, draft page 생성 |
| 6 | graphify는 아직 붙이지 않음 | 외부 viewer 연동 없음 | ✅ Phase 4+로 보류 |

---

## Part VIII. 테스트

```bash
# 1) Taxonomy contract 3 케이스
python -m market_research.tests.test_taxonomy_contract
# Expected: all PASS

# 2) Migration 재실행
python -m market_research.tools.migrate_regime_v11

# 3) GraphRAG P0 검증
python -c "
import json
from pathlib import Path
from market_research.analyze.graph_rag import precompute_transmission_paths
from market_research.wiki.graph_evidence import write_transmission_paths_draft
g = json.load(open('market_research/data/insight_graph/2026-04.json', encoding='utf-8'))
paths = precompute_transmission_paths(g,
    quality_log_path=Path('market_research/data/report_output/_transmission_path_quality.jsonl'))
g['transmission_paths'] = paths
write_transmission_paths_draft(g, '2026-04')
"
# Expected: "전이경로 사전계산: 2개 (trigger 2/9, target 2/12, self-loop skip 2)"
```

---

## Part IX. 다음 배치 후보 (우선순위)

| # | 항목 | 근거 |
|---|------|------|
| 1 | GraphRAG P1 — dynamic trigger/target + alias dict | P0 커버리지 제한 해소 |
| 2 | Entity page redesign 구현 | 설계 완료 (`docs/entity_page_redesign.md`), P1 완료 후 착수 |
| 3 | `_regime_quality.jsonl` 월별 집계 + 대시보드 | 오탐률/churn 추적 |
| 4 | Selected transmission path → canonical 승격 | P1 완료 + 품질 확인 후 |
| 5 | graphify 외부 연동 | 2-tier 구조 안정화 후 |

---

*2026-04-17 | Taxonomy contract fix + GraphRAG P0 + base pages 통일 + entity page 설계 확정*
