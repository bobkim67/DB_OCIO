# Entity diversity — 편중 진단 (v13.3 Step 1)

- 작성: 2026-04-21
- 입력: 02_Entities/ (7건) · `_taxonomy_remap_trace.jsonl` (0건) · `data/insight_graph/2026-04.json` · `data/news/2026-04.json`

---

## 1. 현재 분포

| taxonomy | entity 수 | aliases (PHRASE_ALIAS) | 비고 |
|----------|-----------|-----------------------|------|
| 통화정책 | 0 | 7 | alias 충분, 노드 매칭 0 |
| 금리_채권 | 0 | 5 | alias 충분, 노드 매칭 0 |
| 물가_인플레이션 | 0 | 5 | alias 충분, 노드 매칭 0 |
| 경기_소비 | 0 | 2 | **under-covered** |
| 유동성_크레딧 | 0 | 4 | **under-covered** |
| 환율_FX | 1 | 5 | 환율 |
| 달러_글로벌유동성 | 0 | 4 | **under-covered** |
| 에너지_원자재 | 2 | 6 | 유가, 국제유가 (near-duplicate) |
| 귀금속_금 | 0 | 5 | alias 충분, 노드 매칭 0 |
| 지정학 | 3 | 17 | 이란, 호르무즈 해협, 호르무즈 봉쇄 (cap 도달) |
| 부동산 | 0 | 1 | **under-covered** |
| 관세_무역 | 0 | 3 | **under-covered** |
| 크립토 | 0 | 2 | **under-covered** |
| 테크_AI_반도체 | 1 | 4 | 반도체 |
| **합계** | **7** | 70 | 14 중 4 taxonomy만 entity 보유 |

---

## 2. 핵심 편중 3개 진단

### 2.1 지정학 편중 (3/7 = 43%)

원인:
- 지정학 alias 17개로 압도적 (다른 taxonomy 평균 4개)
- 4월 이슈가 실제로 지정학 중심 (이란/호르무즈)
- per_taxonomy_cap=3로 max 3건까지 채워짐

### 2.2 같은 taxonomy 내 near-duplicate

- 에너지_원자재: **유가** vs **국제유가**
  - label substring 관계 ("유가" ⊂ "국제유가")
  - 같은 dimension의 dual 노출
  - 화면 다양성 저하

다른 잠재 near-dup (현재 entity는 아님):
- 지정학: 이란 vs 이란 협상 (substring)
- 환율_FX: 환율 vs 원_달러_환율_변동 (구문)

### 2.3 under-covered taxonomy의 graph 노드 잠재 매핑

각 under-covered taxonomy로 잠재 매핑 가능한 miss node 검색 결과 (kw 기반):

| taxonomy | miss 노드 잠재 후보 | feasibility |
|----------|---------------------|-------------|
| 경기_소비 | 5건 (전부 descriptive: `기업_수익성_악화_우려` 등) | 낮음 (직접 alias 어려움) |
| 관세_무역 | 8건 (대부분 협상/이란 관련) | 낮음 (다의어) |
| 달러_글로벌유동성 | 7건 (`달러` 외 모두 descriptive) | 보통 (`달러` 단독 audit 필요) |
| 환율_FX | 5건 (`원/달러`, `유로` 등) | **보통** (`원/달러` 후보 가능) |
| 테크_AI_반도체 | 5건 (`삼성전자`, `SK하이닉스`, `나스닥` 등) | 정책 미정 (종목명) |

---

## 3. 진단 결론

1. **지정학 편중은 cap=3 자체보다 alias 17개의 압도적 풀에서 비롯됨**.
   per_taxonomy_cap을 줄이면 분포 개선되지만, 동시에 지정학 entity 정보 손실.

2. **near-duplicate (유가/국제유가)는 명백한 정보 중복**.
   suppression 도입의 evidence 충분.

3. **under-covered taxonomy 보강은 alias만으로는 한계**.
   - 경기_소비/관세_무역은 직접적 단독 명사 노드가 없음 (descriptive form만)
   - 달러_글로벌유동성은 `달러` 다의성 의존 (Step 2 audit)
   - 환율_FX는 `원/달러` 1건 가능
   - 테크는 종목명 정책 미정
   → 현실적으로 ≤1건 추가 가능

4. **floor=1 정책 의의**: 현재는 효과 0이지만 alias 보강 후 의미 생김.
   → 옵션화하여 future-proof, default off로 두기.

→ Step 3 옵션 비교에서 **suppression**이 1순위 evidence, **floor**는 옵션 추가, **alias 1건만** approve.
