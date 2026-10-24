# Security policy

## Supported versions

Only the latest release line of Arynwood Grove gets security fixes. Today that is **0.7.x**.
If you run an older Grove, update with `sudo arynwood-grove update` before reporting. The problem
may already be fixed.

| Version | Security fixes |
|---|---|
| 0.7.x (latest) | Yes |
| Anything older | No, please update |

## Reporting a vulnerability

Report it privately through GitHub's private vulnerability reporting:
**https://github.com/Arynwood-Technology/arynwood-community/security/advisories/new**

Please don't open a public issue, start a discussion or post in a Grove's chat about it. A private
report lets us fix the problem before anyone else learns of it.

This policy covers the Grove software in this repository: the server, the members' page, the
installer and the `arynwood-grove` command. If the problem is with one particular Grove's setup
rather than the software, tell that Grove's host instead.

Test only on a Grove you run yourself, or one whose host has said yes. Don't read, change or
delete other people's data, and stop as soon as you have shown the problem.

## What to include

- The Grove version (shown in Settings, or at `/api/health`) and how it is installed (server
  installer, desktop, or from source).
- What an attacker can do, and what they need first (an account, a role, a link).
- Steps to reproduce it, with the requests or a small proof of concept.
- Anything you know about a fix.

## What happens next

- We acknowledge your report within **7 days**.
- We confirm the problem, decide how serious it is, and keep you told of progress in the report.
- We aim to fix critical problems in the next patch release, and publish a GitHub security
  advisory with it. We credit you there unless you'd rather not be named.

## Bug bounty

There is no bug bounty program at this time.
