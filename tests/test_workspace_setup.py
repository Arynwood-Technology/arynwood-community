"""Workspace staging is owner-only, additive, repeat-safe and uses real file-bank records."""
import csv
import io
from unittest.mock import patch
import unittest
import test_hub
from backend.community import store, workspace_setup

H = test_hub.H
class WorkspaceSetupTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member

    def test_owner_stages_complete_festival_and_repeat_preserves_edits(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}'
        body = {'kit':'film-festival','client':'RogueFest'}
        self.assertEqual(member.get(root+'/workspace-setup').status_code,403)
        self.assertEqual(member.post(root+'/workspace-setup',headers=H,json=body).status_code,403)
        preview = host.post(root+'/workspace-setup/preview',headers=H,json=body).json()
        self.assertEqual(preview['lists'],17)
        self.assertEqual(preview['events'],0)
        self.assertEqual(host.get(root+'/entries').json(),[])
        result = host.post(root+'/workspace-setup',headers=H,json=body)
        self.assertEqual(result.status_code,201,result.text)
        entries = host.get(root+'/entries').json()
        self.assertEqual(sum(e['kind']=='list' for e in entries),17)
        self.assertTrue(all(not e['done'] and not e['assigned_to'] for e in entries))
        parents = {e['id'] for e in entries if e['kind']=='list'}
        self.assertTrue(all(e['parent_id'] in parents for e in entries if e['kind']=='item'))
        self.assertTrue(all(e['visibility']=='shared' for e in entries))
        self.assertEqual(sum(e['kind']=='event' for e in entries),0)
        budget = host.get(root+'/files',params={'folder':'Festival Operations/Finance'}).json()['items']
        budget = next(f for f in budget if f['name']=='budget.csv')
        content = member.get(root+f"/files/{budget['id']}/content").text
        self.assertEqual(len(list(csv.reader(io.StringIO(content)))),1)
        changed = member.put(root+f"/files/{budget['id']}/text",headers=H,json={'text':content+'B1,Production,Venue,Rent,Expense,USD,100,120,,Approved,,,,,,\r\n','version':1})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(host.post(root+'/workspace-setup',headers=H,json=body).status_code,409)
        self.assertEqual(len(host.get(root+'/entries').json()),len(entries))
        self.assertEqual(host.get(root+f"/files/{budget['id']}/content").text,content+'B1,Production,Venue,Rent,Expense,USD,100,120,,Approved,,,,,,\r\n')
        self.assertTrue(any(a['action']=='workspace_staged' for a in host.get('/api/admin/activity',params={'limit':500}).json()['items']))

    def test_dates_are_explicit_proposals_and_other_space_cannot_apply(self):
        host, member, sid = self.host_and_member()
        root = f'/api/community/spaces/{sid}'
        result=host.post(root+'/workspace-setup',headers=H,json={'kit':'film-festival','client':'Test','opening_date':'2027-04-22'})
        self.assertEqual(result.status_code,201,result.text)
        events=[e for e in host.get(root+'/entries').json() if e['kind']=='event']
        self.assertEqual(len(events),14)
        self.assertTrue(all(e['title'].startswith('PROPOSED') for e in events))
        self.assertTrue(any(e['due']=='2027-04-22T09:00' for e in events))
        private=host.post('/api/community/spaces',headers=H,json={'name':'Restricted'}).json()['id']
        self.assertEqual(member.post(f'/api/community/spaces/{private}/workspace-setup',headers=H,json={'kit':'client-project','client':'Other'}).status_code,404)
        generic=host.post(f'/api/community/spaces/{private}/workspace-setup',headers=H,json={'kit':'client-project','client':'Other'})
        self.assertEqual(generic.status_code,201,generic.text)
        self.assertEqual(generic.json()['lists'],5)

    def test_conflicts_and_failure_do_not_leave_partial_entries(self):
        host, member, sid = self.host_and_member()
        root=f'/api/community/spaces/{sid}'
        body={'kit':'film-festival','client':'RogueFest'}
        self.assertEqual(host.post(root+'/workspace-setup',headers=H,json={**body,'kit':'unknown'}).status_code,404)
        self.assertEqual(host.post(root+'/workspace-setup',headers=H,json={**body,'client':'   '}).status_code,422)
        with patch.object(workspace_setup.files,'space_limit',return_value=1):
            self.assertEqual(host.post(root+'/workspace-setup',headers=H,json=body).status_code,413)
        self.assertEqual(host.get(root+'/entries').json(),[])
        self.assertEqual(host.get(root+'/workspace-setup').json()['installed'],[])
        host.post(root+'/folders',headers=H,json={'name':'Festival Operations'})
        self.assertEqual(host.post(root+'/workspace-setup',headers=H,json=body).status_code,409)
        self.assertEqual(host.get(root+'/entries').json(),[])

    def test_mid_transaction_failure_rolls_back_content_and_receipt(self):
        host, member, sid=self.host_and_member()
        root=f'/api/community/spaces/{sid}'
        with patch.object(workspace_setup.files,'blob_path',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                host.post(root+'/workspace-setup',headers=H,json={'kit':'film-festival','client':'RogueFest'})
        with store.db() as c:
            for table in ('entries','files','workspace_setups'):
                self.assertEqual(c.execute(f'SELECT COUNT(*) FROM {table} WHERE space_id=?',(sid,)).fetchone()[0],0)
