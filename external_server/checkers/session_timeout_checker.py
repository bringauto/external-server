from threading import Timer as _Timer

from external_server.checkers.checker import Checker as _Checker
from external_server.models.structures import TimeoutType as _TimeoutType


class SessionTimeoutChecker(_Checker):
    """Checks if connected session did not timed out

    Messages can come from not connected session and connected session would have never
    been timed out. This class takes care that, if connected session did not send any
    message in given timeout, then connected session is timed out
    """

    def __init__(self, timeout: int) -> None:
        super().__init__(_TimeoutType.SESSION_TIMEOUT)
        self._timeout = timeout
        self._timer: _Timer | None = None
        self._timer_running = False

    def start(self) -> None:
        self._timer = _Timer (self._timeout, self._timeout_occurred)
        self._timer.start()
        self._timer_running = True

    def stop(self) -> None:
        if self._timer_running and self._timer is not None:
            if self._timer.is_alive():
                self._timer.cancel()
                self._timer.join()
            self.timeout.clear()
            self._timer_running = False

    def reset(self) -> None:
        self.stop()
        self.start()
