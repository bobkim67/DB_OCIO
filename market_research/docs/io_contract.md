# IO Contract: market_research <-> DB_OCIO_Webview

> 외부 배치(`market_research`)와 Streamlit(`DB_OCIO_Webview`) 사이의 데이터 인터페이스 정의.
> 이 문서가 두 시스템 간 유일한 계약이다.

## 1. Debate Input Package

**생성 주체**: 외부 배치 (`market_research/report/cli.py build --prepare`)
**저장 경로**: `market_research/data/report_output/{period}/{fund_code}.input.json`
**소비 주체**: Streamlit admin (debate 실행 시 로드)

```jsonc
{
  // ── 식별 ──
  "fund_code": "07G04",
  "period": "2026-Q1",              // "YYYY-MM" 또는 "YYYY-QN"
  "period_type": "quarterly",       // "monthly" | "quarterly"
  "prepared_at": "2026-04-13T14:30:00",

  // ── 시장 컨텍스트 (timeseries narrative) ──
  "market_context": {
    "narrative": "1분기 글로벌 자산시장은...",
    "bm_returns": {
      "MSCI ACWI": -2.3,
      "KIS 종합채권": 1.1
    },
    "macro_snapshot": {
      "UST_10Y": 4.25,
      "UST_2Y": 3.98,
      "USDKRW": 1435.5,
      "VIX": 22.3,
      "Gold": 3120.0
    }
  },

  // ── 뉴스 입력 (debate 재료) ──
  "selected_news": [
    {
      "article_id": "a1b2c3d4e5f6",
      "title": "Fed holds rates steady...",
      "source": "Reuters",
      "date": "2026-03-20",
      "primary_topic": "통화정책",
      "direction": "neutral",
      "intensity": 8,
      "_event_salience": 0.85,
      "is_primary": true
    }
  ],

  // ── GraphRAG 인과경로 ──
  "transmission_paths": [
    {
      "path": ["Fed 동결", "달러 약세", "원화 강세"],
      "confidence": 0.92
    }
  ],

  // ── 펀드 성과 데이터 (PA) ──
  "fund_performance": {
    "pa_summary": {},             // Brinson 3-factor 요약 (있으면)
    "bm_price_patterns": {}       // 지지선/고점/MDD 등
  },

  // ── 메타 ──
  "news_count": 87,
  "primary_count": 15,
  "topic_distribution": {
    "지정학": 3,
    "금리_채권": 2,
    "환율_FX": 2
  }
}
```

### 필수 필드

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `fund_code` | string | Y | 펀드코드 |
| `period` | string | Y | 기간 식별자 |
| `period_type` | string | Y | monthly/quarterly |
| `prepared_at` | ISO datetime | Y | 패키지 생성 시각 |
| `market_context` | object | Y | 시장 컨텍스트 |
| `selected_news` | array | Y | debate 입력 뉴스 |
| `transmission_paths` | array | N | GraphRAG 경로 |
| `fund_performance` | object | N | PA/BM 데이터 |

---

## 2. Draft Output

**생성 주체**: Streamlit admin (debate 실행 버튼)
**저장 경로**: `market_research/data/report_output/{period}/{fund_code}.draft.json`
**소비 주체**: Streamlit admin (검토/수정)

```jsonc
{
  // ── 식별 ──
  "fund_code": "07G04",
  "period": "2026-Q1",
  "status": "draft_generated",     // "draft_generated" | "edited"
  "debate_run_id": "a1b2c3d4e5f6...",  // P1-① v1.4+ — uuid4().hex (32자), run당 1회 발급

  // ── debate 결과 ──
  "draft_comment": "1분기 글로벌 시장은 미 연준의 금리 동결 기조 속에...",
  "admin_summary": "bull-bear 합의: 금리 하반기 인하 전망...",
  "consensus_points": ["..."],
  "disagreements": [{"topic": "...", "bull": "...", "bear": "..."}],
  "tail_risks": ["..."],

  // ── 생성 메타 ──
  "generated_at": "2026-04-13T15:00:00",
  "model": "claude-opus-4-6",
  "token_usage": {"input": 12000, "output": 3500},
  "cost_usd": 0.34,

  // ── 검증 결과 ──
  "validation_summary": {
    "sanitize_warnings": [
      {"type": "fund_action", "message": "...", "severity": "warning"},
      {"type": "tense_mismatch", "message": "...", "severity": "critical", "ref_no": 3}
    ],
    "warning_counts": {"critical": 1, "warning": 1, "info": 2}
  },

  // ── evidence quality ──
  "evidence_quality": {
    "total_refs": 8,
    "ref_mismatches": 1,
    "tense_mismatches": 0,
    "mismatch_rate": 0.125,
    "evidence_count": 15
  },

  // ── evidence 상세 ──
  "evidence_annotations": [
    {
      "ref": 1,
      "article_id": "a1b2c3d4e5f6",
      "title": "Fed holds rates steady...",
      "url": "https://...",
      "source": "Reuters",
      "date": "2026-03-20",
      "topic": "통화정책",
      "salience": 0.85,
      "salience_explanation": "TIER1 매체(Reuters), 교차보도 5건"
    }
  ],

  // ── 수정 이력 ──
  "edit_history": [
    {"edited_at": "2026-04-13T15:30:00", "edited_by": "admin"}
  ]
}
```

### 상태 전이

```
not_generated → [debate 실행] → draft_generated → [수정] → edited → [승인] → approved
                                                                    ↗
                                              draft_generated → [승인] → approved
```

---

## 3. Final Output (Approved)

**생성 주체**: Streamlit admin ("최종 승인" 버튼)
**저장 경로**: `market_research/data/report_output/{period}/{fund_code}.final.json`
**소비 주체**: Client 화면 (tabs/report.py)

```jsonc
{
  // ── 식별 ──
  "fund_code": "07G04",
  "period": "2026-Q1",
  "status": "approved",

  // ── 최종 코멘트 ──
  "final_comment": "1분기 글로벌 시장은...",

  // ── 승인 정보 ──
  "approved": true,
  "approved_at": "2026-04-13T16:00:00",
  "approved_by": "admin",
  "approved_debate_run_id": "a1b2c3d4e5f6...",  // P1-① v1.4+ — draft.debate_run_id 복사
                                                 // legacy final 은 부재 (null 또는 키 없음)

  // ── 생성 메타 (감사 추적용) ──
  "generated_at": "2026-04-13T15:00:00",
  "model": "claude-opus-4-6",
  "cost_usd": 0.34,

  // ── client 표시용 메타 (선택) ──
  "consensus_points": ["..."],
  "tail_risks": ["..."]
}
```

### Client가 읽는 필드

| 필드 | 표시 | 비고 |
|------|------|------|
| `final_comment` | 코멘트 본문 | 필수 |
| `period` | 기간 라벨 | 필수 |
| `approved_at` | 승인일 | 선택 |
| `consensus_points` | 합의 요약 | 선택 |
| `tail_risks` | 리스크 경고 | 선택 |

### Client가 보지 않는 필드

- `draft_comment`, `admin_summary`, `disagreements`
- `sanitize_warnings`, `edit_history`
- `token_usage`, `cost_usd`, `model`
- `internal_metrics_guide`

### Client API enrichment (read-time, 2026-04-30 추가, v1.2 lineage gate)

`/api/market-report` 와 `/api/funds/{fund}/report` 응답의 `data.enrichment` 필드는
**final.json 원본을 patch하지 않고** 읽기 시점에 결합한 보조 정보다. 모든 필드는 optional.

| 섹션 | 우선순위 (위가 우선) | 빈 값 처리 |
|------|---------------------|----------|
| `evidence_annotations` | final → draft → empty | empty list + source="unavailable" |
| `related_news` | final → draft → empty | empty list + source="unavailable" |
| `evidence_quality` | final → draft → `_evidence_quality.jsonl` row (lineage 검증된 것만) | null + source="unavailable" |
| `validation_summary` | final → draft | null + source="unavailable" |
| `indicator_chart` | (P1) | null/빈 series + `unavailable_reason` 명시 |

#### Lineage 정합성 가드 (v1.4 — ID strict matching + timestamp legacy fallback)

**문제**: read-time enrichment는 final 승인 이후 생성된 draft/jsonl 데이터를 결합할
위험이 있음 → 승인본과 다른 lineage의 근거가 client에 노출됨.

**규칙 (위가 우선)**:

> **계약 (must)**:
> - **`final.approved_debate_run_id` 가 존재하면 (값이 비어있지 않은 string) ID strict
>   matching 만 허용한다. timestamp fallback 은 금지한다.**
> - **`final.approved_debate_run_id` 가 없거나 `null` 이면 legacy final 로 간주하고
>   기존 timestamp fallback 을 적용한다.**

1. **`final.approved_debate_run_id` 가 있는 경우 (신규 final, P1-① v1.4+) — ID strict matching 전용**:
   - `draft.debate_run_id == final.approved_debate_run_id` → enrichment 허용 (`matched_by_id`)
   - `_evidence_quality.jsonl` row 도 `row.debate_run_id == final.approved_debate_run_id`
     인 row 만 후보, 그 중 `debated_at`/`created_at` 최신 1건 사용
   - draft 또는 jsonl 에 `debate_run_id` 가 없거나 값이 다르면 차단 (`id_mismatch`)
   - **이 경우 timestamp fallback 금지.** approved_at 보다 timestamp 가 이르더라도
     ID 가 일치하지 않으면 노출하지 않는다. 명시적 lineage ID 가 있는 final 은
     ID 로만 검증한다.
2. **`final.approved_debate_run_id` 가 없거나 `null` 인 경우 (legacy final) — timestamp fallback**:
   - draft.json 의 lineage timestamp 후보 (위가 우선): `generated_at` → `debated_at`
     → `updated_at` → `created_at`. 모두 누락이면 `unverifiable`.
   - `draft/jsonl timestamp <= final.approved_at` → 허용 (`older_than_or_equal_final` / `matched`)
   - timestamp newer / 부재 → 차단 (`newer_than_final` / `unverifiable`)
   - timestamp fallback 은 **legacy final 에서만** 동작한다. 신규 final 에서는 절대 사용되지 않는다.
3. **`final.approved_at` 및 `approved_debate_run_id` 둘 다 없음** → 모든 enrichment `unverifiable` → unavailable.

**status enum (`SourceConsistencyStatus`)**:

| status | 의미 | client 노출 |
|--------|------|------|
| `matched_by_id` | ID strict 일치 (P1-① 권장 경로) | ✓ approved |
| `id_mismatch` | final 에 ID 있는데 draft/jsonl 에 다른 ID 또는 부재 | ✗ unavailable |
| `matched` | legacy: timestamp 정확 일치 | ✓ approved |
| `older_than_or_equal_final` | legacy: timestamp <= approved_at | ✓ approved |
| `newer_than_final` | timestamp > approved_at | ✗ unavailable |
| `unverifiable` | timestamp 누락 또는 검증 불가 | ✗ unavailable |
| `unavailable` | 결합 데이터 자체 부재 | ✗ unavailable |

**ID 발급 위치 (single-write)**:
- 시장 debate: `debate_engine.run_market_debate()` / `run_quarterly_debate()` 가 `uuid.uuid4().hex` 1회 발급. result dict 에 `debate_run_id` 키.
- 펀드 코멘트: `fund_comment_service.generate_fund_comment_and_save()` 가 자체 1회 발급.
- `debate_service.run_debate_and_save()` 는 result 의 `debate_run_id` 를 그대로 draft.json + `_evidence_quality.jsonl` row 에 전파 (재발급 / 덮어쓰기 금지).
- sanitize / 후처리 단계에서 `debate_run_id` 키는 draft_data dict 에 명시 보존되므로 strip 위험 없음.

**ID 복사 (final 승인 시)**:
- `report_store.approve_and_save_final()` 가 `load_draft()` 로 읽어온 payload 의 `debate_run_id` 를 final.json `approved_debate_run_id` 로 복사.
- admin 흐름은 모두 `approve_and_save_final()` 단일 경유 (Streamlit `tabs/admin_macro.py`, `tabs/admin_fund.py` 진단 결과 final 직접 write 우회 경로 없음). admin 우회 경로 발견 시 즉시 보고 대상.

**source 표시 (client vs admin/debug)**:

| 필드 | 노출 대상 | 값 |
|------|---------|----|
| `*_source` | client viewer | `"approved"` (lineage 일치) / `"unavailable"` |
| `*_internal_source` | admin/debug | `"final_json"` / `"draft_json"` / `"evidence_quality_jsonl"` / `"unavailable"` |
| `source_consistency_status` | admin/debug | `"matched"` / `"older_than_or_equal_final"` / `"newer_than_final"` / `"unverifiable"` / `"unavailable"` |
| `source_consistency_reason` | admin/debug | 사람 친화적 진단 메시지 |

**일반 규약**:
- 빈 list/null이면 React 클라이언트가 섹션을 숨김
- approved=false 또는 final 미존재 시 enrichment 자체를 제공하지 않음 (404 분기)
- `_evidence_quality.jsonl` 누락 시에도 200 보장 (해당 섹션만 source="unavailable")
- LLM 재호출 없음. final.json 원본 불변 원칙은 모든 enrichment 단계에서 유지

#### evidence_quality 카운트 의미 분리 (v1.2)

기존 `total_refs` / `evidence_count` / `ref_mismatches` 명칭은 의미 혼동을 일으켜
명시적 alias 를 추가:

| 필드 | 정의 |
|------|------|
| `cited_ref_count` | 본문에서 `[ref:N]` 으로 인용된 ref 개수 (= 기존 `total_refs`) |
| `selected_evidence_count` | debate 가 선정한 evidence article 총 개수 (= 기존 `evidence_count`, 인용되지 않은 보조 기사 포함) |
| `uncited_evidence_count` | `max(0, selected_evidence_count − cited_ref_count)` |
| `ref_mismatch_count` | ref 오매핑 건수 (= 기존 `ref_mismatches`) |
| `mismatch_rate` | `ref_mismatch_count / cited_ref_count` (cited 기준, selected 기준 아님) |

기존 필드(`total_refs`/`ref_mismatches`/`evidence_count`)는 backward compat 용도로
동일 값 mirror 한다. 신규 코드는 명시적 필드 사용 권장.

### Indicator chart P1 사유

P0 (현 구현)에서 indicator_chart는 항상 `unavailable`로 고정. 사유:
- `input.json`의 `market_context.macro_snapshot`은 단일 스냅샷 (point-in-time)이라 series 구성 불가
- `draft.json`에는 시계열이 포함되지 않음
- 정규화된 series를 client에 노출하려면 (a) input.json schema를 macro_snapshot → macro_timeseries로 확장 또는
  (b) `/api/macro/timeseries`를 report 기간에 맞춰 필터링한 series를 합치는 구조가 필요. P1으로 분리.

### Final 원본 불변 원칙

- API service 단에서 final.json 파일을 절대 수정하지 않는다.
- enrichment 결합은 메모리상에서만 일어나며, 응답 직후 폐기된다.
- final.json 자체에 추가 필드를 채우려면 별도 one-time migrator로만 가능하며, 본 viewer는 다루지 않는다.

---

## 4. 디렉토리 구조

```
market_research/data/report_output/
├── 2026-Q1/
│   ├── 07G04.input.json      ← 외부 배치 생성
│   ├── 07G04.draft.json      ← admin debate 실행 결과
│   └── 07G04.final.json      ← admin 승인 최종본
├── 2026-04/
│   ├── 08P22.input.json
│   ├── 08P22.draft.json
│   └── 08P22.final.json
└── _evidence_quality.jsonl    ← 누적 evidence 추적
```

---

## 5. 기존 경로 마이그레이션

| 기존 | 신규 | 비고 |
|------|------|------|
| `data/debate_published/{period}.json` | `data/report_output/{period}/{fund}.draft.json` | 펀드별 분리 |
| `data/report_cache/catalog.json` | 유지 (펀드 메타 전용) | |
| `data/report_cache/{period}/{fund}.json` | `data/report_output/{period}/{fund}.input.json` | 입력 패키지로 전환 |

---

## 6. 버전

| 버전 | 날짜 | 변경 |
|------|------|------|
| v1.0 | 2026-04-13 | 초안 작성 |
| v1.1 | 2026-04-30 | Client API enrichment (read-time) 명시. evidence_annotations/related_news/evidence_quality/validation_summary는 final 미존재 시 draft/jsonl에서 결합. indicator_chart는 P1. final.json 불변 원칙 명문화. |
| v1.2 | 2026-04-30 | Lineage 정합성 가드 추가. draft/jsonl timestamp가 approved_at보다 늦으면 client 차단. internal_source 분리 (admin/debug 전용). source_consistency_status/reason 도입. evidence_quality 카운트 명시적 alias (cited_ref_count/selected_evidence_count/uncited_evidence_count/ref_mismatch_count). |
| v1.3 | 2026-04-30 | **Report viewer enrichment P0 완료.** Client/Internal DTO 분리 (`ClientReportEnrichmentDTO` / `InternalReportEnrichmentDTO`). |
| v1.4 | 2026-04-30 | **P1-① debate_run_id 도입.** draft / jsonl 에 `debate_run_id` (uuid4 hex), final 에 `approved_debate_run_id`. ID strict matching 우선, legacy final 은 timestamp fallback. status enum 에 `matched_by_id` / `id_mismatch` 추가. client note 살균 매핑 갱신. |
| v1.5 | 2026-04-30 | **P1-② admin/debug 전용 enrichment endpoint 도입.** `GET /api/admin/report-enrichment?period=&fund=&limit=` (read-only). client endpoint 와 노출 범위 분리: admin 은 `final_unapproved` 상태도 노출 + InternalReportEnrichmentDTO (internal_source + raw reason) + debate_run_id / approved_debate_run_id 비교. jsonl_rows 는 period+fund 정확 매칭 + debated_at desc + 기본 limit 100, 최대 500. |
| v1.6 | 2026-04-30 | **P1-③ indicator_chart normalized series 도입.** approved final 의 period 범위에 맞춰 read-time 합성한 reference macro context (lineage guard 와 독립). source 별도 enum (`macro_timeseries` / `unavailable`, `approved` 와 분리). 기본 series: USDKRW / PE_SP500 / EPS_SP500. normalize: 첫 유효값=100, raw_value 별도 보존. period 변환: YYYY-MM/YYYY-Q[1-4]. |

---

## 7. Report viewer enrichment P0 — 최종 상태 (2026-04-30 완료)

| 항목 | 상태 |
|------|------|
| P0 완료일 | 2026-04-30 |
| Client endpoint source 노출 | `*_source: "approved" | "unavailable"` 만. internal 라벨 미노출. |
| Internal source 노출 범위 | service 내부 (`InternalReportEnrichmentDTO`) 및 admin/debug 전용. client API 응답 schema 자체에서 제외. |
| Lineage 가드 방식 | **ID strict matching (P1-① v1.4) + legacy timestamp fallback**. 신규 final 은 `approved_debate_run_id` 와 draft/jsonl `debate_run_id` 정확 일치 시에만 결합 허용. legacy final (ID 부재) 은 timestamp 비교로 fallback. |
| 후속 개선 (P1-②, P1-③) | admin/debug 전용 enrichment endpoint, indicator_chart normalized series. |
| client 안내 문구 | `source_consistency_note` (status별 살균된 한 줄). 내부 파일명/draft/jsonl 용어 미포함. raw reason은 internal 모델에만 보존. |
| 테스트 | pytest 86 PASS / openapi:gen / tsc 0 errors. |

### P1 후보 진행 상황

| 항목 | 상태 |
|------|------|
| ① **`debate_run_id` / `approved_debate_run_id` 도입** | **2026-04-30 완료 (v1.4) — PASS.** ID strict matching (신규 final 전용) + legacy timestamp fallback (approved_debate_run_id 부재/null 일 때만). pytest 100/100 PASS, openapi 재생성, tsc 0. client endpoint 에 internal_source / raw reason / debate_run_id / approved_debate_run_id 모두 미노출. |
| ② **admin/debug 전용 enrichment endpoint** | **2026-04-30 완료 (v1.5) — PASS.** `GET /api/admin/report-enrichment` 신규 (내부망/개발자용 read-only). `final_unapproved` 상태 read-only 노출. `InternalReportEnrichmentDTO` + run_id 비교 + jsonl rows. pytest 114/114 PASS, openapi 재생성, tsc 0. client endpoint 회귀 누출 0. **운영 주의: 현재 인증 없는 구조에서 `/api/admin` 경로는 보안 경계가 아님 — 외부 노출 시 인증/권한 가드 필수**. client / admin 노출 범위는 의도적 분리. |
| ③ **`indicator_chart` normalized series** | **2026-04-30 완료 (v1.6) — PASS.** B안 read-time 합성. `macro_service.build_macro_timeseries` 재사용. 기본 series 3종(USDKRW/PE_SP500/EPS_SP500). normalize 첫 유효값=100 + raw_value 보존. lineage guard 독립 (newer_than_final 케이스에서도 indicator_chart 노출). source 별도 enum (`macro_timeseries`/`unavailable`). pytest 127/127 PASS, openapi 재생성, tsc 0. client endpoint 누출 회귀 0. |
| ④ **legacy final backfill 가능성 검토** | 미착수 — 다음 후보. **바로 백필하지 않고 4단계 분리 진행**: ① 기존 `final/draft/jsonl/debate_logs` 간 run_id 역산 가능성 진단 → ② 자동 백필 가능/불가능 케이스 분류 → ③ dry-run report 생성 (실 파일 변경 없음) → ④ dry-run 검토 후 실제 migration 여부 결정. |

---

## 8. Admin / Debug Enrichment Endpoint (v1.5)

`GET /api/admin/report-enrichment?period={YYYY-MM|YYYY-Q[1-4]}&fund={9펀드 또는 _market}&limit=N`

### Client endpoint 와의 노출 범위 차이

| 항목 | client (`/api/market-report`, `/api/funds/{fund}/report`) | admin/debug (`/api/admin/report-enrichment`) |
|------|---|---|
| approved=true final | ✓ 노출 (200) | ✓ 노출 (`final_status="approved"`) |
| approved=false final | ✗ **404 차단** (`REPORT_NOT_APPROVED`) | ✓ **read-only 노출** (`final_status="final_unapproved"`) |
| draft only (final 부재) | ✗ 404 (`REPORT_NOT_FOUND`) | ✓ 200 (`final_status="draft_only"`, enrichment=null) |
| 둘 다 부재 | ✗ 404 | ✓ 200 (`final_status="not_generated"`) |
| `*_internal_source` 5개 | ✗ 미노출 | ✓ 노출 (`InternalReportEnrichmentDTO`) |
| `source_consistency_reason` (raw) | ✗ 미노출 | ✓ 노출 (raw 한국어 메시지, 파일명 등 포함) |
| `source_consistency_note` (살균) | ✓ 살균 노출 | (admin 은 raw reason 우선, note 미사용) |
| `debate_run_id` / `approved_debate_run_id` | ✗ 미노출 | ✓ 노출 (lineage 비교 진단용) |
| `jsonl_rows` (count alias 포함) | ✗ 미노출 | ✓ period+fund 정확 매칭, debated_at desc, 기본 limit 100, 최대 500 |

### `final_unapproved` 상태 정의

`final.json` 이 디스크에 존재하지만 `approved=false` 인 상태. client 라우터는 이 경우
`REPORT_NOT_APPROVED` 로 404 반환하지만, admin 검수용으로는 read-only 노출이 필요하므로
별도 상태값 (`final_unapproved`) 으로 분리한다. admin endpoint 는 이 상태에서도
`InternalReportEnrichmentDTO` 를 빌드하여 lineage 진단을 제공한다 — `matched_by_id` / `id_mismatch`
판정은 `approved` 여부와 무관하게 동작한다.

### 운영 주의 (인증) — 최종 메모

- `/api/admin/report-enrichment` 는 **내부망/개발자용 read-only 진단 endpoint** 다.
- 현재 인증이 없는 구조에서는 **`/api/admin` 경로 자체가 보안 경계가 아니다**.
  경로 prefix 는 의미적 분리를 위한 표시일 뿐 접근 제한이 아니다.
- **외부 노출 운영환경에서는 인증/권한 가드가 별도로 필요하다** (JWT, IP allowlist 등).
- **client endpoint 와 admin endpoint 의 정보 노출 범위는 의도적으로 다르다** —
  client 는 approved=true 인 final 만 + 살균된 source/note 만 노출하고,
  admin 은 final_unapproved 상태 + InternalReportEnrichmentDTO (internal_source / raw
  reason) + run_id 비교 + jsonl rows 까지 노출한다.
- 본 PR (v1.5) 에서는 인증을 구현하지 않는다. 운영 적용 시점에 별도 PR 로 추가한다.

### 화이트리스트

`ALLOWED_DEBATE_FUNDS` 재사용 — 9 운용 펀드 + `_market`. 미일치 fund 422.
period regex `^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$` 미일치 422. path traversal 차단 (`report_store_gateway` `_safe_period_dir` 재사용).

---

## 9. Indicator Chart (v1.6) — Read-time Macro Context

### 정의

`enrichment.indicator_chart` 는 **approved final 에 저장된 근거 데이터가 아니다**.
승인된 보고서의 `period` 범위에 맞춰 조회 시점에 `macro_service.build_macro_timeseries`
를 호출하여 합성한 **참고용 macro context** 다.

### 정책

- **client 노출 조건**: approved final 존재 단 하나. (라우터 `/api/market-report` /
  `/api/funds/{fund}/report` 가 approved 검증 후 호출하는 경로에서만 채워진다.)
- **lineage guard 와 독립**: evidence_annotations / related_news / evidence_quality
  / validation_summary 4개 섹션이 `id_mismatch` / `newer_than_final` / `unverifiable`
  로 차단되더라도 indicator_chart 는 별도로 합성·노출된다.
- **source 라벨**: 다른 enrichment 의 `approved` / `unavailable` 과 분리된 별도 enum
  `IndicatorChartSource = "macro_timeseries" | "unavailable"`.
  - `macro_timeseries`: 합성 성공 (series 1개 이상)
  - `unavailable`: 합성 실패 또는 모든 series 가 빈 결과
- **기본 series (1차)**: `USDKRW`, `PE_SP500`, `EPS_SP500`. `MACRO_DATASETS` 에 매핑이
  없거나 period 내 데이터가 비어 있으면 해당 series skip. 모든 series 가 비면
  `unavailable_reason` 반환.

### Normalization

- 각 series 의 **첫 유효값(non-null, non-zero)을 100 으로** 정규화.
- `IndicatorPointDTO.value` 는 normalized 값 (`raw_value(t) / base_value * 100`).
- `IndicatorPointDTO.raw_value` 는 원 macro 값 (tooltip / 디버그용).
- `IndicatorSeriesDTO.base_date` / `base_value` 는 normalization 기준점.

### Period 변환

- `YYYY-MM` → `(YYYY-MM-01, YYYY-MM-말일)` (윤년 포함 calendar.monthrange 기준)
- `YYYY-Q1~Q4` → `(분기 첫 달 1일, 분기 마지막 달 말일)`
- 그 외 형식 → `unavailable_reason="invalid_period_format"`

### 구현 위치

- DTO: `api/schemas/report.py` (`IndicatorPointDTO`/`IndicatorSeriesDTO`/`IndicatorChartDTO`/`IndicatorChartSource`)
- 합성: `api/services/report_service.py` `_build_indicator_chart` / `_period_to_range` / `_normalize_series_points`
- macro 호출: `api/services/macro_service.py` `build_macro_timeseries(keys, start_date)` 재사용 (외부 배치 / CLI 변경 없음)
- React: `web/src/components/charts/IndicatorChart.tsx` (Plotly client-side 렌더, 서버 Figure JSON 생성 금지). `ReportFinalView` "참고 시장지표" 섹션

### 최종 메모 (v1.6 P1-③ PASS)

- **indicator_chart 는 승인본에 저장된 근거 데이터가 아니라 read-time reference macro context 다.**
- **source 는 `approved` 가 아니라 `macro_timeseries` 다.** (`IndicatorChartSource` 별도 enum)
- **client 노출 조건은 approved final 존재다.** lineage guard 와는 독립적으로 합성된다.
- **chart value 는 raw 값이 아니라 normalized index 다 (첫 유효값=100). `raw_value` 는 tooltip 용으로 보존된다.**
