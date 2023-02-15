import logging
import time
from collections import defaultdict
from queue import Empty, Queue

import external_server.protobuf.ExternalProtocol_pb2 as external_protocol
from external_server.checker.ack_checker import AcknowledgmentChecker
from external_server.checker.checker import Checker
from external_server.checker.msg_checker import MessagesChecker
from external_server.exceptions import (
    ConnectSequenceException,
    NormalCommunicationException,
)
from external_server.modules import CarAccessoryCreator, MissionCreator
from external_server.modules.module_type import ModuleType
from external_server.mqtt_client import MqttClient
from external_server.utils import check_file_exists


class ExternalServer:
    # check status message order, use OrderChecker
    def __init__(self, ip_address: str, port: int) -> None:
        self.ip_address = ip_address
        self.port = port
        self.session_id = ""
        self.msg_checker = MessagesChecker()
        self.command_response_checker = AcknowledgmentChecker()
        self.connected_devices = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: False)))
        self.msg_creator = {
            ModuleType.MISSION_MODULE.value: MissionCreator(),
            ModuleType.CAR_ACCESSORY_MODULE.value: CarAccessoryCreator(),
        }
        self.mqtt_client = MqttClient()

    def set_tls(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        "Set tls security to mqtt client"
        if not check_file_exists(ca_certs):
            raise FileNotFoundError(ca_certs)
        if not check_file_exists(certfile):
            raise FileNotFoundError(certfile)
        if not check_file_exists(keyfile):
            raise FileNotFoundError(keyfile)
        self.mqtt_client.set_tls(ca_certs, certfile, keyfile)

    def start(self) -> None:
        self.mqtt_client.init_mqtt_client()
        while True:
            try:
                if not self.mqtt_client.is_connected:
                    self.mqtt_client.connect(self.ip_address, self.port)
                    self.mqtt_client.start()
                self._init_sequence()
                self._normal_communication()
            except ConnectSequenceException:
                logging.error("Connect sequence failed")
            except ConnectionRefusedError:
                logging.error("Unable to connect, trying again")
                time.sleep(0.5)
            except Empty:  # if 30 seconds any message has not been received
                logging.error("Client timed out")
            except NormalCommunicationException as nc_exc:
                logging.error(nc_exc)
            finally:
                self.command_response_checker.reset()
                self.msg_checker.stop()

    def _init_sequence(self) -> None:
        devices_num = self._init_seq_connect()
        received_statuses = self._init_seq_status(devices_num)
        self._init_seq_command(devices_num, received_statuses)
        logging.info("Connect sequence has been succesfully finished")

    def _init_seq_connect(self) -> int:
        received_msg = self.mqtt_client.get()
        if isinstance(received_msg, bool):
            self.mqtt_client.stop()
            raise ConnectSequenceException()
        if not received_msg.HasField("connect"):
            logging.error("Connect message has been expected")
            raise ConnectSequenceException()
        logging.info("Connect message has been received")
        self.session_id = received_msg.connect.sessionId

        devices = received_msg.connect.devices
        for device in devices:
            self.connected_devices[device.module][device.deviceType][device.deviceRole] = True

        sent_msg = self._create_connect_response(self.session_id, external_protocol.ConnectResponse.Type.OK)
        self.mqtt_client.publish(sent_msg)
        return len(devices)

    def _init_seq_status(self, devices_num: int) -> Queue:
        received_statuses = Queue()
        for _ in range(devices_num):
            status_msg = self.mqtt_client.get(timeout=Checker.TIMEOUT)
            if not status_msg.HasField("status"):
                logging.error("Status message has been expected")
                raise ConnectSequenceException()

            device = status_msg.status.deviceStatus.device
            if not self._check_device_is_connected(device):
                logging.error(
                    f"Recieved status from not connected device, unique identificator:\
                                {device.module}/{device.deviceType}/{device.deviceRole}"
                )
                raise ConnectSequenceException()
            if not self._check_status_device_state(status_msg, external_protocol.Status.DeviceState.CONNECTING):
                logging.error(
                    f"Status device state is different. actual: {status_msg.status.deviceState}\
                                expected: {external_protocol.Status.DeviceState.CONNECTING}"
                )
                raise ConnectSequenceException()

            logging.info(
                f"Received Status message message, messageCounter: {status_msg.status.messageCounter} \
                           error: {status_msg.status.errorMessage}"
            )
            received_statuses.put(status_msg)
            sent_msg = self._create_status_response(status_msg)
            self.mqtt_client.publish(sent_msg)
        return received_statuses

    def _init_seq_command(self, devices_num: int, received_statuses: Queue) -> None:
        for _ in range(devices_num):
            status_message = received_statuses.get()
            sent_msg = self._create_command(status_message)
            self.mqtt_client.publish(sent_msg)

        for _ in range(devices_num):
            received_msg = self.mqtt_client.get(timeout=Checker.TIMEOUT)
            if not received_msg.HasField("commandResponse"):
                logging.error("Command response message has been expected")
                raise ConnectSequenceException()
            self.command_response_checker.remove_ack(received_msg.commandResponse.messageCounter)

    def _normal_communication(self) -> None:
        self.msg_checker.start()
        while True:
            received_msg = self.mqtt_client.get(timeout=Checker.TIMEOUT)
            if isinstance(received_msg, bool):
                self.mqtt_client.stop()
                raise NormalCommunicationException("Unexpected disconnection")
            if self.command_response_checker.check_time_out():
                raise NormalCommunicationException("Command response message has not been recieved in time")
            if self.msg_checker.check_time_out():
                raise NormalCommunicationException("Connected session has been timed out")

            if received_msg.HasField("connect"):
                logging.warning("Received Connect message")
                if self._check_session_id(received_msg.connect.sessionId):
                    raise NormalCommunicationException("Connected session sent Connect message")
                sent_msg = self._create_connect_response(
                    received_msg.connect.sessionId,
                    external_protocol.ConnectResponse.Type.ALREADY_LOGGED,
                )
                self.mqtt_client.publish(sent_msg)

            elif received_msg.HasField("status"):
                logging.info(f"Received Status message message, messageCounter: {received_msg.status.messageCounter}")
                self._reset_msg_checker_if_session_id_is_ok(received_msg.status.sessionId)
                # check status order
                match received_msg.status.deviceState:
                    case external_protocol.Status.DeviceState.RUNNING:
                        device = received_msg.status.deviceStatus.device
                        if not self._check_device_is_connected(device):
                            logging.error(
                                f"Device {device.module}/{device.deviceType}/{device.deviceRole} \
                                            is not connected"
                            )

                        sent_msg = self._create_status_response(received_msg)
                        self.mqtt_client.publish(sent_msg)

                        sent_msg = self._create_command(received_msg)
                        self.mqtt_client.publish(sent_msg)

                    case external_protocol.Status.DeviceState.CONNECTING:
                        device = received_msg.status.deviceStatus.device
                        if self._check_device_is_connected(device):
                            logging.error(
                                f"Device {device.module}/{device.deviceType}/{device.deviceRole} \
                                            is already connected"
                            )

                        sent_msg = self._create_status_response(received_msg)
                        self.mqtt_client.publish(sent_msg)

                        sent_msg = self._create_command(received_msg)
                        self.mqtt_client.publish(sent_msg)

                        device = received_msg.status.deviceStatus.device
                        self.connected_devices[device.module][device.deviceType][device.deviceRole] = True

                    case external_protocol.Status.DeviceState.DISCONNECT:
                        device = received_msg.status.deviceStatus.device
                        if not self._check_device_is_connected(device):
                            logging.error(
                                f"Device {device.module}/{device.deviceType}/{device.deviceRole} \
                                            is not connected"
                            )

                        sent_msg = self._create_status_response(received_msg)
                        self.mqtt_client.publish(sent_msg)
                        device = received_msg.status.deviceStatus.device
                        self.connected_devices[device.module][device.deviceType][device.deviceRole] = False

            elif received_msg.HasField("commandResponse"):
                self._reset_msg_checker_if_session_id_is_ok(received_msg.commandResponse.sessionId)
                self.command_response_checker.remove_ack(received_msg.commandResponse.messageCounter)

    def stop(self) -> None:
        logging.info("Server stopped")
        self.mqtt_client.stop()
        self.command_response_checker.reset()
        self.msg_checker.stop()

    def _create_connect_response(self, session_id: str, connect_response_type: int) -> external_protocol.ExternalServer:
        connect_response = self.msg_creator[ModuleType.MISSION_MODULE.value].create_connect_response(
            session_id, connect_response_type
        )
        sent_msg = external_protocol.ExternalServer()
        sent_msg.connectResponse.CopyFrom(connect_response)
        logging.warning(f"Sending Connect response message, response type: {connect_response_type}")
        return sent_msg

    def _create_status_response(self, status: external_protocol.Status) -> external_protocol.ExternalServer:
        module = status.status.deviceStatus.device.module
        if module not in self.msg_creator:
            logging.error(f"Module {module} is not supported")
            raise ConnectSequenceException()
        sent_msg = external_protocol.ExternalServer()
        sent_msg.statusResponse.CopyFrom(
            self.msg_creator[module].create_status_response(status.status.sessionId, status.status.messageCounter)
        )
        logging.info(f"Sending Status response message, messageCounter: {status.status.messageCounter}")
        return sent_msg

    def _create_command(self, status: external_protocol.Status) -> external_protocol.ExternalServer:
        module = status.status.deviceStatus.device.module
        command_counter = self.command_response_checker.add_ack()
        sent_msg = external_protocol.ExternalServer()
        sent_msg.command.CopyFrom(
            self.msg_creator[module].create_external_command(
                status.status.sessionId, command_counter, status.status.deviceStatus
            )
        )
        logging.info(f"Sending Command message, messageCounter: {command_counter}")
        return sent_msg

    def _check_device_is_connected(self, device) -> bool:
        return self.connected_devices[device.module][device.deviceType][device.deviceRole]

    def _check_status_device_state(
        self,
        status: external_protocol.ExternalClient,
        device_state: external_protocol.Status.DeviceState,
    ) -> bool:
        return status.status.deviceState == device_state

    def _check_session_id(self, msg_session_id: str) -> bool:
        return self.session_id == msg_session_id

    def _reset_msg_checker_if_session_id_is_ok(self, msg_session_id: str) -> None:
        if self._check_session_id(msg_session_id):
            self.msg_checker.reset()
