# -*- coding: utf-8 -*-
"""Outlook 리포트 메일 → research-claim 입력 정규화 (broker_mail 레인).

사용자 결정 (2026-07-09):
- Outlook PST '업무\\리포트' 폴더의 증권사 리서치 메일(외사 리포트 전달 포함)을 수집.
- 신문기사 모음/보도자료(news 성격 — ⛔ news 미사용 정책) + 세미나/초청/안내류는 제외.
- naver_research 와 동일 내용(공개 리포트 중복)은 제목 유사도로 제외.
- consensus vote 는 research 동급 (source_type='broker_mail' ≠ 'monygeek' → aggregator
  가 자동으로 broker vote 에 포함, research_aggregator 무변경).

구조 (monygeek_research_adapter 패턴 미러):
- fetch: Outlook COM(GetActiveObject — Outlook 실행 중일 때만) → 화이트리스트/제외 필터
- dedupe: 같은 달 naver_research adapted 제목과 정규화 유사도 매칭 → drop
- persist: data/broker_mail/{YYYY-MM}.json — _article_id 기준 merge-on-save
  (메일이 나중에 이동/삭제돼도 수집 이력 보존)
- load_broker_mail(month): research_claim_extractor 진입점 (COM 비의존 — 파일만 읽음)
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BROKER_MAIL_DIR = BASE_DIR / 'data' / 'broker_mail'

# ── Outlook 위치 ──
PST_STORE_HINT = 'PC 저장'          # store DisplayName 부분매칭
FOLDER_PATH = ('업무', '리포트')

# ── 발신 화이트리스트 (2026-07-09 폴더 실측 기반, 사용자 확정 범위) ──
# SMTP 도메인 → 브로커 표기. kim.co.kr(신문기사 모음=news)은 의도적으로 미포함.
DOMAIN_BROKER = {
    'kiwoom.com': '키움증권',
    'koreainvestment.com': '한국투자증권',
    'dbsec.co.kr': 'DB금융투자',
    'nhsec.com': 'NH증권',
}
# 사내 Exchange(EX) 발신자 fallback — 표시명 기준. ExchangeUser 조회(_sender_domain)가
# 실패할 때만 쓰인다. 정상 조회되면 위 DOMAIN_BROKER 로 매핑됨.
INTERNAL_SENDER_BROKER = {
    '김태훈': '한국투자증권',
}
# 제목 제외 키워드 — 신문기사/보도자료(news 정책) + 세미나/안내/운영성 메일
EXCLUDE_SUBJECT_KW = (
    '신문기사', '보도자료', '세미나', '초청', '포럼', '설명회',
    '컴플라이언스', '주문 참고',
)

BODY_STORE_CLIP = 3000   # 저장 본문 상한 (프롬프트는 desc 800자만 사용)
NAVER_DUP_RATIO = 0.85   # 제목 유사도 임계
_MIN_CONTAIN_LEN = 8     # containment 매칭 최소 정규화 길이

# ── 첨부 파싱 (커버노트형 발신자, 2026-07-27) ──
# A/B 실측: 본문이 인사말·서명뿐이고 내용 100%가 첨부에만 있는 '커버노트형' 발신자만
# 첨부를 읽는다. 나머지(김태훈·홍석민·DB증권·유민제 등)는 본문에 요약이 실려 있어
# 파싱 불필요 — 발신인 기준이라 본문 길이가 그날그날 흔들려도 판정이 안 바뀐다.
# description 은 첨부 본문으로 **대체**한다 (prompt 가 desc 앞 800자만 쓰므로 뒤에
# 덧붙이면 창 밖으로 밀려 무의미). 원본 본문은 _raw_body 로 보존.
# sender → (broker, mode).
#   mode='replace' : 커버노트형 — 본문은 인사말뿐이라 첨부 본문으로 대체(_raw_body 보존)
#   mode='split'   : 본문과 첨부가 **서로 다른 내용** → 별도 evidence 2건으로 분리 발행.
#                    (이어붙이면 prompt 창이 본문 안에서 끝나 첨부가 LLM 에 안 닿는다 —
#                     홍석민 실측: 첨부 시작이 desc 5,318자 지점, 창은 3,000자.)
ATTACH_PARSE_SENDERS = {
    '신성준': ('키움증권', 'replace'),      # 외사 리포트(MS/BofA/UBS) 전달 — 본문 190~400자 인사말
    '이정민': ('한국투자증권', 'replace'),   # 주간회의자료_매크로.docx(DRM) — 본문 531자 전부 서명
    '홍석민': ('키움증권', 'split'),        # 본문=글로벌 시황 / 첨부=당사 리포트 (별개 내용)
}
# claim 추출 prompt 가 evidence 당 읽는 desc 창(자). 미지정이면 extractor 기본값(800).
DESC_WINDOW_WIDE = 3000

# ── 본문 링크 리포트 (2026-07-27) ──
# 키움 메일 본문 하단의 bbn.kiwoom.com/rfXXXX 는 인증 없이 application/pdf 를 직접
# 반환하는 **당사 리포트** — 첨부(외사 리포트)와 내용이 겹치지 않는다. 링크 1개 =
# 리포트 1편이라 evidence 도 링크별로 분리 발행한다.
# (DB증권 whub 는 StreamDocs 뷰어라 파일을 못 받고, 한투/NH 링크는 로고·차트 이미지,
#  UBS/MS 는 면책조항 URL — 전부 대상 외.)
LINK_REPORT_PAT = re.compile(r'https?://bbn\.kiwoom\.com/[A-Za-z0-9]+')
LINK_PARSE_SENDERS = {'홍석민', '신성준'}
LINK_MAX_PER_MAIL = 8
LINK_TIMEOUT_SEC = 25
LINK_PDF_MAX_PAGES = 10
# 상한 없이 전문 저장할 발신자 — 본문 clip·첨부 clip·페이지수·파일수 제한 전부 해제.
ATTACH_NO_CLIP_SENDERS = {'홍석민'}
ATTACH_MAX_FILES = 3          # 메일당 파싱 첨부 상한
ATTACH_PDF_MAX_PAGES = 10     # PDF 앞 N 페이지만
ATTACH_TEXT_CLIP = 6000       # 저장 첨부 본문 상한
ATTACH_EXTS = ('.pdf', '.docx')


def _article_id(source: str, date: str, title: str) -> str:
    """title+date+source MD5 12 hex (core.dedupe / monygeek adapter 컨벤션 동일)."""
    key = f"{title}|{date}|{source}".encode('utf-8')
    return hashlib.md5(key).hexdigest()[:12]


# ══════════════════════════════════════════════════════════════════════════════
# 필터 / 정규화 (순수 함수 — 테스트 대상)
# ══════════════════════════════════════════════════════════════════════════════

def resolve_broker(sender_domain: str, sender_name: str) -> str | None:
    """화이트리스트 매칭 → 브로커 표기. 비대상이면 None."""
    d = (sender_domain or '').strip().lower()
    if d in DOMAIN_BROKER:
        return DOMAIN_BROKER[d]
    n = (sender_name or '').strip()
    return INTERNAL_SENDER_BROKER.get(n)


def should_collect(sender_domain: str, sender_name: str, subject: str) -> bool:
    """수집 대상 판정 — 화이트리스트 발신 + 제외 키워드 미포함."""
    if resolve_broker(sender_domain, sender_name) is None:
        return False
    s = subject or ''
    return not any(kw in s for kw in EXCLUDE_SUBJECT_KW)


_BRACKET_PAT = re.compile(r'\[[^\]]*\]')
_DATE_PAT = re.compile(r'[\(\s]*20\d{2}[.\-/년\s]*\d{1,2}[.\-/월\s]*\d{1,2}[일.\)\s]*')
_AUTHOR_PREFIX_PAT = re.compile(r'^[A-Za-z가-힣]+증권[_\s]*[가-힣]{2,4}[_\s]+')
_NON_ALNUM_PAT = re.compile(r'[^0-9a-z가-힣]+')


def norm_title(title: str) -> str:
    """제목 정규화 — 브래킷 프리픽스/작성자 프리픽스/날짜/기호 제거 후 소문자 연결.

    예) '[Econ Guide] JPY 저평가 개선에 무게' ≒ naver 'JPY 저평가 개선에 무게'
        'DB증권_강현기_GPU렌탈,토큰사용(2026.07.06)' → 'gpu렌탈토큰사용'
    """
    s = (title or '').strip()
    s = _BRACKET_PAT.sub(' ', s)
    s = _AUTHOR_PREFIX_PAT.sub(' ', s)
    s = _DATE_PAT.sub(' ', s)
    return _NON_ALNUM_PAT.sub('', s.lower())


def is_dup_title(mail_title: str, naver_norm_titles: list[str]) -> bool:
    """naver_research 제목과 동일 내용 판정 — containment 또는 ratio ≥ 0.85."""
    m = norm_title(mail_title)
    if len(m) < _MIN_CONTAIN_LEN:
        return False
    for n in naver_norm_titles:
        if len(n) < _MIN_CONTAIN_LEN:
            continue
        if m in n or n in m:
            return True
        # 길이 프리필터 (ratio 상한 = 2*min/(len합) — 임계 미달이면 스킵)
        if 2.0 * min(len(m), len(n)) / (len(m) + len(n)) < NAVER_DUP_RATIO:
            continue
        if SequenceMatcher(None, m, n).ratio() >= NAVER_DUP_RATIO:
            return True
    return False


_GREETING_KW = ('안녕하', '보내드립니다', '송부드립니다', '전달드립니다', '인사드립니다')
_DISCLAIMER_KW = (
    '본 메일은', '본 이메일은', '수신거부', 'unsubscribe', 'compliance notice',
    '금융투자분석사', '무단 전재', '무단전재', '고객상담센터',
)


def clean_body(body: str, clip: int | None = BODY_STORE_CLIP) -> str:
    """메일 본문 정리 — 프롬프트가 desc 앞부분만 쓰므로 인사말/서명을 걷어낸다.

    1) 앞쪽 인사말 줄(첫 5줄 내 짧은 greeting) 제거
    2) disclaimer 마커 이후 절단
    3) 공백 정리 + 저장 상한 clip
    """
    lines = [ln.strip() for ln in (body or '').replace('\r\n', '\n').split('\n')]
    # 1) 앞쪽 greeting 줄 스킵
    start = 0
    for i, ln in enumerate(lines[:5]):
        if ln and len(ln) < 90 and any(kw in ln for kw in _GREETING_KW):
            start = i + 1
    text = '\n'.join(lines[start:])
    # 2) disclaimer 이후 절단 (가장 이른 마커)
    low = text.lower()
    cut = len(text)
    for kw in _DISCLAIMER_KW:
        idx = low.find(kw.lower())
        if idx > 0:
            cut = min(cut, idx)
    text = text[:cut]
    # 3) 공백 정리
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text if clip is None else text[:clip]


# ══════════════════════════════════════════════════════════════════════════════
# Outlook COM fetch
# ══════════════════════════════════════════════════════════════════════════════

def _open_report_folder():
    """실행 중인 Outlook 에 attach → PST 업무\\리포트 폴더 반환. 미실행이면 raise."""
    import win32com.client
    try:
        app = win32com.client.GetActiveObject('Outlook.Application')
    except Exception as exc:
        raise RuntimeError(f'Outlook 미실행 (GetActiveObject 실패): {exc}') from exc
    ns = app.GetNamespace('MAPI')
    store = None
    for s in ns.Stores:
        if PST_STORE_HINT in (s.DisplayName or ''):
            store = s
            break
    if store is None:
        raise RuntimeError(f'PST store 미발견 (hint={PST_STORE_HINT!r})')
    folder = store.GetRootFolder()
    for name in FOLDER_PATH:
        folder = folder.Folders.Item(name)
    return folder


def attach_parse_mode(sender_name: str, broker: str) -> str | None:
    """첨부 파싱 대상 발신자면 mode('replace'|'append'), 아니면 None."""
    cfg = ATTACH_PARSE_SENDERS.get((sender_name or '').strip())
    if not cfg or cfg[0] != broker:
        return None
    return cfg[1]


def _squeeze_extracted(text: str) -> str:
    """추출 텍스트 압축 — 빈 줄/중복 공백 제거.

    Word Content.Text 는 이미지·표 자리마다 빈 문단을 뱉고, 표 셀/행 끝을 제어문자
    \\x07 로 표시한다(공백이 아니라 strip 으로 안 지워짐). prompt 는 desc 앞 800자만
    보므로 이걸 걷어내야 실제 내용이 창 안에 들어온다.
    """
    s = (text or '').replace('\r', '\n')
    s = re.sub(r'[\x0b\x0c]', '\n', s)               # vertical tab / page break → 개행
    s = re.sub(r'[\x00-\x08\x0e-\x1f\x7f]', ' ', s)  # 표 셀 마커(\x07) 등 제어문자 제거
    lines = [re.sub(r'[ \t ]+', ' ', ln).strip()
             for ln in s.split('\n')]
    return '\n'.join(ln for ln in lines if ln)


def _pdf_text(fp: Path, max_pages: int | None = ATTACH_PDF_MAX_PAGES) -> str:
    """PDF 텍스트 (max_pages=None 이면 전 페이지). 실패 시 ''."""
    try:
        import pdfplumber
    except ImportError:
        return ''
    try:
        with pdfplumber.open(str(fp)) as pdf:
            parts = []
            for pg in (pdf.pages if max_pages is None else pdf.pages[:max_pages]):
                try:
                    parts.append(pg.extract_text() or '')
                except Exception:
                    pass
        return '\n'.join(parts).strip()
    except Exception:
        return ''


def _docx_text(fp: Path, word_state: dict) -> str:
    """docx 텍스트. 사내 생성 docx 는 DRM 래핑(`<DOCUMENT SAFER`)이라 zip 파서가
    실패하므로 Word COM 으로 연다(문서보안 에이전트가 투명 복호화). 실패 시 ''.

    word_state 로 Word 인스턴스를 fetch 1회 동안 재사용 — 파일마다 띄우면 느리다.
    """
    try:
        import win32com.client
    except ImportError:
        return ''
    try:
        app = word_state.get('app')
        if app is None:
            app = win32com.client.Dispatch('Word.Application')
            app.Visible = False
            app.DisplayAlerts = False
            word_state['app'] = app
        doc = app.Documents.Open(str(fp), ReadOnly=True)
        try:
            return (doc.Content.Text or '').replace('\r', '\n').strip()
        finally:
            doc.Close(False)
    except Exception:
        return ''


def _parse_attachments(mail, tmpdir: Path, word_state: dict,
                       *, no_clip: bool = False) -> tuple[str, list[str]]:
    """첨부 본문 추출 → (text, parsed_filenames).

    no_clip=True 면 파일수·페이지수·길이 상한 없이 전문을 담는다(ATTACH_NO_CLIP_SENDERS).
    개별 첨부 실패는 skip (COM/파서 오류가 수집 전체를 막지 않게).
    """
    max_files = None if no_clip else ATTACH_MAX_FILES
    max_pages = None if no_clip else ATTACH_PDF_MAX_PAGES
    texts, names = [], []
    for a in mail.Attachments:
        if max_files is not None and len(names) >= max_files:
            break
        fn = str(a.FileName or '')
        low = fn.lower()
        if not low.endswith(ATTACH_EXTS):
            continue
        safe = re.sub(r'[^0-9A-Za-z가-힣._-]+', '_', fn)[:80]
        fp = tmpdir / safe
        try:
            a.SaveAsFile(str(fp))
        except Exception:
            continue
        text = _squeeze_extracted(
            _pdf_text(fp, max_pages) if low.endswith('.pdf')
            else _docx_text(fp, word_state))
        try:
            fp.unlink()
        except Exception:
            pass
        if not text:
            continue
        texts.append(f'[{fn}]\n{text}')
        names.append(fn)
    joined = '\n\n'.join(texts).strip()
    return (joined if no_clip else joined[:ATTACH_TEXT_CLIP]), names


def _fetch_link_reports(body: str, tmpdir: Path,
                        session=None) -> list[tuple[str, str]]:
    """본문 링크 리포트 PDF 다운로드 → [(url, text), ...]. 실패 링크는 skip.

    사내망 SSL 인스펙션 때문에 인증서 검증은 끈다(내부망 전용 도구).
    """
    urls = list(dict.fromkeys(LINK_REPORT_PAT.findall(body or '')))[:LINK_MAX_PER_MAIL]
    if not urls:
        return []
    try:
        import requests
        import urllib3
        urllib3.disable_warnings()
    except ImportError:
        return []
    s = session
    if s is None:
        s = requests.Session()
        s.headers['User-Agent'] = 'Mozilla/5.0'
        s.verify = False
    out: list[tuple[str, str]] = []
    for u in urls:
        try:
            r = s.get(u, timeout=LINK_TIMEOUT_SEC)
            if r.status_code != 200 or r.content[:5] != b'%PDF-':
                continue
            fp = tmpdir / f'link_{u.rsplit("/", 1)[-1]}.pdf'
            fp.write_bytes(r.content)
            text = _squeeze_extracted(_pdf_text(fp, LINK_PDF_MAX_PAGES))
            try:
                fp.unlink()
            except Exception:
                pass
            if text:
                out.append((u, text))
        except Exception:
            continue  # 네트워크/파싱 실패는 skip — 수집 전체를 막지 않는다
    return out


def _sender_domain(mail) -> str:
    """발신 SMTP 도메인 (소문자). 없으면 ''.

    사내 Exchange 발신자는 SenderEmailType='EX' 라 SenderEmailAddress 가 X500 DN
    (`/O=.../CN=RECIPIENTS/CN=...`) — 도메인을 못 얻는다. 이 경우 ExchangeUser 를
    조회해 실제 SMTP 를 얻어 DOMAIN_BROKER 매핑을 그대로 태운다.
    (2026-07-27: EX 발신 리서치 메일이 통째로 누락되던 문제 수정.)
    """
    etype = str(getattr(mail, 'SenderEmailType', '') or '')
    addr = str(getattr(mail, 'SenderEmailAddress', '') or '')
    if etype == 'SMTP':
        return addr.rsplit('@', 1)[-1].lower()
    try:
        smtp = str(mail.Sender.GetExchangeUser().PrimarySmtpAddress or '')
        if '@' in smtp:
            return smtp.rsplit('@', 1)[-1].lower()
    except Exception:
        pass
    return ''


def _known_article_ids(days_back: int) -> set[str]:
    """수집창에 걸치는 월들의 이미 저장된 _article_id 집합."""
    out: set[str] = set()
    cur = datetime.now()
    start = cur - timedelta(days=days_back)
    y, m = start.year, start.month
    while (y, m) <= (cur.year, cur.month):
        for a in load_broker_mail(f'{y:04d}-{m:02d}'):
            if a.get('_article_id'):
                out.add(a['_article_id'])
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def fetch_outlook_reports(days_back: int = 35, *, refresh: bool = False) -> list[dict]:
    """업무\\리포트 폴더에서 최근 days_back 일 메일 → article-like dict 리스트.

    화이트리스트/제외키워드 필터 적용. naver dedupe 는 여기서 하지 않음
    (run_fetch_and_save 에서 월별로 수행 — 필터 순서 명확화).

    ★ 이미 저장된 메일은 **첨부/링크 파싱 전에** 건너뛴다. _article_id 는
    (broker, date, subject) 로 파싱 없이 계산되므로 조기 판정이 가능하다.
    이전에는 저장분 dedupe 가 save_broker_mail 에서만 일어나 매 실행마다 창 안의
    PDF 를 전부 다시 내려받아 파싱했다(수집창을 넓히기 어려웠던 실제 이유).
    refresh=True 면 기존 건도 다시 파싱(모드 변경 반영·손상 복구용).
    """
    import shutil
    import tempfile

    known = set() if refresh else _known_article_ids(days_back)
    skipped_known = 0

    folder = _open_report_folder()
    cut = (datetime.now() - timedelta(days=days_back)).strftime('%m/%d/%Y %H:%M')
    items = folder.Items.Restrict(f"[ReceivedTime] >= '{cut}'")
    out: list[dict] = []
    tmpdir = Path(tempfile.mkdtemp(prefix='broker_mail_att_'))
    word_state: dict = {}
    link_session = None
    try:
        import requests
        import urllib3
        urllib3.disable_warnings()
        link_session = requests.Session()
        link_session.headers['User-Agent'] = 'Mozilla/5.0'
        link_session.verify = False
    except ImportError:
        pass
    try:
        for m in items:
            try:
                if getattr(m, 'Class', None) != 43:  # olMail
                    continue
                sender_name = str(m.SenderName or '')
                domain = _sender_domain(m)
                subject = str(m.Subject or '').strip()
                if not should_collect(domain, sender_name, subject):
                    continue
                broker = resolve_broker(domain, sender_name) or ''
                received = m.ReceivedTime
                date = f'{received.year:04d}-{received.month:02d}-{received.day:02d}'
                # ★ 파싱 전 조기 dedupe — 첨부/링크 다운로드를 아예 하지 않는다
                if _article_id(broker, date, subject) in known:
                    skipped_known += 1
                    continue
                no_clip = sender_name.strip() in ATTACH_NO_CLIP_SENDERS
                body = clean_body(str(m.Body or ''), clip=None if no_clip else BODY_STORE_CLIP)
                attach_names = []
                for a in m.Attachments:
                    fn = str(a.FileName or '')
                    if fn.lower().endswith(('.pdf', '.xlsx', '.docx', '.pptx')):
                        attach_names.append(fn)
                flags = []
                if len(body) < 80:
                    flags.append('short_body')
                # 첨부 파싱 대상 발신자 → mode 에 따라 대체 / 별도 evidence 분리
                desc = body
                attach_text, parsed = '', []
                mode = attach_parse_mode(sender_name, broker) if attach_names else None
                if mode:
                    attach_text, parsed = _parse_attachments(
                        m, tmpdir, word_state, no_clip=no_clip)
                    if attach_text:
                        if mode == 'replace':
                            desc = attach_text
                        flags.append('attach_parsed' if mode == 'replace'
                                     else 'attach_split')
                    else:
                        flags.append('attach_parse_failed')

                def _rec(title, description, aid_key, rec_flags, *,
                         attach_files=(), raw_body=''):
                    return {
                        # 뉴스 article 스키마 호환 (naver/monygeek adapter 동일)
                        'title': title,
                        'date': date,
                        'source': broker,
                        'url': '',
                        'description': description,
                        'source_type': 'broker_mail',
                        '_article_id': _article_id(broker, date, aid_key),
                        # raw 보존
                        '_raw_entry_id': str(m.EntryID or ''),
                        '_raw_sender': sender_name,
                        '_raw_sender_domain': domain,
                        '_raw_received': str(received),
                        '_raw_attach_names': attach_names,
                        '_raw_broker': broker,
                        '_raw_body': raw_body,
                        '_attach_parsed_files': list(attach_files),
                        '_adapter_flags': rec_flags,
                        # claim prompt 창 — 첨부/링크 원문·시황 본문은 800자로는 잘린다
                        '_desc_window': (
                            DESC_WINDOW_WIDE
                            if (mode or {'attach_parsed', 'link_report'} & set(rec_flags))
                            else None),
                    }

                if mode == 'split' and attach_text:
                    # 본문(시황)과 첨부(리포트)는 별개 내용 → evidence 2건으로 분리.
                    # 합치면 prompt 창이 본문에서 끝나 첨부가 LLM 에 닿지 못한다.
                    out.append(_rec(subject, body, subject, flags))
                    out.append(_rec(
                        f'{subject} [첨부] {parsed[0] if parsed else ""}'.strip(),
                        attach_text, f'{subject}#attach',
                        flags + ['attach_parsed', 'attach_record'],
                        attach_files=parsed))
                else:
                    out.append(_rec(
                        subject, desc, subject, flags, attach_files=parsed,
                        raw_body=body if (attach_text and mode == 'replace') else ''))

                # 본문 링크 리포트 — 링크 1개 = 리포트 1편, 첨부와 별개 내용
                if sender_name.strip() in LINK_PARSE_SENDERS:
                    # 링크 레코드는 첨부와 무관 — 첨부 관련 flag 는 물려주지 않는다
                    base_flags = [f for f in flags if not f.startswith('attach')]
                    for url, ltext in _fetch_link_reports(
                            str(m.Body or ''), tmpdir, link_session):
                        head = ltext[:40].replace('\n', ' ').strip()
                        out.append(_rec(
                            f'{subject} [링크] {head}', ltext, f'{subject}#link:{url}',
                            base_flags + ['link_report'], attach_files=[url]))
            except Exception:
                continue  # 개별 메일 실패는 skip (COM 간헐 오류 방어)
    finally:
        app = word_state.get('app')
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        shutil.rmtree(tmpdir, ignore_errors=True)
    if skipped_known:
        print(f'  [outlook] 기존 저장분 {skipped_known}건 파싱 skip '
              f'(신규 {len(out)}건만 처리)')
    return out


# ══════════════════════════════════════════════════════════════════════════════
# naver_research dedupe + 저장/로딩
# ══════════════════════════════════════════════════════════════════════════════

def _naver_norm_titles(month: str) -> list[str]:
    """같은 달 naver_research adapted 제목 정규화 리스트 (dedupe 기준)."""
    try:
        from market_research.collect.naver_research_adapter import load_adapted
        arts = load_adapted(month) or []
    except Exception:
        return []
    return [norm_title(a.get('title') or '') for a in arts]


def broker_mail_path(month: str) -> Path:
    return BROKER_MAIL_DIR / f'{month}.json'


def load_broker_mail(month: str) -> list[dict]:
    """월별 broker_mail 파일 로드 (research_claim_extractor 진입점). 없으면 []."""
    p = broker_mail_path(month)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return []
    return data.get('articles', [])


def save_broker_mail(month: str, articles: list[dict]) -> tuple[Path, int]:
    """merge-on-save: 기존 파일과 _article_id union (신규만 append). → (path, n_new).

    예외로 **첨부 파싱 대상 발신자(ATTACH_PARSE_SENDERS)** 의 기존 레코드는 재수집분으로
    동기화한다 — 파싱 도입/모드 변경 전에 저장된 본문(인사말·합본)을 갱신하기 위함.
    그 외 발신자는 기존 값을 보존(재수집으로 인한 무의미한 변경 방지).
    """
    BROKER_MAIL_DIR.mkdir(parents=True, exist_ok=True)
    p = broker_mail_path(month)
    existing = load_broker_mail(month)
    incoming = {a['_article_id']: a for a in articles if a.get('_article_id')}
    for old in existing:
        cur = incoming.get(old.get('_article_id'))
        if cur is None:
            continue
        if (old.get('_raw_sender') or '').strip() not in ATTACH_PARSE_SENDERS:
            continue
        for k in ('description', '_raw_body', '_attach_parsed_files',
                  '_adapter_flags', '_desc_window', 'title'):
            old[k] = cur.get(k)
    seen = {a.get('_article_id') for a in existing if a.get('_article_id')}
    new = [a for a in articles if a.get('_article_id') and a['_article_id'] not in seen]
    merged = existing + new
    payload = {
        'month': month,
        'source_type': 'broker_mail',
        'total': len(merged),
        'articles': merged,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return p, len(new)


def run_fetch_and_save(days_back: int = 35, dry_run: bool = False,
                       refresh: bool = False) -> dict:
    """fetch → 월별 그룹 → naver dedupe → merge 저장. 반환: 통계 dict.

    refresh=False(기본): 이미 저장된 메일은 첨부/링크 파싱을 건너뛴다 →
      수집창(days_back)을 넓혀도 일일 비용이 늘지 않는다.
    """
    fetched = fetch_outlook_reports(days_back, refresh=refresh)
    by_month: dict[str, list[dict]] = {}
    for a in fetched:
        by_month.setdefault(a['date'][:7], []).append(a)
    stats = {'fetched': len(fetched), 'months': {}, 'dry_run': dry_run}
    for month in sorted(by_month):
        arts = by_month[month]
        naver_norms = _naver_norm_titles(month)
        kept, dup = [], 0
        for a in arts:
            if is_dup_title(a['title'], naver_norms):
                dup += 1
                continue
            kept.append(a)
        n_new = 0
        if not dry_run:
            _, n_new = save_broker_mail(month, kept)
        stats['months'][month] = {'in': len(arts), 'naver_dup': dup,
                                  'kept': len(kept), 'new_saved': n_new}
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Outlook 리포트 메일 adapter (broker_mail 레인)')
    ap.add_argument('--days-back', type=int, default=35)
    ap.add_argument('--dry-run', action='store_true', help='파일 저장 생략, 통계만')
    ap.add_argument('--refresh', action='store_true',
                    help='기존 저장분도 첨부/링크 재파싱 (모드 변경 반영용)')
    args = ap.parse_args()
    stats = run_fetch_and_save(days_back=args.days_back, dry_run=args.dry_run,
                               refresh=args.refresh)
    print(f"[outlook_report_adapter] fetched={stats['fetched']} (days_back={args.days_back})")
    for month, s in stats['months'].items():
        print(f"  {month}: in={s['in']} naver_dup={s['naver_dup']} "
              f"kept={s['kept']} new_saved={s['new_saved']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
