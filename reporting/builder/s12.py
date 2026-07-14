"""슬라이드 12 — Historical Valuation: 지역/국가별 12M 선행 PER 박스 (이미지)."""
import math

from .common import (OUT, E, EX, add_text, slide_scaffold, plt, BODY_PT,
                     PT_PER_PX, PP_ALIGN, kdate)

# 러시아 제외 (2026-07-13 사용자 지시 — 2023-02 이후 데이터 중단)
CATS = [('전세계', 'MXWD'), ('미국', 'MXUS'), ('미국\n빅테크\n7 Plus', 'BUBT7P'),
        ('미국\n성장주', 'MXUS000G'), ('미국\n가치주', 'MXUS000V'), ('DM ex\nUS', 'MXWOU'),
        ('EM', 'MXEF'), ('한국', 'MXKR'), ('중국', 'MXCN'), ('일본', 'MXJP'),
        ('독일', 'MXDE'), ('영국', 'MXGB'), ('인도', 'MXIN'),
        ('브라질', 'MXBR'), ('인니', 'MXID'), ('남아공', 'MXZA')]
STALE_DAYS = 60          # 최근 관측이 이보다 오래되면 '현재' 마커 생략 (러시아 등)


def gen_chart(val, start, end):
    W, H = 1520, 770
    PL, PT_, PW, PH = 60, 40, 1400, 560
    stats = {}
    for nm, sym in CATS:
        v = val.get(sym)
        if not v or len(v['series']) < 10:
            continue
        pers = [p for _, p, _ in v['series']]
        last_d = v['series'][-1][0]
        import datetime
        stale = ((datetime.date.fromisoformat(end) - datetime.date.fromisoformat(last_d)).days
                 > STALE_DAYS)
        stats[sym] = (min(pers), max(pers), sum(pers) / len(pers),
                      None if stale else pers[-1])
    ymax = math.ceil(max(s[1] for s in stats.values()) / 10) * 10 + 2

    def Y(v): return PT_ + (ymax - v) / ymax * PH

    fig = plt.figure(figsize=(W / 72, H / 72), dpi=144)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis('off')
    ax.add_patch(plt.Rectangle((PL, PT_), PW, PH, facecolor='none',
                               edgecolor='#BFBFBF', lw=1.2, zorder=1))
    for v in range(0, ymax, 10):
        ax.plot([PL, PL + PW], [Y(v)] * 2, color='#EBEBEB', lw=1, zorder=1)
        ax.text(PL - 10, Y(v), str(v), ha='right', va='center', fontsize=19, color='#333')
    slot = PW / len(CATS)
    for i, (nm, sym) in enumerate(CATS):
        cx = PL + slot * (i + 0.5)
        ax.text(cx, PT_ + PH + 12, nm, ha='center', va='top', fontsize=19,
                color='#222', linespacing=1.15)
        if sym not in stats:
            continue
        mn, mx, me, cu = stats[sym]
        ax.plot([cx, cx], [Y(mn), Y(mx)], color='#D9DEB0', lw=19,
                solid_capstyle='round', zorder=2)
        ax.plot([cx - 19, cx + 19], [Y(me)] * 2, color='#111', lw=3.2, zorder=4)
        ax.plot(cx, Y(mx), 'o', ms=8, color='#D9412B', zorder=4)
        ax.plot(cx, Y(mn), 'o', ms=8, color='#3D9BDC', zorder=4)
        if cu is not None:
            ax.plot(cx, Y(cu), 'D', ms=8.5, color='#1F3352', zorder=5)
    # 범례
    ly = PT_ + PH + 86
    items = [('#D9412B', 'o', '최대'), ('#3D9BDC', 'o', '최소'),
             ('#111111', '-', '평균'), ('#1F3352', 'D', '현재')]
    lx = W / 2 - 180
    for col, mk, lab in items:
        if mk == '-':
            ax.plot([lx, lx + 26], [ly] * 2, color=col, lw=3.2)
        else:
            ax.plot(lx + 13, ly, mk, ms=9, color=col)
        ax.text(lx + 36, ly, lab, fontsize=19, color='#222', ha='left', va='center')
        lx += 110
    fig.savefig(OUT / 's12_chart.png', facecolor='white')
    plt.close(fig)
    return OUT / 's12_chart.png', (W, H)


def add(prs, ctx, page_label='12'):
    end = ctx['asof']
    val = ctx['valuation']
    start = val['MXKR']['series'][0][0]
    sl = slide_scaffold(prs, 'base_slide12.png', 'Historical Valuation', end,
                        page_label, subtitle=None)
    title = (f"지역/국가별 12개월 선행 PER({start.replace('-', '')} ~ "
             f"{end.replace('-', '')})")
    add_text(sl, 100, 160, 1400, 34, title, 23 * PT_PER_PX, '222222', bold=True,
             align=PP_ALIGN.CENTER)
    png, (w, h) = gen_chart(val, start, end)
    sl.shapes.add_picture(str(png), EX(40), E(210), E(w), E(h))
    add_text(sl, 900, 1010, 660, 26, f'· 자료: {kdate(end)}, Bloomberg, 한국투자신탁운용',
             BODY_PT - 2, '787878', align=PP_ALIGN.RIGHT)
    return sl
