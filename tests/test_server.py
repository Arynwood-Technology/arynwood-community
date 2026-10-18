"""A Grove on a server: members on other computers share one service and see changes live."""
import os
import queue
import socket
import threading
import time
import unittest
from unittest.mock import patch
import test_hub
import httpx
import uvicorn
from fastapi.testclient import TestClient
from backend.api import app
from backend.community import live

H = test_hub.H
PASSWORD = test_hub.PASSWORD


class ServerSettingsTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup

    def test_invite_link_names_the_public_address(self):
        with TestClient(app) as host:
            self.signup(host)
            sid = host.get('/api/community/spaces').json()[0]['id']
            self.assertIsNone(host.post(f'/api/community/spaces/{sid}/invites', headers=H).json()['url'])
            with patch.dict(os.environ, {'GROVE_PUBLIC_URL': 'https://grove.example.test/ignored/path'}):
                result = host.post(f'/api/community/spaces/{sid}/invites', headers=H).json()
                self.assertEqual(result['url'], 'https://grove.example.test/community?invite=' + result['token'])
                self.assertEqual(host.get('/api/auth/status').json()['public_url'], 'https://grove.example.test')

    def test_public_address_and_owner_workspace_are_both_trusted(self):
        env = {'GROVE_PUBLIC_URL': 'https://grove.example.test', 'GROVE_ORIGIN': 'http://127.0.0.1:5180, http://localhost:5180'}
        with patch.dict(os.environ, env), TestClient(app) as client:
            for origin, expected in [('https://grove.example.test', 200), ('http://127.0.0.1:5180', 200),
                                     ('http://localhost:5180', 200), ('https://evil.example', 403),
                                     ('http://grove.example.test', 403)]:
                r = client.post('/api/auth/logout', headers={**H, 'Origin': origin})
                self.assertEqual(r.status_code, expected, origin)

    def test_service_answers_the_workspace_paths(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/community-api/health').json()['name'], 'Arynwood Grove')
            self.assertEqual(client.get('/community-api/auth/status').status_code, 200)
            self.assertEqual(client.get('/community-api/auth/me').status_code, 401)
            self.assertEqual(client.get('/community-api').status_code, 404)
            self.assertEqual(client.get('/community-apix/health').status_code, 404)
            self.assertEqual(client.get('/community-api/health').headers['cache-control'], 'no-store')

    def test_members_page_has_no_owner_workspace(self):
        from backend.api import MEMBER_PAGE
        if not (MEMBER_PAGE / 'index.html').exists(): self.skipTest('members page not built (npm --prefix frontend run build)')
        with TestClient(app) as client:
            page = client.get('/community/calendar')
            self.assertEqual(page.status_code, 200)
            self.assertIn('Arynwood Grove', page.text)
            for name in ('html-tools/design-center.html', 'fonts/inter-latin-wght-normal.woff2', 'arynwood-tree.png'):
                self.assertEqual(client.get('/' + name).status_code, 404 if name.startswith('html-tools') else 200, name)
            bundle = ''.join((MEMBER_PAGE / 'assets' / f).read_text() for f in os.listdir(MEMBER_PAGE / 'assets') if f.endswith('.js'))
            self.assertIn('/community-api', bundle)
            for owner_only in ('/api/chat', '/api/ollama', '/api/fs', 'html-tools'):
                self.assertNotIn(owner_only, bundle)

    def test_cookie_is_secure_over_https(self):
        with TestClient(app, base_url='https://testserver') as secure:
            self.signup(secure)
            r = secure.post('/api/auth/login', headers=H, json={'email': 'host@example.test', 'password': PASSWORD})
            self.assertIn('secure', r.headers['set-cookie'].lower())
        with TestClient(app) as plain:
            r = plain.post('/api/auth/login', headers=H, json={'email': 'host@example.test', 'password': PASSWORD})
            self.assertNotIn('secure', r.headers['set-cookie'].lower())


class Events:
    """Reads one server-sent event stream on a thread; events arrive on a queue."""
    def __init__(self, client, sid, last_event_id=None, path=None):
        self.events, self.status = queue.Queue(), None
        headers = {'Last-Event-ID': last_event_id} if last_event_id else {}
        self.thread = threading.Thread(target=self.read, args=(client, path or f'/api/community/spaces/{sid}/events', headers), daemon=True)
        self.thread.start()

    def read(self, client, path, headers):
        try:
            with client.stream('GET', path, headers=headers, timeout=httpx.Timeout(10, read=20)) as r:
                self.status = r.status_code
                event = {}
                for line in r.iter_lines():
                    if not line:
                        if event: self.events.put(event)
                        event = {}
                    elif not line.startswith(':'):
                        field, _, value = line.partition(': ')
                        event[field] = value
        except httpx.HTTPError:
            pass  # the test closed its client while this stream was open
        finally:
            self.events.put({'event': 'END'})

    def next(self, timeout=4):
        return self.events.get(timeout=timeout)['event']

    def quiet_for(self, seconds):
        try: event = self.events.get(timeout=seconds)
        except queue.Empty: return True
        raise AssertionError(f'unexpected event {event}')


class LiveTests(unittest.TestCase):
    """Runs the real service, because live notices are a long-lived response."""
    setUp_hub = test_hub.HubTests.setUp

    def setUp(self):
        self.setUp_hub()
        self.addCleanup(self.env.stop); self.addCleanup(self.data.cleanup)
        timing = patch.multiple(live, STREAM_SECONDS=20, HEARTBEAT_SECONDS=1)
        timing.start(); self.addCleanup(timing.stop)
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
        thread = threading.Thread(target=self.server.run, daemon=True); thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(setattr, self.server, 'should_exit', True)
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline: time.sleep(0.05)
        self.base = f'http://127.0.0.1:{port}'

    def client(self):
        client = httpx.Client(base_url=self.base)
        self.addCleanup(client.close)
        return client

    def signup(self, client, email, name, invite=''):
        r = client.post('/api/auth/signup', headers=H, json={'name': name, 'email': email, 'password': PASSWORD, 'space': 'Our home', 'invite': invite})
        self.assertEqual(r.status_code, 200, r.text)

    def invite(self, client, sid):
        return client.post(f'/api/community/spaces/{sid}/invites', headers=H).json()['token']

    def entry(self, client, sid, **fields):
        r = client.post(f'/api/community/spaces/{sid}/entries', headers=H, json=fields)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def test_members_on_other_computers_hear_each_change(self):
        host, member, outsider = self.client(), self.client(), self.client()
        self.signup(host, 'host@example.test', 'Host')
        sid = host.get('/api/community/spaces').json()[0]['id']
        self.signup(member, 'member@example.test', 'Member', self.invite(host, sid))
        other = host.post('/api/community/spaces', headers=H, json={'name': 'Elsewhere'}).json()['id']
        self.signup(outsider, 'outsider@example.test', 'Outsider', self.invite(host, other))

        host_events, member_events = Events(host, sid), Events(member, sid)
        self.assertEqual(host_events.next(), 'ready'); self.assertEqual(member_events.next(), 'ready')

        # A shared change reaches everyone in the space at once.
        started = time.time()
        self.entry(host, sid, kind='event', title='Picnic', due='2026-10-10T12:00')
        self.assertEqual(member_events.next(), 'changed')
        self.assertLess(time.time() - started, 1.0)
        self.assertEqual(host_events.next(), 'changed')
        self.assertIn('Picnic', [e['title'] for e in member.get(f'/api/community/spaces/{sid}/entries').json()])
        task = self.entry(host, sid, kind='task', title='Bring blankets')
        self.assertEqual(member_events.next(), 'changed'); self.assertEqual(host_events.next(), 'changed')
        r = member.put(f"/api/community/spaces/{sid}/entries/{task['id']}", headers=H, json={**task, 'done': True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(host_events.next(), 'changed')
        self.assertEqual(member_events.next(), 'changed')

        # A private note is only announced to its author.
        self.entry(host, sid, kind='note', title='Secret', visibility='private')
        self.assertEqual(host_events.next(), 'changed')
        self.assertTrue(member_events.quiet_for(1.5))

        # Outsiders, signed-out pages and missing spaces get nothing.
        refused = Events(outsider, sid); self.assertEqual(refused.next(), 'END'); self.assertEqual(refused.status, 404)
        anonymous = Events(self.client(), sid); self.assertEqual(anonymous.next(), 'END'); self.assertEqual(anonymous.status, 401)

        # Removing a member ends their stream, and it cannot reopen.
        member_id = next(m['id'] for m in host.get(f'/api/community/spaces/{sid}/members').json() if m['name'] == 'Member')
        self.assertEqual(host.delete(f'/api/community/spaces/{sid}/members/{member_id}', headers=H).status_code, 200)
        self.assertEqual(member_events.next(), 'END')
        reopened = Events(member, sid); self.assertEqual(reopened.next(), 'END'); self.assertEqual(reopened.status, 404)

    def test_website_changes_ride_on_everyones_messages_stream(self):
        host, member = self.client(), self.client()
        self.signup(host, 'host@example.test', 'Host')
        sid = host.get('/api/community/spaces').json()[0]['id']
        folder = host.post('/api/webmaster/starter', headers=H, json={'space_id': sid}).json()['folder']
        theirs = host.post('/api/community/spaces', headers=H, json={'name': 'Elsewhere'}).json()['id']
        self.signup(member, 'member@example.test', 'Member', self.invite(host, theirs))
        events = Events(member, None, path='/api/messages/events'); self.assertEqual(events.next(), 'ready')
        self.assertEqual(live.streams_for(member.get('/api/auth/me').json()['id']), 1)
        # A note from anyone, and a saved website file, even in a space they aren't in.
        self.assertEqual(member.post('/api/webmaster/notes', headers=H, json={'space_id': sid, 'folder': folder, 'body': 'Bigger logo'}).status_code, 201)
        self.assertEqual(events.next(), 'website')
        page = next(i for i in host.get(f'/api/community/spaces/{sid}/files', params={'folder': folder}).json()['items'] if i['name'] == 'index.html')
        self.assertEqual(host.put(f"/api/community/spaces/{sid}/files/{page['id']}/text", headers=H, json={'text': '<h1>Hi</h1>', 'version': 1}).status_code, 200)
        self.assertEqual(events.next(), 'website')
        # A draft is only its author's, so it tells no one.
        self.assertEqual(host.put(f"/api/community/spaces/{sid}/files/{page['id']}/draft", headers=H, json={'text': '<h1>Hey</h1>', 'version': 2}).status_code, 200)
        self.assertTrue(events.quiet_for(1.5))

    def test_space_changes_reach_members_and_deleting_ends_their_streams(self):
        host, member = self.client(), self.client()
        self.signup(host, 'host@example.test', 'Host')
        sid = host.get('/api/community/spaces').json()[0]['id']
        self.signup(member, 'member@example.test', 'Member', self.invite(host, sid))
        events = Events(member, sid); self.assertEqual(events.next(), 'ready')
        # A new name or topic and a new role are announced, so open pages show them.
        self.assertEqual(host.put(f'/api/community/spaces/{sid}', headers=H, json={'name': 'Our house', 'topic': 'Sundays'}).status_code, 200)
        self.assertEqual(events.next(), 'changed')
        member_id = next(m['id'] for m in host.get(f'/api/community/spaces/{sid}/members').json() if m['name'] == 'Member')
        self.assertEqual(host.put(f'/api/community/spaces/{sid}/members/{member_id}', headers=H, json={'role': 'owner'}).status_code, 200)
        self.assertEqual(events.next(), 'changed')
        # Deleting the space ends every member's stream, and it cannot reopen.
        self.assertEqual(host.delete(f'/api/community/spaces/{sid}', headers=H).status_code, 200)
        self.assertEqual(events.next(), 'END')
        reopened = Events(member, sid); self.assertEqual(reopened.next(), 'END'); self.assertEqual(reopened.status, 404)

    def test_reconnect_catches_up_and_sign_out_stops_notices(self):
        host = self.client()
        self.signup(host, 'host@example.test', 'Host')
        sid = host.get('/api/community/spaces').json()[0]['id']
        current = live.revision(sid)
        self.assertEqual(Events(host, sid, last_event_id=current).next(), 'ready')
        self.entry(host, sid, kind='task', title='Missed while away')
        self.assertEqual(Events(host, sid, last_event_id=current).next(), 'changed')

        # Streams end on their own, so the browser reconnects and nothing is held open.
        with patch.object(live, 'STREAM_SECONDS', 2):
            events = Events(host, sid); self.assertEqual(events.next(), 'ready')
            self.assertEqual(events.next(timeout=6), 'END')

        events = Events(host, sid); self.assertEqual(events.next(), 'ready')
        signed_out = host.cookies.get('grove_session')
        host.post('/api/auth/logout', headers=H)
        self.assertEqual(events.next(), 'END')  # the next heartbeat re-checks the session
        stale = self.client(); stale.cookies.set('grove_session', signed_out)
        self.assertEqual(Events(stale, sid).next(), 'END')

    def test_open_pages_are_bounded_per_person(self):
        host = self.client()
        self.signup(host, 'host@example.test', 'Host')
        sid = host.get('/api/community/spaces').json()[0]['id']
        with patch.object(live, 'MAX_STREAMS_PER_USER', 2):
            first, second = Events(host, sid), Events(host, sid)
            self.assertEqual(first.next(), 'ready'); self.assertEqual(second.next(), 'ready')
            third = Events(host, sid)
            self.assertEqual(third.next(), 'END'); self.assertEqual(third.status, 429)


if __name__ == '__main__':
    unittest.main()
