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


def write_entity_page(candidate: dict, month_str: str) -> Path:
    """Render an entity page (v13 redesign — graph-structure driven base page).

    The caller (``entity_builder.select_entity_candidates``) precomputes all
    fields needed. Base page contains:
      - Confirmed facts (mention summary + linked events + asset classes +
        recent articles with article_id refs)
      - Graph provenance — summary numerics ONLY (node_importance,
        support_count_sum, path_count, path_role_hit). Adjacency list and
        transmission path detail are intentionally NOT rendered here;
        those live in ``07_Graph_Evidence/``.

    severity-based fields are removed. ``taxonomy_topic`` is supplied by the
    builder via PHRASE_ALIAS exact gate — never from ``node.topic``.
    """
    label = candidate['label']
    entity_id = candidate['entity_id']
    taxonomy_topic = candidate['taxonomy_topic']
    graph_node_id = candidate.get('graph_node_id')
    linked_events = candidate.get('linked_events') or []
    primary_articles = candidate.get('primary_articles') or []
    recent_titles = candidate.get('recent_titles') or []
    unique_count = int(candidate.get('unique_article_count') or 0)
    first_seen = candidate.get('first_seen') or ''
    last_seen = candidate.get('last_seen') or ''
    node_importance = float(candidate.get('node_importance') or 0.0)
    importance_basis = candidate.get('importance_basis') or 'edge_effective_score_sum'
    support_count_sum = int(candidate.get('support_count_sum') or 0)
    path_count = int(candidate.get('path_count') or 0)
    path_role_hit = bool(candidate.get('path_role_hit'))

    frontmatter: list[str] = [
        '---',
        'type: entity',
        'status: base',
        f'entity_id: {entity_id}',
        f'label: "{label}"',
        f'taxonomy_topic: {taxonomy_topic}',
        f'node_importance: {node_importance:.4f}',
        f'importance_basis: {importance_basis}',
        f'support_count_sum: {support_count_sum}',
        f'path_count: {path_count}',
        f'path_role_hit: {"true" if path_role_hit else "false"}',
        f'unique_article_count: {unique_count}',
    ]
    if first_seen:
        frontmatter.append(f'first_seen: {first_seen}')
    if last_seen:
        frontmatter.append(f'last_seen: {last_seen}')
    if primary_articles:
        frontmatter.append(
            'primary_articles: [' + ', '.join(primary_articles[:5]) + ']'
        )
    if graph_node_id:
        frontmatter.append(f'graph_node_id: {graph_node_id}')
    frontmatter += [
        f'period: {month_str}',
        'has_graph_signal: true',
        'source_of_truth: pipeline_refine+graphrag',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
    ]

    related_assets = _related_asset_classes_for(label)

    body: list[str] = [
        f'# Entity — {label}',
        '',
        f'**Canonical label**: `{label}`  ',
        f'**Taxonomy**: `{taxonomy_topic}` · **Graph node**: `{graph_node_id or "—"}`',
        '',
        '## Confirmed facts',
        '',
    ]
    if first_seen and last_seen:
        body.append(
            f'- Mention summary: {first_seen} ~ {last_seen} · '
            f'{unique_count} articles'
        )
    else:
        body.append(f'- Mention summary: {unique_count} articles')
    if linked_events:
        body.append(
            '- Linked events: ' + ', '.join(f'`{e}`' for e in linked_events[:5])
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

    body += ['', '### Recent articles']
    if recent_titles:
        # article_id ref 병기: primary_articles 순서 기준으로 매핑
        ref_iter = iter(primary_articles)
        for title in recent_titles[:8]:
            ref_id = next(ref_iter, None)
            if ref_id:
                body.append(f'- {title} (ref:`{ref_id}`)')
            else:
                body.append(f'- {title}')
    else:
        body.append('- _No articles matched this entity this period._')

    body += [
        '',
        '## Graph provenance',
        '',
        f'- `node_importance`: {node_importance:.4f} ({importance_basis})',
        f'- `support_count_sum`: {support_count_sum}',
        f'- `path_count`: {path_count}',
        f'- `path_role_hit`: {"true" if path_role_hit else "false"}',
        '',
        '> Detailed adjacency and transmission paths are available in '
        '`07_Graph_Evidence/`. This base page records only summary provenance.',
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

    # F3 P1.5-a (2026-05-06): 월별 event page wipe.
    # 기존 동작은 wipe 없이 write_event_page → 매 daily_update 마다 누적.
    # P1.5-b (deterministic event_group_id) 와 결합되어 동일 cluster 는 동일
    # 파일명 → wipe 후 재생성 시 자동 덮어쓰기 효과 + 사라진 cluster 정리.
    #
    # 삭제 범위는 반드시 좁게: 01_Events/{month_str}_event_*.md 만.
    # 02_Entities / 03_Assets / 04_Funds / 05_Regime_Canonical / 수동 보강 페이지
    # 절대 건드리지 않음 (사용자 명시 정책).
    deleted_event_pages = 0
    deleted_samples: list[str] = []
    for fp in sorted(EVENTS_DIR.glob(f'{month_str}_event_*.md')):
        try:
            fp.unlink()
            deleted_event_pages += 1
            if len(deleted_samples) < 5:
                deleted_samples.append(fp.name)
        except OSError as exc:
            print(f'  [wipe warn] failed to delete {fp.name}: {exc}')
    if deleted_event_pages:
        print(f'  [wipe] deleted_event_pages={deleted_event_pages} '
              f'samples={deleted_samples}')

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

    # Entity pages (v13 redesign — graph-structure driven, taxonomy exact gate)
    # - severity 기반 로직 제거 (실데이터 severity_weight=0, severity=neutral)
    # - media entity (source__*) 생성 중단
    # - node.topic fallback 금지; PHRASE_ALIAS exact hit만 허용
    # - body에 adjacency/path 상세 미노출 (07_Graph_Evidence/ 소유)
    entity_count = 0
    try:
        from market_research.wiki.entity_builder import (
            load_graph_snapshot, select_entity_candidates,
        )
        graph = load_graph_snapshot(month_str)
        candidates = select_entity_candidates(
            graph['nodes'], graph['edges'], graph['transmission_paths'],
            articles,
            max_entities=12, per_taxonomy_cap=3,
            suppress_near_duplicates=True,   # v13.3: 유가/국제유가 같은 중복 억제
        )
        # 기존 페이지 정리 (media + legacy graphnode) 후 재생성
        _purge_stale_entity_pages(month_str, keep_ids={c['entity_id'] for c in candidates})
        for c in candidates:
            write_entity_page(c, month_str)
            entity_count += 1
    except Exception as exc:
        print(f'  [entity] 빌드 실패: {exc}')

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


def _purge_stale_entity_pages(month_str: str, keep_ids: set) -> None:
    """Remove entity pages from this month that are not in ``keep_ids``.

    Covers both legacy ``source__*`` (media, deprecated in v13) and stale
    ``graphnode__*`` pages from previous runs.
    """
    prefix = f'{month_str}_'
    if not ENTITIES_DIR.exists():
        return
    for p in ENTITIES_DIR.glob(f'{prefix}*.md'):
        stem = p.stem[len(prefix):]  # e.g. 'source__네이버검색' or 'graphnode__유가'
        if stem not in keep_ids:
            try:
                p.unlink()
            except OSError:
                pass


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
