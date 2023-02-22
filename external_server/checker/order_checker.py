import logging
import threading
from queue import PriorityQueue, Queue

import external_server.protobuf.ExternalProtocol_pb2 as external_protocol
from external_server.checker.checker import Checker


class OrderChecker(Checker):
    def __init__(self, exc: Exception) -> None:
        super().__init__(exc)
        self.counter = 1
        self.received_statuses: PriorityQueue[tuple[int, external_protocol.Status]] = PriorityQueue()
        self.missing_statuses: PriorityQueue[tuple[int, threading.Timer]] = PriorityQueue()
        self.checked_statuses: Queue[external_protocol.Status] = Queue()

    def check(self, status_msg: external_protocol.Status) -> None:
        status_counter = status_msg.messageCounter
        self.received_statuses.put((status_counter, status_msg))
        if status_counter == self.counter:
            self._remove_missing_status()
            return

        for missing_counter in range(self.counter, status_counter + 1):
            if (
                self.missing_statuses.empty()
                or missing_counter > self.missing_statuses.queue[self.missing_statuses.qsize() - 1][0]
            ):
                timer = threading.Timer(Checker.TIMEOUT, super()._set_time_out)
                timer.start()
                self.missing_statuses.put((missing_counter, timer))
                logging.warning(f"Status message with counter {missing_counter} is missing")

    def _remove_missing_status(self):
        if self.missing_statuses.empty():
            self._add_checked_status()
            return
        while (
            not self.received_statuses.empty()
            and self.counter == self.received_statuses.queue[0][0]
            and self.counter == self.missing_statuses.queue[0][0]
        ):
            self._pop_timer()
            self._add_checked_status()

    def _add_checked_status(self):
        status_counter, status = self.received_statuses.get()
        self.checked_statuses.put(status)
        self.counter += 1
        logging.info(f"Status message with counter {status_counter} has been succesfully checked")

    def _pop_timer(self) -> None:
        _, timer = self.missing_statuses.get()
        timer.cancel()
        timer.join()

    def get_status(self) -> external_protocol.Status | None:
        return self.checked_statuses.get_nowait() if not self.checked_statuses.empty() else None

    def reset(self) -> None:
        while not self.missing_statuses.empty():
            self._pop_timer()
        self.received_statuses.queue.clear()
        self.checked_statuses.queue.clear()
        self.time_out.clear()
        self.counter = 1
