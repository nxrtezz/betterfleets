#!/usr/bin/env bash
set -euo pipefail

ROOT="${BETTERFLEET_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

"$ROOT/scripts/stop-production.sh"
"$ROOT/scripts/start-production.sh"
