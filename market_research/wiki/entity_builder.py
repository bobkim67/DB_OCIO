"""Entity builder — GraphRAG 노드 중심 entity 선별 (v13 redesign).

지시서 요약:
  - severity 기반 로직 전면 폐기 (실데이터에서 severity_weight=0, severity='neutral')
  - taxonomy_topic은 ``wiki.taxonomy.extract_taxonomy_tags`` exact hit만 허용
  - 선별은 graph structure (edge/path) 기반으로
  - base page 본문에 path 상세 넣지 않음 (07_Graph_Evidence/ 소유)

본 모듈은 순수 계산만 담당한다. 파일 write 책임은 ``draft_pages.py`` 에 있다.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from market_research.wiki.taxonomy import extract_taxonomy_tags


# ═══════════════════════════════════════════════════════════════
# 1. Graph snapshot loader
# ═══════════════════════════════════════════════════════════════

def load_graph_snapshot(month_str: str,
                        base_dir: Path | None = None) -> dict:
    """``data/insight_graph/{month}.json`` 로드.

    Returns: {'nodes': dict, 'edges': list, 'transmission_paths': list}
    결측 파일 / 파싱 실패 시 빈 dict 구조 반환.
    """
    import json
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent / 'data' / 'insight_graph'
    path = base_dir / f'{month_str}.json'
    if not path.exists():
        return {'nodes': {}, 'edges': [], 'transmission_paths': []}
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'nodes': {}, 'edges': [], 'transmission_paths': []}
    return {
        'nodes': raw.get('nodes') or {},
        'edges': raw.get('edges') or [],
        'transmission_paths': raw.get('transmission_paths') or [],
    }


# ═══════════════════════════════════════════════════════════════
# 2. Taxonomy gate
# ═══════════════════════════════════════════════════════════════

def map_node_to_taxonomy(label: str) -> str | None:
    """PHRASE_ALIAS exact gate.

    Rules:
      - extract_taxonomy_tags(label) → (matched, unresolved)
      - len(matched) == 1  → return matched[0]
      - len(matched) == 0  → None (miss)
      - len(matched) >= 2  → None (ambiguous)

    억지 매핑 금지. node.topic fallback 금지.
    """
    if not label:
        return None
    matched, _unresolved = extract_taxonomy_tags(label)
    if len(matched) == 1:
        return matched[0]
    return None


# ═══════════════════════════════════════════════════════════════
# 3. Graph structure → node importance
# ═══════════════════════════════════════════════════════════════

def compute_node_importance(node_id: str,
                             node_label: str,
                             edges: list[dict],
                             paths: list[dict]) -> dict:
    """node의 graph structure 기반 importance 지표를 계산.

    Returns: {
        'node_importance': float,          # edge effective_score 합
        'importance_basis': str,           # 'edge_effective_score_sum'
        'edge_score_sum': float,
        'support_count_sum': int,
        'path_count': int,
        'path_role_hit': bool,             # trigger/target 직접 등장
    }
    """
    score_sum = 0.0
    support_sum = 0
    label_norm = _norm(node_label)
    id_norm = _norm(node_id)

    for e in edges:
        if e.get('from') == node_id or e.get('to') == node_id:
            try:
                score_sum += float(e.get('effective_score') or 0)
            except (TypeError, ValueError):
                pass
            try:
                support_sum += int(e.get('support_count') or 0)
            except (TypeError, ValueError):
                pass

    path_count = 0
    path_role_hit = False
    for p in paths:
        trig = _norm(p.get('trigger', ''))
        tgt = _norm(p.get('target', ''))
        role_hit = (trig in (label_norm, id_norm)) or (tgt in (label_norm, id_norm))
        # path 내부 경유도 포함해 path_count 계산
        path_nodes = p.get('path') or []
        path_labels = p.get('path_labels') or []
        internal_hit = any(
            _norm(x) in (label_norm, id_norm)
            for x in list(path_nodes) + list(path_labels)
        )
        if role_hit or internal_hit:
            path_count += 1
        if role_hit:
            path_role_hit = True

    return {
        'node_importance': round(score_sum, 4),
        'importance_basis': 'edge_effective_score_sum',
        'edge_score_sum': round(score_sum, 4),
        'support_count_sum': support_sum,
        'path_count': path_count,
        'path_role_hit': path_role_hit,
    }


# ═══════════════════════════════════════════════════════════════
# 4. Article matching
# ═══════════════════════════════════════════════════════════════

def collect_entity_articles(node_label: str,
                             articles: list[dict],
                             k_primary: int = 5,
                             k_recent: int = 8) -> dict:
    """label 매칭 기사 집계.

    Matching: title + description normalized contains (공백/대소문자 무시).
    """
    if not node_label or not articles:
        return _empty_article_result()

    label_norm = _norm(node_label)
    matched: list[dict] = []
    seen_ids: set[str] = set()

    for a in articles:
        aid = a.get('_article_id')
        if not aid or aid in seen_ids:
            continue
        blob_norm = _norm((a.get('title') or '') + ' ' + (a.get('description') or ''))
        if label_norm and label_norm in blob_norm:
            matched.append(a)
            seen_ids.add(aid)

    if not matched:
        return _empty_article_result()

    # primary_articles 정렬: is_primary=True → salience desc → date desc → id tie-break
    def _primary_key(a: dict) -> tuple:
        is_primary = bool(a.get('is_primary'))
        salience = float(a.get('_event_salience') or 0)
        date = a.get('date') or ''
        aid = a.get('_article_id') or ''
        return (
            0 if is_primary else 1,  # primary 먼저
            -salience,                # salience desc
            -_date_key(date),         # 최신 먼저
            aid,                      # deterministic
        )

    primary_sorted = sorted(matched, key=_primary_key)
    primary_ids = [a['_article_id'] for a in primary_sorted[:k_primary]]

    # recent_titles: date desc 상위 k_recent
    recent_sorted = sorted(
        matched,
        key=lambda a: (-_date_key(a.get('date') or ''), a.get('_article_id') or ''),
    )
    recent_titles = [a.get('title') or '' for a in recent_sorted[:k_recent]]

    # linked_events: event_group_id unique
    linked_events: list[str] = []
    seen_events: set[str] = set()
    for a in primary_sorted:
        eid = a.get('_event_group_id')
        if eid and eid not in seen_events:
            seen_events.add(eid)
            linked_events.append(str(eid))

    # first/last seen
    dates_sorted = sorted(a.get('date') or '' for a in matched if a.get('date'))
    first_seen = dates_sorted[0] if dates_sorted else ''
    last_seen = dates_sorted[-1] if dates_sorted else ''

    return {
        'unique_article_ids': sorted(seen_ids),
        'unique_article_count': len(seen_ids),
        'first_seen': first_seen,
        'last_seen': last_seen,
        'primary_articles': primary_ids,
        'recent_titles': recent_titles,
        'linked_events': linked_events[:5],
        'linked_event_count': len(seen_events),
    }


def _empty_article_result() -> dict:
    return {
        'unique_article_ids': [],
        'unique_article_count': 0,
        'first_seen': '',
        'last_seen': '',
        'primary_articles': [],
        'recent_titles': [],
        'linked_events': [],
        'linked_event_count': 0,
    }


# ═══════════════════════════════════════════════════════════════
# 5. Candidate selection
# ═══════════════════════════════════════════════════════════════

def select_entity_candidates(nodes: dict,
                              edges: list[dict],
                              paths: list[dict],
                              articles: list[dict],
                              max_entities: int = 12,
                              per_taxonomy_cap: int = 3) -> list[dict]:
    """hard gate + evidence + 랭킹 + cap 적용.

    Returns: list[candidate]  — each candidate is a dict with fields
      entity_id, node_id, label, taxonomy_topic, node_importance, ...
    """
    raw: list[dict] = []
    for nid, meta in nodes.items():
        label = (meta or {}).get('label') or nid
        taxonomy_topic = map_node_to_taxonomy(label)
        if taxonomy_topic is None:
            # hard gate: PHRASE_ALIAS miss → 후보 제외
            continue

        imp = compute_node_importance(nid, label, edges, paths)
        art = collect_entity_articles(label, articles)

        has_evidence = (
            art['unique_article_count'] >= 2
            or art['linked_event_count'] >= 1
            or imp['path_role_hit']
        )
        if not has_evidence:
            continue

        raw.append({
            'entity_id': f'graphnode__{nid}',
            'graph_node_id': nid,
            'label': label,
            'taxonomy_topic': taxonomy_topic,
            **imp,
            **art,
        })

    # 랭킹: path_role_hit DESC, node_importance DESC, unique_article_count DESC
    raw.sort(key=lambda c: (
        0 if c['path_role_hit'] else 1,
        -c['node_importance'],
        -c['unique_article_count'],
        c['label'],
    ))

    # per_taxonomy_cap 적용
    taxonomy_count: Counter = Counter()
    kept: list[dict] = []
    for c in raw:
        t = c['taxonomy_topic']
        if taxonomy_count[t] >= per_taxonomy_cap:
            continue
        kept.append(c)
        taxonomy_count[t] += 1
        if len(kept) >= max_entities:
            break

    return kept


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _norm(s: Any) -> str:
    return (str(s or '')).replace(' ', '').replace('_', '').lower()


def _date_key(s: str) -> int:
    """YYYY-MM-DD → int. 파싱 실패 시 0."""
    if not s or len(s) < 10:
        return 0
    try:
        return int(s[:4] + s[5:7] + s[8:10])
    except ValueError:
        return 0
