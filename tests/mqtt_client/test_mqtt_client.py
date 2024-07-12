import unittest
import sys
import time
import concurrent.futures
import socket
from unittest.mock import patch, Mock

sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from paho.mqtt.client import MQTTMessage

from queue import Empty
from external_server.clients.mqtt_client import MQTTClient, _QOS# type: ignore
from InternalProtocol_pb2 import (  # type: ignore
    Device,
    DeviceCommand,
    DeviceConnect,
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
from external_server.models.event_queue import EventType  # type: ignore
from tests.utils import MQTTBrokerTest  # type: ignore


TEST_ADDRESS = "127.0.0.1"
TEST_PORT = 1883


class Test_Creating_MQTT_Client(unittest.TestCase):

    @patch("external_server.clients.mqtt_client.mqtt.Client.subscribe")
    def test_wrapped_client_subscribes_to_topic(self, mock: Mock):
        client = MQTTClient("some_company", "test_car", timeout=1, broker_host="", broker_port=0)
        self.assertTrue(client.subscribe_topic.startswith("some_company/test_car"))
        mock.assert_called_with(client.subscribe_topic, qos=_QOS)


class Test_MQTT_Client_Company_And_Car_Name(unittest.TestCase):

    def test_publish_topic_value_starts_with_company_name_slash_car_name(self):
        client = MQTTClient("some_company", "test_car", timeout=1, broker_host="", broker_port=0)
        self.assertTrue(client.publish_topic.startswith("some_company/test_car"))

    def test_empty_company_name_is_allowed(self):
        client = MQTTClient(company="", car_name="test_car", timeout=1, broker_host="", broker_port=0)
        self.assertTrue(client.publish_topic.startswith("/test_car"))

    def test_empty_car_name_is_allowed(self):
        client = MQTTClient(company="some_company", car_name="", timeout=1, broker_host="", broker_port=0)
        self.assertTrue(client.publish_topic.startswith("some_company/"))

    def test_both_names_empty_is_allowed(self):
        client = MQTTClient(company="", car_name="", timeout=1, broker_host="", broker_port=0)
        self.assertTrue(client.publish_topic.startswith("/"))


class Test_Failing_Client_Connection(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MQTTClient(
            "some_company", "test_car", timeout=1, broker_host="", broker_port=0
        )

    def test_client_is_not_initially_connected(self):
        self.assertFalse(self.client.is_connected)

    def test_connecting_to_nonexistent_broker_raises_socket_gaiaerror(self) -> None:
        self.client._set_up_callbacks()
        self.client.update_broker_host_and_port(broker_host="nonexistent_ip", broker_port=TEST_PORT)
        with self.assertRaises(socket.gaierror):
            self.client.connect()


class Test_MQTT_Client_Connection(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MQTTClient(
            "some_company",
            "test_car",
            timeout=1,
            broker_host=TEST_ADDRESS,
            broker_port=TEST_PORT,
        )
        self.test_broker = MQTTBrokerTest(start=True)
        self.client.connect()

    def test_connecting_and_starting_client_marks_client_as_connected(self) -> None:
        self.assertFalse(self.client.is_connected)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(self.client.start)
            time.sleep(0.01)
            self.assertTrue(self.client.is_connected)

    def test_stopped_client_is_still_connected(self) -> None:
        self.assertFalse(self.client.is_connected)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(self.client.start)
            time.sleep(0.02)
            self.client.stop()
            self.assertTrue(self.client.is_connected)

    def tearDown(self) -> None:
        self.test_broker.stop()


class Test_Publishing_Message(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MQTTClient(
            "some_company",
            "test_car",
            timeout=1,
            broker_host=TEST_ADDRESS,
            broker_port=TEST_PORT,
        )
        self.broker = MQTTBrokerTest(start=True)
        self.client.connect()
        self.device = Device(
            module=Device.MISSION_MODULE,
            deviceType=4,
            deviceName="AutonomyDevice",
            deviceRole="autonomy-device",
            priority=1,
        )

    def test_device_connect_message(self):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            msg = DeviceConnect(device=self.device)
            pub_msg = executor.submit(self.broker.get_messages, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result()[0].payload)

    def test_connect_response(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = ConnectResponse(sessionId="some-session-id", type=ConnectResponse.OK)
            pub_msg = ex.submit(self.broker.get_messages, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result()[0].payload)

    def test_device_status(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = Status(
                sessionId="some-session-id",
                deviceState=Status.RUNNING,
                messageCounter=4,
                deviceStatus=DeviceStatus(device=self.device, statusData=b"working"),
            )
            pub_msg = ex.submit(self.broker.get_messages, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result()[0].payload)

    def test_status_response(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = StatusResponse(
                sessionId="some-session-id", messageCounter=4, type=StatusResponse.OK
            )
            pub_msg = ex.submit(self.broker.get_messages, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result()[0].payload)

    def test_device_command(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = DeviceCommand(device=self.device, commandData=b"some-command")
            pub_msg = ex.submit(self.broker.get_messages, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result()[0].payload)

    def test_command_response(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = CommandResponse(sessionId="some-session-id", type=CommandResponse.OK)
            pub_msg = ex.submit(self.broker.get_messages, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result()[0].payload)

    def tearDown(self) -> None:
        self.broker.stop()


class Test_MQTT_Client_Receiving_Message(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MQTTClient(
            "some_company",
            "test_car",
            timeout=1,
            broker_host=TEST_ADDRESS,
            broker_port=TEST_PORT,
        )
        self.broker = MQTTBrokerTest(start=True)
        self.client._set_up_callbacks()
        self.client.connect()
        self.device = Device(
            module=Device.MISSION_MODULE,
            deviceType=4,
            deviceName="AutonomyDevice",
            deviceRole="autonomy-device",
            priority=1,
        )

    def test_mqtt_client_receives_connect_message(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = ExternalClient(
                connect=Connect(
                    sessionId="some_session_id",
                    company="some_company",
                    vehicleName="test_car",
                    devices=[self.device],
                )
            )
            ex.submit(self.client.start)
            rec_msg = ex.submit(self.client.get_message)
            time.sleep(0.5)
            self.broker.publish_messages(self.client.subscribe_topic, msg.SerializeToString())
            rec_msg = rec_msg.result()
            self.assertEqual(msg, rec_msg)

    def tearDown(self) -> None:
        self.broker.stop()


class Test_Getting_Message(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MQTTClient(
            "some_company",
            "test_car",
            timeout=1,
            broker_host=TEST_ADDRESS,
            broker_port=TEST_PORT,
        )

    @patch("external_server.clients.mqtt_client.Queue.get")
    def test_getting_no_message_returns_none(self, mock: Mock) -> None:
        mock.side_effect = lambda block, timeout: None
        self.assertIsNone(self.client.get_message())

    @patch("external_server.clients.mqtt_client.Queue.get")
    def test_getting_message_equal_to_false_returns_False(self, mock: Mock) -> None:
        mock.side_effect = lambda block, timeout: False
        self.assertFalse(self.client.get_message())

    @patch("external_server.clients.mqtt_client.Queue.get")
    def test_getting_message_with_some_nonempty_content_yields_the_message(self, mock: Mock) -> None:
        mock.side_effect = lambda block, timeout: {"content": "some content"}
        self.assertEqual(self.client.get_message(), {"content": "some content"})


class Test_On_Message_Callback(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MQTTClient(
            "some_company",
            "test_car",
            timeout=0.5,
            broker_host=TEST_ADDRESS,
            broker_port=TEST_PORT,
        )

    def test_event_and_msg_queues_are_initially_empty(self):
        self.assertTrue(self.client._event_queue.empty())
        self.assertTrue(self.client.received_messages.empty())

    def test_receiving_empty_message_adds_it_to_the_queue(self):
        message = MQTTMessage()
        message.topic = self.client.subscribe_topic.encode()
        message.payload = b""
        self.client._on_message(client=self.client, _userdata=None, message=message)
        msg = self.client.received_messages.get(block=True, timeout=0.1)
        self.assertEqual(msg, ExternalClient())
        event = self.client._event_queue.get(block=True, timeout=0.1)
        self.assertEqual(event, EventType.RECEIVED_MESSAGE)

    def test_receiving_empty_message_on_wrong_topic_does_not_add_it_to_queue(self):
        message = MQTTMessage()
        message.topic = "wrong_topic".encode()
        message.payload = b""
        self.client._on_message(client=self.client, _userdata=None, message=message)
        with self.assertRaises(Empty):
            self.client.received_messages.get(block=True, timeout=0.1)


class Test_On_Connect_Callback(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MQTTClient(
            "some_company",
            "test_car",
            timeout=0.5,
            broker_host=TEST_ADDRESS,
            broker_port=TEST_PORT,
        )

    def test_on_connect_callback_adds_no_event_to_queue(self):
        self.client._on_connect(client=self.client._mqtt_client, _userdata=None, _flags=None, _rc=0, properties=None)
        with self.assertRaises(Empty):
            self.client._event_queue.get(block=True, timeout=0.1)




class Test_MQTT_Client_Start_And_Stop(unittest.TestCase):

    def setUp(self) -> None:
        self.broker = MQTTBrokerTest(start=True)
        self.client = MQTTClient(
            "some_company",
            "test_car",
            timeout=5,
            broker_host=TEST_ADDRESS,
            broker_port=TEST_PORT,
        )

    def test_mqtt_client_receives_message_even_after_stopping_and_starting_again(self):
        self.client.connect()
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
            ex.submit(self.client.start)
            time.sleep(0.5)
            ex.submit(self.client.stop)
            time.sleep(1)
            ex.submit(self.client.start)
            time.sleep(0.2)
            rec_msg = ex.submit(self.client.get_message)
            ex.submit(self.broker.publish_messages, self.client.subscribe_topic, msg)
            self.assertEqual(msg, rec_msg.result())

    def tearDown(self) -> None:
        self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
