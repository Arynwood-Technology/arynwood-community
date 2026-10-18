"""The Grove's website: the pages visitors see at its address, published from a folder in Files.

A website is a folder in a space's Website folder with an index.html at its top: plain HTML, CSS,
scripts and images, such as one brought in with the webmaster tools. Everyone in the Grove can
preview it; its owners and webmasters publish it. A release lists the folder's files by blob as they were, so editing the folder
changes nothing until the next publish, and an earlier release can be put back at once. Pages get
clean addresses, as on Cloudflare Pages: /about serves about.html, and /about.html moves to
/about. The Grove's own addresses (/community, /api and the members' page's files) stay the Grove's.

Published pages share the Grove's address, so each is served in a sandbox: its scripts run, but
as a page from nowhere, unable to read members' cookies or act with their sign-in."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from .auth import user, webmaster, looks_after_website, identifier, now
from .store import db, grove_setting
from .activity import record
from .routes import membership
from . import files, editor

router = APIRouter()
LIVE = 'website_release'  # grove_settings: the release visitors see
KEEP = 10                 # earlier releases kept to put back
POLICY = "sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads; frame-ancestors 'self'"
HIDDEN = {'_headers', '_redirects'}  # Cloudflare Pages' settings files, never served by it either
RELEASE = '''SELECT r.*,COALESCE(s.name,'') AS space_name,COALESCE(u.name,'') AS user_name FROM site_releases r
             LEFT JOIN spaces s ON s.id=r.space_id LEFT JOIN users u ON u.id=r.user_id'''

def grove_keeps(path):
    """Whether the Grove answers this address itself, whatever a published site has there."""
    from backend.api import web_dir  # the members' page; imported here, as the app imports this module
    if path in ('community', 'api') or path.startswith(('community/', 'api/')): return True
    return path != 'index.html' and (web_dir() / path).is_file()

def release(c, rid):
    row = c.execute(RELEASE + ' WHERE r.id=?', (rid,)).fetchone()
    return dict(row, live=rid == grove_setting(c, LIVE, '')) if row else None

def sites(c, uid):
    """Every space's websites, and whether this person is in the space that keeps each one."""
    out = []
    for r in c.execute('''SELECT f.space_id,s.name AS space_name,f.folder,
                          EXISTS(SELECT 1 FROM members m WHERE m.space_id=f.space_id AND m.user_id=?) AS member,
                          (SELECT COUNT(*) FROM site_notes n WHERE n.space_id=f.space_id AND n.folder=f.folder AND n.status='open') AS notes
                          FROM files f JOIN spaces s ON s.id=f.space_id
                          WHERE f.name='index.html' AND f.kind='file' AND f.deleted IS NULL
                          AND substr(f.folder,1,8)='Website/' AND instr(substr(f.folder,9),'/')=0
                          ORDER BY s.name COLLATE NOCASE,f.folder COLLATE NOCASE''', (uid,)):
        where, args = files.inside(r['folder'])
        count, size, updated = c.execute(f"SELECT COUNT(*),COALESCE(SUM(size),0),MAX(updated) FROM files WHERE space_id=? AND kind='file' AND deleted IS NULL AND {where}",
                                         (r['space_id'], *args)).fetchone()
        out.append({**dict(r), 'member': bool(r['member']), 'name': r['folder'][len('Website/'):], 'files': count, 'bytes': size, 'updated': updated})
    return out

@router.get('/site')
def site(current=Depends(user)):
    with db() as c:
        releases = [release(c, r['id']) for r in c.execute('SELECT id FROM site_releases ORDER BY created DESC')]
        return {'live': next((r for r in releases if r['live']), None), 'sites': sites(c, current['id']),
                'releases': releases if looks_after_website(current) else []}

class SiteBody(BaseModel):
    space_id: str = Field(min_length=1, max_length=64)
    folder: str = Field(min_length=1, max_length=4200)

def site_folder(c, sid, folder):
    """A website's folder: Website/<name>, with an index.html at its top."""
    folder = files.clean_folder(folder)
    if folder.count('/') != 1 or not files.website(folder) or not files.folder_exists(c, sid, folder): raise HTTPException(404, 'Website not found.')
    if not c.execute("SELECT 1 FROM files WHERE space_id=? AND folder=? AND name='index.html' AND kind='file' AND deleted IS NULL", (sid, folder)).fetchone():
        raise HTTPException(422, f'{folder} needs a page called index.html at its top. It’s the front page.')
    return folder

class PreviewBody(SiteBody):
    bridge: bool = False  # for the Grove's own preview pane: its pins, notes and live updates
    drafts: bool = False  # with this webmaster's unsaved changes

def a_site(c, sid, folder):
    if not c.execute('SELECT 1 FROM spaces WHERE id=?', (sid,)).fetchone(): raise HTTPException(404, 'Website not found.')
    return site_folder(c, sid, folder)

@router.post('/previews')
def preview(body: PreviewBody, current=Depends(user)):
    """Anyone in the Grove may look at its websites before they're published."""
    with db() as c:
        folder = a_site(c, body.space_id, body.folder)
        if body.drafts:
            if not looks_after_website(current): raise HTTPException(403, 'Only this Grove’s owners and webmasters change its website.')
            membership(c, body.space_id, current['id'])
    return {'url': editor.preview_url(body.space_id, folder, drafts=current['id'] if body.drafts else None, bridge=body.bridge)}

@router.get('/files')
def site_files(space_id: str, folder: str, current=Depends(webmaster)):
    """Everything in a website's folder, for the site editor, with this webmaster's drafts."""
    with db() as c:
        membership(c, space_id, current['id'])
        folder = site_folder(c, space_id, folder)
        where, args = files.inside(folder)
        drafts = {r['file_id']: dict(r) for r in c.execute(f'''SELECT d.file_id,d.version,d.updated FROM file_drafts d JOIN files f ON f.id=d.file_id
                                                                 WHERE d.user_id=? AND f.space_id=? AND f.deleted IS NULL AND {where.replace('folder', 'f.folder')}''',
                                                              (current['id'], space_id, *args))}
        items = [{**dict(r), 'draft': drafts.get(r['id'])} for r in c.execute(files.ITEM + f" WHERE f.space_id=? AND f.deleted IS NULL AND {where.replace('folder', 'f.folder')} ORDER BY f.folder,f.kind DESC,f.name COLLATE NOCASE",
                                                                           (space_id, *args))]
        return {'space_id': space_id, 'folder': folder, 'items': items}

def go_live(c, rid):
    c.execute('INSERT OR REPLACE INTO grove_settings VALUES (?,?)', (LIVE, rid))

@router.post('/publish', status_code=201)
def publish(body: SiteBody, current=Depends(webmaster)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c, body.space_id, current['id'])
        folder = site_folder(c, body.space_id, body.folder)
        where, args = files.inside(folder)
        pages = {(files.joined(r['folder'][len(folder) + 1:], r['name']) if r['folder'] != folder else r['name']): r
                 for r in c.execute(f"SELECT folder,name,blob,size FROM files WHERE space_id=? AND kind='file' AND deleted IS NULL AND {where}", (body.space_id, *args))}
        rid = identifier()
        c.execute('INSERT INTO site_releases VALUES (?,?,?,?,?,?,?)', (rid, body.space_id, folder, len(pages), sum(r['size'] for r in pages.values()), current['id'], now()))
        c.executemany('INSERT INTO site_release_files VALUES (?,?,?,?)', [(rid, path, r['blob'], r['size']) for path, r in pages.items()])
        go_live(c, rid)
        # Older releases go, oldest first; their blobs go with the daily sweep once nothing names them.
        c.execute('DELETE FROM site_releases WHERE id IN (SELECT id FROM site_releases WHERE id<>? ORDER BY created DESC LIMIT -1 OFFSET ?)', (rid, KEEP))
        record(c, 'site_published', actor=current['id'], space=body.space_id, target=rid, target_name=folder, files=len(pages))
        return {**release(c, rid), 'hidden': sorted(p for p in pages if p in HIDDEN or grove_keeps(p))}

@router.post('/releases/{rid}/live')
def put_back(rid: str, current=Depends(webmaster)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = release(c, rid)
        if not row: raise HTTPException(404, 'That release is no longer kept.')
        go_live(c, rid)
        record(c, 'site_put_back', actor=current['id'], target=rid, target_name=row['folder'], published=row['created'])
        return release(c, rid)

@router.delete('/live')
def take_down(current=Depends(webmaster)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = release(c, grove_setting(c, LIVE, ''))
        if not row: raise HTTPException(409, 'Nothing is published.')
        c.execute('DELETE FROM grove_settings WHERE key=?', (LIVE,))
        record(c, 'site_taken_down', actor=current['id'], target=row['id'], target_name=row['folder'])
    return {'ok': True}

# Visitors ---------------------------------------------------------------------------------------
def find(c, rid, path):
    return c.execute('SELECT path,blob FROM site_release_files WHERE release_id=? AND path=?', (rid, path)).fetchone()

def locate(c, rid, path):
    """The file an address names, or the clean address it moved to: (row, None) or (None, address)."""
    if path in HIDDEN: return None, None
    if path.endswith('.html'):
        if not find(c, rid, path): return None, None
        clean = path[:-len('.html')]
        return None, '/' + (clean[:-len('index')] if clean == 'index' or clean.endswith('/index') else clean)
    if not path or path.endswith('/'): return find(c, rid, path + 'index.html'), None
    row = find(c, rid, path) or find(c, rid, path + '.html')
    if row: return row, None
    return None, ('/' + path + '/' if find(c, rid, path + '/index.html') else None)

def respond(row, request, status=200):
    tag = f'"{row["blob"]}"'
    headers = {'Content-Security-Policy': POLICY, 'X-Frame-Options': 'SAMEORIGIN', 'Access-Control-Allow-Origin': '*',
               'Cache-Control': 'no-cache', 'ETag': tag}
    if status == 200 and tag in request.headers.get('if-none-match', ''): return Response(status_code=304, headers=headers)
    return FileResponse(files.blob_path(row['blob']), status_code=status, media_type=files.media_type(row['path']), headers=headers)

def page(path, request):
    """The live site's answer for an address, or None when it has nothing there."""
    with db() as c:
        rid = grove_setting(c, LIVE, '')
        if not rid: return None
        row, moved = locate(c, rid, path)
    if moved: return RedirectResponse(moved + (f'?{request.url.query}' if request.url.query else ''), status_code=308)
    return respond(row, request) if row else None

def missing(request):
    """The live site's 404.html, for an address nothing answers."""
    with db() as c:
        rid = grove_setting(c, LIVE, '')
        row = rid and find(c, rid, '404.html')
    return respond(row, request, 404) if row else None
