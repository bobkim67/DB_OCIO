"""s4 코멘트 자동 생성 (2026-07-13 사용자 승인 — 발송본 작성 방식 재현 검증 완료).

구성 (발송본 역공학):
  1) 순위 문장·헤드라인 = 좌측 표 데이터에서 결정론적 유도 (발송본 문자열 재현 테스트 통과)
  2) 정성 문장 = 승인된 시장 코멘트(_market.final: 당월 + 당분기) LLM 압축 요약
     — 운용보고 체인과 동일 모델(Opus). 실패 시 순위 문장만으로 폴백.
결과는 OUT/s4_manual_{end}.json 캐시 → 재빌드 시 LLM 재호출 없음 (수동 편집도 이 파일).
"""
import json
import re

from .common import OUT, REPO


# ──────────────────────────── 1) 순위 문장 (결정론) ────────────────────────────
def _row_map(rows):
    m = {}
    for i, r in enumerate(rows):
        m[(r.get('sub', ''), r['label'], i)] = r
    return rows


def _find(rows, label, sub=None, after=0):
    for i, r in enumerate(rows):
        if i < after:
            continue
        if r['label'] == label and (sub is None or r.get('sub', '') == sub):
            return r
    return None


def derive_rankings(data):
    """표 데이터 → (헤드라인, 섹션별 순위 문장 dict). 발송본 재현 검증(2026-07-13)."""
    rows = data['rows']
    v = lambda r, k='v1': (r or {}).get(k)

    eq = {'미국외 선진국': v(_find(rows, '일반', '미국외 선진국'), 'v2'),
          '미국': v(_find(rows, '시장', '미국'), 'v2'),
          '신흥국': v(_find(rows, '일반', '신흥시장'), 'v2'),
          '한국': v(_find(rows, '시장', '국내'), 'v2')}
    sty = {'성장주': v(_find(rows, '성장')), '시장': v(_find(rows, '시장', '미국')),
           '가치주': v(_find(rows, '가치')), '고배당': v(_find(rows, '고배당')),
           '중소형': v(_find(rows, '중소형'))}
    kb = _find(rows, '종합채권', '국내') or _find(rows, '종합채권')
    ub = _find(rows, '종합채권', '미국') or _find(rows, '종합채권', after=rows.index(kb) + 1)
    bd = {'한국종합채권': v(kb), '미국 종합채권': v(ub),
          '미국 투자등급': v(_find(rows, '투자등급')), '미국하이일드': v(_find(rows, '하이일드')),
          '신흥국 달러표시채권': v(_find(rows, '달러국채'))}

    def rank(d):
        ok = {k: x for k, x in d.items() if x is not None}
        return ' < '.join(sorted(ok, key=ok.get))

    def lt(a, b):
        return None if a is None or b is None else (a < b)

    # 헤드라인: 발송본 5쌍 부등호 (방향은 데이터로 결정)
    pairs = [
        ('국내채권', v(kb), '국내주식', v(_find(rows, '시장', '국내'))),
        ('해외채권', v(_find(rows, '글로벌 (UH)')), '해외주식', v(_find(rows, '글로벌'))),
        ('선진국주식', v(_find(rows, '일반', '선진국')), '신흥국주식', v(_find(rows, '일반', '신흥시장'))),
        ('원화', 0.0, '달러인덱스 바스켓', v(_find(rows, '달러 인덱스'))),
        ('금', v(_find(rows, 'Gold')), '원유', v(_find(rows, 'WTI', '원자재'))),
    ]
    hl = []
    for a, av, b, bv in pairs:
        r = lt(av, bv)
        if r is None:
            continue
        hl.append(f'{a} < {b}' if r else f'{b} < {a}')
    return {
        'headline': ', '.join(hl),
        'eq_rank': f'· 환 노출 성과: {rank(eq)}',
        'us_rank': f'· 미국: {rank(sty)}',
        'bd_rank': f'· 표시 통화 성과: {rank(bd)}',
    }


# ──────────────────────────── 2) 정성 문장 (승인 코멘트 LLM 요약) ────────────────────────────
def _load_final(period):
    p = REPO / 'market_research' / 'data' / 'report_output' / period / '_market.final.json'
    if not p.exists():
        return None
    fc = json.loads(p.read_text(encoding='utf-8')).get('final_comment', '')
    return re.sub(r'\[(?:ref|claim):[^\]]+\]', '', fc)


def _llm_qualitative(end_date, rankings, table_digest):
    from market_research.core.constants import ANTHROPIC_API_KEY, LLM_MODEL
    import anthropic
    y, m = end_date[:4], int(end_date[5:7])
    month_c = _load_final(f'{y}-{m:02d}')
    q_c = _load_final(f'{y}-Q{(m - 1) // 3 + 1}')
    if not month_c and not q_c:
        raise RuntimeError('승인된 _market.final 없음')
    prompt = f"""아래는 판매사 발송용 운용보고 PPT 4페이지(자산군별 기간수익률 표) 우측 코멘트 작성 작업이다.

[좌측 표 요약 (기간수익률)]
{table_digest}

[순위 문장 (각 섹션 첫 불릿으로 이미 확정 — 다시 쓰지 말 것)]
{rankings['eq_rank']}
{rankings['bd_rank']}

[사전 승인된 시장 코멘트 — 당월]
{month_c or '(없음)'}

[사전 승인된 시장 코멘트 — 당분기]
{q_c or '(없음)'}

지시:
- 3개 섹션(글로벌 주식 / 글로벌 채권 / 대체·통화)의 **정성 불릿만** 작성하라.
- 각 불릿은 승인된 시장 코멘트의 내용만 근거로 하고, 새로운 사실·수치를 만들지 마라.
- 문체: 발송본 체언 종결. 서술형 종결("~됩니다") 금지. 아래 발송본 예시의 밀도·톤을 따르라.
  예시(2026-06 발송본): "글로벌 경기 회복 및 위험자산 선호에 따른 한국(반도체 중심)의 성과 우위" /
  "지정학적 리스크 및 인플레 우려에도 불구하고 미국의 견조한 매크로 펀더멘털 기반으로 크레딧 스프레드 축소세 지속" /
  "금: 글로벌 중앙은행 수요와 금리 인하 기대에 급등했으나, 미-이란 전쟁 발 유가 및 금리 상승 우려, 달러 강세가 겹치며 급락"
- 각 불릿 40~90자 (공백 포함, 초과 금지 — 공간 제약). 구체적 동인(정책·이벤트·수급)을 담아 정보 밀도 높게.
- 글로벌 주식: 1~2개 (순위의 원인). 글로벌 채권: 2~3개 (미국 크레딧·한국 채권 등). 대체·통화: 금 1개 + 통화 1개.
- JSON 만 출력: {{"주식": ["…"], "채권": ["…", "…"], "대체통화": ["· 금: …", "· 통화: …"]}}
  (불릿 머리 "· " 포함)"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    res = client.messages.create(model=LLM_MODEL, max_tokens=1500,
                                 messages=[{'role': 'user', 'content': prompt}])
    txt = res.content[0].text.strip()
    txt = re.sub(r'^```(?:json)?|```$', '', txt, flags=re.M).strip()
    return json.loads(txt)


def build_manual(data, end_date, use_llm=True, tag=''):
    """s4 manual dict {'headline','comments'} 생성 + 캐시. 캐시 파일 수동 편집 가능.

    tag: 커스텀 구간 시작일 등 캐시 구분자 (YTD 기본은 빈 문자열).
    """
    suffix = f'_{tag.replace("-", "")}' if tag else ''
    cache = OUT / f's4_manual_{end_date.replace("-", "")}{suffix}.json'
    if cache.exists():
        return json.loads(cache.read_text(encoding='utf-8'))
    rk = derive_rankings(data)
    digest = '\n'.join(
        f"{r.get('sub', '')} {r['label']}: v1 {r['v1']}%, 원화환산 {r['v2']}%"
        for r in data['rows'] if r['v1'] is not None)
    qual = {'주식': [], '채권': [], '대체통화': []}
    if use_llm:
        try:
            qual = _llm_qualitative(end_date, rk, digest)
        except Exception as e:            # noqa: BLE001 — LLM 실패 시 순위 문장만
            print(f'[s4-comment] LLM 생략: {e}')
    _b = lambda xs: [x if x.startswith('·') else f'· {x}' for x in xs]   # 불릿 머리 정규화
    manual = {
        'headline': rk['headline'],
        'comments': [
            {'label': '글로벌<br>주식', 'lines': [rk['eq_rank'], rk['us_rank']] + _b(qual.get('주식', []))},
            {'label': '글로벌<br>채권', 'lines': [rk['bd_rank']] + _b(qual.get('채권', []))},
            {'label': '대체/<br>통화', 'lines': _b(qual.get('대체통화', []))},
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(manual, ensure_ascii=False, indent=1), encoding='utf-8')
    return manual
