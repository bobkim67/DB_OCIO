# 설계서 초안 — Research-Synthesis Wiki (naver_research 기반 wiki/코멘트)

> 상태: **초안 (구현 전, 사용자 확인 대기)** · 작성 2026-06-15
> 결정 근거: 월간 wiki/코멘트 주 소스를 **naver_research 분해→재종합**으로 전환. news 는 운영 경로에서 분리(fetch 만 유지, 활용 추후 스터디). monygeek 시각 병합.
> 조사 출처: claim_extractor / asset_fund_enrichment_builder·route_by_region / debate·synthesis 3트랙 재사용 범위 조사 (2026-06-15).

---

## 1. 목표 / 배경

- **현재 (실측 2026-05)**: base wiki(01_Events 8 / 03_Assets 11)가 `data/news`(3,951건 전부 news)로 ~100% 구성. naver_research adapted 1,183건은 base 콘텐츠에 0건(GraphRAG 간접만).
- **목표**: naver_research(증권사 리서치) + monygeek(블로그 관점)을 **원자 claim 으로 분해 → 자산군/테마/기간별로 재종합 → wiki page** 작성. news 는 핵심 경로에서 제외.
- **비핵심**: event clustering(event→cluster→narrative). 이번 구조는 **research claim → asset aggregation → synthesis**.

---

## 2. 목표 아키텍처

```text
[수집 — 기존 유지]
  naver_research raw (5 cat) ──┐
  monygeek blog posts ─────────┤
  news (fetch만, 핵심경로 제외) │ (별도 스터디/비교용)
                               │
[분해 — 신규 adapter + 기존 claim_extractor 재사용]
  naver_research_adapter ──→ adapted/{month}.json (기존)
  monygeek_adapter (신규) ──→ research-claim 입력 정규화
        │
        ▼
  research_claim_extractor (claim_extractor 재사용 + research prompt)
        │  source_type=naver_research|monygeek, --target-suffix=research
        ▼
  data/claims/{month}.research.json   (운영 claim store 와 분리)

[재종합 — debate/synthesis 재사용]
  aggregate by (asset_class × theme × horizon)
        │
        ▼
  research_consensus (run_market_debate 변형: 자산군별 consensus/dissent)
        │  monygeek persona 이미 존재, evidence 70/30 이미 research 가중
        ▼
  09_Research_Synthesis/{period}_{asset}.md   (staging/audit page, 신규)

[소비 — 기존 03_Assets 재배선]
  build_asset_page: _related_events_for_asset(01_Events)
        → _related_research_for_asset(09_Research_Synthesis)  로 스왑
        ▼
  03_Assets/{period}_{asset}.md  (research 종합 기반 재작성)
```

핵심 원칙:
- **staging-first**: 09_Research_Synthesis 를 먼저 신설(audit). 품질 검증 후 03_Assets 가 소비하도록 전환. 03_Assets 즉시 갈아엎지 않음.
- **운영본 격리**: research claim 은 `--target-suffix=research` 로 `data/claims/{month}.research.json` 에 써서 기존 운영 claim store(`{month}.json`) md5 불변.

---

## 3. 입력 / 출력 데이터 구조

### 입력
| 소스 | 경로 | 형태 | 비고 |
|------|------|------|------|
| naver_research adapted | `data/naver_research/adapted/{month}.json` | article-like(title/summary_text/broker/date/category) | 기존 adapter 산출, claim_extractor 입력 호환 |
| monygeek posts | `data/monygeek/posts.json` | blog post(title/body/date) | 신규 adapter 로 article-like 정규화 필요 |

### 중간 산출
| 산출 | 경로 | 비고 |
|------|------|------|
| research claims | `data/claims/{month}.research.json` | 운영 claim store 와 파일 분리 |
| asset aggregation | (in-memory or `data/research/agg_{month}.json`) | 자산군×테마×기간 묶음 |

### 출력
| 산출 | 경로 | 소비처 |
|------|------|--------|
| Research Synthesis page | `wiki/09_Research_Synthesis/{period}_{asset}.md` | audit + 03_Assets 입력 |
| Asset page (재배선) | `wiki/03_Assets/{period}_{asset}.md` | client wiki/코멘트 |

---

## 4. Research Claim Schema (claim_extractor 확장)

기존 `claim_extractor` 의 REQUIRED/OPTIONAL 필드를 **그대로 상속**하고, research 전용 OPTIONAL 필드만 추가. (8-class `ALLOWED_ASSET_CLASSES`, validation soft/hard, ID 결정성, 저장 포맷 전부 재사용)

### 기존 필드로 이미 커버되는 것
| 사용자 요청 필드 | 기존 필드 | 매핑 |
|------------------|-----------|------|
| `horizon` (short/medium/long) | `horizon` | **정확 일치** (이미 enum) |
| `stance` (bullish/neutral/bearish) | `direction`(positive/negative/neutral/mixed) + `confidence` | 근접 — 단 enum 의미 다름(아래 갭) |
| `rationale` | `causal_chain[{source,target,relation}]` | 구조적 근거 일부 커버, 장문 rationale 은 갭 |
| `risk_factor` | `claim_type="risk"` | 라벨만, 구조화는 갭 |
| `affected_assets` | `affected_assets[{asset_class,direction,confidence,role}]` | 그대로 |
| `confidence` | `confidence` (claim) + per-asset confidence | 그대로 |
| `evidence_text` | `supporting_evidence_ids` | ID 만, 본문 텍스트는 갭 |

### 신규 OPTIONAL 필드 (research claim 전용)
```text
source_type   : "naver_research" | "monygeek"   (출처 레인)
broker_author : 증권사명 또는 블로거(author)      (귀속)
stance        : "bullish" | "neutral" | "bearish" (전망 방향, direction 과 별도 명시)
view          : 한 줄 view title (예: "반도체 비중확대")  (claim_text 와 별도)
rationale_text: 장문 논거 (causal_chain 보완)
risk_factor   : 구조화 리스크 (category/text)
evidence_text : 인용 원문 발췌 (≤N자)
theme         : claim 후 부여하는 테마 태그 (sectors 재활용 가능)
```
원칙(Q2): **테마 요약을 먼저 만들지 않음.** 원자 claim 추출 → `theme`/`sectors` 태그 부여 → 후속 단계에서 테마별 묶음.

> **D1 확정**: 신규 `stance` enum 추가, `direction` 은 기존 호환 필드로 유지.

### ★ stance ↔ direction 정의 분리 (혼용 금지)
**`stance` = 리서치 전망 어조**(해당 자산 보유 관점), **`direction` = 자산가격 영향 방향**. 둘은 독립이며 어긋날 수 있다.
> 예: "금리 상승 전망" → 채권 `stance=bearish`(채권에 부정적 view)이지만, 금리 자체 `direction=positive`(금리가 오른다). 둘을 같은 값으로 강제하면 안 됨.

기본(정렬되는 경우) 매핑표 — **default 가이드일 뿐, validator 가 강제하지 않음**:
| stance | direction (정렬 시) |
|--------|---------------------|
| bullish | positive |
| bearish | negative |
| neutral | neutral |
| mixed / 리포트 내 상충 | mixed (stance 는 대표 view 또는 neutral) |

> 구현: `stance` 는 `ALLOWED_STANCES={bullish,neutral,bearish,mixed}` soft 검증만. stance↔direction **일치 검증은 두지 않음**(의도적 디커플). `theme` 은 기존 `sectors`(≤3, TOPIC_TAXONOMY) 재사용 — 중복 필드 신설 안 함.

---

## 5. naver_research → claim decomposition 단계

1. **입력 정규화**: adapted/{month}.json (naver_research) + monygeek adapter 산출 → claim_extractor 입력 스키마(`article_id/title/source/date/topic/_classified_topics`)로 맞춤. naver_research adapted 는 이미 호환, summary_text→description 매핑 확인 필요.
2. **research prompt 신규**: `claim_extractor_prompt` 변형 — "증권사 리서치/블로그에서 **자산군별 전망·논거·리스크**를 원자 단위로 추출, broker/author·stance·view·rationale·risk_factor 출력" 규칙 추가. Taxonomy 제약(asset_class 8-class, region, sector)은 그대로.
3. **추출 실행**: Haiku, MAX_INPUT_EVIDENCE=50 배치. `--target-suffix=research` 로 운영본 격리. 비용 가드 $1/월 캡 재사용.
4. **검증**: 기존 soft/hard validator + `_remap_to_8class`(asset_class 정규화). 신규 stance/source_type enum soft validator 추가.
5. **저장**: `data/claims/{month}.research.json` (top-level keys + claims[] 동일 포맷).

---

## 6. monygeek 병합 방식

- monygeek = **관점(view) 레이어**. 같은 claim 파이프라인에 `source_type=monygeek` 로 태깅해 병합.
- debate 단계에서 **monygeek persona 가 이미 존재**(Bull/Bear/Quant/**monygeek**) → research consensus 에서 monygeek claim 을 그 persona 입력으로 직접 연결.
- 병합 원칙: naver_research(증권사 컨센서스) 와 monygeek(역발상/tail-risk 관점)을 **자산군별 consensus vs dissent** 로 대비. monygeek 은 dissent/tail-risk 쪽 가중.

### ★ monygeek 오염 방지 규칙 (D5 확정)
monygeek 을 자산군 consensus vote 에 **동일 가중으로 넣지 않는다**. 별도 레이어로 분리:
```text
broker consensus : naver_research 중심 → consensus_stance / vote_distribution 산정의 본류
monygeek         : dissent / tail-risk / alternative view 전용 레이어
final consensus_stance 산정 시 monygeek = 보조 입력 (vote 본류 제외)
```
- 09 page 의 `## 1. 컨센서스` = broker 만으로 stance/vote 산정. monygeek 은 `## 2. 이견` / `## 5. monygeek 관점` 에만 출력.
- 효과: 증권사 다수 컨센서스가 monygeek 단일 contrarian view 로 뒤집히는 오염 차단.

---

## 7. 09_Research_Synthesis page 예시

> ⚠️ **네이밍 결정 필요 D2**: 사용자 표현 "05_Research_Synthesis" 의 `05` 는 이미 `05_Regime_Canonical` 이 점유. 05 로 넣으면 06/07/08 전부 renumber(canonical writer·다수 참조 마이그레이션 리스크 큼). **권장 = `09_Research_Synthesis`**(다음 빈 번호) 로 신설, 개념은 동일. 사용자 확정 필요.

페이지 예시 (`wiki/09_Research_Synthesis/2026-05_국내채권.md`):
```markdown
---
period: 2026-05
asset_class: 국내채권
source_type: research_synthesis
generated_by: research_consensus
consensus_stance: neutral
vote_distribution: {bullish: 1, neutral: 2, bearish: 1}
themes: [금리_채권, 통화정책]
horizons: [short, medium]
---

# 2026-05 국내채권 — 리서치 종합

## 1. 컨센서스 (stance: neutral)
- 금리 상단 인식 + 수급 우호 → 듀레이션 회복 기대 (broker: 3사 강세, 2사 중립)

## 2. 이견 (dissent)
- 강세론: 통화정책 인하 기대 상단 부각 (broker A, monygeek 일부)
- 약세론: 글로벌 금리 상승 → 외인 수급 악화 (broker B)

## 3. 리스크
- WGBI 외인 이탈 / 글로벌 금리 급등

## 4. 근거 claim
- [claim:research:ab12cd34ef] 금리 안정 기대 (단기, 강세, broker A)
- [claim:research:...] ...

## 5. monygeek 관점
- (역발상/tail-risk view)
```

---

## 8. 03_Assets 와의 연결 방식

- `build_asset_page` 의 §4 "관련 이벤트" 소스를 스왑:
  - 현재: `_related_events_for_asset(asset, period)` → `01_Events/{period}_*.md` glob+keyword score
  - 전환: `_related_research_for_asset(asset, period)` → `09_Research_Synthesis/{period}_{asset}.md` 직접 매핑(자산군 키 일치라 score 불필요) 또는 frontmatter `asset_class` 필터.
- §1 개요/§6 메모는 템플릿 유지하되 §2 핵심변수·§3 리스크를 research synthesis 의 consensus/risk 에서 주입.
- `build_fund_page` 는 `_related_events_for_fund`(자산 union) → `_related_research_for_fund` 로 동일 패턴 스왑.
- **staging 기간**: 03_Assets 는 기존 동작 유지, 09 만 생성·검수. 품질 확인 후 플래그로 03 소스 전환.

### ★ D4 — 09→03 전환 품질 게이트 (확정)
```text
대상:
- 최근 1개월 기준 주요 자산군 전수 또는 최소 8개 자산군
- 각 자산군별 핵심 claim 3~5개 spotcheck

통과 기준:
1. asset_class routing 정확도 ≥ 90%
2. stance 방향성 agree율 ≥ 80%
3. 핵심 논거 누락/왜곡 ≤ 자산군당 1건
4. monygeek 관점이 consensus 를 오염시키지 않고 dissent/tail-risk 로 분리
5. 03_Assets 기존(news 기반) 산출 대비 설명력 동등 이상

통과 후:
- WIKI_SOURCE=research 플래그로 03_Assets 재배선
- 기존 news 기반 03_Assets 는 롤백 가능하도록 유지
```

---

## 9. news 를 운영 경로에서 분리하는 방식

- **유지**: daily_update Step 1(`_step_collect_news`) fetch — `data/news/{month}.json` 계속 생성(스터디/비교용).
- **분리**: wiki/코멘트 핵심 경로에서 news 제외.
  - `wiki/draft_pages.py::_load_month_articles` → research 소스로 전환(또는 base 01_Events 생성을 research 기반으로 교체/보류).
  - `article_stream.DEFAULT_SOURCES` → GraphRAG/vectorDB 가 news 포함 여부 결정. news 끊으면 단일소스화 → **GraphRAG/vectorDB 영향 검토 필요**(결정 D3).
  - debate evidence 선별은 이미 70% research/30% news → research_only 비중을 100% 로 올리는 옵션 사용.
- **플래그화**: 한 번에 끊지 말고 `WIKI_SOURCE=research|news|both` 류 env 로 단계 전환(롤백 가능).

> **D3 확정**: wiki/코멘트 콘텐츠 경로만 research 전환, GraphRAG/vectorDB 는 일단 both 유지.

### ★ news 분리 범위 명확화 (확정)
```text
news:
- fetch                       : 유지 (data/news/{month}.json 계속 생성)
- GraphRAG / vectorDB         : both 유지 (엔티티/검색 폭 확보)
- wiki/코멘트 narrative source : research_only (기본 미사용)
- 이벤트 날짜 확인/보조 검증   : 별도 플래그에서만 허용 (기본 OFF)
```
즉 fetch·그래프·벡터는 살리되, **월간 wiki/코멘트 본문 생성 narrative 소스에서는 news 기본 제외**. 날짜 cross-check 등 보조 용도는 opt-in 플래그로만.

---

## 10. 기존 자산 재사용 맵 (조사 결과 요약)

| 트랙 | 재사용 | 신규 |
|------|--------|------|
| **claim** (claim_extractor) | schema core·8-class·validation·ID 결정성·저장·Haiku·`--target-suffix` 격리·`horizon`/`direction`/`confidence`/`affected_assets`/`causal_chain` | research prompt, monygeek adapter, stance/broker/view/risk/evidence_text 필드, research 저장 분리 |
| **asset page** (enrichment_builder) | `_scan_text_for_asset` score, `_wiki_link`, period-key 네이밍, route_by_region, claim_primary_asset, build_enrichment_plan 루프 | `_related_research_for_asset/_fund`, 09 page builder, research page frontmatter 계약, paths.py 09 상수 |
| **synthesis** (debate_engine) | 4-persona(**monygeek 포함**), 2-step Opus(narrative+JSON consensus/dissent/tail_risk), evidence citation, 토큰/streaming, evidence 70/30 research 가중, asset_movement_commentary union(자산군 dedupe), draft/06_Debate_Memory 저장 | 자산군별 claim filter, consensus vote 집계(bullish/neutral/bearish votes/4), per-asset dissent JSON, horizon 묶음, research_consensus entrypoint |

대략 claim 70% / asset 60% / synthesis 65% 재사용.

---

## 11. 단계별 구현 플랜

| Phase | 내용 | 산출/검증 | 비용 |
|-------|------|-----------|------|
| **P0** | research claim schema 확정(신규 필드) + validator + 테스트 | schema doc + soft validator + unit test | 0 |
| **P1** | monygeek adapter + 입력 정규화 (naver_research 는 기존 adapted 재사용) | article-like 정규화 출력, 단위테스트 | 0 |
| **P2** | research_claim prompt + `--target-suffix=research` 추출 (dry, 소량) | `{month}.research.json` 소량 샘플, 운영본 md5 불변 확인 | ~$0.1 (별 GO) |
| **P3** | asset×theme×horizon aggregation 모듈 | agg 산출 + 분포 리포트 | 0 |
| **P4** | research_consensus (debate 변형) — 자산군별 consensus/dissent | 09_Research_Synthesis staging page, monygeek 병합 | paid (별 GO) |
| **P5** | 03_Assets 재배선(_related_research_*) — 플래그 staging | 09→03 소비, 품질 비교(vs 기존 news 기반) | 0 |
| **P6** | news 운영 경로 분리 플래그(`WIKI_SOURCE`) + GraphRAG/vectorDB 정책 | 롤백 가능 전환, news fetch 유지 | 0 |

각 paid 단계(P2/P4)는 **별도 GO 필수**(운영 overwrite 금지, target-suffix 격리 유지).

### ★ P2 / P4 실행 전 GO 조건 (확정)
```text
P2 GO 조건 (research claim 추출):
- schema/validator 테스트 통과
- sample input 5~10건 dry 확인
- 기존 data/claims/{month}.json md5 불변 확인 (target-suffix 격리)

P4 GO 조건 (research consensus):
- aggregation 분포 리포트 확인
- 자산군별 claim 수 부족/과다 경고 확인
- 09 page 샘플 포맷 승인
```

---

## 12. 결정 확정 (2026-06-15)

- **D1 stance**: ✅ 신규 `stance` enum(bullish/neutral/bearish/mixed) 추가. `direction` 기존 호환 유지. **stance=전망 어조 / direction=가격영향 방향 정의 분리**(§4, validator 일치강제 X).
- **D2 페이지 번호**: ✅ **`09_Research_Synthesis`** 확정. 05 renumber 안 함.
- **D3 news**: ✅ wiki/코멘트 narrative 만 research 전환. fetch·GraphRAG·vectorDB 는 both 유지(§9).
- **D4 전환 게이트**: ✅ 09 staging spotcheck — routing ≥90% / stance agree ≥80% / 논거왜곡 ≤자산군당 1 / monygeek 분리 / 설명력 동등↑ (§8).
- **D5 monygeek**: ✅ consensus 본류 아님 — dissent/tail-risk/contrarian 레이어, vote 보조 입력(§6).

---

> 다음: **P0(schema)부터** 착수(승인됨). P0/P1/P3/P5/P6 무비용 코드, **P2/P4 만 paid(별 GO, §11 GO 조건 충족 후)**.
