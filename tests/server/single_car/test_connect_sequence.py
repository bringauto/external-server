import unittest
import time
import threading

from pydantic import FilePath

from fleet_protocol_protobuf_files.InternalProtocol_pb2 import (
    Device,
    DeviceStatus
)
from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import (
    CommandResponse,
    ConnectResponse,
    ExternalClient as ExternalClientMsg,
    ExternalServer as ExternalServerMsg,
    Status as _Status,
)
from external_server.config import CarConfig, ModuleConfig
from external_server.server.single_car import CarServer
from external_server.models.messages import (
    connect_msg,
    status,
    cmd_response,
    status_response as _status_response,
)
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH
from tests.utils.mqtt_broker import MQTTBrokerTest
from tests.utils import get_test_car_server


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


def mock_publishing_from_ext_client(server: CarServer, broker: MQTTBrokerTest, *payload: str):
    """This mocks publishing a message by an External Client."""
    payload_str = [
        p.SerializeToString() if isinstance(p, ExternalClientMsg) else p for p in payload
    ]
    broker.publish(server.mqtt.subscribe_topic, *payload_str)


class Test_Receiving_Connect_Message(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = CarConfig(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(
            self.es.mqtt.publish_topic,
            self.es.mqtt.subscribe_topic,
            start=True,
        )
        self._start_server_thread()

    def _start_server_thread(self):
        self.server_thread = threading.Thread(target=self.es.start)
        self.server_thread.start()
        while True:
            if not self.es.mqtt.is_connected:
                time.sleep(0.01)
            else:
                break

    def test_connect_message_with_no_devices_has_no_effect(self):
        payload = connect_msg("id", company="ba", devices=[])
        mock_publishing_from_ext_client(self.es, self.broker, payload.SerializeToString())
        self.assertEqual(self.es._known_devices.n_all, 0)

    def test_from_supported_device_adds_the_device_to_connected_devices(self):
        device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("id", company="ba", devices=[device])
        mock_publishing_from_ext_client(self.es, self.broker, payload.SerializeToString())
        self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        self.assertTrue(self.es._known_devices.is_connected(device))
        self.assertTrue(self.es._known_devices.is_known(device))

    def test_from_unsupported_device_does_not_add_the_device_to_known_devices(self):
        device = Device(module=1000, deviceType=1251, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg(session_id="id", company="ba", devices=[device])
        mock_publishing_from_ext_client(self.es, self.broker, payload.SerializeToString())
        self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        self.assertFalse(self.es._known_devices.is_known(device))

    def test_from_device_in_unsupported_module_does_not_add_the_device_to_known_devices(self):
        device = Device(module=1100, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg(session_id="id", company="ba", devices=[device])
        mock_publishing_from_ext_client(self.es, self.broker, payload.SerializeToString())
        self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        self.assertFalse(self.es._known_devices.is_known(device))

    def test_from_multiple_devices_from_supported_module_adds_them_to_connected_devices(self):
        device_1 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        device_2 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_2")
        payload = connect_msg("id", company="ba", devices=[device_1, device_2])
        mock_publishing_from_ext_client(self.es, self.broker, payload.SerializeToString())
        self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        self.assertTrue(self.es._known_devices.is_connected(device_1))
        self.assertTrue(self.es._known_devices.is_connected(device_2))

    def test_from_supported_device_of_supported_module_makes_server_to_send_connect_response(self):
        device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("id", company="ba", devices=[device])
        mock_publishing_from_ext_client(self.es, self.broker, payload)
        response = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        expected_resp = ExternalServerMsg(connectResponse=ConnectResponse(sessionId="id"))
        self.assertEqual(expected_resp.SerializeToString(), response[0])

    def test_from_supported_device_of_unsupported_module_makes_server_to_send_conn_response(self):
        device = Device(module=1516, deviceType=0, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("id", company="ba", devices=[device])
        mock_publishing_from_ext_client(self.es, self.broker, payload.SerializeToString())
        response = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        expected_resp = ExternalServerMsg(connectResponse=ConnectResponse(sessionId="id"))
        self.assertEqual(expected_resp.SerializeToString(), response[0])

    def test_from_unsupported_device_of_supported_module_makes_server_to_send_conn_response(self):
        device = Device(module=100, deviceType=154, deviceName="TestDevice", deviceRole="test")
        payload = connect_msg("id", company="ba", devices=[device])
        mock_publishing_from_ext_client(self.es, self.broker, payload.SerializeToString())
        response = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        expected_resp = ExternalServerMsg(connectResponse=ConnectResponse(sessionId="id"))
        self.assertEqual(expected_resp.SerializeToString(), response[0])

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_Receiving_First_Status(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = CarConfig(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(
            self.es.mqtt.publish_topic, self.es.mqtt.subscribe_topic, start=True
        )
        self.server_thread = threading.Thread(target=self.es.start)
        self.server_thread.start()
        while True:
            if not self.es.mqtt.is_connected:
                time.sleep(0.01)
            else:
                break

    def test_from_single_connected_devices(self):
        device_1 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        connect_payload = connect_msg("id", "ba", [device_1])
        status_1 = status("id", _Status.CONNECTING, 0, DeviceStatus(device=device_1))

        mock_publishing_from_ext_client(self.es, self.broker, connect_payload)
        mock_publishing_from_ext_client(self.es, self.broker, status_1)
        response = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=2)
        self.assertEqual(response[-1], _status_response("id", 0).SerializeToString())

    def test_from_multiple_connected_devices(self):
        device_1 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        device_2 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_2")
        device_3 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_3")
        connect_payload = connect_msg("id", "ba", [device_1, device_2, device_3])
        status_1 = status("id", _Status.CONNECTING, 0, DeviceStatus(device=device_1))
        status_2 = status("id", _Status.CONNECTING, 1, DeviceStatus(device=device_2))
        status_3 = status("id", _Status.CONNECTING, 2, DeviceStatus(device=device_3))

        mock_publishing_from_ext_client(self.es, self.broker, connect_payload)
        mock_publishing_from_ext_client(self.es, self.broker, status_1, status_2, status_3)
        response = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=4)[1:]
        for k in range(len(response)):
            self.assertEqual(response[k], _status_response("id", k).SerializeToString())

    def test_yields_response_only_to_devices_from_the_connect_message(self):
        dev_1 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        dev_2 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="other_role")
        connect_payload = connect_msg("session_id", company="ba", devices=[dev_1])
        status_1 = status("session_id", _Status.CONNECTING, 0, DeviceStatus(device=dev_1))
        status_2 = status("session_id", _Status.CONNECTING, 1, DeviceStatus(device=dev_2))
        mock_publishing_from_ext_client(self.es, self.broker, connect_payload)
        self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        self.broker.clear_messages(self.es.mqtt.publish_topic)
        # post statuses
        mock_publishing_from_ext_client(self.es, self.broker, status_1, status_2)
        response = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        # the status from device 2 is ignored
        self.assertEqual(response[-1], _status_response("session_id", 0).SerializeToString())

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_Command_Response(unittest.TestCase):

    def setUp(self) -> None:
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = CarConfig(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(
            self.es.mqtt.publish_topic, self.es.mqtt.subscribe_topic, start=True
        )
        server_thread = threading.Thread(target=self.es.start)
        server_thread.start()
        while True:
            if not self.es.mqtt.is_connected:
                time.sleep(0.01)
            else:
                break

    def test_command_response_is_received_at_the_end_of_the_conn_sequence_for_single_device(self):
        device_1 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        connect_payload = connect_msg("id", "ba", [device_1])
        status_1 = status("id", _Status.CONNECTING, 0, DeviceStatus(device=device_1))
        command_response = cmd_response("id", 0, CommandResponse.OK)

        mock_publishing_from_ext_client(self.es, self.broker, connect_payload)
        mock_publishing_from_ext_client(self.es, self.broker, status_1)
        mock_publishing_from_ext_client(self.es, self.broker, command_response)
        received_msgs = self.broker.wait_for_messages(self.es.mqtt.subscribe_topic, n=3)[1:]
        self.assertEqual(received_msgs[0], status_1.SerializeToString())
        self.assertEqual(received_msgs[1], command_response.SerializeToString())

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_Connection_Sequence_Restarted(unittest.TestCase):

    def setUp(self):
        module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.config = CarConfig(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = get_test_car_server()
        self.timeout = self.es.mqtt.timeout
        self.broker = MQTTBrokerTest(
            self.es.mqtt.publish_topic, self.es.mqtt.subscribe_topic, start=True
        )

    def wait_for_server_connection(self) -> None:
        while True:
            if not self.es.mqtt.is_connected:
                time.sleep(0.01)
            else:
                break

    def test_if_first_status_is_not_delivered_before_timeout(self) -> None:
        device_1 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")

        connect_payload_1 = connect_msg("id1", "ba", [device_1])
        connect_payload_2 = connect_msg("id2", "ba", [device_1])
        delayed_status = status("id2", _Status.CONNECTING, 0, DeviceStatus(device=device_1))
        command_response = cmd_response("id2", 0, CommandResponse.OK)

        self.es._set_running_flag(True)

        run_thread = threading.Thread(target=self.es._single_communication_run)
        run_thread.start()
        self.wait_for_server_connection()

        mock_publishing_from_ext_client(self.es, self.broker, connect_payload_1)
        time.sleep(self.timeout + 0.5)

        # connect sequence is repeated
        run_thread = threading.Thread(target=self.es._single_communication_run)
        run_thread.start()
        self.wait_for_server_connection()

        mock_publishing_from_ext_client(self.es, self.broker, connect_payload_2)
        mock_publishing_from_ext_client(self.es, self.broker, delayed_status)
        mock_publishing_from_ext_client(self.es, self.broker, command_response)

        response = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=4)[1:]
        msg_1, msg_2, msg_3 = ExternalServerMsg(), ExternalServerMsg(), ExternalServerMsg()
        msg_1.ParseFromString(response[0])
        msg_2.ParseFromString(response[1])
        msg_3.ParseFromString(response[2])
        self.assertEqual(msg_1.connectResponse.sessionId, "id2")
        self.assertEqual(msg_2.connectResponse.type, ConnectResponse.OK)
        self.assertEqual(msg_2.statusResponse.sessionId, "id2")
        self.assertEqual(msg_2.statusResponse.messageCounter, 0)
        self.assertEqual(msg_3.command.sessionId, "id2")
        self.assertEqual(msg_3.command.messageCounter, 0)

    def test_if_command_response_is_not_delivered_before_timeout(self) -> None:
        device_1 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1")
        connect_payload = connect_msg("idx", "ba", [device_1])
        status_payload = status("idx", _Status.CONNECTING, 0, DeviceStatus(device=device_1))
        cmd_response_payload = cmd_response("idx", 0, CommandResponse.OK)

        run_thread = threading.Thread(target=self.es._single_communication_run)
        run_thread.start()

        self.wait_for_server_connection()

        mock_publishing_from_ext_client(self.es, self.broker, connect_payload)
        mock_publishing_from_ext_client(self.es, self.broker, status_payload)
        time.sleep(self.timeout + 0.1)

        run_thread = threading.Thread(target=self.es._single_communication_run)
        run_thread.start()

        self.wait_for_server_connection()

        # connect sequence is repeated
        self.broker.clear_messages(self.es.mqtt.subscribe_topic)
        mock_publishing_from_ext_client(self.es, self.broker, connect_payload)
        mock_publishing_from_ext_client(self.es, self.broker, status_payload)
        mock_publishing_from_ext_client(self.es, self.broker, cmd_response_payload)
        response = self.broker.wait_for_messages(self.es.mqtt.subscribe_topic, n=3)

        msg_1, msg_2, msg_3 = ExternalServerMsg(), ExternalServerMsg(), ExternalServerMsg()
        msg_1.ParseFromString(response[0])
        msg_2.ParseFromString(response[1])
        msg_3.ParseFromString(response[2])
        self.assertEqual(msg_1.connectResponse.sessionId, "idx")
        self.assertEqual(msg_2.connectResponse.type, ConnectResponse.OK)
        self.assertEqual(msg_2.statusResponse.sessionId, "idx")
        self.assertEqual(msg_2.statusResponse.messageCounter, 0)
        self.assertEqual(msg_3.command.sessionId, "idx")
        self.assertEqual(msg_3.command.messageCounter, 0)

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
