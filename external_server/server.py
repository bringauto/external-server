import logging.config
from functools import partial
import time
import sys
from logging import Logger as _Logger
import enum
import json

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import (  # type: ignore
    CommandResponse as _CommandResponse,
    Connect as _Connect,
    ConnectResponse as _ConnectResponse,
    ExternalClient as _ExternalClientMsg,
    ExternalServer as _ExternalServerMsg,
    Status as _Status,
)
from InternalProtocol_pb2 import Device as _Device  # type: ignore
from external_server.checkers import CommandChecker, Session, StatusChecker
from external_server.models.exceptions import (
    ConnectSequenceFailure,
    CommunicationException,
    StatusTimeout,
    NoPublishedMessage,
    CommandResponseTimeout,
    SessionTimeout,
    UnexpectedMQTTDisconnect,
)
from external_server.models.server_messages import (
    connect_response as _connect_response,
    status_response as _status_response,
)
from external_server.adapters.mqtt_adapter import MQTTClientAdapter
from external_server.utils import device_repr
from external_server.config import Config as ServerConfig
from external_server.models.structures import (
    GeneralErrorCode,
    DisconnectTypes,
    TimeoutType,
)
from external_server.models.devices import DevicePy, KnownDevices
from external_server.models.event_queue import EventQueueSingleton, EventType, Event as _Event
from external_server.server_module.server_module import ServerModule as _ServerModule
from external_server.models.structures import HandledCommand as _HandledCommand


logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


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
    ServerState.CONNECTED: {ServerState.ERROR, ServerState.STOPPED, ServerState.INITIALIZED},
    ServerState.INITIALIZED: {ServerState.ERROR, ServerState.STOPPED, ServerState.RUNNING},
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
        self._running = False
        self._config = config
        self._state: ServerState = ServerState.UNINITIALIZED
        self._event_queue = EventQueueSingleton()
        self._known_devices = KnownDevices()
        self._session = Session(self._config.mqtt_timeout)
        self._status_checker = StatusChecker(self._config.timeout)
        self._command_checker = CommandChecker(self._config.timeout)
        self._mqtt = self.mqtt_adapter_from_config(config)
        self._modules = self._initialized_modules(config)

    @property
    def mqtt(self) -> MQTTClientAdapter:
        return self._mqtt

    @property
    def modules(self) -> dict[int, _ServerModule]:
        return self._modules.copy()

    @property
    def session_id(self) -> str:
        return self._session.id

    @property
    def state(self) -> ServerState:
        return self._state

    def get_and_handle_connect_message(self) -> None:
        """Wait for a connect message. If there is none, raise an exception."""
        msg = self._mqtt.get_connect_message()
        if msg is None:
            raise ConnectSequenceFailure("Connect message has not been received")
        if self.state != ServerState.STOPPED:
            self._session.set_id(msg.sessionId)
            for device in msg.devices:
                self._connect_device_if_supported(device)
            self._publish_connect_response(_ConnectResponse.OK)

    def get_all_first_statuses_and_respond(self) -> None:
        """Wait for first status from each of all known devices and send responses.

        The order of the status is expected to match the order of the devices in the
        connect message.
        """
        k = 0
        n = self._known_devices.n_all
        _counter_initialized = False
        while k < n:
            # after the loop is finished, all supported devices received status response
            # and are expected to accept a first command
            logger.info(f"Waiting for status message {k + 1} of {n}.")
            status_obj = self._mqtt.get_status()
            if status_obj is None:
                raise ConnectSequenceFailure("First status from device has not been received.")
            status, device = status_obj.deviceStatus, status_obj.deviceStatus.device
            module = self._modules[device.module]
            if not module.is_device_supported(device):
                self.warn_device_not_supported_by_module(module, device)
            elif status_obj.sessionId != self._session.id:
                logger.warning("Received status with different session ID. Skipping.")
            else:
                k += 1
                if not _counter_initialized:
                    self._status_checker.initialize_counter(status_obj.messageCounter + 1)

                self.check_device_is_in_connecting_state(status_obj)
                status, device = status_obj.deviceStatus, status_obj.deviceStatus.device
                self._log_new_status(status_obj)

                if self._known_devices.is_not_connected(device):
                    logger.warning(f"Status from not connected device {device_repr(device)}.")
                if status_obj.errorMessage:
                    module.api.forward_error_message(device, status_obj.errorMessage)
                module.api.forward_status(device, status.statusData)

                self._publish_status_response(status_obj)

    def send_first_commands_and_get_responses(self) -> None:
        """Send first command to each of all known connected and not connected devices.
        Raise exception if any command response is not received.
        """
        self._get_and_send_first_commands()
        self._get_first_commands_responses()

    def start(self) -> None:
        """Starts the external server.

        This includes:
        - starting thread waiting for commands for each of the supported modules,
        - starting the MQTT connection.
        """
        self._start_module_threads()
        self._start_communication_loop()

    def stop(self, reason: str = "") -> None:
        """Stop the external server communication, stop the MQTT client event loop,
        clear the modules.
        """
        msg = f"Stopping the external server."
        self._set_state(ServerState.STOPPED)
        if reason:
            msg += f" Reason: {reason}"
        logger.info(msg)
        self._running = False
        self._clear_context()
        self._clear_modules()

    def tls_set(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        "Set tls security to MQTT client"
        self._mqtt.tls_set(ca_certs, certfile, keyfile)

    def _add_connected_device(self, device: _Device) -> None:
        assert isinstance(device, _Device)
        self._known_devices.connected(DevicePy.from_device(device))

    def _add_not_connected_device(self, device: _Device) -> None:
        self._known_devices.not_connected(DevicePy.from_device(device))

    def _check_at_least_one_device_is_connected(self) -> None:
        if self._known_devices.n_connected == 0:
            msg = "All devices have been disconnected, restarting server."
            logger.warning(msg)
            raise CommunicationException(msg)

    def _check_received_status(self, status: _Status) -> None:
        self._log_new_status(status)
        self._reset_session_checker()
        self._status_checker.check(status)

    def _clear_context(self) -> None:
        """Stop and destroy communication with both the API and the MQTT broker.

        Stop and destroy all timers and threads, clear the known devices list and queues.
        """
        self._mqtt.disconnect()
        self._command_checker.reset()
        self._session.stop()
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
                logger.error(f"Module {module.id}: Error in destroy function. Code: {code}")
        self._modules.clear()

    def _collect_first_commands_for_init_sequence(self) -> list[_HandledCommand]:
        """Collect all first commands for the init sequence."""
        commands: list[_HandledCommand] = list()
        expecting_cmd: list[_Device] = [d.to_device() for d in self._known_devices.list_connected()]
        received_cmd: list[_Device] = list()
        for module in self._modules:
            for cmd in self._get_module_commands(module):
                data, device = cmd[0], cmd[1]
                drepr = device_repr(device)
                if device in expecting_cmd:
                    commands.append(_HandledCommand(data, device=device, from_api=True))
                    expecting_cmd.remove(device)
                    received_cmd.append(device)
                elif device in received_cmd:
                    logger.warning(f"Multiple commands for '{drepr}'. Only the first is accepted.")
                else:  # device could not be in the list of connected devices
                    logger.warning(
                        f"Command from API for not connected device '{drepr}' is ignored."
                    )
        for device in expecting_cmd:
            commands.append(_HandledCommand(b"", device=device, from_api=False))
            logger.warning(
                f"No command received for device {device_repr(device)}. Creating empty command."
            )
        for device_py in self._known_devices.list_not_connected():
            commands.append(_HandledCommand(b"", device=device_py.to_device(), from_api=False))
            logger.warning(
                f"Device {device_repr(device_py)} is not connected. Creating empty command."
            )
        return commands

    def _connect_device(self, device: _Device) -> bool:
        """Connect the device if it is not already connected.

        No action is taken if the device is already connected.
        """
        if self._known_devices.is_connected(device):
            logger.error(f"Device {device_repr(device)} already connected.")
        else:
            code = self._modules[device.module].api.device_connected(device)
            if code == GeneralErrorCode.OK:
                self._add_connected_device(device)
                logger.info(f"Connected device {device_repr(device)}.")
                return True
            else:
                logger.error(
                    f"Device {device_repr(device)} could not connect. Response code: {code}"
                )
        return False

    def _disconnect_device(self, disconnect_types: DisconnectTypes, device: _Device) -> bool:
        if not self._known_devices.is_connected(device):
            logger.error(f"Device {device_repr(device)} is not connected.")
        else:
            logger.warning(f"Disconnecting device {device_repr(device)}.")
            self._known_devices.remove(DevicePy.from_device(device))
            code = self._modules[device.module].api.device_disconnected(disconnect_types, device)
            if code == GeneralErrorCode.OK:
                return True
        return False

    def _ensure_connection_to_broker(self) -> None:
        """Connect the MQTT client to the MQTT broker.

        Raise exception if the connection fails.
        """
        logger.info("Connecting to MQTT broker.")
        e = self._mqtt.connect()
        if e is not None:
            raise ConnectionRefusedError(e)
        self._set_state(ServerState.CONNECTED)

    def _forward_status(self, status: _Status, module: _ServerModule) -> None:
        """Forward the status to the module's API."""
        device, data = status.deviceStatus.device, status.deviceStatus.statusData
        module.api.forward_status(device, data)

    def _get_and_send_first_commands(self) -> None:
        """Send command to all connected devices and check responses are returned."""
        if self._known_devices.n_connected == 0:
            raise ConnectSequenceFailure("No connected device.")
        commands = self._collect_first_commands_for_init_sequence()
        for cmd in commands:
            self._command_checker.add(cmd)
            ext_cmd = cmd.external_command(self._session.id)
            self._mqtt.publish(ext_cmd, f"Sending command (counter={cmd.counter}).")

    def _get_first_commands_responses(self) -> None:
        n_devices = self._known_devices.n_all
        logger.info(f"Expecting responses to {n_devices} command{'s' if n_devices>1 else ''}.")
        for iter in range(n_devices):
            logger.info(f"Waiting for command response {iter + 1} of {n_devices}.")
            response = self._get_next_valid_command_response()
            commands = self._command_checker.pop_commands(response.messageCounter)
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
        while (response := self._mqtt._get_message()) is not None:
            if isinstance(response, _ExternalClientMsg) and response.HasField("commandResponse"):
                if response.commandResponse.sessionId == self._session.id:
                    logger.info(f"Received a command response.")
                    return response.commandResponse
                else:
                    logger.warning("Skipping command response with different session ID.")
            else:
                # ignore other messages
                logger.warning(f"Skipping message of wrong type (expected command response).")
        # response is None
        error_msg = "Command response has not been received."
        logger.error(error_msg)
        raise ConnectSequenceFailure(error_msg)

    def _handle_connect(self, connect_msg: _Connect) -> None:
        """Handle connect message received during normal communication, i.e., after init sequence."""
        logger.warning("Received connect message when already connected.")
        if connect_msg.sessionId == self._session.id:
            logger.error("Received connect message with ID of already existing session.")
        else:
            self._publish_connect_response(_ConnectResponse.ALREADY_LOGGED)

    def _handle_status(self, received_status: _Status) -> None:
        """Handle the status received during normal communication, i.e., after init sequence.

        If the status is valid and comes with expected counter value, handle all stored received statuses.
        """
        self._check_received_status(received_status)
        while status := self._status_checker.get():
            self._handle_checked_status(status)
        self._check_at_least_one_device_is_connected()

    def _handle_checked_status(self, status: _Status) -> None:
        """Handle the status that has been checked by the status checker."""
        module_and_dev = self._module_and_device(status)
        if not module_and_dev:
            return
        module, device = module_and_dev
        if not module.is_device_supported(device):
            logger.warning(
                f"Received status from device {device_repr(device)} "
                f"not supported by module {module.id}. Ignoring."
            )
        else:
            status_ok = True
            match status.deviceState:
                case _Status.CONNECTING:
                    status_ok = self._connect_device(device)
                case _Status.RUNNING:
                    if self._known_devices.is_not_connected(device):
                        logger.error(f"Device {device_repr(device)} is not connected.")
                        status_ok = False
                case _Status.DISCONNECT:
                    status_ok = self._disconnect_device(DisconnectTypes.announced, device)
                case _:
                    # unhandled state
                    pass
            if status_ok:
                self._forward_status(status, module)
            self._log_status_error(status, device)
            self._publish_status_response(status)

    def _handle_command(self, module_id: int, command: tuple[bytes, _Device]) -> None:
        """Handle the command received from API during normal communication (after init sequence)."""
        cmd_data, device = command
        if not self._known_devices.is_connected(device):
            logger.warning(f"Sending command to a not connected device ({device_repr(device)}).")
        if not cmd_data:
            logger.warning(f"Data of command for device {device_repr(device)} is empty.")

        if device.module == module_id:
            self._publish_command(cmd_data, device)
        else:
            logger.warning(f"Device ID {device_repr(device)} from API of module {module_id} contains different module ID.")
            if self._config.send_invalid_command:
                logger.warning("Sending command with possibly invalid device.")
                self._publish_command(cmd_data, device)
            else:
                logger.warning("Invalid command will not be sent.")

    def _get_api_command(self, module_id: int) -> tuple[bytes, _Device] | None:
        """Pop the next command from the module's command waiting thread."""
        return self._modules[module_id].thread.pop_command()

    def _handle_command_response(self, cmd_response: _CommandResponse) -> None:
        """Handle the command response received during normal communication, i.e., after init sequence."""
        logger.info("Received command response")
        device_not_connected = cmd_response.type == _CommandResponse.DEVICE_NOT_CONNECTED
        commands = self._command_checker.pop_commands(cmd_response.messageCounter)
        for command in commands:
            module = self._modules[command.device.module]
            module.api.command_ack(command.data, command.device)
            if device_not_connected and command.counter == cmd_response.messageCounter:
                self._disconnect_device(DisconnectTypes.announced, command.device)
                logger.warning(f"Device {device_repr(command.device)} disconnected.")

    def _connect_device_if_supported(self, device: _Device) -> None:
        """Connect the device if it is supported by a supported module."""
        module = self._modules.get(device.module, None)
        if module:
            if module.is_device_supported(device):
                self._connect_device(device)
            else:
                self.warn_device_not_supported_by_module(module, device)
        else:
            logger.warning(f"Ignoring device {device_repr(device)} from unsupported module.")

    def _handle_communication_event(self, event: _Event) -> None:
        """Handle the event from the event queue.

        Log error for invalid car messages.

        Raise exception if connection to MQTT BROKER is lost or if expected command response
        or status is not received.
        """
        match event.event:
            case EventType.CAR_MESSAGE_AVAILABLE:
                try:
                    self._handle_car_message()
                except NoPublishedMessage:
                    logger.error("No message from MQTT broker.")
                except UnexpectedMQTTDisconnect:
                    logger.error("Unexpected disconnection of MQTT broker.")
                except Exception as e:
                    logger.error(f"Error occurred when retrieving message from MQTT client. {e}")
            case EventType.COMMAND_AVAILABLE:
                module_id = event.data
                if not isinstance(module_id, int):
                    logger.error("Internal error: Event CommandAvailable without module ID.")
                else:
                    cmd = self._get_api_command(module_id)
                    if cmd is not None:
                        self._handle_command(module_id, cmd)
            case EventType.MQTT_BROKER_DISCONNECTED:
                if self._running:
                    raise CommunicationException("Unexpected disconnection of MQTT broker.")
            case EventType.TIMEOUT_OCCURRED:
                match event.data:
                    case TimeoutType.SESSION_TIMEOUT:
                        logger.error("Session timeout occurred.")
                        raise SessionTimeout()
                    case TimeoutType.MESSAGE_TIMEOUT:
                        logger.error("Status timeout occurred.")
                        raise StatusTimeout()
                    case TimeoutType.COMMAND_TIMEOUT:
                        logger.error("Command response timeout occurred.")
                        raise CommandResponseTimeout()
                    case _:
                        logger.error("Internal error: Event TimeoutOccurred without TimeoutType.")
                        raise CommunicationException("Internal error: Timeout event without type.")
            case _:
                pass

    def _handle_car_message(self) -> None:
        """Handle the message received from the MQTT broker during normal communication."""
        message = self._mqtt._get_message()
        if message is None:
            raise NoPublishedMessage
        elif message is False:
            raise UnexpectedMQTTDisconnect
        else:
            if message.HasField("connect"):
                # This message is not expected outside of a init sequence
                self._handle_connect(message.connect)
            elif message.HasField("status"):
                if self._session.id == message.status.sessionId:
                    self._reset_session_checker()
                    self._handle_status(message.status)
                else:
                    logger.warning("Ignoring status with different session ID.")
            elif message.HasField("commandResponse"):
                if self._session.id == message.commandResponse.sessionId:
                    self._reset_session_checker()
                    self._handle_command_response(message.commandResponse)
                else:
                    logger.warning("Ignoring command response with different session ID.")

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
            return
        logger.info("Starting the connect sequence.")
        try:
            if not self.state == ServerState.CONNECTED:
                raise ConnectSequenceFailure(
                    "Cannot start connect sequence without connection to MQTT broker."
                )
            self.get_and_handle_connect_message()
            self.get_all_first_statuses_and_respond()
            self.send_first_commands_and_get_responses()
            self._set_state(ServerState.INITIALIZED)
            self._event_queue.clear()
            logger.info("Connect sequence has finished succesfully")
        except Exception as e:
            msg = f"Connection sequence has failed. {e}"
            raise ConnectSequenceFailure(msg)

    def _initialized_modules(self, server_config: ServerConfig) -> dict[int, _ServerModule]:
        """Return dictionary of ServerModule instances created.

        Each instance corresponds to a module defined in the server configuration.
        """
        modules: dict[int, _ServerModule] = dict()
        for id_str, module_config in server_config.modules.items():
            module_id = int(id_str)
            car, company = server_config.car_name, server_config.company_name
            connection_check = partial(self._known_devices.any_connected_device, module_id)
            modules[module_id] = _ServerModule(
                module_id, company, car, module_config, connection_check
            )
        return modules

    def _log_new_status(self, status: _Status) -> None:
        """Log the new status received from the device. Include error message if non-empty."""
        status_error = f" status.errorMessage" if status.errorMessage else ""
        info = f"Received status, counter={status.messageCounter}.{status_error}"
        logger.info(info)

    def _log_status_error(self, status: _Status, device: _Device) -> None:
        """Log error if the status contains a non-empty error message."""
        if status.errorMessage:
            error_str = status.errorMessage.decode()
            logger.error(f"Status for {device_repr(device)} contains error: {error_str}.")

    def _module_and_device(self, message: _Status) -> tuple[_ServerModule, _Device] | None:
        """Return server module and device referenced by the status messages.

        Return None if the module or device is unknown or unsupported.
        """
        device = message.deviceStatus.device
        module = self._modules.get(device.module, None)
        if not module:
            logger.warning(f"Received status from unknown module (ID={device.module}).")
            return None
        elif not module.api.is_device_type_supported(device.deviceType):
            logger.warning(
                f"Device type {device.deviceType} not supported by module with ID={module.id}."
            )
            return None
        return module, device

    def _publish_command(self, data: bytes, device: _Device) -> None:
        """Publish the external command to the MQTT broker on publish topic."""
        handled_cmd = _HandledCommand(data=data, device=device, from_api=True)
        # the following has to be called before publishing in order to assign counter to the command
        self._command_checker.add(handled_cmd)
        logger.info(f"Sending command, counter = {handled_cmd.counter}")
        self._mqtt.publish(handled_cmd.external_command(self.session_id))

    def _publish_connect_response(self, response_type: int) -> None:
        """Publish the connect response message to the MQTT broker on publish topic."""
        msg = _connect_response(self._session.id, response_type)
        logger.info(f"Sending connect response of type {response_type}")
        self._mqtt.publish(msg)

    def _publish_status_response(self, status: _Status) -> None:
        """Publish the status response message to the MQTT broker on publish topic."""
        status_response = self._status_response(status)
        logger.info(f"Sending status response of type {status_response.statusResponse.type}")
        self._mqtt.publish(status_response)

    def _reset_session_timeout_for_session_id_match(self, session_id: str) -> None:
        """Reset the session checker if the session ID matches the current session ID."""
        if session_id == self._session.id:
            self._reset_session_checker()

    def _reset_session_checker(self) -> None:
        """Reset the session checker's timer."""
        self._session.reset_timer()

    def _run_initial_sequence(self) -> None:
        """Ensure connection to MQTT broker and run the initial sequence.

        Raise an exception if the sequence fails
        """
        try:
            self._set_state(ServerState.UNINITIALIZED)
            self._ensure_connection_to_broker()
            self._init_sequence()
        except Exception as e:
            self._set_state(ServerState.ERROR)
            raise e

    def _run_normal_communication(self) -> None:
        """Start the normal communication over MQTT. An init sequence must have been completed successfully."""
        if not self.state == ServerState.INITIALIZED:
            raise ConnectSequenceFailure("Cannot start communication after init sequence failed.")
        self._session.start()
        self._set_state(ServerState.RUNNING)
        while self.state != ServerState.STOPPED:
            try:
                event = self._event_queue.get()
                self._handle_communication_event(event)
            except Exception as e:
                logger.error(e)
                self._set_state(ServerState.ERROR)
                raise e

    def _set_state(self, state: ServerState) -> None:
        """Set the server's state variable to the given value if the transition is allowed.

        No action is taken if the transition is not allowed.
        """
        if state in StateTransitionTable[self._state]:
            logger.debug(f"Changing server's state from {self._state} to {state}")
            self._state = state
        elif state != self.state:
            logger.debug(f"Cannot change server's state from {self._state} to {state}")
        return

    def _status_response(self, status: _Status) -> _ExternalServerMsg:
        return _status_response(status.sessionId, status.messageCounter)

    def _start_module_threads(self) -> None:
        """Start threads for polling each module's API for new commands."""
        for _id in self._modules:
            self._modules[_id].thread.start()

    def _start_communication_loop(self) -> None:
        """Start the main communication loop including the init sequence and normal communication."""
        self._running = True
        while self._running and self.state != ServerState.STOPPED:
            self._single_communication_run()

    def _single_communication_run(self) -> None:
        """Run the initial sequence and normal communication once."""
        try:
            self._run_initial_sequence()
            self._run_normal_communication()
        except Exception as e:
            logger.error(e)
            time.sleep(self._config.sleep_duration_after_connection_refused)
        finally:
            self._clear_context()

    @staticmethod
    def check_message_is_command_response(response: _ExternalClientMsg) -> None:
        """Check if the response is a command response."""
        if response is None or response == False:
            error_msg = "Command response has not been received."
            logger.error(error_msg)
            raise ConnectSequenceFailure(error_msg)
        if not response.HasField("commandResponse"):
            error_msg = "Received message is not a command response."
            logger.error(error_msg)
            raise ConnectSequenceFailure(error_msg)

    @staticmethod
    def check_device_is_in_connecting_state(status: _Status) -> None:
        """Check if the device state contained in the status is connecting."""
        if status.deviceState != _Status.CONNECTING:
            state = DeviceStatusName.get(status.deviceState, str(status.deviceState))
            connecting_state = DeviceStatusName[_Status.CONNECTING]
            msg = (
                f"First status from device {device_repr(status.deviceStatus.device)} "
                f"must contain {connecting_state} state, received {state}."
            )
            logger.error(msg)
            raise ConnectSequenceFailure(msg)

    @staticmethod
    def mqtt_adapter_from_config(config: ServerConfig) -> MQTTClientAdapter:
        return MQTTClientAdapter(
            config.company_name,
            config.car_name,
            config.timeout,
            config.mqtt_address,
            config.mqtt_port,
        )

    @staticmethod
    def warn_device_not_supported_by_module(
        module: _ServerModule, device: _Device, msg: str = ""
    ) -> None:
        logger.warning(
            f"Device type {device.deviceType} not supported by module {module.id}. {msg}"
        )
