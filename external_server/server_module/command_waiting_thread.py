from typing import Callable
import threading
from queue import Queue, Empty
import sys
import logging

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import Device as _Device  # type: ignore
from external_server.models.structures import GeneralErrorCode, EsErrorCode
from external_server.adapters.api.adapter import APIClientAdapter  # type: ignore
from external_server.models.events import EventQueueSingleton, EventType


logger = logging.getLogger(__name__)


class _CommandQueue:

    def __init__(self) -> None:
        self._queue: Queue[tuple[bytes, _Device]] = Queue()
        self._commands_lock = threading.Lock()

    def clear(self) -> None:
        """Clear the stored commands in the queue."""
        while not self._queue.empty():
            self._queue.get()
        logger.debug("Command queue of command waiting thread has been emptied.")

    def empty(self) -> bool:
        """Check if the queue is empty."""
        return self._queue.empty()

    def get(self) -> tuple[bytes, _Device] | None:
        try:
            with self._commands_lock:
                command = self._queue.get(block=False)
                logger.debug(f"Retrieving command from command waiting thread queue. Number of remaning commands: {self.qsize()}.")
        except Empty:
            return None
        return command

    def qsize(self) -> int:
        """Return the number of commands stored in the queue."""
        return self._queue.qsize()

    def put(self, command: bytes, device: _Device) -> None:
        self._queue.put((command, device))
        logger.debug(f"Command added to command waiting thread queue. Number of commands in queue: {self.qsize()}.")


class CommandWaitingThread:
    """Instances of this class are responsible for retrieving commands from external server API.

    These commands are then stored in a queue.
    An event is added to the event queue when a command is available.
    """

    def __init__(
        self,
        api_client: APIClientAdapter,
        module_connection_check: Callable[[], bool],
        timeout_ms: int = 1000,
    ) -> None:

        self._api_adapter: APIClientAdapter = api_client
        self._events = EventQueueSingleton()
        self._waiting_thread = threading.Thread(target=self._main_thread)
        self._commands = _CommandQueue()
        self._module_connected: Callable[[], bool] = module_connection_check
        self._commands_lock = threading.Lock()
        self._connection_established_lock = threading.Lock()
        self._continue_thread = True
        self._timeout_ms = timeout_ms

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    def start(self) -> None:
        """Starts the thread for obtaining command from external server API."""
        self._waiting_thread.start()

    def stop(self) -> None:
        """Stops the thread after """
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
            pass
        else:
            logger.error(f"Error occured in wait_for_command function in API, rc: {rc}")

    def _pass_available_commands_to_queue(self) -> None:
        """Save the available commands in the queue."""
        remaining_commands = 1
        while remaining_commands > 0:
            command, device, remaining_commands = self._api_adapter.pop_command()
            if remaining_commands < 0:
                logger.error(f"Error in pop_command function in API. Code: {remaining_commands}")
            else:
                with self._commands_lock, self._connection_established_lock:
                    if not self._module_connected():
                        self._commands.clear()
                    logger.debug("Command received from API is stored in queue.")
                    self._commands.put(command, device)
        if self._module_connected():
            module_id = self._api_adapter.get_module_number()
            self._events.add(event_type=EventType.COMMAND_AVAILABLE, data=module_id)

    def _main_thread(self) -> None:
        while self._continue_thread:
            self.poll_commands()
