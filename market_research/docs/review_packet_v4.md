# Review Packet v4 — 뉴스 파이프라인 현황 리뷰 요청

> 작성일: 2026-04-09 (최종, debate 실전 테스트 반영)
> 목적: 현재 파이프라인 상태에 대한 외부 리뷰 요청
> 이전 리뷰 이력: v1(초기 설계) → v2(upstream 정제) → v3(taxonomy V2 + dedup)

---

## 1. 시스템 개요

DB형 퇴직연금 OCIO 운용보고서 자동생성 파이프라인.

```
뉴스 수집 (네이버/Finnhub/NewsAPI)
  → Financial Filter (rule-based, 비금융 앞단 차단)
  → LLM 분류 (Haiku, 14개 토픽)
  → 정제 (dedupe + event clustering + salience + fallback)
  → GraphRAG (stratified sample + Self-Regulating TKG)
  → vectorDB (multilingual 임베딩 + hybrid_score)
  → 4인 LLM debate (Bull/Bear/Quant/monygeek → Opus 종합)
  → 수치 가드레일 (코멘트 수치 ↔ 원본 대조)
  → [ref:N] evidence trace
  → 운용보고 코멘트
```

---

## 2. 현재 성능

**gold 50건, V2 taxonomy 기준:**

| 지표 | 시작점 | 최종 |
|------|--------|------|
| precision | 72.5% | **90.3%** |
| topic accuracy | 64.0% | **84.0%** |
| recall | 100% | **96.6%** |
| primary pick | 58.0% | **98.0%** |

### 개선 경로

| 단계 | precision | topic | recall | primary | 핵심 변경 |
|------|-----------|-------|--------|---------|----------|
| 시작점 | 72.5 | 64.0 | 100 | 58.0 | V1 21개 토픽, dedup 오매칭 |
| Phase 1 | 92.3 | 76.0 | 82.8 | 98.0 | filter + URL 수정 + V2 통일 |
| Phase 2 | 88.9 | 70.0 | 82.8 | 98.0 | targeted relabel (gold V1 불일치) |
| **최종** | **90.3** | **84.0** | **96.6** | **98.0** | gold V2 재검토 + 미분류 복구 |

---

## 3. 변경사항

### 3.1 Taxonomy V2 (21→14)

신설 `경기_소비`, 좁게 `유동성_크레딧`, 통합 `환율_FX`/`금리_채권`/`귀금속_금`.
6개 파일 5개 dict V2 전면 교체. V1 잔류 0건.

### 3.2 Financial Filter + Dedup 근본 수정

- 2-Layer filter: 개별종목/상품 우선 차단 + source-aware (Tier1 매체 통과)
- URL 정규화: tracking param만 제거 → primary 52.5%→99.2%
- fallback resurrect 방지: `_filter_reason` 체크 (전수 0건)

### 3.3 미분류 복구

filter 통과 미분류 4,082건 → 1,831건 LLM 재분류 (~$1.36). recall 82.8→96.6%.

### 3.4 수치 가드레일 (debate 연동 완료)

`numeric_guard.py` → debate_engine `_synthesize_debate()`에 삽입.

**검사 대상**: 코멘트 내 수익률(%), bp, FX 레벨(달러/원)
**비교 방식**: 수익률은 BM/PA 수익률과 비교 (레벨 값은 자동 스킵), FX는 레벨끼리 비교
**허용 오차**: 수익률 ±0.5%p, FX ±10%
**불일치 시**: `[가드레일]` 경고 로그 출력 + `_guard_issues`로 반환 (reject 아닌 경고 모드)

**실전 테스트 결과 (2026-03)**:
- 1차 테스트에서 가드레일이 수익률(%)을 레벨(98.999, 1471.2)과 비교하는 오탐 2건 발생
- 수정: `abs(bm_val) > 50` 이면 레벨로 판정하여 수익률 비교 스킵
- 코멘트 내 수치(S&P -4.5%, KOSPI -5.1%, 금 -12.2%, UST 2Y 3.7855%) 모두 정확 → 수정 후 오탐 해소 예상

### 3.5 Sentence-level Evidence

Opus 프롬프트에 `[ref:N]` 태그 지시 삽입 + `evidence_trace.py` 파싱 유틸 구현.

**실전 테스트 결과**: 1차 debate에서 Opus가 `[ref:N]` 태그를 **0건** 생성.
**원인**: 프롬프트 지시가 불충분. "최소 3개 이상 포함" + "태그 없는 사실 주장은 허용되지 않습니다" 규칙으로 강화 완료.
**현재 상태**: 프롬프트 강화 적용됨. 다음 debate 실행 시 검증 필요.

### 3.6 GraphRAG + vectorDB 리빌드

4개월 전체 리빌드 완료:

| 월 | vectorDB | GraphRAG 노드 | 엣지 | 전이경로 |
|----|---------|-------------|------|---------|
| 01 | 5,050건 | 206 | 173 | 3 |
| 02 | 8,457건 | 267 | 249 | 3 |
| 03 | 27,479건 | 286 | 269 | 4 |
| 04 | 20,931건 | 274 | 252 | 7 |

vectorDB 검색 품질 확인:

| 쿼리 | Top-1 결과 | hybrid_score |
|------|-----------|-------------|
| "한국 국채 금리 상승" | 중동 사태 장기화, 대출 부담 | 0.967 |
| "원달러 환율 급등" | 달러·원 환율 1490.0원 출발 | 0.883 |
| "코스피 하락 외국인" | 코스피·코스닥 나란히 하락 | 0.946 |
| "oil price Iran" | Oil price surges as Iran attacks | 0.968 |

한국어+영문 모두 의미 매칭 정상.

### 3.7 실전 Debate 테스트 결과 (2026-03)

```
에이전트: bull=bullish, bear=bearish, quant=bearish, monygeek=neutral
evidence_ids: 15건 추적
가드레일: 2건 오탐 (수익률 vs 레벨 혼동 → 수정 완료)

코멘트 품질:
- GraphRAG 전이경로 신뢰도 직접 인용 (유가→인플레 0.65, 인플레→Fed 0.722)
- 구체적 수치: S&P -4.5%, KOSPI -5.1%, 금 -12.2%, UST 2Y 3.7855%
- 크로스 자산 인과관계 서술
```

### 3.8 오분류 처리 방침

잔여 8건: 프롬프트 튜닝 3건 + 규칙 기반 2건 + boundary 3건.
시장영향 우선 규칙 4줄 프롬프트에 추가 완료:
- oil/유가 명시 → 에너지_원자재
- 금값 명시 → 귀금속_금
- 통화+환율 명시 → 환율_FX
- 중앙은행 주체 → 통화정책

---

## 4. 잔여 오분류 (8건)

| 분류 | 건수 | id | 관리 |
|------|------|-----|------|
| topic mismatch | 3 | 4, 14, 41 | 프롬프트 규칙 추가로 향후 개선 |
| filter miss | 2 | 16, 50 | daily_update 재실행 시 자동 복구 / 프롬프트 규칙 |
| boundary | 3 | 13, 30, 45 | 비금융 경계, 허용 |

---

## 5. 남은 문제

### 5.1 evidence trace 실전 검증

프롬프트 강화 후 Opus가 `[ref:N]`을 실제로 붙이는지 재검증 필요. 다음 debate 실행 시 확인.

### 5.2 가드레일 수익률/레벨 구분

수정 완료(abs>50 → 레벨 스킵). 실전 재검증 필요.

### 5.3 2025년 데이터 미분류

2025-01~12 약 19,000건 분류/정제 미적용.

---

## 6. 내부 파일럿 준비도

`pilot_checklist.md` 10항목 작성 완료. 핵심:

| 항목 | 상태 |
|------|------|
| 뉴스 수집 | OK |
| filter / dedupe / primary / salience | OK (전수 검증) |
| vectorDB 리빌드 | **완료** (4개월) |
| GraphRAG 리빌드 | **완료** (4개월) |
| debate 입력 품질 | OK (diversity, evidence_ids) |
| 수치 가드레일 | **연동 완료** (수익률/레벨 구분 수정) |
| evidence trace | 프롬프트 강화 완료, **실전 재검증 필요** |
| gold eval | precision 90.3%, topic 84%, recall 96.6%, primary 98% |

---

## 7. 리뷰 요청 포인트

1. **현재 성능**: precision 90.3%, topic 84%, recall 96.6%, primary 98% — 내부 파일럿 수준인가?

2. **수치 가드레일**: 수익률(%) vs 레벨(원/달러)을 `abs > 50`으로 구분하는 방식이 충분한가? 더 정교한 구분이 필요한가?

3. **evidence trace**: Opus가 첫 시도에서 `[ref:N]`을 0건 생성. 프롬프트를 강화했지만, LLM이 citation을 일관되게 따를 가능성은? 대안(후처리 NLI 매칭 등)이 필요한가?

4. **코멘트 품질**: GraphRAG 전이경로 신뢰도(0.65, 0.722)를 코멘트에 직접 인용한 것이 운용보고서에 적절한가? 수치 정밀도가 과도해 보일 위험은?

5. **다음 우선순위**: 아래 순서가 맞는가?
   1. evidence trace 실전 재검증 (다음 debate 테스트)
   2. 2025년 데이터 분류
   3. 수집 소스 다변화

6. **전체 성숙도**: 이전 판정 "고급 프로토타입 4.8". 가드레일/evidence/리빌드 완료 후 변동이 있는가?
