import unittest
import sys
import time
import concurrent.futures as futures

sys.path.append(".")

from external_server.server import ServerState, logger
from InternalProtocol_pb2 import Device, DeviceStatus  # type: ignore
from ExternalProtocol_pb2 import Status, CommandResponse  # type: ignore
from external_server.models.exceptions import ConnectSequenceFailure
from external_server.models.devices import DevicePy
from tests.utils import MQTTBrokerTest, get_test_server
from external_server.models.messages import connect_msg, status, cmd_response


logger.setLevel("DEBUG")


class Test_Initial_State(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()

    def test_initial_server_state_is_uninitialized(self):
        self.assertEqual(self.es.state, ServerState.UNINITIALIZED)


class Test_Intializing_Server_Communication_Without_Running_Broker(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()

    def test_without_running_broker_raises_error(self):
        with self.assertRaises(ConnectionRefusedError):
            self.es._run_initial_sequence()


class Test_Initializing_Server_Communication_With_Running_Broker_And_Single_Configured_Device(
    unittest.TestCase
):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test")

    def test_without_receiving_connect_message_sets_the_state_to_error(self):
        with self.assertRaises(ConnectSequenceFailure):
            self.es._run_initial_sequence()
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_without_receiving_first_statuses_sets_the_state_to_error(self):
        broker = self.broker
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_without_receiving_command_responses_sets_the_state_to_error(self):
        broker = self.broker
        device_status = DeviceStatus(device=self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_with_receiving_command_responses_sets_the_state_to_initialized(self):
        broker = self.broker
        device_status = DeviceStatus(device=self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
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
            ex.submit(self.es._run_initial_sequence)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            broker.publish(topic, status("session_id", Status.DISCONNECT, 0, device_status))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_with_receiving_command_response_with_other_state_than_ok_sets_state_to_initialized(
        self,
    ):
        broker = self.broker
        time.sleep(0.1)
        device_status = DeviceStatus(device=self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            broker.publish(
                topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED)
            )
        self.assertEqual(self.es.state, ServerState.INITIALIZED)

    def tearDown(self):
        self.es.mqtt.stop()
        self.broker.stop()


class Test_Connecting_Device_Unsupported_By_Supported_Module(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        # device type 123456 is not supported by module 1000
        self.unsupported = Device(
            module=1000, deviceType=123456, deviceName="Test", deviceRole="test"
        )
        self.supported = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test")

    def test_device_is_not_connected(self):
        broker = self.broker
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.1)
            broker.publish(
                topic,
                connect_msg("session_id", "company", "car", [self.supported, self.unsupported]),
            )
            supported_status = DeviceStatus(device=self.supported)
            unsupported_status = DeviceStatus(device=self.unsupported)
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, supported_status))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, unsupported_status))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 1, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es._known_devices.is_connected(self.supported))
        self.assertFalse(self.es._known_devices.is_connected(self.unsupported))

    def tearDown(self):
        self.es.mqtt.stop()
        self.broker.stop()


class Test_Successful_Initialization_With_Multiple_Devices(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.device_2 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_2")
        self.device_3 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_3")

    def test_initialization_with_mutliple_supported_devices_connects_them_all(self):
        broker = self.broker
        device_status_1 = DeviceStatus(device=self.device_1)
        device_status_2 = DeviceStatus(device=self.device_2)
        device_status_3 = DeviceStatus(device=self.device_3)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            broker.publish(
                topic,
                connect_msg(
                    "session_id", "company", "car", [self.device_1, self.device_2, self.device_3]
                ),
            )
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status_1))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, device_status_2))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, device_status_3))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 2, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.assertTrue(self.es._known_devices.is_connected(self.device_2))
        self.assertTrue(self.es._known_devices.is_connected(self.device_3))

    def test_initialization_with_mutliple_supported_devices_sending_first_statuses_in_wrong_order_connects_them_anyway(
        self,
    ):
        broker = self.broker
        device_status_1 = DeviceStatus(device=self.device_1)
        device_status_2 = DeviceStatus(device=self.device_2)
        device_status_3 = DeviceStatus(device=self.device_3)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            broker.publish(
                topic,
                connect_msg(
                    "session_id", "company", "car", [self.device_1, self.device_2, self.device_3]
                ),
            )
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status_2))
            broker.publish(topic, status("session_id", Status.CONNECTING, 2, device_status_3))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, device_status_1))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 2, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.assertTrue(self.es._known_devices.is_connected(self.device_2))
        self.assertTrue(self.es._known_devices.is_connected(self.device_3))

    def test_initialization_with_mutliple_supported_devices_sending_command_responses_in_wrong_order_connects_them_anyway(
        self,
    ):
        broker = self.broker
        device_status_1 = DeviceStatus(device=self.device_1)
        device_status_2 = DeviceStatus(device=self.device_2)
        device_status_3 = DeviceStatus(device=self.device_3)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            broker.publish(
                topic,
                connect_msg(
                    "session_id", "company", "car", [self.device_1, self.device_2, self.device_3]
                ),
            )
            broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status_1))
            broker.publish(topic, status("session_id", Status.CONNECTING, 1, device_status_2))
            broker.publish(topic, status("session_id", Status.CONNECTING, 2, device_status_3))
            broker.publish(topic, cmd_response("session_id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 2, CommandResponse.OK))
            broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.assertTrue(self.es._known_devices.is_connected(self.device_2))
        self.assertTrue(self.es._known_devices.is_connected(self.device_3))

    def tearDown(self) -> None:
        self.es.mqtt.stop()
        self.broker.stop()
        time.sleep(0.1)


class Test_Partially_Unsuccessful_Initialization_With_Multiple_Devices(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.device_2 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_2")
        self.device_3 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_3")

    def test_initialization_in_wrong_order_sets_server_state_to_error_and_raises_exception(self):
        broker = self.broker
        device_status_1 = DeviceStatus(device=self.device_1)
        device_status_2 = DeviceStatus(device=self.device_2)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            future = ex.submit(self.es._run_initial_sequence)
            broker.publish(
                topic,
                connect_msg(
                    "session_id", "company", "car", [self.device_1, self.device_2, self.device_3]
                ),
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

    def tearDown(self) -> None:
        self.es.mqtt.stop()
        self.broker.stop()


class Test_First_Command(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test")
        self.es.mqtt.connect()

    def test_no_known_devices_raise_error(self):
        with self.assertRaises(ConnectSequenceFailure):
            self.es._get_and_send_first_commands()

    def test_first_command_is_sent_to_a_single_connected_device(self):
        self.es._known_devices.connected(DevicePy.from_device(self.device_1))
        with futures.ThreadPoolExecutor() as ex:
            f = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=1)
            time.sleep(0.1)
            ex.submit(self.es._get_and_send_first_commands)
            sent_commands = f.result()
            self.assertEqual(len(sent_commands), 1)

    def tearDown(self) -> None:
        self.es.mqtt.stop()
        self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
