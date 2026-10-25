"""Notes on the Grove's websites: anyone who can preview a site points at a spot on a page and says
what should change there, or suggests new wording; its owners and webmasters reply, make the
change and mark the note done.

Everyone in the Grove previews its websites, so everyone sees and leaves notes. A note keeps where
it points: the page, a path to the element and the words it held, so its pin finds its place again
after small edits. Open previews hear about every change at once: the Grove's website channel
rides on each signed-in person's Messages stream (messages.py)."""
from collections import defaultdict
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from .auth import user, looks_after_website, identifier, now
from .store import db
from .activity import record
from . import files, live, website

router = APIRouter()
NOTE = '''SELECT n.id,n.space_id,n.folder,n.page,n.selector,n.quote,n.x,n.y,n.device,n.body,n.suggestion,n.status,
          n.author_id,COALESCE(a.name,'') AS author,n.created,COALESCE(b.name,'') AS closed_by,n.closed
          FROM site_notes n LEFT JOIN users a ON a.id=n.author_id LEFT JOIN users b ON b.id=n.closed_by'''

def notes(c, sid, folder):
    replies = defaultdict(list)
    for r in c.execute('''SELECT r.id,r.note_id,r.author_id,COALESCE(u.name,'') AS author,r.body,r.created FROM site_note_replies r
                          JOIN site_notes n ON n.id=r.note_id LEFT JOIN users u ON u.id=r.author_id
                          WHERE n.space_id=? AND n.folder=? ORDER BY r.created''', (sid, folder)):
        replies[r['note_id']].append(dict(r))
    return [{**dict(n), 'replies': replies[n['id']]} for n in c.execute(NOTE + ' WHERE n.space_id=? AND n.folder=? ORDER BY n.created', (sid, folder))]

def summary(text):
    text = ' '.join(text.split())
    return text if len(text) <= 120 else text[:119] + '…'

@router.get('/review')
def review(space_id: str, folder: str, current=Depends(user)):
    """A website as its preview pane needs it: its pages, its notes, and a mark that changes with its files."""
    with db() as c:
        folder = website.a_site(c, space_id, folder)
        where, args = files.inside(folder)
        rows = c.execute(f"SELECT folder,name,version,updated FROM files WHERE space_id=? AND kind='file' AND deleted IS NULL AND {where}", (space_id, *args)).fetchall()
        paths = [files.joined(r['folder'], r['name'])[len(folder) + 1:] for r in rows]
        space = c.execute('SELECT name FROM spaces WHERE id=?', (space_id,)).fetchone()
        return {'space_id': space_id, 'space_name': space['name'], 'folder': folder, 'name': folder[len('Website/'):],
                'pages': sorted((p for p in paths if p.lower().endswith(('.html', '.htm'))), key=lambda p: (p.count('/'), p != 'index.html', p.lower())),
                'changed': f"{len(rows)}:{sum(r['version'] for r in rows)}:{max((r['updated'] for r in rows), default='')}",
                'notes': notes(c, space_id, folder)}

class NoteBody(BaseModel):
    space_id: str = Field(min_length=1, max_length=64)
    folder: str = Field(min_length=1, max_length=4200)
    page: str = Field(default='/', min_length=1, max_length=2000)
    selector: str = Field(default='', max_length=2000)
    quote: str = Field(default='', max_length=1000)
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    device: Literal['', 'phone', 'tablet', 'computer'] = ''
    body: str = Field(default='', max_length=5000)
    suggestion: str | None = Field(default=None, max_length=5000)

    @field_validator('page')
    @classmethod
    def an_address(cls, value):
        if not value.startswith('/') or any(ch in value for ch in '\x00\r\n'): raise ValueError('Give the page’s address, starting with /.')
        return value

    @field_validator('body', 'quote', 'selector')
    @classmethod
    def trimmed(cls, value): return value.strip()

@router.post('/notes', status_code=201)
def add_note(body: NoteBody, current=Depends(user)):
    """Leaves a note, or suggested wording, on a page of a space's website."""
    suggestion = body.suggestion if body.suggestion is not None and body.suggestion.strip() and body.suggestion.strip() != body.quote else None
    if not body.body and suggestion is None: raise HTTPException(422, 'Say what should change, or suggest new wording.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        folder = website.a_site(c, body.space_id, body.folder)
        nid = identifier()
        c.execute('''INSERT INTO site_notes (id,space_id,folder,page,selector,quote,x,y,device,body,suggestion,author_id,created)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (nid, body.space_id, folder, body.page, body.selector, body.quote, body.x, body.y, body.device, body.body, suggestion, current['id'], now()))
        record(c, 'site_note_added', actor=current['id'], space=body.space_id, target=nid, target_name=folder, page=body.page,
               note=summary(body.body or f'Change “{summary(body.quote)}” to “{summary(suggestion)}”'))
        saved = dict(c.execute(NOTE + ' WHERE n.id=?', (nid,)).fetchone(), replies=[])
    live.publish(live.WEBSITE)
    return saved

def a_note(c, nid):
    row = c.execute('SELECT * FROM site_notes WHERE id=?', (nid,)).fetchone()
    if not row: raise HTTPException(404, 'That note was deleted.')
    return row

def may_close(current, note):
    if note['author_id'] != current['id'] and not looks_after_website(current):
        raise HTTPException(403, 'Only whoever left this note, and the website’s owners and webmasters, can do this.')

class ReplyBody(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

@router.post('/notes/{nid}/replies', status_code=201)
def reply(nid: str, body: ReplyBody, current=Depends(user)):
    """Replies to a website note."""
    if not body.body.strip(): raise HTTPException(422, 'Write a reply first.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        a_note(c, nid)
        rid, stamp = identifier(), now()
        c.execute('INSERT INTO site_note_replies VALUES (?,?,?,?,?)', (rid, nid, current['id'], body.body.strip(), stamp))
    live.publish(live.WEBSITE)
    return {'id': rid, 'note_id': nid, 'author_id': current['id'], 'author': current['name'], 'body': body.body.strip(), 'created': stamp}

class StatusBody(BaseModel):
    status: Literal['open', 'done']

@router.put('/notes/{nid}')
def set_status(nid: str, body: StatusBody, current=Depends(user)):
    """Marks a website note done, or open again: whoever left it, or the website's owners and webmasters."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        note = a_note(c, nid)
        may_close(current, note)
        if note['status'] != body.status:
            done = body.status == 'done'
            c.execute('UPDATE site_notes SET status=?,closed_by=?,closed=? WHERE id=?', (body.status, current['id'] if done else None, now() if done else None, nid))
            record(c, 'site_note_done' if done else 'site_note_reopened', actor=current['id'], space=note['space_id'], target=nid, target_name=note['folder'],
                   page=note['page'], note=summary(note['body'] or note['quote']))
        saved = dict(c.execute(NOTE + ' WHERE n.id=?', (nid,)).fetchone())
    live.publish(live.WEBSITE)
    return saved

@router.delete('/notes/{nid}')
def delete_note(nid: str, current=Depends(user)):
    """Deletes a website note: whoever left it, or the website's owners and webmasters."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        note = a_note(c, nid)
        may_close(current, note)
        c.execute('DELETE FROM site_notes WHERE id=?', (nid,))
        record(c, 'site_note_deleted', actor=current['id'], space=note['space_id'], target=nid, target_name=note['folder'],
               page=note['page'], note=summary(note['body'] or note['quote']))
    live.publish(live.WEBSITE)
    return {'ok': True}
