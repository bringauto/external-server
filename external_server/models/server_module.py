import logging.config
import json

from external_server.adapters.api_client import ExternalServerApiClient as _ApiClient
from external_server.command_waiting_thread import CommandWaitingThread as _CommandWaitingThread
from external_server.config import ModuleConfig as _ModuleConfig
from InternalProtocol_pb2 import Device as _Device  # type: ignore


_logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


class ServerModule:

    def __init__(self, module_id: int, company: str, car: str, config: _ModuleConfig) -> None:
        self._id = module_id
        self._api_client = _ApiClient(module_config=config, company_name=company, car_name=car)
        self._api_client.init()
        if not self._api_client.device_initialized():
            _logger.error(
                f"Module {module_id}: Error occurred in init function. Check the configuration file."
            )
            raise RuntimeError(
                f"Module {module_id}: Error occurred in init function. Check the configuration file."
            )
        real_mod_number = self._api_client.get_module_number()
        if real_mod_number != module_id:
            msg = f"Module number '{real_mod_number}' returned from API does not match module number {module_id} in config."
            _logger.error(msg)
            raise RuntimeError(msg)
        self._thread = _CommandWaitingThread(api_client=self._api_client)

    @property
    def api_client(self) -> _ApiClient:
        return self._api_client

    @property
    def car(self) -> str:
        return self._api_client._config.get("car_name", "")

    @property
    def company(self) -> str:
        return self._api_client._config.get("company_name", "")

    @property
    def id(self) -> int:
        return self._id

    @property
    def thread(self) -> _CommandWaitingThread:
        return self._thread

    def warn_if_device_unsupported(self, device: _Device) -> None:
        if not self._api_client.is_device_type_supported(device.deviceType):
            module_id = device.module
            _logger.warning(
                f"Device of type '{device.deviceType}' is not supported by module with ID={module_id}"
                "and probably will not work properly."
            )
