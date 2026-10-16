import asyncio
import os
import unittest
from unittest.mock import patch
import test_hub
from fastapi.testclient import TestClient
from backend.api import app
from backend.community import store
from backend.routers import chat, irc

ROGUEFEST = {'GROVE_CHAT_CHANNEL': '#RogueFest', 'GROVE_CHAT_NICK': 'RogueGuest###', 'GROVE_LOG_NAME': "Event journal"}


class ChatTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member

    def run_chat(self, client, first, server_lines=b':server 001 x :Welcome\r\n:server 376 x :End\r\n'):
        """Connects to Public chat against a stand-in IRC server; returns (where it connected, what it sent, replies)."""
        class Writer:
            def __init__(self): self.data = b''; self.closed = False
            def write(self, data): self.data += data
            async def drain(self): pass
            def is_closing(self): return self.closed
            def close(self): self.closed = True
            async def wait_closed(self): pass
        writer, targets, replies = Writer(), [], []
        async def connect(*args, **kwargs):
            targets.append((args, kwargs))
            reader = asyncio.StreamReader()
            reader.feed_data(server_lines)
            reader.feed_eof()
            return reader, writer
        with patch.object(irc.asyncio, 'open_connection', connect):
            with client.websocket_connect('/api/chat/ws') as ws:
                ws.send_json(first)
                while True:
                    reply = ws.receive_json(); replies.append(reply)
                    if reply['type'] in ('disconnect', 'error'): break
        return targets, writer, replies

    def test_settings(self):
        self.assertIsNone(store.public_chat())
        self.assertEqual(store.log_name(), 'Updates')
        with patch.dict(os.environ, ROGUEFEST):
            self.assertEqual(store.public_chat(), {'channel': '#RogueFest', 'nick': 'RogueGuest###', 'server': 'irc.arynwood.com', 'port': 6697})
            self.assertEqual(store.log_name(), "Event journal")
        with patch.dict(os.environ, {'GROVE_CHAT_CHANNEL': '#a', 'GROVE_CHAT_NICK': 'two words', 'GROVE_CHAT_SERVER': 'irc.example.test:6667',
                                     'GROVE_LOG_NAME': '  Captain’s\n  log ' + 'x' * 60}):
            self.assertEqual(store.public_chat(), {'channel': '#a', 'nick': 'Guest###', 'server': 'irc.example.test', 'port': 6667})
            self.assertEqual(store.log_name(), ('Captain’s log ' + 'x' * 60)[:40])
        for room in ('RogueFest', '#two words', '#a,#b', '#'):
            with patch.dict(os.environ, {'GROVE_CHAT_CHANNEL': room}): self.assertIsNone(store.public_chat(), room)
        for server in ('bad server', 'irc.example.test:0', 'irc.example.test:70000', 'irc.example.test:'):
            with patch.dict(os.environ, {'GROVE_CHAT_CHANNEL': '#a', 'GROVE_CHAT_SERVER': server}):
                self.assertEqual(store.public_chat()['server'], 'irc.arynwood.com', server)

    def test_members_see_the_room_and_the_log_name(self):
        host, member, _ = self.host_and_member()
        self.assertIsNone(member.get('/api/auth/me').json()['public_chat'])
        with patch.dict(os.environ, {**ROGUEFEST, 'GROVE_HOST_TOOLS': 'off'}):
            me = member.get('/api/auth/me').json()
            self.assertEqual(me['public_chat'], {'channel': '#RogueFest', 'nick': 'RogueGuest###', 'server': 'irc.arynwood.com'})
            self.assertEqual(me['log_name'], "Event journal")
            self.assertFalse(me['host_tools'])

    def test_a_member_joins_the_room_on_the_grove_server_only(self):
        with patch.dict(os.environ, {**ROGUEFEST, 'GROVE_HOST_TOOLS': 'off'}):
            host, member, _ = self.host_and_member()
            # Only the nickname comes from the browser: not the server, room, password or proxy.
            targets, writer, _ = self.run_chat(member, {'nick': 'RogueGuest123', 'host': 'evil.test', 'port': 25,
                                                        'channels': ['#other'], 'nick_password': 'not-sent', 'socks5_proxy': 'evil.test:1080'})
            self.assertEqual(targets[0][0][:2], ('irc.arynwood.com', 6697))
            self.assertIsNotNone(targets[0][1]['ssl'])
            self.assertIn(b'NICK RogueGuest123\r\n', writer.data)
            self.assertIn(b'JOIN #RogueFest\r\n', writer.data)
            self.assertNotIn(b'#other', writer.data)
            self.assertNotIn(b'IDENTIFY', writer.data)
            self.assertNotIn(b'not-sent', writer.data)
            # Host tools stay off for members: the host's own IRC relay is still closed to them.
            with self.assertRaises(Exception):
                with member.websocket_connect('/api/irc/ws') as ws: ws.receive_json()

    def test_refusals(self):
        host, member, _ = self.host_and_member()
        targets, _, replies = self.run_chat(member, {'nick': 'RogueGuest1'})
        self.assertEqual((targets, replies[-1]['message']), ([], 'Public chat is switched off on this Grove.'))
        with patch.dict(os.environ, ROGUEFEST):
            for nick in ('', 'Rogue Guest', '1Rogue', 'Rogue#1', 'a' * 31, 'x\r\nQUIT'):
                targets, _, replies = self.run_chat(member, {'nick': nick})
                self.assertEqual((targets, replies[-1]['type']), ([], 'error'), nick)
            chat.open_by_member[member.get('/api/auth/me').json()['id']] = chat.PER_MEMBER
            try:
                targets, _, replies = self.run_chat(member, {'nick': 'RogueGuest1'})
                self.assertEqual(targets, [])
                self.assertIn('two other windows', replies[-1]['message'])
            finally:
                chat.open_by_member.clear()
            with TestClient(app) as stranger, self.assertRaises(Exception):
                with stranger.websocket_connect('/api/chat/ws') as ws: ws.receive_json()


if __name__ == '__main__': unittest.main()
