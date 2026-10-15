# Arynwood Grove

**The Grove, your community – your choices.** Private community software for the people in your life: shared calendars, plans, boards, chat, household tasks, lists and notes, on a server you control. Version 0.5.2. Formerly Arynwood Community; a Community 0.3 install upgrades in place.

**Website:** [arynwood.com/community](https://arynwood.com/community/) · **Join Arynwood's Grove:** [community.arynwood.com](https://community.arynwood.com/) · **Hosting and setup:** [Arynwood setup services](https://arynwood.com/#services)

## Put a Grove on your server

You need a VPS running Ubuntu 22.04+ or Debian 12+, and ideally a domain name. Point the domain's DNS record (an `A` record, e.g. `grove` → your server's IP address) at the server, then run:

```bash
curl -fsSL https://github.com/Arynwood-Technology/arynwood-community/releases/latest/download/install.sh \
  | sudo bash -s -- --domain grove.example.com --email you@example.com
```

About two minutes later it prints a link. Open it and choose **Create your Grove** to make your host account; the link carries a one-time setup code, so nobody else can claim your Grove first. (The same page offers **Join a Grove**, for someone who was sent an invitation link to another Grove.)

### Make it your own domain

No domain yet? Install with `--no-domain`: the Grove starts on a temporary address based on the server's IP. When you have a domain, the host opens **People & identity → Your Grove's address**, types the domain, and the Grove shows the exact DNS record to add (type `A`, the name, and this server's IP). Once the record is in place, **Use** the domain: the server checks that it reaches itself, gets the HTTPS certificate, moves the Grove there, and forwards the old address to the new one. Everyone signs in again at the new address. From a terminal, `sudo arynwood-grove set-domain grove.example.com` does the same.

The installer sets up the service (as its own unprivileged user), nginx, a Let's Encrypt certificate, daily backups and the `arynwood-grove` command:

```bash
sudo arynwood-grove status         # running? version, address, last backup, certificate
sudo arynwood-grove update         # newest release; keeps every account, space and setting
sudo arynwood-grove rollback       # back to the previous release
sudo arynwood-grove recovery-code person@example.com   # someone forgot their password
sudo arynwood-grove help
```

Details, manual installation and troubleshooting: [deploy/README.md](deploy/README.md).

## Invite your people

Sign in, pick a space and choose **Invite members**:

- **Invitation link:** admits one person and expires after seven days. Send it privately.
- **Public invite link:** anyone who has it can join the space. Post it where your friends will see it, make a new one if it spreads too far, and turn it off when you are done. One address can open only a few accounts through it in 15 minutes.

Each person makes their own account on your Grove, from any computer or phone. Everyone in a space sees changes within about a second, without reloading.

## What a Grove has

- **Calendar and Overview:** a shared day planner, upcoming events, open tasks and recent posts.
- **Board, Space discussion, Tasks, Lists, Notes:** shared content with replies, assignments, due dates, private notes and search.
- **Spaces and people:** the first account is the host. Anyone can start more spaces. A space's owners rename it and give it a topic, invite and remove people, make other members owners, and can delete it for everyone; a space always keeps at least one owner. Members can leave.
- **Live updates:** a change by anyone reaches every open page in that space at once.
- **Host connections (host only):** Mail over IMAP/SMTP, IRC (irc.arynwood.com, `#general`, by default; change either in the IRC page), and Private messages over NKN.

## Upgrading from Arynwood Community 0.3

A Community 0.3 server upgrades in place: same folder, `.env`, database, systemd service and nginx site. Members stay signed in and existing invitation links keep working. As the account that owns the install:

```bash
bash upgrade-from-community.sh --dir ~/arynwood-community --from arynwood-grove-0.5.2.tar.gz --prepare-only
bash upgrade-from-community.sh --dir ~/arynwood-community --from arynwood-grove-0.5.2.tar.gz
```

The first run backs up, stages the new release and tests it against a copy of your data without touching the running service. The second switches over, with a few seconds of downtime, and prints the command to go back. The script is in `deploy/`. A server upgraded this way takes later releases the same way: run both commands again with the new release file.

## Run it on your own computer

For trying it out, or for a household on one machine. Requires Linux or macOS, Python 3.10+, Node.js 20.19+ or 22.12+, and npm.

```bash
./setup.sh                 # creates .venv, installs dependencies, builds the page, creates .env
./desktop/install.sh       # optional: adds Arynwood Grove to the app menu and desktop (Linux)
./start.sh                 # then open http://127.0.0.1:8018/community
```

For frontend development, keep the backend running and run `npm --prefix frontend run dev`, then open http://127.0.0.1:5174.

## Configuration

Settings live in `.env` (on a server installed with `install.sh`: `/etc/arynwood-grove/grove.env`). Community 0.3 names (`COMMUNITY_*`) are still read.

| Setting | Purpose |
|---|---|
| `GROVE_PUBLIC_URL` | The address members open, e.g. `https://grove.example.com`. Invite links use it; it is trusted as page origin and host name; cookies are `Secure` over HTTPS. |
| `GROVE_BIND`, `GROVE_PORT` | Listen address. Defaults to `127.0.0.1:8018`. |
| `GROVE_BRAND_NAME`, `GROVE_BRAND_TAGLINE` | Optional identity. A name enables the branded welcome page. |
| `GROVE_BRAND_SURFACE` | Optional dark base, `#rrggbb` with relative luminance at most 0.1. Enables a full theme; invalid or absent values keep today’s palette and accent validation. |
| `GROVE_BRAND_TEXT` | Optional light text, `#rrggbb` with relative luminance at least 0.5. Defaults to Grove’s light text; adjusted for readable contrast when a surface is set. |
| `GROVE_BRAND_ACCENT` | `#rrggbb`. With a surface, derives button and link variants by stepping HSL lightness to reach 4.5:1; borders reach 3:1. Without a surface, keeps the existing contrast check and teal fallback. |
| `GROVE_BRAND_SITE_URL`, `GROVE_BRAND_SITE_LABEL` | Website link and label (default: Website). HTTPS; HTTP allowed only on localhost or loopback. |
| `GROVE_BRAND_SHOP_URL`, `GROVE_BRAND_SHOP_LABEL` | Shop link and label (default: Shop), with the same URL rules. |
| `GROVE_BRAND_LOGO` | File inside the data directory: PNG, JPEG or WebP, at most 512 KB. Invalid files are ignored; branded Groves never show the Arynwood tree. |
| `GROVE_HOST_TOOLS` | `off` hides Mail, IRC and Private messages, which use the host’s own accounts, on a Grove run for someone else. Default `on`. |
| `GROVE_WISH_EMAIL` | Where wishes from the lamp are emailed, using the `MAIL_SMTP_*` settings. Without it, wishes are kept for owners and managers in Grove admin. |
| `GROVE_SPACE_STORAGE_MB`, `GROVE_FILE_MAX_MB` | Room for each space’s files (default 10240) and the largest single file (default 2048). Uploads also stop while the disk has under 2 GB free. |
| `GROVE_DATA_DIR` | Where the database and files live. Defaults to `data/`. |
| `GROVE_SETUP_CODE` | Set by the installer: required to create the host account. |
| `GROVE_ORIGIN`, `GROVE_HOSTS` | Extra page origins and host names to accept, comma-separated. |
| `MAIL_IMAP_*`, `MAIL_SMTP_*`, `MAIL_FROM` | The host's mailbox for Mail. |
| `NKN_IDENTIFIER`, `SOCKS5_PROXY` | Prefix for the Private messages address; optional SOCKS5 proxy for IRC. |

Keep the service on `127.0.0.1` behind an HTTPS reverse proxy. Do not expose it over plain HTTP.

For example, RogueFest’s navy, paper and pink palette:

```dotenv
GROVE_BRAND_SURFACE="#091C32"
GROVE_BRAND_TEXT="#F4EEE8"
GROVE_BRAND_ACCENT="#E2326F"
```

Full themes preserve hue and saturation, stepping lightness by 0.1% in either direction until the rounded colour passes. Button labels use white or the base surface, whichever contrasts better. Links pass on all three surfaces; muted text passes on the raised surface. `GET /api/brand` returns the derived CSS variables in `theme`; without a valid surface it returns an empty theme, preserving the original appearance.

## Your data

- Accounts, spaces and everything in them: `grove.sqlite3` in the data folder (`community.sqlite3` on an upgraded 0.3 install), readable by the service only. Servers keep 14 daily copies in `backups/`, and `arynwood-grove offsite` copies everything, files included, off the server each night (see deploy/README.md). Export a space as JSON from People & identity.
- Private messages identity: `nkn/wallet.json` (on an installed server, `nkn-wallet.json` in the data folder). Keep a private backup; losing it changes the address.
- In the browser: Private messages contacts and history, IRC settings, and your last-selected space.

## Checks

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
npm --prefix frontend run lint && npm --prefix frontend test && npm --prefix frontend run build
scripts/package.sh         # builds release/arynwood-grove-<version>.tar.gz
```

Tests use mocked mail, IRC and NKN services; they never contact live accounts.

## Security

- Passwords: PBKDF2-SHA256 (600,000 rounds). Sessions: HTTP-only, SameSite=Strict cookies, stored hashed.
- Sign-in, sign-up, password changes and public-link sign-ups are rate-limited. The host account needs the installer's setup code.
- Every state-changing request needs a custom header and an allowed `Origin`; WebSocket handshakes check the origin too.
- A strict Content Security Policy, with no third-party scripts, styles or fonts. Change notices carry no content: pages re-read through the normal permission checks.
- On a server, the service runs as its own user with a read-only program folder; only the data folder is writable.
- Mail, IRC and Private messages are for the host only. **On a public server the host reaches them from the public address**, so use a strong, unique host password.

## FAQ

**Where are my community's messages and plans stored?** On the server that runs your Grove, in one database file there. Members' browsers read and write it through that server; nothing is copied to Arynwood or anywhere else, and community.arynwood.com is a separate Grove with its own accounts.

**Do my friends need to install anything?** No. They open your invite link in a browser on any computer or phone and create an account on your Grove.

**What does it cost to run?** The software is free (AGPL-3.0). The service itself uses about 60 MB of memory when idle, so a small VPS plan is enough for a household or a circle of friends; you pay your domain and server providers directly.

## License and branding

Code: GNU AGPL-3.0 (see `LICENSE`). A running server offers its source at `/api/source`. The members' page includes styling adapted from Arynwood MCP, contributed under the same licence.

The Arynwood tree logo (`frontend/public/arynwood-tree.png`, `icon.png`, `favicon-32.png`, `favicon.svg`, `desktop/arynwood-community.png`) is artwork by Lorelei Noble (Arynwood Technology). All rights reserved. It is not covered by any licence that applies to the code.
