"""The host moves the Grove to their own domain: DNS check, request file for the root helper."""
import json
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import test_hub
from backend.api import app
from backend import setup

H = test_hub.H
HELPER = {'GROVE_DOMAIN_HELPER': '1', 'GROVE_SERVER_IP': '203.0.113.5', 'GROVE_PUBLIC_URL': 'https://203-0-113-5.sslip.io'}


class AddressTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite

    def request_file(self):
        return setup.requests_dir() / 'domain.json'

    def test_the_host_checks_dns_and_asks_to_move(self):
        with patch.dict(os.environ, HELPER), TestClient(app) as host:
            self.signup(host)
            info = host.get('/api/grove-setup/address').json()
            self.assertEqual((info['host'], info['temporary'], info['server_ip'], info['can_change']), ('203-0-113-5.sslip.io', True, '203.0.113.5', True))
            with patch.object(setup, 'lookup', return_value=[]):
                r = host.post('/api/grove-setup/check-domain', headers=H, json={'domain': ' HTTPS://Grove.Example.com/ '}).json()
            self.assertEqual(r, {'domain': 'grove.example.com', 'addresses': [], 'points_here': False,
                                 'record': {'type': 'A', 'name': 'grove', 'value': '203.0.113.5'}})
            with patch.object(setup, 'lookup', return_value=['203.0.113.5']):
                self.assertTrue(host.post('/api/grove-setup/check-domain', headers=H, json={'domain': 'example.com'}).json()['points_here'])
                self.assertEqual(host.post('/api/grove-setup/check-domain', headers=H, json={'domain': 'example.com'}).json()['record']['name'], '@')
            r = host.post('/api/grove-setup/domain', headers=H, json={'domain': 'grove.example.com', 'email': 'host@example.com'})
            self.assertEqual(r.status_code, 202, r.text)
            self.assertEqual({k: v for k, v in json.loads(self.request_file().read_text()).items() if k != 'requested'},
                             {'domain': 'grove.example.com', 'email': 'host@example.com'})
            self.assertEqual(host.get('/api/grove-setup/address').json()['pending'], 'grove.example.com')
            # One change at a time.
            self.assertEqual(host.post('/api/grove-setup/domain', headers=H, json={'domain': 'other.example.com'}).status_code, 409)
            # The helper reports back.
            self.request_file().unlink()
            (setup.requests_dir() / 'domain.result.json').write_text(json.dumps({'status': 'done', 'domain': 'grove.example.com', 'message': ''}))
            info = host.get('/api/grove-setup/address').json()
            self.assertIsNone(info['pending']); self.assertEqual(info['result']['status'], 'done')

    def test_only_safe_names_reach_the_helper(self):
        with patch.dict(os.environ, HELPER), TestClient(app) as host:
            self.signup(host)
            for bad in ('localhost', '203.0.113.9', 'grove.example.com;reboot', 'gro ve.example.com', '-grove.example.com', 'a' * 64 + '.example.com', 'grove.example.com\nx'):
                r = host.post('/api/grove-setup/domain', headers=H, json={'domain': bad})
                self.assertEqual(r.status_code, 400, bad)
            r = host.post('/api/grove-setup/domain', headers=H, json={'domain': 'grove.example.com', 'email': 'not an email'})
            self.assertEqual(r.status_code, 400)
            self.assertFalse(self.request_file().exists())

    def test_hosts_only_and_only_on_installed_servers(self):
        with patch.dict(os.environ, HELPER), TestClient(app) as host, TestClient(app) as member:
            self.signup(host)
            sid = host.get('/api/community/spaces').json()[0]['id']
            self.signup(member, 'member@example.test', 'Member', self.invite(host, sid))
            for method, path in (('GET', '/address'), ('POST', '/check-domain'), ('POST', '/domain')):
                self.assertEqual(member.request(method, '/api/grove-setup' + path, headers=H, json={'domain': 'grove.example.com'}).status_code, 403, path)
        with TestClient(app) as host:
            self.assertEqual(host.post('/api/auth/login', headers=H, json={'email': 'host@example.test', 'password': test_hub.PASSWORD}).status_code, 200)
            self.assertFalse(host.get('/api/grove-setup/address').json()['can_change'])
            self.assertEqual(host.post('/api/grove-setup/domain', headers=H, json={'domain': 'grove.example.com'}).status_code, 409)

    def test_temporary_addresses(self):
        for host, temporary in (('203-0-113-5.sslip.io', True), ('10.0.0.5', True), ('', True), ('grove.example.com', False), ('community.arynwood.com', False)):
            self.assertEqual(setup.is_temporary(host), temporary, host)


if __name__ == '__main__':
    unittest.main()
