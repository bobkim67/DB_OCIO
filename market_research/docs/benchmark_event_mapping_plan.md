# Benchmark-Event Mapping Layer — 설계/구현 plan

**status**: v0.1 구현 완료 (2026-04-22)
**스코프**: 자산군별 BM 시계열의 변곡점/이상 구간 ↔ 리포트/뉴스 이벤트를 날짜축으로 매핑하고, graphify 같은 시각화에 넘길 수 있는 정규화된 mapping package 생성.

이번 배치는 debate/report/UI **본체 재설계가 아니다**. 그 위 레이어들이 공통으로 소비할 **중간 계약 (visualization contract)** 만 만든다.

---

## 1. 동기 / 문제 정의

기존 파이프라인:
```
[수집] → [분류] → [정제(salience+dedup)] → [GraphRAG/vectorDB] → [debate evidence quota]
                                                                      ↓
                                                              [report/comment]
```

evidence quota 단계까지는 source-aware (nr=primary, news=corroboration) 가 잘 동작.
그러나 다음 두 단계 사이의 **간극**이 비어 있음:

1. **BM 시계열 변동** ("3월 둘째 주 Gold +4.4%, KOSPI −14%") 가 어느 evidence/topic/graph node 와 직접 연결되는지가 정규화되어 있지 않음 → debate 프롬프트에 BM/news가 따로 들어가서 LLM이 매번 매칭을 다시 해야 함.
2. **시각화/graphify** 로 보내려면 (date × asset_class × evidence × graph_node) 한 통일 객체 필요.

해결: **Benchmark Event Window (BEW)** 라는 중심 객체를 도입.
- 한 BEW = "특정 BM이 특정 기간에 특정 signal(drawdown/rebound/anomaly/trend_break)을 보였다"
- 그 BEW에 **그 기간의 evidence + topic + graph subgraph seed** 를 묶어 단일 단위로 저장.

---

## 2. 핵심 데이터 객체

### 2.1 BenchmarkEventWindow (BEW)
```jsonc
{
  "window_id": "f7c2956bac",        // hash(bm|date_from|signal)
  "asset_class": "국내주식",
  "benchmark": "KOSPI",
  "date_from": "2026-03-04",
  "date_to": "2026-03-06",
  "pivot_date": "2026-03-04",        // |z| 최대 일자
  "signal_type": "drawdown",         // anomaly | trend_break | drawdown | rebound
  "benchmark_move_pct": -14.48,      // pivot 일자의 5일 누적 수익률(%)
  "zscore": -3.33,                   // pivot 일자의 z-score (5d ret / 20d vol)
  "event_count": 3,                  // window를 구성한 일별 signal 수
  "mapped_evidence_ids": [...],
  "mapped_topics": [...],
  "mapped_event_groups": [...],
  "evidence_count": 8,
  "evidence_source_mix": {"naver_research": 5, "news": 3},
  "confidence": 1.125,               // 0~1.2 (이론), 실측 0.4~1.2 분포
  "graph_seed_size": {"nodes": 5, "edges": 3}
}
```

### 2.2 EvidenceCard (window별 평탄화)
```jsonc
{
  "window_id": "f7c2956bac",
  "evidence_id": "ab12...",          // _article_id
  "source_type": "naver_research",   // 또는 "news"
  "date": "2026-03-04",
  "asset_class": "국내주식",
  "primary_topic": "지정학",
  "title": "...",
  "source": "키움증권",              // 매체명
  "broker": "키움증권",              // nr 전용
  "salience": 0.91,
  "asset_relevance": 0.62,
  "bm_overlap": false,
  "event_group_id": "...",
  "category": "market_info",         // nr 전용
  "match_level": 1                   // 1=topic-match, 2=relevance, 3=fallback
}
```

### 2.3 GraphSeed (window 설명용 subgraph)
```jsonc
{
  "nodes": [
    {"node_id": "...", "label": "...", "topic": "...", "severity": "warning",
     "source_types": ["naver_research"], "window_ids": ["f7c2956bac"]}
  ],
  "edges": [
    {"from": "A", "to": "B", "relation": "causes", "weight": 0.7,
     "rule_name": "...", "source_type": "naver_research"}
  ]
}
```

### 2.4 VisualizationContract (월 단위 산출물)
```jsonc
{
  "month": "2026-03",
  "generated_at": "2026-04-22T...",
  "windows": [BEW, ...],             // 시간순 정렬
  "timeline": [
    {"date": "...", "kind": "bm_pivot" | "evidence", ...}
  ],
  "graph": {                         // 모든 window seed 합집합
    "nodes": [...],
    "edges": [...]
  },
  "evidence_cards": [EvidenceCard, ...],
  "debug": {
    "window_count": 13,
    "unmapped_windows": 0,
    "evidence_total": 104,
    "source_mix": {"naver_research": 65, "news": 39},
    "graph_size": {"nodes": 37, "edges": 20},
    "parameters": {...}              // 탐지 임계치 전체 노출 (재현성)
  }
}
```

저장: `market_research/data/benchmark_events/{YYYY-MM}.json`

---

## 3. 구현 방침

### 3.1 Window 탐지 (`detect_benchmark_windows`)
- 입력: core 6개 BM (S&P500 / KOSPI / Gold / DXY / USDKRW / 미국종합채권)
- 시계열: SCIP `back_datapoint` 3개월 lookback (vol 안정성)
- 일별 metric: `ret_5d` (5일 누적 수익률), `vol_20d` (20일 일별 ret 표준편차), `z = ret_5d / vol_20d`
- signal 분류:
  - `drawdown`: ret_5d ≤ −3% AND z ≤ −1.0
  - `rebound`: ret_5d ≥ +3% AND z ≥ +1.0
  - `anomaly`: |z| > 1.5 (drawdown/rebound 미해당)
  - `trend_break`: |z| > 1.0 (위 셋 미해당)
- 인접일 묶기: 같은 BM + 같은 signal_type + ≤ 2일 간격 → 한 window
- 대표값: |z| 최대인 일자 = `pivot_date`

### 3.2 Evidence 매핑 (`load_window_evidence`)
- 입력 풀: `data/news/{YYYY-MM}.json` + `data/naver_research/adapted/{YYYY-MM}.json`, primary + classified만
- 날짜 필터: window 기간 ±2영업일 tolerance
- 매칭 우선순위 3-tier (level):
  1. **topic-match**: `_classified_topics` 또는 `primary_topic` 이 자산군 매칭 토픽 리스트에 포함
  2. **asset_relevance**: `_asset_relevance[asset_class] ≥ 0.4`
  3. **fallback**: 날짜만 일치
- 정렬: `_event_salience` 내림차순
- **Window 내 source quota**: nr 우선 5슬롯 / news 3슬롯 (총 8 캡, 부족 시 상호 흡수)
  - 이유: corroboration lane(news) 가 항상 0이 되는 것 방지. cross-source 다양성 확보.
- 토픽→자산군 매칭표 (`_TOPIC_TO_ASSET_CLASSES`): 14 토픽 × 6 자산군 매트릭스 (mapper 파일에 in-line)

### 3.3 Confidence (`_compute_confidence`)
```
confidence = z_strength × evidence_strength × nr_bonus
  z_strength       = min(|zscore| / 3, 1.0)
  evidence_strength= min(len(ev) / 4, 1.0)
  nr_bonus         = 1.0 + 0.2 × (nr_count / total)   # 1.0 ~ 1.2
```
값 범위: 0 ~ 1.2 (의도된 over-shoot — nr 우위 보상).

### 3.4 GraphSeed (`build_window_graph_seed`)
- 입력: `data/insight_graph/{YYYY-MM}.json` (Phase 3 source_types provenance 포함)
- 매칭 규칙: 노드 label / topic이 (asset_class + 자산군 별칭 + topic 분해 단어) 중 하나 포함
- 추출 규모 캡: 노드 ≤ 12, 엣지 ≤ 20 (window당)
- **GraphRAG 본체는 read-only**, 슬라이스만.

### 3.5 Visualization Contract (`build_visualization_contract`)
- timeline: 월의 모든 window pivot + evidence를 (date, kind) 정렬 → frontend가 한 축에 그릴 수 있게.
- graph: 모든 window의 graph_seed 합집합 (node dedupe, edge dedupe).
  - 각 node에 `window_ids` 리스트 부착 → 어느 window 가 끌어왔는지 역추적 가능.
- evidence_cards: window × evidence 평탄화 → UI 카드 리스트 / debate 입력 직접 사용 가능.

---

## 4. Acceptance (2026-04-22 v0.1)

| # | 항목 | 기준 | 결과 (2026-03) |
|---|------|------|---------------|
| 1 | window 탐지 | ≥ 3 | **13** ✅ |
| 2 | window별 evidence 1건 이상 | all | **13/13** ✅ |
| 3 | contract JSON 생성 | 파일 존재 | `data/benchmark_events/2026-03.json` ✅ |
| 4 | card 필수 필드 (source_type, evidence_id, date, asset_class) | 100% | **104/104** ✅ |

추가 회귀 (4개월 전수):

| month | windows | unmapped | evidence | nr | news | graph(n/e) |
|---|---:|---:|---:|---:|---:|---:|
| 2026-01 | 15 | 0 | 120 | 75 | 45 | 44/19 |
| 2026-02 | 12 | 0 | 96 | 60 | 36 | 40/20 |
| 2026-03 | 13 | 0 | 104 | 65 | 39 | 37/20 |
| 2026-04 | 5 | 0 | 40 | 25 | 15 | 25/12 |

source mix 유지: 평균 nr 62.5% / news 37.5% (window quota 5/3 = 62.5/37.5 정확 일치).

---

## 5. 이번 배치에서 *하지 않은* 것 (의도된 경계)

- Streamlit / graphify UI 본격 구현
- debate_engine / report_service 호출 경로 변경
- GraphRAG 본체 재계산
- vectorDB hybrid_score 변경
- news/source quota 재튜닝
- LLM 호출

전부 contract JSON 생성까지만. UI/debate가 향후 이 contract를 **읽기 전용**으로 소비.

---

## 6. 다음 배치 연결 가이드

### 6.1 debate 입력 강화 (가장 자연스러운 다음 step)
- `_build_evidence_candidates` 가 현재 월 단위로 nr/news quota만 적용.
- 변경: contract.evidence_cards 를 우선 후보로 사용 → BEW 단위로 (window별로 다양성 확보, 자산군 균형).
- 효과: debate 프롬프트에 "어느 BM이 어떻게 움직였고, 어느 evidence 가 그것을 설명한다" 가 1:1 attached 상태로 들어감.

### 6.2 timeseries_narrator 통합
- 현재 narrator 는 BM 시계열을 별도로 z-segment 분해 → news와 매칭.
- 변경: contract.windows + contract.timeline 만 읽도록 단순화. 자체 z 계산 제거.

### 6.3 Streamlit 시각화 (별도 배치)
- contract 그대로 frontend 에 던지면 react-flow / cytoscape / plotly timeline 으로 즉시 그릴 수 있음.
- 권장 layout:
  - 위: timeline (date × asset_class) 가로 스트립, BM pivot은 큰 점, evidence는 작은 점
  - 아래: 선택한 window의 graph_seed 를 force-directed 로
  - 옆: evidence_cards 리스트
- 이번 배치에서는 UI 미구현, contract spec만 고정.

### 6.4 운용보고 자동 inline
- comment_engine 이 펀드별 PA 결과 + contract.windows 의 confidence 가장 높은 N개 → "왜" 코멘트 후보로 변환.

---

## 7. 핵심 파일

| 파일 | 역할 |
|---|---|
| `market_research/report/benchmark_event_mapper.py` | 신규 — 5개 핵심 함수 + CLI |
| `market_research/data/benchmark_events/{YYYY-MM}.json` | 신규 — 월별 visualization contract |
| `market_research/tests/test_benchmark_event_mapper.py` | 신규 — acceptance 4개 + smoke |

기존 파일 수정: **0건** (read-only 소비자).

---

## 8. 리스크 / 주의

- **2026-04 windows=5** 만 탐지 — 월말 데이터 부족 (현재 04-22). 월별 window 개수는 시장 변동성에 따라 0~20+ 변동 가능, 1~2개월은 정상 시그널.
- **confidence > 1.0 가능**: nr_bonus가 곱연산이라 의도된 over-shoot. 향후 `min(.., 1.0)` 캡 도입 여지.
- **GraphSeed 키워드 매칭이 느슨함**: 노드 라벨 부분일치 → false-positive 가능. 향후 `source_types` intersect 까지 강제하는 strict 모드 옵션 검토.
- **Window date_to ≠ evidence date 상한**: tolerance ±2일까지 잡으므로 다음 window와 겹칠 수 있음. 같은 evidence 가 두 window에 매핑될 수 있음 — 의도된 동작 (한 evidence가 여러 자산군 BEW 모두 설명 가능).

---

## 9. CLI / 사용

```bash
# 단일 월
python -m market_research.report.benchmark_event_mapper 2026-03

# 다중 월
python -m market_research.report.benchmark_event_mapper 2026-01 2026-02 2026-03 2026-04

# 저장 안 함 (탐지만)
python -m market_research.report.benchmark_event_mapper 2026-03 --no-save
```

```python
# 프로그래매틱
from market_research.report.benchmark_event_mapper import (
    detect_benchmark_windows, load_window_evidence,
    map_events_to_windows, build_window_graph_seed,
    build_visualization_contract, save_contract,
)
contract = build_visualization_contract(2026, 3)
```
