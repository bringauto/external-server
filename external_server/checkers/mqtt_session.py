from threading import Event as _Event, Timer as _Timer
import logging

from external_server.checkers.checker import TimeoutChecker as _Checker
from external_server.models.structures import TimeoutType as _TimeoutType
from external_server.models.events import EventQueue as _EventQueue
from external_server.logs import LOGGER_NAME


_logger = logging.getLogger(LOGGER_NAME)


class MQTTSession:
    """A class managing MQTT session context and activity."""

    def __init__(self, timeout: float, event_queue: _EventQueue) -> None:
        self._checker = _Checker(
            timeout_type=_TimeoutType.SESSION_TIMEOUT,
            timeout=timeout,
            event_queue=event_queue,
        )
        self._timer: _Timer | None = None
        self._timer_running = False
        self._id: str = ""

    @property
    def id(self) -> str:
        """Return the session ID."""
        return self._id

    @property
    def timeout(self) -> float:
        """Time period in seconds after which session is considered timed out."""
        return self._checker.timeout

    @property
    def timeout_event(self) -> _Event:
        """Return the event object that is set when the session times out."""
        return self._checker.timeout_event

    def set_id(self, session_id: str) -> None:
        """Update the session ID."""
        if not session_id:
            raise ValueError("Session ID cannot be empty")
        _logger.info(f"Updating session ID from {self._id} to {session_id}")
        self._id = session_id

    def start(self) -> None:
        """Starts the checker's timer if not already running."""
        if not self._timer_running:
            self._timer = _Timer(self._checker.timeout, self._checker.set_timeout)
            self._timer.start()
            self._timer_running = True
            _logger.debug(f"Started timer for MQTT session {self._id}")
        else:
            _logger.warning(f"Timer already running for MQTT session {self._id}")

    def reset_timer(self) -> None:
        """Resets the checker's timer.

        Next messages' timeout is checked relative to call to this method.
        """
        self.stop()
        self.start()

    def stop(self) -> None:
        """Stops the checker's timer."""
        if self._timer_running and self._timer is not None:
            _logger.info(f"Stopping timer for MQTT session {self._id}")
            if self._timer.is_alive():
                self._timer.cancel()
                self._timer.join()
            self._checker._timeout_event.clear()
            self._timer_running = False
            self._timer = None
        else:
            _logger.debug(f"No timer running for MQTT session {self._id}")