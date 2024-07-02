import unittest
import sys
import os
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.external_server_api_client import ExternalServerApiClient
from external_server.config import ModuleConfig


EXAMPLE_MODULE_SO_LIB_PATH = \
    os.path.abspath("tests/utils/example-module/_build/libexample-external-server-sharedd.so")


class Test_Module_Config_Validation(unittest.TestCase):

    def test_valid_module_config_contains_config_dict_and_path_to_existing_lib(self):
        self.module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})

    def test_invalid_path_raises_validation_error(self):
        with self.assertRaises(ValueError):
            self.module_config = ModuleConfig(lib_path="invalid_path", config={})


class Test_API_Client(unittest.TestCase):

    def setUp(self):
        self.module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})

    def test_client_library_and_context_is_initially_empty(self):
        client = ExternalServerApiClient(
            module_config=self.module_config, company_name="BringAuto", car_name="Car1"
        )
        self.assertIsNone(client.library)
        self.assertIsNone(client.context)

    def test_client_initializes_library_and_context(self):
        client = ExternalServerApiClient(
            module_config=self.module_config, company_name="BringAuto", car_name="Car1"
        )
        client.init()
        self.assertIsNotNone(client.library)
        self.assertIsNotNone(client.context)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
