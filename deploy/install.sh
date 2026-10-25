#!/usr/bin/env bash
# Arynwood Grove server installer, for Ubuntu 22.04+ or Debian 12+ on a VPS.
#
#   curl -fsSL https://github.com/Arynwood-Technology/arynwood-community/releases/latest/download/install.sh \
#     | sudo bash -s -- --domain grove.example.com --email you@example.com
#
# Run it again (or `sudo arynwood-grove update`) to update: settings, accounts and spaces are kept.
# With --name, it adds another Grove to the same server (or updates that one): each has its own
# service, system user, data, settings and port, and all of them share the releases.
set -euo pipefail
# Root's umask may be 077 on a hardened server; the service user must still read the release.
umask 022

REPO="Arynwood-Technology/arynwood-community"
PREFIX=/opt/arynwood-grove

DOMAIN="" EMAIL="" FROM="" VERSION=latest PORT="" HTTPS=1 NO_DOMAIN=0 ASSUME_YES=0 UPDATE_ONLY=0 NAME=""

usage() {
  cat <<'USAGE'
Installs Arynwood Grove: a private community service your friends open in a browser.

  --domain NAME     The web address for your Grove, e.g. grove.example.com. Point its DNS
                    record (an A record) at this server first.
  --email ADDRESS   Where Let's Encrypt sends certificate notices.
  --no-domain       No domain yet: use a free temporary name for this server's IP address
                    (<ip>.sslip.io). Move to your own domain later.
  --version X.Y.Z   Install a particular release (default: the latest).
  --from PATH       Install from a release file (.tar.gz) or folder instead of downloading.
  --port N          Local port the service listens on (default 8018; with --name, the first
                    free one from 8100).
  --name NAME       Another Grove on this server, e.g. --name roguefest. Its data is in
                    /var/lib/arynwood-groves/NAME; manage it with arynwood-grove --grove NAME.
  --no-https        Skip the certificate. For testing on a private network only.
  --update          Only update the program; leave nginx and certificates alone.
  --yes             Do not ask questions.
USAGE
}

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }
ask()  {  # ask VAR "question" — reads from the terminal even when this script arrives through a pipe
  local reply=""
  if [[ $ASSUME_YES == 0 && -r /dev/tty ]]; then read -r -p "$2 " reply </dev/tty || true; fi
  printf -v "$1" '%s' "$reply"
}
env_value() { [[ -f $ENV_FILE ]] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1 || true; }

# --- Release delivery: the same lines are in deploy/install.sh, deploy/arynwood-grove and
# deploy/upgrade-from-community.sh (tests/test_release_delivery.py keeps them identical).
# A release is a tarball with a .sha256 file beside it, as scripts/package.sh writes them. Nothing is
# installed from a tarball that doesn't match it: a missing, malformed or different checksum stops here.
verify_release() {  # verify_release FILE: FILE must match the checksum in FILE.sha256
  local file=$1 name sums line actual
  name=$(basename "$file") sums=$1.sha256
  [[ -s $sums ]] || { echo "No checksum for $name: $name.sha256, from the same release, must be beside it." >&2; return 1; }
  line=$(<"$sums")
  [[ $line =~ ^([0-9a-f]{64})\ [\ *]([^[:space:]/]+)$ ]] || { echo "$name.sha256 is not a SHA-256 checksum file." >&2; return 1; }
  [[ ${BASH_REMATCH[2]} == "$name" ]] || { echo "$name.sha256 is the checksum of ${BASH_REMATCH[2]}, not of $name." >&2; return 1; }
  actual=$(sha256sum "$file" | cut -d' ' -f1)
  [[ $actual == "${BASH_REMATCH[1]}" ]] || { echo "$name does not match its checksum: it is damaged, or not the published release." >&2; return 1; }
}
fetch_release() {  # fetch_release BASE FILE DIR: FILE and FILE.sha256 from BASE, over HTTPS only, then verified
  local base=${1%/} file=$2 dir=$3 get=(curl -fsSL --proto =https --proto-redir =https --tlsv1.2 --retry 3)
  [[ $base == https://* ]] || { echo "Releases are downloaded over HTTPS only, and $base isn't an https:// address." >&2; return 1; }
  "${get[@]}" -o "$dir/$file" "$base/$file" || { echo "Could not download $base/$file" >&2; return 1; }
  "${get[@]}" -o "$dir/$file.sha256" "$base/$file.sha256" || { echo "Could not download the checksum, $base/$file.sha256." >&2; return 1; }
  verify_release "$dir/$file"
}
# --- end of release delivery

while [[ $# -gt 0 ]]; do
  case $1 in
    --domain) DOMAIN=${2:-}; shift 2 ;;
    --email) EMAIL=${2:-}; shift 2 ;;
    --no-domain) NO_DOMAIN=1; shift ;;
    --version) VERSION=${2:-}; shift 2 ;;
    --from) FROM=${2:-}; shift 2 ;;
    --port) PORT=${2:-}; shift 2 ;;
    --name) NAME=${2:-}; shift 2 ;;
    --no-https) HTTPS=0; shift ;;
    --update) UPDATE_ONLY=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "Unknown option: $1" ;;
  esac
done

[[ $EUID -eq 0 ]] || die "Run this as root, for example: curl -fsSL … | sudo bash -s -- --domain grove.example.com"
# Read in a subshell: os-release defines VERSION, which would replace --version.
case "$( [[ -r /etc/os-release ]] && . /etc/os-release; echo "${ID:-}:${ID_LIKE:-}")" in
  ubuntu:*|debian:*|*:*debian*) ;;
  *) die "This installer supports Ubuntu and Debian. See deploy/README.md to install by hand." ;;
esac

if [[ -n $NAME ]]; then
  # Becomes the system user grove-NAME, which may be at most 32 characters.
  [[ $NAME =~ ^[a-z][a-z0-9-]{0,22}[a-z0-9]$ ]] || die "--name must be 2 to 24 lowercase letters, digits and dashes, starting with a letter."
  DATA=/var/lib/arynwood-groves/$NAME CONFIG_DIR=/etc/arynwood-groves ENV_FILE=/etc/arynwood-groves/$NAME.env
  SERVICE=arynwood-grove@$NAME SITE_NAME=arynwood-grove-$NAME RUN_USER=grove-$NAME CURRENT=$PREFIX/groves/$NAME UNITS=@$NAME
  CLI=(arynwood-grove --grove "$NAME")
else
  DATA=/var/lib/arynwood-grove CONFIG_DIR=/etc/arynwood-grove ENV_FILE=/etc/arynwood-grove/grove.env
  SERVICE=arynwood-grove SITE_NAME=arynwood-grove RUN_USER=grove CURRENT=$PREFIX/current UNITS=""
  CLI=(arynwood-grove)
fi
SITE=/etc/nginx/sites-available/$SITE_NAME

# An existing Grove keeps its address, port and setup code.
if [[ -f $ENV_FILE ]]; then
  existing=$(env_value GROVE_PUBLIC_URL); existing=${existing#*://}; existing=${existing%%/*}
  [[ -z $DOMAIN && -n $existing ]] && DOMAIN=${existing%%:*}
  [[ -n $(env_value GROVE_PORT) ]] && PORT=$(env_value GROVE_PORT)
  NEW_GROVE=0
  # Set up already (published, and with a certificate unless it runs without HTTPS): only update.
  if [[ -f $SITE ]] && { [[ $(env_value GROVE_PUBLIC_URL) == http://* ]] || [[ -d /etc/letsencrypt/live/$DOMAIN ]]; }; then UPDATE_ONLY=1; fi
else
  NEW_GROVE=1
fi
# Ports other Groves have, and ports anything on this server listens on.
taken_ports() { { sed -n 's/^GROVE_PORT=//p' /etc/arynwood-grove/grove.env /etc/arynwood-groves/*.env 2>/dev/null; ss -Hltn 2>/dev/null | awk '{print $4}' | sed 's/.*://'; } | sort -u; }
if [[ -z $PORT ]]; then
  if [[ -n $NAME ]]; then PORT=8100; while taken_ports | grep -qx "$PORT"; do PORT=$((PORT + 1)); done
  else PORT=8018; fi
fi
[[ $PORT =~ ^[0-9]+$ ]] && (( PORT > 0 && PORT < 65536 )) || die "--port must be a number between 1 and 65535."
[[ $NEW_GROVE == 0 ]] || ! taken_ports | grep -qx "$PORT" || die "Port $PORT is already in use on this server. Choose another with --port."

public_ipv4() {
  local ip
  ip=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1)
  case $ip in 10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*|100.6[4-9].*|100.[7-9][0-9].*|100.1[01][0-9].*|100.12[0-7].*|"") return 1 ;; esac
  printf '%s' "$ip"
}

if [[ $UPDATE_ONLY == 0 ]]; then
  if [[ -z $DOMAIN && $NO_DOMAIN == 0 ]]; then
    ask DOMAIN "Web address for your Grove (e.g. grove.example.com), or press Enter to use a temporary one:"
    [[ -z $DOMAIN ]] && NO_DOMAIN=1
  fi
  if [[ $NO_DOMAIN == 1 && -z $DOMAIN ]]; then
    ip=$(public_ipv4) || die "Could not find this server's public IPv4 address. Use --domain instead."
    DOMAIN="${ip//./-}.sslip.io"
    warn "Using the temporary address $DOMAIN (a free service, sslip.io, maps it to $ip). Use your own domain for anything lasting."
  fi
  DOMAIN=${DOMAIN,,}; DOMAIN=${DOMAIN#http://}; DOMAIN=${DOMAIN#https://}; DOMAIN=${DOMAIN%%/*}
  [[ $DOMAIN =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || die "\"$DOMAIN\" is not a web address like grove.example.com."
  if [[ $HTTPS == 1 && -z $EMAIL ]]; then
    ask EMAIL "Email for certificate notices (optional, press Enter to skip):"
  fi
fi

# Before anything on this server changes: get the release and check it against its checksum.
say "Fetching Arynwood Grove (${FROM:-$VERSION})"
work=$(mktemp -d); staging="" reuse=0
trap 'rm -rf "$work"; [[ -n $staging ]] && rm -rf "$staging"' EXIT
if [[ -n $FROM && -d $FROM && $(readlink -f "$FROM") == "$PREFIX/releases/"* && -x $FROM/.venv/bin/python ]]; then
  # A release already on this server (arynwood-grove create): checked when it was installed, used as it is.
  reuse=1
elif [[ -n $FROM && -d $FROM ]]; then
  warn "Installing the folder $FROM as it is: a folder has no checksum to check it against."
  cp -a "$FROM" "$work/src"
elif [[ -n $FROM ]]; then
  verify_release "$FROM" || die "Nothing was installed."
  mkdir "$work/src"; tar -xzf "$FROM" -C "$work/src" --strip-components=1
else
  # GROVE_RELEASE_BASE points at a mirror or a test server instead of GitHub (https:// only).
  # A server that got this script some other way may not have curl yet (the distribution's own, signed package).
  command -v curl >/dev/null || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates >/dev/null; } \
    || die "Could not install curl, which downloads the release."
  if [[ $VERSION == latest ]]; then base=${GROVE_RELEASE_BASE:-https://github.com/$REPO/releases/latest/download}; file=arynwood-grove.tar.gz
  else base=${GROVE_RELEASE_BASE:-https://github.com/$REPO/releases/download/v${VERSION#v}}; file="arynwood-grove-${VERSION#v}.tar.gz"; fi
  fetch_release "$base" "$file" "$work" || die "Nothing was installed."
  mkdir "$work/src"; tar -xzf "$work/$file" -C "$work/src" --strip-components=1
fi

say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
packages=(python3 python3-venv curl ca-certificates tar)
[[ $UPDATE_ONLY == 0 ]] && packages+=(nginx)
[[ $UPDATE_ONLY == 0 && $HTTPS == 1 ]] && packages+=(certbot python3-certbot-nginx)
apt-get install -y -qq "${packages[@]}" >/dev/null
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10 or newer is required (this system has $(python3 --version))."

id "$RUN_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$RUN_USER"
install -d -m 0755 "$PREFIX" "$PREFIX/releases"
[[ -n $NAME ]] && install -d -m 0755 "$PREFIX/groves" /var/lib/arynwood-groves "$CONFIG_DIR"
install -d -m 0750 -o "$RUN_USER" -g "$RUN_USER" "$DATA" "$DATA/config" "$DATA/requests"
[[ -n $NAME ]] || install -d -m 0750 -o root -g grove "$CONFIG_DIR"

# Releases are shared: the folders every Grove's current release link points at.
in_use() { for link in "$PREFIX/current" "$PREFIX"/groves/*; do [[ -L $link ]] && readlink -f "$link"; done | sort -u; }
others_use() { for link in "$PREFIX/current" "$PREFIX"/groves/*; do [[ -L $link && $link != "$CURRENT" && $(readlink -f "$link") == "$1" ]] && return 0; done; return 1; }
# The management command comes from the newest release, so rolling one Grove back never
# takes away commands the others need.
install_cli() {
  local newest; newest=$(ls -1 "$PREFIX/releases" | grep -vE '\.(new|old)$' | sort -V | tail -n1)
  install -m 0755 "$PREFIX/releases/$newest/deploy/arynwood-grove" /usr/local/bin/arynwood-grove
}

if [[ $reuse == 1 ]]; then release=$(basename "$(readlink -f "$FROM")")
else
  [[ -f $work/src/backend/api.py && -f $work/src/frontend/dist/index.html ]] || die "That is not a Grove release (no backend/ or built frontend/dist/)."
  release=$(cat "$work/src/VERSION" 2>/dev/null || sed -n "s/^VERSION = '\(.*\)'/\1/p" "$work/src/backend/community/store.py")
fi
target="$PREFIX/releases/$release"
previous=""; [[ -L $CURRENT ]] && previous=$(readlink -f "$CURRENT")
[[ $release =~ ^[0-9A-Za-z][0-9A-Za-z.+-]*$ && $release != *.new && $release != *.old ]] || die "Release version \"$release\" is not valid."
# Another Grove already runs this release: share it rather than replace it under them.
if [[ $reuse == 0 && -x $target/.venv/bin/python ]] && others_use "$target"; then reuse=1; fi

if [[ $reuse == 1 ]]; then say "Using release $release, already on this server"
else
say "Preparing release $release"
staging="$target.new"
rm -rf "$staging"; mv "$work/src" "$staging"
python3 -m venv "$staging/.venv"
"$staging/.venv/bin/pip" install -q --disable-pip-version-check -r "$staging/requirements.txt" \
  || die "Could not install the Python packages release $release needs. Nothing was changed."
"$staging/.venv/bin/python" -m compileall -q "$staging/backend" "$staging/deploy" >/dev/null \
  || die "Release $release is damaged: its code does not compile. Nothing was changed."
# The program folder is read-only to the service; its few writable files live with the data.
# Only the server's own Grove (no --name) uses them: other Groves have no host tools.
rm -rf "$target.new/config" "$target.new/data"
ln -s /var/lib/arynwood-grove/config "$target.new/config"
chown -R root:root "$target.new"; chmod -R u+rwX,go=rX "$target.new"
if [[ $target == "$previous" ]]; then rm -rf "$target.old"; mv "$target" "$target.old"; previous="$target.old"; fi
rm -rf "$target"; mv "$staging" "$target"; staging=""
fi

# From here on, any failure puts the previous release back before exiting.
undo_switch() {
  [[ -n $previous && -d $previous ]] || return 0
  if [[ $previous == "$target.old" ]]; then rm -rf "$target"; mv "$previous" "$target"; previous="$target"; fi
  ln -sfn "$previous" "$CURRENT.new" && mv -T "$CURRENT.new" "$CURRENT"
  if [[ $previous != "$target" && $reuse == 0 ]] && ! others_use "$target"; then rm -rf "$target"; fi
  install_cli
  systemctl daemon-reload; systemctl restart "$SERVICE" || true
}
trap 'status=$?; trap - ERR; warn "Installing release $release failed. Going back to the release that was running."; undo_switch; exit $status' ERR

if [[ ! -f $ENV_FILE ]]; then
  say "Writing settings to $ENV_FILE"
  scheme=https; [[ $HTTPS == 0 ]] && scheme=http
  code=$(python3 -c 'import secrets; print("-".join(secrets.token_hex(3) for _ in range(4)))')
  named_settings=""
  if [[ -n $NAME ]]; then named_settings=$'# Mail and IRC belong to the server\'s own Grove.\nGROVE_HOST_TOOLS=off'; fi
  umask 027
  cat >"$ENV_FILE" <<ENV
# Arynwood Grove settings. Restart after editing: sudo systemctl restart $SERVICE
GROVE_PUBLIC_URL=$scheme://$DOMAIN
GROVE_DATA_DIR=$DATA
GROVE_PORT=$PORT
# The host can move the Grove to their own domain from Settings; DNS instructions name this IP.
GROVE_DOMAIN_HELPER=1
GROVE_SERVER_IP=$(public_ipv4 || true)
# Needed once, to create the host account. Show it again: sudo arynwood-grove setup-link
GROVE_SETUP_CODE=$code
$named_settings
# Optional host mailbox for the Mail page:
# MAIL_IMAP_HOST=  MAIL_IMAP_PORT=993  MAIL_IMAP_USER=  MAIL_IMAP_PASS=
# MAIL_SMTP_HOST=  MAIL_SMTP_PORT=587  MAIL_SMTP_USER=  MAIL_SMTP_PASS=  MAIL_FROM=
# Running it for someone else? Hide the host's Mail and IRC, and email wishes to you:
# GROVE_HOST_TOOLS=off  GROVE_WISH_EMAIL=
# Room for each space's files, and the largest single file, in MB:
# GROVE_SPACE_STORAGE_MB=10240  GROVE_FILE_MAX_MB=2048
ENV
  umask 022
  chown "root:$RUN_USER" "$ENV_FILE"; chmod 0640 "$ENV_FILE"
fi

install_cli
install -m 0644 "$target"/deploy/arynwood-grove{,@}.service "$target"/deploy/arynwood-grove-backup{,@}.{service,timer} \
  "$target"/deploy/arynwood-grove-domain{,@}.{path,service} "$target"/deploy/arynwood-grove-offsite.{service,timer} /etc/systemd/system/
# Settings written by an older installer gain the address helper.
grep -q '^GROVE_DOMAIN_HELPER=' "$ENV_FILE" || printf 'GROVE_DOMAIN_HELPER=1\nGROVE_SERVER_IP=%s\n' "$(public_ipv4 || true)" >>"$ENV_FILE"
systemctl daemon-reload

# Keep a copy of everyone's data before switching programs.
if [[ -n $previous ]]; then "${CLI[@]}" backup >/dev/null || warn "The pre-update backup failed."; fi
ln -sfn "$target" "$CURRENT.new" && mv -T "$CURRENT.new" "$CURRENT"
systemctl enable -q "$SERVICE" "arynwood-grove-backup$UNITS.timer" "arynwood-grove-domain$UNITS.path"
systemctl restart "$SERVICE"; systemctl start "arynwood-grove-backup$UNITS.timer" "arynwood-grove-domain$UNITS.path"

healthy() {
  for _ in $(seq 1 30); do
    curl -fsS -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}
if ! healthy; then
  if [[ -n $previous && -d $previous ]]; then
    warn "Release $release did not start. Going back to the previous release."
    trap - ERR
    undo_switch
    healthy && die "Release $release did not start, so the Grove is still running $(basename "$previous"). See: sudo journalctl -u $SERVICE -n 50"
  fi
  die "The Grove service did not start. See: sudo journalctl -u $SERVICE -n 50"
fi
trap - ERR
rm -rf "$PREFIX/releases/"*.old
# Keep the three newest releases for `arynwood-grove rollback`, and every release a Grove runs.
ls -1dt "$PREFIX/releases/"*/ 2>/dev/null | tail -n +4 | while read -r old; do
  in_use | grep -qx "$(readlink -f "$old")" || rm -rf "$old"
done

if [[ $UPDATE_ONLY == 1 ]]; then
  say "Arynwood Grove $release is running. Everyone's accounts and spaces were kept."
  exit 0
fi

say "Publishing $DOMAIN with nginx"
install -d -m 0755 /var/www/acme/.well-known/acme-challenge
sed -e "s/@DOMAIN@/$DOMAIN/g" -e "s/@PORT@/$PORT/g" "$target/deploy/nginx-grove.conf" >"$SITE"
ln -sfn "$SITE" "/etc/nginx/sites-enabled/$SITE_NAME"
nginx -t -q || die "nginx rejected the site configuration in $SITE."
systemctl enable -q --now nginx; systemctl reload nginx
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow 'Nginx Full' >/dev/null; fi

if [[ $HTTPS == 1 ]]; then
  # Check that the address really reaches this server before asking for a certificate.
  probe=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
  echo "$probe" >"/var/www/acme/.well-known/acme-challenge/grove-$probe"
  # nginx finishes reloading a moment after the command returns, so try for a few seconds.
  for _ in $(seq 1 10); do
    answer=$(curl -fsS -m 10 "http://$DOMAIN/.well-known/acme-challenge/grove-$probe" 2>/dev/null || true)
    [[ $answer == "$probe" ]] && break; sleep 1
  done
  rm -f "/var/www/acme/.well-known/acme-challenge/grove-$probe"
  if [[ $answer != "$probe" ]]; then
    ip=$(public_ipv4 || echo "this server's IP address")
    warn "http://$DOMAIN does not reach this server yet."
    echo "  Add a DNS record at your domain provider:  type A,  name ${DOMAIN%%.*},  value $ip"
    echo "  Make sure ports 80 and 443 are open in your VPS provider's firewall, then run this installer again."
    exit 1
  fi
  say "Getting a certificate from Let's Encrypt"
  if [[ -n $EMAIL ]]; then account=(-m "$EMAIL"); else account=(--register-unsafely-without-email); fi
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --redirect "${account[@]}" -q \
    || die "Certbot could not get a certificate. Check DNS and ports 80/443, then run this installer again."
fi

link=$("${CLI[@]}" setup-link | head -n1)
cat <<DONE

  Arynwood Grove $release is ready.

  1. Open this link to create your host account (it carries your setup code):
       $link
  2. Then use "Invite members" to send friends a link, or make a public invite link.

  Manage it with:  sudo ${CLI[*]} status | update | backup | logs | help

DONE
