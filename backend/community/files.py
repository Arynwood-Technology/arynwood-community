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
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from .auth import user, identifier, now, looks_after_website
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
ZIP_MAX = 4 * 1024 * MB
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

WEBSITE = 'Website'
def website(*paths): return any(p == WEBSITE or p.startswith(WEBSITE + '/') for p in paths)

def announce(sid, *paths):
    """Tells the space's open pages it changed, and every open website preview when a website file did."""
    live.publish(sid)
    if website(*paths): live.publish(live.WEBSITE)

def may_change_website(current, *paths):
    """A space's Website folder holds the Grove's website: everyone in the space sees it, and only the
    Grove's owners and webmasters change it. True when the paths are in it and this person may."""
    if not website(*paths): return False
    if not looks_after_website(current): raise HTTPException(403, 'Only this Grove’s owners and webmasters change website files.')
    return True

def may_change(c, role, uid, item):
    """Its author or a space owner; a folder's author only if everything in it is theirs too."""
    if role == 'owner': return
    if item['author_id'] != uid: raise HTTPException(403, 'Only whoever added this, or a space owner, can change it.')
    if item['kind'] == 'folder':
        where, args = inside(joined(item['folder'], item['name']))
        if c.execute(f'SELECT 1 FROM files WHERE space_id=? AND deleted IS NULL AND {where} AND author_id IS NOT ?', (item['space_id'], *args, uid)).fetchone():
            raise HTTPException(403, 'Others added things to this folder, so only a space owner can change it.')

def used(c, sid):
    """Bytes a space holds: files and their earlier versions, in the trash too, uploads under way, and
    the editor's unsaved drafts (kept in the database, but room all the same)."""
    return c.execute('''SELECT (SELECT COALESCE(SUM(size),0) FROM files WHERE space_id=?)
        + (SELECT COALESCE(SUM(v.size),0) FROM file_versions v JOIN files f ON f.id=v.file_id WHERE f.space_id=?)
        + (SELECT COALESCE(SUM(size),0) FROM uploads WHERE space_id=?)
        + (SELECT COALESCE(SUM(LENGTH(CAST(d.text AS BLOB))),0) FROM file_drafts d JOIN files f ON f.id=d.file_id WHERE f.space_id=?)''',
        (sid, sid, sid, sid)).fetchone()[0]

ITEM = '''SELECT f.id,f.folder,f.name,f.kind,f.size,f.version,f.created,f.updated,f.deleted,f.author_id,
          COALESCE(a.name,'') AS author,COALESCE(b.name,'') AS updated_by FROM files f
          LEFT JOIN users a ON a.id=f.author_id LEFT JOIN users b ON b.id=f.updated_by'''

def item(c, fid): return dict(c.execute(ITEM + ' WHERE f.id=?', (fid,)).fetchone())

@router.get('/spaces/{sid}/files')
def files(sid: str, folder: str = '', trash: bool = False, current=Depends(user)):
    """A folder of the space's files (or its trash), with the room used and the size limits."""
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
    """Creates a folder."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c, sid, current['id'])
        folder, name = clean_folder(body.folder), clean_name(body.name)
        clean_folder(joined(folder, name))
        may_change_website(current, joined(folder, name))
        if not folder_exists(c, sid, folder): raise HTTPException(404, 'Folder not found.')
        taken(c, sid, folder, name)
        fid, stamp = identifier(), now()
        c.execute('INSERT INTO files (id,space_id,folder,name,kind,author_id,updated_by,created,updated) VALUES (?,?,?,?,?,?,?,?,?)',
                  (fid, sid, folder, name, 'folder', current['id'], current['id'], stamp, stamp))
        record(c, 'folder_created', actor=current['id'], space=sid, target=fid, target_name=joined(folder, name))
        saved = item(c, fid)
    announce(sid, joined(folder, name))
    return saved

class UploadBody(BaseModel):
    folder: str = Field(default='', max_length=4200)
    name: str = Field(min_length=1, max_length=200)
    size: int = Field(ge=0)
    replaces: str | None = Field(default=None, max_length=64)  # a file in this space to give a new version

@router.post('/spaces/{sid}/uploads', status_code=201)
def start_upload(sid: str, body: UploadBody, current=Depends(user)):
    """Starts uploading a file, or a new version of one, after checking its size against the space's room and the
    server's free space. The file then goes up in pieces."""
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
        may_change_website(current, joined(folder, name))
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
    """How much of an upload has arrived, to resume it."""
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
    """One piece of an upload, at most 8 MB, at the given offset; the request body is the bytes."""
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
    """Completes an upload once every byte has arrived, adding the file or its new version."""
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
            may_change_website(current, joined(row['folder'], row['name']))
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
    announce(sid, joined(row['folder'], row['name']))
    return saved

# Website files Python may not know without the system's mime.types.
TYPES = {'.webp': 'image/webp', '.avif': 'image/avif', '.woff': 'font/woff', '.woff2': 'font/woff2', '.webmanifest': 'application/manifest+json', '.mjs': 'text/javascript'}
def media_type(name): return TYPES.get(PurePosixPath(name.lower()).suffix) or mimetypes.guess_type(name)[0] or 'application/octet-stream'
def is_text(name): return PurePosixPath(name.lower()).suffix in TEXT

@router.get('/spaces/{sid}/files/{fid}/content')
def content(sid: str, fid: str, version: int | None = None, inline: bool = False, current=Depends(user)):
    """A file's content, or an older version's, to download or (inline) to view. Anything not shown inline is
    sandboxed."""
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

@router.get('/spaces/{sid}/files/{fid}/zip')
def folder_zip(sid: str, fid: str, current=Depends(user)):
    """A folder and everything in it, as one .zip: how a website leaves the Grove for its host."""
    with db() as c:
        membership(c, sid, current['id'])
        f = live_item(c, sid, fid, 'folder')
        path = joined(f['folder'], f['name'])
        where, args = inside(path)
        rows = [dict(r) for r in c.execute(f"SELECT folder,name,blob,size FROM files WHERE space_id=? AND kind='file' AND deleted IS NULL AND {where}", (sid, *args))]
        if sum(r['size'] for r in rows) > ZIP_MAX: raise HTTPException(413, 'This folder is too large for one download. Download its folders one at a time.')
        record(c, 'folder_downloaded', actor=current['id'], space=sid, target=fid, target_name=path, files=len(rows))
    (storage() / 'tmp').mkdir(mode=0o700, parents=True, exist_ok=True)
    out = storage() / 'tmp' / f'{identifier()}.zip'
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for r in rows: archive.write(blob_path(r['blob']), joined(f['name'], joined(r['folder'][len(path):].lstrip('/'), r['name'])))
    return FileResponse(out, media_type='application/zip', filename=f"{f['name']}.zip", headers={'Content-Security-Policy': 'sandbox'},
                        background=BackgroundTask(out.unlink, missing_ok=True))

@router.get('/spaces/{sid}/files/{fid}/versions')
def versions(sid: str, fid: str, current=Depends(user)):
    """A file's versions, newest first."""
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
        folder, name = clean_folder(body.folder), clean_name(body.name)
        old, new = joined(f['folder'], f['name']), clean_folder(joined(folder, name))
        # Webmasters look after everything already in Website; bringing something in is still its author's call.
        may_change_website(current, old, new)
        if not website(old): may_change(c, role, current['id'], f)
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
    announce(sid, old, new)
    return saved

@router.delete('/spaces/{sid}/files/{fid}')
def trash(sid: str, fid: str, current=Depends(user)):
    """Moves a file, or a folder with everything in it, to the trash."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        role = membership(c, sid, current['id'])
        f = live_item(c, sid, fid)
        if not may_change_website(current, joined(f['folder'], f['name'])): may_change(c, role, current['id'], f)
        stamp = now()
        c.execute('UPDATE files SET deleted=?,trash_root=? WHERE id=?', (stamp, fid, fid))
        if f['kind'] == 'folder':
            where, args = inside(joined(f['folder'], f['name']))
            c.execute(f'UPDATE files SET deleted=?,trash_root=? WHERE space_id=? AND deleted IS NULL AND {where}', (stamp, fid, sid, *args))
        record(c, 'file_deleted', actor=current['id'], space=sid, target=fid, target_name=joined(f['folder'], f['name']), kind=f['kind'])
    announce(sid, joined(f['folder'], f['name']))
    return {'ok': True}

def trashed(c, sid, fid):
    row = c.execute('SELECT * FROM files WHERE id=? AND space_id=? AND trash_root=id', (fid, sid)).fetchone()
    if not row: raise HTTPException(404, 'Not in the trash.')
    return row

@router.post('/spaces/{sid}/files/{fid}/restore')
def restore(sid: str, fid: str, current=Depends(user)):
    """Restores something from the trash: whoever added it, or a space owner."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        role = membership(c, sid, current['id'])
        f = trashed(c, sid, fid)
        if not may_change_website(current, joined(f['folder'], f['name'])) and role != 'owner' and f['author_id'] != current['id']:
            raise HTTPException(403, 'Only whoever added this, or a space owner, can restore it.')
        if not folder_exists(c, sid, f['folder']): raise HTTPException(409, 'Its folder is gone. Restore that folder first.')
        if c.execute('SELECT 1 FROM files WHERE space_id=? AND folder=? AND name=? AND deleted IS NULL', (sid, f['folder'], f['name'])).fetchone():
            raise HTTPException(409, f"Something named {f['name']} is there now. Rename it, then restore this.")
        c.execute('UPDATE files SET deleted=NULL,trash_root=NULL WHERE space_id=? AND trash_root=?', (sid, fid))
        record(c, 'file_restored', actor=current['id'], space=sid, target=fid, target_name=joined(f['folder'], f['name']), kind=f['kind'])
        saved = item(c, fid)
    announce(sid, joined(f['folder'], f['name']))
    return saved

@router.delete('/spaces/{sid}/trash/{fid}')
def purge(sid: str, fid: str, current=Depends(user)):
    """Deletes something in the trash for good. Space owners only."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c, sid, current['id'], owner=True)
        f = trashed(c, sid, fid)
        may_change_website(current, joined(f['folder'], f['name']))
        c.execute('DELETE FROM files WHERE space_id=? AND trash_root=?', (sid, fid))
        record(c, 'file_purged', actor=current['id'], space=sid, target=fid, target_name=joined(f['folder'], f['name']), kind=f['kind'])
    announce(sid, joined(f['folder'], f['name']))
    return {'ok': True}

def sweep(clock=time.time):
    """Run daily with the backup: empties trash older than 30 days, drops stalled uploads, and
    removes blobs no file names once no kept backup can name them either."""
    moment = clock()
    cutoff = (datetime.fromtimestamp(moment, timezone.utc) - timedelta(days=TRASH_DAYS)).isoformat()
    with db() as c:
        c.execute('DELETE FROM files WHERE deleted IS NOT NULL AND deleted<?', (cutoff,))
        c.execute('DELETE FROM uploads WHERE started<?', (moment - UPLOAD_SECONDS,))
        # Photos sent for a message (messages.py) that never followed.
        day_ago = (datetime.fromtimestamp(moment, timezone.utc) - timedelta(days=1)).isoformat()
        c.execute('DELETE FROM message_photos WHERE message_id IS NULL AND created<?', (day_ago,))
        c.execute('DELETE FROM message_files WHERE message_id IS NULL AND created<?', (day_ago,))
        uploading = {r['id'] for r in c.execute('SELECT id FROM uploads UNION SELECT id FROM message_files WHERE blob IS NULL')}
        # A published website's releases (website.py) keep their pages after the files change, and
        # photos and files in Messages (messages.py) are kept as long as their message is.
        kept = ('SELECT blob FROM files WHERE blob IS NOT NULL UNION SELECT blob FROM file_versions UNION SELECT blob FROM site_release_files'
                ' UNION SELECT blob FROM message_photos UNION SELECT blob FROM message_files WHERE blob IS NOT NULL')
        named = {r[0] for r in c.execute(kept)}
        orphans = {r['blob']: r['since'] for r in c.execute('SELECT * FROM orphan_blobs')}
        c.execute(f'DELETE FROM orphan_blobs WHERE blob IN ({kept})')
        for path in sorted((storage() / 'blobs').glob('*/*')):
            if path.name in named: continue
            if path.name not in orphans: c.execute('INSERT INTO orphan_blobs VALUES (?,?)', (path.name, moment))
            elif orphans[path.name] < moment - BLOB_GRACE:
                path.unlink(missing_ok=True)
                c.execute('DELETE FROM orphan_blobs WHERE blob=?', (path.name,))
    for part in (storage() / 'uploads').glob('*'):
        if part.name not in uploading: part.unlink(missing_ok=True)
    # Zips whose download was cut off.
    for leftover in (storage() / 'tmp').glob('*'):
        if leftover.stat().st_mtime < moment - 86400: leftover.unlink(missing_ok=True)
