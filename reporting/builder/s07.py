"""슬라이드 7 — 성과 리뷰: 기간수익률표 + 성과추이 차트(이미지) + 기여수익률표."""
import math

from .common import (
    OUT, CANVAS_OFF, BODY_PT, HDR_BLUE, Z1, Z2, INK, C_FUND, C_BM, C_EXC,
    remap, sv, E, EX, add_text, add_pbar, add_table, slide_scaffold, plt,
)

TH, TD = sv(38), sv(36)


def _fmt(v):
    return '—' if v is None else f'{v:.2f}'


def _fmt_signed(v):
    return '—' if v is None else f'{v:+.2f}'


def gen_perf_chart(ctx):
    """연초 이후 성과추이 (초과성과 영역 + 펀드/BM 라인). 이미지 유지."""
    ser = ctx['series_ytd']
    has_bm = ctx['bm_src'] is not None
    IMG_X0, W, H = 48, 724, sv(340)
    PL, PT = 48, 34                       # 상단 범례 공간 (2026-07-13: legend 위쪽 가운데)
    CW, CH = 640, sv(280)
    n0 = ser[0]['nav']
    b0 = ser[0]['bm'] if has_bm else None
    N = len(ser)
    fv = [(r['nav'] / n0 - 1) * 100 for r in ser]
    bv = [(r['bm'] / b0 - 1) * 100 if has_bm and r['bm'] else None for r in ser]
    ev = [f - b for f, b in zip(fv, bv)] if has_bm else [0.0] * N
    # 동적 y범위 (step 2, 최소 -2~4)
    vals = fv + [v for v in bv if v is not None] + ev
    YMAX = max(4, math.ceil(max(vals) / 2) * 2 + 2)
    YMIN = min(-2, math.floor(min(vals) / 2) * 2)

    def X(i): return PL + i / (N - 1) * CW
    def Y(v): return PT + (YMAX - v) / (YMAX - YMIN) * CH

    fig = plt.figure(figsize=(W / 72, H / 72), dpi=144)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis('off')
    FS_TICK = 19        # 눈금·범례 = 10pt 물리크기 (19px×0.526, 2026-07-13 사용자 지시)
    for v in range(YMIN, YMAX + 1, 2):
        ax.plot([PL, PL + CW], [Y(v)] * 2, color='#999999' if v == 0 else '#E8E8E8',
                lw=1, zorder=1)
        ax.text(PL - 6, Y(v), f'{v}%', ha='right', va='center', fontsize=FS_TICK, color='#666')
    xs = [X(i) for i in range(N)]
    if has_bm:
        ax.fill_between(xs, [Y(0)] * N, [Y(e) for e in ev], color=C_EXC, alpha=0.8,
                        lw=0, zorder=2)
        ax.plot(xs, [Y(v) for v in bv], color=C_BM, lw=2, zorder=3)
    ax.plot(xs, [Y(v) for v in fv], color=C_FUND, lw=2, zorder=3)
    # 월 라벨: 매월 첫 영업일 (1일 미존재 월 누락 방지 — 원본 date=='01' 개선)
    prev_m = ser[0]['date'][5:7]
    for i, r in enumerate(ser[1:], 1):
        m = r['date'][5:7]
        if m != prev_m:
            ax.text(X(i) - 14, PT + CH + 6, f'{int(m)}월', ha='left', va='top',
                    fontsize=FS_TICK, color='#666')
            prev_m = m
    # 범례 — 차트 위쪽 가운데, 10pt (2026-07-13 사용자 지시)
    ly = 15
    items = ([('rect', C_EXC, '초과성과(%p)', 168)] if has_bm else []) \
        + [('line', C_FUND, '펀드', 84)] \
        + ([('line', C_BM, 'BM', 66)] if has_bm else [])
    total_w = sum(30 + w for _k, _c, _t, w in items) + 24 * (len(items) - 1)
    lx = PL + (CW - total_w) / 2
    for kind, col, label, wlab in items:
        if kind == 'rect':
            ax.add_patch(plt.Rectangle((lx, ly - 7), 26, 14, facecolor=col, edgecolor='none'))
        else:
            ax.plot([lx, lx + 26], [ly] * 2, color=col, lw=3.4)
        ax.text(lx + 32, ly, label, ha='left', va='center', fontsize=FS_TICK, color='#555')
        lx += 30 + wlab + 24
    p = OUT / f's7_perf_chart_{ctx["fund_code"]}.png'
    fig.savefig(p, facecolor='white')
    plt.close(fig)
    return p, (IMG_X0, W, H)


def add(prs, ctx, page_label='7'):
    rt = ctx['rets']
    sl = slide_scaffold(prs, 'base_slide07.png', '성과 리뷰', ctx['asof'], page_label)
    OX, OY = CANVAS_OFF

    pl = ctx.get('plabel', '연초 이후')            # 구간 라벨 (YTD 아니면 '기간')
    _x = (round(rt['pr_f'] - rt['pr_b'], 2) if rt.get('pr_b') is not None else None)
    b1 = (f"· {pl} 수익률 {_fmt_signed(rt['pr_f'])}%"
          + (f"로 BM({_fmt_signed(rt['pr_b'])}%) 대비 "
             + (f"{_fmt_signed(_x)}%p 초과 성과" if _x >= 0 else f"{abs(_x):.2f}%p 하회")
             if _x is not None else ''))
    # b2 = 자산군별 성과기여도 요약 (LIG 발송본 형식: 기여 오름차순 나열, 2026-07-13 지시)
    br = ctx.get('brinson') or {}
    if br.get('rows'):
        ranked = sorted(br['rows'].items(), key=lambda kv: kv[1][0])
        b2 = '· 성과기여도: ' + ' < '.join(k for k, _v in ranked)
    else:
        _qn = (int(ctx['asof'][5:7]) - 1) // 3 + 1
        b2 = (f"· {_qn}분기 수익률: 펀드 {_fmt_signed(rt['q_f'])}%"
              + (f", BM {_fmt_signed(rt['q_b'])}% (초과성과 "
                 f"{_fmt_signed(round(rt['q_f'] - rt['q_b'], 2))}%p)"
                 if rt['q_b'] is not None else ''))
    add_text(sl, OX + 52, remap(OY + 18), 1200, 30, b1, BODY_PT, INK)
    add_text(sl, OX + 52, remap(OY + 50), 1200, 30, b2, BODY_PT, INK)

    # 타이틀바 (2026-07-13 사용자 지정): 좌="성과 추이", 우="[구간] 기여수익률 분석(%, %p)"
    #   구간 시작 표기 = 앵커 다음날(수익 귀속 시작일, 예: 12/31 앵커 → '26.1.1)
    import datetime as _dt
    _ps = _dt.date.fromisoformat(ctx['period_start']) + _dt.timedelta(days=1)
    _pe = _dt.date.fromisoformat(ctx['asof'])
    _f = lambda d: f"'{d.year % 100}.{d.month}.{d.day}"
    add_pbar(sl, OX + 48, remap(OY + 246), 724, '성과 추이')
    add_pbar(sl, OX + 788, remap(OY + 246), 694,
             f'[{_f(_ps)} ~ {_f(_pe)}] 기여수익률 분석(%, %p)')

    W = 'FFFFFF'; K = INK
    add_table(
        sl, OX + 52, remap(OY + 96), [230, 240, 240, 240, 240, 240], [TH, TD, TD],
        [
            (HDR_BLUE, [(t, True, W) for t in
                        ['기간', '1개월', '3개월', '6개월', '연초 이후', '설정 이후']]),
            (Z1, [('펀드(%)', True, K)] + [(_fmt(v), False, K) for v in
                  [rt['m1_f'], rt['m3_f'], rt['m6_f'], rt['ytd_f'], rt['si_f']]]),
            (Z2, [('BM(%)', True, K)] + [(_fmt(v), False, K) for v in
                  [rt['m1_b'], rt['m3_b'], rt['m6_b'], rt['ytd_b'], rt['si_b']]]),
        ])

    # 기여수익률: Brinson 자산군별 AP기여/BM기여 (fx_split=False — 환효과 자산군 포함).
    # 값 없는 자산군은 행 자체 삭제 (2026-07-13 사용자 지시 — 07G07 대체투자 등)
    classes = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', '기타']
    contrib = ctx.get('brinson') or {}
    br_rows = contrib.get('rows', {})
    show = [n for n in classes if n in br_rows] if br_rows else classes
    rows = [(HDR_BLUE, [(t, True, W) for t in [pl, '펀드', 'BM', 'Active']])]
    for i, name in enumerate(show):
        c = br_rows.get(name)
        cells = [(name, False, K)]
        if c:
            cells += [(_fmt_signed(c[0]), False, K), (_fmt_signed(c[1]), False, K),
                      (_fmt_signed(round(c[0] - c[1], 2)), False, K)]
        else:
            cells += [('', False, K)] * 3
        rows.append((Z1 if i % 2 == 0 else Z2, cells))
    # 합계 = Brinson 총계 (셀 합과 정합). 없으면 NAV 기간수익률
    tf_, tb_ = contrib.get('ap_total', rt['ytd_f']), contrib.get('bm_total', rt['ytd_b'])
    tx_ = (round(tf_ - tb_, 2) if tf_ is not None and tb_ is not None else None)
    rows.append((Z1, [('합계', True, K), (_fmt_signed(tf_), True, K),
                      (_fmt_signed(tb_), True, K), (_fmt_signed(tx_), True, K)]))
    add_table(sl, OX + 788, remap(OY + 288), [190, 168, 168, 168],
              [TH] + [TD] * (len(rows) - 1), rows)

    chart_png, (cx0, cw, ch) = gen_perf_chart(ctx)
    sl.shapes.add_picture(str(chart_png), EX(OX + cx0), E(remap(OY + 290)), E(cw), E(ch))
    return sl
