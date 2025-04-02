import unittest
from unittest.mock import Mock, patch
import logging
import sys
import time

sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import Status, ExternalServer as ExternalServerMsg  # type: ignore
from InternalProtocol_pb2 import Device, DeviceStatus  # type: ignore
from external_server.server.all_cars import logger as _logger
from external_server.logs import LOGGER_NAME
from external_server.adapters.api.adapter import APIClientAdapter
from tests.utils import get_test_car_server
from external_server.models.structures import GeneralErrorCode, EsErrorCode
from tests.utils.mqtt_broker import MQTTBrokerTest
from external_server.models.messages import status, status_response


_eslogger = _logger._logger


@patch("external_server.adapters.mqtt.adapter.MQTTClientAdapter.publish")
class Test_Handling_Checked_Status_And_Checking_Supported_Device_And_Module(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_car_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.published_responses: list[ExternalServerMsg] = list()
        self.es._add_connected_devices(self.device)
        self.es._mqtt.session.set_id("session_id")

    def publish(self, msg: ExternalServerMsg) -> None:
        self.published_responses.append(msg)

    def test_unsupported_module_referenced_by_status_logs_warning_and_sends_no_response(
        self, mock: Mock
    ):
        device = Device(module=1001, deviceType=0, deviceName="TestDevice", deviceRole="test")
        mock.side_effect = self.publish
        with self.assertLogs(_eslogger, logging.WARNING) as cm:
            self.es._handle_checked_status(
                status("session_id", Status.RUNNING, 1, DeviceStatus(device=device)).status
            )
            self.assertIn("unknown module", cm.output[0].lower())
            self.assertEqual(self.published_responses, [])

    def test_unsupported_device_of_supported_module_referenced_by_status_logs_warning_and_sends_no_response(
        self, mock: Mock
    ):
        device = Device(module=1000, deviceType=11111, deviceName="TestDevice", deviceRole="test")
        mock.side_effect = self.publish
        with self.assertLogs(_eslogger, logging.WARNING) as cm:
            self.es._handle_checked_status(
                status("session_id", Status.RUNNING, 1, DeviceStatus(device=device)).status
            )
            self.assertIn("not supported", cm.output[0])
            self.assertEqual(self.published_responses, [])

    def test_supported_device_of_supported_module_referenced_by_status_sends_response(
        self, mock: Mock
    ):
        device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        mock.side_effect = self.publish
        self.es._handle_checked_status(
            status("session_id", Status.RUNNING, 1, DeviceStatus(device=device)).status
        )
        self.assertEqual(self.published_responses, [status_response("session_id", 1)])


@patch("external_server.adapters.mqtt.adapter.MQTTClientAdapter.publish")
class Test_Handling_Checked_Status_For_Connected_Device(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_car_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.published_responses: list[ExternalServerMsg] = list()
        self.es._add_connected_devices(self.device)
        self.es._mqtt.session.set_id("session_id")

    def publish(self, msg: ExternalServerMsg) -> None:
        self.published_responses.append(msg)

    def test_connected_device_sending_disconnect_status_is_disconnected(self, mock: Mock):
        mock.side_effect = self.publish
        self.assertTrue(self.es._known_devices.is_connected(self.device))
        self.es._handle_checked_status(
            status("session_id", Status.DISCONNECT, 1, DeviceStatus(device=self.device)).status
        )
        self.assertFalse(self.es._known_devices.is_connected(self.device))

    def test_connected_device_sending_running_status_is_still_connected(self, mock: Mock):
        mock.side_effect = self.publish
        self.assertTrue(self.es._known_devices.is_connected(self.device))
        self.es._handle_checked_status(
            status("session_id", Status.RUNNING, 1, DeviceStatus(device=self.device)).status
        )
        self.assertTrue(self.es._known_devices.is_connected(self.device))
        self.assertEqual(self.published_responses, [status_response("session_id", 1)])

    def tearDown(self) -> None:
        self.es.stop()


@patch("external_server.adapters.mqtt.adapter.MQTTClientAdapter.publish")
class Test_Handling_Checked_Status_From_Disconnected_Device(unittest.TestCase):

    def publish(self, msg: ExternalServerMsg) -> None:
        self.published_responses.append(msg)

    def setUp(self) -> None:
        self.es = get_test_car_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.published_responses: list[ExternalServerMsg] = list()
        self.es._add_connected_devices(self.device)
        self.es._mqtt.session.set_id("session_id")

    def test_connecting_state_connects_the_device_and_sends_response(self, mock: Mock):
        self.es._known_devices.not_connected(self.device)
        mock.side_effect = self.publish
        self.assertFalse(self.es._known_devices.is_connected(self.device))
        self.es._handle_checked_status(
            status("session_id", Status.CONNECTING, 1, DeviceStatus(device=self.device)).status
        )
        self.assertTrue(self.es._known_devices.is_connected(self.device))
        self.assertEqual(self.published_responses, [status_response("session_id", 1)])

    def test_running_state_logs_warning_and_does_not_send_response(self, mock: Mock):
        mock.side_effect = self.publish
        self.es._known_devices.not_connected(self.device)
        with self.assertLogs(_eslogger, logging.WARNING) as cm:
            self.es._handle_checked_status(
                status("session_id", Status.RUNNING, 1, DeviceStatus(device=self.device)).status
            )
            self.assertIn("not connected", cm.output[0])
            self.assertEqual(self.published_responses, [])

    def test_disconnect_state_logs_error_and_does_not_send_response(self, mock: Mock):
        mock.side_effect = self.publish
        self.es._known_devices.not_connected(self.device)
        with self.assertLogs(_eslogger, logging.INFO) as cm:
            self.es._handle_checked_status(
                status("session_id", Status.DISCONNECT, 1, DeviceStatus(device=self.device)).status
            )
            self.assertIn("already disconnected", cm.output[-1])
            self.assertEqual(self.published_responses, [])


@patch("external_server.adapters.api.module_lib.ModuleLibrary.forward_status")
class Test_Forwarding_Status(unittest.TestCase):

    def forward_status(self, buffer: bytes, device: Device) -> int:
        self.forwarded_statuses.append((buffer, device))
        return 0

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(start=True)
        self.es.mqtt.connect()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.es._add_connected_devices(self.device)
        self.es._mqtt.session.set_id("session_id")
        self.forwarded_statuses = list()

    def test_status_from_supported_device_is_forwarded(self, mock: Mock):
        mock.side_effect = self.forward_status
        self.es._handle_checked_status(
            status("session_id", Status.RUNNING, 1, DeviceStatus(device=self.device)).status
        )
        time.sleep(1)
        self.assertEqual(len(self.forwarded_statuses), 1)

    def test_status_from_unsupported_device_is_not_forwarded(self, mock: Mock):
        mock.side_effect = self.forward_status
        unsup_device = Device(
            module=1000, deviceType=11111, deviceName="TestDevice", deviceRole="test"
        )
        self.es._handle_checked_status(
            status("session_id", Status.RUNNING, 1, DeviceStatus(device=unsup_device)).status
        )
        time.sleep(1)
        self.assertEqual(len(self.forwarded_statuses), 0)

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_API_Client_Library_Func_Return_Codes_Handling(unittest.TestCase):

    def setUp(self):
        self.device = Device(
            module=1, deviceType=4, deviceRole="test-device", deviceName="Test Device"
        )

    def test_warning_is_logged_if_disconnected_device_is_not_among_connected_devices(self):
        with self.assertLogs(LOGGER_NAME, logging.WARNING) as cm:
            APIClientAdapter.log_nok_device_disconnect(
                self.device, GeneralErrorCode.NOT_OK, "test-car"
            )
            self.assertIn("not among conected devices", cm.output[0])

    def test_incorrect_context_error_logs_error(self):
        with self.assertLogs(LOGGER_NAME, logging.ERROR) as cm:
            APIClientAdapter.log_nok_device_disconnect(
                self.device,
                EsErrorCode.CONTEXT_INCORRECT,
                "test-car",
            )
            self.assertIn("context incorrect", cm.output[0].lower())

    def test_error_is_logged_if_other_error_code_is_returned(self):
        with self.assertLogs(LOGGER_NAME, logging.ERROR) as cm:
            APIClientAdapter.log_nok_device_disconnect(self.device, -5, "test-car")
            self.assertIn("Error in device_disconnected", cm.output[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
