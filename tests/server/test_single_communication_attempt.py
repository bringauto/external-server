import unittest
import sys
import time
import concurrent.futures as futures

sys.path.append(".")

from pydantic import FilePath

from external_server.server import ExternalServer, ServerState
from InternalProtocol_pb2 import Device, DeviceStatus  # type: ignore
from ExternalProtocol_pb2 import Status, CommandResponse  # type: ignore
from external_server.config import Config, ModuleConfig
from external_server.models.exceptions import ConnectSequenceFailure
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH, MQTTBrokerTest
from external_server.utils import connect_msg, status, cmd_response


ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "ba",
    "car_name": "car1",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 1,
    "timeout": 1,
    "send_invalid_command": False,
    "mqtt_client_connection_retry_period": 2,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000,
}


class Test_Initial_State(unittest.TestCase):

    def setUp(self):
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = ExternalServer(config=config)
        MQTTBrokerTest.kill_all_test_brokers()

    def test_initial_server_state_is_uninitialized(self):
        self.assertEqual(self.es.state, ServerState.UNINITIALIZED)


class Test_Intializing_Server_Communication_Without_Running_Broker(unittest.TestCase):

    def setUp(self):
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = ExternalServer(config=config)
        MQTTBrokerTest.kill_all_test_brokers()

    def test_without_running_broker_raises_error_and_sets_state_to_error(self):
        with self.assertRaises(ConnectionRefusedError):
            self.es._initialize()
        self.assertEqual(self.es.state, ServerState.ERROR)


class Test_Initializing_Server_Communication_With_Running_Broker_And_Single_Configured_Device(unittest.TestCase):

    def setUp(self):
        MQTTBrokerTest.kill_all_test_brokers()
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = ExternalServer(config=config)
        self.broker = MQTTBrokerTest()
        self.broker.start()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")

    def test_without_receiving_connect_message_sets_the_state_to_error(self):
        with self.assertRaises(ConnectSequenceFailure):
            self.es._initialize()
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_without_receiving_first_statuses_sets_the_state_to_error(self):
        broker = self.broker
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._initialize)
            broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_without_receiving_command_responses_sets_the_state_to_error(self):
        broker = self.broker
        device_status = DeviceStatus(device=self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._initialize)
            broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_with_receiving_command_responses_sets_the_state_to_initialized(self):
        broker = self.broker
        device_status = DeviceStatus(device=self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._initialize)
            time.sleep(0.1)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)

    def test_with_receiving_status_with_other_state_than_connecting_raises_error(self):
        broker = self.broker
        device_status = DeviceStatus(device=self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._initialize)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            broker.publish(topic, status("session_id", Status.DISCONNECT, 0, device_status))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_with_receiving_command_response_with_other_state_than_ok_sets_state_to_initialized(self):
        broker = self.broker
        time.sleep(0.1)
        device_status = DeviceStatus(device=self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._initialize)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)

    def tearDown(self):
        self.es.mqtt.stop()
        self.broker.stop()


if __name__=="__main__":  # pragma: no cover
    unittest.main()