# -*- coding: utf-8 -*-
"""
뉴스 벡터DB — Finnhub/NewsAPI 뉴스를 임베딩하여 자산군별 RAG 검색
"""
import json
import sys
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import chromadb

_BASE = Path(__file__).resolve().parent.parent  # market_research/
NEWS_DIR = _BASE / "data" / "news"
DB_DIR = _BASE / "data" / "news_vectordb"

# 임베딩 모델 (영어 뉴스용, 가벼움)
_model = None

def _get_model():
    global _model
    if _model is None:
        import os, logging, io
        from sentence_transformers import SentenceTransformer

        # tqdm의 stderr.flush() → OSError 방지 (Streamlit 환경)
        # tqdm.std.status_printer가 sys.stderr.flush()를 호출하는데,
        # Streamlit의 stderr가 이를 지원하지 않음 → monkey-patch
        import tqdm.std as _tqdm_std
        _orig_status_printer = _tqdm_std.tqdm.status_printer

        @staticmethod
        def _safe_status_printer(file):
            try:
                return _orig_status_printer(file)
            except OSError:
                # flush 불가 → 아무것도 안 하는 printer 반환
                def _noop(s):
                    pass
                return _noop

        _tqdm_std.tqdm.status_printer = _safe_status_printer

        os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
        os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
        logging.getLogger('transformers').setLevel(logging.ERROR)
        logging.getLogger('sentence_transformers').setLevel(logging.ERROR)
        logging.getLogger('huggingface_hub').setLevel(logging.ERROR)
        import warnings
        warnings.filterwarnings('ignore', message='.*unauthenticated.*HF Hub.*')

        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2', device='cpu')
    return _model


def _get_collection(month=None):
    """chromadb collection 반환"""
    client = chromadb.PersistentClient(path=str(DB_DIR))
    name = f'news_{month}' if month else 'news_all'
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def build_index(month):
    """월별 뉴스 + naver_research adapted → 벡터DB 인덱싱 (Phase 3, 2026-04-22).

    단일 컬렉션 (`news_{month}`) + source_type metadata filter 방침.
    article_stream.load_month_articles 로 두 소스 합쳐서 입력.
    """
    from market_research.analyze.article_stream import (
        load_month_articles, source_of, stream_stats,
    )

    articles = load_month_articles(month)
    if not articles:
        print(f'  {month}: 기사 없음')
        return 0
    print(f'  {month}: stream stats = {stream_stats(articles)}')

    model = _get_model()
    collection = _get_collection(month)

    # 기존 데이터 클리어 후 재구축
    try:
        existing = collection.count()
        if existing > 0:
            collection.delete(where={"month": month})
    except Exception:
        pass

    # 임베딩할 텍스트: 제목 + 설명
    texts = []
    ids = []
    metadatas = []
    seen_ids: set[str] = set()

    for i, a in enumerate(articles):
        title = a.get('title', '')
        desc = a.get('description', '')
        text = f"{title}. {desc}".strip()
        if not text or len(text) < 20:
            continue

        st = source_of(a)
        aid = a.get('_article_id') or f"{month}_{i}"
        # id 충돌 방지: source prefix + article_id
        doc_id = f"{st}:{aid}"
        # 중복 id 회피 (같은 소스 내에서 _article_id 결측 시 fallback 충돌 가능)
        if doc_id in seen_ids:
            doc_id = f"{doc_id}#{i}"
        seen_ids.add(doc_id)

        ids.append(doc_id)
        texts.append(text)

        # 분류 메타 포함 (dedupe/salience 결과)
        primary_topic = a.get('primary_topic', '')
        meta = {
            'month': month,
            'date': a.get('date', ''),
            'source': a.get('source', ''),
            'asset_class': a.get('asset_class', a.get('category', '')),
            'symbol': a.get('symbol', ''),
            'title': title[:200],
            'url': a.get('url', ''),
            'provider': a.get('provider', 'newsapi'),
            'trusted': str(a.get('trusted', False)),
            # 신규: 분류/정제 메타
            'article_id': aid,
            'primary_topic': primary_topic,
            'intensity': str(a.get('intensity', 0)),
            'direction': a.get('direction', ''),
            'event_salience': str(a.get('_event_salience', 0)),
            'is_primary': str(a.get('is_primary', True)),
            'fallback': str(a.get('_fallback_classified', False)),
            # Phase 3 신규: source provenance
            'source_type': st,
            'category': a.get('_raw_category', '') or '',
            'broker': a.get('_raw_broker', '') or '',
        }
        metadatas.append(meta)

    if not texts:
        return 0

    # 배치 임베딩
    print(f'  {month}: {len(texts)}건 임베딩 중...', end='', flush=True)
    embeddings = model.encode(texts, show_progress_bar=False, batch_size=64)

    # chromadb에 배치 추가 (최대 5000건씩)
    for start in range(0, len(texts), 5000):
        end = min(start + 5000, len(texts))
        collection.add(
            ids=ids[start:end],
            documents=texts[start:end],
            embeddings=embeddings[start:end].tolist(),
            metadatas=metadatas[start:end],
        )

    print(f' 완료 ({len(texts)}건)')
    return len(texts)


def search(query, month, top_k=10, asset_class=None, source_type=None):
    """벡터DB 검색 — 유사도 상위 top_k건 반환.

    Phase 3 (2026-04-22): source_type filter 추가.
        source_type='naver_research' | 'news' | None(전체)
    """
    model = _get_model()
    collection = _get_collection(month)

    if collection.count() == 0:
        return []

    query_embedding = model.encode([query])[0].tolist()

    # 필터 조건 (ChromaDB: 단일 key는 평탄, 다중은 $and)
    clauses = []
    if asset_class:
        clauses.append({'asset_class': asset_class})
    if source_type:
        clauses.append({'source_type': source_type})
    if not clauses:
        where = None
    elif len(clauses) == 1:
        where = clauses[0]
    else:
        where = {'$and': clauses}

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=['documents', 'metadatas', 'distances'],
    )

    articles = []
    for i in range(len(results['ids'][0])):
        meta = results['metadatas'][0][i]
        distance = results['distances'][0][i]
        salience = float(meta.get('event_salience', 0))
        # hybrid score: cosine similarity (1-distance) + salience boost
        hybrid_score = (1.0 - distance) + salience * 0.3
        articles.append({
            'id': results['ids'][0][i],
            'title': meta.get('title', ''),
            'date': meta.get('date', ''),
            'source': meta.get('source', ''),
            'asset_class': meta.get('asset_class', ''),
            'primary_topic': meta.get('primary_topic', ''),
            'url': meta.get('url', ''),
            'article_id': meta.get('article_id', results['ids'][0][i]),
            'source_type': meta.get('source_type', ''),
            'category': meta.get('category', ''),
            'broker': meta.get('broker', ''),
            'distance': distance,
            'event_salience': salience,
            'hybrid_score': round(hybrid_score, 4),
            'text': results['documents'][0][i][:200],
        })

    # hybrid_score 순 정렬
    articles.sort(key=lambda x: -x['hybrid_score'])
    return articles


def search_for_factors(month, asset_class, contribution, top_k=10):
    """자산군 기여도 원인 검색용 — 방향성 포함 쿼리 자동 생성 + salience 가중"""
    direction = "상승" if contribution > 0 else "하락"

    # 자산군별 검색 쿼리
    queries = {
        '국내주식': f'Korean stock market KOSPI {direction} reason',
        '해외주식': f'US stock market S&P 500 growth stocks {direction} reason',
        '국내채권': f'Korean bond market interest rate {direction}',
        '해외채권': f'US Treasury bond yield interest rate {direction}',
        '원자재': f'gold oil commodity price {direction} reason',
    }
    query = queries.get(asset_class, f'{asset_class} market {direction}')

    results = search(query, month, top_k=top_k * 3)  # 넉넉히 검색

    # primary 기사만 + 중복 제목 제거 (앞 40자 기준)
    seen = set()
    deduped = []
    for r in results:
        # primary 필터 (vectorDB에 메타 있으면)
        if r.get('is_primary') == 'False':
            continue
        prefix = r['title'][:40]
        if prefix in seen:
            continue
        seen.add(prefix)
        deduped.append(r)
        if len(deduped) >= top_k:
            break

    return deduped


if __name__ == '__main__':
    # 인덱스 빌드
    month = sys.argv[1] if len(sys.argv) > 1 else '2026-03'
    print(f'뉴스 벡터DB 구축: {month}')
    n = build_index(month)
    print(f'  인덱싱 완료: {n}건')

    # 테스트 검색
    print('\n=== 검색 테스트 ===')
    for q in ['US growth stocks decline AI spending', 'gold price surge safe haven',
              'Korean stock market KOSPI rally', 'bond yield interest rate Fed']:
        results = search(q, month, top_k=3)
        print(f'\n"{q}":')
        for r in results:
            print(f'  [{r["date"]}] {r["source"]:15s} {r["title"][:60]} (dist={r["distance"]:.3f})')
