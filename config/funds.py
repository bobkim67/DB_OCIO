# === DB OCIO 운용 펀드 목록 ===
# 현재 운용중인 사모 OCIO 펀드 코드 (dt.DWPM10510 기준)
# 최근 기준일: 2026-02-11, 총 AUM: ~1.4조원

FUND_LIST = [
    '07G02', '07G03', '07G04',
    '08K88', '08N33', '08N81', '08P22',
    '2JM23', '4JM12'
]

# 펀드 메타정보 (DB 조회 결과 기반, 2026-02-11)
FUND_META = {
    '07G02': {'name': '한국투자인컴추구증권모투자신탁(채권혼합-재간접형)', 'inception': '20210927', 'aum_억': 883.4},
    '07G03': {'name': '한국투자수익추구증권모투자신탁(혼합-재간접형)', 'inception': '20210927', 'aum_억': 888.2},
    '07G04': {'name': '한국투자OCIO알아서증권자투자신탁(채권혼합-재간접형)(모)', 'inception': '20210927', 'aum_억': 1749.6},
    '08K88': {'name': '한국투자OCIO알아서성장형일반사모증권투자신탁(혼합-재간접형)', 'inception': '20240930', 'aum_억': 542.3},
    '08N33': {'name': '한국투자OCIO알아서베이직일반사모투자신탁', 'inception': '20250930', 'aum_억': 241.1},
    '08N81': {'name': '한국투자OCIO알아서액티브일반사모투자신탁', 'inception': '20260108', 'aum_억': 188.7},
    '08P22': {'name': '한국투자OCIO알아서프라임일반사모투자신탁', 'inception': '20260123', 'aum_억': 815.9},
    '2JM23': {'name': '오렌지라이프자산배분B형', 'inception': '20160324', 'aum_억': 194.7},
    '4JM12': {'name': '(무)동부글로벌 Active 자산배분혼합형', 'inception': '20220318', 'aum_억': 234.6},
}

# 펀드 그룹 분류
FUND_GROUPS = {
    'OCIO 알아서': ['07G04', '08K88', '08N33', '08N81', '08P22'],
    '모펀드 (인컴/수익)': ['07G02', '07G03'],
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
# BM 미설정 펀드: 07G02, 07G03, 08N33, 08N81, 08P22, 2JM23

_C = lambda ds, ser, w, nm, cur=None, region='KR', hedged=False: {'dataset_id': ds, 'dataseries_id': ser, 'weight': w, 'name': nm, 'currency': cur, 'region': region, 'hedged': hedged}

FUND_BM = {
    # 07G04: 0.34×MSCI ACWI Gross + 0.25×Bloomberg AGG H KRW + 0.41×KIS KTB 10Y
    # R 동일: MSCI ACWI ex_KR(T-1×USDKRW, FX 가산분해), BBG AGG hedged(T-1 shift)
    '07G04': {
        'name': '0.34×MSCI ACWI Gross + 0.25×BBG AGG(H) + 0.41×KIS KTB10Y',
        'components': [
            _C(57, 9, 0.34, 'MSCI ACWI Gross TR', cur='USD', region='ex_KR'),
            _C(256, 9, 0.25, 'Bloomberg AGG Hedged KRW', region='ex_KR', hedged=True),
            _C(209, 33, 0.41, 'KIS KTB 10Y'),
        ],
    },
    # 08K88: 0.216×KOSPI + 0.504×MSCI ACWI + 0.1×BBG AGG(H) + 0.1×KAP All + 0.08×KAP Call
    # R 프로덕션 동일: ds/dseries + region + hedge_ratio + cost_adjust=34bp + biz_day_adj=-1(ex_KR)
    '08K88': {
        'name': '0.216×KOSPI + 0.504×MSCI ACWI + 0.1×BBG AGG(H) + 0.1×KAP All + 0.08×KAP Call',
        'components': [
            _C(253, 15, 0.216, 'KOSPI Index', cur='KRW'),                               # KR, biz_day_adj=0
            _C(35, 15, 0.504, 'MSCI ACWI Index', cur='USD', region='ex_KR'),            # ex_KR, biz_day_adj=-1, (t-1)×USDKRW
            _C(256, 9, 0.100, 'Bloomberg AGG Hedged KRW', region='ex_KR', hedged=True),  # ex_KR, hedge_ratio=1, biz_day_adj=-1
            _C(257, 9, 0.100, 'KAP Korea Bond All'),                                    # KR, biz_day_adj=0
            _C(255, 9, 0.080, 'KAP MMI Call'),                                          # KR, biz_day_adj=0
        ],
    },
    # 4JM12 R 프로덕션: KAP Bond All(257/9, 0.495) + KAP MMI Call(255/9, 0.055)
    #                   + MSCI ACWI(35/15) 0.225 unhedged + 0.225 hedged
    '4JM12': {
        'name': '0.225×ACWI(unH) + 0.225×ACWI(H) + 0.495×KAP All + 0.055×KAP MMI Call',
        'components': [
            _C(35, 15, 0.225, 'MSCI ACWI Index (Unhedged)', cur='USD', region='ex_KR'),
            _C(35, 15, 0.225, 'MSCI ACWI Index (Hedged)',  cur='USD', region='ex_KR', hedged=True),
            _C(257, 9,  0.495, 'KAP Korea Bond All'),
            _C(255, 9,  0.055, 'KAP MMI Call'),
        ],
    },
    # BM 미설정 펀드: 07G02, 07G03, 08N33, 08N81, 08P22, 2JM23
    # → Tab 0에서 BM 없이 표시
}

# ============================================================
# 펀드별 MP(Model Portfolio) 매핑
# ============================================================

# DB 기반 MP (fund_code → sol_MP_released_inform.펀드설명)
FUND_MP_MAPPING = {
    '07G02': 'TIF',            # 인컴추구 모펀드
    '07G03': 'TDF2050',        # 수익추구 모펀드
    '07G04': 'MS STABLE',      # OCIO 채권혼합 모
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
