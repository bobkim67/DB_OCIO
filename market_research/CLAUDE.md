# CLAUDE.md — market_research

## Project Purpose

매크로 분석 블로그/뉴스 수집 → 추론 엔진 → 대시보드 → 월간 운용보고 매크로 현황 코멘트 작성.
DB_OCIO_Webview Tab 5(운용보고) 시장환경 코멘트의 메인 참조 데이터.
향후 Bloomberg 등 추가 매체 확장 예정.

## Architecture

```
market_research/
├── engine.py               ← 블로거 뷰 추론 엔진 (주제 태깅 + 패턴 DB + 진단 룰)
├── scrapers/
│   ├── __init__.py
│   ├── naver_blog.py       ← monygeek 블로그 크롤러 (Selenium)
│   └── macro_data.py       ← 매크로 지표 수집기 (SCIP + FRED + NY Fed)
├── data/
│   ├── monygeek/
│   │   ├── posts.json          ← 블로그 게시글 (510건, 2024-01~2026-03)
│   │   ├── log_nos.json        ← 게시글 logNo 캐시
│   │   └── analysis_worldview.json  ← 12개 변수별 블로거 경제관 분석
│   └── macro/
│       ├── indicators.json     ← 47개 지표 전체 (메타 정보 포함)
│       ├── indicators.csv      ← 47개 지표 wide format (597행 x 47열)
│       └── pattern_db.json     ← 주제별 지표 통계 패턴
├── __init__.py
└── CLAUDE.md
```

## Pipeline

```
[1] 데이터 수집
    ├─ naver_blog.py → posts.json (510건)
    └─ macro_data.py → indicators.csv (47개 지표)

[2] 추론 엔진 (engine.py)
    ├─ 포스팅-지표 매칭 (480건)
    ├─ 18개 주제 태깅
    ├─ 패턴 DB 생성
    └─ 진단 룰 평가 → 현재 매크로 진단

[3] 대시보드 (dashboard.py) — 미구현
    └─ Streamlit 매크로 대시보드

[4] 코멘트 생성 (comment_generator.py) — 미구현
    └─ 템플릿 기반 룰 엔진 → 운용보고 코멘트 초안
```

## Dependencies

```
selenium, webdriver-manager, pandas, numpy, pymysql
```

내부망 SSL 인증서 문제로 `WDM_SSL_VERIFY=0` 필수.

## Running

```bash
cd C:\Users\user\Downloads\python

# 블로그 크롤링 (incremental)
python -m market_research.scrapers.naver_blog

# 매크로 지표 수집 (SCIP + FRED + NY Fed)
python -c "from market_research.scrapers.macro_data import run; run()"

# 추론 엔진 (패턴 DB 빌드 + 현재 진단)
python -c "from market_research.engine import build, infer; build(); infer()"

# 진단만 실행
python -c "from market_research.engine import infer; infer()"
```

## Scraper: naver_blog.py

### 2단계 파이프라인

1. **step1_collect_urls()** — 모바일 블로그 무한 스크롤 → `log_nos.json` 캐시
2. **step2_scrape_posts()** — PC PostView 직접 접근 → `posts.json` (100건 배치 단위 드라이버 재시작)

### 기술 제약

- 네이버 모바일 스크롤 한계 ~504건 (전체 608건 중)
- ChromeDriver 타임아웃 → 배치(100건) 단위 드라이버 재시작
- 내부망 SSL → `WDM_SSL_VERIFY=0`
- Windows cp949 → `sys.stdout.reconfigure(encoding='utf-8')`

### 수집 항목 (posts.json)

log_no, url, title, date, date_raw, category, blog_category, title_tag, content, scraped_at

## Scraper: macro_data.py

### 47개 지표 — 3개 소스

**SCIP DB (20개)**:
- 달러: DXY(105), USDKRW(31), F_USDKRW(382)
- 금리: UST 1M~20Y (dataset 1~10, ds_id=7)
- 주가: SP500 TR(24), MSCI EAFE(63)/EM(37)/Japan(66)/Korea(144) (ds_id=6, blob_key='USD')
- 금: LBMA Gold PM (277, ds_id=15, blob_key='USD')
- Bloomberg: MOVE(405), LUATTRUU(399), EM Dollar(419), UST 7-10Y TR(420) — 모두 ds_id=48 (PX_LAST)

**FRED CSV (25개)** — API 키 불필요, CSV 다운로드:
- 유동성: SOFR, EFFR, RRP(RRPONTSYD), 지준(WRESBAL), TGA(WTREGEN)
- 고용: UNRATE, PAYEMS, JTSJOL, JTSQUR, ISM_PMI(MANEMP)
- 물가: CPIAUCSL, PCEPI, T5YIE, T10YIE
- 경기: GDPNOW
- 유가: WTI(DCOILWTICO), BRENT(DCOILBRENTEU)
- 변동성: VIX(VIXCLS), US_HY_OAS(BAMLH0A0HYM2), US_2Y10Y(T10Y2Y)
- 금리: DGS2, DGS10
- 환율: USDJPY(DEXJPUS), USDCNY(DEXCHUS), BROAD_DOLLAR(DTWEXBGS)

**NY Fed API (2개)**:
- REPO_FAILS_DEL: `PDFTD-USTET` (seriesbreak=SBN2024)
- REPO_FAILS_RCV: `PDFTR-USTET` (seriesbreak=SBN2024)
- URL: `https://markets.newyorkfed.org/api/pd/get/{sb}/timeseries/{keyid}.json`

### SCIP 신규 등록 dataset (Bloomberg 적재)

| dataset_id | name | symbol | dataseries_id |
|-----------|------|--------|--------------|
| 405 | ICE BofA MOVE Index | MOVE Index | 48 (PX_LAST) |
| 399 | Bloomberg US Treasury TR | LUATTRUU Index | 48 |
| 419 | JP Morgan EM Currency Index | FXJPEMCS Index | 48 |
| 420 | Bloomberg US Treasury 7-10Y TR | LT10TRUU Index | 48 |

## Engine: engine.py

### 주제 태깅 (18개 주제)

금리, 달러, 이민_노동, 물가, 관세, 안전자산, 미국채, 엔화_캐리, 중국_위안화, 유로달러, 유가_에너지, AI_반도체, 한국_원화, 유럽_ECB, 부동산, 저출산_인구, 비트코인_크립토, 금

각 주제별 키워드 2개 이상 매칭 시 태깅. 480/510건 매칭 성공.

### 진단 룰 (블로거 프레임워크 기반)

심각도 3단계: 🔴 critical, 🟡 warning, ⚪ neutral, 🟢 positive

주요 룰:
- EM 달러 인덱스 > 47 → 달러 기근 심화
- 레포 실패 > 80,000 → 달러 조달 스트레스
- 브렌트유 > 110 → 유가 위기 (critical)
- 원/달러 > 1,500 → 원화 위기 (critical)
- USD/CNY > 7.2 → 위안화 스트레스 (critical)
- VIX > 30 → 공포 구간
- MOVE > 120 → 채권 변동성 경고
- 유가+VIX+원화 복합 → 스태그플레이션

### 현재 진단 (2026-03-20 기준)

🔴 원화 위기 (1,500+), 스태그플레이션 복합 신호
🟡 레포 스트레스, 장기금리 급등, 유가 경고, 금 불확실성, VIX 경계, 엔 약세
⚪ RRP 고갈 근접, 수익률 곡선 정상화, MOVE 경계

## Blog Analysis: monygeek 경제관

### 핵심 학파: 유로달러 학파 (Jeff Snider 계열)

- 돈은 Fed가 아닌 민간 은행 대차대조표에서 창출
- 2008년 이후 유로달러 시스템 붕괴 → 17년간 만성적 달러 기근 → "침묵의 공황"
- Fed는 전능하지 않음 — QE는 지준만 늘렸을 뿐 유로달러 유동성 못 늘림

### 매크로 변수 관계 맵 (블로거 관점)

```
         ┌─ 엔화/엔캐리 ── 노린추킨 손실, 캐리 청산 70%+ 완료
         ├─ 중국/위안화 ── 좀비은행, 이자율 오류
         ├─ 한국 원화 ── ATM 구조 (경기ETF + 신흥국 분류 모순)
[유로달러 ├─ 금 ────────── 불확실성 프리미엄 (탈달러 아님)
 유동성]──├─ 유가 ───────── OPEC 자기파괴적 덫
 (중심)  ├─ 비트코인 ──── 달러 유동성 종속 위험자산
         ├─ 부동산 ────── 달러→집값 선행
         └─ 레포/역레포 ── 역레포 감소 ≠ 증시 유동성

[독립/반독립 변수]
├─ AI/반도체 ── J커브, K자 양극화, 한국은 "상인" 전략
├─ 저출산 ──── 침묵의 공황 + 문명적 가치관 전환
└─ 유럽 ────── 독일 부채 브레이크 폐기 = 유로달러 르네상스 기폭제
```

### 블로거의 분석 방법론

1. **내러티브 해체**: 매스컴 설명 → "정말 그런가?" → 배관(plumbing) 데이터로 대안 제시
2. **가격 우선**: "항상 가격이 먼저 움직이고 내러티브가 뒤를 따른다"
3. **미시구조 분석**: 일본 3개월 국채 0.1%p 움직임에서 글로벌 스트레스 포착
4. **니콜라스 케이지 방법론**: 상관관계 ≠ 인과관계, 공통 원인(달러 유동성) 추적

### 블로거 팩트체크 패턴

- 수치 과장 10~50% 반복 (디모나 부상자, 파이크턴 투자액 등)
- 에스컬레이션 편향 (전쟁/위기 글)
- 구조 분석은 우수 (사모대출, 코리아 디스카운트)
- 핵심 금융 데이터는 대부분 정확

## 운용보고 코멘트 엔진 (2026-03-27 구축)

### 파일 구조
```
market_research/
├─ comment_engine.py      ← 벤치마크/PA/digest → LLM 프롬프트 빌드 + Opus 코멘트 생성
├─ digest_builder.py      ← 블로그 월별 구조화 요약 (18개 주제 → 자산군 매핑)
├─ news_vectordb.py       ← chromadb + sentence-transformers 벡터 검색
├─ report_cli.py          ← CLI 팩터 선택 → 코멘트 생성
├─ collect_news.bat       ← 일일 수집 배치 (뉴스+블로그+digest+벡터)
├─ data/news/             ← Finnhub/NewsAPI/네이버 뉴스 (월별 JSON)
├─ data/news_vectordb/    ← chromadb 인덱스
├─ data/monygeek/monthly_digests/  ← 블로그 월별 digest (27개월)
└─ output/                ← 생성된 보고서 + 디버그 로그
```

### Streamlit 연동
`DB_OCIO_Webview/modules/comment_ui.py` → prototype.py tabs[5] (운용보고)

### 벤치마크 32개 — SCIP dataset/dataseries 매핑
comment_engine.py BENCHMARK_MAP 참조. Gold=408(ds=48), KOSPI Price=253(ds=15).

### 뉴스 소스
- Finnhub (해외, Yahoo 제외): `FINNHUB_KEY` in macro_data.py
- NewsAPI (trusted only): `NEWSAPI_KEY` in macro_data.py
- 네이버 금융 (국내): 크롤링, 과거 소급 불가

### LLM 모델
- Haiku: 팩터 요약/랭킹 (~$0.01)
- Opus: 최종 코멘트 생성 (~$0.22/펀드)

### 샘플 펀드 (5개)
08P22(포맷A, 5%), 08N81(포맷A, 8%), 08N33(포맷A, 6%), 07G04(포맷C, 모펀드), 2JM23(포맷D)

## TODO

- [ ] 21개 펀드 확장 (현재 샘플 5개)
- [ ] 미선택 자산군 프롬프트 처리
- [ ] CME FedWatch 데이터 추가
- [ ] 미수집 블로그 ~100건 보완
- [ ] 네이버 검색 API 키 → 과거 뉴스 소급

## Coding Conventions

- Python 3.14, Windows 환경
- 한국어 변수명/주석
- 분석 코드이므로 과도한 추상화 지양
