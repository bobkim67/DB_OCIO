"""Weekly wiki batch commit (idempotent, manual trigger).

Use:
    python tools/weekly_wiki_commit.py

세션 시작 시 Claude 가 마지막 wiki commit 일자 + working tree 변경 여부를
체크해 7일 초과 + 변경 존재 시 사용자에게 진행 여부를 묻는다.
규칙은 프로젝트 CLAUDE.md "Wiki commit 주기 체크" 섹션 참조.

동작:
  1. git status 로 wiki/ 변경분 확인 → 없으면 no-op (exit 0)
  2. 마지막 wiki commit 일자 → 경과 일수 N
  3. git add market_research/data/wiki/  (다른 변경분 안 건드림)
  4. git commit -m "chore(wiki): weekly batch (catchup={N}d, files={F})"
"""
from __future__ import annotations

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


def main() -> int:
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
        days_label = f"{(today - last_dt).days}d"

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
