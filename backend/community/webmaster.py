"""Webmaster tools: bring a website into the file bank from its own address, to change it there.

The Grove reads the site the way a visitor's browser would: the start page, the pages it links
to on the same address, and the styles, scripts, images and fonts they use there, as the site's
robots.txt allows. Links to other sites are listed, never followed. It connects only to public
internet addresses, and only to the one it checked, so an import cannot reach this server or its
network. Files land in the chosen space's file bank under Website/<host>; importing again adds new
versions of whatever changed and deletes nothing."""
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import grove_manager, identifier, now
from .store import db, VERSION
from .activity import record
from .routes import membership
from . import files, live

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
    live.publish(sid)

class ImportBody(BaseModel):
    url: str = Field(min_length=3, max_length=2000)
    space_id: str = Field(min_length=1, max_length=64)

def job(row):
    return {**dict(row), 'notes': json.loads(row['notes'] or '{}')}

@router.post('/imports', status_code=202)
def start_import(body: ImportBody, tasks: BackgroundTasks, current=Depends(grove_manager)):
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
def imports(current=Depends(grove_manager)):
    with db() as c:
        return [job(r) for r in c.execute('''SELECT i.*,COALESCE(s.name,'') AS space_name FROM site_imports i
                                              LEFT JOIN spaces s ON s.id=i.space_id ORDER BY i.started DESC LIMIT 10''')]
