#!/usr/bin/env bash
# Serve Arynwood Grove. Defaults to this computer only (127.0.0.1:8018).
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python || ! -f frontend/dist/index.html ]]; then
  echo 'Run ./setup.sh first.' >&2
  exit 1
fi
# Read only the bind settings here; the app loads the rest of .env itself
# (sourcing it would mangle passwords containing $ or spaces).
env_value() { [[ -f .env ]] && sed -n "s/^$1=//p" .env | tail -n1 | tr -d "\"'" || true; }
# GROVE_* settings; COMMUNITY_* names from Community 0.3 still work.
HOST="${GROVE_BIND:-$(env_value GROVE_BIND)}"; HOST="${HOST:-${COMMUNITY_BIND:-$(env_value COMMUNITY_BIND)}}"; HOST="${HOST:-127.0.0.1}"
PORT="${GROVE_PORT:-$(env_value GROVE_PORT)}"; PORT="${PORT:-${COMMUNITY_PORT:-$(env_value COMMUNITY_PORT)}}"; PORT="${PORT:-8018}"
echo "Arynwood Grove: http://${HOST}:${PORT}/community"
exec .venv/bin/python -m uvicorn backend.api:app --host "$HOST" --port "$PORT" --proxy-headers --forwarded-allow-ips="${GROVE_TRUSTED_PROXIES:-${COMMUNITY_TRUSTED_PROXIES:-127.0.0.1}}"
