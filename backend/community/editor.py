"""Small text edits with versions, and short-lived, cookie-free website previews."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from pathlib import PurePosixPath
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from . import files, live
from .auth import user, now
from .store import db
from .routes import membership
from .activity import record

router = APIRouter()
TEXT_MAX = 2 * files.MB
SECRET = secrets.token_bytes(32)
PREVIEW_SECONDS = 60 * 60
# The site's scripts run, as a page from nowhere: no cookies, no Grove APIs, nothing from other sites.
PREVIEW_CSP = ("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; default-src 'none'; script-src 'self' 'unsafe-inline'; "
               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; media-src 'self'; form-action 'none'; frame-ancestors 'self'")
PREVIEW_HEADERS = {'Content-Security-Policy': PREVIEW_CSP, 'X-Frame-Options': 'SAMEORIGIN', 'Access-Control-Allow-Origin': '*'}
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
        files.may_change_website(current, files.joined(f['folder'], f['name']))
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
    return {'url': preview_url(sid, folder)}

def preview_url(sid, folder):
    """An address showing a folder and everything in it, for an hour, to whoever has it."""
    payload = base64.urlsafe_b64encode(json.dumps([sid, folder, int(time.time()) + PREVIEW_SECONDS], separators=(',', ':')).encode()).decode().rstrip('=')
    return f'/api/community/preview/{payload}.{sign(payload)}/'

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

# A site's own addresses, such as /styles.css, start at its top folder: the preview's folder. In a
# preview they point under the preview's address. /community and /api stay the Grove's.
ROOTED = r'''(?=/(?!/|(?:community|api)(?![^/?#"'\s)>])))'''
TAG = re.compile(r'''<[a-zA-Z](?:[^>"']|"[^"]*"|'[^']*')*>''')
STYLE = re.compile(r'(<style\b[^>]*>)(.*?)(</style\s*>)', re.I | re.S)
ATTRIBUTE = re.compile(r'''(\s(?:href|src|poster|action|formaction|data|background)\s*=\s*["']?)''' + ROOTED, re.I)
SRCSET = re.compile(r'''(\s(?:srcset|imagesrcset)\s*=\s*(["']))(.*?)(\2)''', re.I | re.S)
CANDIDATE = re.compile(r'((?:^|,)\s*)' + ROOTED)
CSS = re.compile(r'''((?:url\(\s*|@import\s+)["']?)''' + ROOTED, re.I)

def rebased(text, kind, base):
    """A page or stylesheet with its site-rooted addresses moved under `base`. Scripts are left as they are."""
    css = lambda value: CSS.sub(lambda m: m[1] + base, value)
    if kind == 'css': return css(text)
    def tag(m):
        value = ATTRIBUTE.sub(lambda a: a[1] + base, m[0])
        value = SRCSET.sub(lambda s: s[1] + CANDIDATE.sub(lambda c: c[1] + base, s[3]) + s[4], value)
        return css(value)
    return STYLE.sub(lambda s: s[1] + css(s[2]) + s[3], TAG.sub(tag, text))

def preview_row(c, sid, full):
    parent, _, name = full.rpartition('/')
    return c.execute("SELECT name,blob FROM files WHERE space_id=? AND folder=? AND name=? AND kind='file' AND deleted IS NULL", (sid, parent, name)).fetchone()

@router.get('/preview/{token}/{path:path}')
def preview_file(token: str, path: str):
    sid, folder = unpack(token)
    parts = path.rstrip('/').split('/') if path else []
    if len(path) > 4200 or any(not part or part in ('.', '..') or files.BAD.search(part) for part in parts):
        raise HTTPException(404, 'File not found.')
    relative = '/'.join(parts)
    full = files.joined(folder, relative) if relative else folder
    status = 200
    with db() as c:
        if files.folder_exists(c, sid, full): full = files.joined(full, 'index.html')
        elif path.endswith('/'): full = ''
        elif not PurePosixPath(full).suffix: full += '.html'
        f = full and preview_row(c, sid, full)
        if not f:
            # As on the live site: the site's own 404 page, when it has one.
            f, status = preview_row(c, sid, files.joined(folder, '404.html')), 404
            if not f: raise HTTPException(404, 'File not found.')
    kind = PurePosixPath(f['name'].lower()).suffix
    if kind in ('.html', '.htm', '.css'):
        base = f'/api/community/preview/{token}'
        text = files.blob_path(f['blob']).read_bytes().decode('utf-8', 'surrogateescape')
        return Response(rebased(text, kind[1:], base).encode('utf-8', 'surrogateescape'), status_code=status,
                        media_type=files.media_type(f['name']), headers=PREVIEW_HEADERS)
    return FileResponse(files.blob_path(f['blob']), status_code=status, media_type=files.media_type(f['name']), headers=PREVIEW_HEADERS)
