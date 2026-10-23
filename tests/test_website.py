"""The Grove's website: owners and webmasters bring a site in, everyone previews it, and a
publish puts it at the Grove's address, apart from members' sign-ins."""
import io
import stat
import time
import unittest
import zipfile
from unittest.mock import patch
import test_hub
import test_files
from backend.community import editor, files, website

H = test_hub.H
SITE = {
    'index.html': b'<!doctype html><link rel="stylesheet" href="/styles.css?v=1"><a href="/filmmakers">Filmmakers</a><a href="/community">Members</a>'
                  b'<img src="/img/badge-320.webp" srcset="/img/badge-320.webp 320w, /img/badge-640.webp 640w"><script src="/site.js" defer></script>',
    'filmmakers.html': b'<h1>Filmmakers</h1>',
    'styles.css': b'body{background:url("/img/burst.svg")}',
    'site.js': b'document.body.dataset.ready = "yes"',
    'img/badge-320.webp': b'RIFF0000WEBPbadge',
    'img/badge-640.webp': b'RIFF0000WEBPbadge2x',
    'img/burst.svg': b'<svg xmlns="http://www.w3.org/2000/svg"/>',
    'docs/index.html': b'<h1>Docs</h1>',
    '404.html': b'<h1>Not here</h1>',
    '_headers': b'/*\n  X-Frame-Options: SAMEORIGIN\n',
}


def packed(entries, top='site/'):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, body in entries.items(): archive.writestr(top + name, body)
        archive.writestr('__MACOSX/site/._index.html', b'resource fork')
        archive.writestr(top + '.DS_Store', b'finder')
        link = zipfile.ZipInfo(top + 'shortcut')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, '/etc/passwd')
    return data.getvalue()


class WebsiteTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member
    upload = test_files.FileTests.upload

    def bring_in(self, client, sid, entries=SITE, name='roguefest-site.zip'):
        """Uploads a site as a .zip into Website and unpacks it, as the webmaster page does."""
        client.post(f'/api/community/spaces/{sid}/folders', headers=H, json={'name': 'Website'})
        sent = next((i for i in client.get(f'/api/community/spaces/{sid}/files', params={'folder': 'Website'}).json()['items'] if i['name'] == name), None)
        zipped = self.upload(client, sid, name, packed(entries), folder='Website', piece=1 << 20, replaces=sent and sent['id'])
        self.assertEqual(zipped.status_code, 201, zipped.text)
        r = client.post('/api/webmaster/unpack', headers=H, json={'space_id': sid, 'file_id': zipped.json()['id']})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def publish(self, client, sid, folder='Website/roguefest-site'):
        r = client.post('/api/webmaster/publish', headers=H, json={'space_id': sid, 'folder': folder})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def file(self, client, sid, folder, name):
        return next(i for i in client.get(f'/api/community/spaces/{sid}/files', params={'folder': folder}).json()['items'] if i['name'] == name)

    def test_a_zip_unpacks_into_website_without_its_wrapping_or_junk(self):
        host, member, sid = self.host_and_member()
        done = self.bring_in(host, sid)
        self.assertEqual([done[k] for k in ('folder', 'added', 'changed', 'skipped', 'has_index')], ['Website/roguefest-site', len(SITE), 0, 1, True])
        self.assertEqual(done['skipped_files'], [['shortcut', 'it is a link, not a file']])
        names = {i['name'] for i in host.get(f'/api/community/spaces/{sid}/files', params={'folder': 'Website/roguefest-site'}).json()['items']}
        self.assertEqual(names, {'index.html', 'filmmakers.html', 'styles.css', 'site.js', 'img', 'docs', '404.html', '_headers'})
        # Sent again with one change: a new version of that file, and nothing deleted.
        again = self.bring_in(host, sid, {**SITE, 'filmmakers.html': b'<h1>Filmmakers!</h1>'})
        self.assertEqual([again[k] for k in ('added', 'changed', 'unchanged')], [0, 1, len(SITE) - 1])
        self.assertEqual(self.file(host, sid, 'Website/roguefest-site', 'filmmakers.html')['version'], 2)
        log = host.get('/api/admin/activity', params={'limit': 1}).json()['items'][0]
        self.assertEqual([log['action'], log['target_name'], log['details']['zip']], ['site_unpacked', 'Website/roguefest-site', 'roguefest-site.zip'])

    def test_unsafe_zip_names_stay_out(self):
        host, member, sid = self.host_and_member()
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('index.html', b'home')
            archive.writestr('../escape.html', b'no')
            archive.writestr('/etc/cron.d/job', b'no')
            archive.writestr('a/b\x01c.html', b'no')
        host.post(f'/api/community/spaces/{sid}/folders', headers=H, json={'name': 'Website'})
        zipped = self.upload(host, sid, 'plain.zip', data.getvalue(), folder='Website', piece=1 << 20).json()
        done = host.post('/api/webmaster/unpack', headers=H, json={'space_id': sid, 'file_id': zipped['id']}).json()
        self.assertEqual([done['added'], done['skipped']], [2, 2])
        self.assertEqual(self.file(host, sid, 'Website/plain/etc/cron.d', 'job')['size'], 2)
        not_zip = self.upload(host, sid, 'notes.zip', b'not a zip', folder='Website').json()
        self.assertEqual(host.post('/api/webmaster/unpack', headers=H, json={'space_id': sid, 'file_id': not_zip['id']}).status_code, 422)

    def test_a_published_site_answers_at_the_grove_address_with_clean_urls(self):
        host, member, sid = self.host_and_member()
        self.bring_in(host, sid)
        release = self.publish(host, sid)
        self.assertEqual([release['folder'], release['files'], release['live'], release['hidden']], ['Website/roguefest-site', len(SITE), True, ['_headers']])
        visitor = self.enterContext(test_hub.TestClient(test_hub.app))
        home = visitor.get('/')
        self.assertEqual([home.status_code, home.content], [200, SITE['index.html']])
        self.assertEqual(home.headers['content-type'], 'text/html; charset=utf-8')
        # Its scripts run, but as a page from nowhere: no member's session goes with them.
        self.assertEqual(home.headers['content-security-policy'], website.POLICY)
        self.assertNotIn('allow-same-origin', website.POLICY)
        self.assertEqual([home.headers['x-frame-options'], home.headers['cache-control']], ['SAMEORIGIN', 'no-cache'])
        self.assertEqual(visitor.get('/filmmakers').content, SITE['filmmakers.html'])
        self.assertEqual(visitor.get('/docs/').content, SITE['docs/index.html'])
        self.assertEqual(visitor.get('/img/badge-320.webp').headers['content-type'], 'image/webp')
        for path, moved in (('/filmmakers.html', '/filmmakers'), ('/index.html', '/'), ('/docs/index.html', '/docs/'), ('/docs', '/docs/'), ('/filmmakers.html?ref=x', '/filmmakers?ref=x')):
            r = visitor.get(path, follow_redirects=False)
            self.assertEqual([r.status_code, r.headers['location']], [308, moved], path)
        missing = visitor.get('/nowhere')
        self.assertEqual([missing.status_code, missing.content], [404, SITE['404.html']])
        self.assertEqual(visitor.get('/_headers').status_code, 404)
        # The Grove keeps its own addresses.
        self.assertEqual(visitor.get('/api/health').json()['name'], 'Arynwood Grove')
        self.assertEqual(visitor.get('/api/auth/me').status_code, 401)
        # Unchanged pages are not sent again.
        again = visitor.get('/', headers={'If-None-Match': home.headers['etag']})
        self.assertEqual([again.status_code, again.content], [304, b''])

    def test_editing_changes_nothing_live_until_published_and_releases_can_be_put_back(self):
        host, member, sid = self.host_and_member()
        self.bring_in(host, sid)
        first = self.publish(host, sid)
        page = self.file(host, sid, 'Website/roguefest-site', 'filmmakers.html')
        saved = host.put(f"/api/community/spaces/{sid}/files/{page['id']}/text", headers=H, json={'text': '<h1>New</h1>', 'version': 1})
        self.assertEqual(saved.status_code, 200, saved.text)
        visitor = self.enterContext(test_hub.TestClient(test_hub.app))
        self.assertEqual(visitor.get('/filmmakers').content, SITE['filmmakers.html'])
        second = self.publish(host, sid)
        self.assertEqual(visitor.get('/filmmakers').text, '<h1>New</h1>')
        state = host.get('/api/webmaster/site').json()
        self.assertEqual([state['live']['id'], [r['id'] for r in state['releases']]], [second['id'], [second['id'], first['id']]])
        back = host.post(f"/api/webmaster/releases/{first['id']}/live", headers=H)
        self.assertEqual([back.status_code, back.json()['live']], [200, True])
        self.assertEqual(visitor.get('/filmmakers').content, SITE['filmmakers.html'])
        self.assertEqual(host.delete('/api/webmaster/live', headers=H).status_code, 200)
        self.assertNotEqual(visitor.get('/filmmakers').content, SITE['filmmakers.html'])
        self.assertIsNone(host.get('/api/webmaster/site').json()['live'])
        self.assertEqual(host.delete('/api/webmaster/live', headers=H).status_code, 409)
        actions = [a['action'] for a in host.get('/api/admin/activity', params={'limit': 4}).json()['items']]
        self.assertEqual(actions, ['site_taken_down', 'site_put_back', 'site_published', 'file_edited'])

    def test_only_a_folder_with_a_front_page_publishes(self):
        host, member, sid = self.host_and_member()
        self.bring_in(host, sid, {'about.html': b'about'})
        for folder, status in (('Website/roguefest-site', 422), ('Website/missing', 404), ('Website', 404), ('Elsewhere', 404)):
            r = host.post('/api/webmaster/publish', headers=H, json={'space_id': sid, 'folder': folder})
            self.assertEqual(r.status_code, status, folder)
        self.assertEqual(host.get('/api/webmaster/site').json()['sites'], [])

    def test_older_releases_go_and_live_pages_outlast_their_files(self):
        host, member, sid = self.host_and_member()
        self.bring_in(host, sid)
        releases = [self.publish(host, sid)['id'] for _ in range(website.KEEP + 2)]
        kept = [r['id'] for r in host.get('/api/webmaster/site').json()['releases']]
        self.assertEqual(kept, releases[::-1][:website.KEEP + 1])
        # The folder goes for good; the published site keeps its pages through the daily sweep.
        folder = self.file(host, sid, 'Website', 'roguefest-site')
        host.delete(f"/api/community/spaces/{sid}/files/{folder['id']}", headers=H).raise_for_status()
        host.delete(f"/api/community/spaces/{sid}/trash/{folder['id']}", headers=H).raise_for_status()
        moment = time.time()
        files.sweep(lambda: moment)
        files.sweep(lambda: moment + files.BLOB_GRACE + 60)
        visitor = self.enterContext(test_hub.TestClient(test_hub.app))
        self.assertEqual(visitor.get('/filmmakers').content, SITE['filmmakers.html'])

    def test_owners_choose_webmasters_and_everyone_previews(self):
        host, member, sid = self.host_and_member()
        self.bring_in(host, sid)
        me = member.get('/api/auth/me').json()
        self.assertFalse(me['webmaster'])
        self.assertTrue(host.get('/api/auth/me').json()['webmaster'])
        body = {'space_id': sid, 'folder': 'Website/roguefest-site'}
        # A member sees what's live and previews, but brings nothing in and publishes nothing.
        state = member.get('/api/webmaster/site').json()
        self.assertEqual([[s['folder'], s['member'], s['files']] for s in state['sites']], [['Website/roguefest-site', True, len(SITE)]])
        self.assertEqual(state['releases'], [])
        self.assertEqual(member.post('/api/webmaster/previews', headers=H, json=body).status_code, 200)
        for method, path, payload in (('post', '/api/webmaster/publish', body), ('post', '/api/webmaster/starter', {'space_id': sid}),
                                      ('post', '/api/webmaster/imports', {'url': 'https://example.com', 'space_id': sid}), ('get', '/api/webmaster/imports', None),
                                      ('delete', '/api/webmaster/live', None)):
            r = getattr(member, method)(path, headers=H, **({'json': payload} if payload else {}))
            self.assertEqual(r.status_code, 403, path)
        # A manager is no webmaster until an owner says so.
        people = {p['name']: p for p in host.get('/api/admin/people').json()}
        uid = people['Member Person']['id']
        host.put(f'/api/admin/people/{uid}/role', headers=H, json={'role': 'manager'}).raise_for_status()
        self.assertEqual(member.post('/api/webmaster/publish', headers=H, json=body).status_code, 403)
        self.assertEqual(member.put(f'/api/admin/people/{uid}/webmaster', headers=H, json={'webmaster': True}).status_code, 403)
        r = host.put(f'/api/admin/people/{uid}/webmaster', headers=H, json={'webmaster': True})
        self.assertEqual(r.json(), {'id': uid, 'webmaster': True})
        self.assertTrue(member.get('/api/auth/me').json()['webmaster'])
        self.assertTrue({p['name']: p for p in host.get('/api/admin/people').json()}['Member Person']['webmaster'])
        self.assertEqual(member.post('/api/webmaster/publish', headers=H, json=body).status_code, 201)
        host.put(f'/api/admin/people/{uid}/webmaster', headers=H, json={'webmaster': False}).raise_for_status()
        self.assertEqual(member.delete('/api/webmaster/live', headers=H).status_code, 403)
        self.assertEqual(host.put('/api/admin/people/nobody/webmaster', headers=H, json={'webmaster': True}).status_code, 404)
        log = [(a['action'], a['details']) for a in host.get('/api/admin/activity', params={'limit': 3}).json()['items']]
        self.assertEqual(log[0], ('webmaster_changed', {'webmaster': False}))

    def test_members_of_other_spaces_preview_but_never_see_other_folders(self):
        host, member, sid = self.host_and_member()
        self.bring_in(host, sid)
        host.post(f'/api/community/spaces/{sid}/folders', headers=H, json={'name': 'Board'}).raise_for_status()
        self.upload(host, sid, 'minutes.txt', b'private', folder='Board')
        # Someone in the Grove, but only in another space.
        theirs = host.post('/api/community/spaces', headers=H, json={'name': 'Volunteers'}).json()['id']
        stranger = self.enterContext(test_hub.TestClient(test_hub.app))
        self.signup(stranger, 'stranger@example.test', 'Stranger', self.invite(host, theirs))
        self.assertEqual([s['id'] for s in stranger.get('/api/community/spaces').json()], [theirs])
        for path in ('Website', 'Board', 'Website/roguefest-site/../../Board'):
            self.assertIn(stranger.post('/api/webmaster/previews', headers=H, json={'space_id': sid, 'folder': path}).status_code, (404, 422), path)
        self.assertEqual(stranger.post('/api/webmaster/previews', headers=H, json={'space_id': theirs, 'folder': 'Website/roguefest-site'}).status_code, 404)
        url = stranger.post('/api/webmaster/previews', headers=H, json={'space_id': sid, 'folder': 'Website/roguefest-site'}).json()['url']
        self.assertEqual(stranger.get(url + 'filmmakers').content, SITE['filmmakers.html'])

    def test_previews_keep_a_sites_own_addresses_inside_the_preview(self):
        host, member, sid = self.host_and_member()
        self.bring_in(host, sid)
        url = member.post('/api/webmaster/previews', headers=H, json={'space_id': sid, 'folder': 'Website/roguefest-site'}).json()['url']
        base = url.rstrip('/')
        page = member.get(url)
        policy = page.headers['content-security-policy']
        self.assertEqual(policy, editor.preview_csp('http://testserver' + url))
        self.assertIn('allow-scripts', policy)
        self.assertNotIn('allow-same-origin', policy)
        for expected in (f'href="{base}/styles.css?v=1"', f'href="{base}/filmmakers"', 'href="/community"', f'src="{base}/site.js"',
                         f'srcset="{base}/img/badge-320.webp 320w, {base}/img/badge-640.webp 640w"'):
            self.assertIn(expected, page.text)
        self.assertEqual(member.get(url + 'styles.css').text, f'body{{background:url("{base}/img/burst.svg")}}')
        self.assertEqual(member.get(url + 'site.js').content, SITE['site.js'])
        missing = member.get(url + 'nowhere')
        self.assertEqual([missing.status_code, missing.text], [404, '<h1>Not here</h1>'])

    def test_website_files_are_for_owners_and_webmasters_to_change(self):
        host, member, sid = self.host_and_member()
        self.bring_in(host, sid)
        page = self.file(host, sid, 'Website/roguefest-site', 'index.html')
        site_folder = self.file(host, sid, 'Website', 'roguefest-site')
        root = f'/api/community/spaces/{sid}'
        refused = [
            self.upload(member, sid, 'new.html', b'x', folder='Website/roguefest-site'),
            self.upload(member, sid, 'index.html', b'x', replaces=page['id']),
            member.post(f'{root}/folders', headers=H, json={'folder': 'Website', 'name': 'mine'}),
            member.put(f"{root}/files/{page['id']}/text", headers=H, json={'text': 'x', 'version': 1}),
            member.put(f"{root}/files/{page['id']}", headers=H, json={'folder': '', 'name': 'index.html'}),
            member.delete(f"{root}/files/{site_folder['id']}", headers=H),
        ]
        for r in refused: self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(refused[0].json()['detail'], 'Only this Grove’s owners and webmasters change website files.')
        # Their own files stay theirs, but can't be moved into the website.
        notes = self.upload(member, sid, 'notes.txt', b'mine').json()
        self.assertEqual(member.put(f"{root}/files/{notes['id']}", headers=H, json={'folder': 'Website', 'name': 'notes.txt'}).status_code, 403)
        self.assertEqual(member.put(f"{root}/files/{notes['id']}", headers=H, json={'folder': '', 'name': 'notes2.txt'}).status_code, 200)
        # A webmaster looks after all of it, whoever added it.
        uid = {p['name']: p['id'] for p in host.get('/api/admin/people').json()}['Member Person']
        host.put(f'/api/admin/people/{uid}/webmaster', headers=H, json={'webmaster': True}).raise_for_status()
        self.assertEqual(member.put(f"{root}/files/{page['id']}/text", headers=H, json={'text': 'x', 'version': 1}).status_code, 200)
        self.assertEqual(member.delete(f"{root}/files/{site_folder['id']}", headers=H).status_code, 200)
        self.assertEqual(member.post(f"{root}/files/{site_folder['id']}/restore", headers=H).status_code, 200)

    def test_a_starter_page_comes_from_the_groves_branding(self):
        host, member, sid = self.host_and_member()
        with patch.dict('os.environ', {'GROVE_BRAND_NAME': 'RogueFest <Community>', 'GROVE_BRAND_TAGLINE': 'Come see what you find.',
                                       'GROVE_BRAND_SURFACE': '#091C32', 'GROVE_BRAND_ACCENT': '#E2326F',
                                       'GROVE_PUBLIC_URL': 'https://roguefest.arynwood.com'}):
            r = host.post('/api/webmaster/starter', headers=H, json={'space_id': sid})
            self.assertEqual((r.status_code, r.json()), (201, {'space_id': sid, 'folder': 'Website/roguefest.arynwood.com', 'existed': False}))
            # Asked again, it says where the one-page site already is, and leaves it be.
            again = host.post('/api/webmaster/starter', headers=H, json={'space_id': sid})
            self.assertEqual((again.status_code, again.json()), (200, {'space_id': sid, 'folder': 'Website/roguefest.arynwood.com', 'existed': True}))
        page = self.file(host, sid, 'Website/roguefest.arynwood.com', 'index.html')
        text = host.get(f"/api/community/spaces/{sid}/files/{page['id']}/content").text
        self.assertIn('<h1>RogueFest &lt;Community&gt;</h1>', text)
        self.assertIn('Come see what you find.', text)
        self.assertIn('--bg: #091c32', text.lower())
        self.assertIn('href="/community"', text)
        self.publish(host, sid, 'Website/roguefest.arynwood.com')
        self.assertIn(b'Members: sign in', self.enterContext(test_hub.TestClient(test_hub.app)).get('/').content)


if __name__ == '__main__':
    unittest.main()
