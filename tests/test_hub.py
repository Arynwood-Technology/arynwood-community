import asyncio
import os
import stat
import unittest
import tempfile
from unittest.mock import patch
os.environ.setdefault('GROVE_HOSTS', 'testserver,localhost,127.0.0.1')
from fastapi.testclient import TestClient
from backend.api import app
from backend.community import store
from backend.routers import irc, mail, p2p

H = {'X-Community-Request': '1'}
PASSWORD = 'correct horse battery staple'


class HubTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GROVE_DATA_DIR': self.data.name})
        self.env.start()
        # Hermetic: no server settings from the shell running the tests.
        for name in [k for k in os.environ if k.startswith(('GROVE_', 'COMMUNITY_')) and k != 'GROVE_DATA_DIR']:
            del os.environ[name]
    def tearDown(self):
        self.env.stop(); self.data.cleanup()

    # Helpers ------------------------------------------------------------------
    def signup(self, client, email='host@example.test', name='Host User', invite=''):
        r = client.post('/api/auth/signup', headers=H, json={'name': name, 'email': email, 'password': PASSWORD, 'space': 'Our home', 'invite': invite})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()
    def invite(self, client, sid):
        r = client.post(f'/api/community/spaces/{sid}/invites', headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['token']
    def host_and_member(self):
        host, member = TestClient(app), TestClient(app)
        host.__enter__(); member.__enter__()
        self.addCleanup(host.__exit__, None, None, None); self.addCleanup(member.__exit__, None, None, None)
        self.signup(host)
        sid = host.get('/api/community/spaces').json()[0]['id']
        self.signup(member, 'member@example.test', 'Member Person', self.invite(host, sid))
        return host, member, sid

    # Tests --------------------------------------------------------------------
    def test_feature_routes_and_removed_endpoints(self):
        with TestClient(app) as client:
            health = client.get('/api/health').json()
            self.assertEqual(health['name'], 'Arynwood Grove')
            self.assertEqual(health['version'], store.VERSION)
            for path in ['/api/servers', '/api/irc/bots', '/api/tools', '/api/spotify/status']:
                self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.get('/api/p2p/status').status_code, 401)

    def test_first_account_space_and_permissions(self):
        with TestClient(app) as client:
            self.signup(client)
            me = client.get('/api/auth/me').json()
            spaces = client.get('/api/community/spaces').json()
            self.assertEqual(me['admin'], 1)
            self.assertEqual(spaces[0]['name'], 'Our home')
            entry = client.post('/api/community/spaces/'+spaces[0]['id']+'/entries', headers=H, json={'kind':'task','title':'Welcome','body':'Set up the house'})
            self.assertEqual(entry.status_code, 201)

    def test_database_is_private(self):
        with TestClient(app):
            mode = stat.S_IMODE(os.stat(store.database_path()).st_mode)
        self.assertEqual(mode, 0o600)

    def test_requests_without_app_header_are_blocked(self):
        with TestClient(app) as client:
            r = client.post('/api/auth/signup', json={'name':'X','email':'x@example.test','password':PASSWORD})
            self.assertEqual(r.status_code, 403)
            r = client.post('/api/auth/signup', headers={**H, 'Origin': 'https://evil.example'}, json={'name':'X','email':'x@example.test','password':PASSWORD})
            self.assertEqual(r.status_code, 403)

    def test_second_signup_requires_invite(self):
        with TestClient(app) as host, TestClient(app) as other:
            self.signup(host)
            r = other.post('/api/auth/signup', headers=H, json={'name':'X','email':'x@example.test','password':PASSWORD})
            self.assertEqual(r.status_code, 400)

    def test_invite_signup_and_single_use(self):
        host, member, sid = self.host_and_member()
        self.assertEqual(member.get('/api/auth/me').json()['admin'], 0)
        self.assertEqual([s['id'] for s in member.get('/api/community/spaces').json()], [sid])
        # Members cannot create invites or reach host-only connections.
        self.assertEqual(member.post(f'/api/community/spaces/{sid}/invites', headers=H).status_code, 403)
        self.assertEqual(member.get('/api/mail/accounts').status_code, 403)
        self.assertEqual(member.get('/api/community/connections').status_code, 403)

    def test_existing_account_joins_with_invite(self):
        host, member, sid = self.host_and_member()
        other = member.post('/api/community/spaces', headers=H, json={'name': 'Book club'}).json()
        token = self.invite(member, other['id'])
        joined = host.post('/api/community/join', headers=H, json={'token': token})
        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertEqual(joined.json()['name'], 'Book club')
        self.assertEqual(joined.json()['role'], 'member')
        self.assertEqual(host.post('/api/community/join', headers=H, json={'token': token}).status_code, 400)

    def test_private_entries_are_hidden_from_others(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}/entries'
        private = host.post(root, headers=H, json={'kind':'note','title':'Secret','visibility':'private'}).json()
        host.post(root, headers=H, json={'kind':'note','title':'Shared'})
        titles = [e['title'] for e in member.get(root).json()]
        self.assertEqual(titles, ['Shared'])
        self.assertEqual(member.put(f"{root}/{private['id']}", headers=H, json={'kind':'note','title':'x','visibility':'private'}).status_code, 404)
        export = member.get(f'/api/community/spaces/{sid}/export').json()
        self.assertNotIn('Secret', [e['title'] for e in export['entries']])

    def test_edit_conflict_and_author_rules(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}/entries'
        post = host.post(root, headers=H, json={'kind':'board','title':'Dinner','body':'Sunday?'}).json()
        # A member cannot edit or delete someone else's post.
        self.assertEqual(member.put(f"{root}/{post['id']}", headers=H, json={**post, 'title':'Hacked'}).status_code, 403)
        self.assertEqual(member.delete(f"{root}/{post['id']}", headers=H).status_code, 403)
        # Tasks are shared work: anyone in the space may complete them.
        task = host.post(root, headers=H, json={'kind':'task','title':'Bins'}).json()
        done = member.put(f"{root}/{task['id']}", headers=H, json={**task, 'done': True})
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()['version'], 2)
        stale = host.put(f"{root}/{task['id']}", headers=H, json={**task, 'title':'Bins out'})
        self.assertEqual(stale.status_code, 409)

    def test_replies_and_list_items_follow_parent(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}/entries'
        lst = host.post(root, headers=H, json={'kind':'list','title':'Groceries'}).json()
        item = member.post(root, headers=H, json={'kind':'item','title':'Milk','parent_id':lst['id']})
        self.assertEqual(item.status_code, 201)
        bad = member.post(root, headers=H, json={'kind':'comment','body':'hi','parent_id':lst['id']})
        self.assertEqual(bad.status_code, 422)
        host.delete(f"{root}/{lst['id']}", headers=H)
        self.assertEqual(host.get(root).json(), [])

    def test_assignment_must_be_a_member(self):
        host, member, sid = self.host_and_member()
        r = host.post(f'/api/community/spaces/{sid}/entries', headers=H, json={'kind':'task','title':'X','assigned_to':'nobody'})
        self.assertEqual(r.status_code, 422)
        self.assertIn('someone in this space', r.json()['detail'])

    def test_member_can_leave_and_owner_can_remove(self):
        host, member, sid = self.host_and_member()
        members = host.get(f'/api/community/spaces/{sid}/members').json()
        host_id = next(m['id'] for m in members if m['role'] == 'owner')
        member_id = next(m['id'] for m in members if m['role'] == 'member')
        self.assertEqual(member.delete(f'/api/community/spaces/{sid}/members/{host_id}', headers=H).status_code, 403)
        self.assertEqual(host.delete(f'/api/community/spaces/{sid}/members/{host_id}', headers=H).status_code, 400)
        self.assertEqual(member.delete(f'/api/community/spaces/{sid}/members/{member_id}', headers=H).status_code, 200)
        self.assertEqual(member.get('/api/community/spaces').json(), [])
        self.assertEqual(member.get(f'/api/community/spaces/{sid}/entries').status_code, 404)

    def test_owner_renames_sets_topic_and_deletes_space(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}'
        # Only an owner manages the space.
        self.assertEqual(member.put(root, headers=H, json={'name': 'Mine now'}).status_code, 403)
        self.assertEqual(member.delete(root, headers=H).status_code, 403)
        saved = host.put(root, headers=H, json={'name': ' Our house ', 'topic': 'Dinner on\n Sundays '})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual([saved.json()[k] for k in ('name', 'topic', 'role')], ['Our house', 'Dinner on Sundays', 'owner'])
        seen = member.get('/api/community/spaces').json()[0]
        self.assertEqual([seen[k] for k in ('name', 'topic', 'role')], ['Our house', 'Dinner on Sundays', 'member'])
        self.assertEqual(member.get(root + '/export').json()['space']['topic'], 'Dinner on Sundays')
        self.assertEqual(host.put(root, headers=H, json={'name': 'Our house', 'topic': ''}).json()['topic'], '')
        self.assertEqual(host.put(root, headers=H, json={'name': '  '}).status_code, 422)
        self.assertEqual(host.put(root, headers=H, json={'name': 'Our house', 'topic': 'x' * 301}).status_code, 422)
        # Deleting removes the space, and everything in it, for every member.
        host.post(root + '/entries', headers=H, json={'kind': 'list', 'title': 'Groceries'})
        host.put(root, headers=H, json={'name': 'Our house', 'topic': 'Kept until deleted'})
        self.invite(host, sid); host.post(root + '/invite-link', headers=H)
        self.assertEqual(host.delete(root, headers=H).status_code, 200)
        self.assertEqual(host.get('/api/community/spaces').json(), [])
        self.assertEqual(member.get('/api/community/spaces').json(), [])
        self.assertEqual(member.get(root + '/entries').status_code, 404)
        self.assertEqual(host.delete(root, headers=H).status_code, 404)
        with store.db() as c:
            for table in ('members', 'entries', 'invites', 'invite_links', 'space_topics'):
                self.assertEqual(c.execute(f'SELECT COUNT(*) FROM {table} WHERE space_id=?', (sid,)).fetchone()[0], 0, table)

    def test_owners_change_roles_and_a_space_keeps_an_owner(self):
        host, member, sid = self.host_and_member()
        people = f'/api/community/spaces/{sid}/members'
        ids = {m['role']: m['id'] for m in host.get(people).json()}
        host_id, member_id = ids['owner'], ids['member']
        # A member cannot change roles, their own included.
        self.assertEqual(member.put(f'{people}/{member_id}', headers=H, json={'role': 'owner'}).status_code, 403)
        # The only owner can neither step down nor leave.
        self.assertEqual(host.put(f'{people}/{host_id}', headers=H, json={'role': 'member'}).status_code, 400)
        self.assertEqual(host.put(f'{people}/{member_id}', headers=H, json={'role': 'admin'}).status_code, 422)
        self.assertEqual(host.put(f'{people}/nobody', headers=H, json={'role': 'owner'}).status_code, 404)
        self.assertEqual(host.put(f'{people}/{member_id}', headers=H, json={'role': 'owner'}).status_code, 200)
        self.assertEqual(member.get('/api/community/spaces').json()[0]['role'], 'owner')
        self.assertEqual(member.post(f'/api/community/spaces/{sid}/invites', headers=H).status_code, 200)
        # With a second owner, the first may step down; the new owner may then remove them.
        self.assertEqual(host.put(f'{people}/{host_id}', headers=H, json={'role': 'member'}).status_code, 200)
        self.assertEqual(host.put(f'{people}/{member_id}', headers=H, json={'role': 'member'}).status_code, 403)
        self.assertEqual(member.delete(f'{people}/{host_id}', headers=H).status_code, 200)
        self.assertEqual([m['name'] for m in member.get(people).json()], ['Member Person'])
        self.assertEqual(member.delete(f'{people}/{member_id}', headers=H).status_code, 400)

    def test_tasks_are_assigned_to_members_and_private_ones_only_to_their_author(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}/entries'
        ids = {m['role']: m['id'] for m in host.get(f'/api/community/spaces/{sid}/members').json()}
        task = host.post(root, headers=H, json={'kind': 'task', 'title': 'Bins', 'assigned_to': ids['member']})
        self.assertEqual(task.status_code, 201, task.text)
        self.assertEqual([e['assigned_to'] for e in member.get(root).json()], [ids['member']])
        # Anyone in the space may hand a task on.
        moved = member.put(f"{root}/{task.json()['id']}", headers=H, json={**task.json(), 'assigned_to': ids['owner']})
        self.assertEqual(moved.json()['assigned_to'], ids['owner'])
        # The other person could never see a private task.
        hidden = host.post(root, headers=H, json={'kind': 'task', 'title': 'Gift', 'visibility': 'private', 'assigned_to': ids['member']})
        self.assertEqual(hidden.status_code, 422)
        self.assertIn('only you', hidden.json()['detail'])
        mine = host.post(root, headers=H, json={'kind': 'task', 'title': 'Gift', 'visibility': 'private', 'assigned_to': ids['owner']})
        self.assertEqual(mine.status_code, 201)

    def test_database_still_works_for_a_grove_rolled_back_to_0_4_1(self):
        store.initialize()
        # 0.4.1 inserts spaces positionally, so topics must not add a column to spaces.
        with store.db() as c:
            c.execute('INSERT INTO spaces VALUES (?,?,?)', ('old', 'Made by 0.4.1', 'now'))

    def test_password_change_signs_out_other_sessions(self):
        with TestClient(app) as a, TestClient(app) as b:
            self.signup(a)
            self.assertEqual(b.post('/api/auth/login', headers=H, json={'email':'host@example.test','password':PASSWORD}).status_code, 200)
            self.assertEqual(a.post('/api/auth/password', headers=H, json={'current':'wrong password here','password':'another long password'}).status_code, 400)
            self.assertEqual(a.post('/api/auth/password', headers=H, json={'current':PASSWORD,'password':'another long password'}).status_code, 200)
            self.assertEqual(a.get('/api/auth/me').status_code, 200)
            self.assertEqual(b.get('/api/auth/me').status_code, 401)
            self.assertEqual(b.post('/api/auth/login', headers=H, json={'email':'HOST@example.test','password':'another long password'}).status_code, 200)

    def test_login_rate_limit(self):
        with TestClient(app) as client:
            self.signup(client)
            codes = [client.post('/api/auth/login', headers=H, json={'email':'host@example.test','password':'wrong password!'}).status_code for _ in range(13)]
            self.assertEqual(codes[-1], 429)

    def test_spa_routes_and_asset_caching(self):
        from backend.api import web_dir
        with TestClient(app) as client:
            if not (web_dir() / 'index.html').exists():
                self.skipTest('frontend not built')
            for path in ['/', '/boards', '/join', '/settings', '/community', '/community/calendar']:
                self.assertEqual(client.get(path).status_code, 200)
            self.assertEqual(client.get('/nope').status_code, 404)
            self.assertEqual(client.get('/api/nope').status_code, 404)
            self.assertEqual(client.get('/../backend/api.py').status_code, 404)
            self.assertIn('no-cache', client.get('/').headers['cache-control'])

    def test_imap_account_without_thunderbird(self):
        with patch.dict(os.environ, {'MAIL_IMAP_HOST': 'example.test', 'MAIL_IMAP_USER': 'user@example.test', 'MAIL_IMAP_PASS': 'test'}):
            with patch.object(mail, '_tb_profiles', side_effect=AssertionError('must not require Thunderbird')):
                self.assertEqual(mail.get_accounts(), [{'id': 'imap', 'label': 'user@example.test'}])

    def test_mail_errors_are_reported(self):
        with TestClient(app) as client:
            self.signup(client)
            with patch.dict(os.environ, {'MAIL_IMAP_HOST': 'example.test', 'MAIL_IMAP_USER': 'u', 'MAIL_IMAP_PASS': 'p'}):
                with patch.object(mail.imaplib, 'IMAP4_SSL', side_effect=OSError('unreachable')):
                    r = client.get('/api/mail/inbox')
            self.assertEqual(r.status_code, 502)
            self.assertIn('unreachable', r.json()['detail'])
            self.assertEqual(client.get('/api/mail/message/..%2F..%2Fetc/1').status_code, 404)
            self.assertEqual(client.get('/api/mail/message/../1').status_code, 404)
            with patch.dict(os.environ, {'MAIL_SMTP_HOST': '', 'MAIL_IMAP_HOST': ''}):
                r = client.post('/api/mail/send', headers=H, json={'to':'a@example.test','subject':'Hi','body':'x'})
            self.assertEqual(r.status_code, 400)
            r = client.post('/api/mail/send', headers=H, json={'to':'a@example.test\r\nBcc: b@example.test','subject':'Hi','body':'x'})
            self.assertEqual(r.status_code, 422)

    def test_wallet_import_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            wallet = os.path.join(tmp, 'wallet.json')
            with patch.object(p2p.os.path, 'abspath', side_effect=lambda p: wallet if p.endswith('wallet.json') else os.path.realpath(p)):
                with TestClient(app) as client:
                    self.signup(client)
                    r = client.post('/api/p2p/wallet', headers=H, json={'seed': 'a' * 64})
                    self.assertEqual(r.status_code, 200, r.text)
                    self.assertEqual(client.post('/api/p2p/wallet', headers=H, json={'seed': 'xyz'}).status_code, 400)
            self.assertEqual(stat.S_IMODE(os.stat(wallet).st_mode), 0o600)

    def run_irc(self, server_lines, commands=()):
        class Writer:
            def __init__(self): self.data = b''; self.closed = False
            def write(self, data): self.data += data
            async def drain(self): pass
            def is_closing(self): return self.closed
            def close(self): self.closed = True
            async def wait_closed(self): pass
        writer = Writer()
        async def connect(*args, **kwargs):
            reader = asyncio.StreamReader()
            reader.feed_data(server_lines)
            reader.feed_eof()
            return reader, writer
        with patch.object(irc.asyncio, 'open_connection', connect):
            with TestClient(app) as client:
                self.signup(client)
                with client.websocket_connect('/api/irc/ws') as ws:
                    ws.send_json({'host': 'example.test', 'port': 6667, 'nick': 'hub', 'channels': ['#test']})
                    for cmd in commands: ws.send_json({'cmd': cmd})
                    while ws.receive_json()['type'] != 'disconnect': pass
        return writer

    def test_irc_relay_nickname_collision_and_no_motd(self):
        writer = self.run_irc(b':server 433 * hub :Nickname in use\r\n:server 422 hub_ :No MOTD\r\nPING :check\r\n')
        self.assertIn(b'NICK hub_\r\n', writer.data)
        self.assertIn(b'JOIN #test\r\n', writer.data)
        self.assertIn(b'PONG :check\r\n', writer.data)
        self.assertTrue(writer.closed)

    def test_irc_nick_collision_after_registration_is_left_alone(self):
        writer = self.run_irc(b':server 001 hub :Welcome\r\n:server 376 hub :End\r\n:server 433 hub taken :Nickname in use\r\n')
        self.assertNotIn(b'NICK hub_', writer.data)

    def test_irc_config_cannot_inject_commands(self):
        self.assertEqual(irc.one_line('PRIVMSG #a :hi\r\nQUIT'), 'PRIVMSG #a :hi  QUIT')


if __name__ == '__main__': unittest.main()
