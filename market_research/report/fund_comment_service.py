# -*- coding: utf-8 -*-
"""Fund Comment Service — 펀드별 코멘트 생성 서비스.

시장 debate 산출물(final/edited draft)을 입력으로 받아,
펀드별 PA/보유비중/거래내역 데이터와 결합해 Opus로 코멘트를 생성한다.

이 모듈이 담당하는 것:
  - 시장 comment payload → 펀드 코멘트용 inputs 변환
  - 펀드 데이터 로딩 + 요약
  - comment_engine.build_report_prompt() / generate_report_from_inputs() 호출
  - fund draft 저장

이 모듈이 담당하지 않는 것:
  - Streamlit UI (st.* 호출 없음)
  - 시장 debate 실행 (debate_service.py 담당)
  - 뉴스 수집/분류/정제/GraphRAG (외부 배치 담당)
"""
from __future__ import annotations

import re as _re
import time
import uuid
from datetime import date, timedelta

from market_research.report.report_store import (
    save_draft, load_draft, load_final,
    sanitize_target_suffix,
    STATUS_DRAFT,
)

# fund draft는 별도 경로에 저장 (시장 debate와 분리)
FUND_REPORT_TYPE = 'fund'


# ══════════════════════════════════════════
# 시장 comment → inputs 변환
# ══════════════════════════════════════════

def _market_comment_to_inputs(market_payload: dict) -> dict:
    """시장 final/edited draft → 펀드 코멘트용 inputs dict.

    approved final 우선, 없으면 edited draft fallback.
    raw dict/list를 그대로 넣지 않고 LLM 친화적 텍스트로 정규화한다.
    """
    if not market_payload:
        return {}

    inputs = {'source': 'market_debate'}

    # market_view: 코멘트 본문 (final > draft)
    comment = (market_payload.get('final_comment', '')
               or market_payload.get('draft_comment', '')
               or market_payload.get('customer_comment', ''))
    if comment:
        inputs['market_view'] = comment

    # outlook: 합의 포인트 (자연어 bullet)
    consensus = market_payload.get('consensus_points', [])
    if consensus:
        bullets = [f'- {p}' for p in consensus[:3]]
        inputs['outlook'] = '\n'.join(bullets)

    # risk: 쟁점 + 테일리스크 (중복 제거, 텍스트 정리)
    risk_parts = []
    for d in market_payload.get('disagreements', [])[:3]:
        if isinstance(d, dict):
            topic = d.get('topic', '')
            bear = d.get('bear', '')
            if bear:
                risk_parts.append(f'- [{topic}] {bear}')
        elif isinstance(d, str):
            risk_parts.append(f'- {d}')
    for t in market_payload.get('tail_risks', [])[:2]:
        risk_parts.append(f'- [테일리스크] {t}')
    if risk_parts:
        inputs['risk'] = '\n'.join(risk_parts)

    # evidence_annotations 전달 (R6-A) — build_report_prompt 가 [ref:N] 인용 가능한
    # evidence 목록으로 변환. ref 번호는 시장 debate 가 부여한 값 그대로 사용.
    ann = market_payload.get('evidence_annotations') or []
    if ann:
        inputs['evidence_annotations'] = ann

    # R8-B-impl: asset_movement_commentary / asset_movement_anchors pass-through.
    # debate 가 자산군별 과거 등락 / drivers / outlook / portfolio_implication 을
    # 구조화해 보내준 결과를 fund_comment prompt 가 우선적으로 사용.
    amc = market_payload.get('asset_movement_commentary') or []
    if amc:
        inputs['asset_movement_commentary'] = amc
    anchors = market_payload.get('asset_movement_anchors') or None
    if anchors:
        inputs['asset_movement_anchors'] = anchors

    # R9-A.3: canonical claims pass-through (read-only). market_payload 에
    # claims 가 있으면 그대로 전달, 없으면 [] 유지. 기존 키는 절대 drop 안 함.
    claims_passthrough = market_payload.get('claims') or []
    if claims_passthrough:
        inputs['claims'] = claims_passthrough

    return inputs


# ══════════════════════════════════════════
# 펀드 데이터 요약 (프롬프트용)
# ══════════════════════════════════════════

def _adapt_compute_single_port_pa(pa_result: dict) -> dict:
    """compute_single_port_pa 의 새 schema (asset_summary DataFrame) 를
    fund_comment_service 가 사용하는 구버전 형태로 변환 (Q-FIX-2, 2026-05-06).

    배경:
      compute_single_port_pa 는 asset_summary / port_daily_returns / sec_summary
      등 DataFrame 중심 schema 로 진화했으나, generate_fund_comment_and_save 는
      구버전 키 (pa_by_class / fund_return / holdings_end / holdings_diff) 를
      dict.get() 함 → 모두 빈 dict / None 반환. 08K88 / 4JM12 / 08N81 등
      production 의 data_snapshot.fund_return=None 의 근본 원인.

    단위 변환:
      compute_single_port_pa : decimal (-0.0271 = -2.71%, 0.1199 = 11.99%)
      _summarize_fund_data_for_prompt : % 단위 (':+.2f%' 포매팅)
      → adapter 가 × 100 으로 % 단위 통일. round 4 자릿수.

    Returns:
        {
          'fund_return'  : float | None     # 포트폴리오 row 의 개별수익률 (%)
          'pa_by_class'  : dict[str, float] # 자산군 → 기여수익률 (%)
          'holdings_end' : dict[str, float] # 자산군 → 순자산비중 (%)
          'holdings_diff': list             # 미산출 (별도 task — sec 변동 비교 필요)
          'warnings'     : list[str]
        }

    asset_summary 가 None / DataFrame 아님 / 빈 결과 시 warning 기록 후 빈 dict 반환.
    """
    out = {
        'fund_return': None,
        'pa_by_class': {},
        'holdings_end': {},
        'holdings_diff': [],
        'warnings': [],
    }
    if not isinstance(pa_result, dict):
        out['warnings'].append('pa_result not a dict')
        return out
    asset_summary = pa_result.get('asset_summary')
    if asset_summary is None:
        out['warnings'].append('asset_summary missing in pa_result')
        return out
    if not hasattr(asset_summary, 'iterrows'):
        out['warnings'].append(
            f'asset_summary not DataFrame: type={type(asset_summary).__name__}'
        )
        return out
    if len(asset_summary) == 0:
        out['warnings'].append('asset_summary empty')
        return out

    PORT_LABEL = '포트폴리오'
    for _, row in asset_summary.iterrows():
        try:
            ac = row.get('자산군') if hasattr(row, 'get') else row['자산군']
        except Exception:
            continue
        if not ac:
            continue
        if ac == PORT_LABEL:
            try:
                ret = row.get('개별수익률') if hasattr(row, 'get') else row['개별수익률']
                if ret is not None:
                    out['fund_return'] = round(float(ret) * 100, 4)
            except (TypeError, ValueError, KeyError):
                pass
            continue
        # 자산군 row
        try:
            contrib = row.get('기여수익률') if hasattr(row, 'get') else row['기여수익률']
            if contrib is not None:
                out['pa_by_class'][ac] = round(float(contrib) * 100, 4)
        except (TypeError, ValueError, KeyError):
            pass
        try:
            wgh = row.get('순자산비중') if hasattr(row, 'get') else row['순자산비중']
            if wgh is not None:
                wgh_pct = round(float(wgh) * 100, 4)
                if wgh_pct > 0:  # 0 이상만 — 빈 자산군 제거
                    out['holdings_end'][ac] = wgh_pct
        except (TypeError, ValueError, KeyError):
            pass

    # holdings_diff 는 별도 task — sec_summary 또는 holdings_start vs end 비교 필요
    out['warnings'].append('holdings_diff not yet computed (Q-FIX-2 후속 task)')
    return out


def _summarize_fund_data_for_prompt(pa: dict, holdings: dict,
                                     trades: dict, bm: dict) -> dict:
    """원자료를 프롬프트에 넣기 좋은 요약본으로 축약.

    full raw table이 아닌 핵심만 추출.
    """
    summary = {}

    # PA: 상위 기여 3개 + 하위 기여 3개
    if pa:
        sorted_pa = sorted(pa.items(), key=lambda x: x[1], reverse=True)
        top3 = sorted_pa[:3]
        bottom3 = sorted_pa[-3:]
        pa_lines = []
        pa_lines.append('상위 기여:')
        for cls, v in top3:
            if abs(v) >= 0.01:
                pa_lines.append(f'  {cls}: {v:+.2f}%')
        pa_lines.append('하위 기여:')
        for cls, v in bottom3:
            if abs(v) >= 0.01:
                pa_lines.append(f'  {cls}: {v:+.2f}%')
        summary['pa_summary'] = '\n'.join(pa_lines)

    # 보유비중: 자산군별 비중
    if holdings:
        hold_lines = [f'  {cls}: {wt:.1f}%' for cls, wt in
                      sorted(holdings.items(), key=lambda x: -x[1]) if wt > 0.5]
        summary['holdings_summary'] = '\n'.join(hold_lines)

    # 거래내역: 순매수 상위 3개 + 순매도 상위 3개 (유동성 제외)
    if trades:
        non_cash = {k: v for k, v in trades.items() if k not in ('유동성', '모펀드')}
        sorted_trades = sorted(non_cash.items(), key=lambda x: x[1]['net'], reverse=True)
        trade_lines = []
        # 순매수 상위
        for cls, v in sorted_trades[:3]:
            if v['net'] > 0:
                trade_lines.append(f'- {cls} 순매수 {v["net"]:+.1f}억')
        # 순매도 상위
        for cls, v in sorted_trades[-3:]:
            if v['net'] < 0:
                trade_lines.append(f'- {cls} 순매도 {v["net"]:+.1f}억')
        if trade_lines:
            summary['trades_summary'] = '\n'.join(trade_lines)

    return summary


def _load_position_events(fund_code: str, prev_last: int, cur_last: int) -> list[str]:
    """기간초 vs 기간말 보유 스냅샷 diff — 전량 편출 / 신규 편입 / 비중 급변.

    자산군 순매수 합계만으로는 '전량 편출' 이벤트가 드러나지 않아 코멘트가
    "비중 축소"로 잘못 서술하는 문제 방지 (2026-07-08 사용자 피드백, DB생명 2Q).
    선물(롤오버 노이즈)·예금·증거금 등 비증권 계정은 제외.
    """
    from modules.data_loader import get_connection

    import re

    EXCLUDE_KW = ('예금', '증거금', '미지급', '미수', '원천세', '선물')
    _FUT_PAT = re.compile(r' F \d{6}$')  # 선물 월물 (예: '미국달러 F 202607') — 롤오버 노이즈 제외

    def _skip(cd: str, nm: str) -> bool:
        return cd.isdigit() or any(k in nm for k in EXCLUDE_KW) or bool(_FUT_PAT.search(nm))

    def _one(row, key):
        # get_connection 은 DictCursor — dict/tuple 모두 대응
        if row is None:
            return None
        return row[key] if isinstance(row, dict) else row[0]

    def _snapshot(cur, dt_str: str) -> dict:
        cur.execute(
            "SELECT ITEM_CD, ITEM_NM, SUM(EVL_AMT) AS EVL FROM DWPM10530 "
            "WHERE FUND_CD=%s AND STD_DT=%s GROUP BY ITEM_CD, ITEM_NM "
            "HAVING SUM(EVL_AMT) != 0", (fund_code, dt_str))
        rows = cur.fetchall()
        cur.execute("SELECT NAST_AMT FROM DWPM10510 WHERE FUND_CD=%s AND STD_DT=%s",
                    (fund_code, dt_str))
        nast_v = _one(cur.fetchone(), 'NAST_AMT')
        nast = float(nast_v) if nast_v else None
        snap = {}
        if not nast:
            return snap
        for row in rows:
            if isinstance(row, dict):
                cd, nm, evl = row['ITEM_CD'], row['ITEM_NM'], row['EVL']
            else:
                cd, nm, evl = row
            cd_s, nm_s = str(cd), str(nm or '')
            if _skip(cd_s, nm_s):
                continue
            snap[cd_s] = (nm_s, float(evl) / nast * 100)
        return snap

    conn = get_connection('dt')
    try:
        cur = conn.cursor()
        s0 = _snapshot(cur, str(int(prev_last)))
        s1 = _snapshot(cur, str(int(cur_last)))
        events = []
        # 전량 편출 (기초 0.5% 이상 → 기말 0). 마지막 보유일 명시.
        for cd, (nm, w0) in sorted(s0.items(), key=lambda x: -x[1][1]):
            if cd not in s1 and w0 >= 0.5:
                cur.execute(
                    "SELECT MAX(STD_DT) AS MX FROM DWPM10530 WHERE FUND_CD=%s AND ITEM_CD=%s "
                    "AND STD_DT BETWEEN %s AND %s AND EVL_AMT > 0",
                    (fund_code, cd, str(int(prev_last)), str(int(cur_last))))
                mx = _one(cur.fetchone(), 'MX')
                last_dt = str(mx) if mx else ''
                tail = f' ({last_dt[4:6]}/{last_dt[6:8]}까지 보유 후 편출)' if len(last_dt) == 8 else ''
                events.append(f'- 전량 편출: {nm} — 기초 {w0:.1f}% → 기말 0%{tail}')
        # 신규 편입 (기초 0 → 기말 0.5% 이상)
        for cd, (nm, w1) in sorted(s1.items(), key=lambda x: -x[1][1]):
            if cd not in s0 and w1 >= 0.5:
                events.append(f'- 신규 편입: {nm} — 기초 0% → 기말 {w1:.1f}%')
        # 비중 급변 (양쪽 보유): ±3%p 이상 또는 포지션의 25% 이상 증감(기초 1% 이상)
        for cd, (nm, w0) in sorted(s0.items(), key=lambda x: -x[1][1]):
            if cd in s1:
                w1 = s1[cd][1]
                big_abs = abs(w1 - w0) >= 3.0
                big_rel = w0 >= 1.0 and abs(w1 - w0) / w0 >= 0.25
                if big_abs or big_rel:
                    d = '축소' if w1 < w0 else '확대'
                    events.append(f'- 비중 {d}: {nm} — {w0:.1f}% → {w1:.1f}%')
        return events
    finally:
        conn.close()


_SENT_REF_CLIP = 3000  # 발송본 참조 텍스트 프롬프트 상한


def _load_sent_report_reference(fund_code: str, period_key: str) -> dict | None:
    """직전 발송 운용보고 텍스트 로드 — 양식·톤·분량 참조용 (2026-07-09).

    data/sent_reports index 에서 해당 펀드의, 생성 기간(period_key) 이전 최신 발송본을
    고른다. 월 생성(YYYY-MM)은 월간 발송본, 분기 생성(YYYY-QN)은 분기 발송본 우선 —
    없으면 종류 무관 최신. 텍스트 사이드카 없는 항목(PDF 등)은 제외.
    """
    from market_research.collect.sent_report_collector import SENT_DIR, load_index

    entries = [e for e in load_index() if e.get('fund') == fund_code]
    if not entries:
        return None
    is_q = 'Q' in period_key or 'H' in period_key
    want_kind = '분기' if is_q else '월간'

    def _candidates(kind_filter: bool):
        out = []
        for e in entries:
            if kind_filter and e.get('kind') != want_kind:
                continue
            # 같은 형식(월간↔YYYY-MM / 분기↔YYYY-QN)끼리는 문자열 비교로 이전 기간 판별
            if e.get('kind') == want_kind and e.get('period', '') >= period_key:
                continue
            txt = SENT_DIR / (e['rel_path'] + '.txt')
            if txt.exists():
                out.append((e, txt))
        return out

    cands = _candidates(True) or _candidates(False)
    if not cands:
        return None
    e, txt = max(cands, key=lambda x: (x[0].get('period', ''), x[0].get('mail_date', '')))
    body = txt.read_text(encoding='utf-8')
    return {'period': e['period'], 'filename': e['filename'],
            'text': body[:_SENT_REF_CLIP],
            # 전문 — 프롬프트에는 클립본을 쓰지만, 특정 문단을 뽑아 쓸 때는 전문이 필요하다
            # (4JM12 환헤지 문장은 s6 라 3,000자 클립 뒤에 있다).
            'full_text': body}


# ══════════════════════════════════════════
# 펀드 코멘트 생성 + 저장
# ══════════════════════════════════════════

def _month_last_bday(year: int, month: int):
    """해당 월 마지막 영업일 (캘린더 미등록이면 None)."""
    from market_research.report.comment_engine import load_business_days
    try:
        return (load_business_days(year, month) or {}).get('cur_month_last')
    except Exception:
        return None


# 환헤지 레인지 — **DXY 대비 원화 상대가치(RV)** 기준 (2026-08-06 사용자 확정).
#   DXY 현행 유지 가정 하에 스프레드가 롤링1Y 분포의 μ ~ +2σ 사이를 움직인다고 본다.
#   정의·검증은 `report/fx_rv_range.py` 참조 (사내 알파페어 화면과 수치 동일).
#   레인지는 최종적으로 운용역 판단이라 **제안값**이며 Admin 에서 고친다.
_HEDGE_RANGE_RE = _re.compile(
    r'(\d{1,2},?\d{3})\s*원?\s*~\s*(\d{1,2},?\d{3})\s*원')


def _hedge_line(fund_code: str, period_key: str, end_dt, warnings: list) -> str:
    """환헤지 비율 문장 — **전월 문장을 그대로 잇고 레인지 숫자만 교체**한다
    (2026-08-06 사용자 지시: "레인지만 업데이트하고 나머진 전월과 동일").

    원본 우선순위:
      1) **직전 발송본 아카이브** — 실제로 고객에게 나간 문장이라 이게 정본이다.
         (⚠ s6 는 3,000자 클립 뒤에 있어 `full_text` 를 써야 한다.)
      2) 전월 report_output 승인본 — 아카이브가 없을 때.
    둘 다 없으면 빈 문자열 + 경고. **지어내지 않는다.**
    """
    from market_research.report.report_store import load_final

    _pat = r'환헤지\s*비율\s*:\s*(.+?)(?:\n\s*\n|\n\S+\s*:|\Z)'
    line, src = '', ''
    ref = _load_sent_report_reference(fund_code, period_key)
    if ref:
        mt = _re.search(_pat, ref.get('full_text') or '', _re.S)
        if mt:
            line, src = ' '.join(mt.group(1).split()), f"발송본 {ref['period']}"
    if not line:
        y, m = int(period_key[:4]), int(period_key[5:7])
        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        prev = load_final(f'{py}-{pm:02d}', fund_code)
        mt = _re.search(_pat, str((prev or {}).get('final_comment') or ''), _re.S)
        if mt:
            line, src = ' '.join(mt.group(1).split()), f'승인본 {py}-{pm:02d}'
    if not line:
        warnings.append('직전 발송본·전월 승인본 어디에서도 환헤지 비율 문단을 찾지 '
                        '못했습니다 — 환헤지 문장을 직접 작성하세요')
        return ''
    warnings.append(f'환헤지 문장 승계 원본 = {src}')

    from market_research.report.fx_rv_range import compute as _rv
    rv = _rv(str(end_dt)) if end_dt is not None else None
    if not rv:
        warnings.append('원화 RV 분포를 계산하지 못해 환헤지 레인지를 전월 값 그대로 '
                        '두었습니다 — 직접 확인하세요')
        return line
    lo, hi = rv['range_pm_2s']
    new, n = _HEDGE_RANGE_RE.subn(f'{lo:,}원 ~ {hi:,}원', line, count=1)
    if not n:
        warnings.append('전월 환헤지 문장에서 레인지(0,000원 ~ 0,000원) 패턴을 찾지 '
                        '못했습니다 — 레인지를 직접 수정하세요')
        return line
    n_lo, n_hi = rv['range_mu_2s']
    warnings.append(
        f"환헤지 레인지 제안 {lo:,}~{hi:,}원 — DXY 현행 유지 · 원화 RV 스프레드 "
        f"±2σ 구간(롤링1Y μ={rv['mu']}% σ={rv['sd']}%p, 현재 z={rv['z']:+}σ, "
        f"기준일 {rv['asof']} {rv['spot']:,}원). 좁은 판본 μ~+2σ={n_lo:,}~{n_hi:,}원. "
        f"운용역 판단으로 조정하세요")
    return new


def _hedge_ratio_block(prev_eom: str, cur_eom: str) -> str | None:
    """환헤지 비율 전월→당월 + BM 기준 — 프롬프트 주입용 (4JM12, 2026-08-06).

    운용경과에 "환 익스포저를 BM 에 맞춰 조정" 을 쓰려면 이 수치가 있어야 한다.
    없으면 LLM 이 방향만 보고 "확대/축소" 만 나열한다(실측).
    정의·산식은 `tools/dblife_monthly_excel.py` 와 동일한 것을 재사용한다.
    """
    from tools.dblife_monthly_excel import (
        BM_HEDGE_RATIO, _overseas_equity_isins, bucket_of, load_holdings_eom,
    )
    ovs_isins = _overseas_equity_isins()

    def _one(eom: str):
        h = load_holdings_eom(str(eom))
        if h is None or not len(h):
            return None
        h = h.copy()
        h['bucket'] = h.apply(bucket_of, axis=1)
        h['w'] = h['NAST_TAMT_AGNST_WGH'].astype(float)
        hedge = float(h.loc[h['bucket'] == '달러선물', 'w'].abs().sum())
        eq = h[h['bucket'] == '주식형']
        is_o = (eq['ITEM_CD'].astype(str).str.strip().isin(ovs_isins)
                if ovs_isins else eq['ITEM_CD'].astype(bool))
        ovs = float(eq.loc[is_o, 'w'].sum()
                    + h.loc[h['bucket'] == '외화현금', 'w'].sum())
        return hedge, ovs, (hedge / ovs * 100 if ovs else None)

    try:
        a, b = _one(prev_eom), _one(cur_eom)
    except Exception:
        return None
    if not a or not b or a[2] is None or b[2] is None:
        return None
    return (
        '[환헤지 비율 (사실 — 이 값만 인용)]\n'
        f'- 전월말: 헤지 {a[0]:.1f}% / 해외자산 {a[1]:.1f}% → 헤지비율 {a[2]:.1f}%\n'
        f'- 당월말: 헤지 {b[0]:.1f}% / 해외자산 {b[1]:.1f}% → 헤지비율 {b[2]:.1f}%\n'
        f'- BM 헤지비율: {BM_HEDGE_RATIO:.1f}% (BM 해외 45% 중 절반만 환헤지)\n'
        '  ※ 헤지비율이 BM 보다 높으면 오버헤지(환노출 축소), 낮으면 언더헤지다.'
    )


# Brinson 블록 꼬리의 헤드라인 — 형식은 `_brinson_factor_block` 이 만든다.
_BRINSON_HEADLINE_RE = _re.compile(
    r'\(펀드\s*(-?\d+\.\d+)%\s*/\s*BM\s*(-?\d+\.\d+)%\)')


def _check_perf_numbers(text: str, brinson_block: str, warnings: list) -> None:
    """펀드성과 본문의 수익률이 **Brinson 표 값과 같은지** 확인 (2026-08-07).

    ⚠ 프롬프트에 사실을 넣어도 LLM 이 지어낸다. 2026-07 4JM12 실측: 표는
      `(펀드 -2.90% / BM -2.20%)` 인데 본문은 "BM은 -1.65%" 로 썼고, 자기 문장 안의
      초과폭(66bp)과도 안 맞았다. 고객에게 나가는 숫자라 경고로 잡는다.
    """
    if not text or not brinson_block:
        return
    m = _BRINSON_HEADLINE_RE.search(brinson_block)
    if not m:
        return
    ap, bm = m.group(1), m.group(2)
    try:
        excess = float(ap) - float(bm)
    except ValueError:
        return
    for label, val in (('펀드', ap), ('BM', bm)):
        # 부호 표기가 갈릴 수 있어 절대값 문자열로 본다 ("-2.20%" / "2.20%" 모두 허용)
        if val.lstrip('-') not in text:
            warnings.append(
                f'펀드성과에 {label} 수익률 {val}% 가 보이지 않습니다 — '
                f'Brinson 표 값(펀드 {ap}% / BM {bm}% · 초과 {excess:+.2f}%p)과 다른 '
                f'수치를 쓴 것 같습니다. 반드시 대조하세요')


def _perf_period_label(mode: str, end_dt, quarter: int) -> str:
    """성과 문장 첫머리 — 발송본은 "6월 중 펀드는 …" 처럼 **기간을 명시**한다.

    월간은 종료일의 월을 쓴다(08K88 처럼 기간 창이 달력월과 어긋나도 보고 대상 월과
    같다). 그 외 유형은 해당 기간 명칭으로, 종료일을 모르면 '당 기간'.

    ⚠ 월간의 `mode` 값은 **'월별'** 이다 ('월간'은 API 가 받는 kind 이고,
      `_PERIOD_PATTERNS` 가 '월별'로 바꿔 넘긴다). 그래서 `_resolve_dates` 와 똑같이
      **비월간을 먼저 걸러내고 나머지를 월간으로** 처리한다 — '월별'을 직접 비교하면
      값이 또 바뀔 때 조용히 '당 기간'으로 새어나간다(실측: 7월 코멘트가 그렇게 나왔다).
    """
    if mode == '분기':
        return f'{quarter}분기 중'
    if mode in ('QTD', 'HTD', 'YTD'):
        return {'QTD': '분기 중', 'HTD': '반기 중', 'YTD': '연초 이후'}[mode]
    return f'{end_dt.month}월 중' if end_dt is not None else '당 기간'


def _resolve_dates(mode: str, year: int, period_num: int):
    """기간 유형에 따른 영업일 범위 계산.

    mode : '월별' | '분기' | 'QTD' | 'HTD' | 'YTD'
      - QTD/HTD/YTD : 직전 분기말/반기말/연말부터 **현재까지**(to-date)
      - period_num  : 월(1~12) / 분기(1~4) / 반기(1~2) / YTD 는 미사용(0)

    진행 중인 기간(당월 MTD 포함)은 종료일을 최신 적재일로 clamp 한다 —
    영업일 캘린더(DWCI10220)에는 미래 영업일도 있어서 clamp 없이는 데이터
    없는 날짜를 종료일로 잡는다. 이미 마감된 과거 기간은 기간말 < 최신적재일
    이라 clamp 가 무영향(기존 산출물 불변).
    """
    from market_research.report.comment_engine import (
        load_business_days, load_business_days_quarter, load_latest_data_date,
    )
    if mode in ('분기', 'QTD'):
        bdays = load_business_days_quarter(year, period_num)
        quarter = period_num
    elif mode == 'HTD':
        # H1 = 전년말~6월말 / H2 = 6월말~12월말
        prev_last_ = (_month_last_bday(year - 1, 12) if period_num == 1
                      else _month_last_bday(year, 6))
        bdays = {'prev_month_last': prev_last_,
                 'cur_month_last': _month_last_bday(year, 6 if period_num == 1 else 12)}
        quarter = 2 if period_num == 1 else 4
    elif mode == 'YTD':
        bdays = {'prev_month_last': _month_last_bday(year - 1, 12),
                 'cur_month_last': _month_last_bday(year, 12)}
        quarter = 4
    else:
        bdays = load_business_days(year, period_num)
        quarter = (period_num - 1) // 3 + 1

    if not bdays:
        return None, None, None, None, quarter

    # load_business_days returns dict: {prev_month_last, cur_month_last, business_days, ...}
    if isinstance(bdays, dict):
        prev_last = bdays.get('prev_month_last')
        cur_last = bdays.get('cur_month_last')
    else:
        # list fallback
        cur_last = bdays[-1]
        prev_last = bdays[0]

    # 진행 중인 기간 → 종료일을 최신 적재일로 clamp (MTD/QTD/HTD/YTD)
    latest = load_latest_data_date()
    if latest and (not cur_last or latest < cur_last):
        cur_last = latest

    if not prev_last or not cur_last:
        return None, None, None, None, quarter
    if int(cur_last) <= int(prev_last):
        # 아직 시작 안 한 기간 (적재 데이터가 기간 시작 이전)
        return None, None, None, None, quarter

    def _int_to_date(d):
        s = str(int(d))
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))

    start_dt = _int_to_date(prev_last)
    end_dt = _int_to_date(cur_last)
    return int(prev_last), int(cur_last), start_dt, end_dt, quarter


def _brinson_factor_block(fund_code: str, start_dt, end_dt) -> str | None:
    """자산군별 비중(OW/UW)·자산배분효과·종목선택효과 표 — 프롬프트 주입용.

    기준: 방법3 · **FX 포함**(fx_split=False) — 코멘트 자산군 분해와 같은 기준
    (2026-08-04 사용자 확정). BM 없는 펀드는 None.
    """
    from api.services.brinson_service import build_brinson
    b = build_brinson(fund_code, start_date=start_dt, end_date=end_dt,
                      fx_split=False, mapping_method='방법3')
    if not b or getattr(b, 'bm_source', 'none') == 'none' or not b.asset_rows:
        return None
    lines, ta, ts = [], 0.0, 0.0
    for a in b.asset_rows:
        d = a.ap_weight - a.bm_weight
        if abs(a.ap_weight) < 1e-9 and abs(a.bm_weight) < 1e-9:
            continue
        ta += a.alloc_effect
        ts += a.select_effect
        lines.append(
            f'- {a.asset_class}: AP {a.ap_weight:.2f}% vs BM {a.bm_weight:.2f}% '
            f'({"OW" if d >= 0 else "UW"} {d:+.2f}%p) · '
            f'자산배분 {a.alloc_effect:+.2f}%p({"긍정" if a.alloc_effect >= 0 else "부정"}) · '
            f'종목선택 {a.select_effect:+.2f}%p({"긍정" if a.select_effect >= 0 else "부정"})')
    return (
        f'[BM 대비 요인분해 — {start_dt}~{end_dt} · 방법3 · FX 포함 (사실 — 반드시 준수)]\n'
        + '\n'.join(lines)
        + f'\n- 합계: 자산배분 {ta:+.2f}%p · 종목선택 {ts:+.2f}%p · '
          f'초과수익 {b.total_excess:+.2f}%p (펀드 {b.period_ap_return:+.2f}% / '
          f'BM {b.period_bm_return:+.2f}%)\n'
          '(주의: 자산배분·종목선택의 **부호(긍정/부정)와 OW/UW 는 위 표대로만** 서술한다. '
          '다른 기간(연초이후·분기 등)의 값을 이 기간 서술에 쓰지 말 것. '
          'BM 에 없는 자산군(BM비중 0)은 자산배분효과가 0.00 으로 계산되지만 OW 로 묶어 '
          '서술해도 무방하다 — 다만 그 0.00 수치를 인용하지는 말 것.)')


def _sub_portfolio_returns(fund_code: str, start_dt, end_dt) -> dict | None:
    """모펀드의 서브 포트폴리오 기간수익률(%) — 기준가 기준. 없으면 None."""
    from market_research.core.constants import FUND_CONFIGS
    subs = (FUND_CONFIGS.get(fund_code) or {}).get('sub_portfolios') or {}
    if not subs:
        return None
    import pandas as pd
    from modules.data_loader import get_pandas_connection
    codes = list(subs.values())
    ph = ','.join(repr(c) for c in codes)
    conn = get_pandas_connection('dt')
    try:
        df = pd.read_sql(
            f"SELECT FUND_CD, STD_DT, MOD_STPR FROM DWPM10510 WHERE FUND_CD IN ({ph}) "
            "AND STD_DT IN (%s, %s)", conn,
            params=[(start_dt - timedelta(days=1)).strftime('%Y%m%d'),
                    end_dt.strftime('%Y%m%d')])
    finally:
        conn.close()
    if df.empty:
        return None
    df['STD_DT'] = df['STD_DT'].astype(str)
    piv = df.pivot(index='FUND_CD', columns='STD_DT', values='MOD_STPR')
    if piv.shape[1] < 2:
        return None
    c0, c1 = sorted(piv.columns)[0], sorted(piv.columns)[-1]
    out = {}
    for label, code in subs.items():
        if code in piv.index and piv.loc[code, c0]:
            out[label] = float(piv.loc[code, c1] / piv.loc[code, c0] - 1) * 100.0
    return out or None


def generate_fund_comment_and_save(
    mode: str, year: int, period_num: int,
    fund_code: str, period_key: str,
    market_payload: dict,
    *,
    target_suffix: str | None = None,
) -> dict:
    """펀드 코멘트 생성: 데이터 로딩 → 시장 payload 변환 → Opus 호출 → fund draft 저장.

    Streamlit 의존성 없음. tabs/admin_fund.py에서 호출한다.

    Parameters
    ----------
    mode : '월별' | '분기'
    year, period_num : 연도, 월(1~12) 또는 분기(1~4)
    fund_code : 펀드코드 (e.g. '08P22')
    period_key : 기간 키 (e.g. '2026-04', '2026-Q1')
    market_payload : 시장 debate final/edited draft (load_final 또는 load_draft 결과)
    target_suffix : R9-B.3.1 opt-in. None → 운영 draft 경로. suffix 명시 시
        `{period}/{fund}.{suffix}.draft.json` 으로 isolated 저장.
        호출자가 동일 suffix 의 _market.final 을 load 해야 lineage 가 맞다.
    """
    target_suffix = sanitize_target_suffix(target_suffix)
    data_warnings = []

    # 1. 영업일 범위
    prev_last, cur_last, start_dt, end_dt, quarter = _resolve_dates(mode, year, period_num)
    if not cur_last:
        data_warnings.append(f'{period_key} 영업일 데이터 없음')

    # 1.5. 펀드별 월간 창 오버라이드 (2026-08-05 사용자 지시)
    #
    # 08K88 은 보고 기간이 달력월이 아니다 — **전월 마지막 영업일부터(포함)
    # 당월 마지막 영업일 −1영업일까지**. 엑셀(성과분석)이 같은 창을 쓰므로
    # 코멘트도 맞추지 않으면 **한 보고서 안에서 수익률이 갈린다**
    # (2026-07 실측: 엑셀 -16.02% vs 코멘트 -11.17%, 4.85%p 괴리).
    # 정의는 `core.period_window` 단일 소스 — 미등록 펀드·월간 외 기간은 무영향.
    #
    # ★ 반드시 BM 로드(§2)보다 **앞**이어야 한다. prev_last/cur_last 가
    #   `_load_bm_returns_for_range` 의 분모·분자라 뒤에서 바꾸면 BM 만 옛 창에
    #   남아 AP/BM 이 서로 다른 기간이 된다.
    _win_first_incl = None
    if mode == '월별' and cur_last:
        from market_research.core.period_window import month_window
        _win = month_window(fund_code, year, period_num)
        if _win:
            prev_last = int(_win['base'].strftime('%Y%m%d'))
            cur_last = int(_win['last'].strftime('%Y%m%d'))
            start_dt, end_dt = _win['base'], _win['last']
            _win_first_incl = _win['first_incl']
            data_warnings.append(
                f'{fund_code} 월간 창 오버라이드 — '
                f'{_win_first_incl}~{end_dt} (기준 {start_dt} 종가)')

    # 2. BM 수익률
    bm = {}
    if prev_last and cur_last:
        try:
            from market_research.report.comment_engine import _load_bm_returns_for_range
            bm = _load_bm_returns_for_range(prev_last, cur_last)
        except Exception as e:
            data_warnings.append(f'BM 수익률 로드 실패: {e}')

    # 3. PA 기여도 + 보유비중
    #
    # ★ prev_last(전월말)는 두 가지 상반된 규약에 동시에 쓰인다 (2026-08-04 발견):
    #   - BM 지수 비율(_load_bm_returns_for_range) · 보유 스냅샷(_load_position_events)
    #     → 전월말이 '기준점(분모/기초)' 이라 그대로 써야 맞다.
    #   - MA000410 일별손익 PA(compute_single_port_pa) · DWPM10520 거래
    #     → start_date **당일의 손익·거래를 포함**한다. 전월말을 그대로 넣으면
    #       전월 마지막 영업일 하루가 당월에 섞인다.
    # 증상: 2026-07 08N33 이 -4.72%(6/30 +0.57% 포함) 로 나와 기준가 -5.26% 와 불일치.
    #       7개 펀드 전부 +0.39~+1.01%p 손실 축소. 시작일을 하루 뒤로 밀면
    #       7개 모두 기준가 기간수익률과 소수점까지 일치한다.
    # → PA·거래만 (전월말, 기간말] 창으로 맞춘다. BM·스냅샷은 prev_last 유지.
    pa_start_dt = _win_first_incl or (
        start_dt + timedelta(days=1) if start_dt else None)
    pa = {}
    fund_ret = None
    holdings_end = {}
    holdings_diff = []
    if pa_start_dt and end_dt:
        try:
            from modules.data_loader import compute_single_port_pa
            # fx_split=False (FX 포함) — 환효과를 별도 FX 자산군으로 떼지 않고
            # 각 해외 자산군 수익률에 접는다 (2026-08-04 사용자 지시).
            # compute_single_port_pa 기본값은 True(분리)라 명시 전달이 필요하다.
            # ⚠ 달러선물 환헤지를 쓰는 펀드(4JM12)는 헤지손익이 FX 자산군에 있어
            #   이 모드에서 자산군 합계가 포트수익률과 어긋난다 → 코멘트에 '환헤지'
            #   항목을 별도로 적어 합을 맞출 것.
            pa_result = compute_single_port_pa(
                fund_code,
                start_date=pa_start_dt.strftime('%Y%m%d'),
                end_date=end_dt.strftime('%Y%m%d'),
                fx_split=False,
            )
            if pa_result:
                # Q-FIX-2 (2026-05-06): asset_summary DataFrame 새 schema → 구버전 키 변환
                adapted = _adapt_compute_single_port_pa(pa_result)
                pa = adapted['pa_by_class']
                fund_ret = adapted['fund_return']
                holdings_end = adapted['holdings_end']
                holdings_diff = adapted['holdings_diff']
                for w in adapted.get('warnings', []):
                    data_warnings.append(f'PA adapter: {w}')
        except Exception as e:
            data_warnings.append(f'PA 데이터 로드 실패: {e}')

    # 4. 거래내역 — std_dt BETWEEN 이라 prev_last 를 그대로 주면 전월말 거래가 섞인다.
    #    위 §3 과 같은 이유로 (전월말, 기간말] 로 맞춘다.
    trades = {}
    if pa_start_dt and cur_last:
        try:
            from modules.data_loader import load_fund_net_trades
            trades = load_fund_net_trades(
                fund_code, int(pa_start_dt.strftime('%Y%m%d')), cur_last)
        except Exception as e:
            data_warnings.append(f'거래내역 로드 실패: {e}')

    # 4.5. 종목 편출입 이벤트 — 자산군 합계가 못 잡는 전량 편출/신규 편입 (2026-07-08)
    position_events = []
    if prev_last and cur_last:
        try:
            position_events = _load_position_events(fund_code, prev_last, cur_last)
        except Exception as e:
            data_warnings.append(f'편출입 이벤트 로드 실패: {e}')

    # 5. 가격 패턴
    price_patterns = {}
    if prev_last and cur_last:
        try:
            from market_research.report.comment_engine import load_bm_price_patterns
            price_patterns = load_bm_price_patterns(prev_last, cur_last)
        except Exception:
            pass

    # 6. 시장 payload → inputs 변환
    inputs = _market_comment_to_inputs(market_payload)

    # 6.5. 펀드 미편입 자산군 파악 (market_view 필터링 + 시드 조립용)
    #
    # ★ 2026-08-05: 종전엔 상수 집합이 **거래 어휘**('대체투자','유동성')인데
    #   holdings_end 는 **PA 어휘**('대체','유동성및기타')로 와서 두 집합이 서로
    #   맞물리지 않았다. 결과적으로 '대체투자' 는 거래가 있었던 달에만 active 로
    #   잡히고, 금을 보유만 하고 매매하지 않은 달에는 "미편입"으로 판정됐다.
    #   → core.asset_class 로 canonical 정규화. 상세는 해당 모듈 docstring.
    from market_research.core.asset_class import (
        active_classes as _active_classes, excluded_classes as _excluded_classes,
    )
    active_classes = _active_classes(holdings_end, trades)
    excluded_classes = _excluded_classes(holdings_end, trades)

    # market_view 상단에 편입 제한 지시를 강하게 삽입
    if excluded_classes and inputs.get('market_view'):
        excluded_str = ', '.join(sorted(excluded_classes))
        constraint = (
            f'[중요] 이 펀드는 {excluded_str} 자산을 편입하지 않습니다. '
            f'{excluded_str} 관련 시장 동향(금 가격, 달러선물, NDF 등)은 코멘트에서 완전히 제외하세요.\n\n'
        )
        inputs['market_view'] = constraint + inputs['market_view']

    # 7. 펀드 데이터 요약
    fund_summary = _summarize_fund_data_for_prompt(pa, holdings_end, trades, bm)

    # 거래 요약을 inputs에 추가 (프롬프트에 자연스럽게 주입)
    additional_parts = []
    if fund_summary.get('trades_summary'):
        additional_parts.append(f'[기간 중 거래 요약]\n{fund_summary["trades_summary"]}')

    # 종목 편출입 이벤트 — 사실 관계 강제 (전량 편출을 "비중 축소"로 쓰는 오류 방지)
    if position_events:
        additional_parts.append(
            '[기간 중 종목 편출입·비중 변화 (사실 — 반드시 준수)]\n'
            + '\n'.join(position_events)
            + '\n(주의: 위 사실과 어긋나는 서술 금지. 전량 편출된 종목/자산을 "비중 축소" 또는 '
              '"보유 지속·전략 유지"로 쓰지 말고, 편출 사실을 운용 서술에 반영할 것.)')

    # 직전 발송 운용보고 참조 — 실제 고객 발송본의 양식·톤·분량 캘리브레이션 (2026-07-09)
    sent_ref = None
    try:
        sent_ref = _load_sent_report_reference(fund_code, period_key)
    except Exception as e:
        data_warnings.append(f'발송본 참조 로드 실패: {e}')
    if sent_ref:
        additional_parts.append(
            f'[직전 발송 운용보고 — {sent_ref["period"]} {sent_ref["filename"]} (기준 서식 — 반드시 준수)]\n'
            + sent_ref['text']
            + '\n(지시: 위 발송본의 운용경과/코멘트 서술을 **기준 원고**로 삼아, 문단 구조·'
              '표현·어투·분량을 그대로 잇는다. 이번 기간의 수치·이벤트·포지션 변화로 내용만 '
              '교체하고, 새로 필요한 서술은 최소한으로 덧붙인다. 발송본의 과거 수치 재인용 금지. '
              '발송본에 없는 형식(헤더/불릿 스타일 변경 등) 도입 금지.)')

    # Brinson 요인분해 — 자산배분/종목선택 효과의 **부호를 사실로 고정** (2026-08-05).
    #   배경: 2026-07 KB(07G07) 코멘트에 해외주식 자산배분효과가 -1.52% 로 들어갔는데,
    #   이는 R 산출물 중 **YTD(2026-01-01~) 파일** 값이었다. 해당 월(7월) 실제값은 +0.03%
    #   으로 부호가 반대. 기간·방법·FX 옵션 3축으로 파일이 갈려 있어 사람이 헷갈리기 쉽다.
    #   → 기간에 맞는 값을 표로 주입하고, 이 표 밖의 부호 서술을 금지한다.
    #   ⚠ 창은 **PA 와 같은 `pa_start_dt`(전월말+1)** 를 써야 한다 (2026-08-07 수정).
    #     종전엔 raw `start_dt`(전월말)를 넘겨 전월 마지막 영업일 하루가 섞였다 —
    #     위 §3 과 똑같은 off-by-one 이다. 실측(4JM12 2026-07):
    #       6/30~7/31 → 펀드 -2.31% / BM -1.65% / 초과 -0.66%p   ← 코멘트에 나가던 값
    #       7/01~7/31 → 펀드 -2.90% / BM -2.20% / 초과 -0.70%p   ← 기준가·엑셀과 일치
    #     LLM 이 지어낸 게 아니라 표 자체가 틀린 기간이었다.
    brinson_blk = None
    if pa_start_dt and end_dt:
        try:
            blk = _brinson_factor_block(fund_code, pa_start_dt, end_dt)
            if blk:
                additional_parts.append(blk)
                brinson_blk = blk
        except Exception as e:
            data_warnings.append(f'Brinson 요인 블록 생성 실패: {e}')

    # 환헤지 비율 (포맷 E — 운용경과에 "환 익스포저를 BM 에 맞춰" 를 쓰려면 필요)
    from market_research.core.constants import FUND_CONFIGS as _FCG
    if (_FCG.get(fund_code) or {}).get('format') == 'E' and prev_last and cur_last:
        try:
            hb = _hedge_ratio_block(prev_last, cur_last)
            if hb:
                additional_parts.append(hb)
            else:
                data_warnings.append('환헤지 비율 블록 생성 실패 — 운용경과에 환 포지션 '
                                     '근거가 빠질 수 있습니다')
        except Exception as e:
            data_warnings.append(f'환헤지 비율 블록 생성 실패: {e}')

    # 모펀드 서브 포트폴리오 수익률 (07G04/07G07 — "인컴추구 …%, 수익추구 …%" 문장용)
    if start_dt and end_dt:
        try:
            subs = _sub_portfolio_returns(fund_code, start_dt, end_dt)
            if subs:
                fund_ret = dict(fund_ret or {})
                fund_ret['sub_returns'] = subs
                additional_parts.append(
                    '[서브 포트폴리오 기간수익률 (사실 — 이 값만 인용)]\n'
                    + '\n'.join(f'- {k} 포트폴리오 {v:+.2f}%' for k, v in subs.items()))
        except Exception as e:
            data_warnings.append(f'서브 포트폴리오 수익률 실패: {e}')

    # (편입 제한은 market_view 상단에서 이미 처리됨)

    if additional_parts:
        inputs['additional'] = inputs.get('additional', '') + '\n\n' + '\n\n'.join(additional_parts)

    # 8. data_ctx 구성
    data_ctx = {
        'bm': bm,
        'fund_ret': fund_ret,
        'pa': pa,
        'holdings_end': holdings_end,
        'holdings_diff': holdings_diff,
        'price_patterns': price_patterns,
    }

    # 8.5. 자산군 시드 — 승인본이 있으면 공통 문단을 결정론적으로 조립 (2026-08-05)
    #
    # 시장동향·전망은 같은 기간 모든 펀드가 공유한다. 종전엔 펀드마다 LLM 이 새로
    # 써서 미세하게 갈렸고(2026-07 은 7개 펀드를 손으로 통일해 발송), 미보유
    # 자산군 제외도 프롬프트 지시에만 의존했다.
    # → 승인 시드가 있으면 보유 자산군 문장만 골라 조립하고, LLM 은 펀드 고유
    #   블록만 쓴다. 시드가 없거나 블록 파싱이 실패하면 **종전 경로 그대로** 간다.
    from market_research.report.comment_engine import (
        generate_report_from_inputs, parse_seeded_blocks, assemble_seeded_comment,
        build_perf_sentence, check_block_rules,
    )
    from market_research.report.market_seed import (
        assemble as _seed_assemble, load_approved_seed, seed_coverage,
        compress_market_paragraph as _compress_market,
    )
    from market_research.core.constants import (
        FUND_CONFIGS as _FC, MARKET_PARA_CAP as _MARKET_CAP,
        FIXED_PERF_SENTENCE_FUNDS as _FIXED_PERF,
    )

    fmt = (_FC.get(fund_code) or {}).get('format', 'C')
    seed = load_approved_seed(period_key)
    seed_sections = None
    seed_meta = {'used': False, 'reason': 'no_approved_seed'}
    if seed:
        seed_sections = {
            'market': _seed_assemble(seed, active_classes, 'market'),
            'outlook': _seed_assemble(seed, active_classes, 'outlook'),
        }
        cov = {s: seed_coverage(seed, active_classes, s) for s in ('market', 'outlook')}
        if not seed_sections['market'] or not seed_sections['outlook']:
            # 보유 자산군에 해당하는 시드 문장이 하나도 없음 — 조립 불가
            seed_sections = None
            seed_meta = {'used': False, 'reason': 'seed_empty_for_active_classes',
                         'coverage': cov}
            data_warnings.append('시드에 이 펀드 보유 자산군 문장이 없어 레거시 경로 사용')
        else:
            seed_meta = {'used': True, 'format': fmt,
                         'active_classes': sorted(active_classes), 'coverage': cov}
            for s, c in cov.items():
                if c['missing']:
                    data_warnings.append(
                        f'시드 {s} 섹션에 {", ".join(c["missing"])} 문장 없음 — 해당 자산군 서술 누락')
            # 펀드별 시장동향 상한 (2026-08-06 사용자 지시 — 2JM23 400자).
            # 발송본 텍스트 상자가 좁은 펀드만. 미등록 펀드는 그대로 지나간다.
            _cap = _MARKET_CAP.get(fund_code)
            if _cap:
                _c = _compress_market(seed_sections['market'], _cap)
                seed_sections['market'] = _c['text']
                seed_meta['market_cap'] = {
                    'cap': _cap, 'applied': _c['applied'],
                    'chars': len(_c['text']), 'reason': _c['reason'],
                    'cached': _c['cached'],
                }
                if not _c['applied']:
                    data_warnings.append(
                        f'시장동향 {_cap}자 재압축 실패({_c["reason"]}) — '
                        f'{len(_c["text"])}자 원문을 그대로 씁니다. 직접 줄여주세요')

    # 9. LLM 호출 (Opus)
    result = generate_report_from_inputs(
        fund_code, year, quarter, data_ctx, inputs,
        model='claude-opus-4-8',
        start_date=start_dt, end_date=end_dt,
        seed_sections=seed_sections,
    )

    comment_text_raw = result.get('comment', '')
    cost = result.get('cost', 0)
    token_usage = result.get('token_usage', {})

    # 9.2. 시드 모드면 블록 파싱 → 조립. 실패 시 레거시 전문 생성으로 1회 재시도
    #      (깨진 블록 원문을 그대로 산출물에 넣지 않기 위함).
    if seed_sections:
        blocks = parse_seeded_blocks(comment_text_raw, fmt)
        if blocks:
            # 성과 문단을 코드가 쓰는 펀드 (2026-08-06 사용자 지시 — 2JM23).
            # 수치 나열이라 LLM 이 개입하면 오기·표현 흔들림만 생긴다. 해설은 붙이지 않는다.
            if fund_code in _FIXED_PERF and '성과' in blocks:
                _fixed = build_perf_sentence(_perf_period_label(mode, end_dt, quarter),
                                             fund_ret, pa, data_warnings)
                if _fixed:
                    seed_meta['fixed_perf'] = {'llm_chars': len(blocks['성과']),
                                               'fixed_chars': len(_fixed)}
                    blocks['성과'] = _fixed
                else:
                    data_warnings.append(
                        '성과 문장 고정 생성 실패(PA 수치 없음) — LLM 문단을 그대로 씁니다')
            # 펀드별 블록 규칙(2JM23 운용계획: 숫자·종목명·정도부사 금지) 준수 점검.
            # 자동으로 지우지 않는다 — 숫자를 기계적으로 빼면 문장이 깨진다. Admin 이 고친다.
            for _bname, _btext in blocks.items():
                for _v in check_block_rules(fund_code, _bname, _btext):
                    data_warnings.append(f'{_bname} 블록 규칙 위반 — {_v}')
            # 펀드성과의 수익률이 Brinson 표와 같은지 (LLM 이 BM 을 지어낸 실측 있음)
            if '펀드성과' in blocks:
                _check_perf_numbers(blocks['펀드성과'], brinson_blk or '', data_warnings)
            sub_line = ''
            if fmt == 'K' and (fund_ret or {}).get('sub_returns'):
                subs = fund_ret['sub_returns']
                sub_line = ('{who}의 비중은 {r} 수준으로 유지하였습니다.'.format(
                    who='와 '.join(f'{l}포트폴리오' for l in subs),
                    r=(_FC.get(fund_code) or {}).get('sub_ratio', 'N/A')))
            # 포맷 E(DB생명) 환헤지 문장 — 전월 승계 + 레인지만 기간말 환율 기준 제안
            hedge_line = ''
            if fmt == 'E':
                hedge_line = _hedge_line(fund_code, period_key, end_dt, data_warnings)
            comment_text_raw = assemble_seeded_comment(
                fmt, seed_sections['market'], seed_sections['outlook'],
                blocks, sub_line=sub_line, hedge_line=hedge_line)
            seed_meta['blocks'] = {k: len(v) for k, v in blocks.items()}
        else:
            seed_meta = {'used': False, 'reason': 'block_parse_failed', 'format': fmt}
            data_warnings.append('시드 블록 파싱 실패 — 레거시 전문 생성으로 재시도')
            result = generate_report_from_inputs(
                fund_code, year, quarter, data_ctx, inputs,
                model='claude-opus-4-8',
                start_date=start_dt, end_date=end_dt,
            )
            comment_text_raw = result.get('comment', '')
            cost += result.get('cost', 0)
            token_usage = result.get('token_usage', {})

    # 9.5. R6-A — [ref:N] 검증 + raw / customer 분리
    # 시장 debate 의 evidence_annotations 를 그대로 재사용 (ref 번호 일관)
    fund_evidence_annotations = inputs.get('evidence_annotations') or []
    from market_research.report.evidence_trace import (
        validate_citations, validate_claim_citations, strip_refs,
    )
    citation_result = validate_citations(comment_text_raw,
                                            fund_evidence_annotations)
    comment_citations = citation_result['comment_citations']
    citation_validation = citation_result['citation_validation']
    customer_comment = strip_refs(comment_text_raw)

    # R9-A.5 — claim citation surface (read-only). inputs.claims 가 있으면
    # 그대로 사용, 없으면 빈 list. customer_comment 에 [claim:hash10] 태그가
    # 그대로 남아있는 정책 (사용자 결정으로 strip 미적용 — admin/client 동시
    # 노출). 본 단계는 trace 만 부착하고 sanitize 정책은 변경하지 않음.
    fund_canonical_claims = inputs.get('claims') or []
    claim_citation_result = validate_claim_citations(
        comment_text_raw, fund_canonical_claims)
    claim_citations = claim_citation_result['claim_citations']
    claim_citation_validation = (
        claim_citation_result['claim_citation_validation'])

    # inputs_used 에는 evidence_annotations 풀더미 저장 금지 (200자 트렁크 적용 안됨)
    # — 원자료는 별도 top-level evidence_annotations 필드로
    inputs_used = {}
    for k, v in inputs.items():
        if k == 'evidence_annotations':
            continue
        inputs_used[k] = v[:200] if isinstance(v, str) else v

    # 10. fund draft 저장 (P1-① — 펀드 코멘트도 자체 run ID 1회 발급)
    debate_run_id = uuid.uuid4().hex
    draft_data = {
        'fund_code': fund_code,
        'period': period_key,
        'report_type': FUND_REPORT_TYPE,
        'status': STATUS_DRAFT,
        'debate_run_id': debate_run_id,
        # R6-A: client 노출은 customer 만, raw 는 admin 전용
        'draft_comment': customer_comment,
        'draft_comment_raw': comment_text_raw,
        'comment_citations': comment_citations,
        'citation_validation': citation_validation,
        # R9-A.5 — claim trace surface (admin viewer 용, client display 무영향)
        'claim_citations': claim_citations,
        'claim_citation_validation': claim_citation_validation,
        'evidence_annotations': fund_evidence_annotations,
        'market_debate_period': period_key,
        # 시드 조립 추적 (2026-08-05) — admin 이 "이 코멘트가 공통 시드로 조립된
        # 것인지 / 어떤 자산군이 살아남았는지" 를 산출물만 보고 알 수 있어야 한다.
        'seed_assembly': seed_meta,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'model': 'claude-opus-4-8',
        'cost_usd': round(cost, 3),
        'token_usage': token_usage,
        'data_warnings': data_warnings,
        'data_snapshot': {
            'bm_count': len(bm),
            'pa_classes': list(pa.keys()),
            'holdings_top3': sorted(holdings_end.items(), key=lambda x: -x[1])[:3] if holdings_end else [],
            'fund_return': fund_ret,
            'trades': trades,
            'position_events': position_events,
        },
        'inputs_used': inputs_used,
        'edit_history': [],
    }

    save_draft(period_key, fund_code, draft_data, target_suffix=target_suffix)
    return draft_data
