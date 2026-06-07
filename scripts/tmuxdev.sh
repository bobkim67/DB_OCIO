#!/usr/bin/env bash
# DB_OCIO 개발 런처 (tmux 디스패처) — 단일 창 3-pane: Claude + 프론트(Vite) + 백엔드(FastAPI)
#
# 사용법:
#   vd all       단일 창 3-pane 기동 (없으면 생성, 있으면 프론트/백엔드 재시작)
#   vd end       백엔드(FastAPI) pane만 재시작
#   vd fr        프론트(Vite) pane만 재시작
#   vd stop      세션 종료
#   vd restart   세션 kill 후 재생성
#   vd           이 사용법 출력
#
# 레이아웃 (세션 'ociodev', 창 'dev'):
#   ┌─────────────┬──────────────┐
#   │             │  fr  (Vite)  │
#   │   claude    ├──────────────┤
#   │             │  end (FastAPI)│
#   └─────────────┴──────────────┘
#
# 동작:
#   - pick_free_port.py 로 빈 포트 결정 → .runtime_ports.json (Vite 가 읽어 포트 + /api 프록시 맞춤)
#   - 각 pane 의 pane-id 를 세션 옵션(@p_claude/@p_fr/@p_end)에 저장 → 프로그램이 제목을 덮어써도
#     재시작 타겟이 안정적. respawn-pane -k 로 기존 프로세스 kill 후 재기동.
#   - remain-on-exit on: 프로세스가 죽어도 pane 유지 → 에러 로그 확인 가능
set -euo pipefail

# --- 프로젝트 루트 (이 스크립트 기준 상위 폴더) ---
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SESSION="ociodev"
WIN="dev"
CLAUDE_CMD="${OCIO_CLAUDE_CMD:-claude}"

# --- 파이썬 인터프리터 결정 (api 전용 venv > 루트 venv > 시스템 python3) ---
if [ -x "api/.venv/bin/python" ]; then
  PY="api/.venv/bin/python"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

# --- pane 별 실행 명령 (포트는 ensure_ports 후 주입) ---
backend_cmd()  { echo "$PY -m uvicorn api.main:app --host 127.0.0.1 --port ${API_PORT} --reload"; }
FRONT_CMD="npm run dev"  # cwd=web (vite 가 .runtime_ports.json 으로 포트 결정)

# --- 빈 포트 결정 → .runtime_ports.json (없을 때만 새로 뽑음) ---
ensure_ports() {
  if [ ! -f .runtime_ports.json ]; then
    "$PY" scripts/pick_free_port.py \
      --start "${OCIO_API_PORT:-8000}" --start "${OCIO_WEB_PORT:-5173}" \
      --write .runtime_ports.json --keys api web >/dev/null
  fi
  API_PORT="$("$PY" -c 'import json;print(json.load(open(".runtime_ports.json"))["api"])')"
  WEB_PORT="$("$PY" -c 'import json;print(json.load(open(".runtime_ports.json"))["web"])')"
}

print_urls() {
  echo "===================================="
  echo "  Backend (FastAPI) : http://127.0.0.1:${API_PORT}"
  echo "  Frontend (Vite)   : http://127.0.0.1:${WEB_PORT}"
  echo "===================================="
}

session_exists() { tmux has-session -t "$SESSION" 2>/dev/null; }

# 활성 pane 의 id 반환 (직전 split 결과 캡처용)
_active_pid() { tmux display-message -p -t "$SESSION:$WIN" '#{pane_id}'; }

# 세션 옵션에 저장된 pane-id 가 아직 살아있으면 반환, 아니면 빈 문자열
_pane_id() {  # $1 = 옵션키 (@p_fr 등)
  local pid
  pid="$(tmux show-options -gqv "$1" 2>/dev/null || true)"
  [ -n "$pid" ] && tmux list-panes -a -F '#{pane_id}' 2>/dev/null | grep -qx "$pid" && echo "$pid"
}

# 3-pane 창 생성 (claude | fr / end) + pane-id 저장
create_layout() {
  tmux new-session -d -s "$SESSION" -n "$WIN" -c "$ROOT" "$CLAUDE_CMD"
  local claude_pid fr_pid end_pid
  claude_pid="$(_active_pid)"
  tmux select-pane -t "$claude_pid" -T claude

  tmux split-window -h -l 45% -t "$SESSION:$WIN" -c "$ROOT/web" "$FRONT_CMD"
  fr_pid="$(_active_pid)"
  tmux select-pane -t "$fr_pid" -T fr

  tmux split-window -v -t "$fr_pid" -c "$ROOT" "$(backend_cmd)"
  end_pid="$(_active_pid)"
  tmux select-pane -t "$end_pid" -T end

  tmux set-option -g "@p_claude" "$claude_pid"
  tmux set-option -g "@p_fr" "$fr_pid"
  tmux set-option -g "@p_end" "$end_pid"
  tmux set-option -w -t "$SESSION:$WIN" remain-on-exit on
  tmux set-option -w -t "$SESSION:$WIN" pane-border-status top
  tmux select-pane -t "$claude_pid"
  echo "[vd] 3-pane 기동 (claude | fr / end)"
}

# 특정 pane 재시작 (pane-id 살아있으면 respawn, 아니면 안내)
restart_pane() {  # $1=옵션키 $2=cmd $3=cwd $4=라벨
  local pid; pid="$(_pane_id "$1")"
  if [ -z "$pid" ]; then
    echo "[vd] '$4' pane 없음 — 'vd restart' 로 재생성하세요"; return 1
  fi
  tmux respawn-pane -k -t "$pid" -c "$3" "$2"
  tmux select-pane -t "$pid"
  echo "[vd] '$4' 재시작"
}

# 세션으로 이동 (tmux 안이면 switch, 밖이면 attach)
goto() {
  if [ -n "${TMUX:-}" ]; then
    tmux switch-client -t "$SESSION"
  else
    exec tmux attach -t "$SESSION"
  fi
}

usage() {
  cat <<'EOF'
사용법: vd <command>
  all        단일 창 3-pane(Claude | 프론트 / 백엔드) 기동 / 있으면 프론트·백엔드 재시작
  end        백엔드(FastAPI) pane만 재시작
  fr         프론트(Vite) pane만 재시작
  stop       세션 종료
  restart    세션 kill 후 재생성
EOF
}

case "${1:-}" in
  all)
    ensure_ports
    print_urls
    if session_exists; then
      restart_pane "@p_fr"  "$FRONT_CMD"     "$ROOT/web" "fr"  || true
      restart_pane "@p_end" "$(backend_cmd)" "$ROOT"     "end" || true
    else
      create_layout
    fi
    goto
    ;;
  end)
    ensure_ports
    session_exists || create_layout
    restart_pane "@p_end" "$(backend_cmd)" "$ROOT" "end" || true
    goto
    ;;
  fr)
    ensure_ports
    session_exists || create_layout
    restart_pane "@p_fr" "$FRONT_CMD" "$ROOT/web" "fr" || true
    goto
    ;;
  stop)
    if session_exists; then
      tmux kill-session -t "$SESSION"
      echo "[vd] '$SESSION' 세션 종료"
    else
      echo "[vd] 실행 중인 세션 없음"
    fi
    ;;
  restart)
    session_exists && tmux kill-session -t "$SESSION"
    ensure_ports
    print_urls
    create_layout
    goto
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "[vd] 알 수 없는 명령: $1" >&2
    usage
    exit 1
    ;;
esac
