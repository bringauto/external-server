from queue import Queue as _Queue
import threading
from typing import Any
import dataclasses
from enum import Enum, auto
import logging.config
import json

logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


class SingletonMeta(type):
    """
    This is a thread-safe implementation of Singleton.
    """

    _instances: dict = dict()
    _lock: threading.Lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        """
        Possible changes to the value of the `__init__` argument do not affect
        the returned instance.
        """
        with cls._lock:
            if cls not in cls._instances:
                instance = super().__call__(*args, **kwargs)
                cls._instances[cls] = instance
        return cls._instances[cls]


class EventType(Enum):
    COMMAND_AVAILABLE = auto()  # data = module number
    CAR_MESSAGE_AVAILABLE = auto()
    MQTT_BROKER_DISCONNECTED = auto()
    TIMEOUT_OCCURRED = auto()  # data = TimeoutType


@dataclasses.dataclass(slots=True)
class Event:
    """A class representing an event in the event queue.

    It contains the event type and data, if required.
    """

    event: EventType
    data: Any | None = None


class EventQueueSingleton(metaclass=SingletonMeta):
    """An event queue used for synchronization of different parts of the system."""

    __slots__ = "_queue"

    def __init__(self) -> None:
        self._queue: _Queue[Any] = _Queue()

    def add(self, event_type: EventType, data: Any = None) -> None:
        """Add new item to the queue."""
        self._queue.put(Event(event=event_type, data=data))

    def empty(self) -> bool:
        """Return True if the queue is empty, False otherwise."""
        return self._queue.empty()

    def get(self, *args, **kwargs) -> Event:
        """Return and remove next item from the queue."""
        return self._queue.get(*args, **kwargs)

    def clear(self) -> None:
        """Remove all items from the queue without returning them."""
        while self._queue.qsize():
            _ = self._queue.get()
