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
# 사내 Exchange(EX) 발신자 — 표시명 기준 (한투증권 세일즈의 외사 리포트 전달)
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


def clean_body(body: str) -> str:
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
    return text[:BODY_STORE_CLIP]


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


def fetch_outlook_reports(days_back: int = 35) -> list[dict]:
    """업무\\리포트 폴더에서 최근 days_back 일 메일 → article-like dict 리스트.

    화이트리스트/제외키워드 필터 적용. naver dedupe 는 여기서 하지 않음
    (run_fetch_and_save 에서 월별로 수행 — 필터 순서 명확화).
    """
    folder = _open_report_folder()
    cut = (datetime.now() - timedelta(days=days_back)).strftime('%m/%d/%Y %H:%M')
    items = folder.Items.Restrict(f"[ReceivedTime] >= '{cut}'")
    out: list[dict] = []
    for m in items:
        try:
            if getattr(m, 'Class', None) != 43:  # olMail
                continue
            sender_name = str(m.SenderName or '')
            domain = ''
            if str(getattr(m, 'SenderEmailType', '')) == 'SMTP':
                domain = str(m.SenderEmailAddress or '').rsplit('@', 1)[-1]
            subject = str(m.Subject or '').strip()
            if not should_collect(domain, sender_name, subject):
                continue
            broker = resolve_broker(domain, sender_name) or ''
            received = m.ReceivedTime
            date = f'{received.year:04d}-{received.month:02d}-{received.day:02d}'
            body = clean_body(str(m.Body or ''))
            attach_names = []
            for a in m.Attachments:
                fn = str(a.FileName or '')
                if fn.lower().endswith(('.pdf', '.xlsx', '.docx', '.pptx')):
                    attach_names.append(fn)
            flags = []
            if len(body) < 80:
                flags.append('short_body')
            out.append({
                # 뉴스 article 스키마 호환 (naver/monygeek adapter 동일)
                'title': subject,
                'date': date,
                'source': broker,
                'url': '',
                'description': body,
                'source_type': 'broker_mail',
                '_article_id': _article_id(broker, date, subject),
                # raw 보존
                '_raw_entry_id': str(m.EntryID or ''),
                '_raw_sender': sender_name,
                '_raw_sender_domain': domain,
                '_raw_received': str(received),
                '_raw_attach_names': attach_names,
                '_raw_broker': broker,
                '_adapter_flags': flags,
            })
        except Exception:
            continue  # 개별 메일 실패는 skip (COM 간헐 오류 방어)
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
    """merge-on-save: 기존 파일과 _article_id union (신규만 append). → (path, n_new)."""
    BROKER_MAIL_DIR.mkdir(parents=True, exist_ok=True)
    p = broker_mail_path(month)
    existing = load_broker_mail(month)
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


def run_fetch_and_save(days_back: int = 35, dry_run: bool = False) -> dict:
    """fetch → 월별 그룹 → naver dedupe → merge 저장. 반환: 통계 dict."""
    fetched = fetch_outlook_reports(days_back)
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
    args = ap.parse_args()
    stats = run_fetch_and_save(days_back=args.days_back, dry_run=args.dry_run)
    print(f"[outlook_report_adapter] fetched={stats['fetched']} (days_back={args.days_back})")
    for month, s in stats['months'].items():
        print(f"  {month}: in={s['in']} naver_dup={s['naver_dup']} "
              f"kept={s['kept']} new_saved={s['new_saved']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
