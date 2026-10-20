"""Resumable snapshot feed: reconnect always receives current local state."""

import asyncio
from hashlib import sha256
import json

from turnlab.storage import ReportStore


async def stream_reports(store: ReportStore, disconnected, *, interval: float = 1):
    previous = None
    ticks = 0
    while not await disconnected():
        try:
            snapshot = await asyncio.to_thread(store.summaries)
            payload = json.dumps(snapshot, sort_keys=True)
            version = sha256(payload.encode()).hexdigest()
            if version != previous:
                yield f"id: {version}\nevent: runs\ndata: {payload}\n\n"
                previous = version
            elif ticks % 15 == 0:
                yield ": heartbeat\n\n"
        except OSError:
            yield 'event: feed_error\ndata: {"message":"Local reports could not be read"}\n\n'
        ticks += 1
        await asyncio.sleep(interval)
