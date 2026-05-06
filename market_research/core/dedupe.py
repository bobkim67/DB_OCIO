# -*- coding: utf-8 -*-
"""
뉴스 기사 중복 제거 + 이벤트 클러스터링 + 안정 ID 부여

3단계:
A. assign_article_ids: 안정적 article_id (title+date+source hash)
B. dedup_group: 같은 기사의 중복 (wire copy, 재전재)
C. event_group: 같은 사건의 다른 보도 (primary_topic 일치 필요)
"""

import hashlib
import re
from collections import defaultdict
from difflib import SequenceMatcher
from urllib.parse import urlparse, urlencode, parse_qs


# ═══════════════════════════════════════════════════════
# A. Article ID — 안정적 식별자
# ═══════════════════════════════════════════════════════

def _make_article_id(article: dict) -> str:
    """title + date + source 해시 → 12자 hex ID."""
    key = f"{article.get('title', '')}|{article.get('date', '')[:10]}|{article.get('source', '')}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()[:12]


def assign_article_ids(articles: list[dict]) -> list[dict]:
    """모든 기사에 _article_id 부여 (이미 있으면 스킵)."""
    for a in articles:
        if '_article_id' not in a:
            a['_article_id'] = _make_article_id(a)
    return articles


# ═══════════════════════════════════════════════════════
# A. Dedup Group — 같은 기사 중복 제거
# ═══════════════════════════════════════════════════════

# wire copy 소스 패턴 (재전재 원본)
WIRE_SOURCES = {'Reuters', 'AP', 'AFP', '연합뉴스', 'Yonhap'}


def _normalize_url(url: str) -> str:
    """URL 정규화: tracking param만 제거, 나머지 query param은 보존.

    기사 URL의 query param은 대부분 기사 식별용이므로 기본 보존.
    utm_*, ref, from, share 등 tracking param만 제거.
    """
    try:
        parsed = urlparse(url)
        if parsed.query:
            params = parse_qs(parsed.query)
            TRACKING = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_content',
                        'utm_term', 'ref', 'from', 'share', 'fbclid', 'gclid',
                        'mc_cid', 'mc_eid', 'mkt_tok'}
            kept = {k: v[0] if len(v) == 1 else v
                    for k, v in params.items() if k.lower() not in TRACKING}
            if kept:
                clean_query = urlencode(kept, doseq=True)
                clean = parsed._replace(query=clean_query, fragment='').geturl()
            else:
                clean = parsed._replace(query='', fragment='').geturl()
        else:
            clean = parsed._replace(fragment='').geturl()
        return clean.rstrip('/')
    except Exception:
        return url


def _title_prefix(title: str, length: int = 40) -> str:
    """제목 앞 N자 정규화 (대소문자, 공백, 특수문자 통일)."""
    t = re.sub(r'[\s\-–—:]+', ' ', title.strip().lower())
    t = re.sub(r'[^\w\s가-힣]', '', t)
    return t[:length]


def _is_wire_copy(article: dict) -> bool:
    """wire 통신사 재전재 감지."""
    source = article.get('source', '')
    title = article.get('title', '')
    # 제목 끝에 "- Reuters", "| AP" 등
    for wire in WIRE_SOURCES:
        if wire.lower() in source.lower():
            return True
        if title.rstrip().endswith(f'- {wire}') or title.rstrip().endswith(f'| {wire}'):
            return True
    return False


def dedupe_articles(articles: list[dict]) -> list[dict]:
    """같은 기사 중복 제거 → dedup_group_id + is_primary 부여.

    기준:
    1. URL 정규화 일치
    2. 제목 앞 40자 일치 + 같은 source 1시간 이내
    3. wire copy: 통신사 원본이 primary

    Returns: 동일 리스트에 필드 추가 (in-place + 반환)
    """
    # 그룹 인덱스
    groups = {}  # prefix → group_id
    group_counter = 0

    # 1차: URL 기반 그룹핑
    url_map = defaultdict(list)
    for i, a in enumerate(articles):
        norm_url = _normalize_url(a.get('url', ''))
        if norm_url:
            url_map[norm_url].append(i)

    assigned = set()
    for url, indices in url_map.items():
        if len(indices) > 1:
            gid = f'dedup_{group_counter}'
            group_counter += 1
            for idx in indices:
                articles[idx]['_dedup_group_id'] = gid
                assigned.add(idx)
            # primary: 가장 긴 description을 가진 것
            best = max(indices, key=lambda i: len(articles[i].get('description', '')))
            for idx in indices:
                articles[idx]['is_primary'] = (idx == best)

    # 2차: 제목 prefix 기반 그룹핑 — 강/약 매칭 분리
    # 강매칭: prefix 일치 + SequenceMatcher(전체 제목) >= 0.7 → cross-source 허용
    # 약매칭: prefix 일치만 → 같은 source에서만 허용
    prefix_map = defaultdict(list)
    for i, a in enumerate(articles):
        if i in assigned:
            continue
        prefix = _title_prefix(a.get('title', ''))
        if len(prefix) >= 15:
            prefix_map[prefix].append(i)

    MAX_PREFIX_GROUP = 20  # prefix 그룹 상한 — 초과 시 오매칭으로 간주, 스킵
    for prefix, indices in prefix_map.items():
        if len(indices) <= 1:
            continue
        by_date = defaultdict(list)
        for idx in indices:
            by_date[articles[idx].get('date', '')[:10]].append(idx)

        for date_str, date_indices in by_date.items():
            if len(date_indices) <= 1:
                continue
            if len(date_indices) > MAX_PREFIX_GROUP:
                continue  # prefix 오매칭 — 너무 많은 기사가 같은 prefix

            # 강매칭 시도: 제목 전체 유사도 0.7 이상 → cross-source 허용
            strong_groups = []  # [(idx_a, idx_b), ...]
            matched_strong = set()
            for ii in range(len(date_indices)):
                for jj in range(ii + 1, len(date_indices)):
                    a_idx, b_idx = date_indices[ii], date_indices[jj]
                    sim = SequenceMatcher(
                        None,
                        articles[a_idx].get('title', '').lower(),
                        articles[b_idx].get('title', '').lower(),
                    ).ratio()
                    if sim >= 0.7:
                        strong_groups.append((a_idx, b_idx))
                        matched_strong.add(a_idx)
                        matched_strong.add(b_idx)

            # 강매칭된 기사들 그룹핑
            if strong_groups:
                strong_indices = list(matched_strong)
                gid = f'dedup_{group_counter}'
                group_counter += 1
                for idx in strong_indices:
                    if idx not in assigned:
                        articles[idx]['_dedup_group_id'] = gid
                        assigned.add(idx)
                wire_indices = [i for i in strong_indices if _is_wire_copy(articles[i])]
                best = wire_indices[0] if wire_indices else max(
                    strong_indices, key=lambda i: len(articles[i].get('description', '')))
                for idx in strong_indices:
                    articles[idx]['is_primary'] = (idx == best)

            # 약매칭: 강매칭 안 된 기사 → 같은 source + 제목 유사도 0.5+ (대형 그룹 방지)
            remaining = [idx for idx in date_indices if idx not in assigned]
            by_source = defaultdict(list)
            for idx in remaining:
                by_source[articles[idx].get('source', '')].append(idx)

            for source, source_indices in by_source.items():
                if len(source_indices) <= 1:
                    continue
                # 같은 source여도 제목 유사도 0.5+ 필요 (네이버검색 대형그룹 방지)
                weak_groups = []
                weak_assigned = set()
                for ii in range(len(source_indices)):
                    for jj in range(ii + 1, len(source_indices)):
                        a_idx, b_idx = source_indices[ii], source_indices[jj]
                        sim = SequenceMatcher(
                            None,
                            articles[a_idx].get('title', '').lower(),
                            articles[b_idx].get('title', '').lower(),
                        ).ratio()
                        if sim >= 0.5:
                            weak_groups.append((a_idx, b_idx))
                            weak_assigned.add(a_idx)
                            weak_assigned.add(b_idx)
                if weak_assigned:
                    gid = f'dedup_{group_counter}'
                    group_counter += 1
                    for idx in weak_assigned:
                        if idx not in assigned:
                            articles[idx]['_dedup_group_id'] = gid
                            assigned.add(idx)
                    best = max(list(weak_assigned), key=lambda i: len(articles[i].get('description', '')))
                    for idx in weak_assigned:
                        articles[idx]['is_primary'] = (idx == best)

    # 미할당 기사: 단독 그룹, primary=True
    for i, a in enumerate(articles):
        if i not in assigned:
            a['_dedup_group_id'] = f'dedup_{group_counter}'
            a['is_primary'] = True
            group_counter += 1

    return articles


# ═══════════════════════════════════════════════════════
# B. Event Group — 같은 사건의 다른 보도
# ═══════════════════════════════════════════════════════

# Union-Find (그룹 병합용)
class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # 작은 값을 root로 (안정적 그룹 ID)
            if ra > rb:
                ra, rb = rb, ra
            self.parent[rb] = ra


_STOPWORDS = {
    'the', 'is', 'at', 'in', 'on', 'of', 'to', 'for', 'and', 'or', 'as',
    'by', 'an', 'it', 'its', 'be', 'are', 'was', 'has', 'have', 'had',
    'this', 'that', 'with', 'from', 'not', 'but', 'can', 'all', 'will',
    'more', 'how', 'what', 'when', 'who', 'why', 'new', 'says', 'could',
    'after', 'over', 'into', 'than', 'about', 'just', 'out', 'been', 'here',
}


def _title_words(title: str) -> set:
    """제목 → 정규화된 단어 집합 (Jaccard pre-filter용). 불용어 제거."""
    t = re.sub(r'[^\w\s가-힣]', '', title.strip().lower())
    words = set(t.split())
    return {w for w in words if len(w) > 1 and w not in _STOPWORDS}


def _jaccard(s1: set, s2: set) -> float:
    """Jaccard similarity."""
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


# ── 인접 토픽 그룹 (같은 사건이 다른 topic으로 분류될 수 있는 관련 토픽) ──
# V2 Taxonomy 기준 인접 토픽 그룹
TOPIC_NEIGHBORS = {}
for _group in [
    {'금리_채권', '통화정책'},
    {'물가_인플레이션', '금리_채권', '경기_소비'},
    {'환율_FX', '달러_글로벌유동성'},
    {'에너지_원자재', '지정학'},
    {'관세_무역', '지정학'},
    {'테크_AI_반도체', '경기_소비'},
    {'귀금속_금', '지정학'},
    {'달러_글로벌유동성', '유동성_크레딧'},
]:
    for _t in _group:
        TOPIC_NEIGHBORS.setdefault(_t, set()).update(_group - {_t})


def cluster_events(articles: list[dict]) -> list[dict]:
    """같은 사건의 다른 보도를 event_group_id로 묶기.

    조건 (모두 충족):
    - 날짜 같거나 ±1일
    - 제목 단어 Jaccard ≥ 0.15 (같은 topic) 또는 ≥ 0.20 (인접 topic)
    - SequenceMatcher ≥ 0.3
    - primary_topic 일치 또는 TOPIC_NEIGHBORS 내 인접

    최적화:
    - (date, topic) 버킷으로 비교 범위 축소
    - Jaccard pre-filter로 SequenceMatcher 호출 최소화
    - Union-Find로 그룹 병합 O(α(n))

    Returns: 동일 리스트에 event_group_id, _event_source_count 추가
    """
    from datetime import datetime as _dt

    # primary 기사만 대상
    primaries = [(i, a) for i, a in enumerate(articles) if a.get('is_primary', True)]

    # 제목 단어 집합 사전 계산
    title_word_cache = {}
    for i, a in primaries:
        title_word_cache[i] = _title_words(a.get('title', ''))

    uf = _UnionFind()
    for i, _ in primaries:
        uf.find(i)  # 초기화

    # (date, topic) → [indices] 버킷
    # 미분류(topic='')는 event_group 대상 제외 — 오클러스터 방지
    bucket = defaultdict(list)
    date_set = set()
    for i, a in primaries:
        d = a.get('date', '')[:10]
        topic = a.get('primary_topic', '')
        if not topic:
            continue
        bucket[(d, topic)].append(i)
        date_set.add(d)

    # 인접일 매핑
    dates_sorted = sorted(date_set)
    adjacent = defaultdict(set)
    for d in dates_sorted:
        adjacent[d].add(d)
    for j in range(len(dates_sorted) - 1):
        d1, d2 = dates_sorted[j], dates_sorted[j + 1]
        try:
            if (_dt.strptime(d2, '%Y-%m-%d') - _dt.strptime(d1, '%Y-%m-%d')).days <= 1:
                adjacent[d1].add(d2)
                adjacent[d2].add(d1)
        except Exception:
            pass

    compared = set()
    topics = {topic for (_, topic) in bucket.keys()}

    # 같은 topic 내 비교 + 인접 topic 교차 비교
    for topic in topics:
        # 비교 대상 토픽: 자신 + neighbors
        compare_topics = {topic} | TOPIC_NEIGHBORS.get(topic, set())

        for d1 in dates_sorted:
            indices_1 = bucket.get((d1, topic), [])
            if not indices_1:
                continue
            for d2 in adjacent[d1]:
                if d2 < d1:
                    continue
                for t2 in compare_topics:
                    indices_2 = bucket.get((d2, t2), [])
                    if not indices_2:
                        continue
                    is_cross_topic = (topic != t2)
                    if d1 == d2 and not is_cross_topic:
                        pool = indices_1
                        for ii in range(len(pool)):
                            for jj in range(ii + 1, len(pool)):
                                _compare_and_merge(
                                    pool[ii], pool[jj], articles,
                                    title_word_cache, uf, compared)
                    else:
                        for ii in indices_1:
                            for jj in indices_2:
                                _compare_and_merge(
                                    ii, jj, articles,
                                    title_word_cache, uf, compared,
                                    jaccard_threshold=0.20 if is_cross_topic else 0.15)

    # Union-Find → event_group_id (P1.5-b, F3 fix 2026-05-06)
    # 기존: f'event_{group_counter}' — 순회 순서 의존 sequential counter (비-deterministic).
    #       articles 입력 순서 / Union-Find root 가 달라지면 매번 다른 ID → 같은
    #       cluster 가 매 daily_update 마다 다른 wiki page 로 누적 (배율: 실행 횟수).
    # 변경: cluster 내 모든 article 의 _article_id (sorted) hash → deterministic.
    #       동일 cluster 는 daily_update 재실행 횟수와 무관하게 동일 ID 보장.
    import hashlib as _hashlib

    def _stable_event_group_id(indices: list[int]) -> str:
        """cluster 의 stable hash. _article_id 정렬 후 MD5 10자."""
        aids = sorted(
            (articles[i].get('_article_id')
             or f"{articles[i].get('url', '')}|{articles[i].get('title', '')[:60]}")
            for i in indices
        )
        h = _hashlib.md5('|'.join(aids).encode('utf-8')).hexdigest()
        return f'event_{h[:10]}'

    group_to_indices: dict[int, list[int]] = defaultdict(list)
    for i, _ in primaries:
        group_to_indices[uf.find(i)].append(i)

    root_to_gid = {}
    event_groups = {}
    for root, indices in group_to_indices.items():
        gid = _stable_event_group_id(indices)
        root_to_gid[root] = gid
        for i in indices:
            event_groups[i] = gid

    # event_group_id + source_count 부여
    group_sources = defaultdict(set)
    for idx, gid in event_groups.items():
        group_sources[gid].add(articles[idx].get('source', ''))

    for idx, gid in event_groups.items():
        articles[idx]['_event_group_id'] = gid
        articles[idx]['_event_source_count'] = len(group_sources[gid])

    # non-primary도 자기 dedup_group primary의 event_group 상속
    dedup_to_event = {}
    for i, a in enumerate(articles):
        if a.get('is_primary') and '_event_group_id' in a:
            dedup_to_event[a.get('_dedup_group_id', '')] = (
                a['_event_group_id'], a.get('_event_source_count', 1))

    for i, a in enumerate(articles):
        if not a.get('is_primary') and '_event_group_id' not in a:
            dgid = a.get('_dedup_group_id', '')
            if dgid in dedup_to_event:
                a['_event_group_id'], a['_event_source_count'] = dedup_to_event[dgid]

    # singleton event primary override:
    # event_group에 primary가 0건이면, 가장 긴 description을 primary로 강제
    event_members = defaultdict(list)
    for i, a in enumerate(articles):
        egid = a.get('_event_group_id', '')
        if egid:
            event_members[egid].append(i)

    for egid, indices in event_members.items():
        has_primary = any(articles[i].get('is_primary') for i in indices)
        if not has_primary and indices:
            best = max(indices, key=lambda i: len(articles[i].get('description', '')))
            articles[best]['is_primary'] = True

    return articles


def _compare_and_merge(idx_a, idx_b, articles, title_word_cache, uf, compared,
                       jaccard_threshold=0.15):
    """두 기사 비교 → 조건 충족 시 Union-Find merge."""
    pair = (min(idx_a, idx_b), max(idx_a, idx_b))
    if pair in compared:
        return
    compared.add(pair)

    a, b = articles[idx_a], articles[idx_b]

    # 같은 source면 skip (dedup에서 이미 처리)
    if a.get('source') == b.get('source'):
        return

    # 1차: Jaccard pre-filter (빠름, 교차 토픽 시 임계치 상향)
    words_a = title_word_cache.get(idx_a, set())
    words_b = title_word_cache.get(idx_b, set())
    if _jaccard(words_a, words_b) < jaccard_threshold:
        return

    # 2차: SequenceMatcher (정밀)
    sim = SequenceMatcher(
        None,
        a.get('title', '').lower().strip(),
        b.get('title', '').lower().strip(),
    ).ratio()
    if sim < 0.3:
        return

    uf.union(idx_a, idx_b)


# ═══════════════════════════════════════════════════════
# 통합 함수
# ═══════════════════════════════════════════════════════

def process_dedupe_and_events(articles: list[dict]) -> list[dict]:
    """수집 직후 호출: article_id → dedup → event clustering → 반환."""
    articles = assign_article_ids(articles)
    articles = dedupe_articles(articles)
    articles = cluster_events(articles)
    return articles
