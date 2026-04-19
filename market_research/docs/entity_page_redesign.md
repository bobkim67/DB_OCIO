# Entity page redesign — 설계 (구현은 다음 배치)

작성일: 2026-04-17
범위: `02_Entities/`의 entity 단위 재설계. 현재는 매체 중심 → GraphRAG node 중심으로 전환.
**이번 배치에서는 구현하지 않고 방향만 확정.**

---

## 1. 현재 상태

`draft_pages.write_entity_page()`가 소스 매체(`Reuters`, `Bloomberg`, `매일경제`)를 entity로 간주하고 페이지 생성.

문제:
- 매체 자체는 분석 대상이 아님 — 정보원(source) tier는 이미 salience 계산에 반영됨
- entity로 의미 있는 것: 정책 주체(Fed/BOJ/한국은행), 인물(파월/이창용), 국가/지역(이란/호르무즈), 개념(유가 급등/달러 기근) 등
- GraphRAG에는 이미 풍부한 entity 노드가 있음 (`insight_graph/{month}.json`의 `nodes`)

## 2. 타겟 상태

`02_Entities/`는 **GraphRAG 노드 중에서 분석 가치 있는 entity**를 페이지화:
- 해당 월 기사에서 언급 빈도 높은 노드
- 해당 월 신규/주목도 급상승 노드
- TOPIC_TAXONOMY와 연결되는 노드

### 스키마 (예정)

```yaml
---
type: entity
status: base
entity_id: fed
label: "Federal Reserve"
taxonomy_topic: 통화정책                # 연결 taxonomy
node_severity: 0.82                       # GraphRAG 노드 severity
mention_count: 47                         # 해당 월 언급 건수
first_seen: 2026-04-01
last_seen: 2026-04-17
primary_articles: [article_id_1, ...]    # 대표 기사 ref
period: 2026-04
source_of_truth: pipeline_refine+graphrag
---
```

### 렌더링 섹션

- 정체성(label + aliases + 타입: 정책기관 / 인물 / 지역 / 개념)
- taxonomy 연결
- GraphRAG 인접 노드 top-5 (이 entity가 자주 연결되는 상대)
- 대표 기사 5건 (salience 상위)
- 월간 mention trend (주차별 그래프는 다음 배치)

## 3. 데이터 소스

| 필드 | 소스 |
|------|------|
| entity_id / label | `insight_graph/{month}.json::nodes.{id}.label` |
| taxonomy_topic | node topic + alias map (wiki/taxonomy.py::PHRASE_ALIAS 재활용) |
| mention_count | 해당 월 news JSON에서 label/alias 부분매칭 |
| primary_articles | salience 상위 + 토픽 매칭 기사 |
| adjacent nodes | `insight_graph/{month}.json::edges` 에서 from/to |

## 4. 매체 정보 이관 위치

현재 entity page가 담당하던 "매체 통계"는:
- base 페이지에는 남기지 않음
- salience 계산(source_quality)에만 반영 (이미 구현됨)
- 필요 시 `00_Index/media_coverage.md` 같은 집계 페이지로 분리 (선택)

## 5. 구현 단계 (다음 배치)

1. `wiki/entity_builder.py` 신규 — GraphRAG 노드 로딩 + alias 매칭 + 대표 기사 선정
2. `draft_pages.write_entity_page()`의 `entity_id` 파라미터 스키마 변경
3. `refresh_base_pages_after_refine()` 내부 호출부 변경 — 매체 루프 → graph node 루프
4. 기존 매체 기반 entity 페이지는 backup 후 제거
5. 테스트: 3~5개 샘플 entity에 대해 페이지 품질 수동 확인

## 6. 리스크 / 열린 질문

- **alias 유지보수 부담**: `fed / 연준 / 미연준 / Federal Reserve / FOMC` 를 하나의 entity로 묶는 맵. 초기 수작업 필요.
- **GraphRAG 노드 품질 의존**: 현재 P0 미적용 상태에서 일부 노드 라벨이 서술형 (`"유가_급등_압력"`). 정규화가 선행되면 entity page 품질도 개선.
- **entity 수 폭증 우려**: 노드 101~274개 중 어떻게 추릴지. 룰 후보:
  - salience 기반 상위 N
  - 월간 mention ≥ 5
  - taxonomy topic이 있는 노드만

## 7. 이번 배치에서의 판단

**구현하지 않는다.** 이유:
- GraphRAG P0는 방금 적용됐지만 P1(dynamic trigger/target + alias) 없이는 노드 정규화가 불완전
- P1 + alias_dict가 완성된 뒤 entity page를 쌓는 것이 재작업 비용이 적음
- 이번 배치의 주 목표인 taxonomy contract fix와 별개 과제

**다음 배치 착수 조건**: GraphRAG P1 완료 + node alias dict 구축.
