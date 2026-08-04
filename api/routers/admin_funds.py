# -*- coding: utf-8 -*-
"""Admin 펀드 운용 콘솔 API (2026-07-09 사용자 지시).

전 펀드(상단 선택 무관) 요약 + 2단계 승인 워크플로우:
  펀드코멘트(운영 경로, {fund}.draft/final) 생성→편집→승인
    → 승인돼야 보고서(suffix 'sentrep') 생성 가능 → 편집→승인 → client 노출.
client 노출 = 운용보고 탭(코멘트 final) / 발송 보고서 뷰(sentrep final).
⚠️ admin 계열은 인증 없는 환경에서 보안 경계 아님 (기존 admin 엔드포인트와 동일 주의).
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from api.schemas.holdings import ComplianceItemDTO, PendingSettlementDTO

REPORT_SUFFIX = 'sentrep'  # 발송 보고서 아티팩트 suffix

router = APIRouter()


# ── DTO ──

class AdminFundRowDTO(BaseModel):
    fund_code: str
    fund_name: str
    beneficiary: str | None = None    # 수익자 (FUND_BENEFICIARY)
    compliance_status: str            # breach | warn | ok | none | error
    compliance_breaches: list[str] = []   # 위반/주의 항목 라벨
    compliance: list[ComplianceItemDTO] = []  # 항목별 가이드 게이지 데이터(전 펀드 노출용)
    returns: dict[str, float] = {}    # MTD/1M/3M/6M/YTD/1Y/SI (raw ratio)
    bm_returns: dict[str, float] = {}    # 동일 기간 BM 수익률 (BM 펀드만)
    benchmark_kind: str = "none"      # BM | SAA | none
    duration_bond: float | None = None     # 채권성 가중평균 듀레이션 (년)
    ytm_bond: float | None = None          # 채권성 가중평균 YTM (%)
    duration_overall: float | None = None  # 펀드 전체 가중평균 듀레이션 (년)
    ytm_overall: float | None = None       # 펀드 전체 가중평균 YTM (%)
    # 원장 미반영 거래(해외 체결확인서에만 있는 건) — 수익자 아래 카드용 (2026-08-03).
    # 미지급금(원장 반영분)은 제외 — 카드는 '원장에 없는 것'만 알린다.
    unreflected_settlements: list[PendingSettlementDTO] = []


class AdminFundsOverviewDTO(BaseModel):
    as_of_date: str | None = None     # 스냅샷 기준일 (실제 데이터 기준일)
    rows: list[AdminFundRowDTO]


class WorkflowStageDTO(BaseModel):
    status: str
    text: str = ''
    approved_at: str = ''
    generated_at: str = ''
    excel_ready: bool = False   # 4JM12 월간: DB생명 월간보고 엑셀 생성 여부


class AdminFundWorkflowDTO(BaseModel):
    fund_code: str
    period: str
    comment: WorkflowStageDTO
    report: WorkflowStageDTO


class GenBodyDTO(BaseModel):
    kind: str    # '월간' | '분기' | 'QTD' | 'HTD' | 'YTD'
    period: str


class EditBodyDTO(BaseModel):
    period: str
    text: str


class PeriodBodyDTO(BaseModel):
    period: str


# ── 내부 헬퍼 ──

# 기간 유형 ↔ period 키 규약 (2026-07-31 사용자 확정)
#   월간 = YYYY-MM        분기 = YYYY-QN
#   QTD  = YYYY-QN.QTD    HTD  = YYYY-HN.HTD    YTD = YYYY-YTD
# TD 계열은 확정 기간 키(YYYY-QN 등)와 폴더가 분리돼 마감 산출물을 덮지 않는다.
_PERIOD_PATTERNS = {
    '월간': (r'(\d{4})-(0[1-9]|1[0-2])', '월별'),
    '분기': (r'(\d{4})-Q([1-4])', '분기'),
    'QTD': (r'(\d{4})-Q([1-4])\.QTD', 'QTD'),
    'HTD': (r'(\d{4})-H([1-2])\.HTD', 'HTD'),
    'YTD': (r'(\d{4})-YTD', 'YTD'),
}

# workflow/조회 엔드포인트가 받는 period 문자열 (위 5종 전부)
PERIOD_RE = (r'^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4]|H[1-2]|Q[1-4]\.QTD|H[1-2]\.HTD|YTD)$')


def _parse_period(kind: str, period: str) -> tuple[str, int, int]:
    spec = _PERIOD_PATTERNS.get(kind)
    if spec:
        pat, mode = spec
        mt = re.fullmatch(pat, period or '')
        if mt:
            num = int(mt.group(2)) if mt.lastindex and mt.lastindex >= 2 else 0
            return mode, int(mt.group(1)), num
    raise HTTPException(
        status_code=400,
        detail='kind/period 조합 오류 (월간=YYYY-MM, 분기=YYYY-QN, '
               'QTD=YYYY-QN.QTD, HTD=YYYY-HN.HTD, YTD=YYYY-YTD)')


def _market_source_periods(mode: str, year: int, num: int) -> tuple[str | None, list[str]]:
    """TD 기간의 시장 코멘트 소스 — (기간 전체를 덮는 상위 키, 기간 내 월간 키들).

    TD 기간 자체로는 시장 debate 를 돌리지 않으므로(사용자 확정, 2026-07-31)
    이미 승인된 시장 코멘트를 재사용한다. 상위 키(분기/반기) 승인본이 있으면
    그것 단독, 없으면 기간 내 월간 승인본을 시간순으로 묶는다.
    """
    if mode == 'QTD':
        return f'{year}-Q{num}', [f'{year}-{(num - 1) * 3 + 1 + i:02d}' for i in range(3)]
    if mode == 'HTD':
        base = 1 if num == 1 else 7
        return f'{year}-H{num}', [f'{year}-{base + i:02d}' for i in range(6)]
    if mode == 'YTD':
        return None, [f'{year}-{m:02d}' for m in range(1, 13)]
    return None, []


def _merge_market_payloads(items: list[tuple[str, dict]]) -> dict | None:
    """여러 기간 시장 코멘트 → 단일 payload.

    본문은 기간 라벨을 붙여 시간순으로 잇는다. [ref:N] 은 기간마다 독립 번호라
    합치면 충돌하고 병합본 기준 evidence 도 없어 복원이 불가능하므로 제거한다.
    전망성 항목(합의/쟁점/테일리스크/자산군 코멘트)은 가장 최근 기간 것을 쓴다.
    """
    if not items:
        return None
    if len(items) == 1:
        return items[0][1]

    from market_research.report.evidence_trace import strip_refs
    parts, claims, seen = [], [], set()
    for label, p in items:
        body = (p.get('final_comment') or p.get('draft_comment')
                or p.get('customer_comment') or '').strip()
        if body:
            parts.append(f'[{label}]\n{strip_refs(body)}')
        for cl in (p.get('claims') or []):
            try:
                key = json.dumps(cl, sort_keys=True, ensure_ascii=False)
            except TypeError:
                key = str(cl)
            if key not in seen:
                seen.add(key)
                claims.append(cl)

    last = items[-1][1]
    merged = {
        'final_comment': '\n\n'.join(parts),
        'claims': claims,
        'merged_from': [label for label, _ in items],
    }
    for k in ('consensus_points', 'tail_risks', 'disagreements',
              'asset_movement_commentary', 'asset_movement_anchors'):
        if last.get(k):
            merged[k] = last[k]
    return merged


def _resolve_market_payload(period: str, mode: str, year: int, num: int) -> dict | None:
    """생성에 쓸 시장 코멘트 payload — 같은 기간 승인본 우선, TD 는 재사용 병합."""
    from market_research.report.report_store import load_final
    exact = load_final(period, '_market')
    if exact:
        return exact
    if mode not in ('QTD', 'HTD', 'YTD'):
        return None
    umbrella, months = _market_source_periods(mode, year, num)
    if umbrella:
        up = load_final(umbrella, '_market')
        if up:
            return up
    items = [(mp, load_final(mp, '_market')) for mp in months]
    merged = _merge_market_payloads([(mp, p) for mp, p in items if p])
    return _compact_market_payload(merged)


def _compact_market_payload(merged: dict | None) -> dict | None:
    """병합 본문이 길면 기간 내러티브 1본으로 압축 (2026-07-31 사용자 지시).

    월별 나열을 그대로 넘기면 6~12개월치가 1.3~2.6만자라 펀드 코멘트 프롬프트를
    압도한다. 임계 미만이거나 압축 실패면 원문 병합본을 그대로 쓴다(기능 무중단).
    """
    if not merged or not merged.get('merged_from'):
        return merged
    from market_research.report.market_digest import build_market_digest
    body = merged.get('final_comment') or ''
    digest = build_market_digest(body, merged['merged_from'])
    if not digest:
        return merged
    out = dict(merged)
    out['final_comment'] = digest['text']
    out['market_digest'] = {
        'model': digest['model'],
        'source_chars': digest['source_chars'],
        'digest_chars': len(digest['text']),
        'source_periods': digest.get('source_periods') or merged['merged_from'],
        'cached': digest.get('cached', False),
    }
    return out


# ── 보고서 단계에 딸린 데이터 엑셀 (펀드별) ──
# 4JM12(2026-07-31): 보고서 **생성** 시 tools.dblife_monthly_excel 로 DB생명 데이터 엑셀.
#   s6 코멘트 = 1단계 승인 코멘트(final.json)가 자동 인용됨.
# 08N33(2026-08-04): 보고서 **승인** 시 성과분석 엑셀(=6월 발송본 `월간운용보고서_08N33_*`
#   과 동일 산출물). 코멘트 본문과 무관한 PA 데이터라 승인 시점에 확정본으로 굽는다.
#   6월 발송본 역산 파라미터: 기간=월초~월말 · 방법3 · pa_method='8' · SAA.
#   ⚠ FX 만 6월 발송본과 다르다 — 발송본은 'FX 분리'였으나 코멘트가 FX 포함 기준으로
#   전환돼(2026-08-04) 엑셀도 **FX 포함**으로 맞춘다(사용자 지시). 환효과를 별도 FX
#   자산군으로 떼지 않고 각 해외 자산군 수익률에 접는다 → 코멘트 분해와 같은 기준.
#   총수익률은 두 방식이 동일하고 분해만 달라진다.
_EXCEL_SPECS = {
    '4JM12': {'kind': '월간', 'on': 'generate', 'label': 'DB생명 엑셀',
              'name': 'DB생명_월간보고_데이터_{ym}.xlsx'},
    '08N33': {'kind': '월간', 'on': 'approve', 'label': '월간운용보고서 엑셀',
              'name': '월간운용보고서_08N33_{y}년{m}월말.xlsx'},
}
_EXCEL_FUND, _EXCEL_KIND = '4JM12', '월간'   # (legacy 별칭 — 기존 참조 보존)


def _excel_path(fund: str, period: str):
    from pathlib import Path as _P
    spec = _EXCEL_SPECS.get(fund)
    if not spec or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', period or ''):
        return None
    y, m = period.split('-')
    base = _P(__file__).resolve().parent.parent.parent
    return base / 'output' / spec['name'].format(
        ym=period.replace('-', ''), y=y, m=int(m))


def _build_excel(fund: str, period: str, xp) -> None:
    """펀드별 데이터 엑셀 생성. 호출자가 예외를 처리한다."""
    if fund == '4JM12':
        from tools.dblife_monthly_excel import build as build_dblife_excel
        build_dblife_excel(period, xp)
        return
    if fund == '08N33':
        import calendar
        from datetime import date as _d
        from api.services.brinson_export_service import build_brinson_export_xlsx
        from market_research.report.report_store import load_draft, load_final
        y, m = int(period[:4]), int(period[5:7])
        # Comment 시트 = 발송용 보고서(sentrep) 승인본 우선 → 없으면 ①펀드코멘트 승인본
        # → 그래도 없으면 보고서 draft. (이 함수는 보고서 승인 직후에 불리므로 보통 1순위)
        _cmt = ''
        for _get, _kw, _key in (
            (load_final, {'target_suffix': REPORT_SUFFIX}, 'final_comment'),
            (load_final, {}, 'final_comment'),
            (load_draft, {'target_suffix': REPORT_SUFFIX}, 'draft_comment'),
        ):
            _d_ = _get(period, fund, **_kw)
            if _d_ and str(_d_.get(_key) or '').strip():
                _cmt = str(_d_[_key])
                break
        content, _ = build_brinson_export_xlsx(
            fund,
            start_date=_d(y, m, 1),
            end_date=_d(y, m, calendar.monthrange(y, m)[1]),
            mapping_method='방법3', pa_method='8',
            fx_split=False, saa_mode='auto',
            comment_text=_cmt or None,
        )
        xp.parent.mkdir(parents=True, exist_ok=True)
        xp.write_bytes(content)
        return
    raise RuntimeError(f'엑셀 빌더 미정의: {fund}')


def _run_excel_step(fund: str, period: str, kind: str | None, when: str, stage) -> None:
    """해당 단계(when='generate'|'approve')에 지정된 펀드만 엑셀을 굽는다.

    kind=None 이면 유형 검사를 생략한다 — 승인 body(PeriodBodyDTO)에는 kind 가 없고,
    `_excel_path` 의 period 정규식(YYYY-MM)이 이미 월간 외 기간을 걸러낸다.
    """
    spec = _EXCEL_SPECS.get(fund)
    if not spec or spec['on'] != when or (kind is not None and spec['kind'] != kind):
        return
    xp = _excel_path(fund, period)
    if xp is None:
        return
    try:
        _build_excel(fund, period, xp)
        stage.excel_ready = True
    except Exception as exc:
        # 텍스트 보고서(draft/final)는 이미 저장됨 — 엑셀 실패만 명확히 알린다
        raise HTTPException(
            status_code=500,
            detail=f"보고서는 저장됨. {spec['label']} 생성 실패: {exc}")


def _stage(period: str, fund: str, suffix: str | None) -> WorkflowStageDTO:
    from market_research.report.report_store import get_status, load_draft, load_final
    status = get_status(period, fund, target_suffix=suffix)
    final = load_final(period, fund, target_suffix=suffix)
    draft = load_draft(period, fund, target_suffix=suffix)
    # text 는 admin 편집 상자의 내용 = **작업본(draft) 우선** (2026-08-03 fix).
    #   종전엔 승인된 final 을 우선해서, 승인 후 수정저장을 하면 draft 는 갱신됐는데
    #   화면은 구 승인본으로 되돌아갔다(= 사용자 체감 '원복'). 승인 직후엔 approve 가
    #   draft→final 을 복사하므로 둘이 같아 이 변경의 부작용이 없다.
    #   draft 가 없는 legacy/외부 반입 final 만 final 로 폴백.
    text = ''
    if draft:
        text = str(draft.get('draft_comment') or '')
    elif final:
        text = str(final.get('final_comment') or '')
    xp = _excel_path(fund, period) if suffix == REPORT_SUFFIX else None
    return WorkflowStageDTO(
        status=status, text=text,
        approved_at=str((final or {}).get('approved_at') or ''),
        generated_at=str((draft or {}).get('generated_at') or ''),
        excel_ready=bool(xp and xp.exists()),
    )


MARKET_CODE = '_market'
# 시장 debate 를 실제로 돌리는 기간 유형. TD(QTD/HTD/YTD)는 돌리지 않고 승인본을
# 재사용한다(2026-07-31 사용자 확정) — run_debate_and_save 의 else 분기가 분기 debate 라
# TD 를 그냥 넘기면 엉뚱한 기간이 생성되므로 진입에서 막는다.
_MARKET_MODES = ('월별', '분기', '반기')


def _generate(fund: str, body: GenBodyDTO, suffix: str | None) -> WorkflowStageDTO:
    mode, year, num = _parse_period(body.kind, body.period)

    # 시장 코멘트(_market)는 debate 엔진 직행 — 선행 시장 승인본이 필요 없다
    if fund == MARKET_CODE:
        if mode not in _MARKET_MODES:
            raise HTTPException(
                status_code=400,
                detail=f'{body.kind} 기간은 시장 debate 를 생성하지 않습니다 '
                       '— 월간/분기 승인본이 자동 재사용됩니다')
        from market_research.report.debate_service import run_debate_and_save
        try:
            run_debate_and_save(mode, year, num, MARKET_CODE, body.period,
                                target_suffix=suffix)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'시장 debate 실패: {exc}')
        return _stage(body.period, fund, suffix)

    market = _resolve_market_payload(body.period, mode, year, num)
    if not market:
        raise HTTPException(status_code=409,
                            detail=f'{body.period} 시장 코멘트 승인본 없음 — 시장 debate 승인 먼저')
    from market_research.report.fund_comment_service import generate_fund_comment_and_save
    try:
        generate_fund_comment_and_save(mode, year, num, fund, body.period, market,
                                       target_suffix=suffix)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'생성 실패: {exc}')
    return _stage(body.period, fund, suffix)


# ── 전 펀드 요약 ──

# 이 스냅샷의 소스(기준가 DWPM10510 · 보유 DWPM10530)는 **익일 새벽 3시 적재** 라
# 장중에 값이 바뀌지 않는다. 600s TTL 은 10분마다 20초 재계산(펀드당 ~2s x 11)을
# 유발해 워밍업 선채움이 무의미했다 → **적재 시각 기준 '데이터 세대'** 로 무효화한다.
# (고정 20h TTL 은 갱신 시점이 매일 4시간씩 당겨져 언젠가 03시 적재 **이전**에 캐시가
#  채워지고, 그날 하루 종일 전일 데이터를 서빙하게 되므로 채택하지 않음.)
_OVERVIEW_LOAD_HOUR = 3                   # DB 적재 시각(새벽 3시) = 세대 경계
_OVERVIEW_TTL = 20 * 3600.0               # 상한 백스톱(세대가 안 바뀌는 이상상황 방어)
_overview_cache: dict = {}                # {as_of|None: (monotonic_ts, generation, DTO)}
_overview_lock = __import__('threading').Lock()


def _overview_generation() -> str:
    """현재 데이터 세대 키 — 03시 이전이면 전일 세대."""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(hours=_OVERVIEW_LOAD_HOUR)).strftime('%Y-%m-%d')


@router.get('/admin/funds-overview', response_model=AdminFundsOverviewDTO)
def get_admin_funds_overview(
    as_of: str | None = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
) -> AdminFundsOverviewDTO:
    """전 펀드 스냅샷: 컴플라이언스 가이드(항목별) + 기간수익률 + 채권/펀드 듀레이션·YTM.
    as_of(YYYY-MM-DD) 미지정 시 최신 영업일 기준.

    응답 캐시 — 펀드당 ~2s x 11 재계산 방지. 서버 웜업이 선채움
    (api/warmup._warm_admin_overview, 2026-07-14). 소스가 새벽 3시 적재라
    **데이터 세대(03시 경계 일단위)** 가 바뀔 때만 무효화 → 하루 1회 재계산.
    """
    import time as _time
    gen = _overview_generation()
    with _overview_lock:
        hit = _overview_cache.get(as_of)
        if (hit and hit[1] == gen
                and _time.monotonic() - hit[0] < _OVERVIEW_TTL):
            return hit[2]
    dto = _build_funds_overview(as_of)
    with _overview_lock:
        _overview_cache[as_of] = (_time.monotonic(), gen, dto)
    return dto


def _build_funds_overview(as_of: str | None) -> AdminFundsOverviewDTO:
    from config.funds import FUND_LIST, FUND_META, FUND_BENEFICIARY

    _SEV = {'breach': 3, 'warn': 2, 'ok': 1, 'none': 0}
    _RET_KEYS = ('MTD', '1M', '3M', '6M', 'YTD', '1Y', 'SI')
    rows: list[AdminFundRowDTO] = []
    snapshot: str | None = None
    for fund in FUND_LIST:
        # 컴플라이언스 가이드 + 듀레이션/YTM — holdings 재사용 (인메모리 캐시)
        comp_status, breaches = 'error', []
        comp_items: list[ComplianceItemDTO] = []
        d_bond = y_bond = d_all = y_all = None
        unreflected: list[PendingSettlementDTO] = []
        try:
            from api.services.holdings_service import build_holdings
            h = build_holdings(fund, lookthrough=True, as_of_date=as_of)
            comp_items = list(getattr(h, 'compliance', None) or [])
            worst = 0
            for c in comp_items:
                s = getattr(c, 'status', 'none')
                worst = max(worst, _SEV.get(s, 0))
                if s in ('breach', 'warn'):
                    breaches.append(f'{getattr(c, "label", "?")}({s})')
            comp_status = {3: 'breach', 2: 'warn', 1: 'ok', 0: 'none'}[worst]
            ds = getattr(h, 'duration_summary', None)
            if ds is not None:
                d_bond, y_bond = ds.duration_bond, ds.ytm_bond
                d_all, y_all = ds.duration_overall, ds.ytm_overall
            if snapshot is None and getattr(h, 'as_of_date', None):
                snapshot = str(h.as_of_date)
            unreflected = [
                p for p in (getattr(h, 'pending_settlements', None) or [])
                if p.source == 'mail'
            ]
        except Exception:
            pass
        # 기간수익률 + 동일기간 BM 수익률 (as_of 앵커)
        rets: dict[str, float] = {}
        bm_rets: dict[str, float] = {}
        bm_kind = 'none'
        try:
            from api.services.overview_service import build_period_returns
            pr = build_period_returns(fund, end_date=as_of)
            rets = {k: v for k, v in (pr.period_returns or {}).items() if k in _RET_KEYS}
            bm_rets = {k: v for k, v in (pr.bm_period_returns or {}).items() if k in _RET_KEYS}
            bm_kind = pr.benchmark_kind
        except Exception:
            pass
        rows.append(AdminFundRowDTO(
            fund_code=fund,
            fund_name=str(FUND_META.get(fund, {}).get('name', '')),
            beneficiary=FUND_BENEFICIARY.get(fund),
            compliance_status=comp_status,
            compliance_breaches=breaches,
            compliance=comp_items,
            returns=rets,
            bm_returns=bm_rets,
            benchmark_kind=bm_kind,
            duration_bond=d_bond, ytm_bond=y_bond,
            duration_overall=d_all, ytm_overall=y_all,
            unreflected_settlements=unreflected,
        ))
    return AdminFundsOverviewDTO(as_of_date=snapshot or as_of, rows=rows)


# ── 워크플로우 조회 ──

@router.get('/admin/funds/{fund}/workflow', response_model=AdminFundWorkflowDTO)
def get_fund_workflow(
    fund: str = Path(..., min_length=1, max_length=32),
    period: str = Query(..., pattern=PERIOD_RE),
) -> AdminFundWorkflowDTO:
    return AdminFundWorkflowDTO(
        fund_code=fund, period=period,
        comment=_stage(period, fund, None),
        report=_stage(period, fund, REPORT_SUFFIX),
    )


# ── 펀드코멘트 (1단계) ──

@router.post('/admin/funds/{fund}/comment/generate', response_model=WorkflowStageDTO)
def generate_comment(body: GenBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    return _generate(fund, body, None)


@router.put('/admin/funds/{fund}/comment/draft', response_model=WorkflowStageDTO)
def edit_comment(body: EditBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    from market_research.report.report_store import update_draft_comment
    if update_draft_comment(body.period, fund, body.text) is None:
        raise HTTPException(status_code=404, detail='draft 없음 — 먼저 생성')
    return _stage(body.period, fund, None)


@router.post('/admin/funds/{fund}/comment/approve', response_model=WorkflowStageDTO)
def approve_comment(body: PeriodBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    from market_research.report.report_store import approve_and_save_final
    if approve_and_save_final(body.period, fund) is None:
        raise HTTPException(status_code=404, detail='draft 없음 — 먼저 생성')
    return _stage(body.period, fund, None)


# ── 보고서 (2단계 — 코멘트 승인 게이트) ──

@router.post('/admin/funds/{fund}/report/generate', response_model=WorkflowStageDTO)
def generate_report(body: GenBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    """보고서(발송용) 생성 = **① 승인 코멘트 시드 복사** (2026-07-31 사용자 확정).

    종전에는 ①과 동일한 LLM 파이프라인을 재실행했는데(도입 시점의 Phase 2 자리),
    ① 생성이 발송본 서식 잇기를 이미 수행해 재생성은 비용·문구 불일치만 남았다.
    → ①의 final_comment 를 draft 로 복사하고 편집→승인 사이클만 유지한다.
    """
    _parse_period(body.kind, body.period)   # kind/period 검증
    # 시장 코멘트는 발송용 보고서 단계가 없다 — client 는 /market-report 로 승인본을 직접 본다
    if fund == MARKET_CODE:
        raise HTTPException(status_code=400,
                            detail='시장 코멘트는 발송용 보고서 단계가 없습니다')
    import time as _time
    from market_research.report.report_store import STATUS_DRAFT, load_final, save_draft
    cf = load_final(body.period, fund)
    if not (cf and cf.get('approved')):
        raise HTTPException(status_code=409,
                            detail='펀드코멘트가 먼저 승인돼야 보고서 생성 가능')
    save_draft(body.period, fund, {
        'report_type': 'fund',
        'status': STATUS_DRAFT,
        'draft_comment': str(cf.get('final_comment') or ''),
        'generated_at': _time.strftime('%Y-%m-%dT%H:%M:%S'),
        'model': 'seed-copy(comment.final)',
        'cost_usd': 0,
        'seeded_from': 'comment.final',
        'seeded_comment_approved_at': str(cf.get('approved_at') or ''),
        'debate_run_id': cf.get('approved_debate_run_id'),   # lineage 승계
        'edit_history': [],
    }, target_suffix=REPORT_SUFFIX)
    stage = _stage(body.period, fund, REPORT_SUFFIX)
    _run_excel_step(fund, body.period, body.kind, 'generate', stage)
    return stage


@router.get('/admin/funds/{fund}/report/excel')
def download_report_excel(fund: str = Path(..., max_length=32),
                          period: str = Query(..., max_length=10)):
    """4JM12 월간 DB생명 데이터 엑셀 다운로드 (보고서 생성 시 산출)."""
    from fastapi.responses import FileResponse
    xp = _excel_path(fund, period)
    if xp is None or not xp.exists():
        raise HTTPException(status_code=404, detail='엑셀 없음 — 보고서 생성 먼저')
    return FileResponse(str(xp), filename=xp.name)


@router.put('/admin/funds/{fund}/report/draft', response_model=WorkflowStageDTO)
def edit_report(body: EditBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    from market_research.report.report_store import update_draft_comment
    if update_draft_comment(body.period, fund, body.text,
                            target_suffix=REPORT_SUFFIX) is None:
        raise HTTPException(status_code=404, detail='보고서 draft 없음 — 먼저 생성')
    return _stage(body.period, fund, REPORT_SUFFIX)


@router.post('/admin/funds/{fund}/report/approve', response_model=WorkflowStageDTO)
def approve_report(body: PeriodBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    from market_research.report.report_store import approve_and_save_final
    if approve_and_save_final(body.period, fund, target_suffix=REPORT_SUFFIX) is None:
        raise HTTPException(status_code=404, detail='보고서 draft 없음 — 먼저 생성')
    stage = _stage(body.period, fund, REPORT_SUFFIX)
    _run_excel_step(fund, body.period, None, 'approve', stage)
    return stage
