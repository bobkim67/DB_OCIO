"""P3-3 Asset coverage guardrail (P3-3.1 hotfix — false-positive 완화).

지배 이슈가 시장을 압도해도, debate prompt 가 주요 자산군별 영향을 최소
한 번씩 점검하도록 guardrail 을 만든다.

P3-3.1 hotfix 변경 (사용자 지시):
  1. raw evidence_count 를 prompt 에 그대로 노출하지 않음 (bucket+signal 만 노출).
  2. include/exclude keyword 분리 + word boundary (영문) + phrase (한글).
  3. selected (relevant primary news) vs all (broad classifier hit) 분리.
  4. dominant_topic_group 산출 (cluster 기반 보강).
  5. summary phrase 어휘 변경 ("직접 근거 충분" → "복수 신호 확인" 등).

Coverage 기준 (변경):
  - covered: signals ≥ 2 AND (graph≥1 OR ts OR ret 중 하나 이상 함께 존재)
              ※ raw evidence 만으로 covered 판정 불가
  - weak   : signals = 1 또는 evidence_only 단독
  - missing: 모든 신호 부재

Fallback 우선순위 (weak/missing):
  evidence_selected → graph → wiki → timeseries → return → no_material_event
"""
from __future__ import annotations

import re
from collections import Counter

# 8개 필수 자산군 (사용자 지시 순서)
REQUIRED_ASSET_CLASSES: tuple[str, ...] = (
    "국내주식",
    "해외주식",
    "국내채권",
    "해외채권",
    "환율",
    "금/대체",
    "크레딧",
    "현금성",
)


# ─────────────────────────────────────────────────────────────────────
# 자산별 include / exclude keyword (P3-3.1 hotfix)
#
# 한국어: substring 매칭 (한글에는 word-boundary 가 없음).
#         단일 글자 키워드 ("금", "달러" 단독) 는 절대 사용 금지 — 반드시 phrase.
# 영문   : 단어 경계 (\b) 매칭. (\b 는 한글에 영향 없음.)
# ─────────────────────────────────────────────────────────────────────

_KOREAN_INCLUDE: dict[str, tuple[str, ...]] = {
    "국내주식": (
        "국내주식", "KOSPI", "코스피", "코스닥", "KOSDAQ",
        "삼성전자", "한국증시", "국내 주식", "한국 증시",
    ),
    "해외주식": (
        "해외주식", "미국주식", "미국 주식", "해외 주식",
        "S&P", "S&P500", "나스닥", "다우", "MSCI",
        "성장주", "빅테크", "AI 관련주", "AI 관련 주",
        "반도체주", "반도체 주식", "테크주", "테크 주식", "반도체 ETF",
        "글로벌 주식",
    ),
    "국내채권": (
        "국내채권", "국내 채권", "국고채", "한국 국고채",
        "한은", "한국은행", "기준금리", "한은 기준금리",
        "원화 채권", "원화채권",
    ),
    "해외채권": (
        "해외채권", "해외 채권", "미국채", "미국 국채", "미 국채",
        "UST", "Treasury", "장기금리", "10Y", "10년물",
        "Fed", "연준", "FOMC",
    ),
    "환율": (
        "원달러", "원·달러", "달러원", "달러/원", "USDKRW",
        "환율", "원화 환율", "원화 약세", "원화 강세",
        "달러 강세", "달러 약세", "달러 인덱스", "달러인덱스",
        "DXY", "위안 환율", "엔화 환율",
    ),
    "금/대체": (
        "금 가격", "금값", "국제 금", "국제금", "금 선물", "금 현물",
        "KRX 금", "골드 가격", "금시세", "금 시세", "금ETF",
        "GLD", "XAU", "bullion", "precious metal", "gold price",
        "리츠", "REIT", "REITs", "원자재", "구리 가격", "옥수수 가격",
        "유가", "원유", "WTI", "브렌트", "Brent", "에너지 가격",
    ),
    "크레딧": (
        "하이일드", "high yield", "HY 스프레드", "HY 채권",
        "credit spread", "신용스프레드", "신용 스프레드",
        "회사채", "회사채 스프레드", "investment grade", "IG 스프레드",
        "CDS", "회사채 발행",
    ),
    "현금성": (
        "MMF", "단기금리", "콜금리", "RP 금리", "CD 금리",
        "현금성 자산", "단기 금리", "초단기",
    ),
}

# 영문 키워드 (word boundary 매칭) — 위 dict 와 분리해 별도 처리
_ENGLISH_INCLUDE: dict[str, tuple[str, ...]] = {
    "해외주식": ("Nasdaq",),
    "해외채권": ("Treasury", "Fed", "FOMC", "UST"),
    "환율": ("FX", "DXY", "USDKRW"),
    "금/대체": ("GLD", "XAU", "WTI", "Brent", "REIT", "REITs", "bullion"),
    "크레딧": ("HY", "CDS"),
    "현금성": ("MMF",),
}

# Exclude keyword — 한국어 substring 으로 잡혔을 때 강제 차감
_KOREAN_EXCLUDE: dict[str, tuple[str, ...]] = {
    "금/대체": (
        "Goldman", "골드만", "Goldman Sachs",
        "금리", "금융", "금요일", "금투", "예금", "자금",
        "기준금리", "현금", "벌금", "장기금", "단기금",
    ),
    "크레딧": (
        "신용카드", "credit card", "신용 카드",
    ),
    "환율": (
        "dollar store", "Eurodollar",
    ),
    "해외주식": (
        # "미국" 단독 매칭 회피용 — include 에 "미국" 단독 키워드 자체를 두지 않음
    ),
    "현금성": (
        "현금영수증",
    ),
}


def _norm(s: str) -> str:
    return (s or "").lower()


def _english_word_count(text: str, word: str) -> int:
    if not text or not word:
        return 0
    pattern = r"\b" + re.escape(word) + r"\b"
    return len(re.findall(pattern, text, flags=re.IGNORECASE))


def _korean_count(text: str, phrase: str) -> int:
    if not text or not phrase:
        return 0
    return _norm(text).count(_norm(phrase))


def _scan_text_for_asset(text: str, asset_class: str) -> int:
    """자산군 키워드가 text 에 등장하는 횟수.

    P3-3.1: include count - exclude count. 음수면 0.
    영문은 word-boundary, 한글은 phrase substring.
    """
    if not text:
        return 0
    body = text  # case 처리는 _norm 내부에서
    hit = 0
    for kw in _KOREAN_INCLUDE.get(asset_class, ()):
        # 영문 phrase (S&P500, GLD, Treasury 등) 가 _KOREAN_INCLUDE 에 섞여 있을 수도 있음.
        # 영문/숫자/구두점만 있는 키워드는 word-boundary 로, 그 외는 substring 으로.
        if re.fullmatch(r"[A-Za-z0-9&./\-+]+", kw):
            hit += _english_word_count(body, kw)
        else:
            hit += _korean_count(body, kw)
    for kw in _ENGLISH_INCLUDE.get(asset_class, ()):
        hit += _english_word_count(body, kw)
    # exclude 차감
    excl = 0
    for kw in _KOREAN_EXCLUDE.get(asset_class, ()):
        if re.fullmatch(r"[A-Za-z0-9&./\-+ ]+", kw):
            excl += _english_word_count(body, kw)
        else:
            excl += _korean_count(body, kw)
    return max(0, hit - excl)


# ─────────────────────────────────────────────────────────────────────
# Topic group (cluster) 매핑 — dominant_topic_group share 산출
# ─────────────────────────────────────────────────────────────────────
TOPIC_GROUPS: dict[str, tuple[str, ...]] = {
    "중동/지정학/에너지": (
        "지정학", "지정학_리스크", "에너지", "에너지_원자재",
        "유가", "원유", "전쟁", "이란", "호르무즈", "중동",
    ),
    "금리/인플레이션": (
        "금리", "금리_채권", "물가", "물가_인플레이션", "인플레이션",
        "연준", "Fed", "중앙은행", "통화정책",
    ),
    "주식/기술주": (
        "빅테크", "AI", "반도체", "나스닥", "테크_AI_반도체",
        "성장주", "S&P500",
    ),
    "환율/달러": (
        "환율", "환율_FX", "달러", "FX", "달러_글로벌유동성",
    ),
    "크레딧": (
        "HY", "하이일드", "회사채", "신용스프레드", "유동성_크레딧",
    ),
    "귀금속/대체": (
        "귀금속_금", "금값", "금 가격", "리츠", "REIT",
    ),
    "국내주식": (
        "KOSPI", "코스피", "한국증시", "삼성전자",
    ),
}


def _topic_to_groups(topic: str) -> list[str]:
    body = _norm(topic)
    matched: list[str] = []
    for grp, kws in TOPIC_GROUPS.items():
        for kw in kws:
            if _norm(kw) in body:
                matched.append(grp)
                break
    return matched


# ─────────────────────────────────────────────────────────────────────
# Topic → asset 매핑 (classifier topic 명을 자산군 list 로 매핑)
# ─────────────────────────────────────────────────────────────────────

def _topic_to_asset_classes(topic: str) -> list[str]:
    """뉴스 classifier topic 명을 자산군 list 로 매핑 (substring + exclude)."""
    matched: list[str] = []
    for ac in REQUIRED_ASSET_CLASSES:
        if _scan_text_for_asset(topic, ac) > 0:
            matched.append(ac)
    return matched


# ─────────────────────────────────────────────────────────────────────
# Signal extraction
# ─────────────────────────────────────────────────────────────────────

def _evidence_count_per_asset(news_articles: list[dict]) -> Counter:
    """primary 뉴스 기사들의 _classified_topics 를 자산군으로 매핑해 카운트.

    한 기사당 자산군 별 1회만 카운트 (set dedupe).
    """
    cnt: Counter = Counter()
    for art in news_articles or []:
        topics = art.get("_classified_topics") or []
        seen: set[str] = set()
        for t in topics:
            if isinstance(t, dict):
                tname = t.get("topic") or ""
            else:
                tname = str(t)
            for ac in _topic_to_asset_classes(tname):
                if ac not in seen:
                    cnt[ac] += 1
                    seen.add(ac)
    return cnt


def _selected_evidence_count_per_asset(selected_evidence: list[dict] | None) -> Counter:
    """debate 가 실제 선정한 evidence 의 자산군 매핑 (primary 와 별도, 더 강한 신호).

    `selected_evidence` 항목이 dict 이고 'topic'/'all_topics' 또는 'title' 을
    가질 때 자산군 키워드로 카운트.
    """
    cnt: Counter = Counter()
    for it in selected_evidence or []:
        if not isinstance(it, dict):
            continue
        text = " ".join([
            str(it.get("title") or ""),
            str(it.get("topic") or ""),
            " ".join(str(t) for t in (it.get("all_topics") or [])),
        ])
        for ac in REQUIRED_ASSET_CLASSES:
            if _scan_text_for_asset(text, ac) > 0:
                cnt[ac] += 1
    return cnt


def _graph_path_count_per_asset(graph_paths: list[dict]) -> Counter:
    cnt: Counter = Counter()
    for p in graph_paths or []:
        labels = p.get("labels") or p.get("path_labels") or p.get("path") or []
        target = p.get("target") or ""
        scan = " ".join([str(x) for x in labels] + [str(target)])
        for ac in REQUIRED_ASSET_CLASSES:
            if _scan_text_for_asset(scan, ac) > 0:
                cnt[ac] += 1
    return cnt


def _wiki_page_count_per_asset(wiki_selected_pages: list[str]) -> Counter:
    cnt: Counter = Counter()
    for p in wiki_selected_pages or []:
        for ac in REQUIRED_ASSET_CLASSES:
            if _scan_text_for_asset(p, ac) > 0:
                cnt[ac] += 1
    return cnt


def _timeseries_signal(narrative_text: str, asset_class: str) -> bool:
    return _scan_text_for_asset(narrative_text or "", asset_class) > 0


def _return_signal(asset_returns: dict[str, float] | None, asset_class: str) -> bool:
    if not asset_returns:
        return False
    for k, v in asset_returns.items():
        if v is None:
            continue
        if asset_class in k or _scan_text_for_asset(k, asset_class) > 0:
            try:
                if float(v) != 0.0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _evidence_bucket(count: int) -> str:
    """raw evidence_count → bucket. prompt 노출용 (raw count 미공개)."""
    if count <= 0:
        return "none"
    if count < 5:
        return "low"
    if count < 25:
        return "medium"
    return "high"


# ─────────────────────────────────────────────────────────────────────
# Coverage status — P3-3.1 강화: raw evidence 단독 covered 금지
# ─────────────────────────────────────────────────────────────────────

def _classify_status(
    *,
    selected_n: int,
    classified_n: int,
    graph_n: int,
    wiki_n: int,
    has_ts: bool,
    has_ret: bool,
) -> tuple[str, list[str]]:
    """coverage status + present_signals 반환.

    규칙:
      - 'classified_only' 단독은 weak (raw 광범위 매칭은 약한 신호).
      - selected_evidence 또는 graph/ts/ret 가 함께 존재하면 강함.
      - covered: 강한 신호 ≥ 2 (selected/graph/ts/ret 중에서)
                 또는 selected≥1 + classified≥1
      - weak  : 강한 신호 1 / classified 단독
      - missing: 모든 신호 부재
    """
    strong = sum([
        1 if selected_n > 0 else 0,
        1 if graph_n > 0 else 0,
        1 if has_ts else 0,
        1 if has_ret else 0,
    ])
    weak_only = (classified_n > 0 and strong == 0 and wiki_n == 0)

    present: list[str] = []
    if selected_n > 0:
        present.append("evidence_selected")
    elif classified_n > 0:
        present.append("evidence_classified")
    if graph_n > 0:
        present.append("graph")
    if wiki_n > 0:
        present.append("wiki")
    if has_ts:
        present.append("timeseries")
    if has_ret:
        present.append("return")

    if strong >= 2:
        return "covered", present
    if strong == 1 and selected_n > 0:
        return "covered", present
    if strong == 1 or wiki_n > 0 or weak_only:
        return "weak", present
    return "missing", present


def _pick_fallback_label(
    *,
    selected_n: int,
    classified_n: int,
    graph_n: int,
    wiki_n: int,
    has_ts: bool,
    has_ret: bool,
) -> str:
    if selected_n > 0:
        return "evidence_selected"
    if classified_n > 0 and (graph_n > 0 or has_ts or has_ret or wiki_n > 0):
        return "evidence_classified"
    if graph_n > 0:
        return "graph"
    if wiki_n > 0:
        return "wiki"
    if has_ts:
        return "timeseries"
    if has_ret:
        return "return"
    if classified_n > 0:
        return "evidence_classified"
    return "no_material_event"


def _summary_phrase(
    asset: str,
    *,
    ev_bucket: str,
    selected_n: int,
    graph_n: int,
    wiki_n: int,
    ts: bool,
    ret_signal: bool,
    status: str,
) -> str:
    """prompt 에 들어갈 한국어 한 줄 요약 (raw count 미노출)."""
    # signal flag 표기 — raw 숫자 미노출, 카테고리/Y/N
    ev_flag = "Y(선정)" if selected_n > 0 else (
        f"Y({ev_bucket})" if ev_bucket != "none" else "N"
    )
    g_flag = "Y" if graph_n > 0 else "N"
    w_flag = "Y" if wiki_n > 0 else "N"
    t_flag = "Y" if ts else "N"
    r_flag = "Y" if ret_signal else "N"
    sig = (
        f"evidence={ev_flag}, graph={g_flag}, wiki={w_flag}, "
        f"ts={t_flag}, ret={r_flag}"
    )
    if status == "covered":
        return f"{asset}: 복수 신호 확인 ({sig})"
    if status == "weak":
        return (
            f"{asset}: 일부 신호만 확인 ({sig}). "
            f"단정 표현 자제, '가능성/관찰' 으로 기술. "
            f"키워드 매칭 기반 evidence 는 보조로만 활용."
        )
    return (
        f"{asset}: 직접 신호 부족 — '특이 이벤트 부재 / 영향 제한적 / "
        f"가격 흐름 중심' 으로 짧게만 점검 (억지 인과 금지)."
    )


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

def build_asset_coverage_map(
    *,
    primary_news: list[dict] | None,
    graph_paths: list[dict] | None,
    wiki_selected_pages: list[str] | None,
    timeseries_narrative_text: str | None,
    asset_returns: dict[str, float] | None = None,
    topic_counts: Counter | None = None,
    selected_evidence: list[dict] | None = None,
) -> dict:
    classified = _evidence_count_per_asset(primary_news or [])
    selected = _selected_evidence_count_per_asset(selected_evidence)
    graph_per = _graph_path_count_per_asset(graph_paths or [])
    wiki_per = _wiki_page_count_per_asset(wiki_selected_pages or [])

    rows: list[dict] = []
    covered: list[str] = []
    weak: list[str] = []
    missing: list[str] = []
    fallback_map: dict[str, str] = {}

    for ac in REQUIRED_ASSET_CLASSES:
        sel_n = int(selected.get(ac, 0))
        cls_n = int(classified.get(ac, 0))
        gp_n = int(graph_per.get(ac, 0))
        wk_n = int(wiki_per.get(ac, 0))
        ts = _timeseries_signal(timeseries_narrative_text or "", ac)
        ret = _return_signal(asset_returns, ac)

        status, present = _classify_status(
            selected_n=sel_n, classified_n=cls_n,
            graph_n=gp_n, wiki_n=wk_n, has_ts=ts, has_ret=ret,
        )
        fb = _pick_fallback_label(
            selected_n=sel_n, classified_n=cls_n,
            graph_n=gp_n, wiki_n=wk_n, has_ts=ts, has_ret=ret,
        )
        fallback_label = "none" if status == "covered" else fb

        ev_bucket = _evidence_bucket(cls_n)
        summary_line = _summary_phrase(
            ac,
            ev_bucket=ev_bucket,
            selected_n=sel_n, graph_n=gp_n, wiki_n=wk_n,
            ts=ts, ret_signal=ret, status=status,
        )

        rows.append({
            "asset_class": ac,
            # 내부 (debug trace 노출 OK, prompt 미노출)
            "evidence_count_classified": cls_n,
            "evidence_count_selected": sel_n,
            "evidence_bucket": ev_bucket,
            "graph_path_count": gp_n,
            "wiki_context_count": wk_n,
            "timeseries_signal_present": ts,
            "return_signal_present": ret,
            "present_signals": present,
            "coverage_status": status,
            "fallback_used": fallback_label,
            "summary_line": summary_line,
        })

        if status == "covered":
            covered.append(ac)
        elif status == "weak":
            weak.append(ac)
        else:
            missing.append(ac)
        fallback_map[ac] = fallback_label

    # dominant topic / dominant topic group
    dom_topic = None
    dom_share = 0.0
    dom_group = None
    dom_group_share = 0.0

    if topic_counts:
        total = sum(topic_counts.values())
        if total > 0:
            top, n = topic_counts.most_common(1)[0]
            dom_topic = top
            dom_share = round(n / total, 3)
            # topic group 집계
            group_cnt: Counter = Counter()
            for tname, c in topic_counts.items():
                groups = _topic_to_groups(str(tname))
                for g in groups:
                    group_cnt[g] += c
            if group_cnt:
                gtop, gn = group_cnt.most_common(1)[0]
                dom_group = gtop
                dom_group_share = round(gn / total, 3)

    return {
        "asset_coverage_map": rows,
        "covered_asset_classes": covered,
        "weak_asset_classes": weak,
        "missing_asset_classes": missing,
        "fallback_used_by_asset": fallback_map,
        "dominant_topic": dom_topic,
        "dominant_topic_share": dom_share,
        "dominant_topic_group": dom_group,
        "dominant_topic_group_share": dom_group_share,
    }


def format_asset_coverage_for_prompt(coverage: dict) -> str:
    if not coverage:
        return ""
    rows = coverage.get("asset_coverage_map") or []
    if not rows:
        return ""
    lines = [
        "## 자산군별 필수 점검 (P3-3 guardrail)",
        "특정 이슈가 시장을 지배하더라도, 아래 자산군별 영향을 최소 한 번씩 점검하세요. "
        "근거가 부족한 자산군은 영향이 제한적이거나 관찰 필요하다고 표현하고, "
        "근거 없는 인과관계를 만들지 마세요. "
        "evidence 신호는 키워드 기반 매칭으로 false-positive 가 있을 수 있으니, "
        "graph/timeseries/return 과 결합된 신호를 우선 신뢰하세요.",
    ]
    for row in rows:
        lines.append(f"- {row.get('summary_line', '')}")

    dom = coverage.get("dominant_topic")
    share = coverage.get("dominant_topic_share") or 0.0
    grp = coverage.get("dominant_topic_group")
    grp_share = coverage.get("dominant_topic_group_share") or 0.0
    if dom or grp:
        ref = []
        if dom:
            ref.append(f"dominant topic = `{dom}` (share={share:.2f})")
        if grp and grp_share > share:
            ref.append(f"dominant topic group = `{grp}` (share={grp_share:.2f})")
        lines.append(
            f"\n(참고: {' · '.join(ref)}. 이 이슈에 과도하게 편중되지 않도록 "
            f"위 자산군별 점검을 활용하세요.)"
        )
    return "\n".join(lines)


__all__ = [
    "REQUIRED_ASSET_CLASSES",
    "TOPIC_GROUPS",
    "build_asset_coverage_map",
    "format_asset_coverage_for_prompt",
]
