"""R8-A: Evidence Annotation Resolver — multi-source lookup.

LLM 호출 0. 디스크 read 만. report_output / draft 무수정.

문제:
  comment_trace 가 market_source._evidence_ids 를 build_evidence_annotations
  (debate_service.py) 로 합성할 때 1~3월 news + naver_research adapted 만
  검색 → article_id 가 그 윈도우 밖 / debate_logs cache 에만 존재하면 모두
  title='(매핑 실패)' 로 남고 causal claim extraction 이 실패.

해결:
  evidence_id 별로 다음 우선순위로 메타를 복구:

    P1. fund_draft.evidence_annotations          (가장 신뢰)
    P2. market_source_data.evidence_annotations  (debate 직접 산출물)
    P3. debate_logs/{period}.json.evidence_annotations
        (Q-FIX-1 이후 quarterly 도 자체 ann 보유 — 보통 P1+P2 보다 풍부)
    P4. data/news/{YYYY-MM}.json (월별, period 의 month + ±1 buffer)
    P5. data/naver_research/adapted/{YYYY-MM}.json (월별, ±1)

  각 ann 에 `_source_type` 메타 (어디서 왔는지) + `_resolved` flag.
  못 찾은 evidence 는 placeholder ann (title='(매핑 실패)') + unresolved 카운트.

API:
    resolved, stats = resolve_evidence_annotations(
        evidence_ids, period, fund_draft, market_source_data, project_root)

    stats = {
        "resolved_count":   int,
        "unresolved_count": int,
        "resolution_rate":  float (0~1),
        "source_counts":    {"fund_draft": .., "market_source": ..,
                              "debate_logs": .., "news": .., "research": ..},
        "unresolved_ids":   [...],
    }
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

UNRESOLVED_TITLE = "(매핑 실패)"

PERIOD_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
PERIOD_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


# ──────────────────────────────────────────────────────────────────
# period → year + month list (with ±1 buffer for news/research)
# ──────────────────────────────────────────────────────────────────

def _period_to_months(period: str) -> tuple[int, list[int], list[int]]:
    """Return (year, primary_months, buffered_months).

    primary_months: 정확히 period 가 cover 하는 월
    buffered_months: ±1 buffer (boundary article_id 흡수)
    """
    m = PERIOD_QUARTER_RE.match(period)
    if m:
        yr = int(m.group(1))
        q = int(m.group(2))
        primary = [(q - 1) * 3 + i for i in (1, 2, 3)]
        # Q1: 0~4월, Q2: 3~7, Q3: 6~10, Q4: 9~12+1(다음해 1월 — 단순화: 12까지)
        lo = max(1, primary[0] - 1)
        hi = min(12, primary[-1] + 1)
        buffered = list(range(lo, hi + 1))
        return yr, primary, buffered
    m = PERIOD_MONTH_RE.match(period)
    if m:
        yr = int(m.group(1))
        mo = int(m.group(2))
        primary = [mo]
        lo = max(1, mo - 1)
        hi = min(12, mo + 1)
        buffered = list(range(lo, hi + 1))
        return yr, primary, buffered
    # Unknown format → 빈
    return 0, [], []


# ──────────────────────────────────────────────────────────────────
# Source loaders (lazy + cached per call)
# ──────────────────────────────────────────────────────────────────

def _index_annotations(anns: list[dict] | None) -> dict[str, dict]:
    """list[ann] → {article_id: ann}. article_id 없으면 skip."""
    out: dict[str, dict] = {}
    for a in anns or []:
        aid = a.get("article_id")
        if aid:
            out[aid] = a
    return out


def _load_debate_logs(project_root: Path, period: str) -> dict[str, dict]:
    """debate_logs/{period}.json.evidence_annotations 인덱스."""
    fp = project_root / "market_research" / "data" / "debate_logs" / f"{period}.json"
    if not fp.exists():
        return {}
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return _index_annotations(d.get("evidence_annotations"))


def _load_news_month(project_root: Path, year: int, month: int) -> dict[str, dict]:
    """news/{YYYY-MM}.json 의 article_id 인덱스."""
    fp = project_root / "market_research" / "data" / "news" / f"{year}-{month:02d}.json"
    if not fp.exists():
        return {}
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return {}
    arts = d.get("articles") if isinstance(d, dict) else d
    if not isinstance(arts, list):
        return {}
    out: dict[str, dict] = {}
    for a in arts:
        aid = a.get("_article_id") or a.get("article_id")
        if aid:
            out[aid] = a
    return out


def _load_research_month(project_root: Path, year: int, month: int) -> dict[str, dict]:
    """naver_research/adapted/{YYYY-MM}.json 의 article_id 인덱스."""
    fp = (project_root / "market_research" / "data" / "naver_research"
          / "adapted" / f"{year}-{month:02d}.json")
    if not fp.exists():
        return {}
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return {}
    arts = d if isinstance(d, list) else d.get("articles") or []
    out: dict[str, dict] = {}
    for a in arts:
        aid = a.get("_article_id") or a.get("article_id")
        if aid:
            out[aid] = a
    return out


# ──────────────────────────────────────────────────────────────────
# Source-shape adapters → 표준 annotation schema
# ──────────────────────────────────────────────────────────────────

def _ann_from_existing(rec: dict, ref: int, source_type: str) -> dict:
    """이미 annotation 형태인 record (debate_logs / fund_draft 등) → 표준 schema."""
    title = (rec.get("title") or "").strip()
    return {
        "ref": ref,
        "article_id": rec.get("article_id"),
        "title": title or UNRESOLVED_TITLE,
        "url": rec.get("url", ""),
        "source": rec.get("source", ""),
        "date": rec.get("date", ""),
        "topic": rec.get("topic", ""),
        "all_topics": list(rec.get("all_topics") or []),
        "salience": rec.get("salience"),
        "salience_explanation": rec.get("salience_explanation", ""),
        "_source_type": source_type,
        "_resolved": bool(title),
    }


def _ann_from_news_article(art: dict, eid: str, ref: int, source_type: str) -> dict:
    """news/research 원천 record → 표준 schema."""
    classified = art.get("_classified_topics") or []
    all_topics = [t.get("topic", "") for t in classified if t.get("topic")]
    title = (art.get("title") or "").strip()
    return {
        "ref": ref,
        "article_id": eid,
        "title": (title or UNRESOLVED_TITLE)[:200],
        "url": art.get("url", ""),
        "source": art.get("source", ""),
        "date": art.get("date", ""),
        "topic": art.get("primary_topic", ""),
        "all_topics": all_topics,
        "salience": art.get("_event_salience"),
        "salience_explanation": "",
        "_source_type": source_type,
        "_resolved": bool(title),
    }


def _placeholder_ann(eid: str, ref: int) -> dict:
    return {
        "ref": ref,
        "article_id": eid,
        "title": UNRESOLVED_TITLE,
        "url": "",
        "source": "",
        "date": "",
        "topic": "",
        "all_topics": [],
        "salience": None,
        "salience_explanation": "",
        "_source_type": "unresolved",
        "_resolved": False,
    }


# ──────────────────────────────────────────────────────────────────
# Public entry
# ──────────────────────────────────────────────────────────────────

def resolve_evidence_annotations(
    evidence_ids: list[str],
    period: str,
    fund_draft: dict | None,
    market_source_data: dict | None,
    project_root: Path,
) -> tuple[list[dict], dict]:
    """evidence_ids 에 대해 다양한 source 에서 lookup → 표준 annotation list.

    Returns (annotations, stats).
    """
    # P1: fund_draft.evidence_annotations
    p1 = _index_annotations((fund_draft or {}).get("evidence_annotations"))
    # P2: market_source_data.evidence_annotations
    p2 = _index_annotations((market_source_data or {}).get("evidence_annotations"))
    # P3: debate_logs/{period}.json
    p3 = _load_debate_logs(project_root, period)
    # P4/P5: lazy month load
    yr, primary_months, buffered_months = _period_to_months(period)

    news_cache: dict[int, dict[str, dict]] = {}
    research_cache: dict[int, dict[str, dict]] = {}

    def _news(month: int) -> dict[str, dict]:
        if month not in news_cache:
            news_cache[month] = _load_news_month(project_root, yr, month)
        return news_cache[month]

    def _research(month: int) -> dict[str, dict]:
        if month not in research_cache:
            research_cache[month] = _load_research_month(project_root, yr, month)
        return research_cache[month]

    annotations: list[dict] = []
    source_counts: dict[str, int] = {
        "fund_draft": 0, "market_source": 0, "debate_logs": 0,
        "news": 0, "research": 0, "unresolved": 0,
    }
    unresolved_ids: list[str] = []

    for i, eid in enumerate(evidence_ids, 1):
        # P1
        if eid in p1 and (p1[eid].get("title") or "").strip():
            annotations.append(_ann_from_existing(p1[eid], i, "fund_draft"))
            source_counts["fund_draft"] += 1
            continue
        # P2
        if eid in p2 and (p2[eid].get("title") or "").strip():
            annotations.append(_ann_from_existing(p2[eid], i, "market_source"))
            source_counts["market_source"] += 1
            continue
        # P3
        if eid in p3 and (p3[eid].get("title") or "").strip():
            annotations.append(_ann_from_existing(p3[eid], i, "debate_logs"))
            source_counts["debate_logs"] += 1
            continue
        # P4 — primary 먼저, 그 다음 buffered
        found = None
        kind = None
        for m in primary_months:
            if eid in _news(m):
                found = _news(m)[eid]; kind = "news"; break
        if not found:
            for m in primary_months:
                if eid in _research(m):
                    found = _research(m)[eid]; kind = "research"; break
        if not found:
            for m in buffered_months:
                if m in primary_months:
                    continue
                if eid in _news(m):
                    found = _news(m)[eid]; kind = "news"; break
        if not found:
            for m in buffered_months:
                if m in primary_months:
                    continue
                if eid in _research(m):
                    found = _research(m)[eid]; kind = "research"; break

        if found:
            annotations.append(_ann_from_news_article(found, eid, i, kind or "news"))
            source_counts[kind or "news"] += 1
            continue

        # Unresolved
        annotations.append(_placeholder_ann(eid, i))
        source_counts["unresolved"] += 1
        unresolved_ids.append(eid)

    total = len(evidence_ids) or 1
    stats = {
        "resolved_count": total - len(unresolved_ids),
        "unresolved_count": len(unresolved_ids),
        "resolution_rate": round(1.0 - len(unresolved_ids) / total, 3),
        "source_counts": source_counts,
        "unresolved_ids": unresolved_ids,
    }
    return annotations, stats


def is_resolved(ann: dict) -> bool:
    """ann 이 실제 메타를 가진 resolved 인지 판정."""
    if not ann:
        return False
    if ann.get("_resolved") is not None:
        return bool(ann["_resolved"])
    title = (ann.get("title") or "").strip()
    return bool(title) and title != UNRESOLVED_TITLE
