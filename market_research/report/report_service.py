# -*- coding: utf-8 -*-
"""Service orchestration for the report tab.

This module keeps report-specific data gathering, factor extraction, and LLM
orchestration out of the Streamlit UI layer.
"""

import json
import os
import sys
import importlib.util
from pathlib import Path

import anthropic

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

if sys.stdout and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_news_vectordb = None


def _load_module(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _get_news_vectordb_module():
    global _news_vectordb
    if _news_vectordb is not None:
        return _news_vectordb

    try:
        from market_research import news_vectordb as module  # noqa: E402
    except ModuleNotFoundError:
        module = _load_module(
            "market_research.news_vectordb_fallback",
            BASE_DIR / "news_vectordb.py",
        )

    _news_vectordb = module
    return _news_vectordb


try:
    from market_research.report.comment_engine import (  # noqa: E402
        ANTHROPIC_API_KEY,
        FUND_CONFIGS,
        _build_llm_prompt,
        load_all_pa_attributions,
        load_benchmark_returns,
        load_digest,
        load_fund_holdings_summary,
        load_fund_return,
        load_pa_by_item,
    )
except ModuleNotFoundError:
    _comment_engine = _load_module(
        "market_research.comment_engine_fallback",
        BASE_DIR / "comment_engine.py",
    )

    ANTHROPIC_API_KEY = _comment_engine.ANTHROPIC_API_KEY
    FUND_CONFIGS = _comment_engine.FUND_CONFIGS
    _build_llm_prompt = _comment_engine._build_llm_prompt
    load_all_pa_attributions = _comment_engine.load_all_pa_attributions
    load_benchmark_returns = _comment_engine.load_benchmark_returns
    load_digest = _comment_engine.load_digest
    load_fund_holdings_summary = _comment_engine.load_fund_holdings_summary
    load_fund_return = _comment_engine.load_fund_return
    load_pa_by_item = _comment_engine.load_pa_by_item


TOPIC_ASSET_MAP = {
    "AI_반도체": ["해외주식", "국내주식"],
    "금리": ["국내채권", "해외채권"],
    "달러": ["해외주식", "대체투자"],
    "국내_통화": ["국내주식"],
    "유가_에너지": ["대체투자"],
    "금": ["대체투자"],
    "관세": ["해외주식", "국내주식"],
    "물가": ["국내채권", "해외채권"],
    "미국채": ["해외채권"],
    "엔화_캐리": ["해외주식"],
    "중국_정책": ["해외주식"],
    "유럽_ECB": ["해외채권", "해외주식"],
    "크레딧": ["해외채권"],
    "부동산": ["대체투자"],
    "안전자산": ["해외채권", "대체투자"],
}

REPORT_ASSET_CLASSES = ["국내주식", "해외주식", "국내채권", "해외채권", "대체투자"]

ASSET_CLASS_ALIASES = {
    "국내주식": ["국내주식"],
    "해외주식": ["해외주식"],
    "국내채권": ["국내채권"],
    "해외채권": ["해외채권"],
    "대체투자": ["대체투자", "대체", "원자재"],
}


def _get_asset_value(mapping, asset_class):
    aliases = ASSET_CLASS_ALIASES.get(asset_class, [asset_class])
    return sum(mapping.get(alias, 0.0) for alias in aliases)


def _search_news_vectordb(month_str, asset_class, contrib, top_k=5):
    """Search the current month first, then fall forward one month if sparse."""
    news_vectordb = _get_news_vectordb_module()
    search_for_factors = news_vectordb.search_for_factors
    _get_collection = news_vectordb._get_collection
    results = search_for_factors(month_str, asset_class, contrib, top_k=top_k)

    if len(results) < 3:
        year, month = int(month_str[:4]), int(month_str[5:7])
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        next_month_str = f"{next_year}-{next_month:02d}"
        next_collection = _get_collection(next_month_str)
        if next_collection.count() > 0:
            extra = search_for_factors(next_month_str, asset_class, contrib, top_k=top_k)
            seen = set(item["title"][:40] for item in results)
            for item in extra:
                prefix = item["title"][:40]
                if prefix in seen:
                    continue
                results.append(item)
                seen.add(prefix)
                if len(results) >= top_k:
                    break

    return results


def _extract_blog_factors(digest, asset_class, global_seen):
    """Extract asset-class-relevant points from the monthly digest."""
    if not digest:
        return []

    raw = []
    for topic, mapped_assets in TOPIC_ASSET_MAP.items():
        if asset_class not in mapped_assets:
            continue
        info = digest.get("topics", {}).get(topic)
        if not info:
            continue
        # 우선순위: claims(인과분석) > data_points(수치+맥락) > events(사실)
        sources = (
            info.get("key_claims", [])
            + info.get("data_points", [])[:5]
            + info.get("key_events", [])[:3]
        )
        for item in sources:
            if not (20 < len(item) < 200):
                continue
            if any(bad in item for bad in ["요", "듯", "월", "종", "|게시", "여러분", "드립니다"]):
                continue
            normalized = item[:10].replace("/", "").replace(" ", "").replace(":", "")
            if len(item) < 25 and normalized.isdigit():
                continue
            if item.endswith("?"):
                continue
            raw.append((item, topic))

    deduped = []
    for item, _topic in raw:
        keywords = set(word for word in item.split() if len(word) >= 3)
        if keywords:
            overlap = len(keywords & global_seen) / max(len(keywords), 1)
            if overlap > 0.4:
                continue
        global_seen.update(keywords)
        deduped.append(item)
        if len(deduped) >= 12:
            break

    if not deduped:
        return []

    try:
        _api_key = os.getenv("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY
        client = anthropic.Anthropic(api_key=_api_key)
        factor_list = "\n".join(f"{i + 1}. {factor}" for i, factor in enumerate(deduped))
        prompt = f"""다음 문장들이 "{asset_class}" 자산군의 월간 수익률 원인을 설명하는 요인인지 판단하세요.

후보:
{factor_list}

각 문장에 대해
- 1 = 해당 자산군이 왜 올랐는지/내렸는지 원인을 설명하는 요인 (인과관계, 수치 포함 우대)
- 0 = 단순 결과 서술, 다른 자산군 얘기, 블로그 감상/비유/광고, 또는 운용보고서에 부적절

JSON 배열만 응답하세요. 길이는 {len(deduped)}개여야 합니다."""
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            flags = json.loads(text[start:end])
            if len(flags) == len(deduped):
                return [factor for factor, flag in zip(deduped, flags) if flag == 1][:6]
    except Exception:
        pass

    return deduped[:6]


def _load_macro_indicators():
    """indicators.json에서 최근 2개 값 로드 → {key: (latest, prev, desc)} dict."""
    indicators_file = BASE_DIR / "data" / "macro" / "indicators.json"
    if not indicators_file.exists():
        return {}
    try:
        with open(indicators_file, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    result = {}
    for source_key in ("fred", "scip", "ecos", "nyfed"):
        source = raw.get(source_key, {})
        if not isinstance(source, dict):
            continue
        for key, meta in source.items():
            if not isinstance(meta, dict):
                continue
            series = meta.get("data", {})
            if not isinstance(series, dict) or len(series) < 2:
                continue
            dates = sorted(series.keys())
            latest = series[dates[-1]]
            prev = series[dates[-2]]
            if latest is not None and prev is not None:
                try:
                    result[key] = (float(latest), float(prev), meta.get("desc", ""))
                except (TypeError, ValueError):
                    continue
    return result


_macro_cache = {}


def _get_macro():
    """매크로 지표 캐시 (세션 내 1회 로드)."""
    if not _macro_cache:
        _macro_cache.update(_load_macro_indicators())
    return _macro_cache


def _extract_indicator_factors(bm_returns, asset_class):
    """Build lightweight factor candidates from benchmark + macro indicators."""
    factors = []
    dxy = bm_returns.get("DXY", {}).get("return")
    gold = bm_returns.get("Gold", {}).get("return")
    wti = bm_returns.get("WTI", {}).get("return")
    usdkrw = bm_returns.get("USDKRW", {}).get("return")
    growth = bm_returns.get("미국성장주", {}).get("return")
    value = bm_returns.get("미국가치주", {}).get("return")
    sp500 = bm_returns.get("S&P500", {}).get("return")
    kospi = bm_returns.get("KOSPI", {}).get("return")
    us_bond = bm_returns.get("미국종합채권", {}).get("return")
    kr_bond = bm_returns.get("매경채권국채3년", {}).get("return")
    em = bm_returns.get("신흥국주식", {}).get("return")
    dm_exus = bm_returns.get("미국외선진국", {}).get("return")

    # ── 매크로 지표 ──
    macro = _get_macro()

    def _m(key):
        """(latest, prev, change) or None."""
        t = macro.get(key)
        if t is None:
            return None
        latest, prev, _ = t
        return latest, prev, latest - prev

    # ── 공통 매크로 팩터 (전 자산군 공유) ──
    # VIX
    vix = _m("VIX")
    if vix and vix[0] > 25:
        factors.append(f"VIX {vix[0]:.1f} (변동성 경계 구간, 전월대비 {vix[2]:+.1f})")

    # 실업률
    unrate = _m("UNRATE")
    if unrate and abs(unrate[2]) >= 0.2:
        direction = "상승" if unrate[2] > 0 else "하락"
        factors.append(f"미국 실업률 {unrate[0]:.1f}% ({direction} {abs(unrate[2]):.1f}%p)")

    # 미시간 소비자심리
    umcsent = _m("UMCSENT")
    if umcsent and (umcsent[0] < 60 or abs(umcsent[2]) > 5):
        factors.append(f"소비자심리 {umcsent[0]:.1f} (전월 {umcsent[1]:.1f}, {umcsent[2]:+.1f})")

    # GDPNow
    gdpnow = _m("GDPNOW")
    if gdpnow and abs(gdpnow[2]) > 0.5:
        factors.append(f"Atlanta Fed GDPNow {gdpnow[0]:.1f}% (전월 {gdpnow[1]:.1f}%)")

    # BEI (10Y 기대인플레이션)
    bei10 = _m("T10YIE")
    if bei10 and abs(bei10[2]) > 0.1:
        factors.append(f"10Y BEI {bei10[0]:.2f}% ({bei10[2]:+.2f}%p)")

    # ── 자산군별 벤치마크 + 매크로 규칙 ──
    if asset_class == "해외주식":
        if dxy and abs(dxy) > 0.3:
            factors.append(f"달러 {'강세' if dxy > 0 else '약세'} DXY {dxy:+.1f}%")
        if growth and value and abs(growth - value) > 1:
            factors.append(f"성장주({growth:+.1f}%) vs 가치주({value:+.1f}%) 스타일 차별화")
        if em and sp500 and em > sp500 + 2:
            factors.append(f"신흥국 상대 강세 EM {em:+.1f}% vs S&P {sp500:+.1f}%")
        if dm_exus and sp500 and dm_exus > sp500 + 2:
            factors.append(f"선진국 ex-US 상대 강세 {dm_exus:+.1f}%")
        # 비농업 고용 변화
        payems = _m("PAYEMS")
        if payems and abs(payems[2]) > 100:
            direction = "증가" if payems[2] > 0 else "감소"
            factors.append(f"비농업 고용 {payems[2]:+,.0f}천명 {direction}")
    elif asset_class == "국내주식":
        if kospi and abs(kospi) > 2:
            factors.append(f"KOSPI {'강세' if kospi > 0 else '약세'} {kospi:+.1f}%")
        if usdkrw and abs(usdkrw) > 1:
            factors.append(f"원화 {'약세' if usdkrw > 0 else '강세'} USD/KRW {usdkrw:+.1f}%")
    elif asset_class == "국내채권":
        if kr_bond and abs(kr_bond) > 0.1:
            factors.append(f"국내 채권지수 {kr_bond:+.2f}%")
    elif asset_class == "해외채권":
        if us_bond and abs(us_bond) > 0.3:
            factors.append(f"미국 종합채권 {us_bond:+.2f}%")
        # 크레딧 스프레드
        hy_oas = _m("US_HY_OAS")
        if hy_oas and abs(hy_oas[2]) > 0.2:
            factors.append(f"US HY OAS {hy_oas[0]:.0f}bp ({hy_oas[2]:+.0f}bp)")
        ig_oas = _m("US_IG_OAS")
        if ig_oas and abs(ig_oas[2]) > 0.1:
            factors.append(f"US IG OAS {ig_oas[0]:.0f}bp ({ig_oas[2]:+.0f}bp)")
        # 미국채 10년 금리
        dgs10 = _m("DGS10")
        if dgs10 and abs(dgs10[2]) > 0.15:
            factors.append(f"미국채 10Y {dgs10[0]:.2f}% ({dgs10[2]:+.2f}%p)")
    elif asset_class == "대체투자":
        if gold and abs(gold) > 0.5:
            factors.append(f"금 {gold:+.1f}%")
        if wti and abs(wti) > 1:
            factors.append(f"WTI {wti:+.1f}%")
        if dxy and gold and dxy > 0.3 and gold < -0.3:
            factors.append(f"달러 강세({dxy:+.1f}%)에 따른 대체자산 약세")

    return factors


def _llm_summarize_factors(asset_class, contrib, raw_factors, bm_returns, cross_themes=None):
    """Summarize raw factors into causal report-ready candidates."""
    if not raw_factors:
        return []

    try:
        _api_key = os.getenv("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY
        client = anthropic.Anthropic(api_key=_api_key)
        bm_parts = []
        for name in [
            "S&P500",
            "미국성장주",
            "미국가치주",
            "KOSPI",
            "DXY",
            "USDKRW",
            "매경채권국채3년",
            "미국종합채권",
            "Gold",
            "WTI",
        ]:
            value = bm_returns.get(name, {}).get("return")
            if value is not None:
                bm_parts.append(f"{name}:{value:+.1f}%")

        theme_text = f'매크로 배경 테마: {", ".join(cross_themes[:5])}' if cross_themes else ''
        factor_list = "\n".join(f"- {factor}" for factor in raw_factors)
        prompt = f"""당신은 운용보고서용 팩터 분석가입니다.

자산군: {asset_class}
월간 기여도: {contrib:+.2f}%
벤치마크: {", ".join(bm_parts)}
{theme_text}

아래는 블로그, 뉴스, 지표에서 수집한 raw 팩터입니다.
{factor_list}

규칙:
1. 비슷한 내용을 합치고 중복을 제거해서 "{asset_class}" 수익률의 핵심 원인을 최대 4개로 요약하세요.
2. 각 팩터는 "원인 → 결과" 구조로 작성하세요. 예: "관세 불확실성과 외국인 매도세 → KOSPI -18.8% 급락"
3. 각 팩터는 60~120자로, 왜 그런 결과가 나왔는지 원인을 반드시 포함하세요.
4. 가능하면 구체적 수치(%, bp, 달러 등)를 포함하세요.
5. raw 팩터 근거가 없는 내용은 만들지 마세요.
6. "{asset_class}"와 직접 관계없는 팩터는 제외하세요.
7. 근거가 부족하면 빈 배열 []를 반환하세요.
8. 직접 설명력은 8~10, 배경 설명은 5~7점으로 scoring 하세요.

JSON만 응답하세요: [{{"text": "...", "score": N}}, ...]"""
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # 마크다운 코드블록 제거
        if text.startswith('```'):
            text = text.split('\n', 1)[-1]
            if text.endswith('```'):
                text = text[:-3].strip()
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            items = json.loads(text[start:end])
            if isinstance(items, list):
                return items[:4]
    except Exception as exc:
        debug_log = OUTPUT_DIR / "debug_haiku.log"
        debug_log.write_text(str(exc), encoding="utf-8")

    return []


MACRO_THEME_GROUPS = {
    '주식시장': ['AI_반도체', '관세', '한국_원화'],
    '채권/금리': ['금리', '미국채', '물가'],
    '통화': ['달러', '엔화_캐리', '중국_위안화', '유로달러'],
    '대체/원자재': ['유가_에너지', '금', '안전자산'],
    '기타 매크로': ['이민_노동', '유럽_ECB', '부동산'],
}


def _build_macro_factor_data(digest, bm_returns, month_str, debug=None):
    """매크로 오버뷰용 factor_data — 테마 그룹별 구성"""
    factor_data_macro = {}

    if not digest:
        return factor_data_macro

    for group_name, topics in MACRO_THEME_GROUPS.items():
        group_claims = []
        group_events = []
        group_direction = None
        total_posts = 0

        for topic in topics:
            info = digest.get('topics', {}).get(topic)
            if not info:
                continue
            total_posts += info.get('post_count', 0)
            group_claims.extend(info.get('key_claims', [])[:3])
            group_events.extend(info.get('key_events', [])[:2])
            if group_direction is None:
                group_direction = info.get('direction', '')

        if not group_claims and not group_events:
            continue

        # 중복 제거
        seen = set()
        items = []
        for text in (group_claims + group_events):
            if not (15 < len(text) < 120):
                continue
            prefix = text[:30]
            if prefix in seen:
                continue
            seen.add(prefix)
            items.append({
                'text': text,
                'score': 7,
                'starred': '보조',
                'source': '블로그',
                'recommended': True,
            })
            if len(items) >= 6:
                break

        # 관련 벤치마크 지표 추가
        indicator_items = _extract_macro_indicators(group_name, bm_returns)
        for ind in indicator_items:
            items.append({
                'text': ind,
                'score': 8,
                'starred': '추천',
                'source': '지표',
                'recommended': True,
            })

        factor_data_macro[group_name] = {
            'contrib': 0.0,  # 매크로는 기여도 없음
            'weight': 0.0,
            'direction': group_direction or '',
            'post_count': total_posts,
            'items': items,
            'has_source': len(items) > 0,
        }

        if debug:
            debug.write(f'[macro:{group_name}] {len(items)} items, {total_posts} posts\n')

    return factor_data_macro


def _extract_macro_indicators(group_name, bm_returns):
    """매크로 그룹별 관련 벤치마크 지표 텍스트 생성"""
    indicators = []

    def _fmt(name):
        ret = bm_returns.get(name, {}).get('return')
        return f'{name} {ret:+.1f}%' if ret is not None else None

    if group_name == '주식시장':
        for name in ['S&P500', 'KOSPI', '미국성장주', '신흥국주식']:
            t = _fmt(name)
            if t:
                indicators.append(t)
    elif group_name == '채권/금리':
        for name in ['미국종합채권', '매경채권국채3년', '미국HY']:
            t = _fmt(name)
            if t:
                indicators.append(t)
    elif group_name == '통화':
        for name in ['DXY', 'USDKRW', 'JPYUSD', 'EURUSD']:
            t = _fmt(name)
            if t:
                indicators.append(t)
    elif group_name == '대체/원자재':
        for name in ['Gold', 'WTI', '미국리츠']:
            t = _fmt(name)
            if t:
                indicators.append(t)

    return indicators[:3]


def _build_news_factors(month_str, asset_class, contrib, blog_factors, indicator_factors):
    """뉴스 벡터검색 → description 포함 팩터 반환."""
    news_factors = []
    try:
        news_results = _search_news_vectordb(month_str, asset_class, contrib, top_k=5)
        seen_titles = set()
        for result in news_results:
            title = result["title"]
            if any(title[:30] in f for f in blog_factors + indicator_factors):
                continue
            prefix = title[:40]
            if prefix in seen_titles:
                continue
            seen_titles.add(prefix)
            text = result.get("text", title)
            source = result.get("source", "")
            news_factors.append(f"{text} ({source})")
            if len(news_factors) >= 4:
                break
    except Exception:
        pass
    return news_factors


def build_factor_data(pa_dict, holdings, bm, digest, month_str):
    """자산군별 팩터 생성 — batch와 live 공용."""
    global_seen = set()
    factor_data = {}
    cross_themes = digest.get("cross_themes", []) if digest else []

    for asset_class in REPORT_ASSET_CLASSES:
        contrib = _get_asset_value(pa_dict, asset_class)
        weight = _get_asset_value(holdings, asset_class)
        if abs(contrib) < 0.01 and weight < 0.1:
            continue

        blog_factors = _extract_blog_factors(digest, asset_class, global_seen)
        indicator_factors = _extract_indicator_factors(bm, asset_class)
        news_factors = _build_news_factors(month_str, asset_class, contrib, blog_factors, indicator_factors)

        all_factors = blog_factors + news_factors + indicator_factors
        summarized = _llm_summarize_factors(
            asset_class, contrib, all_factors, bm, cross_themes=cross_themes
        ) if all_factors else []

        items = []
        for item in summarized:
            score = item.get("score", 5)
            items.append({
                "text": item.get("text", ""),
                "score": score,
                "starred": "추천" if score >= 8 else ("보조" if score >= 6 else ""),
                "source": "종합",
                "recommended": score >= 6,
            })

        factor_data[asset_class] = {
            "contrib": contrib,
            "weight": weight,
            "items": items,
            "has_source": len(items) > 0,
        }

    return factor_data


def build_base_prompt_from_context(fund_code, year, month, context):
    """Build the base report prompt from a precomputed context."""
    return _build_llm_prompt(
        fund_code,
        year,
        month,
        context["bm"],
        context["fund_ret"],
        context["pa"],
        context["holdings"],
        context["digest"],
        context["next_digest"],
    )


def analyze_report_context(fund_code, year, month):
    """Load report data and produce selectable factor candidates."""
    log_path = OUTPUT_DIR / "debug_comment.log"
    month_str = f"{year}-{month:02d}"

    with open(log_path, "w", encoding="utf-8") as debug:
        bm = load_benchmark_returns(year, month)
        pa_all = load_all_pa_attributions([fund_code], year, month)
        pa = pa_all.get(fund_code, {})
        fund_ret = load_fund_return(fund_code, year, month)
        holdings = load_fund_holdings_summary(fund_code, year, month)
        digest = load_digest(year, month)
        next_month = 1 if month == 12 else month + 1
        next_year = year + 1 if month == 12 else year
        next_digest = load_digest(next_year, next_month)

        global_seen = set()
        factor_data = {}
        for asset_class in REPORT_ASSET_CLASSES:
            contrib = _get_asset_value(pa, asset_class)
            weight = _get_asset_value(holdings, asset_class)
            if abs(contrib) < 0.01 and weight < 0.1:
                continue

            blog_factors = _extract_blog_factors(digest, asset_class, global_seen)
            indicator_factors = _extract_indicator_factors(bm, asset_class)

            news_factors = []
            try:
                debug.write(
                    f"[{asset_class}] news search start month={month_str}, contrib={contrib:+.2f}\n"
                )
                news_results = _search_news_vectordb(month_str, asset_class, contrib, top_k=5)
                debug.write(f"[{asset_class}] news result count={len(news_results)}\n")
                seen_titles = set()
                for result in news_results:
                    title = result["title"]
                    if any(title[:30] in factor for factor in blog_factors + indicator_factors):
                        continue
                    prefix = title[:40]
                    if prefix in seen_titles:
                        continue
                    seen_titles.add(prefix)
                    source = result.get("source", "")
                    text = result.get("text", title)  # title + description[:200]
                    news_factors.append(f"{text} ({source})")
                    if len(news_factors) >= 4:
                        break
            except Exception as exc:
                debug.write(f"[{asset_class}] news error={exc}\n")

            all_factors = blog_factors + news_factors + indicator_factors
            debug.write(
                f"[{asset_class}] counts blog={len(blog_factors)} news={len(news_factors)} indicator={len(indicator_factors)}\n"
            )
            cross_themes = digest.get("cross_themes", []) if digest else []
            summarized = _llm_summarize_factors(asset_class, contrib, all_factors, bm, cross_themes=cross_themes) if all_factors else []
            items = []
            for item in summarized:
                score = item.get("score", 5)
                items.append(
                    {
                        "text": item.get("text", ""),
                        "score": score,
                        "starred": "추천" if score >= 8 else ("보조" if score >= 6 else ""),
                        "source": "종합",
                        "recommended": score >= 6,
                    }
                )

            factor_data[asset_class] = {
                "contrib": contrib,
                "weight": weight,
                "items": items,
                "has_source": len(items) > 0,
            }

    # ── 매크로용 factor_data 생성 (테마 중심) ──
    factor_data_macro = _build_macro_factor_data(digest, bm, month_str, debug=open(log_path, 'a', encoding='utf-8'))

    context = {
        "bm": bm,
        "pa": pa,
        "pa_items": load_pa_by_item(fund_code, year, month),
        "fund_ret": fund_ret,
        "holdings": holdings,
        "digest": digest,
        "next_digest": next_digest,
        "factor_data": factor_data,          # PA 중심 (기존)
        "factor_data_macro": factor_data_macro,  # 매크로 오버뷰용
        "debug_log": str(log_path),
    }
    try:
        context["base_prompt"] = build_base_prompt_from_context(fund_code, year, month, context)
        context["base_prompt_error"] = None
    except Exception as exc:
        context["base_prompt"] = None
        context["base_prompt_error"] = str(exc)
    return context


def generate_report_from_selections(fund_code, year, month, context, selections):
    """Generate a final report using user-approved factor selections."""
    prompt = _build_llm_prompt(
        fund_code,
        year,
        month,
        context["bm"],
        context["fund_ret"],
        context["pa"],
        context["holdings"],
        context["digest"],
        context["next_digest"],
    )

    selected_text = ""
    for asset_class, texts in selections.items():
        selected_text += f"\n[{asset_class}] 선택된 요인:\n"
        for text in texts:
            selected_text += f"  - {text}\n"

    injection = f"""## {month}월 시장 및 자산군별 선택 요인
{selected_text}
위에서 선택한 요인만 코멘트에 반영하세요. 선택하지 않은 요인은 언급하지 마세요."""

    next_month = 1 if month == 12 else month + 1
    marker = f"## {month}월 시장 이벤트 분석 (블로그기반)"
    next_marker = f"## {next_month}월 전망 텍스트"
    if marker in prompt:
        start = prompt.index(marker)
        end = prompt.index(next_marker) if next_marker in prompt else len(prompt)
        prompt = prompt[:start] + injection + "\n\n" + prompt[end:]

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    result = response.content[0].text
    usage = response.usage
    cost = usage.input_tokens * 15 / 1_000_000 + usage.output_tokens * 75 / 1_000_000

    return {
        "report_text": result,
        "prompt": prompt,
        "token_usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        },
        "token_text": f"{usage.input_tokens} in + {usage.output_tokens} out",
        "cost": cost,
        "selections": selections,
    }
