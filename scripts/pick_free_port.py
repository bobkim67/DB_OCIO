"""Free port picker — bat launcher 유틸.

사용:
    python scripts/pick_free_port.py --start 8000 [--host 127.0.0.1] [--max-tries 50]
        → 첫 free 포트를 stdout 한 줄로 출력
    python scripts/pick_free_port.py --start 8000 --start 5173 --write runtime_ports.json --keys api web
        → 여러 포트 결정 후 JSON으로 기록 (key:port 매핑)
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path


def _is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pick(host: str, start: int, max_tries: int, taken: set[int]) -> int:
    port = start
    for _ in range(max_tries):
        if port not in taken and _is_free(host, port):
            return port
        port += 1
    raise RuntimeError(f"no free port in range [{start}, {start + max_tries})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--start", action="append", type=int, required=True,
                    help="시작 포트 (반복 지정 가능)")
    ap.add_argument("--max-tries", type=int, default=50)
    ap.add_argument("--write", type=Path, default=None,
                    help="결과를 JSON 파일로 기록 (project root 기준 상대경로 권장)")
    ap.add_argument("--keys", nargs="*", default=None,
                    help="--write 시 사용할 key 이름 (start 개수와 동일)")
    ap.add_argument("--merge", action="store_true",
                    help="--write 시 기존 파일의 다른 키를 보존")
    args = ap.parse_args()

    taken: set[int] = set()
    ports: list[int] = []
    for s in args.start:
        p = pick(args.host, s, args.max_tries, taken)
        taken.add(p)
        ports.append(p)

    if args.write is not None:
        keys = args.keys or [f"port{i}" for i in range(len(ports))]
        if len(keys) != len(ports):
            print(f"keys 개수({len(keys)})와 start 개수({len(ports)}) 불일치",
                  file=sys.stderr)
            return 2
        args.write.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, int] = {}
        if args.merge and args.write.exists():
            try:
                existing = json.loads(args.write.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    payload.update({k: int(v) for k, v in existing.items()
                                    if isinstance(v, (int, str)) and str(v).isdigit()})
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        payload.update({k: p for k, p in zip(keys, ports)})
        args.write.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(" ".join(str(p) for p in ports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
