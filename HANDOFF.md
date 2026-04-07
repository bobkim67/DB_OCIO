# HANDOFF.md

## Snapshot

- Date: 2026-04-06
- Project: `DB_OCIO_Webview`
- Main focus: Report Interview CLI + 코멘트 엔진 개선

## Completed (this session)

### 버그 수정
- 한글 mojibake (naver_blog.py + collect_news.bat)
- Brinson 07G04 `int has no len()` 에러 (data_loader.py + tabs/report.py)
- `bm_code` dead parameter 제거 (compute_brinson_attribution)

### 코멘트 엔진 개선
- PMI 매크로 지표 직접 주입 (report_service.py, 7개 규칙)
- ISM PMI 제외 (FRED 미제공), MANEMP → MFG_EMPLOYMENT 정정
- holdings 분류 통합 (universe DB 우선 + _classify_pa_item_v2 fallback)
- 프롬프트 문체 개선 (서술형, 대비구조, 인과서술)
- FUND_CONFIGS에 philosophy + position_constraints 추가 (07G04/2JM23/4JM12)
- 분기 보고서 모드 (`quarter=` 파라미터)

### Report Interview CLI (신규)
- `report_interview.py` — 5단계 인터뷰 CLI
- `--detail` (07G04 상세 양식) / `--debate` (debate 기본답변) / `--answers` (비대화형)
- 객관식+주관식 하이브리드, 수정 루프
- `run_interview.bat` 더블클릭 실행

### 데이터 확충
- Finnhub 뉴스 백필 2025-04~2026-02 (8,106건, 총 12,074건)
- enriched digest 2026-01/02 빌드
- 배치에 매크로 수집 단계 추가
- narratives.yaml 생성 (2026-01~03)

### insight-engine 브랜치
- DIAGNOSIS_RULES 13키 asset_impact 동적 계산 (TOPIC_ASSET_SENSITIVITY × severity)

## Open Issues

1. **매매이력 분석 문단**: DWPM10520 거래내역 + 종목별 가격 + 뉴스 → "운용 현황" 자동 생성
2. **debate 결과 자산군별 분리**: customer_comment 통째 → Q별 매칭
3. **뉴스/블로그 하이라이트 정제**: key_claims 조각 → 토픽별 요약
4. **미커밋**: main 20+파일, insight-engine 미커밋
5. **GraphRAG 누적 폭발**: 블랙박스 모델 리서치 필요
6. **종목별 비중 합계 ≠ 100%**: R T-1 벤치마킹

## Next 3 Actions

1. 매매이력 분석 문단 구현 (DWPM10520 + 가격 + 뉴스 종합)
2. debate 자산군별 분리 → 인터뷰 Q별 정밀 매칭
3. 미커밋 정리 + 커밋
