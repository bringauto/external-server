import threading

from external_server.models.structures import TimeoutType as _TimeoutType
from external_server.models.events import (
    EventType as _EventType,
    EventQueue as _EventQueue,
)


class TimeoutChecker:
    """A class that provides a mechanism to check for a timeouts in a single or multiple threaded operations."""

    DEFAULT_COUNTER_VALUE = 0

    def __init__(
        self, timeout_type: _TimeoutType, timeout: float, event_queue: _EventQueue
    ) -> None:
        """
        Initializes a new instance of the Checker class with the specified timeout type to signal when timeout occurs.

        Args:
        - timeout_type (TimeoutType): TimeoutType to put onto event queue when timeout occurs
        """
        self._timeout_event = threading.Event()
        self._timeout_type = timeout_type
        self._timeout = timeout
        self._event_queue = event_queue
        self._counter = TimeoutChecker.DEFAULT_COUNTER_VALUE

    @property
    def counter(self) -> int:
        """Expected counter value of the next message to be received."""
        return self._counter

    @property
    def timeout(self) -> float:
        """Time period in seconds after which timeout is considered to occur."""
        return self._timeout

    @property
    def timeout_event(self) -> threading.Event:
        return self._timeout_event

    def timeout_occurred(self) -> bool:
        """Returns True if timeout occurred, False otherwise."""
        return self._timeout_event.is_set()

    def set_timeout(self) -> None:
        """Puts event to event queue."""
        self._timeout_event.set()
        self._event_queue.add(event_type=_EventType.TIMEOUT_OCCURRED, data=self._timeout_type)
