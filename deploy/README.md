# Running a Grove on a server

On a server, the Grove is the one place everyone's spaces live. Each member opens its address in a browser, from any computer, and signs in with their own account. Nothing is copied between machines: when anyone adds an event, task, post or message, the server tells every open page in that space and they refresh within about a second.

```
member's browser ─┐
member's browser ─┼─ https://grove.example.com ─ nginx ─ 127.0.0.1:8018  Grove service (user "grove")
host's browser   ─┘                                                     └ /var/lib/arynwood-grove
```

## With the installer (Ubuntu 22.04+ or Debian 12+)

1. Rent a VPS and note its IP address. Any size works: the service uses about 60 MB of memory when idle.
2. At your domain provider, add an `A` record pointing a name (e.g. `grove.example.com`) at that IP. Make sure ports 80 and 443 are open in the VPS provider's firewall.
3. On the server:

   ```bash
   curl -fsSL https://github.com/Arynwood-Technology/arynwood-community/releases/latest/download/install.sh \
     | sudo bash -s -- --domain grove.example.com --email you@example.com
   ```

4. Open the link it prints and choose **Create your Grove**. The link carries a one-time setup code; `sudo arynwood-grove setup-link` shows it again.

No domain yet? Use `--no-domain` in step 3 and skip step 2. Later, in **People & identity → Your Grove's address**, the host enters the domain, sees the DNS record to add, and switches; or run `sudo arynwood-grove set-domain grove.example.com`.

Options: `--no-domain` (a temporary `<ip>.sslip.io` address, for trying it out), `--version X.Y.Z`, `--from release.tar.gz` (offline install), `--port N`, `--yes`. Run with `--help` for all of them. If the domain does not reach the server yet, the installer says which DNS record to add and stops before asking for a certificate; run it again once DNS has updated.

What it sets up:

| Where | What |
|---|---|
| `/opt/arynwood-grove/releases/<version>`, `current` | The program, read-only to the service. The three newest releases are kept for rollback. |
| `/var/lib/arynwood-grove` | The database, daily backups (`backups/`, 14 kept), IRC settings and the Private messages identity. Only the `grove` user can read it. |
| `/etc/arynwood-grove/grove.env` | Settings (address, port, setup code, optional mailbox). Readable by root and the service. |
| `arynwood-grove.service`, `arynwood-grove-backup.timer` | The service, hardened with `ProtectSystem=strict`, and the daily backup. |
| `/etc/nginx/sites-available/arynwood-grove` | The site, with HTTPS added by Certbot. |
| `/usr/local/bin/arynwood-grove` | The management command (below). |
| `arynwood-grove-domain.path`, `.service` | When the host asks for a new address in Settings, the service writes `requests/domain.json`; this root helper re-checks the name, publishes it with nginx and Certbot, and writes back the result. The service itself never runs anything as root. |

Releases are downloaded from GitHub and checked against their published SHA-256 checksum before anything changes.

## Managing it

```bash
sudo arynwood-grove status                   # service, version, address, data, last backup, certificate
sudo arynwood-grove update                   # newest release; a backup is taken first
sudo arynwood-grove update --version 0.5.1   # a particular release
sudo arynwood-grove rollback                 # the previous release
sudo arynwood-grove backup                   # a copy now (one is made every day)
sudo arynwood-grove restore /var/lib/arynwood-grove/backups/grove-….sqlite3
sudo arynwood-grove recovery-code person@example.com   # 15-minute password reset code
sudo arynwood-grove logs
sudo arynwood-grove set-domain grove.example.com --email you@example.com   # move to your own domain
```

**Moving to another domain** (`set-domain`, or the host's Settings page) checks that `http://<domain>` reaches this server, gets a certificate, saves the new address, restarts the service, and keeps the old address as a redirect. If the check or the certificate fails, nothing changes.

An update that fails to start is undone automatically: the previous release keeps running and the command says so. Open pages reconnect by themselves after an update.

**Password recovery is host-only.** There is no reset email. When someone forgets their password, run `recovery-code` with their email and give them the code privately; they enter it under "Forgot password?".

**Back up off the server too.** Daily copies protect against mistakes, not against losing the server. Copy `/var/lib/arynwood-grove/backups/`, `/var/lib/arynwood-grove/files/` (everyone's uploaded files; the daily copy holds only the database) and `/etc/arynwood-grove/grove.env` somewhere else now and then, and test a restore once.

## Several Groves on one server

One server can run many Groves: one for your friends, one for a festival, one for a club. Each is a separate service with its own system user, data, settings, address and port, so one Grove can't read another's data or use up the server's memory. They share the program: one copy of each release, however many Groves run it.

```bash
sudo arynwood-grove create roguefest --domain roguefest.example.com --email you@example.com
sudo arynwood-grove list                               # every Grove: state, version, port, data, address
sudo arynwood-grove --grove roguefest status           # any command above, for that Grove
sudo arynwood-grove --grove roguefest setup-link
sudo arynwood-grove backup --all
sudo arynwood-grove update --all --canary roguefest    # roguefest first; the rest only if it runs
```

`create` uses the newest release on the server; on a new server, install the first one with `install.sh --name NAME --domain …`. Without `--grove`, commands act on the Grove installed without a name, if there is one.

| For a Grove named `NAME` | |
|---|---|
| `/var/lib/arynwood-groves/NAME` | Its data and backups, readable only by the system user `grove-NAME`. |
| `/etc/arynwood-groves/NAME.env` | Its settings. The port is the first free one from 8100. |
| `/opt/arynwood-grove/groves/NAME` | Link to the release it runs. A release is kept while any Grove runs it. |
| `arynwood-grove@NAME.service` | The service, limited to 768 MB of memory. Also `arynwood-grove-backup@NAME.timer` and `arynwood-grove-domain@NAME.path`. |
| `/etc/nginx/sites-available/arynwood-grove-NAME` | Its site. |

`update --all` downloads the release once and updates one Grove first: the one named by `--canary`, or the Grove without a name. If that Grove doesn't start on the new release, it goes back to its previous one and the others are left alone. Each Grove can also be updated or rolled back by itself.

Named Groves have `GROVE_HOST_TOOLS=off`: Mail, IRC and Private messages use the server owner's own accounts, so only the Grove without a name offers them.

## Upgrading a Community 0.3 server

`upgrade-from-community.sh` upgrades an existing Arynwood Community 0.3 install in place, keeping its folder, `.env`, database, IRC settings, NKN wallet, Python environment, systemd service and nginx site. Run it as the account that owns the install:

```bash
bash upgrade-from-community.sh --dir ~/arynwood-community --from arynwood-grove-0.5.1.tar.gz --prepare-only
bash upgrade-from-community.sh --dir ~/arynwood-community --from arynwood-grove-0.5.1.tar.gz
```

The first run backs up the database, `.env`, IRC settings and wallet, stages the release in `<dir>.next`, and starts it on a spare port against a copy of the data to prove it reads it. The service is not touched. The second run does the same, then stops the service (with `sudo`), moves the live data into the new release, starts it, and checks it. If the Grove does not start, it puts Community 0.3 back by itself. It prints the command to go back later.

Members stay signed in, and invitation links made in 0.3 keep working. `COMMUNITY_ORIGIN` (if it is an `https://` address) becomes the Grove's public address, so new invite links use it.

A server upgraded this way doesn't have the `arynwood-grove` command. It takes later releases the same way: download the new `arynwood-grove-<version>.tar.gz` from the releases page and run both commands again with it. The folder it replaces is kept as `<dir>-<old version>-<date>`.

## By hand

The service is a FastAPI app: `python -m uvicorn backend.api:app --host 127.0.0.1 --port 8018 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1`, run from a release folder with a Python 3.10+ environment (`pip install -r requirements.txt`). The release already contains the built members' page (`frontend/dist`), so the server does not need Node.js. Use the files here as templates: `arynwood-grove.service`, `nginx-grove.conf` (replace `@DOMAIN@` and `@PORT@`), and the backup timer. Set `GROVE_PUBLIC_URL` and `GROVE_DATA_DIR`.

## Things to know

- **One process.** Keep `--workers 1`: change notices are shared in memory, and SQLite has one writer. Pages fall back to polling if their live connection drops.
- **Behind Cloudflare or another proxy,** nginx sees the proxy's address, not the visitor's, so sign-in and public-link limits apply per proxy address. Configure nginx's `real_ip` module with the proxy's address ranges so they apply per visitor.
- **The host account reaches Mail, IRC and Private messages from the public address.** Those use the server's own mail account and identities. Use a strong, unique host password. On a Grove you run for someone else, set `GROVE_HOST_TOOLS=off`.
- **Uploads go through nginx in pieces of up to 8 MB.** The installer's site allows 10 MB a request. A site made by hand, or by Community 0.3, needs `client_max_body_size 10m;` for full-speed uploads and for saving pages over 1 MB in the editor.
- **Private messages need Node.js** and `npm --prefix nkn ci` in the release folder; the installer does not set them up.
