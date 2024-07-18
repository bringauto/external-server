import unittest

from external_server.models.devices import KnownDevices, DevicePy
from InternalProtocol_pb2 import Device  # type: ignore


class Test_Known_Devices(unittest.TestCase):

    def setUp(self) -> None:
        self.devices = KnownDevices()
        self.test_device = DevicePy(1, 0, "test", "Test", 0)

    def test_kown_devices_is_initially_empty(self):
        self.assertEqual(self.devices.n_connected, 0)
        self.assertEqual(self.devices.n_not_connected, 0)
        self.assertEqual(self.devices.list_connected(), [])
        self.assertEqual(self.devices.list_not_connected(), [])

    def test_device_not_added_is_unknown_and_not_connected_or_notconnected(self):
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.assertFalse(self.devices.is_connected(self.test_device))
        self.assertFalse(self.devices.is_not_connected(self.test_device))

    def test_adding_connected_device(self):
        self.devices.connected(self.test_device)
        self.assertTrue(self.devices.is_connected(self.test_device))
        self.assertFalse(self.devices.is_not_connected(self.test_device))
        self.assertEqual(self.devices.list_connected(), [self.test_device])
        self.assertEqual(self.devices.list_not_connected(), [])

    def test_adding_not_connected_device(self):
        self.devices.not_connected(self.test_device)
        self.assertFalse(self.devices.is_connected(self.test_device))
        self.assertTrue(self.devices.is_not_connected(self.test_device))
        self.assertEqual(self.devices.list_connected(), [])
        self.assertEqual(self.devices.list_not_connected(), [self.test_device])

    def test_notconnected_device_connected_is_removed_from_notconnected_devices(self):
        self.devices.not_connected(self.test_device)
        self.devices.connected(self.test_device)
        self.assertFalse(self.devices.is_not_connected(self.test_device))
        self.assertTrue(self.devices.is_connected(self.test_device))

    def test_connected_device_notconnected_is_removed_from_connected_devices(self):
        self.devices.connected(self.test_device)
        self.devices.not_connected(self.test_device)
        self.assertFalse(self.devices.is_connected(self.test_device))
        self.assertTrue(self.devices.is_not_connected(self.test_device))

    def test_removed_connected_device_becomes_unknown_and_is_not_connected(self):
        self.devices.connected(self.test_device)
        self.devices.remove(self.test_device)
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.assertFalse(self.devices.is_connected(self.test_device))
        self.assertFalse(self.devices.is_not_connected(self.test_device))

    def test_removed_notconnected_device_becomes_unknown_and_is_not_connected(self):
        self.devices.not_connected(self.test_device)
        self.devices.remove(self.test_device)
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.assertFalse(self.devices.is_connected(self.test_device))
        self.assertFalse(self.devices.is_not_connected(self.test_device))

    def test_removing_unknown_device_has_no_effect(self):
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.devices.remove(self.test_device)
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.assertFalse(self.devices.is_connected(self.test_device))
        self.assertFalse(self.devices.is_not_connected(self.test_device))

    def test_clearing_devices(self):
        self.devices.connected(self.test_device)
        self.devices.not_connected(DevicePy(2, 0, "test", "Test", 0))
        self.devices.clear()
        self.assertEqual(self.devices.n_connected, 0)
        self.assertEqual(self.devices.n_not_connected, 0)


class Test_Connected_Device_From_The_Same_Module(unittest.TestCase):

    def test_connected_device_from_the_same_module_is_in_the_list(self):
        self.devices = KnownDevices()
        module_id_1 = 5
        module_id_2 = 6
        module_id_3 = 7
        test_device_1 = DevicePy(module_id_1, 0, "test", "Test", 0)
        test_device_2 = DevicePy(module_id_2, 0, "test", "Test", 0)
        self.devices.connected(test_device_1)
        self.devices.not_connected(test_device_2)
        self.assertTrue(self.devices.is_module_connected(module_id_1))
        self.assertFalse(self.devices.is_module_connected(module_id_2))
        self.assertFalse(self.devices.is_module_connected(module_id_3))

    def test_module_of_removed_device_is_not_connected(self):
        self.devices = KnownDevices()
        module_id = 5
        test_device = DevicePy(module_id, 0, "test", "Test", 0)
        self.devices.connected(test_device)
        self.devices.remove(test_device)
        self.assertFalse(self.devices.is_module_connected(module_id))


class Test_Connecting_Device_From_Internal_Proto(unittest.TestCase):

    def test_connected_device_from_internal_proto_adds_device_py_to_the_list(self,):
        self.devices = KnownDevices()
        device = Device(module=5, deviceType=7, deviceRole="test", deviceName="Test")
        devicepy = DevicePy.from_device(device)
        self.devices.connected(device)
        self.assertTrue(self.devices.is_connected(device))
        self.assertTrue(self.devices.is_connected(devicepy))


if __name__ == "__main__":
    unittest.main()
