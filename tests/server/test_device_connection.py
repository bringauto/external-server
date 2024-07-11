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
from external_server.server import ExternalServer
from external_server.models.structures import DevicePy as DevicePy
from external_server.utils import connect_msg, status  # type: ignore
from external_server.server_message_creator import (
    external_command as _external_command,
    status_response as _status_response,
)
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH, MQTTBrokerTest, ExternalServerThreadExecutor


logging.getLogger("ExternalServer").setLevel(logging.DEBUG)


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
    """This mocks publihsing a message by an External Client."""
    for p in payload:
        if isinstance(p, _ExternalClient):
            broker.publish_messages(server.mqtt_client.subscribe_topic, p.SerializeToString())
    broker.publish_messages(server.mqtt_client.subscribe_topic, *payload)


@unittest.skip("These tests are working")
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
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic)
            ex.submit(publish_from_ext_client, self.es, self.broker, payload.SerializeToString())
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


class Test_Timeout_When_Expecting_Connect_Message(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = ExternalServer(config=self.config)
        self.broker = MQTTBrokerTest(start=True)
        self.executor = ExternalServerThreadExecutor(self.es)

    def test_logs_an_error_and_continues_in_waiting_for_the_message(self):
        with self.executor as ex:
            # the server (and the connect sequence) has been already started in the executor
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic)
            time.sleep(self.config.timeout + 0.1)
            self.assertEqual(response.result(), [])


@unittest.skip("These tests are working")
class Test_Receiving_First_Status(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = ExternalServer(config=self.config)
        self.broker = MQTTBrokerTest(start=True)
        self.executor = ExternalServerThreadExecutor(self.es, 0.2)

    def test_makes_server_to_send_status_response_and_command_to_the_device(self):
        device = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        connect_payload = connect_msg("some_id", company="ba", car="car1", devices=[device])
        status_payload = status(
            session_id="some_id",
            state=_Status.CONNECTING,
            counter=0,
            status=_DeviceStatus(device=device),
        )
        with self.executor as ex:
            ex.submit(publish_from_ext_client, self.es, self.broker, connect_payload)
            # the next thread will wait for the broker receiving the status response
            response = ex.submit(self.broker.get_messages, self.es.mqtt_client.publish_topic, n=2)
            ex.submit(publish_from_ext_client, self.es, self.broker, status_payload)
            self.assertEqual(
                response.result()[0].payload, _status_response("some_id", 0).SerializeToString()
            )
            self.assertEqual(
                response.result()[1].payload,
                _external_command("some_id", 0, device).SerializeToString(),
            )

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