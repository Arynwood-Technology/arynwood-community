"""Public chat: every member's way into this Grove's IRC room (GROVE_CHAT_CHANNEL).

Unlike the host's IRC page, the browser chooses nothing but a nickname. The server, port and
room come from the Grove's settings, no NickServ password is ever sent, and the server's
own SOCKS5_PROXY is the only proxy. Every member connects from this server's address, so
each may hold only a couple of connections at once.

A member stays in the room: commands that would join, list or message other channels are
refused (Room). Unless an owner opens it in Grove admin, the room is also private on the IRC
network: hidden from its channel list and locked with a key only this Grove knows."""
import asyncio
import os
import re
import secrets
from collections import Counter
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from backend.community.auth import user
from backend.community.store import db, grove_setting, public_chat, setting
from backend.routers import irc

router = APIRouter()
NICK = re.compile(r'[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}-]{0,29}')
PER_MEMBER = 2
open_by_member = Counter()
# A channel key: printable, without spaces or commas.
KEY = re.compile(r'[!-+\--~]{1,23}')
CHANNEL = tuple('#&+!')
# Channel modes a member's operator may change: who is banned, opped or voiced, never who can find or join.
MEMBER_MODES = set('+-bovhqeI')


def room_key(c):
    """The room's key: GROVE_CHAT_KEY when the IRC admin set one, else one this Grove made for itself."""
    chosen = setting('CHAT_KEY').strip()
    if KEY.fullmatch(chosen): return chosen
    c.execute('INSERT OR IGNORE INTO grove_settings VALUES (?,?)', ('chat_key', secrets.token_hex(8)))
    return grove_setting(c, 'chat_key', '')


class Room:
    """Keeps one member's connection in the Grove's room, and the room private when it should be.

    Members always join with the key, so turning privacy on or off never shuts them out. Whenever
    a member's connection is an operator in the room (the first one into an empty room is), it
    sets the room secret, keyed and closed to outside messages (+snk), or takes off the secret and
    the key once an owner has opened the room. The key itself never reaches the browser."""

    def __init__(self, channel, key, private):
        self.channel, self.key, self.private = channel, key, private
        self.me, self.settled = '', False

    def join(self): return f'{self.channel} {self.key}'

    def ours(self, target): return target.lower() == self.channel.lower()

    def to_server(self, line):
        """(line to send, refusal): a member's command as it goes to the IRC server, or why it doesn't."""
        msg = irc.parse_irc(line)
        command, params = msg['command'], msg['params']
        first = params[0] if params else ''
        stay = f'Public chat stays in {self.channel}.'
        nick_or_room = lambda t: self.ours(t) or (t[:1] not in CHANNEL + tuple('@%~') and not set('*?') & set(t))
        if command in ('NICK', 'AWAY', 'PING', 'PONG', 'QUIT', 'ISON', 'USERHOST'): return line, ''
        if command in ('PRIVMSG', 'NOTICE'):
            # ChanServ could register the room and change who can join it; that's for the network's admins.
            if any(t.lower() == 'chanserv' for t in first.split(',')): return '', 'ChanServ is not open from Public chat.'
            return (line, '') if first and all(nick_or_room(t) for t in first.split(',')) else ('', stay)
        if command == 'JOIN':
            return (f'JOIN {self.join()}', '') if first and all(self.ours(t) for t in first.split(',')) else ('', stay)
        if command in ('PART', 'NAMES', 'TOPIC', 'KICK'):
            return (line, '') if first and all(self.ours(t) for t in first.split(',')) else ('', stay)
        if command == 'WHO': return (line, '') if first and nick_or_room(first) else ('', stay)
        if command == 'WHOIS': return (line, '') if params and all(nick_or_room(t) for t in params) else ('', stay)
        if command == 'MODE':
            if first and not self.ours(first): return (line, '') if first[:1] not in CHANNEL else ('', stay)
            if len(params) < 2 or set(params[1]) <= MEMBER_MODES: return line, ''
            return '', f'Who can find and join {self.channel} is set in Grove admin.'
        if command == 'INVITE' and len(params) > 1 and self.ours(params[1]):
            return ('', f'{self.channel} is private to this Grove.') if self.private else (line, '')
        return '', stay

    def hide(self, text): return text.replace(self.key, '********') if self.key else text

    def from_server(self, msg):
        """Lines to send back after a line from the IRC server: the room's privacy, once this connection may set it."""
        command, params = msg['command'], msg['params']
        if command.isdigit() and params: self.me = params[0]
        elif command == 'NICK' and msg['nick'] == self.me and params: self.me = params[0]
        if self.settled or not self.me: return []
        operator = False
        if command == '353' and len(params) > 3 and self.ours(params[2]):
            operator = any(name.lstrip('~&@%+') == self.me and set(name[:len(name) - len(name.lstrip('~&@%+'))]) & set('~&@') for name in params[3].split())
        elif command == 'MODE' and len(params) > 2 and self.ours(params[0]):
            operator = params[1].startswith('+') and set(params[1]) & set('oqa') and self.me in params[2:]
        if not operator: return []
        self.settled = True
        return [f'MODE {self.channel} +snk {self.key}' if self.private else f'MODE {self.channel} -sk {self.key}']


@router.websocket('/ws')
async def chat_ws(ws: WebSocket, current=Depends(user)):
    settings = public_chat()
    await ws.accept()
    if not settings:
        await ws.send_json({'type': 'error', 'message': 'Public chat is switched off on this Grove.'})
        await ws.close()
        return
    if open_by_member[current['id']] >= PER_MEMBER:
        await ws.send_json({'type': 'error', 'message': 'Public chat is already open in two other windows. Close one and connect again.'})
        await ws.close()
        return
    open_by_member[current['id']] += 1
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=30)
        nick = str(first.get('nick', '')).strip()
        if not NICK.fullmatch(nick):
            await ws.send_json({'type': 'error', 'message': 'Choose a nickname of up to 30 letters, numbers and - _, starting with a letter.'})
            return
        with db() as c:
            room = Room(settings['channel'], room_key(c), grove_setting(c, 'chat_privacy', 'private') == 'private')
        port = settings['port']
        await irc.relay(ws, settings['server'], port, port in irc.TLS_PORTS, os.getenv('SOCKS5_PROXY', ''),
                        nick, '', [room.join()], 'Arynwood Grove', room)
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, AttributeError):
        pass
    finally:
        open_by_member[current['id']] -= 1
        if not open_by_member[current['id']]: del open_by_member[current['id']]
