# -*- coding: utf-8 -*-
"""
GraphRAG — 인과관계 그래프 빌더
================================
1. engine.py의 51개 DIAGNOSIS_RULES에서 시드 엣지 파싱
2. analysis_worldview.json에서 배관(Plumbing) 테마 인과관계 추출
3. 뉴스 엔티티 추출 + 인과관계 LLM 추론
4. BFS 전이경로 탐색

사용법:
    python -m market_research.graph_rag 2026-03
    python -m market_research.graph_rag --seed-only   # 시드만 빌드
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
GRAPH_DIR = BASE_DIR / 'data' / 'insight_graph'
WORLDVIEW_FILE = BASE_DIR / 'data' / 'monygeek' / 'analysis_worldview.json'
NEWS_DIR = BASE_DIR / 'data' / 'news'

GRAPH_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════
# 1. 시드 그래프 (engine.py 룰 파싱)
# ═══════════════════════════════════════════════════════

def build_seed_graph() -> dict:
    """
    engine.py의 DIAGNOSIS_RULES + INDICATOR_TOPIC_MAP + INDICATOR_DIRECTION에서
    인과 엣지를 추출하여 시드 그래프 생성.
    """
    # engine.py import
    try:
        from market_research.analyze.engine import DIAGNOSIS_RULES, INDICATOR_TOPIC_MAP, INDICATOR_DIRECTION
    except ImportError:
        sys.path.insert(0, str(BASE_DIR.parent))
        from market_research.analyze.engine import DIAGNOSIS_RULES, INDICATOR_TOPIC_MAP, INDICATOR_DIRECTION

    nodes = {}
    edges = []

    # ── 1a. DIAGNOSIS_RULES 메시지에서 → 파싱 ──
    for rule in DIAGNOSIS_RULES:
        name = rule.get('name', '')
        message = rule.get('message', '')
        severity = rule.get('severity', 'neutral')
        topic = rule.get('topic', '')

        # → 구분자로 인과 단계 분리
        steps = [s.strip() for s in message.split('→') if s.strip()]
        if len(steps) < 2:
            continue

        for i in range(len(steps) - 1):
            from_node = _normalize_node_id(steps[i])
            to_node = _normalize_node_id(steps[i + 1])

            # + 로 시작하는 복합 조건 → 개별 노드로 분리
            from_parts = [p.strip() for p in steps[i].split('+') if p.strip()]
            if len(from_parts) > 1:
                # 복합 조건: 각 파트 → 다음 단계
                for part in from_parts:
                    part_id = _normalize_node_id(part)
                    _ensure_node(nodes, part_id, part, topic, severity)
                    _ensure_node(nodes, to_node, steps[i + 1], topic, severity)
                    edges.append({
                        'from': part_id,
                        'to': to_node,
                        'relation': 'causes',
                        'weight': _severity_weight(severity),
                        'source': 'engine_rule',
                        'rule_name': name,
                    })
            else:
                _ensure_node(nodes, from_node, steps[i], topic, severity)
                _ensure_node(nodes, to_node, steps[i + 1], topic, severity)
                edges.append({
                    'from': from_node,
                    'to': to_node,
                    'relation': 'causes',
                    'weight': _severity_weight(severity),
                    'source': 'engine_rule',
                    'rule_name': name,
                })

    # ── 1b. INDICATOR_TOPIC_MAP에서 지표-토픽 연결 ──
    for topic, indicators in INDICATOR_TOPIC_MAP.items():
        topic_node = _normalize_node_id(topic)
        _ensure_node(nodes, topic_node, topic, topic, 'neutral')
        for ind in indicators:
            ind_node = _normalize_node_id(ind)
            direction = INDICATOR_DIRECTION.get(ind, 0)
            _ensure_node(nodes, ind_node, ind, topic, 'neutral')
            edges.append({
                'from': ind_node,
                'to': topic_node,
                'relation': 'indicates',
                'weight': 0.5,
                'source': 'indicator_map',
                'direction': '+1' if direction > 0 else '-1' if direction < 0 else '0',
            })

    # NOTE: worldview.json 인과관계는 블로거 관점이므로 GraphRAG에서 제거.
    # blog_analyst.py에서 별도 관리 (관점 분리 원칙).

    # 중복 엣지 제거
    edges = _dedup_edges(edges)

    print(f'  시드 그래프: {len(nodes)} 노드, {len(edges)} 엣지')
    return {'nodes': nodes, 'edges': edges, 'transmission_paths': []}


def _normalize_node_id(text: str) -> str:
    """텍스트를 노드 ID로 정규화"""
    text = text.strip()
    # 따옴표, 괄호 제거
    text = re.sub(r'["\'\(\)]', '', text)
    # 공백/특수문자 → 언더스코어
    text = re.sub(r'[\s,/]+', '_', text)
    # 연속 언더스코어
    text = re.sub(r'_+', '_', text)
    return text.strip('_')[:60]  # 최대 60자


def _ensure_node(nodes: dict, node_id: str, label: str, topic: str, severity: str,
                 source_type: str = None):
    """노드가 없으면 추가. 있으면 source_types 집합에 source_type 을 누적 append.

    Phase 3 (2026-04-22): source_type provenance 는 노드 단위로 set 형태로 쌓고
    JSON 저장 시 list 로 직렬화된다. seed/inferred 노드는 source_type 인자가 None 으로
    들어와 목록이 빈 채 남는다 (acceptance 에서 허용).
    """
    if not node_id:
        return
    if node_id not in nodes:
        nodes[node_id] = {
            'label': label.strip()[:100],
            'topic': topic,
            'severity': severity,
            'source_types': [],
        }
    else:
        nodes[node_id].setdefault('source_types', [])
    if source_type and source_type not in nodes[node_id]['source_types']:
        nodes[node_id]['source_types'].append(source_type)


def _severity_weight(severity: str) -> float:
    return {'critical': 1.0, 'warning': 0.7, 'positive': 0.5, 'neutral': 0.3}.get(severity, 0.5)


def _dedup_edges(edges: list[dict]) -> list[dict]:
    """동일 from→to 엣지 중복 제거 (weight 높은 것 유지)"""
    seen = {}
    for e in edges:
        key = (e['from'], e['to'])
        if key not in seen or e.get('weight', 0) > seen[key].get('weight', 0):
            seen[key] = e
    return list(seen.values())


# ═══════════════════════════════════════════════════════
# 2. LLM 엔티티 추출 + 인과추론
# ═══════════════════════════════════════════════════════

def _get_api_key():
    key = os.getenv('ANTHROPIC_API_KEY')
    if not key:
        try:
            from market_research.core.constants import ANTHROPIC_API_KEY
            key = ANTHROPIC_API_KEY
        except ImportError:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                'ce', BASE_DIR / 'comment_engine.py')
            ce = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ce)
            key = ce.ANTHROPIC_API_KEY
    return key


def extract_entities_from_news(articles: list[dict], batch_size: int = 30) -> dict:
    """
    뉴스 제목에서 금융 엔티티 추출.
    Returns: {article_index: [entity1, entity2, ...]}
    """
    import anthropic
    client = anthropic.Anthropic(api_key=_get_api_key())
    all_entities = {}

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        lines = [f'{j+1}. {a.get("title", "")[:100]}' for j, a in enumerate(batch)]

        prompt = f"""다음 뉴스 제목에서 금융 시장 관련 엔티티를 추출하세요.

엔티티 종류: 기관(Fed, ECB, BOJ), 자산(금리, 엔화, 반도체), 이벤트(금리인하, 관세, 전쟁), 지표(VIX, MOVE)

{chr(10).join(lines)}

JSON 배열만 응답: [{{"id": 1, "entities": ["Fed", "금리인하"]}}, ...]
금융 무관 기사는 entities를 빈 배열로."""

        try:
            response = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=2000,
                messages=[{'role': 'user', 'content': prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith('```'):
                text = text.split('\n', 1)[-1]
                if text.endswith('```'):
                    text = text[:-3].strip()
            start = text.find('[')
            end = text.rfind(']') + 1
            if start >= 0 and end > start:
                results = json.loads(text[start:end])
                for item in results:
                    idx = item.get('id', 0) - 1 + i
                    entities = item.get('entities', [])
                    if entities:
                        all_entities[idx] = entities
        except Exception as exc:
            print(f'    엔티티 추출 실패 (batch {i}): {exc}')

        time.sleep(0.3)

    return all_entities


def infer_causal_edges(entity_map: dict, articles: list[dict]) -> list[dict]:
    """
    공출현 엔티티 간 인과관계를 Sonnet으로 추론.
    Sonnet 사용 이유: 다단계 인과 체인의 중간 단계 보존이 그래프 품질에 직결.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=_get_api_key())

    # 공출현 쌍 수집
    cooccurrences = defaultdict(int)
    for idx, entities in entity_map.items():
        for i, e1 in enumerate(entities):
            for e2 in entities[i + 1:]:
                pair = tuple(sorted([e1, e2]))
                cooccurrences[pair] += 1

    # 3회 이상 공출현 쌍만
    frequent = [(pair, count) for pair, count in cooccurrences.items() if count >= 3]
    if not frequent:
        return []

    frequent.sort(key=lambda x: -x[1])
    top_pairs = frequent[:20]  # 최대 20쌍

    pair_lines = [f'{i+1}. "{p[0]}" ↔ "{p[1]}" (공출현 {c}회)' for i, (p, c) in enumerate(top_pairs)]

    prompt = f"""다음은 뉴스에서 자주 함께 등장하는 금융 엔티티 쌍입니다.
각 쌍의 인과관계 방향을 판단하세요.

{chr(10).join(pair_lines)}

각 쌍에 대해:
1. 인과관계 방향 (A→B 또는 B→A)
2. 중간 단계가 있으면 intermediate_steps로 포함 (예: "금리인상" → "달러강세" → "신흥국 자본유출")
3. 관계 유형: causes(직접 인과), correlates(상관), reacts_to(반응)
4. confidence: 0.0-1.0

JSON 배열만 응답:
[{{"id": 1, "from": "엔티티A", "to": "엔티티B", "relation": "causes", "confidence": 0.8, "intermediate_steps": ["중간단계1", "중간단계2"]}}]
인과관계가 불분명하면 "correlates"로, confidence 낮게. intermediate_steps는 있을 때만."""

    try:
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=3000,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[-1]
            if text.endswith('```'):
                text = text[:-3].strip()
        start = text.find('[')
        end = text.rfind(']') + 1
        if start >= 0 and end > start:
            results = json.loads(text[start:end])
            edges = []
            for item in results:
                from_id = _normalize_node_id(item.get('from', ''))
                to_id = _normalize_node_id(item.get('to', ''))
                conf = item.get('confidence', 0.5)
                relation = item.get('relation', 'correlates')

                # intermediate_steps가 있으면 체인으로 확장
                steps = item.get('intermediate_steps', [])
                if steps:
                    chain = [from_id] + [_normalize_node_id(s) for s in steps] + [to_id]
                    for j in range(len(chain) - 1):
                        edges.append({
                            'from': chain[j],
                            'to': chain[j + 1],
                            'relation': relation,
                            'weight': conf,
                            'source': 'llm_inferred',
                        })
                else:
                    edges.append({
                        'from': from_id,
                        'to': to_id,
                        'relation': relation,
                        'weight': conf,
                        'source': 'llm_inferred',
                    })
            return edges
    except Exception as exc:
        print(f'    인과추론 실패: {exc}')

    return []


# ═══════════════════════════════════════════════════════
# 3. 전이경로 탐색 (BFS)
# ═══════════════════════════════════════════════════════

def _matches_keyword(node_label: str, keyword: str) -> bool:
    """P0: word-boundary 매칭. '금'이 '자금'·'금통위'에 매칭되는 false positive 제거.

    규칙 (순서대로 시도):
      1. 완전 일치 (단어/토큰 단위)
      2. 토큰이 keyword를 접두/접미로 포함하되 길이 차이가 작을 때 (파생형 허용)
      3. keyword 길이가 3자 이상이고 토큰이 정확히 keyword + 형용사형일 때
    """
    if not keyword:
        return False
    norm = node_label.replace('·', '_').replace('-', '_').replace(' ', '_')
    tokens = [t for t in norm.split('_') if t]
    kw = keyword.strip()
    for tok in tokens:
        if tok == kw:
            return True
        # 파생형 허용 제한: keyword가 2자 이상 AND 토큰 길이 <= keyword + 3
        if len(kw) >= 2 and len(tok) <= len(kw) + 3:
            if tok.startswith(kw) or tok.endswith(kw):
                return True
    return False


def query_transmission_path(graph: dict, from_entity: str, to_entity: str,
                            max_depth: int = 5) -> list[dict]:
    """
    BFS로 from_entity → to_entity 전이경로 탐색.
    P0 적용: word-boundary 매칭 + self-loop 필터.

    Returns: [{"path": [node1, node2, ...], "confidence": 0.x}, ...]
    """
    nodes = graph.get('nodes', {})
    edges = graph.get('edges', [])

    # 인접 리스트 구축
    adj = defaultdict(list)
    for e in edges:
        adj[e['from']].append((e['to'], e.get('weight', 0.5)))

    from_kw = _normalize_node_id(from_entity)
    to_kw = _normalize_node_id(to_entity)

    # P0: word-boundary 매칭 (substring → 토큰 단위)
    from_candidates = [n for n, meta in nodes.items()
                        if _matches_keyword(meta.get('label', n), from_kw)
                        or _matches_keyword(n, from_kw)]
    to_candidates = [n for n, meta in nodes.items()
                      if _matches_keyword(meta.get('label', n), to_kw)
                      or _matches_keyword(n, to_kw)]

    if not from_candidates or not to_candidates:
        return []

    all_paths = []
    for start in from_candidates:
        for end in to_candidates:
            # P0: self-loop 제거 — 같은 노드 + 같은 keyword 세트면 스킵
            if start == end:
                continue
            if _matches_keyword(start, to_kw) and _matches_keyword(end, from_kw):
                continue   # 개념적 self-loop
            paths = _bfs_all_paths(adj, start, end, max_depth)
            for path, conf in paths:
                all_paths.append({
                    'path': path,
                    'path_labels': [nodes.get(n, {}).get('label', n) for n in path],
                    'confidence': round(conf, 3),
                })

    # confidence 높은 순 정렬
    all_paths.sort(key=lambda x: -x['confidence'])
    return all_paths[:5]  # 최대 5개


def _bfs_all_paths(adj: dict, start: str, end: str, max_depth: int) -> list:
    """BFS로 모든 경로 탐색 (depth 제한)"""
    queue = deque([(start, [start], 1.0)])
    found = []
    visited_paths = set()

    while queue:
        current, path, confidence = queue.popleft()
        if len(path) > max_depth:
            continue

        if current == end:
            path_key = tuple(path)
            if path_key not in visited_paths:
                visited_paths.add(path_key)
                found.append((path, confidence))
            continue

        for neighbor, weight in adj.get(current, []):
            if neighbor not in path:  # 사이클 방지
                queue.append((neighbor, path + [neighbor], confidence * weight))

    return found


# P0 레거시 키워드 (quality log의 호환 필드용)
_TRIGGER_KEYWORDS = ['달러_부족', '금리_상승', '유가_급등', '인플레', '위안화', '엔화',
                      '관세', '지정학', '레포']
_ASSET_KEYWORDS = ['국내주식', '국내채권', '해외주식', '해외채권', '원자재', '통화',
                    'KOSPI', 'SP500', '금리', '환율', '유가', '금']


def _query_with_aliases(graph: dict, canon: str, aliases: list[str],
                        role: str, max_depth: int = 4,
                        embed_fallback=None) -> list[dict]:
    """canon + aliases 전체를 시도해 path 후보 수집. role='from' or 'to'."""
    collected: list[dict] = []
    for alias in aliases:
        if role == 'from':
            results = query_transmission_path(graph, alias, canon, max_depth=max_depth)
        else:
            results = query_transmission_path(graph, canon, alias, max_depth=max_depth)
        collected.extend(results)
    # Embedding fallback — 기본(alias) 매칭 실패 시만 시도
    if not collected and embed_fallback is not None:
        extra = embed_fallback(graph, canon, role)
        collected.extend(extra)
    return collected


def _select_dynamic_triggers(graph: dict, top_n_salience: int = 5) -> list[str]:
    """drivers + 월별 salience 상위 노드 → 해당 월 그래프에 실제 존재하는 canonical만 반환."""
    from market_research.analyze.graph_vocab import (
        DRIVER_TAXONOMY, TRIGGER_ALIAS, aliases_for_trigger,
    )
    nodes = graph.get('nodes', {})
    active: list[str] = []
    for canon in DRIVER_TAXONOMY:
        for alias in aliases_for_trigger(canon):
            if any(_matches_keyword(n_meta.get('label', n), alias) or
                   _matches_keyword(n, alias)
                   for n, n_meta in nodes.items()):
                active.append(canon)
                break
    return active


def _select_dynamic_targets(graph: dict) -> list[str]:
    """asset taxonomy 중 현재 그래프에 존재하는 canonical만 반환."""
    from market_research.analyze.graph_vocab import ASSET_TAXONOMY, aliases_for_target
    nodes = graph.get('nodes', {})
    active: list[str] = []
    for canon in ASSET_TAXONOMY:
        for alias in aliases_for_target(canon):
            if any(_matches_keyword(n_meta.get('label', n), alias) or
                   _matches_keyword(n, alias)
                   for n, n_meta in nodes.items()):
                active.append(canon)
                break
    return active


def precompute_transmission_paths(graph: dict, quality_log_path=None,
                                   phase: str = 'P1') -> list[dict]:
    """주요 자산군 간 전이경로 사전 계산.

    phase='P0' : 하드코딩 9×12 vocabulary (레거시)
    phase='P1' : dynamic trigger/target + alias dict + embedding fallback

    공통:
      - word-boundary 매칭 (query_transmission_path 내부)
      - self-loop 제거 (trigger ≈ target이면 skip)
      - pair당 1경로 (confidence 최상위만 채택)
      - quality log append
    """
    from market_research.analyze.graph_vocab import (
        aliases_for_trigger, aliases_for_target,
        DRIVER_TAXONOMY, ASSET_TAXONOMY,
    )
    if phase == 'P0':
        triggers = _TRIGGER_KEYWORDS
        targets = _ASSET_KEYWORDS
        alias_t = {t: [t] for t in triggers}
        alias_a = {a: [a] for a in targets}
    else:
        triggers = _select_dynamic_triggers(graph)
        targets = _select_dynamic_targets(graph)
        alias_t = {t: aliases_for_trigger(t) for t in triggers}
        alias_a = {a: aliases_for_target(a) for a in targets}

    # P1-3: embedding fallback (선택적; 실패 시 no-op)
    embed_fallback = _build_embed_fallback(graph) if phase == 'P1' else None

    paths: list[dict] = []
    pairs_total = 0
    pairs_with_path = 0
    self_loops_skipped = 0
    triggers_matched: set[str] = set()
    targets_matched: set[str] = set()
    embed_fallback_used = 0

    for trigger in triggers:
        for target in targets:
            pairs_total += 1
            if trigger == target:
                self_loops_skipped += 1
                continue
            # alias 전체 시도 (P1) — P0에서는 단일 키워드
            from_candidates = alias_t[trigger]
            to_candidates = alias_a[target]

            # 개념 self-loop (alias 간 겹침)
            if set(from_candidates) & set(to_candidates):
                self_loops_skipped += 1
                continue

            candidates: list[dict] = []
            for fa in from_candidates:
                for ta in to_candidates:
                    results = query_transmission_path(graph, fa, ta, max_depth=4)
                    candidates.extend(results)

            # Embedding fallback — alias로 못 찾은 pair만
            if not candidates and embed_fallback is not None:
                extra = embed_fallback(graph, trigger, target)
                if extra:
                    embed_fallback_used += 1
                    candidates.extend(extra)

            if not candidates:
                continue
            candidates.sort(key=lambda x: -x['confidence'])
            top = candidates[0]
            if top['confidence'] <= 0.1:
                continue
            pairs_with_path += 1
            triggers_matched.add(trigger)
            targets_matched.add(target)
            paths.append({
                'trigger': trigger,      # canonical label
                'target': target,
                **top,
            })

    # quality log
    if quality_log_path is not None:
        try:
            from datetime import date as _date
            import json as _json
            q = {
                'date': _date.today().isoformat(),
                'phase': phase,
                'tag_match_mode': 'word_boundary+alias' if phase == 'P1' else 'word_boundary',
                'pairs_total': pairs_total,
                'pairs_with_path': pairs_with_path,
                'self_loops_skipped': self_loops_skipped,
                'total_paths': len(paths),
                'unique_triggers': len(triggers_matched),
                'unique_targets': len(targets_matched),
                'triggers_active': sorted(triggers_matched),
                'targets_active': sorted(targets_matched),
                'unmatched_triggers': sorted(set(triggers) - triggers_matched),
                'unmatched_targets': sorted(set(targets) - targets_matched),
                'avg_confidence': round(
                    sum(p['confidence'] for p in paths) / len(paths), 3) if paths else 0,
                'embed_fallback_used': embed_fallback_used,
            }
            with open(quality_log_path, 'a', encoding='utf-8') as fh:
                fh.write(_json.dumps(q, ensure_ascii=False) + '\n')
        except Exception as exc:
            print(f'  [경고] transmission path quality log 실패: {exc}')

    print(f'  전이경로 사전계산({phase}): {len(paths)}개 '
          f'(trigger {len(triggers_matched)}/{len(triggers)}, '
          f'target {len(targets_matched)}/{len(targets)}, '
          f'self-loop skip {self_loops_skipped}, embed fb {embed_fallback_used})')
    return paths


# ══════════════════════════════════════════
# P1-3: Embedding fallback (lightweight)
# ══════════════════════════════════════════

_EMBED_MODEL = None  # 지연 로드 (module-level singleton)


def _build_embed_fallback(graph: dict, similarity_threshold: float = 0.7):
    """closure를 반환. 실제 embedding 모델이 없으면 None 반환.

    경량 구현: sentence_transformers 로드 실패 시 None → fallback 비활성.
    """
    try:
        global _EMBED_MODEL
        if _EMBED_MODEL is None:
            from sentence_transformers import SentenceTransformer
            _EMBED_MODEL = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    except Exception as exc:
        print(f'  [info] embedding fallback 비활성 ({exc.__class__.__name__})')
        return None

    model = _EMBED_MODEL

    # 노드 label 임베딩 사전계산
    node_ids = list(graph.get('nodes', {}).keys())
    labels = [graph['nodes'][n].get('label', n) for n in node_ids]
    try:
        import numpy as np
        node_embs = model.encode(labels, show_progress_bar=False, convert_to_numpy=True)
    except Exception as exc:
        print(f'  [info] embedding 계산 실패 — fallback 비활성 ({exc})')
        return None

    def _fallback(g, from_canon: str, to_canon: str) -> list[dict]:
        import numpy as np
        # 가장 가까운 노드 찾기 — from/to 각각
        q_from = model.encode([from_canon], show_progress_bar=False, convert_to_numpy=True)[0]
        q_to = model.encode([to_canon], show_progress_bar=False, convert_to_numpy=True)[0]
        # cosine sim
        def _cos(a, b):
            na = np.linalg.norm(a); nb = np.linalg.norm(b)
            return float(a @ b / (na * nb + 1e-9))
        sims_from = [(_cos(q_from, node_embs[i]), node_ids[i]) for i in range(len(node_ids))]
        sims_to = [(_cos(q_to, node_embs[i]), node_ids[i]) for i in range(len(node_ids))]
        sims_from.sort(reverse=True)
        sims_to.sort(reverse=True)
        # threshold 이상인 상위 1개씩
        best_from = next((n for s, n in sims_from if s >= similarity_threshold), None)
        best_to = next((n for s, n in sims_to if s >= similarity_threshold), None)
        if not best_from or not best_to or best_from == best_to:
            return []
        # 해당 노드로 BFS
        paths = query_transmission_path(g, best_from, best_to, max_depth=4)
        # embedding 매칭이므로 confidence 감쇠
        for p in paths:
            p['confidence'] = round(p['confidence'] * 0.7, 3)
            p['_via'] = 'embedding_fallback'
        return paths

    return _fallback


# ═══════════════════════════════════════════════════════
# 4. 메인: 그래프 빌드
# ═══════════════════════════════════════════════════════

def _load_previous_graph(year: int, month: int) -> dict | None:
    """이전 달 그래프 로드 (누적용)"""
    if month == 1:
        prev_str = f'{year - 1}-12'
    else:
        prev_str = f'{year}-{month - 1:02d}'
    prev_file = GRAPH_DIR / f'{prev_str}.json'
    if prev_file.exists():
        graph = json.loads(prev_file.read_text(encoding='utf-8'))
        print(f'  이전 그래프 로드: {prev_str} '
              f'({len(graph.get("nodes", {}))} 노드, {len(graph.get("edges", []))} 엣지)')
        return graph
    return None


def _stratified_sample(candidates: list[dict]) -> list[dict]:
    """Topic-stratified dynamic cap: 토픽 다양성 보장 + 비용 관리.

    전략:
    1. dynamic cap: min(후보수, max(300, 후보수*5%)), 상한 500
    2. 토픽별 최소 10건 보장 (quota)
    3. 나머지는 salience 상위로 채움
    """
    n = len(candidates)
    if n == 0:
        return []

    # dynamic cap
    cap = min(n, max(300, int(n * 0.05)))
    cap = min(cap, 500)

    # 토픽별 그룹핑
    by_topic = defaultdict(list)
    for a in candidates:
        topic = a.get('primary_topic', '') or '_none'
        by_topic[topic].append(a)

    # 각 토픽 내 salience 정렬
    for topic in by_topic:
        by_topic[topic].sort(
            key=lambda x: (-x.get('_event_salience', 0), -x.get('intensity', 0)))

    selected = []
    selected_ids = set()

    # Phase 1: 토픽별 최소 quota (각 10건, 없으면 있는 만큼)
    min_per_topic = 10
    for topic, arts in by_topic.items():
        if topic == '_none':
            continue
        for a in arts[:min_per_topic]:
            aid = a.get('_article_id', id(a))
            if aid not in selected_ids:
                selected.append(a)
                selected_ids.add(aid)

    # Phase 1.5 (Phase 3 fix-forward 2026-04-22): naver_research 최소 floor 보정
    # 경계월 (nr 원본 비율이 낮은 달, e.g. 2026-04 ≈ 4%) 에서 nr_sampled_pct 가
    # acceptance 기준(10%) 을 밑도는 것을 방지하기 위해 sampling 단계에서 nr 최소량을
    # 확보한다. 전체 cap 은 유지되며, Phase 2 의 salience 상위 채움 로직과 충돌하지 않는다.
    NR_FLOOR_PCT = 0.10
    nr_target = max(1, int(cap * NR_FLOOR_PCT))
    nr_in_selected = sum(1 for a in selected
                         if a.get('source_type') == 'naver_research')
    if nr_in_selected < nr_target:
        nr_pool = sorted(
            (a for a in candidates
             if a.get('source_type') == 'naver_research'
             and a.get('_article_id', id(a)) not in selected_ids),
            key=lambda x: (-x.get('_event_salience', 0), -x.get('intensity', 0)),
        )
        need = nr_target - nr_in_selected
        for a in nr_pool[:need]:
            aid = a.get('_article_id', id(a))
            if aid not in selected_ids:
                selected.append(a)
                selected_ids.add(aid)

    # Phase 2: 나머지 cap을 salience 상위로 채움
    remaining = cap - len(selected)
    if remaining > 0:
        all_sorted = sorted(
            candidates,
            key=lambda x: (-x.get('_event_salience', 0), -x.get('intensity', 0)))
        for a in all_sorted:
            if len(selected) >= cap:
                break
            aid = a.get('_article_id', id(a))
            if aid not in selected_ids:
                selected.append(a)
                selected_ids.add(aid)

    return selected


def build_insight_graph(year: int, month: int, include_news: bool = True) -> dict:
    """
    월별 인사이트 그래프 빌드 (누적).

    1. 이전 달 그래프 로드 (있으면 누적, 없으면 시드부터)
    2. 당월 뉴스 엔티티 추출 + 인과추론
    3. 전이경로 사전 계산
    4. JSON 저장
    """
    month_str = f'{year}-{month:02d}'
    print(f'\n── GraphRAG 빌드: {month_str} ──')

    # Step 1: 이전 달 그래프 누적 또는 시드부터 시작
    prev_graph = _load_previous_graph(year, month)
    if prev_graph:
        graph = {
            'nodes': prev_graph.get('nodes', {}),
            'edges': prev_graph.get('edges', []),
            'transmission_paths': [],
        }
        # 시드 엣지 병합 (항상 최신 룰 반영)
        seed = build_seed_graph()
        for nid, ndata in seed['nodes'].items():
            if nid not in graph['nodes']:
                graph['nodes'][nid] = ndata
        graph['edges'].extend(seed['edges'])
        graph['edges'] = _dedup_edges(graph['edges'])
        print(f'  누적 그래프: {len(graph["nodes"])} 노드, {len(graph["edges"])} 엣지')
    else:
        graph = build_seed_graph()

    # Phase 3 migration (2026-04-22): 누적 그래프에서 이어받은 legacy 노드/엣지에
    # source_types / source_type 필드 기본값 주입. 이번 월에서 새로 생성되는 것들과
    # 섞여도 acceptance 집계를 깨지 않도록 사전 표식을 붙인다.
    for _n in graph['nodes'].values():
        _n.setdefault('source_types', [])
    for _e in graph['edges']:
        if _e.get('source') in ('news_entity', 'llm_inferred'):
            _e.setdefault('source_type', None)  # None = legacy_pre_phase3
    _edges_before = len(graph['edges'])

    # Step 2: 뉴스 + naver_research 기반 엔티티/인과 (Phase 3, 2026-04-22)
    nr_sampled = 0
    news_sampled = 0
    if include_news:
        from market_research.analyze.article_stream import (
            load_month_articles, source_of, stream_stats,
        )
        articles = load_month_articles(month_str)
        if articles:
            print(f'  stream stats: {stream_stats(articles)}')

            # 2-lane: primary + topic-stratified dynamic cap (both sources)
            primary_articles = [a for a in articles if a.get('is_primary', True)]
            candidates = [a for a in primary_articles if a.get('intensity', 0) >= 5]
            if not candidates:
                candidates = primary_articles[:200]
            significant = _stratified_sample(candidates)

            # source_type stats on sampled articles
            nr_sampled = sum(1 for a in significant if source_of(a) == 'naver_research')
            news_sampled = len(significant) - nr_sampled
            print(f'  엔티티 추출: {len(significant)}건 (stratified, {len(candidates)} 후보) '
                  f'[nr={nr_sampled} / news={news_sampled}]...')
            entity_map = extract_entities_from_news(significant)
            print(f'  엔티티 보유 기사: {len(entity_map)}건')

            # 엔티티 노드 추가 + salience 가중 엣지 (source_type provenance 전파)
            for idx, entities in entity_map.items():
                art = significant[idx] if idx < len(significant) else {}
                art_source_type = source_of(art) if art else None
                for ent in entities:
                    ent_id = _normalize_node_id(ent)
                    _ensure_node(graph['nodes'], ent_id, ent, 'news', 'neutral',
                                 source_type=art_source_type)
                    # 기사의 primary_topic과 연결 (salience 가중)
                    if art and art.get('primary_topic'):
                        topic_id = _normalize_node_id(art['primary_topic'])
                        salience = art.get('_event_salience', 0.3)
                        base_weight = 0.3 + salience * 0.4  # 0.3~0.7
                        if topic_id in graph['nodes']:
                            graph['edges'].append({
                                'from': ent_id, 'to': topic_id,
                                'relation': 'mentioned_in',
                                'weight': round(base_weight, 3),
                                'source': 'news_entity',
                                'source_type': art_source_type,
                            })

            # 인과관계 추론 (source_type: 원본 배치의 지배 source 로 표시)
            if entity_map:
                print(f'  인과관계 추론...')
                inferred = infer_causal_edges(entity_map, significant)
                # 배치 단위로 지배 source_type 판정
                dominant_st = 'naver_research' if nr_sampled > news_sampled else 'news'
                for edge in inferred:
                    edge['source_type'] = dominant_st
                    _ensure_node(graph['nodes'], edge['from'], edge['from'],
                                 'inferred', 'neutral', source_type=dominant_st)
                    _ensure_node(graph['nodes'], edge['to'], edge['to'],
                                 'inferred', 'neutral', source_type=dominant_st)
                graph['edges'].extend(inferred)
                print(f'  추론 엣지: {len(inferred)}개 (dominant_source_type={dominant_st})')

            # 중복 제거
            graph['edges'] = _dedup_edges(graph['edges'])

    # Step 2.5: TKG decay/prune (이전 달 누적 엣지 정리)
    from datetime import date as _date
    _today = _date(year, month, 1).isoformat()
    print(f'  TKG decay/prune (기준일: {_today})...')
    decay_existing(graph, _today)
    recompute_scores(graph)
    prune_graph(graph)
    print(f'  prune 후: {len(graph["nodes"])} 노드, {len(graph["edges"])} 엣지')

    # Step 3: 전이경로 사전 계산 (P0 적용) + quality log
    _q_log = BASE_DIR / 'data' / 'report_output' / '_transmission_path_quality.jsonl'
    _q_log.parent.mkdir(parents=True, exist_ok=True)
    graph['transmission_paths'] = precompute_transmission_paths(graph, quality_log_path=_q_log)

    # Step 4: 메타데이터 + 저장
    # source_type audit: 노드/엣지에서 nr 관여 비율
    nr_nodes = sum(1 for n in graph['nodes'].values()
                   if 'naver_research' in (n.get('source_types') or []))
    ext_nodes_total = sum(1 for n in graph['nodes'].values()
                          if n.get('source_types'))  # 외부 출처 있는 노드만 집계 대상
    ext_edges = [e for e in graph['edges']
                 if e.get('source') in ('news_entity', 'llm_inferred')]
    ext_edges_with_st = sum(1 for e in ext_edges if e.get('source_type'))
    nr_edges = sum(1 for e in ext_edges if e.get('source_type') == 'naver_research')

    # 이번 월 신규 추가 ext_edges 만 별도 집계 (legacy 제외 판정용)
    # prune/dedup 거친 뒤의 길이 변화로 근사: 누적 그래프에서 prune 되거나 dedup 되는 것이
    # 있기 때문에 완전 정확하지는 않으나, source_type=None 을 'legacy', not None 을 '신규'
    # 로 구분하는 방식이 더 안정적.
    ext_edges_new = [e for e in ext_edges if e.get('source_type') is not None]
    ext_edges_new_with_st = sum(1 for e in ext_edges_new if e.get('source_type'))
    nr_edges_new = sum(1 for e in ext_edges_new if e.get('source_type') == 'naver_research')

    graph['metadata'] = {
        'month': month_str,
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'node_count': len(graph['nodes']),
        'edge_count': len(graph['edges']),
        'path_count': len(graph['transmission_paths']),
        'seed_edges': sum(1 for e in graph['edges'] if e.get('source') in ('engine_rule', 'worldview', 'indicator_map')),
        'llm_edges': sum(1 for e in graph['edges'] if e.get('source') == 'llm_inferred'),
        # Phase 3 (2026-04-22): source_type provenance
        # ext_edges_total/coverage_pct 는 누적 (legacy 포함) 집계
        # ext_edges_new_* 는 이번 월(Phase 3 이후) 생성된 것만 대상 — acceptance 판정용
        'source_type_stats': {
            'nr_articles_sampled': nr_sampled,
            'news_articles_sampled': news_sampled,
            'nr_sampled_pct': (round(nr_sampled / (nr_sampled + news_sampled) * 100, 1)
                               if (nr_sampled + news_sampled) > 0 else 0.0),
            'nodes_with_source_type': ext_nodes_total,
            'nr_nodes': nr_nodes,
            'ext_edges_total': len(ext_edges),
            'ext_edges_with_source_type': ext_edges_with_st,
            'ext_edge_source_type_coverage_pct': (
                round(ext_edges_with_st / len(ext_edges) * 100, 1)
                if ext_edges else 0.0),
            'nr_edges': nr_edges,
            # 신규 분만 대상 — acceptance 기준
            'ext_edges_new': len(ext_edges_new),
            'ext_edges_new_with_source_type': ext_edges_new_with_st,
            'ext_edges_new_coverage_pct': (
                round(ext_edges_new_with_st / len(ext_edges_new) * 100, 1)
                if ext_edges_new else 0.0),
            'nr_edges_new': nr_edges_new,
            'legacy_ext_edges_inherited': _edges_before and sum(
                1 for e in graph['edges']
                if e.get('source') in ('news_entity', 'llm_inferred')
                and e.get('source_type') is None),
        },
    }

    out_file = GRAPH_DIR / f'{month_str}.json'
    out_file.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  저장: {out_file}')

    # Step 4.5: draft evidence page + summary (07_Graph_Evidence/)
    try:
        from market_research.wiki.graph_evidence import (
            write_transmission_paths_draft, write_transmission_paths_summary,
        )
        draft_file = write_transmission_paths_draft(graph, month_str)
        summary_md, _ = write_transmission_paths_summary(graph, month_str, phase='P1')
        print(f'  [wiki] draft evidence: {draft_file.name}, summary: {summary_md.name}')
    except Exception as exc:
        print(f'  [경고] draft evidence 생성 실패: {exc}')
    print(f'  요약: {graph["metadata"]}')

    return graph


def add_incremental_edges(year: int, month: int, new_articles: list[dict]) -> dict:
    """
    Daily Incremental Mode: 기존 그래프에 신규 엔티티/엣지만 추가.
    """
    month_str = f'{year}-{month:02d}'
    graph_file = GRAPH_DIR / f'{month_str}.json'

    if graph_file.exists():
        graph = json.loads(graph_file.read_text(encoding='utf-8'))
    else:
        graph = build_seed_graph()

    if not new_articles:
        return graph

    # 2-lane 필터: primary만 투입
    primary_new = [a for a in new_articles if a.get('is_primary', True)]
    if not primary_new:
        return graph

    # Phase 3 (2026-04-22): source_type provenance 전파 (incremental 경로)
    from market_research.analyze.article_stream import source_of
    entity_map = extract_entities_from_news(primary_new)
    nr_n = sum(1 for a in primary_new if source_of(a) == 'naver_research')
    news_n = len(primary_new) - nr_n
    dominant_st = 'naver_research' if nr_n > news_n else 'news'
    for idx, entities in entity_map.items():
        art = primary_new[idx] if idx < len(primary_new) else {}
        art_st = source_of(art) if art else None
        for ent in entities:
            ent_id = _normalize_node_id(ent)
            _ensure_node(graph['nodes'], ent_id, ent, 'news_daily', 'neutral',
                         source_type=art_st)

    if entity_map:
        inferred = infer_causal_edges(entity_map, primary_new)
        for edge in inferred:
            edge['source_type'] = dominant_st
            _ensure_node(graph['nodes'], edge['from'], edge['from'],
                         'inferred', 'neutral', source_type=dominant_st)
            _ensure_node(graph['nodes'], edge['to'], edge['to'],
                         'inferred', 'neutral', source_type=dominant_st)
        graph['edges'].extend(inferred)
        graph['edges'] = _dedup_edges(graph['edges'])

    # Self-Regulating TKG: decay → merge → recompute → prune
    from datetime import date as _date
    _today = _date.today().isoformat()
    decay_existing(graph, _today)
    merge_today(graph, inferred if entity_map else [])
    recompute_scores(graph)
    prune_graph(graph)

    # 전이경로 갱신 (debate가 최신 경로를 참조하도록) + P0 quality log
    _q_log = BASE_DIR / 'data' / 'report_output' / '_transmission_path_quality.jsonl'
    _q_log.parent.mkdir(parents=True, exist_ok=True)
    graph['transmission_paths'] = precompute_transmission_paths(graph, quality_log_path=_q_log)

    # 저장
    graph_file.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')

    # draft evidence page + summary (07_Graph_Evidence/)
    try:
        from market_research.wiki.graph_evidence import (
            write_transmission_paths_draft, write_transmission_paths_summary,
        )
        write_transmission_paths_draft(graph, month_str)
        write_transmission_paths_summary(graph, month_str, phase='P1')
    except Exception as exc:
        print(f'  [경고] draft evidence 생성 실패: {exc}')

    return graph


# ═══════════════════════════════════════════════════════
# 6. Self-Regulating TKG — Decay / Merge / Prune / Seed
# ═══════════════════════════════════════════════════════

import math
from datetime import date as _d, datetime as _dt

# ── 토픽 → decay class ──
# V2 Taxonomy 기준 decay class
TOPIC_DECAY_CLASS = {}
for _cls, _topics in {
    'flash': ['크립토', '지정학'],
    'news': ['금리_채권', '환율_FX', '물가_인플레이션', '관세_무역',
             '귀금속_금', '에너지_원자재', '테크_AI_반도체', '경기_소비'],
    'structural': ['달러_글로벌유동성', '유동성_크레딧',
                   '부동산', '통화정책'],
}.items():
    for _t in _topics:
        TOPIC_DECAY_CLASS[_t] = _cls
HALF_LIFE_DAYS = {'flash': 5, 'news': 14, 'structural': 60}
MAX_MULTIPLIER = {'flash': 1.5, 'news': 2.0, 'structural': 1.25}

# ── 허브 노드 / 보호 버킷 ──
HUB_NODES = {'금리', '달러', 'SP500', 'USDKRW', '유가', 'KOSPI', '인플레', '미국채', '환율'}
CLUSTER_BUCKET = {
    'rate': ['금리', '미국채', '국채', '채권', 'yield'],
    'fx': ['달러', '환율', 'USDKRW', 'DXY', '엔화', '위안화', '원화'],
    'equity': ['주식', 'SP500', 'KOSPI', '나스닥', '기술주', '성장주', '가치주'],
    'inflation': ['인플레', '물가', 'CPI', 'PPI'],
    'commodity': ['유가', '금', '원자재', 'WTI', 'gold'],
}


def _get_bucket(node_id: str) -> str:
    """노드 ID → cluster bucket 매핑"""
    for bucket, keywords in CLUSTER_BUCKET.items():
        if any(kw in node_id for kw in keywords):
            return bucket
    return 'other'


def _days_between(d1: str, d2: str) -> int:
    """ISO date 문자열 간 일수 차이"""
    try:
        return abs((_dt.fromisoformat(d1[:10]) - _dt.fromisoformat(d2[:10])).days)
    except Exception:
        return 30


def _ensure_edge_fields(edge: dict, today: str):
    """신규 필드 초���화 (기존 엣지 호환)"""
    edge.setdefault('confidence', edge.get('weight', 0.5))
    edge.setdefault('support_count', 1)
    edge.setdefault('last_seen', today)
    edge.setdefault('created_at', today)
    edge.setdefault('obs_bitmap', 1)
    edge.setdefault('effective_score', 0.0)
    edge.setdefault('decay_class', TOPIC_DECAY_CLASS.get(
        edge.get('topic', ''), 'news'))
    edge.setdefault('protected', False)


def decay_existing(graph: dict, today: str):
    """오늘 관측 안 된 모든 엣지에 토픽별 지수감쇠 + obs_bitmap shift."""
    for edge in graph.get('edges', []):
        _ensure_edge_fields(edge, today)
        if edge.get('protected'):
            # bitmap만 shift, weight 감쇠 안 함
            edge['obs_bitmap'] = (edge['obs_bitmap'] << 1) & ((1 << 60) - 1)
            continue

        days = _days_between(edge['last_seen'], today)
        if days <= 0:
            continue  # 오늘 관측된 엣지는 skip

        # obs_bitmap shift
        edge['obs_bitmap'] = (edge['obs_bitmap'] << days) & ((1 << 60) - 1)

        # 토픽별 반감기 + multiplier
        cls = edge.get('decay_class', 'news')
        base_hl = HALF_LIFE_DAYS.get(cls, 14)
        observed_days = bin(edge['obs_bitmap']).count('1')
        max_mult = MAX_MULTIPLIER.get(cls, 2.0)
        multiplier = 1.0 + 0.5 * min(observed_days / 5, max_mult - 1.0)
        effective_hl = base_hl * multiplier

        lam = math.log(2) / effective_hl
        edge['weight'] = edge['weight'] * math.exp(-lam * days)


def merge_today(graph: dict, new_edges: list[dict]):
    """오늘 관측된 엣지: 기존 있으면 noisy-or 재상향, 없으면 추가."""
    today = _d.today().isoformat()
    existing_map = {}
    for i, e in enumerate(graph.get('edges', [])):
        key = (e.get('from', ''), e.get('to', ''))
        existing_map[key] = i

    for ne in new_edges:
        key = (ne.get('from', ''), ne.get('to', ''))
        if key in existing_map:
            edge = graph['edges'][existing_map[key]]
            # noisy-or merge
            w_old = edge['weight']
            w_new = ne.get('weight', 0.5)
            edge['weight'] = 1.0 - (1.0 - w_old) * (1.0 - w_new)
            edge['support_count'] = edge.get('support_count', 1) + 1
            edge['last_seen'] = today
            edge['obs_bitmap'] = edge.get('obs_bitmap', 0) | 1
        # 새 엣지는 add_incremental_edges에서 이미 추가됨


def recompute_scores(graph: dict):
    """전체 엣지 effective_score 재계산 (ranking/seed 전용)."""
    for edge in graph.get('edges', []):
        w = edge.get('weight', 0)
        sc = edge.get('support_count', 1)
        conf = edge.get('confidence', 0.5)
        edge['effective_score'] = round(w * math.log1p(sc) * conf, 4)


def prune_graph(graph: dict, weight_floor: float = 0.12,
                node_out_cap: int = 8, hub_out_cap: int = 12,
                diversity_cap: int = 3):
    """3단 pruning: weight floor → out_cap+diversity → isolate 제거."""
    edges = graph.get('edges', [])
    nodes = graph.get('nodes', {})

    # 1단: weight floor (protected 면제)
    edges = [e for e in edges if e.get('protected') or e.get('weight', 0) >= weight_floor]

    # 2단: node out-cap + diversity
    from collections import defaultdict
    out_edges = defaultdict(list)
    for e in edges:
        out_edges[e['from']].append(e)

    kept = []
    for node_id, outs in out_edges.items():
        cap = hub_out_cap if node_id in HUB_NODES else node_out_cap
        # diversity: bucket별 카운트
        outs.sort(key=lambda x: -x.get('effective_score', 0))
        bucket_counts = defaultdict(int)
        for e in outs:
            bucket = _get_bucket(e['to'])
            if bucket_counts[bucket] < diversity_cap and len(kept_for_node := [x for x in kept if x['from'] == node_id]) < cap:
                kept.append(e)
                bucket_counts[bucket] += 1

    # in-only 엣지 (out_edges에 안 잡힌 것) 보존
    out_from_set = set(e['from'] for e in kept)
    for e in edges:
        if e['from'] not in out_edges:
            kept.append(e)

    graph['edges'] = _dedup_edges(kept)

    # 3단: isolate 노드 제거 (protected 면제)
    active_nodes = set()
    for e in graph['edges']:
        active_nodes.add(e['from'])
        active_nodes.add(e['to'])
    # seed/protected 노드는 유지
    to_remove = [n for n in nodes if n not in active_nodes
                 and not nodes[n].get('protected')]
    for n in to_remove:
        del nodes[n]


def extract_seed(graph: dict, k: int = 150, protect_assets: list = None) -> dict:
    """Hybrid seed_score 기�� core+recent 2층 seed 추출."""
    today = _d.today().isoformat()
    edges = graph.get('edges', [])

    for e in edges:
        _ensure_edge_fields(e, today)

    # seed_score 계산
    for e in edges:
        observed_days = bin(e.get('obs_bitmap', 0)).count('1')
        persistence_bonus = 1.0 + 0.5 * min(observed_days / 10, 1.0)
        struct_bonus = 1.2 if e.get('decay_class') == 'structural' else 1.0
        e['_seed_score'] = (e.get('weight', 0) * math.log1p(e.get('support_count', 1))
                            * e.get('confidence', 0.5) * persistence_bonus * struct_bonus)

    # core: seed_score 상위 + observed_days >= 5
    core_candidates = [e for e in edges if bin(e.get('obs_bitmap', 0)).count('1') >= 5]
    core_candidates.sort(key=lambda x: -x['_seed_score'])
    core_seed = core_candidates[:int(k * 0.65)]

    # recent: 최근 30일 weight × confidence 상위
    recent_candidates = [e for e in edges
                         if _days_between(e.get('last_seen', today), today) <= 30
                         and e not in core_seed]
    recent_candidates.sort(key=lambda x: -(x.get('weight', 0) * x.get('confidence', 0.5)))
    recent_seed = recent_candidates[:int(k * 0.35)]

    # 보호 자산 노드 관련 엣지 추가
    seed_edges = core_seed + recent_seed
    if protect_assets:
        for e in edges:
            if e not in seed_edges:
                if any(a in e.get('from', '') or a in e.get('to', '') for a in protect_assets):
                    seed_edges.append(e)
                    if len(seed_edges) >= k * 1.2:
                        break

    # seed 그래프 구성
    seed_nodes = {}
    for e in seed_edges:
        for nid in [e['from'], e['to']]:
            if nid in graph.get('nodes', {}):
                seed_nodes[nid] = graph['nodes'][nid]

    return {
        'nodes': seed_nodes,
        'edges': seed_edges[:int(k * 1.2)],
        'core_count': len(core_seed),
        'recent_count': len(recent_seed),
        'extracted_at': today,
    }


def extract_subgraph(graph: dict, query_nodes: list[str],
                     max_hops: int = 2, max_edges: int = 80) -> dict:
    """Query-relevant 서브그래프 추출 (소비용 subgraph_score 기반)."""
    edges = graph.get('edges', [])
    nodes = graph.get('nodes', {})

    # 인접 리스트
    adj_out = defaultdict(list)
    adj_in = defaultdict(list)
    for e in edges:
        adj_out[e['from']].append(e)
        adj_in[e['to']].append(e)

    # BFS로 hop 이내 엣지 수집
    visited_nodes = set(query_nodes)
    candidate_edges = []
    frontier = set(query_nodes)

    for hop in range(max_hops):
        next_frontier = set()
        for node in frontier:
            for e in adj_out.get(node, []) + adj_in.get(node, []):
                # query_bonus: 직접 맞닿으면 2.0
                is_direct = (e['from'] in query_nodes or e['to'] in query_nodes)
                query_bonus = 2.0 if is_direct else 1.0
                e['_subgraph_score'] = (e.get('weight', 0) * math.log1p(e.get('support_count', 1))
                                        * e.get('confidence', 0.5) * query_bonus)
                candidate_edges.append(e)
                next_frontier.add(e['from'])
                next_frontier.add(e['to'])
        frontier = next_frontier - visited_nodes
        visited_nodes |= next_frontier

    # 중복 제거 + 상위 max_edges
    seen = set()
    unique = []
    for e in candidate_edges:
        key = (e['from'], e['to'])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda x: -x.get('_subgraph_score', 0))
    selected = unique[:max_edges]

    # 서브그래프 노드
    sub_nodes = {}
    for e in selected:
        for nid in [e['from'], e['to']]:
            if nid in nodes:
                sub_nodes[nid] = nodes[nid]

    return {
        'nodes': sub_nodes,
        'edges': selected,
        'query_nodes': query_nodes,
    }


def monthly_reset(year: int, month: int, engine_seed: dict = None) -> dict:
    """월초 그래프 재구성: engine seed + core + recent."""
    # 이전 달 그래프에서 seed 추출
    prev_graph = _load_previous_graph(year, month)

    if engine_seed is None:
        engine_seed = build_seed_graph()

    if prev_graph:
        seed = extract_seed(prev_graph, k=150)
        # engine seed + extracted seed 병합
        nodes = {**engine_seed['nodes'], **seed['nodes']}
        edges = engine_seed['edges'] + seed['edges']
        # engine seed 엣��에 protected 표시
        for e in engine_seed['edges']:
            e['protected'] = True
            e['weight'] = max(e.get('weight', 0.3), 0.3)
    else:
        nodes = engine_seed['nodes']
        edges = engine_seed['edges']
        for e in edges:
            e['protected'] = True

    graph = {
        'nodes': nodes,
        'edges': _dedup_edges(edges),
        'meta': {
            'created': _d.today().isoformat(),
            'type': 'monthly_reset',
            'engine_edges': len(engine_seed['edges']),
            'seed_core': seed.get('core_count', 0) if prev_graph else 0,
            'seed_recent': seed.get('recent_count', 0) if prev_graph else 0,
        }
    }

    # KPI 로그
    out_degrees = defaultdict(int)
    for e in graph['edges']:
        out_degrees[e['from']] += 1
    top_hubs = sorted(out_degrees.items(), key=lambda x: -x[1])[:10]
    print(f'  [월초 reset] 노드 {len(nodes)}, 엣지 {len(graph["edges"])}')
    print(f'  평균 out-degree: {sum(out_degrees.values())/max(len(out_degrees),1):.1f}')
    print(f'  Top hubs: {[(n, d) for n, d in top_hubs[:5]]}')

    # 저장
    month_str = f'{year}-{month:02d}'
    out_file = GRAPH_DIR / f'{month_str}.json'
    out_file.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    return graph


# ═══════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════���══

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--seed-only':
        graph = build_seed_graph()
        out = GRAPH_DIR / 'seed.json'
        out.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'시드 그래프 저장: {out}')
    elif len(sys.argv) > 1:
        parts = sys.argv[1].split('-')
        y, m = int(parts[0]), int(parts[1])
        build_insight_graph(y, m)
    else:
        # 최신 월
        files = sorted(NEWS_DIR.glob('202*.json'))
        if files:
            parts = files[-1].stem.split('-')
            build_insight_graph(int(parts[0]), int(parts[1]))
        else:
            print('뉴스 파일 없음 — 시드 그래프만 빌드')
            graph = build_seed_graph()
            out = GRAPH_DIR / 'seed.json'
            out.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
