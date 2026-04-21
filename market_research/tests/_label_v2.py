# -*- coding: utf-8 -*-
"""Gold set 라벨링 v2 — 리뷰 피드백 반영

수정 원칙:
1. dedup 3분할: exact_duplicate / event_cluster / primary_pick
2. primary_topic 기준: "시장 영향 자산" (OCIO 운용보고 목적)
3. 개별종목/상품홍보/운용사 브리핑: label_is_financial=False
4. id 7, 10, 18, 19, 30, 50: 재검토 반영
"""
import json
from pathlib import Path

gold = json.loads(Path('market_research/data/eval/gold_set.json').read_text(encoding='utf-8'))

# 기존 label_dedup_correct 제거, 새 3분할 필드 추가
for g in gold:
    g.pop('label_dedup_correct', None)
    g.setdefault('label_exact_duplicate_correct', None)
    g.setdefault('label_event_cluster_correct', None)
    g.setdefault('label_primary_pick_correct', None)

# id → 라벨 (v2)
# ed=exact_dup, ec=event_cluster, pp=primary_pick
L = {
    # 분류된 기사 (1~30)
    1:  dict(fin=True,  topic='금리',         dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    2:  dict(fin=True,  topic='부동산',        dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=False, note='독립 분석기사인데 is_primary=False → primary_pick 오류'),
    3:  dict(fin=True,  topic='유럽_ECB',      dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    4:  dict(fin=True,  topic='금',            dir='positive', tc=False, ir=True,  ed=True, ec=True, pp=False, note='금값 시세 → 금이 primary, 물가 아님'),
    5:  dict(fin=True,  topic='지정학',        dir='positive', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    6:  dict(fin=True,  topic='비트코인_크립토', dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    7:  dict(fin=True,  topic='달러',          dir='positive', tc=True,  ir=True,  ed=True, ec=True, pp=True, note='v2: 달러 강세가 주제 → system 달러 맞음. 안전자산은 과교정'),
    8:  dict(fin=True,  topic='유가_에너지',   dir='positive', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    9:  dict(fin=True,  topic='관세',          dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=False, note='독립 분석기사인데 is_primary=False → primary_pick'),
    10: dict(fin=True,  topic='금',            dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=False, note='v2: "오늘 금시세"류 → intensity 2 자연스러움. ir=True로 수정'),
    11: dict(fin=False, topic='',              dir='',         tc=False, ir=True,  ed=True, ec=True, pp=False, note='v2: 케이뱅크 IPO → 개별종목, 거시뉴스 아님'),
    12: dict(fin=True,  topic='AI_반도체',     dir='positive', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    13: dict(fin=False, topic='',              dir='',         tc=False, ir=False, ed=True, ec=True, pp=True, note='중국 국방비 → 비금융'),
    14: dict(fin=True,  topic='통화정책',      dir='positive', tc=False, ir=True,  ed=True, ec=True, pp=False, note='한은총재 후보 → 통화정책, 유동성_배관 부적절'),
    15: dict(fin=True,  topic='통화정책',      dir='positive', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    16: dict(fin=True,  topic='부동산',        dir='positive', tc=True,  ir=True,  ed=True, ec=True, pp=False),
    17: dict(fin=False, topic='',              dir='',         tc=False, ir=False, ed=True, ec=True, pp=False, note='v2: 증권사 브리핑/상품홍보 → 거시뉴스 아님'),
    18: dict(fin=True,  topic='금리',          dir='negative', tc=False, ir=True,  ed=True, ec=True, pp=True, note='v2: 소비자심리 → 경기/소비, 물가도 금리도 정확하진 않지만 금리가 더 가까움'),
    19: dict(fin=True,  topic='유동성_배관',   dir='positive', tc=True,  ir=True,  ed=True, ec=True, pp=True, note='v2: 비우량 회사채 발행 → 크레딧/유동성 이슈, system 유동성_배관 수용'),
    20: dict(fin=True,  topic='금리',          dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    21: dict(fin=True,  topic='한국_원화',     dir='negative', tc=True,  ir=False, ed=True, ec=True, pp=False, note='정치인 발언 → 환율 언급, intensity 8 과도'),
    22: dict(fin=False, topic='',              dir='',         tc=False, ir=False, ed=True, ec=True, pp=False, note='배터리 시장점유율 → 산업/비금융'),
    23: dict(fin=True,  topic='지정학',        dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=False),
    24: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=False),
    25: dict(fin=False, topic='',              dir='',         tc=False, ir=True,  ed=True, ec=True, pp=False, note='v2: 바이오 IPO → 개별섹터, 거시뉴스 아님'),
    26: dict(fin=True,  topic='금리',          dir='positive', tc=True,  ir=True,  ed=True, ec=True, pp=False),
    27: dict(fin=True,  topic='금리',          dir='negative', tc=False, ir=True,  ed=True, ec=True, pp=False, note='한국 채권시장 → 미국채보다 금리가 정확'),
    28: dict(fin=True,  topic='지정학',        dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=False),
    29: dict(fin=True,  topic='한국_원화',     dir='positive', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    30: dict(fin=False, topic='',              dir='',         tc=False, ir=True,  ed=True, ec=True, pp=True, note='v2: ETF 상품소개 → 거시뉴스 아님. note/label 불일치 수정'),
    # 미분류 기사 (31~40)
    31: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=True, note='미국역사 → 비금융, 시스템도 미분류(정답)'),
    32: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=False, note='포스코 방위기술 → 비금융'),
    33: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=False, note='현대차 공장 → 비금융'),
    34: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=True, note='PyPI 패키지 → 완전비금융'),
    35: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=False, note='AI 전쟁대시보드 → 비금융'),
    36: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=True, note='디스크골프 → 완전비금융'),
    37: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=True, note='일본 자위대 → 비금융'),
    38: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=True, note='호주 여론 → 비금융'),
    39: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=True, note='마약카르텔 → 완전비금융'),
    40: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  ed=True, ec=True, pp=True, note='UFC 도핑 → 완전비금융'),
    # 교차보도+고salience (41~50) — "시장 영향 자산" 기준 적용
    41: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=False, ir=True,  ed=True, ec=True, pp=True, note='유가 상승이 주제 → 유가_에너지 primary (시장영향 기준)'),
    42: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=False, ir=True,  ed=True, ec=True, pp=True, note='에너지 시장 영향 → 유가_에너지 primary'),
    43: dict(fin=False, topic='',              dir='',         tc=False, ir=False, ed=True, ec=True, pp=True, note='이란전쟁 실시간 → 순수 군사, 금융 아님'),
    44: dict(fin=False, topic='',              dir='',         tc=False, ir=False, ed=True, ec=True, pp=False, note='이란 군사위협 → 순수 군사'),
    45: dict(fin=False, topic='',              dir='',         tc=False, ir=False, ed=True, ec=True, pp=True, note='트럼프 외교 → 순수 정치'),
    46: dict(fin=True,  topic='지정학',        dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=True, note='걸프 페트로달러 → 금융+지정학, 지정학 맞음'),
    47: dict(fin=True,  topic='지정학',        dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    48: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=True),
    49: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=True,  ir=True,  ed=True, ec=True, pp=False, note='is_primary=False이지만 독립적 분석 기사'),
    50: dict(fin=True,  topic='환율_USDKRW',  dir='negative', tc=False, ir=True,  ed=True, ec=True, pp=True, note='v2: 루피/Nifty → 환율 영향이 주제. note/label 불일치 수정'),
}

for g in gold:
    i = g['id']
    if i in L:
        d = L[i]
        g['label_is_financial'] = d['fin']
        g['label_primary_topic'] = d['topic']
        g['label_direction'] = d['dir']
        g['label_topic_correct'] = d['tc']
        g['label_intensity_reasonable'] = d['ir']
        g['label_exact_duplicate_correct'] = d['ed']
        g['label_event_cluster_correct'] = d['ec']
        g['label_primary_pick_correct'] = d['pp']
        g['label_notes'] = d.get('note', '')
        # legacy 필드 제거
        g.pop('label_dedup_correct', None)

Path('market_research/data/eval/gold_set.json').write_text(
    json.dumps(gold, ensure_ascii=False, indent=2), encoding='utf-8')
print('v2 라벨링 완료 (50건)')
