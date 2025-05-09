import unittest
import sys
import concurrent.futures as futures
import time
import logging
from unittest.mock import patch, Mock
import threading

sys.path.append(".")

from external_server.server.single_car import CarServer, ServerState
from external_server.server.all_cars import logger as _logger
from external_server.models.structures import Buffer
from fleet_protocol_protobuf_files.InternalProtocol_pb2 import (
    Device,
    DeviceStatus
)
from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import (
    CommandResponse,
    ExternalServer as ExternalServerMsg,
    Status,
)
from tests.utils.mqtt_broker import MQTTBrokerTest
from tests.utils import get_test_car_server
from external_server.models.messages import (
    status_response,
    command,
    connect_msg,
    status,
    cmd_response,
)
from external_server.models.events import EventType
from external_server.models.structures import HandledCommand
from external_server.models.exceptions import NoMessage, SessionTimeout


_eslogger = _logger._logger


def wait_for_server_connection(
    server: CarServer, test_case: unittest.TestCase, timeout: float = 5.0
):
    t = time.time()
    while time.time() - t < timeout:
        if server.mqtt.is_connected:
            return
        else:
            time.sleep(0.01)
    test_case.fail("Server did not connect to broker")


def _wait_for_server_initialization(
    server: CarServer, test_case: unittest.TestCase, timeout: float = 5.0
):
    t = time.time()
    while time.time() - t < timeout:
        if server.state == ServerState.INITIALIZED:
            return
        else:
            time.sleep(0.01)
    test_case.fail("Server init sequence did not complete.")


class Test_Receiving_Disconnect_State_From_Single_Supported_Device(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(
            self.es.mqtt.subscribe_topic, self.es.mqtt.publish_topic, start=True
        )
        self.device_1 = Device(
            module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1"
        )
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            wait_for_server_connection(self.es, self)
            device_status = DeviceStatus(device=self.device_1)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("id", "company", [self.device_1]))
            self.broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
            self.broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
            _wait_for_server_initialization(self.es, self)
            self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=3)
            self.broker.clear_messages(self.es.mqtt.publish_topic)

    def test_disconnect_state_from_connected_device_removes_it_from_connected_devices(self):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            self.broker.clear_messages(self.es.mqtt.publish_topic)
            self.broker.publish(
                topic,
                status("id", Status.DISCONNECT, 1, DeviceStatus(device=self.device_1)),
            )
            self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
            self.assertFalse(self.es._known_devices.is_connected(self.device_1))

    def test_disconnect_state_from_diconnected_device_has_no_effect(self):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            self.broker.clear_messages(self.es.mqtt.publish_topic)
            self.broker.publish(
                topic,
                status("id", Status.DISCONNECT, 1, DeviceStatus(device=self.device_1)),
            )
            self.broker.publish(
                topic,
                status("id", Status.DISCONNECT, 1, DeviceStatus(device=self.device_1)),
            )
            self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=2)
            self.assertFalse(self.es._known_devices.is_connected(self.device_1))

    def test_sending_disconnect_state_from_the_only_connected_device_produces_status_response(self):
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            self.broker.publish(
                self.es.mqtt.subscribe_topic,
                status("id", Status.DISCONNECT, 1, DeviceStatus(device=self.device_1)),
            )
            msgs = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
            self.assertEqual(msgs[0], status_response("id", 1).SerializeToString())

    def tearDown(self) -> None:
        self.es.mqtt.disconnect()
        self.broker.stop()


class Test_Receiving_Running_Status_Sent_By_Single_Supported_Device(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(
            self.es.mqtt.subscribe_topic, self.es.mqtt.publish_topic, start=True
        )
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            self.es._set_running_flag(True)
            ex.submit(self.es._run_initial_sequence)
            wait_for_server_connection(self.es, self)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("id", "company", [self.device]))
            self.broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
            time.sleep(0.1)
            self.broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
            _wait_for_server_initialization(self.es, self)
            self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=3)
            self.broker.clear_messages(self.es.mqtt.publish_topic)

    def test_status_sent_by_connected_device_publishes_status_response(self):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            self.es._status_checker.set_counter(1)
            ex.submit(self.es._run_normal_communication)
            self.broker.publish(
                topic, status("id", Status.RUNNING, 1, DeviceStatus(device=self.device))
            )
            msgs = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
            self.assertTrue(self.es._known_devices.is_connected(self.device))
            self.assertEqual(msgs[0], status_response("id", 1).SerializeToString())

    @patch("external_server.adapters.api.module_lib.ModuleLibrary.forward_error_message")
    def test_status_containing_error_message_forwards_error(self, mock: Mock):
        self.posted_error = ""

        def forward_error(buffer: Buffer, device):
            self.posted_error = buffer.data
            return 0

        mock.side_effect = forward_error
        with futures.ThreadPoolExecutor() as ex:
            self.es._status_checker.set_counter(1)
            ex.submit(self.es._run_normal_communication)
            self.broker.clear_messages(self.es.mqtt.publish_topic)
            self.broker.publish(
                self.es.mqtt.subscribe_topic,
                status("id", Status.RUNNING, 1, DeviceStatus(device=self.device), b"error"),
            )
            self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
            self.assertEqual(self.posted_error, b"error")

    def test_multiple_statuses_sent_by_connected_device_publishes_status_responses_with_corresponding_counter_values(
        self,
    ):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            self.es._status_checker.set_counter(1)
            ex.submit(self.es._run_normal_communication)
            device_status = DeviceStatus(device=self.device)
            self.broker.clear_messages(self.es.mqtt.publish_topic)
            self.broker.publish(topic, status("id", Status.RUNNING, 1, device_status))
            self.broker.publish(topic, status("id", Status.RUNNING, 2, device_status))
            self.broker.publish(topic, status("id", Status.RUNNING, 3, device_status))
            msgs = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=3)
            msgs_objs = [ExternalServerMsg.FromString(m) for m in msgs]
            self.assertEqual(msgs_objs[0], status_response("id", 1))
            self.assertEqual(msgs_objs[1], status_response("id", 2))
            self.assertEqual(msgs_objs[2], status_response("id", 3))

    def test_multiple_statuses_sent_in_wrong_order_produce_status_responses_in_correct_order(self):
        topic = self.es.mqtt.subscribe_topic
        device_status = DeviceStatus(device=self.device)
        with futures.ThreadPoolExecutor() as ex:
            self.es._status_checker.set_counter(1)
            ex.submit(self.es._run_normal_communication)
            self.broker.publish(topic, status("id", Status.RUNNING, 2, device_status))
            self.broker.publish(topic, status("id", Status.RUNNING, 3, device_status))
            self.broker.publish(topic, status("id", Status.RUNNING, 1, device_status))
            msgs = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=3)
            self.assertEqual(msgs[0], status_response("id", 1).SerializeToString())
            self.assertEqual(msgs[1], status_response("id", 2).SerializeToString())
            self.assertEqual(msgs[2], status_response("id", 3).SerializeToString())

    def test_status_without_session_id_matching_current_session_id_is_ignored_and_no_response_is_sent_to_it(
        self,
    ):
        topic = self.es.mqtt.subscribe_topic
        device_status = DeviceStatus(device=self.device)
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            self.broker.publish(topic, status("id", Status.RUNNING, 1, device_status))
            self.broker.publish(topic, status("unknown_id", Status.RUNNING, 2, device_status))
            self.broker.publish(topic, status("id", Status.RUNNING, 2, device_status))
            msgs = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=2)
            msgs_objs = [ExternalServerMsg.FromString(m) for m in msgs]
            self.assertIn(status_response("id", 1), msgs_objs)
            self.assertIn(status_response("id", 2), msgs_objs)

    def tearDown(self) -> None:
        self.es.mqtt.disconnect()
        self.broker.stop()


class Test_Session_Time_Out(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            wait_for_server_connection(self.es, self)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("id", "company", [self.device]))
            self.broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
            self.broker.publish(topic, cmd_response("id", 0, CommandResponse.DEVICE_NOT_CONNECTED))
            _wait_for_server_initialization(self.es, self)

    def test_timeout_is_raised_if_no_message_from_module_gateway_is_received_in_time(self):
        with futures.ThreadPoolExecutor() as ex:
            self.assertTrue(self.es._known_devices.is_connected(self.device))
            future = ex.submit(self.es._run_normal_communication)
            time.sleep(self.es._mqtt.session.timeout + 0.001)
            self.assertTrue(self.es._mqtt.session.timeout_event.is_set())
            with self.assertRaises(SessionTimeout):
                future.result(timeout=10.0)

    def test_timeout_is_not_raised_if_status_is_received_in_time(self):
        with futures.ThreadPoolExecutor() as ex:
            self.assertTrue(self.es._known_devices.is_connected(self.device))
            ex.submit(self.es._run_normal_communication)
            time.sleep(self.es._mqtt.session.timeout / 2)
            self.broker.publish(
                self.es.mqtt.subscribe_topic,
                status("id", Status.RUNNING, 1, DeviceStatus(device=self.device)),
            )
            time.sleep(
                self.es._mqtt.session.timeout / 2 + 0.01
            )  # in total, the sleep time exceeds the timeout
            self.assertFalse(self.es._mqtt.session.timeout_event.is_set())

    def test_timeout_is_not_raised_if_command_respose_from_module_gateway_is_received_in_time(self):
        with futures.ThreadPoolExecutor() as ex:
            self.assertTrue(self.es._known_devices.is_connected(self.device))
            ex.submit(self.es._run_normal_communication)
            time.sleep(self.es._mqtt.session.timeout / 2)
            self.broker.publish(
                self.es.mqtt.subscribe_topic, cmd_response("id", 1, CommandResponse.OK)
            )
            time.sleep(
                self.es._mqtt.session.timeout / 2 + 0.1
            )  # in total, the sleep time exceeds the timeout
            self.assertFalse(self.es._mqtt.session.timeout_event.is_set())

    def tearDown(self) -> None:
        self.es.mqtt.disconnect()
        self.broker.stop()


class Test_Statuses_Containing_Errors(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(
            self.es.mqtt.subscribe_topic, self.es.mqtt.publish_topic, start=True
        )
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self._start_communication()

    def _start_communication(self):
        init_thread = threading.Thread(target=self.es._run_initial_sequence)
        init_thread.start()
        while not self.es.mqtt.is_connected:
            time.sleep(0.01)

        device_status = DeviceStatus(device=self.device)
        topic = self.es.mqtt.subscribe_topic
        self.broker.publish(topic, connect_msg("id", "company", [self.device]))
        self.broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
        self.broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))

        time.sleep(0.1)
        init_thread.join(timeout=2)
        server_thread = threading.Thread(target=self.es._run_normal_communication)
        server_thread.start()

    def test_nonempty_error_msg_from_status_is_logged(self):
        self.broker.clear_messages(self.es.mqtt.publish_topic)
        self.assertEqual(len(self.broker.messages(self.es.mqtt.publish_topic)), 0)
        self.broker.publish(
            self.es.mqtt.subscribe_topic,
            status(
                "id",
                Status.RUNNING,
                counter=1,
                status=DeviceStatus(device=self.device),
                error_message=b"error",
            ),
        )
        result = self.broker.wait_for_messages(self.es.mqtt.publish_topic, n=1)
        self.assertEqual(ExternalServerMsg.FromString(result[0]), status_response("id", 1))

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_Receiving_Connect_Message(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server(mqtt_timeout=0.5)
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            self.es._status_checker.set_counter(1)
            ex.submit(self.es._run_initial_sequence)
            wait_for_server_connection(self.es, self)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("id", "company", [self.device]))
            self.broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
            self.broker.publish(topic, cmd_response("id", 0, CommandResponse.DEVICE_NOT_CONNECTED))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)

    def test_connect_message_with_current_session_id_logs_error_and_produces_no_response(self):
        sub_topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            self.es._status_checker.set_counter(1)
            ex.submit(self.es._run_normal_communication)
            wait_for_server_connection(self.es, self)
            with self.assertLogs(_eslogger, logging.INFO) as cm:
                self.broker.publish(sub_topic, connect_msg("id", "company", [self.device]))
                time.sleep(0.1)
                self.assertIn("already existing session", cm.records[-1].message)

    def test_connect_message_with_other_session_id_does_not_logs_warning(self):
        sub_topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            self.es._status_checker.set_counter(1)
            ex.submit(self.es._run_normal_communication)
            wait_for_server_connection(self.es, self)
            with self.assertNoLogs(_eslogger, logging.WARNING):
                self.broker.publish(
                    sub_topic, connect_msg("other_session_id", "company", [self.device])
                )

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_Connecting_Device_During_Normal_Communication(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server(mqtt_timeout=0.5)
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(
            module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1"
        )
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            wait_for_server_connection(self.es, self)
            device_status = DeviceStatus(device=self.device_1)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("id", "company", [self.device_1]))
            self.broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
            time.sleep(0.1)
            self.broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
            _wait_for_server_initialization(self.es, self)

    def test_connecting_device_during_normal_communication_is_allowed(self):
        sub_topic = self.es.mqtt.subscribe_topic
        device_2 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_2")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            payload = DeviceStatus(statusData=b"Connecting", device=device_2)
            self.broker.publish(sub_topic, status("id", Status.CONNECTING, 1, payload))
            time.sleep(0.1)
            self.assertTrue(self.es._known_devices.is_connected(device_2))

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_Receiving_Command(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            wait_for_server_connection(self.es, self)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("id", "company", [self.device]))
            self.broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
            self.broker.publish(topic, cmd_response("id", 0, CommandResponse.OK))
            _wait_for_server_initialization(self.es, self)

    def test_command_response_received_after_publishing_command_from_api_is_acknowledged(self):
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            self.es._modules[1000].thread._commands.put(b"cmd", self.device)
            self.es._event_queue.add(event_type=EventType.COMMAND_AVAILABLE, data=1000)
            time.sleep(0.3)
            self.assertEqual(self.es._command_checker.n_of_commands, 1)
            self.broker.publish(
                self.es.mqtt.subscribe_topic, cmd_response("id", 1, CommandResponse.OK)
            )
            time.sleep(0.2)
            self.assertEqual(self.es._command_checker.n_of_commands, 0)

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_Command_Response(unittest.TestCase):

    def setUp(self):
        self.es = get_test_car_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            wait_for_server_connection(self.es, self)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("id", "company", [self.device]))
            self.broker.publish(topic, status("id", Status.CONNECTING, 0, device_status))
            self.broker.publish(topic, cmd_response("id", 0, CommandResponse.DEVICE_NOT_CONNECTED))
            _wait_for_server_initialization(self.es, self)

    def test_command_response_with_other_sessioni_id_is_ignored(self):
        sub_topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            time.sleep(0.1)
            self.es._command_checker.add(HandledCommand(data=b"cmd", counter=1, device=self.device))
            self.broker.publish(sub_topic, cmd_response("other_id", 1, CommandResponse.OK))
            time.sleep(0.1)
            self.broker.publish(sub_topic, cmd_response("id", 1, CommandResponse.OK))

    def test_timeout_event_is_set_if_command_response_is_not_received_in_time(self):
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            time.sleep(0.1)
            self.es._command_checker.add(HandledCommand(data=b"cmd", counter=1, device=self.device))
            time.sleep(self.es._config.mqtt_timeout + 0.1)
            self.assertTrue(self.es._command_checker.timeout_occurred())

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


@patch("external_server.adapters.mqtt.adapter.MQTTClientAdapter.publish")
class Test_Handling_Command(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_car_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.published_commands: list[ExternalServerMsg] = list()
        self.es._add_connected_devices(self.device)
        self.es._mqtt.session.set_id("id")

    def publish(self, msg: ExternalServerMsg) -> None:
        self.published_commands.append(msg)

    def test_cmd_is_published_if_module_id_matches_device_id(self, mock: Mock):
        mock.side_effect = self.publish
        self.es._handle_command(module_id=1000, data=b"cmd", device=self.device)
        self.assertEqual(self.published_commands, [command("id", 0, self.device, b"cmd")])

    def test_cmd_is_published_when_module_id_does_not_match_device_id_and_sending_invalid_cmd_is_allowed(
        self, mock: Mock
    ):
        self.es._config.send_invalid_command = True
        mock.side_effect = self.publish
        with self.assertLogs(_eslogger, logging.WARNING):
            self.es._handle_command(module_id=1001, data=b"cmd", device=self.device)
            self.assertEqual(self.published_commands, [command("id", 0, self.device, b"cmd")])

    def test_cmd_is_not_published_when_module_id_does_not_match_device_id_and_sending_invalid_cmd_is_disallowed(
        self, mock: Mock
    ):
        self.es._config.send_invalid_command = False
        mock.side_effect = self.publish
        with self.assertLogs(_eslogger, logging.WARNING):
            self.es._handle_command(module_id=1001, data=b"cmd", device=self.device)
            self.assertEqual(self.published_commands, [])

    def test_cmd_is_published_and_warning_is_logged_when_data_is_empty(self, mock: Mock):
        mock.side_effect = self.publish
        with self.assertLogs(_eslogger, logging.WARNING):
            self.es._handle_command(module_id=1000, data=b"", device=self.device)
            self.assertEqual(self.published_commands, [command("id", 0, self.device, b"")])

    def test_cmd_is_published_and_warning_is_logged_when_device_is_not_connected(self, mock: Mock):
        mock.side_effect = self.publish
        self.es._known_devices.not_connected(self.device)
        with self.assertLogs(_eslogger, logging.WARNING) as cm:
            self.es._handle_command(module_id=1000, data=b"cmd", device=self.device)
            self.assertIn("not connected", cm.output[0])
            self.assertEqual(self.published_commands, [command("id", 0, self.device, b"cmd")])


class Test_Response_Session_ID(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_car_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.published_responses: list[ExternalServerMsg] = list()
        self.es._add_connected_devices(self.device)
        self.es._mqtt.session.set_id("id")

    def test_status_response_is_not_sent_if_session_id_of_status_does_not_match_current_session(
        self,
    ):
        with self.assertLogs(_eslogger, logging.WARNING):
            self.es._handle_checked_status(
                status("some_other_id", Status.RUNNING, 1, DeviceStatus(device=self.device)).status
            )
            self.assertEqual(self.published_responses, [])


class Test_Handling_Car_Message_On_Normal_Communication(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_car_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.published_responses: list[ExternalServerMsg] = list()
        self.es._add_connected_devices(self.device)
        self.es._mqtt.session.set_id("id")

    def publish(self, msg: ExternalServerMsg) -> None:
        self.published_responses.append(msg)

    def test_no_message_in_queue_raises_error(self):
        self.assertTrue(self.es.mqtt._received_msgs.empty)
        with self.assertRaises(NoMessage):
            self.es._handle_car_message()

    @patch("external_server.adapters.mqtt.adapter.MQTTClientAdapter.publish")
    def test_connect_message_logs_error_and_produces_connect_response(self, mock: Mock):
        mock.side_effect = self.publish
        self.es.mqtt._received_msgs.put(connect_msg("id", company="company", devices=[]))
        with self.assertLogs(_eslogger, logging.INFO) as cm:
            self.es._handle_car_message()
            self.assertIn("already existing session", cm.output[-1])

    def test_connect_message_with_session_id_not_matching_current_session_logs_error_and_yields_no_action(
        self,
    ):
        self.es.mqtt._received_msgs.put(
            connect_msg("other_session_id", company="company", devices=[])
        )
        with self.assertLogs(_eslogger, logging.INFO) as cm:
            self.es._handle_car_message()
            self.assertIn("not matching current one", cm.output[-1])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
