import threading

from external_server.timeout import TIMEOUT


class MessagesChecker:

    def __init__(self) -> None:
        self.timer: None | threading.Timer = None
        self.time_out = threading.Event()

    def _set_time_out(self) -> None:
        self.time_out.set()

    def check_time_out(self) -> bool:
        return self.time_out.is_set()

    def start(self) -> None:
        self.timer = threading.Timer(TIMEOUT, self._set_time_out)
        self.timer.start()

    def stop(self) -> None:
        self.timer.cancel()
        self.timer.join()
        self.time_out.clear()

    def reset(self) -> None:
        self.stop()
        self.start()
