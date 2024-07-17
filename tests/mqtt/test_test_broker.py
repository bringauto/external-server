import unittest
import sys
import time

sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.adapters.mqtt_client import create_mqtt_client
from tests.utils import MQTTBrokerTest  # type: ignore


class Test_MQTTBroker(unittest.TestCase):

    def test_start_and_stop_broker(self):
        self.broker = MQTTBrokerTest(start=True)
        time.sleep(10)
        self.assertEqual(MQTTBrokerTest.running_processes(), [self.broker._process])
        self.broker.stop()
        self.assertEqual(MQTTBrokerTest.running_processes(), [])

        # client = create_mqtt_client()
        # client.connect("127.0.0.1", 1883)
        # time.sleep(0.2)
        # self.assertFalse(client.is_connected())
        # print(client._state)


if __name__=="__main__":
    unittest.main()