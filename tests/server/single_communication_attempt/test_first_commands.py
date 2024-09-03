import unittest
import sys
from unittest.mock import patch, Mock

sys.path.append(".")

from InternalProtocol_pb2 import Device  # type: ignore
from external_server.models.structures import HandledCommand
from external_server.models.messages import cmd_response
from external_server.models.exceptions import ConnectSequenceFailure
from ExternalProtocol_pb2 import CommandResponse  # type: ignore
from tests.utils import get_test_server, MQTTBrokerTest


class Test_Commands_For_Single_Connected_Device(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test")
        self.es.mqtt.connect()
        self.es._add_connected_device(self.device_1)

    def test_empty_command_is_returned_if_thread_commands_queue_is_empty(self):
        cmds = self.es._collect_first_commands_for_init_sequence()
        self.assertEqual(cmds, [HandledCommand(b"", device=self.device_1, from_api=False)])

    def test_single_command_is_returned_if_thread_commands_contain_one_cmd(self):
        self.es.modules[1000].thread._commands.put(b"test", self.device_1)
        cmds = self.es._collect_first_commands_for_init_sequence()
        self.assertEqual(cmds, [HandledCommand(b"test", device=self.device_1, from_api=True)])

    def test_only_the_first_command_is_returned_if_thread_commands_contain_multiple_cmds(self):
        self.es.modules[1000].thread._commands.put(b"one", self.device_1)
        self.es.modules[1000].thread._commands.put(b"two", self.device_1)
        self.es.modules[1000].thread._commands.put(b"three", self.device_1)
        cmds = self.es._collect_first_commands_for_init_sequence()
        self.assertEqual(cmds, [HandledCommand(b"one", device=self.device_1, from_api=True)])

    def tearDown(self) -> None:
        self.es.mqtt.disconnect()
        self.broker.stop()


class Test_Multiple_Connected_Devices(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.device_2 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_2")
        self.device_3 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_3")
        self.es.mqtt.connect()
        self.es._add_connected_device(self.device_1)
        self.es._add_connected_device(self.device_2)
        self.es._add_connected_device(self.device_3)

    def test_empty_commands_are_returned_if_thread_commands_queue_is_empty(self):
        cmds = self.es._collect_first_commands_for_init_sequence()
        self.assertEqual(
            cmds,
            [
                HandledCommand(b"", device=self.device_1, from_api=False),
                HandledCommand(b"", device=self.device_2, from_api=False),
                HandledCommand(b"", device=self.device_3, from_api=False),
            ],
        )

    def test_only_the_first_command_is_returned_if_thread_commands_contain_multiple_cmds(self):
        self.es.modules[1000].thread._commands.put(b"one", self.device_1)
        self.es.modules[1000].thread._commands.put(b"two", self.device_2)
        self.es.modules[1000].thread._commands.put(b"three", self.device_3)
        cmds = self.es._collect_first_commands_for_init_sequence()
        self.assertListEqual(
            cmds,
            [
                HandledCommand(b"one", device=self.device_1, from_api=True),
                HandledCommand(b"two", device=self.device_2, from_api=True),
                HandledCommand(b"three", device=self.device_3, from_api=True),
            ],
        )

    def test_only_the_first_commands_are_returned_if_thread_commands_contain_multiple_cmds(self):
        self.es.modules[1000].thread._commands.put(b"one", self.device_1)
        self.es.modules[1000].thread._commands.put(b"two", self.device_1)
        self.es.modules[1000].thread._commands.put(b"three", self.device_2)
        self.es.modules[1000].thread._commands.put(b"four", self.device_2)
        self.es.modules[1000].thread._commands.put(b"five", self.device_3)
        self.es.modules[1000].thread._commands.put(b"six", self.device_3)
        cmds = self.es._collect_first_commands_for_init_sequence()
        self.assertListEqual(
            cmds,
            [
                HandledCommand(b"one", device=self.device_1, from_api=True),
                HandledCommand(b"three", device=self.device_2, from_api=True),
                HandledCommand(b"five", device=self.device_3, from_api=True),
            ],
        )

    def tearDown(self) -> None:
        self.es.mqtt.disconnect()
        self.broker.stop()


class Test_Not_Connected_Devices(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.device_2 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_2")
        self.device_3 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_3")
        self.es.mqtt.connect()
        self.es._add_connected_device(self.device_1)
        self.es._add_not_connected_device(self.device_2)
        # device_3 is not known (not connected or not disconnected)

    def test_commands_are_returned_for_all_known_devices(self):
        self.es.modules[1000].thread._commands.put(b"one", self.device_1)
        self.es.modules[1000].thread._commands.put(b"two", self.device_2)
        cmds = self.es._collect_first_commands_for_init_sequence()
        self.assertListEqual(
            cmds,
            [
                HandledCommand(b"one", device=self.device_1, from_api=True),
                HandledCommand(b"", device=self.device_2, from_api=False),
            ],
        )

    def tearDown(self) -> None:
        self.es.mqtt.disconnect()
        self.broker.stop()


@patch("external_server.adapters.mqtt.adapter.MQTTClientAdapter._get_message")
class Test_Next_Valid_Command_Response(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.es.mqtt.connect()
        self.es._add_connected_device(self.device_1)
        self.es._mqtt_session.set_id("session_id")

    def test_missing_expected_commands_response_raises_exception(self, mock: Mock):
        mock.return_value = None
        with self.assertRaises(ConnectSequenceFailure):
            self.es._get_next_valid_command_response()

    def test_expected_command_response_is_returned(self, mock: Mock):
        mock.side_effect = (r for r in [cmd_response("session_id", 1, CommandResponse.OK)])
        response = self.es._get_next_valid_command_response()
        self.assertEqual(
            response,
            CommandResponse(sessionId="session_id", type=CommandResponse.OK, messageCounter=1),
        )

    def test_command_response_is_not_accepted_if_session_id_does_not_match(self, mock: Mock):
        mock.side_effect = (r for r in [cmd_response("other_session_id", 1, CommandResponse.OK), None])
        with self.assertRaises(ConnectSequenceFailure):
            self.es._get_next_valid_command_response()

    def tearDown(self) -> None:
        self.es.mqtt.disconnect()
        self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
