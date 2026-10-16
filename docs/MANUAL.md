# Arynwood Grove manual

A guide for members, Grove owners and the people who operate their servers.
This manual describes version **0.6.0**. A server running an older release may
lack some of what is described here: `sudo arynwood-grove status` shows the
version a Grove runs.

## Find your way

- [Using your Grove](#using-your-grove)
- [Accounts, roles and privacy](#accounts-roles-and-privacy)
- [Files, editing and websites](#files-editing-and-websites)
- [How the software fits together](#how-the-software-fits-together)
- [Build and release diagram](#build-and-release-diagram)
- [One product, separate Groves](#one-product-separate-groves)
- [Server operation](#server-operation)
- [Troubleshooting](#troubleshooting)

## Using your Grove

Open your organization's Grove address and sign in. An account belongs to that
Grove: signing into one Grove does not sign you into any other.
Use an invitation from a space owner to join their space. Keep invitation links
private unless the owner deliberately creates a public invitation. An ordinary
invitation admits one person and expires after seven days; a space owner can
replace a public invite link or turn it off.

The first account is the host, created using the installer's private setup link.
The server operator can show that link again with `sudo arynwood-grove setup-link`.
Once an account exists, the command reports that the Grove already has a host.
Do not put setup links or recovery codes in shared documentation.

Choose a **Space** in the header. Spaces separate groups and their shared work
inside one Grove; they are not separate Groves.

| Page | What to do there |
|---|---|
| Calendar | Where a space opens: the month, with the chosen day's hours beside it and the space's tasks and lists below. Choose a day to see its schedule; on a phone, dots mark what's scheduled. |
| Overview | See upcoming plans, open tasks and recent activity in the selected space. |
| Board | Share posts and replies. |
| Updates | Post news and updates for everyone in the space. A Grove can give it its own name, such as Event journal. |
| Public chat | Talk with other people in the Grove's IRC room, when the Grove has one (see below). |
| Tasks | Track assignments and due dates. |
| Lists | Keep shared lists. |
| Notes | Keep shared notes or choose private visibility for your own notes. |
| Files | Upload, organize, download and edit the space's files. |
| People & identity | Manage your identity and the selected space; space owners also manage invitations and membership. |
| Grove admin | Owners and managers review people, spaces, storage, activity and wishes. |
| Look & feel | Owners make the Grove look like their organisation: name and tagline, colours (light or dark), the login page's colour and picture, type, corners and logo, or all of it suggested from the Grove's website. |
| Webmaster tools | Owners and webmasters bring the Grove's website in, change it in Files, preview it and publish it at the Grove's address. Everyone else sees **Website preview**: what's live, and previews of what's coming. |
| Workspace setup | Space owners stage a film festival or client project: checklists, notes, documents, folders and CSV trackers. See the [producer workspace guide](PRODUCER-WORKSPACE.md). |

Changes normally appear on other members' pages within about a second. If the
live connection drops, the page polls for changes until it reconnects. The wish
lamp sends a suggestion to the Grove's owners and managers, who see it in Grove
admin. It is also emailed to `GROVE_WISH_EMAIL` when that is set and the server
can send mail.

**Public chat** is an IRC room the Grove names (`GROVE_CHAT_CHANNEL`). Every
member gets a starting nickname, made from the Grove's pattern, and can change it
before connecting; the page remembers it in that browser. The room is on a public
IRC network: anyone on that network can join it, so treat it as public, unlike the
space's Updates. A Grove's sign-in does not register or protect an IRC nickname.
On a Grove without a room, Public chat is the host's own IRC client, under host
tools.

To recover a forgotten password, ask the server operator for a recovery code.
Enter it under **Forgot password?** Codes last 15 minutes; there is no automatic
password-reset email.

## Accounts, roles and privacy

There are three different kinds of authority. They should not be confused.

| Scope | Authority |
|---|---|
| Server operator | Controls Linux, installation, domains, releases, configuration and backups. Root can technically read server files and databases; application privacy is not a barrier to root. |
| Grove-wide roles | The host is always an owner. Owners assign owner, manager or member roles and change Grove settings. Owners and managers can open Grove admin. Owners look after the Grove's website, and can make anyone a webmaster to look after it with them. |
| Space roles | A space owner manages that space, its invitations and membership. Space membership controls ordinary access to its content. This role is separate from the Grove-wide role. |

Grove admin provides visibility across the Grove; it is not an infrastructure
control panel. Managers see everything in Grove admin but cannot change roles
or settings. Whether members can start spaces is a Grove setting: everyone, or
owners and managers only. Mail, the host's IRC client and Private messages, when
enabled, are restricted to the host; being a manager or another owner does not
grant those connections. Members' Public chat can reach only the Grove's
configured IRC server and room, and never uses the host's IRC settings or
passwords.

The invitation page explains the administrative visibility:

> This Grove's owners and managers can see everything shared there, and a log of activity, including what is posted and deleted. Private notes stay private: they see only that they exist.

Private notes are restricted by the application to their author. The activity
log records that they exist, never their titles or words. This is not
end-to-end encryption, and does not remove the server operator's responsibility
to protect the database and backups. Only grant infrastructure access when
authorized and necessary.

## Files, editing and websites

### Upload and organize

1. Select the intended space and open **Files**.
2. Create folders as needed and upload files. Everyone in that space can see them.
3. Uploading a file with a name that is already there offers **New version**,
   **Keep both** or **Skip**. Earlier versions remain available.
4. Use the trash to recover accidental deletions. Trash is kept for 30 days;
   space owners can permanently delete trashed items.

By default a space has 10 GB of file storage and a single file can be up to
2 GB. The operator can change both limits. Pages upload in 4 MB pieces (a
server accepts at most 8 MB per piece) and resume after a dropped connection.
The reverse proxy therefore needs a 10 MB request limit, even though whole
files can be much larger; behind a stricter proxy, pages fall back to smaller
pieces. Uploads stop when less than 2 GB of disk space remains. Earlier
versions count toward the space's storage.

Anyone in the space can add a new version of a file, by uploading or in the
editor. Only a file's author or a space owner can move, rename, delete or
restore it. A folder containing other people's files needs a space owner to
change it.

### Spreadsheets

CSV files, such as Workspace setup's trackers, open in the text editor. To work
on one as a table, download it, edit it in a spreadsheet program, save it as CSV
and upload it with the same name as a new version.

### Edit text and preview HTML

Open a text file and choose **Edit**. The editor handles UTF-8 text up to 2 MB
and saves each change as a new version. If someone has saved a newer version,
save your unsaved work elsewhere, reload and reconcile it before trying again.
The server rejects a stale save rather than overwriting it.

HTML previews load styles, images and fonts from the page's own folder and the
folders inside it. A page in a website (`Website/<site>`, see below) sees the
whole site, including addresses that start with `/`, such as `/styles.css`.
The editor's preview is sandboxed: scripts do not run, nothing outside the
Grove loads and server code does not run. A preview link lasts an hour (the
editor renews it while it is open) and stops working when the service restarts.
Reopen the preview to get a fresh one. Treat these links as private while valid.

### The Grove's website

Each Grove can show a website at its own address, such as
`https://roguefest.arynwood.com/`. The members' page stays at `/community`. The
website is plain HTML, CSS, scripts and images, kept in Files and published
from there. This replaces a website builder's admin for a static site: edit,
preview, publish.

**Who does what.** Owners look after the website. In Grove admin, an owner can
tick **Webmaster** for anyone else, such as a designer, to look after it with
them. Only owners and webmasters change a space's **Website** folder, bring
sites in and publish. Everyone else in the space sees those files read-only,
and everyone in the Grove can open **Website preview** to see what's live and
preview what's coming. Managers are not webmasters unless an owner makes them
one.

**Bring the site in.** Open **Webmaster tools** and choose the space that
will hold its files: a space for the people who work on the website is best.
There are three ways in:

- *From its address.* The importer reads public pages and the styles, scripts,
  images and fonts they use on the same address, following links and
  respecting robots.txt. It records skipped items and errors. It cannot recover
  server-side code, checkout systems, signed-in pages or unlinked pages. Assets
  on other sites stay where they are and are listed in the import result. It
  never connects to private network addresses. This is a working copy of a
  public site, not a complete backup of its hosting platform.
- *From a .zip*, for a site that isn't online yet or one a designer sent. Zip
  the folder that holds `index.html`. The .zip is kept in `Website` and
  unpacked into `Website/<the zip's name>`; links, password-protected entries
  and names that can't be files are left out and listed.
- *Start with one page*: a front page made from the Grove's name, tagline,
  colours and logo, with a way in for members, in `Website/<the Grove's address>`.

Importing or unpacking again creates versions of changed files and deletes
nothing. Review local edits before reimporting: the live website may differ
from your working copy.

**Change it** in Files, with the editor or by uploading new versions. Nothing
changes on the live site until someone publishes.

**Preview** shows the whole site as visitors will see it: its links, clean
addresses such as `/about` for `about.html`, its 404 page, and its scripts.
Scripts run in a sandbox, with no access to members' sign-ins, and nothing
outside the Grove loads, so an embedded video shows as blocked.

**Publish.** A website is a folder in `Website` with an `index.html` at its
top. **Publish** puts it at the Grove's address straight away. A publish keeps
the files as they were, so later edits wait for the next publish. The last ten
versions are kept: **Earlier versions** puts one back at once, and **Take it
down** sends visitors to the members' page again. Every publish, put-back and
take-down is in the activity log.

The published site is served like Cloudflare Pages serves one: `/about`
serves `about.html`, `/about.html` moves to `/about`, and an unknown address
gets `404.html`. Cloudflare's `_headers` and `_redirects` files are not
served. The Grove keeps `/community`, `/api` and its own page files, such as
`/assets/`, `/fonts/` and `/favicon.svg`; a site's file at one of those
addresses is not shown, and publishing says which. Published pages run their
scripts apart from the Grove: they cannot read members' cookies or act with
their sign-in, and browser storage is not available to them.

**Your own domain.** To show the site at your own domain, the host moves the
Grove there (**People & identity → Your Grove's address**, or
`arynwood-grove set-domain`). The website and the members' page move together.
To publish somewhere else instead, use **Download as a .zip** on the site's
folder and send it to whoever runs that host.

A shop link in Grove branding points to a separate website; it does not install
or synchronize a shop.

### Your Grove's look

Owners open **Look & feel** to make the Grove look like their organisation. A
preview of the login page and the members' pages follows every change; nothing
changes for anyone else until **Save**.

- **Name and words**: the name, tagline, and the website and shop links.
- **Colours**: background, text, accent (buttons, links, highlights) and the
  login page's side with the name and logo. Light or dark both work. The Grove
  adjusts a colour only as far as it must for text, buttons and borders to stay
  readable, and says when it has: "Shown as #… so it stays readable". Text,
  accent and login page can be left **Automatic**.
- **Type and shape**: heading and body typefaces from fonts every device has
  (clean, rounded, classic, or a bold display face for headings), round, soft
  or square corners, and the logo as it is or in a circle.
- **Pictures**: the logo (up to 512 KB) and a login page picture (up to 2 MB),
  PNG, JPEG or WebP. They change straight away.
- **Start from your website** reads a website in a space's Website folder and
  suggests its colours, type, logo and share picture, to review before saving.

**Back to the host's look** forgets everything chosen here, pictures included,
and the Grove looks as its host set it up (the `GROVE_BRAND_*` settings).
Changes are in the activity log.

```mermaid
flowchart LR
  Public[Existing website] -->|Import public pages and assets| Files[Space: Website folder]
  Zip[Site as a .zip] -->|Unpack| Files
  Starter[One-page starter] --> Files
  Files --> Edit[Text editor]
  Edit -->|Save a new version| Files
  Files --> Preview[Whole-site preview: every member]
  Files -->|Publish: owners and webmasters| Release[Release: the files as they were]
  Release --> Live[The Grove's address: /]
  Release -->|Put back or take down| Live
  Files --> Download[Download folder .zip for another host]
```

## How the software fits together

Grove is a React 19 and Vite frontend served by a FastAPI Python application.
Production runs one application worker per Grove behind nginx. The same service
serves the page at `/community`, built assets and API endpoints. SQLite stores
accounts, memberships, entries, activity and file metadata; file contents live
beside the database. Live notices stay in process memory, which is one reason
to keep one worker.

```mermaid
flowchart TB
  Browser[Member browser: React page] -->|HTTPS| Nginx[nginx: domain routing and TLS]
  Nginx -->|Loopback HTTP, one assigned port| API[FastAPI: one worker per Grove]
  API --> Auth[Session, origin and permission checks]
  Auth --> Routes[Community, files, editor and admin routes]
  Routes --> DB[(One Grove SQLite database)]
  Routes --> Blobs[Data directory: file contents and upload pieces]
  Routes --> Live[In-memory change notices]
  Live -->|Refresh through permission-checked API| Browser
  API --> Brand[Validated branding and theme]
  Env[Per-Grove environment settings] --> API
  Logo[Logo in data directory] --> Brand
```

| Source path | Responsibility |
|---|---|
| `backend/api.py` | Application assembly, middleware, route mounting and frontend delivery. |
| `backend/community/store.py` | Version, settings lookup, database location and schema initialization. Reads `GROVE_*`, with legacy `COMMUNITY_*` fallback. |
| `backend/community/auth.py`, `routes.py` | Accounts, sessions, access rules, spaces and shared entries. |
| `backend/community/files.py`, `editor.py` | File metadata and contents, uploads in pieces, versions, text editing and previews. |
| `backend/community/admin.py`, `activity.py`, `wishes.py` | Grove administration, activity records and wishes. |
| `backend/community/webmaster.py` | Bringing a website in: imports from its address, .zip uploads and the one-page starter. |
| `backend/community/website.py` | Publishing the website: releases, putting one back, previews for everyone, and serving the live site at the Grove's address. |
| `backend/community/workspace_setup.py`, `workspace_kits.py` | Workspace setup: the kits' content and staging them in one transaction. |
| `backend/routers/irc.py`, `chat.py` | The host's IRC relay, and members' Public chat on the configured room. |
| `backend/brand.py` | `read_brand()` merges the host's branding with what owners saved in Look & feel, validates it and derives accessible CSS theme tokens, light or dark. |
| `backend/community/site_look.py` | Reads a website in Files for Look & feel's suggestions: colours, type, logo and share picture. |
| `frontend/src/Community.tsx` | Signed-in page, space selection and section routing. |
| `frontend/src/pages/` | Welcome, calendar, files, settings, admin and other views. |
| `frontend/src/lib/` | Browser API helpers and shared types. |
| `frontend/src/community.css` | Shared layout and theme variables. |
| `deploy/` | Installer, CLI, service units, nginx template and upgrade tooling. |
| `scripts/package.sh` | Frontend build and versioned release archive. |
| `.github/workflows/release.yml` | Tag-triggered checks, packaging and GitHub release publication. |

Branding is configuration, not a separate copy of the code for each group.
Name, tagline, links, logo and colours come from the server. `GET /api/brand`
returns validated values and derived tokens; `/api/brand/logo` serves an
accepted image. See the [configuration table](../README.md#configuration) for
all names and limits. Keep secrets in protected environment files, not frontend
code or Git.

## Build and release diagram

```mermaid
flowchart TD
  Source[Shared Git source] --> Local[Local development and review]
  Local --> Tag[Push an approved version tag: vX.Y.Z]
  Tag --> CI[GitHub Actions release workflow]
  CI --> Version[Version in store.py matches the tag]
  Version --> Backend[Python dependencies and unittest suite]
  Version --> Frontend[npm ci, lint and frontend tests]
  Version --> Shell[Installer shell syntax checks]
  Backend --> Package[scripts/package.sh]
  Frontend --> Package
  Shell --> Package
  Package --> Build[TypeScript and Vite build: frontend/dist]
  Build --> Archive[Versioned tar.gz, SHA-256 checksum and installer]
  Archive --> Release[GitHub release]
  Release --> Decision[Operator chooses when to update each Grove]
  Decision --> Install[Installer or management CLI]
  Install --> Backup[Backup and release preparation]
  Backup --> Switch[Switch the Grove and check health]
  Switch --> Running[The Grove runs the release]
  Switch -->|Startup failure| Previous[Previous release keeps running]
```

A normal code push does not trigger this release workflow: version tags do.
Publishing a release does not update any running Grove. Updating is a separate
operator action. The release workflow checks that the backend version matches
the tag; keep `frontend/package.json` at the same version. The package contains
tracked source files, documentation, deployment tooling and the built frontend;
it excludes local secrets and runtime data. The package script refuses
untracked files in its source directories so they cannot be silently omitted.
Servers use the built page and do not need Node for it; optional NKN
connections have additional Node requirements.

For local development, use `./setup.sh`, then `./start.sh`. For frontend work,
run `npm --prefix frontend run dev` alongside the backend. Before releasing:

```bash
.venv/bin/python -m unittest discover -s tests
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
bash -n deploy/install.sh deploy/arynwood-grove deploy/upgrade-from-community.sh
```

A successful application rollback does not reverse database changes. Verify
compatibility and keep a restorable data backup before changing versions.

## One product, separate Groves

**Arynwood Grove is the product. Each group gets its own Grove**: the same
release, with its own configuration and data. No per-group Git repository or
fork is needed.

The application serves one Grove per process. The deployment tooling also
supports several named Groves on one server, with separate Linux users,
services, environment files, data directories and ports. This is a
multi-instance architecture, not one application process choosing a tenant for
every request. A symlink alone does not provide isolation. A shared server and
its root operator remain common trust boundaries; groups with stricter
requirements may call for separate containers, VMs or servers.

```mermaid
flowchart TB
  Product[Shared versioned Grove releases] --> A[Festival Grove service]
  Product --> B[Club Grove service]
  Proxy[nginx: hostname routing] --> A
  Proxy --> B
  A --> AConfig[Festival configuration and Linux user]
  A --> AData[(Festival database and files)]
  B --> BConfig[Club configuration and Linux user]
  B --> BData[(Club database and files)]
  Operator[Authorized server operator] --> Proxy
  Operator --> Product
```

### Paths on a server

| Purpose | Unnamed Grove (made by the installer) | Named Grove `NAME` (`arynwood-grove create NAME`) |
|---|---|---|
| Shared release | `/opt/arynwood-grove/releases/<version>` | Same release directory |
| Active release link | `/opt/arynwood-grove/current` | `/opt/arynwood-grove/groves/NAME` |
| Environment | `/etc/arynwood-grove/grove.env` | `/etc/arynwood-groves/NAME.env` |
| Runtime data | `/var/lib/arynwood-grove` | `/var/lib/arynwood-groves/NAME` |
| Linux user | `grove` | `grove-NAME` |
| systemd service | `arynwood-grove.service` | `arynwood-grove@NAME.service` |
| nginx site | `/etc/nginx/sites-available/arynwood-grove` | `/etc/nginx/sites-available/arynwood-grove-NAME` |
| Port | `--port`, default 8018 | The first free port from 8100 |

A Grove's group name does not make it a named Grove: a Grove made by
`install.sh` is unnamed, whatever it is for. Use `--grove NAME` only for Groves
that `sudo arynwood-grove list` shows with a name. A Community 0.3 server
upgraded in place with `upgrade-from-community.sh` keeps its own folder, `.env`
and service; it does not use these paths, and the CLI does not manage it.

Check `sudo arynwood-grove help` on the server itself: a server installed with
an older release may lack newer commands until it is updated.

A central dashboard for many Groves, billing, subscriptions, automatic VM
provisioning and orchestration across servers are **not part of Grove**. Grove
admin administers one Grove; it does not administer a hosting business.

## Server operation

These commands only read state. For a named Grove, put `--grove NAME` before
the command:

```bash
sudo arynwood-grove status
sudo arynwood-grove logs
curl -fsS http://127.0.0.1:8018/api/health   # the Grove's GROVE_PORT
```

Health confirms that the application answers, not that every workflow or the
off-server copies work.

For an authorized operator, the CLI also provides `backup`, `restore`,
`setup-link`, `recovery-code`, `set-domain`, `update`, `rollback` and
`offsite`. These can change state or disclose private access codes. See the
[deployment guide](../deploy/README.md) for procedures, named Groves,
off-server copies and upgrades. Do not run update or restore merely to
troubleshoot a healthy Grove.

Keep the program root-owned and readable by the service, normally directory
mode 0755. Since 0.5.1 the installer and CLI set `umask 022` themselves; with
an older release, run them under `sudo bash -c 'umask 022; …'`, because an
inherited 077 umask makes the release unreadable by the service user.
Environment files are readable by root and the service's group, normally 0640;
writable data belongs to the service user. Never fix a permission error with
`chmod -R 777`.

Production uses loopback binding, nginx TLS termination and one worker.
The systemd service restricts writes to its data directory. Named Groves'
services also have a 768 MB memory limit and a task limit; shared disk and CPU
still need monitoring. Application protections include session cookies,
origin and header checks, permission-checked APIs and a restrictive Content
Security Policy. Do not weaken that policy to make a preview behave like a live
website.

### Backup and recovery

Daily CLI backups use SQLite's online backup API, keep 14 database copies and
then empty trash older than 30 days. **A database backup does not contain file
contents, logos, configuration or the hosting of an external website.** Keep
those too.

`arynwood-grove offsite` uses restic to copy every Grove on the server off it
each night: consistent databases, file data, settings and nginx sites. It needs
explicit setup and a saved recovery password; the local backup timer is not
evidence that off-server copies are on. `sudo arynwood-grove offsite status`
shows whether they are, and when the last copy was made. A Community 0.3 server
upgraded in place is not managed by the CLI, so these copies do not include it.
Back it up separately.

Test recovery in an isolated environment. Confirm accounts, space membership,
file downloads, versions and permissions, not just the health endpoint.
Restoring only an old database while the files it refers to are missing is not
a full recovery. Keep the off-server copies' password safe, off the server.

## Troubleshooting

| Symptom | First checks |
|---|---|
| Site returns 502 | Service status and journal; assigned port; readable release and `.venv`; nginx upstream. |
| Healthy API but page looks old | Reload the page. `sudo arynwood-grove status` shows the version the server runs. |
| Uploads are slow or return 413 | nginx `client_max_body_size 10m`, per-file and per-space limits; the text editor has its own 2 MB limit. |
| Upload stops with a storage error | Free disk space, the space's storage, earlier versions and trash. |
| Preview is incomplete | Sandbox restrictions, files in a parent folder, assets on other sites or server-side functionality; do not disable CSP. |
| Preview expires | Open it again; links last 15 minutes and end when the service restarts. |
| Edit reports a newer version | Copy unsaved work, reload and merge it with the current version. |
| Website unchanged after saving | Grove saved a working copy. Download it and publish it separately. |
| Cannot move or delete a file | Only its author or a space owner can. |
| Cannot open Grove admin | Check the Grove-wide owner or manager role, not just space ownership. |
| Cannot sign in on another Grove | Accounts and sessions belong to each Grove separately. |
| Public chat does not appear | The Grove needs `GROVE_CHAT_CHANNEL`; without it, only the host sees Public chat, and only with host tools on. |
| Public chat refuses to connect | The nickname (letters, numbers, `-` and `_`, starting with a letter, up to 30), two open windows already, or the IRC server's limit on connections from one address. |

Code is AGPL-3.0; the running service offers its source at `/api/source`.
Arynwood's tree artwork has separate rights (see the README). A Grove's own
branding should not imply that its data or accounts belong to a shared
Arynwood-wide service.
