# -*- coding: utf-8 -*-
"""
Blog Analyst — 블로거(monygeek) ���점 분석 에이전트
===================================================
GraphRAG(시장 컨센서스)와 분리된 블로거 고유 관점 그래프.

1. analysis_worldview.json → 정적 프레임워크 (유로달러 학파)
2. 월별 포스트 원문 → Haiku 인과분석 → 동적 인사이트
3. blog_insight.json 출력 → debate에서 monygeek 에이전트가 참조

사용법:
    python -m market_research.blog_analyst 2026-03
    python -m market_research.blog_analyst              # 최신 ���
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
POSTS_FILE = BASE_DIR / 'data' / 'monygeek' / 'posts.json'
WORLDVIEW_FILE = BASE_DIR / 'data' / 'monygeek' / 'analysis_worldview.json'
INSIGHT_DIR = BASE_DIR / 'data' / 'blog_insight'

INSIGHT_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════
# API 헬퍼
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


def _call_haiku(prompt: str, max_tokens: int = 2000) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=_get_api_key())
    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return response.content[0].text.strip()


def _parse_json_response(text: str):
    from market_research.core.json_utils import parse_json_response
    return parse_json_response(text, expect='array')


# ═══════════════════════════════════════════════════════
# 1. 정적 프레임워크 (worldview)
# ═══════════════════════════════════════════════════════

def load_worldview() -> dict:
    """analysis_worldview.json에서 인과관계 그래프 + 핵심 공리 로드"""
    if not WORLDVIEW_FILE.exists():
        return {}
    wv = json.loads(WORLDVIEW_FILE.read_text(encoding='utf-8'))

    framework = {
        'school': wv.get('core_framework', {}).get('school', ''),
        'central_thesis': wv.get('core_framework', {}).get('central_thesis', ''),
        'key_axioms': wv.get('core_framework', {}).get('key_axioms', []),
        'methodology': wv.get('methodology', {}),
        'causal_chains': {},
        'variable_links': {},
    }

    for var_key, var_info in wv.get('variables', {}).items():
        var_name = var_info.get('name', var_key)
        framework['causal_chains'][var_name] = {
            'chain': var_info.get('causal_chain', ''),
            'core_claim': var_info.get('core_claim', ''),
            'vs_mainstream': var_info.get('vs_mainstream', ''),
            'key_indicators': var_info.get('key_indicators', []),
        }
        framework['variable_links'][var_name] = var_info.get('linked_to', [])

    return framework


# ═══════════════════════════════════════════════════════
# 2. 월별 포스트 인과분석
# ═══════════════════════════════════════════════════════

def _get_monthly_posts(year: int, month: int) -> list[dict]:
    """해당 월 블로그 포스트 필터"""
    if not POSTS_FILE.exists():
        return []
    posts = json.loads(POSTS_FILE.read_text(encoding='utf-8'))
    prefix = f'{year}-{month:02d}'
    monthly = [p for p in posts if p.get('date', '').startswith(prefix)]
    return sorted(monthly, key=lambda x: x.get('date', ''))


def analyze_posts(posts: list[dict], batch_size: int = 5) -> list[dict]:
    """
    포스트 원문 → Haiku 인과분석.
    batch_size개씩 묶어서 처리 (포스트당 ~1,500자, 5개 = ~7,500자).
    """
    all_insights = []

    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        post_texts = []
        for j, p in enumerate(batch):
            title = p.get('title', '')
            content = p.get('content', '')[:2000]  # 포스트당 최�� 2,000자
            date = p.get('date', '')
            post_texts.append(f'[포스트 {j+1}] ({date}) {title}\n{content}')

        prompt = f"""다음은 금융/매크로 블로거의 포스트입니다.
이 블로거는 유로달러 학파(Jeff Snider 계열) 관점에서 분석합니다.

각 포스트에서:
1. 핵심 주장 (1문장)
2. 인과관계 체인 (A → B → C 형식, 최대 5단계)
3. 주류와의 차이점 (있으면)
4. 관련 자산군 영향 (국내주식/국내채권/해외주식/해외채권 중)

{chr(10).join(post_texts)}

JSON 배열만 응답:
[{{"post_id": 1, "date": "2026-03-01", "core_claim": "...", "causal_chain": "A → B → C", "vs_mainstream": "...", "asset_impact": ["해외채권", "통화"], "topics": ["금리", "달러"]}}]"""

        try:
            text = _call_haiku(prompt, max_tokens=2500)
            results = _parse_json_response(text)
            if isinstance(results, list):
                for item in results:
                    idx = item.get('post_id', 1) - 1
                    if 0 <= idx < len(batch):
                        item['title'] = batch[idx].get('title', '')
                        item['date'] = batch[idx].get('date', '')
                        item['url'] = batch[idx].get('url', '')
                all_insights.extend(results)
            print(f'    배치 {i//batch_size + 1}: {len(results) if results else 0}건 분석')
        except Exception as exc:
            print(f'    배치 {i//batch_size + 1} 실패: {exc}')

        time.sleep(0.3)

    return all_insights


# ═══════════════════════════════════════════════════════
# 3. 블로그 인사이트 그래프 구축
# ═══════════════════════════════════════════════════════

def build_blog_insight(year: int, month: int) -> dict:
    """
    월별 블로그 인사이트 빌드.

    1. 정적 프레임워크 (worldview)
    2. 해당 월 포스트 인과분석
    3. 인과 체인 → 그래프 엣지 변환
    4. blog_insight.json 저장
    """
    month_str = f'{year}-{month:02d}'
    print(f'\n── Blog Analyst 빌드: {month_str} ──')

    # Step 1: 정적 프레임워크
    framework = load_worldview()
    print(f'  Worldview: {len(framework.get("causal_chains", {}))} 변수')

    # Step 2: 월별 포스트 분석
    posts = _get_monthly_posts(year, month)
    print(f'  {month_str} 포스트: {len(posts)}건')

    post_insights = []
    if posts:
        print(f'  포스트 인과분석 중...')
        post_insights = analyze_posts(posts)
        print(f'  분석 완료: {len(post_insights)}건')

    # Step 3: 인과 체인 → 엣지 변환
    nodes = {}
    edges = []

    # 3a. worldview causal chains
    for var_name, info in framework.get('causal_chains', {}).items():
        chain = info.get('chain', '')
        steps = [s.strip() for s in chain.split('→') if s.strip()]
        for k in range(len(steps) - 1):
            from_id = _norm(steps[k])
            to_id = _norm(steps[k + 1])
            nodes[from_id] = {'label': steps[k], 'source': 'worldview', 'variable': var_name}
            nodes[to_id] = {'label': steps[k + 1], 'source': 'worldview', 'variable': var_name}
            edges.append({
                'from': from_id, 'to': to_id,
                'relation': 'causes', 'weight': 0.7,
                'source': 'worldview', 'variable': var_name,
            })

    # 3b. worldview linked_to
    for var_name, links in framework.get('variable_links', {}).items():
        var_id = _norm(var_name)
        nodes[var_id] = {'label': var_name, 'source': 'worldview'}
        for link in links:
            link_id = _norm(link)
            nodes[link_id] = {'label': link, 'source': 'worldview'}
            edges.append({
                'from': var_id, 'to': link_id,
                'relation': 'linked', 'weight': 0.4,
                'source': 'worldview',
            })

    # 3c. 월별 포스트 인과 체인
    for insight in post_insights:
        chain = insight.get('causal_chain', '')
        steps = [s.strip() for s in chain.split('→') if s.strip()]
        for k in range(len(steps) - 1):
            from_id = _norm(steps[k])
            to_id = _norm(steps[k + 1])
            nodes[from_id] = {'label': steps[k], 'source': 'post', 'date': insight.get('date', '')}
            nodes[to_id] = {'label': steps[k + 1], 'source': 'post', 'date': insight.get('date', '')}
            edges.append({
                'from': from_id, 'to': to_id,
                'relation': 'causes', 'weight': 0.8,
                'source': 'post', 'date': insight.get('date', ''),
            })

    # 중복 엣지 제거
    seen = {}
    for e in edges:
        key = (e['from'], e['to'])
        if key not in seen or e.get('weight', 0) > seen[key].get('weight', 0):
            seen[key] = e
    edges = list(seen.values())

    # Step 4: 빌드 + 저장
    blog_insight = {
        'month': month_str,
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'framework': {
            'school': framework.get('school', ''),
            'central_thesis': framework.get('central_thesis', ''),
            'key_axioms': framework.get('key_axioms', []),
            'methodology': framework.get('methodology', {}),
        },
        'post_insights': post_insights,
        'graph': {
            'nodes': nodes,
            'edges': edges,
            'node_count': len(nodes),
            'edge_count': len(edges),
        },
        'summary': {
            'post_count': len(posts),
            'insight_count': len(post_insights),
            'worldview_chains': len(framework.get('causal_chains', {})),
            'total_edges': len(edges),
        },
    }

    out_file = INSIGHT_DIR / f'{month_str}.json'
    out_file.write_text(json.dumps(blog_insight, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  저장: {out_file}')
    print(f'  요약: {blog_insight["summary"]}')

    return blog_insight


def _norm(text: str) -> str:
    """노드 ID 정규화"""
    import re
    text = text.strip()
    text = re.sub(r'["\'\(\)]', '', text)
    text = re.sub(r'[\s,/]+', '_', text)
    text = re.sub(r'_+', '_', text)
    return text.strip('_')[:60]


# ════════════════════════════════════════════��══════════
# debate용 컨텍스트 빌더
# ═══════════════════════════════════════════════════════

def build_monygeek_context(year: int, month: int) -> str:
    """
    monygeek debate 에이전트용 컨텍스트 텍스트 생성.
    blog_insight.json에서 핵심 내용 추출.
    """
    month_str = f'{year}-{month:02d}'
    insight_file = INSIGHT_DIR / f'{month_str}.json'

    if not insight_file.exists():
        # 빌드 안 됐으면 worldview만
        fw = load_worldview()
        lines = [
            f'## 블로거 프레임워크: {fw.get("school", "")}',
            f'핵심 논지: {fw.get("central_thesis", "")}',
            '',
            '공리:',
        ]
        for ax in fw.get('key_axioms', [])[:5]:
            lines.append(f'  - {ax}')
        return '\n'.join(lines)

    data = json.loads(insight_file.read_text(encoding='utf-8'))
    fw = data.get('framework', {})
    insights = data.get('post_insights', [])

    lines = [
        f'## 블로거 프레임워크: {fw.get("school", "")}',
        f'핵심 논지: {fw.get("central_thesis", "")}',
        '',
    ]

    # 공리 (최대 3개)
    for ax in fw.get('key_axioms', [])[:3]:
        lines.append(f'  - {ax}')

    # 이번 달 포스트 인사이트
    if insights:
        lines.append(f'\n## {month_str} 블로거 분석 ({len(insights)}건)')
        for ins in insights:
            claim = ins.get('core_claim', '')
            chain = ins.get('causal_chain', '')
            vs = ins.get('vs_mainstream', '')
            date = ins.get('date', '')
            lines.append(f'[{date}] {claim}')
            if chain:
                lines.append(f'  인과: {chain}')
            if vs:
                lines.append(f'  vs 주류: {vs}')

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) > 1:
        parts = sys.argv[1].split('-')
        y, m = int(parts[0]), int(parts[1])
    else:
        from datetime import datetime
        now = datetime.now()
        y, m = now.year, now.month
    build_blog_insight(y, m)
