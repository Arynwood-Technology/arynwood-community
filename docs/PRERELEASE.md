# Arynwood Grove release notes

Version: `0.6.1`

Arynwood Community is now **Arynwood Grove**: "The Grove, your community – your choices." A Community 0.3 install upgrades in place.

## 0.6.1

- **Messages.** Private conversations between two members who share a space, with photos: up to six a message, shrunk to 4096 pixels across, and kept without location or camera details. Only the two people can read a conversation; owners and managers can't, and the activity log doesn't mention it. Unread messages are counted in the menu, and new ones arrive without reloading. The host's own peer-to-peer inbox is still **Private messages**, under host tools.
- **Private messages work on servers.** Releases now include the library the host's peer-to-peer inbox uses, so it runs wherever the server has Node.js 20.19+ or 22.12+, without `./setup.sh`.
- In Private messages, a chosen picture or file now waits beside the message box until you press **Send**, and can be removed first. Photos are shrunk to 2048 pixels across before they go, leaving location and camera details behind, so a phone's photos fit; a GIF goes as it is. Pictures and files can be up to 2.5 MB, up from 2 MB and 1 MB. A peer on an older Grove sees a file over 1 MB as an unsupported attachment.

## 0.6.0

Websites

- **A website at the Grove's address.** Each Grove can show a static website at its own address, such as `https://roguefest.arynwood.com/`, with the members' page at `/community`. **Webmaster tools** brings a site in from its address, as a .zip, or as a one-page starter made from the Grove's branding; it's edited in Files and previewed whole, links, scripts and 404 page included. **Publish** puts it live straight away; the last ten versions are kept to put back, and it can be taken down. Pages are served with clean addresses, as on Cloudflare Pages, and their scripts run walled off from members' sign-ins.
- **Webmasters.** Owners look after the website, and can make anyone a webmaster in Grove admin to look after it with them. Only they change a space's Website folder and publish. Everyone in the Grove can open **Website preview**. Managers are no longer webmasters unless an owner makes them one.
- Editor previews now resolve a site's own addresses (`/styles.css`), and preview links last an hour.

Look & feel

- **Owners choose the Grove's look** from the members' page: name and words, light or dark colours with readable contrast worked out, the login page's colour and picture, type, corners and logo. **Start from your website** suggests it all from the Grove's website. The host's `GROVE_BRAND_*` settings are the starting look, and **Back to the host's look** returns to them.
- A branded Grove's Overview banner shows its own logo rather than the Arynwood tree.

## 0.5.5

- **The calendar opens on the month.** A space's home is the month, with the chosen day's hours on the right and its tasks and lists under the month. Choose a day to see its schedule; **Today** comes back to today. On a phone the month comes first, then the day, then tasks and lists, and dots mark what's scheduled.

## 0.5.4

- The spreadsheet table editor, and **New spreadsheet** and **New document** in Files, are held back until documents and spreadsheets have proper editors. CSV and Markdown files open in the text editor as before.
- Workspace setup stays. Its trackers are CSV files: download one, edit it in a spreadsheet program, and upload it with the same name as a new version. The kits' guides say so.

## 0.5.3

Members

- **Public chat.** A Grove that names an IRC room (`GROVE_CHAT_CHANNEL`, e.g. `#RogueFest`) opens it to every member from the Grove. Each member starts with a nickname from `GROVE_CHAT_NICK` (every `#` a random digit, e.g. `RogueGuest###`) and can change it. The browser chooses only the nickname: the server, port and room come from the Grove's settings (`GROVE_CHAT_SERVER`, default `irc.arynwood.com:6697`), no IRC password is sent, and each member may hold two connections at once. Without a room, Public chat is the host's own IRC client, as before.
- "IRC rooms" is now **Public chat**, and "Space discussion" is now each space's **Updates**: a log of news, which a Grove can rename with `GROVE_LOG_NAME` (RogueFest's is the Event journal). Conversation belongs in Public chat.
- An unbranded Grove's welcome badge says "Arynwood Grove" rather than "Grove 0.4".

Producers

- **Workspace setup**, for space owners: stage an independent film festival or a client project in a space, with department checklists, operating notes, setup tasks, a decisions board, folders, documents and empty CSV trackers. An optional opening date adds proposed milestones. A kit is staged once per space, all at once or not at all. See docs/PRODUCER-WORKSPACE.md.
- **Spreadsheets**: CSV files open as editable tables, saved as new versions, with income, expense and net totals per currency for budget tables. Files has **New spreadsheet** and **New document**.
- `scripts/export_workspace.py` writes a kit as a .zip for review, without a Grove.

Docs

- docs/MANUAL.md: a manual for members, owners and server operators.

Workspace setup keeps its receipts in a table of its own, so a Grove rolled back to 0.5.2 keeps working on the same database.

## 0.5.2

Servers

- **Off-server copies.** `sudo arynwood-grove offsite setup <repository>` copies every Grove on the server off it each night with restic: to a Hetzner Storage Box or any SFTP server, S3, B2 or R2.
  - Each copy holds the database, everyone's files, the settings and the nginx sites.
  - The copies are encrypted and deduplicated. 14 daily, 8 weekly and 12 monthly copies are kept.
  - `offsite restore` puts a Grove back from a copy, on the same server or on a new one. The data it had is kept aside.
  - `offsite status`, `list`, `run`, `check`, `on` and `off`. `arynwood-grove status` shows the last off-server copy.

## 0.5.1

Servers

- **Several Groves on one server.** `arynwood-grove create NAME --domain …` adds a Grove with its own service, system user, data, settings and port, limited to 768 MB of memory. All of them share one copy of each release. `arynwood-grove list` shows them all, and `--grove NAME` runs any command for one of them.
- `arynwood-grove update --all` updates one Grove first (`--canary NAME`), and the rest only once it runs the new release. `backup --all` backs them all up.
- The management command always comes from the newest release on the server, so rolling one Grove back never takes commands away from the others.
- A new Grove's installer refuses a port something else already listens on.
- The installer and `arynwood-grove` work under a strict umask, such as 077 on a hardened server. Before, the release folder came out unreadable to the service, which then never started.

A server installed with 0.5.0 or earlier updates as usual (`arynwood-grove update`), and its Grove keeps its paths and has no name.

## 0.5.0

Running a Grove for a group

- **Grove roles.** The host is always an owner. Owners make people owners, managers or members; everyone else comes in as a member. Managers use everything in Grove admin except appointing people.
- **Grove admin**: everyone in the Grove, every space (including ones members start), disk use, and the activity log. The log records who did what and when, including sign-ins; private items are counted, never shown. Owners can stop members starting spaces.
- **Branding**: a Grove's name, tagline, logo, website and shop links, and a full colour theme from three colours, with readable contrast worked out automatically (`GROVE_BRAND_*`).
- **The wish lamp**, small in the bottom right: anyone can wish for a change. Owners and managers see wishes in Grove admin, and they are emailed to `GROVE_WISH_EMAIL` when the server can send mail.
- `GROVE_HOST_TOOLS=off` hides Mail, IRC and Private messages, which use the host's own accounts, on a Grove run for someone else.

Files

- **Files** in every space: folders, uploads of up to 2 GB that resume after a dropped connection, earlier versions kept, and a 30-day trash. Room for each space is set by `GROVE_SPACE_STORAGE_MB`.
- **An editor for text files**, with HTML, CSS, JavaScript, JSON and Markdown highlighting. Saving makes a new version and never overwrites someone else's newer save. HTML pages preview as you type, with their styles and images and with scripts off.
- **Webmaster tools** (owners and the webmasters they choose): bring a website in from its address, from a .zip, or as a one-page starter; edit it in Files; preview the whole site; and publish it at the Grove's address, with earlier versions to put back. Everyone in the Grove can preview it. Imports read only the same site, follow robots.txt, and never reach private addresses.

Servers

- The installer's nginx site accepts upload pieces of up to 10 MB. Sites made by an older installer or by hand still work, with smaller pieces; see deploy/README.md.
- New settings: `GROVE_HOST_TOOLS`, `GROVE_WISH_EMAIL`, `GROVE_SPACE_STORAGE_MB`, `GROVE_FILE_MAX_MB`.
- Back up `files/` in the data folder off the server too: the daily copy holds the database only.

Roles, the activity log, files, wishes and imports are tables of their own, so a Grove rolled back to 0.4.2 keeps working on the same database.

## 0.4.2

Added

- Managing a space (Manage space, or People & identity): owners rename it and give it a topic, which every member sees under its name, and can delete it for everyone after typing its name. Members' open pages move to another space and say why.
- Member roles: owners make other members owners, or members again. A space always keeps at least one owner, so the only owner can neither step down nor leave; with two owners, either can do both.
- Assigning tasks from the Calendar as well as Tasks, with the assignee shown on each goal. A private task can be assigned only to its author, the only person who can see it.

Topics are kept in a table of their own, so a Grove rolled back to 0.4.1 keeps working on the same database.

## 0.4.1

Fixes

- Private messages: importing an identity (seed or wallet file) was refused by the Grove's own cross-site request guard. It now sends the guard header like every other change, and a test checks every change the members' page makes for it.
- Three member avatar colours were too light for their white initials. All eight now meet the 4.5:1 contrast standard.

Servers

- `upgrade-from-community.sh` also updates a Grove that was upgraded in place from Community 0.3, which doesn't have the `arynwood-grove` command: run it again with the new release file. The kept folder is named after the version it replaced.

Housekeeping

- Dependency updates within their current versions (React 19.3, Vite 7.3, ESLint 9.39 and others), including the fix for the source-map-js advisory GHSA-68fv-2mgg-jv7q. npm audit and pip-audit report no known vulnerabilities.
- Code changes for the updated React lint rules.

## 0.4.0

Servers and sharing

- One-command server install for Ubuntu and Debian (`deploy/install.sh`): service user, nginx, Let's Encrypt, daily backups, and the `arynwood-grove` command (status, update, rollback, backup, restore, password recovery codes). Updates are checksum-verified, and an update that fails to start is undone automatically.
- The installer prints a setup link with a one-time code, so only the person installing can create the host account.
- A new Grove's first page offers **Join a Grove** (paste an invitation link) or **Create your Grove**.
- **Your Grove's address** (People & identity, host only): enter your domain, see the DNS record to add, and move the Grove there with HTTPS; the old address forwards. Also `sudo arynwood-grove set-domain`.
- The IRC page connects to irc.arynwood.com (`#general`) by default.
- Public invite links: one reusable link per space that anyone can use to join, which the owner can replace or turn off. One address can open only a few accounts through it in 15 minutes.
- Live updates: a change by anyone reaches every open page in the space within about a second, instead of on the next poll.
- `GROVE_PUBLIC_URL` makes invite links name the server's address.
- `deploy/upgrade-from-community.sh` upgrades a Community 0.3 server in place. Members stay signed in, 0.3 invitation links keep working, and `COMMUNITY_*` settings and `community.sqlite3` are still read.

Design

- The Grove look: charcoal surfaces and green-teal light from the tree logo. The page for members is Community only, with a calendar-first layout and a day planner.

Fixes

- Password recovery through a host-issued code (`arynwood-grove recovery-code`).

## 0.3.0

Design

- New Arynwood look: medium-dark grays, with light teal for actions and plum and slate for highlights, all taken from the tree logo. The tree logo appears in the sidebar, sign-in screen, Today banner, favicon and desktop icon.
- Peer-to-peer messaging is now called **Message** throughout the app (address, identity, Go online). The old `/p2p` address redirects to `/message`.

Fixes

- The product stylesheet was missing, so every page rendered unstyled. The full design is now in place, including the phone layout and the mobile menu.
- Members saw a stray “0” in the sidebar.
- Invite links now work for people who already have an account, and for people who are already signed in. Signing up through an invite no longer reports “Invite expired”.
- People with no spaces were stuck on “Opening your space…”. They now get a “Start a space” screen.
- An expired session now returns you to sign-in instead of failing silently.
- Google Fonts was blocked by the app’s own Content Security Policy. Fonts are now local-first.
- Background polling moved keyboard focus while a dialog was open. Escape closed every open dialog at once.
- Non-owners saw an invite button that always failed.
- Message: the page crashed when browser storage was full. Peers could send non-image content for image display. Incoming messages were missed while you were on other pages.
- IRC: a `/nick` collision after connecting renamed you to the wrong nick. Values from the browser could inject extra IRC commands.
- Mail: server errors were hidden, and the inbox showed as empty. Mail requests blocked the server. The app picked a hard-coded personal address as the default account. Account names were not validated.
- `HEAD` requests to pages returned 405.

Additions

- Settings: people in the space, owners can remove members, members can leave, password change, and connection status.
- Search in the top bar, space creation, a space switcher that remembers your choice, and chat that scrolls to the newest message.
- In-app mail compose and reply over SMTP.
- Unread badges for IRC and Message.
- Desktop launcher and installer (`desktop/`).
- 21 backend tests (up from 4), and an end-to-end browser pass on desktop and phone sizes.

Housekeeping

- Removed 648 lines of unused code (the old browser-only calendar page).
- Removed Tailwind, which was not used.
- Pinned Python dependencies. Fixed all npm audit findings (frontend and the Message bridge are now at 0). pip-audit reports no known vulnerabilities.
- The database, wallet, IRC config and `.env` are created readable by your user only.
- Built assets are cached long-term; pages are always revalidated.

## Still before a public beta

- Automated backups and a restore command
- Import from a JSON export, with validation and schema migrations
- Email delivery for invites, and password recovery (needs SMTP on the host)
- Audit history for membership changes and deletions
- Attachments, with storage limits
- A documented HTTPS deployment (reverse proxy config), plus update checks
- Manual testing on mobile Safari and Android Chrome, and with a live IMAP account, IRC server and Message contact

## Product decisions

- Spaces are the main product boundary. Members see only spaces they joined.
- Mail, IRC, and Message are host connections. They are not exposed as shared credentials.
- The release favors reliable local ownership over broad integrations.
- Public messaging should stay short: “Stay in touch. Make plans. Keep things in order.”
