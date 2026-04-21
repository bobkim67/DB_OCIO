# Selection diversity — 옵션 비교 (v13.3 Step 3)

- 작성: 2026-04-21
- 입력: 2026-04 raw 후보 풀 8건 (alias 적용 전)

---

## 1. 시뮬레이션 입력 (raw 후보 8건)

```
1. 유가          에너지_원자재    imp=4.09  arts=2542  role=True
2. 이란          지정학          imp=2.81  arts=3096  role=False
3. 국제유가      에너지_원자재    imp=2.40  arts=1032  role=False
4. 호르무즈 해협 지정학          imp=1.85  arts= 553  role=False
5. 환율          환율_FX         imp=1.69  arts=2092  role=False
6. 반도체        테크_AI_반도체   imp=0.77  arts=2234  role=False
7. 호르무즈 봉쇄 지정학          imp=0.52  arts=  78  role=False
8. 이란 협상     지정학          imp=0.35  arts= 165  role=False
```

---

## 2. 옵션 결과 비교

| 옵션 | total | 분포 | 지정학 비중 | near-dup |
|------|-------|------|-------------|----------|
| **1. 현행** (cap=3) | **7** | 지정학3 / 에너지2 / FX1 / 테크1 | 43% (3/7) | 유가+국제유가 둘 다 |
| **2. cap=2 + floor=1** | 6 | 지정학2 / 에너지2 / FX1 / 테크1 | 33% (2/6) | 둘 다 |
| **3. cap=3 + floor=1 + suppress** | 6 | 지정학3 / 에너지1 / FX1 / 테크1 | 50% (3/6) | 국제유가/이란협상 drop |
| **3b. cap=2 + suppress** | 5 | 지정학2 / 에너지1 / FX1 / 테크1 | 40% (2/5) | 국제유가/이란협상 drop |

---

## 3. 항목별 평가

| 항목 | Option 1 | Option 2 | Option 3 | Option 3b |
|------|----------|----------|----------|-----------|
| 최종 entity 수 | 7 | 6 | 6 | 5 |
| taxonomy coverage | 4 | 4 | 4 | 4 |
| 상위 10개 다양성 | 보통 | 양호 | 양호 | 가장 양호 |
| 지정학 비중 | 43% | 33% | 50% | 40% |
| near-dup 감소 | ✗ | ✗ | ✓ | ✓ |
| explainability | 단순 | 보통 | 보통 | 복잡 |
| 구현 복잡도 | 0 | 중 | 중 | 중 |

### 관찰
- **floor=1은 현재 풀에서 효과 0** — 후보가 4개 taxonomy에만 있고, under-covered taxonomy 후보가 풀에 미진입 (alias miss). 후보가 더 들어와야 floor가 의미 가짐.
- **suppression**은 명확한 information de-duplication. 유가/국제유가, 이란/이란 협상의 substring 관계가 정당.
- **cap=2로 낮추면** 지정학 비중 떨어지지만 entity 수도 줄어 정보 손실.

---

## 4. 채택 결정

**Option 3 (cap=3 default 유지 + suppress_near_duplicates=True 활성화)** 채택.

세부 결정:
- `per_taxonomy_cap=3` 유지 (지정학이 실제 dominant signal일 때 reflect)
- `suppress_near_duplicates=True` 활성화 (substring 관계 후순위 drop)
- `per_taxonomy_floor=0` (default 유지) — 옵션은 추가하되 활성화는 alias 풀 보강 후

근거:
- 본 batch가 alias 1건만 추가 → floor 활성화 시 효과 0 또는 낮음
- suppression은 evidence 명확하고 information loss 최소
- cap=2로 줄이면 지정학 entity 보존성 하락

---

## 5. 구현 인터페이스

```python
def select_entity_candidates(
    nodes, edges, paths, articles,
    max_entities: int = 12,
    per_taxonomy_cap: int = 3,
    per_taxonomy_floor: int = 0,        # ★ v13.3 신규
    suppress_near_duplicates: bool = False,  # ★ v13.3 신규
) -> list[dict]:
    ...
```

`refresh_base_pages_after_refine` 호출에서 `suppress_near_duplicates=True` 전달.
floor는 default off로 두고 future-proof만 확보.

---

## 6. 다음 트리거

floor 활성화 검토 조건:
- under-covered taxonomy의 alias가 보강되어 raw 풀에 후보 진입
- 또는 taxonomy 14개 중 entity 보유 비율이 50% 이상으로 늘어남

별도 시뮬레이션 후 결정.
