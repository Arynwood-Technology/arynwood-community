#!/usr/bin/env bash
# Serve Arynwood Community. Defaults to this computer only (127.0.0.1:8018).
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python || ! -f frontend/dist/index.html || ! -d nkn/node_modules ]]; then
  echo 'Run ./setup.sh first.' >&2
  exit 1
fi
# Read only the bind settings here; the app loads the rest of .env itself
# (sourcing it would mangle passwords containing $ or spaces).
env_value() { [[ -f .env ]] && sed -n "s/^$1=//p" .env | tail -n1 | tr -d "\"'" || true; }
HOST="${COMMUNITY_BIND:-$(env_value COMMUNITY_BIND)}"; HOST="${HOST:-127.0.0.1}"
PORT="${COMMUNITY_PORT:-$(env_value COMMUNITY_PORT)}"; PORT="${PORT:-8018}"
echo "Arynwood Community: http://${HOST}:${PORT}"
exec .venv/bin/python -m uvicorn backend.api:app --host "$HOST" --port "$PORT" --proxy-headers --forwarded-allow-ips="${COMMUNITY_TRUSTED_PROXIES:-127.0.0.1}"
