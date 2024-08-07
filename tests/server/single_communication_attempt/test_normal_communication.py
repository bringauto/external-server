import unittest
import sys
import concurrent.futures as futures
import time
import logging
from unittest.mock import patch, Mock

sys.path.append(".")

from external_server.server import ServerState, logger as _eslogger
from InternalProtocol_pb2 import Device, DeviceStatus  # type: ignore
from ExternalProtocol_pb2 import (  # type: ignore
    Command,
    CommandResponse,
    ExternalServer as ExternalServerMsg,
    Status,
)
from tests.utils import MQTTBrokerTest, get_test_server
from external_server.utils import connect_msg, status, cmd_response
from external_server.models.server_messages import status_response, command
from external_server.models.event_queue import EventType
from external_server.models.structures import HandledCommand
from external_server.models.exceptions import SessionTimeout


class Test_Receiving_Disconnect_State_From_Single_Supported_Device(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(
            module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1"
        )
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            device_status = DeviceStatus(device=self.device_1)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("session_id", "company", "car", [self.device_1]))
            self.broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            self.broker.publish(
                topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED)
            )
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        self.assertTrue(self.es._known_devices.is_connected(self.device_1))
        # the server is now initialized with mqtt client connected to broker

    def test_disconnect_state_from_connected_device_removes_it_from_connected_devices(self):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            self.broker.publish(
                topic,
                status("session_id", Status.DISCONNECT, 1, DeviceStatus(device=self.device_1)),
            )
            time.sleep(0.2)
            self.assertFalse(self.es._known_devices.is_connected(self.device_1))

    def test_disconnect_state_from_diconnected_device_has_no_effect(self):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            self.broker.publish(
                topic,
                status("session_id", Status.DISCONNECT, 1, DeviceStatus(device=self.device_1)),
            )
            time.sleep(0.3)
            self.broker.publish(
                topic,
                status("session_id", Status.DISCONNECT, 1, DeviceStatus(device=self.device_1)),
            )
            time.sleep(0.5)
            self.assertFalse(self.es._known_devices.is_connected(self.device_1))

    def test_sending_disconnect_state_from_the_only_connected_device_produces_status_response(self):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            time.sleep(0.1)
            future = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=1)
            time.sleep(0.3)
            self.broker.publish(
                topic,
                status("session_id", Status.DISCONNECT, 1, DeviceStatus(device=self.device_1)),
            )
            time.sleep(0.1)
            self.assertEqual(
                future.result()[0].payload, status_response("session_id", 1).SerializeToString()
            )

    def tearDown(self) -> None:
        self.broker.stop()
        self.es.mqtt.stop()


class Test_Receiving_Running_Status_Sent_By_Single_Supported_Device(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            self.broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            self.broker.publish(topic, cmd_response("session_id", 0, CommandResponse.OK))
        self.assertEqual(self.es.state, ServerState.INITIALIZED)
        # the server is now initialized with mqtt client connected to broker

    def test_status_sent_by_connected_device_publishes_status_response(self):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            future = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=1)
            self.broker.publish(
                topic, status("session_id", Status.RUNNING, 1, DeviceStatus(device=self.device))
            )
            self.assertTrue(self.es._known_devices.is_connected(self.device))
            self.assertEqual(
                future.result()[0].payload, status_response("session_id", 1).SerializeToString()
            )

    def test_status_containing_error_message_forwards_error(self):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            future = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=1)
            self.broker.publish(
                topic,
                status(
                    "session_id",
                    Status.RUNNING,
                    1,
                    DeviceStatus(device=self.device),
                    error_message=b"error",
                ),
            )
            self.assertTrue(self.es._known_devices.is_connected(self.device))
            self.assertEqual(
                future.result()[0].payload, status_response("session_id", 1).SerializeToString()
            )

    def test_multiple_statuses_sent_by_connected_device_publishes_status_responses_with_corresponding_counter_values(
        self,
    ):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            future = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=3)
            self.broker.publish(
                topic, status("session_id", Status.RUNNING, 1, DeviceStatus(device=self.device))
            )
            self.broker.publish(
                topic, status("session_id", Status.RUNNING, 2, DeviceStatus(device=self.device))
            )
            self.broker.publish(
                topic, status("session_id", Status.RUNNING, 3, DeviceStatus(device=self.device))
            )
            msgs = future.result()
            self.assertEqual(msgs[0].payload, status_response("session_id", 1).SerializeToString())
            self.assertEqual(msgs[1].payload, status_response("session_id", 2).SerializeToString())
            self.assertEqual(msgs[2].payload, status_response("session_id", 3).SerializeToString())

    def test_multiple_statuses_sent_in_wrong_order_produce_status_responses_in_correct_order(self):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            future = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=3)
            self.broker.publish(
                topic, status("session_id", Status.RUNNING, 2, DeviceStatus(device=self.device))
            )
            self.broker.publish(
                topic, status("session_id", Status.RUNNING, 3, DeviceStatus(device=self.device))
            )
            self.broker.publish(
                topic, status("session_id", Status.RUNNING, 1, DeviceStatus(device=self.device))
            )
            msgs = future.result()
            self.assertEqual(msgs[0].payload, status_response("session_id", 1).SerializeToString())
            self.assertEqual(msgs[1].payload, status_response("session_id", 2).SerializeToString())
            self.assertEqual(msgs[2].payload, status_response("session_id", 3).SerializeToString())

    def test_status_without_session_id_matching_current_session_id_is_ignored_and_no_response_is_sent_to_it(
        self,
    ):
        topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            future = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=2)
            self.broker.publish(
                topic, status("session_id", Status.RUNNING, 1, DeviceStatus(device=self.device))
            )
            self.broker.publish(
                topic, status("unknown_id", Status.RUNNING, 2, DeviceStatus(device=self.device))
            )
            self.broker.publish(
                topic, status("session_id", Status.RUNNING, 2, DeviceStatus(device=self.device))
            )
            msgs = future.result(timeout=3)
            self.assertEqual(len(msgs), 2)
            self.assertEqual(msgs[0].payload, status_response("session_id", 1).SerializeToString())
            self.assertEqual(msgs[1].payload, status_response("session_id", 2).SerializeToString())

    def tearDown(self) -> None:
        self.broker.stop()
        self.es.mqtt.stop()


class Test_Session_Time_Out(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            self.broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            self.broker.publish(
                topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED)
            )
            time.sleep(0.01)
        self.assertEqual(self.es.state, ServerState.INITIALIZED)

    def test_session_timeout_is_raised_if_no_message_from_module_gateway_is_received_in_time(self):
        with futures.ThreadPoolExecutor() as ex:
            self.assertTrue(self.es._known_devices.is_connected(self.device))
            future = ex.submit(self.es._run_normal_communication)
            time.sleep(self.es._session.timeout + 0.001)
            self.assertTrue(self.es._session.timeout_event.is_set())
            with self.assertRaises(SessionTimeout):
                future.result()

    def test_session_timeout_is_not_raised_if_status_is_received_in_time(self):
        with futures.ThreadPoolExecutor() as ex:
            self.assertTrue(self.es._known_devices.is_connected(self.device))
            ex.submit(self.es._run_normal_communication)
            time.sleep(self.es._session.timeout / 2)
            self.broker.publish(
                self.es.mqtt.subscribe_topic,
                status("session_id", Status.RUNNING, 1, DeviceStatus(device=self.device)),
            )
            time.sleep(
                self.es._session.timeout / 2 + 0.01
            )  # in total, the sleep time exceeds the timeout
            self.assertFalse(self.es._session.timeout_event.is_set())

    def test_session_timeout_is_not_raised_if_connect_respose_from_module_gateway_is_received_in_time(
        self,
    ):
        with futures.ThreadPoolExecutor() as ex:
            self.assertTrue(self.es._known_devices.is_connected(self.device))
            ex.submit(self.es._run_normal_communication)
            time.sleep(self.es._session.timeout / 2)
            self.broker.publish(
                self.es.mqtt.subscribe_topic, cmd_response("session_id", 1, CommandResponse.OK)
            )
            time.sleep(
                self.es._session.timeout / 2 + 0.02
            )  # in total, the sleep time exceeds the timeout
            self.assertFalse(self.es._session.timeout_event.is_set())

    def tearDown(self) -> None:
        self.broker.stop()
        self.es.mqtt.stop()


class Test_Statuses_Containing_Errors(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            self.broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            self.broker.publish(
                topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED)
            )
        self.assertEqual(self.es.state, ServerState.INITIALIZED)

    def test_nonempty_error_msg_from_status_is_logged(self):
        topic = self.es.mqtt.subscribe_topic
        with self.assertLogs(_eslogger, logging.ERROR):
            with futures.ThreadPoolExecutor() as ex:
                ex.submit(self.es._run_normal_communication)
                future = ex.submit(self.broker.get_messages, self.es.mqtt.publish_topic, n=1)
                self.broker.publish(
                    topic,
                    status(
                        "session_id",
                        Status.RUNNING,
                        1,
                        DeviceStatus(device=self.device),
                        error_message=b"error",
                    ),
                )
                self.assertEqual(
                    future.result()[0].payload, status_response("session_id", 1).SerializeToString()
                )

    def tearDown(self) -> None:
        self.broker.stop()
        self.es.mqtt.stop()


class Test_Receiving_Connect_Message(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server(mqtt_timeout=0.5)
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.2)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            self.broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            self.broker.publish(
                topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED)
            )
        self.assertEqual(self.es.state, ServerState.INITIALIZED)

    def test_connect_message_with_current_session_id_logs_error_and_produces_no_response(self):
        sub_topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            time.sleep(0.1)
            with self.assertLogs(_eslogger, logging.ERROR) as cm:
                self.broker.publish(
                    sub_topic, connect_msg("session_id", "company", "car", [self.device])
                )
                time.sleep(0.1)
                self.assertIn("already existing session", cm.records[0].message)

    def test_connect_message_with_other_session_id_does_not_logs_warning(self):
        sub_topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            time.sleep(0.1)
            with self.assertNoLogs(_eslogger, logging.WARNING):
                self.broker.publish(
                    sub_topic, connect_msg("other_session_id", "company", "car", [self.device])
                )

    def tearDown(self) -> None:
        self.broker.stop()
        self.es.stop()


class Test_Connecting_Device_During_Normal_Communication(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server(mqtt_timeout=0.5)
        self.broker = MQTTBrokerTest(start=True)
        self.device_1 = Device(
            module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1"
        )
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.1)
            device_status = DeviceStatus(device=self.device_1)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("session_id", "company", "car", [self.device_1]))
            self.broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            self.broker.publish(
                topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED)
            )

    def test_connecting_device_during_normal_communication_is_allowed(self):
        sub_topic = self.es.mqtt.subscribe_topic
        device_2 = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_2")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            self.broker.publish(
                sub_topic,
                status(
                    "session_id",
                    Status.CONNECTING,
                    1,
                    DeviceStatus(statusData=b"Connecting", device=device_2),
                ),
            )
            time.sleep(0.1)
            self.assertTrue(self.es._known_devices.is_connected(device_2))

    def tearDown(self) -> None:
        self.broker.stop()
        self.es.stop()


class Test_Checking_Command(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.1)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            self.broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            self.broker.publish(
                topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED)
            )

    def test_command_response_with_other_session_id_is_ignored(self):
        sub_topic = self.es.mqtt.subscribe_topic
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            time.sleep(0.1)
            with self.assertLogs(_eslogger, logging.WARNING) as cm:
                self.es._command_checker.add(HandledCommand(data=b"cmd", counter=1))
                self.broker.publish(
                    sub_topic, cmd_response("other_session_id", 1, CommandResponse.OK)
                )
                time.sleep(0.1)
                self.broker.publish(sub_topic, cmd_response("session_id", 1, CommandResponse.OK))

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_Receiving_Command(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server()
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.1)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("session_id", "company", "car", [self.device]))
            self.broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            self.broker.publish(
                topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED)
            )

    def test_command_response_received_after_publishing_command_from_api_is_acknowledged(self):
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            self.es._modules[1000].thread._commands.put((b"cmd", self.device))
            self.es._event_queue.add(event_type=EventType.COMMAND_AVAILABLE, data=1000)
            time.sleep(0.2)
            self.assertEqual(self.es._command_checker.n_of_expected_reponses, 1)
            self.broker.publish(
                self.es.mqtt.subscribe_topic, cmd_response("session_id", 1, CommandResponse.OK)
            )
            time.sleep(0.1)
            self.assertEqual(self.es._command_checker.n_of_expected_reponses, 0)

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


@patch("external_server.adapters.mqtt_adapter.MQTTClientAdapter.publish")
class Test_Handling_Command(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.published_commands: list[ExternalServerMsg] = list()
        self.es._add_connected_device(self.device)
        self.es._session.set_id("session_id")

    def publish(self, msg: ExternalServerMsg) -> None:
        self.published_commands.append(msg)

    def test_cmd_is_published_if_module_id_matches_device_id(self, mock: Mock):
        mock.side_effect = self.publish
        cmd = (b"cmd", self.device)
        self.es._handle_command(module_id=1000, command=cmd)
        self.assertEqual(self.published_commands, [command("session_id", 0, self.device, b"cmd")])

    def test_cmd_is_published_when_module_id_does_not_match_device_id_and_sending_invalid_cmd_is_allowed(
        self, mock: Mock
    ):
        self.es._config.send_invalid_command = True
        mock.side_effect = self.publish
        cmd = (b"cmd", self.device)
        with self.assertLogs(_eslogger, logging.WARNING):
            self.es._handle_command(module_id=1001, command=cmd)
            self.assertEqual(self.published_commands, [command("session_id", 0, self.device, b"cmd")])

    def test_cmd_is_not_published_when_module_id_does_not_match_device_id_and_sending_invalid_cmd_is_disallowed(
        self, mock: Mock
    ):
        self.es._config.send_invalid_command = False
        mock.side_effect = self.publish
        cmd = (b"cmd", self.device)
        with self.assertLogs(_eslogger, logging.WARNING):
            self.es._handle_command(module_id=1001, command=cmd)
            self.assertEqual(self.published_commands, [])

    def test_cmd_is_published_and_warning_is_logged_when_data_is_empty(self, mock: Mock):
        mock.side_effect = self.publish
        cmd = (b"", self.device)
        with self.assertLogs(_eslogger, logging.WARNING):
            self.es._handle_command(module_id=1000, command=cmd)
            self.assertEqual(self.published_commands, [command("session_id", 0, self.device, b"")])

    def test_cmd_is_published_and_warning_is_logged_when_device_is_not_connected(self, mock: Mock):
        mock.side_effect = self.publish
        cmd = (b"cmd", self.device)
        self.es._known_devices.not_connected(self.device)
        with self.assertLogs(_eslogger, logging.WARNING) as cm:
            self.es._handle_command(module_id=1000, command=cmd)
            self.assertIn("not connected", cm.output[0])
            self.assertEqual(self.published_commands, [command("session_id", 0, self.device, b"cmd")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
