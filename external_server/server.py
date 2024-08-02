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
        self._devices = KnownDevices()
        self._session = Session(self._config.mqtt_timeout)
        self._status_checker = StatusChecker(self._config.timeout)
        self._command_checker = CommandChecker(self._config.timeout)
        self._mqtt = self.mqtt_adapter_from_config(config)
        self._modules = self._initialized_modules(config)

    @property
    def modules(self) -> dict[int, _ServerModule]:
        return self._modules.copy()

    @property
    def mqtt(self) -> MQTTClientAdapter:
        return self._mqtt

    @property
    def session_id(self) -> str:
        return self._session.id

    @property
    def state(self) -> ServerState:
        return self._state

    @state.setter
    def state(self, state: ServerState) -> None:
        if state in StateTransitionTable[self._state]:
            logger.debug(f"Changing server's state from {self._state} to {state}")
            self._state = state
        elif state != self.state:
            logger.debug(f"Cannot change server's state from {self._state} to {state}")
        return

    def get_and_handle_connect_message(self) -> None:
        """Wait for a connect message. If there is none, raise an exception."""
        msg = self._mqtt.get_connect_message()
        if msg is None:
            raise ConnectSequenceFailure("Connect message has not been received")
        if self.state != ServerState.STOPPED:
            self._session.id = msg.sessionId
            for device in msg.devices:
                self._handle_device_from_connect_message(device)
            self._publish_connect_response(_ConnectResponse.OK)

    def get_all_first_statuses_and_respond(self) -> None:
        """Wait for first status from each of all known devices and send responses.

        The order of the status is expected to match the order of the devices in the
        connect message.
        """
        n = self._devices.n_all
        _counter_initialized = False
        for k in range(n):
            logger.info(f"Waiting for status message {k + 1} out of {n}.")
            status_obj = self._mqtt.get_status()
            if status_obj is None:
                raise ConnectSequenceFailure("First status from device has not been received.")
            if not _counter_initialized:
                self._status_checker.initialize_counter(status_obj.messageCounter + 1)

            ExternalServer.check_device_is_in_connecting_state(status_obj.deviceState)
            status, device = status_obj.deviceStatus, status_obj.deviceStatus.device
            if not self._devices.is_supported(device):
                logger.warning(f"Status from not connected device {device_repr(device)}.")
            self._log_new_status(status_obj)

            if self._devices.is_unsupported(device):
                module = self._modules[device.module]
                if status_obj.errorMessage:
                    module.api_adapter.forward_error_message(device, status_obj.errorMessage)
                module.api_adapter.forward_status(device, status.statusData)

            self._publish_status_response(status_obj)

    def get_and_send_first_commands(self) -> None:
        """Send command to all connected devices and check responses are returned."""
        no_cmd_devices = self._devices.list_supported()
        logger.info("Generating and sending commands to all devices.")
        for module in self._modules:
            module_commands = self._get_module_commands(module)
            for cmd_bytes, device in module_commands:
                device_got_cmd = self.is_device_in_list(device, no_cmd_devices)
                device_supported = self._devices.is_supported(device)
                drepr = device_repr(device)
                if device_got_cmd and device_supported:
                    logger.warning(f"More than one command for '{drepr}' during connect sequence.")
                elif not self.is_device_in_list(device, no_cmd_devices):
                    logger.warning(f"Command for not connected device '{drepr}' will not be sent.")
                else:
                    handled_cmd = _HandledCommand(cmd_bytes, device=device, from_api=True)
                    self._command_checker.add(handled_cmd)
                    ext_cmd = handled_cmd.external_command(self._session.id)
                    self._mqtt.publish(ext_cmd, f"Sending command (counter={handled_cmd.counter}).")
                    try:
                        no_cmd_devices.remove(DevicePy.from_device(device))
                    except ValueError:
                        msg = f"Got command for unexpected device: {drepr}"
                        logger.error(msg)
                        raise ConnectSequenceFailure(msg)

        for device_py in no_cmd_devices + self._devices.list_unsupported():
            device = device_py.to_device()
            handled_cmd = _HandledCommand(b"", device=device, from_api=False)
            self._command_checker.add(handled_cmd)
            logger.warning(
                f"No command returned from API for device {device_repr(device)}. "
                "Sending empty command."
            )
            self._mqtt.publish(
                handled_cmd.external_command(self._session.id),
                f"Sending command, counter = {handled_cmd.counter}",
            )

        n_devices = self._devices.n_all
        logger.info(f"Expecting responses to {n_devices} command{'s' if n_devices>1 else ''}.")
        for iter in range(n_devices):
            logger.info(f"Waiting for command response {iter + 1} of {n_devices}.")
            received_msg = self._mqtt._get_message()
            self._check_command_response(received_msg)
            assert received_msg is not None
            logger.info(f"Received a command response.")
            response = received_msg.commandResponse
            commands = self._command_checker.pop_commands(response.messageCounter)
            for command in commands:
                device = command.device
                device_connected = self._devices.is_supported(device)
                if device_connected and command.from_api:
                    module_id = handled_cmd.device.module
                    self._modules[module_id].api_adapter.command_ack(
                        command.data, handled_cmd.device
                    )

    def _check_command_response(self, response: _ExternalClientMsg) -> None:
        if response is None or response == False:
            msg = "Command response has not been received."
            logger.error(msg)
            raise ConnectSequenceFailure(msg)
        if not response.HasField("commandResponse"):
            msg = "Received message is not a command response."
            logger.error(msg)
            raise ConnectSequenceFailure(msg)

    def tls_set(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        "Set tls security to MQTT client"
        self._mqtt.tls_set(ca_certs, certfile, keyfile)

    def start(self) -> None:
        """Starts the external server.

        This includes:
        - starting thread waiting for commands for each of the supported modules,
        - starting the MQTT connection.
        """
        self._start_module_threads()
        self._start_communication_loop()

    def stop(self, reason: str = "") -> None:
        """Stop the external server communication, stop the MQTT client event loop, clear the modules."""
        msg = f"Stopping the external server."
        self.state = ServerState.STOPPED
        if reason:
            msg += f" Reason: {reason}"
        logger.info(msg)
        self._running = False
        self._clear_context()
        self._clear_modules()

    def _add_supported_device(self, device: _Device) -> None:
        assert isinstance(device, _Device)
        self._devices.add_supported(DevicePy.from_device(device))

    def _add_unsupported_device(self, device: _Device) -> None:
        self._devices.add_unsupported(DevicePy.from_device(device))

    def _check_at_least_one_device_is_connected(self) -> None:
        if self._devices.n_supported == 0:
            msg = "All devices have been disconnected, restarting server."
            logger.warning(msg)
            raise CommunicationException(msg)

    def _check_received_status(self, status: _Status) -> None:
        self._log_new_status(status)
        if status.sessionId != self._session.id:
            logger.warning("Received status with different session ID.")
            return
        else:
            self._reset_session_checker()
            self._status_checker.check(status)

    def _clear_context(self) -> None:
        self._mqtt.disconnect()
        self._command_checker.reset()
        self._session.stop()
        self._status_checker.reset()
        for device in self._devices.list_supported():
            module_adapter = self._modules[device.module_id].api_adapter
            module_adapter.device_disconnected(DisconnectTypes.timeout, device.to_device())
        self._devices.clear()
        self._event_queue.clear()

    def _clear_modules(self) -> None:
        for module in self._modules.values():
            module.thread.stop()
        for module in self._modules.values():
            module.thread.wait_for_join()
            code = module.api_adapter.destroy()
            if not code == GeneralErrorCode.OK:
                logger.error(f"Module {module.id}: Error in destroy function. Code: {code}")
        self._modules.clear()

    def _connect_device(self, device: _Device) -> int:
        code = self._modules[device.module].api_adapter.device_connected(device)
        if code == GeneralErrorCode.OK:
            logger.info(f"Connected device unique identificator: {device_repr(device)}")
        else:
            logger.error(f"Device {device_repr(device)} could not connect. Response code: {code}")
        return code

    def _disconnect_device(self, disconnect_types: DisconnectTypes, device: _Device) -> None:
        logger.warning(f"Disconnecting device {device_repr(device)}.")
        self._devices.remove(DevicePy.from_device(device))
        self._modules[device.module].api_adapter.device_disconnected(disconnect_types, device)

    def _ensure_connection_to_broker(self) -> None:
        """Connect the MQTT client to the MQTT broker.

        Raise exception if the connection fails.
        """
        logger.info("Connecting to MQTT broker.")
        e = self._mqtt.connect()
        if e is not None:
            raise ConnectionRefusedError(e)
        self.state = ServerState.CONNECTED

    def _forward_status(self, status: _Status, module: _ServerModule) -> None:
        """Forward the status to the module's API."""
        device, data = status.deviceStatus.device, status.deviceStatus.statusData
        module.api_adapter.forward_status(device, data)
        self._log_status_error(status, device)
        self._publish_status_response(status)

    def _get_module_commands(self, module_id: int) -> list[tuple[bytes, _Device]]:
        commands: list[tuple[bytes, _Device]] = []
        while (result := self._modules[module_id].thread.pop_command()) is not None:
            cmd_bytes, device = result
            commands.append((cmd_bytes, device))
        return commands

    def _handle_connect(self, connect_msg: _Connect) -> None:
        logger.warning("Received connect message when already connected.")
        if connect_msg.sessionId == self._session.id:
            logger.error("Received connect message with ID of already existing session.")
        else:
            self._publish_connect_response(_ConnectResponse.ALREADY_LOGGED)

    def _handle_received_status(self, received_status: _Status) -> None:
        self._check_received_status(received_status)
        while status := self._status_checker.get():
            self._handle_checked_status(status)
        self._check_at_least_one_device_is_connected()

    def _handle_checked_status(self, status: _Status) -> None:
        module_and_dev = self._module_and_device(status)
        if not module_and_dev:
            return
        module, device = module_and_dev
        match status.deviceState:
            case _Status.CONNECTING:
                if self._devices.is_supported(device):
                    logger.error(f"Device {device_repr(device)} is already connected.")
                else:
                    self._connect_device(device)
                    self._forward_status(status, module)
            case _Status.RUNNING:
                if self._devices.is_supported(device):
                    self._forward_status(status, module)
                else:
                    logger.error(f"Device {device_repr(device)} is not connected.")
            case _Status.DISCONNECT:
                if self._devices.is_supported(device):
                    self._disconnect_device(DisconnectTypes.announced, device)
                    self._forward_status(status, module)
                else:
                    logger.error(f"Device {device_repr(device)} is not connected.")
            case _:
                self._log_status_error(status, device)
                self._publish_status_response(status)

    def _handle_command(self, module_id: int) -> None:
        result = self._modules[module_id].thread.pop_command()
        if not result:
            return
        cmd_data, target_device = result
        ExternalServer.warn_if_device_not_in_list(
            self._devices.list_supported(),
            target_device,
            logger,
            msg="Command for not connected device will not be sent.",
        )
        handled_cmd = _HandledCommand(cmd_data, device=target_device, from_api=True)
        self._command_checker.add(handled_cmd)
        logger.info(f"Sending command, counter = {handled_cmd.counter}")
        if not cmd_data:
            logger.warning(f"Data of command for device {device_repr(target_device)} is empty.")
        if handled_cmd.device.module != module_id:
            logger.warning(f"Device ID from API of module {module_id} has different module ID.")
            if self._config.send_invalid_command:
                logger.warning("Sending command with possibly invalid device.")
                self._mqtt.publish(handled_cmd.external_command(self.session_id))
            else:
                logger.warning("Invalid command will not be sent.")
                self._command_checker.pop_commands(handled_cmd.counter)
        else:
            self._mqtt.publish(handled_cmd.external_command(self.session_id))

    def _handle_command_response(self, cmd_response: _CommandResponse) -> None:
        logger.info("Received command response")
        device_not_connected = cmd_response.type == _CommandResponse.DEVICE_NOT_CONNECTED
        commands = self._command_checker.pop_commands(cmd_response.messageCounter)
        for command in commands:
            module = self._modules[command.device.module]
            module.api_adapter.command_ack(command.data, command.device)
            if device_not_connected and command.counter == cmd_response.messageCounter:
                self._disconnect_device(DisconnectTypes.announced, command.device)
                logger.warning(f"Device {device_repr(command.device)} disconnected.")

    def _handle_device_from_connect_message(self, device: _Device) -> None:
        module = self._modules.get(device.module, None)
        if module:
            module.warn_if_device_unsupported(device)
            code = self._connect_device(device)
            if code == GeneralErrorCode.OK:
                self._add_supported_device(device)
            else:
                logger.error(f"Device {device_repr(device)} was not succesfully connected.")
        else:
            ExternalServer.warn_module_not_supported(device.module, logger, "Ignoring device.")
            self._add_unsupported_device(device)

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
                if isinstance(event.data, int):
                    self._handle_command(event.data)
                else:
                    logger.error("Internal error: Event CommandAvailable without module ID.")
            case EventType.MQTT_BROKER_DISCONNECTED:
                if self._running:
                    raise CommunicationException("Unexpected disconnection of MQTT broker.")
            case EventType.TIMEOUT_OCCURRED:
                match event.data:
                    case TimeoutType.SESSION_TIMEOUT:
                        raise SessionTimeout()
                    case TimeoutType.MESSAGE_TIMEOUT:
                        raise StatusTimeout()
                    case TimeoutType.COMMAND_TIMEOUT:
                        raise CommandResponseTimeout()
                    case _:
                        logger.error("Internal error: Event TimeoutOccurred without TimeoutType.")
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
                self._handle_connect(message.connect)
            elif message.HasField("status"):
                self._reset_session_timeout_for_session_id_match(message.status.sessionId)
                self._handle_received_status(message.status)
            elif message.HasField("commandResponse"):
                self._reset_session_timeout_for_session_id_match(message.commandResponse.sessionId)
                self._handle_command_response(message.commandResponse)

    def _init_sequence(self) -> None:
        """Runs initial sequence before starting normal communication over MQTT.

        This includes
        - receiving (single) connect message and sending reponse,
        - receiving first status for every device listed in the connect message IN ORDER
        of the devices in the connect message and sending responses to each one,
        - sending first command to every device listed in the connect message IN ORDER
        of the devices in the connect message and receiving responses to each one.
        """
        logger.info("Starting the connect sequence.")
        if self.state == ServerState.STOPPED:
            return
        try:
            if not self.state == ServerState.CONNECTED:
                raise ConnectSequenceFailure(
                    "Cannot start connect sequence without connection to MQTT broker."
                )
            self.get_and_handle_connect_message()
            self.get_all_first_statuses_and_respond()
            self.get_and_send_first_commands()
            self.state = ServerState.INITIALIZED
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
            connection_check = partial(self._devices.any_supported_device, module_id)
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
        device = message.deviceStatus.device
        module = self._modules.get(device.module, None)
        if not module:
            logger.warning(f"Received status from unknown module (ID={device.module}).")
            return None
        elif not module.api_adapter.is_device_type_supported(device.deviceType):
            logger.warning(f"Device type {device.deviceType} not supported by module "
                           f"{device.module} and may not work properly.")
            return None
        return module, device

    def _publish_connect_response(self, response_type: int) -> None:
        logger.info(f"Sending Connect response. Response type: {response_type}")
        msg = _connect_response(self._session.id, response_type)
        self._mqtt.publish(msg)

    def _publish_status_response(self, status: _Status) -> None:
        status_response = self._status_response(status)
        self._mqtt.publish(status_response)

    def _reset_session_timeout_for_session_id_match(self, session_id: str) -> None:
        if session_id==self._session.id:
            self._reset_session_checker()

    def _reset_session_checker(self) -> None:
        self._session.reset()

    def _run_initial_sequence(self) -> None:
        """Ensure connection to MQTT broker and run the initial sequence.

        Raise an exception if the sequence fails
        """
        try:
            self.state = ServerState.UNINITIALIZED
            self._ensure_connection_to_broker()
            self._init_sequence()
        except Exception as e:
            self.state = ServerState.ERROR
            raise e

    def _run_normal_communication(self) -> None:
        """Start the normal communication over MQTT. An init sequence must have been completed successfully."""
        if not self.state == ServerState.INITIALIZED:
            raise ConnectSequenceFailure("Cannot start communication after init sequence failed.")
        self._session.start()
        self.state = ServerState.RUNNING
        while self.state != ServerState.STOPPED:
            try:
                event = self._event_queue.get()
                self._handle_communication_event(event)
            except Exception as e:
                logger.error(e)
                self.state = ServerState.ERROR
                raise e

    def _status_response(self, status: _Status) -> _ExternalServerMsg:
        module = status.deviceStatus.device.module
        if module not in self._modules:
            logger.warning(f"Module '{module}' is not supported")
        logger.info(f"Sending Status response message, messageCounter: {status.messageCounter}")
        return _status_response(status.sessionId, status.messageCounter)

    def _start_module_threads(self) -> None:
        """Start threads for polling each module's API for new commands."""
        for _id in self._modules:
            self._modules[_id].thread.start()

    def _start_communication_loop(self) -> None:
        self._running = True
        while self._running and self.state != ServerState.STOPPED:
            self._single_communication_run()

    def _single_communication_run(self) -> None:
        try:
            self._run_initial_sequence()
            self._run_normal_communication()
        except Exception as e:
            logger.error(e)
            time.sleep(self._config.sleep_duration_after_connection_refused)
        finally:
            self._clear_context()

    @staticmethod
    def check_device_is_in_connecting_state(state_enum: _Status.DeviceState) -> None:
        if state_enum != _Status.CONNECTING:
            state = DeviceStatusName.get(state_enum, str(state_enum))
            connecting_state = DeviceStatusName[_Status.CONNECTING]
            msg = (
                f"First status from device must contain {connecting_state} state, received {state}."
            )
            logger.error(msg)
            raise ConnectSequenceFailure(msg)

    @staticmethod
    def is_device_in_list(device: _Device | DevicePy, device_list: list[DevicePy]) -> bool:
        """Check if the device is in the list.

        The device is in the list if the list contains a device with the same module, type, and role.
        """
        return device in device_list

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
    def warn_if_device_not_in_list(
        devices: list[DevicePy], device: _Device, logger: _Logger, msg: str
    ) -> None:
        """Logs a warning if the device is not in the list of devices."""
        if not ExternalServer.is_device_in_list(device, devices):
            logger.warning(f"{msg}. Device {device_repr(device)}")

    @staticmethod
    def warn_module_not_supported(module_id: int, logger: _Logger, msg: str = "") -> None:
        logger.warning(f"Module (ID={module_id}) not supported. {msg}")
