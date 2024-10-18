import unittest
import sys
import time
import concurrent.futures
from unittest.mock import patch, Mock
import logging
import threading

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from paho.mqtt.client import MQTTMessage, MQTT_ERR_SUCCESS, Client

from queue import Empty
from external_server.adapters.mqtt.adapter import (  # type: ignore
    ClientConnectionState,
    create_mqtt_client,
    MQTTClientAdapter,
    mqtt_error_from_code,
    _QOS,
    _logger,
)
from InternalProtocol_pb2 import (  # type: ignore
    Device,
    DeviceCommand,
    DeviceStatus,
)
from ExternalProtocol_pb2 import (  # type: ignore
    CommandResponse,
    ConnectResponse,
    Connect,
    Status,
    StatusResponse,
    ExternalClient,
)
from external_server.models.events import EventType, EventQueue  # type: ignore
from external_server.models.messages import command, connect_msg, status as status_msg, cmd_response
from external_server.models.exceptions import MQTTCommunicationError

from tests.utils.mqtt_broker import MQTTBrokerTest  # type: ignore


TEST_ADDRESS = "127.0.0.1"
TEST_PORT = 1883


class Test_Client_Error_From_Code(unittest.TestCase):

    def test_unknown_error_is_returned_for_unknown_error_code(self):
        self.assertIn("Unknown error", mqtt_error_from_code(-611561851))


class Test_Creating_MQTT_Client(unittest.TestCase):
    """Tests for creating an MQTT client - NOT THE ADAPTER."""

    def wait_for_connection(self, client: Client, timeout_s: int = 2):
        start_time = time.monotonic()
        while not client.is_connected():
            if time.monotonic() - start_time > timeout_s:
                raise self.fail("Timeout while waiting for MQTT client connection in setUp.")
            time.sleep(0.01)

    def test_creating_mqtt_client_adapter(self):
        broker = MQTTBrokerTest(start=True)
        message_received = threading.Event()
        self.x = 0

        def on_message(client, userdata, message):
            self.x += 1
            message_received.set()

        client = create_mqtt_client("car")
        client.on_message = on_message
        client.connect(broker._host, broker._port)
        client.subscribe("some_topic", qos=_QOS)
        client.loop_start()
        self.wait_for_connection(client, timeout_s=1)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(broker.publish, "some_topic", "some_message")
            self.assertTrue(message_received.wait(timeout=5.0))
            self.assertEqual(self.x, 1)

        client.disconnect()
        broker.stop()
        client.loop_stop()


class Test_Creating_MQTT_Client_Adapter(unittest.TestCase):

    def test_sets_up_subscribe_and_publish_topics_including_company_and_car_name(self):
        adapter = MQTTClientAdapter(
            "company", "car", 2, broker_host="127.0.0.1", port=1883, event_queue=EventQueue()
        )
        self.assertEqual(
            adapter.subscribe_topic, f"company/car/{MQTTClientAdapter._MODULE_GATEWAY_SUFFIX}"
        )
        self.assertEqual(
            adapter.publish_topic, f"company/car/{MQTTClientAdapter._EXTERNAL_SERVER_SUFFIX}"
        )
        self.assertEqual(adapter.broker_address, "127.0.0.1:1883")

    def test_creates_empty_received_message_queue(self) -> None:
        adapter = MQTTClientAdapter(
            "company", "car", timeout=2, broker_host="", port=0, event_queue=EventQueue()
        )
        self.assertTrue(adapter.received_messages.empty())

    def test_mqtt_client_is_created(self):
        adapter = MQTTClientAdapter(
            "company", "car", timeout=2, broker_host="", port=0, event_queue=EventQueue()
        )
        self.assertTrue(adapter.client)

    def test_sets_up_callbacks_on_connect_disconnect_and_on_message(self):
        adapter = MQTTClientAdapter(
            "company", "car", timeout=2, broker_host="", port=0, event_queue=EventQueue()
        )
        self.assertEqual(adapter.client._on_connect, adapter._on_connect)
        self.assertEqual(adapter.client._on_disconnect, adapter._on_disconnect)
        self.assertEqual(adapter.client._on_message, adapter._on_message)
        self.assertIsNone(adapter.client._on_subscribe)
        self.assertIsNone(adapter.client._on_unsubscribe)
        self.assertIsNone(adapter.client._on_log)
        self.assertIsNone(adapter.client._on_pre_connect)
        self.assertIsNone(adapter.client._on_connect_fail)
        self.assertIsNone(adapter.client._on_publish)
        self.assertIsNone(adapter.client._on_socket_open)
        self.assertIsNone(adapter.client._on_socket_close)
        self.assertIsNone(adapter.client._on_socket_register_write)
        self.assertIsNone(adapter.client._on_socket_unregister_write)

    def test_leaves_client_in_connection_state_equal_to_new_and_without_connection_thread_existing(
        self,
    ):
        adapter = MQTTClientAdapter(
            "company", "car", timeout=2, broker_host="", port=0, event_queue=EventQueue()
        )
        self.assertEqual(adapter.client._state, ClientConnectionState.MQTT_CS_NEW)
        self.assertIsNone(adapter.thread)


class Test_MQTT_Client_Company_And_Car_Name(unittest.TestCase):

    def test_publish_topic_value_starts_with_company_name_slash_car_name(self):
        client = MQTTClientAdapter(
            "some_company", "test_car", timeout=1, broker_host="", port=0, event_queue=EventQueue()
        )
        self.assertTrue(client.publish_topic.startswith("some_company/test_car"))

    def test_empty_company_name_is_allowed(self):
        client = MQTTClientAdapter(
            company="", car="test_car", timeout=1, broker_host="", port=0, event_queue=EventQueue()
        )
        self.assertTrue(client.publish_topic.startswith("/test_car"))

    def test_empty_car_name_is_allowed(self):
        client = MQTTClientAdapter(
            company="some_company",
            car="",
            timeout=1,
            broker_host="",
            port=0,
            event_queue=EventQueue(),
        )
        self.assertTrue(client.publish_topic.startswith("some_company/"))

    def test_both_names_empty_is_allowed(self):
        client = MQTTClientAdapter(
            company="", car="", timeout=1, broker_host="", port=0, event_queue=EventQueue()
        )
        self.assertTrue(client.publish_topic.startswith("/"))


class Test_Connecting_To_Broker(unittest.TestCase):

    def setUp(self) -> None:
        self.adapter = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=1,
            broker_host="127.0.0.1",
            port=1883,
            event_queue=EventQueue(),
        )
        self.broker = MQTTBrokerTest()
        MQTTBrokerTest.kill_all_test_brokers()

    def test_connecting_to_not_running_broker_leaves_client_in_connecting_state(self):
        # the broker was not started
        with self.assertRaises(ConnectionRefusedError):
            self.adapter.connect()
        self.assertEqual(self.adapter.client._state, ClientConnectionState.MQTT_CS_CONNECTING)
        self.assertFalse(self.adapter.is_connected)

    def test_client_connecting_to_a_broker_ends_up_in_connected_state(self):
        self.broker.start()
        self.adapter.connect()
        self.assertEqual(self.adapter.client._state, ClientConnectionState.MQTT_CS_CONNECTED)
        self.assertTrue(self.adapter.is_connected)

    def test_repeated_connect_calls_have_no_effect_after_the_first_call(self):
        self.broker.start()
        self.adapter.connect()
        self.adapter.connect()
        self.assertEqual(self.adapter.client._state, ClientConnectionState.MQTT_CS_CONNECTED)

    def test_disconnecting_client_before_calling_connect_has_no_effect(self):
        self.broker.start()
        state_before = self.adapter.client._state
        self.adapter.disconnect()
        self.assertEqual(self.adapter.client._state, state_before)

    def test_client_after_disconnecting_is_in_disconnected_state(self):
        self.broker.start()
        self.adapter.connect()
        self.adapter.disconnect()
        self.assertEqual(self.adapter.client._state, ClientConnectionState.MQTT_CS_DISCONNECTED)

    def test_repeated_disconnect_calls_have_no_effect_after_the_first_call(self):
        self.broker.start()
        self.adapter.connect()
        self.adapter.disconnect()
        self.adapter.disconnect()
        self.assertEqual(self.adapter.client._state, ClientConnectionState.MQTT_CS_DISCONNECTED)

    def tearDown(self) -> None:
        self.broker.stop()
        self.adapter.stop()
        MQTTBrokerTest.kill_all_test_brokers()


class Test_Starting_MQTT_Client_From_Adapter(unittest.TestCase):

    def setUp(self) -> None:
        MQTTBrokerTest.kill_all_test_brokers()
        self.adapter = MQTTClientAdapter(
            "some_company", "test_car", 1, "127.0.0.1", 1883, EventQueue()
        )

    def test_client_loop_is_not_started_if_broker_does_not_exist(self):
        self.assertFalse(MQTTBrokerTest.running_processes())
        with self.assertRaises(ConnectionRefusedError):
            self.adapter.connect()
        self.adapter.client.publish(self.adapter.publish_topic)
        self.assertEqual(self.adapter.client._state, ClientConnectionState.MQTT_CS_CONNECTING)

    def test_client_loop_is_started_and_returns_connected_state_if_broker_does_exist(self):
        broker = MQTTBrokerTest(start=True, port=1883)
        self.adapter.connect()
        self.assertEqual(self.adapter.client._state, ClientConnectionState.MQTT_CS_CONNECTED)
        broker.stop()

    def tearDown(self) -> None:
        self.adapter.stop()
        MQTTBrokerTest.kill_all_test_brokers()


class Test_MQTT_Client_Connection(unittest.TestCase):

    def setUp(self) -> None:
        self.adapter = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=1,
            broker_host=TEST_ADDRESS,
            port=TEST_PORT,
            event_queue=EventQueue(),
        )
        self.test_broker = MQTTBrokerTest(start=True)
        self.adapter.connect()

    def test_connecting_and_starting_client_marks_client_as_connected(self) -> None:
        self.assertTrue(self.adapter.is_connected)

    def test_stopped_client_is_still_connected_but_not_running(self) -> None:
        self.adapter.stop()
        self.assertTrue(self.adapter.is_connected)
        self.assertFalse(self.adapter.is_running)

    @patch("paho.mqtt.client.Client.connect")
    def test_error_raised_when_non_ok_return_code_is_returned_from_mqtt_client(self, mock: Mock):
        mock.return_value = MQTT_ERR_SUCCESS + 1
        with self.assertRaises(ConnectionRefusedError):
            self.adapter.connect()

    def tearDown(self) -> None:
        self.test_broker.stop()
        self.adapter.stop()
        MQTTBrokerTest.kill_all_test_brokers()


class Test_Publishing_Message(unittest.TestCase):

    def setUp(self) -> None:
        self.adapter = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=1,
            broker_host=TEST_ADDRESS,
            port=TEST_PORT,
            event_queue=EventQueue(),
        )
        self.broker = MQTTBrokerTest(
            "some_company/test_car/external_server",
            "some_company/test_car/module_gateway",
            start=True,
        )
        self.adapter.connect()
        self.device = Device(
            module=Device.MISSION_MODULE,
            deviceType=4,
            deviceName="AutonomyDevice",
            deviceRole="autonomy-device",
            priority=1,
        )

    def test_connect_response(self):
        topic = "some_company/test_car/external_server"
        msg = ConnectResponse(sessionId="some-session-id", type=ConnectResponse.OK)
        self.adapter.publish(msg)
        messages = self.broker.wait_for_messages(topic, 1)
        self.assertEqual(len(messages), 1)
        self.assertEqual(msg.SerializeToString(), messages[0])

    def test_device_status(self):
        msg = Status(
            sessionId="some-session-id",
            deviceState=Status.RUNNING,
            messageCounter=4,
            deviceStatus=DeviceStatus(device=self.device, statusData=b"working"),
        )
        self.adapter.publish(msg)
        messages = self.broker.wait_for_messages("some_company/test_car/external_server", 1)
        self.assertEqual(len(messages), 1)
        self.assertEqual(msg.SerializeToString(), messages[0])

    def test_status_response(self):
        msg = StatusResponse(sessionId="some-session-id", messageCounter=4, type=StatusResponse.OK)
        topic = "some_company/test_car/external_server"
        self.adapter.publish(msg)
        messages = self.broker.wait_for_messages(topic, 1)
        self.assertEqual(len(messages), 1)
        self.assertEqual(msg.SerializeToString(), messages[0])

    def test_device_command(self):
        msg = DeviceCommand(device=self.device, commandData=b"some-command")
        self.adapter.publish(msg)
        messages = self.broker.wait_for_messages("some_company/test_car/external_server", 1)
        self.assertEqual(len(messages), 1)
        self.assertEqual(msg.SerializeToString(), messages[0])

    def test_command_response(self):
        msg = CommandResponse(sessionId="some-session-id", type=CommandResponse.OK)
        self.adapter.publish(msg)
        messages = self.broker.wait_for_messages("some_company/test_car/external_server", 1)
        self.assertEqual(len(messages), 1)
        self.assertEqual(msg.SerializeToString(), messages[0])

    def tearDown(self) -> None:
        self.broker.stop()
        self.adapter.stop()
        MQTTBrokerTest.kill_all_test_brokers()


class Test_MQTT_Client_Receiving_Message(unittest.TestCase):

    def setUp(self) -> None:
        self.broker = MQTTBrokerTest(start=True)
        self.adapter = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=2,
            broker_host=self.broker._host,
            port=self.broker._port,
            event_queue=EventQueue(),
        )
        assert self.broker.is_running
        self.adapter.connect()
        self.device = Device(
            module=Device.MISSION_MODULE,
            deviceType=4,
            deviceName="AutonomyDevice",
            deviceRole="autonomy-device",
            priority=1,
        )
        assert self.adapter._broker_host == self.broker._host
        assert self.adapter._broker_port == self.broker._port

    def test_mqtt_client_receives_connect_message(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = ExternalClient(
                connect=Connect(
                    sessionId="some_session_id",
                    company="some_company",
                    vehicleName="test_car",
                    devices=[self.device],
                )
            ).SerializeToString()
            future = ex.submit(self.adapter._get_message)
            ex.submit(self.broker.publish, self.adapter.subscribe_topic, msg)
            rec_msg = future.result(timeout=10.0)
            self.assertEqual(msg, rec_msg.SerializeToString())

    def tearDown(self) -> None:
        self.broker.stop()
        self.adapter.stop()
        MQTTBrokerTest.kill_all_test_brokers()


@patch("external_server.adapters.mqtt.adapter.Queue.get")
class Test_Getting_Message(unittest.TestCase):

    def setUp(self) -> None:
        self.adapter = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=1,
            broker_host=TEST_ADDRESS,
            port=TEST_PORT,
            event_queue=EventQueue(),
        )

    def test_getting_no_message_returns_none(self, mock: Mock) -> None:
        mock.side_effect = lambda block, timeout: None
        self.assertIsNone(self.adapter._get_message())

    def test_getting_message_equal_to_false_returns_False(self, mock: Mock) -> None:
        mock.side_effect = lambda block, timeout: False
        self.assertFalse(self.adapter._get_message())

    def test_getting_message_with_some_nonempty_content_yields_the_message(
        self, mock: Mock
    ) -> None:
        mock.side_effect = lambda block, timeout: {"content": "some content"}
        self.assertEqual(self.adapter._get_message(), {"content": "some content"})


class Test_On_Message_Callback(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=0.5,
            broker_host=TEST_ADDRESS,
            port=TEST_PORT,
            event_queue=EventQueue(),
        )
        self.client._event_queue.clear()

    def test_event_and_msg_queues_are_initially_empty(self):
        self.assertTrue(self.client._event_queue.empty())
        self.assertTrue(self.client.received_messages.empty())

    def test_receiving_empty_message_adds_it_to_the_queue(self):
        message = MQTTMessage()
        message.topic = self.client.subscribe_topic.encode()
        message.payload = b""
        self.client._on_message(client=self.client, data=None, message=message)
        msg = self.client.received_messages.get(block=True, timeout=0.1)
        self.assertEqual(msg, ExternalClient())
        event = self.client._event_queue.get(block=True, timeout=0.1)
        self.assertEqual(event.event_type, EventType.CAR_MESSAGE_AVAILABLE)

    def test_receiving_empty_message_on_wrong_topic_does_not_add_it_to_queue(self):
        message = MQTTMessage()
        message.topic = "wrong_topic".encode()
        message.payload = b""
        self.client._event_queue.clear()
        self.client._on_message(client=self.client, data=None, message=message)
        with self.assertRaises(Empty):
            self.client.received_messages.get(block=True, timeout=0.1)


class Test_On_Connect_Callback(unittest.TestCase):

    def setUp(self) -> None:
        self.adapter = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=0.5,
            broker_host=TEST_ADDRESS,
            port=TEST_PORT,
            event_queue=EventQueue(),
        )
        self.broker = MQTTBrokerTest()

    def test_on_connect_callback_logs_info_if_connected_to_broker(self):
        self.broker.start()
        with self.assertLogs(logger=_logger._logger, level=logging.INFO) as cm:
            self.adapter._on_connect(
                client=self.adapter._mqtt_client, data=None, flags=None, rc=0, properties=None
            )
            self.assertIn("Connected", cm.output[-1])

    def test_on_connect_callback_logs_error_if_could_not_connect_to_broker(self):
        with self.assertLogs(logger=_logger._logger, level=logging.INFO):
            self.adapter._on_connect(
                client=self.adapter._mqtt_client, data=None, flags=None, rc=0, properties=None
            )

    def tearDown(self) -> None:
        self.broker.stop()
        self.adapter.stop()
        MQTTBrokerTest.kill_all_test_brokers()


class Test_MQTT_Client_Start_And_Stop(unittest.TestCase):

    def setUp(self) -> None:
        self.broker = MQTTBrokerTest(start=True)
        self.adapter = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=5,
            broker_host=TEST_ADDRESS,
            port=TEST_PORT,
            event_queue=EventQueue(),
        )

    def test_mqtt_client_receives_message_even_after_stopping_and_starting_again(self):
        self.adapter.connect()
        self.device = Device(
            module=Device.MISSION_MODULE,
            deviceType=4,
            deviceName="AutonomyDevice",
            deviceRole="autonomy-device",
            priority=1,
        )
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = ExternalClient(
                connect=Connect(
                    sessionId="some_session_id",
                    company="some_company",
                    vehicleName="test_car",
                    devices=[self.device],
                )
            )
            ex.submit(self.adapter._start_client_loop)
            ex.submit(self.adapter.stop)
            ex.submit(self.adapter._start_client_loop)
            rec_msg = ex.submit(self.adapter._get_message)
            ex.submit(self.broker.publish, self.adapter.subscribe_topic, msg)
            self.assertEqual(msg, rec_msg.result())

    def tearDown(self) -> None:
        self.broker.stop()
        self.adapter.stop()
        MQTTBrokerTest.kill_all_test_brokers()


class Test_Unsuccessful_Connection_To_Broker(unittest.TestCase):

    def test_error_logged_if_broker_does_not_exist(self):
        adapter = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=0.5,
            broker_host="localhost",
            port=1884,
            event_queue=EventQueue(),
        )
        with self.assertLogs(logger=_logger._logger, level="ERROR"), self.assertRaises(
            ConnectionRefusedError
        ):
            adapter.connect()


class Test_MQTT_Client_Disconnected(unittest.TestCase):

    def setUp(self) -> None:
        self.broker = MQTTBrokerTest(start=True)
        self.adapter = MQTTClientAdapter(
            "some_company",
            "test_car",
            timeout=2,
            broker_host=TEST_ADDRESS,
            event_queue=EventQueue(),
            port=TEST_PORT,
        )

    def test_disconnecting_client_leaves_it_in_disconnected_state(self):
        self.adapter.connect()
        self.adapter.disconnect()
        self.assertFalse(self.adapter.is_connected)

    def test_disconnecting_client_twice_has_no_effect(self):
        self.adapter.connect()
        self.adapter.disconnect()
        self.adapter.disconnect()
        self.assertFalse(self.adapter.is_connected)

    @patch("paho.mqtt.client.Client.disconnect")
    def test_error_is_logged_when_non_ok_return_code_is_returned_from_mqtt_client(self, mock: Mock):
        mock.return_value = MQTT_ERR_SUCCESS + 1
        self.adapter.connect()
        with self.assertLogs(logger=_logger._logger, level=logging.ERROR):
            self.adapter.disconnect()

    def test_publishing_message_from_disconnected_client_logs_warning_and_raises_error(self):
        msg = command("session_id", 0, Device(), b"some_command")
        with self.assertLogs(logger=_logger._logger, level=logging.WARNING), self.assertRaises(
            MQTTCommunicationError
        ):
            self.adapter.publish(msg)

    def tearDown(self) -> None:
        self.broker.stop()
        self.adapter.stop()
        MQTTBrokerTest.kill_all_test_brokers()


class Test_Stopping_MQTT_Client_Adapter(unittest.TestCase):

    def setUp(self) -> None:
        self.broker = MQTTBrokerTest(start=True)
        self.adapter = MQTTClientAdapter(
            "some_company", "test_car", 1, TEST_ADDRESS, TEST_PORT, EventQueue()
        )

    def test_stopping_mqtt_client_adapter_leaves_it_connected_but_not_running(self):
        self.adapter.connect()
        self.assertTrue(self.adapter.is_connected)
        self.assertTrue(self.adapter.is_running)

        self.adapter.stop()
        self.assertTrue(self.adapter.is_connected)
        self.assertFalse(self.adapter.is_running)

    @patch("paho.mqtt.client.Client.loop_stop")
    def test_error_is_logged_when_mqtt_client_loop_stop_returns_non_ok_code(self, mock: Mock):
        some_non_ok_code = MQTT_ERR_SUCCESS + 2
        mock.return_value = some_non_ok_code
        self.adapter.connect()
        with self.assertLogs(logger=_logger._logger, level=logging.ERROR) as cm:
            self.adapter.stop()
            self.assertIn(mqtt_error_from_code(some_non_ok_code), cm.output[-1])

    def tearDown(self) -> None:
        self.broker.stop()


class Test_Expecting_Status(unittest.TestCase):

    def setUp(self) -> None:
        self.broker = MQTTBrokerTest(start=True)
        self.adapter = MQTTClientAdapter(
            "some_company", "test_car", 0.5, TEST_ADDRESS, TEST_PORT, EventQueue(), 1.0
        )
        self.adapter.connect()

    def test_without_any_message_published_yields_none(self):
        result = self.adapter.get_status()
        self.assertIsNone(result)

    def test_receiving_status_yields_status_message(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            device_status = DeviceStatus(device=Device(), statusData=b"")
            pub_msg = status_msg("id", 0, Status.RUNNING, device_status)
            f = ex.submit(self.adapter.get_status)
            ex.submit(
                self.broker.publish, self.adapter.subscribe_topic, pub_msg.SerializeToString()
            )
            self.assertEqual(f.result(), pub_msg.status)

    def test_receiving_command_response_yields_none(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            pub_msg = cmd_response("id", 0, CommandResponse.OK)
            f = ex.submit(self.adapter.get_status)
            ex.submit(
                self.broker.publish, self.adapter.subscribe_topic, pub_msg.SerializeToString()
            )
            self.assertIsNone(f.result())

    def test_receiving_connect_message_yields_none(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            pub_msg = connect_msg("id", "some_company", devices=[Device()])
            f = ex.submit(self.adapter.get_status)
            ex.submit(
                self.broker.publish, self.adapter.subscribe_topic, pub_msg.SerializeToString()
            )
            self.assertIsNone(f.result())

    def tearDown(self) -> None:
        self.adapter.stop()
        self.broker.stop()


class Test_Expecting_Connect_Message(unittest.TestCase):

    def setUp(self) -> None:
        self.broker = MQTTBrokerTest(start=True)
        self.adapter = MQTTClientAdapter(
            "some_company", "test_car", 0.5, TEST_ADDRESS, TEST_PORT, EventQueue()
        )
        self.adapter.connect()

    def test_without_any_message_published_yields_none(self):
        result = self.adapter.get_connect_message()
        self.assertIsNone(result)

    def test_receiving_connect_message_yields_connect_message(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            pub_msg = connect_msg("id", "some_company", devices=[Device()])
            f = ex.submit(self.adapter.get_connect_message)
            ex.submit(
                self.broker.publish, self.adapter.subscribe_topic, pub_msg.SerializeToString()
            )
            self.assertEqual(f.result(), pub_msg.connect)

    def test_receiving_command_response_yields_none(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            pub_msg = cmd_response("id", 0, CommandResponse.OK)
            f = ex.submit(self.adapter.get_connect_message)
            ex.submit(
                self.broker.publish, self.adapter.subscribe_topic, pub_msg.SerializeToString()
            )
            self.assertIsNone(f.result())

    def test_receiving_status_yields_none(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            device_status = DeviceStatus(device=Device(), statusData=b"")
            pub_msg = status_msg("id", 0, Status.RUNNING, device_status)
            f = ex.submit(self.adapter.get_connect_message)
            ex.submit(
                self.broker.publish, self.adapter.subscribe_topic, pub_msg.SerializeToString()
            )
            self.assertIsNone(f.result())

    def tearDown(self) -> None:
        self.adapter.stop()
        self.broker.stop()


class Test_Logging_Connection_Result(unittest.TestCase):

    def setUp(self) -> None:
        self.adapter = MQTTClientAdapter(
            "some_company", "test_car", 0.5, TEST_ADDRESS, TEST_PORT, EventQueue()
        )

    def test_error_is_logged_when_connecting_to_broker_fails(self):
        # broker does not exist
        with self.assertLogs(logger=_logger._logger, level=logging.ERROR), self.assertRaises(
            ConnectionRefusedError
        ):
            self.adapter.connect()

    def test_info_is_logged_when_just_connected_to_broker(self):
        MQTTBrokerTest(start=True)
        with self.assertLogs(logger=_logger._logger, level=logging.INFO):
            self.adapter.connect()

    def test_info_is_logged_when_already_connected_to_broker(self):
        MQTTBrokerTest(start=True)
        self.adapter.connect()
        with self.assertLogs(logger=_logger._logger, level=logging.INFO):
            self.adapter.connect()

    def tearDown(self) -> None:
        self.adapter.stop()
        MQTTBrokerTest.kill_all_test_brokers()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
