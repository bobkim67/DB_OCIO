"""
AP 침체 weight 조정 시나리오 백테스트.
- baseline: 역추정된 현 AP weight (장기채 29.7% 듀레이션 확대)
- 시나리오 A~D: 듀레이션 확대 강도 ↓ / 위험자산 추가 축소 / 혼합
- regime != 3 에서는 모든 시나리오 SAA weight 사용 (사용자 명시)
"""
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).parent
SRC = ROOT / "rt7_20260430"

ASSETS = ["미국성장주", "국내주식", "미국국채", "미국외국채",
          "미국HY", "국내중기채", "국내장기채", "금"]
RF = 0.025
TRADING = 252


def load() -> pd.DataFrame:
    df = pd.read_csv(SRC, sep="\t", thousands=",", na_values=[""])
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"])
    for c in ASSETS + ["BM", "SAA", "TAA", "AP"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Regime"] = pd.to_numeric(df["Regime"], errors="coerce").astype("Int64")
    return df.dropna(subset=["SAA"]).set_index("Date").sort_index()


# 진단 회귀로 추정된 weight (R²>=0.9995, 사실상 실제 weight)
W_SAA = pd.Series({
    "미국성장주": 0.244, "국내주식": 0.046, "미국국채": 0.0, "미국외국채": 0.0,
    "미국HY": 0.070, "국내중기채": 0.400, "국내장기채": 0.077, "금": 0.163,
})
W_TAA_REC = pd.Series({
    "미국성장주": 0.194, "국내주식": 0.026, "미국국채": 0.074, "미국외국채": 0.075,
    "미국HY": 0.000, "국내중기채": 0.420, "국내장기채": 0.077, "금": 0.133,
})
W_AP_REC = pd.Series({
    "미국성장주": 0.194, "국내주식": 0.026, "미국국채": 0.075, "미국외국채": 0.075,
    "미국HY": 0.000, "국내중기채": 0.200, "국내장기채": 0.297, "금": 0.133,
})

# 시나리오: 침체 시 weight (비침체 = SAA 동일)
# 듀레이션 확대 강도와 위험자산 축소 강도를 조합
SCENARIOS = {
    "AP_orig": W_AP_REC,
    # A: 듀레이션 확대 약화 (장기채 29.7→22, 중기채 20→27.7)
    "AP_A_mildDur": pd.Series({
        "미국성장주": 0.194, "국내주식": 0.026, "미국국채": 0.075, "미국외국채": 0.075,
        "미국HY": 0.000, "국내중기채": 0.277, "국내장기채": 0.220, "금": 0.133,
    }),
    # B: 듀레이션 확대 추가 약화 (장기채 18%, 중기채 31.7%)
    "AP_B_lightDur": pd.Series({
        "미국성장주": 0.194, "국내주식": 0.026, "미국국채": 0.075, "미국외국채": 0.075,
        "미국HY": 0.000, "국내중기채": 0.317, "국내장기채": 0.180, "금": 0.133,
    }),
    # C: 위험자산 추가축소(-5%p) + 가벼운 듀레이션 확대 (장기채 18, 중기채 36.7)
    "AP_C_riskCut+lightDur": pd.Series({
        "미국성장주": 0.144, "국내주식": 0.010, "미국국채": 0.075, "미국외국채": 0.075,
        "미국HY": 0.000, "국내중기채": 0.367, "국내장기채": 0.180, "금": 0.149,
    }),
    # D: TAA식 위험자산축소 + 듀레이션 mid (장기채 22, 중기채 32)
    "AP_D_TAArisk+midDur": pd.Series({
        "미국성장주": 0.194, "국내주식": 0.026, "미국국채": 0.075, "미국외국채": 0.075,
        "미국HY": 0.000, "국내중기채": 0.320, "국내장기채": 0.220, "금": 0.090,
    }),
}
for k, w in SCENARIOS.items():
    assert abs(w.sum() - 1) < 1e-6, f"{k} weights sum != 1: {w.sum()}"


def backtest(asset_ret: pd.DataFrame, regime: pd.Series,
             w_normal: pd.Series, w_recession: pd.Series) -> pd.Series:
    w_normal = w_normal.reindex(ASSETS).fillna(0).values
    w_recession = w_recession.reindex(ASSETS).fillna(0).values
    is_rec = (regime == 3).reindex(asset_ret.index).fillna(False).values
    W = np.where(is_rec[:, None], w_recession, w_normal)
    port_ret = (asset_ret.values * W).sum(axis=1)
    nav = (1 + pd.Series(port_ret, index=asset_ret.index)).cumprod() * 100
    return nav


def stats(nav: pd.Series) -> dict:
    nav = nav.dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1
    ret = nav.pct_change().dropna()
    vol = ret.std(ddof=1) * np.sqrt(TRADING)
    sharpe = (cagr - RF) / vol
    dd = nav / nav.cummax() - 1
    mdd = dd.min()
    return {
        "CAGR(%)": round(cagr * 100, 2),
        "Vol(%)": round(vol * 100, 2),
        "Sharpe": round(sharpe, 3),
        "MDD(%)": round(mdd * 100, 2),
        "MDD일": dd.idxmin().strftime("%Y-%m-%d"),
        "Calmar": round(cagr / abs(mdd), 3),
    }


def main():
    df = load()
    asset_ret = df[ASSETS].pct_change().fillna(0)

    # 1) 원본 AP / TAA / SAA / BM (파일 그대로) 비교 기준
    base_stats = {}
    for p in ["BM", "SAA", "TAA", "AP"]:
        base_stats[p] = stats(df[p])

    # 2) 재구성: SAA weight 로 비침체, 시나리오 weight 로 침체
    nav_dict = {"AP_orig(file)": df["AP"], "TAA(file)": df["TAA"], "SAA(file)": df["SAA"]}
    sc_stats = {}
    for name, w_rec in SCENARIOS.items():
        nav = backtest(asset_ret, df["Regime"], W_SAA, w_rec)
        nav_dict[name] = nav
        sc_stats[name] = stats(nav)

    rows = []
    for k, s in base_stats.items():
        rows.append({"strategy": f"{k} (file)", **{kk: vv for kk, vv in s.items() if kk != "MDD_date"}})
    # rename for stats() dict
    def _row(k, s): return {"strategy": k, **s}
    for k, s in sc_stats.items():
        rows.append(_row(k, s))
    out_df = pd.DataFrame(rows)
    print("=== 전체기간 성과 (RF=2.5%) ===")
    print(out_df.to_string(index=False))

    # 2022~2023 zoom
    print("\n=== 2022-01 ~ 2023-06 (채권 폭락기) MDD ===")
    z_rows = []
    sub_navs = {**nav_dict}
    for name, nav in sub_navs.items():
        z = nav.loc["2022-01-03":"2023-06-30"]
        zdd = (z / z.cummax() - 1).min()
        z_rows.append({"strategy": name, "MDD(%)": round(zdd * 100, 2)})
    print(pd.DataFrame(z_rows).to_string(index=False))

    out_csv = ROOT / "scenario_results.csv"
    out_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out_csv}")

    # NAV + DD 차트
    fig = go.Figure()
    palette = {
        "AP_orig(file)": "#d62728", "TAA(file)": "#2ca02c", "SAA(file)": "#1f77b4",
        "AP_orig": "#d62728", "AP_A_mildDur": "#ff7f0e",
        "AP_B_lightDur": "#9467bd", "AP_C_riskCut+lightDur": "#17becf",
        "AP_D_TAArisk+midDur": "#8c564b",
    }
    for name, nav in nav_dict.items():
        if name == "AP_orig":  # 중복 (file 과 동일하므로 제외)
            continue
        fig.add_trace(go.Scatter(
            x=nav.index, y=nav, name=name, mode="lines",
            line=dict(color=palette.get(name, "#000"),
                      width=2 if "file" in name else 1.5,
                      dash="solid" if "file" in name else "dot"),
        ))
    fig.update_layout(
        title="AP 침체 weight 시나리오 — NAV (log)", template="plotly_white",
        height=560, yaxis_type="log", hovermode="x unified",
        legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
    )
    out_html = ROOT / "scenario_nav.html"
    fig.write_html(str(out_html), include_plotlyjs="cdn")
    print(f"저장: {out_html}")

    # DD 차트
    fig2 = go.Figure()
    for name, nav in nav_dict.items():
        if name == "AP_orig":
            continue
        dd = (nav / nav.cummax() - 1) * 100
        fig2.add_trace(go.Scatter(
            x=dd.index, y=dd, name=name, mode="lines",
            line=dict(color=palette.get(name, "#000"),
                      width=2 if "file" in name else 1.5,
                      dash="solid" if "file" in name else "dot"),
        ))
    fig2.update_layout(
        title="AP 침체 weight 시나리오 — Drawdown (%)", template="plotly_white",
        height=520, hovermode="x unified",
        legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
    )
    out_html2 = ROOT / "scenario_dd.html"
    fig2.write_html(str(out_html2), include_plotlyjs="cdn")
    print(f"저장: {out_html2}")


if __name__ == "__main__":
    main()
