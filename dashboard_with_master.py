import pandas as pd
import numpy as np
import pickle
import os
import json
from sqlalchemy import create_engine, text
from datetime import datetime, date, timedelta

import dash
from dash import dcc, html, Input, Output, State, dash_table
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from dash_pivottable import PivotTable

from auto_classify import auto_classify_item

# =========================
# 0) Parameters
# =========================
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/dt?charset=utf8"
CONN_STR_SCIP = "mysql+pymysql://solution:Solution123!@192.168.195.55/SCIP?charset=utf8mb4"
START_STD_DT = "20241201"
MASTER_FILE = "master_asset_mapping.pkl"

FUND_LIST = [
    '06X08','07G02','07G03','07G04','07J20','07J27','07J34','07J41',
    '07J48','07J49','07P70','07W15','08K88','08N33','08N81','09L94',
    '1JM96','1JM98','2JM23','4JM12'
]

# 펀드명 매핑은 데이터 로드 시 자동 생성

# =========================
# 1) 마스터 테이블 관리
# =========================
def load_master_mapping():
    """마스터 분류 테이블 로드"""
    if not os.path.exists(MASTER_FILE):
        print(f"[WARNING] {MASTER_FILE} 파일이 없습니다. 빈 마스터 생성")
        df = pd.DataFrame(columns=[
            'ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류',
            '등록일', '비고'
        ])
        df.to_pickle(MASTER_FILE)
        return df
    
    return pd.read_pickle(MASTER_FILE)

def save_master_mapping(df):
    """마스터 테이블 저장"""
    df.to_pickle(MASTER_FILE)
    print(f"[✓] 마스터 테이블 저장 완료: {len(df)}개 종목")

def classify_with_master(holding_df, master_df):
    """마스터 테이블 기반 분류 + 자동 분류"""
    
    # 디버깅: ITEM_CD 타입 확인
    print(f"\n[DEBUG] Holding ITEM_CD 타입: {holding_df['ITEM_CD'].dtype}")
    print(f"[DEBUG] Master ITEM_CD 타입: {master_df['ITEM_CD'].dtype}")
    print(f"[DEBUG] Holding 총 {len(holding_df)}개 행, 고유 ITEM_CD {holding_df['ITEM_CD'].nunique()}개")
    print(f"[DEBUG] Master 총 {len(master_df)}개 행")
    
    # ITEM_CD를 문자열로 통일
    holding_df['ITEM_CD'] = holding_df['ITEM_CD'].astype(str).str.strip()
    master_df['ITEM_CD'] = master_df['ITEM_CD'].astype(str).str.strip()
    
    # 샘플 확인
    print(f"[DEBUG] Holding ITEM_CD 샘플: {holding_df['ITEM_CD'].head(5).tolist()}")
    print(f"[DEBUG] Master ITEM_CD 샘플: {master_df['ITEM_CD'].head(5).tolist()}")
    
    result = holding_df.merge(
        master_df[['ITEM_CD', '대분류', '지역', '소분류']],
        on='ITEM_CD',
        how='left'
    )
    
    # 디버깅: merge 결과
    matched = result['소분류'].notna().sum()
    total = len(result)
    print(f"[DEBUG] Merge 결과: {matched}/{total} ({matched/total*100:.1f}%) 매칭됨")
    
    # 미분류 종목
    unmapped = result[result['소분류'].isna()][
        ['STD_DT', 'ITEM_CD', 'ITEM_NM', 'AST_CLSF_CD_NM', 'EVL_AMT']
    ].drop_duplicates(subset=['ITEM_CD'])
    
    print(f"[DEBUG] 미분류 종목: {len(unmapped)}개")
    if len(unmapped) > 0:
        print(f"[DEBUG] 미분류 샘플:")
        for _, row in unmapped.head(5).iterrows():
            print(f"  - {row['ITEM_CD']}: {row['ITEM_NM']}")
    
    # 🆕 자동 분류 시도
    auto_classified = []
    for _, row in unmapped.iterrows():
        auto_result = auto_classify_item(row['ITEM_CD'], row['ITEM_NM'])
        if auto_result:
            auto_classified.append({
                'ITEM_CD': str(row['ITEM_CD']),
                'ITEM_NM': row['ITEM_NM'],
                '대분류': auto_result['대분류'],
                '지역': auto_result['지역'],
                '소분류': auto_result['소분류'],
                '등록일': datetime.now().strftime('%Y-%m-%d'),
                '비고': '자동분류'
            })
    
    # 🆕 자동 분류된 것 마스터에 추가
    if auto_classified:
        new_items_df = pd.DataFrame(auto_classified)
        
        # 🔥 중복 제거: master에 이미 있는 ITEM_CD 제외
        existing_codes = set(master_df['ITEM_CD'].astype(str).values)
        new_codes = set(new_items_df['ITEM_CD'].astype(str).values)
        duplicate_codes = new_codes & existing_codes
        
        if duplicate_codes:
            print(f"[AUTO] {len(duplicate_codes)}개 중복 종목 제외: {list(duplicate_codes)[:5]}")
        
        new_items_df = new_items_df[~new_items_df['ITEM_CD'].isin(duplicate_codes)]
        
        if len(new_items_df) > 0:
            master_df = pd.concat([master_df, new_items_df], ignore_index=True)
            save_master_mapping(master_df)
            print(f"[AUTO] {len(new_items_df)}개 신규 종목 자동 분류 → 마스터에 추가됨")
        else:
            print(f"[AUTO] 모든 자동 분류 종목이 이미 master에 존재함")
        
        # result에도 자동 분류 반영
        for item in auto_classified:
            mask = result['ITEM_CD'] == item['ITEM_CD']
            result.loc[mask, '소분류'] = item['소분류']
            result.loc[mask, '대분류'] = item['대분류']
            result.loc[mask, '지역'] = item['지역']
        
        # unmapped에서 제외
        auto_codes = [item['ITEM_CD'] for item in auto_classified]
        unmapped = unmapped[~unmapped['ITEM_CD'].isin(auto_codes)]
    
    # 나머지 미분류는 '기타'로 임시 처리
    result['소분류'] = result['소분류'].fillna('기타')
    result['대분류'] = result['대분류'].fillna('기타')
    result['지역'] = result['지역'].fillna('기타')
    
    print(f"[DEBUG] 최종 '기타' 처리: {(result['대분류'] == '기타').sum()}개\n")
    
    return result, unmapped, master_df  # 🔥 업데이트된 master 반환!

# =========================
# 1-2) 수익률 데이터 처리
# =========================
def parse_data_blob(blob):
    """
    Parse FactSet data blob into numeric value
    Handles JSON format: {"USD": value, "KRW": value}
    """
    if blob is None:
        return None

    # Convert bytes to string
    if isinstance(blob, (bytes, bytearray)):
        s = blob.decode('utf-8')
    else:
        s = str(blob)

    s = s.strip()

    # Try JSON parsing
    if s.startswith('{') or s.startswith('['):
        try:
            obj = json.loads(s)
            # If dict, return USD value (or KRW if USD not available)
            if isinstance(obj, dict):
                return float(obj.get('USD', obj.get('KRW', None)))
            return float(obj)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Try direct numeric conversion
    try:
        return float(s.replace(',', ''))
    except (ValueError, AttributeError):
        return None

def should_exclude_for_return(item_nm):
    """
    Determine if item should be excluded from return calculation
    Excludes: cash, futures, REPO, deposits, receivables, etc.
    """
    item_nm_upper = str(item_nm).upper()

    # 모펀드
    if '모투자신탁' in item_nm:
        return True
    # 콜론
    if '콜론' in item_nm_upper:
        return True
    # 선물
    if ('달러 F' in item_nm_upper or 'USD F' in item_nm_upper or
        ('코스피' in item_nm_upper and ' F ' in item_nm_upper)):
        return True
    # REPO
    if 'REPO' in item_nm_upper:
        return True
    # 예금/증거금
    if any(word in item_nm_upper for word in ['예금', '증거금', 'DEPOSIT']):
        return True
    # 미수/미지급
    if any(word in item_nm_upper for word in ['미수', '미지급', '청약금', '원천세', '분배금', '기타자산']):
        return True

    return False

def fetch_factset_returns(master_df, latest_date):
    """
    Fetch FactSet FG Return data for items in master
    Returns DataFrame with columns: ITEM_CD, date, return_index
    """
    # Filter items that should have return data
    items_for_return = master_df[~master_df['ITEM_NM'].apply(should_exclude_for_return)].copy()

    if len(items_for_return) == 0:
        print("[INFO] No items for return calculation")
        return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index'])

    # Get ISIN list
    isin_list = items_for_return['ITEM_CD'].tolist()

    # Calculate lookback period (1 year + buffer)
    start_date = latest_date - timedelta(days=400)

    print(f"[INFO] Fetching FactSet returns for {len(isin_list)} items...")
    print(f"[INFO] Date range: {start_date} to {latest_date}")

    # Connect to SCIP database
    engine_scip = create_engine(CONN_STR_SCIP)

    # Query FG Return data (dataseries_id = 6)
    # Also try Total Return Index (dataseries_id = 39) as fallback
    query = text("""
    SELECT
        d.ISIN as ITEM_CD,
        DATE(dp.timestamp_observation) as date,
        dp.dataseries_id,
        dp.data
    FROM SCIP.back_datapoint dp
    INNER JOIN SCIP.back_dataset d ON dp.dataset_id = d.id
    WHERE d.ISIN IN :isin_list
      AND dp.dataseries_id IN (6, 39)
      AND dp.timestamp_observation >= :start_date
      AND dp.timestamp_observation <= :end_date
    ORDER BY d.ISIN, dp.timestamp_observation
    """)

    try:
        with engine_scip.connect() as conn:
            df_raw = pd.read_sql(
                query, conn,
                params={
                    'isin_list': tuple(isin_list),
                    'start_date': start_date,
                    'end_date': latest_date
                }
            )

        print(f"[INFO] Retrieved {len(df_raw)} raw datapoints")

        if df_raw.empty:
            print("[WARNING] No FactSet data found for any items")
            return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index'])

        # Parse data blobs
        df_raw['return_index'] = df_raw['data'].apply(parse_data_blob)
        df_raw = df_raw.dropna(subset=['return_index'])

        # Prefer dataseries_id = 6, fallback to 39
        df_raw = df_raw.sort_values(['ITEM_CD', 'date', 'dataseries_id'])
        df_raw = df_raw.drop_duplicates(subset=['ITEM_CD', 'date'], keep='first')

        # Keep only necessary columns
        result = df_raw[['ITEM_CD', 'date', 'return_index']].copy()

        print(f"[INFO] Parsed {len(result)} return datapoints for {result['ITEM_CD'].nunique()} items")

        return result

    except Exception as e:
        print(f"[ERROR] Failed to fetch FactSet returns: {e}")
        return pd.DataFrame(columns=['ITEM_CD', 'date', 'return_index'])

def calculate_return_periods(return_df, reference_date):
    """
    Calculate returns for multiple periods: 1D, 1W, 1M, 3M, 6M, 1Y, YTD
    Returns DataFrame with ITEM_CD and return columns
    """
    if return_df.empty:
        return pd.DataFrame(columns=['ITEM_CD', '1D', '1W', '1M', '3M', '6M', '1Y', 'YTD'])

    # Ensure date is datetime
    return_df['date'] = pd.to_datetime(return_df['date'])
    reference_date = pd.to_datetime(reference_date)

    # Define period endpoints
    ytd_start = datetime(reference_date.year, 1, 1)
    periods = {
        '1D': reference_date - timedelta(days=1),
        '1W': reference_date - timedelta(days=7),
        '1M': reference_date - timedelta(days=30),
        '3M': reference_date - timedelta(days=90),
        '6M': reference_date - timedelta(days=180),
        '1Y': reference_date - timedelta(days=365),
        'YTD': ytd_start
    }

    results = []

    for item_cd in return_df['ITEM_CD'].unique():
        item_data = return_df[return_df['ITEM_CD'] == item_cd].sort_values('date')

        # Get latest value
        latest = item_data[item_data['date'] <= reference_date]
        if latest.empty:
            continue

        latest_value = latest.iloc[-1]['return_index']
        latest_date = latest.iloc[-1]['date']

        row = {'ITEM_CD': item_cd}

        # Calculate each period
        for period_name, period_start in periods.items():
            # Find closest date on or before period_start
            period_data = item_data[item_data['date'] <= period_start]

            if period_data.empty:
                row[period_name] = np.nan
            else:
                period_value = period_data.iloc[-1]['return_index']
                # Return calculation: (latest / period - 1) * 100
                if period_value > 0:
                    row[period_name] = round((latest_value / period_value - 1) * 100, 2)
                else:
                    row[period_name] = np.nan

        results.append(row)

    result_df = pd.DataFrame(results)
    print(f"[INFO] Calculated returns for {len(result_df)} items")

    return result_df

# =========================
# 2) 데이터 로드
# =========================
print("[INFO] Loading master mapping...")
master_mapping = load_master_mapping()
print(f"[INFO] Master mapping loaded: {len(master_mapping)} items")

print("[INFO] Loading data from DB...")
engine = create_engine(CONN_STR)

# 영업일 캘린더
query_BDay = """
SELECT std_dt
FROM dt.DWCI10220
WHERE std_dt >= :start_dt
  AND hldy_yn = 'N'
  AND day_ds_cd IN (2,3,4,5,6)
ORDER BY std_dt;
"""
with engine.connect() as conn:
    bdays = pd.read_sql(text(query_BDay), conn, params={"start_dt": START_STD_DT})

if bdays.empty:
    raise ValueError("영업일 캘린더 조회 결과가 없습니다.")

END_STD_DT = str(int(bdays["std_dt"].max()))
print(f"[INFO] Date range: {START_STD_DT} ~ {END_STD_DT}")

# Holdings
query_holding = """
SELECT
    STD_DT,
    FUND_CD,
    FUND_NM,
    ITEM_CD,
    ITEM_NM,
    AST_CLSF_CD_NM,
    SUM(EVL_AMT) AS EVL_AMT
FROM dt.DWPM10530
WHERE STD_DT BETWEEN :start_dt AND :end_dt
  AND EVL_AMT > 0
  AND FUND_CD IN :fund_list
GROUP BY STD_DT, FUND_CD, FUND_NM, ITEM_CD, ITEM_NM, AST_CLSF_CD_NM
ORDER BY STD_DT, FUND_CD;
"""

# Fund metrics
query_metrics = """
SELECT
    STD_DT,
    FUND_CD,
    MOD_STPR,
    NAST_AMT
FROM dt.DWPM10510
WHERE STD_DT BETWEEN :start_dt AND :end_dt
  AND FUND_CD IN :fund_list
ORDER BY STD_DT, FUND_CD;
"""

fund_tuple = tuple(FUND_LIST)
with engine.connect() as conn:
    holding = pd.read_sql(
        text(query_holding), conn,
        params={"start_dt": START_STD_DT, "end_dt": END_STD_DT, "fund_list": fund_tuple}
    )
    metrics = pd.read_sql(
        text(query_metrics), conn,
        params={"start_dt": START_STD_DT, "end_dt": END_STD_DT, "fund_list": fund_tuple}
    )

print(f"[INFO] Loaded {len(holding)} holding records, {len(metrics)} metric records")

# 펀드명 매핑 생성
FUND_NAMES = holding[['FUND_CD', 'FUND_NM']].drop_duplicates().set_index('FUND_CD')['FUND_NM'].to_dict()
print(f"[INFO] Fund names mapped: {len(FUND_NAMES)} funds")
for fund_cd, fund_nm in list(FUND_NAMES.items())[:3]:
    print(f"  - {fund_cd}: {fund_nm}")

# 날짜 변환
def convert_to_date(dt_int):
    """YYYYMMDD int를 date 객체로 변환"""
    dt_str = str(int(dt_int))
    return datetime.strptime(dt_str, '%Y%m%d').date()

holding['STD_DT_INT'] = holding['STD_DT']
holding['STD_DT'] = holding['STD_DT'].apply(convert_to_date)
metrics['STD_DT'] = metrics['STD_DT'].apply(lambda x: datetime.strptime(str(int(x)), '%Y%m%d'))

# 자산군 분류
print("[INFO] Classifying assets with master mapping...")
holding, unmapped, master_mapping = classify_with_master(holding, master_mapping)
print(f"[INFO] Master now contains {len(master_mapping)} items")

# 날짜 리스트 (수익률 계산 전에 latest_date 필요)
available_dates = sorted(holding['STD_DT'].unique())
latest_date = available_dates[-1]

# 🆕 수익률 데이터 로드
print("[INFO] Fetching FactSet return data...")
factset_returns = fetch_factset_returns(master_mapping, latest_date)
return_periods = calculate_return_periods(factset_returns, latest_date)
print(f"[INFO] Return data loaded for {len(return_periods)} items")

# Merge return data with holding
holding = holding.merge(return_periods, on='ITEM_CD', how='left')

# 수익률 계산 (펀드)
metrics = metrics.sort_values(['FUND_CD', 'STD_DT'])
metrics['RET'] = metrics.groupby('FUND_CD')['MOD_STPR'].transform(
    lambda x: (x / x.iloc[0] - 1) * 100
)

print(f"[INFO] Latest date: {latest_date}")
print(f"[INFO] Unmapped items: {len(unmapped)}")

# =========================
# 3) Dash App
# =========================
app = dash.Dash(__name__, suppress_callback_exceptions=True)

app.layout = html.Div([
    html.H1("자산배분 대시보드", style={'textAlign': 'center', 'marginBottom': 30}),
    
    # 탭 구조
    dcc.Tabs(id='tabs', value='tab-dashboard', children=[
        dcc.Tab(label='📊 자산배분 현황', value='tab-dashboard'),
        dcc.Tab(label='🔍 피봇 분석', value='tab-pivot'),
        dcc.Tab(label='📋 종목 리스트', value='tab-itemlist'),
    ]),
    
    html.Div(id='tabs-content')
    
], style={'padding': '20px', 'maxWidth': '1400px', 'margin': '0 auto'})

# =========================
# 4) 탭 레이아웃
# =========================
@app.callback(
    Output('tabs-content', 'children'),
    Input('tabs', 'value')
)
def render_content(tab):
    if tab == 'tab-dashboard':
        return html.Div([
            # 컨트롤 - 수정된 부분
            html.Div([
                html.Div([
                    html.Label("날짜 선택:", style={'fontWeight': 'bold', 'marginRight': 10, 'display': 'inline-block', 'verticalAlign': 'middle', 'fontSize': '14px'}),
                    dcc.DatePickerSingle(
                        id='date-picker',
                        min_date_allowed=available_dates[0],
                        max_date_allowed=available_dates[-1],
                        initial_visible_month=latest_date,
                        date=latest_date,
                        display_format='YYYY-MM-DD',
                        style={'display': 'inline-block', 'verticalAlign': 'middle', 'fontSize': '14px'}
                    )
                ], style={'display': 'inline-block', 'marginRight': 40}),
                
                html.Div([
                    html.Label("펀드 선택:", style={'fontWeight': 'bold', 'marginRight': 10, 'display': 'inline-block', 'verticalAlign': 'middle', 'fontSize': '14px'}),
                    dcc.Dropdown(
                        id='fund-dropdown',
                        options=[{'label': f, 'value': f} for f in FUND_LIST],
                        value=FUND_LIST[0],
                        style={'width': '200px', 'display': 'inline-block', 'verticalAlign': 'middle', 'fontSize': '14px'}
                    ),
                    html.Span(id='fund-name-display', style={'marginLeft': '15px', 'display': 'inline-block', 'verticalAlign': 'middle', 'fontWeight': 'bold', 'fontSize': '14px', 'color': '#333'})
                ], style={'display': 'inline-block'})
            ], style={'textAlign': 'left', 'marginLeft': '30px', 'marginBottom': 30}),
            
            # 보유 종목 테이블
            html.Div([
                html.H3("보유 종목 내역", style={'textAlign': 'center'}),
                dash_table.DataTable(
                    id='holdings-table',
                    style_cell={
                        'textAlign': 'center', 
                        'padding': '8px', 
                        'fontSize': '12px',
                        'whiteSpace': 'normal',
                        'height': 'auto'
                    },
                    style_header={
                        'backgroundColor': '#4CAF50', 
                        'fontWeight': 'bold', 
                        'color': 'white',
                        'border': '1px solid white'
                    },
                    style_data_conditional=[
                        # Zebra striping
                        {
                            'if': {'row_index': 'odd'},
                            'backgroundColor': 'rgb(248, 248, 248)'
                        },
                        # 소계 행 강조
                        {
                            'if': {'filter_query': '{_is_subtotal} = true'},
                            'backgroundColor': '#FFE082',
                            'fontWeight': 'bold',
                            'borderTop': '2px solid #FF6F00',
                            'borderBottom': '2px solid #FF6F00'
                        }
                    ],
                    page_size=50,
                    sort_action='native',
                    filter_action='native'
                )
            ], style={'marginBottom': 30}),
            
            # 시계열 차트
            html.Div([
                dcc.Graph(id='area-chart')
            ], style={'marginTop': 20}),
            
            # 수익률 차트
            html.Div([
                dcc.Graph(id='performance-chart')
            ], style={'marginTop': 20}),
            
            # 자산배분 상세
            html.Div([
                html.H3("자산배분 상세", style={'textAlign': 'center'}),
                dash_table.DataTable(
                    id='allocation-table',
                    style_cell={'textAlign': 'center', 'padding': '8px'},
                    style_header={'backgroundColor': 'lightgrey', 'fontWeight': 'bold'},
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': 'rgb(248, 248, 248)'}
                    ]
                )
            ], style={'marginTop': 30, 'marginBottom': 50})
        ])
    
    elif tab == 'tab-pivot':
        # Pivot Table용 데이터 준비
        pivot_data = holding.copy()
        pivot_data['날짜'] = pivot_data['STD_DT'].astype(str)
        pivot_data['금액(억)'] = (pivot_data['EVL_AMT'] / 100_000_000).round(2)
        pivot_data['금액(원)'] = pivot_data['EVL_AMT'].astype(int)
        
        # PivotTable에 필요한 컬럼만 선택
        pivot_cols = ['날짜', 'FUND_CD', 'FUND_NM', '대분류', '지역', '소분류', 
                      'ITEM_NM', '금액(억)', '금액(원)']
        pivot_data = pivot_data[pivot_cols]
        
        return html.Div([
            html.Div([
                html.H2("🔍 인터랙티브 피봇 분석", style={'textAlign': 'center', 'marginBottom': 20}),
                html.P([
                    "💡 사용 팁: ",
                    html.Br(),
                    "• 좌측 필드를 드래그하여 행/열/값 영역에 배치하세요",
                    html.Br(),
                    "• Aggregator에서 집계 방식 선택 (Sum, Average, Count 등)",
                    html.Br(),
                    "• Renderer에서 표시 방식 선택 (Table, Heatmap, Bar Chart 등)"
                ], style={'textAlign': 'center', 'color': '#666', 'fontSize': 14, 'marginBottom': 30}),
            ]),
            
            html.Div([
                PivotTable(
                    id='pivot-table',
                    data=pivot_data.to_dict('records'),
                    cols=['대분류'],
                    rows=['FUND_NM'],
                    vals=['금액(억)'],
                    aggregatorName='Sum',
                    rendererName='Table',
                )
            ], style={'marginTop': 20})
        ])
    
    elif tab == 'tab-itemlist':
        return html.Div([
            html.H2("📋 종목 분류 리스트", style={'textAlign': 'center', 'marginBottom': 30}),
            
            html.Div(id='itemlist-status', style={'textAlign': 'center', 'marginBottom': 20}),
            
            # 종목 리스트
            html.Div([
                dash_table.DataTable(
                    id='item-list-table',
                    columns=[
                        {'name': '종목코드', 'id': 'ITEM_CD'},
                        {'name': '종목명', 'id': 'ITEM_NM'},
                        {'name': '대분류', 'id': '대분류'},
                        {'name': '지역', 'id': '지역'},
                        {'name': '소분류', 'id': '소분류'},
                        {'name': '1D(%)', 'id': '1D'},
                        {'name': '1W(%)', 'id': '1W'},
                        {'name': '1M(%)', 'id': '1M'},
                        {'name': '3M(%)', 'id': '3M'},
                        {'name': '6M(%)', 'id': '6M'},
                        {'name': '1Y(%)', 'id': '1Y'},
                        {'name': 'YTD(%)', 'id': 'YTD'},
                    ],
                    data=[],
                    style_cell={'textAlign': 'center', 'padding': '10px', 'fontSize': '13px'},
                    style_header={'backgroundColor': '#4CAF50', 'fontWeight': 'bold', 'color': 'white'},
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': 'rgb(248, 248, 248)'}
                    ],
                    page_size=50,
                    sort_action='native',
                    filter_action='native',
                    export_format='xlsx',
                    export_headers='display',
                )
            ], style={'marginBottom': 30}),
            
        ], style={'maxWidth': '1200px', 'margin': '0 auto'})

# =========================
# 5) 대시보드 콜백
# =========================

# 🆕 펀드명 표시 콜백
@app.callback(
    Output('fund-name-display', 'children'),
    Input('fund-dropdown', 'value')
)
def display_fund_name(fund_code):
    if fund_code in FUND_NAMES:
        return f"({FUND_NAMES[fund_code]})"
    return ""

@app.callback(
    [Output('holdings-table', 'data'),
     Output('holdings-table', 'columns'),
     Output('area-chart', 'figure'),
     Output('performance-chart', 'figure'),
     Output('allocation-table', 'data'),
     Output('allocation-table', 'columns')],
    [Input('date-picker', 'date'),
     Input('fund-dropdown', 'value')]
)
def update_dashboard(selected_date, selected_fund):
    # 날짜 변환
    if isinstance(selected_date, str):
        selected_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    
    # 필터링
    df_holding_selected = holding[
        (holding['STD_DT'] == selected_date) & 
        (holding['FUND_CD'] == selected_fund)
    ].copy()
    
    # 전체 금액
    total_amt = df_holding_selected['EVL_AMT'].sum()
    
    # 정렬 순서 정의
    category_order = {'주식': 1, '채권': 2, '모펀드': 3, '현금': 4, '대체': 5, '통화': 6, '기타': 7}
    
    df_holding_selected['대분류_순서'] = df_holding_selected['대분류'].map(category_order).fillna(99)
    
    # 정렬: 대분류 순서 → 비중 내림차순
    df_holding_selected = df_holding_selected.sort_values(
        ['대분류_순서', 'EVL_AMT'], 
        ascending=[True, False]
    )
    
    # 보유 종목 테이블 데이터 준비 (대분류 소계만)
    holdings_list = []
    current_category = None
    category_pct = 0

    # Check if return columns exist
    return_cols = ['1D', '1W', '1M', '3M', '6M', '1Y', 'YTD']
    has_return_data = all(col in df_holding_selected.columns for col in return_cols)

    def format_return(value):
        """Format return value for display"""
        if pd.isna(value):
            return ''
        try:
            return round(float(value), 2)
        except (ValueError, TypeError):
            return ''

    for idx, row in df_holding_selected.iterrows():
        # 대분류가 바뀌면 이전 대분류 소계 추가
        if current_category and row['대분류'] != current_category:
            subtotal_row = {
                '대분류': f'▶ {current_category} 소계',
                'ITEM_NM': '',
                '비중(%)': round(category_pct, 2),
                '_is_subtotal': True
            }
            # Add empty return columns
            for col in return_cols:
                subtotal_row[col] = ''
            holdings_list.append(subtotal_row)
            category_pct = 0

        # 현재 행 추가
        current_category = row['대분류']
        pct = (row['EVL_AMT'] / total_amt * 100) if total_amt > 0 else 0
        category_pct += pct

        item_row = {
            '대분류': row['대분류'],
            'ITEM_NM': row['ITEM_NM'],
            '비중(%)': round(pct, 2),
            '_is_subtotal': False
        }

        # Add return columns if available
        if has_return_data:
            for col in return_cols:
                item_row[col] = format_return(row.get(col))
        else:
            for col in return_cols:
                item_row[col] = ''

        holdings_list.append(item_row)

    # 마지막 대분류 소계 추가
    if current_category and category_pct > 0:
        subtotal_row = {
            '대분류': f'▶ {current_category} 소계',
            'ITEM_NM': '',
            '비중(%)': round(category_pct, 2),
            '_is_subtotal': True
        }
        for col in return_cols:
            subtotal_row[col] = ''
        holdings_list.append(subtotal_row)

    holdings_table_data = holdings_list

    holdings_table_columns = [
        {'name': '대분류', 'id': '대분류'},
        {'name': '종목명', 'id': 'ITEM_NM'},
        {'name': '비중(%)', 'id': '비중(%)'},
        {'name': '1D(%)', 'id': '1D'},
        {'name': '1W(%)', 'id': '1W'},
        {'name': '1M(%)', 'id': '1M'},
        {'name': '3M(%)', 'id': '3M'},
        {'name': '6M(%)', 'id': '6M'},
        {'name': '1Y(%)', 'id': '1Y'},
        {'name': 'YTD(%)', 'id': 'YTD'}
    ]
    
    # 소분류별 집계 (allocation table용)
    df_agg = df_holding_selected.groupby('소분류', as_index=False)['EVL_AMT'].sum()
    df_agg = df_agg[df_agg['EVL_AMT'] > 0].sort_values('EVL_AMT', ascending=False)
    df_agg['비중%'] = (df_agg['EVL_AMT'] / df_agg['EVL_AMT'].sum() * 100).round(2)
    df_agg['EVL_AMT_억'] = (df_agg['EVL_AMT'] / 100_000_000).round(2)
    
    # 시계열 스택 영역차트
    df_timeseries = holding[holding['FUND_CD'] == selected_fund].copy()
    df_ts_agg = df_timeseries.groupby(['STD_DT', '소분류'], as_index=False)['EVL_AMT'].sum()
    df_pivot = df_ts_agg.pivot(index='STD_DT', columns='소분류', values='EVL_AMT').fillna(0)
    
    fig_area = go.Figure()
    for col in df_pivot.columns:
        fig_area.add_trace(go.Scatter(
            x=df_pivot.index,
            y=df_pivot[col],
            mode='lines',
            name=col,
            stackgroup='one',
            hovertemplate='<b>%{fullData.name}</b><br>%{y:,.0f}원<extra></extra>'
        ))
    fig_area.update_layout(
        title='자산배분 추이',
        xaxis_title='날짜',
        yaxis_title='평가금액 (원)',
        height=400,
        hovermode='x unified',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    # 수익률/NAV 차트
    df_metrics_fund = metrics[metrics['FUND_CD'] == selected_fund].copy()
    
    fig_perf = make_subplots(
        rows=2, cols=1,
        subplot_titles=('누적수익률', 'NAV 추이'),
        vertical_spacing=0.12,
        row_heights=[0.5, 0.5]
    )
    
    fig_perf.add_trace(
        go.Scatter(
            x=df_metrics_fund['STD_DT'], 
            y=df_metrics_fund['RET'],
            mode='lines',
            name='수익률',
            line=dict(color='#4ECDC4', width=2),
            hovertemplate='%{x}<br>수익률: %{y:.2f}%<extra></extra>'
        ),
        row=1, col=1
    )
    
    fig_perf.add_trace(
        go.Scatter(
            x=df_metrics_fund['STD_DT'], 
            y=df_metrics_fund['NAST_AMT'] / 100_000_000,
            mode='lines',
            name='NAV',
            line=dict(color='#FF6B6B', width=2),
            fill='tozeroy',
            hovertemplate='%{x}<br>NAV: %{y:,.0f}억원<extra></extra>'
        ),
        row=2, col=1
    )
    
    fig_perf.update_xaxes(title_text="날짜", row=2, col=1)
    fig_perf.update_yaxes(title_text="수익률 (%)", row=1, col=1)
    fig_perf.update_yaxes(title_text="NAV (억원)", row=2, col=1)
    fig_perf.update_layout(height=500, showlegend=False)
    
    # 테이블
    table_data = df_agg[['소분류', 'EVL_AMT_억', '비중%']].to_dict('records')
    table_columns = [
        {'name': '소분류', 'id': '소분류'},
        {'name': '금액 (억원)', 'id': 'EVL_AMT_억'},
        {'name': '비중 (%)', 'id': '비중%'}
    ]
    
    return holdings_table_data, holdings_table_columns, fig_area, fig_perf, table_data, table_columns

# =========================
# 6) 종목 리스트 탭 콜백
# =========================
@app.callback(
    [Output('item-list-table', 'data'),
     Output('itemlist-status', 'children')],
    Input('tabs', 'value')
)
def update_item_list(tab):
    if tab != 'tab-itemlist':
        return [], ""
    
    # 마스터 테이블 로드
    master = load_master_mapping()
    
    if master.empty:
        status = html.Div(
            "⚠️ 등록된 종목이 없습니다",
            style={'color': 'orange', 'fontSize': 18, 'fontWeight': 'bold'}
        )
        return [], status
    
    # Merge return data if available
    master_with_returns = master.merge(return_periods, on='ITEM_CD', how='left')

    # 종목 리스트 데이터 준비
    item_list = master_with_returns[['ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류',
                                       '1D', '1W', '1M', '3M', '6M', '1Y', 'YTD']].copy()
    item_list = item_list.sort_values(['대분류', '지역', '소분류', 'ITEM_NM'])

    # Replace NaN with empty string for display
    for col in ['1D', '1W', '1M', '3M', '6M', '1Y', 'YTD']:
        item_list[col] = item_list[col].apply(lambda x: x if pd.notna(x) else '')

    data = item_list.to_dict('records')
    
    status = html.Div(
        f"✅ 총 {len(item_list)}개 종목이 등록되어 있습니다",
        style={'color': 'green', 'fontSize': 18, 'fontWeight': 'bold'}
    )
    
    return data, status

# =========================
# 7) Run
# =========================
if __name__ == '__main__':
    print("\n" + "="*80)
    print("자산배분 대시보드 시작")
    print("="*80)
    print(f"마스터 종목 수: {len(master_mapping)}")
    print(f"미분류 종목 수: {len(unmapped)}")
    print(f"대시보드 URL: http://127.0.0.1:8050")
    print("="*80 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=8050)