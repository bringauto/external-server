from threading import Timer as _Timer
from queue import PriorityQueue as _PriorityQueue, Queue as _Queue
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import Status as _Status  # type: ignore
from external_server.logs import CarLogger as _CarLogger, LOGGER_NAME
from external_server.checkers.checker import Checker as _Checker
from external_server.models.structures import TimeoutType as _TimeoutType
from external_server.models.events import EventQueue as _EventQueue


logger = _CarLogger(LOGGER_NAME)
CounterValue = int
QueuedStatus = tuple[CounterValue, _Status]
QueuedTimer = tuple[CounterValue, _Timer]


class StatusChecker(_Checker):
    """Stores and checks the order of received Statuses in a queue.

    Ensures that all Statuses can be retrieved only after checking in all the previous Statuses.
    """

    DEFAULT_INIT_COUNTER = 1

    def __init__(self, timeout: float, event_queue: _EventQueue, car: str = "") -> None:
        super().__init__(_TimeoutType.STATUS_TIMEOUT, timeout=timeout, event_queue=event_queue)
        # priority queues instead of ordinary queues ensure the statuses are stored in ascending
        # order of their counter values
        self._received: _PriorityQueue[QueuedStatus] = _PriorityQueue()
        self._skipped: _PriorityQueue[QueuedTimer] = _PriorityQueue()
        self._checked: _Queue[_Status] = _Queue()
        self._allow_counter_reset = True
        self._car = car

    @property
    def checked(self) -> _Queue[_Status]:
        """Queue containing statuses received in the correct order and not yet retrieved."""
        return self._checked

    @property
    def skipped_counters(self) -> list[CounterValue]:
        """List of missing status counters that were not yet received."""
        # a simple list comprehension yielded partially altered order,
        # that is why the sorted() is used
        return sorted([counter for counter, _ in self._skipped.queue])

    def check(self, status: _Status) -> None:
        """Check the counter value of the received Status message and add it to the queue.

        The status is always stored as received, with further processing depending on the
        counter value of the received status:

        - value < expected value - the status is ignored.
        - value == expected value - the status is moved to the checked statuses queue and
        becomes accessible for retrieval.
        - value > expected value - all values between the expected and received counter values
        (inluding the expected) are stored as missing. For each of them, a timer is started, checking timeout
        for the missing statuses receival. The status is not moved to the checked statuses queue.
        """

        if status.messageCounter < self._counter:
            logger.warning(
                f"Status with counter {status.messageCounter} smaller than expected value {self._counter} is ignored.",
                self._car,
            )
        else:
            if self._allow_counter_reset:
                self._counter = status.messageCounter
                self._allow_counter_reset = False

            self._received.put((status.messageCounter, status))
            if status.messageCounter == self._counter:
                while not self._received.empty() and self._received.queue[0][0] == self._counter:
                    self._remove_oldest_skipped_and_stop_its_timer()
                    oldest_received = self._received.get()[1]
                    self._checked.put(oldest_received)
                    self._counter += 1
            else:  # status counter is greater than expected - some statuses are missing
                self._store_skipped_counter_values(status.messageCounter)

    def get(self) -> _Status | None:
        """Returns the next Status message in queue if it is available, otherwise `None`."""
        status = self._checked.get_nowait() if not self._checked.empty() else None
        return status

    def allow_counter_reset(self) -> None:
        """The next status check will reset the counter to the received status counter value."""
        self._allow_counter_reset = True

    def set_counter(self, counter: CounterValue) -> None:
        """Set the counter to the given value and disallow the counter reset."""
        if self._received.empty() and self._checked.empty():
            self._counter = counter
            self._allow_counter_reset = False

    def reset(self) -> None:
        """Clear all data stored in the checker and reset the counter to the initial value.

        Stop timers for all skipped status counter values.
        """
        self._clear_queues_and_timeout_event()
        self._counter = StatusChecker.DEFAULT_INIT_COUNTER

    def _clear_queues_and_timeout_event(self) -> None:
        """Empty queues for received, skipped and checked statuses. Unset timeout event if set."""
        self._clear_skipped_counters()
        self._received.queue.clear()
        self._checked.queue.clear()
        self._timeout_event.clear()

    def _clear_skipped_counters(self) -> None:
        """Clear all skipped statuses and stop all timers."""
        while not self._skipped.empty():
            _, timer = self._skipped.get()
            timer.cancel()
            timer.join()

    def _remove_oldest_skipped_and_stop_its_timer(self) -> None:
        """Clear all skipped statuses that are already received."""
        if not self._skipped.empty() and self._skipped.queue[0][0] <= self._counter:
            _, timer = self._skipped.get()
            timer.cancel()
            timer.join()

    def _store_skipped_counter_values(self, status_counter: CounterValue) -> None:
        """Store all missing status counter values and start timers for them."""
        if not self._skipped.empty() and status_counter <= self._skipped.queue[-1][0]:
            return
        missed_counter_vals = range(self._counter, status_counter)
        for c in missed_counter_vals:
            new_skipped_counter = self._skipped.empty() or c > self._skipped.queue[-1][0]
            if new_skipped_counter:
                self._store_skipped_counter_and_start_timer(c)

    def _store_skipped_counter_and_start_timer(self, counter: CounterValue) -> None:
        """Store the missing status counter value and start a timer for it."""
        timer = _Timer(self._timeout, self.set_timeout)
        timer.start()
        self._skipped.put((counter, timer))
        logger.warning(f"Status with counter {counter} is missing.", self._car)
