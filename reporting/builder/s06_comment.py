"""s6(운용 경과) 불릿 자동 생성 — 상반기(보고구간) 거래를 시장상황과 연결.

참고 문체 = LIG디펜스&에어로스페이스 발송본 (2026-07-13 사용자 제공):
  "· 중동 사태 발발 이후, 유가 및 달러 강세로 금가격 하락 → 금 비중 축소 및 국내주식 비중확대 운용 중"
  "· 금리상승에 대응하여, 국내채권은 모두 장기채권(10년/30년 만기 국고채)으로 전환 운용 중"
입력: 자산군 비중 변화(시작→끝) + 자산군별 순매수 + 종목 순매수 상위 + 신규편입/전량편출
      (보유 diff 교차검증 — 순매수 합계만으론 편출 못 잡음) + 승인 시장코멘트.
캐시: out/s6_manual_{fund}_{end}.json (수동 편집 가능).
"""
import json
import re

from .common import OUT, REPO
from .s04_comment import _load_final

# 종류형 클래스 → 펀드 코멘트 정본 코드 (07G07 은 07G04 로 작성·승인됨)
_FUND_ALIAS = {'07G07': '07G04'}


def _load_fund_final(fund_code, period):
    """승인된 펀드 운용 코멘트 (거래·운용 서술 정본 — 2026-07-13 사용자 지시로 참고)."""
    for f in (fund_code, _FUND_ALIAS.get(fund_code)):
        if not f:
            continue
        p = (REPO / 'market_research' / 'data' / 'report_output' / period / f'{f}.final.json')
        if p.exists():
            d = json.loads(p.read_text(encoding='utf-8'))
            if d.get('approved'):
                fc = d.get('final_comment', '')
                return re.sub(r'\[(?:ref|claim):[^\]]+\]', '', fc)
    return None


def _trade_digest(fund_code, start_iso, end_iso):
    """거래·포지셔닝 요약 (LLM 입력용)."""
    from modules.data_loader import (load_fund_trades_lookthrough,
                                     load_weight_history_lookthrough)
    out = []
    # 자산군 비중: 시작 vs 끝
    wdf, _f, _k = load_weight_history_lookthrough(fund_code, start_iso, 'asset')
    if len(wdf):
        wdf = wdf[wdf['date'] <= end_iso]
        d0, d1 = wdf['date'].min(), wdf['date'].max()
        w0 = wdf[wdf['date'] == d0].set_index('key')['weight']
        w1 = wdf[wdf['date'] == d1].set_index('key')['weight']
        lines = [f"{k}: {w0.get(k, 0):.1f}% → {w1.get(k, 0):.1f}%"
                 for k in sorted(set(w0.index) | set(w1.index))]
        out.append(f'[자산군 비중 변화 {d0} → {d1}]\n' + '\n'.join(lines))
    # 종목 비중: 신규편입/전량편출 (보유 diff — 필수 교차검증)
    sdf, _f2, _k2 = load_weight_history_lookthrough(fund_code, start_iso, 'security')
    if len(sdf):
        sdf = sdf[sdf['date'] <= end_iso]
        d0, d1 = sdf['date'].min(), sdf['date'].max()
        s0 = set(sdf[(sdf['date'] == d0) & (sdf['weight'] > 0.3)]['key'])
        s1 = set(sdf[(sdf['date'] == d1) & (sdf['weight'] > 0.3)]['key'])
        added = sorted(s1 - s0)[:8]
        removed = sorted(s0 - s1)[:8]
        if added:
            out.append('[신규 편입(비중 0.3%↑)]: ' + ', '.join(added))
        if removed:
            out.append('[전량/대부분 편출]: ' + ', '.join(removed))
    # 거래: 자산군별 순매수 + 종목 상위
    tdf, _fq, _fof = load_fund_trades_lookthrough(
        fund_code, int(start_iso.replace('-', '')), int(end_iso.replace('-', '')))
    if tdf is not None and len(tdf):
        tdf = tdf.copy()
        tdf['signed'] = tdf.apply(
            lambda r: r['금액(억)'] * (1 if '매수' in str(r['매수매도']) or '발행' in str(r['매수매도'])
                                      else -1), axis=1)
        by_ac = tdf.groupby('자산군')['signed'].sum().sort_values()
        out.append('[자산군별 순매수(억)]\n' +
                   '\n'.join(f'{k}: {v:+.0f}' for k, v in by_ac.items()))
        by_item = tdf.groupby(['자산군', '종목명'])['signed'].sum()
        top = by_item[by_item.abs() > 5].sort_values()
        picks = list(top.head(6).items()) + list(top.tail(6).items())
        out.append('[종목 순매수 상위/하위(억)]\n' +
                   '\n'.join(f'{ac}/{nm}: {v:+.0f}' for (ac, nm), v in picks))
    return '\n\n'.join(out)


def build_s6_bullets(fund_code, start_iso, end_iso, use_llm=True, tag='',
                     plabel=None, market_text=None):
    """s6 불릿 3개 + 캐시. 캐시 파일 수동 편집 가능.

    tag: 커스텀 구간 시작일 등 **캐시 구분자** (YTD 기본은 빈 문자열 — s4 와 동일 규약).
      ★ 종전에는 캐시명이 `s6_manual_{fund}_{end}.json` 이라 종료일만 같으면
        설정이후 PPT 와 하반기 PPT 가 **같은 파일을 공유**했다. 두 번째 빌드는
        LLM 을 타지도 않고 첫 빌드의 불릿을 그대로 재사용했다(08N33 실측:
        캐시 파일이 딱 1개). s4 는 이미 tag 로 분리돼 있었는데 s6 만 빠져 있었다.
    """
    suffix = f'_{str(tag).replace("-", "")}' if tag else ''
    cache = OUT / f's6_manual_{fund_code}_{end_iso.replace("-", "")}{suffix}.json' 
    if cache.exists():
        return json.loads(cache.read_text(encoding='utf-8'))['bullets']
    digest = _trade_digest(fund_code, start_iso, end_iso)
    y, m = end_iso[:4], int(end_iso[5:7])
    # market_text = 구간 전체를 덮는 시장 코멘트 (라우터 해석). 없으면 종전 폴백.
    if market_text:
        month_c, q_c = market_text, ''
    else:
        month_c = _load_final(f'{y}-{m:02d}') or ''
        q_c = _load_final(f'{y}-Q{(m - 1) // 3 + 1}') or ''
    fund_q = _load_fund_final(fund_code, f'{y}-Q{(m - 1) // 3 + 1}') or ''
    fund_m = _load_fund_final(fund_code, f'{y}-{m:02d}') or ''
    from market_research.core.constants import ANTHROPIC_API_KEY, LLM_MODEL
    import anthropic
    from .period_label import span_block
    prompt = f"""판매사 발송용 운용보고 PPT '운용 경과' 페이지 상단 불릿 3개를 작성하라.
내용 = 보고구간({start_iso}~{end_iso}) 중 실제 운용(매매·비중조절)을 시장상황과 연결해 서술.

{span_block(start_iso, end_iso, plabel)}

[승인된 펀드 운용 코멘트 — 당분기 (거래·운용 서술의 정본, 최우선 참고)]
{fund_q[:2200] or '(없음)'}

[승인된 펀드 운용 코멘트 — 당월]
{fund_m[:1500] or '(없음)'}

[포지셔닝·거래 데이터 (사실 근거 — 여기 없는 매매를 지어내지 말 것)]
{digest}

[승인된 시장 코멘트 — 당월]
{month_c[:1200]}

[승인된 시장 코멘트 — 당분기]
{q_c[:1200]}

[문체 예시 (타 펀드 발송본 — 이 밀도와 형식을 따를 것)]
· 중동 사태 발발 이후, 유가 및 달러 강세로 금가격 하락 → 금 비중 축소 및 국내주식 비중확대 운용 중
· 금리상승에 대응하여, 국내채권은 모두 장기채권(10년/30년 만기 국고채)으로 전환 운용 중

지시:
- 불릿 정확히 3개. 각 45~95자. 체언 종결("~운용 중", "~대응", "~확대"). 서술형("~했습니다") 금지.
- 구조: 시장 이벤트/환경 → 그에 대응한 실제 매매·비중 변화 (화살표 → 사용 가능).
- 위 데이터에 나타난 실제 비중 변화·순매수 방향과 모순되지 않게. 종목명은 대표 1~2개만.
- JSON 만 출력: {{"bullets": ["· …", "· …", "· …"]}}"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    res = client.messages.create(model=LLM_MODEL, max_tokens=900,
                                 messages=[{'role': 'user', 'content': prompt}])
    txt = re.sub(r'^```(?:json)?|```$', '', res.content[0].text.strip(), flags=re.M).strip()
    bullets = json.loads(txt)['bullets']
    bullets = [b if b.startswith('·') else f'· {b}' for b in bullets]
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({'bullets': bullets, 'digest': digest},
                                ensure_ascii=False, indent=1), encoding='utf-8')
    return bullets
