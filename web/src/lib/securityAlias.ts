// 차트 표기용 종목 별칭 — 긴 정식명 → 짧은 표기 (item_nm 기준 매칭).
// 표/드롭다운은 정식명 유지, 차트 라벨에서만 사용. (2026-06-24 사용자 지정)
const ALIAS: Record<string, string> = {
  // 주식
  "ACE 미국대형성장주액티브": "ACE 미국대형성장",
  "ACE 미국대형가치주액티브": "ACE 미국대형가치",
  "ACE 미국나스닥100": "ACE 나스닥100",
  "VANGUARD FTSE EMERGING MARKETS": "Vanguard EM",
  "VANGUARD FTSE DEVELOPED ETF": "Vanguard DM",
  "State Street SPDR Portfolio S&P 500 Grow": "S&P500(G)",
  "State Street SPDR Portfolio S&P 500 Valu": "S&P500(V)", // 선제등록(현재 미보유, 출현 시 검증)
  // 채권
  "한국투자TMF26-12만기형증권투자신탁(채권)": "한국투자TMF 26-12",
  "한국투자TMF28-12만기형증권투자신탁(채권)": "한국투자TMF 28-12",
  "TIGER 국고채30년스트립액티브": "TIGER 국고채30년(S)",
  "KODEX 국고채30년액티브": "KODEX 국고채30년",
  "RISE KIS국고채30년Enhanced": "RISE 국고채30년(E)",
  "ACE 종합채권(AA-이상)액티브": "ACE 종합채권",
  "KODEX iShares미국하이일드액티브": "KODEX 미국HY",
  "iShares Broad USD High Yield Corporate B": "iShares USD HY",
  "VANGUARD EMERG MKTS GOV BND": "Vanguard EM국채",
  "월넛은행채플러스일반사모투자신탁제3호": "월넛은행채플러스",
  // 브로커 체결확인서(해외거래 메일) 정식명 — 원장 ITEM_NM 과 표기가 달라 별도 등재.
  // 결제 예정 카드/툴팁에서만 쓰임 (2026-08-03).
  "ISHARES GOLD TRUST UNDIVIDED BENEFICIAL INTS USD": "iShares Gold Trust",
  // (ACE 200 / ACE 200 TR / ACE 국고채10년 등 짧은 이름은 그대로 노출)
};

/** 차트 라벨용 짧은 표기. 매핑 없으면 원본 반환. */
export function secAlias(name: string): string {
  return ALIAS[name] ?? name;
}
