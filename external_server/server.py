import logging
import time
import sys
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import (  # type: ignore
    CommandResponse as _CommandResponse,
    ConnectResponse as _ConnectResponse,
    ExternalClient as _ExternalClientMsg,
    ExternalServer as _ExternalServerMsg,
    Status as _Status
)
from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device,
    DeviceStatus as _DeviceStatus
)
from external_server.checkers import (
    CommandChecker,
    SessionTimeoutChecker,
    StatusOrderChecker
)
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
    external_command as _external_command
)
from external_server.clients.mqtt_client import MQTTClient
from external_server.utils import check_file_exists, device_repr
from external_server.clients.api_client import ExternalServerApiClient
from external_server.command_waiting_thread import CommandWaitingThread
from external_server.config import Config
from external_server.models.structures import (
    GeneralErrorCodes,
    DisconnectTypes,
    TimeoutType,
    DevicePy as DevicePy
)
from external_server.models.event_queue import EventQueueSingleton, EventType


class ExternalServer:
    def __init__(self, config: Config) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._session_id = ""
        self._event_queue = EventQueueSingleton()
        self._session_checker = SessionTimeoutChecker(self._config.mqtt_timeout)
        self._command_checker = CommandChecker(self._config.timeout)
        self._status_order_checker = StatusOrderChecker(self._config.timeout)
        self._connected_devices: list[DevicePy] = list()
        self._not_connected_devices: list[DevicePy] = list()
        self._mqtt_client = MQTTClient(self._config.company_name, self._config.car_name)
        self._running = False

        self._modules: dict[int, ExternalServerApiClient] = dict()
        self._modules_command_threads: dict[int, CommandWaitingThread] = dict()
        for module_number, module in config.modules.items():
            self._modules[int(module_number)] = ExternalServerApiClient(
                module, self._config.company_name, self._config.car_name
            )
            self._modules[int(module_number)].init()
            if not self._modules[int(module_number)].device_initialized():
                self._logger.error(
                    f"Module {module_number}: Error occurred in init function. Check the configuration file."
                )
                raise RuntimeError(f"Module {module_number}: Error occurred in init function. Check the configuration file.")
            self._check_module_number_from_config_is_module_id(module_number)

    @property
    def connected_devices(self) -> list[DevicePy]:
        return self._connected_devices.copy()

    @property
    def not_connected_devices(self) -> list[DevicePy]:
        return self._not_connected_devices.copy()

    @property
    def modules(self) -> dict[int, ExternalServerApiClient]:
        return self._modules.copy()

    @property
    def mqtt_client(self) -> MQTTClient:
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
        self._mqtt_client.set_tls(ca_certs, certfile, keyfile)

    def start(self) -> None:
        self._mqtt_client.set_up_callbacks()
        for module_number in self._modules:
            self._modules_command_threads[module_number].start()

        self._running = True
        while self._running:
            try:
                if not self._mqtt_client.is_connected_to_broker:
                    self._mqtt_client.connect_to_broker(self._config.mqtt_address, self._config.mqtt_port)
                    self._mqtt_client.start()
                self._run_init_sequence()
                self._normal_communication()
            except ConnectSequenceException:
                self._logger.error("Connect sequence failed")
            except ConnectionRefusedError:
                self._logger.error(
                    f"Unable to connect to MQTT broker on {self._config.mqtt_address}:{self._config.mqtt_port}, trying again"
                )
                time.sleep(self._config.mqtt_client_connection_retry_period)
            except ClientDisconnectedExc:  # if 30 seconds any message has not been received
                self._logger.error("Client timed out")
            except StatusTimeOutExc:
                self._logger.error("Status messages have not been received in time")
            except CommandResponseTimeOutExc:
                self._logger.error("Command response message has not been received in time")
            except CommunicationException:
                pass
            except Exception as e:
                self._logger.error(f"Unexpected error occurred: {e}")
                time.sleep(self._config.mqtt_client_connection_retry_period)
            finally:
                self._clear_context()

    def stop(self, reason: str = "") -> None:
        """Stop the external server communication

        Stop the MQTT client event loop. Clear the modules.
        """
        self._running = False
        self._mqtt_client.stop()
        self._clear_modules()
        if reason:
            reason = f" ({reason})"
        self._logger.info(f"External server stopped{reason}.")


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

    def _check_forward_status_rc(self, module_num: int, rc: int) -> None:
        if rc != GeneralErrorCodes.OK:
            self._logger.error(
                f"Module {module_num}: Error occurred in forward_status function, rc: {rc}"
            )

    def _check_device_disconnected_rc(self, module_num: int, rc: int) -> None:
        if rc != GeneralErrorCodes.OK:
            self._logger.error(
                f"Module {module_num}: Error occurred in device_disconnected function, rc: {rc}"
            )

    def _check_command_ack_rc(self, module_num: int, rc: int) -> None:
        if rc != GeneralErrorCodes.OK:
            self._logger.error(
                f"Module {module_num}: Error occurred in command_ack function, rc: {rc}"
            )

    def _check_module_number_from_config_is_module_id(self, module_key: str) -> None:
        real_mod_number = self._modules[int(module_key)].get_module_number()
        if real_mod_number != int(module_key):
            msg = f"Module number {real_mod_number} returned from API does not match module number {int(module_key)} in config."
            self._logger.error(msg)
            raise RuntimeError(msg)
        self._modules_command_threads[int(module_key)] = CommandWaitingThread(
            self._modules[int(module_key)]
        )

    def _create_status_response(self, status: _Status) -> _ExternalServerMsg:
        module = status.deviceStatus.device.module
        if module not in self._modules:
            self._logger.warning(f"Module {module} is not supported")
        self._logger.info(
            f"Sending Status response message, messageCounter: {status.messageCounter}"
        )
        return _status_response(status.sessionId, status.messageCounter)

    def _connect_device(self, device: _Device) -> int:
        ExternalServer._remove_device_priority(device)
        rc = self._modules[device.module].device_connected(device)
        self._adjust_connection_state_of_module_thread(device.module, True)
        if rc == GeneralErrorCodes.OK:
            self._logger.info(
                f"Connected device unique identificator: {device.module}/{device.deviceType}/{device.deviceRole} named as {device.deviceName}"
            )
            self._add_connected_device(device)
        else:
            self._logger.error(
                f"Device with unique identificator: {device.module}/{device.deviceType}/{device.deviceRole} "
                f"could not be connected, because response from API: {rc}"
            )
        return rc

    def _log_warning_if_device_not_supported_by_module(self, device: _Device) -> None:
        if not self._modules[device.module].is_device_type_supported(device.deviceType):
            module_id = device.module
            self._logger.warning(
                f"Device of type '{device.deviceType}' is not supported by module with ID={module_id}"
                "and probably will not work properly."
            )

    def _clear_context(self) -> None:
        self._mqtt_client.stop()
        self._command_checker.reset()
        self._session_checker.stop()
        self._status_order_checker.reset()
        for device in self._connected_devices:
            rc = self._modules[device.module_id].device_disconnected(
                DisconnectTypes.timeout, device.to_device()
            )
            self._check_device_disconnected_rc(device.module_id, rc)
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
            if not code==GeneralErrorCodes.OK:
                self._logger.error(f"Module {module_num}: Error in destroy function. Return code: {code}")
        self._modules.clear()

    def _disconnect_device(self, disconnect_types: DisconnectTypes, device: _Device) -> None:
        ExternalServer._remove_device_priority(device)
        try:
            self._connected_devices.remove(DevicePy.from_device(device))
        except ValueError:
            return
        assert isinstance(device, _Device)
        rc = self._modules[device.module].device_disconnected(disconnect_types, device)
        self._check_device_disconnected_rc(device.module, rc)
        self._adjust_connection_state_of_module_thread(device.module, False)

    def _handle_connect(self, received_msg_session_id: str) -> None:
        self._logger.warning("Received Connect message when already connected")
        if self._session_id == received_msg_session_id:
            self._logger.error("Same session is attempting to connect multiple times")
            raise CommunicationException()
        self._publish_connect_response(_ConnectResponse.ALREADY_LOGGED)

    def _handle_status(self, received_status:_Status) -> None:
        self._logger.info(
            f"Received Status message, messageCounter: {received_status.messageCounter}"
            f" error: {received_status.errorMessage}"
        )
        self._reset_session_checker_if_session_id_is_ok(received_status.sessionId)
        self._status_order_checker.check(received_status)

        while (status := self._status_order_checker.get_status()) is not None:
            device = status.deviceStatus.device

            if (device.module not in self._modules):
                self._logger.warning(
                    f"Received status for device with unknown module number {device.module}"
                )
                continue
            if self._modules[device.module].is_device_type_supported(device.deviceType):
                self._logger.error(
                    f"Device type {device.deviceType} not supported by module {device.module}"
                )
                continue

            if status.deviceState ==_Status.RUNNING:
                if not self._is_device_in_list(device, self._connected_devices):
                    self._logger.error(f"Device {device_repr(device)} is not connected")
                    continue
                rc = self._modules[device.module].forward_status(
                    device, status.deviceStatus.statusData
                )
                self._check_forward_status_rc(device.module, rc)
            elif status.deviceState ==_Status.CONNECTING:
                if self._is_device_in_list(device, self._connected_devices):
                    self._logger.error(f"Device {device_repr(device)} is already connected")
                    continue
                self._connect_device(device)
                rc = self._modules[device.module].forward_status(
                    device, status.deviceStatus.statusData
                )
                self._check_forward_status_rc(device.module, rc)
            elif status.deviceState ==_Status.DISCONNECT:
                if not self._is_device_in_list(device, self._connected_devices):
                    self._logger.error(f"Device {device_repr(device)} is not connected")
                    continue
                rc = self._modules[device.module].forward_status(
                    device, status.deviceStatus.statusData
                )
                self._check_forward_status_rc(device.module, rc)
                self._disconnect_device(DisconnectTypes.announced, device)
                self._logger.warning(
                    f"Status announces that device {device.deviceName} was disconnected"
                )

            if len(status.errorMessage) > 0:
                self._logger.error(
                    f"Status for device {device_repr(device)} contains error message"
                )

            status_response = self._create_status_response(status)
            self._mqtt_client.publish(status_response)
            if len(self._connected_devices) == 0:
                    self._logger.warning("All devices have been disconnected, restarting server")
                    raise CommunicationException()

    def _handle_command_response(self, command_response: _CommandResponse) -> None:
        self._logger.info("Received command response")
        self._reset_session_checker_if_session_id_is_ok(command_response.sessionId)

        device_not_connected = (
            command_response.type == _CommandResponse.DEVICE_NOT_CONNECTED
        )
        commands = self._command_checker.acknowledge_and_pop_commands(command_response.messageCounter)
        for command, _ in commands:
            rc = self._modules[command.deviceCommand.device.module].command_ack(
                command.deviceCommand.commandData, command.deviceCommand.device
            )
            self._check_command_ack_rc(command.deviceCommand.device.module, rc)
            if device_not_connected and command.messageCounter == command_response.messageCounter:
                self._disconnect_device(DisconnectTypes.announced, command.deviceCommand.device)
                self._logger.warning(
                    f"Command response announces that device {command.deviceCommand.device.deviceName} was disconnected"
                )

    def _handle_command(self, module_num: int) -> None:
        command_counter = self._command_checker.counter
        result = self._modules_command_threads[module_num].pop_command()
        if not result:
            return
        command, for_device = result
        if not self._is_device_in_list(for_device, self._connected_devices):
            self._logger.warning(
                f"Target device for command returned from module {module_num}'s API is not connected."
                "Command won't be sent"
            )
            return
        self._logger.info(f"Sending Command message, messageCounter: {command_counter}")
        external_command = _external_command(
            self._session_id, command_counter, for_device, command
        )
        if len(external_command.command.deviceCommand.commandData) == 0:
            self._logger.warning(
                f"Command data for device {external_command.command.deviceCommand.device.deviceName} is empty"
            )
        self._command_checker.add_command(external_command.command, True)
        if external_command.command.deviceCommand.device.module != module_num:
            self._logger.warning(
                f"Device id returned from module {module_num}'s API has different module number"
            )
            if self._config.send_invalid_command:
                self._logger.warning("Sending Command message with possibly invalid device")
                self._mqtt_client.publish(external_command)
            else:
                self._logger.warning("The Command will not be sent")
                self._command_checker.acknowledge_and_pop_commands(external_command.command.messageCounter)
        else:
            self._mqtt_client.publish(external_command)

    def _checked_connect_message(self) -> _ExternalClientMsg:
        self._logger.info("Expecting a connect message")
        msg = self._mqtt_client.get_message(timeout=self._config.mqtt_timeout)
        if not msg or not msg.HasField("connect"):
            self._logger.error("Connect message has not been received")
            raise ConnectSequenceException()
        elif not msg.HasField("connect"):
            self._logger.error("Received message is not a connect message")
            raise ConnectSequenceException()
        self._logger.info("Connect message has been received")
        return msg

    def _init_seq_connect(self) -> None:
        msg = self._checked_connect_message()
        self._session_id = msg.connect.sessionId
        devices = msg.connect.devices
        for device in devices:
            if self._is_module_supported(device.module):
                self._log_warning_if_device_not_supported_by_module(device)
                if not self._connect_device(device)==GeneralErrorCodes.OK:
                    self._logger.warning(
                        f"Failed to connect device with module ID={device.module}. Ignored."
                    )
            else:
                self._logger.warning(f"Module (ID={device.module}) not supported, ignoring device")
                self._add_not_connected_device(device)
        self._publish_connect_response(_ConnectResponse.OK)

    def _publish_connect_response(self, connect_response_type: int) -> None:
        self._logger.info(f"Sending Connect respons. Response type: {connect_response_type}")
        msg = _connect_response(self._session_id, connect_response_type)
        self._mqtt_client.publish(msg)

    def _is_module_supported(self, module_id: int) -> bool:
        return module_id in self._modules

    def _init_seq_status(self) -> None:
        device_count = len(self._connected_devices) + len(self._not_connected_devices)
        self._logger.info(f"Expecting {device_count} status messages")
        for k in range(device_count):
            self._logger.info(f"Waiting for status message {k + 1} of {device_count}")
            status_obj = self._get_valid_status()
            status = status_obj.deviceStatus
            device = status.device
            self._log_warning_if_status_from_not_connected_device(device)
            self._check_device_is_in_connecting_state(status_obj)
            self._status_order_checker.check(status_obj)
            self._status_order_checker.get_status()  # Checked status is not needed in Init sequence
            self._log_new_status(status_obj)
            if device not in self._not_connected_devices:
                if status_obj.errorMessage:
                    code = self._modules[device.module].forward_error_message(device, status_obj.errorMessage)
                    if code!=GeneralErrorCodes.OK:
                        self._logger.warning(
                            f"Module '{device.module}': Error occurred in forward_error_message function. Return code: {code}"
                        )
                code = self._modules[device.module].forward_status(
                    device, status.statusData
                )
                self._check_forward_status_rc(device.module, code)
            sent_msg = self._create_status_response(status_obj)
            self._mqtt_client.publish(sent_msg)

    def _get_valid_status(self) -> _Status:
        msg = self._mqtt_client.get_message(timeout=self._config.mqtt_timeout)
        if msg is None or msg == False:
            self._logger.error("Status message has not been received")
            raise ConnectSequenceException
        if not msg.HasField("status"):
            self._logger.error("Received message is not a status message")
            raise ConnectSequenceException
        return msg.status

    def _check_device_is_in_connecting_state(self, device_status: _Status) -> None:
        if device_status.deviceState ==_Status.CONNECTING:
            return
        else:
            self._logger.error(
                f"Expected connecting device (state={_Status.CONNECTING}),"
                f"received {device_status.deviceState}")
            raise ConnectSequenceException

    def _log_warning_if_status_from_not_connected_device(self, device: _Device) -> None:
        if not self._is_device_in_list(device, self._connected_devices):
            self._logger.warning(
                f"Received status from not connected device, unique identificator:"
                f" {device.module}/{device.deviceType}/{device.deviceRole}"
            )

    def _log_new_status(self, status: _Status) -> None:
        info = f"Received Status message, messageCounter: {status.messageCounter}"
        if len(status.errorMessage) > 0:
            info += f" error: {status.errorMessage}"
        self._logger.info(info)

    def _init_seq_command(self) -> None:
        devices_with_no_command = self._connected_devices.copy()
        self._logger.info("Generating and sending commands to all devices")
        for module in self._modules:
            module_commands: list[tuple[bytes, _Device]] = []
            result: tuple | None = ()
            while result is not None:
                result = self._modules_command_threads[module].pop_command()
                if result is not None:
                    command, target_device = result
                    module_commands.append((command, target_device))

            for command, target_device in module_commands:
                if not self._is_device_in_list(target_device, devices_with_no_command
                ) and self._is_device_in_list(target_device, self._connected_devices):
                    self._logger.warning(
                        f"Command for {target_device.deviceName} device was returned from API more than once"
                    )
                elif not self._is_device_in_list(target_device, devices_with_no_command):
                    self._logger.warning(
                        f"Command returned from module {module}'s API is intended for not connected device, command won't be sent"
                    )
                else:
                    command_counter = self._command_checker.counter
                    cmd = _external_command(
                        self._session_id, command_counter, target_device, command
                    )
                    print("Cmd: ", cmd)
                    self._logger.info(f"Sending Command message, messageCounter: {command_counter}")
                    self._mqtt_client.publish(cmd)
                    self._command_checker.add_command(cmd.command, True)
                    try:
                        devices_with_no_command.remove(DevicePy.from_device(target_device))
                    except ValueError:
                        self._logger.error(
                            f"Received command for unexpected device in connect sequence:"
                            f"{target_device.module}/{target_device.deviceType}/{target_device.deviceRole} named as {target_device.deviceName}"
                        )
                        raise ConnectSequenceException()

        for device_py in devices_with_no_command + self._not_connected_devices:
            command_counter = self._command_checker.counter
            device = device_py.to_device()
            cmd = _external_command(self._session_id, command_counter, device)
            self._logger.warning(
                f"No command was returned from API for device {device.deviceName}, sending empty command for this device"
            )
            self._logger.info(f"Sending Command message, messageCounter: {command_counter}")
            self._mqtt_client.publish(cmd)
            self._command_checker.add_command(cmd.command, True)

        device_count = range(len(self._connected_devices) + len(self._not_connected_devices))
        self._logger.info(f"Expecting {len(device_count)} command response messages")

        for iter in device_count:
            self._logger.info(f"Waiting for command response message {iter + 1}/{len(device_count)}")
            received_msg = self._mqtt_client.get_message(timeout=self._config.mqtt_timeout)
            if received_msg is None or received_msg == False:
                self._logger.error("Command response message has not been received")
                raise ConnectSequenceException()
            if not received_msg.HasField("commandResponse"):
                self._logger.error("Received message is not a command response message")
                raise ConnectSequenceException()
            self._logger.info(f"Received Command response message")
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
                    self._check_command_ack_rc(command.deviceCommand.device.module, rc)

    def _is_device_in_list(self, device: _Device, device_list: list[DevicePy]) -> bool:
        return device in device_list

    def _normal_communication(self) -> None:
        self._session_checker.start()
        while True:
            event = self._event_queue.get()
            if event.event == EventType.RECEIVED_MESSAGE:
                received_msg = self._mqtt_client.get_message(timeout=None)
                if received_msg == False:
                    raise CommunicationException()
                elif received_msg is not None:
                    if received_msg.HasField("connect"):
                        self._handle_connect(received_msg.connect.sessionId)

                    elif received_msg.HasField("status"):
                        self._handle_status(received_msg.status)

                    elif received_msg.HasField("commandResponse"):
                        self._handle_command_response(received_msg.commandResponse)
            elif event.event == EventType.MQTT_BROKER_DISCONNECTED:
                raise CommunicationException()
            elif event.event == EventType.TIMEOUT_OCCURRED:
                if event.data == TimeoutType.SESSION_TIMEOUT:
                    raise ClientDisconnectedExc()
                elif event.data == TimeoutType.MESSAGE_TIMEOUT:
                    raise StatusTimeOutExc()
                elif event.data == TimeoutType.COMMAND_TIMEOUT:
                    raise CommandResponseTimeOutExc()
                else:
                    self._logger.error(
                        "Internal error: Received Event TimeoutOccurred without TimeoutType"
                    )
            elif event.event == EventType.COMMAND_AVAILABLE:
                if isinstance(event.data, int):
                    self._handle_command(event.data)
                else:
                    self._logger.error(
                        "Internal error: Received Event CommandAvailable without module number"
                    )

    def _reset_session_checker_if_session_id_is_ok(self, msg_session_id: str) -> None:
        if self._session_id == msg_session_id:
            self._session_checker.reset()

    def _run_init_sequence(self) -> None:
        self._logger.info("Starting the connect sequence")
        self._init_seq_connect()
        self._init_seq_status()
        self._init_seq_command()
        self._event_queue.clear()
        self._logger.info("Connect sequence has finished succesfully")

    @staticmethod
    def _remove_device_priority(device: _Device) -> None:
        """Set priority to zero - the external server must ignore the priority."""
        device.priority = 0