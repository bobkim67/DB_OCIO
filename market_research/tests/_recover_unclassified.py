# -*- coding: utf-8 -*-
"""filter 통과 미분류 기사 LLM 재분류 복구 스크립트.

대상: _filter_reason 없고 _classified_topics == [] 인 기사 중
      현재 is_macro_financial() 통과하는 것.

사용법:
    python market_research/tests/_recover_unclassified.py           # 전체
    python market_research/tests/_recover_unclassified.py 2026-03   # 특정 월
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from market_research.analyze.news_classifier import (
    is_macro_financial, classify_batch, TOPIC_TAXONOMY)
from market_research.core.json_utils import safe_write_news_json

NEWS = Path(__file__).resolve().parent.parent / 'data' / 'news'


def recover_month(month: str):
    mf = NEWS / f'{month}.json'
    if not mf.exists():
        print(f'{month}: 파일 없음')
        return 0

    raw = json.loads(mf.read_text(encoding='utf-8'))
    articles = raw.get('articles', [])

    # 복구 대상 추출
    queue = []
    queue_indices = []
    for i, a in enumerate(articles):
        if a.get('_filter_reason'):
            continue
        topics = a.get('_classified_topics')
        if topics == [] or topics is None:
            is_fin, _ = is_macro_financial(a)
            if is_fin:
                queue.append(a)
                queue_indices.append(i)

    if not queue:
        print(f'{month}: 복구 대상 0건')
        return 0

    print(f'{month}: {len(queue)}건 재분류 중...', end='', flush=True)

    # 배치 분류 (30건씩)
    classified = 0
    BATCH = 30
    for start in range(0, len(queue), BATCH):
        batch = queue[start:start + BATCH]
        # _classified_topics 키를 일시 제거하여 classify_batch가 처리하도록
        for a in batch:
            a.pop('_classified_topics', None)
        classify_batch(batch)
        classified += sum(1 for a in batch if a.get('_classified_topics'))
        if (start // BATCH) % 10 == 0:
            print('.', end='', flush=True)
        time.sleep(0.1)

    print(f' 완료 → {classified}건 분류')

    raw['articles'] = articles
    safe_write_news_json(mf, raw)
    return classified


if __name__ == '__main__':
    months = sys.argv[1:] if len(sys.argv) > 1 else ['2026-01', '2026-02', '2026-03', '2026-04']
    total = 0
    for m in months:
        total += recover_month(m)
    print(f'\n총 {total}건 복구')
    print('다음: dedupe/salience 재정제 → gold eval 재실행')
