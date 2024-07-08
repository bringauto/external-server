import unittest
import sys
import concurrent.futures as futures
import time
sys.path.append(".")

from pydantic import FilePath

from InternalProtocol_pb2 import Device
from ExternalProtocol_pb2 import Connect, ExternalClient
from external_server.config import Config, ModuleConfig
from external_server.external_server import ExternalServer
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH, MQTTBrokerTest


ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "bring_auto",
    "car_name": "car_1",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 2,
    "timeout": 5,
    "send_invalid_command": False,
    "mqtt_client_connection_retry_period": 2,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000
}


class Test_Creating_External_Server_Instance(unittest.TestCase):

    def setUp(self) -> None:
        self.example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )

    def test_module_dict_key_in_config_equal_to_the_module_id_is_accepted(self):
        correct_id = "1000"
        self.config = Config(
            modules={correct_id: self.example_module_config}, **ES_CONFIG_WITHOUT_MODULES
        )
        self.es = ExternalServer(config=self.config)

    def test_module_dict_key_in_config_not_equal_to_the_module_id_raises_error(self):
        incorrect_id = "111111111"
        self.config = Config(
            modules={incorrect_id: self.example_module_config}, **ES_CONFIG_WITHOUT_MODULES
        )
        with self.assertRaises(RuntimeError):
            self.es = ExternalServer(config=self.config)


class Test_Initial_State_Of_External_Server(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = ExternalServer(config=self.config)

    def test_external_server_initially_has_no_connected_devices(self):
        self.assertEqual(self.es.connected_devices, [])

    def test_external_server_initially_has_mqtt_client_disconnected(self):
        self.assertFalse(self.es.mqtt_client.is_connected)

    def test_external_server_has_modules_created(self):
        self.assertEqual(len(self.es.modules), 1)
        self.assertTrue(1000 in self.es.modules)

    def test_all_devices_are_initialized(self):
        self.assertTrue(self.es.modules[1000].device_initialized())

    def test_session_id_is_empty(self):
        self.assertEqual(self.es.session_id, "")


class Test_External_Server_Start(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = Config(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = ExternalServer(config=self.config)
        self.device = Device(
            module = Device.EXAMPLE_MODULE,
            deviceType = 0,
            deviceName = "TestDevice",
            deviceRole = "test"
        )
        self.mqttbroker = MQTTBrokerTest(start=True)
        time.sleep(0.02)

    def test_external_server_starting_and_stopping(self):
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es.start)
            time.sleep(0.1)
            self.assertTrue(self.es.mqtt_client.is_connected)
            self.es.stop()
            time.sleep(0.5)
            self.assertFalse(self.es.mqtt_client.is_connected)


class Test_Connecting_Device(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = Config(
            modules={str(Device.EXAMPLE_MODULE): example_module_config},
            **ES_CONFIG_WITHOUT_MODULES
        )
        self.es = ExternalServer(config=self.config)
        self.device = Device(
            module = Device.EXAMPLE_MODULE,
            deviceType = 0,
            deviceName = "TestDevice",
            deviceRole = "test"
        )
        self.mqttbroker = MQTTBrokerTest(start=True)
        time.sleep(0.02)

    def test_connecting_device(self):
        connect_msg = Connect(
            sessionId="some_id",
            company="bring_auto",
            vehicleName="car_1",
            devices=[self.device]
        )
        with futures.ThreadPoolExecutor() as executor:
            executor.submit(self.es.start)
            time.sleep(0.2)
            msg_payload = ExternalClient(connect=connect_msg).SerializeToString()
            subsc_topic = self.es.mqtt_client.subscribe_topic
            executor.submit(self.mqttbroker.publish_message, topic=subsc_topic, payload=msg_payload)
            time.sleep(0.2)
            self.es.stop()
            time.sleep(0.1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()