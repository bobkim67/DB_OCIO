"""ETF/펀드 듀레이션·YTM 시계열 fetcher.

설계 원칙
---------
- ITEM_CD별로 자료원 6종 매핑 (운용사 사이트 직접 fetch 또는 수동 dict).
- fetch 호출 시 일자별 디스크 캐시에 누적 저장 → 시계열 archive 형성.
- 같은 날 같은 ITEM_CD 재호출은 캐시 hit → 외부 호출 skip.
- 펀드 단위 가중평균은 호출부에서 계산 (fetcher는 종목 단위 raw 값만 제공).

캐시 위치
---------
market_research/data/duration_archive/{ITEM_CD}/{fetch_date}.json

응답 정규화 schema
-----------------
{
  "item_cd": str,
  "fetch_date": "YYYY-MM-DD",       # 외부 호출 일자
  "as_of_date": "YYYY-MM-DD" | None,  # 운용사 발표 일자 (응답에서 파싱)
  "duration": float | None,
  "ytm": float | None,
  "source": str,                    # ace_papi / kim_papi / samsung_kodex / rise_html / tiger_html / vanguard / jnk_proxy / manual
  "source_id": str | dict,          # 자료원별 식별자 (fundCd/fid/code/ticker 등)
  "raw": dict | str,                # 원본 응답 일부 (디버깅용)
}
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================
# 매핑 dict — ITEM_CD → (source_type, source_id)
# ============================================================
DURATION_SOURCES: dict[str, tuple[str, Any]] = {
    "KR7356540005": ("ace_papi", "K55101D34156"),       # ACE 종합채권(AA-)액티브
    "KR7365780006": ("ace_papi", "K55101D95314"),       # ACE 국고채10년
    "KR7385560008": ("rise_html", "44B7"),              # RISE KIS국고채30년Enhanced
    "KR7439870007": ("samsung_kodex", "2ETFH3"),        # KODEX 국고채30년액티브
    "KR7451530000": ("tiger_html", "KR7451530000"),     # TIGER 국고채30년스트립
    "KR7468380001": ("samsung_kodex", "2ETFL2"),        # KODEX iShares 미국HY (한국 ETF)
    "KRZ502649912": ("kim_papi", "K55101EP7398"),       # 한국투자 TMF26-12
    "KRZ502649922": ("kim_papi", "K55101EP7455"),       # 한국투자 TMF28-12
    "KRZ502659020": ("manual", {"duration": 10.0, "ytm": 3.10,
                                "as_of_date": None,
                                "note": "월넛 은행채플러스 사모 — 사용자 수동 입력"}),
    "US46435U8532": ("jnk_proxy", None),                # iShares USHY 본 ETF → SPDR JNK proxy
    "US9219468850": ("vanguard", "vwob"),               # VWOB
}


# ============================================================
# 캐시 디렉토리
# ============================================================
_REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = _REPO_ROOT / "market_research" / "data" / "duration_archive"


def _cache_path(item_cd: str, fetch_date: str) -> Path:
    return ARCHIVE_DIR / item_cd / f"{fetch_date}.json"


def _load_cache(item_cd: str, fetch_date: str) -> dict | None:
    p = _cache_path(item_cd, fetch_date)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(payload: dict) -> None:
    p = _cache_path(payload["item_cd"], payload["fetch_date"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 공통 HTTP
# ============================================================
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120 Safari/537.36"),
    "Accept": "application/json, text/html, */*",
}


def _http_get(url: str, accept_html: bool = False, timeout: int = 15) -> requests.Response:
    headers = dict(_HEADERS)
    if accept_html:
        headers["Accept"] = "text/html,application/xhtml+xml,*/*"
    return requests.get(url, headers=headers, verify=False, timeout=timeout)


def _norm_yyyymmdd(s: str) -> str | None:
    """'20260428' → '2026-04-28'."""
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _norm_iso_date(s: str) -> str | None:
    """ISO datetime 또는 'YYYY-MM-DD' → 'YYYY-MM-DD'."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).strip().replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


# ============================================================
# Fetcher 구현 — 운용사별
# ============================================================

def _fetch_ace_papi(fund_cd: str) -> dict:
    """https://papi.aceetf.co.kr/api/funds/{fundCd}/performance

    priceList[0] 응답: {"fundPrice":..., "duration": 7.7127, "ytm": 3.7643,
                        "trackingError":..., "us_STPR":..., "std_DT":"20260430", ...}

    duration 은 KIS BMM 기반 펀드 평균 듀레이션 (사이트 상단 카드 7.71 과 일치).
    /ytmcalc 의 duration 은 YTM 역산 modified duration (6.62) 으로 사이트 카드와 다름.
    """
    url = f"https://papi.aceetf.co.kr/api/funds/{fund_cd}/performance"
    r = _http_get(url)
    r.raise_for_status()
    d = r.json()
    pl = d.get("priceList") or []
    if not pl:
        return {"duration": None, "ytm": None, "as_of_date": None, "raw": d}
    head = pl[0]
    return {
        "duration": _to_float(head.get("duration")),
        "ytm": _to_float(head.get("ytm")),
        "as_of_date": _norm_yyyymmdd(head.get("std_DT", "")),
        "raw": head,
    }


def _fetch_kim_papi(fund_cd: str) -> dict:
    """https://papi.kitmc.com/api/funds/{fundCd}/performance

    응답: {"priceList": [{"fundPrice":..., "duration":0.73, "ytm":3.17,
                          "std_DT":"20260428"}, ...], ...}
    priceList[0]이 최신.
    """
    url = f"https://papi.kitmc.com/api/funds/{fund_cd}/performance"
    r = _http_get(url)
    r.raise_for_status()
    d = r.json()
    pl = d.get("priceList") or []
    if not pl:
        return {"duration": None, "ytm": None, "as_of_date": None, "raw": d}
    head = pl[0]
    return {
        "duration": _to_float(head.get("duration")),
        "ytm": _to_float(head.get("ytm")),
        "as_of_date": _norm_yyyymmdd(head.get("std_DT", "")),
        "raw": head,
    }


def _fetch_samsung_kodex(fid: str) -> dict:
    """https://www.samsungfund.com/api/v1/kodex/product/{fid}.do

    응답: {..., "ytm": {"tab8Info": {"itemDur": "3.0081",
                                      "mkprcPrfr": "7.283",
                                      "stkCdInfo": "KR...",
                                      "fnmInfo": "..."}}}
    asOfDate는 별도 호출(`/now/gijun.do`) 또는 ytm.do 응답에서 보강.
    여기서는 ytm.do로 gijunYMD를 함께 가져온다.
    """
    base = "https://www.samsungfund.com/api/v1/kodex"
    r1 = _http_get(f"{base}/product/{fid}.do")
    r1.raise_for_status()
    d = r1.json()
    tab = ((d.get("ytm") or {}).get("tab8Info") or {})
    dur = _to_float(tab.get("itemDur"))
    ytm = _to_float(tab.get("mkprcPrfr"))

    # 일자: product/{fid}.do 응답엔 없을 수 있어 ytm.do로 보강
    as_of = _norm_yyyymmdd(tab.get("gijunYMD") or "")
    if as_of is None:
        try:
            r2 = _http_get(f"{base}/ytm.do?pageRows=100")
            r2.raise_for_status()
            for row in (r2.json().get("ytmList") or []):
                if row.get("fid") == fid:
                    as_of = _norm_yyyymmdd(row.get("gijunYMD", ""))
                    # dur/ytm 누락 시 fallback
                    if dur is None:
                        dur = _to_float(row.get("dur"))
                    if ytm is None:
                        ytm = _to_float(row.get("ytm"))
                    break
        except Exception:
            pass
    return {
        "duration": dur,
        "ytm": ytm,
        "as_of_date": as_of,
        "raw": tab,
    }


def _fetch_rise_html(code: str) -> dict:
    """https://www.riseetf.co.kr/prod/finderDetail/{code}

    h3 sub_page_title에 '(2026.04.29 기준 ETF YTM: 4.22, 듀레이션: 23.79)' 형식.
    """
    url = f"https://www.riseetf.co.kr/prod/finderDetail/{code}"
    r = _http_get(url, accept_html=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    h3 = soup.find("h3", class_=re.compile(r"sub_page_title"))
    if h3 is None:
        return {"duration": None, "ytm": None, "as_of_date": None, "raw": ""}
    txt = h3.get_text(" ", strip=True)
    # 예: "(2026.04.29 기준 ETF YTM: 4.22, 듀레이션: 23.79)"
    m_date = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*기준", txt)
    m_ytm = re.search(r"YTM\s*[:：]\s*([\d.]+)", txt)
    m_dur = re.search(r"듀레이션\s*[:：]\s*([\d.]+)", txt)
    as_of = None
    if m_date:
        y, mo, d = map(int, m_date.groups())
        as_of = f"{y:04d}-{mo:02d}-{d:02d}"
    return {
        "duration": _to_float(m_dur.group(1)) if m_dur else None,
        "ytm": _to_float(m_ytm.group(1)) if m_ytm else None,
        "as_of_date": as_of,
        "raw": txt,
    }


def _fetch_tiger_html(isin: str) -> dict:
    """https://investments.miraeasset.com/tigeretf/ko/product/search/detail/index.do?ksdFund={isin}

    HTML 패턴: <div class="title asterisked">듀레이션</div>
              <div class="desc"><span class="amount">27.55</span><span class="unit">년</span></div>
    + "듀레이션 : 27.55 (년) / YTM(연환산) : 3.68 (%) (기준일자 : 2026-04-28)"
    """
    url = ("https://investments.miraeasset.com/tigeretf/ko/product/search/"
           f"detail/index.do?ksdFund={isin}")
    r = _http_get(url, accept_html=True)
    r.raise_for_status()
    body = r.text
    soup = BeautifulSoup(body, "html.parser")
    # duration / YTM 카드: title 라벨별 desc.amount
    def _amount_after_title(label_substr: str) -> float | None:
        for el in soup.find_all("div", class_="title"):
            t = el.get_text(strip=True)
            if label_substr not in t:
                continue
            sib = el.find_next_sibling()
            if sib:
                amt = sib.find("span", class_="amount")
                if amt:
                    return _to_float(amt.get_text(strip=True))
        return None

    dur = _amount_after_title("듀레이션")
    ytm = _amount_after_title("YTM")

    # 기준일자만 정규식으로 추출
    as_of = None
    m_date = re.search(r"기준일자\s*[:：]\s*(\d{4}-\d{2}-\d{2})", body)
    if m_date:
        as_of = m_date.group(1)

    # fallback: BS 실패 시 combined 텍스트 정규식 (드물지만 안전망)
    if dur is None or ytm is None:
        m_c = re.search(
            r"듀레이션\s*[:：]\s*([\d.]+)\s*\(년\)\s*/\s*YTM[^:]*[:：]\s*([\d.]+)\s*\(",
            body, re.S)
        if m_c:
            if dur is None:
                dur = _to_float(m_c.group(1))
            if ytm is None:
                ytm = _to_float(m_c.group(2))
    return {
        "duration": dur,
        "ytm": ytm,
        "as_of_date": as_of,
        "raw": {"dur_card": dur, "ytm_card": ytm, "as_of_text": as_of},
    }


def _fetch_vanguard(ticker: str) -> dict:
    """https://investor.vanguard.com/vmf/api/{ticker}/characteristic

    응답: {"fixedIncomeCharacteristic": {"fund": {
            "averageDuration": "6.7 years",
            "yieldToMaturity": "6.4",
            "averageDurationDate": "2026-03-31T..."}}}
    Vanguard는 월말 1회 갱신. asOfDate는 averageDurationDate.
    """
    url = f"https://investor.vanguard.com/vmf/api/{ticker.lower()}/characteristic"
    r = _http_get(url)
    r.raise_for_status()
    d = r.json()
    fund = ((d.get("fixedIncomeCharacteristic") or {}).get("fund") or {})

    def _strip_years(s):
        if not s:
            return None
        return _to_float(str(s).replace("years", "").replace("year", "").strip())

    return {
        "duration": _strip_years(fund.get("averageDuration")),
        "ytm": _to_float(fund.get("yieldToMaturity")),
        "as_of_date": _norm_iso_date(fund.get("averageDurationDate") or fund.get("asOfDate") or ""),
        "raw": {
            "averageDuration": fund.get("averageDuration"),
            "yieldToMaturity": fund.get("yieldToMaturity"),
            "averageMaturity": fund.get("averageMaturity"),
            "averageDurationDate": fund.get("averageDurationDate"),
        },
    }


_JNK_URL = ("https://www.ssga.com/us/en/institutional/etfs/"
            "state-street-spdr-bloomberg-high-yield-bond-etf-jnk")


def _fetch_jnk_proxy(_unused) -> dict:
    """SSGA SPDR JNK 페이지에서 Option Adjusted Duration / Yield to Maturity 추출.

    iShares USHY 본 ETF (US46435U8532) 의 자료원 proxy.
    동일 자산군 (미국 하이일드)이라 dur/ytm 차이가 0.1~0.2 수준.
    """
    r = _http_get(_JNK_URL, accept_html=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    def _row_value(label_re):
        for el in soup.find_all(string=re.compile(label_re)):
            tr = el.find_parent("tr")
            if tr:
                tds = tr.find_all("td")
                if tds:
                    return tds[0].get_text(strip=True)
        return None

    oad = _row_value(r"Option Adjusted Duration")
    ytm = _row_value(r"Yield to Maturity")
    # "2.93 years" / "7.20%"
    dur_v = _to_float(oad.replace("years", "").strip()) if oad else None
    ytm_v = _to_float(ytm.replace("%", "").strip()) if ytm else None

    # asOfDate: 페이지 어딘가 "as of YYYY-MM-DD" 또는 "Updated ..."
    as_of = None
    m = re.search(r"as\s+of\s+(\w+\s+\d{1,2},?\s+\d{4})", r.text, re.I)
    if m:
        try:
            as_of = datetime.strptime(m.group(1).replace(",", ""),
                                       "%b %d %Y").date().isoformat()
        except ValueError:
            try:
                as_of = datetime.strptime(m.group(1).replace(",", ""),
                                           "%B %d %Y").date().isoformat()
            except ValueError:
                pass
    return {
        "duration": dur_v,
        "ytm": ytm_v,
        "as_of_date": as_of,
        "raw": {"oad_text": oad, "ytm_text": ytm},
    }


def _fetch_manual(payload: dict) -> dict:
    """수동 입력 dict 그대로 반환 (월넛 사모 등)."""
    return {
        "duration": _to_float(payload.get("duration")),
        "ytm": _to_float(payload.get("ytm")),
        "as_of_date": payload.get("as_of_date"),
        "raw": payload,
    }


_FETCHERS = {
    "ace_papi": _fetch_ace_papi,
    "kim_papi": _fetch_kim_papi,
    "samsung_kodex": _fetch_samsung_kodex,
    "rise_html": _fetch_rise_html,
    "tiger_html": _fetch_tiger_html,
    "vanguard": _fetch_vanguard,
    "jnk_proxy": _fetch_jnk_proxy,
    "manual": _fetch_manual,
}


# ============================================================
# 진입점
# ============================================================

def fetch_duration(item_cd: str, force_refresh: bool = False) -> dict | None:
    """ITEM_CD에 매핑된 자료원에서 duration/ytm 추출.

    - 매 호출 시 fetch 일자 캐시 hit 검사 → hit이면 외부 호출 skip
    - miss이면 외부 호출 후 archive/{ITEM_CD}/{fetch_date}.json 누적 저장
    - 미매핑 ITEM_CD는 None 반환

    Returns
    -------
    dict | None
        성공 시 정규화된 dict, 미매핑이면 None.
    """
    src = DURATION_SOURCES.get(item_cd)
    if src is None:
        return None
    src_type, src_id = src

    fetch_date = date.today().isoformat()

    # 1) cache hit
    if not force_refresh:
        cached = _load_cache(item_cd, fetch_date)
        if cached is not None:
            return cached

    # 2) external fetch
    fetcher = _FETCHERS.get(src_type)
    if fetcher is None:
        return None
    try:
        result = fetcher(src_id)
    except Exception as exc:
        return {
            "item_cd": item_cd,
            "fetch_date": fetch_date,
            "as_of_date": None,
            "duration": None,
            "ytm": None,
            "source": src_type,
            "source_id": src_id if not isinstance(src_id, dict) else "manual",
            "raw": {"error": f"{type(exc).__name__}: {exc}"},
        }

    payload = {
        "item_cd": item_cd,
        "fetch_date": fetch_date,
        "as_of_date": result.get("as_of_date"),
        "duration": result.get("duration"),
        "ytm": result.get("ytm"),
        "source": src_type,
        "source_id": src_id if not isinstance(src_id, dict) else "manual",
        "raw": result.get("raw"),
    }
    _save_cache(payload)
    return payload


def fetch_all(force_refresh: bool = False) -> dict[str, dict | None]:
    """매핑된 11 ITEM_CD 일괄 fetch."""
    return {ic: fetch_duration(ic, force_refresh=force_refresh)
            for ic in DURATION_SOURCES}


def list_archive(item_cd: str) -> list[str]:
    """특정 ITEM_CD의 보관된 fetch_date 목록 (정렬 desc)."""
    d = ARCHIVE_DIR / item_cd
    if not d.is_dir():
        return []
    return sorted([p.stem for p in d.glob("*.json")], reverse=True)


# ============================================================
# 가중평균 헬퍼
# ============================================================

def compute_weighted_duration(
    holdings: list[tuple[str, float]],
    force_refresh: bool = False,
) -> dict:
    """ITEM_CD별 (dur, ytm)을 비중 가중평균.

    Parameters
    ----------
    holdings : list[(item_cd, weight)]
        weight는 % 또는 0~1 fraction 모두 OK (단위는 호출자 일관 유지).
        매핑 안 된 ITEM_CD는 covered에서 제외.
    force_refresh : bool
        True 시 캐시 우회.

    Returns
    -------
    dict
        {
          "duration_bond": float | None,    # 매핑된(채권성) 종목만 가중평균
          "ytm_bond": float | None,
          "duration_overall": float | None, # 전체 비중 분모 가중평균 (미매핑 종목은 dur=0 효과)
          "ytm_overall": float | None,
          "covered_weight": float,          # 매핑된 종목 합산 비중
          "total_weight": float,            # 입력 전체 합산 비중
          "coverage_ratio": float,          # covered / total (0~1)
          "components": [...],              # {item_cd, weight, duration, ytm, source, source_id, as_of_date}
          "missing": [item_cd, ...],        # 매핑 dict에 없는 ITEM_CD
        }

    Backward compat: 'duration'/'ytm' 키도 'duration_bond'/'ytm_bond' 값으로 함께 반환.
    """
    components: list[dict] = []
    missing: list[str] = []
    total_weight = 0.0
    covered_weight = 0.0
    sum_dur_w = 0.0
    sum_ytm_w = 0.0
    sum_w_with_dur = 0.0
    sum_w_with_ytm = 0.0

    for item_cd, weight in holdings:
        try:
            w = float(weight)
        except (TypeError, ValueError):
            continue
        if w == 0:
            continue
        total_weight += w
        if item_cd not in DURATION_SOURCES:
            missing.append(item_cd)
            continue
        data = fetch_duration(item_cd, force_refresh=force_refresh)
        if data is None:
            missing.append(item_cd)
            continue
        dur = data.get("duration")
        ytm = data.get("ytm")
        components.append({
            "item_cd": item_cd,
            "weight": w,
            "duration": dur,
            "ytm": ytm,
            "source": data.get("source"),
            "source_id": data.get("source_id"),
            "as_of_date": data.get("as_of_date"),
        })
        covered_weight += w
        if dur is not None:
            sum_dur_w += w * dur
            sum_w_with_dur += w
        if ytm is not None:
            sum_ytm_w += w * ytm
            sum_w_with_ytm += w

    dur_bond = (sum_dur_w / sum_w_with_dur) if sum_w_with_dur > 0 else None
    ytm_bond = (sum_ytm_w / sum_w_with_ytm) if sum_w_with_ytm > 0 else None
    dur_overall = (sum_dur_w / total_weight) if total_weight > 0 else None
    ytm_overall = (sum_ytm_w / total_weight) if total_weight > 0 else None
    cov_ratio = (covered_weight / total_weight) if total_weight > 0 else 0.0

    return {
        "duration_bond": dur_bond,
        "ytm_bond": ytm_bond,
        "duration_overall": dur_overall,
        "ytm_overall": ytm_overall,
        # backward compat
        "duration": dur_bond,
        "ytm": ytm_bond,
        "covered_weight": covered_weight,
        "total_weight": total_weight,
        "coverage_ratio": cov_ratio,
        "components": components,
        "missing": missing,
    }
