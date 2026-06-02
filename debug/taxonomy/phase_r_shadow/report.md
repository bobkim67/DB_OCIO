# Phase R-3 — flag ON shadow 측정 (production 경로, dry 100건)

- sample=100건, out_tokens=16022, 69s, model=claude-haiku-4-5-20251001
- flag MR_RESEARCH_REGION_V2=1 (프로세스 국소), 운영 산출물 0 overwrite

## route_source 분포 (hybrid resolver)
| source | n | % |
|---|--:|--:|
| llm | 97 | 97.0% |
| rule | 0 | 0.0% |
| v1 | 0 | 0.0% |
| none | 3 | 3.0% |

## asset 분포 (v1 → v2)
| asset | v1 | v2 |
|---|--:|--:|
| 국내주식 | 26 | 61 |
| 국내채권 | 5 | 4 |
| 금대체 | 0 | 7 |
| 원자재에너지 | 7 | 0 |
| 해외주식 | 24 | 19 |
| 해외채권 | 23 | 3 |
| 환율 | 2 | 3 |

## 게이트 metric
- KR-equity reference set: 51건. 국내주식 정분류 v1=24 (47.1%) → v2=38 (74.5%)
- multi-asset (affected≥2): 42 (42.0%)
- unknown (v2 primary 없음): 3 (3.0%)
- enum: v2 asset 은 resolver 가 selector label 만 반환 (enum 위반 0 보장)

## §8 효과 (지정학 오라우팅)
- 지정학 topic 보유 기사: 32건. 그중 v2 가 원자재(금/에너지)로 간 건수: 5 (낮을수록 §8 None화 효과 — LLM affected/보고대상 우선)

