import threading
from queue import PriorityQueue, Queue
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

import ExternalProtocol_pb2 as external_protocol
from external_server.checker.checker import Checker as _Checker
from external_server.structures import TimeoutType


class StatusOrderChecker(_Checker):
    """ Stores and checks the order of received Statuses in a queue.

    Ensures that all Statuses can be retrieved only after checking in all the previous Statuses.
    """

    def __init__(self, timeout: int) -> None:
        super().__init__(TimeoutType.MESSAGE_TIMEOUT)
        self._timeout = timeout
        self._counter = 1
        self._received_statuses: PriorityQueue[
            tuple[int, external_protocol.Status]
        ] = PriorityQueue()
        self._missing_statuses: PriorityQueue[tuple[int, threading.Timer]] = PriorityQueue()
        self._checked_statuses: Queue[external_protocol.Status] = Queue()

    @property
    def checked_statuses(self) -> Queue[external_protocol.Status]:
        return self._checked_statuses

    @property
    def missing_statuses(self) -> PriorityQueue[tuple[int, threading.Timer]]:
        return self._missing_statuses

    @property
    def received_statuses(self) -> PriorityQueue[tuple[int, external_protocol.Status]]:
        return self._received_statuses

    @property
    def missing_status_counter_vals(self) -> list[int]:
        return [status_counter for status_counter, _ in self._missing_statuses.queue]

    def check(self, status_msg: external_protocol.Status) -> None:
        status_counter = status_msg.messageCounter
        self._received_statuses.put((status_counter, status_msg))
        if status_counter == self._counter:
            self._remove_missing_status()
            return

        for missing_counter in range(self._counter, status_counter + 1):
            if (
                self._missing_statuses.empty()
                or missing_counter
                > self._missing_statuses.queue[self._missing_statuses.qsize() - 1][0]
            ):
                timer = threading.Timer(self._timeout, self._timeout_occurred)
                timer.start()
                self._missing_statuses.put((missing_counter, timer))
                self._logger.warning(f"Status message with counter {missing_counter} is missing")

    def _remove_missing_status(self):
        if self._missing_statuses.empty():
            self._add_checked_status()
            return
        while (
            not self._received_statuses.empty()
            and self._counter == self._received_statuses.queue[0][0]
            and self._counter == self._missing_statuses.queue[0][0]
        ):
            self._pop_timer()
            self._add_checked_status()

    def _add_checked_status(self):
        status_counter, status = self._received_statuses.get()
        self._checked_statuses.put(status)
        self._counter += 1
        self._logger.info(
            f"Status message with counter {status_counter} has been succesfully checked"
        )

    def _pop_timer(self) -> None:
        _, timer = self._missing_statuses.get()
        timer.cancel()
        timer.join()

    def get_status(self) -> external_protocol.Status | None:
        return self._checked_statuses.get_nowait() if not self._checked_statuses.empty() else None

    def reset(self) -> None:
        while not self._missing_statuses.empty():
            self._pop_timer()
        self._received_statuses.queue.clear()
        self._checked_statuses.queue.clear()
        self.timeout.clear()
        self._counter = 1
