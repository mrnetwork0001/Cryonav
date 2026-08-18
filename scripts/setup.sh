#!/usr/bin/env bash
# Cryonav one-shot setup: Python venv + backend deps + frontend deps.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PY="${CRYONAV_PYTHON:-}"
if [[ -z "$PY" ]]; then
  for c in python3.12 python3.11 python3.13 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
  done
fi
[[ -n "$PY" ]] || { echo "no python3 found; set CRYONAV_PYTHON" >&2; exit 1; }

echo "==> Python: $PY ($("$PY" --version 2>&1))"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' \
  || { echo "Cryonav needs Python >= 3.9" >&2; exit 1; }

echo "==> Creating backend venv"
"$PY" -m venv "$ROOT/backend/.venv"
"$ROOT/backend/.venv/bin/pip" install --quiet --upgrade pip
"$ROOT/backend/.venv/bin/pip" install --quiet -r "$ROOT/backend/requirements.txt"

echo "==> Installing frontend packages"
( cd "$ROOT/frontend" && npm install --no-audit --no-fund )

echo
echo "Setup complete."
echo "  ./scripts/dev.sh          start backend :8008 + frontend :5180"
echo "  ./scripts/smoke_test.sh   verify a running backend"
echo "  cd backend && .venv/bin/pytest -q"
