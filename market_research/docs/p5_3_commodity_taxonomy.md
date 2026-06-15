# P5.3 — 03_Assets commodity taxonomy alignment (조사 보고서)

> 상태: **조사·설계 (운영 미반영)**. 작성 2026-06-15.
> 목표 운영 taxonomy: **금 / 원유 / 기타 원자재**. 현재 운영=금/금_대체/원자재, claim 8-class=원자재금(단일).
> 트리거: 2026-05 운영 03_Assets 5개 반영 시 원자재금 skip([[project_wiki_from_naver_research]]).

---

## 0. 핵심 결론 (요약)

- **claim 레벨은 "원자재금" 단일 8-class** (classifier prompt "에너지·원자재·금 전부 원자재금 하나로", `ALLOWED_ASSET_CLASSES`). → 금/원유/기타 분리는 **claim 자체가 아니라 page 레벨 keyword fan-out** 으로만 가능(현재 구조).
- **2026-05 fan-out = 원유 49 / 금 2 / 기타 1 / 미분류 10** (총 62). 압도적 oil. 월별 편차 큼(이달 금 희소).
- market_db dataset 3종 다 존재: 금=Gold Spot(408)/GC00(95)/LBMA(277), **원유=WTI Crude(98)**, 기타=GSCI(87)/DBC(356).
- 03_Assets 는 **context pack→debate 가 디렉토리 glob 으로 소비** → legacy 금/금_대체/원자재(구 news 템플릿) 도 현재 pack 에 유입.

→ **권장: 단기 Option C(legacy commodity context-pack 제외/보류) + 별도 migration 트랙으로 Option B**. 키워드 fan-out 이 heuristic·월별 불안정이라 즉시 운영 분리는 위험.

---

## 1. 운영 03_Assets commodity page 소비처

| name | file_exists | referenced_by | used_in_context_pack | used_in_debate | note |
|------|:---:|---|:---:|:---:|---|
| 금 | ✅ | wiki_context_pack(03_Assets glob), wiki_retriever | ✅ | ✅ (A.6 Assets) | Gold market_db 가능 |
| 금_대체 | ✅ | 03_Assets glob | ✅ | ✅ | ★애매 이름(대체=무엇?) |
| 원자재 | ✅ | 03_Assets glob | ✅ | ✅ | 원유·기타 미분리 |
| 원자재금 | ❌(page 없음) | `ALLOWED_ASSET_CLASSES`/classifier/aggregator | claim layer only | — | **claim 8-class canonical, page 아님** |
| 원유 | ❌ | — | — | — | 신규 후보 |
| 기타원자재 | ❌ | — | — | — | 신규 후보 |

- 소비 경로: `wiki_context_pack_builder` 가 `03_Assets/{period}_*.md` 를 directory glob 으로 수집(개별 파일명 하드참조 아님) → page 추가/삭제는 pack 구성에 자동 반영. `debate_engine` A.6, `wiki_retriever`(market_debate/fund_comment) 도 동일 디렉토리 사용.
- 코드의 "원자재금"/"원자재" 문자열은 대부분 **claim 8-class / classifier 매핑**(news_classifier, claim_extractor)이지 03_Assets 파일명이 아님.

## 2. research claim fan-out 가능성 (원자재금 → 금/원유/기타)

| target | claim_count(2026-05) | top_claims | market_metric_available | note |
|--------|:---:|---|---|---|
| 원유 | **49** | 전쟁협상→에너지 안정화 / 지정학 공급차질 / 중동 리스크 | **WTI Crude id=98** | 이달 dominant(79%) |
| 금 | 2 | (희토류·철강 오버킷 의심) | Gold Spot 408 / GC00 95 | 이달 희소 |
| 기타 원자재 | 1 | 광섬유 가격 | GSCI 87 / DBC 356 | thin |
| 미분류 | 10 | 탄소배출권 / 환경규제 / 중국 철강 | — | 키워드 재정의 필요 |

- fan-out 은 **keyword heuristic** 으로 동작은 하나, ① 월별 편차 큼(이달 금 2건) ② 미분류 10건(탄소배출권/철강/환경규제 = 산업·정책 경계) ③ claim 8-class 가 단일이라 **authoritative sub-label 부재**.
- 정밀 분리는 **claim/classifier 레벨 sub-tag**(원자재금 → {금, 원유, 산업원자재})가 이상적이나, `ALLOWED_ASSET_CLASSES`/classifier prompt 변경 = 전 pipeline 영향(별 트랙).

## 3. 운영 taxonomy 전환안 비교

### Option A — 기존 3개 유지 + 의미 재정의 (금=금 / 원자재=원유 / 금_대체=기타·deprecated)
- 장점: 파일 churn 최소(신규 0). 장점 외 거의 없음.
- 단점: "원자재"=원유는 misnomer(혼선). "금_대체→기타"는 의미 불명. 표시명/asset_class 와 파일명 불일치 누적.

### Option B — 명확한 파일명 전환 (금 / 원유 / 기타원자재 신규, 금_대체·원자재 deprecated+alias)
- 장점: taxonomy 명확, 장기 정합.
- 단점: 신규 2 page + deprecate 2 + context pack 소비자에 alias/redirect 필요. claim fan-out heuristic 의존(미분류 처리). **migration 규모 큼** → 별 트랙 권장.

### Option C — 단기 유지 + context pack filter (이번 달 5개만, legacy commodity 보류)
- 장점: 위험 최소. 이미 5개 반영 완료. legacy 금/금_대체/원자재(구 news 내용)를 **context pack 에서 제외/저우선** 처리해 stale 유입만 차단.
- 단점: 원자재 계열 운용보고 공백(이번 달 미공급). 추후 migration 필요.

---

## 4. 권장 (사용자 결정 대기)

1. **이번 달**: Option C. 5개(주식·채권·환율)만 운영 반영(완료). commodity 4 page(금/금_대체/원자재)는 **context pack 에서 제외하거나 저우선**으로 stale news 내용 유입 차단(코드 변경 시 별 GO).
2. **별 트랙(migration)**: Option B 를 정식 설계 — 단 page-level keyword fan-out 보다 **claim/classifier 레벨에서 원자재금 sub-tag(금/원유/산업원자재)** 도입이 근본적. 미분류(탄소배출권/철강/환경규제) 분류 규칙 + 원유 market_db(WTI 98) 등록 + 기타 GSCI(87) 등록 포함.
3. claim 8-class("원자재금")는 **당분간 불변**(전 pipeline 영향). 분리는 page/aggregation 레이어에서.

## 5. 금지 (P5.3 조사 단계)
- 원자재 계열 운영 overwrite / 금_대체·원자재 삭제 / 신규 원유·기타원자재 생성 / context pack 재생성 / debate 재실행 / report cache overwrite / claim 8-class 변경 — 전부 별 GO.
