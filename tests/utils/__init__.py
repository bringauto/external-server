import os as _os

from pydantic import FilePath

from external_server import CarServer, ExternalServer
from external_server.config import (
    CarConfig as _CarConfig,
    ModuleConfig as _ModuleConfig,
    ServerConfig as _ServerConfig,
)
from external_server.checkers.command_checker import PublishedCommandChecker
from external_server.checkers.status_checker import StatusChecker
from external_server.adapters.mqtt.adapter import MQTTClientAdapter
from external_server.models.events import EventQueue


EXAMPLE_MODULE_SO_LIB_PATH: FilePath = FilePath(
    _os.path.abspath("tests/utils/example_module/_build/libexample-external-server-sharedd.so")
)


COMMON_CONFIG = {
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 2,
    "timeout": 2,
    "send_invalid_command": False,
    "sleep_duration_after_connection_refused": 2,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000,
    "logging": {
        "console": {"level": "DEBUG", "use": True},
        "file": {"level": "DEBUG", "use": True, "path": "./log"},
    },
}

CAR_CONFIG_WITHOUT_MODULES = {"company_name": "ba", "car_name": "car1", **COMMON_CONFIG}
ES_CONFIG_WITHOUT_MODULES = {"company_name": "ba", **COMMON_CONFIG}


def get_test_server(
    company: str, *car_names: str, mqtt_timeout: float = -1, timeout: float = -1
) -> ExternalServer:
    module_config = _ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
    cars: dict[str, dict] = {car_name: {} for car_name in car_names}
    config = _ServerConfig(common_modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES, cars=cars)  # type: ignore
    config.company_name = company
    if mqtt_timeout > 0:
        config.mqtt_timeout = mqtt_timeout
    if timeout > 0:
        config.timeout = timeout
    es = ExternalServer(config=config)
    for e in es.car_servers().values():
        e.mqtt.client.disable_logger()
    return es


def get_test_car_server(mqtt_timeout: float = -1, timeout: float = -1) -> CarServer:
    module_config = _ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
    config = _CarConfig(modules={"1000": module_config}, **CAR_CONFIG_WITHOUT_MODULES)  # type: ignore
    if mqtt_timeout > 0:
        config.mqtt_timeout = mqtt_timeout
    if timeout > 0:
        config.timeout = timeout

    event_queue = EventQueue(config.car_name)
    status_checker = StatusChecker(
        timeout=config.timeout, event_queue=event_queue, car=config.car_name
    )
    command_checker = PublishedCommandChecker(
        timeout=config.timeout, event_queue=event_queue, car=config.car_name
    )
    mqtt_adapter = MQTTClientAdapter(
        company=config.company_name,
        car=config.car_name,
        broker_host=config.mqtt_address,
        port=config.mqtt_port,
        timeout=config.mqtt_timeout,
        event_queue=event_queue,
        mqtt_timeout=config.timeout,
    )

    es = CarServer(
        config=config,
        event_queue=event_queue,
        status_checker=status_checker,
        command_checker=command_checker,
        mqtt_adapter=mqtt_adapter,
    )
    es.mqtt.client.disable_logger()
    return es
