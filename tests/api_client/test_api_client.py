import unittest
import sys
sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.adapters.api_adapter import APIClientAdapter
from InternalProtocol_pb2 import Device  # type: ignore
from external_server.config import ModuleConfig
from external_server.models.structures import DisconnectTypes
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH


class Test_Module_Config_Validation(unittest.TestCase):

    def test_valid_module_config_contains_config_dict_and_path_to_existing_lib(self):
        self.module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})

    def test_invalid_path_raises_validation_error(self):
        with self.assertRaises(ValueError):
            self.module_config = ModuleConfig(lib_path="invalid_path", config={})


class Test_API_Client_Loading_Shared_Library(unittest.TestCase):

    def setUp(self):
        self.module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})

    def test_client_library_and_context_is_initially_empty(self):
        client = APIClientAdapter(
            module_config=self.module_config, company_name="BringAuto", car_name="Car1"
        )
        self.assertIsNone(client.library)
        self.assertIsNone(client.context)

    def test_client_initializes_library_and_context(self):
        client = APIClientAdapter(
            module_config=self.module_config, company_name="BringAuto", car_name="Car1"
        )
        client.init()
        self.assertIsNotNone(client.library)
        self.assertIsNotNone(client.context)


class Test_API_Client_Device_Connection(unittest.TestCase):

    def setUp(self):
        self.module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})
        self.client = APIClientAdapter(
            module_config=self.module_config, company_name="BringAuto", car_name="Car1"
        )
        self.device = Device(
        module=Device.EXAMPLE_MODULE, deviceType=2, deviceRole="testing", deviceName="TestDevice", priority=1
        )

    def test_device_connected_with_valid_device_object_and_get_successful_result(self):
        self.client.init()
        code = self.client.device_connected(self.device)
        self.assertEqual(code, 0)

    def test_device_disconnected_with_valid_device_object_and_get_successful_result(self):
        self.client.init()
        self.client.device_connected(self.device)
        code = self.client.device_disconnected(DisconnectTypes.announced, self.device)
        self.assertEqual(code, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
