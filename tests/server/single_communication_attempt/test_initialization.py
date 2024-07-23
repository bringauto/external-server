import unittest
import sys
import time
import concurrent.futures as futures

sys.path.append(".")

from external_server.server import ServerState
from InternalProtocol_pb2 import Device, DeviceStatus  # type: ignore
from ExternalProtocol_pb2 import Status, CommandResponse  # type: ignore
from external_server.models.exceptions import ConnectSequenceFailure
from tests.utils import MQTTBrokerTest, get_test_server
from external_server.utils import connect_msg, status, cmd_response


class Test_Initial_State(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()

    def test_initial_server_state_is_uninitialized(self):
        self.assertEqual(self.es.state, ServerState.UNINITIALIZED)


class Test_Intializing_Server_Communication_Without_Running_Broker(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()

    def test_without_running_broker_raises_error_and_sets_state_to_error(self):
        with self.assertRaises(ConnectionRefusedError):
            result = self.es._initialize()
        self.assertEqual(self.es.state, ServerState.ERROR)


class Test_Initializing_Server_Communication_With_Running_Broker_And_Single_Configured_Device(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
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


class Test_Successful_Initialization_With_Multiple_Devices(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=10, deviceName="TestDevice", deviceRole="test_1")
        self.device_2 = Device(module=1000, deviceType=10, deviceName="TestDevice", deviceRole="test_2")
        self.device_3 = Device(module=1000, deviceType=10, deviceName="TestDevice", deviceRole="test_3")

    def test_initialization_with_mutliple_supported_devices_connects_them_all(self):
        broker = self.broker
        device_status_1 = DeviceStatus(device=self.device_1)
        device_status_2 = DeviceStatus(device=self.device_2)
        device_status_3 = DeviceStatus(device=self.device_3)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._initialize)
            time.sleep(0.2)
            broker.publish(
                topic,
                connect_msg("session_id", "company", "car", [self.device_1, self.device_2, self.device_3])
            )
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status_1))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, device_status_2))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, device_status_3))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 2, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es.is_supported(self.device_1))
        self.assertTrue(self.es.is_supported(self.device_2))
        self.assertTrue(self.es.is_supported(self.device_3))

    def test_initialization_with_mutliple_supported_devices_sending_first_statuses_in_wrong_order_connects_them_anyway(self):
        broker = self.broker
        device_status_1 = DeviceStatus(device=self.device_1)
        device_status_2 = DeviceStatus(device=self.device_2)
        device_status_3 = DeviceStatus(device=self.device_3)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._initialize)
            broker.publish(
                topic,
                connect_msg("session_id", "company", "car", [self.device_1, self.device_2, self.device_3])
            )
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status_2))
            broker.publish(topic, status("session_id", Status.CONNECTING, 2, device_status_3))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, device_status_1))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 2, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es.is_supported(self.device_1))
        self.assertTrue(self.es.is_supported(self.device_2))
        self.assertTrue(self.es.is_supported(self.device_3))

    def test_initialization_with_mutliple_supported_devices_sending_command_responses_in_wrong_order_connects_them_anyway(self):
        broker = self.broker
        device_status_1 = DeviceStatus(device=self.device_1)
        device_status_2 = DeviceStatus(device=self.device_2)
        device_status_3 = DeviceStatus(device=self.device_3)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._initialize)
            broker.publish(
                topic,
                connect_msg("session_id", "company", "car", [self.device_1, self.device_2, self.device_3])
            )
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status_1))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, device_status_2))
            broker.publish(topic, status("session_id", Status.CONNECTING, 2, device_status_3))
            broker.publish(topic, cmd_response("session_id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 2, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es.is_supported(self.device_1))
        self.assertTrue(self.es.is_supported(self.device_2))
        self.assertTrue(self.es.is_supported(self.device_3))

    def tearDown(self) -> None:
        self.es.mqtt.stop()
        self.broker.stop()


class Test_Partially_Unsuccessful_Initialization_With_Multiple_Devices(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        self.device_2 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_2")
        self.device_3 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_3")

    def test_initialization_in_wrong_order_sets_server_state_to_error_and_raises_exception(self):
        broker = self.broker
        device_status_1 = DeviceStatus(device=self.device_1)
        device_status_2 = DeviceStatus(device=self.device_2)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            future = ex.submit(self.es._initialize)
            broker.publish(
                topic,
                connect_msg("session_id", "company", "car", [self.device_1, self.device_2, self.device_3])
            )
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status_1))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, device_status_2))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 2, CommandResponse.OK))
            time.sleep(0.01)
            with self.assertRaises(ConnectSequenceFailure):
                future.result()
        self.assertEqual(self.es.state, ServerState.ERROR)


if __name__=="__main__":  # pragma: no cover
    unittest.main(verbosity=2)