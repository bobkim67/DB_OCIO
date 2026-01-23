import pandas as pd
from datetime import datetime
from auto_classify import auto_classify_item, get_auto_classify_stats

# =========================
# 초기 마스터 데이터
# =========================
data = """1751100	미수ETF분배금	현금	국내	현금 등
KR7332500008	ACE 200TR	주식	국내	일반
KR7367380003	ACE 미국나스닥100	주식	미국	일반
KR7453850000	ACE 미국30년국채액티브(H)	채권	미국	장기채
KR7356540005	ACE 종합채권(AA-이상)액티브	채권	국내	종합채권
KR7360200000	ACE 미국S&P500	주식	미국	일반
KR7363570003	KODEX 장기종합채권(AA-이상)액티브	채권	국내	종합채권
KR7365780006	ACE 국고채10년	채권	국내	장기채
KR7402970008	ACE 미국배당다우존스	주식	미국	일반
KR7438330003	TIGER 우량회사채액티브	채권	국내	투자등급
KR7458250008	TIGER 미국30년국채스트립액티브(합성 H)	채권	미국	장기채
KRZ501529957	한국투자크레딧포커스ESG자1호(채권)(C-W)	채권	국내	투자등급
KR7461270001	ACE 26-06 회사채(AA-이상)액티브	채권	국내	종합채권
US78464A5083	SPDR S&P 500 VALUE ETF	주식	미국	가치
US78464A4094	SPDR S&P 500 Growth	주식	미국	성장
US9229087443	VANGUARD VALUE ETF	주식	미국	가치
US9219438580	VANGUARD FTSE DEVELOPED ETF	주식	선진국	일반
US9220428588	VANGUARD FTSE EMERGING MARKETS	주식	신흥국	일반
US92206C6646	Vanguard Russell 2000 ETF	주식	미국	중소형
US9229087369	VANGUARD GROWTH ETF	주식	미국	성장
032280007G02	한국투자인컴추구증권모투자신탁(채권혼합-	모펀드	모펀드	모펀드
032280007G03	한국투자수익추구증권모투자신탁(혼합-재간	모펀드	모펀드	모펀드
032280007J48	한국투자MySuper수익추구증권모투자신탁(혼	모펀드	모펀드	모펀드
032280007J49	한국투자MySuper인컴추구증권모투자신탁(채	모펀드	모펀드	모펀드
US46090F1003	INVESCO OPTIMUM YIELD DIVERS	대체	글로벌	혼합
US4642861037	ISHARES MSCI AUSTRALIA ETF	주식	호주	일반
US4642876142	ISHARES RUSSELL 1000 GROWTH	주식	미국	중소형
US4642877397	ISHARES US REAL ESTATE ETF	대체	미국	부동산
US46434V6478	ISHARES GLOBAL REIT ETF	대체	글로벌	부동산
US78463X8552	SPDR S&P Global Infrastructure	대체	글로벌	인프라
KR7152380002	KODEX 국채선물10년	채권	국내	장기채
KR7438570004	SOL 국고채10년	채권	국내	장기채
KR7471230003	KODEX 국고채10년액티브	채권	국내	장기채
US4642871762	ISHARES BARCLAYS TIPS BOND	채권	미국	물가채
US46435U8532	iShares Broad USD High Yield Corporate B	채권	미국	하이일드
US78468R6229	SPDR Bloomberg High Yield Bond ETF	채권	미국	하이일드
KR7114260003	KODEX 국고채3년	채권	국내	단기채
KR7114460009	ACE 국고채3년	채권	국내	단기채
KR7310960000	TIGER 200TR	주식	국내	일반
LU0772969993	FIDELITY GLOBAL DIVIDEND FUND A ACC USD	주식	글로벌	고배당
KR7273130005	KODEX 종합채권(AA-이상)액티브	채권	국내	종합채권
KR7484790001	KODEX 미국30년국채액티브(H)	채권	미국	장기채
KR7487340002	ACE 머니마켓액티브	채권	국내	단기채
KR7481430007	RISE 국고채10년액티브	채권	국내	장기채
KR7451530000	TIGER 국고채30년스트립액티브	채권	국내	장기채
KR70085N0005	ACE 미국10년국채액티브(H)	채권	미국	장기채
KR70085P0003	ACE 미국10년국채액티브	채권	미국	장기채
KR7105190003	ACE 200	주식	국내	일반
KR70127M0006	ACE 미국대형가치주액티브	주식	미국	가치
KR70127P0003	ACE 미국대형성장주액티브	주식	미국	성장
KRZ502649912	한국투자TMF26-12만기형증권투자신탁(채권)	채권	국내	단기채
KRZ502649922	한국투자TMF28-12만기형증권투자신탁(채권)	채권	국내	단기채
1912100	기타자산	기타	국내	기타
000000000000	미지급외화거래비용	현금	국내	현금 등"""

# 데이터 파싱
lines = [line.split('\t') for line in data.strip().split('\n')]

# DataFrame 생성
df = pd.DataFrame(lines, columns=['ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류'])

# 자동 분류 적용
def auto_classify(row):
    """종목명 기반 자동 분류"""
    result = auto_classify_item(row['ITEM_CD'], row['ITEM_NM'])
    
    if result:
        return pd.Series(result)
    
    # 기본값은 원본 유지
    return pd.Series({
        '대분류': row['대분류'],
        '지역': row['지역'],
        '소분류': row['소분류']
    })

# 자동 분류 적용
df[['대분류', '지역', '소분류']] = df.apply(auto_classify, axis=1)

# 등록일, 비고 추가
df['등록일'] = datetime.now().strftime('%Y-%m-%d')
df['비고'] = ''

# 저장
output_file = "master_asset_mapping.pkl"
df.to_pickle(output_file)

print(f"[✓] 초기 마스터 테이블 생성 완료!")
print(f"[✓] 파일: {output_file}")
print(f"[✓] 총 {len(df)}개 종목 등록")

print(f"\n{'='*80}")
print("🤖 자동 분류 적용 결과:")
print(f"{'='*80}")

# 자동 분류 통계 (원본 데이터 기준)
original_df = pd.DataFrame(lines, columns=['ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류'])
auto_stats = get_auto_classify_stats(original_df)

total_auto = sum(auto_stats.values())
for category, count in auto_stats.items():
    print(f"  ✓ {category}: {count}개")

print(f"\n  🎯 총 {total_auto}개 자동 분류됨")

print(f"\n{'='*80}")
print("샘플 데이터 (처음 15개):")
print(f"{'='*80}")
print(df.head(15)[['ITEM_CD', 'ITEM_NM', '대분류', '지역', '소분류']].to_string(index=False))

print(f"\n{'='*80}")
print("소분류별 분포:")
print(f"{'='*80}")
print(df['소분류'].value_counts())
