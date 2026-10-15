"""The activity log: who did what, where and when, for the Grove's owners and managers.

Each row is written in the transaction that makes the change, so a change and its record
stand or fall together. Private items are logged without their titles: only their author
may read them, so the log says only that they exist."""
import json
from datetime import datetime, timezone


def name_of(c, table, key):
    row = c.execute(f'SELECT name FROM {table} WHERE id=?', (key,)).fetchone() if key else None
    return row['name'] if row else ''


def record(c, action, actor=None, space=None, target=None, target_name=None, **details):
    """`target` is a person, named from their account, unless `target_name` is given (an item)."""
    c.execute('INSERT INTO activity (at,action,actor_id,actor_name,space_id,space_name,target_id,target_name,details) VALUES (?,?,?,?,?,?,?,?,?)',
              (datetime.now(timezone.utc).isoformat(), action, actor, name_of(c, 'users', actor), space, name_of(c, 'spaces', space),
               target, name_of(c, 'users', target) if target_name is None else target_name, json.dumps(details)))


def summary(entry):
    """What the log keeps of an item: a shared one's title or opening words; a private one's, nothing."""
    if entry['visibility'] == 'private': return ''
    text = entry['title'] or ' '.join(entry['body'].split())
    return text if len(text) <= 120 else text[:119] + '…'
