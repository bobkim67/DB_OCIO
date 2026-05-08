# R9-A.4 Commit 2 작업지시서 — extractor prompt + Haiku call wrapper + dry-run

작성일: 2026-05-08
선행: Commit 1 push 완료 (`812aaa8`, origin/main)
입력: mini-spec `r9a4_minispec.md` (Decisions D-1~D-8 fix), Review Packet `r9a_review_packet_pre_a4.md`

본 문서는 R9-A.4 Commit 2 코드 진입 전 작업지시서. **현재 단계 코드 변경 0**.
사용자 검토 + 미결정 항목 fix 후 별 트랙으로 구현 진입.

---

## 1. 목표 (Goals)

1. R9-A.1 manual pilot 의 Haiku extractor 를 daily_update Step 2.7 흐름에 연결
2. **운영 default 는 계속 OFF** — flag/CLI override 시에만 LLM 호출
3. Dry-run 경로 우선 — LLM 호출 가능 여부와 file write 를 별도 flag 로 분리
4. R9-A.0 deterministic claim_id + validator 재사용 → R9-A.1 pilot 결과와 비교 검증 가능
5. invalid raw response 는 D-3 결정값대로 `debug/claims/` 에 dump (gitignored)

## 2. Non-goals (Commit 2 미포함)

- **`data/claims/{period}.json` 실제 write** (Commit 3 또는 dry-run-without-write flag 까지)
- **`wiki/08_Claims/*.md` 실제 write** (Commit 3 후행)
- `_promotion_quality.jsonl` append (Commit 3 후행)
- daily_update default ON 전환 (R9-A.6 운영 사이클까지 OFF)
- Out-of-band guard 의 admin override flag 노출 (Commit 4 CLI 트랙)
- Cost cap 위반 시 ledger row 의 정식 schema (Commit 3 failure handling 트랙)
- Sonnet/Opus 비교 검증 (R9-A.4 close 후 별 트랙, D-8 future option)

## 3. 변경 예상 파일 (Commit 2)

| 파일 | 종류 | 변경 |
|---|---|---|
| `market_research/analyze/claim_extractor_prompt.py` | NEW | Haiku prompt template + system prompt + version 메타 (D-5) |
| `market_research/analyze/claim_extractor_runner.py` | NEW | LLM call wrapper — input(period, evidence) → output(claims, invalid, usage). LLM 호출 진입점 |
| `market_research/pipeline/claim_extract_step.py` | modify | `step_claim_extract` 가 enabled 시 runner 호출. dry-run 분기. file write 0 (Commit 3 까지 보류) |
| `market_research/tests/test_claim_extractor_runner.py` | NEW | LLM monkeypatch + prompt 검증 + cost cap + invalid 분리 + dry-run no-write |
| `market_research/tests/test_claim_extract_step_skeleton.py` | modify | Commit 1 회귀 + dry-run 경로 추가 검증 |

총 신규 3 file + 변경 2 file. LOC 추정: +400 / -10.

## 4. Public API (설계)

### 4.1 `claim_extractor_prompt.py`

```python
EXTRACTOR_VERSION = "r9a.4-haiku"
SOURCE = "daily_update_r9a4"
LLM_MODEL = "claude-haiku-4-5-20251001"   # D-8 Haiku 고정
MAX_TOKENS = 16384                          # R9-A.1 pilot 동일
MAX_INPUT_EVIDENCE = 50                     # R9-A.1 default

SYSTEM_PROMPT: str = """..."""               # R9-A.1 manual pilot 그대로 + version 라벨

def build_extraction_prompt(period: str, evidence: list[dict]) -> dict:
    """LLM 호출용 messages dict 구성.
    
    Returns:
        {"system": str, "user": str, "model": str, "max_tokens": int}
    """
```

설계 결정:
- R9-A.1 manual pilot 의 prompt 본문은 **그대로 복사** (deterministic ID 일관성). version label / source 만 r9a.4-haiku / daily_update_r9a4 로 분리.
- Manual pilot 코드 (debug/claims/r9a1_*) 는 미수정 — 운영 batch 와 명확히 분리 (D-5).

### 4.2 `claim_extractor_runner.py`

```python
def extract_claims(
    period: str,
    evidence: list[dict],
    *,
    max_evidence: int = 50,
    cost_cap_per_run: float = 0.5,    # D-4
    cost_cap_monthly: float = 1.0,    # D-4
    invalid_dump_dir: Path | None = None,  # D-3 default debug/claims/
) -> dict:
    """Haiku extractor 호출 + validate + 분리.

    Returns:
        {
            "claims": list[dict],              # validate 통과
            "invalid": list[dict],             # validate 실패 (raw + reason)
            "raw_response": str,               # 원본 LLM 출력 (debug 용)
            "usage": {"input_tokens", "output_tokens"},
            "cost_usd": float,
            "elapsed_seconds": float,
            "extractor_version": "r9a.4-haiku",
            "source": "daily_update_r9a4",
            "abort_reason": str | None,        # cap 위반 등
            "warnings": list[str],
        }

    Failure modes (D-6 graceful):
        - LLM API 실패 → return {"claims": [], "abort_reason": "llm_api_failure", ...}
        - Cost cap 위반 → return {"claims": [], "abort_reason": "cost_cap_exceeded", ...}
        - 응답 JSON 파싱 실패 → invalid 1건 dump + return {"claims": [], "warnings": [...]}
        - 0 claim 추출 → return {"claims": [], "warnings": ["no_claims_extracted"]}
        모든 case 에서 raise 0 (daily_update 전체 graceful)
    """
```

### 4.3 `claim_extract_step.py` 변경

```python
# 기존 ENABLE_CLAIM_EXTRACTION 그대로
# step_claim_extract 시그니처 확장:

def step_claim_extract(
    period: str,
    *,
    enabled: bool | None = None,
    target_suffix: str | None = None,
    write_canonical: bool = False,    # Commit 2 단계 default False (write 차단)
    write_wiki: bool = False,          # 동일
    write_ledger: bool = False,        # 동일
    evidence: list[dict] | None = None,  # daily_update 가 refine 결과 주입
) -> dict:
    """Step 2.7 진입점.

    Commit 1 (skeleton): enabled=False → status=disabled
    Commit 2: enabled=True + evidence 주어지면 runner 호출 (LLM 1 call).
              write_* flag 모두 False → file write 0 (dry-run path).
    Commit 3+: write_* flag 활성화 시 canonical/wiki/ledger 실 write.

    Returns 확장:
      + "extraction": runner 결과 (claims/invalid/usage/cost) 또는 None
      + "would_save": [{"path", "kind"}, ...] (dry-run 모드에서 write 예정 list)
      + "actually_saved": []  (Commit 2 단계 항상 빈 list)
    """
```

## 5. Dry-run 모드 정의

| flag | LLM 호출 | file write |
|---|---|---|
| `enabled=False` (default) | 0 | 0 |
| `enabled=True`, `write_canonical=False`, `write_wiki=False`, `write_ledger=False` | **1 (Haiku)** | **0** |
| `enabled=True`, `write_canonical=True`, ... (Commit 3+) | 1 | actual writes |
| `enabled=True`, `evidence=None` | 0 (skip + warning) | 0 |

Commit 2 는 두 번째 행까지만 지원. 세 번째 행 (실 write) 은 Commit 3 에서 각 write target 별 flag 활성화.

`invalid_dump_dir` 만 default `debug/claims/` 로 활성화 — D-3 결정값. invalid 가 있으면 항상 dump (write 차단 flag 와 무관). 단, `debug/claims/` 자체가 gitignored 라 정식 산출물 아님.

## 6. Cost cap 동작 (D-4)

### Per-run cap ($0.5)
```python
# 호출 직전 max_input_tokens / max_output_tokens 로 추정 비용 계산
# Haiku 가격: $0.80/M input, $4/M output (대략)
# max_tokens=16384, input ~6500 → 추정 < $0.10
# 실 호출 후 actual usage 로 사후 검증
if estimated_cost > cost_cap_per_run:
    return {"abort_reason": "cost_cap_exceeded_estimate", ...}
```

### Monthly cap ($1)
```python
# _promotion_quality.jsonl (gitignored) 또는 별도 ledger 의 직전 30일 cost_usd 합산
# 합산 + 추정 > $1 → abort
```

Commit 2 단계: per-run cap 만 구현. monthly cap 은 ledger 정식 schema 가 필요해 Commit 3 에서.

## 7. Failure handling 매트릭스 (Commit 2 범위)

| 실패 유형 | 동작 | warnings 메시지 |
|---|---|---|
| LLM API 실패 (network/auth) | abort_reason="llm_api_failure" | f"Haiku API 실패: {exc}" |
| Cost cap 추정 초과 | abort_reason="cost_cap_exceeded_estimate" | f"추정 ${est} > cap ${cap}" |
| 응답 JSON 파싱 실패 | invalid 1건 + raw_response | "json_parse_failed" |
| validator 실패 (1건씩) | invalid 분리 + valid 만 반환 | f"validator failed: {claim_id}" |
| 0 claim 추출 (LLM 빈 응답) | return {"claims": []} | "no_claims_extracted" |
| evidence 비어있음 | runner 호출 0, abort_reason="no_evidence" | "evidence_empty" |

모든 case 에서 raise 0 — `step_claim_extract` 가 graceful status 반환. daily_update 전체 진행 보장.

Commit 3 에서 각 case 별 ledger row schema 확정 + monthly cap 구현 + out-of-band guard 통합.

## 8. 테스트 계획

### Commit 2 신규 (`test_claim_extractor_runner.py`, ~12 cases)

1. **prompt 빌드 검증** — `build_extraction_prompt(period, evidence)` 가 system / user / model / max_tokens 모두 채움
2. **LLM monkeypatch — 정상 응답** — 22 valid claims 시뮬, runner 가 claims 22 / invalid 0 반환
3. **LLM monkeypatch — invalid mixed** — 20 valid + 2 invalid 시뮬, 분리 동작
4. **LLM monkeypatch — 0 claim** — 빈 응답, abort_reason None / warnings ["no_claims_extracted"]
5. **LLM API 실패** — `_call_llm` 이 Exception → abort_reason="llm_api_failure" + raise 0
6. **JSON 파싱 실패** — non-JSON raw response → invalid 1 + warnings
7. **Cost cap 추정 초과** — input_tokens 인위적 large → abort_reason="cost_cap_exceeded_estimate"
8. **evidence 빈 list** — abort_reason="no_evidence", LLM 호출 0
9. **deterministic claim_id** — R9-A.0 compute_claim_id 와 일관 (R9-A.1 pilot 과 동일 입력 시 동일 ID)
10. **invalid raw dump path** — `debug/claims/{period}.invalid.{ts}.json` 형식 (실 write 는 monkeypatch 로 차단)
11. **extractor_version / source 메타** — 모든 claim 에 r9a.4-haiku / daily_update_r9a4 라벨
12. **prompt 안정성** — period / evidence 동일 시 build_extraction_prompt 출력 동일 (deterministic)

### `test_claim_extract_step_skeleton.py` 보강 (+4 cases)

1. **enabled=True + evidence 주입 + write_* False** — runner 호출, file write 0
2. **enabled=True + evidence=None** — runner 호출 0, no_evidence warning
3. **enabled=True + LLM mock 실패** — daily_update 전체 graceful (Step 2.7 status="error_caught", 다음 step 진행)
4. **would_save 필드** — dry-run 모드에서 write 예정 list 만 반환, actually_saved=[]

### 기존 회귀
- 기존 384 PASS 모두 유지
- 특히 R9-A.0 / R9-A.1 deterministic ID / R9-A.2 promotion / R9-A.3 read-side / R9-A.5 trace surface 회귀 0

## 9. Smoke 계획 (Commit 2 close 후 사용자 GO)

### 9.1 LLM 0 dry-run (Commit 2 단위 검증)
```bash
# evidence 없이 호출 — runner 호출 0 보장
python -c "from market_research.pipeline.claim_extract_step import step_claim_extract; \
            print(step_claim_extract('2026-04', enabled=True))"
```
기대: `abort_reason="no_evidence"`, file write 0

### 9.2 LLM 1회 dry-run (실 LLM 호출, write 0)
```bash
# daily_update 호출 또는 직접
python -c "
from market_research.pipeline.claim_extract_step import step_claim_extract
import json
evidence = json.loads(...)  # 2026-04 refined evidence 50건
out = step_claim_extract('2026-04', enabled=True, evidence=evidence)
print(out['extraction']['claims'][:2])
print(out['actually_saved'])  # []
"
```
기대:
- 22 valid claims 추출 (R9-A.1 pilot 와 유사)
- claims 모두 r9a.4-haiku / daily_update_r9a4 라벨
- file write 0 (`actually_saved == []`)
- `data/claims/2026-04.json` md5 변경 0
- 비용 ~$0.05

### 9.3 daily_update 진입 검증
```bash
ENABLE_CLAIM_EXTRACTION=1 python -m market_research.pipeline.daily_update 2026-04 --dry-run
```
(env var 설정 등은 Commit 4 CLI 트랙에서 정식화)

기대: Step 2.7 가 LLM 1회 호출 후 status 출력, write 0

## 10. Rollback plan

- Commit 2 회귀 시: `git revert 812aaa8..HEAD` (Commit 1 보존, Commit 2 만 reset)
- runner 모듈 disable: `claim_extractor_runner.py` 의 `extract_claims` 시작부에 `raise NotImplementedError` 또는 step_claim_extract 의 enabled 분기 short-circuit
- 운영 default 는 계속 OFF — runner 가 호출되어도 운영 영향 0

## 11. 구현 GO 전 확인할 결정사항

| # | 항목 | 후보 | default 추천 |
|---|---|---|---|
| **C2-Q1** | evidence 주입 path | (A) daily_update 가 Step 2.5 결과 dict 직접 전달 (B) `_load_month_articles` 등 파일 read | **(A)** — 메모리 직접 전달, file I/O 0 |
| **C2-Q2** | LLM 호출 wrapper | (A) `market_research.report.debate_engine._call_llm` 재사용 (B) 신규 helper | **(A)** — 기존 cost tracking 재사용 |
| **C2-Q3** | invalid dump 시점 | (A) runner 내부 (자동 dump) (B) 호출자가 결정 | **(B)** — runner 는 invalid list 만 반환, dump 는 step_claim_extract 가 (write_* flag 와 일관) |
| **C2-Q4** | cost cap 추정 vs 사후 | (A) 사전 추정만 (B) 사전 추정 + 사후 actual 검증 | **(B)** — 사후 actual > cap 도 warning |
| **C2-Q5** | prompt 본문 출처 | (A) R9-A.1 pilot 코드 그대로 복사 (B) Manual pilot 결과를 docs 에서 다시 정리 | **(A)** — deterministic ID 일관성 |
| **C2-Q6** | extractor_version 변경 시 cache 무효화 | (A) cache layer 0 (B) period 별 cache 도입 | **(A)** — Commit 2 범위 외, 후행 트랙 |
| **C2-Q7** | `_call_llm` retry 정책 | (A) 0 retry (B) 1회 retry (5초 backoff) | **(A)** — 단순, daily_update 다음 호출에서 자동 재시도 가능 |
| **C2-Q8** | LLM 응답 streaming 처리 | (A) blocking 단일 호출 | **(A)** — Commit 2 단순화 |

8개 모두 default 옵션 명확. 사용자가 다른 안 선호 시 결정 후 진입.

## 12. 구현 commit split 제안 (Commit 2 본체)

| Sub-commit | 범위 |
|---|---|
| C2-α | `claim_extractor_prompt.py` 신설 (prompt template, 호출 0) + import 만 검증 |
| C2-β | `claim_extractor_runner.py` 신설 (`extract_claims` 본체, LLM 호출 + validator) + LLM monkeypatch unit test |
| C2-γ | `claim_extract_step.py` 확장 (write_* flag, evidence 주입, runner 호출) + step 보강 test |
| C2-δ | (옵션) cost cap 정식화 + invalid raw dump 정식화 |

α → β → γ → δ 순. 사용자 단계별 검토 게이트.

대안: 단일 Commit 2 로 묶어도 OK (~400 LOC, 회귀 명확).

## 13. Acceptance criteria (Commit 2 close)

- [ ] `claim_extractor_prompt.py` import + system_prompt / build_extraction_prompt 시그니처 안정
- [ ] `claim_extractor_runner.extract_claims` 가 mock 환경에서 22 valid claims 정상 반환
- [ ] LLM 호출 0 sub-smoke (evidence=None 시 runner 호출 0)
- [ ] LLM 1회 dry-run smoke — claims 추출 + write 0 + 비용 < $0.5
- [ ] R9-A.0 deterministic ID — R9-A.1 pilot 과 동일 입력 시 동일 claim_id
- [ ] 운영 default 계속 OFF — `ENABLE_CLAIM_EXTRACTION=False`
- [ ] Failure 6 유형 모두 graceful (raise 0)
- [ ] 보호 영역 변경 0:
  - `data/claims/2026-04.json` md5 da3fed58... 동일
  - `wiki/08_Claims/*.md` mtime 동일
  - `_promotion_quality.jsonl` row 1 그대로
  - `_market.final.json` md5 81eb876b... 동일
  - `regime_memory.json` md5 1ee7151c... 동일
- [ ] 기존 384 PASS + 신규 test 모두 PASS

## 14. 다음 신호 옵션 (사용자 결정 대기)

| 신호 | 액션 |
|---|---|
| **"C2-Q1~8 default 그대로, Commit 2 구현 시작"** (1순위 추천) | C2-α → β → γ 순 sub-commit 진입 |
| "C2-Qx 결정값 다른 안" | 해당 항목 fix 후 구현 시작 |
| "Commit 2 작업지시서 수정 — {섹션}" | 보강 (코드 0) |
| "Commit 2 작업지시서 도 commit" | docs/ 1 path staging |
| "Commit 2 보류, 별 트랙" | R9-A.4 잠시 보류 |

본 작업지시서 자체는 untracked 상태로 두고, 사용자 commit 결정 별로 처리.

---

## 15. 보호 영역 invariant (Commit 2 진입 전)

| 영역 | 현재 |
|---|---|
| `regime_memory.json` md5 | `1ee7151c8c381217c7b34393b0054daf` |
| `data/claims/2026-04.json` md5 | `da3fed58512829099a624ddb5fc1c85f` |
| `_market.final.json` md5 | `81eb876ba8b82b23a2a3dcec3de2f5bc` |
| `07G04.final.json` md5 | `f522cd673c8df342c21459990e86eff1` |
| `wiki/08_Claims/*.md` 파일 수 | 8 |
| `_promotion_quality.jsonl` row | 1 |
| daily_update Step 2.7 default | OFF |
| origin/main | `812aaa8` (Commit 1 push 직후) |

Commit 2 close 시점에도 위 invariant 모두 동일해야 함.
