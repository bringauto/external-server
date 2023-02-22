import threading


class Checker:
    TIMEOUT = 30

    def __init__(self, exc: Exception) -> None:
        self.time_out = threading.Event()
        self.exc = exc

    def _set_time_out(self) -> None:
        self.time_out.set()

    def check_time_out(self) -> bool:
        if self.time_out.is_set():
            raise self.exc
