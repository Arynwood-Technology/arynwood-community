# Arynwood Community

Private community software for messages, plans, household work, lists, notes, and host connections. Version 0.3.0.

**Website:** [arynwood.com/community](https://arynwood.com/community/) · **Try it:** [community.arynwood.com](https://community.arynwood.com/) · **Hosting and setup:** [Arynwood setup services](https://arynwood.com/#services)

- **Today:** a shared home screen for open tasks, upcoming events, and board posts.
- **Boards, Chat, Calendar, Household, Lists, Notes:** shared-space content with replies, assignments, due dates, private notes, and search.
- **Accounts and spaces:** the first account becomes the host and creates the first space. Space owners invite people with single-use links that expire after seven days. Anyone can start more spaces, and members can leave a space.
- **Settings:** people in the space, invites, password changes, JSON export, and host connection status.
- **Mail, IRC, Message:** host-only connections that run on the host's computer.

The connections:

- **Mail:** reads the inbox over IMAP, or from local Thunderbird mailboxes. You can write and reply in the app over SMTP, or open Thunderbird instead.
- **IRC:** channels, direct messages, NickServ login, user lists and slash commands.
- **Message:** private, direct peer-to-peer messages with contacts and groups, text and images, delivery receipts, and a portable identity. Message stays online while you use other pages.

## Install

Requires Linux or macOS, Python 3.10+, Node.js 20.19+ or 22.12+, and npm. Thunderbird is optional.

```bash
cd communication-hub
./setup.sh                 # creates .venv, installs dependencies, builds the app, creates .env
./desktop/install.sh       # optional: adds Arynwood Community to the app menu and desktop (Linux)
```

Start it from the desktop icon, or run `./start.sh` and open http://127.0.0.1:8018. The desktop launcher starts the server in the background if needed and opens the app in its own window. Right-click the icon and choose **Stop Arynwood Community** to stop the server, or run `desktop/arynwood-community --stop`. Server logs go to `data/logs/server.log`.

For frontend development, keep the backend running and run `npm --prefix frontend run dev`, then open http://127.0.0.1:5174. Vite proxies HTTP and WebSockets to port 8018.

## Configuration

Settings live in `.env`. Setup creates it from `.env.example` and makes it readable by your user only.

| Setting | Purpose |
|---|---|
| `MAIL_IMAP_*`, `MAIL_SMTP_*`, `MAIL_FROM` | Mail reading and sending. SMTP falls back to the IMAP host and login. |
| `COMMUNITY_BIND`, `COMMUNITY_PORT` | Listen address. Defaults to `127.0.0.1:8018`. |
| `COMMUNITY_ORIGIN`, `COMMUNITY_HOSTS`, `COMMUNITY_SECURE_COOKIE` | Settings for a hosted install behind an HTTPS reverse proxy. |
| `COMMUNITY_DATA_DIR` | Where the database lives. Defaults to `data/`. |
| `NKN_IDENTIFIER`, `SOCKS5_PROXY` | Prefix for your Message address; optional SOCKS5 proxy for IRC. |

**Sharing with other people.** By default the app only accepts connections from this computer, so invite links only work here. To let other people join, put it behind an HTTPS reverse proxy (for example Caddy or nginx) on a domain. Set `COMMUNITY_ORIGIN=https://your.domain`, `COMMUNITY_HOSTS=your.domain` and `COMMUNITY_SECURE_COOKIE=1`, and keep `COMMUNITY_BIND=127.0.0.1` so that only the proxy can reach it. Do not expose the app over plain HTTP.

## Your data

- Community records: `data/community.sqlite3` (readable by your user only). Back this file up. Export a space as JSON from Settings.
- Message identity: `nkn/wallet.json`, created the first time you go online (readable by your user only). Keep a private backup; losing it changes your Message address.
- In the browser: Message contacts and history, IRC connection settings (including a saved NickServ password), and your last-selected space. Clearing browser storage removes them. Message history keeps the latest 500 messages per conversation; if browser storage fills up, images are dropped from the saved history but text is kept.

`.env`, `data/`, and the wallet are git-ignored. The folder can be moved or copied; it does not depend on ArynCore.

## Checks

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests     # 21 backend tests
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend audit && npm --prefix nkn audit   # nkn/ is the Message network bridge
```

Tests use mocked mail, IRC and Message services; they never contact live accounts.

## Security

- Passwords: PBKDF2-SHA256 (600,000 rounds). Sessions: HTTP-only, SameSite=Strict cookies, stored hashed.
- Changing your password signs out your other sessions.
- Sign-in, sign-up and password changes are rate-limited.
- Every state-changing request needs a custom header and a same-origin `Origin`; WebSocket handshakes check the origin too.
- A strict Content Security Policy is in place, with no third-party scripts, styles or fonts.
- Mail, IRC and Message endpoints are for the host only. IRC input cannot inject extra IRC commands. Mail headers are validated. Images received in Message are only displayed if they are inline PNG, JPEG, GIF or WebP.

## Branding

The Arynwood tree logo (`frontend/public/arynwood-logo.png`, `favicon.png`, `apple-touch-icon.png`, `desktop/arynwood-community.png`) is artwork by Lorelei Noble (Arynwood Technology). All rights reserved. It is not covered by any licence that applies to the code.
