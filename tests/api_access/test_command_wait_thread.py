import unittest
import sys
import time
import logging
import threading

sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.adapters.api.adapter import APIClientAdapter
from external_server.server_module.command_waiting_thread import CommandWaitingThread
from external_server.config import ModuleConfig
from InternalProtocol_pb2 import Device  # type: ignore
from external_server.models.structures import EsErrorCode, GeneralErrorCode, ReturnCode
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH
from external_server.server_module.command_waiting_thread import logger
from external_server.models.events import EventQueue


class APIClientAdapterTest(APIClientAdapter):

    def __init__(self, config: ModuleConfig, company: str, car: str, module_id: int) -> None:
        super().__init__(config=config, company=company, car=car)
        self._commands_list: list[tuple[bytes, Device, ReturnCode]] = []
        self.api_initialized = False
        self._module_id = module_id
        self._command_available = threading.Event()

    def init(self) -> None:
        self.api_initialized = True

    def define_commands(self, api_commands: list[tuple[bytes, Device, ReturnCode]]) -> None:
        """Fill the mocked command queue with commands."""
        self._commands_list = api_commands.copy()
        if self._commands_list:
            self._command_available.set()

    def pop_command(self) -> tuple[bytes, Device, ReturnCode]:  # pragma: no cover
        if self._commands_list:
            cmd = self._commands_list.pop(0)
            cmd = (cmd[0], cmd[1], len(self._commands_list))
            return cmd
        else:
            return (b"", Device(), GeneralErrorCode.NOT_OK)

    def wait_for_command(self, timeout: int) -> ReturnCode:
        if not self.api_initialized:
            return GeneralErrorCode.NOT_OK
        else:
            timeout_s = timeout / 1000.0
            if self._command_available.wait(timeout=timeout_s):
                self._command_available.clear()
                return GeneralErrorCode.OK
            return EsErrorCode.TIMEOUT


class Test_Creating_Command_Waiting_Thread(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})
        cls.client = APIClientAdapterTest(
            config=cls.module_config, company="BringAuto", car="Car1", module_id=4
        )
        cls.client.init()

    def setUp(self):
        self.connected = False
        self.thread = CommandWaitingThread(
            self.client, lambda: self.connected, event_queue=EventQueue(), timeout_ms=100
        )

    def test_thread_is_initially_not_started(self):
        self.assertFalse(self.thread._waiting_thread.is_alive())

    def test_thread_is_not_alive_after_calling_start(self):
        self.thread.start()
        self.assertTrue(self.thread._waiting_thread.is_alive())

    def test_thread_is_not_alive_after_calling_stop(self):
        self.thread.start()
        self.thread.stop()
        self.assertFalse(self.thread._waiting_thread.is_alive())

    def test_popping_command_from_empty_queue_returns_none(self):
        self.assertIsNone(self.thread.pop_command())

    def tearDown(self) -> None:
        self.thread.stop()


class Test_Uninitialized_API_Client(unittest.TestCase):

    def test_polling_commands_from_uninitialized_api_logs_error(self):
        module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})
        client = APIClientAdapterTest(module_config, "BringAuto", "Car1", module_id=4)
        thread = CommandWaitingThread(
            client, lambda: True, event_queue=EventQueue(), timeout_ms=1000
        )  # pragma: no cover
        with self.assertLogs(logger=logger._logger, level=logging.ERROR):
            thread.poll_commands()


class Test_Disconnected_Module(unittest.TestCase):

    def test_only_newest_command_is_stored_in_queue_when_module_is_disconnected(self):
        module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})
        client = APIClientAdapterTest(
            config=module_config, company="BringAuto", car="Car1", module_id=4
        )
        client.init()
        module_connected = False
        thread = CommandWaitingThread(
            client, lambda: module_connected, event_queue=EventQueue(), timeout_ms=100
        )
        client.define_commands(
            [(b"command1", Device(), 2), (b"command2", Device(), 1), (b"command3", Device(), 0)]
        )
        thread.poll_commands()
        time.sleep(thread.timeout_ms / 1000.0)
        self.assertEqual(thread._commands.qsize(), 1)
        expected_command = (b"command3", Device())
        self.assertEqual(thread.pop_command(), expected_command)


class Test_Polling_Commands(unittest.TestCase):

    def setUp(self) -> None:
        self.module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})
        self.client = APIClientAdapterTest(
            config=self.module_config, company="BringAuto", car="Car1", module_id=4
        )
        self.client.init()
        self.connection = False
        self.thread = CommandWaitingThread(
            self.client, lambda: self.connection, event_queue=EventQueue(), timeout_ms=100
        )

    def test_command_queue_remains_empty_if_no_command_occurs_on_api_before_timeout(self):
        self.thread.poll_commands()
        time.sleep(self.thread.timeout_ms / 1000.0)
        self.assertTrue(self.thread._commands.empty())

    def test_no_error_is_logged_if_no_command_occurs_on_api_before_timeout(self):
        self.client.init()
        with self.assertNoLogs(logger=logger._logger, level=logging.ERROR):
            self.thread.poll_commands()
            time.sleep(self.thread.timeout_ms / 1000.0)

    def test_command_queue_is_not_empty_if_command_occurs_on_api_before_timeout(self):
        self.client.define_commands([(b"command1", Device(), 0)])
        self.thread.poll_commands()
        time.sleep(self.thread.timeout_ms / 1000.0)
        self.assertFalse(self.thread._commands.empty())
        self.assertEqual(self.thread.pop_command(), (b"command1", Device()))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
