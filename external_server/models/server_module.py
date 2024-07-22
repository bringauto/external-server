import logging.config
import json
from typing import Callable

from external_server.adapters.api_adapter import APIClientAdapter as _ApiAdapter
from external_server.command_waiting_thread import CommandWaitingThread as _CommandWaitingThread
from external_server.config import ModuleConfig as _ModuleConfig
from InternalProtocol_pb2 import Device as _Device  # type: ignore


_logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


class ServerModule:

    def __init__(
        self,
        id: int,
        company: str,
        car: str,
        config: _ModuleConfig,
        connection_check: Callable[[], bool],
    ) -> None:

        self._id = id
        self._api_client = _ApiAdapter(config=config, company=company, car=car)
        self._api_client.init()
        if not self._api_client.device_initialized():
            msg = f"Module {id}: Error in init function. Check the configuration file."
            _logger.error(msg)
            raise RuntimeError(msg)
        real_mod_number = self._api_client.get_module_number()
        if real_mod_number != id:
            msg = f"Module number '{real_mod_number}' returned from API does not match module number {id} in config."
            _logger.error(msg)
            raise RuntimeError(msg)
        self._thread = _CommandWaitingThread(self._api_client, connection_check)

    @property
    def api_client(self) -> _ApiAdapter:
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
