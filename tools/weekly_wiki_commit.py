"""Weekly wiki batch commit (idempotent, manual trigger).

Use:
    python tools/weekly_wiki_commit.py                  # 수동 (경과일수 무시)
    python tools/weekly_wiki_commit.py --min-age-days 7 # 자동 호출용 (주간 게이트)

세션 시작 시 Claude 가 마지막 wiki commit 일자 + working tree 변경 여부를
체크해 7일 초과 + 변경 존재 시 사용자에게 진행 여부를 묻는다.
규칙은 프로젝트 CLAUDE.md "Wiki commit 주기 체크" 섹션 참조.

--min-age-days 는 daily_update 성공 직후 자동 호출(launch_daily_update.bat)용
게이트다. 매일 daily_update 를 돌려도 wiki commit 은 주 1회로 묶인다
(게이트가 없으면 daily commit 이 되어 batch 정책이 무너진다).
기본 0 = 게이트 없음이라 수동 실행 동작은 종전과 같다.

동작:
  1. git status 로 wiki/ 변경분 확인 → 없으면 no-op (exit 0)
  2. 마지막 wiki commit 일자 → 경과 일수 N. N < min_age_days 면 no-op (exit 0)
  3. git add market_research/data/wiki/  (다른 변경분 안 건드림)
  4. git commit -m "chore(wiki): weekly batch (catchup={N}d, files={F})"
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime

WIKI_PATH = "market_research/data/wiki/"


def _run(cmd: list[str], check: bool = True) -> str:
    out = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if check and out.returncode != 0:
        sys.stderr.write(f"[FAIL] {' '.join(cmd)}\n{out.stderr}")
        sys.exit(1)
    return out.stdout


def _changed_count() -> int:
    out = _run(
        ["git", "-c", "core.quotePath=false", "status", "--porcelain",
         "--", WIKI_PATH]
    )
    return sum(1 for line in out.splitlines() if line.strip())


def _last_commit_date() -> date | None:
    out = _run(
        ["git", "log", "-1", "--format=%cs", "--", WIKI_PATH], check=False
    ).strip()
    if not out:
        return None
    try:
        return datetime.strptime(out, "%Y-%m-%d").date()
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--min-age-days",
        type=int,
        default=0,
        help="마지막 wiki commit 이 이 일수보다 최근이면 아무것도 안 한다 "
             "(자동 호출용 주간 게이트, 기본 0=게이트 없음)",
    )
    args = ap.parse_args(argv)

    n_files = _changed_count()
    if n_files == 0:
        print("[no-op] no changes in wiki/")
        return 0

    last_dt = _last_commit_date()
    today = date.today()
    days_label: str
    if last_dt is None:
        days_label = "first"
    else:
        age = (today - last_dt).days
        if age < args.min_age_days:
            print(
                f"[no-op] last wiki commit {age}d ago "
                f"(< --min-age-days {args.min_age_days}) — batch 주기 대기"
            )
            return 0
        days_label = f"{age}d"

    print(f"[plan] last wiki commit: {last_dt} ({days_label} ago)")
    print(f"[plan] {n_files} changed entries in wiki/")

    _run(["git", "add", "--", WIKI_PATH])
    msg = f"chore(wiki): weekly batch (catchup={days_label}, files={n_files})"
    _run(["git", "commit", "-m", msg])

    head = _run(["git", "rev-parse", "--short", "HEAD"]).strip()
    print(f"[ok] committed {head} — \"{msg}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
