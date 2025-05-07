from __future__ import annotations
from functools import partial
import enum
from typing import Any
import time

from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import (
    CommandResponse as _CommandResponse,
    Connect as _Connect,
    ConnectResponse as _ConnectResponse,
    ExternalClient as _ExternalClientMsg,
    Status as _Status,
)
from fleet_protocol_protobuf_files.InternalProtocol_pb2 import Device as _Device

from external_server.logs import CarLogger as _CarLogger, LOGGER_NAME as _LOGGER_NAME
from external_server.checkers.command_checker import (
    PublishedCommandChecker as _PublishedCommandChecker,
)
from external_server.checkers.status_checker import StatusChecker as _StatusChecker
from external_server.models.exceptions import (  # type: ignore
    ConnectSequenceFailure,
    CommunicationException,
    StatusTimeout,
    NoMessage,
    CommandResponseTimeout,
    SessionTimeout,
    UnexpectedMQTTDisconnect,
)
from external_server.models.messages import (
    connect_response as _connect_response,
    status_response as _status_response,
)
from external_server.adapters.mqtt.adapter import MQTTClientAdapter as _MQTTClientAdapter
from external_server.config import CarConfig as _CarConfig, ModuleConfig as _ModuleConfig
from external_server.models.structures import (
    GeneralErrorCode,
    DisconnectTypes,
    HandledCommand,
    TimeoutType,
)
from external_server.models.devices import DevicePy, KnownDevices, device_repr
from external_server.models.events import (
    EventType as _EventType,
    Event as _Event,
    EventQueue as _EventQueue,
)
from external_server.server_module.server_module import ServerModule as _ServerModule


class DeviceStatusName(enum.Enum):
    CONNECTING = _Status.CONNECTING
    RUNNING = _Status.RUNNING
    DISCONNECT = _Status.DISCONNECT
    ERROR = _Status.ERROR


class ServerState(enum.Enum):
    UNINITIALIZED = enum.auto()
    CONNECTED = enum.auto()
    INITIALIZED = enum.auto()
    RUNNING = enum.auto()
    STOPPED = enum.auto()
    ERROR = enum.auto()

    @classmethod
    def is_valid_transition(cls, current_state: ServerState, new_state: ServerState) -> bool:
        transition_table = {
            cls.UNINITIALIZED: {cls.ERROR, cls.STOPPED, cls.CONNECTED, cls.UNINITIALIZED},
            cls.CONNECTED: {cls.ERROR, cls.STOPPED, cls.INITIALIZED, cls.CONNECTED},
            cls.INITIALIZED: {cls.ERROR, cls.STOPPED, cls.RUNNING, cls.INITIALIZED},
            cls.RUNNING: {cls.ERROR, cls.STOPPED, cls.RUNNING},
            cls.STOPPED: {cls.UNINITIALIZED, cls.STOPPED},
            cls.ERROR: {cls.UNINITIALIZED, cls.ERROR},
        }
        return new_state in transition_table.get(current_state, set())


logger = _CarLogger(_LOGGER_NAME)
ExternalClientMessage = _Connect | _Status | _CommandResponse


class CarServer:

    def __init__(
        self,
        config: _CarConfig,
        event_queue: _EventQueue,
        status_checker: _StatusChecker,
        command_checker: _PublishedCommandChecker,
        mqtt_adapter: _MQTTClientAdapter,
    ) -> None:

        self._running = False
        self._config = config
        self._company = config.company_name
        self._car_name = config.car_name
        self._state: ServerState = ServerState.UNINITIALIZED
        self._event_queue = event_queue
        self._known_devices = KnownDevices()
        self._mqtt = mqtt_adapter
        self._status_checker = status_checker
        self._command_checker = command_checker
        self._modules = self._initialize_modules(config)

    @property
    def modules(self) -> dict[int, _ServerModule]:
        """Return a copy of the dictionary of server modules."""
        return self._modules.copy()

    @property
    def mqtt(self) -> _MQTTClientAdapter:
        """Return the MQTT client adapter."""
        return self._mqtt

    @property
    def session_id(self) -> str:
        """Return an ID of the current session."""
        return self._mqtt.session.id

    @property
    def sleep_time_before_next_attempt_to_connect(self) -> float:
        """Sleep time before next attempt to connect to the MQTT broker in seconds."""
        return self._config.sleep_duration_after_connection_refused

    @property
    def state(self) -> ServerState:
        """Return the state of the server."""
        return self._state

    def _set_running_flag(self, running: bool) -> None:
        """Set the running flag to `running`."""
        if self._running == running:
            logger.debug(f"Running flag is already set to {running}.", self._car_name)
        else:
            logger.debug(f"Setting running flag to {running}.", self._car_name)
            self._running = running

    def _get_and_handle_connect_message(self) -> None:
        """Wait for a connect message. If there is none, raise an exception."""
        msg = self._mqtt.get_connect_message()
        if not isinstance(msg, _Connect):
            raise ConnectSequenceFailure("Connect message has not been received.")
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
        n = self._known_devices.n_all
        self._status_checker.allow_counter_reset()
        valid_statuses: list[_Status] = []
        k = 0
        while k < n:
            # after the loop is finished, all supported devices received status response
            # and are expected to accept a first command
            logger.info(f"Waiting for status message {k + 1} of {n}.", self._car_name)
            status = self._get_status()
            if self._status_from_connected_device(status):
                self._publish_status_response(status)
                k += 1
            valid_statuses.append(status)
        self._forward_ok_statuses(valid_statuses)

    def _status_from_connected_device(self, status: _Status) -> bool:
        device = status.deviceStatus.device
        if not self._known_devices.is_connected(device):
            logger.info(
                f"Status from not connected device '{device_repr(device)}'.", self._car_name
            )
            return False
        return True

    def _publish_response_if_status_from_connected_device(self, status: _Status) -> None:
        device = status.deviceStatus.device
        if not self._known_devices.is_connected(device):
            logger.info(
                f"Status from not connected device '{device_repr(device)}'. Skipping.",
                self._car_name,
            )
        self._publish_status_response(status)

    def _get_status(self) -> _Status:
        while True:
            status_obj = self._mqtt.get_status()
            if status_obj is None:  # no status received before timeout
                raise ConnectSequenceFailure("First status from device has not been received.")
            if self._valid_status(status_obj):
                self._log_new_status(status_obj)
                return status_obj

    def _valid_status(self, status: _Status) -> bool:
        device = status.deviceStatus.device
        module = self._modules[device.module]
        if not self._modules[device.module].is_device_supported(device):
            self.warn_device_not_supported_by_module(module, device, self._car_name)
            return False
        if not self._is_valid_session_id(status.sessionId, "status"):
            return False
        self.check_device_is_in_connecting_state(status, self._car_name)
        return True

    def _forward_ok_statuses(self, statuses: list[_Status]) -> None:
        """Forward all statuses that are in the 'OK' state."""
        for status in statuses:
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
        """Starts this part of external server.

        This includes:
        - starting thread waiting for commands for each of the supported modules,
        - starting the MQTT connection.
        """
        logger.info(f"Starting the external server for car '{self._car_name}'.", self._car_name)
        self._start_module_threads()
        self._start_communication_loop()

    def stop(self, reason: str = "") -> None:
        """Stop the external server communication, stop the MQTT client event loop,
        clear the modules.
        """
        msg = f"Stopping the external server part for car {self._car_name} of company {self._company}."
        self._set_state(ServerState.STOPPED)
        self._event_queue.add(_EventType.SERVER_STOPPED)
        if reason:
            msg += f" Reason: {reason}"
        logger.info(msg, self._car_name)
        self._set_running_flag(False)
        self._clear_modules()
        self._clear_context()

    def tls_set(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        "Set tls security to MQTT client."
        self._mqtt.set_tls(ca_certs, certfile, keyfile)

    def _add_connected_devices(self, *device: _Device) -> None:
        """Store the device as connected for further handling of received messages and messages to be sent to it."""
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
            raise NoMessage("Expected message from car, but did not received any.")
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
            raise CommunicationException(msg)

    def _check_received_status(self, status: _Status) -> None:
        """Reset session timeout checker and pass the status to the status checker."""
        self._reset_session_checker()
        self._status_checker.check(status)

    def _clear_context(self) -> None:
        """Stop and destroy communication with both the API and the MQTT broker,
        all timers and threads, clear the known devices and all queues.
        """
        logger.info("Clearing the context.", self._car_name)
        self._mqtt.disconnect()
        self._mqtt.session.stop()
        self._command_checker.reset()
        self._status_checker.reset()
        for device in self._known_devices.list_connected():
            module = self._modules.get(device.module_id, None)
            if module:
                module_adapter = module.api
                module_adapter.device_disconnected(DisconnectTypes.timeout, device.to_device())
        self._known_devices.clear()
        self._event_queue.clear()

    def _clear_modules(self) -> None:
        """Stop the threads for each server module and destroy the API adapters."""
        for module in self._modules.values():
            module.thread.stop()
            code = module.api.destroy()
            if code != GeneralErrorCode.OK:
                logger.error(
                    f"Module {module.id}: Error in destroy function. Return code: {code}.",
                    self._car_name,
                )
        self._modules.clear()

    def _first_commands_for_init_sequence(self) -> list[HandledCommand]:
        """Collect all first commands for the init sequence."""
        devices_expecting_command = [
            device.to_device() for device in self._known_devices.list_connected()
        ]
        api_commands = self._collect_first_commands_from_apis()
        self._remove_commands_for_devices_not_expecting_command(
            api_commands, devices_expecting_command
        )
        self._fill_in_empty_commands(api_commands, devices_expecting_command)
        return list(api_commands.values())

    def _remove_commands_for_devices_not_expecting_command(
        self, api_commands: dict[str, HandledCommand], devices: list[_Device | DevicePy]
    ) -> None:
        found_commands = api_commands.copy()
        for drepr, command in found_commands.items():
            if command.device not in devices:
                drepr = device_repr(command.device)
                msg = f"Device '{drepr}' not connected. Command from API will be ignored."
                logger.warning(msg, self._car_name)
                api_commands.pop(drepr)

    def _collect_first_commands_from_apis(self) -> dict[str, HandledCommand]:
        commands: dict[str, HandledCommand] = dict()
        for module in self._modules:
            for data, device in self._get_module_commands(module):
                drepr = device_repr(device)
                if drepr in commands:
                    logger.warning(
                        f"First command for device '{drepr}' duriníg connection sequence has already been received. Skipping others.",
                        self._car_name,
                    )
                else:
                    commands[drepr] = HandledCommand(data, device, from_api=True)
        return commands

    def _fill_in_empty_commands(
        self,
        commands: dict[str, HandledCommand],
        devices_expecting_command: list[_Device],
    ) -> None:

        for device in devices_expecting_command:
            if device_repr(device) not in commands:
                commands[device_repr(device)] = HandledCommand(b"", device=device, from_api=False)
                logger.info(
                    f"No command received for device {device_repr(device)}. Creating empty command.",
                    self._car_name,
                )

    def _connect_device(self, device: _Device) -> bool:
        """Connect the device if it is not already connected, take no action if otherwise."""
        drepr = device_repr(device)
        logger.info(f"Connecting device {drepr}.", self._car_name)
        if self._known_devices.is_connected(device):
            logger.info(f"Device {drepr} is already connected.", self._car_name)
        else:
            code = self._modules[device.module].api.device_connected(device)
            if code == GeneralErrorCode.OK:
                self._add_connected_devices(device)
                logger.info(f"Device {drepr} has been connected.", self._car_name)
                return True
            logger.error(
                f"Device {drepr} could not connect. Response code: {code}.", self._car_name
            )
        return False

    def _disconnect_device(self, disconnect_types: DisconnectTypes, device: _Device) -> bool:
        """Disconnect a connected device and return `True` if successful. In other cases, return `False`.

        If the device has already not been connected, log an error.
        """
        drepr = device_repr(device)
        logger.info(f"Disconnecting device {drepr}.", self._car_name)
        if self._known_devices.is_not_connected(device):
            logger.warning(
                f"Device {drepr} is already disconnected. No action is taken.", self._car_name
            )
        else:
            self._known_devices.remove(DevicePy.from_device(device))
            code = self._modules[device.module].api.device_disconnected(disconnect_types, device)
            if code == GeneralErrorCode.OK:
                logger.info(f"Device {drepr} has been disconnected.", self._car_name)
                return True
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
            logger.warning(
                f"Ignoring device {device_repr(device)} from unsupported module.",
                self._car_name,
                stack_level_up=0,
            )

    def _ensure_connection_to_broker(self) -> None:
        """Connect the MQTT client to the MQTT broker.

        Raise exception if the connection fails.
        """
        logger.info("Connecting to MQTT broker.", self._car_name)
        self._mqtt.connect()
        self._set_state(ServerState.CONNECTED)

    def _get_and_send_first_commands(self) -> None:
        """Send command to all connected devices and check responses are returned."""
        self._check_at_least_one_device_is_connected()
        for cmd in self._first_commands_for_init_sequence():
            self._command_checker.add(cmd)
            logger.debug(f"Sending command to {device_repr(cmd.device)}.", self._car_name)
            ext_cmd = cmd.external_command(self._mqtt.session.id)
            self._mqtt.publish(ext_cmd, f"Sending command (counter={cmd.counter}).")

    def _get_first_commands_responses(self) -> None:
        n_devices = self._known_devices.n_all
        logger.info(
            f"Expecting responses to {n_devices} command{'s' if n_devices>1 else ''}.",
            self._car_name,
        )
        for iter in range(n_devices):
            logger.info(f"Waiting for command response {iter + 1} of {n_devices}.", self._car_name)
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
        while response := self._mqtt._get_message():
            if isinstance(response, _ExternalClientMsg) and response.HasField("commandResponse"):
                if self._is_valid_session_id(
                    response.commandResponse.sessionId, "command response"
                ):
                    logger.info("Received a command response.", self._car_name)
                    return response.commandResponse
            else:
                # ignore other messages
                if response.HasField("status"):
                    msg_type = "status"
                elif response.HasField("connect"):
                    msg_type = "connect message"
                else:
                    msg_type = "other"
                logger.info(
                    f"Expected command response, received {msg_type}. Skipping.",
                    self._car_name,
                )
        # response is None
        raise ConnectSequenceFailure("Command response has not been received.")

    def _handle_unexpected_connect_msg(self, connect_msg: _Connect) -> None:
        """Handle connect message received during normal communication, i.e., after init sequence."""
        # matching and not matching session ID are handled differently from the rest of the 'handle_*' methods
        if connect_msg.sessionId == self._mqtt.session.id:
            self._publish_connect_response(_ConnectResponse.ALREADY_LOGGED)
            msg = "Received connect message with ID of already existing session. Ignoring."
        else:
            msg = "Received connect message with session ID not matching current one. Ignoring."
        logger.info(msg, self._car_name)

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
        module, device = self._module_and_device(status)
        if not module or not device:
            logger.info(
                f"Ignoring status (counter={status.messageCounter}') from unsupported device '{device_repr(status.deviceStatus.device)}'.",
                self._car_name,
            )
        elif self._handle_checked_status_by_device_state(status, device):
            module.api.forward_status(status)
            logger.info(
                f"Status (counter={status.messageCounter}' from device '{device_repr(device)}' has been forwarded.",
                self._car_name,
            )
            self._publish_status_response(status)
            if status.deviceState == _Status.DISCONNECT:
                self._disconnect_device(DisconnectTypes.announced, device)

    def _handle_checked_status_by_device_state(self, status: _Status, device: _Device) -> bool:
        """Handle the status that has been checked by the status checker.

        Return `True` if the status is handled successfully, otherwise return `False`.
        """
        status_ok = True
        match status.deviceState:
            case _Status.CONNECTING:
                status_ok = self._connect_device(device)
            case _Status.RUNNING:
                if not self._known_devices.is_connected(device):
                    logger.info("Device is not connected. Ignoring status.", self._car_name)
                    status_ok = False
            case _Status.DISCONNECT:
                logger.info(
                    f"Received status with a disconnect message for device {device_repr(device)}.",
                    self._car_name,
                )
                if not self._known_devices.is_connected(device):
                    logger.info(
                        "Device is already disconnected. Ignoring status with disconnect message.",
                        self._car_name,
                    )
                    status_ok = False
            case _:
                logger.warning(
                    f"Ignoring device status with unknown state: {status.deviceState}.",
                    self._car_name,
                )
                status_ok = False
        return status_ok

    def _handle_command(self, module_id: int, data: bytes, device: _Device) -> None:
        """Handle the command received from API during normal communication (after init sequence)."""
        if device.module == module_id:
            self._publish_command(data, device)
        else:
            logger.warning(
                f"Module ID '{module_id}' stored by API does not match module ID {device.module}' from the command.",
                self._car_name,
            )
            if self._config.send_invalid_command:
                self._publish_command(data, device)
            else:
                logger.warning(
                    f"Command to device {device_repr(device)} with module ID mismatch will not be sent.",
                    self._car_name,
                )

    def _get_api_command(self, module_id: int) -> tuple[bytes, _Device] | None:
        """Pop the next command from the module's command waiting thread."""
        return self._modules[module_id].thread.pop_command()

    def _handle_command_response(self, cmd_response: _CommandResponse) -> None:
        """Handle the command response received during normal communication, i.e., after init sequence."""
        logger.info(
            f"Received command response with counter '{cmd_response.messageCounter}'.",
            self._car_name,
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
            logger.info(f"Device has {device_repr(device)} disconnected.", self._car_name)
        else:
            logger.info("Received command response for unknown device. Ignoring.", self._car_name)

    def _handle_communication_event(self, event: _Event) -> None:
        """Match the event type and handle it accordingly.

        Raise exception if connection to MQTT BROKER is lost or if expected command response
        or status is not received.
        """
        match event.event_type:
            case _EventType.CAR_MESSAGE_AVAILABLE:
                self._handle_car_message()
            case _EventType.COMMAND_AVAILABLE:
                self._check_and_handle_available_commands(event.data)
            case _EventType.MQTT_BROKER_DISCONNECTED:
                raise UnexpectedMQTTDisconnect("Unexpected disconnection of MQTT client.")
            case _EventType.TIMEOUT_OCCURRED:
                self._handle_timeout_event(event.data)
            case _EventType.SERVER_STOPPED:
                logger.info("Server is being stopped.", self._car_name)
            case _:
                logger.warning("Uknown event during normal communication. Ignoring.")

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
            self._handle_unexpected_connect_msg(message.connect)
        elif message.HasField("status"):
            if self._is_valid_session_id(message.status.sessionId, "status"):
                self._reset_session_checker()
                self._handle_status(message.status)
        elif message.HasField("commandResponse"):
            if self._is_valid_session_id(message.commandResponse.sessionId, "command response"):
                self._reset_session_checker()
                self._handle_command_response(message.commandResponse)
        else:
            logger.warning("Received message of unknown type. Ignoring.", self._car_name)

    def _is_valid_session_id(self, message_session_id: str, message_type: str = "message") -> bool:
        """Check if the session ID of the message matches the current session ID of the server.

        Return `True` if the session ID is valid, otherwise log a warning and return `False`.
        """
        if message_session_id != self._mqtt.session.id:
            logger.info(
                f"Ignoring {message_type.strip()} with different session ID '{message_session_id}'.",
                self._car_name,
            )
            return False
        return True

    def _init_sequence(self) -> None:
        """Runs initial sequence before starting normal communication over MQTT.

        This includes
        - receiving (single) connect message and sending reponse,
        - receiving first status for every device listed in the connect message IN ORDER
        of the devices in the connect message and sending responses to each one,
        - sending first command to every device listed in the connect message IN ORDER
        of the devices in the connect message and receiving responses to each one.
        """

        if self._should_skip_init_sequence():
            return
        logger.info("Starting the connect sequence.", self._car_name)
        try:
            self._validate_initial_state()
            self._perform_connect_sequence()
            self._finalize_init_sequence()
        except Exception as e:
            self._handle_init_sequence_failure(e)

    def _should_skip_init_sequence(self) -> bool:
        if self.state == ServerState.STOPPED:
            logger.info(
                "Server has been stopped. Connect sequence will not be started.", self._car_name
            )
            return True
        return False

    def _validate_initial_state(self) -> None:
        if self.state != ServerState.CONNECTED:
            raise ConnectSequenceFailure(
                "Cannot start connect sequence without connection to MQTT broker."
            )

    def _perform_connect_sequence(self) -> None:
        self._get_and_handle_connect_message()
        self._get_all_first_statuses_and_respond()
        self._send_first_commands_and_get_responses()

    def _finalize_init_sequence(self) -> None:
        self._set_state(ServerState.INITIALIZED)
        if self._state == ServerState.INITIALIZED:
            logger.info("Connect sequence has finished successfully.", self._car_name)
        self._event_queue.clear()

    def _handle_init_sequence_failure(self, e: Exception) -> None:
        msg = f"Connection sequence has failed. {e}"
        raise ConnectSequenceFailure(msg) from e

    def _initialize_modules(self, server_config: _CarConfig) -> dict[int, _ServerModule]:
        """Return dictionary of ServerModule instances created.

        Each instance corresponds to a module defined in the server configuration.
        """
        modules: dict[int, _ServerModule] = dict()
        for id_str, module_config in server_config.modules.items():
            module_id = int(id_str)
            modules[module_id] = self._new_server_module(module_id, module_config)
        return modules

    def _new_server_module(self, module_id: int, module_config: _ModuleConfig) -> _ServerModule:
        """Create a new instance of the ServerModule class."""
        return _ServerModule(
            module_id,
            self._company,
            self._car_name,
            module_config,
            partial(self._known_devices.any_connected_device, module_id),
            event_queue=self._event_queue,
        )

    def _log_new_status(self, status: _Status) -> None:
        info = f"Received status, counter={status.messageCounter}."
        logger.info(info, self._car_name)

    def _module_and_device(self, message: _Status) -> tuple[_ServerModule | None, _Device | None]:
        """Return server module and device referenced by the status messages.

        Return None if the module or device is unknown or unsupported.
        """
        device = message.deviceStatus.device
        module = self._modules.get(device.module, None)
        if not module:
            logger.warning(
                f"Status (counter='{message.messageCounter}') from unknown module (ID={device.module}).",
                self._car_name,
            )
            return None, None
        if not module.api.is_device_type_supported(device.deviceType):
            self.warn_device_not_supported_by_module(module, device, self._car_name)
            return None, None
        return module, device

    def _publish_command(self, data: bytes, device: _Device) -> None:
        """Publish the external command to the MQTT broker on publish topic."""

        if not self._known_devices.is_connected(device):
            logger.warning(
                f"Sending command to a not connected device ({device_repr(device)}).",
                self._car_name,
            )
        if not data:
            logger.warning(
                f"Data of command for device {device_repr(device)} is empty.", self._car_name
            )

        handled_cmd = HandledCommand(data=data, device=device, from_api=True)
        self._command_checker.add(handled_cmd)
        # the following has to be called before publishing in order to assign counter to the command
        self._mqtt.publish(handled_cmd.external_command(self.session_id))
        logger.info(f"Sending command, counter = {handled_cmd.counter}", self._car_name)

    def _publish_connect_response(self, response_type: int) -> None:
        """Publish the connect response message to the MQTT broker on publish topic."""
        msg = _connect_response(self._mqtt.session.id, response_type)
        logger.info(f"Sending connect response of type {response_type}", self._car_name)
        self._mqtt.publish(msg)

    def _publish_status_response(self, status: _Status) -> None:
        """Publish the status response message to the MQTT broker on publish topic."""
        if status.sessionId != self._mqtt.session.id:
            logger.warning(
                "Status session ID does not match current session ID of the server. Status response"
                f" to the device {device_repr(status.deviceStatus.device)} will not be sent.",
                self._car_name,
            )
        else:
            status_response = _status_response(self._mqtt.session.id, status.messageCounter)
            logger.info(
                f"Sending status response of type {status_response.statusResponse.type}.",
                self._car_name,
            )
            self._mqtt.publish(status_response)

    def _reset_session_checker(self) -> None:
        """Reset the session checker's timer."""
        logger.debug("Resetting MQTT session checker timer.", self._car_name)
        self._mqtt.session.reset_timer()

    def _run_initial_sequence(self) -> None:
        """Ensure connection to MQTT broker and run the initial sequence.

        Raise an exception if the sequence fails.
        """
        self._set_state(ServerState.UNINITIALIZED)
        try:
            self._ensure_connection_to_broker()
            if not self._running:
                self._set_running_flag(True)
            self._init_sequence()
        except:
            self._set_state(ServerState.ERROR)
            raise

    def _run_normal_communication(self) -> None:
        """Start the normal communication over MQTT. An init sequence must have been completed successfully."""
        if self._state == ServerState.STOPPED:
            return
        elif self.state != ServerState.INITIALIZED:
            raise ConnectSequenceFailure("Cannot start communication after init sequence failed.")
        try:
            self._mqtt.session.start()
            self._set_state(ServerState.RUNNING)
            if not self._running:
                self._set_running_flag(True)
            while self._running and self.state != ServerState.STOPPED:
                event = self._event_queue.get()
                self._handle_communication_event(event)
        except Exception:
            self._set_state(ServerState.ERROR)
            raise

    def _set_state(self, state: ServerState) -> None:
        """Set the server's state variable to the given value if the transition is allowed.

        No action is taken if the transition is not allowed.
        """
        if ServerState.is_valid_transition(current_state=self.state, new_state=state):
            logger.debug(f"Changing server's state from {self._state} to {state}.", self._car_name)
            self._state = state
        elif state != self.state:
            logger.debug(
                f"Cannot change server's state from {self._state} to {state}.", self._car_name
            )

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
        except Exception as e:
            logger.log_on_exception(e, self._car_name)
        finally:
            self._clear_context()
            time.sleep(self._config.sleep_duration_after_connection_refused)

    @staticmethod
    def check_device_is_in_connecting_state(status: _Status, car: str = "") -> None:
        """Check if the device state contained in the status is connecting."""
        if status.deviceState != _Status.CONNECTING:
            state = DeviceStatusName._value2member_map_[status.deviceState]
            connecting_state = DeviceStatusName._value2member_map_[_Status.CONNECTING]
            msg = (
                f"First status from device {device_repr(status.deviceStatus.device)} "
                f"must contain {connecting_state} state, received {state}."
            )
            logger.error(msg, car)
            raise ConnectSequenceFailure(msg)

    @staticmethod
    def warn_device_not_supported_by_module(
        module: _ServerModule, device: _Device, car: str, msg: str = ""
    ) -> None:
        logger.warning(
            f"Device of type `{device.deviceType}` is not supported by module '{module.id}'. {msg}",
            car,
        )
