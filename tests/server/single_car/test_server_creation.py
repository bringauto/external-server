import unittest
import sys
import concurrent.futures as futures
import time

sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from pydantic import FilePath

from InternalProtocol_pb2 import Device  # type: ignore
from external_server.config import CarConfig, ModuleConfig
from external_server.server import CarServer, ServerState
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH
from tests.utils.mqtt_broker import MQTTBrokerTest


ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "bring_auto",
    "car_name": "test_car",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 2,
    "timeout": 5,
    "send_invalid_command": False,
    "sleep_duration_after_connection_refused": 2,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000,
}


class Test_Creating_External_Server_Instance(unittest.TestCase):

    def setUp(self) -> None:
        self.example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )

    def test_module_dict_key_in_config_equal_to_the_module_id_is_accepted(self):
        correct_id = "1000"
        self.config = CarConfig(
            modules={correct_id: self.example_module_config}, **ES_CONFIG_WITHOUT_MODULES
        )
        self.es = CarServer(config=self.config)

    def test_module_dict_key_in_config_not_equal_to_the_module_id_raises_error(self):
        incorrect_id = "111111111"
        self.config = CarConfig(
            modules={incorrect_id: self.example_module_config}, **ES_CONFIG_WITHOUT_MODULES
        )
        with self.assertRaises(RuntimeError):
            self.es = CarServer(config=self.config)


class Test_Initial_State_Of_External_Server(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = CarConfig(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = CarServer(config=self.config)

    def test_external_server_initially_has_no_connected_devices(self):
        self.assertEqual(self.es._known_devices.n_connected, 0)

    def test_external_server_initially_has_mqtt_client_disconnected(self):
        self.assertFalse(self.es.mqtt.is_connected)

    def test_external_server_has_modules_created(self):
        self.assertEqual(len(self.es.modules), 1)
        self.assertIn(1000, self.es.modules)

    def test_all_devices_are_initialized(self):
        self.assertTrue(self.es.modules[1000].api.device_initialized())

    def test_session_id_is_empty(self):
        self.assertEqual(self.es.session_id, "")


class Test_Server_State(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = CarConfig(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = CarServer(config=self.config)

    def test_server_state_is_read_only(self):
        with self.assertRaises(AttributeError):
            self.es.state = ServerState.RUNNING


class Test_External_Server_Start(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = CarConfig(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = CarServer(config=self.config)
        self.device = Device(
            module=Device.EXAMPLE_MODULE, deviceType=0, deviceName="TestDevice", deviceRole="test"
        )
        self.mqttbroker = MQTTBrokerTest(start=True)
        time.sleep(0.2)

    def test_starting_and_stopping_server_connects_and_disconnects_the_mqtt_client(self):
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es.start)
            time.sleep(0.5)
            self.assertTrue(self.es.mqtt.is_connected)
            ex.submit(self.es.stop, reason="test")
            time.sleep(1)
            self.assertFalse(self.es.mqtt.is_connected)

    def tearDown(self) -> None:
        self.mqttbroker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
