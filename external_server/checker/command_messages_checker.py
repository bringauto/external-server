import threading
from queue import Queue
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

import ExternalProtocol_pb2 as external_protocol  # type: ignore
from external_server.checker.checker import Checker
from external_server.structures import TimeoutType


ReturnedFromAPIFlag = bool
ExternalCommand = tuple[external_protocol.Command, ReturnedFromAPIFlag]


class CommandMessagesChecker(Checker):
    """Checker for all Command messages

    Checks for order of received Command responses and checks if duration between
    sending Command and receiving Command reponses do not exceeds timeout given in
    constructor. Is also External Server's memory of commands, which didn't have
    received Command response yet.
    """

    def __init__(self, timeout: int) -> None:
        super().__init__(TimeoutType.COMMAND_TIMEOUT)
        self._timeout = timeout
        self._commands: Queue[tuple[external_protocol.Command, int, bool, threading.Timer]] = (
            Queue()
        )
        self._received_acks: list[int] = []
        self._counter = 0

    def acknowledge_and_pop_commands(self, msg_counter: int) -> list[ExternalCommand]:
        """Pops commands from checker

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
        command_list: list[ExternalCommand] = list()
        if self._commands.empty() or msg_counter != self._commands.queue[0][1]:
            self._received_acks.append(msg_counter)
            self._logger.warning(
                f"Command response message has been received in bad order: {msg_counter}"
            )
            return command_list

        command, _, returned_from_api, timer = self._commands.get()
        command_list.append((command, returned_from_api))

        self._stop_timer(timer)
        self._logger.info(
            f"Received Command response message was acknowledged, messageCounter: {msg_counter}"
        )
        while self._received_acks:
            counter = self._commands.queue[0][1]
            if counter in self._received_acks:
                command, _, returned_from_api, timer = self._commands.get()
                command_list.append((command, returned_from_api))
                self._stop_timer(timer)
                self._received_acks.remove(counter)
                self._logger.info(
                    f"Older Command response message was acknowledged, messageCounter: {counter}"
                )
                continue
            break

        return command_list

    def add_command(
        self, command: external_protocol.Command, returned_from_api: ReturnedFromAPIFlag
    ) -> None:
        """Adds command to checker

        Adds given command to this checker. Starts timeout for Command response. Set
        the returned_from_api to True if command was returned by get_command API
        function. Should be called when command is sent to Module gateway.
        """
        timer = threading.Timer(self._timeout, self._timeout_occurred)
        timer.start()
        self._commands.put((command, self._counter, returned_from_api, timer))
        self._counter += 1

    def reset(self) -> None:
        """Stops all timers and clears command memory"""
        while not self._commands.empty():
            _, _, _, timer = self._commands.get()
            self._stop_timer(timer)
        self._received_acks.clear()
        self.timeout.clear()

    def _stop_timer(self, timer: threading.Timer) -> None:
        timer.cancel()
        timer.join()
