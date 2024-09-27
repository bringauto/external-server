from typing import Callable


from external_server.adapters.api.adapter import APIClientAdapter as _ApiAdapter
from external_server.server_module.command_waiting_thread import (
    CommandWaitingThread as _CommandWaitingThread,
)
from external_server.config import ModuleConfig as _ModuleConfig
from external_server.models.events import EventQueue as _EventQueue
from InternalProtocol_pb2 import Device as _Device  # type: ignore
from external_server.logs import CarLogger as _CarLogger, LOGGER_NAME


logger = _CarLogger(LOGGER_NAME)


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
        event_queue: _EventQueue,
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

        except FileNotFoundError as e:
            msg = f"Module {module_id}: Library file not found. Check the configuration file. {e}"
            logger.error(msg, car)
            raise RuntimeError(msg) from e

        except Exception as e:
            msg = f"Module {module_id}: Error in init function. Check the configuration file. {e}"
            logger.error(msg, car)
            raise RuntimeError(msg) from e

        real_mod_number = self._api_adapter.get_module_number()
        if real_mod_number != module_id:
            msg = f"Module number '{real_mod_number}' returned from API does not match module ID{module_id} in config."
            logger.error(msg, car)
            raise RuntimeError(msg)
        self._thread = _CommandWaitingThread(
            self._api_adapter, connection_check, event_queue=event_queue
        )

    @property
    def api(self) -> _ApiAdapter:
        """Returns the API client adapter used by the ServerModule."""
        return self._api_adapter

    @property
    def car(self) -> str:
        return self._api_adapter.car

    @property
    def company(self) -> str:
        return self._api_adapter.company

    @property
    def id(self) -> int:
        """Return ID of the corresponding car module."""
        return self._id

    @property
    def thread(self) -> _CommandWaitingThread:
        """Returns the command waiting thread used by the ServerModule."""
        return self._thread

    def is_device_supported(self, device: _Device) -> bool:
        """Return `True` if the device is supported by the module, `False` otherwise."""
        return self._api_adapter.is_device_type_supported(device.deviceType)
