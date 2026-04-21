# -*- coding: utf-8 -*-
"""
Naver Finance Research collector — Phase 1 v0.2.0 (plan_naver_research.md v0.5).

5개 카테고리(경제분석/시황정보/투자정보/산업분석/채권분석) 리포트의
메타 + summary 본문 + (선택적) PDF 바이너리를 월별 JSON으로 적재한다.

v0.2.0 안정화 (2026-04-21):
    - 전역 SSL override 제거, verify=False는 Session 범위로 한정 + 시작 경고
    - 429 / 5xx / 403(2회 한정) retry + jittered backoff + Retry-After 지원
    - detail summary selector 재배열(본문 우선) + 최소길이/숫자비중 품질 검증
    - broker 추출을 list → detail 순으로 병행, 실패 시 broker_missing warning
    - 카테고리별 key_index JSON (O(n) 전 월별 JSON 재읽기 회피)
    - warning code 상수화, dry-run 요약에 target/empty/pdf_skipped 노출

Phase 1 범위 (포함):
    - list/detail 수집, (category, nid) dedupe, 카테고리별 cursor
    - summary HTML/텍스트 추출
    - 선택적 PDF 다운로드 (실패해도 record는 유지)
    - 월별 JSON upsert, state.json + key_index/{category}.json 갱신
    - --backfill / --incremental / --category / --limit-pages / --no-pdf / --dry-run

Phase 1 제외 (명시적):
    - 분류/salience/GraphRAG 편입 (Phase 2~3)
    - PDF 파싱/OCR (Phase 5)
    - broker debate (Phase 4 이후, 기존 debate_engine 확장으로만 다룸)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

import requests
import urllib3
from bs4 import BeautifulSoup

from market_research.core.json_utils import safe_read_news_json, safe_write_news_json

# ── 환경 ──
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# TLS 검증은 Session.verify 범위로만 제어한다. 프로세스 전역 SSL 컨텍스트는 건드리지 않는다.
# verify=False일 때만 urllib3 경고를 억제한다 (명시적 경고는 시작 시 별도 출력).

KST = timezone(timedelta(hours=9))
COLLECTOR_VERSION = "0.2.0"

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "naver_research"
RAW_ROOT = DATA_ROOT / "raw"
PDF_ROOT = DATA_ROOT / "pdfs"
STATE_PATH = DATA_ROOT / "state.json"
KEY_INDEX_DIR = DATA_ROOT / "key_index"

BASE_URL = "https://finance.naver.com/research"

CATEGORIES: dict[str, dict[str, str]] = {
    "economy":     {"list": "economy_list.naver",     "read": "economy_read.naver",     "ko": "경제분석"},
    "market_info": {"list": "market_info_list.naver", "read": "market_info_read.naver", "ko": "시황정보"},
    "invest":      {"list": "invest_list.naver",      "read": "invest_read.naver",      "ko": "투자정보"},
    "industry":    {"list": "industry_list.naver",    "read": "industry_read.naver",    "ko": "산업분석"},
    "debenture":   {"list": "debenture_list.naver",   "read": "debenture_read.naver",   "ko": "채권분석"},
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

HTTP_TIMEOUT = 15.0
SLEEP_LIST = 0.3
SLEEP_DETAIL = 0.3
SLEEP_PDF = 0.5
MAX_RETRY = 3
RETRY_BASE = 1.0
RETRY_MAX_403 = 2             # 403은 retry 횟수 별도 상한
RETRY_AFTER_MAX = 60.0        # Retry-After 헤더 상한 (초)
RETRY_JITTER = 0.5            # jitter 상한

# 사내 프록시 self-signed CA 대응. 환경변수로 override. 기본은 verify=False.
TLS_VERIFY = os.environ.get("NAVER_RESEARCH_TLS_VERIFY", "0") == "1"


# ═══════════════════════════════════════════════════════
# Warning codes (자유문장 대신 코드형 문자열로 통일)
# ═══════════════════════════════════════════════════════

W_LIST_NO_TABLE              = "list_no_table"
W_LIST_ROWS_NO_ITEMS         = "list_rows_found_no_items"
W_DETAIL_NO_SUMMARY_BLOCK    = "detail_no_summary_block"
W_DETAIL_FALLBACK_USED       = "detail_selector_fallback_used"
W_SUMMARY_TOO_SHORT          = "summary_too_short"
W_SUMMARY_NUMERIC_HEAVY      = "summary_numeric_heavy"
W_SUMMARY_EMPTY              = "empty_summary"
W_BROKER_MISSING             = "broker_missing"
W_PDF_HTTP_ERROR             = "pdf_http_error"

SUMMARY_MIN_CHARS = 100        # summary로 채택할 최소 길이
SUMMARY_NUMERIC_RATIO_MAX = 0.6  # 숫자/기호 비중이 이 이상이면 summary로 채택 안 함


# ═══════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════


@dataclass
class CollectStats:
    category: str
    list_rows_seen: int = 0
    target_count: int = 0
    records_built: int = 0
    records_saved: int = 0
    summary_ok: int = 0
    summary_empty: int = 0
    pdf_declared: int = 0
    pdf_downloaded: int = 0
    pdf_failed: int = 0
    pdf_skipped: int = 0         # dry-run 또는 --no-pdf로 의도적으로 스킵한 건수
    warnings: int = 0
    warning_codes: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def bump_warnings(self, codes: Iterable[str]) -> None:
        for c in codes:
            self.warnings += 1
            self.warning_codes[c] = self.warning_codes.get(c, 0) + 1


# ═══════════════════════════════════════════════════════
# HTTP
# ═══════════════════════════════════════════════════════


def make_session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    })
    sess.verify = TLS_VERIFY
    if not TLS_VERIFY:
        # verify=False일 때만 urllib3 경고를 억제 (범위 최소화)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print(
            "[WARN] TLS certificate verification disabled (NAVER_RESEARCH_TLS_VERIFY=0). "
            "Restricted to naver_research session. Set NAVER_RESEARCH_TLS_VERIFY=1 in production.",
            flush=True,
        )
    return sess


def _url_path(url: str) -> str:
    """에러 로그용 — query string 제거한 path 부분만 추출."""
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        return f"{p.netloc}{p.path}"
    except Exception:
        return url[:80]


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After 헤더 (초 또는 HTTP date). 초만 지원, 상한 적용."""
    if not value:
        return None
    try:
        sec = float(value.strip())
        return min(max(sec, 0.0), RETRY_AFTER_MAX)
    except ValueError:
        return None  # HTTP date 형식은 현 구현에서 미지원


class _HttpStatusError(Exception):
    """retry 판정용 내부 래퍼."""
    def __init__(self, status: int, url: str, retry_after: float | None = None):
        self.status = status
        self.url = url
        self.retry_after = retry_after
        super().__init__(f"HTTP {status} for {_url_path(url)}")


class AccessBlockedError(requests.HTTPError):
    """retry 한도를 초과한 403 전용 예외 — 구조 warning과 분리해 errors에 기록한다.

    attributes:
        status: 항상 403
        url:    최종 실패한 URL
        stage:  "list" | "detail" | "pdf" | None (호출 측에서 세팅)
    """
    def __init__(self, status: int, url: str, stage: str | None = None):
        self.status = status
        self.url = url
        self.stage = stage
        super().__init__(f"HTTP {status} blocked for {_url_path(url)}")


def http_get(sess: requests.Session, url: str, *, stream: bool = False) -> requests.Response:
    """retry with jittered exponential backoff.

    대상:
      - 429 Too Many Requests (Retry-After 헤더 우선)
      - 5xx
      - 403 (최대 RETRY_MAX_403회 — bot challenge 대비 최소 방어)
      - ConnectionError / Timeout / SSLError

    최종 처리:
      - 403이 retry 한도를 소진해도 계속 blocked → ``AccessBlockedError`` 승격
        (정상 응답처럼 흘러가서 구조 warning으로 묻히지 않도록)
      - 그 외 4xx는 즉시 반환 (호출 측 판정)
      - 5xx/429는 ``requests.HTTPError``로 재포장
    """
    last_exc: Exception | None = None
    attempts_403 = 0
    for attempt in range(MAX_RETRY):
        try:
            r = sess.get(url, timeout=HTTP_TIMEOUT, stream=stream)
            status = r.status_code
            if 200 <= status < 400:
                return r
            if status == 429 or 500 <= status < 600:
                raise _HttpStatusError(status, url, _parse_retry_after(r.headers.get("Retry-After")))
            if status == 403:
                if attempts_403 < RETRY_MAX_403:
                    attempts_403 += 1
                    raise _HttpStatusError(status, url)
                # retry 한도 소진 — 정상 응답처럼 빠져나가지 말고 명시적 차단 실패로 승격
                raise AccessBlockedError(status, url)
            # 그 외 4xx는 즉시 반환 (호출 측에서 판정)
            return r
        except AccessBlockedError:
            # 재시도 금지, 즉시 상위로
            raise
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError, _HttpStatusError) as e:
            last_exc = e
            if isinstance(e, _HttpStatusError) and e.retry_after is not None:
                wait = e.retry_after + random.uniform(0, RETRY_JITTER)
            else:
                wait = RETRY_BASE * (2 ** attempt) + random.uniform(0, RETRY_JITTER)
            tag = f"HTTP {e.status}" if isinstance(e, _HttpStatusError) else type(e).__name__
            print(
                f"    [retry {attempt+1}/{MAX_RETRY}] {tag} @ {_url_path(url)} → sleep {wait:.1f}s",
                flush=True,
            )
            time.sleep(wait)
    # 최종 실패
    assert last_exc is not None
    if isinstance(last_exc, _HttpStatusError):
        raise requests.HTTPError(
            f"HTTP {last_exc.status} after {MAX_RETRY} retries for {_url_path(url)}"
        ) from last_exc
    raise last_exc


# ═══════════════════════════════════════════════════════
# Parsing helpers
# ═══════════════════════════════════════════════════════


_DATE_RAW_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})")
_NID_RE = re.compile(r"nid=(\d+)")


def normalize_date(raw: str) -> str | None:
    """'26.04.20' → '2026-04-20'. 실패 시 None."""
    m = _DATE_RAW_RE.search(raw or "")
    if not m:
        return None
    yy, mm, dd = m.groups()
    year = 2000 + int(yy)
    return f"{year:04d}-{int(mm):02d}-{int(dd):02d}"


def parse_int_safe(s: str) -> int:
    try:
        return int(s.replace(",", "").strip())
    except (AttributeError, ValueError):
        return 0


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


_BROKER_RE = re.compile(r"[가-힣A-Za-z0-9&·]+(?:증권|투자신탁|자산운용|투자증권)")


def _is_valid_broker(s: str) -> bool:
    """broker 후보가 상식적인지 검증. 숫자만/날짜/지나치게 긴 문장은 탈락."""
    if not s:
        return False
    s = s.strip()
    if len(s) == 0 or len(s) > 25:
        return False
    if re.fullmatch(r"[\d,.\s]+", s):
        return False
    if _DATE_RAW_RE.match(s):
        return False
    # "증권" / "투자" 키워드가 있어야 broker로 인정
    if "증권" not in s and "투자" not in s and "운용" not in s:
        return False
    return True


def _extract_broker_from_text(text: str) -> str:
    """임의 텍스트 블록에서 broker 후보 뽑기 (regex 기반)."""
    if not text:
        return ""
    for m in _BROKER_RE.finditer(text):
        cand = m.group(0).strip()
        if _is_valid_broker(cand):
            return cand
    return ""


def parse_list_page(html: str, category: str, page: int) -> tuple[list[dict], list[str]]:
    """list HTML → row dicts + list-level warnings."""
    soup = BeautifulSoup(html, "html.parser")
    warnings: list[str] = []
    rows = soup.select("table.type_1 tr")
    if not rows:
        warnings.append(W_LIST_NO_TABLE)
        return [], warnings

    items: list[dict] = []
    for tr in rows:
        a = tr.find("a", href=lambda h: h and f"{category}_read.naver" in h)
        if not a:
            continue
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        m = _NID_RE.search(a.get("href", ""))
        if not m:
            continue
        nid = int(m.group(1))
        title = _clean_text(a.get_text())

        # broker / date / views 추출 — td 텍스트 순회 (컬럼 순서가 카테고리별 상이)
        broker = ""
        date_raw = ""
        views = 0
        for td in tds[1:]:
            txt = _clean_text(td.get_text(" "))
            if not txt:
                continue
            if not date_raw and _DATE_RAW_RE.match(txt):
                date_raw = txt
                continue
            if not broker and _is_valid_broker(txt):
                broker = txt
                continue
            if re.fullmatch(r"[\d,]+", txt) and views == 0:
                views = parse_int_safe(txt)

        pdf_url = ""
        for link in tr.find_all("a"):
            href = link.get("href") or ""
            if ".pdf" in href.lower():
                pdf_url = href
                break

        items.append({
            "category": category,
            "nid": nid,
            "title": title,
            "broker": broker,
            "date_raw": date_raw,
            "date": normalize_date(date_raw),
            "views": views,
            "pdf_url_list": pdf_url,  # list에서 먼저 발견한 것. detail과 대조.
            "list_page": page,
        })
    if not items and rows:
        warnings.append(W_LIST_ROWS_NO_ITEMS)
    return items, warnings


# 본문 가능성이 높은 블록 순서대로 시도.
# view_cnt/view_cont 류는 네이버 현 구조상 본문을 담고 있기는 하지만
# 이름상 조회수/메타 영역과 혼동되기 쉬워 뒤로 보낸다.
_DETAIL_SUMMARY_SELECTORS = [
    "td.cont",
    "td.view_cont",
    "div.view_cont",
    "div.content",
    "#content td",
    "td.view_cnt",      # 레거시 — 실제로는 여기가 본문일 때도 있음
    ".view_cnt",
    ".bc_day",
]


def _numeric_ratio(text: str) -> float:
    """텍스트 중 숫자/기호/공백 비율. 1에 가까우면 숫자표 덩어리."""
    if not text:
        return 1.0
    total = len(text)
    numeric = sum(1 for c in text if c.isdigit() or c in ".,%()[]-+:/ \t\n")
    return numeric / total


def _accept_summary(text: str) -> tuple[bool, str | None]:
    """summary로 채택할지 여부 + 거부 사유 코드."""
    if not text:
        return False, W_SUMMARY_EMPTY
    if len(text) < SUMMARY_MIN_CHARS:
        return False, W_SUMMARY_TOO_SHORT
    if _numeric_ratio(text) > SUMMARY_NUMERIC_RATIO_MAX:
        return False, W_SUMMARY_NUMERIC_HEAVY
    if _DATE_RAW_RE.fullmatch(text.strip()):
        return False, W_SUMMARY_TOO_SHORT
    return True, None


def parse_detail_page(html: str, category: str) -> dict:
    """detail HTML → summary_html/summary_text/pdf_url/broker_detail/warnings.

    selector 우선순위로 후보 블록을 찾고, 최소 길이 / 숫자 비중 / 순수 날짜 여부로
    품질을 검증한다. primary 후보가 실패하면 longest td fallback을 시도하되,
    그 때도 같은 품질 체크를 거치며 _warnings에 fallback 사용 여부를 기록한다.
    """
    soup = BeautifulSoup(html, "html.parser")
    warnings: list[str] = []

    body = None
    used_selector: str | None = None

    for sel in _DETAIL_SUMMARY_SELECTORS:
        el = soup.select_one(sel)
        if not el:
            continue
        txt = _clean_text(el.get_text(" "))
        ok, reason = _accept_summary(txt)
        if ok:
            body = el
            used_selector = sel
            break

    if body is None:
        # fallback: 가장 긴 텍스트를 가진 <td>
        best = None
        best_txt = ""
        for td in soup.find_all("td"):
            txt = _clean_text(td.get_text(" "))
            if len(txt) > len(best_txt):
                best = td
                best_txt = txt
        ok, reason = _accept_summary(best_txt)
        if ok:
            body = best
            warnings.append(W_DETAIL_FALLBACK_USED)
        else:
            # 전부 실패 — summary 없이 진행
            warnings.append(W_DETAIL_NO_SUMMARY_BLOCK)
            if reason:
                warnings.append(reason)

    summary_html = str(body) if body else ""
    summary_text = _clean_text(body.get_text(" ")) if body else ""

    # detail page에서 broker 보조 추출 (summary 영역 제외하고, 본문 상단 메타 블록 위주)
    broker_detail = ""
    for sel in ("div.sub_tit1", "p.info", ".bd_day", "th.info", "td.info"):
        el = soup.select_one(sel)
        if el:
            cand = _extract_broker_from_text(_clean_text(el.get_text(" ")))
            if cand:
                broker_detail = cand
                break
    if not broker_detail:
        # summary 텍스트 앞부분에서만 한번 시도 (본문 중간 "OO증권"은 오인식 위험)
        head = summary_text[:120]
        broker_detail = _extract_broker_from_text(head)

    # PDF: detail 페이지 링크 우선
    pdf_url = ""
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        if ".pdf" in href.lower():
            pdf_url = href
            break

    return {
        "summary_html": summary_html,
        "summary_text": summary_text,
        "summary_selector": used_selector,
        "broker_detail": broker_detail,
        "pdf_url_detail": pdf_url,
        "_detail_warnings": warnings,
    }


# ═══════════════════════════════════════════════════════
# Record build + PDF download
# ═══════════════════════════════════════════════════════


def build_detail_url(category: str, nid: int, page: int = 1) -> str:
    read = CATEGORIES[category]["read"]
    return f"{BASE_URL}/{read}?nid={nid}&page={page}"


def build_record(list_item: dict, detail: dict) -> dict:
    """list + detail 정보를 최종 record로 합친다. PDF 다운로드는 아직 안 함.

    broker 우선순위:
      1) list page의 명시적 컬럼
      2) detail page의 보조 추출 (broker_detail)
      3) (fallback 없음 → broker_missing warning)
    """
    pdf_url = detail.get("pdf_url_detail") or list_item.get("pdf_url_list") or ""
    has_pdf = bool(pdf_url)
    warnings = list(detail.get("_detail_warnings", []))
    summary_text = detail.get("summary_text", "")
    if not summary_text and W_SUMMARY_EMPTY not in warnings:
        warnings.append(W_SUMMARY_EMPTY)

    broker_list = list_item.get("broker", "") or ""
    broker_detail = detail.get("broker_detail", "") or ""
    if _is_valid_broker(broker_list):
        broker = broker_list
    elif _is_valid_broker(broker_detail):
        broker = broker_detail
    else:
        broker = ""
        warnings.append(W_BROKER_MISSING)

    return {
        "source_type": "naver_research",
        "category": list_item["category"],
        "nid": list_item["nid"],
        "dedupe_key": f"{list_item['category']}:{list_item['nid']}",
        "title": list_item.get("title", ""),
        "broker": broker,
        "broker_source": "list" if broker == broker_list and broker else ("detail" if broker else "missing"),
        "date": list_item.get("date"),
        "date_raw": list_item.get("date_raw", ""),
        "views": list_item.get("views", 0),
        "detail_url": build_detail_url(list_item["category"], list_item["nid"]),
        "list_page": list_item.get("list_page"),
        "summary_html": detail.get("summary_html", ""),
        "summary_text": summary_text,
        "summary_char_len": len(summary_text),
        "summary_selector": detail.get("summary_selector"),
        "has_pdf": has_pdf,
        "pdf_url": pdf_url or None,
        "pdf_path": None,
        "pdf_bytes": None,
        "pdf_download_error": None,
        "collected_at": datetime.now(KST).isoformat(),
        "collector_version": COLLECTOR_VERSION,
        "_warnings": warnings,
    }


def pdf_dest(category: str, date_str: str | None, nid: int) -> Path:
    month = (date_str or "unknown")[:7] or "unknown"
    return PDF_ROOT / category / month / f"{nid}.pdf"


def download_pdf(sess: requests.Session, pdf_url: str, dest: Path) -> tuple[bool, int | None, str | None]:
    try:
        r = http_get(sess, pdf_url, stream=True)
    except Exception as e:
        return False, None, f"http:{type(e).__name__}:{e}"
    if r.status_code != 200:
        return False, None, f"http:{r.status_code}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        written = 0
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    written += len(chunk)
        if written == 0:
            dest.unlink(missing_ok=True)
            return False, None, "empty_body"
        return True, written, None
    except OSError as e:
        return False, None, f"io:{e}"


# ═══════════════════════════════════════════════════════
# Storage
# ═══════════════════════════════════════════════════════


def monthly_json_path(category: str, month: str) -> Path:
    return RAW_ROOT / category / f"{month}.json"


def key_index_path(category: str) -> Path:
    return KEY_INDEX_DIR / f"{category}.json"


def _rebuild_key_index(category: str) -> dict[str, str]:
    """월별 JSON 전수 스캔으로 index 재구축. 기존 index가 없거나 손상됐을 때만 호출."""
    mapping: dict[str, str] = {}
    cat_dir = RAW_ROOT / category
    if not cat_dir.exists():
        return mapping
    for f in sorted(cat_dir.glob("*.json")):
        month = f.stem
        articles = safe_read_news_json(f)
        for a in articles:
            key = a.get("dedupe_key") or (
                f"{a.get('category','')}:{a.get('nid','')}" if a.get("nid") else None
            )
            if key:
                mapping[key] = month
    return mapping


def load_key_index(category: str) -> dict[str, str]:
    """카테고리별 dedupe_key → month 매핑. index 파일이 없으면 1회 rebuild."""
    p = key_index_path(category)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            print(f"  [경고] {p.name} 구조 이상 (dict 아님) → rebuild", flush=True)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"  [경고] {p.name} 파싱 실패: {e} → rebuild", flush=True)
    mapping = _rebuild_key_index(category)
    save_key_index(category, mapping)
    return mapping


def save_key_index(category: str, mapping: dict[str, str]) -> None:
    p = key_index_path(category)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mapping, ensure_ascii=False, indent=0), encoding="utf-8")


def save_records(records: list[dict], category: str, index: dict[str, str]) -> dict[str, int]:
    """월별 JSON에 dedupe upsert + key index 동기 갱신.

    index는 호출 측이 load_key_index()로 얻어서 전달. 본 함수가 in-place 업데이트한 뒤
    save_key_index()를 호출해 디스크에 기록한다.
    반환: {month: 신규_append_count}.
    """
    written: dict[str, int] = {}
    by_month: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        month = (r.get("date") or "unknown")[:7] or "unknown"
        by_month[month].append(r)

    for month, recs in by_month.items():
        path = monthly_json_path(category, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = safe_read_news_json(path)
        seen = {a.get("dedupe_key") for a in existing if a.get("dedupe_key")}
        appended = 0
        for r in recs:
            if r["dedupe_key"] in seen:
                continue
            existing.append(r)
            seen.add(r["dedupe_key"])
            index[r["dedupe_key"]] = month
            appended += 1
        existing.sort(key=lambda x: (x.get("date") or "", x.get("nid") or 0))
        payload = {
            "month": month,
            "category": category,
            "total": len(existing),
            "source_type": "naver_research",
            "articles": existing,
        }
        safe_write_news_json(path, payload)
        written[month] = appended

    save_key_index(category, index)
    return written


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"  [경고] state.json 파싱 실패: {e} → 빈 state로 진행", flush=True)
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def update_state(state: dict, category: str, records: list[dict]) -> None:
    if not records:
        state.setdefault(category, {})
        state[category]["last_crawled_at"] = datetime.now(KST).isoformat()
        return
    max_nid = max(r["nid"] for r in records)
    prev = state.get(category, {}).get("last_seen_nid", 0) or 0
    state[category] = {
        "last_seen_nid": max(prev, max_nid),
        "last_crawled_at": datetime.now(KST).isoformat(),
    }


# ═══════════════════════════════════════════════════════
# Crawl flow
# ═══════════════════════════════════════════════════════


def iter_list_pages(sess: requests.Session, category: str, stop_fn, *, limit_pages: int | None) -> Iterable[tuple[int, list[dict], list[str]]]:
    """list 페이지를 1부터 순회. stop_fn(items)가 True면 중단. limit_pages 넘어가면 중단."""
    list_path = CATEGORIES[category]["list"]
    page = 1
    while True:
        if limit_pages is not None and page > limit_pages:
            return
        url = f"{BASE_URL}/{list_path}?&page={page}"
        try:
            r = http_get(sess, url)
        except AccessBlockedError as e:
            # list 단계 차단 — 상위로 승격하여 caller가 errors에 명시적 코드로 기록
            e.stage = "list"
            print(f"    [ERROR] 403 blocked @ {_url_path(url)} (stage=list, page={page})", flush=True)
            raise
        except Exception as e:
            print(f"    [ERROR] list page {page} 실패: {type(e).__name__}: {e}", flush=True)
            return
        r.encoding = "euc-kr"
        items, warnings = parse_list_page(r.text, category, page)
        yield page, items, warnings
        if not items:
            return
        if stop_fn(items):
            return
        page += 1
        time.sleep(SLEEP_LIST)


def collect_category(
    sess: requests.Session,
    category: str,
    *,
    mode: str,                       # "incremental" | "backfill"
    state: dict,
    since_date: str | None,          # backfill 전용 (YYYY-MM-DD)
    limit_pages: int | None,
    download_pdfs: bool,
    dry_run: bool,
) -> tuple[list[dict], CollectStats]:
    stats = CollectStats(category=category)
    ko = CATEGORIES[category]["ko"]
    print(f"\n=== [{ko}] ({category}) mode={mode} limit_pages={limit_pages} dry_run={dry_run} ===", flush=True)

    last_seen_nid = int(state.get(category, {}).get("last_seen_nid") or 0)
    key_index = load_key_index(category)
    print(f"  기존 수집: {len(key_index)}건 (key_index), last_seen_nid={last_seen_nid}", flush=True)

    records: list[dict] = []
    target_items: list[dict] = []

    def stop_fn(items: list[dict]) -> bool:
        if mode == "incremental":
            # page 전체 nid가 last_seen 이하면 중단
            return all((it.get("nid") or 0) <= last_seen_nid for it in items)
        if mode == "backfill" and since_date:
            return all((it.get("date") or "9999-12-31") < since_date for it in items)
        return False

    # 1단계: list 페이지 순회해서 target 선별
    list_blocked = False
    try:
        for page, items, list_warnings in iter_list_pages(sess, category, stop_fn, limit_pages=limit_pages):
            stats.list_rows_seen += len(items)
            if list_warnings:
                stats.bump_warnings(list_warnings)
                for w in list_warnings:
                    print(f"    [WARN] p{page} {w}", flush=True)
            for it in items:
                key = f"{it['category']}:{it['nid']}"
                if key in key_index:
                    continue
                if mode == "incremental" and (it.get("nid") or 0) <= last_seen_nid:
                    continue
                if mode == "backfill" and since_date and (it.get("date") or "9999") < since_date:
                    continue
                target_items.append(it)
    except AccessBlockedError as e:
        list_blocked = True
        msg = f"http_403_blocked_list: {_url_path(e.url)}"
        stats.errors.append(msg)
        print(f"    [ERROR] {msg} — list 수집 중단, 지금까지 선별한 target만 진행", flush=True)

    stats.target_count = len(target_items)
    print(f"  target: {len(target_items)}건 (list rows {stats.list_rows_seen})", flush=True)

    # 2단계: detail + PDF
    detail_blocked_hits = 0
    for i, it in enumerate(target_items, 1):
        detail_url = build_detail_url(category, it["nid"], page=it.get("list_page") or 1)
        try:
            r = http_get(sess, detail_url)
        except AccessBlockedError as e:
            e.stage = "detail"
            detail_blocked_hits += 1
            msg = f"http_403_blocked_detail: nid={it['nid']} {_url_path(e.url)}"
            stats.errors.append(msg)
            print(f"    [ERROR] 403 blocked @ {_url_path(e.url)} (stage=detail, nid={it['nid']})", flush=True)
            # 연속 차단이 누적되면 detail 루프 자체를 조기 종료 (차단 대응 최소 운영 안전판)
            if detail_blocked_hits >= 3:
                print(f"    [ERROR] detail 403 {detail_blocked_hits}회 연속 감지 — 이 카테고리 detail 루프 중단", flush=True)
                break
            time.sleep(SLEEP_DETAIL)
            continue
        except Exception as e:
            msg = f"{it['nid']}: detail http {type(e).__name__}: {e}"
            print(f"    [ERROR] {msg}", flush=True)
            stats.errors.append(msg)
            time.sleep(SLEEP_DETAIL)
            continue
        detail_blocked_hits = 0  # 정상 응답 시 연속 카운터 리셋
        r.encoding = "euc-kr"
        detail = parse_detail_page(r.text, category)
        record = build_record(it, detail)
        if record["summary_text"]:
            stats.summary_ok += 1
        else:
            stats.summary_empty += 1
        if record["has_pdf"]:
            stats.pdf_declared += 1
        if record["_warnings"]:
            stats.bump_warnings(record["_warnings"])

        # PDF 다운로드
        if record["has_pdf"]:
            if not download_pdfs:
                # --no-pdf 명시
                stats.pdf_skipped += 1
            else:
                dest = pdf_dest(category, record["date"], record["nid"])
                if dest.exists():
                    record["pdf_path"] = str(dest.relative_to(DATA_ROOT.parent.parent))
                    record["pdf_bytes"] = dest.stat().st_size
                    stats.pdf_downloaded += 1
                elif dry_run:
                    stats.pdf_skipped += 1
                else:
                    ok, nbytes, err = download_pdf(sess, record["pdf_url"], dest)
                    if ok:
                        record["pdf_path"] = str(dest.relative_to(DATA_ROOT.parent.parent))
                        record["pdf_bytes"] = nbytes
                        stats.pdf_downloaded += 1
                    else:
                        record["pdf_download_error"] = err
                        record["_warnings"].append(W_PDF_HTTP_ERROR)
                        stats.bump_warnings([W_PDF_HTTP_ERROR])
                        stats.pdf_failed += 1
                    time.sleep(SLEEP_PDF)

        records.append(record)
        stats.records_built += 1

        if i % 25 == 0 or i == len(target_items):
            print(
                f"    [{i}/{len(target_items)}] nid={record['nid']} date={record['date']} "
                f"pdf={record['pdf_path'] is not None} broker={record['broker'] or '-'}",
                flush=True,
            )

        time.sleep(SLEEP_DETAIL)

    # 3단계: 저장 + state 갱신
    if dry_run:
        print(
            f"  [dry-run] built {len(records)} records, SKIP storage & state. "
            f"summary_ok={stats.summary_ok} empty={stats.summary_empty} "
            f"pdf_declared={stats.pdf_declared} pdf_skipped={stats.pdf_skipped} "
            f"warnings={stats.warnings}",
            flush=True,
        )
        stats.records_saved = 0
    elif records:
        written = save_records(records, category, key_index)
        stats.records_saved = sum(written.values())
        print(f"  saved by month: {written}", flush=True)
        update_state(state, category, records)
    else:
        # 저장할 게 없어도 cursor는 갱신 (관측상 last_crawled_at만 필요)
        update_state(state, category, records)

    return records, stats


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════


def print_summary(stats_list: list[CollectStats], *, dry_run: bool) -> None:
    print("\n" + "=" * 78, flush=True)
    print(f"Phase 1 수집 요약{' (DRY-RUN — storage/state skipped)' if dry_run else ''}", flush=True)
    print("=" * 78, flush=True)
    hdr = (
        f"{'category':<12} {'rows':>5} {'target':>6} {'saved':>6} "
        f"{'sum_ok':>7} {'sum_empty':>9} {'pdf_decl':>8} {'pdf_ok':>7} "
        f"{'pdf_fail':>8} {'pdf_skip':>8} {'warn':>5}"
    )
    print(hdr, flush=True)
    print("-" * len(hdr), flush=True)
    totals = CollectStats(category="(total)")
    warn_accum: dict[str, int] = {}
    for s in stats_list:
        print(
            f"{s.category:<12} {s.list_rows_seen:>5} {s.target_count:>6} "
            f"{s.records_saved:>6} {s.summary_ok:>7} {s.summary_empty:>9} "
            f"{s.pdf_declared:>8} {s.pdf_downloaded:>7} {s.pdf_failed:>8} "
            f"{s.pdf_skipped:>8} {s.warnings:>5}",
            flush=True,
        )
        totals.list_rows_seen += s.list_rows_seen
        totals.target_count += s.target_count
        totals.records_saved += s.records_saved
        totals.summary_ok += s.summary_ok
        totals.summary_empty += s.summary_empty
        totals.pdf_declared += s.pdf_declared
        totals.pdf_downloaded += s.pdf_downloaded
        totals.pdf_failed += s.pdf_failed
        totals.pdf_skipped += s.pdf_skipped
        totals.warnings += s.warnings
        for k, v in s.warning_codes.items():
            warn_accum[k] = warn_accum.get(k, 0) + v
    print("-" * len(hdr), flush=True)
    print(
        f"{totals.category:<12} {totals.list_rows_seen:>5} {totals.target_count:>6} "
        f"{totals.records_saved:>6} {totals.summary_ok:>7} {totals.summary_empty:>9} "
        f"{totals.pdf_declared:>8} {totals.pdf_downloaded:>7} {totals.pdf_failed:>8} "
        f"{totals.pdf_skipped:>8} {totals.warnings:>5}",
        flush=True,
    )
    if totals.pdf_declared:
        pct = 100.0 * totals.pdf_downloaded / totals.pdf_declared
        print(f"\nPDF download rate: {totals.pdf_downloaded}/{totals.pdf_declared} ({pct:.1f}%)", flush=True)
    if warn_accum:
        print("\nwarning codes:", flush=True)
        for k, v in sorted(warn_accum.items(), key=lambda kv: -kv[1]):
            print(f"  {k}: {v}", flush=True)
    errs = [e for s in stats_list for e in s.errors]
    if errs:
        print(f"\nerrors ({len(errs)}):", flush=True)
        for e in errs[:10]:
            print(f"  - {e}", flush=True)
        if len(errs) > 10:
            print(f"  ...({len(errs)-10} more)", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m market_research.collect.naver_research",
        description="Naver Finance Research collector (Phase 1)",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--incremental", action="store_true", help="state.json 기반 증분 수집")
    g.add_argument("--backfill", metavar="YYYY-MM-DD", help="해당 날짜 이후 전수 스캔 (state 무시)")

    p.add_argument("--category", action="append", choices=list(CATEGORIES.keys()),
                   help="특정 카테고리만 실행 (여러 번 지정 가능)")
    p.add_argument("--limit-pages", type=int, default=None, help="카테고리별 list 페이지 상한 (smoke test용)")
    p.add_argument("--no-pdf", action="store_true", help="PDF 다운로드 스킵 (summary/metadata만)")
    p.add_argument("--dry-run", action="store_true", help="HTTP 호출은 하되 파일 저장 생략")

    args = p.parse_args(argv)
    cats = args.category or list(CATEGORIES.keys())

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    PDF_ROOT.mkdir(parents=True, exist_ok=True)
    KEY_INDEX_DIR.mkdir(parents=True, exist_ok=True)

    state = load_state()
    sess = make_session()

    stats_list: list[CollectStats] = []
    all_records: list[dict] = []
    t0 = time.time()
    for cat in cats:
        try:
            records, stats = collect_category(
                sess, cat,
                mode=("backfill" if args.backfill else "incremental"),
                state=state,
                since_date=args.backfill,
                limit_pages=args.limit_pages,
                download_pdfs=not args.no_pdf,
                dry_run=args.dry_run,
            )
            stats_list.append(stats)
            all_records.extend(records)
        except Exception as e:
            # 카테고리 단위 예외 격리
            print(f"\n[FATAL] category={cat} 처리 중 예외: {type(e).__name__}: {e}", flush=True)
            stats_list.append(CollectStats(category=cat, errors=[f"fatal:{type(e).__name__}:{e}"]))
            continue

    if not args.dry_run:
        save_state(state)

    print_summary(stats_list, dry_run=args.dry_run)
    print(f"\n총 소요: {time.time()-t0:.1f}s, records={len(all_records)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
