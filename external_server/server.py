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
    CommandResponseTimeout,
    SessionTimeout,
)
from external_server.server_messages import (
    connect_response as _connect_response,
    status_response as _status_response,
    external_command as _external_command,
)
from external_server.adapters.mqtt_adapter import MQTTClientAdapter
from external_server.utils import device_repr
from external_server.config import Config as Config
from external_server.models.structures import (
    GeneralErrorCode,
    DisconnectTypes,
    TimeoutType,
)
from external_server.models.devices import DevicePy, KnownDevices
from external_server.models.event_queue import EventQueueSingleton, EventType
from external_server.models.server_module import ServerModule as _ServerModule


_logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


class ServerState(enum.Enum):
    UNINITIALIZED = enum.auto()
    CONNECTED = enum.auto()
    INITIALIZED = enum.auto()
    RUNNING = enum.auto()
    ERROR = enum.auto()


DeviceStatusName = {
    _Status.CONNECTING: "CONNECTING",
    _Status.RUNNING: "RUNNING",
    _Status.DISCONNECT: "DISCONNECT",
    _Status.ERROR: "ERROR",
    _Status.RUNNING: "RUNNING",
}


StateTransitionTable: dict[ServerState, set[ServerState]] = {
    ServerState.UNINITIALIZED: {ServerState.ERROR, ServerState.CONNECTED},
    ServerState.CONNECTED: {ServerState.ERROR, ServerState.INITIALIZED},
    ServerState.INITIALIZED: {ServerState.ERROR, ServerState.RUNNING},
    ServerState.RUNNING: {
        ServerState.ERROR,
    },
    ServerState.ERROR: {
        ServerState.UNINITIALIZED,
    },
}


ExternalClientMessage = _Connect | _Status | _CommandResponse


class ExternalServer:
    def __init__(self, config: Config) -> None:
        self._running = False
        self._config = config
        self._event_queue = EventQueueSingleton()
        self._session = Session(self._config.mqtt_timeout)
        self._command_checker = CommandChecker(self._config.timeout)
        self._status_checker = StatusChecker(self._config.timeout)
        self._devices = KnownDevices()
        self._mqtt = MQTTClientAdapter(
            config.company_name,
            config.car_name,
            config.timeout,
            config.mqtt_address,
            config.mqtt_port,
        )
        self._modules: dict[int, _ServerModule] = dict()
        self._state: ServerState = ServerState.UNINITIALIZED
        for id_str, module_config in config.modules.items():
            module_id = int(id_str)
            car, company = config.car_name, config.company_name
            connection_check = partial(self._devices.any_supported_device_from_module, module_id)
            self._modules[module_id] = _ServerModule(
                module_id, company, car, module_config, connection_check=connection_check
            )

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
            _logger.info(f"Changing server's state from {self._state} to {state}")
            self._state = state

    def is_supported(self, device: _Device | DevicePy) -> bool:
        return self._devices.is_supported(device)

    def is_unsupported(self, device: _Device | DevicePy) -> bool:
        return self._devices.is_unsupported(device)

    def is_unknown(self, device: _Device | DevicePy) -> bool:
        return self._devices.is_unknown(device)

    def send_first_commands_and_check_responses(self) -> None:
        """Send command to all connected devices and check responses are returned."""
        no_cmd_devices = self._devices.list_supported()
        _logger.info("Generating and sending commands to all devices.")
        for module in self._modules:
            module_commands: list[tuple[bytes, _Device]] = []
            result: tuple | None = ()
            while result is not None:
                result = self._modules[module].thread.pop_command()
                if result is not None:
                    command_bytes, device = result
                    module_commands.append((command_bytes, device))

            for command_bytes, device in module_commands:
                if not self.is_device_in_list(
                    device, no_cmd_devices
                ) and self._devices.is_supported(device):
                    _logger.warning(
                        f"Command for device '{device_repr(device)}' returned from API more than once."
                    )
                elif not self.is_device_in_list(device, no_cmd_devices):
                    _logger.warning(
                        f"Command returned from module {module}'s API for not connected device, command won't be sent"
                    )
                else:
                    counter = self._command_checker.counter
                    cmd = _external_command(self._session.id, counter, device, command_bytes)
                    _logger.info(f"Sending Command message, counter: {counter}")
                    self._mqtt.publish(cmd)
                    self._command_checker.add_command(cmd.command, True)
                    try:
                        no_cmd_devices.remove(DevicePy.from_device(device))
                    except ValueError:
                        msg = f"Got command for unexpected device: {device_repr(device)}"
                        _logger.error(msg)
                        raise ConnectSequenceFailure(msg)

        for device_py in no_cmd_devices + self._devices.list_unsupported():
            counter = self._command_checker.counter
            device = device_py.to_device()
            cmd = _external_command(self._session.id, counter, device)
            _logger.warning(
                f"No command returned from API for device {device_repr(device)}, sending empty command for this device"
            )
            _logger.info(f"Sending Command message, counter: {counter}")
            self._mqtt.publish(cmd)
            self._command_checker.add_command(cmd.command, True)

        n_devices = self._devices.n_all
        _logger.info(f"Expecting {n_devices} command response messages")
        for iter in range(n_devices):
            _logger.info(f"Waiting for command response message {iter + 1} of {n_devices}")
            received_msg = self._mqtt._get_message()
            self._check_command_response(received_msg)
            assert received_msg is not None
            _logger.info(f"Received Command response message")
            response = received_msg.commandResponse
            commands = self._command_checker.acknowledge_and_pop_commands(response.messageCounter)
            for command, was_returned_from_api in commands:
                device = command.deviceCommand.device
                device_connected = self._devices.is_supported(device)
                if device_connected and was_returned_from_api:
                    cmd = command.deviceCommand
                    self._modules[cmd.device.module].api_client.command_ack(
                        cmd.commandData, cmd.device
                    )

    def _check_command_response(self, response: _ExternalClientMsg) -> None:
            if response is None or response == False:
                msg = "Command response message has not been received"
                _logger.error(msg)
                raise ConnectSequenceFailure(msg)
            if not response.HasField("commandResponse"):
                msg = "Received message is not a command response message."
                _logger.error(msg)
                raise ConnectSequenceFailure(msg)

    def set_tls(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        "Set tls security to mqtt client"
        self._mqtt.tls_set(ca_certs, certfile, keyfile)

    def start(self) -> None:
        self._start_module_threads()
        self._start_communication_loop()

    def stop(self, reason: str = "") -> None:
        """Stop the external server communication

        Stop the MQTT client event loop. Clear the modules.
        """
        msg = f"Stopping the external server."
        if reason:
            msg += f" Reason: {reason}"
        _logger.info(msg)
        self._running = False
        self._mqtt.stop()
        self._mqtt.disconnect()
        self._clear_modules()

    def _add_supported_device(self, device: _Device) -> None:
        assert isinstance(device, _Device)
        self._devices.add_supported(DevicePy.from_device(device))

    def _add_unsupported_device(self, device: _Device) -> None:
        self._devices.add_unsupported(DevicePy.from_device(device))

    def _start_communication_loop(self) -> None:
        self._running = True
        while self._running:
            self._single_communication_run()

    def _single_communication_run(self) -> None:
        try:
            self._initialize()
            self._normal_communication()
        except Exception as e:
            self._handle_communication_exception(e)
        finally:
            self._clear_context()

    def _initialize(self) -> None:
        try:
            self._ensure_connection_to_broker()
            self.state = ServerState.CONNECTED
            self._init_sequence()
            self.state = ServerState.INITIALIZED
        except Exception as e:
            self.state = ServerState.ERROR
            raise e

    def _handle_communication_exception(self, e: Exception) -> None:
        try:
            raise e
        except ConnectSequenceFailure as e:
            _logger.error(f"Connection sequence has failed.")
        except ConnectionRefusedError as e:
            address = self._mqtt.broker_address
            _logger.error(f"Unable to connect to broker ({address}. Trying again.")
        except StatusTimeout as e:
            _logger.error("Status messages have not been received in time")
        except CommandResponseTimeout as e:
            _logger.error("Command response message has not been received in time")
        except CommunicationException as e:
            _logger.error(e)
        except Exception as e:
            _logger.error(f"Unexpected error occurred: {e}")
        time.sleep(self._config.mqtt_client_connection_retry_period)

    def _ensure_connection_to_broker(self) -> None:
        if not self._mqtt.is_connected:
            _logger.info("Connecting to MQTT broker")
            e = self._mqtt.connect()
            if e is not None:
                raise ConnectionRefusedError(e)

    def _connect_device(self, device: _Device) -> int:
        code = self._modules[device.module].api_client.device_connected(device)
        if code == GeneralErrorCode.OK:
            _logger.info(f"Connected device unique identificator: {device_repr(device)}")
        else:
            _logger.error(f"Device {device_repr(device)} could not connect. Response code: {code}")
        return code

    def _status_response(self, status: _Status) -> _ExternalServerMsg:
        module = status.deviceStatus.device.module
        if module not in self._modules:
            _logger.warning(f"Module '{module}' is not supported")
        _logger.info(f"Sending Status response message, messageCounter: {status.messageCounter}")
        return _status_response(status.sessionId, status.messageCounter)

    def _start_module_threads(self) -> None:
        for _id in self._modules:
            self._modules[_id].thread.start()

    def _clear_context(self) -> None:
        self._mqtt.stop()
        self._command_checker.reset()
        self._session.stop()
        self._status_checker.reset()
        for device in self._devices.list_supported():
            self._modules[device.module_id].api_client.device_disconnected(
                DisconnectTypes.timeout, device.to_device()
            )
        self._devices.clear()
        self._event_queue.clear()

    def _clear_modules(self) -> None:
        for module in self._modules.values():
            module.thread.stop()
        for module in self._modules.values():
            module.thread.wait_for_join()
            code = module.api_client.destroy()
            if not code == GeneralErrorCode.OK:
                _logger.error(f"Module {module.id}: Error in destroy function. Return code: {code}")
        self._modules.clear()

    def _disconnect_device(self, disconnect_types: DisconnectTypes, device: _Device) -> None:
        _logger.warning(f"Disconnecting device {device_repr(device)}.")
        self._devices.remove(DevicePy.from_device(device))
        self._modules[device.module].api_client.device_disconnected(disconnect_types, device)

    def _handle_connect(self, msg_session_id: str) -> None:
        _logger.warning("Received Connect message when already connected")
        if self._session.id == msg_session_id:
            msg = "The ame session is attempting to connect multiple times"
            _logger.error(msg)
            raise CommunicationException(msg)
        self._publish_connect_response(_ConnectResponse.ALREADY_LOGGED)

    def _message_session_id_matches_current_session(
        self, message: _Connect | _Status | _CommandResponse
    ) -> bool:

        if message.sessionId != self._session.id:
            _logger.debug(
                f"Received status with session ID {message.sessionId}"
                f"does not match current session ID '{self.session_id}'"
            )
            return False
        return True

    def _check_received_status(self, status: _Status) -> None:
        self._log_new_status(status)
        if not self._message_session_id_matches_current_session(status):
            return
        else:
            self._reset_session_checker()
            self._status_checker.check(status)

    def _forward_status(self, status: _Status, module: _ServerModule) -> None:
        device, data = status.deviceStatus.device, status.deviceStatus.statusData
        module.api_client.forward_status(device, data)
        self._log_status_error(status, device)
        self._publish_status_response(status)

    def _handle_status(self, received_status: _Status) -> None:
        self._check_received_status(received_status)
        self._handle_checked_statuses()
        self._check_at_least_one_device_is_connected()

    def _handle_checked_statuses(self) -> None:
        while (status := self._status_checker.get()) is not None:
            module_and_dev = self._module_and_device_referenced_by_status(status)
            if not module_and_dev:
                continue
            module, device = module_and_dev
            if status.deviceState == _Status.CONNECTING:
                if self._devices.is_supported(device):
                    _logger.error(f"Device {device_repr(device)} is already connected.")
                else:
                    self._connect_device(device)
                    self._forward_status(status, module)
            elif status.deviceState == _Status.RUNNING:
                if self._devices.is_supported(device):
                    self._forward_status(status, module)
                else:
                    _logger.error(f"Device {device_repr(device)} is not connected.")
            elif status.deviceState == _Status.DISCONNECT:
                if self._devices.is_supported(device):
                    self._disconnect_device(DisconnectTypes.announced, device)
                    self._forward_status(status, module)
                else:
                    _logger.error(f"Device {device_repr(device)} is not connected.")
            else:
                self._log_status_error(status, device)
                self._publish_status_response(status)

    def _check_at_least_one_device_is_connected(self) -> None:
        if self._devices.n_supported == 0:
            msg = "All devices have been disconnected, restarting server."
            _logger.warning(msg)
            raise CommunicationException(msg)

    def _log_status_error(self, status: _Status, device: _Device) -> None:
        try:
            error_str = status.errorMessage.decode("utf-8")
        except:
            error_str = status.errorMessage
        if error_str:
            _logger.error(
                f"Status for device {device_repr(device)} contains error message: {status.errorMessage}"
            )

    def _publish_status_response(self, status: _Status) -> None:
        status_response = self._status_response(status)
        self._mqtt.publish(status_response)

    def _handle_command_response(self, command_response: _CommandResponse) -> None:
        _logger.info("Received command response")
        self._reset_session_checker_if_session_id_matches_current_session(
            command_response.sessionId
        )

        device_not_connected = (command_response.type == _CommandResponse.DEVICE_NOT_CONNECTED)
        commands = self._command_checker.acknowledge_and_pop_commands(
            command_response.messageCounter
        )
        for command, _ in commands:
            dev_cmd = command.deviceCommand
            module = self._modules[dev_cmd.device.module]
            module.api_client.command_ack(dev_cmd.commandData, dev_cmd.device)
            if device_not_connected and command.messageCounter == command_response.messageCounter:
                self._disconnect_device(DisconnectTypes.announced, dev_cmd.device)
                _logger.warning(
                    f"Command response announces that device {dev_cmd.device.deviceName} was disconnected"
                )

    def _handle_command(self, module_id: int) -> None:
        command_counter = self._command_checker.counter
        result = self._modules[module_id].thread.pop_command()
        if not result:
            return
        command, target_device = result
        ExternalServer.warn_if_device_not_in_list(
            self._devices.list_supported(),
            target_device,
            _logger,
            msg="Command for not connected device will not be sent.",
        )
        _logger.info(f"Sending Command message, messageCounter: {command_counter}")
        external_command = _external_command(
            self._session.id, command_counter, target_device, command
        )
        if len(external_command.command.deviceCommand.commandData) == 0:
            _logger.warning(
                f"Command data for device {external_command.command.deviceCommand.device.deviceName} is empty"
            )
        self._command_checker.add_command(external_command.command, True)
        if external_command.command.deviceCommand.device.module != module_id:
            _logger.warning(
                f"Device id returned from module {module_id}'s API has different module number"
            )
            if self._config.send_invalid_command:
                _logger.warning("Sending Command message with possibly invalid device")
                self._mqtt.publish(external_command)
            else:
                _logger.warning("The Command will not be sent")
                self._command_checker.acknowledge_and_pop_commands(
                    external_command.command.messageCounter
                )
        else:
            self._mqtt.publish(external_command)

    def _handle_connect_message_during_init(self, msg: _Connect) -> None:
        self._session.id = msg.sessionId
        devices = msg.devices
        for device in devices:
            if device.module in self._modules:
                self._modules[device.module].warn_if_device_unsupported(device)
                code = self._connect_device(device)
                if code == GeneralErrorCode.OK:
                    self._add_supported_device(device)
            else:
                ExternalServer.warn_module_not_supported(device.module, _logger, "Ignoring device.")
                self._add_unsupported_device(device)
        self._publish_connect_response(_ConnectResponse.OK)

    def _module_and_device_referenced_by_status(
        self, message: _Status
    ) -> tuple[_ServerModule, _Device] | None:
        if not isinstance(message, _Status):
            return None
        device = message.deviceStatus.device
        module = self._modules.get(device.module, None)
        if not module:
            _logger.warning(f"Received status for device from unknown module (ID={device.module}).")
            return None
        elif module.api_client.is_device_type_supported(device.deviceType):
            _logger.error(
                f"Device type {device.deviceType} not supported by module {device.module}"
            )
            return None
        return module, device

    def get_connect_message_and_respond(self) -> None:
        """Wait for a connect message from External Client.

        If there is no connect message, raise an exception.
        """
        msg = self._mqtt.get_connect_message()
        if msg is None:
            raise ConnectSequenceFailure("Connect message has not been received")
        self._handle_connect_message_during_init(msg)

    def get_all_first_statuses_and_respond(self) -> None:
        """Wait for first status messages from each of all known devices.

        The order of the status messages is expected to match the order of the devices in the connect message.

        Send response to each status message.
        """
        n = self._devices.n_all
        _counter_initialized = False
        for k in range(n):
            _logger.info(f"Waiting for status message {k + 1} out of {n}.")
            status_obj = self._mqtt.get_status()
            if status_obj is None:
                raise ConnectSequenceFailure("First status from device has not been received.")
            if not _counter_initialized:
                self._status_checker.initialize_counter(status_obj.messageCounter + 1)

            ExternalServer.check_device_is_in_connecting_state(status_obj.deviceState)
            status, device = status_obj.deviceStatus, status_obj.deviceStatus.device
            if not self._devices.is_supported(device):
                _logger.warning(f"Status from not connected device {device_repr(device)}.")
            self._log_new_status(status_obj)

            if self._devices.is_unsupported(device):
                module = self._modules[device.module]
                if status_obj.errorMessage:
                    module.api_client.forward_error_message(device, status_obj.errorMessage)
                module.api_client.forward_status(device, status.statusData)

            self._publish_status_response(status_obj)

    def _init_sequence(self) -> None:
        _logger.info("Starting the connect sequence.")
        try:
            self.get_connect_message_and_respond()
            self.get_all_first_statuses_and_respond()
            self.send_first_commands_and_check_responses()
            self._event_queue.clear()
            _logger.info("Connect sequence has finished succesfully")
        except Exception as e:
            _logger.warning("Connection sequence has not been started.")
            raise ConnectSequenceFailure(f"Connection sequence has failed. {e}")

    def _log_new_status(self, status: _Status) -> None:
        info = f"Received Status (counter={status.messageCounter})"
        if len(status.errorMessage) > 0:
            info += f" error: {status.errorMessage}"
        _logger.info(info)

    def _normal_communication(self) -> None:
        if not self.state == ServerState.INITIALIZED:
            raise ConnectSequenceFailure(
                "Cannot run normal communication without succesfull init sequence."
            )
        self._session.start()
        self.state = ServerState.RUNNING
        while True:
            event = self._event_queue.get()
            if event.event == EventType.RECEIVED_MESSAGE:
                received_msg = self._mqtt._get_message(ignore_timeout=False)
                if received_msg is not None:
                    if received_msg is False:
                        raise CommunicationException("Unexpected disconnection")

                    elif received_msg.HasField("connect"):
                        self._handle_connect(received_msg.connect.sessionId)

                    elif received_msg.HasField("status"):
                        self._handle_status(received_msg.status)

                    elif received_msg.HasField("commandResponse"):
                        self._handle_command_response(received_msg.commandResponse)
            elif event.event == EventType.MQTT_BROKER_DISCONNECTED:
                raise CommunicationException("Unexpected disconnection")
            elif event.event == EventType.TIMEOUT_OCCURRED:
                if event.data == TimeoutType.SESSION_TIMEOUT:
                    raise SessionTimeout()
                elif event.data == TimeoutType.MESSAGE_TIMEOUT:
                    raise StatusTimeout()
                elif event.data == TimeoutType.COMMAND_TIMEOUT:
                    raise CommandResponseTimeout()
                else:
                    _logger.error(
                        "Internal error: Received Event TimeoutOccurred without TimeoutType"
                    )
            elif event.event == EventType.COMMAND_AVAILABLE:
                if isinstance(event.data, int):
                    self._handle_command(event.data)
                else:
                    _logger.error(
                        "Internal error: Received Event CommandAvailable without module number"
                    )

    def _publish_connect_response(self, response_type: int) -> None:
        _logger.info(f"Sending Connect respons. Response type: {response_type}")
        msg = _connect_response(self._session.id, response_type)
        self._mqtt.publish(msg)

    def _reset_session_checker_if_session_id_matches_current_session(
        self, msg_session_id: str
    ) -> None:
        if self._session.id == msg_session_id:
            self._reset_session_checker()

    def _reset_session_checker(self) -> None:
        self._session.reset()

    @staticmethod
    def check_device_is_in_connecting_state(state_enum: _Status.DeviceState) -> None:
        if state_enum != _Status.CONNECTING:
            state = DeviceStatusName.get(state_enum, str(state_enum))
            connecting_state = DeviceStatusName[_Status.CONNECTING]
            msg = (
                f"First status from device must contain {connecting_state} state, received {state}."
            )
            _logger.error(msg)
            raise ConnectSequenceFailure(msg)

    @staticmethod
    def is_device_in_list(device: _Device | DevicePy, device_list: list[DevicePy]) -> bool:
        """Check if the device is in the list.

        The device is in the list if the list contains a device with the same module, type, and role.
        """
        return device in device_list

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
