import unittest
import sys
import time
import concurrent.futures
import socket
sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.mqtt_client import MqttClient
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
    ExternalClient
)
from tests.utils import MQTTBrokerTest  # type: ignore


TEST_IP_ADDRESS = "127.0.0.1"
TEST_PORT = 1883


class Test_MQTT_Client_Company_And_Car_Name(unittest.TestCase):

    def test_publish_topic_value_starts_with_company_name_slash_car_name(self):
        client = MqttClient("some_company", "test_car")
        self.assertTrue(client.publish_topic.startswith("some_company/test_car"))

    def test_empty_company_name_is_allowed(self):
        client = MqttClient(company_name="", car_name="test_car")
        self.assertTrue(client.publish_topic.startswith("/test_car"))

    def test_empty_car_name_is_allowed(self):
        client = MqttClient(company_name="some_company", car_name="")
        self.assertTrue(client.publish_topic.startswith("some_company/"))

    def test_both_names_empty_is_allowed(self):
        client = MqttClient(company_name="", car_name="")
        self.assertTrue(client.publish_topic.startswith("/"))


class Test_Failing_Client_Connection(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MqttClient("some_company", "test_car")

    def test_client_is_not_initially_connected(self):
        self.assertFalse(self.client.is_connected)

    def test_connecting_to_nonexistent_broker_raises_socket_gaiaerror(self) -> None:
        self.client.init()
        with self.assertRaises(socket.gaierror):
            self.client.connect(ip_address="nonexistent_ip", port=TEST_PORT)


class Test_MQTT_Client_Connection(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MqttClient("some_company", "test_car")
        self.test_broker = MQTTBrokerTest(start=True)
        self.client.init()
        self.client.connect(ip_address=TEST_IP_ADDRESS, port=TEST_PORT)

    def test_connecting_and_starting_client_marks_client_as_connected(self) -> None:
        self.assertFalse(self.client.is_connected)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(self.client.start)
            time.sleep(0.01)
            self.assertTrue(self.client.is_connected)

    def test_stopped_client_is_marked_as_disconnected(self) -> None:
        self.assertFalse(self.client.is_connected)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(self.client.start)
            time.sleep(0.02)
            self.client.stop()
            self.assertFalse(self.client.is_connected)

    def tearDown(self) -> None:
        self.test_broker.stop()


class Test_Publishing_Message(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MqttClient("some_company", "test_car")
        self.broker = MQTTBrokerTest(start=True)
        self.client.init()
        self.client.connect(ip_address=TEST_IP_ADDRESS, port=TEST_PORT)
        self.device = Device(
                module = Device.MISSION_MODULE,
                deviceType = 4,
                deviceName = "AutonomyDevice",
                deviceRole = "autonomy-device",
                priority=1
            )

    def test_device_connect_message(self):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            msg = DeviceConnect(device=self.device)
            pub_msg = executor.submit(self.broker.next_published_msg, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result().payload)

    def test_connect_response(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = ConnectResponse(sessionId="some-session-id", type=ConnectResponse.OK)
            pub_msg = ex.submit(self.broker.next_published_msg, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result().payload)

    def test_device_status(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = Status(
                sessionId="some-session-id",
                deviceState=Status.RUNNING,
                messageCounter=4,
                deviceStatus=DeviceStatus(device=self.device, statusData=b"working"),
            )
            pub_msg = ex.submit(self.broker.next_published_msg, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result().payload)

    def test_status_response(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = StatusResponse(sessionId="some-session-id", messageCounter=4, type=StatusResponse.OK)
            pub_msg = ex.submit(self.broker.next_published_msg, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result().payload)

    def test_device_command(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = DeviceCommand(device=self.device, commandData=b"some-command")
            pub_msg = ex.submit(self.broker.next_published_msg, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result().payload)

    def test_command_response(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = CommandResponse(sessionId="some-session-id", type=CommandResponse.OK)
            pub_msg = ex.submit(self.broker.next_published_msg, self.client.publish_topic)
            time.sleep(0.05)
            self.client.publish(msg)
            self.assertEqual(msg.SerializeToString(), pub_msg.result().payload)

    def tearDown(self) -> None:
        self.broker.stop()


class Test_MQTT_Client_Receiving_Message(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MqttClient("some_company", "test_car")
        self.broker = MQTTBrokerTest(start=True)
        self.client.init()
        self.client.connect(ip_address=TEST_IP_ADDRESS, port=TEST_PORT)
        self.device = Device(
                module = Device.MISSION_MODULE,
                deviceType = 4,
                deviceName = "AutonomyDevice",
                deviceRole = "autonomy-device",
                priority=1
            )

    def test_mqtt_client_receives_connect_message(self):
        with concurrent.futures.ThreadPoolExecutor() as ex:
            msg = ExternalClient(
                connect=Connect(
                    sessionId="some_session_id",
                    company="some_company",
                    vehicleName="test_car",
                    devices=[self.device]
                )
            )
            ex.submit(self.client.start)
            rec_msg = ex.submit(self.client.get, timeout=1)
            time.sleep(0.5)
            self.broker.publish_message(topic=self.client.subscribe_topic, payload=msg.SerializeToString())
            rec_msg = rec_msg.result()
            self.assertEqual(msg, rec_msg)

    def tearDown(self) -> None:
        time.sleep(0.5)
        self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
