# GraphRAG 전이경로 & Regime Change 진단 및 개선안

작성일: 2026-04-17
대상 파일:
- `market_research/analyze/graph_rag.py` (전이경로)
- `market_research/pipeline/daily_update.py::_step_regime_check` (regime 감지)
- `market_research/report/debate_engine.py` (regime narrative 작성)

관찰 데이터:
- `market_research/data/insight_graph/2026-04.json`
- `market_research/data/regime_memory.json`

---

## 1. 현재 프로세스

### 1.1 전이경로 계산의 위치

`build_insight_graph()` (월별) 또는 `add_incremental_edges()` (일별) 파이프라인의 **마지막 단계**에서 호출.

```
수집 → 분류 → 정제 → 엔티티 추출(Haiku) → 인과추론(Sonnet)
→ TKG decay/merge/prune → [precompute_transmission_paths] → 저장
```

### 1.2 알고리즘 (`precompute_transmission_paths`, graph_rag.py:392)

```python
trigger_keywords = ['달러_부족','금리_상승','유가_급등','인플레','위안화',
                    '엔화','관세','지정학','레포']                     # 9개
asset_keywords   = ['국내주식','국내채권','해외주식','해외채권','원자재',
                    '통화','KOSPI','SP500','금리','환율','유가','금']  # 12개

# 9 × 12 = 108 pair 반복
for trigger in trigger_keywords:
    for asset in asset_keywords:
        results = query_transmission_path(graph, trigger, asset, max_depth=4)
        for r in results[:2]:           # pair당 최대 2경로
            if r['confidence'] > 0.1:   # confidence 하한
                paths.append({...})
```

### 1.3 `query_transmission_path` (graph_rag.py:325)

1. **부분 매칭 (substring)**: `from_id.lower() in node.lower()`로 시작/종료 후보 노드 집합 수집
2. **BFS 모든 경로 탐색 (`_bfs_all_paths`)**: `max_depth=4`, 사이클 방지, `confidence = ∏(edge.weight)`
3. **confidence 내림차순 정렬 후 상위 5개 반환**
4. `precompute`에서 상위 2개만 채택

---

## 2. 2026-04 출력 분석 (8개 경로)

### 2.1 관찰된 패턴

| 증상 | 사례 |
|------|------|
| 트리거 집중 | 9개 중 **3개만** 활성 (유가_급등, 인플레, 지정학) — 67% 미매칭 |
| 타겟 집중 | 12개 중 **3개만** 활성 (유가, 금리, 금) |
| 동일 pair 중복 | #1·#2 (유가→유가), #7·#8 (지정학→금) — 중간 노드만 다름 |
| self-loop | #1 "유가 급등 압력 → 국제유가" — trigger=target=유가 |
| **타겟 오매칭** | #7·#8: target "금" → 경로 종점이 **"외국인_자금_이탈"** — "자**금**"의 "금" substring 오매칭 |
| 동일 경로 복제 | #3·#4: `인플레이션_압력_상승 → 기준금리_조정_검토` 경로가 target "금리"·"금" 두 번 모두 등록 |

### 2.2 그래프 내부 매칭 커버리지

**트리거 매칭 현황** (2026-04 그래프, 노드 101개 기준):

| trigger | 매칭 노드 수 | 상태 |
|---------|-------------|------|
| 달러_부족 | 0 | ❌ |
| 금리_상승 | 0 | ❌ |
| 유가_급등 | 1 | ✅ |
| 인플레 | 2 | ✅ |
| 위안화 | 0 | ❌ |
| 엔화 | 0 | ❌ |
| 관세 | 0 | ❌ |
| 지정학 | 8 | ✅ |
| 레포 | 0 | ❌ |

**6/9 = 67% 트리거가 그래프에 존재하지 않음.**

**타겟 매칭 현황**:

| target | 매칭 수 | 오매칭 사례 |
|--------|--------|-------------|
| 국내주식/해외주식/국내채권/해외채권 | 0 | — |
| 원자재/KOSPI/SP500 | 0 | — |
| 통화 | 2 | "금융**통화**위원회" — 원래 FX 의도인데 monetary policy 노드가 매칭 |
| 금리 | 10 | ✅ 정확 |
| 환율 | 3 | ✅ 정확 |
| 유가 | 6 | ✅ 정확 |
| **금** | **18** | **상당수 오매칭**: "기준**금**리", "**금**리동결", "**금**통위", "외국인 자**금** 이탈" |

---

## 3. 근본 원인

### 3.1 Substring 매칭의 한계

`"금"`이 `"기준금리"`·`"금융통화위원회"`·`"자금이탈"` 등 전혀 다른 의미 노드에 매칭.
→ 타겟이 짧을수록 오매칭 기하급수적 증가.

### 3.2 하드코딩된 키워드 리스트의 경직성

- trigger 9개 중 6개(`달러_부족`·`금리_상승`·`위안화`·`엔화`·`관세`·`레포`)는 당월 뉴스 토픽과 무관 → 커버리지 0
- 반면 당월 핵심 토픽인 `"연준 정책"`·`"반도체"`·`"AI"`·`"중국 성장"` 등은 trigger 목록에 없음
- 지정학은 8개 노드 매칭되어 과대 표집 → 8개 중 4개가 지정학 발

### 3.3 Pair당 중복 허용

`results[:2]`로 **같은 (trigger, target) 쌍에서 2개 경로** 허용 → 중간 노드만 다른 quasi-dup 양산.

### 3.4 Self-loop 미필터

`trigger='유가_급등'`, `target='유가'`일 때 `유가_급등_압력 → 국제유가` 자체가 유효 경로가 됨. 정보가 없음.

### 3.5 Target 종점 검증 부재

BFS는 "substring 포함 노드에 도달하면 성공"으로 종료. **경로 끝 노드의 의미가 target과 일치하는지 확인 안 함**.

### 3.6 타겟 그루핑 누락

당월 뉴스에는 `"국제유가"`·`"원유_선물_가격_급등"`·`"유가"`·`"유가_상승_우려"` 등 **같은 개념 다른 노드**가 공존. 표준화/canonicalization 없이 BFS는 이들 사이로 경로를 구성 → 경로 길이·다양성 왜곡.

---

## 4. 개선안 (우선순위별)

### P0 — 정확성 결함 (즉시 수정)

#### 4.1 타겟 오매칭 필터
```python
# BAD
to_candidates = [n for n in nodes if to_id.lower() in n.lower()]

# GOOD: word-boundary 매칭 (단어 단위) + 오매칭 블랙리스트
def _matches_target(node_label: str, target: str) -> bool:
    label_tokens = re.split(r'[_\s]', node_label)
    for token in label_tokens:
        if token == target: return True                # 완전 일치
        if target in token and len(token) <= len(target) + 2:
            return True                                # 파생 허용 (유가→유가상승)
    return False
```

#### 4.2 Self-loop 스킵
```python
# precompute에서
if _matches_target(trigger, asset) or _matches_target(asset, trigger):
    continue  # trigger와 target이 같은 개념이면 스킵
```

#### 4.3 Pair당 1경로 (상위 confidence만)
```python
for r in results[:1]:   # 2 → 1
    ...
```

예상 효과: 2026-04 기준 8개 → 약 3~4개로 줄되 **중복 제거**.

---

### P1 — 커버리지 결함 (다음 배치)

#### 4.4 Trigger/Target 키워드를 뉴스 분류 토픽과 동기화

현재 하드코딩된 리스트 대신, `news_classifier.py`의 V2 14토픽을 기반으로 매월 동적 생성:

```python
# V2 토픽 (news_classifier)
V2_TOPICS = ['통화정책','금리_채권','물가_인플레이션','환율_FX','달러_글로벌유동성',
             '에너지_원자재','귀금속_금','관세_무역','지정학','테크_AI_반도체',
             '경기_소비','유동성_크레딧','부동산','기타']

# 각 토픽을 trigger/target 후보로 사용. 각 토픽별 상위 salience 노드 1~2개 선택.
def _select_triggers_targets(graph, topic_list, top_k=2):
    by_topic = defaultdict(list)
    for nid, node in graph['nodes'].items():
        t = node.get('topic', '기타')
        by_topic[t].append((nid, node.get('severity_weight', 0.5)))
    selected = {}
    for topic in topic_list:
        ranked = sorted(by_topic[topic], key=lambda x: -x[1])[:top_k]
        selected[topic] = [nid for nid, _ in ranked]
    return selected
```

→ **그래프에 실제 존재하는 노드만 대상** → 커버리지 0% 문제 소멸.

#### 4.5 Alias dict (동의어 표준화)

```python
ASSET_ALIAS = {
    '유가': ['유가','국제유가','원유','WTI','브렌트'],
    '금': ['금','금가격','귀금속','골드'],
    '환율': ['환율','원달러','USDKRW','DXY'],
    ...
}
# 매칭 시 alias 전체 시도, 결과는 canonical name으로 통일
```

#### 4.6 경로 의미 중복 제거

```python
def _path_signature(path: list[str]) -> tuple:
    """앞·뒤 노드 + 중간 길이로 시그니처. 동일 시그니처는 dedup."""
    if len(path) <= 2: return tuple(path)
    return (path[0], path[-1], len(path))  # 또는 (path[0], path[1], path[-1])
```

---

### P2 — 다양성 보강 (여유 있을 때)

#### 4.7 Trigger당 쿼터 (집중 방지)

현재 2026-04는 지정학 발 경로가 4/8 = 50%. quota로 균형:

```python
MAX_PER_TRIGGER = 2
MAX_PER_TARGET = 2
# 전체 합계 TARGET_TOTAL = 12 목표
```

#### 4.8 경로 길이 다양성 보너스

confidence만으로 선택하면 짧은 경로(depth=2)가 항상 승. 중간 과정을 보여주는 depth 3~4 경로에 보너스:

```python
length_bonus = {2: 1.0, 3: 1.05, 4: 1.1}  # 긴 경로 약간 우대
ranked = sorted(paths, key=lambda p: -p['confidence'] * length_bonus.get(len(p['path']), 1.0))
```

#### 4.9 Embedding fallback

Substring 매칭 실패 시 `analyze/news_vectordb.py`의 multilingual embedding으로 노드 라벨 nearest-neighbor 검색 → 의미 유사도 상위 3개를 후보로 추가.

---

## 5. 제안 작업 순서

| Phase | 작업 | 예상 효과 | 리스크 |
|-------|------|-----------|--------|
| P0.1 | Target word-boundary 매칭 | "금" → "자금이탈" 오매칭 제거 | 기존 올바른 매칭 일부 누락 가능 → 테스트 필요 |
| P0.2 | Self-loop + pair당 1경로 | 중복 약 50% 감소 | 없음 |
| P1.1 | Trigger/Target 동적 선택 | 커버리지 0% 트리거 제거, 실제 활성 토픽 반영 | V2 토픽 매핑 품질 의존 |
| P1.2 | Alias dict | 동일 개념 다른 노드 통합 | 유지보수 부담 |
| P2.1 | Trigger quota + 다양성 | 경로 토픽 분산 | 핵심 경로가 quota로 빠질 위험 |

**P0만 적용해도 2026-04 출력은 중복 없는 4~5개 경로로 정리될 전망.**
그 후 P1을 적용하면 `달러_글로벌유동성`·`관세_무역`·`테크_AI_반도체` 등 실제 당월 이슈가 경로에 등장.

---

## 6. 검증 방법

`_evidence_quality.jsonl`처럼 경로 품질 지표 누적:

```python
# data/report_output/_transmission_path_quality.jsonl
{
  "month": "2026-04",
  "built_at": "...",
  "total_paths": 8,
  "unique_triggers": 3,          # 9 중
  "unique_targets": 3,           # 12 중
  "self_loops": 1,
  "dup_signatures": 2,
  "target_mismatches": 2,        # word-boundary 검사 결과
  "avg_confidence": 0.52,
}
```

매월 기록하여 개선 전/후 비교.

---

# Part 2 — Regime Change 진단 및 개선안

## 7. 현재 프로세스

### 7.1 Regime 감지의 위치

`daily_update.py` 파이프라인의 **Step 5** (마지막 단계).

```
Step 0~3: 수집/분류/정제/GraphRAG
Step 4:   MTD 델타 (토픽 카운트 집계)
Step 5:   _step_regime_check(delta)   ← 여기
```

### 7.2 감지 알고리즘 (`_step_regime_check`, daily_update.py:368)

```python
# 1) 현재 narrative 키워드 추출
narrative = regime['current']['dominant_narrative']
narrative_keywords = set(narrative.replace('+',' ').replace(',',' ').split())

# 2) 오늘 상위 토픽과 교집합 비율 계산
top_topics = list(delta['topic_counts'].keys())
overlap = sum(1 for t in top_topics if any(kw in t for kw in narrative_keywords))
overlap_ratio = overlap / len(top_topics)

# 3) shift 후보 판정
if overlap_ratio < 0.3:
    shift_detected = True

# 4) 3일 연속 후보 → 확정
consecutive = regime.get('_shift_consecutive_days', 0) + (1 if shift_detected else 0)
if consecutive >= 3:
    regime['current'] = {'dominant_narrative': ' + '.join(top_topics[:3]), ...}
```

### 7.3 Narrative 작성의 이중 경로

- **daily_update**: top_topics 상위 3개를 `" + "`로 조인 → `"지정학 + 환율_FX + 에너지_원자재"` (태그형)
- **debate_engine**: Opus가 작성한 자연어 narrative로 덮어씀 → `"휴전 완화 vs 유가 구조적 충격의 줄다리기"` (서술형)

→ 같은 `regime_memory.json`을 **두 경로에서 서로 다른 스타일로 쓰기**.

---

## 8. 2026-04-17 관찰 (regime_memory.json)

### 8.1 현재 상태
```json
{
  "current": {
    "dominant_narrative": "지정학 완화 vs 구조적 인플레: 단기 랠리와 장기 리스크의 불일치",
    "weeks": 1,
    "since": "2026-04"
  },
  "previous": {
    "dominant_narrative": "휴전 완화 vs 유가 구조적 충격의 줄다리기",
    "ended": "2026-04"
  },
  "shift_detected": true,
  "_shift_consecutive_days": 0
}
```

### 8.2 History 12개 entry 분석

| # | narrative | period | 비고 |
|---|-----------|--------|------|
| 1 | 지정학 리스크 vs 인플레·성장 둔화의 불확실성 충돌 | 2026-04 ~ 2026-04 | 서술형 |
| 2 | 지정학 완화 vs 구조적 인플레 딜레마 | 2026-04 ~ 2026-04 | 서술형 |
| 3 | 지정학적 완화 vs 에너지 인플레 압력 교차 | 2026-04 ~ 2026-04 | 서술형 |
| 4 | 휴전 안도감 vs 유가 인플레 충격 | 2026-04 ~ 2026-04 | 서술형 |
| 5 | 휴전 안도감 vs 구조적 유가 급등의 불안정한 균형 | 2026-04 ~ 2026-04 | 서술형 |
| 6 | 지정학적 안도감 vs 에너지 인플레이션 압박의 긴장. | 2026-04 ~ 2026-04 | 서술형 (마침표) |
| 7 | 지정학 리스크 vs 인플레 압력의 불확실성 충돌 | 2026-04 ~ **2026-03** | **역순** |
| 8 | 이란 위기 + 유가 급등 + 달러 기근 | 2026-03 ~ 2026-03 | 태그형 (+) |
| 9 | 지정학 위기 + 인플레 재점화 + 유동성 경색 | 2026-03 ~ 2026-03 | 태그형 (+) |
| 10 | 지정학 리스크 + 유가 급등 + 유동성 경색 | **2026-03 ~ 2026-04-17** | 포맷 혼합 |
| 11 | 지정학 + 환율_FX + 에너지_원자재 | 2026-04-17 ~ 2026-04 | 태그형 (daily_update) |
| 12 | 휴전 완화 vs 유가 구조적 충격의 줄다리기 | 2026-04 ~ 2026-04 | 서술형 |

### 8.3 관찰되는 심각한 문제

1. **narrative 중복·churn**: 같은 "지정학 + 인플레" 개념이 서로 다른 문장으로 12번 반복. 실질적 regime 전환은 0~1회인데 history는 전환 12회로 기록.
2. **기간 포맷 혼용**: `YYYY-MM` vs `YYYY-MM-DD` 공존. `history[9]`: `"2026-03 ~ 2026-04-17"`처럼 한 entry 안에서도 혼합.
3. **기간 역순**: `history[6]`: `"2026-04 ~ 2026-03"` — 종료가 시작보다 이르다.
4. **태그형 vs 서술형 혼재**: `"지정학 + 환율_FX"` (daily_update 태그) vs `"휴전 완화 vs 유가 구조적 충격"` (debate 서술) — 같은 필드에 두 포맷 공존.
5. **weeks=1 + since=2026-04**: 이제 막 전환됐는데 `weeks=1` 기록 — 카운터가 의미 있는 수치로 증가하지 않음.
6. **debate 재실행으로 강제 전환**: 오늘 debate 2회 실행 후 `"휴전 완화 vs 유가 충격"` → `"지정학 완화 vs 구조적 인플레"` 즉시 전환. 3일 연속 규칙을 debate가 우회.

---

## 9. 근본 원인

### 9.1 쓰기 경로 이중화 (가장 큰 원인)

`regime_memory.json`을 다음 두 곳에서 각자 덮어씀:
- `daily_update.py::_step_regime_check` — 3일 연속 규칙 적용
- `debate_engine.py` — debate 실행 직후 narrative 재작성 (3일 규칙 무시)

→ **debate를 하루 여러 번 돌리면 narrative가 매번 바뀜.**
오늘 오전 debate 2회 실행 → history에 2건 추가되어 `#11`, `#12` 생성.

### 9.2 Docstring vs 코드 불일치

docstring: "상위 토픽이 현재 narrative 키워드와 **50% 이상 불일치** → shift 후보"
실제 코드: `if overlap_ratio < 0.3` → **70% 이상 불일치**여야 트리거

→ 규칙이 코드보다 관대하게 문서화되어 있어 운영자가 오해.

### 9.3 Keyword 매칭의 fragility

서술형 narrative `"지정학 완화 vs 구조적 인플레: 단기 랠리와 장기 리스크의 불일치"`:
- `.replace('+',' ').replace(',',' ').split()` 후 키워드: `["지정학","완화","vs","구조적","인플레:","단기","랠리와",...]`
- `"인플레:"`는 `:` 포함되어 토픽 `"물가_인플레이션"`과 `in` 매칭 안 됨
- `"vs"`, `"단기"`, `"랠리와"` 같은 불용어가 키워드로 섞여 있어 false match

### 9.4 Period 포맷 미정의

코드가 이벤트마다 다른 포맷을 씀:
- 신규 `current.since`: `date.today().isoformat()` → `2026-04-17`
- history entry: `current.get("since", "?")` ~ `date.today().isoformat()` → `"?"` 또는 `YYYY-MM` 또는 `YYYY-MM-DD`
- debate_engine 쪽은 별도 포맷 사용 추정 (YYYY-MM)

→ 한 파일에 세 가지 포맷 공존.

### 9.5 sentiment 체크 미구현

docstring: "sentiment가 현재 regime 방향과 반대 → shift 후보"
실제 코드: 구현 없음. `delta.get('sentiment')`를 읽지 않음.

### 9.6 Cooldown 부재

regime 전환 확정 후 즉시 다시 전환 감지 가능. 노이즈가 많으면 주 단위로 왔다 갔다.

### 9.7 weeks counter 증가 로직 없음

`regime['current']['weeks']`는 전환 시에만 0으로 초기화되고, daily_update가 매일 실행되어도 증가하지 않음. 값 `1`은 누군가 수동 설정한 것으로 추정.

---

## 10. 개선안 (우선순위별)

### P0 — 정합성 결함 (즉시 수정)

#### 10.1 쓰기 경로 단일화 — debate의 덮어쓰기 금지

```python
# debate_engine.py
# BAD (현재): regime_memory.json 직접 쓰기
# GOOD: regime_memory는 daily_update만 쓴다. debate는 읽기 전용.
```

debate가 생성한 narrative는 `draft.json.debate_narrative` 등 별도 필드로만 저장.
regime 전환은 여전히 daily_update의 3일 연속 규칙으로만 확정.

#### 10.2 Narrative 포맷 고정

선택: **태그형만 사용** (논리 투명하고 매칭 안정).
```
dominant_narrative: "지정학 + 환율_FX + 에너지_원자재"  # 토픽 태그 " + " 조인
```
서술형은 `narrative_description` 별도 필드로 분리. 매칭은 태그형 필드로만.

#### 10.3 Period 포맷 표준화

전 포맷을 `YYYY-MM-DD`로 통일. `since`가 `"?"` 또는 `YYYY-MM`인 기존 entry는 마이그레이션 스크립트 1회 실행.

```python
def _normalize_period_date(s: str) -> str:
    if not s or s == '?': return date.today().isoformat()
    if len(s) == 7: return f'{s}-01'   # YYYY-MM → YYYY-MM-01
    return s
```

#### 10.4 Docstring vs 코드 일치

docstring을 코드에 맞춰 수정 또는 threshold를 0.5로 변경. 의사결정 필요:
- 보수적(shift 적게): 현재 0.3 유지
- 문서대로: 0.5로 완화

→ 현재 history의 churn을 보면 **0.3도 충분히 민감**. 유지 + 문서 수정 권장.

---

### P1 — 안정성 보강 (다음 배치)

#### 10.5 Cooldown 도입

```python
MIN_REGIME_DURATION_DAYS = 14
since_days = (date.today() - date.fromisoformat(regime['current']['since'])).days
if since_days < MIN_REGIME_DURATION_DAYS:
    shift_detected = False   # 전환 후 2주는 잠금
```

#### 10.6 weeks counter 자동 증가

```python
# daily_update 실행 시마다
since_date = date.fromisoformat(regime['current']['since'])
regime['current']['weeks'] = (date.today() - since_date).days // 7
```

#### 10.7 Sentiment 반대 체크 구현

```python
current_direction = regime['current'].get('direction', 'neutral')  # bullish/bearish/neutral
today_sentiment = delta.get('sentiment', 'neutral')
direction_opposite = (
    (current_direction == 'bullish' and today_sentiment == 'negative') or
    (current_direction == 'bearish' and today_sentiment == 'positive')
)
if direction_opposite:
    shift_detected = True
    shift_reason = f'sentiment 반전: {current_direction} → {today_sentiment}'
```

#### 10.8 Keyword 매칭을 토픽 taxonomy 기반으로

narrative 텍스트에서 키워드를 split로 뽑지 말고, **저장 시점에 토픽 태그 목록을 명시적으로 기록**:
```python
regime['current'] = {
    'dominant_narrative': '지정학 + 환율_FX + 에너지_원자재',
    'topic_tags': ['지정학', '환율_FX', '에너지_원자재'],   # ← 추가
    'since': '2026-04-17',
    'direction': 'bearish',
}
# 매칭도 topic_tags vs top_topics로 집합 비교
overlap = len(set(regime['current']['topic_tags']) & set(top_topics))
```

---

### P2 — 품질 추적 (여유 있을 때)

#### 10.9 `_regime_quality.jsonl` 로그

```python
# 매 daily_update마다 append
{
  "date": "2026-04-17",
  "overlap_ratio": 0.22,
  "shift_candidate": true,
  "consecutive_days": 1,
  "shift_confirmed": false,
  "top_topics_today": ["지정학","환율_FX","에너지_원자재"],
  "current_tags": ["지정학","환율_FX","에너지_원자재"]
}
```

→ 월말에 "실제 전환 1회인데 감지 3회" 같은 오탐률 추적 가능.

#### 10.10 History 역순/중복 가드

```python
def _append_history(regime, entry):
    # 기간 역순 체크
    start, end = entry['period'].split(' ~ ')
    if start > end:
        raise ValueError(f'역순 period: {entry["period"]}')
    # 직전 entry와 narrative 동일하면 병합
    if regime['history'] and regime['history'][-1]['narrative'] == entry['narrative']:
        prev = regime['history'][-1]
        prev['period'] = prev['period'].split(' ~ ')[0] + ' ~ ' + end
        return
    regime['history'].append(entry)
```

---

## 11. 작업 순서 제안 (Regime Change)

| Phase | 작업 | 예상 효과 | 리스크 |
|-------|------|-----------|--------|
| P0.1 | debate의 regime_memory 쓰기 제거 | churn 90%+ 감소 | debate narrative가 더 이상 regime에 영향 안 줌 — 수용 가능 |
| P0.2 | narrative 태그형 고정 + 서술형 분리 | 매칭 안정, 포맷 통일 | history 마이그레이션 필요 |
| P0.3 | Period 포맷 `YYYY-MM-DD` 통일 | 역순·혼합 제거 | 기존 파일 1회 변환 |
| P1.1 | topic_tags 필드 + 집합 기반 매칭 | keyword fragility 제거 | regime_memory 스키마 변경 |
| P1.2 | 14일 cooldown | 민감도 적정화 | 실제 급변 시 지연 감지 |
| P1.3 | sentiment 반전 체크 | 지표 다양화 | delta.sentiment 신뢰도 의존 |
| P2.1 | `_regime_quality.jsonl` | 오탐률 측정 | 없음 |
| P2.2 | history 가드 | 데이터 무결성 | 없음 |

**P0 3건만 적용해도** 오늘자 debate 재실행이 narrative를 뒤바꾸는 문제가 사라지고, history churn이 확연히 줄어들 전망.

---

## 12. GraphRAG ↔ Regime 연관성

두 시스템은 현재 **느슨하게만 결합**:
- GraphRAG: 월별 인과 그래프 + 전이경로 8개
- Regime: 일별 상위 토픽 카운트 + 3일 연속 규칙

**개선 여지**: regime 전환 감지 시 GraphRAG의 `transmission_paths`도 **해당 regime의 신규 경로를 우선 반영**하도록 연동. 예컨대 `지정학 완화` regime 확정 시 트리거 목록에 `휴전`·`중동 긴장 완화` 동적 추가.

현재는 양쪽이 독립 실행되어 이 연결이 끊어져 있음. Part 1 §4.4 (트리거 동적 선택)와 Part 2 §10.8 (topic_tags)이 구현되면 자연스럽게 결합 가능.

