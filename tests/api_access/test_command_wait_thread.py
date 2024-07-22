import unittest
import sys
import time

sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.adapters.api_adapter import APIClientAdapter
from external_server.command_waiting_thread import CommandWaitingThread
from external_server.config import ModuleConfig
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH


class Test_Creating_Command_Waiting_Thread(unittest.TestCase):

    def setUp(self) -> None:
        self.module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})  # type: ignore
        self.client = APIClientAdapter(config=self.module_config, company="BringAuto", car="Car1")
        self.client.init()
        self.module_connected = False
        self.thread = CommandWaitingThread(self.client, lambda: self.module_connected)
        self.thread.TIMEOUT = 500

    def test_thread_is_initially_not_started(self):
        self.assertFalse(self.thread._waiting_thread.is_alive())

    def test_thread_is_started(self):
        self.thread.start()
        self.assertTrue(self.thread._waiting_thread.is_alive())

    def test_thread_is_stopped_after_request_timeout_passes(self):
        self.thread.start()
        self.thread.stop()
        self.assertTrue(self.thread._waiting_thread.is_alive())
        time.sleep(self.thread.TIMEOUT/1000.0)
        self.assertFalse(self.thread._waiting_thread.is_alive())

    def tearDown(self) -> None:
        self.thread.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
