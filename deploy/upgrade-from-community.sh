#!/usr/bin/env bash
# Upgrade an Arynwood Community 0.3 server to Arynwood Grove, in place, or a Grove that was
# upgraded this way to a newer release.
#
#   bash upgrade-from-community.sh --dir ~/arynwood-community --from arynwood-grove-0.7.1.tar.gz
#
# Run it as the account that owns the install, not as root. It keeps the install's folder,
# .env, data, IRC settings and Python environment, so the existing systemd service
# and nginx site keep working unchanged. Accounts, spaces and signed-in sessions carry over.
# The only step that needs sudo is the short stop and start of the service.
#
#   --prepare-only   Stage and test the new release without touching the running service.
set -euo pipefail

DIR="" FROM="" SERVICE=arynwood-community PREPARE_ONLY=0 PORT=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --dir) DIR=${2%/}; shift 2 ;;
    --from) FROM=$2; shift 2 ;;
    --service) SERVICE=$2; shift 2 ;;
    --port) PORT=$2; shift 2 ;;
    --prepare-only) PREPARE_ONLY=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done
say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -ne 0 ]] || die "Run this as the account that owns the install, not as root."
[[ -n $DIR && -f $DIR/backend/community/store.py && -f $DIR/.env ]] || die "--dir must be a Community install folder (with backend/ and .env)."
[[ -f $FROM ]] || die "--from must be a Grove release file (arynwood-grove-<version>.tar.gz)."
DIR=$(cd "$DIR" && pwd)
NEXT=$DIR.next
env_value() { sed -n "s/^$1=//p" "$DIR/.env" | tail -n1 | tr -d "\"'"; }
PORT=${PORT:-$(env_value COMMUNITY_PORT)}; PORT=${PORT:-8018}
HOST=$(env_value COMMUNITY_HOSTS); HOST=${HOST%%,*}; HOST=${HOST:-127.0.0.1}
DATA=$(env_value COMMUNITY_DATA_DIR); DATA=${DATA:-$DIR/data}; [[ $DATA == /* ]] || DATA=$DIR/$DATA
DATA=$(cd "$DATA" && pwd)
python=$DIR/.venv/bin/python
[[ -x $python ]] || die "No Python environment at $DIR/.venv."
PREV=$(sed -n "s/^VERSION = '\(.*\)'/\1/p" "$DIR/backend/community/store.py"); PREV=${PREV:-unknown}

stamp=$(date +%Y%m%d-%H%M%S)
BACKUP=${DIR%/*}/arynwood-community-backups/$stamp
say "Backing up to $BACKUP"
install -d -m 0700 "$BACKUP"
for db in "$DATA"/*.sqlite3; do
  [[ -f $db ]] || continue
  # SQLite's online backup: consistent while the service keeps running.
  "$python" -c 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); t=sqlite3.connect(sys.argv[2]); s.backup(t); t.close()' "$db" "$BACKUP/$(basename "$db")"
done
cp -p "$DIR/.env" "$BACKUP/.env"
[[ -d $DIR/config ]] && cp -rp "$DIR/config" "$BACKUP/config"
# Private messages (NKN) are gone; their identity is kept with the backup all the same.
[[ -f $DIR/nkn/wallet.json ]] && cp -p "$DIR/nkn/wallet.json" "$BACKUP/wallet.json"
chmod -R go-rwx "$BACKUP"

say "Staging the new release in $NEXT"
rm -rf "$NEXT"; mkdir "$NEXT"
tar -xzf "$FROM" -C "$NEXT" --strip-components=1
[[ -f $NEXT/backend/api.py && -f $NEXT/frontend/dist/index.html ]] || die "$FROM is not a Grove release."
NEW=$(cat "$NEXT/VERSION" 2>/dev/null || true)
cp -p "$DIR/.env" "$NEXT/.env"
[[ -d $DIR/config ]] && { rm -rf "$NEXT/config"; cp -rp "$DIR/config" "$NEXT/config"; }
# The environment is copied, not rebuilt: it ends up at the same path once the folders swap.
cp -a "$DIR/.venv" "$NEXT/.venv"
"$NEXT/.venv/bin/python" -m pip install -q --disable-pip-version-check -r "$NEXT/requirements.txt"

say "Testing the new release against a copy of the data"
trial=$(mktemp -d); trap 'rm -rf "$trial"' EXIT
db=$(ls "$BACKUP"/*.sqlite3 2>/dev/null | head -n1 || true)
[[ -n $db ]] && cp "$db" "$trial/"
trial_port=$((PORT + 10000))
(cd "$NEXT" && GROVE_DATA_DIR=$trial GROVE_HOSTS=127.0.0.1 exec .venv/bin/python -m uvicorn backend.api:app --host 127.0.0.1 --port $trial_port --log-level warning) &
trial_pid=$!
ok=0
for _ in $(seq 1 30); do curl -fsS -m 2 "http://127.0.0.1:$trial_port/api/health" >/dev/null 2>&1 && { ok=1; break; }; sleep 1; done
counts=$(cd "$NEXT" && GROVE_DATA_DIR=$trial .venv/bin/python -c 'from backend.community.store import db
with db() as c: print(*(c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("users","spaces","entries")))' 2>/dev/null || echo "? ? ?")
kill $trial_pid 2>/dev/null; wait $trial_pid 2>/dev/null || true
[[ $ok == 1 ]] || die "The new release did not start against a copy of the data. Nothing was changed. ($NEXT is left for inspection.)"
read -r users spaces entries <<<"$counts"
say "The new release reads the data: $users accounts, $spaces spaces, $entries items."

if [[ $PREPARE_ONLY == 1 ]]; then
  say "Prepared. To switch, run this again without --prepare-only."
  exit 0
fi

OLD=$DIR-$PREV-$stamp
say "Switching: stopping $SERVICE for a few seconds (sudo)"
sudo systemctl stop "$SERVICE"
# The live data moves (never copied), so nothing written before the stop is lost.
if [[ $DATA == "$DIR/data" ]]; then rm -rf "$NEXT/data"; mv "$DIR/data" "$NEXT/data"; fi
mv "$DIR" "$OLD"; mv "$NEXT" "$DIR"
sudo systemctl start "$SERVICE"
healthy=0
# The new version must be the one answering, not a process left over from before the stop.
for _ in $(seq 1 30); do curl -fsS -m 2 -H "Host: $HOST" "http://127.0.0.1:$PORT/api/health" 2>/dev/null | grep 'Arynwood Grove' | grep -q "\"version\":\"$NEW" && { healthy=1; break; }; sleep 1; done
if [[ $healthy == 0 ]]; then
  echo "The new release did not start. Putting $PREV back." >&2
  sudo systemctl stop "$SERVICE"
  mv "$DIR" "$NEXT"; mv "$OLD" "$DIR"
  if [[ $DATA == "$DIR/data" && -d $NEXT/data ]]; then mv "$NEXT/data" "$DIR/data"; fi
  sudo systemctl start "$SERVICE"
  die "Back on $PREV. See: sudo journalctl -u $SERVICE -n 50"
fi
say "Arynwood Grove is running in $DIR. Members stay signed in."
cat <<DONE

  The previous version ($PREV) is kept in $OLD
  Backups are in $BACKUP
  To go back:  sudo systemctl stop $SERVICE && mv $DIR/data $OLD/data && mv $DIR $DIR.grove && mv $OLD $DIR && sudo systemctl start $SERVICE

DONE
