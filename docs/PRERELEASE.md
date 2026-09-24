# Arynwood Community release notes

Version: `0.3.0`

Positioning: a private home for a group’s messages, plans, household work, lists, and notes. The product promise is “Your people. Your place.”

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
