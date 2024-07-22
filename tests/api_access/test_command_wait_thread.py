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

    def test_connection_is_initially_not_estabilished(self):
        self.assertFalse(self.thread.connection_established)

    def tearDown(self) -> None:
        self.thread.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
