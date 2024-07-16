import unittest
import sys
import logging
import time
sys.path.append(".")

from pydantic import FilePath

from InternalProtocol_pb2 import Device as _Device, DeviceStatus as _DeviceStatus  # type: ignore
from ExternalProtocol_pb2 import (  # type: ignore
    ConnectResponse as _ConnectResponse,
    ExternalClient as _ExternalClient,
    ExternalServer as _ExternalServer,
    Status as _Status,
)
from external_server.config import Config, ModuleConfig
from external_server.server import ExternalServer, _logger
from external_server.models.structures import DevicePy as DevicePy
from external_server.utils import connect_msg, status  # type: ignore
from external_server.server_message_creator import (
    external_command as _external_command,
    status_response as _status_response,
)
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH, MQTTBrokerTest, ExternalServerThreadExecutor


_logger.setLevel(logging.DEBUG)


ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "ba",
    "car_name": "car1",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 1,
    "timeout": 1,
    "send_invalid_command": False,
    "mqtt_client_connection_retry_period": 2,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000,
}


def publish_from_ext_client(server: ExternalServer, broker: MQTTBrokerTest, *payload: str):
    """This mocks publishing a message by an External Client."""
    payload_str = []
    for p in payload:
        if isinstance(p, _ExternalClient):
            payload_str.append(p.SerializeToString())
        else:
            payload_str.append(p)
    broker.publish_messages(server.mqtt_client.subscribe_topic, *payload_str)


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
            ex.submit(publish_from_ext_client, self.es, self.broker, payload)
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
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic)
            ex.submit(publish_from_ext_client, self.es, self.broker, payload)
            expected_resp = _ExternalServer(connectResponse=_ConnectResponse(sessionId="some_id"))
            self.assertEqual(expected_resp.SerializeToString(), response.result()[0].payload)

    def test_from_supported_device_of_unsupported_module_makes_server_to_send_conn_response(self):
        device = _Device(module=1516, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("some_id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic)
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
            expected_resp = _ExternalServer(connectResponse=_ConnectResponse(sessionId="some_id"))
            self.assertEqual(expected_resp.SerializeToString(), response.result()[0].payload)

    def test_from_unsupported_device_of_supported_module_makes_server_to_send_conn_response(self):
        device = _Device(module=100, deviceType=154, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("some_id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic)
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
            expected_resp = _ExternalServer(connectResponse=_ConnectResponse(sessionId="some_id"))
            self.assertEqual(expected_resp.SerializeToString(), response.result()[0].payload)

    def tearDown(self) -> None:
        self.broker.stop()


class Test_Receiving_First_Status(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = ExternalServer(config=self.config)
        self.broker = MQTTBrokerTest(start=True)
        self.executor = ExternalServerThreadExecutor(self.es, 0.2)

    def test_from_single_connected_devices(self):
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        connect_payload = connect_msg("some_id", "ba", "car1", [device_1])
        status_1 = status("some_id", _Status.CONNECTING, 0, _DeviceStatus(device=device_1))
        with self.executor as ex:
            ex.submit(publish_from_ext_client, self.es, self.broker, connect_payload)
            time.sleep(0.1)
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic, n=1)
            ex.submit(
                publish_from_ext_client,
                self.es,
                self.broker,
                status_1
            )
            time.sleep(0.2)
            m = response.result()[0]
            self.assertEqual(m.payload, _status_response("some_id", 0).SerializeToString())

    def test_from_multiple_connected_devices(self):
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        device_2 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_2")
        device_3 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_3")
        connect_payload = connect_msg("some_id", "ba", "car1", [device_1, device_2, device_3])
        status_1 = status("some_id", _Status.CONNECTING, 0, _DeviceStatus(device=device_1))
        status_2 = status("some_id", _Status.CONNECTING, 1, _DeviceStatus(device=device_2))
        status_3 = status("some_id", _Status.CONNECTING, 2, _DeviceStatus(device=device_3))
        with self.executor as ex:
            ex.submit(publish_from_ext_client, self.es, self.broker, connect_payload)
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic, n=1)
            ex.submit(
                publish_from_ext_client,
                self.es,
                self.broker,
                status_1,
                status_2,
                status_3
            )
            for m in response.result():
                self.assertEqual(m.payload, _status_response("some_id", 0).SerializeToString())

    def test_yields_response_only_to_devices_from_the_connect_message(self):
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        device_2 = _Device(
            module=1000, deviceType=0, deviceName="TestDevice", deviceRole="other_role"
        )
        connect_payload = connect_msg("some_id", company="ba", car="car1", devices=[device_1])
        status_1 = status("some_id", _Status.CONNECTING, 0, _DeviceStatus(device=device_1))
        status_2 = status("some_id", _Status.CONNECTING, 1, _DeviceStatus(device=device_2))
        with self.executor as ex:
            # the next thread will wait for the broker receiving the status response
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic, n=1)
            ex.submit(publish_from_ext_client, self.es, self.broker, connect_payload)
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic, n=1)
            ex.submit(publish_from_ext_client, self.es, self.broker, status_1, status_2)
            self.assertEqual(
                response.result()[0].payload, _status_response("some_id", 0).SerializeToString()
            )

    def tearDown(self) -> None:
        self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
