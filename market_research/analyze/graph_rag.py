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

BASE_DIR = Path(__file__).resolve().parent
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

            # significance가 높은 기사만 (이미 분류된 경우)
            significant = [a for a in articles if a.get('intensity', 0) >= 5]
            if not significant:
                significant = articles[:200]  # fallback: 상위 200건

            print(f'  뉴스 엔티티 추출: {len(significant)}건...')
            entity_map = extract_entities_from_news(significant)
            print(f'  엔티티 보유 기사: {len(entity_map)}건')

            # 엔티티 노드 추가
            for idx, entities in entity_map.items():
                for ent in entities:
                    ent_id = _normalize_node_id(ent)
                    _ensure_node(graph['nodes'], ent_id, ent, 'news', 'neutral')
                    # 기사의 primary_topic과 연결
                    if idx < len(articles):
                        art = significant[idx] if idx < len(significant) else None
                        if art and art.get('primary_topic'):
                            topic_id = _normalize_node_id(art['primary_topic'])
                            if topic_id in graph['nodes']:
                                graph['edges'].append({
                                    'from': ent_id, 'to': topic_id,
                                    'relation': 'mentioned_in',
                                    'weight': 0.3, 'source': 'news_entity',
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

    entity_map = extract_entities_from_news(new_articles)
    for idx, entities in entity_map.items():
        for ent in entities:
            ent_id = _normalize_node_id(ent)
            _ensure_node(graph['nodes'], ent_id, ent, 'news_daily', 'neutral')

    if entity_map:
        inferred = infer_causal_edges(entity_map, new_articles)
        for edge in inferred:
            _ensure_node(graph['nodes'], edge['from'], edge['from'], 'inferred', 'neutral')
            _ensure_node(graph['nodes'], edge['to'], edge['to'], 'inferred', 'neutral')
        graph['edges'].extend(inferred)
        graph['edges'] = _dedup_edges(graph['edges'])

    # 저장
    graph_file.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    return graph


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

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
