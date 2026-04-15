# Review Packet v8 — 3-Tier 탭 구조 + 펀드 코멘트 자동생성

> 작성일: 2026-04-13
> 범위: 탭 구조 개편, 시장/펀드 코멘트 분리, fund_comment_service 신규, 거래내역 로더, ref 개선, legacy fallback 제거
> 이전: v7.1 (시장 debate 실행 검증 완료)

---

## Part I. 이번 세션 변경 전체 요약

### 탭 구조 개편

**Before:**
```
Overview | 편입종목 | 성과분석 | 매크로 | 운용보고 | 운용보고(전체) | Admin
```

**After:**
```
Overview | 편입종목 | 성과분석 | 매크로 | 운용보고(펀드) | 운용보고(매크로) | Admin | Admin(운용보고_매크로) | Admin(운용보고_펀드)
```

- Admin: 펀드 현황/AUM만 (debate workflow 제거)
- Admin(운용보고_매크로): 시장 전체 debate 실행/검수/승인
- Admin(운용보고_펀드): 펀드별 코멘트 생성/검수/승인

### 시장 debate와 펀드 코멘트의 분리

| 항목 | 시장 debate | 펀드 코멘트 |
|------|-----------|-----------|
| 서비스 모듈 | `debate_service.py` | `fund_comment_service.py` (신규) |
| UI 탭 | `admin_macro.py` | `admin_fund.py` |
| 저장 코드 | `_market` | 실제 펀드코드 (07G02 등) |
| 저장 경로 | `report_output/{period}/_market.draft.json` | `report_output/{period}/{fund}.draft.json` |
| LLM | Opus (debate 4인 + 종합) | Opus (comment_engine) |
| 입력 | 뉴스/GraphRAG/지표 | 시장 debate 결과 + PA/보유/거래 |
| 비용 | ~$0.34/회 | ~$0.50/펀드 |

### 핵심 원칙

- 시장 debate 산출물과 펀드 코멘트 산출물은 **별개의 산출물**
- 펀드 코멘트 생성은 시장 debate 결과를 **입력으로 받는** 별도 workflow
- `debate_service.py`에 펀드 코멘트 로직을 넣지 않음

---

## Part II. 신규 파일

### 1. `market_research/report/fund_comment_service.py` (287줄)

Streamlit 의존성 없는 펀드 코멘트 생성 서비스.

**함수 3개:**

| 함수 | 역할 |
|------|------|
| `_market_comment_to_inputs(market_payload)` | 시장 final/edited draft → LLM 친화적 inputs dict. `market_view`(본문), `outlook`(합의 bullet), `risk`(쟁점+테일리스크) |
| `_summarize_fund_data_for_prompt(pa, holdings, trades, bm)` | 원자료를 프롬프트용 요약본으로 축약. PA 상위/하위 3개, 거래 순매수/매도 상위 3개 |
| `generate_fund_comment_and_save(mode, year, period_num, fund_code, period_key, market_payload)` | 전체 오케스트레이션: 데이터 로딩 → inputs 변환 → Opus 호출 → fund draft 저장 |

**데이터 로딩 흐름:**
```
1. 영업일 범위 (comment_engine.load_business_days)
2. BM 수익률 (comment_engine._load_bm_returns_for_range)
3. PA 기여도 + 보유비중 (data_loader.compute_single_port_pa)
4. 거래내역 순매수/매도 (data_loader.load_fund_net_trades)  ← 신규
5. 가격 패턴 (comment_engine.load_bm_price_patterns)
6. 시장 payload → inputs 변환
7. 거래 요약 → inputs['additional']에 주입
8. comment_engine.generate_report_from_inputs(model='claude-opus-4-6')
9. report_store.save_draft()
```

**시장 코멘트 로딩 정책:**
1. `market final` (approved) 있으면 사용
2. 없으면 `market edited draft` fallback
3. 둘 다 없으면 생성 차단 (UI에서 경고)

→ 미검토 raw debate를 바탕으로 펀드 코멘트를 만들지 않음.

### 2. `tabs/admin_macro.py` (261줄)

기존 admin.py의 debate workflow를 분리한 탭. 시장 전체 debate 전용.
- 펀드 드롭다운 없음 (시장 전체 debate이므로)
- 저장 코드: `_market`
- 출처 + 관련 뉴스 분리 표시
- evidence quality 메트릭 + 파일럿 모니터링

### 3. `tabs/admin_fund.py` (158줄)

펀드별 코멘트 생성/검수/승인 탭.
- 기간 + 펀드 선택
- 시장 debate 상태 확인 (final 우선, draft fallback, 없으면 차단)
- "펀드 코멘트 생성" → `fund_comment_service.generate_fund_comment_and_save()` 호출
- draft 수정 → Draft 저장 → 최종 승인 → 승인 해제

---

## Part III. 수정 파일

### 1. `modules/data_loader.py` — 거래내역 로더 추가

**`load_fund_net_trades(fund_code, start_date, end_date) -> dict`**

- `dt.DWPM10520` 조회
- `buy_sell_ds_cd`: M=매수, D=매도
- 35건 수동 분류 override (`_TRADE_ITEM_CLASSIFY`) — 채권ETF 오분류 방지
- fallback: `_classify_6class()` 재사용
- 반환: `{자산군: {'buy': 억원, 'sell': 억원, 'net': 억원}}`

**분류 override 확인 (사용자 수동 검증 완료):**

| 분류 | 종목 수 | 대표 예시 |
|------|---------|----------|
| 국내채권 | 12 | ACE 국고채10년, KODEX 국고채30년, 국고02750 등 |
| 해외채권 | 6 | ACE 미국30년국채(H), iShares HY, VANGUARD EM GOV BND |
| 해외주식 | 7 | ACE 미국나스닥100, VANGUARD FTSE DEV/EM, SPDR Growth |
| 국내주식 | 2 | ACE 200, ACE 200TR |
| 대체투자 | 3 | ACE KRX금현물, ISHARES GOLD, VANECK GOLD MINERS |
| FX | 4 | 미국달러 F 202601~04 |
| 유동성 | 1 | USD DEPOSIT |

**검증 결과 (07G02, 2026년 3월):**
```
국내주식:  매수  55.0억 | 매도   0.0억 | 순매수  +55.0억
국내채권:  매수 234.4억 | 매도  73.1억 | 순매수 +161.4억
해외주식:  매수   0.0억 | 매도  82.7억 | 순매수  -82.7억
해외채권:  매수   0.0억 | 매도 130.6억 | 순매수 -130.6억
유동성:   매수  72.8억 | 매도   0.0억 | 순매수  +72.8억
```

→ "국내채권 순매수 +161억, 해외채권 순매도 -131억" — 미국채→국내채 전환 전략과 일치.

### 2. `tabs/admin.py` (92줄)

debate workflow 전체 제거. 펀드 현황/AUM만 남김.

### 3. `tabs/report.py` (567줄)

- `_render_comment_with_sources()`: 출처(ref 포함) + 관련 뉴스 분리 표시
- `_load_comment_for_admin()`: legacy fallback 제거
- `render_macro()`: `related_news` 필드 표시 추가

### 4. `market_research/report/debate_service.py` (475줄)

- ref_mismatch validator 비활성화 (false positive만 생성, 실질 오류 0)
- `renumber_refs()`: ref를 등장순 1번부터 재부여 + 미사용 기사를 `related_news`로 분리
- `_INTERNAL_PATTERNS`에서 `[ref:\d+]` 제거 (ref 태그 유지)
- "기조를 유지" banned pattern false positive 수정
- 문장 분리 패턴 개선 (`[ref:N].` 뒤에서도 분리)

### 5. `market_research/report/debate_engine.py`

- Opus 프롬프트: "기사에서 직접 확인 가능한 사실에 반드시 ref" 지시. 최소 갯수 제약 제거.

### 6. `market_research/report/report_store.py` (215줄)

- legacy `debate_published` fallback 완전 제거
- `list_periods()`: report_output만 참조

### 7. `prototype.py` (397줄)

- 탭 이름 변경: 운용보고→운용보고(펀드), 운용보고(전체)→운용보고(매크로)
- admin 탭 3개: Admin, Admin(운용보고_매크로), Admin(운용보고_펀드)

---

## Part IV. 프롬프트에 주입되는 거래내역

거래 요약은 `inputs['additional']`로 주입되어 `build_report_prompt()`의 `[추가 강조]` 섹션에 포함됨.

형식:
```
[기간 중 거래 요약]
- 국내채권 순매수 +161.4억
- 국내주식 순매수 +55.0억
- 해외주식 순매도 -82.7억
- 해외채권 순매도 -130.6억
```

full raw table이 아닌 **요약본**만 주입. 유동성/모펀드는 제외.

---

## Part V. 저장 구조

```
market_research/data/report_output/
├── 2026-04/
│   ├── _market.draft.json      ← 시장 debate (debate_service)
│   ├── _market.final.json      ← 시장 debate 승인본
│   ├── 08P22.draft.json        ← 펀드 코멘트 (fund_comment_service)
│   └── 07G02.draft.json        ← 펀드 코멘트
└── _evidence_quality.jsonl     ← 시장 debate evidence 추적
```

- `_market.*`: 시장 debate 전용 (debate_service 생성)
- `{fund_code}.*`: 펀드 코멘트 전용 (fund_comment_service 생성)
- 파일명으로 자연 분리 (같은 fund_code가 시장과 펀드 양쪽에 생성되지 않음)
- `report_type` 필드로 추가 구분 (`'fund'` vs 미설정/`'market'`)

---

## Part VI. 검증 상태

### 완료된 검증

| 항목 | 결과 |
|------|------|
| `load_fund_net_trades` DB 조회 | PASS (07G02 3월, 5개 자산군 정상) |
| 35건 종목 분류 override | 사용자 수동 확인 완료 |
| `fund_comment_service` import chain | PASS |
| `ast.parse()` 전 파일 | PASS |
| Streamlit 기동 (HTTP 200) | PASS |
| 시장 debate workflow (admin_macro) | 이전 세션에서 검증 완료 |

### 미완료 (LLM 비용 발생)

| 항목 | 비용 | 방법 |
|------|------|------|
| Admin(운용보고_펀드)에서 실제 펀드 코멘트 생성 | ~$0.50 | 08P22 등 1건 실행 |
| 코멘트에 거래 기반 서술 포함 여부 | — | 생성 결과 수동 확인 |
| 시장 payload → 펀드 코멘트 자연스러운 결합 | — | 생성 결과 수동 확인 |
| comment_engine.build_report_prompt()에 trades 섹션 정상 주입 | — | 생성 시 확인 |

---

## Part VII. Ref 개선 (v7.1 이후)

| 변경 | 내용 |
|------|------|
| ref_mismatch validator 비활성화 | false positive만 생성 (14/14 정확 매핑). ref_invalid + tense_mismatch만 유지 |
| ref 재부여 (renumber_refs) | Opus가 임의 번호로 달아도 등장순 1번부터 재정렬. 미사용 기사는 `related_news`로 분리 |
| Opus 프롬프트 수정 | "직접 확인 가능한 사실에 ref 부착" 지시. 최소 갯수 제약 삭제 |
| "기조를 유지" false positive | `(비중\|편입\|운용\|투자)\s*기조를\s*유지`로 범위 축소 |
| 문장 분리 패턴 | `(?<=[.다\]])\.\s+` 추가 — `다[ref:N]. ` 패턴에서도 분리 |
| ref 태그 표시 | admin/client 모두 `[ref:N]` 유지 (제거 로직 삭제) |
| legacy fallback | 완전 제거 — report_output에 파일 없으면 빈칸 |

---

## Part VIII. 남은 작업

| # | 항목 | 우선순위 |
|---|------|---------|
| 1 | **펀드 코멘트 실행 검증** (1건) | P0 — 이번 세션 |
| 2 | WGBI 등 토픽 다양성 보장 (salience/debate 입력 개선) | P1 |
| 3 | comment_engine에 trades 전용 프롬프트 섹션 추가 (현재는 `[추가 강조]`에 주입) | P1 |
| 4 | Reuters Google News URL → 원본 URL 리졸브 | P2 |
| 5 | 시장/펀드 코멘트 client 탭 분리 표시 | P1 |

---

## Part IX. 파일 목록

### 신규 (3개)

| 파일 | 줄수 | 역할 |
|------|------|------|
| `market_research/report/fund_comment_service.py` | 287 | 펀드 코멘트 생성 서비스 |
| `tabs/admin_macro.py` | 261 | 시장 debate admin 탭 |
| `tabs/admin_fund.py` | 158 | 펀드 코멘트 admin 탭 |

### 수정 (6개)

| 파일 | 줄수 | 변경 |
|------|------|------|
| `modules/data_loader.py` | 3,432 | `load_fund_net_trades` + 35건 분류 override |
| `market_research/report/debate_service.py` | 475 | ref 개선, renumber_refs, validator 비활성화 |
| `market_research/report/report_store.py` | 215 | legacy fallback 제거 |
| `tabs/admin.py` | 92 | debate workflow 제거 (펀드 현황만) |
| `tabs/report.py` | 567 | 출처/관련뉴스 분리, legacy 제거 |
| `prototype.py` | 397 | 탭 구조 개편 (9개 탭) |

---

*2026-04-13 | 3-Tier 탭 구조 + 시장/펀드 코멘트 분리 + fund_comment_service + 거래내역 로더 + ref 개선*
