# -*- coding: utf-8 -*-
"""발송 운용보고 취합기 — Outlook 발신 메일 → data/sent_reports/{fund}/{period}/.

사용자 확정 매핑 (2026-07-09):
  4JM12  DB생명 월간 PPT + 변액 분기 XLSX + 비정기 Final.pdf
  2JM23  신한라이프 월간(5영업일) PPTX + 분기 코멘트 XLSX + 비정기 Final.pdf
  07G07  KB국민은행 투자풀 월간 코멘트 DOCX + FactSheet XLSX
  07G04  145개펀드 회신(장성호)의 07G04_YYYYMM.pptx
  08N33/08N81/08P22  월간운용보고서_{fund} XLSX (+08N33 LIG넥스원 비정기 PPT)
  08K88  월별 'SCBK_모니터링 양식' PPT (+교보생명 비정기 PPT)
         ※ 수익자=SC제일은행, 교보생명=판매사. 보고서에 교보생명 로고가 찍히는 건
           판매사 양식이기 때문 (2026-07-28 사용자 확정). FUND_BENEFICIARY 값이 정본.
  (07G02/03 개별 보고 없음 확정. SC제일은행/SK증권 랩 = 대상 외.)

수집 원칙:
- 발신 계열 폴더만: PST/Exchange 보낸 편지함 (+07G04 는 장성호 폴더의 회신).
  요청 메일(업무\\운용보고)의 '양식/작성중/전월 참고' 첨부는 수집하지 않는다.
- 파일명에 양식/작성중/업데이트 전/요청 포함 시 제외. 같은 (fund, period, 파일명) 은
  최신 메일 것만 유지 (PST/Exchange 중복 흡수).
- 저장: data/sent_reports/{fund}/{period}/{filename} + index.json (메일 메타·증분 EntryID).
- 파일은 DRM 원본 그대로 저장 (복호화 없음 — 사내 PC 에서만 열림, 사용자 확정).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SENT_DIR = BASE_DIR / 'data' / 'sent_reports'
INDEX_PATH = SENT_DIR / 'index.json'

PST_STORE_HINT = 'PC 저장'

# 파일명 → (fund, period, kind) 룰. period: YYYY-MM / YYYY-QN / 파일명 날짜.
_MONTH2 = lambda y, m: f'{int(y):04d}-{int(m):02d}'


def _p_4jm12_monthly(fn, dt):
    m = re.search(r'\((\d{4})-(\d{2})\)DB생명', fn)
    return ('4JM12', _MONTH2(m.group(1), m.group(2)), '월간') if m else None


def _p_4jm12_quarterly(fn, dt):
    m = re.search(r'자산운용보고서_DB생명_(\d{2})\.(\d)Q', fn)
    return ('4JM12', f'20{m.group(1)}-Q{m.group(2)}', '분기') if m else None


def _p_2jm23_monthly(fn, dt):
    m = re.search(r'글로벌자산배분B형\)_(\d{4})(\d{2})', fn)
    return ('2JM23', _MONTH2(m.group(1), m.group(2)), '월간') if m else None


def _p_2jm23_quarterly(fn, dt):
    m = re.search(r'코멘트_통합.*?(\d{2})\.(\d)Q', fn)
    if m:
        return ('2JM23', f'20{m.group(1)}-Q{m.group(2)}', '분기')
    m = re.search(r'(\d{4})_(\d)분기_코멘트_통합', fn)  # (첨부1) 2026_1분기_... 형식
    return ('2JM23', f'{m.group(1)}-Q{m.group(2)}', '분기') if m else None


def _p_07g07_comment(fn, dt):
    m = re.search(r'국민은행_(\d{2})년\s*(\d{1,2})월.*코멘트', fn)
    return ('07G07', _MONTH2('20' + m.group(1), m.group(2)), '월간') if m else None


def _p_07g07_factsheet(fn, dt):
    m = re.search(r'FactSheet_(\d{4})년\s*(\d{1,2})월', fn)
    return ('07G07', _MONTH2(m.group(1), m.group(2)), '월간') if m else None


def _p_07g04(fn, dt):
    m = re.search(r'^07G04_(\d{4})(\d{2})\.pptx?$', fn, re.I)
    return ('07G04', _MONTH2(m.group(1), m.group(2)), '월간') if m else None


def _p_ocio_monthly(fn, dt):
    m = re.search(r'월간운용보고서_(08N33|08N81|08P22)_(\d{4})년\s*(\d{1,2})월말', fn)
    return (m.group(1), _MONTH2(m.group(2), m.group(3)), '월간') if m else None


def _p_08k88_adhoc(fn, dt):
    m = re.search(r'교보생명_운용보고_(\d{4})(\d{2})\d{2}', fn)
    return ('08K88', _MONTH2(m.group(1), m.group(2)), '비정기') if m else None


def _p_08n33_adhoc(fn, dt):
    if 'LIG넥스원' in fn and '운용보고' in fn:
        return ('08N33', dt.strftime('%Y-%m'), '비정기')
    return None


def _p_adhoc_final_pdf(fn, dt):
    m = re.search(r'(신한라이프|DB생명)_운용보고_(\d{4})(\d{2})\d{2}.*\.pdf$', fn, re.I)
    if not m:
        return None
    fund = '2JM23' if m.group(1) == '신한라이프' else '4JM12'
    return (fund, _MONTH2(m.group(2), m.group(3)), '비정기')


PARSERS = [
    _p_4jm12_monthly, _p_4jm12_quarterly, _p_2jm23_monthly, _p_2jm23_quarterly,
    _p_07g07_comment, _p_07g07_factsheet, _p_07g04, _p_ocio_monthly,
    _p_08k88_adhoc, _p_08n33_adhoc, _p_adhoc_final_pdf,
]

# 양식/미완성 제외. 단 '작성중' 은 스킵이 아닌 후순위 랭킹 — 회신본 없이 작성중
# 이름 그대로 발송한 사례(4JM12 2026-03) 대응.
_SKIP_FN_KW = ('양식', '업데이트 전', '업데이트요청', '요청', '기초펀드')
_DOC_EXT = ('.ppt', '.pptx', '.doc', '.docx', '.xls', '.xlsx', '.pdf')


def _rank(fn: str) -> int:
    """같은 (fund, period, kind, 확장자) 후보 중 우선순위 — 낮을수록 우선."""
    low = fn.lower()
    if '회신' in fn or 'final' in low:
        return 0
    if '작성중' in fn:
        return 2
    return 1


def classify_attachment(filename: str, mail_dt: datetime):
    """첨부 파일명 → (fund, period, kind) | None."""
    fn = filename.strip()
    if not fn.lower().endswith(_DOC_EXT):
        return None
    if any(k in fn for k in _SKIP_FN_KW):
        return None
    for p in PARSERS:
        r = p(fn, mail_dt)
        if r:
            return r
    return None


# ── Outlook fetch ──

def _iter_source_folders(ns):
    """수집 폴더: (라벨, 폴더). 장성호 폴더는 팀 작성 최종본 발신처 —
    첨부 파일명 파서가 대상 펀드만 거르므로 제목 필터 없이 전체 스캔."""
    pst = None
    exch = None
    for s in ns.Stores:
        if PST_STORE_HINT in (s.DisplayName or ''):
            pst = s
        elif '@' in (s.DisplayName or ''):
            exch = s
    out = []
    if pst:
        root = pst.GetRootFolder()
        for f in root.Folders:
            if f.Name == '보낸 편지함':
                out.append(('PST보낸', f))
            if f.Name == '솔루션전략부':
                for sub in f.Folders:
                    if sub.Name == '장성호':
                        out.append(('장성호', sub))
    if exch:
        try:
            out.append(('Exchange보낸', exch.GetDefaultFolder(5)))
        except Exception:
            pass
    return out


def collect_sent_reports(days_back: int = 400, dry_run: bool = False) -> dict:
    """Outlook 스캔 → 신규 첨부 저장 + index.json 갱신. 반환: 통계."""
    import win32com.client
    try:
        app = win32com.client.GetActiveObject('Outlook.Application')
    except Exception as exc:
        raise RuntimeError(f'Outlook 미실행: {exc}') from exc
    ns = app.GetNamespace('MAPI')

    index = {'entries': [], 'processed_entry_ids': []}
    if INDEX_PATH.exists():
        try:
            index = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    processed = set(index.get('processed_entry_ids') or [])
    # 그룹 key = (fund, period, kind, 확장자) — 같은 문서의 버전들 중 best 1개 유지
    def _gkey(e):
        return (e['fund'], e['period'], e['kind'], Path(e['filename']).suffix.lower())
    by_key = {_gkey(e): e for e in index.get('entries', [])}

    cut = (datetime.now() - timedelta(days=days_back)).strftime('%m/%d/%Y %H:%M')
    n_scanned = n_new = 0
    for label, folder in _iter_source_folders(ns):
        items = folder.Items.Restrict(f"[ReceivedTime] >= '{cut}'")
        for m in items:
            try:
                if getattr(m, 'Class', None) != 43:
                    continue
                eid = str(m.EntryID or '')
                if eid in processed:
                    continue
                n_scanned += 1
                rt = m.ReceivedTime
                mail_dt = datetime(rt.year, rt.month, rt.day)
                subj = str(m.Subject or '')
                for a in m.Attachments:
                    fn = str(a.FileName or '')
                    cls = classify_attachment(fn, mail_dt)
                    if not cls:
                        continue
                    fund, period, kind = cls
                    cand = {
                        'fund': fund, 'period': period, 'kind': kind,
                        'filename': fn, 'rel_path': f'{fund}/{period}/{fn}',
                        'mail_date': mail_dt.strftime('%Y-%m-%d'),
                        'mail_subject': subj[:120], 'source_folder': label,
                        'rank': _rank(fn), 'text_extracted': False,
                    }
                    key = _gkey(cand)
                    old = by_key.get(key)
                    # 우선순위: rank 낮은 것 > 같은 rank 면 최신 메일
                    if old is not None:
                        old_rank = old.get('rank', _rank(old['filename']))
                        if (old_rank, ) < (cand['rank'], ):
                            continue
                        if old_rank == cand['rank'] and old.get('mail_date', '') >= cand['mail_date']:
                            continue
                    dest = SENT_DIR / fund / period / fn
                    if not dry_run:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        a.SaveAsFile(str(dest))
                    by_key[key] = cand
                    n_new += 1
                processed.add(eid)
            except Exception:
                continue

    entries = sorted(by_key.values(), key=lambda e: (e['fund'], e['period'], e['filename']))
    if not dry_run:
        SENT_DIR.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps(
            {'entries': entries, 'processed_entry_ids': sorted(processed)},
            ensure_ascii=False, indent=1), encoding='utf-8')
    funds = {}
    for e in entries:
        funds.setdefault(e['fund'], set()).add(e['period'])
    return {'scanned': n_scanned, 'new_files': n_new, 'total_entries': len(entries),
            'funds': {k: sorted(v) for k, v in sorted(funds.items())},
            'dry_run': dry_run}


def load_index() -> list[dict]:
    """API/생성 참조용 — index entries 로드."""
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text(encoding='utf-8')).get('entries', [])
    except Exception:
        return []


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description='발송 운용보고 취합 (Outlook → sent_reports)')
    ap.add_argument('--days-back', type=int, default=400)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    st = collect_sent_reports(days_back=args.days_back, dry_run=args.dry_run)
    print(f"[sent_report_collector] scanned={st['scanned']} new={st['new_files']} "
          f"total={st['total_entries']} dry_run={st['dry_run']}")
    for fund, periods in st['funds'].items():
        print(f"  {fund}: {len(periods)}개 기간 — {', '.join(periods)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
