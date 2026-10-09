"""Data tasks for the arynwood-grove command. Runs as the grove user, on the server only."""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.getenv('GROVE_ENV_FILE', '/etc/arynwood-grove/grove.env'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.community.store import database_path, public_origin, initialize, db  # noqa: E402
from backend.community.recovery import issue_reset  # noqa: E402


def backup(keep):
    source = database_path()
    if not source.exists():
        print('No database yet, so there is nothing to back up.')
        return
    folder = source.parent / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    target = folder / f'grove-{time.strftime("%Y%m%d-%H%M%S")}.sqlite3'
    # SQLite's online backup: a consistent copy while the service keeps running.
    with sqlite3.connect(source) as live, sqlite3.connect(target) as copy:
        live.backup(copy)
    os.chmod(target, 0o600)
    for old in sorted(folder.glob('grove-*.sqlite3'))[:-keep]:
        old.unlink()
    print(target)


def setup_link():
    initialize()
    with db() as c:
        accounts = c.execute('SELECT count(*) FROM users').fetchone()[0]
    if accounts:
        print('This Grove already has a host account. Sign in at ' + (public_origin() or 'its address') + '/community')
        return
    code = os.getenv('GROVE_SETUP_CODE', '').strip()
    print(f'{public_origin()}/community?setup={code}' if code else f'{public_origin()}/community')
    if code: print(f'Setup code: {code}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('path', help='print the database file')
    run_backup = commands.add_parser('backup', help='copy the database into backups/')
    run_backup.add_argument('--keep', type=int, default=14)
    commands.add_parser('setup-link', help='print the link that creates the host account')
    recovery = commands.add_parser('recovery-code', help='issue a 15-minute password reset code')
    recovery.add_argument('email')
    args = parser.parse_args()
    if args.command == 'path': print(database_path())
    elif args.command == 'backup': backup(max(1, args.keep))
    elif args.command == 'setup-link': setup_link()
    else:
        try: print(issue_reset(args.email))
        except ValueError as error: parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
