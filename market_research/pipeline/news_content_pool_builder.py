# -*- coding: utf-8 -*-
"""
News Content Pool Builder
==========================
월별 뉴스를 임베딩 → 클러스터링하여 반복 테마를 추출하고
Haiku로 테마별 한국어 요약을 생성하는 배치 모듈.

사용법:
    python -m market_research.news_content_pool_builder 2026 3
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

if sys.stdout and sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent
NEWS_DIR = BASE_DIR / 'data' / 'news'
POOL_DIR = BASE_DIR / 'data' / 'news_content_pool'

# HTML 엔티티 클리닝
_HTML_ENTITIES = {
    '&middot;': '·', '&lsquo;': "'", '&rsquo;': "'",
    '&ldquo;': '"', '&rdquo;': '"', '&hellip;': '…',
    '&amp;': '&', '&lt;': '<', '&gt;': '>',
    '&nbsp;': ' ', '&quot;': '"',
}


def _clean_html(text: str) -> str:
    for entity, replacement in _HTML_ENTITIES.items():
        text = text.replace(entity, replacement)
    text = re.sub(r'&#\d+;', '', text)
    return text.strip()


def _get_embedding_model():
    """sentence-transformers 모델 (news_vectordb와 공유)"""
    try:
        from market_research.analyze.news_vectordb import _get_model
        return _get_model()
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'news_vectordb', BASE_DIR / 'news_vectordb.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._get_model()


def _cluster_embeddings(embeddings: np.ndarray, n_clusters: int = 15) -> np.ndarray:
    """KMeans 클러스터링"""
    from sklearn.cluster import KMeans
    n_clusters = min(n_clusters, len(embeddings) // 5)  # 최소 클러스터당 5개
    n_clusters = max(n_clusters, 3)
    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    return km.fit_predict(embeddings)


def _extract_label_keywords(titles: list[str], top_n: int = 5) -> str:
    """타이틀에서 빈도 높은 키워드 추출 → 라벨"""
    stop_words = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
        'to', 'of', 'in', 'for', 'on', 'at', 'by', 'as', 'and', 'or',
        'it', 'its', 'this', 'that', 'with', 'from', 'not', 'but',
        'has', 'have', 'had', 'will', 'would', 'could', 'should',
        'may', 'might', 'can', 'do', 'does', 'did', 'no', 'so',
        'if', 'up', 'out', 'what', 'how', 'why', 'when', 'where',
        'who', 'which', 'all', 'more', 'new', 'says', 'said', 'over',
        'after', 'about', 'into', 'than', 'just', 'also', 'been', 'being',
    }
    words = Counter()
    for title in titles:
        for w in re.findall(r'[A-Za-z가-힣]{2,}', title):
            w_lower = w.lower()
            if w_lower not in stop_words and len(w_lower) > 2:
                words[w_lower] += 1
    top = words.most_common(top_n)
    return ' '.join(w for w, _ in top)


def _haiku_summarize_themes(themes: list[dict]) -> list[dict]:
    """Haiku로 테마별 한국어 요약 생성"""
    try:
        import anthropic
        # API 키: 환경변수 우선, fallback으로 comment_engine
        import os
        ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
        if not ANTHROPIC_API_KEY:
            try:
                from market_research.core.constants import ANTHROPIC_API_KEY
            except ImportError:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    'ce', BASE_DIR / 'comment_engine.py')
                ce = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(ce)
                ANTHROPIC_API_KEY = ce.ANTHROPIC_API_KEY

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # 전체 테마를 한 번에 요약 (비용 절감)
        theme_desc = []
        for i, t in enumerate(themes):
            titles = [a['title'][:80] for a in t['representative_articles'][:3]]
            theme_desc.append(
                f"{i+1}. [{t['label']}] ({t['article_count']}건)\n"
                f"   대표기사: {' / '.join(titles)}"
            )

        prompt = f"""다음은 월간 뉴스에서 추출한 핵심 테마 {len(themes)}개입니다.
각 테마를 운용보고서용 한국어 한 문장(30~50자)으로 요약하세요.

{chr(10).join(theme_desc)}

JSON 배열만 응답: ["테마1 요약", "테마2 요약", ...]"""

        response = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1500,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = response.content[0].text.strip()
        # 마크다운 코드블록 제거
        if text.startswith('```'):
            text = text.split('\n', 1)[-1]  # 첫 줄 (```json) 제거
            if text.endswith('```'):
                text = text[:-3].strip()
        start = text.find('[')
        end = text.rfind(']') + 1
        if start >= 0 and end > start:
            summaries = json.loads(text[start:end])
            print(f'  Haiku 응답: {len(summaries)}개 요약 (기대: {len(themes)}개)')
            if len(summaries) >= len(themes):
                for theme, summary in zip(themes, summaries):
                    theme['summary_kr'] = summary
                return themes
            elif summaries:
                # 개수 불일치여도 있는 만큼 채움
                for theme, summary in zip(themes, summaries):
                    theme['summary_kr'] = summary
                return themes
        else:
            print(f'  Haiku JSON 파싱 실패: {text[:100]}')
    except Exception as exc:
        import traceback
        print(f'  Haiku 요약 실패: {exc}')
        traceback.print_exc()

    # fallback: 라벨 그대로 사용
    for t in themes:
        t['summary_kr'] = t['label']
    return themes


def build_news_content_pool(year: int, month: int) -> dict:
    """월별 뉴스 → 클러스터링 → 핵심 테마 풀 생성"""
    month_str = f'{year}-{month:02d}'
    news_path = NEWS_DIR / f'{month_str}.json'

    if not news_path.exists():
        print(f'  뉴스 파일 없음: {news_path}')
        return {}

    data = json.loads(news_path.read_text(encoding='utf-8'))
    articles = data.get('articles', [])
    if len(articles) < 20:
        print(f'  기사 수 부족: {len(articles)}')
        return {}

    # 텍스트 준비 + HTML 엔티티 클리닝
    texts = []
    valid_articles = []
    for a in articles:
        title = _clean_html(a.get('title', ''))
        desc = _clean_html(a.get('description', ''))
        text = f'{title}. {desc}'.strip()
        if len(text) >= 20:
            a['_clean_title'] = title
            texts.append(text)
            valid_articles.append(a)

    print(f'  {month_str}: {len(texts)}건 임베딩 중...', end='', flush=True)
    model = _get_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False, batch_size=64)
    print(' 완료')

    # 클러스터링
    n_clusters = min(15, max(5, len(texts) // 50))
    labels = _cluster_embeddings(np.array(embeddings), n_clusters)

    # 클러스터별 집계
    cluster_data = {}
    for idx, (article, label) in enumerate(zip(valid_articles, labels)):
        label = int(label)
        if label not in cluster_data:
            cluster_data[label] = {'articles': [], 'indices': []}
        cluster_data[label]['articles'].append(article)
        cluster_data[label]['indices'].append(idx)

    # 테마 구성 (크기순 정렬, 최소 5건 이상)
    themes = []
    for label in sorted(cluster_data, key=lambda k: -len(cluster_data[k]['articles'])):
        cluster = cluster_data[label]
        cluster_articles = cluster['articles']
        if len(cluster_articles) < 5:
            continue

        # centroid에 가장 가까운 기사 = 대표 기사
        cluster_embs = embeddings[cluster['indices']]
        centroid = cluster_embs.mean(axis=0)
        dists = np.linalg.norm(cluster_embs - centroid, axis=1)
        top_indices = dists.argsort()[:5]

        titles = [a.get('_clean_title', a.get('title', '')) for a in cluster_articles]
        keyword_label = _extract_label_keywords(titles)

        representative = []
        for ti in top_indices:
            a = cluster_articles[ti]
            representative.append({
                'title': _clean_html(a.get('title', '')),
                'date': a.get('date', ''),
                'source': a.get('source', ''),
                'url': a.get('url', ''),
            })

        # 소스 분포
        sources = Counter(a.get('source', '?') for a in cluster_articles)

        themes.append({
            'theme_id': len(themes) + 1,
            'label': keyword_label,
            'article_count': len(cluster_articles),
            'representative_articles': representative,
            'top_sources': dict(sources.most_common(3)),
            'summary_kr': '',  # Haiku에서 채워짐
        })

        if len(themes) >= 15:
            break

    # Haiku 한국어 요약
    if themes:
        print(f'  {len(themes)}개 테마 Haiku 요약 중...')
        themes = _haiku_summarize_themes(themes)

    pool = {
        'month': month_str,
        'article_count': len(valid_articles),
        'theme_count': len(themes),
        'themes': themes,
    }

    # 저장
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = POOL_DIR / f'{month_str}.json'
    out_path.write_text(
        json.dumps(pool, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'  news content pool: {month_str} — {len(themes)} themes, '
          f'{len(valid_articles)} articles')

    return pool


if __name__ == '__main__':
    if len(sys.argv) >= 3:
        y, m = int(sys.argv[1]), int(sys.argv[2])
    else:
        from datetime import datetime
        now = datetime.now()
        y, m = now.year, now.month
    build_news_content_pool(y, m)
