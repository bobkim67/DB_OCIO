# debug/ — Python/R 대조 검증 스크립트

CSV/xlsx 출력은 `.gitignore` 처리 (재생성 가능).

## R 소스 복사본 (trace 인라인 삽입됨)

| 파일 | 원본 | 설명 |
|------|------|------|
| `PA_module_funcs_only.R` | `General_Backtest/04_사후분석/func_펀드_PA_모듈_adj_GENERAL_final.R` | PA_from_MOS STEP A~H 추적 trace (ACE 국고채10년 03-06 + ACE 종합채권 03-16 필터) |
| `PA_combine_funcs_only.R` | `General_Backtest/04_사후분석/func_PA_결합및요약용_final.R` | Portfolio_analysis + normalized_performance trace |

## R Runner (headless)

| 파일 | 용도 |
|------|------|
| `debug_pa_from_mos_08K88.R` | 08K88 PA_from_MOS 실행 (ACE 국고채10년 2026-03-06 레퍼런스) |
| `debug_pa_from_mos_08N81.R` | 08N81 PA_from_MOS + Portfolio_analysis + single_port_historical_weight 실행 (ACE 종합채권 2026-03-16 BA정산 레퍼런스) |
| `debug_ace_step_by_step.R` | 기초정보요약 Step1(reframe) → Step2(lag) → Step3(fill down) 개별 추적 |

실행: `"/c/Program Files/R/R-4.5.2/bin/Rscript.exe" debug/debug_pa_from_mos_08N81.R`

## Python Verify (Py vs R 대조)

| 파일 | 용도 |
|------|------|
| `debug_08n81_ace_divergence.py` | 08N81 ACE 종합채권 일별 Py vs R Excel 대조 (divergence 지점 찾기) |
| `debug_08n81_compare.py` | 08N81 sec/asset 전체 R Excel 대조 |
| `debug_ace_py_verify.py` | 08K88 ACE 국고채10년 sec_daily 일별 pull |
| `debug_bmless_output.py` | BM 미설정 펀드(08N81) 자산군/종목별 수익률 출력 |
| `debug_brinson_v2_multifund.py` | 다중 펀드 Brinson v2 회귀 (08K88, 07G04, 08N81, 07G02, 2JM23) |
| `debug_brinson_v2_verify.py` | 단일 펀드 Brinson v2 전체 결과 dump |

## 진단 스크립트 (구조/분류 확인)

| 파일 | 용도 |
|------|------|
| `debug_07g04_structure.py` | 07G04 FoF 구조 (DWPI10011 + DWPM10530 보유종목 분포) |
| `debug_07g04_duplication.py` | 07G02/07G03 양측 보유 중복 sec_id 확인 |
| `debug_07g04_v1_vs_v2.py` | compute_brinson_attribution v1 vs v2 |
| `debug_ba_jungsan_scan.py` | 08K88/07G04/08N81 ETF 환매 후 잔존 보유 종목 스캔 |

## 레퍼런스 Excel 경로 (버전 관리 외부)

- `C:/Users/user/Downloads/PA_compare_08K88_vs_08K88_BM(2026-01-01 ~ 2026-04-16)_방법4_FXsplit=TRUE (2).xlsx`
- `C:/Users/user/Downloads/PA_compare_07G04_vs_07G04_BM(2026-01-01 ~ 2026-04-16)_방법3_FXsplit=TRUE.xlsx`
- `C:/Users/user/Downloads/PA_single_한국투자OCIO알아서액티브일반사모투자신탁_(2026-01-08 ~ 2026-04-20)_방법3_FXsplit=TRUE.xlsx` (08N81)
