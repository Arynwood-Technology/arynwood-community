#!/usr/bin/env bash
# Arynwood Grove server installer, for Ubuntu 22.04+ or Debian 12+ on a VPS.
#
#   curl -fsSL https://github.com/Arynwood-Technology/arynwood-community/releases/latest/download/install.sh \
#     | sudo bash -s -- --domain grove.example.com --email you@example.com
#
# Run it again (or `sudo arynwood-grove update`) to update: settings, accounts and spaces are kept.
set -euo pipefail

REPO="Arynwood-Technology/arynwood-community"
PREFIX=/opt/arynwood-grove
DATA=/var/lib/arynwood-grove
CONFIG_DIR=/etc/arynwood-grove
ENV_FILE=$CONFIG_DIR/grove.env
SERVICE=arynwood-grove
SITE=/etc/nginx/sites-available/arynwood-grove

DOMAIN="" EMAIL="" FROM="" VERSION=latest PORT=8018 HTTPS=1 NO_DOMAIN=0 ASSUME_YES=0 UPDATE_ONLY=0

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
  --port N          Local port the service listens on (default 8018).
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

while [[ $# -gt 0 ]]; do
  case $1 in
    --domain) DOMAIN=${2:-}; shift 2 ;;
    --email) EMAIL=${2:-}; shift 2 ;;
    --no-domain) NO_DOMAIN=1; shift ;;
    --version) VERSION=${2:-}; shift 2 ;;
    --from) FROM=${2:-}; shift 2 ;;
    --port) PORT=${2:-}; shift 2 ;;
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
[[ $PORT =~ ^[0-9]+$ ]] && (( PORT > 0 && PORT < 65536 )) || die "--port must be a number between 1 and 65535."

# An existing Grove keeps its address, port and setup code.
if [[ -f $ENV_FILE ]]; then
  existing=$(env_value GROVE_PUBLIC_URL); existing=${existing#*://}; existing=${existing%%/*}
  [[ -z $DOMAIN && -n $existing ]] && DOMAIN=${existing%%:*}
  [[ -n $(env_value GROVE_PORT) ]] && PORT=$(env_value GROVE_PORT)
  # Set up already (published, and with a certificate unless it runs without HTTPS): only update.
  if [[ -f $SITE ]] && { [[ $(env_value GROVE_PUBLIC_URL) == http://* ]] || [[ -d /etc/letsencrypt/live/$DOMAIN ]]; }; then UPDATE_ONLY=1; fi
fi

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

say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
packages=(python3 python3-venv curl ca-certificates tar)
[[ $UPDATE_ONLY == 0 ]] && packages+=(nginx)
[[ $UPDATE_ONLY == 0 && $HTTPS == 1 ]] && packages+=(certbot python3-certbot-nginx)
apt-get install -y -qq "${packages[@]}" >/dev/null
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10 or newer is required (this system has $(python3 --version))."

id grove >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin grove
install -d -m 0755 "$PREFIX" "$PREFIX/releases"
install -d -m 0750 -o grove -g grove "$DATA" "$DATA/config" "$DATA/requests"
install -d -m 0750 -o root -g grove "$CONFIG_DIR"

say "Fetching Arynwood Grove (${FROM:-$VERSION})"
work=$(mktemp -d); staging=""
trap 'rm -rf "$work"; [[ -n $staging ]] && rm -rf "$staging"' EXIT
if [[ -n $FROM ]]; then
  if [[ -d $FROM ]]; then cp -a "$FROM" "$work/src"
  else mkdir "$work/src"; tar -xzf "$FROM" -C "$work/src" --strip-components=1; fi
else
  # GROVE_RELEASE_BASE points at a mirror or a test server instead of GitHub.
  if [[ $VERSION == latest ]]; then base=${GROVE_RELEASE_BASE:-https://github.com/$REPO/releases/latest/download}; file=arynwood-grove.tar.gz
  else base=${GROVE_RELEASE_BASE:-https://github.com/$REPO/releases/download/v${VERSION#v}}; file="arynwood-grove-${VERSION#v}.tar.gz"; fi
  curl -fsSL --retry 3 -o "$work/$file" "$base/$file" || die "Could not download $base/$file"
  curl -fsSL --retry 3 -o "$work/$file.sha256" "$base/$file.sha256" || die "Could not download the checksum for $file"
  (cd "$work" && echo "$(cut -d' ' -f1 "$file.sha256")  $file" | sha256sum -c --quiet) || die "The download is damaged (checksum mismatch). Try again."
  mkdir "$work/src"; tar -xzf "$work/$file" -C "$work/src" --strip-components=1
fi
[[ -f $work/src/backend/api.py && -f $work/src/frontend/dist/index.html ]] || die "That is not a Grove release (no backend/ or built frontend/dist/)."
release=$(cat "$work/src/VERSION" 2>/dev/null || sed -n "s/^VERSION = '\(.*\)'/\1/p" "$work/src/backend/community/store.py")
target="$PREFIX/releases/$release"
previous=""; [[ -L $PREFIX/current ]] && previous=$(readlink -f "$PREFIX/current")

say "Preparing release $release"
[[ $release =~ ^[0-9A-Za-z][0-9A-Za-z.+-]*$ && $release != *.new && $release != *.old ]] || die "Release version \"$release\" is not valid."
staging="$target.new"
rm -rf "$staging"; mv "$work/src" "$staging"
python3 -m venv "$staging/.venv"
"$staging/.venv/bin/pip" install -q --disable-pip-version-check -r "$staging/requirements.txt" \
  || die "Could not install the Python packages release $release needs. Nothing was changed."
"$staging/.venv/bin/python" -m compileall -q "$staging/backend" "$staging/deploy" >/dev/null \
  || die "Release $release is damaged: its code does not compile. Nothing was changed."
# The program folder is read-only to the service; its few writable files live with the data.
rm -rf "$target.new/config" "$target.new/data"
ln -s "$DATA/config" "$target.new/config"
mkdir -p "$target.new/nkn"; ln -sfn "$DATA/nkn-wallet.json" "$target.new/nkn/wallet.json"
chown -R root:root "$target.new"; chmod -R go-w "$target.new"
if [[ $target == "$previous" ]]; then rm -rf "$target.old"; mv "$target" "$target.old"; previous="$target.old"; fi
rm -rf "$target"; mv "$staging" "$target"; staging=""

# From here on, any failure puts the previous release back before exiting.
undo_switch() {
  [[ -n $previous && -d $previous ]] || return 0
  if [[ $previous == "$target.old" ]]; then rm -rf "$target"; mv "$previous" "$target"; previous="$target"; fi
  ln -sfn "$previous" "$PREFIX/current.new" && mv -T "$PREFIX/current.new" "$PREFIX/current"
  if [[ $previous != "$target" ]]; then rm -rf "$target"; fi
  install -m 0755 "$previous/deploy/arynwood-grove" /usr/local/bin/arynwood-grove
  systemctl daemon-reload; systemctl restart "$SERVICE" || true
}
trap 'status=$?; trap - ERR; warn "Installing release $release failed. Going back to the release that was running."; undo_switch; exit $status' ERR

if [[ ! -f $ENV_FILE ]]; then
  say "Writing settings to $ENV_FILE"
  scheme=https; [[ $HTTPS == 0 ]] && scheme=http
  code=$(python3 -c 'import secrets; print("-".join(secrets.token_hex(3) for _ in range(4)))')
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
# Optional host mailbox for the Mail page:
# MAIL_IMAP_HOST=  MAIL_IMAP_PORT=993  MAIL_IMAP_USER=  MAIL_IMAP_PASS=
# MAIL_SMTP_HOST=  MAIL_SMTP_PORT=587  MAIL_SMTP_USER=  MAIL_SMTP_PASS=  MAIL_FROM=
# Running it for someone else? Hide the host's Mail, IRC and Private messages, and email wishes to you:
# GROVE_HOST_TOOLS=off  GROVE_WISH_EMAIL=
# Room for each space's files, and the largest single file, in MB:
# GROVE_SPACE_STORAGE_MB=10240  GROVE_FILE_MAX_MB=2048
ENV
  umask 022
  chown root:grove "$ENV_FILE"; chmod 0640 "$ENV_FILE"
fi

install -m 0755 "$target/deploy/arynwood-grove" /usr/local/bin/arynwood-grove
install -m 0644 "$target/deploy/arynwood-grove.service" "$target/deploy/arynwood-grove-backup.service" "$target/deploy/arynwood-grove-backup.timer" \
  "$target/deploy/arynwood-grove-domain.path" "$target/deploy/arynwood-grove-domain.service" /etc/systemd/system/
# Settings written by an older installer gain the address helper.
grep -q '^GROVE_DOMAIN_HELPER=' "$ENV_FILE" || printf 'GROVE_DOMAIN_HELPER=1\nGROVE_SERVER_IP=%s\n' "$(public_ipv4 || true)" >>"$ENV_FILE"
systemctl daemon-reload

# Keep a copy of everyone's data before switching programs.
if [[ -n $previous && -x /usr/local/bin/arynwood-grove ]]; then arynwood-grove backup >/dev/null || warn "The pre-update backup failed."; fi
ln -sfn "$target" "$PREFIX/current.new" && mv -T "$PREFIX/current.new" "$PREFIX/current"
systemctl enable -q "$SERVICE" arynwood-grove-backup.timer arynwood-grove-domain.path
systemctl restart "$SERVICE"; systemctl start arynwood-grove-backup.timer arynwood-grove-domain.path

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
# Keep the three newest releases for `arynwood-grove rollback`.
ls -1dt "$PREFIX/releases/"*/ 2>/dev/null | tail -n +4 | while read -r old; do
  if [[ $(readlink -f "$old") != "$(readlink -f "$PREFIX/current")" ]]; then rm -rf "$old"; fi
done

if [[ $UPDATE_ONLY == 1 ]]; then
  say "Arynwood Grove $release is running. Everyone's accounts and spaces were kept."
  exit 0
fi

say "Publishing $DOMAIN with nginx"
install -d -m 0755 /var/www/acme/.well-known/acme-challenge
sed -e "s/@DOMAIN@/$DOMAIN/g" -e "s/@PORT@/$PORT/g" "$target/deploy/nginx-grove.conf" >"$SITE"
ln -sfn "$SITE" /etc/nginx/sites-enabled/arynwood-grove
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

link=$(arynwood-grove setup-link | head -n1)
cat <<DONE

  Arynwood Grove $release is ready.

  1. Open this link to create your host account (it carries your setup code):
       $link
  2. Then use "Invite members" to send friends a link, or make a public invite link.

  Manage it with:  sudo arynwood-grove status | update | backup | logs | help

DONE
