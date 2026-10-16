"""Owner-applied workspace kits; additions and receipt commit together exactly once."""
import hashlib
import os
import re
import shutil
import tempfile
from datetime import date, datetime, time, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from . import files, live
from .activity import record
from .auth import identifier, now, user
from .routes import membership, logged
from .store import db
from .workspace_kits import CATALOG, kit_content, csv_text

router = APIRouter()

class SetupBody(BaseModel):
    kit: str
    client: str = Field(min_length=1, max_length=80)
    opening_date: date | None = None

    @field_validator('client')
    @classmethod
    def client_name(cls, value):
        value = ' '.join(value.split())
        if not value: raise ValueError('Enter the client or project name.')
        return value


def plan(body):
    if body.kit not in CATALOG: raise HTTPException(404, 'Workspace kit not found.')
    content = kit_content(body.kit, body.client)
    entries = []
    for title, (lead, items) in content['lists'].items():
        key = f'list-{len(entries)}'
        entries.append({'key': key, 'kind': 'list', 'title': title, 'body': f'Proposed lead: {lead}. Assign a person and confirm the checklist with the producer. Use Tasks for individual assignments and due dates.'})
        entries.extend({'kind': 'item', 'title': title, 'parent': key} for title in items)
    for title, text in content['docs'].items():
        entries.append({'kind': 'note', 'title': title, 'body': text.replace('{client}', body.client)})
    entries.append({'kind': 'board', 'title': f'{body.client} — producer decisions & weekly updates'[:200], 'body': 'Post approved decisions, upcoming deadlines, department status, budget changes, blockers and accountable next actions here. Include the approver, owner and review date.'})
    entries.extend({'kind': 'task', 'title': title, 'body': 'Producer setup action. Assign the responsible team member and confirm a deadline.'} for title in ['Assign department leads and approve workspace access','Confirm festival dates and add approved events to Calendar' if body.kit == 'film-festival' else 'Confirm project milestones and add approved events to Calendar','Confirm reporting currency and enter approved budget figures','Review all staged checklists and replace role suggestions with real owners'])
    if body.opening_date and content['milestones']:
        for offset, title in content['milestones']:
            try: day = body.opening_date + timedelta(days=offset)
            except OverflowError: raise HTTPException(422, 'Choose an opening date with room for planning milestones.')
            entries.append({'kind': 'event', 'title': f'PROPOSED — {title}', 'due': datetime.combine(day, time(9)).isoformat(timespec='minutes'), 'body': f'Planning placeholder, not an approved event. Based on opening date {body.opening_date.isoformat()}, offset {offset:+d} days. Confirm actual date, time, timezone, venue, duration and owner. A three-day festival is assumed for closing-day placeholders.'})
    root = content['root']
    folders = [root] + [root + '/' + f for f in content['folders']]
    documents = {root + '/Documents/START-HERE.md': content['docs'][next(iter(content['docs']))].replace('{client}', body.client) + '\n'}
    for title, text in list(content['docs'].items())[1:]:
        name = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') + '.md'
        documents[root + '/Documents/' + name] = text.replace('{client}', body.client) + '\n'
    for path, headers in content['trackers'].items(): documents[root + '/' + path] = csv_text(headers)
    return {'entries': entries, 'folders': folders, 'documents': documents, 'root': root}


def summary(body):
    content = plan(body)
    return {'kit': body.kit, 'name': CATALOG[body.kit][0], 'description': CATALOG[body.kit][1], 'root': content['root'], 'lists': sum(e['kind'] == 'list' for e in content['entries']), 'items': sum(e['kind'] == 'item' for e in content['entries']), 'notes': sum(e['kind'] == 'note' for e in content['entries']), 'events': sum(e['kind'] == 'event' for e in content['entries']), 'tasks': sum(e['kind'] == 'task' for e in content['entries']), 'folders': len(content['folders']), 'files': len(content['documents']), 'spreadsheets': sum(path.endswith('.csv') for path in content['documents']), 'departments': [e['title'] for e in content['entries'] if e['kind'] == 'list'], 'trackers': list(content['documents'])}

@router.get('/spaces/{sid}/workspace-setup')
def catalog(sid: str, current=Depends(user)):
    with db() as c:
        membership(c, sid, current['id'], owner=True)
        installed = [dict(r) for r in c.execute('SELECT kit,client,opening_date,created FROM workspace_setups WHERE space_id=?', (sid,))]
    return {'kits': [summary(SetupBody(kit=key, client='Your team')) for key in CATALOG], 'installed': installed}

@router.post('/spaces/{sid}/workspace-setup/preview')
def preview(sid: str, body: SetupBody, current=Depends(user)):
    with db() as c: membership(c, sid, current['id'], owner=True)
    return summary(body)

@router.post('/spaces/{sid}/workspace-setup', status_code=201)
def apply(sid: str, body: SetupBody, current=Depends(user)):
    content = plan(body)
    stamp = now()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c, sid, current['id'], owner=True)
        if c.execute('SELECT 1 FROM workspace_setups WHERE space_id=? AND kit=?', (sid, body.kit)).fetchone():
            raise HTTPException(409, 'This kit has already been staged in this space. Your team’s edits are kept; use a new space for another edition.')
        # Avoid silently merging into an existing folder tree or truncating the entries view.
        root = content['root']
        if c.execute('SELECT 1 FROM files WHERE space_id=? AND deleted IS NULL AND ((folder=? AND name=?) OR folder=? OR substr(folder,1,?)=?)', (sid, '', root, root, len(root)+1, root+'/')).fetchone():
            raise HTTPException(409, f'{root} already exists. Rename it or choose a new space before staging this kit.')
        if c.execute('SELECT COUNT(*) FROM entries WHERE space_id=?', (sid,)).fetchone()[0] + len(content['entries']) > 2000:
            raise HTTPException(409, 'Choose a new space; this kit would exceed the workspace item limit.')
        data_files = {path: text.encode('utf-8') for path, text in content['documents'].items()}
        size = sum(map(len, data_files.values()))
        if files.used(c, sid) + size > files.space_limit() or any(len(data)>files.file_limit() for data in data_files.values()):
            raise HTTPException(413, 'This space needs more storage before the kit can be staged.')
        files.storage().mkdir(mode=0o700, parents=True, exist_ok=True)
        if shutil.disk_usage(files.storage()).free - size < files.MIN_FREE: raise HTTPException(507, 'The server needs more free space.')
        keys = {}
        for e in content['entries']:
            eid = identifier()
            if 'key' in e: keys[e['key']] = eid
            parent = keys.get(e.get('parent'))
            c.execute('INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (eid, sid, current['id'], e['kind'], e['title'], e.get('body',''), 'shared', parent, 0, e.get('due',''), None, stamp, stamp, 1))
            logged(c, 'entry_created', current, dict(c.execute('SELECT * FROM entries WHERE id=?', (eid,)).fetchone()))
        for path in content['folders']:
            parent, _, name = path.rpartition('/')
            c.execute('INSERT INTO files (id,space_id,folder,name,kind,author_id,updated_by,created,updated) VALUES (?,?,?,?,?,?,?,?,?)', (identifier(), sid, parent, name, 'folder', current['id'], current['id'], stamp, stamp))
        for path, data in data_files.items():
            blob = hashlib.sha256(data).hexdigest()
            target = files.blob_path(blob)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not target.exists():
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
                    staging = temp.name
                    try:
                        temp.write(data); temp.flush(); os.replace(staging, target)
                    finally:
                        if os.path.exists(staging): os.unlink(staging)
            c.execute('DELETE FROM orphan_blobs WHERE blob=?', (blob,))
            parent, _, name = path.rpartition('/')
            c.execute('INSERT INTO files (id,space_id,folder,name,kind,blob,size,author_id,updated_by,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (identifier(), sid, parent, name, 'file', blob, len(data), current['id'], current['id'], stamp, stamp))
        c.execute('INSERT INTO workspace_setups VALUES (?,?,?,?,?,?)', (sid, body.kit, body.client, body.opening_date.isoformat() if body.opening_date else '', stamp, current['id']))
        record(c, 'workspace_staged', actor=current['id'], space=sid, kit=body.kit, client=body.client, entries=len(content['entries']), files=len(data_files), folders=len(content['folders']))
    live.publish(sid)
    return summary(body)
