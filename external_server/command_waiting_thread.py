import threading
from queue import Queue, Empty
import logging
import sys
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import Device as _Device  # type: ignore
from external_server.models.structures import GeneralErrorCodes, EsErrorCodes
from external_server.clients.api_client import ExternalServerApiClient
from external_server.models.event_queue import EventQueueSingleton, EventType


class CommandWaitingThread:
    TIMEOUT = 1000  # Timeout for wait_for_command in ms

    def __init__(self, api_client: ExternalServerApiClient) -> None:
        self._logger = logging.getLogger(
            f"{self.__class__.__name__}({api_client.get_module_number()})"
        )

        self._api_client = api_client
        self._event_queue = EventQueueSingleton()
        self._waiting_thread = threading.Thread(target=self._main_thread)
        self._commands: Queue[tuple[bytes, _Device]] = Queue()
        self._connection_established = False
        self._commands_lock = threading.Lock()
        self._connection_established_lock = threading.Lock()
        self._continue_thread = True

    @property
    def connection_established(self) -> bool:
        with self._connection_established_lock:
            return self._connection_established

    @connection_established.setter
    def connection_established(self, value: bool):
        with self._connection_established_lock:
            self._connection_established = value

    def start(self) -> None:
        """Starts the thread for obtaining command from external server api."""
        self._waiting_thread.start()

    def stop(self) -> None:
        """Stops the thread."""
        self._continue_thread = False

    def wait_for_join(self) -> None:
        """Waits for join with calling thread."""
        if self._waiting_thread.is_alive():
            self._waiting_thread.join()

    def pop_command(self) -> tuple[bytes, _Device] | None:
        """Returns available command if currently available, else returns None."""
        try:
            with self._commands_lock:
                command = self._commands.get(block=False)
        except Empty:
            return None
        return command

    def _save_available_commands(self) -> None:
        remaining_commands = 1
        while remaining_commands > 0:
            command, device, remaining_commands = self._api_client.pop_command()

            if remaining_commands < 0:
                self._logger.error(
                    f"Error occured in pop_command function in API, rc: {remaining_commands}"
                )
            else:
                with self._commands_lock:
                    with self._connection_established_lock:
                        if not self._connection_established:
                            while not self._commands.empty():
                                _ = self._commands.get()

                    self._commands.put((command, device))
        if self._connection_established:
            self._event_queue.add_event(
                event_type=EventType.COMMAND_AVAILABLE, data=self._api_client.get_module_number()
            )

    def _main_thread(self) -> None:
        while self._continue_thread:
            rc = self._api_client.wait_for_command(self.TIMEOUT)
            if rc == GeneralErrorCodes.OK:
                self._save_available_commands()
            elif rc == EsErrorCodes.TIMEOUT_OCCURRED:
                continue
            else:
                self._logger.error(f"Error occured in wait_for_command function in API, rc: {rc}")
