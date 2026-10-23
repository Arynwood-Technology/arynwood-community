"""Text edits are versioned, and preview capabilities stay inside one folder."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import time
import unittest
from unittest.mock import patch
import test_hub
import test_files
from fastapi.testclient import TestClient
from backend.api import app
from backend.community import editor, files, live, store

H = test_hub.H

class EditorTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member
    upload = test_files.FileTests.upload

    def host(self):
        client = self.enterContext(TestClient(app))
        self.signup(client)
        return client, client.get('/api/community/spaces').json()[0]['id']

    def save(self, client, sid, fid, text='new text', version=1):
        return client.put(f'/api/community/spaces/{sid}/files/{fid}/text', headers=H, json={'text': text, 'version': version})

    def test_any_member_saves_a_new_version_and_keeps_the_previous_one(self):
        host, member, sid = self.host_and_member()
        original = self.upload(host, sid, 'index.html', b'<h1>Before</h1>').json()
        with patch.object(live, 'publish') as publish:
            result = self.save(member, sid, original['id'], '<h1>After</h1>')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['version'], 2)
        publish.assert_called_once_with(sid)
        root = f"/api/community/spaces/{sid}/files/{original['id']}"
        self.assertEqual(host.get(root+'/content', params={'inline':1}).text, '<h1>After</h1>')
        self.assertEqual(host.get(root+'/content', params={'inline':1,'version':1}).text, '<h1>Before</h1>')
        self.assertEqual([v['version'] for v in host.get(root+'/versions').json()], [2,1])
        activity = next(a for a in host.get('/api/admin/activity').json()['items'] if a['action']=='file_edited')
        self.assertEqual(activity['actor_id'], member.get('/api/auth/me').json()['id'])
        self.assertEqual(activity['details'], {'version':2})
        with store.db() as c: self.assertEqual(files.used(c, sid), len(b'<h1>Before</h1>')+len(b'<h1>After</h1>'))

    def test_stale_save_never_overwrites(self):
        host, sid = self.host()
        f = self.upload(host, sid, 'style.css', b'body{}').json()
        self.assertEqual(self.save(host, sid, f['id'], 'body{color:red}').status_code, 200)
        stale = self.save(host, sid, f['id'], 'body{color:blue}')
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['detail'], editor.STALE)
        self.assertEqual(host.get(f"/api/community/spaces/{sid}/files/{f['id']}/content?inline=1").text, 'body{color:red}')

    def test_two_simultaneous_saves_keep_only_one_new_version(self):
        host, sid = self.host()
        f = self.upload(host, sid, 'notes.txt', b'original').json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda text: self.save(host, sid, f['id'], text).status_code, ('First', 'Second')))
        self.assertEqual(sorted(results), [200, 409])
        versions = host.get(f"/api/community/spaces/{sid}/files/{f['id']}/versions").json()
        self.assertEqual([v['version'] for v in versions], [2, 1])

    def test_nonmembers_and_deleted_files_are_not_available(self):
        host, member, sid = self.host_and_member()
        other = host.post('/api/community/spaces', headers=H, json={'name':'Other'}).json()['id']
        f = self.upload(host, other, 'private.txt', b'private').json()
        self.assertEqual(self.save(member, other, f['id']).status_code, 404)
        self.assertEqual(member.post(f'/api/community/spaces/{other}/previews', headers=H, json={'folder':''}).status_code, 404)
        host.delete(f"/api/community/spaces/{other}/files/{f['id']}", headers=H)
        self.assertEqual(self.save(host, other, f['id']).status_code, 404)

    def test_nontext_binary_and_oversized_files_are_refused(self):
        host, sid = self.host()
        for name, data in [('photo.png', b'png'), ('binary.txt', b'\x00binary'), ('latin.txt', b'\xff')]:
            f = self.upload(host, sid, name, data).json()
            self.assertEqual(self.save(host, sid, f['id']).status_code, 415)
        f = self.upload(host, sid, 'large.txt', b'x'*(editor.TEXT_MAX+1), piece=4*files.MB).json()
        self.assertEqual(self.save(host, sid, f['id']).status_code, 413)
        f = self.upload(host, sid, 'small.txt', b'old').json()
        self.assertEqual(self.save(host, sid, f['id'], 'é'*(editor.TEXT_MAX//2+1)).status_code, 413)
        self.assertEqual(self.save(host, sid, f['id'], 'x'*(editor.TEXT_MAX+1)).status_code, 422)
        self.assertEqual(self.save(host, sid, f['id'], '\x00new').status_code, 415)
        self.assertEqual(self.save(host, sid, f['id'], '', version=0).status_code, 422)
        self.assertEqual(self.save(host, sid, f['id'], 'x'*editor.TEXT_MAX).status_code, 200)

    def test_quota_counts_saved_versions_and_pending_uploads(self):
        host, sid = self.host()
        f = self.upload(host, sid, 'notes.md', b'original').json()
        with patch.object(files, 'space_limit', return_value=10):
            self.assertEqual(self.save(host, sid, f['id'], '123').status_code, 413)
            self.assertEqual(self.save(host, sid, f['id'], '12').status_code, 200)
            self.assertEqual(self.save(host, sid, f['id'], '1', version=2).status_code, 413)
        with store.db() as c: self.assertEqual(files.used(c, sid), 10)
        with patch.object(files, 'space_limit', return_value=12):
            pending = host.post(f'/api/community/spaces/{sid}/uploads', headers=H, json={'name':'waiting.txt','size':2})
            self.assertEqual(pending.status_code, 201)
            self.assertEqual(self.save(host, sid, f['id'], '1', version=2).status_code, 413)

    def test_drafts_count_against_the_space(self):
        # A one-byte file could hold a 2 MB draft that the space never counted.
        host, member, sid = self.host_and_member()
        f = self.upload(member, sid, 'a.txt', b'1').json()
        draft = lambda client, text: client.put(f"/api/community/spaces/{sid}/files/{f['id']}/draft", headers=H, json={'text': text, 'version': 1})
        with patch.object(files, 'space_limit', return_value=10):
            full = draft(member, 'x' * 10)
            self.assertEqual(full.status_code, 413)
            self.assertEqual(full.json()['detail'], editor.FULL)
            self.assertEqual(draft(member, 'x' * 6).status_code, 200)
            with store.db() as c: self.assertEqual(files.used(c, sid), 7)
            # Each person's draft is room of its own; one that shrinks is kept even in a full space.
            self.assertEqual(draft(host, 'x' * 4).status_code, 413)
            self.assertEqual(draft(host, 'x' * 3).status_code, 200)
            self.assertEqual(draft(member, 'x' * 7).status_code, 413)
            self.assertEqual(draft(member, 'x' * 2).status_code, 200)
            # Saving ends the saver's draft, so its room counts toward the save.
            self.assertEqual(self.save(member, sid, f['id'], 'x' * 5).status_code, 200)
            with store.db() as c: self.assertEqual(files.used(c, sid), 1 + 5 + 3)
        with patch.object(files, 'MIN_FREE', 10 ** 18):
            self.assertEqual(draft(host, 'x' * 4).status_code, 507)
            self.assertEqual(draft(host, 'x').status_code, 200)

    def website(self):
        host, sid = self.host()
        for name in ('Site','Other'):
            host.post(f'/api/community/spaces/{sid}/folders', headers=H, json={'name':name}).raise_for_status()
        host.post(f'/api/community/spaces/{sid}/folders', headers=H, json={'folder':'Site','name':'pages'}).raise_for_status()
        fixtures = [('Site','index.html',b'<h1>Home</h1>'), ('Site','about.html',b'<h1>About</h1>'),
                    ('Site','style.css',b'body{color:red}'), ('Site/pages','index.html',b'<h1>Pages</h1>'),
                    ('Other','secret.txt',b'not in the site')]
        for folder,name,data in fixtures: self.upload(host, sid, name, data, folder=folder)
        url = host.post(f'/api/community/spaces/{sid}/previews', headers=H, json={'folder':'Site'}).json()['url']
        return host, sid, url

    def test_preview_needs_no_cookie_and_has_exact_policies(self):
        host, sid, url = self.website()
        client = self.enterContext(TestClient(app))
        expected = {'':'<h1>Home</h1>', 'index.html':'<h1>Home</h1>', 'about':'<h1>About</h1>', 'pages/':'<h1>Pages</h1>', 'pages':'<h1>Pages</h1>', 'style.css':'body{color:red}'}
        for path, text in expected.items():
            response = client.get(url+path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.text, text)
            self.assertEqual(response.headers['content-security-policy'], editor.preview_csp('http://testserver' + url))
            self.assertEqual(response.headers['x-frame-options'], 'SAMEORIGIN')
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(client.get(url+'style.css').headers['content-type'], 'text/css; charset=utf-8')
        # The page's files are named by the preview's own address: WebKit matches 'self' in a sandboxed frame to nothing.
        policy = client.get(url).headers['content-security-policy']
        self.assertIn(f"style-src http://testserver{url} 'unsafe-inline'", policy)
        self.assertNotIn("'self'", policy.split('frame-ancestors')[0])
        self.assertEqual(client.get('/api/health').headers['x-frame-options'], 'DENY')
        self.assertIn("script-src 'self'", client.get('/api/health').headers['content-security-policy'])
        self.assertEqual(client.get('/api/auth/me').status_code, 401)

    def test_preview_refuses_expired_forged_and_other_folder_tokens(self):
        host, sid, url = self.website()
        token = url.split('/')[-2]
        payload, signature = token.split('.')
        details = json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
        self.assertAlmostEqual(details[2]-time.time(), editor.PREVIEW_SECONDS, delta=3)
        with patch.object(editor.time, 'time', return_value=details[2]+1):
            self.assertEqual(host.get(url).status_code, 404)
        details[1] = 'Other'
        forged = base64.urlsafe_b64encode(json.dumps(details).encode()).decode().rstrip('=')+'.'+signature
        for bad in (forged, payload+'.'+'0'*64, 'not-a-token'):
            self.assertEqual(host.get('/api/community/preview/'+bad+'/secret.txt').status_code, 404)
        for path in ('Other/secret.txt','../Other/secret.txt','%2e%2e/Other/secret.txt','pages/%2e%2e/%2e%2e/Other/secret.txt','%2fOther/secret.txt','pages%5c..%5cOther/secret.txt'):
            self.assertEqual(host.get(url+path).status_code, 404, path)
        self.assertEqual(host.post(f'/api/community/spaces/{sid}/previews', headers=H, json={'folder':'missing'}).status_code,404)
        self.assertEqual(host.post(f'/api/community/spaces/{sid}/previews', headers=H, json={'folder':'../Other'}).status_code,422)
