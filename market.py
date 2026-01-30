import json
from datetime import timedelta
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from dash import Dash, dcc, html, Input, Output
import plotly.express as px

# ============================================================
# 0) DB Connection
# ============================================================
CONN_STR = "mysql+pymysql://solution:Solution123!@192.168.195.55/SCIP?charset=utf8mb4"
engine = create_engine(CONN_STR)

SOURCE_ID = 3

# ============================================================
# 1) Mapping (dataset_id 기반)
# ============================================================
DATASET_MAPPING = {
    # Equity (주식)
    24:  {"asset1": "주식", "asset2": "미국",   "style": "일반", "display_name": "S&P 500 (미국)",           "include": True},
    36:  {"asset1": "주식", "asset2": "선진국", "style": "일반", "display_name": "Vanguard DM (선진국)",      "include": True},
    63:  {"asset1": "주식", "asset2": "선진국", "style": "일반", "display_name": "MSCI EAFE (선진국 ex-US)",  "include": True},
    66:  {"asset1": "주식", "asset2": "선진국", "style": "일반", "display_name": "MSCI Japan (일본)",         "include": True},
    37:  {"asset1": "주식", "asset2": "신흥국", "style": "일반", "display_name": "Vanguard EM (신흥국)",      "include": True},
    64:  {"asset1": "주식", "asset2": "신흥국", "style": "일반", "display_name": "MSCI EM (신흥국)",          "include": True},
    114: {"asset1": "주식", "asset2": "미국",   "style": "성장", "display_name": "SPDR S&P500 Growth",        "include": True},
    116: {"asset1": "주식", "asset2": "미국",   "style": "가치", "display_name": "SPDR S&P500 Value",         "include": True},
    144:  {"asset1": "주식", "asset2": "국내",   "style": "일반", "display_name": "MSCI KR (국내)",          "include": True},

    # FX (환율) - 필요 시 확장
    31:  {"asset1": "FX",   "asset2": "환율",   "style": "USDKRW", "display_name": "USD/KRW",                "include": True},
}

# ============================================================
# 2) Data Loading
#   - 필요한 dataseries_id만: TR(6), PE(24), EPS(31)
# ============================================================
DS_TR = 6
DS_PE = 24
DS_EPS = 31

def _coerce_number(v):
    if isinstance(v, str):
        v = v.replace(",", "")
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def parse_data_blob(blob):
    if blob is None:
        return None
    if isinstance(blob, (bytes, bytearray)):
        s = blob.decode("utf-8")
    else:
        s = str(blob)
    s = s.strip()

    if s.startswith("{") or s.startswith("["):
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            return s

        if isinstance(obj, dict):
            return {k: _coerce_number(v) for k, v in obj.items()}
        return obj

    return _coerce_number(s)


def load_source3_needed(start_date: str | None = None) -> pd.DataFrame:
    """
    source_id=3에서 TR/PE/EPS 데이터를 가져와서 long->wide로 정리.
    - start_date: 'YYYY-MM-DD' (없으면 전체)
    """
    where_date = ""
    params = {"source_id": SOURCE_ID, "ds_tr": DS_TR, "ds_pe": DS_PE, "ds_eps": DS_EPS}

    if start_date:
        where_date = "AND dp.timestamp_observation >= :start_date"
        params["start_date"] = start_date

    q = text(f"""
    SELECT
        dp.timestamp_observation,
        dp.dataseries_id,
        ds.name AS dataseries_name,
        dp.dataset_id,
        d.name AS dataset_name,
        dp.data
    FROM SCIP.back_datapoint dp
    JOIN SCIP.back_dataseries ds ON dp.dataseries_id = ds.id
    LEFT JOIN SCIP.back_dataset d ON dp.dataset_id = d.id
    WHERE ds.source_id = :source_id
      AND dp.dataseries_id IN (:ds_tr, :ds_pe, :ds_eps)
      {where_date}
    ORDER BY dp.timestamp_observation, dp.dataseries_id, dp.dataset_id
    """)

    with engine.connect() as conn:
        df_raw = pd.read_sql(q, conn, params=params)

    # parse -> long
    records = []
    for row in df_raw.itertuples(index=False):
        parsed = parse_data_blob(row.data)
        base = {
            "date": pd.to_datetime(row.timestamp_observation).normalize(),
            "dataseries_id": int(row.dataseries_id),
            "dataseries_name": row.dataseries_name,
            "dataset_id": int(row.dataset_id) if row.dataset_id is not None else None,
            "dataset_name": row.dataset_name,
        }
        if isinstance(parsed, dict):
            for k, v in parsed.items():
                records.append({**base, "field": k, "value": v})
        else:
            records.append({**base, "field": "value", "value": parsed})

    df_long = pd.DataFrame(records)
    if df_long.empty:
        return df_long

    # pivot -> wide (KRW/USD/value 등 자동 컬럼 생성)
    df_wide = (
        df_long.pivot_table(
            index=["date", "dataseries_id", "dataseries_name", "dataset_id", "dataset_name"],
            columns="field",
            values="value",
            aggfunc="last",
        )
        .reset_index()
    )
    df_wide.columns.name = None
    return df_wide


def apply_mapping(df_wide: pd.DataFrame) -> pd.DataFrame:
    """
    dataset_id 기준으로 매핑 붙이고, 매핑 없는 건 include=False로 숨김 처리 가능하게 컬럼만 붙여둠
    """
    if df_wide.empty:
        return df_wide

    map_rows = []
    for did, meta in DATASET_MAPPING.items():
        meta2 = meta.copy()
        meta2["dataset_id"] = did
        map_rows.append(meta2)

    df_map = pd.DataFrame(map_rows)

    out = df_wide.merge(df_map, on="dataset_id", how="left")
    out["include"] = out["include"].fillna(False)
    out["display_name"] = out["display_name"].fillna("미분류")
    out["asset1"] = out["asset1"].fillna("미분류")
    out["asset2"] = out["asset2"].fillna("미분류")
    out["style"] = out["style"].fillna("미분류")
    return out


def pick_tr_value(row: pd.Series) -> float:
    """
    TR은 USD가 있으면 USD, 없으면 value 사용
    """
    if "USD" in row and pd.notna(row["USD"]):
        return float(row["USD"])
    if "value" in row and pd.notna(row["value"]):
        return float(row["value"])
    return np.nan


def first_on_or_after(g: pd.DataFrame, target_date: pd.Timestamp, col: str) -> float:
    gp = g[g["date"] >= target_date]
    if gp.empty:
        return np.nan
    return float(gp.iloc[0][col])

def calc_ytd_tr_return(df_mapped: pd.DataFrame) -> pd.DataFrame:
    df_tr = df_mapped[df_mapped["dataseries_id"] == DS_TR].copy()
    if df_tr.empty:
        return pd.DataFrame(columns=["dataset_id", "date", "tr_ytd"])

    df_tr["tr_index"] = df_tr.apply(pick_tr_value, axis=1)
    df_tr = df_tr.dropna(subset=["tr_index"])

    out_rows = []
    for did, g in df_tr.groupby("dataset_id"):
        g = g.sort_values("date")
        latest_date = g["date"].max()
        latest_val = g.loc[g["date"] == latest_date, "tr_index"].iloc[-1]

        ytd_start = pd.Timestamp(year=latest_date.year, month=1, day=1)
        base_val = first_on_or_after(g, ytd_start, "tr_index")
        if pd.isna(base_val) or base_val == 0:
            out_rows.append({"dataset_id": did, "date": latest_date, "tr_ytd": np.nan})
            continue

        tr_ytd = (latest_val / base_val - 1.0) * 100.0
        out_rows.append({"dataset_id": did, "date": latest_date, "tr_ytd": float(tr_ytd)})

    return pd.DataFrame(out_rows)

METRICS = ["12M Fwd P/E", "12M Fwd EPS"]
# 예: df_wide 컬럼
# ['timestamp_observation','dataseries_id','dataseries_name','dataset_id','dataset_name', 'value', 'USD','KRW', ...]

def calc_ytd_growth_from_level(df_equity: pd.DataFrame, ds_id: int, col_name: str) -> pd.DataFrame:
    """
    ds_id(PE/EPS) 레벨 시계열로부터 YTD growth(%) 계산
    반환: dataset_id, date(최신일), {col_name}  (ex. eps_g_ytd, pe_g_ytd)
    """
    t = df_equity[df_equity["dataseries_id"] == ds_id].copy()
    if t.empty:
        return pd.DataFrame(columns=["dataset_id", "date", col_name])

    t["lvl"] = pd.to_numeric(t["value"], errors="coerce")
    t = t.dropna(subset=["lvl"]).sort_values(["dataset_id", "date"])

    out = []
    for did, g in t.groupby("dataset_id"):
        g = g.sort_values("date")
        latest_date = g["date"].max()
        latest_lvl = g.loc[g["date"] == latest_date, "lvl"].iloc[-1]

        ytd_start = pd.Timestamp(year=latest_date.year, month=1, day=1)
        base_lvl = first_on_or_after(g, ytd_start, "lvl")

        if pd.isna(base_lvl) or base_lvl == 0:
            out.append({"dataset_id": did, "date": latest_date, col_name: np.nan})
            continue

        out.append({"dataset_id": did, "date": latest_date, col_name: (latest_lvl / base_lvl - 1.0) * 100.0})

    return pd.DataFrame(out)


def build_ytd_decomposition(df_equity: pd.DataFrame) -> pd.DataFrame:
    """
    TR(YTD)을 EPS growth, PE growth, Other로 분해.
    - eps_g_ytd = EPS 레벨의 YTD growth
    - pe_g_ytd  = PE 레벨의 YTD growth
    - other_ytd = TR_ytd - (eps+pe로 설명되는 부분) 을 곱셈 구조로 잔차 산출
      other = (1+TR)/( (1+eps)*(1+pe) ) - 1
    """
    # TR(YTD)
    tr = calc_ytd_tr_return(df_equity).rename(columns={"tr_ytd": "tr_ytd"})

    # EPS/PE YTD growth
    eps_g = calc_ytd_growth_from_level(df_equity, DS_EPS, "eps_g_ytd")
    pe_g  = calc_ytd_growth_from_level(df_equity, DS_PE,  "pe_g_ytd")

    # latest snapshot label 붙이기용(표시명)
    latest_lbl = (
        df_equity[["dataset_id", "display_name"]]
        .drop_duplicates()
    )

    d = tr.merge(eps_g[["dataset_id", "eps_g_ytd"]], on="dataset_id", how="left") \
          .merge(pe_g[["dataset_id", "pe_g_ytd"]], on="dataset_id", how="left") \
          .merge(latest_lbl, on="dataset_id", how="left")

    # other 계산 (퍼센트 -> 소수)
    def _other(row):
        trr  = row["tr_ytd"]
        epsg = row["eps_g_ytd"]
        peg  = row["pe_g_ytd"]
        if pd.isna(trr) or pd.isna(epsg) or pd.isna(peg):
            return np.nan
        trr, epsg, peg = trr/100.0, epsg/100.0, peg/100.0
        return ((1.0 + trr) / ((1.0 + epsg) * (1.0 + peg)) - 1.0) * 100.0

    d["other_ytd"] = d.apply(_other, axis=1)
    return d[["dataset_id", "display_name", "tr_ytd", "eps_g_ytd", "pe_g_ytd", "other_ytd"]]


def build_valuation_df(df_wide: pd.DataFrame, dataset_mapping: dict) -> pd.DataFrame:
    df = df_wide.copy()

    # timestamp 정리
    df["date"] = pd.to_datetime(df["date"])

    # PE/EPS만
    df = df[df["dataseries_name"].isin(METRICS)].copy()

    # value만 쓰기로 했으니 value가 숫자 아니면 정리
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # 매핑 붙이기 (dataset_id 기준)
    map_df = (
        pd.DataFrame.from_dict(dataset_mapping, orient="index")
        .reset_index()
        .rename(columns={"index": "dataset_id"})
    )

    df = df.merge(map_df, on="dataset_id", how="left")

    # 매핑에 없는 건 숨김(include True만)
    df = df[df["include"] == True].copy()

    # 표시용 라벨 (드롭다운)
    df["label"] = df["display_name"].fillna(df["dataset_name"])

    return df

# ============================================================
# 3) Load once (간단 버전: 앱 시작 시 로딩)
#    - 필요하면 start_date만 바꿔서 리로딩 구조로 확장 가능
# ============================================================
START_DATE = None  # 예: "2020-01-01"
df_wide = load_source3_needed(start_date=START_DATE)
df = apply_mapping(df_wide)

# 매핑된(보이는) 주식만 기본 대상으로
df_equity = df[(df["include"]) & (df["asset1"] == "주식")].copy()

# 최신일 스냅샷(PE/EPS 기준)
def latest_snapshot(df_in: pd.DataFrame, ds_id: int) -> pd.DataFrame:
    t = df_in[df_in["dataseries_id"] == ds_id].copy()
    if t.empty:
        return t
    # dataset_id별 최신 1행
    t = (
        t.sort_values("date")
         .drop_duplicates(subset=["dataset_id"], keep="last")
    )
    return t

snap_pe = latest_snapshot(df_equity, DS_PE)[["dataset_id", "display_name", "asset2", "style", "date", "value"]].rename(columns={"value": "pe"})
snap_eps = latest_snapshot(df_equity, DS_EPS)[["dataset_id", "date", "value"]].rename(columns={"value": "eps"})

snap = snap_pe.merge(snap_eps, on=["dataset_id", "date"], how="outer")
trytd = calc_ytd_tr_return(df_equity)
snap = snap.merge(trytd[["dataset_id", "tr_ytd"]], on="dataset_id", how="left")


# ============================================================
# 4) Dash App
# ============================================================
app = Dash(__name__)
app.title = "Valuation Panel (source_id=3)"

asset2_options = [{"label": a, "value": a} for a in sorted(df_equity["asset2"].dropna().unique())]

def make_item_options():
    items = (
        df_equity[["dataset_id", "display_name"]]
        .drop_duplicates()
        .sort_values("display_name")
    )
    return [{"label": r.display_name, "value": int(r.dataset_id)} for r in items.itertuples(index=False)]

item_options = make_item_options()
default_items = [144]

app.layout = html.Div(
    style={"maxWidth": "1300px", "margin": "0 auto", "padding": "16px"},
    children=[
        html.H2("7️⃣ 주식 밸류에이션 패널 (PE & EPS + 6M TR Scatter)"),

        html.Div(
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr", "gap": "12px"},
            children=[
                html.Div([
                    html.Div("보고 싶은 항목(복수 선택)"),
                    dcc.Dropdown(
                        id="items_dd",
                        options=make_item_options(),
                        value=default_items,
                        multi=True,
                    )
                ]),
            ],
        ),

        html.Hr(),

        html.Div(
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"},
            children=[
                dcc.Graph(id="pe_line"),
                dcc.Graph(id="eps_line"),
            ],
        ),
        html.Div(style={"marginTop": "12px"}, children=[
            dcc.Graph(id="decomp_bar"),
        ]),

        # 간단 표(원하면 DataTable로 바꿔도 됨)
        html.Div(id="decomp_table", style={"marginTop": "8px"}),

        html.Div(id="meta_text", style={"marginTop": "8px", "color": "#666"})
    ],
)
# ------------------------------------------------------------
# Callbacks
# ------------------------------------------------------------
@app.callback(
    Output("pe_line", "figure"),
    Output("eps_line", "figure"),
    Output("decomp_bar", "figure"),
    Output("decomp_table", "children"),
    Output("meta_text", "children"),
    Input("items_dd", "value"),
)
def render_charts(dataset_ids):
    dataset_ids = dataset_ids or []

    # 선택 종목만
    t = df_equity[df_equity["dataset_id"].isin(dataset_ids)].copy() if dataset_ids else df_equity.copy()

    # -------------------------
    # 1) PE / EPS 시계열
    # -------------------------
    t_pe = t[t["dataseries_id"] == DS_PE].copy()
    t_eps = t[t["dataseries_id"] == DS_EPS].copy()

    t_pe["value"] = pd.to_numeric(t_pe["value"], errors="coerce")
    t_eps["value"] = pd.to_numeric(t_eps["value"], errors="coerce")

    t_pe = t_pe.dropna(subset=["value"]).sort_values(["display_name", "date"])
    t_eps = t_eps.dropna(subset=["value"]).sort_values(["display_name", "date"])

    fig_pe = px.line(t_pe, x="date", y="value", color="display_name", title="12M Fwd P/E (Level)")
    fig_pe.update_layout(legend_title_text="", margin=dict(l=10, r=10, t=50, b=10))

    fig_eps = px.line(t_eps, x="date", y="value", color="display_name", title="12M Fwd EPS (Level)")
    fig_eps.update_layout(legend_title_text="", margin=dict(l=10, r=10, t=50, b=10))

    # -------------------------
    # 2) YTD 분해 (TR, EPS g, PE g, Other)
    # -------------------------
    decomp = build_ytd_decomposition(df_equity)
    if dataset_ids:
        decomp = decomp[decomp["dataset_id"].isin(dataset_ids)].copy()

    # 막대차트(종목별: eps/pe/other)
    decomp_long = decomp.melt(
        id_vars=["dataset_id", "display_name", "tr_ytd"],
        value_vars=["eps_g_ytd", "pe_g_ytd", "other_ytd"],
        var_name="component",
        value_name="pct",
    )
    comp_map = {"eps_g_ytd": "EPS growth (YTD)", "pe_g_ytd": "PE ratio growth (YTD)", "other_ytd": "Other (YTD)"}
    decomp_long["component"] = decomp_long["component"].map(comp_map).fillna(decomp_long["component"])

    fig_bar = px.bar(
        decomp_long,
        x="display_name",
        y="pct",
        color="component",
        barmode="relative",
        title="YTD 성과 분해 (TR ≈ EPS growth + PE ratio growth + Other)",
    )
    fig_bar.update_layout(xaxis_title="", yaxis_title="%p", margin=dict(l=10, r=10, t=50, b=10))

    # 간단 표(HTML)
    decomp_view = decomp.copy()
    for c in ["tr_ytd", "eps_g_ytd", "pe_g_ytd", "other_ytd"]:
        decomp_view[c] = decomp_view[c].map(lambda x: None if pd.isna(x) else round(float(x), 2))

    table = html.Table(
        style={"width": "100%", "borderCollapse": "collapse"},
        children=[
            html.Thead(html.Tr([
                html.Th("항목", style={"textAlign": "left", "borderBottom": "1px solid #ddd", "padding": "6px"}),
                html.Th("TR YTD(%)", style={"borderBottom": "1px solid #ddd", "padding": "6px"}),
                html.Th("EPS g YTD(%)", style={"borderBottom": "1px solid #ddd", "padding": "6px"}),
                html.Th("PE g YTD(%)", style={"borderBottom": "1px solid #ddd", "padding": "6px"}),
                html.Th("Other YTD(%)", style={"borderBottom": "1px solid #ddd", "padding": "6px"}),
            ])),
            html.Tbody([
                html.Tr([
                    html.Td(r["display_name"], style={"padding": "6px", "borderBottom": "1px solid #f0f0f0"}),
                    html.Td(r["tr_ytd"], style={"padding": "6px", "textAlign": "right", "borderBottom": "1px solid #f0f0f0"}),
                    html.Td(r["eps_g_ytd"], style={"padding": "6px", "textAlign": "right", "borderBottom": "1px solid #f0f0f0"}),
                    html.Td(r["pe_g_ytd"], style={"padding": "6px", "textAlign": "right", "borderBottom": "1px solid #f0f0f0"}),
                    html.Td(r["other_ytd"], style={"padding": "6px", "textAlign": "right", "borderBottom": "1px solid #f0f0f0"}),
                ])
                for r in decomp_view.sort_values("display_name").to_dict("records")
            ])
        ],
    )

    latest_date = pd.to_datetime(df_equity["date"]).max() if not df_equity.empty else None
    meta = f"선택 종목: {len(dataset_ids) if dataset_ids else df_equity['dataset_id'].nunique()}개 | 최신 기준일: {latest_date.date() if latest_date is not None else 'N/A'}"

    return fig_pe, fig_eps, fig_bar, table, meta

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)

