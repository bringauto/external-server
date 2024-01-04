import threading
import logging

from external_server.structures import TimeoutType
from external_server.event_queue import EventQueueSingleton, EventType


class Checker:
    """
    A class that provides a mechanism to check for a timeout in a threaded operation.
    """

    def __init__(self, timeout_type: TimeoutType) -> None:
        """
        Initializes a new instance of the Checker class with the specified timeout type to signal when timeout occurs.

        Args:
        - timeout_type (TimeoutType): TimeoutType to put onto event queue when timeout occurs
        """
        self._logger = logging.getLogger(self.__class__.__name__)

        self.time_out = threading.Event()
        self._event_queue = EventQueueSingleton()
        self._timeout_type = timeout_type

    def _timeout_occurred(self) -> None:
        """
        Puts the TIMEOUT_OCCURRED event to event queue.
        """
        self._event_queue.add_event(event_type=EventType.TIMEOUT_OCCURRED, data=self._timeout_type)
