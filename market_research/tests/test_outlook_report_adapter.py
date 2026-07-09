# -*- coding: utf-8 -*-
"""outlook_report_adapter 순수 함수 테스트 (COM 비의존).

python -m market_research.tests.test_outlook_report_adapter
"""
from market_research.collect.outlook_report_adapter import (
    clean_body, is_dup_title, norm_title, resolve_broker, should_collect,
)


def test_resolve_broker():
    assert resolve_broker('kiwoom.com', '') == '키움증권'
    assert resolve_broker('DBSEC.CO.KR', '아무개') == 'DB금융투자'
    assert resolve_broker('', '김태훈') == '한국투자증권'   # 사내 EX 발신 화이트리스트
    assert resolve_broker('kim.co.kr', '') is None          # 신문기사 모음 → news, 제외
    assert resolve_broker('unknown.com', '이정민') is None


def test_should_collect_exclude_kw():
    ok = should_collect('kiwoom.com', '', '글로벌 시황 및 당사 리서치 리포트 공유')
    assert ok
    # 화이트리스트 발신이라도 제외 키워드 → drop
    assert not should_collect('', '김태훈', 'BESS 세미나 제안드립니다')
    assert not should_collect('', '김태훈', 'Russell 리밸런싱 — 주문 참고사항')
    assert not should_collect('koreainvestment.com', '', '2026.07.01 신문기사 모음 & 보도자료')
    # 비대상 발신 → drop
    assert not should_collect('skills.google', '', '리포트')


def test_norm_title():
    # 브래킷/작성자 프리픽스/날짜 제거
    assert norm_title('[Econ Guide] JPY 저평가 개선에 무게') == norm_title('JPY 저평가 개선에 무게')
    assert norm_title('DB증권_강현기_GPU렌탈,토큰사용(2026.07.06)') == 'gpu렌탈토큰사용'


def test_is_dup_title():
    naver = [norm_title('JPY 저평가 개선에 무게'), norm_title('7월 글로벌 전략: 여전한 성장주 우위')]
    assert is_dup_title('[Econ Guide] JPY 저평가 개선에 무게', naver)          # containment
    assert is_dup_title('7월 글로벌전략 - 여전한 성장주 우위', naver)          # ratio
    assert not is_dup_title('[키움증권/신성준] BofA 주간 Fund flow 리포트', naver)
    assert not is_dup_title('짧은제목', naver)  # 정규화 8자 미만 → dedupe 안 함


def test_clean_body():
    body = (
        '안녕하십니까 키움증권 홍길동입니다.\r\n\r\n'
        '금일 미 증시는 반도체 강세로 상승 마감했습니다.\r\n'
        'Fed 9월 인하 기대가 유지되며 금리는 하락.\r\n\r\n'
        '본 메일은 투자 참고자료입니다. 수신거부는 회신 바랍니다.'
    )
    out = clean_body(body)
    assert out.startswith('금일 미 증시는')          # greeting 제거
    assert '수신거부' not in out                     # disclaimer 절단
    assert 'Fed 9월 인하' in out                     # 본문 보존


def main() -> int:
    fns = [v for k, v in globals().items() if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f'  PASS {fn.__name__}')
    print(f'[test_outlook_report_adapter] {len(fns)}/{len(fns)} PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
