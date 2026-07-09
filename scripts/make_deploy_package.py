# -*- coding: utf-8 -*-
"""배포 패키지 생성 — 소스 공유용 최소셋 zip (배포 하드닝, 2026-07-09).

python scripts/make_deploy_package.py [출력디렉토리]

포함: api/ modules/ config/ market_research/(코드만) web/(소스+dist, node_modules 제외)
      scripts/ docs/dashboard_features.md DEPLOY.md .env.example
제외: 데이터/캐시/R legacy/디버그/git — 아래 EXCLUDE 참조.
생성 후 zip 내부에 시크릿 문자열이 남았는지 자체 검사한다 (발견 시 실패).
"""
from __future__ import annotations

import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INCLUDE = [
    'api', 'modules', 'config', 'market_research', 'web',
    # scripts 는 기동 관련만 (설치/배포도구/데일리배치 제외)
    'scripts/launch_dashboard.bat', 'scripts/launch_fastapi.bat',
    'scripts/uvicorn_logging.json', 'scripts/pick_free_port.py',
    'docs/dashboard_features.md',
    'DEPLOY.md', '.env.example',
]

# 디렉토리명 단위 제외 (경로 어디에 나와도 제외)
EXCLUDE_DIR_NAMES = {
    '__pycache__', 'node_modules', '.git', '.cache', '.pytest_cache',
    'dist-snapshot', '.venv', 'venv',
}
# 운용보고 조회 데이터 씨딩 (2026-07-09 사용자 지시) — data 제외보다 우선 적용.
# 서버는 조회 전용: 코멘트 생성/승인은 PC 에서 하고, 이후 갱신은 이 5개 폴더를
# 서버에 덮어쓰면 됨 (report_service 무캐시 → 재시작 불필요).
ALLOW_PREFIXES = [
    'market_research/data/report_output',    # 승인 final + draft
    'market_research/data/claims',           # 근거 claim (read-time 인용 해석)
    'market_research/data/naver_research/adapted',  # evidence 원천
    'market_research/data/broker_mail',
    'market_research/data/monygeek',
]

# ROOT 기준 상대경로 prefix 제외 — 구동 불필요 내부자료 (2026-07-09 사용자 지적로 강화)
EXCLUDE_PREFIXES = [
    'market_research/data',      # 리서치 산출물 (뉴스/claim/wiki/보고서)
    'market_research/debug',
    'market_research/devlog',
    'market_research/docs',      # 설계문서/리뷰패킷 (내부)
    'market_research/output',
    'market_research/research',
    'market_research/tests',
    'market_research/tools',     # 운영 배치 도구 (서버 구동 불필요)
    'api/tests',
    'web/dist_dev',
]
EXCLUDE_FILE_NAMES = {'.env', 'db_cache.sqlite', 'CLAUDE.md'}
EXCLUDE_SUFFIXES = {'.pyc', '.pkl', '.log', '.bak'}

# zip 내부 시크릿 잔존 검사 — 실제 시크릿 값은 로컬 .env 에서 읽어 동적 구성
# (이 스크립트 자체가 패키지에 포함되므로 시크릿 리터럴을 박지 않는다)
_SECRET_KEY_PAT = re.compile(r'(PASSWORD|API_KEY|KEY|TOKEN|SECRET)\s*$', re.I)


def _load_secret_patterns() -> list[re.Pattern]:
    pats = [re.compile(rb'sk-' + rb'ant-')]  # API 키 prefix (값 아님; 자기매칭 방지 분리)
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = (s.strip() for s in line.split('=', 1))
            # 시크릿성 키만 (host/user 는 코드 default 로 존재 — 오탐 방지)
            if val and len(val) >= 8 and _SECRET_KEY_PAT.search(key):
                pats.append(re.compile(re.escape(val.encode('utf-8'))))
    return pats


SECRET_PATTERNS = _load_secret_patterns()
TEXT_SUFFIXES = {'.py', '.ts', '.tsx', '.js', '.json', '.md', '.txt', '.yaml', '.yml',
                 '.bat', '.css', '.html', '.example', '.toml', '.cfg', '.ini', '.R'}


def _excluded(rel: str, name: str) -> bool:
    parts = rel.replace('\\', '/').split('/')
    if any(p in EXCLUDE_DIR_NAMES for p in parts):
        return True
    if name in EXCLUDE_FILE_NAMES:
        return True
    if Path(name).suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    rel_posix = rel.replace('\\', '/')
    if any(rel_posix.startswith(pfx) for pfx in ALLOW_PREFIXES):
        return False  # 운용보고 데이터 씨딩 — data 제외보다 우선
    return any(rel_posix.startswith(pfx) for pfx in EXCLUDE_PREFIXES)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'dist_package'
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d')
    zip_path = out_dir / f'DB_OCIO_dashboard_{stamp}.zip'

    n_files = 0
    leaks: list[str] = []
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in INCLUDE:
            src = ROOT / item
            if not src.exists():
                print(f'  [skip] {item} (없음)')
                continue
            files = [src] if src.is_file() else sorted(src.rglob('*'))
            for f in files:
                if not f.is_file():
                    continue
                rel = str(f.relative_to(ROOT))
                if _excluded(rel, f.name):
                    continue
                data = f.read_bytes()
                if f.suffix.lower() in TEXT_SUFFIXES:
                    for pat in SECRET_PATTERNS:
                        if pat.search(data):
                            leaks.append(rel)
                            break
                zf.write(f, rel)
                n_files += 1

    if leaks:
        zip_path.unlink(missing_ok=True)
        print('[FAIL] 시크릿 잔존 발견 — 패키지 삭제됨:')
        for l in leaks:
            print(f'   - {l}')
        return 1

    mb = zip_path.stat().st_size / 1e6
    print(f'[ok] {zip_path} ({n_files} files, {mb:.1f} MB) — 시크릿 검사 통과')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
