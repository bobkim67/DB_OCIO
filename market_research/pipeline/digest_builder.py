"""
Blog Monthly Digest Builder
============================
monygeek 블로그 포스팅에서 월별 구조화된 요약을 추출하는 파이프라인.
규칙 기반(키워드 매칭 + 정규식) — LLM API 호출 없음.

사용법:
    python -m market_research.digest_builder              # 전체 27개월
    python -m market_research.digest_builder 2026 2       # 단일 월
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Windows cp949 stdout 호환
sys.stdout.reconfigure(encoding='utf-8')

# ═══════════════════════════════════════════════════════
# 경로
# ═══════════════════════════════════════════════════════
BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
POSTS_FILE = BASE_DIR / 'data' / 'monygeek' / 'posts.json'
DIGEST_DIR = BASE_DIR / 'data' / 'monygeek' / 'monthly_digests'

# ═══════════════════════════════════════════════════════
# engine.py 에서 TOPIC_KEYWORDS 임포트
# ═══════════════════════════════════════════════════════
try:
    from market_research.analyze.engine import TOPIC_KEYWORDS
except ImportError:
    # 직접 실행 시 fallback
    sys.path.insert(0, str(BASE_DIR.parent))
    from market_research.analyze.engine import TOPIC_KEYWORDS

# ═══════════════════════════════════════════════════════
# 토픽 → 자산군 매핑
# ═══════════════════════════════════════════════════════
TOPIC_TO_ASSETS = {
    '금리': [
        ('금리', 'Fed'), ('금리', 'BOK'), ('채권', '미국'), ('채권', '글로벌'),
    ],
    '달러': [
        ('통화', 'DXY'), ('통화', 'USD/KRW'),
    ],
    '이민_노동': [
        ('주식', 'S&P500'), ('주식', '글로벌'),
    ],
    '물가': [
        ('금리', 'Fed'), ('채권', '미국'), ('채권', '글로벌'),
    ],
    '관세': [
        ('주식', '글로벌'), ('주식', 'S&P500'), ('주식', '신흥국'), ('통화', 'DXY'),
    ],
    '안전자산': [
        ('대체', '금'), ('채권', '미국'), ('주식', '글로벌'),
    ],
    '미국채': [
        ('채권', '미국'), ('채권', '글로벌'), ('금리', 'Fed'),
    ],
    '엔화_캐리': [
        ('통화', 'JPY'), ('금리', 'BOJ'), ('주식', '글로벌'),
    ],
    '중국_위안화': [
        ('통화', 'CNY'), ('주식', '신흥국'), ('주식', 'KOSPI'),
    ],
    '유로달러': [
        ('통화', 'DXY'), ('금리', 'Fed'), ('채권', '글로벌'),
    ],
    '유가_에너지': [
        ('대체', 'WTI'), ('주식', '글로벌'),
    ],
    'AI_반도체': [
        ('주식', '미국성장주'), ('주식', 'S&P500'), ('주식', 'KOSPI'),
    ],
    '한국_원화': [
        ('통화', 'USD/KRW'), ('주식', 'KOSPI'),
    ],
    '유럽_ECB': [
        ('금리', 'ECB'), ('주식', '미국외선진국'), ('통화', 'DXY'),
    ],
    '부동산': [
        ('대체', '리츠'),
    ],
    '저출산_인구': [
        ('주식', 'KOSPI'),
    ],
    '비트코인_크립토': [],  # 우리 자산군 범위 밖 — 기록만
    '금': [
        ('대체', '금'),
    ],
}

# ═══════════════════════════════════════════════════════
# 감성 키워드 (방향 판단)
# ═══════════════════════════════════════════════════════
_BULLISH_KW = [
    '상승', '강세', '양호', '반등', '회복', '확대', '개선', '호조', '상향',
    '돌파', '랠리', '서프라이즈', '호재', '완화', '부양', '성장',
    '긍정', '사상최고', '최고치', '급등', '폭등', '낙관', '르네상스',
]
_BEARISH_KW = [
    '하락', '약세', '부진', '침체', '위축', '악화', '둔화', '하향',
    '급락', '폭락', '우려', '리스크', '경고', '위기', '충격', '붕괴',
    '부정', '스트레스', '긴축', '비관', '공포', '기근', '스태그플레이션',
    '매도', '이탈', '하방', '취약',
]

# ═══════════════════════════════════════════════════════
# 숫자/데이터포인트 추출 정규식
# ═══════════════════════════════════════════════════════
_RE_PERCENT = re.compile(r'[\-+]?\d+\.?\d*\s*%')
_RE_PRICE_LEVEL = re.compile(
    r'(?:(?:달러|원|엔|위안|유로|포인트|bp|bps|pt)\s*)?'
    r'[\-+]?\d[\d,]*\.?\d*'
    r'(?:\s*(?:달러|원|엔|위안|유로|포인트|bp|bps|pt|조|억|만))?',
)
_RE_NUMBER_SENTENCE = re.compile(
    r'[^.!?\n]*(?:\d+\.?\d*\s*(?:%|bp|bps|포인트|달러|원|조|억))[^.!?\n]*[.!?]?'
)

# 이벤트 추출용 — 날짜 패턴 + 고유명사/기관 + 동사
_RE_DATE_MENTION = re.compile(
    r'\d{4}[년./-]\s*\d{1,2}[월./-]\s*\d{1,2}[일.]?'
    r'|\d{1,2}[월./-]\s*\d{1,2}[일.]?'
    r'|(?:지난|이번|다음|전|후)\s*(?:주|월|분기|해|년)'
)
_RE_EVENT_SENTENCE = re.compile(
    r'[^.!?\n]*(?:'
    r'발표|결정|인상|인하|동결|회의|선언|합의|발사|선거|사임|임명|출범'
    r'|전쟁|침공|위기|폭락|폭등|제재|관세|서명|체결|협정'
    r')[^.!?\n]*[.!?]?'
)


# ═══════════════════════════════════════════════════════
# 헬퍼 함수
# ═══════════════════════════════════════════════════════

def _tag_topics(title: str, content: str) -> dict[str, int]:
    """키워드 매칭으로 토픽 태깅 (engine.py tag_topics 동일 로직)."""
    text = (title + ' ' + content).lower()
    topics = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score >= 2:
            topics[topic] = score
    return topics


def _split_sentences(text: str) -> list[str]:
    """텍스트를 문장 단위로 분리."""
    # 한국어 블로그 — 줄바꿈 + 마침표/물음표/느낌표
    sents = re.split(r'[.!?]\s+|\n+', text)
    return [s.strip() for s in sents if len(s.strip()) > 10]


def _extract_data_points(text: str) -> list[str]:
    """숫자/데이터 포인트가 포함된 문장 추출."""
    matches = _RE_NUMBER_SENTENCE.findall(text)
    # 중복 제거, 길이 제한
    seen = set()
    result = []
    for m in matches:
        m = m.strip()
        if len(m) < 10 or len(m) > 200:
            continue
        short = m[:50]
        if short not in seen:
            seen.add(short)
            result.append(m)
    return result[:20]  # 월별 최대 20개


def _extract_events(text: str) -> list[str]:
    """이벤트 문장 추출 (날짜 언급 + 행위 동사)."""
    events = []
    sents = _split_sentences(text)
    for s in sents:
        has_date = _RE_DATE_MENTION.search(s)
        has_event = _RE_EVENT_SENTENCE.match(s)
        if has_date or has_event:
            clean = s.strip()
            if 15 < len(clean) < 200:
                events.append(clean)
    return events


def _score_direction(sentences: list[str]) -> tuple[str, int, int]:
    """문장 리스트에서 방향(상승/하락/중립) 판단."""
    bull = 0
    bear = 0
    for s in sentences:
        s_lower = s.lower()
        bull += sum(1 for kw in _BULLISH_KW if kw in s_lower)
        bear += sum(1 for kw in _BEARISH_KW if kw in s_lower)
    if bull > bear * 1.3:
        direction = '상승/강세'
    elif bear > bull * 1.3:
        '하락/약세'
        direction = '하락/약세'
    else:
        direction = '중립/혼조'
    return direction, bull, bear


def _extract_key_claims(sentences: list[str], topic_keywords: list[str]) -> list[str]:
    """토픽 키워드와 감성 키워드가 함께 등장하는 핵심 주장 추출."""
    claims = []
    sentiment_kw = _BULLISH_KW + _BEARISH_KW
    for s in sentences:
        s_lower = s.lower()
        has_topic = any(kw.lower() in s_lower for kw in topic_keywords)
        has_sentiment = any(kw in s_lower for kw in sentiment_kw)
        if has_topic and has_sentiment and 20 < len(s) < 200:
            claims.append(s.strip())
    # 중복 제거
    seen = set()
    unique = []
    for c in claims:
        short = c[:40]
        if short not in seen:
            seen.add(short)
            unique.append(c)
    return unique[:10]  # 토픽당 최대 10개


# ═══════════════════════════════════════════════════════
# 핵심 함수
# ═══════════════════════════════════════════════════════

def build_monthly_digest(year: int, month: int, posts: list[dict] | None = None) -> dict:
    """
    특정 월의 블로그 포스팅에서 구조화된 다이제스트 추출.

    Parameters
    ----------
    year, month : 대상 연/월
    posts : 전체 포스팅 리스트 (None이면 파일에서 로드)

    Returns
    -------
    dict : 월별 다이제스트 (스키마는 모듈 docstring 참조)
    """
    if posts is None:
        posts = json.load(open(POSTS_FILE, 'r', encoding='utf-8'))

    ym = f'{year:04d}-{month:02d}'
    month_posts = [
        p for p in posts
        if p.get('date', '').startswith(ym)
    ]

    if not month_posts:
        return {'month': ym, 'post_count': 0, 'topics': {}, 'asset_mapping': {},
                'cross_themes': [], 'top_posts': []}

    # ── 1. 토픽 태깅 ──
    topic_posts: dict[str, list[dict]] = defaultdict(list)
    for p in month_posts:
        topics = _tag_topics(p.get('title', ''), p.get('content', ''))
        p['_topics'] = topics
        for t in topics:
            topic_posts[t].append(p)

    # ── 2. 토픽별 분석 ──
    topics_result = {}
    for topic, t_posts in sorted(topic_posts.items()):
        # 전체 텍스트 + 문장 분리
        all_sentences = []
        all_events = []
        all_data_points = []
        for p in t_posts:
            text = p.get('content', '')
            sents = _split_sentences(text)
            # 토픽 관련 문장만 필터
            topic_kws = TOPIC_KEYWORDS[topic]
            relevant = [s for s in sents if any(kw.lower() in s.lower() for kw in topic_kws)]
            all_sentences.extend(relevant)
            all_events.extend(_extract_events(text))
            all_data_points.extend(_extract_data_points(text))

        # 방향 판단
        direction, bull_score, bear_score = _score_direction(all_sentences)

        # 핵심 주장
        key_claims = _extract_key_claims(all_sentences, TOPIC_KEYWORDS[topic])

        # 이벤트 중복 제거
        seen_events = set()
        unique_events = []
        for e in all_events:
            short = e[:40]
            if short not in seen_events:
                seen_events.add(short)
                unique_events.append(e)

        # 데이터 포인트 중복 제거
        seen_dp = set()
        unique_dp = []
        for dp in all_data_points:
            short = dp[:40]
            if short not in seen_dp:
                seen_dp.add(short)
                unique_dp.append(dp)

        topics_result[topic] = {
            'post_count': len(t_posts),
            'key_events': unique_events[:10],
            'direction': direction,
            'direction_scores': {'bullish': bull_score, 'bearish': bear_score},
            'key_claims': key_claims[:10],
            'data_points': unique_dp[:15],
        }

    # ── 3. 자산군 매핑 ──
    asset_sentiments: dict[str, dict] = defaultdict(lambda: {'bull': 0, 'bear': 0, 'reasons': []})

    for topic, t_info in topics_result.items():
        asset_list = TOPIC_TO_ASSETS.get(topic, [])
        for asset_class, asset_name in asset_list:
            key = f'{asset_class}:{asset_name}'
            # 방향 전파
            if t_info['direction'] == '상승/강세':
                asset_sentiments[key]['bull'] += t_info['direction_scores']['bullish']
            elif t_info['direction'] == '하락/약세':
                asset_sentiments[key]['bear'] += t_info['direction_scores']['bearish']
            # 이유 추가 (토픽 방향 + 대표 주장)
            if t_info['key_claims']:
                reason = f"[{topic}] {t_info['direction']}: {t_info['key_claims'][0][:60]}"
                asset_sentiments[key]['reasons'].append(reason)

    asset_mapping = {}
    for key, info in sorted(asset_sentiments.items()):
        b, br = info['bull'], info['bear']
        if b > br * 1.3:
            sentiment = '긍정'
        elif br > b * 1.3:
            sentiment = '부정'
        else:
            sentiment = '중립'
        asset_mapping[key] = {
            'sentiment': sentiment,
            'reasons': info['reasons'][:5],
        }

    # ── 4. 크로스 테마 ──
    # 3개 이상 토픽에서 공통으로 등장하는 감성 키워드 → 크로스 테마 후보
    all_theme_kw: Counter = Counter()
    theme_phrases = [
        '스태그플레이션', '유로달러 르네상스', '달러 기근', '미국 예외주의',
        '침묵의 공황', '골디락스', '소프트 랜딩', '하드 랜딩', '경기 침체',
        '디커플링', '리쇼어링', '관세 전쟁', '무역 전쟁', '텀프리미엄',
        '엔 캐리', '안전자산 선호', '리스크온', '리스크오프', '유동성 위기',
        '인플레이션 재점화', '디플레이션', '금리 역전', '커브 정상화',
        '연준 피벗', '양적긴축', '양적완화',
    ]
    all_text = ' '.join(p.get('content', '') for p in month_posts).lower()
    cross_themes = [phrase for phrase in theme_phrases if phrase.lower() in all_text]

    # ── 5. 상위 포스팅 (토픽 점수 기준) ──
    scored_posts = []
    for p in month_posts:
        total_score = sum(p.get('_topics', {}).values())
        if total_score > 0:
            scored_posts.append({
                'title': p['title'],
                'date': p['date'],
                'relevance': f"topics={list(p['_topics'].keys())}, score={total_score}",
                'url': p.get('url', ''),
            })
    scored_posts.sort(key=lambda x: -len(x['relevance']))
    top_posts = scored_posts[:10]

    # ── 결과 조립 ──
    digest = {
        'month': ym,
        'post_count': len(month_posts),
        'topics': topics_result,
        'asset_mapping': asset_mapping,
        'cross_themes': cross_themes,
        'top_posts': top_posts,
    }

    return digest


def build_all_digests() -> list[dict]:
    """
    전체 기간(2024-01 ~ 2026-03) 월별 다이제스트 생성 후 개별 JSON 저장.

    Returns
    -------
    list[dict] : 월별 다이제스트 리스트
    """
    posts = json.load(open(POSTS_FILE, 'r', encoding='utf-8'))

    DIGEST_DIR.mkdir(parents=True, exist_ok=True)

    digests = []
    for year in range(2024, 2027):
        for month in range(1, 13):
            ym = f'{year:04d}-{month:02d}'
            if ym < '2024-01' or ym > '2026-03':
                continue

            digest = build_monthly_digest(year, month, posts)
            digests.append(digest)

            # 개별 파일 저장
            out_path = DIGEST_DIR / f'{ym}.json'
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(digest, f, ensure_ascii=False, indent=2)

            print(f'  {ym}: {digest["post_count"]} posts, '
                  f'{len(digest["topics"])} topics, '
                  f'{len(digest["cross_themes"])} cross-themes')

    print(f'\nTotal: {len(digests)} months saved to {DIGEST_DIR}')
    return digests


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════
if __name__ == '__main__':
    if len(sys.argv) == 3:
        y, m = int(sys.argv[1]), int(sys.argv[2])
        print(f'Building digest for {y:04d}-{m:02d}...')
        d = build_monthly_digest(y, m)
        DIGEST_DIR.mkdir(parents=True, exist_ok=True)
        out = DIGEST_DIR / f'{y:04d}-{m:02d}.json'
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        print(f'Saved: {out}')
        print(f'  posts={d["post_count"]}, topics={len(d["topics"])}, '
              f'cross_themes={d["cross_themes"]}')
        # 요약 출력
        for topic, info in d['topics'].items():
            print(f'  [{topic}] {info["direction"]} ({info["post_count"]} posts, '
                  f'{len(info["key_claims"])} claims, {len(info["data_points"])} data pts)')
    else:
        print('Building all monthly digests (2024-01 ~ 2026-03)...')
        build_all_digests()
