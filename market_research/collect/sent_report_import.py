# -*- coding: utf-8 -*-
"""정리 폴더(OCIO_DB/운용보고서) → data/sent_reports 임포터 (2026-07-28).

사용자가 월/분기·펀드별로 정리해 둔 폴더가 **정본**이고, "최종본인가"는
Outlook 첨부와의 교차검증으로 판정한다(사용자 확정 2026-07-28).

  포함: 파일명이 메일 첨부(보낸편지함 2곳 + 장성호 폴더)에 존재하는 것만.
        07G04 처럼 최종본이 장성호 회신으로 돌아오는 건이 있어 보낸함만 보면 누락된다.
  분류: category='main'(운용보고서 본문) / 'appendix'(Factsheet·월별요약 등 부속자료).
        제안서·모니터링 양식·성과분석·백테스트 등 그 외는 임포트하지 않는다.
  기간: 파일명 파서(sent_report_collector.PARSERS) 우선 → 없으면 폴더명.
        202606 폴더에 202605 보고서가 섞여 있는 사례가 있어 파일명이 더 정확하다.

구 아카이브(Outlook 직접 수집분)는 --replace 시 sent_reports.bak_{ts} 로 옮긴다.
후속: sent_report_text(텍스트 추출) → sent_report_preview(캡쳐) 를 이어서 실행할 것.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from market_research.collect.sent_report_collector import PARSERS, SENT_DIR

DEFAULT_ROOT = Path(r'C:\Users\user\Downloads\OCIO_DB\운용보고서')
MANUAL_PATH = Path(__file__).with_name('sent_report_manual.json')
DAYS_BACK = 400
_DOC_EXT = ('.ppt', '.pptx', '.doc', '.docx', '.xls', '.xlsx', '.pdf')

# 본문 = 고객에게 나가는 운용보고서 본체
# 'SCBK_모니터링 양식' 은 이름만 양식일 뿐 08K88(SC제일은행)의 **월별 보고 본체**다
# (사용자 확정 2026-07-28). 구 수집기는 파일명의 '양식' 때문에 이걸 통째로 걸러
# 08K88 아카이브가 비어 있었다.
MAIN_PAT = (
    '월간운용보고서', 'DB생명 글로벌Active', '신한라이프_운용보고서',
    'OCIO 운용 펀드 관련 코멘트', '자산운용보고서_DB생명', '코멘트_통합',
    '펀드운용보고서_한국투자퇴직연금', 'SCBK_모니터링',
    # 08K88 은 모니터링 양식 + 성과분석 시트가 한 세트로 나간다(사용자 확정 2026-07-28,
    # 2026-07 분도 동일 양식 예정). 타 펀드의 성과분석_* 는 PA 작업파일이라 제외 —
    # 그쪽은 메일 첨부에도 없어 어차피 교차검증에서 걸러진다.
    '성과분석_08K88',
)
MAIN_RE = re.compile(r'^07G04_\d{6}\.pptx?$', re.I)
# 부속 = 본문과 함께/별도로 정기 발송되는 참고자료
APPENDIX_PAT = ('Factsheet', 'FactSheet', '월별요약보고서')


def categorize(fn: str) -> str | None:
    if any(p in fn for p in MAIN_PAT) or MAIN_RE.match(fn):
        return 'main'
    if any(p in fn for p in APPENDIX_PAT):
        return 'appendix'
    return None


def folder_period(kind_dir: str, folder: str) -> tuple[str, str] | None:
    """폴더명 → (period, kind). 월/202606 → ('2026-06','월간') · 분기/2026.2Q → ('2026-Q2','분기')"""
    if kind_dir == '월':
        m = re.fullmatch(r'(\d{4})(\d{2})', folder)
        return (f'{m.group(1)}-{m.group(2)}', '월간') if m else None
    m = re.fullmatch(r'(\d{4})\.(\d)Q', folder)
    return (f'{m.group(1)}-Q{m.group(2)}', '분기') if m else None


def name_period(fn: str, dt: datetime):
    """파일명에서 (fund, period, kind) — collector 파서 재사용(제외 키워드는 적용 안 함)."""
    for p in PARSERS:
        try:
            r = p(fn, dt)
        except Exception:
            r = None
        if r:
            return r
    return None


def load_manual() -> list[dict]:
    """수동 포함 목록 (sent_report_manual.json). 없으면 빈 목록."""
    if not MANUAL_PATH.exists():
        return []
    try:
        return json.loads(MANUAL_PATH.read_text(encoding='utf-8')).get('entries', [])
    except Exception as exc:
        print(f'  ⚠ 수동 포함 목록 파싱 실패: {exc}')
        return []


def load_mail_attachments(days_back: int = DAYS_BACK) -> dict[str, dict]:
    """파일명 → 첨부 메타(가장 최근 메일 기준). 보낸편지함 2곳 + 장성호."""
    import pythoncom
    import win32com.client
    from datetime import timedelta

    from market_research.collect.sent_report_collector import _iter_source_folders
    pythoncom.CoInitialize()
    ns = win32com.client.Dispatch('Outlook.Application').GetNamespace('MAPI')
    cut = (datetime.now() - timedelta(days=days_back)).strftime('%m/%d/%Y %H:%M')

    out: dict[str, dict] = {}
    for label, folder in _iter_source_folders(ns):
        try:
            items = folder.Items.Restrict(f"[ReceivedTime] >= '{cut}'")
        except Exception:
            continue
        for m in items:
            try:
                if getattr(m, 'Class', None) != 43 or m.Attachments.Count == 0:
                    continue
                rt = m.ReceivedTime
                d = f'{rt.year:04d}-{rt.month:02d}-{rt.day:02d}'
                subj = str(m.Subject or '')
                for a in m.Attachments:
                    fn = str(a.FileName or '')
                    if not fn.lower().endswith(_DOC_EXT):
                        continue
                    prev = out.get(fn)
                    if prev is None or d > prev['mail_date']:
                        out[fn] = {'mail_date': d, 'mail_subject': subj, 'source': label}
            except Exception:
                continue
    return out


def run(root: Path, replace: bool, dry_run: bool) -> dict:
    from config.funds import FUND_LIST
    funds = set(FUND_LIST)

    mail = load_mail_attachments()
    print(f'[mail] 첨부 고유 파일명 {len(mail)}건')

    picked: dict[tuple[str, str, str], dict] = {}   # (fund, period, filename) → row
    skipped_nomail: list[str] = []
    skipped_cat: list[str] = []
    for kind_dir in ('월', '분기'):
        base = root / kind_dir
        if not base.is_dir():
            continue
        for folder in sorted(p.name for p in base.iterdir() if p.is_dir()):
            fp = folder_period(kind_dir, folder)
            if not fp:
                continue                                  # _inbox_*, '새 폴더' 등
            f_period, f_kind = fp
            # (펀드폴더, 그 안의 파일) + **기간폴더 직하 파일**.
            # ⚠ 종전엔 펀드 하위폴더만 훑어서, 정리가 덜 된 달의 루트 직하 파일이
            #   `skipped_*` 에도 안 잡히고 **통째로 사라졌다** (2026-07 실측: 08K88·
            #   08N33·08P22·4JM12 4건). 루트 직하는 파일명 파서로 펀드를 정한다 —
            #   메일 교차검증은 그대로 걸리므로 오수집 위험은 늘지 않는다.
            scan: list[tuple[str | None, Path]] = [
                (None, p) for p in sorted((base / folder).iterdir()) if p.is_file()
            ]
            for fund_dir in sorted(p for p in (base / folder).iterdir() if p.is_dir()):
                if fund_dir.name not in funds:
                    continue                              # 대시보드 11펀드만
                scan += [(fund_dir.name, p)
                         for p in sorted(fund_dir.iterdir()) if p.is_file()]

            for fund_hint, src in scan:
                fn = src.name
                if not fn.lower().endswith(_DOC_EXT) or fn.startswith('~$'):
                    continue                          # Office 잠금 파일(~$) 제외
                fund = fund_hint
                if fund is None:
                    # 루트 직하 — 파일명에서 펀드를 못 뽑으면 건너뛴다
                    _np = name_period(fn, datetime.now())
                    fund = _np[0] if _np else None
                    if fund not in funds:
                        continue
                cat = categorize(fn)
                if cat is None:
                    skipped_cat.append(f'{fund}/{folder}/{fn}')
                    continue
                meta = mail.get(fn)
                if meta is None:
                    skipped_nomail.append(f'{fund}/{folder}/{fn}')
                    continue
                np = name_period(fn, datetime.strptime(meta['mail_date'], '%Y-%m-%d'))
                period = np[1] if np else f_period
                key = (fund, period, fn)
                if key in picked:
                    continue                          # 여러 폴더에 중복 배치된 동일본
                picked[key] = {
                    'fund': fund, 'period': period, 'filename': fn,
                    'rel_path': f'{fund}/{period}/{fn}', 'kind': f_kind,
                    'category': cat, 'mail_date': meta['mail_date'],
                    'mail_subject': meta['mail_subject'], 'mail_source': meta['source'],
                    'src': str(src), 'text_extracted': False, 'preview_pages': 0,
                }

    # 수동 포함 — 정리 폴더 밖이거나 발송 기록이 없어 교차검증을 통과 못 하는 건
    for m in load_manual():
        src = Path(m['src'])
        if not src.exists():
            print(f"  ⚠ 수동 포함 파일 없음: {m['src']}")
            continue
        key = (m['fund'], m['period'], src.name)
        picked[key] = {
            'fund': m['fund'], 'period': m['period'], 'filename': src.name,
            'rel_path': f"{m['fund']}/{m['period']}/{src.name}",
            'kind': m.get('kind', '비정기'), 'category': m.get('category', 'main'),
            'mail_date': datetime.fromtimestamp(src.stat().st_mtime).strftime('%Y-%m-%d'),
            'mail_subject': m.get('note', ''), 'mail_source': 'manual',
            'src': str(src), 'text_extracted': False, 'preview_pages': 0,
        }
        print(f"  [manual] {m['fund']} {m['period']} {src.name[:56]}")

    print(f'[pick] 임포트 대상 {len(picked)}건 '
          f"(main {sum(1 for v in picked.values() if v['category']=='main')} / "
          f"appendix {sum(1 for v in picked.values() if v['category']=='appendix')})")
    print(f'[skip] 메일 미검증 {len(skipped_nomail)}건 · 분류 제외 {len(skipped_cat)}건')
    if dry_run:
        for k in sorted(picked):
            v = picked[k]
            print(f"  {v['category']:8s} {v['fund']} {v['period']}  {v['filename'][:60]}")
        return {'picked': len(picked), 'dry_run': True}

    # 직전 아카이브의 산출물(.txt / .preview) — 파일이 그대로면 승계한다.
    # 매월 재실행마다 캡쳐를 전량 재생성하면 Office COM 으로 10분이 날아간다.
    old_by_key: dict[tuple[str, str, str], dict] = {}
    bak: Path | None = None
    if replace and SENT_DIR.exists():
        old_idx = SENT_DIR / 'index.json'
        if old_idx.exists():
            try:
                for e in json.loads(old_idx.read_text(encoding='utf-8')).get('entries', []):
                    old_by_key[(e['fund'], e['period'], e['filename'])] = e
            except Exception:
                pass
        bak = SENT_DIR.parent / f'sent_reports.bak_{datetime.now():%Y%m%d_%H%M%S}'
        shutil.move(str(SENT_DIR), str(bak))
        print(f'[backup] 기존 아카이브 → {bak.name}')
    SENT_DIR.mkdir(parents=True, exist_ok=True)

    entries, carried = [], 0
    for k in sorted(picked):
        v = dict(picked[k])
        src = Path(v.pop('src'))
        dst = SENT_DIR / v['rel_path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

        old = old_by_key.get(k)
        if bak and old:
            old_src = bak / old['rel_path']
            if old_src.exists() and old_src.stat().st_size == src.stat().st_size:
                # 같은 파일 → 텍스트/캡쳐 재생성 불필요
                old_txt = Path(str(old_src) + '.txt')
                if old_txt.exists():
                    shutil.copyfile(old_txt, Path(str(dst) + '.txt'))
                    v['text_extracted'] = True
                    v['text_chars'] = old.get('text_chars', 0)
                old_pv = Path(str(old_src) + '.preview')
                if old_pv.is_dir() and old.get('preview_pages'):
                    shutil.copytree(old_pv, Path(str(dst) + '.preview'))
                    v['preview_pages'] = old['preview_pages']
                if v.get('preview_pages') or v.get('text_extracted'):
                    carried += 1
        entries.append(v)
    if carried:
        print(f'[carry] 변경 없는 {carried}건은 기존 텍스트·캡쳐 승계 (재생성 불필요)')

    (SENT_DIR / 'index.json').write_text(
        json.dumps({'entries': entries, 'processed_entry_ids': []},
                   ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'[write] {len(entries)}건 저장 + index.json')
    return {'imported': len(entries),
            'skipped_nomail': len(skipped_nomail), 'skipped_cat': len(skipped_cat)}


def main() -> int:
    ap = argparse.ArgumentParser(description='정리 폴더 → sent_reports 임포트 (메일 교차검증)')
    ap.add_argument('--root', default=str(DEFAULT_ROOT))
    ap.add_argument('--replace', action='store_true', help='기존 아카이브를 백업 후 교체')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    print(f'[sent_report_import] {run(Path(a.root), a.replace, a.dry_run)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
