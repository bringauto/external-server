from queue import Queue as _Queue
import threading
from typing import Any
import dataclasses
from enum import Enum, auto


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
    RECEIVED_MESSAGE = auto()
    MQTT_BROKER_DISCONNECTED = auto()
    TIMEOUT_OCCURRED = auto()  # data = TimeoutType


@dataclasses.dataclass(slots=True)
class Event:
    event: EventType
    data: Any | None = None


class EventQueueSingleton(metaclass=SingletonMeta):
    __slots__ = "_queue"

    def __init__(self) -> None:
        self._queue: _Queue[Any] = _Queue()

    def add_event(self, event_type: EventType, data: Any | None = None) -> None:
        self._queue.put(Event(event=event_type, data=data))

    def get(self, *args, **kwargs) -> Event:
        return self._queue.get(*args, **kwargs)

    def clear(self) -> None:
        while self._queue.qsize():
            _ = self._queue.get()
