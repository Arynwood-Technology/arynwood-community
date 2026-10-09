#!/usr/bin/env bash
# One-time setup: Python environment, NKN bridge, and the production frontend build.
set -euo pipefail
cd "$(dirname "$0")"

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo 'Python 3.10 or newer is required.' >&2; exit 1; }
command -v npm >/dev/null || { echo 'Node.js 20.19+ (with npm) is required.' >&2; exit 1; }
node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22&&b>=12)||(a===20&&b>=19)||a===21?0:1)' \
  || { echo "Node.js 20.19+ or 22.12+ is required (found $(node --version))." >&2; exit 1; }

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt
npm --prefix nkn ci
npm --prefix frontend ci
npm --prefix frontend run build

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo 'Created .env from .env.example. Add mail settings there if you want Mail.'
fi
chmod 600 .env
echo 'Setup complete. Start with ./start.sh or install the desktop launcher with ./desktop/install.sh'
echo 'To run a Grove on a server for other people, use deploy/install.sh instead (see deploy/README.md).'
