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

# ============================================================
# 펀드별 BM (Benchmark) 매핑
# ============================================================
# 복합: {'name', 'components': [{'dataset_id', 'dataseries_id', 'weight', 'name', 'currency'}, ...]}
# SCIP 지수 ID:
#   MSCI ACWI Gross TR (57/9), MSCI ACWI Standard TR (35/39),
#   KIS 종합채권 TR (279/40), Bloomberg Global AGG H KRW (256/9),
#   KIS KTB 10Y (209/33), KOSPI (253/9), KIS Call (288/40)
# BM 미설정 펀드: 07P70, 07W15, 08N33, 08N81, 09L94, 2JM23, 4JM12

_C = lambda ds, ser, w, nm, cur=None: {'dataset_id': ds, 'dataseries_id': ser, 'weight': w, 'name': nm, 'currency': cur}

FUND_BM = {
    # 06X08: 0.5×MSCI ACWI Gross + 0.5×KIS종합채권
    '06X08': {
        'name': '0.5×MSCI ACWI Gross + 0.5×KIS종합채권',
        'components': [_C(57, 9, 0.50, 'MSCI ACWI Gross TR'), _C(279, 40, 0.50, 'KIS 종합채권 TR')],
    },
    # 07G04: 0.34×MSCI ACWI Gross + 0.25×Bloomberg AGG H KRW + 0.41×KIS KTB 10Y
    '07G04': {
        'name': '0.34×MSCI ACWI Gross + 0.25×BBG AGG(H) + 0.41×KIS KTB10Y',
        'components': [
            _C(57, 9, 0.34, 'MSCI ACWI Gross TR'),
            _C(256, 9, 0.25, 'Bloomberg AGG Hedged KRW'),
            _C(209, 33, 0.41, 'KIS KTB 10Y'),
        ],
    },
    # 07J20: 0.4×MSCI ACWI Gross + 0.6×KIS종합채권
    '07J20': {
        'name': '0.4×MSCI ACWI Gross + 0.6×KIS종합채권',
        'components': [_C(57, 9, 0.40, 'MSCI ACWI Gross TR'), _C(279, 40, 0.60, 'KIS 종합채권 TR')],
    },
    # 07J27: 0.2×MSCI ACWI Gross + 0.8×KIS종합채권
    '07J27': {
        'name': '0.2×MSCI ACWI Gross + 0.8×KIS종합채권',
        'components': [_C(57, 9, 0.20, 'MSCI ACWI Gross TR'), _C(279, 40, 0.80, 'KIS 종합채권 TR')],
    },
    # 07J34: 0.7×MSCI ACWI Gross + 0.3×KIS종합채권
    '07J34': {
        'name': '0.7×MSCI ACWI Gross + 0.3×KIS종합채권',
        'components': [_C(57, 9, 0.70, 'MSCI ACWI Gross TR'), _C(279, 40, 0.30, 'KIS 종합채권 TR')],
    },
    # 07J41: 0.2×MSCI ACWI Gross + 0.8×KIS종합채권
    '07J41': {
        'name': '0.2×MSCI ACWI Gross + 0.8×KIS종합채권',
        'components': [_C(57, 9, 0.20, 'MSCI ACWI Gross TR'), _C(279, 40, 0.80, 'KIS 종합채권 TR')],
    },
    # 08K88: 0.216×KOSPI + 0.504×MSCI ACWI Std + 0.1×BBG AGG(H) + 0.1×KIS종합채권 + 0.08×KIS Call
    # (매경BP종합 → KIS종합채권으로 대체, 연34bp 비용 차감 생략)
    '08K88': {
        'name': '0.216×KOSPI + 0.504×MSCI ACWI + 0.1×BBG AGG(H) + 0.1×KIS종합 + 0.08×CALL',
        'components': [
            _C(253, 9, 0.216, 'KOSPI Index'),
            _C(35, 39, 0.504, 'MSCI ACWI Standard TR'),
            _C(256, 9, 0.100, 'Bloomberg AGG Hedged KRW'),
            _C(279, 40, 0.100, 'KIS 종합채권 TR'),
            _C(288, 40, 0.080, 'KIS Call'),
        ],
    },
    # 1JM96: 0.9×MSCI ACWI Standard + 0.1×CALL금리
    '1JM96': {
        'name': '0.9×MSCI ACWI Standard + 0.1×CALL',
        'components': [_C(35, 39, 0.90, 'MSCI ACWI Standard TR'), _C(288, 40, 0.10, 'KIS Call')],
    },
    # 1JM98: 0.9×MSCI ACWI Standard (USD) + 0.1×ZERO
    '1JM98': {
        'name': '0.9×MSCI ACWI Standard (USD)',
        'components': [_C(35, 39, 0.90, 'MSCI ACWI Standard TR')],
    },
    # 4JM12: 0.55×KBP동부생명7 + 0.225×MSCI ACWI(USD) + 0.225×MSCI ACWI(USDKRW)
    # KBP동부생명7 미존재 → MSCI ACWI + KIS종합채권 혼합으로 근사
    '4JM12': {
        'name': '0.45×MSCI ACWI Standard + 0.55×KIS종합채권 (근사)',
        'components': [_C(35, 39, 0.45, 'MSCI ACWI Standard TR'), _C(279, 40, 0.55, 'KIS 종합채권 TR')],
    },
    # BM 미설정 펀드: 07P70, 07W15, 08N33, 08N81, 08P22, 09L94, 2JM23
    # → Tab 0에서 BM 없이 표시
}

# ============================================================
# 펀드별 MP(Model Portfolio) 매핑
# ============================================================

# DB 기반 MP (fund_code → sol_MP_released_inform.펀드설명)
FUND_MP_MAPPING = {
    '07J34': 'MS GROWTH',      # MySuper 성장형
    '07J41': 'MS STABLE',      # MySuper 안정형
    '07J48': 'TDF2050',        # MySuper 수익추구 모
    '07J49': 'TIF',            # MySuper 인컴추구 모
    '07G02': 'TIF',            # 인컴추구 모펀드
    '07G03': 'TDF2050',        # 수익추구 모펀드
    '07G04': 'MS STABLE',      # OCIO 채권혼합 모
    '07P70': 'Golden Growth',  # 골든그로스 (경기국면 1~4, 기본=1)
    '06X08': 'MS GROWTH',      # OCIO RSP
    '07J20': 'TDF2050',        # OCIO 수익형
    '07J27': 'TIF',            # OCIO 인컴형
    '09L94': 'TIF',            # MySuper 인컴추구형 모
    '07W15': 'TIF',            # 디딤CPI+
}

# 직접 지정 MP (8분류 비중 %, DB 외 펀드)
FUND_MP_DIRECT = {
    '08K88': {'국내주식': 16.2, '해외주식': 67.4, '국내채권': 8.2, '해외채권': 8.2,
              '대체투자': 0.0, 'FX': 0.0, '모펀드': 0.0, '유동성': 0.0},
    '08N33': {'국내주식': 4.9, '해외주식': 16.6, '국내채권': 59.8, '해외채권': 7.0,
              '대체투자': 11.7, 'FX': 0.0, '모펀드': 0.0, '유동성': 0.0},
    '08N81': {'국내주식': 4.3, '해외주식': 32.0, '국내채권': 35.3, '해외채권': 7.0,
              '대체투자': 20.9, 'FX': 0.0, '모펀드': 0.0, '유동성': 0.5},
    '08P22': {'국내주식': 3.5, '해외주식': 12.9, '국내채권': 75.8, '해외채권': 0.0,
              '대체투자': 7.8, 'FX': 0.0, '모펀드': 0.0, '유동성': 0.0},
    '2JM23': {'국내주식': 1.5, '해외주식': 49.1, '국내채권': 21.0, '해외채권': 2.0,
              '대체투자': 26.5, 'FX': 0.0, '모펀드': 0.0, '유동성': 0.0},
    '4JM12': {'국내주식': 0.0, '해외주식': 45.0, '국내채권': 50.0, '해외채권': 0.0,
              '대체투자': 0.0, 'FX': 22.5, '모펀드': 0.0, '유동성': 0.0},
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
