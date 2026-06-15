"""
rt7_20260430 진단:
- MDD, CAGR, Vol, Sharpe (RF=2.5%) for BM/SAA/TAA/AP
- regime별(침체=3 vs 그외) 기여도 분해
- TAA / AP 침체 allocation 역추정 (regression)
"""
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).parent
SRC = ROOT / "rt7_20260430"

ASSETS = ["미국성장주", "국내주식", "미국국채", "미국외국채",
          "미국HY", "국내중기채", "국내장기채", "금"]
PORTS = ["BM", "SAA", "TAA", "AP"]
PORT_COLOR = {"BM": "#7f7f7f", "SAA": "#1f77b4", "TAA": "#2ca02c", "AP": "#d62728"}
RF = 0.025
TRADING = 252


def load() -> pd.DataFrame:
    df = pd.read_csv(SRC, sep="\t", thousands=",", na_values=[""])
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"])
    for c in ASSETS + PORTS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Regime"] = pd.to_numeric(df["Regime"], errors="coerce").astype("Int64")
    df = df.dropna(subset=PORTS).set_index("Date").sort_index()
    return df


def perf_stats(nav: pd.Series, rf: float = RF) -> dict:
    nav = nav.dropna()
    ret = nav.pct_change().dropna()
    days = (nav.index[-1] - nav.index[0]).days
    years = days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1
    vol = ret.std(ddof=1) * np.sqrt(TRADING)
    sharpe = (cagr - rf) / vol if vol > 0 else np.nan
    rmax = nav.cummax()
    dd = nav / rmax - 1
    mdd = dd.min()
    mdd_date = dd.idxmin()
    peak_before = nav.loc[:mdd_date].idxmax()
    return {
        "CAGR": cagr, "Vol": vol, "Sharpe": sharpe,
        "MDD": mdd, "MDD_date": mdd_date, "MDD_peak": peak_before,
        "CalmarLike": cagr / abs(mdd) if mdd < 0 else np.nan,
        "Years": round(years, 2),
    }


def regime_decomp(df: pd.DataFrame, col: str) -> pd.DataFrame:
    ret = df[col].pct_change()
    out = []
    for r in [3, 1, 2, 4]:
        mask = df["Regime"] == r
        rr = ret[mask].dropna()
        if len(rr) == 0:
            continue
        ann_ret = rr.mean() * TRADING
        ann_vol = rr.std(ddof=1) * np.sqrt(TRADING)
        out.append({
            "regime": r,
            "days": int(mask.sum()),
            "ann_return": ann_ret,
            "ann_vol": ann_vol,
            "neg_day_pct": (rr < 0).mean() * 100,
        })
    return pd.DataFrame(out)


def infer_weights(df: pd.DataFrame, port: str, regime: int | None) -> pd.Series:
    """비음수 + 합=1 제약 NNLS 회귀로 가중치 추정."""
    from scipy.optimize import minimize
    asset_ret = df[ASSETS].pct_change()
    port_ret = df[port].pct_change()
    mask = df["Regime"] == regime if regime is not None else df["Regime"].notna()
    X = asset_ret[mask].dropna().values
    y = port_ret.loc[asset_ret[mask].dropna().index].values
    if len(X) < 30:
        return pd.Series(np.nan, index=ASSETS)
    n = X.shape[1]
    w0 = np.ones(n) / n

    def obj(w):
        return np.sum((X @ w - y) ** 2)

    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bnds = [(0, 1)] * n
    res = minimize(obj, w0, bounds=bnds, constraints=cons, method="SLSQP",
                   options={"maxiter": 500, "ftol": 1e-12})
    return pd.Series(res.x, index=ASSETS)


def main():
    df = load()
    print(f"기간: {df.index[0].date()} ~ {df.index[-1].date()}  n={len(df):,}")
    reg_counts = df["Regime"].value_counts().sort_index()
    print(f"Regime 분포: {dict(reg_counts)}  (3=침체 {reg_counts.get(3,0)}일, "
          f"{reg_counts.get(3,0)/len(df)*100:.1f}%)\n")

    rows = []
    for p in PORTS:
        s = perf_stats(df[p])
        rows.append({
            "포트": p,
            "CAGR(%)": f"{s['CAGR']*100:.2f}",
            "Vol(%)": f"{s['Vol']*100:.2f}",
            "Sharpe": f"{s['Sharpe']:.3f}",
            "MDD(%)": f"{s['MDD']*100:.2f}",
            "MDD일": s["MDD_date"].strftime("%Y-%m-%d"),
            "Calmar≈": f"{s['CalmarLike']:.3f}",
        })
    perf_df = pd.DataFrame(rows)
    print("=== 전체 기간 성과 (RF=2.5%) ===")
    print(perf_df.to_string(index=False))

    print("\n=== Regime별 연환산 평균수익률 / 변동성 / 음의일비중 ===")
    for p in PORTS:
        d = regime_decomp(df, p)
        d.insert(0, "포트", p)
        d["ann_return"] = (d["ann_return"] * 100).round(2)
        d["ann_vol"] = (d["ann_vol"] * 100).round(2)
        d["neg_day_pct"] = d["neg_day_pct"].round(1)
        print(d.to_string(index=False))
        print()

    print("=== SAA / TAA / AP 비중 역추정 (NNLS, sum=1, w>=0) ===")
    print("[비침체 (regime != 3)]")
    saa_w = infer_weights(df.assign(Regime=df["Regime"].where(df["Regime"] != 3, other=999)),
                          "SAA", 999)  # placeholder; we'll redo with explicit mask below
    # 명확화: 직접 mask
    asset_ret = df[ASSETS].pct_change()

    def _nnls(port: str, mask: pd.Series) -> pd.Series:
        from scipy.optimize import minimize
        X = asset_ret[mask].dropna().values
        idx = asset_ret[mask].dropna().index
        y = df[port].pct_change().loc[idx].values
        if len(X) < 30:
            return pd.Series(np.nan, index=ASSETS)
        n = X.shape[1]
        w0 = np.ones(n) / n
        res = minimize(
            lambda w: np.sum((X @ w - y) ** 2), w0,
            bounds=[(0, 1)] * n,
            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
            method="SLSQP", options={"maxiter": 1000, "ftol": 1e-14},
        )
        w = pd.Series(res.x, index=ASSETS)
        pred = asset_ret.loc[idx].values @ res.x
        r2 = 1 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2)
        w["_R2"] = r2
        return w

    non_rec = df["Regime"] != 3
    rec = df["Regime"] == 3
    weights_tbl = pd.DataFrame({
        "SAA(비침체)": _nnls("SAA", non_rec),
        "SAA(침체)": _nnls("SAA", rec),
        "TAA(비침체)": _nnls("TAA", non_rec),
        "TAA(침체)": _nnls("TAA", rec),
        "AP(비침체)": _nnls("AP", non_rec),
        "AP(침체)": _nnls("AP", rec),
    })
    weights_pct = weights_tbl.drop(index="_R2").apply(lambda c: (c * 100).round(1))
    weights_pct.loc["R²"] = weights_tbl.loc["_R2"].round(4)
    print(weights_pct.to_string())

    out_csv_perf = ROOT / "perf_summary.csv"
    out_csv_w = ROOT / "weights_inferred.csv"
    perf_df.to_csv(out_csv_perf, index=False, encoding="utf-8-sig")
    weights_pct.to_csv(out_csv_w, encoding="utf-8-sig")
    print(f"\n저장: {out_csv_perf}, {out_csv_w}")

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.6, 0.4],
        vertical_spacing=0.05,
        subplot_titles=("NAV (log scale)", "Drawdown"),
    )
    rec_blocks = []
    in_rec = False
    start = None
    for d, r in zip(df.index, df["Regime"]):
        if r == 3 and not in_rec:
            in_rec = True
            start = d
        elif r != 3 and in_rec:
            in_rec = False
            rec_blocks.append((start, d))
    if in_rec:
        rec_blocks.append((start, df.index[-1]))
    for s, e in rec_blocks:
        fig.add_vrect(x0=s, x1=e, fillcolor="rgba(200,0,0,0.08)",
                      line_width=0, row=1, col=1)
        fig.add_vrect(x0=s, x1=e, fillcolor="rgba(200,0,0,0.08)",
                      line_width=0, row=2, col=1)

    for p in PORTS:
        fig.add_trace(
            go.Scatter(x=df.index, y=df[p], name=p, mode="lines",
                       line=dict(color=PORT_COLOR[p], width=1.5)),
            row=1, col=1,
        )
        dd = df[p] / df[p].cummax() - 1
        fig.add_trace(
            go.Scatter(x=df.index, y=dd * 100, name=f"{p} DD", mode="lines",
                       line=dict(color=PORT_COLOR[p], width=1.2),
                       showlegend=False),
            row=2, col=1,
        )
    fig.update_yaxes(type="log", row=1, col=1)
    fig.update_yaxes(title="DD (%)", row=2, col=1)
    fig.update_layout(
        title=f"BM/SAA/TAA/AP — 침체구간 음영 (RF={RF*100:.1f}%)",
        template="plotly_white", height=720, hovermode="x unified",
        legend=dict(orientation="h", y=1.06, x=0.5, xanchor="center"),
    )
    out_html = ROOT / "nav_dd_regime.html"
    fig.write_html(str(out_html), include_plotlyjs="cdn")
    print(f"저장: {out_html}")


if __name__ == "__main__":
    main()
