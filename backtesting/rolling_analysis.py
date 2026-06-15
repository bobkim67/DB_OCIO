"""
rt7_20260430 롤링수익률 분석
- 손실확률: 다중 horizon 표 (숫자)
- 7% 이상(연환산) 확률: 스파게티차트
"""
from pathlib import Path
import pandas as pd
import numpy as np
import plotly.graph_objects as go

ROOT = Path(__file__).parent
SRC = ROOT / "rt7_20260430"
TRADING_DAYS = 252

HORIZONS = {
    "1M":  21,
    "3M":  63,
    "6M":  126,
    "1Y":  252,
    "2Y":  504,
    "3Y":  756,
    "5Y":  1260,
}

COLS = ["BM", "SAA", "TAA", "AP"]
COLOR = {"BM": "#7f7f7f", "SAA": "#1f77b4", "TAA": "#2ca02c", "AP": "#d62728"}


def load_prices() -> pd.DataFrame:
    df = pd.read_csv(SRC, sep="\t", thousands=",", na_values=[""])
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"])
    for c in COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=COLS).set_index("Date").sort_index()[COLS]


def rolling_returns(prices: pd.Series, window: int) -> pd.Series:
    """기간말 / 기간초 - 1 (연환산 변환 전 raw period return)."""
    return prices.pct_change(window).dropna()


def annualize(period_ret: pd.Series, window: int) -> pd.Series:
    return (1.0 + period_ret) ** (TRADING_DAYS / window) - 1.0


def main():
    px = load_prices()

    loss_tbl = pd.DataFrame(index=list(HORIZONS.keys()), columns=COLS, dtype=float)
    ge7_tbl = pd.DataFrame(index=list(HORIZONS.keys()), columns=COLS, dtype=float)
    n_tbl = pd.DataFrame(index=list(HORIZONS.keys()), columns=COLS, dtype=int)

    for h_name, w in HORIZONS.items():
        for c in COLS:
            r = rolling_returns(px[c], w)
            ann = annualize(r, w)
            n = len(r)
            loss_tbl.loc[h_name, c] = (r < 0).sum() / n * 100.0
            ge7_tbl.loc[h_name, c] = (ann >= 0.07).sum() / n * 100.0
            n_tbl.loc[h_name, c] = n

    loss_tbl = loss_tbl.round(2)
    ge7_tbl = ge7_tbl.round(2)

    print("=" * 70)
    print(f"데이터 기간: {px.index[0].date()} ~ {px.index[-1].date()}  (n={len(px):,} 일)")
    print("=" * 70)
    print("\n[손실확률] 롤링 기간말 수익률 < 0 인 비율 (%)")
    print(loss_tbl.to_string())
    print("\n[7% 이상(연환산) 확률] (%)")
    print(ge7_tbl.to_string())
    print("\n[샘플 수] 롤링 윈도우 개수")
    print(n_tbl.to_string())

    out_csv = ROOT / "rolling_summary.csv"
    summary = pd.concat(
        {"loss_pct": loss_tbl, "ge7_ann_pct": ge7_tbl, "n_samples": n_tbl},
        axis=1,
    )
    summary.to_csv(out_csv, encoding="utf-8-sig")
    print(f"\n저장: {out_csv}")

    fig = go.Figure()
    x_labels = list(HORIZONS.keys())
    for c in COLS:
        fig.add_trace(
            go.Scatter(
                x=x_labels,
                y=ge7_tbl[c].values,
                mode="lines+markers+text",
                name=c,
                line=dict(width=2.5, color=COLOR[c]),
                marker=dict(size=10),
                text=[f"{v:.1f}" for v in ge7_tbl[c].values],
                textposition="top center",
                textfont=dict(size=10),
            )
        )
    fig.update_layout(
        title="롤링 horizon별 연환산 수익률 ≥ 7% 발생확률",
        xaxis_title="롤링 기간 (영업일 환산: 1M=21d ... 5Y=1260d)",
        yaxis_title="확률 (%)",
        yaxis=dict(range=[0, 105], ticksuffix="%"),
        template="plotly_white",
        height=520,
        legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
        hovermode="x unified",
    )
    out_html = ROOT / "ge7_probability_spaghetti.html"
    fig.write_html(str(out_html), include_plotlyjs="cdn")
    print(f"저장: {out_html}")


if __name__ == "__main__":
    main()
