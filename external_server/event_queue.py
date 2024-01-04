import queue
from typing import Any
from dataclasses import dataclass
from enum import Enum, auto

from external_server.utils import SingletonMeta


class EventType(Enum):
    COMMAND_AVAILABLE = auto()  # data = module number
    RECEIVED_MESSAGE = auto()
    MQTT_BROKER_DISCONNECTED = auto()
    TIMEOUT_OCCURRED = auto()  # data = TimeoutType


@dataclass(slots=True)
class Event:
    event: EventType
    data: Any | None = None


class EventQueueSingleton(metaclass=SingletonMeta):
    __slots__ = "_queue"

    def __init__(self) -> None:
        self._queue = queue.Queue()

    def add_event(self, event_type: EventType, data: Any | None = None) -> None:
        self._queue.put(Event(event=event_type, data=data))

    def get(self, *args, **kwargs) -> Event:
        return self._queue.get(*args, **kwargs)

    def clear(self) -> None:
        while self._queue.qsize():
            _ = self._queue.get()
