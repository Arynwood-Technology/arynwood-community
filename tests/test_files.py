"""The file bank: uploads in pieces, folders, versions, the trash, and what may be opened in a browser."""
import hashlib
import os
import time
import unittest
from unittest.mock import patch
import test_hub
from backend.community import files, store

H = test_hub.H


class FileTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member

    def upload(self, client, sid, name, data, folder='', piece=5, replaces=None, finish=True):
        root = f'/api/community/spaces/{sid}/uploads'
        started = client.post(root, headers=H, json={'folder': folder, 'name': name, 'size': len(data), 'replaces': replaces})
        if started.status_code != 201: return started
        uid = started.json()['id']
        for offset in range(0, len(data), piece):
            r = client.put(f'{root}/{uid}', headers=H, params={'offset': offset}, content=data[offset:offset + piece])
            self.assertEqual(r.status_code, 200, r.text)
        return client.post(f'{root}/{uid}/finish', headers=H) if finish else uid

    def listing(self, client, sid, **query):
        r = client.get(f'/api/community/spaces/{sid}/files', params=query)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_a_file_arrives_in_pieces_and_is_stored_once(self):
        host, member, sid = self.host_and_member()
        data = b'Opening night: doors at 6, first film at 7.\n' * 3
        saved = self.upload(member, sid, 'Schedule.txt', data)
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual([saved.json()[k] for k in ('name', 'size', 'version', 'author')], ['Schedule.txt', len(data), 1, 'Member Person'])
        listed = self.listing(host, sid)
        self.assertEqual([i['name'] for i in listed['items']], ['Schedule.txt'])
        self.assertEqual(listed['used'], len(data))
        got = host.get(f"/api/community/spaces/{sid}/files/{saved.json()['id']}/content")
        self.assertEqual(got.content, data)
        self.assertTrue(got.headers['content-disposition'].startswith('attachment'))
        # The same contents again take no more room on the disk.
        self.upload(host, sid, 'Copy of schedule.txt', data)
        blobs = list((files.storage() / 'blobs').glob('*/*'))
        self.assertEqual([b.name for b in blobs], [hashlib.sha256(data).hexdigest()])
        actions = [(a['action'], a['target_name']) for a in host.get('/api/admin/activity').json()['items'][:3]]
        self.assertEqual(actions, [('file_uploaded', 'Copy of schedule.txt'), ('file_downloaded', 'Schedule.txt'), ('file_uploaded', 'Schedule.txt')])

    def test_pieces_must_arrive_in_order_and_add_up(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}/uploads'
        uid = self.upload(member, sid, 'Badges.pdf', b'%PDF-1.4 badges', finish=False, piece=100)
        self.assertEqual(member.get(f'{root}/{uid}').json(), {'received': 15, 'size': 15})
        self.assertEqual(member.put(f'{root}/{uid}', headers=H, params={'offset': 3}, content=b'x').status_code, 409)
        self.assertEqual(member.put(f'{root}/{uid}', headers=H, params={'offset': 15}, content=b'extra').status_code, 422)
        # Nobody else can add to, or finish, someone's upload.
        self.assertEqual(host.post(f'{root}/{uid}/finish', headers=H).status_code, 404)
        half = self.upload(member, sid, 'Half.pdf', b'0123456789', finish=False, piece=100)
        self.assertEqual(member.post(f'{root}/{half}/finish', headers=H).status_code, 201)
        fresh = member.post(root, headers=H, json={'name': 'Later.pdf', 'size': 10}).json()['id']
        self.assertEqual(member.post(f'{root}/{fresh}/finish', headers=H).status_code, 409)
        with patch.object(files, 'CHUNK_MAX', 4):
            self.assertEqual(member.put(f'{root}/{fresh}', headers=H, params={'offset': 0}, content=b'01234').status_code, 413)

    def test_limits_for_a_file_and_a_space(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}/uploads'
        with patch.dict(os.environ, {'GROVE_FILE_MAX_MB': '1', 'GROVE_SPACE_STORAGE_MB': '2'}):
            self.assertEqual(member.post(root, headers=H, json={'name': 'Screener.mov', 'size': 2 * files.MB}).status_code, 413)
            self.assertEqual(member.post(root, headers=H, json={'name': 'A.mov', 'size': files.MB}).status_code, 201)
            # An upload under way holds its room.
            self.assertEqual(member.post(root, headers=H, json={'name': 'B.mov', 'size': files.MB}).status_code, 201)
            full = member.post(root, headers=H, json={'name': 'C.mov', 'size': 1})
            self.assertEqual(full.status_code, 413)
            self.assertIn('room', full.json()['detail'])
        for name in ('../escape.txt', 'a/b.txt', 'tab\there.txt', '..', ' '):
            self.assertEqual(member.post(root, headers=H, json={'name': name, 'size': 1}).status_code, 422, name)
        self.assertEqual(member.post(root, headers=H, json={'name': 'x.txt', 'folder': 'Nowhere', 'size': 1}).status_code, 404)

    def test_folders_hold_files_and_move_with_them(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}'
        site = member.post(root + '/folders', headers=H, json={'name': 'Website'}).json()
        member.post(root + '/folders', headers=H, json={'folder': 'Website', 'name': 'assets'})
        self.assertEqual(member.post(root + '/folders', headers=H, json={'name': 'Website'}).status_code, 409)
        logo = self.upload(member, sid, 'logo.png', b'\x89PNG fake', folder='Website/assets').json()
        self.assertEqual([i['name'] for i in self.listing(member, sid, folder='Website')['items']], ['assets'])
        renamed = member.put(f"{root}/files/{site['id']}", headers=H, json={'folder': '', 'name': 'Site'})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual([i['id'] for i in self.listing(member, sid, folder='Site/assets')['items']], [logo['id']])
        self.assertEqual(member.get(f'{root}/files', params={'folder': 'Website'}).status_code, 404)
        self.assertEqual(member.put(f"{root}/files/{site['id']}", headers=H, json={'folder': 'Site/assets', 'name': 'Site'}).status_code, 422)
        moved = member.put(f"{root}/files/{logo['id']}", headers=H, json={'folder': 'Site', 'name': 'logo.png'})
        self.assertEqual(moved.json()['folder'], 'Site')
        log = [(a['action'], a['target_name'], a['details'].get('from')) for a in host.get('/api/admin/activity').json()['items'][:2]]
        self.assertEqual(log, [('file_moved', 'Site/logo.png', 'Site/assets/logo.png'), ('file_renamed', 'Site', 'Website')])

    def test_new_versions_keep_the_old_ones(self):
        host, member, sid = self.host_and_member()
        first = self.upload(member, sid, 'Program.txt', b'Draft one').json()
        second = self.upload(host, sid, 'ignored', b'Draft two, final', replaces=first['id'])
        self.assertEqual([second.json()[k] for k in ('id', 'name', 'version', 'updated_by')], [first['id'], 'Program.txt', 2, 'Host User'])
        root = f"/api/community/spaces/{sid}/files/{first['id']}"
        self.assertEqual([(v['version'], v['author']) for v in host.get(root + '/versions').json()], [(2, 'Host User'), (1, 'Member Person')])
        self.assertEqual(host.get(root + '/content').content, b'Draft two, final')
        self.assertEqual(host.get(root + '/content', params={'version': 1}).content, b'Draft one')
        self.assertEqual(host.get(root + '/content', params={'version': 7}).status_code, 404)
        self.assertEqual(self.listing(host, sid)['used'], len(b'Draft one') + len(b'Draft two, final'))
        # Uploading over a name without asking for a new version is refused.
        self.assertEqual(self.upload(member, sid, 'Program.txt', b'x').status_code, 409)

    def test_only_safe_things_open_in_the_browser(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}/files'
        page = self.upload(member, sid, 'index.html', b'<script>alert(1)</script>').json()
        photo = self.upload(member, sid, 'still.png', b'\x89PNG\r\n').json()
        pdf = self.upload(member, sid, 'press.pdf', b'%PDF-1.7').json()
        tool = self.upload(member, sid, 'tool.exe', b'MZ').json()
        shown = host.get(f"{root}/{page['id']}/content", params={'inline': 1})
        self.assertEqual([shown.headers['content-type'], shown.headers['content-security-policy']], ['text/plain; charset=utf-8', 'sandbox'])
        self.assertTrue(shown.headers['content-disposition'].startswith('inline'))
        self.assertEqual(shown.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(host.get(f"{root}/{photo['id']}/content", params={'inline': 1}).headers['content-type'], 'image/png')
        self.assertNotEqual(host.get(f"{root}/{pdf['id']}/content", params={'inline': 1}).headers['content-security-policy'], 'sandbox')
        download = host.get(f"{root}/{tool['id']}/content", params={'inline': 1})
        self.assertEqual([download.headers['content-disposition'][:10], download.headers['content-security-policy']], ['attachment', 'sandbox'])
        # Looking at a file is not logged as a download.
        self.assertNotIn('file_downloaded', [a['action'] for a in host.get('/api/admin/activity').json()['items']])

    def test_the_trash_keeps_things_for_their_owners(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}'
        folder = member.post(root + '/folders', headers=H, json={'name': 'Press'}).json()
        kit = self.upload(member, sid, 'kit.txt', b'Press kit', folder='Press').json()
        theirs = self.upload(host, sid, 'host.txt', b'Host notes', folder='Press').json()
        # Others' things inside: only a space owner can bin the folder.
        self.assertEqual(member.delete(f"{root}/files/{folder['id']}", headers=H).status_code, 403)
        self.assertEqual(member.delete(f"{root}/files/{theirs['id']}", headers=H).status_code, 403)
        self.assertEqual(host.delete(f"{root}/files/{folder['id']}", headers=H).status_code, 200)
        self.assertEqual([i['name'] for i in self.listing(member, sid)['items']], [])
        self.assertEqual([i['name'] for i in self.listing(member, sid, trash=1)['items']], ['Press'])
        # Something new in its place blocks the restore until it is renamed.
        blocker = member.post(root + '/folders', headers=H, json={'name': 'Press'}).json()
        self.assertEqual(host.post(f"{root}/files/{folder['id']}/restore", headers=H).status_code, 409)
        member.put(f"{root}/files/{blocker['id']}", headers=H, json={'name': 'Press 2027'})
        self.assertEqual(host.post(f"{root}/files/{folder['id']}/restore", headers=H).status_code, 200)
        self.assertEqual({i['id'] for i in self.listing(member, sid, folder='Press')['items']}, {kit['id'], theirs['id']})
        member.delete(f"{root}/files/{kit['id']}", headers=H)
        self.assertEqual(member.delete(f"{root}/trash/{kit['id']}", headers=H).status_code, 403)
        self.assertEqual(host.delete(f"{root}/trash/{kit['id']}", headers=H).status_code, 200)
        self.assertEqual(self.listing(host, sid, trash=1)['items'], [])
        self.assertEqual(self.listing(host, sid)['used'], len(b'Host notes'))

    def test_only_members_see_a_spaces_files(self):
        host, member, sid = self.host_and_member()
        saved = self.upload(host, sid, 'Budget.csv', b'line,amount').json()
        other = host.post('/api/community/spaces', headers=H, json={'name': 'Board'}).json()
        self.upload(host, other['id'], 'Minutes.txt', b'Minutes')
        self.assertEqual(member.get(f"/api/community/spaces/{other['id']}/files").status_code, 404)
        self.assertEqual(member.get(f"/api/community/spaces/{other['id']}/files/{saved['id']}/content").status_code, 404)
        spaces = {s['name']: s['used'] for s in host.get('/api/admin/spaces').json()}
        self.assertEqual(spaces, {'Board': 7, 'Our home': 11})

    def test_the_daily_sweep_empties_old_trash_and_unused_contents(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}'
        old = self.upload(member, sid, 'Old.txt', b'Last year').json()
        kept = self.upload(member, sid, 'Kept.txt', b'This year').json()
        stalled = self.upload(member, sid, 'Stalled.txt', b'0123456789', finish=False, piece=4)
        member.delete(f"{root}/files/{old['id']}", headers=H)
        later = time.time() + 31 * 86400
        files.sweep(lambda: later)
        self.assertEqual(self.listing(member, sid, trash=1)['items'], [])
        self.assertEqual(member.get(f'{root}/uploads/{stalled}').status_code, 404)
        self.assertEqual(list((files.storage() / 'uploads').glob('*')), [])
        # Unused contents wait until no kept backup can name them.
        blob = files.blob_path(hashlib.sha256(b'Last year').hexdigest())
        self.assertTrue(blob.exists())
        files.sweep(lambda: later + 14 * 86400)
        self.assertTrue(blob.exists())
        files.sweep(lambda: later + 16 * 86400)
        self.assertFalse(blob.exists())
        self.assertEqual(member.get(f"{root}/files/{kept['id']}/content").content, b'This year')
        with store.db() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM orphan_blobs').fetchone()[0], 0)

    def test_deleting_a_space_removes_its_files(self):
        host, member, sid = self.host_and_member()
        self.upload(host, sid, 'Notes.txt', b'Notes')
        host.delete(f'/api/community/spaces/{sid}', headers=H)
        with store.db() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM files').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
