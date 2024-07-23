import threading
import logging

from external_server.models.structures import TimeoutType as _TimeoutType
from external_server.models.event_queue import (
    EventQueueSingleton as _EventQueueSingleton,
    EventType as _EventType
)


_DEFAULT_COUNTER_VALUE = 0


class Checker:
    """
    A class that provides a mechanism to check for a timeout in a threaded operation.
    """

    def __init__(self, timeout_type: _TimeoutType) -> None:
        """
        Initializes a new instance of the Checker class with the specified timeout type to signal when timeout occurs.

        Args:
        - timeout_type (TimeoutType): TimeoutType to put onto event queue when timeout occurs
        """
        self._logger = logging.getLogger(self.__class__.__name__)

        self.timeout = threading.Event()  # to be removed?
        self._event_queue = _EventQueueSingleton()
        self._timeout_type = timeout_type
        self._counter = _DEFAULT_COUNTER_VALUE

    @property
    def counter(self) -> int:
        return self._counter

    def _timeout_occurred(self) -> None:
        """Puts the TIMEOUT_OCCURRED event to event queue. """
        self.timeout.set()
        self._event_queue.add(event_type=_EventType.TIMEOUT_OCCURRED, data=self._timeout_type)
