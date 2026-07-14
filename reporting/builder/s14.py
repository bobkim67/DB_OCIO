"""슬라이드 14 — FX-Rate: 선진국 통화바스켓(DXY) 대비 원화 상대가치 ± 2.24σ 밴드.

산식(글로벌 마켓 모니터 FX RV 동일): RV = DXY 누적로그수익률 − USDKRW 누적로그수익률 (%).
밴드 = 롤링 3Y(756영업일, 최소 126) 평균 ± K·σ. K=2.24 (발송본 표기).
데이터: DXY(105/ds48, 2010-09~), USDKRW(31/ds6).
"""
import datetime
import math

import pymysql

from .common import (OUT, E, add_text, slide_scaffold, plt, BODY_PT,
                     PT_PER_PX, PP_ALIGN, kdate)
from modules.data_loader import parse_data_blob

WINDOW_START = '2017-01-01'      # 발송본 표기 구간
ROLL, ROLL_MIN, K = 756, 126, 2.24
C_RV, C_MEAN, C_UP, C_DN = '#4A90D9', '#ED7D31', '#70AD47', '#C3B1E1'


def _dnum(d):
    y, m, dd = map(int, d.split('-'))
    return datetime.date(y, m, dd).toordinal()


def _load(end_date):
    conn = pymysql.connect(host='192.168.195.55', user='solution', password='Solution123!',
                           db='SCIP', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
    try:
        cur = conn.cursor()
        out = {}
        for key, did, sid in [('dxy', 105, 48), ('usdkrw', 31, 6)]:
            cur.execute(
                "SELECT DATE(timestamp_observation) d, data FROM back_datapoint "
                "WHERE dataset_id=%s AND dataseries_id=%s AND DATE(timestamp_observation)<=%s "
                "ORDER BY timestamp_observation", (did, sid, end_date))
            ser = {}
            for r in cur.fetchall():
                try:
                    v = parse_data_blob(r['data'])
                    if isinstance(v, dict):
                        v = v.get('USD') or next(iter(v.values()))
                    ser[r['d'].strftime('%Y-%m-%d')] = float(v)
                except Exception:
                    continue
            out[key] = ser
    finally:
        conn.close()
    return out


def compute_rv(data):
    """(dates, rv, mean, up, dn) — 롤링 통계는 표시구간 이전 이력 포함해 계산."""
    common = sorted(set(data['dxy']) & set(data['usdkrw']))
    a0, b0 = data['dxy'][common[0]], data['usdkrw'][common[0]]
    rv_all = [(d, (math.log(data['dxy'][d] / a0) - math.log(data['usdkrw'][d] / b0)) * 100)
              for d in common]
    mean, up, dn = [], [], []
    vals = [v for _, v in rv_all]
    for i in range(len(rv_all)):
        w = vals[max(0, i - ROLL + 1): i + 1]
        if len(w) < ROLL_MIN:
            mean.append(None); up.append(None); dn.append(None)
            continue
        m = sum(w) / len(w)
        sd = (sum((x - m) ** 2 for x in w) / len(w)) ** 0.5
        mean.append(m); up.append(m + K * sd); dn.append(m - K * sd)
    # 표시구간 필터 + 구간시작=0 리베이스
    idx = [i for i, (d, _v) in enumerate(rv_all) if d >= WINDOW_START]
    base = rv_all[idx[0]][1]
    dates = [rv_all[i][0] for i in idx]
    rv = [rv_all[i][1] - base for i in idx]
    mean = [(mean[i] - base) if mean[i] is not None else None for i in idx]
    up = [(up[i] - base) if up[i] is not None else None for i in idx]
    dn = [(dn[i] - base) if dn[i] is not None else None for i in idx]
    return dates, rv, mean, up, dn


def gen_chart(dates, rv, mean, up, dn):
    W, H = 1420, 730
    PL, PT_, PW, PH = 90, 60, 1250, 590
    allv = rv + [v for v in up if v is not None] + [v for v in dn if v is not None]
    YMAX = math.ceil(max(allv) / 5) * 5
    YMIN = math.floor(min(allv) / 5) * 5
    T0, T1 = _dnum(dates[0]), _dnum(dates[-1])

    def X(d): return PL + (_dnum(d) - T0) / (T1 - T0) * PW
    def Y(v): return PT_ + (YMAX - v) / (YMAX - YMIN) * PH

    fig = plt.figure(figsize=(W / 72, H / 72), dpi=144)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis('off')
    ax.add_patch(plt.Rectangle((PL, PT_), PW, PH, facecolor='none',
                               edgecolor='#BFBFBF', lw=1.2, zorder=1))
    for v in range(YMIN, YMAX + 1, 5):
        ax.plot([PL, PL + PW], [Y(v)] * 2, color='#9a9a9a' if v == 0 else '#EBEBEB',
                lw=1, zorder=1)
        ax.text(PL - 10, Y(v), f'{v}%', ha='right', va='center', fontsize=19, color='#333')
    for yr in range(int(dates[0][:4]), int(dates[-1][:4]) + 1):
        d = f'{yr}-01-01'
        if _dnum(d) < T0 or _dnum(d) > T1:
            continue
        ax.plot([X(d)] * 2, [PT_ + PH, PT_ + PH + 7], color='#BFBFBF', lw=1)
        ax.text(X(d), PT_ + PH + 16, d, fontsize=17, color='#555', ha='center', va='top')
    def seg_plot(ys, col, lw, z):
        xs2, ys2 = [], []
        for d, v in zip(dates, ys):
            if v is None:
                continue
            xs2.append(X(d)); ys2.append(Y(v))
        ax.plot(xs2, ys2, color=col, lw=lw, zorder=z)
    seg_plot(up, C_UP, 2, 3)
    seg_plot(mean, C_MEAN, 2, 3)
    seg_plot(dn, C_DN, 2, 3)
    ax.plot([X(d) for d in dates], [Y(v) for v in rv], color=C_RV, lw=1.6, zorder=4)
    # 범례 (플롯 상단 안쪽)
    lx = PL + 560
    for col, lab in [(C_MEAN, '평균'), (C_UP, f'평균 + {K}σ'), (C_DN, f'평균 - {K}σ')]:
        ax.plot([lx, lx + 26], [PT_ + 20] * 2, color=col, lw=3)
        ax.text(lx + 33, PT_ + 20, lab, fontsize=19, color='#333', ha='left', va='center')
        lx += 33 + len(lab) * 19 + 46
    fig.savefig(OUT / 's14_chart.png', facecolor='white')
    plt.close(fig)
    return OUT / 's14_chart.png', (W, H)


def add(prs, ctx, page_label='14'):
    end = ctx['asof']
    data = _load(end)
    dates, rv, mean, up, dn = compute_rv(data)
    # 부제 자동: 현재 z-스코어 기반 (편집 가능)
    m_now = next((m for m in reversed(mean) if m is not None), None)
    u_now = next((u for u in reversed(up) if u is not None), None)
    z_txt = ''
    if m_now is not None and u_now is not None and u_now != m_now:
        z = (rv[-1] - m_now) / ((u_now - m_now) / K)
        zone = '절대적 저평가 영역' if z <= -K else ('고평가 영역' if z >= K else '중립 영역')
        z_txt = f'원달러 환율은 달러인덱스 바스켓 대비 z={z:+.2f}σ — {zone}'
    sl = slide_scaffold(prs, 'base_slide07.png', 'FX-Rate', end, page_label,
                        subtitle=z_txt or None)
    add_text(sl, 100, 208, 1400, 34, '선진국 통화바스켓 대비 원화 상대가치', 24 * PT_PER_PX,
             '222222', bold=True, align=PP_ALIGN.CENTER)
    png, (w, h) = gen_chart(dates, rv, mean, up, dn)
    sl.shapes.add_picture(str(png), E((1600 - w) // 2), E(258), E(w), E(h))
    add_text(sl, 900, 1015, 660, 26, f'· 자료: {kdate(end)}, Bloomberg, 한국투자신탁운용',
             BODY_PT - 2, '787878', align=PP_ALIGN.RIGHT)
    return sl
