import asyncio
import json
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def one_line(value) -> str:
    """Strip CR/LF so a browser value can never smuggle extra IRC commands."""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def parse_irc(raw: str) -> dict:
    """Parse a raw IRC line into {raw, prefix, nick, command, params, trailing}."""
    prefix = ""
    rest = raw
    if raw.startswith(":"):
        idx = raw.find(" ")
        prefix = raw[1:idx]
        rest = raw[idx + 1:]

    parts = rest.split(" ", 1)
    command = parts[0].upper()
    trailing = ""
    params_raw = parts[1] if len(parts) > 1 else ""

    if " :" in params_raw:
        idx = params_raw.find(" :")
        trailing = params_raw[idx + 2:]
        params_raw = params_raw[:idx]
    elif params_raw.startswith(":"):
        trailing = params_raw[1:]
        params_raw = ""

    params = params_raw.split() if params_raw else []
    if trailing:
        params.append(trailing)

    nick = prefix.split("!")[0] if "!" in prefix else prefix

    return {
        "raw": raw,
        "prefix": prefix,
        "nick": nick,
        "command": command,
        "params": params,
        "trailing": trailing,
    }


@router.get("/client-config")
async def get_client_config():
    """Return the personal IRC client connection config."""
    path = os.path.join(BASE_DIR, "config", "irc_client.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


@router.post("/client-config")
async def save_client_config(cfg: dict):
    """Save the personal IRC client connection config."""
    path = os.path.join(BASE_DIR, "config", "irc_client.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # May hold a NickServ password: keep it readable by this user only.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    return {"ok": True}


@router.websocket("/ws")
async def irc_ws(ws: WebSocket):
    """WebSocket relay: bridges a personal IRC session between the browser UI and the IRC server."""
    await ws.accept()
    irc_writer = None
    irc_reader = None

    async def send(data: dict):
        """Send JSON to the browser WebSocket, silently swallowing send errors."""
        try:
            await ws.send_json(data)
        except Exception:
            pass

    try:
        config = await asyncio.wait_for(ws.receive_json(), timeout=30)
        host          = one_line(config.get("host", "irc.libera.chat"))
        port          = int(config.get("port", 6667))
        nick          = one_line(config.get("nick", "arynwood-hub")).replace(" ", "")
        nick_password = one_line(config.get("nick_password", ""))
        channels      = [one_line(c).replace(" ", "") for c in config.get("channels", []) if one_line(c)]
        realname      = one_line(config.get("realname", "Arynwood Community"))
        if not host or not nick or not 0 < port < 65536:
            await send({"type": "error", "message": "Enter a server, port and nickname."})
            return

        # If frontend didn't send a password, look it up from the client config file
        if not nick_password:
            _client_cfg_path = os.path.join(BASE_DIR, "config", "irc_client.json")
            if os.path.exists(_client_cfg_path):
                with open(_client_cfg_path) as _f:
                    _client_cfg = json.load(_f)
                if _client_cfg.get("nick") == nick:
                    nick_password = _client_cfg.get("nick_password", "")

        use_ssl = port in (6697, 6660, 7000, 7070) or config.get("ssl", False)
        socks5  = config.get("socks5_proxy", os.getenv("SOCKS5_PROXY", ""))
        if socks5:
            await send({"type": "status", "message": f"Connecting to {host}:{port} via proxy {socks5}…"})
        else:
            await send({"type": "status", "message": f"Connecting to {host}:{port}…"})
        try:
            import ssl as _ssl
            ssl_ctx = _ssl.create_default_context() if use_ssl else None
            if socks5:
                from python_socks.async_.asyncio import Proxy as _Proxy
                _proxy_url = socks5 if "://" in socks5 else f"socks5://{socks5}"
                _sock = await asyncio.wait_for(
                    _Proxy.from_url(_proxy_url).connect(dest_host=host, dest_port=port),
                    timeout=15,
                )
                if use_ssl:
                    irc_reader, irc_writer = await asyncio.open_connection(
                        ssl=ssl_ctx, sock=_sock, server_hostname=host
                    )
                else:
                    irc_reader, irc_writer = await asyncio.open_connection(sock=_sock)
            else:
                irc_reader, irc_writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port, ssl=ssl_ctx), timeout=15
                )
        except asyncio.TimeoutError:
            await send({"type": "error", "message": f"Timed out connecting to {host}:{port}"})
            return
        except OSError as e:
            await send({"type": "error", "message": f"Could not connect to {host}:{port} — {e}"})
            return

        irc_writer.write(f"NICK {nick}\r\nUSER {nick} 0 * :{realname}\r\n".encode())
        await irc_writer.drain()

        registered = False
        channel_joined = False
        stop_event = asyncio.Event()

        async def read_irc():
            """Pump IRC server → WebSocket: handle PING, auth, JOIN, and forward all messages."""
            nonlocal registered, channel_joined, nick
            try:
                while not stop_event.is_set():
                    try:
                        line = await asyncio.wait_for(irc_reader.readline(), timeout=300)
                    except asyncio.TimeoutError:
                        irc_writer.write(b"PING :keepalive\r\n")
                        await irc_writer.drain()
                        continue

                    if not line:
                        await send({"type": "disconnect", "message": "Server closed the connection"})
                        break

                    text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not text:
                        continue

                    msg = parse_irc(text)

                    if msg["command"] == "PING":
                        pong_arg = msg["params"][0] if msg["params"] else ""
                        irc_writer.write(f"PONG :{pong_arg}\r\n".encode())
                        await irc_writer.drain()
                        continue

                    if msg["command"] in ("376", "422") and not registered:
                        registered = True
                        if nick_password:
                            irc_writer.write(f"PRIVMSG NickServ :IDENTIFY {nick_password}\r\n".encode())
                            await irc_writer.drain()
                            async def _ws_delayed_join():
                                """Wait 15 s for NickServ auth to complete before joining channels."""
                                await asyncio.sleep(15)
                                nonlocal channel_joined
                                if not channel_joined:
                                    channel_joined = True
                                    for ch in channels:
                                        irc_writer.write(f"JOIN {ch}\r\n".encode())
                                    await irc_writer.drain()
                            asyncio.create_task(_ws_delayed_join())
                        else:
                            channel_joined = True
                            for ch in channels:
                                irc_writer.write(f"JOIN {ch}\r\n".encode())
                            await irc_writer.drain()

                    # 401 = no such nick (NickServ down) — join anyway rather than hanging
                    if nick_password and not channel_joined and msg["command"] == "401":
                        target = msg["params"][1] if len(msg["params"]) > 1 else ""
                        if target.lower() == "nickserv":
                            channel_joined = True
                            for ch in channels:
                                irc_writer.write(f"JOIN {ch}\r\n".encode())
                            await irc_writer.drain()

                    if nick_password and msg["command"] == "NOTICE" and msg["nick"].lower() == "nickserv":
                        notice = (msg["params"][-1] if msg["params"] else "").lower()
                        if any(p in notice for p in ("password accepted", "you are now identified", "you are now recognized", "identified for")):
                            irc_writer.write(b"PRIVMSG HostServ :ON\r\n")
                            if not channel_joined:
                                channel_joined = True
                                for ch in channels:
                                    irc_writer.write(f"JOIN {ch}\r\n".encode())
                            await irc_writer.drain()

                    # Only pick an alternate nick during registration; later
                    # collisions come from /nick and are reported to the user.
                    if msg["command"] == "433" and not registered:
                        new_nick = nick + "_"
                        nick = new_nick
                        irc_writer.write(f"NICK {new_nick}\r\n".encode())
                        await irc_writer.drain()
                        await send({"type": "status", "message": f"Nick in use, trying {new_nick}"})
                        # If no password flow, join now with the new nick
                        if not nick_password and not channel_joined:
                            channel_joined = True
                            for ch in channels:
                                irc_writer.write(f"JOIN {ch}\r\n".encode())
                            await irc_writer.drain()

                    await send({"type": "irc", "msg": msg})
            finally:
                stop_event.set()

        async def read_ws():
            """Pump WebSocket → IRC server: forward raw IRC commands from the browser."""
            try:
                while not stop_event.is_set():
                    try:
                        data = await asyncio.wait_for(ws.receive_json(), timeout=1)
                    except asyncio.TimeoutError:
                        continue
                    raw_cmd = one_line(data.get("cmd", ""))
                    if raw_cmd and irc_writer and not irc_writer.is_closing():
                        irc_writer.write(f"{raw_cmd}\r\n".encode())
                        await irc_writer.drain()
            except WebSocketDisconnect:
                pass
            finally:
                stop_event.set()

        task_irc = asyncio.create_task(read_irc())
        task_ws  = asyncio.create_task(read_ws())

        await asyncio.wait([task_irc, task_ws], return_when=asyncio.FIRST_COMPLETED)

        task_irc.cancel()
        task_ws.cancel()
        await asyncio.gather(task_irc, task_ws, return_exceptions=True)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await send({"type": "error", "message": str(e)})
    finally:
        if irc_writer and not irc_writer.is_closing():
            try:
                irc_writer.write(b"QUIT :Arynwood Hub disconnected\r\n")
                await irc_writer.drain()
                irc_writer.close()
                await irc_writer.wait_closed()
            except Exception:
                pass

