from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


CHANNELS = ("telemetry", "decisions", "reasoning", "alerts", "approvals")


@dataclass
class Event:
    channel: str
    payload: dict[str, Any]
    id: int = 0


class EventBus:
    """In-process fan-out. Each subscription gets its own bounded asyncio.Queue; slow consumers
    lose oldest events rather than stalling producers."""

    def __init__(self, maxsize: int = 256) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = {c: set() for c in CHANNELS}
        self._lock = asyncio.Lock()
        self._counter = 0
        self._maxsize = maxsize

    async def subscribe(self, channel: str) -> asyncio.Queue[Event]:
        if channel not in self._subscribers:
            raise ValueError(f"unknown channel: {channel}")
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._maxsize)
        async with self._lock:
            self._subscribers[channel].add(queue)
        return queue

    async def unsubscribe(self, channel: str, queue: asyncio.Queue[Event]) -> None:
        async with self._lock:
            self._subscribers.get(channel, set()).discard(queue)

    def publish(self, channel: str, payload: dict[str, Any]) -> None:
        """Fire-and-forget publish. Safe to call from sync code running in an asyncio context."""
        if channel not in self._subscribers:
            return
        self._counter += 1
        event = Event(channel=channel, payload=payload, id=self._counter)
        for queue in list(self._subscribers[channel]):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest then insert — never block the producer.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    async def stream(self, channel: str) -> AsyncIterator[Event]:
        queue = await self.subscribe(channel)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            await self.unsubscribe(channel, queue)


@dataclass
class BusHolder:
    bus: EventBus = field(default_factory=EventBus)


_holder = BusHolder()


def get_bus() -> EventBus:
    return _holder.bus


def reset_bus_for_tests() -> None:
    _holder.bus = EventBus()
