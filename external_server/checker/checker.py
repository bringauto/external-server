import threading


class Checker:

    TIMEOUT = 30

    def __init__(self) -> None:
        self.time_out = threading.Event()

    def _set_time_out(self) -> None:
        self.time_out.set()

    def check_time_out(self) -> bool:
        return self.time_out.is_set()
