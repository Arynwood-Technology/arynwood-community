import asyncio
import os
import unittest
from unittest.mock import patch
import test_hub
from test_hub import H
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
            self.assertEqual(me['public_chat'], {'channel': '#RogueFest', 'nick': 'RogueGuest###', 'server': 'irc.arynwood.com', 'private': True})
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
            self.assertRegex(writer.data, rb'JOIN #RogueFest [0-9a-f]{16}\r\n')
            self.assertNotIn(b'#other', writer.data)
            self.assertNotIn(b'IDENTIFY', writer.data)
            self.assertNotIn(b'not-sent', writer.data)
            # Host tools stay off for members: the host's own IRC relay is still closed to them.
            with self.assertRaises(Exception):
                with member.websocket_connect('/api/irc/ws') as ws: ws.receive_json()

    def test_a_member_stays_in_the_room(self):
        room = chat.Room('#RogueFest', 'k3y', True)
        allowed = {'PRIVMSG #roguefest :hi': 'PRIVMSG #roguefest :hi', 'PRIVMSG Ann :psst': 'PRIVMSG Ann :psst', 'NOTICE #RogueFest :x': 'NOTICE #RogueFest :x',
                   'JOIN #RogueFest': 'JOIN #RogueFest k3y', 'PART #RogueFest :bye': 'PART #RogueFest :bye', 'NICK Rogue2': 'NICK Rogue2',
                   'WHOIS Ann Ann': 'WHOIS Ann Ann', 'WHO #RogueFest %nuh': 'WHO #RogueFest %nuh', 'NAMES #RogueFest': 'NAMES #RogueFest',
                   'TOPIC #RogueFest :Tonight': 'TOPIC #RogueFest :Tonight', 'MODE #RogueFest': 'MODE #RogueFest', 'MODE #RogueFest +b bad!*@*': 'MODE #RogueFest +b bad!*@*',
                   'MODE #RogueFest +o Ann': 'MODE #RogueFest +o Ann', 'AWAY :lunch': 'AWAY :lunch', 'QUIT :bye': 'QUIT :bye'}
        for line, sent in allowed.items(): self.assertEqual(room.to_server(line), (sent, ''), line)
        for line in ('JOIN #OtherGrove', 'JOIN #RogueFest,#Other', 'JOIN 0', 'LIST', 'LIST #Other', 'PRIVMSG #Other :hi', 'PRIVMSG Ann,#Other :hi', 'NOTICE @#RogueFest :x',
                     'NAMES', 'NAMES #Other', 'WHO *', 'WHO #Other', 'WHOIS #Other', 'PART #Other', 'TOPIC #Other :x', 'KICK #Other Ann', 'MODE #Other +b x',
                     'STATS u', 'LINKS', 'CAP REQ :x', 'KNOCK #Other'):
            sent, refusal = room.to_server(line)
            self.assertEqual((sent, refusal), ('', 'Public chat stays in #RogueFest.'), line)
        # The room's privacy, ChanServ and invitations into a private room are the Grove's to decide.
        for line in ('MODE #RogueFest -s', 'MODE #RogueFest -k k3y', 'MODE #RogueFest +i', 'MODE #roguefest +l 2'):
            self.assertEqual(room.to_server(line), ('', 'Who can find and join #RogueFest is set in Grove admin.'), line)
        self.assertEqual(room.to_server('PRIVMSG ChanServ :REGISTER #RogueFest'), ('', 'ChanServ is not open from Public chat.'))
        self.assertEqual(room.to_server('INVITE Ann #RogueFest'), ('', '#RogueFest is private to this Grove.'))
        self.assertEqual(chat.Room('#RogueFest', 'k3y', False).to_server('INVITE Ann #RogueFest'), ('INVITE Ann #RogueFest', ''))
        self.assertEqual(room.hide(':Ann!a@b MODE #RogueFest +k k3y'), ':Ann!a@b MODE #RogueFest +k ********')

    def test_the_room_is_private_unless_an_owner_opens_it(self):
        joined = lambda nick, names: (f':server 001 {nick} :Welcome\r\n:server 376 {nick} :End\r\n:{nick}!u@h JOIN #RogueFest\r\n'
                                      f':server 353 {nick} = #RogueFest :{names}\r\n:{nick}!u@h MODE #RogueFest +snk fest-key-1\r\n').encode()
        with patch.dict(os.environ, {**ROGUEFEST, 'GROVE_HOST_TOOLS': 'off', 'GROVE_CHAT_KEY': 'fest-key-1'}):
            host, member, _ = self.host_and_member()
            self.assertTrue(member.get('/api/auth/me').json()['public_chat']['private'])
            # The first one in is an operator, and makes the room secret and keyed. The key never reaches the browser.
            _, writer, replies = self.run_chat(member, {'nick': 'Rogue1'}, joined('Rogue1', '@Rogue1'))
            self.assertIn(b'JOIN #RogueFest fest-key-1\r\n', writer.data)
            self.assertIn(b'MODE #RogueFest +snk fest-key-1\r\n', writer.data)
            self.assertNotIn('fest-key-1', str(replies))
            self.assertIn('+snk ********', str(replies))
            # Someone who isn't an operator changes nothing.
            _, writer, _ = self.run_chat(member, {'nick': 'Rogue2'}, joined('Rogue2', '@Rogue1 Rogue2'))
            self.assertIn(b'JOIN #RogueFest fest-key-1\r\n', writer.data)
            self.assertNotIn(b'MODE', writer.data)
            # Only an owner opens the room; then an operator takes the secret and the key off.
            self.assertEqual(member.put('/api/admin/settings', headers=H, json={'chat_privacy': 'open'}).status_code, 403)
            self.assertEqual(host.put('/api/admin/settings', headers=H, json={'chat_privacy': 'nobody'}).status_code, 422)
            saved = host.put('/api/admin/settings', headers=H, json={'chat_privacy': 'open'})
            self.assertEqual(saved.json(), {'space_creation': 'everyone', 'chat_privacy': 'open'})
            self.assertFalse(member.get('/api/auth/me').json()['public_chat']['private'])
            _, writer, _ = self.run_chat(member, {'nick': 'Rogue3'}, joined('Rogue3', '@Rogue3'))
            self.assertIn(b'MODE #RogueFest -sk fest-key-1\r\n', writer.data)
            actions = [a['details'] for a in host.get('/api/admin/activity').json()['items'] if a['action'] == 'grove_setting_changed']
            self.assertEqual(actions, [{'chat_privacy': 'open'}])
        # Without a key from the IRC admin, the Grove makes one and keeps it.
        with patch.dict(os.environ, {**ROGUEFEST, 'GROVE_HOST_TOOLS': 'off'}):
            _, first, _ = self.run_chat(member, {'nick': 'Rogue4'})
            _, again, _ = self.run_chat(member, {'nick': 'Rogue5'})
            with store.db() as c: key = store.grove_setting(c, 'chat_key', '')
            self.assertRegex(key, r'^[0-9a-f]{16}$')
            self.assertIn(f'JOIN #RogueFest {key}\r\n'.encode(), first.data)
            self.assertIn(f'JOIN #RogueFest {key}\r\n'.encode(), again.data)

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
