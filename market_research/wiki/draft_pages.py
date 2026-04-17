# -*- coding: utf-8 -*-
"""Base wiki pages — event / entity / asset / fund.

Generated right after refine (Step 2.5): dedupe + salience + classify done.
These are "base" pages (01~04) — factual aggregation only.

**Must not** include regime narrative, debate interpretation, or graph
transmission paths. Canonical regime lives in 05_; debate memory in 06_;
graph evidence in 07_.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from market_research.wiki.paths import (
    EVENTS_DIR, ENTITIES_DIR, ASSETS_DIR, FUNDS_DIR, INDEX_DIR,
)

BASE_DIR = Path(__file__).resolve().parent.parent
NEWS_DIR = BASE_DIR / 'data' / 'news'

# 간단 자산/펀드 맵 — constants에서 불러올 수도 있지만 draft는 샘플 수준
_ASSET_TOPIC_MAP = {
    '국내주식': ['경기_소비', '부동산'],
    '해외주식': ['테크_AI_반도체', '경기_소비'],
    '채권': ['금리_채권', '통화정책'],
    '원자재': ['에너지_원자재'],
    '금': ['귀금속_금'],
    '환율': ['환율_FX', '달러_글로벌유동성'],
}

_SAFE_CHARS = re.compile(r'[^\w가-힣_.-]')


def _safe_filename(name: str, maxlen: int = 80) -> str:
    s = _SAFE_CHARS.sub('_', name.strip())[:maxlen]
    return s or 'unknown'


def _load_month_articles(month_str: str) -> list[dict]:
    f = NEWS_DIR / f'{month_str}.json'
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        return []
    return data.get('articles', [])


# ══════════════════════════════════════════
# Event page (event_group_id 단위)
# ══════════════════════════════════════════

def write_event_page(event_id: str, articles: list[dict], month_str: str) -> Path:
    if not articles:
        return None
    top = max(articles, key=lambda a: a.get('_event_salience', 0))
    topics = Counter()
    sources = Counter()
    for a in articles:
        for t in a.get('_classified_topics', []):
            tn = t.get('topic', '')
            if tn:
                topics[tn] += 1
        s = a.get('source', '')
        if s:
            sources[s] += 1
    avg_sal = round(sum(a.get('_event_salience', 0) for a in articles) / len(articles), 3)

    lines = [
        '---',
        'type: event',
        'status: draft',
        f'event_id: {event_id}',
        f'period: {month_str}',
        f'source_count: {len(articles)}',
        f'avg_salience: {avg_sal}',
        f'top_topics: [{", ".join(chr(34)+t+chr(34) for t, _ in topics.most_common(3))}]',
        'source_of_truth: pipeline_refine',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
        f'# Event {event_id}',
        '',
        f'**Primary headline**: {top.get("title", "(제목 없음)")}',
        f'**Primary source**: {top.get("source", "")} / {top.get("date", "")}',
        f'**URL**: {top.get("url", "")}',
        '',
        '## Statistics',
        f'- 기사 수: {len(articles)}',
        f'- 평균 salience: {avg_sal}',
        f'- 주요 토픽: {", ".join(t for t, _ in topics.most_common(5)) or "(미분류)"}',
        f'- 매체 구성: {", ".join(f"{s}({n})" for s, n in sources.most_common(5))}',
        '',
        '## Articles',
    ]
    for a in sorted(articles, key=lambda x: -x.get('_event_salience', 0))[:10]:
        lines.append(
            f'- [{a.get("date", "")}] **{a.get("source", "")}** '
            f'(sal={a.get("_event_salience", 0):.2f}): {a.get("title", "")}'
        )
    lines += ['', '> Base page — regime/debate 해석 금지. 사실 집계만 기록.']

    out = EVENTS_DIR / f'{month_str}_{_safe_filename(event_id)}.md'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return out


# ══════════════════════════════════════════
# Entity page (v13 redesign — confirmed / draft 섹션 분리)
# ══════════════════════════════════════════
#
# Page lifecycle status stays at `base` (no new status values).
# The separation is made inside the body via section headers and source
# badges, so pages stay stable across rebuilds and ids are preserved.

def _reverse_asset_topic_map() -> dict[str, list[str]]:
    rev: dict[str, list[str]] = defaultdict(list)
    for asset, topics in _ASSET_TOPIC_MAP.items():
        for t in topics:
            rev[t].append(asset)
    return dict(rev)


def _related_asset_classes_for(label: str) -> list[str]:
    """Resolve label → taxonomy tag → asset classes. Empty list when no hit."""
    try:
        from market_research.wiki.taxonomy import extract_taxonomy_tags
    except Exception:
        return []
    tags, _ = extract_taxonomy_tags(label)
    if not tags:
        return []
    reverse = _reverse_asset_topic_map()
    out: list[str] = []
    seen: set = set()
    for t in tags:
        for a in reverse.get(t, []):
            if a not in seen:
                seen.add(a)
                out.append(a)
    return out


def _graph_adjacency_for(node_id: str | None,
                         edges: list[dict] | None,
                         limit: int = 5) -> list[dict]:
    if not node_id or not edges:
        return []
    out: list[dict] = []
    for e in edges:
        frm = e.get('from')
        to = e.get('to')
        if frm == node_id:
            direction = 'out'
            neighbor = to
        elif to == node_id:
            direction = 'in'
            neighbor = frm
        else:
            continue
        out.append({
            'neighbor': neighbor,
            'direction': direction,
            'relation': e.get('relation') or '',
            'weight': float(e.get('effective_score')
                            or e.get('weight') or 0),
        })
    out.sort(key=lambda x: -x['weight'])
    return out[:limit]


def _paths_involving(node_label: str,
                     node_id: str | None,
                     transmission_paths: list[dict] | None,
                     limit: int = 5) -> list[dict]:
    if not transmission_paths:
        return []
    nl = (node_label or '').strip()
    nid = (node_id or '').strip()
    matched: list[dict] = []
    for p in transmission_paths:
        trig = str(p.get('trigger') or '')
        tgt = str(p.get('target') or '')
        labels = p.get('path_labels') or p.get('path') or []
        hit_in_path = any(
            nl and (nl == s or nl in s or s in nl)
            for s in labels
        )
        if (nl and (nl == trig or nl == tgt)) \
                or (nid and (nid == trig or nid == tgt)) \
                or hit_in_path:
            matched.append(p)
    # stable order: highest confidence first
    matched.sort(key=lambda p: -float(p.get('confidence') or 0))
    return matched[:limit]


def write_entity_page(entity_id: str, label: str, topic: str,
                      mentioned_in: list[str], month_str: str,
                      graph_node_id: str | None = None,
                      canonical_entity_label: str | None = None,
                      linked_events: list[str] | None = None,
                      adjacent_nodes: list[dict] | None = None,
                      paths_involving: list[dict] | None = None,
                      graph_node_meta: dict | None = None) -> Path:
    """Render an entity page with Confirmed / Draft evidence separation.

    Confirmed facts — sourced from ``pipeline_refine``:
      mention count, linked events, related asset classes (derived),
      recent article titles.

    Draft evidence — sourced from ``07_Graph_Evidence`` (GraphRAG P1):
      adjacent graph nodes (top 5) and transmission paths that involve
      this node. This section ALWAYS carries the draft badge so callers
      cannot mistake it for canonical regime signal.

    Media entities (no ``graph_node_id``) gracefully render an empty
    draft section with a "not applicable" note.

    frontmatter stays at ``status: base``. Two optional helper fields
    (``has_draft_evidence``, ``draft_sources``) signal to downstream
    readers whether the draft block carried any content.
    """
    linked_events = linked_events or []
    adjacent_nodes = adjacent_nodes or []
    paths_involving = paths_involving or []
    has_draft = bool(adjacent_nodes or paths_involving)
    draft_sources = ['graph_evidence'] if has_draft else []

    frontmatter: list[str] = [
        '---',
        'type: entity',
        'status: base',
        f'entity_id: {entity_id}',
        f'label: "{label}"',
        f'topic: {topic}',
        f'period: {month_str}',
    ]
    if graph_node_id:
        frontmatter.append(f'graph_node_id: {graph_node_id}')
    if canonical_entity_label:
        frontmatter.append(f'canonical_entity_label: "{canonical_entity_label}"')
    if linked_events:
        frontmatter.append(
            'linked_events: [' + ', '.join(linked_events[:5]) + ']'
        )
    frontmatter.append(
        'has_draft_evidence: ' + ('true' if has_draft else 'false')
    )
    if draft_sources:
        frontmatter.append(
            'draft_sources: [' + ', '.join(draft_sources) + ']'
        )
    frontmatter += [
        'source_of_truth: pipeline_refine',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
    ]

    # ── severity proxy for Provenance ──
    severity_str = '—'
    if graph_node_meta:
        sev_weight = graph_node_meta.get('severity_weight')
        if sev_weight is not None:
            try:
                severity_str = f'{float(sev_weight):.2f}'
            except (TypeError, ValueError):
                pass
        if severity_str == '—':
            sev_label = graph_node_meta.get('severity')
            if sev_label:
                severity_str = str(sev_label)

    related_assets = _related_asset_classes_for(label)
    canon = canonical_entity_label or label

    header_topic = f'**Topic**: `{topic}`'
    if graph_node_id:
        header_topic += f' · **Graph node**: `{graph_node_id}`'

    body: list[str] = [
        f'# Entity — {label}',
        '',
        f'**Canonical label**: `{canon}`  ',
        header_topic,
        '',
        '## Confirmed facts  _[source: `pipeline_refine`]_',
        '',
        f'- Mentioned in **{len(mentioned_in)}** articles this period',
    ]
    if linked_events:
        body.append(
            '- Linked events: '
            + ', '.join(f'`{e}`' for e in linked_events[:5])
        )
    else:
        body.append('- Linked events: —')
    if related_assets:
        body.append(
            '- Related asset classes (derived): '
            + ', '.join(f'`{a}`' for a in related_assets)
        )
    else:
        body.append('- Related asset classes (derived): —')
    body.append('- Related funds: —  _(populated in a later batch)_')
    body += ['', '### Recent articles']
    if mentioned_in:
        for t in mentioned_in[:8]:
            body.append(f'- {t}')
    else:
        body.append('- _No articles matched this entity this period._')

    # ── Draft evidence ──
    body += [
        '',
        '## Draft evidence  _[source: `07_Graph_Evidence` · draft]_',
        '',
        '> Adjacency and transmission paths below are **draft evidence** produced',
        '> by GraphRAG. Do NOT treat as confirmed regime signal.',
        '> Canonical regime lives in `05_Regime_Canonical/`.',
        '',
        '### Graph adjacency (top 5)',
    ]
    if adjacent_nodes:
        for a in adjacent_nodes:
            arrow = '→' if a.get('direction') == 'out' else '←'
            rel = a.get('relation') or '—'
            body.append(
                f'- {arrow} `{a.get("neighbor")}`  '
                f'({rel}, w={a.get("weight", 0):.2f})'
            )
    elif graph_node_id:
        body.append('- _No adjacent edges recorded this period._')
    else:
        body.append(
            '- _Not applicable — media entity, no graph node attached._'
        )

    body += ['', '### Transmission paths involving this node']
    if paths_involving:
        for p in paths_involving:
            labels = p.get('path_labels') or p.get('path') or []
            path_str = ' → '.join(f'`{n}`' for n in labels) or '_empty path_'
            conf = float(p.get('confidence') or 0)
            body.append(
                f'- trigger `{p.get("trigger","?")}` → target '
                f'`{p.get("target","?")}`: {path_str}  (conf={conf:.2f})'
            )
    elif graph_node_id:
        body.append('- _No transmission path matched this node this period._')
    else:
        body.append('- _Not applicable for media entities._')

    # ── Provenance ──
    body += [
        '',
        '## Provenance',
        '',
        '- Base entity: `pipeline_refine` (daily_update Step 2.5 / 2.6)',
        f'- Graph node: {"`"+graph_node_id+"`" if graph_node_id else "—"}',
        f'- Confidence proxy (node severity): `{severity_str}`',
        '',
        '> Base page. Canonical regime → `05_Regime_Canonical/`. '
        'Debate commentary → `06_Debate_Memory/`. '
        'Full transmission paths → `07_Graph_Evidence/`.',
    ]

    out = ENTITIES_DIR / f'{month_str}_{_safe_filename(entity_id)}.md'
    out.write_text('\n'.join(frontmatter + body) + '\n', encoding='utf-8')
    return out


# ══════════════════════════════════════════
# Asset page
# ══════════════════════════════════════════

def write_asset_page(asset_name: str, linked_topics: list[str],
                     topic_counts: dict, month_str: str) -> Path:
    top_articles = topic_counts.get(asset_name, [])
    total = sum(len(v) for v in topic_counts.values()) or 1
    asset_total = sum(topic_counts.get(t, 0) if isinstance(topic_counts.get(t), int) else 0
                      for t in linked_topics)
    # 간단: linked_topics의 article 수 합
    related_count = 0
    for t in linked_topics:
        related_count += len(topic_counts.get(t, []))

    lines = [
        '---',
        'type: asset',
        'status: draft',
        f'asset_name: "{asset_name}"',
        f'linked_topics: [{", ".join(chr(34)+t+chr(34) for t in linked_topics)}]',
        f'period: {month_str}',
        f'related_article_count: {related_count}',
        'source_of_truth: pipeline_refine',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
        f'# Asset — {asset_name}',
        '',
        f'- Linked topics: {", ".join(f"`{t}`" for t in linked_topics)}',
        f'- Related articles this period: {related_count}',
        '',
        '## Current regime section',
        '(canonical regime은 `05_Regime_Canonical/current_regime.md` 참조)',
        '',
        '> Base asset page — transmission paths 반영 금지 (Phase 4+ 이후 승격).',
    ]
    out = ASSETS_DIR / f'{month_str}_{_safe_filename(asset_name)}.md'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return out


# ══════════════════════════════════════════
# Fund page
# ══════════════════════════════════════════

def write_fund_page(fund_code: str, fund_meta: dict, month_str: str) -> Path:
    lines = [
        '---',
        'type: fund',
        'status: draft',
        f'fund_code: {fund_code}',
        f'fund_name: "{fund_meta.get("name", "")}"',
        f'period: {month_str}',
        'source_of_truth: pipeline_refine',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
        f'# Fund — {fund_code}',
        '',
        f'- Name: {fund_meta.get("name", "")}',
        f'- AUM: {fund_meta.get("aum", "N/A")}',
        f'- Asset mix: {fund_meta.get("asset_mix", "")}',
        '',
        '## Current regime section',
        '(canonical regime은 `05_Regime_Canonical/current_regime.md` 참조)',
        '',
        '> Base fund page — debate commentary는 `06_Debate_Memory/` 경유.',
    ]
    out = FUNDS_DIR / f'{month_str}_{_safe_filename(fund_code)}.md'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return out


# ══════════════════════════════════════════
# 오케스트레이션
# ══════════════════════════════════════════

def refresh_base_pages_after_refine(month_str: str,
                                      top_events: int = 5,
                                      top_entities: int = 5,
                                      sample_assets: list[str] | None = None,
                                      sample_funds: dict | None = None) -> dict:
    """정제(Step 2.5) 직후 호출. 샘플 수준의 base 페이지를 재생성.

    Returns: 생성된 파일 카운트.
    """
    articles = _load_month_articles(month_str)
    if not articles:
        return {'events': 0, 'entities': 0, 'assets': 0, 'funds': 0}

    # Event pages (top salience event groups)
    by_event = defaultdict(list)
    for a in articles:
        eid = a.get('_event_group_id')
        if eid:
            by_event[eid].append(a)
    # sort by max salience per group
    ranked = sorted(by_event.items(),
                    key=lambda kv: max((a.get('_event_salience', 0) for a in kv[1]), default=0),
                    reverse=True)
    event_count = 0
    for eid, arts in ranked[:top_events]:
        if write_event_page(eid, arts, month_str):
            event_count += 1

    # Entity pages (v13 redesign — media + GraphRAG 상위 노드, confirmed/draft 분리)
    entity_count = 0
    src_counter = Counter(a.get('source', '') for a in articles if a.get('source'))

    # GraphRAG 로드 (nodes + edges + transmission_paths 전부)
    graph_nodes: dict = {}
    graph_edges: list[dict] = []
    graph_paths: list[dict] = []
    try:
        from pathlib import Path as _P
        import json as _j
        graph_path = (_P(__file__).resolve().parent.parent /
                      'data' / 'insight_graph' / f'{month_str}.json')
        if graph_path.exists():
            _g = _j.loads(graph_path.read_text(encoding='utf-8'))
            graph_nodes = _g.get('nodes', {}) or {}
            graph_edges = _g.get('edges', []) or []
            graph_paths = _g.get('transmission_paths', []) or []
    except Exception:
        graph_nodes, graph_edges, graph_paths = {}, [], []

    def _find_graph_node(text: str) -> tuple[str | None, str | None]:
        """text 에 대응하는 GraphRAG 노드 id / canonical label 시도."""
        if not graph_nodes:
            return None, None
        t_norm = text.replace(' ', '').lower()
        for nid, meta in graph_nodes.items():
            label = (meta.get('label') or nid).replace(' ', '').lower()
            if t_norm and (t_norm in label or label in t_norm):
                return nid, meta.get('label', nid)
        return None, None

    def _linked_events(src_name: str) -> list[str]:
        evs: list[str] = []
        seen_ids: set = set()
        for a in articles:
            if a.get('source') == src_name:
                eid = a.get('_event_group_id')
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    evs.append(str(eid))
        return evs[:5]

    # --- Media entities (source__) — no graph node, draft section shows N/A ---
    for src, _ in src_counter.most_common(top_entities):
        samples = [a.get('title', '') for a in articles
                   if a.get('source') == src][:8]
        node_id, canon_label = _find_graph_node(src)
        adj = _graph_adjacency_for(node_id, graph_edges)
        paths = _paths_involving(src, node_id, graph_paths)
        meta = graph_nodes.get(node_id) if node_id else None
        write_entity_page(
            entity_id=f'source__{src}',
            label=src,
            topic='매체',
            mentioned_in=samples,
            month_str=month_str,
            graph_node_id=node_id,
            canonical_entity_label=canon_label,
            linked_events=_linked_events(src),
            adjacent_nodes=adj,
            paths_involving=paths,
            graph_node_meta=meta,
        )
        entity_count += 1

    # --- GraphRAG 상위 severity 노드 — 기존 3 demo (유가/환율/달러) 유지.
    # id는 graphnode__<node_id> 이라 stable하고, v12.1 샘플과 1:1 대응된다.
    try:
        if graph_nodes:
            ranked = sorted(
                graph_nodes.items(),
                key=lambda kv: -float(kv[1].get('severity_weight', 0) or 0),
            )
            for nid, meta in ranked[:3]:
                label = meta.get('label', nid)
                topic_tag = meta.get('topic', '기타')
                mentioned = [
                    a.get('title', '') for a in articles
                    if label and label.replace(' ', '').lower() in
                    (a.get('title', '') + ' ' + a.get('description', '')).replace(' ', '').lower()
                ][:6]
                events: list[str] = []
                seen_ids: set = set()
                for a in articles:
                    if not mentioned:
                        break
                    if any(a.get('title', '') == m for m in mentioned):
                        eid = a.get('_event_group_id')
                        if eid and eid not in seen_ids:
                            seen_ids.add(eid)
                            events.append(str(eid))
                adj = _graph_adjacency_for(nid, graph_edges)
                paths = _paths_involving(label, nid, graph_paths)
                write_entity_page(
                    entity_id=f'graphnode__{nid}',
                    label=label,
                    topic=topic_tag,
                    mentioned_in=mentioned,
                    month_str=month_str,
                    graph_node_id=nid,
                    canonical_entity_label=label,
                    linked_events=events[:5],
                    adjacent_nodes=adj,
                    paths_involving=paths,
                    graph_node_meta=meta,
                )
                entity_count += 1
    except Exception:
        pass

    # Asset pages — topic buckets as proxy
    topic_bucket = defaultdict(list)
    for a in articles:
        for t in a.get('_classified_topics', []):
            topic_bucket[t.get('topic', '기타')].append(a)
    asset_count = 0
    assets = sample_assets or list(_ASSET_TOPIC_MAP.keys())
    for asset in assets:
        linked = _ASSET_TOPIC_MAP.get(asset, [])
        # 간단한 topic_counts dict: {topic_name: [articles]}
        write_asset_page(asset, linked, topic_bucket, month_str)
        asset_count += 1

    # Fund pages — sample_funds 기반
    funds = sample_funds or {
        '08K88': {'name': '한투 공격적 OCIO', 'aum': '~', 'asset_mix': '주식 80 / 채권 20'},
        '07G04': {'name': '한투 복합 OCIO', 'aum': '~', 'asset_mix': '주식 60 / 채권 40'},
    }
    fund_count = 0
    for code, meta in funds.items():
        write_fund_page(code, meta, month_str)
        fund_count += 1

    # Index page 갱신
    _refresh_index(month_str, event_count, entity_count, asset_count, fund_count)

    return {
        'events': event_count, 'entities': entity_count,
        'assets': asset_count, 'funds': fund_count,
    }


# 하위 호환 alias (v10 이후 임시)
def refresh_draft_pages_after_refine(*args, **kwargs):
    return refresh_base_pages_after_refine(*args, **kwargs)


def _refresh_index(month_str: str, ec: int, en: int, ac: int, fc: int) -> None:
    idx = INDEX_DIR / 'index.md'
    lines = [
        '---',
        'type: wiki_index',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
        '# Wiki Index',
        '',
        f'Latest period: **{month_str}**',
        '',
        '## Tier map',
        '',
        '- **Base pages (01~04)** — factual aggregation from refine step',
        '  - `01_Events/` — event pages (event_group_id 단위)',
        '  - `02_Entities/` — entity pages',
        '  - `03_Assets/` — asset pages',
        '  - `04_Funds/` — fund pages',
        '- **Confirmed memory (05)** — `05_Regime_Canonical/` — daily_update.Step 5 writer only',
        '- **Provisional memory (06)** — `06_Debate_Memory/` — debate_engine interpretations',
        '- **Graph evidence (07)** — `07_Graph_Evidence/` — transmission path draft (not canonical)',
        '',
        '## Latest batch counts (base pages)',
        f'- Events: {ec}',
        f'- Entities: {en}',
        f'- Assets: {ac}',
        f'- Funds: {fc}',
        '',
        '## Query routing order',
        '1. `05_Regime_Canonical/` (confirmed memory)',
        '2. `01_Events/` ~ `04_Funds/` (base pages)',
        '3. `06_Debate_Memory/` (interpretations)',
        '4. `07_Graph_Evidence/` or GraphRAG retrieval',
        '5. raw source chunk',
        '',
    ]
    idx.write_text('\n'.join(lines) + '\n', encoding='utf-8')
