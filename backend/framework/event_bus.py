import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional, Set

EventHandler = Callable[..., Awaitable[None]]


class EventBus:
    def __init__(self):
        self._handlers: Dict[str, Set[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler):
        if event_type not in self._handlers:
            self._handlers[event_type] = set()
        self._handlers[event_type].add(handler)
        def unsubscribe():
            self._handlers[event_type].discard(handler)
        return unsubscribe

    async def publish(self, event_type: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        handlers = self._handlers.get(event_type, set())
        if not handlers:
            return
        payload = dict(data or {})
        payload.update(kwargs)
        tasks = [handler(_event_type=event_type, **payload) for handler in handlers]
        await asyncio.gather(*tasks, return_exceptions=True)

    def clear(self) -> None:
        self._handlers.clear()


global_event_bus = EventBus()
