"""Persistent community data. All records belong to an explicit space."""
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
VERSION = '0.5.4'

def setting(name, default=''):
    """GROVE_<name>, else COMMUNITY_<name>: an Arynwood Community 0.3 install keeps its .env when upgraded."""
    value = os.getenv('GROVE_' + name)
    if value is None: value = os.getenv('COMMUNITY_' + name)
    return default if value is None else value

def host_tools():
    """Mail, IRC and Private messages use the host's own accounts; a Grove run for someone else turns them off."""
    return setting('HOST_TOOLS', 'on').strip().lower() not in ('off', '0', 'no', 'false')

def log_name():
    """What this Grove calls each space's log of news and updates (GROVE_LOG_NAME, e.g. Event journal)."""
    return ' '.join(setting('LOG_NAME').split())[:40] or 'Updates'

CHAT_ROOM = re.compile(r'[#&][^\s,:\x00-\x1f\x7f]{1,49}')
# An IRC nickname; in GROVE_CHAT_NICK each # becomes a random digit, so members start with distinct names.
CHAT_NICK = re.compile(r'[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}#-]{0,29}')
CHAT_SERVER = re.compile(r'([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)(?::(\d{1,5}))?')

def public_chat():
    """Public chat, open to every member: an IRC room (GROVE_CHAT_CHANNEL) on GROVE_CHAT_SERVER, joined with a
    nickname made from GROVE_CHAT_NICK. None when no room is set."""
    room = setting('CHAT_CHANNEL').strip()
    if not CHAT_ROOM.fullmatch(room): return None
    nick = setting('CHAT_NICK').strip()
    server = CHAT_SERVER.fullmatch(setting('CHAT_SERVER', 'irc.arynwood.com:6697').strip())
    port = int(server[2] or 6697) if server else 6697
    if not server or not 0 < port < 65536: server, port = None, 6697
    return {'channel': room, 'nick': nick if CHAT_NICK.fullmatch(nick) else 'Guest###',
            'server': server[1] if server else 'irc.arynwood.com', 'port': port}

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
        -- A table of its own rather than a column on spaces: 0.4.1 inserts spaces positionally,
        -- so a Grove rolled back to it keeps working on the same database.
        CREATE TABLE IF NOT EXISTS space_topics (
          space_id TEXT PRIMARY KEY REFERENCES spaces(id) ON DELETE CASCADE,
          topic TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (key TEXT NOT NULL, at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS attempts_key ON attempts(key,at);
        -- Grove-wide roles. Anyone without a row is a member; the host (users.admin) is always
        -- an owner. Like topics, these are tables of their own, so a Grove rolled back to 0.4.2
        -- keeps working on the same database.
        CREATE TABLE IF NOT EXISTS grove_roles (
          user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK(role IN ('owner','manager')));
        CREATE TABLE IF NOT EXISTS grove_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        -- Names are kept as they were and nothing cascades into the log, so it outlives the
        -- spaces, items and accounts it mentions.
        CREATE TABLE IF NOT EXISTS activity (
          id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, action TEXT NOT NULL,
          actor_id TEXT, actor_name TEXT NOT NULL DEFAULT '',
          space_id TEXT, space_name TEXT NOT NULL DEFAULT '',
          target_id TEXT, target_name TEXT NOT NULL DEFAULT '',
          details TEXT NOT NULL DEFAULT '{}');
        CREATE INDEX IF NOT EXISTS activity_space ON activity(space_id,id);
        CREATE INDEX IF NOT EXISTS activity_actor ON activity(actor_id,id);
        CREATE INDEX IF NOT EXISTS activity_target ON activity(target_id,id);
        -- Wishes for the Grove itself, from the lamp on every page. Each is kept here, and emailed
        -- to GROVE_WISH_EMAIL when the server can send mail ('kept' when it was not).
        CREATE TABLE IF NOT EXISTS wishes (
          id TEXT PRIMARY KEY, created TEXT NOT NULL,
          author_id TEXT REFERENCES users(id) ON DELETE SET NULL, author_name TEXT NOT NULL, author_email TEXT NOT NULL,
          page TEXT NOT NULL DEFAULT '', space_name TEXT NOT NULL DEFAULT '', body TEXT NOT NULL,
          delivery TEXT NOT NULL CHECK(delivery IN ('kept','sending','sent','failed')));
        -- The file bank (files.py). A row is a file or a folder at a path in its space; a file's
        -- contents are a blob named by its SHA-256. Deleted rows wait in the trash, marked with
        -- the item that was deleted (trash_root), so a folder comes back with what was in it.
        CREATE TABLE IF NOT EXISTS files (
          id TEXT PRIMARY KEY, space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
          folder TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('file','folder')),
          blob TEXT, size INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
          author_id TEXT REFERENCES users(id) ON DELETE SET NULL, updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
          created TEXT NOT NULL, updated TEXT NOT NULL, deleted TEXT, trash_root TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS files_path ON files(space_id,folder,name) WHERE deleted IS NULL;
        CREATE INDEX IF NOT EXISTS files_trash ON files(space_id,trash_root);
        -- Earlier versions of a file; the current one is on its files row.
        CREATE TABLE IF NOT EXISTS file_versions (
          file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE, version INTEGER NOT NULL,
          blob TEXT NOT NULL, size INTEGER NOT NULL, author_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          created TEXT NOT NULL, PRIMARY KEY(file_id,version));
        CREATE TABLE IF NOT EXISTS uploads (
          id TEXT PRIMARY KEY, space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, folder TEXT NOT NULL, name TEXT NOT NULL,
          size INTEGER NOT NULL, received INTEGER NOT NULL DEFAULT 0, replaces TEXT, started REAL NOT NULL);
        -- Blobs no file refers to any more, and since when. They are removed only once no
        -- backup (14 are kept) can still name them.
        CREATE TABLE IF NOT EXISTS orphan_blobs (blob TEXT PRIMARY KEY, since REAL NOT NULL);
        -- Website imports (webmaster.py): one row per run, with what it brought in and what it left.
        CREATE TABLE IF NOT EXISTS site_imports (
          id TEXT PRIMARY KEY, space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
          user_id TEXT REFERENCES users(id) ON DELETE SET NULL, url TEXT NOT NULL, folder TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('running','done','failed')),
          added INTEGER NOT NULL DEFAULT 0, changed INTEGER NOT NULL DEFAULT 0, unchanged INTEGER NOT NULL DEFAULT 0,
          skipped INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '{}',
          message TEXT NOT NULL DEFAULT '', started TEXT NOT NULL, finished TEXT);
        CREATE TABLE IF NOT EXISTS workspace_setups (
          space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
          kit TEXT NOT NULL, client TEXT NOT NULL, opening_date TEXT NOT NULL DEFAULT '',
          created TEXT NOT NULL, created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
          PRIMARY KEY(space_id,kit));
        PRAGMA user_version = 1;
        ''')
    os.chmod(database_path(), 0o600)

# A person's Grove-wide role, for queries joining users u with grove_roles r.
GROVE_ROLE = "CASE WHEN u.admin THEN 'owner' ELSE COALESCE(r.role,'member') END"

def grove_setting(c, key, default):
    row = c.execute('SELECT value FROM grove_settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default
