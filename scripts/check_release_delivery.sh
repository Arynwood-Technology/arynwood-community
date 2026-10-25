#!/usr/bin/env bash
# End-to-end check of release delivery, in throwaway Docker containers: the one-command installer and
# `arynwood-grove update` against a local HTTPS release server with its own certificate.
#
#   scripts/check_release_delivery.sh release/arynwood-grove-<version>.tar.gz
#
# The tarball is what scripts/package.sh builds. From it this makes test releases: three good ones, one
# changed after its checksum was published, one with no checksum, and one that can't start. It checks that
#   - the installer installs a verified release, and refuses a changed one, a missing checksum and a
#     plain-HTTP address before it changes anything on the server;
#   - the updater installs a verified release, refuses a changed one and a missing checksum, and leaves
#     the running release in place;
#   - an update that can't start goes back to the release that was running.
# Needs Docker, and network access for the containers' apt and pip. It contacts no Grove and not GitHub.
# A stand-in for systemctl runs the service directly, since the containers have no systemd.
set -euo pipefail
cd "$(dirname "$0")/.."
release=${1:?Usage: scripts/check_release_delivery.sh release/arynwood-grove-<version>.tar.gz}
image=${E2E_IMAGE:-ubuntu:24.04}
work=$(mktemp -d); containers=()
cleanup() { for c in "${containers[@]}"; do docker rm -f "$c" >/dev/null 2>&1 || true; done; rm -rf "$work"; }
trap cleanup EXIT
pass=0 fail=0
ok()   { printf '\033[1;32mPASS\033[0m %s\n' "$*"; pass=$((pass + 1)); }
bad()  { printf '\033[1;31mFAIL\033[0m %s\n' "$*"; fail=$((fail + 1)); }

# Test releases ------------------------------------------------------------------------------------
make_release() {  # make_release VERSION [break|tamper|nosum]
  local version=$1 how=${2:-} dir=$work/srv/download/v$1 name=arynwood-grove-$1
  mkdir -p "$dir" "$work/build/$version"
  tar -xzf "$release" -C "$work/build/$version"
  mv "$work/build/$version"/arynwood-grove-* "$work/build/$version/$name"
  echo "$version" >"$work/build/$version/$name/VERSION"
  # A release that compiles but whose service exits at once.
  [[ $how == break ]] && sed -i '1i raise SystemExit("this release is broken on purpose")' "$work/build/$version/$name/backend/api.py"
  tar --owner=0 --group=0 -czf "$dir/$name.tar.gz" -C "$work/build/$version" "$name"
  (cd "$dir" && sha256sum "$name.tar.gz" >"$name.tar.gz.sha256")
  [[ $how == tamper ]] && printf 'x' >>"$dir/$name.tar.gz"   # changed after the checksum was published
  [[ $how == nosum ]] && rm "$dir/$name.tar.gz.sha256"
  return 0
}
make_release 1.0.0-e2e.1
make_release 1.0.0-e2e.2
make_release 1.0.0-e2e.3 tamper
make_release 1.0.0-e2e.4 nosum
make_release 1.0.0-e2e.5 break
cp deploy/install.sh "$work/install.sh"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$work/key.pem" -out "$work/cert.pem" -days 1 \
  -subj /CN=127.0.0.1 -addext subjectAltName=IP:127.0.0.1 2>/dev/null
cat >"$work/serve.py" <<'PY'
import http.server, ssl, sys
handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory='/e2e/srv', **kw)
server = http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), handler)
if sys.argv[2] == 'https':
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain('/e2e/cert.pem', '/e2e/key.pem')
    server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
PY
cat >"$work/systemctl" <<'SH'
#!/bin/bash
# Stand-in for systemd: starts and stops the Grove's service directly; every other unit is a no-op.
cmd=$1; shift
grove_running() { pgrep -f 'uvicorn backend.api:app' >/dev/null; }
case $cmd in
  start|restart|stop)
    for unit in "$@"; do
      [[ $unit == arynwood-grove || $unit == arynwood-grove.service ]] || continue
      pkill -f 'uvicorn backend.api:app' || true
      for _ in $(seq 1 20); do grove_running || break; sleep 0.2; done
      [[ $cmd == stop ]] && continue
      setsid -f runuser -u grove -- bash -c 'set -a; . /etc/arynwood-grove/grove.env; set +a; cd /opt/arynwood-grove/current &&
        exec .venv/bin/python -m uvicorn backend.api:app --host 127.0.0.1 --port "$GROVE_PORT" --no-access-log' >>/var/log/grove.log 2>&1
    done ;;
  is-active) grove_running ;;
esac
exit 0
SH
chmod +x "$work/systemctl"

# Containers ---------------------------------------------------------------------------------------
start_container() {  # start_container NAME: a fresh server, as $c, with the release servers running
  local name=grove-e2e-$1-$$
  docker run -d --name "$name" -v "$work:/e2e:ro" "$image" sleep infinity >/dev/null
  containers+=("$name")
  docker exec "$name" bash -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq python3 openssl ca-certificates curl procps >/dev/null' \
    || { echo "Could not prepare the container" >&2; exit 1; }
  # The release server's certificate is trusted the way a mirror's would be: in the system's store.
  docker exec "$name" bash -c 'cp /e2e/cert.pem /usr/local/share/ca-certificates/grove-e2e.crt && update-ca-certificates >/dev/null'
  docker exec "$name" install -m 0755 /e2e/systemctl /usr/local/bin/systemctl
  docker exec -d "$name" python3 /e2e/serve.py 8443 https
  docker exec -d "$name" python3 /e2e/serve.py 8080 http
  docker exec "$name" bash -c 'for _ in $(seq 1 50); do curl -fsS -o /dev/null https://127.0.0.1:8443/ && exit 0; sleep 0.2; done; exit 1'
  c=$name
}
run() {  # run CONTAINER BASE COMMAND...: a command as root, with the test release address
  local c=$1 base=$2; shift 2
  docker exec -e GROVE_RELEASE_BASE="$base" "$c" "$@" >"$work/out" 2>&1
}
said() { grep -qF -- "$1" "$work/out"; }
running() { docker exec "$1" bash -c "readlink -f /opt/arynwood-grove/current; curl -fsS -m 5 http://127.0.0.1:8018/api/health >/dev/null"; }
https=https://127.0.0.1:8443/download
install=(bash /e2e/install.sh --domain grove.test --no-https --yes)

echo "== The installer refuses before changing anything"
start_container refuse
untouched() { docker exec "$c" bash -c '! test -e /opt/arynwood-grove && ! id grove >/dev/null 2>&1 && ! command -v nginx >/dev/null'; }
if ! run "$c" "$https/v1.0.0-e2e.3" "${install[@]}" --version 1.0.0-e2e.3 && said 'does not match its checksum' && said 'Nothing was installed' && untouched
then ok "changed release: refused, nothing installed"; else bad "changed release"; cat "$work/out"; fi
if ! run "$c" "$https/v1.0.0-e2e.4" "${install[@]}" --version 1.0.0-e2e.4 && said 'Could not download the checksum' && untouched
then ok "missing checksum: refused, nothing installed"; else bad "missing checksum"; cat "$work/out"; fi
if ! run "$c" "http://127.0.0.1:8080/download/v1.0.0-e2e.1" "${install[@]}" --version 1.0.0-e2e.1 && said 'over HTTPS only' && untouched
then ok "plain-HTTP release address: refused, nothing installed"; else bad "plain-HTTP address"; cat "$work/out"; fi
docker exec "$c" cp /e2e/srv/download/v1.0.0-e2e.1/arynwood-grove-1.0.0-e2e.1.tar.gz /root/
if ! run "$c" "" "${install[@]}" --from /root/arynwood-grove-1.0.0-e2e.1.tar.gz && said 'No checksum for' && untouched
then ok "--from a tarball with no checksum beside it: refused, nothing installed"; else bad "--from without checksum"; cat "$work/out"; fi

echo "== Install, update, refusals and rollback on one server"
start_container server
if run "$c" "$https/v1.0.0-e2e.1" "${install[@]}" --version 1.0.0-e2e.1 && running "$c" | grep -q 'releases/1.0.0-e2e.1$'
then ok "verified release: installed and running (1.0.0-e2e.1)"; else bad "verified install"; cat "$work/out"; fi
if run "$c" "$https/v1.0.0-e2e.2" arynwood-grove update --version 1.0.0-e2e.2 && running "$c" | grep -q 'releases/1.0.0-e2e.2$'
then ok "update to a verified release: installed and running (1.0.0-e2e.2)"; else bad "verified update"; cat "$work/out"; fi
if ! run "$c" "$https/v1.0.0-e2e.3" arynwood-grove update --version 1.0.0-e2e.3 && said 'does not match its checksum' && said 'Nothing was changed' \
   && running "$c" | grep -q 'releases/1.0.0-e2e.2$' && ! docker exec "$c" test -e /opt/arynwood-grove/releases/1.0.0-e2e.3
then ok "update to a changed release: refused, 1.0.0-e2e.2 still running"; else bad "changed update"; cat "$work/out"; fi
if ! run "$c" "$https/v1.0.0-e2e.4" arynwood-grove update --version 1.0.0-e2e.4 && said 'Could not download the checksum' && running "$c" | grep -q 'releases/1.0.0-e2e.2$'
then ok "update with a missing checksum: refused, 1.0.0-e2e.2 still running"; else bad "missing-checksum update"; cat "$work/out"; fi
docker exec "$c" cp /e2e/srv/download/v1.0.0-e2e.1/arynwood-grove-1.0.0-e2e.1.tar.gz /root/
if ! run "$c" "" arynwood-grove update --from /root/arynwood-grove-1.0.0-e2e.1.tar.gz && said 'No checksum for' && running "$c" | grep -q 'releases/1.0.0-e2e.2$'
then ok "update --from a tarball with no checksum beside it: refused"; else bad "update --from without checksum"; cat "$work/out"; fi
if ! run "$c" "$https/v1.0.0-e2e.5" arynwood-grove update --version 1.0.0-e2e.5 && said 'did not start' && running "$c" | grep -q 'releases/1.0.0-e2e.2$'
then ok "verified release that can't start: rolled back, 1.0.0-e2e.2 running"; else bad "rollback"; cat "$work/out"; fi

echo "$pass passed, $fail failed"
[[ $fail == 0 ]]
