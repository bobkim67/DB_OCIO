"""슬라이드 9 — Total Return Breakdown: PER×EPS 분해 누적바 + 표 (이미지)."""
import math

from .common import (OUT, E, add_text, slide_scaffold, plt, BODY_PT,
    PT_PER_PX, PP_ALIGN, kdate)

# (표시명, 심볼) — 발송본 14열. 데이터 없으면 빈칸.
CATS = [('전세계', 'MXWD'), ('미국', 'MXUS'), ('미국\n빅테크 7 Plus', 'BUBT7P'),
        ('미국\n성장주', 'MXUS000G'), ('미국\n가치주', 'MXUS000V'), ('DM ex US', 'MXWOU'),
        ('EM', 'MXEF'), ('한국', 'MXKR'), ('중국', 'MXCN'), ('일본', 'MXJP'),
        ('독일', 'MXDE'), ('영국', 'MXGB'), ('브라질', 'MXBR'), ('남아공', 'MXZA')]
RANK_SCOPE = [('DM ex US', 'MXWOU'), ('US Growth', 'MXUS000G'), ('US', 'MXUS'),
              ('Global', 'MXWD'), ('US Value', 'MXUS000V'), ('EM', 'MXEF'), ('Korea', 'MXKR')]
C_B, C_R, C_G = '#2C5A9C', '#A83232', '#6E8B3D'


def decomp(val, start, end):
    """구간 PER/EPS 변화율 분해: {sym: (per%, eps%, cross%, total%)}"""
    out = {}
    for sym, v in val.items():
        ser = [r for r in v['series'] if start <= r[0] <= end]
        if len(ser) < 2:
            continue
        # 구간 시작 = start 이후 첫 관측 (원본 동일)
        s0, s1 = ser[0], ser[-1]
        perc = (s1[1] / s0[1] - 1) * 100
        epsc = (s1[2] / s0[2] - 1) * 100
        tot = ((1 + perc / 100) * (1 + epsc / 100) - 1) * 100
        out[sym] = (round(perc, 1), round(epsc, 1), round(tot - perc - epsc, 1), round(tot, 1))
    return out


def subtitle_rank(dec):
    ranked = sorted((nm for nm, sym in RANK_SCOPE if sym in dec),
                    key=lambda nm: dec[dict(RANK_SCOPE)[nm]][3])
    return ' < '.join(ranked[:-1]) + ' <<< ' + ranked[-1] if len(ranked) > 1 else ''


def gen_chart(dec):
    W, H = 1520, 760
    PL, PR, PT_, PH = 112, 17, 14, 400
    fig = plt.figure(figsize=(W / 72, H / 72), dpi=144)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis('off')
    vals = [v for sym in (s for _, s in CATS) if sym in dec for v in dec[sym][:3]]
    pos_max = max(sum(max(v, 0) for v in dec[s][:3]) for _, s in CATS if s in dec)
    neg_min = min(sum(min(v, 0) for v in dec[s][:3]) for _, s in CATS if s in dec)
    YMAX = max(100, math.ceil(pos_max / 50) * 50)
    YMIN = min(-50, math.floor(neg_min / 50) * 50)
    S = PH / (YMAX - YMIN)
    y0 = PT_ + YMAX * S
    PW = W - PL - PR
    for v in range(YMAX, YMIN - 1, -50):
        yy = PT_ + (YMAX - v) * S
        ax.plot([PL, PL + PW], [yy] * 2, color='#7f7f7f' if v == 0 else '#DDDDDD',
                lw=2 if v == 0 else 1, zorder=1)
        ax.text(PL - 10, yy, f'{v}%', ha='right', va='center', fontsize=16, color='#333')
    slot = PW / len(CATS)
    BW = 56
    for i, (nm, sym) in enumerate(CATS):
        cx = PL + slot * (i + 0.5)
        if sym not in dec:
            continue
        up = dn = 0.0
        for col, v in zip((C_B, C_R, C_G), dec[sym][:3]):
            if v is None:
                continue
            h = abs(v) * S
            if v >= 0:
                top = y0 - (up + v) * S; up += v
            else:
                top = y0 + dn * S; dn += -v
            ax.add_patch(plt.Rectangle((cx - BW / 2, top), BW, h, facecolor=col,
                                       edgecolor='none', zorder=3))
    # ── 표 ──
    ty = PT_ + PH + 14
    col0 = PL
    cw = PW / len(CATS)
    TH, TD = 52, 44
    labels = ['총수익', 'PER 변화율', 'EPS 변화율', '기타']
    swatch = {1: C_B, 2: C_R, 3: C_G}
    def cell_rect(x, y, w, h, fill=None):
        ax.add_patch(plt.Rectangle((x, y), w, h, facecolor=fill or 'none',
                                   edgecolor='#C9C9C9', lw=1, zorder=2))
    # 헤더
    for i, (nm, _s) in enumerate(CATS):
        x = col0 + i * cw
        cell_rect(x, ty, cw, TH, '#F5F5F5')
        ax.text(x + cw / 2, ty + TH / 2, nm, ha='center', va='center', fontsize=14.5,
                fontweight='bold', color='#222', linespacing=1.1)
    for ri, lab in enumerate(labels):
        y = ty + TH + ri * TD
        fill0 = '#F2F2F2' if ri == 0 else '#FAFAFA'
        cell_rect(col0 - 112, y, 112, TD, fill0)
        if ri in swatch:
            ax.add_patch(plt.Rectangle((col0 - 106, y + TD / 2 - 7), 14, 14,
                                       facecolor=swatch[ri], edgecolor='none', zorder=3))
            ax.text(col0 - 86, y + TD / 2, lab, ha='left', va='center', fontsize=15,
                    fontweight='bold', color='#222')
        else:
            ax.text(col0 - 104, y + TD / 2, lab, ha='left', va='center', fontsize=15,
                    fontweight='bold', color='#222')
        for i, (nm, sym) in enumerate(CATS):
            x = col0 + i * cw
            fill = '#F2F2F2' if ri == 0 else None
            cell_rect(x, y, cw, TD, fill)
            if sym in dec:
                v = dec[sym][3] if ri == 0 else dec[sym][ri - 1]
                ax.text(x + cw / 2, y + TD / 2, f'{v:.1f}%', ha='center', va='center',
                        fontsize=15, color='#222',
                        fontweight='bold' if ri == 0 else 'normal')
    # 헤더행 좌측 빈 셀
    cell_rect(col0 - 112, ty, 112, TH, 'white')
    fig.savefig(OUT / 's9_chart.png', facecolor='white')
    plt.close(fig)
    return OUT / 's9_chart.png', (W, H)


def add(prs, ctx, page_label='9'):
    # s9~16 은 커스텀 구간과 무관하게 YTD 고정 (2026-07-13 사용자 확정)
    start = ctx.get('ytd_start') or ctx['series_ytd'][0]['date']
    end = ctx['asof']
    dec = decomp(ctx['valuation'], start, end)
    sl = slide_scaffold(prs, 'base_slide09.png', 'Total Return Breakdown', end,
                        page_label, subtitle=subtitle_rank(dec))
    title = f"글로벌 주식 총 수익률 분석(USD, {start.replace('-', '')} ~ {end.replace('-', '')})"
    add_text(sl, 100, 208, 1400, 34, title, 24 * PT_PER_PX, '222222', bold=True,
             align=PP_ALIGN.CENTER)
    png, (w, h) = gen_chart(dec)
    sl.shapes.add_picture(str(png), E(40), E(252), E(w), E(h))
    add_text(sl, 100, 1018, 900, 26,
             '총수익은 12M 선행 PER×EPS 기반 가격수익률(USD, 배당 제외), 기타는 PER·EPS 변동의 교차항',
             13 * PT_PER_PX * 1.4, '777777')
    add_text(sl, 900, 1018, 660, 26, f'· 자료: {kdate(end)}, Bloomberg, 한국투자신탁운용',
             BODY_PT - 2, '787878',
             align=PP_ALIGN.RIGHT)
    return sl
