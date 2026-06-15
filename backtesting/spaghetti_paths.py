"""
스파게티차트: AP 5Y 롤링 윈도우 각각의 누적수익률 path.
- 월말 NAV 기준 (daily → resample 'ME' last)
- 5Y = 60 개월
- 종착 ≥ 연환산 7% → 파스텔 스카이블루
- 그 외 → 파스텔 핑크
"""
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).parent
SRC = ROOT / "rt7_20260430"
TARGET = "AP"
YEARS = 5
WINDOW_MONTHS = 12 * YEARS   # 60
ANNUAL_THRESHOLD = 0.07
THRESHOLD = (1 + ANNUAL_THRESHOLD) ** YEARS - 1   # ≈ 0.4026

BLUE = "rgba(135, 206, 235, 0.35)"   # path: 파스텔 스카이블루
PINK = "rgba(247, 140, 140, 0.55)"   # path: 파스텔 핑크
BLUE_LEGEND = "#1F77B4"              # legend: 진한 블루
PINK_LEGEND = "#C0392B"              # legend: 진한 레드
LINE_W = 0.6
FONT_SIZE = 18                        # 22 의 20% 감소 (≈17.6)


def load_monthend() -> pd.Series:
    df = pd.read_csv(SRC, sep="\t", thousands=",", na_values=[""])
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"])
    df[TARGET] = pd.to_numeric(df[TARGET], errors="coerce")
    s = df.dropna(subset=[TARGET]).set_index("Date").sort_index()[TARGET]
    return s.resample("ME").last().dropna()


def build_paths(px: pd.Series, window: int):
    arr = px.values
    n = len(arr)
    x_months = np.arange(window + 1)
    xs_b, ys_b, xs_p, ys_p = [], [], [], []
    n_b = n_p = 0
    for s in range(n - window):
        seg = arr[s:s + window + 1] / arr[s] - 1.0
        if seg[-1] >= THRESHOLD:
            xs_b.append(x_months); xs_b.append([None])
            ys_b.append(seg);      ys_b.append([np.nan])
            n_b += 1
        else:
            xs_p.append(x_months); xs_p.append([None])
            ys_p.append(seg);      ys_p.append([np.nan])
            n_p += 1
    xb = np.concatenate(xs_b) if xs_b else np.array([])
    yb = np.concatenate(ys_b) if ys_b else np.array([])
    xp = np.concatenate(xs_p) if xs_p else np.array([])
    yp = np.concatenate(ys_p) if ys_p else np.array([])
    return (xb, yb, n_b), (xp, yp, n_p)


def main():
    px = load_monthend()
    (xb, yb, nb), (xp, yp, np_) = build_paths(px, WINDOW_MONTHS)
    total = nb + np_

    fig = go.Figure()
    # 실제 path: legend 미표시
    if len(xp) > 0:
        fig.add_trace(go.Scatter(
            x=xp, y=yp * 100, mode="lines",
            line=dict(color=PINK, width=LINE_W),
            hoverinfo="skip", showlegend=False,
        ))
    if len(xb) > 0:
        fig.add_trace(go.Scatter(
            x=xb, y=yb * 100, mode="lines",
            line=dict(color=BLUE, width=LINE_W),
            hoverinfo="skip", showlegend=False,
        ))
    # legend 전용 더미 trace (진한 색상, 굵은 라인)
    pct_b = nb / total * 100
    pct_p = np_ / total * 100
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="lines",
        line=dict(color=BLUE_LEGEND, width=4),
        name=f"수익률(연) 7% 이상 ({nb:,}/{total:,}건, {pct_b:.0f}%)",
    ))
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="lines",
        line=dict(color=PINK_LEGEND, width=4),
        name=f"수익률(연) 7% 미만 ({np_:,}/{total:,}건, {pct_p:.0f}%)",
    ))

    fig.add_hline(
        y=THRESHOLD * 100,
        line=dict(color="#222", width=1, dash="dash"),
        annotation_text=(f"누적 {THRESHOLD*100:.2f}% "
                         f"(연환산 {ANNUAL_THRESHOLD*100:.0f}%)"),
        annotation_position="top right",
        annotation_font=dict(size=FONT_SIZE, color="#222"),
    )
    fig.add_hline(y=0.0, line=dict(color="#888", width=0.7, dash="dot"))

    fig.update_layout(
        title=None,                       # 제목 제거
        font=dict(size=FONT_SIZE),
        xaxis=dict(
            title=dict(text=f"개월 (0 → {WINDOW_MONTHS}, 월말 기준)",
                       font=dict(size=FONT_SIZE)),
            tickfont=dict(size=FONT_SIZE),
        ),
        yaxis=dict(
            title=dict(text="누적수익률 (%)", font=dict(size=FONT_SIZE)),
            tickfont=dict(size=FONT_SIZE),
        ),
        template="plotly_white",
        width=960, height=540,           # 16:9 PPT 슬라이드 사이즈
        margin=dict(t=50, b=60, l=70, r=30),
        legend=dict(
            orientation="v",                    # 위아래 stack
            y=1.0, x=1.0, xanchor="right", yanchor="top",
            font=dict(size=FONT_SIZE),
            bgcolor="rgba(255,255,255,0.6)",
        ),
        hovermode=False,
    )

    out = ROOT / f"spaghetti_paths_{YEARS}Y_7pct_{TARGET}_ME.html"
    fig.write_html(str(out), include_plotlyjs="cdn")
    print(f"저장: {out}")
    print(f"월말 데이터 개수: {len(px)}, rolling path 개수: {total}")
    print(f"{TARGET} ≥ 연환산 7%: {nb:,}/{total:,} = {nb/total*100:.2f}%")


if __name__ == "__main__":
    main()
