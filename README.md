# Arynwood Grove

**The Grove, your community – your choices.** Shared calendars, conversations,
files, tasks and websites for a group of people, on a server you control.
Members join through a browser; they do not need the desktop app.

[Website](https://arynwood.com/community/) · [Downloads](https://github.com/Arynwood-Technology/arynwood-community/releases/latest) · [Manual](docs/MANUAL.md) · [Arynwood's Grove](https://community.arynwood.com/)

[![CI](https://github.com/Arynwood-Technology/arynwood-community/actions/workflows/ci.yml/badge.svg)](https://github.com/Arynwood-Technology/arynwood-community/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/Arynwood-Technology/arynwood-community)](https://github.com/Arynwood-Technology/arynwood-community/releases/latest)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Arynwood-Technology/arynwood-community/badge)](https://scorecard.dev/viewer/?uri=github.com/Arynwood-Technology/arynwood-community)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/15881/badge)](https://www.bestpractices.dev/projects/15881)

## Current standing

**Grove 0.7.4 is published.** It strengthens release delivery: installation checks
an archive against its correctly named checksum before changing the server,
downloads require HTTPS, and redirects to plain HTTP are refused.
[Release notes](docs/PRERELEASE.md) · [0.7.4 downloads](https://github.com/Arynwood-Technology/arynwood-community/releases/tag/v0.7.4).

The published packages carry GitHub build-provenance attestations. Backend tests,
frontend tests, lint, build and installer checks run before packaging. CodeQL and
OpenSSF Scorecard provide additional checks; the best-practices badge remains in
progress. A passing workflow or a badge is evidence of specific checks, not a
promise that software has no vulnerabilities.

Grove is open source under the AGPL-3.0 and is still developing. It was formerly
Arynwood Community; Community 0.3 installations can upgrade in place. It runs
independently of [Arynwood MCP](https://github.com/Arynwood-Technology/ArynwoodMCP),
which can also show your Grove inside its Community page.

## A place for the group

| Area | What members can do |
|---|---|
| Calendar and plans | See the month and day planner, assign tasks, keep lists and track upcoming work |
| Conversations | Share updates and boards, reply, and send private messages with photos and files |
| Files | Upload in resumable pieces, organize folders, edit text, keep versions and use the trash |
| Websites | Preview the group's site; appointed webmasters edit, publish and restore earlier versions |
| People and identity | Invite members, manage spaces and choose the Grove's branding |
| Workspace setup | Stage a film-festival or client-project workspace with guides, folders and CSV trackers |

Spaces determine who shares the work. Owners manage their spaces; Grove owners
and managers have administration tools. Host mail and IRC connections have their
own access restrictions. Public chat is available when the operator configures
an IRC room. [Member and operator manual](docs/MANUAL.md).

## Put a Grove on your server

Use Ubuntu 22.04+ or Debian 12+ and a domain pointed at the server. The installer
sets up an unprivileged service, nginx, HTTPS, daily backups and the management
command. Read [deployment and requirements](deploy/README.md) before running it.

```bash
curl -fsSL https://github.com/Arynwood-Technology/arynwood-community/releases/latest/download/install.sh \
  | sudo bash -s -- --domain grove.example.com --email you@example.com
```

The installer prints a setup link. Open it and create the host account; its setup
code prevents someone else claiming the new Grove first. Then create a space and
choose **Invite members**. Private invitations admit one person and expire after
seven days. Public invitations can be replaced or disabled by the space's owners.

```bash
sudo arynwood-grove status
sudo arynwood-grove update
sudo arynwood-grove rollback
sudo arynwood-grove help
```

The management command also supports several Groves on one server, password
recovery and encrypted off-server backups. If you install without a domain, the
host can add one later from **People & identity → Your Grove's address**.
[Operations guide](deploy/README.md).

## Verify release files

Keep each `.tar.gz` beside its matching `.tar.gz.sha256` file. The installer and
updater verify them before installation changes the server. For a manual check:

```bash
sha256sum -c arynwood-grove-0.7.4.tar.gz.sha256
gh attestation verify arynwood-grove-0.7.4.tar.gz \
  -R Arynwood-Technology/arynwood-community \
  --source-ref refs/tags/v0.7.4 --deny-self-hosted-runners
```

The checksum checks the downloaded bytes; the attestation ties the archive to the
repository's tagged build. Grove does not claim an owner-key signature for this release.

### Upgrade from Community 0.3

Download the versioned archive and its checksum into the same folder. As the
account that owns the installation, run the upgrade script from `deploy/`:

```bash
bash upgrade-from-community.sh --dir ~/arynwood-community --from arynwood-grove-0.7.4.tar.gz --prepare-only
bash upgrade-from-community.sh --dir ~/arynwood-community --from arynwood-grove-0.7.4.tar.gz
```

Preparation backs up and tests a staged release against a copy of your data.
The second command switches the service and prints the rollback command. Existing
accounts, spaces, settings and invitation links are retained. Follow the
[upgrade guide](deploy/README.md) for your installation.

## Try it locally or develop

Requires Python 3.10+, Node.js 20.19+ or 22.12+, and npm on Linux or macOS.

```bash
./setup.sh
./start.sh
```

Open http://127.0.0.1:8018/community. For frontend development, keep the backend
running and use `npm --prefix frontend run dev` at http://127.0.0.1:5174.

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
scripts/package.sh
```

[API reference](docs/API.md) · [Architecture and manual](docs/MANUAL.md) · [Workspace guide](docs/PRODUCER-WORKSPACE.md).

## Data and security

The operator controls the server, database, uploaded files and backups. Keep the
service on loopback behind HTTPS and arrange off-server backups. Members' private
messages are restricted by application permissions; server ownership remains a
trust boundary. Mail and IRC contact their configured providers when used.

Sessions use HTTP-only, SameSite cookies; requests and WebSockets check origins;
account operations are rate-limited. Sandbox policies restrict file and website
previews. Details and private vulnerability reporting are in [SECURITY.md](SECURITY.md).

## Maintenance and license

Lorelei Noble maintains the project, reviews changes and ships releases.
[How we build](https://github.com/Arynwood-Technology/.github/blob/main/HOW-WE-BUILD.md).

Code is licensed under [GNU AGPL-3.0](LICENSE). A running Grove offers its source
at `/api/source`. The Arynwood tree logo and branded icons are separate artwork,
all rights reserved. The code license does not grant rights to that branding.
