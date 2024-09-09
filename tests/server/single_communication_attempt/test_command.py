import unittest
from unittest.mock import Mock, patch
import logging
import sys

sys.path.append(".")

from InternalProtocol_pb2 import Device  # type: ignore
from ExternalProtocol_pb2 import CommandResponse, ExternalServer as ExternalServerMsg  # type: ignore
from external_server.server import logger as es_logger
from external_server.checkers.command_checker import logger as command_checker_logger
from external_server.models.structures import HandledCommand
from external_server.models.messages import cmd_response
from tests.utils import get_test_server, MQTTBrokerTest
from external_server.models.exceptions import ConnectSequenceFailure


class Test_Handling_Command(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.es.mqtt.connect()
        self.es._add_connected_devices(self.device_1)
        self.es._mqtt_session.set_id("id")

    @patch("external_server.checkers.command_checker.CommandQueue.get")
    def test_missing_expected_commands_response_raises_exception(self, mock: Mock):
        mock.return_value = None
        with self.assertRaises(ConnectSequenceFailure):
            self.es._get_next_valid_command_response()

    def tearDown(self) -> None:
        self.es.mqtt.disconnect()
        self.broker.stop()


class Test_Handling_Command_Response(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.published_responses: list[ExternalServerMsg] = list()
        self.es._add_connected_devices(self.device)
        self.es._mqtt_session.set_id("id")

    def test_to_sent_command_logs_info_and_empties_checked_commands(self):
        self.es._command_checker.add(HandledCommand(data=b"cmd", counter=0, device=self.device))
        self.es.mqtt._received_msgs.put(cmd_response("id", 0, CommandResponse.OK) )
        self.assertEqual(self.es._command_checker.n_of_commands, 1)
        with self.assertLogs(es_logger, level=logging.INFO):
            self.es._handle_car_message()
            self.assertEqual(self.es._command_checker.n_of_commands, 0)

    def test_to_command_not_sent_logs_warning_and_empties_checked_commands(self):
        self.es.mqtt._received_msgs.put(cmd_response("id", 0, CommandResponse.OK))
        self.assertEqual(self.es._command_checker.n_of_commands, 0)
        with self.assertLogs(command_checker_logger, level=logging.WARNING) as cm:
            self.es._handle_car_message()
            self.assertIn("no commands", cm.output[0].lower())

    def test_to_sent_command_but_with_session_id_not_matching_server_logs_warning_and_does_not_accept_response(self):
        self.es._command_checker.add(HandledCommand(data=b"cmd", counter=0, device=self.device))
        self.es.mqtt._received_msgs.put(cmd_response("wrong_id", 0, CommandResponse.OK))
        with self.assertLogs(es_logger, level=logging.WARNING) as cm:
            self.es._handle_car_message()
            self.assertIn("session id", cm.output[0].lower())
            # the response has not been accepted, checker still expects the response
            self.assertEqual(self.es._command_checker.n_of_commands, 1)

    def test_to_sent_command_but_with_counter_not_matching_server_logs_warning_and_does_not_accept_response(self):
        self.es._command_checker.add(HandledCommand(data=b"cmd", counter=0, device=self.device))
        self.es.mqtt._received_msgs.put(cmd_response("id", 1, CommandResponse.OK))
        with self.assertLogs(command_checker_logger, level=logging.WARNING) as cm:
            self.es._handle_car_message()
            self.assertIn("counter", cm.output[0].lower())
            # the response has not been accepted, checker still expects the response
            self.assertEqual(self.es._command_checker.n_of_commands, 1)


class Test_Command_Response_With_Type_Device_Not_Connected(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server()
        self.device_1 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test1")
        self.device_2 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test2")
        self.published_responses: list[ExternalServerMsg] = list()
        self.es._add_connected_devices(self.device_1, self.device_2)
        self.es._mqtt_session.set_id("id")

    def test_with_counter_matching_oldest_command_disconnects_device(self):
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.es._handle_command(module_id=1000, data=b"cmd", device=self.device_1)
        self.es._handle_command_response(cmd_response("id", 0, CommandResponse.DEVICE_NOT_CONNECTED).commandResponse)
        self.assertFalse(self.es._known_devices.is_connected(self.device_1))
        self.assertTrue(self.es._known_devices.is_connected(self.device_2))

    def test_with_counter_matching_newer_command_still_disconnects_device(self):
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.es._handle_command(module_id=1000, data=b"cmd", device=self.device_1)
        self.es._handle_command(module_id=1000, data=b"cmd", device=self.device_1)
        self.es._handle_command_response(cmd_response("id", 1, CommandResponse.DEVICE_NOT_CONNECTED).commandResponse)
        self.assertFalse(self.es._known_devices.is_connected(self.device_1))
        self.assertTrue(self.es._known_devices.is_connected(self.device_2))

    def test_with_counter_not_matching_any_published_command_does_not_disconnect_device(self):
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.es._handle_command(module_id=1000, data=b"cmd", device=self.device_1) # counter=0
        self.es._handle_command(module_id=1000, data=b"cmd", device=self.device_1)  # counter=1
        self.es._handle_command_response(cmd_response("id", 2, CommandResponse.DEVICE_NOT_CONNECTED).commandResponse)
        # device remains connected - the response was not relevant to any command
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        self.assertTrue(self.es._known_devices.is_connected(self.device_2))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
