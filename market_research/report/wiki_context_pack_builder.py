# -*- coding: utf-8 -*-
"""R9-B.2 — Wiki Context Pack Builder (read-only, debug-only).

Loads canonical wiki pages and packages them into a structured
``wiki_context_pack`` dict for downstream R9-B.4 prompt injection.

Boundary (R9-B.2):
  - LLM 호출 0
  - debate prompt 미주입 (builder 산출만)
  - 운영 wiki / claims / report_output / regime_memory 변경 0
  - 기존 raw-source-first path 변경 0

Public API:
    build_wiki_context_pack(...)
    parse_wiki_page(path) -> WikiPageRecord

CLI 는 ``market_research/tools/build_wiki_context_pack.py`` 에서 호출.

See ``market_research/docs/r9b_wiki_first_debate_architecture.md`` for the
schema this builder targets.
"""
from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

# wiki/__init__ 는 pymysql 의존이라 paths 만 직접 import.
import importlib.util as _iu
import sys as _sys

_WIKI_PATHS_PATH = Path(__file__).resolve().parent.parent / "wiki" / "paths.py"
_spec = _iu.spec_from_file_location("_r9b_paths", _WIKI_PATHS_PATH)
_paths_mod = _iu.module_from_spec(_spec)
_sys.modules.setdefault("_r9b_paths", _paths_mod)
_spec.loader.exec_module(_paths_mod)  # type: ignore[union-attr]
WIKI_ROOT: Path = _paths_mod.WIKI_ROOT


SCHEMA_VERSION = "r9b-context-pack-1.0.0"
MODE = "wiki_first_debug"
DEFAULT_MAX_PAGES = 12
DEFAULT_BODY_EXCERPT_CHARS = 700

# R9-B.6C — Project local timezone for timestamp-naive frontmatter values.
# Existing production wiki pages (R9-A.1 pilot, R9-A.21A dual-anchor) store
# `promoted_at` as KST timestamp without offset; new pages may include
# `+09:00` or UTC `Z`. _parse_timestamp normalizes both to tz-aware datetime.
_PROJECT_LOCAL_TZ = timezone(timedelta(hours=9))


def _parse_timestamp(s: str | None) -> datetime | None:
    """ISO-8601 timestamp string → timezone-aware datetime.

    naive (no tz offset) 값은 project local (Asia/Seoul, UTC+9) 으로 해석.
    parse 실패 → None.
    """
    if not isinstance(s, str) or not s.strip():
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_PROJECT_LOCAL_TZ)
    return dt


def _is_future_relative(available_from: str | None,
                        builder_run_time: str) -> bool:
    """available_from 이 builder_run_time 이후이면 True.

    timezone-aware datetime 비교. naive 입력은 KST(UTC+9) 로 해석. 둘 다
    parse 실패하면 안전하게 lex string 비교 (legacy 회귀 방지).
    """
    if not available_from:
        return False
    af = _parse_timestamp(available_from)
    rt = _parse_timestamp(builder_run_time)
    if af is None or rt is None:
        return bool(available_from > builder_run_time)
    return af > rt

# Global selection priority (workorder §"권장 selection priority").
# 1. 08_Claims (joined) → reserved phase
# 2. 07_Graph_Evidence → 5. 03_Assets → 6. 02_Entities → fill phase (round-robin)
# 04_Funds pinned 은 fund_comment stage contract 이라 claims 보다 먼저 reserve.
# 06_Debate_Memory 는 opt-in 시 round-robin 맨 끝.
_FILL_PRIORITY_DIRS: tuple[str, ...] = (
    "07_Graph_Evidence",
    "05_Regime_Canonical",
    "01_Events",
    "03_Assets",
    "02_Entities",
)

# Dir → page_type
_DIR_TO_TYPE: dict[str, str] = {
    "00_Index": "wiki_index",
    "01_Events": "event",
    "02_Entities": "entity",
    "03_Assets": "asset",
    "04_Funds": "fund",
    "05_Regime_Canonical": "regime",
    "06_Debate_Memory": "debate_memory",
    "07_Graph_Evidence": "graph_evidence",
    "08_Claims": "claim",
}

# Dir → source_type (R9-B.1 §8.12)
_DIR_TO_SOURCE_TYPE: dict[str, str] = {
    "01_Events": "wiki_event_memory",
    "02_Entities": "wiki_entity_memory",
    "03_Assets": "wiki_asset_memory",
    "04_Funds": "fund_context",
    "05_Regime_Canonical": "wiki_regime_memory",
    "06_Debate_Memory": "interpreted_memory",
    "07_Graph_Evidence": "wiki_graph_memory",
    "08_Claims": "claim_memory",
    "00_Index": "wiki_index",
}

# Stage policy (R9-B.2 §7 + design doc §5)
_STAGE_DIRS: dict[str, tuple[str, ...]] = {
    "market_debate": (
        "01_Events", "02_Entities", "03_Assets",
        "05_Regime_Canonical", "07_Graph_Evidence", "08_Claims",
    ),
    "fund_comment": (
        "01_Events", "02_Entities", "03_Assets",
        "04_Funds",  # pinned via fund_code
        "05_Regime_Canonical", "07_Graph_Evidence", "08_Claims",
    ),
    "quarterly_debate": (
        "01_Events", "02_Entities", "03_Assets",
        "05_Regime_Canonical", "07_Graph_Evidence", "08_Claims",
    ),
    "admin_preview": tuple(_DIR_TO_TYPE.keys()),
}

# Period-agnostic dirs — window filter 면제 (date 없는 canonical regime / index)
_PERIOD_AGNOSTIC_DIRS: frozenset[str] = frozenset({
    "00_Index", "05_Regime_Canonical",
})


_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")
_FILENAME_PERIOD_RE = re.compile(r"(\d{4})-(\d{2})")


# ──────────────────────────────────────────────────────────────────
# Local Rule A/B (decoupled from market_research.wiki.claim_pages —
# 그 모듈은 pymysql 까지 전이 import 함). 운영 정의와 정확히 동일.
# ──────────────────────────────────────────────────────────────────

_RULE_B_CHAIN_MIN = 3
_RULE_B_SUPPORTING_EV_MIN = 2


def _meets_rule_a_local(claim: dict) -> bool:
    try:
        s = float(claim.get("salience", 0.0))
        c = float(claim.get("confidence", 0.0))
    except (TypeError, ValueError):
        return False
    aas = claim.get("affected_assets") or []
    return s >= 0.7 and c >= 0.7 and isinstance(aas, list) and len(aas) >= 3


def _meets_rule_b_local(claim: dict) -> bool:
    cc = claim.get("causal_chain") or []
    if not isinstance(cc, list) or len(cc) < _RULE_B_CHAIN_MIN:
        return False
    sup = claim.get("supporting_evidence_ids") or []
    return isinstance(sup, list) and len(sup) >= _RULE_B_SUPPORTING_EV_MIN


def _reorder_claims_asset_roundrobin(entries: list[dict]) -> list[dict]:
    """claim entries 를 자산군 round-robin 으로 재배열 (B Gate3).

    입력은 store 우선순위(confidence × salience desc) 순서. 자산군별 버킷으로
    나눠 conf×sal 순서를 보존한 채 자산군을 번갈아 1개씩 뽑는다. → 자산 다양성이
    앞쪽에 보존되어, max_pages 트림 후에도 특정 자산(이란·에너지) 독점이 완화되고
    LLM prompt 가 자산 균형 claim 을 먼저 본다. 멤버십(개수)은 불변.

    affected_assets 추출 불가 entry 는 순서 보존해 뒤로.
    """
    from collections import OrderedDict
    from market_research.core.asset_taxonomy import claim_primary_asset

    buckets: "OrderedDict[str, list[dict]]" = OrderedDict()
    no_asset: list[dict] = []
    for e in entries:  # store conf×sal 순서 유지
        a = claim_primary_asset({"affected_assets": e.get("affected_assets") or []})
        if a is None:
            no_asset.append(e)
        else:
            buckets.setdefault(a, []).append(e)
    out: list[dict] = []
    while any(buckets.values()):
        for a in list(buckets.keys()):
            if buckets[a]:
                out.append(buckets[a].pop(0))
    out.extend(no_asset)
    return out


def _reorder_event_records_asset_stratified(records: list) -> list:
    """01_Events 레코드를 자산군 round-robin 으로 재배열 (B Gate4).

    알파벳순(파일명) 대신 frontmatter primary_asset 별 버킷 → 버킷 내 milestone 우선
    + avg_salience desc → 자산 번갈아. 특정 이슈(지정학·에너지) 독점 완화 +
    주요 자산 이벤트(코스피 record 등 milestone) 가 pack 에 진입하도록.
    """
    from collections import OrderedDict

    def _fm(r):
        return getattr(r, "frontmatter", None) or {}

    def _asset(r):
        return _fm(r).get("primary_asset") or None

    def _ms(r):
        v = _fm(r).get("is_milestone")
        return str(v).strip().lower() == "true" if v is not None else False

    def _sal(r):
        try:
            return float(_fm(r).get("avg_salience") or 0.0)
        except (ValueError, TypeError):
            return 0.0

    # 버킷 내 정렬: milestone 우선, 그다음 avg_salience desc
    ordered = sorted(records, key=lambda r: (_ms(r), _sal(r)), reverse=True)
    buckets: "OrderedDict[str, list]" = OrderedDict()
    no_asset: list = []
    for r in ordered:
        a = _asset(r)
        if a:
            buckets.setdefault(a, []).append(r)
        else:
            no_asset.append(r)
    out: list = []
    while any(buckets.values()):
        for a in list(buckets.keys()):
            if buckets[a]:
                out.append(buckets[a].pop(0))
    out.extend(no_asset)
    return out


# ──────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────

@dataclass
class WikiPageRecord:
    """Parsed wiki page (read-only)."""
    path: str                # WIKI_ROOT-relative posix path
    directory: str           # "01_Events" 등
    page_type: str           # "event" 등
    source_type: str         # "wiki_event_memory" 등
    title: str
    frontmatter: dict
    body_excerpt: str
    # Derived date fields (frontmatter 또는 filename fallback)
    period_key: str | None
    window_start: str | None
    window_end: str | None
    as_of_date: str | None
    source_cutoff_date: str | None
    available_from: str | None
    # Claim-specific
    claim_id: str | None = None
    canonical_group_id: str | None = None
    related_group_ids: list[str] = field(default_factory=list)
    affected_assets: list[str] = field(default_factory=list)
    promotion_rule: str | None = None
    # Provenance — fallback warning 발생 여부
    used_filename_fallback: bool = False


# ──────────────────────────────────────────────────────────────────
# Date helpers
# ──────────────────────────────────────────────────────────────────

def _month_end_date(period_key: str) -> str | None:
    """'2026-04' → '2026-04-30'."""
    m = _PERIOD_RE.match(period_key or "")
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12):
        return None
    last = calendar.monthrange(y, mo)[1]
    return f"{y:04d}-{mo:02d}-{last:02d}"


def _month_start_date(period_key: str) -> str | None:
    m = _PERIOD_RE.match(period_key or "")
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    return f"{y:04d}-{mo:02d}-01"


# R9-B.5 — quarter label → 3 monthly period_keys.
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def _quarter_to_period_keys(quarter_label: str) -> list[str]:
    """'2026-Q1' → ['2026-01', '2026-02', '2026-03'].

    Raises ValueError on bad input. R9-B.5 quarterly stage 의 유일한
    label→monthly unpacking 진입점.
    """
    m = _QUARTER_RE.match(quarter_label or "")
    if not m:
        raise ValueError(
            f"invalid quarter label {quarter_label!r}: expected YYYY-Q[1-4]"
        )
    y, q = int(m.group(1)), int(m.group(2))
    months = [(q - 1) * 3 + i for i in (1, 2, 3)]
    return [f"{y:04d}-{mo:02d}" for mo in months]


def _resolve_request_window(
    *,
    period_key: str,
    period_type: str,
    window_start: str | None,
    window_end: str | None,
    as_of_date: str | None,
    period_keys: list[str] | None = None,
) -> dict:
    """Fill defaults for monthly / quarterly / custom request.

    monthly: period_key='YYYY-MM' single month window.
    quarterly (R9-B.5): period_key='YYYY-QX' label + period_keys=['YYYY-MM',
      ...] (1~3개). window = [첫 month 1일, 마지막 month 말일].
    custom: caller 가 window_start/end/as_of_date 를 명시해야 한다.
    """
    if period_type == "monthly":
        ws = window_start or _month_start_date(period_key) or ""
        we = window_end or _month_end_date(period_key) or ""
        aod = as_of_date or we
        resolved_keys = [period_key]
    elif period_type == "quarterly":
        # period_keys 명시 우선, 없으면 period_key (예 '2026-Q1') 로부터 자동
        # 도출. 둘 다 부재 → 에러.
        if period_keys:
            resolved_keys = list(period_keys)
        else:
            resolved_keys = _quarter_to_period_keys(period_key)
        if not resolved_keys:
            raise ValueError(
                "quarterly period_type requires non-empty period_keys"
            )
        # sort for deterministic window. month start of first, month end of last.
        sorted_keys = sorted(resolved_keys)
        first, last = sorted_keys[0], sorted_keys[-1]
        ws = window_start or _month_start_date(first) or ""
        we = window_end or _month_end_date(last) or ""
        aod = as_of_date or we
        resolved_keys = sorted_keys
    elif period_type == "custom":
        ws = window_start or ""
        we = window_end or ""
        aod = as_of_date or we
        resolved_keys = period_keys or ([period_key] if period_key else [])
    else:
        raise ValueError(
            f"unsupported period_type: {period_type!r} "
            f"(expected 'monthly' | 'quarterly' | 'custom')"
        )
    return {
        "period_type": period_type,
        "period_key": period_key,
        "period_keys": resolved_keys,
        "window_start": ws,
        "window_end": we,
        "as_of_date": aod,
        "source_cutoff_date": aod,
    }


def _periods_overlap(
    page_ws: str | None, page_we: str | None,
    req_ws: str, req_we: str,
) -> bool:
    if not page_ws or not page_we:
        return False
    return page_ws <= req_we and page_we >= req_ws


# ──────────────────────────────────────────────────────────────────
# Frontmatter / body parser
# ──────────────────────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict, int]:
    """Very small YAML-ish frontmatter parser — strings/numbers/bool/list/null.

    Returns (dict, body_offset). 만약 frontmatter 가 없으면 ({}, 0).
    body_offset 은 frontmatter 종료 바로 다음 줄의 인덱스.
    """
    if not text.startswith("---"):
        return {}, 0
    end = text.find("\n---", 4)
    if end < 0:
        return {}, 0
    fm_text = text[3:end].strip("\n")
    body_offset = end + 4  # skip "\n---"
    if body_offset < len(text) and text[body_offset] == "\n":
        body_offset += 1

    out: dict = {}
    for line in fm_text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        # nested mapping (we ignore — keep top-level only)
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        # strip simple quotes
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
            out[k] = v
            continue
        # list literal
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            if not inner:
                out[k] = []
                continue
            items: list = []
            for raw in inner.split(","):
                t = raw.strip()
                if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
                    t = t[1:-1]
                items.append(t)
            out[k] = items
            continue
        # bool / null
        lv = v.lower()
        if lv in ("true", "false"):
            out[k] = (lv == "true")
            continue
        if lv in ("null", "none", "~", ""):
            out[k] = None if lv != "" else ""
            continue
        # number
        try:
            if "." in v:
                out[k] = float(v)
            else:
                out[k] = int(v)
            continue
        except ValueError:
            pass
        out[k] = v
    return out, body_offset


def _filename_period(name: str) -> str | None:
    m = _FILENAME_PERIOD_RE.search(name)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}"


def _excerpt_body(text: str, body_offset: int, max_chars: int) -> str:
    body = text[body_offset:].strip()
    if len(body) <= max_chars:
        return body
    return body[:max_chars].rstrip() + " …"


def _extract_title(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _parse_affected_assets_from_body(body: str) -> list[str]:
    """`## Affected Assets` 섹션의 첫 토큰들 추출 (08_Claims body 패턴)."""
    out: list[str] = []
    in_section = False
    for line in body.splitlines():
        s = line.strip()
        if s.lower().startswith("## affected assets"):
            in_section = True
            continue
        if in_section:
            if s.startswith("## "):
                break
            if s.startswith("- "):
                core = s[2:]
                # "원자재금: positive"
                head = core.split(":", 1)[0].strip()
                if head and head != "(없음)":
                    out.append(head)
    return out


# Body 에 들어오는 group_id pattern. R9-A.14 G1 정의: group:{period}:{md5[:10]}.
_RELATED_GROUP_ID_RE = re.compile(r"group:\d{4}-\d{2}:[0-9a-f]{10}")


def _parse_related_group_ids_from_body(body: str) -> list[str]:
    """`## Related Stable Lineage` 섹션의 `- related_group_id[s]: ...` 추출.

    R9-A.21A dual-anchor lineage linking 이 도입한 body 블록 컨벤션을 위한
    fallback parser. frontmatter `related_group_ids` 가 비어 있을 때만
    호출되도록 caller 가 분기 (frontmatter 우선 원칙).

    지원 형태:
      - `- related_group_id: group:2026-04:cfee0ff342`        (singular)
      - `- related_group_ids: ["group:...", "group:..."]`     (plural list)
      - `- related_group_ids: group:..., group:...`           (plural CSV)

    section 안에 등장한 모든 `group:YYYY-MM:hash10` 패턴을 dedup 보존순으로
    반환. section 외부의 group_id 는 무시 (대량 graph excerpt 가 noise 가
    되지 않도록).
    """
    if not body:
        return []
    in_section = False
    out: list[str] = []
    seen: set[str] = set()
    for line in body.splitlines():
        s = line.strip()
        if not in_section:
            # heading match: "## Related Stable Lineage" — case insensitive,
            # tolerate trailing spaces/anchors.
            if s.lower().startswith("## related stable lineage"):
                in_section = True
            continue
        # in section
        if s.startswith("## "):
            break
        if not s.startswith("- "):
            continue
        item = s[2:].lstrip()
        key, _, _ = item.partition(":")
        key_l = key.strip().lower()
        if key_l not in ("related_group_id", "related_group_ids"):
            continue
        # Pattern match instead of structured parse — Robust to JSON-ish,
        # CSV, single-quoted, or bare values.
        for m in _RELATED_GROUP_ID_RE.findall(item):
            if m not in seen:
                seen.add(m)
                out.append(m)
    return out


def parse_wiki_page(
    path: Path, *,
    body_excerpt_chars: int = DEFAULT_BODY_EXCERPT_CHARS,
    wiki_root: Path | None = None,
) -> WikiPageRecord | None:
    """단일 wiki page → WikiPageRecord. 읽기 실패 시 None.

    wiki_root 가 명시되면 그 root 기준 relative path 로 directory 추출.
    기본은 module-level WIKI_ROOT. 테스트의 synthetic wiki tree 에서
    필수.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    fm, body_off = _parse_frontmatter(text)
    body = text[body_off:]
    excerpt = _excerpt_body(text, body_off, body_excerpt_chars)
    title = _extract_title(body)

    root = wiki_root or WIKI_ROOT
    try:
        rel = str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        rel = path.name
    directory = rel.split("/", 1)[0] if "/" in rel else ""
    page_type = _DIR_TO_TYPE.get(directory, str(fm.get("type") or fm.get("page_type") or ""))
    source_type = _DIR_TO_SOURCE_TYPE.get(directory, "unknown")

    # Date fields — frontmatter 우선
    fm_period = fm.get("period_key") or fm.get("period")
    fm_window_start = fm.get("window_start")
    fm_window_end = fm.get("window_end")
    fm_as_of = fm.get("as_of_date")
    fm_cutoff = fm.get("source_cutoff_date")
    # NOTE: `updated_at` 은 selection 기준으로 쓰지 않는다 (design doc §1.4).
    # 파일 수정시각이라 daily_update 재실행만으로 미래로 점프할 수 있음.
    # available_from 은 semantic 타임스탬프 (generated_at/promoted_at/debate_date)
    # 만 사용. 없으면 None → cutoff 검사만 적용.
    fm_available = (
        fm.get("available_from")
        or fm.get("generated_at")
        or fm.get("promoted_at")
        or fm.get("debate_date")
    )

    used_fallback = False
    period_key: str | None = str(fm_period) if fm_period else None
    if not period_key:
        period_key = _filename_period(path.name)
        if period_key:
            used_fallback = True

    window_start = str(fm_window_start) if fm_window_start else None
    window_end = str(fm_window_end) if fm_window_end else None
    if (window_start is None or window_end is None) and period_key:
        window_start = window_start or _month_start_date(period_key)
        window_end = window_end or _month_end_date(period_key)
        used_fallback = used_fallback or (
            fm_window_start is None or fm_window_end is None
        )
    as_of_date = str(fm_as_of) if fm_as_of else (window_end if window_end else None)
    source_cutoff_date = str(fm_cutoff) if fm_cutoff else as_of_date
    available_from = str(fm_available) if fm_available else None

    claim_id = fm.get("claim_id")
    canonical_group_id = fm.get("canonical_group_id")
    # frontmatter 우선 — `related_group_ids` (plural) / `related_group_id`
    # (singular) 둘 다 인식. 비어 있고 08_Claims 페이지면 R9-A.21A 의 body
    # `## Related Stable Lineage` 블록을 fallback 으로 파싱.
    related = fm.get("related_group_ids")
    if related is None:
        related = fm.get("related_group_id")
    if isinstance(related, list):
        related_ids = [str(r) for r in related if r]
    elif isinstance(related, str) and related:
        related_ids = [related]
    else:
        related_ids = []
    if not related_ids and directory == "08_Claims":
        related_ids = _parse_related_group_ids_from_body(body)
    promotion_rule = fm.get("promotion_rule")

    affected: list[str] = []
    fm_aa = fm.get("affected_assets")
    if isinstance(fm_aa, list):
        affected = [str(a) for a in fm_aa]
    elif directory == "08_Claims":
        affected = _parse_affected_assets_from_body(body)

    return WikiPageRecord(
        path=rel,
        directory=directory,
        page_type=page_type,
        source_type=source_type,
        title=title,
        frontmatter=fm,
        body_excerpt=excerpt,
        period_key=period_key,
        window_start=window_start,
        window_end=window_end,
        as_of_date=as_of_date,
        source_cutoff_date=source_cutoff_date,
        available_from=available_from,
        claim_id=str(claim_id) if claim_id else None,
        canonical_group_id=str(canonical_group_id) if canonical_group_id else None,
        related_group_ids=related_ids,
        affected_assets=affected,
        promotion_rule=str(promotion_rule) if promotion_rule else None,
        used_filename_fallback=used_fallback,
    )


# ──────────────────────────────────────────────────────────────────
# Directory scanning
# ──────────────────────────────────────────────────────────────────

def _list_pages_in_dir(directory: str, wiki_root: Path | None = None) -> list[Path]:
    root = wiki_root or WIKI_ROOT
    d = root / directory
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.md") if p.is_file())


def _is_production_claim_page(name: str) -> bool:
    """Filter out replay variants (e.g. `*.r9a4-replay.md`).

    Production page filename: `{period}_claim_{hash10}.md` — no extra suffix.
    Anything with an extra dot-suffix before `.md` is a target_suffix variant.
    """
    if not name.endswith(".md"):
        return False
    stem = name[:-3]
    # production: 2026-04_claim_xxxxxxxxxx
    # variant:    2026-04_claim_xxxxxxxxxx.r9a4-replay
    return stem.count(".") == 0


def _select_pages_for_window(
    directory: str,
    request_window: dict,
    *,
    builder_run_time: str,
    body_excerpt_chars: int,
    wiki_root: Path | None = None,
) -> tuple[list[WikiPageRecord], dict]:
    """Read directory, parse, apply date-window filter. Returns
    (window_passed_records, stats).

    Note: This is **pre-cap** — global ``max_pages`` is enforced later by
    ``_apply_global_cap``. ``stats['window_passed']`` is the count after
    filters; ``stats['final_selected']`` is filled by caller after
    cap+priority+round-robin.
    """
    records: list[WikiPageRecord] = []
    stats = {
        "considered": 0,
        "window_passed": 0,
        "final_selected": 0,
        "skipped_window_miss": 0,
        "skipped_cutoff_violation": 0,
        "skipped_available_from_future": 0,
        "skipped_unparseable": 0,
        "skipped_non_production": 0,
        "fallback_count": 0,
    }
    for fp in _list_pages_in_dir(directory, wiki_root):
        # 08_Claims 는 replay variant 가 폭증 — production filename 만.
        if directory == "08_Claims" and not _is_production_claim_page(fp.name):
            stats["skipped_non_production"] += 1
            continue
        rec = parse_wiki_page(
            fp, body_excerpt_chars=body_excerpt_chars, wiki_root=wiki_root,
        )
        if rec is None:
            stats["skipped_unparseable"] += 1
            continue
        stats["considered"] += 1

        if directory in _PERIOD_AGNOSTIC_DIRS:
            # period-agnostic: as_of cutoff 만 본다 (window 자체가 없음).
            if rec.source_cutoff_date and rec.source_cutoff_date > request_window["as_of_date"]:
                stats["skipped_cutoff_violation"] += 1
                continue
        else:
            if not _periods_overlap(
                rec.window_start, rec.window_end,
                request_window["window_start"], request_window["window_end"],
            ):
                stats["skipped_window_miss"] += 1
                continue
            if rec.source_cutoff_date and rec.source_cutoff_date > request_window["as_of_date"]:
                stats["skipped_cutoff_violation"] += 1
                continue
        if _is_future_relative(rec.available_from, builder_run_time):
            stats["skipped_available_from_future"] += 1
            continue
        if rec.used_filename_fallback:
            stats["fallback_count"] += 1
        records.append(rec)
        stats["window_passed"] += 1
    return records, stats


# ──────────────────────────────────────────────────────────────────
# Entry rendering + global cap helpers
# ──────────────────────────────────────────────────────────────────

def _rec_to_entry(directory: str, rec: WikiPageRecord) -> dict:
    """WikiPageRecord → context_pack entry dict (uniform per-bucket schema)."""
    entry: dict = {
        "page_id": _make_page_id(directory, rec),
        "path": rec.path,
        "page_type": rec.page_type,
        "title": rec.title,
        "window_start": rec.window_start,
        "window_end": rec.window_end,
        "as_of_date": rec.as_of_date,
        "source_cutoff_date": rec.source_cutoff_date,
        "available_from": rec.available_from,
        "excerpt": rec.body_excerpt,
        "source_type": rec.source_type,
        "frontmatter_keys": sorted(rec.frontmatter.keys()),
    }
    if directory == "08_Claims":
        entry["claim_id"] = rec.claim_id
        entry["canonical_group_id"] = rec.canonical_group_id
        entry["related_group_ids"] = rec.related_group_ids
        entry["affected_assets"] = rec.affected_assets
        entry["promotion_rule"] = rec.promotion_rule
    return entry


def _apply_global_cap(
    *,
    max_pages: int,
    fund_pinned: dict | None,
    claim_entries: list[dict],
    candidates_by_dir: dict[str, list[WikiPageRecord]],
    include_debate_memory: bool,
) -> dict:
    """Global ``max_pages`` cap + priority reservation + round-robin fill.

    Priority (workorder §"권장 selection priority"):

    1. ``fund_pinned`` (fund_comment stage contract — 1 page)
    2. ``08_Claims`` joined (claim_store rank: confidence × salience desc)
    3. Round-robin from ``_FILL_PRIORITY_DIRS``
       (07_Graph_Evidence > 05_Regime_Canonical > 01_Events > 03_Assets
       > 02_Entities)
    4. If ``include_debate_memory`` → 06_Debate_Memory at the end

    Returns dict with per-dir selected entries + summary counts.
    """
    out_events: list[dict] = []
    out_entities: list[dict] = []
    out_assets: list[dict] = []
    out_regime: list[dict] = []
    out_graph: list[dict] = []
    out_claims: list[dict] = []
    out_debate_memory: list[dict] = []
    out_fund: dict | None = None
    selected_paths: list[str] = []
    source_type_counts: dict[str, int] = {}
    selected_by_dir: dict[str, int] = {}
    total = 0

    def _route(directory: str, entry: dict) -> None:
        nonlocal total, out_fund
        if directory == "01_Events":
            out_events.append(entry)
        elif directory == "02_Entities":
            out_entities.append(entry)
        elif directory == "03_Assets":
            out_assets.append(entry)
        elif directory == "04_Funds":
            out_fund = entry
        elif directory == "05_Regime_Canonical":
            out_regime.append(entry)
        elif directory == "06_Debate_Memory":
            out_debate_memory.append(entry)
        elif directory == "07_Graph_Evidence":
            out_graph.append(entry)
        elif directory == "08_Claims":
            out_claims.append(entry)
        selected_paths.append(entry["path"])
        st = entry.get("source_type") or "unknown"
        source_type_counts[st] = source_type_counts.get(st, 0) + 1
        selected_by_dir[directory] = selected_by_dir.get(directory, 0) + 1
        total += 1

    # Phase 1 — fund_pinned (fund_comment contract)
    if fund_pinned is not None and total < max_pages:
        _route("04_Funds", fund_pinned)

    # Phase 2 — claims (priority #1 in workorder)
    for ce in claim_entries:
        if total >= max_pages:
            break
        _route("08_Claims", ce)

    # Phase 3 — round-robin priority dirs
    fill_dirs: list[str] = [
        d for d in _FILL_PRIORITY_DIRS if d in candidates_by_dir
    ]
    if include_debate_memory and "06_Debate_Memory" in candidates_by_dir:
        fill_dirs.append("06_Debate_Memory")
    # Build pools (preserve _select_pages_for_window order — alphabetical).
    pools: dict[str, list[WikiPageRecord]] = {
        d: list(candidates_by_dir.get(d, [])) for d in fill_dirs
    }
    # B Gate4 — 01_Events 는 알파벳 대신 자산군 stratified(milestone 우선)로 재배열.
    if "01_Events" in pools:
        pools["01_Events"] = _reorder_event_records_asset_stratified(pools["01_Events"])
    while total < max_pages:
        added_this_round = False
        for d in fill_dirs:
            if total >= max_pages:
                break
            if pools[d]:
                rec = pools[d].pop(0)
                _route(d, _rec_to_entry(d, rec))
                added_this_round = True
        if not added_this_round:
            break

    return {
        "events": out_events,
        "entities": out_entities,
        "assets": out_assets,
        "regime": out_regime,
        "graph": out_graph,
        "claims": out_claims,
        "debate_memory": out_debate_memory,
        "fund_page": out_fund,
        "selected_paths": selected_paths,
        "source_type_counts": source_type_counts,
        "selected_by_dir": selected_by_dir,
        "total_selected": total,
    }


# ──────────────────────────────────────────────────────────────────
# Claim store integration
# ──────────────────────────────────────────────────────────────────

def _load_claim_store_passing(
    period_key: str, *,
    claims_dir: Path | None = None,
) -> list[dict]:
    """Load canonical claim store for period and apply local Rule A/B.

    Decoupled from ``market_research.analyze.claim_store.select_promoted_claims_for_period``
    — that function transitively imports pymysql via wiki package and silently
    returns [] when the env lacks pymysql. We read the JSON directly.
    """
    if claims_dir is None:
        claims_dir = WIKI_ROOT.parent / "claims"
    fp = claims_dir / f"{period_key}.json"
    if not fp.exists():
        return []
    try:
        store = json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    claims = store.get("claims") if isinstance(store, dict) else None
    if not isinstance(claims, list):
        return []
    out: list[dict] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        if _meets_rule_a_local(c) or _meets_rule_b_local(c):
            out.append(c)
            continue
        # R9-B.6C — Rule C (force) surface. canonical store metadata 의
        # optional `promotion_rule` 필드가 "C" 인 경우 read-side 도 인정
        # (claim_store.select_promoted_claims_for_period 와 동일 정책).
        pr = c.get("promotion_rule")
        if isinstance(pr, str) and pr.strip().upper() == "C":
            out.append(c)
    return out


def _claim_id_to_filename(claim_id: str) -> str | None:
    """`claim:2026-04:e78dc83a1e` → `2026-04_claim_e78dc83a1e.md`."""
    if not isinstance(claim_id, str) or not claim_id.startswith("claim:"):
        return None
    parts = claim_id.split(":")
    if len(parts) != 3:
        return None
    _, period, h = parts
    if not period or not h:
        return None
    return f"{period}_claim_{h}.md"


def _build_claim_section(
    *,
    period_keys: list[str],
    wiki_root: Path,
    claims_dir: Path | None = None,
    body_excerpt_chars: int,
    builder_run_time: str,
    request_window: dict,
) -> tuple[list[dict], dict]:
    """claim_store selected + wiki 08_Claims 매칭 → claim entries + trace.

    R9-B.5 multi-month union: period_keys list 의 각 monthly store 를 순차
    load 하고, dedup-by-claim_id 보존순으로 합친다. monthly path 도
    동일 코드를 거치며 (period_keys=[그 month]) regression-free.

    Returns (claim_entries, trace_dict). trace 는 selected/matched count,
    join rate, related_group_ids, source_cutoff_violations 포함.
    """
    # Phase 1 — load + dedup per (period, claim_id).
    selected_all: list[dict] = []
    seen_claim_ids: set[str] = set()
    per_period_selected_counts: dict[str, int] = {}
    for pk in period_keys:
        store = _load_claim_store_passing(pk, claims_dir=claims_dir)
        per_period_selected_counts[pk] = len(store)
        for c in store:
            cid = c.get("claim_id")
            if not cid or cid in seen_claim_ids:
                continue
            seen_claim_ids.add(cid)
            selected_all.append(c)

    selected_ids = [c.get("claim_id") for c in selected_all if c.get("claim_id")]
    claim_entries: list[dict] = []
    matched = 0
    related_group_ids: list[str] = []
    cutoff_violations = 0
    warnings: list[dict] = []

    for c in selected_all:
        cid = c.get("claim_id")
        if not cid:
            continue
        fname = _claim_id_to_filename(cid)
        if not fname:
            continue
        page_path = wiki_root / "08_Claims" / fname
        if not page_path.exists():
            warnings.append({
                "warning_type": "claim_wiki_missing",
                "claim_id": cid,
                "expected_path": f"08_Claims/{fname}",
            })
            continue
        rec = parse_wiki_page(
            page_path, body_excerpt_chars=body_excerpt_chars,
            wiki_root=wiki_root,
        )
        if rec is None:
            warnings.append({
                "warning_type": "claim_wiki_unparseable",
                "claim_id": cid,
                "path": f"08_Claims/{fname}",
            })
            continue
        # date hygiene
        if rec.source_cutoff_date and rec.source_cutoff_date > request_window["as_of_date"]:
            cutoff_violations += 1
            warnings.append({
                "warning_type": "source_cutoff_violation",
                "path": rec.path,
                "source_cutoff_date": rec.source_cutoff_date,
                "request_as_of": request_window["as_of_date"],
            })
            continue
        if _is_future_relative(rec.available_from, builder_run_time):
            warnings.append({
                "warning_type": "available_from_future",
                "path": rec.path,
                "available_from": rec.available_from,
                "builder_run_time": builder_run_time,
            })
            continue
        if rec.used_filename_fallback:
            warnings.append({
                "warning_type": "frontmatter_missing_date_fields",
                "path": rec.path,
            })
        related_group_ids.extend(rec.related_group_ids)
        matched += 1
        # page_id 의 period 는 claim_id 에 내장된 period (cid 의 가운데 토큰).
        claim_period = cid.split(":")[1] if cid.count(":") == 2 else "?"
        claim_entries.append({
            "page_id": f"claim:{claim_period}:{cid.rsplit(':', 1)[-1]}",
            "path": rec.path,
            "claim_id": cid,
            "canonical_group_id": rec.canonical_group_id,
            "related_group_ids": rec.related_group_ids,
            "promotion_rule": rec.promotion_rule,
            "title": rec.title,
            "affected_assets": rec.affected_assets,
            "store_confidence": c.get("confidence"),
            "store_salience": c.get("salience"),
            "store_claim_type": c.get("claim_type"),
            "store_supporting_evidence_ids": c.get("supporting_evidence_ids") or [],
            "window_start": rec.window_start,
            "window_end": rec.window_end,
            "as_of_date": rec.as_of_date,
            "source_cutoff_date": rec.source_cutoff_date,
            "excerpt": rec.body_excerpt,
            "source_type": "claim_memory",
        })

    selected_count = len(selected_ids)
    join_rate: float | None
    if selected_count == 0:
        join_rate = None  # n/a
        warnings.append({
            "warning_type": "claim_store_zero_selected",
            "period_keys": list(period_keys),
            "note": (
                "claim_store 에서 Rule A/B 통과 claim 0. join rate 계산 불가. "
                "기존 운영 wiki 8개 page 와 무관 — store/promotion threshold "
                "issue. R9-A 트랙 후속과 별 트랙으로 진단 필요."
            ),
        })
    else:
        join_rate = matched / selected_count

    # dedup related_group_ids
    dedup_related = list(dict.fromkeys(related_group_ids))

    trace = {
        "selected_claim_ids": selected_ids,
        "matched_wiki_claim_count": matched,
        "claim_store_to_wiki_join_rate": join_rate,
        "selected_related_group_ids": dedup_related,
        "source_cutoff_violations": cutoff_violations,
        "warnings": warnings,
        # R9-B.5 per-period claim_store selection counts.
        "claim_store_selected_count_by_period": per_period_selected_counts,
    }
    # B Gate3 — 자산군 round-robin 재배열 (멤버십 불변, 순서만; 트림 시 자산 균형 보존).
    claim_entries = _reorder_claims_asset_roundrobin(claim_entries)
    return claim_entries, trace


# ──────────────────────────────────────────────────────────────────
# Stage gating
# ──────────────────────────────────────────────────────────────────

def _allowed_dirs(stage: str) -> tuple[str, ...]:
    if stage not in _STAGE_DIRS:
        raise ValueError(
            f"unknown stage: {stage!r} (expected one of "
            f"{list(_STAGE_DIRS)})"
        )
    return _STAGE_DIRS[stage]


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def build_wiki_context_pack(
    *,
    period_key: str,
    period_type: str = "monthly",
    period_keys: list[str] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    as_of_date: str | None = None,
    stage: str = "market_debate",
    fund_code: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    body_excerpt_chars: int = DEFAULT_BODY_EXCERPT_CHARS,
    include_debate_memory: bool = False,
    wiki_root: Path | None = None,
    builder_run_time: str | None = None,
) -> dict:
    """Build the wiki context pack (read-only).

    R9-B.5 — period_type='quarterly' 일 때:
      - period_key 가 'YYYY-QX' 면 _quarter_to_period_keys 로 자동 unpacking.
      - period_keys 가 명시되면 그 list 를 그대로 사용 (custom 범위).
      - window = [첫 month 1일, 마지막 month 말일].
      - claim_store 는 각 period_key 별 monthly store 를 union (dedup by
        claim_id, 보존순).
      - 01_Events/02_Entities/03_Assets/07_Graph_Evidence 는 분기 window
        overlap 기준으로 selection (기존 monthly window 로직 그대로).
      - 04_Funds pinned 은 fund_comment stage 에서만 — quarterly stage 는
        04_Funds 미허용.

    monthly path (default) 는 regression-free.
    See ``r9b_wiki_first_debate_architecture.md`` §8 for the schema.
    """
    root = wiki_root or WIKI_ROOT
    request_window = _resolve_request_window(
        period_key=period_key,
        period_type=period_type,
        window_start=window_start,
        window_end=window_end,
        as_of_date=as_of_date,
        period_keys=period_keys,
    )
    run_time = builder_run_time or datetime.now(timezone.utc).isoformat(timespec="seconds")
    allowed = _allowed_dirs(stage)
    if max_pages <= 0:
        raise ValueError(f"max_pages must be > 0, got {max_pages}")

    per_dir_stats: dict[str, dict] = {}
    overall_warnings: list[dict] = []
    total_considered = 0
    cutoff_violations_total = 0

    # ── Phase A: scan all non-claim, non-fund dirs for window-passing
    # candidates. NO max_pages applied yet (global cap applied later).
    scan_dirs = [
        d for d in (
            "01_Events", "02_Entities", "03_Assets",
            "05_Regime_Canonical", "07_Graph_Evidence",
        ) if d in allowed
    ]
    if include_debate_memory and "06_Debate_Memory" in allowed:
        scan_dirs.append("06_Debate_Memory")

    candidates_by_dir: dict[str, list[WikiPageRecord]] = {}
    for directory in scan_dirs:
        recs, stats = _select_pages_for_window(
            directory, request_window,
            builder_run_time=run_time,
            body_excerpt_chars=body_excerpt_chars,
            wiki_root=root,
        )
        per_dir_stats[directory] = stats
        total_considered += stats["considered"]
        cutoff_violations_total += stats["skipped_cutoff_violation"]
        if stats["fallback_count"] > 0:
            overall_warnings.append({
                "warning_type": "frontmatter_missing_date_fields",
                "directory": directory,
                "count": stats["fallback_count"],
            })
        candidates_by_dir[directory] = recs

    # ── Phase B: fund_pinned (fund_comment stage contract — pre-cap)
    fund_pinned_entry: dict | None = None
    if stage == "fund_comment" and "04_Funds" in allowed and fund_code:
        fname = f"{period_key}_{fund_code}.md"
        fp = root / "04_Funds" / fname
        per_dir_stats["04_Funds"] = {
            "considered": 0, "window_passed": 0, "final_selected": 0,
            "skipped_window_miss": 0, "skipped_cutoff_violation": 0,
            "skipped_available_from_future": 0, "skipped_unparseable": 0,
            "skipped_non_production": 0, "fallback_count": 0,
        }
        if fp.exists():
            per_dir_stats["04_Funds"]["considered"] = 1
            total_considered += 1
            rec = parse_wiki_page(
                fp, body_excerpt_chars=body_excerpt_chars, wiki_root=root,
            )
            if rec is not None:
                ok = True
                if rec.source_cutoff_date and rec.source_cutoff_date > request_window["as_of_date"]:
                    cutoff_violations_total += 1
                    per_dir_stats["04_Funds"]["skipped_cutoff_violation"] += 1
                    ok = False
                if ok and _is_future_relative(rec.available_from, run_time):
                    per_dir_stats["04_Funds"]["skipped_available_from_future"] += 1
                    ok = False
                if ok:
                    per_dir_stats["04_Funds"]["window_passed"] = 1
                    if rec.used_filename_fallback:
                        per_dir_stats["04_Funds"]["fallback_count"] = 1
                    fund_pinned_entry = {
                        "page_id": _make_page_id("04_Funds", rec),
                        "path": rec.path,
                        "fund_code": fund_code,
                        "title": rec.title,
                        "window_start": rec.window_start,
                        "window_end": rec.window_end,
                        "as_of_date": rec.as_of_date,
                        "excerpt": rec.body_excerpt,
                        "source_type": "fund_context",
                        "frontmatter_keys": sorted(rec.frontmatter.keys()),
                    }
        else:
            overall_warnings.append({
                "warning_type": "fund_page_not_found",
                "expected_path": f"04_Funds/{fname}",
                "fund_code": fund_code,
            })

    # ── Phase C: 08_Claims — store join. claim entries 는 store 우선순위
    # (confidence × salience desc) 그대로 보존 (raw 모두 — 캡은 Phase D).
    claims_section_entries: list[dict] = []
    claim_trace: dict = {
        "selected_claim_ids": [],
        "matched_wiki_claim_count": 0,
        "claim_store_to_wiki_join_rate": None,
        "selected_related_group_ids": [],
        "source_cutoff_violations": 0,
        "warnings": [],
    }
    if "08_Claims" in allowed:
        claims_section_entries, claim_trace = _build_claim_section(
            period_keys=request_window["period_keys"],
            wiki_root=root,
            claims_dir=(root.parent / "claims"),
            body_excerpt_chars=body_excerpt_chars,
            builder_run_time=run_time,
            request_window=request_window,
        )
        # claim wiki page 도 considered 카운트 (per-page traversal).
        per_dir_stats["08_Claims"] = {
            "considered": len(claims_section_entries),
            "window_passed": len(claims_section_entries),
            "final_selected": 0,  # filled after cap
            "skipped_window_miss": 0,
            "skipped_cutoff_violation": claim_trace.get("source_cutoff_violations", 0),
            "skipped_available_from_future": 0,
            "skipped_unparseable": 0,
            "skipped_non_production": 0,
            "fallback_count": 0,
        }
        total_considered += len(claims_section_entries)
        cutoff_violations_total += claim_trace.get("source_cutoff_violations", 0)
        overall_warnings.extend(claim_trace.get("warnings", []))

    # ── Phase D: global cap + priority reservation + round-robin
    selection = _apply_global_cap(
        max_pages=max_pages,
        fund_pinned=fund_pinned_entry,
        claim_entries=claims_section_entries,
        candidates_by_dir=candidates_by_dir,
        include_debate_memory=include_debate_memory,
    )
    market_events = selection["events"]
    market_entities = selection["entities"]
    market_assets = selection["assets"]
    market_regime = selection["regime"]
    market_graph = selection["graph"]
    market_claims = selection["claims"]
    debate_memory_entries = selection["debate_memory"]
    fund_page_entry = selection["fund_page"]
    selected_paths = selection["selected_paths"]
    source_type_counts = selection["source_type_counts"]
    selected_by_dir = selection["selected_by_dir"]
    total_selected = selection["total_selected"]

    # Backfill final_selected per_dir_stats (post-cap actual counts)
    for d, n in selected_by_dir.items():
        if d in per_dir_stats:
            per_dir_stats[d]["final_selected"] = n

    # Pack assembly
    pack = {
        "schema_version": SCHEMA_VERSION,
        "period_type": request_window["period_type"],
        "period_key": request_window["period_key"],
        # R9-B.5 — quarterly union 일 때 unpacked monthly keys 노출. monthly
        # path 도 [period_key] 형태로 일관 노출.
        "period_keys": request_window["period_keys"],
        "window_start": request_window["window_start"],
        "window_end": request_window["window_end"],
        "as_of_date": request_window["as_of_date"],
        "stage": stage,
        "fund_code": fund_code,
        "mode": MODE,
        "generated_at": run_time,
        "debate_run_id": None,
        "market_context": {
            "events": market_events,
            "entities": market_entities,
            "assets": market_assets,
            "regime": market_regime,
            "graph_evidence": market_graph,
            "claims": market_claims,
        },
        "fund_context": {
            "fund_page": fund_page_entry,
            "fund_claims": [],            # R9-B.2: schema 자리만 (B4+)
            "fund_asset_exposures": [],
        },
        "prior_memory": {
            "debate_memory": debate_memory_entries,
            "include_policy": ("summary_only" if include_debate_memory else "disabled"),
        },
        "validation_pack": {
            "raw_sources_used": [],       # R9-B.2: pack 단독 호출. B4+ 에서 채움.
            "numeric_guardrails": [],
            "source_cutoff_date": request_window["source_cutoff_date"],
        },
        "source_trace": {
            "wiki_pages_considered": total_considered,
            "wiki_pages_selected": total_selected,
            "selected_wiki_paths": selected_paths,
            "selected_by_directory": selected_by_dir,
            "source_type_counts": source_type_counts,
            "selected_claim_ids": claim_trace["selected_claim_ids"],
            "selected_related_group_ids": claim_trace["selected_related_group_ids"],
            "claim_store_selected_count": len(claim_trace["selected_claim_ids"]),
            "matched_wiki_claim_count": claim_trace["matched_wiki_claim_count"],
            "claim_store_to_wiki_join_rate": claim_trace["claim_store_to_wiki_join_rate"],
            "source_cutoff_violations": cutoff_violations_total,
            "per_dir_stats": per_dir_stats,
            # R9-B.5 — per-period claim_store size (quarterly union 분포).
            "claim_store_selected_count_by_period": claim_trace.get(
                "claim_store_selected_count_by_period", {},
            ),
        },
        "warnings": overall_warnings,
    }
    return pack


def _make_page_id(directory: str, rec: WikiPageRecord) -> str:
    """Generate a stable page_id."""
    if directory == "08_Claims" and rec.claim_id:
        return rec.claim_id
    if directory == "05_Regime_Canonical":
        return f"regime:{rec.path}"
    if directory == "04_Funds":
        return f"fund:{rec.period_key or '?'}:{rec.path.rsplit('/', 1)[-1].rstrip('.md')}"
    # 01/02/03/06/07 — period + file stem
    stem = rec.path.rsplit("/", 1)[-1].removesuffix(".md")
    return f"{rec.page_type}:{rec.period_key or '?'}:{stem}"


__all__ = [
    "build_wiki_context_pack",
    "parse_wiki_page",
    "WikiPageRecord",
    "SCHEMA_VERSION",
]
