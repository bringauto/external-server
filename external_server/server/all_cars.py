from __future__ import annotations
import sys
import threading

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import (  # type: ignore
    CommandResponse as _CommandResponse,
    Connect as _Connect,
    Status as _Status,
)
from external_server.logs import ESLogger as _ESLogger, LOGGER_NAME as _LOGGER_NAME
from external_server.checkers.command_checker import (
    PublishedCommandChecker as _PublishedCommandChecker,
)
from external_server.checkers.status_checker import StatusChecker as _StatusChecker
from external_server.adapters.mqtt.adapter import MQTTClientAdapter as _MQTTClientAdapter
from external_server.config import CarConfig as _CarConfig, ServerConfig as _ServerConfig
from external_server.models.events import EventType as _EventType, EventQueue as _EventQueue
from external_server.server.single_car import CarServer


logger = _ESLogger(_LOGGER_NAME)
ExternalClientMessage = _Connect | _Status | _CommandResponse


class ExternalServer:
    """This class is the implementation of the external server.

    It maintains instances of the CarServer class for each car defined in the configuration.
    """

    def __init__(self, config: _ServerConfig) -> None:
        self._car_servers: dict[str, CarServer] = {}
        self._car_threads: dict[str, threading.Thread] = dict()
        self._company = config.company_name
        for car_name in config.cars:
            event_queue = _EventQueue(car_name)
            status_checker = _StatusChecker(config.timeout, event_queue, car_name)
            command_checker = _PublishedCommandChecker(config.timeout, event_queue, car_name)
            mqtt_adapter = _MQTTClientAdapter(
                broker_host=config.mqtt_address,
                port=config.mqtt_port,
                timeout=config.timeout,
                mqtt_timeout=config.mqtt_timeout,
                car=car_name,
                company=self._company,
                event_queue=event_queue,
            )

            self._car_servers[car_name] = CarServer(
                config=_CarConfig.from_server_config(car_name, config),
                event_queue=event_queue,
                status_checker=status_checker,
                command_checker=command_checker,
                mqtt_adapter=mqtt_adapter,
            )

    def car_servers(self) -> dict[str, CarServer]:
        """Return parts of the external server responsible for each car defined in configuration."""
        return self._car_servers.copy()

    def start(self, wait_for_join: bool = False) -> None:
        """Start the external server.

        For reach car defined in the configuration, create a separate thread and inside that,
        start an instance of the CarServer class.

        The 'wait_for_join' parameter is used to determine if the main thread should wait
        for all car threads to finish or just return and let the car threads run in the background.
        """
        for car in self._car_servers:
            self._car_threads[car] = threading.Thread(target=self._car_servers[car].start)
        for t in self._car_threads.values():
            t.start()
        # The following for loop ensures, that the main thread waits for all car threads to finish
        # This allows for the external server __main__ script to run while the car threads are running
        # This ensures the server can be stopped by KeyboardInterrupt
        if wait_for_join:
            for t in self._car_threads.values():
                t.join()

    def stop(self, reason: str = "") -> None:
        """Stop the external server.

        For each car defined in the configuration, stop the CarServer instance.
        """
        try:
            for car_server in self.car_servers().values():
                car_server.stop(reason)
            for car_thread in self._car_threads.values():
                if car_thread.is_alive():
                    car_thread.join()
            self._car_threads.clear()
        except Exception as e:
            logger.error(f"Error in stopping the external server (company='{self._company}'): {e}")

    def set_tls(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        """Set the TLS security to the MQTT client for each car server."""
        for car_server in self._car_servers.values():
            car_server.tls_set(ca_certs, certfile, keyfile)
