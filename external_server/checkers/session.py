from threading import (
    Event as _Event,
    Timer as _Timer
)

from external_server.checkers.checker import Checker as _Checker
from external_server.models.structures import TimeoutType as _TimeoutType


class Session:
    """Checks if connected session did not timed out."""

    def __init__(self, timeout: int) -> None:
        self._checker = _Checker(timeout_type=_TimeoutType.SESSION_TIMEOUT, timeout=timeout)
        self._timer: _Timer | None = None
        self._timer_running = False
        self.id: str = ""

    @property
    def timeout(self) -> float:
        """Time period in seconds after which session is considered timed out."""
        return self._checker.timeout

    @property
    def timeout_event(self) -> _Event:
        return self._checker._timeout_event

    def start(self) -> None:
        self._timer = _Timer(self._checker.timeout, self._checker._create_timeout_event)
        self._timer.start()
        self._timer_running = True

    def reset(self) -> None:
        """Resets the checker's timer.

        Next messages' timeout is checked relative to call to this method.
        """
        self.stop()
        self.start()

    def stop(self) -> None:
        if self._timer_running and self._timer is not None:
            if self._timer.is_alive():
                self._timer.cancel()
                self._timer.join()
            self._checker._timeout_event.clear()
            self._timer_running = False