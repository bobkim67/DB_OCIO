from datetime import date

from config.funds import (
    DEFAULT_MAPPING_METHOD,
    FUND_BM,
    FUND_DEFAULT_MAPPING_METHOD,
    FUND_GROUPS,
    FUND_LIST,
    FUND_META,
)

from ..schemas.fund import FundMetaDTO


def _fund_group_of(code: str) -> str:
    for group, codes in FUND_GROUPS.items():
        if code in codes:
            return group
    return "기타"


def _parse_yyyymmdd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def list_funds() -> list[FundMetaDTO]:
    out: list[FundMetaDTO] = []
    for code in FUND_LIST:
        meta = FUND_META.get(code, {})
        inc_str = meta.get("inception", "20220101")
        out.append(FundMetaDTO(
            code=code,
            name=meta.get("name", code),
            group=_fund_group_of(code),
            inception=_parse_yyyymmdd(inc_str),
            bm_configured=code in FUND_BM,
            default_mapping_method=FUND_DEFAULT_MAPPING_METHOD.get(
                code, DEFAULT_MAPPING_METHOD
            ),
        ))
    return out
