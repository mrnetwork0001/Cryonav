#!/usr/bin/env bash
# Run the FastAPI backend and the Vite dashboard together; Ctrl-C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${CRYONAV_API_PORT:-8008}"
WEB_PORT="${CRYONAV_WEB_PORT:-5180}"

[[ -x "$ROOT/backend/.venv/bin/uvicorn" ]] || { echo "run ./scripts/setup.sh first" >&2; exit 1; }
[[ -d "$ROOT/frontend/node_modules" ]]     || { echo "run ./scripts/setup.sh first" >&2; exit 1; }

cleanup() { trap - INT TERM EXIT; kill 0 2>/dev/null || true; }
trap cleanup INT TERM EXIT

echo "==> backend  http://localhost:${API_PORT}  (docs at /docs)"
( cd "$ROOT/backend" && exec .venv/bin/uvicorn main:app --reload --port "$API_PORT" ) &

echo "==> frontend http://localhost:${WEB_PORT}"
( cd "$ROOT/frontend" && CRYONAV_API="http://127.0.0.1:${API_PORT}" exec npx vite --port "$WEB_PORT" ) &

wait
