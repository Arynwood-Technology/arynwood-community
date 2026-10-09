"""Upgrading a Community 0.3 server in place, the installer's setup code, and public invite links."""
import os
import sqlite3
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import test_hub
from backend.api import app
from backend.community import auth, store

H = test_hub.H
PASSWORD = test_hub.PASSWORD


class Base(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite

    def space(self, client):
        return client.get('/api/community/spaces').json()[0]['id']

    def users(self):
        with sqlite3.connect(store.database_path()) as c: return c.execute('SELECT count(*) FROM users').fetchone()[0]


class UpgradeTests(Base):
    def test_community_03_install_keeps_its_data_settings_and_sessions(self):
        with TestClient(app) as old:
            self.signup(old)
            sid = self.space(old)
            old.post(f'/api/community/spaces/{sid}/entries', headers=H, json={'kind': 'task', 'title': 'Kept'})
            session = old.cookies.get('grove_session')
        # The same data, as Community 0.3 left it: community.sqlite3, COMMUNITY_* settings, its cookie.
        os.rename(os.path.join(self.data.name, 'grove.sqlite3'), os.path.join(self.data.name, 'community.sqlite3'))
        legacy = {'COMMUNITY_DATA_DIR': self.data.name, 'COMMUNITY_ORIGIN': 'https://community.example.test',
                  'COMMUNITY_HOSTS': 'community.example.test,testserver', 'COMMUNITY_SECURE_COOKIE': '1'}
        del os.environ['GROVE_DATA_DIR']
        with patch.dict(os.environ, legacy):
            self.assertEqual(store.database_path().name, 'community.sqlite3')
            self.assertEqual(store.public_origin(), 'https://community.example.test')
            with TestClient(app) as upgraded:
                upgraded.cookies.set('community_session', session)
                self.assertEqual(upgraded.get('/api/auth/me').status_code, 200)
                self.assertEqual([e['title'] for e in upgraded.get(f'/api/community/spaces/{sid}/entries').json()], ['Kept'])
                link = upgraded.post(f'/api/community/spaces/{sid}/invites', headers={**H, 'Origin': 'https://community.example.test'}).json()['url']
                self.assertTrue(link.startswith('https://community.example.test/community?invite='))
                self.assertEqual(upgraded.post('/api/auth/logout', headers={**H, 'Origin': 'https://elsewhere.example'}).status_code, 403)
                r = upgraded.post('/api/auth/login', headers=H, json={'email': 'host@example.test', 'password': PASSWORD})
                self.assertIn('secure', r.headers['set-cookie'].lower())
                upgraded.post('/api/auth/logout', headers=H)
                self.assertEqual(upgraded.get('/api/auth/me').status_code, 401)

    def test_a_plain_http_community_origin_is_not_a_public_address(self):
        with patch.dict(os.environ, {'COMMUNITY_ORIGIN': 'http://127.0.0.1:5174'}):
            self.assertEqual(store.public_origin(), '')
        with patch.dict(os.environ, {'COMMUNITY_ORIGIN': 'https://old.example.test', 'GROVE_PUBLIC_URL': 'https://new.example.test'}):
            self.assertEqual(store.public_origin(), 'https://new.example.test')


class SetupCodeTests(Base):
    def test_only_the_installer_can_create_the_host_account(self):
        with patch.dict(os.environ, {'GROVE_SETUP_CODE': 'river-stone-4821'}), TestClient(app) as client:
            self.assertEqual(client.get('/api/auth/status').json()['setup_code'], True)
            account = {'name': 'Host', 'email': 'host@example.test', 'password': PASSWORD, 'space': 'Home'}
            for code in ('', 'wrong'):
                r = client.post('/api/auth/signup', headers=H, json={**account, 'setup_code': code})
                self.assertEqual(r.status_code, 403, code)
            self.assertEqual(self.users(), 0)
            r = client.post('/api/auth/signup', headers=H, json={**account, 'setup_code': ' river-stone-4821 '})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()['admin'], 1)
            self.assertEqual(client.get('/api/auth/status').json()['setup_code'], False)

    def test_without_a_setup_code_the_first_account_is_open_as_before(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/auth/status').json()['setup_code'], False)
            self.signup(client)


class PublicLinkTests(Base):
    def link(self, client, sid, method='POST'):
        r = client.request(method, f'/api/community/spaces/{sid}/invite-link', headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_anyone_with_the_link_can_join_until_it_is_turned_off(self):
        with TestClient(app) as host:
            self.signup(host)
            sid = self.space(host)
            self.assertIsNone(self.link(host, sid, 'GET')['token'])
            token = self.link(host, sid)['token']
            self.assertEqual(self.link(host, sid, 'GET')['token'], token)  # the owner can copy it again later
            with patch.dict(os.environ, {'GROVE_PUBLIC_URL': 'https://grove.example.test'}):
                self.assertEqual(self.link(host, sid, 'GET')['url'], f'https://grove.example.test/community?invite={token}')
            # It works for many people, unlike a one-use invite.
            for n in range(3):
                with TestClient(app) as friend:
                    self.assertEqual(self.signup(friend, f'friend{n}@example.test', f'Friend {n}', token)['admin'], 0)
                    self.assertEqual(self.space(friend), sid)
            names = [m['name'] for m in host.get(f'/api/community/spaces/{sid}/members').json()]
            self.assertEqual(sorted(names), ['Friend 0', 'Friend 1', 'Friend 2', 'Host User'])
            # Someone who already has an account joins with it.
            other = host.post('/api/community/spaces', headers=H, json={'name': 'Elsewhere'}).json()['id']
            with TestClient(app) as existing:
                self.signup(existing, 'existing@example.test', 'Existing', self.invite(host, other))
                joined = existing.post('/api/community/join', headers=H, json={'token': token})
                self.assertEqual(joined.json()['id'], sid)
                self.assertEqual(existing.post('/api/community/join', headers=H, json={'token': token}).status_code, 200)
            # A new link replaces the old one; turning it off stops it.
            fresh = self.link(host, sid)['token']
            self.assertNotEqual(fresh, token)
            with TestClient(app) as late:
                late_account = {'name': 'Late', 'email': 'late@example.test', 'password': PASSWORD, 'invite': token}
                self.assertEqual(late.post('/api/auth/signup', headers=H, json=late_account).status_code, 400)
                self.link(host, sid, 'DELETE')
                self.assertIsNone(self.link(host, sid, 'GET')['token'])
                self.assertEqual(late.post('/api/auth/signup', headers=H, json={**late_account, 'invite': fresh}).status_code, 400)

    def test_only_the_space_owner_manages_the_link(self):
        with TestClient(app) as host, TestClient(app) as member:
            self.signup(host)
            sid = self.space(host)
            self.signup(member, 'member@example.test', 'Member', self.invite(host, sid))
            for method in ('GET', 'POST', 'DELETE'):
                self.assertEqual(member.request(method, f'/api/community/spaces/{sid}/invite-link', headers=H).status_code, 403, method)
            with TestClient(app) as stranger:
                self.assertEqual(stranger.get(f'/api/community/spaces/{sid}/invite-link').status_code, 401)

    def test_one_address_can_open_only_a_few_accounts_through_a_link(self):
        with TestClient(app) as host:
            self.signup(host)
            token = self.link(host, self.space(host))['token']
            with patch.object(auth, 'PUBLIC_LINK_SIGNUPS', 2), TestClient(app) as crowd:
                for n in range(2): self.signup(crowd, f'person{n}@example.test', f'Person {n}', token)
                r = crowd.post('/api/auth/signup', headers=H, json={'name': 'Third', 'email': 'third@example.test', 'password': PASSWORD, 'invite': token})
                self.assertEqual(r.status_code, 429)
            self.assertEqual(self.users(), 3)  # the refused sign-up left no account behind
            # One-use invites are not limited this way.
            with TestClient(app) as invited:
                self.signup(invited, 'invited@example.test', 'Invited', self.invite(host, self.space(host)))

    def test_deleting_a_space_removes_its_link(self):
        with TestClient(app) as host:
            self.signup(host)
            sid = host.post('/api/community/spaces', headers=H, json={'name': 'Short-lived'}).json()['id']
            self.link(host, sid)
            with sqlite3.connect(store.database_path()) as c:
                c.execute('PRAGMA foreign_keys = ON'); c.execute('DELETE FROM spaces WHERE id=?', (sid,))
                self.assertEqual(c.execute('SELECT count(*) FROM invite_links').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
