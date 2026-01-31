# CLAUDE.md - AI Assistant Guide for DB_OCIO

Last Updated: 2026-01-31

## Repository Overview

**Repository Name**: DB_OCIO
**Purpose**: Fund & Market Monitoring System - 펀드 자산배분 모니터링 및 분류 시스템
**Primary Function**: MySQL 데이터베이스에서 펀드 보유 종목 데이터를 가져와 자동 분류하고, 인터랙티브 대시보드로 시각화

This document serves as a comprehensive guide for AI assistants working on this codebase. It outlines the repository structure, development workflows, coding conventions, and best practices specific to this project.

---

## Table of Contents

1. [Project Architecture](#project-architecture)
2. [Technology Stack](#technology-stack)
3. [File Structure](#file-structure)
4. [Database Schema](#database-schema)
5. [Core Modules](#core-modules)
6. [Development Workflow](#development-workflow)
7. [Security Considerations](#security-considerations)
8. [Coding Conventions](#coding-conventions)
9. [Testing Guidelines](#testing-guidelines)
10. [Common Tasks](#common-tasks)
11. [Troubleshooting](#troubleshooting)

---

## Project Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────┐
│                   MySQL Database                        │
│  - dt.DWPM10530 (Holdings)                             │
│  - dt.DWPM10510 (Fund Metrics)                         │
│  - dt.DWCI10220 (Business Day Calendar)                │
│  - SCIP.back_datapoint (Market Data)                   │
│  - SCIP.back_dataset (Dataset Metadata)                │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│           Python Data Processing Layer                  │
│  - SQLAlchemy (Database Connection)                     │
│  - Pandas (Data Transformation)                         │
│  - Auto Classification Engine (integrated)              │
│  - US Market Time Lag Adjustment                        │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│              Master Data Management                      │
│  - MASTER_DATA_RAW (code-embedded constant)             │
│  - Auto-classification Rules                            │
│  - Cash/Currency Filtering                              │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│              Applications                                │
│  - dashboard.py: Asset Allocation Dashboard             │
│  - market.py: Valuation Panel (PE, EPS, TR)            │
│  - report.py: Terminal Fund Report                      │
└─────────────────────────────────────────────────────────┘
```

### Key Features

1. **자동 자산 분류**: 종목명과 종목코드 기반으로 자산군 자동 분류
2. **마스터 데이터 관리**: 코드 내장 상수(MASTER_DATA_RAW) 기반 분류 규칙 관리
3. **실시간 대시보드**: Dash 기반 인터랙티브 웹 인터페이스
4. **피봇 분석**: 다차원 자산배분 분석 도구
5. **성과 모니터링**: NAV, 수익률, 자산배분 추이 시각화
6. **미국 시장 시차 반영**: USD 자산 T-1 가격 적용 (KRW 기준가 = USD(T-1) × FX(T))
7. **현금/통화 필터링**: 비중/기여율 왜곡 제거를 위한 필터링
8. **수익률 분해**: 순수 자산 수익률 + 환율 기여 분리 표시
9. **밸류에이션 패널**: PE/EPS 시계열 및 YTD 성과 분해

---

## Technology Stack

### Core Technologies

- **Python**: 3.8+
- **Web Framework**: Dash 2.14.0+ (Plotly-based)
- **Database**: MySQL (via SQLAlchemy + PyMySQL)
- **Data Processing**: Pandas 2.0.0+
- **Visualization**: Plotly 5.18.0+
- **UI Components**: dash-ag-grid 31.0.0+, dash-pivottable 0.0.2+

### Dependencies

```txt
dash>=2.14.0
dash-ag-grid>=31.0.0
dash-pivottable>=0.0.2
pandas>=2.0.0
plotly>=5.18.0
sqlalchemy>=2.0.0
pymysql>=1.1.0
python-dateutil>=2.8.0
```

### Development Tools

- **Version Control**: Git
- **Jupyter Notebooks**: For ad-hoc analysis and exploration

---

## File Structure

```
DB_OCIO/
├── .git/                           # Git repository
├── .gitignore                      # Git ignore patterns
├── README.md                       # Project overview
├── CLAUDE.md                       # This file (AI assistant guide)
│
├── requirements.txt                # Python dependencies
│
├── dashboard.py                    # 메인 대시보드 애플리케이션 (자동 분류 통합)
├── market.py                       # 주식 밸류에이션 패널 (PE, EPS, TR 분석)
├── report.py                       # 펀드 요약 리포트 (터미널 출력용)
├── mysql.ipynb                     # MySQL 연결 및 데이터 탐색 노트북
│
├── source_3_latest_snapshot.pkl    # SCIP source_id=3 스냅샷 데이터
└── factset_data_summary_20260123.xlsx  # FactSet 데이터 요약
```

### File Descriptions

#### Core Application Files

1. **dashboard.py** (~1600 lines)
   - Main application entry point
   - Dash web server setup
   - Database connection management
   - **Auto-classification engine integrated** (기존 auto_classify.py 통합)
   - **Master data management integrated** (기존 create_initial_master.py 통합)
   - **Cash/Currency filtering** for weight/contribution calculation
   - **US market time lag** handling for USD assets
   - Three main tabs:
     - 📊 자산배분 현황: Holdings, time series, performance charts
     - 🔍 피봇 분석: Interactive pivot tables
     - 📋 종목 리스트: Master data management
   - Runs on `http://127.0.0.1:8050`

2. **market.py** (~500 lines)
   - Valuation panel for equity analysis
   - SCIP DB source_id=3 data fetching
   - Features:
     - 12M Fwd P/E time series chart
     - 12M Fwd EPS time series chart
     - YTD performance decomposition (TR = EPS growth + PE growth + Other)
     - Multi-select dropdown for asset comparison
   - Dataset mapping for equity indices (S&P 500, MSCI, Vanguard ETFs, etc.)
   - Runs on `http://127.0.0.1:8050`

3. **report.py** (~770 lines)
   - Terminal-based fund summary report
   - CLI interface with argparse
   - Features:
     - 최근 4영업일 수정기준가(MOD_STPR) 출력
     - 최근 3영업일 일별 수익률 출력
     - USD 자산: 순수 USD 수익률 + FX 기여 분리 표시
   - US market time lag handling:
     - KRW 기준가(T) = USD 가격(T-1) × 환율(T)
     - KRW 수익률 = [USD(T-1) × FX(T)] / [USD(T-2) × FX(T-1)] - 1
   - Usage: `python report.py --fund 06X08`

4. **mysql.ipynb** (Jupyter Notebook)
   - Ad-hoc database queries
   - Data exploration and analysis
   - Two main sections:
     - Dataset/dataseries structure exploration
     - Rate & duration analysis (10-year window)
   - Connects to SCIP database for market data

#### Data Files

5. **source_3_latest_snapshot.pkl**
   - Pickle snapshot of SCIP source_id=3 data
   - Used for offline analysis and caching

6. **factset_data_summary_20260123.xlsx**
   - FactSet data summary export
   - Reference data for validation

---

## Database Schema

### Connection Configuration

```python
# Production Database (dt) - Holdings, Fund Metrics
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"

# Market Data Database (SCIP) - Price, FX, Valuation
CONN_STR_SCIP = "mysql+pymysql://solution:Solution123!@192.168.195.55/SCIP?charset=utf8mb4"
```

**⚠️ SECURITY WARNING**: Database credentials are hardcoded in source files. See [Security Considerations](#security-considerations).

### Key Tables

#### 1. dt.DWPM10530 (Holdings)

Stores daily fund holdings data.

```sql
SELECT
    STD_DT,          -- 기준일 (YYYYMMDD)
    FUND_CD,         -- 펀드 코드
    FUND_NM,         -- 펀드명
    ITEM_CD,         -- 종목 코드
    ITEM_NM,         -- 종목명
    AST_CLSF_CD_NM,  -- 자산분류코드명
    EVL_AMT          -- 평가금액 (원)
FROM dt.DWPM10530
WHERE STD_DT BETWEEN '20241201' AND '20241231'
  AND EVL_AMT > 0
  AND FUND_CD IN ('06X08', '07G02', ...)
```

#### 2. dt.DWPM10510 (Fund Metrics)

Stores fund-level metrics (NAV, performance). Also used for 모펀드 return calculation.

```sql
SELECT
    STD_DT,          -- 기준일
    FUND_CD,         -- 펀드 코드
    MOD_STPR,        -- 수정기준가격
    NAST_AMT         -- 순자산총액
FROM dt.DWPM10510
```

#### 3. dt.DWCI10220 (Business Day Calendar)

Korean business day calendar.

```sql
SELECT std_dt
FROM dt.DWCI10220
WHERE std_dt >= '20241201'
  AND hldy_yn = 'N'           -- Not a holiday
  AND day_ds_cd IN (2,3,4,5,6) -- Mon-Fri
ORDER BY std_dt
```

#### 4. SCIP.back_datapoint (Market Data)

Market data time series (prices, FX, PE, EPS).

```sql
SELECT
    timestamp_observation,
    dataseries_id,    -- 6: Total Return, 24: PE, 31: EPS
    dataset_id,
    data              -- JSON blob with USD/KRW values
FROM SCIP.back_datapoint
WHERE dataseries_id = 6  -- Total Return Index
```

#### 5. SCIP.back_dataset (Dataset Metadata)

Dataset information including ISIN codes.

```sql
SELECT id, name, ISIN
FROM SCIP.back_dataset
WHERE ISIN IN ('US78464A5083', 'KR7332500008', ...)
```

### Fund List

Currently tracked funds (21 total):

```python
FUND_LIST = [
    '06X08','07G02','07G03','07G04','07J20','07J27','07J34','07J41',
    '07J48','07J49','07P70','07W15','08K88','08N33','08N81','08P22','09L94',
    '1JM96','1JM98','2JM23','4JM12'
]
```

---

## Core Modules

### 1. Auto-Classification Engine (in `dashboard.py`)

The auto-classification logic is now integrated into `dashboard.py` (lines 46-92).

#### Function

**`auto_classify_item(item_cd: str, item_nm: str) -> dict | None`**

Classifies an asset based on item code and name.

```python
result = auto_classify_item('KR7332500008', 'ACE 200TR')
# Returns: None (uses master data instead)

result = auto_classify_item('000000', '콜론')
# Returns: {'대분류': '현금', '지역': '국내', '소분류': '현금 등'}

result = auto_classify_item('US78464A5083', 'SPDR S&P 500 VALUE ETF')
# Returns: None (uses master data instead)
```

#### Classification Rules (Priority Order)

1. **콜론 (Call Loan)** - Highest priority
   - Keywords: `'콜론'`, `'증권(콜론)'`
   - Result: 현금 / 국내 / 현금 등

2. **금 (Gold)**
   - Keywords: `'GOLD'`, `'금현물'`, `'KRX금'`
   - Logic: Check if `item_cd` starts with `'KR'` → 국내, else → 글로벌
   - Result: 대체 / 국내 or 글로벌 / 금

3. **달러 선물 (Dollar Futures)**
   - Keywords: `'달러 F'`, `'USD F'`, `'미국달러 F'`
   - Result: 통화 / 미국 / 달러 선물

4. **코스피 선물 (KOSPI Futures)**
   - Keywords: `'코스피'` + `' F '`
   - Result: 주식 / 국내 / 코스피 선물

5. **REPO**
   - Keyword: `'REPO'`
   - Result: 채권 / 국내 / REPO

6. **예금/증거금 (Deposits)**
   - Keywords: `'예금'`, `'증거금'`, `'DEPOSIT'`
   - Logic: Check for USD/외화 → 미국, else → 국내
   - Result: 현금 / 국내 or 미국 / 현금 등

7. **미수금/미지급금 (Receivables/Payables)**
   - Keywords: `'미수'`, `'미지급'`, `'청약금'`, `'원천세'`, `'분배금'`, `'기타자산'`
   - Result: 현금 / 국내 / 현금 등

### 2. Master Data Management (in `dashboard.py`)

Master data is now embedded as a constant `MASTER_DATA_RAW` (lines 162-214).

#### Loading Master Data

```python
from dashboard import load_master_mapping

# Load
master_df = load_master_mapping()
# Returns DataFrame with columns:
# - ITEM_CD: 종목코드
# - ITEM_NM: 종목명
# - 대분류: 주식, 채권, 대체, 현금, 통화, 모펀드, 기타
# - 지역: 국내, 미국, 글로벌, 선진국, 신흥국, 호주, 기타
# - 소분류: 일반, 가치, 성장, 중소형, 장기채, 단기채, etc.
# - 등록일: YYYY-MM-DD
# - 비고: 자동분류, 수동입력, etc.
```

#### Classification Workflow

```python
def classify_with_master(holding_df, master_df):
    """
    1. Merge holdings with master data (left join on ITEM_CD)
    2. For unmapped items, try auto-classification
    3. Auto-classified items are added to master (with duplicate check)
    4. Remaining items marked as '기타' (Other)

    Returns:
        - classified_df: Holdings with classifications
        - unmapped: Items that couldn't be classified
        - master_df: Updated master data (if auto-classifications added)
    """
```

### 3. Cash/Currency Filtering (in `dashboard.py`)

New function `filter_holdings_for_weight()` (lines 98-153) for removing distortion in weight/contribution calculations.

#### Filtering Policy

- **주식/채권/대체/모펀드**: 비중/기여율에 포함
- **현금**: "USD Deposit" 또는 "예금" 포함된 종목만 유지, 나머지 drop
- **통화(달러 선물)**: 비중/기여율에서 제외, 환차손익 계산에만 사용

```python
df_main, df_cash_keep, df_fx_hedge, df_cash_drop = filter_holdings_for_weight(holdings_df)
```

### 4. US Market Time Lag Handling

For USD assets, the system applies T-1 price adjustment to account for US market closing time.

#### Return Calculation Rules

**USD Assets**:
```
KRW 기준가(T) = USD 가격(T-1) × 환율(T)
KRW 수익률 = [USD(T-1) × FX(T)] / [USD(T-2) × FX(T-1)] - 1
         = 순수 USD 수익률(T-2→T-1) + FX 수익률(T-1→T)
```

**KRW Assets**:
```
KRW 수익률(T) = [가격(T) / 가격(T-1)] - 1
```

### 5. Valuation Panel (`market.py`)

Standalone application for equity valuation analysis.

#### Dataset Mapping

```python
DATASET_MAPPING = {
    24:  {"asset1": "주식", "asset2": "미국",   "style": "일반", "display_name": "S&P 500 (미국)"},
    36:  {"asset1": "주식", "asset2": "선진국", "style": "일반", "display_name": "Vanguard DM (선진국)"},
    37:  {"asset1": "주식", "asset2": "신흥국", "style": "일반", "display_name": "Vanguard EM (신흥국)"},
    114: {"asset1": "주식", "asset2": "미국",   "style": "성장", "display_name": "SPDR S&P500 Growth"},
    116: {"asset1": "주식", "asset2": "미국",   "style": "가치", "display_name": "SPDR S&P500 Value"},
    144: {"asset1": "주식", "asset2": "국내",   "style": "일반", "display_name": "MSCI KR (국내)"},
    # FX
    31:  {"asset1": "FX",   "asset2": "환율",   "style": "USDKRW", "display_name": "USD/KRW"},
}
```

#### YTD Decomposition

```python
def build_ytd_decomposition(df_equity):
    """
    TR(YTD)을 EPS growth, PE growth, Other로 분해.
    - eps_g_ytd = EPS 레벨의 YTD growth
    - pe_g_ytd  = PE 레벨의 YTD growth
    - other_ytd = (1+TR)/((1+eps)*(1+pe)) - 1
    """
```

### 6. Terminal Report (`report.py`)

CLI-based fund summary report.

#### Usage

```bash
# With argument
python report.py --fund 06X08

# Interactive mode
python report.py
```

#### Output Sections

- **FX Rate**: 최근 4영업일 USD/KRW 환율
- **Section A**: 수정기준가(MOD_STPR) - 최근 4영업일
- **Section B**: 일별 수익률 - 최근 3영업일
  - USD 자산: Asset(T-2→T-1), FX(T-1→T), Total (KRW) 분리

---

## Development Workflow

### Initial Setup

1. **Clone Repository**
   ```bash
   git clone http://127.0.0.1:60382/git/bobkim67/DB_OCIO
   cd DB_OCIO
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Dashboard**
   ```bash
   python dashboard.py
   ```

4. **Run Valuation Panel (Optional)**
   ```bash
   python market.py
   ```

5. **Run Fund Report (Optional)**
   ```bash
   python report.py --fund 06X08
   ```

### Branch Strategy

- **Main Branch**: Default branch for stable code
- **Development Branches**: `claude/feature-name-{session-id}`
- **Feature Branches**: `feature/description`
- **Hotfix Branches**: `hotfix/description`

### Making Changes

1. **Create Feature Branch**
   ```bash
   git checkout -b claude/feature-name-{session-id}
   ```

2. **Make Changes**
   - Edit Python files
   - Test locally
   - Update documentation if needed

3. **Test Changes**
   ```bash
   # Run dashboard and verify
   python dashboard.py

   # Test auto-classification (now in dashboard.py)
   python -c "from dashboard import auto_classify_item; print(auto_classify_item('test', '콜론'))"
   ```

4. **Commit Changes**
   ```bash
   git add [specific-files]
   git commit -m "feat: description

   https://claude.ai/code/session_[session-id]"
   ```

5. **Push to Remote**
   ```bash
   git push -u origin claude/feature-name-{session-id}
   ```

### Commit Message Format

Use conventional commits:

```
<type>: <subject>

<optional body>

https://claude.ai/code/session_[session-id]
```

**Types**:
- `feat`: New feature (new classification rule, dashboard tab, etc.)
- `fix`: Bug fix (classification error, chart issue, etc.)
- `refactor`: Code refactoring (no functional change)
- `docs`: Documentation only
- `data`: Master data updates
- `config`: Configuration changes
- `perf`: Performance improvements

---

## Security Considerations

### Critical Security Issues

#### 1. Hardcoded Database Credentials

**Current State**: Database credentials are hardcoded in source files.

```python
# dashboard.py, report.py
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"
CONN_STR_SCIP = "mysql+pymysql://solution:Solution123!@192.168.195.55/SCIP?charset=utf8mb4"
```

**Risk Level**: 🔴 HIGH

**Recommended Fix**:

1. Create `.env` file (already in `.gitignore`):
   ```bash
   # .env
   DB_HOST=192.168.195.55
   DB_USER=solution
   DB_PASSWORD=Solution123!
   DB_NAME_DT=dt
   DB_NAME_SCIP=SCIP
   DB_CHARSET=utf8
   ```

2. Update code to use environment variables:
   ```python
   import os
   from dotenv import load_dotenv

   load_dotenv()

   CONN_STR = (
       f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
       f"@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME_DT')}"
       f"?charset={os.getenv('DB_CHARSET')}"
   )
   ```

3. Add `python-dotenv` to `requirements.txt`:
   ```txt
   python-dotenv>=1.0.0
   ```

---

## Coding Conventions

### Python Style

Follow PEP 8 with these specifics:

1. **Naming Conventions**
   - Functions: `snake_case`
   - Classes: `PascalCase`
   - Constants: `UPPER_SNAKE_CASE`
   - Private methods: `_leading_underscore`

2. **Imports**
   ```python
   # Standard library
   import os
   from datetime import datetime, date

   # Third-party
   import pandas as pd
   import numpy as np
   from sqlalchemy import create_engine, text

   # Local (no separate modules now)
   # Auto-classify and master management are in dashboard.py
   ```

3. **String Formatting**
   - Prefer f-strings: `f"Value: {value}"`
   - Use triple quotes for docstrings: `"""Docstring"""`
   - Use single quotes for regular strings: `'string'`

4. **Comments**
   ```python
   # Section headers with separator
   # =========================
   # 1) Data Loading
   # =========================

   # Inline comments for non-obvious logic
   mask = result['ITEM_CD'] == item['ITEM_CD']  # Match by item code
   ```

### DataFrame Operations

1. **Column Selection**
   ```python
   # Good: List of columns
   df[['ITEM_CD', 'ITEM_NM', 'EVL_AMT']]

   # Avoid: Select all then drop
   df.drop(columns=['unwanted_col'])
   ```

2. **Chaining**
   ```python
   # Good: Clear chain with comments
   result = (
       df
       .query('EVL_AMT > 0')           # Filter positive amounts
       .groupby('FUND_CD')['EVL_AMT']  # Group by fund
       .sum()                          # Aggregate
       .reset_index()                  # Flatten index
   )
   ```

### Database Queries

1. **Query Format**
   ```python
   query = text("""
   SELECT
       column1,
       column2,
       column3
   FROM schema.table
   WHERE condition1
     AND condition2
   ORDER BY column1;
   """)
   ```

2. **Parameter Binding**
   ```python
   # Always use parameterized queries
   query = text("SELECT * FROM table WHERE id = :id")
   result = conn.execute(query, {"id": item_id})

   # For IN clauses, use tuples
   query = text("SELECT * FROM table WHERE id IN :ids")
   result = conn.execute(query, {"ids": tuple(id_list)})
   ```

---

## Testing Guidelines

### Manual Testing Checklist

Before committing changes, verify:

1. **Dashboard Functionality**
   - [ ] Dashboard starts without errors
   - [ ] All three tabs load correctly
   - [ ] Date picker works
   - [ ] Fund dropdown works
   - [ ] Charts render properly
   - [ ] Tables display data
   - [ ] Return display toggle works (원본/기여율)
   - [ ] No console errors

2. **Data Processing**
   - [ ] Database connection successful
   - [ ] Holdings data loads correctly
   - [ ] Auto-classification works
   - [ ] Cash/Currency filtering works correctly
   - [ ] No duplicate items created

3. **Return Calculation**
   - [ ] USD assets show T-1 adjusted returns
   - [ ] FX impact calculated correctly
   - [ ] KRW assets show standard returns

### Testing Auto-Classification

```python
# Test individual rules (now in dashboard.py)
from dashboard import auto_classify_item

# Test cases
test_cases = [
    ('000000', '콜론', {'대분류': '현금', '지역': '국내', '소분류': '현금 등'}),
    ('KR123', 'KRX금', {'대분류': '대체', '지역': '국내', '소분류': '금'}),
    ('US123', 'GOLD ETF', {'대분류': '대체', '지역': '글로벌', '소분류': '금'}),
    ('000000', '달러 F 2024', {'대분류': '통화', '지역': '미국', '소분류': '달러 선물'}),
]

for item_cd, item_nm, expected in test_cases:
    result = auto_classify_item(item_cd, item_nm)
    assert result == expected, f"Failed: {item_nm}"
    print(f"✓ {item_nm}: {result}")
```

### Testing Database Connection

```python
from sqlalchemy import create_engine, text

CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"
engine = create_engine(CONN_STR)

# Test connection
with engine.connect() as conn:
    result = conn.execute(text("SELECT COUNT(*) FROM dt.DWPM10530"))
    count = result.scalar()
    print(f"✓ Connection OK: {count:,} rows in DWPM10530")
```

---

## Common Tasks

### Task 1: Adding a New Classification Rule

**Example**: Add classification for "원유" (Crude Oil) assets

1. **Update `dashboard.py` auto_classify_item function**
   ```python
   def auto_classify_item(item_cd, item_nm):
       item_nm_upper = str(item_nm).upper()
       item_cd_upper = str(item_cd).upper()

       # ... existing rules ...

       # NEW: Crude Oil
       if '원유' in item_nm_upper or 'CRUDE' in item_nm_upper or 'OIL' in item_nm_upper:
           if 'WTI' in item_nm_upper:
               return {'대분류': '대체', '지역': '미국', '소분류': '원유'}
           else:
               return {'대분류': '대체', '지역': '글로벌', '소분류': '원유'}

       return None
   ```

2. **Test and commit**
   ```bash
   python -c "from dashboard import auto_classify_item; print(auto_classify_item('US123', 'WTI Crude Oil'))"
   git add dashboard.py
   git commit -m "feat: add crude oil classification rule"
   ```

### Task 2: Adding a New Fund to Monitoring

1. **Update fund list in `dashboard.py` and `report.py`**
   ```python
   FUND_LIST = [
       '06X08','07G02','07G03','07G04','07J20','07J27','07J34','07J41',
       '07J48','07J49','07P70','07W15','08K88','08N33','08N81','08P22','09L94',
       '1JM96','1JM98','2JM23','4JM12',
       'NEW_FUND_CODE'  # Add new fund code
   ]
   ```

2. **Test dashboard and report**
   ```bash
   python dashboard.py
   python report.py --fund NEW_FUND_CODE
   ```

### Task 3: Adding Items to Master Data

**Update the `MASTER_DATA_RAW` constant in `dashboard.py`**

```python
MASTER_DATA_RAW = """KR7332500008	ACE 200TR	주식	국내	일반
KR7367380003	ACE 미국나스닥100	주식	미국	일반
...existing items...
KR7NEW123456	New ETF Name	주식	국내	일반"""  # Add new line
```

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Failed

**Symptoms**:
```
sqlalchemy.exc.OperationalError: (pymysql.err.OperationalError)
(2003, "Can't connect to MySQL server on '192.168.195.55'")
```

**Solutions**:
```python
# Test connection
import pymysql

try:
    conn = pymysql.connect(
        host='192.168.195.55',
        user='solution',
        password='Solution123!',
        database='dt'
    )
    print("✓ Connection successful")
    conn.close()
except pymysql.Error as e:
    print(f"✗ Connection failed: {e}")
```

#### 2. Dashboard Not Loading

**Symptoms**:
- Blank page at http://127.0.0.1:8050
- Spinner keeps spinning

**Solutions**:
```python
# Check logs in terminal
# Look for error messages or stack traces

# Reduce data range for testing
START_STD_DT = "20260120"  # Instead of "20241201"
```

#### 3. Port Already in Use

**Symptoms**:
```
OSError: [Errno 98] Address already in use
```

**Solutions**:
```bash
# Find process using port 8050
lsof -i :8050

# Kill the process
kill -9 <PID>
```

---

## Best Practices Summary

### DO ✅

1. **Always read files before editing**
2. **Use parameterized SQL queries**
3. **Check for duplicates before adding to master**
4. **Test classification rules with sample data**
5. **Log important operations** (classifications, data loads)
6. **Document complex logic with comments**
7. **Apply cash/currency filtering for weight calculations**
8. **Handle USD asset T-1 time lag correctly**

### DON'T ❌

1. **Never commit database credentials** (use environment variables)
2. **Don't use `SELECT *` in production queries**
3. **Don't skip duplicate checks**
4. **Don't ignore warning messages**
5. **Don't hardcode date ranges** (use parameters)
6. **Don't push large data files to git** (use .gitignore)
7. **Don't run `git add -A`** (add specific files)

---

## Appendix

### A. Asset Classification Taxonomy

#### 대분류 (Major Category)

1. **주식** (Equity)
   - 국내/미국/글로벌/선진국/신흥국/호주
   - 일반/가치/성장/중소형/고배당

2. **채권** (Fixed Income)
   - 국내/미국/글로벌/신흥국
   - 국고채/회사채/하이일드/REPO/물가채
   - 단기채/장기채/종합채권/투자등급

3. **대체** (Alternative)
   - 국내/미국/글로벌
   - 금/부동산/인프라/원유/혼합

4. **현금** (Cash)
   - 국내/미국
   - 현금 등/예금/머니마켓

5. **통화** (Currency)
   - 미국/글로벌
   - 달러 선물/기타 통화

6. **모펀드** (Fund of Funds)
   - 모펀드 전용 분류

7. **기타** (Other)
   - 미분류 항목

### B. CATEGORY_ORDER (대분류 순서)

```python
CATEGORY_ORDER = ['주식', '채권', '대체', '모펀드', '통화', '기타', '현금']
```

---

## Changelog

### 2026-01-31

- Updated CLAUDE.md to reflect current codebase structure
- Major changes documented:
  - `dashboard_with_master.py` → `dashboard.py` (renamed)
  - `auto_classify.py` → integrated into `dashboard.py`
  - `create_initial_master.py` → integrated into `dashboard.py`
  - `master_asset_mapping.pkl` → replaced with `MASTER_DATA_RAW` constant
  - Added `market.py` (valuation panel)
  - Added `report.py` (terminal fund report)
  - Added `08P22` to FUND_LIST (now 21 funds)
  - Added cash/currency filtering feature
  - Added US market time lag handling for USD assets
  - Added return display toggle (raw/contribution)

### 2026-01-23

- Initial CLAUDE.md created
- Documented existing codebase structure
- Added comprehensive guides for:
  - Auto-classification system
  - Master data management
  - Dashboard application
  - Security considerations
  - Development workflows

---

**End of Document**

For questions or clarifications, refer to the source code or create an issue in the repository.
