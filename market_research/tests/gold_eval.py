# -*- coding: utf-8 -*-
"""
Gold Evaluation Set — 정답 기반 분류/정제 품질 검증
===================================================

50건 샘플을 라벨링하여 precision/recall 측정.
라벨링: data/eval/gold_set.json (수동)
평가: 이 스크립트 실행

사용법:
    # 1. 샘플 생성 (최초 1회)
    python -m market_research.tests.gold_eval --generate

    # 2. 수동 라벨링 후 평가
    python -m market_research.tests.gold_eval --evaluate
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
NEWS_DIR = BASE_DIR / 'data' / 'news'
EVAL_DIR = BASE_DIR / 'data' / 'eval'
GOLD_FILE = EVAL_DIR / 'gold_set.json'


def generate_sample(n: int = 50, month: str = '2026-03', seed: int = 42):
    """월별 뉴스에서 stratified 샘플 추출 → gold_set.json 생성.

    샘플링 전략:
    - 분류된 기사 30건 (다양한 토픽/intensity)
    - 미분류 기사 10건
    - 교차보도 기사 5건
    - 고 salience 기사 5건
    """
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    data = json.loads((NEWS_DIR / f'{month}.json').read_text(encoding='utf-8'))
    articles = data.get('articles', [])

    classified = [a for a in articles if a.get('_classified_topics')]
    unclassified = [a for a in articles if a.get('_classified_topics') == []]
    multi_source = [a for a in articles if a.get('_event_source_count', 0) >= 3]
    high_sal = sorted(
        [a for a in articles if a.get('_event_salience', 0) >= 0.6],
        key=lambda x: -x.get('_event_salience', 0))

    random.seed(seed)
    samples = []

    # 분류된 기사 — 토픽별 최소 1건 보장
    topics = Counter(a.get('primary_topic', '') for a in classified if a.get('primary_topic'))
    topic_pool = {}
    for a in classified:
        pt = a.get('primary_topic', '')
        if pt:
            topic_pool.setdefault(pt, []).append(a)

    # 각 토픽에서 1건씩
    for topic in list(topics.keys())[:15]:
        pool = topic_pool.get(topic, [])
        if pool:
            samples.append(random.choice(pool))

    # 나머지는 랜덤
    remaining_classified = [a for a in classified if a not in samples]
    samples.extend(random.sample(remaining_classified, min(15, len(remaining_classified))))

    # 미분류
    samples.extend(random.sample(unclassified, min(10, len(unclassified))))

    # 교차보도
    multi_not_in = [a for a in multi_source if a not in samples]
    samples.extend(random.sample(multi_not_in, min(5, len(multi_not_in))))

    # 고 salience
    high_not_in = [a for a in high_sal if a not in samples]
    samples.extend(high_not_in[:5])

    # 총 n건으로 자르기
    samples = samples[:n]

    # gold set 구조 생성
    gold = []
    for i, a in enumerate(samples):
        gold.append({
            'id': i + 1,
            'article_id': a.get('_article_id', ''),
            'title': a.get('title', ''),
            'description': a.get('description', '')[:200],
            'date': a.get('date', ''),
            'source': a.get('source', ''),
            # 시스템 분류 결과 (참고용)
            'system_primary_topic': a.get('primary_topic', ''),
            'system_intensity': a.get('intensity', 0),
            'system_direction': a.get('direction', ''),
            'system_salience': a.get('_event_salience', 0),
            'system_is_primary': a.get('is_primary', True),
            'system_event_source_count': a.get('_event_source_count', 0),
            'system_fallback': a.get('_fallback_classified', False),
            # === 수동 라벨링 필드 (사람이 채움) ===
            'label_is_financial': None,           # True/False: 거시 금융 관련 기사인가 (개별종목/상품홍보 제외)
            'label_primary_topic': None,          # 정답 토픽 — "시장 영향 자산" 기준 (21개 중 또는 '' = 비금융)
            'label_direction': None,              # positive/negative/neutral
            'label_topic_correct': None,          # True/False: system 토픽이 맞는가
            'label_intensity_reasonable': None,    # True/False: system intensity가 합리적인가
            # dedup 3분할
            'label_exact_duplicate_correct': None, # True/False: 같은 기사 중복 판정이 맞는가
            'label_event_cluster_correct': None,   # True/False: 같은 사건 그룹핑이 맞는가
            'label_primary_pick_correct': None,    # True/False: 그룹 내 대표기사 선정이 맞는가
            'label_notes': '',                    # 자유 메모
        })

    GOLD_FILE.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Gold set 생성: {GOLD_FILE}')
    print(f'  총 {len(gold)}건')
    print(f'  분류 {sum(1 for g in gold if g["system_primary_topic"])}건, '
          f'미분류 {sum(1 for g in gold if not g["system_primary_topic"])}건')
    print(f'  교차보도 {sum(1 for g in gold if g["system_event_source_count"]>=3)}건, '
          f'고sal {sum(1 for g in gold if g["system_salience"]>=0.6)}건')
    print(f'\n다음 단계: {GOLD_FILE}을 열어 label_* 필드를 채우세요.')


def _refresh_system_values(gold: list[dict], month: str = '2026-03'):
    """gold set의 system_* 필드를 실제 최신 뉴스 데이터에서 갱신."""
    news_file = NEWS_DIR / f'{month}.json'
    if not news_file.exists():
        print(f'  {news_file} 없음 — system 값 갱신 스킵')
        return
    data = json.loads(news_file.read_text(encoding='utf-8'))
    by_aid = {a.get('_article_id', ''): a for a in data.get('articles', [])}
    updated = 0
    for g in gold:
        actual = by_aid.get(g.get('article_id', ''))
        if actual:
            g['system_primary_topic'] = actual.get('primary_topic', '')
            g['system_intensity'] = actual.get('intensity', 0)
            g['system_direction'] = actual.get('direction', '')
            g['system_salience'] = actual.get('_event_salience', 0)
            g['system_is_primary'] = actual.get('is_primary', True)
            g['system_event_source_count'] = actual.get('_event_source_count', 0)
            g['system_fallback'] = actual.get('_fallback_classified', False)
            g['system_filter_reason'] = actual.get('_filter_reason', '')
            updated += 1
            # primary_pick 자동 재판정
            pp = g.get('label_primary_pick_correct')
            if pp is False and actual.get('is_primary', True):
                g['label_primary_pick_correct'] = True
            # topic_correct 자동 재판정
            sys_t = g['system_primary_topic']
            lab_t = g.get('label_primary_topic', '')
            if lab_t == '' and sys_t == '':
                g['label_topic_correct'] = True
            elif lab_t == '' and sys_t != '':
                g['label_topic_correct'] = False
            elif lab_t != '' and sys_t == '':
                g['label_topic_correct'] = False
            else:
                g['label_topic_correct'] = (sys_t == lab_t)
    if updated:
        GOLD_FILE.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'  system 값 갱신: {updated}/{len(gold)}건')


def evaluate():
    """라벨링된 gold set으로 시스템 분류 품질 평가."""
    if not GOLD_FILE.exists():
        print(f'{GOLD_FILE} 없음. --generate 먼저 실행하세요.')
        return

    gold = json.loads(GOLD_FILE.read_text(encoding='utf-8'))

    # 실행 시점의 최신 system 값으로 자동 갱신
    _refresh_system_values(gold)

    # 라벨링 완료 여부
    labeled = [g for g in gold if g.get('label_is_financial') is not None]
    if not labeled:
        print('라벨링된 항목이 없습니다. label_* 필드를 채우세요.')
        return

    print(f'=== Gold Set 평가 ({len(labeled)}/{len(gold)}건 라벨링됨) ===\n')

    # 1. 분류 정확도 (topic)
    topic_labeled = [g for g in labeled if g.get('label_topic_correct') is not None]
    if topic_labeled:
        correct = sum(1 for g in topic_labeled if g['label_topic_correct'])
        print(f'[토픽 분류 정확도] {correct}/{len(topic_labeled)} = {correct/len(topic_labeled)*100:.1f}%')

    # 2. 금융 관련성 판정
    fin_labeled = [g for g in labeled if g.get('label_is_financial') is not None]
    if fin_labeled:
        # 시스템이 분류한 것 중 실제 금융인 것 (precision)
        sys_classified = [g for g in fin_labeled if g['system_primary_topic']]
        if sys_classified:
            true_pos = sum(1 for g in sys_classified if g['label_is_financial'])
            print(f'[분류 precision] {true_pos}/{len(sys_classified)} = {true_pos/len(sys_classified)*100:.1f}%')

        # 실제 금융인 것 중 시스템이 분류한 것 (recall)
        actual_fin = [g for g in fin_labeled if g['label_is_financial']]
        if actual_fin:
            detected = sum(1 for g in actual_fin if g['system_primary_topic'])
            print(f'[분류 recall] {detected}/{len(actual_fin)} = {detected/len(actual_fin)*100:.1f}%')

    # 3. Intensity 합리성
    int_labeled = [g for g in labeled if g.get('label_intensity_reasonable') is not None]
    if int_labeled:
        reasonable = sum(1 for g in int_labeled if g['label_intensity_reasonable'])
        print(f'[Intensity 합리성] {reasonable}/{len(int_labeled)} = {reasonable/len(int_labeled)*100:.1f}%')

    # 4. Dedup 3분할 정확도
    for field, label in [
        ('label_exact_duplicate_correct', '중복 판정'),
        ('label_event_cluster_correct', '이벤트 그룹핑'),
        ('label_primary_pick_correct', '대표기사 선정'),
    ]:
        sub = [g for g in labeled if g.get(field) is not None]
        if sub:
            correct = sum(1 for g in sub if g[field])
            print(f'[{label}] {correct}/{len(sub)} = {correct/len(sub)*100:.1f}%')

    # 하위호환: label_dedup_correct가 있으면 표시
    dedup_labeled = [g for g in labeled if g.get('label_dedup_correct') is not None]
    if dedup_labeled:
        correct = sum(1 for g in dedup_labeled if g['label_dedup_correct'])
        print(f'[Dedup 통합(legacy)] {correct}/{len(dedup_labeled)} = {correct/len(dedup_labeled)*100:.1f}%')

    # 5. 오분류 상세
    print(f'\n=== 오분류 상세 ===')
    wrong_topic = [g for g in topic_labeled if not g.get('label_topic_correct')]
    for g in wrong_topic[:10]:
        print(f'  [{g["id"]}] system={g["system_primary_topic"]!r} → label={g["label_primary_topic"]!r}')
        print(f'       {g["title"][:60]}')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--generate', action='store_true', help='50건 샘플 생성')
    parser.add_argument('--evaluate', action='store_true', help='라벨링 결과 평가')
    parser.add_argument('--month', default='2026-03', help='대상 월')
    parser.add_argument('-n', type=int, default=50, help='샘플 수')
    args = parser.parse_args()

    if args.generate:
        generate_sample(args.n, args.month)
    elif args.evaluate:
        evaluate()
    else:
        parser.print_help()
