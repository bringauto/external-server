import logging.config
import json
from typing import Callable

from external_server.adapters.api_adapter import APIClientAdapter as _ApiAdapter
from external_server.server_module.command_waiting_thread import CommandWaitingThread as _CommandWaitingThread
from external_server.config import ModuleConfig as _ModuleConfig
from InternalProtocol_pb2 import Device as _Device  # type: ignore


_logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


class ServerModule:
    """This class represents an API client used by the External Server to communicate with the cloud.

    Each instance corresponds a single car module on a given the car.
    """

    def __init__(
        self,
        module_id: int,
        company: str,
        car: str,
        config: _ModuleConfig,
        connection_check: Callable[[], bool],
    ) -> None:
        """Initializes the ServerModule instance.

        `module_id` is the number of the module on the car.
        `company` and `car` are the names of the company and the car, respectively.
        `config` is the pydantic model of the module configuration, that contains the path to the module library.
        `connection_check` is a callback function used by the server module to check at least one device
        is communicating with the external server.
        """

        self._id = module_id
        self._api_adapter = _ApiAdapter(config=config, company=company, car=car)
        try:
            self._api_adapter.init()
        except:
            msg = f"Module {module_id}: Error in init function. Check the configuration file."
            _logger.error(msg)
            raise RuntimeError(msg)
        real_mod_number = self._api_adapter.get_module_number()
        if real_mod_number != module_id:
            msg = f"Module number '{real_mod_number}' returned from API does not match module ID{module_id} in config."
            _logger.error(msg)
            raise RuntimeError(msg)
        self._thread = _CommandWaitingThread(self._api_adapter, connection_check)

    @property
    def api_adapter(self) -> _ApiAdapter:
        """Returns the API client adapter used by the ServerModule."""
        return self._api_adapter

    @property
    def car(self) -> str:
        return self._api_adapter._config.get("car_name", "")

    @property
    def company(self) -> str:
        return self._api_adapter._config.get("company_name", "")

    @property
    def id(self) -> int:
        """Return ID of the corresponding car module."""
        return self._id

    @property
    def thread(self) -> _CommandWaitingThread:
        """Returns the command waiting thread used by the ServerModule."""
        return self._thread

    def warn_if_device_unsupported(self, device: _Device) -> None:
        """Logs a warning if the device is not supported by the module."""
        if not self._api_adapter.is_device_type_supported(device.deviceType):
            module_id = device.module
            _logger.warning(
                f"Device of type '{device.deviceType}' is not supported by module with ID={module_id}"
                "and probably will not work properly."
            )