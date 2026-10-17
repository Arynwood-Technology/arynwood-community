"""
P2P Chat router — bridges the NKN network to the frontend via WebSocket.

The NKN bridge (nkn/bridge.js) is spawned as a subprocess; it communicates
with this router via JSON lines on stdin/stdout.  All connected browser clients
share a single NKN identity per backend process.
"""

import asyncio
import json
import logging
import os
from typing import Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bridge state (module-level singletons)
# ---------------------------------------------------------------------------

_bridge_proc: Optional[asyncio.subprocess.Process] = None
_bridge_addr: Optional[str] = None
_bridge_connected: bool = False
_ws_clients: Set[WebSocket] = set()

BRIDGE_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "nkn", "bridge.js"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _broadcast(msg: dict) -> None:
    """Send a JSON message to all connected WebSocket clients, pruning dead connections."""
    dead: Set[WebSocket] = set()
    for ws in list(_ws_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


async def _read_bridge_output(proc: asyncio.subprocess.Process) -> None:
    """Read JSON-line output from the NKN bridge and broadcast each event to clients."""
    global _bridge_addr, _bridge_connected
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        try:
            data = json.loads(line.decode().strip())
            if data.get("type") == "connected":
                _bridge_addr = data.get("addr")
                _bridge_connected = True
            await _broadcast(data)
        except Exception as e:
            logger.warning("Bridge read error: %s", e)
    _bridge_connected = False
    _bridge_addr = None
    await _broadcast({"type": "disconnected"})


async def _log_bridge_stderr(proc: asyncio.subprocess.Process) -> None:
    """Forward bridge stderr to the Python logger, demoting NKN reconnection noise to debug."""
    while True:
        line = await proc.stderr.readline()
        if not line:
            break
        text = line.decode().rstrip()
        # NKN SDK reconnection noise — demote to debug
        if "WebSocket unexpectedly closed" in text or "WebSocket error" in text:
            logger.debug("NKN bridge: %s", text)
        else:
            logger.warning("NKN bridge: %s", text)


async def _start_bridge() -> None:
    """Spawn the NKN bridge.js subprocess if it isn't already running."""
    global _bridge_proc, _bridge_connected, _bridge_addr
    if _bridge_proc and _bridge_proc.returncode is None:
        return  # already running

    if not os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(BRIDGE_SCRIPT)), "node_modules", "nkn-sdk")):
        await _broadcast({"type": "error", "message": "Messaging is not installed here. On a server, update the Grove to a newer release; in a source checkout, run ./setup.sh."})
        return
    identifier = os.environ.get("NKN_IDENTIFIER", "arynwood-hub")
    env = {**os.environ, "NKN_IDENTIFIER": identifier}

    bridge_dir = os.path.dirname(os.path.abspath(BRIDGE_SCRIPT))
    repo_root  = os.path.join(bridge_dir, "..")

    try:
        _bridge_proc = await _spawn_bridge(env, repo_root)
    except FileNotFoundError:
        await _broadcast({"type": "error", "message": "Messaging needs Node.js. Install Node.js and try again."})
        return
    asyncio.create_task(_read_bridge_output(_bridge_proc))
    asyncio.create_task(_log_bridge_stderr(_bridge_proc))


async def _spawn_bridge(env, repo_root):
    return await asyncio.create_subprocess_exec(
        "node",
        os.path.abspath(BRIDGE_SCRIPT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,  # 10 MB — supports base64-encoded images up to ~7.5 MB
        env=env,
        cwd=os.path.abspath(repo_root),
    )


async def _send_to_bridge(cmd: dict) -> bool:
    """Send a fully-formed command dict to the bridge process."""
    if not _bridge_proc or _bridge_proc.returncode is not None:
        return False
    _bridge_proc.stdin.write((json.dumps(cmd) + "\n").encode())
    await _bridge_proc.stdin.drain()
    return True


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def p2p_status():
    """Return NKN bridge connection state and wallet address."""
    return {
        "connected": _bridge_connected,
        "addr":      _bridge_addr,
        "running":   _bridge_proc is not None and _bridge_proc.returncode is None,
    }


@router.post("/start")
async def p2p_start():
    """Start the NKN bridge subprocess."""
    await _start_bridge()
    return {"started": True}


class WalletImport(BaseModel):
    seed: Optional[str] = Field(default=None, max_length=128)           # 64-char hex seed
    wallet_json: Optional[str] = Field(default=None, max_length=20000)  # full wallet JSON string


@router.get("/wallet")
async def p2p_wallet_info():
    """Return current wallet address (never the private key)."""
    wallet_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "nkn", "wallet.json")
    )
    if os.path.exists(wallet_file):
        try:
            data = json.loads(open(wallet_file).read())
            return {"has_wallet": True, "address": data.get("Address") or data.get("address")}
        except Exception:
            pass
    return {"has_wallet": False, "address": None}


@router.post("/wallet")
async def p2p_wallet_import(body: WalletImport):
    """Import a wallet by seed or full wallet JSON. Restarts the bridge if running."""
    from fastapi import HTTPException

    if not body.seed and not body.wallet_json:
        raise HTTPException(status_code=400, detail="Paste a secret key or an identity file.")

    wallet_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "nkn", "wallet.json")
    )
    os.makedirs(os.path.dirname(wallet_file), exist_ok=True)

    if body.wallet_json:
        try:
            parsed = json.loads(body.wallet_json)
        except Exception:
            raise HTTPException(status_code=400, detail="That identity file could not be read.")
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="That identity file could not be read.")
    else:
        seed = (body.seed or "").strip().lower()
        if len(seed) != 64 or not all(c in "0123456789abcdef" for c in seed):
            raise HTTPException(status_code=400, detail="A secret key is 64 characters of 0-9 and a-f.")
        parsed = {"__seed": seed}
    # The wallet holds a private key: write it readable by this user only.
    fd = os.open(wallet_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(parsed, f)

    # Restart bridge if running so new wallet takes effect immediately
    was_running = _bridge_proc is not None and _bridge_proc.returncode is None
    if was_running:
        await p2p_stop()
        await asyncio.sleep(0.3)
        await _start_bridge()

    return {"ok": True, "restarted": was_running}


@router.post("/stop")
async def p2p_stop():
    """Terminate the NKN bridge subprocess gracefully."""
    global _bridge_proc, _bridge_connected, _bridge_addr
    if _bridge_proc and _bridge_proc.returncode is None:
        _bridge_proc.terminate()
        try:
            await asyncio.wait_for(_bridge_proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            _bridge_proc.kill()
    _bridge_connected = False
    _bridge_addr = None
    return {"stopped": True}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def p2p_ws(websocket: WebSocket):
    """WebSocket endpoint for real-time NKN send/receive and bridge control."""
    await websocket.accept()
    _ws_clients.add(websocket)

    await websocket.send_json({
        "type":      "status",
        "connected": _bridge_connected,
        "addr":      _bridge_addr,
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            cmd_type = data.get("type")

            if cmd_type == "start":
                await _start_bridge()

            elif cmd_type == "stop":
                await p2p_stop()

            elif cmd_type == "send":
                dest    = data.get("dest", "").strip()
                content = data.get("content") or data.get("text", "")
                if dest and content:
                    ok = await _send_to_bridge({
                        "type":        "send",
                        "dest":        dest,
                        "content":     content,
                        "contentType": data.get("contentType", "text"),
                        "id":          data.get("id", ""),
                    })
                    if not ok:
                        await websocket.send_json({
                            "type":    "error",
                            "message": "You are offline. Select Go online first.",
                        })
                else:
                    await websocket.send_json({
                        "type":    "error",
                        "message": "send requires dest and content",
                    })

            elif cmd_type == "send_multi":
                dests   = [d.strip() for d in data.get("dests", []) if d.strip()]
                content = data.get("content") or data.get("text", "")
                if dests and content:
                    bridge_ok = True
                    for dest in dests:
                        ok = await _send_to_bridge({
                            "type":        "send",
                            "dest":        dest,
                            "content":     content,
                            "contentType": data.get("contentType", "text"),
                            "id":          data.get("id", ""),
                        })
                        if not ok:
                            bridge_ok = False
                            break
                    if not bridge_ok:
                        await websocket.send_json({
                            "type":    "error",
                            "message": "You are offline. Select Go online first.",
                        })
                else:
                    await websocket.send_json({
                        "type":    "error",
                        "message": "send_multi requires dests (list) and content",
                    })

    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)
