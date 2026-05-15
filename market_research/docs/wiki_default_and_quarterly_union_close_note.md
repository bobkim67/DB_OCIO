# Wiki Context Pack Viewer + WIKI-DEFAULT.1 + R9-B.5 quarterly union — Close Note

**date**: 2026-05-15
**origin/main**: `b4a9347`
**LLM cost (this session)**: ≈ $2.04
**LLM cost (cumulative across R9-B + R9-B.6C + this session)**: ≈ $13.99

## 1. 트랙 개요

R9-B 본 트랙 + R9-B.6C close (origin=`3048986`) 이후, R9-B 의 wiki context pack 을 (a) 노출 (viewer) + (b) default 화 + (c) quarterly multi-month union 으로 확장한 단일 세션.

| 트랙 | commit | LOC | LLM |
|---|---|---|---|
| Wiki Context Pack Viewer | `80bb043` | +1092 / -1 | 0 |
| WIKI-DEFAULT.1 default 전환 + 5 final promote | `b826e31` + suffix rebuild | +123 / -54 + promote scripts | $1.70 |
| R9-B.5 quarterly union builder/preview | `b39a78d` | +486 / -18 | 0 |
| R9-B.5.6 quarterly wiring + Q1 LLM smoke + promote | `b4a9347` + promote scripts | +177 / -19 | $0.34 |

## 2. Wiki Context Pack Viewer (commit `80bb043`)

### 산출

- `api/services/wiki_context_pack_gateway.py` — `build_wiki_context_pack` 래퍼 + `data/claims/*.json` 스캔 기반 period 후보 노출
- `api/services/wiki_page_gateway.py` — `WIKI_ROOT` 산하 .md 단일 파일 frontmatter+body (traversal 가드)
- `api/schemas/wiki_context_pack.py`, `wiki_page.py` — DTO
- `api/routers/admin.py` — `/admin/wiki-context-pack`, `/admin/wiki-context-pack/periods`, `/admin/wiki-page`
- `web/src/api/generated/openapi.d.ts` — 재생성
- `web/src/api/endpoints.ts` — fetcher 3종 + 타입 alias
- `web/src/hooks/useWikiContextPack.ts` — `useWikiContextPackPeriods` / `useWikiContextPack` / `useWikiPage`
- `web/src/tabs/AdminWikiContextPackPanel.tsx` — period/stage/fund/max_pages 선택 + summary chips + path → 인라인 본문
- `web/src/tabs/AdminTab.tsx` — "Wiki Context Pack" 서브탭 추가

### 검증

- FastAPI smoke 8 케이스 PASS (monthly / quarterly / fund_comment / bad period / bad path / traversal / missing page)
- tsc --noEmit 통과

## 3. WIKI-DEFAULT.1 — wiki-first default 전환 (commit `b826e31`)

### 정책 요약

`use_wiki_context_pack` default `False → True`. opt-out 은 `--no-wiki-context-pack` CLI flag 또는 함수 인자 `=False`. `--use-wiki-context-pack` 은 deprecated no-op 보존.

`prompt_context_mode` 라벨:
- `wiki_context_pack_default` (default)
- `legacy_raw_first_opt_out`

### 변경 파일

| 파일 | 변경 |
|---|---|
| `market_research/report/debate_engine.py` | `run_market_debate` / `run_quarterly_debate` default ON + trace 라벨 |
| `market_research/report/debate_service.py` | `run_debate_and_save` default ON |
| `market_research/report/cli.py` | `_run_debate` / `build_report` default ON + `--no-wiki-context-pack` flag + 가드 |
| `market_research/tests/test_debate_engine_r9b3_wiki_context_pack.py` | 기존 default 가정 test 갱신 + 신규 `test_run_market_debate_no_flag_uses_wiki_default` |
| `market_research/tests/test_report_store_r9b31_target_suffix.py` | stub trace 라벨 갱신 |

### Promote 5건 (운영 `_market.final.json`)

| period | mode | source_generation_mode | pre md5 | post md5 |
|---|---|---|---|---|
| 2026-01 | initial | wiki_context_pack_default_initial | (부재) | `a716a03d76c0f9192a330557849094a8` |
| 2026-02 | initial | wiki_context_pack_default_initial | (부재) | `c0699b72a127ba924239e705df2899dc` |
| 2026-03 | initial | wiki_context_pack_default_initial | (부재) | `fe1990649013a4b893f47014d0c7eeb9` |
| 2026-04 | overwrite | wiki_context_pack_default_rebuild | `81eb876ba8b82b23a2a3dcec3de2f5bc` | `cb3da19ce1400abb142d210ad0550f5a` |
| 2026-Q1 (1차) | initial | wiki_context_pack_default_initial | (부재) | `c14902419383940331e8f9d1831391f2` (human_edit_trace 1) |

target_suffix = `wiki-default-rebuild`. 사용자 부분 승인 흐름으로 promote. Q1 1차 final 은 R9-B.5.6 에서 다시 overwrite (아래 참조).

## 4. R9-B.5 multi-month quarterly union builder/preview (commit `b39a78d`)

### 핵심

`build_wiki_context_pack` 가 분기 전체 월의 claim_store union + wiki layer 분기 window selection 지원.

```python
build_wiki_context_pack(
    period_key="2026-Q1",        # quarter label
    period_type="quarterly",
    period_keys=["2026-01","2026-02","2026-03"],  # auto-unpack 또는 명시
    stage="quarterly_debate",
    max_pages=30,
)
```

### 변경 파일

- `market_research/report/wiki_context_pack_builder.py` — `_quarter_to_period_keys` / `_resolve_request_window` quarterly 분기 / `_build_claim_section` multi-period union (dedup by claim_id) / `build_wiki_context_pack(period_keys=...)` / 응답 schema 에 `period_keys`, `source_trace.claim_store_selected_count_by_period` 추가
- `market_research/tools/build_wiki_context_pack.py` — `--period-type quarterly`, `--period-keys` CSV 옵션
- `api/services/wiki_context_pack_gateway.py` — `PERIOD_MONTHLY_RE` / `PERIOD_QUARTER_RE` / `parse_period_keys_csv`
- `api/routers/admin.py` — `/admin/wiki-context-pack` 에 `period_type`, `period_keys` query + 정합성 가드 (monthly+period_keys → 400, quarterly+monthly key 단독 → 400, bad period_keys item → 400)
- `api/schemas/wiki_context_pack.py` — `period_keys`, `period_type` 노출
- `web/src/api/generated/openapi.d.ts` — 재생성
- `market_research/tests/test_wiki_context_pack_builder.py` — quarterly union 8 케이스 신규

### 2026-Q1 preview (LLM 0)

| 지표 | 값 |
|---|---|
| period_keys | `['2026-01','2026-02','2026-03']` |
| window | `2026-01-01 ~ 2026-03-31` |
| selected_claim_ids | 16 (4+5+7 union) |
| claim_store_to_wiki_join_rate | 1.0 |
| source_cutoff_violations | 0 |
| source_type_counts (cap=30) | claim 16 + graph 2 + regime 2 + event 4 + asset 3 + entity 3 |

monthly 회귀 (2026-03 / 2026-04 selected=12, claims=7/3, join=1.0, cutoff=0, period_keys 단일 원소): PASS.

## 5. R9-B.5.6 quarterly wiring + Q1 LLM smoke + promote (commit `b4a9347`)

### Wiring

`run_quarterly_debate` 가 builder 를 `period_type='quarterly' + period_keys=[3개월] + period_key='YYYY-QX'` 로 호출. quarterly default `max_pages=30`.

```
run_quarterly_debate(2026, 1, use_wiki_context_pack=True, wiki_context_max_pages=30)
   ↓
_build_wiki_context_pack_for_debate(
     period_key='2026-Q1',
     period_type='quarterly',
     period_keys=['2026-01','2026-02','2026-03'],
     stage='quarterly_debate',
     fund_code=None,
     max_pages=30,
)
```

`_wiki_context_pack_trace` 가 quarterly 필드 surface (`wiki_context_pack_period_type`, `wiki_context_pack_period_keys`, `claim_store_selected_count_by_period`).

`debate_service.run_debate_and_save(wiki_context_max_pages: int | None = None)` sentinel → mode 기반 default (`monthly=12`, `quarterly=30`).

### Q1 LLM smoke (target_suffix=`r9b5-quarterly-union`, $0.34)

| 항목 | 값 |
|---|---|
| starts_with_error | False |
| prompt_context_mode | `wiki_context_pack_default` |
| wiki_context_pack_enabled | True |
| period_keys | `['2026-01','2026-02','2026-03']` |
| selected_claim_ids | 16 (4+5+7 by_period union) |
| join_rate | 1.0 |
| source_cutoff_violations | 0 |
| wiki_pages_selected | 30 |
| 본문 `[claim:hash10]` 인용 | 0 / 16 (LLM 분기 narrative-first 한계) |
| 본문 `[ref:N]` 인용 | 16 |
| chars | 3,709 |

### Q1 본문 patch 4종 (사용자 지시)

| # | 위치 | 변경 |
|---|---|---|
| 1 | 3월 환율 | "1,500원을 목전" → "1,500원을 돌파하며 17년 만의 최저" (종합 단락과 일관) |
| 2 | 3월 주식 급락 | "6%대 급락" → "6.49% 급락, 코스닥 5.56% 하락" (정밀 수치 복원) |
| 3 | 3월 반등 | "코스피 2.74% 반등" → "코스피 2.74%, 코스닥 2.24% 반등" (코스닥 보강) |
| 4 | 3월 금 | "7.9% 폭락" → "7.9% 조정" (WIKI-DEFAULT.1 1차 patch 톤과 일치) |

`_apply` 에 ref shift fallback (`ref:NN ↔ ref:NN±1`) 도입 — sanitize 가 ref 번호 재매핑하므로 raw/sanitized 양쪽 본문 동시 patch.

### Q1 final overwrite

| 항목 | 값 |
|---|---|
| pre md5 | `c14902419383940331e8f9d1831391f2` (WIKI-DEFAULT.1 promote 결과) |
| backup | `_market.final.legacy-backup-20260515T171538.json` |
| post md5 | `a0d65552089c970213266419f0a96afb` |
| source_generation_mode | `wiki_context_pack_quarterly_union_rebuild` |
| human_edit_trace | 4 patches |
| chars | 3,748 |

## 6. 운영 invariant (트랙 전체 후)

| 영역 | 상태 |
|---|---|
| `_market.final.json` 5건 (01/02/03/04/Q1) | 갱신 완료 — 모두 사용자 승인 흐름 거침 |
| `_market.draft.json` mtime | 변경 0 (prior session 그대로) |
| `_market.input.json` | 부재 그대로 |
| `wiki/06_Debate_Memory/` 새 파일 | 0 (target_suffix → writer skip 정상) |
| `wiki/` 운영 페이지 | 변경 0 |
| `data/regime_memory.json` | 변경 0 |
| `data/claims/` | 변경 0 |
| `data/debate_logs/2026-Q1.json` | LLM smoke 1회로 갱신 (gitignored, debug 백업 2건 보존) |
| `_evidence_quality.{wiki-default-rebuild, r9b5-quarterly-union}.jsonl` | suffix 격리 |
| 운영 final legacy backup 2종 | `_market.final.legacy-backup-{20260515T125507, 20260515T171538}.json` 보존 |

## 7. 테스트

| suite | 결과 |
|---|---|
| `test_debate_engine_r9b3_wiki_context_pack.py + test_wiki_context_pack_builder.py + test_report_store_r9b31_target_suffix.py` | 121/121 PASS (기존 72 + 신규 49) |
| `pytest market_research/tests/ -k r9b` | 81/81 (name match) PASS |
| `pytest api/tests/` | 220/220 PASS |
| `tsc --noEmit` (web) | 0 errors |

기존 R9-A.4 baseline test (`test_r9a4_93a_smoke.py`) 의 3건 md5/count failure 는 R9-B.6C backfill 의 stale baseline 결과 — 본 트랙 무관.

## 8. 별 트랙 후보 (close 후 갱신)

| 후보 | 우선순위 | 비용 | 진입 조건 |
|---|---|---|---|
| 본문 `[claim:hash10]` 인용 강화 | P2 | LLM 0 (prompt) | quarterly Q1 본문 0 / 16 — prompt instruction 보강 |
| R9-B.4.2 debate_logs suffix 분리 | P3 | LLM 0 | `data/debate_logs/{period}.json` 매 run overwrite. suffix 격리. |
| Sonnet fallback 영구 도입 | P3 | LLM 0 | Opus overload 빈도 운영 영향 시 — 본 트랙 미발생 |
| wiki/canonical promotion_rule 동기화 | P5 | LLM 0 | 2026-03 7 force_only claim 의 wiki=C / canonical=None (read-side 영향 0) |
| AdminWikiContextPackPanel quarterly dropdown | P3 | LLM 0 | UI 에 2026-Q1 등 quarterly period 노출 (현재 monthly only) |

## 9. PASS 판정

- ✅ Wiki Context Pack Viewer (read-only) — FastAPI 8 분기 smoke / tsc 통과
- ✅ WIKI-DEFAULT.1 default 전환 — 5 final promote 완료, prompt_context_mode 라벨 일관
- ✅ R9-B.5 quarterly union — period_keys schema 통일, monthly 회귀 0
- ✅ R9-B.5.6 wiring — Q1 LLM smoke 검증 12/13 PASS (1개 HOLD = 본문 claim citation 0건, prompt 한계로 본질적 별 트랙)
- ✅ 운영 invariant 모두 PASS (final 5건만 사용자 승인 흐름으로 갱신, 그 외 0)

R9-B 전체 트랙 close.
