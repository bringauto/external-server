from threading import Timer as _Timer
from queue import PriorityQueue as _PriorityQueue, Queue as _Queue
import logging.config
import json
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import Status as _Status  # type: ignore
from external_server.checkers.checker import Checker as _Checker
from external_server.models.structures import TimeoutType as _TimeoutType


logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


CounterValue = int
QueuedStatus = tuple[CounterValue, _Status]
QueuedTimer = tuple[CounterValue, _Timer]


class StatusChecker(_Checker):
    """Stores and checks the order of received Statuses in a queue.

    Ensures that all Statuses can be retrieved only after checking in all the previous Statuses.
    """

    def __init__(self, timeout: int) -> None:
        super().__init__(_TimeoutType.MESSAGE_TIMEOUT)
        self._timeout = timeout
        self._counter = 1
        self._received_statuses: _PriorityQueue[QueuedStatus] = _PriorityQueue()
        self._skipped: _PriorityQueue[QueuedTimer] = _PriorityQueue()
        self._checked_statuses: _Queue[_Status] = _Queue()

    @property
    def checked_statuses(self) -> _Queue[_Status]:
        return self._checked_statuses

    @property
    def missing_status_counter_vals(self) -> list[CounterValue]:
        return [status_counter for status_counter, _ in self._skipped.queue]

    def check(self, status: _Status) -> None:
        assert isinstance(status, _Status)
        self._received_statuses.put((status.messageCounter, status))
        if status.messageCounter == self._counter:
            self._move_next_received_status_to_checked()
        else:
            self._store_skipped_counter_values(status.messageCounter)

    def get(self) -> _Status | None:
        """Returns the next Status message in queue if it is available, otherwise `None`."""
        status = self._checked_statuses.get_nowait() if not self._checked_statuses.empty() else None
        return status

    def initialize_counter(self, counter: CounterValue) -> None:
        self._counter = counter

    def reset(self) -> None:
        while not self._skipped.empty():
            self._delete_timer_for_skipped_counter()
        self._received_statuses.queue.clear()
        self._checked_statuses.queue.clear()
        self.timeout.clear()
        self._counter = 1

    def _move_next_status_from_received_to_checked(self):
        status_counter, status = self._received_statuses.get()
        self._checked_statuses.put(status)
        self._counter += 1
        self._logger.info(f"Status (counter={status_counter}) has been added to queue.")

    def _move_next_received_status_to_checked(self):
        if self._skipped.empty():
            self._move_next_status_from_received_to_checked()
        else:
            while self._any_received_skipped_statuses():
                self._delete_timer_for_skipped_counter()
                self._move_next_status_from_received_to_checked()

    def _any_received_skipped_statuses(self) -> bool:
        return (
            not self._skipped.empty()
            and self._skipped.queue[0][0] == self._counter
            and self._received_statuses.queue[0][0] == self._counter
        )

    def _delete_timer_for_skipped_counter(self) -> None:
        _, timer = self._skipped.get()
        timer.cancel()
        timer.join()

    def _store_skipped_counter_values(self, status_counter: CounterValue) -> None:
        missed_counter_vals = range(self._counter, status_counter + 1)
        for c in missed_counter_vals:
            new_skipped_counter = self._skipped.empty() or c > self._skipped.queue[-1][0]
            if new_skipped_counter:
                self._start_timer_for_skipped_status(c)

    def _start_timer_for_skipped_status(self, counter: CounterValue) -> None:
        timer = _Timer(self._timeout, self._timeout_occurred)
        timer.start()
        self._skipped.put((counter, timer))
        self._logger.warning(f"Status with counter {counter} is missing.")
