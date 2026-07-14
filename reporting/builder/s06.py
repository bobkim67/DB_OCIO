"""슬라이드 6 — 운용 경과: 불릿 3 + 경기국면표 + 자산배분표 (전부 네이티브 편집)."""
from .common import (
    CANVAS_OFF, BODY_PT, HDR_BLUE, Z1, Z2, INK,
    remap, sv, add_text, add_table, slide_scaffold,
)

TH6, TD6 = sv(54), sv(56)
ASSET_ORDER = ['국내주식', '해외주식', '국내채권', '해외채권', '대체', '현금']


def _fmt_signed(v):
    return '—' if v is None else f'{v:+.2f}'


def add(prs, ctx, page_label='6'):
    rt = ctx['rets']
    sl = slide_scaffold(prs, 'base_slide06.png', '운용 경과', ctx['asof'], page_label)
    OX, OY = CANVAS_OFF
    W = 'FFFFFF'; K = INK

    # ── 불릿 3줄 ──
    # 불릿 3개 = 보고구간 거래 x 시장상황 연결 (LIG 발송본 문체, 2026-07-13 지시).
    # 승인 펀드코멘트(정본) + 거래/비중 데이터 + 시장코멘트 기반 LLM. 실패 시 수치 불릿 폴백.
    bullets = None
    try:
        from .s06_comment import build_s6_bullets
        bullets = build_s6_bullets(ctx['fund_code'], ctx['period_start'], ctx['asof'])
    except Exception as e:                # noqa: BLE001
        print(f'[s6] 거래 코멘트 생성 실패 → 수치 불릿 폴백: {e}')
    if not bullets:
        pl = ctx.get('plabel', '연초 이후')
        _qn = (int(ctx['asof'][5:7]) - 1) // 3 + 1
        top = sorted(((k, v) for k, v in ctx['weights'].items() if v >= 0.5),
                     key=lambda kv: -kv[1])[:3]
        alloc = ', '.join(f'{k} {v:.1f}%' for k, v in top)
        bullets = [
            f"· {pl} 수익률: 펀드 {_fmt_signed(rt['pr_f'])}%"
            + (f", BM {_fmt_signed(rt['pr_b'])}%" if rt.get('pr_b') is not None else ''),
            f"· {_qn}분기 수익률: 펀드 {_fmt_signed(rt['q_f'])}%"
            + (f", BM {_fmt_signed(rt['q_b'])}%" if rt['q_b'] is not None else ''),
            f'· 보유자산 배분: {alloc}',
        ]
    for i, b in enumerate(bullets[:3]):
        add_text(sl, OX + 24, remap(OY + 18 + 32 * i), 1450, 30, b, BODY_PT, INK)

    # ── 좌: 경기국면표 (SCIP regime 전환 이력 — 최근 5건, 마지막 2행 볼드) ──
    trans = ctx['regime']['transitions'][-5:]
    rows = [(HDR_BLUE, [(t, True, W) for t in ['기준 월', '관측 월', '경기국면']])]
    for i, t in enumerate(trans):
        bold = i >= len(trans) - 2
        rows.append((Z1 if i % 2 == 0 else Z2,
                     [(t['base_kr'], bold, K), (t['obs_kr'], bold, K),
                      (t['phase'], bold, K)]))
    add_table(sl, OX + 24, remap(OY + 192), [200, 200, 192],
              [TH6] + [TD6] * len(trans), rows)

    # ── 우: 자산배분표 (펀드 vs BM vs Active) ──
    w, bw = ctx['weights'], ctx['bm_weights']
    names = [a for a in ASSET_ORDER
             if w.get(a, 0) >= 0.05 or bw.get(a, 0) >= 0.05 or a not in ('대체',)]
    rows = [(HDR_BLUE, [(t, True, W) for t in
                        ['자산군', '펀드 비중(%)', 'BM 비중(%)', 'Active 비중(%p)']])]
    for i, a in enumerate(names):
        f, b = w.get(a, 0.0), bw.get(a, 0.0)
        rows.append((Z1 if i % 2 == 0 else Z2,
                     [(a, False, K), (f'{f:.1f}', False, K), (f'{b:.1f}', False, K),
                      (f'{f - b:+.1f}', False, K)]))
    add_table(sl, OX + 656, remap(OY + 192), [150, 202, 202, 200],
              [TH6] + [TD6] * len(names), rows)
    return sl
