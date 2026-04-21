# 뉴스 데이터 매뉴얼

> 작성일: 2026-04-10
> 대상: `DB_OCIO_Webview/market_research/data/news/` 뉴스 데이터
> 용도: 다른 프로젝트(인물관계도 등)에서 뉴스 데이터 활용 시 참조

---

## 1. 저장 위치

```
C:\Users\user\Downloads\python\DB_OCIO_Webview\market_research\data\news\
├── 2025-01.json    (0.1MB,    200건)
├── 2025-02.json    (0.2MB,    360건)
├── ...
├── 2026-03.json    (45.3MB, 27,482건)
├── 2026-04.json    (31.4MB, 21,120건)
└── (월별 자동 생성)
```

총 **81,092건** (2025-01 ~ 2026-04), 합계 약 110MB.

---

## 2. JSON 구조

### 최상위

```json
{
  "month": "2026-04",
  "total": 21120,
  "articles": [ ... ]
}
```

### 기사 1건 필드

| 필드 | 타입 | 설명 | 예시 |
|------|------|------|------|
| **date** | str | 날짜 (YYYY-MM-DD) | "2026-04-10" |
| **datetime** | str | ISO 타임스탬프 | "2026-04-10T10:07:00+09:00" |
| **title** | str | 기사 제목 | "한은, 기준금리 7연속 동결" |
| **description** | str | 요약 (평균 126자) | 기사 앞부분 발췌 |
| **url** | str | 원문 URL | "https://www.nocutnews.co.kr/..." |
| **source** | str | 매체명 | "nocutnews.co.kr", "Reuters" |
| **provider** | str | 수집 API | "naver", "finnhub", "newsapi" |
| **asset_class** | str | 자산군 (수집 시 태깅) | "원자재", "국내주식", "general" |
| **symbol** | str | 종목 심볼 (Finnhub) | "SPY", "" |

### 파이프라인 부가 필드 (`_` prefix)

| 필드 | 타입 | 설명 | 예시 |
|------|------|------|------|
| _article_id | str | 고유 ID (MD5 12자, title+date+source) | "888e649a366d" |
| _is_macro_financial | bool | 매크로 금융 기사 여부 | true |
| _classified_topics | list[dict] | LLM 분류 결과 (14개 토픽) | [{"topic": "에너지_원자재", "direction": "positive", "intensity": 6}] |
| _asset_impact_vector | dict | 자산군별 영향도 (13키) | {"원자재_원유": 0.54} |
| primary_topic | str | 대표 토픽 | "에너지_원자재" |
| direction | str | 방향성 | "positive", "negative", "neutral" |
| intensity | int | 강도 (1~10) | 6 |
| _dedup_group_id | str | 중복 그룹 ID | "dedup_131" |
| is_primary | bool | 중복 그룹 내 대표 기사 | true |
| _event_group_id | str | 이벤트 클러스터 ID | "event_0" |
| _event_source_count | int | 교차보도 매체 수 | 6 |
| _event_salience | float | 중요도 점수 (0~1) | 0.49 |
| _asset_relevance | dict | 자산군별 관련도 | {"국내주식": 0.18, ...} |

---

## 3. 수집 소스

| 소스 | 비율 | 언어 | 특징 |
|------|------|------|------|
| **네이버 검색 API** | ~97% | 한국어 | 7개 카테고리 (국내주식/채권/해외주식/채권/원자재/통화/매크로) |
| **Finnhub** | ~2% | 영어 | SPY/QQQ/NVDA/TLT/HYG/GLD/USO/UUP + general (Reuters/CNBC) |
| **NewsAPI** | ~1% | 영어 | Reuters/Bloomberg/WSJ/FT/CNBC 등 신뢰 소스 |

---

## 4. Python으로 접근하는 방법

### 4.1 기본 로드

```python
import json
from pathlib import Path

NEWS_DIR = Path('C:/Users/user/Downloads/python/DB_OCIO_Webview/market_research/data/news')

# 특정 월 로드
def load_month(year_month: str) -> list[dict]:
    """year_month: '2026-04' 형식"""
    fpath = NEWS_DIR / f'{year_month}.json'
    data = json.loads(fpath.read_text(encoding='utf-8'))
    return data['articles']

articles = load_month('2026-04')
print(f'{len(articles)}건')
```

### 4.2 전체 월 로드

```python
def load_all() -> list[dict]:
    all_articles = []
    for f in sorted(NEWS_DIR.glob('*.json')):
        data = json.loads(f.read_text(encoding='utf-8'))
        all_articles.extend(data.get('articles', []))
    return all_articles

all_news = load_all()
print(f'전체: {len(all_news)}건')
```

### 4.3 pandas DataFrame 변환

```python
import pandas as pd

articles = load_month('2026-04')
df = pd.DataFrame(articles)

# 주요 컬럼만 추출
df_clean = df[['date', 'title', 'description', 'url', 'source', 'provider',
               'primary_topic', 'direction', 'intensity', '_event_salience']].copy()
df_clean = df_clean.rename(columns={'_event_salience': 'salience'})

print(df_clean.head())
```

### 4.4 날짜/토픽 필터

```python
# 특정 날짜
apr10 = [a for a in articles if a['date'] == '2026-04-10']

# 특정 토픽
energy = [a for a in articles if a.get('primary_topic') == '에너지_원자재']

# 중복 제거 (primary만)
primary = [a for a in articles if a.get('is_primary', False)]

# 중요도 상위
top = sorted(articles, key=lambda x: x.get('_event_salience', 0), reverse=True)[:20]
```

### 4.5 매체별 필터

```python
# 영문 매체만
english = [a for a in articles if a.get('provider') in ('finnhub', 'newsapi')]

# TIER1 매체만
TIER1 = {'Reuters', 'Bloomberg', 'AP', 'Financial Times', 'WSJ',
         'CNBC', 'MarketWatch', '연합뉴스', '연합뉴스TV', '뉴시스', '뉴스1'}
tier1 = [a for a in articles if a.get('source', '') in TIER1]
```

### 4.6 인물/키워드 검색

```python
# 제목+요약에서 인물 검색
def search_person(articles, name):
    return [a for a in articles
            if name in a.get('title', '') or name in a.get('description', '')]

bok = search_person(articles, '이창용')
print(f'이창용 관련: {len(bok)}건')
```

---

## 5. 14개 토픽 분류 체계

| 토픽 | 설명 |
|------|------|
| 지정학 | 전쟁, 외교, 군사 분쟁 |
| 환율_FX | 달러, 원화, 엔화 등 통화 |
| 에너지_원자재 | 유가, 가스, 원자재 |
| 금리_채권 | 국채, 금리, 채권시장 |
| 테크_AI_반도체 | 기술주, AI, 반도체 |
| 관세_무역 | 관세, 무역정책 |
| 크립토 | 비트코인, 암호화폐 |
| 물가_인플레이션 | CPI, PCE, 인플레이션 |
| 귀금속_금 | 금, 은 |
| 유동성_크레딧 | 크레딧 스프레드, 유동성 |
| 경기_소비 | GDP, 소비, 고용 |
| 통화정책 | 연준, 한은, ECB 정책 |
| 부동산 | 부동산 시장 |
| 재정_정부 | 재정정책, 정부 지출 |

---

## 6. 한계 및 주의사항

| 항목 | 현재 상태 |
|------|----------|
| **본문(content)** | **없음** — title + description(126자)만 저장 |
| **인물 엔티티(NER)** | 미수행 — title/description에서 직접 검색해야 함 |
| **이미지** | 없음 |
| **2025-01~03** | 네이버만 (Finnhub 미수집 기간) |
| **NewsAPI 무료 플랜** | 과거 30일만 조회 가능, 약관 제한 있음 |
| **파일 크기** | 2026-03이 45MB — 전체 로드 시 메모리 주의 |
| **인코딩** | UTF-8 (BOM 없음) |

---

## 7. 일일 배치로 자동 갱신

```bash
# daily_update.py 실행 시 자동 수집 (네이버+Finnhub+NewsAPI)
cd C:\Users\user\Downloads\python\DB_OCIO_Webview
C:\Users\user\Downloads\python\.venv\Scripts\python -m market_research.pipeline.daily_update

# 특정 날짜
C:\Users\user\Downloads\python\.venv\Scripts\python -m market_research.pipeline.daily_update 2026-04-10
```

매일 배치 실행 시 해당 월 JSON에 신규 기사가 append됩니다.
