"""Live change notices, so every member's open page refreshes as soon as anyone edits a space.

A notice carries no content, only "this space changed". Pages refetch through the normal,
permission-checked endpoints, so private entries and removed members are handled there.
Fan-out is in memory: run the service as one process (one uvicorn worker), as SQLite needs.
"""
import asyncio
import secrets
import threading
from collections import defaultdict

from starlette.concurrency import run_in_threadpool

# Streams end and the browser reconnects (EventSource does this by itself), so a shutdown
# or a revoked session never waits on a long-lived connection.
STREAM_SECONDS = 30
HEARTBEAT_SECONDS = 15
RETRY_MS = 1500
MAX_STREAMS_PER_USER = 12

BOOT = secrets.token_hex(4)
# Every open preview of the Grove's websites, whatever space keeps them: a website file or a note changed.
WEBSITE = 'website'
_lock = threading.Lock()
_revisions: dict[str, int] = defaultdict(int)
_subscribers: dict[str, set['Subscriber']] = defaultdict(set)


class Subscriber:
    def __init__(self, space, user, loop, counted=True):
        self.space, self.user, self.loop, self.counted = space, user, loop, counted
        self.queue: asyncio.Queue[str] = asyncio.Queue()


def revision(space):
    with _lock: return f'{BOOT}-{_revisions[space]}'


def publish(space, only_user=None):
    """Tell the space's open pages it changed. Call after the change has committed.

    only_user limits the notice to one member's pages (a private entry's author)."""
    with _lock:
        _revisions[space] += 1
        current = f'{BOOT}-{_revisions[space]}'
        targets = [s for s in _subscribers.get(space, ()) if only_user is None or s.user == only_user]
    for subscriber in targets:
        try: subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, current)
        except RuntimeError: pass  # that stream's event loop has already closed


def streams_for(user):
    with _lock: return sum(1 for group in _subscribers.values() for s in group if s.user == user and s.counted)


def _subscribe(space, user, counted=True):
    subscriber = Subscriber(space, user, asyncio.get_running_loop(), counted)
    with _lock: _subscribers[space].add(subscriber)
    return subscriber


def _unsubscribe(subscriber):
    with _lock:
        group = _subscribers.get(subscriber.space)
        if group is not None:
            group.discard(subscriber)
            if not group: del _subscribers[subscriber.space]


def _event(rev, name):
    return f'id: {rev}\nevent: {name}\ndata: {{}}\n\n'


async def stream(space, user, last_event_id, allowed, also=()):
    """Server-sent events for one member's page. `allowed` re-checks the session and membership
    (blocking; run off the event loop) before every message, so a removed member or a
    signed-out session stops receiving notices. Notices for the keys in `also` come on the same
    connection, named by their key, so a page needs no connection of its own for them: browsers
    keep only six open to a server reached without HTTP/2."""
    subscriber = _subscribe(space, user)
    extra = [_subscribe(key, user, counted=False) for key in also]
    loop, waiting = asyncio.get_running_loop(), {}
    try:
        current = revision(space)
        # A reconnect that missed a change is told at once; a first connect has just loaded.
        changed = bool(last_event_id) and last_event_id != current
        yield f'retry: {RETRY_MS}\n' + _event(current, 'changed' if changed else 'ready')
        deadline = loop.time() + STREAM_SECONDS
        waiting = {asyncio.ensure_future(s.queue.get()): s for s in (subscriber, *extra)}
        while (remaining := deadline - loop.time()) > 0:
            done, _ = await asyncio.wait(waiting, timeout=min(HEARTBEAT_SECONDS, remaining), return_when=asyncio.FIRST_COMPLETED)
            if not await run_in_threadpool(allowed): return
            if not done: yield ': still here\n\n'; continue
            for task in done:
                s, rev = waiting.pop(task), task.result()
                while not s.queue.empty(): rev = s.queue.get_nowait()  # one refetch per burst
                # The page's own notices carry the revision it resumes from; the others are only a nudge.
                yield _event(rev, 'changed') if s is subscriber else f'event: {s.space}\ndata: {{}}\n\n'
                waiting[asyncio.ensure_future(s.queue.get())] = s
    finally:
        for task in waiting: task.cancel()
        for s in (subscriber, *extra): _unsubscribe(s)
