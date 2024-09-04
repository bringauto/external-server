import unittest
import sys
import logging
import time

sys.path.append(".")

from pydantic import FilePath

from InternalProtocol_pb2 import Device as _Device, DeviceStatus as _DeviceStatus  # type: ignore
from ExternalProtocol_pb2 import (  # type: ignore
    CommandResponse as _CommandResponse,
    ConnectResponse as _ConnectResponse,
    ExternalClient as _ExternalClientMsg,
    ExternalServer as _ExternalServerMsg,
    Status as _Status,
)
from external_server.config import Config, ModuleConfig
from external_server.server import ExternalServer, logger
from external_server.models.messages import (
    connect_msg,
    status,
    cmd_response,
    status_response as _status_response,
)
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH, MQTTBrokerTest, ExternalServerThreadExecutor


ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "ba",
    "car_name": "car1",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 1,
    "timeout": 1,
    "send_invalid_command": False,
    "sleep_duration_after_connection_refused": 1,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000,
}


def mock_publishing_from_ext_client(server: ExternalServer, broker: MQTTBrokerTest, *payload: str):
    """This mocks publishing a message by an External Client."""
    payload_str = [
        p.SerializeToString() if isinstance(p, _ExternalClientMsg) else p for p in payload
    ]
    broker.publish(server.mqtt.subscribe_topic, *payload_str)


class Test_Receiving_Connect_Message(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = ExternalServer(config=self.config)
        self.broker = MQTTBrokerTest(start=True)
        self.executor = ExternalServerThreadExecutor(self.es)
        time.sleep(0.1)

    def test_connect_message_with_no_devices_has_no_effect(self):
        payload = connect_msg("id", company="ba", car="car1", devices=[])
        with self.executor as ex:
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, payload.SerializeToString())
            self.assertEqual(self.es._known_devices.n_all, 0)

    def test_from_supported_device_adds_the_device_to_connected_devices(self):
        device = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, payload.SerializeToString())
            self.assertTrue(self.es._known_devices.is_connected(device))
            self.assertTrue(self.es._known_devices.is_known(device))

    def test_from_unsupported_device_does_not_add_the_device_to_known_devices(self):
        device = _Device(module=1000, deviceType=1251, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg(session_id="id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, payload.SerializeToString())
            self.assertFalse(self.es._known_devices.is_known(device))

    def test_from_device_in_unsupported_module_does_not_add_the_device_to_known_devices(self):
        device = _Device(module=1100, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg(session_id="id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, payload)
            self.assertFalse(self.es._known_devices.is_known(device))

    def test_from_multiple_devices_from_supported_module_adds_them_to_connected_devices(self):
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        device_2 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_2")
        payload = connect_msg("id", company="ba", car="car1", devices=[device_1, device_2])
        with self.executor as ex:
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, payload.SerializeToString())
            self.assertTrue(self.es._known_devices.is_connected(device_1))
            self.assertTrue(self.es._known_devices.is_connected(device_2))

    def test_from_supported_device_of_supported_module_makes_server_to_send_connect_response(self):
        device = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            response = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, payload)
            expected_resp = _ExternalServerMsg(
                connectResponse=_ConnectResponse(sessionId="id")
            )
            self.assertEqual(expected_resp.SerializeToString(), response.result()[0].payload)

    def test_from_supported_device_of_unsupported_module_makes_server_to_send_conn_response(self):
        device = _Device(module=1516, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            response = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, payload.SerializeToString())
            expected_resp = _ExternalServerMsg(
                connectResponse=_ConnectResponse(sessionId="id")
            )
            self.assertEqual(expected_resp.SerializeToString(), response.result()[0].payload)

    def test_from_unsupported_device_of_supported_module_makes_server_to_send_conn_response(self):
        device = _Device(module=100, deviceType=154, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("id", company="ba", car="car1", devices=[device])
        with self.executor as ex:
            response = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, payload.SerializeToString())
            expected_resp = _ExternalServerMsg(
                connectResponse=_ConnectResponse(sessionId="id")
            )
            self.assertEqual(expected_resp.SerializeToString(), response.result()[0].payload)

    def tearDown(self) -> None:
        self.broker.stop()


class Test_Receiving_First_Status(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = ExternalServer(config=self.config)
        self.broker = MQTTBrokerTest(start=True)
        self.executor = ExternalServerThreadExecutor(self.es, 0.2)

    def test_from_single_connected_devices(self):
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        connect_payload = connect_msg("id", "ba", "car1", [device_1])
        status_1 = status("id", _Status.CONNECTING, 0, _DeviceStatus(device=device_1))
        with self.executor as ex:
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, connect_payload)
            response = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=1)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, status_1)
            m = response.result()[0]
            self.assertEqual(m.payload, _status_response("id", 0).SerializeToString())

    def test_from_multiple_connected_devices(self):
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        device_2 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_2")
        device_3 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_3")
        connect_payload = connect_msg("id", "ba", "car1", [device_1, device_2, device_3])
        status_1 = status("id", _Status.CONNECTING, 0, _DeviceStatus(device=device_1))
        status_2 = status("id", _Status.CONNECTING, 1, _DeviceStatus(device=device_2))
        status_3 = status("id", _Status.CONNECTING, 2, _DeviceStatus(device=device_3))
        with self.executor as ex:
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, connect_payload)
            response = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=1)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, status_1, status_2, status_3)
            for m in response.result():
                self.assertEqual(m.payload, _status_response("id", 0).SerializeToString())

    def test_yields_response_only_to_devices_from_the_connect_message(self):
        dev_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        dev_2 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="other_role")
        connect_payload = connect_msg("id", company="ba", car="car1", devices=[dev_1])
        status_1 = status("id", _Status.CONNECTING, 0, _DeviceStatus(device=dev_1))
        status_2 = status("id", _Status.CONNECTING, 1, _DeviceStatus(device=dev_2))
        with self.executor as ex:
            # the next thread will wait for the broker receiving the status response
            response = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=1)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, connect_payload)
            response = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=1)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, status_1, status_2)
            self.assertEqual(
                response.result()[0].payload, _status_response("id", 0).SerializeToString()
            )

    def tearDown(self) -> None:
        self.broker.stop()


class Test_Command_Response(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = ExternalServer(config=self.config)
        self.broker = MQTTBrokerTest(start=True)
        self.executor = ExternalServerThreadExecutor(self.es, 0.1)

    def test_command_response_is_received_at_the_end_of_the_conn_sequence_for_single_device(self):
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        connect_payload = connect_msg("id", "ba", "car1", [device_1])
        status_1 = status("id", _Status.CONNECTING, 0, _DeviceStatus(device=device_1))
        command_response = cmd_response("id", 0, _CommandResponse.OK)
        with self.executor as ex:
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, connect_payload)
            response = ex.submit(self.broker.get_messages, self.es.mqtt.subscribe_topic, n=2)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, status_1)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, command_response)
            received_msgs = response.result()
            self.assertEqual(len(received_msgs), 2)
            self.assertEqual(received_msgs[0].payload, status_1.SerializeToString())
            self.assertEqual(received_msgs[1].payload, command_response.SerializeToString())

    def tearDown(self) -> None:
        self.broker.stop()
        self.es.stop()


class Test_Connection_Sequence_Restarted(unittest.TestCase):

    def setUp(self):
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = ExternalServer(config=self.config)
        self.timeout = self.es.mqtt.timeout
        self.broker = MQTTBrokerTest(start=True)
        self.executor = ExternalServerThreadExecutor(self.es, 0.1, start=False)
        time.sleep(0.1)

    def test_if_first_status_is_not_delivered_before_timeout(self) -> None:
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        connect_payload = connect_msg("id", "ba", "car1", [device_1])

        delayed_status = status("id", _Status.CONNECTING, 0, _DeviceStatus(device=device_1))
        command_response = cmd_response("id", 0, _CommandResponse.OK)

        with self.executor as ex:
            self.es._set_running_flag(True)
            ex.submit(self.es._single_communication_run)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, connect_payload)
            time.sleep(self.timeout + 1)

            # connect sequence is repeated
            ex.submit(self.es._single_communication_run)
            response = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=2)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, connect_payload)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, delayed_status)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, command_response)
            msg_1, msg_2 = _ExternalServerMsg(), _ExternalServerMsg()

            result = response.result()
            msg_1.ParseFromString(result[0].payload)
            msg_2.ParseFromString(result[1].payload)

            self.assertEqual(msg_1.connectResponse.sessionId, "id")
            self.assertEqual(msg_2.connectResponse.type, _ConnectResponse.OK)
            self.assertEqual(msg_2.statusResponse.sessionId, "id")
            self.assertEqual(msg_2.statusResponse.messageCounter, 0)

    def test_if_command_response_is_not_delivered_before_timeout(self) -> None:
        device_1 = _Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        connect_payload = connect_msg("id", "ba", "car1", [device_1])
        status_payload = status("id", _Status.CONNECTING, 0, _DeviceStatus(device=device_1))
        cmd_response_payload = cmd_response("id", 0, _CommandResponse.OK)
        with self.executor as ex:
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, connect_payload)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, status_payload)
            time.sleep(self.timeout + 0.1)
            # connect sequence is repeated
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, connect_payload)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, status_payload)
            ex.submit(mock_publishing_from_ext_client, self.es, self.broker, cmd_response_payload)

    def tearDown(self) -> None:
        self.broker.stop()
        MQTTBrokerTest.kill_all_test_brokers()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
