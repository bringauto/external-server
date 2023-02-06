import threading

from external_server.checker.checker import Checker

class MessagesChecker(Checker):
    """
    Checks if connected session did not timed out

    Messages can come from not connected session and connected session would have never
    been timed out. This class takes care that, if connected session did not send any
    message in TIMEOUT, then connected session is timed out
    """

    def __init__(self) -> None:
        super().__init__()
        self.timer: threading.Timer = threading.Timer(Checker.TIMEOUT, self._set_time_out)

    def start(self) -> None:
        self.timer = threading.Timer(Checker.TIMEOUT, super()._set_time_out)
        self.timer.start()

    def stop(self) -> None:
        if self.timer.is_alive():
            self.timer.cancel()
            self.timer.join()
        self.time_out.clear()

    def reset(self) -> None:
        self.stop()
        self.start()
