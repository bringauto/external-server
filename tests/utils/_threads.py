from typing import Callable
import time
from concurrent import futures as _futures

from external_server import ExternalServer as _ExternalServer


class ExternalServerThreadExecutor:
    """This class encapsulates the ThreadPoolExecutor of concurrent.futures package and is used to:
    - start and stop an external server in a separate thread for unit tests,
    - submit functions to be executed in separate threads inside a unit test.

    To initialize the instance, an external server instance must be passed as an argument `server`.
    `sleep_after` is the time in seconds to sleep time after starting a new thread.

    The instance can be used via context manager in the same way as the ThreadPoolExecutor itself.

    Example:
    with ExternalServerThreadExecutor(server) as ex:
        ex.submit(foo)
    """

    def __init__(self, server: _ExternalServer, sleep_after: float = 0.1, start: bool = True) -> None:
        self._ex = _futures.ThreadPoolExecutor()
        self._sleep_after = sleep_after
        self._server = server
        self._start = start

    def __enter__(self):
        if self._start:
            self._ex.submit(self._server.start)
            time.sleep(self._sleep_after)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._ex.submit(self._server.stop)
        time.sleep(self._sleep_after)
        self._ex.shutdown()
        return False

    def submit(self, func: Callable, *func_args, **func_kwargs) -> _futures.Future:
        """Method for calling function `func` in separate threads inside a unit test."""
        future = self._ex.submit(func, *func_args, **func_kwargs)
        time.sleep(self._sleep_after)
        return future
