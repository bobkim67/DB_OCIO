# Review Packet v6 — 파일럿 진입 준비 보고서

> 작성일: 2026-04-13
> 범위: v4/v5 외부 리뷰 → 취약점 구현 → 운영 체계 구축
> 한 줄 요약: **기술적 뼈대는 파일럿 가능 수준에 도달했지만, evidence 안정성과 운영 회귀 관리가 아직 완성되지는 않았다.**

---

## Part I. 이번 세션에서 완료한 것

### 1. 외부 리뷰 수행

v4/v5 + 관련 문서 7건 + **소스코드 12항목 전수 대조**.
문서의 모든 주요 주장이 실제 구현과 일치함을 확인.

### 2. 코드 변경 (5개 파일, 221줄 추가/13줄 삭제)

#### 2.1 수치 가드레일 금리 오판 수정

**파일**: `market_research/report/numeric_guard.py`

**문제**: `abs(bm_val) > 50`으로 레벨/수익률 구분 → 금리(3.78%)가 수익률로 오분류.

**변경**:
- `_RATE_LEVEL_KEYWORDS` 22개 키워드 추가 (금리, UST, 2Y, 10Y, MOVE, DXY 등)
- 2단계 판정: 키워드 1순위 → abs>50 fallback
- 확장 컨텍스트 패턴: `"UST 2Y 3.78%"` → ctx=`"UST 2Y"` (기존: `"UST"`만)
- `seen_positions`로 패턴 간 중복 매칭 방지

**Before → After**:
```
[Before] "UST 2Y 3.78%" → 수익률로 판정 → BM과 비교 시도 → 오탐 가능
[After]  "UST 2Y 3.78%" → 키워드 매칭 → 레벨로 판정 → 비교 스킵 → 0건

[Before] "S&P500 -3.0%, UST 2Y 3.78%" → 둘 다 수익률로 비교
[After]  동일 입력 → S&P500만 불일치 1건 감지, UST는 스킵
```

**테스트**: 3건 전수 PASS.

---

#### 2.2 경고 severity 3단계 분류

**파일**: `tabs/admin.py`

**문제**: admin에 경고 5~10건이 전부 동일 수준 → 피로도.

**변경**:
- `_warn()` severity 매핑: critical(시제/ref/사실오류) / warning(펀드액션/권고형) / info(자동제거/raw number)
- admin UI 요약 블록: `⛔ CRITICAL 2건 | ⚠️ WARNING 1건 | ℹ️ INFO 3건`
- CRITICAL → `st.error()` 필수 확인, INFO → 접힌 expander

**Before → After**:
```
[Before] ⚠️ 시제 불일치 / ⚠️ ref 오매핑 / ⚠️ 펀드 액션 / ⚠️ 내부 지표 제거 (모두 동일)
[After]  ⛔ 검수 필요: CRITICAL 2건
           시제 불일치: "동결한" ← evidence "동결 유력"
           ref 오매핑: {한국은행} ← ref:5 {IMF}
         ⚠️ WARNING 1건: 펀드 액션 "비중을 확대"
         ▶ INFO 2건 (자동 처리됨)  [접힘]
```

---

#### 2.3 Opus 프롬프트 few-shot 예시

**파일**: `market_research/report/debate_engine.py`

**문제**: 금지 규칙만으로는 Opus가 내부 지표를 반복 생성. 후처리 제거에만 의존.

**변경**: `_synthesize_debate()` comment_prompt에 `## 좋은 코멘트 예시` 1문단 삽입.
- 재작성본에서 발췌 (내부 지표 없음, 수치에 단위 포함, ref 정확)
- "이 구조를 따르되 현재 월 데이터로 작성" 지시
- → generation 억제 + 후처리 제거 = 이중 방어

---

#### 2.4 Evidence Quality 누적 추적 체계

**파일**: `tabs/admin.py`

**문제**: evidence [ref:N] 안정성이 1회 검증에 그침. ref 오매핑률 추적이 P1에 밀려 있었음 → **P0으로 상향**.

**변경**:
- debate 저장 시 자동 계산: `total_refs`, `ref_mismatches`, `tense_mismatches`, `mismatch_rate`
- `_evidence_quality.jsonl`에 JSONL 누적 append (debate 1회 = 1행)
- admin 하단 expander에 누적 현황 테이블 + 평균 오매핑률 표시

**운영 규칙**:
- 3개월 평균 mismatch_rate > 20% → NLI 도입 검토
- tense_mismatches 증가 추세 → 프롬프트 재검토

---

#### 2.5 pilot_checklist.md 보강

**파일**: `market_research/docs/pilot_checklist.md`

기존 10항목 → **13항목**. 신규 3개:

| # | 항목 | 유형 |
|---|------|------|
| 11 | Evidence Quality 누적 추적 | 운영 필수 |
| 12 | Gold Set 확대 (월 20건 → 100건) | 운영 필수 |
| 13 | 모델 회귀 테스트 (월 1회, 고정 5건) | 운영 필수 |

---

#### 2.6 문서 정리

| 파일 | 변경 |
|------|------|
| `review_packet_v5.md` | Section 4.3 "미구현" → "구현 완료" 모순 수정 |
| `review_packet_v6.md` | 신규 작성 (본 문서) |
| memory: `project_insight_engine.md` | v6 반영, 2025 분류 제거 |
| memory: `handoff_insight_engine.md` | P0 갱신, 완료 항목 정리 |

---

### 3. 성숙도 변화

| 영역 | v5 | v6 | 변경 |
|------|-----|-----|------|
| 수치 가드레일 | 5 | **7** | 금리 오판 수정 |
| Evidence trace | 5 | **6** | 누적 추적 체계 |
| 후처리 체계 | 7 | **8** | severity 3단계 |
| **전체** | **5.5** | **6.0** | |

---

## Part II. 앞으로 해야 할 것

### P0 — 파일럿 진입 전 필수 (다음 세션)

| # | 작업 | 설명 | 완료 기준 |
|---|------|------|----------|
| 1 | **debate 재실행 2회+** | evidence quality 누적 데이터 확보 | `_evidence_quality.jsonl`에 2행+ |
| 2 | **pilot_checklist 13항목 전수 확인** | 재실행 결과 반영하여 체크리스트 점검 | 13항목 전부 PASS |

**예상 소요**: debate 1회 ~$0.34, 2회 실행 + 점검 = 1세션.

---

### P1 — 파일럿 운영 중 반복 (월별)

| # | 작업 | 주기 | 중단 기준 |
|---|------|------|----------|
| 1 | **gold set 확대** | 월 1회, 20건 샘플링+수동 라벨링 | precision < 85% 또는 topic < 75% |
| 2 | **모델 회귀 테스트** | 월 1회 또는 모델 변경 시 | ref 0건, 내부지표 노출, 펀드 액션 포함 |
| 3 | **evidence quality 리뷰** | 월 1회 | mismatch_rate 3개월 평균 > 20% |
| 4 | **수집 소스 다변화** | 가능 시 | — |
| 5 | **LLM 비용 모니터링** | 월 1회 | 월 $200 초과 시 분류 필터 조정 |

---

### P2 — 조건부 (P1 지표에 따라)

| # | 작업 | 발동 조건 |
|---|------|----------|
| 1 | NLI 후처리 도입 | mismatch_rate 3개월 평균 > 20% |
| 2 | 시제 validator lexicon 확장 | tense_mismatches 증가 추세 |
| 3 | gold set 200건 확대 | 100건 도달 후 정밀도 추가 개선 필요 시 |

---

## Part III. 파일럿 진입 조건 현황

| # | 조건 | 상태 | 비고 |
|---|------|------|------|
| 1 | 가드레일 금리 오판 해소 | **완료** | 테스트 3건 PASS |
| 2 | 경고 severity 분류 | **완료** | 3단계 + UI 요약 |
| 3 | 프롬프트 few-shot | **완료** | 이중 방어 |
| 4 | evidence 누적 추적 체계 | **완료** | JSONL 자동 기록 |
| 5 | evidence 2회+ 검증 데이터 | **미완** | debate 재실행 필요 |
| 6 | gold eval 기준선 통과 | **PASS** | 90.3/84.0/96.6 |
| 7 | gold set 확대 규칙 편입 | **완료** | checklist #12 |
| 8 | 모델 회귀 테스트 규칙 편입 | **완료** | checklist #13 |
| 9 | pilot_checklist 13항목 전수 | **부분** | #11 데이터 부족 |

**블로커**: #5 evidence 2회+ 검증. debate 재실행 1세션으로 해소 가능.

---

## Part IV. 리뷰 요청 응답 요약

| Q | 질문 핵심 | 응답 |
|---|----------|------|
| v4 Q1 | 파일럿 수준인가 | Yes, 조건부. gold 50건 → 100건 확대 필수 |
| v4 Q2 | abs>50 충분한가 | 아니오 → v6에서 키워드 기반으로 해결 |
| v4 Q3 | citation 대안 | rule-based + 누적 추적. NLI는 20% 초과 시 |
| v4 Q4 | 내부 지표 인용 | few-shot 이중 방어로 해결 |
| v5 Q7.1 | hallucination 방어 한계 | severity=critical 강제 + 자동 치환 비권고 |
| v5 Q7.2 | client ref 제거 | 정확. 기관 고객은 inline citation 미기대 |

---

## Part V. 잔여 리스크

| 리스크 | 심각도 | 현재 대응 | 추가 필요 |
|--------|--------|----------|----------|
| evidence ref 오매핑 | 높음 | client 제거 + admin 경고 + 누적 추적 | 누적 데이터로 NLI 판단 |
| 시제 변조 hallucination | 높음 | lexicon 18x15 + severity critical | coverage 70-80%, 확장 여지 |
| gold set 표본 부족 | 중간 | 50건 (95%CI: 79-97%) | 100건 목표 (83-95%) |
| 모델 업데이트 회귀 | 중간 | claude-opus-4-6 명시 | 월 1회 회귀 테스트 |
| LLM 비용 급증 | 낮음 | 분류 필터 50건 제한 | 비용 로깅 |
| Finnhub 한도 | 낮음 | 네이버 fallback | 대체 소스 P1 |

---

---

## Part VI. 아키텍처 정리 (2026-04-13 추가)

### 3-Tier Runtime Boundary

```
[외부 배치 — market_research]     [Streamlit Admin]          [Client]
 뉴스 수집/분류/정제/GraphRAG      debate 실행 트리거          approved final만 조회
 timeseries narrative              결과 검토/수정              draft/warning 미노출
 debate input package 생성         evidence/warning 표시
                                   draft 저장 → 최종 승인
```

### 저장 구조 (report_output)

```
market_research/data/report_output/
├── {period}/
│   ├── {fund}.input.json   ← 외부 배치 생성
│   ├── {fund}.draft.json   ← admin debate 결과
│   └── {fund}.final.json   ← admin 승인 (client 조회 대상)
└── _evidence_quality.jsonl  ← 누적 evidence 추적
```

### 핵심 신규 파일

| 파일 | 역할 |
|------|------|
| `report/report_store.py` | draft/final 저장·로딩·상태 관리 |
| `docs/io_contract.md` | input/draft/final 스키마 정의 |
| `tabs/admin.py` | debate workflow (생성→검토→수정→승인) |
| `tabs/report.py` | client(final)/admin(draft+evidence) 뷰어 |

### 상태 전이

`not_generated` → `draft_generated` → `edited` → `approved`

---

*2026-04-13 | 외부 리뷰 + 구현 + 운영 체계 구축 + 아키텍처 정리 완료*
