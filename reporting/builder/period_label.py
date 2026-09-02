# -*- coding: utf-8 -*-
"""보고 구간을 LLM 프롬프트에 알려주는 블록.

★ 왜 필요한가 (2026-09-02 사용자 리포트): s4·s6 의 시장 코멘트 프롬프트가
`end_date` 만 받아서, **같은 종료일이면 설정이후 PPT 와 하반기 PPT 의 정성 문장이
사실상 동일**하게 나왔다(08N33 실측: 표에서 유도되는 순위 문장만 다르고 LLM 불릿은
조사 몇 개 차이). 구간을 모르니 모델이 구간을 반영할 방법이 없었다.
"""
from __future__ import annotations


def span_block(start_iso, end_iso, plabel=None):
    """프롬프트에 넣을 [보고 구간] 블록. start 가 없으면 종료일만 알린다."""
    if not start_iso:
        return "[보고 구간]" + chr(10) + f"종료일 {end_iso} (시작일 미지정)"
    try:
        from datetime import date

        def _d(s):
            return date(int(s[:4]), int(s[5:7]), int(s[8:10]))

        days = (_d(end_iso) - _d(start_iso)).days
        span = f"{days / 30.44:.1f}개월({days}일)"
    except Exception:
        span = "기간 길이 미상"
    lab = f" · {plabel}" if plabel else ""
    out = [
        "[보고 구간]",
        f"{start_iso} ~ {end_iso} = {span}{lab}",
        "★ 이 코멘트는 **위 구간 전체**를 설명해야 한다. 종료일이 같아도 구간이",
        "  다르면 다른 코멘트가 나와야 한다. 구간이 길면(3개월 초과) 월별 사건을",
        "  나열하지 말고 구간을 관통하는 흐름·누적된 변화로 서술하고, 짧으면 그",
        "  기간에 실제로 일어난 변화에 집중하라.",
        "⚠ 아래 승인 시장 코멘트는 **종료월(또는 종료분기) 기준**이라 구간 전체를",
        "  덮지 않는다. 그 범위를 넘는 사실·수치를 지어내지 말고, 구간 전체를",
        "  말할 때는 표에서 확인되는 것만 근거로 삼아라.",
    ]
    return chr(10).join(out)
