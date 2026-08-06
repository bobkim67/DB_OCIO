"""load_fund_meta 총보수(fee_bp) 회귀 — BOS3203 유효기간 합산 + bp 환산.

2026-08-06 수정 전엔 `MAX(apply_frdate)` 한 날짜의 행만 합쳐서, 컴포넌트 중
일부만 나중에 갱신된 펀드는 그 컴포넌트 단독 값이 나왔다. 2JM23 은 2024-12-16 에
A50 만 바뀌어 0.16(A50 단독)을 돌려줬다 — 실제 총보수는 7.225(=0.7225%)다.

추가로 `BOS3203.fee_rate_bp` 는 이름과 달리 **0.1%p 단위**라 ×10 해야 진짜 bp 다.
"""
import pytest

from modules.data_loader import load_fund_meta

# 2JM23 연 총보수(%) — 신한라이프 2026-06 발송본의 보수 환원 값을 역산해 확정했다.
# (구 `tools/shinhan_monthly_ppt.FEE_ANNUAL_PCT`. 표② 를 엑셀 범위에서 빼면서
#  빌더 상수는 사라졌고, 검증값으로서의 출처만 여기 남긴다.)
FEE_ANNUAL_PCT = 0.7225


def test_2jm23_fee_sums_all_valid_components():
    """유효기간 필터 — 컴포넌트 전량 합산(0.16 단독 아님)."""
    fee_bp = load_fund_meta("2JM23")["fee_bp"]
    assert fee_bp == pytest.approx(72.25)
    # 발송본 검증 상수와 단위까지 일치 (bp → %)
    assert fee_bp / 100 == pytest.approx(FEE_ANNUAL_PCT)


@pytest.mark.parametrize("fund,expected_bp", [
    ("08K88", 34.0),
    ("4JM12", 55.0),
    ("06X08", 29.5),
    ("07G04", 0.0),   # 모펀드 — 보수 없음
])
def test_fee_bp_unchanged_for_single_version_funds(fund, expected_bp):
    """컴포넌트가 모두 같은 apply_frdate 인 펀드는 수정 전후 값이 같아야 한다."""
    assert load_fund_meta(fund)["fee_bp"] == pytest.approx(expected_bp)
