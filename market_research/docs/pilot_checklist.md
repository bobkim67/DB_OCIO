# 내부 파일럿 체크리스트

> 운영자가 파일럿 실행 전 확인하는 항목. 모두 PASS여야 파일럿 가능.
> 파일럿 운영 중 반복 검증 항목은 [운영] 태그로 표시.
>
> **최종 점검: 2026-04-13 — 13/13 PASS**

## 1. 뉴스 수집

- [x] 당월 뉴스 JSON 파일 존재 (`data/news/2026-04.json`, 21,809건)
- [x] 네이버 뉴스 수집 건수 > 0 (19,664건)
- [x] Finnhub 뉴스 수집 건수 > 0 (20,086건)

## 2. Financial Filter + LLM 분류

- [x] `_filter_reason` 있는 기사의 `_classified_topics` = `[]` (0건)
- [x] `_classified_topics`에 V1 토픽명 0건
- [x] `primary_topic`에 V1 토픽명 0건
- [x] `topic_taxonomy_version` = `'14_v2'`

## 3. Dedupe / Primary / Salience

- [x] primary 비율 > 95% (99.2%)
- [x] 최대 dedup 그룹 < 20건 (5건)
- [x] singleton event에 primary 없는 그룹 = 0개

## 4. vectorDB

- [x] 당월 컬렉션 존재 (`news_2026-04`)
- [x] 한국어 검색 테스트 통과 (score 0.90+)

## 5. GraphRAG

- [x] 당월 insight_graph JSON 존재 (131노드, 140엣지, 9경로)
- [x] 전이경로 > 0개 (9개)
- [x] 노드에 V1 토픽 분류명 없음 (노드명 "달러"는 엔티티명이지 분류 체계 아님)

## 6. Debate 입력 품질

- [x] primary_classified 기사 중 diversity guardrail 동작 (5개 토픽)
- [x] evidence_ids 15건 추적됨

## 7. 수치 가드레일

- [x] `numeric_guard.py` import 정상
- [x] debate 실행 시 가드레일 동작 확인

## 8. Evidence Trace

- [x] `evidence_trace.py` import 정상
- [x] Opus 코멘트에 `[ref:N]` 태그 포함 (Debate 1: 4건, Debate 2: 10건)

## 9. Gold Eval

- [x] `python -m market_research.tests.gold_eval --evaluate` 실행
- [x] precision 90.3% > 85%
- [x] topic 84.0% > 80%
- [x] recall 96.6% > 90%
- [x] primary 98.0% > 95%

## 10. 최종 확인

- [x] `daily_update` 실행 성공 (마지막 수집일: 2026-04-13)
- [x] debate 테스트: 2회 실행 완료 (07G04 Q1 + 08P22 4월)
- [x] 생성된 코멘트에 수치 오류 없음
- [x] 생성된 코멘트에 [ref:N] 태그 포함

## 11. Evidence Quality 누적 추적 [운영]

- [x] `_evidence_quality.jsonl`에 최소 2회 이상 기록 존재 (2건)
- [x] 평균 `mismatch_rate` < 20% (5.0%)
- [x] `tense_mismatches` 누적 추이 확인 — 증가 추세 없음 (합계 0건)

## 12. Gold Set 확대 [운영]

- [x] 파일럿 시작 시 gold set 50건 기준선 확인
- [ ] 매월 당월 분류 기사에서 무작위 20건 추출 → gold_set.json에 추가 (파일럿 운영 시작 후)
- [ ] 누적 100건 도달 시 gold_eval 재실행 (파일럿 운영 시작 후)

## 13. 모델 회귀 테스트 [운영]

- [x] 회귀 테스트 기준 확인: 2건 모두 ref 3+, 내부지표 없음, 펀드액션 없음
- [ ] 월 1회 고정 샘플 5건 재실행 (파일럿 운영 시작 후)
