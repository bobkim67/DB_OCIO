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
import time

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
    excel_ready: bool = False   # 보고서 단계 산출물(엑셀/PPT) 존재 여부 — _EXCEL_SPECS
    # 산출물 빌더가 남긴 경고. 승인 응답에만 실린다(GET workflow 는 빈 리스트) —
    # 2JM23 PPT 의 템플릿 승계·현금 잔여 경고처럼 발송 전 눈으로 봐야 하는 것들.
    build_warnings: list[str] = []


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


# ── 자산군 시드 (2026-08-05) ──
# 공통 문단(시장동향·전망)을 기간당 1본 만들어 전 펀드가 공유한다.
# 펀드 코멘트 생성은 **승인된 시드만** 사용한다 (draft 는 무시).

class SeedSectionDTO(BaseModel):
    market: dict[str, str] = {}
    outlook: dict[str, str] = {}


class SeedDTO(BaseModel):
    period: str
    status: str = 'not_generated'
    sections: SeedSectionDTO = SeedSectionDTO()
    outlook_period: str = ''
    generated_at: str = ''
    approved_at: str = ''
    model: str = ''
    cost_usd: float = 0
    over_budget: list[dict] = []
    classes: list[str] = []
    # 서술 순서 — 프론트 미리보기가 순서를 추측하지 않도록 서버가 내려준다
    # (시장동향과 전망의 관행적 순서가 다르다: core.asset_class 참조).
    market_order: list[str] = []
    outlook_order: list[str] = []


class SeedEditBodyDTO(BaseModel):
    period: str
    sections: SeedSectionDTO


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
    # 설정이후 — 펀드마다 설정일이 달라 **펀드 코멘트 전용**이다. 시장 코멘트
    # (`_market`)는 펀드 무관이라 SI 라는 개념이 성립하지 않는다(아래 주석 참조).
    '설정이후': (r'(\d{4})-SI', 'SI'),
}

# workflow/조회 엔드포인트가 받는 period 문자열 (위 5종 전부)
PERIOD_RE = (r'^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4]|H[1-2]|Q[1-4]\.QTD|H[1-2]\.HTD|YTD|SI)$')


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
               'QTD=YYYY-QN.QTD, HTD=YYYY-HN.HTD, YTD=YYYY-YTD, '
               '설정이후=YYYY-SI)')


# ── 시장 코멘트 payload 해석 ──
# ★ 구현은 `market_research/report/market_payload.py` 로 옮겼다 (2026-09-02).
#   운용보고 PPT(`reporting/builder/*`)가 같은 스킴을 써야 하는데 라우터를 import 할
#   수 없어서다. 여기서는 **기존 이름 그대로 재노출**만 한다 — 동작·테스트 불변.
from market_research.report.market_payload import (  # noqa: E402
    compact_market_payload as _compact_market_payload,
    market_source_periods as _market_source_periods,
    merge_market_payloads as _merge_market_payloads,
    resolve_market_payload as _resolve_market_payload,
)


# ── 보고서 단계에 딸린 데이터 엑셀 (펀드별) ──
# 4JM12(2026-07-31): 보고서 **생성** 시 tools.dblife_monthly_excel 로 DB생명 데이터 엑셀.
#   s6 코멘트 = 1단계 승인 코멘트(final.json)가 자동 인용됨.
# 08N33·08N81(2026-08-04): 보고서 **승인** 시 성과분석 엑셀(=6월 발송본
#   `월간운용보고서_{fund}_*` 과 동일 산출물). 코멘트와 무관한 PA 데이터라 승인 시점에 굽는다.
#   ★ brinson 옵션은 spec 의 'brinson' 에 담아 `_build_excel` 이 그대로 넘긴다(하드코딩 금지).
#   6월 발송본 헤더 역산값은 펀드마다 달랐다:
#       08N33 = FX 분리 · SAA / 08N81 = FX 포함 · SAA / 08P22 = FX 포함 · SAA(**proxy**)
#   ⚠ 현재는 셋 다 **08N33 7월 기준(FX 포함 · 등록 SAA)으로 통일**한다 (2026-08-04 사용자
#     지시). 발송본과 달라지는 지점 2곳:
#       · 08N33 FX 분리→포함  — 코멘트가 FX 포함 기준으로 전환된 데 맞춤
#       · 08P22 proxy→등록 SAA — 벤치마크 기준선이 바뀌므로 6월 발송본과 SAA 수치가 다름
#     둘 다 총수익률(AP)은 불변이고 분해·벤치 비교만 달라진다.
SHINHAN_PPT_FUND = '2JM23'

_EXCEL_SPECS = {
    # 2026-08-06: on 'generate' → 'approve' 로 통일 (사용자 지시). 종전엔 4JM12 만
    # 보고서 생성 시 구워져 다른 5개 펀드와 동작이 달랐다. 이제 전부 승인 시 재생성.
    '4JM12': {'kind': '월간', 'on': 'approve', 'label': 'DB생명 엑셀',
              'name': 'DB생명_월간보고_데이터_{ym}.xlsx'},
    '08N33': {'kind': '월간', 'on': 'approve', 'label': '월간운용보고서 엑셀',
              'name': '월간운용보고서_08N33_{y}년{m}월말.xlsx',
              'brinson': {'fx_split': False, 'saa_mode': 'auto'}},
    '08N81': {'kind': '월간', 'on': 'approve', 'label': '월간운용보고서 엑셀',
              'name': '월간운용보고서_08N81_{y}년{m}월말.xlsx',
              'brinson': {'fx_split': False, 'saa_mode': 'auto'}},
    '08P22': {'kind': '월간', 'on': 'approve', 'label': '월간운용보고서 엑셀',
              'name': '월간운용보고서_08P22_{y}년{m}월말.xlsx',
              'brinson': {'fx_split': False, 'saa_mode': 'auto'}},
    # 08K88 = 위 셋과 달리 **실제 BM 펀드**(SAA 아님). saa_mode 는 BM 펀드에도
    # 비중방식(fixed/drift)으로 작용하는데 'auto'=fixed(constant-mix)라 골든 기본값과
    # 같다 → 옵션은 나머지 셋과 동일하게 둔다 (2026-08-05 사용자 확정).
    # ⚠ 08K88 은 기간 창이 달력월이 아니다 — `core.period_window.FUND_MONTH_WINDOW`
    #   에 등록돼 있고 코멘트 경로도 같은 정의를 쓴다 (2026-08-05 사용자 확정).
    '08K88': {'kind': '월간', 'on': 'approve', 'label': '월간운용보고서 엑셀',
              'name': '월간운용보고서_08K88_{y}년{m}월말.xlsx',
              'brinson': {'fx_split': False, 'saa_mode': 'auto'}},
    # 신한라이프 월간보고 데이터 엑셀 (Comment + 자산배분현황 2시트).
    # PPT COM 치환기는 2026-08-06 폐기 — 이 엑셀에서 **블록 복사 → 발송본 PPT 표에
    # 붙여넣기** 한다. name 은 `tools.shinhan_monthly_excel.OUT_NAME` 과 반드시
    # 같아야 한다(빌더가 자기 경로에 쓰고 여기서는 그 경로를 읽는다). 테스트가 고정.
    '2JM23': {'kind': '월간', 'on': 'approve', 'label': '신한라이프 엑셀',
              'name': '한국투자신탁운용_신한라이프_운용보고서(글로벌자산배분B형)_{ym}_데이터.xlsx'},
    # KB국민은행 투자풀 월간 붙여넣기용 (표 + 서술 + FactSheet 3시트, 2026-08-07).
    # 신한 PPT 와 같은 전환 — Word COM 치환기(tools.kb_monthly_report.build_docx)는
    # 쓰지 않고 이 엑셀에서 블록 복사 → 워드 표에 붙여넣는다.
    # ★ 07G07 은 매월 **워드 + FactSheet 2종**이 나간다. 스펙은 펀드당 산출물 1개만
    #   지원하므로(엔드포인트·프론트 버튼 각 1개) FactSheet 는 별도 스펙을 만들지 않고
    #   같은 워크북의 **3번째 시트**로 얹었다 (2026-09-01 사용자 지시).
    # name 은 `tools.kb_monthly_excel.OUT_NAME` 과 반드시 같아야 한다(테스트가 고정).
    '07G07': {'kind': '월간', 'on': 'approve', 'label': 'KB 워드 엑셀',
              'name': 'KB국민은행_07G07_월간워드_데이터_{ym}.xlsx'},
}


def _excel_period_window(fund: str, y: int, m: int):
    """엑셀 기간 창 → (start_date, end_date) — build_brinson 인자 규약.

    ★ `build_brinson(start, end)` 의 AP 는 **start 당일 손익부터 포함**한다
      (= 기준가로는 start 직전 영업일 종가 → end 종가).
      실측(08K88 2026-07): (7/1, 7/30) → -16.9648% (기준가 6/30→7/30) /
      (6/30, 7/30) → **-16.0226%** (기준가 6/29→7/30, 사용자 확인값).

    창 정의는 `market_research.core.period_window` 단일 소스 — 코멘트 경로와
    같은 함수를 쓴다. 한쪽만 고치면 같은 보고서 안에서 수익률이 갈린다
    (2026-07 실측 4.85%p 괴리).

    미등록 펀드는 종전대로 당월 1일 ~ 당월 말일 (골든 불변).
    """
    import calendar
    from datetime import date as _date
    from market_research.core.period_window import month_window

    win = month_window(fund, y, m)
    if not win:
        return _date(y, m, 1), _date(y, m, calendar.monthrange(y, m)[1])
    return win['first_incl'], win['last']
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


def _build_excel(fund: str, period: str, xp) -> list[str]:
    """펀드별 보고서 산출물 생성 → 빌더 경고 리스트. 호출자가 예외를 처리한다."""
    if fund == '4JM12':
        from tools.dblife_monthly_excel import build as build_dblife_excel
        return list((build_dblife_excel(period, xp) or {}).get('warnings') or [])
    if fund == SHINHAN_PPT_FUND:
        # 코멘트 승인본이 Comment 시트 소스 — 없으면 빈 칸으로 나가므로 여기서 막는다.
        from market_research.report.report_store import load_final as _lf
        cf = _lf(period, fund)
        if not (cf and cf.get('approved')):
            raise RuntimeError('펀드 코멘트 승인본 없음 (Comment 시트 소스)')
        from tools.shinhan_monthly_excel import build as build_shinhan_xlsx
        return list(build_shinhan_xlsx(period, xp).get('warnings') or [])
    if fund == '07G07':
        # 서술 시트는 LLM 1회를 태운다 — 승인 응답이 그만큼 늦어진다(수십 초).
        from tools.kb_monthly_excel import build as build_kb_xlsx
        return list(build_kb_xlsx(period, xp).get('warnings') or [])
    _spec = _EXCEL_SPECS.get(fund) or {}
    _bo = _spec.get('brinson')
    if _bo:
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
        _start, _end = _excel_period_window(fund, y, m)
        content, _ = build_brinson_export_xlsx(
            fund,
            start_date=_start,
            end_date=_end,
            mapping_method='방법3', pa_method='8',
            comment_text=_cmt or None,
            **_bo,                      # fx_split / saa_mode — 펀드별 발송본 역산값
        )
        xp.parent.mkdir(parents=True, exist_ok=True)
        xp.write_bytes(content)
        return []
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
        stage.build_warnings = _build_excel(fund, period, xp)
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


# ── 신한라이프 월간보고 엑셀 (2JM23) ──
# `tools/shinhan_monthly_excel.py` — Comment + 자산배분현황 2시트. 발송본 PPT 표에
# **블록 복사로 붙여넣는 데이터 소스**다(2026-08-06 사용자 지시로 PPT COM 치환기 폐기).
#
# 배선은 SAA 펀드 엑셀과 동일 — 전용 엔드포인트 없이 `_EXCEL_SPECS['2JM23']` 에 얹어
# 보고서 승인 시 재생성 + 승인 버튼 우측 다운로드(`/report/excel`).
# 재생성은 **승인을 다시 누르면** 된다(approve 는 멱등).


# ── 리서치 wiki 뷰어 (2026-08-06) ──
# 자산군별 09_Research_Synthesis + claim 전량 + 원본 링크. **조회 전용**.
#
# 배경: 09 는 자산군당 salience 상위 N(§2 8 / §4 12 / §5 6)만 싣는다. 2026-07
# 환율(FX)은 111건 중 12건만 실려 엔캐리 청산 claim(45위)이 통째로 빠졌고, 09 가
# debate primary source 라 시장 코멘트에도 그 주제가 없었다. 무엇이 잘렸는지
# 눈으로 볼 수 있어야 해서 **전량 + 09 채택 표시**로 낸다 (2026-08-06 사용자 확정).

class ClaimSourceDTO(BaseModel):
    title: str = ''
    date: str = ''
    broker: str = ''
    lane: str = ''          # naver_research | broker_mail
    url: str = ''           # broker_mail 은 URL 부재 → 빈 문자열
    attachments: str = ''   # broker_mail 첨부파일명 (원본 추적용)


class ClaimRowDTO(BaseModel):
    claim_id: str
    text: str
    stance: str = ''
    direction: str = ''
    horizon: str = ''
    confidence: float = 0
    salience: float = 0
    source_type: str = ''
    broker: str = ''
    adopted: bool = False       # 09 페이지에 실렸는지
    rank: int = 0               # 자산군 내 salience 순위 (1-base)
    sources: list[ClaimSourceDTO] = []
    # ★ claim_text 는 프롬프트상 "한 줄 요약(≤180자)" 이라 원인분석이 안 담긴다.
    #   실제 인과는 아래 세 필드에 있다 — 이걸 안 보여주면 "사건 나열인데 왜 sal 이
    #   높냐"는 오해가 생긴다 (2026-08-06 사용자 지적).
    rationale: str = ''
    risk_factor: str = ''
    causal_chain: list[str] = []     # "A →relation→ B" 문자열로 평탄화


class ResearchWikiDTO(BaseModel):
    period: str
    asset: str = ''
    assets: list[str] = []
    page_md: str = ''
    page_generated_at: str = ''
    page_stale: bool = False        # claims 가 09 보다 최신 → 재생성 대기
    claims_total: int = 0
    adopted_total: int = 0
    claims: list[ClaimRowDTO] = []


def _research_period_re(period: str) -> bool:
    return bool(re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', period or ''))


def _load_lane_index(period: str) -> dict:
    """evidence_id → (lane, article). naver_research + broker_mail.

    ★ 키 규약은 **추출기와 동일해야 한다** (2026-08-06 fix).
      `research_claim_extractor._load_lane_evidence` 는 `_article_id` 가 없으면
      `_raw_dedupe_key` → `_raw_nid` 순으로 폴백해 evidence id 를 만든다(메모리
      한정 — adapted 파일에는 저장하지 않는다). 여기서 `_article_id` 만 인덱싱하면
      **그 폴백으로 만들어진 claim 의 원본이 통째로 안 붙는다**.

      실측(2026-07): adapted 1,412건 중 311건이 refine(Step 2.5)을 안 거쳐
      `_article_id` 가 없고, 그 기사에서 나온 claim 222건이 "원본 연결 없음"
      이었다. 폴백을 맞추니 evidence join 83.8% → 94.0%,
      연결 없는 claim 242건 → 87건.

    ★ monygeek 은 정적 파일이 아니라 `build_monygeek_articles()` 로 파생되는
      레인이다 (posts.json 자체엔 `_article_id` 가 없다). 어댑터를 거치면
      `_article_id`·`url` 이 100% 붙으므로 여기서도 같은 어댑터를 쓴다 —
      종전에 이 레인을 통째로 빠뜨려 monygeek claim 의 원본이 안 붙었다.
    """
    import json as _json
    from pathlib import Path as _P
    base = _P(__file__).resolve().parent.parent.parent / 'market_research' / 'data'
    out: dict = {}

    def _add(lane: str, arts) -> None:
        for a in arts or []:
            aid = (a.get('_article_id') or a.get('_raw_dedupe_key')
                   or a.get('_raw_nid') or '')
            if aid:
                out.setdefault(str(aid), (lane, a))

    for lane, path in (
        ('naver_research', base / 'naver_research' / 'adapted' / f'{period}.json'),
        ('broker_mail', base / 'broker_mail' / f'{period}.json'),
    ):
        if not path.exists():
            continue
        try:
            d = _json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        _add(lane, (d.get('articles') if isinstance(d, dict) else d))

    try:
        from market_research.collect.monygeek_research_adapter import (
            build_monygeek_articles,
        )
        _add('monygeek', build_monygeek_articles(period))
    except Exception:
        pass      # 어댑터 실패는 조회를 막지 않는다 (monygeek 만 링크 누락)
    return out


@router.get('/admin/research-wiki', response_model=ResearchWikiDTO)
def get_research_wiki(period: str = Query(..., min_length=7, max_length=7),
                      asset: str = Query('', max_length=32)) -> ResearchWikiDTO:
    import json as _json
    from pathlib import Path as _P

    if not _research_period_re(period):
        raise HTTPException(status_code=422, detail='period 는 YYYY-MM 형식')

    base = _P(__file__).resolve().parent.parent.parent / 'market_research' / 'data'
    cp = base / 'claims' / f'{period}.research.json'
    if not cp.exists():
        return ResearchWikiDTO(period=period)
    claims = (_json.loads(cp.read_text(encoding='utf-8')) or {}).get('claims') or []

    from market_research.analyze.research_aggregator import aggregate_by_asset
    agg = aggregate_by_asset(claims)
    assets = sorted(agg, key=lambda a: -agg[a]['n_claims'])
    if not assets:
        return ResearchWikiDTO(period=period)
    if asset not in agg:
        asset = assets[0]

    # 09 페이지 — stem 은 파일명 규칙상 특수문자 제거 (환율(FX) → 환율FX)
    stem = re.sub(r'[^0-9A-Za-z가-힣]', '', asset)
    pdir = base / 'wiki' / '09_Research_Synthesis'
    page = pdir / f'{period}_{stem}.md'
    page_md = page.read_text(encoding='utf-8') if page.exists() else ''
    page_mtime = page.stat().st_mtime if page.exists() else 0.0
    adopted_ids = set(re.findall(r'claim:([0-9a-f]{10})', page_md))

    a = agg[asset]
    ordered = list(a['broker_claims']) + list(a['monygeek_claims'])
    lane_idx = _load_lane_index(period)

    rows: list[ClaimRowDTO] = []
    for i, c in enumerate(ordered, 1):
        cid = str(c.get('claim_id') or '')
        short = cid.split(':')[-1]
        srcs = []
        for eid in (c.get('source_evidence_ids') or [])[:6]:
            # `_raw_nid` 폴백은 정수로 저장돼 있어 str 정규화가 필요하다.
            hit = lane_idx.get(str(eid))
            if not hit:
                continue
            lane, art = hit
            srcs.append(ClaimSourceDTO(
                title=str(art.get('title') or '')[:200],
                date=str(art.get('date') or '')[:10],
                broker=str(art.get('_raw_broker') or art.get('source') or ''),
                lane=lane,
                url=str(art.get('url') or ''),
                attachments=', '.join(art.get('_raw_attach_names') or [])[:200],
            ))
        rows.append(ClaimRowDTO(
            claim_id=cid, text=str(c.get('claim_text') or ''),
            stance=str(c.get('stance') or ''), direction=str(c.get('direction') or ''),
            horizon=str(c.get('horizon') or ''),
            confidence=float(c.get('confidence') or 0),
            salience=float(c.get('salience') or 0),
            source_type=str(c.get('source_type') or ''),
            broker=str(c.get('broker_author') or ''),
            adopted=short in adopted_ids, rank=i, sources=srcs,
            rationale=str(c.get('rationale_text') or ''),
            risk_factor=str(c.get('risk_factor') or ''),
            causal_chain=[
                f"{x.get('source', '')} →{x.get('relation', '')}→ {x.get('target', '')}"
                for x in (c.get('causal_chain') or [])
                if isinstance(x, dict) and (x.get('source') or x.get('target'))
            ],
        ))

    return ResearchWikiDTO(
        period=period, asset=asset, assets=assets,
        page_md=page_md,
        page_generated_at=(time.strftime('%Y-%m-%d %H:%M',
                                         time.localtime(page_mtime))
                           if page_mtime else ''),
        page_stale=bool(page_mtime and cp.stat().st_mtime > page_mtime),
        claims_total=len(rows),
        adopted_total=sum(1 for r in rows if r.adopted),
        claims=rows,
    )


# ── 자산군 시드 (공통 문단 단일 소스) ──

def _seed_dto(period: str) -> SeedDTO:
    from market_research.core.asset_class import (
        CANONICAL_CLASSES, MARKET_ORDER, OUTLOOK_ORDER,
    )
    from market_research.report.market_seed import load_seed, over_budget
    orders = {'classes': list(CANONICAL_CLASSES),
              'market_order': list(MARKET_ORDER),
              'outlook_order': list(OUTLOOK_ORDER)}
    seed = load_seed(period)
    if not seed:
        return SeedDTO(period=period, **orders)
    sections = seed.get('sections') or {}
    return SeedDTO(
        period=period,
        status=seed.get('status', 'draft'),
        sections=SeedSectionDTO(market=sections.get('market') or {},
                                outlook=sections.get('outlook') or {}),
        outlook_period=(seed.get('source') or {}).get('outlook_period', ''),
        generated_at=seed.get('generated_at', ''),
        approved_at=seed.get('approved_at', ''),
        model=seed.get('model', ''),
        cost_usd=seed.get('cost_usd', 0) or 0,
        over_budget=[{'section': s, 'key': k, 'chars': n, 'limit': hi}
                     for s, k, n, hi in over_budget(sections)],
        **orders,
    )


@router.get('/admin/market-seed', response_model=SeedDTO)
def get_market_seed(period: str = Query(..., pattern=PERIOD_RE)) -> SeedDTO:
    return _seed_dto(period)


@router.post('/admin/market-seed/generate', response_model=SeedDTO)
def generate_market_seed(body: GenBodyDTO) -> SeedDTO:
    """승인된 _market 코멘트 → 자산군별 시드. LLM 1회 (펀드 수 무관)."""
    mode, year, num = _parse_period(body.kind, body.period)
    market = _resolve_market_payload(body.period, mode, year, num)
    if not market:
        raise HTTPException(
            status_code=409,
            detail=f'{body.period} 시장 코멘트 승인본 없음 — 시장 debate 승인 먼저')
    from market_research.report.market_seed import build_seed, save_seed
    try:
        seed = build_seed(body.period, market, period_label=body.period)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'시드 생성 실패: {exc}')
    save_seed(body.period, seed)
    return _seed_dto(body.period)


@router.put('/admin/market-seed/draft', response_model=SeedDTO)
def edit_market_seed(body: SeedEditBodyDTO) -> SeedDTO:
    """Admin 수정 저장. 수정하면 승인 상태를 draft 로 되돌린다."""
    from market_research.report.market_seed import (
        STATUS_DRAFT, load_seed, save_seed,
    )
    seed = load_seed(body.period)
    if not seed:
        raise HTTPException(status_code=404, detail='시드 없음 — 먼저 생성')
    seed['sections'] = {'market': dict(body.sections.market),
                        'outlook': dict(body.sections.outlook)}
    if seed.get('status') != STATUS_DRAFT:
        seed['status'] = STATUS_DRAFT
        seed.pop('approved_at', None)
        seed.pop('approved_by', None)
    seed.setdefault('edit_history', []).append(
        {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'by': 'admin'})
    save_seed(body.period, seed)
    return _seed_dto(body.period)


@router.post('/admin/market-seed/approve', response_model=SeedDTO)
def approve_market_seed(body: PeriodBodyDTO) -> SeedDTO:
    from market_research.report.market_seed import approve_seed
    if approve_seed(body.period) is None:
        raise HTTPException(status_code=404, detail='시드 없음 — 먼저 생성')
    return _seed_dto(body.period)


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
    """보고서 단계 산출물 다운로드 — `_EXCEL_SPECS` 등록 펀드(엑셀/PPT)."""
    from fastapi.responses import FileResponse
    xp = _excel_path(fund, period)
    if xp is None or not xp.exists():
        raise HTTPException(status_code=404, detail='산출물 없음 — 보고서 생성/승인 먼저')
    # .pptx 는 mimetypes 가 못 알아보는 환경이 있어(그러면 text/plain) 명시한다
    mt = ('application/vnd.openxmlformats-officedocument.presentationml.presentation'
          if xp.suffix == '.pptx' else None)
    return FileResponse(str(xp), filename=xp.name, media_type=mt)


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
