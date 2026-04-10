# 내부 파일럿 체크리스트

> 운영자가 파일럿 실행 전 확인하는 항목. 모두 PASS여야 파일럿 가능.

## 1. 뉴스 수집

- [ ] `python -m market_research.pipeline.daily_update --dry-run` 정상 실행
- [ ] 네이버 뉴스 수집 건수 > 0
- [ ] Finnhub 뉴스 수집 건수 > 0
- [ ] 당월 뉴스 JSON 파일 존재 (`data/news/YYYY-MM.json`)

## 2. Financial Filter + LLM 분류

- [ ] `_filter_reason` 있는 기사의 `_classified_topics` = `[]` (resurrect 0건)
- [ ] `_classified_topics`에 V1 토픽명 0건
- [ ] `primary_topic`에 V1 토픽명 0건
- [ ] `topic_taxonomy_version` = `'14_v2'`

```bash
# 검증 명령
python -c "
import json; from pathlib import Path
data = json.loads(Path('market_research/data/news/2026-03.json').read_text(encoding='utf-8'))
V1 = {'금리','달러','물가','관세','안전자산','미국채','유가_에너지','AI_반도체','한국_원화','유럽_ECB','유동성_배관'}
v1 = sum(1 for a in data['articles'] for t in a.get('_classified_topics',[]) if t.get('topic') in V1)
filt = sum(1 for a in data['articles'] if a.get('_filter_reason') and a.get('_classified_topics'))
print(f'V1잔류: {v1}, filter+topic: {filt}')
"
```

## 3. Dedupe / Primary / Salience

- [ ] primary 비율 > 95%
- [ ] 최대 dedup 그룹 < 20건
- [ ] singleton event에 primary 없는 그룹 = 0개

```bash
python -c "
import json; from pathlib import Path; from collections import defaultdict
data = json.loads(Path('market_research/data/news/2026-03.json').read_text(encoding='utf-8'))
arts = data['articles']
primary = sum(1 for a in arts if a.get('is_primary'))
groups = defaultdict(int)
for a in arts: groups[a.get('_dedup_group_id','')] += 1
print(f'primary: {primary}/{len(arts)} ({primary/len(arts)*100:.1f}%)')
print(f'최대그룹: {max(groups.values())}')
"
```

## 4. vectorDB

- [ ] 당월 컬렉션 존재 (`news_YYYY-MM`)
- [ ] 한국어 검색 테스트 통과 (의미 매칭)

```bash
python -c "
from market_research.analyze.news_vectordb import search
r = search('원달러 환율 급등', '2026-03', top_k=3)
for x in r: print(f'{x[\"title\"][:50]} (score={x[\"hybrid_score\"]:.3f})')
"
```

## 5. GraphRAG

- [ ] 당월 insight_graph JSON 존재
- [ ] 전이경로 > 0개
- [ ] TOPIC_DECAY_CLASS 키가 V2

```bash
python -c "
import json
g = json.loads(open('market_research/data/insight_graph/2026-03.json', encoding='utf-8').read())
print(f'노드 {len(g[\"nodes\"])}, 엣지 {len(g[\"edges\"])}, 경로 {len(g.get(\"transmission_paths\",[]))}')
"
```

## 6. Debate 입력 품질

- [ ] primary_classified 기사 중 diversity guardrail 동작 (토픽 3개+)
- [ ] evidence_ids 15건 추적됨

## 7. 수치 가드레일

- [ ] `numeric_guard.py` import 정상
- [ ] debate 실행 시 `[가드레일]` 로그 출력 (불일치 시 경고)

```bash
python -c "
from market_research.report.numeric_guard import check_comment_numbers, format_guard_report
issues = check_comment_numbers('S&P500 -4.0%', {'bm_returns': {'S&P500': -4.5}})
print(format_guard_report(issues))
"
```

## 8. Evidence Trace

- [ ] `evidence_trace.py` import 정상
- [ ] Opus 코멘트에 `[ref:N]` 태그 포함 여부 확인

## 9. Gold Eval

- [ ] `python -m market_research.tests.gold_eval --evaluate` 실행
- [ ] precision > 85%, topic > 80%, recall > 90%, primary > 95%

## 10. 최종 확인

- [ ] `python -m market_research.pipeline.daily_update` 전체 실행 성공
- [ ] debate 테스트: `python -m market_research.report.cli build 07G04 -q 1 -y 2026`
- [ ] 생성된 코멘트에 수치 오류 없음 (가드레일 통과)
- [ ] 생성된 코멘트에 [ref:N] 태그 포함
