# Review Packet v10 — LLM Wiki 2-Tier 분리 + Regime Canonical/Draft 구조화

> 작성일: 2026-04-17
> 범위: canonical/draft wiki 분리, regime writer 단일화, debate memory 페이지, regime_memory 정규화
> 이전: v9 (펀드 코멘트 자동생성 + debate 품질 개선 + UI 개편)

---

## Part I. 배경

### 문제 상황 (진단)

`market_research/docs/graphrag_transmission_paths_review.md` Part 2 참조.

1. **regime_memory.json 쓰기 경로 이중화** — daily_update와 debate_engine이 모두 직접 write → narrative churn
2. **history 데이터 오염** — 2026-04 한 달 12 entry, 기간 포맷 3종 혼용, 역순 존재
3. **태그형/서술형 혼재** — 같은 필드에 `"지정학 + 환율_FX"`와 `"휴전 완화 vs 유가 충격"` 공존
4. **3일 연속 규칙 우회** — debate 2회 실행으로 narrative 즉시 전환

### 설계 원칙

- **Canonical writer 단일화**: regime 확정은 `daily_update._step_regime_check`만
- **Wiki 2-tier**: canonical(05) vs debate memory(06) 디렉토리 분리
- **GraphRAG transmission path는 draft only**: P0/P1 개선 전까지 canonical 반영 금지
- **regime_memory.json = machine SSOT**, canonical wiki = read model/projection

---

## Part II. 핵심 변경

### 1. Wiki 디렉토리 구조 (신규)

```
market_research/data/wiki/
  00_Index/                   index.md (섹션 안내 + 조회 라우팅 순서)
  01_Events/                  정제 직후 생성 (event_group_id 단위)
  02_Entities/                정제 직후 생성 (매체/엔티티)
  03_Assets/                  정제 직후 생성 (8개 자산군)
  04_Funds/                   정제 직후 생성 (펀드별 메타)
  05_Regime_Canonical/        ★ daily_update만 writer
                              current_regime.md + regime_history.md
  06_Debate_Memory/           ★ debate engine만 writer (draft only)
                              {period}_{fund}_{ts}.md
  07_Graph_Evidence/          transmission path draft (현재 비어있음)
```

### 2. `market_research/wiki/` 패키지 (신규)

| 파일 | 역할 |
|------|------|
| `paths.py` | 디렉토리 상수 + 자동 생성 |
| `canonical.py` | `update_canonical_regime`, `normalize_regime_memory`, period/narrative 정규화 |
| `debate_memory.py` | `write_debate_memory_page` (provisional 페이지) |
| `draft_pages.py` | event/entity/asset/fund + index refresh |
| `__init__.py` | 공개 API |

### 3. Canonical regime 스키마

```yaml
---
type: regime
status: confirmed
dominant_narrative: "지정학 + 환율_FX + 에너지_원자재"   # 태그형만
topic_tags: ["지정학", "환율_FX", "에너지_원자재"]
since: 2026-04-17                                          # YYYY-MM-DD 통일
direction: bearish | bullish | neutral
weeks: 0                                                    # 자동 계산
source_of_truth: daily_update
---
```

서술형 narrative는 `narrative_description` 별도 필드 (canonical이지만 매칭에 사용 금지).

### 4. Debate memory 스키마

```yaml
---
type: debate_memory
status: provisional
fund_code: _market
period: 2026-04
debate_date: 2026-04-17T11:55:27
linked_regime_since: 2026-04-01                     # canonical snapshot 시점
linked_regime_narrative: "지정학 완화 + 구조적 인플레 + ..."
linked_regime_tags: ["지정학 완화", "구조적 인플레", ...]
source_of_truth: debate_engine
---
```

섹션: debate narrative / consensus / disagreements / tail risks / divergence from canonical.

### 5. `_step_regime_check` 리팩토링

`pipeline/daily_update.py`:

| 변경 | 내용 |
|------|------|
| 입력 정규화 | `normalize_regime_memory()` 호출 (포맷 통일 + history guard) |
| 매칭 방식 | free-text keyword split → **topic_tags 집합 교집합** |
| Cooldown | `MIN_REGIME_DURATION_DAYS = 14` — 전환 후 2주 재전환 잠금 |
| weeks | 자동 계산 `(today - since).days // 7` |
| direction | `delta.sentiment` (positive/negative/mixed)를 bullish/bearish/neutral로 매핑 |
| history | 전환 시 append + 최근 24건 보존 |
| canonical page | `update_canonical_regime()` 호출 (Step 5 마지막) |
| quality log | `_regime_quality.jsonl` append (overlap_count / shift_candidate / cooldown 등) |

### 6. `debate_engine.py` — regime write 제거

| 이전 | 이후 |
|------|------|
| `_update_regime_memory(agent_responses, year, month)` | `_summarize_debate_narrative(agent_responses)` |
| `regime_memory.json` write | ❌ (읽기 전용) |
| `history.append` | ❌ |
| `result['regime']` = 전체 regime dict | `result['debate_narrative']` = {narrative, canonical_snapshot, diverges} |
| print `"레짐 전환 감지"` | print `"debate 해석: ... (canonical과 상이)"` |

`run_market_debate` + `run_quarterly_debate` 양쪽 동일 적용.

### 7. `debate_service.py` — wiki 연동

`run_debate_and_save` 내부:
- `draft_data`에 `debate_narrative`, `canonical_regime_snapshot`, `diverges_from_canonical` 필드 추가
- `save_draft` + `append_evidence_quality` 뒤에 `write_debate_memory_page(draft_data, regime_file)` 호출
- 출력: `06_Debate_Memory/{period}_{fund}_{ts}.md`

### 8. Step 2.6 (신규) — 정제 직후 draft pages

`daily_update.py` Step 2.5 완료 직후:
```python
refresh_draft_pages_after_refine(month_str)
  → events (top salience group 5)
  → entities (매체 top 5)
  → assets (8개 자산군)
  → funds (08K88, 07G04 샘플)
  → 00_Index/index.md 재생성
```

조건: canonical regime / debate narrative / transmission path **포함 금지**.

### 9. regime_memory.json 정규화 (마이그레이션)

백업 → 정규화 → 저장:
- 백업: `regime_memory.json.bak` (생성됨)
- 날짜 포맷: 전부 `YYYY-MM-DD`로 통일
- history 역순 수정 (`2026-04 ~ 2026-03` → `2026-03-01 ~ 2026-04-01`)
- 연속 동일 narrative 자동 병합 (루트 로직)
- 서술형 narrative는 `narrative_description` 필드로 분리

---

## Part III. 파일 목록

### 신규 (5개)

| 파일 | 줄수 | 역할 |
|------|------|------|
| `market_research/wiki/__init__.py` | 30 | 패키지 공개 API |
| `market_research/wiki/paths.py` | 22 | 디렉토리 상수 + 자동 생성 |
| `market_research/wiki/canonical.py` | 200 | regime canonical writer + 정규화 |
| `market_research/wiki/debate_memory.py` | 95 | debate memory page writer |
| `market_research/wiki/draft_pages.py` | 250 | event/entity/asset/fund + index |

### 수정 (3개)

| 파일 | 주요 변경 |
|------|-----------|
| `market_research/pipeline/daily_update.py` | `_step_regime_check` 리팩토링, Step 2.6 추가, cooldown/weeks/quality log |
| `market_research/report/debate_engine.py` | `_update_regime_memory` → `_summarize_debate_narrative` (read-only), result 필드명 변경 |
| `market_research/report/debate_service.py` | debate memory 필드 + `write_debate_memory_page` 호출 |

### 자동 생성 (backfill 포함)

| 경로 | 파일 수 |
|------|--------|
| `wiki/00_Index/index.md` | 1 |
| `wiki/01_Events/` | 5 |
| `wiki/02_Entities/` | 5 |
| `wiki/03_Assets/` | 6 |
| `wiki/04_Funds/` | 2 |
| `wiki/05_Regime_Canonical/` | 2 (current + history) |
| `wiki/06_Debate_Memory/` | 1 (검증 runtime 생성) |
| `regime_memory.json.bak` | 1 (원본 백업) |

### 참고 문서

- `market_research/docs/graphrag_transmission_paths_review.md` — 진단 및 개선안 (Part 1 transmission path / Part 2 regime change)

---

## Part IV. 완료 기준 (지시서 기준 6개)

| # | 기준 | 검증 방법 | 결과 |
|---|------|-----------|------|
| 1 | debate 재실행이 canonical regime page를 바꾸지 않는다 | `current_regime.md` MD5 before/after | ✅ `8902b1cb0039e4d47f07037de5b8a96f` 동일 |
| 2 | canonical regime은 daily_update Step 5 이후에만 갱신된다 | debate_engine grep — write 없음 | ✅ `REGIME_FILE.write_text` 제거 확인 |
| 3 | debate 결과는 별도 memory/draft page에만 축적 | `06_Debate_Memory/` 생성 확인 | ✅ `2026-04__market_20260417T115527.md` |
| 4 | event/entity/asset/fund wiki는 정제 직후 생성 | Step 2.6에서 18건 생성 | ✅ events 5 / entities 5 / assets 6 / funds 2 |
| 5 | transmission path는 아직 draft evidence로만 저장 | `07_Graph_Evidence/` 내용 | ✅ 비어있음 (canonical 미반영) |
| 6 | topic_tags 기반 조회 가능 | frontmatter 확인 | ✅ `topic_tags: ["지정학 완화", ...]` 배열 존재 |

---

## Part V. 검증 세부

### A. Canonical 불변 테스트

```python
# BEFORE debate
MD5(current_regime.md) = 8902b1cb0039e4d47f07037de5b8a96f
regime_memory.current.dominant_narrative = "지정학 완화 + 구조적 인플레 + ..."

# debate 1회 실행 (2026-04, _market)
debate_narrative: "지정학 리스크 완화 vs 구조적 인플레이션 악화"
diverges_from_canonical: True
wiki: 06_Debate_Memory/2026-04__market_20260417T115527.md 생성

# AFTER debate
MD5(current_regime.md) = 8902b1cb0039e4d47f07037de5b8a96f   # ★ 동일
regime_memory.current.dominant_narrative = 동일              # ★ 동일
```

### B. Step 5 단독 동작

```python
delta.top_topics = ['지정학', '환율_FX', '에너지_원자재', '금리_채권', '테크_AI_반도체']
current.topic_tags = ['지정학 완화', '구조적 인플레', '단기 랠리와 장기 리스크의 불일치']

→ overlap = 0 / 5
→ shift_candidate = True
→ consecutive_days = 1 (아직 3 미만)
→ cooldown_active = False (since = 2026-04-01, 16일 경과)
→ shift_confirmed = False (3일 연속 필요)

_regime_quality.jsonl append:
  {"date":"2026-04-17", "overlap_count":0, "overlap_ratio":0.0,
   "shift_candidate":true, "consecutive_days":1, ...}
```

### C. Regime memory 정규화 결과

| 항목 | Before | After |
|------|--------|-------|
| since 포맷 | `2026-04` | `2026-04-01` |
| history[6] period | `2026-04 ~ 2026-03` (역순) | `2026-03-01 ~ 2026-04-01` |
| history[9] period | `2026-03 ~ 2026-04-17` (혼합) | `2026-03-01 ~ 2026-04-17` |
| topic_tags 필드 | 없음 | 3개 태그 (서술형에서 추출) |
| narrative_description | 없음 | `"지정학 완화 vs 구조적 인플레..."` (서술형 보존) |

### D. 수동 검증 커맨드

```bash
# 1) canonical page 확인
cat market_research/data/wiki/05_Regime_Canonical/current_regime.md

# 2) debate 재실행 후 canonical 불변 확인
md5sum market_research/data/wiki/05_Regime_Canonical/current_regime.md
python -c "from market_research.report.debate_service import run_debate_and_save; \
           run_debate_and_save('월별', 2026, 4, '_market', '2026-04')"
md5sum market_research/data/wiki/05_Regime_Canonical/current_regime.md   # 동일해야 함

# 3) quality log 추적
tail market_research/data/report_output/_regime_quality.jsonl
```

---

## Part VI. 남은 작업 (Phase 3~, 다음 배치)

| # | 항목 | 우선순위 | 배치 |
|---|------|---------|------|
| 1 | GraphRAG transmission path P0 — target 오매칭 필터, self-loop 제거, pair당 1경로 | P0 | Phase 3 |
| 2 | `_transmission_path_quality.jsonl` | P0 | Phase 3 |
| 3 | GraphRAG P1 — trigger/target 동적 선택, alias dict, embedding fallback | P1 | Phase 3 |
| 4 | `07_Graph_Evidence/transmission_paths_draft.md` 페이지 생성 | P1 | Phase 3 |
| 5 | P1 완료 후 selected path → canonical supporting evidence 승격 | P1 | Phase 4 |
| 6 | graphify 연동 | P2 | Phase 4+ |
| 7 | entity page 품질 개선 (현재 매체 단위 → GraphRAG 노드 연동) | P2 | Phase 4+ |

---

## Part VII. 운영 가이드

### 신규 규칙

1. **debate_engine에서 regime_memory.json을 수정하지 말 것** — `_update_regime_memory` 함수 자체를 제거했고, 복구 금지.
2. **canonical regime 태그형 서식 고정** — `" + "` join. 서술형이 필요하면 `narrative_description` 필드에.
3. **날짜 포맷 `YYYY-MM-DD`** — 모든 regime 관련 필드 (since / ended / period).
4. **debate 결과는 무조건 `06_Debate_Memory/`** — wiki draft tier에만 축적.
5. **Step 2.6 draft pages는 정제 직후** — regime/debate/path 포함 금지.

### 조회 라우팅 (Wiki Index에 명시)

```
1. 05_Regime_Canonical/       (confirmed memory)
2. 01_Events ~ 04_Funds/      (canonical draft pages)
3. 06_Debate_Memory/          (interpretations, provisional)
4. 07_Graph_Evidence/ 또는 GraphRAG retrieval
5. raw source (news JSON)
```

### Cooldown / weeks

- cooldown: 전환 후 14일 재전환 잠금 (`MIN_REGIME_DURATION_DAYS = 14`)
- weeks: daily_update 실행 시 자동 계산 (`(today - since).days // 7`)
- 3일 연속 shift 후보 AND cooldown 해제 → 확정

---

*2026-04-17 | canonical/draft 분리 + regime writer 단일화 + wiki 2-tier 구조화*
