import unittest
import sys
import time
import threading

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import Device, DeviceStatus  # type: ignore
from ExternalProtocol_pb2 import Status  # type: ignore
from external_server.server.single_car import ServerState
from external_server.server.all_cars import ExternalServer
from external_server.models.messages import connect_msg, status, cmd_response
from InternalProtocol_pb2 import Device as _Device  # type: ignore
from ExternalProtocol_pb2 import Status, CommandResponse  # type: ignore

from tests.utils import get_test_server
from tests.utils.mqtt_broker import MQTTBrokerTest


def _device_status(device: _Device, status_data: bytes = b"") -> DeviceStatus:
    return DeviceStatus(device=device, statusData=status_data)


def wait_for_server_connection(
    server: ExternalServer, test_case: unittest.TestCase, timeout: float = 2.0
):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        if all(server.mqtt.is_connected for server in server.car_servers().values()):
            return
        else:
            time.sleep(0.01)
    test_case.fail("Server did not connect to broker")


class Test_Multiple_Cars(unittest.TestCase):

    def setUp(self) -> None:
        self.es = get_test_server("company_x", "car_a", "car_b")
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(
            module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test_1"
        )
        self.es.start()
        wait_for_server_connection(self.es, self)

    def test_complete_connect_sequence_for_all_cars_sets_all_car_servers_to_running_state(self):
        connect_msg_a = connect_msg("car_a_session", "company_x", [self.device])
        connect_msg_b = connect_msg("car_b_session", "company_x", [self.device])
        self.broker.publish("company_x/car_a/module_gateway", connect_msg_a.SerializeToString())
        self.broker.publish("company_x/car_b/module_gateway", connect_msg_b.SerializeToString())
        time.sleep(0.1)
        status_a = status("car_a_session", Status.CONNECTING, 0, DeviceStatus(device=self.device))
        status_b = status("car_b_session", Status.CONNECTING, 0, DeviceStatus(device=self.device))
        self.broker.publish("company_x/car_a/module_gateway", status_a.SerializeToString())
        self.broker.publish("company_x/car_b/module_gateway", status_b.SerializeToString())
        time.sleep(0.1)
        cmd_response_a = cmd_response("car_a_session", 0)
        cmd_response_b = cmd_response("car_b_session", 0)
        self.broker.publish("company_x/car_a/module_gateway", cmd_response_a.SerializeToString())
        self.broker.publish("company_x/car_b/module_gateway", cmd_response_b.SerializeToString())
        time.sleep(0.1)
        for server in self.es.car_servers().values():
            self.assertEqual(server.state, ServerState.RUNNING)

    def test_complete_connect_sequence_for_only_some_cars_sets_only_these_cars_servers_to_running_state(
        self,
    ):
        connect_msg_a = connect_msg("car_a_session", "company_x", [self.device])
        connect_msg_b = connect_msg("car_b_session", "company_x", [self.device])
        self.broker.publish("company_x/car_a/module_gateway", connect_msg_a.SerializeToString())
        self.broker.publish("company_x/car_b/module_gateway", connect_msg_b.SerializeToString())
        time.sleep(0.1)

        # the car_b stopped sending messages, its connect sequence will fail and its server
        # will not be set to running state
        status_a = status("car_a_session", Status.CONNECTING, 0, DeviceStatus(device=self.device))
        self.broker.publish("company_x/car_a/module_gateway", status_a.SerializeToString())
        time.sleep(0.1)
        cmd_response_a = cmd_response("car_a_session", 0)
        self.broker.publish("company_x/car_a/module_gateway", cmd_response_a.SerializeToString())
        time.sleep(0.1)
        self.assertEqual(self.es.car_servers()["car_a"].state, ServerState.RUNNING)
        self.assertNotEqual(self.es.car_servers()["car_b"].state, ServerState.RUNNING)

    def tearDown(self) -> None:
        self.es.stop()
        self.broker.stop()


class Test_MQTT_Client_Thread_Exists_Before_Server_Is_Started(unittest.TestCase):

    def setUp(self):
        self.es = get_test_server("x", "car_a", timeout=0.5, mqtt_timeout=0.7)
        self.broker = MQTTBrokerTest(start=True)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")

    def test_warning_is_logged_and_thread_is_replaced_with_new_valid_thread(self):
        server_a = self.es.car_servers()["car_a"]
        server_a.mqtt.client._thread = threading.Thread(target=lambda: None)
        orig_invalid_thread = server_a.mqtt.client._thread
        with self.assertLogs(level="WARNING") as cm:
            self.es.start()
            time.sleep(0.1)
            self.assertIn(
                "Attempted to start MQTT client traffic-processing loop, but it is already running",
                cm.output[0],
            )
            self.assertTrue(server_a.mqtt.client._thread.is_alive())
            self.assertNotEqual(server_a.mqtt.client._thread, orig_invalid_thread)

    def tearDown(self):
        self.es.stop()
        self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
