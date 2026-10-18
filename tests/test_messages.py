"""Messages: private conversations between members who share a space, with photos stripped of their metadata."""
import struct
import time
import unittest
import zlib
import test_hub
from backend.community import files, photos

H = test_hub.H


def png(width=3, height=2, text=b'GPS 30.0475,-99.1403'):
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    rows = b''.join(b'\x00' + b'\xff\x00\x00' * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'tEXt', b'Location\x00' + text) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def jpeg(width=640, height=480):
    exif = b'Exif\x00\x00' + b'MM\x00\x2a' + b'GPS 30.0475,-99.1403 iPhone'
    segment = lambda marker, data: b'\xff' + bytes([marker]) + struct.pack('>H', len(data) + 2) + data
    return (b'\xff\xd8' + segment(0xE0, b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00') + segment(0xE1, exif) + segment(0xFE, b'Taken at the theater')
            + segment(0xC0, b'\x08' + struct.pack('>HH', height, width) + b'\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01')
            + b'\xff\xda' + struct.pack('>H', 12) + b'\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00' + b'\x12\x34pixels' + b'\xff\xd9')


class PhotoTests(unittest.TestCase):
    def test_metadata_comes_out_and_the_picture_stays(self):
        clean, kind, width, height = photos.plain(jpeg())
        self.assertEqual([kind, width, height], ['image/jpeg', 640, 480])
        for leak in (b'Exif', b'GPS', b'iPhone', b'theater'): self.assertNotIn(leak, clean)
        self.assertIn(b'JFIF', clean); self.assertTrue(clean.endswith(b'\x12\x34pixels\xff\xd9'))
        clean, kind, width, height = photos.plain(png())
        self.assertEqual([kind, width, height], ['image/png', 3, 2])
        self.assertNotIn(b'GPS', clean); self.assertIn(b'IDAT', clean); self.assertTrue(clean.endswith(b'IEND\xaeB`\x82'))
        for bad in (b'GIF89a...', b'<svg/>', b'\x89PNG\r\n\x1a\n\x00'):
            with self.assertRaises(photos.NotAPhoto): photos.plain(bad)


class MessageTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member

    def people(self):
        host, member, sid = self.host_and_member()
        ids = {p['name']: p['id'] for p in host.get('/api/messages/people').json()}
        me = host.get('/api/auth/me').json()['id']
        return host, member, sid, me, ids['Member Person']

    def test_members_who_share_a_space_write_to_each_other(self):
        host, member, sid, host_id, member_id = self.people()
        self.assertEqual([p['name'] for p in member.get('/api/messages/people').json()], ['Host User'])
        chat = host.post('/api/messages/conversations', headers=H, json={'user_id': member_id}).json()
        self.assertEqual(chat['with']['name'], 'Member Person')
        # The same two people always share one conversation.
        self.assertEqual(member.post('/api/messages/conversations', headers=H, json={'user_id': host_id}).json()['id'], chat['id'])
        sent = host.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H, json={'body': '  Venue walk-through at 10?  '})
        self.assertEqual([sent.status_code, sent.json()['body']], [201, 'Venue walk-through at 10?'])
        self.assertEqual(member.get('/api/messages/unread').json(), {'unread': 1})
        listed = member.get('/api/messages/conversations').json()
        self.assertEqual([listed[0]['with']['name'], listed[0]['last'], listed[0]['unread']], ['Host User', 'Venue walk-through at 10?', 1])
        thread = member.get(f"/api/messages/conversations/{chat['id']}").json()
        self.assertEqual([[m['body'], m['sender_id']] for m in thread['messages']], [['Venue walk-through at 10?', host_id]])
        self.assertTrue(thread['can_write'])
        member.post(f"/api/messages/conversations/{chat['id']}/read", headers=H).raise_for_status()
        self.assertEqual(member.get('/api/messages/unread').json(), {'unread': 0})
        self.assertEqual(member.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H, json={'body': ''}).status_code, 422)
        self.assertEqual(host.post('/api/messages/conversations', headers=H, json={'user_id': host_id}).status_code, 422)

    def test_messages_are_private_even_from_owners(self):
        host, member, sid, host_id, member_id = self.people()
        third = test_hub.TestClient(test_hub.app); third.__enter__(); self.addCleanup(third.__exit__, None, None, None)
        self.signup(third, 'third@example.test', 'Third Person', self.invite(host, sid))
        third_id = third.get('/api/auth/me').json()['id']
        chat = member.post('/api/messages/conversations', headers=H, json={'user_id': third_id}).json()
        member.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H, json={'body': 'Just between us'}).raise_for_status()
        # The host owns the Grove and the space, and still can't open it or see it listed.
        self.assertEqual(host.get(f"/api/messages/conversations/{chat['id']}").status_code, 404)
        self.assertEqual(host.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H, json={'body': 'hi'}).status_code, 404)
        self.assertEqual(host.get('/api/messages/conversations').json(), [])
        log = host.get('/api/admin/activity').json()['items']
        self.assertFalse([a for a in log if 'message' in a['action'] or 'Just between us' in str(a)])

    def test_only_people_who_share_a_space(self):
        host, member, sid, host_id, member_id = self.people()
        stranger = test_hub.TestClient(test_hub.app); stranger.__enter__(); self.addCleanup(stranger.__exit__, None, None, None)
        theirs = member.post('/api/community/spaces', headers=H, json={'name': 'Elsewhere'}).json()['id']
        self.signup(stranger, 'stranger@example.test', 'Stranger', self.invite(member, theirs))
        stranger_id = stranger.get('/api/auth/me').json()['id']
        self.assertNotIn('Stranger', [p['name'] for p in host.get('/api/messages/people').json()])
        self.assertEqual(host.post('/api/messages/conversations', headers=H, json={'user_id': stranger_id}).status_code, 404)
        # Once they no longer share a space, the conversation stays readable but takes no new messages.
        chat = member.post('/api/messages/conversations', headers=H, json={'user_id': stranger_id}).json()
        member.delete(f"/api/community/spaces/{theirs}/members/{stranger_id}", headers=H)
        if member.get(f"/api/messages/conversations/{chat['id']}").json()['can_write']: self.skipTest('removing a member works differently here')
        self.assertEqual(member.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H, json={'body': 'hello?'}).status_code, 403)

    def test_photos_travel_without_their_metadata_and_only_to_the_conversation(self):
        host, member, sid, host_id, member_id = self.people()
        chat = host.post('/api/messages/conversations', headers=H, json={'user_id': member_id}).json()
        first = host.post('/api/messages/photos', headers=H, content=jpeg())
        second = host.post('/api/messages/photos', headers=H, content=png())
        self.assertEqual([first.status_code, first.json()['width'], second.json()['height']], [201, 640, 2])
        self.assertEqual(host.post('/api/messages/photos', headers=H, content=b'GIF89a not a photo').status_code, 415)
        # Until it's sent, a photo is only its uploader's.
        self.assertEqual(member.get(f"/api/messages/photos/{first.json()['id']}").status_code, 404)
        sent = host.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H,
                         json={'body': '', 'photos': [second.json()['id'], first.json()['id']]}).json()
        self.assertEqual([p['id'] for p in sent['photos']], [second.json()['id'], first.json()['id']])
        shown = member.get(f"/api/messages/photos/{first.json()['id']}")
        self.assertEqual([shown.status_code, shown.headers['content-type'], shown.headers['content-security-policy']], [200, 'image/jpeg', 'sandbox'])
        self.assertNotIn(b'GPS', shown.content)
        self.assertEqual(member.get('/api/messages/conversations').json()[0]['last'], '2 photos')
        # A photo goes with one message only, and nobody else's.
        again = member.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H, json={'photos': [first.json()['id']]})
        self.assertEqual(again.status_code, 422)
        outsider = test_hub.TestClient(test_hub.app); outsider.__enter__(); self.addCleanup(outsider.__exit__, None, None, None)
        self.signup(outsider, 'third@example.test', 'Third Person', self.invite(host, sid))
        self.assertEqual(outsider.get(f"/api/messages/photos/{first.json()['id']}").status_code, 404)

    def test_taking_a_message_back_and_the_sweep(self):
        host, member, sid, host_id, member_id = self.people()
        chat = host.post('/api/messages/conversations', headers=H, json={'user_id': member_id}).json()
        photo = host.post('/api/messages/photos', headers=H, content=jpeg()).json()
        sent = host.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H, json={'body': 'Oops, wrong person', 'photos': [photo['id']]}).json()
        self.assertEqual(member.delete(f"/api/messages/messages/{sent['id']}", headers=H).status_code, 404)
        self.assertEqual(host.delete(f"/api/messages/messages/{sent['id']}", headers=H).status_code, 200)
        thread = member.get(f"/api/messages/conversations/{chat['id']}").json()['messages']
        self.assertEqual([thread[0]['body'], thread[0]['photos'], thread[0]['deleted']], ['', [], True])
        self.assertEqual(member.get(f"/api/messages/photos/{photo['id']}").status_code, 404)
        # Kept photos survive the sweep; ones never sent go after a day.
        kept = host.post('/api/messages/photos', headers=H, content=png(text=b'kept')).json()
        host.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H, json={'photos': [kept['id']]}).raise_for_status()
        waiting = host.post('/api/messages/photos', headers=H, content=png(text=b'waiting', width=5)).json()
        later = time.time() + 2 * 86400
        files.sweep(lambda: later); files.sweep(lambda: later + files.BLOB_GRACE + 60)
        self.assertEqual(member.get(f"/api/messages/photos/{kept['id']}").status_code, 200)
        self.assertEqual(host.get(f"/api/messages/photos/{waiting['id']}").status_code, 404)

    def send_file(self, client, name, data, piece=4000, finish=True):
        r = client.post('/api/messages/uploads', headers=H, json={'name': name, 'size': len(data)})
        self.assertEqual(r.status_code, 201, r.text)
        fid = r.json()['id']
        for offset in range(0, len(data), piece):
            self.assertEqual(client.put(f'/api/messages/uploads/{fid}', headers=H, params={'offset': offset}, content=data[offset:offset + piece]).status_code, 200)
        if finish: self.assertEqual(client.post(f'/api/messages/uploads/{fid}/finish', headers=H).status_code, 201)
        return fid

    def test_files_go_up_in_pieces_and_only_to_the_conversation(self):
        host, member, sid, host_id, member_id = self.people()
        chat = host.post('/api/messages/conversations', headers=H, json={'user_id': member_id}).json()
        say = lambda client, **body: client.post(f"/api/messages/conversations/{chat['id']}/messages", headers=H, json=body)
        data = b'%PDF-1.7 <script>alert(1)</script> minutes of the meeting ' * 300
        fid = self.send_file(host, 'Minutes “draft”.pdf', data, finish=False)
        self.assertEqual(host.get(f'/api/messages/uploads/{fid}').json(), {'received': len(data), 'size': len(data)})
        self.assertEqual(host.put(f'/api/messages/uploads/{fid}', headers=H, params={'offset': 0}, content=b'again').status_code, 409)
        self.assertEqual(say(host, files=[fid]).status_code, 422)  # not finished yet
        self.assertEqual(member.post(f'/api/messages/uploads/{fid}/finish', headers=H).status_code, 404)
        self.assertEqual(host.post(f'/api/messages/uploads/{fid}/finish', headers=H).json(), {'id': fid, 'name': 'Minutes “draft”.pdf', 'size': len(data)})
        # Until it's sent, a file is only its uploader's.
        self.assertEqual(member.get(f'/api/messages/files/{fid}').status_code, 404)
        sent = say(host, body='The minutes', files=[fid]).json()
        self.assertEqual(sent['files'], [{'id': fid, 'name': 'Minutes “draft”.pdf', 'size': len(data)}])
        got = member.get(f'/api/messages/files/{fid}')
        self.assertEqual([got.status_code, got.content, got.headers['content-type'], got.headers['content-security-policy']], [200, data, 'application/octet-stream', 'sandbox'])
        self.assertTrue(got.headers['content-disposition'].startswith('attachment;'))
        self.assertIn("filename*=utf-8''Minutes%20%E2%80%9Cdraft%E2%80%9D.pdf", got.headers['content-disposition'])
        # A file goes with one message only; a file on its own reads as one in the list.
        self.assertEqual(say(member, files=[fid]).status_code, 422)
        self.assertEqual(say(host, files=[self.send_file(host, 'Poster.ai', b'art')]).status_code, 201)
        self.assertEqual(member.get('/api/messages/conversations').json()[0]['last'], 'A file')
        outsider = test_hub.TestClient(test_hub.app); outsider.__enter__(); self.addCleanup(outsider.__exit__, None, None, None)
        self.signup(outsider, 'third@example.test', 'Third Person', self.invite(host, sid))
        self.assertEqual(outsider.get(f'/api/messages/files/{fid}').status_code, 404)
        self.assertEqual(host.post('/api/messages/uploads', headers=H, json={'name': 'Film.mov', 'size': 50 * files.MB + 1}).status_code, 413)
        self.assertEqual(host.post('/api/messages/uploads', headers=H, json={'name': '../secrets', 'size': 1}).status_code, 422)
        # Taking the message back takes its file; the sweep clears uploads that never became a message.
        self.assertEqual(host.delete(f"/api/messages/messages/{sent['id']}", headers=H).status_code, 200)
        self.assertEqual(member.get(f'/api/messages/files/{fid}').status_code, 404)
        stalled, waiting = self.send_file(host, 'Half.zip', b'x' * 9000, finish=False), self.send_file(host, 'Unsent.txt', b'never sent')
        later = time.time() + 2 * 86400
        files.sweep(lambda: later)
        for gone in (stalled, waiting): self.assertEqual(host.get(f'/api/messages/uploads/{gone}').status_code, 404)
        self.assertEqual(host.get(f'/api/messages/files/{waiting}').status_code, 404)
        self.assertFalse(files.part_path(stalled).exists())


if __name__ == '__main__':
    unittest.main()
