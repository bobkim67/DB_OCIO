# -*- coding: utf-8 -*-
"""자산군별 코멘트 시드 — 펀드 코멘트 공통 문단의 단일 소스 (2026-08-05 사용자 지시).

## 왜 필요한가

2026-07 승인본 실측: 08N81·08N33·08P22 의 시장동향 1문단과 전망 섹션은 **글자 그대로
동일**했고, 금을 보유하지 않는 08K88 만 금 문장이 빠져 있었다. 즉 실무에서 이미
"공통 뼈대 + 미보유 자산군 삭제" 로 운영하는데, 파이프라인은 펀드마다 LLM 이 각자
새로 쓰고 있어서 매달 손으로 통일해야 했다.

→ 공통 문단을 **기간당 1본** 만들고(시드), 펀드는 **보유 자산군 문장만 골라 조립**한다.
   펀드 간 편차가 구조적으로 0 이 된다.

## 시드 소스

- **시장동향**: 승인된 `_market` 본문(`final_comment`)을 자산군별 1~2문장으로 압축.
  문단 위치로 자르지 않고 **의미 기반 추출**이다 — debate 의 문단 구조는 프롬프트가
  보장하지 않아(현 `structure_instruction` 은 테마 기준 3~4문단인데 2026-07 산출물은
  자산군별 7문단이었다) 위치 파싱은 언제든 깨진다.
- **전망**: 시장 debate synthesis Step 3 의 `asset_outlook`. 없는 기간(이 기능 도입
  이전 승인본)은 같은 LLM 호출에서 함께 생성한다 — 소급 검증용 fallback.

## 분량 기준 (2026-07 08N81 승인본 실측)

| 구간 | 실측 |
|---|---|
| 시장동향 문단1 전체 | 653자 (총론 132 + 자산군 66~144) |
| 전망 문단 전체 | 545자 (자산군 86~207) |

자산군 6개가 모두 살아 있을 때 이 분량이 나오도록 자산군당 70~130자로 잡는다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from market_research.core.asset_class import CANONICAL_CLASSES, ordered
from market_research.core.constants import ANTHROPIC_API_KEY, LLM_MODEL
from market_research.core.json_utils import parse_json_response

SEED_CODE = '_market'
SEED_KIND = 'seed'
TOTAL_KEY = '_총론'

STATUS_DRAFT = 'draft'
STATUS_APPROVED = 'approved'


# ══════════════════════════════════════════
# 저장·로딩
# ══════════════════════════════════════════

def seed_path(period: str) -> Path:
    from market_research.report.report_store import _artifact_path
    return _artifact_path(period, SEED_CODE, SEED_KIND)


def load_seed(period: str) -> dict | None:
    p = seed_path(period)
    if p.exists():
        return json.loads(p.read_text(encoding='utf-8'))
    return None


def save_seed(period: str, data: dict) -> Path:
    p = seed_path(period)
    p.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault('period', period)
    data['saved_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return p


def approve_seed(period: str, approved_by: str = 'admin') -> dict | None:
    seed = load_seed(period)
    if not seed:
        return None
    seed['status'] = STATUS_APPROVED
    seed['approved_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    seed['approved_by'] = approved_by
    save_seed(period, seed)
    return seed


def load_approved_seed(period: str) -> dict | None:
    """승인된 시드만 반환. 미승인 draft 는 조립에 쓰지 않는다."""
    seed = load_seed(period)
    if seed and seed.get('status') == STATUS_APPROVED:
        return seed
    return None


# ══════════════════════════════════════════
# 조립 — 결정론적
# ══════════════════════════════════════════

import re as _re

# 전망 문장 앞의 기간 라벨("8월 ", "4분기 ", "2026년 하반기 ") 제거용.
# 시드에는 라벨 없이 저장하고 조립 시 **첫 문장에만** 붙인다 — 2026-07 승인본이
# "8월 국내주식시장은 … 글로벌 주식시장도 … 채권시장은 …" 처럼 첫 문장만
# 라벨을 달기 때문. 6문장이 모두 "8월"로 시작하면 단조롭고 발송본과 다르다.
_PERIOD_PREFIX_RE = _re.compile(
    r'^(?:\d{4}년\s*)?(?:\d{1,2}월|\d분기|[상하]반기|상반기|하반기)\s+')


def strip_period_prefix(s: str) -> str:
    return _PERIOD_PREFIX_RE.sub('', (s or '').strip(), count=1)


def assemble(seed: dict, active: set[str], section: str) -> str:
    """보유 자산군 문장만 골라 한 문단으로 조립.

    section : 'market' | 'outlook'
    active  : canonical 자산군 집합 (core.asset_class.active_classes 결과)

    미보유 자산군은 **삭제만** 한다 — 대체 문장을 끼워넣지 않는다
    (2026-08-05 사용자 확정). 자리를 메우려면 Admin 에서 손으로 넣는다.
    """
    seed = seed or {}
    sect = (seed.get('sections') or {}).get(section) or {}
    parts = []
    if section == 'market':
        head = (sect.get(TOTAL_KEY) or '').strip()
        if head:
            parts.append(head)
    for cls in ordered(active, section):
        s = (sect.get(cls) or '').strip()
        if s:
            parts.append(s)
    if not parts:
        return ''
    if section == 'outlook':
        label = ((seed.get('source') or {}).get('outlook_period') or '').strip()
        if label:
            parts[0] = f'{label} {strip_period_prefix(parts[0])}'
    return ' '.join(parts)


def seed_coverage(seed: dict, active: set[str], section: str) -> dict:
    """조립 전 점검용 — 보유 자산군 중 시드 문장이 비어 있는 것."""
    sect = ((seed or {}).get('sections') or {}).get(section) or {}
    want = ordered(active, section)
    missing = [c for c in want if not (sect.get(c) or '').strip()]
    return {
        'section': section,
        'expected': want,
        'missing': missing,
        'chars': len(assemble(seed, active, section)),
    }


# ══════════════════════════════════════════
# 빌드 (LLM 1회 / 기간당)
# ══════════════════════════════════════════

# 2026-07 08N81 승인본 — 사용자가 "지금 승인된 내용이 마음에 든다"고 확인한 원고.
# 톤·문장 길이·자산군 커버리지의 앵커로만 쓴다 (내용 재사용 금지).
_STYLE_ANCHOR = """[시장동향 — 653자, 총론 2문장 + 자산군별 1문장]
7월 금융시장은 중동 지정학 리스크 재점화와 반도체 투자 수익성 우려가 맞물리며 극단적인 변동성을 보였습니다. 미군의 이란 공습과 호르무즈 해협 재봉쇄로 유가가 전쟁 이전을 크게 상회하면서 인플레이션 우려와 위험회피 심리가 확산되었습니다. 글로벌 증시는 월간 소폭 상승했으나, 고금리 장기화 속 하이퍼스케일러들의 공격적 투자가 호실적에도 불구하고 잉여현금흐름 훼손 우려로 이어지면서, 성장주에서 가치주와 배당주로 로테이션이 나타났습니다. 국내 증시는 반도체 쏠림 구조가 변동성 증폭기로 작용하며 KOSPI가 장중 5,200포인트 선까지 밀리는 등 극단적 변동성이 교차하였으나, 월말 미국 기술주 반등과 삼성전자의 호실적에 힘입어 낙폭을 일부 되돌렸습니다. 금은 지정학 리스크 확대에도 유가발 인플레 우려가 실질금리를 밀어올리며 안전자산 수요를 상쇄해 월간 보합에 그쳤습니다. 외환시장에서는 달러 약세 속에서 수출 호조와 한은의 긴축 전환으로 원화 강세가 두드러지며 달러/원이 1,420원대까지 급락하였습니다.

[전망 — 545자]
8월 국내주식시장은 삼성전자의 실적 개선과 월말 낙폭 되돌림에도 불구하고, 유가 급등에 따른 인플레이션 재점화와 한은의 연속 인상 경계로 변동성이 지속될 것으로 예상합니다. 글로벌 주식시장도 호르무즈 봉쇄 리스크와 미국 장기금리 상승 부담이 위험회피 심리를 자극하고 있어, 성장주 중심의 회복까지 시간이 필요할 것으로 보입니다. 금은 지정학 리스크가 상방 요인으로 남아 있으나 미국 장기금리 상승에 따른 실질금리 부담이 이를 상쇄하고 있어, 실질금리 경로가 안정되기 전까지는 방향성이 제한적일 것으로 예상합니다."""

# 분량 예산 (2026-07 08N81 승인본 실측 기반). cap 초과 시 1회 재압축.
BUDGET = {
    'market':  {'total': (120, 150, 170), 'cls': (70, 130, 145)},
    'outlook': {'total': None,            'cls': (80, 150, 165)},
}

_RULES = """## 규칙 (반드시 준수)
1. ★ **분량이 이 작업의 핵심 제약입니다.**
   - 자산군별 문장: **1문장, {cls_lo}~{cls_hi}자**. {cls_hi}자를 넘기지 마세요.
   - `_총론`: **2문장, {tot_lo}~{tot_hi}자**.
   - 자산군 6개가 모두 살아 있을 때 시장동향 합계가 **600~700자**여야 합니다.
   원문은 자산군당 250자 이상입니다. 그대로 옮기지 말고 **핵심 인과 하나만 남기고
   덜어내세요**. 부연 사례·수치 나열·2차 파급은 버립니다.
2. 각 문장은 **단독으로 읽어도 완결**되어야 합니다. 이 문장들은 펀드마다 보유
   자산군만 골라 이어붙이므로, 앞뒤 문장이 있다고 전제하면 안 됩니다.
   - 금지: 문장 첫머리의 "이에", "또한", "반면", "이와 함께", "한편"
   - 각 문장의 주어는 해당 자산군이어야 합니다.
3. 경어체. 마크다운 기호·불릿 금지. [ref:N] 태그 금지.
4. **시장 서술은 정성적으로**. 퍼센트 등락률을 쓰지 말고 방향과 레벨로 쓰세요.
   허용: "KOSPI가 장중 5,200포인트 선까지 밀리는", "달러/원이 1,420원대까지 급락"
   금지: "KOSPI -22.1%", "7월 14일 -8.95%"
   ★ **레벨 숫자는 아래 [시장 레벨 — DB 실측] 블록에 있는 것만** 쓰세요.
   브리핑 본문에는 보통 변동률만 있고 레벨이 없어, 이 규칙이 없는 레벨을
   지어내게 만듭니다. 블록이 없으면 레벨을 아예 쓰지 말고 방향으로만 쓰세요.
   ⚠ 실측 — 시드가 8월말 달러/원을 "1,530원대"(실제 1,368.60), KOSPI 를
   "7,200포인트 터치"(월중 최고 6,977.94)로 썼습니다. 레벨의 정본은 DB 입니다.
5. ★ **`대체` 는 금(金)만 다루세요.** 리츠·유가·원자재·인프라는 쓰지 마세요.
   - 리츠는 대체 문장에 넣지 않습니다 (2026-08-05 사용자 지시).
   - 유가·원자재는 펀드 보유자산이 아니라 매크로 드라이버이므로 `_총론` 에서
     다루고, `대체` 문장의 주어로 삼지 마세요.
   - 즉 `대체` 문장의 주어는 항상 "금은 …" 입니다.
6. 특정 펀드/당사의 액션 금지 ("비중을 확대", "듀레이션을 축소" 등).
7. 근거가 없는 자산군은 **빈 문자열**로 두세요. 지어내지 마세요.
8. ★ **`FX` 문장은 원화가 왜 그렇게 움직였는지를 반드시 담으세요.**
   - 주어는 "달러/원은 …". 방향만 쓰고 끝내면 실패입니다.
   - **달러 요인과 원화 고유 요인을 구분**하세요. 달러지수(DXY) 변동폭과 원화
     변동폭을 견줘, 원화가 달러지수보다 크게 움직였으면 그 차이를 만든 **원화
     쪽 요인**(수출, 외국인 자금, 한은 정책 등)을 짚어야 합니다.
   - ⚠ 2026-08 실패 사례: 원화가 4.0% 절상됐는데 달러지수는 -0.4%뿐이었습니다.
     그런데 시드는 "달러인덱스 소폭 약세 … 소강 흐름"이라고만 써서, 10배 차이를
     만든 원화 고유 요인이 통째로 빠졌습니다. 4% 절상을 '소강'이라 쓰지 마세요.
   - 원인은 아래 [자산군별 movement] 의 drivers·인과경로에서 가져옵니다."""


# ══════════════════════════════════════════
# 시장 레벨 사실 — 레벨의 정본은 DB (SCIP)
# ══════════════════════════════════════════
# 규칙 4 가 "레벨로 쓰라"고 권하는데 debate 본문에는 변동률만 있는 경우가 많아
# 모델이 없는 레벨을 지어낸다. 2026-09-02 실측 2건 —
#   ① KOSPI "7,200 터치"(월중 최고 6,977.94) : **2026-08 운영 산출물에 실렸다**
#      (_market.seed.json + 07G07 코멘트 5파일, 승인본 포함)
#   ② 달러/원 "1,530원대"(월말 1,368.60) : 규칙 8 추가 후 재생성에서 나왔고
#      운영 산출물에는 없다 — 나가기 전에 잡았다.
# → 기초·기말·기간중 고저를 사실로 주입한다. 실패하면 블록 없이 진행 —
# 규칙 8 이 "사실 블록이 없으면 레벨을 쓰지 말라"고 지시하므로 무중단이다.
_LEVEL_SERIES = (
    (253, 15, 'KRW', 'KOSPI', 2),
    (31, 6, 'USD', '달러/원', 2),
    (105, 48, None, '달러지수(DXY)', 2),
)


def _period_bounds(period: str):
    """period 키 → (기초일, 기말일) 달력 경계. 기초 = 직전 기간의 마지막 날."""
    import datetime as _dt
    import re as _r
    from calendar import monthrange

    def eom(y, m):
        return _dt.date(y, m, monthrange(y, m)[1])

    s_ = (period or '').strip()
    today = _dt.date.today()
    m = _r.fullmatch(r'(\d{4})-(\d{2})', s_)
    if m:
        y, mo = int(m[1]), int(m[2])
        prev = eom(y - 1, 12) if mo == 1 else eom(y, mo - 1)
        return prev, min(eom(y, mo), today)
    m = _r.fullmatch(r'(\d{4})-Q([1-4])(\.QTD)?', s_)
    if m:
        y, q = int(m[1]), int(m[2])
        start = eom(y - 1, 12) if q == 1 else eom(y, (q - 1) * 3)
        end = today if m[3] else eom(y, q * 3)
        return start, min(end, today)
    m = _r.fullmatch(r'(\d{4})-H([12])\.HTD', s_)
    if m:
        y, h = int(m[1]), int(m[2])
        return (eom(y - 1, 12) if h == 1 else eom(y, 6)), today
    m = _r.fullmatch(r'(\d{4})-YTD', s_)
    if m:
        return eom(int(m[1]) - 1, 12), today
    return None


def _market_level_facts(period: str) -> list | None:
    """['- KOSPI: 6,821.32 (07/31) → 6,820.02 (08/31) · 기간중 5,593.6~6,977.9', …]."""
    try:
        bounds = _period_bounds(period)
        if not bounds:
            return None
        start, end = bounds
        import json as _json

        import pandas as _pd

        from modules.data_loader import get_pandas_connection

        def _px(blob, key=None):
            t = blob.decode('utf-8') if isinstance(blob, (bytes, bytearray)) else str(blob)
            t = t.strip()
            if t.startswith('{'):
                o = _json.loads(t)
                return float(o[key]) if key and key in o else float(list(o.values())[0])
            return float(t.replace(',', ''))

        # ⚠ OR 는 반드시 괄호로 묶는다 — 안 묶으면 AND 가 먼저 걸려 한쪽 시리즈가
        #   날짜 필터 없이 전 이력을 긁어온다.
        warm = (_pd.Timestamp(start) - _pd.Timedelta(days=40)).strftime('%Y-%m-%d')
        pairs = ' OR '.join(f'(dataset_id={d} AND dataseries_id={sid})'
                            for d, sid, *_ in _LEVEL_SERIES)
        sql = (f"SELECT dataset_id, DATE(timestamp_observation) d, data "
               f"FROM back_datapoint WHERE ({pairs}) "
               f"AND timestamp_observation >= '{warm}' "
               f"AND timestamp_observation <= '{end:%Y-%m-%d}' "
               f"ORDER BY timestamp_observation")
        conn = get_pandas_connection('SCIP')
        try:
            df = _pd.read_sql(sql, conn)
        finally:
            conn.close()
        if df.empty:
            return None

        out = []
        for ds, _sid, key, label, nd in _LEVEL_SERIES:
            sub = df[df['dataset_id'] == ds]
            if sub.empty:
                continue
            sv = _pd.Series({_pd.Timestamp(r['d']): _px(r['data'], key)
                             for _, r in sub.iterrows()}).sort_index()
            a = sv[sv.index <= _pd.Timestamp(start)]
            b = sv[sv.index <= _pd.Timestamp(end)]
            if a.empty or b.empty:
                continue
            v0, v1 = float(a.iloc[-1]), float(b.iloc[-1])
            chg = (v1 / v0 - 1) * 100 if v0 else 0.0
            # 기간 중 고저 — "장중 …까지 밀리는" 식 서술의 근거.
            win = sv[(sv.index > _pd.Timestamp(start)) & (sv.index <= _pd.Timestamp(end))]
            line = (f'- {label}: {v0:,.{nd}f} ({a.index[-1]:%m/%d}) → '
                    f'{v1:,.{nd}f} ({b.index[-1]:%m/%d}) = {chg:+.2f}%')
            if not win.empty:
                line += f' · 기간중 {win.min():,.{nd}f}~{win.max():,.{nd}f}'
            out.append(line)
        return out or None
    except Exception:
        return None


def _build_prompt(market_body: str, next_label: str,
                  consensus: list, tail_risks: list,
                  have_outlook: bool, period_label: str,
                  movement: list | None = None,
                  levels: list | None = None) -> str:
    m_lo, m_hi, _ = BUDGET['market']['cls']
    t_lo, t_hi, _ = BUDGET['market']['total']
    rules = _RULES.format(cls_lo=m_lo, cls_hi=m_hi, tot_lo=t_lo, tot_hi=t_hi)
    # JSON 스켈레톤에 자수 예산을 박아둔다 — 규칙 본문보다 이 자리가 잘 지켜진다.
    cls_json = ','.join(f'"{c}":"({m_lo}~{m_hi}자)"' for c in CANONICAL_CLASSES)
    o_lo, o_hi, _ = BUDGET['outlook']['cls']
    outlook_spec = '' if have_outlook else (
        ',"outlook":{%s}' % ','.join(
            f'"{c}":"({o_lo}~{o_hi}자)"' for c in CANONICAL_CLASSES)
    )
    outlook_task = '' if have_outlook else (
        f'\n**작업 2 — 전망**: 같은 근거로 **{next_label} 자산군별 전망**을 쓰세요.\n'
        f'   자산군당 1~2문장, {o_lo}~{o_hi}자. 회고가 아니라 전망입니다.\n'
        f'   상방·하방 요인을 함께 담아 조건부로 서술하고 단정하지 마세요.\n'
        f'   ★ 문장을 "{next_label}" 로 시작하지 마세요. 기간 라벨은 조립할 때\n'
        f'     첫 문장에만 자동으로 붙습니다. 자산군을 주어로 바로 시작하세요\n'
        f'     (예: "국내주식시장은 …", "금은 …").\n'
    )
    extra = ''
    if consensus:
        extra += '\n## 합의 포인트\n' + '\n'.join(f'- {c}' for c in consensus[:5])
    if tail_risks:
        extra += '\n\n## Tail Risk\n' + '\n'.join(f'- {t}' for t in tail_risks[:3])
    # ★ debate 의 asset_movement_commentary — 원문 본문이 놓친 **원인**이 여기 있다.
    #   2026-08 실측: 본문은 환율을 "소강 흐름"으로만 썼는데 movement 의 drivers 에는
    #   '외인 자금 유입'·'한은 인상 기조'가 들어 있었다(2026-09-01 사용자 지적).
    #   종전엔 시드가 final_comment 만 받아 이 원인이 통째로 유실됐다.
    if movement:
        _m = ['\n\n## 자산군별 movement (원인 — 본문에 없으면 여기서 가져오세요)']
        for it in movement[:6]:
            it = it or {}
            ac = it.get('asset_class', '?')
            drv = ', '.join(it.get('drivers') or [])
            pth = ' / '.join(it.get('causal_paths') or [])
            line = f'- [{ac}] {it.get("past_movement", "")}'
            if drv:
                line += f' · 원인: {drv}'
            if pth:
                line += f' · 인과경로: {pth}'
            _m.append(line)
        extra += '\n'.join(_m)
    if levels:
        extra += ('\n\n## 시장 레벨 — DB 실측 (레벨은 여기 숫자만 인용)\n'
                  + '\n'.join(levels))

    return f"""당신은 DB형 퇴직연금 OCIO 운용보고서 코멘트 작성자입니다.
아래 {period_label} 시장 브리핑을 **자산군별 문장으로 분해**하세요.

이 문장들은 여러 펀드의 운용보고서에 **그대로 인용**됩니다. 펀드마다 보유한
자산군이 달라서, 보유하지 않은 자산군의 문장은 통째로 삭제하고 나머지만
이어붙입니다. 따라서 문장 하나하나가 독립적으로 성립해야 합니다.

## {period_label} 시장 브리핑 (원문)
{market_body}
{extra}

## 작업
**작업 1 — 시장동향**: 위 원문을 자산군별로 압축하세요. 원문에 있는 사실만 쓰고
   새 사실을 넣지 마세요. `_총론`에는 특정 자산군에 속하지 않는 그 기간의
   지배적 내러티브(지정학·유가·정책 등 매크로 드라이버)를 2문장으로 쓰세요.
{outlook_task}
{rules}

## 문체·분량 앵커 (구조와 길이만 참고. 내용은 절대 재사용 금지 — 다른 기간입니다)
{_STYLE_ANCHOR}

반드시 유효한 JSON 객체 하나만 출력. 설명 텍스트 금지. 문자열 안 줄바꿈 금지.
{{"market":{{"{TOTAL_KEY}":"",{cls_json}}}{outlook_spec}}}"""


def _clean(v) -> str:
    return v.strip() if isinstance(v, str) and v.strip() else ''


def over_budget(sections: dict) -> list[tuple[str, str, int, int]]:
    """예산 초과 항목 → [(section, key, 현재자수, 목표상한)]."""
    out = []
    for sec, spec in BUDGET.items():
        body = sections.get(sec) or {}
        for key, val in body.items():
            n = len(val or '')
            if not n:
                continue
            lo, hi, cap = spec['total'] if key == TOTAL_KEY else spec['cls']
            if spec['total'] is None and key == TOTAL_KEY:
                continue
            if n > cap:
                out.append((sec, key, n, hi))
    return out


def _recompress(client, model: str, sections: dict,
                offenders: list[tuple[str, str, int, int]]) -> tuple[dict, float]:
    """예산 초과 문장만 재압축. 통과 문장은 손대지 않는다(불필요한 드리프트 방지)."""
    items = {f'{sec}|{key}': (sections[sec][key], hi)
             for sec, key, _, hi in offenders}
    listing = '\n\n'.join(
        f'### {k}  (현재 {len(v)}자 → **{hi}자 이하**로)\n{v}'
        for k, (v, hi) in items.items())
    prompt = (
        '아래 문장들이 분량 상한을 넘었습니다. **의미를 유지한 채 줄이세요**.\n\n'
        '## 규칙\n'
        '1. 각 항목을 지정된 자수 이하로 줄이세요. 핵심 인과 하나만 남기고 '
        '부연 사례·수치 나열·2차 파급을 버립니다.\n'
        '2. 문장은 단독으로 완결되어야 합니다. 첫머리에 "이에/또한/반면" 금지.\n'
        '3. 경어체 유지. 새 사실을 넣지 마세요.\n\n'
        f'## 대상\n{listing}\n\n'
        '반드시 유효한 JSON 객체 하나만 출력. 키는 위 ### 제목과 정확히 같게.\n'
        '{' + ','.join(f'"{k}":""' for k in items) + '}'
    )
    resp = client.messages.create(
        model=model, max_tokens=3000,
        messages=[{'role': 'user', 'content': prompt}])
    usage = resp.usage
    cost = usage.input_tokens * 3 / 1_000_000 + usage.output_tokens * 15 / 1_000_000
    if getattr(resp, 'stop_reason', None) == 'max_tokens':
        return sections, cost          # 잘린 재압축은 채택하지 않는다
    parsed = parse_json_response(resp.content[0].text) or {}
    out = {sec: dict(body) for sec, body in sections.items()}
    for k, (_orig, hi) in items.items():
        new = _clean(parsed.get(k))
        # 재압축이 되레 길어졌거나 비었으면 원문 유지
        if new and len(new) < len(_orig):
            sec, key = k.split('|', 1)
            out[sec][key] = new
    return out, cost


# ══════════════════════════════════════════
# 펀드별 시장동향 재압축 (2026-08-06 사용자 지시 — 2JM23 400자)
# ══════════════════════════════════════════
#
# 조립된 공통 문단이 특정 펀드 발송본의 텍스트 상자에 안 들어갈 때, **그 펀드에만**
# 짧은 판본을 만든다. 문장 단위로 잘라내면 뒤쪽 자산군(FX 등)이 통째로 사라지므로
# 자산군을 모두 살린 채 LLM 이 다시 쓴다(2026-08-06 사용자 선택).
#
# 캐시 키가 기간이 아니라 **원문 해시 + 상한**이라 같은 시드를 여러 번 조립해도
# LLM 은 1회만 돈다. 시드를 다시 승인하면 원문이 바뀌어 자동 무효화된다.

_COMPACT_CACHE = Path(__file__).resolve().parents[2] / '.cache' / 'market_seed_compact'


def _compact_cache_path(body: str, cap: int, model: str) -> Path:
    import hashlib
    h = hashlib.sha256(f'{model}\n{cap}\n{body}'.encode('utf-8')).hexdigest()[:16]
    return _COMPACT_CACHE / f'{h}.json'


def compress_market_paragraph(text: str, cap: int, *,
                              model: str | None = None) -> dict:
    """시장동향 문단을 `cap` 자 이하로 재압축.

    Returns `{'text', 'applied', 'cost', 'cached', 'reason'}`.
    **실패하면 원문을 그대로 돌려준다**(`applied=False`) — 문장을 기계적으로 잘라
    자산군을 유실시키는 것보다, 길게 두고 Admin 이 손으로 줄이는 편이 안전하다.
    호출부가 경고를 남긴다.
    """
    import anthropic

    body = (text or '').strip()
    if not body:
        return {'text': body, 'applied': False, 'cost': 0.0, 'cached': False,
                'reason': 'empty'}
    if len(body) <= cap:
        return {'text': body, 'applied': True, 'cost': 0.0, 'cached': False,
                'reason': 'already_within_cap'}

    mdl = model or LLM_MODEL
    cache = _compact_cache_path(body, cap, mdl)
    if cache.exists():
        try:
            hit = json.loads(cache.read_text(encoding='utf-8'))
            if (hit.get('text') or '') and len(hit['text']) <= cap:
                hit['cached'] = True
                return hit
        except Exception:
            pass

    # 문장 수를 세어 문장당 예산을 명시한다 — "N자 이하"만으로는 안 지켜진다
    # (시드 생성에서도 규칙 문장만으로는 1.5배 초과했다. 자수를 박아야 지켜진다).
    n_sent = max(1, body.count('다.'))
    per = max(30, int(cap * 0.92) // n_sent)

    def _prompt(target: int, feedback: str = '') -> str:
        return (
            f'아래 시장동향 문단을 **{cap}자 이하**(공백 포함)로 다시 쓰세요.\n\n'
            f'{feedback}'
            '## 규칙\n'
            f'1. ★ 전체 {cap}자 이하. 이것이 가장 중요한 제약입니다.\n'
            f'2. 원문은 {n_sent}개 문장입니다. **문장 수를 유지**하되 각 문장을 '
            f'**{per}자 안팎**으로 줄이세요. 자산군을 통째로 버리지 마세요.\n'
            '3. 각 문장에서 핵심 인과 하나만 남기고 부연 사례·2차 파급·수식어를 '
            '버립니다. 원문에 없는 사실·수치를 만들지 마세요.\n'
            '4. 경어체. 마크다운·불릿·[ref:N] 금지. 한 문단으로 이어 쓰세요.\n'
            '5. 등락률 퍼센트를 쓰지 말고 방향과 레벨로 서술하세요.\n\n'
            f'## 원문 ({len(body)}자)\n{body}\n\n'
            '재작성한 문단만 출력하세요. 설명·머리말 금지.'
        )

    cost = 0.0
    new = ''
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        # 1차는 cap, 넘치면 초과분을 알려주고 1회만 더 — 실측상 첫 시도가 근소하게
        # 넘는 일이 잦다(735→428/400). 무한 재시도는 하지 않는다.
        for attempt in (1, 2):
            fb = ('' if attempt == 1 else
                  f'⚠ 직전 시도가 {len(new)}자로 {len(new) - cap}자 초과했습니다. '
                  f'문장마다 더 덜어내세요.\n\n')
            resp = client.messages.create(
                model=mdl, max_tokens=2000,
                messages=[{'role': 'user', 'content': _prompt(cap, fb)}])
            usage = resp.usage
            cost += usage.input_tokens * 3 / 1_000_000 + usage.output_tokens * 15 / 1_000_000
            # 잘린 응답은 채택하지 않는다 ([[reference_debate_token_cap]] 의 cap 오염과 동일)
            if getattr(resp, 'stop_reason', None) == 'max_tokens':
                return {'text': body, 'applied': False, 'cost': cost, 'cached': False,
                        'reason': 'max_tokens'}
            new = _clean(resp.content[0].text)
            if new and len(new) <= cap:
                break
    except Exception as exc:
        return {'text': body, 'applied': False, 'cost': cost, 'cached': False,
                'reason': f'llm_error: {exc}'}

    if not new or len(new) > cap:
        return {'text': body, 'applied': False, 'cost': cost, 'cached': False,
                'reason': f'over_cap({len(new)}자)' if new else 'empty_response'}

    out = {'text': new, 'applied': True, 'cost': cost, 'cached': False,
           'reason': 'compressed'}
    try:
        _COMPACT_CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                         encoding='utf-8')
    except Exception:
        pass
    return out


def build_seed(period: str, market_payload: dict,
               *, model: str | None = None, period_label: str | None = None,
               next_label: str | None = None) -> dict:
    """승인된 _market payload → 자산군별 시드. LLM 1회 (기간당, 펀드 수 무관).

    market_payload 에 `asset_outlook`(debate Step 3 산출)이 있으면 전망은 그것을
    쓰고 LLM 에는 시장동향 분해만 시킨다. 없으면 같은 호출에서 함께 생성한다.
    """
    import anthropic

    body = (market_payload.get('final_comment')
            or market_payload.get('draft_comment') or '').strip()
    if not body:
        raise ValueError(f'{period} 시장 코멘트 본문이 비어 있습니다')

    supplied_outlook = {
        c: _clean(v) for c, v in (market_payload.get('asset_outlook') or {}).items()
        if c in CANONICAL_CLASSES and _clean(v)
    }
    have_outlook = bool(supplied_outlook)

    period_label = period_label or period
    next_label = (next_label or market_payload.get('asset_outlook_period')
                  or '다음 기간')

    prompt = _build_prompt(
        body, next_label,
        market_payload.get('consensus_points') or [],
        market_payload.get('tail_risks') or [],
        have_outlook, period_label,
        market_payload.get('asset_movement_commentary') or [],
        _market_level_facts(period),
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=model or LLM_MODEL,
        max_tokens=4000,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = resp.content[0].text
    usage = resp.usage
    cost = usage.input_tokens * 3 / 1_000_000 + usage.output_tokens * 15 / 1_000_000

    # ⚠ cap 잘림은 채택하지 않는다 — 잘린 JSON 이 부분 파싱되면 뒤쪽 자산군이
    #   조용히 비어버린다 ([[reference_debate_token_cap]] 과 같은 함정).
    if getattr(resp, 'stop_reason', None) == 'max_tokens':
        raise RuntimeError(
            f'{period} 시드 생성이 max_tokens 로 잘렸습니다 — 채택하지 않습니다')

    parsed = parse_json_response(text) or {}
    raw_market = parsed.get('market') or {}
    raw_outlook = supplied_outlook or (parsed.get('outlook') or {})

    market = {TOTAL_KEY: _clean(raw_market.get(TOTAL_KEY))}
    for c in CANONICAL_CLASSES:
        market[c] = _clean(raw_market.get(c))
    # 전망은 기간 라벨 없이 저장한다 (조립 시 첫 문장에만 붙임). 지시를 어기고
    # 라벨을 붙여 오는 경우가 있어 방어적으로 벗긴다.
    outlook = {c: strip_period_prefix(_clean(raw_outlook.get(c)))
               for c in CANONICAL_CLASSES}

    if not any(market.values()):
        raise RuntimeError(f'{period} 시드 파싱 실패 — raw 앞 300자: {text[:300]}')

    # ── 분량 예산 강제 (1회 재압축) ──
    # 실측: 규칙만으로는 안 지켜진다. 2026-07 로 돌렸을 때 자산군당 185~199자로
    # 목표(70~130)의 1.5배, 시장동향 합계 1,317자 vs 승인본 653자였다.
    # 조립이 결정론적이라 시드 길이가 곧 최종 분량이므로 여기서 잡아야 한다.
    sections = {'market': market, 'outlook': outlook}
    offenders = over_budget(sections)
    budget_trace = {'initial_offenders': len(offenders)}
    if offenders:
        try:
            sections, extra_cost = _recompress(
                client, model or LLM_MODEL, sections, offenders)
            cost += extra_cost
        except Exception as exc:
            budget_trace['recompress_error'] = str(exc)
    budget_trace['remaining_offenders'] = [
        {'section': s, 'key': k, 'chars': n} for s, k, n, _ in over_budget(sections)]

    return {
        'period': period,
        'status': STATUS_DRAFT,
        'sections': sections,
        'budget_trace': budget_trace,
        'source': {
            'market_approved_at': market_payload.get('approved_at', ''),
            'market_model': market_payload.get('model', ''),
            'outlook_from': 'debate_step3' if have_outlook else 'seed_builder',
            'outlook_period': next_label,
            'body_chars': len(body),
        },
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'model': model or LLM_MODEL,
        'cost_usd': round(cost, 4),
        'edit_history': [],
    }
