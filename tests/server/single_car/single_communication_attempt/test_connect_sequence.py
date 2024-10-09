import unittest
import sys
import time
import concurrent.futures as futures
from unittest.mock import Mock, patch

sys.path.append(".")

from external_server.server import ServerState
from InternalProtocol_pb2 import Device  # type: ignore
from ExternalProtocol_pb2 import (  # type: ignore
    ExternalServer as ExternalServerMsg,
    Status,
    CommandResponse
)
from external_server.models.exceptions import ConnectSequenceFailure
from external_server.models.devices import DevicePy, device_status as _device_status
from tests.utils.mqtt_broker import MQTTBrokerTest
from tests.utils import get_test_car_server
from external_server.models.messages import connect_msg, status, cmd_response


class Test_Initial_State(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()

    def test_initial_server_state_is_uninitialized(self):
        self.assertEqual(self.es.state, ServerState.UNINITIALIZED)


class Test_Intializing_Server_Communication_Without_Running_Broker(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()

    def test_without_running_broker_raises_error(self):
        with self.assertRaises(ConnectionRefusedError):
            self.es._run_initial_sequence()


class Test_Initializing_Server_Communication_With_Running_Broker_And_Single_Configured_Device(
    unittest.TestCase
):

    def setUp(self):
        self.es = get_test_car_server()
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
            broker.publish(topic, connect_msg("id", "company", [self.device]))
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_without_receiving_command_responses_sets_the_state_to_error(self):
        broker = self.broker
        device_status = _device_status(self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            broker.publish(topic, connect_msg("id", "company", [self.device]))
            broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_with_receiving_command_responses_sets_the_state_to_initialized(self):
        broker = self.broker
        device_status = _device_status(self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.1)
            broker.publish(topic, connect_msg("id", "company", [self.device]))
            broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
            broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)

    def test_with_receiving_status_with_other_state_than_connecting_raises_error(self):
        broker = self.broker
        device_status = _device_status(self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            broker.publish(topic, connect_msg("id", "company", [self.device]))
            broker.publish(topic, status("id", Status.DISCONNECT, 0, device_status))
            broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.ERROR)

    def test_with_receiving_command_response_with_other_state_than_ok_sets_state_to_initialized(
        self,
    ):
        broker = self.broker
        time.sleep(0.1)
        device_status = _device_status(self.device)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            broker.publish(topic, connect_msg("id", "company", [self.device]))
            broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
            broker.publish(topic, cmd_response("id", 0, CommandResponse.DEVICE_NOT_CONNECTED))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)

    def tearDown(self):
        self.es.mqtt.stop()
        self.broker.stop()


class Test_Connecting_Device_Unsupported_By_Supported_Module(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
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
                connect_msg("id", "company", [self.supported, self.unsupported]),
            )
            supported_status = _device_status(self.supported)
            unsupported_status = _device_status(self.unsupported)
            broker.publish(topic, status("id", Status.CONNECTING, 0, supported_status))
            broker.publish(topic, status("id", Status.CONNECTING, 1, unsupported_status))
            broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("id", 1, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es._known_devices.is_connected(self.supported))
        self.assertFalse(self.es._known_devices.is_connected(self.unsupported))

    def tearDown(self):
        self.es.mqtt.stop()
        self.broker.stop()


class Test_Successful_Initialization_With_Multiple_Devices(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.device_2 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_2")
        self.device_3 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_3")

    def test_initialization_with_mutliple_supported_devices_connects_them_all(self):
        broker = self.broker
        device_status_1 = _device_status(self.device_1)
        device_status_2 = _device_status(self.device_2)
        device_status_3 = _device_status(self.device_3)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            broker.publish(
                topic,
                connect_msg("id", "company", [self.device_1, self.device_2, self.device_3]),
            )
            broker.publish(topic, status("id", Status.CONNECTING, 0, device_status_1))
            broker.publish(topic, status("id", Status.CONNECTING, 1, device_status_2))
            broker.publish(topic, status("id", Status.CONNECTING, 1, device_status_3))
            broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("id", 2, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.assertTrue(self.es._known_devices.is_connected(self.device_2))
        self.assertTrue(self.es._known_devices.is_connected(self.device_3))

    def test_initialization_with_mutliple_supported_devices_sending_first_statuses_in_wrong_order_connects_them_anyway(
        self,
    ):
        broker = self.broker
        device_status_1 = _device_status(self.device_1)
        device_status_2 = _device_status(self.device_2)
        device_status_3 = _device_status(self.device_3)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            broker.publish(
                topic,
                connect_msg("id", "company", [self.device_1, self.device_2, self.device_3]),
            )
            broker.publish(topic, status("id", Status.CONNECTING, 0, device_status_2))
            broker.publish(topic, status("id", Status.CONNECTING, 2, device_status_3))
            broker.publish(topic, status("id", Status.CONNECTING, 1, device_status_1))
            broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("id", 2, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.assertTrue(self.es._known_devices.is_connected(self.device_2))
        self.assertTrue(self.es._known_devices.is_connected(self.device_3))

    def test_initialization_with_mutliple_supported_devices_sending_command_responses_in_wrong_order_connects_them_anyway(
        self,
    ):
        broker = self.broker
        device_status_1 = _device_status(self.device_1)
        device_status_2 = _device_status(self.device_2)
        device_status_3 = _device_status(self.device_3)
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            broker.publish(
                topic,
                connect_msg("id", "company", [self.device_1, self.device_2, self.device_3]),
            )
            broker.publish(topic, status("id", Status.CONNECTING, 0, device_status_1))
            broker.publish(topic, status("id", Status.CONNECTING, 1, device_status_2))
            broker.publish(topic, status("id", Status.CONNECTING, 2, device_status_3))
            broker.publish(topic, cmd_response("id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("id", 2, CommandResponse.OK))
            broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.assertTrue(self.es._known_devices.is_connected(self.device_2))
        self.assertTrue(self.es._known_devices.is_connected(self.device_3))

    def tearDown(self) -> None:
        self.es.mqtt.stop()
        self.broker.stop()


class Test_Partially_Unsuccessful_Initialization_With_Multiple_Devices(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.device_2 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_2")
        self.device_3 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_3")

    def test_missed_status_sets_server_state_to_error_and_raises_exception(self):
        broker = self.broker
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            future = ex.submit(self.es._run_initial_sequence)
            broker.publish(
                topic,
                connect_msg("id", "company", [self.device_1, self.device_2, self.device_3]),
            )
            broker.publish(topic, status("id", Status.CONNECTING, 0, _device_status(self.device_1)))
            broker.publish(topic, status("id", Status.CONNECTING, 1, _device_status(self.device_2)))
            broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
            broker.publish(topic, cmd_response("id", 1, CommandResponse.OK))
            broker.publish(topic, cmd_response("id", 2, CommandResponse.OK))
            time.sleep(0.01)
            with self.assertRaises(ConnectSequenceFailure):
                future.result(timeout=10.0)
        self.assertEqual(self.es.state, ServerState.ERROR)

    def tearDown(self) -> None:
        self.es.mqtt.stop()
        self.broker.stop()


class Test_First_Command(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(
            self.es.mqtt.publish_topic,
            start=True
        )
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test")
        self.es.mqtt.connect()

    def test_no_known_devices_raise_error(self):
        with self.assertRaises(ConnectSequenceFailure):
            self.es._get_and_send_first_commands()

    def test_first_command_is_sent_to_a_single_connected_device(self):
        self.es._known_devices.connected(DevicePy.from_device(self.device_1))
        with futures.ThreadPoolExecutor() as ex:
            self.broker.clear_messages(self.es.mqtt.publish_topic)
            ex.submit(self.es._get_and_send_first_commands)
            sent_commands = self.broker.wait_for_messages(self.es.mqtt.publish_topic, 1)
            self.assertEqual(ExternalServerMsg.FromString(sent_commands[0]).command.messageCounter, 0)

    def tearDown(self) -> None:
        self.es.mqtt.stop()
        self.broker.stop()


@patch("external_server.adapters.api.module_lib.ModuleLibrary.forward_status")
@patch("external_server.adapters.mqtt.adapter.MQTTClientAdapter.get_status")
class Test_Forwarding_First_Status(unittest.TestCase):

    def forward_status(self, buffer: bytes, device: Device) -> int:
        self.forwarded_statuses.append((buffer, device))
        return 0

    def setUp(self):
        self.es = get_test_car_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.es._mqtt.session.set_id("id")
        self.forwarded_statuses = list()

    def test_status_from_supported_device_is_forwarded(self, mock_get: Mock, mock_forward: Mock):
        mock_forward.side_effect = self.forward_status
        mock_get.return_value = status(
            "id", Status.CONNECTING, 1, _device_status(self.device)
        ).status
        self.es._handle_init_connect(connect_msg("id", "company", [self.device]).connect)
        self.es._get_all_first_statuses_and_respond()
        self.assertEqual(len(self.forwarded_statuses), 1)

    def test_status_from_unsupported_device_is_not_forwarded(self, mock_g: Mock, mock_f: Mock):
        mock_f.side_effect = self.forward_status
        unsup_device = Device(module=1000, deviceType=123, deviceName="Test", deviceRole="test")
        mock_g.side_effect = (  # pragma: no cover
            r
            for r in [
                status("id", Status.CONNECTING, 1, _device_status(unsup_device)).status,
                None,
            ]
        )
        self.es._handle_init_connect(connect_msg("id", "company", [self.device]).connect)
        self.es._get_all_first_statuses_and_respond()
        self.assertEqual(len(self.forwarded_statuses), 0)

    def test_status_from_device_not_in_connect_message_is_not_forwarded(
        self, mock_g: Mock, mock_f: Mock
    ):
        mock_f.side_effect = self.forward_status
        other_device = Device(module=1000, deviceType=777, deviceName="Other", deviceRole="test")
        mock_g.side_effect = (  # pragma: no cover
            r
            for r in [
                status("id", Status.CONNECTING, 1, _device_status(other_device)).status,
                None,
            ]
        )
        self.es._handle_init_connect(
            connect_msg("id", "company", [self.device, other_device]).connect
        )
        self.es._get_all_first_statuses_and_respond()
        self.assertEqual(len(self.forwarded_statuses), 0)

    def test_statuses_from_connected_devices_are_forwarded_in_order_they_were_received(
        self, mock_g: Mock, mock_f: Mock
    ):
        mock_f.side_effect = self.forward_status
        device_1 = Device(module=1000, deviceType=0, deviceName="Other device", deviceRole="test1")
        device_2 = Device(module=1000, deviceType=0, deviceName="Other device", deviceRole="test2")
        device_3 = Device(module=1000, deviceType=0, deviceName="Other device", deviceRole="test3")
        self.es._handle_init_connect(
            connect_msg("id", "company", [device_1, device_2, device_3]).connect
        )
        mock_g.side_effect = (  # pragma: no cover
            r
            for r in [
                status(
                    "id", Status.CONNECTING, 1, _device_status(device_1, b"from_device_1")
                ).status,
                status(
                    "id", Status.CONNECTING, 2, _device_status(device_3, b"from_device_3")
                ).status,
                status(
                    "id", Status.CONNECTING, 3, _device_status(device_2, b"from_device_2")
                ).status,
            ]
        )
        self.es._get_all_first_statuses_and_respond()
        self.assertEqual(len(self.forwarded_statuses), 3)
        self.assertEqual(self.forwarded_statuses[0][0].data, b"from_device_1")
        self.assertEqual(self.forwarded_statuses[1][0].data, b"from_device_3")
        self.assertEqual(self.forwarded_statuses[2][0].data, b"from_device_2")

    def test_status_from_not_connected_device_is_forwarded(self, mock_g: Mock, mock_f: Mock):
        mock_f.side_effect = self.forward_status
        device_1 = Device(module=1000, deviceType=0, deviceName="Other device", deviceRole="test1")
        device_2 = Device(module=1000, deviceType=0, deviceName="Other device", deviceRole="test2")
        not_connected = Device(
            module=1000, deviceType=0, deviceName="Other device", deviceRole="test3"
        )
        self.es._handle_init_connect(connect_msg("id", "company", [device_1, device_2]).connect)
        mock_g.side_effect = (  # pragma: no cover
            r
            for r in [
                status(
                    "id", Status.CONNECTING, 1, _device_status(device_1, b"from_device_1")
                ).status,
                status(
                    "id", Status.CONNECTING, 2, _device_status(not_connected, b"from_not_connected")
                ).status,
                status(
                    "id", Status.CONNECTING, 3, _device_status(device_2, b"from_device_2")
                ).status,
            ]
        )
        self.es._get_all_first_statuses_and_respond()
        self.assertEqual(len(self.forwarded_statuses), 3)
        self.assertEqual(self.forwarded_statuses[0][0].data, b"from_device_1")
        self.assertEqual(self.forwarded_statuses[1][0].data, b"from_not_connected")
        self.assertEqual(self.forwarded_statuses[2][0].data, b"from_device_2")

    def tearDown(self) -> None:
        self.es.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
