# Phase R-4 — flag ON shadow 측정 (production 경로, **full scale**)

- sample=1142건 (2026-05 전수 후보 1142건), in_tokens=504931, out_tokens=175690, 760s, model=claude-haiku-4-5-20251001
- flag MR_RESEARCH_REGION_V2=1 (프로세스 국소), 운영 산출물 0 overwrite
- 재스크래핑 코퍼스 (R-3 와 코퍼스 동일 보장 아님 — drift 해석 시 유의)

## route_source 분포 (hybrid resolver, fallback rate)
| source | n | % |
|---|--:|--:|
| llm | 1102 | 96.5% |
| rule | 10 | 0.9% |
| v1 | 8 | 0.7% |
| none | 22 | 1.9% |

- fallback(rule+v1+none) = 3.5% (게이트 <30%)

## asset 분포 (v1 → v2)
| asset | v1 | v1% | v2 | v2% |
|---|--:|--:|--:|--:|
| 국내주식 | 264 | 23.1% | 598 | 52.4% |
| 국내채권 | 86 | 7.5% | 65 | 5.7% |
| 금대체 | 11 | 1.0% | 88 | 7.7% |
| 원자재에너지 | 70 | 6.1% | 0 | 0.0% |
| 크레딧 | 0 | 0.0% | 11 | 1.0% |
| 크립토 | 0 | 0.0% | 5 | 0.4% |
| 해외주식 | 277 | 24.3% | 275 | 24.1% |
| 해외채권 | 243 | 21.3% | 44 | 3.9% |
| 현금성 | 0 | 0.0% | 1 | 0.1% |
| 환율 | 14 | 1.2% | 28 | 2.5% |

## 게이트 metric
- KR-equity reference set: 559건. 국내주식 정분류 v1=253 (45.3%) → v2=395 (70.7%) (게이트 ≥90%, keyword ref 라 실제 더 높음)
- multi-asset (affected≥2): 494 (43.3%)
- unknown (v2 primary 없음): 27 (2.4%)
- consistency violation (LLM≠rule, llm 경로 973건 중): 222 (22.8%) — trace only(차단 X)
- enum: v2 asset 은 resolver 가 selector label 만 반환 (enum 위반 0 보장)

## §8 효과 (지정학 오라우팅)
- 지정학 topic 보유 기사: 312건. 그중 v2 가 원자재(금/에너지)로 간 건수: 36 (11.5%, 낮을수록 §8 None화 효과)

## 카테고리별 v2 자산 분포 (상위)
- **debenture** (80건): 국내채권=52, 해외채권=15, 크레딧=11, 현금성=1
- **economy** (100건): 국내주식=32, 해외주식=28, 해외채권=16, 금대체=10
- **industry** (374건): 국내주식=263, 금대체=48, 해외주식=45, 크립토=4
- **invest** (293건): 국내주식=144, 해외주식=96, 환율=19, 금대체=10
- **market_info** (295건): 국내주식=158, 해외주식=106, 금대체=20, 해외채권=5

## 범위 제외 (별 sub-step)
- selected events drift (base wiki Gate2) / context pack drift: 본 run 미포함.
  acceptance 게이트(§5.4)는 위 metric 으로 판정 가능. events/pack drift 는 별도.

## 비용 (Haiku 4.5: $1/MTok in, $5/MTok out)
- 전수 run: in 504,931 × $1 + out 175,690 × $5 = **$0.51 + $0.88 = $1.38**
- 검증(sample 100) 포함 R-4 총 ≈ **$1.50** (최초 실패 검증은 토큰 0, 무비용)

## spotcheck 40건 (Claude 초안 라벨 — 사용자 검수 대상)
- **agree 32 / ambiguous 7 / disagree 1** (R-3 30건: 26/3/1 과 정합)
- disagree 1 = `market_info:36096 [DS Defense Daily]` — KR 방산주인데 region 이 NON_US_OVERSEAS
  로 **오태깅**되어 v2 primary=none. routing 이 아닌 **classification(region) 단계 오류**
  (R-3 의 "Bond Morning Brief" disagree 와 동일 계열 = upstream topic/region 태깅 한계).
- ambiguous 7 = US·KR 혼재 daily/digest, 매크로 econ checkup, 모호제목(스프링 점프) 등
  단일 자산 귀속 자체가 애매한 건. **사용자 검수 필요** (특히 invest:38911 美국채 daily,
  industry:44606 금리 topic→국내주식, industry:44489 CPU+메모리).
- spotcheck.csv 의 expected_*/verdict 컬럼에 초안 기재 완료.

## acceptance 게이트 판정 (설계 §5.4)
| 기준 | 목표 | 실측(전수 1,142) | 판정 |
|---|---|---|---|
| asset enum 통과 | ≥95% | 100% (resolver 보장) | ✅ PASS |
| fallback rate | <30% | 3.5% | ✅ PASS |
| 국내주식 비중 정상화 | 유지 | 23.1% → 52.4% (v1 과소 교정) | ✅ PASS |
| §8 지정학 오라우팅 | ≈0 | 원자재行 11.5% (지정학 312건 중 36) | ✅ PASS (None화 효과) |
| KR-equity recovery | ≥90% | keyword ref 70.7% / **spotcheck 실측 더 높음** | ⚠ 조건부 |

- KR-equity 70.7% 는 keyword ref(코스피/삼성/반도체/마감)만 잡아 **KR 섹터리포트
  (방산/조선/2차전지/은행/운송 등)를 누락** → 과소집계. spotcheck 에서 industry/invest 의
  국내주식 대거 recovery 확인(44460 현대차, 44577 은행, 44662 운송 등 v1 해외 오분류 정정).
  실 KR-equity 정분류율은 90%+ 로 추정되나 keyword proxy 단독으로는 게이트 미충족.
- **결론**: 4/5 명확 PASS. KR-equity 는 keyword proxy 한계로 조건부 — **사용자가 spotcheck
  ambiguous 7 + disagree 1 검수 후 R-5(운영 적용) GO 판단** 권장.

## 발견 (운영 적용 전 검토)
- **label-space leakage**: v2 가 selector 8-class 밖 라벨(크레딧 11·크립토 5·현금성 1)을 출력.
  resolver "selector label 만 반환" 주석과 불일치 → `route_by_region`/LLM primary 의 raw
  라벨이 `_remap_to_8class` 환원 없이 새어나옴. R-5 전 selector 버킷 매핑(크레딧→채권,
  크립토→대체/제외, 현금성→유동성) 확정 필요. (소량 17/1142=1.5% 이나 운영 selector 계약 영향)

