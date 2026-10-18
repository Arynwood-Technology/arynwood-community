"""Webmaster tools: bring a website into the file bank, to change it there and publish it.

A website comes from its own address, from a .zip, or as a one-page starter made from the Grove's
branding. Only the Grove's owners and webmasters bring sites in.

From an address, the Grove reads the site the way a visitor's browser would: the start page, the pages it links
to on the same address, and the styles, scripts, images and fonts they use there, as the site's
robots.txt allows. Links to other sites are listed, never followed. It connects only to public
internet addresses, and only to the one it checked, so an import cannot reach this server or its
network. Files land in the chosen space's file bank under Website/<host>; importing again adds new
versions of whatever changed and deletes nothing."""
import hashlib
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import stat
import logging
import time
import zipfile
import zlib
from collections import deque
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import webmaster, identifier, now
from .store import db, public_origin, VERSION
from .activity import record
from .routes import membership
from . import files

router = APIRouter()
logger = logging.getLogger(__name__)
AGENT = 'ArynwoodGrove'
USER_AGENT = f'{AGENT}/{VERSION} (website import; +https://arynwood.com/community/)'
MAX_FILES = 400
MAX_FILE = 50 * files.MB
MAX_TOTAL = 300 * files.MB
SECONDS = 600
STALE = 900  # an import still "running" after this was cut short by a restart
# Cloudflare adds its analytics script to each page as it serves it, at a versioned path, unlike the
# snippet a site's owners paste in themselves. Kept, it would be added a second time once published.
INJECTED = re.compile(rb'<script[^>]*static\.cloudflareinsights\.com/beacon\.min\.js/v[0-9a-f]+[^>]*>\s*</script>', re.I)
NAT64 = [ipaddress.ip_network('64:ff9b::/96'), ipaddress.ip_network('64:ff9b:1::/48')]

class Refused(Exception):
    pass

def reachable(ip):
    """A public internet address, including one tunnelled inside an IPv6 address."""
    address = ipaddress.ip_address(ip.split('%')[0])
    if address.version == 6:
        inner = address.ipv4_mapped or address.sixtofour or next((ipaddress.IPv4Address(int(address) & 0xFFFFFFFF) for net in NAT64 if address in net), None)
        if inner is not None and not inner.is_global: return False
    return address.is_global

def public_address(host, port):
    """The address to connect to, once every address the name has is public."""
    try: found = [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
    except (socket.gaierror, UnicodeError): raise Refused(f'{host} could not be found.')
    if not found or not all(reachable(ip) for ip in found): raise Refused(f'{host} is not a public address.')
    return found[0]

class PinnedHTTPS(http.client.HTTPSConnection):
    """Connects to the address that was checked, while checking the certificate for the name."""
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.ip = ip
    def connect(self):
        self.sock = self._context.wrap_socket(socket.create_connection((self.ip, self.port), self.timeout), server_hostname=self.host)

class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self.ip = ip
    def connect(self):
        self.sock = socket.create_connection((self.ip, self.port), self.timeout)

def origin(url):
    parts = urlsplit(url)
    return parts.scheme, (parts.hostname or '').lower(), parts.port or (443 if parts.scheme == 'https' else 80)

def start_url(value):
    value = value.strip()
    if '://' not in value: value = 'https://' + value
    try: parts = urlsplit(value)
    except ValueError: parts = None
    if not parts or parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or any(c.isspace() for c in value):
        raise HTTPException(422, 'Enter a web address like https://example.com.')
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or '/', parts.query, ''))

def fetch(url, site, limit):
    """GET a URL on the site, following redirects that stay on it: (url, type, server, body), or a reason it was skipped."""
    for _ in range(6):
        scheme, host, port = origin(url)
        if (scheme, host, port) != site: return 'it moved to another site'
        parts = urlsplit(url)
        connection = (PinnedHTTPS if scheme == 'https' else PinnedHTTP)(host, port, public_address(host, port), 20)
        try:
            connection.request('GET', (parts.path or '/') + (f'?{parts.query}' if parts.query else ''), headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308) and response.getheader('Location'):
                url = urljoin(url, response.getheader('Location')); continue
            if response.status != 200: return f'the site answered {response.status}'
            if int(response.getheader('Content-Length') or 0) > limit: return 'it is too large'
            body = response.read(limit + 1)
            if len(body) > limit: return 'it is too large'
            return url, (response.getheader('Content-Type') or '').split(';')[0].strip().lower(), response.getheader('Server') or '', body
        finally:
            connection.close()
    return 'it redirects too many times'

class Links(HTMLParser):
    """Everything a page refers to: pages it links to, and what it needs to display."""
    SOURCES = {'link': 'href', 'script': 'src', 'img': 'src', 'source': 'src', 'video': 'poster', 'audio': 'src',
               'track': 'src', 'input': 'src', 'embed': 'src', 'object': 'data', 'iframe': 'src'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.style = [], False
    def handle_starttag(self, tag, attrs):
        a = {k: v for k, v in attrs if v}
        if tag == 'a' and a.get('href'): self.found.append(a['href'])
        if a.get(self.SOURCES.get(tag, '')): self.found.append(a[self.SOURCES[tag]])
        if tag == 'video' and a.get('src'): self.found.append(a['src'])
        for candidates in (a.get('srcset'), a.get('imagesrcset')):
            if candidates: self.found += [c.strip().split(' ')[0] for c in candidates.split(',') if c.strip()]
        if tag == 'meta' and a.get('property', a.get('name', '')) in ('og:image', 'twitter:image') and a.get('content'): self.found.append(a['content'])
        if a.get('style'): self.found += css_links(a['style'])
        self.style = tag == 'style'
    def handle_endtag(self, tag): self.style = False
    def handle_data(self, data):
        if self.style: self.found += css_links(data)

def css_links(text):
    return [m[1] for m in re.findall(r'url\(\s*([\'"]?)([^\'")]+)\1\s*\)', text)] + [m[1] for m in re.findall(r'@import\s+([\'"])([^\'"]+)\1', text)]

def references(url, kind, body):
    text = body.decode('utf-8', 'replace')
    if kind == 'text/css': found = css_links(text)
    elif kind in ('text/html', 'application/xhtml+xml'):
        parser = Links(); parser.feed(text); found = parser.found
    else: return []
    return [urljoin(url, f.strip()) for f in found if not f.strip().lower().startswith(('data:', 'javascript:', 'mailto:', 'tel:', '#'))]

def local_path(url, kind):
    """Where a URL's file goes in the website's folder: / is index.html, an extensionless page gets .html."""
    path = unquote(urlsplit(url).path)
    if not path or path.endswith('/'): path += 'index.html'
    parts = [p for p in path.split('/') if p]
    if kind == 'text/html' and '.' not in parts[-1]: parts[-1] += '.html'
    return '/'.join(files.clean_name(p) for p in parts)

def ensure_folder(c, sid, path, uid):
    """Makes each missing folder on the way to `path`."""
    folder = ''
    for name in [p for p in path.split('/') if p]:
        row = c.execute('SELECT kind FROM files WHERE space_id=? AND folder=? AND name=? AND deleted IS NULL', (sid, folder, name)).fetchone()
        if row and row['kind'] != 'folder': raise Refused(f'{files.joined(folder, name)} is a file, not a folder.')
        if not row:
            stamp = now()
            c.execute('INSERT INTO files (id,space_id,folder,name,kind,author_id,updated_by,created,updated) VALUES (?,?,?,?,?,?,?,?,?)',
                      (identifier(), sid, folder, name, 'folder', uid, uid, stamp, stamp))
        folder = files.joined(folder, name)

def store_file(sid, uid, folder, path, body):
    """'added', 'changed' or 'unchanged'. A changed file gets a new version; nothing is ever deleted."""
    blob = hashlib.sha256(body).hexdigest()
    target = files.blob_path(blob)
    if not target.exists():
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        staging = target.with_suffix('.part')
        staging.write_bytes(body)
        staging.replace(target)
    where, name = path.rpartition('/')[::2]
    where = files.joined(folder, where) if where else folder
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM orphan_blobs WHERE blob=?', (blob,))
        current = c.execute('SELECT * FROM files WHERE space_id=? AND folder=? AND name=? AND deleted IS NULL', (sid, where, name)).fetchone()
        if current and current['kind'] == 'folder': raise Refused(f'{files.joined(where, name)} is a folder.')
        if current and current['blob'] == blob: return 'unchanged'
        if files.used(c, sid) + len(body) > files.space_limit(): raise Refused('The space ran out of room.')
        ensure_folder(c, sid, where, uid)
        stamp = now()
        if current:
            c.execute('INSERT INTO file_versions VALUES (?,?,?,?,?,?)', (current['id'], current['version'], current['blob'], current['size'], current['updated_by'], current['updated']))
            c.execute('UPDATE files SET blob=?,size=?,version=version+1,updated_by=?,updated=? WHERE id=?', (blob, len(body), uid, stamp, current['id']))
            return 'changed'
        c.execute('INSERT INTO files (id,space_id,folder,name,kind,blob,size,author_id,updated_by,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  (identifier(), sid, where, name, 'file', blob, len(body), uid, uid, stamp, stamp))
        return 'added'

def robots(url, site):
    rules = RobotFileParser()
    got = fetch(urljoin(url, '/robots.txt'), site, files.MB)
    rules.parse(got[3].decode('utf-8', 'replace').splitlines() if isinstance(got, tuple) else [])
    return rules

def run_import(job):
    with db() as c: row = c.execute('SELECT * FROM site_imports WHERE id=?', (job,)).fetchone()
    sid, uid, start, folder = row['space_id'], row['user_id'], row['url'], row['folder']
    site, counts, notes = origin(start), {'added': 0, 'changed': 0, 'unchanged': 0, 'skipped': 0}, {'elsewhere': [], 'skipped': [], 'server': ''}
    total, deadline, seen, saved = 0, time.monotonic() + SECONDS, {start}, set()
    queue = deque([start])
    def progress(status='running', message=''):
        with db() as c:
            c.execute('UPDATE site_imports SET status=?,added=?,changed=?,unchanged=?,skipped=?,bytes=?,notes=?,message=?,finished=? WHERE id=?',
                      (status, counts['added'], counts['changed'], counts['unchanged'], counts['skipped'], total, json.dumps(notes), message, None if status == 'running' else now(), job))
    def skip(url, reason):
        counts['skipped'] += 1
        if len(notes['skipped']) < 50: notes['skipped'].append([urlsplit(url).path or '/', reason])
    try:
        rules = robots(start, site)
        while queue:
            if time.monotonic() > deadline: raise Refused('The import took too long; what arrived is kept.')
            if len(saved) >= MAX_FILES: raise Refused(f'The site has more than {MAX_FILES} files; the first {MAX_FILES} are kept.')
            url = queue.popleft()
            if not rules.can_fetch(AGENT, url): skip(url, 'its robots.txt asks visitors like the Grove not to'); continue
            if urlsplit(url).path.startswith('/cdn-cgi/'): skip(url, 'Cloudflare adds it as the site is served'); continue
            got = fetch(url, site, min(MAX_FILE, MAX_TOTAL - total))
            if isinstance(got, str): skip(url, got); continue
            final, kind, server, body = got
            notes['server'] = notes['server'] or server
            if kind == 'text/html':
                body, injected = INJECTED.subn(b'', body)
                if injected: notes['cloudflare_analytics'] = True
            try: path = local_path(url, kind)
            except HTTPException: skip(url, 'its name cannot be kept as a file'); continue
            if path not in saved:
                saved.add(path)
                counts[store_file(sid, uid, folder, path, body)] += 1
                total += len(body)
            for ref in references(final, kind, body):
                ref = urlunsplit(urlsplit(ref)._replace(fragment=''))
                if origin(ref) != site:
                    host = urlsplit(ref).hostname
                    if host and urlsplit(ref).scheme in ('http', 'https') and host not in notes['elsewhere']: notes['elsewhere'].append(host)
                elif ref not in seen:
                    seen.add(ref); queue.append(ref)
            progress()
        status, message = 'done', ''
    except Refused as reason:
        status, message = 'done' if saved else 'failed', str(reason)
    except (OSError, http.client.HTTPException, ssl.SSLError) as error:
        status, message = 'done' if saved else 'failed', f'The site could not be read: {error}'
    except Exception:
        logger.exception('Website import %s failed', job)
        status, message = 'failed', 'Something went wrong on the server. Tell the host.'
    progress(status, message)
    with db() as c:
        record(c, 'site_imported', actor=uid, space=sid, target=job, target_name=folder, url=start, status=status, **counts)
    files.announce(sid, folder)

class ImportBody(BaseModel):
    url: str = Field(min_length=3, max_length=2000)
    space_id: str = Field(min_length=1, max_length=64)

def job(row):
    return {**dict(row), 'notes': json.loads(row['notes'] or '{}')}

@router.post('/imports', status_code=202)
def start_import(body: ImportBody, tasks: BackgroundTasks, current=Depends(webmaster)):
    url = start_url(body.url)
    _, host, port = origin(url)
    try: public_address(host, port)
    except Refused as reason: raise HTTPException(422, str(reason))
    folder = files.joined('Website', files.clean_name(host))
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c, body.space_id, current['id'])
        c.execute("UPDATE site_imports SET status='failed',message='The server restarted during the import.',finished=? WHERE status='running' AND started<?",
                  (now(), (datetime.now(timezone.utc) - timedelta(seconds=STALE)).isoformat()))
        if c.execute("SELECT 1 FROM site_imports WHERE status='running'").fetchone(): raise HTTPException(409, 'An import is already running. Wait for it to finish.')
        jid = identifier()
        c.execute('INSERT INTO site_imports (id,space_id,user_id,url,folder,status,started) VALUES (?,?,?,?,?,?,?)', (jid, body.space_id, current['id'], url, folder, 'running', now()))
        saved = job(c.execute('SELECT * FROM site_imports WHERE id=?', (jid,)).fetchone())
    tasks.add_task(run_import, jid)
    return saved

@router.get('/imports')
def imports(current=Depends(webmaster)):
    with db() as c:
        return [job(r) for r in c.execute('''SELECT i.*,COALESCE(s.name,'') AS space_name FROM site_imports i
                                              LEFT JOIN spaces s ON s.id=i.space_id ORDER BY i.started DESC LIMIT 10''')]

# A site sent as a .zip ------------------------------------------------------------------------------
ZIP_FILES = 2000
JUNK = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}

class UnpackBody(BaseModel):
    space_id: str = Field(min_length=1, max_length=64)
    file_id: str = Field(min_length=1, max_length=64)

@router.post('/unpack', status_code=201)
def unpack(body: UnpackBody, current=Depends(webmaster)):
    """A .zip in Files, such as a site that isn't online yet, unpacked into Website/<its name>.
    Unpacking again adds new versions of whatever changed and deletes nothing, as importing does."""
    sid, uid = body.space_id, current['id']
    with db() as c:
        membership(c, sid, uid)
        f = files.live_item(c, sid, body.file_id, 'file')
    stem = f['name'][:-len('.zip')] if f['name'].lower().endswith('.zip') else f['name']
    folder = files.joined('Website', files.clean_name(stem))
    counts, skipped, total, message = {'added': 0, 'changed': 0, 'unchanged': 0, 'skipped': 0}, [], 0, ''
    def skip(name, reason):
        counts['skipped'] += 1
        if len(skipped) < 50: skipped.append([name, reason])
    try: archive = zipfile.ZipFile(files.blob_path(f['blob']))
    except (zipfile.BadZipFile, OSError): raise HTTPException(422, 'That file isn’t a .zip the Grove can open.')
    with archive:
        entries = [(i, i.filename.replace('\\', '/').lstrip('/')) for i in archive.infolist() if not i.is_dir()]
        entries = [(i, name) for i, name in entries if not name.startswith('__MACOSX/') and name.rsplit('/', 1)[-1] not in JUNK]
        # A zip of a folder: what was in the folder goes at the top of the website's folder.
        inner = len({name.split('/', 1)[0] for _, name in entries}) == 1 and all('/' in name for _, name in entries)
        try:
            if len(entries) > ZIP_FILES: raise Refused(f'The .zip holds more than {ZIP_FILES} files.')
            for info, name in entries:
                path = name.split('/', 1)[1] if inner else name
                if info.flag_bits & 1: skip(path, 'it is password-protected'); continue
                if stat.S_ISLNK(info.external_attr >> 16): skip(path, 'it is a link, not a file'); continue
                try: path = files.clean_folder(files.joined(folder, path))[len(folder) + 1:]
                except HTTPException: skip(path, 'its name cannot be kept as a file'); continue
                limit = min(MAX_FILE, MAX_TOTAL - total)
                try:
                    with archive.open(info) as source: data = source.read(limit + 1)
                except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError): skip(path, 'it is damaged, or packed in a way the Grove can’t read'); continue
                if len(data) > limit: skip(path, 'it is too large'); continue
                counts[store_file(sid, uid, folder, path, data)] += 1
                total += len(data)
        except Refused as reason:
            message = str(reason)
    with db() as c:
        front = c.execute("SELECT 1 FROM files WHERE space_id=? AND folder=? AND name='index.html' AND kind='file' AND deleted IS NULL", (sid, folder)).fetchone()
        record(c, 'site_unpacked', actor=uid, space=sid, target=f['id'], target_name=folder, zip=f['name'], **counts)
    files.announce(sid, folder)
    return {'space_id': sid, 'folder': folder, **counts, 'bytes': total, 'skipped_files': skipped, 'message': message, 'has_index': bool(front)}

# A one-page starter -------------------------------------------------------------------------------
# Colours for a Grove without branding: the members' page's own.
PLAIN = {'--bg': '#0f1314', '--surface': '#171c1d', '--text': '#f4f8f6', '--text-muted': '#b8c7c1', '--accent': '#4fd1ab',
         '--on-accent': '#0f1314', '--accent-text': '#4fd1ab', '--border': '#354343'}
LOGO_NAMES = {'image/png': 'logo.png', 'image/jpeg': 'logo.jpg', 'image/webp': 'logo.webp'}

def starter_page(brand, logo):
    """The Grove's front page: its name, tagline, a way to the members' page, and its website if it has one."""
    tokens = {**PLAIN, **{k: v for k, v in brand['theme'].items() if k in PLAIN}}
    e = lambda value: html.escape(value, quote=True)
    name, tagline = e(brand['name']), e(brand['tagline'])
    elsewhere = f'<a class="button secondary" href="{e(brand["site_url"])}">{e(brand["site_label"])}</a>' if brand['site_url'] else ''
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<meta name="description" content="{tagline}">
<!-- {name}'s front page, made from the Grove's name, tagline and colours. Change anything here,
     preview it in Webmaster tools, and publish it when it's ready. -->
<style>
  :root {{ color-scheme: dark; --bg: {tokens['--bg']}; --surface: {tokens['--surface']}; --text: {tokens['--text']}; --muted: {tokens['--text-muted']};
          --accent: {tokens['--accent']}; --on-accent: {tokens['--on-accent']}; --link: {tokens['--accent-text']}; --border: {tokens['--border']}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; display: flex; flex-direction: column; background: var(--bg); color: var(--text);
         font: 17px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
  main {{ flex: 1; display: grid; place-items: center; padding: 48px 16px; }}
  .card {{ width: 100%; max-width: 640px; text-align: center; }}
  .logo {{ max-width: 160px; max-height: 160px; width: auto; height: auto; margin: 0 auto 24px; display: block; }}
  h1 {{ font-size: clamp(2rem, 7vw, 3.25rem); line-height: 1.1; margin: 0 0 12px; overflow-wrap: anywhere; }}
  .tagline {{ color: var(--muted); font-size: 1.2rem; margin: 0 0 32px; }}
  .actions {{ display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; margin: 0; }}
  .button {{ display: inline-block; padding: 12px 22px; border-radius: 999px; font-weight: 700; text-decoration: none; }}
  .primary {{ background: var(--accent); color: var(--on-accent); }}
  .secondary {{ border: 1px solid var(--border); color: var(--text); background: var(--surface); }}
  .button:focus-visible, footer a:focus-visible {{ outline: 3px solid var(--link); outline-offset: 3px; }}
  footer {{ padding: 20px 16px; text-align: center; color: var(--muted); font-size: .9rem; }}
</style>
</head>
<body>
<main>
  <div class="card">
    {f'<img class="logo" src="{logo}" alt="">' if logo else ''}
    <h1>{name}</h1>
    <p class="tagline">{tagline}</p>
    <p class="actions"><a class="button primary" href="/community">Members: sign in</a>{elsewhere}</p>
  </div>
</main>
<footer>{name} · Made with Arynwood Grove</footer>
</body>
</html>
'''

class StarterBody(BaseModel):
    space_id: str = Field(min_length=1, max_length=64)

@router.post('/starter', status_code=201)
def starter(body: StarterBody, current=Depends(webmaster)):
    """A one-page website for a Grove that has none yet, in Website/<the Grove's address>."""
    from backend.brand import read_brand
    brand = read_brand()
    folder = files.joined('Website', files.clean_name(urlsplit(public_origin()).hostname or 'home'))
    with db() as c:
        membership(c, body.space_id, current['id'])
        if c.execute("SELECT 1 FROM files WHERE space_id=? AND folder=? AND name='index.html' AND deleted IS NULL", (body.space_id, folder)).fetchone():
            raise HTTPException(409, f'{folder} already has a front page. Open it in Files to change it.')
    logo = brand['_logo'] and LOGO_NAMES[brand['_logo'][1]]
    try:
        if logo: store_file(body.space_id, current['id'], folder, logo, brand['_logo'][0])
        store_file(body.space_id, current['id'], folder, 'index.html', starter_page(brand, logo).encode())
    except Refused as reason:
        raise HTTPException(409, str(reason))
    with db() as c: record(c, 'site_started', actor=current['id'], space=body.space_id, target_name=folder)
    files.announce(body.space_id, folder)
    return {'space_id': body.space_id, 'folder': folder}
