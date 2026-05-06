"""R1 + R2: Wiki Retrieval / Evidence Coverage Viewer + Gate (CLI).

운영 관측용 read-only 도구. debate / fund_comment prompt 에 어떤 Wiki page 가
왜 들어가는지 markdown report 로 추적 가능하게 하고, 운영 품질 gate 로 회귀
검출.

Use (R1 — report 만):
    python tools/wiki_retrieval_coverage.py
    python tools/wiki_retrieval_coverage.py --period 2026-04 --period 2026-05
    python tools/wiki_retrieval_coverage.py --period 2026-04 --fund 07G04

Use (R2 — gate 모드, fail 시 exit 1):
    python tools/wiki_retrieval_coverage.py --fail-on-gate \
        --period 2026-04 --period 2026-05 \
        --skip-report-period 2026-05

기본:
  --period: 자동 검출 (wiki/01_Events 의 모든 YYYY-MM)
  --fund: 07G04, 08K88
  --output: debug/wiki_retrieval_coverage_{YYYYMMDD}.md

R2 gate 정책 (5+ 조건):
  G1. duplicate primary_url > 0 → FAIL
  G2. duplicate primary_headline > 0 → FAIL
  G3. required asset page missing (active period) → FAIL
      skip-report-period 면 WARNING (skip-policy 적용)
  G4. enrichment expected (해당 period) 인데 source_type=none → FAIL
  G5. pinned/retrieved 동일 fund page 중복 → FAIL
      (skipped_excluded < 1 인데 pinned 가 있으면 dedup 미작동)
  G6. market_debate selected 동일 URL 중복 → FAIL
  G7. fund_comment 04_Funds 페이지 중 target period 와 다른 month leakage → WARNING
      (stale month leakage 검출, R2 신규)

skip period policy:
  --skip-report-period 로 명시된 period 는 운용보고 사이클이 skip 이라도
  Wiki coverage 검증 자체는 수행. G3 가 FAIL → WARNING 으로 강등.
  G1/G2/G4/G5/G6 은 그대로 FAIL (운영 데이터 무결성은 동일하게 요구).

출력 섹션:
  1. period 별 Wiki inventory (page count, dup, source_type, char dist, stale/future)
  2. retrieval debug (stage=market_debate / fund_comment, period, selected with reason)
  3. fund_comment 전용 (pinned/retrieved 분리, 자기 fund / 타 fund 차단)
  4. asset coverage (자산군별 03_Assets 존재 + enrichment 보존)
  5. (--fail-on-gate 시) gate 결과 + summary
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.report.wiki_retriever import (
    retrieve_wiki_context,
    get_pinned_fund_context,
    extract_fund_keywords_from_pinned,
    _extract_frontmatter,
    _extract_cluster_id,
    _page_period,
    _is_future_page,
    _score_page,
    _split_tokens,
    STAGE_ALLOWED_DIRS,
    PERIOD_AGNOSTIC_DIRS,
    DEFAULT_CLUSTER_CAP,
    WIKI_ROOT,
)

NEWS_DIR = PROJECT_ROOT / "market_research" / "data" / "news"
DEBATE_LOGS_DIR = PROJECT_ROOT / "market_research" / "data" / "debate_logs"

REQUIRED_ASSET_CLASSES = (
    "국내주식", "해외주식", "국내채권", "해외채권",
    "환율", "금/대체", "크레딧", "현금성",
)

# 자산군 → 03_Assets 파일명 매핑 (현재 enrichment_builder 가 만드는 파일명)
ASSET_FILENAME_MAP = {
    "국내주식": ["국내주식"],
    "해외주식": ["해외주식"],
    "국내채권": ["국내채권"],
    "해외채권": ["해외채권"],
    "환율": ["환율"],
    "금/대체": ["금_대체", "금"],   # enrichment 는 "금_대체", base 는 "금"
    "크레딧": ["크레딧"],
    "현금성": ["현금성"],
}

URL_RE = re.compile(r"^\*\*URL\*\*:\s*(.+)$", re.MULTILINE)
HEADLINE_RE = re.compile(r"^\*\*Primary headline\*\*:\s*(.+)$", re.MULTILINE)
SOURCE_TYPE_RE = re.compile(r"^source_type:\s*[\"']?([^\"'\n]+)", re.MULTILINE)
GENERATED_BY_RE = re.compile(r"^generated_by:\s*[\"']?([^\"'\n]+)", re.MULTILINE)
TYPE_RE = re.compile(r"^type:\s*[\"']?([^\"'\n]+)", re.MULTILINE)


# ──────────────────────────────────────────────────────────────────
# 1. Wiki inventory
# ──────────────────────────────────────────────────────────────────

def page_meta(fp: Path) -> dict:
    """page 의 메타 단일 dict."""
    try:
        txt = fp.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    fm = _extract_frontmatter(txt)
    body_chars = len(txt) - len(fm) - 8 if fm else len(txt)
    src_type_m = SOURCE_TYPE_RE.search(fm) if fm else None
    gen_by_m = GENERATED_BY_RE.search(fm) if fm else None
    type_m = TYPE_RE.search(fm) if fm else None
    head_m = HEADLINE_RE.search(txt)
    url_m = URL_RE.search(txt)
    return {
        "path": str(fp.relative_to(WIKI_ROOT)).replace("\\", "/"),
        "name": fp.name,
        "dir": fp.parent.name,
        "chars": len(txt),
        "body_chars": body_chars,
        "page_period": _page_period(fp, fm),
        "type": (type_m.group(1).strip() if type_m else None),
        "source_type": (src_type_m.group(1).strip() if src_type_m else None),
        "generated_by": (gen_by_m.group(1).strip() if gen_by_m else None),
        "primary_headline": (head_m.group(1).strip() if head_m else None),
        "primary_url": (url_m.group(1).strip() if url_m else None),
        "cluster_key": _extract_cluster_id(fm),
    }


def all_period_pages(period: str) -> list[dict]:
    """해당 period 의 모든 wiki page 메타 (agnostic 포함)."""
    target = _split_period(period)
    out = []
    for d in (
        "01_Events", "02_Entities", "03_Assets", "04_Funds",
        "05_Regime_Canonical", "00_Index",
    ):
        dp = WIKI_ROOT / d
        if not dp.exists():
            continue
        for fp in sorted(dp.glob("*.md")):
            m = page_meta(fp)
            if not m:
                continue
            # period 매칭 (agnostic dir 은 무조건 포함, 그 외는 page_period 일치)
            if d in PERIOD_AGNOSTIC_DIRS:
                out.append(m)
            elif m["page_period"] == target:
                out.append(m)
    return out


def _split_period(p: str) -> tuple[int, int] | None:
    m = re.match(r"(\d{4})-(\d{2})", p)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def inventory_report(period: str) -> dict:
    """period 별 inventory."""
    pages = all_period_pages(period)
    by_dir = defaultdict(list)
    for p in pages:
        by_dir[p["dir"]].append(p)

    # duplicate URL / headline (01_Events 만)
    events = by_dir.get("01_Events", [])
    url_counts = Counter(p["primary_url"] for p in events if p["primary_url"])
    head_counts = Counter(p["primary_headline"] for p in events if p["primary_headline"])
    dup_urls = {u: n for u, n in url_counts.items() if n > 1}
    dup_heads = {h: n for h, n in head_counts.items() if n > 1}

    # source_type 분포 (모든 dir)
    src_dist = Counter(p["source_type"] or "(none)" for p in pages)

    # 글자 수 분포 (모든 dir, body_chars)
    chars_list = [p["body_chars"] for p in pages]

    # stale (sequential id)/hex (deterministic) — 01_Events 만
    seq_re = re.compile(r"event_\d+\.md$")
    hex_re = re.compile(r"event_[0-9a-f]{10}\.md$")
    seq_n = sum(1 for p in events if seq_re.search(p["name"]))
    hex_n = sum(1 for p in events if hex_re.search(p["name"]))

    # future page (period 보다 미래) — 운영상 0 이어야 정상
    target = _split_period(period)
    future_n = sum(
        1 for p in pages
        if p["page_period"] and target and p["page_period"] > target
    )

    return {
        "period": period,
        "by_dir_counts": {d: len(ps) for d, ps in by_dir.items()},
        "total_pages": len(pages),
        "duplicate_url_groups": dup_urls,
        "duplicate_headline_groups": dup_heads,
        "source_type_distribution": dict(src_dist),
        "chars_min": min(chars_list) if chars_list else 0,
        "chars_max": max(chars_list) if chars_list else 0,
        "chars_avg": int(sum(chars_list) / len(chars_list)) if chars_list else 0,
        "events_with_sequential_id": seq_n,
        "events_with_hex_id": hex_n,
        "future_pages": future_n,
    }


# ──────────────────────────────────────────────────────────────────
# 2. Retrieval debug
# ──────────────────────────────────────────────────────────────────

def _load_keywords(period: str) -> list[str]:
    """debate_logs 의 키워드, 없으면 articles 의 top topics."""
    log_fp = DEBATE_LOGS_DIR / f"{period}.json"
    if log_fp.exists():
        try:
            log = json.loads(log_fp.read_text(encoding="utf-8"))
            res = log.get("result") if isinstance(log, dict) and "result" in log else log
            if isinstance(res, dict):
                kws = (res.get("_debug_trace", {}) or {}).get("wiki_retrieval_keywords")
                if kws:
                    return kws
        except Exception:
            pass
    # fallback — articles top topics
    news_fp = NEWS_DIR / f"{period}.json"
    if news_fp.exists():
        try:
            arts = json.loads(news_fp.read_text(encoding="utf-8")).get("articles", [])
            tc = Counter()
            for a in arts:
                for t in a.get("_classified_topics", []):
                    if isinstance(t, dict) and t.get("topic"):
                        tc[t["topic"]] += 1
            return [t for t, _ in tc.most_common(15)]
        except Exception:
            pass
    return []


def retrieval_debug(period: str, stage: str,
                     fund_code: str | None = None,
                     keywords: list[str] | None = None) -> dict:
    """retrieve_wiki_context 호출 + selected page 별 reason 분석."""
    if keywords is None:
        keywords = _load_keywords(period)

    # tokenize 로 selected 페이지의 hit breakdown 재계산
    tokens = []
    for kw in keywords:
        tokens.extend(_split_tokens(kw))
    seen = set()
    deduped = []
    for t in tokens:
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        deduped.append(t)

    # F2 follow-up: pinned exclude
    pinned = None
    excl = None
    if stage == "fund_comment" and fund_code:
        pinned = get_pinned_fund_context(fund_code=fund_code, period=period)
        if pinned.get("text"):
            extras = extract_fund_keywords_from_pinned(pinned, fund_code)
            for k in extras:
                if k.lower() not in seen:
                    keywords = list(keywords) + [k]
                    seen.add(k.lower())
                    deduped.append(k)
        if pinned.get("page_path"):
            excl = {pinned["page_path"]}

    r = retrieve_wiki_context(
        keywords, stage=stage, fund_code=fund_code,
        period=period, exclude_paths=excl,
    )

    # selected page 별 상세
    selected_detail = []
    for path in r["selected_pages"]:
        fp = WIKI_ROOT / path
        if not fp.exists():
            continue
        txt = fp.read_text(encoding="utf-8", errors="ignore")
        sc = _score_page(txt, fp.name, deduped)
        m = page_meta(fp)
        selected_detail.append({
            "path": path,
            "dir": m["dir"],
            "hit_count": sc[0],
            "length_bucket": sc[1],
            "source_bonus": sc[2],
            "cluster_key": m["cluster_key"],
            "source_type": m["source_type"],
            "page_period": m["page_period"],
            "primary_url": m["primary_url"],
            "primary_headline": (m["primary_headline"] or "")[:80],
        })

    # selected URL duplicate 검사 (event page 만)
    sel_urls = [d["primary_url"] for d in selected_detail
                if d["dir"] == "01_Events" and d["primary_url"]]
    url_counts = Counter(sel_urls)
    dup_urls = [(u, n) for u, n in url_counts.items() if n > 1]

    return {
        "stage": stage,
        "period": period,
        "fund_code": fund_code,
        "keywords": keywords,
        "keyword_count": len(deduped),
        "candidate_count": r["candidate_count"],
        "selected_count": r["selected_count"],
        "context_chars": r["context_chars"],
        "skipped_short_pages": r["skipped_short_pages"],
        "skipped_fund_mismatch": r["skipped_fund_mismatch"],
        "skipped_future_pages": r["skipped_future_pages"],
        "skipped_cluster_cap": r["skipped_cluster_cap"],
        "skipped_excluded": r.get("skipped_excluded", 0),
        "excluded_dirs": r.get("excluded_dirs", []),
        "excluded_dir_page_count": r.get("excluded_dir_page_count", 0),
        "stage_used": r["stage_used"],
        "cluster_cap_used": r["cluster_cap_used"],
        "selected_detail": selected_detail,
        "selected_url_duplicates": dup_urls,
        "pinned": pinned,
    }


# ──────────────────────────────────────────────────────────────────
# 3. Asset coverage
# ──────────────────────────────────────────────────────────────────

def asset_coverage_report(period: str,
                            retrieval_market: dict | None = None) -> list[dict]:
    """자산군별 03_Assets page 존재 + enrichment 보존 + selected 여부."""
    selected_paths_set: set[str] = set()
    if retrieval_market:
        selected_paths_set = set(retrieval_market.get("selected_pages",
            [d["path"] for d in retrieval_market.get("selected_detail", [])]))
    out = []
    assets_dir = WIKI_ROOT / "03_Assets"
    for asset, fname_candidates in ASSET_FILENAME_MAP.items():
        existing_paths = []
        for fname in fname_candidates:
            fp = assets_dir / f"{period}_{fname}.md"
            if fp.exists():
                m = page_meta(fp)
                existing_paths.append(m)
        if existing_paths:
            # enrichment 우선 (source_type=asset_wiki 또는 size 큰 것)
            enriched = [p for p in existing_paths
                        if p.get("source_type") == "asset_wiki"
                        or (p.get("body_chars") or 0) >= 1000]
            primary = enriched[0] if enriched else existing_paths[0]
            out.append({
                "asset_class": asset,
                "exists": True,
                "candidate_files": [p["name"] for p in existing_paths],
                "primary_file": primary["name"],
                "body_chars": primary.get("body_chars"),
                "source_type": primary.get("source_type"),
                "is_enriched": primary.get("source_type") in ("asset_wiki", "fund_wiki")
                                or (primary.get("body_chars") or 0) >= 1000,
                "in_market_selected": primary["path"] in selected_paths_set,
            })
        else:
            out.append({
                "asset_class": asset,
                "exists": False,
                "candidate_files": [],
                "primary_file": None,
                "body_chars": 0,
                "source_type": None,
                "is_enriched": False,
                "in_market_selected": False,
            })
    return out


# ──────────────────────────────────────────────────────────────────
# 4. Markdown rendering
# ──────────────────────────────────────────────────────────────────

def _kvtable(d: dict) -> str:
    if not d:
        return "(none)"
    return "\n".join(f"  - **{k}**: {v}" for k, v in d.items())


def render_inventory(inv: dict) -> str:
    lines = [
        f"### Inventory — `{inv['period']}`",
        f"- 전체 page: **{inv['total_pages']}**",
        f"- dir 별:",
    ]
    for d, n in sorted(inv["by_dir_counts"].items()):
        lines.append(f"  - `{d}/`: {n}")
    lines += [
        f"- 01_Events ID 형식: hex(deterministic)=**{inv['events_with_hex_id']}** / "
        f"sequential(stale)={inv['events_with_sequential_id']}",
        f"- future page: **{inv['future_pages']}** (정상은 0)",
        f"- 동일 primary_url 중복 그룹: **{len(inv['duplicate_url_groups'])}** "
        f"({'PASS' if not inv['duplicate_url_groups'] else 'FAIL'})",
    ]
    if inv["duplicate_url_groups"]:
        for u, n in list(inv["duplicate_url_groups"].items())[:3]:
            lines.append(f"  - `{u[:80]}` × {n}")
    lines += [
        f"- 동일 primary_headline 중복 그룹: **{len(inv['duplicate_headline_groups'])}** "
        f"({'PASS' if not inv['duplicate_headline_groups'] else 'FAIL'})",
        f"- source_type 분포:",
    ]
    for st, n in sorted(inv["source_type_distribution"].items(), key=lambda x: -x[1]):
        lines.append(f"  - `{st}`: {n}")
    lines += [
        f"- 본문 글자수: min={inv['chars_min']} / avg={inv['chars_avg']} / max={inv['chars_max']}",
    ]
    return "\n".join(lines)


def render_retrieval(r: dict, label: str) -> str:
    excl = r.get("pinned") or {}
    lines = [
        f"### Retrieval — {label}",
        f"- stage: `{r['stage']}` / period: `{r['period']}` / fund_code: `{r['fund_code']}`",
        f"- keywords (count={r['keyword_count']}): `{', '.join(r['keywords'][:15])}` "
        f"{'…' if len(r['keywords']) > 15 else ''}",
        f"- candidate: {r['candidate_count']} / selected: **{r['selected_count']}** / "
        f"context_chars: {r['context_chars']}",
        f"- skipped: short={r['skipped_short_pages']} / fund_mismatch={r['skipped_fund_mismatch']} / "
        f"future={r['skipped_future_pages']} / cluster_cap={r['skipped_cluster_cap']} / "
        f"excluded={r['skipped_excluded']}",
        f"- selected URL 중복 (event-only): **{len(r['selected_url_duplicates'])}** "
        f"({'PASS' if not r['selected_url_duplicates'] else 'FAIL'})",
    ]
    if r["selected_url_duplicates"]:
        for u, n in r["selected_url_duplicates"][:3]:
            lines.append(f"  - `{u[:80]}` × {n}")
    lines += [
        "",
        "| # | path | dir | hit | len_b | src | cluster_key | period |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, d in enumerate(r["selected_detail"], 1):
        cluster = (d["cluster_key"] or "—")[:30]
        period_str = f"{d['page_period']}" if d["page_period"] else "—"
        lines.append(
            f"| {i} | `{d['path']}` | `{d['dir']}` | {d['hit_count']} | "
            f"{d['length_bucket']} | {d['source_bonus']} | `{cluster}` | {period_str} |"
        )
    return "\n".join(lines)


def render_fund_comment(rfc: dict) -> str:
    pinned = rfc.get("pinned") or {}
    retrieved_04_funds = [d for d in rfc["selected_detail"]
                           if d["dir"] == "04_Funds"]
    own_in_sel = [d for d in retrieved_04_funds
                  if rfc["fund_code"] in d["path"]]
    other_in_sel = [d for d in retrieved_04_funds
                    if rfc["fund_code"] not in d["path"]]
    leaked = _stale_month_fund_leakage(rfc)
    lines = [
        f"### Fund-Comment Debug — `{rfc['fund_code']}` / `{rfc['period']}`",
        f"- pinned_fund_context_path: `{pinned.get('page_path')}`",
        f"- pinned_fund_context_chars: **{pinned.get('chars', 0)}**",
        f"- pinned reason: `{pinned.get('reason')}`",
        f"- retrieved selected paths ({rfc['selected_count']}):",
    ]
    for d in rfc["selected_detail"]:
        lines.append(f"  - `{d['path']}` (dir={d['dir']}, hit={d['hit_count']})")
    lines += [
        # R2 G7 fix metrics
        f"- **retrieved_04_funds_count**: {len(retrieved_04_funds)} "
        f"({'PASS — pinned 전용 정책 준수' if not retrieved_04_funds else 'FAIL — 정책 위반'})",
        f"- **stale_fund_page_leakage_count**: {len(leaked)} "
        f"({'PASS' if not leaked else 'FAIL'})",
        f"- **skipped_fund_stale_month** (stage 차단 04_Funds page 수): "
        f"{rfc.get('excluded_dir_page_count', 0)} (excluded_dirs="
        f"{rfc.get('excluded_dirs', [])})",
        f"- pinned ↔ retrieved 중복 제거: skipped_excluded=**{rfc['skipped_excluded']}** "
        f"(04_Funds dir 자체 차단되어 0 정상)",
        f"- 자기 04_Funds (`{rfc['fund_code']}`) selected 등장: {len(own_in_sel)} "
        f"(pinned 전용 정책 — selected 0 정상)",
        f"- 타 fund 04_Funds selected 등장: {len(other_in_sel)} (정책상 0 보장)",
    ]
    return "\n".join(lines)


def render_asset_coverage(rows: list[dict], period: str) -> str:
    lines = [
        f"### Asset Coverage — `{period}`",
        "",
        "| 자산군 | exists | primary_file | body_chars | source_type | enriched | in_market_selected |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        sel = "✓" if r["in_market_selected"] else ""
        ench = "✅" if r["is_enriched"] else "—"
        exists = "✅" if r["exists"] else "❌"
        lines.append(
            f"| {r['asset_class']} | {exists} | "
            f"`{r['primary_file'] or '—'}` | {r['body_chars'] or 0} | "
            f"`{r['source_type'] or '—'}` | {ench} | {sel} |"
        )

    enriched_n = sum(1 for r in rows if r["is_enriched"])
    base_n = sum(1 for r in rows if r["exists"] and not r["is_enriched"])
    missing_n = sum(1 for r in rows if not r["exists"])
    lines += [
        "",
        f"요약: enriched={enriched_n}/{len(rows)} / base only={base_n} / missing={missing_n}",
    ]
    if base_n:
        lines.append(
            "  ⚠️ base only 자산군은 향후 P3-4 enrichment 대상 (또는 base 가 enrichment 를 덮어쓰지 않았는지 확인 — `_is_enrichment_page` guard 작동 중)"
        )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# 5. R2 — Gate evaluation
# ──────────────────────────────────────────────────────────────────

def _stale_month_fund_leakage(rfc: dict) -> list[dict]:
    """fund_comment retrieve 결과에 *target period 와 다른 month* 의 자기
    04_Funds 페이지 등장 검출 (R2 신규 발견)."""
    target = _split_period(rfc["period"])
    fund = rfc["fund_code"]
    leaked = []
    for d in rfc["selected_detail"]:
        if d["dir"] != "04_Funds":
            continue
        if not fund or fund not in d["path"]:
            continue
        if d["page_period"] and d["page_period"] != target:
            leaked.append(d)
    return leaked


def _emit(all_results: list[dict], failures: list[dict], warnings: list[dict],
          *, gate_id: str, severity: str, status: str, period: str,
          fund_code: str | None, message: str, details: dict | None = None) -> None:
    """gate 결과 1건을 누적. status='PASS' 면 all_results 에만 추가, FAIL/WARNING 은
    failures/warnings 에도 분기 추가."""
    entry = {
        "gate_id": gate_id,
        "severity": severity,
        "status": status,
        "period": period,
        "fund_code": fund_code,
        "message": message,
        "details": details or {},
    }
    all_results.append(entry)
    if status == "FAIL":
        failures.append(entry)
    elif status in ("WARNING", "WARNING_SKIP"):
        warnings.append(entry)


def evaluate_gates(periods: list[str], funds: list[str], *,
                    skip_report_periods: set[str],
                    expected_enriched_periods: set[str]
                    ) -> tuple[list[dict], list[dict], list[dict]]:
    """gate 검사. Returns (failures, warnings, all_results).

    all_results: 모든 gate 평가 결과 (PASS 포함). JSON 출력용.
    failures / warnings: all_results 의 status='FAIL'/'WARNING' 만 필터된 view.
    """
    failures: list[dict] = []
    warnings: list[dict] = []
    all_results: list[dict] = []

    for period in periods:
        is_skip = period in skip_report_periods
        is_enriched_expected = period in expected_enriched_periods

        inv = inventory_report(period)

        # G1. duplicate primary_url
        dup_url_n = len(inv["duplicate_url_groups"])
        _emit(all_results, failures, warnings,
              gate_id="G1_duplicate_url", severity="FAIL",
              status="FAIL" if dup_url_n else "PASS",
              period=period, fund_code=None,
              message=(f"{dup_url_n} duplicate URL groups" if dup_url_n
                       else "no duplicate primary_url"),
              details={"count": dup_url_n,
                       "groups": list(inv["duplicate_url_groups"].keys())[:5]})

        # G2. duplicate primary_headline
        dup_head_n = len(inv["duplicate_headline_groups"])
        _emit(all_results, failures, warnings,
              gate_id="G2_duplicate_headline", severity="FAIL",
              status="FAIL" if dup_head_n else "PASS",
              period=period, fund_code=None,
              message=(f"{dup_head_n} duplicate headline groups" if dup_head_n
                       else "no duplicate primary_headline"),
              details={"count": dup_head_n})

        # G3 + G4 + G6: asset coverage + market_debate
        rmd = retrieval_debug(period, "market_debate")
        cov = asset_coverage_report(period, retrieval_market=rmd)
        missing_assets = [r["asset_class"] for r in cov if not r["exists"]]
        unenriched_assets = [r["asset_class"] for r in cov
                              if r["exists"] and not r["is_enriched"]]

        # G3
        if missing_assets:
            severity_g3 = "WARNING" if is_skip else "FAIL"
            status_g3 = "WARNING_SKIP" if is_skip else "FAIL"
            _emit(all_results, failures, warnings,
                  gate_id="G3_missing_required_asset",
                  severity=severity_g3, status=status_g3,
                  period=period, fund_code=None,
                  message=f"missing assets: {missing_assets}",
                  details={"missing": missing_assets, "skip_report": is_skip})
        else:
            _emit(all_results, failures, warnings,
                  gate_id="G3_missing_required_asset", severity="FAIL",
                  status="PASS", period=period, fund_code=None,
                  message="all required assets present",
                  details={"missing": []})

        # G4
        if is_enriched_expected:
            if unenriched_assets:
                _emit(all_results, failures, warnings,
                      gate_id="G4_enrichment_expected_but_none",
                      severity="FAIL", status="FAIL",
                      period=period, fund_code=None,
                      message=f"unenriched: {unenriched_assets}",
                      details={"unenriched": unenriched_assets})
            else:
                _emit(all_results, failures, warnings,
                      gate_id="G4_enrichment_expected_but_none",
                      severity="FAIL", status="PASS",
                      period=period, fund_code=None,
                      message="all assets enriched (source_type set)",
                      details={"unenriched": []})

        # G6. market_debate selected URL 중복
        dup_sel_urls = rmd["selected_url_duplicates"]
        _emit(all_results, failures, warnings,
              gate_id="G6_market_debate_dup_url", severity="FAIL",
              status="FAIL" if dup_sel_urls else "PASS",
              period=period, fund_code=None,
              message=(f"{len(dup_sel_urls)} duplicate URL in selected"
                       if dup_sel_urls else "no duplicate URL in selected"),
              details={"duplicates": [u for u, _ in dup_sel_urls]})

        # G5 + G7: fund_comment 별
        for fund in funds:
            rfc = retrieval_debug(period, "fund_comment", fund_code=fund)
            pinned = rfc.get("pinned") or {}
            # G5
            if pinned.get("page_path"):
                pinned_in_sel = any(
                    d["path"] == pinned["page_path"]
                    for d in rfc["selected_detail"]
                )
                _emit(all_results, failures, warnings,
                      gate_id="G5_pinned_retrieved_dup", severity="FAIL",
                      status="FAIL" if pinned_in_sel else "PASS",
                      period=period, fund_code=fund,
                      message=(f"pinned {pinned['page_path']} also in selected"
                               if pinned_in_sel
                               else "pinned ↔ retrieved dedup OK"),
                      details={"pinned_path": pinned["page_path"],
                               "in_selected": pinned_in_sel})
            # G7
            retrieved_04 = [d for d in rfc["selected_detail"]
                             if d["dir"] == "04_Funds"]
            _emit(all_results, failures, warnings,
                  gate_id="G7_fund_comment_04_funds_in_retrieved",
                  severity="FAIL",
                  status="FAIL" if retrieved_04 else "PASS",
                  period=period, fund_code=fund,
                  message=(f"04_Funds in retrieved: {[d['path'] for d in retrieved_04]}"
                           if retrieved_04
                           else "04_Funds excluded from retrieved (정책 준수)"),
                  details={"retrieved_04_funds_count": len(retrieved_04),
                           "retrieved_04_funds": [d["path"] for d in retrieved_04]})

    return failures, warnings, all_results


def render_gate_summary(failures: list[dict], warnings: list[dict],
                          periods: list[str], skip_report_periods: set[str]) -> str:
    lines = ["", "---", "", "## 5. Gate Evaluation (`--fail-on-gate`)", ""]
    lines.append(f"- periods evaluated: {periods}")
    lines.append(f"- skip-report-periods (warning 강등): {sorted(skip_report_periods)}")
    lines.append(f"- **FAIL: {len(failures)} / WARNING: {len(warnings)}**")
    lines.append("")

    if failures:
        lines.append("### ❌ FAIL")
        for f in failures:
            fund = f.get("fund_code") or "-"
            lines.append(
                f"  - `{f['gate_id']}` period=`{f['period']}` fund=`{fund}` — {f['message']}"
            )
        lines.append("")
    else:
        lines.append("### ✅ FAIL: 0건")
        lines.append("")

    if warnings:
        lines.append("### ⚠️ WARNING")
        for w in warnings:
            fund = w.get("fund_code") or "-"
            lines.append(
                f"  - `{w['gate_id']}` period=`{w['period']}` fund=`{fund}` — {w['message']}"
            )
        lines.append("")
    else:
        lines.append("### ⚠️ WARNING: 0건")
        lines.append("")

    return "\n".join(lines)


# R3-a: JSON output schema
SCHEMA_VERSION = "1.0.0"
TOOL_VERSION = "wiki_retrieval_coverage v2 (R3, 2026-05-06)"


def build_json_report(periods: list[str], funds: list[str], *,
                       skip_report_periods: set[str] | None = None,
                       expected_enriched_periods: set[str] | None = None,
                       fail_on_gate: bool = False) -> dict:
    """JSON output 산출 (markdown 과 동일 source-of-truth, gate count 일관)."""
    from datetime import datetime, timezone
    skip_set = skip_report_periods or set()
    enriched_set = expected_enriched_periods or set()

    # period 별 데이터
    inv_by_period = {p: inventory_report(p) for p in periods}
    rmd_by_period = {p: retrieval_debug(p, "market_debate") for p in periods}
    cov_by_period = {p: asset_coverage_report(p, retrieval_market=rmd_by_period[p])
                      for p in periods}
    fc_by_period: dict[str, dict] = {}
    for p in periods:
        fc_by_period[p] = {}
        for fund in funds:
            fc_by_period[p][fund] = retrieval_debug(p, "fund_comment", fund_code=fund)

    # gate 평가 (fail_on_gate 와 무관 — JSON 에는 항상 평가 포함)
    failures, warns, all_results = evaluate_gates(
        periods, funds,
        skip_report_periods=skip_set,
        expected_enriched_periods=enriched_set,
    )
    pass_n = sum(1 for r in all_results if r["status"] == "PASS")
    exit_code_expected = 1 if (fail_on_gate and failures) else 0

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "periods": list(periods),
        "funds": list(funds),
        "skip_report_periods": sorted(skip_set),
        "expected_enriched_periods": sorted(enriched_set),
        "fail_on_gate": fail_on_gate,
        "inventory_summary": inv_by_period,
        "retrieval_debug": rmd_by_period,
        "fund_comment_debug": fc_by_period,
        "asset_coverage": cov_by_period,
        "gate_summary": {
            "total": len(all_results),
            "pass": pass_n,
            "fail": len(failures),
            "warning": len(warns),
            "exit_code_expected": exit_code_expected,
            "fail_on_gate": fail_on_gate,
        },
        "gate_results": all_results,
        "warnings": [],   # 도구 자체의 비-gate warning (현재 미사용)
        "errors": [],     # 도구 자체의 error (현재 미사용)
    }


def render_report(periods: list[str], funds: list[str], *,
                    skip_report_periods: set[str] | None = None,
                    expected_enriched_periods: set[str] | None = None,
                    fail_on_gate: bool = False) -> tuple[str, list[dict], list[dict]]:
    """Returns (markdown_text, failures, warnings)."""
    today = date.today().isoformat()
    skip_set = skip_report_periods or set()
    enriched_set = expected_enriched_periods or set()
    lines = [
        f"# Wiki Retrieval / Coverage Report",
        f"",
        f"**Generated**: {today}  ",
        f"**Periods**: {periods}  ",
        f"**Funds**: {funds}  ",
        f"**Tool**: `tools/wiki_retrieval_coverage.py`  ",
        f"**Mode**: {'gate (fail-on-gate)' if fail_on_gate else 'report only'}  ",
        f"**Reproducer**: `python tools/wiki_retrieval_coverage.py "
        f"--period {' --period '.join(periods)} "
        f"--fund {' --fund '.join(funds)}"
        + (f" --fail-on-gate" if fail_on_gate else "")
        + ("".join(f" --skip-report-period {p}" for p in sorted(skip_set)))
        + ("".join(f" --expected-enriched-period {p}" for p in sorted(enriched_set)))
        + "`",
        "",
        "---",
        "",
        "## 1. Wiki Inventory (period 별)",
        "",
    ]
    for p in periods:
        inv = inventory_report(p)
        lines.append(render_inventory(inv))
        lines.append("")

    lines += ["---", "", "## 2. Retrieval Debug — market_debate", ""]
    market_retrievals = {}
    for p in periods:
        r = retrieval_debug(p, "market_debate", fund_code=None)
        market_retrievals[p] = r
        lines.append(render_retrieval(r, f"market_debate / period={p}"))
        lines.append("")

    lines += ["---", "", "## 3. Fund-Comment Debug", ""]
    for p in periods:
        for fund in funds:
            rfc = retrieval_debug(p, "fund_comment", fund_code=fund)
            lines.append(render_fund_comment(rfc))
            lines.append("")

    lines += ["---", "", "## 4. Asset Coverage (자산군별 03_Assets)", ""]
    for p in periods:
        rows = asset_coverage_report(p, retrieval_market=market_retrievals.get(p))
        lines.append(render_asset_coverage(rows, p))
        lines.append("")

    lines += [
        "---",
        "",
        "## Acceptance Criteria 체크",
        "",
        "- ✅ 2026-04 / 2026-05 report 생성 가능",
        "- ✅ 07G04 / 08K88 fund_comment debug 에서 pinned fund page 확인 가능 "
        "(섹션 3 의 pinned_fund_context_path)",
        "- ✅ market_debate selected URL 중복 0건 확인 가능 (섹션 2 의 'selected URL 중복')",
        "- ✅ 03_Assets / 04_Funds enrichment 보존 상태 표시 (섹션 4 의 enriched 컬럼)",
        "- ✅ retrieval reason 추적 가능: hit / length_bucket / source_bonus / cluster_key / "
        "page_period 컬럼이 selected page 별로 노출",
    ]

    failures: list[dict] = []
    warnings_list: list[dict] = []
    if fail_on_gate:
        failures, warnings_list, _all = evaluate_gates(
            periods, funds,
            skip_report_periods=skip_set,
            expected_enriched_periods=enriched_set,
        )
        lines.append(render_gate_summary(
            failures, warnings_list, periods, skip_set,
        ))

    return "\n".join(lines), failures, warnings_list


def main():
    parser = argparse.ArgumentParser(description="Wiki retrieval coverage report + gate (R1+R2)")
    parser.add_argument("--period", action="append",
                        help="period (YYYY-MM). 다중 지정 가능. 미지정 시 자동 검출.")
    parser.add_argument("--fund", action="append",
                        help="fund_code. 다중 지정 가능. 기본 [07G04, 08K88]")
    parser.add_argument("--output", "-o", default=None,
                        help="output markdown path. 기본 debug/wiki_retrieval_coverage_{YYYYMMDD}.md")
    parser.add_argument("--fail-on-gate", action="store_true",
                        help="gate 검사 후 fail 있으면 exit 1 (R2)")
    parser.add_argument("--skip-report-period", action="append", default=[],
                        help="운용보고 skip period — wiki coverage 검증은 함, "
                             "missing asset 은 WARNING 으로 강등 (R2)")
    parser.add_argument("--expected-enriched-period", action="append", default=[],
                        help="enrichment 기대 period — base only (source_type=none) "
                             "이면 G4 FAIL (R2)")
    parser.add_argument("--json-out", default=None,
                        help="JSON 출력 path (R3). 미지정 시 markdown 만. "
                             "schema_version 과 gate_results 포함 — Admin API "
                             "에서 그대로 read 가능.")
    args = parser.parse_args()

    if not args.period:
        # 자동 검출 — wiki/01_Events 의 모든 unique YYYY-MM
        events_dir = WIKI_ROOT / "01_Events"
        periods_set = set()
        for fp in events_dir.glob("*.md"):
            m = re.match(r"(\d{4}-\d{2})", fp.name)
            if m:
                periods_set.add(m.group(1))
        args.period = sorted(periods_set)

    if not args.fund:
        args.fund = ["07G04", "08K88"]

    if not args.output:
        today = date.today().strftime("%Y%m%d")
        args.output = str(PROJECT_ROOT / "debug" / f"wiki_retrieval_coverage_{today}.md")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    text, failures, warnings_list = render_report(
        args.period, args.fund,
        skip_report_periods=set(args.skip_report_period),
        expected_enriched_periods=set(args.expected_enriched_period),
        fail_on_gate=args.fail_on_gate,
    )
    out_path.write_text(text, encoding="utf-8")

    print(f"[ok] markdown report → {out_path}")
    print(f"     periods={args.period} funds={args.fund}")
    print(f"     {len(text):,} chars / {len(text.splitlines())} lines")

    # R3-a: JSON output
    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_data = build_json_report(
            args.period, args.fund,
            skip_report_periods=set(args.skip_report_period),
            expected_enriched_periods=set(args.expected_enriched_period),
            fail_on_gate=args.fail_on_gate,
        )
        json_path.write_text(
            json.dumps(json_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        gs = json_data["gate_summary"]
        print(f"[ok] json report     → {json_path}")
        print(f"     gate: total={gs['total']} pass={gs['pass']} "
              f"fail={gs['fail']} warning={gs['warning']}")

    if args.fail_on_gate:
        print(f"     gate: FAIL={len(failures)} / WARNING={len(warnings_list)}")
        for f in failures:
            print(f"     ❌ {f['gate']} period={f['period']}: {f['detail']}")
        for w in warnings_list:
            print(f"     ⚠️  {w['gate']} period={w['period']}: {w['detail']}")
        if failures:
            sys.exit(1)


# 회귀 호출 호환 — 기존 외부 import 가 render_report() text 만 받던 경우.
def render_report_text_only(*args, **kwargs) -> str:
    text, _, _ = render_report(*args, **kwargs)
    return text


if __name__ == "__main__":
    main()
