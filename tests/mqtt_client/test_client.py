import unittest
import sys
import time
import concurrent.futures
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")


from external_server.mqtt_client import MqttClient


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


class Test_MQTT_Client_Connection(unittest.TestCase):

    def setUp(self) -> None:
        self.client = MqttClient("some_company", "test_car")

    def test_client_is_not_initially_connected(self):
        self.assertFalse(self.client.is_connected)

    def test_connecting_and_starting_client_marks_client_as_connected(self) -> None:
        self.client.init()
        self.client.connect(ip_address=TEST_IP_ADDRESS, port=TEST_PORT)
        self.assertFalse(self.client.is_connected)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(self.client.start)
            time.sleep(0.01)
            self.assertTrue(self.client.is_connected)
            future.result()

    def tearDown(self) -> None:
        pass


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
