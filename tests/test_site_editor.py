"""The site editor and its notes: a webmaster's preview shows their drafts as they type, and anyone
in the Grove leaves notes on a preview that webmasters answer and close."""
import unittest
from unittest.mock import patch
import test_hub
import test_website
from backend.community import live

H = test_hub.H
SITE = {**test_website.SITE, 'index.html': b'<!doctype html><html lang="en"><head><title>Home</title></head><body><h1>RogueFest</h1></body></html>',
        'about.html': b'<p>About us</p>'}
FOLDER = 'Website/roguefest-site'


class SiteEditorTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member
    upload = test_website.WebsiteTests.upload
    bring_in = test_website.WebsiteTests.bring_in
    file = test_website.WebsiteTests.file

    def site(self):
        host, member, sid = self.host_and_member()
        self.bring_in(host, sid, SITE)
        return host, member, sid

    def preview(self, client, sid, **options):
        r = client.post('/api/webmaster/previews', headers=H, json={'space_id': sid, 'folder': FOLDER, **options})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['url']

    def test_a_webmasters_preview_shows_their_drafts_until_they_save(self):
        host, member, sid = self.site()
        page, style = self.file(host, sid, FOLDER, 'about.html'), self.file(host, sid, FOLDER, 'styles.css')
        root = f'/api/community/spaces/{sid}/files'
        self.assertEqual(host.get(f"{root}/{page['id']}/draft").status_code, 404)
        for f, text in ((page, '<p>About us, drafted</p>'), (style, 'body{color:red}')):
            r = host.put(f"{root}/{f['id']}/draft", headers=H, json={'text': text, 'version': 1})
            self.assertEqual(r.status_code, 200, r.text)
        drafts, plain = self.preview(host, sid, drafts=True), self.preview(host, sid)
        self.assertIn('About us, drafted', host.get(drafts + 'about').text)
        self.assertEqual(host.get(drafts + 'styles.css').text, 'body{color:red}')
        self.assertEqual(host.get(plain + 'about').text, '<p>About us</p>')
        # Only theirs: everyone else previews the saved site, and a member can't ask for drafts.
        self.assertEqual(member.get(self.preview(member, sid) + 'about').text, '<p>About us</p>')
        self.assertEqual(member.post('/api/webmaster/previews', headers=H, json={'space_id': sid, 'folder': FOLDER, 'drafts': True}).status_code, 403)
        self.assertEqual(member.put(f"{root}/{page['id']}/draft", headers=H, json={'text': 'x', 'version': 1}).status_code, 403)
        listed = {i['name']: i['draft'] for i in host.get('/api/webmaster/files', params={'space_id': sid, 'folder': FOLDER}).json()['items']}
        self.assertEqual(listed['about.html']['version'], 1)
        self.assertIsNone(listed['index.html'])
        self.assertEqual(member.get('/api/webmaster/files', params={'space_id': sid, 'folder': FOLDER}).status_code, 403)
        self.assertEqual(host.get(f"{root}/{page['id']}/draft").json()['text'], '<p>About us, drafted</p>')
        # Saving ends the draft; discarding one puts the saved file back in the preview.
        with patch.object(live, 'publish', wraps=live.publish) as told:
            self.assertEqual(host.put(f"{root}/{page['id']}/text", headers=H, json={'text': '<p>About us, saved</p>', 'version': 1}).status_code, 200)
        self.assertIn(((live.WEBSITE,), {}), told.call_args_list)
        self.assertEqual(host.get(f"{root}/{page['id']}/draft").status_code, 404)
        self.assertEqual(host.get(plain + 'about').text, '<p>About us, saved</p>')
        host.delete(f"{root}/{style['id']}/draft", headers=H).raise_for_status()
        self.assertEqual(host.get(drafts + 'styles.css').text, 'body{background:url("%simg/burst.svg")}' % drafts)

    def test_the_grove_preview_pane_gets_its_bridge_and_a_new_tab_does_not(self):
        host, member, sid = self.site()
        bridged, plain = self.preview(member, sid, bridge=True), self.preview(member, sid)
        page = member.get(bridged).text
        self.assertTrue(page.startswith('<!doctype html><html lang="en"><head><script>(() => {'), page[:120])
        self.assertIn('const base = "%s"' % bridged.rstrip('/'), page)
        self.assertIn('</script><title>Home</title>', page)
        # A page with no <head> gets it first; styles and scripts never do.
        self.assertTrue(member.get(bridged + 'about').text.startswith('<script>'))
        self.assertNotIn('<script>', member.get(bridged + 'styles.css').text)
        self.assertNotIn('grove-preview-layer', member.get(plain).text)

    def test_anyone_leaves_notes_and_webmasters_close_them(self):
        host, member, sid = self.site()
        where = {'space_id': sid, 'folder': FOLDER}
        self.assertEqual(member.post('/api/webmaster/notes', headers=H, json={**where, 'page': '/about'}).status_code, 422)
        self.assertEqual(member.post('/api/webmaster/notes', headers=H, json={**where, 'page': 'about', 'body': 'x'}).status_code, 422)
        with patch.object(live, 'publish') as told:
            r = member.post('/api/webmaster/notes', headers=H, json={**where, 'page': '/about', 'selector': 'p:nth-of-type(1)', 'quote': 'About us',
                                                                    'x': 0.5, 'y': 0.25, 'device': 'phone', 'suggestion': 'About RogueFest'})
        self.assertEqual(r.status_code, 201, r.text)
        told.assert_called_once_with(live.WEBSITE)
        note = r.json()
        self.assertEqual([note[k] for k in ('author', 'quote', 'suggestion', 'body', 'status', 'device')], ['Member Person', 'About us', 'About RogueFest', '', 'open', 'phone'])
        page_note = member.post('/api/webmaster/notes', headers=H, json={**where, 'body': '  The menu covers the title on phones.  '}).json()
        self.assertEqual([page_note['page'], page_note['body'], page_note['suggestion']], ['/', 'The menu covers the title on phones.', None])
        # Someone else in the Grove, in another space, sees the notes and replies.
        theirs = host.post('/api/community/spaces', headers=H, json={'name': 'Volunteers'}).json()['id']
        stranger = self.enterContext(test_hub.TestClient(test_hub.app))
        self.signup(stranger, 'stranger@example.test', 'Stranger', self.invite(host, theirs))
        review = stranger.get('/api/webmaster/review', params=where).json()
        self.assertEqual(review['pages'][:2], ['index.html', '404.html'])
        self.assertIn('docs/index.html', review['pages'])
        self.assertEqual([n['id'] for n in review['notes']], [note['id'], page_note['id']])
        self.assertEqual(stranger.post(f"/api/webmaster/notes/{note['id']}/replies", headers=H, json={'body': 'Yes please'}).status_code, 201)
        self.assertEqual(stranger.put(f"/api/webmaster/notes/{note['id']}", headers=H, json={'status': 'done'}).status_code, 403)
        self.assertEqual(stranger.delete(f"/api/webmaster/notes/{note['id']}", headers=H).status_code, 403)
        self.assertEqual([s['notes'] for s in host.get('/api/webmaster/site').json()['sites']], [2])
        # A webmaster closes it; its author may open it again, or delete their own.
        done = host.put(f"/api/webmaster/notes/{note['id']}", headers=H, json={'status': 'done'}).json()
        self.assertEqual([done['status'], done['closed_by']], ['done', 'Host User'])
        self.assertEqual(member.put(f"/api/webmaster/notes/{note['id']}", headers=H, json={'status': 'open'}).json()['status'], 'open')
        self.assertEqual(member.delete(f"/api/webmaster/notes/{page_note['id']}", headers=H).status_code, 200)
        review = host.get('/api/webmaster/review', params=where).json()
        self.assertEqual([(n['id'], [r['author'] for r in n['replies']]) for n in review['notes']], [(note['id'], ['Stranger'])])
        # The review's mark changes with the site's files, so open previews know to reload.
        about = self.file(host, sid, FOLDER, 'about.html')
        host.put(f"/api/community/spaces/{sid}/files/{about['id']}/text", headers=H, json={'text': '<p>New</p>', 'version': 1}).raise_for_status()
        self.assertNotEqual(host.get('/api/webmaster/review', params=where).json()['changed'], review['changed'])
        log = [(a['action'], a['details']['page']) for a in host.get('/api/admin/activity', params={'limit': 10}).json()['items'] if a['action'].startswith('site_note')]
        self.assertEqual(log, [('site_note_deleted', '/'), ('site_note_reopened', '/about'), ('site_note_done', '/about'), ('site_note_added', '/'), ('site_note_added', '/about')])

    def test_notes_need_a_website(self):
        host, member, sid = self.site()
        for folder in ('Website', 'Website/nothing', 'Board'):
            self.assertIn(member.post('/api/webmaster/notes', headers=H, json={'space_id': sid, 'folder': folder, 'body': 'x'}).status_code, (404, 422), folder)
            self.assertIn(member.get('/api/webmaster/review', params={'space_id': sid, 'folder': folder}).status_code, (404, 422), folder)
        self.assertEqual(member.put('/api/webmaster/notes/nothing', headers=H, json={'status': 'done'}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
