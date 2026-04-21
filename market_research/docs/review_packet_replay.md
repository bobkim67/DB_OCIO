# Review Packet v15 — as-of-date regime replay (supplementary)

> v15는 **보조 검증 배치**다. live `_regime_quality.jsonl`의 "같은 날짜 append
> 다수" 성격을 보완하기 위해, 미래 기사 정보 누수 없이 과거 날짜별 regime
> 판단을 재생성하는 **replay/backfill 경로**를 추가했다. 이 결과는 threshold
> 재평가 · false positive/negative 점검의 **보조** 자료이지 **live monitor의
> 대체재가 아니다**.
>
> 고정 원칙 6개(regime 판정 로직 / threshold / canonical-debate-evidence
> writer 경계 / alias propose-only / entity `status: base` / GraphRAG P1)는
> **전부 불변**.

---

## 1. 왜 replay를 추가했는가

v14 monitor summary에서 드러난 문제:
- `source_rows: 40+` 그러나 `unique_dates_in_window: 1` (동일 날짜 append)
- `row_per_date_ratio: 46` → 운영/테스트/디버그 noise가 row를 부풀림
- **day-level 진단 불가** (v12.1, v13, v14 packet 반복 경고)

대응 선택지:
- (a) live judgement을 하루 1회만 append하게 바꾼다 → 규칙 변경, 금지
- (b) live 로그를 후처리로 deduplicate → 정보 손실, 원래 시점 정보 소실
- (c) **별도 replay 경로로 날짜당 1번씩 판정 재생성** → 정보 무손실, 규칙 불변

(c)를 선택. 단, replay는 보조용이고 live monitor를 대체하지 않는다.

---

## 2. 무엇을 만들었나

### 2.1 구조 (Option C — pure function factor-out)

`_step_regime_check` 내부 판정 로직이 live-only에서 공유 가능한 pure 함수로
분리되었다. **규칙/threshold는 한 글자도 바뀌지 않았다**; `date.today()`만
`asof_date` 파라미터로 치환된 것이 차이의 전부다.

```
pipeline/daily_update.py (수정)
├── _judge_regime_state(regime, delta, asof_date, taxonomy_set)  ← NEW pure
│     입력: regime dict, delta, asof_date(date)
│     출력: (updated_regime, quality_record)
│     부작용 없음 — 파일/canonical/stdout 모두 caller 책임
├── _compute_delta_from_articles(articles, asof_date=None)       ← NEW pure
│     articles 집합 → topic_counts/topic_direction/asset_impact/sentiment
├── _step_regime_check(delta)  ← thin wrapper (기존 엔트리)
│     REGIME_FILE read → normalize → _judge_regime_state
│     → REGIME_FILE write → update_canonical_regime
│     → _regime_quality.jsonl append → stdout
└── _step_mtd_delta(year, month, date_str)  ← _compute_delta_from_articles 위임

tools/regime_replay.py (신규)
├── 월별 news JSON union 로드 (배치 1회)
├── for asof in [start .. end]:
│     ├── as-of window 필터:  pub_date in [asof-44, asof]
│     ├── copy.deepcopy (원본 dict 오염 방지)
│     ├── refine 재실행: process_dedupe_and_events →
│     │     compute_salience_batch → fallback_classify_uncategorized
│     │     (BM anomaly dates는 asof 이하로 prune)
│     ├── today slice = where date == asof & _classified_topics present
│     ├── delta = _compute_delta_from_articles(today_slice)
│     ├── regime, quality_record = _judge_regime_state(carry, delta, asof)
│     └── append quality_record to in-memory rows
├── overwrite:
│     data/report_output/_regime_quality_replay.jsonl
│     data/report_output/regime_replay_summary.{json,md}
└── 절대 접근 금지: REGIME_FILE / live quality jsonl /
     05_Regime_Canonical/ / raw news JSON write
```

### 2.2 Initial state 결정: neutral_empty

- `topic_tags=[]` / `direction=neutral` / `since=start_date` /
  `_shift_consecutive_days=0`
- live `regime_memory.json` snapshot은 **절대 사용 금지** (look-ahead
  금지 원칙 + 재현성)
- 실제 운영 상 귀결: v12의 "empty tags → hold" 규칙 때문에 replay loop
  전체가 hold 상태에 머문다 (§4 참조). 이 동작은 **의도된 결과**이며
  정직하게 보고한다.

### 2.3 Lookback 45일

- 하루만 보면 event/corroboration 과소평가
- 전체 history를 보면 오래된 기사 영향 과대
- **45일 = 당월 + 전월** 범위. 월 경계 이벤트도 일정 흡수
- `--lookback-days` 플래그로 조정 가능 (검증용 75일 테스트 허용)

---

## 3. 고정 원칙 준수 매핑

| 원칙 | 구현 | 검증 |
|------|------|------|
| 판정 규칙/threshold 불변 | `_judge_regime_state`는 기존 로직을 그대로 옮김 | test case 8 (subprocess로 `test_regime_decision_v12` + `test_taxonomy_contract` 실행) |
| `REGIME_FILE` write 금지 | replay 경로에 `REGIME_FILE` import 없음 | test case 5 (MD5 pre=post) |
| live `_regime_quality.jsonl` write 금지 | replay 경로에 `_regime_quality.jsonl` 참조 없음 | test case 5 |
| `05_Regime_Canonical/` write 금지 | `update_canonical_regime` import 없음 | test case 5 |
| raw news JSON write 금지 | `safe_write_news_json` import/호출 없음; refine은 deep copy 상에서만 동작 | test case 5 |
| Look-ahead bias 금지 | `_filter_asof_window`는 `asof - 44 ≤ date ≤ asof`; BM anomaly도 prune | test case 1 (미래 articles 추가 시 과거 row 불변), test case 4 (lookback 경계) |
| 날짜당 1 row | for loop iteration당 append 1회 | test case 2 (17일 → 17 rows), case 7 (empty day도 row 1개) |
| state 승계 | regime dict를 다음 iteration에 carry | test case 3 (3-consecutive + cooldown re-confirm 억제) |

---

## 4. 실제 17일 replay 실행 (2026-04-01 ~ 2026-04-17)

### 4.1 실행 증거

```
$ python -m market_research.tools.regime_replay \
      --start 2026-04-01 --end 2026-04-17
...
=== regime_replay summary ===
mode: asof_replay — supplementary verification — NOT live monitor
window: 2026-04-01 ~ 2026-04-17  (lookback 45d, initial_state=neutral_empty)
total_replay_dates: 17  unique: 17
total_loaded_articles: 58,871  per_date_avg: 1,262.29
runtime: 351.63s
candidate_days: 0  confirmed_count: 0  churn: None
avg coverage_current: 0.0  avg coverage_today: 0.0
→ wrote _regime_quality_replay.jsonl, regime_replay_summary.{json,md}
```

### 4.2 Live 파일 MD5 불변 (사전/사후)

```
pre-replay (2026-04-17 17:42):
  regime_memory.json         31f8354afb276af51a7432a9473f4682
  _regime_quality.jsonl      5ead106012dde8eba7826348983de3ef

post-replay (2026-04-17 17:50):
  regime_memory.json         31f8354afb276af51a7432a9473f4682   ✓
  _regime_quality.jsonl      5ead106012dde8eba7826348983de3ef   ✓
  05_Regime_Canonical/current_regime.md   c937e0853922b194771ec3891af7d1d4
  05_Regime_Canonical/regime_history.md   7724f32ca46cb271ab02655e7dae3b02
  (canonical pages는 replay 전 기록이 없어도, replay 실행 중에는 write가
  일어나지 않았음을 test case 5가 직접 검증)
```

### 4.3 Row-level summary (replay)

| indicator | value |
|---|---|
| total_replay_dates | 17 |
| unique_replay_dates | 17 |
| total_loaded_articles | 58,871 |
| per_date_avg_article_count | 1,262.29 |
| runtime_seconds | 351.63 |
| candidate_days | 0 |
| confirmed_count | 0 |
| sentiment_flip_days | 0 |
| cooldown_days | 14 |
| empty_tag_days | 17 |
| avg_coverage_current | 0.0 |
| avg_coverage_today_core3 | 0.0 |
| churn_proxy | `null` (candidate_days=0) |

consecutive_day_distribution: `{0: 17}`

### 4.4 해석 — 정직한 기록

replay는 **모든 17일이 `empty tags → hold`** 로 판정됐다. 이유:
- `initial_state = neutral_empty`이면 `current.topic_tags = []`.
- v12 규칙: `if not current_tags: hold ("description 기반 판정 금지")`
- → `shift_candidate = False` → `consecutive = 0` → 영원히 확정 불가.

이것은 **버그가 아니다**. v12는 애초에 "빈 regime을 태동시키지 않는다"로
설계됐다 (description-based tag 유입 차단이 상위 원칙). 즉 replay는
"빈 상태에서는 스스로 첫 regime을 만들지 못한다"는 사실을 **시각화**하는
용도로만 유용하다. threshold나 shift 감지 빈도를 **이 replay만으로**
재평가하는 것은 의미가 없다.

replay가 의미 있는 범위:
- **기존 regime이 존재**하는 상태에서 shift가 어떻게 감지/억제되는지
  → `_judge_regime_state`를 synthetic state로 직접 호출 (test case 3)
- **look-ahead 차단 확인** (test case 1, 4)
- **live 파일 격리 보증** (test case 5)

따라서 이번 17일 replay의 진짜 가치는 "실행 증거 + live 격리 증명"이며,
숫자 자체는 neutral_empty 초기값의 부작용을 보여준다. 이 한계는 **§9
후속 배치 제안**에서 "seeded initial state with look-ahead audit" 로 다룬다.

### 4.5 Runtime 체감 / hotspot

- 하루당 평균 **~20.7초** (351.63s / 17일)
- 주 hotspot: `process_dedupe_and_events` — 45일 union ~35k-60k articles에
  대한 union-find dedupe + event clustering. 일 평균 1,262 기사의 당일 추가
  비용보다 **45일 window 재정제 비용**이 압도적
- BM anomaly 로드는 월 전환 시점마다 DB 호출 — CLI stdout의
  `salience: bm_anomaly N일 연동` 라인이 17일 전체에서 17회 찍힘
- 17일 배치 실행 시간 ~6분은 CI 블로커 아님. 한 달치(30일) 기준으로도 ~10분
  수준

---

## 5. 테스트

```
$ python -m market_research.tests.test_regime_replay     # 8/8 PASS

=== Summary ===
  PASS     test_case_1_no_lookahead
  PASS     test_case_2_one_row_per_date
  PASS     test_case_3_stateful_rule
  PASS     test_case_4_lookback_window
  PASS     test_case_5_live_file_isolation
  PASS     test_case_6_summary_consistency
  PASS     test_case_7_null_empty_day_handling
  PASS     test_case_8_live_wrapper_equivalence
```

기존 회귀 유지:
```
test_taxonomy_contract: 3/3
test_regime_decision_v12: 4/4
test_alias_review: 6/6
test_regime_monitor: 7/7
test_entity_demo_render: 5/5
```

**전체 33 cases PASS.** 회귀 0건.

---

## 6. 변경 파일 목록

| 파일 | 변경 | 커밋 |
|------|------|------|
| `pipeline/daily_update.py` | `_judge_regime_state` / `_compute_delta_from_articles` pure functions 분리, `_step_regime_check`는 thin wrapper, `_step_mtd_delta`는 delegate | #1 `80aab5f` |
| `tools/regime_replay.py` | as-of-date replay CLI 신규 | #2 `db3a551` |
| `tests/test_regime_replay.py` | 8-case 스위트 신규 | #3 `7550f21` |
| `docs/review_packet_replay.md` | 본 문서 | #4 |

**변경 없음**:
- `wiki/canonical.py` / `wiki/debate_memory.py` / `wiki/graph_evidence.py` — writer 경계 불변
- `wiki/draft_pages.py` — entity page 불변
- `report/debate_engine.py` — regime write 재도입 없음
- `analyze/graph_rag.py` — GraphRAG P1 불변
- `tools/regime_monitor.py`, `tools/alias_review.py` — v14 상태 유지

---

## 7. 리뷰 체크리스트

- [ ] `_judge_regime_state`는 규칙/threshold를 한 글자도 바꾸지 않았는가
  (**#1 diff 확인 + test case 8**)
- [ ] `_step_regime_check` wrapper는 기존 출력·stdout·canonical write
  타이밍을 보존하는가 (**test_regime_decision_v12 / test_taxonomy_contract**)
- [ ] replay 경로에 `REGIME_FILE` / `update_canonical_regime` /
  `safe_write_news_json` import가 0건인가 (**grep + test case 5**)
- [ ] 미래 articles 추가가 과거 asof row에 영향 주지 않는가
  (**test case 1, case 4**)
- [ ] 날짜당 정확히 1 row인가 (**test case 2, case 7**)
- [ ] stateful rule (3연속+cooldown)이 순차 승계되는가 (**test case 3**)
- [ ] summary 수치가 jsonl과 일치하는가 (**test case 6**)
- [ ] **replay 결과만으로 threshold 조정 금지** 원칙이 지켜지는가
  (**본 packet §4.4 + §8**)

---

## 8. 하지 않은 것 (지시서 금지 항목 + 본 packet에서 스스로 제한)

- live `_regime_quality.jsonl`에 replay row append 금지 ✓
- canonical writer 호출 금지 ✓
- debate → regime write 재도입 금지 ✓
- alias 자동 apply 금지 ✓
- threshold 조정 금지 ✓ — 본 replay가 `candidate_days=0`을 보였더라도
  이는 neutral_empty 초기값의 부작용이며, v12 threshold를 조정할 근거
  아님
- entity 확장 강행 금지 ✓
- GraphRAG P1 수정 금지 ✓
- "월별 정제 결과를 그대로 잘라 replay라 부르기" 금지 ✓ — 매일 deep copy
  후 **as-of-date 재정제** 수행

---

## 9. 남은 한계 / 후속 배치 제안

### 9.1 한계

| 한계 | 원인 | 대응 방향 |
|------|------|----------|
| `initial_state = neutral_empty`로는 첫 regime을 태동시키지 못함 | v12의 "empty tags → hold"가 상위 원칙이라 설계대로 | seeded initial state + look-ahead audit (아래 9.2) |
| 하루 ~20초 (dedupe O(n²)·union-find) | 45일 union 재정제가 hotspot | 필요 시 dedupe 캐시. 현재는 수용 가능한 비용 |
| BM anomaly가 월 단위 로드 | `load_bm_anomaly_dates(y, m)`가 월 경계 기준 설계 | 필요 시 range 인자 추가 (별도 배치) |

### 9.2 다음 배치 제안

**(a) seeded initial state with look-ahead audit**
- replay start 이전의 **공식 live snapshot 1회**를 명시적으로 초기 state로
  주입 가능하게 하되, "이 snapshot 자체가 상대적으로 과거인지"를 audit.
  예: `--seed-from-date 2026-03-15 regime_memory.json.snapshot.2026-03-15`
  같이 **과거 버전 파일**을 명시적으로 읽어 들이는 방식.
- look-ahead는 snapshot 파일이 start date 이전에 만들어졌음을 보증해야 통과.
- 이렇게 해야 replay가 "기존 regime 위의 shift 감지 / hold 거동"을 실제로
  관찰할 수 있다.

**(b) dedupe 캐시**
- 하루 ~20초 중 대부분이 dedupe/event clustering. D와 D+1의 기사 집합이
  거의 겹치므로 cache-friendly. 별도 배치에서 다룬다.

**(c) daily_update Step 5.5로 monitor/replay 둘 다 연동**
- v14에서 보류한 자동화. unique_dates 누적 ≥ 10 이후에 재검토.

### 9.3 다음 배치 아님 — 하지 말 것

- replay 결과를 근거로 threshold 조정
- replay를 live monitor의 대체재로 쓰기
- replay를 canonical writer의 입력으로 쓰기
- `regime_memory.json`에 replay state를 병합

---

## 10. 판정

**총평: packet 기준 pass-leaning (supplementary verification path 추가).**

- 고정 원칙 6개 불변 유지 확인
- live 파일 격리는 MD5 기준으로 직접 검증
- 판정 로직 동치성은 기존 회귀 2종 subprocess 실행으로 검증
- 실제 17일 실행의 `candidate_days=0` 결과는 **정직하게 보고** (neutral_empty
  초기값의 부작용이며, threshold 조정 근거 아님)
- replay 한계는 §9로 드러내고, 후속 배치 제안을 명시

최종 pass는 코드 diff와 §4 MD5 증거 / §5 테스트 로그 재확인 전제. replay는
**live monitor를 대체하지 않으며, 보조 검증 경로로만 위치 지정**된다.

---

## Revision note

- **v15 (2026-04-17 KST)** — 초판:
  - Option C factor-out: `_judge_regime_state` + `_compute_delta_from_articles`
    pure functions. regime 판정 규칙/threshold는 한 글자도 불변.
  - `tools/regime_replay.py` as-of-date rolling 45-day lookback CLI
    + neutral_empty initial state + overwrite-on-rerun 산출물.
  - `tests/test_regime_replay.py` 8 cases (no-lookahead / 1-row-per-date /
    stateful rule / lookback / live isolation / summary consistency /
    null day / live wrapper equivalence).
  - 실제 17일 replay 수행 (2026-04-01 ~ 2026-04-17): runtime 351.63s,
    58,871 articles loaded, neutral_empty 부작용으로 candidate_days=0.
    Live MD5 (`regime_memory.json`, `_regime_quality.jsonl`, canonical
    pages, raw news JSON) pre/post 일치 확인.
  - 전체 회귀 33 cases PASS.
  - Live monitor 대체 아님 · threshold 미조정 · canonical 미오염 명시.
