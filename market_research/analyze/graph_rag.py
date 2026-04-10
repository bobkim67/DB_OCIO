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


def _ensure_node(nodes: dict, node_id: str, label: str, topic: str, severity: str):
    """노드가 없으면 추가"""
    if node_id and node_id not in nodes:
        nodes[node_id] = {
            'label': label.strip()[:100],
            'topic': topic,
            'severity': severity,
        }


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

def query_transmission_path(graph: dict, from_entity: str, to_entity: str,
                            max_depth: int = 5) -> list[dict]:
    """
    BFS로 from_entity → to_entity 전이경로 탐색.
    Returns: [{"path": [node1, node2, ...], "confidence": 0.x}, ...]
    """
    nodes = graph.get('nodes', {})
    edges = graph.get('edges', [])

    # 인접 리스트 구축
    adj = defaultdict(list)
    for e in edges:
        adj[e['from']].append((e['to'], e.get('weight', 0.5)))

    from_id = _normalize_node_id(from_entity)
    to_id = _normalize_node_id(to_entity)

    # 부분 매칭: from_entity/to_entity를 포함하는 노드 찾기
    from_candidates = [n for n in nodes if from_id.lower() in n.lower()]
    to_candidates = [n for n in nodes if to_id.lower() in n.lower()]

    if not from_candidates or not to_candidates:
        return []

    all_paths = []
    for start in from_candidates:
        for end in to_candidates:
            if start == end:
                continue
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


def precompute_transmission_paths(graph: dict) -> list[dict]:
    """주요 자산군 간 전이경로 사전 계산"""
    asset_keywords = ['국내주식', '국내채권', '해외주식', '해외채권', '원자재', '통화',
                       'KOSPI', 'SP500', '금리', '환율', '유가', '금']
    trigger_keywords = ['달러_부족', '금리_상승', '유가_급등', '인플레', '위안화', '엔화',
                         '관세', '지정학', '레포']

    paths = []
    for trigger in trigger_keywords:
        for asset in asset_keywords:
            results = query_transmission_path(graph, trigger, asset, max_depth=4)
            for r in results[:2]:  # 트리거당 최대 2경로
                if r['confidence'] > 0.1:
                    paths.append({
                        'trigger': trigger,
                        'target': asset,
                        **r,
                    })

    print(f'  전이경로 사전계산: {len(paths)}개')
    return paths


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

    # Step 2: 뉴스 기반 엔티티/인과 (선택)
    if include_news:
        news_file = NEWS_DIR / f'{month_str}.json'
        if news_file.exists():
            data = json.loads(news_file.read_text(encoding='utf-8'))
            articles = data.get('articles', [])

            # 2-lane: primary + topic-stratified dynamic cap
            primary_articles = [a for a in articles if a.get('is_primary', True)]
            candidates = [a for a in primary_articles if a.get('intensity', 0) >= 5]
            if not candidates:
                candidates = primary_articles[:200]
            significant = _stratified_sample(candidates)

            print(f'  뉴스 엔티티 추출: {len(significant)}건 (stratified, {len(candidates)} 후보)...')
            entity_map = extract_entities_from_news(significant)
            print(f'  엔티티 보유 기사: {len(entity_map)}건')

            # 엔티티 노드 추가 + salience 가중 엣지
            for idx, entities in entity_map.items():
                for ent in entities:
                    ent_id = _normalize_node_id(ent)
                    _ensure_node(graph['nodes'], ent_id, ent, 'news', 'neutral')
                    # 기사의 primary_topic과 연결 (salience 가중)
                    if idx < len(significant):
                        art = significant[idx]
                        if art.get('primary_topic'):
                            topic_id = _normalize_node_id(art['primary_topic'])
                            salience = art.get('_event_salience', 0.3)
                            base_weight = 0.3 + salience * 0.4  # 0.3~0.7
                            if topic_id in graph['nodes']:
                                graph['edges'].append({
                                    'from': ent_id, 'to': topic_id,
                                    'relation': 'mentioned_in',
                                    'weight': round(base_weight, 3),
                                    'source': 'news_entity',
                                })

            # 인과관계 추론
            if entity_map:
                print(f'  인과관계 추론...')
                inferred = infer_causal_edges(entity_map, significant)
                for edge in inferred:
                    _ensure_node(graph['nodes'], edge['from'], edge['from'], 'inferred', 'neutral')
                    _ensure_node(graph['nodes'], edge['to'], edge['to'], 'inferred', 'neutral')
                graph['edges'].extend(inferred)
                print(f'  추론 엣지: {len(inferred)}개')

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

    # Step 3: 전이경로 사전 계산
    graph['transmission_paths'] = precompute_transmission_paths(graph)

    # Step 4: 메타데이터 + 저장
    graph['metadata'] = {
        'month': month_str,
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'node_count': len(graph['nodes']),
        'edge_count': len(graph['edges']),
        'path_count': len(graph['transmission_paths']),
        'seed_edges': sum(1 for e in graph['edges'] if e.get('source') in ('engine_rule', 'worldview', 'indicator_map')),
        'llm_edges': sum(1 for e in graph['edges'] if e.get('source') == 'llm_inferred'),
    }

    out_file = GRAPH_DIR / f'{month_str}.json'
    out_file.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  저장: {out_file}')
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

    entity_map = extract_entities_from_news(primary_new)
    for idx, entities in entity_map.items():
        for ent in entities:
            ent_id = _normalize_node_id(ent)
            _ensure_node(graph['nodes'], ent_id, ent, 'news_daily', 'neutral')

    if entity_map:
        inferred = infer_causal_edges(entity_map, primary_new)
        # salience 기반 엣지 가중치 부스트
        for edge in inferred:
            _ensure_node(graph['nodes'], edge['from'], edge['from'], 'inferred', 'neutral')
            _ensure_node(graph['nodes'], edge['to'], edge['to'], 'inferred', 'neutral')
        graph['edges'].extend(inferred)
        graph['edges'] = _dedup_edges(graph['edges'])

    # Self-Regulating TKG: decay → merge → recompute → prune
    from datetime import date as _date
    _today = _date.today().isoformat()
    decay_existing(graph, _today)
    merge_today(graph, inferred if entity_map else [])
    recompute_scores(graph)
    prune_graph(graph)

    # 전이경로 갱신 (debate가 최신 경로를 참조하도록)
    graph['transmission_paths'] = precompute_transmission_paths(graph)

    # 저장
    graph_file.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
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
