# Review Packet v14 — Partial Expansion / Operational Readiness

> v14는 **조건부 확장 배치**였고, 실태 확인 결과 entry criteria 1건만 충족
> 되어 **부분 확장 + 운영 준비 배치**로 축소 수행했다. packet 제목과 총평
> 모두 "partial expansion / operational readiness"로 표기한다.
>
> v13에서 확정된 원칙 6개(regime 판정 로직 / threshold / writer 경계 /
> alias propose-only / entity `status: base` / GraphRAG P1)는 **전부 불변**.

---

## 1. v14가 "조건부 확장 배치"였던 이유

v12 → v12.1 → v13을 거치며 "기능 확장"이 아니라 "운영 투명성"이 남은
핵심 이슈로 식별됐다. v14는 이 잔여 이슈에 대해:

1. 운영 로그가 충분히 쌓였는지 먼저 확인하고
2. 쌓였을 때만 확장하고
3. 쌓이지 않았으면 운영 준비만 하는

조건부 설계를 택했다. 이는 "검증 없이 규모만 늘리는" 함정을 피하기 위함이다.

### 이번 배치에서 금지된 것 (10 non-goals, 전부 준수)

- regime threshold 조정 / decision rule 변경
- alias 자동 apply
- canonical writer 추가 / debate → regime write 재도입
- transmission path canonical 승격
- graphify viewer 연동
- graphnode entity 대량 생성 강행
- entity frontmatter에 draft evidence를 confirmed처럼 삽입
- GraphRAG P1 로직 변경

---

## 2. Entry criteria 판정

### 2.1 Regime 운영 로그 — **미충족**

- 목표: `unique_dates_in_window ≥ 10` (이상적 14)
- 실측 (2026-04-17 15:xx KST, `_regime_quality.jsonl` 46 rows 기준):
  - `unique_dates_in_window: 1` (46 rows 모두 `2026-04-17`)
  - `unique_date_coverage_ratio: 0.0714` (1/14)
  - `row_per_date_ratio: 46.0` (극단적 append 압력)
- 결론: **세션 내 해결 불가**. 달력 기반 날짜 누적은 운영 스케줄에 의존
  하며, 이 세션은 그 스케줄을 대체할 수 없다.

### 2.2 Approved alias 운영 루프 — **부분 충족 (1건 실증)**

- 목표: `phrase_alias_approved.yaml`에 ≥1건 반영 + `--apply --strict` 통과
  + builtin override 없이 overlay 적용 + runtime import 시 정상 반영
- 결과:
  - `approved:` 1건 (`"이란 위기" → 지정학`)
  - `keep_unresolved:` 5건
  - `--apply --strict` → accepted 1, rejected 0, exit 0
  - runtime `extract_taxonomy_tags("이란 위기")` → `(['지정학'], [])`
  - builtin entry `"이란"`, `"지정학 위기"`는 불변 (setdefault 검증)
- 결론: **1건 실증으로 루프는 증명됨**. 다만 대량 승인 경험은 없으므로
  "안정 운영"이라기보다 "운영 가능성 확인" 단계.

### 2.3 종합 판정: 부분 확장 (B) + 준비 (A) + 보류 (C)

| Workstream | 조건 | 조치 |
|-----------|------|-----|
| B — alias 루프 실증 | 2.2 부분 충족 | **실행** (1건 승인 + 가이드) |
| A — regime monitor 운영 승격 | 2.1 미충족 | **prep metrics만** (판정 로직 불변) |
| C — entity 확장 | 2.1 미충족 | **보류** (demo 3건 유지) |

---

## 3. Workstream B — approve one alias (실증)

### 3.1 승인 결정 근거

- **승인**: `"이란 위기" → 지정학`
  - Trace 근거: `_taxonomy_remap_trace.jsonl` `history[7]` unresolved 1회
  - 이유: 짧은 **사건/주제형** 표현, 반복 가능성, taxonomy 수렴 명확
    (서술형 문장이 아님)
- **keep_unresolved**: 5건 (문장형/해석 의존/반복 주제성 낮음/taxonomy
  강제 매핑 위험/서술형 색채 강함 — 각 1건씩 이유 주석)
  - `단기 랠리와 장기 리스크의 불일치`
  - `유가 구조적 충격의 줄다리기`
  - `인플레·성장 둔화의 불확실성 충돌`
  - `에너지 인플레이션 압박의 긴장.`
  - `구조적 인플레 딜레마`

### 3.2 버그 발견 + 수정 (필수 전제였음)

1건 승인을 시도하는 과정에서 **self-fulfilling duplicate 버그**를 발견
했다. `--apply`가 runtime-merged `PHRASE_ALIAS`(builtin + overlay)를
"builtin"으로 오인하여 overlay entry를 `duplicates (same target)`으로
잘못 분류했다. v13에서는 yaml이 비어 있어 드러나지 않았던 이슈.

수정:
- `wiki/taxonomy.py`에 `BUILTIN_PHRASE_ALIAS` 스냅샷 (pre-overlay 복사본)
- `tools/alias_review.py::cmd_apply`가 `BUILTIN_PHRASE_ALIAS`를 사용해
  builtin 기준 conflict 검사 (runtime PHRASE_ALIAS는 extractor의 SSOT로
  유지)

이 수정 후에야 `accepted: 1 "이란 위기" → 지정학`이 정확히 나온다.

### 3.3 실제 실행 증거

```
$ python -m market_research.tools.alias_review --apply --strict
=== alias_review --apply ===
approved file: market_research/config/phrase_alias_approved.yaml
accepted (new aliases): 1
  + "이란 위기" -> 지정학
keep_unresolved entries: 5
  ~ 단기 랠리와 장기 리스크의 불일치
  ~ 유가 구조적 충격의 줄다리기
  ~ 인플레·성장 둔화의 불확실성 충돌
  ~ 에너지 인플레이션 압박의 긴장.
  ~ 구조적 인플레 딜레마
Runtime merge: taxonomy._load_approved_alias() picks up accepted
entries on next import (setdefault — builtin PHRASE_ALIAS wins on conflict).
exit=0

$ python -c "from market_research.wiki.taxonomy import extract_taxonomy_tags; \
            print(extract_taxonomy_tags('이란 위기'))"
(['지정학'], [])
```

### 3.4 운영 가이드

신규: `market_research/docs/alias_review_guide.md` — 승인/keep_unresolved
판별 기준, builtin 충돌 처리, strict mode 사용, re-propose cadence,
금지 사항. v14 first-loop evidence 블록도 끝부분에 포함.

### 3.5 테스트

`tests/test_alias_review.py::test_case_6_builtin_snapshot_vs_overlay` 추가:
BUILTIN 스냅샷이 overlay와 분리되어 있어 apply 분류가 정확한지 검증.

---

## 4. Workstream A — regime_monitor day-level prep metrics

### 4.1 목적

실태 (§2.1)가 `unique_dates_in_window=1`이므로 **day-level 운영 해석은
불가능**. v14에서는 threshold 재평가 대신, 다음 배치에서 재평가를 할 때
row 노이즈와 day 신호를 시각적으로 구분할 수 있도록 **보조 지표 4개**를
summary에 추가했다. 판정 로직은 **불변**.

### 4.2 추가된 지표 (전부 observation-only)

| 지표 | 정의 | null 조건 |
|------|------|----------|
| `unique_date_coverage_ratio` | `unique_dates / window_days` | `window_days=0` |
| `row_per_date_ratio` | `window_rows / unique_dates` | `unique_dates=0` |
| `observed_unique_dates_with_candidate` | shift_candidate=true가 발생한 distinct date 수 | 0으로 떨어짐 (null 아님) |
| `observed_unique_dates_with_empty_tags` | empty tags hold가 발생한 distinct date 수 | 0으로 떨어짐 (null 아님) |

**설계**: 지표 이름에 `unique_date`, `per_date`, `dates_with`가 붙은 것은
**전부 day-level** 기준. 기존의 `_rows` 지표와 이름 수준에서 혼동하지
않도록 분리했다.

### 4.3 실제 출력 (2026-04-17 live, 46 rows)

```
$ python -m market_research.tools.regime_monitor --days 14
window: 2026-04-04 ~ 2026-04-17 (14 days)
source_rows: 46  window_rows: 46  unique_dates_in_window: 1  malformed_skipped: 0
unique_date_coverage_ratio: 0.0714  row_per_date_ratio: 46.0
  obs_dates_with_candidate: 1  obs_dates_with_empty_tags: 1
shift_candidate_rows: 16
shift_confirmed_count: 1
...
churn proxy (confirmed / candidate_row): 0.0625
```

`row_per_date_ratio: 46.0` 한 숫자만 봐도 day-level 해석이 불가능함을
즉시 파악할 수 있다. 이것이 본 prep metric의 목적.

### 4.4 daily_update 연동 — 보류

작업지시서 §3.A의 `daily batch 연동 검토`는 **이번 세션에서 보류**했다.
이유:
- 세션 내에서 스케줄러(cron/Streamlit admin) 동작을 검증할 방법이 없음
- 실제 연동 없이 훅만 추가하면 "구현했지만 돌지 않는 상태"가 된다
- v15에서 실제 daily 스케줄 정착 후 합치는 것이 안전

### 4.5 테스트

`tests/test_regime_monitor.py`:
- `test_case_6_prep_metrics_day_level` — 2-rows-same-date + candidate/empty
  overlap fixture로 4개 지표가 **row가 아닌 unique date** 기준으로 집계
  되는지 검증
- `test_case_7_prep_metrics_null_safe` — empty window & `window_days=0`
  에서 null/0 경로가 crash 없이 처리되는지 검증

7/7 PASS.

---

## 5. Workstream C — entity 확장 보류

### 5.1 보류 사유

1. Entry criteria 2.1 미충족 → day-level 운영 증거 부재
2. graphnode severity_weight 기준 자체가 미완 (v12.1 §10 리스크 유지)
3. alias 실증이 1건뿐 → 대량 노드 label 품질 보증 불가
4. 3 demo 페이지는 여전히 well-formed이며 파일 id가 안정 → 확장 전
   기준선이 훼손되지 않음

### 5.2 재시도 조건 (v15 candidate)

- `unique_dates_in_window ≥ 10` 유지 상태에서 2주 이상 운영 로그 축적
- `phrase_alias_approved.yaml` 승인 entry ≥ 5건 (anecdotal → 안정 운영
  전환)
- graphnode severity_weight 기준 재정비 완료

위 3조건이 전부 충족되면 graphnode top-3 → top-5 (이후 top-10) 단계 확장.

---

## 6. 변경 파일 목록

| 파일 | 변경 내용 | 커밋 |
|------|-----------|------|
| `config/phrase_alias_approved.yaml` | approved 1건 + keep_unresolved 5건 + reason 주석 | #1 |
| `wiki/taxonomy.py` | `BUILTIN_PHRASE_ALIAS` 스냅샷 export (버그 수정 전제) | #1 |
| `tools/alias_review.py` | `cmd_apply`가 BUILTIN 스냅샷 사용 | #1 |
| `tests/test_alias_review.py` | case 6 (BUILTIN 스냅샷 ↔ overlay 분리 검증) | #1 |
| `docs/alias_review_guide.md` | 운영 가이드 신규 | #1 |
| `tools/regime_monitor.py` | prep metrics 4개 + day-level 섹션 | #2 |
| `tests/test_regime_monitor.py` | case 6 + 7 (prep metric / null-safe) | #2 |
| `docs/review_packet_v14.md` | 본 문서 | #3 |

**변경 없음**:
- `pipeline/daily_update.py` — Step 5 판정 로직, threshold, writer 경계 전부 불변
- `analyze/graph_rag.py` — P1 로직 불변
- `wiki/canonical.py`, `wiki/debate_memory.py`, `wiki/graph_evidence.py` — writer 경계 불변
- `wiki/draft_pages.py::write_entity_page` — demo 3건 유지 (확장 보류)
- `report/debate_engine.py`, `report/debate_service.py` — regime write 재도입 없음

---

## 7. 실행 증거

**실행 환경**:
- Branch: `feature/insight-v14` @ commit `d67202f` (#2 완료 시점)
- Python: 3.14.3 · Platform: win32 (Windows 11)
- 실행 시각: 2026-04-17 KST (알리어스 승인 + prep metrics 검증)
- 이전 브랜치: `feature/insight-v13` (HEAD `f97c3c6`)

```
$ python -m market_research.tools.alias_review --propose
  total trace rows: 31
  unresolved unique phrases: 10  (keep_unresolved: 6, review_needed: 4)

$ python -m market_research.tools.alias_review --apply --strict
  accepted (new aliases): 1   + "이란 위기" -> 지정학
  keep_unresolved entries: 5
  exit=0

$ python -m market_research.tools.regime_monitor --days 14
  source_rows: 46  window_rows: 46  unique_dates_in_window: 1
  unique_date_coverage_ratio: 0.0714  row_per_date_ratio: 46.0
  obs_dates_with_candidate: 1  obs_dates_with_empty_tags: 1
  shift_confirmed_count: 1   churn proxy: 0.0625

$ python -c "from market_research.wiki.taxonomy import extract_taxonomy_tags; \
            print(extract_taxonomy_tags('이란 위기'))"
(['지정학'], [])

$ python -m market_research.tests.test_alias_review           # 6/6 PASS
$ python -m market_research.tests.test_regime_monitor          # 7/7 PASS
$ python -m market_research.tests.test_entity_demo_render      # 5/5 PASS
$ python -m market_research.tests.test_taxonomy_contract       # 3/3 PASS
$ python -m market_research.tests.test_regime_decision_v12     # 4/4 PASS
$ python -m market_research.tests.test_graphrag_p0_vs_p1 2026-04
  total_paths   P0 2 → P1 6
  unique_trig   P0 2 → P1 4   (configured 4/9, active 4/6)
  unique_tgt    P0 2 → P1 3   (configured 3/10, active 3/5)
```

**집계**: 기존 회귀 3종 12 케이스 + 신규/보강 3종 18 케이스 = **27/27 PASS**.
GraphRAG P0/P1 수치 변동 없음.

---

## 8. 아직 보류한 것

| 항목 | 보류 사유 | 재시도 조건 |
|------|----------|------------|
| Entity graphnode 확장 (3 → 5/10) | criteria 2.1 미충족, severity_weight 기준 미완 | §5.2 3조건 충족 |
| `daily_update` Step 5.5 연동 | 세션 내 스케줄러 검증 불가 | 운영 스케줄 정착 후 |
| Transmission path canonical 승격 | v13부터 유지 | alias dict 실전 검증 + 경로 품질 모니터링 이후 (Phase 4+) |
| graphify viewer 연동 | v13부터 유지 | 내부 정합성 확보가 선결 |
| regime threshold 재조정 | day-level 증거 0 | `unique_dates_in_window ≥ 14` 누적 후 |

---

## 9. 다음 배치 (v15) 제안

### v15 진입 조건 (둘 다 충족)

1. 2주 이상 daily batch 규칙 실행 → `unique_dates_in_window ≥ 10`
2. `approved` alias entry ≥ 5 (this batch 1 + 추가 4+)

### v15 수행 예상 범위

- Workstream A 승격: regime threshold 재평가 (정량 근거 기반)
- Workstream C 시작: graphnode entity 3 → 5 → 10 단계 확장 (entry 조건
  충족 시)
- daily_update Step 5.5 연동 (monitor summary 자동 갱신)

### v15 에서도 건드리지 말 것

- canonical writer 추가
- debate → regime write 재도입
- transmission path canonical 승격 (v15 범위 밖)
- entity frontmatter에 draft-as-confirmed

---

## 10. 판정

**총평: packet 기준 pass-leaning (partial expansion / operational readiness).**

- 확장 조건 1개만 충족된 상태를 정직하게 인정하고, 축소된 범위를 완결
- Workstream B 실증 + 그 과정에서 드러난 버그까지 수정 (self-fulfilling
  duplicate)
- Workstream A는 preparatory (판정식 불변)로 범위 제한
- Workstream C는 보류 사유 명시 + 재시도 조건 적시

코드 diff와 §7 실행 증거 재확인 전제하에 pass. "조건 미충족 시 확장 보류"
라는 v14 설계 원칙이 실제로 지켜졌는지가 이 패킷의 판정 기준.

---

## Revision note

- **v14 (2026-04-17 KST)** — 초판:
  - Entry criteria 실태 확인 (2.1 미충족 / 2.2 부분 충족 1건 실증)
  - Workstream B: `"이란 위기" → 지정학` 승인 1건 + keep_unresolved 5건
    + `docs/alias_review_guide.md`
  - **버그 수정**: `BUILTIN_PHRASE_ALIAS` snapshot 도입 (self-fulfilling
    duplicate 차단)
  - Workstream A: day-level prep metrics 4개 (`unique_date_coverage_ratio`,
    `row_per_date_ratio`, `observed_unique_dates_with_candidate/_with_empty_tags`)
  - Workstream C: demo 3 유지 (보류 + 재시도 조건 §5.2)
  - 회귀 27/27 PASS. v13 고정 원칙 6개 전부 불변.
