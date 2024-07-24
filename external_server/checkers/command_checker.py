from queue import Queue
from threading import Timer as _Timer
import sys
import dataclasses

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import Command as _Command  # type: ignore
from external_server.checkers.checker import Checker as _Checker
from external_server.models.structures import TimeoutType as _TimeoutType


_ReturnedFromAPIFlag = bool
_ExternalCommand = tuple[_Command, _ReturnedFromAPIFlag]
_Counter = int


@dataclasses.dataclass(frozen=True)
class QueuedCommand:
    command: _Command
    counter: _Counter
    from_api: _ReturnedFromAPIFlag
    timer: _Timer

    def stop_timer(self) -> None:
        self.timer.cancel()
        self.timer.join()


class CommandQueue:
    def __init__(self) -> None:
        self._queue: Queue[QueuedCommand] = Queue()

    @property
    def oldest_counter(self) -> _Counter | None:
        if self._queue.empty():
            return None
        else:
            cmd: QueuedCommand = self._queue.queue[0]
            return cmd.counter

    def clear(self) -> None:
        while not self._queue.empty():
            cmd = self._queue.get()
            cmd.stop_timer()

    def empty(self) -> bool:
        return self._queue.empty()

    def get(self, stop_timer: bool = True) -> QueuedCommand:
        cmd: QueuedCommand = self._queue.get()
        cmd.stop_timer()
        return cmd

    def put(self, command: QueuedCommand) -> None:
        self._queue.put(command)


class CommandChecker(_Checker):
    """Checker for all Command messages

    Checks for order of received Command responses and checks if duration between
    sending Command and receiving Command reponses do not exceeds timeout given in
    constructor. Is also External Server's memory of commands, which didn't have
    received Command response yet.
    """

    def __init__(self, timeout: int) -> None:
        super().__init__(_TimeoutType.COMMAND_TIMEOUT)
        self._timeout = timeout
        self._commands = CommandQueue()
        self._missed_counter_vals: list[_Counter] = []
        self._counter = 0

    def pop_commands(self, counter: _Counter) -> list[_ExternalCommand]:
        """Pops commands from checker.

        Returns list of Command messages, which have been acknowledged with Command
        responses in correct order. With every command the returned_from_api flag is
        also returned. Can return empty list if received Command responses in wrong
        order.

        Stops the timer for acknowledged commands. Should be called when Command
        response from Module gateway is received.

        Parameters
        ----------
        msg_counter : int
            number of command, which was acknowledged by received commandResponse
        """
        if self._commands.oldest_counter != counter:
            self._missed_counter_vals.append(counter)
            self._logger.warning(f"Command response received in wrong order. Counter={counter}")
            return []

        queued_command = self._commands.get()
        popped = [(queued_command.command, queued_command.from_api)]
        self._logger.info(f"Received Command response was acknowledged, counter={counter}")
        while self._missed_counter_vals:
            counter = self._commands.oldest_counter
            if (counter is not None) and (counter in self._missed_counter_vals):
                command = self._commands.get()
                command.stop_timer()
                popped.append((command.command, command.from_api))
                self._missed_counter_vals.remove(counter)
                self._logger.info(f"Older Command response acknowledged, counter={counter}")
            else:
                break
        return popped

    def add_command(self, command: _Command, returned_from_api: _ReturnedFromAPIFlag) -> None:
        """Adds command to checker

        Adds given command to this checker. Starts timeout for Command response. Set
        the returned_from_api to True if command was returned by get_command API
        function. Should be called when command is sent to Module gateway.
        """
        timer = _Timer(self._timeout, self._timeout_occurred)
        timer.start()
        self._commands.put(QueuedCommand(command, self._counter, returned_from_api, timer))
        self._counter += 1

    def reset(self) -> None:
        """Stops all timers and clears command memory"""
        self._commands.clear()
        self._missed_counter_vals.clear()
        self.timeout.clear()

