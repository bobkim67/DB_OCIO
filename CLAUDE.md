# CLAUDE.md - AI Assistant Guide for DB_OCIO

Last Updated: 2026-01-23

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
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│           Python Data Processing Layer                  │
│  - SQLAlchemy (Database Connection)                     │
│  - Pandas (Data Transformation)                         │
│  - Auto Classification Engine                           │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│              Master Data Management                      │
│  - master_asset_mapping.pkl                             │
│  - Auto-classification Rules                            │
│  - Manual Override Support                              │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│              Dash Web Dashboard                          │
│  - Asset Allocation View                                │
│  - Interactive Pivot Tables                             │
│  - Time Series Charts                                   │
│  - Performance Analytics                                │
└─────────────────────────────────────────────────────────┘
```

### Key Features

1. **자동 자산 분류**: 종목명과 종목코드 기반으로 자산군 자동 분류
2. **마스터 데이터 관리**: Pickle 파일 기반 분류 규칙 저장 및 관리
3. **실시간 대시보드**: Dash 기반 인터랙티브 웹 인터페이스
4. **피봇 분석**: 다차원 자산배분 분석 도구
5. **성과 모니터링**: NAV, 수익률, 자산배분 추이 시각화

---

## Technology Stack

### Core Technologies

- **Python**: 3.8+
- **Web Framework**: Dash 2.14.0+ (Plotly-based)
- **Database**: MySQL (via SQLAlchemy + PyMySQL)
- **Data Processing**: Pandas 2.0.0+
- **Visualization**: Plotly 5.18.0+
- **UI Components**: dash-ag-grid 31.0.0+

### Dependencies

```txt
dash>=2.14.0
dash-ag-grid>=31.0.0
pandas>=2.0.0
plotly>=5.18.0
sqlalchemy>=2.0.0
pymysql>=1.1.0
```

### Development Tools

- **Version Control**: Git
- **Data Serialization**: Pickle (for master data)
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
├── auto_classify.py                # 자동 분류 엔진
├── create_initial_master.py        # 초기 마스터 데이터 생성 스크립트
├── dashboard_with_master.py        # 메인 대시보드 애플리케이션
├── mysql.ipynb                     # MySQL 연결 및 데이터 탐색 노트북
│
└── master_asset_mapping.pkl        # 자산 분류 마스터 데이터 (바이너리)
```

### File Descriptions

#### Core Application Files

1. **dashboard_with_master.py** (666 lines)
   - Main application entry point
   - Dash web server setup
   - Database connection management
   - Three main tabs:
     - 📊 자산배분 현황: Holdings, time series, performance charts
     - 🔍 피봇 분석: Interactive pivot tables
     - 📋 종목 리스트: Master data management
   - Runs on `http://0.0.0.0:8050`

2. **auto_classify.py** (108 lines)
   - Auto-classification logic based on item names
   - Classification rules:
     - 콜론 (Call Loan) → 현금/국내/현금 등
     - GOLD → 대체/국내 or 글로벌/금
     - 달러 선물 → 통화/미국/달러 선물
     - 코스피 선물 → 주식/국내/코스피 선물
     - REPO → 채권/국내/REPO
     - 예금/증거금 → 현금/국내 or 미국/현금 등
     - 미수금/미지급금 → 현금/국내/현금 등
   - Returns: `{'대분류': str, '지역': str, '소분류': str}` or `None`

3. **create_initial_master.py** (121 lines)
   - Initial master data setup script
   - Parses hardcoded asset mapping data
   - Applies auto-classification rules
   - Saves to `master_asset_mapping.pkl`
   - Includes 62 pre-defined assets (ETFs, funds, cash, etc.)

4. **mysql.ipynb** (Jupyter Notebook)
   - Ad-hoc database queries
   - Data exploration and analysis
   - Two main sections:
     - Dataset/dataseries structure exploration
     - Rate & duration analysis (10-year window)
   - Connects to SCIP database for market data

#### Data Files

5. **master_asset_mapping.pkl** (84KB)
   - Serialized Pandas DataFrame
   - Columns: `ITEM_CD`, `ITEM_NM`, `대분류`, `지역`, `소분류`, `등록일`, `비고`
   - Updated automatically when new items are auto-classified
   - **Important**: Binary file, do not edit manually

---

## Database Schema

### Connection Configuration

```python
# Production Database (dt)
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"
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

Stores fund-level metrics (NAV, performance).

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

Market data time series (rates, KRX, macro indicators).

```sql
SELECT
    timestamp_observation,
    timestamp_effective,
    dataseries_id,    -- 17: Rate, 22: Duration, 23: Real Rate, 46: KRX
    dataset_id,
    data              -- JSON blob
FROM SCIP.back_datapoint
```

### Fund List

Currently tracked funds (20 total):

```python
FUND_LIST = [
    '06X08','07G02','07G03','07G04','07J20','07J27','07J34','07J41',
    '07J48','07J49','07P70','07W15','08K88','08N33','08N81','09L94',
    '1JM96','1JM98','2JM23','4JM12'
]
```

---

## Core Modules

### 1. Auto-Classification Engine (`auto_classify.py`)

#### Functions

**`auto_classify_item(item_cd: str, item_nm: str) -> dict | None`**

Classifies an asset based on item code and name.

```python
result = auto_classify_item('KR7332500008', 'ACE 200TR')
# Returns: {'대분류': '주식', '지역': '국내', '소분류': '일반'}

result = auto_classify_item('1751100', '미수ETF분배금')
# Returns: {'대분류': '현금', '지역': '국내', '소분류': '현금 등'}

result = auto_classify_item('US78464A5083', 'SPDR S&P 500 VALUE ETF')
# Returns: None (auto-classification not applicable)
```

**`get_auto_classify_stats(items_df: DataFrame) -> dict`**

Returns statistics on auto-classified items.

```python
stats = get_auto_classify_stats(holdings_df)
# Returns: {'콜론': 2, '금': 3, '예금/증거금': 5, ...}
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

#### Adding New Classification Rules

When adding new rules:
1. Add to `auto_classify_item()` function in priority order
2. Test with sample data
3. Update `get_auto_classify_stats()` if creating a new category
4. Document the rule in this file

### 2. Master Data Management

#### Loading Master Data

```python
from dashboard_with_master import load_master_mapping, save_master_mapping

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

#### Updating Master Data

```python
# Add new item
new_item = pd.DataFrame([{
    'ITEM_CD': 'KR7123456789',
    'ITEM_NM': 'KODEX 미국채10년',
    '대분류': '채권',
    '지역': '미국',
    '소분류': '장기채',
    '등록일': '2026-01-23',
    '비고': '수동입력'
}])

master_df = pd.concat([master_df, new_item], ignore_index=True)
save_master_mapping(master_df)
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

### 3. Dashboard Application (`dashboard_with_master.py`)

#### Application Structure

```python
app = dash.Dash(__name__)
app.layout = html.Div([
    html.H1("자산배분 대시보드"),
    dcc.Tabs(id='tabs', children=[
        dcc.Tab(label='📊 자산배분 현황', value='tab-dashboard'),
        dcc.Tab(label='🔍 피봇 분석', value='tab-pivot'),
        dcc.Tab(label='📋 종목 리스트', value='tab-itemlist'),
    ]),
    html.Div(id='tabs-content')
])
```

#### Tab 1: 자산배분 현황 (Asset Allocation Dashboard)

Features:
- Date picker (영업일 기준)
- Fund selector dropdown
- Holdings table with subtotals by 대분류
- Stacked area chart (자산배분 추이)
- Performance chart (수익률 + NAV)
- Allocation detail table

#### Tab 2: 피봇 분석 (Pivot Analysis)

Interactive pivot table using `dash-pivottable`:
- Drag-and-drop field arrangement
- Multiple aggregation methods (Sum, Average, Count, etc.)
- Multiple renderers (Table, Heatmap, Bar Chart, etc.)
- Fields available: 날짜, FUND_CD, FUND_NM, 대분류, 지역, 소분류, ITEM_NM, 금액(억), 금액(원)

#### Tab 3: 종목 리스트 (Item List)

- Displays all items in master data
- Sortable and filterable
- Excel export support
- Shows total count

#### Running the Dashboard

```bash
python dashboard_with_master.py
# Access at: http://127.0.0.1:8050
# or http://0.0.0.0:8050 (accessible from network)
```

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

3. **Initialize Master Data** (if not exists)
   ```bash
   python create_initial_master.py
   ```

4. **Run Dashboard**
   ```bash
   python dashboard_with_master.py
   ```

### Branch Strategy

- **Main Branch**: Not yet created (first commit on claude/ branch)
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
   # Run application and verify
   python dashboard_with_master.py

   # Test auto-classification
   python -c "from auto_classify import auto_classify_item; print(auto_classify_item('test', '콜론'))"
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

**Examples**:
```
feat: add new classification rule for infrastructure funds

Added rule to auto-classify infrastructure ETFs based on
'인프라' or 'INFRASTRUCTURE' keywords.

https://claude.ai/code/session_abc123
```

```
fix: resolve duplicate items in master data

Added deduplication logic in classify_with_master() to prevent
duplicate ITEM_CD entries when auto-classifying.

https://claude.ai/code/session_xyz789
```

---

## Security Considerations

### Critical Security Issues

#### 1. Hardcoded Database Credentials

**Current State**: Database credentials are hardcoded in source files.

```python
# dashboard_with_master.py:20
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"

# mysql.ipynb
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/SCIP?charset=utf8mb4"
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

4. Create `.env.example` for reference:
   ```bash
   DB_HOST=your_host
   DB_USER=your_user
   DB_PASSWORD=your_password
   DB_NAME_DT=dt
   DB_NAME_SCIP=SCIP
   DB_CHARSET=utf8
   ```

#### 2. Network Exposure

**Current State**: Dashboard runs on `0.0.0.0:8050` (accessible from network)

**Risk Level**: 🟡 MEDIUM

**Recommended Actions**:
- Add authentication (dash-auth)
- Use reverse proxy (nginx) with HTTPS
- Restrict access by IP whitelist
- Use VPN for remote access

#### 3. SQL Injection

**Current State**: Using SQLAlchemy `text()` with parameterized queries ✅

**Status**: 🟢 SECURE

The code correctly uses parameterized queries:
```python
query = text("""
SELECT * FROM dt.DWPM10530
WHERE STD_DT BETWEEN :start_dt AND :end_dt
  AND FUND_CD IN :fund_list
""")
conn.execute(query, {"start_dt": "20241201", "fund_list": tuple(FUND_LIST)})
```

#### 4. Data Validation

**Current State**: Limited input validation

**Recommendations**:
- Validate date ranges before database queries
- Sanitize user inputs in callbacks
- Add error handling for malformed data

### Security Checklist

- [ ] Move database credentials to environment variables
- [ ] Add `.env` to `.gitignore` (already done ✅)
- [ ] Implement dashboard authentication
- [ ] Add HTTPS support
- [ ] Review and restrict network access
- [ ] Add input validation in Dash callbacks
- [ ] Regular security audits of dependencies
- [ ] Document sensitive data handling procedures

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

   # Local
   from auto_classify import auto_classify_item
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

3. **Type Conversion**
   ```python
   # Explicit type conversion
   df['ITEM_CD'] = df['ITEM_CD'].astype(str).str.strip()
   ```

### Dash Callbacks

1. **Callback Organization**
   ```python
   @app.callback(
       [Output('output-1', 'data'),
        Output('output-2', 'figure')],
       [Input('input-1', 'value'),
        Input('input-2', 'date')]
   )
   def update_dashboard(input1, input2):
       """
       Brief description of what this callback does.

       Parameters:
       -----------
       input1 : str
           Description
       input2 : date
           Description

       Returns:
       --------
       tuple
           (data, figure)
       """
       # Implementation
       return data, figure
   ```

2. **State Management**
   - Keep state in component properties (value, data, figure)
   - Avoid global mutable state
   - Use `State` for values that don't trigger callback

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

### Master Data Management

1. **Always check for duplicates**
   ```python
   existing_codes = set(master_df['ITEM_CD'].values)
   new_codes = set(new_items_df['ITEM_CD'].values)
   duplicates = new_codes & existing_codes

   if duplicates:
       print(f"[WARNING] {len(duplicates)} duplicates found")
       new_items_df = new_items_df[~new_items_df['ITEM_CD'].isin(duplicates)]
   ```

2. **Save after modifications**
   ```python
   master_df = pd.concat([master_df, new_items], ignore_index=True)
   save_master_mapping(master_df)
   print(f"[✓] Master updated: {len(master_df)} items")
   ```

3. **Log changes**
   ```python
   print(f"[AUTO] {len(new_items)} items auto-classified")
   print(f"[MANUAL] {len(manual_items)} items manually added")
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
   - [ ] No console errors

2. **Data Processing**
   - [ ] Database connection successful
   - [ ] Holdings data loads correctly
   - [ ] Auto-classification works
   - [ ] Master data saves/loads correctly
   - [ ] No duplicate items created

3. **Classification Rules**
   - [ ] Test each auto-classification rule
   - [ ] Verify priority order
   - [ ] Check edge cases

### Testing Auto-Classification

```python
# Test individual rules
from auto_classify import auto_classify_item

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

### Testing Master Data

```python
from dashboard_with_master import load_master_mapping, save_master_mapping

# Load
master = load_master_mapping()
print(f"✓ Loaded {len(master)} items")

# Check for duplicates
duplicates = master[master.duplicated('ITEM_CD', keep=False)]
if len(duplicates) > 0:
    print(f"⚠️ Found {len(duplicates)} duplicates:")
    print(duplicates[['ITEM_CD', 'ITEM_NM']])
else:
    print("✓ No duplicates")

# Check required columns
required_cols = ['ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류']
missing_cols = set(required_cols) - set(master.columns)
if missing_cols:
    print(f"⚠️ Missing columns: {missing_cols}")
else:
    print("✓ All required columns present")
```

---

## Common Tasks

### Task 1: Adding a New Classification Rule

**Example**: Add classification for "원유" (Crude Oil) assets

1. **Update `auto_classify.py`**
   ```python
   def auto_classify_item(item_cd, item_nm):
       item_nm_upper = str(item_nm).upper()
       item_cd_upper = str(item_cd).upper()

       # ... existing rules ...

       # NEW: Crude Oil
       if '원유' in item_nm_upper or 'CRUDE' in item_nm_upper or 'OIL' in item_nm_upper:
           # Distinguish WTI vs Brent
           if 'WTI' in item_nm_upper:
               return {'대분류': '대체', '지역': '미국', '소분류': '원유'}
           else:
               return {'대분류': '대체', '지역': '글로벌', '소분류': '원유'}

       return None
   ```

2. **Update statistics function**
   ```python
   def get_auto_classify_stats(items_df):
       stats = {
           # ... existing categories ...
           '원유': 0,
       }

       for _, row in items_df.iterrows():
           # ... existing logic ...
           elif '원유' in item_nm_upper or 'CRUDE' in item_nm_upper:
               stats['원유'] += 1

       return {k: v for k, v in stats.items() if v > 0}
   ```

3. **Test the new rule**
   ```python
   from auto_classify import auto_classify_item

   test_cases = [
       ('US123', 'WTI Crude Oil', {'대분류': '대체', '지역': '미국', '소분류': '원유'}),
       ('GB456', 'Brent Crude', {'대분류': '대체', '지역': '글로벌', '소분류': '원유'}),
   ]

   for item_cd, item_nm, expected in test_cases:
       result = auto_classify_item(item_cd, item_nm)
       assert result == expected
       print(f"✓ {item_nm}: {result}")
   ```

4. **Run dashboard and verify**
   ```bash
   python dashboard_with_master.py
   # Check that crude oil items are now classified correctly
   ```

5. **Commit changes**
   ```bash
   git add auto_classify.py
   git commit -m "feat: add crude oil classification rule

   Added auto-classification for crude oil assets with WTI/Brent distinction.

   https://claude.ai/code/session_[id]"
   ```

### Task 2: Adding a New Fund to Monitoring

1. **Update fund list in `dashboard_with_master.py`**
   ```python
   FUND_LIST = [
       '06X08','07G02','07G03','07G04','07J20','07J27','07J34','07J41',
       '07J48','07J49','07P70','07W15','08K88','08N33','08N81','09L94',
       '1JM96','1JM98','2JM23','4JM12',
       'NEW_FUND_CODE'  # Add new fund code
   ]
   ```

2. **Verify fund exists in database**
   ```python
   from sqlalchemy import create_engine, text

   engine = create_engine(CONN_STR)
   with engine.connect() as conn:
       result = conn.execute(
           text("SELECT DISTINCT FUND_CD, FUND_NM FROM dt.DWPM10530 WHERE FUND_CD = :code"),
           {"code": "NEW_FUND_CODE"}
       )
       print(result.fetchall())
   ```

3. **Test dashboard**
   ```bash
   python dashboard_with_master.py
   # Select new fund from dropdown
   # Verify data loads correctly
   ```

4. **Commit changes**
   ```bash
   git add dashboard_with_master.py
   git commit -m "feat: add NEW_FUND_CODE to monitoring list"
   ```

### Task 3: Manually Adding Items to Master Data

**Example**: Add a new custom fund that can't be auto-classified

1. **Create a script or notebook**
   ```python
   import pandas as pd
   from datetime import datetime
   from dashboard_with_master import load_master_mapping, save_master_mapping

   # Load existing master
   master = load_master_mapping()

   # Create new items
   new_items = pd.DataFrame([
       {
           'ITEM_CD': 'KR7999999999',
           'ITEM_NM': 'Custom Private Equity Fund A',
           '대분류': '대체',
           '지역': '국내',
           '소분류': '사모펀드',
           '등록일': datetime.now().strftime('%Y-%m-%d'),
           '비고': '수동입력'
       },
       {
           'ITEM_CD': 'LU1234567890',
           'ITEM_NM': 'Luxembourg Infrastructure Fund',
           '대분류': '대체',
           '지역': '글로벌',
           '소분류': '인프라',
           '등록일': datetime.now().strftime('%Y-%m-%d'),
           '비고': '수동입력'
       }
   ])

   # Check for duplicates
   existing_codes = set(master['ITEM_CD'].values)
   new_codes = set(new_items['ITEM_CD'].values)
   duplicates = new_codes & existing_codes

   if duplicates:
       print(f"⚠️ Duplicates found: {duplicates}")
       new_items = new_items[~new_items['ITEM_CD'].isin(duplicates)]

   # Add to master
   master = pd.concat([master, new_items], ignore_index=True)

   # Save
   save_master_mapping(master)
   print(f"✓ Added {len(new_items)} items. Total: {len(master)}")
   ```

2. **Verify in dashboard**
   ```bash
   python dashboard_with_master.py
   # Go to "📋 종목 리스트" tab
   # Search for new items
   ```

### Task 4: Exporting Data

**Export holdings data to Excel**

```python
import pandas as pd
from sqlalchemy import create_engine, text

CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"
engine = create_engine(CONN_STR)

query = text("""
SELECT
    STD_DT,
    FUND_CD,
    FUND_NM,
    ITEM_CD,
    ITEM_NM,
    AST_CLSF_CD_NM,
    SUM(EVL_AMT) AS EVL_AMT
FROM dt.DWPM10530
WHERE STD_DT = '20241231'
  AND EVL_AMT > 0
GROUP BY STD_DT, FUND_CD, FUND_NM, ITEM_CD, ITEM_NM, AST_CLSF_CD_NM
ORDER BY FUND_CD, EVL_AMT DESC;
""")

with engine.connect() as conn:
    df = pd.read_sql(query, conn)

# Apply classification
from dashboard_with_master import load_master_mapping, classify_with_master

master = load_master_mapping()
df, unmapped, _ = classify_with_master(df, master)

# Export
df.to_excel("holdings_20241231_classified.xlsx", index=False)
print(f"✓ Exported {len(df)} records to Excel")
```

### Task 5: Analyzing Unmapped Items

**Find and analyze items that need classification**

```python
from dashboard_with_master import load_master_mapping, classify_with_master
import pandas as pd
from sqlalchemy import create_engine, text

# Load data
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"
engine = create_engine(CONN_STR)

query = text("""
SELECT DISTINCT ITEM_CD, ITEM_NM, AST_CLSF_CD_NM
FROM dt.DWPM10530
WHERE STD_DT >= '20241201'
  AND EVL_AMT > 0
ORDER BY ITEM_NM;
""")

with engine.connect() as conn:
    holdings = pd.read_sql(query, conn)

# Classify
master = load_master_mapping()
_, unmapped, _ = classify_with_master(holdings, master)

# Analyze
print(f"Total unique items: {len(holdings)}")
print(f"Unmapped items: {len(unmapped)}")
print(f"Coverage: {(1 - len(unmapped)/len(holdings))*100:.1f}%\n")

print("Top 20 unmapped items:")
print(unmapped[['ITEM_CD', 'ITEM_NM', 'AST_CLSF_CD_NM']].head(20))

# Group by AST_CLSF_CD_NM
print("\nUnmapped items by asset class:")
print(unmapped['AST_CLSF_CD_NM'].value_counts())
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

**Possible Causes**:
- Network connectivity issues
- Database server down
- Firewall blocking connection
- Incorrect credentials

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

#### 2. Master Data File Corrupted

**Symptoms**:
```
pickle.UnpicklingError: invalid load key
```

**Solutions**:
```bash
# Backup corrupted file
mv master_asset_mapping.pkl master_asset_mapping.pkl.bak

# Recreate master data
python create_initial_master.py

# Or restore from backup (if available)
cp master_asset_mapping.pkl.backup master_asset_mapping.pkl
```

#### 3. Dashboard Not Loading

**Symptoms**:
- Blank page at http://127.0.0.1:8050
- Spinner keeps spinning

**Possible Causes**:
- Data loading failed
- Database query timeout
- Memory exhaustion

**Solutions**:
```python
# Check logs in terminal
# Look for error messages or stack traces

# Reduce data range for testing
START_STD_DT = "20241220"  # Instead of "20241201"

# Test data loading separately
from dashboard_with_master import engine, query_holding
import pandas as pd
from sqlalchemy import text

with engine.connect() as conn:
    df = pd.read_sql(text(query_holding), conn, params={...})
    print(f"Loaded {len(df)} records")
```

#### 4. Duplicate Items in Master

**Symptoms**:
- Same ITEM_CD appears multiple times
- Incorrect classification

**Detection**:
```python
from dashboard_with_master import load_master_mapping

master = load_master_mapping()
duplicates = master[master.duplicated('ITEM_CD', keep=False)]

if len(duplicates) > 0:
    print("Duplicates found:")
    print(duplicates.sort_values('ITEM_CD')[['ITEM_CD', 'ITEM_NM', '등록일', '비고']])
```

**Fix**:
```python
# Keep the first occurrence, remove duplicates
master_clean = master.drop_duplicates('ITEM_CD', keep='first')

from dashboard_with_master import save_master_mapping
save_master_mapping(master_clean)

print(f"Removed {len(master) - len(master_clean)} duplicates")
```

#### 5. Port Already in Use

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

# Or use a different port
# In dashboard_with_master.py:
app.run(debug=True, host='0.0.0.0', port=8051)
```

#### 6. Memory Error with Large Datasets

**Symptoms**:
```
MemoryError: Unable to allocate array
```

**Solutions**:
```python
# Reduce date range
START_STD_DT = "20241215"  # Last 2 weeks instead of 1 month

# Limit funds
FUND_LIST = FUND_LIST[:5]  # Test with 5 funds first

# Use chunking for large queries
chunk_size = 10000
chunks = []
for chunk in pd.read_sql(query, conn, chunksize=chunk_size):
    chunks.append(chunk)
df = pd.concat(chunks, ignore_index=True)
```

---

## Best Practices Summary

### DO ✅

1. **Always read files before editing**
2. **Use parameterized SQL queries**
3. **Check for duplicates before adding to master**
4. **Test classification rules with sample data**
5. **Log important operations** (classifications, data loads)
6. **Use type hints in function signatures**
7. **Write descriptive commit messages**
8. **Document complex logic with comments**
9. **Save master data after modifications**
10. **Validate user inputs in callbacks**

### DON'T ❌

1. **Never commit database credentials** (use environment variables)
2. **Never manually edit .pkl files** (use Python)
3. **Don't use `SELECT *` in production queries**
4. **Don't skip duplicate checks**
5. **Don't ignore warning messages**
6. **Don't hardcode date ranges** (use parameters)
7. **Don't use `pd.concat` in loops** (collect then concat once)
8. **Don't ignore NULL values** (use `.fillna()` or `.dropna()`)
9. **Don't push large data files to git** (use .gitignore)
10. **Don't run `git add -A`** (add specific files)

---

## Appendix

### A. Asset Classification Taxonomy

#### 대분류 (Major Category)

1. **주식** (Equity)
   - 국내/미국/글로벌/선진국/신흥국
   - 일반/가치/성장/중소형/고배당

2. **채권** (Fixed Income)
   - 국내/미국/글로벌
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

### B. Database Table Details

#### DWPM10530 Schema

```sql
CREATE TABLE dt.DWPM10530 (
    STD_DT          INT,           -- 기준일 YYYYMMDD
    FUND_CD         VARCHAR(10),   -- 펀드코드
    FUND_NM         VARCHAR(200),  -- 펀드명
    ITEM_CD         VARCHAR(20),   -- 종목코드
    ITEM_NM         VARCHAR(200),  -- 종목명
    AST_CLSF_CD_NM  VARCHAR(100),  -- 자산분류코드명
    EVL_AMT         DECIMAL(18,2), -- 평가금액
    -- ... other columns
    PRIMARY KEY (STD_DT, FUND_CD, ITEM_CD)
);
```

#### DWPM10510 Schema

```sql
CREATE TABLE dt.DWPM10510 (
    STD_DT       INT,           -- 기준일
    FUND_CD      VARCHAR(10),   -- 펀드코드
    MOD_STPR     DECIMAL(18,4), -- 수정기준가격
    NAST_AMT     DECIMAL(18,2), -- 순자산총액
    -- ... other columns
    PRIMARY KEY (STD_DT, FUND_CD)
);
```

### C. Useful SQL Queries

**Get all unique funds**:
```sql
SELECT DISTINCT FUND_CD, FUND_NM
FROM dt.DWPM10530
ORDER BY FUND_CD;
```

**Get holdings on specific date**:
```sql
SELECT *
FROM dt.DWPM10530
WHERE STD_DT = 20241231
  AND EVL_AMT > 0
ORDER BY FUND_CD, EVL_AMT DESC;
```

**Get fund performance metrics**:
```sql
SELECT
    STD_DT,
    FUND_CD,
    MOD_STPR,
    NAST_AMT,
    LAG(MOD_STPR) OVER (PARTITION BY FUND_CD ORDER BY STD_DT) AS prev_price
FROM dt.DWPM10510
WHERE FUND_CD = '07G02'
  AND STD_DT >= 20241201
ORDER BY STD_DT;
```

**Get asset allocation by fund**:
```sql
SELECT
    FUND_CD,
    FUND_NM,
    AST_CLSF_CD_NM,
    SUM(EVL_AMT) AS total_amt
FROM dt.DWPM10530
WHERE STD_DT = 20241231
  AND EVL_AMT > 0
GROUP BY FUND_CD, FUND_NM, AST_CLSF_CD_NM
ORDER BY FUND_CD, total_amt DESC;
```

---

## Changelog

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
