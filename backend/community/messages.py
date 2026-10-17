"""Messages: private conversations between two members, with photos.

Anyone can write to someone they share a space with. A conversation belongs to the two people
in it: the Grove's owners and managers can't read it, and the activity log doesn't mention it
(the server's operator can still read the database, as with everything here). Photos go up one
at a time before the message that carries them, are kept without their metadata, and are shown
only to the people in the conversation."""
import hashlib
import os
import shutil
import tempfile
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool
from .auth import user, identifier, now, digest, session_token
from .store import db
from . import files, live, photos

router = APIRouter()
PHOTO_MAX = 10 * files.MB      # as sent; members' pages shrink photos well below this
PHOTOS_PER_MESSAGE = 6
TEXT_MAX = 4000
PAGE = 200                     # messages shown at once, newest last

def inbox(uid): return f'inbox:{uid}'

def neighbours(c, uid):
    """Everyone who shares a space with this person."""
    return c.execute('''SELECT DISTINCT u.id,u.name FROM members mine JOIN members theirs ON theirs.space_id=mine.space_id
                        JOIN users u ON u.id=theirs.user_id WHERE mine.user_id=? AND theirs.user_id<>? ORDER BY u.name COLLATE NOCASE''', (uid, uid)).fetchall()

def shares_a_space(c, a, b):
    return c.execute('SELECT 1 FROM members x JOIN members y ON y.space_id=x.space_id WHERE x.user_id=? AND y.user_id=?', (a, b)).fetchone() is not None

def conversation(c, cid, uid):
    """The conversation, if this person is in it; otherwise it doesn't exist for them."""
    row = c.execute('SELECT c.* FROM conversations c JOIN conversation_members m ON m.conversation_id=c.id WHERE c.id=? AND m.user_id=?', (cid, uid)).fetchone()
    if not row: raise HTTPException(404, 'Conversation not found.')
    return row

def other(c, cid, uid):
    return c.execute('SELECT u.id,u.name FROM conversation_members m JOIN users u ON u.id=m.user_id WHERE m.conversation_id=? AND m.user_id<>?', (cid, uid)).fetchone()

def summary(c, row, uid):
    them = other(c, row['id'], uid)
    last = c.execute('''SELECT m.body,m.sender_id,m.created,(SELECT COUNT(*) FROM message_photos p WHERE p.message_id=m.id) AS photos
                        FROM messages m WHERE m.conversation_id=? AND m.deleted IS NULL ORDER BY m.created DESC LIMIT 1''', (row['id'],)).fetchone()
    read = c.execute('SELECT read_at FROM conversation_members WHERE conversation_id=? AND user_id=?', (row['id'], uid)).fetchone()['read_at']
    unread = c.execute('SELECT COUNT(*) FROM messages WHERE conversation_id=? AND deleted IS NULL AND sender_id<>? AND created>?', (row['id'], uid, read)).fetchone()[0]
    preview = '' if not last else last['body'] or ('A photo' if last['photos'] == 1 else f"{last['photos']} photos")
    return {'id': row['id'], 'with': dict(them) if them else {'id': None, 'name': 'Someone who has left'},
            'last': preview, 'last_from_me': bool(last and last['sender_id'] == uid), 'updated': row['updated'], 'unread': unread}

@router.get('/people')
def people(current=Depends(user)):
    with db() as c: return [dict(r) for r in neighbours(c, current['id'])]

@router.get('/conversations')
def conversations(current=Depends(user)):
    with db() as c:
        rows = c.execute('''SELECT c.* FROM conversations c JOIN conversation_members m ON m.conversation_id=c.id
                            WHERE m.user_id=? ORDER BY c.updated DESC''', (current['id'],)).fetchall()
        return [summary(c, r, current['id']) for r in rows]

class StartBody(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)

@router.post('/conversations')
def start(body: StartBody, current=Depends(user)):
    """The conversation with this person: the one there is, or a new one."""
    uid = current['id']
    if body.user_id == uid: raise HTTPException(422, 'Choose someone else to write to.')
    pair = ':'.join(sorted((uid, body.user_id)))
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM conversations WHERE pair=?', (pair,)).fetchone()
        if not row:
            if not shares_a_space(c, uid, body.user_id): raise HTTPException(404, 'You can write to people you share a space with.')
            cid, stamp = identifier(), now()
            c.execute('INSERT INTO conversations VALUES (?,?,?,?)', (cid, pair, stamp, stamp))
            c.executemany('INSERT INTO conversation_members VALUES (?,?,?)', [(cid, uid, ''), (cid, body.user_id, '')])
            row = c.execute('SELECT * FROM conversations WHERE id=?', (cid,)).fetchone()
        return summary(c, row, uid)

def message(c, row):
    shown = [{'id': p['id'], 'width': p['width'], 'height': p['height']} for p in
             c.execute('SELECT id,width,height FROM message_photos WHERE message_id=? ORDER BY created', (row['id'],))]
    return {'id': row['id'], 'sender_id': row['sender_id'], 'body': row['body'] if not row['deleted'] else '',
            'photos': shown if not row['deleted'] else [], 'created': row['created'], 'deleted': bool(row['deleted'])}

@router.get('/conversations/{cid}')
def read(cid: str, current=Depends(user)):
    with db() as c:
        row = conversation(c, cid, current['id'])
        latest = c.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY created DESC LIMIT ?', (cid, PAGE)).fetchall()[::-1]
        them = other(c, cid, current['id'])
        return {**summary(c, row, current['id']), 'messages': [message(c, m) for m in latest],
                'can_write': bool(them) and shares_a_space(c, current['id'], them['id'])}

@router.post('/conversations/{cid}/read')
def seen(cid: str, current=Depends(user)):
    with db() as c:
        conversation(c, cid, current['id'])
        c.execute('UPDATE conversation_members SET read_at=? WHERE conversation_id=? AND user_id=?', (now(), cid, current['id']))
    live.publish(inbox(current['id']))
    return {'ok': True}

class MessageBody(BaseModel):
    body: str = Field(default='', max_length=TEXT_MAX)
    photos: list[str] = Field(default_factory=list, max_length=PHOTOS_PER_MESSAGE)
    @field_validator('body')
    @classmethod
    def trimmed(cls, value): return value.strip()

@router.post('/conversations/{cid}/messages', status_code=201)
def send(cid: str, body: MessageBody, current=Depends(user)):
    uid = current['id']
    if not body.body and not body.photos: raise HTTPException(422, 'Write something, or add a photo.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        conversation(c, cid, uid)
        them = other(c, cid, uid)
        if not them or not shares_a_space(c, uid, them['id']): raise HTTPException(403, 'You no longer share a space with them, so you can’t write here.')
        mine = {r['id'] for r in c.execute(f"SELECT id FROM message_photos WHERE owner_id=? AND message_id IS NULL AND id IN ({','.join('?' * len(body.photos))})", (uid, *body.photos))} if body.photos else set()
        if len(mine) != len(set(body.photos)): raise HTTPException(422, 'A photo is missing. Add it again.')
        mid, stamp = identifier(), now()
        c.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (mid, cid, uid, body.body, stamp, None))
        for order, pid in enumerate(body.photos):
            # Photos keep the order they were chosen in.
            c.execute('UPDATE message_photos SET message_id=?,created=? WHERE id=?', (mid, f'{stamp}#{order:02d}', pid))
        c.execute('UPDATE conversations SET updated=? WHERE id=?', (stamp, cid))
        c.execute('UPDATE conversation_members SET read_at=? WHERE conversation_id=? AND user_id=?', (stamp, cid, uid))
        sent = message(c, c.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone())
    for person in (uid, them['id']): live.publish(inbox(person))
    return sent

@router.delete('/messages/{mid}')
def unsend(mid: str, current=Depends(user)):
    """Takes back a message: its words and photos go for everyone; that something was said stays."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM messages WHERE id=? AND sender_id=?', (mid, current['id'])).fetchone()
        if not row or row['deleted']: raise HTTPException(404, 'Message not found.')
        c.execute("UPDATE messages SET body='',deleted=? WHERE id=?", (now(), mid))
        c.execute('DELETE FROM message_photos WHERE message_id=?', (mid,))
        people = [r['user_id'] for r in c.execute('SELECT user_id FROM conversation_members WHERE conversation_id=?', (row['conversation_id'],))]
    for person in people: live.publish(inbox(person))
    return {'ok': True}

def keep_photo(uid, data):
    try: plain, kind, width, height = photos.plain(data)
    except photos.NotAPhoto as reason: raise HTTPException(415, str(reason))
    files.storage().mkdir(mode=0o700, parents=True, exist_ok=True)
    if shutil.disk_usage(files.storage()).free - len(plain) < files.MIN_FREE: raise HTTPException(507, 'The server is nearly out of space. Tell the host.')
    blob = hashlib.sha256(plain).hexdigest()
    target = files.blob_path(blob)
    if not target.exists():
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as part:
            part.write(plain)
        os.replace(part.name, target)
    pid = identifier()
    with db() as c:
        c.execute('DELETE FROM orphan_blobs WHERE blob=?', (blob,))
        c.execute('INSERT INTO message_photos (id,owner_id,message_id,blob,size,media_type,width,height,created) VALUES (?,?,?,?,?,?,?,?,?)',
                  (pid, uid, None, blob, len(plain), kind, width, height, now()))
    return {'id': pid, 'width': width, 'height': height}

@router.post('/photos', status_code=201)
async def upload_photo(request: Request, current=Depends(user)):
    """A photo for the next message, sent as the request body."""
    if int(request.headers.get('content-length') or 0) > PHOTO_MAX: raise HTTPException(413, 'Photos can be up to 10 MB.')
    data = bytearray()
    async for piece in request.stream():
        data += piece
        if len(data) > PHOTO_MAX: raise HTTPException(413, 'Photos can be up to 10 MB.')
    return await run_in_threadpool(keep_photo, current['id'], bytes(data))

@router.get('/photos/{pid}')
def photo(pid: str, current=Depends(user)):
    with db() as c:
        row = c.execute('''SELECT p.* FROM message_photos p LEFT JOIN messages m ON m.id=p.message_id
                           LEFT JOIN conversation_members cm ON cm.conversation_id=m.conversation_id AND cm.user_id=?
                           WHERE p.id=? AND (cm.user_id IS NOT NULL OR (p.message_id IS NULL AND p.owner_id=?))''', (current['id'], pid, current['id'])).fetchone()
    if not row: raise HTTPException(404, 'Photo not found.')
    return FileResponse(files.blob_path(row['blob']), media_type=row['media_type'],
                        headers={'Content-Security-Policy': 'sandbox', 'Content-Disposition': f'inline; filename="photo-{pid[:8]}.{row["media_type"].split("/")[1]}"'})

@router.get('/unread')
def unread(current=Depends(user)):
    with db() as c:
        return {'unread': c.execute('''SELECT COUNT(*) FROM messages m JOIN conversation_members cm ON cm.conversation_id=m.conversation_id AND cm.user_id=?
                                       WHERE m.deleted IS NULL AND m.sender_id<>? AND m.created>cm.read_at''', (current['id'], current['id'])).fetchone()[0]}

def signed_in(token, uid):
    with db() as c: return c.execute('SELECT 1 FROM sessions WHERE token=? AND expires>? AND user_id=?', (token, time.time(), uid)).fetchone() is not None

@router.get('/events')
async def events(request: Request, current=Depends(user)):
    """Tells this person's open pages when a conversation of theirs changes."""
    token = digest(session_token(request))
    if live.streams_for(current['id']) >= live.MAX_STREAMS_PER_USER: raise HTTPException(429, 'Too many open pages. Close some and reload.')
    return StreamingResponse(live.stream(inbox(current['id']), current['id'], request.headers.get('last-event-id'), lambda: signed_in(token, current['id'])),
                             media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})
