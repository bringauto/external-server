from typing import Callable
import threading
from queue import Queue, Empty

from fleet_protocol_protobuf_files.InternalProtocol_pb2 import (
    Device as _Device
)
from external_server.models.structures import GeneralErrorCode, EsErrorCode
from external_server.adapters.api.adapter import APIClientAdapter  # type: ignore
from external_server.models.events import EventType as _EventType, EventQueue as _EventQueue
from external_server.logs import CarLogger as _CarLogger, LOGGER_NAME as _LOGGER_NAME


logger = _CarLogger(_LOGGER_NAME)


class _CommandQueue:

    def __init__(self, car: str) -> None:
        self._queue: Queue[tuple[bytes, _Device]] = Queue()
        self._commands_lock = threading.Lock()
        self._car = car

    def clear(self) -> None:
        """Clear the stored commands in the queue."""
        while not self._queue.empty():
            self._queue.get()
        logger.debug("Command queue of command waiting thread has been emptied.", self._car)

    def empty(self) -> bool:
        """Check if the queue is empty."""
        return self._queue.empty()

    def get(self) -> tuple[bytes, _Device] | None:
        try:
            with self._commands_lock:
                command = self._queue.get(block=False)
                logger.debug(
                    f"Retrieving command from command waiting thread queue. Number of remaning commands: {self.qsize()}.",
                    self._car,
                )
        except Empty:
            return None
        return command

    def qsize(self) -> int:
        """Return the number of commands stored in the queue."""
        return self._queue.qsize()

    def put(self, command: bytes, device: _Device) -> None:
        self._queue.put((command, device))
        logger.debug(
            f"Command added to command waiting thread queue. Number of commands in queue: {self.qsize()}.",
            self._car,
        )


class CommandWaitingThread:
    """Instances of this class are responsible for retrieving commands from external server API.

    These commands are then stored in a queue.
    An event is added to the event queue when a command is available.
    """

    def __init__(
        self,
        api_client: APIClientAdapter,
        module_connection_check: Callable[[], bool],
        event_queue: _EventQueue,
        timeout_ms: int = 1000,
    ) -> None:

        self._api_adapter: APIClientAdapter = api_client
        self._event_queue = event_queue
        self._waiting_thread = threading.Thread(target=self._main_thread)
        self._commands = _CommandQueue(api_client._car)
        self._module_connected: Callable[[], bool] = module_connection_check
        self._commands_lock = threading.Lock()
        self._connection_established_lock = threading.Lock()
        self._continue_thread = True
        self._timeout_ms = timeout_ms
        self._car = api_client.car

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    def start(self) -> None:
        """Starts the thread for obtaining command from external server API."""
        self._waiting_thread.start()

    def stop(self) -> None:
        """Stops the thread by setting the continue flag to False."""
        self._continue_thread = False
        self.wait_for_join()

    def wait_for_join(self) -> None:
        """Waits for join with calling thread."""
        if self._waiting_thread.is_alive():
            self._waiting_thread.join()

    def pop_command(self) -> tuple[bytes, _Device] | None:
        """Return available command if currently available, else returns None."""
        return self._commands.get()

    def poll_commands(self) -> None:
        """Poll for a single command from the API.

        If commands are avaiable, they are saved in the queue.
        If no commands are available before the timeout, no action is taken.
        If an error occurs, an error message is logged.
        """

        # The function is made public in order to be used in unit tests
        rc = self._api_adapter.wait_for_command(self._timeout_ms)
        if rc == GeneralErrorCode.OK:
            self._pass_available_commands_to_queue()
        elif rc == EsErrorCode.TIMEOUT:
            logger.debug("No command available from API.", self._car)
        else:
            logger.error(
                f"Error occured in wait_for_command function in API, return code: {rc}.", self._car
            )

    def _pass_available_commands_to_queue(self) -> None:
        """Save the available commands in the queue."""
        remain_cmds = 1
        popped_commands: list[tuple[bytes, _Device]] = list()
        while remain_cmds > 0:
            command, device, remain_cmds = self._api_adapter.pop_command()
            if remain_cmds < 0:
                logger.error(f"Error in pop_command in API. Code: {remain_cmds}.", self._car)
            else:
                popped_commands.append((command, device))
        self._put_popped_commands_into_queue(popped_commands)

    def _put_popped_commands_into_queue(self, commands: list[tuple[bytes, _Device]]) -> None:
        if not commands:
            return
        if not self._module_connected():
            commands = commands[-1:]
        for command, device in commands:
            self._put_single_popped_command_into_queue(command, device)

    def _put_single_popped_command_into_queue(self, command: bytes, device: _Device) -> None:
        """Put the command in the queue."""
        with self._commands_lock, self._connection_established_lock:
            logger.debug("Command received from the API is stored in queue.", self._car)
            self._commands.put(command, device)
            if self._module_connected():
                module_id = self._api_adapter.get_module_number()
                self._event_queue.add(event_type=_EventType.COMMAND_AVAILABLE, data=module_id)

    def _main_thread(self) -> None:
        while self._continue_thread:
            self.poll_commands()
