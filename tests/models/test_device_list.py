import unittest

from external_server.models.devices import KnownDevices, DevicePy
from InternalProtocol_pb2 import Device  # type: ignore


class Test_Known_Devices(unittest.TestCase):

    def setUp(self) -> None:
        self.devices = KnownDevices()
        self.test_device = DevicePy(1, 0, "test", "Test", 0)

    def test_kown_devices_is_initially_empty(self):
        self.assertEqual(self.devices.n_supported, 0)
        self.assertEqual(self.devices.n_unsupported, 0)
        self.assertEqual(self.devices.list_supported(), [])
        self.assertEqual(self.devices.list_unsupported(), [])

    def test_device_not_added_is_unknown_and_unsupported_or_unsupported(self):
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.assertFalse(self.devices.is_supported(self.test_device))
        self.assertFalse(self.devices.is_unsupported(self.test_device))

    def test_adding_supported_device(self):
        self.devices.add_supported(self.test_device)
        self.assertTrue(self.devices.is_supported(self.test_device))
        self.assertFalse(self.devices.is_unsupported(self.test_device))
        self.assertEqual(self.devices.list_supported(), [self.test_device])
        self.assertEqual(self.devices.list_unsupported(), [])

    def test_adding_unsupported_device(self):
        self.devices.add_unsupported(self.test_device)
        self.assertFalse(self.devices.is_supported(self.test_device))
        self.assertTrue(self.devices.is_unsupported(self.test_device))
        self.assertEqual(self.devices.list_supported(), [])
        self.assertEqual(self.devices.list_unsupported(), [self.test_device])

    def test_unsupported_device_supported_is_removed_from_unsupported_devices(self):
        self.devices.add_unsupported(self.test_device)
        self.devices.add_supported(self.test_device)
        self.assertFalse(self.devices.is_unsupported(self.test_device))
        self.assertTrue(self.devices.is_supported(self.test_device))

    def test_supported_device_unsupported_is_removed_from_supported_devices(self):
        self.devices.add_supported(self.test_device)
        self.devices.add_unsupported(self.test_device)
        self.assertFalse(self.devices.is_supported(self.test_device))
        self.assertTrue(self.devices.is_unsupported(self.test_device))

    def test_removed_supported_device_becomes_unknown_and_is_unsupported(self):
        self.devices.add_supported(self.test_device)
        self.devices.remove(self.test_device)
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.assertFalse(self.devices.is_supported(self.test_device))
        self.assertFalse(self.devices.is_unsupported(self.test_device))

    def test_removed_unsupported_device_becomes_unknown_and_is_unsupported(self):
        self.devices.add_unsupported(self.test_device)
        self.devices.remove(self.test_device)
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.assertFalse(self.devices.is_supported(self.test_device))
        self.assertFalse(self.devices.is_unsupported(self.test_device))

    def test_removing_unknown_device_has_no_effect(self):
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.devices.remove(self.test_device)
        self.assertTrue(self.devices.is_unknown(self.test_device))
        self.assertFalse(self.devices.is_supported(self.test_device))
        self.assertFalse(self.devices.is_unsupported(self.test_device))

    def test_clearing_devices(self):
        self.devices.add_supported(self.test_device)
        self.devices.add_unsupported(DevicePy(2, 0, "test", "Test", 0))
        self.devices.clear()
        self.assertEqual(self.devices.n_supported, 0)
        self.assertEqual(self.devices.n_unsupported, 0)


class Test_Device_Py(unittest.TestCase):

    def test_device_py_is_created_from_device(self):
        device = Device(module=5, deviceType=7, deviceRole="test", deviceName="Test")
        devicepy = DevicePy.from_device(device)
        self.assertEqual(devicepy.module_id, 5)
        self.assertEqual(devicepy.type, 7)
        self.assertEqual(devicepy.role, "test")
        self.assertEqual(devicepy.name, "Test")
        self.assertEqual(devicepy.priority, 0)

    def test_device_py_is_created_from_device_with_priority(self):
        device = Device(module=5, deviceType=7, deviceRole="test", deviceName="Test", priority=1)
        devicepy = DevicePy.from_device(device)
        self.assertEqual(devicepy.module_id, 5)
        self.assertEqual(devicepy.type, 7)
        self.assertEqual(devicepy.role, "test")
        self.assertEqual(devicepy.name, "Test")
        self.assertEqual(devicepy.priority, 1)

    def test_device_is_created_from_device_py(self):
        devicepy = DevicePy(5, 7, "test", "Test", 0)
        device = devicepy.to_device()
        self.assertEqual(device.module, 5)
        self.assertEqual(device.deviceType, 7)
        self.assertEqual(device.deviceRole, "test")
        self.assertEqual(device.deviceName, "Test")

    def test_two_devices_py_are_equal_if_module_id_role_and_type_are_equal(self):
        devicepy_1 = DevicePy(5, 7, "test", "Test", 0)
        devicepy_2 = DevicePy(5, 7, "test", "Test", 0)
        self.assertEqual(devicepy_1, devicepy_2)

    def test_two_devices_py_are_not_equal_if_module_id_is_different(self):
        devicepy_1 = DevicePy(5, 7, "test", "Test", 0)
        devicepy_2 = DevicePy(6, 7, "test", "Test", 0)
        self.assertNotEqual(devicepy_1, devicepy_2)

    def test_two_devices_py_are_not_equal_if_role_is_different(self):
        devicepy_1 = DevicePy(5, 7, "test", "Test", 0)
        devicepy_2 = DevicePy(5, 7, "test2", "Test", 0)
        self.assertNotEqual(devicepy_1, devicepy_2)

    def test_two_devices_py_are_not_equal_if_type_is_different(self):
        devicepy_1 = DevicePy(5, 7, "test", "Test", 0)
        devicepy_2 = DevicePy(5, 8, "test", "Test", 0)
        self.assertNotEqual(devicepy_1, devicepy_2)

    def test_device_and_device_py_are_equal(self):
        device = Device(module=5, deviceType=7, deviceRole="test", deviceName="Test")
        devicepy = DevicePy.from_device(device)
        self.assertEqual(device, devicepy.to_device())

    def test_comparing_device_py_to_another_type_raises_type_error(self):
        devicepy = DevicePy(5, 7, "test", "Test", 0)
        with self.assertRaises(TypeError):
            devicepy == 5


class Test_Connected_Device_From_The_Same_Module(unittest.TestCase):

    def test_supported_device_from_the_same_module_is_in_the_list(self):
        self.devices = KnownDevices()
        module_id_1 = 5
        module_id_2 = 6
        module_id_3 = 7
        test_device_1 = DevicePy(module_id_1, 0, "test", "Test", 0)
        test_device_2 = DevicePy(module_id_2, 0, "test", "Test", 0)
        self.devices.add_supported(test_device_1)
        self.devices.add_unsupported(test_device_2)
        self.assertTrue(self.devices.any_supported_device_from_module(module_id_1))
        self.assertFalse(self.devices.any_supported_device_from_module(module_id_2))
        self.assertFalse(self.devices.any_supported_device_from_module(module_id_3))

    def test_module_of_removed_device_is_unsupported(self):
        self.devices = KnownDevices()
        module_id = 5
        test_device = DevicePy(module_id, 0, "test", "Test", 0)
        self.devices.add_supported(test_device)
        self.devices.remove(test_device)
        self.assertFalse(self.devices.any_supported_device_from_module(module_id))


class Test_Connecting_Device_From_Internal_Proto(unittest.TestCase):

    def test_supported_device_from_internal_proto_adds_device_py_to_the_list(self,):
        self.devices = KnownDevices()
        device = Device(module=5, deviceType=7, deviceRole="test", deviceName="Test")
        devicepy = DevicePy.from_device(device)
        self.devices.add_supported(device)
        self.assertTrue(self.devices.is_supported(device))
        self.assertTrue(self.devices.is_supported(devicepy))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
