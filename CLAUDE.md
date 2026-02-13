# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

DB형 퇴직연금 OCIO(Outsourced CIO) 운용 현황 웹 대시보드.
Streamlit 기반 프로토타입으로, R Shiny 기존 시스템(General_Backtest/)을 Python으로 재구현 중.
21개 펀드 (총 AUM ~1.4조원)의 성과 모니터링, 자산배분, Brinson PA, 매크로 지표 분석 제공.

## Running the App

```bash
# 프로토타입 실행
streamlit run prototype.py

# 구문 검증만 (UI 실행 없이)
python -c "import ast; ast.parse(open('prototype.py', encoding='utf-8').read())"
```

## Architecture

### 프로젝트 구조

```
DB_OCIO_Webview/
├── prototype.py           ← 메인 Streamlit 앱 (v3, ~1800줄, 7개 탭)
├── config/
│   ├── funds.py           ← 21개 펀드 메타정보, 8개 그룹, DB 설정
│   └── users.yaml         ← 사용자 인증 정보
├── modules/
│   ├── auth.py            ← 로그인 인증 모듈
│   └── data_loader.py     ← 15개 DB 로딩 함수 (MariaDB)
├── tabs/                  ← (예정) 탭별 모듈 분리
├── docs/
│   ├── 01-plan/features/  ← Plan 문서
│   └── 02-design/features/ ← Design 문서
├── devlog/                ← 일별 개발일지
└── General_Backtest/      ← R Shiny 원본 (참조용, 수정 금지)
```

### prototype.py 탭 구조

| Tab Index | 탭명 | 핵심 기능 |
|-----------|------|-----------|
| tabs[0] | Overview | 기준가, 누적수익률, 기간성과, 편입현황 도넛 |
| tabs[1] | 편입종목 & MP Gap | 자산군/종목 토글, 파이+테이블, 비중추이 |
| tabs[2] | 성과분석 | 기간수익률, 롤링 샤프, BM비교, 비중비교 |
| tabs[3] | Brinson PA | 3-Factor Attribution, 워터폴, 기여도 |
| tabs[4] | 매크로 지표 | TR Decomposition, EPS/PE, FX, 금리, 벤치마크 히트맵 |
| tabs[5] | 운용보고 | 시장환경, 성과요약, Brinson, 리스크 종합 |
| tabs[6] | Admin | 전체 펀드 현황 (admin 전용) |

### 데이터 흐름

현재 **mockup 단계**: prototype.py 내부에서 `np.random` 기반 샘플 데이터 생성.
향후 `modules/data_loader.py`의 DB 함수로 교체 예정.

- DB: MariaDB (192.168.195.55) - dt, solution, SCIP, cream 스키마
- 펀드 메타: `config/funds.py::FUND_META` (21개 펀드)
- 시장 지표: `macro_env_data` DataFrame (42행, 16칼럼)

## Dependencies

```
streamlit, pandas, numpy, plotly, openpyxl
```

DB 연동 시 추가: `pymysql` 또는 `mariadb`

## Coding Conventions

- 한국어 변수명/주석 사용 (금융 전문용어는 영문 병기)
- Streamlit 위젯 key는 고유 문자열로 지정 (예: `key='env_krw_toggle'`)
- DataFrame 계층 구조: 대분류/중분류/소분류가 빈 문자열이면 이전 행 값 상속 (forward-fill 패턴)
- 색상 규칙: 음수=#636EFA(파랑), 양수=#EF553B(빨강) — 한국 금융 관행과 반대 (Bloomberg 스타일)
- Source 배경색: Factset=#e8f0fe, Bloomberg=#fef7e0, KIS=#e8f5e9
- 분석 코드이므로 과도한 모듈화 금지. 선형적이고 읽기 쉬운 코드 지향.
- prototype.py 수정 후 반드시 `ast.parse()` 구문 검증 수행

## Key Patterns

### 자산군별 벤치마크 수익률 테이블 (tabs[4])

- 42행 x 7기간(`1D, 1W, 1M, 3M, 6M, 1Y, YTD`) 수치 데이터
- 행 유형별 포맷: `return`(%), `bp`(bp), `vol`(포인트), `econ`(%p)
- `_make_env_formatter(row_types, src_data)` 함수로 유형별 포맷 문자열 생성
- 원화환산 토글: 해외 자산에 +1.5% 가산 (mockup, 실 DB 연동 시 FX 수익률로 교체)

### Forward-fill 계층 처리

```python
_ff = df.copy()
_ff['_대분류'] = _ff['대분류'].replace('', np.nan).ffill()
_ff['_중분류'] = _ff['중분류'].replace('', np.nan).ffill()
```

tabs[4], tabs[5] 모두 이 패턴으로 빈 셀 계층 구조 처리.

### Growth Rate (Indexed Return)

EPS/PE Growth Rate는 선택 기간 시작점에서 0%부터 시작하는 indexed return:
```python
start_idx = max(0, n_md - n_shift - 1)
pe_trimmed = pe_s.iloc[start_idx:]
pe_indexed = (pe_trimmed / pe_trimmed.iloc[0] - 1) * 100
```

## Important Notes

- `General_Backtest/` 디렉토리는 R Shiny 원본 참조용. 수정하지 말 것.
- prototype.py는 단일 파일 프로토타입. 향후 tabs/ 모듈로 분리 예정.
- DB 접속 정보가 코드/config에 하드코딩 (내부망 전용).
- `users.yaml`에 사용자 비밀번호 포함 — 커밋 시 주의.
- Streamlit의 Pandas Styler 지원이 제한적: `.bar()` 등 일부 기능 미지원.

## PDCA Status

- Feature: DB_OCIO_Webview
- Phase: Do (구현 진행중)
- Plan/Design 문서: `docs/` 디렉토리
- 개발일지: `devlog/` 디렉토리 (일별)
