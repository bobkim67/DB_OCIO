# HANDOFF.md

## Snapshot

- Date: 2026-04-10
- Project: `DB_OCIO_Webview`
- Main focus: debate hallucination 방어체계 + 매크로 브리핑 UI

## Completed (04-10 세션)

### debate 파이프라인 개선
- 산출물 목적 재정의: 펀드 운용보고 → **매크로 시장 브리핑**
- Opus 프롬프트 전면 재작성 (system_msg, 문단 구조, 금지 규칙)
- 분기 통합 debate (`run_quarterly_debate`) 구현
- daily_update에 블로그 수집(Step 1.5) + 인사이트 빌드(Step 1.6) + NewsAPI 통합

### hallucination 방어체계
- **ref 매핑 강화**: 프롬프트 뉴스 목록에 `[ref:N]` 식별자 직접 표기
- **시제 validator**: evidence "유력" → 코멘트 "확정형" 탐지 (rule-based)
- **ref 교차검증**: 문장 토픽 ↔ ref 기사 토픽 키워드 매칭
- **ref 유효성 검증**: 존재하지 않는 ref 번호 탐지
- **당일 기사 슬롯**: TIER1/TIER2 당일 기사 최대 2건 우선 배정
- **structured warnings**: `list[dict]` (type/ref_no/message/severity)

### client/admin 분리
- **client**: inline ref 완전 제거, 하단 "참고 뉴스" 목록만 표시, 관련 지표 차트 (3열)
- **admin**: debate 생성/수정/저장 UI, 출처에 ⚠️ 경고 표시, 내부 지표 가이드
- 후처리: 펀드 액션 패턴 금지 (시장 설명 허용), 권고형 문장 탐지

### 외부 리뷰 시스템
- OpenAI reviewer hooks (`python/tools/`) 빌드 + DB_OCIO_Webview에 hooks 등록
- `.env` 경로: `python/tools/.env`
- review_packet_v5 작성

### 기타
- 미커밋 정리 + 2커밋 완료 (코드 + 데이터)
- evidence [ref:N] 실전 검증: 9건 생성, 15건 매핑 성공
- 문서 현행화: AGENTS.md, docs/market_research.md, CLAUDE.md 경로 수정
- collect skill 현행화 (daily_update 단일 명령)

## Open Issues

1. **Opus hallucination 잔여**: ref 오매핑/시제 변조 **완화**됨, 완전 해결 아님
2. **매매이력 분석 문단**: DWPM10520 거래내역 + 가격 + 뉴스 → "운용 현황" 자동 생성
3. **debate 결과 자산군별 분리**: customer_comment → 펀드별 매칭
4. **GraphRAG 누적 폭발**: rolling window 리서치 필요
5. **2025년 데이터 19,000건**: V2 분류 보류 (비용 $190, 우선순위 낮음)

## 집에서 작업 가능한 것

- 뉴스/블로그 수집 (`daily_update.py`) — DB 불필요
- debate 실행 + 코멘트 생성 — Anthropic API만 필요
- Streamlit 운용보고(전체) 탭 — 로컬 JSON 기반
- 후처리/validator 개선 — 코드 작업

## 집에서 불가능한 것

- SCIP/dt DB 접속 (192.168.195.55 내부망)
- Overview/편입종목/성과분석/매크로 탭 (DB 필요)
- VP/BM/PA 관련 작업

## GitHub

- 뉴스/블로그/매크로/GraphRAG/debate 데이터 push 완료
- vectorDB (661MB) + enriched_digests + news_content_pool은 .gitignore 제외
- 집에서 clone 후 vectorDB만 리빌드하면 됨:
  ```bash
  python -m market_research.analyze.news_vectordb 2026-04
  ```

## Next 3 Actions

1. debate 재실행하여 ref [ref:N] 식별자 효과 검증
2. review_packet_v5 외부 리뷰 전달
3. 매매이력 분석 문단 구현 (DWPM10520)
