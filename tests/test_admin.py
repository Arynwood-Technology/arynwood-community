"""Running a Grove: Grove-wide roles, who may start spaces, and the activity log."""
import json
import unittest
import test_hub
from fastapi.testclient import TestClient
from backend.api import app
from backend.community import store
from backend.community.recovery import issue_reset

H = test_hub.H
PASSWORD = test_hub.PASSWORD


class AdminTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member

    def ids(self, host):
        return {p['name']: p['id'] for p in host.get('/api/admin/people').json()}

    def actions(self, client, **query):
        r = client.get('/api/admin/activity', params=query)
        self.assertEqual(r.status_code, 200, r.text)
        return [(a['action'], a['actor_name'], a['target_name']) for a in r.json()['items']][::-1]

    def test_the_host_is_an_owner_and_appoints_owners_and_managers(self):
        host, member, sid = self.host_and_member()
        me = host.get('/api/auth/me').json()
        self.assertEqual([me['role'], me['can_start_spaces']], ['owner', True])
        self.assertEqual(member.get('/api/auth/me').json()['role'], 'member')
        # Everyone comes in as a member, who sees none of this.
        for path in ('/api/admin/people', '/api/admin/activity', '/api/admin/settings', '/api/admin/spaces'):
            self.assertEqual(member.get(path).status_code, 403, path)
        ids = self.ids(host)
        role = lambda client, who, value: client.put(f'/api/admin/people/{ids[who]}/role', headers=H, json={'role': value})
        self.assertEqual(role(member, 'Member Person', 'owner').status_code, 403)
        self.assertEqual(role(host, 'Member Person', 'admin').status_code, 422)
        self.assertEqual(host.put('/api/admin/people/nobody/role', headers=H, json={'role': 'manager'}).status_code, 404)
        # A manager sees everything an owner sees, but changes no roles or settings.
        self.assertEqual(role(host, 'Member Person', 'manager').status_code, 200)
        self.assertEqual(member.get('/api/auth/me').json()['role'], 'manager')
        people = {p['name']: p for p in member.get('/api/admin/people').json()}
        self.assertEqual([people['Host User'][k] for k in ('role', 'host', 'spaces')], ['owner', 1, 1])
        self.assertEqual(people['Member Person']['role'], 'manager')
        self.assertEqual(member.get('/api/admin/activity').status_code, 200)
        self.assertEqual(role(member, 'Member Person', 'owner').status_code, 403)
        self.assertEqual(member.put('/api/admin/settings', headers=H, json={'space_creation': 'managers'}).status_code, 403)
        # A second owner appoints people too, and may step down; the host is always an owner.
        self.assertEqual(role(host, 'Member Person', 'owner').status_code, 200)
        self.assertEqual(role(member, 'Host User', 'member').status_code, 400)
        self.assertEqual(host.get('/api/auth/me').json()['role'], 'owner')
        self.assertEqual(role(member, 'Member Person', 'member').status_code, 200)
        self.assertEqual(member.get('/api/admin/people').status_code, 403)
        # Grove roles are separate from space roles.
        self.assertEqual(member.get('/api/community/spaces').json()[0]['role'], 'member')

    def test_owners_can_keep_space_starting_to_owners_and_managers(self):
        host, member, sid = self.host_and_member()
        self.assertEqual(host.get('/api/admin/settings').json(), {'space_creation': 'everyone', 'chat_privacy': 'private'})
        self.assertEqual(member.post('/api/community/spaces', headers=H, json={'name': 'Volunteers'}).status_code, 201)
        self.assertEqual(host.put('/api/admin/settings', headers=H, json={'space_creation': 'nobody'}).status_code, 422)
        self.assertEqual(host.put('/api/admin/settings', headers=H, json={'space_creation': 'managers'}).status_code, 200)
        self.assertFalse(member.get('/api/auth/me').json()['can_start_spaces'])
        refused = member.post('/api/community/spaces', headers=H, json={'name': 'Afterparty'})
        self.assertEqual(refused.status_code, 403)
        self.assertIn('owners and managers', refused.json()['detail'])
        member_id = self.ids(host)['Member Person']
        host.put(f'/api/admin/people/{member_id}/role', headers=H, json={'role': 'manager'})
        self.assertTrue(member.get('/api/auth/me').json()['can_start_spaces'])
        self.assertEqual(member.post('/api/community/spaces', headers=H, json={'name': 'Afterparty'}).status_code, 201)
        # Every space shows to owners and managers, whoever started it.
        self.assertEqual([s['name'] for s in host.get('/api/admin/spaces').json()], ['Afterparty', 'Our home', 'Volunteers'])

    def test_the_log_records_each_change_and_never_a_private_title(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}'
        member_id = self.ids(host)['Member Person']
        board = host.post(root + '/entries', headers=H, json={'kind': 'board', 'title': 'Screening schedule'}).json()
        member.post(root + '/entries', headers=H, json={'kind': 'comment', 'body': 'Looks good', 'parent_id': board['id']})
        task = member.post(root + '/entries', headers=H, json={'kind': 'task', 'title': 'Print badges'}).json()
        host.put(f"{root}/entries/{task['id']}", headers=H, json={**task, 'done': True})
        member.post(root + '/entries', headers=H, json={'kind': 'note', 'title': 'Secret plans', 'body': 'Secret body', 'visibility': 'private'})
        host.delete(f"{root}/entries/{board['id']}", headers=H)
        host.put(root, headers=H, json={'name': 'Festival team', 'topic': 'Opening night'})
        host.put(f'{root}/members/{member_id}', headers=H, json={'role': 'owner'})
        host.post(root + '/invite-link', headers=H)
        host.delete(root + '/invite-link', headers=H)
        member.get(root + '/export')
        self.assertEqual(self.actions(host), [
            ('signed_up', 'Host User', ''), ('invite_created', 'Host User', ''), ('signed_up', 'Member Person', ''),
            ('entry_created', 'Host User', 'Screening schedule'), ('entry_created', 'Member Person', 'Looks good'),
            ('entry_created', 'Member Person', 'Print badges'), ('entry_updated', 'Host User', 'Print badges'),
            ('entry_created', 'Member Person', ''), ('entry_deleted', 'Host User', 'Screening schedule'),
            ('space_updated', 'Host User', ''), ('space_role_changed', 'Host User', 'Member Person'),
            ('public_link_created', 'Host User', ''), ('public_link_turned_off', 'Host User', ''),
            ('space_exported', 'Member Person', '')])
        items = host.get('/api/admin/activity').json()['items']
        details = {a['action']: a['details'] for a in reversed(items)}
        self.assertEqual(details['signed_up'], {'via': 'invitation', 'invited_by': 'Host User'})
        self.assertEqual(details['entry_updated'], {'kind': 'task', 'done': True, 'author': 'Member Person'})
        self.assertEqual(details['entry_deleted'], {'kind': 'board', 'children': 1})
        self.assertEqual(details['space_updated'], {'renamed_from': 'Our home', 'topic': 'Opening night'})
        private = next(a for a in items if a['details'].get('private'))
        self.assertEqual([private['details']['kind'], private['target_name']], ['note', ''])
        self.assertNotIn('Secret', json.dumps(items))
        # The log outlives the space and its items, with names as they were. (The reply went with its post.)
        host.delete(root, headers=H)
        deleted = host.get('/api/admin/activity', params={'limit': 1}).json()['items'][0]
        self.assertEqual([deleted['action'], deleted['space_name'], deleted['details']], ['space_deleted', 'Festival team', {'members': 2, 'items': 2}])
        # All fourteen changes above happened in the space, and so did its deletion.
        self.assertEqual(len(host.get('/api/admin/activity', params={'space': sid}).json()['items']), 15)

    def test_joining_leaving_and_being_removed(self):
        host, member, sid = self.host_and_member()
        other = member.post('/api/community/spaces', headers=H, json={'name': 'Volunteers'}).json()
        link = member.post(f"/api/community/spaces/{other['id']}/invite-link", headers=H).json()['token']
        self.assertEqual(host.post('/api/community/join', headers=H, json={'token': link}).status_code, 200)
        # Opening the link again, already a member, is no news.
        host.post('/api/community/join', headers=H, json={'token': link})
        host.delete(f"/api/community/spaces/{other['id']}/members/{self.ids(host)['Host User']}", headers=H)
        host.delete(f"/api/community/spaces/{sid}/members/{self.ids(host)['Member Person']}", headers=H)
        log = host.get('/api/admin/activity').json()['items']
        self.assertEqual([(a['action'], a['space_name'], a['target_name']) for a in log[:5]][::-1], [
            ('space_created', 'Volunteers', ''), ('public_link_created', 'Volunteers', ''), ('joined_space', 'Volunteers', ''),
            ('member_left', 'Volunteers', ''), ('member_removed', 'Our home', 'Member Person')])
        self.assertEqual(log[2]['details'], {'via': 'public link', 'invited_by': 'Member Person'})

    def test_sign_ins_failures_and_recovery_codes_are_logged(self):
        host, member, sid = self.host_and_member()
        with TestClient(app) as stranger:
            stranger.post('/api/auth/login', headers=H, json={'email': 'member@example.test', 'password': 'not the password'})
            stranger.post('/api/auth/login', headers=H, json={'email': 'nobody@example.test', 'password': 'not the password'})
            stranger.post('/api/auth/login', headers=H, json={'email': 'member@example.test', 'password': PASSWORD})
        issue_reset('member@example.test')
        member.post('/api/auth/password', headers=H, json={'current': PASSWORD, 'password': 'another long password'})
        self.assertEqual(self.actions(host)[-4:], [
            ('sign_in_failed', '', 'Member Person'), ('signed_in', 'Member Person', ''),
            ('recovery_code_issued', '', 'Member Person'), ('password_changed', 'Member Person', '')])
        people = {p['name']: p for p in host.get('/api/admin/people').json()}
        self.assertIsNotNone(people['Member Person']['last_active'])

    def test_filtering_and_paging_the_log(self):
        host, member, sid = self.host_and_member()
        member_id = self.ids(host)['Member Person']
        for n in range(5):
            member.post(f'/api/community/spaces/{sid}/entries', headers=H, json={'kind': 'chat', 'body': f'Message {n}'})
        host.put(f'/api/admin/people/{member_id}/role', headers=H, json={'role': 'manager'})
        # Someone's activity includes what was done to them.
        self.assertEqual([a[0] for a in self.actions(host, person=member_id)], ['signed_up'] + ['entry_created'] * 5 + ['grove_role_changed'])
        first = host.get('/api/admin/activity', params={'limit': 3}).json()
        self.assertEqual(len(first['items']), 3)
        rest = host.get('/api/admin/activity', params={'before': first['next'], 'limit': 50}).json()
        self.assertIsNone(rest['next'])
        every = [a['id'] for a in first['items'] + rest['items']]
        self.assertEqual(every, sorted(every, reverse=True))
        self.assertEqual(len(every), len(set(every)))
        self.assertEqual(host.get('/api/admin/activity', params={'limit': 501}).status_code, 422)

    def test_a_grove_rolled_back_to_0_4_2_still_writes_accounts(self):
        store.initialize()
        # 0.4.2 inserts users and spaces positionally, so roles and the log must not add columns to them.
        with store.db() as c:
            c.execute('INSERT INTO users VALUES (?,?,?,?,?,?)', ('old', 'Made by 0.4.2', 'old@example.test', 'x', 0, 'now'))
            c.execute('INSERT INTO spaces VALUES (?,?,?)', ('old', 'Made by 0.4.2', 'now'))

    def test_host_tools_can_be_switched_off_for_a_client_grove(self):
        host, member, sid = self.host_and_member()
        self.assertEqual([host.get('/api/auth/me').json()['host_tools'], member.get('/api/auth/me').json()['host_tools']], [True, False])
        self.assertEqual(member.get('/api/mail/accounts').status_code, 403)
        with test_hub.patch.dict(test_hub.os.environ, {'GROVE_HOST_TOOLS': 'off'}):
            self.assertFalse(host.get('/api/auth/me').json()['host_tools'])
            # Gone rather than forbidden, for the host as much as anyone.
            for path in ('/api/mail/accounts', '/api/irc/client-config'):
                self.assertEqual(host.get(path).status_code, 404, path)
                self.assertEqual(TestClient(app).get(path).status_code, 404, path)


if __name__ == '__main__':
    unittest.main()
