# Contributing to Arynwood Grove

Thank you for helping. This page says how changes get in, and what a change needs.

## Reporting bugs and asking for features

Open an issue: https://github.com/Arynwood-Technology/arynwood-community/issues. Say which version
you run (Settings, or `/api/health`), how it is installed, what you did, what you expected and
what happened instead.

**Security problems are different.** Don't open an issue for them. Follow
[SECURITY.md](SECURITY.md) and report them privately.

## Proposing a change

1. For anything bigger than a small fix, open an issue first, so we can agree on the approach
   before you spend time on it.
2. Fork the repository, make your change on a branch, and open a pull request against `main`.
3. Each pull request is reviewed before it is merged. The checks below must pass.

Contributions are accepted under the project's licence, the GNU AGPL-3.0 (see `LICENSE`).

## What a change needs

- **Tests.** New features and bug fixes come with tests that cover them: backend changes in
  `tests/` (Python `unittest`), changes to the members' page in a `*.test.ts(x)` file beside the
  code (Vitest). A bug fix includes a test that fails without the fix. Tests never contact live
  mail, IRC or other outside services.
- **Clean lint.** `npm --prefix frontend run lint` reports nothing, and TypeScript stays in
  `strict` mode.
- **No weaker protections.** Keep the Content Security Policy, cookie flags, origin checks and rate
  limits at least as strict as they are. Load nothing from other sites: no CDN scripts, styles or
  fonts.
- **Pinned dependencies.** `requirements.txt` pins exact versions; `frontend/package-lock.json` is
  committed. Add a dependency only when it is needed, and say why in the pull request.

## Running the checks

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
npm --prefix frontend ci
npm --prefix frontend run lint && npm --prefix frontend test && npm --prefix frontend run build
```

Dependency audits, which should report nothing:

```bash
npm --prefix frontend audit
pip-audit -r requirements.txt -r requirements-dev.txt   # pip install pip-audit, in any venv
```

Every push to `main` and every pull request runs the tests, lint, build and installer check
above (`.github/workflows/ci.yml`).

## Releases

- The version lives in `backend/community/store.py` (`VERSION`) and `frontend/package.json`, and
  the two must match.
- Each release adds a section at the top of `docs/PRERELEASE.md` saying what changed. It becomes the
  GitHub release's notes. Security fixes are listed there, with their advisory or CVE identifier
  when they have one.
- Pushing a tag `v<version>` runs `.github/workflows/release.yml`: it checks the version, runs the
  tests and lint, builds the release with `scripts/package.sh`, and publishes it with SHA-256
  checksums.
