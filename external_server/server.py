from __future__ import annotations
from functools import partial
import sys
import enum
from typing import Any, Type
import time
import threading

sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import (  # type: ignore
    CommandResponse as _CommandResponse,
    Connect as _Connect,
    ConnectResponse as _ConnectResponse,
    ExternalClient as _ExternalClientMsg,
    Status as _Status,
)
from InternalProtocol_pb2 import Device as _Device  # type: ignore
from external_server.logs import CarLogger as _CarLogger, ESLogger as _ESLogger
from external_server.checkers import PublishedCommandChecker, StatusChecker
from external_server.models.exceptions import (  # type: ignore
    ConnectSequenceFailure,
    CommunicationException,
    StatusTimeout,
    NoPublishedMessage,
    CommandResponseTimeout,
    SessionTimeout,
    UnexpectedMQTTDisconnect,
)
from external_server.models.messages import (
    connect_response as _connect_response,
    status_response as _status_response,
)
from external_server.adapters.mqtt.adapter import MQTTClientAdapter
from external_server.config import CarConfig as CarConfig, ServerConfig as ServerConfig
from external_server.models.structures import (
    GeneralErrorCode,
    DisconnectTypes,
    TimeoutType,
)
from external_server.models.devices import DevicePy, KnownDevices, device_repr
from external_server.models.events import (
    EventType,
    Event as _Event,
    EventQueue as _EventQueue,
)
from external_server.server_module.server_module import ServerModule as _ServerModule
from external_server.models.structures import HandledCommand as _HandledCommand


eslogger = _ESLogger(__name__)
carlogger = _CarLogger(__name__)


class ServerState(enum.Enum):
    UNINITIALIZED = enum.auto()
    CONNECTED = enum.auto()
    INITIALIZED = enum.auto()
    RUNNING = enum.auto()
    STOPPED = enum.auto()
    ERROR = enum.auto()


DeviceStatusName = {
    _Status.CONNECTING: "CONNECTING",
    _Status.RUNNING: "RUNNING",
    _Status.DISCONNECT: "DISCONNECT",
    _Status.ERROR: "ERROR",
    _Status.RUNNING: "RUNNING",
}


StateTransitionTable: dict[ServerState, set[ServerState]] = {
    ServerState.UNINITIALIZED: {
        ServerState.ERROR,
        ServerState.STOPPED,
        ServerState.CONNECTED,
    },
    ServerState.CONNECTED: {
        ServerState.ERROR,
        ServerState.STOPPED,
        ServerState.INITIALIZED,
    },
    ServerState.INITIALIZED: {
        ServerState.ERROR,
        ServerState.STOPPED,
        ServerState.RUNNING,
    },
    ServerState.RUNNING: {
        ServerState.ERROR,
        ServerState.STOPPED,
    },
    ServerState.STOPPED: {
        ServerState.UNINITIALIZED,
    },
    ServerState.ERROR: {
        ServerState.UNINITIALIZED,
    },
}


ExternalClientMessage = _Connect | _Status | _CommandResponse


class ExternalServer:

    def __init__(self, config: ServerConfig) -> None:
        self._car_servers: dict[str, CarServer] = {}
        for car_name in config.cars:
            self._car_servers[car_name] = CarServer(CarConfig.from_server_config(car_name, config))
        self._company = config.company_name

    @property
    def company(self) -> str:
        return self._company

    def car_servers(self) -> dict[str, CarServer]:
        return self._car_servers.copy()

    def start(self) -> None:
        threads: dict[str, threading.Thread] = {}
        for car in self._car_servers:
            threads[car] = threading.Thread(target=self._car_servers[car].start)
        for t in threads.values():
            t.start()

    def stop(self, reason: str = "") -> None:
        for e in self.car_servers().values():
            e.stop(reason)

    def tls_set(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        for car_server in self._car_servers.values():
            car_server.tls_set(ca_certs, certfile, keyfile)


class CarServer:

    def __init__(self, config: CarConfig) -> None:
        self._running = False
        self._config = config
        self._car = config.car_name
        self._state: ServerState = ServerState.UNINITIALIZED
        self._event_queue = _EventQueue(self._car)
        self._known_devices = KnownDevices()
        self._mqtt = self.mqtt_adapter_from_config(config, self._event_queue)
        self._status_checker = StatusChecker(self._config.timeout, self._event_queue, self._car)
        self._command_checker = PublishedCommandChecker(
            self._config.timeout, self._event_queue, self._car
        )
        self._modules = self._initialized_modules(config)

    @property
    def sleep_time_before_next_attempt_to_connect(self) -> float:
        """Sleep time before next attempt to connect to the MQTT broker in seconds."""
        return self._config.sleep_duration_after_connection_refused

    @property
    def mqtt(self) -> MQTTClientAdapter:
        """Return the MQTT client adapter."""
        return self._mqtt

    @property
    def modules(self) -> dict[int, _ServerModule]:
        """Return a copy of the dictionary of server modules."""
        return self._modules.copy()

    @property
    def session_id(self) -> str:
        """Return an ID of the current session."""
        return self._mqtt.session.id

    @property
    def state(self) -> ServerState:
        """Return the state of the server."""
        return self._state

    def _set_running_flag(self, running: bool) -> None:
        """Set the running flag to `running`."""
        if self._running == running:
            carlogger.debug(f"Running flag is already set to {running}.", self._car)
        else:
            carlogger.debug(f"Setting running flag to {running}.", self._car)
            self._running = running

    def _get_and_handle_connect_message(self) -> None:
        """Wait for a connect message. If there is none, raise an exception."""
        msg = self._mqtt.get_connect_message()
        if not isinstance(msg, _Connect):
            raise ConnectSequenceFailure("Connect message has not been received")
        elif not msg.devices:
            raise ConnectSequenceFailure("Connect message does not contain any devices.")
        else:
            self._handle_init_connect(msg)

    def _handle_init_connect(self, msg: _Connect) -> None:
        self._mqtt.session.set_id(msg.sessionId)
        devices = list(msg.devices)
        for device in devices:
            self._connect_device_if_supported(device)
        self._publish_connect_response(_ConnectResponse.OK)

    def _get_all_first_statuses_and_respond(self) -> None:
        """Wait for first status from each of all known devices and send status response.

        The order of the statuses is expected to match the order of the devices in the
        connect message.
        """
        k = 0
        n = self._known_devices.n_all
        self._status_checker.allow_counter_reset()
        ok_statuses: list[_Status] = []
        while k < n:
            # after the loop is finished, all supported devices received status response
            # and are expected to accept a first command
            carlogger.info(f"Waiting for status message {k + 1} of {n}.", self._car)
            status_obj = self._mqtt.get_status()
            if status_obj is None:
                if not self._running:
                    return
                raise ConnectSequenceFailure("First status from device has not been received.")
            status, device = status_obj.deviceStatus, status_obj.deviceStatus.device
            module = self._modules[device.module]
            if not module.is_device_supported(device):
                self.warn_device_not_supported_by_module(module, device, self._car)
            elif status_obj.sessionId != self._mqtt.session.id:
                carlogger.warning("Received status with different session ID. Skipping.", self._car)
            else:
                self.check_device_is_in_connecting_state(status_obj, self._car)
                status, device = status_obj.deviceStatus, status_obj.deviceStatus.device
                self._log_new_status(status_obj)
                if self._known_devices.is_connected(device):
                    k += 1
                elif self._known_devices.is_not_connected(device):
                    carlogger.warning(
                        f"Status from not connected device {device_repr(device)}.", self._car
                    )
                self._publish_status_response(status_obj)
                ok_statuses.append(status_obj)

        for status in ok_statuses:
            module = self._modules[status.deviceStatus.device.module]
            module.api.forward_status(status)

    def _send_first_commands_and_get_responses(self) -> None:
        """Send first command to each of all known connected and not connected devices.
        Raise exception if any command response is not received.
        """
        if self._running:
            self._get_and_send_first_commands()
            self._get_first_commands_responses()

    def start(self) -> None:
        """Starts the external server.

        This includes:
        - starting thread waiting for commands for each of the supported modules,
        - starting the MQTT connection.
        """

        carlogger.debug(f"Starting the external server for car {self._config.car_name}.", self._car)
        self._start_module_threads()
        self._start_communication_loop()

    def stop(self, reason: str = "") -> None:
        """Stop the external server communication, stop the MQTT client event loop,
        clear the modules.
        """
        msg = f"Stopping the external server part for car {self._config.car_name} of company {self._config.company_name}."
        self._set_state(ServerState.STOPPED)
        if reason:
            msg += f" Reason: {reason}"
        carlogger.info(msg, self._car)
        self._set_running_flag(False)
        self._clear_context()
        self._clear_modules()

    def tls_set(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        "Set tls security to MQTT client"
        self._mqtt.tls_set(ca_certs, certfile, keyfile)

    def _add_connected_devices(self, *device: _Device) -> None:
        """Store the device as connected for further handling of received messages and messages to be sent to it."""
        for d in device:
            assert isinstance(d, _Device)
        for d in device:
            self._known_devices.connected(DevicePy.from_device(d))

    def _add_not_connected_device(self, device: _Device) -> None:
        """Store the device as not connected for further handling of received messages and messages to be sent to it."""
        self._known_devices.not_connected(DevicePy.from_device(device))

    def _car_message_from_mqtt(self) -> _ExternalClientMsg:
        """Get the next message from the MQTT broker.

        Raise exception if there is no message or the message is not a valid `ExternalClient` message.
        """
        message = self._mqtt._get_message()
        if message is None:
            raise NoPublishedMessage("Expected message from car, but did not received any.")
        return message

    def _check_and_handle_available_commands(self, module_id: Any) -> None:
        """Check if there are any commands available for the module and process them."""
        if not isinstance(module_id, int):
            raise ValueError(f"Invalid module ID: {module_id}.")
        while (cmd := self._get_api_command(module_id)) is not None:
            data, device = cmd
            self._handle_command(module_id, data, device)

    def _check_at_least_one_device_is_connected(self) -> None:
        """Raise an exception if all devices have been disconnected."""
        if self._known_devices.n_connected == 0:
            msg = "All devices have been disconnected, restarting server."
            carlogger.warning(msg, self._car)
            raise CommunicationException(msg)

    def _check_received_status(self, status: _Status) -> None:
        """Reset session timeout checker and pass the status to the status checker."""
        self._reset_session_checker()
        self._status_checker.check(status)

    def _clear_context(self) -> None:
        """Stop and destroy communication with both the API and the MQTT broker.

        Stop and destroy all timers and threads, clear the known devices list and queues.
        """
        self._mqtt.disconnect()
        self._mqtt.session.stop()

        self._command_checker.reset()
        self._status_checker.reset()

        for device in self._known_devices.list_connected():
            module_adapter = self._modules[device.module_id].api
            module_adapter.device_disconnected(DisconnectTypes.timeout, device.to_device())

        self._known_devices.clear()
        self._event_queue.clear()

    def _clear_modules(self) -> None:
        """Stop the threads for each server module and destroy the API adapters."""
        for module in self._modules.values():
            module.thread.stop()
        for module in self._modules.values():
            module.thread.wait_for_join()
            code = module.api.destroy()
            if not code == GeneralErrorCode.OK:
                carlogger.error(
                    f"Module {module.id}: Error in destroy function. Code: {code}", self._car
                )
        self._modules.clear()

    def _collect_first_commands_for_init_sequence(self) -> list[_HandledCommand]:
        """Collect all first commands for the init sequence."""
        commands: list[_HandledCommand] = list()
        devices_expecting_cmd: list[_Device] = [
            d.to_device() for d in self._known_devices.list_connected()
        ]
        devices_received_cmd: list[_Device] = list()
        for module in self._modules:
            for cmd in self._get_module_commands(module):
                data, device = cmd[0], cmd[1]
                drepr = device_repr(device)
                if device in devices_expecting_cmd:
                    commands.append(_HandledCommand(data, device=device, from_api=True))
                    devices_expecting_cmd.remove(device)
                    devices_received_cmd.append(device)
                elif device in devices_received_cmd:
                    carlogger.warning(
                        f"Multiple commands for '{drepr}'. Only the first is accepted.", self._car
                    )
                else:  # device could not be in the list of connected devices
                    carlogger.warning(
                        f"Device {drepr} is not connected. Command retrieved from API will be ignored.",
                        self._car,
                    )
        for device in devices_expecting_cmd:
            commands.append(_HandledCommand(b"", device=device, from_api=False))
            carlogger.info(
                f"No command received for device {device_repr(device)}. Creating empty command.",
                self._car,
            )
        for device_py in self._known_devices.list_not_connected():
            commands.append(_HandledCommand(b"", device=device_py.to_device(), from_api=False))
            carlogger.info(
                f"Device {device_repr(device_py)} is not connected. No command is being sent.",
                self._car,
            )
        return commands

    def _connect_device(self, device: _Device) -> bool:
        """Connect the device if it is not already connected.

        No action is taken if the device is already connected.
        """
        drepr = device_repr(device)
        carlogger.info(f"Connecting device {drepr}.", self._car)
        if self._known_devices.is_connected(device):
            carlogger.info(f"Device {drepr} is already connected.", self._car)
        else:
            code = self._modules[device.module].api.device_connected(device)
            if code == GeneralErrorCode.OK:
                self._add_connected_devices(device)
                carlogger.info(f"Device {drepr} has been connected.", self._car)
                return True
            carlogger.error(f"Device {drepr} could not connect. Response code: {code}", self._car)
        return False

    def _connect_device_if_supported(self, device: _Device) -> None:
        """Connect the device if it is supported by a supported module."""
        module = self._modules.get(device.module, None)
        if module:
            if module.is_device_supported(device):
                self._connect_device(device)
            else:
                self.warn_device_not_supported_by_module(
                    module, device, "Device will not be connected to the server."
                )
        else:
            carlogger.warning(
                f"Ignoring device {device_repr(device)} from unsupported module.", self._car
            )

    def _disconnect_device(self, disconnect_types: DisconnectTypes, device: _Device) -> bool:
        """Disconnect a connected device and return `True` if successful. In other cases, return `False`.

        If the device has already not been connected, log an error.
        """
        drepr = device_repr(device)
        carlogger.info(f"Disconnecting device {drepr}.", self._car)
        if not self._known_devices.is_connected(device):
            carlogger.info(f"Device {drepr} is already disconnected.", self._car)
        else:
            carlogger.info(f"Device {drepr} has been disconnected.", self._car)
            self._known_devices.remove(DevicePy.from_device(device))
            code = self._modules[device.module].api.device_disconnected(disconnect_types, device)
            if code == GeneralErrorCode.OK:
                return True
        return False

    def _ensure_connection_to_broker(self) -> None:
        """Connect the MQTT client to the MQTT broker.

        Raise exception if the connection fails.
        """
        carlogger.info("Connecting to MQTT broker.", self._car)
        e = self._mqtt.connect()
        if e is not None:
            raise ConnectionRefusedError(e)
        self._set_state(ServerState.CONNECTED)

    def _get_and_send_first_commands(self) -> None:
        """Send command to all connected devices and check responses are returned."""
        if self._known_devices.n_connected == 0:
            raise ConnectSequenceFailure("No connected device.")
        commands = self._collect_first_commands_for_init_sequence()
        for cmd in commands:
            try:
                self._command_checker.add(cmd)
                carlogger.debug(f"Sending command to {device_repr(cmd.device)}", self._car)
                ext_cmd = cmd.external_command(self._mqtt.session.id)
                self._mqtt.publish(ext_cmd, f"Sending command (counter={cmd.counter}).")
            except Exception as e:
                carlogger.error(f"Error in sending command: {e}", self._car)

    def _get_first_commands_responses(self) -> None:
        n_devices = self._known_devices.n_all
        carlogger.info(
            f"Expecting responses to {n_devices} command{'s' if n_devices>1 else ''}.", self._car
        )
        for iter in range(n_devices):
            carlogger.info(f"Waiting for command response {iter + 1} of {n_devices}.", self._car)
            response = self._get_next_valid_command_response()
            commands = self._command_checker.pop(response)
            for cmd in commands:
                if self._known_devices.is_connected(cmd.device) and cmd.from_api:
                    self._modules[cmd.device.module].api.command_ack(cmd.data, cmd.device)

    def _get_module_commands(self, module_id: int) -> list[tuple[bytes, _Device]]:
        """Get all commands for the module from the module's command waiting thread."""
        commands: list[tuple[bytes, _Device]] = []
        while (result := self._modules[module_id].thread.pop_command()) is not None:
            cmd_bytes, device = result
            commands.append((cmd_bytes, device))
        return commands

    def _get_next_valid_command_response(self) -> _CommandResponse:
        """Get the next command response from the MQTT broker. Throw away all other messages.

        Raise an exception there is not command response.
        """
        while (response := self._mqtt._get_message()) is not None:
            if isinstance(response, _ExternalClientMsg) and response.HasField("commandResponse"):
                if response.commandResponse.sessionId == self._mqtt.session.id:
                    carlogger.info(f"Received a command response.", self._car)
                    return response.commandResponse
                else:
                    carlogger.error(
                        "Skipping command response with different session ID.", self._car
                    )
            else:
                # ignore other messages
                carlogger.warning(
                    f"Expected command response, received other type of external client message. Skipping",
                    self._car,
                )
        # response is None
        raise ConnectSequenceFailure("Command response has not been received.")

    def _handle_connect(self, connect_msg: _Connect) -> None:
        """Handle connect message received during normal communication, i.e., after init sequence."""
        if connect_msg.sessionId == self._mqtt.session.id:
            carlogger.error(
                "Received connect message with ID of already existing session.", self._car
            )
            self._publish_connect_response(_ConnectResponse.ALREADY_LOGGED)
        else:
            carlogger.error(
                "Received connect message with session ID not matching current session ID.",
                self._car,
            )

    def _handle_status(self, received_status: _Status) -> None:
        """Handle the status received during normal communication, i.e., after init sequence.

        If the status is valid and comes with expected counter value, handle all stored received statuses.
        """
        self._check_received_status(received_status)
        self._log_new_status(received_status)
        while status := self._status_checker.get():
            self._handle_checked_status(status)
        self._check_at_least_one_device_is_connected()

    def _handle_checked_status(self, status: _Status) -> None:
        """Handle the status that has been checked by the status checker."""
        module_and_dev = self._module_and_device(status)
        if not module_and_dev:
            carlogger.info(f"Received status from unsupported device. Ignoring status.", self._car)
        else:
            module, device = module_and_dev
            status_ok = True
            carlogger.info(f"Received status from {device_repr(device)}", self._car)
            match status.deviceState:
                case _Status.CONNECTING:
                    status_ok = self._connect_device(device)
                case _Status.RUNNING:
                    if not self._known_devices.is_connected(device):
                        carlogger.warning(f"Device is not connected. Ignoring status.", self._car)
                        status_ok = False
                case _Status.DISCONNECT:
                    status_ok = self._disconnect_device(DisconnectTypes.announced, device)
                case _:  # unhandled state
                    carlogger.warning(
                        f"Unknown device state: {status.deviceState}. Ignoring status.", self._car
                    )
            if status_ok:
                module.api.forward_status(status)
                self._publish_status_response(status)

    def _handle_command(self, module_id: int, data: bytes, device: _Device) -> None:
        """Handle the command received from API during normal communication (after init sequence)."""
        if device.module == module_id:
            self._publish_command(data, device)
        else:
            carlogger.warning(
                f"Module ID {module_id} stored by API does not match module ID in Device ID {device_repr(device)} carried by the command.",
                self._car,
            )
            if self._config.send_invalid_command:
                self._publish_command(data, device)
            else:
                carlogger.warning(
                    f"Command to device {device_repr(device)} with module ID mismatch will not be sent.",
                    self._car,
                )

    def _get_api_command(self, module_id: int) -> tuple[bytes, _Device] | None:
        """Pop the next command from the module's command waiting thread."""
        return self._modules[module_id].thread.pop_command()

    def _handle_command_response(self, cmd_response: _CommandResponse) -> None:
        """Handle the command response received during normal communication, i.e., after init sequence."""
        carlogger.info(
            f"Received command response (counter = {cmd_response.messageCounter}).", self._car
        )

        if cmd_response.type == _CommandResponse.DEVICE_NOT_CONNECTED:
            self._handle_command_response_with_disconnected_type(cmd_response)

        commands = self._command_checker.pop(cmd_response)
        for command in commands:
            module = self._modules[command.device.module]
            module.api.command_ack(command.data, command.device)

    def _handle_command_response_with_disconnected_type(
        self, cmd_response: _CommandResponse
    ) -> None:
        device = self._command_checker.command_device(cmd_response.messageCounter)
        if device:
            self._disconnect_device(DisconnectTypes.announced, device)
            carlogger.warning(f"Device {device_repr(device)} disconnected.", self._car)

    def _handle_communication_event(self, event: _Event) -> None:
        """Match the event type and handle it accordingly.

        Raise exception if connection to MQTT BROKER is lost or if expected command response
        or status is not received.
        """
        match event.event_type:
            case EventType.CAR_MESSAGE_AVAILABLE:
                self._handle_car_message()
            case EventType.COMMAND_AVAILABLE:
                self._check_and_handle_available_commands(event.data)
            case EventType.MQTT_BROKER_DISCONNECTED:
                raise UnexpectedMQTTDisconnect("Unexpected disconnection of MQTT client.")
            case EventType.TIMEOUT_OCCURRED:
                self._handle_timeout_event(event.data)
            case _:
                carlogger.warning("Uknown event during normal communication. Ignoring.")

    def _handle_timeout_event(self, timeout_type: Any) -> None:
        """Handle the timeout event and put it in the event queue."""
        if not isinstance(timeout_type, TimeoutType):
            raise CommunicationException("Timeout event occured, but without type.")
        match timeout_type:
            case TimeoutType.SESSION_TIMEOUT:
                raise SessionTimeout("MQTT Session timeout occurred. No message received in time.")
            case TimeoutType.STATUS_TIMEOUT:
                raise StatusTimeout("Some skipped statuses were not received in time.")
            case TimeoutType.COMMAND_RESPONSE_TIMEOUT:
                raise CommandResponseTimeout("Some command responses were not received in time.")
            case _:
                raise CommunicationException(f"Timeout event with unknown type: {timeout_type}.")

    def _handle_car_message(self) -> None:
        """Handle the message received from the MQTT broker during normal communication."""
        message = self._car_message_from_mqtt()
        if message.HasField("connect"):
            # This message is not expected outside of a init sequence
            self._handle_connect(message.connect)
        elif message.HasField("status"):
            if self._mqtt.session.id == message.status.sessionId:
                self._reset_session_checker()
                self._handle_status(message.status)
            else:
                carlogger.warning("Ignoring status with different session ID.", self._car)
        elif message.HasField("commandResponse"):
            if self._mqtt.session.id == message.commandResponse.sessionId:
                self._reset_session_checker()
                self._handle_command_response(message.commandResponse)
            else:
                carlogger.warning(
                    "Ignoring command response with session ID not matching"
                    "the current session ID.",
                    self._car,
                )

    def _init_sequence(self) -> None:
        """Runs initial sequence before starting normal communication over MQTT.

        This includes
        - receiving (single) connect message and sending reponse,
        - receiving first status for every device listed in the connect message IN ORDER
        of the devices in the connect message and sending responses to each one,
        - sending first command to every device listed in the connect message IN ORDER
        of the devices in the connect message and receiving responses to each one.
        """
        if self.state == ServerState.STOPPED:
            carlogger.info(
                "Server has been stopped. Connect sequence will not be started.", self._car
            )
            return
        carlogger.info("Starting the connect sequence.", self._car)
        try:
            if not self.state == ServerState.CONNECTED:
                raise ConnectSequenceFailure(
                    "Cannot start connect sequence without connection to MQTT broker."
                )
            self._get_and_handle_connect_message()
            self._get_all_first_statuses_and_respond()
            self._send_first_commands_and_get_responses()

            self._set_state(ServerState.INITIALIZED)
            if self._state == ServerState.INITIALIZED:
                carlogger.info("Connect sequence has finished succesfully.", self._car)
            self._event_queue.clear()
        except Exception as e:
            msg = f"Connection sequence has failed. {e}"
            raise ConnectSequenceFailure(msg)

    def _initialized_modules(self, server_config: CarConfig) -> dict[int, _ServerModule]:
        """Return dictionary of ServerModule instances created.

        Each instance corresponds to a module defined in the server configuration.
        """
        modules: dict[int, _ServerModule] = dict()
        for id_str, module_config in server_config.modules.items():
            module_id = int(id_str)
            car, company = server_config.car_name, server_config.company_name
            connection_check = partial(self._known_devices.any_connected_device, module_id)
            modules[module_id] = _ServerModule(
                module_id,
                company,
                car,
                module_config,
                connection_check,
                event_queue=self._event_queue,
            )
        return modules

    def _log_new_status(self, status: _Status) -> None:
        info = f"Received status, counter={status.messageCounter}."
        carlogger.info(info, self._car)

    def _log_and_set_error_and_raise(self, exception: Exception, car_name: str = "") -> None:
        """Log the exception and raise it. Set the server's state to ERROR."""
        carlogger.log_on_exception(exception, car_name)
        self._set_state(ServerState.ERROR)
        raise exception

    def _module_and_device(self, message: _Status) -> tuple[_ServerModule, _Device] | None:
        """Return server module and device referenced by the status messages.

        Return None if the module or device is unknown or unsupported.
        """
        device = message.deviceStatus.device
        module = self._modules.get(device.module, None)
        if not module:
            carlogger.warning(f"Unknown module (ID={device.module}).", self._car)
            return None
        elif not module.api.is_device_type_supported(device.deviceType):
            self.warn_device_not_supported_by_module(module, device, self._car)
            return None
        return module, device

    def _publish_command(self, data: bytes, device: _Device) -> None:
        """Publish the external command to the MQTT broker on publish topic."""

        if not self._known_devices.is_connected(device):
            carlogger.warning(
                f"Sending command to a not connected device ({device_repr(device)}).", self._car
            )
        if not data:
            carlogger.warning(
                f"Data of command for device {device_repr(device)} is empty.", self._car
            )

        handled_cmd = _HandledCommand(data=data, device=device, from_api=True)
        self._command_checker.add(handled_cmd)
        # the following has to be called before publishing in order to assign counter to the command
        self._mqtt.publish(handled_cmd.external_command(self.session_id))
        carlogger.info(f"Sending command, counter = {handled_cmd.counter}", self._car)

    def _publish_connect_response(self, response_type: int) -> None:
        """Publish the connect response message to the MQTT broker on publish topic."""
        msg = _connect_response(self._mqtt.session.id, response_type)
        carlogger.info(f"Sending connect response of type {response_type}", self._car)
        self._mqtt.publish(msg)

    def _publish_status_response(self, status: _Status) -> None:
        """Publish the status response message to the MQTT broker on publish topic."""
        if status.sessionId != self._mqtt.session.id:
            carlogger.warning(
                "Status session ID does not match current session ID of the server. Status response"
                f" to the device {device_repr(status.deviceStatus.device)} will not be sent.",
                self._car,
            )
        else:
            status_response = _status_response(self._mqtt.session.id, status.messageCounter)
            carlogger.info(
                f"Sending status response of type {status_response.statusResponse.type}", self._car
            )
            self._mqtt.publish(status_response)

    def _reset_session_checker(self) -> None:
        """Reset the session checker's timer."""
        carlogger.debug("Resetting MQTT session checker timer.", self._car)
        self._mqtt.session.reset_timer()

    def _run_initial_sequence(self) -> None:
        """Ensure connection to MQTT broker and run the initial sequence.

        Raise an exception if the sequence fails.
        """
        try:
            self._set_state(ServerState.UNINITIALIZED)
            self._ensure_connection_to_broker()
            if not self._running:
                self._set_running_flag(True)
            self._init_sequence()
        except Exception as e:
            self._log_and_set_error_and_raise(e)

    def _run_normal_communication(self) -> None:
        """Start the normal communication over MQTT. An init sequence must have been completed successfully."""
        if self._state == ServerState.STOPPED:
            return
        elif not self.state == ServerState.INITIALIZED:
            raise ConnectSequenceFailure("Cannot start communication after init sequence failed.")
        self._mqtt.session.start()
        if not self._running:
            self._set_running_flag(True)
        self._set_state(ServerState.RUNNING)
        while self.state != ServerState.STOPPED:
            try:
                event = self._event_queue.get()
                self._handle_communication_event(event)
            except Exception as e:
                self._log_and_set_error_and_raise(e)

    def _set_state(self, state: ServerState) -> None:
        """Set the server's state variable to the given value if the transition is allowed.

        No action is taken if the transition is not allowed.
        """
        if state in StateTransitionTable[self._state]:
            carlogger.debug(f"Changing server's state from {self._state} to {state}", self._car)
            self._state = state
        elif state != self.state:
            carlogger.debug(
                f"Cannot change server's state from {self._state} to {state}", self._car
            )
        return

    def _start_module_threads(self) -> None:
        """Start threads for polling each module's API for new commands."""
        for _id in self._modules:
            self._modules[_id].thread.start()

    def _start_communication_loop(self) -> None:
        """Start the main communication loop including the init sequence and normal communication."""
        self._set_running_flag(True)
        while self._running and self.state != ServerState.STOPPED:
            self._single_communication_run()

    def _single_communication_run(self) -> None:
        """Run the initial sequence and normal communication once."""
        try:
            self._run_initial_sequence()
            self._run_normal_communication()
        except Exception:
            time.sleep(self._config.sleep_duration_after_connection_refused)
        finally:
            self._clear_context()

    @staticmethod
    def check_device_is_in_connecting_state(status: _Status, car: str = "") -> None:
        """Check if the device state contained in the status is connecting."""
        if status.deviceState != _Status.CONNECTING:
            state = DeviceStatusName.get(status.deviceState, str(status.deviceState))
            connecting_state = DeviceStatusName[_Status.CONNECTING]
            msg = (
                f"First status from device {device_repr(status.deviceStatus.device)} "
                f"must contain {connecting_state} state, received {state}."
            )
            carlogger.error(msg, car)
            raise ConnectSequenceFailure(msg)

    @staticmethod
    def mqtt_adapter_from_config(config: CarConfig, event_queue: _EventQueue) -> MQTTClientAdapter:
        return MQTTClientAdapter(
            config.company_name,
            config.car_name,
            config.timeout,
            config.mqtt_address,
            config.mqtt_port,
            event_queue,
            config.mqtt_timeout,
        )

    @staticmethod
    def warn_device_not_supported_by_module(
        module: _ServerModule, device: _Device, car: str, msg: str = ""
    ) -> None:
        carlogger.warning(
            f"Device of type `{device.deviceType}` is not supported by module '{module.id}'. {msg}",
            car,
        )
