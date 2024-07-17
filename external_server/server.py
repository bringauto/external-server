import logging.config
import time
import sys
from logging import Logger as _Logger
from typing import Optional
import json
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import (  # type: ignore
    CommandResponse as _CommandResponse,
    Connect as _Connect,
    ConnectResponse as _ConnectResponse,
    ExternalServer as _ExternalServerMsg,
    Status as _Status,
)
from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device
)
from external_server.checkers import CommandChecker, SessionTimeoutChecker, StatusOrderChecker
from external_server.models.exceptions import (
    ConnectSequenceException,
    CommunicationException,
    StatusTimeOutExc,
    ClientDisconnectedExc,
    CommandResponseTimeOutExc,
)
from external_server.server_message_creator import (
    connect_response as _connect_response,
    status_response as _status_response,
    external_command as _external_command,
)
from external_server.adapters.mqtt_client import MQTTClientAdapter
from external_server.utils import check_file_exists, device_repr
from external_server.adapters.api_client import ExternalServerApiClient
from external_server.command_waiting_thread import CommandWaitingThread
from external_server.config import Config
from external_server.models.structures import (
    GeneralErrorCodes,
    DisconnectTypes,
    TimeoutType,
    DevicePy as DevicePy,
)
from external_server.models.event_queue import EventQueueSingleton, EventType


_logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


class ExternalServer:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._session_id = ""
        self._event_queue = EventQueueSingleton()
        self._session_checker = SessionTimeoutChecker(self._config.mqtt_timeout)
        self._command_checker = CommandChecker(self._config.timeout)
        self._status_order_checker = StatusOrderChecker(self._config.timeout)
        self._connected_devices: list[DevicePy] = list()
        self._not_connected_devices: list[DevicePy] = list()
        self._mqtt_client = MQTTClientAdapter(
            self._config.company_name,
            self._config.car_name,
            config.timeout,
            self._config.mqtt_address,
            self._config.mqtt_port
        )
        self._running = False
        self._modules: dict[int, ExternalServerApiClient] = dict()
        self._modules_command_threads: dict[int, CommandWaitingThread] = dict()
        for module_number, module in config.modules.items():
            self._modules[int(module_number)] = ExternalServerApiClient(
                module, self._config.company_name, self._config.car_name
            )
            self._modules[int(module_number)].init()
            if not self._modules[int(module_number)].device_initialized():
                _logger.error(
                    f"Module {module_number}: Error occurred in init function. Check the configuration file."
                )
                raise RuntimeError(
                    f"Module {module_number}: Error occurred in init function. Check the configuration file."
                )
            self._check_module_number_from_config_is_module_id(module_number)
        _logger.debug("External server has been initialized.")

    @property
    def connected_devices(self) -> list[DevicePy]:
        return self._connected_devices.copy()

    @property
    def n_of_all_devices(self) -> int:
        return len(self._connected_devices) + len(self._not_connected_devices)

    @property
    def not_connected_devices(self) -> list[DevicePy]:
        return self._not_connected_devices.copy()

    @property
    def modules(self) -> dict[int, ExternalServerApiClient]:
        return self._modules.copy()

    @property
    def mqtt_client(self) -> MQTTClientAdapter:
        return self._mqtt_client

    @property
    def session_id(self) -> str:
        return self._session_id

    def set_tls(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        "Set tls security to mqtt client"
        if not check_file_exists(ca_certs):
            raise FileNotFoundError(ca_certs)
        if not check_file_exists(certfile):
            raise FileNotFoundError(certfile)
        if not check_file_exists(keyfile):
            raise FileNotFoundError(keyfile)
        self._mqtt_client.tls_set(ca_certs, certfile, keyfile)

    def start(self) -> None:
        self._start_module_threads()
        self._communicate()

    def stop(self, reason: str = "") -> None:
        """Stop the external server communication

        Stop the MQTT client event loop. Clear the modules.
        """
        msg = f"Stopping the external server."
        if reason:
            msg += f" Reason: {reason}"
        _logger.info(msg)
        self._running = False
        self._mqtt_client.stop()
        self._clear_modules()


    def _add_connected_device(self, device: _Device) -> None:
        assert isinstance(device, _Device)
        self._connected_devices.append(DevicePy.from_device(device))

    def _add_not_connected_device(self, device: _Device) -> None:
        self._not_connected_devices.append(DevicePy.from_device(device))

    def _adjust_connection_state_of_module_thread(self, device_module: int, connected: bool):
        for device in self._connected_devices:
            if device_module == device.module_id:
                # There is connected device with same module, no need to adjust the module thread
                return
        if connected:
            self._modules_command_threads[device_module].connection_established = True
        else:
            self._modules_command_threads[device_module].connection_established = False

    def _check_module_number_from_config_is_module_id(self, module_key: str) -> None:
        real_mod_number = self._modules[int(module_key)].get_module_number()
        if real_mod_number != int(module_key):
            msg = f"Module number '{real_mod_number}' returned from API does not match module number {int(module_key)} in config."
            _logger.error(msg)
            raise RuntimeError(msg)
        self._modules_command_threads[int(module_key)] = CommandWaitingThread(
            self._modules[int(module_key)]
        )

    def _communicate(self) -> None:
        self._running = True
        while self._running:
            try:
                if not self._mqtt_client.is_connected:
                    _logger.info("Connecting to MQTT broker")
                    self._mqtt_client.connect()
                    self._mqtt_client._start()
                self._run_init_sequence()
                self._normal_communication()
            except ConnectSequenceException as e:
                _logger.error(f"Connection sequence has failed.")
            except ConnectionRefusedError:
                _logger.error(
                    f"Unable to connect to MQTT broker on {self._config.mqtt_address}:{self._config.mqtt_port}, trying again"
                )
                time.sleep(self._config.mqtt_client_connection_retry_period)
            except ClientDisconnectedExc as e:
                # if no message has been received for given time
                _logger.error("Client timed out")
            except StatusTimeOutExc:
                _logger.error("Status messages have not been received in time")
            except CommandResponseTimeOutExc:
                _logger.error("Command response message has not been received in time")
            except CommunicationException as e:
                _logger.error(e)
            except Exception as e:
                _logger.error(f"Unexpected error occurred: {e}")
            finally:
                time.sleep(self._config.mqtt_client_connection_retry_period)
                self._clear_context()

    def _connect_device(self, device: _Device) -> int:
        ExternalServer._remove_device_priority(device)
        code = self._modules[device.module].device_connected(device)
        self._adjust_connection_state_of_module_thread(device.module, True)
        if code == GeneralErrorCodes.OK:
            _logger.info(
                f"Connected device unique identificator: {device.module}/{device.deviceType}/{device.deviceRole} named as {device.deviceName}"
            )
        else:
            _logger.error(
                f"Device with unique identificator: {device.module}/{device.deviceType}/{device.deviceRole} "
                f"could not be connected. Response code from API: {code}"
            )
        return code

    def _create_status_response(self, status: _Status) -> _ExternalServerMsg:
        module = status.deviceStatus.device.module
        if module not in self._modules:
            _logger.warning(f"Module '{module}' is not supported")
        _logger.info(
            f"Sending Status response message, messageCounter: {status.messageCounter}"
        )
        return _status_response(status.sessionId, status.messageCounter)

    def _publish_status_response(self, status: _Status) -> None:
        msg = self._create_status_response(status)
        self._mqtt_client.publish(msg)

    def _start_module_threads(self) -> None:
        for module_number in self._modules:
            self._modules_command_threads[module_number].start()

    def _warn_if_device_not_supported_by_module(self, device: _Device) -> None:
        if not self._modules[device.module].is_device_type_supported(device.deviceType):
            module_id = device.module
            _logger.warning(
                f"Device of type '{device.deviceType}' is not supported by module with ID={module_id}"
                "and probably will not work properly."
            )

    def _clear_context(self) -> None:
        self._mqtt_client.stop()
        self._command_checker.reset()
        self._session_checker.stop()
        self._status_order_checker.reset()
        for device in self._connected_devices:
            code = self._modules[device.module_id].device_disconnected(
                DisconnectTypes.timeout, device.to_device()
            )
            ExternalServer._check_device_disconnected_code(device.module_id, code, _logger)
        for command_thread in self._modules_command_threads.values():
            command_thread.connection_established = False
        self._connected_devices.clear()
        self._not_connected_devices.clear()
        self._event_queue.clear()

    def _clear_modules(self) -> None:
        for module_number in self._modules_command_threads:
            self._modules_command_threads[module_number].stop()
        for module_num in self._modules:
            self._modules_command_threads[module_num].wait_for_join()
            code = self._modules[module_num].destroy()
            if not code == GeneralErrorCodes.OK:
                _logger.error(
                    f"Module {module_num}: Error in destroy function. Return code: {code}"
                )
        self._modules.clear()

    def _disconnect_device(self, disconnect_types: DisconnectTypes, device: _Device) -> None:
        ExternalServer._remove_device_priority(device)
        try:
            self._connected_devices.remove(DevicePy.from_device(device))
        except ValueError:
            return
        assert isinstance(device, _Device)
        rc = self._modules[device.module].device_disconnected(disconnect_types, device)
        ExternalServer._check_device_disconnected_code(device.module, rc, _logger)
        self._adjust_connection_state_of_module_thread(device.module, False)

    def _handle_connect(self, received_msg_session_id: str) -> None:
        _logger.warning("Received Connect message when already connected")
        if self._session_id == received_msg_session_id:
            msg = "Same session is attempting to connect multiple times"
            _logger.error(msg)
            raise CommunicationException(msg)
        self._publish_connect_response(_ConnectResponse.ALREADY_LOGGED)

    def _handle_status(self, received_status: _Status) -> None:
        _logger.info(
            f"Received Status message, messageCounter: {received_status.messageCounter}"
            f" error: {received_status.errorMessage}"
        )
        self._reset_session_checker_if_session_id_is_ok(received_status.sessionId)
        self._status_order_checker.check(received_status)

        while (status := self._status_order_checker.get_status()) is not None:
            device = status.deviceStatus.device
            if device.module not in self._modules:
                _logger.warning(
                    f"Received status for device with unknown module number {device.module}"
                )
                continue
            if self._modules[device.module].is_device_type_supported(device.deviceType):
                _logger.error(
                    f"Device type {device.deviceType} not supported by module {device.module}"
                )
                continue

            if status.deviceState == _Status.RUNNING:
                if not self.is_device_in_list(device, self._connected_devices):
                    _logger.error(f"Device {device_repr(device)} is not connected")
                    continue
                code = self._modules[device.module].forward_status(
                    device, status.deviceStatus.statusData
                )
                ExternalServer._check_forward_status_code(device.module, code, _logger)
            elif status.deviceState == _Status.CONNECTING:
                if self.is_device_in_list(device, self._connected_devices):
                    _logger.error(f"Device {device_repr(device)} is already connected")
                    continue
                self._connect_device(device)
                code = self._modules[device.module].forward_status(
                    device, status.deviceStatus.statusData
                )
                ExternalServer._check_forward_status_code(device.module, code, _logger)
            elif status.deviceState == _Status.DISCONNECT:
                if not self.is_device_in_list(device, self._connected_devices):
                    _logger.error(f"Device {device_repr(device)} is not connected")
                    continue
                code = self._modules[device.module].forward_status(
                    device, status.deviceStatus.statusData
                )
                ExternalServer._check_forward_status_code(device.module, code, _logger)
                self._disconnect_device(DisconnectTypes.announced, device)
                _logger.warning(
                    f"Status announces that device {device.deviceName} was disconnected"
                )

            if len(status.errorMessage) > 0:
                _logger.error(
                    f"Status for device {device_repr(device)} contains error message"
                )

            status_response = self._create_status_response(status)
            self._mqtt_client.publish(status_response)
            if len(self._connected_devices) == 0:
                msg = "All devices have been disconnected, restarting server"
                _logger.warning(msg)
                raise CommunicationException(msg)

    def _handle_command_response(self, command_response: _CommandResponse) -> None:
        _logger.info("Received command response")
        self._reset_session_checker_if_session_id_is_ok(command_response.sessionId)

        device_not_connected = command_response.type == _CommandResponse.DEVICE_NOT_CONNECTED
        commands = self._command_checker.acknowledge_and_pop_commands(
            command_response.messageCounter
        )
        for command, _ in commands:
            rc = self._modules[command.deviceCommand.device.module].command_ack(
                command.deviceCommand.commandData, command.deviceCommand.device
            )
            ExternalServer._check_command_ack_code(
                command.deviceCommand.device.module, rc, _logger
            )
            if device_not_connected and command.messageCounter == command_response.messageCounter:
                self._disconnect_device(DisconnectTypes.announced, command.deviceCommand.device)
                _logger.warning(
                    f"Command response announces that device {command.deviceCommand.device.deviceName} was disconnected"
                )

    def _handle_command(self, module_num: int) -> None:
        command_counter = self._command_checker.counter
        result = self._modules_command_threads[module_num].pop_command()
        if not result:
            return
        command, target_device = result
        ExternalServer.warn_if_device_not_in_list(
            self._connected_devices,
            target_device,
            _logger,
            msg="Command for not connected device will not be sent."
        )
        _logger.info(f"Sending Command message, messageCounter: {command_counter}")
        external_command = _external_command(self._session_id, command_counter, target_device, command)
        if len(external_command.command.deviceCommand.commandData) == 0:
            _logger.warning(
                f"Command data for device {external_command.command.deviceCommand.device.deviceName} is empty"
            )
        self._command_checker.add_command(external_command.command, True)
        if external_command.command.deviceCommand.device.module != module_num:
            _logger.warning(
                f"Device id returned from module {module_num}'s API has different module number"
            )
            if self._config.send_invalid_command:
                _logger.warning("Sending Command message with possibly invalid device")
                self._mqtt_client.publish(external_command)
            else:
                _logger.warning("The Command will not be sent")
                self._command_checker.acknowledge_and_pop_commands(
                    external_command.command.messageCounter
                )
        else:
            self._mqtt_client.publish(external_command)

    def _handle_connect_message(self, msg: _Connect) -> None:
        self._session_id = msg.sessionId
        devices = msg.devices
        for device in devices:
            if self._is_module_supported(device.module):
                self._warn_if_device_not_supported_by_module(device)
                code = self._connect_device(device)
                if code==GeneralErrorCodes.OK:
                    self._add_connected_device(device)
            else:
                ExternalServer.warn_module_not_supported(device.module, _logger, msg="Ignoring device.")
                self._add_not_connected_device(device)
        self._publish_connect_response(_ConnectResponse.OK)

    def get_connect_message_and_respond(self) -> None:
        """Wait for a connect message from External Client.

        If there is no connect message, raise an exception.
        """
        msg = self.get_connect_message(self._mqtt_client, _logger)
        if msg is None:
            raise ConnectSequenceException
        else:
            self._handle_connect_message(msg)

    def get_first_statuses_and_respond(self) -> None:
        """Wait for first status messages from each of all known devices.

        The order of the status messages is expected to match the order of the devices in the connect message.

        Send response to each status message.
        """
        n_devices = self.n_of_all_devices
        for k in range(n_devices):
            _logger.info(f"Waiting for status message {k + 1} out of {n_devices}.")
            status_obj = ExternalServer.get_status(self._mqtt_client, _logger)
            if status_obj is None:
                raise ConnectSequenceException
            status, device = status_obj.deviceStatus, status_obj.deviceStatus.device
            ExternalServer.warn_if_device_not_in_list(
                self._connected_devices,
                device,
                _logger,
                msg="Received status from not connected device."
            )
            ExternalServer.check_connecting_state(status_obj.deviceState, _logger)
            self._status_order_checker.check(status_obj)
            self._status_order_checker.get_status()  # Checked status is not needed in Init sequence
            self._log_new_status(status_obj)

            if device not in self._not_connected_devices:
                if status_obj.errorMessage:
                    code = self._modules[device.module].forward_error_message(
                        device, status_obj.errorMessage
                    )
                    if code != GeneralErrorCodes.OK:
                        _logger.warning(
                            f"Module '{device.module}': Error occurred in forward_error_message function. Return code: {code}"
                        )
                code = self._modules[device.module].forward_status(device, status.statusData)
                ExternalServer._check_forward_status_code(device.module, code, _logger)
            self._publish_status_response(status_obj)

    def send_first_commands_and_check_responses(self) -> None:
        """Send command to all connected devices and check responses are returned."""
        no_cmd_devices = self._connected_devices.copy()
        _logger.info("Generating and sending commands to all devices.")
        for module in self._modules:
            module_commands: list[tuple[bytes, _Device]] = []
            result: tuple | None = ()
            while result is not None:
                result = self._modules_command_threads[module].pop_command()
                if result is not None:
                    command_bytes, target_device = result
                    module_commands.append((command_bytes, target_device))

            for command_bytes, target_device in module_commands:
                if not self.is_device_in_list(target_device, no_cmd_devices) \
                and self.is_device_in_list(target_device, self._connected_devices):
                    _logger.warning(
                        f"Command for {target_device.deviceName} device was returned from API more than once"
                    )
                elif not self.is_device_in_list(target_device, no_cmd_devices):
                    _logger.warning(
                        f"Returned command returned from module {module}'s API for not connected device, command won't be sent"
                    )
                else:
                    command_counter = self._command_checker.counter
                    cmd = _external_command(
                        self._session_id, command_counter, target_device, command_bytes
                    )
                    _logger.info(f"Sending Command message, messageCounter: {command_counter}")
                    self._mqtt_client.publish(cmd)
                    self._command_checker.add_command(cmd.command, True)
                    try:
                        no_cmd_devices.remove(DevicePy.from_device(target_device))
                    except ValueError:
                        _logger.error(
                            f"Received command for unexpected device in connect sequence:"
                            f"{target_device.module}/{target_device.deviceType}/{target_device.deviceRole} named as {target_device.deviceName}"
                        )
                        raise ConnectSequenceException()

        for device_py in no_cmd_devices + self._not_connected_devices:
            command_counter = self._command_checker.counter
            device = device_py.to_device()
            cmd = _external_command(self._session_id, command_counter, device)
            _logger.warning(
                f"No command was returned from API for device {device.deviceName}, sending empty command for this device"
            )
            _logger.info(f"Sending Command message, messageCounter: {command_counter}")
            self._mqtt_client.publish(cmd)
            self._command_checker.add_command(cmd.command, True)

        n_devices = self.n_of_all_devices
        _logger.info(f"Expecting {n_devices} command response messages")
        for iter in range(n_devices):
            _logger.info(
                f"Waiting for command response message {iter + 1} of {n_devices}"
            )
            received_msg = self._mqtt_client.get_message()
            if received_msg is None or received_msg == False:
                _logger.error("Command response message has not been received")
                raise ConnectSequenceException()
            if not received_msg.HasField("commandResponse"):
                _logger.error(f"Received message is not a command response message. Message: {received_msg}")
                raise ConnectSequenceException()
            _logger.info(f"Received Command response message")
            commands = self._command_checker.acknowledge_and_pop_commands(
                received_msg.commandResponse.messageCounter
            )
            for command, was_returned_from_api in commands:
                device = command.deviceCommand.device
                device_connected = DevicePy.from_device(device) in self._connected_devices
                if device_connected and was_returned_from_api:
                    rc = self._modules[command.deviceCommand.device.module].command_ack(
                        command.deviceCommand.commandData, command.deviceCommand.device
                    )
                    ExternalServer._check_command_ack_code(
                        command.deviceCommand.device.module, rc, _logger
                    )


    def _is_module_supported(self, module_id: int) -> bool:
        return module_id in self._modules

    def _log_new_status(self, status: _Status) -> None:
        info = f"Received Status message, messageCounter: {status.messageCounter}"
        if len(status.errorMessage) > 0:
            info += f" error: {status.errorMessage}"
        _logger.info(info)

    def _normal_communication(self) -> None:
        self._session_checker.start()
        while True:
            event = self._event_queue.get()
            if event.event == EventType.RECEIVED_MESSAGE:
                received_msg = self._mqtt_client.get_message(ignore_timeout=True)
                if received_msg is False:
                    raise CommunicationException("Unexpected disconnection")
                elif received_msg is not None:
                    if received_msg.HasField("connect"):
                        self._handle_connect(received_msg.connect.sessionId)

                    elif received_msg.HasField("status"):
                        self._handle_status(received_msg.status)

                    elif received_msg.HasField("commandResponse"):
                        self._handle_command_response(received_msg.commandResponse)
            elif event.event == EventType.MQTT_BROKER_DISCONNECTED:
                raise CommunicationException("Unexpected disconnection")
            elif event.event == EventType.TIMEOUT_OCCURRED:
                if event.data == TimeoutType.SESSION_TIMEOUT:
                    raise ClientDisconnectedExc()
                elif event.data == TimeoutType.MESSAGE_TIMEOUT:
                    raise StatusTimeOutExc()
                elif event.data == TimeoutType.COMMAND_TIMEOUT:
                    raise CommandResponseTimeOutExc()
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
        msg = _connect_response(self._session_id, response_type)
        self._mqtt_client.publish(msg)

    def _reset_session_checker_if_session_id_is_ok(self, msg_session_id: str) -> None:
        if self._session_id == msg_session_id:
            self._session_checker.reset()

    def _run_init_sequence(self) -> None:
        _logger.info("Starting the connect sequence.")
        try:
            self.get_connect_message_and_respond()
            self.get_first_statuses_and_respond()
            self.send_first_commands_and_check_responses()
            self._event_queue.clear()
            _logger.info("Connect sequence has finished succesfully")
        except Exception as e:
            _logger.warning("Connection sequence has not been started.")
            raise ConnectSequenceException(f"Connection sequence has failed. {e}")

    @staticmethod
    def check_connecting_state(state: _Status.DeviceState, logger: Optional[_Logger] = None) -> None:
        if state == _Status.CONNECTING:
            return
        else:
            if logger:
                logger.error(
                    f"Expected connecting device (state={_Status.CONNECTING}),"
                    f"received {state}"
                )
            raise ConnectSequenceException

    @staticmethod
    def _check_forward_status_code(module_id: int, code: int, logger: _Logger) -> None:
        if code != GeneralErrorCodes.OK:
            logger.error(f"Module {module_id}: Error in forward_status function, code: {code}")

    @staticmethod
    def _check_device_disconnected_code(module_id: int, code: int, logger: _Logger) -> None:
        if code != GeneralErrorCodes.OK:
            logger.error(f"Module {module_id}: Error in device_disconnected function, code: {code}")

    @staticmethod
    def _check_command_ack_code(module_id: int, code: int, logger: _Logger) -> None:
        if code != GeneralErrorCodes.OK:
            logger.error(f"Module {module_id}: Error in command_ack function, code: {code}")

    @staticmethod
    def get_connect_message(mqtt_client: MQTTClientAdapter, logger: logging.Logger) -> _Connect | None:
        """Get expected connect message from mqtt client.

        Raise an exception if the message is not received or is not a connect message.
        """
        logger.info("Expecting a connect message")
        msg = mqtt_client.get_message()
        while msg is False:
            logger.debug("Found disconnect message from connected client. Repeating message retrieval")
            msg = mqtt_client.get_message()
        if msg is None:
            logger.error("Connect message has not been received")
            return None
        elif not msg.HasField("connect"):
            logger.error("Received message is not a connect message")
            return None
        logger.info("Connect message has been received")
        return msg.connect

    @staticmethod
    def get_status(mqtt_client: MQTTClientAdapter, logger: logging.Logger) -> _Status | None:
        """Get expected status message from mqtt client.

        Raise an exception if the message is not received or is not a status message.
        """
        msg = mqtt_client.get_message()
        if msg is None or msg == False:
            logger.error("Status message has not been received")
            return None
        if not msg.HasField("status"):
            logger.error("Received message is not a status message")
            return None
        return msg.status

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

    @staticmethod
    def _remove_device_priority(device: _Device) -> None:
        """Set priority to zero - the external server must ignore the priority."""
        device.priority = 0
