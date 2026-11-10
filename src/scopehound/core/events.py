"""Barramento de eventos em memória (alimenta o SSE e a CLI)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def publish(self, channel: str, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(channel, ())):
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[channel].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[channel].discard(queue)
