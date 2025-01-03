import unittest
import sys
import concurrent.futures as futures
import time

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from pydantic import FilePath

from external_server.config import CarConfig, ModuleConfig
from external_server.server.single_car import CarServer, ServerState
from external_server.models.events import EventQueue
from external_server.adapters.mqtt.adapter import MQTTClientAdapter
from external_server.checkers.command_checker import PublishedCommandChecker
from external_server.checkers.status_checker import StatusChecker

from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH
from tests.utils.mqtt_broker import MQTTBrokerTest


ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "bring_auto",
    "car_name": "test_car",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 2,
    "timeout": 5,
    "send_invalid_command": False,
    "sleep_duration_after_connection_refused": 2,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000,
}


class Test_Creating_External_Server_Instance(unittest.TestCase):

    def setUp(self) -> None:
        self.example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )

    def test_module_dict_key_in_config_equal_to_the_module_id_is_accepted(self):
        correct_id = "1000"
        self.config = CarConfig(
            modules={correct_id: self.example_module_config}, **ES_CONFIG_WITHOUT_MODULES
        )
        self.event_queue = EventQueue(self.config.car_name)
        self.mqtt_adapter = MQTTClientAdapter(
            company=self.config.company_name,
            car=self.config.car_name,
            broker_host=self.config.mqtt_address,
            port=self.config.mqtt_port,
            event_queue=self.event_queue,
            timeout=self.config.timeout,
            mqtt_timeout=self.config.mqtt_timeout,
        )
        self.status_checker = StatusChecker(
            timeout=self.config.timeout, event_queue=self.event_queue, car=self.config.car_name
        )
        self.command_checker = PublishedCommandChecker(
            timeout=self.config.timeout, event_queue=self.event_queue, car=self.config.car_name
        )
        self.es = CarServer(
            config=self.config,
            mqtt_adapter=self.mqtt_adapter,
            event_queue=self.event_queue,
            status_checker=self.status_checker,
            command_checker=self.command_checker,
        )

    def test_module_dict_key_in_config_not_equal_to_the_module_id_raises_error(self):
        incorrect_id = "111111111"
        self.config = CarConfig(
            modules={incorrect_id: self.example_module_config}, **ES_CONFIG_WITHOUT_MODULES
        )
        self.event_queue = EventQueue(self.config.car_name)
        self.mqtt_adapter = MQTTClientAdapter(
            company=self.config.company_name,
            car=self.config.car_name,
            broker_host=self.config.mqtt_address,
            port=self.config.mqtt_port,
            event_queue=self.event_queue,
            timeout=self.config.timeout,
            mqtt_timeout=self.config.mqtt_timeout,
        )
        self.status_checker = StatusChecker(
            timeout=self.config.timeout, event_queue=self.event_queue, car=self.config.car_name
        )
        self.command_checker = PublishedCommandChecker(
            timeout=self.config.timeout, event_queue=self.event_queue, car=self.config.car_name
        )
        with self.assertRaises(RuntimeError):
            self.es = CarServer(
                config=self.config,
                mqtt_adapter=self.mqtt_adapter,
                event_queue=self.event_queue,
                status_checker=self.status_checker,
                command_checker=self.command_checker,
            )


class Test_Initial_State_Of_External_Server(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = CarConfig(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        event_queue = EventQueue(self.config.car_name)
        mqtt_adapter = MQTTClientAdapter(
            company=self.config.company_name,
            car=self.config.car_name,
            broker_host=self.config.mqtt_address,
            port=self.config.mqtt_port,
            event_queue=event_queue,
            timeout=self.config.timeout,
            mqtt_timeout=self.config.mqtt_timeout,
        )
        status_checker = StatusChecker(
            timeout=self.config.timeout, event_queue=event_queue, car=self.config.car_name
        )
        command_checker = PublishedCommandChecker(
            timeout=self.config.timeout, event_queue=event_queue, car=self.config.car_name
        )
        self.es = CarServer(
            config=self.config,
            mqtt_adapter=mqtt_adapter,
            event_queue=event_queue,
            status_checker=status_checker,
            command_checker=command_checker,
        )

    def test_external_server_initially_has_no_connected_devices(self):
        self.assertEqual(self.es._known_devices.n_connected, 0)

    def test_external_server_initially_has_mqtt_client_disconnected(self):
        self.assertFalse(self.es.mqtt.is_connected)

    def test_external_server_has_modules_created(self):
        self.assertEqual(len(self.es.modules), 1)
        self.assertIn(1000, self.es.modules)

    def test_all_devices_are_initialized(self):
        self.assertTrue(self.es.modules[1000].api.device_initialized())

    def test_session_id_is_empty(self):
        self.assertEqual(self.es.session_id, "")


class Test_Server_State(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = CarConfig(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        event_queue = EventQueue(self.config.car_name)
        mqtt_adapter = MQTTClientAdapter(
            company=self.config.company_name,
            car=self.config.car_name,
            broker_host=self.config.mqtt_address,
            port=self.config.mqtt_port,
            event_queue=event_queue,
            timeout=self.config.timeout,
            mqtt_timeout=self.config.mqtt_timeout,
        )
        status_checker = StatusChecker(
            timeout=self.config.timeout, event_queue=event_queue, car=self.config.car_name
        )
        command_checker = PublishedCommandChecker(
            timeout=self.config.timeout, event_queue=event_queue, car=self.config.car_name
        )
        self.es = CarServer(
            config=self.config,
            mqtt_adapter=mqtt_adapter,
            event_queue=event_queue,
            status_checker=status_checker,
            command_checker=command_checker,
        )

    def test_server_state_is_read_only(self):
        with self.assertRaises(AttributeError):
            self.es.state = ServerState.RUNNING


class Test_External_Server_Start(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = CarConfig(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.broker = MQTTBrokerTest(start=True)
        event_queue = EventQueue(self.config.car_name)
        mqtt_adapter = MQTTClientAdapter(
            company=self.config.company_name,
            car=self.config.car_name,
            broker_host=self.config.mqtt_address,
            port=self.config.mqtt_port,
            event_queue=event_queue,
            timeout=self.config.timeout,
            mqtt_timeout=self.config.mqtt_timeout,
        )
        status_checker = StatusChecker(
            timeout=self.config.timeout, event_queue=event_queue, car=self.config.car_name
        )
        command_checker = PublishedCommandChecker(
            timeout=self.config.timeout, event_queue=event_queue, car=self.config.car_name
        )
        self.es = CarServer(
            config=self.config,
            mqtt_adapter=mqtt_adapter,
            event_queue=event_queue,
            status_checker=status_checker,
            command_checker=command_checker,
        )
        time.sleep(0.2)

    def test_starting_and_stopping_server_connects_and_disconnects_the_mqtt_client(self):
        with futures.ThreadPoolExecutor() as ex:
            ex.submit(self.es.start)
            time.sleep(0.5)
            self.assertTrue(self.es.mqtt.is_connected)
            ex.submit(self.es.stop, reason="test")
            time.sleep(1)
            self.assertFalse(self.es.mqtt.is_connected)

    def tearDown(self) -> None:
        self.broker.stop()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
