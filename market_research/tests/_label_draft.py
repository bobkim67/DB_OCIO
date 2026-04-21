# -*- coding: utf-8 -*-
"""1차 라벨링 초안 작성 (Claude가 제목+설명 기반 판단)"""
import json
from pathlib import Path

gold = json.loads(Path('market_research/data/eval/gold_set.json').read_text(encoding='utf-8'))

# id → {fin, topic, dir, tc, ir, dc, note}
L = {
    1:  dict(fin=True,  topic='금리',         dir='negative', tc=True,  ir=True,  dc=True),
    2:  dict(fin=True,  topic='부동산',        dir='negative', tc=True,  ir=True,  dc=False, note='is_primary=False인데 독립 분석기사'),
    3:  dict(fin=True,  topic='유럽_ECB',      dir='negative', tc=True,  ir=True,  dc=True),
    4:  dict(fin=True,  topic='금',            dir='positive', tc=False, ir=True,  dc=False, note='금값+인플레 -> 물가보다 금이 primary'),
    5:  dict(fin=True,  topic='지정학',        dir='positive', tc=True,  ir=True,  dc=True),
    6:  dict(fin=True,  topic='비트코인_크립토', dir='negative', tc=True,  ir=True,  dc=True),
    7:  dict(fin=True,  topic='안전자산',      dir='negative', tc=False, ir=True,  dc=True,  note='금하락+달러강세 -> 안전자산 더 정확'),
    8:  dict(fin=True,  topic='유가_에너지',   dir='positive', tc=True,  ir=True,  dc=True),
    9:  dict(fin=True,  topic='관세',          dir='negative', tc=True,  ir=True,  dc=False, note='is_primary=False이지만 독립 분석기사'),
    10: dict(fin=True,  topic='금',            dir='negative', tc=True,  ir=False, dc=False, note='intensity 2 너무 낮음'),
    11: dict(fin=True,  topic='한국_원화',     dir='positive', tc=False, ir=True,  dc=False, note='케이뱅크 IPO는 개별종목'),
    12: dict(fin=True,  topic='AI_반도체',     dir='positive', tc=True,  ir=True,  dc=True),
    13: dict(fin=False, topic='',              dir='',         tc=False, ir=False, dc=True,  note='중국 국방비는 지정학/비금융'),
    14: dict(fin=True,  topic='통화정책',      dir='positive', tc=False, ir=True,  dc=False, note='한은총재 후보 -> 통화정책'),
    15: dict(fin=True,  topic='통화정책',      dir='positive', tc=True,  ir=True,  dc=True),
    16: dict(fin=True,  topic='부동산',        dir='positive', tc=True,  ir=True,  dc=False),
    17: dict(fin=True,  topic='한국_원화',     dir='positive', tc=False, ir=False, dc=False, note='증권사 브리핑은 개별종목'),
    18: dict(fin=True,  topic='금리',          dir='negative', tc=False, ir=True,  dc=True,  note='소비자심리->경기, 물가보다 금리'),
    19: dict(fin=True,  topic='금리',          dir='positive', tc=False, ir=True,  dc=True,  note='회사채->금리/크레딧'),
    20: dict(fin=True,  topic='금리',          dir='negative', tc=True,  ir=True,  dc=True),
    21: dict(fin=True,  topic='한국_원화',     dir='negative', tc=True,  ir=False, dc=False, note='intensity 8 과도'),
    22: dict(fin=False, topic='',              dir='',         tc=False, ir=False, dc=False, note='배터리 시장점유율->산업'),
    23: dict(fin=True,  topic='지정학',        dir='negative', tc=True,  ir=True,  dc=False),
    24: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=True,  ir=True,  dc=False),
    25: dict(fin=True,  topic='한국_원화',     dir='positive', tc=False, ir=True,  dc=False, note='바이오 IPO->개별섹터'),
    26: dict(fin=True,  topic='금리',          dir='positive', tc=True,  ir=True,  dc=False),
    27: dict(fin=True,  topic='금리',          dir='negative', tc=False, ir=True,  dc=False, note='한국 채권->미국채보다 금리'),
    28: dict(fin=True,  topic='지정학',        dir='negative', tc=True,  ir=True,  dc=False),
    29: dict(fin=True,  topic='한국_원화',     dir='positive', tc=True,  ir=True,  dc=True),
    30: dict(fin=True,  topic='한국_원화',     dir='positive', tc=False, ir=True,  dc=True,  note='ETF상품->유동성_배관 부적절'),
    31: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=True,  note='미국역사->비금융, 시스템도 미분류'),
    32: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=False, note='포스코 방위기술->비금융'),
    33: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=False, note='현대차 공장->비금융'),
    34: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=True,  note='PyPI패키지->완전비금융'),
    35: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=False, note='AI전쟁대시보드->비금융'),
    36: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=True,  note='디스크골프->완전비금융'),
    37: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=True,  note='일본자위대->비금융'),
    38: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=True,  note='호주여론->비금융'),
    39: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=True,  note='마약카르텔->완전비금융'),
    40: dict(fin=False, topic='',              dir='',         tc=True,  ir=True,  dc=True,  note='UFC도핑->완전비금융'),
    41: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=False, ir=True,  dc=True,  note='유가상승->지정학보다 유가'),
    42: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=False, ir=True,  dc=True,  note='아프리카 에너지->유가 primary'),
    43: dict(fin=False, topic='',              dir='',         tc=False, ir=False, dc=True,  note='이란전쟁실시간->순수군사'),
    44: dict(fin=False, topic='',              dir='',         tc=False, ir=False, dc=False, note='이란군사위협->순수군사'),
    45: dict(fin=False, topic='',              dir='',         tc=False, ir=False, dc=True,  note='트럼프외교->순수정치'),
    46: dict(fin=True,  topic='지정학',        dir='negative', tc=True,  ir=True,  dc=True,  note='걸프페트로달러->금융+지정학'),
    47: dict(fin=True,  topic='지정학',        dir='negative', tc=True,  ir=True,  dc=True),
    48: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=True,  ir=True,  dc=True),
    49: dict(fin=True,  topic='유가_에너지',   dir='negative', tc=True,  ir=True,  dc=False),
    50: dict(fin=True,  topic='지정학',        dir='negative', tc=False, ir=True,  dc=True,  note='루피환율+Nifty->환율이 더 primary할수도'),
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
        g['label_dedup_correct'] = d['dc']
        g['label_notes'] = d.get('note', '')

Path('market_research/data/eval/gold_set.json').write_text(
    json.dumps(gold, ensure_ascii=False, indent=2), encoding='utf-8')
print('50건 1차 라벨링 완료')
