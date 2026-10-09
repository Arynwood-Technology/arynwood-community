import time
import unittest
from fastapi.testclient import TestClient
import test_hub
from backend.api import app
from backend.community.auth import digest
from backend.community.recovery import issue_reset
from backend.community.store import db

H=test_hub.H
NEW='new fixture password only'

class RecoveryTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member
    def test_reset_is_single_use_revokes_sessions_and_keeps_spaces(self):
        host,member,sid=self.host_and_member()
        with TestClient(app) as other:
            other.post('/api/auth/login',headers=H,json={'email':'host@example.test','password':test_hub.PASSWORD})
            token=issue_reset('HOST@example.test')
            with db() as c:
                self.assertEqual(c.execute('SELECT token FROM password_resets').fetchone()[0],digest(token))
            result=member.post('/api/auth/password/reset',headers=H,json={'token':token,'password':NEW})
            self.assertEqual(result.status_code,200)
            self.assertEqual(host.get('/api/auth/me').status_code,401)
            self.assertEqual(other.get('/api/auth/me').status_code,401)
            self.assertEqual(member.get('/api/auth/me').status_code,401)
            self.assertEqual(host.post('/api/auth/login',headers=H,json={'email':'host@example.test','password':test_hub.PASSWORD}).status_code,401)
            self.assertEqual(host.post('/api/auth/login',headers=H,json={'email':'host@example.test','password':NEW}).status_code,200)
            self.assertEqual(host.get('/api/community/spaces').json()[0]['id'],sid)
            self.assertEqual(host.post('/api/auth/password/reset',headers=H,json={'token':token,'password':NEW}).status_code,400)

    def test_expired_and_replaced_codes_fail(self):
        with TestClient(app) as client:
            self.signup(client)
            old=issue_reset('host@example.test');new=issue_reset('host@example.test')
            self.assertEqual(client.post('/api/auth/password/reset',headers=H,json={'token':old,'password':NEW}).status_code,400)
            with db() as c:c.execute('UPDATE password_resets SET expires=?',(time.time()-1,))
            self.assertEqual(client.post('/api/auth/password/reset',headers=H,json={'token':new,'password':NEW}).status_code,400)
            self.assertEqual(client.get('/api/auth/me').status_code,200)

    def test_no_http_issue_endpoint_and_protections_remain(self):
        with TestClient(app) as client:
            self.signup(client)
            self.assertEqual(client.post('/api/auth/password/issue',headers=H,json={'email':'host@example.test'}).status_code,405)
            token=issue_reset('host@example.test')
            payload={'token':token,'password':NEW}
            self.assertEqual(client.post('/api/auth/password/reset',json=payload).status_code,403)
            self.assertEqual(client.post('/api/auth/password/reset',headers={**H,'Origin':'https://evil.example'},json=payload).status_code,403)
            self.assertEqual(client.post('/api/auth/password/reset',headers=H,json={'token':token,'password':'short'}).status_code,422)
            for _ in range(12):
                self.assertEqual(client.post('/api/auth/password/reset',headers=H,json={'token':'invalid','password':NEW}).status_code,400)
            self.assertEqual(client.post('/api/auth/password/reset',headers=H,json=payload).status_code,429)

    def test_password_change_invalidates_outstanding_reset_codes(self):
        with TestClient(app) as client:
            self.signup(client);token=issue_reset('host@example.test')
            self.assertEqual(client.post('/api/auth/password',headers=H,json={'current':test_hub.PASSWORD,'password':NEW}).status_code,200)
            self.assertEqual(client.post('/api/auth/password/reset',headers=H,json={'token':token,'password':test_hub.PASSWORD}).status_code,400)

