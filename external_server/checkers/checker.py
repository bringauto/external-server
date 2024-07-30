import threading
import logging

from external_server.models.structures import TimeoutType as _TimeoutType
from external_server.models.event_queue import (
    EventQueueSingleton as _EventQueueSingleton,
    EventType as _EventType
)



class Checker:
    """
    A class that provides a mechanism to check for a timeout in a threaded operation.
    """

    DEFAULT_COUNTER_VALUE = 0

    def __init__(self, timeout_type: _TimeoutType, timeout: float) -> None:
        """
        Initializes a new instance of the Checker class with the specified timeout type to signal when timeout occurs.

        Args:
        - timeout_type (TimeoutType): TimeoutType to put onto event queue when timeout occurs
        """
        self._logger = logging.getLogger(self.__class__.__name__)

        self._timeout_event = threading.Event()
        self._timeout_type = timeout_type
        self._timeout = timeout
        self._event_queue = _EventQueueSingleton()
        self._counter = Checker.DEFAULT_COUNTER_VALUE

    @property
    def counter(self) -> int:
        """Expected counter value of the next message to be received."""
        return self._counter

    @property
    def timeout(self) -> float:
        """Time period in seconds after which timeout is considered to occur."""
        return self._timeout

    def timeout_occured(self) -> bool:
        """Returns True if timeout occured, False otherwise."""
        return self._timeout_event.is_set()

    def _create_timeout_event(self) -> None:
        """Puts event to event queue. """
        self._timeout_event.set()
        self._event_queue.add(event_type=_EventType.TIMEOUT_OCCURRED, data=self._timeout_type)
