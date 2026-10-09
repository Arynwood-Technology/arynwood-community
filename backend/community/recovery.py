"""Recovery requires access to the host machine, never an unauthenticated HTTP grant."""
import secrets
import time
from .auth import digest
from .store import db, database_path, initialize


def issue_reset(email: str) -> str:
    if not database_path().is_file():
        raise ValueError('No Community database exists on this host.')
    initialize()
    token = secrets.token_urlsafe(32)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT id FROM users WHERE email=?', (email.strip().lower(),)).fetchone()
        if not row:
            raise ValueError('Account not found on this host.')
        c.execute('DELETE FROM password_resets WHERE user_id=? OR expires<?', (row['id'], time.time()))
        c.execute('INSERT INTO password_resets VALUES (?,?,?)', (digest(token), row['id'], time.time()+900))
    return token


def main():
    import argparse
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    parser = argparse.ArgumentParser(description='Issue a one-use, 15-minute Community password reset code. Run only on the trusted host.')
    parser.add_argument('email', help='Account email on this Community instance')
    args = parser.parse_args()
    try:
        token = issue_reset(args.email)
    except ValueError as error:
        parser.exit(1, str(error)+'\n')
    print('Enter this code in Community → Forgot password. Keep it private; it expires in 15 minutes.')
    print(token)


if __name__ == '__main__':
    main()
