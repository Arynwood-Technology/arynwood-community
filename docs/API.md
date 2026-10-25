# API reference

Everything a Grove accepts and answers over HTTP and WebSocket, and who may call each part. The members'
page uses this API, and so does Arynwood MCP's Community page, which passes its requests through to it.

- [HTTP and WebSocket reference](api/http/README.md): every route, by area, with who may call it, its
  parameters, request body, response and errors. Generated from the Grove itself.
- [`api/openapi.json`](api/openapi.json): the machine-readable OpenAPI document. A running Grove doesn't
  serve it (`openapi_url`, `/docs` and `/redoc` are off; the interactive pages load from a CDN), so it is
  kept here. Open it in any OpenAPI viewer you run yourself.

This page covers what the generated pages can't show: signing in, the roles, the checks every request
passes, the WebSocket messages, uploads and the server's command line.

## Signing in

A browser signs in with [`POST /api/auth/login`](api/http/auth.md#post-api-auth-login) (or creates an
account with [`POST /api/auth/signup`](api/http/auth.md#post-api-auth-signup)) and gets the session cookie
`grove_session`: `HttpOnly`, `SameSite=Strict`, `Secure` when the Grove is reached over HTTPS, valid for 14
days. Every route marked anything but "Anyone" needs it; without a valid session the answer is `401 Sign in
to continue.` There are no API keys and no password reset by email: the host gives a person a reset code
(`sudo arynwood-grove recovery-code <email>`), which they use at
[`POST /api/auth/password/reset`](api/http/auth.md#post-api-auth-password-reset).

The first account on a new Grove is the host's. The installer prints a setup code; signing up without it is
refused while no account exists. Every later account needs an invitation or a space's public link.

## Who may call what

Each route in the reference names who may call it. Grove-wide roles come from `backend/community/auth.py`:

| Reference says | Who that is | Checked by |
|---|---|---|
| Anyone | No sign-in: health, the source code offer, the Grove's name and pictures, sign-up, sign-in, sign-out, password reset, the members' page and the published website | nothing |
| Signed address | Whoever holds a website preview's signed address; no account is involved | the signature |
| Member | Any signed-in person | `user` |
| Space member | A member of the space in the path (others get `404 Space not found.`, so a space's existence isn't revealed) | `membership()` |
| Space owner | An owner of that space (`403 Space owner access required.`) | `membership(owner=True)` |
| Webmaster | The Grove's owners and the webmasters they choose | `webmaster` |
| Grove manager | The Grove's owners and managers: they see what owners see, but change no roles or Grove settings | `grove_manager` |
| Grove owner | The Grove's owners | `grove_owner` |
| Host | The host's account only: mail, IRC, the domain helper and the owner tools | `administrator` |

**Host-only** (the host's account): everything under `/api/mail`, `/api/irc`, `/api/grove` and
`/api/grove-setup`, plus `/api/community/connections`. Mail and IRC are also turned off, answering 404,
when the Grove runs with `GROVE_HOST_TOOLS=off` (a Grove hosted for someone else).

**Grove-wide administration** (Grove owners or managers, not every member): `/api/admin`, the look under
`/api/brand/look`, and the website tools under `/api/webmaster` that publish, import or take the site down.

**Member-accessible** (any signed-in member, within their own spaces): spaces, items, files, the editor,
Messages, wishes, Public chat, and leaving notes on a website preview. Inside a space, some changes need
more than membership: editing or deleting someone else's item needs a space owner; private items are only
ever shown to their author. Each route's errors list those refusals with their messages.

## Errors

Errors are JSON, `{"detail": "<message>"}`, with the HTTP status. Each route lists the errors it and the
helpers it calls raise. A `422` for a request that doesn't match the documented parameters or body carries
FastAPI's list instead: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`.

Every request also passes these checks (`backend/api.py`):

| Status | Detail | When |
|---|---|---|
| 400 | `Invalid host header` | The `Host` isn't `localhost`, `127.0.0.1`, `[::1]`, a name in `GROVE_HOSTS`, or the host of `GROVE_PUBLIC_URL` |
| 403 | `Request blocked. Reload and try again.` | A request other than GET/HEAD/OPTIONS without the header `X-Community-Request: 1`, or with an `Origin` that isn't the Grove's own (`GROVE_PUBLIC_URL`, `GROVE_ORIGIN`, or the same host) |
| 429 | `Try again in 15 minutes.` | Too many sign-in, sign-up or password attempts from one address |

A WebSocket whose `Origin` isn't the Grove's own is closed with code 1008. Answers under `/api` carry
`Cache-Control: no-store`; every answer carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`
(unless the route sets its own) and a `Content-Security-Policy`; files and photos come with `sandbox`.

The members' page in a development checkout reaches the API as `/community-api/...`; the Grove answers
that prefix as `/api/...`.

## Live notices

[`GET /api/community/spaces/{sid}/events`](api/http/routes.md#get-api-community-spaces-sid-events) and
[`GET /api/messages/events`](api/http/messages.md#get-api-messages-events) are server-sent event streams.
Each event carries only an `id` (a revision) and a name: `ready` on connecting, `changed` when something the
page shows has changed, which the page answers by fetching again. Send `Last-Event-ID` when reconnecting:
a stream that missed a change starts with `changed`. The stream re-checks the session and membership
before every notice, ends itself about every half minute (the browser reconnects after 1.5 s), and one
person may keep up to 12 open.

## Uploads in pieces

Files (a space's Files, and attachments in Messages) go up in pieces, so a large one survives a dropped
connection: start the upload (`POST .../uploads`, with name and size; the size is checked against the
space's room first), `PUT .../uploads/{id}?offset=N` with each piece as the raw body (at most 8 MB; pages
send 4 MB), `GET .../uploads/{id}` to learn how much has arrived and resume, then `POST
.../uploads/{id}/finish`. A space upload left unfinished is forgotten after a day.

## WebSockets

### Public chat (`/api/chat/ws`)

Members only, and only on a Grove with a Public chat room; at most two windows per member. Send
`{"nick": "<name>"}` first, within 30 seconds (up to 30 letters, numbers, `-` and `_`, starting with a
letter). Then send `{"cmd": "<an IRC line>"}`. Commands stay in the Grove's room: messages to the room
or to a person, joining, leaving and naming within it, and a few harmless ones (NICK, AWAY, WHO, WHOIS);
anything else is refused and the reason comes back as a `status`. Receive `{"type": "irc", "msg": "<a line from the IRC server>"}`,
`{"type": "status", "message"}`, `{"type": "error", "message"}` and `{"type": "disconnect", "message"}`.

### Host IRC (`/api/irc/ws`)

The host only. Send the connection first, within 30 seconds: `{"host", "port", "nick", "nick_password"?,
"channels": [...], "realname"?}` (a missing password is taken from the saved settings for that nick).
Then the same messages as Public chat, without the room's limits.

## Command line (on a server)

| Command | What it does |
|---|---|
| `install.sh --domain NAME --email ADDRESS` | Installs or updates a Grove on Ubuntu or Debian ([deploy/README.md](../deploy/README.md) has every option) |
| `sudo arynwood-grove status \| update \| rollback \| backup \| restore \| logs` | Runs a Grove on its server |
| `sudo arynwood-grove recovery-code <email>` | A 15-minute password reset code |
| `sudo arynwood-grove set-domain <name>` | Moves the Grove to a domain |
| `sudo arynwood-grove help` | Everything else, including off-server copies and more Groves on one server |

## How this reference is made

```bash
.venv/bin/python scripts/gen_api_reference.py          # rewrite docs/api/http/ and docs/api/openapi.json
.venv/bin/python scripts/gen_api_reference.py --check  # fail if they are out of date
```

The generator imports the Grove with a throwaway data folder, takes FastAPI's OpenAPI document (built in
memory, never served) for methods, paths, parameters, request bodies and descriptions (the handlers'
docstrings), and reads each handler's source for the rest: the response shape (return statements and the
columns of a returned database row), the errors (the `HTTPException`s the handler, its dependencies and the
helpers it calls raise), and who may call it (the auth dependencies above and the `membership()` checks).
`tests/test_api_reference.py` fails when the pages are out of date or a route has no section.

The response descriptions are read from code, not from a typed schema: a field list says which keys the
handler builds, not each value's type. One operation's response is shown as the expression its handler
returns. This page is written by hand from `backend/api.py`, `backend/community/auth.py`,
`backend/community/live.py`, `backend/community/files.py`, `backend/routers/chat.py` and
`backend/routers/irc.py`; when they change, change it too.
