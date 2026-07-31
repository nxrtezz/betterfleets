#!/usr/bin/env bash
set -euo pipefail

SESSION="${BETTERFLEET_TMUX_SESSION:-betterfleet}"

if ! command -v tmux >/dev/null 2>&1; then
    echo "Missing required command: tmux" >&2
    exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo "Stopped tmux session: $SESSION"
else
    echo "No tmux session found: $SESSION"
fi
