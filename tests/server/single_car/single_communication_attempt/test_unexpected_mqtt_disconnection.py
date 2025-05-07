import unittest
import sys
from concurrent import futures
import time

sys.path.append(".")

from fleet_protocol_protobuf_files.InternalProtocol_pb2 import Device, DeviceStatus
from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import (
    CommandResponse,
    ExternalServer as ExternalServerMsg,
    Status,
)
from external_server.server.single_car import ServerState
from external_server.models.exceptions import UnexpectedMQTTDisconnect
from external_server.models.events import Event, EventType
from external_server.models.messages import cmd_response, connect_msg, status
from tests.utils import get_test_car_server
from tests.utils.mqtt_broker import MQTTBrokerTest


class Test_Unexpected_MQTT_Client_Disconnection(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_car_server()
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.published_responses: list[ExternalServerMsg] = list()
        self.es._add_connected_devices(self.device)
        self.es._mqtt.session.set_id("session_id")

    def test_unexpected_disconnect_raises_error_when_handling_event(self):
        event = Event(event_type=EventType.MQTT_BROKER_DISCONNECTED)
        with self.assertRaises(UnexpectedMQTTDisconnect):
            self.es._handle_communication_event(event)


class Test_Unexpected_MQTT_Client_Disconnection_During_Normal_Communication(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_car_server(mqtt_timeout=5)
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_initial_sequence)
            time.sleep(0.1)
            device_status = DeviceStatus(device=self.device)
            topic = self.es.mqtt.subscribe_topic
            self.broker.publish(topic, connect_msg("session_id", "company", [self.device]))
            self.broker.publish(topic, status("session_id", Status.CONNECTING, 0, device_status))
            self.broker.publish(
                topic, cmd_response("session_id", 0, CommandResponse.DEVICE_NOT_CONNECTED)
            )

    def test_receiving_unexpected_disconnect_event_removes_device_stops_normal_communication(self):
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es._run_normal_communication)
            time.sleep(0.1)
            self.assertEqual(self.es.state, ServerState.RUNNING)
            self.es._mqtt.disconnect()
            time.sleep(0.1)
            self.assertEqual(self.es.state, ServerState.ERROR)
            self.assertFalse(self.es.mqtt.is_connected)

    def tearDown(self) -> None:
        self.broker.stop()
        self.es.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
