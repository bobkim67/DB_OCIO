# -*- coding: utf-8 -*-
"""
매크로 지표 수집기 — SCIP DB + FRED CSV
블로거(monygeek) 핵심 지표 일일 수집 → JSON 저장
"""

import json
import ssl
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path
from io import StringIO

import pandas as pd
import pymysql

# ── 인코딩 설정 ──
ssl._create_default_https_context = ssl._create_unverified_context
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 경로 ──
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "macro"
OUTPUT_FILE = DATA_DIR / "indicators.json"
OUTPUT_CSV = DATA_DIR / "indicators.csv"

# ── DB 접속 ──
DB_CONFIG = dict(
    host='192.168.195.55', user='solution', password='Solution123!',
    charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
)


# ═══════════════════════════════════════════════════════
# SCIP DB 지표 정의
# ═══════════════════════════════════════════════════════
SCIP_INDICATORS = {
    # ── 달러/환율 ──
    'DXY':           {'dataset_id': 105, 'dataseries_id': 48, 'desc': '미국 달러 인덱스'},
    'USDKRW':        {'dataset_id': 31,  'dataseries_id': 6,  'desc': 'USD/KRW 환율', 'blob_key': 'USD'},
    'F_USDKRW':      {'dataset_id': 382, 'dataseries_id': None, 'desc': 'USD/KRW 선물환'},

    # ── 미국채 금리 ──
    'UST_1M':        {'dataset_id': 10,  'dataseries_id': 7,  'desc': 'Treasury 1M'},
    'UST_3M':        {'dataset_id': 9,   'dataseries_id': 7,  'desc': 'Treasury 3M'},
    'UST_1Y':        {'dataset_id': 7,   'dataseries_id': 7,  'desc': 'Treasury 1Y'},
    'UST_2Y':        {'dataset_id': 6,   'dataseries_id': 7,  'desc': 'Treasury 2Y'},
    'UST_5Y':        {'dataset_id': 4,   'dataseries_id': 7,  'desc': 'Treasury 5Y'},
    'UST_10Y':       {'dataset_id': 2,   'dataseries_id': 7,  'desc': 'Treasury 10Y'},
    'UST_20Y':       {'dataset_id': 1,   'dataseries_id': 7,  'desc': 'Treasury 20Y'},

    # ── 주가지수 ──
    'SP500_TR':      {'dataset_id': 24,  'dataseries_id': 6,  'desc': 'S&P 500 Total Return', 'blob_key': 'USD'},
    'MSCI_EAFE':     {'dataset_id': 63,  'dataseries_id': 6,  'desc': 'MSCI EAFE', 'blob_key': 'USD'},
    'MSCI_EM':       {'dataset_id': 37,  'dataseries_id': 6,  'desc': 'MSCI Emerging Markets', 'blob_key': 'USD'},
    'MSCI_JAPAN':    {'dataset_id': 66,  'dataseries_id': 6,  'desc': 'MSCI Japan', 'blob_key': 'USD'},
    'MSCI_KOREA':    {'dataset_id': 144, 'dataseries_id': 6,  'desc': 'MSCI Korea', 'blob_key': 'USD'},

    # ── 금 ──
    'GOLD':          {'dataset_id': 277, 'dataseries_id': 15, 'desc': 'LBMA Gold Price PM ($/oz)', 'blob_key': 'USD'},

    # ── Bloomberg (신규 적재) ──
    'MOVE':          {'dataset_id': 405, 'dataseries_id': 48, 'desc': 'ICE BofA MOVE Index'},
    'LUATTRUU':      {'dataset_id': 399, 'dataseries_id': 48, 'desc': 'Bloomberg US Treasury TR'},
    'EM_DOLLAR':     {'dataset_id': 419, 'dataseries_id': 48, 'desc': 'JP Morgan EM Currency Index'},
    'UST_7_10Y_TR':  {'dataset_id': 420, 'dataseries_id': 48, 'desc': 'Bloomberg US Treasury 7-10Y TR'},
}


# ═══════════════════════════════════════════════════════
# FRED CSV 지표 정의 (API 키 불필요)
# ═══════════════════════════════════════════════════════
FRED_INDICATORS = {
    # ── 레포/유동성 ──
    'SOFR':          {'series_id': 'SOFR',       'desc': 'Secured Overnight Financing Rate'},
    'EFFR':          {'series_id': 'EFFR',       'desc': 'Effective Federal Funds Rate'},
    'RRP':           {'series_id': 'RRPONTSYD',  'desc': 'Fed Overnight Reverse Repo (억$)'},
    'RESERVE_BAL':   {'series_id': 'WRESBAL',    'desc': 'Fed 지급준비금 잔액 (주간, 억$)'},
    'TGA':           {'series_id': 'WTREGEN',    'desc': 'Treasury General Account (주간, 억$)'},
    'WALCL':         {'series_id': 'WALCL',      'desc': 'Fed 총자산 (주간, 백만$)'},
    'M2SL':          {'series_id': 'M2SL',       'desc': 'M2 통화량 (월간, 십억$)'},
    # 레포 실패는 NY Fed API로 별도 수집 (FRED에 없음)

    # ── 고용 ──
    'UNRATE':        {'series_id': 'UNRATE',     'desc': '실업률 (월간, %)'},
    'PAYEMS':        {'series_id': 'PAYEMS',     'desc': '비농업 고용자 수 (월간, 천명)'},
    'JTSJOL':        {'series_id': 'JTSJOL',     'desc': 'JOLTS 채용공고 (월간, 천건)'},
    'JTSQUR':        {'series_id': 'JTSQUR',     'desc': 'JOLTS 퇴사율 (월간, %)'},
    'ICSA':          {'series_id': 'ICSA',       'desc': '신규 실업수당 청구 (주간, 건)'},

    # ── 물가 ──
    'CPIAUCSL':      {'series_id': 'CPIAUCSL',   'desc': 'CPI 도시소비자 (월간, 지수)'},
    'CPILFESL':      {'series_id': 'CPILFESL',   'desc': 'Core CPI (식품·에너지 제외, 월간, 지수)'},
    'PCEPI':         {'series_id': 'PCEPI',      'desc': 'PCE 물가지수 (월간, 지수)'},
    'PCEPILFE':      {'series_id': 'PCEPILFE',   'desc': 'Core PCE (식품·에너지 제외, 월간, 지수)'},
    'T5YIE':         {'series_id': 'T5YIE',      'desc': '5Y 브레이크이븐 인플레이션 (일간, %)'},
    'T10YIE':        {'series_id': 'T10YIE',     'desc': '10Y 브레이크이븐 인플레이션 (일간, %)'},

    # ── 경기 ──
    'GDPNOW':        {'series_id': 'GDPNOW',    'desc': 'Atlanta Fed GDPNow (비정기)'},
    'MFG_EMPLOYMENT': {'series_id': 'MANEMP',    'desc': '제조업 고용자 수 (월간, 천명)'},
    # ISM PMI (NAPM, NMFBAI): FRED CSV 미제공 (ISM 저작권) → 제외
    'RSAFS':         {'series_id': 'RSAFS',      'desc': '소매판매 (월간, 백만$)'},
    'UMCSENT':       {'series_id': 'UMCSENT',    'desc': '미시간 소비자심리지수 (월간)'},
    'INDPRO':        {'series_id': 'INDPRO',     'desc': '산업생산지수 (월간, 지수)'},

    # ── 유가 ──
    'WTI':           {'series_id': 'DCOILWTICO', 'desc': 'WTI 원유 (일간, $/배럴)'},
    'BRENT':         {'series_id': 'DCOILBRENTEU', 'desc': '브렌트유 (일간, $/배럴)'},

    # ── 변동성/크레딧/커브 (SCIP 비가용 → FRED) ──
    'VIX':           {'series_id': 'VIXCLS',     'desc': 'CBOE VIX (일간)'},
    # MOVE는 SCIP에서 수집 (dataset 405)
    'US_HY_OAS':     {'series_id': 'BAMLH0A0HYM2', 'desc': 'US HY OAS (일간, bp)'},
    'US_IG_OAS':     {'series_id': 'BAMLC0A0CM',  'desc': 'US IG OAS (일간, bp)'},
    'US_2Y10Y':      {'series_id': 'T10Y2Y',    'desc': '10Y-2Y 스프레드 (일간, %)'},

    # ── 기타 ──
    'MORTGAGE30US':  {'series_id': 'MORTGAGE30US','desc': '30Y 모기지 금리 (주간, %)'},

    # ── 기타 ──
    'DGS2':          {'series_id': 'DGS2',       'desc': '미국채 2년 금리 (FRED, 일간)'},
    'DGS10':         {'series_id': 'DGS10',      'desc': '미국채 10년 금리 (FRED, 일간)'},
    'USDJPY':        {'series_id': 'DEXJPUS',    'desc': 'USD/JPY (일간)'},
    'USDCNY':        {'series_id': 'DEXCHUS',    'desc': 'USD/CNY (일간)'},
    'BROAD_DOLLAR':  {'series_id': 'DTWEXBGS',   'desc': 'Broad Dollar Index (일간)'},

    # ── 주요국 기준금리 ──
    'FED_UPPER':     {'series_id': 'DFEDTARU',   'desc': 'Fed Funds Target Upper (일간, %)'},
    'FED_LOWER':     {'series_id': 'DFEDTARL',   'desc': 'Fed Funds Target Lower (일간, %)'},
    'ECB_RATE':      {'series_id': 'ECBDFR',     'desc': 'ECB Deposit Facility Rate (일간, %)'},
    'BOJ_RATE':      {'series_id': 'IRSTCI01JPM156N', 'desc': 'BOJ Policy Rate (월간, %)'},
}


# ═══════════════════════════════════════════════════════
# ECOS (한국은행) 수집 — BOK 기준금리
# ═══════════════════════════════════════════════════════

ECOS_API_KEY = 'FWC2IZWA5YD459SQ7RJM'

ECOS_INDICATORS = {
    'BOK_RATE': {
        'stat_code': '722Y001', 'item_code': '0101000', 'cycle': 'M',
        'desc': 'BOK 기준금리 (월간, %)',
    },
}


def load_ecos_indicators(start_date='2024-01-01'):
    """ECOS에서 BOK 기준금리 수집"""
    print("\n── ECOS (한국은행) 수집 ──")
    results = {}
    start_ym = start_date[:4] + start_date[5:7]  # '202401'
    end_ym = date.today().strftime('%Y%m')

    for name, cfg in ECOS_INDICATORS.items():
        url = (
            f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}/json/kr/1/100/"
            f"{cfg['stat_code']}/{cfg['cycle']}/{start_ym}/{end_ym}/{cfg['item_code']}"
        )
        try:
            req = urllib.request.urlopen(url, timeout=30)
            data = json.loads(req.read().decode())
            rows = data.get('StatisticSearch', {}).get('row', [])
            series = {}
            for r in rows:
                ym = r.get('TIME', '')
                val = r.get('DATA_VALUE', '')
                if ym and val:
                    # YYYYMM → YYYY-MM-01 (월초)
                    dt_str = f"{ym[:4]}-{ym[4:6]}-01"
                    try:
                        series[dt_str] = float(val)
                    except ValueError:
                        pass
            results[name] = series
            print(f"  {name}: {len(series)}건 ({cfg['desc']})")
        except Exception as e:
            results[name] = {}
            print(f"  {name}: 실패 — {e}")

    return results


# ═══════════════════════════════════════════════════════
# SCIP 데이터 수집
# ═══════════════════════════════════════════════════════

def _parse_blob(blob, blob_key=None):
    """SCIP data blob 파싱"""
    if blob is None:
        return None
    if isinstance(blob, (bytes, bytearray)):
        s = blob.decode('utf-8')
    else:
        s = str(blob)
    s = s.strip()
    if s.startswith('{'):
        obj = json.loads(s)
        if blob_key and blob_key in obj:
            return float(obj[blob_key])
        return obj
    try:
        return float(s.replace(',', '').replace('"', ''))
    except ValueError:
        return None


def load_scip_indicators(start_date='2024-01-01'):
    """SCIP DB에서 매크로 지표 수집"""
    print("── SCIP DB 수집 ──")
    conn = pymysql.connect(db='SCIP', **DB_CONFIG)
    results = {}

    try:
        with conn.cursor() as cur:
            for name, cfg in SCIP_INDICATORS.items():
                ds_id = cfg['dataset_id']
                dseries = cfg.get('dataseries_id')
                blob_key = cfg.get('blob_key')

                sql = """
                    SELECT DATE(timestamp_observation) AS dt, data
                    FROM back_datapoint
                    WHERE dataset_id = %s
                      AND timestamp_observation >= %s
                """
                params = [ds_id, start_date]

                if dseries is not None:
                    sql += " AND dataseries_id = %s"
                    params.append(dseries)

                sql += " ORDER BY timestamp_observation"
                cur.execute(sql, params)
                rows = cur.fetchall()

                series = {}
                for r in rows:
                    dt_str = str(r['dt'])
                    val = _parse_blob(r['data'], blob_key)
                    if val is not None and not isinstance(val, dict):
                        series[dt_str] = float(val)

                results[name] = series
                print(f"  {name}: {len(series)}건 ({cfg['desc']})")
    finally:
        conn.close()

    return results


# ═══════════════════════════════════════════════════════
# NY Fed Primary Dealer Statistics 수집 (레포 실패)
# ═══════════════════════════════════════════════════════

NYFED_INDICATORS = {
    'REPO_FAILS_DEL': {
        'seriesbreak': 'SBN2024', 'keyid': 'PDFTD-USTET',
        'desc': 'Treasury 레포 실패-인도 (주간, 백만$)',
    },
    'REPO_FAILS_RCV': {
        'seriesbreak': 'SBN2024', 'keyid': 'PDFTR-USTET',
        'desc': 'Treasury 레포 실패-수취 (주간, 백만$)',
    },
}


def load_nyfed_indicators(start_date='2024-01-01'):
    """NY Fed에서 레포 실패 데이터 수집"""
    print("\n── NY Fed API 수집 ──")
    results = {}

    for name, cfg in NYFED_INDICATORS.items():
        url = (
            f"https://markets.newyorkfed.org/api/pd/get/"
            f"{cfg['seriesbreak']}/timeseries/{cfg['keyid']}.json"
        )
        try:
            req = urllib.request.urlopen(url, timeout=30)
            data = json.loads(req.read().decode())
            obs = data.get('pd', {}).get('timeseries', [])
            series = {}
            for o in obs:
                dt_str = o.get('asofdate', '')
                val = o.get('value', '')
                if dt_str >= start_date and val:
                    try:
                        series[dt_str] = float(val)
                    except ValueError:
                        pass
            results[name] = series
            print(f"  {name}: {len(series)}건 ({cfg['desc']})")
        except Exception as e:
            results[name] = {}
            print(f"  {name}: 실패 — {e}")

    return results


# ═══════════════════════════════════════════════════════
# FRED CSV 수집
# ═══════════════════════════════════════════════════════

def _fetch_fred_csv(series_id, start_date='2024-01-01', end_date=None):
    """FRED CSV 다운로드 (API 키 불필요)"""
    if end_date is None:
        end_date = date.today().isoformat()
    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={series_id}&cosd={start_date}&coed={end_date}"
    )
    try:
        req = urllib.request.urlopen(url, timeout=30)
        csv_text = req.read().decode('utf-8')
        df = pd.read_csv(StringIO(csv_text))
        df.columns = ['date', 'value']
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df = df.dropna()
        return dict(zip(df['date'].astype(str), df['value'].astype(float)))
    except Exception as e:
        return {}


def load_fred_indicators(start_date='2024-01-01'):
    """FRED에서 매크로 지표 수집"""
    print("\n── FRED CSV 수집 ──")
    results = {}

    for name, cfg in FRED_INDICATORS.items():
        series = _fetch_fred_csv(cfg['series_id'], start_date)
        results[name] = series
        status = f"{len(series)}건" if series else "실패"
        print(f"  {name} ({cfg['series_id']}): {status} — {cfg['desc']}")

    return results


# ═══════════════════════════════════════════════════════
# 네이버 검색 API 뉴스
# ═══════════════════════════════════════════════════════

NAVER_CLIENT_ID = '1x0YjgIVXVz68s3Eq6Nz'
NAVER_CLIENT_SECRET = '7H2crvgQgh'

NAVER_NEWS_QUERIES = {
    '국내주식': ['KOSPI 증시', '코스피 외국인', '반도체 삼성전자', 'SK하이닉스 AI'],
    '국내채권': ['국고채 금리', '금통위 한국은행', '채권시장 수익률'],
    '해외주식': ['S&P500 나스닥', '미국 증시 Fed', 'AI 빅테크'],
    '해외채권': ['미국 국채 금리', '하이일드 크레딧'],
    '원자재':   ['금값 금시세', '유가 WTI 브렌트', '원자재 GSCI'],
    '통화':     ['원달러 환율', 'USD 달러 강세'],
    '매크로':   ['CPI 물가', '고용 실업률', 'FOMC 금리'],
}


def load_naver_finance_news():
    """네이버 검색 API로 금융 뉴스 수집 (제목 + 요약 description)"""
    import re, html as html_mod
    NEWS_DIR_ = Path(__file__).resolve().parent.parent / "data" / "news"
    NEWS_DIR_.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    print(f"\n── 네이버 검색 API 뉴스 ({today}) ──")

    headers = {
        'X-Naver-Client-Id': NAVER_CLIENT_ID,
        'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
    }

    all_articles = []
    seen_titles = set()

    def _clean(text):
        """HTML 태그 + 엔티티 정리"""
        text = re.sub(r'<[^>]+>', '', text)
        text = html_mod.unescape(text)
        return text.strip()

    def _parse_pubdate(pd_str):
        """'Wed, 08 Apr 2026 09:00:00 +0900' → '2026-04-08'"""
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pd_str)
            return dt.strftime('%Y-%m-%d'), dt.isoformat()
        except Exception:
            return today, f'{today}T00:00:00'

    for ac, keywords in NAVER_NEWS_QUERIES.items():
        for kw in keywords:
            try:
                encoded_kw = urllib.parse.quote(kw)
                url = f'https://openapi.naver.com/v1/search/news.json?query={encoded_kw}&display=20&sort=date'
                resp = urllib.request.Request(url, headers={**headers, 'User-Agent': 'Mozilla/5.0'})
                result = urllib.request.urlopen(resp, timeout=10)
                data = json.loads(result.read().decode('utf-8'))

                count = 0
                for item in data.get('items', []):
                    title = _clean(item.get('title', ''))
                    if not title or title in seen_titles or len(title) < 10:
                        continue
                    seen_titles.add(title)

                    description = _clean(item.get('description', ''))
                    art_date, art_datetime = _parse_pubdate(item.get('pubDate', ''))

                    all_articles.append({
                        'date': art_date,
                        'datetime': art_datetime,
                        'source': '네이버검색',
                        'asset_class': ac,
                        'symbol': '',
                        'title': title,
                        'description': description,
                        'url': item.get('originallink', item.get('link', '')),
                        'provider': 'naver',
                    })
                    count += 1
                    if count >= 10:
                        break
            except Exception as e:
                print(f"  {ac}/{kw}: 실패 — {e}")

        print(f"  {ac}: {sum(1 for a in all_articles if a['asset_class']==ac)}건")

    print(f"  합계: {len(all_articles)}건")

    # 월별 파일에 병합
    month = today[:7]
    mfile = NEWS_DIR_ / f'{month}.json'
    existing = []
    if mfile.exists():
        try:
            existing = json.loads(mfile.read_text(encoding='utf-8')).get('articles', [])
        except Exception:
            pass
    existing_titles = set(a['title'] for a in existing)
    new_articles = [a for a in all_articles if a['title'] not in existing_titles]
    merged = existing + new_articles
    merged.sort(key=lambda x: x.get('datetime', ''), reverse=True)
    with open(mfile, 'w', encoding='utf-8') as f:
        json.dump({'month': month, 'total': len(merged), 'articles': merged},
                  f, ensure_ascii=False, indent=2)
    print(f"  [저장] {mfile} — 신규 {len(new_articles)}건, 총 {len(merged)}건")

    return all_articles


# ═══════════════════════════════════════════════════════
# Finnhub 뉴스 수집
# ═══════════════════════════════════════════════════════

FINNHUB_KEY = 'd72tmv1r01qlfd9ohbggd72tmv1r01qlfd9ohbh0'
NEWS_DIR = Path(__file__).resolve().parent.parent / "data" / "news"

# 자산군별 ETF 심볼
FINNHUB_SYMBOLS = {
    '미국주식':  ['SPY', 'QQQ', 'NVDA'],
    '국내주식':  ['EWY'],
    '미국채권':  ['TLT', 'HYG'],
    '원자재':    ['GLD', 'USO'],
    '통화':      ['UUP'],
}

# Yahoo 제외 (노이즈 74%)
FINNHUB_EXCLUDE_SOURCES = {'Yahoo'}


def load_finnhub_news(from_date=None, to_date=None):
    """Finnhub company-news 수집 (Yahoo 제외, 자산군 태깅)"""
    import time as _time
    NEWS_DIR.mkdir(parents=True, exist_ok=True)

    if not from_date:
        from_date = date.today().isoformat()
    if not to_date:
        to_date = date.today().isoformat()

    print(f"\n── Finnhub 뉴스 수집 ({from_date} ~ {to_date}) ──")

    all_articles = []
    seen_headlines = set()

    for asset_class, symbols in FINNHUB_SYMBOLS.items():
        for sym in symbols:
            try:
                url = (f'https://finnhub.io/api/v1/company-news?'
                       f'symbol={sym}&from={from_date}&to={to_date}&token={FINNHUB_KEY}')
                req = urllib.request.urlopen(url, timeout=15)
                data = json.loads(req.read().decode())

                count = 0
                for a in data:
                    src = a.get('source', '')
                    headline = a.get('headline', '')
                    if src in FINNHUB_EXCLUDE_SOURCES:
                        continue
                    if not headline or headline in seen_headlines:
                        continue
                    seen_headlines.add(headline)
                    ts = a.get('datetime', 0)
                    dt_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts else ''
                    all_articles.append({
                        'date': dt_str,
                        'datetime': datetime.fromtimestamp(ts).isoformat() if ts else '',
                        'source': src,
                        'asset_class': asset_class,
                        'symbol': sym,
                        'title': headline,
                        'description': (a.get('summary') or '')[:500],
                        'url': a.get('url', ''),
                        'provider': 'finnhub',
                    })
                    count += 1

                print(f"  {sym} ({asset_class}): {count}건")
                _time.sleep(0.3)
            except Exception as e:
                print(f"  {sym}: 실패 — {e}")

    # general news (Reuters/CNBC)
    try:
        url = f'https://finnhub.io/api/v1/news?category=general&token={FINNHUB_KEY}'
        req = urllib.request.urlopen(url, timeout=15)
        data = json.loads(req.read().decode())
        count = 0
        for a in data:
            headline = a.get('headline', '')
            if not headline or headline in seen_headlines:
                continue
            seen_headlines.add(headline)
            ts = a.get('datetime', 0)
            dt_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts else ''
            # from~to 범위 필터
            if dt_str < from_date or dt_str > to_date:
                continue
            all_articles.append({
                'date': dt_str,
                'datetime': datetime.fromtimestamp(ts).isoformat() if ts else '',
                'source': a.get('source', ''),
                'asset_class': 'general',
                'symbol': '',
                'title': headline,
                'description': (a.get('summary') or '')[:500],
                'url': a.get('url', ''),
                'provider': 'finnhub',
            })
            count += 1
        print(f"  general (Reuters/CNBC): {count}건")
    except Exception as e:
        print(f"  general: 실패 — {e}")

    all_articles.sort(key=lambda x: x.get('datetime', ''), reverse=True)
    print(f"  총 {len(all_articles)}건 (Yahoo 제외)")

    # 월별 파일에 병합 저장
    monthly = {}
    for a in all_articles:
        m = a['date'][:7] if a.get('date') else None
        if m:
            monthly.setdefault(m, []).append(a)

    for m, articles in sorted(monthly.items()):
        mfile = NEWS_DIR / f'{m}.json'
        existing = []
        if mfile.exists():
            try:
                existing = json.loads(mfile.read_text(encoding='utf-8')).get('articles', [])
            except Exception:
                pass
        existing_titles = set(a['title'] for a in existing)
        new_articles = [a for a in articles if a['title'] not in existing_titles]
        merged = existing + new_articles
        merged.sort(key=lambda x: x.get('datetime', ''), reverse=True)
        with open(mfile, 'w', encoding='utf-8') as f:
            json.dump({'month': m, 'total': len(merged), 'articles': merged},
                      f, ensure_ascii=False, indent=2)
        print(f"    {m}: {len(merged)}건 (신규 {len(new_articles)}건)")

    return all_articles


def load_news_all():
    """매일 수집: Finnhub + NewsAPI trusted + 네이버"""
    today = date.today().isoformat()
    print(f"\n{'='*50}")
    print(f"  뉴스 수집 ({today})")
    print(f"{'='*50}")

    # Finnhub (해외 메인)
    fh = load_finnhub_news(from_date=today, to_date=today)

    # NewsAPI trusted (Reuters/Bloomberg 보충)
    na = load_news_daily()

    # 네이버 (국내 시장)
    nv = load_naver_finance_news()

    print(f"\n  합산: Finnhub {len(fh)}건 + NewsAPI {len(na)}건 + 네이버 {len(nv)}건")
    return fh, na, nv


# ═══════════════════════════════════════════════════════
# NewsAPI 뉴스 수집
# ═══════════════════════════════════════════════════════

NEWSAPI_KEY = 'eee66221bc984a679ab63068f6164eeb'

# 자산군별 검색 키워드
NEWS_QUERIES = {
    '글로벌주식': '"stock market" OR "equity market" OR "MSCI" OR "S&P 500"',
    '미국주식': '"Wall Street" OR "Nasdaq" OR "tech stocks" OR "growth stocks" OR "AI stocks"',
    '신흥국': '"emerging markets" OR "MSCI EM" OR "China economy" OR "yuan"',
    '채권': '"bond market" OR "Treasury" OR "yield" OR "interest rate" OR "FOMC" OR "Fed rate"',
    '원자재': '"gold price" OR "oil price" OR "WTI" OR "commodity" OR "OPEC"',
    '통화': '"dollar index" OR "DXY" OR "USD" OR "forex" OR "yen" OR "won"',
    '지정학': '"geopolitical" OR "Iran" OR "tariff" OR "trade war" OR "sanctions"',
    '경기': '"GDP" OR "recession" OR "inflation" OR "CPI" OR "employment" OR "PMI"',
}

# 신뢰할 만한 소스 (NewsAPI domains)
TRUSTED_SOURCES = [
    'reuters.com', 'bloomberg.com', 'wsj.com', 'ft.com', 'cnbc.com',
    'bbc.co.uk', 'economist.com', 'marketwatch.com', 'barrons.com',
    'forbes.com', 'axios.com',
]


def load_news_daily():
    """오늘자 뉴스 수집 (매일 실행용) — top-headlines + everything 조합"""
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    all_articles = []
    seen_titles = set()

    def _add_article(a, category):
        title = a.get('title', '')
        if not title or title in seen_titles or '[Removed]' in title:
            return
        src_url = a.get('url', '')
        is_trusted = any(d in src_url for d in TRUSTED_SOURCES)
        seen_titles.add(title)
        all_articles.append({
            'date': a.get('publishedAt', '')[:10],
            'datetime': a.get('publishedAt', ''),
            'source': a.get('source', {}).get('name', ''),
            'category': category,
            'title': title,
            'description': (a.get('description') or '')[:300],
            'url': a.get('url', ''),
            'trusted': is_trusted,
        })

    print(f"\n── NewsAPI 수집 ({today}) ──")

    # 1) top-headlines (Reuters, Bloomberg 등 신뢰 소스 포함)
    for cat in ['business', 'technology']:
        try:
            params = urllib.parse.urlencode({
                'category': cat,
                'language': 'en',
                'pageSize': 100,
                'apiKey': NEWSAPI_KEY,
            })
            url = f'https://newsapi.org/v2/top-headlines?{params}'
            req = urllib.request.urlopen(url, timeout=15)
            data = json.loads(req.read().decode())
            for a in data.get('articles', []):
                _add_article(a, f'headline_{cat}')
            print(f"  top-headlines/{cat}: {len(data.get('articles',[]))}건")
        except Exception as e:
            print(f"  top-headlines/{cat}: 실패 — {e}")

    # 2) everything (키워드별)
    for category, query in NEWS_QUERIES.items():
        try:
            params = urllib.parse.urlencode({
                'q': query,
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': 20,
                'apiKey': NEWSAPI_KEY,
            })
            url = f'https://newsapi.org/v2/everything?{params}'
            req = urllib.request.urlopen(url, timeout=15)
            data = json.loads(req.read().decode())
            before = len(all_articles)
            for a in data.get('articles', []):
                _add_article(a, category)
            print(f"  {category}: {len(all_articles) - before}건")
        except Exception as e:
            print(f"  {category}: 실패 — {e}")

    # 저장 — 월별 파일에 병합
    month = today[:7]
    mfile = NEWS_DIR / f'{month}.json'
    existing = []
    if mfile.exists():
        try:
            existing = json.loads(mfile.read_text(encoding='utf-8')).get('articles', [])
        except Exception:
            pass
    existing_titles = set(a['title'] for a in existing)
    new_articles = [a for a in all_articles if a['title'] not in existing_titles]
    merged = existing + new_articles
    merged.sort(key=lambda x: x.get('datetime', ''), reverse=True)

    with open(mfile, 'w', encoding='utf-8') as f:
        json.dump({'month': month, 'total': len(merged), 'articles': merged},
                  f, ensure_ascii=False, indent=2)

    trusted = sum(1 for a in all_articles if a['trusted'])
    print(f"  [저장] {mfile} — 신규 {len(new_articles)}건 (신뢰 {trusted}건), 총 {len(merged)}건")

    return all_articles


def load_news_backfill(pages=5):
    """최근 뉴스 일괄 수집 (무료 tier: from/to 불가 → 페이지네이션으로 최대한 수집)"""
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    outfile = NEWS_DIR / f'backfill_{today.isoformat()}.json'

    print(f"\n── NewsAPI 백필 (카테고리별 {pages}페이지) ──")

    all_articles = []
    seen_titles = set()

    for category, query in NEWS_QUERIES.items():
        cat_count = 0
        for page in range(1, pages + 1):
            try:
                params = urllib.parse.urlencode({
                    'q': query,
                    'language': 'en',
                    'sortBy': 'relevancy',  # relevancy로 해야 ~1달치 커버
                    'pageSize': 100,
                    'page': page,
                    'apiKey': NEWSAPI_KEY,
                })
                url = f'https://newsapi.org/v2/everything?{params}'
                req = urllib.request.urlopen(url, timeout=15)
                data = json.loads(req.read().decode())

                articles = data.get('articles', [])
                if not articles:
                    break

                for a in articles:
                    title = a.get('title', '')
                    if not title or title in seen_titles or '[Removed]' in title:
                        continue
                    src_url = a.get('url', '')
                    is_trusted = any(d in src_url for d in TRUSTED_SOURCES)

                    seen_titles.add(title)
                    all_articles.append({
                        'date': a.get('publishedAt', '')[:10],
                        'datetime': a.get('publishedAt', ''),
                        'source': a.get('source', {}).get('name', ''),
                        'category': category,
                        'title': title,
                        'description': (a.get('description') or '')[:300],
                        'url': a.get('url', ''),
                        'trusted': is_trusted,
                    })
                    cat_count += 1

            except urllib.error.HTTPError as e:
                if e.code == 426:
                    print(f"  {category} p{page}: 무료 tier 제한 (426)")
                    break
                elif e.code == 429:
                    print(f"  {category} p{page}: rate limit — 중단")
                    break
                else:
                    print(f"  {category} p{page}: HTTP {e.code}")
                    break
            except Exception as e:
                print(f"  {category} p{page}: 실패 — {e}")
                break

        print(f"  {category}: {cat_count}건")

    # 날짜순 정렬
    all_articles.sort(key=lambda x: x.get('datetime', ''), reverse=True)

    # 기간 확인
    dates = [a['date'] for a in all_articles if a.get('date')]
    period = f'{min(dates)} ~ {max(dates)}' if dates else 'N/A'

    result = {
        'collected_at': datetime.now().isoformat(),
        'period': period,
        'total': len(all_articles),
        'articles': all_articles,
    }
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  [저장] {outfile} ({len(all_articles)}건, {period})")

    # 월별 분리 저장
    monthly = {}
    for a in all_articles:
        m = a['date'][:7] if a.get('date') else None
        if m:
            monthly.setdefault(m, []).append(a)
    for m, articles in sorted(monthly.items()):
        mfile = NEWS_DIR / f'{m}.json'
        existing = []
        if mfile.exists():
            try:
                existing = json.loads(mfile.read_text(encoding='utf-8')).get('articles', [])
            except Exception:
                pass
        existing_titles = set(a['title'] for a in existing)
        new_articles = [a for a in articles if a['title'] not in existing_titles]
        merged = existing + new_articles
        merged.sort(key=lambda x: x.get('datetime', ''), reverse=True)
        with open(mfile, 'w', encoding='utf-8') as f:
            json.dump({'month': m, 'total': len(merged), 'articles': merged},
                      f, ensure_ascii=False, indent=2)
        print(f"    {m}: {len(merged)}건 (신규 {len(new_articles)}건)")

    return all_articles


# ═══════════════════════════════════════════════════════
# 통합 저장
# ═══════════════════════════════════════════════════════

def save_results(scip_data, fred_data, nyfed_data=None, ecos_data=None):
    """JSON + CSV 저장"""
    if nyfed_data is None:
        nyfed_data = {}
    if ecos_data is None:
        ecos_data = {}
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 메타 정보 포함 JSON
    combined = {
        'updated_at': datetime.now().isoformat(),
        'scip': {},
        'fred': {},
        'nyfed': {},
        'ecos': {},
    }
    for name, series in scip_data.items():
        combined['scip'][name] = {
            'desc': SCIP_INDICATORS[name]['desc'],
            'count': len(series),
            'data': series,
        }
    for name, series in fred_data.items():
        combined['fred'][name] = {
            'desc': FRED_INDICATORS[name]['desc'],
            'count': len(series),
            'data': series,
        }
    for name, series in nyfed_data.items():
        combined['nyfed'][name] = {
            'desc': NYFED_INDICATORS[name]['desc'],
            'count': len(series),
            'data': series,
        }
    for name, series in ecos_data.items():
        combined['ecos'][name] = {
            'desc': ECOS_INDICATORS[name]['desc'],
            'count': len(series),
            'data': series,
        }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
    print(f"\n[JSON 저장] {OUTPUT_FILE}")

    # 통합 CSV (wide format — 날짜 x 지표)
    all_series = {}
    for name, series in {**scip_data, **fred_data, **nyfed_data, **ecos_data}.items():
        all_series[name] = pd.Series(series, dtype=float)

    df = pd.DataFrame(all_series)
    df.index.name = 'date'
    df = df.sort_index()
    df.to_csv(OUTPUT_CSV, encoding='utf-8-sig')
    print(f"[CSV 저장] {OUTPUT_CSV} ({len(df)}행 x {len(df.columns)}열)")

    return df


# ═══════════════════════════════════════════════════════
# 실행
# ═══════════════════════════════════════════════════════

def run(start_date='2024-01-01'):
    """전체 수집 파이프라인"""
    print(f"[매크로 지표 수집] 시작일: {start_date}\n")

    scip_data = load_scip_indicators(start_date)
    fred_data = load_fred_indicators(start_date)
    nyfed_data = load_nyfed_indicators(start_date)
    ecos_data = load_ecos_indicators(start_date)

    df = save_results(scip_data, fred_data, nyfed_data, ecos_data)

    # 요약
    total = len(scip_data) + len(fred_data) + len(nyfed_data) + len(ecos_data)
    ok = sum(1 for s in {**scip_data, **fred_data, **nyfed_data, **ecos_data}.values() if s)
    print(f"\n[완료] {ok}/{total}개 지표 수집 성공")

    return df


if __name__ == '__main__':
    run()
