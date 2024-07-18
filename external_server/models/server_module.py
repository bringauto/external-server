from external_server.adapters.api_client import ExternalServerApiClient as _ApiClient
from external_server.command_waiting_thread import CommandWaitingThread as _CommandWaitingThread
from external_server.config import ModuleConfig as _ModuleConfig


class ServerModule:

    def __init__(self, company: str, car: str, config: _ModuleConfig) -> None:
        self._api_client = _ApiClient(module_config=config, company_name=company, car_name=car)
        self._api_client.init()
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
    def thread(self) -> _CommandWaitingThread:
        return self._thread