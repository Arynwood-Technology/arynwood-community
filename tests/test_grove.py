import unittest
import test_hub
H = test_hub.H
from unittest.mock import patch

class GroveTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member
    def test_owner_tools_deny_members(self):
        host, member, sid = self.host_and_member()
        for endpoint in ('projects','server','models'):
            self.assertEqual(member.get('/api/grove/'+endpoint).status_code,403)
        self.assertEqual(member.post('/api/grove/chat',headers=H,json={'model':'fixture','prompt':'hello'}).status_code,403)
        self.assertEqual(member.post('/api/grove/projects',headers=H,json={'name':'secret'}).status_code,403)
        self.assertEqual(host.post('/api/grove/projects',headers=H,json={'name':'Website','description':'Draft'}).status_code,201)
        self.assertEqual(host.get('/api/grove/projects').json()[0]['name'],'Website')
        self.assertFalse(host.get('/api/grove/server').json()['execution_enabled'])
    def test_chat_does_not_send_other_workspace_content(self):
        host, member, sid = self.host_and_member()
        with patch('backend.grove.ollama',return_value={'message':{'content':'fixture reply'}}) as model:
            response=host.post('/api/grove/chat',headers=H,json={'model':'fixture','prompt':'Only this prompt'})
            self.assertEqual(response.json(),{'text':'fixture reply'})
            payload=model.call_args.args[1]
            self.assertEqual(payload['messages'],[{'role':'user','content':'Only this prompt'}])
            self.assertFalse(payload['stream'])
    def test_grove_cookie_and_database_are_separate(self):
        host, member, sid = self.host_and_member()
        self.assertIn('grove_session',host.cookies)
        self.assertNotIn('community_session',host.cookies)
        from backend.community.store import database_path
        self.assertEqual(database_path().name,'grove.sqlite3')

    def test_source_offer_excludes_runtime_data(self):
        import io, zipfile
        from fastapi.testclient import TestClient
        from backend.api import app
        with TestClient(app) as client:
            response=client.get('/api/source')
            self.assertEqual(response.status_code,200)
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                names=z.namelist()
                self.assertIn('arynwood-grove/LICENSE',names)
                self.assertIn('arynwood-grove/backend/grove.py',names)
                self.assertFalse(any('/data/' in n or n.endswith('/.env') or 'wallet' in n or 'node_modules' in n or 'design/' in n for n in names))
    def test_model_redirects_are_refused(self):
        from backend.grove import NoRedirect
        import urllib.error
        with self.assertRaises(urllib.error.URLError):
            NoRedirect().redirect_request(None,None,302,'Found',{},'https://example.test/')

