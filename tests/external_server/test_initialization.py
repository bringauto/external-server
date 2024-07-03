import unittest
import sys
import os
sys.path.append(".")

import pydantic
from pydantic import FilePath

from external_server.config import Config, ModuleConfig
from external_server.external_server import ExternalServer
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH


ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "bring_auto",
    "car_name": "car_1",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1884,
    "mqtt_timeout": 4,
    "timeout": 5,
    "send_invalid_command": False,
    "sleep_duration_after_connection_refused": 7,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000
}


class Test_External_Server_Initialization(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = ExternalServer(config=self.config)

    def test_external_server_initially_has_no_connected_devices(self):
        self.assertEqual(self.es.connected_devices, [])



if __name__ == "__main__":  # pragma: no cover
    unittest.main()