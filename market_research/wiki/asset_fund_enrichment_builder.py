"""P3-4 / P3-5: 03_Assets / 04_Funds enrichment + internal link builder.

원천 지식층 보강용. daily_update Step 2.6 이후 후처리 단계에서 호출.

핵심 원칙:
  - 운영 wiki 를 직접 overwrite 하지 않는 dry-run 모드 기본 제공.
  - dry_run=True (기본): 메모리 상에서만 page 객체 생성 + plan 반환.
  - dry_run=False: 실제 디스크 write (호출자가 명시적 GO 시점에만 사용).
  - 8 자산군 표준명 사용 (`REQUIRED_ASSET_CLASSES` + 파일명 표준).
  - 7 펀드 (07G02/07G03 제외, 07G04 포함) 만 fund page 생성.
  - 07G04 page 에 look-through + 모펀드 (07G02/07G03) 참조 명시.
  - 사람이 따라갈 수 있는 internal link [[wiki path]] 자동 삽입.
  - LLM 호출 0. 운영 final/draft/jsonl 수정 0.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from market_research.wiki.paths import (
    ASSETS_DIR, ENTITIES_DIR, EVENTS_DIR, FUNDS_DIR, WIKI_ROOT,
)
from market_research.report.asset_coverage import (
    REQUIRED_ASSET_CLASSES, _scan_text_for_asset,
)

# ─────────────────────────────────────────────────────────────────────
# 표준 파일명 / 자산군 상수
# ─────────────────────────────────────────────────────────────────────
ASSET_FILENAME_STEMS: dict[str, str] = {
    "국내주식": "국내주식",
    "해외주식": "해외주식",
    "국내채권": "국내채권",
    "해외채권": "해외채권",
    "환율": "환율",
    "금/대체": "금_대체",      # 슬래시 대신 언더스코어
    "크레딧": "크레딧",
    "현금성": "현금성",
}

# 펀드 운용보고 대상 (사용자 지시) — 07G02/07G03 제외
FUND_TARGETS: tuple[str, ...] = (
    "07G04", "08K88", "08N33", "08N81", "08P22", "2JM23", "4JM12",
)

# 07G04 의 look-through 모펀드 — 별도 fund page 생성 금지, 참조만
LOOKTHROUGH_MOTHER_FUNDS: dict[str, tuple[str, ...]] = {
    "07G04": ("07G02", "07G03"),
}

# 펀드 메타 (간단 요약 — config/funds.py FUND_META 와 별도, 본 builder 자급자족용)
FUND_META: dict[str, dict[str, str]] = {
    "07G04": {"name": "한국투자OCIO알아서증권자투자신탁(채권혼합-재간접형)",
              "primary_assets": "국내주식, 해외주식, 국내채권, 해외채권",
              "note": "look-through 구조 (07G02/07G03 모펀드 편입)"},
    "08K88": {"name": "한국투자OCIO알아서성장형일반사모증권투자신탁",
              "primary_assets": "해외주식, 국내주식, 채권 일부",
              "note": "성장형, 공격적 자산배분"},
    "08N33": {"name": "한국투자OCIO알아서베이직일반사모투자신탁",
              "primary_assets": "국내채권, 국내주식, 해외주식",
              "note": "안정형, 보수적 자산배분"},
    "08N81": {"name": "한국투자OCIO알아서액티브일반사모투자신탁",
              "primary_assets": "해외채권, 해외주식, 국내채권",
              "note": "듀레이션 확대, HY 일부"},
    "08P22": {"name": "한국투자OCIO알아서프라임일반사모투자신탁",
              "primary_assets": "국내채권, 해외채권, 국내주식",
              "note": "종합채권+은행채 중심"},
    "2JM23": {"name": "오렌지라이프자산배분B형",
              "primary_assets": "해외주식, 국내주식, 금/대체",
              "note": "글로벌자산배분, 절대수익 목표"},
    "4JM12": {"name": "(무)동부글로벌 Active 자산배분혼합형",
              "primary_assets": "금/대체, 해외주식, 환율",
              "note": "금광주, 달러선물 활용"},
}

# 펀드 → 주요 노출 자산군 (link 우선순위)
FUND_PRIMARY_ASSETS: dict[str, tuple[str, ...]] = {
    "07G04": ("국내주식", "해외주식", "국내채권", "해외채권"),
    "08K88": ("해외주식", "국내주식", "환율", "국내채권"),
    "08N33": ("국내채권", "국내주식", "해외주식"),
    "08N81": ("해외채권", "해외주식", "국내채권"),
    "08P22": ("국내채권", "해외채권", "국내주식"),
    "2JM23": ("해외주식", "국내주식", "금/대체"),
    "4JM12": ("금/대체", "해외주식", "환율"),
}

# 자산군별 운용보고 활용 메모 (정형 문구 — 단정 회피)
ASSET_OVERVIEW: dict[str, str] = {
    "국내주식": (
        "국내주식은 펀드 자산배분에서 위험자산 노출의 한 축이며, "
        "KOSPI/코스닥 흐름과 외국인 수급, 환율 변동에 민감하다. "
        "OCIO 퇴직연금 펀드는 보통 국내주식을 BM 비중에 맞춰 패시브 또는 "
        "ETF 형태로 편입하며, 본월 코스피·코스닥 등락이 펀드 수익률 핵심 동인 "
        "중 하나로 작용한다. 외국인 수급 방향과 글로벌 위험자산 sentiment 가 "
        "단기 흐름을, 기업 실적과 통화정책이 중기 흐름을 주도한다."
    ),
    "해외주식": (
        "해외주식은 미국 성장주 / 글로벌 분산을 통한 위험자산 노출 확대 수단이며, "
        "S&P500 / 나스닥 / MSCI ACWI / 환율 변동을 통해 펀드 수익률에 영향을 준다. "
        "OCIO 펀드는 환오픈/환헷지 비중에 따라 원화환산 수익률 변동성이 달라지며, "
        "AI/반도체/빅테크 사이클이 글로벌 성장주 흐름을 주도한다. "
        "VOO/SPY/QQQ/EFA 등 ETF 편입을 통해 효율적 분산을 추구한다."
    ),
    "국내채권": (
        "국내채권은 펀드 안정성/듀레이션 핵심 축이며, "
        "한은 기준금리, 국고채 흐름, 물가 전망에 따라 가격이 변동한다. "
        "OCIO 펀드는 국고채 + 통안채 + 회사채(IG) 조합으로 듀레이션을 관리하며, "
        "본월 한은 금통위 결정과 물가 경로, 환율 변동이 채권 수익률에 영향을 준다. "
        "장단기 금리 스프레드와 외국인 채권 수급 방향이 추가 변수다."
    ),
    "해외채권": (
        "해외채권은 글로벌 듀레이션/통화 분산 도구이며, "
        "미국채 10Y, 연준 정책, 달러 흐름이 핵심 변수다. "
        "OCIO 펀드는 BBG Global Aggregate (헷지/언헷지) 또는 미국채 ETF (TLT/IEF) "
        "형태로 편입하며, 환헷지 비율에 따라 원화환산 수익률 노출이 결정된다. "
        "FOMC 회의·점도표·인플레이션 지표 발표가 단기 변동성의 주된 트리거다."
    ),
    "환율": (
        "환율(USDKRW)은 펀드 해외자산의 원화환산 수익률을 직접 좌우하며, "
        "달러 강세/약세, 외국인 수급, 경상수지, 한미 금리차에 영향을 받는다. "
        "지정학 리스크 발생 시 안전자산 달러 매수가 강해지며, 위험선호 "
        "회복 시 원화 강세가 진행된다. 본월 환율 변동은 펀드 해외주식·해외채권 "
        "평가액에 직접 반영되며, 환헷지 펀드는 헷지 비용/베이시스 위험이 동반된다."
    ),
    "금/대체": (
        "금/대체 자산은 인플레이션 헤지 + 지정학 리스크 헤지 역할이며, "
        "유가/원자재/금 가격 흐름이 핵심 변수다. "
        "OCIO 펀드는 GLD/IAU/금ETF 또는 원자재 ETF (DBC/PDBC), 리츠 등으로 "
        "분산 노출을 가져가며, 달러 흐름과 역상관 + 실질금리 역상관이 일반적이다. "
        "본월 중동/지정학 이벤트와 OPEC 산유 정책이 유가·금 가격에 직접 영향."
    ),
    "크레딧": (
        "크레딧(HY/회사채)은 위험자산 + 캐리 수익 목적이며, "
        "신용스프레드, 디폴트율, 금리 환경에 민감하다. "
        "OCIO 펀드는 HYG/JNK/IG 회사채 ETF 또는 직접 회사채 편입으로 노출을 가져가며, "
        "경기 사이클 후반부에 변동성이 확대되는 특성이 있다. "
        "스프레드 확대/축소 방향이 단기 수익률을 좌우하고, 디폴트 사이클이 중기 위험."
    ),
    "현금성": (
        "현금성 자산은 유동성 확보와 단기금리 수익 목적이며, "
        "MMF/CD/콜 금리 흐름이 핵심이지만 펀드 운용보고 영향도는 낮다. "
        "본 자산군은 유동성 버퍼/단기 환매 대비 목적이 주된 기능이며, "
        "월별 수익 기여도는 제한적이다. 단기 정책금리 변동이 캐리 수익에 영향을 주나, "
        "운용보고에서는 보통 '특이 이벤트 부재' 수준으로만 점검한다."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return (s or "").lower()


def _safe_period_re(period: str) -> bool:
    p = (period or "").strip()
    if not re.fullmatch(r"\d{4}-(?:\d{2}|Q[1-4])", p):
        return False
    tail = p[5:]
    if tail.startswith("Q"):
        return True
    try:
        m = int(tail)
    except ValueError:
        return False
    return 1 <= m <= 12


def _list_existing(dir_path: Path, period: str) -> list[Path]:
    if not dir_path.exists():
        return []
    return sorted(dir_path.glob(f"{period}_*.md"))


# ─────────────────────────────────────────────────────────────────────
# 03_Assets 빌더
# ─────────────────────────────────────────────────────────────────────

def _related_events_for_asset(asset_class: str, period: str) -> list[Path]:
    """01_Events 중 해당 자산군 키워드 hit 페이지 (top 5)."""
    out: list[tuple[int, Path]] = []
    for fp in EVENTS_DIR.glob(f"{period}_*.md"):
        try:
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        score = _scan_text_for_asset(fp.name + " " + txt, asset_class)
        if score > 0:
            out.append((score, fp))
    out.sort(key=lambda x: -x[0])
    return [fp for _, fp in out[:5]]


def _related_entities_for_asset(asset_class: str) -> list[Path]:
    """02_Entities 중 해당 자산군 hit 페이지 (top 3) — entity는 period suffix 다양."""
    out: list[tuple[int, Path]] = []
    for fp in ENTITIES_DIR.glob("*.md"):
        try:
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        score = _scan_text_for_asset(fp.name + " " + txt, asset_class)
        if score > 0:
            out.append((score, fp))
    out.sort(key=lambda x: -x[0])
    return [fp for _, fp in out[:3]]


def _related_funds_for_asset(asset_class: str) -> list[str]:
    """해당 자산군을 primary 노출로 가진 펀드 목록."""
    out: list[str] = []
    for f in FUND_TARGETS:
        if asset_class in FUND_PRIMARY_ASSETS.get(f, ()):
            out.append(f)
    return out


def _wiki_link(target_path: Path) -> str:
    """절대 path → `[[<dir>/<stem>]]` 형식. WIKI_ROOT 외 path 면 빈 문자열."""
    try:
        rel = target_path.relative_to(WIKI_ROOT)
    except ValueError:
        return ""
    parts = list(rel.parts)
    if parts and parts[-1].endswith(".md"):
        parts[-1] = parts[-1][:-3]
    return f"[[{'/'.join(parts)}]]"


def _fund_link(fund_code: str, period: str) -> str:
    return f"[[04_Funds/{period}_{fund_code}]]"


def _asset_link(asset_class: str, period: str) -> str:
    stem = ASSET_FILENAME_STEMS[asset_class]
    return f"[[03_Assets/{period}_{stem}]]"


def build_asset_page(asset_class: str, period: str) -> str:
    """단일 03_Assets/{period}_{stem}.md 본문 생성. read-only."""
    stem = ASSET_FILENAME_STEMS[asset_class]
    overview = ASSET_OVERVIEW[asset_class]
    events = _related_events_for_asset(asset_class, period)
    entities = _related_entities_for_asset(asset_class)
    funds = _related_funds_for_asset(asset_class)

    front = (
        "---\n"
        f"period: {period}\n"
        f"asset_class: {asset_class}\n"
        "source_type: asset_wiki\n"
        "generated_by: asset_fund_enrichment_builder\n"
        "---\n\n"
    )
    body: list[str] = [f"# {period} {asset_class}", ""]

    body.append("## 1. 자산군 개요")
    body.append(overview)
    body.append("")

    body.append("## 2. 본월 핵심 시장 변수")
    if asset_class in ("국내채권", "해외채권"):
        body.append("- 금리/물가/중앙은행 정책 동향이 듀레이션·캐리 수익률을 좌우.")
        body.append("- 환율/유가가 인플레이션 경로를 통해 간접 영향.")
    elif asset_class in ("국내주식", "해외주식"):
        body.append("- 기업 실적/통화정책/지정학 이벤트가 위험자산 sentiment 를 좌우.")
        body.append("- 환율은 해외주식의 원화환산 수익률에 직접 영향.")
    elif asset_class == "환율":
        body.append("- USDKRW 는 달러 강/약세, 한미 금리차, 외국인 수급에 따라 변동.")
        body.append("- 펀드 해외자산 노출 비중에 따라 수익률 영향이 크게 달라짐.")
    elif asset_class == "금/대체":
        body.append("- 유가/원자재/금 가격이 인플레이션 헤지/지정학 헤지 수요를 반영.")
        body.append("- 달러 흐름과 역상관, 실질금리와도 연동.")
    elif asset_class == "크레딧":
        # P3-4.1: 핵심 변수 chip 강제 (HY / 회사채 / 신용스프레드 / credit spread / 금리 경로 / 위험선호)
        body.append("- 핵심 변수: HY 스프레드, 회사채 발행 환경, 신용스프레드 (credit spread).")
        body.append("- 금리 경로와 위험선호 변화가 단기 변동성을 좌우.")
        body.append("- 디폴트율/회수율은 중기 위험. 사이클 후반부에 변동성 확대 가능성.")
    else:  # 현금성
        # P3-4.1: 핵심 변수 chip 강제 (단기금리 / CD / MMF / 유동성 / 리밸런싱 대기자금)
        body.append("- 핵심 변수: 단기금리, CD/MMF 금리, 콜 금리.")
        body.append("- 유동성 버퍼 역할 + 리밸런싱 대기자금/대기성 자금 보유 목적.")
        body.append("- 운용보고 영향도는 제한적이며, 단기 캐리 수익 외 대형 위험 없음.")
    body.append("")

    body.append("## 3. 성과 및 위험 요인")
    if asset_class in ("국내채권", "해외채권"):
        body.append("- 듀레이션, 금리 민감도, 크레딧 스프레드 변화에 노출.")
    elif asset_class in ("국내주식", "해외주식"):
        body.append("- 시장 변동성, 섹터 쏠림, 외국인 수급, 환율 노출.")
    elif asset_class == "환율":
        body.append("- 환차손익이 펀드 해외자산 평가에 직접 반영.")
    elif asset_class == "금/대체":
        body.append("- 가격 변동성, 보관/롤오버 비용, 통화 노출.")
    elif asset_class == "크레딧":
        body.append("- 신용 risk, 유동성 risk, 금리 risk 가 동시 노출.")
    else:
        body.append("- 단기금리 변동에 따른 캐리 수익 외 대형 위험은 제한적.")
    body.append("")

    body.append("## 4. 관련 이벤트")
    if events:
        for fp in events:
            body.append(f"- {_wiki_link(fp)}")
    else:
        body.append("- (본월 직접 매칭 이벤트 없음 — 가격 흐름 중심으로 점검)")
    # P3-4.1: 크레딧/현금성은 직접 이벤트 제한 가능성 명시 (filler 대신 사실 표시)
    if asset_class in ("크레딧", "현금성"):
        if not events:
            body.append("")
            body.append(
                f"> **직접 이벤트 제한적** — 본월 {asset_class} 자산군에 "
                "직접 매핑되는 이벤트가 부족합니다. 억지 인과 없이 가격 흐름 / "
                "단기금리 변동 중심으로만 점검하며, 운용보고 본문에서는 "
                "'특이 이벤트 부재' 또는 '영향 제한' 식의 짧은 문구로만 다룹니다."
            )
        else:
            body.append("")
            body.append(
                f"> **이벤트 제한 가능성** — {asset_class} 자산군은 직접 매핑 "
                "이벤트가 적을 수 있습니다. 위 link 가 있더라도 운용보고에서는 "
                "'관찰 필요' / '가격 흐름 중심' 으로 짧게 처리합니다."
            )
    if entities:
        body.append("")
        body.append("### 관련 엔티티")
        for fp in entities:
            body.append(f"- {_wiki_link(fp)}")
    body.append("")

    body.append("## 5. 관련 펀드")
    if funds:
        for f in funds:
            body.append(f"- {_fund_link(f, period)}")
    else:
        body.append("- 직접 관련 펀드 제한적 (운용보고 영향도 낮음).")
    body.append("")

    body.append("## 6. 운용보고 활용 메모")
    if asset_class == "현금성":
        # P3-4.1: 직접 이벤트 제한적 명시 + 펀드 역할 명시 (또는 제한적 명시)
        body.append(
            "- 본월 특이 이벤트 부재 가능성 — '영향 제한' / '가격 흐름 중심' 표현 권장."
        )
        body.append(
            "- 단기 정책금리 변동에 따른 캐리 수익 외 대형 위험은 제한적. "
            "운용보고 본문 1문장 내외로만 짧게 점검."
        )
        body.append(
            "- 펀드 역할: 직접 관련 펀드 제한적. 모든 OCIO 펀드의 유동성 버퍼 / "
            "리밸런싱 대기자금 형태로만 기능하며, 단독 비중 의사결정 대상이 아님."
        )
    elif asset_class == "크레딧":
        # P3-4.1: 직접 이벤트 제한적 명시 + 운용보고 활용 방식 + 펀드 역할
        body.append(
            "- 직접 이벤트가 제한적일 수 있음 — '관찰 필요' / 'HY 스프레드 변화' / "
            "'회사채 발행 환경' 식으로 짧게 점검."
        )
        body.append(
            "- 신용스프레드 (credit spread) 확대/축소 방향이 핵심. "
            "본월 직접 이벤트가 부족하면 억지 인과를 만들지 말고 가격 흐름 중심으로 처리."
        )
        if funds:
            body.append(
                f"- 펀드 역할: 위 관련 펀드 ({', '.join(funds)}) 의 위험자산 + "
                "캐리 수익 일부. 단정적 전망 금지, '조건부' 표현."
            )
        else:
            body.append(
                "- 펀드 역할: 직접 관련 펀드 제한적. 운용보고 본문에서는 보조적 "
                "점검 대상."
            )
    elif funds:
        body.append(
            f"- {asset_class} 변동은 위 관련 펀드 ({', '.join(funds)}) 수익률에 영향. "
            "단정적 전망 대신 '관찰 필요' / '조건부' 표현 권장."
        )
        body.append(
            "- 본월 데이터/이벤트 근거가 약한 부분은 단정 회피. "
            "graph/timeseries 가 결합된 신호를 우선 인용하고, 키워드 매칭 기반 "
            "evidence 는 보조로만 활용."
        )
    else:
        body.append(
            "- 본 자산군은 본월 운용보고에서 보조적 점검 대상. "
            "단정 표현 자제, 가격 흐름 중심으로 짧게 점검."
        )
    body.append("")
    body.append("## 7. Cross-reference")
    body.append(
        "- 본 페이지는 daily_update 후처리 단계의 asset_fund_enrichment_builder "
        "가 자동 생성한 표준 wiki 페이지다. 운용보고 작성 시 위 5번 섹션의 "
        "관련 펀드 link 와 4번 섹션의 관련 이벤트 link 를 cross-reference "
        "근거로 사용한다."
    )
    body.append("")

    return front + "\n".join(body)


# ─────────────────────────────────────────────────────────────────────
# 04_Funds 빌더
# ─────────────────────────────────────────────────────────────────────

def _related_events_for_fund(fund_code: str, period: str) -> list[Path]:
    """펀드 primary asset 들의 합집합 이벤트 (top 5 dedupe)."""
    seen: set[str] = set()
    scored: list[tuple[int, Path]] = []
    for ac in FUND_PRIMARY_ASSETS.get(fund_code, ()):
        for fp in _related_events_for_asset(ac, period):
            key = fp.name
            if key in seen:
                continue
            seen.add(key)
            txt = fp.read_text(encoding="utf-8", errors="ignore")
            scored.append((_scan_text_for_asset(txt, ac), fp))
    scored.sort(key=lambda x: -x[0])
    return [fp for _, fp in scored[:5]]


def build_fund_page(fund_code: str, period: str) -> str:
    if fund_code not in FUND_TARGETS:
        raise ValueError(f"fund_code {fund_code!r} is not in FUND_TARGETS — refused")
    meta = FUND_META[fund_code]
    primary_assets = FUND_PRIMARY_ASSETS.get(fund_code, ())
    events = _related_events_for_fund(fund_code, period)

    front = (
        "---\n"
        f"period: {period}\n"
        f"fund_code: {fund_code}\n"
        "source_type: fund_wiki\n"
        "generated_by: asset_fund_enrichment_builder\n"
        "---\n\n"
    )
    body: list[str] = [f"# {period} {fund_code}", ""]

    body.append("## 1. 펀드 개요")
    body.append(f"- **펀드명**: {meta['name']}")
    body.append(f"- **주요 자산군**: {meta['primary_assets']}")
    body.append(f"- **운용 메모**: {meta['note']}")
    body.append("")

    body.append("## 2. 주요 자산군 노출")
    if primary_assets:
        for ac in primary_assets:
            body.append(f"- {ac}: {_asset_link(ac, period)}")
    else:
        body.append("- (정의된 primary 자산군 없음)")
    body.append("")

    body.append("## 3. 본월 성과 민감도")
    body.append(
        "- 본월 펀드 수익률은 위 주요 자산군의 BM/PA 흐름에 좌우됨. "
        "구체 수치는 운용보고 본문(코멘트/PA)에서 별도 제시."
    )
    if "환율" in primary_assets or "해외주식" in primary_assets or "해외채권" in primary_assets:
        body.append(
            "- USDKRW 변동이 원화환산 수익률에 직접 영향. 환오픈 비중 "
            "수준에 따라 환차손익 기여도가 달라지며, 본월 달러 흐름이 핵심 변수."
        )
    if "국내채권" in primary_assets or "해외채권" in primary_assets:
        body.append(
            "- 듀레이션·금리 민감도가 핵심 위험. 본월 한은/연준 정책, "
            "장단기 금리 스프레드, 물가 경로 변화가 채권 평가액에 직접 영향."
        )
    if "금/대체" in primary_assets:
        body.append(
            "- 금/원자재 가격 변동성과 달러 흐름이 주요 변수. 지정학 "
            "이벤트/OPEC 정책/실질금리 변동이 단기 변동성을 키우는 트리거."
        )
    if "국내주식" in primary_assets or "해외주식" in primary_assets:
        body.append(
            "- 위험자산 sentiment, 기업 실적, 외국인 수급, 섹터 쏠림이 "
            "단기 변동성 핵심 변수. 본월 기술주/AI 사이클이 추가 영향 요인."
        )
    body.append(
        f"- 펀드 운용 메모: {meta['note']}. 자세한 BM/PA/holdings 수치는 "
        "운용보고 본문에서 별도 제시."
    )
    body.append("")

    body.append("## 4. 관련 시장 이벤트")
    if events:
        for fp in events:
            body.append(f"- {_wiki_link(fp)}")
    else:
        body.append("- (본월 직접 매칭 이벤트 없음)")
    body.append("")

    body.append("## 5. 운용보고 활용 메모")
    body.append(
        f"- {fund_code} 코멘트 작성 시 위 주요 자산군의 본월 동향을 "
        "조건부/단정 회피 형태로 반영. evidence/related_news 는 "
        "동일 기간 _market debate 에서 fan-out 결합."
    )
    body.append(
        f"- 본월 펀드 final_comment 본문에는 {meta['primary_assets']} "
        "자산군 영향을 최소 한 번씩 분산 배치하고, 근거가 약한 자산군은 "
        "'영향 제한' / '관찰 필요' / '직접 근거 부족' 표현으로 짧게 점검한다."
    )
    body.append(
        "- BM 비중·PA 기여도·holdings 흐름은 운용보고 별도 섹션에서 제시하며, "
        "본 wiki 페이지는 사전 요약 + cross-reference 용도로만 사용한다."
    )
    body.append("")
    body.append("## 6. Cross-reference")
    body.append(
        "- 본 페이지는 asset_fund_enrichment_builder 가 자동 생성한 표준 fund "
        "wiki 페이지다. 위 2번 섹션의 자산군 link 와 4번 섹션의 이벤트 link "
        "는 모두 클릭 가능한 wiki internal link 다."
    )
    body.append("")

    # 07G04 전용 look-through 섹션 (사용자 지시)
    if fund_code == "07G04":
        body.append("## Look-through 구조")
        mothers = LOOKTHROUGH_MOTHER_FUNDS.get(fund_code, ())
        body.append(
            "- 07G04 는 모자형 구조이며, look-through 기준 실질 자산배분으로 "
            "운용보고를 작성한다."
        )
        for m in mothers:
            body.append(
                f"- {m} 는 **모펀드**로, 별도 운용보고 생성 대상이 아니며 "
                "look-through 참조용으로만 사용된다 (별도 04_Funds/{m} 페이지를 "
                "생성하지 않는다)."
            )
        body.append("")

    return front + "\n".join(body)


# ─────────────────────────────────────────────────────────────────────
# Internal link audit (broken / self / count)
# ─────────────────────────────────────────────────────────────────────

_LINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")


def _resolve_internal_link(token: str) -> str:
    """`03_Assets/2026-04_국내주식` → 절대 경로 후보 (확장자 보정)."""
    p = WIKI_ROOT / (token + ".md")
    return str(p)


def audit_internal_links(pages: dict[str, str]) -> dict:
    """주어진 page dict (rel path str → body str) 의 internal link 통계.

    pages 키는 wiki-root 기준 rel path (예: '03_Assets/2026-04_국내주식.md').
    self-link / broken / total 반환. 외부 (디스크 기존 wiki) 페이지도 검사.
    """
    total = 0
    broken: list[tuple[str, str]] = []
    self_links: list[tuple[str, str]] = []
    for src_rel, body in pages.items():
        for m in _LINK_RE.finditer(body):
            tok = m.group(1).strip()
            total += 1
            target_rel = tok + ".md"           # wiki-root 기준
            target_abs = WIKI_ROOT / target_rel  # 절대 경로
            src_stem = Path(src_rel).stem
            tok_stem = Path(target_rel).stem
            if src_stem == tok_stem:
                self_links.append((src_rel, tok))
            # broken: plan 내부 dict 에도 없고, 디스크에도 없음
            if target_rel not in pages and not target_abs.exists():
                broken.append((src_rel, tok))
    return {
        "total_links": total,
        "broken": broken,
        "self_links": self_links,
    }


# ─────────────────────────────────────────────────────────────────────
# Top-level builder (dry-run only by default)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class EnrichmentPlan:
    period: str
    asset_pages: dict[str, str] = field(default_factory=dict)   # rel path → body
    fund_pages: dict[str, str] = field(default_factory=dict)
    skipped_funds: list[str] = field(default_factory=list)      # 07G02/07G03 제외 기록
    audit: dict = field(default_factory=dict)


def build_enrichment_plan(period: str) -> EnrichmentPlan:
    """모든 page body 를 메모리에 만들고 plan 반환. 디스크 write 없음."""
    if not _safe_period_re(period):
        raise ValueError(f"invalid period: {period!r}")
    plan = EnrichmentPlan(period=period)
    # 8 자산
    for ac in REQUIRED_ASSET_CLASSES:
        stem = ASSET_FILENAME_STEMS[ac]
        rel = f"03_Assets/{period}_{stem}.md"
        plan.asset_pages[rel] = build_asset_page(ac, period)
    # 7 펀드
    for f in FUND_TARGETS:
        rel = f"04_Funds/{period}_{f}.md"
        plan.fund_pages[rel] = build_fund_page(f, period)
    # 07G02/07G03 명시 skip
    for excl in ("07G02", "07G03"):
        plan.skipped_funds.append(excl)

    # internal link audit
    all_pages = {**plan.asset_pages, **plan.fund_pages}
    plan.audit = audit_internal_links(all_pages)
    return plan


def commit_enrichment_plan(plan: EnrichmentPlan) -> dict:
    """실제 디스크 write. 호출자가 명시적 GO 한 시점에만 사용.

    기존 파일 overwrite 가능성 존재. 호출 전 backup 필수.
    """
    written: list[str] = []
    for rel, body in {**plan.asset_pages, **plan.fund_pages}.items():
        target = WIKI_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        written.append(rel)
    return {"written": written}


# ─────────────────────────────────────────────────────────────────────
# wiki_retriever 03/04 확장 옵션 (preview only — 실제 retriever 변경 X)
# ─────────────────────────────────────────────────────────────────────

ASSET_FUND_ELIGIBILITY_MIN_CHARS = 1000   # 03_Assets 핵심 6 자산
ASSET_BOUNDARY_MIN_CHARS = 700           # 03_Assets 보조 (크레딧/현금성)
FUND_ELIGIBILITY_MIN_CHARS = 1200        # 04_Funds

BOUNDARY_ASSETS: tuple[str, ...] = ("크레딧", "현금성")


def evaluate_retrieval_eligibility(plan: EnrichmentPlan) -> dict:
    """plan 의 asset/fund page 가 retriever 기준 충족하는지.

    P3-4.1 변경:
      - 핵심 6 자산: ≥ ASSET_FUND_ELIGIBILITY_MIN_CHARS (1000ch)
      - 보조 (크레딧/현금성): ≥ ASSET_BOUNDARY_MIN_CHARS (700ch) — filler 회피
    """
    asset_ok: dict[str, bool] = {}
    for rel, body in plan.asset_pages.items():
        is_boundary = any(b in rel for b in BOUNDARY_ASSETS)
        thr = ASSET_BOUNDARY_MIN_CHARS if is_boundary else ASSET_FUND_ELIGIBILITY_MIN_CHARS
        asset_ok[rel] = len(body) >= thr
    fund_ok: dict[str, bool] = {}
    for rel, body in plan.fund_pages.items():
        fund_ok[rel] = len(body) >= FUND_ELIGIBILITY_MIN_CHARS
    return {
        "asset_eligible": asset_ok,
        "fund_eligible": fund_ok,
        "asset_eligible_count": sum(1 for v in asset_ok.values() if v),
        "fund_eligible_count": sum(1 for v in fund_ok.values() if v),
        "asset_min_chars_core": ASSET_FUND_ELIGIBILITY_MIN_CHARS,
        "asset_min_chars_boundary": ASSET_BOUNDARY_MIN_CHARS,
        "fund_min_chars": FUND_ELIGIBILITY_MIN_CHARS,
    }


# ─────────────────────────────────────────────────────────────────────
# Filler self-check (P3-4.1)
# ─────────────────────────────────────────────────────────────────────

_FILLER_NORM_RE = re.compile(r"[\s\W_]+")


def _normalize_for_filler(s: str) -> str:
    return _FILLER_NORM_RE.sub("", s).lower()


def detect_filler_repetition(body: str) -> dict:
    """page 본문 내 동일 문장/bullet 3회 이상 반복 검출.

    Returns:
      {"repeated_sentences": [(text, count)], "repeated_bullets": [(text, count)]}
    """
    # 문장 분리: '. ' 또는 줄바꿈
    sentences: list[str] = []
    for line in body.splitlines():
        line = line.strip().lstrip("-").lstrip("*").strip()
        if not line or line.startswith("#") or line.startswith("---") or line.startswith(">"):
            continue
        for s in re.split(r"(?<=[.])\s+", line):
            s = s.strip()
            if len(s) >= 12:
                sentences.append(s)

    norm_counts: Counter = Counter()
    for s in sentences:
        norm_counts[_normalize_for_filler(s)] += 1
    repeated = [(s, n) for s, n in norm_counts.items() if n >= 3 and len(s) >= 12]

    # bullet: '- ' 또는 '* ' 시작 라인
    bullets: list[str] = []
    for line in body.splitlines():
        sl = line.strip()
        if sl.startswith("- ") or sl.startswith("* "):
            tok = sl[2:].strip()
            if len(tok) >= 12:
                bullets.append(tok)
    bullet_counts: Counter = Counter(_normalize_for_filler(b) for b in bullets)
    repeated_bullets = [(b, n) for b, n in bullet_counts.items() if n >= 3 and len(b) >= 12]
    return {
        "repeated_sentences": repeated,
        "repeated_bullets": repeated_bullets,
    }


__all__ = [
    "ASSET_FILENAME_STEMS", "FUND_TARGETS", "FUND_META", "FUND_PRIMARY_ASSETS",
    "LOOKTHROUGH_MOTHER_FUNDS", "BOUNDARY_ASSETS",
    "ASSET_FUND_ELIGIBILITY_MIN_CHARS", "ASSET_BOUNDARY_MIN_CHARS",
    "FUND_ELIGIBILITY_MIN_CHARS",
    "EnrichmentPlan", "build_enrichment_plan", "commit_enrichment_plan",
    "build_asset_page", "build_fund_page",
    "audit_internal_links", "evaluate_retrieval_eligibility",
    "detect_filler_repetition",
]
