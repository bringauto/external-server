import unittest
import sys
import logging

sys.path.append(".")

from pydantic import FilePath

from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device,
    DeviceCommand as _DeviceCommand,
    DeviceStatus as _DeviceStatus,
)
from ExternalProtocol_pb2 import (  # type: ignore
    ConnectResponse as _ConnectResponse,
    ExternalServer as _ExternalServer,
)
from external_server.config import Config, ModuleConfig
from external_server.server import ExternalServer
from external_server.models.structures import DevicePy as DevicePy
from external_server.utils import connect_msg, command_response, status  # type: ignore
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH, MQTTBrokerTest, ExternalServerThreadExecutor


logging.getLogger("ExternalServer").setLevel(logging.CRITICAL)

ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "ba",
    "car_name": "car1",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 2,
    "timeout": 5,
    "send_invalid_command": False,
    "mqtt_client_connection_retry_period": 2,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000,
}


def publish_from_ext_client(server: ExternalServer, broker: MQTTBrokerTest, payload: str):
    """This mocks publihsing a message by an External Client."""
    broker.publish_message(topic=server.mqtt_client.subscribe_topic, payload=payload)


class Test_Receiving_Connect_Message(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = ExternalServer(config=self.config)
        self.broker = MQTTBrokerTest(start=True)
        self.executor = ExternalServerThreadExecutor(self.es)

    def test_from_supported_device_adds_the_device_to_connected_devices(self):
        device = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("some_id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
            self.assertTrue(DevicePy.from_device(device) in self.es.connected_devices)

    def test_from_supported_device_of_unsupported_type_adds_the_device_to_connected_devices(self):
        device = _Device(module=1000, deviceType=1251, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg(session_id="some_id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
            self.assertTrue(DevicePy.from_device(device) in self.es.connected_devices)
            self.assertFalse(DevicePy.from_device(device) in self.es.not_connected_devices)

    def test_from_device_in_unsupported_module_adds_the_device_to_not_connected_devices(self):
        device = _Device(module=1100, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg(session_id="some_id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
            self.assertFalse(DevicePy.from_device(device) in self.es.connected_devices)
            self.assertTrue(DevicePy.from_device(device) in self.es.not_connected_devices)

    def test_from_multiple_devices_from_supported_module_adds_them_to_connected_devices(self):
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        device_2 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_2")
        payload = connect_msg("some_id", company="ba", car="car1", devices=[device_1, device_2])
        with self.executor as ex:
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
            self.assertTrue(DevicePy.from_device(device_1) in self.es.connected_devices)
            self.assertTrue(DevicePy.from_device(device_2) in self.es.connected_devices)

    def test_from_supported_device_of_supported_module_makes_server_to_send_connect_response(self):
        device = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("some_id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            response = ex.submit(self.broker.get_message, self.es.mqtt_client.publish_topic)
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
            expected_resp = _ExternalServer(connectResponse=_ConnectResponse(sessionId="some_id"))
            self.assertEqual(expected_resp.SerializeToString(), response.result().payload)

    def test_from_supported_device_of_unsupported_module_makes_server_to_send_conn_response(self):
        device = _Device(module=1516, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("some_id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            response = ex.submit(self.broker.get_message, self.es.mqtt_client.publish_topic)
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
            expected_resp = _ExternalServer(connectResponse=_ConnectResponse(sessionId="some_id"))
            self.assertEqual(expected_resp.SerializeToString(), response.result().payload)

    def test_from_unsupported_device_of_supported_module_makes_server_to_send_conn_response(self):
        device = _Device(module=100, deviceType=154, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("some_id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            response = ex.submit(self.broker.get_message, self.es.mqtt_client.publish_topic)
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
            expected_resp = _ExternalServer(connectResponse=_ConnectResponse(sessionId="some_id"))
            self.assertEqual(expected_resp.SerializeToString(), response.result().payload)

    def tearDown(self) -> None:
        self.broker.stop()


# class Test_Receiving_First_Status(unittest.TestCase):

#     def setUp(self) -> None:
#         module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
#         self.config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)
#         self.es = ExternalServer(config=self.config)
#         self.broker = MQTTBrokerTest(start=True)

#     def test_makes_server_to_send_command_to_the_device(self):
#         device = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
#         connect_payload = connect_msg("some_id", company="ba", car="car1", devices=[device])
#         status_payload = status("some_id", state=0, counter=0, status=_DeviceStatus(device=device))
#         with futures.ThreadPoolExecutor() as ex:
#             ex.submit(self.es.start)
#             time.sleep(0.2)
#             ex.submit(_publish_msg_from_external_client, self.es, self.broker, connect_payload.SerializeToString())
#             time.sleep(0.2)
#             ex.submit(_publish_msg_from_external_client, self.es, self.broker, status_payload.SerializeToString())
#             time.sleep(0.2)


#             ex.submit(self.es.stop)

#     def tearDown(self) -> None:
#         self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
