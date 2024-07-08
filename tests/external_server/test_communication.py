import unittest
import sys
import concurrent.futures as futures
import time
sys.path.append(".")

from pydantic import FilePath

from InternalProtocol_pb2 import Device, DeviceStatus
from ExternalProtocol_pb2 import Connect, ExternalClient, Status
from external_server.config import Config, ModuleConfig
from external_server.external_server import ExternalServer
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH, MQTTBrokerTest


ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "ba",
    "car_name": "car1",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 2,
    "timeout": 5,
    "send_invalid_command": False,
    "mqtt_client_connection_retry_period": 2,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000
}


class Test_Connecting_Device(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = Config(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)
        self.es = ExternalServer(config=self.config)
        self.device = Device(module=1000, deviceType=0, deviceName="TestDevice", deviceRole="test")
        self.mqttbroker = MQTTBrokerTest(start=True)
        self.connect_msg_payload = ExternalClient(
            connect=Connect(
                sessionId="some_id", company="ba", vehicleName="car1", devices=[self.device]
            )
        ).SerializeToString()
        time.sleep(0.02)

    def test_nothing(self):
        pass

    # def test_connecting_device(self):
    #     status_msg = Status(
    #         sessionId="some_id",
    #         deviceState=Status.DISCONNECT,
    #         messageCounter=1551,
    #         deviceStatus=DeviceStatus(device=self.device)
    #     )
    #     with futures.ThreadPoolExecutor() as ex:
    #         ex.submit(self.es.start)
    #         time.sleep(0.2)
    #         first_status_payload = ExternalClient(status=status_msg).SerializeToString()
    #         subsc_topic = self.es.mqtt_client.subscribe_topic
    #         ex.submit(self.mqttbroker.publish_message, topic=subsc_topic, payload=self.connect_msg_payload)
    #         ex.submit(self.mqttbroker.publish_message, topic=subsc_topic, payload=first_status_payload)
    #         time.sleep(0.2)
    #         self.es.stop()
    #         time.sleep(0.1)

    def tearDown(self) -> None:
        self.mqttbroker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()