# R9-A — Claim Identity & Monitoring 트랙 Close Note

작성: 2026-05-13
range: R9-A.5 ~ R9-A.21A (R9-A.4 까지는 `r9a4_close_note.md` 별도 정리)
origin/main close 시점 hash: `29008b9`
참고: R9-A.4 close note — `r9a4_close_note.md`

본 문서는 **R9-A 트랙의 기능 개발 + 운영 반영 한 사이클 완료** 를 정식 기록한다.
R9-A.4 (claim extraction 파이프라인) 이후 R9-A.5~A.21A 에서 다룬 핵심 문제는
"같은 evidence 가 주어졌을 때 Haiku 가 산출하는 claim 의 identity 가 흔들리는
문제" 였고, 본 트랙의 결론은 **text 기반 identity 폐기 + evidence/assets 기반
deterministic group_id 채택 + multi-run monitoring + 운영 wiki dual-anchor
lineage linking** 으로 정리됐다.

---

## 1. 최종 상태 요약

| 항목 | 상태 |
|---|---|
| canonical_group_id 정의 | R9-A.14 G1: `period + evidence_set_hash + sorted_assets` |
| source_evidence_ids 누락 (R9-A.4 운영 prompt) | R9-A.10 normalize_claim fallback (supporting → source) 으로 해소 |
| Haiku wording variance | R9-A.12 부터 text 기반 grouping 폐기 (claim_text 는 display only) |
| Haiku taxonomy enum variance (dir/hor/type) | R9-A.13 sensitivity matrix 로 split 주범 확인 (claim_type 33%, horizon 25%, direction 8%) → R9-A.14 에서 group_id 산정 제외, diagnostic field 로만 유지 |
| Multi-run monitoring | R9-A.17 utility `build_claim_group_monitoring_summary` + tools/ entrypoint |
| Daily update opt-in | R9-A.18 Step 2.8 `--enable-group-monitoring` (default OFF) |
| Mode semantics | R9-A.19 single_batch (daily_update) vs multi_run (entrypoint) |
| Promote candidate review | R9-A.20 review packet (LLM 0) — overlap=0 발견 |
| 운영 wiki lineage | R9-A.21A dual-anchor (de1729b413 / e78dc83a1e) + group:2026-04:cfee0ff342 |
| pytest | 585 PASS (R9-A.19 commit 직후 기준, 이후 코드 변경 0) |
| LLM 누적 (R9-A 전체) | ~$1.12 |
| 운영 보호 영역 invariant | 의도된 R9-A.21A wiki 2 파일 외 변경 0 |

---

## 2. 주요 commit hash (R9-A.5 ~ R9-A.21A)

| commit | track | 설명 |
|---|---|---|
| `67c6b45` | R9-A.5 / Commit 6 | prompt 보강 (affected_assets ≥ 3 유도). Rule A dead code 해소 (0→4 활성화) |
| `c88449c` | R9-A.5.1 | claim merge/dedup diagnostic (Jaccard 0.50, LLM 0, read-only) |
| `df8752f` | R9-A.8 | Canonical claim identity 재설계 (layered: normalize text + evidence_set_hash + content_signature) |
| `dcbb6d8` | R9-A.10 | source_evidence_ids fallback (R9-A.4 운영 prompt schema 누락 보정) |
| `5b1fe56` | R9-A.12 | group_id 재정의 (text 폐기, evidence + assets + dir/hor/type) |
| `4733d36` | R9-A.14 | G1 채택 (enum 도 제거, evidence + assets only) |
| `437ce1a` | R9-A.17 | claim group monitoring 운영 통합 (utility + tools entrypoint + 21 tests) |
| `f5c27a7` | R9-A.18 | daily_update Step 2.8 opt-in (`--enable-group-monitoring`, default OFF) |
| `0ebeba2` | R9-A.19 | monitoring_mode semantics (single_batch vs multi_run) |
| `29008b9` | R9-A.21A | dual-anchor stable lineage linking (운영 wiki 첫 R9-A 갱신) |

부속 진단 (코드 변경 0):
- R9-A.6 daily_update smoke (Haiku run-to-run variance 노출, rate 100%→25% / A/B/C {4/6/0}→{3/0/0})
- R9-A.7 fresh N=5+7 calibration ($0.149, HIGH variance: range 61.43%p, claim_id Jaccard 0.0)
- R9-A.9 fresh N=5 ($0.063, CASE 2 진단: source_evidence_ids 비어있음 발견)
- R9-A.11 fresh N=5 ($0.065, R9-A.10 fallback 검증: source filled 73/73, group_id 여전히 0.0)
- R9-A.13 sensitivity matrix (G0~G8 + E0~E3 13 variant, Case A 확정)
- R9-A.16 N-run monitoring (4 strong stable 식별: 이란휴전 / 삼성 / 사모대출 / 외환보유)
- R9-A.20 review packet (overlap=0 발견 — 같은 사건 두 ID 로 surface)

---

## 3. 최종 canonical_group_id 정의

```python
# market_research/analyze/claim_extractor.py
def compute_canonical_group_id(
    period: str,
    claim_text: str,                # 시그니처 보존, hash 입력 X
    affected_assets: list[Any] | None,
    *,
    source_evidence_ids: list[Any] | None = None,
    direction: Any = "unknown",     # 시그니처 보존, hash 입력 X (R9-A.14)
    horizon: Any = "unknown",       # 시그니처 보존, hash 입력 X (R9-A.14)
    claim_type: Any = "outlook_view",  # 시그니처 보존, hash 입력 X
) -> str:
    """
    G1 정의:
        signature = md5(period + evidence_set_hash + sorted_assets)
        canonical_group_id = "group:{period}:{md5_hex10}"

    제외 (모두 R9-A 트랙 진행 중 검증 후 제거):
        - claim_text / normalized_text (R9-A.12, Haiku wording variance)
        - direction / horizon / claim_type (R9-A.14, taxonomy enum variance)
        - causal_chain natural language
    """
```

설계 원칙 (사용자 § design):
- LLM claim 은 후보 생성, group_id 가 운영 identity
- claim_text 는 display only
- 과소병합 > 과대병합 (다른 evidence set 또는 assets 이면 distinct)
- 1차 deterministic, entity/topic/embedding 은 별 단계

---

## 4. claim_id vs canonical_group_id 역할 구분

| 속성 | `claim_id` | `canonical_group_id` |
|---|---|---|
| format | `claim:{period}:{md5[:10]}` | `group:{period}:{md5[:10]}` |
| hash 입력 | period + evidence_set_hash + **content_signature** (norm_text 포함) | period + evidence_set_hash + **sorted_assets** (norm_text 미포함) |
| 의도 | **개별 claim instance** 식별자 | **반복 사건 lineage** 식별자 |
| Haiku wording variance | 매번 다른 ID 산출 (의도된 stochasticity) | wording 무관, 같은 evidence + assets 면 동일 |
| run-to-run 안정성 | 0 (R9-A.7 N=7 fresh 21 pair Jaccard 0.0) | 일부 안정 (R9-A.14 N=5 fresh 10 pair Jaccard mean 0.0737, max 0.1667) |
| 운영 추적 layer | citation anchor `[claim:hash10]` 단발 사용 | N-run monitoring + wiki lineage |
| 운영 파일 활용 | `08_Claims/{period}_claim_{hash10}.md` page filename | `## Related Stable Lineage` 블록 + ledger (별 commit) |

→ **두 layer 가 다른 목적 — 동시 유지가 의도된 설계**.

---

## 5. Group monitoring mode semantics

R9-A.19 에서 명시:

| mode | 사용처 | stable_candidate_enabled | within_run_duplicate semantics |
|---|---|---|---|
| `multi_run` | `tools/promotion_monthly_summary.py`<br>R9-A.7/11/16/17 cross-run aggregation | **True** | `overmerge_warning` |
| `single_batch` | `daily_update.py` Step 2.8 (R9-A.18) | **False** | `same_batch_repeated_group_diagnostic` |

핵심:
- **numeric 계산은 mode 와 무관**. mode 는 **해석 layer 만** 분기.
- single_batch 에서는 run_id 가 단일이므로 stable_candidate (run_count ≥ 2)
  자체가 의미 적음 → reference-only 표시.
- single_batch within_run_duplicate 는 **overmerge failure 아님** — 같은 batch
  내 동일 evidence+assets 의 claim 이 2회 이상 나왔다는 진단.
- R9-A.18 fixture 재현 (R9-A.11 73 rows 를 single batch 로 inject) 에서
  within_run_duplicate=12 가 발생하지만 이는 R9-A.16 multi_run 의 cross-run
  repeat≥2 = 12 가 single-run inject 시 within-run dup 으로 카운트된 것 —
  **다른 의미의 같은 숫자**.

---

## 6. 운영 wiki 반영 내역 (R9-A.21A dual-anchor lineage linking)

운영 wiki `08_Claims/` 의 같은 경제 사건 (이란 휴전) 두 anchor 에 R9-A.16
strong stable group `group:2026-04:cfee0ff342` lineage 연결. **신규 page 생성
0, wiki count 8 유지**.

### Anchor 1 — `de1729b413`

- title: 트럼프 2주 휴전 승인으로 WTI 19% 폭락, 91.64달러
- file: `market_research/data/wiki/08_Claims/2026-04_claim_de1729b413.md`
- coverage: **partial — commodity / oil shock side**
- 기존 affected_assets: 원자재금 / 국내주식

### Anchor 2 — `e78dc83a1e`

- title: 중동 휴전으로 코스피 5%대 급등, 원·달러 24.3원 급락
- file: `market_research/data/wiki/08_Claims/2026-04_claim_e78dc83a1e.md`
- coverage: **partial — Korean equity / FX side**
- 기존 affected_assets: 국내주식 / 환율(FX)

### Linked stable group (양 anchor 동일)

```yaml
related_group_id: group:2026-04:cfee0ff342
source: R9-A.16/R9-A.20 strong stable candidate
run_count: 3
promoted_count: 3
promoted_rate: 100%
affected_assets: [국내주식, 원자재금, 환율(FX)]
representative_claim: 중동 미·이란 2주 휴전 합의로 지정학적 리스크 급락,
                      원유가 19% 폭락 및 코스피 5% 이상 급등 견인
```

### 의사결정 근거 (R9-A.20 review packet 발견)

- 워크오더 R9-A.21 의 가정 anchor `e065e56406` 은 r9a4-c5replay suffix 영역에만
  존재, 운영 wiki 부재.
- 운영 wiki 8 은 **r9a.1-haiku manual_pilot** 의 별 8 claim (2026-05-08 promote)
  으로 R9-A.4 close note §6 KEEP 8 (r9a.4-haiku) 와 disjoint.
- 운영 wiki 8 중 이란 휴전 사건이 **이미 두 측면 (commodity + Korean equity/
  FX) 으로 분해되어 promote** 된 상태 — 이는 cfee0ff342 의 multi-asset 통합
  view 와 동일 사건의 다른 분해.
- 새 anchor 신규 promote 시 같은 사건의 wiki page 가 3개로 분산 (위험).
- → **dual-anchor 양쪽에 lineage 추가** 가 워크오더 §"중복 생성 금지" 정신
  부합 + 사건 lineage 추적 가능.

---

## 7. 변경하지 않은 운영 파일 (R9-A 전체)

R9-A.5 이후 R9-A.21A 까지 **단 한 번도 변경하지 않은** 운영 파일:

| 영역 | md5 / state | 보존 기간 |
|---|---|---|
| `market_research/data/claims/2026-04.json` | `da3fed58512829099a624ddb5fc1c85f` | R9-A.1 이후 불변 |
| `market_research/data/report_output/2026-04/_market.final.json` | `81eb876ba8b82b23a2a3dcec3de2f5bc` | R9-A.3 이전 불변 |
| `market_research/data/report_output/2026-04/07G04.final.json` | `f522cd673c8df342c21459990e86eff1` | 동일 |
| `market_research/data/regime_memory.json` | `1ee7151c8c381217c7b34393b0054daf` | R9-A.4 이전 불변 |
| `market_research/data/claims/_promotion_quality.jsonl` | 1 row (R9-A.1 manual_pilot 단독) | R9-A.4 이전 불변 |
| `ENABLE_CLAIM_EXTRACTION` (claim_extract_step.py) | `False` | R9-A.4 이후 불변 (default OFF) |

R9-A.21A 에서 의도된 변경:
- `wiki/08_Claims/2026-04_claim_de1729b413.md` (+12 lines, lineage 블록 추가)
- `wiki/08_Claims/2026-04_claim_e78dc83a1e.md` (+12 lines, lineage 블록 추가)
- wiki 파일 count 자체는 8 그대로.

---

## 8. 남은 리스크

### 8.1 Haiku taxonomy variance (R9-A.12/A.13 부속 발견)

같은 evidence 라도 Haiku 가 매번 다른 `direction` / `horizon` / `claim_type`
을 분류함. R9-A.13 sensitivity matrix 의 split 비율:

| enum | split |
|---|---|
| direction | 8.3% (1/12) — 가장 안정 |
| horizon | 25.0% (3/12) |
| **claim_type** | **33.3% (4/12)** — 가장 불안정 |

R9-A.14 에서 group_id 산정에서 제거 (diagnostic field 로 격하) 했으나, **운영
monitoring** 에서는 enum 분포가 흔들리는 게 여전히 보임 (R9-A.16/R9-A.17 의
direction variance 1 / horizon 3 / claim_type 4 group). 안정화는 후속 별 트랙.

### 8.2 Evidence-based grouping 의 과소병합

R9-A.20 review packet 의 **overlap=0** 이 결정적 증거:
- R9-A.4 close note §6 KEEP 8 (r9a4-c5replay) 와 R9-A.16 strong stable 4 의
  G1 group_id 가 완전 disjoint
- 같은 경제 사건 (이란 휴전) 이라도 affected_assets subset 이 다르면 G1
  group 분리 — 사용자 design 의 "과소병합 > 과대병합" 원칙 그대로지만, 운영
  관점에서는 같은 사건이 여러 group 으로 나뉘어 lineage 추적 부담.
- R9-A.21A 가 dual-anchor lineage linking 으로 부분 해소했으나, 다른 경제
  사건도 동일 패턴이면 매번 수동 anchor 매핑 필요.

### 8.3 single_batch vs multi_run 해석 차이 (R9-A.19 명시)

- daily_update Step 2.8 는 single_batch — stable_candidate 해석 불가, within_
  run_duplicate 도 diagnostic 만.
- 운영자가 두 mode 의 결과를 같은 metric 으로 잘못 비교할 위험.
- R9-A.19 에서 mode banner + render_md 경고 박스로 surface, 그러나 운영
  monitoring UI / dashboard 통합 시 추가 가이드 필요.

### 8.4 운영 wiki ≠ R9-A.4 close note KEEP (R9-A.21A 발견)

운영 wiki 8 = **r9a.1-haiku manual_pilot 8** ; R9-A.4 close note §6 KEEP 8 =
**r9a.4-haiku replay 영역**. 두 집합 hash10 disjoint. R9-A.4 §6 KEEP 8 의
운영 promote 는 미진행 — 별 트랙 (보호 영역 변경, 사용자 GO 필요).

### 8.5 LLM 비용 hard cap

R9-A 누적 ~$1.12 — hard cap $1/월 12% 초과. 다음 monthly cycle 까지 추가 Haiku
호출 보류 (R9-A.18 실 cycle smoke / N≥10 calibration 등).

---

## 9. 다음 후보

R9-A 트랙 닫고 다음에 진입 가능한 후보 (우선순위 순):

### 9.1 다른 monthly cycle 진입
2026-05 또는 신규 batch 에 R9-A.5~A.21A 의 전체 구조 (G1 group_id + monitoring
+ dual-anchor lineage 정책) 가 그대로 작동하는지 운영 검증. **LLM 비용 없이
(또는 일반 batch 비용 안에서) 가장 큰 가치**.

### 9.2 taxonomy variance fix (별 트랙)
direction/horizon/claim_type 의 Haiku 분류 안정화:
- N-run majority vote 적용 (group 내 enum 별 최다 값 선택)
- canonical mapping table (Haiku 출력 → 안정화된 enum)
- prompt 보강 (단발 호출 결정성 향상)

### 9.3 R9-A.22 — `_promotion_quality.jsonl` schema 확장 (LLM 0)
워크오더 §4 미루어둔 옵션:
- `group_monitoring_summary_path` optional 필드 (R9-A.18 의 diagnostics 경로)
- `related_group_id` optional 필드 (R9-A.21A 의 lineage)
- `claim_ledger_schema.py` 의 backward-compat 패턴 (`allow_legacy_c3` 등) 따름

### 9.4 ACCEPTANCE_BAND 재검토 (후보안 B)
`wiki/claim_pages.py` 의 `ACCEPTANCE_BAND = (30.0, 70.0)` → `(15.0, 85.0)`
한 줄 변경. R9-A.7 fresh N=7 의 range 61.43%p variance 에 대한 tolerance.
운영 사이클 누적 후 결정 권장.

### 9.5 R9-A.1 manual_pilot 22 claim retrofit (별 트랙)
운영 `data/claims/2026-04.json` 의 22 claim 에 R9-A.14 G1 group_id +
R9-A.10 fallback 적용 + `canonical_group_id` field 자동 부착. 운영 데이터
md5 의도된 변경 — 사용자 GO 필요.

### 9.6 R9-A.4 close note §6 KEEP 8 의 운영 promote (별 트랙)
r9a4-c5replay suffix 영역의 8 KEEP claim 을 운영 wiki/08_Claims/ 정식 promote.
운영 wiki count 8 → 16 의도된 변경. 사용자 GO 필요.

---

## 10. Rollback 방법

### 10.1 R9-A.21A 만 회귀

```bash
git revert 29008b9
```

또는 wiki 파일 두 개만:

```bash
git checkout 0ebeba2 -- \
  market_research/data/wiki/08_Claims/2026-04_claim_de1729b413.md \
  market_research/data/wiki/08_Claims/2026-04_claim_e78dc83a1e.md
```

### 10.2 운영 wiki 변경 전체 회귀 (R9-A.21A 까지)

운영 wiki 의 R9-A 트랙 변경은 R9-A.21A 한 번뿐 — 위와 동일.

### 10.3 R9-A 트랙 전체 회귀 (R9-A.5 이후)

```bash
# R9-A.5 직전 hash
git reset --hard 0b00746
```

⚠️ destructive — 의도된 rollback 만 사용. `_promotion_quality.jsonl` /
`data/claims/2026-04.json` md5 는 R9-A.5 이후 변경 없어 본 reset 으로 운영
데이터 회귀는 wiki 만 발생.

### 10.4 부분 rollback table

| 회귀 대상 | hash |
|---|---|
| R9-A.21A 만 회귀 → A.19 보존 | `0ebeba2` |
| R9-A.19 회귀 → A.18 보존 | `f5c27a7` |
| R9-A.18 회귀 → A.17 보존 | `437ce1a` |
| R9-A.17 회귀 → A.14 보존 | `4733d36` |
| R9-A.14 회귀 → A.12 보존 | `5b1fe56` |
| R9-A.12 회귀 → A.10 보존 | `dcbb6d8` |
| R9-A.10 회귀 → A.8 보존 | `df8752f` |
| R9-A.8 회귀 → A.5.1 보존 | `c88449c` |
| R9-A.5.1 회귀 → A.5 보존 | `67c6b45` |
| R9-A 트랙 전체 회귀 | `0b00746` (R9-A.4 close note 직후) |

---

## 11. 결론

R9-A 트랙은 R9-A.5 prompt 보강에서 R9-A.21A wiki lineage 까지 **17 단계** 를
거쳐 기능 개발 + 운영 반영 한 사이클 완료. 처음 R9-A.7 fresh N=7 에서 claim_id
Jaccard 21/21 = 0.0 으로 시작한 미궁이, **text-based identity 폐기 → evidence
+ assets 기반 group_id → multi-run monitoring → 운영 wiki dual-anchor lineage**
의 순서로 정리됨.

핵심 메시지 한 줄:
> **LLM 이 흔들려도 시스템이 흔들리지 않게 만든다** — 운영 identity 는
> deterministic group_id, LLM claim 은 후보 생성기로만 사용.

본 close note 시점에 운영 invariant 6 영역 모두 의도된 변경만 (R9-A.21A wiki
2 파일 lineage 추가) — 그 외 R9-A 전체 기간 변경 0.

다음 monthly cycle 또는 별 트랙 (taxonomy fix / ledger schema / manual_pilot
retrofit / KEEP 8 promote) 진입은 사용자 결정.
