# Review Packet v7 — 3-Tier 아키텍처 정리 + 실검증

> 작성일: 2026-04-13
> 범위: `market_research` ↔ `DB_OCIO_Webview` 역할 경계 확정, debate workflow UI, 저장 구조 분리, service layer 분리, client 격리 강화, E2E 실검증
> 한 줄 요약: **3-Tier 구조를 확정하고 코드에 반영했다. 핵심 워크플로우(draft→edit→approve→revoke)와 client 격리는 자동 E2E 테스트로 검증 완료. Streamlit UI 실행은 기동 확인까지. debate 실행(LLM 호출)은 비용 때문에 미실행.**

---

## Part I. 아키텍처

### 3-Tier Runtime Boundary

```
[Tier 1: 외부 배치]              [Tier 2: Streamlit Admin]     [Tier 3: Client]
 market_research CLI/배치          tabs/admin.py (UI)             tabs/report.py
 ─────────────────────            ─────────────────────          ─────────────────
 뉴스 수집                         debate 실행 트리거              approved final만 조회
 분류 (Haiku)                      결과 검토/수정                  합의/테일리스크 (선택)
 정제 (dedupe/salience)            evidence/warning 표시          참고 뉴스 (제목만)
 GraphRAG                          draft 저장                     관련 지표 차트
 timeseries narrative              최종 승인 → final.json
 debate input package              승인 해제 → 재수정
```

### `input.json`의 현재 지위

`io_contract.md`에 input.json 스키마를 정의했지만, **현재는 선택사항(fallback 허용)**이다.

- debate 엔진(`debate_engine.py`)은 직접 뉴스/지표를 읽어 컨텍스트를 빌드한다
- `debate_service.run_debate_and_save()` 주석에 "현재는 input.json 없이 debate 엔진이 직접 컨텍스트를 빌드한다 (과도기 fallback)"로 명시
- `cli.py build --prepare` 옵션은 미구현. 다음 세션에서 구현 후 input 필수화 예정

### role 분리의 현재 수준

`st.session_state['user_role'] == 'admin'` 기반 UI 분기이다.

- **보안/권한 통제가 아니라 운영상 UI 분리**
- production-grade auth는 범위 밖
- client 화면에 final만 노출하는 것은 파일 접근 규칙(`_load_comment_for_client` → `load_final()` only)으로 강제

### `debate_published` 하위호환

기존 `debate_published/{period}.json`은 **임시 fallback**이다.

- admin의 `_load_comment_for_admin()`에서만 최후순위로 접근
- client의 `_load_comment_for_client()`에서는 **접근 불가** (E2E 테스트 검증 완료)
- 최종 source of truth는 `report_output/{period}/{fund}.draft.json` / `.final.json`
- 마이그레이션 종료 시 fallback 제거 대상

---

## Part II. 코드 변경

### 2.1 `market_research/report/debate_service.py` (신규, 310줄)

tabs/admin.py에서 분리한 workflow/service layer. **Streamlit 의존성 없음 (st.* 호출 0건)**.

담당하는 것:
- debate 엔진 호출 (`run_market_debate` / `run_quarterly_debate`)
- evidence annotations 빌드 (`build_evidence_annotations`)
- customer_comment 후처리 (`sanitize_customer_comment` + tense/ref 검증)
- evidence quality 계산
- draft 저장 (`save_draft`) + evidence log append

담당하지 않는 것:
- Streamlit UI (버튼, textarea, expander 등)
- 뉴스 수집/분류/정제/GraphRAG (외부 배치 담당)

### 2.2 `market_research/report/report_store.py` (신규, 226줄)

draft/final JSON 저장·로딩·상태 관리. IO contract 구현체.

핵심 함수: `save_draft`, `load_draft`, `update_draft_comment`, `approve_and_save_final`, `load_final`, `get_status`, `list_approved_periods`, `list_approved_funds`

하위호환: `load_draft()`에서 기존 `debate_published/{period}.json`을 최후순위 fallback으로 인식.

### 2.3 `tabs/admin.py` (재작성, 280줄 → UI only)

**Before**: 741줄. 후처리(sanitize), 검증(tense/ref), evidence 빌드, service 호출, UI가 하나의 파일에.
**After**: 280줄. UI 렌더링만 담당. workflow 로직은 `debate_service`에서 import.

```python
# admin.py import (UI layer)
from market_research.report.debate_service import run_debate_and_save, METRICS_GUIDE
from market_research.report.report_store import load_draft, load_final, get_status, ...
```

### 2.4 `tabs/report.py` (재작성, 560줄)

client/admin **로딩 함수 분리**:

| 함수 | 대상 | final | draft | legacy |
|------|------|-------|-------|--------|
| `_load_comment_for_client()` | Client | O | X | X |
| `_load_comment_for_admin()` | Admin | O | O | O (임시) |

- Client: `list_approved_periods()` → final 있는 기간만 표시. 없으면 "승인된 코멘트가 아직 없습니다."
- Admin: `list_periods()` → 전체 기간. draft/legacy 포함.

### 2.5 문서 (4개 신규/수정)

| 파일 | 내용 |
|------|------|
| `docs/io_contract.md` | input/draft/final 스키마 정의 (input은 현재 선택사항 명시) |
| `docs/architecture_memo.md` | 3-Tier 경계 메모 |
| `CLAUDE.md` | 3-Tier 도식, Runtime Boundary 재작성, TODO 최신화 |
| `market_research/CLAUDE.md` | Purpose에 Boundary 추가, 트리에 5파일 추가 |

---

## Part III. 검증 결과

### 자동 E2E 테스트 (코드 레벨)

| 테스트 | 결과 |
|--------|------|
| **Workflow round-trip**: not_generated → draft → edited → approved → revoked | PASS |
| save_draft → load_draft | PASS |
| update_draft_comment → status=edited + edit_history | PASS |
| approve_and_save_final → final.json (approved=true) | PASS |
| revoke → final 삭제 → status=edited | PASS |
| evidence log append + load | PASS |
| **Client 격리**: draft만 있을 때 client=None | PASS |
| **Client 격리**: final 있을 때 client=final | PASS |
| **Client 격리**: revoke 후 client=None | PASS |
| **Client 격리**: legacy fallback → client 차단 | PASS |
| **Client 격리**: legacy fallback → admin 접근 가능 | PASS |
| **Import chain**: admin.py → debate_service → report_store | PASS |
| **Import chain**: report.py → report_store | PASS |
| debate_service.sanitize 기능 검증 | PASS |

### Streamlit 실행 검증

| 항목 | 결과 |
|------|------|
| `streamlit run prototype.py --server.port 8505` 기동 | PASS (HTTP 200) |
| `ast.parse()` 전체 파일 | PASS |

### 미검증 (비용/시간 사유)

| 항목 | 사유 | 검증 방법 |
|------|------|----------|
| admin debate 실행 버튼 → LLM 호출 | ~$0.34/회 비용 발생 | 다음 세션에서 실행 |
| admin UI textarea 수정 → Draft 저장 | Streamlit 브라우저 조작 필요 | 수동 확인 |
| admin 승인 해제 후 client 화면 갱신 | 브라우저 조작 필요 | 수동 확인 |

---

## Part IV. 저장 구조

### 디렉토리

```
market_research/data/
├── report_output/                  ← 신규 (3-Tier)
│   ├── {period}/
│   │   ├── {fund}.input.json      ← 외부 배치 (현재 미생성, 과도기)
│   │   ├── {fund}.draft.json      ← admin debate 결과
│   │   └── {fund}.final.json      ← admin 승인 (client 유일 접근 대상)
│   └── _evidence_quality.jsonl    ← 누적 evidence 추적
├── debate_published/               ← 기존 (임시 fallback, 마이그레이션 후 제거)
└── report_cache/                   ← 기존 (PA 캐시, 변경 없음)
```

### 상태 전이

```
not_generated → [Debate 실행] → draft_generated → [Draft 저장] → edited → [최종 승인] → approved
                                                                                          │
                                                                            [승인 해제] ───▶ edited
```

---

## Part V. 파일 목록

### 신규 (4개)

| 파일 | 줄수 | 역할 |
|------|------|------|
| `market_research/report/debate_service.py` | 310 | workflow/service layer (Streamlit 의존성 없음) |
| `market_research/report/report_store.py` | 226 | draft/final 저장·로딩·상태 관리 |
| `market_research/docs/io_contract.md` | 249 | input/draft/final 스키마 정의 |
| `market_research/docs/architecture_memo.md` | 111 | 3-Tier 아키텍처 메모 |

### 재작성 (2개)

| 파일 | 줄수 | 변경 |
|------|------|------|
| `tabs/admin.py` | 280 | UI only. workflow 로직은 debate_service로 이동 |
| `tabs/report.py` | 560 | client/admin 로딩 분리. client는 final only |

### 문서 수정 (5개)

| 파일 | 변경 |
|------|------|
| `CLAUDE.md` | 3-Tier 도식, Runtime Boundary 재작성 |
| `market_research/CLAUDE.md` | Purpose에 Boundary + 트리에 5파일 추가 |
| `review_packet_v6.md` | Part VI (아키텍처 정리) 추가 |
| `memory/handoff_insight_engine.md` | 아키텍처+저장구조 추가 |
| `memory/project_insight_engine.md` | 아키텍처 섹션 추가 |

---

## Part VI. 하지 않은 것

| 항목 | 이유 |
|------|------|
| Streamlit 안으로 수집/분류/GraphRAG 이식 | 명시적 금지 |
| Client에 draft/warning/evidence raw 노출 | 명시적 금지 |
| `input.json` 필수화 (--prepare 구현) | 과도기 fallback 허용. 다음 세션 |
| production-grade auth | 범위 밖. 현재는 role flag UI 분기 |
| admin UI 브라우저 수동 테스트 | 자동 E2E로 핵심 로직 검증. UI 수동 검증은 다음 세션 |

---

## Part VII. 다음 세션 TODO

### P0 (파일럿 진입 전 필수)

| # | 작업 | 설명 |
|---|------|------|
| 1 | **admin UI 브라우저 수동 검증** | debate 버튼, textarea 수정, 승인/해제 플로우 |
| 2 | **debate 재실행 2회+** | `_evidence_quality.jsonl` 누적 기록 확보 |
| 3 | **pilot_checklist 13항목 전수** | 전부 PASS 후 파일럿 시작 |
| 4 | **`--prepare` CLI 구현** | input.json 생성 경로. 구현 후 input 필수화 |

### P1 (파일럿 운영)

- gold set 확대, 모델 회귀 테스트, evidence quality 리뷰

---

## Part VIII. 잔여 리스크

| 리스크 | 심각도 | 현재 대응 | 추가 필요 |
|--------|--------|----------|----------|
| debate 실행 시 Streamlit 블로킹 | 중간 | `st.spinner` | 비동기 실행 검토 |
| `debate_published` 하위호환 장기화 | 낮음 | admin only fallback, client 차단 | 마이그레이션 후 제거 |
| input.json 과도기 | 낮음 | debate 엔진이 직접 컨텍스트 빌드 | --prepare 후 필수화 |
| role flag = UI 분기 ≠ 보안 | 낮음 | 내부 운영용 | production auth 필요 시 별도 구현 |

---

*2026-04-13 | 3-Tier 아키텍처 정리 + service layer 분리 + client 격리 강화 + E2E 검증 완료*
*구현 완료와 운영 검증 완료는 다르다. 코드 반영은 마쳤고, UI 수동 검증과 debate 실행은 다음 세션 P0.*
