# === DB OCIO 운용 펀드 목록 ===
# 현재 운용중인 사모 OCIO 펀드 코드 (dt.DWPM10510 기준)
# 최근 기준일: 2026-02-11, 총 AUM: ~1.4조원

FUND_LIST = [
    '06X08', '07G02', '07G03', '07G04', '07J20', '07J27', '07J34', '07J41',
    '07J48', '07J49', '07P70', '07W15', '08K88', '08N33', '08N81', '08P22',
    '09L94', '1JM96', '1JM98', '2JM23', '4JM12'
]

# 펀드 메타정보 (DB 조회 결과 기반, 2026-02-11)
FUND_META = {
    '06X08': {'name': '한국투자퇴직연금OCIO알아서RSP일반사모증권투자신탁(혼합-재간접형)', 'inception': '20220214', 'aum_억': 40.6},
    '07G02': {'name': '한국투자인컴추구증권모투자신탁(채권혼합-재간접형)', 'inception': '20210927', 'aum_억': 883.4},
    '07G03': {'name': '한국투자수익추구증권모투자신탁(혼합-재간접형)', 'inception': '20210927', 'aum_억': 888.2},
    '07G04': {'name': '한국투자OCIO알아서증권자투자신탁(채권혼합-재간접형)(모)', 'inception': '20210927', 'aum_억': 1749.6},
    '07J20': {'name': '한국투자OCIO알아서수익형증권자투자신탁(혼합-재간접형)(모)', 'inception': '20220808', 'aum_억': 8.5},
    '07J27': {'name': '한국투자OCIO알아서인컴형증권자(채권혼합-재간접형)(모)', 'inception': '20220808', 'aum_억': 19.9},
    '07J34': {'name': '한국투자MySuper알아서성장형증권자(혼합-재간접형)(모)', 'inception': '20221005', 'aum_억': 2370.8},
    '07J41': {'name': '한국투자MySuper알아서안정형증권자투자신탁(채권혼합-재간접형)', 'inception': '20221005', 'aum_억': 1358.0},
    '07J48': {'name': '한국투자MySuper수익추구증권모투자신탁(혼합-재간접형)', 'inception': '20221005', 'aum_억': 2261.1},
    '07J49': {'name': '한국투자MySuper인컴추구증권모투자신탁(채권혼합-재간접형)', 'inception': '20221005', 'aum_억': 1548.8},
    '07P70': {'name': '한국투자골든그로스글로벌자산배분증권투자신탁(혼합-재)(모)', 'inception': '20231228', 'aum_억': 518.5},
    '07W15': {'name': '한국투자디딤CPI+증권자투자신탁(채권혼합-재간접형)(모)', 'inception': '20240925', 'aum_억': 90.3},
    '08K88': {'name': '한국투자OCIO알아서성장형일반사모증권투자신탁(혼합-재간접형)', 'inception': '20240930', 'aum_억': 542.3},
    '08N33': {'name': '한국투자OCIO알아서베이직일반사모투자신탁', 'inception': '20250930', 'aum_억': 241.1},
    '08N81': {'name': '한국투자OCIO알아서액티브일반사모투자신탁', 'inception': '20260108', 'aum_억': 188.7},
    '08P22': {'name': '한국투자OCIO알아서프라임일반사모투자신탁', 'inception': '20260123', 'aum_억': 815.9},
    '09L94': {'name': '한국투자MySuper알아서인컴추구형증권자투자신탁(채권혼합-재간접형)(모)', 'inception': '20251031', 'aum_억': 1.3},
    '1JM96': {'name': 'ABL생명글로벌배당인컴주식재간접형', 'inception': '20150417', 'aum_억': 46.1},
    '1JM98': {'name': 'ABL생명글로벌배당인컴주식재간접형(달러형)', 'inception': '20150526', 'aum_억': 1.9},
    '2JM23': {'name': '오렌지라이프자산배분B형', 'inception': '20160324', 'aum_억': 194.7},
    '4JM12': {'name': '(무)동부글로벌 Active 자산배분혼합형', 'inception': '20220318', 'aum_억': 234.6},
}

# 펀드 그룹 분류
FUND_GROUPS = {
    'OCIO 알아서': ['06X08', '07G04', '07J20', '07J27', '08K88', '08N33', '08N81', '08P22'],
    'MySuper': ['07J34', '07J41', '07J48', '07J49', '09L94'],
    '모펀드 (인컴/수익)': ['07G02', '07G03'],
    '골든그로스': ['07P70'],
    '디딤CPI+': ['07W15'],
    'ABL생명': ['1JM96', '1JM98'],
    '오렌지라이프': ['2JM23'],
    '동부글로벌': ['4JM12'],
}

# 펀드별 BM 매핑 (SCIP dataset_id + dataseries_id)
# dataseries_id=6: FG Return, JSON blob {"USD":x, "KRW":y}
# 기본값: S&P 500 TR (dataset_id=24) — 추후 펀드별 실제 BM으로 교체
FUND_BM = {
    '06X08': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07G02': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07G03': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07G04': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07J20': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07J27': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07J34': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07J41': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07J48': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07J49': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07P70': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '07W15': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '08K88': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '08N33': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '08N81': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '08P22': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '09L94': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '1JM96': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '1JM98': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '2JM23': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
    '4JM12': {'dataset_id': 24, 'dataseries_id': 6, 'name': 'S&P 500 TR', 'currency': 'KRW'},
}

# 자산 6분류 매핑 기준
ASSET_6CLASS = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', '유동성']

# DB 접속 설정
DB_CONFIG = {
    'host': '192.168.195.55',
    'user': 'solution',
    'password': 'Solution123!',
    'charset': 'utf8mb4',
}
