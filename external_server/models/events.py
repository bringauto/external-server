from queue import Queue as _Queue
from typing import Any
import dataclasses
from enum import Enum, auto


from external_server.logs import CarLogger as _CarLogger


logger = _CarLogger()


class EventType(Enum):
    COMMAND_AVAILABLE = auto()
    CAR_MESSAGE_AVAILABLE = auto()
    MQTT_BROKER_DISCONNECTED = auto()
    TIMEOUT_OCCURRED = auto()
    SERVER_STOPPED = auto()


@dataclasses.dataclass(slots=True, frozen=True)
class Event:
    """A class representing an event in the event queue.

    It contains the event type and optionally a data.
    """

    event_type: EventType
    data: Any | None = None


class EventQueue:
    """An event queue used for synchronization of different parts of the system."""

    __slots__ = "_queue", "_car"

    def __init__(self, car: str = "") -> None:
        self._queue: _Queue[Any] = _Queue()
        self._car = car
        logger.debug(f"Event queue '{id(self)}' has been created.", self._car)

    def add(self, event_type: EventType, data: Any = None) -> None:
        """Add new item to the queue."""
        self._queue.put(Event(event_type=event_type, data=data))
        msg = f"Adding new event: {event_type}"
        if data:
            msg += f" with data: {data}"
        logger.debug(msg, self._car)

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
        logger.debug("Event queue has been emptied.", self._car)
