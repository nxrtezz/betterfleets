#!/usr/bin/env bash
set -euo pipefail

ROOT="${BETTERFLEET_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SESSION="${BETTERFLEET_TMUX_SESSION:-betterfleet}"

APP_COMMAND="${BETTERFLEET_APP_COMMAND:-.venv/bin/gunicorn buses.wsgi:application -c gunicorn.conf.py}"
HUEY_COMMAND="${BETTERFLEET_HUEY_COMMAND:-.venv/bin/python manage.py run_huey}"
ENABLE_HUEY="${BETTERFLEET_ENABLE_HUEY:-1}"

CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-/DATA/cloudflared}"

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Missing required command: $1" >&2
        exit 1
    }
}

cloudflare_command() {
    if [[ -n "${CLOUDFLARED_COMMAND:-}" ]]; then
        printf '%s\n' "$CLOUDFLARED_COMMAND"
        return
    fi

    if [[ ! -x "$CLOUDFLARED_BIN" ]]; then
        echo "Missing executable: $CLOUDFLARED_BIN" >&2
        exit 1
    fi

    if [[ -n "${CLOUDFLARED_CONFIG:-}" ]]; then
        printf '%q tunnel --config %q run' "$CLOUDFLARED_BIN" "$CLOUDFLARED_CONFIG"
        return
    fi

    if [[ -n "${CLOUDFLARED_TUNNEL:-}" ]]; then
        printf '%q tunnel run %q' "$CLOUDFLARED_BIN" "$CLOUDFLARED_TUNNEL"
        return
    fi

    echo "Set CLOUDFLARED_COMMAND, CLOUDFLARED_CONFIG, or CLOUDFLARED_TUNNEL." >&2
    exit 1
}

start_window() {
    local name="$1"
    local command="$2"

    if tmux list-windows -t "$SESSION" -F '#{window_name}' | grep -Fxq "$name"; then
        echo "Window already exists: $SESSION:$name"
        return
    fi

    tmux new-window -t "$SESSION" -c "$ROOT" -n "$name"
    tmux send-keys -t "$SESSION:$name" "$command" C-m
}

need tmux

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Using existing tmux session: $SESSION"
else
    tmux new-session -d -s "$SESSION" -c "$ROOT" -n app
    tmux send-keys -t "$SESSION:app" "$APP_COMMAND" C-m
fi

if [[ "$ENABLE_HUEY" == "1" ]]; then
    start_window huey "$HUEY_COMMAND"
fi

start_window tunnel "$(cloudflare_command)"

echo
echo "Started tmux session: $SESSION"
echo "Attach with:"
echo "  tmux attach -t $SESSION"
