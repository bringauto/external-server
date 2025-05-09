from queue import Queue
from threading import Lock as _Lock, Timer as _Timer
import dataclasses

from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import (
    CommandResponse as _CommandResponse
)
from fleet_protocol_protobuf_files.InternalProtocol_pb2 import (
    Device as _Device
)

from external_server.checkers.checker import TimeoutChecker as _Checker
from external_server.logs import CarLogger as _CarLogger, LOGGER_NAME
from external_server.models.structures import (
    Counter as _Counter,
    HandledCommand as HandledCommand,
    TimeoutType as _TimeoutType,
)
from external_server.models.events import EventQueue as _EventQueue


logger = _CarLogger(LOGGER_NAME)


@dataclasses.dataclass(frozen=True)
class QueuedCommand:
    """This class binds Command message with its counter value, the flag denoting if the
    command was returned by get_command API function or generated by the server, and a timer.
    """

    command: HandledCommand
    timer: _Timer

    def stop_timer(self) -> None:
        """Stop the timer for this command."""
        self.timer.cancel()
        self.timer.join()


class CommandQueue:
    """It stores instances of `QueuedCommand` and provides methods for adding and removing
    them from the queue.
    """

    def __init__(self, car: str) -> None:
        self._queue: Queue[QueuedCommand] = Queue()
        self._car = car
        self._oldest_counter: int | None = None
        self._newest_counter: int | None = None

    @property
    def command_counters(self) -> list[_Counter]:
        data: list[QueuedCommand] = list(self._queue.queue).copy()
        return [cmd.command.counter for cmd in data]

    @property
    def oldest_command_counter(self) -> _Counter | None:
        """Get the counter of the oldest command in the queue.

        Returns None if the queue is empty.
        """
        if self._queue.empty():
            return None
        else:
            cmd: QueuedCommand = self._queue.queue[0]
            return cmd.command.counter

    @property
    def newest_command_counter(self) -> _Counter | None:
        """Get the counter of the oldest command in the queue.

        Returns None if the queue is empty.
        """
        if self._queue.empty():
            return None
        else:
            cmd: QueuedCommand = self._queue.queue[-1]
            return cmd.command.counter

    def clear(self) -> None:
        """Remove all commands from queue and stop their timers."""
        while not self._queue.empty():
            cmd = self._queue.get()
            cmd.stop_timer()

    def empty(self) -> bool:
        """Check if the queue is empty."""
        return self._queue.empty()

    def get(self) -> HandledCommand:
        """Get the oldest command (instance of `QueuedCommand`) from the queue and stop its timer."""
        cmd: QueuedCommand = self._queue.get()
        cmd.stop_timer()
        logger.debug(
            f"Command retrieved from the command checker queue, number of remaining stored commands: {self._queue.qsize()}",
            self._car,
        )
        return cmd.command

    def list_commands(self) -> list[HandledCommand]:
        """Return the list of commands in the queue."""
        data: list[QueuedCommand] = list(self._queue.queue).copy()
        return [cmd.command for cmd in data]

    def put(self, command: HandledCommand, timer: _Timer) -> None:
        """Put the command (instance of `HandledCommand`) into the queue."""
        self._queue.put(QueuedCommand(command, timer))
        self._newest_counter = command.counter
        logger.debug(
            f"Command added to the command checker queue. Number of stored commands: {self._queue.qsize()}",
            self._car,
        )


class PublishedCommandChecker(_Checker):
    """Checks for order of received Command responses and checks if duration between
    sending Command and receiving Command reponses do not exceeds timeout given in
    constructor.

    Is also External Server's memory of commands, which didn't have
    received Command response yet.
    """

    def __init__(self, timeout: float, event_queue: _EventQueue, car: str) -> None:
        super().__init__(
            _TimeoutType.COMMAND_RESPONSE_TIMEOUT,
            timeout=timeout,
            event_queue=event_queue,
        )
        self._lock = _Lock()
        self._counter = 0
        self._car = car
        with self._lock:
            self._commands = CommandQueue(car)
            self._received_response_counters: list[_Counter] = []

    @property
    def n_of_commands(self) -> int:
        return self._commands._queue.qsize()

    @property
    def command_counters(self) -> list[_Counter]:
        """Get the list of counters of commands in the queue.

        It is ensured that each counter in the list equals the previous one incremented by 1.
        """
        return self._commands.command_counters

    def command_device(self, counter: _Counter) -> None | _Device:
        """Return the device of the command with the given counter.

        Return None if the command with the given counter is not in the queue.
        """
        for cmd in self._commands.list_commands():
            if cmd.counter == counter:
                return cmd.device
        return None

    def pop(self, response: _CommandResponse) -> list[HandledCommand]:
        """Returns list of commands acknowledged with command responses in correct order.

        The list content depends on the response counter value:
        - if it matches the oldest commands counter waiting for response, the commands is returned
        with all the newer commands coming right after it.
        - if its outside of range of counters of the commands currently waiting for response, the
        response is ignored and empty list is returned.
        - if its within the range of counters of the commands currently waiting for response, the
        the response counter is stored in the list of received response counters and empty list is
        returned.
        """
        oldest_counter = self._commands.oldest_command_counter
        counter = response.messageCounter

        if oldest_counter == counter:
            cmds = [self._commands.get()]
            logger.info(
                f"Command delivery to a car has been acknowledged (counter={counter}).", self._car
            )
            next_counter = self._commands.oldest_command_counter
            while next_counter in sorted(self._received_response_counters):
                cmd = self._commands.get()
                cmds.append(cmd)
                self._received_response_counters.remove(next_counter)
                logger.info(
                    f"Command delivery to a car has been acknowledged (counter={next_counter}).",
                    self._car,
                )
                next_counter = self._commands.oldest_command_counter
            logger.debug(
                f"Popping commands with counters: {', '.join(str(cmd.counter) for cmd in cmds)}",
                self._car,
            )
            return cmds
        else:
            if oldest_counter is None:
                logger.info(
                    "No commands in the queue awaiting a response. "
                    f"Ignoring the recevied response (counter={counter}).",
                    self._car,
                )
            elif oldest_counter < counter <= self._commands.newest_command_counter:
                self._received_response_counters.append(counter)
                logger.info(
                    f"Cannot pop command with counter={counter} "
                    f"because it is not the oldest command (counter={oldest_counter}).",
                    self._car,
                )
            else:
                logger.info(
                    f"Ignoring received response (counter={counter}) as it "
                    f"corresponds to a command that is not in the queue.",
                    self._car,
                )
            return []

    def add(self, command: HandledCommand) -> HandledCommand:
        """Add command to checker, when command is sent to Module Gateway.

        Start timeout for Command response.
        """
        with self._lock:
            command.update_counter_value(self._counter)
            self._commands.put(command, self._get_started_timer())
            logger.debug(f"Command added to checker, counter={self._counter}", self._car)
            self._counter += 1
        return command

    def reset(self) -> None:
        self._commands.clear()
        self._received_response_counters.clear()
        self._timeout_event.clear()

    def set_counter(self, counter: int) -> None:
        self._counter = counter

    def _get_started_timer(self) -> _Timer:
        """Get the timer object for the oldest command in the queue and start it."""
        timer = _Timer(self._timeout, self.set_timeout)
        timer.start()
        return timer
