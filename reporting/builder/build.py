"""운용보고 PPT 빌드 엔트리.

사용:
    python -m reporting.builder.build 07G07 2026-06-30
    python -m reporting.builder.build 07G07 2026-06-30 --check   # 레포 스냅샷 회귀 대조
"""
import argparse
import json

from .common import OUT, new_presentation
from .data_fund import get_fund_data, get_brinson_contrib
from .data_regime import fetch_regime
from .data_valuation import load_valuation
from . import s_static, s04, s06, s07, s09, s10, s11, s12, s13, s14, s16


def build_report(fund_code: str, end_date: str, start_date: str | None = None,
                 out_path=None) -> str:
    """start_date: 보고 구간 시작 (None=전년말 YTD). s4/s6/s7 에 반영, s9~16 은 종료일만."""
    ctx = get_fund_data(fund_code, end_date, start_date)
    ctx['regime'] = fetch_regime(end_date)
    ctx['valuation'] = load_valuation(end_date)
    # Brinson 엔진은 start '당일 수익 포함'(base=전영업일) 규약 — 커스텀 구간은
    # 앵커 다음 영업일을 넘겨 base=앵커로 정렬 (YTD 12/31 은 엔진이 앵커로 처리, 검증 2026-07-13)
    br_start = (ctx['period_start'] if ctx['is_ytd']
                else (ctx['series_ytd'][1]['date'] if len(ctx['series_ytd']) > 1
                      else ctx['period_start']))
    ctx['brinson'] = get_brinson_contrib(fund_code, br_start, ctx['asof'])
    prs = new_presentation()
    # 16장 구성 = 사용자 재구성 202606 편집본 (2026-07-14): 표지·목차·섹션 4장 + 데이터 10장
    s_static.add_cover(prs, ctx)                  # 1
    s_static.add_toc(prs, fund_code)              # 2 (부제 = 펀드명 규칙)
    s_static.add_section(prs, 'slide3')           # 3  01 금융시장 리뷰
    s04.add(prs, ctx)                             # 4
    s_static.add_section(prs, 'slide5')           # 5  02 운용 및 성과 리뷰
    s06.add(prs, ctx)                             # 6
    s07.add(prs, ctx)                             # 7
    s_static.add_section(prs, 'slide8')           # 8  03 펀더멘털 점검
    s09.add(prs, ctx)
    s10.add(prs, ctx)
    s11.add(prs, ctx)
    s12.add(prs, ctx)
    s13.add(prs, ctx)
    s14.add(prs, ctx)
    s_static.add_section(prs, 'slide15')          # 15 04 운용 계획
    s16.add(prs, ctx)                             # 16
    _tag = f'_{start_date.replace("-", "")}' if start_date else ''
    out = out_path or (OUT / f'report_{fund_code}_{end_date.replace("-", "")}{_tag}.pptx')
    base = out
    for n in range(2, 10):                   # PowerPoint 에 열려있으면 _vN 폴백
        try:
            prs.save(str(out))
            break
        except PermissionError:
            out = base.with_stem(base.stem + f'_v{n}')
    return str(out)


def regression_check(fund_code: str, end_date: str):
    """레포 스냅샷(fund_07G07_YTD/2Q.json) 대비 라이브 DB 수치 대조."""
    from .common import ROOT
    ctx = get_fund_data(fund_code, end_date)
    ref = json.loads((ROOT / 'reference' / 'fund_07G07_YTD.json').read_text(encoding='utf-8'))
    ref2q = json.loads((ROOT / 'reference' / 'fund_07G07_2Q.json').read_text(encoding='utf-8'))
    print(f"== regression {fund_code} @ {end_date} (bm_src={ctx['bm_src']}) ==")
    sm, rt = ref['summary'], ctx['rets']
    print(f"YTD 펀드: ref {sm['fund_return_pct']} vs live {rt['ytd_f']}")
    print(f"YTD BM  : ref {sm['bm_return_pct']} vs live {rt['ytd_b']}")
    print(f"2Q  펀드: ref {ref2q['summary']['fund_return_pct']} vs live {rt['q_f']}")
    print(f"2Q  BM  : ref {ref2q['summary']['bm_return_pct']} vs live {rt['q_b']}")
    print(f"SI 펀드 : ref {round(ref['series'][-1]['nav'] / 1000 - 1, 4) * 100:.2f} (base1000) "
          f"vs live {rt['si_f']} (inception base 규약)")
    # 시계열 대조 (YTD)
    ref_ser = {r['date']: r for r in ref['series']}
    live_ser = {r['date']: r for r in ctx['series_ytd']}
    common_d = sorted(set(ref_ser) & set(live_ser))
    nav_diff = max(abs(ref_ser[d]['nav'] - live_ser[d]['nav']) for d in common_d)
    bm_diff = max(abs(ref_ser[d]['bm'] - (live_ser[d]['bm'] or 0)) for d in common_d)
    print(f"시계열: 공통 {len(common_d)}일 (ref {len(ref_ser)} / live {len(live_ser)}) | "
          f"nav 최대차 {nav_diff:.6f} | bm 최대차 {bm_diff:.6f}")
    only_ref = sorted(set(ref_ser) - set(live_ser))
    only_live = sorted(set(live_ser) - set(ref_ser))
    if only_ref:
        print(f"  ref 에만: {only_ref[:5]}{'...' if len(only_ref) > 5 else ''}")
    if only_live:
        print(f"  live 에만: {only_live[:5]}{'...' if len(only_live) > 5 else ''}")
    # 비중 대조 (s6 발송본: 국내주식 17.1 / 해외주식 19.2 / 국내채권 62.9 / 현금 0.9)
    print(f"weights(live): { {k: round(v, 1) for k, v in ctx['weights'].items()} }")
    print(f"bm_weights   : {ctx['bm_weights']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('fund_code')
    ap.add_argument('end_date')            # YYYY-MM-DD
    ap.add_argument('--start', default=None, help='보고 구간 시작 (기본: 전년말 YTD)')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    if args.check:
        regression_check(args.fund_code, args.end_date)
        return
    out = build_report(args.fund_code, args.end_date, args.start)
    print(f'OK: {out}')


if __name__ == '__main__':
    main()
