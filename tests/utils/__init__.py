import os as _os


from pydantic import FilePath

from tests.utils._mqtt_broker_test import MQTTBrokerTest
from tests.utils._threads import ExternalServerThreadExecutor
from external_server import ExternalServer
from external_server.config import Config as Config, ModuleConfig


EXAMPLE_MODULE_SO_LIB_PATH: FilePath = \
    FilePath(_os.path.abspath("tests/utils/example_module/_build/libexample-external-server-sharedd.so"))


ES_CONFIG_WITHOUT_MODULES = {
    "company_name": "ba",
    "car_name": "car1",
    "mqtt_address": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_timeout": 4,
    "timeout": 4,
    "send_invalid_command": False,
    "sleep_duration_after_connection_refused": 2,
    "log_files_directory": ".",
    "log_files_to_keep": 5,
    "log_file_max_size_bytes": 100000,
}


def get_test_server() -> ExternalServer:
    module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
    config = Config(modules={"1000": module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
    return ExternalServer(config=config)
