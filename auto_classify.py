"""
자산 자동 분류 모듈

종목 코드와 종목명을 기반으로 자동 분류를 수행합니다.
"""

def auto_classify_item(item_cd, item_nm):
    """
    종목명 기반 자동 분류
    
    Parameters:
    -----------
    item_cd : str
        종목 코드
    item_nm : str
        종목명
    
    Returns:
    --------
    dict or None
        {'대분류': str, '지역': str, '소분류': str} 또는 None (자동 분류 불가)
    """
    item_nm_upper = str(item_nm).upper()
    item_cd_upper = str(item_cd).upper()
    
    # 1. 콜론 (최우선)
    if '콜론' in item_nm_upper or '증권(콜론)' in item_nm_upper:
        return {'대분류': '현금', '지역': '국내', '소분류': '현금 등'}
    
    # 2. 금 관련
    if 'GOLD' in item_nm_upper or '금현물' in item_nm_upper or 'KRX금' in item_nm_upper:
        if 'KR' in item_cd_upper[:2]:
            return {'대분류': '대체', '지역': '국내', '소분류': '금'}
        else:
            return {'대분류': '대체', '지역': '글로벌', '소분류': '금'}
    
    # 3. 달러 선물
    if '달러 F' in item_nm_upper or 'USD F' in item_nm_upper or '미국달러 F' in item_nm_upper:
        return {'대분류': '통화', '지역': '미국', '소분류': '달러 선물'}
    
    # 4. 코스피 선물
    if '코스피' in item_nm_upper and ' F ' in item_nm_upper:
        return {'대분류': '주식', '지역': '국내', '소분류': '코스피 선물'}
    
    # 5. REPO
    if 'REPO' in item_nm_upper:
        return {'대분류': '채권', '지역': '국내', '소분류': 'REPO'}
    
    # 6. 예금/증거금
    if any(word in item_nm_upper for word in ['예금', '증거금', 'DEPOSIT']):
        if 'USD' in item_nm_upper or '외화' in item_nm_upper or 'DOLLAR' in item_nm_upper:
            return {'대분류': '현금', '지역': '미국', '소분류': '현금 등'}
        else:
            return {'대분류': '현금', '지역': '국내', '소분류': '현금 등'}
    
    # 7. 미수금/미지급금/청약금 등
    if any(word in item_nm_upper for word in ['미수', '미지급', '청약금', '원천세', '분배금', '기타자산']):
        return {'대분류': '현금', '지역': '국내', '소분류': '현금 등'}
    
    # 자동 분류 불가
    return None


def get_auto_classify_stats(items_df):
    """
    자동 분류 통계 계산
    
    Parameters:
    -----------
    items_df : DataFrame
        종목 데이터프레임 (ITEM_CD, ITEM_NM 컬럼 필요)
    
    Returns:
    --------
    dict
        {'category_name': count, ...}
    """
    stats = {
        '콜론': 0,
        '금': 0,
        '달러 선물': 0,
        '코스피 선물': 0,
        'REPO': 0,
        '예금/증거금': 0,
        '미수/청약': 0,
    }
    
    for _, row in items_df.iterrows():
        result = auto_classify_item(row['ITEM_CD'], row['ITEM_NM'])
        if result:
            item_nm_upper = str(row['ITEM_NM']).upper()
            
            if '콜론' in item_nm_upper:
                stats['콜론'] += 1
            elif 'GOLD' in item_nm_upper or '금' in item_nm_upper:
                stats['금'] += 1
            elif '달러 F' in item_nm_upper:
                stats['달러 선물'] += 1
            elif '코스피' in item_nm_upper and ' F ' in item_nm_upper:
                stats['코스피 선물'] += 1
            elif 'REPO' in item_nm_upper:
                stats['REPO'] += 1
            elif any(w in item_nm_upper for w in ['예금', '증거금', 'DEPOSIT']):
                stats['예금/증거금'] += 1
            elif any(w in item_nm_upper for w in ['미수', '미지급', '청약금']):
                stats['미수/청약'] += 1
    
    return {k: v for k, v in stats.items() if v > 0}
