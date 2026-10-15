"""Webmaster tools: a website comes in from its own address, and leaves again as a .zip."""
import io
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import test_hub
from backend.community import webmaster

H = test_hub.H
PAGES = {
    '/': ('text/html', b'''<html><head><link rel="stylesheet" href="style.css?v=2"><meta property="og:image" content="/assets/share.jpg"></head>
        <body><a href="filmmakers.html">Filmmakers</a><a href="https://player.vimeo.com/video/1">Intro</a>
        <a href="http://169.254.169.254/latest/meta-data/">Not ours</a><a href="/private/plans.html">Plans</a><a href="/gone.html">Gone</a>
        <a href="/away.html">Away</a><a href="/huge.mov">Screener</a><img src="assets/logo.png" srcset="assets/logo@2x.png 2x">
        <a href="mailto:hello@festival.test">Mail</a><a href="#top">Top</a><a href="/cdn-cgi/l/email-protection">Email</a>
        <script type="module" src="https://static.cloudflareinsights.com/beacon.min.js/v4bc70e2c" data-cf-beacon='{"version":"2024.11.0","r":1}' crossorigin="anonymous"></script></body></html>'''),
    '/filmmakers': ('text/html', b'''<html><body><img src="assets/mascot.png"><a href="/">Home</a>
        <script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "theirs"}'></script></body></html>'''),
    '/style.css': ('text/css', b"@import 'more.css'; body{background:url('assets/bg.jpg')}"),
    '/more.css': ('text/css', b'h1{color:#e2326f}'),
    '/assets/logo.png': ('image/png', b'\x89PNG logo'),
    '/assets/logo@2x.png': ('image/png', b'\x89PNG logo 2x'),
    '/assets/mascot.png': ('image/png', b'\x89PNG mascot'),
    '/assets/bg.jpg': ('image/jpeg', b'\xff\xd8 background'),
    '/assets/share.jpg': ('image/jpeg', b'\xff\xd8 share'),
    '/private/plans.html': ('text/html', b'secret'),
    '/huge.mov': ('video/quicktime', b'x' * 4096),
    '/robots.txt': ('text/plain', b'User-agent: *\nDisallow: /private/\n'),
}


class Site(BaseHTTPRequestHandler):
    requested = []
    def do_GET(self):
        Site.requested.append(self.path)
        path = self.path.split('?')[0]
        if path == '/filmmakers.html': return self.answer(307, b'', {'Location': '/filmmakers'})
        if path == '/away.html': return self.answer(302, b'', {'Location': 'https://elsewhere.example/'})
        if path not in PAGES: return self.answer(404, b'')
        kind, body = PAGES[path]
        self.answer(200, body, {'Content-Type': kind})
    def answer(self, status, body, headers=None):
        self.send_response(status)
        for k, v in {'Content-Length': str(len(body)), **(headers or {})}.items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def version_string(self): return 'cloudflare'
    def log_message(self, *args): pass


class WebmasterTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member

    def serve(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        Site.requested = []
        # festival.test is this little server; everything else is refused, as a private address would be.
        def address(host, port):
            if host == 'festival.test': return '127.0.0.1'
            raise webmaster.Refused(f'{host} is not a public address.')
        for patcher in (patch.object(webmaster, 'public_address', address), patch.object(webmaster, 'MAX_FILE', 1024)):
            patcher.start(); self.addCleanup(patcher.stop)
        return f'http://festival.test:{server.server_address[1]}'

    def run_import(self, client, url, sid):
        r = client.post('/api/webmaster/imports', headers=H, json={'url': url, 'space_id': sid})
        self.assertEqual(r.status_code, 202, r.text)
        return client.get('/api/webmaster/imports').json()[0]

    def tree(self, client, sid, folder):
        out = {}
        for item in client.get(f'/api/community/spaces/{sid}/files', params={'folder': folder}).json()['items']:
            path = f"{folder}/{item['name']}"
            if item['kind'] == 'folder': out.update(self.tree(client, sid, path))
            else: out[path] = client.get(f"/api/community/spaces/{sid}/files/{item['id']}/content").content
        return out

    def test_a_site_comes_in_as_its_visitors_see_it(self):
        host, member, sid = self.host_and_member()
        base = self.serve()
        done = self.run_import(host, base, sid)
        self.assertEqual(done['status'], 'done', done)
        root = f"Website/festival.test"
        self.assertEqual(done['folder'], root)
        got = self.tree(host, sid, root)
        self.assertEqual(sorted(got), sorted(f'{root}/{p}' for p in ('index.html', 'filmmakers.html', 'style.css', 'more.css', 'assets/logo.png',
                                                                   'assets/logo@2x.png', 'assets/mascot.png', 'assets/bg.jpg', 'assets/share.jpg')))
        self.assertEqual(got[f'{root}/filmmakers.html'], PAGES['/filmmakers'][1])
        self.assertEqual(done['added'], 9)
        notes = done['notes']
        self.assertEqual(notes['server'], 'cloudflare')
        # Cloudflare's own analytics script comes out of the page it was added to; one the site's owners added stays.
        self.assertTrue(notes['cloudflare_analytics'])
        self.assertNotIn(b'beacon.min.js/v', got[f'{root}/index.html'])
        self.assertIn(b'data-cf-beacon=\'{"token": "theirs"}\'', got[f'{root}/filmmakers.html'])
        self.assertEqual(sorted(notes['elsewhere']), ['169.254.169.254', 'player.vimeo.com', 'static.cloudflareinsights.com'])
        self.assertEqual(sorted(notes['skipped']), sorted([['/private/plans.html', 'its robots.txt asks visitors like the Grove not to'],
            ['/gone.html', 'the site answered 404'], ['/away.html', 'it moved to another site'], ['/huge.mov', 'it is too large'],
            ['/cdn-cgi/l/email-protection', 'Cloudflare adds it as the site is served']]))
        # Never asked for: what robots.txt keeps out, and anything on another address.
        self.assertNotIn('/private/plans.html', Site.requested)
        log = next(a for a in host.get('/api/admin/activity').json()['items'] if a['action'] == 'site_imported')
        self.assertEqual([log['target_name'], log['details']['added'], log['details']['status']], [root, 9, 'done'])

    def test_importing_again_adds_versions_of_what_changed(self):
        host, member, sid = self.host_and_member()
        base = self.serve()
        self.run_import(host, base, sid)
        with patch.dict(PAGES, {'/more.css': ('text/css', b'h1{color:#08bdd4}')}):
            again = self.run_import(host, base, sid)
        self.assertEqual([again[k] for k in ('added', 'changed', 'unchanged')], [0, 1, 8])
        css = next(i for i in host.get(f'/api/community/spaces/{sid}/files', params={'folder': 'Website/festival.test'}).json()['items'] if i['name'] == 'more.css')
        self.assertEqual(css['version'], 2)

    def test_only_owners_and_managers_import_and_only_into_their_spaces(self):
        host, member, sid = self.host_and_member()
        base = self.serve()
        self.assertEqual(member.post('/api/webmaster/imports', headers=H, json={'url': base, 'space_id': sid}).status_code, 403)
        self.assertEqual(member.get('/api/webmaster/imports').status_code, 403)
        theirs = member.post('/api/community/spaces', headers=H, json={'name': 'Volunteers'}).json()
        self.assertEqual(host.post('/api/webmaster/imports', headers=H, json={'url': base, 'space_id': theirs['id']}).status_code, 404)
        for url in ('ftp://festival.test/', 'https://user:pw@festival.test/', 'https://', 'https://exa mple.com'):
            self.assertEqual(host.post('/api/webmaster/imports', headers=H, json={'url': url, 'space_id': sid}).status_code, 422, url)
        refused = host.post('/api/webmaster/imports', headers=H, json={'url': 'http://intranet.local/', 'space_id': sid})
        self.assertEqual([refused.status_code, refused.json()['detail']], [422, 'intranet.local is not a public address.'])

    def test_a_folder_leaves_as_one_zip(self):
        host, member, sid = self.host_and_member()
        base = self.serve()
        self.run_import(host, base, sid)
        site = next(i for i in host.get(f'/api/community/spaces/{sid}/files', params={'folder': 'Website'}).json()['items'])
        r = member.get(f"/api/community/spaces/{sid}/files/{site['id']}/zip")
        self.assertEqual([r.status_code, r.headers['content-type'], r.headers['content-security-policy']], [200, 'application/zip', 'sandbox'])
        self.assertIn('festival.test.zip', r.headers['content-disposition'])
        archive = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertIn('festival.test/assets/logo.png', archive.namelist())
        self.assertEqual(archive.read('festival.test/style.css'), PAGES['/style.css'][1])
        log = host.get('/api/admin/activity', params={'limit': 1}).json()['items'][0]
        self.assertEqual([log['action'], log['target_name'], log['details']], ['folder_downloaded', 'Website/festival.test', {'files': 9}])


class AddressTests(unittest.TestCase):
    def test_only_public_addresses_are_reached(self):
        for ip in ('127.0.0.1', '10.0.0.8', '192.168.1.1', '169.254.169.254', '100.64.0.1', '::1', 'fe80::1', 'fd00::1',
                   '::ffff:127.0.0.1', '64:ff9b::a00:1', '2002:7f00:1::', '0.0.0.0'):
            self.assertFalse(webmaster.reachable(ip), ip)
        for ip in ('104.21.72.100', '172.67.181.29', '2606:4700:3033::6815:4864'):
            self.assertTrue(webmaster.reachable(ip), ip)

    def test_a_name_with_any_private_address_is_refused(self):
        answers = [(None, None, None, None, ('104.21.72.100', 443)), (None, None, None, None, ('10.0.0.8', 443))]
        with patch.object(webmaster.socket, 'getaddrinfo', return_value=answers):
            with self.assertRaises(webmaster.Refused): webmaster.public_address('sneaky.example', 443)
        with patch.object(webmaster.socket, 'getaddrinfo', return_value=answers[:1]):
            self.assertEqual(webmaster.public_address('festival.example', 443), '104.21.72.100')


if __name__ == '__main__':
    unittest.main()
