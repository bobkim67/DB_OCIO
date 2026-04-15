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
- `validation_summary`, `evidence_quality`, `evidence_annotations`
- `sanitize_warnings`, `edit_history`
- `token_usage`, `cost_usd`, `model`

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
