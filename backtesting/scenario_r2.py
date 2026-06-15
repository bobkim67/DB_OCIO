"""
옵션 1 백테스트: AP만 regime=2(감속/late cycle)에도 defensive tilt.
규칙 완화 — 사용자 원안 "그 외는 SAA"를 일부 깨야 AP MDD < TAA MDD 가능.
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


W_SAA = pd.Series({
    "미국성장주": 0.244, "국내주식": 0.046, "미국국채": 0.0, "미국외국채": 0.0,
    "미국HY": 0.070, "국내중기채": 0.400, "국내장기채": 0.077, "금": 0.163,
})
# AP_C (앞 시나리오 권장안)
W_AP_C_REC = pd.Series({
    "미국성장주": 0.144, "국내주식": 0.010, "미국국채": 0.075, "미국외국채": 0.075,
    "미국HY": 0.000, "국내중기채": 0.367, "국내장기채": 0.180, "금": 0.149,
})

# Regime=2 (late-cycle) 일 때 AP defensive tilt 후보들
# 미국성장주 ↓, 국내중기채 ↑, 금 ↑ (rate 변화 영향 받기 전 위험자산 가벼운 축소)
LATE_CYCLE_AP = {
    "off": W_SAA,  # 비활성 — 기존 룰
    "tilt3": pd.Series({
        "미국성장주": 0.214, "국내주식": 0.046, "미국국채": 0.0, "미국외국채": 0.0,
        "미국HY": 0.070, "국내중기채": 0.420, "국내장기채": 0.077, "금": 0.173,
    }),  # -3%p 성장주, +2%p 중기채, +1%p 금
    "tilt5": pd.Series({
        "미국성장주": 0.194, "국내주식": 0.036, "미국국채": 0.0, "미국외국채": 0.0,
        "미국HY": 0.070, "국내중기채": 0.430, "국내장기채": 0.087, "금": 0.183,
    }),  # -5%p 성장주, -1%p 국내주식, +3%p 중기채, +1%p 장기채, +2%p 금
    "as_rec": W_AP_C_REC,  # regime=2 도 침체 weight 동일 적용 (가장 공격적 defensive)
}
for k, w in LATE_CYCLE_AP.items():
    assert abs(w.sum() - 1) < 1e-6, k


def backtest(asset_ret: pd.DataFrame, regime: pd.Series,
             w_others: pd.Series, w_r2: pd.Series, w_r3: pd.Series) -> pd.Series:
    r = regime.reindex(asset_ret.index).astype("Int64")
    w_oth = w_others.reindex(ASSETS).fillna(0).values
    w2 = w_r2.reindex(ASSETS).fillna(0).values
    w3 = w_r3.reindex(ASSETS).fillna(0).values
    is_r2 = (r == 2).values
    is_r3 = (r == 3).values
    W = np.tile(w_oth, (len(r), 1))
    W[is_r2] = w2
    W[is_r3] = w3
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
    return dict(CAGR=cagr * 100, Vol=vol * 100, Sharpe=sharpe,
                MDD=mdd * 100, MDD일=dd.idxmin().strftime("%Y-%m-%d"),
                Calmar=cagr / abs(mdd))


def main():
    df = load()
    asset_ret = df[ASSETS].pct_change().fillna(0)

    rows = []
    rows.append({"strategy": "TAA (file)", **stats(df["TAA"])})
    rows.append({"strategy": "AP (file)", **stats(df["AP"])})

    for name, w_r2 in LATE_CYCLE_AP.items():
        nav = backtest(asset_ret, df["Regime"],
                       w_others=W_SAA, w_r2=w_r2, w_r3=W_AP_C_REC)
        rows.append({"strategy": f"AP_C + R2={name}", **stats(nav)})

    out = pd.DataFrame(rows)
    out["CAGR"] = out["CAGR"].round(2)
    out["Vol"] = out["Vol"].round(2)
    out["Sharpe"] = out["Sharpe"].round(3)
    out["MDD"] = out["MDD"].round(2)
    out["Calmar"] = out["Calmar"].round(3)
    print("=== AP regime=2 tilt 백테스트 (RF=2.5%) ===")
    print(out.to_string(index=False))

    # 2020 COVID 구간 zoom
    print("\n=== 2020-02 ~ 2020-04 (COVID) MDD ===")
    z_rows = [{"strategy": "TAA (file)",
               "MDD(%)": round((df["TAA"].loc["2020-02-01":"2020-04-30"] /
                                df["TAA"].loc["2020-02-01":"2020-04-30"].cummax() - 1).min() * 100, 2)}]
    for name, w_r2 in LATE_CYCLE_AP.items():
        nav = backtest(asset_ret, df["Regime"], W_SAA, w_r2, W_AP_C_REC)
        z = nav.loc["2020-02-01":"2020-04-30"]
        z_rows.append({"strategy": f"AP_C+R2={name}",
                       "MDD(%)": round((z / z.cummax() - 1).min() * 100, 2)})
    print(pd.DataFrame(z_rows).to_string(index=False))


if __name__ == "__main__":
    main()
