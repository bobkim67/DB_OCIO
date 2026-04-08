# -*- coding: utf-8 -*-
"""
뉴스 기사 중복 제거 + 이벤트 클러스터링

2단계:
A. dedup_group: 같은 기사의 중복 (wire copy, 재전재)
B. event_group: 같은 사건의 다른 보도 (primary_topic 일치 필요)
"""

import hashlib
import re
from collections import defaultdict
from difflib import SequenceMatcher
from urllib.parse import urlparse, urlencode, parse_qs


# ═══════════════════════════════════════════════════════
# A. Dedup Group — 같은 기사 중복 제거
# ═══════════════════════════════════════════════════════

# wire copy 소스 패턴 (재전재 원본)
WIRE_SOURCES = {'Reuters', 'AP', 'AFP', '연합뉴스', 'Yonhap'}


def _normalize_url(url: str) -> str:
    """URL 정규화: query param 제거, trailing slash 통일."""
    try:
        parsed = urlparse(url)
        # 의미 있는 param만 유지 (id, article 등)
        clean = parsed._replace(query='', fragment='').geturl()
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

    # 2차: 제목 prefix 기반 그룹핑 (URL 다르지만 같은 기사)
    prefix_map = defaultdict(list)
    for i, a in enumerate(articles):
        if i in assigned:
            continue
        prefix = _title_prefix(a.get('title', ''))
        if len(prefix) >= 15:  # 너무 짧은 제목은 skip
            prefix_map[prefix].append(i)

    for prefix, indices in prefix_map.items():
        if len(indices) <= 1:
            continue
        # 같은 날짜 기사만 그룹핑
        by_date = defaultdict(list)
        for idx in indices:
            by_date[articles[idx].get('date', '')[:10]].append(idx)

        for date_str, date_indices in by_date.items():
            if len(date_indices) <= 1:
                continue
            gid = f'dedup_{group_counter}'
            group_counter += 1
            for idx in date_indices:
                if idx not in assigned:
                    articles[idx]['_dedup_group_id'] = gid
                    assigned.add(idx)

            # primary: wire 원본 우선, 아니면 가장 긴 description
            wire_indices = [i for i in date_indices if _is_wire_copy(articles[i])]
            if wire_indices:
                best = wire_indices[0]
            else:
                best = max(date_indices, key=lambda i: len(articles[i].get('description', '')))
            for idx in date_indices:
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

def _title_similarity(t1: str, t2: str) -> float:
    """제목 유사도 (0~1)."""
    t1 = t1.lower().strip()
    t2 = t2.lower().strip()
    return SequenceMatcher(None, t1, t2).ratio()


def cluster_events(articles: list[dict]) -> list[dict]:
    """같은 사건의 다른 보도를 event_group_id로 묶기.

    조건 (모두 충족):
    - 날짜 같거나 ±1일
    - 제목 유사도 ≥ 0.3
    - primary_topic 일치 (분류된 기사) 또는 둘 다 미분류

    미분류 기사(topics=[])끼리: event_group_prelim으로 임시 묶음.
    분류 후 topic 일치하는 그룹에 병합.

    Returns: 동일 리스트에 event_group_id, _event_source_count 추가
    """
    # primary 기사만 대상
    primaries = [(i, a) for i, a in enumerate(articles) if a.get('is_primary', True)]

    event_groups = {}  # idx → group_id
    group_counter = 0

    # 날짜별 그룹핑
    by_date = defaultdict(list)
    for i, a in primaries:
        by_date[a.get('date', '')[:10]].append(i)

    # 날짜 쌍 (같은 날 + 인접일)
    dates = sorted(by_date.keys())
    date_pairs = set()
    for d in dates:
        date_pairs.add((d, d))
    for j in range(len(dates) - 1):
        # 인접일인지 확인 (간단히 날짜 차이)
        d1, d2 = dates[j], dates[j + 1]
        try:
            from datetime import datetime
            dt1 = datetime.strptime(d1, '%Y-%m-%d')
            dt2 = datetime.strptime(d2, '%Y-%m-%d')
            if (dt2 - dt1).days <= 1:
                date_pairs.add((d1, d2))
                date_pairs.add((d2, d1))
        except Exception:
            pass

    # 같은 날짜(±1일) 기사들 비교
    for d1, d2 in date_pairs:
        if d1 > d2:
            continue
        indices_1 = by_date.get(d1, [])
        indices_2 = by_date.get(d2, []) if d1 != d2 else []
        all_indices = indices_1 + indices_2

        for i in range(len(all_indices)):
            for j in range(i + 1, len(all_indices)):
                idx_a, idx_b = all_indices[i], all_indices[j]
                a, b = articles[idx_a], articles[idx_b]

                # 같은 source면 skip (dedup에서 이미 처리)
                if a.get('source') == b.get('source'):
                    continue

                # 제목 유사도
                sim = _title_similarity(a.get('title', ''), b.get('title', ''))
                if sim < 0.3:
                    continue

                # topic 일치 확인
                topic_a = a.get('primary_topic', '')
                topic_b = b.get('primary_topic', '')
                if topic_a and topic_b and topic_a != topic_b:
                    continue  # 다른 topic이면 다른 사건

                # 같은 이벤트 → 그룹 병합
                gid_a = event_groups.get(idx_a)
                gid_b = event_groups.get(idx_b)

                if gid_a and gid_b:
                    # 둘 다 이미 그룹 → 작은 ID로 통일
                    if gid_a != gid_b:
                        merge_to = min(gid_a, gid_b)
                        merge_from = max(gid_a, gid_b)
                        for k, v in event_groups.items():
                            if v == merge_from:
                                event_groups[k] = merge_to
                elif gid_a:
                    event_groups[idx_b] = gid_a
                elif gid_b:
                    event_groups[idx_a] = gid_b
                else:
                    gid = f'event_{group_counter}'
                    group_counter += 1
                    event_groups[idx_a] = gid
                    event_groups[idx_b] = gid

    # 미할당: 단독 이벤트
    for i, a in primaries:
        if i not in event_groups:
            event_groups[i] = f'event_{group_counter}'
            group_counter += 1

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

    return articles


# ═══════════════════════════════════════════════════════
# 통합 함수
# ═══════════════════════════════════════════════════════

def process_dedupe_and_events(articles: list[dict]) -> list[dict]:
    """수집 직후 호출: dedup → event clustering → 반환."""
    articles = dedupe_articles(articles)
    articles = cluster_events(articles)
    return articles
