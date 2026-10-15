"""Small text edits with versions, and short-lived, cookie-free website previews."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import tempfile
import time
from pathlib import PurePosixPath
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from . import files, live
from .auth import user, now
from .store import db
from .routes import membership
from .activity import record

router = APIRouter()
TEXT_MAX = 2 * files.MB
SECRET = secrets.token_bytes(32)
PREVIEW_SECONDS = 15 * 60
PREVIEW_CSP = "sandbox; default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; media-src 'self'; frame-ancestors 'self'"
STALE = 'Someone saved a newer version. Copy your changes, reload, and try again.'

class TextBody(BaseModel):
    text: str = Field(max_length=TEXT_MAX)
    version: int = Field(ge=1, strict=True)

@router.put('/spaces/{sid}/files/{fid}/text')
def save_text(sid: str, fid: str, body: TextBody, current=Depends(user)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c, sid, current['id'])
        f = files.live_item(c, sid, fid, 'file')
        if not files.is_text(f['name']): raise HTTPException(415, 'Only text files can be edited.')
        if f['size'] > TEXT_MAX: raise HTTPException(413, 'The editor opens files up to 2 MB.')
        if f['version'] != body.version: raise HTTPException(409, STALE)
        try:
            previous = files.blob_path(f['blob']).read_bytes().decode('utf-8')
            data = body.text.encode('utf-8')
        except UnicodeError:
            raise HTTPException(415, 'The editor needs UTF-8 text.')
        if '\x00' in previous or '\x00' in body.text: raise HTTPException(415, 'Only text files can be edited.')
        if len(data) > min(TEXT_MAX, files.file_limit()): raise HTTPException(413, 'The editor saves files up to 2 MB.')
        if len(data) + files.used(c, sid) > files.space_limit(): raise HTTPException(413, 'This space is full. Delete something, or ask the host for more room.')
        if shutil.disk_usage(files.storage()).free - len(data) < files.MIN_FREE: raise HTTPException(507, 'The server is nearly out of space. Tell the host.')
        blob = hashlib.sha256(data).hexdigest()
        target = files.blob_path(blob)
        if not target.exists():
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as part:
                staging = part.name
                try:
                    part.write(data); part.flush()
                    os.replace(staging, target)
                finally:
                    if os.path.exists(staging): os.unlink(staging)
        stamp = now()
        c.execute('DELETE FROM orphan_blobs WHERE blob=?', (blob,))
        c.execute('INSERT INTO file_versions VALUES (?,?,?,?,?,?)', (fid, f['version'], f['blob'], f['size'], f['updated_by'], f['updated']))
        c.execute('UPDATE files SET blob=?,size=?,version=version+1,updated_by=?,updated=? WHERE id=?', (blob, len(data), current['id'], stamp, fid))
        record(c, 'file_edited', actor=current['id'], space=sid, target=fid, target_name=files.joined(f['folder'], f['name']), version=f['version'] + 1)
        saved = files.item(c, fid)
    live.publish(sid)
    return saved

class PreviewBody(BaseModel):
    folder: str = Field(default='', max_length=4200)

def sign(payload): return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()

@router.post('/spaces/{sid}/previews')
def preview_token(sid: str, body: PreviewBody, current=Depends(user)):
    with db() as c:
        membership(c, sid, current['id'])
        folder = files.clean_folder(body.folder)
        if not files.folder_exists(c, sid, folder): raise HTTPException(404, 'Folder not found.')
    payload = base64.urlsafe_b64encode(json.dumps([sid, folder, int(time.time()) + PREVIEW_SECONDS], separators=(',', ':')).encode()).decode().rstrip('=')
    return {'url': f'/api/community/preview/{payload}.{sign(payload)}/'}

def unpack(token):
    try:
        if len(token) > 12000: raise ValueError()
        payload, signature = token.split('.')
        if not hmac.compare_digest(signature, sign(payload)): raise ValueError()
        sid, folder, expires = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        if expires <= time.time(): raise ValueError()
        return sid, folder
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(404, 'Preview expired or unavailable. Open it again.')

@router.get('/preview/{token}/{path:path}')
def preview_file(token: str, path: str):
    sid, folder = unpack(token)
    parts = path.rstrip('/').split('/') if path else []
    if len(path) > 4200 or any(not part or part in ('.', '..') or files.BAD.search(part) for part in parts):
        raise HTTPException(404, 'File not found.')
    relative = '/'.join(parts)
    full = files.joined(folder, relative) if relative else folder
    with db() as c:
        if files.folder_exists(c, sid, full): full = files.joined(full, 'index.html')
        elif path.endswith('/'): raise HTTPException(404, 'File not found.')
        elif not PurePosixPath(full).suffix: full += '.html'
        parent, _, name = full.rpartition('/')
        f = c.execute("SELECT name,blob FROM files WHERE space_id=? AND folder=? AND name=? AND kind='file' AND deleted IS NULL", (sid, parent, name)).fetchone()
        if not f: raise HTTPException(404, 'File not found.')
    return FileResponse(files.blob_path(f['blob']), media_type=files.media_type(f['name']),
                        headers={'Content-Security-Policy': PREVIEW_CSP, 'X-Frame-Options': 'SAMEORIGIN', 'Access-Control-Allow-Origin': '*'})
