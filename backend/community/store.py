"""Persistent community data. All records belong to an explicit space."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
VERSION = '0.4.1'

def setting(name, default=''):
    """GROVE_<name>, else COMMUNITY_<name>: an Arynwood Community 0.3 install keeps its .env when upgraded."""
    value = os.getenv('GROVE_' + name)
    if value is None: value = os.getenv('COMMUNITY_' + name)
    return default if value is None else value

def database_path():
    directory = Path(setting('DATA_DIR') or ROOT / 'data')
    # Community 0.3 kept its data in community.sqlite3; an upgraded install goes on using it.
    current, legacy = directory / 'grove.sqlite3', directory / 'community.sqlite3'
    return legacy if legacy.exists() and not current.exists() else current

def public_origin():
    """The address members use to reach this Grove (GROVE_PUBLIC_URL, e.g. https://grove.example.com
    on a VPS). Empty when the Grove is only reachable on this computer."""
    configured = os.getenv('GROVE_PUBLIC_URL', '').strip()
    parts = urlsplit(configured)
    if not configured:
        # A hosted Community 0.3 install named its public HTTPS address in COMMUNITY_ORIGIN.
        parts = urlsplit(os.getenv('COMMUNITY_ORIGIN', '').split(',')[0].strip())
        if parts.scheme != 'https': return ''
    if parts.scheme not in ('http', 'https') or not parts.hostname: return ''
    return f'{parts.scheme}://{parts.netloc}'

@contextmanager
def db():
    path = database_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def initialize():
    with db() as c:
        c.execute('PRAGMA journal_mode = WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
          expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS spaces (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS members (
          space_id TEXT REFERENCES spaces(id) ON DELETE CASCADE,
          user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK(role IN ('owner','member')), PRIMARY KEY(space_id,user_id));
        CREATE TABLE IF NOT EXISTS invites (
          token TEXT PRIMARY KEY, space_id TEXT REFERENCES spaces(id) ON DELETE CASCADE,
          expires REAL NOT NULL, created_by TEXT REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS entries (
          id TEXT PRIMARY KEY, space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
          author_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
          title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
          visibility TEXT NOT NULL DEFAULT 'shared', parent_id TEXT REFERENCES entries(id) ON DELETE CASCADE,
          done INTEGER NOT NULL DEFAULT 0, due TEXT NOT NULL DEFAULT '',
          assigned_to TEXT REFERENCES users(id), created TEXT NOT NULL, updated TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1);
        CREATE INDEX IF NOT EXISTS entries_space ON entries(space_id,kind,updated);
        CREATE TABLE IF NOT EXISTS password_resets (
          token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS invite_links (
          space_id TEXT PRIMARY KEY REFERENCES spaces(id) ON DELETE CASCADE,
          token TEXT NOT NULL UNIQUE, created TEXT NOT NULL,
          created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS attempts (key TEXT NOT NULL, at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS attempts_key ON attempts(key,at);
        PRAGMA user_version = 1;
        ''')
    os.chmod(database_path(), 0o600)
