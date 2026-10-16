"""Public chat: every member's way into this Grove's IRC room (GROVE_CHAT_CHANNEL).

Unlike the host's IRC page, the browser chooses nothing but a nickname. The server, port and
room come from the Grove's settings, no NickServ password is ever sent, and the server's
own SOCKS5_PROXY is the only proxy. Every member connects from this server's address, so
each may hold only a couple of connections at once."""
import asyncio
import os
import re
from collections import Counter
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from backend.community.auth import user
from backend.community.store import public_chat
from backend.routers import irc

router = APIRouter()
NICK = re.compile(r'[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}-]{0,29}')
PER_MEMBER = 2
open_by_member = Counter()


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
        port = settings['port']
        await irc.relay(ws, settings['server'], port, port in irc.TLS_PORTS, os.getenv('SOCKS5_PROXY', ''),
                        nick, '', [settings['channel']], 'Arynwood Grove')
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, AttributeError):
        pass
    finally:
        open_by_member[current['id']] -= 1
        if not open_by_member[current['id']]: del open_by_member[current['id']]
