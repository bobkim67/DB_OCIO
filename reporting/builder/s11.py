"""슬라이드 11 — Total 기업 실적 전망치: 12M 선행 EPS 추이 (리베이스 %, 이미지)."""
import datetime
import math

from .common import (OUT, E, add_text, slide_scaffold, plt, BODY_PT,
                     PT_PER_PX, PP_ALIGN, kdate)

SERIES = [('MXKR', 'Korea', '#A6A6A6', '#7F7F7F'),
          ('MXUS000G', 'US Growth', '#FFC000', '#D99E00'),
          ('MXUS', 'US', '#ED7D31', '#E06B1F'),
          ('MXUS000V', 'US Value', '#4472C4', '#3A66B8'),
          ('MXEF', 'EM', '#5B9BD5', '#4E95D4'),
          ('MXWOU', 'DM ex US', '#1F3864', '#1F3864')]


def _dnum(d):
    y, m, dd = map(int, d.split('-'))
    return datetime.date(y, m, dd).toordinal()


def gen_chart(val, end):
    W, H = 1520, 770
    PL, PT_, PW, PH = 84, 30, 1230, 620
    ref = val['MXKR']['series']
    T0, T1 = _dnum(ref[0][0]), _dnum(ref[-1][0])

    lines, ends, allv = [], [], []
    for sym, nm, col, tcol in SERIES:
        rows = val[sym]['series']
        e0 = rows[0][2]
        pts = [((_dnum(d) - T0) / (T1 - T0), (e / e0 - 1) * 100) for d, _p, e in rows]
        allv += [v for _, v in pts]
        lines.append((pts, col))
        ends.append((nm, pts[-1][1], tcol))
    YMAX = math.ceil(max(allv) / 100) * 100
    YMIN = min(-100, math.floor(min(allv) / 100) * 100)

    def X(fx): return PL + fx * PW
    def Y(v): return PT_ + (YMAX - v) / (YMAX - YMIN) * PH

    fig = plt.figure(figsize=(W / 72, H / 72), dpi=144)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis('off')
    for v in range(YMAX, YMIN - 1, -100):
        ax.plot([PL, PL + PW], [Y(v)] * 2, color='#9a9a9a' if v == 0 else '#EBEBEB',
                lw=1, zorder=1)
        if v > YMIN:      # 최하단 라벨은 회전 x라벨과 겹쳐 생략
            ax.text(PL - 10, Y(v), f'{v}%', ha='right', va='center', fontsize=19, color='#333')
    y0, y1 = int(ref[0][0][:4]), int(ref[-1][0][:4])
    for yr in range(y0, y1 + 1):
        d = f'{yr}-09-30'
        if _dnum(d) < T0 or _dnum(d) > T1:
            continue
        fx = (_dnum(d) - T0) / (T1 - T0)
        ax.plot([X(fx)] * 2, [PT_ + PH, PT_ + PH + 7], color='#BFBFBF', lw=1.2)
        ax.text(X(fx) + 6, PT_ + PH + 20, d, fontsize=19, color='#333',
                rotation=32, ha='right', va='top', rotation_mode='anchor')
    for pts, col in lines:
        ax.plot([X(fx) for fx, _ in pts], [Y(v) for _, v in pts], color=col, lw=2, zorder=3)
    # 우측 끝 라벨 (겹침 방지 최소 간격)
    prev = -1e9
    for nm, v, tcol in sorted(ends, key=lambda t: Y(t[1])):
        yy = max(Y(v), prev + 28)
        prev = yy
        ax.text(PL + PW + 14, yy, f'{nm} {v:.0f}%', fontsize=19, fontweight='bold',
                color=tcol, ha='left', va='center')
    fig.savefig(OUT / 's11_chart.png', facecolor='white')
    plt.close(fig)
    return OUT / 's11_chart.png', (W, H)


def add(prs, ctx, page_label='11'):
    end = ctx['asof']
    sl = slide_scaffold(prs, 'base_slide11.png', 'Total 기업 실적 전망치', end,
                        page_label, subtitle=None)
    add_text(sl, 100, 160, 1400, 34, '12개월 선행 EPS 추이', 24 * PT_PER_PX,
             '222222', bold=True, align=PP_ALIGN.CENTER)
    png, (w, h) = gen_chart(ctx['valuation'], end)
    sl.shapes.add_picture(str(png), E(40), E(210), E(w), E(h))
    add_text(sl, 900, 1010, 660, 26, f'· 자료: {kdate(end)}, Factset, 한국투자신탁운용',
             BODY_PT - 2, '787878', align=PP_ALIGN.RIGHT)
    return sl
