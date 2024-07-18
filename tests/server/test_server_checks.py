import unittest
import logging

from InternalProtocol_pb2 import Device as _Device  # type: ignore
from external_server.models.devices import DevicePy
from external_server.models.exceptions import ConnectSequenceException
from external_server import ExternalServer as ES
from ExternalProtocol_pb2 import Status as _Status  # type: ignore


class Test_Server_Checks(unittest.TestCase):

    def setUp(self) -> None:
        self.device = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")

    def test_device_is_not_in_list_if_list_is_empty(self) -> None:
        self.assertFalse(ES.is_device_in_list(self.device, []))

    def test_device_is_in_the_list(self) -> None:
        devices = [
            DevicePy(module_id=1000, type=0, name="TestDevice", role="test", priority=0),
            DevicePy(module_id=1000, type=2, name="TestDevice", role="test", priority=0)
        ]
        self.assertTrue(ES.is_device_in_list(self.device, devices))

    def test_device_is_not_in_list_if_all_devices_in_list_differ_by_module_id(self):
        devices = [
            DevicePy(module_id=2000, type=0, name="TestDevice", role="test", priority=0),
            DevicePy(module_id=3000, type=0, name="TestDevice", role="test", priority=0)
        ]
        self.assertFalse(ES.is_device_in_list(self.device, devices))

    def test_device_is_not_in_list_if_all_devices_in_list_differ_by_type(self):
        devices = [
            DevicePy(module_id=1000, type=1, name="TestDevice", role="test", priority=0),
            DevicePy(module_id=1000, type=2, name="TestDevice", role="test", priority=0)
        ]
        self.assertFalse(ES.is_device_in_list(self.device, devices))

    def test_device_is_not_in_list_if_all_devices_in_list_differ_by_role(self):
        devices = [
            DevicePy(module_id=1000, type=0, name="TestDevice", role="test_1", priority=0),
            DevicePy(module_id=1000, type=0, name="TestDevice", role="test_2", priority=0)
        ]
        self.assertFalse(ES.is_device_in_list(self.device, devices))

    def test_device_is_in_list_if_all_devices_in_list_differ_by_name(self):
        devices = [
            DevicePy(module_id=1000, type=0, name="TestDevice_1", role="test", priority=0),
            DevicePy(module_id=1000, type=0, name="TestDevice_2", role="test", priority=0)
        ]
        self.assertTrue(ES.is_device_in_list(self.device, devices))

    def test_device_is_in_list_if_all_devices_in_list_differ_by_priority(self):
        devices = [
            DevicePy(module_id=1000, type=0, name="TestDevice", role="test", priority=1),
            DevicePy(module_id=1000, type=0, name="TestDevice", role="test", priority=2)
        ]
        self.assertTrue(ES.is_device_in_list(self.device, devices))


class Test_Connecting_State(unittest.TestCase):

    def test_connecting_state_returns_without_exception(self):
        ES.check_connecting_state(_Status.CONNECTING)

    def test_other_than_connecting_state_returns_exception(self):
        for state in [_Status.DISCONNECT, _Status.ERROR, _Status.RUNNING]:
            with self.assertRaises(ConnectSequenceException):
                ES.check_connecting_state(state)


class Test_Logging_Warning_For_Status_From_Not_Connected_Device(unittest.TestCase):

    def setUp(self) -> None:
        self.logger = logging.Logger("test_logger")

    def test_warning_is_logged_if_device_not_in_list(self):
        device = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        devices = [
            DevicePy(module_id=2000, type=0, name="TestDevice", role="test", priority=0),
            DevicePy(module_id=3000, type=0, name="TestDevice", role="test", priority=0)
        ]
        with self.assertLogs(self.logger, level="WARNING") as cm:
            ES.warn_if_device_not_in_list(devices, device, self.logger, msg="Test message")

    def test_warning_is_not_logged_if_device_in_list(self):
        device = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        devices = [DevicePy(module_id=1000, type=0, name="TestDevice", role="test", priority=0)]
        with self.assertNoLogs(self.logger, level="WARNING") as cm:
            ES.warn_if_device_not_in_list(devices, device, self.logger, msg="Test message")


if __name__=="__main__":  # pragma: no cover
    unittest.main(buffer=True)