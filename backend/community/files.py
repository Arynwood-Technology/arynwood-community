"""The file bank: each space's shared files and folders, kept on this server.

Contents live in the data folder as blobs named by their SHA-256, so a file uploaded twice is
stored once and a version never changes after it is written; the database keeps names, folders,
versions and who did what. Uploads arrive in pieces small enough for any proxy in front of the
Grove, and pick up where they stopped. Deleted files wait in their space's trash for 30 days.
Nothing is served as a page of the Grove: downloads are attachments under a sandbox policy, and
only images, PDFs and text open in the browser, text always as text/plain."""
import hashlib
import mimetypes
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .auth import user, identifier, now
from .store import db, database_path, setting
from .activity import record
from .routes import membership
from . import live

router = APIRouter()
MB = 1024 * 1024
CHUNK = 4 * MB          # what pages send; they fall back to smaller pieces if a proxy refuses these
CHUNK_MAX = 8 * MB      # the most one piece may carry
TRASH_DAYS = 30
BLOB_GRACE = 15 * 86400  # longer than the 14 daily backups keep a database that may name a blob
UPLOAD_SECONDS = 24 * 3600
MIN_FREE = 2 * 1024 * MB
BAD = re.compile(r'[/\\\x00-\x1f\x7f]')
# Opened in the browser rather than downloaded; text is always sent as text/plain.
SHOWN = {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'application/pdf'}
TEXT = {'.txt', '.md', '.csv', '.tsv', '.json', '.html', '.htm', '.css', '.js', '.mjs', '.ts', '.tsx', '.jsx',
        '.svg', '.xml', '.yml', '.yaml', '.toml', '.ini', '.srt', '.vtt'}

def megabytes(name, default):
    try: return max(1, int(setting(name, str(default)))) * MB
    except ValueError: return default * MB

def file_limit(): return megabytes('FILE_MAX_MB', 2048)
def space_limit(): return megabytes('SPACE_STORAGE_MB', 10240)

def storage(): return database_path().parent / 'files'
def blob_path(blob): return storage() / 'blobs' / blob[:2] / blob
def part_path(uid): return storage() / 'uploads' / uid

def clean_name(value):
    name = value.strip()
    if not name or name in ('.', '..') or len(name) > 200 or BAD.search(name):
        raise HTTPException(422, 'Use a name of up to 200 characters, without slashes.')
    return name

def clean_folder(value):
    parts = [clean_name(p) for p in value.split('/') if p.strip()]
    if len(parts) > 20: raise HTTPException(422, 'Folders go 20 deep at most.')
    return '/'.join(parts)

def joined(folder, name): return f'{folder}/{name}' if folder else name

def inside(path):
    """SQL (and its arguments) matching rows in folder `path` or anywhere below it."""
    return '(folder=? OR substr(folder,1,?)=?)', (path, len(path) + 1, path + '/')

def folder_exists(c, sid, folder):
    if not folder: return True
    parent, _, name = folder.rpartition('/')
    return c.execute("SELECT 1 FROM files WHERE space_id=? AND folder=? AND name=? AND kind='folder' AND deleted IS NULL", (sid, parent, name)).fetchone() is not None

def taken(c, sid, folder, name):
    if c.execute('SELECT 1 FROM files WHERE space_id=? AND folder=? AND name=? AND deleted IS NULL', (sid, folder, name)).fetchone():
        raise HTTPException(409, f'Something named {name} is already here.')

def live_item(c, sid, fid, kind=None):
    row = c.execute('SELECT * FROM files WHERE id=? AND space_id=? AND deleted IS NULL', (fid, sid)).fetchone()
    if not row or (kind and row['kind'] != kind): raise HTTPException(404, 'File not found.')
    return row

def may_change(c, role, uid, item):
    """Its author or a space owner; a folder's author only if everything in it is theirs too."""
    if role == 'owner': return
    if item['author_id'] != uid: raise HTTPException(403, 'Only whoever added this, or a space owner, can change it.')
    if item['kind'] == 'folder':
        where, args = inside(joined(item['folder'], item['name']))
        if c.execute(f'SELECT 1 FROM files WHERE space_id=? AND deleted IS NULL AND {where} AND author_id IS NOT ?', (item['space_id'], *args, uid)).fetchone():
            raise HTTPException(403, 'Others added things to this folder, so only a space owner can change it.')

def used(c, sid):
    """Bytes a space holds: files and their earlier versions, in the trash too, and uploads under way."""
    return c.execute('''SELECT (SELECT COALESCE(SUM(size),0) FROM files WHERE space_id=?)
        + (SELECT COALESCE(SUM(v.size),0) FROM file_versions v JOIN files f ON f.id=v.file_id WHERE f.space_id=?)
        + (SELECT COALESCE(SUM(size),0) FROM uploads WHERE space_id=?)''', (sid, sid, sid)).fetchone()[0]

ITEM = '''SELECT f.id,f.folder,f.name,f.kind,f.size,f.version,f.created,f.updated,f.deleted,f.author_id,
          COALESCE(a.name,'') AS author,COALESCE(b.name,'') AS updated_by FROM files f
          LEFT JOIN users a ON a.id=f.author_id LEFT JOIN users b ON b.id=f.updated_by'''

def item(c, fid): return dict(c.execute(ITEM + ' WHERE f.id=?', (fid,)).fetchone())

@router.get('/spaces/{sid}/files')
def files(sid: str, folder: str = '', trash: bool = False, current=Depends(user)):
    with db() as c:
        membership(c, sid, current['id'])
        if trash:
            rows = c.execute(ITEM + ' WHERE f.space_id=? AND f.trash_root=f.id ORDER BY f.deleted DESC', (sid,))
        else:
            folder = clean_folder(folder)
            if not folder_exists(c, sid, folder): raise HTTPException(404, 'Folder not found.')
            # Folders first ('folder' sorts after 'file').
            rows = c.execute(ITEM + ' WHERE f.space_id=? AND f.folder=? AND f.deleted IS NULL ORDER BY f.kind DESC, f.name COLLATE NOCASE', (sid, folder))
        return {'folder': '' if trash else folder, 'items': [dict(r) for r in rows], 'used': used(c, sid), 'limit': space_limit(), 'file_limit': file_limit()}

class FolderBody(BaseModel):
    folder: str = Field(default='', max_length=4200)
    name: str = Field(min_length=1, max_length=200)

@router.post('/spaces/{sid}/folders', status_code=201)
def new_folder(sid: str, body: FolderBody, current=Depends(user)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c, sid, current['id'])
        folder, name = clean_folder(body.folder), clean_name(body.name)
        clean_folder(joined(folder, name))
        if not folder_exists(c, sid, folder): raise HTTPException(404, 'Folder not found.')
        taken(c, sid, folder, name)
        fid, stamp = identifier(), now()
        c.execute('INSERT INTO files (id,space_id,folder,name,kind,author_id,updated_by,created,updated) VALUES (?,?,?,?,?,?,?,?,?)',
                  (fid, sid, folder, name, 'folder', current['id'], current['id'], stamp, stamp))
        record(c, 'folder_created', actor=current['id'], space=sid, target=fid, target_name=joined(folder, name))
        saved = item(c, fid)
    live.publish(sid)
    return saved

class UploadBody(BaseModel):
    folder: str = Field(default='', max_length=4200)
    name: str = Field(min_length=1, max_length=200)
    size: int = Field(ge=0)
    replaces: str | None = Field(default=None, max_length=64)  # a file in this space to give a new version

@router.post('/spaces/{sid}/uploads', status_code=201)
def start_upload(sid: str, body: UploadBody, current=Depends(user)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c, sid, current['id'])
        stalled = [r['id'] for r in c.execute('SELECT id FROM uploads WHERE started<?', (time.time() - UPLOAD_SECONDS,))]
        c.execute('DELETE FROM uploads WHERE started<?', (time.time() - UPLOAD_SECONDS,))
        if body.replaces:
            target = live_item(c, sid, body.replaces, 'file')
            folder, name = target['folder'], target['name']
        else:
            folder, name = clean_folder(body.folder), clean_name(body.name)
            if not folder_exists(c, sid, folder): raise HTTPException(404, 'Folder not found.')
            taken(c, sid, folder, name)
        if body.size > file_limit(): raise HTTPException(413, f'Files can be up to {file_limit() // MB:,} MB here.')
        room = space_limit() - used(c, sid)
        if body.size > room: raise HTTPException(413, f'This space has room for {max(room, 0) / MB:,.1f} MB more. Delete something, or ask the host for more room.')
        storage().mkdir(mode=0o700, parents=True, exist_ok=True)
        if shutil.disk_usage(storage()).free - body.size < MIN_FREE: raise HTTPException(507, 'The server is nearly out of space. Tell the host.')
        uid = identifier()
        c.execute('INSERT INTO uploads VALUES (?,?,?,?,?,?,?,?,?)', (uid, sid, current['id'], folder, name, body.size, 0, body.replaces, time.time()))
    for old in stalled: part_path(old).unlink(missing_ok=True)
    part_path(uid).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    part_path(uid).touch(mode=0o600)
    return {'id': uid, 'chunk': CHUNK, 'received': 0}

def upload_row(c, sid, uid, user_id):
    membership(c, sid, user_id)
    row = c.execute('SELECT * FROM uploads WHERE id=? AND space_id=? AND user_id=?', (uid, sid, user_id)).fetchone()
    if not row: raise HTTPException(404, 'This upload has stopped. Start it again.')
    return row

@router.get('/spaces/{sid}/uploads/{uid}')
def upload_status(sid: str, uid: str, current=Depends(user)):
    with db() as c: row = upload_row(c, sid, uid, current['id'])
    return {'received': row['received'], 'size': row['size']}

def write_piece(sid, uid, user_id, offset, data):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = upload_row(c, sid, uid, user_id)
        if offset != row['received']: raise HTTPException(409, f"Expected the piece at {row['received']}.")
        if offset + len(data) > row['size']: raise HTTPException(422, 'This is more than the file’s size.')
        with open(part_path(uid), 'r+b') as part:
            part.seek(offset); part.write(data)
        c.execute('UPDATE uploads SET received=? WHERE id=?', (offset + len(data), uid))
    return {'received': offset + len(data)}

@router.put('/spaces/{sid}/uploads/{uid}')
async def upload_piece(sid: str, uid: str, offset: int, request: Request, current=Depends(user)):
    if int(request.headers.get('content-length') or 0) > CHUNK_MAX: raise HTTPException(413, 'Send at most 8 MB at a time.')
    data = bytearray()
    async for piece in request.stream():
        data += piece
        if len(data) > CHUNK_MAX: raise HTTPException(413, 'Send at most 8 MB at a time.')
    return await run_in_threadpool(write_piece, sid, uid, current['id'], offset, bytes(data))

def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(MB), b''): digest.update(block)
    return digest.hexdigest()

@router.post('/spaces/{sid}/uploads/{uid}/finish', status_code=201)
def finish_upload(sid: str, uid: str, current=Depends(user)):
    with db() as c: row = upload_row(c, sid, uid, current['id'])
    if row['received'] != row['size']: raise HTTPException(409, 'The upload is not complete yet.')
    # Hashing a large file takes a while, so it happens outside any transaction.
    blob = sha256(part_path(uid))
    target = blob_path(blob)
    if target.exists(): part_path(uid).unlink()
    else:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.replace(part_path(uid), target)
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = upload_row(c, sid, uid, current['id'])
            c.execute('DELETE FROM uploads WHERE id=?', (uid,))
            c.execute('DELETE FROM orphan_blobs WHERE blob=?', (blob,))
            stamp = now()
            if row['replaces']:
                f = live_item(c, sid, row['replaces'], 'file')
                c.execute('INSERT INTO file_versions VALUES (?,?,?,?,?,?)', (f['id'], f['version'], f['blob'], f['size'], f['updated_by'], f['updated']))
                c.execute('UPDATE files SET blob=?,size=?,version=version+1,updated_by=?,updated=? WHERE id=?', (blob, row['size'], current['id'], stamp, f['id']))
                fid = f['id']
                record(c, 'file_version_added', actor=current['id'], space=sid, target=fid, target_name=joined(f['folder'], f['name']), version=f['version'] + 1, size=row['size'])
            else:
                if not folder_exists(c, sid, row['folder']): raise HTTPException(404, 'Its folder was deleted while it uploaded.')
                taken(c, sid, row['folder'], row['name'])
                fid = identifier()
                c.execute('INSERT INTO files (id,space_id,folder,name,kind,blob,size,author_id,updated_by,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                          (fid, sid, row['folder'], row['name'], 'file', blob, row['size'], current['id'], current['id'], stamp, stamp))
                record(c, 'file_uploaded', actor=current['id'], space=sid, target=fid, target_name=joined(row['folder'], row['name']), size=row['size'])
            saved = item(c, fid)
    except HTTPException:
        # Its pieces are already filed away, so this upload cannot be finished another time.
        with db() as c: c.execute('DELETE FROM uploads WHERE id=?', (uid,))
        raise
    live.publish(sid)
    return saved

def media_type(name): return mimetypes.guess_type(name)[0] or 'application/octet-stream'
def is_text(name): return PurePosixPath(name.lower()).suffix in TEXT

@router.get('/spaces/{sid}/files/{fid}/content')
def content(sid: str, fid: str, version: int | None = None, inline: bool = False, current=Depends(user)):
    with db() as c:
        membership(c, sid, current['id'])
        f = c.execute("SELECT * FROM files WHERE id=? AND space_id=? AND kind='file'", (fid, sid)).fetchone()
        if not f: raise HTTPException(404, 'File not found.')
        blob = f['blob']
        if version and version != f['version']:
            old = c.execute('SELECT blob FROM file_versions WHERE file_id=? AND version=?', (fid, version)).fetchone()
            if not old: raise HTTPException(404, 'Version not found.')
            blob = old['blob']
        if not inline: record(c, 'file_downloaded', actor=current['id'], space=sid, target=fid, target_name=joined(f['folder'], f['name']), **({'version': version} if version else {}))
    text, kind = is_text(f['name']), media_type(f['name'])
    shown = inline and (text or kind in SHOWN)
    # A PDF opens in the browser's own viewer; anything else is sandboxed even if a browser renders it.
    headers = {} if shown and kind == 'application/pdf' else {'Content-Security-Policy': 'sandbox'}
    return FileResponse(blob_path(blob), media_type='text/plain; charset=utf-8' if shown and text else kind, headers=headers,
                        filename=f['name'], content_disposition_type='inline' if shown else 'attachment')

@router.get('/spaces/{sid}/files/{fid}/versions')
def versions(sid: str, fid: str, current=Depends(user)):
    with db() as c:
        membership(c, sid, current['id'])
        f = live_item(c, sid, fid, 'file')
        older = c.execute('''SELECT v.version,v.size,v.created,COALESCE(u.name,'') AS author FROM file_versions v
                             LEFT JOIN users u ON u.id=v.author_id WHERE v.file_id=? ORDER BY v.version DESC''', (fid,))
        return [{'version': f['version'], 'size': f['size'], 'created': f['updated'], 'author': item(c, fid)['updated_by']}, *[dict(r) for r in older]]

class MoveBody(BaseModel):
    folder: str = Field(default='', max_length=4200)
    name: str = Field(min_length=1, max_length=200)

@router.put('/spaces/{sid}/files/{fid}')
def move(sid: str, fid: str, body: MoveBody, current=Depends(user)):
    """Renames, or moves to another folder; a folder takes everything in it along."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        role = membership(c, sid, current['id'])
        f = live_item(c, sid, fid)
        may_change(c, role, current['id'], f)
        folder, name = clean_folder(body.folder), clean_name(body.name)
        old, new = joined(f['folder'], f['name']), clean_folder(joined(folder, name))
        if new != old:
            if not folder_exists(c, sid, folder): raise HTTPException(404, 'Folder not found.')
            if f['kind'] == 'folder' and (folder == old or folder.startswith(old + '/')): raise HTTPException(422, 'A folder cannot go inside itself.')
            taken(c, sid, folder, name)
            c.execute('UPDATE files SET folder=?,name=? WHERE id=?', (folder, name, fid))
            if f['kind'] == 'folder':
                # Things binned on their own move too, so they come back to the right place; what
                # went to the trash with another folder of this name stays with that folder.
                where, args = inside(old)
                c.execute(f'UPDATE files SET folder=?||substr(folder,?) WHERE space_id=? AND (deleted IS NULL OR trash_root=id) AND {where}', (new, len(old) + 1, sid, *args))
            record(c, 'file_moved' if folder != f['folder'] else 'file_renamed', actor=current['id'], space=sid, target=fid, target_name=new, kind=f['kind'], **{'from': old})
        saved = item(c, fid)
    live.publish(sid)
    return saved

@router.delete('/spaces/{sid}/files/{fid}')
def trash(sid: str, fid: str, current=Depends(user)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        role = membership(c, sid, current['id'])
        f = live_item(c, sid, fid)
        may_change(c, role, current['id'], f)
        stamp = now()
        c.execute('UPDATE files SET deleted=?,trash_root=? WHERE id=?', (stamp, fid, fid))
        if f['kind'] == 'folder':
            where, args = inside(joined(f['folder'], f['name']))
            c.execute(f'UPDATE files SET deleted=?,trash_root=? WHERE space_id=? AND deleted IS NULL AND {where}', (stamp, fid, sid, *args))
        record(c, 'file_deleted', actor=current['id'], space=sid, target=fid, target_name=joined(f['folder'], f['name']), kind=f['kind'])
    live.publish(sid)
    return {'ok': True}

def trashed(c, sid, fid):
    row = c.execute('SELECT * FROM files WHERE id=? AND space_id=? AND trash_root=id', (fid, sid)).fetchone()
    if not row: raise HTTPException(404, 'Not in the trash.')
    return row

@router.post('/spaces/{sid}/files/{fid}/restore')
def restore(sid: str, fid: str, current=Depends(user)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        role = membership(c, sid, current['id'])
        f = trashed(c, sid, fid)
        if role != 'owner' and f['author_id'] != current['id']: raise HTTPException(403, 'Only whoever added this, or a space owner, can restore it.')
        if not folder_exists(c, sid, f['folder']): raise HTTPException(409, 'Its folder is gone. Restore that folder first.')
        if c.execute('SELECT 1 FROM files WHERE space_id=? AND folder=? AND name=? AND deleted IS NULL', (sid, f['folder'], f['name'])).fetchone():
            raise HTTPException(409, f"Something named {f['name']} is there now. Rename it, then restore this.")
        c.execute('UPDATE files SET deleted=NULL,trash_root=NULL WHERE space_id=? AND trash_root=?', (sid, fid))
        record(c, 'file_restored', actor=current['id'], space=sid, target=fid, target_name=joined(f['folder'], f['name']), kind=f['kind'])
        saved = item(c, fid)
    live.publish(sid)
    return saved

@router.delete('/spaces/{sid}/trash/{fid}')
def purge(sid: str, fid: str, current=Depends(user)):
    """Deletes something in the trash for good. Space owners only."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c, sid, current['id'], owner=True)
        f = trashed(c, sid, fid)
        c.execute('DELETE FROM files WHERE space_id=? AND trash_root=?', (sid, fid))
        record(c, 'file_purged', actor=current['id'], space=sid, target=fid, target_name=joined(f['folder'], f['name']), kind=f['kind'])
    live.publish(sid)
    return {'ok': True}

def sweep(clock=time.time):
    """Run daily with the backup: empties trash older than 30 days, drops stalled uploads, and
    removes blobs no file names once no kept backup can name them either."""
    moment = clock()
    cutoff = (datetime.fromtimestamp(moment, timezone.utc) - timedelta(days=TRASH_DAYS)).isoformat()
    with db() as c:
        c.execute('DELETE FROM files WHERE deleted IS NOT NULL AND deleted<?', (cutoff,))
        c.execute('DELETE FROM uploads WHERE started<?', (moment - UPLOAD_SECONDS,))
        uploading = {r['id'] for r in c.execute('SELECT id FROM uploads')}
        named = {r[0] for r in c.execute('SELECT blob FROM files WHERE blob IS NOT NULL UNION SELECT blob FROM file_versions')}
        orphans = {r['blob']: r['since'] for r in c.execute('SELECT * FROM orphan_blobs')}
        c.execute('DELETE FROM orphan_blobs WHERE blob IN (SELECT blob FROM files WHERE blob IS NOT NULL UNION SELECT blob FROM file_versions)')
        for path in sorted((storage() / 'blobs').glob('*/*')):
            if path.name in named: continue
            if path.name not in orphans: c.execute('INSERT INTO orphan_blobs VALUES (?,?)', (path.name, moment))
            elif orphans[path.name] < moment - BLOB_GRACE:
                path.unlink(missing_ok=True)
                c.execute('DELETE FROM orphan_blobs WHERE blob=?', (path.name,))
    for part in (storage() / 'uploads').glob('*'):
        if part.name not in uploading: part.unlink(missing_ok=True)
