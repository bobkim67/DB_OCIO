# === MP_monitoring 패키지 ===
# R Shiny 기반 MP(Model Portfolio) 모니터링 시스템
#
# 구조:
#   00_data/               - 원시 데이터 (SCIP, BOS, ECOS 등)
#   00_data_updating/      - 데이터 업데이트 스크립트 & 캐시
#   01_DB_update/          - DB 동기화 (MariaDB)
#   02_preprocessing/      - 데이터 전처리
#     performance.R        - AP/VP/MP/BM 통합 성과 계산
#     performance_BM.R     - BM 성과 계산
#     performance_MP.R     - MP 성과 계산
#     position.R           - AP/VP/MP 포지션 비중 계산
#   03_MP_monitor/         - Shiny 대시보드 (port 7600)
#   04_Issue_notes/        - BM 계산 이슈 노트
#   05_Performance_Attribution/ - Brinson PA
#   VP/                    - Virtual Portfolio 관리
#
# 핵심 개념:
#   AP (Actual Portfolio)  - 실제 운용 포트폴리오 (dt.DWPM10530)
#   VP (Virtual Portfolio) - 목표 포트폴리오 (sol_VP_rebalancing_inform)
#   MP (Model Portfolio)   - 장기 전략 포트폴리오 (sol_MP_released_inform)
#   BM (Benchmark)         - 성과 비교 기준 (KIS/Bloomberg 지수)
#
# Gap 분석:
#   AP vs VP Gap → 복제오차 분석, 리밸런싱 필요 여부
#   VP vs MP Gap → 전술적 조정 효과 측정
#
# 데이터 소스 (DB):
#   SCIP.back_datapoint          - 지수/자산 가격
#   dt.DWPM10510                 - 펀드 수정기준가
#   dt.DWPM10530                 - 펀드 보유종목/비중
#   dt.MA000410                  - PA 원천 데이터
#   solution.sol_VP_rebalancing_inform - VP 리밸런싱 정보
#   solution.sol_MP_released_inform    - MP 발표 정보
#   solution.universe_non_derivative   - 자산 유니버스 분류
#
# 수익률 계산 (R → Python 변환 핵심 공식):
#   일별수익률 = price_t / price_t-1 - 1
#   FX조정    = (1 + ret) * (1 + usdkrw_ret * (1-hedge_ratio) * is_foreign) - 1
#   FX분리    = (1 + ret_total) / (1 + ret_fx) - 1
#   Weight_drift(T) = (1 + cum_ret) * init_weight / sum(...)
#   Brinson: Alloc = (w_AP - w_BM) * r_BM
#            Select = w_BM * (r_AP - r_BM)
#            Cross  = (w_AP - w_BM) * (r_AP - r_BM)
