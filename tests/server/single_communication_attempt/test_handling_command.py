import unittest
from unittest.mock import Mock, patch

from InternalProtocol_pb2 import Device  # type: ignore
from tests.utils import get_test_server, MQTTBrokerTest
from external_server.models.exceptions import ConnectSequenceFailure


class Test_Handling_Command(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.es.mqtt.connect()
        self.es._add_connected_device(self.device_1)
        self.es._session.set_id("session_id")

    @patch("external_server.checkers.command_checker.CommandQueue.get")
    def test_missing_expected_commands_response_raises_exception(self, mock: Mock):
        mock.return_value = None
        with self.assertRaises(ConnectSequenceFailure):
            self.es._get_next_valid_command_response()

    def tearDown(self) -> None:
        self.es.mqtt.disconnect()
        self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)